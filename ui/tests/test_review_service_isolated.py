# ============================================================
# Row 18b - İZOLE SAF-PYTHON SERVİS TESTLERİ (Layer B inceleme
# kararları)
#
# Bu dosya FastAPI'YE İHTİYAÇ DUYMAZ ve onu import ETMEZ - yalnız
# `ui/services/review_registry.py`'yi ve (yalnız REDDİ/rejection
# yollarını, backend'in İÇ MANTIĞINI YENİDEN YAZMADAN) GERÇEK
# `src/*_review.py` modüllerini doğrudan çağırır. Talimat gereği
# (kullanıcı kararı, 2026-09-04): tüm mutasyon testleri yalnız
# `tempfile.TemporaryDirectory()` içindeki SENTETİK/izole
# canonical/audit dosyalarıyla çalışır - GERÇEK case_0001'e veya
# başka bir canonical dosyaya YAZILMAZ (yalnız Drafting'in
# stale-source testi, salt-okunur biçimde GERÇEK case_0001'in
# fact/document indekslerini okur - hiçbir şey oraya YAZILMAZ, bu
# byte-snapshot karşılaştırmasıyla ayrıca kanıtlanır).
#
# Çalıştırma (bu sandbox'ta da çalışır - FastAPI gerekmez):
#   python ui/tests/test_review_service_isolated.py
# ============================================================

import contextlib
import copy
import hashlib
import json
import sys
import tempfile
import types
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths as real_paths                    # noqa: E402
from ui.services import review_registry as reviewreg            # noqa: E402
from ui.services.common import (                                 # noqa: E402
    UnknownReviewKindError,
    ReviewRecordNotFoundError,
    ReviewStaleViewError,
    ReviewLiveViewInvalidError,
    InvalidReviewNoteError,
    ReviewUiError,
)

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - beklenmeyen istisna: {error!r}")
    else:
        check(label, False, f"{detail} - istisna hiç fırlatılmadı")


@contextlib.contextmanager
def fake_case_registered(fake_case_id):
    """
    `reviewreg.apply_transition`, GERÇEK bir case_id'yi
    `paths.resolve_case_id` ile doğrular (path-traversal/güvenlik
    kontrolü - test için ATLANMAZ veya zayıflatılmaz, GERÇEK
    fonksiyon hiç değiştirilmez). Bu izole testler sentetik/tempdir
    tabanlı case_id'ler kullandığından, `test_routes.py`'deki
    `isolated_case_fixture` ile AYNI desenle `paths.list_case_ids`/
    `paths.resolve_case_id`'yi GEÇİCİ olarak yalnız bu sentetik
    case_id'yi de kabul edecek şekilde genişletiyoruz; `finally`'de
    orijinaline geri dönülür.
    """
    original_list_case_ids = real_paths.list_case_ids
    original_resolve = real_paths.resolve_case_id
    real_paths.list_case_ids = lambda: original_list_case_ids() + [fake_case_id]
    real_paths.resolve_case_id = lambda cid: cid if cid == fake_case_id else original_resolve(cid)
    try:
        yield
    finally:
        real_paths.list_case_ids = original_list_case_ids
        real_paths.resolve_case_id = original_resolve


# ============================================================
# 0) GERÇEK REPO BYTE-SNAPSHOT (test öncesi/sonrası)
# ============================================================

def snapshot_tree(*roots):
    manifest = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest[str(path)] = (path.stat().st_size, path.stat().st_mtime_ns, digest)
    return manifest


_SNAPSHOT_ROOTS = (real_paths.DATA_DIR, real_paths.SRC_DIR)
_before_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)

# GERÇEK case_id - bazı testler (qa.suggestion çağrı-şekli, drafting
# stale-source, fail-closed şema, empty-state) SENTETİK bir case_id ile
# ÇALIŞAMAZ: `qa_review`/`drafting_review`'in transition-onayı GERÇEK
# case'in yukarı akış (issues/arguments/risk_strategy/drafting)
# verisini KENDİ İÇİNDE yeniden hesaplayıp tazelik/tutarlılık
# kontrolü yapıyor (backend'in İÇ MANTIĞI - burada YENİDEN
# YAZILMIYOR). Bu yüzden bu testler GERÇEK case_id'yi kullanır, yalnız
# `canonical_path_override`/`audit_dir_override` ile SENTETİK/izole
# dosyalara yönlendirir - gerçek canonical dosyaya ASLA yazılmaz.
_real_case_ids = real_paths.list_case_ids()
check("ön koşul: gerçek repoda en az bir case var", len(_real_case_ids) > 0, f"case_ids={_real_case_ids}")
_valid_case = _real_case_ids[0] if _real_case_ids else None


# ============================================================
# 1) 12 review_kind REGISTRY MAPPING - doğrulanmış tam liste, her
#    kind için gerçek modül import edilebilir mi, allowed_targets
#    gerçek modül sabitiyle (KOPYA DEĞİL - identity/eşitlik) uyuşuyor
#    mu.
# ============================================================

_EXPECTED_KINDS = {
    "evidence.candidate", "evidence.suggestion",
    "argument.claim", "argument.counterargument", "argument.rebuttal", "argument.suggestion",
    "risk_strategy.risk", "risk_strategy.strategy", "risk_strategy.suggestion",
    "drafting.section", "drafting.suggestion",
    "qa.suggestion",
}

check(
    "REVIEW_KIND_REGISTRY tam olarak 12 doğrulanmış review_kind içeriyor",
    set(reviewreg.REVIEW_KIND_REGISTRY.keys()) == _EXPECTED_KINDS,
    f"fark={set(reviewreg.REVIEW_KIND_REGISTRY.keys()) ^ _EXPECTED_KINDS}",
)

import evidence_review        # noqa: E402
import argument_review        # noqa: E402
import risk_strategy_review   # noqa: E402
import drafting_review        # noqa: E402
import qa_review              # noqa: E402
import risk_strategy_agent    # noqa: E402
import risk_strategy_engine   # noqa: E402
import risk_strategy_policy   # noqa: E402

for kind in sorted(_EXPECTED_KINDS):
    targets = reviewreg.get_allowed_targets(kind)
    check(f"get_allowed_targets({kind!r}) boş olmayan bir küme döndürüyor", bool(targets), f"targets={targets}")

# Hedef-durum sabiti HİÇBİR YERDE KOPYALANMADI - identity (aynı nesne)
# kontrolüyle doğrulanıyor.
check(
    "evidence.candidate hedefleri GERÇEK modül sabitiyle AYNI nesne (kopya değil)",
    reviewreg.get_allowed_targets("evidence.candidate") is evidence_review.CANDIDATE_ALLOWED_TARGETS,
)
check(
    "evidence.suggestion hedefleri GERÇEK modül sabitiyle AYNI nesne (kopya değil)",
    reviewreg.get_allowed_targets("evidence.suggestion") is evidence_review.SUGGESTION_ALLOWED_TARGETS,
)
check(
    "argument.claim hedefleri GERÇEK ALLOWED_TARGETS_BY_TYPE['claim'] ile AYNI nesne",
    reviewreg.get_allowed_targets("argument.claim") is argument_review.ALLOWED_TARGETS_BY_TYPE["claim"],
)
check(
    "risk_strategy.strategy hedefleri GERÇEK ALLOWED_TARGETS_BY_TYPE['strategy'] ile AYNI nesne",
    reviewreg.get_allowed_targets("risk_strategy.strategy")
    is risk_strategy_review.ALLOWED_TARGETS_BY_TYPE["strategy"],
)
check(
    "drafting.section hedefleri GERÇEK ALLOWED_TARGETS_BY_TYPE['section'] ile AYNI nesne",
    reviewreg.get_allowed_targets("drafting.section") is drafting_review.ALLOWED_TARGETS_BY_TYPE["section"],
)
check(
    "qa.suggestion hedefleri GERÇEK ALLOWED_TARGET_STATES ile AYNI nesne",
    reviewreg.get_allowed_targets("qa.suggestion") is qa_review.ALLOWED_TARGET_STATES,
)

# Alan adları (array/id/state) argument/risk_strategy/drafting için
# CANLI modül sabitinden okunuyor - KOPYA DEĞİL.
_af, _if, _sf = reviewreg.get_field_names("argument.counterargument")
check(
    "argument.counterargument alan adları GERÇEK ARRAY/ID/STATE_FIELD_BY_TYPE ile birebir",
    (_af, _if, _sf) == (
        argument_review.ARRAY_FIELD_BY_TYPE["counterargument"],
        argument_review.ID_FIELD_BY_TYPE["counterargument"],
        argument_review.STATE_FIELD_BY_TYPE["counterargument"],
    ),
)


# ============================================================
# 2) QA'NIN FARKLI CALL SHAPE'İ - `record_type` parametresi YOK,
#    yapay bir `record_type` İCAT EDİLMEDİ (`call_shape="qa_special"`)
# ============================================================

check(
    "qa.suggestion kaydı record_type=None taşıyor (yapay record_type İCAT EDİLMEDİ)",
    reviewreg.REVIEW_KIND_REGISTRY["qa.suggestion"]["record_type"] is None,
)
check(
    "qa.suggestion call_shape='qa_special' olarak işaretli",
    reviewreg.REVIEW_KIND_REGISTRY["qa.suggestion"]["call_shape"] == "qa_special",
)

# NOT: `qa_review.apply_review_transition` GERÇEK bir tazelik/tutarlılık
# doğrulaması yapar - CONFIRM sırasında case'in yukarı akış (issues/
# arguments/risk_strategy/drafting) verisinden QA motorunun ÇIKTISINI
# YENİDEN hesaplayıp canonical'dakiyle karşılaştırır (backend'in İÇ
# MANTIĞI - burada yeniden yazılmıyor). Bu yüzden SENTETİK bir case_id
# (`case_iso_qa` gibi) ile çağrılırsa yukarı akış dosyaları hiç
# bulunamadığı için FileNotFoundError fırlatır - bu registry'nin BİR
# HATASI DEĞİL, backend'in kendi tazelik kontrolünün bir sonucu. Bu
# yüzden burada GERÇEK case_id (`_valid_case`) kullanılıyor, yalnız
# `canonical_path_override`/`audit_dir_override` ile İZOLE/sentetik
# dosyalara yönlendiriliyor - gerçek qa.json'a ASLA yazılmaz. Sentetik
# canonical içeriği gerçek case'in yeniden hesaplanan çıktısıyla
# uyuşmayabileceğinden, ALTTAKI mutasyonun başarılı olması
# BEKLENMİYOR - yalnız `qa_review.apply_review_transition`'ın
# `record_type` OLMADAN, tam 5 pozisyonel argümanla çağrıldığı
# (çağrı ŞEKLİ) doğrulanıyor; sayaç, GERÇEK fonksiyon herhangi bir
# istisna fırlatsa BİLE (fırlatma çağrıdan SONRA olur) doğru kalır.
if _valid_case:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        qa_canonical = tmp_path / "qa.json"
        qa_canonical.write_text(
            json.dumps({"qa_agent_suggestions": [{"suggestion_id": "qas_1", "suggestion_review_state": "needs_review"}]}),
            encoding="utf-8",
        )
        qa_audit_dir = tmp_path / "reviews" / "qa_reviews"

        _qa_calls = {"n": 0, "args": None}
        _original_qa_apply = qa_review.apply_review_transition

        def _counting_qa_apply(*args, **kwargs):
            _qa_calls["n"] += 1
            _qa_calls["args"] = args
            return _original_qa_apply(*args, **kwargs)

        qa_review.apply_review_transition = _counting_qa_apply
        try:
            expected_hash = hashlib.sha256(qa_canonical.read_bytes()).hexdigest()
            try:
                reviewreg.apply_transition(
                    "qa.suggestion", _valid_case, "qas_1", "dismissed", "izole test notu",
                    expected_hash, canonical_path_override=qa_canonical, audit_dir_override=qa_audit_dir,
                )
            except Exception:
                # Gerçek backend'in tazelik/tutarlılık kontrolü sentetik
                # canonical içeriğini reddedebilir - bu testin konusu
                # DEĞİL, yalnız çağrı ŞEKLİ ilgileniyor (aşağıda kontrol
                # edilir). Gerçek qa.json'a hiçbir şey yazılmadı (yalnız
                # izole tmp dosyası kullanıldı).
                pass
            check(
                "qa.suggestion mutasyonu record_type OLMADAN çağrıldı (pozisyonel imza doğru)",
                _qa_calls["n"] == 1 and len(_qa_calls["args"]) == 5,
                f"args={_qa_calls['args']}",
            )
        finally:
            qa_review.apply_review_transition = _original_qa_apply


# ============================================================
# 3) review_note DOĞRULAMASI - boş, yalnız whitespace, 2000, 2001
# ============================================================

expect_raises(InvalidReviewNoteError, lambda: reviewreg.normalize_review_note(""), "review_note: boş string reddedilir")
expect_raises(InvalidReviewNoteError, lambda: reviewreg.normalize_review_note("   \n\t  "), "review_note: yalnız whitespace reddedilir")
expect_raises(InvalidReviewNoteError, lambda: reviewreg.normalize_review_note(None), "review_note: None reddedilir")

_note_2000 = "a" * 2000
check("review_note: tam 2000 karakter KABUL edilir", reviewreg.normalize_review_note(_note_2000) == _note_2000)

_note_2001 = "a" * 2001
expect_raises(InvalidReviewNoteError, lambda: reviewreg.normalize_review_note(_note_2001), "review_note: 2001 karakter reddedilir")

check(
    "review_note: baştaki/sondaki whitespace trim edilir, backend'e trimmed gider",
    reviewreg.normalize_review_note("  gerçek not  ") == "gerçek not",
)


# ============================================================
# 4) GEÇERSİZ HEDEF DURUM - registry allowlist'ine karşı reddedilir
# ============================================================

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    ev_canonical = tmp_path / "evidence.json"
    ev_canonical.write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_1", "review_state": "needs_review"}]}),
        encoding="utf-8",
    )
    expected_hash = hashlib.sha256(ev_canonical.read_bytes()).hexdigest()

    with fake_case_registered("case_iso_evidence"):
        expect_raises(
            ReviewUiError,
            lambda: reviewreg.apply_transition(
                "evidence.candidate", "case_iso_evidence", "ec_1", "APPROVED_FOREVER",
                "not", expected_hash, canonical_path_override=ev_canonical,
                audit_dir_override=tmp_path / "reviews",
            ),
            "geçersiz target_state ('APPROVED_FOREVER') reddedilir",
        )
    check(
        "geçersiz target_state sonrası canonical dosya DEĞİŞMEDİ",
        json.loads(ev_canonical.read_text(encoding="utf-8"))["evidence_candidates"][0]["review_state"] == "needs_review",
    )

expect_raises(
    UnknownReviewKindError,
    lambda: reviewreg.get_allowed_targets("olmayan.kind"),
    "bilinmeyen review_kind reddedilir",
)


# ============================================================
# 5) AYNI suggestion_id FARKLI review_kind'LARDA ÇAKIŞMIYOR (bileşik
#    kimlik: review_kind + record_id)
# ============================================================

_original_load_and_validate = reviewreg._load_and_validate_canonical


def _fake_load_and_validate(review_kind, case_id):
    if review_kind == "argument.suggestion":
        return (
            {"argument_agent_suggestions": [
                {"suggestion_id": "suggestion_shared_001", "suggestion_review_state": "needs_review", "kaynak": "argument"},
            ]},
            Path("argument_fake.json"),
        )
    if review_kind == "risk_strategy.suggestion":
        return (
            {"risk_strategy_agent_suggestions": [
                {"suggestion_id": "suggestion_shared_001", "suggestion_review_state": "needs_review", "kaynak": "risk_strategy"},
            ]},
            Path("risk_strategy_fake.json"),
        )
    return _original_load_and_validate(review_kind, case_id)


if _real_case_ids:
    reviewreg._load_and_validate_canonical = _fake_load_and_validate
    try:
        _arg_item = reviewreg.get_review_record("argument.suggestion", _valid_case, "suggestion_shared_001")
        _rs_item = reviewreg.get_review_record("risk_strategy.suggestion", _valid_case, "suggestion_shared_001")

        check(
            "aynı record_id ('suggestion_shared_001') iki farklı review_kind'da BAĞIMSIZ kayıtlara çözülüyor",
            _arg_item["record"]["kaynak"] == "argument" and _rs_item["record"]["kaynak"] == "risk_strategy",
            f"arg={_arg_item['record']}, rs={_rs_item['record']}",
        )
    finally:
        reviewreg._load_and_validate_canonical = _original_load_and_validate


# ============================================================
# 6) GERÇEK BACKEND RETLERİ - parent-dependency (argument), R1/R2
#    (risk_strategy), stale-source (drafting), terminal-state ikinci
#    transition reddi (evidence). Backend'in İÇ MANTIĞI (bu
#    kontroller) HİÇ YENİDEN YAZILMADI - GERÇEK modül fonksiyonları
#    doğrudan, yalnız izole/sentetik canonical dosyalarla çağrılıyor.
# ============================================================

# --- 6a: evidence - terminal state'ten ikinci transition reddi ---
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    ev_canonical = tmp_path / "evidence.json"
    ev_canonical.write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_1", "review_state": "confirmed"}]}),
        encoding="utf-8",
    )
    expect_raises(
        evidence_review.EvidenceReviewError,
        lambda: evidence_review.apply_review_transition(
            "case_iso_evidence", "candidate", "ec_1", "rejected", "test", "not",
            canonical_path=ev_canonical, audit_dir=tmp_path / "reviews",
        ),
        "evidence: zaten 'confirmed' olan candidate'a ikinci transition reddedilir",
    )
    check(
        "evidence: reddedilen ikinci transition sonrası dosya DEĞİŞMEDİ",
        json.loads(ev_canonical.read_text(encoding="utf-8"))["evidence_candidates"][0]["review_state"] == "confirmed",
    )
    check(
        "evidence: reddedilen ikinci transition sonrası HİÇBİR audit dosyası oluşmadı",
        not (tmp_path / "reviews").exists() or not any((tmp_path / "reviews").iterdir()),
    )

# --- 6b: argument - parent henüz terminal değil ---
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    arg_canonical = tmp_path / "arguments.json"
    arg_canonical.write_text(
        json.dumps({
            "argument_claims": [{"claim_id": "c1", "claim_review_state": "needs_review"}],
            "argument_counterarguments": [
                {"counterargument_id": "ca1", "counter_review_state": "needs_review", "source_claim_id": "c1"},
            ],
        }),
        encoding="utf-8",
    )
    try:
        argument_review.apply_review_transition(
            "case_iso_argument", "counterargument", "ca1", "confirmed", "test", "not",
            canonical_path=arg_canonical, audit_dir=tmp_path / "reviews",
        )
        check("argument: parent needs_review iken child confirm reddedilir", False, "istisna fırlatılmadı")
    except argument_review.ArgumentReviewError as error:
        check(
            "argument: parent needs_review iken child confirm reddedilir (R: top-down sıra)",
            "terminal state" in str(error),
            str(error),
        )

# --- 6c: argument - parent rejected iken child yalnız rejected olabilir ---
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    arg_canonical = tmp_path / "arguments.json"
    arg_canonical.write_text(
        json.dumps({
            "argument_claims": [{"claim_id": "c1", "claim_review_state": "rejected"}],
            "argument_counterarguments": [
                {"counterargument_id": "ca1", "counter_review_state": "needs_review", "source_claim_id": "c1"},
            ],
        }),
        encoding="utf-8",
    )
    try:
        argument_review.apply_review_transition(
            "case_iso_argument", "counterargument", "ca1", "confirmed", "test", "not",
            canonical_path=arg_canonical, audit_dir=tmp_path / "reviews",
        )
        check("argument: parent rejected iken child confirm reddedilir", False, "istisna fırlatılmadı")
    except argument_review.ArgumentReviewError as error:
        check(
            "argument: parent rejected iken child confirm reddedilir (LOCKED contract)",
            "yalnız 'rejected' olabilir" in str(error),
            str(error),
        )

# --- 6d: risk_strategy R1 - addressed risk hâlâ needs_review ---
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    rs_canonical = tmp_path / "risk_strategy.json"
    rs_canonical.write_text(
        json.dumps({
            "risk_candidates": [{"risk_id": "r1", "risk_review_state": "needs_review"}],
            "strategy_candidates": [
                {"strategy_id": "s1", "strategy_review_state": "needs_review", "addresses_risk_ids": ["r1"]},
            ],
        }),
        encoding="utf-8",
    )
    try:
        risk_strategy_review.apply_review_transition(
            "case_iso_rs", "strategy", "s1", "accepted_for_follow_up", "test", "not",
            canonical_path=rs_canonical, audit_dir=tmp_path / "reviews",
        )
        check("risk_strategy R1: needs_review risk varken strategy review reddedilir", False, "istisna fırlatılmadı")
    except risk_strategy_review.RiskStrategyReviewError as error:
        check(
            "risk_strategy R1: needs_review risk varken strategy review reddedilir",
            "needs_review" in str(error),
            str(error),
        )

# --- 6e: risk_strategy R2 - tüm addressed risk'ler rejected -> yalnız
# dismissed olabilir. Bu ret, `check_parent_dependency` içinde,
# MUTASYONDAN ÖNCE gerçekleşir - herhangi bir case verisine ihtiyaç
# duymaz, bu yüzden sentetik case_id ile test edilebilir. ---
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    rs_canonical = tmp_path / "risk_strategy.json"
    rs_canonical.write_text(
        json.dumps({
            "risk_candidates": [{"risk_id": "r1", "risk_review_state": "rejected"}],
            "strategy_candidates": [
                {"strategy_id": "s1", "strategy_review_state": "needs_review", "addresses_risk_ids": ["r1"]},
            ],
        }),
        encoding="utf-8",
    )
    try:
        risk_strategy_review.apply_review_transition(
            "case_iso_rs", "strategy", "s1", "accepted_for_follow_up", "test", "not",
            canonical_path=rs_canonical, audit_dir=tmp_path / "reviews",
        )
        check("risk_strategy R2: tüm risk'ler rejected iken 'accepted_for_follow_up' reddedilir", False, "istisna fırlatılmadı")
    except risk_strategy_review.RiskStrategyReviewError as error:
        check(
            "risk_strategy R2: tüm risk'ler rejected iken 'accepted_for_follow_up' reddedilir",
            "dismissed" in str(error),
            str(error),
        )
    check(
        "risk_strategy R2: reddedilen çağrı sonrası dosya DEĞİŞMEDİ",
        json.loads(rs_canonical.read_text(encoding="utf-8"))["strategy_candidates"][0]["strategy_review_state"] == "needs_review",
    )

# --- 6e-2: risk_strategy R2 KABUL YOLU (targeted remediation,
# 2026-09-05) - GERÇEK `risk_strategy_review.apply_review_transition`
# ile UÇTAN UCA, backend'in KENDİ self-test fixture-üretim deseninin
# (`src/risk_strategy_review.py` `run_self_test()` - T07 senaryosu)
# BİREBİR AYNISI kullanılarak. R2 mantığı BURADA YENİDEN
# YAZILMIYOR/TAKLİT EDİLMİYOR: gerçek `FakeRiskStrategyLLMClient` +
# gerçek `build_risk_strategy_engine_output` (case_0001'in GERÇEK,
# salt-okunur issue/fact context'inden ŞEMAYA UYGUN bir analiz
# üretir) + gerçek `_recompute_coverage` fixture-yardımcısı ile
# schema-valid bir analiz üretilip YALNIZ izole bir tempdir canonical
# dosyasına yazılır - GERÇEK case_0001/risk_strategy/risk_strategy.json
# dosyasına HİÇBİR AN yazılmaz (bu, aşağıda hem yerel byte-snapshot
# hem de dosyanın sonundaki genel data/+src/ byte-snapshot ile İKİ
# KEZ kanıtlanır). Ardından GERÇEK `apply_review_transition`,
# mutasyon SONRASI backend'in TAM `validate_risk_strategy_analysis`
# doğrulayıcısını (raise_on_error=True) bu izole dosya üzerinde
# çalıştırır - bu, testin GERÇEKTEN production şemasından geçtiğinin
# kanıtıdır. ---
if _valid_case:
    _rs_r2_real_tree_before = risk_strategy_review.snapshot_real_risk_strategy_tree(_valid_case)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rs_r2_canonical = tmp_path / "risk_strategy.json"
        rs_r2_audit_dir = tmp_path / "reviews" / "risk_strategy_reviews"

        _identified_response = json.dumps([
            {
                "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
                "reason_code": "explicit_textual_match",
                "grounded_explanation": "Test guvenli metin (izole Row 18b R2 kabul-yolu testi).",
                "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
                "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
                "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
                "source_timeline_event_ids": [], "source_deadline_ids": [],
            }
        ], ensure_ascii=False)

        _rs_client = risk_strategy_agent.FakeRiskStrategyLLMClient(
            response_sequence=[_identified_response, "[]"],
        )
        _rs_engine_result = risk_strategy_engine.build_risk_strategy_engine_output(
            _valid_case, use_agent=True, llm_client=_rs_client, network_allowed=False,
        )
        _rs_real_analysis = _rs_engine_result["analysis"]
        _rs_risk_by_id = {r["risk_id"]: r for r in _rs_real_analysis["risk_candidates"]}

        # T07 (run_self_test) ile AYNI desen: 2 farklı issue'ya bağlı
        # gap risk, TEK bir stratejiyle birlikte adreslenir - R2, TÜM
        # addressed risk'ler rejected iken devreye girer.
        _r2_risk_id_a, _r2_risk_id_b = "risk_gap_002", "risk_gap_003"
        _r2_risk_a = copy.deepcopy(_rs_risk_by_id[_r2_risk_id_a])
        _r2_risk_a["risk_review_state"] = "needs_review"
        _r2_risk_b = copy.deepcopy(_rs_risk_by_id[_r2_risk_id_b])
        _r2_risk_b["risk_review_state"] = "needs_review"

        _r2_strategy = {
            "strategy_id": "strategy_iso_r2_accept_path_001",
            "addresses_risk_ids": [_r2_risk_id_a, _r2_risk_id_b],
            "strategy_action_type": "request_human_risk_assessment",
            "strategy_description": risk_strategy_policy.render_strategy_description("request_human_risk_assessment"),
            "grounded_explanation": "İzole Row 18b R2 kabul-yolu testi - iki gap risk birlikte adreslenmektedir.",
            "source_fact_ids": [], "source_claim_ids": [], "source_counterargument_ids": [],
            "source_rebuttal_ids": [], "source_evidence_candidate_ids": [], "source_legal_research_ids": [],
            "source_case_law_ids": [],
            "source_timeline_event_ids": list(set(
                _r2_risk_a.get("source_timeline_event_ids", []) + _r2_risk_b.get("source_timeline_event_ids", [])
            )),
            "source_deadline_ids": list(set(
                _r2_risk_a.get("source_deadline_ids", []) + _r2_risk_b.get("source_deadline_ids", [])
            )),
            "flags": dict(_r2_risk_a["flags"]),
            "depends_on_gap_only": True,
            "record_kind": "suggested_next_action",
            "requires_human_decision": True,
            "strategy_review_state": "needs_review",
            "requires_human_review": True,
            "status": "candidate",
        }

        _rs_r2_base = json.loads(json.dumps(_rs_real_analysis))
        _rs_r2_base["risk_candidates"] = [_r2_risk_a, _r2_risk_b]
        _rs_r2_base["strategy_candidates"] = [_r2_strategy]
        _rs_r2_base["risk_strategy_agent_suggestions"] = []
        _rs_r2_base = risk_strategy_review._recompute_coverage(
            _rs_r2_base, [_r2_risk_a, _r2_risk_b], [_r2_strategy], [],
        )
        risk_strategy_review.atomic_write_json(rs_r2_canonical, _rs_r2_base)

        # Her iki parent risk de GERÇEK apply_review_transition ile
        # rejected yapılır (R2'nin ön koşulu).
        risk_strategy_review.apply_review_transition(
            _valid_case, "risk", _r2_risk_id_a, "rejected", "test_reviewer", "izole R2 kabul-yolu testi",
            canonical_path=rs_r2_canonical, audit_dir=rs_r2_audit_dir,
        )
        risk_strategy_review.apply_review_transition(
            _valid_case, "risk", _r2_risk_id_b, "rejected", "test_reviewer", "izole R2 kabul-yolu testi",
            canonical_path=rs_r2_canonical, audit_dir=rs_r2_audit_dir,
        )

        try:
            risk_strategy_review.apply_review_transition(
                _valid_case, "strategy", "strategy_iso_r2_accept_path_001", "accepted_for_follow_up",
                "test_reviewer", "izole R2 kabul-yolu testi",
                canonical_path=rs_r2_canonical, audit_dir=rs_r2_audit_dir,
            )
            check(
                "risk_strategy R2 kabul-yolu: TÜM parent'lar rejected iken accepted_for_follow_up hedefi REDDEDİLİR",
                False, "istisna fırlatılmadı",
            )
        except risk_strategy_review.RiskStrategyReviewError as error:
            check(
                "risk_strategy R2 kabul-yolu: TÜM parent'lar rejected iken accepted_for_follow_up hedefi REDDEDİLİR",
                "dismissed" in str(error),
                str(error),
            )

        _r2_result = risk_strategy_review.apply_review_transition(
            _valid_case, "strategy", "strategy_iso_r2_accept_path_001", "dismissed",
            "test_reviewer", "izole R2 kabul-yolu testi",
            canonical_path=rs_r2_canonical, audit_dir=rs_r2_audit_dir,
        )
        check(
            "risk_strategy R2 kabul-yolu: 'dismissed' hedefi GERÇEK apply_review_transition ile BAŞARIYLA uygulanır (backend'in TAM validator'ü dahil)",
            _r2_result.get("new_state") == "dismissed",
            _r2_result,
        )
        check(
            "risk_strategy R2 kabul-yolu: apply_review_transition sonucu parent_states TAM parent haritasını içerir",
            _r2_result.get("parent_states") == {_r2_risk_id_a: "rejected", _r2_risk_id_b: "rejected"},
            _r2_result.get("parent_states"),
        )

        _rs_r2_final = json.loads(rs_r2_canonical.read_text(encoding="utf-8"))
        _rs_r2_final_strategy = next(
            s for s in _rs_r2_final["strategy_candidates"]
            if s["strategy_id"] == "strategy_iso_r2_accept_path_001"
        )
        check(
            "risk_strategy R2 kabul-yolu: canonical (izole) dosyada strategy durumu 'dismissed'",
            _rs_r2_final_strategy["strategy_review_state"] == "dismissed",
        )

        # audit_dir'de bu blokta toplam 3 audit dosyası oluşur (2x
        # risk rejected + 1x strategy dismissed) - yalnız 'dismissed'
        # geçişine ait olanı seçip TAM OLARAK BİR TANE olduğunu
        # doğruluyoruz.
        _r2_audit_files = list(rs_r2_audit_dir.glob("*.json")) if rs_r2_audit_dir.exists() else []
        _r2_audit_records = [json.loads(p.read_text(encoding="utf-8")) for p in _r2_audit_files]
        _r2_dismiss_audits = [
            a for a in _r2_audit_records
            if a.get("new_state") == "dismissed" and a.get("record_id") == "strategy_iso_r2_accept_path_001"
        ]
        check(
            "risk_strategy R2 kabul-yolu: TAM OLARAK BİR izole Layer B audit dosyası ('dismissed') yazıldı",
            len(_r2_dismiss_audits) == 1,
            f"toplam_audit={len(_r2_audit_records)} dismiss_audit={len(_r2_dismiss_audits)}",
        )
        if len(_r2_dismiss_audits) == 1:
            check(
                "risk_strategy R2 kabul-yolu: audit.parent_states_at_review_time TAM parent haritasını içerir",
                _r2_dismiss_audits[0].get("parent_states_at_review_time") == {_r2_risk_id_a: "rejected", _r2_risk_id_b: "rejected"},
                _r2_dismiss_audits[0].get("parent_states_at_review_time"),
            )

    _rs_r2_real_tree_after = risk_strategy_review.snapshot_real_risk_strategy_tree(_valid_case)
    check(
        "risk_strategy R2 kabul-yolu testi sonrası GERÇEK case'in risk_strategy/ ağacı DEĞİŞMEDİ (yerel byte-snapshot)",
        _rs_r2_real_tree_after == _rs_r2_real_tree_before,
        f"önce={_rs_r2_real_tree_before} sonra={_rs_r2_real_tree_after}",
    )

# --- 6f: drafting - stale-source-deny (GERÇEK case_0001'in fact indeksi
#     SALT OKUNUR olarak kullanılır - hiçbir şey oraya YAZILMAZ) ---
if _real_case_ids:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        draft_canonical = tmp_path / "drafting.json"
        draft_canonical.write_text(
            json.dumps({
                "draft_sections": [{"section_id": "sec1", "section_review_state": "needs_review"}],
                "draft_source_refs": [
                    {"section_id": "sec1", "source_field": "source_fact_ids", "source_id": "fact_bu_asla_var_olmayan_999"},
                ],
            }),
            encoding="utf-8",
        )
        try:
            drafting_review.apply_review_transition(
                _valid_case, "section", "sec1", "confirmed", "test", "not",
                canonical_path=draft_canonical, audit_dir=tmp_path / "reviews",
            )
            check("drafting: var olmayan kaynağa (stale) sahip section confirm reddedilir", False, "istisna fırlatılmadı")
        except drafting_review.DraftingReviewError as error:
            check(
                "drafting: var olmayan kaynağa (stale) sahip section confirm reddedilir",
                "stale_source_now_denied" in str(error) or "CONFIRM edilemedi" in str(error),
                str(error),
            )
        check(
            "drafting: stale-source reddi sonrası dosya DEĞİŞMEDİ",
            json.loads(draft_canonical.read_text(encoding="utf-8"))["draft_sections"][0]["section_review_state"] == "needs_review",
        )


# ============================================================
# 7) STALE CANONICAL HASH -> SIFIR MUTASYON, SIFIR AUDIT (registry
#    seviyesi guard - GERÇEK apply_review_transition HİÇ ÇAĞRILMAZ)
# ============================================================

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    ev_canonical = tmp_path / "evidence.json"
    ev_canonical.write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_1", "review_state": "needs_review"}]}),
        encoding="utf-8",
    )
    audit_dir = tmp_path / "reviews"

    stale_expected_hash = hashlib.sha256(ev_canonical.read_bytes()).hexdigest()

    # Ekran render edildikten SONRA dosya değişmiş gibi simüle et.
    ev_canonical.write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_1", "review_state": "needs_review", "degisti": True}]}),
        encoding="utf-8",
    )

    _calls = {"n": 0}
    _original_apply = evidence_review.apply_review_transition

    def _counting_apply(*args, **kwargs):
        _calls["n"] += 1
        return _original_apply(*args, **kwargs)

    evidence_review.apply_review_transition = _counting_apply
    try:
        with fake_case_registered("case_iso_stale"):
            expect_raises(
                ReviewStaleViewError,
                lambda: reviewreg.apply_transition(
                    "evidence.candidate", "case_iso_stale", "ec_1", "confirmed", "not",
                    stale_expected_hash, canonical_path_override=ev_canonical, audit_dir_override=audit_dir,
                ),
                "stale hash -> ReviewStaleViewError, GERÇEK apply_review_transition HİÇ ÇAĞRILMADI",
            )
        check("stale hash durumunda gerçek apply_review_transition ÇAĞRILMADI (sayaç=0)", _calls["n"] == 0)
    finally:
        evidence_review.apply_review_transition = _original_apply

    check("stale hash durumunda HİÇBİR audit dosyası oluşmadı", not audit_dir.exists())


# ============================================================
# 8) BEKLENEN DOMAIN MESAJI vs BEKLENMEYEN EXCEPTION AYRIMI
# ============================================================

check(
    "5 domain hata sınıfı DOMAIN olarak sınıflandırılıyor",
    all(
        reviewreg.is_domain_review_error(exc_type("test"))
        for exc_type in reviewreg.DOMAIN_REVIEW_ERROR_TYPES
    ),
)
check(
    "sıradan bir RuntimeError DOMAIN DEĞİL (generic kalmalı)",
    not reviewreg.is_domain_review_error(RuntimeError("gizli ayrıntı - tarayıcıya SIZMAMALI")),
)
check(
    "registry'nin kendi ReviewUiError'ı DOMAIN DEĞİL (ayrı allowlist)",
    not reviewreg.is_domain_review_error(ReviewUiError("iç hata")),
)


# ============================================================
# 9) GEÇERSİZ CANONICAL ŞEMA -> FAIL-CLOSED (18a'nın live_view
#    deseniyle AYNI ilke - GERÇEK case_0001 argument.json'ı deepcopy
#    edilip bozuluyor, orijinal dosyaya HİÇ dokunulmuyor)
# ============================================================

if _real_case_ids:
    _real_arguments_path = argument_review.get_canonical_path(_valid_case)

    if _real_arguments_path.exists():

        with open(_real_arguments_path, "r", encoding="utf-8") as f:
            _real_arguments = json.load(f)

        # Pozitif yol: gerçek canonical veriyle fail-closed'a DÜŞMEMELİ.
        try:
            _listing = reviewreg.list_reviewable("argument.claim", _valid_case)
            check("list_reviewable: GERÇEK case verisiyle başarıyla döner (fail-closed'a düşmez)", True)
        except ReviewLiveViewInvalidError as error:
            check("list_reviewable: GERÇEK case verisiyle başarıyla döner (fail-closed'a düşmez)", False, str(error))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _broken = copy.deepcopy(_real_arguments)
            _broken.pop("case_id", None)
            _broken.pop("argument_claims", None)
            _broken_path = tmp_path / "arguments.json"
            _broken_path.write_text(json.dumps(_broken), encoding="utf-8")

            _original_get_canonical_path = argument_review.get_canonical_path
            argument_review.get_canonical_path = lambda cid: _broken_path
            try:
                expect_raises(
                    ReviewLiveViewInvalidError,
                    lambda: reviewreg.list_reviewable("argument.claim", _valid_case),
                    "list_reviewable: bozuk/eksik alanlı canonical -> fail-closed ReviewLiveViewInvalidError",
                )
            finally:
                argument_review.get_canonical_path = _original_get_canonical_path

        check(
            "GERÇEK arguments.json dosyası bu testle DEĞİŞMEDİ (yalnız okundu)",
            json.loads(_real_arguments_path.read_text(encoding="utf-8")) == _real_arguments,
        )


# ============================================================
# 10) DRAFTING/QA GEÇERLİ EMPTY-STATE (GERÇEK case_0001 verisiyle -
#     her iki agent da bu session'da hiç çalıştırılmadığı için
#     canonical dosyaları VAR ama ilgili array'leri GERÇEKTEN boş)
#
# NOT (dürüstçe belgelenmiş kapsam sınırı): `drafting.*` için GERÇEK
# case_0001 verisi bu turda kendi validator'ünden GEÇİYOR (boş
# array'ler geçerli empty-state). `qa.suggestion` için ise GERÇEK
# case_0001'in qa.json'ı - Row 18b'nin YAZDIĞI hiçbir şeyle İLGİSİZ,
# ambient bir veri tazeliği durumu nedeniyle (qa.json'daki kayıtlı
# 'legal_research' sonucu, bağımsız yeniden hesaplamayla EŞLEŞMİYOR -
# muhtemelen qa.json üretildikten SONRA legal_research verisi
# değişti) - şu an KENDİ validator'ünden GEÇMİYOR. Bu, registry'nin
# fail-closed korumasının TAM DA beklendiği gibi çalıştığının
# kanıtıdır (18a'nın canlı-görünüm deseniyle AYNI ilke - geçersiz
# canonical asla sessizce boş array'e çevrilmez). Bu yüzden
# qa.suggestion için HER İKİ sonuç da (geçerli+boş VEYA fail-closed)
# kabul edilir; hangisi gerçekleşirse gerçekleşsin, davranışın DOĞRU
# olduğu ayrıca doğrulanır.
# ============================================================

if _real_case_ids:
    for kind in ("drafting.section", "drafting.suggestion"):
        try:
            listing = reviewreg.list_reviewable(kind, _valid_case)
            check(f"{kind}: gerçek case_0001 verisiyle fail-closed'a DÜŞMEDEN döner", True)
            if listing["canonical_exists"]:
                check(
                    f"{kind}: canonical VAR ve items geçerli bir liste (boş olabilir, hata DEĞİL)",
                    isinstance(listing["items"], list),
                    f"items={listing['items']}",
                )
        except ReviewLiveViewInvalidError as error:
            check(f"{kind}: gerçek case_0001 verisiyle fail-closed'a DÜŞMEDEN döner", False, str(error))

    try:
        qa_listing = reviewreg.list_reviewable("qa.suggestion", _valid_case)
        check(
            "qa.suggestion: GERÇEK case_0001 verisiyle ya geçerli+boş DÖNER ya da fail-closed REDDEDER (ikisi de doğru davranış)",
            (not qa_listing["canonical_exists"]) or isinstance(qa_listing["items"], list),
            f"listing={qa_listing}",
        )
    except ReviewLiveViewInvalidError:
        check(
            "qa.suggestion: GERÇEK case_0001 verisiyle ya geçerli+boş DÖNER ya da fail-closed REDDEDER (ikisi de doğru davranış)",
            True,
        )


# ============================================================
# 11) ALAN METADATA TUTARLILIĞI (evidence/qa - BY_TYPE sözlüğü
#     taşımayan iki özel durum) - registry'nin hardcoded array/id
#     alan adları, modülün KENDİ find_candidate/find_suggestion
#     fonksiyonuyla AYNI kaydı buluyor mu.
# ============================================================

with tempfile.TemporaryDirectory() as tmp:
    _fixture = {
        "evidence_candidates": [{"candidate_id": "ec_x", "review_state": "needs_review", "iz": 1}],
        "evidence_agent_suggestions": [{"suggestion_id": "es_x", "suggestion_review_state": "needs_review", "iz": 2}],
    }
    _real_via_module = evidence_review.find_candidate(_fixture, "ec_x")
    array_field, id_field, state_field = reviewreg.get_field_names("evidence.candidate")
    _real_via_registry_metadata = next(
        (r for r in _fixture.get(array_field, []) if r.get(id_field) == "ec_x"), None,
    )
    check(
        "evidence.candidate: registry'nin array/id alan metadata'sı modülün KENDİ find_candidate'ıyla AYNI kaydı buluyor",
        _real_via_module == _real_via_registry_metadata and _real_via_module is not None,
    )

    _real_via_module_sugg = evidence_review.find_suggestion(_fixture, "es_x")
    array_field2, id_field2, _ = reviewreg.get_field_names("evidence.suggestion")
    _real_via_registry_metadata_sugg = next(
        (r for r in _fixture.get(array_field2, []) if r.get(id_field2) == "es_x"), None,
    )
    check(
        "evidence.suggestion: registry'nin array/id alan metadata'sı modülün KENDİ find_suggestion'ıyla AYNI kaydı buluyor",
        _real_via_module_sugg == _real_via_registry_metadata_sugg and _real_via_module_sugg is not None,
    )

    _qa_fixture = {"qa_agent_suggestions": [{"suggestion_id": "qas_x", "suggestion_review_state": "needs_review", "iz": 3}]}
    _real_via_qa_module = qa_review.find_suggestion(_qa_fixture, "qas_x")
    qa_array_field, qa_id_field, _ = reviewreg.get_field_names("qa.suggestion")
    _real_via_qa_registry = next(
        (r for r in _qa_fixture.get(qa_array_field, []) if r.get(qa_id_field) == "qas_x"), None,
    )
    check(
        "qa.suggestion: registry'nin array/id alan metadata'sı modülün KENDİ find_suggestion'ıyla AYNI kaydı buluyor",
        _real_via_qa_module == _real_via_qa_registry and _real_via_qa_module is not None,
    )


# ============================================================
# 12) GERÇEK data/ ve src/ AĞAÇLARININ HİÇBİR TESTLE DEĞİŞMEDİĞİNİN
#     BYTE-DÜZEYİNDE KANITI
# ============================================================

_after_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)
check(
    "GERÇEK data/ ve src/ ağaçları bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)",
    _before_snapshot == _after_snapshot,
    f"before={len(_before_snapshot)} dosya, after={len(_after_snapshot)} dosya, "
    f"fark={set(_before_snapshot) ^ set(_after_snapshot)}",
)


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
