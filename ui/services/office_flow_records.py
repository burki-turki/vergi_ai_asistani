# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - ORTAK TABAN
# (ui/office_deadline_flow.py'nin koşu durumu, kayıt ve sahiplik temeli)
#
# Bu modül: (1) kapalı hata kodu kümesi, (2) O_EXCL/fsync tek-yazımlık
# dosya yazıcıları, (3) sahiplik işaretli dizin açma, (4) koşu durum
# makinesi, (5) avukatın BAĞIMSIZ OKUMA kaydı, (6) kimlik anlık
# görüntüsü, (7) girdi manifesti / bayatlık karşılaştırması, (8) "sonuç
# görüldü" (yeniden kontrol) iç işareti.
#
# SINIRLAR (bilinçli):
#   - Hiçbir ağ/LLM/alt süreç import'u yok (ağ, urllib, subprocess vb.).
#   - Üç kayıt (pilot test sonucu / imha kaydı / destek özeti) BU
#     modülde DEĞİL, `office_flow_outcomes.py`'dedir.
#   - Bu modül HİÇBİR dosya silmez/budamaz.
#   - Asıl PDF'e dokunmaz: kaynak yol burada hiç görünmez.
# ============================================================

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RECORD_SCHEMA_VERSION = 1
SOFTWARE_VERSION = "office_flow_t1"

OWNER_MARKER_NAME = ".office_flow_owner"
IMHA_BINDING_NAME = ".office_flow_imha"
RUN_STATE_NAME = "run_state.json"
MANIFEST_NAME = "run_manifest.json"
READING_RECORD_NAME = "okuma_kaydi.json"
REPORT_NAME = "pilot_hesap_raporu.txt"
TMP_DIR_NAME = "tmp"
RUNS_DIRNAME = "runs"
RECORDS_DIRNAME = "kayitlar"
HISTORY_DIRNAME = "dosya_gecmisi"

REQUIRED_ASSIGNMENT_ROLE = "lawyer"

# ----------------------------------------------------------------
# KAPALI HATA KODU KÜMESİ (destek özeti yalnız bunlardan birini taşır)
# ----------------------------------------------------------------

ERROR_CODES = frozenset({
    "YETKI_YOK", "KIMLIK_TEYIDI_BASARISIZ", "ONAY_TEYIDI_BASARISIZ",
    "OKUMA_KAYDI_GECERSIZ", "OKUMA_KAYDI_MEVCUT", "OKUMA_KAYDI_YOK",
    "DURUM_GECISI_GECERSIZ", "SAHIPLIK_ISARETI_YOK", "DIZIN_MEVCUT",
    "DOSYA_MEVCUT", "YAZMA_BASARISIZ", "KAYNAK_YOK", "KAYNAK_PDF_DEGIL",
    "KAYNAK_ICERIDE", "KAYNAK_AYNI_DOSYA", "VERGI_TURU_GECERSIZ",
    "SAYFA_GECERSIZ", "KOD_GECERSIZ", "CIKARICI_BASARISIZ", "METIN_BOS",
    "METIN_COK_UZUN", "TOHUM_DOGRULAMA_BASARISIZ",
    "ADAY_YOK", "ADAY_SECIMI_GECERSIZ", "TARIH_UYUSMAZLIGI",
    "ANCHOR_BELIRSIZ", "DOGRULAMA_REDDEDILDI", "ZINCIR_ADIMI_BASARISIZ",
    "SISTEM_HESAPLAMADI", "GIRDI_DEGISTI", "INCELEME_ACIK",
    "SILME_ONAYI_YOK", "SILME_DURUMU_UYGUN_DEGIL",
    "SILME_BELIRSIZ_SAHIPLIK", "SILME_YARIM", "SILME_DOGRULAMA_BASARISIZ",
    "KAYIT_ICERIK_RED", "KAYIT_SEMASI_GECERSIZ", "PREFLIGHT_BASARISIZ",
    "DIS_YZ_PAKETI_VAR", "DIS_YZ_ORTAM_ANAHTARI_VAR", "DSN_LOOPBACK_DEGIL",
    "BIRIM_FARKLI", "SISTEM_SURUCUSU", "OFFICE_ROOT_GECERSIZ",
    "TATIL_TAKVIMI_GECERSIZ", "VERITABANI_HATASI",
    "VERITABANI_YAPILANDIRMASI_YOK", "DOSYA_ISLEMI_BASARISIZ",
    "KULLANICI_ILERLETMEDI", "BILINMEYEN_HATA", "KULLANIM_HATASI",
})

PROCESS_STEPS = ("F0", "F1", "F2", "F3", "F4", "F5", "F6")

ERROR_CATEGORIES = frozenset({
    "TEBLIG_TARIHI_SECIMI", "SURE_KURALI", "TATIL_KAYDIRMASI",
    "NEDEN_HENUZ_BELIRLENEMEDI",
})


class OfficeFlowError(Exception):
    """Mesajı YALNIZ kapalı koddur - `str(error)` içerik/yol taşıyamaz."""

    def __init__(self, code: str):
        if code not in ERROR_CODES:
            code = "BILINMEYEN_HATA"
        self.code = code
        super().__init__(code)


# ----------------------------------------------------------------
# Küçük yardımcılar
# ----------------------------------------------------------------


def canonical_bytes(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, indent=2,
    ).encode("utf-8") + b"\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_run_id() -> str:
    """Dosyadan türetilmeyen, rastgele opak koşu kimliği."""
    return uuid.uuid4().hex


_CASE_ID_RE = re.compile(r"^[a-z0-9_-]{3,64}$")
_DOSYA_KODU_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def validate_case_id(case_id) -> str:
    if not isinstance(case_id, str) or not _CASE_ID_RE.match(case_id):
        raise OfficeFlowError("KOD_GECERSIZ")
    return case_id


def validate_dosya_kodu(code) -> str:
    if not isinstance(code, str) or not _DOSYA_KODU_RE.match(code):
        raise OfficeFlowError("KOD_GECERSIZ")
    return code


def write_new_file(path, data: bytes) -> None:
    """O_CREAT|O_EXCL + fsync. ASLA üzerine yazmaz."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        raise OfficeFlowError("DOSYA_MEVCUT") from None
    except OSError:
        raise OfficeFlowError("YAZMA_BASARISIZ") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        try:
            os.unlink(str(path))
        except OSError:
            pass
        raise OfficeFlowError("YAZMA_BASARISIZ") from None


def atomic_replace_file(path, data: bytes) -> None:
    """Çalışma kaydı (koşu durumu/rapor damgası) için: yan dosyaya yaz,
    fsync, os.replace. YALNIZ bu akışın kendi çalışma kayıtları için;
    kayitlar/ altındaki üç kayıt ASLA bununla yazılmaz."""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    if os.path.lexists(str(tmp)):
        try:
            os.unlink(str(tmp))
        except OSError:
            raise OfficeFlowError("YAZMA_BASARISIZ") from None
    write_new_file(tmp, data)
    try:
        os.replace(str(tmp), str(target))
    except OSError:
        raise OfficeFlowError("YAZMA_BASARISIZ") from None


def create_owned_dir(path, *, run_id: str, kind: str) -> Path:
    """Var olan bir dizini ASLA devralmaz; O_EXCL işareti koyar."""
    target = Path(path)
    try:
        os.mkdir(str(target))
    except FileExistsError:
        raise OfficeFlowError("DIZIN_MEVCUT") from None
    except OSError:
        raise OfficeFlowError("YAZMA_BASARISIZ") from None
    write_new_file(
        target / OWNER_MARKER_NAME,
        canonical_bytes({"kayit_surumu": RECORD_SCHEMA_VERSION, "kos": run_id, "tur": kind}),
    )
    return target


def read_owner_marker(directory, *, run_id: str, kind: str) -> bool:
    """İşaret var, geçerli JSON ve (run_id, kind) ile birebir eşleşiyor mu."""
    marker = Path(directory) / OWNER_MARKER_NAME
    try:
        if marker.is_symlink() or not marker.is_file():
            return False
        data = json.loads(marker.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(data, dict) and data.get("kos") == run_id and data.get("tur") == kind
        and data.get("kayit_surumu") == RECORD_SCHEMA_VERSION
    )


# ----------------------------------------------------------------
# Koşu yolları
# ----------------------------------------------------------------


@dataclass(frozen=True)
class RunPaths:
    office_root: Path
    run_id: str
    run_dir: Path
    tmp_dir: Path
    case_id: str
    case_dir: Path
    records_dir: Path
    history_dir: Path

    @property
    def state_path(self) -> Path:
        return self.run_dir / RUN_STATE_NAME

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / MANIFEST_NAME

    @property
    def reading_path(self) -> Path:
        return self.run_dir / READING_RECORD_NAME

    @property
    def report_path(self) -> Path:
        return self.run_dir / REPORT_NAME


def build_run_paths(office_root, case_root, case_id: str, run_id: str) -> RunPaths:
    validate_case_id(case_id)
    office = Path(office_root)
    run_dir = office / RUNS_DIRNAME / run_id
    return RunPaths(
        office_root=office, run_id=run_id, run_dir=run_dir, tmp_dir=run_dir / TMP_DIR_NAME,
        case_id=case_id, case_dir=Path(case_root) / case_id,
        records_dir=office / RECORDS_DIRNAME, history_dir=office / HISTORY_DIRNAME,
    )


def ensure_office_infra(office_root) -> None:
    """runs/, kayitlar/, dosya_gecmisi/ - var olanı ezmez; yoksa açar."""
    office = Path(office_root)
    for name in (RUNS_DIRNAME, RECORDS_DIRNAME, HISTORY_DIRNAME):
        try:
            (office / name).mkdir(exist_ok=True)
        except OSError:
            raise OfficeFlowError("OFFICE_ROOT_GECERSIZ") from None


# ----------------------------------------------------------------
# Koşu durum makinesi
# ----------------------------------------------------------------

STATES = (
    "HAZIRLANIYOR", "OKUMA_KAYITLI", "SISTEM_ZINCIRI", "KARSILASTIRMA_YAPILDI",
    "UYUMLU_RAPOR_KONTROLU", "KONTROL_TAMAM", "UYUSMAZLIK_INCELEME_ACIK",
    "INCELEME_KAPALI", "GECERSIZ", "DURDURULDU", "SILME_ONAYI_BEKLIYOR",
    "SILINIYOR", "SILME_YARIM", "SILME_REDDEDILDI", "SILINDI",
)

# Hiçbir yol UYUSMAZLIK_* durumundan UYUMLU_*/KONTROL_TAMAM'a gitmez.
_TRANSITIONS = {
    "HAZIRLANIYOR": {"OKUMA_KAYITLI", "DURDURULDU"},
    "OKUMA_KAYITLI": {"SISTEM_ZINCIRI", "UYUSMAZLIK_INCELEME_ACIK", "DURDURULDU", "GECERSIZ"},
    "SISTEM_ZINCIRI": {"KARSILASTIRMA_YAPILDI", "UYUSMAZLIK_INCELEME_ACIK", "DURDURULDU", "GECERSIZ"},
    "KARSILASTIRMA_YAPILDI": {"UYUMLU_RAPOR_KONTROLU", "UYUSMAZLIK_INCELEME_ACIK", "GECERSIZ"},
    "UYUMLU_RAPOR_KONTROLU": {"KONTROL_TAMAM", "GECERSIZ"},
    "KONTROL_TAMAM": {"SILME_ONAYI_BEKLIYOR"},
    "UYUSMAZLIK_INCELEME_ACIK": {"INCELEME_KAPALI"},
    "INCELEME_KAPALI": {"SILME_ONAYI_BEKLIYOR"},
    "GECERSIZ": {"SILINIYOR", "SILME_REDDEDILDI"},
    "DURDURULDU": {"SILINIYOR", "SILME_REDDEDILDI"},
    "SILME_ONAYI_BEKLIYOR": {"SILINIYOR", "SILME_REDDEDILDI"},
    "SILINIYOR": {"SILINDI", "SILME_YARIM", "SILME_REDDEDILDI"},
    "SILME_YARIM": {"SILINIYOR", "SILINDI", "SILME_REDDEDILDI"},
    # Plan sahipliği doğrulayamadı: HİÇBİR şey silinmedi (SILME_YARIM DEĞİL).
    "SILME_REDDEDILDI": {"SILINIYOR"},
    "SILINDI": set(),
}

# Silme adımına girilebilen durumlar (UYUSMAZLIK_INCELEME_ACIK ve
# UYUMLU_RAPOR_KONTROLU/KONTROL... DEĞİL: "tetik" avukatın açık eylemidir).
DELETION_ENTRY_STATES = frozenset({
    "SILME_ONAYI_BEKLIYOR", "GECERSIZ", "DURDURULDU", "SILINIYOR", "SILME_YARIM",
    "SILME_REDDEDILDI",
})


def transition_allowed(old: str, new: str) -> bool:
    return new in _TRANSITIONS.get(old, set())


class RunState:
    """run_state.json'ın bellekteki hâli. Çalışma kaydıdır (silinir)."""

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def new(cls, *, run_id: str, case_id: str, dosya_kodu: str):
        return cls({
            "kayit_surumu": RECORD_SCHEMA_VERSION, "kos": run_id, "case_id": case_id,
            "dosya_kodu": dosya_kodu, "durum": "HAZIRLANIYOR", "gecmis": ["HAZIRLANIYOR"],
            "sonuc": None, "hata_kategorisi": None, "kontrol_turu": None,
            "rapor_gecersiz": False, "imha_token": None, "durdu_nedeni": None,
        })

    @property
    def state(self) -> str:
        return self.data["durum"]

    def set_state(self, new: str) -> None:
        if not transition_allowed(self.state, new):
            raise OfficeFlowError("DURUM_GECISI_GECERSIZ")
        self.data["durum"] = new
        self.data["gecmis"].append(new)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def save_run_state(paths: RunPaths, state: RunState) -> None:
    atomic_replace_file(paths.state_path, canonical_bytes(state.data))


def create_run_state_file(paths: RunPaths, state: RunState) -> None:
    write_new_file(paths.state_path, canonical_bytes(state.data))


def run_state_present(run_dir) -> bool:
    """Durum dosyası VAR mı (bozuk olsa bile True): `yok` ile `bozuk` ayrılır."""
    return os.path.lexists(str(Path(run_dir) / RUN_STATE_NAME))


def load_run_state(run_dir) -> RunState:
    try:
        data = json.loads((Path(run_dir) / RUN_STATE_NAME).read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        raise OfficeFlowError("DOSYA_ISLEMI_BASARISIZ") from None
    _validate_state_schema(data)
    return RunState(data)


_STATE_REQUIRED_KEYS = (
    "kayit_surumu", "kos", "case_id", "dosya_kodu", "durum", "gecmis", "sonuc",
    "hata_kategorisi", "kontrol_turu", "rapor_gecersiz", "imha_token", "durdu_nedeni",
)


def _validate_state_schema(data) -> None:
    """Eksik/yanlış tipli alan -> KAYIT_SEMASI_GECERSIZ (akış DURUR: soru, bağ,
    kayıt ve durum geçişi YOK). Akışın sonradan eklediği ek alanlar serbesttir."""
    if not isinstance(data, dict) or any(key not in data for key in _STATE_REQUIRED_KEYS):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    history = data["gecmis"]
    if (
        data["durum"] not in STATES or data["kayit_surumu"] != RECORD_SCHEMA_VERSION
        or not isinstance(data["kos"], str) or not isinstance(history, list) or not history
        or any(item not in STATES for item in history) or history[-1] != data["durum"]
        or type(data["rapor_gecersiz"]) is not bool
        or not all(data[key] is None or isinstance(data[key], str) for key in ("sonuc", "hata_kategorisi", "kontrol_turu", "durdu_nedeni"))
        or not (data["imha_token"] is None or (isinstance(data["imha_token"], str) and _TOKEN_RE.match(data["imha_token"])))
    ):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    try:
        validate_case_id(data["case_id"])
        validate_dosya_kodu(data["dosya_kodu"])
    except OfficeFlowError:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ") from None


# ----------------------------------------------------------------
# Koşu bildirimi (akışın KENDİ oluşturduğu dosyalar; kaynak yol YOK)
# ----------------------------------------------------------------

COPY_TYPES = (
    "CALISMA_DIZINI_BELGE_KOPYASI", "CIKARILMIS_METIN", "CALISMA_DOSYALARI",
    "PILOT_HESAP_RAPORU", "GECICI_DOSYALAR",
)


def _normalize_rel(rel) -> str:
    """Bildirimdeki göreli yol: '/' ayraçlı, mutlak/üst/boş parça YOK."""
    if not isinstance(rel, str):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    value = rel.replace("\\", "/")
    if not value or value.startswith("/") or ":" in value:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    return value


class RunManifest:
    """Bu koşunun KENDİ oluşturduğu dosya/dizinler. Silme üyeliği YALNIZ bu
    bildirimle belirlenir: desene uyan ama bildirimde OLMAYAN her girdi
    bilinmeyendir (silme REDDEDİLİR). Kaynak yol burada YOKTUR."""

    def __init__(self, entries=None, dirs=None):
        self.entries = list(entries or [])
        self.dirs = list(dirs or [])

    def add(self, *, root: str, rel: str, tur: str) -> None:
        if root not in ("case", "run") or tur not in COPY_TYPES:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        item = {"root": root, "rel": _normalize_rel(rel), "tur": tur}
        if item not in self.entries:
            self.entries.append(item)

    def add_dir(self, *, root: str, rel: str) -> None:
        if root not in ("case", "run"):
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        item = {"root": root, "rel": _normalize_rel(rel)}
        if item not in self.dirs:
            self.dirs.append(item)

    def file_types(self, root: str) -> dict:
        return {item["rel"]: item["tur"] for item in self.entries if item["root"] == root}

    def dir_rels(self, root: str) -> set:
        return {item["rel"] for item in self.dirs if item["root"] == root}

    def to_bytes(self) -> bytes:
        return canonical_bytes({
            "kayit_surumu": RECORD_SCHEMA_VERSION,
            # Asıl PDF: yalnız bayrak. YOL YAZILMAZ.
            "kaynak_salt_okunur": True, "entries": self.entries, "dirs": self.dirs,
        })

    @classmethod
    def load(cls, path) -> "RunManifest":
        try:
            data = json.loads(Path(path).read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            raise OfficeFlowError("DOSYA_ISLEMI_BASARISIZ") from None
        if not isinstance(data, dict) or data.get("kaynak_salt_okunur") is not True:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        entries, dirs = data.get("entries", []), data.get("dirs", [])
        if not isinstance(entries, list) or not isinstance(dirs, list):
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        manifest = cls()
        try:
            for item in entries:
                manifest.add(root=item["root"], rel=item["rel"], tur=item["tur"])
            for item in dirs:
                manifest.add_dir(root=item["root"], rel=item["rel"])
        except (KeyError, TypeError):
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ") from None
        return manifest


def save_manifest(paths: RunPaths, manifest: RunManifest) -> None:
    if paths.manifest_path.exists():
        atomic_replace_file(paths.manifest_path, manifest.to_bytes())
    else:
        write_new_file(paths.manifest_path, manifest.to_bytes())


# ----------------------------------------------------------------
# İmha jetonu bağı (koşu dizini içinde; `kayitlar/`a ASLA gitmez)
# Jeton YALNIZ bu koşuya aittir: durum dosyası yitse bile yeniden başlatma
# kendi jetonunu ve vaka/dosya kodunu BURADAN okur; başka koşunun açık
# jetonu asla kullanılmaz.
# ----------------------------------------------------------------

_TOKEN_RE = re.compile(r"^[0-9a-f]{16}$")


def imha_token_for_run(run_id: str) -> str:
    """Koşuya BAĞLI jeton: koşu kimliğinden türetilir. Kurcalanmış bir bağ
    başka koşunun jeton serisini gösteremez (eşleşme doğrulanır)."""
    return sha256_hex(("imha|" + str(run_id)).encode("utf-8"))[:16]


def write_imha_binding(paths: RunPaths, *, token: str, dosya_kodu: str) -> None:
    if not _TOKEN_RE.match(str(token)) or token != imha_token_for_run(paths.run_id):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    validate_dosya_kodu(dosya_kodu)
    write_new_file(
        paths.run_dir / IMHA_BINDING_NAME,
        canonical_bytes({
            "kayit_surumu": RECORD_SCHEMA_VERSION, "kos": paths.run_id,
            "imha_token": token, "case_id": paths.case_id, "dosya_kodu": dosya_kodu,
        }),
    )


def read_imha_binding(run_dir, *, run_id: str):
    """Geçerli ve BU koşuya ait bağ -> dict; yok/bozuk/başka koşunun -> None."""
    target = Path(run_dir) / IMHA_BINDING_NAME
    try:
        if target.is_symlink() or not target.is_file():
            return None
        data = json.loads(target.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("kos") != run_id or data.get("kayit_surumu") != RECORD_SCHEMA_VERSION:
        return None
    try:
        validate_case_id(data.get("case_id"))
        validate_dosya_kodu(data.get("dosya_kodu"))
    except OfficeFlowError:
        return None
    if not _TOKEN_RE.match(str(data.get("imha_token"))) or data["imha_token"] != imha_token_for_run(run_id):
        return None
    return data


# ----------------------------------------------------------------
# Kimlik anlık görüntüsü (oturumdaki yetkili kullanıcı belirler;
# yazılan tam ad YALNIZ ek teyittir)
# ----------------------------------------------------------------


@dataclass(frozen=True)
class IdentitySnapshot:
    user_id: int
    display_name: str
    windows_user: str
    machine_name: str
    db_time: str

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id, "display_name": self.display_name,
            "windows_user": self.windows_user, "machine_name": self.machine_name,
            "db_time": self.db_time,
        }


def _windows_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "bilinmiyor"


def capture_identity(conn, user_id: int, case_id: str, *, repository) -> IdentitySnapshot:
    """Aktif, devre dışı olmayan, bu vakaya ATANMIŞ `lawyer` rolü şart."""
    with conn.cursor() as cur:
        cur.execute("SELECT display_name, disabled FROM iam.users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None or row[1]:
            raise OfficeFlowError("YETKI_YOK")
        display_name = row[0]
        cur.execute("SELECT clock_timestamp()")
        db_time = cur.fetchone()[0].isoformat()
    assignment = repository.get_active_case_assignment(user_id, case_id)
    if assignment is None or assignment.role != REQUIRED_ASSIGNMENT_ROLE:
        raise OfficeFlowError("YETKI_YOK")
    return IdentitySnapshot(
        user_id=user_id, display_name=str(display_name), windows_user=_windows_user(),
        machine_name=platform.node() or "bilinmiyor", db_time=db_time,
    )


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text))).strip()


def confirm_full_name(typed: str, display_name: str) -> bool:
    """EK TEYİT: yazılan ad, oturumdaki kullanıcının kayıtlı adıyla birebir
    (NFC + boşluk daraltma) eşleşmeli. Aktörü SEÇMEZ/DEĞİŞTİRMEZ."""
    normalized = _normalize_name(typed)
    return bool(normalized) and normalized == _normalize_name(display_name)


# ----------------------------------------------------------------
# Avukatın bağımsız okuma kaydı (F2)
# ----------------------------------------------------------------

_TR_DATE_RE = re.compile(r"^([0-9]{2})[./]([0-9]{2})[./]([0-9]{4})$")
_ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_REF_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,64}$")


def parse_date_input(text) -> str:
    """GG.AA.YYYY / GG/AA/YYYY / YYYY-AA-GG -> ISO; gerçek takvim günü şart."""
    value = str(text).strip()
    match = _TR_DATE_RE.match(value)
    if match:
        day, month, year = match.groups()
        iso = f"{year}-{month}-{day}"
    elif _ISO_DATE_RE.match(value):
        iso = value
    else:
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    try:
        parsed = date.fromisoformat(iso)
    except ValueError:
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ") from None
    if parsed.isoformat() != iso or not (1990 <= parsed.year <= 2100):
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    return iso


def validate_stopping_ref(ref) -> str:
    """Opak referans: tarih ve 6+ ardışık rakam YASAK (içerik sızıntısı)."""
    value = "" if ref is None else str(ref).strip()
    if not _REF_RE.match(value) or re.search(r"[0-9]{6,}", value) or re.search(
        r"[0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4}", value,
    ):
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    return value


def build_reading_record(
    *, tebligat_tarihi, sayfa, kor_son_gun, adli_tatil, stopping_status, stopping_ref,
    identity: IdentitySnapshot,
) -> dict:
    iso_date = parse_date_input(tebligat_tarihi)
    iso_last = parse_date_input(kor_son_gun)
    if type(sayfa) is not int or sayfa < 1:
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    if adli_tatil not in ("yes", "no", "unknown"):
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    if stopping_status not in ("none", "present", "unknown"):
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    if stopping_status == "none":
        ref_value = validate_stopping_ref(stopping_ref)
    else:
        ref_value = validate_stopping_ref(stopping_ref) if stopping_ref else None
    return {
        "kayit_surumu": RECORD_SCHEMA_VERSION,
        "kayit_turu": "bagimsiz_okuma",
        "tebligat_tarihi": iso_date,
        "sayfa": sayfa,
        "kor_son_gun": iso_last,
        "adli_tatil": adli_tatil,
        "stopping_event_status": stopping_status,
        "stopping_event_ref": ref_value,
        "kimlik": identity.as_dict(),
    }


def write_reading_record(paths: RunPaths, record: dict) -> str:
    """O_EXCL; ikinci kez yazılamaz. Dönüş: kaydın sha256'sı (çalışma kaydı)."""
    data = canonical_bytes(record)
    write_new_file(paths.reading_path, data)
    return sha256_hex(data)


def load_reading_record(paths: RunPaths, *, expected_sha=None) -> dict:
    """`expected_sha` verilirse (koşu durumundaki `okuma_sha`) dosyanın ham
    baytlarının sha256'sı BİREBİR eşleşmelidir; değilse kayıt kullanılamaz."""
    try:
        raw = paths.reading_path.read_bytes()
        record = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        raise OfficeFlowError("OKUMA_KAYDI_YOK") from None
    if expected_sha is not None and sha256_hex(raw) != expected_sha:
        raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
    return record


# ----------------------------------------------------------------
# Girdi manifesti / bayatlık
# ----------------------------------------------------------------


def _hash_file(path: Path):
    try:
        return sha256_hex(path.read_bytes())
    except OSError:
        return None


def compute_input_manifest(case_dir, global_paths: dict) -> dict:
    """Doğrulanmış GİRDİLERİN ham bayt hash'leri (yalnız ad->sha256).
    Hesap SONUCU (deadline pending/canonical) dahil DEĞİLDİR; o ayrıca
    `deadline_fingerprint()` ile izlenir."""
    root = Path(case_dir)
    manifest = {"case.json": _hash_file(root / "case.json")}
    documents = root / "documents"
    names = []
    try:
        names = sorted(p.name for p in documents.iterdir() if p.is_dir())
    except OSError:
        names = []
    for name in names:
        base = documents / name
        manifest[f"documents/{name}/document.json"] = _hash_file(base / "document.json")
        manifest[f"documents/{name}/extractions/facts.json"] = _hash_file(
            base / "extractions" / "facts.json",
        )
        extracted = base / "extracted"
        try:
            texts = sorted(p.name for p in extracted.iterdir() if p.is_file())
        except OSError:
            texts = []
        for text_name in texts:
            manifest[f"documents/{name}/extracted/{text_name}"] = _hash_file(extracted / text_name)
    manifest["timeline/timeline.json"] = _hash_file(root / "timeline" / "timeline.json")
    for key in sorted(global_paths):
        manifest[f"global:{key}"] = _hash_file(Path(global_paths[key]))
    return manifest


def manifest_digest(manifest: dict) -> str:
    return sha256_hex(canonical_bytes(manifest))


def changed_inputs(recorded: dict, current: dict) -> list:
    """Değişen GİRDİ ADLARI (hash değil). Boşsa girdi değişmemiştir."""
    keys = sorted(set(recorded) | set(current))
    return [key for key in keys if recorded.get(key) != current.get(key)]


def deadline_fingerprint(case_dir) -> dict:
    root = Path(case_dir) / "deadlines"
    pending = None
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if entry.is_file() and entry.name.endswith(".json.pending"):
                pending = _hash_file(entry)
                break
    except OSError:
        pending = None
    return {"pending": pending, "canonical": _hash_file(root / "deadline.json")}


# ----------------------------------------------------------------
# "Sistem sonucu daha önce görüldü" iç işareti (dosya_gecmisi/)
# Üç kaydın PARÇASI DEĞİLDİR; silinmez; geliştiriciye gitmez; içeriksizdir.
# ----------------------------------------------------------------


def _history_marker_path(history_dir, dosya_kodu: str) -> Path:
    validate_dosya_kodu(dosya_kodu)
    digest = sha256_hex(dosya_kodu.encode("utf-8"))[:32]
    return Path(history_dir) / f"{digest}.json"


def result_seen_before(history_dir, dosya_kodu: str) -> bool:
    return _history_marker_path(history_dir, dosya_kodu).is_file()


def mark_result_seen(history_dir, dosya_kodu: str) -> None:
    """Yoksa O_EXCL ile yazar; varsa dokunmaz (idempotent)."""
    path = _history_marker_path(history_dir, dosya_kodu)
    if path.exists():
        return
    try:
        write_new_file(path, canonical_bytes({
            "kayit_surumu": RECORD_SCHEMA_VERSION, "sonuc_gorulmus": True,
        }))
    except OfficeFlowError as error:
        if error.code != "DOSYA_MEVCUT":
            raise


def determine_kontrol_turu(history_dir, dosya_kodu: str) -> str:
    return "YENIDEN_KONTROL" if result_seen_before(history_dir, dosya_kodu) else "ILK_KONTROL"
