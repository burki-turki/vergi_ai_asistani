# ============================================================
# PENALTY-BASIS-V1 - src/penalty_basis_review.py ISOLATED TESTS.
#
# Pure-Python, in-process: no network, no subprocess, no database. The
# test itself never starts a subprocess (no import of `subprocess`). The
# CLI is exercised through `main(argv, stdout=..., stderr=...)` and the
# real console entry point with byte-level in-memory streams. The two
# expected screens (fixtures dosya_1 / dosya_2) are pinned by SHA-256.
# Section G covers the independent-review findings M1-M4, L1-L7; section
# H covers the re-review findings (D-1 sentence rule, YL1, YL3, YL7,
# YL8; YL5/YL6 sit with the path checks in G). Every write goes to a
# private tempdir OUTSIDE the repository (write attempts aimed at a
# repository use a fake repository inside the tempdir; the real
# repository is exercised only through the pure pre-check); fixtures are
# copied there before any mutation. At the end the fixture bytes
# (SHA-256) and the full worktree file set (excluding .git) must be
# unchanged.
#
# Run: python -B ui/tests/test_penalty_basis_review_isolated.py
# ============================================================

import sys

sys.dont_write_bytecode = True

import ast            # noqa: E402
import hashlib        # noqa: E402
import html as _html  # noqa: E402
import io             # noqa: E402
import json           # noqa: E402
import os             # noqa: E402
import re             # noqa: E402
import shutil         # noqa: E402
import socket         # noqa: E402
import tempfile       # noqa: E402
from pathlib import Path  # noqa: E402

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
SRC_DIR = REPO_ROOT / "src"
MODULE_PATH = SRC_DIR / "penalty_basis_review.py"
SCHEMA_PATH = REPO_ROOT / "data" / "penalty_basis_statements.schema.json"
FIXTURE_ROOT = UI_DIR / "tests" / "fixtures" / "penalty_basis"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import penalty_basis_review as pbr  # noqa: E402

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


# ------------------------------------------------------------
# Baselines: fixture bytes + worktree file set.
# ------------------------------------------------------------

def fixture_hashes():
    out = {}
    for path in sorted(FIXTURE_ROOT.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(FIXTURE_ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def worktree_file_set():
    out = set()
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            out.add(os.path.relpath(os.path.join(dirpath, name), REPO_ROOT))
        for name in dirnames:
            out.add(os.path.relpath(os.path.join(dirpath, name), REPO_ROOT) + os.sep)
    return out


_fixtures_before = fixture_hashes()
_worktree_before = worktree_file_set()

# ------------------------------------------------------------
# No-network guard (in-process). Any connect attempt is recorded AND
# refused. Subprocess use is excluded statically (section A: the module
# imports only argparse/contextlib/html/json/os/sys/pathlib).
# ------------------------------------------------------------
_network_attempts = []
_orig_socket_connect = socket.socket.connect


def _guarded_connect(self, address):
    _network_attempts.append(repr(address))
    raise OSError("network disabled in test")


socket.socket.connect = _guarded_connect

TEMP_ROOT = Path(tempfile.mkdtemp(prefix="pbr_isolated_")).resolve()
_counter = [0]


def _fresh_name(prefix):
    _counter[0] += 1
    return f"{prefix}_{_counter[0]:03d}"


def copy_fixture(name):
    target = TEMP_ROOT / _fresh_name(f"in_{name}")
    shutil.copytree(FIXTURE_ROOT / name, target)
    return target


def output_path(name="out"):
    return TEMP_ROOT / (_fresh_name(name) + ".html")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = pbr.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def load_statements(input_dir):
    return json.loads((input_dir / "statements.json").read_text(encoding="utf-8"))


def save_statements(input_dir, doc):
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    (input_dir / "statements.json").write_bytes(text.encode("utf-8"))


def find_statement(doc, statement_id):
    for item in doc["statements"]:
        if item["statement_id"] == statement_id:
            return item
    raise KeyError(statement_id)


def render(input_dir):
    target = output_path()
    code, out, err = run(["--input", str(input_dir), "--output", str(target)])
    data = target.read_bytes() if target.exists() else b""
    return code, out, err, target, data


def section_text(html_text, number):
    start = html_text.find(f'<section id="b{number}">')
    end = html_text.find("</section>", start)
    return html_text[start:end] if start >= 0 and end >= 0 else ""


def tr_lower(text):
    """Turkish-aware lower case: İ -> i, I -> ı (str.lower/casefold would
    turn İ into i + combining dot and I into i)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def forbidden_hits(text):
    lowered = tr_lower(text)
    return [p for p in pbr.FORBIDDEN_PHRASES if p in text or tr_lower(p) in lowered]


STMT_BLOCK_RE = re.compile(
    r'<div class="stmt role-(?P<role>[a-z_]+)">'
    r'<div class="stmt-role">(?P<label>[^<]*)</div>'
    r"<blockquote>(?P<excerpt>.*?)</blockquote>"
    r'(?P<values><div class="sale-values">(?:<div>.*?</div>)+</div>)?'
    r'<div class="stmt-meta">(?P<meta>.*?)</div></div>\n',
    re.S,
)


def stmt_blocks(fragment):
    return list(STMT_BLOCK_RE.finditer(fragment))


def split_cards(sec3):
    """[(css_class, block_html)] for every card in section 3; each block
    runs up to the next card start (the last one to the section end)."""
    starts = [m.start() for m in re.finditer(r'<div class="card ', sec3)]
    cards = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(sec3)
        block = sec3[start:end]
        cards.append((re.match(r'<div class="card ([a-z-]+)">', block).group(1), block))
    return cards


def cards_of(sec3, css_class):
    return [block for cls, block in split_cards(sec3) if cls == css_class]


def value_line(label_key, value, statement_id, role):
    return (
        f'<div>{pbr.FIXED_TEXTS[label_key]}: {_html.escape(value)} '
        f'({pbr.FIXED_TEXTS["value_role_source"]}: <a href="#s-{statement_id}">'
        f'{pbr.FIXED_TEXTS["role." + role]}</a>)</div>'
    )


def not_tagged_line(label_key):
    return f'<div>{pbr.FIXED_TEXTS[label_key]}: {pbr.FIXED_TEXTS["value_not_tagged"]}</div>'


def common_html_checks(label, html_text, data, statements):
    check(f"{label}: output has no BOM", not data.startswith(b"\xef\xbb\xbf"))
    check(f"{label}: output has no CR", b"\r" not in data)
    check(f"{label}: output ends with LF", data.endswith(b"\n"))
    check(f"{label}: forbidden phrases = 0", forbidden_hits(html_text) == [], str(forbidden_hits(html_text)))
    positions = [html_text.find(f'<section id="b{n}">') for n in range(1, 7)]
    check(f"{label}: sections 1-6 present in order",
          all(p >= 0 for p in positions) and positions == sorted(positions), str(positions))
    for n in range(1, 7):
        check(f"{label}: section {n} title", pbr.FIXED_TEXTS[f"s{n}"] in section_text(html_text, n))
    check(f"{label}: no script", "<script" not in html_text.lower())
    for token in ("http://", "https://", " src=", "url(", "@import", "<link", "<iframe", "<img"):
        check(f"{label}: no external ref {token!r}", token not in html_text.lower())
    check(f"{label}: CSP meta present", "default-src 'none'" in html_text)
    check(f"{label}: section 2 fixed note", pbr.FIXED_TEXTS["s2_note"] in section_text(html_text, 2))
    check(f"{label}: section 4 fixed note", pbr.FIXED_TEXTS["s4_note"] in section_text(html_text, 4))
    check(f"{label}: banner present", pbr.FIXED_TEXTS["banner"] in html_text)
    sec6 = section_text(html_text, 6)
    for item in statements:
        sid = item["statement_id"]
        check(f"{label}: link to anchor s-{sid}", f'href="#s-{sid}"' in html_text)
        marks = re.findall(rf'<mark id="s-{re.escape(sid)}" class="role-[a-z_]+">(.*?)</mark>', sec6, re.S)
        check(f"{label}: anchor s-{sid} exactly once in section 6", len(marks) == 1, str(len(marks)))
        if marks:
            check(f"{label}: anchor s-{sid} wraps the excerpt", _html.unescape(marks[0]) == item["excerpt"])
    # Every printed statement block carries the tagged note on its OWN
    # bottom line (stmt-meta), and every statement is printed at least once.
    blocks = stmt_blocks(html_text)
    check(f"{label}: every statement block parsed",
          len(blocks) == html_text.count('<div class="stmt role-') and blocks, str(len(blocks)))
    for i, block in enumerate(blocks):
        check(f"{label}: block {i} ({block['role']}) own bottom line ends with tagged note",
              block["meta"].endswith(" · " + pbr.FIXED_TEXTS["tagged_note"]))
        check(f"{label}: block {i} role label matches its class",
              block["label"] == pbr.FIXED_TEXTS["role." + block["role"]])
    for item in statements:
        sid = item["statement_id"]
        own = [b for b in blocks if f'<a href="#s-{sid}">{pbr.FIXED_TEXTS["goto_doc"]}</a>' in b["meta"]]
        check(f"{label}: statement {sid} printed in a block of its own role",
              own and all(b["role"] == item["role"] for b in own))


# ============================================================
# A. Static / constant checks
# ============================================================

for key, value in pbr.FIXED_TEXTS.items():
    check(f"A fixed text {key!r} has no forbidden phrase", forbidden_hits(value) == [], str(forbidden_hits(value)))
check("A forbidden list covers the required minimum", set(pbr.FORBIDDEN_PHRASES) >= {
    "mevcut değil", "bulunmamaktadır", "hukuka aykırı", "hukuka uygun",
    "yerindedir", "kesinlikle", "iptal edilmeli", "kazan",
})
check("A refusal prefix", pbr.REFUSAL_PREFIX == "RAPOR REDDEDİLDİ: ")
check("A refusal codes are upper-case constants",
      all(re.fullmatch(r"[A-Z0-9_]+", code) for code in pbr.REFUSAL_CODES))
check("A fixed sentence text",
      pbr.FIXED_TEXTS["no_observed_sale"]
      == "İncelenen belgelerde belirli bir satış veya memurun ayrıca yaptığı bir tespit görünmüyor.")
check("A question text", pbr.FIXED_TEXTS["q_which_sale"] == "İhbarname hangi satış için düzenlenmiş?")
# Texts fixed by the user decisions R-1 ... R-4 (2026-11-11).
check("A R-1 sentence text",
      pbr.FIXED_TEXTS["no_observation_complaint_sale"]
      == "İncelenen belgelerde memurun ayrıca yaptığı bir tespit görünmüyor; "
         "satışın tarih ve tutarı yalnız şikâyetçinin anlatımında geçiyor.")
check("A R-1 card title",
      pbr.FIXED_TEXTS["card_complaint_unobserved_sale"] == "Şikâyette anlatılan satış (memur gözlemi değil)")
check("A R-2 role source label", pbr.FIXED_TEXTS["value_role_source"] == "kaynak")
check("A R-3 card text (D-2)",
      pbr.FIXED_TEXTS["notice_sale_no_basis"]
      == "Operatör, ihbarnamenin bağlandığı bu satış için dayanak belgelerde "
         "şikâyet, aktarım veya gözlem ifadesi işaretlemedi.")
check("A R-5 sentence text (D-1)",
      pbr.FIXED_TEXTS["no_officer_finding"] == "İncelenen belgelerde memurun ayrıca yaptığı bir tespit görünmüyor.")
check("A R-5 and new R-3 texts carry no forbidden phrase",
      forbidden_hits(pbr.FIXED_TEXTS["no_officer_finding"]) == []
      and forbidden_hits(pbr.FIXED_TEXTS["notice_sale_no_basis"]) == [])
check("A R-3 question",
      pbr.FIXED_TEXTS["q_notice_sale_basis"]
      == "İhbarnamenin bağlandığı satış dayanak belgelerin hangi satırında geçiyor?")
check("A R-4 text",
      pbr.FIXED_TEXTS["no_basis_statements"] == "Operatör bu dosyada şikâyet veya aktarım ifadesi işaretlemedi.")
check("A Turkish lower-casing (O6)",
      tr_lower("İPTAL EDİLMELİ") == "iptal edilmeli" and tr_lower("KAZANIR") == "kazanır"
      and forbidden_hits("KESİNLİKLE") == ["kesinlikle"] and forbidden_hits("HUKUKA AYKIRI") == ["hukuka aykırı"])

schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
statement_def = schema["$defs"]["statement"]
check("A schema draft 2020-12", schema["$schema"] == "https://json-schema.org/draft/2020-12/schema")
check("A schema top additionalProperties false", schema["additionalProperties"] is False)
check("A schema object defs additionalProperties false",
      all(schema["$defs"][k]["additionalProperties"] is False
          for k in ("document", "statement", "sale", "sale_value")))
check("A schema role enum == module ROLES", tuple(statement_def["properties"]["role"]["enum"]) == pbr.ROLES)
check("A schema header_item enum == module HEADER_ITEMS",
      tuple(statement_def["properties"]["header_item"]["enum"]) == pbr.HEADER_ITEMS)
check("A schema tagged_by const", statement_def["properties"]["tagged_by"]["const"] == pbr.TAGGED_BY)
check("A schema statement required",
      set(statement_def["required"]) == {"statement_id", "document_id", "excerpt", "role", "tagged_by"})
check("A schema top required", set(schema["required"]) == {"schema_version", "documents", "statements", "sales"})
check("A schema document is_notice boolean",
      schema["$defs"]["document"]["properties"]["is_notice"] == {"type": "boolean"})
documents_def = schema["properties"]["documents"]
check("A schema exactly one is_notice document",
      documents_def["contains"]["properties"]["is_notice"] == {"const": True}
      and documents_def["contains"]["required"] == ["is_notice"]
      and documents_def["minContains"] == 1 and documents_def["maxContains"] == 1)
check("A schema header_item forbids sale_ref",
      statement_def["allOf"][1]["then"]["not"] == {"required": ["sale_ref"]})

module_source = MODULE_PATH.read_text(encoding="utf-8")
tree = ast.parse(module_source)
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(alias.name.split(".")[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        imported.add((node.module or "").split(".")[0])
check("A module imports only the standard library",
      imported <= {"argparse", "contextlib", "html", "json", "os", "sys", "pathlib"}, str(imported))
check("A module has __main__ guard", 'if __name__ == "__main__":' in module_source)
check("A module source has no CR byte", b"\r" not in MODULE_PATH.read_bytes())

# ============================================================
# B. Dosya 1 - no officer-observed sale
# ============================================================

d1_statements = load_statements(FIXTURE_ROOT / "dosya_1")["statements"]
code, out, err, target, data = render(FIXTURE_ROOT / "dosya_1")
check("B dosya_1 exit 0", code == 0, f"code={code} err={err!r}")
check("B dosya_1 stderr empty", err == "")
check("B dosya_1 stdout written line", out == f"{pbr.OUTPUT_WRITTEN_PREFIX}{target}\n")
html1 = data.decode("utf-8")
common_html_checks("B dosya_1", html1, data, d1_statements)
sec3 = section_text(html1, 3)
sentence = pbr.FIXED_TEXTS["no_observed_sale"]
check("B dosya_1 fixed sentence exactly once", html1.count(sentence) == 1)
check("B dosya_1 fixed sentence in section 3", sentence in sec3)
based_on_pos = sec3.find(pbr.FIXED_TEXTS["based_on"])
check("B dosya_1 'based on' right after sentence",
      based_on_pos > sec3.find(sentence) >= 0)
for sid in ("cimer-iddia-1", "cimer-iddia-2", "tut-aktarim-1", "tut-aktarim-2"):
    pos = sec3.find(f'href="#s-{sid}"')
    check(f"B dosya_1 basis {sid} listed below 'based on'", pos > based_on_pos >= 0)
check("B dosya_1 no sale question", pbr.FIXED_TEXTS["q_which_sale"] not in html1)
check("B dosya_1 no observation card", '<div class="card card-observation">' not in html1)
check("B dosya_1 no complaint card (basis listed under the fixed note)",
      '<div class="card card-complaint">' not in html1)
check("B dosya_1 section 5 no-question note", pbr.FIXED_TEXTS["no_questions"] in section_text(html1, 5))
check("B dosya_1 taxpayer card shown", 'class="card card-taxpayer"' in sec3)
check("B dosya_1 taxpayer statement coloured",
      '<div class="stmt role-taxpayer_statement">' in sec3 and pbr.FIXED_TEXTS["role.taxpayer_statement"] in sec3)
check("B dosya_1 officer observation label absent",
      pbr.FIXED_TEXTS["role.officer_observation"] not in html1)
check("B dosya_1 header items all tagged", pbr.FIXED_TEXTS["header_not_tagged"] not in html1)
check("B dosya_1 madde no in section 2",
      "213 sayılı Vergi Usul Kanunu 353 üncü madde, 1 numaralı bent" in section_text(html1, 2))
check("B dosya_1 synthetic trailer shown",
      html1.count("sentetik test verisidir ve gerçek bir belge değildir.") == 3)

check("B dosya_1 R-1 sentence absent (no sale linked)",
      pbr.FIXED_TEXTS["no_observation_complaint_sale"] not in html1)
check("B dosya_1 R-4 text absent (basis statements tagged)", pbr.FIXED_TEXTS["no_basis_statements"] not in html1)
check("B dosya_1 no notice-sale card / question",
      'class="card card-notice-sale"' not in html1 and pbr.FIXED_TEXTS["q_notice_sale_basis"] not in html1)
check("B dosya_1 taxpayer card has its own heading after the basis list",
      f'<h4>{pbr.FIXED_TEXTS["card_taxpayer"]}</h4>' in sec3
      and sec3.find('class="card card-taxpayer"') > sec3.find('href="#s-tut-aktarim-2"') > 0)
# Expected screen pinned: identical to the reviewed demo output
# (vergi_product_penalty_demo_b6e58b82/dosya_1.html).
check("B dosya_1 screen unchanged (SHA-256 pin)",
      hashlib.sha256(data).hexdigest() == "a25c73dd2eea72c88df2de346847cd0f0ede46e4d5199f164603605c7f2cbe26",
      hashlib.sha256(data).hexdigest())
dosya_1_bytes = data

code_b, out_b, err_b, target_b, data_b = render(FIXTURE_ROOT / "dosya_1")
check("B dosya_1 deterministic (identical bytes on second run)", code_b == 0 and data_b == data)

# ============================================================
# C. Dosya 2 - one officer-observed sale, ihbarname not linked
# ============================================================

d2_statements = load_statements(FIXTURE_ROOT / "dosya_2")["statements"]
code, out, err, target, data = render(FIXTURE_ROOT / "dosya_2")
check("C dosya_2 exit 0", code == 0, f"code={code} err={err!r}")
check("C dosya_2 stderr empty", err == "")
html2 = data.decode("utf-8")
common_html_checks("C dosya_2", html2, data, d2_statements)
sec3 = section_text(html2, 3)
complaint_cards = sec3.count('<div class="card card-complaint">')
observation_cards = sec3.count('<div class="card card-observation">')
check("C dosya_2 two separate event cards (1 complaint + 1 observation)",
      complaint_cards == 1 and observation_cards == 1, f"{complaint_cards}/{observation_cards}")
obs_start = sec3.find('<div class="card card-observation">')
obs_card = sec3[obs_start:]
complaint_card = sec3[sec3.find('<div class="card card-complaint">'):obs_start]
check("C dosya_2 observation card has date", "Tarih: 20.02.2026" in obs_card)
check("C dosya_2 observation card has amount", "Tutar: 350,00 TL" in obs_card)
check("C dosya_2 observation card has observation", 'href="#s-tespit-gozlem"' in obs_card)
check("C dosya_2 complaint card has no observation", "role-officer_observation" not in complaint_card)
check("C dosya_2 complaint card holds complaint + relays",
      all(f'href="#s-{sid}"' in complaint_card
          for sid in ("cimer-iddia-1", "cimer-iddia-2", "tut-aktarim-1", "tut-aktarim-2")))
check("C dosya_2 taxpayer statement inside observation card, coloured",
      '<div class="stmt role-taxpayer_statement">' in obs_card)
check("C dosya_2 sale question exactly once", html2.count(pbr.FIXED_TEXTS["q_which_sale"]) == 1)
check("C dosya_2 sale question in section 5", pbr.FIXED_TEXTS["q_which_sale"] in section_text(html2, 5))
check("C dosya_2 no 'görünmüyor' sentence", pbr.FIXED_TEXTS["no_observed_sale"] not in html2)
check("C dosya_2 no R-1 sentence", pbr.FIXED_TEXTS["no_observation_complaint_sale"] not in html2)
check("C dosya_2 no act-linked note", pbr.FIXED_TEXTS["act_linked"] not in html2)
# M4 (3): role separation inside each card, checked per card block.
obs_blocks = cards_of(sec3, "card-observation")
complaint_blocks = cards_of(sec3, "card-complaint")
check("C dosya_2 card split 1 observation + 1 complaint", len(obs_blocks) == 1 and len(complaint_blocks) == 1)
for block in obs_blocks:
    roles = {b["role"] for b in stmt_blocks(block)}
    check("C dosya_2 observation card holds no complaint/relay statement",
          not roles & {"complainant_allegation", "officer_relay"}, str(roles))
    check("C dosya_2 observation card holds the observation", "officer_observation" in roles, str(roles))
    check("C dosya_2 observation card shows no complaint label",
          pbr.FIXED_TEXTS["role.complainant_allegation"] not in block
          and pbr.FIXED_TEXTS["role.officer_relay"] not in block)
for block in complaint_blocks:
    roles = {b["role"] for b in stmt_blocks(block)}
    check("C dosya_2 complaint card holds no officer observation", "officer_observation" not in roles, str(roles))
    check("C dosya_2 complaint card shows no observation label",
          pbr.FIXED_TEXTS["role.officer_observation"] not in block)
# R-2: values carry the role label of their source.
check("C dosya_2 date line with role label",
      value_line("date_label", "20.02.2026", "tespit-gozlem", "officer_observation") in obs_card)
check("C dosya_2 amount line with role label",
      value_line("amount_label", "350,00 TL", "tespit-gozlem", "officer_observation") in obs_card)
# Expected screen pinned. Differs from the reviewed demo
# (vergi_product_penalty_demo_b6e58b82/dosya_2.html) only in the two
# value lines above (R-2 role label).
check("C dosya_2 screen pinned (SHA-256)",
      hashlib.sha256(data).hexdigest() == "8cfdbd665e620be691557786964f1ef207d1976ca132d3c92a8c5522a82b5d95", hashlib.sha256(data).hexdigest())
dosya_2_bytes = data

# ============================================================
# D. Synthetic variants (tempdir copies)
# ============================================================

# D1: ihbarname linked to the sale -> no question, linked note in card.
d = copy_fixture("dosya_2")
doc = load_statements(d)
find_statement(doc, "ihb-aciklama")["sale_ref"] = "satis-1"
save_statements(d, doc)
code, out, err, target, data = render(d)
htmlv = data.decode("utf-8")
obs_card = section_text(htmlv, 3)
obs_card = obs_card[obs_card.find('<div class="card card-observation">'):]
check("D1 exit 0", code == 0, err)
check("D1 no sale question", pbr.FIXED_TEXTS["q_which_sale"] not in htmlv)
check("D1 act-linked note in observation card", pbr.FIXED_TEXTS["act_linked"] in obs_card)
check("D1 linked act excerpt in observation card", 'href="#s-ihb-aciklama"' in obs_card)

# D2: sale date not bound -> date not shown, fixed placeholder.
d = copy_fixture("dosya_2")
doc = load_statements(d)
del doc["sales"][0]["date"]
save_statements(d, doc)
code, out, err, target, data = render(d)
htmlv = data.decode("utf-8")
check("D2 exit 0", code == 0, err)
check("D2 date placeholder", f'{pbr.FIXED_TEXTS["date_label"]}: {pbr.FIXED_TEXTS["value_not_tagged"]}' in htmlv)
check("D2 amount still shown", "Tutar: 350,00 TL" in htmlv)

# D3: madde_no header item not tagged -> fixed text + question.
d = copy_fixture("dosya_1")
doc = load_statements(d)
del find_statement(doc, "ihb-madde-no")["header_item"]
save_statements(d, doc)
code, out, err, target, data = render(d)
htmlv = data.decode("utf-8")
check("D3 exit 0", code == 0, err)
check("D3 header_not_tagged in section 2", pbr.FIXED_TEXTS["header_not_tagged"] in section_text(htmlv, 2))
expected_q = pbr.FIXED_TEXTS["q_header_not_tagged"].format(label=pbr.FIXED_TEXTS["header.madde_no"])
check("D3 header question in section 5", expected_q in section_text(htmlv, 5))
check("D3 forbidden phrases = 0", forbidden_hits(htmlv) == [])

# D4: CRLF documents accepted; CR dropped in display only.
d = copy_fixture("dosya_1")
for name in ("ihbarname.txt", "cimer_sikayet.txt", "tutanak.txt"):
    raw = (d / name).read_bytes()
    (d / name).write_bytes(raw.replace(b"\n", b"\r\n"))
code, out, err, target, data = render(d)
check("D4 CRLF documents exit 0", code == 0, err)
check("D4 CRLF output has no CR", b"\r" not in data and len(data) > 0)
check("D4 CRLF output identical to the LF output", data == dosya_1_bytes)

# D5 (L5): lone-CR line endings are shown as line breaks, not glued.
d = copy_fixture("dosya_1")
for name in ("ihbarname.txt", "cimer_sikayet.txt", "tutanak.txt"):
    raw = (d / name).read_bytes()
    (d / name).write_bytes(raw.replace(b"\n", b"\r"))
code, out, err, target, data = render(d)
check("D5 lone-CR documents exit 0", code == 0, err)
check("D5 lone-CR output identical to the LF output", data == dosya_1_bytes)
check("D5 trailer lines kept apart",
      data.decode("utf-8").count("oluşturulmuş\nsentetik test verisidir") == 3)

# D6: a CRLF split exactly at a highlight boundary stays one line break.
check("D6 CRLF split at a slice boundary", pbr._d_slice("ab\r\ncd", 0, 3) + pbr._d_slice("ab\r\ncd", 3, 6)
      == "ab\ncd")

# ============================================================
# E. Refusals - each: exit 1 (USAGE 2), stdout empty, exactly one
# stderr line, no output file.
# ============================================================

_codes_exercised = set()


def expect_refusal(label, input_dir, code_name, *, output=None, argv=None, exit_code=1):
    target = output_path() if output is None else output
    existed_before = os.path.lexists(target) if isinstance(target, Path) else False
    args = argv if argv is not None else ["--input", str(input_dir), "--output", str(target)]
    code, out, err = run(args)
    check(f"E {label}: exit {exit_code}", code == exit_code, f"code={code}")
    check(f"E {label}: stdout empty", out == "", repr(out))
    check(f"E {label}: stderr is exactly '{code_name}'", err == f"{pbr.REFUSAL_PREFIX}{code_name}\n", repr(err))
    check(f"E {label}: code in closed list", code_name in pbr.REFUSAL_CODES)
    if err == f"{pbr.REFUSAL_PREFIX}{code_name}\n":
        _codes_exercised.add(code_name)
    if isinstance(target, Path) and not existed_before:
        check(f"E {label}: no output file", not os.path.lexists(target))


def mutate(fixture, fn):
    d = copy_fixture(fixture)
    doc = load_statements(d)
    fn(d, doc)
    save_statements(d, doc)
    return d


d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(
    excerpt="Bu işletme hiçbir satışta fiş kesmiyor."))
expect_refusal("invented excerpt", d, "EXCERPT_NOT_FOUND")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(excerpt="fiş"))
expect_refusal("excerpt occurring twice", d, "EXCERPT_AMBIGUOUS")


def _overlap_twice(d, doc):
    path = d / "cimer_sikayet.txt"
    path.write_bytes(path.read_bytes() + "Kod: xyxyx\n".encode("utf-8"))
    find_statement(doc, "cimer-iddia-1").update(excerpt="xyx")


d = mutate("dosya_1", _overlap_twice)
expect_refusal("excerpt occurring twice (overlapping)", d, "EXCERPT_AMBIGUOUS")


def _unlisted(d, doc):
    (d / "ek_belge.txt").write_bytes("Listede olmayan sentetik belge.\n".encode("utf-8"))


d = mutate("dosya_1", _unlisted)
expect_refusal("document not listed", d, "DOCUMENT_NOT_LISTED")

d = mutate("dosya_1", lambda d, doc: (d / "tutanak.txt").unlink())
expect_refusal("listed document missing", d, "DOCUMENT_MISSING")

d = mutate("dosya_1", lambda d, doc: (d / "alt_klasor").mkdir())
expect_refusal("subdirectory in input", d, "INPUT_UNEXPECTED_ENTRY")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(role="witness_statement"))
expect_refusal("unknown role", d, "UNKNOWN_ROLE")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "ihb-evrak").update(header_item="ceza_tutari"))
expect_refusal("unknown header_item", d, "UNKNOWN_HEADER_ITEM")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(header_item="evrak_turu"))
expect_refusal("header_item on non-administrative role", d, "HEADER_ITEM_ROLE_INVALID")

d = mutate("dosya_2", lambda d, doc: find_statement(doc, "tespit-gozlem").pop("sale_ref"))
expect_refusal("officer_observation without sale_ref", d, "OBSERVATION_SALE_REF_MISSING")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(sale_ref="satis-9"))
expect_refusal("unknown sale_ref", d, "UNKNOWN_SALE_REF")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(document_id="belge-9"))
expect_refusal("unknown document_id", d, "UNKNOWN_DOCUMENT_REF")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-2").update(statement_id="cimer-iddia-1"))
expect_refusal("duplicate statement_id", d, "DUPLICATE_ID")

d = mutate("dosya_2", lambda d, doc: doc["sales"][0]["amount"].update(value="999,00 TL"))
expect_refusal("sale value not in excerpt", d, "SALE_VALUE_NOT_IN_EXCERPT")

d = mutate("dosya_2", lambda d, doc: doc["sales"][0]["date"].update(statement_id="cimer-iddia-1"))
expect_refusal("sale value bound to unrelated statement", d, "SALE_VALUE_STATEMENT_MISMATCH")

d = mutate("dosya_2", lambda d, doc: doc["sales"][0]["date"].update(statement_id="yok-boyle-ifade"))
expect_refusal("sale value bound to unknown statement", d, "UNKNOWN_STATEMENT_REF")

d = mutate("dosya_1", lambda d, doc: doc["sales"].append({"sale_id": "satis-bos"}))
expect_refusal("sale referenced by no statement", d, "SALE_UNREFERENCED")


def _overlap_spans(d, doc):
    find_statement(doc, "cimer-iddia-2").update(
        excerpt="fiş kesmiyor. Birkaç kez alışveriş yaptım")


d = mutate("dosya_1", _overlap_spans)
expect_refusal("overlapping excerpts in one document", d, "EXCERPT_OVERLAP")


def _bom_document(d, doc):
    path = d / "tutanak.txt"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())


d = mutate("dosya_1", _bom_document)
expect_refusal("document with BOM", d, "DOCUMENT_BOM")


def _latin1_document(d, doc):
    path = d / "tutanak.txt"
    path.write_bytes(path.read_bytes() + b"\xfe\xfd\n")


d = mutate("dosya_1", _latin1_document)
expect_refusal("document not UTF-8", d, "DOCUMENT_NOT_UTF8")


def _control_document(d, doc):
    path = d / "tutanak.txt"
    path.write_bytes(path.read_bytes() + b"\x00\n")


d = mutate("dosya_1", _control_document)
expect_refusal("document with control character", d, "DOCUMENT_CONTROL_CHAR")

d = copy_fixture("dosya_1")
(d / "statements.json").write_bytes(b"\xef\xbb\xbf" + (d / "statements.json").read_bytes())
expect_refusal("statements.json with BOM", d, "STATEMENTS_BOM")

d = copy_fixture("dosya_1")
(d / "statements.json").write_bytes(b'{"schema_version": 1, "schema_version": 1}\n')
expect_refusal("statements.json duplicate key", d, "STATEMENTS_INVALID_JSON")

d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(tagged_by="agent"))
expect_refusal("tagged_by not operator", d, "STATEMENTS_SCHEMA_INVALID")

d = mutate("dosya_1", lambda d, doc: doc.update(schema_version=True))
expect_refusal("schema_version boolean", d, "STATEMENTS_SCHEMA_INVALID")

d = mutate("dosya_1", lambda d, doc: doc.update(extra_field=1))
expect_refusal("additional top-level property", d, "STATEMENTS_SCHEMA_INVALID")

d = copy_fixture("dosya_1")
(d / "statements.json").unlink()
expect_refusal("statements.json missing", d, "STATEMENTS_MISSING")

expect_refusal("input dir missing", TEMP_ROOT / "yok_boyle_klasor", "INPUT_DIR_INVALID")

existing = output_path("existing")
existing.write_bytes(b"onceden var\n")
expect_refusal("existing output file", FIXTURE_ROOT / "dosya_1", "OUTPUT_EXISTS", output=existing)
check("E existing output file untouched", existing.read_bytes() == b"onceden var\n")

expect_refusal("relative output path", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_RELATIVE",
               output=Path("rapor_goreli.html"))
check("E relative output not created in cwd", not os.path.lexists("rapor_goreli.html"))


def _precheck_code(raw):
    """The pure pre-check alone (no file is created by it)."""
    try:
        pbr._prepare_output_target(raw)
    except pbr.ReportRefused as refusal:
        return refusal.code
    return None


# YO3: every write attempt aimed at a repository goes to a fake repository
# (a tree with a .git directory) inside the tempdir; the real repository
# root is exercised only through the pure pre-check, which creates nothing.
FAKE_REPO = TEMP_ROOT / "sahte_repo_yazma"
(FAKE_REPO / ".git").mkdir(parents=True)
(FAKE_REPO / "ui").mkdir()
in_repo = FAKE_REPO / "pbr_test_should_not_exist.html"
expect_refusal("output path inside a (fake) repository", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_IN_REPO",
               output=in_repo)
in_repo_nested = FAKE_REPO / "ui" / "pbr_test_should_not_exist.html"
expect_refusal("output path nested inside a (fake) repository", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_IN_REPO",
               output=in_repo_nested)
check("E pre-check alone refuses a target in the real repository root",
      _precheck_code(str(REPO_ROOT / "pbr_test_should_not_exist.html")) == "OUTPUT_PATH_IN_REPO")
check("E pre-check alone refuses a target nested in the real repository",
      _precheck_code(str(REPO_ROOT / "ui" / "pbr_test_should_not_exist.html")) == "OUTPUT_PATH_IN_REPO")

expect_refusal("output parent missing", FIXTURE_ROOT / "dosya_1", "OUTPUT_PARENT_MISSING",
               output=TEMP_ROOT / "yok_boyle_ust" / "rapor.html")

d = copy_fixture("dosya_1")
expect_refusal("output inside input folder", d, "OUTPUT_PATH_IN_INPUT", output=d / "rapor.html")

expect_refusal("missing --output", None, "USAGE_ERROR",
               argv=["--input", str(FIXTURE_ROOT / "dosya_1")], exit_code=2)
expect_refusal("unknown argument", None, "USAGE_ERROR",
               argv=["--input", str(FIXTURE_ROOT / "dosya_1"), "--output", str(output_path()), "--x"],
               exit_code=2)

# ============================================================
# G. Review findings M1-M4, L1-L7 (synthetic inputs, tempdir only)
# ============================================================

def build_input(name, documents, statements, sales):
    """documents: [(document_id, file_name, title, document_type, text, is_notice)]."""
    d = TEMP_ROOT / _fresh_name(name)
    d.mkdir()
    entries = []
    for doc_id, file_name, title, doc_type, text, is_notice in documents:
        (d / file_name).write_bytes(text.encode("utf-8"))
        entry = {"document_id": doc_id, "file_name": file_name, "title": title, "document_type": doc_type}
        if is_notice:
            entry["is_notice"] = True
        entries.append(entry)
    save_statements(d, {"schema_version": 1, "documents": entries, "statements": statements, "sales": sales})
    return d


def append_text(path, text):
    path.write_bytes(path.read_bytes() + text.encode("utf-8"))


def stmt(statement_id, document_id, excerpt, role, **extra):
    item = {"statement_id": statement_id, "document_id": document_id, "excerpt": excerpt,
            "role": role, "tagged_by": "operator"}
    item.update(extra)
    return item


# --- M4 (1): hostile characters in document, title, section, value ---
NASTY_EXCERPT = "Müşteri \"A&B\" dedi: <script>alert('x')</script> </pre> tutar <12,00&TL> idi."
NASTY_NOTICE_TITLE = "İhbarname <script>alert(\"t\")</script> & 'q'"
d = build_input("in_escape", [
    ("ihb", "ihbarname.txt", NASTY_NOTICE_TITLE, "<i>tür</i>",
     "KURGUSAL İHBARNAME <i>\nCeza açıklaması: kurgusal & sentetik.\n"
     "Bu metin sentetik test verisidir.\n", True),
    ("sik", "sikayet.txt", "Şikâyet </pre> & <", "Tür \" ' &",
     "Kurgusal şikâyet (sentetik test verisi).\n" + NASTY_EXCERPT
     + "\nSon satır <b>kalın</b> & 'tek' \"çift\" </mark>\n", False),
], [
    stmt("ihb-1", "ihb", "Ceza açıklaması: kurgusal & sentetik.", "administrative_act",
         section="<b>Bölüm</b> & \"x\""),
    stmt("sik-1", "sik", NASTY_EXCERPT, "complainant_allegation",
         section="</pre><script>s</script>", sale_ref="satis-x"),
], [{"sale_id": "satis-x", "amount": {"value": "<12,00&TL>", "statement_id": "sik-1"}}])
code, out, err, target, data = render(d)
htmle = data.decode("utf-8") if data else ""
check("G-M4-1 hostile input renders", code == 0, err)
common_html_checks("G-M4-1", htmle, data, load_statements(d)["statements"])
check("G-M4-1 no raw <script", "<script" not in htmle.lower())
check("G-M4-1 no raw <b>/<i> from input", "<b>" not in htmle and "<i>" not in htmle)
check("G-M4-1 </pre> only as the two document closers", htmle.count("</pre>") == 2, str(htmle.count("</pre>")))
check("G-M4-1 </mark> only as the two highlight closers", htmle.count("</mark>") == 2, str(htmle.count("</mark>")))
check("G-M4-1 escaped title present", _html.escape(NASTY_NOTICE_TITLE) in htmle)
check("G-M4-1 single quote escaped", "&#x27;" in htmle and "'x'" not in htmle)
check("G-M4-1 escaped value with role label",
      value_line("amount_label", "<12,00&TL>", "sik-1", "complainant_allegation") in section_text(htmle, 3))
marks = re.findall(r'<mark id="s-sik-1" class="role-[a-z_]+">(.*?)</mark>', htmle, re.S)
check("G-M4-1 highlight unescapes to the excerpt", len(marks) == 1 and _html.unescape(marks[0]) == NASTY_EXCERPT)

# --- M4 (2): no normalisation in the excerpt gate ---
d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(
    excerpt="bu işletme nakit satışlarda fiş kesmiyor."))
expect_refusal("excerpt differs only in letter case", d, "EXCERPT_NOT_FOUND")
d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(
    excerpt="Bu işletme  nakit satışlarda fiş kesmiyor."))
expect_refusal("excerpt differs only by a double space", d, "EXCERPT_NOT_FOUND")
MULTILINE = "Başvuru Metni:\nBu işletme nakit satışlarda fiş kesmiyor."


def _crlf_doc_lf_excerpt(d, doc):
    path = d / "cimer_sikayet.txt"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    find_statement(doc, "cimer-iddia-1").update(excerpt=MULTILINE)


d = mutate("dosya_1", _crlf_doc_lf_excerpt)
expect_refusal("excerpt differs only by LF vs CRLF", d, "EXCERPT_NOT_FOUND")
d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(
    excerpt=MULTILINE.replace("\n", "\r\n")))
expect_refusal("excerpt differs only by CRLF vs LF", d, "EXCERPT_NOT_FOUND")
d = mutate("dosya_1", lambda d, doc: find_statement(doc, "cimer-iddia-1").update(excerpt=MULTILINE))
code, out, err, target, data = render(d)
check("G-M4-2 control: same multi-line excerpt with matching LF is accepted", code == 0, err)

# --- M1 + R-1: no observation, complaint linked to a sale ---
SALE_SENTENCE = "02.01.2031 günü 90,00 TL ödedim, bana fiş verilmedi."


def _complaint_sale(d, doc):
    append_text(d / "cimer_sikayet.txt", "Kurgusal ek: " + SALE_SENTENCE + "\n")
    doc["statements"].append(stmt("cimer-satis", "cimer", SALE_SENTENCE, "complainant_allegation",
                                  sale_ref="satis-S"))
    doc["sales"].append({"sale_id": "satis-S",
                         "date": {"value": "02.01.2031", "statement_id": "cimer-satis"},
                         "amount": {"value": "90,00 TL", "statement_id": "cimer-satis"}})


d = mutate("dosya_1", _complaint_sale)
code, out, err, target, data = render(d)
htmlm = data.decode("utf-8") if data else ""
sec3 = section_text(htmlm, 3)
check("G-M1 exit 0", code == 0, err)
common_html_checks("G-M1", htmlm, data, load_statements(d)["statements"])
check("G-M1 old sentence NOT printed", pbr.FIXED_TEXTS["no_observed_sale"] not in htmlm)
check("G-M1 R-1 sentence printed once in section 3",
      htmlm.count(pbr.FIXED_TEXTS["no_observation_complaint_sale"]) == 1
      and pbr.FIXED_TEXTS["no_observation_complaint_sale"] in sec3)
m1_cards = cards_of(sec3, "card-complaint")
check("G-M1 one sale card", len(m1_cards) == 1, str(len(m1_cards)))
m1_card = m1_cards[0] if m1_cards else ""
check("G-M1 card title",
      f'<h4>{pbr.FIXED_TEXTS["card_complaint_unobserved_sale"]} — {pbr.FIXED_TEXTS["sale_label"]}: satis-S</h4>'
      in m1_card)
check("G-M1 card date with role", value_line("date_label", "02.01.2031", "cimer-satis", "complainant_allegation") in m1_card)
check("G-M1 card amount with role",
      value_line("amount_label", "90,00 TL", "cimer-satis", "complainant_allegation") in m1_card)
check("G-M1 card holds the linked complaint only",
      [b["role"] for b in stmt_blocks(m1_card)] == ["complainant_allegation"] and 'href="#s-cimer-satis"' in m1_card)
check("G-M1 unlinked basis still listed under 'based on'",
      sec3.find(pbr.FIXED_TEXTS["based_on"]) < sec3.find('href="#s-cimer-iddia-1"') < sec3.find(m1_card[:40]))
check("G-M1 no sale question", pbr.FIXED_TEXTS["q_which_sale"] not in htmlm
      and pbr.FIXED_TEXTS["q_notice_sale_basis"] not in htmlm)
check("G-M1 no observation card", not cards_of(sec3, "card-observation"))


def _complaint_sale_act_linked(d, doc):
    _complaint_sale(d, doc)
    find_statement(doc, "ihb-aciklama")["sale_ref"] = "satis-S"


d = mutate("dosya_1", _complaint_sale_act_linked)
code, out, err, target, data = render(d)
htmlm = data.decode("utf-8") if data else ""
m1_cards = cards_of(section_text(htmlm, 3), "card-complaint")
check("G-M1 act-linked exit 0", code == 0, err)
check("G-M1 act-linked: notice link note in the sale card",
      len(m1_cards) == 1 and pbr.FIXED_TEXTS["act_linked"] in m1_cards[0] and 'href="#s-ihb-aciklama"' in m1_cards[0])
check("G-M1 act-linked: old sentence NOT printed", pbr.FIXED_TEXTS["no_observed_sale"] not in htmlm)

# --- M2 + R-2: values shown only in the card of their own role ---
COMPLAINT_DATE_SENTENCE = "Ben de 20.02.2026 günü nakit ödeme yaptım."


def _mixed_roles(d, doc):
    append_text(d / "cimer_sikayet.txt", "Kurgusal ek: " + COMPLAINT_DATE_SENTENCE + "\n")
    doc["statements"].append(stmt("cimer-satis", "cimer", COMPLAINT_DATE_SENTENCE, "complainant_allegation",
                                  sale_ref="satis-1"))
    doc["sales"][0]["date"]["statement_id"] = "cimer-satis"


d = mutate("dosya_2", _mixed_roles)
code, out, err, target, data = render(d)
htmlm = data.decode("utf-8") if data else ""
sec3 = section_text(htmlm, 3)
obs_blocks = cards_of(sec3, "card-observation")
sale_complaint = [b for b in cards_of(sec3, "card-complaint") if "satis-1" in b]
check("G-M2 exit 0", code == 0, err)
common_html_checks("G-M2", htmlm, data, load_statements(d)["statements"])
check("G-M2 one observation card + one complaint sale card", len(obs_blocks) == 1 and len(sale_complaint) == 1)
if obs_blocks and sale_complaint:
    obs_header = obs_blocks[0].split('<div class="stmt')[0]
    check("G-M2 observation card: complainant's date NOT shown",
          "20.02.2026" not in obs_header and not_tagged_line("date_label") in obs_header)
    check("G-M2 observation card: own amount with role",
          value_line("amount_label", "350,00 TL", "tespit-gozlem", "officer_observation") in obs_blocks[0])
    check("G-M2 observation card: no complainant label anywhere",
          pbr.FIXED_TEXTS["role.complainant_allegation"] not in obs_blocks[0])
    check("G-M2 complaint card: own date with role",
          value_line("date_label", "20.02.2026", "cimer-satis", "complainant_allegation") in sale_complaint[0])
    check("G-M2 complaint card: officer's amount NOT shown",
          not_tagged_line("amount_label") in sale_complaint[0] and "350,00" not in sale_complaint[0])
    check("G-M2 complaint card: no observation label", pbr.FIXED_TEXTS["role.officer_observation"] not in sale_complaint[0])
TAXPAYER_AMOUNT_SENTENCE = "Yetkili, alışverişin 350,00 TL olduğunu kabul etmiştir."


def _taxpayer_value(d, doc):
    append_text(d / "tespit_tutanagi.txt", "Kurgusal ek: " + TAXPAYER_AMOUNT_SENTENCE + "\n")
    doc["statements"].append(stmt("tespit-mukellef-2", "tespit", TAXPAYER_AMOUNT_SENTENCE, "taxpayer_statement",
                                  sale_ref="satis-1"))
    doc["sales"][0]["amount"]["statement_id"] = "tespit-mukellef-2"


d = mutate("dosya_2", _taxpayer_value)
code, out, err, target, data = render(d)
htmlm = data.decode("utf-8") if data else ""
obs_blocks = cards_of(section_text(htmlm, 3), "card-observation")
check("G-M2 taxpayer exit 0", code == 0, err)
common_html_checks("G-M2 taxpayer", htmlm, data, load_statements(d)["statements"])
taxpayer_rows = [b for b in stmt_blocks(htmlm) if b["values"]]
check("G-M2 taxpayer value only on the taxpayer statement row",
      len(taxpayer_rows) == 1 and taxpayer_rows[0]["role"] == "taxpayer_statement"
      and value_line("amount_label", "350,00 TL", "tespit-mukellef-2", "taxpayer_statement")
      in taxpayer_rows[0]["values"])
check("G-M2 taxpayer value not in the observation card header",
      len(obs_blocks) == 1 and not_tagged_line("amount_label") in obs_blocks[0].split('<div class="stmt')[0])

# --- L1: value must not be glued to a digit or letter ---
d = mutate("dosya_2", lambda d, doc: doc["sales"][0]["amount"].update(value="50,00 TL"))
expect_refusal("amount value inside a longer number", d, "SALE_VALUE_NOT_DELIMITED")
d = mutate("dosya_2", lambda d, doc: doc["sales"][0]["date"].update(value="0.02.2026"))
expect_refusal("date value inside a longer date", d, "SALE_VALUE_NOT_DELIMITED")
d = mutate("dosya_2", lambda d, doc: doc["sales"][0]["amount"].update(value="350,00 TL tutarındak"))
expect_refusal("value followed by a letter", d, "SALE_VALUE_NOT_DELIMITED")
check("G-L1 helper: first occurrence glued, second clean",
      pbr._occurs_delimited("20,00 TL", "120,00 TL ve 20,00 TL") is True
      and pbr._occurs_delimited("20,00 TL", "120,00 TL") is False
      and pbr._occurs_delimited("20.02.2026", "20.02.2026") is True)

# --- L2 + R-3: notice linked to a sale the basis documents do not tag ---


def _notice_sale(d, doc):
    find_statement(doc, "ihb-aciklama")["sale_ref"] = "satis-C"
    doc["sales"].append({"sale_id": "satis-C"})


for fixture in ("dosya_2", "dosya_1"):
    d = mutate(fixture, _notice_sale)
    code, out, err, target, data = render(d)
    htmlm = data.decode("utf-8") if data else ""
    notice_cards = cards_of(section_text(htmlm, 3), "card-notice-sale")
    check(f"G-L2 {fixture} exit 0", code == 0, err)
    common_html_checks(f"G-L2 {fixture}", htmlm, data, load_statements(d)["statements"])
    check(f"G-L2 {fixture} one notice-sale card", len(notice_cards) == 1, str(len(notice_cards)))
    card = notice_cards[0] if notice_cards else ""
    check(f"G-L2 {fixture} card title", f'<h4>{pbr.FIXED_TEXTS["sale_label"]}: satis-C</h4>' in card)
    check(f"G-L2 {fixture} R-3 text in card", pbr.FIXED_TEXTS["notice_sale_no_basis"] in card)
    check(f"G-L2 {fixture} notice statement linked in card",
          pbr.FIXED_TEXTS["act_linked"] in card and 'href="#s-ihb-aciklama"' in card)
    check(f"G-L2 {fixture} R-3 question once in section 5",
          htmlm.count(pbr.FIXED_TEXTS["q_notice_sale_basis"]) == 1
          and pbr.FIXED_TEXTS["q_notice_sale_basis"] in section_text(htmlm, 5))
    check(f"G-L2 {fixture} no 'which sale' question", pbr.FIXED_TEXTS["q_which_sale"] not in htmlm)


def _notice_sale_dated(d, doc):
    find_statement(doc, "ihb-aciklama")["sale_ref"] = "satis-C"
    doc["sales"].append({"sale_id": "satis-C", "date": {"value": "12.01.2026", "statement_id": "ihb-aciklama"}})


d = mutate("dosya_1", _notice_sale_dated)
code, out, err, target, data = render(d)
htmlm = data.decode("utf-8") if data else ""
notice_cards = cards_of(section_text(htmlm, 3), "card-notice-sale")
check("G-L2 dated exit 0", code == 0, err)
check("G-L2 dated: notice value with its role label",
      len(notice_cards) == 1
      and value_line("date_label", "12.01.2026", "ihb-aciklama", "administrative_act") in notice_cards[0])

# --- L3 + R-4: no complaint or relay statement tagged ---


def _no_basis(d, doc):
    drop = {"cimer-iddia-1", "cimer-iddia-2", "tut-aktarim-1", "tut-aktarim-2"}
    doc["statements"] = [item for item in doc["statements"] if item["statement_id"] not in drop]


d = mutate("dosya_1", _no_basis)
code, out, err, target, data = render(d)
htmlm = data.decode("utf-8") if data else ""
sec3 = section_text(htmlm, 3)
check("G-L3 exit 0", code == 0, err)
common_html_checks("G-L3", htmlm, data, load_statements(d)["statements"])
check("G-L3 'based on' line NOT printed", pbr.FIXED_TEXTS["based_on"] not in htmlm)
check("G-L3 R-4 text printed once", htmlm.count(pbr.FIXED_TEXTS["no_basis_statements"]) == 1)
check("G-L3 taxpayer card separate, own heading, after R-4 text",
      f'<h4>{pbr.FIXED_TEXTS["card_taxpayer"]}</h4>' in sec3
      and sec3.find('class="card card-taxpayer"') > sec3.find(pbr.FIXED_TEXTS["no_basis_statements"]) >= 0)

# --- L4: notice document and header items ---
d = mutate("dosya_1", lambda d, doc: doc["documents"][0].pop("is_notice"))
expect_refusal("no document marked is_notice", d, "NOTICE_DOCUMENT_COUNT_INVALID")
d = mutate("dosya_1", lambda d, doc: doc["documents"][1].update(is_notice=True))
expect_refusal("two documents marked is_notice", d, "NOTICE_DOCUMENT_COUNT_INVALID")
d = mutate("dosya_1", lambda d, doc: doc["documents"][0].update(is_notice=False))
expect_refusal("is_notice false only", d, "NOTICE_DOCUMENT_COUNT_INVALID")
d = mutate("dosya_1", lambda d, doc: doc["documents"][0].update(is_notice="true"))
expect_refusal("is_notice not boolean", d, "STATEMENTS_SCHEMA_INVALID")
d = mutate("dosya_1", lambda d, doc: find_statement(doc, "tut-aktarim-1").update(role="administrative_act"))
expect_refusal("administrative_act outside the notice document", d, "NOTICE_STATEMENT_DOCUMENT_INVALID")
d = mutate("dosya_1", lambda d, doc: find_statement(doc, "tut-aktarim-1").update(
    role="administrative_act", header_item="madde_no"))
expect_refusal("header item outside the notice document", d, "NOTICE_STATEMENT_DOCUMENT_INVALID")
d = mutate("dosya_2", lambda d, doc: find_statement(doc, "ihb-teblig-tarihi").update(sale_ref="satis-1"))
expect_refusal("header item with sale_ref", d, "HEADER_ITEM_SALE_REF_INVALID")

# --- M3 + O8: device namespace / UNC / trailing dot or space ---
for raw in (
    "\\\\?\\" + str(FAKE_REPO / "pbr_test_should_not_exist.html"),
    "\\\\?\\" + str(TEMP_ROOT / "yok_boyle_ust" / "x.html"),
    "//?/" + str(TEMP_ROOT / "yok_boyle_ust" / "x.html").replace("\\", "/"),
    "\\\\.\\" + str(TEMP_ROOT / "yok_boyle_ust" / "x.html"),
):
    expect_refusal(f"device-namespace path {raw[:4]!r}...", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_INVALID",
                   output=raw)
check("G-M3 nothing written into the (fake) repository via \\\\?\\",
      not os.path.lexists(FAKE_REPO / "pbr_test_should_not_exist.html"))
check("G-M3 pre-check alone refuses \\\\?\\ + real repository root",
      _precheck_code("\\\\?\\" + str(REPO_ROOT / "pbr_test_should_not_exist.html")) == "OUTPUT_PATH_INVALID")
# YL6: mixed-separator prefixes are refused before anything is touched.
for prefix, sep in (("/\\./", "/"), ("\\/.\\", "\\"), ("\\/?\\", "\\"), ("/\\?\\", "\\")):
    name = _fresh_name("yl6") + ".html"
    raw = prefix + str(TEMP_ROOT / name).replace("\\", sep)
    expect_refusal(f"YL6 mixed-separator prefix {prefix!r}", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_INVALID",
                   output=raw)
    check(f"G-YL6 nothing written for {prefix!r}", not os.path.lexists(TEMP_ROOT / name))
    check(f"G-YL6 pre-check alone refuses {prefix!r}", _precheck_code(raw) == "OUTPUT_PATH_INVALID")
for name in ("rapor.html.", "rapor.html ", "rapor.html. "):
    expect_refusal(f"output name {name!r}", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_INVALID",
                   output=str(TEMP_ROOT / name))
    check(f"G-O8 nothing written for {name!r}", not os.path.lexists(TEMP_ROOT / name.rstrip(". ")))


def _is_within_refuses(child, root):
    try:
        pbr._is_within(child, root)
    except pbr.ReportRefused as refusal:
        return refusal.code == "OUTPUT_PATH_INVALID"
    return False


# YL5: two plain X:\ paths on different drive letters are "not within";
# prefixed forms stay refusals. Pure string function only (no other drive
# is touched).
def _within_or_refused(child, root):
    try:
        return pbr._is_within(child, root)
    except pbr.ReportRefused as refusal:
        return "refused:" + refusal.code


check("G-YL5 _is_within: plain paths on different drives -> not within",
      _within_or_refused("C:\\a\\b", "Q:\\a") is False and _within_or_refused("Q:\\a\\b", "C:\\a") is False
      and _within_or_refused("c:\\a\\b", "Q:\\a\\b") is False,
      str([_within_or_refused("C:\\a\\b", "Q:\\a"), _within_or_refused("Q:\\a\\b", "C:\\a")]))
check("G-YL5 _is_within: input folder on another drive -> output not within it",
      _within_or_refused(TEMP_ROOT / "x.html", "Q:\\girdi") is False)
check("G-M3 _is_within fail-closed on \\\\?\\ vs plain form",
      _is_within_refuses("\\\\?\\" + str(REPO_ROOT / "x"), str(REPO_ROOT)))
check("G-YL5 _is_within fail-closed on prefixed vs plain form on different drives",
      _is_within_refuses("\\\\?\\C:\\a\\b", "Q:\\a") and _is_within_refuses("\\\\.\\C:\\a\\b", "Q:\\a")
      and _is_within_refuses("Q:\\a\\b", "\\\\?\\C:\\a"))
_orig_repo_root_real = pbr._repo_root_real
pbr._repo_root_real = lambda: Path("Q:\\pbr_sahte_repo")
try:
    _yl5_target = output_path("yl5")
    check("G-YL5 pre-check with the module repository (patched) on another drive accepts an outside target",
          _precheck_code(str(_yl5_target)) is None)
    check("G-YL5 pre-check created no file", not os.path.lexists(_yl5_target))
finally:
    pbr._repo_root_real = _orig_repo_root_real
check("G-M3 _is_within still answers inside/outside",
      pbr._is_within(REPO_ROOT / "ui", REPO_ROOT) is True and pbr._is_within(TEMP_ROOT, REPO_ROOT) is False)

# --- L6: any tree with a .git entry counts as a repository ---
fake_repo_dir = TEMP_ROOT / "sahte_repo_dizin"
(fake_repo_dir / ".git").mkdir(parents=True)
(fake_repo_dir / "alt").mkdir()
expect_refusal("output under a tree with a .git directory", FIXTURE_ROOT / "dosya_1", "OUTPUT_PATH_IN_REPO",
               output=fake_repo_dir / "alt" / "rapor.html")
fake_repo_file = TEMP_ROOT / "sahte_repo_dosya"
fake_repo_file.mkdir()
(fake_repo_file / ".git").write_bytes(b"gitdir: sahte\n")
expect_refusal("output under a tree with a .git file (working copy)", FIXTURE_ROOT / "dosya_1",
               "OUTPUT_PATH_IN_REPO", output=fake_repo_file / "rapor.html")


check("G pre-check alone refuses a target inside the module repository",
      _precheck_code(str(REPO_ROOT / "pbr_test_should_not_exist.html")) == "OUTPUT_PATH_IN_REPO")
check("G pre-check alone refuses a target under a .git tree",
      _precheck_code(str(fake_repo_dir / "alt" / "rapor.html")) == "OUTPUT_PATH_IN_REPO")
check("G pre-check alone accepts a fresh target outside any repository",
      _precheck_code(str(output_path("precheck"))) is None)

# --- L7: remaining refusal codes ---
d = copy_fixture("dosya_1")
(d / "statements.json").write_bytes(b" " * (pbr.MAX_STATEMENTS_BYTES + 1))
expect_refusal("statements.json too large", d, "STATEMENTS_TOO_LARGE")
d = copy_fixture("dosya_1")
(d / "statements.json").write_bytes(b'{"schema_version": "\xfe"}\n')
expect_refusal("statements.json not UTF-8", d, "STATEMENTS_NOT_UTF8")
d = mutate("dosya_1", lambda d, doc: (d / "tutanak.txt").write_bytes(b"a" * (pbr.MAX_DOCUMENT_BYTES + 1)))
expect_refusal("document too large", d, "DOCUMENT_TOO_LARGE")
expect_refusal("output name the file system cannot create", FIXTURE_ROOT / "dosya_1", "OUTPUT_WRITE_FAILED",
               output=TEMP_ROOT / "rapor|x.html")
_orig_locate = pbr._locate_excerpts


def _boom(*_args, **_kwargs):
    raise RuntimeError("synthetic failure")


pbr._locate_excerpts = _boom
try:
    expect_refusal("unexpected internal failure", FIXTURE_ROOT / "dosya_1", "INTERNAL_ERROR")
finally:
    pbr._locate_excerpts = _orig_locate


# --- L7: real console entry point (in-process, byte-level streams) ---
def run_console(argv):
    saved = (sys.argv, sys.stdout, sys.stderr)
    out_bytes, err_bytes = io.BytesIO(), io.BytesIO()
    sys.stdout = io.TextIOWrapper(out_bytes, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(err_bytes, encoding="utf-8")
    sys.argv = ["penalty_basis_review.py", *argv]
    try:
        code = pbr._console_entrypoint()
        sys.stdout.flush()
        sys.stderr.flush()
        return code, out_bytes.getvalue(), err_bytes.getvalue()
    finally:
        sys.argv, sys.stdout, sys.stderr = saved


target = output_path("console")
code, out_b, err_b = run_console(["--input", str(FIXTURE_ROOT / "dosya_1"), "--output", str(target)])
check("G-L7 console success exit 0", code == 0, f"code={code} err={err_b!r}")
check("G-L7 console success stdout bytes",
      out_b == f"{pbr.OUTPUT_WRITTEN_PREFIX}{target}\n".encode("utf-8"), repr(out_b))
check("G-L7 console success stderr empty", err_b == b"")
check("G-L7 console success same bytes as main()", target.exists() and target.read_bytes() == dosya_1_bytes)
code, out_b, err_b = run_console(["--input", str(FIXTURE_ROOT / "dosya_1"), "--output", "goreli.html"])
check("G-L7 console refusal exit 1", code == 1, f"code={code}")
check("G-L7 console refusal stdout empty", out_b == b"")
check("G-L7 console refusal stderr bytes",
      err_b == f"{pbr.REFUSAL_PREFIX}OUTPUT_PATH_RELATIVE\n".encode("utf-8"), repr(err_b))
code, out_b, err_b = run_console(["--input"])
check("G-L7 console usage error exit 2 + fixed line",
      code == 2 and out_b == b"" and err_b == f"{pbr.REFUSAL_PREFIX}USAGE_ERROR\n".encode("utf-8"))

# ============================================================
# H. Re-review findings (FIX2): D-1 sentence rule, YM1/YM2 cases
# N-5a1 ... N-5d5, YL1, YL3, YL7, YL8 (synthetic inputs, tempdir only)
# ============================================================

H_ACT = "Mükellefin fiş düzenlemediği tespit edildiğinden ceza kesilmiştir."
H_ACT2 = "09.01.2031 tarihli 500,00 TL tutarındaki satış için fiş düzenlenmemiştir."
H_C1 = "Bu işletme nakit satışlarda fiş kesmiyor."
H_CSALE = "02.01.2031 günü 90,00 TL ödedim, bana fiş verilmedi."
H_CVAGUE = "Geçen hafta bir alışverişte de fiş almadım."
H_CTOTAL = "Toplam 1.120,00 TL harcadım."
H_R1 = "Şikâyetçinin işletmede fiş verilmediğini bildirdiği aktarılmıştır."
H_RSALE = "Başvuruda 04.01.2031 günü 75,00 TL tutarındaki satışta fiş verilmediği bildirilmiştir."
H_TAXSALE = "İşletme yetkilisi 09.01.2031 günü 500,00 TL tutarındaki satış için fiş kestiğini beyan etmiştir."
H_OBS = "03.01.2031 günü 120,00 TL tutarındaki satışta fiş verilmediği görülmüştür."
H_TRAILER = "Bu metin sentetik test verisidir.\n"
H_DOCS = [
    ("ihb", "ihbarname.txt", "Kurgusal ihbarname", "Ceza ihbarnamesi",
     "KURGUSAL İHBARNAME (test)\n" + H_ACT + "\n" + H_ACT2 + "\n" + H_TRAILER, True),
    ("sik", "sikayet.txt", "Kurgusal şikâyet", "Şikâyet",
     "KURGUSAL ŞİKÂYET (test)\n" + "\n".join((H_C1, H_CSALE, H_CVAGUE, H_CTOTAL)) + "\n" + H_TRAILER, False),
    ("tut", "tutanak.txt", "Kurgusal tutanak", "Tutanak",
     "KURGUSAL TUTANAK (test)\n" + "\n".join((H_R1, H_RSALE, H_TAXSALE)) + "\n" + H_TRAILER, False),
    ("tes", "tespit.txt", "Kurgusal tespit", "Tespit tutanağı",
     "KURGUSAL TESPİT (test)\n" + H_OBS + "\n" + H_TRAILER, False),
]
SENTENCE_KEYS = ("no_observed_sale", "no_observation_complaint_sale", "no_officer_finding")


def h_sale(sale_id, date=None, amount=None):
    item = {"sale_id": sale_id}
    if date:
        item["date"] = {"value": date[0], "statement_id": date[1]}
    if amount:
        item["amount"] = {"value": amount[0], "statement_id": amount[1]}
    return item


def h_input(name, extra=(), sales=(), drop=(), act_sale_ref=None):
    act = stmt("act", "ihb", H_ACT, "administrative_act")
    if act_sale_ref:
        act["sale_ref"] = act_sale_ref
    base = [act, stmt("c1", "sik", H_C1, "complainant_allegation"), stmt("r1", "tut", H_R1, "officer_relay")]
    statements = [item for item in base if item["statement_id"] not in drop] + list(extra)
    return build_input(name, H_DOCS, statements, list(sales))


def h_render(label, d):
    code, out, err, target, data = render(d)
    text = data.decode("utf-8") if data else ""
    check(f"{label}: exit 0", code == 0, err)
    if code == 0:
        common_html_checks(label, text, data, load_statements(d)["statements"])
    return text


def sentence_shown(text):
    return [key for key in SENTENCE_KEYS
            if f'<p class="no-observed-sale">{_html.escape(pbr.FIXED_TEXTS[key])}</p>' in text]


def expect_sentence(label, text, key):
    shown = sentence_shown(text)
    check(f"{label}: first right-column sentence is exactly {key!r}",
          shown == [key] and text.count('<p class="no-observed-sale">') == 1, str(shown))


def card_header(block):
    return block.split('<div class="stmt')[0]


ACT2_DATE = ("09.01.2031", "act2")
ACT2_AMOUNT = ("500,00 TL", "act2")

# --- D-1 branch (1): no sale record -> old sentence ---
t = h_render("H-D1 branch 1 (no sale)", h_input("h_d1b1"))
expect_sentence("H-D1 branch 1", t, "no_observed_sale")

# --- D-1 branch (2): one sale, complaint linked, both values from it -> R-1 ---
d = h_input("h_d1b2", [stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="S")],
            [h_sale("S", ("02.01.2031", "cs"), ("90,00 TL", "cs"))])
t = h_render("H-D1 branch 2 (complaint)", d)
expect_sentence("H-D1 branch 2 (complaint)", t, "no_observation_complaint_sale")

# YL7 (1): relay-bound values carry the "Memurun aktarımı" label (also D-1 branch 2).
d = h_input("h_d1b2r", [stmt("rs", "tut", H_RSALE, "officer_relay", sale_ref="S")],
            [h_sale("S", ("04.01.2031", "rs"), ("75,00 TL", "rs"))])
t = h_render("H-YL7-1 relay values", d)
expect_sentence("H-YL7-1 relay values", t, "no_observation_complaint_sale")
cards = cards_of(section_text(t, 3), "card-complaint")
check("H-YL7-1 one sale card", len(cards) == 1, str(len(cards)))
if cards:
    check("H-YL7-1 date labelled 'Memurun aktarımı'",
          value_line("date_label", "04.01.2031", "rs", "officer_relay") in card_header(cards[0]))
    check("H-YL7-1 amount labelled 'Memurun aktarımı'",
          value_line("amount_label", "75,00 TL", "rs", "officer_relay") in card_header(cards[0]))
    check("H-YL7-1 no 'Şikâyetçi iddiası' label in the card header",
          pbr.FIXED_TEXTS["role.complainant_allegation"] not in card_header(cards[0]))

# --- D-1 branch (3) examples ---
d = h_input("h_d1b3", [stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="S")],
            [h_sale("S", ("02.01.2031", "cs"))])
t = h_render("H-D1 branch 3 (only the date bound)", d)
expect_sentence("H-D1 branch 3 (only the date bound)", t, "no_officer_finding")
d = h_input("h_d1b3a", [stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="S")],
            [h_sale("S", None, ("90,00 TL", "cs"))])
t = h_render("H-D1 branch 3 (only the amount bound)", d)
expect_sentence("H-D1 branch 3 (only the amount bound)", t, "no_officer_finding")

# N-5a1: notice linked to sale C (values from the notice), unlinked complaint.
d = h_input("h_n5a1", [stmt("act2", "ihb", H_ACT2, "administrative_act", sale_ref="C")],
            [h_sale("C", ACT2_DATE, ACT2_AMOUNT)])
t = h_render("H-N-5a1", d)
expect_sentence("H-N-5a1", t, "no_officer_finding")
notice_cards = cards_of(section_text(t, 3), "card-notice-sale")
check("H-N-5a1 one notice-sale card", len(notice_cards) == 1, str(len(notice_cards)))
if notice_cards:
    card = notice_cards[0]
    check("H-N-5a1 new R-3 text in the card (D-2)", pbr.FIXED_TEXTS["notice_sale_no_basis"] in card)
    check("H-N-5a1 notice values in the card header",
          value_line("date_label", "09.01.2031", "act2", "administrative_act") in card_header(card)
          and value_line("amount_label", "500,00 TL", "act2", "administrative_act") in card_header(card))
    # YL8 choice: the notice-sale card header already shows the notice
    # values, so the notice row in that card does not repeat them.
    check("H-YL8 notice-sale card: each notice value appears exactly once",
          card.count(value_line("date_label", "09.01.2031", "act2", "administrative_act")) == 1
          and card.count(value_line("amount_label", "500,00 TL", "act2", "administrative_act")) == 1)
    check("H-YL8 notice-sale card: notice row carries no value lines",
          [b["values"] for b in stmt_blocks(card) if b["role"] == "administrative_act"] == [None])

# N-5a4: sale linked only to a taxpayer statement.
d = h_input("h_n5a4", [stmt("tx", "tut", H_TAXSALE, "taxpayer_statement", sale_ref="T")],
            [h_sale("T", ("09.01.2031", "tx"), ("500,00 TL", "tx"))])
t = h_render("H-N-5a4", d)
expect_sentence("H-N-5a4", t, "no_officer_finding")

# N-5d1: complaint linked to a sale, no value bound.
d = h_input("h_n5d1", [stmt("cv", "sik", H_CVAGUE, "complainant_allegation", sale_ref="S")], [h_sale("S")])
t = h_render("H-N-5d1", d)
expect_sentence("H-N-5d1", t, "no_officer_finding")

# N-5d2: vague complaint + notice on the same sale; values bound to the notice.
d = h_input("h_n5d2", [stmt("cv", "sik", H_CVAGUE, "complainant_allegation", sale_ref="S"),
                       stmt("act2", "ihb", H_ACT2, "administrative_act", sale_ref="S")],
            [h_sale("S", ACT2_DATE, ACT2_AMOUNT)])
t = h_render("H-N-5d2", d)
expect_sentence("H-N-5d2", t, "no_officer_finding")
cards = cards_of(section_text(t, 3), "card-complaint")
check("H-N-5d2 one complaint sale card", len(cards) == 1, str(len(cards)))
if cards:
    card = cards[0]
    # YL7 (3): the complaint-sale card header shows no other role's value.
    check("H-YL7-3 complaint-sale card header: notice values NOT shown",
          not_tagged_line("date_label") in card_header(card) and not_tagged_line("amount_label") in card_header(card)
          and "09.01.2031" not in card_header(card))
    # YL8: the notice values appear on the notice statement's own row.
    act_rows = [b for b in stmt_blocks(card) if b["role"] == "administrative_act"]
    check("H-YL8 complaint-sale card: notice row shows date and amount with role label",
          len(act_rows) == 1 and act_rows[0]["values"] is not None
          and value_line("date_label", "09.01.2031", "act2", "administrative_act") in act_rows[0]["values"]
          and value_line("amount_label", "500,00 TL", "act2", "administrative_act") in act_rows[0]["values"])
    check("H-YL8 complaint-sale card: each notice value appears exactly once",
          card.count(value_line("date_label", "09.01.2031", "act2", "administrative_act")) == 1
          and card.count(value_line("amount_label", "500,00 TL", "act2", "administrative_act")) == 1)
check("H-YL8 left column notice row unchanged (no value lines)",
      all(b["values"] is None for b in stmt_blocks(section_text(t, 3).split(pbr.FIXED_TEXTS["s3_right_title"])[0])))

# N-5d3: vague complaint + taxpayer on the same sale; values bound to the taxpayer.
d = h_input("h_n5d3", [stmt("cv", "sik", H_CVAGUE, "complainant_allegation", sale_ref="S"),
                       stmt("tx", "tut", H_TAXSALE, "taxpayer_statement", sale_ref="S")],
            [h_sale("S", ("09.01.2031", "tx"), ("500,00 TL", "tx"))])
t = h_render("H-N-5d3", d)
expect_sentence("H-N-5d3", t, "no_officer_finding")
cards = cards_of(section_text(t, 3), "card-complaint")
if cards:
    check("H-YL7-3 complaint-sale card header: taxpayer values NOT shown",
          not_tagged_line("date_label") in card_header(cards[0]) and "09.01.2031" not in card_header(cards[0]))
check("H-N-5d3 one complaint sale card", len(cards) == 1, str(len(cards)))

# N-5d4: two complaint sales (one with values, one without).
d = h_input("h_n5d4", [stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="S1"),
                       stmt("cv", "sik", H_CVAGUE, "complainant_allegation", sale_ref="S2")],
            [h_sale("S1", ("02.01.2031", "cs"), ("90,00 TL", "cs")), h_sale("S2")])
t = h_render("H-N-5d4", d)
expect_sentence("H-N-5d4", t, "no_officer_finding")

# N-5d5: complaint sale S (values from it) + separate notice sale C.
d = h_input("h_n5d5", [stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="S"),
                       stmt("act2", "ihb", H_ACT2, "administrative_act", sale_ref="C")],
            [h_sale("S", ("02.01.2031", "cs"), ("90,00 TL", "cs")), h_sale("C", ACT2_DATE, ACT2_AMOUNT)])
t = h_render("H-N-5d5", d)
expect_sentence("H-N-5d5", t, "no_officer_finding")

# YL7 (3) notice-sale card: a taxpayer-bound value is not shown in its header (N-R3b shape).
d = h_input("h_r3b", [stmt("act2", "ihb", H_ACT2, "administrative_act", sale_ref="C"),
                      stmt("tx", "tut", H_TAXSALE, "taxpayer_statement", sale_ref="C")],
            [h_sale("C", ("09.01.2031", "tx"), ("500,00 TL", "tx"))])
t = h_render("H-YL7-3 notice-sale card", d)
notice_cards = cards_of(section_text(t, 3), "card-notice-sale")
check("H-YL7-3 one notice-sale card", len(notice_cards) == 1, str(len(notice_cards)))
if notice_cards:
    header = card_header(notice_cards[0])
    check("H-YL7-3 notice-sale card header: taxpayer values NOT shown",
          not_tagged_line("date_label") in header and not_tagged_line("amount_label") in header
          and "09.01.2031" not in header)
    check("H-YL7-3 notice-sale card: taxpayer value on its own row",
          value_line("date_label", "09.01.2031", "tx", "taxpayer_statement") in notice_cards[0])

# YL7 (2): officer observed A; complaint describes B; notice and taxpayer linked to B.
d = h_input("h_obsb", [stmt("obs", "tes", H_OBS, "officer_observation", sale_ref="A"),
                       stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="B"),
                       stmt("tx", "tut", H_TAXSALE, "taxpayer_statement", sale_ref="B")],
            [h_sale("A", ("03.01.2031", "obs"), ("120,00 TL", "obs")),
             h_sale("B", ("02.01.2031", "cs"), ("90,00 TL", "cs"))], act_sale_ref="B")
t = h_render("H-YL7-2 observed A, complaint B", d)
sec3 = section_text(t, 3)
b_cards = [b for b in cards_of(sec3, "card-complaint") if "Satış kaydı: B</h4>" in b]
check("H-YL7-2 one complaint card for B", len(b_cards) == 1, str(len(b_cards)))
if b_cards:
    check("H-YL7-2 B card keeps the notice link",
          pbr.FIXED_TEXTS["act_linked"] in b_cards[0] and 'href="#s-act"' in b_cards[0])
    check("H-YL7-2 B card keeps the taxpayer statement",
          [b["role"] for b in stmt_blocks(b_cards[0])].count("taxpayer_statement") == 1)
    check("H-YL7-2 B card shows its own complaint values",
          value_line("date_label", "02.01.2031", "cs", "complainant_allegation") in card_header(b_cards[0]))
check("H-YL7-2 observation card for A only",
      len(cards_of(sec3, "card-observation")) == 1 and "Satış kaydı: A</h4>" in cards_of(sec3, "card-observation")[0])
check("H-YL7-2 no separate taxpayer card", not cards_of(sec3, "card-taxpayer"))

# YL7 (4): every complaint/relay statement linked to the sale -> R-4 text NOT printed.
d = h_input("h_all_linked", [stmt("cs", "sik", H_CSALE, "complainant_allegation", sale_ref="S"),
                             stmt("rs", "tut", H_RSALE, "officer_relay", sale_ref="S")],
            [h_sale("S", ("02.01.2031", "cs"), ("90,00 TL", "cs"))], drop=("c1", "r1"))
t = h_render("H-YL7-4 all complaints linked", d)
check("H-YL7-4 R-4 text NOT printed", pbr.FIXED_TEXTS["no_basis_statements"] not in t)
check("H-YL7-4 'based on' line printed", pbr.FIXED_TEXTS["based_on"] in section_text(t, 3))
expect_sentence("H-YL7-4 all complaints linked", t, "no_observation_complaint_sale")

# --- YL1: a "." or "," with a digit on its other side is not a boundary ---
for value in ("120,00 TL", "1", "00 TL", "120"):
    d = h_input("h_yl1", [stmt("ct", "sik", H_CTOTAL, "complainant_allegation", sale_ref="S")],
                [h_sale("S", None, (value, "ct"))])
    expect_refusal(f"YL1 amount {value!r} inside '1.120,00 TL'", d, "SALE_VALUE_NOT_DELIMITED")
d = h_input("h_yl1ok", [stmt("ct", "sik", H_CTOTAL, "complainant_allegation", sale_ref="S")],
            [h_sale("S", None, ("1.120,00 TL", "ct"))])
t = h_render("H-YL1 control: full amount '1.120,00 TL'", d)
# YL7 (5): a letter right before the value is not a boundary.
d = h_input("h_yl7_5", [stmt("cl", "sik", H_C1, "complainant_allegation", sale_ref="S")],
            [h_sale("S", None, ("şletme", "cl"))], drop=("c1",))
expect_refusal("YL7-5 value preceded by a letter", d, "SALE_VALUE_NOT_DELIMITED")
check("H-YL1 helper: dot/comma with a digit beyond is not a boundary",
      pbr._occurs_delimited("120,00 TL", "1.120,00 TL") is False
      and pbr._occurs_delimited("1", "1.120,00 TL") is False
      and pbr._occurs_delimited("00 TL", "1.120,00 TL") is False
      and pbr._occurs_delimited("2031", "02.01.2031 günü") is False
      and pbr._occurs_delimited("02.01", "02.01.2031 günü") is False)
check("H-YL1 helper: sentence punctuation is still a boundary",
      pbr._occurs_delimited("02.01.2031", "günü 02.01.2031.") is True
      and pbr._occurs_delimited("90,00 TL", "90,00 TL, sonra") is True
      and pbr._occurs_delimited("90,00 TL", "Toplam: 90,00 TL.") is True)
check("H-YL7-5 helper: letter before the value is not a boundary",
      pbr._occurs_delimited("90,00 TL", "Tutarx90,00 TL") is False)

# --- YL3: the notice document carries only administrative_act statements ---
for role in ("officer_observation", "complainant_allegation", "officer_relay", "taxpayer_statement"):
    extra = stmt("x-ihb", "ihb", H_ACT2, role, sale_ref="A")
    d = h_input("h_yl3", [extra], [h_sale("A")])
    expect_refusal(f"YL3 {role} statement in the notice document", d, "NOTICE_DOCUMENT_ROLE_INVALID")

check("E every refusal code in the closed list is exercised",
      _codes_exercised == set(pbr.REFUSAL_CODES), str(sorted(set(pbr.REFUSAL_CODES) - _codes_exercised)))

# ============================================================
# F. Invariants
# ============================================================

socket.socket.connect = _orig_socket_connect

check("F no network attempts", _network_attempts == [], str(_network_attempts))
check("F fixture bytes unchanged (SHA-256)", fixture_hashes() == _fixtures_before)
check("F fixture count", len(_fixtures_before) == 9, str(len(_fixtures_before)))
_worktree_after = worktree_file_set()
check("F no new file in worktree", _worktree_after == _worktree_before,
      str(sorted(_worktree_after ^ _worktree_before)))
check("F temp root outside repository",
      os.path.commonpath([os.path.normcase(str(TEMP_ROOT)), os.path.normcase(str(REPO_ROOT))])
      != os.path.normcase(str(REPO_ROOT)))

shutil.rmtree(TEMP_ROOT, ignore_errors=True)
check("F tempdir cleaned up", not TEMP_ROOT.exists())

print(f"--- test_penalty_basis_review_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
