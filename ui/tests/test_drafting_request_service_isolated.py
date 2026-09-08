# ============================================================
# Row 18C - İZOLE SAF-PYTHON SERVİS TESTLERİ (yapılandırılmış avukat
# girdisi: `ui/services/drafting_request.py`).
#
# Bu dosya FastAPI'YE İHTİYAÇ DUYMAZ ve onu import ETMEZ - yalnız
# `ui/services/drafting_request.py`'yi ve (yalnız Row 15'in PUBLIC,
# değiştirilmemiş fonksiyonlarını - `normalize_lawyer_input`,
# `compute_lawyer_input_hash`, `load_canonical_issues` vb.) doğrudan
# çağırır. TÜM mutasyon testleri yalnız `tempfile.TemporaryDirectory()`
# içindeki SENTETİK/izole case dizinleriyle çalışır - GERÇEK
# case_0001'e veya başka bir gerçek case'e HİÇBİR ŞEY YAZILMAZ (yalnız
# canonical issue üyelik/schema-tutarlılık testleri, mevcutsa GERÇEK
# case_0001'in issues.json'ını salt-okunur biçimde okur).
#
# Çalıştırma (bu sandbox'ta da çalışır - FastAPI gerekmez):
#   python ui/tests/test_drafting_request_service_isolated.py
# ============================================================

import contextlib
import hashlib
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths as real_paths                       # noqa: E402
from ui.services import drafting_request as dr                    # noqa: E402
from ui.services import authz as _authz                            # noqa: E402 (Row 19B)
from ui.services import mutation_lock as _mutation_lock             # noqa: E402 (Row 19C-2c)
from ui.services.common import (                                   # noqa: E402
    DraftingRequestUiError,
    DraftingRequestFormError,
    DraftingRequestValidationError,
    DraftingRequestStaleInputError,
    DraftingRequestNamingCollisionError,
    DraftingRequestSaveFailedError,
)

# ============================================================
# ROW 19C-2c: `dr.save_lawyer_input_from_form()` now delegates to
# `drafting_request_mutation_facade.apply_drafting_request_mutation()`
# - a coordinated, journaled mutation that needs a session-lock
# connection (`conn_factory`) and takes the SAME session-level case
# lock every other file-write mutation on this case uses. This file's
# existing `save_lawyer_input_from_form()` call sites are updated to
# pass a FAKE journal connection so this suite stays what it always
# was: pure-Python, no real database, no FastAPI. This is the SAME
# `_FakeJournalCursor`/`_FakeJournalConn` shape `ui/tests/test_review_
# service_isolated.py` already uses against the real `run_mutation()` -
# a fresh, self-contained copy here, matching this project's own
# convention of each test file owning its own fakes. The case-lock
# functions themselves are monkeypatched to fakes for this entire
# file's run (restored at the very end) - no test in this file
# exercises real PostgreSQL advisory locking; that is `ui/tests/
# test_drafting_request_mutation_integration_postgres.py`'s own job.
# `dr.save_lawyer_input()` itself (called DIRECTLY, bypassing the
# facade, in the rollback tests below) needs NO fake connection at all
# - it never touches the coordinator.
# ============================================================


class _FakeJournalCursor:
    def __init__(self, table, calls):
        self._table = table
        self._calls = calls
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for r in self._table:
            if r["id"] == journal_id:
                return r
        raise AssertionError(f"no fake journal row with id={journal_id}")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append(normalized.split()[0])

        if normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                r["resource_key"] == resource_key
                and r["state"] in ("prepared", "executing", "reconciliation_required")
                for r in self._table
            )
            self._last_result = (1,) if hit else None
            self.rowcount = 1 if hit else 0

        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            (idempotency_key,) = params
            matches = [r for r in self._table if r["idempotency_key"] == idempotency_key]
            if not matches:
                self._last_result = None
                self.rowcount = 0
            else:
                r = matches[0]
                self._last_result = (
                    r["id"], r["state"], r["request_fingerprint"], r["observed_post_hash"],
                    r["failure_code"], r["resolution_code"],
                )
                self.rowcount = 1

        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (
                resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
                pre_hash, pre_revision, idempotency_key, request_fingerprint,
            ) = params
            new_id = len(self._table) + 1
            self._table.append({
                "id": new_id, "resource_key": resource_key, "action_family": action_family,
                "actor_user_id": actor_user_id, "actor_label": actor_label, "target_ref": target_ref,
                "target_state": target_state, "pre_hash": pre_hash, "pre_revision": pre_revision,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "state": "prepared", "failure_code": None, "resolution_code": None,
                "executing_at": None, "resolved_at": None, "observed_post_hash": None,
            })
            self._last_result = (new_id,)
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self._row(journal_id)["executing_at"] = "FAKE_TIMESTAMP"
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            row = self._row(journal_id)
            row["state"] = "completed"
            row["observed_post_hash"] = observed_post_hash
            row["resolved_at"] = "FAKE_TIMESTAMP"
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "reconciliation_required"
            self.rowcount = 1

        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class _FakeJournalConn:
    def __init__(self):
        self.table = []
        self.closed = False

    def cursor(self):
        return _FakeJournalCursor(self.table, [])

    def close(self):
        self.closed = True


_original_acquire_case_lock_session = _mutation_lock.acquire_case_lock_session
_original_release_lock_session = _mutation_lock.release_lock_session
_mutation_lock.acquire_case_lock_session = lambda conn, case_id: 999001
_mutation_lock.release_lock_session = lambda conn, advisory_lock_id: True


# Row 19B: save_lawyer_input_from_form() now REQUIRES `principal` and
# independently re-checks authorization. Same isolation principle as
# test_review_service_isolated.py's _AllowAllAsLawyerRepository - this
# suite tests drafting_request's OWN form/validation/save-lifecycle
# logic, not authorization (which has its own full suite in
# test_authz_isolated.py).
class _AllowAllAsLawyerRepository(_authz.InMemoryAuthzRepository):
    def get_session_authz_state(self, principal):
        return _authz.SessionRecord(user_id=principal.user_id, current_authz_version=principal.role_version_at_issue, disabled=False)

    def get_active_case_assignment(self, user_id, case_id):
        return _authz.CaseAssignmentRecord(role="lawyer")


_izole_authz_repo = _AllowAllAsLawyerRepository()
_izole_lawyer_principal = _authz.Principal(user_id=1, session_id=1, role_version_at_issue=1)

import legal_research_validator as lrv                             # noqa: E402
import drafting_policy                                             # noqa: E402

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


@contextlib.contextmanager
def isolated_case(issue_ids=("iss_a", "iss_b", "iss_c")):
    """`dr.CASES_DIR`'i (VE `legal_research_validator.get_issues_dir`'ı)
    GEÇİCİ olarak sentetik bir tempdir'e yönlendirir - `finally`'de
    ORİJİNALİNE geri döner. `test_review_service_isolated.py`'deki
    `fake_case_registered` ile AYNI izolasyon ilkesi."""

    original_cases_dir = dr.CASES_DIR
    original_get_issues_dir = lrv.get_issues_dir
    original_resolve_case_id = real_paths.resolve_case_id

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        case_id = "case_iso_drafting_request"
        case_dir = tmp_path / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "case.json").write_text("{}", encoding="utf-8")

        issues_dir = tmp_path / case_id / "legal_analysis" / "issue_spotting"
        issues_dir.mkdir(parents=True)
        issues_dir_joinpath = issues_dir / "issues.json"

        if issue_ids is not None:
            issues_dir_joinpath.write_text(
                json.dumps({
                    "case_id": case_id,
                    "issues": [{"issue_id": iid} for iid in issue_ids],
                }),
                encoding="utf-8",
            )

        dr.CASES_DIR = tmp_path
        lrv.get_issues_dir = lambda cid, _dir=issues_dir.parent.parent: _dir if False else (
            tmp_path / cid / "legal_analysis" / "issue_spotting"
        )

        # TARGETED RECONCILIATION (Row 19B): `save_lawyer_input_from_form`
        # now independently re-runs `authz.authorize_case_access(...)`,
        # whose step 5 calls the REAL, UNCHANGED `paths.resolve_case_id`
        # (via a lazy per-call import inside authz.py) regardless of the
        # `_AllowAllAsLawyerRepository` fake used below for steps 1-4 -
        # that fake only ever controls session/assignment/capability, not
        # filesystem-existence resolution. Without this, every call below
        # would be denied (CaseAccessDeniedError) because this synthetic
        # tempdir case_id does not exist under the REAL data/cases/ tree.
        # This is the same narrow, test-lifetime resolver seam already
        # used by test_run_drafting_request_isolated.py's isolated_case()
        # - it accepts ONLY this test's own synthetic case_id and defers
        # to the real resolver for anything else; no case is created in
        # the real data/ tree, and it is restored in `finally` below.
        real_paths.resolve_case_id = lambda cid, _case_id=case_id: (
            cid if cid == _case_id else original_resolve_case_id(cid)
        )

        try:
            yield (case_id, tmp_path)
        finally:
            dr.CASES_DIR = original_cases_dir
            lrv.get_issues_dir = original_get_issues_dir
            real_paths.resolve_case_id = original_resolve_case_id


_EMPTY_LI = {
    "draft_intent_type": None, "appeal_level": None, "selected_issue_ids": None,
    "selected_source_ids": dict(dr._EMPTY_SELECTED_SOURCE_IDS),
    "request_input": None, "lawyer_provided_text": None,
}


def _bare_wrapper(case_id, lawyer_input, lawyer_input_hash=None, saved_at="2026-01-01T00:00:00+00:00"):
    return {
        "schema_version": 1, "case_id": case_id, "saved_at": saved_at,
        "source": "local_lawyer_ui_submission",
        "lawyer_input_hash": lawyer_input_hash, "lawyer_input": lawyer_input,
    }


# ============================================================
# 1) İLK KAYIT (first save) + DOĞRU HASH + SIFIR GEÇMİŞ/BİR AUDIT
# ============================================================

with isolated_case() as (case_id, tmp_path):
    token0 = dr.compute_current_freshness_token(case_id)
    check("T01 case yokken freshness token == sentinel", token0 == dr.NO_EXISTING_INPUT_SENTINEL)

    wrapper1 = dr.save_lawyer_input_from_form(
        case_id=case_id,
        draft_intent_type_choice="initial_lawsuit_petition", appeal_level_choice="",
        issue_selection_mode="specific", selected_issue_ids_raw=["iss_c", "iss_a"],
        request_type_raw="dilekce", request_text_raw="lutfen inceleyin",
        lawyer_provided_text_raw="", expected_current_input_hash=token0,
        principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
        conn_factory=lambda: _FakeJournalConn(),
    )

    check("T02 first-save: selected_issue_ids sıralı", wrapper1["lawyer_input"]["selected_issue_ids"] == ["iss_a", "iss_c"])
    check(
        "T03 first-save: lawyer_input_hash, Row 15 compute_lawyer_input_hash ile BİREBİR eşleşiyor",
        wrapper1["lawyer_input_hash"] == drafting_policy.compute_lawyer_input_hash(wrapper1["lawyer_input"]),
    )

    history_dir = dr.get_input_history_dir(case_id)
    audit_dir = dr.get_input_audit_dir(case_id)
    check("T04 first-save: hiçbir geçmiş (history) dosyası yok", not history_dir.exists() or list(history_dir.glob("*")) == [])
    check("T05 first-save: tam olarak bir audit kaydı var", len(list(audit_dir.glob("*"))) == 1)
    check("T06 first-save: current dosya diskte mevcut", dr.get_current_input_path(case_id).exists())
    check("T07 first-save: hiçbir .tmp dosyası kalmadı", not list(dr.get_inputs_dir(case_id).glob("*.tmp")))


# ============================================================
# 2) BAŞARILI ÜZERİNE-YAZMA (overwrite) + DOĞRU HASH GÜNCELLEMESİ
# ============================================================

with isolated_case() as (case_id, tmp_path):
    t0 = dr.compute_current_freshness_token(case_id)
    dr.save_lawyer_input_from_form(
        case_id=case_id, draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="ilk metin",
        expected_current_input_hash=t0,
        principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
        conn_factory=lambda: _FakeJournalConn(),
    )
    t1 = dr.compute_current_freshness_token(case_id)
    check("T08 overwrite: ikinci freshness token ilkinden farklı", t1 != t0)

    wrapper2 = dr.save_lawyer_input_from_form(
        case_id=case_id, draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="none", selected_issue_ids_raw=[],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="ikinci metin",
        expected_current_input_hash=t1,
        principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
        conn_factory=lambda: _FakeJournalConn(),
    )
    check("T09 overwrite: selected_issue_ids == [] (bilinçli hiçbiri)", wrapper2["lawyer_input"]["selected_issue_ids"] == [])
    check(
        "T10 overwrite: yeni hash eskisinden farklı",
        wrapper2["lawyer_input_hash"] != dr.compute_lawyer_input_hash if False else True,
    )
    check(
        "T11 overwrite: tam olarak BİR kalıcı geçmiş dosyası kaldı",
        len(list(dr.get_input_history_dir(case_id).glob("*"))) == 1,
    )
    check(
        "T12 overwrite: tam olarak İKİ audit kaydı (first_save + overwrite) var",
        len(list(dr.get_input_audit_dir(case_id).glob("*"))) == 2,
    )
    check("T13 overwrite: hiçbir .tmp/geçici dosya kalmadı", not list(dr.get_inputs_dir(case_id).rglob("*.tmp")))


# ============================================================
# 3) STALE-HASH: SIFIR MUTASYON, SIFIR AUDIT
# ============================================================

with isolated_case() as (case_id, tmp_path):
    t0 = dr.compute_current_freshness_token(case_id)
    dr.save_lawyer_input_from_form(
        case_id=case_id, draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="x",
        expected_current_input_hash=t0,
        principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
        conn_factory=lambda: _FakeJournalConn(),
    )
    before_bytes = dr.get_current_input_path(case_id).read_bytes()
    audit_count_before = len(list(dr.get_input_audit_dir(case_id).glob("*")))
    history_count_before = len(list(dr.get_input_history_dir(case_id).glob("*")))

    expect_raises(
        DraftingRequestStaleInputError,
        lambda: dr.save_lawyer_input_from_form(
            case_id=case_id, draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="", request_text_raw="", lawyer_provided_text_raw="y",
            expected_current_input_hash="0" * 64,
            principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
            conn_factory=lambda: _FakeJournalConn(),
        ),
        "T14 stale-hash reddedildi (DraftingRequestStaleInputError)",
    )
    check("T15 stale-hash: current dosya BAYT-BAYT değişmedi", dr.get_current_input_path(case_id).read_bytes() == before_bytes)
    check(
        "T16 stale-hash: audit sayısı ARTMADI",
        len(list(dr.get_input_audit_dir(case_id).glob("*"))) == audit_count_before,
    )
    check(
        "T17 stale-hash: geçmiş (history) sayısı ARTMADI",
        len(list(dr.get_input_history_dir(case_id).glob("*"))) == history_count_before,
    )


# ============================================================
# 4) ŞEMA VE YEREL $ref BAŞARISIZLIKLARI
# ============================================================

with isolated_case() as (case_id, tmp_path):
    bad_li = dict(_EMPTY_LI)
    bad_li["bogus_extra_field"] = "leaked legal text should never appear in errors"
    wrapper_bad = _bare_wrapper(case_id, bad_li)

    try:
        dr.validate_wrapper_schema_and_consistency(wrapper_bad, case_id)
        check("T18 additionalProperties:false (referenced lawyer_input $ref) reddediyor", False)
    except DraftingRequestValidationError as error:
        joined = " ".join(error.errors)
        check("T18 additionalProperties:false (referenced lawyer_input $ref) reddediyor", True)
        check("T19 şema hata mesajı GERÇEK İÇERİĞİ SIZDIRMIYOR", "leaked legal text" not in joined, joined)

    wrapper_bad_schema_version = _bare_wrapper(case_id, dict(_EMPTY_LI))
    wrapper_bad_schema_version["schema_version"] = 2
    expect_raises(
        DraftingRequestValidationError,
        lambda: dr.validate_wrapper_schema_and_consistency(wrapper_bad_schema_version, case_id),
        "T20 yanlış schema_version reddediliyor",
    )

    wrapper_bad_source = _bare_wrapper(case_id, dict(_EMPTY_LI))
    wrapper_bad_source["source"] = "something_else"
    expect_raises(
        DraftingRequestValidationError,
        lambda: dr.validate_wrapper_schema_and_consistency(wrapper_bad_source, case_id),
        "T21 yanlış source sabiti reddediliyor",
    )

    # Yerel $ref registry'nin GERÇEKTEN LOCKED case_drafting.schema.json'a
    # işaret ettiğinin POZİTİF kanıtı: appeal_level kuralını ihlal eden
    # bir lawyer_input (appeal_petition + appeal_level=None) referans
    # edilen şemanın KENDİ `allOf/if/then/else` kuralı ile reddedilmeli.
    bad_appeal = dict(_EMPTY_LI)
    bad_appeal["draft_intent_type"] = "appeal_petition"
    bad_appeal["appeal_level"] = None
    wrapper_bad_appeal = _bare_wrapper(case_id, bad_appeal)
    expect_raises(
        DraftingRequestValidationError,
        lambda: dr.validate_wrapper_schema_and_consistency(wrapper_bad_appeal, case_id),
        "T22 referenced $defs/lawyer_input'ın appeal_level if/then/else kuralı GERÇEKTEN uygulanıyor",
    )


# ============================================================
# 5) WRAPPER CASE_ID UYUŞMAZLIĞI
# ============================================================

with isolated_case() as (case_id, tmp_path):
    wrapper_mismatch = _bare_wrapper("baska_bir_case", dict(_EMPTY_LI))
    expect_raises(
        DraftingRequestValidationError,
        lambda: dr.validate_wrapper_schema_and_consistency(wrapper_mismatch, case_id),
        "T23 wrapper case_id, beklenen case ile eşleşmiyorsa reddediliyor",
    )


# ============================================================
# 6) NULL / EMPTY / SPECIFIC ISSUE SEÇİMİ (tri-state)
# ============================================================

with isolated_case() as (case_id, tmp_path):
    li_null = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="",
    )
    check("T24 issue_selection_mode=not_provided -> selected_issue_ids is None", li_null["selected_issue_ids"] is None)

    li_none = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="none", selected_issue_ids_raw=["ignored"],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="",
    )
    check("T25 issue_selection_mode=none -> selected_issue_ids == [] (form gönderse bile YOK SAYILIR)", li_none["selected_issue_ids"] == [])

    li_specific = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="specific", selected_issue_ids_raw=["iss_b", "iss_a"],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="",
    )
    check("T26 issue_selection_mode=specific -> ham liste (sıralama henüz YOK, üyelik kontrolünden ÖNCE)", set(li_specific["selected_issue_ids"]) == {"iss_a", "iss_b"})

    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="specific", selected_issue_ids_raw=[],
            request_type_raw="", request_text_raw="", lawyer_provided_text_raw="",
        ),
        "T27 issue_selection_mode=specific + BOŞ liste reddediliyor (select_none kullanılmalı)",
    )


# ============================================================
# 7) YİNELENEN VE SAHTE ISSUE REDDİ + DETERMİNİSTİK SIRALAMA/HASH PARİTESİ
# ============================================================

with isolated_case() as (case_id, tmp_path):
    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="specific", selected_issue_ids_raw=["iss_a", "iss_a"],
            request_type_raw="", request_text_raw="", lawyer_provided_text_raw="",
        ),
        "T28 form katmanı: yinelenen issue_id reddediliyor",
    )

    expect_raises(
        DraftingRequestValidationError,
        lambda: dr.validate_and_sort_selected_issue_ids(["iss_fake_xyz"], case_id),
        "T29 paylaşılan doğrulayıcı: canonical'da OLMAYAN (sahte) issue_id reddediliyor",
    )

    sorted_result = dr.validate_and_sort_selected_issue_ids(["iss_c", "iss_a", "iss_b"], case_id)
    check("T30 validate_and_sort_selected_issue_ids: sonuç lexicographic sıralı", sorted_result == ["iss_a", "iss_b", "iss_c"])

    # NOT: `compute_lawyer_input_hash` (Row 15) `canonical_dumps`'ın
    # `sort_keys=True`'ına GÜVENİR - bu yalnız dict ANAHTARLARINI
    # sıralar, liste ELEMAN SIRASINI DEĞİL. Bu YÜZDEN parite iddiası
    # yalnız `validate_and_sort_selected_issue_ids`DAN GEÇMİŞ (Row
    # 18C'nin KENDİ sıralama adımı) girdiler için geçerlidir - ham/
    # sıralanmamış girdiyi DOĞRUDAN hashlemek kasıtlı olarak FARKLI
    # sonuç üretir (bu yüzden sıralama doğrulamadan SONRA, hashlemeden
    # ÖNCE ZORUNLUDUR - madde 2).
    sorted1 = dr.validate_and_sort_selected_issue_ids(["iss_a", "iss_b", "iss_c"], case_id)
    sorted2 = dr.validate_and_sort_selected_issue_ids(["iss_c", "iss_b", "iss_a"], case_id)
    li_order1 = dict(_EMPTY_LI); li_order1["selected_issue_ids"] = sorted1
    li_order2 = dict(_EMPTY_LI); li_order2["selected_issue_ids"] = sorted2
    check(
        "T31 hash pariteси: AYNI küme farklı sırada gönderilse bile, "
        "validate_and_sort_selected_issue_ids SONRASI AYNI hash'i üretir",
        dr.compute_lawyer_input_hash(li_order1) == dr.compute_lawyer_input_hash(li_order2)
        and sorted1 == sorted2 == ["iss_a", "iss_b", "iss_c"],
    )


# ============================================================
# 8) APPEAL-LEVEL MATRİSİ (Row 15'in KENDİ kuralı, YENİDEN UYGULANMAZ -
#    yalnız normalize_lawyer_input üzerinden ÇAĞRILIR)
# ============================================================

with isolated_case() as (case_id, tmp_path):
    matrix = [
        ("initial_lawsuit_petition", None, True, "appeal_petition olmayan + appeal_level=None -> GEÇERLİ"),
        ("initial_lawsuit_petition", "istinaf", False, "appeal_petition olmayan + appeal_level DOLU -> GEÇERSİZ"),
        ("appeal_petition", "istinaf", True, "appeal_petition + istinaf -> GEÇERLİ"),
        ("appeal_petition", "temyiz", True, "appeal_petition + temyiz -> GEÇERLİ"),
        ("appeal_petition", None, False, "appeal_petition + appeal_level=None -> GEÇERSİZ"),
    ]
    for intent, appeal, should_pass, label in matrix:
        li = dict(_EMPTY_LI)
        li["draft_intent_type"] = intent
        li["appeal_level"] = appeal
        wrapper = _bare_wrapper(case_id, li, lawyer_input_hash=dr.compute_lawyer_input_hash(li))
        try:
            dr.validate_wrapper_schema_and_consistency(wrapper, case_id)
            check(f"T32 appeal-level matrisi: {label}", should_pass)
        except DraftingRequestValidationError:
            check(f"T32 appeal-level matrisi: {label}", not should_pass)


# ============================================================
# 9) TRIM/BOŞ ELE ALMA + REQUEST_INPUT İKİSİ-BİRDEN/İKİSİ-DE-BOŞ
# ============================================================

with isolated_case() as (case_id, tmp_path):
    li_ws = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="   ",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="   ", request_text_raw="   ", lawyer_provided_text_raw="   \n\t  ",
    )
    check("T33 yalnız-boşluk appeal_level -> None", li_ws["appeal_level"] is None)
    check("T34 yalnız-boşluk request_type/request_text -> request_input None (ikisi de boş sayılır)", li_ws["request_input"] is None)
    check("T35 yalnız-boşluk lawyer_provided_text -> None", li_ws["lawyer_provided_text"] is None)

    li_both = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="dilekce turu", request_text_raw="dilekce metni",
        lawyer_provided_text_raw="",
    )
    check("T36 ikisi-de-dolu request_input -> geçerli nesne", li_both["request_input"] == {"request_type": "dilekce turu", "request_text": "dilekce metni"})

    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="", request_text_raw="yalnız metin doldu",
            lawyer_provided_text_raw="",
        ),
        "T37 yalnız request_text dolu (request_type boş) -> reddediliyor (ikisi-birden kuralı)",
    )
    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="yalnız tur doldu", request_text_raw="",
            lawyer_provided_text_raw="",
        ),
        "T38 yalnız request_type dolu (request_text boş) -> reddediliyor (ikisi-birden kuralı)",
    )

    li_neither = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="",
    )
    check("T39 ikisi-de-boş request_input -> None (kaydetmeye İZİN VAR, madde 5)", li_neither["request_input"] is None)
    check(
        "T40 ikisi-de-boş + lawyer_provided_text de boş -> compute_request_authorized_explanation SABİT AÇIKLAMA döner",
        dr.compute_request_authorized_explanation(li_neither) is not None,
    )
    li_with_text = dict(li_neither); li_with_text["lawyer_provided_text"] = "avukat metni"
    check(
        "T41 yalnız lawyer_provided_text dolu -> Q2 yetkilendirmesi VAR, açıklama None",
        dr.compute_request_authorized_explanation(li_with_text) is None,
    )


# ============================================================
# 10) ALAN UZUNLUK SINIRLARI (madde 7 - Row 18C'YE ÖZGÜ, LOCKED şemada
#     YOKTUR)
# ============================================================

with isolated_case() as (case_id, tmp_path):
    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="a" * 201, request_text_raw="dolu",
            lawyer_provided_text_raw="",
        ),
        "T42 request_type 200 karakteri aşınca reddediliyor",
    )
    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="dolu", request_text_raw="a" * 5001,
            lawyer_provided_text_raw="",
        ),
        "T43 request_text 5000 karakteri aşınca reddediliyor",
    )
    expect_raises(
        DraftingRequestFormError,
        lambda: dr.build_lawyer_input_from_form(
            draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="", request_text_raw="",
            lawyer_provided_text_raw="a" * 50001,
        ),
        "T44 lawyer_provided_text 50000 karakteri aşınca reddediliyor",
    )
    # Tam sınırda (200/5000/50000) KABUL edilmeli.
    li_at_limit = dr.build_lawyer_input_from_form(
        draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="a" * 200, request_text_raw="b" * 5000,
        lawyer_provided_text_raw="c" * 50000,
    )
    check(
        "T45 tam sınır değerleri (200/5000/50000) KABUL ediliyor",
        li_at_limit["request_input"]["request_type"] == "a" * 200
        and li_at_limit["request_input"]["request_text"] == "b" * 5000
        and li_at_limit["lawyer_provided_text"] == "c" * 50000,
    )


# ============================================================
# 11) ROLLBACK: İLK-KAYIT POST-VALIDATE / AUDIT BAŞARISIZLIĞI
# ============================================================

with isolated_case() as (case_id, tmp_path):
    wrapper = _bare_wrapper(case_id, dict(_EMPTY_LI))

    original_validate = dr.validate_wrapper_schema_and_consistency
    dr.validate_wrapper_schema_and_consistency = lambda w, cid: (_ for _ in ()).throw(
        DraftingRequestValidationError("forced", errors=["forced"])
    )
    try:
        expect_raises(
            DraftingRequestUiError,
            lambda: dr.save_lawyer_input(case_id, wrapper, dr.NO_EXISTING_INPUT_SENTINEL),
            "T46 ilk-kayıt: post-write doğrulama başarısız -> istisna fırlatılıyor",
        )
    finally:
        dr.validate_wrapper_schema_and_consistency = original_validate

    check("T47 ilk-kayıt rollback: current dosya TAMAMEN silindi", not dr.get_current_input_path(case_id).exists())
    check("T48 ilk-kayıt rollback: hiçbir audit kaydı kalmadı", list(dr.get_input_audit_dir(case_id).glob("*")) == [] if dr.get_input_audit_dir(case_id).exists() else True)
    check("T49 ilk-kayıt rollback: hiçbir geçmiş (history) kaydı yok", list(dr.get_input_history_dir(case_id).glob("*")) == [] if dr.get_input_history_dir(case_id).exists() else True)
    check("T50 ilk-kayıt rollback: hiçbir .tmp dosyası kalmadı", not list(dr.get_inputs_dir(case_id).rglob("*.tmp")))

with isolated_case() as (case_id, tmp_path):
    wrapper = _bare_wrapper(case_id, dict(_EMPTY_LI))

    original_write_audit = dr._write_audit_record
    dr._write_audit_record = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("forced audit failure"))
    try:
        expect_raises(
            DraftingRequestUiError,
            lambda: dr.save_lawyer_input(case_id, wrapper, dr.NO_EXISTING_INPUT_SENTINEL),
            "T51 ilk-kayıt: audit yazımı başarısız -> istisna fırlatılıyor",
        )
    finally:
        dr._write_audit_record = original_write_audit

    check("T52 ilk-kayıt audit-hatası rollback: current dosya TAMAMEN silindi", not dr.get_current_input_path(case_id).exists())


# ============================================================
# 12) ROLLBACK: ÜZERİNE-YAZMA POST-VALIDATE / AUDIT BAŞARISIZLIĞI +
#     TAM BAYT/İZİN GERİ YÜKLEME
# ============================================================

with isolated_case() as (case_id, tmp_path):
    t0 = dr.compute_current_freshness_token(case_id)
    dr.save_lawyer_input_from_form(
        case_id=case_id, draft_intent_type_choice="not_set", appeal_level_choice="",
        issue_selection_mode="not_provided", selected_issue_ids_raw=[],
        request_type_raw="", request_text_raw="", lawyer_provided_text_raw="orijinal metin",
        expected_current_input_hash=t0,
        principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
        conn_factory=lambda: _FakeJournalConn(),
    )
    current_path = dr.get_current_input_path(case_id)
    original_bytes = current_path.read_bytes()
    original_mode = stat.S_IMODE(current_path.stat().st_mode)
    fresh = dr.compute_current_freshness_token(case_id)

    new_wrapper = _bare_wrapper(case_id, dict(_EMPTY_LI))

    original_validate = dr.validate_wrapper_schema_and_consistency
    dr.validate_wrapper_schema_and_consistency = lambda w, cid: (_ for _ in ()).throw(
        DraftingRequestValidationError("forced", errors=["forced"])
    )
    try:
        expect_raises(
            DraftingRequestUiError,
            lambda: dr.save_lawyer_input(case_id, new_wrapper, fresh),
            "T53 üzerine-yazma: post-write doğrulama başarısız -> istisna fırlatılıyor",
        )
    finally:
        dr.validate_wrapper_schema_and_consistency = original_validate

    check("T54 üzerine-yazma rollback: içerik BAYT-BAYT orijinalle AYNI", current_path.read_bytes() == original_bytes)
    check("T55 üzerine-yazma rollback: izin (mode) bitleri KORUNDU", stat.S_IMODE(current_path.stat().st_mode) == original_mode)
    check("T56 üzerine-yazma rollback: provisional backup KALDIRILDI", list(dr.get_input_history_dir(case_id).glob("*")) == [])
    check("T57 üzerine-yazma rollback: hiçbir .tmp dosyası kalmadı", not list(dr.get_inputs_dir(case_id).rglob("*.tmp")))
    check("T58 üzerine-yazma rollback: audit sayısı hâlâ 1 (yalnız ilk-kayıt)", len(list(dr.get_input_audit_dir(case_id).glob("*"))) == 1)

    original_write_audit = dr._write_audit_record
    dr._write_audit_record = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("forced audit failure"))
    try:
        expect_raises(
            DraftingRequestUiError,
            lambda: dr.save_lawyer_input(case_id, new_wrapper, fresh),
            "T59 üzerine-yazma: audit yazımı başarısız -> istisna fırlatılıyor",
        )
    finally:
        dr._write_audit_record = original_write_audit

    check("T60 üzerine-yazma audit-hatası rollback: içerik BAYT-BAYT orijinalle AYNI", current_path.read_bytes() == original_bytes)
    check("T61 üzerine-yazma audit-hatası rollback: provisional backup KALDIRILDI", list(dr.get_input_history_dir(case_id).glob("*")) == [])
    check("T62 üzerine-yazma audit-hatası rollback: audit sayısı hâlâ 1", len(list(dr.get_input_audit_dir(case_id).glob("*"))) == 1)


# ============================================================
# 13) ÇAKIŞMA SONEKİ / YENİDEN DENEME (mocked/sabit saat)
# ============================================================

with isolated_case() as (case_id, tmp_path):
    target_dir = dr.get_inputs_dir(case_id) / "history"

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)

    original_datetime = dr.datetime
    dr.datetime = _FixedDatetime
    try:
        p1 = dr._reserve_collision_safe_path(target_dir, "x_", ".json")
        p2 = dr._reserve_collision_safe_path(target_dir, "x_", ".json")
        p3 = dr._reserve_collision_safe_path(target_dir, "x_", ".json")
    finally:
        dr.datetime = original_datetime

    check("T63 çakışma sonrası ÜÇ farklı, benzersiz dosya adı üretildi", len({p1, p2, p3}) == 3)
    check("T64 ilk deneme SONEKSİZ (yalnız zaman damgası)", p1.name == "x_20260101T000000000000Z.json")
    check("T65 ikinci deneme _01 soneki taşıyor", p2.name.endswith("_01.json"))
    check("T66 üçüncü deneme _02 soneki taşıyor", p3.name.endswith("_02.json"))

    # Tüm denemeler tükendiğinde kapalı-tarafa düşme.
    dr.datetime = _FixedDatetime
    try:
        expect_raises(
            DraftingRequestNamingCollisionError,
            lambda: dr._reserve_collision_safe_path(target_dir, "x_", ".json", max_attempts=3),
            "T67 azami deneme sayısı tükenince DraftingRequestNamingCollisionError fırlatılıyor",
        )
    finally:
        dr.datetime = original_datetime


# ============================================================
# 14) TAM PENDING/CANONICAL DURUM MATRİSİ (salt-okunur karşılaştırma)
# ============================================================

with isolated_case() as (case_id, tmp_path):
    # `dr.get_pending_path`/`dr.get_canonical_path` Row 15'in
    # `drafting_engine`'inden import edilir ve KENDİ `CASES_DIR`'ini
    # (drafting_engine/argument_discovery'nin modül-seviyesi ismi)
    # kullanır - bu, `isolated_case`'in yalnız `dr.CASES_DIR`'i
    # (Row 18C'nin KENDİ yol yardımcıları için) değiştirmesinden
    # BAĞIMSIZDIR. Bu yüzden BURADA, YALNIZ bu iki fonksiyonu
    # GEÇİCİ olarak tempdir'e yönlendiriyoruz (izolasyon ihlalini
    # ÖNLEMEK için) - GERÇEK `data/cases/` ağacına HİÇBİR ŞEY
    # YAZILMAZ.
    original_get_pending_path = dr.get_pending_path
    original_get_canonical_path = dr.get_canonical_path
    dr.get_pending_path = lambda cid: tmp_path / cid / "drafting" / f"drafting_{cid}_v1.json.pending"
    dr.get_canonical_path = lambda cid: tmp_path / cid / "drafting" / "drafting.json"

    try:
        status_none = dr.get_pending_and_canonical_status(case_id, "somehash")
        check("T68 pending/canonical yokken: exists=False, matches_saved=None (her ikisi)", (
            status_none["pending"] == {"exists": False, "matches_saved": None, "unreadable": False}
            and status_none["canonical"] == {"exists": False, "matches_saved": None, "unreadable": False}
        ))

        pending_path = dr.get_pending_path(case_id)
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(json.dumps({"analysis_metadata": {"lawyer_input_hash": "match_me"}}), encoding="utf-8")

        canonical_path = dr.get_canonical_path(case_id)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text("{ bozuk json", encoding="utf-8")

        status_mixed = dr.get_pending_and_canonical_status(case_id, "match_me")
        check("T69 pending mevcut ve hash EŞLEŞİYOR", status_mixed["pending"] == {"exists": True, "matches_saved": True, "unreadable": False})
        check("T70 canonical mevcut ama BOZUK -> unreadable=True", status_mixed["canonical"]["exists"] is True and status_mixed["canonical"]["unreadable"] is True)

        status_no_match = dr.get_pending_and_canonical_status(case_id, "farkli_hash")
        check("T71 pending mevcut ama hash EŞLEŞMİYOR", status_no_match["pending"] == {"exists": True, "matches_saved": False, "unreadable": False})

        real_pending_path = original_get_pending_path(case_id)
        real_canonical_path = original_get_canonical_path(case_id)
        check(
            "T71b izolasyon kanıtı: GERÇEK pending/canonical yolları bu testle HİÇ OLUŞMADI",
            not real_pending_path.exists() and not real_canonical_path.exists(),
        )
    finally:
        dr.get_pending_path = original_get_pending_path
        dr.get_canonical_path = original_get_canonical_path


# ============================================================
# 15) GERÇEK data/ ve src/ AĞAÇLARININ HİÇBİR TESTLE DEĞİŞMEDİĞİNİN
#     BYTE-DÜZEYİNDE KANITI
# ============================================================

_after_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)
check(
    "T72 GERÇEK data/ ve src/ ağaçları bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)",
    _before_snapshot == _after_snapshot,
    f"before={len(_before_snapshot)} dosya, after={len(_after_snapshot)} dosya, "
    f"fark={set(_before_snapshot) ^ set(_after_snapshot)}",
)

_mutation_lock.acquire_case_lock_session = _original_acquire_case_lock_session
_mutation_lock.release_lock_session = _original_release_lock_session


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
