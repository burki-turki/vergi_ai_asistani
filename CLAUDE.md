# CLAUDE.md — Vergi Uyuşmazlığı Analiz ve Hukuki Araştırma Platformu

Bu dosya, bu repository üzerinde çalışan her Claude Code session'ının uyması gereken
canonical proje talimatlarını içerir. Amaç: her yeni session'ın repository'yi sıfırdan
yorumlamasını önlemek. Bu dosyadaki roadmap ve mimari kurallar **sabittir**; bir görev
sırasında yeniden yorumlanamaz veya değiştirilemez (bkz. §12 — istisna yalnızca
checkpoint/status güncellemesidir).

Bu dosyadaki tüm güvenlik ve roadmap kuralları, doğrudan çalışan Claude Code
session'ı için olduğu kadar, **Task/Agent tool ile başlatılan her subagent için de
aynen geçerlidir** — bir subagent bu kuralları bilmiyor olması gerekçesiyle muaf
tutulamaz; onu başlatan session bu kuralların subagent'a da uygulanmasından
sorumludur.

## 1. Proje

Vergi uyuşmazlığı ve vergi davalarıyla çalışan **avukatlar** için bir analiz ve hukuki
araştırma platformu.

Ürün akışı (hedef, tamamı henüz implement edilmedi):

```
case/dispute → facts → issues → legal research → evidence → arguments → risk/strategy → drafting
```

## 2. Repository Mimarisi (mevcut durum)

İki pipeline var:

**Pipeline A — Case/Uyuşmazlık: Fact → Timeline → Deadline**
```
fact_extraction_engine.py (LLM)
  → case_fact_validator.py
  → [human approval: fact_approval.py]  → canonical facts.json
  → timeline_engine.py (deterministik, LLM yok)
  → timeline_validator.py
  → [human approval: timeline_approval.py] → canonical timeline.json
  → deadline_rule_selection_policy.py + deadline_calculator.py
  → deadline_validator.py
  → [human approval: deadline_approval.py] → canonical deadline.json
```

**Pipeline B — Legal Research RAG**
```
ingest.py (PDF → chunk → embedding → FAISS)
  → retriever.py / query_parser.py
  → provision_policy.py / temporal_policy.py / version_policy.py (deterministik cevap denemesi)
  → yalnızca deterministik cevap yoksa: rag.py → LLM (deterministik sonuçla çelişemez)
```

### Canonical / Pending / Review / Audit — klasör değil, konvansiyon

- `canonical/`, `pending/`, `audit/` diye bir **klasör yok**.
- **Canonical** = `.pending` suffix'i taşımayan canonical JSON dosyası
  (`facts.json`, `timeline.json`, `deadline.json`).
- **Pending** = aynı dizinde kardeş `*.json.pending` dosyası.
- **Review/Audit** = her artefaktın yanında `reviews/` (`*.approval.json` kayıtları) +
  `history/` (promosyon öncesi yedek) + `*.bak` dosyaları.
- Gerçek doğrulama durumu her katmanda ayrı bir alan olarak taşınır:
  `verification_state ∈ {unverified, partially_verified, verified, disputed, rejected}`.

### Kilit dosyalar (gerçek modül adları)

| Katman | Fact | Timeline | Deadline | Kural/Kayıt |
|---|---|---|---|---|
| Engine | `fact_extraction_engine.py` | `timeline_engine.py` | `deadline_engine.py`, `deadline_calculator.py` | — |
| Policy | — | `timeline_consolidation_policy.py` | `deadline_rule_selection_policy.py` | `provision_policy.py`, `provision_version_policy.py`, `temporal_policy.py`, `version_policy.py`, `source_policy.py` |
| Validator | `case_fact_validator.py` | `timeline_validator.py` | `deadline_validator.py`, `deadline_rule_validator.py` | `case_validator.py`, `case_document_validator.py`, `manifest_validator.py`, `provision_manifest_validator.py` |
| Approval | `fact_approval.py` | `timeline_approval.py` | `deadline_approval.py` | — |
| Destek | `document_reference_resolver.py` (LLM document_id seçmez) | — | `deadline_legal_basis_resolver.py`, `add_iyuk_*.py` (tek seferlik provizyon seed script'leri) | — |
| RAG | `ingest.py`, `retriever.py`, `query_parser.py`, `rag.py`, `evaluation*.py` | | | |

Veri: `data/*.schema.json` (case, case_document, case_fact_extraction, case_timeline,
case_deadline, deadline_rule, documents, provisions), `data/documents.json`,
`data/provisions.json`, `data/deadline_rules/deadline_rules.json` (gerçek aktif
registry), `data/cases/case_0001/` (tek demo case: `documents/`, `timeline/`,
`deadlines/`, her biri canonical + `.pending` + `reviews/` + `history/`).

⚠️ `data/deadline_rules.json` (üst düzey, boş `rules: []`) **stale/duplicate**'tir,
gerçek registry `data/deadline_rules/deadline_rules.json`'dır — bkz. Backlog.

## 3. Temel Mimari Prensipler (ihlal edilemez)

1. Agent/LLM çıktısı canonical truth değildir.
2. Case fact ile AI analysis kesin olarak ayrıdır.
3. Kaynak belgenin söylediği şey ile doğrulanmış hukuki gerçek aynı şey değildir.
4. Extraction confidence ile verification_state aynı şey değildir.
5. Approval ile verification aynı şey değildir.
6. Kritik hukuki gerçekler deterministic policy + validator + verification ve
   gerektiğinde human approval olmadan kesinleştirilemez.
7. Agent kritik tarih, deadline, mevzuat uygulanabilirliği, yürürlük, dava sonucu
   veya hukuki gerçeği kendi başına canonical hale getiremez.
8. Unverified anchor üzerinden kesin deadline hesaplanamaz
   (bkz. `deadline_calculator.py`: `calculation_state = blocked_unverified_anchor`).
9. Fail-closed davranış tercih edilir (belirsizlik → hesaplama yok, onay bekle).
10. Existing locked katmanlar gerekmedikçe yeniden tasarlanmaz.
11. Mevcut repository source of truth'tur.
12. Bir hata görüldüğünde önce mevcut API, schema ve gerçek runtime çıktısı incelenir;
    tahminle çoklu dosya değişikliği yapılmaz.
13. Değişiklikler küçük, izlenebilir ve geri alınabilir olmalıdır.
14. Validator PASS olmadan katman tamamlanmış sayılmaz.
15. Human approval gereken yerde agent DURMALI ve açık onay istemelidir.
16. Pending → validation → human approval → canonical akışı korunmalıdır.
17. Backup / SHA256 / audit kullanılan mevcut katmanlarda bu güvenlik seviyesi
    düşürülmemelidir.
18. Test fixture ile production canonical data birbirine karıştırılmamalıdır.
19. Special-law / general-law çatışmalarında agent varsayım yapmamalı; ambiguity
    fail-closed çözülmelidir.
20. Hukuki kaynakların version/temporal/applicability çözümü Legal Knowledge Engine
    (`provision_policy.py` + `provision_version_policy.py` + `temporal_policy.py` +
    `version_policy.py` + `source_policy.py`) üzerinden yapılmalıdır.

## 4. Canonical Multi-Agent Development Roadmap (SABİT)

Agent kendi kararıyla sıralamayı değiştiremez.

1. Legal Knowledge Engine — **DONE / LOCKED**
2. Case Model V1 — **DONE / LOCKED**
3. Case Document Layer — **DONE / LOCKED**
4. Fact Extraction Agent — **DONE / LOCKED**
5. Document Reference Resolver — **DONE / LOCKED**
6. Fact Approval / Repository — **DONE / LOCKED**
7. Timeline Agent / Engine — **DONE / LOCKED**
8. Deadline Engine — **DONE / LOCKED**
9. Issue Spotting Agent — **DONE / LOCKED**
10. Legal Research Agent — **DONE / LOCKED**
11. Case Law Agent — **DONE / LOCKED**
12. Evidence Agent — **DONE / LOCKED**
13. Argument Agent — **DONE / LOCKED**
14. Risk / Strategy Agent — **DONE / LOCKED**
15. Drafting Agent — **DONE / LOCKED**
16. QA Agent — **DONE / LOCKED**
17. Product Orchestrator Agent — **DONE / LOCKED**
18. Lawyer UI — **ACTIVE / NEXT**
19. Production / Security
20. Pilot / Evaluation
21. Commercial V1

### Her row için standart geliştirme sırası

1. Amaç
2. Input / Output contract
3. Schema
4. Deterministic rules
5. Agent / LLM task
6. Validator
7. Synthetic tests
8. Edge-case tests
9. Human approval gerekiyorsa approval workflow
10. Repository / downstream integration
11. LOCK
12. Next row

## 5. Current Checkpoint

- Git baseline tag: **`v0.8-pre-claude`** (commit `f3c97f8`, "Vergi AI checkpoint -
  rows 1-8 complete - pre Claude")
- Development branch: **`claude-dev`** ← burada çalış
- `main` branch üzerinde geliştirme yapılmaz
- `v0.8-pre-claude` tag'i değiştirilmez veya silinmez
- Rows 1-17 tamamlandı ve **LOCKED**
- Sıradaki canonical development row: **ROW 18 — LAWYER UI** (İLERLEME
  HALİNDE, tam Row 18 için henüz LOCK YOK) — kullanıcı kararıyla
  18a/18b/18c olarak fazlandırıldı (bkz. Row 18 checkpoint özeti, §5
  sonrası). **18a** (tüm canonical katmanların görüntülenmesi + yalnız
  registry-supported aileler için Layer A onay tetikleme; fact/timeline
  onayı `unsupported_pending_resolution` olarak fail-closed)
  **DONE / LOCKED** — hedeflenen `vergi_ui_runtime` ortamında `pip
  check` PASS ve 117/117 test PASS ile kullanıcı tarafından
  doğrulandı ve onaylandı. **18b** (Layer B inceleme kararları)
  **ACTIVE / NEXT**. **18c** (Row 15 yapılandırılmış avukat talebi
  girişi) henüz BAŞLAMADI.

### Row 9 — Issue Spotting Agent (DONE / LOCKED — checkpoint özeti)

Deterministik Policy/Engine (`issue_spotting_policy.py`, `issue_spotting_engine.py`) +
LLM Agent katmanı (`issue_spotting_agent.py`, yapılandırılmış sinyal + deterministik
template rendering, free-text safety + network safety gate) + Validator
(`issue_spotting_validator.py`) + Approval (`issue_spotting_approval.py`) tamamlandı.
`case_0001` için canonical `data/cases/case_0001/issues/issues.json` insan onayıyla
(`--approve`) promote edildi (6 deterministic issue candidate; agent bu approval'a
katkı sağlamadı). Issue candidate'lar hâlâ verified fact/legal conclusion/case
outcome/deadline determination DEĞİLDİR (bkz. Prensip 7, 8; `case_issue_spotting.schema.json`
içindeki `status: "candidate"` const kısıtı).

### Row 10 — Legal Research Agent (DONE / LOCKED — checkpoint özeti)

Deterministik Policy/Engine (`legal_research_policy.py`, `legal_research_engine.py`,
`resolve_provision_locator()` ortak çözümleyici) + Issue-Driven Discovery katmanı
(`legal_research_discovery.py`, `query_parser.py`/`retriever.py` mevcut altyapısı
üzerinden, üç ayrı execution-state semantiğiyle: `retrieval_not_run` /
`retrieval_failed` / `no_research_evidence`) + LLM Agent katmanı
(`legal_research_agent.py`, yapılandırılmış sinyal + deterministik template
rendering, free-text safety + network safety gate) + Validator
(`legal_research_validator.py`) + Approval (`legal_research_approval.py`) tamamlandı.
`case_0001` için canonical `data/cases/case_0001/research/research.json` insan
onayıyla (`--approve`) promote edildi (6 research candidate: 5 `provision_resolution`,
1 `issue_driven_discovery`; agent katkısı 0). `finding_status` alanı yalnız
citation/provision-level teknik çözümü ifade eder — hiçbir değer hukuki meselenin
çözüldüğü, hükmün uygulanabilir olduğu veya case outcome anlamına GELMEZ (bkz.
Prensip 7; `case_legal_research.schema.json` içindeki `finding_status`/`status`
alan açıklamaları).

### Row 11 — Case Law Agent (DONE / LOCKED — checkpoint özeti)

Deterministik Policy/Discovery katmanı (`case_law_policy.py`, `case_law_discovery.py`,
`build_case_law_intent()` — citation-öncelikli, `legal_research_discovery.build_research_intent()`
fallback'i yeniden kullanır) + coverage/decision ayrımı (her canonical issue için tam
1 coverage kaydı, `execution_state ∈ {retrieval_not_run, retrieval_failed,
no_case_law_evidence, retrieval_completed}`; her issue için 0..N bağımsız
`source_document_id`'ye göre dedup edilmiş decision kaydı, her decision canonical
`documents.json`'a karşı çift aşamalı grounding ile doğrulanır) + ayrı
`agent_suggestion` tipi (şema seviyesinde hiçbir mahkeme-metadata alanı yok) + LLM
Agent katmanı (`case_law_agent.py`, yapılandırılmış sinyal + free-text safety +
network safety gate) + Validator (`case_law_validator.py`, 14 test) + Approval
(`case_law_approval.py`) tamamlandı. `case_0001` için canonical
`data/cases/case_0001/case_law/case_law.json` insan onayıyla (`--approve`) promote
edildi (6 coverage kaydı, tümü `execution_state: retrieval_not_run`; 0 decision;
0 agent suggestion — network bu session'da hiç kullanılmadı). Decision candidate'lar
ve agent suggestion'lar hâlâ verified fact/legal conclusion/case outcome DEĞİLDİR
(bkz. Prensip 7; `case_case_law.schema.json` içindeki `requires_human_review: true`
const kısıtı ve `applicability_result` alanının yalnızca `null`/`"unknown"`/
`"needs_review"` değerlerini kabul etmesi).

### Row 12 — Evidence Agent (DONE / LOCKED — checkpoint özeti)

**Status: LOCKED.**

**Schema boundary** — `data/case_evidence.schema.json`, dört ayrı üst-düzey alan:
`evidence_coverage` (issue başına tam 1), `evidence_candidates` (0..N, issue+fact+
document+source_location+relationship_candidate atomik üçlüsü), `evidence_agent_suggestions`
(0..N, yalnız şemada tanımlı 6 suggestion türünden biri), `analysis_metadata`
(issues/facts/active-documents input hash manifesti).

**Deterministic source boundary** — Evidence Agent (`evidence_discovery.py` +
`evidence_policy.py`) yalnız canonical issues (`issues.json`), approved canonical
facts (`*/extractions/facts.json`, `timeline_validator.load_canonical_fact_index`
üzerinden) ve active canonical case document kayıtları (`*/document.json`,
`case_document_validator.load_case_documents` üzerinden) üzerinde çalışır; yeni
issue/fact/document/source_location icat edemez — allowlist tamamen bu üç canonical
kaynaktan deterministik olarak türetilir.

**Agent boundary** — `evidence_agent.py`, LLM'i yalnız deterministik allowlist
içinden `relationship_candidate ∈ {supports, contradicts}` seçimine ve izin verilen
6 suggestion türünden birini önermeye sınırlar (`ALLOWED_LLM_CANDIDATE_KEYS`/
`ALLOWED_LLM_SUGGESTION_KEYS` allowlist'i + free-text safety + network safety gate).
Agent candidate'a `confidence`/`strength`/`priority`/`admissibility` gibi hukuki/
delil ağırlığı alanı EKLEYEMEZ (şema düzeyinde bu alanlar `evidence_candidate`
tipinde TANIMLI DEĞİLDİR). Agent yalnız `review_state`/`suggestion_review_state`
için `needs_review` üretebilir; `confirmed`/`rejected`/`accepted_for_follow_up`/
`dismissed` agent/engine tarafından ASLA üretilemez (bkz. `evidence_engine.py`
`validate_engine_output_semantics`, `evidence_approval.py`
`validate_approval_semantics`).

**Layer A / Layer B separation (LOCKED contract)** — İki bağımsız insan-onay
katmanı:

- **Layer A** (`evidence_approval.py`): yalnız pending evidence package →
  canonical evidence package promosyonunu yapar (Row 9-11 deseni: backup → atomic
  write → post-write validation → SHA256 eşitliği → approval audit → rollback).
  Layer A candidate/suggestion için semantic review YAPMAZ; yalnız
  `review_state`/`suggestion_review_state`'i hâlâ `needs_review` olan bir paketi
  kabul edebilir.
- **Layer B** (`evidence_review.py`): yalnız zaten canonical olmuş bireysel
  candidate/suggestion kayıtlarının `needs_review → confirmed|rejected` (candidate)
  veya `needs_review → accepted_for_follow_up|dismissed` (suggestion) geçişini
  yapar; pending package approval mekanizması DEĞİLDİR.
- Audit/rollback bağımsızlığı: Layer A `reviews/` (`*.approval.json`,
  `evidence.json.before_approval_*.bak`); Layer B ayrı alt dizin
  `reviews/evidence_reviews/` (`*.review_audit.json`,
  `evidence.json.before_review_*.bak`) — farklı fonksiyonlar, farklı `audit_type`.

**Safety** — network varsayılan KAPALI (`network_allowed=False` varsayılan); gerçek
LLM/API çağrısı yalnız `--with-agent` + `--allow-network` ile; Fake/injected client
test amaçlı serbest; allowlist grounding + free-text safety zorunlu; stale-input hash
validation zorunlu (`analysis_metadata` içindeki issues/facts/active-documents
hash'leri güncel canonical veriyle eşleşmezse validator FAIL döner); canonical
`evidence.json` insan onayı (Layer A `--approve`) olmadan OLUŞTURULAMAZ.

**Pending baseline checkpoint** — `case_0001` için yalnız pending analiz üretildi
(`data/cases/case_0001/evidence/evidence_case_0001_v1.json.pending`, SHA256
`084056de5a0242f4bac57c0916e532acba581e2eb8418d0d54187c37ec2acdce`): 6 coverage
(canonical issue ile 1:1), 0 candidate, 0 suggestion, `execution_state:
analysis_not_run` × 6 (network/agent bu session'da hiç kullanılmadı). **Canonical
`evidence.json` HENÜZ OLUŞTURULMADI** — Layer A approval bu checkpoint'e kadar
kasıtlı olarak çalıştırılmamıştır; bu satırın kendisi Row 12'nin mimari/contract
LOCK'udur, canonical veri promosyonu ayrı ve sonraki bir kullanıcı onayı gerektirir.

Future row'lar (Row 13+) Row 12 contractını (şema, deterministic source boundary,
agent boundary, Layer A/Layer B ayrımı) sessizce değiştiremez veya yeniden
yorumlayamaz. **Row 12 contract changes require an explicit unlock/review before
modification.**

### Row 13 — Argument Agent (DONE / LOCKED — checkpoint özeti)

Normalized `claim` / `counterargument` / `rebuttal` modeli (ayrı flat array'ler,
ID referanslarıyla bağlı — gömülü/nested argument graph DEĞİL) + deterministik
`argument_coverage` (issue başına tam 1 kayıt) + deterministik allowlist
(`argument_discovery.py`, canonical issue/approved fact/(varsa) canonical
evidence-research-case_law-timeline-deadline'dan; `allowlist_count` validator
tarafından aynı saf fonksiyonla bağımsız yeniden hesaplanır, pending/canonical
değerine güvenilmez) + `evidence_agent_suggestions`'a paralel, kendi yapısal
izolasyonuna sahip `argument_agent_suggestions` (fact/document grounding alanı
KAZANMAZ; free-text `grounded_explanation` hem agent hem validator katmanında
bağımsız guard setinden geçer: forbidden phrase, ID-smuggling, unverified quote,
unsupported date/amount) + deterministik `depends_on_unconfirmed_evidence` /
`depends_on_unconfirmed_authority` / `missing_legal_authority` bayrakları (agent
set edemez) + versioned structural update ile safe review carry-forward
(fingerprint + upstream hash birebir eşleşmesi + önceki review_state
'needs_review' olmaması şartıyla, ayrı `history/carry_forward/*.json` audit
kaydıyla).

**Layer A / Layer B** — Layer A (`argument_approval.py`) pending → canonical
promosyonunu Row 9-12 deseniyle tamamladı. Layer B (`argument_review.py`)
**top-down parent-dependency** ile LOCKED: bir child (counterargument'ın parent'ı
claim; rebuttal'ın parent'ı counterargument) ancak parent terminal state'e
(`confirmed`/`rejected`) geldiyse review edilebilir; parent `rejected` ise child
YALNIZ `rejected` olabilir (`confirmed` reddedilir). **Bu session'da Layer B
üzerinde gerçek bir review mutation ÇALIŞTIRILMADI** — yalnız izole tempdir
self-testleri çalıştı.

**Canonical promosyon** — `case_0001` için canonical
`data/cases/case_0001/arguments/arguments.json` insan onayıyla (`--approve`)
promote edildi: `coverage=6`, `claims=0`, `counterarguments=0`, `rebuttals=0`,
`suggestions=0`, tüm `execution_state: analysis_not_run` (agent bu session'da hiç
çalıştırılmadı). Pending ve canonical SHA256 birebir aynı:
`24c2637663d40803f6720ce43e91ac02a190b82dbb4428fe5875829077bc0742`. Approval audit
kaydı `data/cases/case_0001/arguments/reviews/` altında mevcut.

**Final doğrulama** — validator 17/17, agent 26/26, engine 14/14, approval 10/10,
review 9/9 PASS; Rows 1-12 regresyon testleri PASS; bu session boyunca hiçbir
gerçek network/API çağrısı yapılmadı. Claim/counterargument/rebuttal/suggestion
candidate'lar hâlâ verified fact/legal conclusion/nihai hukuki sonuç/case outcome
DEĞİLDİR (bkz. Prensip 7; `case_arguments.schema.json`'da confidence/strength/
priority/admissibility/sufficiency/win_probability/recommended_outcome/
success_probability alanlarının hiçbirinin tanımlı olmaması).

### Row 14 — Risk / Strategy Agent (DONE / LOCKED — checkpoint özeti)

**Schema boundary** — `data/case_risk_strategy.schema.json`: `risk_coverage[]`
(canonical issue başına tam 1 kayıt, 6/6) ve `case_scope_coverage[]` (7 sabit
scope başına tam 1 kayıt: `documentary_record, fact_verification,
timeline_verification, deadline_calculability, legal_authority_coverage,
case_law_coverage, procedural_posture`) birbirinden ayrı, saf deterministik
muhasebe katmanlarıdır — issue-seviyesi ve case-geneli kapsam ayrı ayrı izlenir.
`risk_candidates[]` (`risk_kind ∈ {identified, gap}`), `strategy_candidates[]`
(`record_kind: "suggested_next_action"` const, `requires_human_decision: true`
const) ve `risk_strategy_agent_suggestions[]` üç ayrı ve yapısal olarak izole
üst-düzey alandır.

**Deterministic gap generation ve proof-of-looking sınırı** — Gap risk'ler
(`absence_basis` yalnızca 6 sabit değerden biri: `no_confirmed_evidence_for_issue,
no_resolved_legal_authority_for_issue, no_grounded_case_law_for_issue,
deadline_not_computable, anchor_event_unverified, no_confirmed_argument_for_issue`)
YALNIZ deterministik motor tarafından üretilir — agent asla gap risk
seçemez/üretemez. Bir gap risk yalnız upstream kaynağın KENDİ gerçek
execution/finding-status alanı gerçekten tamamlanmış-ama-boş bir durum
gösterdiğinde üretilebilir (ör. Row 11 `case_law_coverage.execution_state=
no_case_law_evidence`); salt dosya yokluğu veya `*_not_run`/`*_failed`
durumları asla bir gap risk üretmez, yalnızca coverage/snapshot sinyali veya
agent suggestion üretebilir.

**Dokuz canonical input hash ve stale-input kontrolü** —
`analysis_metadata` içinde `issues_input_hash, facts_input_hash,
documents_input_hash, timeline_input_hash, deadline_input_hash,
legal_research_input_hash, case_law_input_hash, evidence_input_hash,
arguments_input_hash`; `evidence_input_hash` case_0001 için `null` (canonical
`evidence.json` henüz yok — bkz. Row 12), diğer 8 hash non-null. Validator bu
hash'leri güncel canonical girdilerle bağımsız yeniden hesaplayıp stale-input
durumunda FAIL döner.

**Birleşik yasak ifade politikası ve bağımsız validator** —
`risk_strategy_policy.ALL_FORBIDDEN_PHRASES`, Row 9'un prosedürel/deadline-
kesinliği ifadeleriyle Row 14'ün kazanma-olasılığı/kesinlik/garanti
ifadelerinin birleşimidir; validator ve engine bu TEK paylaşılan listeyi ve
paylaşılan `check_forbidden_phrases` fonksiyonunu import eder (agent'ın
yüksek-seviye `check_text_safety()` sarmalayıcısı asla import edilmez —
yalnız düşük seviye saf fonksiyonlar paylaşılır). `risk_description`/
`strategy_description` ayrıca deterministik template renderer'ın çıktısıyla
byte-for-byte eşitlik kontrolünden geçer (hem engine hem validator seviyesinde,
bağımsız olarak).

**Ayrı semantic dedup/content fingerprint'leri** — Her risk/strategy/suggestion
için iki ayrı fingerprint hesaplanır: `*_dedup_fingerprint` (serbest metin
hariç, aynı-çalışma içi duplicate tespiti için) ve `*_content_fingerprint`
(serbest metin + referanslar + bayraklar dahil, yalnız Layer B safe
carry-forward eşleştirmesi için) — reworded bir kayıt asla önceki bir insan
review_state'ini sessizce miras almaz.

**Güvenli, diskten yeniden yüklemeyle doğrulanmış review carry-forward** —
Carry-forward mantığı, izole bir tempdir'de gerçek Layer A (`run_approve`) ve
gerçek Layer B (`apply_review_transition`) çağrıları üzerinden uçtan uca
doğrulandı: canonical JSON diskten `json.loads()` ile taze okunup aynı-içerik
yeniden üretimde review_state'in korunduğu, farklı-metin yeniden üretimde ise
`needs_review`'a resetlendiği ayrı ayrı kanıtlandı.

**Layer A / Layer B** — Layer A (`risk_strategy_approval.py`) `case_0001` için
canonical promosyonu **tamamladı** (Row 9-13 deseni: backup → atomic write →
post-write validation → SHA256 eşitliği → approval audit → rollback). Layer B
(`risk_strategy_review.py`) many-to-many parent-dependency kurallarıyla
(R1: needs_review herhangi bir parent varsa child review edilemez; R2: tüm
parent'lar rejected ise yalnız dismissed; R3: tüm parent'lar terminal ve en az
1 confirmed ise hem accepted_for_follow_up hem dismissed insan tercihine
bırakılır; R4: otomatik cascade yok; R5: audit tam `parent_states_at_review_time`
haritası taşır; R6: suggestion yaşam döngüsü risk/strategy parent zincirinden
tamamen bağımsız) doğrulandı — **bu session'da Layer B üzerinde gerçek bir
review mutation ÇALIŞTIRILMADI**, yalnız izole tempdir self-testleri çalıştı.

**Canonical promosyon** — `case_0001` için canonical
`data/cases/case_0001/risk_strategy/risk_strategy.json` insan onayıyla
(`--approve`) promote edildi: `risk_coverage=6`, `case_scope_coverage=7`,
`risk_candidates=0`, `strategy_candidates=0`, `risk_strategy_agent_suggestions=0`.
Risk execution_state × 6 = `analysis_not_run`, strategy execution_state × 6 =
`analysis_not_run`, case-scope execution_state × 7 = `analysis_not_run`. **Bu
dağılım "risk yok" veya "risk analizi tamamlandı" sonucu DEĞİLDİR** — agent bu
session'da hiç çalıştırılmadı; bu saf bir offline baseline'dır (bkz. Prensip 7).
Pending ve canonical SHA256 birebir aynı:
`4b5cc8cfa0b0148ae13e84a96cbc94d2f022c81defba319aa139ee0fd35ceb7f`. Approval
audit kaydı `data/cases/case_0001/risk_strategy/reviews/
risk_strategy_case_0001_v1_20260904_112002.approval.json`'da mevcut.

**Final doğrulama** — validator 30/30, engine 24/24, approval 8/8, review
11/11 PASS; post-approval final lock-readiness review'da tüm dört self-test
paketi canonical dosya gerçekten mevcutken yeniden çalıştırılıp aynı sonuçla
doğrulandı, canonical üzerinde bağımsız validator ve approval semantic-guard
salt-okunur olarak PASS verdi, `data/` dosya manifesti ve git index turlar
arasında değişmedi. Risk/strategy/suggestion candidate'lar hâlâ verified fact/
legal conclusion/nihai hukuki sonuç/case outcome DEĞİLDİR (bkz. Prensip 7;
`case_risk_strategy.schema.json`'da confidence/strength/severity/risk_score/
win_probability gibi alanların hiçbirinin tanımlı olmaması).

### Row 15 — Drafting Agent (DONE / LOCKED — checkpoint özeti)

**Schema boundary** — `data/case_drafting.schema.json`: beş ayrı üst-düzey alan
birbirinden kesin olarak izole: `draft_coverage[]` (issue başına tam 1 kayıt,
6/6), `draft_sections[]` (`section_type ∈ {facts_summary, legal_basis,
argument_summary, request, procedural_history}`), `draft_source_refs[]`
(section'lara ID referanslarıyla bağlı, gömülü değil), `draft_review_notes[]`
(deterministik gap/disputed/agent-suggested-citation notları) ve
`draft_agent_suggestions[]` (0..N, kendi yapısal izolasyonuna sahip).
`submission_status` HER section'da SABİT `"draft_only"`dır.

**Lawyer-input / selection sınırları ve talep yetkilendirmesi (Q1/Q2 ayrımı)** —
İki AYRI soru kesin olarak ayrılır: Q1 (`is_grounded_advocacy` — dayanak var
mı?) confirmed argüman referansı VEYA geçerli avukat girdisiyle karşılanabilir;
Q2 (`request_authorized` — avukat AÇIKÇA bu ÜRETİMİ istedi mi?) YALNIZ yapısal
olarak geçerli `request_input` (`is_valid_request_input` — dict, yalnız
`request_type`/`request_text`, ikisi de trim sonrası boş olmayan string) VEYA
boş/whitespace olmayan `lawyer_provided_text` (`has_valid_lawyer_text`) ile
karşılanabilir. Confirmed argument/risk/strateji TEK BAŞINA Q2'ye asla yetki
veremez; `section_type="request"` üretimi Q2 olmadan hem agent hem bağımsız
validator katmanında reddedilir.

**Canonical kaynak uygunluğu, bağımsız doğrulama, kaynağa-bağlı render,
stale-source review güvencesi** — Section/suggestion serbest metni yalnız
canonical issue allowlist'inden (`drafting_discovery.build_allowlists_for_issues`,
Row 4-14 üzerinden türetilen fact/timeline/deadline/legal_research/case_law/
evidence/claim/counterargument/rebuttal/risk/strategy eligible-set'i) atıf
alabilir; her referans `direct` (confirmed/aktif) veya `flagged` (henüz
incelenmemiş/confirmed olmayan) olarak sınıflandırılır (`is_ref_direct`), ve
her flagged referansın `claim_span`'i section_text içinde GERÇEKTEN var olmalı
VE kendi içinde bir belirsizlik ifadesi (`HEDGE_PHRASES`) taşımalıdır
(`find_refs_missing_hedge`) — tek bir genel uyarı tüm flagged referansları
meşrulaştırmaz. `contains_unreviewed_source` bağımsız olarak yeniden
hesaplanır, agent'ın kendi bildirdiği değere güvenilmez.

**Ghost-ID/beyan edilmemiş referans kontrolü ve sınırlı sonuç-garantisi
kontrolü** — `find_id_reference_issues` (Row 15'e özgü), serbest metindeki
gerçek canonical ID biçimlerini (13 bilinen prefix: `fact_`, `timeline_event_`,
`deadline_`, `research_`, `case_law_decision_`, `evidence_candidate_`,
`argument_claim_`, `argument_counter_`, `argument_rebuttal_`, `risk_`,
`strategy_`, `issue_`, `draft_section_`) tarayıp üç kategoriye ayırır: declared
(izinli), `smuggled` (gerçek ama başka issue'ya ait veya beyan edilmemiş),
`fabricated` (canonical'da hiç yok) — ikisi de reddedilir, hem agent hem
bağımsız validator'da, hem section hem suggestion metninde. Ayrıca
`OUTCOME_GUARANTEE_PATTERN`, sabit ifadelerin (Row 14'ten miras
`UNIVERSAL_FORBIDDEN_PHRASES`) ötesinde kesinlik-zarfı + kazan/kaybet fiil
çekimi kombinasyonlarını (normalize edilmiş metinde, aynı cümle içinde) yakalar
— meşru, yetkilendirilmiş savunma/talep dili (ör. "işlemin iptalini talep
ediyoruz") bu kontrollerden ETKİLENMEZ, ayrı bir bağlamsal kapı
(`CONDITIONAL_ADVOCACY_PHRASES`, yalnız `section_type='request'` VE Q1
karşılanmışken) ile korunur.

**Layer A / Layer B** — Layer A (`drafting_approval.py`) pending → canonical
promosyonunu Row 9-14 deseniyle (backup → atomic write → post-write validation
→ semantic guard → SHA256 eşitliği → audit) tamamladı. **Bu session'da Layer B
(`drafting_review.py`) üzerinde gerçek bir review mutation ÇALIŞTIRILMADI** —
yalnız izole tempdir self-testleri çalıştı.

**İçerik-duyarlı review carry-forward ve canonical mevcutken izole regresyon**
— Row 13/14 desenine paralel `*_dedup_fingerprint`/`*_content_fingerprint`
ayrımı ve versioned carry-forward korunur. Canonical `drafting.json` promote
edildikten SONRA dört self-test paketi tekrar izole biçimde (approval/review
kendi `tempfile.TemporaryDirectory()`'sine yönlendirilerek) çalıştırılıp gerçek
case_0001 `drafting/` ağacının değişmediği ayrı ayrı doğrulandı.

**Final doğrulama** — engine 59/59, validator 6/6, approval 8/8, review 10/10
PASS; canonical `drafting.json` üzerinde bağımsız tam validator ve approval
semantic-guard salt-okunur PASS verdi. Pending ve canonical SHA256 birebir
aynı: `eee885ddc6bd263dc5aeb8fe95fad74a885f0d49dfb33ef5e91faeddd1725536`.
Approval audit kaydı
`data/cases/case_0001/drafting/reviews/drafting_case_0001_v1_20260904_171024.approval.json`'da
mevcut.

**Canonical promosyon (offline baseline)** — `case_0001` için canonical
`data/cases/case_0001/drafting/drafting.json` insan onayıyla (`--approve`)
promote edildi: `draft_coverage=6` (canonical issue setiyle 1:1),
`selection_scope=selection_not_provided` ×6, `execution_state=
analysis_not_run` ×6, `block_reason=blocked_missing_lawyer_input` ×6,
`draft_sections=draft_source_refs=draft_review_notes=draft_agent_suggestions=0`.
On canonical input hash'ten `evidence_input_hash=null` (canonical
`evidence.json` henüz yok — bkz. Row 12), diğer dokuzu (`issues, facts,
documents, timeline, deadline, legal_research, case_law, arguments,
risk_strategy`) non-null; ayrı olarak `lawyer_input_hash=null`. **Bu dağılım
"taslak üretildi" veya "hukuki analiz tamamlandı" anlamına GELMEZ** — bu
session'da avukat girdisi sağlanmadı, Drafting Agent hiç çalıştırılmadı; bu
saf bir offline baseline'dır (bkz. Prensip 7). Section/suggestion candidate'lar
hâlâ verified fact/legal conclusion/nihai hukuki sonuç/dava sonucu DEĞİLDİR;
lexical/ID/outcome-garantisi kontrolleri metnin TAM anlamsal doğruluğunu
KANITLAMAZ, ve `lawyer_input_hash` yalnız içerik tutarlılığı sağlar — avukat
kimliğinin doğrulanması (authentication) anlamına GELMEZ.

### Row 16 — QA Agent (DONE / LOCKED — checkpoint özeti)

**Schema boundary** — `data/case_qa.schema.json`: `qa_coverage[]` (11 sabit
scope — `documents, facts, timeline, deadline, issues, legal_research,
case_law, evidence, arguments, risk_strategy, drafting` — başına tam 1
kayıt), `qa_check_results[]` (12 sabit `check_id` registry'sinden üretilen
instance'lar), `qa_agent_suggestions[]` (0..N, kendi yapısal izolasyonuna
sahip), `analysis_metadata` (dependency manifest + pre/post-scan manifest
karşılaştırması). 11 scope ve 12 check_id `qa_policy.py`'de FIXED REGISTRY
olarak donduruldu — yeni scope/check icat edilmez. `evidence` tek opsiyonel
scope'tur (Row 12'de canonical `evidence.json` henüz yok); `documents`/
`facts` çok-dosyalı aile, diğer 9 tek-dosyalı.

**Deterministik check katmanı** — 12 check_id, Row 1-15'in canonical/pending
artefaktlarını okuyup artefakt varlığı/okunabilirlik/JSON geçerliliği,
üyelik enumerasyonu, şema+referans geçerliliği, stale-input hash
tutarlılığı, coverage completeness/1:1, execution-state muhasebesi,
bekleyen human-review backlog sayımı ve yasaklı ifade/sonuç-garantisi
yokluğunu kontrol eder. Alan isimleri hiçbir zaman zorla ortaklaştırılmaz —
ör. `risk_strategy` için `risk_execution_state`/`strategy_execution_state`/
case-scope `execution_state` üç ayrı dağılım olarak korunur; `case_law`'ın
review-lifecycle alanı olmadığı için #11
(`pending_human_review_backlog_count`) bu scope'ta
`not_applicable`/`no_review_lifecycle_field_in_schema` döner — boş küme
icat edilmez.

**QA'ya özgü ID-biçimi ve metin-güvenlik izolasyonu** — Row 15'in
`ID_SHAPE_PATTERN`'i (`drafting_policy.py`, LOCKED) yalnız Row 1-15 prefix
ailesini tanır; `qa_check_result_`/`qa_agent_suggestion_` bu listede yoktur
ve Row 15 değiştirilemediği için QA kendi dar `QA_ID_SHAPE_PATTERN`'ini ve
üç-kategori (declared/smuggled/fabricated) sınıflandırmasını `qa_policy.py`
içinde ayrı tanımlar. QA'nın kendi serbest metni (agent suggestion
`grounded_explanation`) için yasaklı-ifade/sonuç-garantisi kontrolü, Row
15'in `check_forbidden_phrases_context` fonksiyonu sabit
`section_type="facts_summary"`, `is_grounded_advocacy=False` ile (yani her
zaman en katı mod) çağrılarak yeniden kullanılır — kilitli fonksiyon
değiştirilmez.

**Bağımsız validator** — `qa_validator.py`, kayıtlı
`qa_check_results`/`qa_coverage`'a güvenmez; `qa_engine.build_qa_engine_output()`'u
yeniden çağırıp kayıtla tek tek karşılaştırır (tahrif edilmiş/gizlenmiş/
eksik/fazladan kayıt tespiti) ve stale snapshot'ı ayrı bir hata sınıfı
olarak (tahrifat DENMEDEN) sınıflandırır. Not: bu "bağımsızlık" kayıtlı
veriye karşı tahrifat/tutarsızlığa karşıdır — `qa_engine.py`'nin check
mantığındaki olası bir hataya karşı değildir, çünkü doğrulama AYNI
fonksiyonları yeniden çağırır.

**Layer A / Layer B** — Layer A (`qa_approval.py`) pending → canonical
promosyonunu Row 9-15 deseniyle (backup → pre/post-write manifest
karşılaştırması → atomic write → post-write validation → semantic guard →
SHA256 eşitliği → audit) tamamladı. Layer B (`qa_review.py`) bu session'da
çalıştırılmadı — `qa_agent_suggestions=0` olduğu için henüz review
edilecek bir kayıt yok.

**Final doğrulama** — qa_engine 13/13, qa_validator 9/9, qa_approval 9/9,
qa_review 8/8, qa_agent 7/7 PASS (toplam 46/46); self-test'ler gerçek
`case_0001/qa/` ağacına hiç dokunmadığını ayrıca doğruladı; implementasyon
öncesi/sonrası git-tracked dosya SHA256 manifesti birebir aynı kaldı
(yalnız 9 yeni dosya eklendi, hiçbiri var olan dosyayı değiştirmedi/
silmedi).

**Canonical promosyon (offline baseline)** — `case_0001` için canonical
`data/cases/case_0001/qa/qa.json` insan onayıyla (`--approve`) promote
edildi: `qa_coverage=11`, `qa_check_results=83`
(`passed=72, blocked=7, not_applicable=4, failed=0, error=0`),
`qa_agent_suggestions=0`, `qa_generation_status=completed`,
`qa_agent_execution_status=not_requested` (agent bu session'da hiç
çağrılmadı — yalnız izole self-testlerde Fake client ile test edildi).
7 `blocked` sonucun TAMAMI `evidence` scope'undadır ve tek nedeni
`prerequisite_unmet`/`artifact_absent`'tir — yani Row 12'de canonical
`evidence.json`'ın henüz oluşturulmamış olmasının doğrudan, deterministik
sonucudur (bkz. Row 12 checkpoint), başka bir upstream hata değildir.
Pending ve canonical SHA256 birebir aynı:
`a4af057af4e21e6994823378bae6b1127a799cbc6db3ca7dc1b4b207d31aec40`.
Approval audit kaydı
`data/cases/case_0001/qa/reviews/qa_case_0001_v1_20260904_202837.approval.json`'da
mevcut. **Bu dağılım "dosyalar hatasız" veya "QA analizi tamamlandı"
anlamına GELMEZ** — agent bu session'da hiç çalıştırılmadı, 7 blocked
sonuç yalnızca Row 12'nin bilinen eksik canonical girdisini yansıtır; bu
saf bir offline baseline'dır (bkz. Prensip 7).

### Row 17 — Product Orchestrator Agent (DONE / LOCKED — checkpoint özeti)

**Kapsam kararı (kullanıcı, 2026-09-04): Seçenek A** — Row 17 **saf deterministik
birleştirmedir, agent/LLM katmanı YOKTUR**. `case_view.json`, Row 1-16'nın zaten
canonical olan çıktılarını issue etrafında yeniden gruplayan **tek bir salt-okunur
rollup belgesidir** — diğer row'ların aksine ayrı `*_candidates`/`*_agent_suggestions`
üst-düzey alanları YOKTUR; agent/LLM'in hiçbir zaman dokunmadığı bir katmandır (bkz.
Prensip 1/2/7).

**Schema boundary** — `data/case_view.schema.json`: `case_summary`,
`timeline_summary`, `deadline_panel`, `issue_panel[]` (canonical issue başına tam 1
kayıt, her biri case_law/evidence/arguments/risk_strategy/drafting alt-nesnelerini
ve `qa_related_check_result_ids`'i taşır), `evidence_panel` (case-geneli özet),
`case_scope_panel` (Row 14'ün 7 sabit `case_scope_coverage` girdisi — issue-scoped
DEĞİLDİR, `issue_panel`'e dahil edilmez), `open_items_panel[]` (var olan
`requires_human_review`/`needs_review`/`qa_result∈{blocked,failed}` alanlarının
yeniden listelenmesi — YENİ bir sınıflandırma icat edilmez), `qa_health_panel`
(qa.json'un kendi özetine güvenmeden `qa_check_results`'tan bağımsızca yeniden
sayılmış dağılım), `analysis_metadata.dependency_manifest` (11 sabit kaynağın
artifact_state + raw_byte_sha256'ı). 11 sabit kaynak `orchestrator_policy.py`'de
FIXED REGISTRY: `case, timeline, deadline, issues, legal_research, case_law,
evidence, arguments, risk_strategy, drafting, qa` — `evidence` tek opsiyonel
kaynaktır (Row 12'de canonical `evidence.json` henüz yok).

**Dolaylı linkajlar, tekilleştirilmeden korunur** — `strategy_candidates`'ın
`source_issue_id` alanı YOKTUR; issue'ya yalnız `addresses_risk_ids` →
`risk_candidates[].source_issue_id` üzerinden dolaylı bağlanır (bir strateji birden
fazla issue'nun riskini adresliyorsa, HEPSİ altında görünür). `draft_sections[]`
`source_issue_ids` (ÇOĞUL) taşır — gerçek çoklu-üyelik, kopyalama hatası değildir;
`group_by_issue_id_membership()` bu ayrımı ayrı bir fonksiyon olarak taşır
(`group_by_issue_id()`'den kasıtlı olarak ayrı).

**QA → issue linkaj politikası (kullanıcı kararı, 2026-09-04)** — Bir
`qa_check_result` YALNIZ `related_issue_id` alanı dolu ve deterministik olarak
çözülebiliyorsa `issue_panel[].qa_related_check_result_ids`'e eklenir; bağlantı
kurulamıyorsa kayıp DEĞİLDİR — `qa_health_panel` (toplam sayaç) ve gerektiğinde
scope-seviyeli `open_items_panel`'de görünmeye devam eder. Metinden veya isim/kelime
benzerliğinden issue ilişkisi ASLA tahmin edilmez. **Tespit edilen gerçek durum**:
`qa_engine.py` (Row 16, LOCKED) şu an `related_issue_id`'yi HİÇBİR check için
doldurmuyor — case_0001'in 83 check_result'ının tamamında bu alan `null`'dır (kod
incelemesiyle doğrulandı: `qa_engine.py` içinde bu parametreye gerçek bir değer
geçen tek bir çağrı yok). Bu Row 17'nin hatası DEĞİLDİR, Row 16'nın önceden var
olan, bilinen bir sınırıdır; **şimdilik yamanmamasına karar verildi**. İleride
gerçek ihtiyaç doğarsa Row 16 için ayrı bir bakım yaması değerlendirilecek ve olası
alan TEKİL `related_issue_id` değil, ÇOĞUL `related_issue_ids[]` olacaktır (bir
check birden fazla issue'yu ilgilendirebilir).

**Bağımsız validator — Row 16'dan farklı mekanizma, aynı disiplin** —
`orchestrator_validator.py`, kayıtlı `case_view`'a güvenmez;
`orchestrator_engine.build_case_view()`'ı yeniden çağırıp üç zaman-damgası alanı
(`generated_at`, `analysis_metadata.scan_started_at/scan_completed_at`) HARİÇ **tam
belge eşitliği** karşılaştırması yapar (genel-amaçlı `_deep_diff()` ile yol-etiketli
fark raporu). Row 16'nın check-by-check karşılaştırmasından farklıdır çünkü Row 17
saf deterministik bir birleştirmedir — aynı girdi her zaman birebir aynı çıktıyı
ÜRETMEK ZORUNDADIR; herhangi bir fark tahrifat/tutarsızlık şüphesidir. Stale
snapshot (11 kaynağın güncel SHA256'sıyla uyuşmazlık) ayrı bir hata sınıfı olarak
(tahrifat DENMEDEN) sınıflandırılır.

**`generation_status` — geniş şema, dar motor, daha dar promosyon (üç ayrı
kullanıcı kararı)** — Şema 4 değer taşır (`completed, completed_with_errors,
aborted_source_changed, failed` — Row 16 ile aynı sözlük, kasıtlı olarak
DARALTILMADI), ama v1 saf deterministik motoru yalnız `completed`/`failed`
üretebilir (`orchestrator_validator.validate_generation_status_consistency` bunu
ayrıca doğrular). **Layer A (`orchestrator_approval.py`) yalnız
`generation_status='completed'` olan bir case_view'i canonical'a promote eder** —
`'failed'` (bir veya daha fazla zorunlu kaynak eksik) kendi içinde tutarlı ve
şema-geçerli olsa BİLE reddedilir; motor yine de HER ZAMAN `'failed'` için
şema-geçerli, hatasız bir case_view üretmeye devam eder (bu yalnız
görüntüleme/hata-toleransı içindir, promosyon için değil).

**Layer A / Layer B** — Yalnız Layer A vardır (`orchestrator_approval.py`, Row 9-16
deseniyle: backup → PRE/POST-write bağımlılık karşılaştırması → atomic write →
post-write validation → semantic guard → SHA256 eşitliği → audit → rollback).
**Layer B YOKTUR** — case_view'de bireysel review_state taşıyan bir kayıt tipi
bulunmaz (saf rollup, kendi review lifecycle'ı yok); bir alt-kaydın review_state'i
DEĞİŞTİRİLECEKSE bu her zaman kendi kaynak row'unda (ör. `evidence_review.py`) olur,
Row 17'de DEĞİL.

**Final doğrulama** — engine 10/10, validator 8/8, approval 10/10 PASS (toplam
28/28); tüm self-testler bu session'da case_0001'in gerçek canonical verisiyle
(makineye bağlı device bridge üzerinden dosyalar bizzat çekilip izole bir ortamda
çalıştırılarak) doğrulandı, salt terminal çıktısına güvenilmedi. Kullanıcı da
kendi makinesinde aynı üç self-test'i bağımsız olarak çalıştırıp birebir aynı
sonucu (10/10, 8/8, 10/10) aldı.

**Canonical promosyon** — `case_0001` için canonical
`data/cases/case_0001/case_view/case_view.json` insan onayıyla (`--approve`)
promote edildi: `case_view_id=case_view_case_0001_v1`, `generation_status=completed`,
`issue_panel=6` (canonical issue setiyle 1:1), `open_items_panel=25`,
`warnings=1` (yukarıdaki QA linkaj politikasının dürüst yansıması: "83
qa_check_result related_issue_id olmadan"). Pending ve canonical SHA256 birebir
aynı: `357e1d48b0cca73626a980d6e2bb84d785bab4236a539de9966e161e7b393a42` — bu hem
kullanıcının terminal çıktısında hem bu session'ın kendi bağımsız hesaplamasında
(makineden dosyalar tekrar çekilerek) doğrulandı. Approval audit kaydı
`data/cases/case_0001/case_view/reviews/case_view_case_0001_v1_20260904_212319.approval.json`'da
mevcut. **Orchestrator hiçbir yeni hukuki fact/olasılık/sonuç İCAT ETMEMİŞTİR** —
yalnız Row 1-16'nın zaten canonical olan çıktılarını issue etrafında yeniden
gruplamıştır (bkz. Prensip 1, 2, 7).

**EK (kullanıcı kararı, 2026-09-04, Row 18 tasarımı sırasında eklendi) —
canonical snapshot / canlı deterministik görünüm ayrımı**: `case_view.json`
**onaylı, audit'li bir SNAPSHOT olarak kalır** — Row 18 (Lawyer UI) tam
etkileşimli olduğu için, avukatın Layer A/B'de verdiği HER küçük karardan
sonra bu snapshot ANINDA stale olabilir; avukatın her seferinde Row 17'nin
onay akışını yeniden çalıştırması pratik DEĞİLDİR. Bu yüzden Row 18 kendi
ekranlarını canonical `case_view.json`'ı OKUYARAK değil,
`orchestrator_engine.build_case_view(case_id)`'i (Row 17'nin AYNI saf,
yan etkisiz fonksiyonu) DOĞRUDAN çağırıp bellekte ANLIK bir "canlı görünüm"
üreterek doldurur — bu görünüm HİÇBİR dosyaya yazılmaz/promote edilmez. Bu
karar **Row 17'nin kodunda hiçbir değişiklik gerektirmedi** (fonksiyon zaten
bağımsız çağrılabilir saf bir fonksiyondu — `orchestrator_validator.py` da
aynı şekilde kullanıyor); yalnız Row 18'in `ui/services/live_view.py`
modülünde tüketildi. Canlı görünüm ile en son onaylı canonical snapshot
(varsa) zaman damgası alanları HARİÇ karşılaştırılır; farklıysa UI'da açıkça
"görünüm güncel değil" uyarısı gösterilir (canonical snapshot'ı güncellemek
avukatın Row 17 onay akışını — "Onaylar" ekranından case_view row'unu —
tekrar çalıştırmasını gerektirir). Bir mutasyon işlemi (onay), sayfa
render edildiğinde hesaplanan bir pending hash'ine dayanıyorsa ve işlem
anında o hash değişmişse REDDEDİLİR (bkz. Row 18 checkpoint özeti,
`StaleViewError`) — canlı görünümün kendisi asla bir onayın DOĞRUDAN
girdisi değildir, yalnız görüntüleme amaçlıdır.

### Row 18 — Lawyer UI (İLERLEME HALİNDE / NOT LOCKED — 18a: DONE/LOCKED, 18b: ACTIVE/NEXT — checkpoint özeti)

**Kapsam kararı (kullanıcı, 2026-09-04): Seçenek C** — tam etkileşimli kapsam
(dosya/kaynak görüntüleme, Layer A onay tetikleme, Layer B inceleme kararları,
Row 15 yapılandırılmış avukat talebi girişi, sonuç/hata/audit görüntüleme) +
**yerel, tek kullanıcılı FastAPI + Jinja2 (server-rendered) web uygulaması**,
yalnız `127.0.0.1` üzerinde. Kimlik doğrulama, çoklu kullanıcı, HTTPS/production
deployment, kalıcı oturum/veritabanı Row 19'a bırakıldı. Kullanıcı işi
**18a/18b/18c** olarak fazlandırdı; her faz kendi içinde test edilip
onaylanacak, tam Row 18 LOCK'u yalnız üçü de bittiğinde verilecek.

**Mutasyon sınırı (kullanıcı spesifikasyonu, her mutasyon için ZORUNLU)**:
(a) ilgili validator işlem anında yeniden çalışır, (b) kullanıcıya hedef kayıt/
mevcut durum/değişiklik gösterilir, (c) açık ikinci onay istenir (checkbox +
ayrı submit), (d) görüntülenen kaynak hash'i işlem anında yeniden kontrol
edilir ve değiştiyse işlem REDDEDİLİR, (e) yalnız var olan approval/review
Python fonksiyonları DOĞRUDAN çağrılır (asla shell/subprocess ile
`python ... --approve` çalıştırılmaz), (f) başarıda audit yolu + yeni hash
gösterilir, (g) hatada ASLA başarı ekranı gösterilmez. Generic "dosya yaz",
"komut çalıştır" veya kullanıcıdan keyfi path alan endpoint YOKTUR — bir
pending dosya kimliği yalnız ilgili modülün KENDİ listeleme fonksiyonunun
döndürdüğü gerçek bir adayla eşleşiyorsa kabul edilir (path traversal engeli).

**18a kapsamı — DONE / LOCKED** (kullanıcı onayı, hedeflenen
`vergi_ui_runtime` ortamında `pip check` PASS + 117/117 test PASS ile):
tüm 12 row için görüntüleme + Layer A onay tetikleme (Layer B ve Row 15
girişi 18a'da YOK — 18b/18c'ye bırakıldı). 23 dosya, tamamı `ui/` altında,
tamamı untracked: `main.py`, `__init__.py`, `requirements.txt`,
`services/{__init__,paths,common,live_view,security,approval_registry}.py`,
`templates/*.html` (9 dosya) + `static/style.css`,
`tests/{__init__,test_routes,test_service_isolated,test_templates_isolated}.py`.

**18a final güvenlik/mimari durumu** (bir statik inceleme + hedefli
remediation turu + iki route-test düzeltme turuyla ulaşıldı — kod tekrar
okunarak doğrulandı, varsayılmadı):

- **Yerel-only FastAPI/Jinja2 avukat arayüzü**: `ui/` gerçek bir Python
  paketi (`__init__.py`'lar, bağıl importlar) — desteklenen tek çalıştırma
  biçimi `python -m ui.main` / `uvicorn ui.main:app`; eski sys.path
  bootstrap'ı kaldırıldı.
- **Canonical/canlı case-view ayrımı korunuyor** (bkz. yukarıdaki EK) —
  görüntüleme öncesi canlı görünüm Row 17'nin gerçek
  `orchestrator_validator` fonksiyonlarından (`validate_schema`,
  `validate_case_id`, `validate_generated_at`,
  `validate_generation_status_consistency`) geçiyor; doğrulama
  başarısızsa fail-closed genel hata sayfası (`LiveViewInvalidError`),
  görünüm ASLA doğrulanmadan render edilmiyor.
- **Yalnız Layer A onay tetikleme** — case-scoped 10 modül (Row 8-17)
  `get_pending_path`/`get_canonical_path`/`inspect_pending`/`run_approve`
  tekdüze arayüzüyle tetikleniyor.
- **Fact (Row 6) / Timeline (Row 7) onayı DEVRE DIŞI** — kaynak kod
  (`fact_approval.py`, `timeline_approval.py`) tam okunarak doğrulandı:
  case_id başına "hangi pending güncel" sorusunu çözen yetkili bir
  resolver YOK. Bu iki aile `kind="unsupported_pending_resolution"`
  olarak yalnız bilgi amaçlı listeleniyor, onay butonu/route'u YOK — Row
  1-17'ye bu boşluğu kapatan bir resolver İCAT EDİLMEDİ.
- **Enumerated case_id ve row_key kontrolü** — tek bir allowlist
  çözücü (`paths.resolve_case_id`) hem route hem servis katmanında, her
  case_id alan noktanın başında; traversal/encode edilmiş
  traversal/separator/bilinmeyen-case reddi doğrudan test edildi.
  `row_key` sabit `CASE_SCOPED_ROWS_BY_KEY` evrenine karşı kontrol
  ediliyor.
- **Loopback-only middleware** — gerçek bağlanan istemci IP'sini
  kontrol ediyor, bind adresine güvenmiyor (`--host 0.0.0.0` yanlışlıkla
  verilse bile LAN'dan gelen istekler reddedilir).
- **HMAC CSRF token** — case_id + row_key + expected_hash'e bağlı,
  süreç-ömürlü sırla üretilen, sabit-zamanlı (`hmac.compare_digest`)
  doğrulanan token; expected-hash kontrolünün YERİNE GEÇMİYOR, ayrı bir
  katman.
- **Aynı-origin (Origin/Referer) doğrulaması** — header varsa host
  eşleşmesi zorunlu, CSRF token'a ek bir katman.
- **Mutasyon öncesi stale-hash koruması** — review ekranı render
  edildiğindeki pending hash, onay anında yeniden kontrol ediliyor;
  değiştiyse `run_approve` HİÇ ÇAĞRILMIYOR (`StaleViewError`).
- **Tarayıcıya genel hatalar** — `str(exception)`/ham mutlak path asla
  HTTP yanıtına girmiyor; sabit kod/mesaj tablosu kullanılıyor, ayrıntılı
  exception yalnız yerel konsola (`logging`) yazılıyor, repoya/dosyaya
  YAZILMIYOR.
- **Repo-göreli sonuç path'leri** — `approval_result.html`'e geçen
  canonical/audit path'leri `paths.to_repo_relative()`'ten geçiyor.
- **İzole mutasyon testleri + gerçek data/src byte-bütünlüğü** — tüm
  mutasyon/rollback/audit-failure testleri `TemporaryDirectory` + sahte
  adaptör modülüyle çalışıyor; eski `VERGI_UI_RUN_DESTRUCTIVE_TEST`
  yıkıcı test yolu tamamen kaldırıldı; gerçek `data/`/`src/` ağacının
  test öncesi/sonrası byte-düzeyinde değişmediği her test turunda
  ayrıca kanıtlandı.
- **`pip check` PASS ve 117/117 test sonucu** — 50 (saf-servis) + 17
  (Jinja2 şablon) + 50 (FastAPI route, TestClient) — hedeflenen
  `vergi_ui_runtime` ortamında kullanıcı tarafından fiilen çalıştırıldı.
- **Pinned `ui/requirements.txt`** — kök (UTF-16, ilgisiz anomalili)
  `requirements.txt`'den AYRI: `fastapi==0.141.1`, `starlette==1.6.0`,
  `httpx==0.28.1`, `jsonschema==4.26.0`, `pydantic==2.13.5`,
  `uvicorn==0.52.4`, `python-multipart==0.0.32`, `Jinja2==3.1.6`.
- **Bilinen, bloklayıcı olmayan backlog maddesi**: `StarletteDeprecationWarning:
  Using httpx with starlette.testclient is deprecated; install httpx2
  instead.` — yalnız test altyapısını (`TestClient`) ilgilendiriyor,
  üretim `uvicorn`/`fastapi` çalışma zamanını ETKİLEMİYOR; 117/117
  fonksiyonel geçiş bunu doğruluyor. `httpx2` bu fazda KURULMADI/ikame
  EDİLMEDİ (kullanıcı kararı) - gelecekteki bir bağımlılık yükseltme
  turuna bırakıldı.

**18a KAPSAM DIŞI (bilinçli, Row 19/18b/18c'ye bırakıldı)**: Layer B
inceleme kararları, Row 15 yapılandırılmış avukat talebi girişi, kimlik
doğrulama, çoklu kullanıcı erişimi, production/dış deployment.

**Sonraki adım**: **18b** (Layer B inceleme kararları) — **ACTIVE / NEXT**.

## 6. Cross-Cutting Backlog

Bu maddeler gerçek engineering requirement'lardır ama **roadmap sırasını değiştirmez**.
Row 9 yerine geçirilmez; production/pilot öncesi kapatılmalıdır.

- **Verification Workflow** (approval'dan ayrı bir modül): evidence-based,
  auditable, human-controlled; verification_state yükseltme/düşürme işlemleri açık
  provenance taşımalı. Şu an `fact_approval.py` yalnızca pending→canonical promosyonu
  yapar, `verification_state`'i değiştirmez — bu boşluk kayda geçirilmiştir, şimdi
  doldurulmayacaktır.
- `data/deadline_rules.json` (boş/stale) ile `data/deadline_rules/deadline_rules.json`
  (gerçek registry) arasındaki duplicate risk.
- `source_policy.py` ve `temporal_policy.py`'deki import-time test/assert davranışı
  (`__main__` koruması yok).
- Otomatik/tekrarlanabilir regression test suite eksikliği (mevcut testler her
  modülün gömülü `run_self_test()`'i + `case_0001` üzerindeki tek gerçek koşu).

Bu maddeler Row 9'u bloke etmiyorsa **şimdi düzeltilmez**.

## 7. Development Agent Çalışma Şekli

Bu repository'de **Development Orchestrator** olarak davran. Bir görev aldığında:

1. Önce ilgili mevcut schema/API/test/canonical data'yı oku.
2. Mevcut mimariyle uyumlu plan çıkar.
3. Locked modülleri gereksiz değiştirme.
4. Gereken dosyaları oluştur/değiştir.
5. Syntax/test/validator komutlarını kendin çalıştır.
6. Hata çıkarsa exact runtime output'u incele.
7. Testleri geçmeden başarı ilan etme.
8. Human approval gereken mutation öncesinde DUR (bkz. §8).
9. Kullanıcı açıkça onaylamadan canonical truth mutation yapma.
10. İş tamamlanınca değiştirilen dosyaları, test sonuçlarını, riskleri ve mevcut
    checkpoint'i raporla.
11. Kendi kendine roadmap değiştirme.
12. Yeni bir architectural requirement tespit edersen roadmap'i değiştirmek yerine
    backlog olarak raporla (bkz. §6).
13. Git commit/push/tag işlemlerini kullanıcı açıkça istemeden yapma.
14. `main` branch üzerinde geliştirme yapma.
15. `claude-dev` branch üzerinde çalış.
16. `v0.8-pre-claude` tag'ini değiştirme veya silme.
17. Task/Agent tool ile bir subagent başlatırsan, bu dosyadaki tüm güvenlik ve
    roadmap kurallarının subagent için de aynen geçerli olduğunu subagent'a
    açıkça belirt; subagent bu kurallara aykırı bir şey yaparsa sorumluluk onu
    başlatan session'a aittir.

## 8. Human Approval Sınırı

**Normal source code/schema/validator/test dosyaları:** Kullanıcı ilgili development
row'un implementasyonunu açıkça verdiyse, bu dosyalar `claude-dev` üzerinde her
dosya için ayrıca onay istemeden değiştirilebilir (örn. Row 9 implementasyonu
kapsamında yeni bir `.py` dosyası, schema veya test yazmak).

**Ancak aşağıdakilerden ÖNCE MUTLAKA DUR ve açık kullanıcı onayı iste:**
- canonical case/fact/timeline/deadline truth mutation
- verification_state yükseltme veya düşürme
- production rule activation/deactivation
- locked row contract değişikliği
- destructive delete veya mass rename
- main branch üzerinde herhangi bir geliştirme
- git commit/push/tag/reset/rebase/force işlemleri

Bu liste §3 Prensip 15-16 ile birlikte okunur: onay gereken bir noktaya gelindiğinde
agent işlemi **yapmadan** durur, ne yapmak istediğini ve neden onay gerektiğini
açıklar, ve kullanıcının açık cevabını bekler.

## 9. Row Lock Kuralı

DONE / LOCKED bir row yalnızca şu durumlarda değiştirilebilir:
- açık bug,
- downstream uyumsuzluk,
- security/safety ihlali,
- veya kullanıcı talebi.

Böyle bir değişiklik gerektiğinde önce şunlar raporlanır:
- neden gerektiği,
- hangi locked contract'ın etkilendiği,
- regression riski.

## 10. Secret / Credential Safety

- `.env` içeriğini kullanıcıya, loglara, commitlere veya başka dosyalara kopyalama.
- API key, token, password veya secret değerlerini çıktı olarak gösterme.
- `.env`, `.venv/`, `index/`, `*.bak` Git'e alınmaz.
- `.gitignore`'daki bu güvenlik exclusion'ları kullanıcı açıkça istemeden kaldırılmaz.
- Bir secret yanlışlıkla tracked görünürse mutation yapmadan önce kullanıcıya bildir.
- Secret değerlerini test fixture içine koyma.

## 11. Hukuki Güvenlik

Model hukuki araştırma ve analiz yardımı sağlayabilir fakat:
- doğrulanmamış olguyu kesin gerçek yapamaz,
- hukuki kaynak version'ını varsayamaz,
- uygulanabilirliği varsayamaz,
- deadline'ı doğrulanmamış anchor'dan hesaplayamaz,
- özel hüküm yokmuş gibi varsayarak genel hükmü kesin uygulayamaz,
- kaynak ile çıkarımı birbirine karıştıramaz.

## 12. Checkpoint Maintenance

Bir row için:
- contract tamamlandı,
- validator/testler geçti,
- gereken approval tamamlandı,
- kullanıcı tarafından LOCK edildi

ise bu dosyada **yalnızca** şu üç bölüm güncellenebilir:
- ilgili roadmap satırının status'ü (§4),
- Current Checkpoint (§5),
- next active row (§5).

Bu, roadmap değiştirmek **sayılmaz**. Roadmap sırası (§4) ve temel mimari prensipler
(§3) kendi kendine değiştirilemez; bunlarda değişiklik yalnızca kullanıcının açık
talebiyle yapılabilir.
