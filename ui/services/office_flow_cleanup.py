# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - F6 SİLME (BİLDİRİM + SAHİPLİK DOĞRULAMALI)
#
# YALNIZ bu koşunun oluşturduğu VE koşu bildiriminde (run_manifest.json)
# KAYITLI olan pilot kopyalarını siler. Üyelik YALNIZ bildirimden gelir:
# kapalı tür deseni yalnız TÜRÜ belirler, üyelik vermez. Desene uyan ama
# bildirimde olmayan (ör. büronun kendi `baska.pdf`/`buro_notu.json`/
# `tmp/not.docx` dosyası) HER girdi bilinmeyendir -> hiçbir şey silinmez,
# REDDEDILDI. Asıl PDF'e, büronun müvekkil dosyasına ve arşive hiçbir
# koşulda dokunmaz (kaynak yol bu modülde HİÇ görünmez).
#
# PROSEDÜR: plan (yalnız okur) -> [belirsizlik/yanlış hedef => hiçbir şey
# silinmez, REDDEDILDI] -> imha kaydı BASLADI -> sil -> doğrula ->
# SONUC (TAMAMLANDI yalnız doğrulamadan SONRA; yarım kalırsa KISMEN).
# Süreç silme sırasında ölürse son kayıt BASLADI kalır; yeniden başlatmada
# YALNIZ BU koşunun kendi jetonu (koşu dizinindeki bağ dosyası) kullanılır
# ve yalnız KALAN bildirimli öğeler silinir.
#
# `shutil.rmtree` KULLANILMAZ: yalnız plana alınmış dosyalar tek tek, sonra
# boş dizinler silinir. Bağlantı/junction/aygıt girdisi veya bildirimde
# olmayan HERHANGİ bir girdi => belirsiz sahiplik. Kök dizinlerin gerçek
# yolu PLAN anında dondurulur; silme sırasında kök başka bir yere işaret
# ediyorsa hiçbir şey silinmez.
# `TAMAMLANDI` YALNIZ pilot kopyaları içindir; veritabanı işlem kayıtları
# silinmez ve bu ifade onları kapsamaz.
#
# Bu modül `kayitlar/`, `dosya_gecmisi/` altına DOKUNMAZ (yalnız imha kaydı
# YAZAR; silmez/budamaz).
# ============================================================

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ui.services.office_flow_outcomes import (
    build_imha_record, imha_records_for, new_imha_token, write_imha_record,
)
from ui.services.office_flow_records import (
    COPY_TYPES, IMHA_BINDING_NAME, MANIFEST_NAME, OWNER_MARKER_NAME, READING_RECORD_NAME,
    REPORT_NAME, RUN_STATE_NAME, TMP_DIR_NAME, OfficeFlowError, RunManifest, RunPaths,
    read_owner_marker,
)

# ----------------------------------------------------------------
# Kapalı tür listesi (YALNIZ tür belirler; üyelik bildirimden gelir)
# ----------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_WORK_SUFFIXES = (".json", ".pending", ".bak", ".tmp")

_RUN_WORK_FILES = frozenset({RUN_STATE_NAME, MANIFEST_NAME, READING_RECORD_NAME})
_RUN_INFRA_TMP_SUFFIX = ".tmp"

# Koşu kökünde bildirimden ÖNCE var olan / bildirimi taşıyan akış-iç dosyaları:
# bunlar bildirimde aranmaz (bildirimin kendisi dahil), adıyla bilinir.
RUN_INFRA_NAMES = frozenset({
    OWNER_MARKER_NAME, IMHA_BINDING_NAME, RUN_STATE_NAME, MANIFEST_NAME,
    RUN_STATE_NAME + ".tmp", MANIFEST_NAME + ".tmp",
})


def _is_work_name(name: str) -> bool:
    return bool(_NAME_RE.match(name)) and name.endswith(_WORK_SUFFIXES)


def classify_case_file(rel_posix: str):
    """Vaka dizini altındaki bir DOSYA için tür; kapalı listede yoksa None."""
    parts = rel_posix.split("/")
    name = parts[-1]
    if rel_posix == OWNER_MARKER_NAME:
        return "INFRA"
    if rel_posix == "case.json":
        return "CALISMA_DOSYALARI"
    if len(parts) >= 3 and parts[0] == "documents":
        # documents/<doc>/...
        if len(parts) == 3:
            if name == "document.json":
                return "CALISMA_DOSYALARI"
            if _NAME_RE.match(name) and name.lower().endswith(".pdf"):
                return "CALISMA_DIZINI_BELGE_KOPYASI"
            return None
        sub = parts[2]
        if sub == "extracted" and len(parts) == 4 and _NAME_RE.match(name) and name.endswith(".txt"):
            return "CIKARILMIS_METIN"
        if sub in ("manual_input", "extractions") and _is_work_name(name):
            return "CALISMA_DOSYALARI"
        return None
    if parts[0] in ("timeline", "deadlines") and _is_work_name(name):
        return "CALISMA_DOSYALARI"
    return None


def classify_run_file(rel_posix: str):
    parts = rel_posix.split("/")
    name = parts[-1]
    if len(parts) == 1:
        if name in (OWNER_MARKER_NAME, IMHA_BINDING_NAME):
            return "INFRA"
        if name in _RUN_WORK_FILES or (
            name.endswith(_RUN_INFRA_TMP_SUFFIX) and name[: -len(_RUN_INFRA_TMP_SUFFIX)] in _RUN_WORK_FILES
        ):
            return "CALISMA_DOSYALARI"
        if name == REPORT_NAME or (name.startswith("pilot_hesap_raporu") and name.endswith(".txt")):
            return "PILOT_HESAP_RAPORU"
        return None
    if parts[0] == TMP_DIR_NAME:
        return "GECICI_DOSYALAR"
    return None


# ----------------------------------------------------------------
# Bildirim kaydı: koşu sırasında oluşan girdilerin bildirime işlenmesi
# ----------------------------------------------------------------


def _is_link(path: str) -> bool:
    try:
        return os.path.islink(path) or os.path.isjunction(path)
    except OSError:
        return True


def snapshot_tree(root, prefix: str = "") -> tuple:
    """(dosyalar, dizinler): `root` altındaki bağlantı OLMAYAN girdilerin
    '/' ayraçlı göreli yolları (`prefix` eklenir). Yalnız okur."""
    files, dirs = set(), set()
    start = Path(root)
    if not os.path.lexists(str(start)) or _is_link(str(start)):
        return files, dirs
    stack = [(start, prefix)]
    while stack:
        current, rel_prefix = stack.pop()
        try:
            entries = list(os.scandir(str(current)))
        except OSError:
            continue
        for entry in entries:
            if _is_link(entry.path):
                continue
            rel = f"{rel_prefix}{entry.name}"
            try:
                if entry.is_dir(follow_symlinks=False):
                    dirs.add(rel)
                    stack.append((Path(entry.path), rel + "/"))
                elif entry.is_file(follow_symlinks=False):
                    files.add(rel)
            except OSError:
                continue
    return files, dirs


def register_new_entries(manifest: RunManifest, root_name: str, before: tuple, after: tuple) -> int:
    """`after - before` farkını bildirime yazar (dosya türü desenle belirlenir;
    türü belirlenemeyen dosya KAYDEDİLMEZ -> silmede bilinmeyen sayılır).
    Dönüş: kaydedilemeyen (sınıflanamayan) yeni dosya sayısı."""
    classify = classify_case_file if root_name == "case" else classify_run_file
    new_files = sorted(after[0] - before[0])
    new_dirs = sorted(after[1] - before[1])
    skipped = 0
    for rel in new_dirs:
        manifest.add_dir(root=root_name, rel=rel)
    for rel in new_files:
        tur = classify(rel)
        if tur is None or tur == "INFRA":
            if tur is None:
                skipped += 1
            continue
        manifest.add(root=root_name, rel=rel, tur=tur)
    return skipped


# ----------------------------------------------------------------
# Plan (yalnız okur)
# ----------------------------------------------------------------


@dataclass
class DeletionPlan:
    ok: bool
    refusal_code: str | None
    files: list = field(default_factory=list)       # (Path, tur, root_name)
    dirs: list = field(default_factory=list)        # Path (alt dizinler; kökler hariç)
    roots: list = field(default_factory=list)       # (Path, kind)
    roots_real: dict = field(default_factory=dict)  # kind -> PLAN anında dondurulmuş gerçek yol
    manifest_paths: list = field(default_factory=list)  # bildirimdeki her girdinin mutlak yolu
    unknown_count: int = 0
    unregistered_count: int = 0                     # desene uyan ama bildirimde olmayan
    unclassified_count: int = 0                     # kapalı tür listesinde olmayan / bağlantı / okunamayan
    counts: dict = field(default_factory=dict)

    def type_counts(self) -> list:
        return [{"tur": tur, "adet": self.counts[tur]} for tur in COPY_TYPES if self.counts.get(tur)]


def _expand_dirs(files_by_rel: dict, dirs_set: set) -> set:
    """Bildirimdeki dosya/dizinlerin ÜST dizinleri de akışın kendi dizinleridir."""
    implied = set(dirs_set)
    for rel in list(files_by_rel) + list(dirs_set):
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            implied.add("/".join(parts[:i]))
    return implied


def _walk(root: Path, classify, root_name: str, plan: DeletionPlan, manifest: RunManifest) -> None:
    registered = manifest.file_types(root_name)
    known_dirs = _expand_dirs(registered, manifest.dir_rels(root_name))
    stack = [(root, "")]
    while stack:
        current, prefix = stack.pop()
        try:
            entries = list(os.scandir(str(current)))
        except OSError:
            plan.unknown_count += 1
            plan.unclassified_count += 1
            continue
        for entry in entries:
            rel = f"{prefix}{entry.name}"
            if _is_link(entry.path):
                plan.unknown_count += 1
                plan.unclassified_count += 1
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                plan.unknown_count += 1
                plan.unclassified_count += 1
                continue
            if is_dir:
                if rel not in known_dirs:
                    plan.unknown_count += 1
                    plan.unregistered_count += 1
                    continue
                plan.dirs.append(Path(entry.path))
                stack.append((Path(entry.path), rel + "/"))
            elif is_file:
                tur = classify(rel)
                infra_by_name = root_name == "run" and prefix == "" and entry.name in RUN_INFRA_NAMES
                if tur is None:
                    plan.unknown_count += 1
                    plan.unclassified_count += 1
                    continue
                if root_name == "case" and rel == OWNER_MARKER_NAME:
                    infra_by_name = True
                if not infra_by_name:
                    # Üyelik YALNIZ bildirimden; tür bildirimdeki ile uyuşmalı.
                    if registered.get(rel) != tur:
                        plan.unknown_count += 1
                        plan.unregistered_count += 1
                        continue
                plan.files.append((Path(entry.path), tur, root_name))
                if tur != "INFRA":
                    plan.counts[tur] = plan.counts.get(tur, 0) + 1
            else:
                plan.unknown_count += 1
                plan.unclassified_count += 1


def _is_empty_dir(path: Path) -> bool:
    try:
        return not any(True for _ in os.scandir(str(path)))
    except OSError:
        return False


def _load_manifest_for_plan(paths: RunPaths):
    """(bildirim, hata_var). Yok -> boş bildirim (yalnız akış-iç dosyalar
    kalabilir); VAR ama bozuk -> hata."""
    if not os.path.lexists(str(paths.manifest_path)):
        return RunManifest(), False
    try:
        return RunManifest.load(paths.manifest_path), False
    except OfficeFlowError:
        return RunManifest(), True


def build_deletion_plan(paths: RunPaths, *, allow_empty_unmarked: bool = False) -> DeletionPlan:
    """Yalnız OKUR. Hedefler: (1) vaka dizini, (2) koşu dizini. Her ikisi
    de: gerçek dizin (bağlantı değil), sahiplik işareti (run_id+tur)
    eşleşiyor. Biri yoksa (zaten silinmiş) atlanır. Bildirimde olmayan
    HERHANGİ bir girdi => belirsiz sahiplik."""
    plan = DeletionPlan(ok=True, refusal_code=None)
    manifest, manifest_bad = _load_manifest_for_plan(paths)
    if manifest_bad:
        plan.ok, plan.refusal_code = False, "SILME_BELIRSIZ_SAHIPLIK"
        return plan
    targets = (
        (Path(paths.case_dir), "case_dir", "case", classify_case_file),
        (Path(paths.run_dir), "run_dir", "run", classify_run_file),
    )
    for root, kind, root_name, classify in targets:
        if not os.path.lexists(str(root)):
            continue
        if _is_link(str(root)) or not root.is_dir():
            plan.ok, plan.refusal_code = False, "SILME_BELIRSIZ_SAHIPLIK"
            return plan
        if not read_owner_marker(root, run_id=paths.run_id, kind=kind):
            # Yarım kalmış silmeden arta kalan, BOŞ ve işaretsiz kök: yalnız
            # açık bir imha kaydı (BASLADI) varken devralınır (içeriği yok).
            if allow_empty_unmarked and _is_empty_dir(root):
                plan.roots.append((root, kind))
                plan.roots_real[kind] = Path(os.path.realpath(str(root)))
                continue
            plan.ok, plan.refusal_code = False, "SAHIPLIK_ISARETI_YOK"
            return plan
        plan.roots.append((root, kind))
        plan.roots_real[kind] = Path(os.path.realpath(str(root)))
        _walk(root, classify, root_name, plan, manifest)
    for item in manifest.entries:
        base = paths.case_dir if item["root"] == "case" else paths.run_dir
        plan.manifest_paths.append(Path(base) / item["rel"])
    for item in manifest.dirs:
        base = paths.case_dir if item["root"] == "case" else paths.run_dir
        plan.manifest_paths.append(Path(base) / item["rel"])
    if plan.unknown_count:
        plan.ok, plan.refusal_code = False, "SILME_BELIRSIZ_SAHIPLIK"
    return plan


# ----------------------------------------------------------------
# Silme
# ----------------------------------------------------------------


class FsOps:
    """Enjekte edilebilir dosya sistemi işlemleri (test hata enjeksiyonu)."""

    def unlink(self, path) -> None:
        os.unlink(str(path))

    def rmdir(self, path) -> None:
        os.rmdir(str(path))


@dataclass
class DeletionResult:
    outcome: str                 # TAMAMLANDI | KISMEN | REDDEDILDI
    token: str | None
    refusal_code: str | None
    type_counts: list
    remaining_counts: dict = field(default_factory=dict)


def _within_roots(path: Path, plan: DeletionPlan) -> bool:
    """Yol, PLAN anında dondurulmuş gerçek kök yollarından birinin içinde mi;
    kökün gerçek yolu o zamandan beri DEĞİŞTİYSE (bağlantı değişimi) HAYIR."""
    real = Path(os.path.realpath(str(path)))
    for root, kind in plan.roots:
        frozen = plan.roots_real.get(kind)
        if frozen is None:
            continue
        if Path(os.path.realpath(str(root))) != frozen:
            continue
        if real == frozen or frozen in real.parents:
            return True
    return False


def _remaining(plan: DeletionPlan) -> tuple:
    remaining_files = [item for item in plan.files if os.path.lexists(str(item[0]))]
    remaining_dirs = [d for d in plan.dirs if os.path.lexists(str(d))]
    roots_left = [r for r in plan.roots if os.path.lexists(str(r[0]))]
    return remaining_files, remaining_dirs, roots_left


def _manifest_leftovers(plan: DeletionPlan) -> list:
    """Bildirimdeki girdilerden hâlâ var olanlar (doğrulama: HİÇBİRİ kalmamalı)."""
    return [p for p in plan.manifest_paths if os.path.lexists(str(p))]


def _items_for_record(plan: DeletionPlan, remaining_files, result_kind: str) -> list:
    """kopya_turleri: tür başına planlanan adet; sonuç türü kalan var mı."""
    remaining_by = {}
    for _path, tur, _root in remaining_files:
        if tur != "INFRA":
            remaining_by[tur] = remaining_by.get(tur, 0) + 1
    items = []
    for tur in COPY_TYPES:
        planned = plan.counts.get(tur, 0)
        if not planned:
            continue
        if result_kind == "PLANLANDI":
            sonuc = "PLANLANDI"
        else:
            sonuc = "KISMEN" if remaining_by.get(tur) else "TAMAMLANDI"
        items.append({"tur": tur, "adet": planned, "sonuc": sonuc})
    return items


def deletion_started(records_dir, token) -> bool:
    """Bu jetonda bir silme denemesi BAŞLADI mı (BASLADI kaydı var mı)."""
    return any(rec.get("asama") == "BASLADI" for _seq, rec in imha_records_for(records_dir, token))


def record_refusal(records_dir, *, token=None, now=None) -> str:
    """Silme HİÇ başlamadı: tek SONUC kaydı REDDEDILDI (TAMAMLANDI DEĞİL).
    Jetonda bir silme denemesi ZATEN başlamışsa (BASLADI/KISMEN) 'hiç başlamadı'
    anlamı yanlış olurdu: mevcut kayıtlar (KISMEN/açık BASLADI) KORUNUR, yeni kayıt yazılmaz."""
    if token is not None and deletion_started(records_dir, token):
        return token
    reject_token = token or new_imha_token()
    write_imha_record(records_dir, reject_token, build_imha_record(
        asama="SONUC", kopya_turleri=[], genel_sonuc="REDDEDILDI", now=now,
    ))
    return reject_token


def execute_deletion(
    paths: RunPaths, *, records_dir, token=None, fs=None, now=None, confirmed: bool = False,
) -> DeletionResult:
    """`confirmed`: avukatın AYRI onayı (çağıran akış alır). Onaysız çağrı
    hiçbir şey yapmaz (SILME_ONAYI_YOK)."""
    if not confirmed:
        raise OfficeFlowError("SILME_ONAYI_YOK")
    fs = fs or FsOps()
    resume = token is not None and last_imha_stage(records_dir, token) in ("BASLADI", "SONUC")
    plan = build_deletion_plan(paths, allow_empty_unmarked=resume)
    if not plan.ok:
        # Hiçbir şey silinmez. Tek, SONUC kaydı: REDDEDILDI (TAMAMLANDI DEĞİL).
        return DeletionResult(
            "REDDEDILDI", record_refusal(records_dir, token=token, now=now), plan.refusal_code, [],
        )

    token = token or new_imha_token()
    planned_items = _items_for_record(plan, plan.files, "PLANLANDI")
    write_imha_record(records_dir, token, build_imha_record(
        asama="BASLADI", kopya_turleri=planned_items, now=now,
    ))

    # Silme sırası: vaka dosyaları -> vaka alt dizinleri -> vaka kökü;
    # koşu dosyaları (durum/bildirim/bağ/işaret HARİÇ) -> koşu alt dizinleri;
    # en SON: koşu bildirim/durum/bağ/işaret dosyaları ve koşu kökü.
    case_root = next((r for r, k in plan.roots if k == "case_dir"), None)
    run_root = next((r for r, k in plan.roots if k == "run_dir"), None)
    keep_last_names = {MANIFEST_NAME, RUN_STATE_NAME, IMHA_BINDING_NAME, OWNER_MARKER_NAME}
    last_order = {MANIFEST_NAME: 0, RUN_STATE_NAME: 1, IMHA_BINDING_NAME: 2, OWNER_MARKER_NAME: 3}

    def delete_file(path):
        if not _within_roots(path, plan):
            return  # asla kök dışı
        try:
            fs.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def delete_dir(path):
        if not _within_roots(path, plan):
            return
        try:
            fs.rmdir(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    case_files = [p for p, _t, root in plan.files if root == "case" and p.name != OWNER_MARKER_NAME]
    case_marker = [p for p, _t, root in plan.files if root == "case" and p.name == OWNER_MARKER_NAME]
    run_files_first = [
        p for p, _t, root in plan.files
        if root == "run" and not (p.parent == run_root and p.name in keep_last_names)
    ]
    run_files_last = sorted(
        (p for p, _t, root in plan.files
         if root == "run" and p.parent == run_root and p.name in keep_last_names),
        key=lambda p: last_order[p.name],
    )

    def only_infra_left(root, names) -> bool:
        try:
            return {entry.name for entry in os.scandir(str(root))} <= set(names)
        except OSError:
            return False

    try:
        for path in case_files:
            delete_file(path)
        case_dirs = sorted(
            (d for d in plan.dirs if case_root is not None and case_root in d.parents),
            key=lambda d: len(d.parts), reverse=True,
        )
        for directory in case_dirs:
            delete_dir(directory)
        # İşaret ve kök YALNIZ içerik tamamen gittiyse silinir: yarım kalan
        # silme yeniden başlatmada sahiplik işaretiyle devam edebilsin.
        if case_root is not None and os.path.lexists(str(case_root)) and only_infra_left(
            case_root, {OWNER_MARKER_NAME},
        ):
            for path in case_marker:
                delete_file(path)
            delete_dir(case_root)

        for path in run_files_first:
            delete_file(path)
        run_dirs = sorted(
            (d for d in plan.dirs if run_root is not None and run_root in d.parents),
            key=lambda d: len(d.parts), reverse=True,
        )
        for directory in run_dirs:
            delete_dir(directory)
        case_gone = case_root is None or not os.path.lexists(str(case_root))
        if (
            run_root is not None and case_gone
            and only_infra_left(run_root, keep_last_names)
        ):
            # bildirim -> durum -> bağ -> işaret EN SON: çökme anında boş-işaretsiz
            # kök kalabilir (devralınır); bağ, durum yitse de jetonu koşuya bağlar.
            for path in run_files_last:
                delete_file(path)
            delete_dir(run_root)
    except Exception:
        # Beklenmeyen hata: doğrulamaya git (KISMEN üretilir); BaseException
        # (süreç ölümü simülasyonu dahil) YAKALANMAZ -> son kayıt BASLADI kalır.
        pass

    remaining_files, remaining_dirs, roots_left = _remaining(plan)
    leftovers = _manifest_leftovers(plan)
    complete = not remaining_files and not remaining_dirs and not roots_left and not leftovers
    outcome = "TAMAMLANDI" if complete else "KISMEN"
    write_imha_record(records_dir, token, build_imha_record(
        asama="SONUC", kopya_turleri=_items_for_record(plan, remaining_files, outcome),
        genel_sonuc=outcome, now=now,
    ))
    remaining_counts = {}
    for _p, tur, _r in remaining_files:
        if tur != "INFRA":
            remaining_counts[tur] = remaining_counts.get(tur, 0) + 1
    return DeletionResult(
        outcome, token, None if complete else "SILME_YARIM", plan.type_counts(), remaining_counts,
    )


def last_imha_stage(records_dir, token: str):
    records = imha_records_for(records_dir, token)
    return records[-1][1].get("asama") if records else None
