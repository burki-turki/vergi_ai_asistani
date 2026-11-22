# ============================================================
# BÜRO MODELİ / T1 - ui/office_deadline_flow.py İZOLE (SAHTE ARKA UÇ) TESTİ
# Akış mantığı: SIRA (F2 -> aday/sonuç), durum makinesi, UYUMLU/UYUŞMAZLIK/
# GEÇERSİZ, kimlik (ek teyit), kapalı hata/destek özeti, CLI, TEMP yönlendirmesi,
# S1-S4 MANTIK düzeyi (gerçek zincir/PG kanıtı ayrı PG modülündedir).
#
# Sahte arka uç facade/PG kullanmaz; dosya düzenini taklit eder (manifest/
# bayatlık gerçek dosya baytlarıyla çalışır). Asıl PDF: bayt/mtime + audit-hook.
# ============================================================

import hashlib
import io
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


def summarize_and_exit():
    print(f"--- test_office_deadline_flow_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


import ui.office_deadline_flow as F  # noqa: E402
from ui.services import office_flow_cleanup as cleanup  # noqa: E402
from ui.services import office_flow_intake as intake  # noqa: E402
from ui.services import office_flow_outcomes as outcomes  # noqa: E402
from ui.services import office_flow_records as R  # noqa: E402
from ui.services.authz import CaseAccessDeniedError  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_flow_"))
NAME = "Av. Örnek Kullanıcı"
OTHER_NAME = "Av. Başka Kişi"
TEXT = ("SENTETİK İHBARNAME - GERÇEK DEĞİL\n"
        "Düzenleme 05.02.2026 ve vade 06.02.2026 tarihlidir.\n"
        "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.\n"
        "Ek yazı 15.02.2026 tarihlidir.\n")
PDF = b"%PDF-1.4\nsentetik asil\n%%EOF\n"
SENT = ["10.02.2026", "2026-02-10", "12.03.2026", "2026-03-12", "13.03.2026", "tebliğ edilmiştir", "asil_belge"]
SOURCE_EVENTS = []
WATCH = {"path": None}


def _audit(event, args):
    try:
        if WATCH["path"] and args and isinstance(args[0], (str, bytes, os.PathLike)):
            text = os.fsdecode(args[0])
            if os.path.basename(text).startswith("asil_belge") and os.path.normcase(os.path.realpath(text)) == WATCH["path"]:
                if event in ("os.remove", "os.rmdir", "os.rename", "shutil.rmtree", "os.truncate"):
                    SOURCE_EVENTS.append(event)
                elif event == "open" and isinstance(args[1], str) and any(c in args[1] for c in "wax+"):
                    SOURCE_EVENTS.append(("open", args[1]))
    except Exception:
        pass


sys.addaudithook(_audit)


class ScriptedIO:
    def __init__(self, answers, events, on_ask=None):
        self.answers = {k: (list(v) if isinstance(v, (list, tuple)) else [v]) for k, v in answers.items()}
        self.asked, self.said, self.events, self.on_ask = [], [], events, on_ask
        self.prompts = []

    def ask(self, key, prompt):
        self.asked.append(key)
        self.prompts.append(prompt)
        self.events.append(("ask", key))
        if self.on_ask:
            override = self.on_ask(key)
            if override is not None:
                return override
        queue = self.answers.get(key)
        if not queue:
            raise EOFError()
        return queue.pop(0)

    def say(self, text):
        self.said.append(text)
        self.events.append(("say", text))


class FakeBackend:
    actor_user_id = 7

    def __init__(self, case_root, events, *, system=("2026-02-10", "calculated", "2026-03-12"), anchors=1, fail_at=None,
                 holiday_ok=True, secret_failure=None):
        self.case_root, self.events = Path(case_root), events
        self.system, self.anchors, self.fail_at, self.holiday_ok, self.secret_failure = system, anchors, fail_at, holiday_ok, secret_failure
        self.temp_seen = []
        self.identity_calls, self.deny = 0, False
        self.deny_from_call = None   # TF-1: bu sıradaki (1 tabanlı) kimlik çağrısından itibaren IAM reddeder
        self.db_time_by_call = None  # L-1: çağrı sırasına (1 tabanlı) bağlı db_time; None = bugünkü sabit değer
        self.deny_chain_step = None  # O-5 (D2): `deny` açıkken bu zincir adımı facade gibi CaseAccessDeniedError fırlatır
        self.global_file = TMP / "global_ruleset.json"
        self.global_file.write_text("v1", encoding="utf-8")
        self.name = NAME

    def _enter(self, name, case_id=None):
        self.events.append(("backend", name))
        self.temp_seen.append((name, os.path.realpath(tempfile.gettempdir())))
        if self.deny and self.deny_chain_step == name:
            raise CaseAccessDeniedError("no_assignment")   # gerçek facade'in canlı authorize_case_access reddi
        if self.secret_failure and self.fail_at == name:
            raise RuntimeError(self.secret_failure)
        if self.fail_at == name:
            raise RuntimeError("beklenmeyen zincir hatasi")

    def _case(self, case_id):
        return self.case_root / case_id

    def identity(self, case_id):
        self.events.append(("identity", case_id))
        self.identity_calls += 1
        if self.deny or (self.deny_from_call is not None and self.identity_calls >= self.deny_from_call):
            raise R.OfficeFlowError("YETKI_YOK")
        db_time = "2026-11-18T10:00:00+00:00" if self.db_time_by_call is None else self.db_time_by_call(self.identity_calls)
        return R.IdentitySnapshot(7, self.name, "kullanici", "makine", db_time)

    def holiday_calendar_ok(self):
        return self.holiday_ok

    def global_input_paths(self):
        return {"ruleset": self.global_file}

    def release(self):
        pass

    def close(self):
        self.closed = True

    def manual_fact(self, case_id):
        self._enter("manual_fact", case_id)
        d = self._case(case_id) / "documents" / intake.DOC_ID / "extractions"
        d.mkdir(exist_ok=True)
        (d / "facts_pending.json.pending").write_text("{\"pending\":1}", encoding="utf-8")

    def promote_fact(self, case_id):
        self._enter("promote_fact", case_id)
        (self._case(case_id) / "documents" / intake.DOC_ID / "extractions" / "facts.json").write_text(
            json.dumps({"facts": [{"fact_id": "f1", "verification_state": "unverified"}]}), encoding="utf-8")

    def verify_fact(self, case_id):
        self._enter("verify_fact", case_id)
        (self._case(case_id) / "documents" / intake.DOC_ID / "extractions" / "facts.json").write_text(
            json.dumps({"facts": [{"fact_id": "f1", "verification_state": "verified"}]}), encoding="utf-8")

    def generate_timeline(self, case_id):
        self._enter("generate_timeline", case_id)
        (self._case(case_id) / "timeline").mkdir(exist_ok=True)
        (self._case(case_id) / "timeline" / "timeline_v1.json.pending").write_text("{}", encoding="utf-8")

    def promote_timeline(self, case_id):
        self._enter("promote_timeline", case_id)
        (self._case(case_id) / "timeline" / "timeline.json").write_text("{\"events\":[]}", encoding="utf-8")

    def anchor_candidates(self, case_id):
        return [f"timeline_event_00{i}" for i in range(1, self.anchors + 1)]

    def generate_deadline(self, case_id, anchor, adli, stopping, ref):
        self._enter("generate_deadline", case_id)
        self.last_declarations = (adli, stopping, ref)
        (self._case(case_id) / "deadlines").mkdir(exist_ok=True)
        anchor_date, state, deadline = self.system
        (self._case(case_id) / "deadlines" / f"deadline_{case_id}_v1.json.pending").write_text(json.dumps({
            "deadlines": [{"anchor_date": anchor_date, "calculation_state": state, "calculated_deadline": deadline,
                           "rule_id": "iyuk_x", "requires_human_review": state != "calculated"}]}), encoding="utf-8")

    def pending_deadline_path(self, case_id):
        return self._case(case_id) / "deadlines" / f"deadline_{case_id}_v1.json.pending"

    def approve_deadline(self, case_id, expected_pending_sha=None):
        self._enter("approve_deadline", case_id)
        self.last_expected_pending_sha = expected_pending_sha
        (self._case(case_id) / "deadlines" / "deadline.json").write_text("{\"approved\":1}", encoding="utf-8")

    def canonical_report(self, case_id):
        self._enter("canonical_report", case_id)
        return "ONAYLI SONUC RAPORU\n", None


class Ctx:
    pass


def start(tag, *, answers=None, backend_kwargs=None, probes=None, office=None, dosya_kodu=None, on_ask=None, fs=None):
    ctx = Ctx()
    ctx.tag = tag
    ctx.office = office or (TMP / f"ofis_{tag}")
    if office is None:
        ctx.office.mkdir()
    ctx.cases = TMP / f"vakalar_{tag}"
    ctx.cases.mkdir()
    ctx.source = TMP / f"kaynak_{tag}" / f"asil_belge_{tag}.pdf"
    ctx.source.parent.mkdir()
    ctx.source.write_bytes(PDF)
    os.chmod(ctx.source, 0o444)
    ctx.source_id = (hashlib.sha256(PDF).hexdigest(), ctx.source.stat().st_size, ctx.source.stat().st_mtime_ns)
    ctx.case_id = f"vaka{tag}"
    ctx.dosya = dosya_kodu or f"DK{tag}"
    ctx.events = []
    ctx.backend = FakeBackend(ctx.cases, ctx.events, **(backend_kwargs or {}))
    ctx.probes = probes if probes is not None else {"import_probe": lambda n: False, "env": {}, "dsn": ""}
    ctx.on_ask, ctx.fs = on_ask, fs
    ctx.answers = answers
    return ctx


def base_answers(**over):
    a = {"kimlik_ad": NAME, "sayfa_sayisi": "2", "vergi_turleri": "KDV", "tebligat_tarihi": "10.02.2026",
         "tebligat_sayfa": "1", "kor_son_gun": "12.03.2026", "adli_tatil": "no", "stopping_durum": "none",
         "stopping_ref": "BEYAN-T1", "aday_secimi": "1", "dogrulama_karari": "evet", "onay_ad": NAME}
    a.update(over)
    return a


def flow_for(ctx, answers):
    ctx.io = ScriptedIO(answers, ctx.events, on_ask=ctx.on_ask)
    ctx.flow = F.OfficeFlow(office_root=ctx.office, case_root=ctx.cases, backend=ctx.backend, io=ctx.io,
                            extractor=lambda p: TEXT, repo_root=REPO_ROOT, allow_system_drive=True,
                            preflight_options=ctx.probes, fs=ctx.fs)
    return ctx.flow


def new_run(ctx, answers=None):
    WATCH["path"] = os.path.normcase(os.path.realpath(str(ctx.source)))
    del SOURCE_EVENTS[:]
    flow = flow_for(ctx, answers if answers is not None else base_answers())
    ctx.new_io = ctx.io
    ctx.run_id = flow.run_new(case_id=ctx.case_id, dosya_kodu=ctx.dosya, source_pdf=ctx.source)
    ctx.paths = R.build_run_paths(ctx.office, ctx.cases, ctx.case_id, ctx.run_id)
    return ctx.run_id


def resume(ctx, answers):
    WATCH["path"] = os.path.normcase(os.path.realpath(str(ctx.source)))
    flow = flow_for(ctx, answers)
    return flow.continue_run(ctx.run_id)


def state_of(ctx):
    return R.load_run_state(ctx.paths.run_dir)


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except R.OfficeFlowError as error:
        return error.code
    return None


def kayitlar(ctx):
    return sorted((ctx.office / "kayitlar").iterdir())


def results(ctx):
    return [json.loads(p.read_bytes()) for p in kayitlar(ctx) if p.name.startswith("test_sonucu_")]


def imha(ctx):
    return [json.loads(p.read_bytes()) for p in kayitlar(ctx) if p.name.startswith("imha_")]


def source_ok(ctx):
    return ctx.source.exists() and (hashlib.sha256(ctx.source.read_bytes()).hexdigest(), ctx.source.stat().st_size,
                                    ctx.source.stat().st_mtime_ns) == ctx.source_id and not SOURCE_EVENTS


DEL = lambda c: {"silme_tam_ad": NAME, "silme_kod": c.dosya, "silme_onay": "SİLMEYİ ONAYLIYORUM", "kimlik_ad": NAME}


try:
    # ================================================================ sıra
    c1 = start("s1")
    new_run(c1)
    ev = c1.events
    last_f2 = max(i for i, e in enumerate(ev) if e == ("ask", "stopping_ref"))
    first_cand = next(i for i, e in enumerate(ev) if e[0] == "say" and "ADAY SATIR" in e[1])
    first_backend = next(i for i, e in enumerate(ev) if e[0] == "backend")
    first_system = next(i for i, e in enumerate(ev) if e[0] == "say" and "SİSTEMİN SONUCU" in e[1])
    first_date = next(i for i, e in enumerate(ev) if e[0] == "say" and any(d in e[1] for d in ("10.02.2026", "12.03.2026")))
    check("ORDER: the F2 independent reading is asked BEFORE the candidate list, any backend call and the system result",
          last_f2 < first_cand < first_backend < first_system, f"{last_f2},{first_cand},{first_backend},{first_system}")
    check("ORDER: no date is printed before the F2 reading was recorded", first_date >= first_cand > last_f2)
    check("ORDER: the F4 result is printed only AFTER the deadline generation call",
          first_system > max(i for i, e in enumerate(ev) if e == ("backend", "generate_deadline")))
    check("the exact chain order is manual_fact, promote_fact, verify_fact, generate_timeline, promote_timeline, generate_deadline, approve_deadline, canonical_report",
          [e[1] for e in ev if e[0] == "backend"] == ["manual_fact", "promote_fact", "verify_fact", "generate_timeline", "promote_timeline",
                                                        "generate_deadline", "approve_deadline", "canonical_report"], str([e[1] for e in ev if e[0] == "backend"]))
    reading_file = c1.paths.reading_path
    check("the reading record exists on disk with the lawyer's values BEFORE the first backend call (file created, hash stored in the run state)",
          reading_file.is_file() and state_of(c1)["okuma_sha"] == R.sha256_hex(reading_file.read_bytes()))
    onay = state_of(c1)["onay_kimlik"]
    check("the approval record holds the SESSION identity (user id, registered name, OS user, machine, DB time) and ONLY the boolean ek_teyit_eslesti - never the typed text",
          onay["user_id"] == 7 and onay["display_name"] == NAME and onay["ek_teyit_eslesti"] is True and onay["windows_user"] and onay["machine_name"]
          and onay["db_time"] and set(onay) == {"user_id", "display_name", "windows_user", "machine_name", "db_time", "ek_teyit_eslesti"})
    check("the lawyer's declarations were handed to the deadline generation unchanged", c1.backend.last_declarations == ("no", "none", "BEYAN-T1"))
    st = state_of(c1)
    check("S1 logic: UYUMLU -> state UYUMLU_RAPOR_KONTROLU, approval performed once, report written with the approved report appended",
          st.state == "UYUMLU_RAPOR_KONTROLU" and sum(1 for e in ev if e == ("backend", "approve_deadline")) == 1
          and "ONAYLI SONUC RAPORU" in c1.paths.report_path.read_text(encoding="utf-8"))
    check("the run state is the ONLY place the system result lives besides the report (both inside the run dir)",
          st["sistem_ozeti"]["calculated_deadline"] == "2026-03-12" and "2026-03-12" not in "".join(p.read_text(encoding="utf-8") for p in (c1.office / "kayitlar").iterdir()))
    resume(c1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "evet", **DEL(c1)})
    check("S1 logic: 'kontrol tamamlandı' -> ONE result UYUMLU/ILK_KONTROL, then the lawyer-approved deletion -> TAMAMLANDI, dirs gone",
          results(c1) == [{"kayit_surumu": 1, "yazilim_surumu": R.SOFTWARE_VERSION, "sonuc": "UYUMLU", "kontrol_turu": "ILK_KONTROL"}]
          and [r["asama"] for r in imha(c1)] == ["BASLADI", "SONUC"] and imha(c1)[-1]["genel_sonuc"] == "TAMAMLANDI"
          and not c1.paths.case_dir.exists() and not c1.paths.run_dir.exists())
    text_all = "".join(p.read_text(encoding="utf-8") for p in kayitlar(c1))
    check("S1 logic: no sentinel (date/excerpt/name/ids/hash/path) in any record", not any(s in text_all for s in SENT + [c1.case_id, c1.run_id, NAME, c1.dosya, str(TMP)]))
    check("S1 logic: the original PDF is intact (sha/size/mtime + no write/delete audit event)", source_ok(c1), str(SOURCE_EVENTS))
    check("S1 logic: TEMP was redirected into the run tmp dir for EVERY backend call and restored afterwards",
          all(seen == os.path.realpath(str(c1.paths.tmp_dir)) for _n, seen in c1.backend.temp_seen)
          and os.path.realpath(tempfile.gettempdir()) != os.path.realpath(str(c1.paths.tmp_dir)))

    # ================================================================ S2 mantığı
    c2 = start("s2", answers=None)
    new_run(c2, base_answers(kor_son_gun="13.03.2026"))
    st2 = state_of(c2)
    check("S2 logic: one day off -> UYUSMAZLIK_INCELEME_ACIK; the approval step is never offered and no approval call happens",
          st2.state == "UYUSMAZLIK_INCELEME_ACIK" and "onay_ad" not in c2.io.asked and ("backend", "approve_deadline") not in c2.events)
    check("S2 logic: the report exists immediately and states UYUSMAZLIK; no canonical deadline file",
          "UYUSMAZLIK" in c2.paths.report_path.read_text(encoding="utf-8") and not (c2.paths.case_dir / "deadlines" / "deadline.json").exists())
    rep_hash = hashlib.sha256(c2.paths.report_path.read_bytes()).hexdigest()
    flow2 = flow_for(c2, {})
    check("S2 logic: a direct deletion request is refused (INCELEME_ACIK); nothing deleted",
          code_of(flow2.delete_run, c2.paths, state_of(c2)) == "INCELEME_ACIK" and c2.paths.case_dir.exists())
    resume(c2, {"inceleme_kapat": "hayır"})
    resume(c2, {"inceleme_kapat": "kapat"})
    check("S2 logic: a later launch that does not close the review changes nothing (report bytes, state, dirs); no auto deletion",
          hashlib.sha256(c2.paths.report_path.read_bytes()).hexdigest() == rep_hash and state_of(c2).state == "UYUSMAZLIK_INCELEME_ACIK"
          and c2.paths.case_dir.exists() and results(c2) == [])
    check("S2 logic: closing with an unknown category is refused and leaves the review OPEN",
          code_of(resume, c2, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "serbest metin"}) == "KAYIT_SEMASI_GECERSIZ"
          and state_of(c2).state == "UYUSMAZLIK_INCELEME_ACIK" and results(c2) == [])
    resume(c2, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "TATIL_KAYDIRMASI", "silme_simdi": "evet", **DEL(c2)})
    check("S2 logic: closing -> result UYUSMAZLIK + TATIL_KAYDIRMASI (never UYUMLU); then the lawyer-approved deletion completes",
          results(c2) == [{"kayit_surumu": 1, "yazilim_surumu": R.SOFTWARE_VERSION, "sonuc": "UYUSMAZLIK", "kontrol_turu": "ILK_KONTROL",
                           "hata_kategorisi": "TATIL_KAYDIRMASI"}] and imha(c2)[-1]["genel_sonuc"] == "TAMAMLANDI" and not c2.paths.case_dir.exists())
    check("S2 logic: the closing text states the category is not a finding and closing is not proof of correctness",
          any(outcomes.CATEGORY_NOT_FINDING_SENTENCE in t for t in c2.io.said) and any(outcomes.CLOSURE_NOT_PROOF_SENTENCE in t for t in c2.io.said))
    check("S2 logic: the original PDF is intact", source_ok(c2))

    # F3 tarih uyuşmazlığı
    c3 = start("f3")
    new_run(c3, base_answers(aday_secimi="2"))
    check("F3: a chosen candidate line whose date differs from the independent F2 date -> UYUSMAZLIK with NO backend call at all (no promotion/calculation)",
          state_of(c3).state == "UYUSMAZLIK_INCELEME_ACIK" and not [e for e in c3.events if e[0] == "backend"]
          and "onay_ad" not in c3.io.asked and not (c3.paths.case_dir / "documents" / intake.DOC_ID / "manual_input").exists())
    check("F3: the report shows both dates and 'Hesap yapılmadı.'",
          all(t in c3.paths.report_path.read_text(encoding="utf-8") for t in ("15.02.2026", "10.02.2026", "Hesap yapılmadı.")))
    check("F3: the result is NOT recorded until the lawyer closes the review", results(c3) == [])

    # sistem hesaplamadı / belirsiz
    c4 = start("nc", backend_kwargs={"system": ("2026-02-10", "needs_review", None)})
    new_run(c4)
    check("an un-calculated system result (needs_review) is UYUSMAZLIK / SISTEM_HESAPLAMADI: no approval is offered",
          state_of(c4).state == "UYUSMAZLIK_INCELEME_ACIK" and "onay_ad" not in c4.io.asked and any("SISTEM_HESAPLAMADI" in t for t in c4.io.said))
    c4b = start("anch", backend_kwargs={"system": ("2026-02-11", "calculated", "2026-03-12")})
    new_run(c4b)
    check("a system anchor date different from the lawyer's independent date is UYUSMAZLIK (no approval)",
          state_of(c4b).state == "UYUSMAZLIK_INCELEME_ACIK" and ("backend", "approve_deadline") not in c4b.events)

    # ================================================================ S3 mantığı
    def invalidate_facts(ctx):
        facts = ctx.cases / ctx.case_id / "documents" / intake.DOC_ID / "extractions" / "facts.json"
        facts.write_text(json.dumps({"facts": [{"fact_id": "f1", "verification_state": "unverified"}]}), encoding="utf-8")

    c5 = start("s3a")
    c5.on_ask = lambda key: (invalidate_facts(c5), None)[1] if key == "onay_ad" else None
    new_run(c5)
    check("S3 logic: a verified input changed before the approval -> GECERSIZ; NO approval call, no 'kontrol tamamlandı', no result",
          state_of(c5).state == "GECERSIZ" and ("backend", "approve_deadline") not in c5.events and "kontrol_tamam" not in c5.io.asked and results(c5) == [])
    check("S3 logic: the user is told the old result is unusable (GIRDI_DEGISTI)", any("GIRDI_DEGISTI" in t for t in c5.io.said))
    c5.on_ask = None
    resume(c5, {"silme_tam_ad": NAME, "silme_kod": c5.dosya, "silme_onay": "SİLMEYİ ONAYLIYORUM", "kimlik_ad": NAME})
    check("S3 logic: an invalid run can be deleted by the lawyer's separate approval; still NO test result", results(c5) == [] and not c5.paths.case_dir.exists()
          and imha(c5)[-1]["genel_sonuc"] == "TAMAMLANDI")

    c6 = start("s3b")
    new_run(c6)
    invalidate_facts(c6)
    resume(c6, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    check("S3 logic: after the approval a changed input makes 'kontrol tamamlandı' impossible (GECERSIZ, report stamped, no result)",
          state_of(c6).state == "GECERSIZ" and c6.paths.report_path.read_text(encoding="utf-8").startswith("*** GEÇERSİZ") and results(c6) == [])
    c6g = start("s3g")
    new_run(c6g)
    c6g.backend.global_file.write_text("v2", encoding="utf-8")
    resume(c6g, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    check("S3 logic: a GLOBAL input change (ruleset) is detected exactly like a case input change",
          state_of(c6g).state == "GECERSIZ" and results(c6g) == [])
    c7 = start("s3c")
    new_run(c7, base_answers(kor_son_gun="20.03.2026"))
    invalidate_facts(c7)
    resume(c7, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "NEDEN_HENUZ_BELIRLENEMEDI", "silme_simdi": "hayır"})
    check("S3 logic: an input change during an open UYUSMAZLIK review keeps it UYUSMAZLIK (stamped report, result UYUSMAZLIK, never UYUMLU)",
          results(c7) and results(c7)[0]["sonuc"] == "UYUSMAZLIK" and c7.paths.report_path.read_text(encoding="utf-8").startswith("*** GEÇERSİZ"))
    c8 = start("s3d")
    new_run(c8)
    (c8.cases / c8.case_id / "deadlines" / f"deadline_{c8.case_id}_v1.json.pending").write_text("{\"degisti\":1}", encoding="utf-8")
    resume(c8, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    check("S3 logic: a changed pending/canonical deadline file (the result itself) is detected too (deadline fingerprint)", state_of(c8).state == "GECERSIZ" and results(c8) == [])

    # ================================================================ S4 mantığı
    class FaultyFs(cleanup.FsOps):
        def __init__(self, deny=None, kill_after=None):
            self.deny, self.kill_after, self.calls = deny, kill_after, 0

        def unlink(self, path):
            self.calls += 1
            if self.deny and self.deny in str(path).replace("\\", "/"):
                raise PermissionError("kilitli")
            if self.kill_after is not None and self.calls > self.kill_after:
                raise SimulatedKill()
            super().unlink(path)

    class SimulatedKill(BaseException):
        pass

    def ready(tag):
        c = start(tag)
        new_run(c)
        resume(c, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
        return c

    d1 = ready("s4a")
    d1.fs = FaultyFs(deny="documents/ihbarname_001/extractions/facts.json")
    resume(d1, DEL(d1))
    check("S4 logic (a): one undeletable path -> BASLADI + SONUC=KISMEN, never TAMAMLANDI; state SILME_YARIM",
          [r["asama"] for r in imha(d1)] == ["BASLADI", "SONUC"] and imha(d1)[-1]["genel_sonuc"] == "KISMEN" and state_of(d1).state == "SILME_YARIM")
    d1.fs = None
    resume(d1, DEL(d1))
    check("S4 logic (a): a healthy retry completes; exactly one TAMAMLANDI", sum(1 for r in imha(d1) if r.get("genel_sonuc") == "TAMAMLANDI") == 1 and not d1.paths.case_dir.exists())
    d2 = ready("s4c")
    d2.fs = FaultyFs(kill_after=2)
    killed = False
    try:
        resume(d2, DEL(d2))
    except SimulatedKill:
        killed = True
    check("S4 logic (c): process death -> last record BASLADI, no SONUC; state stays SILINIYOR (resumable)",
          killed and imha(d2)[-1]["asama"] == "BASLADI" and all("genel_sonuc" not in r for r in imha(d2)) and state_of(d2).state == "SILINIYOR")
    d2.fs = None
    resume(d2, DEL(d2))
    check("S4 logic (c): the restart resumes from the persisted state and finishes with TAMAMLANDI only after verification",
          imha(d2)[-1]["genel_sonuc"] == "TAMAMLANDI" and not d2.paths.case_dir.exists() and not d2.paths.run_dir.exists())
    d3 = ready("s4d")
    foreign_pdf = d3.paths.case_dir / "documents" / intake.DOC_ID / "baska_muvekkil.pdf"   # kapalı tür desenine UYAN yabancı ad
    foreign_pdf.write_bytes(b"x")
    listing = sorted(os.path.join(r, f) for r, _d, fs in os.walk(d3.paths.case_dir) for f in fs)
    resume(d3, {})   # HİÇ cevap yok: plan reddedilirse ad/kod/onay cümlesi SORULMAMALI (soru gelseydi EOFError)
    check("S4 logic (d) / H-1+L-6: an office file that merely MATCHES a closed type name (not in the run's manifest) -> REDDEDILDI, nothing deleted, "
          "NO name/code/phrase question, state SILME_REDDEDILDI (not SILME_YARIM)",
          imha(d3)[-1]["genel_sonuc"] == "REDDEDILDI" and sorted(os.path.join(r, f) for r, _d, fs in os.walk(d3.paths.case_dir) for f in fs) == listing
          and state_of(d3).state == "SILME_REDDEDILDI"
          and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(d3.io.asked)
          and [r["asama"] for r in imha(d3)] == ["SONUC"], f"{state_of(d3).state} {d3.io.asked}")
    foreign_pdf.unlink()
    resume(d3, DEL(d3))
    check("S4 logic (d): once the lawyer removes the foreign file the SAME run (SILME_REDDEDILDI) is retried with the full approval and completes (TAMAMLANDI)",
          sorted(r.get("genel_sonuc") or "-" for r in imha(d3)) == ["-", "REDDEDILDI", "TAMAMLANDI"]   # iki ayrı jeton: kayıt SIRASI dosya adına bağlı DEĞİL
          and not d3.paths.case_dir.exists() and not d3.paths.run_dir.exists()
          and {"silme_tam_ad", "silme_kod", "silme_onay"} <= set(d3.io.asked))
    d4 = ready("s4e")
    (d4.paths.case_dir / R.OWNER_MARKER_NAME).unlink()
    resume(d4, {})
    check("S4 logic (e): a missing ownership marker -> REDDEDILDI, nothing deleted, no approval questions, SILME_REDDEDILDI",
          imha(d4)[-1]["genel_sonuc"] == "REDDEDILDI" and d4.paths.case_dir.exists() and state_of(d4).state == "SILME_REDDEDILDI"
          and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(d4.io.asked))
    check("S4 logic: the original PDFs are intact in every deletion scenario", all(source_ok(x) for x in (d1, d2, d3, d4)))
    d5 = ready("s4w")
    bad = {"silme_tam_ad": OTHER_NAME, "silme_kod": d5.dosya, "silme_onay": "SİLMEYİ ONAYLIYORUM", "kimlik_ad": NAME}
    check("deletion needs the lawyer's full name: a wrong name -> ONAY_TEYIDI_BASARISIZ and nothing is deleted",
          code_of(resume, d5, bad) == "ONAY_TEYIDI_BASARISIZ" and d5.paths.case_dir.exists() and imha(d5) == [])
    check("deletion needs the file code: a wrong code -> ONAY_TEYIDI_BASARISIZ",
          code_of(resume, d5, {**DEL(d5), "silme_kod": "baska"}) == "ONAY_TEYIDI_BASARISIZ" and d5.paths.case_dir.exists())
    check("deletion needs the explicit phrase: anything else -> SILME_ONAYI_YOK and nothing is deleted",
          code_of(resume, d5, {**DEL(d5), "silme_onay": "evet"}) == "SILME_ONAYI_YOK" and d5.paths.case_dir.exists() and imha(d5) == [])
    # orphan: yarım silmeden durum dosyası kalmamış
    d6 = ready("s4o")
    d6.fs = FaultyFs(kill_after=12)  # vaka dizini (11 dosya + işaret) gider; ölüm ilk koşu dosyasında
    try:
        resume(d6, DEL(d6))
    except SimulatedKill:
        pass
    check("(setup) the orphan scenario starts from an interrupted deletion: BASLADI last, the case dir already gone, the run dir still there",
          imha(d6)[-1]["asama"] == "BASLADI" and not d6.paths.case_dir.exists() and d6.paths.run_dir.exists())
    d6_token = state_of(d6)["imha_token"]
    check("(setup) the run's OWN token is bound in its run dir (binding file) and equals the open token",
          R.read_imha_binding(d6.paths.run_dir, run_id=d6.run_id)["imha_token"] == d6_token and outcomes.open_imha_tokens(d6.paths.records_dir) == [d6_token])
    os.unlink(d6.paths.state_path)   # yalnız durum dosyası yitti; bildirim + bağ + işaret duruyor
    d6.fs = None
    orphan_flow = flow_for(d6, {})
    try:
        orphan_flow.continue_run(d6.run_id)
        eof = False
    except EOFError:
        eof = True
    check("H-2: the orphan restart asks the lawyer's full name FIRST (identity + separate approval); with no answer nothing is deleted and the token stays open",
          eof and d6.io.asked[:1] == ["silme_tam_ad"] and d6.paths.run_dir.exists() and outcomes.open_imha_tokens(d6.paths.records_dir) == [d6_token]
          and not any(r.get("genel_sonuc") == "TAMAMLANDI" for r in imha(d6)))
    orphan_result = resume(d6, DEL(d6))
    check("H-2: a run whose state file is gone is finished by the restart ONLY after the full approval (name, file code from the binding, phrase) -> TAMAMLANDI with ITS OWN token",
          orphan_result is not None and orphan_result.outcome == "TAMAMLANDI" and orphan_result.token == d6_token and not d6.paths.run_dir.exists()
          and {"silme_tam_ad", "silme_kod", "silme_onay"} <= set(d6.io.asked) and outcomes.open_imha_tokens(d6.paths.records_dir) == [])
    check("H-2: the closing record is the SAME token's SONUC=TAMAMLANDI appended after the restart's BASLADI (never a fresh token)",
          [r["asama"] for r in imha(d6)][-2:] == ["BASLADI", "SONUC"] and imha(d6)[-1]["genel_sonuc"] == "TAMAMLANDI")
    check("S4 logic (c)/restart: the restart planned only what was LEFT (fewer items than the first BASLADI)",
          sum(i["adet"] for i in imha(d2)[1]["kopya_turleri"]) < sum(i["adet"] for i in imha(d2)[0]["kopya_turleri"]))

    # H-2 / P2: bozuk durum + başka koşunun açık jetonu; durum+bildirim yitik; bağlanamayan jeton
    shared_p2 = TMP / "ofis_p2"
    shared_p2.mkdir()
    pa = start("p2a", office=shared_p2, dosya_kodu="DKP2A")
    new_run(pa)
    resume(pa, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    pb = start("p2b", office=shared_p2, dosya_kodu="DKP2B")
    new_run(pb)
    resume(pb, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    pb.fs = FaultyFs(kill_after=12)
    try:
        resume(pb, DEL(pb))
    except SimulatedKill:
        pass
    pb_token = state_of(pb)["imha_token"]
    check("(setup P2) another run (B) of the same office has an OPEN deletion (BASLADI last)", outcomes.open_imha_tokens(pa.paths.records_dir) == [pb_token])
    (pa.paths.run_dir / "run_state.json").write_text("{ bozuk json", encoding="utf-8")
    a_listing = sorted(os.path.join(r, f) for r, _d, fs in os.walk(pa.paths.case_dir) for f in fs)
    records_before = sorted(p.name for p in pa.paths.records_dir.iterdir())
    pa.fs = None
    code_p2 = code_of(resume, pa, DEL(pa))
    check("H-2 / P2: a CORRUPT run state STOPS: closed error, nothing deleted, NO record written (not even a refusal), the case dir is preserved, NO approval question asked",
          code_p2 == "KAYIT_SEMASI_GECERSIZ" and sorted(os.path.join(r, f) for r, _d, fs in os.walk(pa.paths.case_dir) for f in fs) == a_listing
          and sorted(p.name for p in pa.paths.records_dir.iterdir()) == records_before and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(pa.io.asked),
          f"{code_p2}")
    check("H-2 / P2: ... and ANOTHER run's open token is neither used nor closed (still the only open token, no TAMAMLANDI for it)",
          outcomes.open_imha_tokens(pa.paths.records_dir) == [pb_token] and all("genel_sonuc" not in r for r in
                                                                                 [json.loads(p.read_bytes()) for p in pa.paths.records_dir.iterdir() if p.name.startswith(f"imha_{pb_token}")])
          and any("bozuk" in t for t in pa.io.said))
    os.unlink(pa.paths.state_path)   # durum dosyası tamamen yok + bu koşunun bağı yok (hiç silme başlamadı)
    records_before = sorted(p.name for p in pa.paths.records_dir.iterdir())
    result_p2 = resume(pa, DEL(pa))
    check("H-2: a run with NO state file and NO token binding is an unbindable orphan: nothing touched, nothing recorded, NOT TAMAMLANDI, reported to the lawyer; the other run's open token stays open",
          result_p2 is None and pa.paths.case_dir.exists() and sorted(p.name for p in pa.paths.records_dir.iterdir()) == records_before
          and outcomes.open_imha_tokens(pa.paths.records_dir) == [pb_token] and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(pa.io.asked)
          and any("bağlanamıyor" in t for t in pa.io.said))
    # Silme sırası gereği bildirim ANCAK içerik gittikten sonra silinir: durum + bildirim yitikse
    # koşu dizininde yalnız bağ + işaret kalır (içerik zaten silinmiştir).
    for leftover in (pb.paths.reading_path, pb.paths.report_path):
        if leftover.exists():
            leftover.unlink()
    shutil.rmtree(pb.paths.tmp_dir, ignore_errors=True)
    os.unlink(pb.paths.state_path)
    os.unlink(pb.paths.manifest_path)
    pb.fs = None
    result_pb = resume(pb, DEL(pb))
    check("H-2: with state AND manifest lost, B restarts with its OWN token (from its binding) and only after the full approval -> TAMAMLANDI; A's tree and records are untouched",
          result_pb.outcome == "TAMAMLANDI" and result_pb.token == pb_token and not pb.paths.run_dir.exists()
          and pa.paths.case_dir.exists() and outcomes.open_imha_tokens(pa.paths.records_dir) == [])
    # iki açık jeton: yalnız KENDİ jetonu kapanır
    shared_p3 = TMP / "ofis_p3"
    shared_p3.mkdir()
    qa = start("p3a", office=shared_p3, dosya_kodu="DKP3A")
    qb = start("p3b", office=shared_p3, dosya_kodu="DKP3B")
    for q in (qa, qb):
        new_run(q)
        resume(q, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
        q.fs = FaultyFs(kill_after=12)
        try:
            resume(q, DEL(q))
        except SimulatedKill:
            pass
    qa_token, qb_token = state_of(qa)["imha_token"], state_of(qb)["imha_token"]
    check("(setup P3) two different runs each have their OWN open token", qa_token != qb_token and sorted(outcomes.open_imha_tokens(qa.paths.records_dir)) == sorted([qa_token, qb_token]))
    for q in (qa, qb):
        os.unlink(q.paths.state_path)
        q.fs = None
    # Önce jetonu SÖZLÜKSEL OLARAK BÜYÜK olan koşu yeniden başlatılır: "ilk açık jeton" seçen bir gerçekleme
    # (open_imha_tokens()[0]) yanlış (küçük) jetonu, yani DİĞER koşununkini kapatırdı - rastgele sıraya bağlı DEĞİL.
    (first_q, first_token), (second_q, second_token) = sorted(((qa, qa_token), (qb, qb_token)), key=lambda item: item[1], reverse=True)
    result_first = resume(first_q, DEL(first_q))
    check("H-2 / token binding: with TWO open tokens in the office, restarting a run closes ONLY ITS OWN token (the lexicographically LARGER one first, so a 'first open token' "
          "choice would close the other run's); the other token stays open and the other run's tree is untouched",
          result_first.token == first_token and outcomes.open_imha_tokens(first_q.paths.records_dir) == [second_token]
          and second_q.paths.run_dir.exists()
          and all("genel_sonuc" not in r for r in [json.loads(p.read_bytes()) for p in first_q.paths.records_dir.iterdir() if p.name.startswith(f"imha_{second_token}")]))
    result_second = resume(second_q, DEL(second_q))
    check("H-2 / token binding: the other run then closes its own token (first-open-token order never decides)",
          result_second.token == second_token and outcomes.open_imha_tokens(second_q.paths.records_dir) == [])
    check("the ORIGINAL PDFs are intact in every H-2 scenario", all(source_ok(x) for x in (pa, pb, qa, qb, d6)))

    # ================================================================ yeniden kontrol
    shared = TMP / "ofis_paylasilan"
    shared.mkdir()
    ra = start("ra", office=shared, dosya_kodu="DKORTAK")
    new_run(ra, base_answers(kor_son_gun="14.03.2026"))
    ra_report = hashlib.sha256(ra.paths.report_path.read_bytes()).hexdigest()
    ra_state = json.dumps(state_of(ra).data, sort_keys=True)
    rb = start("rb", office=shared, dosya_kodu="DKORTAK")
    new_run(rb)
    check("second run on the SAME file after the system result was seen -> YENIDEN_KONTROL; the first run was ILK_KONTROL",
          state_of(ra)["kontrol_turu"] == "ILK_KONTROL" and state_of(rb)["kontrol_turu"] == "YENIDEN_KONTROL")
    check("the earlier UYUSMAZLIK run was neither deleted nor overwritten by the second run",
          ra.paths.case_dir.exists() and hashlib.sha256(ra.paths.report_path.read_bytes()).hexdigest() == ra_report and json.dumps(state_of(ra).data, sort_keys=True) == ra_state)
    resume(rb, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    check("the second run's UYUMLU result is recorded as YENIDEN_KONTROL", results(rb)[-1]["kontrol_turu"] == "YENIDEN_KONTROL" and results(rb)[-1]["sonuc"] == "UYUMLU")
    rc = start("rc", office=shared, dosya_kodu="DKORTAK", answers=None)
    new_run(rc, base_answers(aday_secimi="2"))
    check("a run that stops at F3 (system result never shown) on a file whose result was seen earlier is still YENIDEN_KONTROL",
          state_of(rc)["kontrol_turu"] == "YENIDEN_KONTROL")
    rd = start("rd", office=shared, dosya_kodu="DKYENI")
    new_run(rd, base_answers(aday_secimi="2"))
    check("a run that stops at F3 on a brand-new file code is ILK_KONTROL and does NOT mark the system result as seen",
          state_of(rd)["kontrol_turu"] == "ILK_KONTROL" and R.determine_kontrol_turu(rd.paths.history_dir, "DKYENI") == "ILK_KONTROL")

    # ================================================================ kimlik
    k1 = start("k1")
    code_k1 = code_of(lambda: flow_for(k1, base_answers(kimlik_ad=OTHER_NAME)).run_new(case_id=k1.case_id, dosya_kodu=k1.dosya, source_pdf=k1.source))
    check("identity: a wrong typed name stops at F0 (KIMLIK_TEYIDI_BASARISIZ) before any run dir, case dir or backend call",
          code_k1 == "KIMLIK_TEYIDI_BASARISIZ" and not list((k1.office / "runs").iterdir()) and not [e for e in k1.events if e[0] == "backend"]
          and not (k1.cases / k1.case_id).exists(), str(code_k1))
    k2 = start("k2")
    code = code_of(lambda: flow_for(k2, base_answers(onay_ad=OTHER_NAME)).run_new(case_id=k2.case_id, dosya_kodu=k2.dosya, source_pdf=k2.source))
    k2.run_id = [p.name for p in (k2.office / "runs").iterdir()][0]
    k2.paths = R.build_run_paths(k2.office, k2.cases, k2.case_id, k2.run_id)
    check("identity: a wrong approval name -> ONAY_TEYIDI_BASARISIZ; NO approval call; the run stays KARSILASTIRMA_YAPILDI (retryable)",
          code == "ONAY_TEYIDI_BASARISIZ" and ("backend", "approve_deadline") not in k2.events and state_of(k2).state == "KARSILASTIRMA_YAPILDI")
    resume(k2, {"onay_ad": NAME, "kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    check("identity: after the correct name the approval goes through and the run proceeds to a UYUMLU result",
          ("backend", "approve_deadline") in k2.events and results(k2) and results(k2)[0]["sonuc"] == "UYUMLU")
    check("the typed name is only a confirmation: the reading record's identity is the SESSION identity",
          R.load_reading_record(k2.paths)["kimlik"]["display_name"] == NAME and R.load_reading_record(k2.paths)["kimlik"]["user_id"] == 7)

    # ================================================================ M-1: üç yeniden-hash noktasının HER BİRİ AYRI korunur
    m9 = start("m9")
    code_m9 = code_of(lambda: flow_for(m9, base_answers(onay_ad=OTHER_NAME)).run_new(case_id=m9.case_id, dosya_kodu=m9.dosya, source_pdf=m9.source))
    m9.run_id = [p.name for p in (m9.office / "runs").iterdir()][0]
    m9.paths = R.build_run_paths(m9.office, m9.cases, m9.case_id, m9.run_id)
    invalidate_facts(m9)
    resume(m9, {"onay_ad": NAME})
    check("M-1 window A (before the approval PROMPT): a verified input changed while the run waited -> GECERSIZ and the approval question is NEVER asked, no approval call, no result",
          code_m9 == "ONAY_TEYIDI_BASARISIZ" and state_of(m9).state == "GECERSIZ" and "onay_ad" not in m9.io.asked
          and ("backend", "approve_deadline") not in m9.events and results(m9) == [], f"{code_m9} {state_of(m9).state} {m9.io.asked}")
    m11 = start("m11")
    new_run(m11)
    invalidate_facts(m11)
    resume(m11, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    check("M-1 window B (before the REPORT is shown): the changed input is caught first - the report text is never displayed, 'kontrol tamamlandı' is never asked, GECERSIZ, no result",
          state_of(m11).state == "GECERSIZ" and "kontrol_tamam" not in m11.io.asked and not any("ONAYLI SONUC RAPORU" in t for t in m11.io.said)
          and results(m11) == [], f"{state_of(m11).state} {m11.io.asked}")
    m8 = start("m8")
    new_run(m8)
    m8.on_ask = lambda key: (invalidate_facts(m8), None)[1] if key == "kontrol_tamam" else None   # insan beklemesi PENCERESİNDE girdi değişir
    resume(m8, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})   # silme_simdi: kapı kaldırılırsa kırmızı SONUÇ temiz görünsün (çökme değil)
    check("M-1 window C (after the 'KONTROL TAMAMLANDI' answer): an input changed WHILE the lawyer was reading -> GECERSIZ; the answer is NOT honoured: no KONTROL_TAMAM, no result record, report stamped",
          state_of(m8).state == "GECERSIZ" and m8.io.asked.count("kontrol_tamam") == 1 and results(m8) == [] and state_of(m8)["sonuc"] is None
          and m8.paths.report_path.read_text(encoding="utf-8").startswith("*** GEÇERSİZ"), f"{state_of(m8).state} {results(m8)}")

    # ================================================================ M-2: koşu kimliği + açık koşu listesi
    ev1 = c1.events
    run_id_say = [i for i, e in enumerate(ev1) if e[0] == "say" and f"Çalışma kimliği: {c1.run_id}" in e[1] and f"--devam {c1.run_id}" in e[1]]
    check("M-2: the run id (opaque, 32 hex, not derived from the case id / file code) is printed at the START of F1, before the first backend call, with the --devam hint",
          bool(run_id_say) and run_id_say[0] < next(i for i, e in enumerate(ev1) if e[0] == "backend")
          and len(c1.run_id) == 32 and c1.case_id not in c1.run_id and c1.dosya not in c1.run_id)
    m2e = start("m2e", backend_kwargs={"fail_at": "verify_fact"})
    code_m2e = code_of(lambda: flow_for(m2e, base_answers()).run_new(case_id=m2e.case_id, dosya_kodu=m2e.dosya, source_pdf=m2e.source))
    m2e.run_id = [p.name for p in (m2e.office / "runs").iterdir()][0]
    check("M-2: the run id is repeated in the intermediate/stop outputs (UYUSMAZLIK review, UYUMLU report stage, chain-failure DURDURULDU, deletion stages)",
          sum(1 for t in c2.io.said if c2.run_id in t) >= 2 and sum(1 for t in m2e.io.said if m2e.run_id in t) >= 2
          and sum(1 for t in c1.io.said if c1.run_id in t) >= 2 and code_m2e == "BILINMEYEN_HATA")
    lst_office = TMP / "ofis_lst"
    lst_office.mkdir()
    la = start("lsta", office=lst_office, dosya_kodu="DKLSTA")
    new_run(la, base_answers(kor_son_gun="13.03.2026"))
    lb = start("lstb", office=lst_office, dosya_kodu="DKLSTB")
    new_run(lb)
    lc = start("lstc", office=lst_office, dosya_kodu="DKLSTC")
    new_run(lc)
    (lc.paths.run_dir / "run_state.json").write_text("{ bozuk", encoding="utf-8")
    ld = start("lstd", office=lst_office, dosya_kodu="DKLSTD")
    new_run(ld)
    os.unlink(ld.paths.state_path)
    stray_token = outcomes.new_imha_token()
    outcomes.write_imha_record(lst_office / "kayitlar", stray_token, outcomes.build_imha_record(asama="BASLADI", kopya_turleri=[]))
    list_flow = flow_for(la, {"devam_secimi": ""})
    found, unbound = list_flow.list_runs()
    check("M-2: list_runs shows every run with its id and a state label (UYUSMAZLIK / UYUMLU / corrupt state / missing state) and counts the unbindable open deletion record",
          dict(found) == {la.run_id: "UYUSMAZLIK_INCELEME_ACIK", lb.run_id: "UYUMLU_RAPOR_KONTROLU", lc.run_id: "DURUM_DOSYASI_BOZUK",
                          ld.run_id: "DURUM_DOSYASI_YOK"} and unbound == 1, f"{found} {unbound}")
    selection = list_flow.select_run()
    said_text = "\n".join(la.io.said)
    check("M-2: select_run prints id + state for each open run, never the case id / file code, says how many open deletion records could not be bound, and an empty answer exits changing nothing",
          selection is None and all(f"{rid}  {label}" in said_text for rid, label in found)
          and not any(x in said_text for x in (la.case_id, lb.case_id, "DKLSTA", "DKLSTB")) and "bağlanamayan açık imha kaydı sayısı: 1" in said_text
          and la.io.asked == ["devam_secimi"] and state_of(la).state == "UYUSMAZLIK_INCELEME_ACIK" and outcomes.open_imha_tokens(lst_office / "kayitlar") == [stray_token])
    resume_by_list = flow_for(la, {"devam_secimi": la.run_id, "inceleme_kapat": "hayır"}).select_run()
    check("M-2: typing a listed id continues THAT run (the UYUSMAZLIK review prompt appears; declining leaves it open)",
          resume_by_list is None and "inceleme_kapat" in la.io.asked and state_of(la).state == "UYUSMAZLIK_INCELEME_ACIK")
    out_stop, err_stop = io.StringIO(), io.StringIO()
    cm5 = start("cm5", backend_kwargs={"fail_at": "verify_fact"})
    code5 = F.main(["--office-root", str(cm5.office), "--actor-user-id", "7", "--case-id", cm5.case_id, "--dosya-kodu", cm5.dosya, "--kaynak-pdf", str(cm5.source)],
                   backend=cm5.backend, io=ScriptedIO(base_answers(), cm5.events), case_root=cm5.cases, extractor=lambda p: TEXT,
                   stdout=out_stop, stderr=err_stop, allow_system_drive=True)
    cm5_run = [p.name for p in (cm5.office / "runs").iterdir()][0]
    check("M-2 CLI: a STOPPED run prints its run id on stdout (so --devam is possible) and the id is NOT in the stderr support summary (3 fields only)",
          code5 == 1 and f"--devam {cm5_run}" in out_stop.getvalue() and cm5_run not in err_stop.getvalue() and err_stop.getvalue().count("=") == 3)

    # ================================================================ M-3: sistem sürücüsü gevşetmesi ortam değişkeniyle AÇILAMAZ
    t1_sources = [REPO_ROOT / "ui" / "office_deadline_flow.py"] + [REPO_ROOT / "ui" / "services" / f"office_flow_{n}.py" for n in
                                                                  ("records", "outcomes", "intake", "preflight", "report", "cleanup")]
    t1_text = "".join(p.read_text(encoding="utf-8") for p in t1_sources)
    check("M-3: the VERGI_OFFICE_FLOW_ALLOW_SYSTEM_DRIVE variable (and any ALLOW_SYSTEM_DRIVE env name) exists nowhere in the 7 T1 source files",
          "VERGI_OFFICE_FLOW_ALLOW_SYSTEM_DRIVE" not in t1_text and "ALLOW_SYSTEM_DRIVE" not in t1_text and len(t1_sources) == 7)
    captured = {}

    class StubFlow:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def select_run(self):
            return None

        def restore_temp(self):
            pass

    original_flow_class = F.OfficeFlow
    F.OfficeFlow = StubFlow
    os.environ["VERGI_OFFICE_FLOW_ALLOW_SYSTEM_DRIVE"] = "1"
    try:
        code_env = F.main(["--office-root", str(TMP), "--actor-user-id", "7"], backend=FakeBackend(TMP / "x", []), io=ScriptedIO({}, []),
                          case_root=TMP, stdout=io.StringIO(), stderr=io.StringIO())
        relaxed_by_env = captured.get("allow_system_drive")
        captured.clear()
        F.main(["--office-root", str(TMP), "--actor-user-id", "7"], backend=FakeBackend(TMP / "x", []), io=ScriptedIO({}, []),
               case_root=TMP, stdout=io.StringIO(), stderr=io.StringIO(), allow_system_drive=True)
        relaxed_by_param = captured.get("allow_system_drive")
        code_flag = F.main(["--office-root", str(TMP), "--actor-user-id", "7", "--allow-system-drive"], backend=FakeBackend(TMP / "x", []),
                           io=ScriptedIO({}, []), case_root=TMP, stdout=io.StringIO(), stderr=io.StringIO())
    finally:
        del os.environ["VERGI_OFFICE_FLOW_ALLOW_SYSTEM_DRIVE"]
        F.OfficeFlow = original_flow_class
    check("M-3: with the env variable set to '1' the flow is built with allow_system_drive=False (the env variable has NO effect); only the explicit test parameter relaxes it",
          code_env == 0 and relaxed_by_env is False and relaxed_by_param is True, f"{relaxed_by_env} {relaxed_by_param}")
    check("M-3: there is no command-line flag for it either (usage error exit 2)", code_flag == 2)

    # ================================================================ L-1 / L-2 / L-5 / etiketler
    l1 = start("l1")
    code_l1a = code_of(lambda: flow_for(l1, base_answers(onay_ad=OTHER_NAME)).run_new(case_id=l1.case_id, dosya_kodu=l1.dosya, source_pdf=l1.source))
    l1.run_id = [p.name for p in (l1.office / "runs").iterdir()][0]
    l1.paths = R.build_run_paths(l1.office, l1.cases, l1.case_id, l1.run_id)
    reading_bytes = l1.paths.reading_path.read_bytes()
    l1.paths.reading_path.write_bytes(reading_bytes.replace(b"2026-03-12", b"2026-03-13"))
    code_l1 = code_of(resume, l1, {"onay_ad": NAME})
    check("L-1: a reading record edited after it was recorded (hash differs from the run state) STOPS the restart (OKUMA_KAYDI_GECERSIZ): no approval, state unchanged",
          code_l1a == "ONAY_TEYIDI_BASARISIZ" and code_l1 == "OKUMA_KAYDI_GECERSIZ" and ("backend", "approve_deadline") not in l1.events
          and state_of(l1).state == "KARSILASTIRMA_YAPILDI", f"{code_l1}")
    l1b = start("l1b")
    l1b.on_ask = lambda key: (l1b.paths.reading_path.write_bytes(l1b.paths.reading_path.read_bytes().replace(b"2026-03-12", b"2026-03-13")), None)[1] \
        if key == "dogrulama_karari" else None
    l1b.run_id = None
    l1b.paths = R.build_run_paths(l1b.office, l1b.cases, l1b.case_id, "f" * 32)
    original_new_id = R.new_run_id
    R.new_run_id = lambda: "f" * 32   # yol önceden bilinsin (kanca kayıt dosyasını değiştirecek)
    try:
        code_l1b = code_of(lambda: flow_for(l1b, base_answers()).run_new(case_id=l1b.case_id, dosya_kodu=l1b.dosya, source_pdf=l1b.source))
    finally:
        R.new_run_id = original_new_id
    check("L-1: a reading record changed between the candidate step and the comparison is caught at F4 BEFORE the system result is shown",
          code_l1b == "OKUMA_KAYDI_GECERSIZ" and not any("SİSTEMİN SONUCU" in t for t in l1b.io.said), f"{code_l1b}")
    check("L-2 (L-a): the F0/F1/F2/F3/F4 output of the NEW run itself (captured from the run_new io, not the later resume io) never shows the registered full name "
          "and F0 asks for the name without printing it",
          NAME not in " ".join(c1.new_io.said + c1.new_io.prompts) and NAME not in " ".join(c2.new_io.said + c2.new_io.prompts)
          and not any("kullanıcısı" in t for t in c1.new_io.said) and "kimlik_ad" in c1.new_io.asked
          and bool(c1.new_io.said) and len(c1.new_io.prompts) >= 10)
    check("L-2: ... nor in anything printed by the later resume steps (review, deletion)",
          NAME not in " ".join(c1.io.said + c1.io.prompts) and NAME not in " ".join(c2.io.said + c2.io.prompts))
    l5 = start("l5")
    new_run(l5)
    pending_file = l5.cases / l5.case_id / "deadlines" / f"deadline_{l5.case_id}_v1.json.pending"
    check("L-5: the approval is bound to the pending the comparison saw (the flow hands its sha256 to the backend)",
          l5.backend.last_expected_pending_sha == R.sha256_hex(pending_file.read_bytes()) and len(l5.backend.last_expected_pending_sha) == 64)
    tr1 = start("tr1")
    new_run(tr1, base_answers(adli_tatil="hayır", stopping_durum="yok"))
    check("Turkish labels hayır/yok map to the SAME internal values (no/none) - the reading record schema is unchanged",
          tr1.backend.last_declarations == ("no", "none", "BEYAN-T1") and R.load_reading_record(tr1.paths)["adli_tatil"] == "no")
    tr2 = start("tr2")
    new_run(tr2, base_answers(adli_tatil="evet", stopping_durum="var"))
    tr3 = start("tr3")
    new_run(tr3, base_answers(adli_tatil="bilinmiyor", stopping_durum="bilinmiyor"))
    check("Turkish labels evet/var/bilinmiyor map to yes/present/unknown",
          tr2.backend.last_declarations == ("yes", "present", None) and tr3.backend.last_declarations == ("unknown", "unknown", None))
    tr4 = start("tr4")
    code_tr4 = code_of(lambda: flow_for(tr4, base_answers(adli_tatil="belki")).run_new(case_id=tr4.case_id, dosya_kodu=tr4.dosya, source_pdf=tr4.source))
    check("an unknown label is refused at F2 (OKUMA_KAYDI_GECERSIZ): no backend call, no reading record",
          code_tr4 == "OKUMA_KAYDI_GECERSIZ" and not [e for e in tr4.events if e[0] == "backend"]
          and not any(p.name == "okuma_kaydi.json" for p in (tr4.office / "runs").rglob("*")))

    # ================================================================ M-A: IAM denetimi HER devam yolunun ilk işi
    def fingerprint(ctx):
        out = {}
        for base in (ctx.paths.case_dir, ctx.paths.run_dir, ctx.office / "kayitlar", ctx.office / "dosya_gecmisi"):
            for dp, _d, fs_ in os.walk(base):
                for f in fs_:
                    fp_ = os.path.join(dp, f)
                    out[fp_] = hashlib.sha256(open(fp_, "rb").read()).hexdigest()
        return out

    def denied_resume(ctx, answers):
        """Backend kimliği reddeder: çıktı, kayıt, durum, dosya değişimi ve soru SIFIR olmalı."""
        before, ev_n = fingerprint(ctx), len(ctx.events)
        ctx.backend.deny = True
        try:
            code = code_of(resume, ctx, answers)
        finally:
            ctx.backend.deny = False
        new_events = ctx.events[ev_n:]
        clean = (fingerprint(ctx) == before and ctx.io.said == [] and ctx.io.asked == []
                 and not [e for e in new_events if e[0] in ("say", "ask", "backend")]
                 and new_events[:1] == [("identity", ctx.case_id)])
        return code, clean

    class KillFlow(BaseException):
        pass

    # U1: UYUŞMAZLIK incelemesini yetkisiz kullanıcı kapatamaz
    u1 = start("u1")
    new_run(u1, base_answers(kor_son_gun="13.03.2026"))
    code_u1, clean_u1 = denied_resume(u1, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "SURE_KURALI"})
    check("U1 M-A: an actor the IAM check rejects (not assigned / not lawyer / unknown) cannot see the report or close an UYUSMAZLIK review: YETKI_YOK, NO screen output, NO question, "
          "NO test result, state and every file unchanged, the identity call is the FIRST event",
          code_u1 == "YETKI_YOK" and clean_u1 and results(u1) == [] and state_of(u1).state == "UYUSMAZLIK_INCELEME_ACIK", f"{code_u1} {clean_u1}")
    n_u1 = len(u1.events)
    resume(u1, {"inceleme_kapat": "hayır"})
    check("U1: the SAME call with an authorised identity starts with the identity check and then proceeds (report shown, review prompt asked)",
          u1.events[n_u1] == ("identity", u1.case_id) and "inceleme_kapat" in u1.io.asked and any("UYUSMAZLIK" in t for t in u1.io.said))
    # U2: UYUMLU
    u2 = start("u2")
    new_run(u2)
    code_u2, clean_u2 = denied_resume(u2, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    check("U2 M-A: an unauthorised actor cannot confirm 'KONTROL TAMAMLANDI' or even see the report of a UYUMLU run: YETKI_YOK, no output, no UYUMLU result record, state unchanged",
          code_u2 == "YETKI_YOK" and clean_u2 and results(u2) == [] and state_of(u2).state == "UYUMLU_RAPOR_KONTROLU" and "kontrol_tamam" not in u2.io.asked,
          f"{code_u2} {clean_u2}")
    n_u2 = len(u2.events)
    resume(u2, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    check("U2: with an authorised identity the first event is the identity check and the result is written", u2.events[n_u2] == ("identity", u2.case_id) and len(results(u2)) == 1)
    # U3: reddedilen silme planı da kimlik ister
    u3 = start("u3")
    new_run(u3)
    resume(u3, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    (u3.paths.case_dir / "documents" / intake.DOC_ID / "baska_muvekkil.pdf").write_bytes(b"BURO")
    code_u3, clean_u3 = denied_resume(u3, {})
    check("U3 M-A: a refused deletion plan does NOT write the REDDEDILDI imha record or the SILME_REDDEDILDI state for an unauthorised actor (identity is checked BEFORE the plan): "
          "no record, no state change, no output",
          code_u3 == "YETKI_YOK" and clean_u3 and imha(u3) == [] and state_of(u3).state == "SILME_ONAYI_BEKLIYOR", f"{code_u3} {clean_u3}")
    n_u3 = len(u3.events)
    resume(u3, {})
    check("U3: authorised: the identity call comes first, then the refusal (no name question while the plan is refused, still SILME_REDDEDILDI)",
          u3.events[n_u3] == ("identity", u3.case_id) and state_of(u3).state == "SILME_REDDEDILDI" and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(u3.io.asked))
    # U4: zincir ortasında kalmış koşu yetkisiz DURDURULDU yapılamaz
    u4 = start("u4")
    u4.on_ask = lambda key: (_ for _ in ()).throw(KillFlow()) if key == "dogrulama_karari" else None
    try:
        flow_for(u4, base_answers()).run_new(case_id=u4.case_id, dosya_kodu=u4.dosya, source_pdf=u4.source)
    except KillFlow:
        pass
    u4.on_ask = None
    u4.run_id = [p_.name for p_ in (u4.office / "runs").iterdir()][0]
    u4.paths = R.build_run_paths(u4.office, u4.cases, u4.case_id, u4.run_id)
    check("(setup U4) a hard stop left the run mid-chain (SISTEM_ZINCIRI)", state_of(u4).state == "SISTEM_ZINCIRI")
    code_u4, clean_u4 = denied_resume(u4, {})
    check("U4 M-A: an unauthorised actor cannot turn a mid-chain run into DURDURULDU: YETKI_YOK, state still SISTEM_ZINCIRI, no output",
          code_u4 == "YETKI_YOK" and clean_u4 and state_of(u4).state == "SISTEM_ZINCIRI", f"{code_u4} {clean_u4}")
    n_u4 = len(u4.events)
    resume(u4, {})
    check("U4: authorised: identity first, then DURDURULDU", u4.events[n_u4] == ("identity", u4.case_id) and state_of(u4).state == "DURDURULDU")
    # KARSILASTIRMA_YAPILDI (onay adı yanlış) yolu
    u5 = start("u5")
    code5 = code_of(lambda: flow_for(u5, base_answers(onay_ad=OTHER_NAME)).run_new(case_id=u5.case_id, dosya_kodu=u5.dosya, source_pdf=u5.source))
    u5.run_id = [p_.name for p_ in (u5.office / "runs").iterdir()][0]
    u5.paths = R.build_run_paths(u5.office, u5.cases, u5.case_id, u5.run_id)
    code_u5, clean_u5 = denied_resume(u5, {"onay_ad": NAME})
    check("U5 M-A: the KARSILASTIRMA_YAPILDI continue path (approval retry) also stops at the identity check: no approval call, no output",
          code5 == "ONAY_TEYIDI_BASARISIZ" and code_u5 == "YETKI_YOK" and clean_u5 and state_of(u5).state == "KARSILASTIRMA_YAPILDI"
          and ("backend", "approve_deadline") not in u5.events)
    # yetim (durum dosyası yok) yeniden başlatma
    u6 = start("u6")
    new_run(u6)
    resume(u6, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    u6.fs = FaultyFs(kill_after=12)
    try:
        resume(u6, DEL(u6))
    except SimulatedKill:
        pass
    u6.fs = None
    os.unlink(u6.paths.state_path)
    code_u6, clean_u6 = denied_resume(u6, {})
    check("U6 M-A: the state-file-lost (orphan) restart also checks the identity FIRST: YETKI_YOK, nothing recreated (no state file), no record, no output",
          code_u6 == "YETKI_YOK" and clean_u6 and not u6.paths.state_path.exists(), f"{code_u6} {clean_u6}")
    n_u6 = len(u6.events)
    res6 = resume(u6, DEL(u6))
    check("U6: authorised: identity first, full approval, TAMAMLANDI", u6.events[n_u6] == ("identity", u6.case_id) and res6.outcome == "TAMAMLANDI")
    # delete_run doğrudan
    u7 = start("u7")
    new_run(u7)
    resume(u7, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    before7 = fingerprint(u7)
    flow7 = flow_for(u7, {})
    u7.backend.deny = True
    code7 = code_of(flow7.delete_run, u7.paths, state_of(u7))
    u7.backend.deny = False
    check("U7 M-A: delete_run called directly checks the identity before the plan/refusal/token/record work", code7 == "YETKI_YOK" and fingerprint(u7) == before7 and u7.io.said == [])
    # kimlik sayacı: her yol en az bir kimlik çağrısı yaptı
    check("M-A: every continue path made at least one identity call (backend call counter)",
          all(c.backend.identity_calls >= 2 for c in (u1, u2, u3, u4, u5, u6, u7)))

    # ================================================================ TF-1: yetki HER kayıt/durum yazımından HEMEN önce yeniden kontrol edilir
    # Senaryo: `continue_run` başındaki kimlik GEÇER; insan beklemesi sürerken atama geri alınır; yazım noktasında RED.
    def flip_at(ctx, key_name, snap):
        """`key_name` sorulduğunda (insan beklemesi sürüyor, yazım henüz yok) atamayı geri al ve o anki
        disk/ekran anlık görüntüsünü al: sonradan fark = geri alma SONRASI yazılan her şey."""
        def hook(key):
            if key == key_name:
                snap["fp"], snap["said"] = fingerprint(ctx), len(ctx.io.said)
                ctx.backend.deny = True
            return None
        return hook

    def records_of(ctx, prefix):
        return [p.name for p in kayitlar(ctx) if p.name.startswith(prefix)]

    def state_name(ctx):
        try:
            return state_of(ctx).state
        except R.OfficeFlowError:
            return "(durum dosyası yok)"

    def first_result(ctx):
        found = results(ctx)
        return found[0].get("sonuc") if found else None

    def code_safe(fn, *args):
        """Hata kodu; mutasyonlu akışta beklenmeyen soru (EOFError) testi çökertmesin diye adlandırılmış değere çevrilir."""
        try:
            return code_of(fn, *args)
        except EOFError:
            return "EOFError(beklenmeyen soru)"

    def tolerant_resume(ctx, answers):
        """Kurtarma adımı: bozuk (mutasyonlu) bir akışta test çökmek yerine adlandırılmış FAIL ile sürsün."""
        try:
            return resume(ctx, answers)
        except (R.OfficeFlowError, EOFError):
            return None

    # W1: UYUMLU, 'KONTROL TAMAMLANDI' beyanından sonra yetki reddedilir
    t1 = start("tf1a")
    new_run(t1)
    snap_t1 = {}
    t1.on_ask = flip_at(t1, "kontrol_tamam", snap_t1)
    code_t1 = code_safe(resume, t1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    t1.backend.deny, t1.on_ask = False, None
    print(f"INFO TF-1 W1 disk after the refusal: state={state_name(t1)}, result_records={len(records_of(t1, 'test_sonucu_'))}, "
          f"imha_records={len(records_of(t1, 'imha_'))}")
    check("TF-1 W1: the identity passes at continue_run start, the assignment is revoked while 'KONTROL TAMAMLANDI' is awaited -> YETKI_YOK; "
          "state stays UYUMLU_RAPOR_KONTROLU (NOT KONTROL_TAMAM), NO result/imha record, NO file change and NO screen output after the confirmation",
          code_t1 == "YETKI_YOK" and results(t1) == [] and imha(t1) == [] and state_name(t1) == "UYUMLU_RAPOR_KONTROLU"
          and fingerprint(t1) == snap_t1["fp"] and len(t1.io.said) == snap_t1["said"], f"{code_t1}")
    tolerant_resume(t1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    check("TF-1 W1 recovery: the authorised --devam completes from the SAME state: exactly ONE UYUMLU result record (no duplicate), state SILME_ONAYI_BEKLIYOR",
          len(records_of(t1, "test_sonucu_")) == 1 and first_result(t1) == "UYUMLU" and state_name(t1) == "SILME_ONAYI_BEKLIYOR")

    # W2: UYUŞMAZLIK, kategori yanıtından sonra yetki reddedilir
    t2 = start("tf1b")
    new_run(t2, base_answers(kor_son_gun="13.03.2026"))
    snap_t2 = {}
    t2.on_ask = flip_at(t2, "kategori", snap_t2)
    code_t2 = code_safe(resume, t2, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "SURE_KURALI", "silme_simdi": "hayır"})
    t2.backend.deny, t2.on_ask = False, None
    print(f"INFO TF-1 W2 disk after the refusal: state={state_name(t2)}, result_records={len(records_of(t2, 'test_sonucu_'))}")
    check("TF-1 W2: revoked while the category is awaited -> YETKI_YOK; state stays UYUSMAZLIK_INCELEME_ACIK (NOT INCELEME_KAPALI), no result record, no file change, no screen output after the answer",
          code_t2 == "YETKI_YOK" and results(t2) == [] and state_name(t2) == "UYUSMAZLIK_INCELEME_ACIK"
          and fingerprint(t2) == snap_t2["fp"] and len(t2.io.said) == snap_t2["said"], f"{code_t2}")
    tolerant_resume(t2, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "SURE_KURALI", "silme_simdi": "hayır"})
    check("TF-1 W2 recovery: the authorised --devam closes the review: exactly ONE UYUSMAZLIK result record, state SILME_ONAYI_BEKLIYOR",
          len(records_of(t2, "test_sonucu_")) == 1 and first_result(t2) == "UYUSMAZLIK" and state_name(t2) == "SILME_ONAYI_BEKLIYOR")

    # W3: `continue_run` tekrar yolu (durum KONTROL_TAMAM, kayıt yazım penceresinde kalmış): `_write_result_once` tek geçit
    class WindowCrash(BaseException):
        pass

    t3 = start("tf1c")
    new_run(t3)
    flow_t3 = flow_for(t3, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})

    def crash_before_write(paths_, state_):
        raise WindowCrash()

    flow_t3._write_result_once = crash_before_write
    try:
        flow_t3.continue_run(t3.run_id)
    except WindowCrash:
        pass
    check("(setup TF-1 W3) the write-window crash left state KONTROL_TAMAM with NO result record",
          state_name(t3) == "KONTROL_TAMAM" and results(t3) == [])
    before_t3 = fingerprint(t3)
    t3.backend.deny_from_call = t3.backend.identity_calls + 2   # 1. çağrı (continue_run başı) geçer; 2.si (`_write_result_once`) reddedilir
    code_t3 = code_safe(resume, t3, DEL(t3))
    t3.backend.deny_from_call = None
    print(f"INFO TF-1 W3 disk after the refusal: state={state_name(t3)}, result_records={len(records_of(t3, 'test_sonucu_'))}")
    check("TF-1 W3: the first identity check passes, the second (inside _write_result_once, retry path) is refused -> YETKI_YOK; state stays KONTROL_TAMAM, NO result record, NO file change, deletion not asked",
          code_t3 == "YETKI_YOK" and results(t3) == [] and state_name(t3) == "KONTROL_TAMAM" and fingerprint(t3) == before_t3
          and "silme_tam_ad" not in t3.io.asked, f"{code_t3}")
    res_t3 = tolerant_resume(t3, DEL(t3))
    check("TF-1 W3 recovery: the authorised --devam writes exactly ONE result record (no duplicate), then the deletion completes (TAMAMLANDI)",
          len(records_of(t3, "test_sonucu_")) == 1 and first_result(t3) == "UYUMLU" and getattr(res_t3, "outcome", None) == "TAMAMLANDI")

    # W4: bayat kimlik — inceleme beklemesinde (silme_simdi sorusu) atama geri alınır; delete_run taze kimlik almalı
    t4 = start("tf1d")
    new_run(t4)
    snap_t4 = {}
    t4.on_ask = flip_at(t4, "silme_simdi", snap_t4)
    code_t4 = code_safe(resume, t4, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "evet", **DEL(t4)})
    t4.backend.deny, t4.on_ask = False, None
    check("TF-1 W4: revoked while 'silme_simdi' is awaited (the identity snapshot from continue_run is STALE) -> YETKI_YOK before the plan/refusal/name question: "
          "no imha record, no binding, nothing deleted, state SILME_ONAYI_BEKLIYOR; the result record written BEFORE the revocation stays (exactly one)",
          code_t4 == "YETKI_YOK" and imha(t4) == [] and len(records_of(t4, "test_sonucu_")) == 1 and state_name(t4) == "SILME_ONAYI_BEKLIYOR"
          and fingerprint(t4) == snap_t4["fp"] and t4.paths.case_dir.exists() and "silme_tam_ad" not in t4.io.asked
          and R.read_imha_binding(t4.paths.run_dir, run_id=t4.run_id) is None, f"{code_t4}")
    res_t4 = tolerant_resume(t4, DEL(t4))
    check("TF-1 W4 recovery: the authorised --devam deletes (TAMAMLANDI) with BASLADI+SONUC exactly once and still ONE result record",
          getattr(res_t4, "outcome", None) == "TAMAMLANDI" and [r["asama"] for r in imha(t4)] == ["BASLADI", "SONUC"] and len(records_of(t4, "test_sonucu_")) == 1)

    # W5/W6: son insan onayından ('SİLMEYİ ONAYLIYORUM') sonra reddedilirse silme HİÇ başlamaz
    t5 = ready("tf1e")
    snap_t5 = {}
    t5.on_ask = flip_at(t5, "silme_onay", snap_t5)
    code_t5 = code_safe(resume, t5, DEL(t5))
    t5.backend.deny, t5.on_ask = False, None
    print(f"INFO TF-1 W5 disk after the refusal: state={state_name(t5)}, imha_records={len(imha(t5))}, case_dir_exists={t5.paths.case_dir.exists()}")
    check("TF-1 W5/W6: revoked after the last confirmation, BEFORE the deletion -> YETKI_YOK; deletion NEVER started: no BASLADI/imha record, no binding, "
          "every case/run file is still on disk (byte-identical to the moment of the revocation), state SILME_ONAYI_BEKLIYOR",
          code_t5 == "YETKI_YOK" and imha(t5) == [] and R.read_imha_binding(t5.paths.run_dir, run_id=t5.run_id) is None
          and fingerprint(t5) == snap_t5["fp"] and t5.paths.case_dir.exists() and state_name(t5) == "SILME_ONAYI_BEKLIYOR", f"{code_t5}")
    res_t5 = tolerant_resume(t5, DEL(t5))
    check("TF-1 W5/W6 recovery: the authorised --devam performs the deletion: TAMAMLANDI, BASLADI then SONUC exactly once",
          getattr(res_t5, "outcome", None) == "TAMAMLANDI" and [r["asama"] for r in imha(t5)] == ["BASLADI", "SONUC"] and not t5.paths.case_dir.exists())

    # Bilinçli istisna: silme BAŞLADIKTAN sonra yetki geri alınsa da KAPANIŞ kaydı (SONUC) yazılır
    class RevokeDuringDeleteFs(cleanup.FsOps):
        def __init__(self, backend):
            self.backend = backend

        def unlink(self, path):
            self.backend.deny = True     # silme sürerken atama geri alındı
            super().unlink(path)

    t6 = ready("tf1f")
    t6.fs = RevokeDuringDeleteFs(t6.backend)
    res_t6 = tolerant_resume(t6, DEL(t6))
    revoked_during = t6.backend.deny
    t6.backend.deny, t6.fs = False, None
    check("TF-1 exception: an assignment revoked AFTER the deletion started does NOT block the closing SONUC record (a deletion without its record is worse): "
          "BASLADI + SONUC=TAMAMLANDI are both written",
          revoked_during and getattr(res_t6, "outcome", None) == "TAMAMLANDI" and [r["asama"] for r in imha(t6)] == ["BASLADI", "SONUC"]
          and imha(t6)[-1]["genel_sonuc"] == "TAMAMLANDI" and not t6.paths.case_dir.exists())

    # delete_run'a DIŞARIDAN verilen (bayat) kimlik parametresi yetki denetimini atlatamaz
    t7 = ready("tf1g")
    before_t7 = fingerprint(t7)
    stale_identity = R.IdentitySnapshot(7, NAME, "kullanici", "makine", "2026-01-01T00:00:00+00:00")
    flow_t7 = flow_for(t7, {})
    t7.backend.deny = True
    code_t7 = code_safe(flow_t7.delete_run, t7.paths, state_of(t7), stale_identity)
    t7.backend.deny = False
    check("TF-1 W4: a stale identity PASSED to delete_run as a parameter does not bypass the live check (YETKI_YOK, no output, no change)",
          code_t7 == "YETKI_YOK" and fingerprint(t7) == before_t7 and t7.io.said == [] and imha(t7) == [], f"{code_t7}")

    # L-1 (W7): onay ADI beklenirken atama geri alınırsa durum dosyasına `onay_kimlik` YAZILMAZ (bağımsız incelemenin L-1 bulgusu)
    def onay_of(ctx):
        try:
            return state_of(ctx).get("onay_kimlik")
        except R.OfficeFlowError:
            return "(durum dosyası yok)"

    def run_new_fixed_id(ctx, answers, run_id):
        """run_new, koşu kimliği ve yolları ÖNCEDEN bilinerek: red durumunda da disk/durum okunabilsin."""
        ctx.run_id = run_id
        ctx.paths = R.build_run_paths(ctx.office, ctx.cases, ctx.case_id, run_id)
        WATCH["path"] = os.path.normcase(os.path.realpath(str(ctx.source)))
        del SOURCE_EVENTS[:]
        original = R.new_run_id
        R.new_run_id = lambda: run_id
        try:
            return code_safe(lambda: flow_for(ctx, answers).run_new(case_id=ctx.case_id, dosya_kodu=ctx.dosya, source_pdf=ctx.source))
        finally:
            R.new_run_id = original

    ONAY_KEYS = {"user_id", "display_name", "windows_user", "machine_name", "db_time", "ek_teyit_eslesti"}
    w7 = start("w7a")
    snap_w7 = {}
    w7.on_ask = flip_at(w7, "onay_ad", snap_w7)
    code_w7 = run_new_fixed_id(w7, base_answers(), "e" * 32)
    w7.backend.deny, w7.on_ask = False, None
    print(f"INFO L-1 W7 disk after the refusal: state={state_name(w7)}, onay_kimlik={onay_of(w7)!r}, result_records={len(records_of(w7, 'test_sonucu_'))}")
    check("L-1 W7: the identity passes at the start, the assignment is revoked while the approval NAME is awaited -> exactly YETKI_YOK; the run state holds NO 'onay_kimlik' "
          "(a revoked lawyer's approval mark is never written), the state stays KARSILASTIRMA_YAPILDI, NO approval call, NO result/imha record, NO file change, NO output after the answer",
          code_w7 == "YETKI_YOK" and onay_of(w7) is None and state_name(w7) == "KARSILASTIRMA_YAPILDI"
          and ("backend", "approve_deadline") not in w7.events and results(w7) == [] and imha(w7) == []
          and fingerprint(w7) == snap_w7["fp"] and len(w7.io.said) == snap_w7["said"], f"{code_w7} {onay_of(w7)!r} {state_name(w7)}")
    tolerant_resume(w7, {"onay_ad": NAME, "kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    onay_w7 = onay_of(w7)
    check("L-1 W7 recovery: the re-assigned lawyer's --devam completes the approval EXACTLY ONCE (one approve_deadline call), writes 'onay_kimlik' (session identity, exact key set, "
          "ek_teyit_eslesti True), state SILME_ONAYI_BEKLIYOR, exactly ONE UYUMLU result record",
          sum(1 for e in w7.events if e == ("backend", "approve_deadline")) == 1 and isinstance(onay_w7, dict) and set(onay_w7) == ONAY_KEYS
          and onay_w7["user_id"] == 7 and onay_w7["display_name"] == NAME and onay_w7["ek_teyit_eslesti"] is True
          and state_name(w7) == "SILME_ONAYI_BEKLIYOR" and len(results(w7)) == 1 and first_result(w7) == "UYUMLU", f"{onay_w7!r} {state_name(w7)}")

    # yetki SÜRÜYORSA: davranış aynı, kayıt TAZE kimlikten gelir (ad beklemesinden SONRA alınan anlık görüntü)
    w8 = start("w8a")
    w8.backend.db_time_by_call = lambda n: f"2026-11-18T10:00:{n:02d}+00:00"
    mark_w8 = {}

    def mark_onay(key):
        if key == "onay_ad":
            mark_w8["idx"], mark_w8["calls"] = len(w8.events), w8.backend.identity_calls
        return None

    w8.on_ask = mark_onay
    new_run(w8)
    w8.on_ask = None
    onay_w8 = onay_of(w8)
    after_w8 = w8.events[mark_w8["idx"]:]
    first_id_w8 = next((i for i, e in enumerate(after_w8) if e[0] == "identity"), None)
    approve_w8 = next((i for i, e in enumerate(after_w8) if e == ("backend", "approve_deadline")), None)
    check("L-1 W7 (authority kept): a live identity query runs AFTER the approval-name question and BEFORE the approval call; behaviour is otherwise unchanged "
          "(one approval, state UYUMLU_RAPOR_KONTROLU, exact key set, no typed text)",
          first_id_w8 is not None and approve_w8 is not None and first_id_w8 < approve_w8
          and sum(1 for e in w8.events if e == ("backend", "approve_deadline")) == 1 and state_name(w8) == "UYUMLU_RAPOR_KONTROLU"
          and isinstance(onay_w8, dict) and set(onay_w8) == ONAY_KEYS and onay_w8["ek_teyit_eslesti"] is True, f"{first_id_w8} {approve_w8} {onay_w8!r}")
    fresh_time = f"2026-11-18T10:00:{mark_w8['calls'] + 1:02d}+00:00"
    stale_time = f"2026-11-18T10:00:{mark_w8['calls']:02d}+00:00"
    check("L-1 W7 (fresh identity): 'onay_kimlik.db_time' is the snapshot taken by the FIRST identity call after the name question - NOT the snapshot passed in from earlier",
          isinstance(onay_w8, dict) and onay_w8["db_time"] == fresh_time and onay_w8["db_time"] != stale_time, f"{onay_w8!r} fresh={fresh_time} stale={stale_time}")
    check("L-1 W7 (same user): the approval mark and the reading record (fresh W10 identity, O-5 D3) carry the SAME user_id and registered name - the name confirmation and the fresh query bind to one user",
          isinstance(onay_w8, dict) and onay_w8["user_id"] == R.load_reading_record(w8.paths)["kimlik"]["user_id"] == 7
          and onay_w8["display_name"] == R.load_reading_record(w8.paths)["kimlik"]["display_name"] == NAME)

    # ================================================================ O-5: yeni koşunun ERKEN yazımlarında canlı yetki (W8-W11) + D2 + D3
    # Senaryo: F0 kimliği GEÇER; insan beklemesi sürerken atama geri alınır; o noktanın ilk yazımından ÖNCE RED.
    # D2: run_new'deki YETKI_YOK reddinde durum dosyasına HİÇBİR ŞEY yazılmaz (DURDURULDU yok, ekran çıktısı yok).
    def o5_tree(ctx):
        """Ofis ve vaka köklerinin TAMAMI (dosya -> sha256, dizin -> '<dir>'): yeni boş dizin de fark sayılır."""
        out = {}
        for base in (ctx.office, ctx.cases):
            for dp, ds, fs_ in os.walk(base):
                for d_ in ds:
                    out[os.path.join(dp, d_)] = "<dir>"
                for f in fs_:
                    fp_ = os.path.join(dp, f)
                    with open(fp_, "rb") as fh:
                        out[fp_] = hashlib.sha256(fh.read()).hexdigest()
        return out

    def o5_flip(ctx, key_name, snap):
        """`key_name` sorulduğunda (insan beklemesi, yazım yok) disk/ekran/olay anlık görüntüsü + atama geri alınır."""
        def hook(key):
            if key == key_name:
                snap["tree"], snap["said"], snap["events"] = o5_tree(ctx), len(ctx.io.said), len(ctx.events)
                ctx.backend.deny = True
            return None
        return hook

    def o5_denied_new(ctx, key_name, answers, run_id):
        """run_new: `key_name` beklenirken geri alma. Dönüş: (kod, anlık görüntü, sonraki olaylar)."""
        snap = {}
        ctx.on_ask = o5_flip(ctx, key_name, snap)
        try:
            code = run_new_fixed_id(ctx, answers, run_id)
        finally:
            ctx.backend.deny, ctx.on_ask = False, None
        return code, snap, ctx.events[snap.get("events", len(ctx.events)):]

    def o5_clean(ctx, snap, after_events):
        """Red anından sonra: disk bayt-bayt aynı, ekran çıktısı yok, tek olay = reddeden canlı kimlik sorgusu."""
        return (bool(snap) and o5_tree(ctx) == snap["tree"] and len(ctx.io.said) == snap["said"]
                and after_events == [("identity", ctx.case_id)])

    def o5_recover(ctx):
        """Geri atanan avukat: 1. --devam koşuyu DURDURULDU yapar, 2. --devam (tam onayla) siler."""
        first = tolerant_resume(ctx, {})
        halted = state_name(ctx)
        second = tolerant_resume(ctx, DEL(ctx))
        return (first is None and halted == "DURDURULDU" and getattr(second, "outcome", None) == "TAMAMLANDI"
                and not ctx.paths.run_dir.exists() and not ctx.paths.case_dir.exists()), halted, getattr(second, "outcome", None)

    # W8: ad teyidi beklenirken geri alma -> koşu dizini/durum/bildirim/TEMP yok, koşu kimliği basılmaz
    o5_w8 = start("o5w8")
    code_o5_w8, snap_o5_w8, after_o5_w8 = o5_denied_new(o5_w8, "kimlik_ad", base_answers(), "8" * 32)
    check("O-5 W8: the F0 identity passes, the assignment is revoked while the typed name is awaited -> exactly YETKI_YOK; NO run dir (runs/ empty), NO case dir, "
          "NO state/manifest/TEMP dir, the run id is NEVER announced, NO screen output after the answer, the only event after the answer is the refusing live identity query",
          code_o5_w8 == "YETKI_YOK" and o5_clean(o5_w8, snap_o5_w8, after_o5_w8) and not list((o5_w8.office / "runs").iterdir())
          and not (o5_w8.cases / o5_w8.case_id).exists() and o5_w8.flow.run_id is None and "sayfa_sayisi" not in o5_w8.io.asked,
          f"{code_o5_w8} {after_o5_w8} {o5_w8.flow.run_id}")
    o5_w8_rerun = code_safe(lambda: new_run(o5_w8))
    check("O-5 W8 recovery: nothing was left to resume; the re-assigned lawyer simply starts a new run, which completes normally (UYUMLU_RAPOR_KONTROLU)",
          o5_w8_rerun is None and state_name(o5_w8) == "UYUMLU_RAPOR_KONTROLU" and len(list((o5_w8.office / "runs").iterdir())) == 1, f"{o5_w8_rerun}")

    # W9: kaynak/sayfa/vergi türü beklenirken geri alma -> belge kopyası vaka klasörüne YAZILMAZ
    o5_w9 = start("o5w9")
    code_o5_w9, snap_o5_w9, after_o5_w9 = o5_denied_new(o5_w9, "vergi_turleri", base_answers(), "9" * 32)
    print(f"INFO O-5 W9 disk after the refusal: state={state_name(o5_w9)}, case_dir_exists={o5_w9.paths.case_dir.exists()}")
    check("O-5 W9: revoked while the tax types are awaited -> exactly YETKI_YOK; the client document copy and the extracted text are NOT written (no case dir), "
          "D2: the run state stays HAZIRLANIYOR (NOT DURDURULDU), every file byte-identical, NO screen output after the answer, no F2 question asked",
          code_o5_w9 == "YETKI_YOK" and o5_clean(o5_w9, snap_o5_w9, after_o5_w9) and not o5_w9.paths.case_dir.exists()
          and state_name(o5_w9) == "HAZIRLANIYOR" and "tebligat_tarihi" not in o5_w9.io.asked, f"{code_o5_w9} {state_name(o5_w9)} {after_o5_w9}")
    ok_o5_w9, halted_o5_w9, out_o5_w9 = o5_recover(o5_w9)
    check("O-5 W9 recovery: the re-assigned lawyer's --devam turns the run into DURDURULDU, the next --devam deletes it with the full approval (TAMAMLANDI)",
          ok_o5_w9 and source_ok(o5_w9), f"{halted_o5_w9} {out_o5_w9}")

    # W10: altı F2 sorusundan sonra geri alma -> okuma kaydı YAZILMAZ
    o5_w10 = start("o5w10")
    code_o5_w10, snap_o5_w10, after_o5_w10 = o5_denied_new(o5_w10, "stopping_ref", base_answers(), "a" * 32)
    print(f"INFO O-5 W10 disk after the refusal: state={state_name(o5_w10)}, reading_record_exists={o5_w10.paths.reading_path.exists()}")
    check("O-5 W10: revoked while the last F2 answer is awaited -> exactly YETKI_YOK; NO reading record, D2: state stays HAZIRLANIYOR (no okuma_sha, NOT DURDURULDU), "
          "every file byte-identical, NO screen output after the answer (no candidate list), the candidate question is never asked",
          code_o5_w10 == "YETKI_YOK" and o5_clean(o5_w10, snap_o5_w10, after_o5_w10) and not o5_w10.paths.reading_path.exists()
          and state_name(o5_w10) == "HAZIRLANIYOR" and "aday_secimi" not in o5_w10.io.asked and o5_w10.paths.case_dir.exists(),
          f"{code_o5_w10} {state_name(o5_w10)} {after_o5_w10}")
    ok_o5_w10, halted_o5_w10, out_o5_w10 = o5_recover(o5_w10)
    check("O-5 W10 recovery: --devam -> DURDURULDU, then the lawyer-approved deletion removes the client copy (TAMAMLANDI)",
          ok_o5_w10 and source_ok(o5_w10), f"{halted_o5_w10} {out_o5_w10}")

    # W11 (a): uyuşmazlık dalı - aday seçimi beklenirken geri alma -> uyuşmazlık durumu/raporu YAZILMAZ
    o5_w11a = start("o5w11a")
    code_o5_w11a, snap_o5_w11a, after_o5_w11a = o5_denied_new(o5_w11a, "aday_secimi", base_answers(aday_secimi="2"), "b" * 32)
    check("O-5 W11 (mismatch branch): revoked while the candidate choice is awaited -> exactly YETKI_YOK; NO mismatch report, D2: state stays OKUMA_KAYITLI "
          "(NOT UYUSMAZLIK_INCELEME_ACIK, NOT DURDURULDU), NO mismatch message on screen, every file byte-identical, no backend call",
          code_o5_w11a == "YETKI_YOK" and o5_clean(o5_w11a, snap_o5_w11a, after_o5_w11a) and not o5_w11a.paths.report_path.exists()
          and state_name(o5_w11a) == "OKUMA_KAYITLI" and not any("UYUŞMUYOR" in t for t in o5_w11a.io.said)
          and not [e for e in o5_w11a.events if e[0] == "backend"], f"{code_o5_w11a} {state_name(o5_w11a)} {after_o5_w11a}")
    ok_o5_w11a, halted_o5_w11a, out_o5_w11a = o5_recover(o5_w11a)
    check("O-5 W11 (mismatch branch) recovery: --devam -> DURDURULDU, then deletion TAMAMLANDI", ok_o5_w11a, f"{halted_o5_w11a} {out_o5_w11a}")

    # W11 (b): uyuşma dalı - elle girdi dosyası YAZILMAZ, SISTEM_ZINCIRI'ne geçilmez
    o5_w11b = start("o5w11b")
    code_o5_w11b, snap_o5_w11b, after_o5_w11b = o5_denied_new(o5_w11b, "aday_secimi", base_answers(), "c" * 32)
    check("O-5 W11 (match branch): revoked while the candidate choice is awaited -> exactly YETKI_YOK; NO manual_input file, D2: state stays OKUMA_KAYITLI "
          "(NOT SISTEM_ZINCIRI, NOT DURDURULDU), every file byte-identical, no screen output, no backend call",
          code_o5_w11b == "YETKI_YOK" and o5_clean(o5_w11b, snap_o5_w11b, after_o5_w11b)
          and not (o5_w11b.paths.case_dir / "documents" / intake.DOC_ID / "manual_input").exists()
          and state_name(o5_w11b) == "OKUMA_KAYITLI" and not [e for e in o5_w11b.events if e[0] == "backend"],
          f"{code_o5_w11b} {state_name(o5_w11b)} {after_o5_w11b}")
    ok_o5_w11b, halted_o5_w11b, out_o5_w11b = o5_recover(o5_w11b)
    check("O-5 W11 (match branch) recovery: --devam -> DURDURULDU, then deletion TAMAMLANDI", ok_o5_w11b, f"{halted_o5_w11b} {out_o5_w11b}")

    # D2 (zincir adımı): `dogrulama_karari` beklenirken geri alma -> verify_fact facade'i CaseAccessDeniedError ile reddeder
    check("(setup O-5 D2) the facade's CaseAccessDeniedError maps to exactly YETKI_YOK (the D2 distinction does not depend on one class)",
          outcomes.error_code_for(CaseAccessDeniedError("no_assignment")) == "YETKI_YOK" and outcomes.error_code_for(R.OfficeFlowError("YETKI_YOK")) == "YETKI_YOK")
    o5_ch = start("o5ch")
    o5_ch.backend.deny_chain_step = "verify_fact"
    code_o5_ch, snap_o5_ch, after_o5_ch = o5_denied_new(o5_ch, "dogrulama_karari", base_answers(), "d" * 32)
    check("O-5 D2 (chain step): revoked while the verification decision is awaited -> the verify_fact facade refuses (CaseAccessDeniedError) -> exactly YETKI_YOK; "
          "the state stays SISTEM_ZINCIRI (DURDURULDU is NOT written), every file byte-identical, NO screen output (no run-id announce) after the answer",
          code_o5_ch == "YETKI_YOK" and bool(snap_o5_ch) and after_o5_ch == [("backend", "verify_fact")] and o5_tree(o5_ch) == snap_o5_ch["tree"]
          and len(o5_ch.io.said) == snap_o5_ch["said"] and state_name(o5_ch) == "SISTEM_ZINCIRI", f"{code_o5_ch} {state_name(o5_ch)} {after_o5_ch}")
    ok_o5_ch, halted_o5_ch, out_o5_ch = o5_recover(o5_ch)
    check("O-5 D2 (chain step) recovery: the re-assigned lawyer's --devam turns it into DURDURULDU (U4 rule), the next --devam deletes it (TAMAMLANDI)",
          ok_o5_ch, f"{halted_o5_ch} {out_o5_ch}")

    # D2 sınırı: aynı noktada YETKI_YOK OLMAYAN bir hata -> DURDURULDU bugünkü gibi yazılır (ve koşu kimliği basılır)
    o5_db = start("o5db")
    o5_db_orig_identity = o5_db.backend.identity
    o5_db_flag = {"fail": False}

    def o5_db_identity(case_id):
        snapshot = o5_db_orig_identity(case_id)
        if o5_db_flag["fail"]:
            raise R.OfficeFlowError("VERITABANI_HATASI")
        return snapshot

    o5_db.backend.identity = o5_db_identity
    o5_db_said = {}

    def o5_db_hook(key):
        if key == "stopping_ref":
            o5_db_flag["fail"], o5_db_said["n"] = True, len(o5_db.io.said)
        return None

    o5_db.on_ask = o5_db_hook
    code_o5_db = run_new_fixed_id(o5_db, base_answers(), "1" * 32)
    o5_db.on_ask, o5_db.backend.identity = None, o5_db_orig_identity
    check("O-5 D2 boundary: a NON-authorization error at the same point (W10 live query fails with VERITABANI_HATASI) still halts the run as today: "
          "state DURDURULDU (deletable) and the run id is announced; no reading record",
          code_o5_db == "VERITABANI_HATASI" and state_name(o5_db) == "DURDURULDU" and not o5_db.paths.reading_path.exists()
          and any(o5_db.run_id in t for t in o5_db.io.said[o5_db_said.get("n", 10 ** 6):]), f"{code_o5_db} {state_name(o5_db)}")

    # yetki SÜRÜYORSA: davranış aynı; her yeni nokta cevabın HEMEN ardından canlı sorgu; okuma kaydı TAZE (W10) kimlik
    o5_keep = start("o5keep")
    o5_keep.backend.db_time_by_call = lambda n: f"2026-11-22T09:00:{n:02d}+00:00"
    o5_mark = {}
    o5_f2_keys = ("tebligat_tarihi", "tebligat_sayfa", "kor_son_gun", "adli_tatil", "stopping_durum", "stopping_ref")

    def o5_mark_f2(key):
        if key in o5_f2_keys:
            o5_mark["calls"] = o5_keep.backend.identity_calls   # son F2 sorusu kazanır
        return None

    o5_keep.on_ask = o5_mark_f2
    new_run(o5_keep)
    o5_keep.on_ask = None
    ev_keep = o5_keep.events

    def o5_next_after(key):
        idx = ev_keep.index(("ask", key))
        return ev_keep[idx + 1] if idx + 1 < len(ev_keep) else None

    check("O-5 (authority kept): each new point queries the live identity IMMEDIATELY after its last question (kimlik_ad -> W8, vergi_turleri -> W9, stopping_ref -> W10, "
          "aday_secimi -> W11)",
          all(o5_next_after(k) == ("identity", o5_keep.case_id) for k in ("kimlik_ad", "vergi_turleri", "stopping_ref", "aday_secimi")),
          str([o5_next_after(k) for k in ("kimlik_ad", "vergi_turleri", "stopping_ref", "aday_secimi")]))
    check("O-5 (authority kept): behaviour otherwise unchanged - run_new makes exactly 6 live identity queries (F0, W8, W9, W10, W11, W7), the chain order is identical, "
          "state UYUMLU_RAPOR_KONTROLU, report written",
          sum(1 for e in ev_keep if e[0] == "identity") == 6 and o5_keep.backend.identity_calls == 6
          and [e[1] for e in ev_keep if e[0] == "backend"] == ["manual_fact", "promote_fact", "verify_fact", "generate_timeline", "promote_timeline",
                                                              "generate_deadline", "approve_deadline", "canonical_report"]
          and state_name(o5_keep) == "UYUMLU_RAPOR_KONTROLU" and o5_keep.paths.report_path.is_file(), str([e for e in ev_keep if e[0] in ("identity", "backend")]))
    o5_kimlik = R.load_reading_record(o5_keep.paths)["kimlik"]
    o5_fresh = f"2026-11-22T09:00:{o5_mark.get('calls', -1) + 1:02d}+00:00"
    o5_earlier = {f"2026-11-22T09:00:{n:02d}+00:00" for n in range(1, o5_mark.get("calls", 0) + 1)}
    check("O-5 D3: the reading record's kimlik.db_time is the value of the FIRST live query AFTER the F2 questions (W10) - NOT the F0 snapshot nor any earlier one; "
          "same user and registered name",
          o5_mark.get("calls") == 3 and o5_kimlik["db_time"] == o5_fresh and o5_kimlik["db_time"] not in o5_earlier
          and o5_kimlik["db_time"] != "2026-11-22T09:00:01+00:00" and o5_kimlik["user_id"] == 7 and o5_kimlik["display_name"] == NAME,
          f"{o5_kimlik!r} mark={o5_mark} fresh={o5_fresh}")

    # D3 (akış): W10'dan sonra F3/F4'e geçen kimlik W10 kimliğidir. Kayıtlı ad F2 sırasında değişir (F0 anlık görüntüsü
    # eski adı taşır); onay adı YENİ adla verilir: koşu yalnız W10 kimliği akıyorsa tamamlanır.
    o5_ren = start("o5ren")
    o5_new_name = "Av. Örnek Kullanıcı Yeni"

    def o5_rename(key):
        if key == "tebligat_tarihi":
            o5_ren.backend.name = o5_new_name   # F0/W8/W9 eski adı gördü; W10 ve sonrası yeni adı görür
        return None

    o5_ren.on_ask = o5_rename
    code_o5_ren = code_safe(lambda: new_run(o5_ren, base_answers(onay_ad=o5_new_name)))
    o5_ren.on_ask = None
    o5_ren_run = [p_.name for p_ in (o5_ren.office / "runs").iterdir()]
    o5_ren_paths = R.build_run_paths(o5_ren.office, o5_ren.cases, o5_ren.case_id, o5_ren_run[0]) if len(o5_ren_run) == 1 else None
    o5_ren_state = R.load_run_state(o5_ren_paths.run_dir) if o5_ren_paths else None
    check("O-5 D3 (flow): the identity handed to F3/F4 after W10 is the W10 snapshot - with the registered name changed during F2, the approval-name confirmation "
          "against the NEW name succeeds (one approval, UYUMLU_RAPOR_KONTROLU) and the reading record carries the new name",
          code_o5_ren is None and o5_ren_state is not None and o5_ren_state.state == "UYUMLU_RAPOR_KONTROLU"
          and sum(1 for e in o5_ren.events if e == ("backend", "approve_deadline")) == 1
          and R.load_reading_record(o5_ren_paths)["kimlik"]["display_name"] == o5_new_name,
          f"{code_o5_ren} {getattr(o5_ren_state, 'state', None)}")

    # L-h akış: eksik alanlı durum dosyası -> DUR (soru/bağ/kayıt yok)
    lh = start("lh")
    new_run(lh)
    resume(lh, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    state_data = json.loads(lh.paths.state_path.read_bytes())
    del state_data["gecmis"]
    lh.paths.state_path.write_text(json.dumps(state_data), encoding="utf-8")
    before_lh = fingerprint(lh)
    code_lh = code_of(resume, lh, DEL(lh))
    check("L-h: a state file missing a required field (gecmis) STOPS at load: KAYIT_SEMASI_GECERSIZ, NO question, NO binding file, NO record, nothing deleted",
          code_lh == "KAYIT_SEMASI_GECERSIZ" and fingerprint(lh) == before_lh and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(lh.io.asked)
          and not (lh.paths.run_dir / R.IMHA_BINDING_NAME).exists() and lh.paths.case_dir.exists(), f"{code_lh}")

    # L-g: dürüst sınır cümlesi
    check("L-g: the deletion-complete message carries the honest limit (not a physical/SSD erase guarantee; DB transaction records are not deleted; privacy rests on key destruction)",
          any("fiziksel/SSD silme garantisi DEĞİLDİR" in t and "veritabanı işlem kayıtları silinmez" in t and "anahtarının imhasına" in t for t in c1.io.said))

    # L-f akış: KISMEN sonrası reddedilen deneme KISMEN'i korur
    lf = ready("lf")
    lf.fs = FaultyFs(deny="documents/ihbarname_001/extractions/facts.json")
    resume(lf, DEL(lf))
    lf.fs = None
    records_lf = sorted(p_.name for p_ in (lf.office / "kayitlar").iterdir())
    (lf.paths.case_dir / "documents" / intake.DOC_ID / "baska_muvekkil.pdf").write_bytes(b"BURO")
    resume(lf, {})
    check("L-f: after KISMEN a refused retry (foreign file) adds NO imha record (the KISMEN stays the last word) and the state is SILME_REDDEDILDI",
          sorted(p_.name for p_ in (lf.office / "kayitlar").iterdir()) == records_lf and imha(lf)[-1]["genel_sonuc"] == "KISMEN"
          and state_of(lf).state == "SILME_REDDEDILDI")

    # ================================================================ F0 ve hata yolları
    f0 = start("f0", probes={"import_probe": lambda n: n == "anthropic", "env": {}, "dsn": ""})
    check("F0: an importable external-AI package REFUSES the whole run before any directory or backend call",
          code_of(lambda: flow_for(f0, base_answers()).run_new(case_id=f0.case_id, dosya_kodu=f0.dosya, source_pdf=f0.source)) == "DIS_YZ_PAKETI_VAR"
          and not (f0.office / "runs").exists() and not [e for e in f0.events if e[0] == "backend"] and not (f0.cases / f0.case_id).exists())
    f1 = start("f0b", backend_kwargs={"holiday_ok": False})
    check("F0: an invalid holiday calendar refuses the run (TATIL_TAKVIMI_GECERSIZ) before any directory is created",
          code_of(lambda: flow_for(f1, base_answers()).run_new(case_id=f1.case_id, dosya_kodu=f1.dosya, source_pdf=f1.source)) == "TATIL_TAKVIMI_GECERSIZ" and not (f1.office / "runs").exists())
    f2 = start("f0c", probes={"import_probe": lambda n: False, "env": {}, "dsn": "postgresql://u@db.example.com/x"})
    check("F0: a non-loopback database host refuses the run", code_of(lambda: flow_for(f2, base_answers()).run_new(case_id=f2.case_id, dosya_kodu=f2.dosya, source_pdf=f2.source)) == "DSN_LOOPBACK_DEGIL")
    f3_ = start("f1a")
    inside = f3_.cases / "x.pdf"
    inside.write_bytes(PDF)
    code_f1 = code_of(lambda: flow_for(f3_, base_answers()).run_new(case_id=f3_.case_id, dosya_kodu=f3_.dosya, source_pdf=inside))
    f3_.run_id = [p.name for p in (f3_.office / "runs").iterdir()][0]
    f3_.paths = R.build_run_paths(f3_.office, f3_.cases, f3_.case_id, f3_.run_id)
    check("F1: a source PDF inside the case root is refused (KAYNAK_ICERIDE), no case dir is created and the run is halted (DURDURULDU, deletable)",
          code_f1 == "KAYNAK_ICERIDE" and not f3_.paths.case_dir.exists() and state_of(f3_).state == "DURDURULDU", f"{code_f1} {state_of(f3_).state}")
    check("F1: the offending file inside the case root was NOT touched", inside.read_bytes() == PDF)

    e1 = start("e1", backend_kwargs={"fail_at": "verify_fact"})
    code = code_of(lambda: flow_for(e1, base_answers()).run_new(case_id=e1.case_id, dosya_kodu=e1.dosya, source_pdf=e1.source))
    e1.run_id = [p.name for p in (e1.office / "runs").iterdir()][0]
    e1.paths = R.build_run_paths(e1.office, e1.cases, e1.case_id, e1.run_id)
    check("a chain failure becomes a closed error code, the run is DURDURULDU (no success, no result) and TEMP is restored",
          code == "BILINMEYEN_HATA" and state_of(e1).state == "DURDURULDU" and results(e1) == [] and os.path.realpath(tempfile.gettempdir()) != os.path.realpath(str(e1.paths.tmp_dir)))
    resume(e1, DEL(e1))
    check("a DURDURULDU run can be deleted by the lawyer's separate approval (TAMAMLANDI)", imha(e1)[-1]["genel_sonuc"] == "TAMAMLANDI" and not e1.paths.case_dir.exists())
    e2 = start("e2", backend_kwargs={"anchors": 2})
    check("two candidate anchors -> ANCHOR_BELIRSIZ (no automatic anchor selection)",
          code_of(lambda: flow_for(e2, base_answers()).run_new(case_id=e2.case_id, dosya_kodu=e2.dosya, source_pdf=e2.source)) == "ANCHOR_BELIRSIZ")
    e3 = start("e3", backend_kwargs={"anchors": 0})
    check("no anchor -> ANCHOR_BELIRSIZ", code_of(lambda: flow_for(e3, base_answers()).run_new(case_id=e3.case_id, dosya_kodu=e3.dosya, source_pdf=e3.source)) == "ANCHOR_BELIRSIZ")
    e4 = start("e4")
    check("the lawyer refusing the verification question stops the chain before the verification call (DOGRULAMA_REDDEDILDI)",
          code_of(lambda: flow_for(e4, base_answers(dogrulama_karari="hayır")).run_new(case_id=e4.case_id, dosya_kodu=e4.dosya, source_pdf=e4.source)) == "DOGRULAMA_REDDEDILDI"
          and ("backend", "verify_fact") not in e4.events and ("backend", "generate_deadline") not in e4.events)
    e5 = start("e5")
    check("an invalid candidate choice -> ADAY_SECIMI_GECERSIZ with no backend call",
          code_of(lambda: flow_for(e5, base_answers(aday_secimi="9")).run_new(case_id=e5.case_id, dosya_kodu=e5.dosya, source_pdf=e5.source)) == "ADAY_SECIMI_GECERSIZ" and not [e for e in e5.events if e[0] == "backend"])
    e6 = start("e6")
    code = code_of(lambda: flow_for(e6, base_answers(tebligat_tarihi="31.02.2026")).run_new(case_id=e6.case_id, dosya_kodu=e6.dosya, source_pdf=e6.source))
    check("an impossible independent date is refused at F2 (OKUMA_KAYDI_GECERSIZ) and the reading record is NOT created", code == "OKUMA_KAYDI_GECERSIZ")
    e7 = start("e7")
    try:
        flow_for(e7, {k: v for k, v in base_answers().items() if k != "tebligat_tarihi"}).run_new(case_id=e7.case_id, dosya_kodu=e7.dosya, source_pdf=e7.source)
        eof_raised = False
    except EOFError:
        eof_raised = True
    check("a missing answer (stdin closed) raises EOFError at F2 (mapped to KULLANICI_ILERLETMEDI by the CLI); no backend call happened",
          eof_raised and not [e for e in e7.events if e[0] == "backend"] and outcomes.error_code_for(EOFError()) == "KULLANICI_ILERLETMEDI")

    # ================================================================ CLI main
    class StubBackendFactory:
        pass

    out, err = io.StringIO(), io.StringIO()
    code = F.main(["--office-root", str(TMP)], stdout=out, stderr=err)
    check("CLI: missing required arguments -> exit 2, nothing on stdout, ONLY the fixed closed usage line on the injected stderr (no argument value echo)",
          code == 2 and out.getvalue() == "" and err.getvalue().strip() == "KULLANIM_HATASI: argümanlar geçersiz veya eksik", err.getvalue())
    err_value = io.StringIO()
    code_value = F.main(["--office-root", str(TMP), "--actor-user-id", "GIZLI-10.02.2026"], stdout=io.StringIO(), stderr=err_value)
    check("CLI: a bad argument VALUE is never echoed back (argparse message replaced by the fixed line)",
          code_value == 2 and "GIZLI" not in err_value.getvalue() and "10.02.2026" not in err_value.getvalue())
    cm = start("cm")
    out_half, err_half = io.StringIO(), io.StringIO()
    code = F.main(["--office-root", str(cm.office), "--actor-user-id", "7", "--case-id", cm.case_id], backend=cm.backend, io=ScriptedIO({}, []),
                  case_root=cm.cases, stdout=out_half, stderr=err_half)
    check("CLI: only ONE of --case-id/--dosya-kodu (and no --devam) -> usage exit 2", code == 2 and out_half.getvalue() == "")
    out_list, err_list = io.StringIO(), io.StringIO()
    code = F.main(["--office-root", str(cm.office), "--actor-user-id", "7"], backend=cm.backend, io=F.ConsoleIO(stdin=io.StringIO(""), stdout=out_list),
                  case_root=cm.cases, stdout=out_list, stderr=err_list)
    check("M-2 CLI: neither --devam nor --case-id/--dosya-kodu -> the open-run LIST path (exit 0), nothing created, no usage error",
          code == 0 and "Açık veya yarım kalmış çalışma yok." in out_list.getvalue() and err_list.getvalue() == ""
          and not ((cm.office / "runs").exists() and list((cm.office / "runs").iterdir())))
    cm2 = start("cm2", backend_kwargs={"fail_at": "manual_fact", "secret_failure": "GIZLI tarih 10.02.2026 yol C:\\gizli\\asil_belge.pdf hash " + "a" * 64})
    err = io.StringIO()
    code = F.main(["--office-root", str(cm2.office), "--actor-user-id", "7", "--case-id", cm2.case_id, "--dosya-kodu", cm2.dosya, "--kaynak-pdf", str(cm2.source)],
                  backend=cm2.backend, io=ScriptedIO(base_answers(), cm2.events), case_root=cm2.cases, extractor=lambda p: TEXT,
                  stdout=io.StringIO(), stderr=err, allow_system_drive=True)
    text = err.getvalue()
    check("CLI: a failing run exits 1 and writes ONLY the support summary (version, step, code) to stderr",
          code == 1 and text.count("=") == 3 and "ISLEM_ADIMI=F3" in text and "HATA_KODU=BILINMEYEN_HATA" in text, f"{code} {text!r}")
    check("CLI: the failure text carries NO sentinel from the raised exception (date, path, hash, file name)",
          not any(s in text for s in ("GIZLI", "10.02.2026", "gizli", "asil_belge", "a" * 16, "Traceback")))
    check("CLI: logging.lastResort is restored after main()", logging.lastResort is not None)
    check("CLI: TEMP is restored after a failed main()", os.path.realpath(tempfile.gettempdir()) != os.path.realpath(str(cm2.office)) and "runs" not in tempfile.gettempdir())
    check("CLI: a bad --devam id (not 32 hex) is the closed KOD_GECERSIZ summary, exit 1",
          F.main(["--office-root", str(cm2.office), "--actor-user-id", "7", "--devam", "../../x"], backend=cm2.backend, io=ScriptedIO({}, []),
                 case_root=cm2.cases, stdout=io.StringIO(), stderr=(e_buf := io.StringIO()), allow_system_drive=True) == 1 and "KOD_GECERSIZ" in e_buf.getvalue())
    cm3 = start("cm3")
    code = F.main(["--office-root", str(cm3.office), "--actor-user-id", "7", "--case-id", cm3.case_id, "--dosya-kodu", cm3.dosya, "--kaynak-pdf", str(cm3.source)],
                  backend=cm3.backend, io=ScriptedIO(base_answers(), cm3.events), case_root=cm3.cases, extractor=lambda p: TEXT,
                  stdout=io.StringIO(), stderr=io.StringIO(), allow_system_drive=True)
    cm3_run = [p.name for p in (cm3.office / "runs").iterdir()]
    check("CLI: a successful run (injected backend/io/extractor) exits 0 and leaves a UYUMLU_RAPOR_KONTROLU run",
          code == 0 and len(cm3_run) == 1 and R.load_run_state(cm3.office / "runs" / cm3_run[0]).state == "UYUMLU_RAPOR_KONTROLU", str(code))
    cm4 = start("cm4")
    err4 = io.StringIO()
    code4 = F.main(["--office-root", str(cm4.office), "--actor-user-id", "7", "--case-id", cm4.case_id, "--dosya-kodu", cm4.dosya, "--kaynak-pdf", str(cm4.source)],
                   backend=cm4.backend, io=ScriptedIO({k: v for k, v in base_answers().items() if k != "kor_son_gun"}, cm4.events), case_root=cm4.cases,
                   extractor=lambda p: TEXT, stdout=io.StringIO(), stderr=err4, allow_system_drive=True)
    check("CLI: a closed stdin mid-run is the closed code KULLANICI_ILERLETMEDI at the right step (F2) with the three-field summary only",
          code4 == 1 and "ISLEM_ADIMI=F2" in err4.getvalue() and "HATA_KODU=KULLANICI_ILERLETMEDI" in err4.getvalue() and err4.getvalue().count("=") == 3)
finally:
    for p in TMP.rglob("asil_belge*.pdf"):
        try:
            os.chmod(p, 0o666)
        except OSError:
            pass
    WATCH["path"] = None
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
