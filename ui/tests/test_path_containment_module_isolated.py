# ============================================================
# ROW 19C-3a SLICE 1 - isolated tests for src/path_containment.py, the
# NEW stdlib-only, framework/domain-independent path-containment
# primitive (FORBIDDEN_SEGMENT_SUBSTRINGS / PathContainmentError /
# validate_segment / resolve_existing / resolve_for_create /
# list_contained_dir).
#
# PLATFORM-INDEPENDENT BY DESIGN, same discipline as ui/tests/test_
# path_containment_isolated.py: every check either (a) needs no
# symlink at all, or (b) attempts a REAL POSIX symlink via os.symlink
# and, ONLY for that specific sub-case, treats a privilege-related
# failure (expected on Windows without Developer Mode/elevation) as an
# EXPLICIT, clearly labeled SKIP - never silently counted as a pass.
# The Windows-native NTFS-junction equivalent for ui/services/paths.py
# is proven separately in ui/tests/test_path_containment_windows.py
# (which this turn also extends with a module-level broken-junction
# proof); this file's own POSIX self-loop/broken-link sub-tests are
# NOT re-proven there with a junction - this file already exhaustively
# covers src/path_containment.py's own logic wherever symlinks are
# available, and re-implementing every one of these cases via mklink
# /J would be pure duplication of proof, not new coverage.
#
# Every fixture lives under a fresh tempfile.mkdtemp() - this file
# NEVER reads or writes this repository's own data/ tree.
#
# Run: python -m ui.tests.test_path_containment_module_isolated
# ============================================================

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import path_containment as pc  # noqa: E402

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
    """A real, throwaway probe - the only reliable way to know whether
    this process can create a symlink right now is to actually try."""
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
    if not root.is_dir():
        return frozenset()
    return frozenset(str(p.relative_to(root)) for p in root.rglob("*"))


tmp_root = Path(tempfile.mkdtemp(prefix="row19c3a_path_containment_module_"))
tmp_outside = Path(tempfile.mkdtemp(prefix="row19c3a_path_containment_module_outside_"))

try:
    # ============================================================
    # 1) validate_segment() - acceptance/rejection matrix. Pure,
    #    no filesystem touched.
    # ============================================================

    check("validate_segment: a normal simple segment is returned UNCHANGED", pc.validate_segment("case_0001") == "case_0001")
    check("validate_segment: digits/underscore segment accepted", pc.validate_segment("abc_123") == "abc_123")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment(""), "validate_segment: empty string rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment(None), "validate_segment: None rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment(123), "validate_segment: non-string (int) rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment([]), "validate_segment: non-string (list) rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment(".."), "validate_segment: bare '..' rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment("../etc"), "validate_segment: leading traversal rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment("a/b"), "validate_segment: forward slash rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment("a\\b"), "validate_segment: backslash rejected")
    expect_raises(pc.PathContainmentError, lambda: pc.validate_segment("a\x00b"), "validate_segment: embedded NUL byte rejected")
    check(
        "validate_segment: FORBIDDEN_SEGMENT_SUBSTRINGS is the exact expected tuple (ROW 19C-3a "
        "DRIVE-RELATIVE ESCAPE REMEDIATION - ':' added)",
        pc.FORBIDDEN_SEGMENT_SUBSTRINGS == ("..", "/", "\\", "\x00", ":"),
    )

    # ============================================================
    # 1b) ROW 19C-3a DRIVE-RELATIVE ESCAPE REMEDIATION - targeted
    #     regression coverage for the independent-review Critical
    #     finding: a NOT-YET-EXISTING segment shaped like a Windows
    #     drive-relative reference (or an NTFS alternate-data-stream
    #     reference) used to defeat resolve_for_create()'s containment
    #     guarantee entirely, because Path.joinpath() silently
    #     RE-ANCHORS the whole path when the joined-in segment carries
    #     its own drive - discarding every part that came before it -
    #     and the escaped candidate, not existing yet, was returned
    #     completely unverified. Every case here is deterministic and
    #     platform-independent: none of it requires a real second
    #     drive to exist (the join-time re-anchoring hazard fires
    #     purely from pathlib's OWN string parsing, before any
    #     filesystem query is made), so these run identically on any
    #     machine/CI runner.
    # ============================================================

    _drive_relative_attack_segments = [
        ("D:not_yet_existing_evil.txt", "drive-relative filename on an arbitrary drive letter"),
        ("D:", "bare drive-relative reference, no filename at all"),
        ("C:not_yet_existing_evil.txt", "drive-relative filename on the conventional 'C' drive letter"),
        ("file.txt:stream", "NTFS alternate-data-stream reference (colon NOT in leading position)"),
        (".", "bare current-directory reference"),
        (":", "a bare colon alone"),
        ("Q:", "drive-relative reference on a drive letter that (almost certainly) does not exist - "
                "must be rejected WITHOUT the drive needing to be real"),
    ]

    for _attack_segment, _attack_label in _drive_relative_attack_segments:
        expect_raises(
            pc.PathContainmentError,
            lambda seg=_attack_segment: pc.validate_segment(seg),
            f"validate_segment: {_attack_label} ({_attack_segment!r}) is rejected",
        )

    # The exact bug: resolve_for_create() must reject every one of the
    # same segments too, as the FIRST (only) part of a create-chain -
    # this is the actual, empirically-reproduced escape path the
    # independent review demonstrated end-to-end.
    for _attack_segment, _attack_label in _drive_relative_attack_segments:
        expect_raises(
            pc.PathContainmentError,
            lambda seg=_attack_segment: pc.resolve_for_create(tmp_root, seg),
            f"resolve_for_create: {_attack_label} ({_attack_segment!r}) as the ONLY/first segment is "
            f"rejected, never silently returned as an unverified 'not yet existing' candidate",
        )

    # The same attack segment planted as a LATER part of an otherwise
    # perfectly normal, genuinely-missing create-chain (the case the
    # independent review specifically called out: a normal first part,
    # then the drive-relative escape) - must be rejected just as hard,
    # not just when it happens to be first.
    for _attack_segment, _attack_label in _drive_relative_attack_segments:
        expect_raises(
            pc.PathContainmentError,
            lambda seg=_attack_segment: pc.resolve_for_create(tmp_root, "new_directory", seg, "trailing.txt"),
            f"resolve_for_create: {_attack_label} ({_attack_segment!r}) as a LATER segment of an "
            f"otherwise-normal missing chain is also rejected",
        )

    # Using the REAL, currently-running system's own drive letter (not
    # just an arbitrary/nonexistent one) - the review's item (3): the
    # segment must be rejected even when the drive-relative reference
    # points at a drive that genuinely, verifiably exists on this
    # machine right now.
    _real_system_drive = tmp_root.drive  # e.g. "C:" on Windows, "" on POSIX
    if _real_system_drive:
        _real_drive_segment = f"{_real_system_drive}real_system_drive_evil.txt"
        expect_raises(
            pc.PathContainmentError,
            lambda: pc.validate_segment(_real_drive_segment),
            f"validate_segment: a drive-relative segment on the REAL, currently-existing system "
            f"drive ({_real_drive_segment!r}) is rejected too - this is not just an 'unknown drive' "
            f"special case",
        )
        expect_raises(
            pc.PathContainmentError,
            lambda: pc.resolve_for_create(tmp_root, _real_drive_segment),
            f"resolve_for_create: same real-drive segment ({_real_drive_segment!r}) is rejected",
        )
    else:
        skip(
            "real-system-drive drive-relative segment check",
            "this platform's paths carry no drive component (POSIX) - the arbitrary-drive-letter "
            "checks above already cover the Windows-shaped hazard platform-independently",
        )

    # No rejected attack scenario above wrote anything to disk.
    _attack_snapshot_before = snapshot_tree(tmp_root)
    for _attack_segment, _ in _drive_relative_attack_segments:
        try:
            pc.resolve_for_create(tmp_root, _attack_segment)
        except pc.PathContainmentError:
            pass
        try:
            pc.resolve_for_create(tmp_root, "new_directory", _attack_segment, "trailing.txt")
        except pc.PathContainmentError:
            pass
    _attack_snapshot_after = snapshot_tree(tmp_root)
    check(
        "resolve_for_create: none of the rejected drive-relative/ADS-colon attack attempts wrote "
        "anything to disk",
        _attack_snapshot_before == _attack_snapshot_after,
        f"diff={_attack_snapshot_before ^ _attack_snapshot_after}",
    )

    # Regression: ordinary segments, and an ordinary genuinely-missing
    # multi-level create-chain, are completely UNAFFECTED by this fix -
    # every returned candidate is still exactly what it was before, and
    # still genuinely contained under root.
    check(
        "validate_segment: ordinary segments are still accepted, unchanged, after the fix",
        pc.validate_segment("case_0001") == "case_0001" and pc.validate_segment("leaf.txt") == "leaf.txt",
    )
    _regression_result = pc.resolve_for_create(tmp_root, "brand_new_dir_x", "brand_new_dir_y", "brand_new_leaf.txt")
    check(
        "resolve_for_create: an ordinary, fully-missing multi-level chain is unaffected by the fix",
        _regression_result == tmp_root.resolve(strict=True) / "brand_new_dir_x" / "brand_new_dir_y" / "brand_new_leaf.txt",
    )
    try:
        _regression_result.relative_to(tmp_root.resolve(strict=True))
        check("resolve_for_create: the ordinary regression result is genuinely contained under root", True)
    except ValueError:
        check("resolve_for_create: the ordinary regression result is genuinely contained under root", False)

    # ============================================================
    # 2) resolve_existing() - missing root, file-as-root, normal
    #    contained path, real escape, missing path.
    # ============================================================

    expect_raises(
        pc.PathContainmentError,
        lambda: pc.resolve_existing(tmp_root, root=tmp_root / "does_not_exist_root"),
        "resolve_existing: a MISSING root is rejected",
    )

    file_as_root = tmp_root / "file_as_root.txt"
    file_as_root.write_text("not a directory")
    expect_raises(
        pc.PathContainmentError,
        lambda: pc.resolve_existing(file_as_root, root=file_as_root),
        "resolve_existing: a root that is a FILE (not a directory) is rejected",
    )

    inside_dir = tmp_root / "inside_subdir"
    inside_dir.mkdir()
    inside_file = inside_dir / "file.txt"
    inside_file.write_text("hello")

    resolved = pc.resolve_existing(inside_file, root=tmp_root)
    check(
        "resolve_existing: a normal, existing, genuinely-contained path resolves and returns its real form",
        resolved == inside_file.resolve(strict=True),
    )
    resolved_dir = pc.resolve_existing(inside_dir, root=tmp_root)
    check("resolve_existing: a contained subdirectory resolves too", resolved_dir == inside_dir.resolve(strict=True))

    outside_file = tmp_outside / "outside_file.txt"
    outside_file.write_text("nope")
    expect_raises(
        pc.PathContainmentError,
        lambda: pc.resolve_existing(outside_file, root=tmp_root),
        "resolve_existing: a real, EXISTING path genuinely outside root is rejected",
    )

    expect_raises(
        pc.PathContainmentError,
        lambda: pc.resolve_existing(tmp_root / "does_not_exist.txt", root=tmp_root),
        "resolve_existing: a genuinely non-existent path is rejected (fail-closed, never silently 'passes')",
    )

    check(
        "PathContainmentError is a plain Exception (framework-independent - NOT tied to any UnknownCaseError hierarchy)",
        issubclass(pc.PathContainmentError, Exception) and not issubclass(pc.PathContainmentError, (OSError, RuntimeError)),
    )

    # ----------------------------------------------------------------
    # 2b) Broken link + POSIX self-loop (ELOOP) - the exact Row 19C-2c
    #     lesson this module generalizes.
    # ----------------------------------------------------------------

    if symlink_creation_is_available(tmp_root):
        ghost_target = tmp_outside / "ghost_target"
        ghost_target.mkdir()
        broken_link = tmp_root / "broken_link"
        os.symlink(str(ghost_target), str(broken_link), target_is_directory=True)
        shutil.rmtree(ghost_target)  # break it - target gone, link entry remains
        try:
            check("broken link precondition: os.path.lexists()==True", os.path.lexists(broken_link) is True)
            check("broken link precondition: Path.exists()==False", broken_link.exists() is False)
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.resolve_existing(broken_link, root=tmp_root),
                "resolve_existing: a BROKEN link (lexists=True, exists=False) is rejected, never treated as missing",
            )
        finally:
            broken_link.unlink()

        loop_link = tmp_root / "loop_link"
        os.symlink("loop_link", str(loop_link))  # points to its own name -> genuine ELOOP on resolve
        try:
            check("self-loop precondition: os.path.lexists()==True", os.path.lexists(loop_link) is True)
            check("self-loop precondition: Path.exists()==False (ELOOP)", loop_link.exists() is False)
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.resolve_existing(loop_link, root=tmp_root),
                "resolve_existing: a DÖNGÜSEL (self-loop, ELOOP) link is rejected",
            )
        finally:
            loop_link.unlink()
    else:
        skip(
            "broken-link / self-loop resolve_existing() checks",
            "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation)",
        )

    # ============================================================
    # 3) resolve_for_create() - full/partial/empty create-chains,
    #    existing-file-in-middle rejection, live/broken/looping link
    #    in the middle of the chain.
    # ============================================================

    expect_raises(
        pc.PathContainmentError,
        lambda: pc.resolve_for_create(tmp_root / "no_such_root", "a", "b"),
        "resolve_for_create: a missing root is rejected before any segment is even walked",
    )

    check(
        "resolve_for_create: zero parts returns the verified root itself",
        pc.resolve_for_create(tmp_root) == tmp_root.resolve(strict=True),
    )

    fully_existing_dir = tmp_root / "fully_existing"
    fully_existing_dir.mkdir()
    fully_existing_leaf = fully_existing_dir / "leaf.txt"
    fully_existing_leaf.write_text("already here")
    check(
        "resolve_for_create: a FULLY EXISTING chain (dir + file leaf) resolves to the real leaf",
        pc.resolve_for_create(tmp_root, "fully_existing", "leaf.txt") == fully_existing_leaf.resolve(strict=True),
    )

    check(
        "resolve_for_create: a FULLY MISSING chain returns root_real joined with every part, unresolved",
        pc.resolve_for_create(tmp_root, "new_a", "new_b", "new_c.txt")
        == tmp_root.resolve(strict=True) / "new_a" / "new_b" / "new_c.txt",
    )

    partial_dir = tmp_root / "partial_existing"
    partial_dir.mkdir()
    check(
        "resolve_for_create: a PARTIALLY EXISTING chain returns the deepest verified real ancestor + missing tail",
        pc.resolve_for_create(tmp_root, "partial_existing", "new_x", "new_y.txt")
        == partial_dir.resolve(strict=True) / "new_x" / "new_y.txt",
    )

    plain_file = tmp_root / "plain_file.txt"
    plain_file.write_text("just a file")
    expect_raises(
        pc.PathContainmentError,
        lambda: pc.resolve_for_create(tmp_root, "plain_file.txt", "leaf.txt"),
        "resolve_for_create: a create-chain UNDER an existing plain FILE (not a directory) is rejected",
    )
    check(
        "resolve_for_create: the SAME existing file as the FINAL segment (no tail) is accepted, not rejected",
        pc.resolve_for_create(tmp_root, "plain_file.txt") == plain_file.resolve(strict=True),
    )

    if symlink_creation_is_available(tmp_root):
        # Live link in the middle, escaping root.
        mid_escape_target = tmp_outside / "mid_escape_target"
        mid_escape_target.mkdir()
        mid_escape_link = tmp_root / "mid_escape_link"
        os.symlink(str(mid_escape_target), str(mid_escape_link), target_is_directory=True)
        try:
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.resolve_for_create(tmp_root, "mid_escape_link", "leaf.txt"),
                "resolve_for_create: a LIVE link escaping root, in the MIDDLE of the chain, is rejected",
            )
        finally:
            mid_escape_link.unlink()
        shutil.rmtree(mid_escape_target, ignore_errors=True)

        # Broken link in the middle.
        mid_broken_target = tmp_outside / "mid_broken_target"
        mid_broken_target.mkdir()
        mid_broken_link = tmp_root / "mid_broken_link"
        os.symlink(str(mid_broken_target), str(mid_broken_link), target_is_directory=True)
        shutil.rmtree(mid_broken_target)
        try:
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.resolve_for_create(tmp_root, "mid_broken_link", "leaf.txt"),
                "resolve_for_create: a BROKEN link in the MIDDLE of the chain is rejected",
            )
        finally:
            mid_broken_link.unlink()

        # Looping link in the middle.
        mid_loop_link = tmp_root / "mid_loop_link"
        os.symlink("mid_loop_link", str(mid_loop_link))
        try:
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.resolve_for_create(tmp_root, "mid_loop_link", "leaf.txt"),
                "resolve_for_create: a DÖNGÜSEL (self-loop) link in the MIDDLE of the chain is rejected",
            )
        finally:
            mid_loop_link.unlink()
    else:
        skip(
            "resolve_for_create() live/broken/looping mid-chain link checks",
            "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation)",
        )

    # ============================================================
    # 4) list_contained_dir() - mixed valid/broken/escaping children,
    #    safe internal-link alias logical-identity preservation,
    #    deterministic order.
    # ============================================================

    listing_root = tmp_root / "listing_root"
    listing_root.mkdir()
    (listing_root / "zzz_last_dir").mkdir()
    (listing_root / "aaa_first_file.txt").write_text("x")
    (listing_root / "mmm_middle_dir").mkdir()

    # ROW 19C-3a ROOT-CONTRACT REMEDIATION: root errors RAISE (the same
    # generic PathContainmentError as every other containment failure),
    # never a silent empty list - only INDIVIDUAL child errors, after a
    # successfully-verified root, are silently skipped.
    expect_raises(
        pc.PathContainmentError,
        lambda: pc.list_contained_dir(tmp_root / "does_not_exist_listing_root"),
        "list_contained_dir: a genuinely MISSING root raises PathContainmentError (fail-closed, "
        "never a silent empty list)",
    )
    expect_raises(
        pc.PathContainmentError,
        lambda: pc.list_contained_dir(file_as_root),
        "list_contained_dir: a root that is a FILE (not a directory) raises the SAME generic error",
    )

    if symlink_creation_is_available(tmp_root):
        broken_root_target = tmp_outside / "broken_root_target"
        broken_root_target.mkdir()
        broken_root_link = tmp_root / "broken_root_link"
        os.symlink(str(broken_root_target), str(broken_root_link), target_is_directory=True)
        shutil.rmtree(broken_root_target)  # break it - target gone, link entry remains
        try:
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.list_contained_dir(broken_root_link),
                "list_contained_dir: a BROKEN-link root raises the SAME generic error",
            )
        finally:
            broken_root_link.unlink()

        loop_root_link = tmp_root / "loop_root_link"
        os.symlink("loop_root_link", str(loop_root_link))  # own name -> genuine ELOOP on resolve
        try:
            expect_raises(
                pc.PathContainmentError,
                lambda: pc.list_contained_dir(loop_root_link),
                "list_contained_dir: a DÖNGÜSEL (self-loop, ELOOP) root raises the SAME generic error",
            )
        finally:
            loop_root_link.unlink()
    else:
        skip(
            "list_contained_dir() broken/ELOOP root checks",
            "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation) - "
            "see ui/tests/test_path_containment_windows.py for the junction-based broken-root equivalent",
        )

    plain_listing = pc.list_contained_dir(listing_root)
    check(
        "list_contained_dir: all 3 normal children are listed",
        [p.name for p in plain_listing] == ["aaa_first_file.txt", "mmm_middle_dir", "zzz_last_dir"],
        f"got {[p.name for p in plain_listing]!r}",
    )
    check(
        "list_contained_dir: deterministic sort order (by name)",
        [p.name for p in plain_listing] == sorted(p.name for p in plain_listing),
    )

    if symlink_creation_is_available(tmp_root):
        # Safe internal alias: a symlink INSIDE listing_root pointing to
        # ANOTHER real directory also inside listing_root - genuinely
        # contained (real target resolves under root), but the RETURNED
        # entry must keep the ALIAS's OWN name, never silently become
        # the target's name.
        real_target_dir = listing_root / "real_target_dir"
        real_target_dir.mkdir()
        alias_link = listing_root / "alias_link"
        os.symlink(str(real_target_dir), str(alias_link), target_is_directory=True)

        # Broken child - must be silently omitted.
        broken_child_target = tmp_outside / "broken_child_target"
        broken_child_target.mkdir()
        broken_child = listing_root / "broken_child"
        os.symlink(str(broken_child_target), str(broken_child), target_is_directory=True)
        shutil.rmtree(broken_child_target)

        # Escaping child - must be silently omitted.
        escape_child_target = tmp_outside / "escape_child_target"
        escape_child_target.mkdir()
        escaping_child = listing_root / "escaping_child"
        os.symlink(str(escape_child_target), str(escaping_child), target_is_directory=True)

        try:
            mixed_listing = pc.list_contained_dir(listing_root)
            mixed_names = [p.name for p in mixed_listing]
            check(
                "list_contained_dir: broken and escaping children are silently OMITTED, safe ones (incl. the "
                "safe alias) are all present",
                set(mixed_names) == {
                    "aaa_first_file.txt", "mmm_middle_dir", "zzz_last_dir", "real_target_dir", "alias_link",
                },
                f"got {sorted(mixed_names)!r}",
            )
            check(
                "list_contained_dir: mixed listing is still deterministically sorted by name",
                mixed_names == sorted(mixed_names),
            )

            alias_entry = next(p for p in mixed_listing if p.name == "alias_link")
            check(
                "list_contained_dir: the safe internal alias's returned Path keeps its OWN logical name "
                "('alias_link'), never silently renamed to its resolved target's name ('real_target_dir')",
                alias_entry.name == "alias_link" and alias_entry.parent == listing_root,
            )
            check(
                "list_contained_dir: the alias's real target IS genuinely resolvable/contained (this is a "
                "SAFE internal alias, not a broken one)",
                alias_entry.resolve(strict=True) == real_target_dir.resolve(strict=True),
            )
        finally:
            alias_link.unlink()
            broken_child.unlink()
            escaping_child.unlink()
            shutil.rmtree(escape_child_target, ignore_errors=True)
    else:
        skip(
            "list_contained_dir() safe-alias/broken/escaping child checks",
            "this process/OS could not create a symlink (likely Windows without Developer Mode/elevation)",
        )

    # ============================================================
    # 5) No filesystem write, ever, from any "create" path.
    # ============================================================

    no_write_root = tmp_root / "no_write_root"
    no_write_root.mkdir()
    (no_write_root / "existing_dir").mkdir()
    before_snapshot = snapshot_tree(no_write_root)

    pc.resolve_for_create(no_write_root, "brand_new_a", "brand_new_b", "brand_new_c.txt")
    pc.resolve_for_create(no_write_root, "existing_dir", "not_yet_here.txt")
    try:
        pc.resolve_for_create(no_write_root, "existing_dir", "..", "escape.txt")
    except pc.PathContainmentError:
        pass
    try:
        pc.resolve_for_create(no_write_root / "nope", "a")
    except pc.PathContainmentError:
        pass

    after_snapshot = snapshot_tree(no_write_root)
    check(
        "resolve_for_create() never writes to disk - the tree is byte-for-byte, entry-for-entry unchanged "
        "after several calls, including ones that raise",
        before_snapshot == after_snapshot,
        f"diff={before_snapshot ^ after_snapshot}",
    )

finally:
    shutil.rmtree(tmp_root, ignore_errors=True)
    shutil.rmtree(tmp_outside, ignore_errors=True)

print(f"--- test_path_containment_module_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
sys.exit(1 if failed else 0)
