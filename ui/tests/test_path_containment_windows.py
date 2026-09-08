# ============================================================
# Row 19C-1 - Windows-NATIVE path containment test
# (ui/services/paths.py's verify_real_path_contained/resolve_case_path
# against an NTFS junction, via `mklink /J`).
#
# WHY A SEPARATE FILE FROM test_path_containment_isolated.py
# ----------------------------------------------------------------
# That file already proves the POSIX-symlink escape case for real
# wherever a real symlink can be created (this cloud sandbox included -
# see its own 19/19 run) and gracefully, EXPLICITLY skips only the
# symlink-specific sub-case on a Windows machine that lacks Developer
# Mode/elevation (POSIX `os.symlink` on Windows needs one of those).
# An NTFS JUNCTION (`mklink /J`), unlike a Windows symlink, needs
# NEITHER Developer Mode NOR elevation - it is the Windows-native
# mechanism this project's own target runtime is expected to actually
# encounter, and Python's `Path.resolve(strict=True)` on Windows
# already resolves junctions via the OS's own reparse-point
# resolution, so THIS file is what proves the real target-platform
# defense, not a mere POSIX stand-in for it.
#
# EXPLICIT, MANDATORY BEHAVIOR (per this turn's approved contract -
# never a silent SKIP that could be confused with a genuine pass):
#   - On any NON-Windows platform: prints an explicit
#     "SKIPPED - Windows-only" message and exits 0 WITHOUT recording
#     any passed/failed count - there is nothing to prove here off
#     Windows (test_path_containment_isolated.py already covers the
#     POSIX-native case).
#   - On Windows: this test MUST actually run. If `mklink` is
#     unavailable, or junction creation fails for ANY reason, that is
#     an EXPLICIT, COUNTED FAILURE - never a silent skip - because
#     `mklink /J` needs no special privilege on a normal Windows
#     account and its absence/failure means this file cannot do the
#     one job it exists for.
#
# NOT EXECUTED IN THIS SESSION'S CLOUD SANDBOX (Linux) - this is
# disclosed explicitly in the Row 19C-1 delivery report, together with
# the exact local command below for the user to run on their own
# Windows machine:
#
#     python -m ui.tests.test_path_containment_windows
#
# ROW 19C-3a SLICE 1 EXTENSION: `ui/services/paths.py`'s containment
# logic now delegates to `src/path_containment.py` (see that module's
# own tests, `ui/tests/test_path_containment_module_isolated.py`,
# which is platform-independent and gracefully skips its own POSIX-
# symlink sub-cases where unavailable). THIS file additionally proves,
# Windows-natively via a REAL `mklink /J` junction, the specific fix
# Row 19C-2c's independent broken-link finding generalized here too: a
# BROKEN junction (its target deleted, the reparse-point entry itself
# still on disk - `os.path.lexists()==True`, `Path.exists()==False`)
# must fail closed, both for `verify_real_path_contained()` directly
# and for `resolve_case_path()`'s create-chain (the OLD `candidate.
# exists()` gate there would have silently treated a broken junction
# as "not yet created"). Genuinely missing create-chains and normal
# existing paths are proven UNCHANGED by this fix.
#
# Run: python -m ui.tests.test_path_containment_windows
# ============================================================

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


if sys.platform != "win32":
    print(
        "SKIPPED - Windows-only: this file proves the NTFS-junction "
        "containment defense, which only exists on Windows "
        f"(sys.platform={sys.platform!r} here). NOT a pass, NOT a "
        "failure - see ui/tests/test_path_containment_isolated.py for "
        "the platform-independent POSIX-symlink equivalent, which DOES "
        "run (and passes) in this environment."
    )
    sys.exit(0)

# --------------------------------------------------------------
# Everything below this line runs ONLY on sys.platform == 'win32', and
# every failure from here on is an explicit, counted FAIL - never a
# skip - per this file's own mandatory-behavior contract above.
# --------------------------------------------------------------

from ui.services import paths  # noqa: E402
import path_containment as pc  # noqa: E402  (src/ is importable once ui.services.paths has run)


def make_junction(link_path: Path, target_path: Path) -> None:
    """`mklink /J` requires NO elevation and NO Developer Mode on a
    normal Windows account (unlike a Windows symlink) - a failure here
    is therefore treated as a genuine, counted test failure by the
    caller, never silently swallowed into a skip."""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {result.stdout!r} {result.stderr!r}")


tmp_root = Path(tempfile.mkdtemp(prefix="row19c1_path_containment_win_"))
tmp_outside = Path(tempfile.mkdtemp(prefix="row19c1_path_containment_win_outside_"))

try:
    try:
        junction_link = tmp_root / "junction_escape"
        make_junction(junction_link, tmp_outside)
    except Exception as error:
        check(
            "mklink /J junction creation succeeded (no elevation/Developer Mode required on a normal Windows account)",
            False,
            f"{error!r} - THIS IS A REAL FAILURE ON WINDOWS, not a reason to skip",
        )
    else:
        try:
            outside_file = tmp_outside / "outside_file.txt"
            outside_file.write_text("should never be reachable through the junction")

            expect_raises(
                paths.PathContainmentError,
                lambda: paths.verify_real_path_contained(junction_link, root=tmp_root),
                "a REAL NTFS junction physically inside root, pointing OUTSIDE root, is caught and rejected",
            )
            expect_raises(
                paths.PathContainmentError,
                lambda: paths.verify_real_path_contained(junction_link / "outside_file.txt", root=tmp_root),
                "a path THROUGH that escaping junction is also caught and rejected",
            )

            # ROW 19C-3a SLICE 1 - BROKEN NTFS JUNCTION (target deleted,
            # link/reparse-point entry itself remains) - the exact Row
            # 19C-2c lesson generalized into src/path_containment.py
            # and now proven here, Windows-natively, via a REAL mklink
            # /J junction (never a monkeypatch): os.path.lexists()
            # reports True for the broken entry, Path.exists() reports
            # False, and verify_real_path_contained() must still fail
            # closed rather than silently treating it as "nothing
            # here".
            broken_junction_outside = tmp_outside / "broken_junction_ghost"
            broken_junction_outside.mkdir()
            broken_junction_link = tmp_root / "broken_junction"
            make_junction(broken_junction_link, broken_junction_outside)
            shutil.rmtree(broken_junction_outside)  # break it - target gone, link entry remains
            try:
                check(
                    "broken junction precondition: os.path.lexists()==True (reparse-point entry itself "
                    "still on disk)",
                    os.path.lexists(broken_junction_link) is True,
                )
                check(
                    "broken junction precondition: Path.exists()==False (target cannot be resolved)",
                    broken_junction_link.exists() is False,
                )
                expect_raises(
                    paths.PathContainmentError,
                    lambda: paths.verify_real_path_contained(broken_junction_link, root=tmp_root),
                    "a REAL, BROKEN NTFS junction (target deleted) is caught and rejected by "
                    "verify_real_path_contained(), never silently treated as 'nothing here'",
                )

                # ROW 19C-3a ROOT-CONTRACT REMEDIATION, Windows-native
                # proof: the broken junction USED AS THE ROOT ITSELF.
                # The POSIX broken/ELOOP-root sub-tests in
                # test_path_containment_module_isolated.py are SKIPPED
                # on a machine without symlink privileges - THIS is the
                # authoritative broken-root proof there.
                expect_raises(
                    pc.PathContainmentError,
                    lambda: pc.list_contained_dir(broken_junction_link),
                    "shared list_contained_dir(): a BROKEN NTFS junction AS THE ROOT raises the "
                    "generic shared PathContainmentError (fail-closed, never a silent empty list)",
                )
                original_cases_dir_for_root = paths.CASES_DIR
                paths.CASES_DIR = broken_junction_link
                try:
                    expect_raises(
                        paths.PathContainmentError,
                        lambda: paths.list_case_ids(),
                        "UI list_case_ids(): CASES_DIR that is a BROKEN NTFS junction raises the "
                        "translated UI PathContainmentError",
                    )
                    expect_raises(
                        paths.UnknownCaseError,
                        lambda: paths.list_case_ids(),
                        "UI list_case_ids(): that broken-root failure is still catchable as "
                        "UnknownCaseError (existing call sites unchanged)",
                    )
                finally:
                    paths.CASES_DIR = original_cases_dir_for_root
            finally:
                try:
                    broken_junction_link.rmdir()
                except OSError:
                    pass

            # End-to-end: a CASE directory that is itself a junction -
            # same attack shape as test_path_containment_isolated.py's
            # symlinked-case-directory proof, but via the Windows-
            # native mechanism.
            #
            # ROW 19C-1 PATH CHOKE-POINT REMEDIATION: previously, only
            # resolve_case_path() caught this - list_case_ids() happily
            # discovered the junctioned case directory and
            # resolve_case_id() ALONE (the check every EXISTING
            # production caller, via ui.services.authz, actually uses)
            # accepted it as legitimate. That gap is now closed
            # DIRECTLY in the shared choke point: list_case_ids() no
            # longer lists an escaping junction, and resolve_case_id()
            # itself now also rejects it. This is the AUTHORITATIVE,
            # real Windows-native security proof (mklink /J needs no
            # elevation/Developer Mode, unlike a POSIX symlink) - it is
            # never skipped on Windows, unlike
            # test_path_containment_isolated.py's symlink sub-case.
            fake_data_dir = tmp_root / "fake_data"
            fake_cases_dir = fake_data_dir / "cases"
            fake_cases_dir.mkdir(parents=True)

            # A normal, real (non-junction) case directory - proves the
            # fix does not disturb ordinary case resolution.
            normal_case_dir = fake_cases_dir / "case_0001"
            normal_case_dir.mkdir()
            (normal_case_dir / "case.json").write_text("{}")
            (normal_case_dir / "existing_file.txt").write_text("already here")

            evil_target_dir = tmp_outside / "evil_case_target"
            evil_target_dir.mkdir()
            (evil_target_dir / "case.json").write_text("{}")
            (evil_target_dir / "secret_outside_file.txt").write_text("should never be reachable via case_0002")

            symlinked_case_dir = fake_cases_dir / "case_0002"
            make_junction(symlinked_case_dir, evil_target_dir)

            original_data_dir = paths.DATA_DIR
            original_cases_dir = paths.CASES_DIR
            paths.DATA_DIR = fake_data_dir
            paths.CASES_DIR = fake_cases_dir
            try:
                check(
                    "(1) list_case_ids() no longer discovers the junctioned case directory escaping the cases root",
                    "case_0002" not in paths.list_case_ids(),
                )
                expect_raises(
                    paths.UnknownCaseError,
                    lambda: paths.resolve_case_id("case_0002"),
                    "(2) resolve_case_id() ALONE now REJECTS the escaping junctioned case (the exact gap that was closed)",
                )
                # resolve_case_path() calls resolve_case_id() as its own
                # first step, so it now raises the same plain
                # UnknownCaseError resolve_case_id() raised - asserting
                # the broader UnknownCaseError (rather than the narrower
                # PathContainmentError) is deliberate: it is the
                # externally-observable, closed-result contract that
                # matters, not which internal layer caught it first.
                expect_raises(
                    paths.UnknownCaseError,
                    lambda: paths.resolve_case_path("case_0002"),
                    "(3) resolve_case_path() also rejects a case directory that is itself an NTFS junction escaping the cases root",
                )
                expect_raises(
                    paths.UnknownCaseError,
                    lambda: paths.resolve_case_path("case_0002", "secret_outside_file.txt"),
                    "(4) a subpath reached THROUGH the escaping junction is also rejected",
                )
                check(
                    "(5) a normal, real case directory (case_0001) and a normal file path continue to work",
                    paths.resolve_case_id("case_0001") == "case_0001"
                    and "case_0001" in paths.list_case_ids()
                    and paths.resolve_case_path("case_0001", "existing_file.txt")
                    == (normal_case_dir / "existing_file.txt").resolve(strict=True),
                )

                # ROW 19C-3a SLICE 1 - the actual fix under test: a
                # BROKEN NTFS junction as an INTERMEDIATE create-chain
                # segment. Before this fix, resolve_case_path()'s OLD
                # `candidate.exists()` gate would have seen `False` for
                # this broken junction and silently returned it as a
                # "not yet existing" candidate - exactly the Row
                # 19C-2c bug class, now closed here too, proven with a
                # REAL mklink /J junction (never a monkeypatch).
                broken_chain_ghost = tmp_outside / "broken_chain_ghost"
                broken_chain_ghost.mkdir()
                broken_chain_link = normal_case_dir / "broken_chain_child"
                make_junction(broken_chain_link, broken_chain_ghost)
                shutil.rmtree(broken_chain_ghost)
                try:
                    check(
                        "(6) broken create-chain precondition: os.path.lexists()==True",
                        os.path.lexists(broken_chain_link) is True,
                    )
                    check(
                        "(6) broken create-chain precondition: Path.exists()==False",
                        broken_chain_link.exists() is False,
                    )
                    expect_raises(
                        paths.PathContainmentError,
                        lambda: paths.resolve_case_path("case_0001", "broken_chain_child", "leaf.txt"),
                        "(6) resolve_case_path(): a BROKEN NTFS junction as an intermediate create-chain "
                        "segment now FAILS CLOSED (the Row 19C-3a fix for the OLD .exists()-based "
                        "fail-open gate) - proven Windows-natively",
                    )
                    expect_raises(
                        paths.PathContainmentError,
                        lambda: paths.resolve_case_path("case_0001", "broken_chain_child"),
                        "(6b) a BROKEN NTFS junction as the FINAL create-chain segment is also rejected",
                    )
                finally:
                    try:
                        broken_chain_link.rmdir()
                    except OSError:
                        pass

                check(
                    "(7) resolve_case_path(): a genuinely MISSING (never-created) create-chain still "
                    "returns a usable, unresolved candidate path - completely unaffected by the "
                    "broken-link fix",
                    paths.resolve_case_path("case_0001", "brand_new_dir", "brand_new_file.txt")
                    == normal_case_dir.resolve(strict=True) / "brand_new_dir" / "brand_new_file.txt",
                )

                # ROW 19C-3a SLICE 1 - SAFE internal NTFS-junction alias
                # (pointing to ANOTHER real, already-listed case
                # directory, still genuinely contained under
                # CASES_DIR) must be listed under its OWN logical name
                # - never silently merged into/replaced by its
                # target's name. Windows-native proof (the POSIX
                # equivalent in ui/tests/test_path_containment_isolated.py
                # is SKIPPED on this machine - no Developer Mode/
                # elevation - so THIS is the authoritative proof here).
                alias_case_dir = fake_cases_dir / "case_0001_alias"
                make_junction(alias_case_dir, normal_case_dir)
                try:
                    ids_with_alias = paths.list_case_ids()
                    check(
                        "(8) list_case_ids(): a SAFE internal NTFS-junction alias (pointing to ANOTHER "
                        "real, contained case directory) is listed under its OWN logical name, "
                        "alongside its target, never silently merged/renamed",
                        "case_0001_alias" in ids_with_alias and "case_0001" in ids_with_alias,
                        f"got {ids_with_alias!r}",
                    )
                    check(
                        "(8b) resolve_case_path() through the safe alias resolves to the SAME real "
                        "target file the original case_id already reaches",
                        paths.resolve_case_path("case_0001_alias", "existing_file.txt")
                        == paths.resolve_case_path("case_0001", "existing_file.txt"),
                    )
                finally:
                    try:
                        alias_case_dir.rmdir()
                    except OSError:
                        pass
            finally:
                paths.DATA_DIR = original_data_dir
                paths.CASES_DIR = original_cases_dir
        finally:
            # Junctions are removed with rmdir, not unlink - deleting
            # via shutil.rmtree(tmp_root, ...) below would otherwise
            # recurse INTO the junction target and could delete files
            # under tmp_outside instead of just the link itself.
            for junction in (junction_link, fake_cases_dir / "case_0002"):
                try:
                    junction.rmdir()
                except OSError:
                    pass
finally:
    shutil.rmtree(tmp_root, ignore_errors=True)
    shutil.rmtree(tmp_outside, ignore_errors=True)

print(f"--- test_path_containment_windows: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
