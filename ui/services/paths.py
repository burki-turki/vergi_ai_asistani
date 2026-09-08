# ============================================================
# VERGİ AI - LAWYER UI, PATHS BOOTSTRAP (Row 18a)
#
# `ui/` paketi `src/`'nin bir KOPYASI/YENİDEN YAZIMI DEĞİLDİR - var
# olan 12 onay modülünü OLDUĞU GİBİ import edip kullanır (Prensip 10).
# Bu modülün TEK işi: src/'yi import edilebilir kılmak ve DATA_DIR'i
# tek bir yerden vermek.
#
# ROW 19C-3a SLICE 1 - THIN DELEGATION LAYER: this module's own
# containment logic (originally a self-contained Row 19C-1 addition,
# later independently duplicated by Row 19C-2c's drafting-request
# facade/adapter once the SAME "Path.exists() cannot tell missing from
# broken/looping" gap was found and fixed there too) has been EXTRACTED
# into `src/path_containment.py` - the ONE stdlib-only, framework-
# independent primitive. `CASES_DIR`/`BASE_DIR`/`DATA_DIR`/`SRC_DIR`
# and every PUBLIC function signature/return type below are UNCHANGED;
# each function's OWN body now delegates to the shared module and
# translates its generic `path_containment.PathContainmentError` into
# this module's own `PathContainmentError` (still a `UnknownCaseError`
# subclass - every existing `except UnknownCaseError:` call site
# project-wide keeps working, completely unchanged) at the call
# boundary. `CASES_DIR` is NEVER cached/imported-by-value anywhere in
# this file - every function below reads the CURRENT module-level
# value at call time, preserving the existing monkeypatch test seam
# (`paths.CASES_DIR = fake_cases_dir`, as several test files already
# do) exactly as before.
# ============================================================

from __future__ import annotations

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

import path_containment as _path_containment  # noqa: E402


def list_case_ids():
    """
    `data/cases/*` altındaki case dizinlerini listeler (bir case.json
    içeren her dizin). Yeni bir case registry İCAT EDİLMEZ - dosya
    sistemi zaten tek source of truth.

    ROW 19C-3a SLICE 1: containment-safe doğrudan çocuk listesi artık
    paylaşılan `path_containment.list_contained_dir(CASES_DIR)`'tan
    (o fonksiyonun kendi containment garantisiyle - kırık/döngüsel/
    kaçan HERHANGİ bir çocuk sessizce atlanır) alınır; bu güvenli liste
    üzerinde `is_dir()`/`case.json` üyelik kontrolleri BU fonksiyonda
    (domain-özgü, `path_containment.py`'nin bilmediği bir kural olarak)
    UYGULANIR - önce containment, SONRA üyelik, ASLA ters sırada.
    `CASES_DIR`'i TERK EDEN bir symlink/junction (POSIX sembolik link
    veya Windows `mklink /J`) burada ASLA sonuçlarda görünmez; kırık/
    döngüsel bir link de aynı şekilde sessizce atlanır - ne bir hata
    fırlatılır ne de o girdi listelenir. Dönen isimler, her doğrudan
    çocuğun KENDİ mantıksal adıdır (`path_containment.list_contained_
    dir()`'in kendi garantisi - bir güvenli internal alias'ın adı asla
    hedefinin adıyla değiştirilmez), sıralama korunur.

    ROW 19C-3a ROOT-CONTRACT REMEDIATION: `CASES_DIR`'in KENDİSİ eksik,
    kırık/döngüsel bir link veya dizin-olmayan bir şeyse bu artık
    SESSİZCE boş liste DEĞİLDİR - paylaşılan modül fail-closed generic
    `path_containment.PathContainmentError` fırlatır ve BU fonksiyon
    onu açıkça yakalayıp bu modülün KENDİ `PathContainmentError`'ına
    (`UnknownCaseError` alt sınıfı - mevcut her `except
    UnknownCaseError:` çağrı noktası değişmeden yakalamaya devam eder)
    `raise ... from error` ile çevirir. Eski `if not CASES_DIR.
    is_dir(): return []` pre-gate'i KALDIRILMIŞTIR - kökün kendisinin
    doğrulanamadığı bir durumda "hiç case yok" ile "kök güvensiz/
    çözülemez" birbirinden ayırt edilemez hale gelirdi; onaylanan
    sözleşme fail-closed davranıştır. YALNIZ kök başarıyla
    doğrulandıktan sonra tekil güvensiz çocuklar sessizce atlanır -
    kök hatası ile çocuk hatası asla birbirine karıştırılmaz.

    Bu, `resolve_case_id()`'in altında yatan asıl keşif mekanizması
    olduğu için, buradaki filtre aynı zamanda `resolve_case_id()`'in
    KENDİ allowlist kontrolünü de - o fonksiyon hiç değişmese bile -
    dolaylı olarak güçlendirir; `resolve_case_id()` ayrıca kendi
    doğrudan containment kontrolünü de aşağıda uygular
    (defense-in-depth, tek başına bu filtreye güvenmez).
    """

    try:
        contained_children = _path_containment.list_contained_dir(CASES_DIR)
    except _path_containment.PathContainmentError as error:
        raise PathContainmentError(
            "Case kök dizini containment doğrulamasından geçemedi (eksik, çözülemiyor veya dizin "
            "değil)."
        ) from error

    result = []
    for p in contained_children:
        if not p.is_dir() or not (p / "case.json").exists():
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

# ROW 19C-3a SLICE 1: bound to the shared module's OWN constant - no
# second, independently-maintained copy of this tuple exists anywhere
# in this project any more.
_FORBIDDEN_SUBSTRINGS = _path_containment.FORBIDDEN_SEGMENT_SUBSTRINGS


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
#
# ROW 19C-3a SLICE 1: both functions below are now THIN wrappers over
# `path_containment.resolve_existing()`/`resolve_for_create()` - see
# this module's own top-of-file header comment. `resolve_case_path()`'s
# OLD `candidate.exists()` fail-open gate (the exact bug class Row
# 19C-2c independently found and fixed in the drafting-request facade/
# adapter - `Path.exists()` cannot distinguish "genuinely not yet
# created" from "a broken or looping link is here") is GONE: the
# shared `resolve_for_create()` gates on `os.path.lexists()` instead,
# so a broken/looping link anywhere in `relative_parts` is now ALWAYS
# routed through full containment verification rather than silently
# treated as a not-yet-existing leaf.
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
    exception handling.

    ROW 19C-3a SLICE 1: raised here ONLY as an explicit, caught-and-
    translated ('raise ... from error') response to the shared
    `path_containment.PathContainmentError` - never a plain re-export
    or subclass of it (that module is framework-independent by design
    and must never be imported by anything expecting THIS project's
    own `UnknownCaseError` hierarchy)."""


def verify_real_path_contained(path, *, root: Path | None = None) -> Path:
    """
    Resolves `path` to its REAL, symlink/junction-free absolute form
    and verifies the result is contained within `root` (defaults to
    `BASE_DIR` - the whole repository - when `root` is not given,
    read at CALL TIME, never cached; `resolve_case_path()` below
    passes `CASES_DIR` explicitly for its own, narrower check).
    Returns the resolved, verified-contained `Path` on success.

    `path` MUST already exist (`Path.resolve(strict=True)` requires
    this, and deliberately so: refusing to "verify" a path that is not
    even real yet is the fail-closed choice, not a limitation to work
    around here - see `resolve_case_path()`'s own handling of a
    not-yet-created leaf, which delegates to the shared `path_
    containment.resolve_for_create()` instead of trying to strict-
    resolve a not-yet-existing candidate directly).

    ROW 19C-3a SLICE 1: a thin wrapper over the shared `path_
    containment.resolve_existing()` primitive - see this module's own
    top-of-file header comment. Raises `PathContainmentError` - never a
    bare `OSError`/`FileNotFoundError`/`RuntimeError`, and NEVER
    silently returns an uncontained path - if `path` does not exist,
    cannot be resolved (e.g. a broken or looping symlink/junction), or
    resolves outside `root`; the SAME generic message covers every one
    of these causes (see the shared module's own "INDISTINGUISHABLE
    FAILURE MODES" header comment - the exact underlying reason is
    never leaked to the caller).
    """

    effective_root = root if root is not None else BASE_DIR
    try:
        return _path_containment.resolve_existing(path, root=effective_root)
    except _path_containment.PathContainmentError as error:
        raise PathContainmentError(
            "Path containment doğrulaması başarısız (mevcut değil, çözümlenemiyor veya izin verilen "
            "kök dizinin dışına çözümleniyor)."
        ) from error


def resolve_case_path(case_id, *relative_parts: str) -> Path:
    """
    Combines `resolve_case_id()`'s allowlist check (which, since the
    Row 19C-1 PATH CHOKE-POINT REMEDIATION, ALREADY performs its own
    `verify_real_path_contained()` call internally) with a further,
    defense-in-depth containment verification below, for the common
    case of locating a path inside an already-existing, already-
    discovered case directory (`CASES_DIR / case_id[/ *relative_parts]`).

    The case directory itself (`CASES_DIR / case_id`) MUST exist
    (guaranteed by `resolve_case_id()` having found it via
    `list_case_ids()`) and its real form must be contained within
    `CASES_DIR`'s own real form - checked unconditionally, even when
    `relative_parts` is empty.

    ROW 19C-3a SLICE 1: `relative_parts` is no longer validated by a
    local loop here - the shared `path_containment.resolve_for_create()`
    below validates every segment itself (the SAME `_FORBIDDEN_
    SUBSTRINGS`/`FORBIDDEN_SEGMENT_SUBSTRINGS` rule: no `..`, no path
    separator, no NUL byte in any single segment) BEFORE ever touching
    the filesystem, and walks the whole chain: an already-existing
    segment (checked via `os.path.lexists()`, NEVER `Path.exists()` -
    see the shared module's own "ROW 19C-2c BROKEN-LINK LESSON,
    GENERALIZED" header comment) is unconditionally containment-
    verified, whether it is a live, broken, or looping link; the first
    genuinely not-yet-existing segment (and everything after it) is
    returned unresolved, joined onto the deepest already-verified real
    ancestor. This function itself creates nothing - see the shared
    module's own "NO WRITES, EVER" header comment.
    """

    verified_case_id = resolve_case_id(case_id)

    case_dir_real = verify_real_path_contained(CASES_DIR / verified_case_id, root=CASES_DIR)

    try:
        return _path_containment.resolve_for_create(case_dir_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise PathContainmentError(
            "Path containment doğrulaması başarısız (geçersiz path bileşeni, kök dizinin dışına "
            "çözümleniyor, veya mevcut bir dosyanın altına path üretilmeye çalışılıyor)."
        ) from error


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
