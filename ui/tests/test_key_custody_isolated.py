"""Isolated Row 19D Slice 1 key-custody tests.

Run with: python -m ui.tests.test_key_custody_isolated
"""

from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import csv
import inspect
import importlib
import io
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from urllib.parse import urlencode
from pathlib import Path


UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


opened_env_files: list[str] = []


def _audit(event, args):
    if event == "open" and args:
        try:
            path = os.fspath(args[0])
        except TypeError:
            return
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if Path(path).name == ".env":
            opened_env_files.append(path)


sys.addaudithook(_audit)

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect_raises(exc_type, function, label):
    try:
        function()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"unexpected exception: {type(error).__name__}: {error}")
    else:
        check(label, False, "no exception raised")


def _encoded(length: int) -> str:
    return base64.b64encode(secrets.token_bytes(length)).decode("ascii")


def _valid_document(key_id="local-a"):
    return {
        "version": 1,
        "current_key_id": key_id,
        "keys": {key_id: _encoded(32)},
        "server_pepper": _encoded(32),
    }


def _write_raw_secure(path: Path, raw: bytes) -> None:
    from ui.services import key_custody as custody
    resolved = custody.resolve_local_key_path(path)
    with custody._trusted_namespace(resolved, create=True):
        custody._publish_payload(resolved, raw, replace=False)


def _write_document(path: Path, document) -> None:
    _write_raw_secure(path, json.dumps(document).encode("utf-8"))


def _icacls(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["icacls", str(path), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _acl_is_private(path: Path) -> bool:
    text = _icacls(path)
    forbidden = ("CodexSandboxUsers", "Authenticated Users", "Everyone", "BUILTIN\\Users", "(I)")
    return (
        all(value.casefold() not in text.casefold() for value in forbidden)
        and "SYSTEM" in text
        and "Administrators" in text
        and os.environ.get("USERNAME", "") in text
    )


def _grant_inheritable_users(path: Path, current_sid: str) -> None:
    _icacls(path, "/inheritance:r")
    _icacls(
        path,
        "/grant:r",
        f"*{current_sid}:(OI)(CI)(F)",
        "*S-1-5-18:(OI)(CI)(F)",
        "*S-1-5-32-544:(OI)(CI)(F)",
        "*S-1-5-32-545:(OI)(CI)(RX)",
    )


def _make_junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"junction creation failed: {result.stdout}")


def _wait_for(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def _worker_process(operation: str, root: Path, signal: Path | None = None, release: Path | None = None):
    script = r'''
import os, sys, time
from pathlib import Path
from scripts import key_custody_admin as admin
operation, root, signal, release = sys.argv[1:]
os.environ["LOCALAPPDATA"] = root
os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
if signal:
    original = admin.secrets.token_bytes
    fired = False
    def delayed(count):
        global fired
        if not fired:
            fired = True
            Path(signal).write_text("locked", encoding="ascii")
            deadline = time.monotonic() + 15
            while not Path(release).exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("release timeout")
                time.sleep(0.01)
        return original(count)
    admin.secrets.token_bytes = delayed
sys.exit(admin.main([operation]))
'''
    return subprocess.Popen(
        [sys.executable, "-B", "-c", script, operation, str(root), str(signal or ""), str(release or "")],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )


class _SqlRecorder:
    def __init__(self, row):
        self.row = row
        self.consumed = False
        self.session_inserts = 0
        self._pending_consumed = False
        self.last_sql = ""

    @contextlib.contextmanager
    def transaction(self):
        before = self.consumed
        self._pending_consumed = self.consumed
        try:
            yield self
        except BaseException:
            self.consumed = before
            raise
        else:
            self.consumed = self._pending_consumed

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _parameters=None):
        self.last_sql = " ".join(sql.split()).lower()
        if self.last_sql.startswith("update iam.oidc_login_transactions"):
            self._pending_consumed = True
        if self.last_sql.startswith("insert into iam.sessions"):
            self.session_inserts += 1

    def fetchone(self):
        if "from iam.oidc_login_transactions" in self.last_sql:
            return self.row
        return None


def _callback_request(state: str):
    from starlette.requests import Request
    query = urlencode({"code": "synthetic-code", "state": state}).encode("ascii")
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/auth/callback", "raw_path": b"/auth/callback",
        "query_string": query, "headers": [], "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8000), "root_path": "",
    })


original_local_app_data = os.environ.get("LOCALAPPDATA")
original_provider_kind = os.environ.get("VERGI_KEY_PROVIDER_KIND")

try:
    with tempfile.TemporaryDirectory(prefix="row19d_key_custody_") as temp_name:
        external_root = Path(temp_name).resolve()
        os.environ["LOCALAPPDATA"] = str(external_root)
        os.environ.pop("VERGI_KEY_PROVIDER_KIND", None)

        from scripts import key_custody_admin as admin
        from ui import auth_routes
        from ui.services import key_custody as kc
        from ui.services import session_store
        from ui.services import transient_secrets as ts

        path = kc.resolve_local_key_path()
        check("provider-module import does not create custody material", not path.exists())
        check("resolved key path is outside the repository", REPO_ROOT not in path.parents)
        expect_raises(
            kc.KeyCustodyConfigurationError,
            lambda: kc.resolve_local_key_path(REPO_ROOT / "local_keys.json"),
            "repository-contained custody path is rejected",
        )

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            init_rc = admin.main(["initialize"])
        init_output = stdout.getvalue() + stderr.getvalue()
        check("operator initialization succeeds", init_rc == 0 and path.is_file())
        check("operator initialization identifies destination and key id", str(path) in init_output and "current_key_id=" in init_output)

        document_after_init = json.loads(path.read_text(encoding="utf-8"))
        encoded_secrets = list(document_after_init["keys"].values()) + [document_after_init["server_pepper"]]
        check("operator output contains no raw key or pepper material", all(value not in init_output for value in encoded_secrets))
        expect_raises(FileExistsError, admin.initialize_local_key_file, "initialization refuses to overwrite an existing file")

        os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
        provider_a = kc.get_configured_key_provider()
        key_a_id = provider_a.current_key_id()
        plaintext = secrets.token_bytes(97)
        aad = secrets.token_bytes(31)
        ciphertext_a = ts.encrypt_transient_secret(plaintext, key_provider=provider_a, associated_data=aad)
        check(
            "encrypt/decrypt is byte-for-byte exact",
            ts.decrypt_transient_secret(ciphertext_a, key_provider=provider_a, associated_data=aad) == plaintext,
        )
        expect_raises(ts.UnknownKeyError, lambda: provider_a.get_key("local-unknown"), "unknown key raises UnknownKeyError")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            key_rotation_rc = admin.main(["rotate-key"])
        key_rotation_output = stdout.getvalue()
        document_after_key_rotation = json.loads(path.read_text(encoding="utf-8"))
        key_b_id = document_after_key_rotation["current_key_id"]
        provider_b = kc.get_configured_key_provider()
        ciphertext_b = ts.encrypt_transient_secret(plaintext, key_provider=provider_b, associated_data=aad)
        check("operator AES-key rotation succeeds and changes the current key id", key_rotation_rc == 0 and key_b_id != key_a_id)
        check("operator AES-key rotation identifies its path, key id, and preservation behavior", str(path) in key_rotation_output and key_b_id in key_rotation_output and "previous keys preserved" in key_rotation_output)
        check("operator AES-key rotation output contains no raw key material", all(value not in key_rotation_output for value in document_after_key_rotation["keys"].values()))
        check("old ciphertext remains decryptable after A-to-B rotation", ts.decrypt_transient_secret(ciphertext_a, key_provider=provider_b, associated_data=aad) == plaintext)
        check("new ciphertext uses rotated key B", ciphertext_b.key_id == key_b_id)
        check("restart persistence loads the same current key", kc.LocalFileKeyProvider().current_key_id() == key_b_id)

        corrupted = ts.EncryptedSecret(
            ciphertext=ciphertext_b.ciphertext[:-1] + bytes([ciphertext_b.ciphertext[-1] ^ 1]),
            nonce=ciphertext_b.nonce,
            key_id=ciphertext_b.key_id,
            alg=ciphertext_b.alg,
        )
        expect_raises(
            ts.DecryptionFailedError,
            lambda: ts.decrypt_transient_secret(corrupted, key_provider=provider_b, associated_data=aad),
            "corrupt ciphertext raises DecryptionFailedError",
        )

        token_hash = secrets.token_hex(32)
        pepper_before = kc.get_configured_server_pepper()
        csrf_before = session_store.derive_csrf_secret(token_hash, server_pepper=pepper_before)
        csrf_after_restart = session_store.derive_csrf_secret(
            token_hash, server_pepper=kc.get_configured_server_pepper()
        )
        check("CSRF derivation is identical after restart with the same pepper and token hash", csrf_before == csrf_after_restart)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            pepper_rc = admin.main(["rotate-pepper"])
        pepper_output = stdout.getvalue()
        pepper_after = kc.get_configured_server_pepper()
        csrf_after_rotation = session_store.derive_csrf_secret(token_hash, server_pepper=pepper_after)
        check("separate pepper rotation succeeds without changing current AES key", pepper_rc == 0 and kc.LocalFileKeyProvider().current_key_id() == key_b_id)
        check("pepper mismatch changes the CSRF derivation", pepper_before != pepper_after and csrf_before != csrf_after_rotation)
        check("pepper rotation clearly warns about invalidated CSRF derivations", "WARNING" in pepper_output and "invalidates" in pepper_output and "CSRF" in pepper_output)
        check("pepper rotation output contains no secret material", document_after_init["server_pepper"] not in pepper_output)

        for value, label in [
            (None, "unset provider kind fails closed"),
            ("", "empty provider kind fails closed"),
            ("unknown", "unknown provider kind fails closed"),
        ]:
            if value is None:
                os.environ.pop("VERGI_KEY_PROVIDER_KIND", None)
            else:
                os.environ["VERGI_KEY_PROVIDER_KIND"] = value
            expect_raises(kc.KeyCustodyConfigurationError, kc.get_configured_key_provider, label)
            expect_raises(kc.KeyCustodyConfigurationError, kc.get_configured_server_pepper, label + " for pepper")

        os.environ["VERGI_KEY_PROVIDER_KIND"] = "kms"
        expect_raises(kc.KmsProviderNotImplementedError, kc.get_configured_key_provider, "kms provider selection fails closed as not implemented in Slice 1")
        expect_raises(kc.KmsProviderNotImplementedError, kc.get_configured_server_pepper, "kms pepper selection fails closed as not implemented in Slice 1")

        from ui.services import azure_key_vault_custody as azure_custody

        class _AzureSecret:
            value = json.dumps(_valid_document("azure-a"))
            properties = type("_Properties", (), {"version": "vault-v1"})()

        class _AzureClient:
            def __init__(self):
                self.calls = 0

            def get_secret(self, name, **kwargs):
                self.calls += 1
                return _AzureSecret()

        azure_client = _AzureClient()
        azure_env = {
            "VERGI_AZURE_KEY_VAULT_URL": "https://unit.vault.azure.net",
            "VERGI_AZURE_KEY_VAULT_SECRET_NAME": "custody",
        }
        for name, value in azure_env.items():
            os.environ[name] = value
        os.environ.pop("VERGI_AZURE_CREDENTIAL_KIND", None)
        os.environ["VERGI_KEY_PROVIDER_KIND"] = "azure_key_vault_secret"
        azure_custody._reset_azure_custody_manager_for_tests(client_factory=lambda _config: azure_client)
        azure_provider = kc.get_configured_key_provider()
        azure_pepper = kc.get_configured_server_pepper()
        check(
            "explicit azure selector dispatches key and pepper through one shared manager snapshot",
            azure_provider._snapshot is azure_custody.get_azure_custody_manager()._snapshot
            and azure_pepper == azure_provider._snapshot.server_pepper
            and azure_client.calls == 1,
        )
        azure_custody._reset_azure_custody_manager_for_tests()
        for name in azure_env:
            os.environ.pop(name, None)

        os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
        os.environ["VERGI_DEPLOYMENT_MODE"] = "production"
        check(
            "VERGI_DEPLOYMENT_MODE does not become a selector and local_file remains backward compatible",
            isinstance(kc.get_configured_key_provider(), kc.LocalFileKeyProvider),
        )
        os.environ.pop("VERGI_DEPLOYMENT_MODE", None)

        validation_dir = external_root / "validation"
        missing_path = validation_dir / "missing.json"
        expect_raises(kc.KeyCustodyProviderUnavailableError, lambda: kc.LocalFileKeyProvider(missing_path), "missing local custody file fails closed")

        malformed_path = validation_dir / "malformed.json"
        _write_raw_secure(malformed_path, b"{not-json")
        expect_raises(kc.KeyCustodyDocumentError, lambda: kc.LocalFileKeyProvider(malformed_path), "malformed JSON fails closed")

        raw_cases = [
            (b"[]", "non-object document is rejected"),
            (b'{"version":1,"version":1,"current_key_id":"local-a","keys":{},"server_pepper":"AA=="}', "duplicate top-level fields are rejected"),
            (b'{"version":1,"current_key_id":"local-a","keys":{"local-a":"AA==","local-a":"AA=="},"server_pepper":"AA=="}', "duplicate key fields are rejected"),
        ]
        for index, (raw, label) in enumerate(raw_cases):
            case_path = validation_dir / f"raw-{index}.json"
            _write_raw_secure(case_path, raw)
            expect_raises(kc.KeyCustodyDocumentError, lambda p=case_path: kc.LocalFileKeyProvider(p), label)

        structural_cases = []
        doc = _valid_document(); doc["extra"] = "value"; structural_cases.append((doc, "unexpected structural field is rejected"))
        doc = _valid_document(); doc["version"] = True; structural_cases.append((doc, "boolean version does not satisfy integer validation"))
        doc = _valid_document(); doc["version"] = 2; structural_cases.append((doc, "wrong document version is rejected"))
        doc = _valid_document(); doc["keys"] = []; structural_cases.append((doc, "non-object keys shape is rejected"))
        doc = _valid_document(); del doc["current_key_id"]; structural_cases.append((doc, "missing current_key_id is rejected"))
        doc = _valid_document(); doc["current_key_id"] = "local-absent"; structural_cases.append((doc, "current key absent from keys is rejected"))
        doc = _valid_document(); doc["keys"][doc["current_key_id"]] = "not base64!"; structural_cases.append((doc, "invalid key base64 is rejected"))
        doc = _valid_document(); doc["server_pepper"] = "not base64!"; structural_cases.append((doc, "invalid pepper base64 is rejected"))
        doc = _valid_document(); doc["keys"][doc["current_key_id"]] = _encoded(31); structural_cases.append((doc, "non-32-byte AES key is rejected"))
        doc = _valid_document(); doc["server_pepper"] = _encoded(31); structural_cases.append((doc, "too-short server pepper is rejected"))
        for index, (document, label) in enumerate(structural_cases):
            case_path = validation_dir / f"structural-{index}.json"
            _write_document(case_path, document)
            expect_raises(kc.KeyCustodyDocumentError, lambda p=case_path: kc.LocalFileKeyProvider(p), label)

        redaction_path = validation_dir / "redaction.json"
        redaction_marker = "marker-" + secrets.token_hex(24)
        redaction_doc = _valid_document()
        redaction_doc["server_pepper"] = redaction_marker
        _write_document(redaction_path, redaction_doc)
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            try:
                kc.LocalFileKeyProvider(redaction_path)
            except kc.KeyCustodyDocumentError as error:
                error_text = str(error)
            else:
                error_text = ""
        finally:
            root_logger.removeHandler(handler)
        check("raw secret material is redacted from exceptions and logs", redaction_marker not in error_text and redaction_marker not in log_stream.getvalue())

        # One writer repeatedly atomically replaces the document while readers
        # construct fresh snapshots. Every reader must observe a whole version.
        os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
        concurrency_errors = []
        reader_observations = 0

        def writer():
            try:
                for _ in range(12):
                    admin.rotate_current_key()
            except Exception as error:
                concurrency_errors.append(error)

        thread = threading.Thread(target=writer)
        thread.start()
        while thread.is_alive():
            try:
                snapshot = kc.LocalFileKeyProvider()
                reader_observations += 1
                check_id = snapshot.current_key_id()
                if len(snapshot.get_key(check_id)) != 32:
                    concurrency_errors.append(AssertionError("partial key observed"))
                    break
            except Exception as error:
                concurrency_errors.append(error)
                break
        thread.join()
        check("concurrent readers observe only complete atomic documents", not concurrency_errors and reader_observations > 0, f"observations={reader_observations}; errors={concurrency_errors!r}")

        # The same minimal behavior contract applies to the test provider and
        # the configured local provider.
        memory_provider = ts.InMemoryKeyProvider()
        memory_id = "memory-" + secrets.token_hex(8)
        memory_provider.add_key(memory_id, secrets.token_bytes(32))
        local_provider = kc.LocalFileKeyProvider()
        for label, provider in [("in-memory", memory_provider), ("local-file", local_provider)]:
            current = provider.current_key_id()
            check(f"shared provider contract: {label} current key resolves to 32 bytes", len(provider.get_key(current)) == 32)
            expect_raises(ts.UnknownKeyError, lambda p=provider: p.get_key("missing-key"), f"shared provider contract: {label} unknown key fails closed")

        os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
        production_provider = auth_routes._key_provider()
        check("configured local_file never returns InMemoryKeyProvider", isinstance(production_provider, kc.LocalFileKeyProvider) and not isinstance(production_provider, ts.InMemoryKeyProvider))
        check("auth_routes server-pepper seam dispatches to custody source", auth_routes._server_pepper() == kc.get_configured_server_pepper())

        original_key_seam = auth_routes._key_provider
        original_pepper_seam = auth_routes._server_pepper
        seam_provider = ts.InMemoryKeyProvider()
        seam_provider.add_key("seam-key", secrets.token_bytes(32))
        seam_pepper = secrets.token_bytes(32)
        auth_routes._key_provider = lambda: seam_provider
        auth_routes._server_pepper = lambda: seam_pepper
        check("existing auth_routes monkeypatch seam remains functional", auth_routes._key_provider() is seam_provider and auth_routes._server_pepper() == seam_pepper)
        auth_routes._key_provider = original_key_seam
        auth_routes._server_pepper = original_pepper_seam

        os.environ.pop("VERGI_KEY_PROVIDER_KIND", None)
        expect_raises(kc.KeyCustodyConfigurationError, auth_routes._key_provider, "unmonkeypatched auth_routes key seam fails closed without configuration")
        expect_raises(kc.KeyCustodyConfigurationError, auth_routes._server_pepper, "unmonkeypatched auth_routes pepper seam fails closed without configuration")

        unavailable = kc.KeyCustodyProviderUnavailableError("provider unavailable")
        original_dispatch = kc.get_configured_key_provider
        kc.get_configured_key_provider = lambda: (_ for _ in ()).throw(unavailable)
        try:
            try:
                auth_routes._key_provider()
            except Exception as error:
                check("provider-unavailable exception is not converted to an attack-shaped denial", error is unavailable)
            else:
                check("provider-unavailable exception is not converted to an attack-shaped denial", False, "no exception raised")
        finally:
            kc.get_configured_key_provider = original_dispatch

        # F1: create below a deliberately broad inheritable parent, then inspect
        # actual ACLs without consulting the production ACL validator.
        with tempfile.TemporaryDirectory(prefix="row19d_acl_parent_") as acl_name:
            acl_parent = Path(acl_name)
            _grant_inheritable_users(acl_parent, kc._current_user_sid())
            check("ACL fixture parent carries broad inheritable Users access", "BUILTIN\\Users" in _icacls(acl_parent))
            saved_local = os.environ["LOCALAPPDATA"]
            os.environ["LOCALAPPDATA"] = str(acl_parent)
            observed_temp_acls = []
            original_rename = kc.os.rename

            def inspect_initial_temp(source, destination):
                observed_temp_acls.append(_acl_is_private(Path(source)))
                return original_rename(source, destination)

            kc.os.rename = inspect_initial_temp
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    acl_init_rc = admin.main(["initialize"])
            finally:
                kc.os.rename = original_rename
            acl_path = kc.resolve_local_key_path()
            acl_objects = [acl_parent / "vergi_ai", acl_path.parent, acl_path.parent / kc._LOCK_FILE_NAME, acl_path]
            check("initialization under broad parent succeeds", acl_init_rc == 0)
            check("new custody directories, lock, temp, and final file have private protected ACLs", all(_acl_is_private(item) for item in acl_objects) and observed_temp_acls == [True])

            original_replace = kc.os.replace
            observed_rotation_temp = []

            def inspect_rotation_temp(source, destination):
                observed_rotation_temp.append(_acl_is_private(Path(source)))
                return original_replace(source, destination)

            kc.os.replace = inspect_rotation_temp
            try:
                admin.rotate_current_key()
            finally:
                kc.os.replace = original_replace
            check("rotation validates a private temporary ACL before commit", observed_rotation_temp == [True] and _acl_is_private(acl_path))

            unsafe_parent = acl_parent / "unsafe"
            unsafe_parent.mkdir()
            _grant_inheritable_users(unsafe_parent, kc._current_user_sid())
            unsafe_file = unsafe_parent / "local_keys.json"
            unsafe_file.write_text(json.dumps(_valid_document()), encoding="utf-8")
            expect_raises(kc.KeyCustodyConfigurationError, lambda: kc.LocalFileKeyProvider(unsafe_file), "existing unsafe custody ACL fails closed")
            os.environ["LOCALAPPDATA"] = saved_local

        # F5: static junctions are rejected, and a validated parent cannot be
        # renamed into a surrogate protected root while handles are held.
        with tempfile.TemporaryDirectory(prefix="row19d_reparse_") as reparse_name:
            reparse_root = Path(reparse_name)
            surrogate = reparse_root / "surrogate_protected"
            surrogate.mkdir()
            junction = reparse_root / "custody_link"
            _make_junction(junction, surrogate)
            try:
                expect_raises(kc.KeyCustodyConfigurationError, lambda: kc.LocalFileKeyProvider(junction / "local_keys.json"), "static custody junction is rejected")
            finally:
                os.rmdir(junction)

            file_target = reparse_root / "file_reparse_target"
            file_target.mkdir()
            file_reparse = reparse_root / "secure_parent" / "local_keys.json"
            with kc._trusted_namespace(file_reparse, create=True):
                pass
            _make_junction(file_reparse, file_target)
            try:
                expect_raises(kc.KeyCustodyError, lambda: kc.LocalFileKeyProvider(file_reparse), "custody-file reparse point is rejected")
            finally:
                os.rmdir(file_reparse)

            swap_target = reparse_root / "swap_target"
            swap_target.mkdir()
            moved_parent = path.parent.with_name(path.parent.name + "_moved")
            swap_attempted = []
            original_secure_temp = kc._write_secure_temporary

            def attempt_parent_swap(destination, payload):
                try:
                    os.rename(path.parent, moved_parent)
                except OSError:
                    swap_attempted.append("blocked")
                else:
                    swap_attempted.append("renamed")
                    _make_junction(path.parent, swap_target)
                    raise AssertionError("validated custody parent was renameable")
                return original_secure_temp(destination, payload)

            kc._write_secure_temporary = attempt_parent_swap
            try:
                admin.rotate_current_key()
            finally:
                kc._write_secure_temporary = original_secure_temp
            check("held namespace handles block deterministic parent-swap race", swap_attempted == ["blocked"])
            check("surrogate protected root receives no key material", not (swap_target / "local_keys.json").exists())

        # F3: before the os.replace commit point old bytes survive and residue is
        # cleaned; after commit a reporting failure is classified as committed.
        before_fault = path.read_bytes()
        original_replace = kc.os.replace
        def fail_before_commit(_source, _destination):
            raise OSError("injected pre-commit replacement failure")

        kc.os.replace = fail_before_commit
        pre_stdout, pre_stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(pre_stdout), contextlib.redirect_stderr(pre_stderr):
                pre_rc = admin.main(["rotate-key"])
        finally:
            kc.os.replace = original_replace
        check("pre-commit failure reports unapplied and preserves destination bytes", pre_rc == 2 and path.read_bytes() == before_fault and "ERROR" in pre_stderr.getvalue())
        check("pre-commit failure cleans normal temporary residue", not list(path.parent.glob(f".{path.name}.*.tmp")))

        before_post = path.read_bytes()
        original_emit = admin._emit_committed

        def fail_reporting(*_args):
            raise RuntimeError("injected post-commit reporting failure")

        admin._emit_committed = fail_reporting
        post_stdout, post_stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(post_stdout), contextlib.redirect_stderr(post_stderr):
                post_rc = admin.main(["rotate-pepper"])
        finally:
            admin._emit_committed = original_emit
        check("post-commit reporting failure is explicitly classified as committed", post_rc == 3 and path.read_bytes() != before_post and "COMMITTED_WITH_REPORTING_ERROR" in post_stderr.getvalue())
        check("committed pepper warning survives reporting failure", "WARNING" in post_stderr.getvalue() and "CSRF" in post_stderr.getvalue())

        # F2: real child processes contend on the Win32 byte-range lock.
        os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
        with tempfile.TemporaryDirectory(prefix="row19d_process_key_key_") as process_name:
            process_root = Path(process_name)
            saved_local = os.environ["LOCALAPPDATA"]
            os.environ["LOCALAPPDATA"] = str(process_root)
            admin.initialize_local_key_file()
            signal = process_root / "first.locked"
            release = process_root / "release.first"
            first = _worker_process("rotate-key", process_root, signal, release)
            _wait_for(signal)
            process_path = kc.resolve_local_key_path()

            timeout_failed = False
            try:
                with kc._trusted_namespace(process_path, create=False):
                    with kc._mutation_lock(process_path, timeout=0.05):
                        pass
            except kc.KeyCustodyProviderUnavailableError:
                timeout_failed = True
            check("mutation lock acquisition times out fail-closed within a bound", timeout_failed)
            second = _worker_process("rotate-key", process_root)
            time.sleep(0.15)
            check("competing process remains blocked while mutation lock is held", second.poll() is None)
            release.write_text("go", encoding="ascii")
            first_output = first.communicate(timeout=15)
            second_output = second.communicate(timeout=15)
            process_document = json.loads(kc.resolve_local_key_path().read_text(encoding="utf-8"))
            check("two successful process key rotations retain all three keys", first.returncode == second.returncode == 0 and len(process_document["keys"]) == 3, repr((first_output, second_output)))
            os.environ["LOCALAPPDATA"] = saved_local

        with tempfile.TemporaryDirectory(prefix="row19d_process_key_pepper_") as process_name:
            process_root = Path(process_name)
            saved_local = os.environ["LOCALAPPDATA"]
            os.environ["LOCALAPPDATA"] = str(process_root)
            admin.initialize_local_key_file()
            initial_pepper = kc.get_configured_server_pepper()
            key_signal, key_release = process_root / "key.locked", process_root / "key.release"
            pepper_signal, pepper_release = process_root / "pepper.locked", process_root / "pepper.release"
            key_worker = _worker_process("rotate-key", process_root, key_signal, key_release)
            _wait_for(key_signal)
            pepper_worker = _worker_process("rotate-pepper", process_root, pepper_signal, pepper_release)
            key_release.write_text("go", encoding="ascii")
            key_worker.communicate(timeout=15)
            _wait_for(pepper_signal)
            intermediate_provider = kc.LocalFileKeyProvider()
            intermediate_plaintext = secrets.token_bytes(41)
            intermediate_ciphertext = ts.encrypt_transient_secret(intermediate_plaintext, key_provider=intermediate_provider)
            pepper_release.write_text("go", encoding="ascii")
            pepper_worker.communicate(timeout=15)
            final_provider = kc.LocalFileKeyProvider()
            final_document = json.loads(kc.resolve_local_key_path().read_text(encoding="utf-8"))
            check("key rotation racing pepper rotation preserves both mutations", key_worker.returncode == pepper_worker.returncode == 0 and len(final_document["keys"]) == 2 and kc.get_configured_server_pepper() != initial_pepper)
            check("intermediate newly published key remains decryptable after competing pepper rotation", ts.decrypt_transient_secret(intermediate_ciphertext, key_provider=final_provider) == intermediate_plaintext)
            os.environ["LOCALAPPDATA"] = saved_local

        with tempfile.TemporaryDirectory(prefix="row19d_process_pepper_key_") as process_name:
            process_root = Path(process_name)
            saved_local = os.environ["LOCALAPPDATA"]
            os.environ["LOCALAPPDATA"] = str(process_root)
            admin.initialize_local_key_file()
            old_pepper = kc.get_configured_server_pepper()
            pepper_signal, pepper_release = process_root / "pepper.locked", process_root / "pepper.release"
            key_signal, key_release = process_root / "key.locked", process_root / "key.release"
            pepper_worker = _worker_process("rotate-pepper", process_root, pepper_signal, pepper_release)
            _wait_for(pepper_signal)
            key_worker = _worker_process("rotate-key", process_root, key_signal, key_release)
            pepper_release.write_text("go", encoding="ascii")
            pepper_worker.communicate(timeout=15)
            _wait_for(key_signal)
            intermediate_pepper = kc.get_configured_server_pepper()
            key_release.write_text("go", encoding="ascii")
            key_worker.communicate(timeout=15)
            final_document = json.loads(kc.resolve_local_key_path().read_text(encoding="utf-8"))
            check("pepper rotation racing key rotation cannot restore old pepper", pepper_worker.returncode == key_worker.returncode == 0 and intermediate_pepper != old_pepper and kc.get_configured_server_pepper() == intermediate_pepper and len(final_document["keys"]) == 2)
            os.environ["LOCALAPPDATA"] = saved_local

        # F4: exercise the unchanged real callback, provider parser and AEAD.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from ui.services import db

        callback_env = {
            "VERGI_ENTRA_TENANT_ID": "11111111-1111-1111-1111-111111111111",
            "VERGI_ENTRA_CLIENT_ID": "callback-client",
            "VERGI_ENTRA_AUTH_ENDPOINT": "https://invalid.example/authorize",
            "VERGI_ENTRA_TOKEN_ENDPOINT": "https://invalid.example/token",
            "VERGI_ENTRA_JWKS_URI": "https://invalid.example/keys",
            "VERGI_ENTRA_REDIRECT_URI": "http://localhost:8000/auth/callback",
            "VERGI_ENTRA_REQUIRED_AUTH_CONTEXT_ID": "c1",
            "VERGI_ENTRA_MFA_TIER": "entra_p1",
        }
        saved_callback_env = {name: os.environ.get(name) for name in callback_env}
        os.environ.update(callback_env)
        app = FastAPI()
        app.include_router(auth_routes.router)
        client = TestClient(app, raise_server_exceptions=False)
        original_transaction = db.transaction
        original_exchange = auth_routes.oidc_client.exchange_code_for_tokens
        exchange_calls = []

        async def forbidden_exchange(*_args, **_kwargs):
            exchange_calls.append(True)
            raise AssertionError("token exchange must not occur")

        auth_routes.oidc_client.exchange_code_for_tokens = forbidden_exchange

        def callback_http(row, state):
            recorder = _SqlRecorder(row)
            db.transaction = recorder.transaction
            response = client.get("/auth/callback", params={"code": "synthetic-code", "state": state})
            return response, recorder

        with tempfile.TemporaryDirectory(prefix="row19d_callback_") as callback_name:
            callback_root = Path(callback_name)
            os.environ["LOCALAPPDATA"] = str(callback_root)
            os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
            admin.initialize_local_key_file()
            callback_provider = kc.LocalFileKeyProvider()
            callback_state = secrets.token_urlsafe(24)
            callback_state_hash = auth_routes.oidc_client.hash_transaction_value(callback_state)
            verifier = secrets.token_urlsafe(48).encode("ascii")
            callback_secret = ts.encrypt_transient_secret(verifier, key_provider=callback_provider, associated_data=callback_state_hash.encode("utf-8"))
            base_row = (1, "unused-nonce-hash", callback_secret.ciphertext, callback_secret.nonce, callback_secret.key_id, callback_secret.alg, "c1")

            unknown_row = base_row[:4] + ("local-unknown",) + base_row[5:]
            unknown_response, unknown_recorder = callback_http(unknown_row, callback_state)
            corrupt_bytes = callback_secret.ciphertext[:-1] + bytes([callback_secret.ciphertext[-1] ^ 1])
            corrupt_row = (2, "unused-nonce-hash", corrupt_bytes, callback_secret.nonce, callback_secret.key_id, callback_secret.alg, "c1")
            corrupt_response, corrupt_recorder = callback_http(corrupt_row, callback_state)
            check("unknown stored key gets generic HTTP denial, consumes transaction, and creates no session", unknown_response.status_code == 401 and unknown_recorder.consumed and unknown_recorder.session_inserts == 0)
            check("corrupt ciphertext gets the identical generic denial and creates no session", corrupt_response.status_code == 401 and corrupt_response.content == unknown_response.content and corrupt_recorder.consumed and corrupt_recorder.session_inserts == 0)
            check("attack-shaped callback denials perform zero token exchanges", exchange_calls == [])

            for kind, label, expected_error in [
                (None, "provider selection unset", kc.KeyCustodyConfigurationError),
                ("kms", "kms selected", kc.KmsProviderNotImplementedError),
            ]:
                if kind is None:
                    os.environ.pop("VERGI_KEY_PROVIDER_KIND", None)
                else:
                    os.environ["VERGI_KEY_PROVIDER_KIND"] = kind
                response, recorder = callback_http(base_row, callback_state)
                check(f"{label} remains a 500 provider/config failure with zero writes/exchange", response.status_code == 500 and response.content != unknown_response.content and not recorder.consumed and recorder.session_inserts == 0 and exchange_calls == [])

            original_async_dispatch = kc.get_configured_key_provider_async

            async def transient_async_dispatch():
                raise kc.KeyCustodyTransientError("retry-after-vault-marker")

            kc.get_configured_key_provider_async = transient_async_dispatch
            try:
                transient_response, transient_recorder = callback_http(base_row, callback_state)
            finally:
                kc.get_configured_key_provider_async = original_async_dispatch
            check(
                "transient callback provider failure is generic 503 with rollback/not-consumed and no leak",
                transient_response.status_code == 503
                and not transient_recorder.consumed
                and transient_recorder.session_inserts == 0
                and exchange_calls == []
                and "retry-after-vault-marker" not in transient_response.text,
            )

            os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
            callback_path = kc.resolve_local_key_path()
            callback_bytes = callback_path.read_bytes()
            callback_path.unlink()
            missing_response, missing_recorder = callback_http(base_row, callback_state)
            check("missing custody file remains a 500 provider failure with zero writes/exchange", missing_response.status_code == 500 and missing_response.content != unknown_response.content and not missing_recorder.consumed and missing_recorder.session_inserts == 0 and exchange_calls == [])
            callback_path.write_bytes(callback_bytes)
            _icacls(callback_path, "/grant", "*S-1-5-32-545:(R)")
            unsafe_response, unsafe_recorder = callback_http(base_row, callback_state)
            check("unsafe custody ACL remains a 500 security/config failure with zero writes/exchange", unsafe_response.status_code == 500 and unsafe_response.content != unknown_response.content and not unsafe_recorder.consumed and unsafe_recorder.session_inserts == 0 and exchange_calls == [])

        # Handler mutant: replacing only the exact catch tuple must change the
        # permanent unknown-key expectation from 401 to an unhandled 500.
        with tempfile.TemporaryDirectory(prefix="row19d_callback_mutant_") as mutant_name:
            os.environ["LOCALAPPDATA"] = mutant_name
            os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"
            admin.initialize_local_key_file()
            source = textwrap.dedent(inspect.getsource(auth_routes.callback))
            tree = ast.parse(source)
            tree.body[0].decorator_list = []
            changed = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
                    if any(isinstance(item, ast.Attribute) and item.attr == "UnknownKeyError" for item in node.type.elts):
                        node.type = ast.Name(id="ZeroDivisionError", ctx=ast.Load())
                        changed = True
            namespace = dict(auth_routes.__dict__)
            exec(compile(ast.fix_missing_locations(tree), "<callback-handler-mutant>", "exec"), namespace)
            original_code = auth_routes.callback.__code__
            auth_routes.callback.__code__ = namespace["callback"].__code__
            try:
                mutant_provider = kc.LocalFileKeyProvider()
                mutant_state = secrets.token_urlsafe(24)
                mutant_hash = auth_routes.oidc_client.hash_transaction_value(mutant_state)
                mutant_secret = ts.encrypt_transient_secret(b"mutant-verifier", key_provider=mutant_provider, associated_data=mutant_hash.encode("utf-8"))
                mutant_row = (3, "nonce", mutant_secret.ciphertext, mutant_secret.nonce, "local-unknown", mutant_secret.alg, "c1")
                mutant_response, mutant_recorder = callback_http(mutant_row, mutant_state)
            finally:
                auth_routes.callback.__code__ = original_code
            check("handler-deletion mutant is killed by the permanent callback expectation", changed and mutant_response.status_code == 500 and not mutant_recorder.consumed and mutant_recorder.session_inserts == 0)

        db.transaction = original_transaction
        auth_routes.oidc_client.exchange_code_for_tokens = original_exchange
        client.close()
        for name, value in saved_callback_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        os.environ["LOCALAPPDATA"] = str(external_root)
        os.environ["VERGI_KEY_PROVIDER_KIND"] = "local_file"

        check("no .env file is opened", opened_env_files == [], repr(opened_env_files))
finally:
    if original_local_app_data is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original_local_app_data
    if original_provider_kind is None:
        os.environ.pop("VERGI_KEY_PROVIDER_KIND", None)
    else:
        os.environ["VERGI_KEY_PROVIDER_KIND"] = original_provider_kind


print(f"--- test_key_custody_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
