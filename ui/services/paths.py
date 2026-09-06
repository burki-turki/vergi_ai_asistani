# ============================================================
# VERGİ AI - LAWYER UI, PATHS BOOTSTRAP (Row 18a)
#
# `ui/` paketi `src/`'nin bir KOPYASI/YENİDEN YAZIMI DEĞİLDİR - var
# olan 12 onay modülünü OLDUĞU GİBİ import edip kullanır (Prensip 10).
# Bu modülün TEK işi: src/'yi import edilebilir kılmak ve DATA_DIR'i
# tek bir yerden vermek.
# ============================================================

from __future__ import annotations

import os
import sys
from pathlib import Path

from .common import UnknownCaseError

UI_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = UI_DIR.parent
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"

if str(SRC_DIR) not in sys.path:

    sys.path.insert(0, str(SRC_DIR))


def list_case_ids():
    """
    `data/cases/*` altındaki case dizinlerini listeler (bir case.json
    içeren her dizin). Yeni bir case registry İCAT EDİLMEZ - dosya
    sistemi zaten tek source of truth.

    ROW 19C-1 PATH CHOKE-POINT REMEDIATION: her aday, gerçek (symlink/
    NTFS junction çözümlenmiş) haline `Path.resolve(strict=True)` ile
    çözülür ve bu gerçek halin hâlâ `CASES_DIR`'in gerçek kökü altında
    kaldığı doğrulanır - `CASES_DIR`'i TERK EDEN bir symlink/junction
    (POSIX sembolik link veya Windows `mklink /J`) burada ASLA
    sonuçlarda görünmez. Kırık/döngüsel bir link (`OSError`/
    `RuntimeError`) veya kapsam dışına çözümlenen bir link SESSİZCE
    atlanır (skip) - ne bir hata fırlatılır ne de o girdi listelenir;
    sıradan, gerçek case dizinleri bu davranıştan etkilenmeden aynen
    döner. Bu, `resolve_case_id()`'in altında yatan asıl keşif
    mekanizması olduğu için, buradaki filtre aynı zamanda
    `resolve_case_id()`'in KENDİ allowlist kontrolünü de - o fonksiyon
    hiç değişmese bile - dolaylı olarak güçlendirir; `resolve_case_id()`
    ayrıca kendi doğrudan containment kontrolünü de aşağıda uygular
    (defense-in-depth, tek başına bu filtreye güvenmez).
    """

    if not CASES_DIR.is_dir():

        return []

    cases_dir_real = Path(os.path.realpath(str(CASES_DIR)))

    result = []
    for p in sorted(CASES_DIR.iterdir()):
        if not p.is_dir() or not (p / "case.json").exists():
            continue
        try:
            p_real = p.resolve(strict=True)
        except (OSError, RuntimeError):
            # Broken/looping symlink or junction - skip silently,
            # never raise and never list it.
            continue
        try:
            p_real.relative_to(cases_dir_real)
        except ValueError:
            # Resolves outside CASES_DIR (an escaping symlink/junction)
            # - skip silently, never list it.
            continue
        result.append(p.name)

    return sorted(result)


# ============================================================
# PAYLAŞILAN ALLOWLIST ÇÖZÜCÜ (targeted remediation, bkz. inceleme
# bulgusu: case_id 6 route'ta hiç doğrulanmadan Row 6-17 modüllerinin
# `CASES_DIR / case_id / "..."` şeklindeki DOĞRUDAN path
# birleştirmesine gidiyordu). BU FONKSİYON, case_id kullanan HER
# route/servis fonksiyonunun İLK SATIRINDA çağrılmalıdır - hiçbir
# upstream modül fonksiyonu (get_pending_path, get_canonical_path,
# inspect_pending, run_approve, glob tabanlı keşif) doğrulanmamış bir
# case_id ile ÇAĞRILMAMALIDIR.
#
# Starlette/uvicorn'un URL normalizasyonuna GÜVENİLMEZ - bu kontrol
# path birleştirmesinden ÖNCE, Python içinde, decode edilmiş DEĞER
# üzerinde çalışır. `%2e%2e` gibi encode edilmiş traversal biçimleri
# ASGI katmanı tarafından tek seviye decode edilip düz `..` olarak
# BURAYA ulaşır (aşağıdaki karakter kontrolü bunu yakalar); double-
# encoding (`%252e%252e`) decode edilmeden `%2e%2e` string'i olarak
# gelir ve gerçek bir case adıyla ASLA eşleşmediği için allowlist
# kontrolünde zaten reddedilir - iki savunma katmanı da bağımsız
# olarak yeterlidir.
# ============================================================

_FORBIDDEN_SUBSTRINGS = ("..", "/", "\\", "\x00")


def resolve_case_id(case_id):
    """
    Yalnız `list_case_ids()`'in GERÇEKTEN keşfettiği bir case dizini
    adıyla TAM eşleşen bir case_id'yi kabul eder; aksi halde
    `UnknownCaseError` (veya onun mevcut-uyumlu alt sınıfı
    `PathContainmentError`) fırlatır (boş değer, separator/traversal
    biçimleri, bilinmeyen ID'ler ve - ROW 19C-1 PATH CHOKE-POINT
    REMEDIATION ile - kökü TERK EDEN bir symlink/NTFS junction case
    dizini dahil: hepsi AYNI kapalı sonuca gider, hangi kontrolün
    tetiklendiği saldırgana sızdırılmaz).

    Bu fonksiyon, PROJE GENELİNDEKİ TEK PAYLAŞILAN allowlist/containment
    choke point'idir: `ui.services.authz` içindeki her route/servis
    girişi (`require_principal_and_case`, `authorize_or_redirect`,
    `authorize_case_access`) ve `approval_registry.py`/`live_view.py`/
    `review_registry.py`/`run_drafting_request.py` gibi aşağı akış
    servisleri, hepsi doğrudan veya dolaylı olarak BU fonksiyonu
    çağırır. Bu yüzden buraya eklenen containment kontrolü, o
    çağıranların HİÇBİRİNİN kendi kodunu değiştirmesine gerek kalmadan,
    onları da otomatik olarak kapsar - bu, sadece yeni
    `resolve_case_path()` kullanan kodu değil, VAR OLAN her
    `resolve_case_id()` tüketicisini de korumanın amaçlanan yoludur.
    """

    if not isinstance(case_id, str) or not case_id:

        raise UnknownCaseError("Geçersiz (boş) case kimliği.")

    if any(token in case_id for token in _FORBIDDEN_SUBSTRINGS):

        raise UnknownCaseError("Geçersiz case kimliği.")

    if case_id not in list_case_ids():

        raise UnknownCaseError("Bilinmeyen case kimliği.")

    # ROW 19C-1 PATH CHOKE-POINT REMEDIATION: `list_case_ids()`'in
    # kendisi artık kaçan symlink/junction'ları listelemediği için bu
    # satır çoğu zaman zaten gereksiz olacaktır (case_id yukarıdaki
    # membership kontrolünü hiç geçemez) - ama TOCTOU'ya (bu iki
    # çağrı arasında case dizininin bir junction ile DEĞİŞTİRİLMESİ)
    # ve `list_case_ids()`'in gelecekte bağımsız şekilde
    # değiştirilebilme ihtimaline karşı, containment doğrudan BURADA,
    # bağımsız bir ikinci savunma katmanı olarak da uygulanır.
    # `PathContainmentError` zaten `UnknownCaseError`'ın bir alt sınıfı
    # olduğundan, mevcut HİÇBİR `except UnknownCaseError:` çağrı
    # noktası bundan etkilenmez.
    verify_real_path_contained(CASES_DIR / case_id, root=CASES_DIR)

    return case_id


# ============================================================
# ROW 19C-1 ADDITION - realpath/`resolve(strict=True)`-based path
# CONTAINMENT (additive; `_FORBIDDEN_SUBSTRINGS` and every existing
# public error shape are preserved exactly as they were from Row 18a).
#
# UPDATED UNDER THE ROW 19C-1 PATH CHOKE-POINT REMEDIATION: the two
# defenses described below are NO LONGER split the way the original
# Row 19C-1 addition described. Originally, `resolve_case_id()` above
# was a PURE STRING allowlist check with no filesystem-realpath
# awareness at all, and only the newer, separately-called
# `resolve_case_path()` performed real containment checking - which
# left every EXISTING production caller of `resolve_case_id()` alone
# (i.e. every route via `ui.services.authz`, and every downstream
# service that trusts an already-`resolve_case_id()`-validated
# case_id string to build its own `CASES_DIR / case_id / "..."` paths)
# unprotected against a case directory that is itself a symlink
# (POSIX) or an NTFS junction/reparse point (Windows, e.g.
# `mklink /J`) escaping `CASES_DIR`. That gap has since been closed
# DIRECTLY IN THE SHARED CHOKE POINT: `list_case_ids()` now filters
# out any escaping symlink/junction entry before it can ever be
# returned, discovered, or subsequently accepted, and `resolve_case_id()`
# itself now ALSO calls `verify_real_path_contained()` as an
# independent second layer. This means the fix protects every existing
# `resolve_case_id()` consumer project-wide with zero changes required
# to any of those call sites - not just new code written against
# `resolve_case_path()`.
#
# `verify_real_path_contained()` / `resolve_case_path()` below remain
# available for callers that want the REAL, resolved `Path` object
# itself (not just a validated case_id string) and/or need to build
# and verify a path several segments deep inside a case directory in
# one call; `resolve_case_path()`'s own internal
# `verify_real_path_contained()` call is now DEFENSE-IN-DEPTH atop
# `resolve_case_id()`'s own new check, not the sole gap-closer it
# originally was.
#
# `Path.resolve(strict=True)`, on modern Python (3.8+), on both POSIX
# and Windows, fully resolves symlinks/junctions along the ENTIRE
# path, not just its final component - which is why testing containment
# only after this resolution is the correct check.
#
# Neither this addition nor `resolve_case_path()` attempt any
# cross-case isolation/authorization check: two different, each
# individually-legitimate case_ids resolving to two different real
# directories under the same real `CASES_DIR` is the normal, expected,
# SAFE case. Preventing one authenticated actor from reading/writing a
# case they are not authorized for is Row 19B's `ui.services.authz`
# layer's job - entirely orthogonal to, and unaffected by, this
# addition.
# ============================================================


class PathContainmentError(UnknownCaseError):
    """A candidate path failed the realpath/symlink-escape containment
    check - either it could not be resolved to a real, existing
    location at all, or its fully-resolved real form lies OUTSIDE the
    permitted root (the repository root, or - via `resolve_case_path()`
    - a specific case's own directory).

    Deliberately a SUBCLASS of `UnknownCaseError`, never a sibling
    exception: every existing `except UnknownCaseError:` call site
    anywhere in this project keeps working completely unchanged (this
    failure is still, and always was meant to be, indistinguishable
    from "unknown/invalid case" to any caller that does not
    specifically care to tell them apart), and the same closed,
    non-specific user-facing message applies - callers get additional
    hardening for free, with zero required changes to their own
    exception handling."""


def verify_real_path_contained(path, *, root: Path | None = None) -> Path:
    """
    Resolves `path` to its REAL, symlink/junction-free absolute form
    and verifies the result is contained within `root` (defaults to
    `BASE_DIR` - the whole repository - when `root` is not given;
    `resolve_case_path()` below passes `CASES_DIR` explicitly for its
    own, narrower check). Returns the resolved, verified-contained
    `Path` on success.

    `path` MUST already exist (`Path.resolve(strict=True)` requires
    this, and deliberately so: refusing to "verify" a path that is not
    even real yet is the fail-closed choice, not a limitation to work
    around here - see `resolve_case_path()`'s own handling of a
    not-yet-created leaf file, which explicitly resolves its PARENT
    directory instead of trying to strict-resolve the not-yet-existing
    leaf itself).

    Raises `PathContainmentError` - never a bare `OSError`/
    `FileNotFoundError`/`RuntimeError`, and NEVER silently returns an
    uncontained path - if `path` does not exist, cannot be resolved
    (e.g. a symlink loop), or resolves outside `root`.
    """

    effective_root = root if root is not None else BASE_DIR
    root_real = Path(os.path.realpath(str(effective_root)))

    try:
        candidate_real = Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PathContainmentError(
            "Path gerçek (mevcut) bir konuma çözümlenemedi."
        ) from error

    try:
        candidate_real.relative_to(root_real)
    except ValueError:
        raise PathContainmentError(
            "Path izin verilen kök dizinin dışına çözümleniyor."
        )

    return candidate_real


def resolve_case_path(case_id, *relative_parts: str) -> Path:
    """
    Combines `resolve_case_id()`'s allowlist check (which, since the
    Row 19C-1 PATH CHOKE-POINT REMEDIATION, ALREADY performs its own
    `verify_real_path_contained()` call internally) with a further,
    defense-in-depth `verify_real_path_contained()` call below, for the
    common case of locating a path inside an already-existing,
    already-discovered case directory
    (`CASES_DIR / case_id[/ *relative_parts]`).

    Every one of `relative_parts` is validated against the SAME
    `_FORBIDDEN_SUBSTRINGS` `resolve_case_id()` itself enforces on
    `case_id` (no `..`, no path separator, no NUL byte in any single
    segment) BEFORE being joined - a caller-supplied extra segment can
    never smuggle in its own traversal, independent of, and prior to,
    the realpath containment check that follows.

    The case directory itself (`CASES_DIR / case_id`) MUST exist
    (guaranteed by `resolve_case_id()` having found it via
    `list_case_ids()`) and its real form must be contained within
    `CASES_DIR`'s own real form - checked unconditionally, even when
    `relative_parts` is empty.

    When `relative_parts` names a path that ALREADY EXISTS, the FULL
    joined candidate is itself realpath-verified (catching a symlink/
    junction planted anywhere along the way, not just at the case
    directory's own root). When it does not yet exist (the caller is
    about to CREATE it), this function verifies the immediate PARENT
    directory instead - which must already exist - and returns the
    (not-yet-existing) candidate unresolved; this covers creating one
    new file or directory directly inside an already-verified,
    already-existing directory. It does NOT attempt to create, or
    verify containment through, multiple levels of not-yet-existing
    nested directories at once - a caller needing that creates each
    intermediate directory itself first, each of which is then its own
    already-existing, independently verifiable case via a fresh
    `resolve_case_path()` call. This scope boundary is deliberate: Row
    19C-1 builds this primitive as infrastructure only - it is not
    wired into any real writer this turn (see this module's own
    Row 19C-1 addition banner above).
    """

    verified_case_id = resolve_case_id(case_id)

    for part in relative_parts:
        if not isinstance(part, str) or not part or any(token in part for token in _FORBIDDEN_SUBSTRINGS):
            raise UnknownCaseError("Geçersiz path bileşeni.")

    case_dir_real = verify_real_path_contained(CASES_DIR / verified_case_id, root=CASES_DIR)

    if not relative_parts:
        return case_dir_real

    candidate = case_dir_real.joinpath(*relative_parts)

    if candidate.exists():
        return verify_real_path_contained(candidate, root=CASES_DIR)

    # Not-yet-existing leaf (about to be created): verify the
    # immediate parent instead - see this function's own docstring for
    # why this is the deliberate scope boundary rather than a gap.
    verify_real_path_contained(candidate.parent, root=CASES_DIR)
    return candidate


def to_repo_relative(path):
    """
    Tarayıcıya HİÇBİR ZAMAN ham mutlak dosya sistemi path'i
    göstermemek için (bkz. inceleme bulgusu) - repo köküne göre
    göreli, güvenli bir gösterim üretir. Repo dışında bir path
    (beklenmez ama savunma amaçlı) genel bir metinle değiştirilir.
    """

    try:

        return str(Path(path).resolve().relative_to(BASE_DIR))

    except Exception:

        return "(repo dışında bir konum)"
