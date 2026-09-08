# ============================================================
# Row 19C-1 - isolated tests for ui/services/paths.py's realpath/
# `resolve(strict=True)`-based containment addition
# (`verify_real_path_contained` / `resolve_case_path` /
# `PathContainmentError`).
#
# PLATFORM-INDEPENDENT BY DESIGN: every check in this file either (a)
# needs no symlink at all (a genuinely-outside-root real path, a
# missing path, forbidden-substring rejection - proven with plain
# temp directories on any OS), or (b) attempts a REAL POSIX symlink
# via `os.symlink` and, ONLY for that specific sub-case, treats a
# privilege-related failure (expected on a Windows machine without
# Developer Mode or an elevated prompt) as an EXPLICIT, clearly
# labeled SKIP - never silently counted as a pass, never hidden. The
# Windows-NATIVE equivalent (an NTFS junction via `mklink /J`, which
# does not require elevation) is proven separately in
# ui/tests/test_path_containment_windows.py, which itself must never
# silently skip on Windows - only off-Windows.
#
# Every fixture here lives under a fresh `tempfile.mkdtemp()` -
# `ui.services.paths.CASES_DIR`/`DATA_DIR` are monkeypatched to point
# there for the duration of this file's `resolve_case_path()` tests
# and restored immediately after, so this file NEVER reads or writes
# this repository's own (real, or in this sandbox absent) `data/`
# tree - matching this turn's explicit prohibition on touching `data/`.
#
# Run: python -m ui.tests.test_path_containment_isolated
# ============================================================

import os
import shutil
import sys
import tempfile
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths  # noqa: E402

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {label} - {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


def symlink_creation_is_available(tmp_root: Path) -> bool:
    """A real, throwaway probe (not a platform.system() guess) - the
    ONLY reliable way to know whether this process can create a
    symlink right now is to actually try. Cleans up after itself
    either way."""
    target = tmp_root / "_symlink_probe_target"
    link = tmp_root / "_symlink_probe_link"
    target.mkdir()
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        if link.exists() or link.is_symlink():
            try:
                link.unlink()
            except OSError:
                pass
        shutil.rmtree(target, ignore_errors=True)


def snapshot_tree(root: Path):
    """A byte-for-byte, entry-for-entry snapshot of every path under
    `root` (relative names only) - used by the ROW 19C-3a DRIVE-
    RELATIVE ESCAPE REMEDIATION coverage to prove that rejected attack
    attempts never write anything to disk."""
    if not root.is_dir():
        return frozenset()
    return frozenset(str(p.relative_to(root)) for p in root.rglob("*"))


# ----------------------------------------------------------------
# 1) verify_real_path_contained() - pure unit tests, NO symlink
#    needed, fully platform-independent.
# ----------------------------------------------------------------

tmp_root = Path(tempfile.mkdtemp(prefix="row19c1_path_containment_"))
tmp_outside = Path(tempfile.mkdtemp(prefix="row19c1_path_containment_outside_"))

try:
    inside_dir = tmp_root / "inside_subdir"
    inside_dir.mkdir()
    inside_file = inside_dir / "file.txt"
    inside_file.write_text("hello")

    resolved = paths.verify_real_path_contained(inside_file, root=tmp_root)
    check(
        "an existing path genuinely inside root is verified and its real form is returned",
        resolved == inside_file.resolve(strict=True),
    )

    resolved_dir = paths.verify_real_path_contained(inside_dir, root=tmp_root)
    check("root itself... err, a subdirectory of root is verified too", resolved_dir == inside_dir.resolve(strict=True))

    outside_file = tmp_outside / "outside_file.txt"
    outside_file.write_text("nope")
    expect_raises(
        paths.PathContainmentError,
        lambda: paths.verify_real_path_contained(outside_file, root=tmp_root),
        "a real, EXISTING path genuinely outside root is rejected (no symlink needed for this case)",
    )

    expect_raises(
        paths.PathContainmentError,
        lambda: paths.verify_real_path_contained(tmp_root / "does_not_exist.txt", root=tmp_root),
        "a non-existent path is rejected (Path.resolve(strict=True) fails closed, never silently 'passes')",
    )

    check(
        "PathContainmentError IS a subclass of UnknownCaseError (every existing except UnknownCaseError: call site keeps working)",
        issubclass(paths.PathContainmentError, paths.UnknownCaseError),
    )

    check(
        "verify_real_path_contained() defaults root= to BASE_DIR when omitted",
        paths.verify_real_path_contained(Path(paths.__file__)) == Path(paths.__file__).resolve(strict=True),
    )

    # --------------------------------------------------------------
    # 1b) The REAL symlink-escape case - a symlink physically INSIDE
    #     root pointing OUTSIDE it. This is the actual defense this
    #     addition exists for (a bare string/allowlist check can never
    #     catch this - see paths.py's own Row 19C-1 addition banner).
    # --------------------------------------------------------------
    if symlink_creation_is_available(tmp_root):
        escape_link = tmp_root / "escape_link"
        os.symlink(str(tmp_outside), str(escape_link), target_is_directory=True)
        try:
            expect_raises(
                paths.PathContainmentError,
                lambda: paths.verify_real_path_contained(escape_link, root=tmp_root),
                "a REAL symlink physically inside root, pointing OUTSIDE root, is caught and rejected",
            )
            expect_raises(
                paths.PathContainmentError,
                lambda: paths.verify_real_path_contained(escape_link / "outside_file.txt", root=tmp_root),
                "a path THROUGH that escaping symlink is also caught and rejected (not just the symlink itself)",
            )
        finally:
            escape_link.unlink()
    else:
        skip(
            "real symlink-escape check (verify_real_path_contained)",
            "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation) - "
            "see ui/tests/test_path_containment_windows.py for the junction-based Windows-native equivalent",
        )

    # ----------------------------------------------------------------
    # 2) resolve_case_path() - monkeypatch CASES_DIR/DATA_DIR to an
    #    isolated temp tree so this file NEVER touches the real
    #    (in this sandbox: absent) data/ directory.
    # ----------------------------------------------------------------

    fake_data_dir = tmp_root / "fake_data"
    fake_cases_dir = fake_data_dir / "cases"
    fake_cases_dir.mkdir(parents=True)

    case_0001_dir = fake_cases_dir / "case_0001"
    case_0001_dir.mkdir()
    (case_0001_dir / "case.json").write_text("{}")
    (case_0001_dir / "existing_file.txt").write_text("already here")

    original_data_dir = paths.DATA_DIR
    original_cases_dir = paths.CASES_DIR
    paths.DATA_DIR = fake_data_dir
    paths.CASES_DIR = fake_cases_dir
    try:
        check(
            "resolve_case_path() sanity: the fake case is actually discoverable via list_case_ids()",
            "case_0001" in paths.list_case_ids(),
        )

        resolved_case_dir = paths.resolve_case_path("case_0001")
        check("resolve_case_path(case_id) with no extra parts returns the case directory's real form", resolved_case_dir == case_0001_dir.resolve(strict=True))

        resolved_existing = paths.resolve_case_path("case_0001", "existing_file.txt")
        check("resolve_case_path() locates an EXISTING file inside the case directory", resolved_existing == (case_0001_dir / "existing_file.txt").resolve(strict=True))

        new_file_candidate = paths.resolve_case_path("case_0001", "brand_new_file.txt")
        check(
            "resolve_case_path() returns a usable (not-yet-existing) candidate path for a file about to be created",
            new_file_candidate == case_0001_dir / "brand_new_file.txt" and not new_file_candidate.exists(),
        )

        expect_raises(
            paths.UnknownCaseError,
            lambda: paths.resolve_case_path("case_does_not_exist", "file.txt"),
            "resolve_case_path() rejects an unknown case_id (delegates to the UNCHANGED resolve_case_id())",
        )

        expect_raises(
            paths.UnknownCaseError,
            lambda: paths.resolve_case_path("case_0001", "..", "escape.txt"),
            "resolve_case_path() rejects a traversal segment in relative_parts BEFORE any filesystem resolution",
        )

        expect_raises(
            paths.UnknownCaseError,
            lambda: paths.resolve_case_path("case_0001", ""),
            "resolve_case_path() rejects an empty relative_parts segment",
        )

        # ============================================================
        # ROW 19C-3a DRIVE-RELATIVE ESCAPE REMEDIATION - the same
        # independent-review Critical finding proven end-to-end through
        # the PUBLIC ui.services.paths.resolve_case_path() wrapper, not
        # just the shared src/path_containment.py module directly (see
        # ui/tests/test_path_containment_module_isolated.py for the
        # shared-module-level coverage). Deterministic, platform-
        # independent - none of it requires a real second drive.
        # ============================================================

        _drive_relative_attack_segments_via_wrapper = [
            "D:not_yet_existing_evil.txt",
            "D:",
            "C:not_yet_existing_evil.txt",
            "file.txt:stream",
            ".",
            ":",
            "Q:",
        ]

        for _attack_segment in _drive_relative_attack_segments_via_wrapper:
            expect_raises(
                paths.PathContainmentError,
                lambda seg=_attack_segment: paths.resolve_case_path("case_0001", seg),
                f"resolve_case_path(): drive-relative/ADS-colon segment {_attack_segment!r} as the "
                f"ONLY relative part is rejected (PathContainmentError), never returned as an "
                f"unverified escaped candidate",
            )
            expect_raises(
                paths.PathContainmentError,
                lambda seg=_attack_segment: paths.resolve_case_path("case_0001", "new_subdir", seg, "trailing.txt"),
                f"resolve_case_path(): same segment {_attack_segment!r} as a LATER part of an "
                f"otherwise-normal missing chain is also rejected",
            )

        # Using the REAL, currently-existing system drive letter, not
        # just an arbitrary/nonexistent one.
        _real_system_drive_via_wrapper = fake_cases_dir.drive
        if _real_system_drive_via_wrapper:
            _real_drive_segment_via_wrapper = f"{_real_system_drive_via_wrapper}real_system_drive_evil.txt"
            expect_raises(
                paths.PathContainmentError,
                lambda: paths.resolve_case_path("case_0001", _real_drive_segment_via_wrapper),
                f"resolve_case_path(): a drive-relative segment on the REAL, currently-existing "
                f"system drive ({_real_drive_segment_via_wrapper!r}) is rejected too",
            )
        else:
            skip(
                "resolve_case_path() real-system-drive drive-relative segment check",
                "this platform's paths carry no drive component (POSIX)",
            )

        # No rejected attack attempt wrote anything under the fake case
        # directory (or anywhere else in the fake cases tree).
        _wrapper_attack_snapshot_before = snapshot_tree(fake_cases_dir)
        for _attack_segment in _drive_relative_attack_segments_via_wrapper:
            try:
                paths.resolve_case_path("case_0001", _attack_segment)
            except paths.PathContainmentError:
                pass
            try:
                paths.resolve_case_path("case_0001", "new_subdir", _attack_segment, "trailing.txt")
            except paths.PathContainmentError:
                pass
        _wrapper_attack_snapshot_after = snapshot_tree(fake_cases_dir)
        check(
            "resolve_case_path(): none of the rejected drive-relative/ADS-colon attack attempts "
            "wrote anything under the fake cases tree",
            _wrapper_attack_snapshot_before == _wrapper_attack_snapshot_after,
            f"diff={_wrapper_attack_snapshot_before ^ _wrapper_attack_snapshot_after}",
        )

        # Regression: ordinary resolve_case_path() behavior (existing
        # file lookup, genuinely-missing leaf candidate) is completely
        # UNAFFECTED by the fix.
        check(
            "resolve_case_path(): ordinary existing-file lookup is unaffected by the drive-relative fix",
            paths.resolve_case_path("case_0001", "existing_file.txt")
            == (case_0001_dir / "existing_file.txt").resolve(strict=True),
        )
        check(
            "resolve_case_path(): ordinary not-yet-existing leaf candidate is unaffected by the "
            "drive-relative fix",
            paths.resolve_case_path("case_0001", "still_a_normal_new_file.txt")
            == case_0001_dir / "still_a_normal_new_file.txt",
        )

        # ROW 19C-3a SLICE 1 - BROKEN/LOOPING LINK IN A CREATE-CHAIN NOW
        # FAILS CLOSED (the exact bug class Row 19C-2c independently
        # found and fixed for the drafting-request facade/adapter: the
        # OLD `candidate.exists()` gate could not tell "genuinely not
        # yet created" from "a broken or looping link is here", so it
        # silently returned the raw, unverified link path as a
        # not-yet-existing candidate). Uses a REAL symlink, never a
        # monkeypatch.
        if symlink_creation_is_available(tmp_root):
            ghost_target = tmp_outside / "row19c3a_ghost_target"
            ghost_target.mkdir()
            broken_link_path = case_0001_dir / "broken_link_child"
            os.symlink(str(ghost_target), str(broken_link_path), target_is_directory=True)
            shutil.rmtree(ghost_target)  # break it - target gone, link entry remains
            try:
                check(
                    "broken create-chain precondition: os.path.lexists()==True",
                    os.path.lexists(broken_link_path) is True,
                )
                check(
                    "broken create-chain precondition: Path.exists()==False",
                    broken_link_path.exists() is False,
                )
                expect_raises(
                    paths.PathContainmentError,
                    lambda: paths.resolve_case_path("case_0001", "broken_link_child", "leaf.txt"),
                    "resolve_case_path(): a BROKEN link as an intermediate create-chain segment now FAILS "
                    "CLOSED (PathContainmentError) instead of the old .exists()-based fail-open",
                )
                expect_raises(
                    paths.PathContainmentError,
                    lambda: paths.resolve_case_path("case_0001", "broken_link_child"),
                    "resolve_case_path(): a BROKEN link as the FINAL create-chain segment is also rejected",
                )
            finally:
                broken_link_path.unlink()

            loop_link_path = case_0001_dir / "loop_link_child"
            os.symlink("loop_link_child", str(loop_link_path))
            try:
                check(
                    "circular create-chain precondition: os.path.lexists()==True",
                    os.path.lexists(loop_link_path) is True,
                )
                check(
                    "circular create-chain precondition: Path.exists()==False (ELOOP)",
                    loop_link_path.exists() is False,
                )
                expect_raises(
                    paths.PathContainmentError,
                    lambda: paths.resolve_case_path("case_0001", "loop_link_child", "leaf.txt"),
                    "resolve_case_path(): a DÖNGÜSEL (self-loop, ELOOP) link as an intermediate create-chain "
                    "segment now FAILS CLOSED",
                )
            finally:
                loop_link_path.unlink()

            check(
                "resolve_case_path(): normal (non-broken, non-circular) behavior is completely UNCHANGED "
                "after the broken-link fix - existing file still resolves, not-yet-existing leaf still "
                "returns a usable candidate",
                paths.resolve_case_path("case_0001", "existing_file.txt")
                == (case_0001_dir / "existing_file.txt").resolve(strict=True)
                and paths.resolve_case_path("case_0001", "still_brand_new.txt")
                == case_0001_dir / "still_brand_new.txt",
            )
        else:
            skip(
                "broken/circular create-chain fail-closed check (resolve_case_path)",
                "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation) - "
                "see ui/tests/test_path_containment_windows.py for the junction-based Windows-native equivalent",
            )

        # ROW 19C-3a SLICE 1 - list_case_ids() PRESERVES LOGICAL CHILD
        # IDENTITY AND SORT ORDER through the new path_containment.
        # list_contained_dir() delegation (a safe internal symlink
        # alias must keep its OWN on-disk name, never silently become
        # its target's name).
        if symlink_creation_is_available(tmp_root):
            case_0003_dir = fake_cases_dir / "case_0003"
            case_0003_dir.mkdir()
            (case_0003_dir / "case.json").write_text("{}")

            alias_case_dir = fake_cases_dir / "case_0001_alias"
            os.symlink(str(case_0001_dir), str(alias_case_dir), target_is_directory=True)
            try:
                ids_with_alias = paths.list_case_ids()
                check(
                    "list_case_ids(): a SAFE internal alias (symlink to ANOTHER real case dir, still "
                    "contained under CASES_DIR) is listed under its OWN logical name, sorted with the rest",
                    ids_with_alias == sorted(["case_0001", "case_0001_alias", "case_0003"]),
                    f"got {ids_with_alias!r}",
                )
            finally:
                alias_case_dir.unlink()
                shutil.rmtree(case_0003_dir)

            check(
                "list_case_ids(): logical names/order are UNCHANGED once the alias is removed again",
                paths.list_case_ids() == ["case_0001"],
            )
        else:
            skip(
                "list_case_ids() logical-identity/order preservation check",
                "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation)",
            )

        # The real, end-to-end attack scenario: a case directory that
        # is ITSELF a symlink pointing outside the cases root.
        #
        # ROW 19C-1 PATH CHOKE-POINT REMEDIATION: previously, only
        # resolve_case_path() caught this - list_case_ids() happily
        # discovered it (Path.is_dir() follows symlinks) and
        # resolve_case_id() ALONE (the check every EXISTING production
        # caller, via ui.services.authz, actually uses) accepted the
        # bare string "case_0002" as legitimate. That was exactly the
        # gap this remediation closes: list_case_ids() now filters the
        # escaping entry out before it can ever be discovered, and
        # resolve_case_id() itself now also rejects it directly.
        if symlink_creation_is_available(tmp_root):
            evil_target_dir = tmp_outside / "evil_case_target"
            evil_target_dir.mkdir()
            (evil_target_dir / "case.json").write_text("{}")
            (evil_target_dir / "secret_outside_file.txt").write_text("should never be reachable via case_0002")

            symlinked_case_dir = fake_cases_dir / "case_0002"
            os.symlink(str(evil_target_dir), str(symlinked_case_dir), target_is_directory=True)
            try:
                check(
                    "(1) list_case_ids() no longer discovers a symlinked case escaping the cases root",
                    "case_0002" not in paths.list_case_ids(),
                )
                expect_raises(
                    paths.UnknownCaseError,
                    lambda: paths.resolve_case_id("case_0002"),
                    "(2) resolve_case_id() ALONE now REJECTS the escaping symlinked case (the exact gap that was closed)",
                )
                # resolve_case_path() calls resolve_case_id() as its
                # OWN first step, so - now that resolve_case_id() itself
                # rejects the escaping symlink - resolve_case_path()
                # raises the same plain UnknownCaseError resolve_case_id()
                # raised, never even reaching its own internal
                # verify_real_path_contained() call. Asserting the
                # broader UnknownCaseError (rather than the narrower
                # PathContainmentError) is deliberate here: it is the
                # externally-observable, closed-result contract that
                # matters, not which internal layer caught it first.
                expect_raises(
                    paths.UnknownCaseError,
                    lambda: paths.resolve_case_path("case_0002"),
                    "(3) resolve_case_path() also rejects a case directory that is itself a symlink escaping the cases root",
                )
                expect_raises(
                    paths.UnknownCaseError,
                    lambda: paths.resolve_case_path("case_0002", "secret_outside_file.txt"),
                    "(4) a subpath reached THROUGH the escaping case-directory symlink is also rejected",
                )
                check(
                    "(5) a normal, real case directory (case_0001) is unaffected and continues to resolve normally",
                    paths.resolve_case_id("case_0001") == "case_0001"
                    and "case_0001" in paths.list_case_ids(),
                )
            finally:
                symlinked_case_dir.unlink()
        else:
            skip(
                "real symlinked-case-directory escape check (resolve_case_id/list_case_ids/resolve_case_path)",
                "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation) - "
                "see ui/tests/test_path_containment_windows.py for the junction-based Windows-native equivalent, "
                "which becomes the authoritative proof when this platform-independent path is unavailable",
            )
    finally:
        paths.DATA_DIR = original_data_dir
        paths.CASES_DIR = original_cases_dir

    # ============================================================
    # ROW 19C-3a ROOT-CONTRACT REMEDIATION - list_case_ids() with an
    # UNVERIFIABLE CASES_DIR root now FAILS CLOSED (translated UI
    # PathContainmentError, still catchable as UnknownCaseError) -
    # never the old silent `[]` pre-gate. Platform-independent: a
    # genuinely missing root needs no symlink at all.
    # ============================================================

    _rc_original_cases_dir = paths.CASES_DIR
    paths.CASES_DIR = tmp_root / "does_not_exist_cases_root"
    try:
        expect_raises(
            paths.PathContainmentError,
            lambda: paths.list_case_ids(),
            "list_case_ids(): a genuinely MISSING CASES_DIR root raises the UI PathContainmentError "
            "(fail-closed, translated from the shared module's own error - never a silent [])",
        )
        try:
            paths.list_case_ids()
        except paths.UnknownCaseError:
            check(
                "list_case_ids(): that root failure is still catchable as UnknownCaseError (every "
                "existing except UnknownCaseError: call site keeps working unchanged)",
                True,
            )
        except Exception as unexpected:
            check(
                "list_case_ids(): that root failure is still catchable as UnknownCaseError (every "
                "existing except UnknownCaseError: call site keeps working unchanged)",
                False, f"unexpected exception: {unexpected!r}",
            )
        else:
            check(
                "list_case_ids(): that root failure is still catchable as UnknownCaseError (every "
                "existing except UnknownCaseError: call site keeps working unchanged)",
                False, "no exception raised at all",
            )
        try:
            paths.list_case_ids()
        except paths.PathContainmentError as translated:
            check(
                "list_case_ids(): the translated UI error explicitly chains ('from') the shared "
                "path_containment.PathContainmentError (never swallowed, never a bare re-raise)",
                type(translated.__cause__).__module__ == "path_containment"
                and type(translated.__cause__).__name__ == "PathContainmentError",
                f"__cause__={translated.__cause__!r}",
            )
    finally:
        paths.CASES_DIR = _rc_original_cases_dir

    # A FILE (not a directory) as the CASES_DIR root fails closed the
    # same way - still no symlink needed.
    _rc_file_root = tmp_root / "cases_root_is_a_file.txt"
    _rc_file_root.write_text("not a directory")
    _rc_original_cases_dir = paths.CASES_DIR
    paths.CASES_DIR = _rc_file_root
    try:
        expect_raises(
            paths.PathContainmentError,
            lambda: paths.list_case_ids(),
            "list_case_ids(): a CASES_DIR root that is a FILE (not a directory) raises the UI "
            "PathContainmentError too",
        )
    finally:
        paths.CASES_DIR = _rc_original_cases_dir

    # ============================================================
    # ROW 19C-2a - SHARED PATH ROOT PROOF FOR ALL 10 CASE-SCOPED
    # APPROVAL MODULES.
    #
    # WHY THIS BELONGS IN *THIS* FILE: every containment guarantee
    # proven above is enforced at ONE choke point -
    # `ui.services.paths`'s own `CASES_DIR`-rooted resolution. That
    # guarantee only actually protects a production approval if the 10
    # `src/*_approval.py` modules, which build their own
    # `CASES_DIR / case_id / "..."` paths DIRECTLY (they do not call
    # `paths.resolve_case_path()`), are rooted at the SAME REAL
    # directory. If any one of them were rooted somewhere else, a
    # case_id that `paths.resolve_case_id()` had verified as contained
    # would still land outside the verified root once that module
    # joined it - the containment check would be sound but simply
    # pointed at the wrong tree.
    #
    # This runs AFTER the monkeypatch above has been restored, so it
    # compares the REAL roots - and it is READ-ONLY: it imports the 10
    # modules (exactly as `ui.services.mutation_approval_facade` and
    # `ui.services.mutation_approval_adapters.build_production_registry()`
    # already do in production) and reads one module attribute from
    # each. NO production path code is modified, and nothing under
    # `data/` is read, written or even listed.
    #
    # `os.path.realpath()` (not `==` on the raw `Path`s, and not
    # `Path.resolve()`) is the comparison, matching
    # `paths.verify_real_path_contained()`'s own choice: two roots that
    # differ textually (`src/..` vs `ui/../..`, a substituted drive, an
    # 8.3 short name, a junctioned parent) but resolve to the SAME real
    # directory are correctly treated as identical, and two that merely
    # LOOK alike but resolve differently are correctly rejected.
    #
    # `qa_approval`/`orchestrator_approval` deliberately do not define
    # their own `CASES_DIR` - they re-export their discovery module's
    # (`from qa_discovery import CASES_DIR`), which is exactly the
    # binding their own `get_*_dir(case_id)` functions use, so reading
    # the module attribute is the faithful check for them too.
    # ============================================================

    import importlib

    _APPROVAL_MODULE_NAMES = [
        "deadline_approval",
        "issue_spotting_approval",
        "legal_research_approval",
        "case_law_approval",
        "evidence_approval",
        "argument_approval",
        "risk_strategy_approval",
        "drafting_approval",
        "qa_approval",
        "orchestrator_approval",
    ]

    check(
        "(path root) exactly 10 case-scoped approval modules are covered by this proof",
        len(_APPROVAL_MODULE_NAMES) == 10 and len(set(_APPROVAL_MODULE_NAMES)) == 10,
    )

    _ui_cases_root_real = os.path.realpath(str(paths.CASES_DIR))
    _observed_roots = {}

    for _module_name in _APPROVAL_MODULE_NAMES:
        try:
            _approval_module = importlib.import_module(_module_name)
        except Exception as _import_error:
            check(
                f"(path root) {_module_name} is importable",
                False, f"import failed: {_import_error!r}",
            )
            continue

        _module_cases_dir = getattr(_approval_module, "CASES_DIR", None)
        if _module_cases_dir is None:
            check(
                f"(path root) {_module_name} exposes a CASES_DIR attribute",
                False, "no CASES_DIR attribute at all - this proof cannot cover it",
            )
            continue

        _module_root_real = os.path.realpath(str(_module_cases_dir))
        _observed_roots[_module_name] = _module_root_real
        check(
            f"(path root) {_module_name}.CASES_DIR resolves to the SAME real root as "
            "ui.services.paths.CASES_DIR",
            _module_root_real == _ui_cases_root_real,
            f"module={_module_root_real!r} != ui={_ui_cases_root_real!r}",
        )

    check(
        "(path root) all 10 modules were actually reached and compared (none silently skipped)",
        len(_observed_roots) == 10,
        f"only compared: {sorted(_observed_roots)}",
    )
    check(
        "(path root) the 10 modules agree on ONE single real cases root, not several",
        len(set(_observed_roots.values())) == 1,
        f"distinct roots observed: {sorted(set(_observed_roots.values()))}",
    )

    # Negative control: this comparison genuinely DISCRIMINATES - it is
    # not a tautology that passes for any two paths. A deliberately
    # different real directory (the `tmp_outside` root this file already
    # created) must NOT compare equal to the shared cases root.
    check(
        "(path root) the realpath comparison is discriminating (a genuinely different real "
        "directory does NOT compare equal)",
        os.path.realpath(str(tmp_outside)) != _ui_cases_root_real,
    )

finally:
    shutil.rmtree(tmp_root, ignore_errors=True)
    shutil.rmtree(tmp_outside, ignore_errors=True)

print(f"--- test_path_containment_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
sys.exit(1 if failed else 0)
