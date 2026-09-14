import hashlib
import os
import json

from datetime import date

from jsonschema import Draft202012Validator

# CORPUS POLICY FOUNDATION: the ONE shared, decision-free path-
# containment primitive (Row 19C-3a Slice 1) - used to close the
# raw os.path.join() escape in validate_files_exist() below and to
# guard the new file-content admissibility/quality checks this
# version adds.
import path_containment

# CORPUS POLICY FOUNDATION: pure, side-effect-free module (no file
# I/O at import time) - used by the new corpus-admissibility check
# below to load the corpus policy's document_family_rules/quality_
# gates. `manifest_validator` -> `corpus_policy_validator` is a
# one-directional edge (corpus_policy_validator never imports this
# module back), so no import cycle is introduced.
import corpus_policy_validator


# ============================================================
# VERGİ AI - MANIFEST VALIDATOR V2.1
#
# V2.1:
# - Bakanlar Kurulu Kararı belge türü desteği
# - karar_tarihi temporal doğrulamaları
# - süre uzatma relation semantic kontrolleri
# - mevcut V2 public API korunmuştur
#
# CORPUS POLICY FOUNDATION EKİ:
# - validate_files_exist() artık path_containment üzerinden
#   containment-doğrulamalı (T15 sınıfı ham join kapatıldı)
# - YENİ additive fonksiyon validate_corpus_admissibility_and_quality()
#   ve validate_manifest_file() orkestrasyonuna 13. adım olarak eklendi
# ============================================================


# ============================================================
# DOSYA YOLLARI
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)

MEVZUAT_DIR = os.path.join(
    DATA_DIR,
    "mevzuat"
)

MANIFEST_PATH = os.path.join(
    DATA_DIR,
    "documents.json"
)

SCHEMA_PATH = os.path.join(
    DATA_DIR,
    "documents.schema.json"
)


# ============================================================
# JSON OKU
# ============================================================

def load_json(
    path
):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(
            file
        )


# ============================================================
# TARİH PARSE
# ============================================================

def parse_date(
    value
):

    if value is None:
        return None

    return date.fromisoformat(
        value
    )


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    manifest,
    schema
):

    validator = Draft202012Validator(
        schema
    )

    errors = sorted(
        validator.iter_errors(
            manifest
        ),
        key=lambda error:
            list(error.path)
    )

    messages = []

    for error in errors:

        path = ".".join(
            str(item)
            for item
            in error.path
        )

        if not path:
            path = "root"

        messages.append(
            f"{path}: {error.message}"
        )

    return messages


# ============================================================
# DUPLICATE DOCUMENT ID
# ============================================================

def validate_unique_document_ids(
    documents
):

    errors = []

    seen = set()

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        if document_id in seen:

            errors.append(
                "Tekrarlanan document_id: "
                f"{document_id}"
            )

        seen.add(
            document_id
        )

    return errors


# ============================================================
# DUPLICATE ACTIVE FILE
# ============================================================

def validate_unique_active_files(
    documents
):

    errors = []

    seen = {}

    for document in documents:

        if not document.get(
            "active",
            True
        ):
            continue

        file_name = document.get(
            "file_name"
        )

        if file_name in seen:

            errors.append(
                "Aynı aktif dosya birden fazla "
                "manifest kaydında kullanılıyor: "
                f"{file_name}"
            )

        seen[
            file_name
        ] = document.get(
            "document_id"
        )

    return errors


# ============================================================
# DOSYA VAR MI?
# ============================================================

def validate_files_exist(
    documents
):

    errors = []

    for document in documents:

        active = document.get(
            "active",
            True
        )

        ingest = document.get(
            "ingest",
            {}
        )

        ingest_enabled = ingest.get(
            "enabled",
            True
        )

        if not active:
            continue

        if not ingest_enabled:
            continue

        file_name = document.get(
            "file_name"
        )

        # CORPUS POLICY FOUNDATION (§L containment closure): a
        # containment failure (escape, broken/looping link) is
        # deliberately reported with the SAME "dosya bulunamadı"
        # message a genuinely missing file gets - manifest-derived
        # file_name is never trusted for a raw os.path.join()+exists()
        # check again (see src/path_containment.py's own "INDISTIN-
        # GUISHABLE FAILURE MODES" contract).
        if not isinstance(file_name, str) or not file_name:

            errors.append(
                "Aktif ve ingest açık belge için "
                "dosya bulunamadı: "
                f"{file_name}"
            )

            continue

        candidate = os.path.join(
            MEVZUAT_DIR,
            file_name
        )

        try:

            path_containment.resolve_existing(
                candidate,
                root=MEVZUAT_DIR,
            )

        except path_containment.PathContainmentError:

            errors.append(
                "Aktif ve ingest açık belge için "
                "dosya bulunamadı: "
                f"{file_name}"
            )

    return errors


# ============================================================
# CORPUS POLICY ADMISSIBILITY + STAGE-1 QUALITY
#
# YENİ (Corpus Policy Foundation) additive fonksiyon: her belgeyi
# data/corpus_policy/corpus_policy.json'un document_family_rules'una
# karşı doğrular (aile admission'ı, zorunlu provenance alanları) ve,
# yalnız gerçekten ingest edilebilir (active + ingest.enabled)
# belgeler için, policy_foundation aşaması dosya-içerik kalite
# kapılarını (%PDF magic-byte, max dosya boyutu, cross-document
# ham-hash dedup) uygular.
#
# `policy=None` iken gerçek, repo-committed corpus policy'yi yükler
# (corpus_policy_validator.load_policy() - kendi bağımsız sabiti,
# bu modülün MEVZUAT_DIR/MANIFEST_PATH fixture-redirection'ından
# AYRI); testler açık bir `policy=` sözlüğü geçirerek bu fonksiyonu
# tamamen izole çağırabilir.
# ============================================================

def _corpus_policy_gate_threshold(policy, gate_id):

    for gate in policy.get("quality_gates", []) or []:

        if gate.get("gate_id") == gate_id:

            return gate.get("threshold")

    return None


def _sha256_of_file(path):

    sha256 = hashlib.sha256()

    with open(path, "rb") as file:

        while True:

            block = file.read(1024 * 1024)

            if not block:

                break

            sha256.update(block)

    return sha256.hexdigest()


def validate_corpus_policy_admissibility(
    documents,
    policy=None,
):

    errors = []

    warnings = []

    if policy is None:

        policy = corpus_policy_validator.load_policy()

    family_rules = policy.get("document_family_rules", {}) or {}

    max_file_size = _corpus_policy_gate_threshold(
        policy,
        "max_file_size_bytes",
    )

    seen_hashes = {}

    for document in documents:

        document_id = document.get("document_id")

        belge_turu = document.get("belge_turu")

        rule = family_rules.get(belge_turu)

        if rule is None:

            errors.append(
                f"{document_id}: belge_turu='{belge_turu}' için "
                "corpus policy document_family_rules'da tanımlı "
                "bir kural yok."
            )

            continue

        # ----------------------------------------------------
        # ADMISSION
        #
        # CORPUS POLICY FOUNDATION F2 REMEDIATION: exact fail-closed
        # matrix (user-approved binding decision) -
        #   admission="allowed"    -> passes this check (other checks
        #                              below still apply)
        #   admission="deferred"   -> fail-closed ERROR; prerequisites
        #                              not yet satisfied, may not enter
        #                              a bundle regardless of an
        #                              otherwise-empty required_
        #                              provenance_fields list
        #   admission="prohibited" -> fail-closed ERROR (unchanged)
        #   anything else (missing/unrecognized value - reachable only
        #   when this function is called standalone with a hand-
        #   crafted `policy=` dict that bypasses corpus_policy_
        #   validator's own closed-vocabulary schema check) -> fail-
        #   closed ERROR; never silently treated as allowed
        # ----------------------------------------------------

        admission = rule.get("admission")

        if admission == "prohibited":

            errors.append(
                f"{document_id}: belge_turu='{belge_turu}' corpus "
                "policy tarafından admission=prohibited olarak "
                "işaretlenmiş; bu aileden belge kabul edilemez."
            )

        elif admission == "deferred":

            prerequisites = rule.get("prerequisites") or []

            errors.append(
                f"{document_id}: belge_turu='{belge_turu}' corpus "
                "policy tarafından admission=deferred olarak "
                "işaretlenmiş; bu aile için prerequisites "
                "tamamlanmadan belge bundle'a giremez "
                "(admission=deferred, prerequisites: "
                + (", ".join(prerequisites) if prerequisites else "yok")
                + ")."
            )

        elif admission != "allowed":

            errors.append(
                f"{document_id}: belge_turu='{belge_turu}' için "
                "corpus policy admission değeri tanınmıyor: "
                f"{admission!r}."
            )

        # ----------------------------------------------------
        # REQUIRED PROVENANCE FIELDS (alan-bazlı, dosya erişimi
        # gerektirmez - ingest.enabled=False belgeler dahil TÜM
        # kayıtlara uygulanır).
        # ----------------------------------------------------

        for field_name in rule.get("required_provenance_fields", []) or []:

            value = document.get(field_name)

            if value is None or value == "":

                errors.append(
                    f"{document_id}: corpus policy gereği zorunlu "
                    f"provenance alanı boş/eksik: {field_name}"
                )

        # ----------------------------------------------------
        # DOSYA-İÇERİK KALİTE KAPILARI - yalnız gerçekten
        # ingest edilebilir belgeler için (validate_files_exist()
        # ile AYNI erken-çıkış deseni; dosya zaten yoksa/kaçıyorsa
        # o hata orada zaten raporlanmıştır, burada TEKRARLANMAZ).
        # ----------------------------------------------------

        active = document.get("active", True)

        ingest_config = document.get("ingest", {}) or {}

        ingest_enabled = ingest_config.get("enabled", True)

        if not active or not ingest_enabled:

            continue

        file_name = document.get("file_name")

        if not isinstance(file_name, str) or not file_name:

            continue

        candidate = os.path.join(MEVZUAT_DIR, file_name)

        try:

            verified_path = path_containment.resolve_existing(
                candidate,
                root=MEVZUAT_DIR,
            )

        except path_containment.PathContainmentError:

            continue

        try:

            size_bytes = verified_path.stat().st_size

        except OSError:

            continue

        if (
            isinstance(max_file_size, (int, float))
            and size_bytes > max_file_size
        ):

            errors.append(
                f"{document_id}: dosya boyutu policy "
                "max_file_size_bytes eşiğini aşıyor: "
                f"{size_bytes} > {max_file_size}"
            )

        try:

            with open(verified_path, "rb") as file:

                header = file.read(5)

        except OSError:

            header = b""

        if not header.startswith(b"%PDF"):

            errors.append(
                f"{document_id}: dosya %PDF magic-byte imzasıyla "
                f"başlamıyor (policy pdf_magic_byte gate): "
                f"{file_name}"
            )

            continue

        file_hash = _sha256_of_file(verified_path)

        seen_hashes.setdefault(file_hash, []).append(document_id)

    for file_hash, document_ids in seen_hashes.items():

        if len(document_ids) > 1:

            errors.append(
                "Birden fazla belge aynı ham-bayt içeriğe sahip "
                "(cross-document raw-hash dedup): "
                + ", ".join(sorted(document_ids))
            )

    return errors, warnings


# ============================================================
# TARİH MANTIĞI
# ============================================================

def validate_dates(
    documents
):

    errors = []

    warnings = []

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        try:

            decision_date = parse_date(
                document.get(
                    "karar_tarihi"
                )
            )

            rg_date = parse_date(
                document.get(
                    "resmi_gazete_tarihi"
                )
            )

            publication = parse_date(
                document.get(
                    "yayin_tarihi"
                )
            )

            effective = parse_date(
                document.get(
                    "yururluk_tarihi"
                )
            )

            start = parse_date(
                document.get(
                    "gecerlilik_baslangici"
                )
            )

            end = parse_date(
                document.get(
                    "gecerlilik_sonu"
                )
            )

            repeal = parse_date(
                document.get(
                    "mulga_tarihi"
                )
            )

        except ValueError as error:

            errors.append(
                f"{document_id}: geçersiz tarih: "
                f"{error}"
            )

            continue


        # ----------------------------------------------------
        # Geçerlilik başlangıç / bitiş
        # ----------------------------------------------------

        if (
            start is not None
            and end is not None
            and start > end
        ):

            errors.append(
                f"{document_id}: "
                "gecerlilik_baslangici, "
                "gecerlilik_sonu tarihinden "
                "sonra olamaz."
            )


        # ----------------------------------------------------
        # Mülga tarihi
        # ----------------------------------------------------

        if (
            repeal is not None
            and start is not None
            and repeal < start
        ):

            errors.append(
                f"{document_id}: "
                "mulga_tarihi, "
                "gecerlilik_baslangici tarihinden "
                "önce olamaz."
            )


        # ----------------------------------------------------
        # Yayın / yürürlük
        #
        # Bazı hukuki düzenlemelerde yürürlük tarihi
        # yayın tarihinden farklı olabilir.
        # Bu nedenle burada hard error üretmiyoruz.
        # ----------------------------------------------------

        if (
            publication is not None
            and effective is not None
            and effective < publication
        ):

            warnings.append(
                f"{document_id}: "
                "yururluk_tarihi, yayin_tarihi "
                "öncesinde görünüyor. "
                "Hukuki kaynaktan kontrol edilmeli."
            )


        # ----------------------------------------------------
        # RG tarihi / yayın tarihi farkı
        # ----------------------------------------------------

        if (
            rg_date is not None
            and publication is not None
            and rg_date != publication
        ):

            warnings.append(
                f"{document_id}: "
                "resmi_gazete_tarihi ile "
                "yayin_tarihi farklı."
            )


        # ----------------------------------------------------
        # Karar tarihi / RG tarihi
        #
        # Karar, Resmî Gazete'de yayımlanmasından sonra
        # alınmış görünemez.
        # ----------------------------------------------------

        if (
            decision_date is not None
            and rg_date is not None
            and decision_date > rg_date
        ):

            errors.append(
                f"{document_id}: "
                "karar_tarihi, resmi_gazete_tarihi "
                "sonrasında olamaz."
            )


        # ----------------------------------------------------
        # Karar tarihi / yayın tarihi
        # ----------------------------------------------------

        if (
            decision_date is not None
            and publication is not None
            and decision_date > publication
        ):

            errors.append(
                f"{document_id}: "
                "karar_tarihi, yayin_tarihi "
                "sonrasında olamaz."
            )

    return (
        errors,
        warnings
    )


# ============================================================
# STATUS / ACTIVE MANTIĞI
# ============================================================

def validate_status_logic(
    documents
):

    errors = []

    warnings = []

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        active = document.get(
            "active"
        )

        status = document.get(
            "status"
        )

        repeal = document.get(
            "mulga_tarihi"
        )

        end = document.get(
            "gecerlilik_sonu"
        )

        # ----------------------------------------------------
        # Repealed ama tarih yok
        # ----------------------------------------------------

        if (
            status == "repealed"
            and repeal is None
            and end is None
        ):

            warnings.append(
                f"{document_id}: "
                "status=repealed ancak "
                "mulga_tarihi ve gecerlilik_sonu boş."
            )


        # ----------------------------------------------------
        # Active status ama mülga tarihi var
        # ----------------------------------------------------

        if (
            status == "active"
            and repeal is not None
        ):

            warnings.append(
                f"{document_id}: "
                "status=active ancak "
                "mulga_tarihi girilmiş."
            )


        # ----------------------------------------------------
        # Historical ama teknik olarak indexte olabilir
        # Bu hata değildir.
        # ----------------------------------------------------

        if (
            status == "historical"
            and active is True
        ):

            pass

    return (
        errors,
        warnings
    )


# ============================================================
# INGEST MANTIĞI
# ============================================================

def validate_ingest_logic(
    documents
):

    errors = []

    warnings = []

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        active = document.get(
            "active"
        )

        ingest = document.get(
            "ingest",
            {}
        )

        enabled = ingest.get(
            "enabled"
        )

        parser = ingest.get(
            "parser"
        )

        ocr_required = ingest.get(
            "ocr_required"
        )

        # ----------------------------------------------------
        # Teknik active ama ingest kapalı
        # Bu mümkün, warning yeterli.
        # ----------------------------------------------------

        if (
            active is True
            and enabled is False
        ):

            warnings.append(
                f"{document_id}: "
                "active=true ancak "
                "ingest.enabled=false."
            )


        # ----------------------------------------------------
        # OCR gerekli ama plain_text parser
        # anlamsız kombinasyon
        # ----------------------------------------------------

        if (
            ocr_required is True
            and parser == "plain_text"
        ):

            warnings.append(
                f"{document_id}: "
                "ocr_required=true ancak "
                "parser=plain_text."
            )

    return (
        errors,
        warnings
    )


# ============================================================
# VERSION ZİNCİRİ
# ============================================================

def validate_version_links(
    documents
):

    errors = []

    warnings = []

    known_ids = {
        document.get(
            "document_id"
        )
        for document in documents
    }

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        previous_version = document.get(
            "previous_version"
        )

        next_version = document.get(
            "next_version"
        )

        supersedes = document.get(
            "supersedes"
        )

        superseded_by = document.get(
            "superseded_by"
        )

        links = {
            "previous_version":
                previous_version,

            "next_version":
                next_version,

            "supersedes":
                supersedes,

            "superseded_by":
                superseded_by
        }

        for field, target in links.items():

            if target is None:
                continue

            if target == document_id:

                errors.append(
                    f"{document_id}: "
                    f"{field} kendisini gösteremez."
                )

                continue

            if target not in known_ids:

                warnings.append(
                    f"{document_id}: "
                    f"{field} hedefi manifestte yok: "
                    f"{target}"
                )

    return (
        errors,
        warnings
    )


# ============================================================
# RELATION KONTROLÜ
# ============================================================

def validate_relations(
    documents
):

    errors = []

    warnings = []

    known_ids = {
        document.get(
            "document_id"
        )
        for document in documents
    }

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        seen_relations = set()

        for relation in document.get(
            "relations",
            []
        ):

            relation_type = relation.get(
                "type"
            )

            target = relation.get(
                "document_id"
            )

            article = relation.get(
                "article"
            )

            fikra = relation.get(
                "fikra"
            )

            bent = relation.get(
                "bent"
            )

            effective_date = relation.get(
                "effective_date"
            )

            # ------------------------------------------------
            # Kendi kendine relation
            # ------------------------------------------------

            if target == document_id:

                errors.append(
                    f"{document_id}: "
                    "relation kendisini hedefleyemez."
                )


            # ------------------------------------------------
            # Relation hedefi manifestte yok
            # ------------------------------------------------

            if target not in known_ids:

                warnings.append(
                    f"{document_id}: "
                    "relation hedefi manifestte yok: "
                    f"{target}"
                )


            # ------------------------------------------------
            # Duplicate relation
            # ------------------------------------------------

            relation_key = (
                relation_type,
                target,
                article,
                fikra,
                bent,
                effective_date
            )

            if relation_key in seen_relations:

                warnings.append(
                    f"{document_id}: "
                    "aynı relation birden fazla kez "
                    "tanımlanmış: "
                    f"{relation_type} -> {target}"
                )

            seen_relations.add(
                relation_key
            )

    return (
        errors,
        warnings
    )


# ============================================================
# SÜRE UZATMA RELATION MANTIĞI
# ============================================================

def validate_deadline_relations(
    documents
):

    errors = []

    warnings = []

    document_map = {
        document.get(
            "document_id"
        ):
            document
        for document in documents
    }

    reverse_types = {
        "extends_deadline":
            "deadline_extended_by",

        "deadline_extended_by":
            "extends_deadline"
    }

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        for relation in document.get(
            "relations",
            []
        ):

            relation_type = relation.get(
                "type"
            )

            if relation_type not in reverse_types:
                continue

            target_id = relation.get(
                "document_id"
            )

            article = relation.get(
                "article"
            )

            fikra = relation.get(
                "fikra"
            )

            bent = relation.get(
                "bent"
            )

            effective_date = relation.get(
                "effective_date"
            )


            # ------------------------------------------------
            # Süre uzatma ilişkisinde yürürlük/etki tarihi
            # retrieval ve evidence zinciri için önemlidir.
            # Eksikliği veri kalitesi uyarısıdır.
            # ------------------------------------------------

            if effective_date is None:

                warnings.append(
                    f"{document_id}: "
                    f"{relation_type} relation için "
                    "effective_date boş."
                )


            # ------------------------------------------------
            # Locator tamamen boşsa ilişki belge geneline
            # uygulanıyor olabilir. Hata değildir ama
            # scope kontrol edilmelidir.
            # ------------------------------------------------

            if (
                article is None
                and fikra is None
                and bent is None
            ):

                warnings.append(
                    f"{document_id}: "
                    f"{relation_type} relation için "
                    "article/fikra/bent boş; ilişki belge "
                    "geneli kapsamındaymış gibi modelleniyor."
                )


            # ------------------------------------------------
            # Reverse relation kontrolü
            #
            # Graph tek yönlü kalırsa evidence traversal
            # eksik olabilir. Hata değil, warning.
            # ------------------------------------------------

            target_document = document_map.get(
                target_id
            )

            if target_document is None:
                continue

            expected_reverse = reverse_types[
                relation_type
            ]

            reverse_found = False

            for reverse_relation in target_document.get(
                "relations",
                []
            ):

                if (
                    reverse_relation.get(
                        "type"
                    )
                    == expected_reverse
                    and reverse_relation.get(
                        "document_id"
                    )
                    == document_id
                    and reverse_relation.get(
                        "article"
                    )
                    == article
                    and reverse_relation.get(
                        "fikra"
                    )
                    == fikra
                    and reverse_relation.get(
                        "bent"
                    )
                    == bent
                    and reverse_relation.get(
                        "effective_date"
                    )
                    == effective_date
                ):

                    reverse_found = True
                    break

            if not reverse_found:

                warnings.append(
                    f"{document_id}: "
                    f"{relation_type} -> {target_id} için "
                    f"ters relation ({expected_reverse}) "
                    "bulunamadı."
                )

    return (
        errors,
        warnings
    )


# ============================================================
# BELGE TÜRÜ MANTIĞI
# ============================================================

def validate_document_type_logic(
    documents
):

    errors = []

    warnings = []

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        belge_turu = document.get(
            "belge_turu"
        )

        kanun_no = document.get(
            "kanun_no"
        )

        document_number = document.get(
            "document_number"
        )

        decision_date = document.get(
            "karar_tarihi"
        )


        # ----------------------------------------------------
        # Kanun ise kanun_no bekliyoruz
        # ----------------------------------------------------

        if (
            belge_turu == "Kanun"
            and not kanun_no
        ):

            errors.append(
                f"{document_id}: "
                "belge_turu=Kanun ancak "
                "kanun_no boş."
            )


        # ----------------------------------------------------
        # Kanun ise document_number yoksa warning
        # ----------------------------------------------------

        if (
            belge_turu == "Kanun"
            and not document_number
        ):

            warnings.append(
                f"{document_id}: "
                "Kanun için document_number boş."
            )


        # ----------------------------------------------------
        # Bakanlar Kurulu Kararı
        #
        # 2016/9385 gibi kararların kimliği document_number
        # üzerinden taşındığı için numara zorunludur.
        # ----------------------------------------------------

        if (
            belge_turu == "Bakanlar Kurulu Kararı"
            and not document_number
        ):

            errors.append(
                f"{document_id}: "
                "Bakanlar Kurulu Kararı için "
                "document_number zorunludur."
            )


        # ----------------------------------------------------
        # Bakanlar Kurulu Kararı için karar tarihi
        #
        # Eski kaynaklarda tarih bulunamayabilir; bu nedenle
        # hard error yerine warning üretiyoruz.
        # ----------------------------------------------------

        if (
            belge_turu == "Bakanlar Kurulu Kararı"
            and not decision_date
        ):

            warnings.append(
                f"{document_id}: "
                "Bakanlar Kurulu Kararı için "
                "karar_tarihi boş."
            )


        # ----------------------------------------------------
        # Cumhurbaşkanı Kararı
        #
        # Document number mevcutsa kararın resmi kimliği daha
        # güvenilir biçimde izlenebilir. Eski manifest davranışını
        # kırmamak için boşluk warning olarak kalır.
        # ----------------------------------------------------

        if (
            belge_turu == "Cumhurbaşkanı Kararı"
            and not document_number
        ):

            warnings.append(
                f"{document_id}: "
                "Cumhurbaşkanı Kararı için "
                "document_number boş."
            )

        if (
            belge_turu == "Cumhurbaşkanı Kararı"
            and not decision_date
        ):

            warnings.append(
                f"{document_id}: "
                "Cumhurbaşkanı Kararı için "
                "karar_tarihi boş."
            )

    return (
        errors,
        warnings
    )


# ============================================================
# OFFICIAL SOURCE MANTIĞI
# ============================================================

def validate_source_logic(
    documents
):

    warnings = []

    for document in documents:

        document_id = document.get(
            "document_id"
        )

        official_source = document.get(
            "official_source"
        )

        source_url = document.get(
            "source_url"
        )

        kaynak_kurum = document.get(
            "kaynak_kurum"
        )

        if (
            official_source is True
            and not kaynak_kurum
        ):

            warnings.append(
                f"{document_id}: "
                "official_source=true ancak "
                "kaynak_kurum boş."
            )

        if (
            official_source is True
            and source_url is None
        ):

            warnings.append(
                f"{document_id}: "
                "official_source=true ancak "
                "source_url boş."
            )

    return warnings


# ============================================================
# ANA VALIDATOR
# ============================================================

def validate_manifest_file(
    raise_on_error=True
):

    if not os.path.exists(
        MANIFEST_PATH
    ):

        raise FileNotFoundError(
            f"documents.json bulunamadı:\n"
            f"{MANIFEST_PATH}"
        )

    if not os.path.exists(
        SCHEMA_PATH
    ):

        raise FileNotFoundError(
            f"documents.schema.json bulunamadı:\n"
            f"{SCHEMA_PATH}"
        )

    manifest = load_json(
        MANIFEST_PATH
    )

    schema = load_json(
        SCHEMA_PATH
    )

    errors = []

    warnings = []

    # ========================================================
    # 1. JSON SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            manifest,
            schema
        )
    )

    # Schema başarısızsa custom validation güvenilir değil.
    if errors:

        if raise_on_error:

            message = (
                "\nMANIFEST VALIDATION HATASI\n"
                + "\n".join(
                    f"- {error}"
                    for error in errors
                )
            )

            raise ValueError(
                message
            )

        return {
            "valid":
                False,

            "errors":
                errors,

            "warnings":
                warnings
        }

    documents = manifest[
        "documents"
    ]

    # ========================================================
    # 2. DUPLICATE ID
    # ========================================================

    errors.extend(
        validate_unique_document_ids(
            documents
        )
    )

    # ========================================================
    # 3. DUPLICATE FILE
    # ========================================================

    errors.extend(
        validate_unique_active_files(
            documents
        )
    )

    # ========================================================
    # 4. FILE EXISTENCE
    # ========================================================

    errors.extend(
        validate_files_exist(
            documents
        )
    )

    # ========================================================
    # 5. DATES
    # ========================================================

    date_errors, date_warnings = (
        validate_dates(
            documents
        )
    )

    errors.extend(
        date_errors
    )

    warnings.extend(
        date_warnings
    )

    # ========================================================
    # 6. STATUS
    # ========================================================

    status_errors, status_warnings = (
        validate_status_logic(
            documents
        )
    )

    errors.extend(
        status_errors
    )

    warnings.extend(
        status_warnings
    )

    # ========================================================
    # 7. INGEST
    # ========================================================

    ingest_errors, ingest_warnings = (
        validate_ingest_logic(
            documents
        )
    )

    errors.extend(
        ingest_errors
    )

    warnings.extend(
        ingest_warnings
    )

    # ========================================================
    # 8. VERSION LINKS
    # ========================================================

    version_errors, version_warnings = (
        validate_version_links(
            documents
        )
    )

    errors.extend(
        version_errors
    )

    warnings.extend(
        version_warnings
    )

    # ========================================================
    # 9. RELATIONS
    # ========================================================

    relation_errors, relation_warnings = (
        validate_relations(
            documents
        )
    )

    errors.extend(
        relation_errors
    )

    warnings.extend(
        relation_warnings
    )

    # ========================================================
    # 10. DEADLINE RELATION LOGIC
    # ========================================================

    deadline_errors, deadline_warnings = (
        validate_deadline_relations(
            documents
        )
    )

    errors.extend(
        deadline_errors
    )

    warnings.extend(
        deadline_warnings
    )

    # ========================================================
    # 11. DOCUMENT TYPE LOGIC
    # ========================================================

    type_errors, type_warnings = (
        validate_document_type_logic(
            documents
        )
    )

    errors.extend(
        type_errors
    )

    warnings.extend(
        type_warnings
    )

    # ========================================================
    # 12. SOURCE LOGIC
    # ========================================================

    warnings.extend(
        validate_source_logic(
            documents
        )
    )

    # ========================================================
    # 13. CORPUS POLICY ADMISSIBILITY + STAGE-1 QUALITY
    # ========================================================

    policy_errors, policy_warnings = (
        validate_corpus_policy_admissibility(
            documents
        )
    )

    errors.extend(
        policy_errors
    )

    warnings.extend(
        policy_warnings
    )

    valid = (
        len(
            errors
        )
        == 0
    )

    if (
        not valid
        and raise_on_error
    ):

        message = (
            "\nMANIFEST VALIDATION HATASI\n"
            + "\n".join(
                f"- {error}"
                for error in errors
            )
        )

        raise ValueError(
            message
        )

    return {

        "valid":
            valid,

        "errors":
            errors,

        "warnings":
            warnings,

        "document_count":
            len(
                documents
            )
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - MANIFEST VALIDATOR V2.1"
    )

    print(
        "======================================"
    )

    try:

        result = validate_manifest_file(
            raise_on_error=True
        )

        print(
            "\nMANIFEST GEÇERLİ"
        )

        print(
            "Belge sayısı:",
            result[
                "document_count"
            ]
        )

        if result[
            "warnings"
        ]:

            print(
                "\nUYARILAR:"
            )

            for warning in result[
                "warnings"
            ]:

                print(
                    "-",
                    warning
                )

        else:

            print(
                "Uyarı yok."
            )

    except Exception as error:

        print(
            "\nMANIFEST GEÇERSİZ"
        )

        print(
            error
        )