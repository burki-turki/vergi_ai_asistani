# ============================================================
# ADIM 10 B YOLU - src/manual_fact_entry_engine.py ISOLATED TESTS
# (exact-scope §5.1: E-P1..E-P5, E-N1..E-N11).
#
# Saf Python; PostgreSQL yok, ağ yok, Python alt süreci yok. Validator
# PASS kanıtı (E-P1) case_0001'in BİR KOPYASI üzerinde, repo DIŞINDAKİ
# bir tempdir'de yapılır - gerçek data/ ağacı hiç yazılmaz (sonunda
# bayt-bayt karşılaştırılır).
#
# Run: python ui/tests/test_manual_fact_entry_engine_isolated.py
# ============================================================

import ast
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:  # noqa: BLE001
        check(label, False, f"{detail} - wrong exception {type(error).__name__}: {error!r}")
        return None
    check(label, False, f"{detail} - no exception raised")
    return None


REAL_DATA_DIR = REPO_ROOT / "data"


def snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


_data_before = snapshot_data_tree()

# ============================================================
# E-N8 (L-2) - AST taraması: giriş noktası yok, ağ/alt süreç/ui importu
# yok. Modül import EDİLMEDEN önce kaynak üzerinden.
# ============================================================

ENGINE_PATH = SRC_DIR / "manual_fact_entry_engine.py"
_tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
_forbidden_roots = {"anthropic", "httpx", "dotenv", "openai", "socket", "subprocess", "requests", "ui"}
_import_roots = set()
for node in ast.walk(_tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            _import_roots.add(alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            _import_roots.add(node.module.split(".")[0])
check(
    "E-N8a engine imports none of anthropic/httpx/dotenv/openai/socket/subprocess/requests/ui",
    not (_import_roots & _forbidden_roots), f"roots={sorted(_import_roots)}",
)
check(
    "E-N8a positive control: the AST scan genuinely sees the engine's real imports",
    {"hashlib", "json", "jsonschema", "case_fact_validator", "fact_approval", "path_containment"} <= _import_roots,
    f"roots={sorted(_import_roots)}",
)
check(
    "E-N8b engine has no module-level `def main`",
    not any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in _tree.body),
)


def _is_name_main_compare(node):
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [n for n in ast.walk(node.test) if isinstance(n, ast.Name)]
    return any(n.id == "__name__" for n in names)


check(
    "E-N8c engine has no `if __name__ ...` block",
    not any(_is_name_main_compare(n) for n in ast.walk(_tree)),
)

# Zehirli stub'lar + sayan (engellemeyen) socket audit hook'u: motor
# import edilip TAM bir değerlendirme + yazım yapılırken.
_POISON_NAMES = ("anthropic", "httpx", "openai", "dotenv", "requests")
_poison_hits = []


class _PoisonModule(types.ModuleType):
    def __getattr__(self, item):
        _poison_hits.append((self.__name__, item))
        raise AssertionError(f"poisoned module {self.__name__} accessed: {item}")


_saved_modules = {name: sys.modules.get(name) for name in _POISON_NAMES}
for _name in _POISON_NAMES:
    sys.modules[_name] = _PoisonModule(_name)

_socket_events = []
_socket_armed = [False]


def _socket_counter(event, args):
    if _socket_armed[0] and event.startswith("socket."):
        _socket_events.append(event)


sys.addaudithook(_socket_counter)

# Pozitif kontrol: hook gerçekten socket olaylarını görüyor (bağlantı
# kurulmadan yalnız soket nesnesi oluşturulur).
_socket_armed[0] = True
_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_probe.close()
_socket_armed[0] = False
check(
    "E-N8d positive control: the counting audit hook genuinely observes socket.* events",
    len(_socket_events) >= 1, f"events={_socket_events!r}",
)
_socket_events.clear()

_socket_armed[0] = True
import manual_fact_entry_engine as mfe  # noqa: E402
import case_fact_validator  # noqa: E402
import fact_approval  # noqa: E402
import timeline_engine  # noqa: E402

# ============================================================
# Fixture (tempdir, repo dışı).
# ============================================================

CASE_ID = "case_0001"
DOC = "ihbarname_001"
DATE = "2026-02-10"
EXCERPT = "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir."

INPUT_SCHEMA_BYTES = mfe.INPUT_SCHEMA_PATH.read_bytes()
INPUT_SCHEMA = mfe.load_input_schema(INPUT_SCHEMA_BYTES)
FACT_SCHEMA = json.loads(mfe.FACT_SCHEMA_PATH.read_bytes().decode("utf-8"))
REAL_TEXT_BYTES = (REAL_DATA_DIR / "cases" / CASE_ID / "documents" / DOC / "extracted" / f"{DOC}.txt").read_bytes()
REAL_DOC = json.loads((REAL_DATA_DIR / "cases" / CASE_ID / "documents" / DOC / "document.json").read_bytes())
ELIGIBLE_DOC = json.loads(json.dumps(REAL_DOC))
ELIGIBLE_DOC["file"]["page_count"] = 2
ELIGIBLE_DOC_BYTES = json.dumps(ELIGIBLE_DOC, ensure_ascii=False, indent=2).encode("utf-8")
DIGEST = hashlib.sha256(b"synthetic-manifest").hexdigest()


def make_input(**overrides):
    fact = {"role": "notification_date", "date": DATE, "page": 1, "text_excerpt": EXCERPT}
    fact.update(overrides.pop("fact", {}))
    data = {"schema_version": 1, "case_id": CASE_ID, "document_id": DOC, "facts": [fact]}
    data.update(overrides)
    return data


def input_bytes(data):
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def evaluate(**kw):
    args = dict(
        case_id=CASE_ID, document_id=DOC, input_digest=DIGEST,
        manual_input_bytes=input_bytes(make_input()), input_schema_bytes=INPUT_SCHEMA_BYTES,
        document_bytes=ELIGIBLE_DOC_BYTES, source_text_bytes=REAL_TEXT_BYTES, fact_schema=FACT_SCHEMA,
    )
    args.update(kw)
    return mfe.evaluate_candidate(**args)


_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_mfe_iso_"))
try:
    case_dir = _tmp_root / CASE_ID
    shutil.copytree(REAL_DATA_DIR / "cases" / CASE_ID, case_dir)
    (case_dir / "documents" / DOC / "document.json").write_bytes(ELIGIBLE_DOC_BYTES)
    ext_dir = case_dir / "documents" / DOC / "extractions"
    for p in list(ext_dir.iterdir()):
        if p.is_file():
            p.unlink()
    reviews_dir = ext_dir / mfe.GENERATION_REVIEWS_DIRNAME

    # ========================================================
    # E-P1 / E-P2 / E-P3
    # ========================================================
    result = evaluate()
    extraction = result["extraction"]
    check(
        "E-P1a method=manual; provider/model/prompt_version/run_at all null",
        extraction["extractor"] == {
            "method": "manual", "provider": None, "model": None,
            "extractor_version": "manual_fact_entry_v1", "prompt_version": None, "run_at": None,
        },
        f"{extraction['extractor']!r}",
    )
    probe_path = ext_dir / "probe_facts.json"
    probe_path.write_bytes(result["frozen_pending_bytes"])
    validation = case_fact_validator.validate_fact_extraction(probe_path, raise_on_error=True)
    check("E-P1b real case_fact_validator PASSes the frozen candidate (valid=True, 0 errors)",
          validation["valid"] is True and validation["errors"] == [], f"{validation!r}")
    probe_path.unlink()

    result2 = evaluate()
    check("E-P2a determinism: two builds are byte-identical",
          result2["frozen_pending_bytes"] == result["frozen_pending_bytes"])
    check(
        "E-P2b ids carry no timestamp: extraction_id/fact_id derive only from document_id + input_digest[:12]",
        extraction["extraction_id"] == f"extract_{DOC}_manual_v1_{DIGEST[:12]}"
        and extraction["facts"][0]["fact_id"] == f"fact_{DOC}_manual_v1_{DIGEST[:12]}_001",
    )
    other = evaluate(input_digest=hashlib.sha256(b"other").hexdigest())
    check("E-P2c a different input_digest yields different ids/bytes",
          other["frozen_pending_bytes"] != result["frozen_pending_bytes"])
    check("E-P2d frozen bytes are LF-only with a single trailing newline",
          b"\r" not in result["frozen_pending_bytes"] and result["frozen_pending_bytes"].endswith(b"}\n"))

    fact = extraction["facts"][0]
    check(
        "E-P3 fact fields match exact-scope §4 exactly",
        fact == {
            "fact_id": f"fact_{DOC}_manual_v1_{DIGEST[:12]}_001",
            "fact_kind": "date_fact",
            "statement": "Tebliğ Tarihi: 10.02.2026",
            "normalized_statement": None,
            "extraction_basis": "explicit_text",
            "attributed_party_id": None,
            "attributed_actor_label": None,
            "source": {"page": 1, "section": None, "paragraph": None, "text_excerpt": EXCERPT},
            "structured_values": [{
                "value_type": "date", "label": "Tebliğ Tarihi", "string_value": None,
                "number_value": None, "date_value": DATE, "money_value": None, "reference_value": None,
            }],
            "related_party_ids": [], "related_document_ids": [], "related_dispute_item_ids": [],
            "confidence": 1.0, "verification_state": "unverified",
            "notes": "Manuel giriş (manual_fact_entry_v1); confidence model güveni değildir; verification değildir.",
        },
        f"{fact!r}",
    )
    check("E-P3b status=completed, warnings=[]",
          extraction["status"] == "completed" and extraction["warnings"] == [])

    # E-P4 real timeline classification (pure calls, no file writes).
    label = fact["structured_values"][0]["label"]
    check(
        "E-P4 real timeline_engine classifies the fact as notification_date with exact precision",
        timeline_engine.classify_event_type(fact, label, "vergi_ceza_ihbarnamesi", "administrative_action")
        == "notification_date"
        and timeline_engine.determine_date_precision(fact["structured_values"][0]["date_value"]) == "exact",
    )

    # E-P5 txt with BOM tolerated (the real fixture starts with one).
    check("E-P5a the real extracted text genuinely starts with a UTF-8 BOM",
          REAL_TEXT_BYTES.startswith(b"\xef\xbb\xbf"))
    no_bom = REAL_TEXT_BYTES[3:]
    check("E-P5b BOM-less text also PASSes and yields identical candidate bytes",
          evaluate(source_text_bytes=no_bom)["frozen_pending_bytes"] == result["frozen_pending_bytes"])

    # ========================================================
    # Negatives E-N1..E-N7, E-N10
    # ========================================================
    def with_fact(**fact_overrides):
        return input_bytes(make_input(fact=fact_overrides))

    expect_raises(mfe.ManualFactExcerptNotFoundError,
                  lambda: evaluate(manual_input_bytes=with_fact(text_excerpt=EXCERPT.replace("tebliğ", "teblig"))),
                  "E-N1a one-letter difference -> M-07 refusal")
    expect_raises(mfe.ManualFactExcerptNotFoundError,
                  lambda: evaluate(manual_input_bytes=with_fact(text_excerpt=EXCERPT.replace("İhbarname", "ihbarname"))),
                  "E-N1b case difference -> M-07 refusal (no case folding)")
    try:
        evaluate(manual_input_bytes=with_fact(text_excerpt=EXCERPT.replace(" ", "   ")))
        check("E-N1c whitespace-only difference -> PASS", True)
    except Exception as error:  # noqa: BLE001
        check("E-N1c whitespace-only difference -> PASS", False, repr(error))

    two = make_input()
    two["facts"].append(dict(two["facts"][0]))
    expect_raises(mfe.ManualFactInputSchemaError, lambda: evaluate(manual_input_bytes=input_bytes(two)),
                  "E-N2a two facts -> M-02 refusal")
    expect_raises(mfe.ManualFactInputSchemaError,
                  lambda: evaluate(manual_input_bytes=with_fact(role="issue_date")),
                  "E-N2b role != notification_date -> M-02 refusal")
    expect_raises(mfe.ManualFactInputSchemaError,
                  lambda: evaluate(manual_input_bytes=with_fact(verification_state="verified")),
                  "E-N3 extra verification_state field -> M-02 refusal")
    expect_raises(mfe.ManualFactInputSchemaError,
                  lambda: evaluate(manual_input_bytes=input_bytes(make_input(confidence=1.0))),
                  "E-N3b extra top-level field -> M-02 refusal")

    expect_raises(mfe.ManualFactDateInvalidError,
                  lambda: evaluate(manual_input_bytes=with_fact(date="2026-02-30")),
                  "E-N4a 2026-02-30 -> M-03 refusal")
    expect_raises(mfe.ManualFactInputSchemaError,
                  lambda: evaluate(manual_input_bytes=with_fact(page=0)),
                  "E-N4b page=0 -> schema refusal")
    expect_raises(mfe.ManualFactPageError,
                  lambda: evaluate(manual_input_bytes=with_fact(page=3)),
                  "E-N4c page > page_count -> M-04 refusal")
    doc_null = json.loads(json.dumps(ELIGIBLE_DOC))
    doc_null["file"]["page_count"] = None
    expect_raises(mfe.ManualFactPageError,
                  lambda: evaluate(document_bytes=json.dumps(doc_null).encode("utf-8")),
                  "E-N4d page_count: null -> M-04 refusal (M-8 decision)")
    doc_str = json.loads(json.dumps(ELIGIBLE_DOC))
    doc_str["file"]["page_count"] = "2"
    expect_raises(mfe.ManualFactPageError,
                  lambda: evaluate(document_bytes=json.dumps(doc_str).encode("utf-8")),
                  "E-N4e page_count string -> M-04 refusal")
    doc_bool = json.loads(json.dumps(ELIGIBLE_DOC))
    doc_bool["file"]["page_count"] = True
    expect_raises(mfe.ManualFactPageError,
                  lambda: evaluate(document_bytes=json.dumps(doc_bool).encode("utf-8")),
                  "E-N4f page_count True (bool is an int subclass) -> M-04 refusal")
    expect_raises(mfe.ManualFactInputSchemaError,
                  lambda: evaluate(manual_input_bytes=input_bytes(make_input(fact={"page": True}))),
                  "E-N4g page True -> refusal")

    expect_raises(mfe.ManualFactExcerptDateMismatchError,
                  lambda: evaluate(manual_input_bytes=with_fact(text_excerpt="İhbarname mükellefe")),
                  "E-N5a excerpt without a date -> M-08 refusal")
    expect_raises(mfe.ManualFactExcerptDateMismatchError,
                  lambda: evaluate(manual_input_bytes=with_fact(date="2026-02-11")),
                  "E-N5b excerpt date differs from date -> M-08 refusal")
    two_dates = "Düzenleme Tarihi: 05.02.2026"
    two_text = REAL_TEXT_BYTES + ("\n" + two_dates + " ve 10.02.2026 tebliğ\n").encode("utf-8")
    expect_raises(mfe.ManualFactExcerptDateMismatchError,
                  lambda: evaluate(source_text_bytes=two_text,
                                   manual_input_bytes=with_fact(text_excerpt=two_dates + " ve 10.02.2026 tebliğ")),
                  "E-N5c two different dates (one equals date) -> M-08 refusal")
    same_twice = "10.02.2026 tebliğ; 10/02/2026"
    try:
        evaluate(source_text_bytes=REAL_TEXT_BYTES + ("\n" + same_twice + "\n").encode("utf-8"),
                 manual_input_bytes=with_fact(text_excerpt=same_twice))
        check("E-N5d the same date twice -> PASS", True)
    except Exception as error:  # noqa: BLE001
        check("E-N5d the same date twice -> PASS", False, repr(error))
    bad_token = "31.02.2026 ve 10.02.2026"
    expect_raises(mfe.ManualFactExcerptDateMismatchError,
                  lambda: evaluate(source_text_bytes=REAL_TEXT_BYTES + ("\n" + bad_token + "\n").encode("utf-8"),
                                   manual_input_bytes=with_fact(text_excerpt=bad_token)),
                  "E-N5e invalid token 31.02.2026 -> M-08 refusal")
    mixed = "tebliğ 10.02/2026"
    expect_raises(mfe.ManualFactExcerptDateMismatchError,
                  lambda: evaluate(source_text_bytes=REAL_TEXT_BYTES + ("\n" + mixed + "\n").encode("utf-8"),
                                   manual_input_bytes=with_fact(text_excerpt=mixed)),
                  "E-N5f mixed separator 10.02/2026 is not a token -> no token -> M-08 refusal")
    check("E-N5g extract_excerpt_dates ignores digits glued to a longer number",
          mfe.extract_excerpt_dates("110.02.20261") == set())

    doc_type = json.loads(json.dumps(ELIGIBLE_DOC))
    doc_type["document_type"] = "vergi_inceleme_raporu"
    expect_raises(mfe.ManualFactDocumentTypeError,
                  lambda: evaluate(document_bytes=json.dumps(doc_type).encode("utf-8")),
                  "E-N6a document_type != vergi_ceza_ihbarnamesi -> M-05 refusal")
    doc_inactive = json.loads(json.dumps(ELIGIBLE_DOC))
    doc_inactive["active"] = False
    expect_raises(mfe.ManualFactDocumentTypeError,
                  lambda: evaluate(document_bytes=json.dumps(doc_inactive).encode("utf-8")),
                  "E-N6b active=false -> M-05 refusal")

    expect_raises(mfe.ManualFactSourceTextError, lambda: evaluate(source_text_bytes=b""),
                  "E-N7a empty text -> M-06 refusal")
    expect_raises(mfe.ManualFactSourceTextError, lambda: evaluate(source_text_bytes=b"\xef\xbb\xbf \n\t  \n"),
                  "E-N7b whitespace-only text -> M-06 refusal")
    expect_raises(mfe.ManualFactSourceTextError, lambda: evaluate(source_text_bytes=b"\xff\xfe bad"),
                  "E-N7c invalid UTF-8 text -> M-06 refusal")

    expect_raises(mfe.ManualFactEncodingError,
                  lambda: evaluate(manual_input_bytes=b"\xef\xbb\xbf" + input_bytes(make_input())),
                  "E-N10a input with BOM -> M-15 refusal")
    expect_raises(mfe.ManualFactEncodingError,
                  lambda: evaluate(manual_input_bytes=b'{"schema_version": "\xff"}'),
                  "E-N10b invalid UTF-8 input -> M-15 refusal")
    import unicodedata
    nfd = unicodedata.normalize("NFD", EXCERPT)
    check("E-N10c fixture sanity: the NFD excerpt genuinely differs from the NFC one", nfd != EXCERPT)
    expect_raises(mfe.ManualFactEncodingError,
                  lambda: evaluate(manual_input_bytes=with_fact(text_excerpt=nfd)),
                  "E-N10c NFD excerpt -> M-15 refusal")
    expect_raises(mfe.ManualFactEncodingError,
                  lambda: evaluate(manual_input_bytes=with_fact(text_excerpt=EXCERPT + "\x07")),
                  "E-N10d control character in excerpt -> M-15 refusal")
    expect_raises(mfe.ManualFactEncodingError,
                  lambda: evaluate(manual_input_bytes=b'{"schema_version": 1, "schema_version": 1}'),
                  "E-N10e duplicate JSON key -> M-15 refusal")
    expect_raises(mfe.ManualFactEncodingError,
                  lambda: evaluate(manual_input_bytes=b"not json"),
                  "E-N10f non-JSON input -> M-15 refusal")

    # ========================================================
    # E-N9 / E-N11 + writer happy path
    # ========================================================
    pending_path = ext_dir / mfe.CURRENT_PENDING_FILENAME
    temp_path = ext_dir / mfe.TEMP_FILENAME
    base_record = {"schema_version": "1", "document_id": DOC, "outcome": "generated"}

    def write(frozen, **kw):
        return mfe.write_manual_pending(
            extractions_dir=ext_dir, reviews_dir=reviews_dir, pending_path=pending_path,
            temp_path=temp_path, frozen_pending_bytes=frozen, audit_record=base_record,
            document_id=DOC, **kw,
        )

    def files_now():
        names = set(p.name for p in ext_dir.iterdir() if p.is_file())
        audits = set(p.name for p in reviews_dir.iterdir()) if reviews_dir.is_dir() else set()
        return names, audits

    verified = json.loads(result["frozen_pending_bytes"])
    verified["facts"][0]["verification_state"] = "verified"
    expect_raises(mfe.ManualFactCandidateInvalidError, lambda: write(mfe.freeze_pending_bytes(verified)),
                  "E-N9a a candidate flipped to verified in memory is refused by the writer helper")
    check("E-N9b ... and NO file was written (no temp, no pending, no audit)",
          files_now() == (set(), set()), f"{files_now()!r}")
    expect_raises(mfe.ManualFactCandidateInvalidError,
                  lambda: write(result["frozen_pending_bytes"].replace(b"\n", b"\r\n")),
                  "E-N9c non-canonical (CRLF) frozen bytes are refused before any write")

    validator_calls = []

    def failing_validate(path, raise_on_error=True):
        validator_calls.append(Path(path).name)
        raise ValueError("synthetic validator failure")

    expect_raises(ValueError, lambda: write(result["frozen_pending_bytes"], validate=failing_validate),
                  "E-N11a validator FAIL propagates")
    check("E-N11b the validator ran on the TEMP file (not on the pending name)",
          validator_calls == [mfe.TEMP_FILENAME], f"{validator_calls!r}")
    check("E-N11c after validator FAIL: temp and pending gone, no audit",
          files_now() == (set(), set()), f"{files_now()!r}")

    _orig_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("synthetic os.replace failure")

    os.replace = failing_replace
    try:
        expect_raises(OSError, lambda: write(result["frozen_pending_bytes"]),
                      "E-N11d os.replace failure (after the audit was written) propagates")
    finally:
        os.replace = _orig_replace
    check("E-N11e after os.replace FAIL: no pending, no temp, and the audit this call created was removed",
          files_now() == (set(), set()), f"{files_now()!r}")

    _orig_create_audit = mfe._create_audit_excl

    def failing_audit(reviews, document_id, data):
        raise OSError("synthetic audit write failure")

    mfe._create_audit_excl = failing_audit
    try:
        expect_raises(OSError, lambda: write(result["frozen_pending_bytes"]),
                      "E-N11f audit write failure propagates")
    finally:
        mfe._create_audit_excl = _orig_create_audit
    check("E-N11g after audit FAIL: no pending, no temp, no audit (pending never existed)",
          files_now() == (set(), set()), f"{files_now()!r}")

    # N-L1: a partially written audit (os.write fails AFTER O_EXCL created
    # the file) is removed by the call that created it.
    _orig_write_open_fd = mfe._write_open_fd
    _calls = {"n": 0}

    def write_fd_failing_second(fd, data):
        _calls["n"] += 1
        if _calls["n"] == 2:
            os.close(fd)
            raise OSError("synthetic partial audit write")
        return _orig_write_open_fd(fd, data)

    mfe._write_open_fd = write_fd_failing_second
    try:
        expect_raises(OSError, lambda: write(result["frozen_pending_bytes"]),
                      "E-N11h partial-audit write failure propagates")
    finally:
        mfe._write_open_fd = _orig_write_open_fd
    check("E-N11i after partial-audit FAIL: the half-created audit file is gone (N-L1)",
          files_now() == (set(), set()), f"{files_now()!r}")

    # Rollback branch A: a failure AFTER os.replace with the pending bytes
    # INTACT (the post-write re-read raises) and the pending cannot be
    # unlinked (e.g. AV lock) -> the audit is KEPT, so disk stays "audit +
    # pending" whose audit.pending_sha256 equals the on-disk pending sha
    # (the adapter's completed condition) instead of the dual-false
    # "pending without audit".
    _orig_unlink_quietly = mfe._unlink_quietly
    _orig_read_bytes = Path.read_bytes

    def unlink_refusing_pending(path):
        if Path(path).name == mfe.CURRENT_PENDING_FILENAME:
            return False
        return _orig_unlink_quietly(path)

    def read_bytes_failing_on_pending(self):
        if self.name == mfe.CURRENT_PENDING_FILENAME:
            raise OSError("synthetic post-write re-read failure")
        return _orig_read_bytes(self)

    Path.read_bytes = read_bytes_failing_on_pending
    mfe._unlink_quietly = unlink_refusing_pending
    try:
        expect_raises(OSError, lambda: write(result["frozen_pending_bytes"]),
                      "E-N11j post-replace failure with intact pending bytes propagates")
    finally:
        Path.read_bytes = _orig_read_bytes
        mfe._unlink_quietly = _orig_unlink_quietly
    names_j, audits_j = files_now()
    audit_j = json.loads((reviews_dir / next(iter(audits_j))).read_bytes()) if len(audits_j) == 1 else {}
    check(
        "E-N11k pending could not be removed -> the audit is KEPT, temp gone, and audit.pending_sha256 == "
        "the on-disk pending sha (consistent 'audit + pending' = the adapter's completed condition)",
        names_j == {mfe.CURRENT_PENDING_FILENAME} and len(audits_j) == 1
        and audit_j.get("pending_sha256") == hashlib.sha256(pending_path.read_bytes()).hexdigest()
        == hashlib.sha256(result["frozen_pending_bytes"]).hexdigest(),
        f"{names_j!r} {audits_j!r}",
    )
    pending_path.unlink()
    for _p in reviews_dir.iterdir():
        _p.unlink()

    # Rollback branch B: the post-write invariant itself (disk bytes differ
    # from the frozen bytes) with an unremovable pending. Disk is then
    # "audit + DIFFERENT pending": audit.pending_sha256 != on-disk sha, i.e.
    # deliberately NOT a completed proof (dual-false, fail-closed) - the
    # invariant propagates as a raw (non-domain) error.
    def corrupting_replace(src, dst):
        _orig_replace(src, dst)
        with open(dst, "ab") as handle:
            handle.write(b" ")

    os.replace = corrupting_replace
    mfe._unlink_quietly = unlink_refusing_pending
    try:
        expect_raises(mfe.ManualFactPostWriteInvariantError, lambda: write(result["frozen_pending_bytes"]),
                      "E-N11l post-write sha mismatch -> ManualFactPostWriteInvariantError (not a domain error)")
    finally:
        os.replace = _orig_replace
        mfe._unlink_quietly = _orig_unlink_quietly
    names_l, audits_l = files_now()
    audit_l = json.loads((reviews_dir / next(iter(audits_l))).read_bytes()) if len(audits_l) == 1 else {}
    check(
        "E-N11m byte-mismatch with an unremovable pending: audit kept but its pending_sha256 does NOT match "
        "the on-disk pending (never a completed proof; fail-closed dual-false)",
        names_l == {mfe.CURRENT_PENDING_FILENAME} and len(audits_l) == 1
        and audit_l.get("pending_sha256") != hashlib.sha256(pending_path.read_bytes()).hexdigest(),
        f"{names_l!r} {audits_l!r}",
    )
    pending_path.unlink()
    for _p in reviews_dir.iterdir():
        _p.unlink()

    written = write(result["frozen_pending_bytes"])
    names, audits = files_now()
    check("W-P1 happy path: exactly the pending file + exactly one manual_ audit",
          names == {mfe.CURRENT_PENDING_FILENAME} and len(audits) == 1
          and next(iter(audits)).startswith(f"manual_{DOC}_"), f"{names!r} {audits!r}")
    check("W-P2 pending bytes == frozen bytes; reported sha matches",
          pending_path.read_bytes() == result["frozen_pending_bytes"]
          and written["pending_sha256"] == hashlib.sha256(result["frozen_pending_bytes"]).hexdigest())
    audit_bytes = Path(written["audit_path"]).read_bytes()
    audit = json.loads(audit_bytes)
    check("W-P3 audit carries pending_sha256 of the frozen bytes and is LF-only",
          audit["pending_sha256"] == written["pending_sha256"] and b"\r" not in audit_bytes)
    check("W-P4 audit name passes validate_segment and contains no colon",
          ":" not in Path(written["audit_path"]).name)
    temp_path.write_bytes(b"x")
    expect_raises(FileExistsError, lambda: write(result["frozen_pending_bytes"]),
                  "W-N1 a leftover temp-name collision (O_EXCL) is refused, pending untouched")
    check("W-N1b the pre-existing temp residue was NOT deleted by the failed call, pending unchanged",
          temp_path.read_bytes() == b"x" and pending_path.read_bytes() == result["frozen_pending_bytes"])
    temp_path.unlink()

    check("E-N8e no poisoned stub was ever touched during import + evaluation + writes",
          _poison_hits == [], f"{_poison_hits!r}")
    _socket_armed[0] = False
    check("E-N8f zero socket.* audit events during import + evaluation + writes",
          _socket_events == [], f"{_socket_events!r}")
    check("E-N8g engine module has no `main` attribute", not hasattr(mfe, "main"))
finally:
    _socket_armed[0] = False
    for _name, _mod in _saved_modules.items():
        if _mod is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _mod
    shutil.rmtree(_tmp_root, ignore_errors=True)

check("FINAL: tempdir fully removed", not _tmp_root.exists())
check("FINAL: the real data/ tree is byte-for-byte identical to the pre-test snapshot",
      snapshot_data_tree() == _data_before)

print(f"--- test_manual_fact_entry_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
