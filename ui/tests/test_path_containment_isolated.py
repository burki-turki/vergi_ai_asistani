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

finally:
    shutil.rmtree(tmp_root, ignore_errors=True)
    shutil.rmtree(tmp_outside, ignore_errors=True)

print(f"--- test_path_containment_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
sys.exit(1 if failed else 0)
