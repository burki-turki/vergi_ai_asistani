"""Sweep environment guard -- Pilot Readiness Step 3 (Runner / Environment /
Skip Reporting), Fable FINAL contract sections H.1-H.3, S.2.

ROLE
----
This is the COMMITTED SOURCE of the fail-closed audit-hook guard that
``scripts/run_ui_tests.py`` arms in every test child process. The runner
copies these bytes VERBATIM to ``<run>/guard/sitecustomize.py`` inside its
private run directory and starts every child with ``PYTHONPATH=<run>/guard``
(+ ``PYTHONNOUSERSITE=1``). CPython's ``site`` module imports a module named
``sitecustomize`` at interpreter start-up, so the copy self-installs in every
child (``__name__ == "sitecustomize"`` branch at the bottom of this file).

The repository itself NEVER contains a file named ``sitecustomize.py``: a
committed one would auto-inject into every ``python scripts/<tool>.py``
invocation (``scripts/`` becomes ``sys.path[0]``) and into the runner.

IMPORT SAFETY
-------------
Importing this module as ``scripts.sweep_env_guard`` (or ``sweep_env_guard``)
has NO side effects: no hook is installed, no file is written. ``install()``
must be called explicitly. Only the ``sitecustomize`` name triggers
self-installation (from the environment variables the runner sets).

This module is stdlib-only and never imports anything from ``src``, ``ui``
or ``scripts``.

WHAT IS BLOCKED (``PermissionError`` raised BEFORE the operation happens)
----------------------------------------------------------------------
* ``open`` audit event (built-in ``open``, ``io.open``, ``os.open``,
  ``pathlib`` all emit it) when the target's basename is exactly ``.env`` or
  starts with ``.env.`` (the ``.env*`` family: ``.env``, ``.env.local``,
  ``.env.production`` ...). ``.envx`` / ``.environment`` are NOT affected.
* ``socket.connect`` / ``socket.connect_ex`` (CPython emits ``socket.connect``
  for both; the guard matches every event name that starts with
  ``socket.connect``), ``socket.sendto``, ``socket.sendmsg`` when the
  destination is not loopback (``127.0.0.0/8``, ``::1``, ``localhost``,
  IPv4-mapped loopback). AF_UNIX addresses are local and allowed.
* ``socket.getaddrinfo`` / ``socket.gethostbyname`` /
  ``socket.gethostbyaddr`` / ``socket.getnameinfo`` when the host is not
  loopback / ``localhost`` -- blocked before the OS resolver is reached.

WHAT IS RECORDED (never blocked)
--------------------------------
* ``GUARD_ARMED`` once per process at installation.
* ``POPEN`` for every ``subprocess.Popen`` (executable, argv, cwd -- NEVER
  the environment mapping, which may carry secrets).
* ``ENV_OPEN_BLOCKED`` / ``NET_BLOCKED`` for blocked operations (basename or
  a short hash only -- no full path, no address).

LEDGER LINE FORMATS (tab-separated, one line, UTF-8)
---------------------------------------------------
GUARD_ARMED\t<pid>\t<ppid>\t<run_id>\t<sys.executable>\t<argv-json>
POPEN\t<pid>\t<run_id>\t<executable-json>\t<argv-json>\t<cwd-json>
ENV_OPEN_BLOCKED\t<pid>\t<run_id>\t<basename>\t<sha256(parent dir)[:16]>
NET_BLOCKED\t<pid>\t<run_id>\t<event>\t<sha256(address repr)[:16]>

KNOWN LIMITS (disclosed, not claimed otherwise)
----------------------------------------------
* libpq (psycopg) opens its sockets in C: invisible to audit hooks. The
  runner compensates with a server-side ``inet_server_addr()`` loopback
  proof and a syntactic ``PGHOST`` restriction.
* Subprocesses with their own network stacks (curl, powershell, ...) are not
  blocked here; the runner classifies their ``POPEN`` records post-run.
* A differently-named link to ``.env`` (``x.txt -> .env``) is not caught
  (basename check) -- an OS-ACL matter (Row 19D), not a guard matter.
* Python children started with ``-I`` / ``-S`` / ``-E`` ignore PYTHONPATH
  and are therefore NOT armed; the runner detects this through the
  ``GUARD_ARMED`` / ``POPEN`` accounting (fail-closed).
"""

import hashlib
import json
import os
import sys
import threading

GUARD_VERSION = "1"

LEDGER_ENV = "VERGI_UI_TEST_SWEEP_GUARD_LEDGER"
RUN_ID_ENV = "VERGI_UI_TEST_SWEEP_RUN_ID"
PARENT_PID_ENV = "VERGI_UI_TEST_SWEEP_PARENT_PID"

_STATE_ATTR = "_vergi_ui_test_sweep_guard_state"
_MAX_LINE_CHARS = 8000

_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})


class _GuardState:
    __slots__ = ("ledger_path", "run_id", "lock", "reentrant", "installed")

    def __init__(self, ledger_path, run_id):
        self.ledger_path = ledger_path
        self.run_id = run_id
        self.lock = threading.Lock()
        self.reentrant = threading.local()
        self.installed = True


# ---------------------------------------------------------------------------
# Pure classification helpers (unit-testable without installing anything)
# ---------------------------------------------------------------------------

def _to_text(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive
            return repr(value)
    if isinstance(value, str):
        return value
    try:
        return os.fspath(value)
    except TypeError:
        return str(value)


def basename_of(path_value):
    """Return the final path component of a str/bytes/PathLike value.

    Both ``\\`` and ``/`` are treated as separators regardless of platform
    so that an alias path spelled with either separator is classified the
    same way. Integers (file descriptors) yield ``""``.
    """
    if isinstance(path_value, int):
        return ""
    text = _to_text(path_value)
    text = text.replace("\\", "/")
    # Windows drive-relative spelling ("C:.env" = ".env" in the drive's
    # current directory): the drive designator is not part of the name.
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha() and "/" not in text[:2]:
        text = text[2:]
    while text.endswith("/") and len(text) > 1:
        text = text[:-1]
    return text.rsplit("/", 1)[-1]


def normalize_windows_file_name(name):
    """Fold a final path component the way the Win32 namespace does before
    it is compared against the ``.env*`` family (B1, fail-closed):

    * an NTFS alternate data stream / drive remnant (``.env:stream``,
      ``.env::$DATA``) addresses the SAME file -- only the part before the
      first ``:`` is the file name;
    * Win32 strips trailing dots and spaces (``.env.``, ``.env ``,
      ``.env. .`` all open ``.env``);
    * NTFS is case-insensitive (``.ENV``, ``.Env.local``).

    The folding is applied on every platform: on POSIX ``.ENV`` or
    ``.env.`` would be distinct files, and treating them as protected is
    the fail-closed direction. 8.3 short names (``ENV~1``) cannot be
    classified from a basename and remain an OS-ACL matter (W12 class).
    """
    text = name
    if ":" in text:
        text = text.split(":", 1)[0]
    text = text.rstrip(". ")
    return text.lower()


def is_env_file_name(name):
    """True for the ``.env*`` family after Windows name folding: exactly
    ``.env`` or ``.env.<anything>`` (case-insensitive, trailing dots/spaces
    and NTFS stream suffixes folded). ``.envx``/``.environment`` are not
    members."""
    folded = normalize_windows_file_name(name)
    return folded == ".env" or folded.startswith(".env.")


def _strip_ipv6_zone(host):
    if "%" in host:
        return host.split("%", 1)[0]
    return host


def is_loopback_host(host):
    """True when ``host`` designates the local loopback interface.

    Accepts ``localhost``, any ``127.x.y.z`` IPv4 address, ``::1`` (with or
    without a zone id), the IPv4-mapped form ``::ffff:127.x.y.z`` and the
    empty string (which the socket module maps to the local host for
    connect on some platforms). Everything else -- including any other
    hostname -- is NOT loopback (fail-closed).
    """
    if host is None:
        return False
    text = _to_text(host).strip()
    if text == "":
        return True
    lowered = _strip_ipv6_zone(text.lower())
    if lowered in _LOOPBACK_NAMES:
        return True
    if lowered.startswith("::ffff:"):
        lowered = lowered[len("::ffff:"):]
    parts = lowered.split(".")
    if len(parts) == 4 and parts[0] == "127":
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            return False
    return False


def address_is_loopback(address):
    """Classify a socket address object as passed to connect/sendto/sendmsg.

    * tuple -> first element is the host (AF_INET / AF_INET6)
    * str / bytes -> AF_UNIX path (local by construction) -> allowed
    * anything else -> not loopback (fail-closed)
    """
    if isinstance(address, tuple):
        if not address:
            return False
        return is_loopback_host(address[0])
    if isinstance(address, (str, bytes)):
        return True
    return False


def _short_hash(text):
    return hashlib.sha256(_to_text(text).encode("utf-8", "replace")).hexdigest()[:16]


def _json_compact(value):
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        return json.dumps(repr(value), ensure_ascii=True)


def _argv_to_list(args):
    if args is None:
        return []
    if isinstance(args, (str, bytes)) or not hasattr(args, "__iter__"):
        return [_to_text(args)]
    return [_to_text(a) for a in args]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def _append_ledger(state, fields):
    """Append one tab-separated line with a single low-level write.

    Failures are swallowed: the guard must never make a test crash because
    of ledger I/O -- the runner detects a missing GUARD_ARMED line and
    fails closed on its side.
    """
    if state.ledger_path is None:
        return
    if getattr(state.reentrant, "active", False):
        return
    state.reentrant.active = True
    try:
        line = "\t".join(str(f) for f in fields)
        if len(line) > _MAX_LINE_CHARS:
            line = line[:_MAX_LINE_CHARS] + "\t<TRUNCATED>"
        data = (line + "\n").encode("utf-8", "replace")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        with state.lock:
            fd = os.open(state.ledger_path, flags, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
    except Exception:
        pass
    finally:
        state.reentrant.active = False


# ---------------------------------------------------------------------------
# Audit hook
# ---------------------------------------------------------------------------

def _make_hook(state):
    def hook(event, args):
        if event == "open":
            try:
                target = args[0] if args else None
            except Exception:
                return
            name = basename_of(target)
            if is_env_file_name(name):
                parent = ""
                try:
                    text = _to_text(target).replace("\\", "/")
                    parent = text.rsplit("/", 1)[0] if "/" in text else ""
                except Exception:
                    parent = ""
                _append_ledger(state, ("ENV_OPEN_BLOCKED", os.getpid(), state.run_id, name, _short_hash(parent)))
                raise PermissionError(
                    "sweep_env_guard: opening a .env* file is forbidden during the test sweep (%s)" % name
                )
            return
        if event.startswith("socket.connect") or event in ("socket.sendto", "socket.sendmsg"):
            try:
                address = args[1] if len(args) > 1 else None
            except Exception:
                address = None
            if address is None and event in ("socket.sendto", "socket.sendmsg"):
                # sendmsg without an explicit address uses the connected peer,
                # which was itself subject to the connect check.
                return
            if not address_is_loopback(address):
                _append_ledger(state, ("NET_BLOCKED", os.getpid(), state.run_id, event, _short_hash(repr(address))))
                raise PermissionError(
                    "sweep_env_guard: non-loopback network access is forbidden during the test sweep (%s)" % event
                )
            return
        if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"):
            try:
                if event == "socket.getnameinfo":
                    sockaddr = args[0] if args else None
                    host = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else sockaddr
                else:
                    host = args[0] if args else None
            except Exception:
                host = None
            if host is None:
                # getaddrinfo(None, port) resolves the local host.
                return
            if not is_loopback_host(host):
                _append_ledger(state, ("NET_BLOCKED", os.getpid(), state.run_id, event, _short_hash(repr(host))))
                raise PermissionError(
                    "sweep_env_guard: non-loopback name resolution is forbidden during the test sweep (%s)" % event
                )
            return
        if event == "subprocess.Popen":
            try:
                executable = args[0] if len(args) > 0 else None
                argv = args[1] if len(args) > 1 else None
                cwd = args[2] if len(args) > 2 else None
            except Exception:
                executable, argv, cwd = None, None, None
            # args[3] is the environment mapping: deliberately NOT recorded.
            _append_ledger(
                state,
                (
                    "POPEN",
                    os.getpid(),
                    state.run_id,
                    _json_compact(_to_text(executable) if executable is not None else None),
                    _json_compact(_argv_to_list(argv)),
                    _json_compact(_to_text(cwd) if cwd is not None else None),
                ),
            )
            return

    return hook


def is_installed():
    return getattr(sys, _STATE_ATTR, None) is not None


def install(ledger_path=None, run_id=None):
    """Install the guard in the current process (idempotent).

    Returns True when the hook was installed by this call, False when a
    guard was already active (the existing one is left untouched so that
    exactly one GUARD_ARMED line is written per process).
    """
    if is_installed():
        return False
    state = _GuardState(ledger_path, run_id if run_id is not None else "")
    setattr(sys, _STATE_ATTR, state)
    sys.addaudithook(_make_hook(state))
    try:
        argv = list(getattr(sys, "argv", []) or [])
    except Exception:
        argv = []
    try:
        ppid = os.getppid()
    except Exception:
        ppid = -1
    _append_ledger(
        state,
        (
            "GUARD_ARMED",
            os.getpid(),
            ppid,
            state.run_id,
            _to_text(getattr(sys, "executable", "") or ""),
            _json_compact([_to_text(a) for a in argv]),
        ),
    )
    return True


def _install_from_environment():
    ledger = os.environ.get(LEDGER_ENV) or None
    run_id = os.environ.get(RUN_ID_ENV) or ""
    install(ledger, run_id)


if __name__ == "sitecustomize":
    _install_from_environment()
