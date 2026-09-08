# ============================================================
# VERGİ AI - ROW 19C-3a SLICE 1: SHARED PATH-CONTAINMENT FOUNDATION.
#
# The ONE stdlib-only, framework/domain-independent primitive for
# "is this filesystem path really, after resolving every symlink/NTFS
# junction along the way, still inside this root" - extracted from the
# pattern `ui/services/paths.py` (Row 19C-1) and `ui/services/
# drafting_request_mutation_facade.py`/`drafting_request_mutation_
# adapters.py` (Row 19C-2c) each independently arrived at and proved
# correct on their own. This module carries NO `ui.*` import, NO other
# `src/*` domain import, and NO module-level filesystem root of its
# own (no `CASES_DIR`, no `BASE_DIR`) - every caller supplies its own
# root explicitly, every call. `ui/services/paths.py` becomes a thin
# delegation layer on top of this module (see that module's own Row
# 19C-3a header comment) - Row 19C-3a Slice 2+ is expected to migrate
# the remaining CLI-only writers onto the SAME primitive rather than
# each growing its own copy.
#
# ROW 19C-2c BROKEN-LINK LESSON, GENERALIZED
# -------------------------------------------------------------------
# `Path.exists()` FOLLOWS a symlink/junction and returns `False` for
# BOTH "genuinely nothing at this name" AND "something is at this
# name, but it's a broken or looping (ELOOP) link" - two entirely
# different situations that must be treated differently: the first is
# safe (nothing to escape through), the second must always be routed
# through a full containment check (a broken/looping link could still
# resolve to something meaningful once its target changes, and must
# never be silently treated as "not yet created"). This module uses
# `os.path.lexists()` - which reports `True` for ANY filesystem entry
# at that exact name, resolving or not - as the ONLY gate that decides
# "nothing here at all" vs. "something here that needs verifying".
# `Path.exists()` is never called anywhere in this module.
#
# INDISTINGUISHABLE FAILURE MODES (deliberate)
# -------------------------------------------------------------------
# Every containment failure this module raises (missing, broken link,
# ELOOP, root itself missing/not-a-directory, real escape outside
# root) carries the SAME generic message - a caller/attacker can never
# learn from the error text alone which specific condition triggered
# it. Segment-shape rejection (`validate_segment()`) is a distinct
# failure class - it happens BEFORE any filesystem resolution is even
# attempted and reveals nothing about what does or does not exist on
# disk - so it is allowed its own, differently-worded message.
#
# NO WRITES, EVER
# -------------------------------------------------------------------
# Nothing in this module creates, opens, or modifies a file or
# directory. `resolve_for_create()` only ever COMPUTES a candidate
# path for a caller that is *about* to create something there - the
# actual creation remains entirely the caller's own responsibility,
# exactly as `ui.services.paths.resolve_case_path()`'s own pre-Row-
# 19C-3a docstring already established for its not-yet-existing-leaf
# case.
#
# ROW 19C-3a DRIVE-RELATIVE ESCAPE REMEDIATION (targeted fix)
# -------------------------------------------------------------------
# An independent review found that a NOT-YET-EXISTING segment shaped
# like a Windows drive-relative reference (`"D:"`, `"D:file.txt"`) or
# an NTFS alternate-data-stream reference (`"file.txt:stream"`)
# defeated `resolve_for_create()`'s containment guarantee entirely:
# `Path.joinpath()` on Windows silently RE-ANCHORS the whole path when
# the joined-in segment carries its own drive, discarding every part
# that came before it - and since the escaped candidate typically does
# not exist yet, `os.path.lexists()` correctly (but insufficiently)
# classifies it as "not yet created" and the old code returned it
# completely unverified, with zero relation to `root`. This is closed
# with THREE independent layers, each sufficient on its own: (1) `":"`
# is now a forbidden substring - no segment may contain a colon at
# all, closing both the drive-designator and the ADS-stream case; (2)
# `validate_segment()` additionally parses every segment with BOTH
# `PureWindowsPath` and `PurePosixPath` and rejects anything carrying a
# drive/root/anchor or that does not round-trip as exactly one, single,
# unchanged relative component - platform-independent by construction,
# so this catches a Windows-anchoring hazard even when the check itself
# runs on POSIX, and vice versa; (3) `resolve_for_create()` additionally
# verifies, AFTER every single-segment join and BEFORE any filesystem
# query, that the joined candidate's own `.parent`/`.name` still equal
# the exact parent/segment that produced it - a pure, no-filesystem-
# touching invariant that would independently catch this exact class of
# bug even if layers (1)/(2) had a future gap.
# ============================================================

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

FORBIDDEN_SEGMENT_SUBSTRINGS = ("..", "/", "\\", "\x00", ":")

_CONTAINMENT_FAILURE_MESSAGE = "Path containment doğrulaması başarısız."


class PathContainmentError(Exception):
    """A path segment was rejected, or a candidate path could not be
    verified as genuinely contained within its required root. Carries
    a single generic message across every distinct underlying cause
    (missing, broken/looping link, root itself invalid, real escape) -
    see this module's own header comment, "INDISTINGUISHABLE FAILURE
    MODES". Framework-independent: callers (e.g. `ui.services.paths`)
    are expected to catch this at their own boundary and translate it
    into their own, framework-specific exception type - this class is
    never meant to cross into UI/route code directly."""


def validate_segment(segment) -> str:
    """Rejects a non-string, empty, forbidden-substring-containing, or
    structurally-anchoring path segment; returns it UNCHANGED on
    success. Never touches the filesystem - a pure, synchronous input
    check.

    Beyond the `FORBIDDEN_SEGMENT_SUBSTRINGS` denylist (which alone
    already rejects every colon, closing both the Windows drive-
    designator and NTFS alternate-data-stream cases - see this
    module's own header comment, "ROW 19C-3a DRIVE-RELATIVE ESCAPE
    REMEDIATION"), every segment is ALSO parsed with BOTH
    `PureWindowsPath` and `PurePosixPath` and rejected if either parse
    carries a drive, root, or anchor, or does not round-trip as
    EXACTLY one relative component equal to the original segment
    (this also rejects `"."`, which normalizes away to zero parts, and
    is a second, independent, platform-agnostic layer against any
    future re-anchoring hazard neither today's denylist nor today's
    review happened to enumerate). Every rejection in this function -
    including these structural ones - raises the SAME generic
    `PathContainmentError` message; the exact rule that tripped is
    never revealed."""
    if not isinstance(segment, str) or not segment:
        raise PathContainmentError("Geçersiz (boş veya string olmayan) path bileşeni.")
    if any(token in segment for token in FORBIDDEN_SEGMENT_SUBSTRINGS):
        raise PathContainmentError("Geçersiz path bileşeni.")
    if segment in (".", ".."):
        raise PathContainmentError("Geçersiz path bileşeni.")
    for view in (PureWindowsPath(segment), PurePosixPath(segment)):
        if view.drive or view.root or view.anchor:
            raise PathContainmentError("Geçersiz path bileşeni.")
        if view.parts != (segment,):
            raise PathContainmentError("Geçersiz path bileşeni.")
    return segment


def _resolve_root(root) -> Path:
    """Shared root-resolution step for every public function below:
    `root` MUST already exist and MUST be a real directory (never
    lazily created, never assumed) - see this module's own header
    comment, "NO WRITES, EVER"."""
    try:
        root_real = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE) from error
    if not root_real.is_dir():
        raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE)
    return root_real


def _join_verified_child(parent: Path, segment: str) -> Path:
    """Joins `segment` (which MUST already have passed
    `validate_segment()`) onto `parent` and verifies the join could not
    have silently re-anchored/discarded `parent` - the exact Windows
    drive-relative-path hazard this module's own header comment, "ROW
    19C-3a DRIVE-RELATIVE ESCAPE REMEDIATION", describes:
    `Path.joinpath()` treats a segment carrying its own drive/root/
    anchor as re-anchoring the WHOLE path, silently dropping every part
    that came before it. This check is independent of, and does not
    rely on, `validate_segment()` already having rejected such a
    segment - it re-verifies the STRUCTURAL result of the join itself,
    purely via `.parent`/`.name` equality, and touches the filesystem
    NOT AT ALL. Raises `PathContainmentError` (the same generic
    containment-failure message every other real-escape case in this
    module uses) if the join did not produce a path whose own parent is
    exactly `parent` and whose own name is exactly `segment`."""
    candidate = parent / segment
    if candidate.parent != parent or candidate.name != segment:
        raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE)
    return candidate


def resolve_existing(path, *, root) -> Path:
    """Resolves `path` to its REAL, symlink/junction-free absolute
    form and verifies the result is contained within `root`'s own
    real form. `root` is REQUIRED (no default - this module holds no
    notion of a "default" root of its own) and MUST already exist as
    a real directory. `path` MUST already exist (`Path.resolve(strict=
    True)` requires this - refusing to "verify" a path that is not
    even real yet is the fail-closed choice). Returns the resolved,
    verified-contained `Path` on success; raises `PathContainmentError`
    - the SAME generic message regardless of cause - if `root` is
    missing/not-a-directory, `path` does not exist, cannot be resolved
    (e.g. a symlink loop), or resolves outside `root`."""
    root_real = _resolve_root(root)
    try:
        candidate_real = Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE) from error
    try:
        candidate_real.relative_to(root_real)
    except ValueError as error:
        raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE) from error
    return candidate_real


def resolve_for_create(root, *parts) -> Path:
    """Walks `parts` one segment at a time, starting from `root`
    (which MUST already exist as a real, verified directory), and
    returns a candidate `Path` suitable for a caller that is ABOUT TO
    CREATE something there - this function itself creates nothing
    (see this module's own header comment, "NO WRITES, EVER").

    Every segment is first validated via `validate_segment()` (which,
    since the ROW 19C-3a DRIVE-RELATIVE ESCAPE REMEDIATION - see this
    module's own header comment - already rejects any segment that
    could re-anchor a join). For each segment, in order: `_join_
    verified_child()` joins it onto the current verified ancestor and
    independently re-checks the join's own structural safety (a second,
    filesystem-untouching layer against the same hazard, kept even
    though `validate_segment()` should already have rejected the
    segment - see `_join_verified_child()`'s own docstring). If
    `os.path.lexists()` on that joined candidate is `False` (NEVER
    `Path.exists()` - see this module's own header comment, "ROW
    19C-2c BROKEN-LINK LESSON, GENERALIZED"), that segment and every
    remaining one are treated as genuinely not-yet-created - the walk
    stops there; every remaining segment is joined on, ONE AT A TIME
    through the SAME `_join_verified_child()` structural check (never a
    single unchecked multi-part `joinpath()`), with NO filesystem query
    of any kind against any of them, and the resulting candidate is
    returned. If `lexists()` is `True` (a live, broken, or looping
    link, or a genuine file/directory), the segment is UNCONDITIONALLY
    verified via `resolve_existing()` against the fixed, original
    `root` - a broken or looping link is therefore NEVER silently
    treated as "not yet existing". When that existing segment is NOT
    the final one, it must also resolve to a real DIRECTORY - a
    create-chain can never be produced underneath an existing plain
    file.

    Raises `PathContainmentError` (the same generic message throughout)
    on any segment-validation failure, any escape (including a joined
    candidate whose own `.parent`/`.name` no longer match the ancestor/
    segment that produced it), or an attempt to walk through an
    existing non-directory segment. Returns `root`'s own verified real
    form unchanged when `parts` is empty."""
    for part in parts:
        validate_segment(part)

    root_real = _resolve_root(root)

    current = root_real
    remaining = list(parts)
    while remaining:
        part = remaining.pop(0)
        candidate = _join_verified_child(current, part)
        if not os.path.lexists(candidate):
            tail = candidate
            for missing_part in remaining:
                tail = _join_verified_child(tail, missing_part)
            return tail
        verified = resolve_existing(candidate, root=root_real)
        if remaining and not verified.is_dir():
            raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE)
        current = verified
    return current


def list_contained_dir(root) -> list:
    """Returns a list of `Path` objects for every DIRECT child of
    `root` that is genuinely, real-path-contained within `root` -
    filtered PURELY on containment, never on entry type (a caller
    wanting only directories, or only case-shaped entries, applies
    that filter itself on top of this list - see `ui.services.
    paths.list_case_ids()`'s own use of this function).

    ROOT ERRORS RAISE; CHILD ERRORS SKIP - never conflated (ROW
    19C-3a root-contract remediation): `root` is verified FIRST, via
    the same `_resolve_root()` every other public function here uses
    (`Path.resolve(strict=True)` + must-be-a-directory) - a missing,
    broken-link, looping (ELOOP), or non-directory root raises the
    generic `PathContainmentError` (the SAME single message as every
    other containment failure in this module - the caller/attacker
    never learns WHICH root condition failed). A silent empty list
    for an unverifiable root would make a containment DECISION
    impossible for the caller - that behavior is deliberately
    forbidden by the approved shared-module contract. Only AFTER the
    root has been successfully verified is each INDIVIDUAL child
    checked: an unsafe child (broken link, looping link, or one that
    resolves outside `root`) is silently OMITTED, never raised for
    and never aborts the rest of the listing. A directory-listing
    failure on the ALREADY-VERIFIED root (a race/permission change
    between verification and iteration) is a root-level failure and
    raises too - never degraded to an empty list.

    Each returned `Path` is the child's OWN name/path directly under
    `root` (e.g. `root / child_name`) - NEVER the resolved real target
    - so a safe internal symlink/junction alias never loses its own
    logical identity (its own on-disk name) merely because containment
    verification had to resolve through it internally.

    Deterministic order: sorted by entry name."""
    root_path = Path(root)
    root_real = _resolve_root(root_path)

    try:
        entries = sorted(root_path.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise PathContainmentError(_CONTAINMENT_FAILURE_MESSAGE) from error

    result = []
    for entry in entries:
        try:
            entry_real = entry.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        try:
            entry_real.relative_to(root_real)
        except ValueError:
            continue
        result.append(entry)

    return result
