# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - TEK YÖNLENDİRMELİ AKIŞ (SİHİRBAZ)
#
#   python -m ui.office_deadline_flow --office-root <yol> --actor-user-id <N> \
#       --case-id <kimlik> --dosya-kodu <kod> [--kaynak-pdf <yol>] [--devam <koşu>]
#
# F0 hazırlık denetimi -> F1 dosya hazırlama -> F2 BAĞIMSIZ OKUMA (aday
# satır/sonuç görülmeden ÖNCE O_EXCL kayıt) -> F3 aday satır + sistem zinciri
# -> F4 karşılaştırma (sonuç YALNIZ burada gösterilir) -> F5 rapor kontrolü
# / inceleme -> F6 silme (sahiplik doğrulamalı, avukatın ayrı onayıyla).
#
# Mevcut facade'ler SÜREÇ İÇİNDEN çağrılır (`cli_mutate._run_*` KULLANILMAZ);
# `apply_generation`'ın stdout'u ASLA basılmaz. Hiçbir ağ/LLM/alt süreç yok
# (varsayılan Poppler çıkarıcısı YALNIZ office_flow_intake'te). Otomatik
# silme/zamanlayıcı yoktur. T2 (onay kapısı) YAPILMADI: akışı atlayan
# doğrudan `cli_mutate approval` / `ui.deadline_report` yolu bu akışın
# güvencesi DEĞİLDİR (bilinen, T2'ye bağlı açık bağımlılık).
# ============================================================

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import warnings
from pathlib import Path

from ui.services import office_flow_cleanup as cleanup
from ui.services import office_flow_intake as intake
from ui.services import office_flow_outcomes as outcomes
from ui.services import office_flow_preflight as preflight
from ui.services import office_flow_records as records
from ui.services import office_flow_report as report
from ui.services.office_flow_records import OfficeFlowError

EXIT_OK = 0
EXIT_DOMAIN_ERROR = 1
EXIT_USAGE_ERROR = 2

DEVICE_STEPS_LIST = (
    "CİHAZ ADIMLARI (yazılım yapamaz, elle yapılır): "
    "(1) şifreli çalışma alanını kapatıp silme/anahtar-parola imhası, "
    "(2) vaka atamasının iptali (ADMIN rolü), "
    "(3) sistem TEMP'i ve yedek/bulut/arama dizinlerinin kalıntı kontrolü."
)

DELETION_HONEST_LIMIT = (
    "TAMAMLANDI, dosya sisteminden kaldırıldığı ve doğrulandığı anlamına gelir; fiziksel/SSD silme garantisi DEĞİLDİR "
    "ve veritabanı işlem kayıtları silinmez. Gizlilik, korunan alanın anahtarının imhasına dayanır (cihaz adımı)."
)

STAGE_DATE_FREE_NOTICE = "Sistem sonucu bağımsız okuma kaydedilmeden gösterilmez."


# ----------------------------------------------------------------
# Giriş/çıkış (enjekte edilebilir)
# ----------------------------------------------------------------


class ConsoleIO:
    def __init__(self, stdin=None, stdout=None):
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout

    def ask(self, key: str, prompt: str) -> str:
        self._stdout.write(prompt + " ")
        self._stdout.flush()
        line = self._stdin.readline()
        if line == "":
            raise EOFError()
        return line.rstrip("\r\n")

    def say(self, text: str) -> None:
        self._stdout.write(text if text.endswith("\n") else text + "\n")
        self._stdout.flush()


# ----------------------------------------------------------------
# Gerçek zincir arka ucu (mevcut facade'ler, süreç içinden)
# ----------------------------------------------------------------

_RECESS = {"yes": True, "no": False, "unknown": None}

# Türkçe/İngilizce giriş etiketleri AYNI iç değerlere eşlenir (kayıt şeması aynı).
_LABELS_RECESS = {
    "evet": "yes", "hayır": "no", "hayir": "no", "bilinmiyor": "unknown",
    "yes": "yes", "no": "no", "unknown": "unknown",
}
_LABELS_STOPPING = {
    "yok": "none", "var": "present", "bilinmiyor": "unknown",
    "none": "none", "present": "present", "unknown": "unknown",
}


class RealChainBackend:
    """Mevcut facade'leri süreç içinden çağırır. `authz` bağlantısı
    mutation/journal bağlantısından AYRIDIR (CLI ile aynı disiplin)."""

    DOC = intake.DOC_ID

    def __init__(self, *, actor_user_id: int, authz_conn_factory=None,
                 mutation_conn_factory=None, report_conn_factory=None):
        self.actor_user_id = actor_user_id
        self._authz_conn_factory = authz_conn_factory
        self._mutation_conn_factory = mutation_conn_factory
        self._report_conn_factory = report_conn_factory
        self._conn = None
        self._principal = None
        self._repository = None

    # -- bağlantı/principal ------------------------------------------------

    def _open(self):
        if self._conn is not None:
            return
        from ui.services import cli_authz as _cli_authz

        if self._authz_conn_factory is None:
            from ui.services import db as _db
            factory = _db.get_connection
        else:
            factory = self._authz_conn_factory
        self._conn = factory()
        try:
            self._principal = _cli_authz.build_cli_principal(self._conn, self.actor_user_id)
        except (_cli_authz.CliActorNotFoundError, _cli_authz.CliActorDisabledError):
            self.close()
            raise OfficeFlowError("YETKI_YOK") from None
        self._repository = _cli_authz.CliActorAuthzRepository(self._conn)

    def release(self) -> None:
        """Uzun insan beklemelerinde açık işlem bırakma."""
        if self._conn is not None:
            try:
                self._conn.rollback()
            except Exception:
                pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn, self._principal, self._repository = None, None, None

    # -- kimlik ------------------------------------------------------------

    def identity(self, case_id: str):
        self._open()
        try:
            return records.capture_identity(
                self._conn, self.actor_user_id, case_id, repository=self._repository,
            )
        finally:
            self.release()

    # -- global girdiler -----------------------------------------------------

    def global_input_paths(self) -> dict:
        from ui.services import paths as _paths  # noqa: F401 - src/ sys.path
        import deadline_calculator
        import deadline_engine

        return {
            "ruleset": Path(deadline_engine.DEFAULT_RULESET_PATH),
            "provisions": Path(deadline_calculator.DEFAULT_PROVISIONS_PATH),
            "holiday_calendar": Path(deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH),
        }

    def holiday_calendar_ok(self) -> bool:
        import json
        from ui.services import paths as _paths  # noqa: F401
        import holiday_calendar_validator

        try:
            document = json.loads(self.global_input_paths()["holiday_calendar"].read_bytes().decode("utf-8"))
            holiday_calendar_validator.validate_holiday_calendar(document, raise_on_error=True)
        except Exception:
            return False
        return True

    # -- zincir -------------------------------------------------------------

    def _case_dir(self, case_id: str) -> Path:
        from ui.services import paths as _paths

        return Path(_paths.CASES_DIR) / case_id

    def manual_fact(self, case_id: str) -> None:
        from ui.services import manual_fact_mutation_facade as mf

        self._open()
        preview = mf.preview_manual_fact(
            case_id, self.DOC, principal=self._principal, authz_repository=self._repository,
        )
        mf.apply_manual_fact(
            case_id, self.DOC, preview["input_digest"], attempt=1,
            principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def promote_fact(self, case_id: str) -> None:
        from ui.services import promotion_mutation_facade as pm

        self._open()
        preview = pm.preview_promotion(
            "fact", case_id, document_id=self.DOC,
            principal=self._principal, authz_repository=self._repository,
        )
        pm.approve_promotion_mutation(
            "fact", case_id, preview["pending_hash"], document_id=self.DOC,
            note=None, discard_verified_states=False,
            principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def verify_fact(self, case_id: str) -> None:
        import json
        from ui.services import fact_verification_mutation_facade as fv

        facts_path = self._case_dir(case_id) / "documents" / self.DOC / "extractions" / "facts.json"
        facts = json.loads(facts_path.read_bytes().decode("utf-8"))
        fact_id = facts["facts"][0]["fact_id"]
        self._open()
        preview = fv.preview_verification(
            case_id, self.DOC, fact_id,
            principal=self._principal, authz_repository=self._repository,
        )
        fv.apply_verification_mutation(
            case_id, self.DOC, fact_id, preview["canonical_sha256"], "verified",
            evidence_document_id=self.DOC, attempt=1,
            principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def generate_timeline(self, case_id: str) -> None:
        from ui.services import generation_mutation_facade as gen

        self._open()
        preview = gen.preview_generation(
            "timeline", case_id, principal=self._principal, authz_repository=self._repository,
        )
        gen.apply_generation(
            "timeline", case_id, preview["input_digest"],
            principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def promote_timeline(self, case_id: str) -> None:
        from ui.services import promotion_mutation_facade as pm

        self._open()
        preview = pm.preview_promotion(
            "timeline", case_id, principal=self._principal, authz_repository=self._repository,
        )
        pm.approve_promotion_mutation(
            "timeline", case_id, preview["pending_hash"],
            principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def anchor_candidates(self, case_id: str) -> list:
        import json

        timeline = json.loads(
            (self._case_dir(case_id) / "timeline" / "timeline.json").read_bytes().decode("utf-8"),
        )
        return [e["event_id"] for e in timeline.get("events", []) if e.get("event_type") == "notification_date"]

    def generate_deadline(self, case_id: str, anchor_event_id: str, adli_tatil: str,
                          stopping_status: str, stopping_ref) -> None:
        from ui.services import generation_mutation_facade as gen

        self._open()
        preview = gen.preview_generation(
            "deadline", case_id, anchor_event_id=anchor_event_id,
            principal=self._principal, authz_repository=self._repository,
        )
        # `result.stdout` ASLA basılmaz (sonuç yalnız F4'te gösterilir).
        gen.apply_generation(
            "deadline", case_id, preview["input_digest"], anchor_event_id=anchor_event_id,
            judicial_recess_applicable=_RECESS[adli_tatil],
            stopping_event_status=stopping_status, stopping_event_attestation_ref=stopping_ref,
            attempt=1, principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def pending_deadline_path(self, case_id: str) -> Path:
        from ui.services import paths as _paths  # noqa: F401
        import deadline_engine

        return Path(deadline_engine.get_pending_path(case_id))

    def approve_deadline(self, case_id: str, expected_pending_sha=None) -> None:
        from ui.services import approval_registry as ar
        from ui.services import authz as _authz

        self._open()
        _authz.authorize_case_access(self._principal, case_id, "read", repository=self._repository)
        review = ar.case_scoped_review("deadline", case_id)
        if expected_pending_sha is not None and review["pending_hash"] != expected_pending_sha:
            self.release()
            raise OfficeFlowError("GIRDI_DEGISTI")
        ar.case_scoped_approve(
            "deadline", case_id, review["pending_hash"],
            principal=self._principal, authz_repository=self._repository,
            conn_factory=self._mutation_conn_factory,
        )
        self.release()

    def canonical_report(self, case_id: str):
        """(metin | None, ret kodu | None). Ret kodu deadline_report'un kapalı kümesidir."""
        import ui.deadline_report as deadline_report

        try:
            text = deadline_report.build_report(
                case_id, self.actor_user_id, conn_factory=self._report_conn_factory,
            )
        except deadline_report.ReportRefused as refused:
            return None, refused.code
        return text, None


# ----------------------------------------------------------------
# Akış
# ----------------------------------------------------------------

_FULL_CHAIN_STATES = ("HAZIRLANIYOR", "OKUMA_KAYITLI", "SISTEM_ZINCIRI")


class OfficeFlow:
    def __init__(self, *, office_root, case_root, backend, io, extractor=None, repo_root=None,
                 allow_system_drive=False, clock=None, fs=None, preflight_options=None):
        self.office_root = Path(office_root)
        self.case_root = Path(case_root)
        self.backend = backend
        self.io = io
        self.extractor = extractor or intake.default_pdftotext_extractor
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
        self.allow_system_drive = allow_system_drive
        self.clock = clock
        self.fs = fs
        self.preflight_options = dict(preflight_options or {})
        self.step = "F0"
        self.run_id = None
        self._temp_restore = None
        self._temp_paths = None
        self._tmp_baseline = None

    # -- yardımcılar ---------------------------------------------------------

    def _say(self, text: str) -> None:
        self.io.say(text)

    def _paths(self, run_id: str, case_id: str):
        return records.build_run_paths(self.office_root, self.case_root, case_id, run_id)

    def _save(self, paths, state) -> None:
        records.save_run_state(paths, state)

    def _manifest(self, paths):
        if paths.manifest_path.exists():
            return records.RunManifest.load(paths.manifest_path)
        return records.RunManifest()

    def _protected_roots(self, paths) -> list:
        return [self.case_root, self.office_root, paths.case_dir, paths.run_dir]

    def _ask(self, key: str, prompt: str) -> str:
        return self.io.ask(key, prompt)

    def _confirm_identity(self, identity, key: str, prompt: str) -> None:
        typed = self._ask(key, prompt)
        if not records.confirm_full_name(typed, identity.display_name):
            raise OfficeFlowError("KIMLIK_TEYIDI_BASARISIZ" if key == "kimlik_ad" else "ONAY_TEYIDI_BASARISIZ")

    def _announce(self, run_id) -> None:
        """Koşu kimliği (rastgele, opak; dosyadan türetilmez). `--devam` için
        kullanıcıya her ara/durma çıktısında gösterilir. Destek özetine GİRMEZ."""
        self.run_id = run_id
        self._say(f"Çalışma kimliği: {run_id}  (devam etmek için: --devam {run_id})")

    def _redirect_temp(self, paths) -> None:
        try:
            paths.tmp_dir.mkdir(exist_ok=True)
        except OSError:
            raise OfficeFlowError("YAZMA_BASARISIZ") from None
        mf = self._manifest(paths)
        mf.add_dir(root="run", rel=records.TMP_DIR_NAME)
        records.save_manifest(paths, mf)
        # Bu süreçte oluşan geçici dosyalar yalnız FARKLA bildirime girer: iki
        # oturum arasında tmp/ içine konan yabancı dosya kaydedilmez.
        self._tmp_baseline = cleanup.snapshot_tree(paths.tmp_dir, prefix=records.TMP_DIR_NAME + "/")
        self._temp_paths = paths
        self._temp_restore = preflight.redirect_temp(paths.tmp_dir)

    def restore_temp(self) -> None:
        if self._temp_restore is not None:
            preflight.restore_temp(self._temp_restore)
            self._temp_restore = None
            paths, baseline = self._temp_paths, self._tmp_baseline
            self._temp_paths = self._tmp_baseline = None
            if paths is not None and baseline is not None:
                try:
                    after = cleanup.snapshot_tree(paths.tmp_dir, prefix=records.TMP_DIR_NAME + "/")
                    mf = self._manifest(paths)
                    cleanup.register_new_entries(mf, "run", baseline, after)
                    records.save_manifest(paths, mf)
                except OfficeFlowError:
                    pass  # kaydedilemeyen geçici dosya silmede bilinmeyen sayılır (fail-closed)

    # -- bildirime işleme (H-1): koşunun KENDİ oluşturduğu girdiler ------------

    def _register_case_diff(self, paths, before) -> None:
        after = cleanup.snapshot_tree(paths.case_dir)
        mf = self._manifest(paths)
        cleanup.register_new_entries(mf, "case", before, after)
        records.save_manifest(paths, mf)

    def _tracked(self, paths, fn, /, *args, **kwargs):
        """`fn`'in vaka dizininde yarattığı HER yeni dosya/dizin bildirime
        işlenir (hata yolunda da). Bildirimde olmayan girdi silmede bilinmeyendir."""
        before = cleanup.snapshot_tree(paths.case_dir)
        try:
            result = fn(*args, **kwargs)
        except BaseException:
            try:
                self._register_case_diff(paths, before)
            except OfficeFlowError:
                pass
            raise
        self._register_case_diff(paths, before)
        return result

    def _merge_manifest(self, paths, scratch) -> None:
        mf = self._manifest(paths)
        for item in scratch.entries:
            mf.add(root=item["root"], rel=item["rel"], tur=item["tur"])
        for item in scratch.dirs:
            mf.add_dir(root=item["root"], rel=item["rel"])
        records.save_manifest(paths, mf)

    def _reading(self, paths, state) -> dict:
        """F2 okuma kaydı; koşu durumundaki sha256 ile BİREBİR eşleşmeli."""
        expected = state.get("okuma_sha")
        if not expected:
            raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ")
        return records.load_reading_record(paths, expected_sha=expected)

    def _current_inputs(self, paths) -> dict:
        return records.compute_input_manifest(paths.case_dir, self.backend.global_input_paths())

    def _fresh(self, paths, state) -> bool:
        """Girdi manifesti ve (varsa) hesap parmak izi karşılaştırmadaki gibi mi."""
        recorded = state.get("girdi_manifesti")
        if recorded is None:
            return True
        if records.changed_inputs(recorded, self._current_inputs(paths)):
            return False
        fingerprint = state.get("deadline_izi")
        if fingerprint is not None and records.deadline_fingerprint(paths.case_dir) != fingerprint:
            return False
        return True

    def _invalidate(self, paths, state) -> None:
        """GEÇERSİZ: rapor ve onay kullanılamaz; başarı sonucu ÜRETİLMEZ."""
        state["rapor_gecersiz"] = True
        if paths.report_path.exists():
            report.stamp_report_invalid(paths)
        if state.state in ("UYUSMAZLIK_INCELEME_ACIK",):
            # UYUŞMAZLIK asla UYUMLU'ya terfi etmez; yalnız rapor damgalanır.
            self._save(paths, state)
            return
        if records.transition_allowed(state.state, "GECERSIZ"):
            state.set_state("GECERSIZ")
        self._save(paths, state)
        self._say("GEÇERSİZ: karşılaştırmadan sonra doğrulanmış girdi değişti. "
                  "Eski sonuç nihai onay veya geçerli rapor için kullanılamaz. "
                  "Yeni karşılaştırma yeni bir çalışmayla yapılır. (GIRDI_DEGISTI)")
        self._announce(paths.run_id)

    # ------------------------------------------------------------------
    # F0 - F2
    # ------------------------------------------------------------------

    def run_new(self, *, case_id: str, dosya_kodu: str, source_pdf=None) -> str:
        """F0 -> F4 (UYUMLU/UYUSMAZLIK); dönüş: koşu kimliği."""
        self.step = "F0"
        records.validate_case_id(case_id)
        records.validate_dosya_kodu(dosya_kodu)
        options = self.preflight_options
        result = preflight.run_preflight(
            office_root=self.office_root, case_root=self.case_root, repo_root=self.repo_root,
            dsn=options.get("dsn"), env=options.get("env"), import_probe=options.get("import_probe"),
            volume_probe=options.get("volume_probe"), allow_system_drive=self.allow_system_drive,
            system_drive=options.get("system_drive"), drive_of=options.get("drive_of"),
        )
        for warning in result.warnings:
            self._say("UYARI: " + warning)
        preflight.raise_if_failed(result)
        if not self.backend.holiday_calendar_ok():
            raise OfficeFlowError("TATIL_TAKVIMI_GECERSIZ")
        records.ensure_office_infra(self.office_root)
        identity = self.backend.identity(case_id)
        # Kayıtlı ad EKRANA YAZILMAZ: ad yalnız ek teyittir; kullanıcı kendi adını
        # yazar, karşılaştırma içeride yapılır.
        self._confirm_identity(
            identity, "kimlik_ad", "Kimlik teyidi için tam adınızı yazın (kayıtlı adla aynen eşleşmeli):",
        )

        run_id = records.new_run_id()
        paths = self._paths(run_id, case_id)
        records.create_owned_dir(paths.run_dir, run_id=run_id, kind="run_dir")
        self._announce(run_id)
        state = records.RunState.new(run_id=run_id, case_id=case_id, dosya_kodu=dosya_kodu)
        records.create_run_state_file(paths, state)
        manifest = records.RunManifest()
        manifest.add(root="run", rel=records.RUN_STATE_NAME, tur="CALISMA_DOSYALARI")
        records.save_manifest(paths, manifest)
        self._redirect_temp(paths)
        try:
            self._f1(paths, state, manifest, source_pdf)
            self._f2(paths, state, identity)
            self._f3_f4(paths, state, manifest, identity)
        except Exception:
            self._halt_if_prechain(paths, state)
            raise
        finally:
            self.restore_temp()
        return run_id

    def _halt_if_prechain(self, paths, state) -> None:
        """Zincir tamamlanmadan hata: DURDURULDU (silme yolu açılır)."""
        if state.state in _FULL_CHAIN_STATES and records.transition_allowed(state.state, "DURDURULDU"):
            state.set_state("DURDURULDU")
            try:
                self._save(paths, state)
            except OfficeFlowError:
                pass
            self._announce(paths.run_id)

    def _f1(self, paths, state, manifest, source_pdf) -> None:
        self.step = "F1"
        source = source_pdf if source_pdf is not None else self._ask(
            "kaynak_pdf", "Asıl ihbarname PDF'inin yolu (salt-okunur kullanılır, değiştirilmez):",
        )
        page_count_text = self._ask("sayfa_sayisi", "Belgenin sayfa sayısı:")
        try:
            page_count = int(str(page_count_text).strip())
        except ValueError:
            raise OfficeFlowError("SAYFA_GECERSIZ") from None
        tax_text = self._ask(
            "vergi_turleri", "Uyuşmazlık kalemlerinin vergi türü (virgülle; G8 listesi):",
        )
        tax_types = [item.strip() for item in str(tax_text).split(",") if item.strip()]
        scratch = records.RunManifest()
        try:
            self._tracked(
                paths, intake.seed_case,
                paths=paths, source_pdf=source, page_count=page_count, tax_types=tax_types,
                extractor=self.extractor, manifest=scratch,
                protected_roots=self._protected_roots(paths),
            )
        finally:
            self._merge_manifest(paths, scratch)

    def _f2(self, paths, state, identity) -> None:
        self.step = "F2"
        self._say("F2 - BAĞIMSIZ OKUMA: asıl belgeden okuyun; çıkarılmış metin ve sistem sonucu "
                  "henüz GÖSTERİLMEZ.")
        tarih = self._ask("tebligat_tarihi", "Tebliğ tarihi (asıl belgeden; GG.AA.YYYY):")
        sayfa_text = self._ask("tebligat_sayfa", "Tebliğ tarihinin geçtiği sayfa:")
        kor = self._ask("kor_son_gun", "Kendi hesapladığınız dava açma süresi son günü (GG.AA.YYYY):")
        adli = _LABELS_RECESS.get(
            self._ask("adli_tatil", "Adli tatil bu süreye uygulanır mı? (evet/hayır/bilinmiyor):").strip().lower(),
            "invalid",
        )
        stopping = _LABELS_STOPPING.get(
            self._ask(
                "stopping_durum", "Tebliğden sonra süreyi durdurabilecek/kesebilecek işlem var mı? "
                "(yok/var/bilinmiyor):",
            ).strip().lower(),
            "invalid",
        )
        stopping_ref = None
        if stopping == "none":
            stopping_ref = self._ask("stopping_ref", "Beyanınızın opak referansı (tarih/uzun sayı yazmayın):")
        try:
            sayfa = int(str(sayfa_text).strip())
        except ValueError:
            raise OfficeFlowError("OKUMA_KAYDI_GECERSIZ") from None
        record = records.build_reading_record(
            tebligat_tarihi=tarih, sayfa=sayfa, kor_son_gun=kor, adli_tatil=adli,
            stopping_status=stopping, stopping_ref=stopping_ref, identity=identity,
        )
        state["okuma_sha"] = records.write_reading_record(paths, record)
        state.set_state("OKUMA_KAYITLI")
        self._save(paths, state)
        mf = self._manifest(paths)
        mf.add(root="run", rel=records.READING_RECORD_NAME, tur="CALISMA_DOSYALARI")
        records.save_manifest(paths, mf)

    # ------------------------------------------------------------------
    # F3 - F4
    # ------------------------------------------------------------------

    def _f3_f4(self, paths, state, manifest, identity) -> None:
        self.step = "F3"
        reading = self._reading(paths, state)
        text = intake.read_extracted_text(paths)
        candidates = intake.candidate_lines(text)
        if not candidates:
            raise OfficeFlowError("ADAY_YOK")
        self._say("F3 - AYNI TARİHİ İÇEREN ADAY SATIRLAR (yalnız tam bir tarih içeren satırlar):")
        for candidate in candidates:
            self._say(f"{candidate.index}) {candidate.text}")
        choice_text = self._ask("aday_secimi", "Tebliğ tarihini içeren satırın numarası:")
        try:
            chosen = next(c for c in candidates if c.index == int(str(choice_text).strip()))
        except (StopIteration, ValueError):
            raise OfficeFlowError("ADAY_SECIMI_GECERSIZ") from None

        if chosen.date_iso != reading["tebligat_tarihi"]:
            # F3 tarih uyuşmazlığı: hesap/promotion YOK.
            self._say("Seçilen satırdaki tarih, F2'deki bağımsız tarihinizle UYUŞMUYOR. Hesap yapılmadı. (TARIH_UYUSMAZLIGI)")
            state["f3_aday_tarihi"] = chosen.date_iso
            state["kontrol_turu"] = records.determine_kontrol_turu(paths.history_dir, state["dosya_kodu"])
            state.set_state("UYUSMAZLIK_INCELEME_ACIK")
            self._save(paths, state)
            report.write_report(paths, report.build_report_text(
                reading=reading, system=None, comparison=report.Comparison("UYUSMAZLIK", False, None, "TARIH_FARKLI"),
                state=state.state, f3_date_mismatch=chosen.date_iso, kontrol_turu=state["kontrol_turu"],
            ))
            self._manifest_add_report(paths)
            return

        state.set_state("SISTEM_ZINCIRI")
        self._save(paths, state)
        manual_input = intake.build_manual_input(paths.case_id, chosen, reading["sayfa"])
        scratch = records.RunManifest()
        try:
            self._tracked(paths, intake.write_manual_input, paths, manual_input, scratch)
        finally:
            self._merge_manifest(paths, scratch)

        backend, case_id = self.backend, paths.case_id
        track = self._tracked
        try:
            track(paths, backend.manual_fact, case_id)
            track(paths, backend.promote_fact, case_id)
            self.step = "F3"
            if not self._ask("dogrulama_karari", "Tebliğ tarihini asıl belgeyle karşılaştırdınız ve doğruluyor musunuz? (evet/hayır):").strip().lower() == "evet":
                raise OfficeFlowError("DOGRULAMA_REDDEDILDI")
            track(paths, backend.verify_fact, case_id)
            track(paths, backend.generate_timeline, case_id)
            track(paths, backend.promote_timeline, case_id)
            anchors = backend.anchor_candidates(case_id)
            if len(anchors) != 1:
                raise OfficeFlowError("ANCHOR_BELIRSIZ")
            track(
                paths, backend.generate_deadline,
                case_id, anchors[0], reading["adli_tatil"], reading["stopping_event_status"],
                reading["stopping_event_ref"],
            )
        except OfficeFlowError:
            raise
        except Exception as error:
            raise OfficeFlowError(outcomes.error_code_for(error)) from None

        try:
            system = report.read_pending_summary(backend.pending_deadline_path(case_id))
        except OfficeFlowError:
            system = None
        state["sistem_ozeti"] = None if system is None else {
            "anchor_date": system.anchor_date, "calculation_state": system.calculation_state,
            "calculated_deadline": system.calculated_deadline, "rule_id": system.rule_id,
            "requires_human_review": system.requires_human_review,
        }
        state["girdi_manifesti"] = self._current_inputs(paths)
        state["deadline_izi"] = records.deadline_fingerprint(paths.case_dir)
        state.set_state("KARSILASTIRMA_YAPILDI")
        self._save(paths, state)
        self._f4(paths, state, identity)

    def _manifest_add_report(self, paths) -> None:
        mf = self._manifest(paths)
        mf.add(root="run", rel=records.REPORT_NAME, tur="PILOT_HESAP_RAPORU")
        records.save_manifest(paths, mf)

    def _system_from_state(self, state):
        data = state.get("sistem_ozeti")
        if data is None:
            return None
        return report.SystemSummary(
            anchor_date=data["anchor_date"], calculation_state=data["calculation_state"],
            calculated_deadline=data["calculated_deadline"], rule_id=data["rule_id"],
            requires_human_review=data["requires_human_review"],
        )

    def _f4(self, paths, state, identity) -> None:
        """Sistem sonucu YALNIZ burada gösterilir (F2 kaydı ZATEN yazılmıştır)."""
        self.step = "F4"
        reading = self._reading(paths, state)
        system = self._system_from_state(state)
        if state.get("kontrol_turu") is None:
            # Önce türü belirle, SONRA işareti yaz (kendi eşleşmesi kendini
            # YENIDEN yapmasın); işaret sonuç gösterilmeden ÖNCE yazılır.
            state["kontrol_turu"] = records.determine_kontrol_turu(paths.history_dir, state["dosya_kodu"])
            self._save(paths, state)
        records.mark_result_seen(paths.history_dir, state["dosya_kodu"])
        if system is None:
            comparison = report.Comparison("UYUSMAZLIK", None, None, "SISTEM_HESAPLAMADI")
            self._say("Sistem bir sonuç üretemedi (SISTEM_HESAPLAMADI).")
        else:
            self._say("SİSTEMİN SONUCU")
            self._say(f"  Anchor (tebliğ) tarihi: {report.iso_to_tr(system.anchor_date) if system.anchor_date else '-'}")
            self._say(f"  Hesap durumu: {system.calculation_state}")
            self._say(f"  Hesaplanan son gün: {report.iso_to_tr(system.calculated_deadline) if system.calculated_deadline else '-'}")
            self._say(f"  Kural: {system.rule_id or '-'}")
            comparison = report.compare(reading, system)
        self._say(f"KARŞILAŞTIRMA SONUCU: {comparison.sonuc}")
        if comparison.neden == "SISTEM_HESAPLAMADI" and system is not None:
            self._say("Sistem bu dosya için kesin bir son gün hesaplayamadı (SISTEM_HESAPLAMADI).")

        if comparison.sonuc == "UYUSMAZLIK":
            self._say("Nihai onay verilmez; farkı büro cihazında inceleyin. İnceleme sürerken rapor silinmez.")
            report.write_report(paths, report.build_report_text(
                reading=reading, system=system, comparison=comparison, state="UYUSMAZLIK_INCELEME_ACIK",
                kontrol_turu=state["kontrol_turu"],
            ))
            self._manifest_add_report(paths)
            state.set_state("UYUSMAZLIK_INCELEME_ACIK")
            self._save(paths, state)
            self._announce(paths.run_id)
            return

        self._approval_phase(paths, state, identity, reading, system, comparison)

    def _approval_phase(self, paths, state, identity, reading, system, comparison) -> None:
        self.step = "F4"
        if not self._fresh(paths, state):
            self._invalidate(paths, state)
            return
        self._confirm_identity(
            identity, "onay_ad", "Süre onayı için kayıtlı tam adınızı aynen yazın (ek teyit):",
        )
        # Onay sahibi = oturumdaki yetkili kullanıcı (principal). Yazılan ad YALNIZ ek
        # teyittir: kayda yalnız `ek_teyit_eslesti` yazılır, yazılan metin ASLA.
        state["onay_kimlik"] = {**identity.as_dict(), "ek_teyit_eslesti": True}
        self._save(paths, state)
        if not self._fresh(paths, state):
            self._invalidate(paths, state)
            return
        try:
            # Onay, karşılaştırmada GÖRÜLEN pending ile bağlıdır: pending o günden
            # beri değiştiyse onay verilmez (GIRDI_DEGISTI).
            self._tracked(
                paths, self.backend.approve_deadline, paths.case_id,
                expected_pending_sha=(state.get("deadline_izi") or {}).get("pending"),
            )
        except OfficeFlowError:
            raise
        except Exception as error:
            raise OfficeFlowError(outcomes.error_code_for(error)) from None
        state["deadline_izi"] = records.deadline_fingerprint(paths.case_dir)
        canonical_text, refusal = self.backend.canonical_report(paths.case_id)
        text = report.build_report_text(
            reading=reading, system=system, comparison=comparison, state="UYUMLU_RAPOR_KONTROLU",
            canonical_report=canonical_text if canonical_text else (
                f"(onaylı sonuç raporu alınamadı: {refusal})" if refusal else None
            ),
            kontrol_turu=state["kontrol_turu"],
        )
        report.write_report(paths, text)
        self._manifest_add_report(paths)
        state.set_state("UYUMLU_RAPOR_KONTROLU")
        self._save(paths, state)
        self._announce(paths.run_id)

    # ------------------------------------------------------------------
    # F5
    # ------------------------------------------------------------------

    def review(self, paths, state, identity=None) -> None:
        """Rapor kontrolü ('kontrol tamamlandı') veya inceleme kapatma.
        Kimlik (aktif + lawyer + vakaya atanmış) HER ZAMAN ilk iş: yetkisiz çağrı
        ekran çıktısı, kayıt veya durum geçişi üretmez."""
        self.step = "F5"
        identity = identity or self.backend.identity(paths.case_id)
        if state.state == "KARSILASTIRMA_YAPILDI":
            reading = self._reading(paths, state)
            system = self._system_from_state(state)
            comparison = report.compare(reading, system) if system is not None else report.Comparison(
                "UYUSMAZLIK", None, None, "SISTEM_HESAPLAMADI")
            if comparison.sonuc == "UYUMLU":
                self._approval_phase(paths, state, identity, reading, system, comparison)
            else:
                self._f4(paths, state, identity)
            if state.state not in ("UYUMLU_RAPOR_KONTROLU", "UYUSMAZLIK_INCELEME_ACIK"):
                return
        if state.state == "UYUMLU_RAPOR_KONTROLU":
            self._review_uyumlu(paths, state)
        elif state.state == "UYUSMAZLIK_INCELEME_ACIK":
            self._review_uyusmazlik(paths, state)
        else:
            raise OfficeFlowError("SILME_DURUMU_UYGUN_DEGIL")

    def _review_uyumlu(self, paths, state) -> None:
        if not self._fresh(paths, state):
            self._invalidate(paths, state)
            return
        self._say(report.read_report(paths))
        answer = self._ask("kontrol_tamam", "Raporu kontrol ettiyseniz KONTROL TAMAMLANDI yazın:")
        if answer.strip() != "KONTROL TAMAMLANDI":
            self._say("Kontrol tamamlandı olarak işaretlenmedi; rapor korunuyor.")
            return
        if not self._fresh(paths, state):
            self._invalidate(paths, state)
            return
        state.set_state("KONTROL_TAMAM")
        state["sonuc"] = "UYUMLU"
        self._save(paths, state)
        self._write_result_once(paths, state)

    def _review_uyusmazlik(self, paths, state) -> None:
        if not self._fresh(paths, state):
            # girdi değişti: UYUŞMAZLIK terfi etmez; yalnız rapor damgalanır.
            self._invalidate(paths, state)
        self._say(report.read_report(paths))
        answer = self._ask("inceleme_kapat", "İncelemeyi kapatmak için İNCELEMEYİ KAPAT yazın:")
        if answer.strip() != "İNCELEMEYİ KAPAT":
            self._say("İnceleme AÇIK kalıyor; rapor silinmez.")
            return
        category = self._ask(
            "kategori", "Hata kategorisi (sınıflamanız): TEBLIG_TARIHI_SECIMI / SURE_KURALI / "
            "TATIL_KAYDIRMASI / NEDEN_HENUZ_BELIRLENEMEDI:",
        ).strip()
        if category not in records.ERROR_CATEGORIES:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        self._say(outcomes.CATEGORY_NOT_FINDING_SENTENCE)
        self._say(outcomes.CLOSURE_NOT_PROOF_SENTENCE)
        state.set_state("INCELEME_KAPALI")
        state["sonuc"] = "UYUSMAZLIK"
        state["hata_kategorisi"] = category
        self._save(paths, state)
        self._write_result_once(paths, state)

    def _write_result_once(self, paths, state) -> None:
        """Pilot test sonucu: koşu başına en çok BİR kez (aynı jeton -> O_EXCL)."""
        if state.get("sonuc") not in outcomes.RESULTS:
            return
        if state.get("sonuc_token") is None:
            state["sonuc_token"] = outcomes.new_result_token()
            self._save(paths, state)
        kontrol_turu = state.get("kontrol_turu") or records.determine_kontrol_turu(
            paths.history_dir, state["dosya_kodu"],
        )
        record = outcomes.build_test_result(
            sonuc=state["sonuc"], kontrol_turu=kontrol_turu,
            hata_kategorisi=state.get("hata_kategorisi") if state["sonuc"] == "UYUSMAZLIK" else None,
        )
        try:
            outcomes.write_test_result(paths.records_dir, record, token=state["sonuc_token"])
        except OfficeFlowError as error:
            if error.code != "DOSYA_MEVCUT":
                raise
        state.set_state("SILME_ONAYI_BEKLIYOR")
        self._save(paths, state)
        self._say("Pilot test sonucu kaydedildi. Silme adımı için akışı yeniden başlatıp silmeyi seçebilirsiniz.")
        self._announce(paths.run_id)

    # ------------------------------------------------------------------
    # F6
    # ------------------------------------------------------------------

    def delete_run(self, paths, state, identity=None) -> cleanup.DeletionResult:
        self.step = "F6"
        # Kimlik (aktif + lawyer + vakaya atanmış) plan/ret/jeton/kayıt işinden ÖNCE:
        # yetkisiz çağrı ekran çıktısı, kayıt, bağ veya durum geçişi üretmez.
        identity = identity or self.backend.identity(paths.case_id)
        if state.state == "UYUSMAZLIK_INCELEME_ACIK":
            raise OfficeFlowError("INCELEME_ACIK")
        if state.state not in records.DELETION_ENTRY_STATES:
            raise OfficeFlowError("SILME_DURUMU_UYGUN_DEGIL")
        self._announce(paths.run_id)
        self.restore_temp()

        # Jeton YALNIZ bu koşuya aittir (koşu dizinindeki bağ + kendi durumu);
        # ofisteki başka açık jeton ASLA kullanılmaz.
        binding = records.read_imha_binding(paths.run_dir, run_id=paths.run_id)
        token = state.get("imha_token")
        if binding is not None:
            if token is not None and token != binding["imha_token"]:
                raise OfficeFlowError("SAHIPLIK_ISARETI_YOK")
            token = binding["imha_token"]
        elif token is not None:
            raise OfficeFlowError("SAHIPLIK_ISARETI_YOK")

        plan = cleanup.build_deletion_plan(paths, allow_empty_unmarked=token is not None)
        if not plan.ok:
            # Sahiplik doğrulanamadı: ad/kod/onay cümlesi İSTENMEZ, hiçbir şey silinmez.
            self._say(f"Silme REDDEDİLDİ: sahiplik doğrulanamadı ({plan.refusal_code}). "
                      "Hiçbir şey silinmedi. Sorunu giderip yeniden deneyin.")
            if plan.unregistered_count or plan.unclassified_count:
                # yalnız ADET: ad/yol gösterilmez (içerik sızıntısı yok)
                self._say(f"Bu çalışmanın bildiriminde olmayan girdi sayısı: {plan.unregistered_count}; "
                          f"tanınmayan/bağlantı girdi sayısı: {plan.unclassified_count}. Bunlar bu aracın "
                          "oluşturduğu pilot kopyası olarak doğrulanamadı; kontrol edip kendiniz taşıyın/kaldırın.")
            refusal_token = cleanup.record_refusal(paths.records_dir, token=token, now=self.clock)
            if state.state != "SILME_REDDEDILDI" and records.transition_allowed(state.state, "SILME_REDDEDILDI"):
                state.set_state("SILME_REDDEDILDI")
                self._save(paths, state)
            return cleanup.DeletionResult("REDDEDILDI", refusal_token, plan.refusal_code, [])

        self._say("SİLİNECEK PİLOT KOPYALARI (yalnız tür ve adet):")
        for item in plan.type_counts():
            self._say(f"  {item['tur']}: {item['adet']}")
        self._say("Asıl ihbarname, büronun müvekkil dosyası ve büro arşivi silme kapsamı DIŞINDADIR.")
        self._confirm_identity(identity, "silme_tam_ad", "Silmeyi onaylamak için tam adınızı yazın (kayıtlı adla aynen eşleşmeli):")
        code = self._ask("silme_kod", "Dosyanın kısa kodunu yazın:")
        if code.strip() != state["dosya_kodu"]:
            raise OfficeFlowError("ONAY_TEYIDI_BASARISIZ")
        approved = self._ask("silme_onay", "Silmeyi başlatmak için SİLMEYİ ONAYLIYORUM yazın:")
        if approved.strip() != "SİLMEYİ ONAYLIYORUM":
            raise OfficeFlowError("SILME_ONAYI_YOK")

        if token is None:
            token = records.imha_token_for_run(paths.run_id)
            records.write_imha_binding(paths, token=token, dosya_kodu=state["dosya_kodu"])
        state["imha_token"] = token
        if state.state != "SILINIYOR" and records.transition_allowed(state.state, "SILINIYOR"):
            state.set_state("SILINIYOR")
        self._save(paths, state)
        result = cleanup.execute_deletion(
            paths, records_dir=paths.records_dir, token=token, fs=self.fs, now=self.clock,
            confirmed=True,
        )
        if result.outcome == "TAMAMLANDI":
            self._say("Pilot kopyaları silindi ve doğrulandı (YALNIZ pilot kopyaları; veritabanı işlem kayıtları silinmez). "
                      + DELETION_HONEST_LIMIT)
            self._say(DEVICE_STEPS_LIST)
        else:
            if result.outcome == "KISMEN":
                self._say("Silme YARIM kaldı (SILME_YARIM); kalan pilot kopyaları var. İşlemi yeniden başlatıp tamamlayın.")
                self._announce(paths.run_id)
            else:
                self._say("Silme reddedildi; hiçbir şey silinmedi. Sahiplik doğrulanamadı; "
                          "sorunu giderip yeniden deneyin.")
                self._announce(paths.run_id)
            target = "SILME_YARIM" if result.outcome == "KISMEN" else "SILME_REDDEDILDI"
            try:
                if state.state == "SILINIYOR" and records.transition_allowed("SILINIYOR", target):
                    state.set_state(target)
                    self._save(paths, state)
            except OfficeFlowError:
                pass
        return result

    # ------------------------------------------------------------------
    # Devam / yeniden başlatma / koşu listesi
    # ------------------------------------------------------------------

    _RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")

    def list_runs(self) -> tuple:
        """([(koşu_kimliği, durum_etiketi)], bağlanamayan_açık_imha_sayısı).
        Yalnız OKUR; vaka kimliği/dosya kodu GÖSTERİLMEZ."""
        runs_dir = self.office_root / records.RUNS_DIRNAME
        found, bound_tokens = [], set()
        try:
            names = sorted(entry.name for entry in os.scandir(str(runs_dir)))
        except OSError:
            names = []
        for name in names:
            run_dir = runs_dir / name
            if not self._RUN_ID_RE.match(name) or os.path.islink(str(run_dir)) or not run_dir.is_dir():
                continue
            if not records.read_owner_marker(run_dir, run_id=name, kind="run_dir"):
                found.append((name, "SAHIPLIK_ISARETI_YOK"))
                continue
            binding = records.read_imha_binding(run_dir, run_id=name)
            if binding is not None:
                bound_tokens.add(binding["imha_token"])
            if not records.run_state_present(run_dir):
                found.append((name, "DURUM_DOSYASI_YOK"))
                continue
            try:
                found.append((name, records.load_run_state(run_dir).state))
            except OfficeFlowError:
                found.append((name, "DURUM_DOSYASI_BOZUK"))
        open_tokens = [t for t in outcomes.open_imha_tokens(self.office_root / records.RECORDS_DIRNAME)]
        unbound = sum(1 for token in open_tokens if token not in bound_tokens)
        return found, unbound

    def select_run(self):
        """`--devam` verilmediğinde: açık/yarım koşuları KİMLİK + DURUM ile listeler,
        kullanıcıdan birini seçmesini ister."""
        found, unbound = self.list_runs()
        if not found:
            self._say("Açık veya yarım kalmış çalışma yok.")
        else:
            self._say("AÇIK / YARIM ÇALIŞMALAR (kimlik  durum):")
            for run_id, label in found:
                self._say(f"  {run_id}  {label}")
        if unbound:
            self._say(f"Hiçbir koşuya bağlanamayan açık imha kaydı sayısı: {unbound}. "
                      "Hiçbir şey değiştirilmedi; bu durumu avukata/geliştirici desteğine bildirin.")
        if not found:
            return None
        chosen = self._ask("devam_secimi", "Devam edilecek çalışma kimliğini yazın (boş bırakırsanız çıkılır):").strip()
        if not chosen:
            return None
        return self.continue_run(chosen)

    def continue_run(self, run_id: str):
        """Kalıcı duruma göre devam: karşılaştırma sonrası -> F4/F5; silme
        durumları -> F6; zincir ortasında kalmış -> DURDURULDU.
        Bozuk durum dosyası -> DUR (hiçbir şey silinmez/yazılmaz); durum dosyası
        yoksa yalnız bu koşunun kendi imha bağıyla, avukatın AYRI onayıyla."""
        if not self._RUN_ID_RE.match(str(run_id)):
            raise OfficeFlowError("KOD_GECERSIZ")
        run_dir = self.office_root / records.RUNS_DIRNAME / run_id
        if not os.path.lexists(str(run_dir)):
            raise OfficeFlowError("KOD_GECERSIZ")
        if os.path.islink(str(run_dir)) or not records.read_owner_marker(run_dir, run_id=run_id, kind="run_dir"):
            raise OfficeFlowError("SAHIPLIK_ISARETI_YOK")
        if not records.run_state_present(run_dir):
            binding = records.read_imha_binding(run_dir, run_id=run_id)
            if binding is None:
                self._announce(run_id)
                self._say("Bu çalışmanın durum dosyası yok ve imha jetonu bu çalışmaya bağlanamıyor. "
                          "Hiçbir şey silinmedi veya değiştirilmedi. Avukata/geliştirici desteğine bildirin.")
                return None
            paths = self._paths(run_id, binding["case_id"])
            identity = self.backend.identity(paths.case_id)   # ekran/kayıt/durumdan ÖNCE
            self._announce(run_id)
            state = records.RunState.new(run_id=run_id, case_id=binding["case_id"], dosya_kodu=binding["dosya_kodu"])
            state["durum"] = "SILINIYOR"
            state.data["gecmis"].append("SILINIYOR")
            state["imha_token"] = binding["imha_token"]
            return self.delete_run(paths, state, identity)

        try:
            state = records.load_run_state(run_dir)
            if state["kos"] != run_id:
                raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
            paths = self._paths(run_id, state["case_id"])
        except (OfficeFlowError, KeyError):
            self._say("Çalışma durum dosyası bozuk, eksik alanlı veya bu çalışmaya ait değil. DURULDU: hiçbir şey silinmedi, "
                      "hiçbir kayıt yazılmadı. Avukata/geliştirici desteğine bildirin.")
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ") from None
        # Kontrolü değiştiren/gösteren/kaydeden HER devam yolunun ilk işi: kimlik.
        identity = self.backend.identity(paths.case_id)
        self._announce(run_id)
        if state.state in _FULL_CHAIN_STATES:
            self._halt_if_prechain(paths, state)
            self._say("Zincir tamamlanmadan yarım kalmış; çalışma DURDURULDU. Silme adımı yapılabilir.")
            return None
        if state.state in ("KARSILASTIRMA_YAPILDI", "UYUMLU_RAPOR_KONTROLU", "UYUSMAZLIK_INCELEME_ACIK"):
            self._redirect_temp(paths)
            try:
                self.review(paths, state, identity)
            finally:
                self.restore_temp()
            if state.state != "SILME_ONAYI_BEKLIYOR":
                return None
            if self._ask("silme_simdi", "Silme adımına şimdi geçilsin mi? (evet/hayır):").strip().lower() != "evet":
                return None
            return self.delete_run(paths, state, identity)
        if state.state in ("KONTROL_TAMAM", "INCELEME_KAPALI"):
            # sonuç kaydı yazım penceresinde kalmış olabilir (idempotent)
            self._write_result_once(paths, state)
        return self.delete_run(paths, state, identity)


# ----------------------------------------------------------------
# CLI
# ----------------------------------------------------------------


class _QuietParser(argparse.ArgumentParser):
    """argparse hata iletisi argüman DEĞERİNİ yansıtabilir; kapalı sabit satır."""

    closed_stderr = None

    def error(self, message):
        (self.closed_stderr or sys.stderr).write("KULLANIM_HATASI: argümanlar geçersiz veya eksik\n")
        raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    parser = _QuietParser(
        prog="python -m ui.office_deadline_flow", add_help=True,
        description="Büro modeli: tek yönlendirmeli süre ön hesabı akışı (T1).",
    )
    parser.add_argument("--office-root", required=True)
    parser.add_argument("--actor-user-id", type=int, required=True)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--dosya-kodu", default=None)
    parser.add_argument("--kaynak-pdf", default=None)
    parser.add_argument("--devam", default=None, help="mevcut koşu kimliği")
    return parser


def main(argv=None, *, backend=None, io=None, extractor=None, case_root=None, stdout=None,
         stderr=None, allow_system_drive=None) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        parser = _build_parser()
        parser.closed_stderr = stderr
        args = parser.parse_args(argv)
    except SystemExit as exit_signal:
        return EXIT_USAGE_ERROR if exit_signal.code else EXIT_OK

    previous_last_resort = logging.lastResort
    quiet = logging.getLogger("vergi_ai")
    quiet.addHandler(logging.NullHandler())
    previous_propagate = quiet.propagate
    quiet.propagate = False
    logging.lastResort = None
    flow = None
    own_backend = backend is None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from ui.services import paths as _paths

            flow_io = io or ConsoleIO(stdout=stdout)
            if backend is None:
                backend = RealChainBackend(actor_user_id=args.actor_user_id)
            # Sistem sürücüsü gevşetmesi YALNIZ test parametresidir: ne komut satırından
            # ne de ortam değişkeninden açılabilir (üretimde sessizce açılamaz).
            flow = OfficeFlow(
                office_root=args.office_root, case_root=case_root or _paths.CASES_DIR,
                backend=backend, io=flow_io, extractor=extractor,
                allow_system_drive=bool(allow_system_drive),
            )
            if args.devam:
                flow.continue_run(args.devam)
            elif not args.case_id and not args.dosya_kodu:
                # `--devam` yok ve yeni koşu da istenmiyor: açık/yarım koşuları listele.
                flow.select_run()
            else:
                if not args.case_id or not args.dosya_kodu:
                    stderr.write("KULLANIM_HATASI: --case-id ve --dosya-kodu birlikte gerekli (veya --devam)\n")
                    return EXIT_USAGE_ERROR
                flow.run_new(case_id=args.case_id, dosya_kodu=args.dosya_kodu, source_pdf=args.kaynak_pdf)
        return EXIT_OK
    except BaseException as error:  # noqa: BLE001 - hata yolu KAPALI kümeye eşlenir
        if isinstance(error, SystemExit):
            raise
        code = outcomes.error_code_for(error)
        if flow is not None and flow.run_id:
            try:  # durma çıktısında kimlik: kullanıcı --devam ile geri dönebilsin (stdout; özette YOK)
                stdout.write(f"Çalışma kimliği: {flow.run_id}  (devam etmek için: --devam {flow.run_id})\n")
            except Exception:
                pass
        step = flow.step if flow is not None and flow.step in records.PROCESS_STEPS else "F0"
        summary = outcomes.build_support_summary(islem_adimi=step, hata_kodu=code)
        stderr.write(outcomes.render_support_summary(summary))
        return EXIT_DOMAIN_ERROR
    finally:
        if flow is not None:
            flow.restore_temp()
        if own_backend and backend is not None:
            try:
                backend.close()
            except Exception:
                pass
        logging.lastResort = previous_last_resort
        quiet.propagate = previous_propagate


if __name__ == "__main__":
    sys.exit(main())
