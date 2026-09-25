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
18. Lawyer UI — **DONE / LOCKED**
19. Production / Security — **ACTIVE / NEXT**
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
- Rows 1-18 tamamlandı ve **LOCKED**
- Sıradaki canonical development row: **ROW 19 — PRODUCTION / SECURITY**
  — henüz implementasyona BAŞLANMADI.
- **ROW 18 — LAWYER UI** artık **DONE / LOCKED** — kullanıcı kararıyla
  18a/18b/18c olarak fazlandırılmış, üçü de tamamlanmış, test edilmiş
  ve onaylanmıştır (bkz. Row 18 checkpoint özeti, §5 sonrası). **18a**
  (tüm canonical katmanların görüntülenmesi + yalnız
  registry-supported aileler için Layer A onay tetikleme; fact/timeline
  onayı `unsupported_pending_resolution` olarak fail-closed)
  **DONE / LOCKED** — hedeflenen `vergi_ui_runtime` ortamında `pip
  check` PASS ve 117/117 test PASS ile kullanıcı tarafından
  doğrulandı ve onaylandı. **18b** (Layer B inceleme kararları — 12
  review-kind adaptörü, 5 aile: Evidence/Argument/Risk-Strategy/
  Drafting/QA) **DONE / LOCKED** — hedeflenen `vergi_ui_runtime`
  ortamında `pip check` PASS ve Row 18A 117/117 + Row 18B servis
  69/69 + şablon 42/42 + route 115/115 = **343/343** test PASS ile
  kullanıcı tarafından doğrulandı ve onaylandı (bkz. Row 18 checkpoint
  özeti, §5 sonrası). **18c** (Row 15 yapılandırılmış avukat talebi
  girişi — görüntüleme/doğrulama/kaydetme; Drafting Engine/agent/
  network HİÇBİR ZAMAN tetiklenmez) **DONE / LOCKED** — bağımsız bir
  salt-okunur LOCK-hazırlık incelemesinden geçmiş, hedeflenen
  `vergi_ui_runtime` ortamında `pip check` PASS ve Row 18A 117/117 +
  Row 18B 226/226 + Row 18C 169/169 (servis 77/77 + şablon 15/15 +
  route 51/51 + CLI 26/26) = **Row 18 toplamı 512/512** test PASS ile
  kullanıcı tarafından doğrulandı ve onaylandı (bkz. Row 18 checkpoint
  özeti, §5 sonrası, "18c final güvenlik/mimari durumu").
- **ROW 19A — Threat Model & Deployment Contract** artık **DONE /
  LOCKED** — kullanıcı onayıyla ("ROW 19A — USER DECISION"), salt-okunur
  bir kontrat/tehdit-modeli/exact-mapping incelemesi olarak tamamlandı
  (bkz. Row 19A checkpoint özeti, §5 sonrası). Rows 1-18 contract'ları
  (§3, §4, §9) değişmedi. **Dosya-değişiklik sınırı**: 19A yalnız
  `CLAUDE.md`'yi değiştirebilir; 19B, 19C ve 19D'nin HER BİRİ kendi tam
  dosya allowlist'ini implementasyondan ÖNCE ayrıca sunup onaylatmalıdır
  — genel Row 19 onayı hiçbir alt-fazın dosya değişikliğini ÖNCEDEN
  yetkilendirmez.
- **ROW 19B — Identity / Session / Authorization** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış 43 dosyalık
  allowlist (25 yeni + 18 değiştirilmiş dosya) üzerinde implement
  edildi, yerel testlerle doğrulandı ve bağımsız, salt-okunur bir
  LOCK-hazırlık incelemesinden geçti (bkz. Row 19B checkpoint özeti,
  §5 sonrası). Rows 1-18 ve Row 19A contract'ları değişmedi.
- **ROW 19C-1 — Coordinator Core & Path Safety** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış 15 dosyalık
  allowlist (10 yeni + 5 değiştirilmiş dosya) üzerinde implement
  edildi, gerçek/disposable bir PostgreSQL örneğine karşı yerel
  testlerle doğrulandı ve bağımsız, salt-okunur bir LOCK-hazırlık
  incelemesinden geçti (bkz. Row 19C-1 checkpoint özeti, §5 sonrası).
  Rows 1-18, Row 19A ve Row 19B contract'ları değişmedi. Bu
  checkpoint'in kendisi de (19A/19B örneğinde olduğu gibi) yalnız
  `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir —
  hiçbir kaynak/migration/test/production dosyasına dokunmaz.
- **ROW 19C-2a — Layer A Approval Mutation Integration** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış 31 dosyalık
  allowlist (8 yeni + 23 değiştirilmiş dosya) üzerinde implement
  edildi, gerçek/disposable bir PostgreSQL örneğine karşı yerel
  testlerle doğrulandı ve bağımsız bir salt-okunur final inceleme +
  dar kapsamlı bir remediation turundan geçti (bkz. Row 19C-2a
  checkpoint özeti, §5 sonrası). Bu, mutation coordinator/journal
  altyapısının İLK gerçek production writer'a bağlandığı alt-fazdır:
  on Layer A approval ailesinin tamamı. Rows 1-18, Row 19A, Row 19B ve
  Row 19C-1 contract'ları değişmedi.
- **ROW 19C-2b — Layer B Review Mutation Integration** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış, dört ayrı
  mekanik-netleştirme turuyla (advisor Fable 5 danışmalı) kesinleştirilmiş
  20 dosyalık allowlist (4 yeni + 16 değiştirilmiş dosya) üzerinde
  implement edildi, gerçek/disposable bir PostgreSQL örneğine karşı
  yerel testlerle doğrulandı ve bağımsız, salt-okunur bir final
  inceleme - iddia edilen test sonuçlarının rapora güvenilmeden
  bağımsızca yeniden çalıştırılması dahil - `No blocking findings`
  sonucuyla `ROW 19C-2b LOCK-READY` verdict'inden geçti (bkz. Row
  19C-2b checkpoint özeti, §5 sonrası). Bu, mutation coordinator/journal altyapısının İKİNCİ gerçek
  production writer ailesine bağlandığı alt-fazdır: 12 review_kind'ın
  (Evidence/Argument/Risk-Strategy/Drafting/QA Layer B) tamamı. Rows
  1-18, Row 19A, Row 19B, Row 19C-1 ve Row 19C-2a contract'ları
  değişmedi.
- **ROW 19C-2c — Drafting-Request Mutation Integration** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam dosya
  allowlist'i (4 yeni + 9 değiştirilmiş dosya) üzerinde implement
  edildi, gerçek/disposable bir PostgreSQL örneğine karşı yerel
  testlerle doğrulandı ve İKİ ayrı bağımsız, salt-okunur final
  inceleme + iki hedefli path-containment remediation turundan (canlı
  symlink/NTFS-junction escape, ardından broken-link fail-open) geçerek
  `ROW 19C-2c LOCK-READY — No blocking findings` verdict'ine ulaştı
  (bkz. Row 19C-2c checkpoint özeti, §5 sonrası). Bu, mutation
  coordinator/journal altyapısının ÜÇÜNCÜ gerçek production writer'a
  bağlandığı alt-fazdır: Row 18C'nin `drafting_request.save` action
  family'si. Rows 1-18, Row 19A, Row 19B, Row 19C-1, Row 19C-2a ve Row
  19C-2b contract'ları değişmedi.
- **ROW 19C-3a Slice 1 — Shared Path-Containment Foundation** artık
  **DONE / LOCKED** — kullanıcı tarafından ayrıca onaylanmış 5 dosyalık
  allowlist (2 yeni + 3 değiştirilmiş dosya) üzerinde implement edildi,
  iki ayrı remediation turundan (root fail-closed düzeltmesi ve
  Windows drive-relative escape Critical bulgusu) geçti ve bağımsız,
  salt-okunur bir final re-review'da `ROW 19C-3a SLICE 1 LOCK-READY`
  verdict'ine ulaştı (bkz. Row 19C-3a Slice 1 checkpoint özeti, §5
  sonrası). Rows 1-18, Row 19A, Row 19B, Row 19C-1, Row 19C-2a, Row
  19C-2b ve Row 19C-2c contract'ları değişmedi.
- **ROW 19C-3a Slice 2 — Layer A/B Nested Path-Containment Closure**
  artık **DONE / LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam
  dosya allowlist'i (13 değiştirilmiş, 0 yeni dosya) üzerinde implement
  edildi, gerçek/disposable bir PostgreSQL örneğine karşı yerel
  testlerle doğrulandı, bir ilk bağımsız incelemenin bulduğu üç dar
  maddeyle ve ardından hedefli bir re-review'un bulduğu bir backup-kind
  sıralama boşluğuyla remediation turlarından geçti ve son, bağımsız,
  salt-okunur bir targeted re-review'da `ROW 19C-3a SLICE 2 LOCK-READY`
  verdict'ine ulaştı (bkz. Row 19C-3a Slice 2 checkpoint özeti, §5
  sonrası). Rows 1-18, Row 19A, Row 19B, Row 19C-1, Row 19C-2a, Row
  19C-2b, Row 19C-2c ve Row 19C-3a Slice 1 contract'ları değişmedi.
- **ROW 19C-3b Slice 1 — Facade-Backed Legacy CLI Mutation Integration**
  artık **DONE / LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam
  dosya allowlist'i (4 yeni + 24 değiştirilmiş dosya) üzerinde implement
  edildi, gerçek/disposable bir PostgreSQL örneğine karşı yerel
  testlerle doğrulandı, bir ilk bağımsız incelemenin bulduğu bir
  test-evidence gap'iyle ve ardından hedefli bir re-review'un bulduğu
  bir High test-correctness (legacy subprocess encoding) blocker'ıyla
  remediation turlarından geçti ve son, bağımsız, salt-okunur bir
  targeted re-review'da `ROW 19C-3b SLICE 1 LOCK-READY` verdict'ine
  ulaştı (bkz. Row 19C-3b Slice 1 checkpoint özeti, §5 sonrası). Rows
  1-18, Row 19A, Row 19B, Row 19C-1, Row 19C-2a, Row 19C-2b, Row 19C-2c
  ve Row 19C-3a Slice 1/Slice 2 contract'ları değişmedi.
- **ROW 19C-3b Slice 2 — Fact/Timeline Canonical Promotion Integration**
  artık **DONE / LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam
  dosya allowlist'i (4 yeni + 8 değiştirilmiş dosya) üzerinde implement
  edildi, gerçek/disposable bir PostgreSQL örneğine karşı yerel
  testlerle doğrulandı ve bağımsız, salt-okunur bir final incelemede
  `ROW 19C-3b SLICE 2 LOCK-READY — No blocking findings` verdict'ine
  ulaştı (bkz. Row 19C-3b Slice 2 checkpoint özeti, §5 sonrası). Bu,
  fact (Row 6) ve timeline (Row 7) canonical promotion writer'larının
  (`src/fact_approval.py --approve`, `src/timeline_approval.py
  --approve`) mutation coordinator/journal altyapısına, Layer A'nın
  exact-10 facade'i GENİŞLETİLMEDEN, ayrı bir promotion facade/adapters
  çifti üzerinden bağlandığı alt-fazdır. Rows 1-18, Row 19A, Row 19B,
  Row 19C-1, Row 19C-2a, Row 19C-2b, Row 19C-2c, Row 19C-3a Slice
  1/Slice 2 ve Row 19C-3b Slice 1 contract'ları değişmedi.
- **ROW 19C-3c-i — Deterministic Generation Integration** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam dosya
  allowlist'i (6 yeni + 13 değiştirilmiş dosya) üzerinde implement
  edildi, bir bağımsız salt-okunur incelemenin bulduğu HIGH önemde bir
  deadline revision-identity kusuruyla hedefli bir remediation turundan
  geçti ve son, bağımsız, salt-okunur bir targeted re-review'da
  `ROW 19C-3c-i LOCK-READY — No blocking findings` verdict'ine ulaştı
  (bkz. Row 19C-3c-i checkpoint özeti, §5 sonrası). Bu, timeline (Row 7,
  `src/timeline_engine.run_timeline_engine()`) ve deadline (Row 8,
  `src/deadline_engine.run_engine()`) deterministik pending-generation
  writer'larının mutation coordinator/journal altyapısına, iki YENİ,
  CLI-only action family (`generation.deadline`/`generation.timeline`)
  üzerinden, ayrı bir generation facade/adapters çifti ile bağlandığı
  alt-fazdır. Rows 1-18, Row 19A, Row 19B, Row 19C-1, Row 19C-2a, Row
  19C-2b, Row 19C-2c, Row 19C-3a Slice 1/Slice 2 ve Row 19C-3b Slice
  1/Slice 2 contract'ları değişmedi.
- **ROW 19C-3c-ii — Case-Scoped Agent-Gated Pending Generation
  Integration** artık **DONE / LOCKED** — kullanıcı tarafından ayrıca
  onaylanmış tam dosya allowlist'i (9 yeni + 13 değiştirilmiş dosya, 0
  allowlist dışı dosya) üzerinde implement edildi ve bağımsız, salt-
  okunur bir final incelemede — 22 dosyalık diff/kaynak incelemesi,
  gerçek/disposable bir PostgreSQL 16 örneğine karşı 51/51 test
  modülünün yeniden çalıştırılması (implementer'ın kendi sayısıyla
  birebir: 2936 passed, 0 failed, 8 counted skipped, 1 informational
  uncounted skip), yeni reconciliation adapter'ına karşı ek bir
  supplementary crash-matrix diagnostic'i ve static/residue/git
  bütünlük kontrolleri dahil — `ROW 19C-3c-ii LOCK-READY — No
  blocking findings` verdict'ine ulaştı (bkz. Row 19C-3c-ii checkpoint
  özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce). Bu,
  beş case-scoped agent-gated pending-generation writer'ının
  (issue_spotting Row 9, evidence Row 12, argument Row 13,
  risk_strategy Row 14, drafting Row 15) mutation coordinator/journal
  altyapısına, BEŞ YENİ, CLI-only action family
  (`generation.issue_spotting`/`generation.evidence`/
  `generation.argument`/`generation.risk_strategy`/
  `generation.drafting`) üzerinden, Row 19C-3c-i'nin deterministik
  deadline/timeline facade/adapters çiftinden AYRI, bağımsız bir
  agent-generation facade/adapters çifti ile bağlandığı alt-fazdır —
  Row 19C-3c-i'nin kendi çifti DEĞİŞTİRİLMEDİ. Rows 1-18, Row 19A, Row
  19B, Row 19C-1, Row 19C-2a, Row 19C-2b, Row 19C-2c, Row 19C-3a Slice
  1/Slice 2, Row 19C-3b Slice 1/Slice 2 ve Row 19C-3c-i contract'ları
  değişmedi.
- **ROW 19C-3c-iii — Fact Extraction Generation Integration** artık
  **DONE / LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam dosya
  allowlist'i (5 yeni + 9 değiştirilmiş dosya olarak onaylandı; 14.
  dosya olan `ui/tests/test_cli_mutate_integration_postgres.py`
  kaynak-kanıtlı gerekçeyle GENUINELY untouched kaldı — fiilen 5 yeni +
  8 değiştirilmiş = 13 dosya) üzerinde implement edildi ve session
  kesintisiyle bölünüp disk kanıtından devam ettirilen bağımsız,
  salt-okunur bir final incelemede — 8 modified dosyanın diff
  yakalaması, fresh disposable bir PostgreSQL 16'ya karşı BAĞIMSIZ bir
  54-modül final-tree sweep'i (54/54 exit 0, 3099 passed, 0 failed, 8
  counted skipped, implementer'ın kendi sayısıyla birebir), hedefli
  kaynak spot-check'leri ve static/residue/git bütünlük kontrolleri
  dahil — `ROW 19C-3c-iii LOCK-READY — No blocking findings`
  verdict'ine ulaştı (bkz. Row 19C-3c-iii checkpoint özeti, §5
  sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce). Bu,
  `fact_extraction_engine.py`'nin (Row 4) pending-generation
  writer'ının mutation coordinator/journal altyapısına, BİR YENİ,
  CLI-only, document-scoped action family
  (`generation.fact_extraction`) üzerinden, Row 19C-3c-i/ii'nin kendi
  facade/adapters çiftlerinden AYRI, bağımsız bir fact-extraction
  facade/adapters çifti ile bağlandığı alt-fazdır — coordinator
  entegrasyonundan önce zorunlu kılınan `--with-agent`/
  `--allow-network` çift açık network gate hem CLI hem facade
  katmanında bağımsız olarak uygulanmış, motorun import-zamanı
  `load_dotenv()` yan etkisi `call_llm()`'in production dalının içine
  taşınmış ve doğrudan CLI mutasyon yolu kapatılmıştır. Rows 1-18, Row
  19A, Row 19B, Row 19C-1, Row 19C-2a, Row 19C-2b, Row 19C-2c, Row
  19C-3a Slice 1/Slice 2, Row 19C-3b Slice 1/Slice 2, Row 19C-3c-i ve
  Row 19C-3c-ii contract'ları değişmedi.
- **ROW 19C-3c-iv Slice 1 — Deterministic + Agent Legal Research /
  Case Law Pending-Generation Integration (retrieval/discovery
  deferred)** artık **DONE / LOCKED** — kullanıcı tarafından ayrıca
  onaylanmış tam dosya allowlist'i (6 yeni + 10 değiştirilmiş = 16
  dosya) üzerinde implement edildi. İki YENİ, CLI-only action family
  (`generation.legal_research` / `generation.case_law`) mutation
  coordinator/journal altyapısına bağlandı; deterministik ve agent
  modları AYNI coordinated yol üzerindedir; retrieval/discovery
  BİLİNÇLİ olarak ertelenmiştir; iki doğrudan engine CLI mutasyon yolu
  (`legal_research_engine.py`/`case_law_engine.py` `main()`)
  kapatılmıştır. İlk bağımsız salt-okunur inceleme bir F1 HIGH
  (case_law coordinated agent apply'ın discovery katmanına
  `network_allowed=True` taşıması) ve bir F2 MEDIUM (agent-mode test
  kanıt zincirindeki yanlış nedensel iddia + hiç konuşulmayan
  `client.generate()` injection protokolü) bulgusuyla NOT LOCK-READY
  verdi; dar, 5 dosyalık bir remediasyon uygulandı ve bağımsız bir
  Fable yeniden incelemesi — kaynak/call-chain doğrulaması, bağımsız
  fail-closed import tanısı ve bağımsız 58-modül full sweep dahil —
  F1/F2'nin kapandığını doğruladı. Final verdict:
  `ROW 19C-3c-iv SLICE 1 LOCK-READY — F1/F2 closed, no blocking findings`
  (bkz. Row
  19C-3c-iv Slice 1 checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce).
- **RAG Global-Resource Bundle Foundation** artık **DONE / LOCKED** —
  kullanıcı tarafından ayrıca onaylanmış 21 dosyalık allowlist (10
  yeni + 11 değiştirilmiş dosya) üzerinde implement edildi (bkz. RAG
  Global-Resource Bundle Foundation checkpoint özeti, §5 sonrası,
  "## 6. Cross-Cutting Backlog"dan hemen önce). Immutable,
  content-addressed RAG bundle yapısı (`index/v_<64hex>/` + tek
  atomik `current_version` pointer); `rag_bundle.build` ve
  `rag_bundle.activate` iki action family'si mutation coordinator/
  journal altyapısına `global:rag_index` lock/journal üzerinden
  bağlandı; migration 0005 (`iam.global_resource_grants` +
  `iam.global_resource_grant_events`) ile global-resource grant/authz
  modeli eklendi; pinned/verified reader (`load_pinned_bundle`) +
  import/credential hijyeni (`ingest.py`/`retriever.py`'nin import-anı
  faiss/numpy/dotenv/openai yükleri kaldırıldı) uygulandı;
  `src/ingest.py`'nin doğrudan CLI mutasyon yolu kapatıldı. İlk
  bağımsız incelemede (metodolojik bağımsızlık — implementer ile aynı
  session, ayrı analiz disiplini) 1 HIGH (F1: activation identity
  hedef bundle'ı içermiyor → sessiz cross-replay riski) + 3 MEDIUM
  (F2: rollback sınırı audit-dizin oluşturmayı kapsamıyor; F3:
  completed-replay corroboration yok; F4: build audit ince/recompute
  bağı yok) bulundu, verdict NOT LOCK-READY idi. Yalnız 6 dosyada
  (mevcut 20-dosyalık değişen set İÇİNDE, yeni dosya/migration
  EKLENMEDEN) dar bir remediasyon uygulandı; TAMAMEN AYRI, bağımsız
  bir Fable yeniden-incelemesi (repo-dışı fault-injection tanısı +
  gerçek/disposable PostgreSQL 16 ile) F1-F4'ün dördünün de
  KAPANDIĞINI doğruladı; 0 Critical/High/Medium, 5 Low/Observation
  (bloklamayan) bulguyla final verdict:
  `RAG BUNDLE FOUNDATION LOCK-READY — F1-F4 CLOSED, NO BLOCKING FINDINGS`.
  Rows 1-18, Row 19A, Row 19B, Row 19C-1…19C-3c-iv Slice 1
  contract'ları değişmedi.
- **RAG Real-Dependency Validation + Synthetic E2E Gate** artık
  **DONE / LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam
  dosya allowlist'i (1 YENİ + 0 DEĞİŞTİRİLMİŞ = 1 dosya) üzerinde
  implement edildi (bkz. RAG Real-Dependency Validation + Synthetic
  E2E Gate checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting
  Backlog"dan hemen önce). Yeni dosya: `ui/tests/test_rag_bundle_
  dependency_smoke.py`; production/migration/şema/web değişikliği
  SIFIR. Root `.venv` üzerinde gerçek dependency gate (faiss-cpu/
  numpy/pypdf/openai/python-dotenv/httpx2) ve gerçek sentetik
  build→publish→activate→load→retrieve E2E zinciri başarıyla
  doğrulandı. İlk bağımsız incelemede iki MEDIUM bulgu (F1: "bundle
  #2 retrieval" kanıt zincirinin fiilen bundle #1 üzerinde koşması;
  F2: `DEPENDENCY GATE: PASS` marker'ının son zorunlu data/index
  bayt-değişmezlik kontrolünden ÖNCE basılması) tespit edilerek
  verdict NOT LOCK-READY idi. Yalnız AYNI tek test dosyasında dar bir
  remediasyon uygulanarak F1/F2 kapatıldı; TAMAMEN AYRI, bağımsız bir
  Fable yeniden incelemesi F1/F2'nin kaynak + bağımsız tanılarla
  KAPANDIĞINI doğruladı ve final verdict verdi:
  `RAG REAL-DEPENDENCY VALIDATION + SYNTHETIC E2E GATE LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`.
  Rows 1-18, Row 19A, Row 19B, Row 19C-1…19C-3c-iv Slice 1 ve RAG
  Global-Resource Bundle Foundation contract'ları değişmedi.
- **Row 10/11 Legal Research + Case Law Schema Patch** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam dosya
  allowlist'i üzerinde implement edildi: **0 YENİ + 8 DEĞİŞTİRİLMİŞ =
  8 dosya**. Tek, exact-isimli alan `rag_index_version_used`
  (`case_legal_research.schema.json`'da `research_candidate.
  properties`'e; `case_case_law.schema.json`'da `coverage_record.
  properties` ve `decision_candidate.properties`'e) geriye-uyumlu,
  additive, `required`'a EKLENMEMİŞ (optional) bir property olarak
  eklendi; iki discovery modülü (`legal_research_discovery.py`,
  `case_law_discovery.py`) yeni alanı additive keyword-only/
  default-`None` parametreyle taşıyacak şekilde genişletildi; iki
  validator (`legal_research_validator.py`, `case_law_validator.py`)
  yeni bir fail-closed consistency kuralı kazandı; iki engine-isolated
  test dosyası (`ui/tests/test_legal_research_engine_isolated.py`,
  `ui/tests/test_case_law_engine_isolated.py`) additive kanıt
  kazandı. Artifact `schema_version` const'ları **1** (Legal Research)
  ve **2** (Case Law) olarak KORUNDU — bump edilmedi. Sıfır migration,
  sıfır production data rewrite/regeneration/reapproval, sıfır UI/web/
  CLI değişikliği. Fresh disposable PostgreSQL 16 (migration
  0001-0005) ile 64/64 `ui/tests/test_*.py` modülü exit 0, **3686
  passed, 0 failed, 8 counted skipped** (yeni counted skip yok); ayrı,
  bağımsız bir Fable final incelemesi — 47/47 repo-dışı bağımsız
  diagnostic, aynı hedefli test sonuçları, kendi fresh PostgreSQL'iyle
  64/64 aynı sonuç, 0 external network, 0 `.env` open, korunan
  data/index/migration/`CLAUDE.md` manifestlerinin byte-identical
  kaldığı dahil — hiçbir blocking bulgu raporlamadı. Final verdict:
  `ROW 10/11 LEGAL RESEARCH + CASE LAW SCHEMA PATCH LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Row 10/11 Legal Research + Case Law Schema Patch checkpoint
  özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce).
  Rows 1-18, Row 19A, Row 19B, Row 19C-1…19C-3c-iv Slice 1, RAG
  Global-Resource Bundle Foundation ve RAG Real-Dependency Validation
  + Synthetic E2E Gate contract'ları değişmedi.
- **RAG Corpus Policy Foundation** artık **DONE / LOCKED** — kullanıcı
  tarafından ayrıca onaylanmış tam dosya allowlist'i (4 YENİ + 8
  DEĞİŞTİRİLMİŞ = 12 dosya) üzerinde implement edildi (bkz. RAG Corpus
  Policy Foundation checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting
  Backlog"dan hemen önce). Tek birleşik policy artefaktı
  (`data/corpus_policy.schema.json` +
  `data/corpus_policy/corpus_policy.json`) + validator
  (`src/corpus_policy_validator.py`) + enforcement wiring slice'ıdır —
  static, git-governed bir corpus kabul politikasıdır, yeni bir
  mutation-coordinator action family DEĞİLDİR. Policy dosyası
  `ingest.compute_source_manifest()`'in bir kaynak girdisi olarak bağlanır;
  bu tek bağlama noktası üzerinden `input_digest`,
  `source_digest`/`pre_hash`, `bundle_version`, build audit, completed
  replay ve reconciliation'ın TAMAMINI otomatik kapsar — ayrı bir
  identity-core alanı açılmadan. `apply_activate()`'in hem pre-lock hem
  under-lock precondition zincirine yeni bir `CorpusPolicyDriftError`
  kapısı eklendi: hedef bundle'ın policy girdisi eksikse veya canlı,
  repo-committed policy'nin ham-bayt hash'inden farklıysa, sıfır
  pointer/journal/audit yazımıyla reddedilir. Belge
  admissibility/provenance/`%PDF` magic-byte/max-boyut/cross-document dedup
  kontrolleri (`src/manifest_validator.py`) ve provision temporal-disiplin
  + cross-version interval kontrolleri
  (`src/provision_manifest_validator.py`, bu validator'ın İLK gerçek
  otomatik çağrı yolu) build gate'ine eklendi. İlk bağımsız incelemede
  (Fable haftalık kotası dolduğu için Opus kullanıldı, implementasyondan
  AYRI model/oturum) **F1 HIGH** (`src/ingest.py`'nin üç bundle-yolu join
  noktasında sözleşmenin gerektirdiği path-containment kontrolü hiç
  implement edilmemişti, `preview_build()` üzerinden gerçek bir
  arbitrary-file read-and-hash primitive'iydi) ve **F2 MEDIUM**
  (`admission="deferred"` build gate'i tarafından enforce edilmiyordu, üç
  deferred aile sıfır hatayla kabul ediliyordu) bulundu, ilk verdict `NOT
  LOCK-READY` idi. Dar, üç dosyalık bir remediasyon (`src/ingest.py`,
  `src/manifest_validator.py`,
  `ui/tests/test_rag_bundle_builder_isolated.py`) ikisini de kapattı;
  TAMAMEN AYRI bir Opus yeniden incelemesi (yine Fable kotası nedeniyle)
  F1/F2'nin kaynak + gerçek NTFS junction/absolute-path fault-injection +
  bağımsız `sys.addaudithook` tanılarıyla KAPANDIĞINI doğruladı ve final
  verdict'e ulaştı:
  `RAG CORPUS POLICY FOUNDATION LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`
  Rows 1-18, Row 19A, Row 19B, Row 19C-1…19C-3c-iv Slice 1, RAG
  Global-Resource Bundle Foundation, RAG Real-Dependency Validation +
  Synthetic E2E Gate ve Row 10/11 Legal Research + Case Law Schema Patch
  contract'ları değişmedi.
- **RAG Corpus Prerequisite Documents-Schema Patch** artık **DONE /
  LOCKED** — kullanıcı tarafından ayrıca onaylanmış tam dosya
  allowlist'i (0 YENİ + 4 DEĞİŞTİRİLMİŞ = 4 dosya) üzerinde implement
  edildi (bkz. RAG Corpus Prerequisite Documents-Schema Patch
  checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen
  önce). Fable FINAL raporunun **P2** olarak adlandırdığı Phase-2
  prerequisite documents-şema yamasıdır. `data/documents.schema.json`'a
  **on optional/nullable alan** eklendi: `daire`, `esas_no`, `karar_no`,
  `temyiz_kesinlesme_durumu`, `anonymization_applied`, `text_basis`,
  `raw_byte_sha256`, `acquisition_timestamp`, `acquisition_channel`,
  `acquiring_actor_ref` — schema title `V2.1`→`V2.2` (kozmetik),
  `schema_version` `const` **1** ve `required[]` (14 alan) DEĞİŞMEDEN.
  `esas_no` ve `karar_no` **ayrı canonical alanlar** olarak eklendi
  (tek `document_number` esas-no ile karar-no'yu ayırt edemediği için);
  `document_number` kendi mevcut genel belge-numarası anlamını
  (Kanun/BKK/CK) korur — `case_number` P2'de hâlâ `document_number`'dan
  okunur, `esas_no`'ya re-point P5b'ye bırakıldı. `src/
  manifest_validator.py`'ye active+ingest-enabled `Yargı Kararı`
  (`daire`/`esas_no`/`karar_no`/`karar_tarihi` zorunlu) ve `Özelge`
  (`anonymization_applied is True` **identity** kontrolü — presence/
  truthiness DEĞİL) için fail-closed per-type kurallar eklendi; ayrıca
  zaten hesaplanmış dosya hash'ini yeniden kullanan, gerçek PDF
  baytlarına karşı çalışan bir `raw_byte_sha256` declared-vs-computed
  bütünlük kapısı eklendi (containment sonrası, yalnız
  active+ingest-enabled belgeler için — disclosed sınır). İki mevcut
  test dosyası (`ui/tests/test_rag_bundle_builder_isolated.py`,
  `ui/tests/test_case_law_engine_isolated.py`) additive kanıtla
  genişletildi; sıfır yeni test modülü (65→65). Sıfır migration, sıfır
  production `data/documents.json`/corpus/index/policy değişikliği,
  sıfır CLI/web yüzeyi. Bağımsız Opus incelemesinde (Fable haftalık
  kotası dolduğu için, Sonnet implementasyonundan AYRI model/oturum) 0
  Critical/High/Medium bulguyla final verdict:
  `RAG CORPUS PREREQUISITE DOCUMENTS-SCHEMA PATCH LOCK-READY — NO BLOCKING FINDINGS`
  Rows 1-18, Row 19A, Row 19B, Row 19C-1…19C-3c-iv Slice 1, RAG
  Global-Resource Bundle Foundation, RAG Real-Dependency Validation +
  Synthetic E2E Gate, Row 10/11 Legal Research + Case Law Schema Patch
  ve RAG Corpus Policy Foundation contract'ları değişmedi.
- **ROW 19D Authentication Enablement Slice 1 — Local Key Custody and Auth
  Seam Enablement — DONE / LOCKED.** Exact scope **3 NEW + 2 MODIFIED = 5
  dosya**dır. Mevcut `KeyProvider` arayüzü genişletilmeden fail-closed
  local-file custody desteği bağlandı; key ile server pepper ayrı tutulur ve
  yalnız açık operatör `initialize`/rotation komutlarıyla oluşturulur veya
  döndürülür. Production seçiminde `InMemoryKeyProvider` veya sessiz fallback
  yoktur. Gerçek Windows ACL, processler-arası serialization, doğru commit /
  reporting semantiği, gerçek callback regresyon kanıtı ve handle-bound
  namespace koruması sağlandı. İlk bağımsız inceleme **F1 HIGH + F2–F5
  MEDIUM** buldu; yalnız üç dosyalık remediation sonrasında bağımsız re-review
  F1–F5'in tamamını kapattı. Exact final verdict:
  `ROW 19D AUTHENTICATION ENABLEMENT SLICE 1 LOCK-READY — F1–F5 CLOSED, NO BLOCKING FINDINGS`
- **ROW 19D Authentication Enablement Slice 2 — Azure Key Vault Secrets
  Custody Provider Foundation — DONE / LOCKED.** Kullanıcı tarafından
  onaylanan corrected final scope'un exact 11-path allowlist'i (**2 NEW +
  9 MODIFIED**) üzerinde implement edildi: Azure Key Vault Secrets
  üzerinde **read-only, versioned custody snapshot foundation**. Tek,
  shared, immutable, process-local snapshot/manager; `KeyProvider` ve
  server pepper AYNI secret version'ından ATOMİK türetilir. Yalnız
  latest-version exact-name `get_secret(name)`; LIST/version
  enumeration/write/delete/recover/purge YOK; prior-version veya
  local-file fallback YOK. Tek SDK retry katmanı: **2 total attempt,
  1.0s connect + 1.0s read, ≤0.25s backoff/Retry-After, 5.0s outer
  monotonic budget**; revoked generation + deadline completion gate ile
  late publish ENGELLENİR. Credential yalnız explicit Managed Identity /
  Workload Identity; `DefaultAzureCredential` ve developer credential
  fallback'ları YASAKTIR. Mevcut `VERGI_KEY_PROVIDER_KIND` selector'ı
  TEK authority olarak korunur; `local_file` ve `kms` Slice 1
  davranışları DEĞİŞMEDİ. Auth (login/callback/logout) ve altı CSRF
  yolunda async/offload + generic 500/503 fail-closed sınıflandırma.
  Migration ve security-event vocabulary DEĞİŞMEDİ (5 migration;
  18/18). Bağımsız inceleme final verdict'i:
  `ROW 19D AUTHENTICATION ENABLEMENT SLICE 2 LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Row 19D Slice 2 checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce).
- **Row 19B OIDC Confidential-Client Remediation — DONE / LOCKED.**
  CLAUDE.md §9 kapsamında LOCKED Row 19B, downstream incompatibility
  gerekçesiyle dar biçimde yeniden açıldı: exact kapsam **0 YENİ + 6
  DEĞİŞTİRİLMİŞ** dosya. `EntraProviderConfig` artık zorunlu,
  `field(repr=False)` bir `client_secret` alanı taşır; eksik/
  non-string/boş/whitespace değerler fail-closed reddedilir; secret
  asla normalize edilmeden ham (verbatim) saklanır. Gerçek Authlib
  `AsyncOAuth2Client` ile `token_endpoint_auth_method=
  "client_secret_post"` kullanılır; PKCE S256 korunur; authorization
  URL'ye secret taşınmaz; `Authorization: Basic`/`client_assertion`/
  `private_key_jwt`/fallback YOKTUR. `ui/auth_routes.py` ve `scripts/
  iam_bootstrap_probe.py` aynı `VERGI_ENTRA_CLIENT_SECRET`
  sözleşmesine bağlıdır. Migration/şema/data/dependency/route/CLI/
  custody/MFA/cookie/selector/hosting/cloud değişikliği YOK.
  İmplementasyon ve bağımsız inceleme ayrı oturum/model zincirinde
  yürütüldü. Final sonuç: **0 Critical / 0 High / 0 Medium**. Final
  verdict:
  `ROW 19B OIDC CONFIDENTIAL-CLIENT REMEDIATION LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Row 19B OIDC Confidential-Client Remediation checkpoint özeti,
  §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce).
- **Fact Verification Workflow — DONE / LOCKED.** Pilot Readiness
  Adım 1 tamamlandı (bkz. Pilot Readiness Priority Reconciliation
  kararı — bu roadmap-lock turu Adım 0/1/2 sıralamasının `CLAUDE.md`'ye
  İLK kaydıdır; önceki bir roadmap-lock turu bu kaydı henüz yapmamıştı,
  aşağıdaki "Pilot Readiness Adım 2" pointer'ı bu yüzden doğrudan bu
  turda önceki "Row 19D External Activation / Adoption Gate — ACTIVE /
  NEXT" pointer'ının yerini alır). Exact uygulama kapsamı **6 YENİ + 12
  DEĞİŞTİRİLMİŞ = 18 dosya**; sıfır schema değişikliği; sıfır
  migration; sıfır web route; sıfır cloud/Entra değişikliği. Yeni,
  CLI-only `verification.fact` action family; altı gerçek state
  transition; üç self-transition fail-closed reddedilir; pozitif
  hedeflerde evidence/locator zorunluluğu; safe replay + explicit
  attempt identity; re-promotion verification-loss guard; downstream
  stale uyarısı; gerçek timeline propagation ve gerçek deadline
  `blocked_unverified_anchor → calculated` zinciri kanıtlı. İlk
  bağımsız review: **NOT LOCK-READY**, F1 Medium + F2 Medium. Exact
  5-file remediasyon (0 YENİ + 5 DEĞİŞTİRİLMİŞ). Final re-review
  verdict'i exact olarak:
  `FACT VERIFICATION WORKFLOW LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`
  (bkz. Fact Verification Workflow checkpoint özeti, §5 sonrası,
  "## 6. Cross-Cutting Backlog"dan hemen önce).
- **Pilot Readiness Adım 2 — Case-Data Repository Protection — DONE /
  LOCKED.** Exact kapsam **1 YENİ + 1 DEĞİŞTİRİLMİŞ = 2 dosya**:
  `.gitignore` (MODIFIED — tek, root-anchored, istisnasız `/data/cases/`
  kuralı; negation YOK) ve `ui/tests/test_case_data_gitignore_guard_
  isolated.py` (YENİ — kalıcı, non-tautological regresyon testi).
  Tracked `case_0001` fixture'ının TAMAMI (65 dosya) tracked kalır;
  edit/delete normal ` M`/` D` olarak görünür ve stageable kalır.
  `case_0001` içine veya herhangi bir başka case dizinine eklenen YENİ
  untracked içerik, normal `git add -A`, `git add .` ve IDE "stage all"
  akışından korunur; yeni bir fixture dosyası yalnız açık, incelenen
  `git add -f` ile eklenebilir. Configurable repo-dışı case root
  implementasyonu bu slice'a DAHİL DEĞİLDİR — post-pilot Adım 13c için
  ayrı bir scope/onay turu gerektirir. Final bağımsız verdict, exact
  olarak:
  `PILOT READINESS STEP 2 CASE-DATA REPOSITORY PROTECTION LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Pilot Readiness Adım 2 checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce). **Dar, exact güvenlik iddiası**
  (abartılmaz, "tüm case verisi güvenlidir" veya "risk tamamen kapandı"
  DENMEZ): normal `git add -A` / `git add .` / IDE stage-all yoluyla
  `data/cases/` altındaki YENİ untracked case içeriğinin kazara
  stage/commit edilmesi engellenir (bkz. checkpoint özeti §O).
- **Pilot Readiness Adım 3 — Runner / Environment / Skip Reporting —
  DONE / LOCKED.** Exact kapsam **4 YENİ + 1 DEĞİŞTİRİLMİŞ = 5 dosya**:
  `scripts/run_ui_tests.py` (YENİ — tek, dürüst, fail-closed test
  çalıştırıcısı), `scripts/sweep_env_guard.py` (YENİ — çalıştırıcının her
  koşuda private dizine bayt-bayt kopyaladığı `sitecustomize` guard
  kaynağı), `ui/tests/test_run_ui_tests_isolated.py` (YENİ — T.1),
  `ui/tests/test_run_ui_tests_integration_postgres.py` (YENİ — T.2,
  gerçek PostgreSQL) ve `ui/tests/test_rag_bundle_mutation_integration_
  postgres.py` (DEĞİŞTİRİLMİŞ — `run_cli()`'de tek satır
  `authz_conn_factory=pg_connect`). İki yerel commit: `4ee72ef` (beş
  yol) ve `2afff40` (RAG kapısı K.1 daraltması); ikisi de yalnız yerel,
  **push YAPILMADI**. Çalıştırıcı, PostgreSQL gerektiren modüllerin
  sessiz 0-check/exit-0 görünmesini, counted skip ile informational
  skip'in karışmasını ve `.env`/network/secret sızıntısını mekanik
  olarak engeller; tek yetkili çıktı sırası: exit code > özet
  varlığı/ad bağı > sayılar > ham PASS/FAIL çapraz kontrolü > SKIPPED
  taraması. Resmî `production-parity` (gerçek PostgreSQL) ve
  `rag-dependency` kapıları commit'li baytlarla exit 0 verdi (bkz.
  checkpoint özeti). Final verdict, exact olarak:
  `PILOT READINESS STEP 3 RUNNER / ENVIRONMENT / SKIP REPORTING LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Pilot Readiness Adım 3 checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce). **Dar, exact iddia**
  (abartılmaz): bu, Python-seviyesi guard sayaçlarına ve DSN'nin
  `127.0.0.1` + disposable kümeye sabitlenmesine dayanan bir test-
  disiplini çalıştırıcısıdır; libpq'nun C-seviyesi soketlerini
  `sys.addaudithook` göremez; production ortamı veya hosting doğrulaması
  DEĞİLDİR.
- **Pilot Readiness Adım 4a — LLM Gizlilik Sınırı: Fact Extraction
  Takma Adlandırma — DONE / LOCKED.** Exact kapsam **2 YENİ + 9
  DEĞİŞTİRİLMİŞ = 11 dosya**, yerel commit `77f96c9` (push YAPILMADI):
  `src/llm_privacy_boundary.py` (YENİ — ortak, stdlib-only maskele/geri-
  çevir/tara modülü), `ui/tests/test_llm_privacy_boundary_isolated.py`
  (YENİ), `src/fact_extraction_engine.py`,
  `ui/services/fact_extraction_mutation_facade.py`,
  `ui/services/fact_extraction_mutation_adapters.py`, `ui/cli_mutate.py`
  ve beş test dosyası. Belge metni ve taraf adı/TCKN/VKN/IBAN/telefon/
  e-posta, fact extraction ajanının dış LLM'e (Anthropic) gitmeden önce
  geri çevrilebilir biçimde takma adlandırılır; harita YALNIZ bellekte
  tutulur, diske/log'a/audit'e/exception'a yazılmaz; hayatta kalan
  bilinen desen veya bozuk/bilinmeyen dönüş token'ı fail-closed reddedilir
  (pending YAZILMAZ); `masking_policy_version` ve
  `masking_extra_terms_digest` identity'ye girer (7→9 anahtar);
  önizleme maskeli metni gösterir, haritayı ASLA. Final bağımsız verdict,
  exact olarak:
  `PILOT READINESS STEP 4a LLM PRIVACY BOUNDARY LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Pilot Readiness Adım 4a checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce). **Dar, exact iddia**
  (abartılmaz): bu takma adlandırmadır, ANONİMLEŞTİRME DEĞİLDİR;
  tohum listesinde olmayan veya farklı yazılmış isimler hayatta kalır;
  sağlayıcı veri-işleme şartları, avukatlık sırrı ve KVKK yurt dışı aktarım
  soruları KODLA KAPANMAZ (Adım 6'ya `EXTERNAL LEGAL VERIFICATION
  REQUIRED`).
- **Pilot Readiness Adım 4a Remediation — Satır-Sonu Tire Maskeleme
  Açığının Kapatılması — DONE / LOCKED.** Exact kapsam **0 YENİ + 2
  DEĞİŞTİRİLMİŞ = 2 dosya** (`src/llm_privacy_boundary.py`, `ui/tests/
  test_llm_privacy_boundary_isolated.py`), yerel commit `218c081` (push
  YAPILMADI). Adım 4a'nın kendi §H madde 3'ünde disclose edilmiş, gerçek
  ASCII tire ile satır-sonuna bölünmüş bir taraf adının üç koruma
  katmanının HİÇBİRİNİ tetiklemeden tamamen maskesiz dış LLM'e gitmesi
  açığı kapatıldı (§9 security/privacy — kullanıcı talebi); backstop +
  ana maskeleyicinin ikisi de satır-sonu tire köprüsünü artık geçiyor;
  `MASKING_POLICY_VERSION` v1→v3. Bir bağımsız incelemenin bulduğu Bulgu
  F1 (fix'in kendisinin `possible_squeeze_seed_match` uyarı sayacını
  ilgisiz bir senaryoda sessizce düşürmesi — yeni sızıntı DEĞİL, kayıp
  sinyal) dar bir remediasyonla kapatıldı ve İKİNCİ, bağımsız bir
  incelemede doğrulandı. Final verdict, exact olarak:
  `PILOT READINESS STEP 4a LINE-WRAP HYPHEN REMEDIATION LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan
  hemen önce). Bu session ayrıca resmî `production-parity` (76/76 modül,
  5789 passed, 0 failed) ve `rag-dependency` (216 passed, 0 failed)
  kapılarını bu commit'e karşı doğrudan çalıştırıp temiz sonuç aldı.
  Adım 4a'nın diğer tüm disclosed limitleri (pseudonymization sınırı,
  bölünmüş TCKN/VKN, modelin token'ı yansıtıp yansıtmadığının
  ölçülmemesi, Anthropic/KVKK soruları) DEĞİŞMEDEN AÇIK kalır.
- **Pilot Readiness Adım 4a Remediation 2 — Bölünmüş TCKN/VKN Fail-Closed Maskeleme (R5) —
  DONE / LOCKED.** Exact kapsam **0 YENİ + 2 DEĞİŞTİRİLMİŞ = 2 dosya**
  (`src/llm_privacy_boundary.py`, `ui/tests/test_llm_privacy_boundary_isolated.py`), yerel
  commit `1aa709c` (push YAPILMADI). Adım 4a Remediation'ın kendi §I'sinde "DEĞİŞMEDEN AÇIK
  kalır" olarak bırakılan bölünmüş TCKN/VKN açığının bir kısmı bu turla KAPANMIŞTIR — dar,
  exact tanım: b2 kararıyla zaten bilinçli olarak informational-only bırakılmış
  whitespace/checksum-geçersiz adaylar, R5'in kapattığı blocker DEĞİLDİ; bunlar bilinçli
  olarak kabul edilmiş bir residual limitation olarak AÇIK KALMAYA devam eder (bu adayların
  risksiz olduğu veya kişisel veri içermediği İDDİA EDİLMEZ). R5'in gerçekten kapattığı
  blocker daha dardı: belirli GERÇEK line-wrap-hyphen ve (ikinci turda ortaya çıkan)
  karışık-türlü (mixed-kind) biçimlerin üç koruma katmanının (maskeleyici, backstop, sayaç)
  HİÇBİRİNE hiç görünmeden, tamamen maskesiz biçimde dış LLM'e gidebilmesiydi.

  Hibrit yüksek/düşük-sinyal politikası (Karar #1a): R5 tarayıcısına
  (`_scan_split_digit_runs`) ulaşan, zero-width/soft-hyphen veya gerçek line-wrap-hyphen
  ayraçlı, exact 10/11 haneli adaylar checksum aranmadan maskelenir. Düz whitespace ayraçlı
  bir aday için üç KESİN sonuç vardır: `tckn_is_valid`/`vkn_is_valid` AÇIK `False` dönerse
  aday informational-only kalır ve MASKELENMEZ; AÇIK `True` dönerse maskelenir; bir istisna
  fırlatırsa veya beklenmeyen (non-boolean) bir değer dönerse fail-closed olarak yine
  MASKELENİR (`_digit_checksum_permits_masking()` — belirsizlik ASLA "checksum'ı atla"
  anlamına gelmez).

  **Karar A** (kullanıcı kararı): pre-existing `ZeroWidthDigitRunError` guard'ı (R5'ten ÖNCE
  var, bu remediasyonda DEĞİŞMEDİ) KORUNDU. Saf zero-width bölünmeler R5 tarayıcısına HİÇ
  ULAŞMADAN, bu guard tarafından `mask_prompt_inputs()`'in en başında TOPYEKÜN reddedilir —
  yani "bütün yüksek-sinyalli adaylar maskelenir" gibi mutlak bir iddia YANLIŞTIR; saf
  zero-width adaylar MASKELENMEZ, REDDEDİLİR. Bu ret, R5'in "mask-or-refuse-before-outbound"
  sözleşmesini karşılar. Karışık-türlü (bir zero-width karakterin hemen ardından düz boşluk
  gibi) bölünmeler ise bu guard'ı tetiklemez ve R5 tarayıcısına ulaşır — bunlar için
  `_match_split_separator()` ardışık, farklı türden ayraç atomlarını TEK blok halinde
  birleştirip HERHANGİ biri yüksek-sinyalliyse TÜM bloğu yüksek-sinyal sayacak şekilde
  yeniden yazıldı (`_match_separator_atom()` eski tek-atom mantığını AYNEN korur).

  Final bağımsız yeniden inceleme verdict'i: **PASS — LOCK-READY** (bir önceki turun
  vacuous-assertion bulgusu kapatıldıktan sonra). Final kapılar (commit'ten ÖNCE, sonradan
  `1aa709c` commit'ine byte-identical olarak alınan working-tree baytlarında çalıştırıldı —
  ayrıntı için bkz. tam checkpoint bölümü §I): odaklı **619/619 PASS**; resmî
  `production-parity` **77/77 modül PASS** (guard positive controls 10/10); resmî
  `rag-dependency` **3/3, RAG_GATE_PASS**.

  (bkz. checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce). **Dar,
  exact iddia** (abartılmaz): Adım 4a'nın diğer tüm disclosed limitleri (pseudonymization
  sınırı — bu takma adlandırmadır ANONİMLEŞTİRME DEĞİLDİR, tohumda olmayan/farklı yazılmış
  isimler hayatta kalır; ÜÇ VEYA DAHA FAZLA farklı ayraç türünü aynı blokta birleştiren
  senaryolar AYRICA regresyon testiyle KANITLANMADI; modelin token'ı yansıtıp
  yansıtmadığının ölçülmemesi; Anthropic/KVKK soruları) DEĞİŞMEDEN AÇIK kalır.
- **Pilot Readiness Adım 4b — Ham Veri Taşıyan Ajanların ve `app.py`'nin
  Mekanik Kapatılması — DONE / LOCKED.** Exact kapsam **0 YENİ + 7
  DEĞİŞTİRİLMİŞ = 7 dosya**, yerel commit `2097b9e` (push YAPILMADI):
  `ui/cli_mutate.py`, `ui/services/agent_generation_mutation_facade.py`,
  `ui/services/legal_research_case_law_mutation_facade.py`, `app.py` ve üç
  test dosyası. `issue_spotting`, `legal_research`, `evidence`, `argument`
  ajanları ham fact cümlesi/belge alıntısı dış LLM'e yolladığı ve bunlar için
  maskeleme OLMADIĞI için, bu dört ailede `--with-agent` (ajan modu) hem
  önizlemede hem uygulamada KOŞULSUZ reddedilir — iki bağımsız katmanda:
  CLI usage-shape (her bağlantı/authz/dosya/model erişiminden ÖNCE; CLI
  `llm_client` geçmez) ve facade (`llm_client is None` = üretim istemcisi;
  enjekte edilmiş sahte istemci çalışmaya devam eder). `legal_research` reddedilirken
  aynı facade/CLI dalını paylaşan `case_law` (C2) açık kalır; deterministik mod,
  fact_extraction, risk_strategy, drafting, timeline, deadline AYNEN çalışır.
  `--with-agent`'ın tümden reddi, ağsız agent modunun model çağrılmadan agent
  provenansı yazan kalıcı sahte kaydını (Row 19C-3c-iv F3) da ortadan kaldırır.
  Hiçbir kapısı olmayan `app.py` (avukatın serbest metnini `src/rag.py`
  üzerinden Anthropic'e gönderebilirdi; bugün gizli/latent, canlı değil) kapatıldı:
  modül-başı `src.rag` importu ve ölü sohbet gövdesi silindi, sabit mesaj +
  `SystemExit(2)`. Final bağımsız verdict, exact olarak:
  `PILOT READINESS STEP 4b RAW-DATA AGENT CLOSURE LOCK-READY — NO BLOCKING FINDINGS`
  (bkz. Pilot Readiness Adım 4b checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce).
- **Pilot Readiness Adım 4c — Kalan Outbound LLM Yollarının Kapatılması —
  DONE / LOCKED.** Exact kapsam **1 YENİ + 9 DEĞİŞTİRİLMİŞ = 10 dosya**,
  yerel commit `9a3b3b2` (push YAPILMADI). 4b'nin "fact_extraction dışında
  ham-veri taşıyan dört ajan kapalı" kilidi kullanıcının bugünkü bar'ını
  ("ham veri gitmiyor" DEĞİL, "fact_extraction dışında hiçbir outbound
  yol teknik olarak çalışamaz") KARŞILAMIYORDU — bağımsız bir gap analizi
  altı gerçek gap buldu: `case_law`/`risk_strategy`/`drafting` ajan modu
  CLI'dan erişilebilir ve canlıydı; `python src/evaluation.py` bugün
  FİİLEN gerçek bir Anthropic çağrısı tetikliyordu (T06); `python
  src/rag.py` doğrudan çalıştırma yalnız ilgisiz bir `RagBundleNotPinnedError`
  çökmesiyle tesadüfen kapalıydı. Bu alt-faz altısını da kapattı:
  (1) `case_law`/`risk_strategy`/`drafting` için her iki facade'de
  (`agent_generation_mutation_facade.py`,
  `legal_research_case_law_mutation_facade.py`) AYRI, doğru gerekçeli
  yeni `*_PILOT_POLICY_REFUSED_ROW_KEYS` kümeleri (4b'nin "ham metin"
  kümeleri — üç ailenin prompt'u GERÇEKTEN ID/enum-only, bu doğru kaldı,
  DOKUNULMADI) + `ui/cli_mutate.py`'de iki katmanlı (CLI usage-shape +
  facade) refusal; deterministik mod AYNEN çalışıyor; (2) `src/rag.py`'nin
  üç gerçek ağ-dokunan fonksiyonu (`rewrite_query`/`rerank_candidates`/
  `generate_answer`) tek, KOŞULSUZ (env-değişkeni YOK) `_get_client()`
  noktasına indirildi — `anthropic` import'undan ÖNCE reddediyor; modül-
  seviyesi `client = Anthropic()` kaldırıldı; `__main__` artık
  `RagBundleNotPinnedError`'a hiç ulaşmadan reddediyor — RAG Slice 2
  aktive olduğunda bu yol KENDİLİĞİNDEN açılmayacak; (3) `src/evaluation.py`/
  `src/evaluation_v6.py` her biri kendi bağımsız `__main__` kapanışını
  aldı (T06 dahil gövdeleri DOKUNULMADI — asıl güvenlik `rag.py`'nin
  gate'i, bu yalnız UX/exit-code netliği). Yeni test dosyası (50 kontrol)
  gerçek, patch'lenmemiş `rag.answer_question()`'ı (mock DEĞİL) çağırıp
  gate'in durdurduğunu, "RAG Slice 2 simülasyonu" pozitif kontrolüyle
  `RagBundleNotPinnedError`'a bağımlı OLMADIĞINI, gerçek OS subprocess
  kanıtlarıyla (normal VE poisoned-`anthropic` ortamda) üç script'in de
  kapalı olduğunu kanıtlıyor. İlk bağımsız inceleme bir HIGH bulgu
  buldu (F1: yeni test dosyasının kendi ağ-guard mekanizması resmî
  sweep'in guard muhasebesiyle çakışıp `GUARD_INHERITANCE_MISMATCH`
  üretiyordu — yalnız test dosyasının kendi içinde, dört LOCKED üretim
  dosyasının hiçbirinde değil); dar, tek-dosyalık bir remediasyon ve
  hedefli bir ikinci bağımsız inceleme F1'i kapattı. Bu session ayrıca
  resmî `production-parity` (77/77 modül, 5890 passed, 0 failed) ve
  `rag-dependency` (216 passed, 0 failed) kapılarını bu commit'e karşı
  doğrudan çalıştırıp temiz sonuç aldı. Final verdict, exact olarak:
  `PILOT READINESS STEP 4c LOCK-READY — F1 CLOSED, NO BLOCKING FINDINGS`
  (bkz. checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan
  hemen önce). **Dar, exact iddia** (abartılmaz): `rag-dependency`
  profilinin modül listesi (`RAG_GATE_MODULES`) sabit/hardcoded 3
  modülden oluşur (builder/reader/dependency_smoke) — yeni test dosyası
  bu sabit listeye DAHİL DEĞİLDİR; dosyanın `anthropic`-kurulu ortamdaki
  (root `.venv`) davranışı bunun yerine hem implementer hem iki bağımsız
  inceleme tarafından TEKRARLANAN standalone koşularla (50/50 PASS)
  doğrudan doğrulanmıştır. `rag.py`'ye DI seam BİLİNÇLİ olarak
  EKLENMEDİ (kullanıcı kararı) — `evaluation.py`/`evaluation_v6.py`'nin
  iç mantığı hâlâ fake client'a karşı test EDİLEMEZ; bu ayrı, gelecekteki
  bir maddedir. `_get_client()`'in gate'i `anthropic`'i import etmeden
  önce çalışır; `anthropic`'in kurulu olup olmaması/API key varlığı
  ASLA bir güvenlik kontrolü sayılmaz.
- **Pilot Readiness Adım 5 — Resmî Tatil Takvimi Registry'si +
  `calendar_complete` Türetimi — DONE / LOCKED.** Exact kapsam **5 YENİ +
  9 DEĞİŞTİRİLMİŞ = 14 dosya**, yerel commit `203c71a` (push YAPILMADI).
  Elle `--holiday`/`--calendar-complete` bayrakları tamamen kaldırıldı;
  yerine git-governed `data/holiday_calendar/holiday_calendar.json`
  (2024–2035, TÜMÜ `verified:false`, sıfır tatil adı/tarihi — K3) +
  şema + `src/holiday_calendar_validator.py` geldi. `deadline_calculator.py`
  (LOCKED Row 8) tatil kaydırmasını ÖNCE, kapsanan-yıl kontrolünü SONRA
  yapacak şekilde yeniden sıralandı (bağımsız incelemenin döngüsellik
  bulgusu — kaydırma kapsanmayan bir yıla itiyorsa `needs_review`, hiçbir
  ara "calculated" durum sızmaz); `deadline_engine.py` (LOCKED Row 8)
  takvimi yükler/doğrular/audit'e bağlar; takvim baytları
  `generation.deadline`'ın `input_digest`'ine girdi (v2→v3, Row 19C-3c-i
  ruleset/provisions emsaliyle aynı sınıf); `generation_mutation_adapters.py`
  DOKUNULMADI (K5). Final bağımsız verdict, exact olarak:
  `ADIM 5 IMPLEMENTATION LOCK-READY` (bkz. Pilot Readiness Adım 5
  checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen
  önce). **Dar, exact iddia** (abartılmaz): üretim `holiday_calendar.json`
  hâlâ tamamen doğrulanmamıştır — avukat Adım 6'da en az bir yılı
  onaylayıp `verified:true` yapana kadar, `next_business_day_if_holiday`
  policy'li tek aktif kural HİÇBİR gerçek dosyada `calculated` bir tarih
  ÜRETMEZ.
- **Pilot Readiness Adım 6 — Avukat Doğrulaması — ACTIVE / NEXT.** Avukat
  paketi (`avukat_dogrulama_paketi_DRAFT2`) repo dışında hazırdır ve avukata
  verilebilir — Adım 4a Remediation (satır-sonu tire maskeleme açığının
  kapatılması), Adım 4b (ham-veri kapatma), Adım 4c (kalan outbound LLM
  yollarının kapatılması) ve Adım 5 (takvim registry'si) kilitleriyle
  önkoşulları sağlanmıştır. Bu pointer KODLAMA/İMPLEMENTASYON YETKİSİ VERMEZ —
  Adım 6 avukatın SORU 3.1-3.8/5.1-5.4'ü yanıtlaması ve altın örnekleri
  doldurmasıdır (bir hukuk işidir, bir kod turu DEĞİL). Avukat doğrulamasının
  mali tatil alt-bölümüne ilişkin yazılı cevap alınmış ve bu cevap
  doğrultusunda Adım 7'nin mali tatil alt-kapsamı ayrı, dar bir implementasyon
  turuyla DONE/LOCKED olmuştur (bkz. aşağıdaki Pilot Readiness Adım 7 — Mali
  Tatil pointer ve checkpoint özeti). Adım 6'nın kalan soruları/altın
  örnekleri, takvim içeriğinin
  (`data/holiday_calendar/holiday_calendar.json`'daki ilgili yılların
  `verified:true`'ya çevrilmesi) doğrulaması ve Adım 7'nin mali tatil
  dışındaki kalan deadline hardening alt-kapsamları ayrıca tamamlanmış veya
  yetkilendirilmiş DEĞİLDİR — bu nedenle Adım 6'nın genel statüsü ACTIVE /
  NEXT olarak kalır. Açıkça BAŞLAMAMIŞ/YETKİLENDİRİLMEMİŞ: Adım 8 yerel
  PostgreSQL/IAM adoption; Adım 9 sentetik concierge dry-run; Adım 10 ilk
  gerçek concierge pilotu; Adım 11 Entra/P1; Adım 12 hosting/Key Vault;
  configurable external case root (post-pilot Adım 13c). Eski "Row 19D
  External Activation / Adoption Gate" pointer'ının kapsadığı maddelerin
  (gerçek Entra tenant/app registration, `acrs` claims dış doğrulaması,
  Conditional Access/authentication-context preflight'i, Key Vault custom
  GET-only role deployment/adoption, Graph izinleri, loopback-only middleware
  ile `X-Forwarded-For` yasağının hosting uyumluluğu) TAMAMI Entra/P1 (Pilot
  Readiness Adım 11) ve hosting/Key Vault (Adım 12)'ye ERTELENMİŞ olarak
  KALMAYA devam eder — bu maddeler KAPANMAMIŞTIR (bkz. Row 19B OIDC
  Confidential-Client Remediation checkpoint özeti). İlk pilot modeli
  concierge olarak korunmaktadır. Corpus acquisition/population bu pointer
  tarafından YETKİLENDİRİLMEZ. Yeni bir roadmap Row numarası İCAT
  EDİLMEMİŞTİR; mevcut Pilot Readiness adım numaraları korunur.
- **Pilot Readiness Adım 7 — Mali Tatil (5604 sayılı Kanun) Deadline Handling
  — DONE / LOCKED.** 5604 sayılı Malî Tatil İhdas Edilmesi Hakkında Kanun
  m.1'in 1, 3, 5, 6 ve 7. fıkralarının, LOCKED Row 8
  `src/deadline_calculator.py` dosyasına deterministik bir duraklama/devam
  mekanizması, fiilî tebligatın süreye etkisi ve fail-closed ayrımlar olarak
  entegrasyonudur. Exact kapsam **1 YENİ + 5 DEĞİŞTİRİLMİŞ = 6 dosya**
  (`data/deadline_rules/deadline_rules.json`, `data/documents.json`,
  `data/provisions.json`, `src/deadline_calculator.py`,
  `ui/tests/test_deadline_calculator_mali_tatil_isolated.py` [YENİ],
  `ui/tests/test_deadline_calendar_derivation_isolated.py`); sıfır migration,
  sıfır şema değişikliği. 5604 m.1/3'teki "vergiyle ilgili işlemlere ilişkin
  dava açma süreleri" hükmünün İYUK m.7'deki genel vergi mahkemesi dava açma
  süresine uygulanabilirliğini doğrulayan avukat görüşü, kullanıcı tarafından
  doğrulanmış ve repo dışında saklanan haricî hukuk kanıtıdır — bu LOCK'un
  kendisi bu görüşü ÜRETMEZ, yalnız onun ışığında yapılan mühendislik
  kararlarını kayda geçirir. Implementasyon commit'i
  `ce3cb01c131728d3f26ce9af464b58161b46cdc5` ("Implement verified mali tatil
  deadline handling"); gerçek disposable PostgreSQL 16 + resmî
  `scripts/run_ui_tests.py --profile production-parity` koşucusuyla commit'li
  baytlar üzerinde doğrulandı: 78/78 modül PASS, 6074 passed/0 failed/8
  counted skip/14 informational skip, guard positive controls 10/10
  (`armed_count: 212 = expected_armed: 212`), migration 0001-0005 başarılı, 14
  PostgreSQL modülü gerçek loopback PostgreSQL ile PASS, protected
  manifest/secret scan temiz, residue yok (bkz. checkpoint özeti, §5 sonrası,
  "## 6. Cross-Cutting Backlog"dan hemen önce). Commit-öncesi bir koşuda
  `test_fact_verification_mutation_facade_isolated` modülünde
  `PermissionError: [WinError 5]` biçiminde tek seferlik bir Windows
  dosya-kilidi olayı gözlemlenmiştir; bu olay mali tatil kapsamı dışındaki,
  değiştirilmemiş bir modülde gözlenmiş, sonraki bağımsız ve commit-sonrası
  koşumlarda tekrar üretilememiş ve mali tatil implementasyonuna
  atfedilememiştir — runner/environment olayı olarak kayda geçirilmiştir.
  **Dar, exact iddia** (abartılmaz): bu LOCK yalnız mali tatil mekanizmasını
  kapsar — `data/holiday_calendar/holiday_calendar.json` içindeki 2024-2035
  yılları hâlâ `verified:false`'tur (gerçek dosyalar bu nedenle
  `needs_review`'a düşebilir); 27.01.2016 öncesi mali tatil hükümlerinin
  temporal modellemesi YOKTUR; `stopping_event_status` bu kapsamın DIŞINDADIR
  ve ayrı bir çalışma olarak açık kalır; gelecekte mali tatil ref'i taşıyıp
  İYUK adli tatil ref'lerini TAŞIMAYAN yeni bir deadline rule eklenirse
  grace-floor/recess birleşimi yeniden doğrulanmalıdır (mevcut üretim
  kuralında bu durum erişilemezdir); bu LOCK pilotun genel hazır olduğunu,
  tatil takviminin doğrulandığını veya uygulamanın production-ready olduğunu
  İDDİA ETMEZ.
- **Holiday Calendar Schema V2 — Phase A Technical Plumbing — DONE /
  LOCKED.** Yalnız teknik tesisat; veri popülasyonu DEĞİL. Exact kapsam
  **0 YENİ + 7 DEĞİŞTİRİLMİŞ = 7 dosya**, yerel commit
  `1366e8e40d7923c304f4a818caa65b211764b593` (parent
  `d2e66fe6b75bb95fa3fe3f00ffe3dbc241f99023`; push YAPILMADI):
  `data/holiday_calendar.schema.json` (title V1→V2; `schema_version`
  const 1 DEĞİŞMEDİ; `half_day_policy` top-level kaldı, mevcut üç değer
  `not_decided`/`counts_as_holiday`/`counts_as_working_day` korunup
  dördüncü additive değer `needs_review_if_deadline_day` eklendi;
  `holiday_entry`'ye opsiyonel, additive `observances[]` — legacy flat
  kayıt uyumluluğu korunur; `observance_id` enum'u 17 canonical değer),
  `data/holiday_calendar/holiday_calendar.json` (YALNIZ
  `calendar_version` 1→2 — başka hiçbir içerik değişikliği; şema
  `calendar_version`'ı `integer, minimum 1` olarak bırakır, 2'ye
  PİNLEMEZ), `src/holiday_calendar_validator.py`
  (`HOLIDAY_CALENDAR_VALIDATOR_VERSION` `"1"`→`"2"`; 17 kayıtlı canonical
  observance registry'si ve registry doğrulamaları; ulusal duplicate
  anahtarı yıl-içi `observance_id`, dinî duplicate anahtarı
  `(family, block_index, observance_id)`; çok bloklu yıllarda her blok
  bağımsız doğrulanır; 2024–2035 exact dinî blok-sayısı sözleşmesi —
  Ramazan 2033=2, diğer Ramazan ve Kurban blokları=1; sözleşme dışı
  `verified:true` + `observances[]` yıl sessiz tahmin yerine fail-closed
  reddedilir), LOCKED Row 8 `src/deadline_calculator.py` (full-day +
  half-day çakışmasında full-day üstün gelir;
  `needs_review_if_deadline_day` yalnız final gün GERÇEKTEN
  yalnız-half-day olduğunda fail-closed `needs_review` üretir — `reason`
  = `holiday_calendar_half_day_deadline_requires_review`; diğer üç
  politikada davranış DEĞİŞMEDİ; deadline dalında sıfır silme) ve üç
  test dosyası (yalnız additive/tutarlılık kanıtı). Bağımsız final
  re-review verdict'i, exact olarak:
  `PHASE A READY FOR COMMIT AUTHORIZATION`
  (bkz. Holiday Calendar Schema V2 — Phase A Technical Plumbing
  checkpoint özeti, §5 sonrası, "## 6. Cross-Cutting Backlog"dan hemen
  önce). **Dar, exact iddia** (abartılmaz): üretim takvimi HÂLÂ
  TARİHSİZDİR — 12 yıl (2024–2035), her yılda `holidays: []` ve
  `source_refs: []`, 0 `verified:true`, tüm `verification_ref` değerleri
  `null`, hiçbir yerde `observances` anahtarı yok, üretim
  `half_day_policy` hâlâ `not_decided` (dördüncü politika şema ve
  hesaplayıcı düzeyinde MEVCUT, üretimde BENİMSENMEMİŞ). Hiçbir resmî
  tatil tarihi eklenmedi; hiçbir yıl `verified:true` yapılmadı; hiçbir
  `verification_ref` alınmadı; avukat doğrulaması (Adım 6) TAMAMLANMADI
  ve Adım 6 ACTIVE / NEXT olarak KALIR; pilotun genel olarak
  production-ready olduğu İDDİA EDİLMEZ. **Phase B (veri popülasyonu):
  NOT STARTED / NOT AUTHORIZED / BLOCKED ON REAL LAWYER verification_ref**
  — bu pointer Phase B için hiçbir kodlama/veri yetkisi VERMEZ.

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

### Row 18 — Lawyer UI (DONE / LOCKED — 18a: DONE/LOCKED, 18b: DONE/LOCKED, 18c: DONE/LOCKED — checkpoint özeti)

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

**18b kapsamı — DONE / LOCKED** (kullanıcı onayı, hedeflenen
`vergi_ui_runtime` ortamında `pip check` PASS + Row 18A 117/117 + Row
18B servis 69/69 + şablon 42/42 + route 115/115 = **343/343** test PASS
ile): mevcut Layer B ("kayıt bazlı inceleme kararı": `needs_review` ->
`confirmed`/`rejected` veya `needs_review` -> `accepted_for_follow_up`/
`dismissed`) akışı, 5 ailenin (Evidence/Argument/Risk-Strategy/
Drafting/QA) **12 review-kind adaptörü** üzerinden TEK bir arayüzde
toplanır: `evidence.candidate`, `evidence.suggestion`,
`argument.claim`, `argument.counterargument`, `argument.rebuttal`,
`argument.suggestion`, `risk_strategy.risk`, `risk_strategy.strategy`,
`risk_strategy.suggestion`, `drafting.section`, `drafting.suggestion`,
`qa.suggestion`. Tam **11 dosyalık** Row 18B uygulama kapsamı — 4'ü
18a'nın var olan `ui/` dosyalarında değişiklik, 7'si yeni dosya:
`main.py` (değişiklik — Layer B route seti + CSRF üretim/doğrulama
yardımcıları eklendi), `services/common.py` (değişiklik — 6 yeni
`ReviewUiError` alt sınıfı eklendi), `static/style.css` (değişiklik —
salt-sunumsal `.confirm-form`/`.confirm-check`/`code.hash` eklendi),
`templates/case_view.html` (değişiklik — "İncelemeler (Layer B)" nav
linki eklendi), `services/review_registry.py` (yeni — 12 review-kind
registry), `templates/review_detail.html`, `templates/review_result.html`,
`templates/reviews_list.html` (yeni), `tests/test_review_routes.py`,
`tests/test_review_service_isolated.py`, `tests/test_review_templates_isolated.py`
(yeni).

**18b final güvenlik/mimari durumu** (bir hedefli remediation turu, bir
script-context JSON serialization sertleştirme turu, bir salt-okunur
LOCK-hazırlık incelemesi ve bir domain-error redaksiyon remediation
turuyla ulaşıldı — kod tekrar okunarak doğrulandı, varsayılmadı):

- **Backend-otoriter doğrulama/hedef-durum/geçiş kuralları** —
  `review_registry.py` var olan `src/*_review.py` (Row 12-16) modüllerinin
  İÇ MANTIĞINI (parent-dependency, R1-R6, stale-source, previous_state
  kontrolü, backup/atomic-write/rollback) YENİDEN YAZMAZ/KOPYALAMAZ;
  array/id/state alan adları ve hedef-durum allowlist'i HER ZAMAN ilgili
  backend modülünün KENDİ canlı sabitinden okunur (evidence/qa için
  registry'nin kendi, koddan doğrulanmış sabit metadata'sı — bu iki modül
  BY_TYPE sözlüğü taşımadığı için). R1-R6 parent-dependency semantiği
  aynen korunur; Risk/Strategy R2 hem reddi HEM DE `dismissed` kabul
  yolu, backend'in kendi `run_self_test()` fixture-üretim deseni
  (`FakeRiskStrategyLLMClient` + `build_risk_strategy_engine_output` +
  `_recompute_coverage`) yeniden kullanılarak bağımsız doğrulandı.
- **case_id ve review_kind allowlist'leri** — `_resolve_case` (case_id)
  ve `REVIEW_KIND_REGISTRY` (review_kind, sabit 12 değer) her route'un
  en başında; bilinmeyen/geçersiz değer her zaman aynı genel 404/hata.
- **Loopback-only erişim + aynı-origin doğrulaması** — 18a'nın middleware/
  `_check_csrf_and_origin` deseniyle AYNI, Layer B route'larında da
  uygulanıyor.
- **Beş parçalı CSRF bağlama** — `case_id + review_kind + record_id +
  target_state + canonical_hash` (HMAC, sabit-zamanlı doğrulama);
  `target_state` GET anında henüz seçilmediğinden her olası hedef için
  ayrı bir token üretilip sayfaya gömülür, `<select>` değiştikçe JS ile
  o hedefin token'ına güncellenir — POST anındaki `target_state` üretim
  hedefinden FARKLIYSA doğrulama BAŞARISIZ olur.
- **Mutasyon öncesi stale canonical-hash reddi** — `reviewreg.apply_transition`
  dosya varlığı + güncel hash'i, HERHANGİ bir backend adaptörü
  çağrılmadan ÖNCE kontrol eder; değiştiyse `ReviewStaleViewError`, sıfır
  mutasyon.
- **Fail-closed canonical yükleme/doğrulama** — `_load_and_validate_canonical`
  dosya okuma + ilgili ailenin KENDİ validator'ını (`raise_on_error=False`)
  TEK korumalı blokta çalıştırır; validator'ın ÖN KOŞUL yüklemesinde
  (`raise_on_error` bayrağından bağımsız) fırlayabilecek HERHANGİ bir
  beklenmeyen exception `ReviewLiveViewInvalidError`'a çevrilir — hiçbir
  kayıt doğrulanmadan render edilmez.
- **Tarayıcıya sabit, güvenli hata mesajları; domain exception'lar
  redakte edilir** — `_error_page` 18a'daki ilkeyle AYNI (sabit kod/mesaj
  tablosu, ham `str(exception)`/traceback/mutlak path asla yanıta
  girmez). Ayrıca 5 GERÇEK backend domain hata sınıfı
  (`EvidenceReviewError`/`ArgumentReviewError`/`RiskStrategyReviewError`/
  `DraftingReviewError`/`QaReviewError`) için `_domain_error_page`
  **ARTIK bu sınıfların KENDİ mesajını (`str(error)`) DA tarayıcıya
  geçirmez** — LOCK-hazırlık incelemesinde 5 backend'in TAMAMININ aynı
  domain sınıflarıyla mutlak dosya yolu içeren bir mesaj ("Canonical
  X.json bulunamadı:\n{mutlak_path}") fırlatabildiği kanıtlandı; tarayıcı
  artık HER ZAMAN tek bir sabit `REVIEW_DOMAIN_REJECTED` mesajı görür,
  orijinal exception TÜRÜ + TAM mesaj yalnız yerel `logging`'e (repoya/
  diske YAZILMADAN) yazılır — tanı için tam ayrıntı yerelde SAKLI kalır.
- **Script-context güvenli JSON serialization** — `review_detail.html`
  beş hedefe ait CSRF token haritasını (`csrf_tokens_by_target`) ham
  Python sözlüğü olarak main.py'den alır ve Jinja'nın KENDİ `|tojson`
  filtresiyle (elle `json.dumps(...)` + `|safe` YERİNE) serileştirir —
  `<`, `>`, `&`, `'` Unicode kaçışa çevrilir, `</script>` gibi
  script-kıran diziler HİÇBİR ZAMAN ham/çalıştırılabilir biçimde
  görünmez; script-breakout test kapsamı bunu doğrudan kanıtlıyor.
- **İzole mutasyon testleri + gerçek data/src byte-bütünlüğü** — tüm
  Row 18B mutasyon/CSRF/stale-hash/domain-redaksiyon testleri
  `TemporaryDirectory` + sahte/geçici olarak değiştirilmiş modül
  attribute'larıyla (backend'in KENDİ kodu hiç değiştirilmeden) çalışır;
  gerçek `data/`/`src/` ağacının test öncesi/sonrası byte-düzeyinde
  DEĞİŞMEDİĞİ her test turunda ayrıca kanıtlandı. `case_0001` üzerinde
  GERÇEK bir Layer B inceleme mutasyonu HİÇ ÇALIŞTIRILMADI; Row 18B
  testleri hiçbir canonical, approval-audit, review-audit, history veya
  backup verisi ÜRETMEDİ.
- **`pip check` PASS ve 343/343 toplam test sonucu** — Row 18A 117/117 +
  Row 18B servis (saf-Python) 69/69 + Row 18B şablon (Jinja2) 42/42 +
  Row 18B route (FastAPI, TestClient) 115/115 — hedeflenen
  `vergi_ui_runtime` ortamında kullanıcı tarafından fiilen çalıştırıldı.

**18b KAPSAM DIŞI (bilinçli, Row 19/18c'ye bırakıldı, DÜZELTİLMEYECEK)**:

- `StarletteDeprecationWarning: Using httpx with starlette.testclient is
  deprecated; install httpx2 instead.` — 18a'dan devralınan, yalnız test
  altyapısını ilgilendiren, üretim çalışma zamanını ETKİLEMEYEN bağımlılık
  bakım backlog maddesi; `httpx2` bu fazda KURULMADI/ikame EDİLMEDİ.
- **Çapraz-süreç eşzamanlılık / lost-update koruması** — mevcut
  stale-hash kontrolü atomik bir compare-and-swap DEĞİLDİR; backend'in
  kendi bağımsız yeniden-okumasıyla arada dar bir TOCTOU penceresi
  vardır (18a'nın `approval_registry.case_scoped_approve`'ıyla AYNI
  şekilde, zaten kabul edilmiş desen). Atomik CAS/kilitleme, kimlik
  doğrulama, çoklu kullanıcı yetkilendirme ve ilgili production
  sertleştirme kontrolleri Row 19'a bırakıldı.
- Row 18b, 18a ile AYNI şekilde yerel, loopback, tek-kullanıcılı bir araç
  sınırı içinde kalır.

**18c kapsamı — DONE / LOCKED** (kullanıcı onayı ve bağımsız bir
salt-okunur LOCK-hazırlık incelemesi, hedeflenen `vergi_ui_runtime`
ortamında `pip check` PASS + Row 18A 117/117 + Row 18B 226/226 + Row
18C servis 77/77 + şablon 15/15 + route 51/51 + CLI 26/26 =
**169/169** (Row 18 toplamı **512/512**) test PASS ile): Row 15'in
yapılandırılmış avukat talebi girişinin görüntülenmesi, doğrulanması
ve kaydedilmesi. Row 18C uygulama kapsamı — 4'ü 18a/18b'nin var olan
`ui/` dosyalarında değişiklik, geri kalanı yeni dosya: `main.py`
(değişiklik — Row 18C route seti + case_id'ye özgü 128 KiB ASGI
gövde-boyutu ara-katmanı eklendi), `services/common.py` (değişiklik —
yeni `DraftingRequestUiError` alt sınıfları eklendi), `static/
style.css` (değişiklik — salt-sunumsal eklemeler), `templates/
case_view.html` (değişiklik — "Yapılandırılmış Avukat Girdisi (Row
18C)" nav linki eklendi), `data/case_lawyer_input.schema.json` (yeni
— wrapper şeması), `services/drafting_request.py` (yeni — Row 18C
servis katmanı), `templates/drafting_request.html`, `templates/
drafting_request_result.html` (yeni), `run_drafting_request.py` (yeni
— salt-okunur varsayılan CLI köprüsü), `tests/
test_drafting_request_service_isolated.py`, `tests/
test_drafting_request_templates_isolated.py`, `tests/
test_drafting_request_routes.py`, `tests/
test_run_drafting_request_isolated.py` (yeni).

**18c final güvenlik/mimari durumu** (bir hedefli route-safety
remediation turu, bir ExceptionGroup body-limit remediation turu, bir
BaseException safety-order düzeltme turu ve bağımsız bir salt-okunur
LOCK-hazırlık incelemesiyle ulaşıldı — kod tekrar okunarak doğrulandı,
varsayılmadı):

- **Mimari sınır (Option A-prime, kullanıcı kararı)** — Row 18C
  route'ları YALNIZ `ui.services.drafting_request`'i çağırır; Drafting
  Engine'i (`build_drafting_engine_output`), `write_pending`'i, bir
  agent'ı veya bir network/LLM çağrısını HİÇBİR ZAMAN TETİKLEMEZ.
  Gerçek üretim yalnız ayrı, elle çalıştırılan `ui/run_drafting_request.py`
  CLI köprüsünün (`--generate-pending` bayrağı ARKASINDA) işidir;
  `main.py` bu modülü ASLA import ETMEZ.
- **Sabit case-scoped kayıt yolu** — `data/cases/<case_id>/drafting/
  inputs/lawyer_input.json`; kullanıcı-kontrollü path YOK.
- **Yerel `$ref` ile şema bütünlüğü** — `case_lawyer_input.schema.json`,
  `lawyer_input` alanı için YEREL, önceden diskten yüklenmiş bir
  `referencing.Registry` üzerinden Row 15'in LOCKED
  `case_drafting.schema.json#/$defs/lawyer_input` tanımına atıf yapar;
  hiçbir `retrieve=` callback'i TANIMLANMAZ (network'e ULAŞAMAZ),
  kayıtlı olmayan bir referans fail-closed `Unresolvable` fırlatır.
- **Issue seçim tri-state'i + canonical üyelik** — "sağlanmadı" /
  "açıkça hiçbiri" / "açıkça seçilmiş" ayrımı korunuyor; yinelenen/
  sahte/bilinmeyen issue id'leri reddediliyor, kabul edilenler
  deterministik (lexicographic) sıralanıyor. `selected_source_ids`
  editable UI'da HİÇ GÖSTERİLMİYOR, her zaman onaylı boş yapı olarak
  kaydediliyor.
- **request_input / lawyer_provided_text bağımsızlığı** — Row 15'in
  Q1 (dayanak var mı) / Q2 (avukat açıkça üretim istedi mi) ayrımı
  DEĞİŞTİRİLMEDEN kullanılıyor; boş/yalnız-boşluk değerler YETKİ
  ÜRETMİYOR.
- **Atomik yazma + tam rollback** — kaydetme öncesi TAM paylaşılan
  doğrulayıcı (pre-write), atomik `os.replace` yazımı, post-write
  yeniden doğrulama, ve başarısızlıkta TAM rollback: ilk-kayıt
  başarısızlığı yeni dosyayı/audit'i/history'yi/`.tmp`'yi tamamen
  temizliyor; üzerine-yazma başarısızlığı orijinal içeriği BAYT-BAYT
  ve izin bitleriyle GERİ YÜKLÜYOR; audit-yazma başarısızlığı da AYNI
  rollback'i tetikliyor. Geçmiş/audit dosya adları `O_CREAT|O_EXCL` +
  sayısal sonekle çakışmaya dayanıklı. Audit kayıtları yalnız
  metadata/hash taşıyor, asla hukuki serbest metin.
- **Mutasyon öncesi zorunlu kontroller** — case_id allowlist çözümü,
  loopback-only erişim, aynı-origin doğrulaması, HMAC CSRF (case_id +
  "drafting_request" + "save" + expected_current_input_hash'e bağlı),
  onay checkbox'ı ve stale-hash reddi HEPSİ herhangi bir mutasyondan
  ÖNCE uygulanıyor; loopback ara-katmanı, Row 18C'ye özgü gövde-boyutu
  ara-katmanından ÖNCE çalışıyor (Starlette middleware sırası doğrudan
  doğrulandı).
- **128 KiB gövde sınırı + ExceptionGroup/BaseExceptionGroup güvenliği**
  — hem beyan edilen `Content-Length` hem GERÇEK kümülatif bayt sayımı
  kontrol ediliyor; tam 128 KiB kabul, 128 KiB+1 red. AnyIO/Starlette'in
  hedef istisnayı bir `ExceptionGroup` içine sarmalayabilmesi
  ihtimaline karşı, saf `isinstance` tabanlı yinelemeli bir ağaç
  kontrolü (`_exception_tree_contains_body_too_large`) kullanılıyor -
  string eşleştirmesi YOK. **BaseException güvenlik sırası**: hem
  route'un hem ara-katmanın yakalama noktaları `except BaseException`
  DEĞİL `except Exception` kullanıyor, ve yardımcı fonksiyon en dış
  çağrıda dahi önce `isinstance(error, Exception)` kontrolü yapıyor -
  bu yüzden `_DraftingRequestBodyTooLarge` + iptal/`CancelledError`/
  `SystemExit`/`KeyboardInterrupt` TAŞIYAN karışık bir
  `BaseExceptionGroup` ASLA 413'e dönüştürülüp kontrol-akışı sinyali
  YUTULMUYOR (standalone script + gömülü birim testleriyle doğrudan
  doğrulandı).
- **Tarayıcıya sabit, güvenli hata mesajları** — `_error_page` 18a/18b
  ile AYNI ilkeyle çalışıyor; ham exception/traceback/mutlak path/
  gönderilen hukuki serbest metin ASLA yanıta/audit'e/dosya adına
  YANSIMIYOR.
- **Script-context güvenli şablonlar** — `drafting_request.html`
  yalnız sabit bir sunucu-sabiti `|tojson` ile JS'e gömüyor; hiçbir
  kullanıcı girdisi `<script>` içine GİRMİYOR; üç Row 18C şablonunda
  da `|safe` bypass'ı YOK (Jinja2 varsayılan autoescape korunuyor).
- **Salt-okunur varsayılan CLI köprüsü** — `python -m ui.run_drafting_request
  --case <case_id>` bayraksız TAMAMEN salt-okunur; `--generate-pending`
  olmadan üretim/agent/network TETİKLENEMEZ; `--with-agent`/
  `--allow-network`, `--generate-pending` olmadan veya `--allow-network`,
  `--with-agent` olmadan verilirse hiçbir mutasyon olmadan reddediliyor;
  üretim öncesi kaydedilmiş wrapper yeniden doğrulanıyor; `--case`
  DIŞINDA hiçbir path/dosya argümanı YOK.
- **İzole mutasyon testleri + gerçek data/src byte-bütünlüğü** — tüm
  Row 18C mutasyon/rollback/audit/CSRF/stale-hash/body-limit testleri
  `TemporaryDirectory` + sentetik case_id ile çalışıyor; gerçek
  `data/`/`src/` ağacının ve gerçek `case_0001`'in test öncesi/sonrası
  byte-düzeyinde DEĞİŞMEDİĞİ her test turunda ayrıca kanıtlandı.
  `case_0001` üzerinde GERÇEK bir Row 18C girdi kaydı HİÇ ÇALIŞTIRILMADI;
  implementasyon/test boyunca hiçbir gerçek Drafting Engine/LLM/network
  çalıştırması YAPILMADI ve hiçbir gerçek case verisi mutasyona
  uğratılMADI.
- **`pip check` PASS ve Row 18C 169/169 test sonucu** — servis
  (saf-Python) 77/77 + şablon (Jinja2) 15/15 + route (FastAPI,
  TestClient) 51/51 + CLI 26/26 — hedeflenen `vergi_ui_runtime`
  ortamında kullanıcı tarafından fiilen çalıştırıldı; Row 18A 117/117
  + Row 18B 226/226 ile birlikte **Row 18 toplamı 512/512**.
- **Bağımsız salt-okunur LOCK-hazırlık incelemesi** — ayrı bir
  incelemede git preflight (branch/HEAD/staged set/13 dosyalık kapsam),
  şema/$ref izolasyonu, storage/rollback sırası, HTTP/CSRF/loopback/
  body-limit/exception-safety davranışı ve CLI kapıları KODUN
  KENDİSİNDEN doğrudan yeniden doğrulandı (yalnız test isimlerine/
  raporlara güvenilmedi); hiçbir engelleyici bulgu RAPORLANMADI - tek
  kozmetik not aşağıda listeleniyor.

**18c KAPSAM DIŞI / bilinen backlog (bilinçli, Row 19'a bırakıldı,
DÜZELTİLMEYECEK)**:

- `DraftingRequestCsrfError` (`services/common.py`) şu an TANIMLI ama
  hiç fırlatılmıyor - kullanılmayan ölü kod, güvenlik açığı DEĞİL
  (CSRF zaten `_check_csrf_and_origin` ile ayrıca uygulanıyor); yalnız
  kozmetik bir temizlik maddesi.
- `StarletteDeprecationWarning: Using httpx with starlette.testclient
  is deprecated; install httpx2 instead.` — 18a'dan devralınan, yalnız
  test altyapısını ilgilendiren bağımlılık bakım backlog maddesi;
  `httpx2` bu fazda KURULMADI/ikame EDİLMEDİ.
- Kimlik doğrulama, çoklu kullanıcı yetkilendirme, production/dış
  deployment ve çapraz-süreç eşzamanlılık/atomik CAS koruması (18b'de
  de not edilen TOCTOU penceresiyle AYNI, zaten kabul edilmiş desen)
  — Row 18'in TAMAMI için Row 19'a bırakılmış kapsam dışı maddelerdir.
- Row 18c, 18a/18b ile AYNI şekilde yerel, loopback, tek-kullanıcılı
  bir araç sınırı içinde kalır.
- **Önemli netlik**: bu fazda bir avukat girdisinin KAYDEDİLMESİ, bir
  taslağın (draft) ÜRETİLDİĞİ anlamına GELMEZ - kaydetme ve pending
  taslak üretimi (yalnız ayrı CLI köprüsüyle, `--generate-pending` ile)
  TAMAMEN AYRI işlemlerdir.

**ROW 18 — LAWYER UI TAMAMLANDI VE LOCKED** (18a + 18b + 18c üçü de
DONE/LOCKED) — kullanıcı onayı ve bağımsız bir salt-okunur
LOCK-hazırlık incelemesiyle.

**Sonraki adım**: **ROW 19 — PRODUCTION / SECURITY** — **ACTIVE / NEXT**
— 19A tamamlandı (aşağıya bkz.); 19B/19C/19D için henüz implementasyona
BAŞLANMADI.

### Row 19A — Threat Model & Deployment Contract (DONE / LOCKED — checkpoint özeti)

**İki ayrı işlem, iki ayrı mutasyon durumu** — Row 19A'nın kendisi
(route/rol matrisi, tam mutasyon envanteri, trust boundary analizi,
reconciled tehdit kaydı ve aşağıdaki mimari kararların kontrat düzeyinde
onayı) **tamamen salt-okunur** bir inceleme olarak yürütüldü ve
repository'de **sıfır mutasyona** yol açtı. Bu checkpoint'in kendisi
(bu roadmap-lock işlemi) AYRI bir adımdır ve **yalnız `CLAUDE.md`'yi**
değiştirir — hiçbir kaynak, şema, veri, bağımlılık, canonical, pending,
audit veya migration dosyasına dokunmaz.

**Kapsam kararı (kullanıcı, "Kesinleştirilmiş kararlar" + "ROW 19A —
USER DECISION")** — Row 19, dört alt-faza bölündü: **19A** (Threat
Model & Deployment Contract — bu bölüm), **19B** (Identity / Session /
Authorization), **19C** (Mutation Integrity), **19D** (Operations &
Recovery).

**Dosya-değişiklik sınırı**:

- 19A yalnız `CLAUDE.md`'yi değiştirebilir (bu checkpoint dahil) —
  başka HİÇBİR dosyaya dokunmaz.
- 19B, 19C ve 19D'nin HER BİRİ, kendi implementasyonuna başlamadan
  ÖNCE tam bir dosya allowlist'i sunmalı ve bunun için AYRICA
  kullanıcı onayı almalıdır — genel Row 19 onayı hiçbir alt-fazın
  dosya değişikliğini ÖNCEDEN yetkilendirmez.
- Rows 1-18'in domain mantığı ve şemaları KORUNMAYA devam eder — Row
  19, hiçbir alt-fazında bunları sessizce değiştiremez/yeniden
  yorumlayamaz.
- Yeni, katmasal (additive) security/auth/coordinator/journal/
  migration/deployment/test modülleri, yalnız ilgili alt-fazın kendi
  onaylanmış allowlist'i üzerinden yetkilendirilebilir.
- QA/Orchestrator pending-generation publisher'ları YALNIZ Row 19C
  dosya kapsamı ayrıca onaylandıktan SONRA eklenebilir; var olan saf
  builder/validator fonksiyonlarını yeniden kullanmalı, onların domain
  mantığını DEĞİŞTİRMEMELİ veya KOPYALAMAMALIDIR.
- Row 10/11 şema uyumluluk yaması, AYRI, dar kapsamlı, gelecekteki bir
  review/approval/commit olarak kalır — bu şu an LOCKED olan
  `case_legal_research.schema.json`/`case_case_law.schema.json`'ı
  değiştirme İZNİ DEĞİLDİR; genel Row 19 kapsamı bu yamayı OTOMATİK
  yetkilendirmez.

**Rol modeli ve mutasyon koordinasyonu kapsamı (kullanıcı kararı)** —
Üç HİYERARŞİK-OLMAYAN yetenek profili:

- `admin`: YALNIZ kimlik/rol/atama yönetimi; admin rolü TEK BAŞINA
  case enumeration veya case-içerik erişimi VERMEZ.
- `lawyer`: yalnız KENDİSİNE ATANMIŞ case'ler için erişim ve izin
  verilen hukuki mutasyonlar.
- `analyst`: yalnız KENDİSİNE ATANMIŞ case'ler için salt-okunur
  erişim; Layer A, Layer B, Row 18C veya başka HİÇBİR production
  mutasyonu YAPAMAZ.

`MutationCoordinator` hem web hem CLI mutasyon yollarını kapsar.
**Kilitleme birimi**: case-scoped mutasyonlar, o case'in TÜM artefakt
aileleri için TEK bir `case:<case_id>` kilidini kullanır. Global
mutasyonlar, `global:rag_index`, `global:deadline_rules`,
`global:legal_provisions` gibi tipli resource key'ler kullanır. Kimlik
doğrulama: dual MFA — hem sağlayıcı (provider) politikası hem
uygulama-seviyesi `acr`/`amr` iddia kontrolü. Yedekleme: harici KMS
ile envelope-encrypted backup.

**Tam mutasyon envanteri ve sabit sayım birimi** — Sayım birimi olarak
**"production mutation family"** (bir sınırlı mutasyon giriş-noktası
rolü; pending-generation ve promotion ayrı aile olarak sayılır) sabit
tanımlandı. Mekanik olarak yeniden sayıldı ve kesinleştirildi: **29
doğrulanmış production mutation family** (28 case-scoped + 1 global —
`ingest.py`), **5 maintenance/migration family**, **34 doğrulanmış
toplam**. Row 16 (QA) ve Row 17 (Orchestrator) pending-generation
publisher'ları şu an **YOK** — belgelenmemiş operasyonel boşluklardır
(var-olup-çözülmemiş bir mutator değil); 19C kapsamında ileride
eklenirlerse gelecekteki sayı 31 production / 36 toplam olacaktır
(henüz YETKİLENDİRİLMEDİ).

**Trust boundary ve reconciled tehdit kaydı** — 21 benzersiz tehdit;
şiddet dağılımı Kritik=6, Yüksek=10, Orta=4, Düşük=1; faz dağılımı
19A=3, 19B=8, 19C=4, 19D=6; çapraz-faz: T9 (19A↔19D), **T15** (19A↔19D,
symlink/junction — Windows NTFS junction admin gerektirmez ve
`os.path.islink()` tarafından tespit edilmez; `paths.resolve_case_id`
buna karşı bir containment kontrolü taşımaz; şiddet **Yüksek**; 19A
tanımlar, 19C uygulama-seviyesi path-containment düzeltmesini + writer
entegrasyonunu sahiplenir, 19D OS ACL'lerini/servis kimliğini/izlemeyi
sahiplenir; kod-seviyesi `realpath()` kontrolü tek başına yeterli bir
TOCTOU çözümü DEĞİLDİR, OS ACL'leri zorunlu kalır), T18 (19B↔19D).

**Reverse proxy / Uvicorn kontratı** — Pinned `uvicorn==0.52.4`'ün TAM
commit'i `8988c23704fc373c9206cca53ec57dd8ad7f44a5` (PyPI provenance
sayfasıyla `Kludex/uvicorn` tag `0.52.4`'e birebir eşlendiği
doğrulandı) doğrudan incelenerek şu ikisi confirm edildi: (1)
`proxy_headers=True`/varsayılan `forwarded_allow_ips="127.0.0.1"`
davranışı, (2) `X-Forwarded-Proto` ve `X-Forwarded-For`'un
BİRBİRİNDEN BAĞIMSIZ işlendiği. Bu davranış için: `proxy_headers=True`
ve varsayılan `forwarded_allow_ips="127.0.0.1"` KORUNUR — `ui/main.py`'nin
mevcut `uvicorn.run(app, host="127.0.0.1", port=8000)` çağrısında kod
değişikliği GEREKMEZ (netlik için argümanların açıkça yazılması
önerilir). Onaylanan deployment kuralı: reverse proxy yalnız
`X-Forwarded-Proto: https` gönderir; `X-Forwarded-For`'u ASLA
göndermez/gelen değeri STRIPLER; `Host` başlığını DEĞİŞTİRMEDEN
iletir. Bu konfigürasyon altında Row 18'in mevcut loopback
middleware'inde HİÇBİR kod değişikliği gerekmez; 19D bu kontratın
enforcement/testini sahiplenir.

**Onaylanan MutationCoordinator kilitleme tasarımı** —
`mutation_resources(resource_key TEXT PRIMARY KEY, advisory_lock_id
BIGINT UNIQUE NOT NULL)` (BIGINT veritabanı SERIAL/sequence ile
atanır — `hashtext()` tabanlı çözüm 32-bit çakışma riski nedeniyle
REDDEDİLDİ) + `pg_advisory_lock(advisory_lock_id)` (session-seviyeli,
bağlantı kopmasında otomatik serbest bırakılır) + AYRI, kalıcı bir
`mutation_journal` tablosu (`prepared` / stale-`executing` /
`reconciliation_required` / `completed` / `failed`). Kilit öncesi bir
journal-gate ön-kontrolü yalnız hızlı-red optimizasyonu olarak
izinlidir — **otoriter journal-gate, idempotency, yetkilendirme ve
pre-state hash kontrolleri kilit ALINDIKTAN SONRA TEKRAR yapılmalıdır**
(kullanıcı kararı). Reconciliation AYNI kilidi alır, aksiyon-özgü
adaptör + domain'in kendi validator'ü + mevcut domain audit kanıtıyla
doğrular, journal'ı çözer, sonra gate'i temizleyip kilidi bırakır.
`expected_post_hash` nullable kalır; belirsiz durumlar operatör
incelemesi için bloklanmış kalır, gözlemlenen bir hash asla otomatik
kabul edilmez. Lease-tablosu tasarımı REDDEDİLDİ.

**Onaylanan RAG global-resource (versioned bundle) tasarımı** —
Immutable versioned bundle'lar (`index/v<...>/...`) + tek bir atomik
`current_version` manifest pointer'ı (tek `os.replace`); okuyucular
tüm işlemleri için TEK bir versiyonu yakalar; aktif bir journal
işlemi, kayıtlı provenance veya saklanan audit tarafından referans
verilen bir bundle SİLİNEMEZ — GC açık bir referans/retention
kontrolü gerektirir. Legal Research/Case Law üretim sırası: girdi
hash'leri + RAG versiyonunu kilitsiz yakala → uzun üretimi case
kilidi OLMADAN çalıştır → yazmak için yalnız `case:<case_id>` kilidini
al. **Stale-sonuç kuralı (bağlayıcı)**: kilit alındıktan sonra ilgili
TÜM canonical pre-state hash'leri ve yakalanmış RAG versiyonu yeniden
kontrol edilir; herhangi biri değiştiyse pending çıktı YAZILMAZ — ya
atılır ya da güncel state'ten yeniden üretilir.

**Row 10/11 şema yaması** AYRI, dar kapsamlı, geriye-uyumlu bir
GELECEKTEKİ onay/review/commit maddesidir — `case_legal_research.schema.json`
ve `case_case_law.schema.json` KAPALI şemalardır (`additionalProperties:
false`) ve şu an hiçbir hash-manifest alanı taşımazlar; önerilen
`rag_index_version_used` alanı başka hiçbir implementasyon adımına
SESSİZCE paketlenemez ve bu checkpoint bu iki LOCKED şemayı değiştirme
İZNİ VERMEZ — kendi başına ayrıca incelenip onaylanmalı ve ayrı bir
commit olarak uygulanmalıdır.

**Maintenance/migration family sahiplenmesi** — 5 maintenance/migration
family SIRADAN bir UI mutasyonu DEĞİLDİR; ayrıca onaylanmış bir
operasyonel workflow, uygun TİPLİ global-resource kilitleri, kendi
servis kimliği (service identity), security audit ve 19D deployment
kontrolleri GEREKTİRİR. Bunlar case-scoped lawyer/analyst mutasyon
yollarıyla AYNI coordinator-lock+journal mekanizmasını paylaşabilir,
ama kendi AYRI yetkilendirme/işletim politikasına tabidir — bir
case-scoped mutasyon onayı bir maintenance/migration işlemini OTOMATİK
yetkilendirmez.

**Onaylanan static-asset politikası** — `/static/*` pre-auth sayfalar
için anonim KALIR, ama enforcement geniş bir uzantı-tabanlı allowlist
yerine **EXACT committed path manifest** ile yapılır; 19D'nin
CI/paket doğrulaması, canonical/audit/yüklenen/üretilen/source-map/
secret/hukuki-içerik dosyalarını `/static` altına yerleştiren HERHANGİ
bir build'i FAIL ettirir.

**Kullanıcı onayı ve final durum** — Kullanıcı yukarıdaki dört ana
kararı ("ROW 19A — USER DECISION") netleştirmelerle birlikte onayladı:
(1) 19C'de eklenecek QA/Orchestrator publisher'ları var olan saf
builder/validator'ları yeniden kullanan İNCE (thin), coordinator-kontrollü
katmanlar olacak, domain mantığı kopyalanmayacak; (2) BIGINT-tablo +
session advisory lock + ayrı journal modeli, kilit-sonrası otoriter
yeniden-kontrollerle; (3) immutable versioned RAG bundle'ları, Row
10/11 şema yaması AYRI onay maddesi olarak; (4) `/static/*` anonim,
exact path manifest ile. Sayımlar kullanıcı tarafından kesin (aralık
değil) olarak teyit edildi: **29 production / 5 maintenance / 34
toplam** (gelecekteki 31/36 yalnız iki yeni publisher fiilen implement
edildikten SONRA geçerli olacaktır). **Kullanıcı açıkça "implementasyona
henüz başlanmasın" talimatı vermiştir** — 19B/19C/19D için hiçbir kod/
şema değişikliği bu checkpoint ile YETKİLENDİRİLMEZ; her alt-fazın
implementasyonu kendi ayrı dosya allowlist onayını gerektirir.

### Row 19B — Identity / Session / Authorization (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış 43
dosyalık allowlist üzerinde tamamlandı: **25 yeni dosya + 18
değiştirilmiş dosya**; allowlist dışında hiçbir dosyaya dokunulmadı.

**Kimlik doğrulama akışı** — OIDC Authorization Code + PKCE (S256)
akışı; `state`/`nonce` tek-kullanımlık (single-use) olarak aynı
veritabanı transaction'ı içinde tüketilir. Entra ID sağlayıcı modeli:
P1 (ücretli) tier için `acrs: list[str]` üzerinde katı exact-membership
MFA doğrulaması uygulanır; Free tier için MFA iddiası KOŞULSUZ
fail-closed reddedilir. Issuer/audience/tenant/nonce doğrulaması katı;
çoklu-audience (liste tipi `aud`) durumunda `azp` claim'i ZORUNLUDUR ve
tam/case-sensitive eşleşmesi gerekir. **NO-JIT**: bilinmeyen kimlik
login sırasında ASLA yeni kullanıcı oluşturmaz — kullanıcı yalnız ayrı,
açık bir admin işlemi olan `provision-user` CLI komutuyla oluşturulur.

**Veri modeli** — PostgreSQL şeması: `iam.users`, external identities,
roller, case assignments, sessions, security events; tümü
yeniden-çalıştırılabilir (re-runnable) migration'larla sürüm
kontrollüdür; advisory lock ID'leri veritabanı tarafından atanır
(Row 19A kararıyla tutarlı — `hashtext()` tabanlı çözüm kullanılmaz).

**Oturum / CSRF** — `__Host-session` cookie (Secure, HttpOnly,
SameSite=Lax, Path=/); idle timeout 30 dakika, absolute timeout 8
saat; remember-me veya refresh-token YOKTUR. CSRF token'ı oturuma
bağlı (session-bound) ve HKDF ile türetilir.

**Rol modeli ve yetkilendirme** — `admin`: kimlik/rol/atama yönetimi
yapar ama case erişimi veya case enumeration ALMAZ (koşulsuz veto —
ayrıca lawyer/analyst olarak atanmış olsa bile bu listeleme
fonksiyonunda sıfır case görür). `analyst`: yalnız kendisine atanmış
case'lerde salt-okunur erişim. `lawyer`: yalnız kendisine atanmış
case'lerde okuma + izin verilen mutasyonlar. `GET /` yalnız aktif,
kullanıcıya atanmış ve dosya sisteminde hâlâ çözülebilir
(filesystem-resolvable) case'leri listeler; iptal edilmiş (revoked),
başka kullanıcıya ait veya stale (artık dosya sisteminde
çözülemeyen) atamalar bu listede GÖRÜNMEZ. Yetkilendirme kontrolü hem
route hem servis katmanında ZORUNLU olarak uygulanır — tek katmana
güvenilmez.

**IAM admin CLI** — Bootstrap sonrası 8 admin komutunun HER BİRİ açık
`--actor-user-id` parametresi GEREKTİRİR; bu actor, mutasyondan ÖNCE
aynı `global:iam` kilidi altında ve aynı transaction içinde
var/aktif/admin olarak doğrulanır. IAM mutasyonu ile buna karşılık
gelen tipli security event kaydı AYNI transaction içinde birlikte
commit/rollback edilir (kısmi/yetim event kaydı imkânsızdır).
`bootstrap-first-admin` ve `provision-user` kendi NO-JIT/idempotency
sınırlarını korur (bootstrap yalnız ilk admin için, sonraki
çalıştırmalarda idempotent şekilde no-op/hata; `provision-user` var
olan bir external identity'yi sessizce ikinci kez oluşturmaz).

**Hata / gözlemlenebilirlik** — Tarayıcıya dönen hata mesajları
redaksiyonludur (iç detay sızdırmaz); security event'ler kapalı
(closed) bir `reason_code` sözlüğü ile CHECK-constrained tutulur.

**Bağımlılıklar** — Authlib 1.8.0, joserfc 1.7.5, psycopg 3.3.5,
cryptography 50.0.1 pinned; `pip check` PASS.

**Doğrulama** — Gerçek, disposable bir PostgreSQL 16.15 örneğine karşı
migration/lock/event akışları ve IAM CLI FK/rollback davranışı
(actor bulunamadı / disabled / admin-değil senaryoları dahil)
doğrulandı. Final test özeti: Row 18'in kilitli 512 testi değişmeden
PASS; Row 19B'nin genişletilmiş 337 doğrulaması PASS; **toplam
849/849 PASS**.

**Bağımsız inceleme** — Bağımsız, salt-okunur bir LOCK-hazırlık
incelemesi yapıldı; final verdict: **ROW 19B LOCK-READY**.

**19B KAPSAM DIŞI / bilinen backlog (bilinçli, 19C/19D'ye veya
production konfigürasyonuna bırakıldı)**:

- `StarletteDeprecationWarning: Using httpx with starlette.testclient
  is deprecated; install httpx2 instead.` — yalnız test altyapısını
  ilgilendiren, engelleyici olmayan bağımlılık bakım maddesi.
- Gerçek harici OIDC tenant/sağlayıcı bağlantı testi production
  konfigürasyonuna bırakıldı — izole testler gerçek dış OIDC
  sağlayıcısına bağlanmaz.
- `origin_mismatch` reason-code ayrımı şu an kullanılmamaktadır
  (kozmetik).
- `ui/services/security.py` dosyasının eski "no session/cookie" üst
  yorumu güncel değildir (kozmetik dokümantasyon temizliği).
- **Row 19C — Mutation Integrity** (sıradaki alt-faz): coordinator/
  idempotency/journal ve case/global kilitlemenin TÜM production
  mutator'larına genişletilmesi.
- **Row 19D — Operations & Recovery**: deployment, TLS/reverse proxy,
  secret/KMS yönetimi, backup/restore, OS ACL'leri ve operasyonel
  sertleştirme.

### Row 19C-1 — Coordinator Core & Path Safety (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış 15
dosyalık allowlist üzerinde tamamlandı: **10 yeni dosya + 5
değiştirilmiş dosya**; allowlist dışında hiçbir dosyaya dokunulmadı.

- Yeni (10): `db/migrations/0003_mutation_journal.sql`,
  `src/mutation_guard.py`, `ui/services/mutation_coordinator.py`,
  `ui/services/mutation_registry.py`,
  `ui/tests/test_mutation_guard_isolated.py`,
  `ui/tests/test_mutation_coordinator_isolated.py`,
  `ui/tests/test_reconciliation_isolated.py`,
  `ui/tests/test_mutation_journal_postgres.py`,
  `ui/tests/test_path_containment_isolated.py`,
  `ui/tests/test_path_containment_windows.py`.
- Değiştirilmiş (5): `ui/services/db.py`, `ui/services/mutation_lock.py`,
  `ui/services/paths.py`, `ui/tests/test_iam_migrations_isolated.py`,
  `ui/tests/test_mutation_lock_isolated.py`.

**Kilitleme birimi** — Row 19A'da onaylanan tasarım aynen uygulandı:
`mutation.mutation_resources` (BIGINT `advisory_lock_id`, veritabanı
tarafından atanır) TEK resource-key→advisory-lock-id registry'sidir; bu
migration İKİNCİ bir registry OLUŞTURMAZ. Kilitler
`pg_advisory_lock(advisory_lock_id)` ile session-seviyelidir (bağlantı
kopmasında otomatik serbest bırakılır).

**Journal modeli** — Ayrı, kalıcı `mutation.mutation_journal` tablosu:
`prepared → executing → {completed | reconciliation_required | failed}`
state makinesi. `idempotency_key` KOŞULSUZ ve tablonun TÜM geçmişi
boyunca UNIQUE'tir (`failed` dahil) — bir istemci başarısız bir
denemeyi yeniden denemek isterse yeni bir `MutationIntent`'ten
(ör. taze `pre_hash`/`pre_revision`) türetilmiş YENİ bir
`idempotency_key` üretmelidir; `run_mutation()` var olan bir
`idempotency_key` için asla ikinci bir satır oluşturmaz. Authz ve
precondition kontrolleri `prepared` satırı oluşturulmadan ÖNCE
tamamlanır. Writer başladıktan (`executing`) SONRA fırlatılan HER
exception, satırı `completed`/`failed` yerine
`reconciliation_required`'a taşır — hiçbir yazma-sonrası hata satırı
sessizce terminal bir state'e düşürmez.

**Tek, kilit-altı reconciliation akışı** —
`reconcile_and_apply_journal_entry(conn, journal_id, registry)` TEK
kamuya açık giriş noktasıdır: kilit öncesi yalnız `resource_key`
okunur (hangi kilidin alınacağına karar vermek için) → ilgili kilit
alınır → satırın TAMAMI kilit ALTINDA otoriter biçimde yeniden okunur
→ karar bu otoriter okumaya göre verilir → guarded UPDATE
(`rowcount == 1` kontrolüyle) AYNI kilit altında uygulanır → kilit
`finally` içinde her koşulda bırakılır. Karar hiçbir zaman kilit
öncesi okumaya veya varsayıma dayanmaz.

**`prepared` kurtarma semantiği (bu turun asıl düzeltmesi)** — Bir
`prepared` satırı (writer HİÇ çağrılmamış) yalnız pre-state'in
DEĞİŞMEDİĞİ kanıtlandığında (`pre_state_confirmed_unchanged=True AND
post_state_verified=False`) `failed` + sabit
`reconciled_failed_prepared_never_executed` resolution_code'una
çözülür — bu TEK durumda `executing_at` NULL kalır (gerçekleşmemiş bir
yürütme için ASLA sahte bir zaman damgası üretilmez). Kanıt yetersiz,
çelişkili veya yalnızca post-state'i doğrularsa (writer'ın hiç
çağrılmadığını KANITLAMAZ), `_decide_outcome()` yeni
`PreparedJournalUnresolvedError`'ı fırlatır: **sıfır UPDATE** issue
edilir, satır (`state`/`executing_at`/`resolved_at`/`resolution_code`)
TAMAMEN dokunulmamış kalır, kaynak hâlâ gated'dir, kilit yine de
normal şekilde bırakılır — operasyon daha güçlü kanıtla daha sonra
tekrar denenebilir. DB CHECK constraint'leri
(`mutation_journal_executing_at_matches_state`,
`mutation_journal_prepared_never_executed_code_is_exclusive`) bu iki
durumu (NULL/NOT NULL `executing_at`) veritabanı seviyesinde de
zorunlu kılar; SQL NULL three-valued-logic'in bu CHECK'lerde fail-open
bir boşluk YARATMADIĞI bağımsız incelemede doğrulandı.

**Path containment (T15 düzeltmesi)** — `ui/services/paths.py`'nin
case-yolu çözümleme choke point'i artık symlink/junction escape'e
karşı `realpath()`/containment kontrolü uygular
(`ui/tests/test_path_containment_isolated.py` POSIX symlink ile,
`ui/tests/test_path_containment_windows.py` Windows NTFS junction ile
kanıtlar). Bu kod-seviyesi kontrol TEK BAŞINA yeterli bir TOCTOU
çözümü değildir — Row 19A kararı uyarınca OS ACL'leri (Row 19D
kapsamı) zorunlu kalır.

**Production writer durumu** — Bu turda coordinator'a HİÇBİR gerçek
production writer BAĞLANMADI; Row 19C-1 tamamen altyapı katmanıdır
(kilit + journal + reconciliation + path-safety primitive'leri).

**Test kanıtı (yalnız fiilen çalıştırılmış sonuçlar)** — Bu checkpoint
öncesi, gerçek/disposable bir PostgreSQL 16 örneğine karşı (migration
0001+0002+0003 uygulanmış, sonra iz bırakmadan DROP edilmiş) 8 test
modülünün TAMAMI yeniden çalıştırıldı:
`test_mutation_guard_isolated` 22/22,
`test_iam_migrations_isolated` 38/38,
`test_mutation_lock_isolated` 26/26,
`test_mutation_coordinator_isolated` 77/77,
`test_reconciliation_isolated` 71/71,
`test_mutation_journal_postgres` 49/49,
`test_path_containment_isolated` 20/20 — **toplam 303/303 PASS, 0
FAIL**, hepsi exit code 0. `test_path_containment_windows` bu Linux
sandbox'ında kendi tasarımı gereği SKIP olur (`sys.platform='linux'`)
— NTFS junction kontrolünün otoriter kanıtı yalnız gerçek Windows
hedef ortamında (`test_path_containment_isolated.py`'nin POSIX
eşdeğeri bu ortamda 20/20 PASS ile geçti). Bu sandbox'ta `psycopg`
import edilemediği için tüm gerçek-DB testleri `psql`-subprocess
shim yedek backend'i üzerinden çalıştı (üretim sürücüsü `psycopg`,
Windows hedef ortamında kullanılmalıdır — bkz. ilgili test
dosyalarının kendi başlık yorumları).

**Bağımsız inceleme** — Bağımsız, salt-okunur bir LOCK-hazırlık
incelemesi yapıldı; final verdict: **ROW 19C-1 LOCK-READY**. İnceleme
0 BLOCKER/HIGH, 3 MEDIUM, 2 LOW, 1 NON-BLOCKING bulgu tespit etti —
hiçbiri LOCK'u engellemedi, ama hepsi aşağıda Row 19C-2'nin açılış
kapısına taşındı (bilinçli olarak Row 19C-1'in kendisine değil).

**ROW 19C-2 MANDATORY OPENING GATE (19C-1'in blocker'ı veya tamamlanmış
işi DEĞİL — 19C-2 implementasyonuna başlamadan ÖNCE kapatılması
gereken listedir)**:

1. `mutation_coordinator.py`'nin writer'dan gelen bare
   `BaseException` ve `_mark_completed()` UPDATE'inin kendisinin
   başarısız olması yollarının kilit-temizliği için GERÇEK PostgreSQL'e
   karşı test edilmesi (şu an yalnız fake-conn ile kanıtlanmış).
2. `state='prepared' + resolution_code='reconciled_failed_prepared_never_executed'
   + executing_at IS NULL` kombinasyonunun GERÇEK veritabanına karşı
   açık bir negative-constraint testinin eklenmesi (şu an yalnız
   analitik olarak kanıtlanmış, gerçek DB'de test edilmemiş).
3. `mutation_coordinator.py:60` civarındaki, kaldırılmış
   `ui.services.mutation_registry.reconcile_journal_entry()`
   fonksiyonunu hâlâ adlandıran eski yorumun güncellenmesi.
4. `mutation_lock.py`'nin `release_lock_session()` dönüş değeri
   `False` olduğunda bunun görünür/fail-closed hale getirilmesi —
   dokümante edilmiş kontrat şu an hiçbir çağıran tarafından fiilen
   onurlandırılmıyor.
5. Coordinator'ın kendi `_mark_executing`/`_mark_completed`/
   `_mark_reconciliation_required` UPDATE'lerine (reconciliation'ın
   guarded UPDATE'i gibi) `rowcount == 1` doğrulaması eklenmesi.
6. İlk gerçek production writer coordinator'a bağlanmadan ÖNCE bir
   reconciliation operatör/CLI aracının eklenmesi.
7. `ui/services/paths.py`'nin `CASES_DIR`'i DOĞRUDAN kullanan ~30
   dosya + bunu import eden 8 dosya için path-containment borcunun,
   ilgili CLI/writer entegrasyonu sırasında kapatılması.

**Migration history note** — `db/migrations/0003_mutation_journal.sql`
bu commit'e kadar YALNIZ disposable/tek-kullanımlık test
veritabanlarına uygulandı (hiçbir zaman kalıcı/paylaşılan bir
veritabanına) ve o test veritabanları test'lerin kendi
`DROP DATABASE`/teardown adımlarıyla zaten kaldırıldı — bu nedenle
migration'ın önceki taslak sürümlerini kalıcı bir veritabanında
yükseltecek ayrı bir upgrade migration'ına GEREK YOKTUR. Bu commit'ten
İTİBAREN `0003` **immutable** kabul edilir; gelecekteki HERHANGİ bir
şema değişikliği (constraint, kolon, index) `0003`'ü değiştirmek
yerine YENİ, ayrı numaralı bir migration dosyasına gitmelidir
(`CREATE TABLE IF NOT EXISTS` deseni var olan bir tabloyu ASLA
yükseltmez — bu, gelecekte gerçek bir kalıcı veritabanı üzerinde
`0003` sonrası bir değişiklik gerektiğinde hatırlanması gereken genel
bir kısıttır, yalnız bu migration'a özgü değildir).

### Row 19C-2a — Layer A Approval Mutation Integration (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış 31
dosyalık allowlist üzerinde tamamlandı: **8 NEW + 23 MODIFIED**;
allowlist dışında hiçbir dosyaya dokunulmadı.

- Yeni (8): `db/migrations/0004_mutation_reconciliation_provenance.sql`,
  `ui/services/mutation_approval_facade.py`,
  `ui/services/mutation_approval_adapters.py`,
  `ui/reconciliation_operator.py`,
  `ui/tests/test_mutation_approval_facade_isolated.py`,
  `ui/tests/test_mutation_approval_integration_postgres.py`,
  `ui/tests/test_mutation_reconciliation_provenance_postgres.py`,
  `ui/tests/test_reconciliation_operator_isolated.py`.
- Değiştirilmiş (23): `ui/services/{mutation_coordinator,
  mutation_registry,approval_registry,common}.py`, `ui/main.py`,
  `src/mutation_guard.py`, `ui/tests/{test_mutation_guard_isolated,
  test_mutation_coordinator_isolated,test_mutation_journal_postgres,
  test_service_isolated,test_routes,test_reconciliation_isolated,
  test_path_containment_isolated}.py` ve 10 `src/*_approval.py`.

**İlk gerçek production writer bağlantısı** — Row 19C-1 tamamen altyapı
katmanıydı ve coordinator'a HİÇBİR gerçek writer bağlanmamıştı. Bu
alt-fazda on Layer A approval ailesinin (`deadline, issue_spotting,
legal_research, case_law, evidence, arguments, risk_strategy, drafting,
qa, case_view`) GERÇEK production writer'ları
`ui.services.mutation_approval_facade.approve_case_scoped_mutation()`
üzerinden mutation coordinator/journal altyapısına bağlandı;
`approval_registry.case_scoped_approve()` artık kendi mutasyon
mantığını yürütmez, tümünü bu facade'e devreder. Diğer production
mutator'lar (Layer B review, Row 18C drafting-request, CLI giriş
noktaları) BİLİNÇLİ olarak bağlanmadan bırakıldı.

**Dual authorization** — Dış (outer) `authorize_case_access()`
kontrolü, HERHANGİ bir journal/lock connection'ı açılmadan, session
advisory lock istenmeden, herhangi bir artefakt hash'i okunmadan ve
dolayısıyla herhangi bir journal gate/idempotency SQL'i çalışmadan
ÖNCE yapılır; yetkisiz bir çağıran bu dördünün SIFIRINA neden olur.
İkinci (iç, otoriter) authz kontrolü ve composite pre-state
doğrulaması case lock ALTINDA uygulanır — dış kontrol fail-fast/
sızıntı-önleme filtresidir, otoriter kararın YERİNE GEÇMEZ.
Existence-blindness her iki kontrolde de korunur (ikisi de aynı
`CaseAccessDeniedError`'a düşer); gated ve ungated bir case'in reddi
dışarıdan ayırt edilemez.

**Composite pre-state ve yarış tespiti** — `pre_hash`, pending SHA-256
+ canonical var/yok + canonical SHA-256 üzerinden hesaplanan
deterministik bir composite digest'tir (`pre_revision` ise isteğin
kendi beyan ettiği `expected_hash` olarak kalır). Snapshot kilit
öncesi hesaplanıp kilit altında dosya sisteminden YENİDEN hesaplanır;
composite digest değiştiyse `PreconditionRaceDetectedError` (mevcut
`StaleViewError`'ın bir ALT SINIFI, böylece var olan her
`except StaleViewError` bloğu değişmeden çalışmaya devam eder), pending
SHA-256 `pre_revision` ile uyuşmuyorsa düz `StaleViewError` fırlatılır.
Her iki durumda da SIFIR `prepared` journal satırı yazılır ve writer
HİÇ çağrılmaz. Yalnız-canonical değişiklikler de yakalanır (yalnız
pending'e bakan bir kontrol bunları KAÇIRIRDI).

**Korunan Row 19C-1 sözleşmeleri** — Case-scoped session advisory lock
(`case:<case_id>`, aile başına değil case başına tek kilit), KOŞULSUZ
idempotency identity (`pre_hash` kimliğe GİRMEZ, `pre_revision` girer),
journal state machine (`prepared → executing → {completed |
reconciliation_required | failed}`) ve fail-closed reconciliation
sözleşmeleri (writer istisnası ASLA `failed` üretmez; `prepared`-origin
belirsizliği hiçbir satırı uydurulmuş zaman damgasıyla çözmez) AYNEN
korunur.

**Eklenen katmanlar** — `0004_mutation_reconciliation_provenance.sql`
(yalnız additive, idempotent, yeniden çalıştırılabilir; `0003`
DEĞİŞTİRİLMEDİ; iki NULLable provenance kolonu + kapalı actor-type
seti, non-blank ≤255 actor-ref, both-or-neither ve
provenance⇒resolved CHECK'leri), `ui/reconciliation_operator.py`
(dry-run varsayılan, `--apply --actor-ref` ile gerçek çözüm),
approval facade + 10 aile için reconciliation adapter'ları ve gerçek
PostgreSQL entegrasyon testi.

**Journal/audit bağları — beş eşitlik, fail-closed** — Completed
replay doğrulaması ve reconciliation, aşağıdakilerin TAMAMINI
doğrular; eksik, boş, malformed veya uyuşmayan HERHANGİ bir değer
otomatik başarı/completed SAYILMAZ:

- `journal.idempotency_key == audit.mutation_idempotency_key`
- `journal.resource_key == audit.mutation_resource_key ==
  case:<case_id>` (eşitlik + `case:` biçim kontrolü)
- `journal.observed_post_hash == güncel canonical SHA-256`
- `audit.canonical_sha256 == güncel canonical SHA-256`
- `audit.pending_sha256 == journal/request pre_revision` (idempotency
  hash'inin bunu transitif taşımasına GÜVENİLMEZ, doğrudan kontrol
  edilir)

`mutation_idempotency_key` ve `mutation_resource_key`, on approval
modülünün TAMAMINDA keyword-only ve geriye uyumlu (`None`) alanlar
olarak audit yazıcısına aktarılır; `None` iken mevcut CLI davranışı
DEĞİŞMEZ. Reconciliation adapter'ı, çözülmemiş bir satırda
`observed_post_hash` yapısal olarak NULL olduğu için o tek bağı
gerekçesiyle birlikte hariç tutar; diğer dördünü zorunlu kılar.

**Taze canonical yeniden hash'leme** — Completed replay sırasında
güncel canonical dosya YENİDEN hash'lenir ve doğrulanan bu taze değer
`CaseScopedApprovalResult.canonical_hash` olarak döner; journal'daki
eski hash KÖR BİÇİMDE başarı ekranına taşınMAZ. Fresh (replay
olmayan) yolda ise bu alan writer'ın kendi az önce hesapladığı
değerdir. Replay doğrulama yardımcısı PRIVATE'tır ve zorunlu bir
`journal_state` parametresiyle KAPALIDIR — yalnız `completed`
durumundan çağrılabilir.

**Temizleme hataları sonucu maskelemez** — `release_lock_session()`
yalnız `False` dönmekle kalmayıp EXCEPTION da fırlatabilir; her iki
durum da CRITICAL loglanır ve hiçbiri durable/journal'a yazılmış
`completed` sonucu veya aktif birincil exception'ı MASKELEMEZ.
`conn.close()` kendi ayrı iç içe `finally`'sinde her koşulda çağrılır
ve onun hatası da yalnız loglanır. `False` dönüş davranışı mevcut
sözleşmeyle uyumlu şekilde görünür kalır.

**Production-default authz repository lifecycle** — `_resolve_authz_
repository(None)` / `_default_authz_repository()` yolu (üretimde
`ui/main.py`'nin fiilen kullandığı yol) gerçek olarak test edildi:
`(repository, close)` kontratı, gerçek `PostgresAuthzRepository`,
bağlantının tam bir kez açılıp tam bir kez kapanması, dış+iç authz
kontrollerinin gerçekten kendi SQL'lerini çalıştırması, exception
yolunda da kapatılması, enjekte edilmiş repository'de sıfır bağlantı
açılması ve fırlatan bir closer'ın sonucu değiştirmemesi.

**Production veri durumu** — Bu alt-fazda HİÇBİR production case
verisi değişmedi. Tüm mutasyon testleri geçici dizinlerde ve/veya
disposable veritabanlarında çalıştı; gerçek `data/` ağacının test
öncesi/sonrası bayt-düzeyinde DEĞİŞMEDİĞİ entegrasyon testi
tarafından ayrıca kanıtlandı.

**Test kanıtı (yalnız fiilen çalıştırılmış sonuçlar)**:

- `test_mutation_approval_facade_isolated`: **145/145 PASS**
- `test_reconciliation_isolated`: **108/108 PASS**
- `test_reconciliation_operator_isolated`: **73/73 PASS**
- `test_mutation_approval_integration_postgres`: **140/140 PASS**,
  gerçek disposable PostgreSQL üzerinde **iki kez** (yeniden
  çalıştırılabilirlik kanıtı)
- `test_mutation_reconciliation_provenance_postgres`: **24/24 PASS**
- `test_mutation_journal_postgres`: **61/61 PASS**
- `test_mutation_coordinator_isolated`: **99/99 PASS**
- `test_routes`: **60/60 PASS**
- `test_service_isolated`: **55/55 PASS**
- Windows yerel regresyon taraması: **31/31 modül exit 0**,
  `pip check` temiz.
- **Skip'ler PASS SAYILMAMIŞTIR**: DSN verilmeden yapılan son genel
  taramada PostgreSQL bölümleri SKIP olmuştur. Yukarıdaki PostgreSQL
  sonuçları AYRI, gerçek disposable PostgreSQL çalıştırmalarından
  gelmektedir. Ayrıca `test_path_containment_isolated`'ın 2 POSIX-
  symlink alt-kontrolü Windows'ta (Developer Mode/elevation olmadan)
  SKIP olur; T15'in otoriter Windows kanıtı
  `test_path_containment_windows`'un NTFS junction testidir (7/7 PASS).

**Final karar** — Bağımsız salt-okunur final inceleme 0 BLOCKER / 0
HIGH bulgusu bildirdi; tespit edilen M1/M2/M3/L1 maddeleri dar
kapsamlı bir remediation turunda kapatıldı ve yukarıdaki test
sonuçları o turdan SONRA alındı. Final verdict: **ROW 19C-2a
LOCK-READY**.

**Bu checkpoint'in kendisi** — 19A/19B/19C-1 örneğinde olduğu gibi
yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

**ROW 19C-2b'ye taşınan açık madde (Row 19C-2a blocker'ı DEĞİLDİR)** —
Row 19C-2'nin açılış kapısındaki 7 maddenin tamamı bu alt-fazda
kapatıldı; geriye yalnız `ui/services/paths.py`'nin `CASES_DIR`'ini
DOĞRUDAN kullanan dosyalar için path-containment borcunun ilgili
writer/CLI entegrasyonu sırasında kapatılması kaldı (Layer A tarafı
kapandı; Layer B/CLI tarafı 19C-2b/19C-2+ kapsamındadır).

### Row 19C-2b — Layer B Review Mutation Integration (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından, dört ayrı mekanik-
netleştirme turuyla (her turda advisor Fable 5'e danışılarak) kesinleştirilmiş
20 dosyalık allowlist üzerinde tamamlandı: **4 YENİ + 16 DEĞİŞTİRİLMİŞ**;
allowlist dışında hiçbir dosyaya dokunulmadı (git status ile ayrıca
doğrulandı - tam 20 dosya, `data/` ağacı bütünüyle temiz).

- Yeni (4): `ui/services/review_mutation_facade.py`,
  `ui/services/review_mutation_adapters.py`,
  `ui/tests/test_review_mutation_facade_isolated.py`,
  `ui/tests/test_review_mutation_integration_postgres.py`.
- Değiştirilmiş (16): `src/mutation_guard.py`, `src/evidence_review.py`,
  `src/argument_review.py`, `src/risk_strategy_review.py`,
  `src/drafting_review.py`, `src/qa_review.py`, `ui/services/common.py`,
  `ui/services/review_registry.py`, `ui/services/mutation_registry.py`,
  `ui/main.py`, `ui/reconciliation_operator.py`, `ui/tests/
  test_review_service_isolated.py`, `ui/tests/test_review_routes.py`,
  `ui/tests/test_mutation_guard_isolated.py`, `ui/tests/
  test_reconciliation_isolated.py`, `ui/tests/
  test_reconciliation_operator_isolated.py`.

**İkinci gerçek production writer ailesi bağlantısı** — Row 19C-2a
mutation coordinator/journal altyapısını Layer A'nın 10 case-scoped
approval ailesine bağlamıştı. Bu alt-faz AYNI altyapıyı (Row 19C-1'in
kilit/journal/reconciliation çekirdeği, HİÇ DEĞİŞTİRİLMEDEN) Layer B'nin
12 review_kind kayıt-bazlı inceleme ailesinin (`evidence.candidate/
suggestion`, `argument.claim/counterargument/rebuttal/suggestion`,
`risk_strategy.risk/strategy/suggestion`, `drafting.section/suggestion`,
`qa.suggestion`) TAMAMINA bağlar. `ui.services.review_registry.
apply_transition()` artık kendi authz/hash-tazelik/writer-çağırma
mantığını YÜRÜTMEZ - TÜMÜNÜ yeni `ui.services.review_mutation_facade.
apply_review_mutation()`'a devreder (Row 19C-2a Step 7'nin
`approval_registry.case_scoped_approve()` için yaptığı AYNI delegasyonun
Layer B karşılığı). Diğer production mutator'lar (CLI-only giriş
noktaları, Row 18C drafting-request writer) BİLİNÇLİ olarak
bağlanmadan bırakıldı.

**Import topolojisi (döngüsüz, kasıtlı)** — `review_registry.py` yeni
facade'i import eder; facade `review_registry`'yi ASLA import ETMEZ
(tüm review_kind-özgü metadata - modül nesnesi, `record_type`,
`call_shape`, `state_field`, gerçek domain exception sınıfı, audit-dizini
getter'ı, sabit `REVIEWER_REF` - `ReviewFamilyBinding` adlı TEK bir
paket olarak `review_registry.apply_transition()` tarafından önceden
çözülüp facade'e argüman olarak geçirilir). `review_mutation_adapters.py`
İSE `review_registry`'yi DOĞRUDAN import eder (güvenli, tek yönlü kenar -
`review_registry` hiçbir zaman adapters'ı import etmez) - `REVIEW_KIND_
REGISTRY`'nin metadata'sını (artık `audit_dir_getter`/`domain_error_class`
alanlarıyla genişletilmiş) tekrar türetmek yerine yeniden kullanmak için.

**Composite pre-state snapshot (canonical + audit + backup)** —
Writer'ın (`<family>_review.apply_review_transition()`) ÜÇ durable etkisi
VAR: canonical dosya mutasyonu, YENİ bir `*.review_audit.json`, YENİ bir
`*.before_review_*.bak` - kaynak kodu doğrudan okunarak doğrulandı, ÜÇÜ
DE AYNI `reviews/<family>_reviews/` dizinine yazılır (Layer A'nın
DAHA SIĞ `reviews/` dizininden TAMAMEN AYRI). `ReviewPreconditionSnapshot`
canonical'ın varlık+hash'i ile bu dizindeki HER `*.review_audit.json` VE
HER `*.before_review_*.bak` girişinin sıralı `(relative_name,
content_sha256)` manifestini (sayı+digest) TEK bir composite digest'e
birleştirir - `pre_hash` olarak kaydedilir, case kilidi altında yeniden
hesaplanır. Manifest taraması her girişi `paths.verify_real_path_
contained(entry, root=audit_dir)` ile doğrular (symlink/junction kaçışı,
beklenmeyen giriş türü, yinelenen ad, kaybolan/okunamayan dosya HEPSİ
TÜM taramayı fail-closed durdurur); `*.review_audit.json`-şekilli AMA
içeriği ayrıştırılamayan bir dosya tarama-seviyesinde durdurmaz, aile-
genelinde bir "bozuk aday" olarak SAYILIR.

**Kayıt-bazlı audit admission gate (yeni journal satırından ÖNCE)** —
Composite digest eşitliği TEK BAŞINA "bu kayıt için önceden mevcut bir
audit YOK" ıspatlamaz (restore/re-review saldırısı: canonical, gerçek
bir review'dan SONRA needs_review görünümüne geri yüklenebilir).
`precondition_callback` bu yüzden case kilidi altında, family-genelinde
`*.review_audit.json` dosyalarının TAMAMINI İÇERİKTEN (asla dosya adından
ön-filtrelenerek DEĞİL) tarayıp bu TAM kayıt için content-eşleşen
(case_id+record_type+record_id) "temiz" aday sayısını VE aile-genelindeki
"bozuk" aday sayısını AYRI AYRI sayar. Faz-bağımlı eşik: **admission**
(journal satırı/writer'dan ÖNCE) `bozuk==0 VE temiz==0` gerektirir;
**post-write/replay doğrulaması** ve **reconciliation**
`bozuk==0 VE temiz==1` gerektirir. Herhangi bir aile-genelinde bozuk
aday, o ailedeki TÜM kayıtların admission'ını (ilgisiz bir kayıt DAHİL)
bloke eder - kasıtlı, kabul edilmiş bir maliyet.

**Guard-hoisting (kullanıcı kararı, uygulandı)** — 5 backend'in KENDİ
public, saf fonksiyonları (`find_record`/`find_candidate`/
`find_suggestion`, `check_parent_dependency`, `check_stale_sources`)
case kilidi ALTINDA, `precondition_callback` içinde DOĞRUDAN çağrılır -
YENİDEN YAZILMAZ/KOPYALANMAZ. Bu, sıradan bir domain reddini (kayıt zaten
incelenmiş, parent henüz terminal değil) journal satırı SIFIR bırakan bir
precondition-seviyesi red olarak tutar - `mutation_coordinator.py`'nin
"writer'dan HERHANGİ bir exception -> reconciliation_required" kuralına
YAKALANMASINI ÖNLER (aksi halde her gün yaşanan sıradan bir red, admin'e
görünen bir olaya dönüşürdü).

**`secondary_input_hash` - review_note kimliği, Layer A için byte-for-
byte korunmuş** — `src/mutation_guard.py`'nin `MutationIntent`'ine YENİ,
opsiyonel bir alan eklendi: yalnız normalize edilmiş `review_note`'un
sha256 hex digest'ini taşır (asla ham metin). `_identity_fields()`'ten
HARİÇ tutulur (yalnız `request_fingerprint`'e girer, `target_state` ile
AYNI asimetri) - aynı kimlik + farklı not -> AYNI idempotency_key, FARKLI
fingerprint -> mevcut `IdempotencyConflictError` mekanizması SIFIR
değişiklikle bunu doğru ele alır. `compute_request_fingerprint()` bu alanı
yalnız `None` DEĞİLKEN dict'e ekler (koşullu anahtar VARLIĞI, `null`
değerli bir anahtar DEĞİL) - Layer A'nın HER çağrısı (`secondary_input_
hash=None`, hiç değişmez) bu yüzden ESKİ formülle BAYT-BAYT AYNI
fingerprint üretir; git HEAD'deki eski `mutation_guard.py` ile doğrudan
karşılaştırılarak KANITLANDI (izole test).

**14 semantik binding** — Safe-replay doğrulaması (facade, tek
implementasyon) VE reconciliation (adapters, BAĞIMSIZ ikinci bir
implementasyon - Layer A'nın `mutation_approval_adapters.py`'sinin AYNI
"bir hata diğerini maskelemesin" ilkesiyle) idempotency key, resource key,
case_id, record_type, record_id, actor (gerçek kimlik -
`mutation_actor_ref`, YENİ additive audit alanı), reviewer sentinel
(`reviewer_ref=="local_lawyer_ui"`, KİMLİK DEĞİL), target_state, normalize
edilmiş not hash'i, pre/post SHA256, completed-replay observed-post SHA,
canonical İÇİNDEKİ GERÇEK hedef kaydın state'i (asla yalnız tüm-dosya
hash'ine güvenilmeden) ve audit alanlarından YENİDEN HESAPLANMIŞ request
fingerprint'i doğrular. Üç YENİ additive, keyword-only audit alanı (5
backend'in TAMAMINA, Row 19C-2a Step 5'in Layer A'ya yaptığı AYNI
desenle eklendi): `mutation_idempotency_key`, `mutation_resource_key`,
`mutation_actor_ref`.

**`JournalEntrySnapshot` genişletmesi** — `ui.services.mutation_registry.
JournalEntrySnapshot`'a İKİ yeni, sonda eklenmiş (mevcut pozisyonel
construction'ları BOZMAYAN), zaten-NOT-NULL olan 0003 kolonlarından
gelen alan eklendi: `request_fingerprint`, `actor_label` - reconciliation
adapter'ının audit içeriğinden fingerprint'i yeniden hesaplayabilmesi VE
gerçek aktör kimliğini bağlayabilmesi için. **Yeni migration GEREKMEDİ** -
her iki alan da 0003'ün zaten var olan kolonlarından okunuyor.

**HTTP eşlemesi - YENİ mesaj/kod YOK** — `ReviewPreconditionRaceDetectedError`
(yeni, `ReviewStaleViewError`'ın alt sınıfı) mevcut `except
ReviewStaleViewError` bloğu tarafından OTOMATİK yakalanır
(`REVIEW_STALE_VIEW`, HTTP 200, kod değişikliği YOK). Layer A'nın ÜÇ
mevcut 409 kodu (`MUTATION_REQUIRES_REVIEW`, `MUTATION_IDENTITY_CONFLICT`,
`MUTATION_PERMANENTLY_FAILED`) AYNEN yeniden kullanıldı - `ui/main.py`'nin
`review_confirm` route'una `case_scoped_confirm` ile BİREBİR AYNI
gruplamayla yeni except blokları eklendi.

**Test kanıtı (yalnız fiilen çalıştırılmış sonuçlar)** — Bu turda
implementasyon sırasında GERÇEK bir bug (review_registry.py'nin
`ReviewFamilyBinding` construction'ında eksik `review_kind` argümanı) VE
GERÇEK bir test-izolasyon açığı (`isolated_domain_error_fixture`'ın
placeholder canonical'ı yeni precondition-seviyesi guard-hoisting
tarafından erken reddedilip domain-hata testinin amacını boşa
çıkarıyordu) test çalıştırmaları SIRASINDA yakalanıp düzeltildi - bu
belge yalnız düzeltmeler SONRASI, gerçekten elde edilmiş sonuçları
raporlar:

- `test_mutation_guard_isolated`: **39/39 PASS** (+9 yeni `secondary_
  input_hash` kontrolü)
- `test_reconciliation_isolated`: **125/125 PASS** (+17 yeni Layer B
  reconciliation-adapter kontrolü, gerçek `ReviewMutationReconciliationAdapter`
  ile)
- `test_reconciliation_operator_isolated`: **78/78 PASS** (+5 yeni,
  gerçek `_default_registry_factory()`'nin Layer A'nın 10 + Layer B'nin
  12 = 22 aileyi BİRLEŞTİRDİĞİni doğrulayan kontrol)
- `test_review_service_isolated`: **69/69 PASS**
- `test_review_routes`: **115/115 PASS**
- `test_review_mutation_facade_isolated` (YENİ): **50/50 PASS** -
  fresh mutation, safe replay, iki ayrı idempotency-conflict senaryosu
  (state + not), composite race, admission gate (önceden-mevcut +
  bozuk audit), guard-hoisting (zaten incelenmiş + parent-dependency,
  GERÇEK `evidence_review`/`argument_review` modülleriyle), outer authz
  denial (sıfır bağlantı/kilit)
- `test_review_mutation_integration_postgres` (YENİ): **47/47 PASS**,
  gerçek disposable PostgreSQL üzerinde - aynı-case iki-bağlantı kilit
  serialization'ı (PostgreSQL'in KENDİ `pg_locks` view'ı ile sunucu-
  gözlemli kanıt), başarılı mutasyon, safe replay, fingerprint conflict,
  writer crash -> `reconciliation_required`, GERÇEK Layer B production
  adapter registry ile reconciliation + provenance doğrulaması (`
  reconciled_by_actor_type`/`reconciled_by_actor_ref`) - kullanıcının
  bağlayıcı talimatındaki ALTI zorunlu senaryonun TAMAMI
- `test_mutation_approval_integration_postgres` (Layer A, READ-ONLY,
  regresyon): **140/140 PASS**, gerçek disposable PostgreSQL üzerinde -
  `JournalEntrySnapshot` genişletmesinin Layer A'yı BOZMADIĞININ kanıtı
- `test_mutation_journal_postgres`, `test_mutation_reconciliation_
  provenance_postgres` (READ-ONLY, regresyon): **61/61** ve **24/24 PASS**
- **Tüm `ui/tests/` paketi (34 dosya) tek seferde çalıştırıldı**: gerçek
  disposable PostgreSQL'e karşı, **33/33 dosya PASS (1733/1733 tekil
  kontrol, 0 FAIL)**, sıfır regresyon
- `pip check` temiz; 20 allowlist dosyasının TAMAMI `py_compile`'dan
  GEÇTİ
- Gerçek `data/` ağacı (özellikle `case_0001`) bu turun HİÇBİR testiyle
  DEĞİŞMEDİ - hem yerel byte-snapshot kontrolleriyle hem de `git status`
  ile AYRICA doğrulandı

**Bilinçli olarak kapsam dışı bırakılan (Row 19C-2c'ye veya sonrasına
taşınan)** — CLI-only mutasyon giriş noktaları (henüz coordinator'a
bağlanmadı); Row 18C drafting-request writer'ı (`ui.services.
drafting_request.save_lawyer_input_from_form`, HİÇ dokunulmadı); `ui/
services/paths.py`'nin `CASES_DIR`'ini DOĞRUDAN kullanan dosyalar için
path-containment borcu (bu turda gerçek entegrasyon test fixture'ında
18 modülün KENDİ `CASES_DIR` kopyasını taşıdığı - ayrıca `qa_validator.py`'nin
`BASE_DIR`'i qa_discovery'den BY VALUE import edip `CASES_DIR` yerine
`BASE_DIR/"data"/"cases"` hardcode ettiği - doğrudan gözlemlendi, HENÜZ
DÜZELTİLMEDİ, backlog'da kalmaya devam ediyor).

**Bağımsız salt-okunur final inceleme** — Yukarıdaki tüm allowlist/
kapsam/tasarım/test iddiaları, ayrı, salt-okunur bir incelemede kaynak
koddan yeniden doğrulandı - rapora değil kodun kendisine bakılarak.
İnceleme preflight'ı (branch `claude-dev`, HEAD
`a0b88e561e7770f1353495c641838b81884d5cca`, boş staged set, tam 20
dosyalık allowlist + `CLAUDE.md`, dokunulmamış `stash@{0}`) doğruladı;
5 backend'in gerçek fonksiyon imzalarını facade/adapters'ın varsaydığı
çağrı şekilleriyle tek tek karşılaştırdı; ve yukarıdaki test sonuçlarını
RAPORA GÜVENMEDEN kendi başına, gerçek/disposable bir PostgreSQL 16
kümesi kurup TEKRAR ÇALIŞTIRDI - birebir aynı sonuçlarla:
`test_mutation_guard_isolated` **39/39**, `test_reconciliation_isolated`
**125/125**, `test_reconciliation_operator_isolated` **78/78**,
`test_review_service_isolated` **69/69**, `test_review_routes`
**115/115**, `test_review_mutation_facade_isolated` **50/50**,
`test_review_mutation_integration_postgres` (gerçek PostgreSQL)
**47/47** (0 skip), Layer A gerçek PostgreSQL regresyonları
`test_mutation_approval_integration_postgres` **140/140**,
`test_mutation_journal_postgres` **61/61**,
`test_mutation_reconciliation_provenance_postgres` **24/24**;
`py_compile` ve `pip check` temiz. Disposable küme inceleme sonunda
kaldırıldı; gerçek `data/` ağacının test öncesi/sonrası bayt-düzeyinde
DEĞİŞMEDİĞİ `git status` ile ayrıca doğrulandı.

İnceleme İKİ non-blocking, DÜŞÜK önemde gözlem raporladı (ikisi de bu
alt-fazın LOCK'unu ENGELLEMEZ, bilinen düşük önemde notlar/backlog
olarak kaydedilir):

1. Backend'in writer sınırı (`executing`) GEÇİLDİKTEN SONRA kendi iç
   guard'ının (ör. `check_parent_dependency`'nin, out-of-band bir
   tamper altında tetiklenebilecek dahili tekrar-kontrolü) fırlattığı
   HAM domain exception (`EvidenceReviewError` vb.), `mutation_
   coordinator.run_mutation()`'ın orijinal exception'ı DEĞİŞTİRMEDEN
   yeniden fırlatması nedeniyle `ui/main.py`'de `except _REVIEW_
   DOMAIN_ERRORS` ile genel bir review-domain sonucu üretir - journal
   satırı yine de doğru şekilde `reconciliation_required` olur, ama
   tarayıcı mesajı bunu yansıtmaz. Bu, Row 19C-2a'nın Layer A için
   ZATEN belgelediği/kabul ettiği AYNI, kasıtlı tasarımla TUTARLIDIR
   (`main.py`'nin `case_scoped_confirm` route'unun kendi son `except
   Exception` bloğunun yorumu: yalnız DÖRT tanımlı koşul HTTP 409
   üretebilir, beklenmeyen bir exception ASLA bu sözleşmeye yeniden
   sınıflandırılmaz) - Layer B burada YENİ bir sapma İCAT ETMEMİŞTİR,
   önceden kabul edilmiş AYNI davranışı doğru şekilde miras almıştır.
   **19C-2b blocker'ı DEĞİLDİR.**
2. `src/qa_validator.py`'nin `BASE_DIR`'i `qa_discovery`'den BY VALUE
   import edip `CASES_DIR` yerine `BASE_DIR/"data"/"cases"` hardcode
   etmesi (bu turun gerçek entegrasyon test fixture'ında keşfedildi)
   yalnız TEST-HARNESS'a özgü bir tuhaflıktır - production çalışma
   zamanı `CASES_DIR`'i hiçbir zaman yönlendirmez/redirect etmez, bu
   yüzden gerçek dağıtımda hiçbir etkisi yoktur. Backlog'da kalmaya
   devam eder (yukarıdaki "Bilinçli olarak kapsam dışı bırakılan"
   paragrafıyla AYNI madde). **19C-2b blocker'ı DEĞİLDİR.**

**Final verdict: `ROW 19C-2b LOCK-READY` — No blocking findings.**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Row 19C-2c — Drafting-Request Mutation Integration (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış
tam dosya allowlist'i üzerinde implement edildi: **4 YENİ + 9
DEĞİŞTİRİLMİŞ = 13 dosya** (git status ile doğrulandı; allowlist
dışında hiçbir dosyaya dokunulmadı).

- Yeni (4): `ui/services/drafting_request_mutation_adapters.py`,
  `ui/services/drafting_request_mutation_facade.py`,
  `ui/tests/test_drafting_request_mutation_facade_isolated.py`,
  `ui/tests/test_drafting_request_mutation_integration_postgres.py`.
- Değiştirilmiş (9): `ui/main.py`, `ui/reconciliation_operator.py`,
  `ui/services/common.py`, `ui/services/drafting_request.py`,
  `ui/tests/test_drafting_request_routes.py`,
  `ui/tests/test_drafting_request_service_isolated.py`,
  `ui/tests/test_reconciliation_isolated.py`,
  `ui/tests/test_reconciliation_operator_isolated.py`,
  `ui/tests/test_run_drafting_request_isolated.py`.

Yeni bir migration EKLENMEDİ — bu alt-faz `db/migrations/0001-0004`'ü
(Row 19C-1/19C-2a'nın kendi migration'ları) OLDUĞU GİBİ kullanır.
`src/mutation_guard.py`, `ui/services/mutation_coordinator.py`, `ui/
services/mutation_registry.py`, `ui/services/mutation_lock.py`, `ui/
services/db.py`, `ui/services/authz.py`, `ui/services/paths.py`, Layer
A'nın `mutation_approval_facade.py`/`mutation_approval_adapters.py` ve
Layer B'nin `review_mutation_facade.py`/`review_mutation_adapters.py`
bu alt-fazda DEĞİŞTİRİLMEDİ.

**Mimari** — Row 18C'nin `drafting_request.save_lawyer_input_from_
form()` yazıcısı artık YENİ bir action family
(`drafting_request.save`) üzerinden mutation coordinator/journal
altyapısına bağlıdır: `resource_key=case:<case_id>`,
`target_ref=drafting_request.lawyer_input`, `target_state=saved`;
Layer A/B ile AYNI case-scoped session lock (`case:<case_id>`)
kullanılır. Outer (pre-lock) + inner (under-lock, authoritative) authz
ve pre-lock + under-lock composite precondition korunur. Composite
pre-state ÜÇ parçadan oluşur: current input token, audit manifest,
history manifest. `drafting_policy.compute_lawyer_input_hash()` TEK
deterministik `secondary_input_hash` kaynağıdır. Aynı identity + aynı
(normalize edilmiş) içerik safe replay'e; aynı identity + FARKLI
içerik `IdempotencyConflictError`'a (fingerprint conflict) gider.
First-save ve overwrite'ın backup/reconciliation davranışları AYRI
ayrı doğrulanmıştır (overwrite audit'i `history_backup_path` taşımak
ZORUNDADIR, first-save'in `None` olmak ZORUNDADIR). `ui/
reconciliation_operator.py`'nin production reconciliation registry'si
artık **10 Layer A + 12 Layer B + 1 drafting-request = 23 action
family**'yi TEK bir birleşik registry'de taşır. Gerçek production
`data/` bu alt-fazın hiçbir turunda DEĞİŞMEDİ (her tur kendi izole
sentetik case dizinlerinde çalıştı, byte-snapshot kontrolleriyle
doğrulandı).

**Path güvenliği — üç turlu bulgu/remediation zinciri** — Bu alt-fazın
implementasyonundan SONRA, bağımsız bir ilk salt-okunur inceleme,
onaylı sözleşmenin nested audit/history/current-input-parent
symlink/NTFS-junction escape'ini reddetmeyi ZORUNLU tuttuğunu, ama
`paths.verify_real_path_contained(entry, root=audit_dir)` gibi
yalnızca "kendi kökü" ile karşılaştıran per-entry kontrollerin TEK
BAŞINA yetersiz kaldığını (audit_dir/history_dir/current-input'in
PARENT zincirinin KENDİSİ escape edebiliyorsa) bir Medium contract
violation olarak tespit etti. Birinci remediation turu, `ui/services/
drafting_request_mutation_facade.py` ve `ui/services/drafting_
request_mutation_adapters.py`'de İKİ bağımsız (birbirinden import
etmeyen) `_resolve_verified_case_dir()`/`_verify_nested_case_path()`
çifti ekleyerek CANLI (live) symlink/NTFS-junction escape'lerini
(audit/history/inputs seviyesinde) kapattı; gerçek `mklink /J`
junction'larla doğrulandı.

Hedefli bir İKİNCİ bağımsız salt-okunur re-review, bu ilk düzeltmenin
KENDİSİNDE yeni, gerçek bir HIGH severity blocker buldu: `_verify_
nested_case_path()`'in `candidate.exists()` pre-gate'i, KIRIK (hedefi
silinmiş) veya DÖNGÜSEL (ELOOP) bir symlink/junction'ı "henüz hiç
oluşturulmamış path" ile AYIRT EDEMİYORDU — `Path.exists()` link'i
TAKİP EDER ve ikisinde de `False` döner; bu, `paths.verify_real_path_
contained()`'ın (kendisi doğru şekilde fail-closed olan) HİÇ
ÇAĞRILMAMASINA yol açıyordu. Bu bulgu, disposable/salt-okunur bir
harness'te GERÇEK bir NTFS junction'ın hedefi kaldırılarak (`os.path.
lexists()==True` ama `Path.exists()==False`) ampirik olarak
KANITLANDI.

İkinci (son) remediation turu, HER İKİ bağımsız helper'da da
`candidate.exists()`'i `os.path.lexists(candidate)` ile DEĞİŞTİRDİ:
`lexists()==False` YALNIZ gerçekten hiçbir dizin girişi (regular veya
reparse-point) yokken missing-path davranışına girer; `lexists()==True`
olan HER durum (canlı, kırık veya döngüsel) KOŞULSUZ `paths.verify_
real_path_contained()`'a yönlendirilir — bu mevcut primitive KENDİSİ
DEĞİŞTİRİLMEDİ, yalnız hangi girdilerin ona ULAŞTIĞI düzeltildi.
Windows'ta hem CANLI escape hem KIRIK link testleri GERÇEK `mklink /J`
junction'larla (asla monkeypatch ile DEĞİL) doğrulandı; her ikisinde
de `lexists=True`/`exists=False` önkoşulu testte AÇIKÇA kanıtlandı.
POSIX'e özgü bir self-loop (ELOOP) alt-testi eklendi ama bu Windows
hedef ortamında `sys.platform != "win32"` ile platform-gated'dir -
Windows'ta yalnız açık bir `SKIPPED (NOT counted as pass/fail)`
mesajı basılır, HİÇBİR `check()` çağrısı yapmaz, ve bu sub-test'in
final pass/fail toplamına KATKISI SIFIRDIR (bağımsız sayımla ayrıca
doğrulandı) — Windows'ta döngüsel-link fail-closed kanıtı kırık-
junction ampirik kanıtı + her iki servis dosyasının kendi "ROW
19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION" header yorumundaki
kaynak-kod analizine dayanır.

Final hedefli re-review verdict'i: **`ROW 19C-2c LOCK-READY — No
blocking findings`**.

**Test kanıtları (yalnız fiilen çalıştırılmış sonuçlar)** — Aşağıdaki
sonuçlar bu alt-fazın implementasyonu ve iki path-containment
remediation turu boyunca FİİLEN çalıştırılan test komutlarından
alınmıştır; hiçbir skip PASS SAYILMAMIŞTIR:

- `test_drafting_request_mutation_facade_isolated` (final kod
  durumu): **63/63 PASS**
- `test_reconciliation_isolated` (final kod durumu): **148/148 PASS**;
  Windows'ta 1 POSIX-only self-loop alt-testi `SKIPPED`, PASS
  SAYILMADI
- `test_drafting_request_mutation_integration_postgres` (final kod
  durumu, gerçek disposable PostgreSQL): **53/53 PASS, 0 skipped**
- `test_drafting_request_service_isolated` (final kod durumu):
  **77/77 PASS**
- `test_drafting_request_routes` (final kod durumu): **51/51 PASS**
- `test_run_drafting_request_isolated` (CLI köprüsü, final kod
  durumu): **26/26 PASS**
- `test_mutation_approval_integration_postgres` (Layer A regresyon,
  final kod durumu, gerçek PostgreSQL): **140/140 PASS, 0 skipped**
- `test_review_mutation_integration_postgres` (Layer B regresyon,
  final kod durumu, gerçek PostgreSQL): **47/47 PASS, 0 skipped**
- `test_reconciliation_operator_isolated`: **80/80 PASS** —
  implementasyonun ERKEN bir turunda (iki path-containment remediation
  turundan ÖNCE) doğrulandı; bu iki remediation `_verify_nested_
  case_path()`'e ÖZGÜ olduğundan ve `reconciliation_operator.py`'nin
  kendi registry-merge yüzeyine DOKUNMADIĞINDAN düşük risk olarak
  değerlendirilir, ama final kod durumuna karşı YENİDEN
  ÇALIŞTIRILMADI — bu açıkça belirtilir, sessizce "yeniden doğrulandı"
  varsayılmaz.
- `test_mutation_journal_postgres` **61/61 PASS**, `test_mutation_
  reconciliation_provenance_postgres` **24/24 PASS** — AYNI şekilde
  implementasyonun erken bir turunda, gerçek PostgreSQL'e karşı
  doğrulandı; final kod durumuna karşı YENİDEN ÇALIŞTIRILMADI (Layer
  A/B regresyon paketleri final durumda AYRICA doğrulandığı için bu
  iki dosyanın kapsadığı journal/reconciliation çekirdek mekaniği
  zaten dolaylı olarak yeniden kanıtlanmıştır).
- `py_compile`, `pip check`, `git diff --check`: final kod durumunda
  TEMİZ.
- Bu alt-fazın implementasyonu ve iki remediation turu boyunca
  kullanılan HER disposable PostgreSQL kümesi (toplam üç ayrı kümede)
  testler bitince TAMAMEN durduruldu ve kaldırıldı; gerçek `data/`
  ağacı (özellikle `case_0001`) her turda byte-düzeyinde DEĞİŞMEDİ, hem
  testlerin kendi snapshot kontrolleriyle hem `git status` ile AYRICA
  doğrulandı.

**Bilinen non-blocking/backlog**:

- Layer B'nin (Row 19C-2b) bağımsız incelemesinin daha önce işaret
  ettiği, `qa_validator.py`'nin `BASE_DIR`'i `CASES_DIR` yerine
  hardcode etmesi gibi benzer nested-directory path-containment borcu,
  bu turda KAPATILMADI — Row 19C-3a'nın kendi "shared
  path-containment foundation" değerlendirmesine TAŞINIR. Row
  19C-2c'nin KENDİ açığı (broken-link fail-open) bu turda
  KAPATILMIŞTIR; bu ayrı, önceden bilinen bir maddedir.
- Test module-scope monkeypatch cleanup ile ilgili daha önce
  raporlanmış Low önemdeki not non-blocking kalmaya devam eder;
  production kod yolunu ETKİLEMEZ.
- Session-level advisory-lock için bounded acquisition/timeout (§6'da
  zaten kayıtlı, Row 19C-2a'da tespit edildi) Row 19D backlog'unda
  KALMAYA devam eder — bu alt-faz bu maddeye DOKUNMADI.

**Sayım — action-family grain (yeni bir sayım birimi, ESKİ file-grain
sayımın YERİNE GEÇMEZ)** — Row 19A'nın orijinal sayımı ("29 production
mutation family + 5 maintenance = 34 doğrulanmış toplam") file-grain
bir analizdi. Bu checkpoint AYRI bir eksende, Row 19C-2a/19C-2b'nin
kendi "production mutation family = sınırlı bir mutasyon giriş-noktası
ROLÜ (pending-generation ve promotion/review AYRI aile sayılır)"
biriminde SAYAR: bu iki grain birbirinin YERİNE GEÇMEZ ve bu
checkpoint ESKİ 34 rakamını "yanlış" ilan ETMEZ — iki farklı analiz
eksenidir, aralarındaki tam eşleme ayrı, gelecekteki bir mutabakat
turunu gerektirir (bu turda YAPILMADI).

Action-family grain'de: bu fazdan SONRA coordinator'a bağlı case-scoped
family = **23** (10 Layer A approval + 12 Layer B review + 1
drafting-request.save). Coordinator'a HENÜZ bağlanmamış kalan writer
family = **18**: 2 CLI-only Layer A approval (fact/timeline — Row
18a'dan beri `unsupported_pending_resolution`, hiç UI'a bağlanmadı),
10 pending-generation (on Layer A ailesinin KENDİ deterministik
engine/agent üretim adımı — promotion'dan AYRI, henüz hiçbiri
coordinator'a bağlanmadı), 5 maintenance/migration family (Row 19A'nın
orijinal sayımıyla AYNI), 1 global RAG family (`ingest.py`, Row 19A'nın
orijinal sayımıyla AYNI).

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b örneğinde
olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir
roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Row 19C-3a Slice 1 — Shared Path-Containment Foundation (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış 5
dosyalık allowlist üzerinde tamamlandı: **2 YENİ + 3 DEĞİŞTİRİLMİŞ**;
allowlist dışında hiçbir dosyaya dokunulmadı.

- Yeni (2): `src/path_containment.py`,
  `ui/tests/test_path_containment_module_isolated.py`.
- Değiştirilmiş (3): `ui/services/paths.py`,
  `ui/tests/test_path_containment_isolated.py`,
  `ui/tests/test_path_containment_windows.py`.

Hiçbir migration, writer, facade/adapter, `ui/main.py`,
`ui/services/authz.py`, drafting-request helper'ı veya `data/` ağacı bu
alt-fazda DEĞİŞMEDİ.

**Mimari ve güvenlik sözleşmesi** — `src/path_containment.py`,
stdlib-only, framework/domain bağımsız ve kendi module-level filesystem
kökünü (ne `CASES_DIR`, ne `BASE_DIR`) SAKLAMAYAN paylaşılan bir
primitive'tir; her çağıran kendi kökünü her çağrıda açıkça geçirir.
Dört public fonksiyon: `validate_segment`, `resolve_existing`,
`resolve_for_create`, `list_contained_dir`. `root` her zaman `Path(
root).resolve(strict=True)` ile strict çözülür ve dizin OLMAK
ZORUNDADIR; missing/broken/döngüsel (ELOOP)/dizin-olmayan/kaçan bir
root fail-closed generic `PathContainmentError` fırlatır — SESSİZCE
boş listeye ASLA çevrilmez. Yalnız root başarıyla doğrulandıktan SONRA
tekil unsafe child'lar (`list_contained_dir()`'da) sessizce atlanır;
root hatası ile child hatası ASLA birbirine karıştırılmaz.
`os.path.lexists()` missing-vs-broken/döngüsel ayrımında ZORUNLUDUR;
`Path.exists()` hiçbir yerde bir pre-gate olarak kullanılmaz (grep ile
doğrulandı — modülde tek bir `os.path.lexists()` çağrısı ve modülün
kendi kodunda sıfır `.exists()` çağrısı vardır). `ui/services/paths.py`
artık bu paylaşılan modül üzerinde İNCE bir delegasyon katmanıdır:
`CASES_DIR`/`BASE_DIR`/`DATA_DIR`/`SRC_DIR` ve her public fonksiyonun
imzası/dönüş tipi DEĞİŞMEDEN kalır; her fonksiyon shared modülün
generic `path_containment.PathContainmentError`'ını açıkça
yakalayıp (`raise ... from error`) bu modülün KENDİ
`PathContainmentError`/`UnknownCaseError` ailesine çevirir - mevcut
HİÇBİR `except UnknownCaseError:` çağrı noktası değişmeden çalışmaya
devam eder. `CASES_DIR` hiçbir yerde by-value cache'lenmez - mevcut
monkeypatch test seam'i (`paths.CASES_DIR = fake_cases_dir`) aynen
korunur. Bir güvenli internal alias/symlink/junction'ın KENDİ
mantıksal adı ve deterministic sıralama korunur (hedefinin adına ASLA
sessizce dönüştürülmez). Containment kontrolü HER ZAMAN domain-özgü
membership kontrolünden (`is_dir()`, `case.json` varlığı) ÖNCE yapılır,
ASLA ters sırada. `resolve_for_create()` hiçbir dosya/dizin
OLUŞTURMAZ - yalnız salt-okunur bir aday path hesaplar/doğrular;
mevcut bir ara dosyanın (dizin değil) altında bir create-chain
üretilmeye çalışılması reddedilir; missing tail'in HER segmenti,
doğrulanmış en derin ata ile olan `_join_verified_child()` ilişkisini
korur (tek, kontrolsüz bir `joinpath(*remaining)` çağrısı YOKTUR).

**İki remediation turu (dürüst kayıt)**:

1. İlk implementasyon raporunda `list_contained_dir()`, missing veya
   dizin-olmayan bir root'u SESSİZCE boş listeye çeviriyordu. Bu,
   onaylanan strict-root kontratına (root hatası ile "hiç child yok"
   durumunun asla karıştırılmaması) aykırı bulundu ve root-first
   fail-closed davranışla (root ÖNCE doğrulanır ve doğrulanamazsa
   RAISE eder; yalnız doğrulanmış bir root altındaki tekil child'lar
   sessizce atlanır) düzeltildi.
2. Ardından bağımsız bir inceleme, Windows drive-relative bir segment
   biçiminin (`"D:evil.txt"`, `"D:"` gibi) `Path.joinpath()`'in
   Windows'ta segment kendi drive'ını taşıdığında TÜM path'i sessizce
   yeniden-anchor edip önceki her parçayı attığı gerçeğini kullanarak,
   zaten doğrulanmış bir root'u tamamen atlayabildiğini gösteren bir
   **Critical** bulgu çıkardı (aynı sınıf, `"file.txt:stream"` NTFS
   alternate-data-stream biçimini de kapsayacak şekilde).
3. Bu açık ÜÇ bağımsız katmanla kapatıldı: (a) `":"` karakteri
   `FORBIDDEN_SEGMENT_SUBSTRINGS` denylist'ine eklenerek (hem
   drive-designator hem ADS-stream biçimini tek başına kapatır); (b)
   `validate_segment()`'in her segmenti HEM `PureWindowsPath` HEM
   `PurePosixPath` ile yapısal olarak ayrıştırıp bir drive/root/anchor
   taşıyan veya tam olarak tek, değişmemiş bir relative component
   olarak round-trip etmeyen HERHANGİ bir segmenti reddetmesiyle
   (platform-bağımsız, gelecekteki henüz enumerate edilmemiş bir
   re-anchoring riskine karşı ikinci, bağımsız bir katman); (c) her
   join'den SONRA, HERHANGİ bir filesystem sorgusundan ÖNCE, joined
   candidate'ın kendi `.parent`/`.name`'inin tam olarak onu üreten
   ata/segmentle eşleştiğini doğrulayan `_join_verified_child()` ile
   (yukarıdaki iki katman bir gelecekteki boşluk bıraksa bile bağımsız
   olarak aynı hata sınıfını yakalardı).
4. Aynı saldırının hem paylaşılan `path_containment` API'si üzerinden
   HEM DE public `ui.services.paths.resolve_case_path()` wrapper'ı
   üzerinden - segmentin create-chain'in İLK, bir mevcut segmentten
   SONRAKİ, ve genuinely-missing bir tail İÇİNDEKİ konumlarının
   HEPSİNDE, gerçek şu an çalışan sistem drive harfi dahil - kapandığı
   bağımsız bir final re-review'da doğrulandı.
5. Final bağımsız verdict: **`ROW 19C-3a SLICE 1 LOCK-READY`**.

**Test kanıtı — implementasyon turu (full sweep)** — Implementasyon
turunun kendi raporuna göre: tüm 36 `ui/tests/test_*.py` modülü, gerçek
disposable PostgreSQL 16 üzerinde (migration 0001-0004 uygulanmış),
tek seferde çalıştırıldı: **1967 passed, 0 failed, 8 skipped**. Sekiz
skip'in TAMAMI bu ortamda Developer Mode/elevation ayrıcalığı
bulunmayan POSIX-symlink alt-testleridir - PASS SAYILMAMIŞTIR.
Windows-native gerçek `mklink /J` testleri (`test_path_containment_
windows.py`) skip OLMADAN, tam olarak çalıştı. Disposable PostgreSQL
kümesi test sonunda kaldırıldı; gerçek `data/` ağacı ve `case_0001`
byte-düzeyinde DEĞİŞMEDİ.

**Test kanıtı — bağımsız final re-review (AYRI, dar kapsamlı)** — Bu
sayılar implementasyon turunun 1967 toplamının bir PARÇASI DEĞİL,
bağımsız bir re-review turunda AYRICA, dar kapsamlı olarak (yalnız
path-containment + ilgili regresyon dosyaları, PostgreSQL/full-suite
KOŞULMADAN) çalıştırılmıştır:

- `test_path_containment_module_isolated`: **58 PASS, 0 FAIL, 4 SKIP**
- `test_path_containment_isolated`: **49 PASS, 0 FAIL, 4 SKIP**
- `test_path_containment_windows`: **20 PASS, 0 FAIL** (gerçek
  `mklink /J`, sıfır skip)
- `test_authz_isolated`: **27 PASS, 0 FAIL**
- `test_routes`: **60 PASS, 0 FAIL**
- `py_compile` (5 dosya): temiz
- `pip check`: temiz

Bağımsız re-review implementasyon turunun **1967 toplam full sweep'ini
YENİDEN ÇALIŞTIRMAMIŞTIR** - yalnız yukarıdaki hedefli sonuçları
bizzat çalıştırmış ve `1922 (önceki final) + 27 (yeni module test
farkı) + 18 (yeni isolated UI test farkı) = 1967` matematiksel
tutarlılığını doğrulamıştır. Bağımsız olarak bizzat çalıştırılmamış
hiçbir test bu re-review tarafından bağımsız PASS olarak sunulmamıştır.

**Bilinen backlog — LOCK'u ENGELLEMEZ**:

- Windows reserved device adları (`CON`, `PRN`, `AUX`, `NUL`, `COM*`,
  `LPT*`) ve trailing-dot/trailing-space segmentleri (`"foo."`,
  `"foo "`) hâlâ `validate_segment()` tarafından sıradan, tek-
  component relative segment olarak KABUL EDİLMEKTEDİR. Bunlar
  doğrulanmış root DIŞINA re-anchor oluşturan bir containment kaçağı
  DEĞİLDİR (drive/root/anchor taşımazlar, tek relative component olarak
  round-trip ederler) - bu, ayrı bir Windows namespace/portability
  hardening borcudur. Herhangi bir gelecek writer, ham veya kullanıcı-
  kontrollü bir segmenti `resolve_for_create()`'e bağlamadan ÖNCE: ya
  paylaşılan `validate_segment()` bu adlar için AYRICA güçlendirilmeli,
  ya da caller'ın yalnız güvenli, deterministic, allowlisted dosya
  adları ürettiği ayrıca KANITLANMALIDIR. Bu not Slice 1 LOCK'unu
  ENGELLEMEZ, ama gelecekteki herhangi bir writer-migration açılış
  kapısında YENİDEN değerlendirilmelidir.
- Gerçek bir ikinci-drive/UNC fixture'ı bulunmadığı için ayrı, canlı
  bir cross-drive filesystem testi YOKTUR - drive-relative ve tüm
  anchored/rooted biçimler yalnız yapısal (`PureWindowsPath`/
  `PurePosixPath`) testlerle kapatılmıştır (bkz. yukarıdaki test kanıtı
  - gerçek şu an çalışan sistem drive harfi dahil edilmiştir, ama farklı
  bir GERÇEK ikinci sürücü değil).
- Layer A ve Layer B'nin nested-directory (audit/history/current-input)
  path-containment açıkları **Row 19C-3a Slice 2**'nin ACTIVE/NEXT
  kapsamındadır - bu turda KAPATILMADI.
- `src/*_approval.py`/`src/*_discovery.py` gibi modüllerdeki bağımsız
  `CASES_DIR` tanımları ve (Row 19C-2b'nin bağımsız incelemesinde
  tespit edilen `qa_validator.py`'nin `BASE_DIR`'i hardcode etmesi gibi)
  by-value import borcu henüz bu paylaşılan modüle MIGRATE EDİLMEDİ.
- `resolve_for_create()` bu alt-fazda HİÇBİR gerçek production writer'a
  BAĞLANMADI - Row 19C-3a Slice 1 tamamen shared-primitive/altyapı
  katmanıdır (`ui.services.paths` kendi mevcut, zaten-onaylı çağıranları
  dışında).

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c
örneğinde olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir
roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Row 19C-3a Slice 2 — Layer A/B Nested Path-Containment Closure (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış tam
dosya allowlist'i üzerinde tamamlandı: **13 DEĞİŞTİRİLMİŞ, 0 YENİ dosya**.

1. `ui/services/mutation_approval_adapters.py`
2. `ui/services/mutation_approval_facade.py`
3. `ui/services/review_mutation_adapters.py`
4. `ui/services/review_mutation_facade.py`
5. `ui/services/review_registry.py`
6. `ui/tests/test_mutation_approval_facade_isolated.py`
7. `ui/tests/test_mutation_approval_integration_postgres.py`
8. `ui/tests/test_reconciliation_isolated.py`
9. `ui/tests/test_review_mutation_facade_isolated.py`
10. `ui/tests/test_review_mutation_integration_postgres.py`
11. `ui/tests/test_review_routes.py`
12. `ui/tests/test_routes.py`
13. `ui/tests/test_service_isolated.py`

Üç fixture dosyası — `test_routes.py`, `test_review_routes.py`,
`test_service_isolated.py` — bu allowlist'e SONRADAN, yeni containment/
root kontratına yalnız MEKANİK fixture uyumu (ör. yeni doğrulama
zincirinin beklediği gerçek/monkeypatch'lenmiş kök yapısı) için,
kullanıcının AÇIK onayıyla eklendi; hiçbir mevcut beklenti/status/
message kontrolü GEVŞETİLMEDİ veya KALDIRILMADI.

**Layer A sonucu**:

- Her approval ailesinin kendi dinamik `CASES_DIR` anchor'ı kullanıldı —
  paylaşılan tek bir sabit kök varsayılmadı.
- Pending/canonical/`reviews/` zinciri pre-lock, under-lock ve completed
  replay sırasında AYRI AYRI yeniden doğrulanıyor.
- Argument, risk_strategy, drafting ve qa ailelerinin `history/
  carry_forward` zinciri de case kilidi ALTINDA doğrulanıyor.
- Matching audit/carry-forward girdilerinde containment ve exact-parent
  membership, HERHANGİ bir metadata/content erişiminden ÖNCE
  uygulanıyor.
- Layer A'nın kendi `run_approve()` writer imzaları DEĞİŞTİRİLMEDİ ve
  hiçbir yeni path-override parametresi EKLENMEDİ.
- Facade doğrulaması ile writer'ın kendi raw path türetmesi arasında
  kalan dar local-filesystem-actor TOCTOU penceresinin KAPANDIĞI iddia
  EDİLMEZ; Row 19A'nın T15 kararı doğrultusunda bu pencere Row 19D'nin
  OS ACL / service identity hardening borcu olarak KALMAYA devam eder.

**Layer B sonucu**:

- Registry 12 review_kind olarak KALDI.
- `qa.suggestion` review_kind'ı için CASES_DIR anchor'ı YALNIZ
  `qa_approval` modülünden okunuyor; diğer review_kind'lar kendi backend
  modüllerinin CASES_DIR'ini kullanıyor.
- Canonical/audit zinciri pre-lock, under-lock ve replay sırasında
  yeniden doğrulanıyor.
- Case kilidi ALTINDA elde edilen en güncel verified path'ler mevcut
  writer kwargs'ı ÜZERİNDEN backend'e taşınıyor.
- Facade (`review_mutation_facade.py`) ve reconciliation adapter
  (`review_mutation_adapters.py`) BAĞIMSIZ doğrulama/karar mantığını
  korudu.
- Adapter, containment hatasında `ReconciliationEvidence(post_state_
  verified=False, pre_state_confirmed_unchanged=False)` dual-false
  evidence üretir.

**Güvenli tarama kontratı**:

- Filename classification ÖNCE, saf string işlemiyle yapılır.
- Karar üzerinde etkili olan (audit VE backup dahil) classified
  girdilerde containment ve exact-parent membership,
  `is_file`/`stat`/`open`/JSON-read'den ÖNCE uygulanır.
- Metadata ve içerik YALNIZ verified/resolved Path üzerinden okunur.
- Güvenli regular backup dosyasının içeriği okunmadan yok sayılır.
- Güvenli fakat non-regular VEYA escaping/broken/looping backup girdisi
  fail-closed scan error üretir.
- Facade ile adapter'ın karar mantığı ORTAKLAŞTIRILMADI; yalnız Slice
  1'in karar içermeyen `src/path_containment.py` primitive'i (`ui.
  services.paths.verify_real_path_contained()` üzerinden) HER İKİSİ
  tarafından ayrı ayrı çağrılarak ortak kullanılıyor.

**Remediation geçmişi**:

1. Real-PostgreSQL A1/A2/B1/B2 path-rejection kanıtları eklendi.
2. İlk bağımsız inceleme şunları buldu: A2'nin tautolojik pending
   assertion'ı, Layer B'nin audit-kind dalındaki `is_file()` sıralaması,
   audit tie-break davranışını anlatan bir docstring'in koddan sapması.
3. Bunlar dar bir remediation ile kapatıldı: gerçek before/after pending
   hash karşılaştırması, containment-before-stat sıralaması, davranış
   değiştirmeyen bir docstring düzeltmesi ve equal-mtime testi.
4. Hedefli bir re-review, adapter'ın SEPARATE backup-kind dalında AYNI
   sıralama boşluğunun hâlâ durduğunu buldu.
5. Son remediation, audit ve backup akışlarını tek bir ortak sıralamaya
   birleştirerek raw `entry.is_file()` kullanımını tamamen kaldırdı.
6. Son, bağımsız, salt-okunur bir targeted re-review; production
   ordering, backup semantics, test kalitesi ve dual-false
   reconciliation sonucu için hiçbir bulgu RAPORLAMADI ve `ROW 19C-3a
   SLICE 2 LOCK-READY` verdict'ine ulaştı.

**Test kanıtı — dürüst zaman ayrımıyla**:

Son dar (backup-kind) remediation'dan ÖNCE, gerçek disposable PostgreSQL'e
karşı çalıştırılan geniş 36-dosyalık `ui/tests/` sweep'i: **2056 passed,
0 failed, 8 skipped**. **Bu sweep, final backup-kind kod durumuna karşı
YENİDEN ÇALIŞTIRILMADI** — final-tree'nin tam sweep sonucu olarak
SUNULAMAZ, yalnız o ANDAKİ kod durumunun kanıtıdır.

Final kod üzerinde AYRICA doğrulanan targeted sonuçlar:

- `test_mutation_approval_facade_isolated`: **170/170**
- `test_review_mutation_facade_isolated`: **64/64**
- `test_reconciliation_isolated`: **168/168** (1 ilgisiz açık skip, PASS
  SAYILMADI)
- `test_mutation_approval_integration_postgres`: **162/162, 0 skipped**
- `test_review_mutation_integration_postgres`: **66/66, 0 skipped**
- `test_routes`: **60/60**
- `test_review_routes`: **115/115**
- `test_service_isolated`: **55/55**
- `test_mutation_journal_postgres`: **61/61**
- `test_mutation_reconciliation_provenance_postgres`: **24/24**

Son, bağımsız backup-kind targeted re-review'un BİZZAT yeniden
çalıştırdığı ve doğruladığı sonuçlar (yukarıdaki listenin bir PARÇASI
değil, AYRI, dar kapsamlı bir doğrulama):

- `test_reconciliation_isolated`: **168/168**
- `test_review_mutation_facade_isolated`: **64/64**
- `test_review_mutation_integration_postgres`: **66/66**, gerçek
  disposable PostgreSQL 16 üzerinde (migration 0001-0004), **0 skipped**
- `py_compile` (iki remediation dosyası): temiz
- `pip check`: temiz
- `git diff --check` / `git diff --cached --check`: temiz
- gerçek `data/` ağacı: bayt-düzeyinde DEĞİŞMEDİ
- kullanılan disposable PostgreSQL kümesi VE her junction/temp dizini
  test sonunda TAMAMEN kaldırıldı

**Hiçbir skip PASS SAYILMAMIŞTIR** — ne geniş 36-dosyalık sweep'in 8
skip'i, ne `test_reconciliation_isolated`'ın kendi 1 ilgisiz skip'i.

**Scope dışı/kalan borç**:

- OS düzeyinde ATOMİK path pinning SAĞLANDIĞI iddia EDİLMEZ.
- Yerel bir actor'ın link-swap/TOCTOU riski Row 19D'nin OS ACL / service
  identity kapsamındadır.
- CLI-only writer entegrasyonu Row 19C-3b'ye KALMIŞTIR.
- Hiçbir migration/şema DEĞİŞMEDİ.
- Production `data/` DEĞİŞMEDİ.
- Slice 1'in paylaşılan primitive'i (`src/path_containment.py`) ve Row
  19C-2c'nin drafting-request'e özgü bağımsız helper'ları
  (`_resolve_verified_case_dir()`/`_verify_nested_case_path()`) bu
  turda DEĞİŞTİRİLMEDİ.

**Final verdict: `ROW 19C-3a SLICE 2 LOCK-READY — No blocking
findings.`**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/19C-3a
Slice 1 örneğinde olduğu gibi yalnız `CLAUDE.md`'yi değiştiren,
salt-okunur bir roadmap-lock işlemidir; hiçbir kaynak/migration/test/
production dosyasına dokunmaz.

### Row 19C-3b Slice 1 — Facade-Backed Legacy CLI Mutation Integration (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış tam
dosya allowlist'i üzerinde tamamlandı: **4 YENİ + 24 DEĞİŞTİRİLMİŞ = 28
dosya**, **0 migration**, **0 production-data değişikliği**.

Yeni (4):
1. `ui/cli_mutate.py`
2. `ui/services/cli_authz.py`
3. `ui/tests/test_cli_mutate_isolated.py`
4. `ui/tests/test_cli_mutate_integration_postgres.py`

Değiştirilmiş (24):
5. `src/deadline_approval.py`
6. `src/issue_spotting_approval.py`
7. `src/legal_research_approval.py`
8. `src/case_law_approval.py`
9. `src/evidence_approval.py`
10. `src/argument_approval.py`
11. `src/risk_strategy_approval.py`
12. `src/drafting_approval.py`
13. `src/qa_approval.py`
14. `src/orchestrator_approval.py`
15. `src/evidence_review.py`
16. `src/argument_review.py`
17. `src/risk_strategy_review.py`
18. `src/drafting_review.py`
19. `src/qa_review.py`
20. `ui/services/review_registry.py`
21. `ui/services/review_mutation_facade.py`
22. `ui/services/review_mutation_adapters.py`
23. `ui/tests/test_review_service_isolated.py`
24. `ui/tests/test_review_mutation_facade_isolated.py`
25. `ui/tests/test_reconciliation_isolated.py`
26. `ui/tests/test_review_mutation_integration_postgres.py`
27. `ui/tests/test_reconciliation_operator_isolated.py`
28. `ui/tests/test_drafting_request_mutation_integration_postgres.py`

`test_drafting_request_mutation_integration_postgres.py` bu allowlist'e
SONRADAN, merged reconciliation registry'nin kanal-ayrımlı **35**
routing-key sayısına yalnız MEKANİK test uyumu için, kullanıcının AÇIK
onayıyla eklendi (bkz. Remediation geçmişi, madde 2-3).

**Tamamlanan kapsam**:

- **10** Layer A approval family
- **12** logical Layer B review kind
- toplam **22** facade-backed mutation family
- bunları temsil eden **15** legacy executable module

Bu Slice'ın bütün CLI writer envanterini tamamladığı İDDİA EDİLMEZ —
kalan kapsam Row 19C-3b Slice 2'ye bırakılmıştır (bkz. §5, Scope dışı/
kalan borç).

**Universal CLI**:

- Yeni giriş noktası: `python -m ui.cli_mutate`
- `approval` ve `review` subcommand'ları
- zorunlu `--actor-user-id`
- preview/apply ayrımı
- apply için explicit expected hash
- expected hash'in apply sırasında sessizce yeniden hesaplanmaması
- force/bypass bulunmaması
- domain writer'ın doğrudan çağrılmaması
- mevcut registry/facade/coordinator/journal yolunun kullanılması
- `reviewer_ref`/`channel`/`action_family`'nin kullanıcı girdisi
  OLMAMASI

**CLI authorization**:

- `CliActorAuthzRepository`
- trusted-local-shell actor-user-id modeli
- bunun kriptografik OS identity kanıtı OLMADIĞI
- outer authz'nin mutation connection/lock/journal/case-file
  erişiminden ÖNCE olması
- inner authz'nin lock altında fresh şekilde yeniden çalışması
- authz ve mutation bağlantılarının AYRI olması
- nonexistent/disabled/unassigned/wrong-capability aktörlerin
  fail-closed ve existence-blind reddedilmesi
- authz connection cleanup

Trusted-local-shell sınırı Row 19D OS/service-identity hardening borcu
olarak KALIR.

**Reviewer provenance ve channel binding**:

- web reviewer_ref: `local_lawyer_ui`
- CLI reviewer_ref: `local_lawyer_cli`
- write-side kapalı iki-değerli vocabulary
- bilinmeyen değerin I/O öncesi programming error olarak reddedilmesi
- web journal action_family: `review.<kind>`
- CLI journal action_family: `review.<kind>.cli`
- kanalın PostgreSQL journal'daki immutable action_family üzerinden
  reconciliation'a bağlanması
- exact equality kullanılması
- suffix/prefix/two-value membership fallback bulunmaması
- UI↔CLI cross-channel audit tamper'ın dual-false olması
- fresh mutation ve completed replay binding-14'ün AYNI
  channel-specific action_family'yi kullanması
- eski web journal satırlarının geriye uyumlu KALMASI

Sayılar AYRI eksenlerdir, birbirinin YERİNE GEÇMEZ:

- **12** logical Layer B review kind — DEĞİŞMEDİ
- **24** channel-separated Layer B adapter routing key
- merged registry: **10** approval + **24** review routing key + **1**
  drafting_request = **35** routing key

24 routing key "24 yeni logical family" gibi SUNULAMAZ — aynı 12
logical kind'ın web/CLI kanal ayrımından doğan routing-key
çoğalmasıdır.

**Legacy bypass closure** (15 legacy executable dosyada):

- gerçek mutation branch'inin doğrudan writer ÇAĞIRMADIĞI
- fixed stderr mesajı verdiği
- `raise SystemExit(2)` ile gerçek process exit code 2 ürettiği
- traceback VERMEDİĞİ
- refusal öncesinde DB/case filesystem erişimi OLMADIĞI
- writer fonksiyon gövdelerinin DEĞİŞMEDİĞİ
- 11 self-test yolunun KORUNDUĞU
- self-test bulunmayan dört approval modülünün preview yolunun
  KORUNDUĞU
- review preview/usage davranışlarının KORUNDUĞU

Açıkça belirtilir: yerel Python kodu tarafından writer fonksiyonunun
doğrudan import edilmesini OS seviyesinde İMKÂNSIZ kılan bir sandbox
SAĞLANMAMIŞTIR; bu Slice yalnız EXECUTABLE legacy CLI bypass'larını
kapatır. Yerel kod çalıştırma ve service identity sınırı Row 19D
kapsamındadır.

**Remediation geçmişi**:

1. İlk implementasyon 27 dosyada tamamlandı.
2. Full sweep, drafting-request integration testindeki bayat 23
   routing-key beklentisini buldu.
3. Açık kullanıcı onayıyla 28. dosya eklendi ve exact beklenti 35
   olarak düzeltildi.
4. İlk bağımsız final review production davranışını doğru buldu fakat
   15 legacy executable için kalıcı subprocess regresyon testi
   bulunmadığını Medium test-evidence gap olarak raporladı.
5. İki yeni CLI test dosyasında gerçek subprocess regresyon matrisi
   eklendi.
6. Targeted re-review, Turkish Windows cp1254 ortamında child
   stderr'in unconditional UTF-8 replacement decode edilmesini High
   test-correctness blocker'ı olarak buldu.
7. Test child environment'ına explicit `PYTHONIOENCODING=utf-8`
   eklendi; raw bytes strict UTF-8 decode edildi.
8. `evidence_review`'ın `--confirm`, `--reject`, `--accept-follow-up`,
   `--dismiss` yollarının tamamı kalıcı test kapsamına alındı.
9. Son bağımsız targeted re-review encoding kusurunun gerçek
   cp1254/captured-output koşullarında kapandığını doğruladı ve
   LOCK-READY verdict'i verdi.

**Kalıcı legacy CLI test kontratı**:

- 15 benzersiz executable
- evidence_review'ın üç ek flag varyantıyla toplam **18** mutation
  subprocess senaryosu
- gerçek `subprocess.run`
- `sys.executable`
- explicit `cwd`
- bounded timeout
- `shell=True` YOK
- returncode tam 2
- fixed stderr
- traceback YOK
- stdout boş
- data byte-invariance
- real PostgreSQL journal full-row-set invariance
- 11 self-test ve dört preview yolu
- ambient cp1254 ortamından BAĞIMSIZ child UTF-8 stdio

**Test kanıtı — dürüst zaman ayrımı**:

Final-tree implementation sweep: **38/38 test modules exit 0**, **2387
passed, 0 failed, 8 counted skipped**, gerçek disposable PostgreSQL 16,
migration 0001-0004.

`test_reconciliation_isolated.py` içindeki bir Windows self-loop
alt-testi yalnız informational bir `SKIPPED (NOT counted as pass/fail)`
satırı basar; bu dosyanın kendi summary skip sayacına DAHİL DEĞİLDİR
(bu dosyanın özet satırı hiçbir "skipped" alanı taşımaz). Bu yüzden:
**counted skips: 8** (yalnız `test_path_containment_isolated` (4) +
`test_path_containment_module_isolated` (4)); **raw informational
SKIPPED satırı dahil gözlenen satır: 9**. Hiçbir skip PASS
SAYILMAMIŞTIR.

Final kod üzerinde implementasyon turunda doğrulanan targeted
sonuçlar:

- `test_cli_mutate_isolated`: **153/153**
- `test_cli_mutate_integration_postgres`: **130/130, 0 skipped**
- `test_review_mutation_integration_postgres`: **82/82, 0 skipped**
- `test_reconciliation_isolated`: **173/173**

Son bağımsız targeted re-review'ün BİZZAT yeniden çalıştırdığı
sonuçlar (yukarıdaki listeden AYRI, bağımsız bir doğrulama):

- **153/153**
- **130/130** real PostgreSQL, **0 skipped**
- **82/82** real PostgreSQL
- **173/173**
- ambient `PYTHONIOENCODING`/`PYTHONUTF8` unset, cp1254 koşulu
- redirected/captured output
- zero `UnicodeDecodeError`
- zero `UnicodeEncodeError`
- zero U+FFFD
- **18/18** refusal checks
- `py_compile` temiz
- `pip check` temiz
- `git diff` kontrolleri temiz
- `data/` bayt-düzeyinde DEĞİŞMEDİ
- disposable PostgreSQL/temp/process residue TAMAMEN temizlendi

Bağımsız re-review, **2387'lik full sweep'i YENİDEN ÇALIŞTIRMADI** —
yalnız `2353 + 17 + 17 = 2387` aritmetiğini VE yukarıdaki targeted
sayıların kendisini bağımsız olarak doğruladı.

**Scope dışı/kalan borç**:

- `drafting_request.save` bu Slice'a DAHİL DEĞİL.
- Pending-generation writer'ları DAHİL DEĞİL.
- Fact/timeline promotion writer'ları DAHİL DEĞİL.
- Maintenance/global RAG writer'ları DAHİL DEĞİL.
- Migration/şema DEĞİŞMEDİ.
- Production data DEĞİŞMEDİ.
- OS-level caller identity ve local-code execution sınırı Row 19D'ye
  KALDI.
- Advisory-lock timeout backlog'u DEĞİŞMEDİ.
- Row 19C-3a'da kabul edilen local-filesystem TOCTOU sınırı
  DEĞİŞMEDİ.

**Final verdict: `ROW 19C-3b SLICE 1 LOCK-READY — No blocking
findings.`**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/19C-3a
Slice 1/Slice 2 örneğinde olduğu gibi yalnız `CLAUDE.md`'yi
değiştiren, salt-okunur bir roadmap-lock işlemidir; hiçbir kaynak/
migration/test/production dosyasına dokunmaz.

### Row 19C-3b Slice 2 — Fact/Timeline Canonical Promotion Integration (DONE / LOCKED — checkpoint özeti)

**Kapsam (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış tam
dosya allowlist'i üzerinde tamamlandı: **4 YENİ + 8 DEĞİŞTİRİLMİŞ = 12
dosya**.

Yeni (4):
1. `ui/services/promotion_mutation_facade.py`
2. `ui/services/promotion_mutation_adapters.py`
3. `ui/tests/test_promotion_mutation_facade_isolated.py`
4. `ui/tests/test_promotion_mutation_integration_postgres.py`

Değiştirilmiş (8):
5. `src/fact_approval.py`
6. `src/timeline_approval.py`
7. `ui/cli_mutate.py`
8. `ui/reconciliation_operator.py`
9. `ui/tests/test_cli_mutate_isolated.py`
10. `ui/tests/test_cli_mutate_integration_postgres.py`
11. `ui/tests/test_reconciliation_operator_isolated.py`
12. `ui/tests/test_drafting_request_mutation_integration_postgres.py`

Aşağıdakiler bu alt-fazda DEĞİŞMEDİ: Layer A'nın exact-10
facade/adapters'ı (`mutation_approval_facade.py`/
`mutation_approval_adapters.py`), `approval_registry.py` ve web route
yüzeyi (`ui/main.py`), mutation coordinator/registry/guard
(`mutation_coordinator.py`, `mutation_registry.py`,
`src/mutation_guard.py`), paylaşılan path-containment primitive'i
(`src/path_containment.py`), authz/cli_authz (`ui/services/authz.py`,
`ui/services/cli_authz.py`), migration'lar (`db/migrations/`) ve
production `data/`.

**Slice sonucu** — Fact (Row 6) ve timeline (Row 7) canonical promotion
işlemleri, mevcut Layer A facade'i koşullu branch'lerle
GENİŞLETİLMEDEN, ayrı ve bağımsız bir promotion facade/adapters çiftine
(`promotion_mutation_facade.py`/`promotion_mutation_adapters.py`)
bağlandı. Yalnız CLI yüzeyi (`python -m ui.cli_mutate promotion ...`)
eklendi; web promotion yüzeyi AÇILMADI. Action family'ler:
`promotion.fact` / `promotion.timeline`. Registry eksenleri: `approval.*
= 10`, logical review kind = 12, review routing key = 24,
`drafting_request.* = 1`, `promotion.* = 2`, merged routing key = **37**.
Fact'in `target_ref`'i doküman-scoped (`fact.<document_id>.canonical`),
timeline'ınki case-scoped (`timeline.canonical`) kaldı. Fact'in
`--note`'u yalnız fingerprint girdisidir (`secondary_input_hash`); aynı
kimlik + farklı not mevcut `IdempotencyConflictError` mekanizmasına
düşer.

**Authz ve CLI kontratı** — Promotion preview, dış (outer) 'read'
authz'dan SONRA çalışır; apply dış (outer) 'mutate' authz + case kilidi
ALTINDA iç (inner), otoriter 'mutate' authz ile çalışır. Usage-shape
doğrulaması (fact apply için `--document` zorunluluğu, timeline için
`--document`/`--note` reddi, `--expected-hash` eşleşmesi) HERHANGİ bir
connection/filesystem/journal erişiminden ÖNCE uygulanır. Fact
document/case_id ↔ pending içerik çapraz-kontrolü pre-lock VE
kilit-altında ayrıca doğrulanır. Analyst preview yapabilir, apply
YAPAMAZ (`authorize_case_access` capability kontrolü). Legacy
`src/fact_approval.py --approve` / `src/timeline_approval.py --approve`
doğrudan yolları sabit stderr mesajı + `SystemExit(2)` ile KAPATILDI -
preview/self-test yolları KORUNDU. Promotion reviewer/provenance
değerleri (`PROMOTION_REVIEWER_REF`) kullanıcı tarafından
DEĞİŞTİRİLEMEZ - sabit modül sabiti.

**Writer-root ve path güvenliği** — Writer containment kökü ÇAĞRI ANINDA
writer modülünün KENDİ `CASES_DIR` değerinden okunur (asla
cache/default-arg); `ui.services.paths.resolve_case_path()` writer
doğrulaması için KULLANILMAZ. Facade ve adapter, kendi BAĞIMSIZ
root/nested/audit-scan mantığını taşır (yalnız karar içermeyen
`src/path_containment.py` primitive'i paylaşılır). Pre-lock, kilit-altı
VE completed-replay sırasında SIFIRDAN path doğrulaması yapılır. Writer
callback'e kilit-altı doğrulanmış Path nesneleri ve TAM `verified_paths`
paketi aktarılır: fact için `extractions_dir`/`pending_path`/
`canonical_path`/`history_dir`/`reviews_dir`; timeline için
`timeline_dir`/`pending_path`/`canonical_path`/`history_dir`/
`reviews_dir`. Verified (production) modda raw `DATA_DIR`/`case_id`/
`pending.parent` türetimi filesystem authority olarak KULLANILMAZ.
Writer'ın kendi structural parent/leaf kontrolü (literal ata-dizin adı
YERİNE) safe internal alias'ı destekler ama containment yetkisini
facade'den ALMAZ - facade'in containment zinciri tek konum otoritesi
kalır. Live escape, broken/looping link ve kilit beklerken oluşan
junction swap fail-closed reddedilir; containment-before-stat/open/write
disiplini korunur.

İki tasarım kararı ayrıca kaydedilir:

1. Fact promotion'ın verified modunda `CASES_DIR` TEK writer path
   seam'i yapılmıştır; `DATA_DIR` bu modda hiçbir path authority
   TAŞIMAZ.
2. Literal ata-dizin adları yerine structural parent/leaf doğrulaması
   kullanılmıştır; bağımsız inceleme bunun containment'ı ZAYIFLATMADAN
   safe internal alias'ı KORUDUĞUNU doğruladı.

**Serialization, audit ve reconciliation** — Her writer'da
`_canonical_json_bytes()` hem gerçek canonical writer hem
`compute_expected_canonical_sha256()` için TEK bayt kaynağıdır - fact
deterministik `build_canonical()` dönüşümü, timeline kimlik dönüşümü;
her iki expected-hash yardımcısı salt-okunur ve deterministiktir.
Timeline success audit'i `canonical_sha256` + mutation-binding
alanlarını taşır; rollback audit'i ASLA success evidence sayılmaz. Fact
audit'i zaman damgalı ad + `O_CREAT|O_EXCL` + sayısal sonek ile legacy
sabit-ad overwrite riskini kapattı; eşleşme HER ZAMAN içerik
binding'inden yapılır, addan ASLA. Reconciliation: post-state yalnız
deterministik canonical hash + TAM BİR bound success audit
birlikteyken verified sayılır; canonical doğru ama audit yok/bozuk/
duplicate ise auto-completed YOKTUR. Pre-state yalnız composite
pre-hash eşleşmesiyle doğrulanır. Dual-false evidence sıfır UPDATE
bırakır. İdempotent overwrite köşesi `completed` DEĞİL `failed` olarak
çözülür. Writer exception'ı `reconciliation_required`'a düşer; completed
replay writer'ı TEKRAR ÇAĞIRMAZ.

**Remediation ve doğrulama geçmişi**:

1. İlk corrected scope analizinde mevcut Layer A facade'ini genişletme
   önerisi REDDEDİLDİ; ayrı promotion facade/adapters seçildi.
2. Timeline reconciliation için `observed_post_hash`'ın TEK BAŞINA
   yetersiz olduğu belirlendi; audit `canonical_sha256` + deterministik
   expected-hash çözümü getirildi.
3. Fact'in sabit audit adının overwrite riski timestamp/`O_EXCL`
   modeliyle kapatıldı.
4. Timeline'ın yalnız verified pending üzerinden kardeş yolları yeniden
   türetmesinin YETERSİZ olduğu bulundu; TAM `verified_paths` handoff
   eklendi.
5. Implementasyon sırasında adapter'ın post kanıtı kurulamayınca
   pre-state kanıtına DÜŞEMEYEN bir sıralama hatası test tarafından
   yakalanıp düzeltildi.
6. F3 fixture'ının aslında idempotent-overwrite senaryosu olduğu
   görüldü; gerçek first-save audit-crash dual-false senaryosu
   AYRILDI ve idempotent-overwrite köşesi ayrıca dürüstçe sabitlendi.
7. İlk final raporda eksik kalan gerçek PostgreSQL `_mark_completed`
   failure kanıtı, P11 ile hem fact hem timeline için TAMAMLANDI.
8. Son bağımsız (Sonnet) inceleme hiçbir Critical/High/Medium/Low
   bulgu bulmadı.

**P11 gerçek PostgreSQL kanıtı** — Disposable DB'ye özgü bir trigger
yalnız EXACT resource_key için `completed` UPDATE'ini reddetti;
production coordinator/facade/adapter MONKEYPATCH EDİLMEDİ; writer'ın
canonical/audit/backup etkileri TAMAMLANDI; journal `executing` ve
`observed_post_hash` NULL kaldı; trigger kaldırıldıktan SONRA gerçek
merged 37-key registry ile reconciliation çalıştırıldı; hem fact hem
timeline `completed` + `reconciled_completed_post_state_verified`
sonucuna ulaştı; `observed_post_hash` ve reconciler provenance
(`cli_service`) doğrulandı; writer İKİNCİ KEZ ÇAĞRILMADI; trigger/
function ve PostgreSQL residue TAMAMEN temizlendi.

**Test kanıtı — zaman ayrımı korunarak**:

Implementation final full sweep: **40/40** `ui/tests/test_*.py` modülü
exit 0, **2570 passed, 0 failed, 8 counted skipped**, 1 informational
`SKIPPED` satırı sayaç DIŞI - fresh disposable PostgreSQL 16.15,
migration 0001-0004, hiçbir skip PASS SAYILMADI. **Bu full sweep
bağımsız review sırasında YENİDEN ÇALIŞTIRILMADI**.

Bağımsız (Sonnet) review'ın BİZZAT çalıştırdığı sonuçlar (full sweep'ten
AYRI, kendi ölçümü):

- `test_promotion_mutation_facade_isolated`: **101/101**
- `test_cli_mutate_isolated`: **173/173**
- `test_reconciliation_operator_isolated`: **87/87**
- `test_promotion_mutation_integration_postgres`: **50/50, 0 skipped**
- `test_cli_mutate_integration_postgres`: **140/140, 0 skipped**
- `test_drafting_request_mutation_integration_postgres`: **53/53, 0
  skipped**
- `test_mutation_approval_integration_postgres`: **162/162, 0 skipped**
- `test_review_mutation_integration_postgres`: **82/82, 0 skipped**
- `test_mutation_journal_postgres`: **61/61**
- `test_mutation_reconciliation_provenance_postgres`: **24/24**

Bağımsız review'da ayrıca `py_compile` temiz, `pip check` temiz, `git
diff` kontrolleri temiz, gerçek `data/` ağacı bayt-düzeyinde DEĞİŞMEDİ,
kullanılan disposable PostgreSQL/temp residue TAMAMEN temizlendi ve
HİÇBİR bulgu raporlanmadı.

**Kalan kapsam ve borçlar**:

- OS-level atomik path pinning SAĞLANMADI.
- Doğrulama ile tekil filesystem işlemleri arasındaki dar local
  link-swap/TOCTOU riski Row 19D'nin OS ACL/service-identity kapsamında
  KALIR.
- Trusted-local-shell sınırı Row 19D'ye KALIR.
- Eski sürüm-adlı pending dosyaları (`facts_llm_v1.json.pending` vb.,
  `timeline_v1.json.pending`) bu pinli promotion yollarından ONAYLANAMAZ.
- Canonical yazılmış fakat başarı audit'i OLUŞMAMIŞ T2b/F3 vakaları
  OTOMATİK TAMAMLANMAZ; operatör müdahalesi (reconciliation) gerekir.
- Fact canonical writer'ın (timeline'a kıyasla) `fsync` farkı bu
  Slice'ta DEĞİŞTİRİLMEDİ.
- Pending-generation writer'ları (on Layer A ailesinin kendi
  deterministik engine/agent üretim adımı) HENÜZ coordinator/journal'a
  BAĞLI DEĞİLDİR.
- `ui/run_drafting_request.py --generate-pending` ikinci generation
  kapısı HÂLÂ AÇIKTIR.
- Maintenance/config ve global RAG ingest (`ingest.py`) bu Slice'ın
  DIŞINDADIR.
- Migration/şema ve production data DEĞİŞMEDİ.

**Final verdict: `ROW 19C-3b SLICE 2 LOCK-READY — No blocking
findings.`**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/19C-3a
Slice 1/Slice 2/19C-3b Slice 1 örneğinde olduğu gibi yalnız
`CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Row 19C-3c-i — Deterministic Generation Integration (DONE / LOCKED — checkpoint özeti)

**Exact scope (final, kilitli)** — Kullanıcı tarafından ayrıca onaylanmış
tam dosya allowlist'i üzerinde implement edildi: **6 YENİ + 13
DEĞİŞTİRİLMİŞ = 19 dosya**.

Yeni (6):
1. `ui/services/generation_mutation_facade.py`
2. `ui/services/generation_mutation_adapters.py`
3. `ui/tests/test_generation_mutation_facade_isolated.py`
4. `ui/tests/test_generation_mutation_integration_postgres.py`
5. `ui/tests/test_deadline_engine_isolated.py`
6. `ui/tests/test_timeline_engine_isolated.py`

Değiştirilmiş (13):
7. `src/deadline_engine.py`
8. `src/deadline_calculator.py`
9. `src/timeline_engine.py`
10. `src/timeline_validator.py`
11. `ui/cli_mutate.py`
12. `ui/reconciliation_operator.py`
13. `ui/services/promotion_mutation_adapters.py`
14. `ui/tests/test_cli_mutate_isolated.py`
15. `ui/tests/test_cli_mutate_integration_postgres.py`
16. `ui/tests/test_reconciliation_operator_isolated.py`
17. `ui/tests/test_reconciliation_isolated.py`
18. `ui/tests/test_drafting_request_mutation_integration_postgres.py`
19. `ui/tests/test_promotion_mutation_integration_postgres.py`

**Tamamlanan kapsam** — İki CLI-only action family: `generation.deadline`
/ `generation.timeline`. Merged reconciliation registry **37**'den
**39** routing key'e çıktı. Yeni bir web route/registry surface
AÇILMADI (generation ailesi yalnız `python -m ui.cli_mutate generation
...` üzerinden erişilebilir). Dedicated generation facade
(`generation_mutation_facade.py`) ve BAĞIMSIZ reconciliation adapter
(`generation_mutation_adapters.py`) eklendi - Layer A/Layer B/
drafting-request/promotion facade'lerinin HİÇBİRİ GENİŞLETİLMEDİ.
Existing coordinator, advisory lock, journal, idempotency ve
dual-authz altyapısı (Row 19C-1/19C-2a) AYNEN kullanıldı, DEĞİŞTİRİLMEDİ.
Direct `deadline_engine.py`/`timeline_engine.py` mutation CLI yolları
sabit stderr mesajı + `raise SystemExit(2)` ile, hiçbir DB/case
filesystem erişimi olmadan kapatıldı. Legacy executable matrisi
**19**; toplam refusal scenario sayısı **22**.

**Deadline revision/snapshot kontratı (final, remediation SONRASI)** —
Deadline `input_digest`/`pre_revision` şu DÖRT content revision'ını
bağlar: case.json, canonical timeline.json, kilit altında yakalanmış
(captured) ruleset, kilit altında yakalanmış provisions. `anchor_event_id`
YALNIZ `target_ref=deadline.<anchor_event_id>.pending` içindedir - hiçbir
digest'e girmez. `secondary_input_hash` YALNIZ
`holiday_dates`/`calendar_complete`/`judicial_recess_applicable`
parametre digest'idir - ruleset/provisions bu digest'te DEĞİLDİR (bkz.
Remediation geçmişi, madde 7-8). Aynı content + aynı anchor + farklı
parametre → aynı idempotency identity + farklı fingerprint → conflict.
Ruleset veya provisions revision değişikliği → yeni `pre_revision`/
idempotency identity → yeni, bağımsız bir generation denemesi (kalıcı
conflict ÜRETMEZ). Pre-lock best-effort read'den SONRA, under-lock
taze (fresh) baytlar YALNIZ belleğe (memory) capture edilir - hiçbir
dosya bu aşamada yazılmaz. Temp snapshot dosyaları ANCAK
`_mark_executing` sonrasında, `writer_callback` içinde oluşturulur ve
strict biçimde yeniden hash'lenir (re-hash). Writer, hesaplama için
YALNIZ bu snapshot rules/provisions'ı kullanır. `pre_commit_callback`,
atomic write'tan HEMEN önce canlı (live) global revision'ı tekrar
kontrol eder. Bu protokol global kaynaklar açısından TAM bir
linearizability SAĞLADIĞINI İDDİA ETMEZ - `pre_commit_callback`'in
kendi kontrolü ile gerçek `os.replace()` arasında kalan dar pencere
AÇIKÇA Row 19D borcu olarak KALIR.

**Timeline verified path-set kontratı** — `documents/` kökü,
document-id dizini, `document.json` ve `extractions/facts.json`
segmentleri AYRI AYRI, sırasıyla: `lexists` → `resolve_existing` →
exact-parent membership → doğrulanmış `is_dir`/`is_file` disiplinine
tabidir. Kaçan/kırık/döngüsel (broken/looping/escaping) bir intermediate
segment SESSİZCE "absent" sayılAMAZ - tüm taramayı fail-closed durdurur.
Duplicate resolved alias fail-closed reddedilir. Under-lock üretilen
sabit, containment-doğrulanmış Path seti (`document_paths`/`facts_paths`)
writer'a DOĞRUDAN taşınır; override verildiğinde `timeline_validator`
kendi raw glob'una ASLA geri DÜŞMEZ. Bu bir immutable byte-bundle
garantisi DEĞİLDİR - yerel bir filesystem aktörünün doğrulama ile
`open()` arasındaki link/content swap TOCTOU riski Row 19D borcu olarak
AÇIKÇA KALIR.

**Writer/audit/reconciliation** — Deadline ve timeline pending
yazımları atomic write + history backup + rollback düzenindedir.
Validator veya audit failure'ında: yeni pending kaldırılır, önceki
pending byte-for-byte restore edilir, partial audit temizlenir. Success
audit tam şema + tam journal binding (idempotency_key, resource_key,
actor_ref, action_family, target_ref/state, input_digest,
generation_parameters_digest, pending_sha256, first_write, history
backup bilgisi) taşır. `entry.pre_hash`/`pre_revision`, first_write/
history backup bilgisiyle birlikte YENİDEN üretilebilir composite bir
formülle journal'a bağlanır. Exactly-one fully-bound audit ZORUNLUDUR;
corrupt/duplicate audit fail-closed (`post_state_verified=False`)
davranır. `_mark_completed` failure durumunda satır `executing`/
`observed_post_hash=NULL` kalabilir ve YALNIZ tam disk+audit evidence
ile SONRADAN `completed` olarak reconciled edilebilir. Pre-state ve
post-state kanıtları TAMAMEN BAĞIMSIZ iki fonksiyonla hesaplanır:
pre-state YALNIZ containment-doğrulanmış pending presence/ham-bayt
hash'ine dayanır, JSON/audit ASLA okumaz; post-state pending
varlığı/hash'i + tam audit binding taraması kullanır. Post-state
tarafındaki bir JSON parse/audit hatası, bağımsız hesaplanmış geçerli
bir pre-state proof'unu ASLA BASTIRMAZ (bkz. erratum (e), Remediation
geçmişi madde 8).

**Remediation geçmişi (kısa, olgusal)**:

1. İlk scope çalışması timeline raw-glob divergence riski, deadline
   global-kaynak snapshot threading ihtiyacı, timeline'ın eski
   non-atomic writer'ı ve eksik audit zorunluluğunu ortaya çıkardı.
2. `timeline_validator`'a additive `document_paths=`/`facts_paths=`
   override parametreleri eklenerek writer'ın facade'den FARKLI bir
   girdi setini tekrar glob etmesi kapatıldı.
3. Deadline global-kaynak snapshot materialization `precondition_
   callback`'ten ÇIKARILDI; under-lock memory capture + yalnız
   `_mark_executing` SONRASI temp materialization düzenine getirildi.
4. `documents/*/extractions/` altındaki kırık ara-zincir, segment-
   segment fail-closed taramayla kapatıldı.
5. Audit `action_family`/`generated_at`/`pre_hash` bağları tamamlandı.
6. Adapter'ın post-state ve pre-state kanıtları birbirinden TAMAMEN
   bağımsız iki fonksiyona ayrıldı.
7. Bir İLK bağımsız salt-okunur inceleme, ruleset/provisions ham
   baytlarının yanlışlıkla `secondary_input_hash` içinde kalmasının,
   ruleset/provisions değiştiğinde `idempotency_key`'in DEĞİŞMEMESİNE
   (yalnız `request_fingerprint`'in değişmesine) - ve dolayısıyla
   meşru bir ikinci generation denemesinin KALICI bir
   `IdempotencyConflictError`'a düşebilmesine - yol açan HIGH önemde
   bir "deadline revision-identity" kusuru buldu.
8. Final remediation: ruleset/provisions hash'lerini `input_digest`/
   `pre_revision`'a TAŞIDI; `secondary_input_hash`'i YALNIZ generation
   parametrelerine (holiday/calendar/recess) İNDİRDİ; generation
   ailesi için eksik olan authz-denial testlerini (analyst preview/
   apply ayrımı, unassigned/unknown actor existence-blind denial)
   ekledi; erratum (e)'nin birleşik corrupt-JSON + matching raw
   pre-hash senaryosunu TEK bir `gather_evidence()` çağrısı + tam
   reconciliation pipeline proof'uyla ekledi; stale "17 legacy
   executable / 20 scenario" etiketlerini gerçek assertion'larla
   (19/22) hizaladı.
9. Son, bağımsız, salt-okunur bir targeted re-review, HIGH fix'i
   doğrudan kaynaktan yeniden türeterek (`input_digest`'in case+
   timeline+ruleset+provisions'ı bağladığını, `secondary_input_hash`'in
   yalnız holiday/calendar/recess taşıdığını, `anchor_event_id`'nin
   hiçbir digest'e sızmadığını, non-generation fingerprint/identity
   kodunun DEĞİŞMEDİĞİNİ) ve yukarıdaki testleri okuyarak, hiçbir
   Critical/High/Medium veya blocking bulgu RAPORLAMADI ve:
   `ROW 19C-3c-i LOCK-READY` verdict'ine ulaştı.

**Test kanıtı — dürüst zaman ayrımıyla**:

Final identity-remediated working tree üzerinde implementer'ın fiilen
çalıştırdığı full sweep: **44/44** `ui/tests/test_*.py` modülü exit 0,
**2770 passed, 0 failed, 8 counted skipped** (+ `test_reconciliation_
isolated` içinde PASS/FAIL sayacına girmeyen 1 informational `SKIPPED`
satırı), fresh disposable PostgreSQL 16, migration 0001-0004. Hiçbir
skip PASS SAYILMAMIŞTIR. **Bu full sweep, son targeted independent
re-review tarafından YENİDEN ÇALIŞTIRILMADI** - implementer'ın kendi
final-tree yürütme kanıtı olarak AYRI belirtilir, bağımsız reviewer'ın
kendi çalıştırması gibi SUNULMAZ.

Son, bağımsız targeted independent re-review'un BİZZAT çalıştırdığı ve
doğruladığı sonuçlar (yukarıdaki full sweep'ten AYRI, kendi ölçümü):

- `test_generation_mutation_facade_isolated`: **60/60**
- `test_reconciliation_isolated`: **192/192**
- `test_cli_mutate_isolated`: **191/191**
- `test_generation_mutation_integration_postgres`: **40/40, 0 skipped**
  (fresh disposable PostgreSQL 16, migration 0001-0004)
- `test_cli_mutate_integration_postgres`: **150/150, 0 skipped**
- `test_drafting_request_mutation_integration_postgres`: **53/53, 0
  skipped**
- `test_promotion_mutation_integration_postgres`: **50/50, 0 skipped**
- `test_mutation_journal_postgres`: **61/61**
- `test_mutation_reconciliation_provenance_postgres`: **24/24**
- `py_compile`: temiz
- `pip check`: temiz
- `git diff`/`git diff --cached` kontrolleri: temiz
- gerçek `data/` ağacı: bayt-düzeyinde DEĞİŞMEDİ
- kullanılan disposable PostgreSQL kümesi VE temp residue test sonunda
  TAMAMEN kaldırıldı

**Pre-remediation 2724-pass sweep, final identity-remediated kod
kanıtı olarak SUNULMAZ** - final, geniş full-sweep kanıtı **2770**'tir
(implementer'ın 46 yeni kontrolü: K1-K6 + L1-L5 identity/authz testleri,
erratum (e) birleşik senaryosu, G6/G7 gerçek-SQL identity/authz
kanıtları eklendikten SONRAKİ sayı).

**Scope dışı/kalan borç**:

- Agent/LLM-gated generation bu Slice'a DAHİL DEĞİLDİR.
- Retrieval/RAG generation bu Slice'a DAHİL DEĞİLDİR.
- Fact-extraction generation bu Slice'a DAHİL DEĞİLDİR.
- Global maintenance/RAG ingest (`ingest.py`) bu Slice'ın DIŞINDADIR.
- OS-level atomik path pinning SAĞLANDIĞI İDDİA EDİLMEZ.
- Yerel actor'ın link/content-swap TOCTOU riski Row 19D'nin OS ACL/
  service identity kapsamında KALIR.
- Global-kaynak (ruleset/provisions) için GERÇEK bir kilit/
  linearizability garantisi bu Slice tarafından SAĞLANMAZ - yalnız
  best-effort pre-lock + under-lock + pre-commit üç aşamalı kontrol.
- `mutation_lock`'ın session-level advisory-lock timeout/backoff borcu
  (§6'da zaten kayıtlı) bu Slice ile DEĞİŞMEDİ.
- Migration/şema DEĞİŞMEDİ.
- Production data DEĞİŞMEDİ.
- Existing approval (Layer A)/review (Layer B)/promotion/
  drafting-request facade ve adapter kontratları DEĞİŞTİRİLMEDİ.

**Final verdict: `ROW 19C-3c-i LOCK-READY — No blocking findings.`**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/19C-3a
Slice 1/Slice 2/19C-3b Slice 1/Slice 2 örneğinde olduğu gibi yalnız
`CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Row 19C-3c-ii — Case-Scoped Agent-Gated Pending Generation Integration (DONE / LOCKED — checkpoint özeti)

**Exact implementation scope** — Final çalışma ağacında **22 changed
path** (**9 NEW + 13 MODIFIED**), **0 allowlist dışı dosya**.

Yeni (9):
1. `ui/services/agent_generation_mutation_facade.py`
2. `ui/services/agent_generation_mutation_adapters.py`
3. `ui/tests/test_agent_generation_mutation_facade_isolated.py`
4. `ui/tests/test_agent_generation_mutation_integration_postgres.py`
5. `ui/tests/test_issue_spotting_engine_isolated.py`
6. `ui/tests/test_evidence_engine_isolated.py`
7. `ui/tests/test_argument_engine_isolated.py`
8. `ui/tests/test_risk_strategy_engine_isolated.py`
9. `ui/tests/test_drafting_engine_isolated.py`

Değiştirilmiş (13):
10. `src/issue_spotting_engine.py`
11. `src/evidence_engine.py`
12. `src/argument_engine.py`
13. `src/risk_strategy_engine.py`
14. `src/drafting_engine.py`
15. `src/risk_strategy_agent.py`
16. `src/drafting_agent.py`
17. `ui/run_drafting_request.py`
18. `ui/cli_mutate.py`
19. `ui/reconciliation_operator.py`
20. `ui/tests/test_reconciliation_operator_isolated.py`
21. `ui/tests/test_run_drafting_request_isolated.py`
22. `ui/tests/test_drafting_request_mutation_integration_postgres.py`

Üç dosya implementasyon öncesi onaylanmış allowlist'te bulunuyordu,
ancak source/test incelemesi sonucunda değişiklik GEREKTİRMEDİĞİ için
**untouched** kaldı: `ui/tests/test_cli_mutate_isolated.py`,
`ui/tests/test_cli_mutate_integration_postgres.py`,
`ui/tests/test_reconciliation_isolated.py`. Bu üçünün mevcut testleri
final ağaca karşı bağımsız olarak yeniden çalıştırıldı:
`test_cli_mutate_isolated` **191/191**,
`test_cli_mutate_integration_postgres` **150/150, 0 skipped**,
`test_reconciliation_isolated` **192/192**.

**Tamamlanan aile ve registry kapsamı** — Beş yeni action family:
`generation.issue_spotting` / `generation.evidence` /
`generation.argument` / `generation.risk_strategy` /
`generation.drafting`. Existing deterministik
`generation.deadline`/`generation.timeline` facade/adapters çifti
(Row 19C-3c-i, LOCKED) DEĞİŞTİRİLMEDİ; yeni beş aile AYRI
`agent_generation_mutation_facade.py`/`agent_generation_mutation_
adapters.py` çiftiyle entegre edildi — facade ve adapter kendi
bağımsız karar/path/evidence mantığını korur, yalnız karar içermeyen
`src/path_containment.py` primitive'i ortak kullanılır. Merged
reconciliation registry **39 → 44 routing key** oldu (10 approval + 24
review + 1 drafting_request + 2 promotion + 2 deterministic-generation
+ 5 agent-generation). Yeni bir web route/surface EKLENMEDİ; tek
mevcut `ui.cli_mutate generation` namespace'i additive olarak
genişletildi; `--expected-input-digest` sözleşmesi KORUNDU.

**Deterministic/agent ve network sözleşmesi** — Beş aile hem
deterministic hem agent modlarını AYNI coordinated path üzerinden
destekler. Agent apply için hem `--with-agent` hem `--allow-network`
ZORUNLUDUR; network izni mutation authorization'dan AYRI, açık bir
kullanıcı rızasıdır; `--allow-network` tek başına ve deterministic
mode ile REDDEDİLİR. Preview HİÇBİR model/network çağrısı yapmaz.
Usage-shape validation authz/connection/filesystem/model/journal
erişiminden ÖNCE çalışır. Production CLI HİÇBİR ZAMAN `llm_client`
geçmez — `preview_generation()`/`apply_generation()` içindeki keyword-
only `llm_client=None` yalnız test/dependency-injection seam'idir.
Injected client provenance: `model_id=external_injected_client`,
`prompt_agent_version=`gerçek family `AGENT_VERSION`. Deterministic
provenance: `model_id=deterministic_no_model`,
`prompt_agent_version=n/a`. Production agent provenance gerçek
`DEFAULT_AGENT_MODEL`/`AGENT_VERSION` sabitlerinden gelir.
`risk_strategy_agent.py` ve `drafting_agent.py` için eksik named
model/version sabitleri (`RISK_STRATEGY_AGENT_VERSION`/
`DRAFTING_AGENT_VERSION`, ikisi için de `DEFAULT_AGENT_MODEL`)
additive olarak eklendi; prompt/candidate/text-safety mantığı
DEĞİŞTİRİLMEDİ.

**Input manifest ve identity sonucu** — Her family için exact
logical-input container sayısı: `issue_spotting=3`, `evidence=3`,
`argument=8`, `risk_strategy=10`, `drafting=12`. Identity YALNIZ
facade'in bağımsız, containment-verified raw-byte manifestinden
üretilir; builder'ın kendi `analysis_metadata`'sı identity veya
stale kararı için KULLANILMAZ. Argument/risk_strategy/drafting
current-family canonical carry-forward kaynakları (`arguments.json`/
`risk_strategy.json`/`drafting.json`) digest üyesidir; drafting'in
`risk_strategy.json` ve `lawyer_input` girdileri de digest üyesidir.
Container state'leri kapalı bir vocabulary'dir: `present`/`empty`/
`missing`. Manifest scanner raw `Path.glob()` KULLANMAZ; `documents/`
yalnız verified directory üzerinden `iterdir()` ile taranır; entry
classification saf string işlemiyle containment kontrolünden ÖNCE
yapılır; metadata/content erişimi yalnız resolved/verified Path
üzerinden yapılır; broken/looping/escaping path missing SAYILAMAZ;
duplicate resolved target'lar fail-closed'dır; logical relative path'ler
validated segmentlerden ve POSIX `/` biçiminde kurulur.
`identity_payload` canonical bytes olarak dondurulur; under-lock fresh
identity bytes pre-build bytes ile birebir karşılaştırılır — fark
varsa candidate atılır, sıfır `prepared` journal satırı ve sıfır
filesystem mutation. `input_digest`, frozen `identity_payload`
bytes'ının SHA-256 değeridir. Builder'ın gelecekte manifest dışı yeni
bir file read eklememesi manuel code-review invariant'ıdır; bir
runtime metadata cross-check VARMIŞ GİBİ sunulmamalıdır.

**Outside-lock build ve frozen handoff** — Uzun deterministic/agent
build, case lock DIŞINDA ve journal satırı oluşturulmadan ÖNCE çalışır;
model/build failure sıfır journal row ve sıfır output mutation bırakır.
Candidate analysis, exact pending serialization bytes olarak build
sonrasında HEMEN dondurulur; under-lock writer'a fresh
`json.loads(frozen_bytes)` nesnesi verilir — original mutable analysis
dict freeze sonrasında KULLANILMAZ. Argument `carry_records` ayrıca
canonical bytes olarak dondurulup writer'a fresh object olarak taşınır.
Argument coordinated build `write_carry_forward_audit_enabled=False`
kullanır ve build aşamasında carry-forward audit YAZMAZ. Model çağrısı
case lock altında HİÇBİR ZAMAN yapılmaz; completed replay
model/builder/writer ÇAĞIRMAZ.

**Verified output-path handoff** — Per-module dinamik `CASES_DIR`
anchor kullanılır. Case/family/pending/history/reviews/carry-forward
zinciri pre-lock ve under-lock SIFIRDAN doğrulanır; completed replay
öncesi fresh path verification yapılır. Under-lock üretilen exact
`VerifiedGenerationOutputPaths` nesnesi writer'a aktarılır; coordinated
writer bütün gerçek output I/O işlemlerinde YALNIZ verified paths
kullanır — raw getters yalnız pure topology/leaf-name cross-check
amacıyla kullanılabilir. Legacy `verified_paths=None` davranışı
KORUNUR. Audit ve argument carry-forward dosyaları verified directory
altında `resolve_for_create` ile oluşturulur. Facade ve adapter path
derivation/decision mantığını PAYLAŞMAZ (yalnız karar içermeyen
`src/path_containment.py` ortak kullanılır). OS seviyesinde
verification ile `open`/`os.replace` arasında atomik path pinning
SAĞLANDIĞI İDDİA EDİLMEZ — kalan link-swap/TOCTOU penceresi Row 19D
OS ACL/service-identity hardening borcu olarak KALIR.

**Writer/audit/rollback sonucu** — Beş `write_pending()` writer'ı
mutation-binding kwargs ve `verified_paths` desteği kazandı; dönüş
şekli 3-tuple'dan generation-family dict sonucuna dönüştü; repo-wide
altı caller AYNI slice içinde uyumlandırıldı; legacy/self-test
davranışları KORUNDU. Pending write, post-write validation, canonical-
mutation guard, carry-forward audit ve generation audit AYNI
rollback-aware writer sınırı içinde yürütülür. Argument carry-forward
audit yalnız lock altında yazılır; generation audit failure sonrası
carry-forward audit için best-effort cleanup yapılır, cleanup failure
primary exception'ı MASKELEMEZ; successful rollback eski pending'i
byte-for-byte geri getirir; rollback-of-rollback residuali fail-closed
`reconciliation_required` bırakabilir.

Generation audit'in doğrudan bağladığı alanlar: `schema_version`,
`case_id`, `target_ref`, `target_state`, `action_family`, `channel`,
`mutation_actor_ref`, `mutation_idempotency_key`,
`mutation_resource_key`, `input_digest`,
`generation_parameters_digest`, `generation_mode`, `model_id`,
`prompt_agent_version`, `identity_payload`, `first_write`,
`history_backup_path`, `history_backup_sha256`, `pending_sha256`,
`generated_at`, `outcome`, ve argument için ayrıca
`carry_forward_audit_path`/`carry_forward_audit_sha256`. Adapter
`identity_payload`'ı bağımsız canonical serialization ile YENİDEN
hash eder; recomputed digest hem `audit.input_digest` hem journal
`entry.pre_revision` ile eşleşmek ZORUNDADIR; top-level
mode/model/prompt alanları `identity_payload` ile birebir eşleşir;
`mutation_actor_ref` journal `entry.actor_label` alanına bağlanır.
Overwrite success evidence için history backup dosyası gerçekten
mevcut, contained ve hash-matching olmak ZORUNDADIR. Argument
carry-forward audit path/hash/content/`audit_type`/`case_id` bağları
bağımsız doğrulanır. Exactly-one fully-bound success audit gerekir;
duplicate/corrupt/missing/unsafe audit auto-completed ÜRETEMEZ.

**Reconciliation/crash sözleşmesi** — Pre-state ve post-state proof
BAĞIMSIZDIR; reconciliation model/builder/writer ÇAĞIRMAZ. Karar
matrisi: `post=true → reconciled_completed`; `post=false, pre=true →
reconciled_failed_pre_state_confirmed_unchanged`; `post=false,
pre=false → unresolved/reconciliation_required`. First-write,
overwrite, backup-before-write, pending-written/audit-missing,
argument carry-forward aralıkları ve `_mark_completed` DB failure
senaryoları test edildi. Idempotent overwrite yalnız pending hash
eşitliğiyle `completed` SAYILAMAZ; audit yoksa `post=false` kalır;
rollback sonrası history backup artık yerinde değilse surviving
overwrite audit post-proof'ü GEÇEMEZ. `_mark_completed` DB failure
sonrasında `executing`/NULL journal kaydı, durable pending+audit
evidence ile writer/model YENİDEN ÇAĞRILMADAN `completed` olarak
reconcile edilebilir. Rollback-of-rollback ve process-death ara
durumları fail-closed operatör judgment gerektirebilir.

**Direct CLI closure** — Beş engine'in direct mutation branch'i
kapatıldı: `issue_spotting_engine.py`, `evidence_engine.py`,
`argument_engine.py`, `risk_strategy_engine.py`, `drafting_engine.py`.
İkinci drafting bypass'ı, `ui/run_drafting_request.py
--generate-pending`, de kapatıldı. Sabit stderr + gerçek
`SystemExit(2)`/`return 2` kullanılıyor; refusal DB/authz/case-file/
model/writer erişiminden ÖNCE; read-only preview ve `--self-test`
yolları KORUNDU. Final closure sayıları bağımsız incelemede
doğrulandı: **24 closed legacy src executable**, `ui/run_drafting_
request.py` dahil **25 total closed mutation entry point**, **40
refusal scenario**.

**Remediation geçmişi**:

1. İlk scope reconciliation beş case-scoped agent-gated aileyi
   belirledi.
2. Fable bir kez danışman olarak kullanıldı; ikinci drafting bypass'ı
   buldu ve model/prompt revision'ın identity içinde olması gerektiğini
   netleştirdi.
3. Independent manifest, frozen candidate, audit ownership ve mevcut
   generation CLI namespace'i sözleşmeleri birkaç read-only closure
   turunda kesinleştirildi.
4. Argument builder'ın pre-lock carry-forward audit yan etkisi bulundu
   ve coordinated path için kapatıldı.
5. Output-side verified Path handoff'ın önceki deterministic generation
   precedentinde eksik olduğu dürüstçe tespit edildi; bu slice daha
   güçlü verified writer-path handoff uyguladı.
6. Raw-glob/traversal, identity-payload binding, fake-client
   preview/apply digest uyumu ve idempotent-overwrite crash pencereleri
   implementasyon öncesinde kapatıldı.
7. Implementasyon sırasında: boş file descriptor bırakan carry-forward
   audit helper kaldırıldı; audit record path'ine güvenen containment
   hatası bağımsız verified root türetimiyle düzeltildi; registry count
   assertion'ları 44'e güncellendi; valid saved-wrapper ile
   `run_drafting_request` refusal coverage eklendi.
8. Paralel testlerin production data snapshot kontrollerini birbirine
   karıştırdığı iki yalancı failure görüldü; final doğrulama bütün
   testlerin tek süreçte/sırayla çalıştırılmasıyla yapıldı.
9. Bağımsız final review production/source/test/real-PostgreSQL
   doğrulamasını tamamladı ve `ROW 19C-3c-ii LOCK-READY` verdict'i
   verdi.

**Test kanıtı — zaman ayrımı dürüst tutularak**:

Implementer final-tree targeted sonuçları:

- `test_run_drafting_request_isolated`: **32/32**
- `test_drafting_request_mutation_integration_postgres`: **53/53, 0
  skipped**
- `test_cli_mutate_integration_postgres`: **150/150, 0 skipped**
- `test_mutation_approval_integration_postgres`: **162/162**
- `test_review_mutation_integration_postgres`: **82/82**
- `test_promotion_mutation_integration_postgres`: **50/50**
- `test_generation_mutation_integration_postgres`: **40/40**
- `test_mutation_journal_postgres`: **61/61**
- `test_mutation_reconciliation_provenance_postgres`: **24/24**
- `test_agent_generation_mutation_facade_isolated`: **47/47**
- `test_agent_generation_mutation_integration_postgres`: **33/33, 0
  skipped**
- `test_reconciliation_operator_isolated`: **91/91**
- `test_reconciliation_isolated`: **192/192**
- `test_cli_mutate_isolated`: **191/191**

Implementer final full sweep: **51/51** test modülü exit 0, **2936
passed, 0 failed, 8 counted skipped**, 1 informational, uncounted
`SKIPPED` satırı; bütün testler tek süreçte/sırayla çalıştırıldı; skip
HİÇBİR ZAMAN PASS SAYILMADI.

Bağımsız reviewer ayrıca: 22 dosyalık diff/source incelemesini
tamamladı; fresh disposable PostgreSQL 16 ile **51/51 full sweep'i
YENİDEN ÇALIŞTIRDI** ve AYNI **2936 passed / 0 failed / 8 counted
skipped** sonucunu bağımsız üretti; static/residue/git kontrollerini
yeniden doğruladı; yeni `AgentGenerationReconciliationAdapter`'a karşı
supplementary bir 8-scenario crash diagnostic'i çalıştırdı ve TAMAMI
GEÇTİ; repository review başı/sonu byte-identical KALDI. Nihai
verdict: `ROW 19C-3c-ii LOCK-READY`.

**Bağımsız review'de kalan üç Low bulgu** (non-blocking backlog/
test-depth notları, GİZLENMEDİ):

1. Yeni `AgentGenerationReconciliationAdapter`'ın repoda KALICI
   crash-matrix testleri deterministic sibling'a göre daha incedir.
   Reviewer'ın geçici supplementary 8-scenario diagnostic'i GEÇTİ,
   fakat repo test dosyasına EKLENMEDİ.
2. Full real CLI → PostgreSQL `apply_generation` round-trip beş
   aileden yalnız `issue_spotting` için uçtan uca kanıtlandı. Diğer
   dört aile writer/unit/facade seviyelerinde doğrulandı.
3. `_load_drafting_lawyer_input()` fonksiyonunun gerçek saved-wrapper
   branch'i DOĞRUDAN test edilmedi; no-wrapper branch ve Row 18C'nin
   temel wrapper kodu testlidir.

Bunlar production defect DEĞİLDİR; Critical/High/Medium bulgu YOKTUR;
LOCK'u ENGELLEMEZLER; gelecekte uygun test-hardening/backlog
kapsamında ele alınabilirler. Bu roadmap-lock turunda test dosyası
DEĞİŞTİRİLMEMİŞ ve test ÇALIŞTIRILMAMIŞTIR (bu bölümün kendisi
yalnızca önceki turun sonuçlarını kayda geçirir).

**Scope dışı ve kalan borç**:

- Fact extraction entegrasyonu Row 19C-3c-iii'ye KALDI.
- Legal Research/Case Law RAG-dependent generation Row 19C-3c-iv'e
  KALDI.
- `ingest.py`/deadline_rule maintenance/global-resource writer'ları
  AYRI bir operasyonel authorization fazına KALDI.
- Migration/şema DEĞİŞMEDİ.
- Production data DEĞİŞMEDİ.
- Existing deterministic generation facade/adapters (Row 19C-3c-i)
  DEĞİŞMEDİ.
- Yeni web surface EKLENMEDİ.
- OS-level path pinning SAĞLANMADI.
- Yerel actor link-swap/TOCTOU riski Row 19D'DEDİR.
- Rollback-of-rollback residuali KORUNMAKTADIR.
- Advisory-lock timeout/backoff backlog'u (§6) DEĞİŞMEDİ.

**Final verdict: `ROW 19C-3c-ii LOCK-READY — No blocking findings.`**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/19C-3a
Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i örneğinde olduğu gibi
yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Row 19C-3c-iii — Fact Extraction Generation Integration (DONE / LOCKED — checkpoint özeti)

**Exact scope (final, kilitli)** — Kullanıcı tarafından ayrıca
onaylanmış tam dosya allowlist'i **5 YENİ + 9 DEĞİŞTİRİLMİŞ = 14
dosya** idi; implementasyonda 14. dosya
(`ui/tests/test_cli_mutate_integration_postgres.py`) kaynak-kanıtlı
gerekçeyle (bkz. aşağıda "Untouched allowlist dosyası") GENUINELY
untouched kaldı — fiilen değişen: **5 YENİ + 8 DEĞİŞTİRİLMİŞ = 13
dosya, 0 allowlist dışı dosya**.

Yeni (5):
1. `ui/services/fact_extraction_mutation_facade.py`
2. `ui/services/fact_extraction_mutation_adapters.py`
3. `ui/tests/test_fact_extraction_mutation_facade_isolated.py`
4. `ui/tests/test_fact_extraction_mutation_integration_postgres.py`
5. `ui/tests/test_fact_extraction_engine_isolated.py`

Değiştirilmiş (8):
6. `src/fact_extraction_engine.py`
7. `ui/cli_mutate.py`
8. `ui/reconciliation_operator.py`
9. `ui/tests/test_cli_mutate_isolated.py`
10. `ui/tests/test_reconciliation_operator_isolated.py`
11. `ui/tests/test_reconciliation_isolated.py`
12. `ui/tests/test_agent_generation_mutation_integration_postgres.py`
13. `ui/tests/test_drafting_request_mutation_integration_postgres.py`

**Untouched allowlist dosyası** —
`ui/tests/test_cli_mutate_integration_postgres.py` allowlist'teydi ama
DEĞİŞTİRİLMEDİ: o dosyanın subprocess `LEGACY_MUTATION_MATRIX`'i sabit
`"...DEVRE DIŞIDIR (Row 19C-3b)."` literal'ini arayan 19 tarihsel-etiketli
legacy executable'ı kapsar; Row 19C-3c-ii'nin beş agent-generation
motoru gibi, `fact_extraction_engine.py` de KENDİ satır etiketini
(`"(Row 19C-3c-iii)"`) taşıdığı için bu matrise EKLENMEDİ — kapanışı
kendi izole engine test dosyasında hem in-process hem GERÇEK OS
subprocess kanıtıyla test edildi (beş agent-generation motorunun kendi
izole testlerinin HİÇBİRİNDE bulunmayan bir kanıt seviyesi). Dosyanın
untouched kaldığı final sweep'te 150/150 PASS ile ayrıca regresyonsuz
kanıtlandı.

**Tamamlanan kapsam** — BİR yeni, CLI-only, DOCUMENT-scoped action
family: `generation.fact_extraction` (`target_ref =
fact.<document_id>.pending` — promotion'ın `fact.<document_id>.canonical`
namespace'inin doğal uzantısı; `resource_key = case:<case_id>`
case-scoped kalır). Merged reconciliation registry **44 → 45 routing
key** oldu (10 approval + 24 review + 1 drafting_request + 2 promotion
+ 2 deterministic-generation + 5 agent-generation + 1
fact-extraction-generation) — dört bağımsız test konumu 45'i ayrı ayrı
doğrular. Yeni bir web route/surface AÇILMADI. Dedicated
fact-extraction facade/adapters çifti eklendi — Row 19C-3c-i'nin
deterministik ve Row 19C-3c-ii'nin agent-generation çiftlerinin HİÇBİRİ
DEĞİŞTİRİLMEDİ (adapters, facade'den yalnız karar-içermeyen sabit/format
yardımcılarını import eder; karar/containment/audit-eşleşme mantığı
bağımsız ikinci implementasyondur). Existing coordinator, advisory
lock, journal, idempotency ve dual-authz altyapısı AYNEN kullanıldı,
DEĞİŞTİRİLMEDİ. Kapalı mutasyon giriş noktası **25 → 26** (yeni:
`fact_extraction_engine.py` `main()`); toplam refusal senaryosu **40 →
41**; test modülü **51 → 54**.

**Zorunlu çift network gate ve credential hijyeni** — Row 19C-3c-ii
checkpoint'inin bu faz için açıkça zorunlu kıldığı
`--with-agent`/`--allow-network` çift açık network gate, İKİ BAĞIMSIZ
katmanda uygulandı: CLI usage-shape katmanı (her authz/DB/filesystem/
model erişiminden ÖNCE; bu ailede `--with-agent` preview DAHİL her
zaman ZORUNLU — deterministik mod YOKTUR; `--allow-network` preview'da
RED, apply'da `--with-agent` ile BİRLİKTE ZORUNLU) ve facade'in kendi
`_check_argument_shapes()`'i (CLI'dan bağımsız ikinci enforcement).
Motorun repo-genelinde EMSALSİZ import-zamanı `load_dotenv()` yan
etkisi `call_llm()`'in production (`llm_client is None`) dalının İÇİNE
taşındı — import/preview/refusal sırasında `.env` ASLA okunmaz;
`anthropic`/`python-dotenv` importları da aynı dala lazy taşındı
(hedef `vergi_ui_runtime`'da bu paketler kurulu değildir — module-level
import, facade'in `importlib.import_module()`'ını kırardı; diğer beş
LLM-çağıran agent modülünün var olan lazy-import deseniyle aynı,
allowlist-içi, gerekçeli sapma). `call_llm(prompt, model, *,
llm_client=None)` test-seam'i eklendi: injected-client dalı
`.env`/credential/gerçek `Anthropic()` constructor'ına SIFIR temas
eder; production CLI bu parametreyi HİÇBİR ZAMAN geçmez. Production
model kimliği her zaman call-time okunan `DEFAULT_MODEL` sabitidir —
coordinated CLI'ya `--model` flag'i BİLİNÇLİ olarak EKLENMEDİ;
injected client provenance'ı `model_id="external_injected_client"`.

**Identity/manifest kontratı** — `identity_payload` 7 alan taşır:
`manifest_version` (`row19c3ciii.fact_extraction.manifest.v1`),
`document_id`, `manifest` (4 sıralı logical container), `generation_mode`
(sabit `"agent"`), `model_id`, `engine_version`
(`FACT_EXTRACTION_ENGINE_VERSION`), `prompt_agent_version`
(`PROMPT_VERSION`). Manifest 4 container'dır: `case` (tekil),
`target_document` (document_id-parametreli tekil), `target_document_text`
(deterministik `documents/<id>/extracted/<id>.txt` konvansiyonu —
şema-zorlanmış DEĞİL, açıkça disclosure edilmiş sınır) ve
`case_documents` (değişken kardinaliteli; target_document kasıtlı hafif
redundancy ile yine görünür; geçerli bir başarılı apply'da minimum
kardinalite 1'dir, asla 0 değil). Containment-before-traversal tarama
precedent'in birebir bağımsız kopyasıdır; `Path.glob()` zero-call
mekanik kanıtla, escaping/broken GERÇEK NTFS junction'lar (`mklink /J`)
fail-closed testlerle doğrulandı. Model/engine/prompt revision
değişikliği `identity_payload` → `input_digest`/`pre_revision` →
`idempotency_key` zinciri üzerinden YENİ, bağımsız bir deneme üretir
(kalıcı conflict DEĞİL). `secondary_input_hash = None` (bu ailede
gerçek per-run parametre yoktur; yapay hash İCAT EDİLMEDİ).
`_MANIFEST_VERSION` ile `_SNAPSHOT_VERSION`
(`row19c3ciii.fact_extraction.snapshot.v1`) BİLİNÇLİ olarak FARKLI
literal'lerdir — precedent'in aynı-literal seçimi tekrarlanmadı.

**Build-skip fast path (Row 19A uyumlu)** — Pre-build, kilitsiz,
salt-okunur `_precheck_build_skip()` YALNIZ bir build-atlama bayrağı
üretir, HİÇBİR ZAMAN otoriter bir sonuç döndürmez; otoriter karar HER
ZAMAN, İSTİSNASIZ, `mutation_coordinator.run_mutation()`'ın
DEĞİŞTİRİLMEMİŞ kilit-altı idempotency-lookup'una aittir (Row 19A'nın
"otoriter kontroller kilit ALINDIKTAN SONRA TEKRAR" kararı). Build
atlanırsa `writer_callback` fail-closed bir sentinel'e
(`FactExtractionBuildSkippedInvariantError`) bağlanır — sessiz rebuild
veya sessiz eksik-yazım imkânsızdır. Gerçek PostgreSQL'e karşı
kanıtlandı: satır yokken build gerçekten çalışır (fake client tam 1
çağrı); `completed`/`failed` satır varken build GERÇEKTEN atlanır
(exploding client hiç çağrılmaz; `failed` için
`PriorAttemptFailedError`). LLM'in pending çıktısı deterministik
DEĞİLDİR (`extraction_id`/`fact_id`/`run_at` run_stamp taşır) — frozen
candidate disiplini bu yüzden kritiktir: frozen bytes
`json.dumps(extraction, ensure_ascii=False, indent=2).encode("utf-8") +
b"\n"` tarifiyle LLM cevabından hemen sonra dondurulur, writer'a
`json.loads(frozen_bytes)` ile üretilen taze kopya geçirilir, replay/
reconciliation'da model ASLA yeniden çağrılmaz.

**Writer/audit/rollback** — `run_fact_extraction()` davranış korunarak
`build_fact_extraction()` (saf build, dosyaya yazmaz) +
`write_pending()` (atomik yazım + audit + rollback) olarak refaktör
edildi; eski non-atomic `write_json()` coordinated path'te KULLANILMAZ
— LF-only + fsync + `os.replace` `atomic_write_json()` eklendi.
Pending dosya adı `facts_llm_v1_3.json.pending` — `fact_approval.py`'nin
(READ-ONLY) kendi pinli `CURRENT_PENDING_FILENAME`'iyle birebir; üretilen
pending, mevcut `promotion.fact` yolundan onaylanabilir (uçtan uca test
edildi). Post-write `validate_fact_extraction()` + canonical-mutation
guard + `document_id`/`engine_version` dahil tam-bağlama audit kaydı
(`O_CREAT|O_EXCL` + zaman damgası + sayısal sonek, kendi
`generation_reviews/` dizini, kendi `"local_lawyer_fact_extraction_cli"`
channel literal'i) writer sınırının içindedir; herhangi bir hata yeni
pending'i siler, önceki pending'i byte-for-byte geri taşır.

**Reconciliation** — Pre-state proof yalnız `entry.pre_hash`/
`pre_revision` + containment-doğrulanmış ham-bayt hash kullanır
(JSON/audit ASLA okumaz); post-state proof pending hash + exactly-one
tam-bağlama audit eşleşmesi kullanır (şekil doğrulama + ÜÇ YÖNLÜ
`document_id` bağlanması: target_ref'ten parse edilen ==
`audit["document_id"]` == `identity_payload["document_id"]`). Erratum
sertleştirmesi: `recomputed_input_digest` HEM `audit["input_digest"]`
HEM journal `entry.pre_revision` ile DOĞRUDAN eşit olmak zorundadır —
precedent'in dolaylı (idempotency_key-üzerinden) bağlamasının ÖTESİNDE,
bu aileye özgü açık bir ek savunma katmanı. Crash-matrix senaryoları +
6 malformed target_ref + tamper senaryoları KALICI olarak
`test_reconciliation_isolated.py`'ye eklendi (Row 19C-3c-ii'nin
bağımsız incelemesinin kaydettiği "supplementary diagnostic repoya
eklenmedi" backlog'unun bu ailede TEKRARLANMAMASI için — 3c-i'nin
yaptığı gibi).

**Scope/tasarım süreci** — İmplementasyondan önce ayrı, salt-okunur bir
scope-reconciliation + final-scope raporu + hedefli bir erratum turu
tamamlandı (dört paralel araştırma fork'u + Fable danışman geri
bildirimi: scope turunda 13 accepted / 3 corrected / 0 rejected;
erratum turunda 4 ek düzeltme — en önemlisi B1: lock-free replay-success
dönüşünün Row 19A ihlali olarak yakalanıp build-skip'in yalnız
optimizasyon olarak yeniden tasarlanması). `document_reference_resolver.py`
ve `case_fact_validator.py` kaynak-kanıtlı kararla READ-ONLY bırakıldı
(beş agent-generation ailesinin builder'larının aynı risk sınıfındaki
kendi raw-okumalarıyla tutarlı — builder'a manifest/verified-path
enjeksiyonu precedent'te YOKTUR).

**Test kanıtı — dürüst zaman ayrımıyla**:

İmplementer'ın final-tree full sweep'i (kendi disposable PostgreSQL 16
kümesi, migration 0001-0004): **54/54 modül exit 0, 3099 passed, 0
failed, 8 counted skipped** (+ `test_reconciliation_isolated` içinde
sayaca girmeyen 1 informational `SKIPPED` satırı). Hiçbir skip PASS
sayılmadı.

Bağımsız final inceleme (session kesintisiyle bölündü, disk kanıtından
devam ettirildi; tamamlanmış aşamalar yeniden üretilmedi): 8 modified
dosyanın diff yakalaması; KENDİ fresh disposable PostgreSQL 16 kümesi
(port 55433, migration 0001-0004) üzerinde BAĞIMSIZ 54-modül final-tree
sweep'i — **54/54 exit 0, 3099 passed, 0 failed, 8 counted skipped**,
implementer'ın sayısıyla birebir; sweep'in final tree'ye aidiyeti dosya
mtime'ları + sweep-sonrası sıfır repo değişikliği kanıtıyla ayrıca
doğrulandı. Bu faza özgü modüllerin bağımsız sweep sonuçları:
`test_fact_extraction_engine_isolated` **40/40**,
`test_fact_extraction_mutation_facade_isolated` **47/47**,
`test_fact_extraction_mutation_integration_postgres` **36/36, 0
skipped**, `test_cli_mutate_isolated` **202/202**,
`test_reconciliation_isolated` **220/220**,
`test_reconciliation_operator_isolated` **92/92**,
`test_agent_generation_mutation_integration_postgres` **33/33**,
`test_drafting_request_mutation_integration_postgres` **53/53**,
`test_cli_mutate_integration_postgres` (untouched) **150/150**.
Hedefli kaynak spot-check'leri (registry 45, çift network gate iki
katmanda, legacy closure, `llm_client` seam, facade/adapters
bağımsızlığı), `py_compile` 13/13, `pip check`, diff-check'ler ve
`data/` bayt-değişmezliği temiz. Disposable PostgreSQL kümeleri ve
inceleme temp kalıntıları tamamen temizlendi. Bağımsız incelemenin iki
Low/non-blocking notu: (1) kesilen oturumun satır-satır kaynak
incelemesinin yazılı ara-sonuçları yoktu — devam turu yük taşıyan
kontrat noktalarını güncel ağaçtan yeniden doğruladı; (2)
kendi-satır-etiketli motorların `LEGACY_MUTATION_MATRIX` dışında
kalması — Row 19C-3c-ii'de kabul edilmiş desenin devamı, yeni sapma
değil.

**Scope dışı/kalan borç**:

- Legal Research/Case Law RAG-dependent generation Row 19C-3c-iv'e
  KALDI.
- Global maintenance/RAG ingest (`ingest.py`/deadline_rule maintenance)
  AYRI bir operasyonel authorization fazına KALDI.
- OS-level atomik path pinning SAĞLANDIĞI İDDİA EDİLMEZ; yerel actor'ın
  link/content-swap TOCTOU riski Row 19D'nin OS ACL/service identity
  kapsamında KALIR.
- Trusted-local-shell CLI actor kimlik modeli Row 19D'ye KALIR.
- Advisory-lock timeout/backoff backlog'u (§6) DEĞİŞMEDİ.
- `document_reference_resolver.py`/`case_fact_validator.py`'nin raw-glob
  containment borcu (qa_validator BASE_DIR hardcode'u ile aynı sınıf)
  bilinen backlog olarak KALIR.
- Model/engine revision değişikliğinin yeni idempotency_key ürettiği
  formülün matematiksel garantisine dayanır — doğrudan izole testi
  gelecekteki test-hardening backlog'udur; fingerprint-mismatch bu
  ailede yapısal olarak ulaşılamaz (`target_state` sabit,
  `secondary_input_hash` her zaman `None`).
- Eşzamanlı iki İLK istek için model iki kez çağrılabilir (build-skip
  yalnız sequential replay'leri optimize eder) — bilinçli, disclosure
  edilmiş trade-off.
- `fact_repository.py` entegre EDİLMEDİ (sıfır harici çağıran, ayrı
  tasarım sorusu olarak backlog).
- `extracted_text_path` şema alanının hiçbir kod tarafından
  tüketilmemesi (deterministik konvansiyonun şema-zorlanmamış kalması)
  ayrı bir şema/pipeline borcudur.
- Migration/şema DEĞİŞMEDİ. Production data DEĞİŞMEDİ. Yeni web
  surface EKLENMEDİ.

**Final verdict: `ROW 19C-3c-iii LOCK-READY — No blocking findings.`**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/19C-3a
Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii örneğinde
olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir
roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Row 19C-3c-iv Slice 1 — Deterministic + Agent Legal Research / Case Law Pending-Generation Integration (retrieval/discovery deferred) (DONE / LOCKED — checkpoint özeti)

**Exact scope (final, kilitli)** — Kullanıcı tarafından ayrıca
onaylanmış tam dosya allowlist'i üzerinde implement edildi: **6 YENİ +
10 DEĞİŞTİRİLMİŞ = 16 dosya**, **0 migration**, **0 production-data
değişikliği**, **0 şema değişikliği**, **0 web surface**.

Yeni (6):
1. `ui/services/legal_research_case_law_mutation_facade.py`
2. `ui/services/legal_research_case_law_mutation_adapters.py`
3. `ui/tests/test_legal_research_case_law_mutation_facade_isolated.py`
4. `ui/tests/test_legal_research_case_law_mutation_integration_postgres.py`
5. `ui/tests/test_legal_research_engine_isolated.py`
6. `ui/tests/test_case_law_engine_isolated.py`

Değiştirilmiş (10):
7. `src/legal_research_engine.py`
8. `src/case_law_engine.py`
9. `ui/cli_mutate.py`
10. `ui/reconciliation_operator.py`
11. `ui/tests/test_cli_mutate_isolated.py`
12. `ui/tests/test_reconciliation_operator_isolated.py`
13. `ui/tests/test_reconciliation_isolated.py`
14. `ui/tests/test_agent_generation_mutation_integration_postgres.py`
15. `ui/tests/test_fact_extraction_mutation_integration_postgres.py`
16. `ui/tests/test_drafting_request_mutation_integration_postgres.py`

**F1/F2 remediasyonu YALNIZ şu 5 dosyada gerçekleşti** (marker-grep +
diff-aritmetiği ile bağımsız doğrulandı; remediasyon nedeniyle altıncı
bir dosya DEĞİŞMEDİ): `src/case_law_engine.py`,
`ui/services/legal_research_case_law_mutation_facade.py`,
`ui/tests/test_case_law_engine_isolated.py`,
`ui/tests/test_legal_research_engine_isolated.py`,
`ui/tests/test_legal_research_case_law_mutation_facade_isolated.py`.

**Mimari sonuçlar** — TEK birleşik facade/adapters çifti
(`legal_research_case_law_mutation_facade.py` /
`legal_research_case_law_mutation_adapters.py`). İki action family:
`generation.legal_research` / `generation.case_law`. `target_ref =
legal_research.pending` / `case_law.pending` (case_id-free);
`target_state = "generated"`; `resource_key = case:<case_id>`;
`secondary_input_hash = None`; `channel =
"local_lawyer_legal_research_case_law_cli"`. Önceki YEDİ
facade/adapter çifti (Layer A, Layer B, drafting_request, promotion,
deterministic-generation, agent-generation, fact-extraction)
DEĞİŞTİRİLMEDİ. Coordinator/registry/lock/guard/authz/DB altyapısı
DEĞİŞTİRİLMEDİ. Yalnız CLI yüzeyi (`python -m ui.cli_mutate
generation ...`); web surface AÇILMADI.

**Mod/network/RAG kontratı** — Deterministik ve agent modları AYNI
coordinated yolda desteklenir. Preview HİÇBİR model çağrısı yapmaz.
Gerçek agent/model çağrısı `--with-agent` + `--allow-network` çift
açık rızasına bağlıdır. Retrieval/discovery bu slice'ta
coordinator'dan YAPISAL olarak erişilemez: `retriever.py`/`rag.py`/
`ingest.py` ve `index/**` DOKUNULMAMIŞTIR; legal_research coordinated
build'i `use_discovery=False` sabitiyle çalışır (discovery'nin TÜM kod
yolu koşulsuz atlanır); case_law için agent ve discovery network
izinleri F1 remediasyonuyla AYRILMIŞTIR — `network_allowed` YALNIZ
agent (Anthropic) katmanına ulaşır, coordinated yolda facade
`discovery_network_allowed=False` sabitini geçirir (çağıran facade
üzerinden override EDEMEZ — `_invoke_builder` imzasında bu parametre
yoktur), `discovery_network_allowed=None` (legacy/default) davranışı
ise bugünkü `network_allowed` passthrough'unu AYNEN korur (mevcut
doğrudan Python call-site'ları değişmez). Doğrudan
`legal_research_engine.py` / `case_law_engine.py` mutasyon CLI'ları
sabit stderr mesajı + `raise SystemExit(2)` ile, `parse_args()`'tan
HEMEN sonra, hiçbir DB/case-filesystem/model erişimi olmadan
KAPATILDI — bu iki motorda korunacak `--self-test`/preview yolu
YOKTUR (kaynak-kanıtlı; `main()` SAF refusal'dır). Kapanış her iki
motorun kendi izole test dosyasında hem in-process hem GERÇEK OS
subprocess kanıtıyla (data/ byte-invariance dahil) test edilmiştir.

**Identity/manifest kontratı** — legal_research exact **6** logical
container: `facts, timeline, deadline, issues, global_documents,
global_provisions`. case_law exact **4** logical container: `issues,
timeline, research, global_documents` — **case_law identity'sinde
`provisions.json` BULUNMAZ** (builder zinciri okumaz; D13 düzeltmesi).
Manifest raw-byte SHA-256 + containment-before-traversal disipliniyle,
builder metadata'sından bağımsız kurulur; identity bytes deterministik
canonical serialization ile dondurulur; `generation_mode`/`model_id`/
`prompt_agent_version`/`engine_version` identity üyeleridir;
`pre_revision = input_digest = sha256(frozen identity bytes)`;
`secondary_input_hash = None`. Model/girdi/versiyon değişikliği
`identity_payload → input_digest/pre_revision → idempotency_key`
zinciri üzerinden YENİ, bağımsız bir deneme üretir — kalıcı conflict
DEĞİLDİR. Pre-lock best-effort capture + kilit ALTINDA exact recheck;
herhangi bir drift → candidate atılır, SIFIR `prepared` journal satırı
ve SIFIR filesystem mutasyonu.

**Build/writer/audit/reconciliation** — Uzun build (deterministik veya
agent) case kilidi DIŞINDA ve journal satırından ÖNCE çalışır; pending
exact serialization bytes olarak dondurulur, writer'a fresh
`json.loads(frozen_bytes)` verilir; model kilit altında ASLA
çağrılmaz. Kilit altında türetilen
`VerifiedLegalResearchCaseLawOutputPaths` writer'a aktarılır ve writer
verified modda tüm gerçek çıktı I/O'sunda yalnız verified path'leri
kullanır. Mevcut atomik yazım + history backup + post-write LOCKED
validator + rollback düzeni korunur. Success audit tam
mutation-binding taşır (`O_CREAT|O_EXCL`, aile-yerel
`generation_reviews/`). Adapter `identity_payload`'ı bağımsız
canonical serialization ile YENİDEN hash'ler;
`recomputed_input_digest == audit.input_digest == entry.pre_revision`
DOĞRUDAN zorunludur. Duplicate/corrupt/missing/unsafe audit
fail-closed'dır ve auto-completed ÜRETEMEZ. Reconciliation
model/builder/writer ÇAĞIRMAZ; `_mark_completed` DB failure'ında
`executing`/NULL satır, durable pending+audit kanıtıyla writer/model
yeniden çağrılmadan `completed` olarak reconcile edilebilir.

**Sayımlar (başlangıç → sonuç)** — test modülü **54 → 58**; merged
reconciliation registry routing key **45 → 47**; logical action family
**33 → 35**; kapalı mutasyon giriş noktası **26 → 28**; refusal
senaryosu **41 → 43**; registry'deki generation-family exact set
**8 → 10** üye.

**Dürüst test ve inceleme kronolojisi (zaman ayrımı korunarak — hiçbir
tur tek bir birleşik sonuç gibi SUNULMAZ)**:

1. **İlk implementasyon** (implementer'ın kendi final-tree sweep'i,
   fresh disposable PostgreSQL 16, migration 0001-0004, tek
   süreçli/sıralı): **58/58 modül exit 0, 3348 passed, 0 failed, 8
   counted skipped, 1 informational uncounted `SKIPPED`**. Buna
   RAĞMEN bağımsız inceleme iki blocking finding buldu — testlerin
   geçmesi LOCK için YETERLİ SAYILMADI.
2. **İlk bağımsız Fable incelemesi** (salt-okunur; kendi 58-modül
   sweep'inde AYNI 3348/0/8 sonucunu bağımsız üretti): **F1 HIGH** —
   case_law coordinated agent apply (`--with-agent --allow-network`)
   engine'in koşulsuz discovery katmanına `network_allowed=True`
   taşıyarak issue başına canlı `import retriever` denemesine
   ulaşıyordu (ampirik: 6 girişim; RAG bağımlılıkları kurulu bir
   ortamda `.env`/OpenAI/canlı flat-index yoluna, hedef runtime'da
   6× `retrieval_failed`'lı yanıltıcı pending'e dönüşürdü — Row 19A
   stale-sonuç kuralının ihlali). **F2 MEDIUM** — iki engine testinin
   fake'leri gerçek `client.generate(prompt)` protokolünü
   kullanmıyordu; `AttributeError` motorun kendi warning'ine
   yutuluyor ve "issues tam kapsandığı için agent çağrılmıyor"
   biçiminde YANLIŞ bir nedensel kanıt üretiyordu. Verdict: **NOT
   LOCK-READY**.
3. **Dar remediasyon** (yalnız 5 dosya): case_law
   build/run_engine'ine additive, keyword-only
   `discovery_network_allowed=None` seam'i; facade coordinated yolda
   `discovery_network_allowed=False` geçiriyor; agent katmanı ham
   `network_allowed`'ı koruyor; legacy `None` passthrough'u Section
   5a ile ampirik korundu; fake client'lar gerçek
   generate→parse→accept→output zincirini konuşuyor; yanlış
   "coverage nedeniyle agent çağrılmıyor" etiketi kaldırıldı,
   assertion'lar `==0`'dan `==1`'e SIKILAŞTIRILDI; remediasyonun
   kendi öz-incelemesinde yakalanan bir test-güvenliği kusuru
   (Section 5'in yanlışlıkla legacy default'u coordinated yol gibi
   test etmesi) 5a/5b ayrımı + fail-closed import guard'larla ayrıca
   düzeltildi. Remediasyon final sweep'i (implementer): **58/58,
   3367 passed, 0 failed, 8 counted skipped, 1 informational
   uncounted**.
4. **Bağımsız Fable yeniden incelemesi** (salt-okunur; bu turun ana
   ve bağımsız incelemecisi olarak Fable, ayrı advisor çağrısı
   olmadan): kaynak/call-chain doğrulaması (15/15 F1 maddesi, 15/15
   F2 maddesi); repo testlerinden BAĞIMSIZ, farklı mekanizmalı
   (`sys.meta_path`) fail-closed import tanısı **16/16 PASS** —
   coordinated case_law agent yolunda **SIFIR** RAG-stack import
   girişimi, legacy default kolunda beklenen **6** engellenmiş
   retriever girişimi (runtime-okunan coverage sayısıyla birebir),
   fake `.generate()` gerçek ve başarılı; 13/13 bağımsız hedefli
   test implementer sonuçlarıyla BİREBİR (50/43/55/60/212/270/92/
   33/36/40/61/24/53); bağımsız 58-modül full sweep (İKİNCİ fresh
   disposable PostgreSQL 16): **58/58 exit 0, 3367 passed, 0
   failed, 8 counted skipped, 1 informational uncounted** —
   sweep-genelinde recording-only import ledger'ı SIFIR RAG-stack
   girişimi kaydetti (enstrümantasyonun çalıştığı ayrı bir probe ile
   kanıtlandı). Final verdict: **LOCK-READY**.

**F1 kapanışı (açık kayıt)** — Eski durum: case_law'da `use_discovery`
parametresi yoktur (discovery baseline'dır), bu yüzden agent network
rızası (`--allow-network`) discovery katmanına DA ulaşıyordu. Risk:
flat, versiyonsuz RAG index'inden, identity/input_digest'e HİÇBİR RAG
versiyonu bağlanmadan retrieval-türevi içeriğin coordinated pending'e
girmesi. Çözüm: additive `discovery_network_allowed` ayrımı + facade'de
sabit `False`; legacy `None` passthrough'u korunur. Coordinated
agent VE deterministic yollarında SIFIR RAG importu, iki bağımsız
fail-closed kanıt zinciriyle (repo testleri + bağımsız meta_path
tanısı) kanıtlanmıştır.

**F2 kapanışı (açık kayıt)** — Eski fake'ler yalnız
`.messages.create()` taşıyordu; gerçek agent injection protokolü
`client.generate(prompt)`'tır; `AttributeError` motorun kendi
catch-all'ında "LLM çağrısı başarısız oldu" warning'ine yutuluyordu.
Yeni testler gerçek, runtime'da okunan fixture id'leriyle
generate→parse→validate/accept→output zincirini uçtan uca kanıtlar;
yanlış açıklamalar kaldırıldı; hiçbir catch-all monkeypatch ile
gizlenmedi; hiçbir assertion gevşetilmedi.

**Kalan Low/Observation disclosure'ları (GİZLENMEDİ)**:

- **F3 (Low, bu slice'ta DÜZELTİLMEDİ)** — `--with-agent --apply`,
  `--allow-network` olmadan usage-shape seviyesinde KABUL
  edilmektedir. `--allow-network` olmadan gerçek model/network
  çağrısı yapılmaz; ancak agent-mode apply'ın usage-shape reddi
  henüz uygulanmamıştır — "çift gate tam uygulanmıştır" DENEMEZ. Bu
  durumda pending, `generation_mode=agent` + production model
  identity'siyle yazılabilir ve o identity'nin idempotency slotunu
  TÜKETEBİLİR; sonradan `--allow-network` ile aynı identity retry
  edildiğinde safe replay nedeniyle model yine ÇAĞRILMAYABİLİR —
  girdiler değişene kadar gerçek agent çıktısı alınamayabilir. Bu
  davranış Row 19C-3c-ii'nin FİİLEN implement edilmiş mevcut
  semantiğiyle AYNIDIR; mimari raporun §G RED hücresi ile fiili
  precedent arasındaki fark burada disclosure olarak kaydedilir.
  Gelecekteki ortak agent-gate hardening backlog'una yazılır.
- **F4 (Low, bu slice'ta DÜZELTİLMEDİ)** — adapter'ın
  `history_backup_path` reconciliation okuması containment'sız ham
  `Path` kullanır (3c-ii'den miras, üç adapter'ı birlikte ilgilendiren
  ortak hardening borcu; yorum metni koddan daha iddialıdır).
- **F5 (Observation)** — audit yazımı ORTASINDA kalan partial audit
  dosyası rollback'te ayrıca temizlenmeyebilir; reconciliation
  corrupt/partial audit'i fail-closed reddeder (post=False). Bu
  slice'ta düzeltilmedi (3c-ii precedent şekli).
- **F6 (Observation)** — facade yorumundaki "bağımsız kopya / import
  edilmez" ifadesi, adapter'ın `FAMILY_INPUT_SPECS`'i facade'den
  fiilen import etmesiyle KOZMETİK olarak çelişir; güvenlik etkisi
  yok.
- **Yeni non-blocking observation'lar** — (a) untouched PostgreSQL
  integration testinin B10 fake'i hâlâ `.messages.create()`-only'dir;
  genuine `.generate()` round-trip kanıtı üç remediasyon test dosyası
  + bağımsız tanıda mevcuttur (gelecekteki test-hardening adayı). (b)
  Bazı implementer ara sayım etiketleri granüler değildir; otoriter
  sonuç, iki bağımsız sweep'in mekanik sayımlarıdır (3367/0/8/1).

**LOCKED-file §9 kaydı** — İki LOCKED engine bu slice'ta açıldı:
`src/legal_research_engine.py` (additive, keyword-only
mutation-binding/audit/`verified_paths` desteği + doğrudan CLI
kapanışı) ve `src/case_law_engine.py` (aynısı + F1 remediasyonundaki
additive `discovery_network_allowed` ayrımı). Gerekçeler: coordinator
uyumluluğu, doğrudan mutasyon bypass'ının kapatılması (security),
audit/rollback/reconciliation bağlama zorunluluğu ve Row 19A gereği
retrieval'ın yapısal olarak ertelenmesi. Build/policy/candidate domain
mantığı DEĞİŞMEDİ; her iki ailenin policy/discovery/agent/validator/
approval dosyaları UNTOUCHED kaldı.

**Scope dışı ve başlamamış işler (bu checkpoint HİÇBİRİNE dosya
yetkisi VERMEZ)**:

- RAG Global-Resource Bundle Foundation (sıradaki faz — yalnız
  salt-okunur reconciliation ile açılır).
- ROW 19C-3c-iv Slice 2 — Retrieval/Discovery-Dependent Generation
  (ancak Bundle Foundation SONRASI).
- Row 10/11 `rag_index_version_used` şema yaması (Row 19A'nın ayrı
  onay maddesi).
- Production mevzuat/içtihat corpus population.
- Global maintenance authz/capability/lock modeli.
- QA/Orchestrator pending-generation publisher'ları.
- Row 19D — Operations & Recovery (OS ACL/service identity/TOCTOU,
  advisory-lock timeout backlog'u dahil).
- Ortak agent-gate hardening (F3) ve ortak `history_backup_path`
  containment hardening (F4).

**Final verdict: `ROW 19C-3c-iv SLICE 1 LOCK-READY — F1/F2 closed, no blocking findings`**

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/
19C-3a Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii/
19C-3c-iii örneğinde olduğu gibi yalnız `CLAUDE.md`'yi değiştiren,
salt-okunur bir roadmap-lock işlemidir; hiçbir kaynak/migration/test/
production dosyasına dokunmaz.

### RAG Global-Resource Bundle Foundation (DONE / LOCKED — checkpoint özeti)

**Preflight ve scope** — Başlangıç HEAD
`c757dad6a419e635037c7ef0535ce7576e562eab`; branch `claude-dev`;
staged set boş; `data/`, `index/`, `CLAUDE.md`, `db/migrations/`
(0001-0004) temiz; `stash@{0}` mevcut ve dokunulmamış. Onaylı exact
allowlist **21 dosya** (10 yeni + 11 değiştirilmiş). Fiilen değişen
**20 dosya**: 10 yeni + 10 değiştirilmiş —
`ui/tests/test_reconciliation_isolated.py` (allowlist'in 11.
"değiştirilmiş" dosyası) kaynak-kanıtlı olarak (registry-count
coupling'i SIFIR — grep'le doğrulandı) GENUINELY untouched kaldı ve
kendi regresyonuyla (270/270, hem implementasyon hem bağımsız
re-review turunda) değişmeden PASS etti — bu, Row 19C-3c-iii'nin
`test_cli_mutate_integration_postgres.py` precedent'iyle AYNI
desendir. Sonradan gelen targeted remediation turu bu 20-dosyalık
setin İÇİNDEKİ yalnız **6 dosyada** kaldı (§7) — SIFIR yeni dosya,
SIFIR yeni migration. `data/**` ve `index/**` (mevcut flat index
dahil) implementasyon, ilk bağımsız inceleme, remediasyon ve nihai
Fable yeniden-incelemesi boyunca bayt-düzeyinde DEĞİŞMEDİ (her turda
ayrıca sha256 manifestiyle kanıtlandı). `CLAUDE.md` implementasyon
sırasında HİÇ değiştirilmedi — bu checkpoint'in kendisi ilk yazım
anıdır.

**IAM/migration** — `db/migrations/0005_global_resource_grants.sql`
(yalnız additive, 0001-0004 bayt-düzeyinde untouched):
`iam.global_resource_grants` (surrogate `BIGSERIAL PRIMARY KEY` —
doğal-key PK DEĞİL; `resource` kapalı `'rag_index'`; `capability`
kapalı `inspect`/`build`/`activate`; `granted_by_user_id`/
`granted_at`/`revoked_at`/`revoked_by_user_id`; `(revoked_at IS
NULL) = (revoked_by_user_id IS NULL)` CHECK) + aktif-grant partial
unique index (`(user_id,resource,capability) WHERE revoked_at IS
NULL` — `iam.case_assignments`'ın 0001'deki aynı desenidir) +
bağımsız, append-only `iam.global_resource_grant_events`
(`event_type` kapalı `grant_created`/`grant_revoked`; `grant_id`
FK'si `iam.global_resource_grants(id)`'e bağlı — bağımsız incelemenin
doğrudan kaynaktan doğruladığı madde). Revoke sonrası re-grant YENİ
bir surrogate-id satırı + kendi `grant_created` event'ini açar;
eski satırın tarihçesi kalıcı korunur (hem fake hem gerçek
PostgreSQL'de kanıtlı). `iam.security_events` (0001) tablosuna
DOKUNULMADI — 19B'nin "IAM mutasyonu + typed event AYNI transaction"
invariant'ı adanmış `global_resource_grant_events` tablosuyla AYNEN
sağlanır, çift-otorite yaratılmaz. `mutation.mutation_resources`'a
YENİ satır eklenmedi — `global:rag_index` migration 0003 tarafından
ZATEN seed'liydi. Grant/revoke/list YENİ, dar
`scripts/global_resource_grants.py` CLI'ı üzerinden —
`scripts/iam_admin.py`'nin `_run_locked_as_admin`/
`_verify_actor_is_active_admin` desenini BAĞIMSIZ bir kopya olarak
(import değil) uygular: `global:iam` transaction-lock → aktif-admin
actor doğrulaması → grant/revoke satırı + AYNI transaction'da typed
event → commit/rollback birlikte. Aktif global admin olan bir
kullanıcıya capability grant'ı CLI karar-mantığında KOŞULSUZ
REDDEDİLİR (hem fake hem gerçek PostgreSQL'de kanıtlı; bypass yok).
`ui/services/global_authz.py`'nin `authorize_global_resource_access()`'i
iki-adımlı, existence-blind bir kontroldür — admin rolüne HİÇBİR
otomatik yetki vermez (kod içinde admin sorgusu hiç yok); revoked bir
grant ile hiç verilmemiş bir capability BİRBİRİNDEN AYIRT
EDİLEMEZ. **Bilinen kozmetik sapmalar** (Low, F5.8 — LOCK'u
engellemedi): (a) zaten aktif bir capability için tekrar grant isteği
implementasyonda idempotent BAŞARI döner (`created=False`, görünür
"already actively granted" mesajı) — Fable FINAL'in tercih ettiği
"açık hata" davranışından SAPAR, ama sessiz DEĞİLDİR; (b) event tipi
literal'leri Fable FINAL'in önerdiği `global_resource_grant_created/
…_revoked` yerine daha kısa `grant_created`/`grant_revoked`'tir
(adanmış tabloda önek gereksiz).

**Bundle mimarisi** — `bundle_version = "v_" +
sha256(canonical_json(identity_core)).hexdigest()` — TAM 64
lowercase hex, HİÇ kısaltılmaz (her tüketim noktasında regex'le
doğrulanır). İki-parçalı model: `manifest.json` = SALT deterministik
identity-core (`source_manifest`, `pipeline_config`, üç sabit
artifact adı — `mevzuat.faiss`/`documents.pkl`/`config.json` —
için `{sha256,size_bytes}` tablosu, `record_count`/`chunk_count`) +
`bundle_version` alanı hash'lendikten SONRA eklenir (self-reference-
sız). Volatile provenance (`created_at`, actor kimliği, `channel`,
mutation idempotency, `input_digest`) HİÇBİR ZAMAN manifest'te
BULUNMAZ — tamamı build AUDIT kaydına taşınır (tek otorite: journal +
audit; çift-otorite reddi). **İki kasıtlı ayrı digest**
(implementasyon sırasında yapılan bir tasarım düzeltmesi):
`input_digest` (journal identity/`pre_revision`; `build_attempt`
dahil; build ÖNCESİ hesaplanabilir) ile `source_digest`
(`MutationIntent.pre_hash`, reconciliation pre-state kanıtı için;
`build_attempt` HARİÇ — böylece crash'lenmiş bir attempt'in numarası
audit'siz köşede geri kazanılmak ZORUNDA değildir). Staging kökü
`index/staging/b_<idempotency_key[:24]>`; artifact'ler fsync'lenip
manifest yazımından ÖNCE re-read ile yeniden doğrulanır (manifest
EN SON yazılır); `Path.rename`/`os.replace` ile `index/v_<64hex>/`e
atomik publish. Aynı bayt içeriği = deterministik güvenli replay;
farklı bayt = `BundleVersionCollisionError`, mevcut dizin TAMAMEN
DOKUNULMAMIŞ. Orphan staging dizinleri için HİÇBİR silme/cleanup/GC
yüzeyi YOKTUR (grep-kanıtlı) — kasıtlı olarak inert, GC yalnız
gelecekteki bir başlıktır.

**Build/activate coordinator sözleşmesi** — `rag_bundle.build` ve
`rag_bundle.activate`, `resource_key="global:rag_index"` (0003
tarafından zaten seed'li — kilit için yeni migration GEREKMEDİ),
`channel="local_maintenance_rag_bundle_cli"`. Build apply'da
`--allow-network` KOŞULSUZ zorunludur (CLI usage-shape katmanı +
facade katmanı, ikisi de bağımsız); ağır build (PDF→chunk→embed→
FAISS) TAMAMEN RAM'de, kilit DIŞINDA, journal satırı OLUŞMADAN ÖNCE
çalışır; kilit altında kaynak re-hash edilip frozen pre-lock
snapshot'ıyla karşılaştırılır — drift → `SourceDriftDetectedError`,
SIFIR journal/bundle/staging/audit yazımı. `build_attempt` retry
kuralı: attempt artışı `input_digest`'i (ve idempotency identity'yi)
değiştirir, `source_digest` değişmeyen kaynaklar için AYNI kalır.
Build-skip fast path: pre-lock, best-effort, HİÇBİR ZAMAN otoriter
olmayan bir peek, bilinen-güvenli bir replay'den ÖNCE pahalı
builder çağrısını atlar; otoriter karar HER ZAMAN coordinator'ın
kendi kilit-altı idempotency lookup'ındadır; peek'in yanıldığı
(ulaşılmaması gereken) durum için `writer_callback` içinde
fail-closed bir sentinel vardır. Activation: hedef bundle için
geçerli, tam-bağlama bir `rag_bundle.build` audit'i OLMADAN reddeder
(`BundleNotBuildAuditedError`); zaten aktifse reddeder
(`AlreadyActiveError`); bayat `--expected-current-version`'da
reddeder (`StaleCurrentVersionError` — gerçek versiyon/`"none"`/
`"corrupt"` üç gözlemlenebilir durumu kapsar); pointer temp-dosya +
fsync + tek atomik `os.replace()` ile değiştirilir; activation ASLA
network'e dokunmaz (`--allow-network` activate'te topyekûn
reddedilir). Bu sözleşmenin F1-F4 remediasyonuyla kazandığı nihai
hâli (`activation_attempt` identity alanı, parametreli `target_ref`,
composite `pre_hash`, W0-W6 crash-safe writer/rollback sırası, her
iki aile için replay corroboration, per-idempotency-key `O_EXCL`
build audit'leri) §7'de ayrıntılıdır.

**Reader ve closure** — `PinnedRagBundle`: pointer→manifest→artifact
hash zinciri tam doğrulanır; altı adlandırılmış fail-closed hata
sınıfı (`RagPointerMissingError`, `RagPointerInvalidError`,
`RagManifestInvalidError`, `RagArtifactHashMismatchError`,
`RagDimensionMismatchError`, `RagBundleNotPinnedError`); hash-önce-
deserialize disiplini — 11 fail-closed senaryonun TAMAMI faiss'in
süreçte HİÇ BULUNMADIĞI bir ortamda geçti (deserialize'a
ulaşılamayacağının yapısal kanıtı). `retrieve()`/`retrieve_detailed()`
açık bir `bundle=<PinnedRagBundle>` GEREKTİRİR; varsayılan
`bundle=None` fail-closed `RagBundleNotPinnedError` verir — sessiz
flat-index fallback yolu reader içinde SIFIR referansla (kasıtlı RED
kararı, gözden kaçma DEĞİL). `src.rag`/`src.evaluation`/
`src.evaluation_v6` bu Foundation slice'ında `bundle=` geçecek şekilde
GÜNCELLENMEDİ — mevcut çağrıları (ve `retriever.py`'nin kendi
`__main__` smoke-test bloğu) artık `RagBundleNotPinnedError` ile
fail-closed olur; bu, gelecekteki AYRI bir adaptasyon fazına
kadar kabul edilen sonuçtur. `rag.py:53`'ün module-level `from
anthropic import Anthropic` importu DOKUNULMADAN kalır — bu
Foundation'ın öncesinde de var olan, Foundation'ın DEĞİŞTİRMEDİĞİ bir
kırılganlıktır (anthropic'siz ortamda `import rag` bugün de, sonra da
kırıktır). `src/ingest.py`'nin `main()`'i sabit stderr + gerçek
`SystemExit(2)` ile, hiçbir I/O'dan önce kapatıldı — gerçek OS
subprocess ile kanıtlandı; import-anı yan etkilerin (dotenv/openai/
faiss/numpy/pypdf/mkdir/RuntimeError) TAMAMI kaldırıldı —
`import ingest`/`import retriever` artık bu beş bağımlılığın HİÇBİRİ
kurulu olmayan gerçek hedef ortamda (`vergi_ui_runtime`) sıfır I/O/
credential/network ile temiz import olur (subprocess probe ile
kanıtlı).

**Reconciliation/crash** — Ayrı `BuildReconciliationAdapter` /
`ActivateReconciliationAdapter`; post-state kanıtı için exactly-one
bound audit ZORUNLU; corrupt/duplicate audit hiçbir yerde kesin
post-state kanıtı SAYILMAZ (`corrupt==0 && len(matches)==1` şartı).
Reconciliation writer/network/build'i ASLA yeniden çağırmaz — yapısal
olarak (adapter kodu `build_bundle_snapshot`/`embedding_client`'a
hiç referans vermez) ve ampirik olarak (zehirlenmiş builder birçok
`gather_evidence()` çağrısı boyunca hiç tetiklenmedi) kanıtlı. F1-F4
remediasyonunun getirdiği **W0-W6 yazıcı/rollback sırası**: W0
fail-closed önceki-pointer okuması (okunamayan-mevcut'u absent ile
ASLA karıştırmaz); W1 audit-dizin `mkdir`'i pointer replace'ten
ÖNCEYE taşındı (F2'nin çekirdek düzeltmesi); W2 pointer temp+fsync+
atomik `os.replace`; W3 `O_CREAT|O_EXCL` audit açılışı — eski
`FileExistsError→pass` yutması TAMAMEN KALDIRILDI (F5.7 kapanışı),
artık rollback + re-raise tetikler; W4 fd alındıktan SONRAKİ yazım/
fsync hatası → best-effort partial-dosya unlink (unlink hatası
CRITICAL loglanır, asla sessiz) → pointer rollback → ORİJİNAL
exception değişmeden yeniden fırlatılır; W5 rollback'in KENDİSİ
başarısız olursa CRITICAL loglanır (asla sessiz `pass`), orijinal
exception yine fırlar; W6 audit başarıyla yazılmış ama
`_mark_completed` DB hatası almışsa satır `executing` kalır,
reconciliation writer'ı YENİDEN ÇAĞIRMADAN durable kanıtla çözer
(gerçek PostgreSQL'de bir P11-tarzı, yalnız DB-seviyesinde
`completed` UPDATE'ini kıran trigger'la — production kodda SIFIR
monkeypatch — kanıtlandı). İki aktör aynı içerikte bundle
yayımlarsa HER BİRİ kendi, bağımsız, per-idempotency-key `O_EXCL`
audit dosyasını alır (`first_publish=True/False` ayrımı) — F4'ün
orijinal "paylaşımlı tek audit dosyası" kusurunu kapatır; her
aktörün kendi journal satırı KENDİ audit'iyle replay-doğrulanır,
diğerininkiyle ASLA.

**Bulgular ve remediasyon kronolojisi (dürüst zaman ayrımıyla)** —
İlk implementasyon sweep'i (implementer'ın kendi koşusu): **63/63
modül exit 0, 3530 passed, 0 failed, 8 counted skipped**. İlk
inceleme — **metodolojik bağımsızlık, implementer ile AYNI Sonnet
session'ı, ayrı model/ayrı session DEĞİL** (rapor bunu açıkça
disclose eder) — aynı 3530/0/8 sonucunu bağımsız yeniden üretti,
AMA kaynak/diff/gerçek fault-injection ile implementer raporuna
güvenmeden 1 HIGH (F1) + 3 MEDIUM (F2/F3/F4) + bir Low paketi
(F5, 12 madde) buldu; verdict **NOT LOCK-READY**. Dar bir targeted
remediation (F1/F2/F3/F4 + iki adlandırılmış Low madde — F5.4'ün
pre_hash-composite yarısı ve F5.7'nin audit `FileExistsError→pass`
kaldırılması) TAM OLARAK **6 dosyada**, mevcut 20-dosyalık set
İÇİNDE (sıfır yeni dosya, sıfır yeni migration) uygulandı.
Remediasyon implementer'ının kendi final full sweep'i: **63/63 modül
exit 0, 3650 passed, 0 failed, 8 counted skipped**. Bunun ardından
**tamamen AYRI, gerçekten bağımsız bir Fable session'ı** (implementer
oturumundan ayrı olduğu açıkça disclose edilir) — kendi repo-dışı
FakeConn/fault-injection tanısıyla (repo test fixture'larından
KOPYALANMADAN), fresh disposable PostgreSQL 16 ile, ve implementer
raporunun hiçbir iddiasına güvenmeden — **63/63 modül, 3650 passed,
0 failed, 8 counted skipped**'i BAĞIMSIZ olarak bire bir yeniden
üretti; F1-F4'ün dördünün de KAPANDIĞINI kaynak-kanıtlı olarak
doğruladı; kendi repo-dışı 66/66 DIAG-PASS fault-injection matrisini
çalıştırdı; **0 Critical, 0 High, 0 Medium, 5 Low/Observation**
(O1-O5, hiçbiri bloklamaz) buldu. Final verdict (tam metin):
`RAG BUNDLE FOUNDATION LOCK-READY — F1-F4 CLOSED, NO BLOCKING FINDINGS`.

**Sabit sayımlar** — test modülü **58→63**; merged reconciliation
registry routing key **47→49**; logical action family **35→37** (10
approval + 12 review + 1 drafting_request + 2 promotion + 2
deterministic-generation + 5 agent-generation + 1
fact-extraction-generation + 2 legal-research/case-law-generation +
2 rag-bundle [build/activate]); migration **4→5**; kapalı mutasyon
giriş noktası **28→29** (+`src/ingest.py`'nin `main()`'i); refusal
senaryosu **43→44**.

**Kalan Low/Observation** — Nihai Fable yeniden-incelemesinin kendi
beş maddesi (hiçbiri bloklamaz): **O1** (Low) — başarılı bir
aktivasyondan SONRA AYNI CLI girdilerinin SIRALI (sequential) tekrar
verilişi, pre-lock `StaleCurrentVersionError`'a düşer (yüksek sesli,
fail-closed red); genuine "replay-accept" yalnız ULAŞILABİLİR olduğu
tek senaryoda — eşzamanlı (concurrent) çift-gönderim — gerçek public
API üzerinden uçtan uca kanıtlanmıştır; hiçbir yol sessiz veya
fail-open değildir. **O2** (Low) — activation audit'inin üst-seviye
`activation_attempt`/`expected_current_bundle_version` kopyaları
recompute kontrolünde `identity_payload`'ın kendi kopyalarına
BAĞLANMAZ (yalnız `bundle_version`/`bundle_manifest_sha256` üst-
seviye kopyaları bağlanır) — yalnız GÖRÜNTÜLEME etkisi (bir replay
sonucunun `previous_version` gösterim alanı yanlış raporlanabilir;
pointer/journal/state/karar üzerinde SIFIR etki). **O3**
(Observation) — writer-içi W0 pointer okuması etkisiz-ulaşılamaz bir
üçüncü savunma katmanıdır (pre-lock + kilit-altı precondition recheck
aynı anomaliyi zaten daha önce yakalar) — fail-closed fazlalık, kusur
DEĞİL. **O4** (Observation) — `cli_mutate.py`'nin
`_is_known_domain_error` docstring'i üç yeni exception sınıfını
(`BundleManifestDriftError`/`BuildReplayVerificationError`/
`ActivationReplayVerificationError`) saymıyor; gerçek davranış
`RagBundleMutationError` tabanı üzerinden DOĞRUdur — kozmetik. **O5**
(Observation) — W5 (rollback-failure) yolu re-review'da tek-seferlik
fault injection ile kanıtlandı ama kalıcı bir repo testi yok —
gelecekteki test-hardening adayı. İlk bağımsız incelemenin diğer Low
maddeleri (F5.1, F5.2, F5.3, F5.4'ün diğer yarısı, F5.5, F5.6,
F5.8'in kalan literal sapmaları, F5.9, F5.10, F5.11, F5.12) bu
remediasyona dahil EDİLMEDİ ve AÇIK backlog olarak kalır — hiçbiri
"kapandı" olarak SUNULMAZ.

**Gerçek dependency kapısı** — `faiss`/`numpy`/`openai`/`pypdf`/
`python-dotenv` bu ortamda (`vergi_ui_runtime`) KURULU DEĞİLDİR. Dört
informational skip (`test_rag_bundle_builder_isolated`: 3,
`test_rag_bundle_reader_isolated`: 1) PASS SAYILMADI ve 8 counted
skip'in İÇİNDE DEĞİLLER. Bu skip'ler, Foundation'ın kendi LOCK'u
için TEK BAŞINA bloklayıcı SAYILMADI (çekirdek altyapı — grant/authz/
kilit/journal/identity/staging/publish/pointer/reconciliation/CLI/
closure — gerçek PostgreSQL + gerçek filesystem ile tam kanıtlı;
faiss'e dokunan alt yollar bu slice'ın kapsamında hiçbir zaman koşmaz,
çünkü corpus population zaten bilinçli olarak ertelenmiştir). **BU
YÜK TAŞIYAN, ertelenemez bir kapı olarak kayda geçirilir**: production
corpus population VEYA retrieval-dependent Slice 2'den ÖNCE ZORUNLU
açılış maddesi — (a) faiss/numpy kurulu bir makinede bu 4 skip'li
testin gerçekten koşulması, (b) gerçek, küçük bir synthetic corpus,
(c) gerçek bir build→publish→activate→load_pinned_bundle→retrieve
round-trip'i, (d) FAISS serialize/deserialize API uyumluluğunun
doğrulanması (`np.frombuffer`'ın read-only array döndürmesi bazı
faiss sürümlerinde `deserialize_index` için sorun olabilir — bu
ortamda ne kanıtlanabildi ne çürütülebildi, dürüst açık risk), (e)
embedding dimension/count doğrulaması.

**Scope dışı işler** — Production mevzuat corpus population;
production içtihat corpus population; corpus provenance/lisans/
güncelleme politikası; Row 10/11 `rag_index_version_used` şema
yaması; retrieval/discovery-dependent Slice 2 (ROW 19C-3c-iv Slice
2); GC/retention/delete yüzeyleri; `rag.py`/`evaluation*`'ın pinleme
API'sine adaptasyonu; streaming/incremental büyük-corpus build
varyantı; `global:deadline_rules`/`global:legal_provisions` gibi
diğer global-resource aileleri; Row 19D — Operations & Recovery
(OS-level hardening, OS ACL, service identity, TOCTOU, advisory-lock
timeout backlog'u dahil).

**LOCKED-file §9 gerekçeleri** — `src/ingest.py`: import-hijyeni +
pure-build/frozen-bytes seam + `__main__` kapanışı için açıldı.
Gerekçe: kullanıcı talebi (Bundle Foundation ACTIVE/NEXT) + security
(bu dosya, koordinatörsüz, import-anı-credential'lı, non-atomik TEK
global writer'dı — Row 19A'nın 17-maddelik gap'inin ana kaynağı) +
downstream entegrasyon (coordinator'a bağlama). Risk: repo'nun en
büyük tek-dosya müdahalesi (3017 satır, import-yan-etkili) —
azaltım: chunk/embedding domain fonksiyon gövdelerine dokunmadan
seam ekleme, deterministic frozen-bytes testleri, gerçek-OS-
subprocess refusal kanıtı. `src/retriever.py`: reader-pinleme API'si
+ module-level yük kaldırma için açıldı. Gerekçe: Row 19A'nın
"okuyucu tek versiyon pinler" kuralının TEK uygulanma yeri; security
(import-anı credential/index yükünün kaldırılması). Risk:
`bundle=None` fail-closed davranışı `rag.py`/`evaluation*`'ın legacy
doğrudan çağrılarını kırar — tam etki envanteri disclose edildi ve
kullanıcı kararı #5 ile AÇIKÇA kabul edildi; `rag.py`/`evaluation*`
bilinçli olarak DOKUNULMADAN (EXCLUDED) bırakıldı, fail-closed sonuç
kabul edilen bedeldir. `ui/cli_mutate.py` / `ui/reconciliation_
operator.py`: yalnız additive (5. `rag-bundle` subcommand'ı; 9.
merge kaynağı) — her önceki slice'ın (19C-3b'den beri) kabul edilmiş
AYNI açılış sınıfı; risk düşük (mevcut registry'de exact-set
assertion'ı yoktu — kaynak-grep'le doğrulandı). Migration/test
dosyaları: `db/migrations/0005` yalnız additive (0001-0004 bayt-
düzeyinde untouched); dört integration-postgres dosyası +
`test_reconciliation_operator_isolated.py` yalnız kendi `==47→==49`
registry-sayım assertion'ları için mekanik güncellendi (hiçbir
assertion gevşetilmedi); `test_cli_mutate_isolated.py`/
`test_rag_bundle_mutation_facade_isolated.py`/`test_rag_bundle_
mutation_integration_postgres.py` remediasyonun T1-T22 test matrisini
additive olarak aldı — hem implementer hem AYRI Fable
yeniden-incelemesi hiçbir mevcut assertion'ın kaldırılmadığını/
gevşetilmediğini bağımsız doğruladı.

**Final verdict**: `RAG BUNDLE FOUNDATION LOCK-READY — F1-F4 CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/
19C-3a Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii/
19C-3c-iii/19C-3c-iv Slice 1 örneğinde olduğu gibi yalnız
`CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### RAG Real-Dependency Validation + Synthetic E2E Gate (DONE / LOCKED — checkpoint özeti)

**Preflight ve exact scope** — Başlangıç HEAD:
`84117d6ff0b2ab2e6c3d63eb619a07ac1ad08a1a`. Exact değişiklik: **1
YENİ** dosya (`ui/tests/test_rag_bundle_dependency_smoke.py`), **0
DEĞİŞTİRİLMİŞ**, **0 migration**, **0 production dosyası**;
`CLAUDE.md` bu implementasyon/inceleme/remediasyon/re-review
turlarının HİÇBİRİNDE değişmedi — bu checkpoint'in kendisi ilk
yazım anıdır. Test modülü sayısı **63 → 64**; routing key (49),
logical family (37), migration (5), kapalı mutasyon giriş noktası
(29), refusal senaryosu (44) bu slice'ta DEĞİŞMEDİ.

**Gerçek dependency gate** — Root `.venv` (Python **3.14.4**)
üzerinde gerçek import + metadata doğrulamasıyla altı paketin
TAMAMI kendi `requirements.txt` pin'iyle birebir ve "ok_pinned":
`faiss-cpu` **1.15.0**, `numpy` **2.5.2**, `pypdf` **6.16.2**,
`openai` **3.6.0**, `python-dotenv` **1.2.3**, `httpx2` **2.12.0**.
`anthropic` **1.2.0** yalnız INFORMATIONAL olarak raporlanır — gate
koşuluna GİRMEZ (build→activate→load→retrieve zinciri anthropic'i
hiç import/çağırmaz). Paketin dist-info/`pip`'te "kurulu"
görünmesi TEK BAŞINA yeterli kabul EDİLMEDİ — gate her paket için
GERÇEK `importlib.import_module()` probe'u + gerçek sürüm
karşılaştırması çalıştırır (`classify_package()`/
`decide_gate_outcome()`, saf ve enjekte edilebilir fonksiyonlar).
`require` modunda eksik/kırık/sürüm-uyumsuz bir paket **skip
DEĞİL, FAIL**tir — bu, `vergi_ui_runtime` interpreter'ında (altı
paketin altısı da gerçekten kurulu değil) `require` ile
çalıştırılan bağımsız bir koşuda **6 gerçek, SAYILAN FAILURE**
(paket başına exact `ModuleNotFoundError`), 0 informational skip,
marker YOK sonucuyla AMPİRİK olarak kanıtlanmıştır. `developer`
(env değişkeni unset) ve geçersiz env-değeri davranışları AYRI
sınandı: developer modunda bağımlılıklar mevcutken require ile
AYNI tam E2E'yi çalıştırır (disclose edilmiş, sözleşmeyle uyumlu);
bağımlılık eksikken yalnız informational skip verir, hard-fail
ÜRETMEZ; geçersiz bir env değeri ise ortamdan BAĞIMSIZ olarak
fail-closed reddedilir (tek FAIL, "unknown" çıktıda, sıfır PASS
marker). Bu gate, corpus population ve RAG-bağımlı Slice 2'den
ÖNCE **zorunlu bir açılış kapısıdır** — o iki faz `require` modunda
bu gate'in GERÇEKTEN PASS ettiği bir ortam gerektirir.

**Gerçek sentetik E2E** — Test, gerçek production zincirini uçtan
uca sürer: gerçek, bayt-hesaplı sentetik PDF'ler → gerçek `pypdf`
extraction (`ingest.extract_pdf_pages`, facade'in koşulsuz sabittiği
`pdf_page_extractor=None` üzerinden — bypass EDİLEMEZ) → gerçek
`openai.OpenAI` SDK'sı + `httpx2.MockTransport` (SDK'nın gerçek
base64-encoded embedding decode yolu dahil) → gerçek
`faiss.IndexFlatIP` add/search/serialize/deserialize → gerçek public
`facade.apply_build/apply_activate` + `retriever.load_pinned_bundle/
retrieve_detailed` build→publish→activate→load→retrieve zinciri →
doğru source/citation attribution (döndürülen kaydın document_id/
source/madde alanları) → tamper-before-deserialize reddi
(`RagArtifactHashMismatchError`, hash doğrulaması faiss import'undan
dahi ÖNCE) → önceki pin edilmiş bundle'ın devamlılığı (pointer
ikinci bundle'a geçtikten SONRA bile eski in-memory pin doğru
çalışır) → içerik olarak GERÇEKTEN ayırt edilebilir ikinci bir
corpus + bundle #2 retrieval'i (GAMMA sentinel'i yalnız bundle
#2'de). **Bu sentetik E2E gerçek mevzuat corpus population'ı
ANLAMINA GELMEZ** — corpus, iki/üç sentetik, tek-sayfalık, tamamen
programatik PDF'ten ibarettir; production `data/mevzuat/` içeriği bu
gate'in hiçbir turunda okunmadı/kullanılmadı.

**Dürüst kronoloji (dört ayrı aşama, karıştırılmadan)**:

1. **İlk implementasyon** — tek yeni test dosyası; root `.venv`
   `require`: **55 passed / 0 failed / 0 skipped**; ilk full suite:
   **64 modül, 3672 passed / 0 failed / 8 counted skipped**; verdict
   `RAG REAL-DEPENDENCY VALIDATION + SYNTHETIC E2E GATE IMPLEMENTATION READY FOR INDEPENDENT VERIFICATION`.
2. **İlk bağımsız Fable incelemesi** — production çekirdeğinin
   (gerçek pypdf/OpenAI-SDK-base64/FAISS zinciri, fail-closed
   env-var sözleşmesi, sıfır network, data/index bayt-değişmezliği,
   64-modül sweep) sağlam bulunduğu; ANCAK F1 (MEDIUM) ve F2
   (MEDIUM) nedeniyle `NOT LOCK-READY` verdict'i.
3. **Dar remediasyon** — yine yalnız AYNI tek test dosyasında; F1/F2
   düzeltmeleri; root `.venv` require/developer: **72 passed / 0
   failed / 0 skipped**; 64-modül sweep'in yeniden başarıyla
   geçtiği (64/64 exit 0, 3672 passed, 0 failed, 8 counted skipped);
   bu turda commit/roadmap-lock YAPILMADIĞI; verdict
   `RAG REAL-DEPENDENCY VALIDATION + SYNTHETIC E2E GATE TARGETED REMEDIATION READY FOR INDEPENDENT RE-REVIEW`.
4. **Ayrı, bağımsız Fable yeniden incelemesi** — F1/F2'nin kaynaktan
   + bağımsız enstrümantasyon/tanılarla KAPANDIĞININ doğrulanması;
   root `.venv` require/developer **72/0/0**; fresh disposable
   PostgreSQL 16 (migration 0001-0005) ile **64/64 modül exit 0**,
   **3672 passed / 0 failed / 8 counted skipped** (informational/
   `SKIPPED` satırları — 11 informational + 1 ayrı sayaç-dışı satır —
   bu 8 counted skip tabanına KARIŞTIRILMADI); bağımsız 113-dosyalık
   `data/`+`index/` sha256 manifesti inceleme başı/sonu IDENTICAL;
   sıfır gerçek dış network (bağımsız `sys.addaudithook` netguard
   ledger'ı) ve sıfır `.env`-open olayı; final verdict:
   `RAG REAL-DEPENDENCY VALIDATION + SYNTHETIC E2E GATE LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`.

**İlk yeşil koşunun (aşama 1) tek başına LOCK sağlamadığı açıkça
kaydedilir** — LOCK yalnız aşama 4'ün bağımsız, kaynak-kanıtlı
re-review'undan sonra verilmiştir.

**F1 kapanışı** — İlk kusur: `query()` closure'ı `bundle_1`'i
kalıcı olarak yakalıyordu; "post-second-activation: retrieval
against bundle #2 still correct" etiketli kontrol GERÇEKTE yine
bundle #1 üzerinde koşuyordu; iki build'in artifact'leri byte-
identical olduğundan bu yanlış-bundle kullanımı sonuç eşitliğiyle
GÖRÜNMEZ kalıyordu. Remediasyon: `query()` artık `bundle`'ı
zorunlu, açık ikinci parametre olarak alır (hiçbir closure-yakalanan
bundle KALMADI); build #2'nin corpus'u GERÇEKTEN içerik olarak
farklı yapıldı (üçüncü bir PDF, GAMMA sentinel'i, `ntotal` 2→3,
farklı artifact hash'leri); bundle #2 GERÇEKTEN kendi benzersiz
içeriğiyle sorgulanıp doğrulandı; ESKİ `bundle_1` nesnesi pointer
swap'tan SONRA yeniden sorgulanıp hem doğru çalıştığı hem GAMMA'yı
ASLA döndürmediği ayrıca kanıtlandı. Bağımsız re-review'un KENDİ
enstrümantasyonu (retrieval çağrılarını kayıt altına alan bir
tanı) yedi retrieve çağrısının iki bundle versiyonunu doğru sırayla
ayırt ettiğini, GAMMA'nın yalnız bundle #2'den geldiğini ve eski
pin'in GAMMA sorgusunda dahi sıfır gamma-hit döndürdüğünü bağımsızca
doğruladı. **F1: CLOSED.**

**F2 kapanışı** — İlk kusur: `DEPENDENCY GATE: PASS` marker'ı,
koşunun SON zorunlu kontrolü olan `data/`/`index/` bayt-değişmezlik
kontrolünden ÖNCE basılıyordu; bu yüzden invariance'ı İHLAL EDEN,
exit-1 ile biten bir koşu stdout'ta yanıltıcı bir PASS marker'ı
taşıyabiliyordu. Remediasyon: marker artık YALNIZ `run_self_test()`
sonunda, final invariance kontrolü VE özet satırından SONRA, ve
YALNIZ TOPLAM `failed == 0` şartıyla basılıyor. Bağımsız re-review'un
KENDİ zorlanmış-ihlal child süreç tanısı bunu ampirik olarak
doğruladı: gerçek E2E TAMAMEN başarılı (64 PASS satırı, tamper testi
dahil) → yalnız SON, zorlanmış bir final-invariance kontrolü FAIL →
exit code 1 → `DEPENDENCY GATE: PASS` alt-dizgesi çıktının HİÇBİR
yerinde yok. Bu senaryo artık kalıcı, gerçek bir `subprocess.run`
meta-testi olarak repoda korunmaktadır. **F2: CLOSED.**

**Network ve güvenlik** — `httpx2.MockTransport` dışına SIFIR gerçek
dış network girişimi; bu, testin kendi socket-guard'ından TAMAMEN
AYRI, bağımsız bir `sys.addaudithook` netguard/ledger mekanizmasıyla
her koşuda (require/developer/invalid-value/64-modül sweep) ayrıca
kanıtlandı — sweep'teki TEK gözlenen ağ olayları yerel loopback
PostgreSQL/TestClient trafiğidir. Gerçek OpenAI/Anthropic API
credential'ı HİÇBİR ZAMAN kullanılmadı; `.env` HİÇBİR koşuda
açılmadı (sıfır `.env`-open olayı, bağımsız ledger'la kanıtlı).
`data/` ve `index/` bu gate'in hiçbir turunda (implementasyon,
inceleme, remediasyon, re-review) değişmedi — her tur kendi
bağımsız bayt-manifestiyle bunu doğruladı. Artifact tamper
doğrulaması (`RagArtifactHashMismatchError`) her zaman
`faiss.deserialize_index`'ten ÖNCE koşar.

**Kalan Low/Observation (bloklamayan, backlog)** — Bağımsız
re-review'un final bulgu tablosundan: **N1** — F2'nin PARENT-modda
basılan meta-test check etiketi ("…no DEPENDENCY GATE: PASS marker
anywhere in output") marker literal'ini alt-dizge olarak içerir;
tam-satır marker tekil ve doğru kalır, ama naif bir alt-dizge
tüketicisi bu etiket satırından YANILABİLİR. **N2** — F2 meta-
testinin parent assertion'ları child E2E'sinin başarısını AYRICA
pinlemez (özet "≥1 failure" yeterli sayılır). **N3** —
`VERGI_RAG_DEPENDENCY_GATE_CHILD=1` iki subprocess meta-testini
sessizce atlar (recursion önleme; fail-open DEĞİL, ama belgelenmiş
davranış). **L1** (miras, bilinçli scope-dışı) — `requirements.
txt`'te bulunmayan bir pin, sürüm doğrulaması sessizce atlanıp
`ok_pinned` üretir; bugün altı paketin altısı da pinli olduğundan
tetiklenmiyor. **L2** (miras, bilinçli scope-dışı) — mekanik bir
`DEPENDENCY GATE: FAIL` marker satırı yoktur; FAIL, `FAIL …`
satırları + özet + exit code ile taşınır. Bunların HİÇBİRİ LOCK'u
ENGELLEMEZ; hepsi açık backlog olarak korunur.

**Kalan gerçek kapılar (bu checkpoint HİÇBİRİNİ açmaz/başlatmaz)**:

- Row 10/11 legal-research/case-law şema yaması (ayrı, salt-okunur
  exact-scope/allowlist reconciliation gerektirir — bkz. §5 pointer).
- Corpus politikası (kaynak/provenance/lisans/güncelleme).
- Corpus edinimi (acquisition) — gerçek mevzuat/içtihat PDF/metin
  edinimi.
- Corpus population — `data/mevzuat/`+`documents.json`'a gerçek
  içerik yüklenmesi.
- Bundle activation için gerçek production corpus.
- Legal Research/Case Law RAG-bağımlı Slice 2 (ROW 19C-3c-iv Slice
  2 — Retrieval/Discovery-Dependent Generation).
- `rag.py`/Anthropic gerçek agent adaptasyonu (pinlenmiş bundle
  API'sine geçiş).
- GC/retention/maintenance işleri.
- Row 19D (deployment/OS hardening, OS ACL/service identity, TOCTOU
  dahil).
- Production deployment.

**§9/LOCKED-file değerlendirmesi** — Bu gate implementasyonunda,
incelemesinde, remediasyonunda ve re-review'unda **hiçbir LOCKED
production dosyası değiştirilmedi** — tek değişen dosya, hiçbir
zaman git'e commit edilmemiş, tamamen yeni bir test dosyasıdır
(`ui/tests/test_rag_bundle_dependency_smoke.py`); Row 1-18, Row
19A-19C ve RAG Global-Resource Bundle Foundation'ın hiçbir
kaynak/şema/migration dosyasına dokunulmadı. Bu `CLAUDE.md`
değişikliği, yukarıdaki dört aşamanın TAMAMLANMIŞ ve bağımsız
doğrulanmış sonucunu kaydetmek için, ayrı ve açık kullanıcı yetkili
bu roadmap-lock turunda yapılmıştır — implementasyon/inceleme/
remediasyon/re-review turlarının HİÇBİRİ `CLAUDE.md`'ye
dokunmamıştır.

**Final verdict**:

`RAG REAL-DEPENDENCY VALIDATION + SYNTHETIC E2E GATE LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/
19C-3a Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii/
19C-3c-iii/19C-3c-iv Slice 1/RAG Global-Resource Bundle Foundation
örneğinde olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur
bir roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Row 10/11 Legal Research + Case Law Schema Patch (DONE / LOCKED — checkpoint özeti)

**A. Exact scope** — Kullanıcı tarafından ayrıca onaylanmış tam dosya
allowlist'i üzerinde implement edildi: **0 YENİ + 8 DEĞİŞTİRİLMİŞ = 8
dosya**.

1. `data/case_legal_research.schema.json`
2. `data/case_case_law.schema.json`
3. `src/legal_research_discovery.py`
4. `src/case_law_discovery.py`
5. `src/legal_research_validator.py`
6. `src/case_law_validator.py`
7. `ui/tests/test_legal_research_engine_isolated.py`
8. `ui/tests/test_case_law_engine_isolated.py`

**0 migration**; **0 production data rewrite** (`case_0001`
regeneration/reapproval GEREKMEDİ); **0 UI/web/CLI değişikliği**;
**0 facade/adapter/coordinator değişikliği**
(`ui/services/legal_research_case_law_mutation_facade.py`/
`..._adapters.py` DOKUNULMADI); **0 engine-orchestrator değişikliği**
(`src/legal_research_engine.py`/`src/case_law_engine.py` DOKUNULMADI);
**0 yeni test modülü** (64 kaldı, yalnız 2 mevcut modül genişletildi).

**B. Schema sözleşmesi** — Legal Research
(`data/case_legal_research.schema.json`): title `"...Schema V1.1"`
(kozmetik, `"...Schema V1"`den); `schema_version` `const` **1**
(DEĞİŞMEDİ); `rag_index_version_used` YALNIZ `$defs.research_candidate.
properties`'e eklendi; `research_candidate` required **21** (DEĞİŞMEDİ),
properties **21 → 22**. Case Law (`data/case_case_law.schema.json`):
title `"...Schema V2.1"`; `schema_version` `const` **2** (DEĞİŞMEDİ);
alan `$defs.coverage_record.properties` VE `$defs.decision_candidate.
properties`'e eklendi; `coverage_record` required **13**/properties
**13 → 14**; `decision_candidate` required **21**/properties
**21 → 22**; `agent_suggestion` required/properties **11/11 —
DOKUNULMADI**, alan orada YOK. Exact tip/pattern: `type:
["string","null"]`, `pattern: "^v_[0-9a-f]{64}$"` (`src/retriever.py`'nin
`_BUNDLE_VERSION_PATTERN`'iyle birebir); **hiçbir konumda `required`'a
eklenmedi**; top-level veya `analysis_metadata` alanı DEĞİLDİR (her iki
şemada da `analysis_metadata` bulunmaz — bu patch onu da eklemedi).

**C. Absent/null/value semantiği** — **absent**: patch-öncesi kayıt
VEYA kaydın üretim yolu yapısal olarak retrieval'a hiç dokunmaz (Legal
Research `provision_resolution`/`agent_suggestion` tipli kayıtlar).
**null**: retrieval-yetenekli yol, ama gerçekten pinlenmiş bir bundle'a
karşı başarılı retrieval kanıtı YOK (`retrieval_not_run`,
`retrieval_failed`). **`v_<64 lowercase hex>`**: gerçekten kullanılan,
immutable, content-addressed bundle kimliği
(`retriever.PinnedRagBundle.bundle_version`). Path, URL, `current`,
legacy flat-index adı, boş string ve her türlü sentinel/boş-liste
kodlaması şema `pattern`'i tarafından YASAKTIR.

**D. Discovery davranışı** — Dört builder additive keyword-only/
default-`None` sözleşmesiyle genişletildi: `legal_research_discovery.
build_execution_state_candidate()`, `build_discovery_candidate()`;
`case_law_discovery.build_coverage_record()`, `build_decision_record()`
(`retrieved_chunk_id=None` ikizinin hemen yanına, aynı desende).
Bugünkü sonuç: coordinated Legal Research'te (`use_discovery=False`
sabit) alan HİÇ görünmez (absent); coordinated Case Law coverage
kayıtlarında alan `null` olarak açıkça belirir; `retrieval_not_run`/
`retrieval_failed` yollarında `null`; agent suggestion kayıtlarında
absent (LR: agent allowlist alanı hiç taşımaz; CL: `$def`'te alan hiç
tanımlı değil). Gerçek bundle pinleme (`bundle=` kablolaması) bu
patch'te AÇILMADI — Slice 2'nin işi. `LEGAL_RESEARCH_ENGINE_VERSION`/
`CASE_LAW_ENGINE_VERSION` ve `*_DISCOVERY_VERSION` sabitleri BUMP
EDİLMEDİ — bu bilinçli bir karardır: additive-null çıktı-şekli
değişikliği identity'ye görünmezdir ve hiçbir replay/reconciliation
yolu builder'ı yeniden çağırmadığından bump'sızlık identity churn'ü
ÖNLER.

**E. Validator kuralları** — Legal Research: alan mevcut VE non-null
⇒ `research_type == "issue_driven_discovery"` VE `finding_status ∉
{retrieval_not_run, retrieval_failed}`
(`validate_rag_index_version_consistency()`,
`legal_research_validator.py`). Case Law coverage: alan mevcut VE
non-null ⇒ `execution_state ∈ {retrieval_completed,
no_case_law_evidence}`
(`validate_rag_index_version_consistency_for_coverage()`,
`case_law_validator.py`). Case Law decision: bu patch'te YALNIZ schema
`pattern` uygulanır — coverage↔decision bundle-değer eşitliği çapraz
kontrolü Slice 2'ye ERTELENDİ, bu patch'te İCAT EDİLMEDİ. Agent
suggestion içinde alan (Case Law) `additionalProperties: false`
nedeniyle şema katmanında reddedilir — hiçbir runtime kontrolü
gerekmez.

**F. Geriye uyumluluk** — Eski canonical/pending/history/review
kayıtları (alan hiç yokken) patched şemada değişmeden geçerli kalır.
QA'nın canlı schema-validation baseline'ı (`qa_engine.py --self-test`)
temiz kaldı. QA'nın `analysis_metadata` dependency manifest'i şema
dosyalarını İZLEMEDİĞİNDEN (yalnız 11 scope artefaktı + `case.json` ham
baytlarını izler) canonical `qa.json` bu patch'le stale OLMADI.
Mevcut journal replay/pending SHA davranışı ETKİLENMEDİ (facade
`_build_identity_payload`'ın 7 anahtarı business-şema alanı okumaz).
Production case dosyaları (`case_0001` dahil) DEĞİŞMEDİ. JSON Schema
DOKÜMAN revizyonu (title V1.1/V2.1) ile artifact `schema_version`
kontratı (const 1/2, DEĞİŞMEDİ) arasındaki ayrım
(`data/documents.schema.json`'ın "V2.1 title + const 1" precedent'iyle
tutarlı) KORUNDU.

**G. Test kanıtı** — Implementer turu (yalnız implementer'ın kendi
koşusu): LR validator **16/16**, CL validator **17/17**, LR
engine-isolated **50/50**, CL engine-isolated **57/57**, QA **13/13**,
LR/CL mutation facade **55/55**; fresh disposable PostgreSQL 16
(migration 0001-0005) ile **64/64 test modülü exit 0, 3686 passed, 0
failed, 8 counted skipped** (8'i önceden bilinen, bu patch'le ilgisiz
POSIX-symlink alt-testleri; yeni counted skip EKLENMEDİ).

Bağımsız Fable final incelemesi (AYRI, kendi ölçümü — implementer
sonuçlarıyla KARIŞTIRILMAZ): repo-dışı, testlerden bağımsız bir
diagnostic ile **47/47** bağımsız kontrol (saf `jsonschema` +
GERÇEK production validator/discovery/policy/agent modülleri); aynı
hedefli test sonuçlarının bağımsız yeniden-koşusu (LR validator 16/16,
CL validator 17/17, LR engine 50/50, CL engine 57/57, QA 13/13,
LR/CL facade 55/55 — implementer'ınkiyle birebir); kendi, AYRI, fresh
disposable PostgreSQL 16 kümesiyle **64/64 modül exit 0, 3686 passed,
0 failed, 8 counted skipped** (implementer sayısıyla birebir, bağımsız
üretildi); bağımsız bir `sys.addaudithook` netguard ile **0 external
network, 0 `.env` open**; korunan `data/cases/**`/`index/**`/
`db/migrations/**`/`CLAUDE.md`/`documents.json`/`provisions.json` raw
byte-manifestlerinin inceleme başı/sonu **byte-identical** kaldığı;
disposable PostgreSQL/temp residue'nun tam temizlendiği.

**H. Scope/Fable kronolojisi** — Sonnet oturumu + dört salt-okunur,
karşılıklı-kör araştırma alt ajanı (Schema/Version;
Producer/Consumer/Call-Site; Identity/Compatibility/Security;
Tests/Counts/Allowlist) salt-okunur bir scope DRAFT hazırladı; her
yük-taşıyan iddia koordinatör tarafından kaynaktan bağımsızca
yeniden doğrulandı. Taslağın erken, daha az disiplinli keşif
turlarının önerdiği farklı bir alan adı (`rag_bundle_version`) ve
breaking bir `schema_version` bump önerisi, `CLAUDE.md`'nin kendi
bağlayıcı metniyle (exact alan adı `rag_index_version_used`,
"geriye-uyumlu" zorunluluğu) çelişerek ana ajan tarafından
kaynak-kanıtlı olarak reddedildi. Ayrı bir Fable scope review üç
düzeltme uyguladı: (1) validator consistency check "opsiyonel" →
"zorunlu"ya yükseltildi (koşullu allowlist yasağı + Legal Research'in
tek `$def`'i gerekçesiyle); (2) "64 test dosyasının hiçbiri
değişmeyecek" iddiası, yeni sözleşmenin kalıcı kanıtının bir yerde
YAŞAMASI gerektiği gerekçesiyle düzeltilerek allowlist'e 2 engine-test
dosyası eklendi; (3) "şema suite'inde ilk optional property olur"
iddiası, `case_document.schema.json`/`case_view.schema.json`'da
ZATEN var olan optional-property örnekleri bulunarak yanlışlandı
(tasarım sonucunu DEĞİŞTİRMEDİ). Allowlist bu üç düzeltmeyle **8
koşulsuz MODIFIED dosyaya** kapatıldı. İmplementasyon, tek yazıcı bir
Sonnet oturumuyla, bu exact 8-dosyalık allowlist üzerinde yapıldı.
Bağımsız Fable final review (ayrı bir Fable oturumu, session
kesintisi sonrası kaldığı yerden devam ettirilerek) **hiçbir
blocking bulgu** raporlamadı.

**I. Sayaçlar** — Test modülü: **64 → 64** (değişmedi). Merged
reconciliation registry routing key: **49 → 49** (değişmedi). Logical
action family: **37 → 37** (değişmedi). Kapalı mutasyon giriş
noktası: **29 → 29** (değişmedi). Refusal senaryosu: **44 → 44**
(değişmedi). Migration: **5 → 5** (değişmedi). Legal Research
`schema_version`: **1** (const, değişmedi). Case Law `schema_version`:
**2** (const, değişmedi).

**J. Remaining observations** (bloklamayan, dürüstçe kaydedildi) —
**O1**: Case Law `decision_candidate` için semantic consistency çapraz
kuralı YOK (yalnız şema `pattern`); coverage↔decision bundle-değer
eşitliği Slice 2'nin tasarım sorusu olarak bilinçli bırakıldı — bugün
gerçek retrieval yapısal olarak kapalı olduğundan pratik erişilemez.
**O2**: Alan `optional` (required-dışı) olduğundan, Slice 2'nin
"retrieval gerçekten koştuysa alan non-null olmalı" application-
katmanı zorunluluğu gelene kadar retrieval-türevi bir kayıt teorik
olarak sessizce null yazılabilir — bugün coordinated yolda RAG yapısal
olarak kapalı ve legacy yol fail-closed `retrieval_failed`'a düştüğü
için bu durum ULAŞILAMAZ; açık kayıt, Slice 2 kapısına yazılı. **O3/
O4**: Bağımsız incelemenin netguard ledger'ında önceki bir session'dan
kalan, tamamen loopback-only (127.0.0.1) bir kalıntı blok bulundu —
sonuç üzerinde SIFIR etkisi vardı, salt-scratchpad hijyen notu. Önceden
bilinen, bu patch'le İLGİSİZ backlog maddeleri (`case_law_engine.py`
8-key vs `case_law_approval.py` 7-key forbidden-key drift'i;
`documents.schema.json`'ın `daire`/`karar_no` boşluğu) DOKUNULMADAN
kaldı.

**K. Slice 2'ye kalan dört bağlayıcı yükümlülük** — (1) pinlenmiş
`bundle_version`'ın coordinator `identity_payload`/`input_digest`'e
bağlanması; (2) retrieval gerçekten koştuysa `rag_index_version_used`
alanının non-null olması application-katmanı zorunluluğu; (3)
canonical `rag_index_version_used` değeri ile coordinator journal/
audit'in bundle kimliğinin DOĞRUDAN eşitlik kontrolü; (4) discovery
çağrılarına verified/pinned `bundle=` kablolaması
(`legal_research_discovery.py`/`case_law_discovery.py`'nin retrieval
çağrıları bugün `bundle=` GEÇMİYOR). Citation/chunk/page/excerpt
ayrıntıları (Legal Research `research_candidate`'a henüz eklenmemiş
provenance zenginleştirmesi dahil) da Slice 2'ye KALIR — bu patch'in
bağlayıcı taahhüdü tek bir alanla ("hangi bundle kullanıldı?")
sınırlıdır.

**L. §9 LOCKED-file gerekçesi** — `data/case_legal_research.schema.json`
(Row 10 + 19A ayrı-onay maddesi): patch'in doğrudan nesnesi; salt
additive optional property + kozmetik title; geriye uyumluluk mükemmel
(eski veri değişmeden geçerli). `data/case_case_law.schema.json`
(Row 11 + 19A): aynı, iki `$defs` konumunda. `src/legal_research_
discovery.py` (Row 10): retrieval sonucuna erişen TEK Legal Research
katmanı — checkpoint'in "ilgili LOCKED engine'ler" taahhüdünün
çözümü; mevcut dönüş dict'lerine 1 yeni anahtar (bugün her yolda
`None`), imza kırılması yok, tüm çağıranlar `dict()` pass-through
üzerinden değişmeden çalışmaya devam eder. `src/case_law_discovery.py`
(Row 11): aynı gerekçe, `retrieved_chunk_id=None` precedent'inin
birebir eşi. `src/legal_research_validator.py` (Row 10): non-null'un
yanlış bağlamda TEK reddedicisi (fail-closed, Prensip 9); mevcut hiçbir
check gevşetilmedi/kaldırılmadı; kalıcı, non-tautological kanıtın
evi. `src/case_law_validator.py` (Row 11): aynı. `ui/tests/
test_legal_research_engine_isolated.py` ve `ui/tests/
test_case_law_engine_isolated.py`: yeni sözleşmenin producer-side
kalıcı kanıtı (round-trip + sentetik bundle-injection + gerçek
`case_0001` canonical regresyonu); yalnız additive check'ler, hiçbir
mevcut assertion gevşetilmedi/kaldırılmadı.

Bunların DIŞINDA hiçbir LOCKED dosya bu patch'te açılmadı. Özellikle
DEĞİŞMEYENLER: `legal_research_engine.py`, `case_law_engine.py`
(engine-orkestratörler), iki policy, iki agent, iki approval, `ui/
services/legal_research_case_law_mutation_facade.py`/`..._adapters.py`
(facade/adapters), Layer A facade/adapters/`approval_registry.py`,
`ui/cli_mutate.py`, `ui/reconciliation_operator.py`, `ui/main.py`
(CLI/UI), tüm `ui/templates/**`, `qa_*`/`orchestrator_*`,
`retriever.py`, `ingest.py`, `db/migrations/*.sql` (tüm 5 migration),
tüm `data/` production case verisi.

**M. Kalan işler** — Başlamamış ve bu checkpoint ile
YETKİLENDİRİLMEMİŞTİR: corpus politikası (kaynak/provenance/lisans/
güncelleme); corpus edinimi (acquisition); gerçek mevzuat/içtihat
yüklenmesi; corpus population (`data/mevzuat/`+`documents.json`'a
gerçek içerik); production RAG bundle'ının build/activation'ı (gerçek
corpus'a karşı); RAG-bağımlı Slice 2 (ROW 19C-3c-iv Slice 2 —
Retrieval/Discovery-Dependent Generation); citation/chunk/page/excerpt
provenance genişletmesi; `rag.py`/Anthropic gerçek agent adaptasyonu
(pinlenmiş bundle API'sine geçiş); GC/retention/maintenance devam
işleri; global-resource maintenance authz/capability/lock modeli; Row
19D (Operations & Recovery — deployment/OS hardening, OS ACL/service
identity, TOCTOU dahil); production deployment.

**Final verdict**: `ROW 10/11 LEGAL RESEARCH + CASE LAW SCHEMA PATCH LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/
19C-3a Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii/
19C-3c-iii/19C-3c-iv Slice 1/RAG Global-Resource Bundle Foundation/
RAG Real-Dependency Validation + Synthetic E2E Gate örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına
dokunmaz.

### RAG Corpus Policy Foundation (DONE / LOCKED — checkpoint özeti)

**A. Preflight ve exact scope** — Başlangıç HEAD
`6492500405b06ddd5647cde49074cc984edfec26`; branch `claude-dev`; staged set
boş; `stash@{0}` ("quarantine unexpected post-Row19C-2a late writes")
dokunulmamış. Onaylı exact allowlist **4 YENİ + 8 DEĞİŞTİRİLMİŞ = 12
dosya**: YENİ (4) — `data/corpus_policy.schema.json`,
`data/corpus_policy/corpus_policy.json`, `src/corpus_policy_validator.py`,
`ui/tests/test_corpus_policy_validator_isolated.py`. DEĞİŞTİRİLMİŞ (8) —
`src/ingest.py`, `src/manifest_validator.py`,
`src/provision_manifest_validator.py`,
`ui/services/rag_bundle_mutation_facade.py`,
`ui/tests/test_rag_bundle_builder_isolated.py`,
`ui/tests/test_rag_bundle_mutation_facade_isolated.py`,
`ui/tests/test_rag_bundle_mutation_integration_postgres.py`,
`ui/tests/test_rag_bundle_dependency_smoke.py`. 0 migration; 0 production
corpus içeriği (`data/cases/**`, `data/documents.json`,
`data/provisions.json`, `data/mevzuat/**` dokunulmadı); 0 `index/**`
değişikliği; 0 yeni web/CLI yüzeyi
(`ui/cli_mutate.py`/`ui/reconciliation_operator.py` açılmadı); 0 yeni
action family/routing key; 0 `ui/services/rag_bundle_mutation_adapters.py`
değişikliği (mekanizma seçimi adapter'ı zaten değiştirmeden doğru
bırakıyor); 0 `src/retriever.py` değişikliği (reader-side kontrol gerekçeli
ertelendi). F1/F2 remediasyonunun exact alt-sınırı (12 dosyalık allowlist
İÇİNDE, yeni dosya EKLENMEDEN): yalnız `src/ingest.py`,
`src/manifest_validator.py`,
`ui/tests/test_rag_bundle_builder_isolated.py`.

**B. Policy artefaktı** — `data/corpus_policy.schema.json`: draft 2020-12,
kök VE tüm `$defs`'te (`source_authority_tier`, `document_family_rule`,
`quality_gate`) VE tüm inline root alt-nesnelerinde
`additionalProperties:false`. `schema_version` integer `const:1`;
`policy_id` `const:"vergi_ai_corpus_policy_v1"`; `policy_version` integer
`minimum:1`, monoton. Kök `required` tam 12 kapalı anahtar.
`data/corpus_policy/corpus_policy.json`: `policy_version=1`,
`effective_from="2026-09-14"`. `document_family_rules` **tam 10
belge-ailesi gerçeği** (`belge_turu` enum'uyla birebir,
`documents.schema.json`'dan runtime'da CANLI okunur — ikinci bir tip
sözlüğü icat edilmez): **6 `allowed`** (Kanun, Bakanlar Kurulu Kararı,
Cumhurbaşkanı Kararı, Yönetmelik, Genel Tebliğ, Tebliğ) / **3 `deferred`**
(Sirküler, Özelge, Yargı Kararı — her biri kendi `prerequisites[]`'iyle) /
**1 `prohibited`** (Diğer). Pilot
`temporal_requirements.current_law_only=true`; Tier-1 hedefi
VUK+İYUK+AATUHK; Danıştay/VDDK (`Yargı Kararı`) Phase-2 case-law metadata
şema yaması + anonimizasyon alanları prerequisite'lerinin ARKASINDADIR.
Policy git-governed, static bir registry'dir (`deadline_rules.json` emsali)
— yeni bir mutation-coordinator action family DEĞİLDİR; düzenlenmesi
`CLAUDE.md` §8 onayı + reviewed commit ile olur.

**C. Policy identity ve bundle binding** — Exact zincir: policy dosyasının
ham baytları → `ingest.compute_source_manifest()`'in `{path, sha256,
size_bytes}` kaynak girdisi → `source_digest`/`pre_hash` → `input_digest` →
identity payload → `bundle_version` → build audit → completed replay +
reconciliation doğrulaması → reader'ın (`retriever.load_pinned_bundle`)
`bundle_version` hariç TÜM manifest alanlarını jenerik rehash'lemesi.
Policy hash'i dosyanın KENDİ içine YAZILMAZ (self-reference yok). Ayrı,
adlandırılmış bir identity-core alanı AÇILMADI — policy yalnız mevcut
`source_manifest` girdi listesine bir üye olarak eklendi. Adapter
(`ui/services/rag_bundle_mutation_adapters.py`) ve reader
(`src/retriever.py`) HİÇ DEĞİŞTİRİLMEDİ ve doğru kaldı — ikisi de canlı
`compute_source_manifest()`/jenerik manifest rehash üzerinden policy
girdisini otomatik kapsar. Policy'de TEK BAYT değişikliği (corpus sabit
tutulurken) `source_digest`, `input_digest` VE `bundle_version`'ın üçünü de
değiştirir — bağımsız olarak kanıtlandı. Under-lock policy drift, mevcut
`SourceDriftDetectedError` yolu üzerinden, SIFIR yeni facade kodu ile
yakalanır (`apply_build`'in `_precondition_callback`'i zaten
`_freeze_pre_build_state`'i yeniden çalıştırır).

**D. Build enforcement** — `build_bundle_snapshot()` üç gate'i
chunk/embed/FAISS'ten KESİNLİKLE ÖNCE, sırayla çalıştırır: (1)
`corpus_policy_validator.validate_corpus_policy(raise_on_error=True)`, (2)
`validate_manifest_file(raise_on_error=True)` (artık YENİ admissibility
adımını da içeriyor), (3)
`provision_manifest_validator.validate_provisions_file(raise_on_error=True)`
— bu validator'ın **İLK gerçek otomatik çağrı yolu** (önceden repo
genelinde sıfır çağıranı vardı). Policy/admission ihlalinde: sıfır staging,
sıfır bundle, sıfır audit, sıfır network — her şey yalnız `run_mutation`
tarafından çağrılan `_writer_callback` içinde yaşar, builder dönmeden ona
ulaşılamaz. Belge kapıları: `%PDF` magic-byte (gerçek 5-bayt header
okuması), policy'den okunan max-dosya-boyutu eşiği, cross-document ham-hash
dedup (farklı `document_id`'ler altında byte-identical içeriği yakalar),
provenance-alan-varlığı kontrolü (bugün şemada GERÇEKTEN var olan alanlara
sınırlı). Provision kapıları: temporal-sensitive ailelerde (`verified=True`
+ dolu `valid_from`) en az bir `statute_text`/`amending_law` evidence
zorunluluğu (yalnız `consolidated_legislation` yetmez); aynı
`provision_id`'nin versiyonları arası interval **overlap → ERROR**,
açıklanamayan (>1 gün) **gap → WARNING**. Mevcut 7 gerçek provision
(`verified=False`/`status="unknown"` olan `kanun_6736_m5_f3` dahil) bu yeni
kontrolleri **vacuous-pass** ile geçti — `verified=False` dalındaki önceden
var olan warning davranışı BYTE-DEĞİŞMEDEN korundu, sıfır yeni hata/uyarı
üretildi.

**E. Activation enforcement** — Yeni
`CorpusPolicyDriftError(RagBundleMutationError)`. `apply_activate()`'in HEM
pre-lock HEM under-lock precondition zincirine bir adım eklendi: hedef
bundle'ın `source_manifest`'inde corpus-policy girdisi (a) MEVCUT olmalı,
(b) sha256'sı CANLI, repo-committed
`data/corpus_policy/corpus_policy.json`'ın ham-bayt hash'ine TAM EŞİT
olmalı. Eski-policy, policy'siz, corrupt veya duplicate-entry'li bir bundle
**REDDEDİLİR** — sıfır pointer/journal/audit yazımıyla. Under-lock kontrol,
kilit VERİLDİĞİ ANDA policy dosyası değiştirilerek bağımsızca test edildi
(gerçek disposable PostgreSQL'e karşı): drift yakalandı, pointer yazılmadı,
sıfır `rag_bundle.activate` journal satırı oluştu. Activation identity
payload'ı ve reconciliation adapter'ı DEĞİŞMEDİ — yeni hata sınıfı yalnız
`apply_activate()`'in KENDİ senkron akışında fırlar.

**F. İlk implementasyon kanıtı (Sonnet, ayrı zaman dilimi — SONRAKİ
remediasyon koşusuyla BİRLEŞTİRİLMEZ)** — Fresh disposable PostgreSQL 16 +
migration 0001-0005 + `vergi_ui_runtime` ortamında **65/65 modül exit 0**:
**3785 passed, 0 failed, 8 counted skipped, 11 informational skipped**. 8
counted skip: `test_path_containment_isolated` (4) +
`test_path_containment_module_isolated` (4) — önceden bilinen
Windows-Developer-Mode-kapalı POSIX-symlink precedent'i. 11 informational
skip: `test_rag_bundle_builder_isolated` (3, faiss/numpy
`vergi_ui_runtime`'da yok) + `test_rag_bundle_dependency_smoke` (7, aynı
neden + geliştirici modu) + `test_rag_bundle_reader_isolated` (1, önceden
var olan, bu implementasyonla ilgisiz). Root `.venv`'de
(faiss/numpy/pypdf/openai/dotenv/httpx2 GERÇEKTEN kurulu):
`corpus_policy_validator.py --self-test` **20/20 PASS**;
`test_corpus_policy_validator_isolated` **69/0**;
`test_rag_bundle_builder_isolated` **39/0** (faiss VAR, hiç skip yok);
`test_rag_bundle_mutation_facade_isolated` **148/0**; dependency smoke hem
`developer` hem `VERGI_RAG_DEPENDENCY_GATE=require` modunda **73/0, 0
informational skip**, `DEPENDENCY GATE: PASS`. **Bu ilk yeşil full sweep,
ilerideki bağımsız incelemenin bulduğu F1/F2'yi YAKALAMADI** — testlerin
geçmesi tek başına LOCK için YETERLİ SAYILMADI (bkz. §G).

**G. İlk bağımsız Opus incelemesi** — Açık, dürüst kronoloji: **Fable
haftalık kotası dolduğu için bu turun doğrudan ana bağımsız incelemecisi
Opus olarak kullanıldı**; implementasyon Sonnet tarafından AYRI bir
oturumda yapıldığından model ve bağlam bağımsızlığı korunmuştur; advisor
çağrılmamıştır. Üç bağımsız, birbirine kör, salt-okunur alt-ajan +
koordinatörün kendi doğrudan kaynak incelemesi + altı repo-dışı, sıfırdan
yazılmış diagnostic kullanıldı. **F1 — HIGH**: `src/ingest.py`'nin
sözleşmenin (Fable §L satır 5, §U) açıkça gerektirdiği path-containment
kontrolü hiçbir yerde implement edilmemişti (`grep -n "path_containment"
src/ingest.py` sıfır eşleşme); üç ham join noktası
(`compute_source_manifest()`, `build_bundle_snapshot()`'ın kendi join'i,
`build_document_chunks()`) hâlâ ham `.exists()`/`open()`/`.stat()`
kullanıyordu; gerçek `mklink /J` junction + gerçek absolute-path escape ile
ampirik olarak kanıtlandı — `compute_source_manifest()` root dışındaki bir
kanaryayı GERÇEKTEN okuyup hash'ledi, digest kanaryeninkiyle birebir
eşleşti; ayrıca **gerçek public `preview_build()` API'si** üzerinden,
HİÇBİR validator'dan geçmeden erişilebilir bir arbitrary-file read-and-hash
primitive'iydi. Dosyayı açmanın §9 gerekçesi olarak zaten belirtilen bu
kontrol TESLİM EDİLMEMİŞ ve implementer raporunda AÇIKÇA DİSCLOSE
EDİLMEMİŞTİ. **F2 — MEDIUM**: `src/manifest_validator.py`'nin admission
kontrolü yalnız `"prohibited"`'i reddediyordu; `"deferred"` dalı YOKTU —
gerçek committed policy'ye karşı çalıştırılan bağımsız bir diagnostic, üç
deferred ailenin (Sirküler, Özelge, Yargı Kararı) TAMAMININ **sıfır hatayla
kabul edildiğini** kanıtladı; ağırlaştırıcı detay: en yüksek PII riski
taşıyan iki aile (`Özelge`, `Yargı Kararı`) `required_provenance_fields:[]`
taşıyordu, yani izin verilen bir `Kanun`'dan DAHA AZ denetime tabiydi.
**Sonuç: `NOT LOCK-READY`.** Ayrıca F3-F8 (Low) ve O1-O6 (Observation)
bulguları raporlandı (bkz. §K — hiçbiri kaybolmadı).

**H. Dar remediasyon (Sonnet, F1/F2'nin doğrudan zorunlu sonucu)** — Exact
**3 dosya**: `src/ingest.py`, `src/manifest_validator.py`,
`ui/tests/test_rag_bundle_builder_isolated.py`. **F1 kapanışı**: üç gerçek
join noktasının HER BİRİ, `src/path_containment.resolve_existing(candidate,
root=MEVZUAT_DIR)` üzerinden containment-before-query'ye taşındı (Row
19C-3a Slice 1'in paylaşılan primitive'i — YENİDEN YAZILMADI, YENİDEN
KULLANILDI); sonraki tüm `open`/`stat`/hash işlemleri YALNIZ
containment-doğrulanmış `verified_path` üzerinde çalışır; genuinely-missing
dosya ile escape AYNI `FileNotFoundError` mesajıyla raporlanır (mevcut
`manifest_validator.py` deseniyle tutarlı); manifest'e kaydedilen LOGICAL
isim (alias'ın kendi adı) korunur, resolve edilmiş gerçek hedef adına ASLA
sessizce dönüştürülmez. Gerçek `mklink /J` junction, gerçek
absolute/drive-qualified path, `../` traversal ve UNC-şekilli path'lerin
TAMAMI reddedildi; genuine broken junction
(`lexists()==True`/`exists()==False`) fail-closed reddedildi. Public
`preview_build()` — incelemenin somut olarak gösterdiği erişilebilir yol —
site #1'in kendi düzeltmesiyle kapandı,
`ui/services/rag_bundle_mutation_facade.py`'ye DOKUNULMADAN. **F2
kapanışı**: `validate_corpus_policy_admissibility()`'nin admission kontrolü
dört-yönlü fail-closed matrise genişletildi — `allowed` → diğer kapılara
devam; `deferred` → **ERROR**, ailenin kendi `prerequisites[]`'ini (veya
`"yok"`) atıfla; `prohibited` → DEĞİŞMEDEN ERROR; tanınmayan/eksik değer →
**ERROR** (asla sessizce `allowed` sayılmaz). Policy metninin KENDİSİ
dokunulmadı/yumuşatılmadı — bu bir enforcement düzeltmesiydi, policy-text
softening DEĞİL. Üç deferred aile (Sirküler, Özelge, Yargı Kararı) AYRI
AYRI test edildi; `Özelge`'nin `required_provenance_fields=[]` olduğu ÖN
KOŞUL olarak doğrulanıp yine de reddedildiği (boş provenance admission
red'ini KURTARMAZ) ayrıca kanıtlandı; gerçek 3-belgelik seed corpus'un
(tamamı `allowed` ailelerde) regresyonsuz geçtiği doğrulandı.

Remediasyon implementer'ının kendi koşusu (**ayrı etiketli, §F
implementasyon koşusuyla BİRLEŞTİRİLMEZ**): **65/65 modül exit 0**, **3817
passed, 0 failed, 8 counted skipped, 13 informational skipped** (+2
informational fark, tamamı `test_rag_bundle_builder_isolated`'ın yeni
FAISS-gated + privilege-gated alt-testlerinden, matematiksel olarak
`3785+32=3817` ve `11+2=13` şeklinde mutabık). Hedefli:
`corpus_policy_validator.py --self-test` **20/20**;
`test_rag_bundle_builder_isolated` **73/0/1 informational** (root `.venv`,
faiss VAR); `test_rag_bundle_mutation_integration_postgres` **68/0/0
skipped**; dependency smoke `developer`+`require` **73/0/0**, `DEPENDENCY
GATE: PASS`. Bağımsız F1 audithook diagnostic'i: **7/7 DIAG-PASS**.
Bağımsız network/`.env` invariance diagnostic'i: sıfır socket event, sıfır
`.env` open.

**I. Bağımsız Opus re-review** — Açık disclosure: **Fable haftalık kotası
yine dolu olduğu için bu turun da ana bağımsız yeniden incelemecisi
Opus'tur**; ilk implementasyon VE remediasyon Sonnet tarafından AYRI
oturumlarda yapıldığından model/bağlam bağımsızlığı korunur; advisor
çağrılmamıştır. Dört repo-dışı, sıfırdan yazılmış diagnostic (**122
DIAG-PASS, 0 DIAG-FAIL, 1 informational skip** toplam) kullanıldı. **F1:
CLOSED** — üç join noktası kaynaktan tek tek doğrulandı
(`ingest.py:3148-3171`, `:3245-3257`, `:1663-1686`); `import
path_containment` module-level; her iki join'de AYNI `ingest.MEVZUAT_DIR`
dinamik olarak okunuyor (cached/default-arg yok); dosyanın TAMAMINDA yalnız
3 `except` bloğu var, hepsi bu containment çevirileri — bare
except/pass/continue/warning-downgrade YOK. Kendi 40+13 DIAG-PASS'lık
fault-injection matrisi (gerçek `mklink /J`, gerçek broken junction, gerçek
absolute/drive-qualified path, UNC, `../`) + bir POZİTİF KONTROL (kabul
edilen bir dosyanın GERÇEKTEN okunduğunu kanıtlayan) + gerçek public
`preview_build()` API'sine karşı (gerçek `Principal`, gerçek
`InMemoryGlobalResourceAuthzRepository`) doğrudan fault injection.
Repo-genelinde DÖRDÜNCÜ bir korumasız eşdeğer join arandı:
`run_ingest()`'in kendi, AYRI ham join'i (`ingest.py:2631`) bulundu — bu üç
kontratlı siteden biri DEĞİLDİR, remediasyon raporunda AÇIKÇA disclose
edilmiştir; sıra (containment-hardened `validate_manifest_file` ondan önce
çalışır) ve küme (aynı active+ingest-enabled filtresi) kaynaktan
doğrulanarak transitive-safe olduğu kanıtlandı, reachability sıfır
(production caller yok, `main()` `SystemExit(2)` ile kapalı) — **O-A**
olarak backlog'a kaydedildi (bkz. §K). **F2: CLOSED** — dört-yönlü matris
kaynaktan (`manifest_validator.py:407-437`) tek tek doğrulandı; GERÇEK
committed policy'den mekanik olarak yeniden sayıldı: **6 allowed / 3
deferred / 1 prohibited**; kendi 50 DIAG-PASS'lık diagnostic'i üç deferred
ailenin AYRI AYRI reddini, boş-provenance'ın admission red'ini
kurtarmadığını, policy metninin YUMUŞATILMADIĞINI (mtime karşılaştırmasıyla
da doğrulandı) ve deferred bir belgenin `build_bundle_snapshot()`'a sıfır
extraction/embedding/`index/` artefaktı ile reddedildiğini kanıtladı.

Bağımsız 65-modüllük full sweep (kendi fresh disposable PostgreSQL 16.15
kümesi, migration 0001-0005): **65/65 modül exit 0**, **3817 passed, 0
failed, 8 counted skipped, 13 informational skipped** — remediasyon
implementer'ının 3817/0/8/13'ünü bağımsız olarak BİREBİR yeniden üretti
(kendi kümesi, kendi aritmetiği). Network/`.env`/data/index invariance:
repo-dışı `sitecustomize.py` audithook ledger'ı (pozitif+negatif kontrollü)
tam sweep boyunca **119 event, tümü `127.0.0.1`'e `socket.connect`**,
**sıfır DNS lookup, sıfır `.env` open**; kapanış 90-dosyalık protected-path
manifest'i açılışla **byte-identical**. Cleanup: disposable PostgreSQL
durduruldu, cluster silindi, junction/temp fixture'lar temizlendi; kapanış
git durumu açılışla birebir aynı (branch, HEAD, staged set, `stash@{0}`,
exact 12 dosya).

**Final verdict**:

`RAG CORPUS POLICY FOUNDATION LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`

**J. Sayaçlar** — Corpus Policy Foundation sonrasında: test modülü
**64→65**; merged routing key **49→49** (değişmedi); logical action family
**37→37** (değişmedi); kapalı mutasyon giriş noktası **29→29** (değişmedi);
refusal senaryosu **44→44** (değişmedi — bu sayaç, önceki checkpoint'lerde
de kayıtlı olduğu gibi, TEK bir artefaktan mekanik olarak doğrulanamayan,
yalnız checkpoint aritmetiğiyle tutarlı bir sayım KONVANSİYONUDUR; bu faz
bu soft-spot'a dokunmadı, gizlemedi); migration **5→5** (değişmedi).

**K. Kalan Low/Observation maddeleri — hiçbiri kaybolmadı**

İlk bağımsız Opus incelemesinin F3-F8/O1-O6 bulguları (remediasyon KAPSAM
DIŞI bıraktı, re-review'de hâlâ açık olduğu doğrulandı):

- **F3 (Low)** — `Yargı Kararı` policy notu,
  `mahkeme_dairesi`/`esas_no`/`karar_no`/`temyiz_kesinlesme_durumu`
  alanlarını yanlışlıkla `data/case_case_law.schema.json`'a atfediyor (bu
  dört isim o şemada SIFIR kez geçiyor; gerçekte bunlar Phase-2'nin
  `documents.schema.json`'a eklenecek önerilen alanlarıdır). Notun VARDIĞI
  SONUÇ doğru (court metadata bugün gerçekten yok); yalnız atıf hatalı.
  Re-review'de HÂLÂ AÇIK olduğu doğrulandı.
- **F4 (Low)** — `Yargı Kararı.prerequisites`,
  `"phase2_anonymization_fields"`i içeriyor ama
  `security_rules.anonymization_required_for` yalnız `["Özelge"]`
  listeliyor — iki alan arasında çapraz kontrol yok; registry'nin bugün
  sıfır tüketicisi olduğundan etkisi nil. Re-review'de HÂLÂ AÇIK.
- **F5 (Low)** — tier-membership çapraz kontrolü yok;
  `document_family_rules[*].tier` herhangi bir integer'ı kabul eder,
  `source_authority_tiers`'a karşı doğrulanmaz; `tier`'in bugün sıfır
  runtime tüketicisi var.
- **F6 (Low)** — `official_source: false`, required-provenance kontrolünü
  GEÇER (bu bir varlık kontrolüdür, doğruluk kontrolü değil — `False is
  None`/`False == ""` ikisi de yanlış); gerçek 3 belgenin üçü de `true`
  taşıdığından bugün yanlış-kabul yok.
- **F7 (Low)** — admissibility gate'inin içerik-kapısı yarısında dar
  fail-open `continue` yolları: `.stat()`'ta bir `OSError` o belge için
  boyut/magic-byte/dedup'ı SESSİZCE atlar; bir containment hatası da
  sessizce `continue` eder (`validate_manifest_file` içinde güvenli —
  `validate_files_exist` aynı alt-kümeyi zaten reddediyor — ama fonksiyon
  STANDALONE çağrılırsa bir escape tüm içerik kapılarını atlayıp temiz
  dönebilir); `_sha256_of_file` unguarded, bir `OSError` ham olarak kaçar.
- **F8 (Low)** — `validate_provisions_file`, şema hataları ile
  `validate_manifest` arasında fail-fast yapmıyor (kardeş validator'ların
  ikisi de yapıyor) — malformed bir `provisions.json` temiz bir
  `ValueError` yerine tipsiz bir `KeyError`/`TypeError` çökmesi olarak
  yüzeye çıkabilir.
- **O1** — facade'in policy-entry lookup'ı first-match-wins'tir, duplicate
  policy girdisini reddetmez (defense-in-depth only; sömürmek yerel
  `index/**` yazma erişimi gerektirir — Row 19D OS-ACL sınıfı).
- **O2** — gate yalnız `path`/`sha256` okur; `size_bytes` doğrudan kontrol
  edilmez (dolaylı olarak `bundle_version` üzerinden bağlıdır); malformed
  `sha256` şekil-doğrulanmaz (yine de eşleşmediği için fail-closed kalır).
- **O3** — `preview_activate`'in policy gate'i YOK — sözleşme gate'i yalnız
  `apply_activate`'e zorunlu kıldığından bu UYUMLUDUR, kusur değildir.
- **O4** — `completed` idempotency replay'inde under-lock gate ÇALIŞMAZ
  (benign: pre-lock kontrol her `apply_activate`'te çalışmaya devam eder,
  replay yeni pointer yazmaz).
- **O5** — 25 negatif test yalnız `result["valid"] is False` doğrular,
  hangi kuralın tetiklendiğini pinlemez — yanlış nedenle geçme teorik
  olarak mümkün.
- **O6** — kozmetik: `manifest_validator.py` içinde var olmayan bir
  fonksiyon adına (`validate_corpus_admissibility_and_quality`) yorum
  atıfı; `validate_corpus_policy_admissibility`'nin hiç append edilmeyen
  bir `warnings` listesi döndürmesi; interval kontrolündeki dokümante
  edilmemiş `valid_through`-inclusive konvansiyonu; tek bir global
  `text_basis_declaration`'ın hem as-published (Resmî Gazete) hem
  consolidated (mevzuat.gov.tr) kaynakları kapsaması (policy'nin kendi
  bitişik notunda dürüstçe disclose edilmiş).

Re-review'in KENDİ yeni bulguları (**O-A — O-E**, remediasyon sonrası kod
durumuna karşı):

- **O-A (Low)** — `run_ingest()`'in DÖRDÜNCÜ, AYRI ham join'i
  (`src/ingest.py:2631`, `.exists()` `:2650`, tam hash-okuması `:2661`)
  yalnız TRANSİTİF olarak korunuyor: sıra doğrulandı (containment-hardened
  `validate_manifest_file` ondan ~170 satır önce çalışıyor), belge kümesi
  doğrulandı (aynı active+ingest-enabled filtresi), reachability sıfır
  (production caller yok, `allow_network=True` açık rıza gerektiriyor,
  `main()` `SystemExit(2)` ile kapalı). Kalan risk,
  `manifest_validator.MEVZUAT_DIR` ile `ingest.MEVZUAT_DIR` adlı İKİ AYRI,
  production-eşdeğer, bağımsız monkeypatch'lenebilir sabit kullanan bir
  check-then-re-derive-raw deseninin yarattığı TOCTOU penceresidir —
  `CLAUDE.md` Row 19A bunu AÇIKÇA Row 19D OS-ACL kapsamına atar. "Tamamen
  çözüldü" DENMEZ; remediasyon raporunda dürüstçe disclose edildiği
  doğrulandı.
- **O-B (Observation)** — `CACHE_DIR` join/unlink işlemleri
  (`get_cache_paths`, `document_cache_exists`, `delete_document_cache`)
  containment UYGULANMAMIŞTIR; farklı bir kök (`CACHE_DIR`, `MEVZUAT_DIR`
  değil); önceden var olan, bu slice'ın DIŞINDA; `document_id` şema
  pattern'i (`^[a-z0-9_-]+$`, ayırıcı yok) + `run_ingest`'in erişilemezliği
  tarafından hafifletilmiş; backlog'da kalır.
- **O-C (Observation)** — `resolve_existing()` segment-seviyesi doğrulama
  YAPMAZ; containment tamamen `resolve(strict=True)` + `relative_to`'ya
  dayanır. Bu, safe-internal-alias sözleşmesi için ZORUNLUDUR
  (çok-segmentli bir `file_name`'in root İÇİNDE kalması gerektiğinde kabul
  edilmesi gerekir) ve bu incelemede kusur SAYILMADI — yalnız primitive'in
  garantisinin "segmentler doğrulanıyor" diye ABARTILMAMASI için kayda
  geçirildi. Row 19D/OS-seviyesi risklerden AYRI bir maddedir.
- **O-D (Observation)** — admission/provenance kontrolleri
  `ingest.enabled=False` dahil TÜM kayıtlara uygulanır (kod içinde açıkça
  dokümante edilmiştir) — bilinçli, daha KATI (fail-closed) bir davranış;
  bloklamayan bir observation'dır, ama gelecekte deferred bir aile için
  devre dışı bir placeholder kayıt eklenirse bu kaydın TÜM manifest'i bloke
  edeceği bilinmelidir.
- **O-E (Observation)** — dependency-smoke çıktısında `DEPENDENCY GATE:
  PASS` literal'i iki kez geçiyor (marker'ın kendisi + meta-testin kendi
  etiket satırı) — bu, RAG Real-Dependency Validation + Synthetic E2E Gate
  checkpoint'inde ÖNCEDEN kayıtlı, DEĞİŞMEMİŞ bir backlog notudur, bu turda
  YENİ değildir.

Korunan, önceden bilinen sınırlar (bu turda dokunulmadı, kaybolmadı):
`validate_status_logic`'in yalnızca warning üretmesi, hiçbir zaman error
üretmemesi; hard-neutral discovery'nin temporal sınırı
(issue-driven/case-law discovery sorgu tarihini bastırır); policy hash'in
whitespace/ham-bayt duyarlılığı (bilinçli, fail-closed davranış);
`preview_build.source_document_count`'un +1 kayan, yalnız görüntüleme
amaçlı semantiği; legacy `run_ingest` davranış sertleşmesi (gate #2'yi
miras alır); prompt-injection sınırının implementasyonunun RAG-bağımlı
Slice 2'ye bırakılması; population-stage
encrypted-PDF/OCR/Unicode-hijyen/embedded-JavaScript/decompression-bomb
kontrollerinin policy'de TANIMLI ama henüz KODLANMAMIŞ olması; case-law
metadata/provenance/`text_basis` şema eksikliklerinin Phase-2'ye
bırakılması; mevzuat.gov.tr/Resmî Gazete/Danıştay-UYAP erişim-lisans
koşullarının dış doğrulama gerektirmesi (Phase-3); corpus PDF'lerinin
git-depolama stratejisi kararının henüz verilmemiş olması; Row 19D
TOCTOU/OS-ACL residual'ı (O-A dahil, tüm local-filesystem-actor sınıfı
riskler).

**L. Scope dışı/kalan fazlar** — Bu checkpoint aşağıdakilerin HİÇBİRİNE
dosya-yazma veya implementasyon yetkisi VERMEZ; hiçbiri başlamamıştır:
**P2** — documents-şema prerequisite yaması (court metadata + provenance +
`text_basis` + anonimizasyon alanları + `manifest_validator` per-type
kuralları); **P3** — external source/licensing verification
(mevzuat.gov.tr/Resmî Gazete/Danıştay-UYAP); **P4** — acquisition tooling;
**P5** — Tier-1 population + ilk gerçek bundle; **P5b** — Danıştay/VDDK
(case-law) population; **P6** — RAG-bağımlı Slice 2 (ROW 19C-3c-iv Slice
2); gerçek prompt-injection boundary implementasyonu (`rag.py`
adaptasyonu); Row 19D (Operations & Recovery — OS ACL/service
identity/TOCTOU dahil); maintenance/global-resource backlog devam işleri;
gerçek corpus belgelerinin indirilmesi/edinimi.

**M. LOCKED-file §9 gerekçesi**

| Dosya | Neden yeniden açıldı | Değişiklik türü | Regresyon riski / azaltım | Neden başka katmanda çözülemez |
|---|---|---|---|---|
| `src/ingest.py` | Kullanıcı talebi (Corpus Policy ACTIVE/NEXT fazı) + security (T15 sınıfı ham join'lerin kapatılması; policy'nin bundle identity'ye bağlanması) | Additive: `CORPUS_POLICY_PATH` sabiti, `compute_source_manifest`'e policy girdisi, `build_bundle_snapshot`'a iki yeni validator çağrısı; **remediasyon turunda İKİNCİ KEZ açıldı** — üç join noktasına `path_containment.resolve_existing()` eklendi | Sıfır mevcut bundle olduğundan `source_manifest` şeklinin genişlemesinin uyumluluk maliyeti teoriktir; remediasyon turunun kendisi F1 HIGH bulgusunun DOĞRUDAN ZORUNLU sonucudur — dosyayı açmanın orijinal gerekçesi (security) teslim edilmemişti, ikinci açılış bunu tamamladı; azaltım: §F/§H/§I testleri + gerçek NTFS junction/absolute-path fault-injection | `compute_source_manifest`/`build_document_chunks`'ın TEK tanım yeridir; kopya bir containment implementasyonu drift riski yaratırdı |
| `src/manifest_validator.py` | Downstream entegrasyon (corpus-policy enforcement bir gate gerektirir) + security (policy-ihlalli/deferred belgenin sessizce geçmesinin önlenmesi) | Additive: `validate_corpus_policy_admissibility()` yeni fonksiyonu + `validate_files_exist()`'e containment + orkestrasyona 13. adım; **remediasyon turunda İKİNCİ KEZ açıldı** — admission kontrolü iki-yönlü (`prohibited`-only)'den dört-yönlü fail-closed matrise genişletildi | Yeni red'ler yalnız gerçekten policy-ihlalli belgeler için; gerçek 3-belgelik seed corpus regresyon fixture'ı olarak yeniden doğrulandı; remediasyon turu F2 MEDIUM bulgusunun DOĞRUDAN ZORUNLU sonucudur | `validate_manifest_file()` `ingest`'in TEK güvendiği gate'tir; kopya validator drift riski yaratır |
| `src/provision_manifest_validator.py` | Downstream entegrasyon — validator zaten var ama repo genelinde SIFIR çağıranı vardı; bu boşluğu kapatmak minimum-mümkün düzeltmedir | Additive: `validate_temporal_discipline()` + `validate_cross_version_provision_intervals()` + `validate_provisions_file()` (İLK gerçek otomatik çağıran) | Mevcut 7 gerçek provision yeni kontrollerle yeniden doğrulandı (vacuous-pass, `verified=False` dalı BYTE-DEĞİŞMEDEN korundu); azaltım: wire-in öncesi/sonrası fark raporu | Temporal disiplinin tek uzman validator'ıdır; kopyası yasak |
| `ui/services/rag_bundle_mutation_facade.py` | Kullanıcı talebi + security (Row 19A stale-sonuç kuralının activation'a izdüşümü) | Additive: `CorpusPolicyDriftError` + iki yardımcı fonksiyon + `apply_activate()`'in pre-lock/under-lock zincirine 1 çağrı noktası; **remediasyon turunda AÇILMADI** (F1/F2'nin ikisi de bu dosyanın DIŞINDaydı) | Build yolu dokunulmaz; activation zinciri mevcut çift-kontrol deseninin birebir uzantısıdır; azaltım: §E'deki pre-lock/under-lock testleri (izole + gerçek PostgreSQL, kilit-anı drift injection dahil) | Pointer yazımından önceki SON kapı yalnız burasıdır; başka katmanda tekrarlanamaz |

Remediasyon turunda `src/ingest.py` ve `src/manifest_validator.py`'nin
İKİNCİ KEZ açılması, F1 (HIGH) ve F2 (MEDIUM) bloklayıcı bulgularının
DOĞRUDAN ZORUNLU sonucudur — kozmetik bir düzeltme veya kapsam genişlemesi
DEĞİLDİR.

Bunların DIŞINDA hiçbir LOCKED dosya bu slice'ta açılmadı. Özellikle
DEĞİŞMEYENLER: `ui/services/rag_bundle_mutation_adapters.py`,
`src/retriever.py`, `src/path_containment.py`, `ui/cli_mutate.py`,
`ui/reconciliation_operator.py`, `src/rag.py`,
`data/documents.schema.json`, `data/provisions.schema.json`,
`data/case_*.schema.json` tümü, `src/source_policy.py`,
`src/temporal_policy.py`, `src/provision_policy.py`,
`src/provision_version_policy.py`, `db/migrations/**`, tüm production
`data/`.

**N. Final verdict**

`RAG CORPUS POLICY FOUNDATION LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/
19C-3a Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii/
19C-3c-iii/19C-3c-iv Slice 1/RAG Global-Resource Bundle Foundation/
RAG Real-Dependency Validation + Synthetic E2E Gate/Row 10/11 Legal
Research + Case Law Schema Patch örneğinde olduğu gibi yalnız
`CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### RAG Corpus Prerequisite Documents-Schema Patch (DONE / LOCKED — checkpoint özeti)

**A. Preflight ve exact scope** — Başlangıç HEAD
`5ce7b9ca4d8382792deb5e48d1f5d26f5b1c82a6` (implementasyon, bağımsız
Opus scope review ve bağımsız Opus final review boyunca DEĞİŞMEDİ —
hiçbir commit yapılmadı); branch `claude-dev`; staged set boş;
`stash@{0}` ("quarantine unexpected post-Row19C-2a late writes")
dokunulmamış. Onaylı exact allowlist **0 YENİ + 4 DEĞİŞTİRİLMİŞ = 4
dosya**:

1. `data/documents.schema.json`
2. `src/manifest_validator.py`
3. `ui/tests/test_rag_bundle_builder_isolated.py`
4. `ui/tests/test_case_law_engine_isolated.py`

`git diff --numstat` (mekanik): `108/1` + `131/0` + `148/0` + `422/0` =
**809 satır ekleme, 1 satır silme, 4 dosya, 0 YENİ**. Dört dosyalık
diff'teki TEK silinen satır şema başlığıdır (`"...V2.1"` →
`"...V2.2"`) — kalan 808 satırın tamamı saf ekleme. 0 migration; 0
production `data/documents.json` değişikliği; 0 corpus population; 0
`data/corpus_policy/**` değişikliği; 0 `index/**` değişikliği; 0 CLI/
web yüzeyi; 0 yeni action family/routing key; 0 `src/ingest.py`/
`src/retriever.py`/`ui/services/rag_bundle_mutation_facade.py`/
`…_adapters.py`/`src/case_law_policy.py`/`src/case_law_discovery.py`/
`src/path_containment.py`/`db/migrations/*.sql` değişikliği.

**B. Scope reconciliation ve Opus düzeltmeleri (dürüst kronoloji)** —
İlk Sonnet taslağı **1 YENİ + 6 DEĞİŞTİRİLMİŞ** öneriyordu: yeni bir
`ui/tests/test_documents_schema_prerequisite_patch_isolated.py` test
modülü, `data/corpus_policy/corpus_policy.json`'a bir içerik
düzenlemesi (F3/F4 düzeltmesi + `required_provenance_fields`
doldurma + `policy_version` 1→2 bump), `src/case_law_validator.py`'ye
yorum-only bir düzeltme, ve `esas_no` alanının **reddi** (`document_number`
alanının esas-no'yu zaten taşıdığı varsayımıyla). Bağımsız Opus mimari
inceleme (`rag_documents_schema_prerequisite_opus_review_FINAL.md`)
taslağı Fable FINAL raporunun bağlayıcı §W-1 P2 tanımına karşı
kaynaktan yeniden doğrulayıp dört maddi sapmayı düzeltti:

- **`document_number` `esas_no` için yeterlidir önerisi REDDEDİLDİ** —
  dört bağımsız kanıt: (1) Fable FINAL §G'nin kendi ifadesi ("Tek
  `document_number` alanı esas-no ile karar-no'yu ayırt edemez"); (2)
  LOCKED `case_case_law.schema.json`'ın `case_number`/`decision_number`
  açıklamalarının ikisinin de ayrı alan gerektirmesi ve ikisinin
  karıştırılmamasını açıkça yasaklaması; (3) LOCKED
  `case_law_validator.py`'deki üç sentetik `Yargı Kararı` fixture'ının
  esas+karar numarasını TEK, ayrıştırılamaz bir string'e paketleyerek
  (`"2018/1000 E, 2019/500 K"` gibi) tam olarak bu anti-pattern'i
  kanıtlaması; (4) `document_number`'ın zaten Kanun/BKK/CK için FARKLI,
  yerleşik bir anlam taşıması (versiyon kimlik anahtarı, chunk metadata
  hash'i, retrieval yüzeyi).
- **`esas_no` ayrı canonical alan olarak geri getirildi.**
- **Fable §W-1'in per-type validator kuralları geri getirildi** —
  taslak bunları tamamen reddetmişti; `CLAUDE.md`'nin kendi bağlayıcı
  P2 tanımının ("`manifest_validator.py`'nin per-document-type
  kuralları") ve Fable §W-1'in açık talimatının aksine.
- **`data/corpus_policy/corpus_policy.json` düzenlemesi scope creep
  olarak REDDEDİLDİ** — P2 tarafından zorunlu kılınmıyor (prerequisite
  string'leri yalnız hata mesajına interpolasyon amaçlı okunuyor,
  hiçbir koşul olarak tüketilmiyor); kendi ayrı governance maddesi var
  (`policy_change_approval`, ayrı §8 onayı + `policy_version` bump
  gerektirir); ve — en önemlisi — **canlı, gerçek bir test
  assertion'ını kırardı**:
  `ui/tests/test_rag_bundle_builder_isolated.py`'nin, committed
  policy'nin `Özelge` ailesinin `required_provenance_fields == []`
  taşıdığını sabit bir ön-koşul olarak doğrulayan assertion'ı.
  `anonymization_applied`'ı `required_provenance_fields`'a eklemek
  ayrıca **F6-sınıfı bir PII fail-open** üretirdi (`False is None` →
  `False`, `False == ""` → `False`, presence-loop `anonymization_applied:
  false`'u KABUL ederdi).
- **Yeni test modülü REDDEDİLDİ** (65→66 değil, 65→65) — Fable §W-1
  "iki mevcut test dosyasına additive kanıt" diyor; Row 10/11 emsali
  sıfır yeni test modülü ekledi; taslağın "dosya zaten büyük" gerekçesi
  ölçülünce yanlış çıktı (1230 satır, repo ölçeğinde orta boy).
- **`src/case_law_validator.py`'ye yorum-only düzenleme REDDEDİLDİ →
  READ-ONLY** — sıfır runtime etkisi var, §9 zemini yok (bug/downstream
  uyumsuzluk/güvenlik/kullanıcı talebi değil), Principle 13 ihlali
  olurdu.
- **`acquisition_timestamp` için `format`-tabanlı değil `pattern`-tabanlı
  doğrulama zorunlu kılındı** — `src/manifest_validator.py:117`,
  repodaki `FormatChecker` OLMADAN inşa edilen TEK validator'dır; bir
  `format` anahtar kelimesi burada tamamen etkisizdir. Taslağın
  `case_document.schema.json`'ı taklit eden `format: "date-time"`
  önerisi hiçbir şeyi doğrulamazdı.
- **`anonymization_applied` genel presence kontrolüne bağlanmadı; exact
  `is True` identity kararı alındı** — presence/truthiness tabanlı bir
  kontrol `false`/`1`/`"true"` gibi değerleri kabul ederdi; per-type
  identity check bunların hepsini reddeder.
- Ayrıca kabul edilen düzeltmeler: `mahkeme_dairesi` → `daire` rename
  (iki LOCKED okuyucu + LOCKED in-code yorum zaten `"daire"` okuyor);
  `temyiz_kesinlesme_durumu` enum'undan `bilinmiyor` sentinel'i
  ÇIKARILDI (iki spelling of one state riski); `acquisition_channel`
  enum'u `corpus_policy.json`'ın kendi `source_authority_tiers[].name`
  beş değerini BİREBİR yeniden kullanır (icat edilmiş `elle_giris`/
  `diger` YOK).

Final scope **0 YENİ + 4 DEĞİŞTİRİLMİŞ** oldu (§W, Opus scope review
FINAL). Sonnet implementasyonu bu düzeltilmiş kapsamı birebir uyguladı
— hiçbir taslak-kaynaklı sapma implementasyona sızmadı (bkz. §H).

**C. Exact 10-field schema contract** — Tüm on alan
`data/documents.schema.json` → `$defs.document.properties`'e eklendi.
**Hiçbiri** `required`'a EKLENMEDİ. `additionalProperties: false`
korundu. `schema_version` `const` **1** DEĞİŞMEDEN. Yeni bir
`$defs.nullableDateTime` def'i eklendi (pattern-tabanlı). `$defs`
sayısı 5→6; `$defs.document.required` 14 (DEĞİŞMEDİ, byte-identical);
`$defs.document.properties` 31→41.

| # | Alan | Tip | Enum/pattern | Not |
|---|---|---|---|---|
| 1 | `daire` | `["string","null"]` | serbest metin | `kaynak_kurum`'un normalize edilmiş alt-birimi; tutarlılık curation görevi, P2'de makine tarafından zorlanmıyor |
| 2 | `esas_no` | `["string","null"]` | serbest metin | `karar_no`'dan ayrı; `case_number` P2'de hâlâ `document_number`'dan okunur (§D) |
| 3 | `karar_no` | `["string","null"]` | serbest metin | `esas_no`'dan ayrı; `karar_no` populate edildiğinde `case_law_policy.py` üzerinden `decision_number`'ı OTOMATİK aktive eder |
| 4 | `temyiz_kesinlesme_durumu` | `["string","null"]` | kapalı enum `["kesinlesmis","kesinlesmemis",null]` — **`bilinmiyor` sentinel'i YOK** | curator girdisi, doğrulanmış dava sonucu DEĞİL (Prensip 7) |
| 5 | `anonymization_applied` | `["boolean","null"]` | — | repoda otomatik PII/anonimizasyon doğrulama yeteneği YOK; asla gerçek redaksiyon kanıtı sayılmaz |
| 6 | `text_basis` | `["string","null"]` | kapalı enum `["as_published_original","editorially_consolidated_current",null]`, `corpus_policy.schema.json`'dan BİREBİR | policy-seviyesi beyanı disçarj eder |
| 7 | `raw_byte_sha256` | `["string","null"]` | `^[0-9a-f]{64}$` (yalnız küçük harf) | yalnız `active=true AND ingest.enabled=true` belgeler için doğrulanır — disclosed sınır |
| 8 | `acquisition_timestamp` | `$ref: "#/$defs/nullableDateTime"` | pattern `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$` — **pattern-tabanlı, `format`-tabanlı DEĞİL** | UTC, yalnız `Z`-sonlu |
| 9 | `acquisition_channel` | `["string","null"]` | kapalı enum, `source_authority_tiers[].name`'in 5 değeri BİREBİR | bilinmeyen kanal `null`, `"diğer"` icat edilmedi |
| 10 | `acquiring_actor_ref` | `["string","null"]` | serbest metin | açıkça non-authenticated bir curator etiketi, kriptografik kimlik DEĞİL |

`enum` dizileri (4, 6, 9) bir `null` üyesi içerir — bu `type:
["string","null"]` ile tutarlılık için ZORUNLUDUR, sapma DEĞİLDİR.
Real `data/documents.json` patched şemaya karşı yeniden doğrulandı:
**0 hata** (3 gerçek kayıt da gated aile dışında).

**D. `document_number` / `esas_no` / `karar_no` kararı** — `esas_no` ve
`karar_no` **ayrı canonical property**'lerdir. `document_number` kendi
mevcut genel anlamını (Kanun için kanun numarası, BKK/CK için karar
numarası) korur — YENİDEN TANIMLANMADI, DEPRECATE EDİLMEDİ; ona bağlı
mevcut per-type kurallar (Kanun uyarısı, BKK hard-error, CK uyarısı)
DOKUNULMADAN aynı sırada/şiddette kalır. **Hiçbir sessiz aliasing YOK**
— bağımsız doğrulandı: `esas_no` `src/case_law_policy.py`,
`src/case_law_validator.py`, `src/case_law_discovery.py`'de **sıfır**
kez geçiyor; `case_law_policy.py:305-308` hâlâ `"case_number":
document.get("document_number")` okuyor. P2'de `esas_no` **yalnız
şema + validator**'dır — gerçek admission-time dişleri var (aktif,
ingest-enabled bir `Yargı Kararı` onsuz doğrulanamaz), ama
`case_number`'a KABLOLANMAMIŞTIR. Bu erteleme P5b'nin açık
yükümlülüğüdür. **Testler bunu abartmıyor**:
`test_case_law_engine_isolated.py:876-891`, `esas_no = "2020/9999"` ve
`document_number = "2021/1111"` (genuinely farklı değerler) ile
`case_number == "2021/1111"` **ve** `!= "2020/9999"` conjunction
assertion'ı taşır — non-tautological, mapping yeniden kablolanırsa
yüksek sesle FAIL eder. Hiçbir test var olmayan bir P6 downstream
round-trip'i iddia etmiyor. Var olan iki round-trip kontrolü (`daire`
→ `court_unit`, `karar_no` → `decision_number`) doğrudur — ikisi de
HEAD'de zaten dormant/wired mapping'ler üzerinden sıfır production-kod
değişikliğiyle otomatik aktive olur.

**E. Absent/null/value ve geriye uyumluluk** — Row 10/11 emsalinden
(`rag_index_version_used`) birebir devralınan üç-durumlu makine: **absent**
= kayıt bu alandan önce var VEYA `belge_turu`'nun curation yolu
yapısal olarak asla doldurmaz; **null** = kapsamda ama beyan edilmemiş;
**value** = curator-beyanlı içerik (`anonymization_applied`/
`acquiring_actor_ref` için bu yalnız bir beyandır, asla makine tarafından
doğrulanmaz). Hiçbir cross-field completeness kuralı (ör. "`raw_byte_sha256`
varsa `acquisition_timestamp` da olmalı") eklenmedi — bu bilinçlidir,
`corpus_policy.json`'ın kendi `full_acquisition_provenance` kapısının
`enforcement_stage: "population"` olarak evrelenmiş olmasıyla tutarlı
(alan varlığı P2/policy_foundation, tuple tamlığı P4/P5/population).
Geriye uyumluluk: 3 gerçek kayıt şema-geçerli kaldı (hiçbiri `Yargı
Kararı`/`Özelge` gated ailede değil); Corpus Policy Foundation build
yolu bozulmadı (`validate_manifest_file()` gerçek committed manifest
üzerinde `valid=True`, sıfır hata, ve **tam olarak aynı tek
pre-existing uyarı** — `kanun_2577: active=true ancak
ingest.enabled=false`); `data/documents.json` byte-identical (§A);
Legal Research/Case Law validator self-testleri (16/16, 17/17), QA
self-testi (13/13) DEĞİŞMEDEN geçti; policy admission dağılımı hâlâ
**6 allowed / 3 deferred / 1 prohibited**.

**F. Per-type validator kuralları** — `validate_document_type_logic()`
içine, mevcut altı branch'ten SONRA, iki yeni branch eklendi — HER
İKİSİ AYNI ÖN KOŞULLA gated: `active is True` **ve** `ingest.enabled
is True` **ve** `belge_turu == <target>` (identity karşılaştırması,
truthiness DEĞİL; `ingest` `document.get("ingest", {}) or {}` olarak
okunuyor, JSON `null` asla raise etmiyor):

| `belge_turu` | Yeni kural | Sonuç |
|---|---|---|
| `Yargı Kararı` | `daire`, `esas_no`, `karar_no`, `karar_tarihi` her biri var ve boş değil | eksik her alan için bir `ERROR`, `document_id` + alan adı ile |
| `Özelge` | `anonymization_applied is True` — **identity check**, presence/truthiness DEĞİL | tek `ERROR`, `document_id` + gerçek değer ile |

Bilinçli olarak **`Sirküler`'e hiçbir kural eklenmedi** — bu, mevcut
`admission=deferred` attribution testinin ("bu belge SADECE
admission=deferred nedeniyle reddedildi") doğruluğunu korur.
`temyiz_kesinlesme_durumu`'nu zorunlu kılan bir kural da eklenmedi
(finality beyanını admission zamanında zorlamak için zemin yok —
Prensip 7). **Kanıtlanmış sıfır-regresyon**: gate, 3 gerçek belgenin
ve her iki genişletilmiş test dosyasındaki 5 mevcut fixture'ın
TAMAMI için inert — `active=False`, `active=None`, `active` absent,
`ingest.enabled=False`, `ingest.enabled=None` durumlarının HEPSİNDE.
`Özelge` kuralı `False`/`None`/absent/`1`/`"true"`/`"True"`/`0`/`1.0`/
`[True]` değerlerinin TÜMÜNÜ reddeder, yalnız literal `True`'yu kabul
eder — bu, taslağın düşeceği F6-sınıfı fail-open'ı bizzat kanıtlanmış
biçimde önler (`False is None` → `False`, `False == ""` → `False`
doğrudan çalıştırılarak doğrulandı). Sıralama: `validate_manifest_file()`
13 adım çalıştırır; `validate_document_type_logic` adım 11'dir,
`validate_corpus_policy_admissibility` adım 13'tür (son) — ikisi de
aynı `errors` listesine birikir; gerçek build gate'i
`src/ingest.py:3230`'un `validate_manifest_file(raise_on_error=True)`
çağrısıdır — bu kurallar gerçekten bir bundle build'ini bloke eder.

**G. Raw-byte integrity** — `raw_byte_sha256` gate'i
`validate_corpus_policy_admissibility()`'nin içine, **zaten hesaplanmış**
`file_hash = _sha256_of_file(verified_path)` satırından HEMEN sonra
eklendi — **sıfır ek I/O**. Gerçek PDF baytlarını karşılaştırır (extracted
text hash'i DEĞİL). **Containment kesinlikle önce gelir**: karşılaştırma
`path_containment.resolve_existing(candidate, root=MEVZUAT_DIR)`'in
zaten doğruladığı `verified_path`'i kullanır; sonraki her `.stat()`/
`open()`/hash aynı doğrulanmış path'i kullanır — ham-join escape YOK.
Semantik: `raw_byte_sha256` `None`/absent → skip (iddia yok, hata yok);
mevcut ve `!= file_hash` → belgeyi ve iki hash'i adlandıran `ERROR`.
**Disclosed sınır** (alanın `description`'ına yazıldı): bu blok yalnız
`active AND ingest.enabled` belgeler için ulaşılır — `kanun_2577` gibi
inaktif/ingest-disabled bir kayıttaki beyan edilmiş hash ASLA
doğrulanmaz; bir negatif testle pinlendi. Gerçek NTFS junction escape
ve gerçek kırık junction ile fault-injection dahil ampirik olarak
kanıtlandı (bkz. §I): absolute-path escape, `../` traversal ve
gerçek NTFS junction escape'lerinin HİÇBİRİ canary hash'ini
sızdırmadı; büyük/küçük harf normalizasyonu YOK (doğru hash'in
uppercase'i bile `ERROR`). `compute_source_manifest()`'in bundle-identity
hash'i ile bu declared-provenance hash'i AYRI rollerde kalır — patch
yeni bir identity-core alan eklemez, hiçbir facade/adapter/retriever
değişikliği gerektirmez (`ui/services/rag_bundle_mutation_facade.py`,
`…_adapters.py`, `src/retriever.py` üçü de untouched).

**H. Implementation kanıtı (implementer turu — ayrı etiketli)** —
Standalone smoke-check'ler (repo dışı, 17/17 PASS) sonrası,
`.venv`'in (gerçek faiss/numpy/openai/pypdf/dotenv mevcut) Python'u ile:
`ui/tests/test_rag_bundle_builder_isolated.py` **122 passed, 0 failed,
1 informational skip** (11 yeni test fonksiyonu, `run_self_test()`'e
kayıtlı, sıfır orphan); `ui/tests/test_case_law_engine_isolated.py`
**63 passed, 0 failed** (57 baseline + 6 yeni check). `src/
manifest_validator.py`'nin `__main__` smoke'u gerçek committed
manifest üzerinde: `MANIFEST GEÇERLİ`, `Belge sayısı: 3`, **tek
pre-existing uyarı DEĞİŞMEDEN**. Daha geniş hedefli regresyon (`.venv`):
`test_corpus_policy_validator_isolated` 69/0;
`test_rag_bundle_mutation_facade_isolated` 148/0;
`test_rag_bundle_mutation_integration_postgres` (gerçek disposable
PostgreSQL 16, port 55433, migration 0001-0005) 68/0/0;
`test_rag_bundle_dependency_smoke.py` (`.venv`, bağımlılıklar
GERÇEKTEN mevcut, env var açıkça `require`'a ZORLANMADI — bkz. §I'nin
bu boşluğu nasıl kapattığı) 73/0/0, `DEPENDENCY GATE: PASS`;
`legal_research_validator.py`/`case_law_validator.py` self-test 16/16/
17/17; `qa_engine.py --self-test` 13/13; Layer A promotion-adjacent
regresyon (`test_mutation_approval_facade_isolated`) 170/0; fact/timeline
promotion regresyonu (`test_promotion_mutation_facade_isolated`) 101/0.
**Full 65-modül sweep** (fresh disposable PostgreSQL 16.15, port
55433, migration 0001-0005, `vergi_ui_runtime` interpreter —
`psycopg` var, `faiss`/`numpy`/`openai`/`pypdf`/`python-dotenv` yok,
dokümante hedef ortamla tutarlı): **65/65 modül exit 0, 3872 passed, 0
failed, 8 counted skipped, 13 informational skip + 1 ayrı, farklı
ifadeli, sayaç-dışı satır (`test_reconciliation_isolated`) = 14 toplam
informational**. 8 counted skip = `test_path_containment_isolated`
(4) + `test_path_containment_module_isolated` (4) (bilinen,
Developer-Mode-gated POSIX-symlink alt-testleri). 13 informational =
`test_rag_bundle_builder_isolated` (5) + `test_rag_bundle_dependency_smoke`
(7) + `test_rag_bundle_reader_isolated` (1) — tümü `faiss`/`numpy`'nin
`vergi_ui_runtime`'da kurulu olmamasından. Network/`.env`/`data`/`index`
invariance: hiçbir gerçek Anthropic/OpenAI credential kullanılmadı,
`.env` bu turun kendi kodu tarafından hiç açılmadı, korunan yolların
(`data/cases/**`, `data/documents.json`, `data/provisions.json`,
`data/mevzuat/**`, `data/corpus_policy/**`, `index/**`,
`db/migrations/**`, `CLAUDE.md`) raw-byte SHA-256 manifesti başta/sonda
**byte-identical**. Cleanup: PostgreSQL durduruldu, dizin ağacı
kaldırıldı, port 55433 free doğrulandı.

**I. Bağımsız Opus final review (ayrı etiketli, implementer'dan AYRI
model/oturum)** — Fable haftalık kotası dolduğu için bu turun doğrudan
ana bağımsız incelemecisi Opus olarak kullanıldı; implementasyon
Sonnet tarafından AYRI bir oturumda yapıldığından model ve bağlam
bağımsızlığı korundu; `advisor` çağrılmadı. Üç mutually-blind salt-okunur
alt-ajan tamamlandı; her yük-taşıyan iddia ana Opus incelemecisi
tarafından kaynaktan bağımsızca yeniden doğrulandı. **0 Critical/High/
Medium bulgu.** Exact 4-dosya scope + 809 ekleme/1 silme (yalnız başlık
bump'ı) mekanik olarak yeniden doğrulandı; 10 alanın TAMAMI gerçek
dosyadan mekanik olarak doğrulandı (tip/enum/pattern/nullability);
`anonymization_applied` identity kontrolü doğrudan çalıştırılarak
kanıtlandı (`False`/`None`/`1`/`"true"` reddedildi, yalnız `True`
kabul edildi); raw-hash + containment gerçek out-of-root canary,
**gerçek NTFS junction escape** ve **gerçek kırık junction** ile
fault-injection'la doğrulandı; geriye uyumluluk (3 gerçek kayıt,
Corpus Policy Foundation build yolu, tek pre-existing uyarı) bağımsızca
teyit edildi; gerçek committed manifest build-gate'ten uçtan uca
geçirildi (`MANIFEST GEÇERLİ`, 3 belge, 1 uyarı). **Bağımsız diagnostic
matrisi**: repo-dışı, kendi başına yazılmış, 165 DIAG-PASS, 0 DIAG-FAIL,
0 skip. **Bağımsız full sweep** (kendi fresh disposable PostgreSQL
16.15 kümesi, port **55434** — implementer'ınkinden AYRI, sıfır state
paylaşımı): **65/65 modül exit 0, 3872 passed, 0 failed, 8 counted
skipped** — implementer'ın iddiasını BAĞIMSIZCA, birebir yeniden
üretti; 13 informational + 1 ek satır = 14 toplam, implementer'ın
muhasebesiyle eşleşti. **Doğru dependency-environment tespiti**: review
brief'inin öncülü (implementer'ın `.venv`'de faiss/numpy'nin eksik
olduğunu söylediği) FİİLEN YANLIŞTI — düzeltildi: `.venv` (Python
3.14.4) tam pinned RAG zincirini GERÇEKTEN taşıyor
(`faiss-cpu` 1.15.0, `numpy` 2.5.2, `pypdf` 6.16.2, `openai` 3.6.0,
`python-dotenv` 1.2.3, `httpx2` 2.12.0 — hepsi IMPORT-OK, pin'le
birebir; `anthropic` 1.2.0 yalnız informational); `vergi_ui_runtime`
hiçbirini taşımıyor (yalnız `psycopg` 3.3.5). **İmplementerin yalnız
developer-mode koşusu nedeniyle oluşan evidence-gap kapatıldı**:
implementer'ın `.venv` koşusu bağımlılıklar gerçekten mevcutken
`DEPENDENCY GATE: PASS` gösterdi, ama env değişkenini açıkça
`require`'a ZORLAMADIĞI için bu, LOCKED require-mode gate'in
gerçekten bozulmadığının KANITI DEĞİLDİ. Bağımsız review bunu bizzat
`VERGI_RAG_DEPENDENCY_GATE=require` ile çalıştırdı: **73 passed, 0
failed, 0 informational skip**, `DEPENDENCY GATE: PASS`, exit 0,
**sıfır dış network** (OpenAI trafiği yalnız `httpx2.MockTransport`
üzerinden). **Doğru data-invariance sınırı**: review brief'inin
implementer raporuna atfettiği "blanket `data/` byte-identical" iddiası
da FİİLEN YANLIŞTI — implementer raporu bu sınırı zaten doğru
kapsamıştı (`data/documents.json`, `data/corpus_policy/**`, `index/**`,
`CLAUDE.md` byte-identical; `data/documents.schema.json` bilinçli tek
istisna); bu bir non-finding olarak kaydedildi, gerçek bir yanlış
temsil BULUNMADI. **`.env` audit-hook positive-control disclosure**:
netguard'ın gerçekten tetiklendiğini kanıtlamak için reviewer'ın kendi
positive-control probe'u bir throwaway subprocess içinde `.env`'i
`open('.env','rb')` ile açtı — **sıfır bayt okundu/yazdırıldı/
saklandı/iletildi**; bu talimata teknik bir sapmaydı, açıkça disclose
edildi, TEKRARLANMADI; sonraki her koşu sıfır `.env` open olayı
gösteriyor. PostgreSQL/temp cleanup doğrulandı, port 55434 free. Final
verdict:

`RAG CORPUS PREREQUISITE DOCUMENTS-SCHEMA PATCH LOCK-READY — NO BLOCKING FINDINGS`

**J. Sayaçlar** — Patch öncesi ve sonrası (hepsi hem implementer hem
bağımsız review tarafından ayrı ayrı, mekanik olarak doğrulandı):

| Sayaç | Öncesi | Sonrası |
|---|---|---|
| `ui/tests/test_*.py` modülü | 65 | **65 (değişmedi)** |
| Merged reconciliation routing key | 49 | **49 (değişmedi)** |
| Logical action family | 37 | **37 (değişmedi)** |
| Kapalı mutasyon giriş noktası | 29 | **29 (değişmedi)** |
| Refusal senaryosu | 44 | **44 (değişmedi)** — tek artefaktan mekanik doğrulanamayan, checkpoint-arithmetic konvansiyonu, korunan |
| `db/migrations/*.sql` | 5 | **5 (değişmedi)** |
| `data/*.schema.json` | 19 | **19 (değişmedi)** |
| `documents.schema.json` `schema_version` | 1 | **1 (değişmedi)** |
| `corpus_policy.json` `policy_version` | 1 | **1 (değişmedi)** — policy dosyası hiç açılmadı |
| Family admission dağılımı | 6/3/1 | **6/3/1 (değişmedi)** |
| Published RAG bundle | 0 | **0 (değişmedi)** |

**K. Bütün Low/Observation kayıtları — HİÇBİRİ KAYBOLMADI** —
Bağımsız incelemenin kendi bulgu tablosu tam **11 madde** taşır (`L1`
+ `O1`–`O10`); hiçbiri toplu geçilmeden, her biri kendi kaynağı ve
gerekçesiyle tek tek kaydedilir:

- **L1** (Low, **bu inceleme tarafından KAPATILDI**) — implementasyon
  raporunun dependency kanıtı yalnız developer-mode'du; require-mode
  koşusu YOKTU, bu yüzden LOCKED gate'in sürekli reprodüksiyonu
  KANITLANMAMIŞ, yalnız İDDİA EDİLMİŞTİ. Kaynak: impl raporu §J/§K.
  Kapanış: bağımsız review `VERGI_RAG_DEPENDENCY_GATE=require` ile
  bizzat çalıştırıp 73/0/0 PASS + sıfır network doğruladı (§I). Artık
  açık backlog DEĞİL.
- **O1** (Low) — `src/manifest_validator.py:1957-1965`'in `__main__`
  bloğu `Exception`'ı yakalayıp `MANIFEST GEÇERSİZ` basıp sonlanıyor,
  yani `python src/manifest_validator.py` **geçersiz bir manifest'te
  bile exit 0 verebiliyor**. Pre-existing, diff hiçbir `__main__`
  satırına dokunmuyor. Bloklamıyor çünkü gerçek build gate
  `src/ingest.py:3230`'un `validate_manifest_file(raise_on_error=True)`
  çağrısıdır — bu raise eder. Yalnız bu script'in exit code'una
  güvenen bir CI adımı yanıltılabilir. Genel bakım backlog'u, P-faz
  ataması yok.
- **O2** (Low) — `manifest_validator.py:505-507`'deki `except OSError:
  continue`, `stat()` üzerinde boyut/`%PDF`/hash/dedup gate'lerini VE
  şimdi yeni `raw_byte_sha256` doğrulamasını sessizce atlıyor, hata/
  uyarı YOK. Bu, `CLAUDE.md`'de zaten kayıtlı **F7**'dir (RAG Corpus
  Policy Foundation checkpoint). Bu patch sıfır yeni `continue` ekliyor
  ve F7'yi ne kötüleştiriyor ne düzeltiyor — sözleşmenin dediği tam
  olarak bu. **F7 açık backlog olarak KALIR**, "çözüldü" DENMEZ. Row
  19D / genel security backlog.
- **O3** (Observation) — `Yargı Kararı` zorunlu-alan boşluk kontrolü
  `.strip()` olmadan `if not X` kullanıyor, yani yalnız boşluktan oluşan
  `"   "` kontrolü geçiyor; şema `minLength` koymuyor. Dosyanın
  pre-existing konvansiyonuyla (`if not kanun_no`, `if not
  document_number`) birebir tutarlı — yeni bir sapma değil, "present
  and non-empty" sözleşmesinden bir uzaklaşma değil. Genel bakım
  backlog'u, P-faz ataması yok.
- **O4** (Observation) — Gate-konvansiyon asimetrisi: yeni adım-11
  kuralları varsayılansız + `is True` kullanıyor; adım-13 ve
  `validate_files_exist` `.get(..., True)` + truthiness kullanıyor.
  `validate_manifest_file()` üzerinden **sömürülemez**: `active` ve
  `ingest` şema-`required`, `ingest.enabled` `$defs.ingest` içinde
  required, ve adım 1 adım 11'den ÖNCE short-circuit ediyor
  (doğrudan doğrulandı). Yalnız hand-built dict'lerle çağıran
  standalone caller'lar (yani testler) tarafından erişilebilir. Genel
  bakım backlog'u, P-faz ataması yok.
- **O5** (Observation) — Builder informational skip'leri burada 5,
  Corpus Policy Foundation tally'sinde 3 olarak okunuyor. Beşi de
  **pre-existing** gate'tir (3 faiss/numpy + 1 POSIX self-loop + 1
  Corpus Policy Foundation'ın kendi F1 remediasyonunun eklediği faiss
  gate'i). 48 yeni P2 check'in TAMAMI sıfır P2 skip'iyle çalıştı ve
  geçti. Bu, yeni bir skip değil, önceki tally'nin bir atıf farkıdır —
  bookkeeping notu, backlog değil.
- **O6** (Observation) — `acquisition_timestamp`, on yeni alanın
  arasında `description` taşımayan TEK alan. Sözleşme yalnız
  disclosure-taşıyan alanlar için (`raw_byte_sha256`,
  `anonymization_applied`, `acquiring_actor_ref`, `daire`) açıklama
  zorunlu kılıyordu — dördü de taşıyor. Kozmetik, istenirse herhangi
  bir zamanda kapatılabilir, hiçbir P-faz zorunluluğu yok.
- **O7** (Observation) — `$defs.nullableString` ölü kod olarak KALIYOR
  (sıfır `$ref` tüketicisi). Pre-existing; doğru şekilde dokunulmadan
  bırakıldı — on yeni string alan, dosyanın gerçek konvansiyonuyla
  uyumlu inline `["string","null"]` biçimini kullanıyor. Genel şema
  temizliği backlog'u, P-faz ataması yok.
- **O8** (Observation) — Test başlıklarındaki altı bayat routing-key
  anlatı yorumu (44/45/47/39) yedi canlı `== 49` assertion'ıyla
  çelişiyor. Pre-existing dokümantasyon kayması, bu patch'le tamamen
  ilgisiz; her canlı assertion geçiyor. Genel temizlik backlog'u.
- **O9** (Observation) — `test_p2_real_manifest_still_valid_full_orchestration`,
  adının önerdiğinden daha zayıf bir guard — gerçek hiçbir kayıt
  `Yargı Kararı`/`Özelge` değil, yani yeni kurallara göre trivially
  geçiyor. Doğru işbölümü: pozitif kanıt sentetik-fixture testlerinden
  geliyor, bağımsız incelemenin kendi 165-check diagnostic'i tarafından
  ayrıca doğrulandı. Gerçek pozitif kanıt P5b'nin gerçek Danıştay/VDDK
  belgeleriyle gelecek.
- **O10** (Observation) — İnceleme brief'inin `.venv` dependency
  durumu ve "blanket `data/` byte-identical" iddiası hakkındaki
  öncülleri, gerçek implementasyon raporuna göre İKİSİ DE YANLIŞTI
  (§I). Kayıt için tutuldu; patch'te bir kusura işaret ETMİYOR.

Ayrıca RAG Corpus Policy Foundation checkpoint'inden miras kalan ve bu
patch'le HİÇ DOKUNULMAYAN, hâlâ ilgili sınırlar tekrar çözülmüş gibi
gösterilmez: hard-neutral discovery; prompt-injection boundary'nin
P6'ya bırakılması; kaynak/lisans doğrulamasının P3'e bırakılması; PII
kanıtının P4/P5b'ye bırakılması; Row 19D TOCTOU/OS-ACL residual'ı;
corpus PDF git-depolama stratejisi kararsızlığı; population-stage
kalite kapılarının (`encrypted_pdf`, `max_page_count`,
`text_layer_coverage_*`, `ocr_required_without_ocr`,
`unicode_hygiene`, `pdf_embedded_javascript_or_external_reference`,
`decompression_bomb`, `full_acquisition_provenance`) henüz kodda
enforce EDİLMEMESİ.

**L. Scope dışı/kalan fazlar** — Bu checkpoint aşağıdakilerin
HİÇBİRİNE dosya-yazma veya implementasyon yetkisi VERMEZ; hiçbiri
başlamamıştır: **P3** — external source/licensing verification
(§5'te ACTIVE/NEXT olarak açıldı, ama implementasyona HENÜZ
BAŞLANMADI); **P4** — acquisition tooling, `judgment_pdf`/
`judgment_sections` ingest hard-fail'inin (`ingest.py:1706-1724`)
çözümü, population-stage kalite kapılarının aktivasyonu; **P5** —
Tier-1 population + ilk gerçek bundle, `corpus_policy.json`'ın kendi
içerik düzenlemesi (`required_provenance_fields` doldurma, F3/F4
düzeltmesi, `policy_version` bump), `Sirküler` admission flip'i; **P5b**
— Danıştay/VDDK population, `Yargı Kararı` admission flip'i,
`case_number ← esas_no` re-point'i (`case_law_policy.py` **ve**
`case_law_validator.py`'de lockstep), `(kaynak_kurum, daire, esas_no,
karar_no)` natural-key uniqueness kuralı, `Yargı Kararı` anonimizasyon
kuralı (F4 kapandıktan sonra); **P6** — RAG-bağımlı Slice 2:
`temyiz_kesinlesme_durumu`'nun `decision_candidate`'e kablolanması, on
alanın (ve pre-existing `karar_tarihi` boşluğunun) chunk metadata/
retrieval'a propagasyonu, gerçek prompt-injection boundary'si. Ayrıca
başlamamış: production `data/documents.json` metadata population
(3 gerçek kayıt geri-doldurulmadı — Prensip 9/11); Row 19D (OS ACL,
service identity, TOCTOU, advisory-lock timeout backlog).

**M. LOCKED-file §9 analizi**

| Dosya | Neden açıldı | Değişiklik türü | Regresyon riski | Neden başka katmanda çözülemez |
|---|---|---|---|---|
| `data/documents.schema.json` | RAG Corpus Policy Foundation'ın canlı, committed `corpus_policy.json`'ının üç `prerequisites[]` string'i tarafından açıkça isimlendirilen tek dosya — bu fazın patch etmek için VAR OLDUĞU dosya | Additive: 10 optional/nullable property + yeni `$defs.nullableDateTime`; başlık kozmetik `V2.1`→`V2.2`; 14 `required` DEĞİŞMEDEN, `additionalProperties:false` korundu, `schema_version` const 1 DEĞİŞMEDEN | **Sıfır** — additive optional property'ler hiçbir mevcut kaydı geçersiz kılamaz; 3 gerçek kayıt hiçbiri gated ailede değil | Belge kaydı şeklinin TEK tanım yeridir |
| `src/manifest_validator.py` | On alan onsuz sadece dekorasyon olur; Fable §W-1 ve `CLAUDE.md`'nin kendi bağlayıcı P2 tanımı per-type kuralları zorunlu kılıyor | `validate_document_type_logic()`'e `Yargı Kararı`/`Özelge` için fail-closed per-type branch + `raw_byte_sha256` declared-vs-computed karşılaştırması (zaten hesaplanmış hash'i yeniden kullanarak); diğer 12 validator DOKUNULMADI | Düşük, mekanik olarak sınırlı — gate 3 gerçek kaydın ve 5 mevcut fixture'ın TAMAMI için inert (§F); hash karşılaştırması zaten hesaplanmış bir değeri ve zaten containment-doğrulanmış bir path'i yeniden kullanıyor | `validate_manifest_file()`, `ingest.build_bundle_snapshot()`'ın güvendiği TEK gate'tir; paralel bir validator drift riski yaratırdı |

Test dosyaları için additive-evidence rolü: `ui/tests/
test_rag_bundle_builder_isolated.py` (11 yeni test fonksiyonu, tek
mevcut `manifest_validator` kapsamı barındıran dosya — yeni bir modül
onu parçalardı) ve `ui/tests/test_case_law_engine_isolated.py` (6 yeni
check + 1 additive import, court-metadata round-trip'inin ve pinlenmiş
`esas_no` ertelemesinin TEK dayanıklı evi) — ikisi de yalnız additive,
hiçbir mevcut assertion zayıflatılmadı/kaldırılmadı; §9 bu ikisine
uygulanmaz (test dosyası).

**N. Final verdict**

`RAG CORPUS PREREQUISITE DOCUMENTS-SCHEMA PATCH LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — 19A/19B/19C-1/19C-2a/19C-2b/19C-2c/
19C-3a Slice 1/Slice 2/19C-3b Slice 1/Slice 2/19C-3c-i/19C-3c-ii/
19C-3c-iii/19C-3c-iv Slice 1/RAG Global-Resource Bundle Foundation/
RAG Real-Dependency Validation + Synthetic E2E Gate/Row 10/11 Legal
Research + Case Law Schema Patch/RAG Corpus Policy Foundation
örneğinde olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur
bir roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Row 19D Authentication Enablement Slice 1 — Local Key Custody and Auth Seam Enablement (DONE / LOCKED)

**A. Başlangıç durumu ve exact scope** — Slice 1'in exact değişiklik yüzeyi
**3 NEW + 2 MODIFIED = 5 dosya**dır:

- NEW: `ui/services/key_custody.py`
- NEW: `scripts/key_custody_admin.py`
- NEW: `ui/tests/test_key_custody_isolated.py`
- MODIFIED: `ui/auth_routes.py`
- MODIFIED: `ui/tests/test_oidc_client_isolated.py`

Bu slice **0 migration, 0 yeni route, 0 yeni IAM action/reason code, 0
production credential ve 0 gerçek custody file** üretti. Test modülü sayısı
**65 → 66** oldu. Kaynak ve bağlayıcı raporlardan doğrulanabilen diğer roadmap
sayaçları değişmedi: merged reconciliation routing key **49**, logical action
family **37**, kapalı mutasyon giriş noktası **29**, migration **5**. Refusal
senaryosu **44** mevcut checkpoint-arithmetic konvansiyonudur; tek artefaktan
mekanik olarak yeniden türetilemediği için burada bağımsız kaynak sayımı olarak
sunulmaz.

**B. Mimari sözleşme** — Existing `KeyProvider` Protocol değişmedi:
`get_key(key_id)` ve `current_key_id()`. Local-file provider yalnız açık
`VERGI_KEY_PROVIDER_KIND=local_file` seçimiyle kullanılabilir; unset, empty veya
unknown seçim fail-closed'dur. `kms` seçimi Slice 1'de açık bir “not
implemented/provider unavailable” sonucu verir; production yolunda
`InMemoryKeyProvider` ve sessiz fallback yoktur. Import-time key/pepper üretimi
veya dosya yazımı yapılmaz. Key file strict JSON/parser doğrulaması, canonical
base64, 32-byte AES key, ayrı en az 32-byte pepper ve current-key bütünlüğü
zorunludur. `initialize`, `rotate-key` ve `rotate-pepper` yalnız açık operator
işlemleridir; key rotation eski decrypt anahtarlarını korur, pepper rotation ayrı
bir işlemdir ve mevcut CSRF türetimlerini etkileyeceği açıkça bildirilir. Raw
key/pepper/token/verifier/plaintext/ciphertext normal output'a veya loglara
yazılmaz.

**C. Auth seam bağlantısı** — `ui/auth_routes.py` içinde yalnız
`_key_provider()` ve `_server_pepper()` gövdeleri provider dispatch'e bağlandı.
Callback/login/logout/session davranışları mevcut sınırlarını aşmadı; Slice 1'in
tek başına “gerçek kullanıcı girişini açtığı” iddia edilmez. Gerçek Entra
tenant, app registration, Conditional Access binding verification, bootstrap ve
browser smoke Slice 3'tedir.

**D. İlk implementasyon kanıtı (implementer turu, tarihsel)** — Focused sonuç
**356 passed / 0 failed / 3 informational skip**; full sweep sonucu fresh
disposable PostgreSQL 16 ve migration `0001`–`0005` ile **66 modül, 3946 passed
/ 0 failed / 22 skipped** idi. External network ve `.env` erişimi sıfırdı;
gerçek custody path oluşturulmadı. Sonraki bağımsız incelemenin bulduğu F1–F5
nedeniyle bu turun kanıtı LOCK için tek başına yeterli DEĞİLDİ.

**E. İlk bağımsız inceleme** — Aynı **3946 passed / 0 failed / 22 skipped**
sonucu bağımsız üretildi; verdict **NOT LOCK-READY** idi. Bulgular tarihsel
kayıttan silinmez veya küçültülmez:

- **F1 HIGH** — unsafe Windows ACL inheritance.
- **F2 MEDIUM** — concurrent rotation lost updates.
- **F3 MEDIUM** — post-commit failure misreporting.
- **F4 MEDIUM** — gerçek callback regression kanıtının eksikliği.
- **F5 MEDIUM** — path-validation / namespace race.

**F. Dar remediation sınırı** — Remediation yalnız
`ui/services/key_custody.py`, `scripts/key_custody_admin.py` ve
`ui/tests/test_key_custody_isolated.py` dosyalarında yapıldı.
`ui/auth_routes.py` ile `ui/tests/test_oidc_client_isolated.py` remediation
boyunca byte-identical kaldı.

**G. F1–F5 kapanış mekanizmaları**

- **F1 CLOSED** — Windows objeleri creation-time private/protected DACL ile
  oluşturulur; yalnız current operator, `SYSTEM` ve Builtin Administrators
  trustee'leri kabul edilir. `chmod` veya sonradan düzeltme güvenlik kanıtı
  değildir. Owner/protection/trustee/mask/flag/inherited/duplicate/unexpected
  ACE kontrolleri uygulanır.
- **F2 CLOSED** — Win32 processler-arası byte-range lock initialize ve bütün
  read-modify-write/publish işlemini kapsar. Key/key, key/pepper ve pepper/key
  yarışlarında committed mutation'lar korunur; abnormal process exit sonrası
  OS lock release kanıtlandı.
- **F3 CLOSED** — Tek commit point `os.rename`/`os.replace`'dir; commit sonrası
  fallible ACL/`chmod` hardening yoktur. Pre-commit failure eski baytları korur;
  post-commit reporting failure açık **result 3 /
  `COMMITTED_WITH_REPORTING_ERROR`** üretir ve pepper warning kaybolmaz.
  Power-loss durability veya tam crash-proof cleanup iddiası yapılmaz.
- **F4 CLOSED** — Kanıt gerçek FastAPI callback, gerçek local provider parsing,
  gerçek AEAD ve gerçek transaction/session recorder kullanır; yalnız dış OAuth
  exchange mock/block edilir. Unknown key ve corrupt ciphertext generic 401,
  consumed transaction ve zero exchange/session üretir; provider/configuration
  sorunları ayrık 500 ve rollback/not-consumed üretir. Handler-deletion mutant
  öldürülür ve reader observations **> 0**'dır.
- **F5 CLOSED** — Validation açılmış Windows handle'ları üzerinden yapılır;
  reparse reddi, final handle-path verification ve no-delete-sharing directory
  handles uygulanır. Handle'lar sensitive operation boyunca açık kalır;
  repository containment check açılmış gerçek nesne üzerinde yapılır.
  Junction/file-reparse/parent-swap testleri bu sınırı kanıtlar.

**H. Remediation implementasyon test kanıtı (implementer turu)** — Focused:
**383 passed / 0 failed / 3 informational skip**. Full sweep: **66 modül, 3973
passed / 0 failed / 22 informational skip**. Bu sayılar yalnız implementer'ın
remediation turuna aittir.

**I. Final bağımsız remediation re-review kanıtı** — Focused: **383 passed / 0
failed / 3 focused-only DB skip**. Full sweep: **66/66 modül, 3973 passed / 0
failed / 8 counted skip**. Sekiz skip yalnız
`test_path_containment_isolated: 4` ve
`test_path_containment_module_isolated: 4` dağılımındadır; RAG
optional-dependency modülleri final bağımsız re-review runtime'ında **0 skip**
verdi. Dolayısıyla implementer turundaki 22 ile re-review turundaki 8
birleştirilmez veya tek ortak skip sayısı gibi sunulmaz; bunlar farklı gerçek
ortam/raporlama sonuçlarıdır. External network, `.env`, Entra, Graph, OIDC
provider, model veya RAG-service çağrısı yapılmadı; cleanup tamamlandı. Final
exact verdict:

`ROW 19D AUTHENTICATION ENABLEMENT SLICE 1 LOCK-READY — F1–F5 CLOSED, NO BLOCKING FINDINGS`

**J. Kalan Low/Observation kayıtları (non-blocking backlog, AÇIK)**

- **O1** — malformed field-name reflection: açık.
- **O2** — snapshot/private mutable mapping limitation: açık.
- **O3** — resource bounds and crash-durability limitations: dar F3
  commit-boundary düzeltmesi dışında açık.
- **O4** — pre-existing secret-bearing dataclass repr exposure: açık.
- **O5** — OIDC-test strengthening opportunities: açık.
- **O6** — pre-existing out-of-slice authentication behavior: açık.

**K. Scope dışı / henüz başlamayan işler** — Production KMS/Key Vault
provider; deployment/workload identity; production ACL/recovery/backup/rotation
cadence; pepper'ın production kaynağına bağlanması; gerçek Entra development ve
production tenant; public-client `InstalledClient` app registration;
Conditional Access Authentication Context'in Graph üzerinden gerçekten policy'ye
bağlı olduğunun doğrulanması; admin bootstrap/provisioning; gerçek browser
üzerinden `__Host-session` cookie doğrulaması; opt-in live login/logout smoke;
production secrets/credentials; migration `0006` veya yeni IAM reason code; P3
legal/access blocker closure; corpus acquisition/population; web product/pilot
deployment. Bunların hiçbiri bu checkpoint ile başlamaz veya yetkilendirilmez.

**L. §9 / LOCKED-file gerekçesi** — `ui/auth_routes.py` yalnız daha önce açık
bırakılmış iki `NotImplementedError` seam gövdesini fail-closed provider
dispatch'e bağlamak için açıldı; route, callback policy veya dış auth protokolü
yeniden tasarlanmadı.

**M. Son durum**

`ROW 19D AUTHENTICATION ENABLEMENT SLICE 1 LOCK-READY — F1–F5 CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

### Row 19D Authentication Enablement Slice 2 — Azure Key Vault Secrets Custody Provider Foundation (DONE / LOCKED — checkpoint özeti)

**A. Preflight ve exact scope** — Branch `claude-dev`; HEAD
`f1b7c577a826a638cceee9ed47968f256166baf4` (implementasyon, bağımsız
inceleme ve bu roadmap-lock turu boyunca DEĞİŞMEDİ; commit yapılmadı).
Kullanıcı tarafından onaylanan corrected final scope'un exact 11-path
allowlist'i: **2 NEW + 9 MODIFIED = 11 dosya**.

NEW (2):
1. `ui/services/azure_key_vault_custody.py`
2. `ui/tests/test_azure_key_vault_custody_isolated.py`

MODIFIED (9):
3. `ui/services/key_custody.py`
4. `ui/auth_routes.py`
5. `ui/main.py`
6. `ui/requirements.txt`
7. `ui/tests/test_key_custody_isolated.py`
8. `ui/tests/test_auth_routes.py`
9. `ui/tests/test_drafting_request_routes.py`
10. `ui/tests/test_routes.py`
11. `ui/tests/test_review_routes.py`

**0 migration**; SQL security-event vocabulary ve Python writer map
DEĞİŞMEDİ. `CLAUDE.md` implementasyon/inceleme turlarında HİÇ
değişmedi — bu checkpoint'in kendisi ilk yazım anıdır. `data/**`,
`index/**`, `db/migrations/**` korunmuştur (bağımsız incelemenin
121-dosyalık açılış/kapanış SHA-256 manifesti byte-identical).
HİÇBİR Azure/cloud configuration yapılmadı; hiçbir gerçek Azure/Entra/
Graph/OIDC endpoint'ine bağlanılmadı; gerçek custody dosyası
(`%LOCALAPPDATA%\vergi_ai\key_custody`) OLUŞTURULMADI.

**B. Mimari karar** — Custody modeli **Azure Key Vault Secrets**tır:
tek, versioned bir secret value içinde bütün-custody JSON snapshot'ı.
Bu model açıkça **transitional/provider-compatible read-only secrets
custody foundation**dır; **KMS-grade, HSM-grade veya non-exportable
crypto İDDİASI TAŞIMAZ**. Residual risk açık kayıttır: raw AES
anahtarları ve server pepper, secret value ile birlikte Python process
BELLEĞİNE gelir; secure zeroization garanti edilmez. Non-exportable
key material isteniyorsa Azure Key Vault Keys / Managed HSM modeli
AYRI bir mimari/protokol slice'ı gerektirir (mevcut
`get_key(key_id) -> bytes` sözleşmesiyle karşılanamaz) — bu slice o
iddiada bulunmaz.

**C. Atomic snapshot sözleşmesi** — Tek JSON secret document; exact
root alan kümesi: `version`, `current_key_id`, `keys`,
`server_pepper`. Tek `get_secret(name)` sonucu TEK sefer strict
parse/validate edilir ve frozen `AzureCustodySnapshot`'a çevrilir
(private dict kopyası + `MappingProxyType`; dışarı mutable dict/list
verilmez; repr'ler redakte). Cache publish YALNIZ fully validated
candidate için, lock altında, lease current + non-revoked +
generation-match + deadline-unexpired dörtlü kapısından sonra TEK
snapshot pointer atamasıyla yapılır. `KeyProvider` görünümü ve server
pepper AYNI published snapshot referansından türetilir — tek snapshot
içinde torn key/pepper yapısal olarak imkânsızdır. Atomicity
**process-local**'dır: multi-worker deployment'ta worker'lar 60.0s
monotonic TTL penceresi içinde FARKLI valid version'lar görebilir —
cache/version skew residual risk olarak açık kayıttır.

**D. Parser ve bounds** — UTF-8 belge üst sınırı **16.384 bayt**;
**1..64 key**; AES key **exact 32 bayt**; pepper **32..1024 bayt**;
`current_key_id`'nin `keys` içinde bulunması ZORUNLU; canonical Base64
(decode + re-encode round-trip; padding-bit ihlali dahil non-canonical
biçimler reddedilir); duplicate alan/key-id, unknown/missing alan,
non-finite JSON sabiti (NaN/Infinity) ve bool/non-integer `version`
reddi; boş/whitespace/non-string Azure secret version ID reddi. Yeni
secret-bearing tipler (`AzureCustodyConfig`, `AzureCustodySnapshot`,
lease) repr-redakte; TÜM parser/manager exception mesajları sabit
metindir — alan adı/değer/secret yansıtılmaz.

**E. Retry, timeout ve generation lease** — TEK retry katmanı Azure
Core SDK `RetryPolicy` tabanlı custody policy'sidir; application
retry loop YOKTUR; identity credential'larına `retry_total=0` verilir.
Exact değerler: **2 total attempt** (1 initial + en çok 1 retry);
attempt başına **1.0s connect + 1.0s read**; **≤0.25s
backoff/Retry-After** (oversize Retry-After uyumadan/retry'sız
transient exhaustion); **5.0s outer monotonic budget**; üst sınır
aritmetiği **2×(1.0+1.0)+0.25 = 4.25 ≤ 5.0**. Bağımsız incelemenin
gerçek-SDK gözlemi kayıttadır: azure-core 1.41.0'da İLK retry'ın
backoff'u 0'dır (history ≤ 1) — 0.25 yalnız Retry-After yolunda fiilen
uyunur; 4.25s bir ÜST SINIR olarak geçerlidir. Credential/token
acquisition, outer budget saati BAŞLADIKTAN SONRA gerçekleşir. Worker
cache'e ASLA publish edemez (done-callback yok); caller timeout ve
async cancellation lease'i lock altında REVOKE edip generation'ı
ilerletir; geç worker sonucu DISCARD edilir; refresh failure'da süresi
geçmiş snapshot SERVİS EDİLMEZ ve TTL UZATILMAZ (fail-closed transient
hata).

**F. Credential, API ve RBAC sınırı** — Default: explicit
system-assigned `ManagedIdentityCredential`; user-assigned MI yalnız
explicit client ID ile; workload identity yalnız explicit tenant ID +
client ID + token-file path üçlüsüyle. `DefaultAzureCredential`,
Azure CLI, PowerShell, VS Code, shared token cache ve interactive
browser fallback'ları YOKTUR (repo genelinde sıfır referans). SDK
importu ve client/credential construction lazy'dir (yalnız Azure
seçimi + ilk fetch'te, worker thread'de); import-time
network/discovery yoktur. Runtime API yalnız exact-name
`get_secret(name)`'dir; LIST/version enumeration/write/delete/recover/
purge çağrısı kod tabanında YOKTUR. Strict custom-role beklentisi
`Microsoft.KeyVault/vaults/secrets/getSecret/action`'dır; gerçek role
definition/assignment, identity ve resource kurulumu EXTERNAL
GATE'tedir; built-in "Key Vault Secrets User" rolünün metadata okuma
dahil daha GENİŞ olduğu kayıtlıdır — kod bundan daha dar bir RBAC
iddiası yapmaz.

**G. Selector ve fallback sözleşmesi** — TEK authority mevcut
`VERGI_KEY_PROVIDER_KIND`'dır: `local_file` Slice 1 LOCKED davranışıyla
geriye uyumlu (hata metinleri dahil bayt-aynı korundu);
`azure_key_vault_secret` Azure'un TEK explicit seçim değeri; `kms`
mevcut not-implemented sentinel olarak korunur; unset/empty/unknown
fail-closed. `VERGI_DEPLOYMENT_MODE` EKLENMEDİ ve seçim üzerinde
etkisizliği test edildi. Azure env değişkenlerinin varlığı Azure'u
OTOMATİK SEÇMEZ. Azure config/credential/fetch/parse hatasında local
veya stale fallback YOKTUR. Azure SDK'sı kurulu olmayan hedef
runtime'da local path import/selection çalışır; Azure seçimi sabit
mesajlı, redakte, fail-closed configuration error (500 sınıfı) verir.

**H. Auth ve CSRF call graph** — Exact ALTI CSRF yüzeyi:

1. approval GET — `/cases/{case_id}/approvals/{row_key}`
2. approval POST — `/cases/{case_id}/approvals/{row_key}/confirm`
3. review GET — `/cases/{case_id}/reviews/{review_kind}/{record_id}`
4. review POST — `/cases/{case_id}/reviews/{review_kind}/{record_id}/confirm`
5. drafting GET — `/cases/{case_id}/drafting-request`
6. drafting POST — `/cases/{case_id}/drafting-request/confirm`

İlk beşi sync `def` route'lardır ve Starlette/FastAPI worker
thread'inde çalışır (event loop üzerinde custody erişimi yok; kalıcı
causal heartbeat testleriyle kanıtlı); drafting POST async route'tur
ve awaited async CSRF boundary (`_csrf_secret_for_request_async`)
kullanır. `ui/auth_routes.py`'nin login/callback/logout yolları async
custody accessor'ları kullanır; local-file blocking erişimi de
`asyncio.to_thread` sınırından geçer.

**I. HTTP/transaction error contract** — Unknown application key /
corrupt ciphertext: **generic 401 + callback state consumed**. Bad
config, credential auth, RBAC 403, missing/disabled/deleted secret,
empty version, malformed snapshot, SDK-yok: **generic 500 +
transaction rollback / state NOT consumed**. Retry exhaustion,
connect/read timeout, 408/429/retryable 5xx: **generic 503 + rollback
/ state NOT consumed**. `Retry-After` kullanıcı yanıtına ASLA forward
edilmez. Vault URL/name, tenant/client ID, token path/value, RBAC
detayı, key/pepper baytları yanıt/log/exception yüzeylerine SIZMAZ
(sabit mesajlar; marker taramaları sıfır isabet). Altı CSRF yüzeyinde
provider failure sırasında SIFIR mutation/audit yan etkisi (fixture
sayaçlarıyla kanıtlı).

**J. Dependency ve sayaçlar** — `ui/requirements.txt`'e üç exact
doğrudan pin eklendi: `azure-keyvault-secrets==4.11.2`,
`azure-identity==1.25.3`, `azure-core==1.41.0` (azure-core, retry
policy sözleşmesinin doğrudan API yüzeyi olduğu için transitif
bırakılmadı). Sayaçlar: production Python **149→150**; UI test modülü
**66→67**; UI exact pin **12→15**; root pin **26→26** (UTF-16 root
`requirements.txt` untouched); migration **5→5**; SQL event vocabulary
/ Python writer map **18/18→18/18**.

**K. Dürüst kronoloji (aşamalar birleştirilmeden)**:

1. **İlk scope draft** — 9-path'lik taslak kapsam ve mimari araştırma.
2. **Bağımsız architecture review: NOT READY** — dört bloklayıcı
   düzeltme: (a) shared snapshot atomicity'nin call graph'ta garanti
   edilmemesi (iki bağımsız factory/fetch → torn key/pepper riski);
   (b) 7 saniyelik retry/deadline matematiğinin gerçek SDK
   davranışı altında YANLIŞ olması; (c) `ui/main.py`'nin altı CSRF
   call-site'ının under-scope edilmesi; (d) zorunlu
   `VERGI_DEPLOYMENT_MODE` selector'ının Slice 1 LOCKED selector
   sözleşmesini kırması. İlk tasarım doğruymuş gibi YENİDEN
   YAZILMAMIŞTIR — bu verdict tarihsel kayıttır.
3. **Corrected final exact scope** — F1-F4 düzeltmeleriyle koşulsuz
   11-path allowlist (2 NEW + 9 MODIFIED).
4. **Kullanıcı implementation onayı** — exact 11-path sözleşmesi
   üzerine.
5. **İmplementasyon** — yalnız 11 path içinde; cloud configuration
   sıfır.
6. **Bağımsız güvenlik incelemesi** — kaynak + diff + bağımsız
   ampirik tanılar + testlerin bağımsız yeniden koşulması (aşağıda L).
7. **Final verdict**:
   `ROW 19D AUTHENTICATION ENABLEMENT SLICE 2 LOCK-READY — NO BLOCKING FINDINGS`

**L. Test kanıtı — zaman ayrımlı ve dürüst**:

İmplementer kanıtı (kendi koşuları):

- Targeted: **11 modül, 638 passed, 0 failed**.
- Full sweep (fresh disposable PostgreSQL 16, migration 0001-0005,
  target runtime, her modül ayrı process): **67/67 modül exit 0, 4067
  passed, 0 failed, 8 counted skip, 14 informational skip**.

Bağımsız inceleme kanıtı (AYRI koşular; implementer sayılarıyla
BİRLEŞTİRİLMEZ):

- Targeted: **FARKLI bir 7-modül seti, 558 passed, 0 failed** — bu iki
  targeted seti aynı test setiymiş gibi SUNULAMAZ ve toplamları
  birleştirilemez.
- Full sweep, KENDİ fresh disposable PostgreSQL 16 kümesiyle: **67/67
  modül exit 0, 4067 passed, 0 failed, 8 counted skip, 14
  informational skip** — implementer'ın full-sweep sonucunun BİREBİR
  BAĞIMSIZ reprodüksiyonu.
- Bağımsız repo-dışı tanılar: **31/31** snapshot-atomicity/generation-
  lease race diagnostic; **20/20** parser/bounds boundary diagnostic;
  **36/36** GERÇEK Azure SDK (exact üç pin, disposable venv, fake
  transport) retry/timeout diagnostic.
- Fail-closed audit guard (pozitif kontrollü): **0 external network, 0
  dış DNS lookup, 0 `.env` open**; test loglarında **0 secret
  marker/materyal sızıntısı**; korunan yolların **121-dosyalık SHA-256
  manifesti byte-identical**.

**M. O1-O6 disposition** — Hiçbiri repo-geneli tamamen kapanmış borç
gibi SUNULMAZ:

- **O1 INCLUDE (yalnız Azure parser)** — yeni parser'da field-name
  reflection sıfır; local parser'ın kendi residual'ı AÇIK.
- **O2 INCLUDE (yalnız Azure immutable snapshot)** — repo-geneli
  mutable-mapping residual'ı AÇIK.
- **O3 PARTIAL** — Azure belge/key/pepper bounds kapandı; local crash
  durability AÇIK.
- **O4 INCLUDE (yalnız yeni Azure secret-bearing tipleri)** — eski
  tiplerin repr residual'ı AÇIK.
- **O5 EXCLUDE** — OIDC/client-assertion/MFA step-up DEĞİŞMEDİ
  (`test_oidc_client_isolated.py` byte-identical, geçmeye devam etti).
- **O6 PARTIAL** — yalnız dokunulan auth/altı-CSRF yüzeyinde
  classification/offload; daha geniş yüzey residual'ı AÇIK.

**N. Bağımsız incelemenin TÜM Low/Observation kayıtları (R1-R11,
hiçbiri düşürülmeden)**:

- **R1 (Low)** — İki YENİ dosyada toplam ÜÇ kozmetik CRLF satırı
  (azure modülü satır 343 ve 571; yeni test dosyası satır 449).
  Bloklamıyor; **bu roadmap-lock turunda DÜZELTİLMEDİ** — iki dosyaya
  dokunulmadı; açık Low kayıt olarak kalır.
- **R2** — Gerçek azure-core'da ilk retry backoff'u 0'dır; 4.25s
  YALNIZ geçerli bir üst sınırdır (bkz. E).
- **R3** — Tek-flight lease'te bir async waiter'ın iptali, aynı
  lease'i bekleyen diğer caller'lara nadir gereksiz 503 üretebilir
  (sözleşmenin kendi revoke-on-cancel kararı; fail-closed).
- **R4** — OS seviyesinde ASILI bir SDK çağrısı tek-thread executor'ı
  meşgul edebilir; caller'lar 5.0s'de bounded 503 alır; kuyruğa giren
  bayat fetch'ler budget admission'ında anında düşer (kendi kendini
  sınırlar).
- **R5** — Selector hata metinleri geriye uyumluluk gereği hâlâ yalnız
  `local_file`/`kms` değerlerini anıyor (kozmetik operatör-deneyimi
  notu).
- **R6** — Vault URL doğrulaması path bileşenini reddetmiyor; dar
  hardening adayı.
- **R7** — Route testlerinde failure mapping katmanlara bölünerek
  kanıtlanıyor (route seviyesinde mapped HTTPException enjeksiyonu;
  ham KeyCustodyError→HTTP eşlemesi auth/callback testlerinde);
  kombine kapsam TAMDIR.
- **R8** — Heartbeat mutantı temiz assertion yerine deterministik
  timeout/hang ile ölür (yine causal/öldürücü).
- **R9** — login/callback DB transaction'ı custody fetch boyunca en
  fazla ~5.0s açık kalabilir; rollback semantiği doğru; Row 19D
  operasyon notu.
- **R10** — Python 3.14 `concurrent.futures.TimeoutError == TimeoutError`
  alias gözlemi; production'da ulaşılamaz (worker her exception'ı
  sınıflandırır).
- **R11** — Roadmap pointer'ının bu turdan önce salt-okunur kalması
  süreç kaydıydı; bu checkpoint ile KAPANIYOR.

**O. Residual risk ve external gate (scope dışı / kalan iş)** —
Aşağıdakilerin TAMAMI bu slice'ın DIŞINDADIR ve başlamamıştır: Azure
resource ve gerçek secret oluşturulması; tenant/subscription/region;
identity ve RBAC assignment; private endpoint/firewall/DNS; initial
secret material; adoption ve pepper/key transfer kararı (default: yeni
pepper + planlı global re-auth); aktif session/PKCE/MFA pending-state
invalidation; rotation/recovery/backup/break-glass; multi-worker
coordinated refresh/version telemetry; live cloud smoke; production
cutover. Local dosya Azure failure için silent fallback DEĞİLDİR ve
cutover sonrası aktif ikinci authority olarak TUTULMAZ. Bu slice
KMS/HSM-grade non-exportable custody SAĞLAMAZ (bkz. B).

**P. LOCKED-file §9 gerekçesi** — Tüm değişiklikler kullanıcı onaylı
exact 11-path allowlist İÇİNDE, migration'sız ve backward-compatible
yapıldı; bu checkpoint ile 11 dosyanın Slice 2 sonucu LOCKED kabul
edilir:

- `ui/services/azure_key_vault_custody.py` (YENİ): Azure
  config/credential/client, exact retry policy, strict parser,
  immutable snapshot, generation lease, single-flight ve cache
  manager'ın TEK production evi — corrected scope'un zorunlu kıldığı
  yeni modül.
- `ui/services/key_custody.py`: yalnız additive selector branch'i
  (`azure_key_vault_secret`), `KeyCustodyTransientError` sınıfı ve
  shared manager'a giden sync/async accessor'lar; `local_file`/`kms`
  dalları ve hata metinleri bayt-aynı korundu (Slice 1 sözleşmesi
  GENİŞLETİLDİ, kırılmadı).
- `ui/auth_routes.py`: login/callback/logout'un async
  offload/cancellation sınırı ve 401/500/503 consume/rollback
  sözleşmesi için açıldı; route/callback policy'si ve dış auth
  protokolü yeniden tasarlanmadı.
- `ui/main.py`: yalnız drafting POST'un async CSRF boundary'si ve
  seam-uyumlu async wrapper; beş sync route davranışı DEĞİŞMEDİ.
- `ui/requirements.txt`: yalnız üç exact Azure pini (sona, additive).
- İlgili ALTI test dosyası (`test_azure_key_vault_custody_isolated.py`
  YENİ + beş mevcut test dosyası): yalnız additive kanıt — provider
  failure 500/503 sınıflandırması, sıfır-mutasyon, event-loop
  heartbeat/offload, selector geriye uyumluluğu, redaction; hiçbir
  mevcut assertion gevşetilmedi/kaldırılmadı (beş modified test
  diff'inde sıfır silme).

**Q. Final verdict**

ROW 19D AUTHENTICATION ENABLEMENT SLICE 2 LOCK-READY — NO BLOCKING FINDINGS

**DONE / LOCKED**

### Row 19B OIDC Confidential-Client Remediation — DONE / LOCKED

**A. Başlangıç durumu ve neden yeniden açıldığı** — Row 19D external
activation/adoption gate'in salt-okunur scope draft'ı, gerçek bir
tenant'a karşı secretless PKCE-only bir Web-client exchange'i
doğrulamak üzere "Slice 0" adlı, zero-file bir external verification
adımı önermişti. Bu draft'ın bağımsız Fable mimari incelemesi, bu
öneriyi Microsoft'un resmi OIDC sözleşmesine dayanarak REDDETTİ:
Entra'nın resmi taksonomisi, sunucu tarafı Python uygulamalarını
(`reply-url` sayfasının "Web application redirect URI configuration"
tablosunda Python açıkça "Web" satırında listelenir) **confidential
client** kategorisine yerleştirir; `v2-oauth2-auth-code-flow`
sayfası `client_secret`'ın *"required for confidential web apps"*
olduğunu ve *"Public clients, which include native applications and
single page apps, must not use secrets or certificates"* dediğini
doğrular; `reference-error-codes` sayfası eksik `client_secret`/
`client_assertion`'ın `AADSTS7000218` ile reddedildiğini teyit eder.
PKCE, resmi olarak hem public hem confidential client'lar için
**ek (defense-in-depth)** bir önlemdir — client authentication'ın
**yerine geçmez**. Mevcut, o ana kadar LOCKED olan
`ui/services/oidc_client.py` (Row 19B) tam tersini yapıyordu:
`OAuth2Client`/`AsyncOAuth2Client`'ı hiçbir `client_secret` parametresi
olmadan, salt PKCE-only bir public-client exchange'i olarak
çağırıyordu — bu, uygulamanın mimari olarak bir Web-platform
confidential client olmasıyla doğrudan çelişiyordu ve gerçek bir
Entra tenant'ına karşı ilk gerçek entegrasyon denemesinde
`AADSTS7000218` sınıfı bir reddiyle karşılaşacaktı (corner case değil,
**primary path**). Bu, `CLAUDE.md` §9'un "downstream uyumsuzluk"
(identity provider'ın dokümante edilmiş token-endpoint sözleşmesiyle
çelişki) ve "security/safety ihlali" (bir sunucu uygulamasının kendi
kimliğini identity provider'a ispatlayamaması) gerekçelerinin ikisini
birden karşılayan, LOCKED bir row'un dar biçimde yeniden açılmasını
haklı kılan somut bir bulguydu — Fable incelemesi bunu resmi kaynak
alıntılarıyla (§E, `row19d_external_activation_adoption_gate_
fable_review_FINAL.md`) kanıtladı ve bu remediation'ı, draft'ın
önerdiği "Slice 0" yerine, external activation/adoption gate'in
**immediate scope**'u ("Option C") olarak belirledi.

**B. Exact scope** — Kullanıcı tarafından ayrıca onaylanmış tam dosya
allowlist'i üzerinde implement edildi: **0 YENİ + 6 DEĞİŞTİRİLMİŞ = 6
dosya**:

1. `ui/services/oidc_client.py` (+46 / -1)
2. `ui/auth_routes.py` (+10 / -0)
3. `scripts/iam_bootstrap_probe.py` (+11 / -1)
4. `ui/tests/test_oidc_client_isolated.py` (+226 / -6)
5. `ui/tests/test_auth_routes.py` (+215 / -0)
6. `ui/tests/test_key_custody_isolated.py` (+70 / -0)

Toplam **578 insertions, 8 deletions**. `db/migrations/**` (5
migration), `data/**`, `index/**`, `CLAUDE.md`, `ui/requirements.txt`/
kök `requirements.txt` (Authlib zaten pinliydi), web route/CLI yüzeyi,
Key Vault custody modülleri, MFA/`acrs`, cookie/session, selector/
deployment-mode, proxy/hosting — HİÇBİRİ değişmedi. `ui/tests/
test_*.py` modül sayısı bu turdan SONRA da **67** olarak kaldı
(mekanik olarak `find ui/tests -maxdepth 1 -name "test_*.py" | wc -l`
ile bu roadmap-lock turunda ayrıca doğrulandı); merged reconciliation
registry routing key, logical action family, kapalı mutasyon giriş
noktası ve migration sayacı (5) bu remediation'la DEĞİŞMEDİ — bu dört
sayaç bir mutation-coordinator action family değil, saf bir auth/
config-katmanı değişikliğidir.

**C. Config sözleşmesi** — `EntraProviderConfig`, `client_id`'den hemen
sonra, zorunlu (default'suz) bir `client_secret: str = field(repr=
False)` alanı kazandı; eksik keyword bir `TypeError`, `None`/`123`/
`b"x"`/`[…]`/`True`/`False` gibi non-string değerler `isinstance`
kontrolü `.strip()`'ten ÖNCE çalıştığı için `AttributeError` değil
sabit-mesajlı bir `ValueError`, boş/yalnız-boşluk/tab/`\n`/`\r\n`/
non-breaking-space (` `) değerler `.strip() == ""` ile aynı
sabit-mesajlı `ValueError` üretir. Her iki red mesajı da yalnız
`VERGI_ENTRA_CLIENT_SECRET` env-değişken adını taşır, değeri veya
onun bir dönüşümünü ASLA içermez. Değer HİÇBİR ZAMAN normalize
edilmez — baştaki/sondaki whitespace dahil ham (verbatim) saklanır.
`repr(cfg)`/`str(cfg)`/`f"{cfg!r}"` secret'ı ASLA içermez (diğer
alanlar hâlâ görünür — redaksiyon alan-özgüdür); `dataclasses.asdict()`
/`astuple()`/`vars()`/`__dict__` secret'ı YİNE DE açığa çıkarır — bu
Python dataclass'larının doğal sınırıdır (`field(repr=False)` yalnız
`repr`/`str`'i bastırır), repo genelinde bu dört API'yi
`EntraProviderConfig` üzerinde kullanan SIFIR production caller
mevcuttur (bkz. K, F2/O1). Repodaki altı `EntraProviderConfig(`
construction site'inin TAMAMI keyword-only'dir, bu yüzden alanın
`client_id` ile `authorization_endpoint` arasına EKLENMESİ (sona
değil) hiçbir çağrı sitesini bozmaz.

**D. Gerçek Authlib token-exchange sözleşmesi** — `exchange_code_
for_tokens()`, gerçek `AsyncOAuth2Client(client_id=…, client_secret=
provider_config.client_secret, token_endpoint_auth_method=
"client_secret_post", redirect_uri=…)` inşa eder ve `fetch_token(
token_endpoint, code=…, code_verifier=…)` çağrısını ÖNCEKİ ile AYNI
şekilde yapar. Authlib 1.8.0'ın `encode_client_secret_post`'u
`client_id`+`client_secret`'ı YALNIZ body'ye ekler (`add_params_to_
qs`, header'a ASLA dokunmaz); `token_endpoint_auth_method` `None`
bırakılsaydı Authlib varsayılan olarak `client_secret_basic`'e
(`Authorization` header) düşerdi — bu yüzden açık
`"client_secret_post"` seçimi kozmetik değil, gerçek ve zorunlu bir
override'dır. Sonuç: `client_secret` body'de TAM OLARAK BİR KEZ,
`client_id` TAM OLARAK BİR KEZ; `Authorization: Basic` header'ı YOK;
`client_assertion`/`client_assertion_type` YOK; tek auth method, retry/
fallback YOK. Bir 400 `invalid_client` yanıtı exchange'i fırlatır
(token dönmez), yalnız TEK istek yapılır (ikinci bir auth method
denenmez), exception `str()`/`repr()`'i ham ve URL-encoded secret'tan
arınmıştır.

**E. PKCE ve front-channel korunumu** — `build_authorization_url()`
byte-identical kaldı: authorization-code flow, `state`/`nonce`, S256
PKCE challenge, verifier korunumu ve `claims` payload'ı bu diff'in
HİÇBİR hunk'ında görünmez — front channel yapısal olarak secret
TAŞIYAMAZ (kaynaktan doğrudan doğrulandı, bir test assertion'ına
güvenilmeden).

**F. İki loader ve call graph** — `ui/auth_routes.py`'nin
`_load_provider_config()`'i tek bir yeni keyword ekler:
`client_secret=os.environ.get("VERGI_ENTRA_CLIENT_SECRET")` — eksik
değişken `None` üretir, bu da `__post_init__` tarafından reddedilir
(missing/empty/whitespace TEK bir otorite üzerinden fail-closed'dır).
Route seviyesinde bu, OIDC transaction AÇILMADAN ÖNCE genel bir 500
(`Internal Server Error`) olarak yüzeye çıkar (gerçek production
`ui.main.app` üzerinde, `db.transaction()`'a bir sentinel enjekte
edilerek doğrudan kanıtlandı — bkz. I). `scripts/iam_bootstrap_
probe.py`, `VERGI_ENTRA_CLIENT_SECRET`'ı `required_env`'e ekler
(varlık kontrolü yalnız değişken ADLARINI anan bir `RuntimeError`
fırlatır) ve `client_secret=os.environ["VERGI_ENTRA_CLIENT_SECRET"]`
geçirir; whitespace-only değer varlık kontrolünü geçer ama
`__post_init__` tarafından reddedilir. Probe'un `main()`'i zaten AYNI
`exchange_code_for_tokens`'ı çağırıyordu — artık hiçbir ek değişiklik
olmadan confidential client olarak redeem eder. Hiçbir loader/exchange
sitesinde `.env`/`dotenv`/config-file fallback veya secretless/
public-client dalı YOKTUR (repo-wide grep, sıfır isabet).

**G. Dürüst kronoloji — aşamalar birleştirilmeden**

1. External activation/adoption gate scope draft'ı ("Slice 0" —
   secretless PKCE Web-client test önerisi).
2. Fable architecture review, resmi Microsoft sözleşmesi üzerinden
   Slice 0'ı REDDETTİ ve Option C'yi ("Row 19B OIDC Confidential-Client
   Remediation", 0 YENİ + 6 DEĞİŞTİRİLMİŞ) immediate scope olarak
   belirledi.
3. Kullanıcı onaylı exact 6-path implementasyon.
4. İmplementasyon, talimatta "Sonnet" denmesine RAĞMEN fiilen **Claude
   Fable 5.1** üzerinde ve **iki advisor çağrısıyla** (biri
   implementasyondan önce, biri kapanıştan önce) yapıldı — bu sapma
   implementer'ın kendi raporunda AÇIKÇA disclose edilmiştir (§O4),
   burada gizlenmez veya yeniden yazılmaz.
5. Bağımsız inceleme **Sonnet 5, xhigh effort**, advisor/sub-agent
   ÇAĞRILMADAN yürütüldü — implementasyon oturumundan AYRI model/
   session, bu model/advisor sapmasına RAĞMEN bağımsızlık korunmuştur.
6. Final verdict: `ROW 19B OIDC CONFIDENTIAL-CLIENT REMEDIATION
   LOCK-READY — NO BLOCKING FINDINGS`.

**H. Test kanıtları — implementer ve reviewer sayıları AYRI tutulur**

Implementer targeted (HEAD baseline → working tree, aynı runtime):

- `test_oidc_client_isolated`: 61/0 → **111/0**
- `test_auth_routes`: 97/0 → **128/0**
- `test_key_custody_isolated`: 87/0 → **93/0**
- `test_iam_bootstrap_probe_isolated` (untouched, regresyon): 6/0 →
  **6/0**

Bağımsız reviewer targeted (kendi `git worktree add --detach`'iyle
BAĞIMSIZ olarak yeniden türetilen HEAD baseline + kendi çalıştırdığı
working-tree sayıları):

- aynı dört modül BAĞIMSIZCA yeniden koşuldu
- HEAD baseline: **61/97/87/6** — implementer'ınkiyle birebir
- working tree: **111/128/93/6** — implementer'ınkiyle birebir
- delta: **+50/+31/+6/+0** — implementer'ınkiyle birebir

Implementer full sweep (fresh disposable PostgreSQL 16.15, migration
0001-0005, tek-process/sıralı 67 modül):

- **67/67 modül exit 0**
- **4154 passed, 0 failed**
- **8 counted skipped** (`test_path_containment_isolated` 4 +
  `test_path_containment_module_isolated` 4)
- **14 non-counted informational** `SKIPPED` satırı (toplam 22 ham
  `SKIPPED` satırı = 8 counted + 14 informational)

Bağımsız reviewer full sweep — AYRI, kendi bağımsız altyapısıyla
(kendi fresh disposable PostgreSQL 16.15 kümesi, port `55437`, kendi
sıfırdan yazılmış guard/driver/offline-retally script'i, implementer'ın
kendi O3'te disclose ettiği live-parser hatasından BAĞIMSIZ bir
mekanizma):

- **67/67 modül exit 0**
- **4154 passed, 0 failed**
- **8 counted skipped, 14 non-counted informational** —
  implementer'ın sonucunun BAĞIMSIZ, birebir reprodüksiyonu, FARKLI
  tooling'le elde edilmiştir.

Bu iki sweep TEK bir koşuymuş gibi BİRLEŞTİRİLMEZ — implementer'ın
port `55435`'teki kümesiyle reviewer'ın port `55437`'deki kümesi
tamamen ayrı, birbirinden bağımsız çalıştırmalardır.

**I. Bağımsız ampirik güvenlik kanıtları** — Bağımsız inceleme,
implementer'ın testlerine güvenmek yerine kendi, repo-dışı, sıfırdan
yazılmış İKİ diagnostic script'i kullandı: (1) gerçek Authlib
kaynağından (`authlib/oauth2/auth.py`, `authlib/oauth2/client.py`,
`authlib/integrations/httpx_client/*`) DOĞRUDAN izlenen bir call-chain
trace + FARKLI bir hostile-character canary + FARKLI bir capture
mekanizması (httpx event hooks, `MockTransport`'a EK bir ikinci
bağımsız kanal) ile: `AsyncOAuth2Client`'ın tam olarak configured
secret + `client_secret_post` ile inşa edildiği, body'de `client_secret`
TAM OLARAK BİR KEZ (hostile karakterler `#!@$%^&*()_+-={}[]|;'",.<>?/~
\:` ve Unicode `éü` dahil doğru round-trip ederek), `Authorization`
header'ı OLMADIĞI, `client_assertion` OLMADIĞI, provider red'inde
(`invalid_client`) TEK istek yapıldığı ve exception mesajının canary'yi
hiçbir formda İÇERMEDİĞİ bağımsızca kanıtlandı. (2) gerçek production
`ui.main.app` nesnesi import edilip `ui.services.db.transaction`'a bir
sentinel enjekte edilerek: eksik secret'ta `db.transaction()`'ın SIFIR
KEZ girildiği (`count==0`), yanıt gövdesinin yalnız `"Internal Server
Error"` olduğu (secret/config detayı YOK); secret mevcutken
`db.transaction()`'ın GERÇEKTEN girildiği (`count==1`) — sınır
noktasının tam olarak `_load_provider_config()` olduğu, salt
korelasyon değil DOĞRUDAN kanıtlandı (11/11 PASS). Guard'ın kendi
pozitif kontrolü, bir throwaway child interpreter'da repo'nun GERÇEK
`.env` dosyasını `open()` ile açmaya deliberate olarak teşebbüs etti
— `sys.addaudithook` `open()` ANINDA, herhangi bir `.read()`'DEN ÖNCE
`PermissionError` fırlattı — SIFIR bayt okundu/yazdırıldı/saklandı/
iletildi; sweep boyunca **0 external network, 0 `.env` open olayı**
kaydedildi (implementer: 148 `GUARD_ARMED`; reviewer: 147
`GUARD_ARMED`, farkın nedeni subprocess-spawning modüllerdir — ikisi
de tutarlı).

**J. Korunan sınırlar** — Key Vault custody (Row 19D Slice 1/2) HİÇ
DEĞİŞMEDİ; deployment selector (`VERGI_KEY_PROVIDER_KIND`) HİÇ
DEĞİŞMEDİ; MFA/`acrs` (`mfa_adapter.py`, `validate_acrs_claim`) HİÇ
DEĞİŞMEDİ; cookie/session (`__Host-session`, `session_store.py`) HİÇ
DEĞİŞMEDİ; hosting/proxy (`ui/main.py`'nin loopback-only middleware'i,
Row 19A'nın reverse-proxy kontratı) HİÇ DEĞİŞMEDİ; migration/şema/
data/index HİÇ DEĞİŞMEDİ; gerçek hiçbir Azure/Entra/Graph/OIDC login
veya cloud işlemi bu turda YAPILMADI.

**K. Tüm Low/Observation kayıtları — hiçbiri kaybolmadı**

**F1 — Low/report-accuracy (bağımsız inceleme tarafından bulundu,
implementasyon dosyalarında DÜZELTİLMEDİ)**: implementasyon raporunun
"tüm altı dosya HEAD'de CRLF idi" iddiası YANLIŞTIR — `git show HEAD:
<path>` doğrudan kontrol edildiğinde altı dosyanın TAMAMI HEAD'de saf
LF'dir (hiç `\r` byte'ı yok). Working tree'de beş dosya (`oidc_client.
py`, `auth_routes.py`, `iam_bootstrap_probe.py`,
`test_oidc_client_isolated.py`, `test_auth_routes.py`) hâlâ saf LF'dir
— HEAD'den değişmemiştir, doğrudur. Yalnız `test_key_custody_isolated.
py`, working tree'de saf CRLF'dir (959 CR = 959 LF) — bu, HEAD'in
CRLF konvansiyonuna bir "restorasyon" DEĞİL, bir session artifact'idir
(çünkü öyle bir orijinal CRLF durumu hiç olmamıştır). İşlevsel/güvenlik
etkisi SIFIRDIR: `.gitattributes` `*.py` için bir EOL politikası
zorlamaz, `core.autocrlf=true` etkindir, bu yüzden gerçek bir `git
add`/`git commit` işlemi bu dosyanın CRLF'ini otomatik olarak LF'ye
normalize edecektir — nihai committed blob diğer beş dosyayla ve
HEAD'in kendi konvansiyonuyla tutarlı, LF olacaktır. **Bu roadmap-lock
turunda hiçbir kod dosyası değiştirilmemiştir** — bu, bir kod
remediasyonu DEĞİLDİR, yalnız raporun anlatısının bir doğruluk
düzeltmesidir; implementasyon dosyasının (`row19b_oidc_confidential_
client_remediation_impl_FINAL.md`) kendisi bu roadmap-lock turunda
DEĞİŞTİRİLMEMİŞTİR.

**F2 (O1) — Low, confirmed**: `dataclasses.asdict()`/`astuple()`/
`vars()`/`__dict__` `client_secret`'ı açığa çıkarır — Python
dataclass'larının doğal sınırıdır (`field(repr=False)` yalnız `repr`/
`str`'i bastırır). Repo-wide grep, `EntraProviderConfig`'i bu şekilde
serialize eden SIFIR mevcut caller'ı doğrular. Non-blocking; gelecekte
bir logging/observability aracının bu dataclass'a dokunması durumunda
radarda tutulmalı — bu dar remediation'ın kapsamı DIŞINDADIR.

**F3 (O2) — Low, confirmed**: `auth_routes._load_provider_config`
diğer yedi değişkeni `os.environ[...]` (ham `KeyError`, önceden var
olan, bu remediation'la ilgisiz) ile okurken secret'ı `.get()` ile
okur — asimetri deliberate'dir, TEK bir fail-closed otorite
(`__post_init__`) missing/empty/whitespace'i credential için tekdüze
kapsasın diye. Kozmetik tutarsızlık, doğru gerekçelenmiş.

**F4 (O3) — Observation, confirmed benign**: implementer'ın kendi
sweep-driver'ının canlı regex'i bare `N passed, M failed` özet
satırlarını KAÇIRDI ve driver'ın canlı toplamı (**3049**) implementer
tarafından AÇIKÇA "kullanılmamalıdır" olarak disclose edildi; nihai
tally (4154/0/8/14) ham logların offline yeniden-sayımından geldi.
Bağımsız inceleme TAMAMEN AYRI bir driver + offline re-tally
script'i (farklı regex, farklı özet-format handling) inşa etti ve
BAĞIMSIZCA AYNI final sayılara (4154 passed, 0 failed, 8 counted
skipped, 14 informational) ulaştı — altta yatan test sonuçları bu
yüzden sağlam olarak doğrulanmıştır; yalnız implementer'ın canlı
progress-counter'ı (asla final claim olarak kullanılmamış) hatalıydı.

**F5 (O4) — Observation, implementer tarafından disclose edilmiş,
bağımsızca düzeltilemez**: turun brief'i implementasyon için Sonnet
adını verdi; gerçek implementasyon oturumu **Claude Fable 5.1**
üzerinde, **iki advisor danışmasıyla** (biri işten önce, biri
kapanıştan önce) yürütüldü. Bağımsız incelemenin kendi model/oturumu
(Sonnet 5, xhigh, bu roadmap-lock turunun kendisi DEĞİL — inceleme
turu) implementasyon oturumundan bağımsızdır, hangi model
implementasyonu yaptığından bağımsız olarak. Yukarıdaki teknik
bulguların hiçbirine etkisi yoktur — hepsi kaynaktan ve canlı yeniden
çalıştırmadan bağımsızca yeniden türetilmiştir, implementer'ın sözüne
güvenilmemiştir.

**F6 (O5) — Observation, bu incelemenin kendi açık brief'ine
UYUMLU**: hem implementer'ın sweep'i hem bağımsız incelemenin kendi
sweep'i, fail-closed audit guard'ın GERÇEKTEN ateşlediğini kanıtlamak
için repo'nun gerçek `.env` dosyasını bir kez, throwaway/guarded bir
bağlamda açmaya deliberate olarak teşebbüs etti. Her iki durumda da
guard'ın `PermissionError`'ı `open()` ANINDA, herhangi bir `.read()`'
DEN ÖNCE ateşledi — SIFIR bayt okundu/yazdırıldı/saklandı/iletildi.
Bağımsız incelemenin kendi brief'i bu pozitif kontrolü AÇIKÇA talep
etmişti — bu bir sapma DEĞİL, uyumluluk kanıtıdır.

**L. Kalan external activation/adoption gate işleri** — Web/
confidential-client kod uyumsuzluğu (§H.1) bu remediation ile
KAPANDI. Ancak şunların HİÇBİRİ bu turda BAŞLAMADI/ÇÖZÜLMEDİ: gerçek
Entra tenant/app registration; client secret'ın gerçek güvenli
teslimatı/deployment'i (App Service Key Vault reference veya owner-only
env — deployment-gate matter, kod değil); certificate/`private_key_jwt`
credential hardening (kullanıcı kararıyla bu remediation'ın DIŞINDA
bırakıldı, gelecekteki bir hardening slice'ına ertelendi); Row 18
loopback-only middleware ile Row 19A `X-Forwarded-For` yasağının App
Service/Container Apps hosting üzerinde satisfiable OLMADIĞI bulgusu
(bağımsız Fable incelemesinin İkinci, önceden tespit edilmemiş bulgusu
— hosting default'u "resolved cleanly"den "OPEN"e düşürülmüştür, bu
remediation'ın KAPSAMI DIŞINDADIR); id_token-hedefli `acrs` claims
desteğinin gerçek tenant davranışı (`[EXTERNAL VERIFICATION
REQUIRED]`, optional-claims fallback'i değerlendirilmedi); Conditional
Access/authentication-context binding operator preflight'i (Graph
`Policy.Read.All`/`AuthenticationContext.Read.All` ile, henüz
YAPILMADI); Key Vault custom GET-only role (LOCKED Slice 2 kontratı)
deployment/adoption'ı; Graph izinleri ve tenant preflight'i; gerçek
login/smoke/rollback/rotation/adoption'ın HİÇBİRİ bu turda
BAŞLAMAMIŞTIR.

**M. LOCKED-file §9 gerekçesi** — `ui/services/oidc_client.py` ve
`ui/auth_routes.py`, downstream incompatibility (identity provider'ın
dokümante edilmiş token-endpoint sözleşmesiyle çelişki, §A/§E) ve
security posture (bir sunucu uygulamasının confidential client olarak
kendi kimliğini ispatlayamaması) gerekçesiyle, minimum-mümkün,
altı-dosyalık bir remediation ile dar biçimde yeniden açıldı;
`scripts/iam_bootstrap_probe.py` aynı `VERGI_ENTRA_CLIENT_SECRET`
sözleşmesine bağlanmak için additive olarak genişletildi; üç test
dosyası yalnız yeni sözleşmenin kalıcı kanıtı için additive/inverted
assertion'lar kazandı (LOCKED `"sends no client_secret"` assertion'ı
Fable'ın binding tasarımının açıkça talep ettiği TEK inversion'dır;
komşu `"sends no client_assertion"`/`"sends client_id"`/PKCE
assertion'ları KORUNMUŞTUR). Komşu LOCKED davranışlar (Key Vault
custody, MFA/`acrs`, cookie/session, deployment selector, hosting/
proxy — bkz. J) bu remediation ile DEĞİŞMEMİŞTİR; bu, `CLAUDE.md`
§9'un izin verdiği türden dar, izlenebilir bir yeniden-açılıştır, Row
19B'nin genel contract'ını yeniden yorumlamaz. Bu yeniden açılış, bu
checkpoint (roadmap-lock) ile KAPATILMIŞTIR — Row 19B, bu remediation
sonrasında yeniden DONE / LOCKED'dır.

**N. Final verdict**

ROW 19B OIDC CONFIDENTIAL-CLIENT REMEDIATION LOCK-READY — NO BLOCKING FINDINGS

**DONE / LOCKED**

### Fact Verification Workflow (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — Fact/timeline/deadline doğrulama
durumunun insan tarafından kontrollü ve auditli biçimde değiştirilmesi
için bir mekanizma yoktu: production yolunda hiçbir writer bir fact'i
`verified`/`partially_verified` yapamıyordu, bu yüzden gerçek deadline
zinciri kalıcı olarak `blocked_unverified_anchor` durumunda kalıyordu.
Bu slice bu yapısal engeli kaldırır — Pilot Readiness Priority
Reconciliation'ın sıralamasında **Adım 1**'dir.

**B. Exact kapsam** — Kullanıcı tarafından onaylanmış tam dosya
allowlist'i: **6 YENİ + 12 DEĞİŞTİRİLMİŞ = 18 dosya**.

Yeni (6):
1. `src/fact_verification.py`
2. `ui/services/fact_verification_mutation_facade.py`
3. `ui/services/fact_verification_mutation_adapters.py`
4. `ui/tests/test_fact_verification_isolated.py`
5. `ui/tests/test_fact_verification_mutation_facade_isolated.py`
6. `ui/tests/test_fact_verification_mutation_integration_postgres.py`

Değiştirilmiş (12):
7. `ui/cli_mutate.py`
8. `ui/reconciliation_operator.py`
9. `ui/services/promotion_mutation_facade.py`
10. `ui/tests/test_cli_mutate_isolated.py`
11. `ui/tests/test_reconciliation_isolated.py`
12. `ui/tests/test_reconciliation_operator_isolated.py`
13. `ui/tests/test_agent_generation_mutation_integration_postgres.py`
14. `ui/tests/test_drafting_request_mutation_integration_postgres.py`
15. `ui/tests/test_fact_extraction_mutation_integration_postgres.py`
16. `ui/tests/test_legal_research_case_law_mutation_integration_postgres.py`
17. `ui/tests/test_rag_bundle_mutation_integration_postgres.py`
18. `ui/tests/test_promotion_mutation_facade_isolated.py`

Remediasyon alt kapsamı (0 YENİ + 5 DEĞİŞTİRİLMİŞ, yukarıdaki 18
dosyanın İÇİNDE):
- `ui/services/fact_verification_mutation_adapters.py`
- `ui/services/fact_verification_mutation_facade.py`
- `ui/tests/test_reconciliation_isolated.py`
- `ui/tests/test_fact_verification_mutation_facade_isolated.py`
- `ui/tests/test_fact_verification_mutation_integration_postgres.py`

Sıfır schema, migration, UI/web route, production case verisi ve
cloud değişikliği.

**C. Action family ve identity** — `action_family = verification.fact`,
CLI-only. `target_ref = fact.<document_id>.<fact_id>.verification`.
`resource_key = case:<case_id>`. `attempt` identity bileşenidir
(`pre_revision`'a girer); varsayılan **1**; otomatik ARTIRILMAZ.
`--note` ve `--idempotency-key` CLI'da TANIMLANMADI (argparse
"unrecognized arguments", exit 2, sıfır I/O). Aynı byte-state'e
dönülen bir revision cycle'da `--attempt N+1` açık operatör çıkış
yoludur. Immediate genuine replay stored result döndürür (writer
ikinci kez çağrılmaz). Gerçek request conflict (farklı target/evidence)
fail-closed kalır.

**D. State ve evidence sözleşmesi** — State'ler: `unverified`,
`partially_verified`, `verified`. Altı gerçek transition kabul edilir;
üç self-transition (`u→u`, `p→p`, `v→v`) fail-closed reddedilir, sıfır
journal satırı. `verified`/`partially_verified` hedeflerinde
`--evidence-ref` ZORUNLU; `unverified` hedefinde opsiyonel. İzinli
evidence kümesi `{source_document_id} ∪ related_document_ids` —
başka HİÇBİR belge kabul edilmez; evidence belgesi `active is True`
(identity kontrolü, truthiness değil). Pozitif (verified/
partially_verified) hedef için mevcut source locator ZORUNLU
(locator'sız fact'te `partially_verified` de reddedilir — validator'dan
daha güçlü business rule). `--note` reddedildi. Otomatik downstream
cascade YOK.

**E. Writer ve facade** — Raw/legacy writer bypass YOK; `verified_paths`
ZORUNLU. Canonical serializer TEK kaynak: mevcut `fact_approval`
primitive'i (`_canonical_json_bytes`/`_canonical_json_text`) yeniden
kullanılır, yeniden yazılmaz. LF/CRLF yapısal olarak kabul edilir
(key-order/indent farkı fail-closed reddedilir — ama bkz. F5 için
gerçek sınır). History backup (O_EXCL), atomic `os.replace`,
post-write validation + parse-back, audit (O_EXCL) ve herhangi bir
adım başarısız olursa canonical byte-bayt rollback. Outer + under-lock
authz (iki katman). Stale-hash, composite race ve evidence race
fail-closed. Completed replay bağımsız audit corroboration gerektirir
(sessiz başarı yok). Exact stale-downstream blok literal'leri:
`STALE_DOWNSTREAM` / `RERUN_ORDER` / `NO_COORDINATED_PATH`.

**F. Reconciliation ve F1 kapanışı** — İlk implementasyon, eksik
binding nedeniyle bağımsız incelemede **NOT LOCK-READY** kaldı.

İlk bağımsız review **F1 (Medium)**: reconciliation adapter'ın
(`_audit_record_matches`) ve facade'in completed-replay corroboration'ının
(`_verify_completed_replay_binding`) yalnız dar bir alan kümesini
(idempotency_key, resource_key, action_family, target_ref,
canonical_sha256(after), outcome, `identity_payload→pre_revision`)
bağladığı; onaylı Fable §I kontratının ZORUNLU saydığı
`mutation_actor_ref == entry.actor_label`, `request_fingerprint`
recompute, `history_backup_path` containment+mevcudiyet+hash eşitliği,
`from_state`/`target_state`/`document_id`/`fact_id` tutarlılığının
BAĞLANMADIĞI; tamper matrisinin (actor/state/evidence/secondary/
attempt/document-fact-id/history-backup/`request_fingerprint`
tamper'ları dahil 13/13) HEPSİNİN kabul edildiği; emsal adapter'ların
(`fact_extraction_mutation_adapters.py`, `agent_generation_mutation_adapters.py`)
actor_label VE history backup'ı bağladığı, bu ailenin emsalden GERİ
olduğu tespit edildi.

Remediasyon sonrası: adapter (`_full_binding()`) ve facade
(`_replay_audit_fully_bound()`) ayrı, bağımsız iki full-binding
matcher taşır (biri diğerini import etmez; yalnız karar-içermeyen
generic `path_containment`/`mutation_guard` primitive'leri paylaşılır).
Bağlanan alanlar: outcome, idempotency_key, resource_key, actor_ref
(journal `actor_label` ile), action_family, target_ref, target_ref'ten
ayrıştırılan document/fact id, audit doc/fact ↔ canonical hedef fact,
`target_state`, `from_state` (backup'taki state ile + `from ≠ target`),
evidence_document_id ↔ `secondary_input_hash` tutarlılığı, `attempt`
(bool reddi, `identity_payload.attempt` ile eşleşme), `identity_payload`
exact key seti + `pre_revision` bağımsız recompute,
`canonical_sha256_before`, `request_fingerprint` audit alanlarından
yeniden kurulup journal ile eşitlik, `canonical_sha256`(after) diskten,
`history_backup_path` containment (absolute/relative escape, junction,
traversal, dizin-olarak-dosya reddi), backup sha ==
`history_backup_sha256` == `canonical_sha256_before`, backup JSON parse
+ `source_document_id`/`from_state` tutarlılığı, exactly-one full-binding
audit, corrupt/duplicate audit fail-closed.

Final re-review kanıtı: adapter tarafında **28 tamper sınıfı** gerçek
PostgreSQL + gerçek `reconcile_and_apply_journal_entry` (gerçek
registry) üzerinden test edildi; diagnostic toplamı dürüstçe **"142
DIAG-PASS + 2 reviewer-grep harness DIAG-FAIL"** olarak kaydedildi —
iki DIAG-FAIL ürün kusuru DEĞİLDİR, reviewer'ın kendi statik grep
kontrolünün yorum/docstring metnine takılmasıdır (gerçek adapter→facade/
facade→adapter import topolojisi kaynaktan ayrıca doğrulandı). Facade
replay tarafında **70/70 diagnostic** (aynı 28 sınıf + journal
`observed_post_hash` SQL tamper'ı). Gerçek `mklink /J` junction ve
kırık junction reddi ampirik olarak kanıtlandı. Pozitif kontroller,
matcher'ların koşulsuz red OLMADIĞINI (untampered → `post_state_
verified=True`, gerçek reconciliation → `completed`) gösterdi.

`observed_post_hash` disposition (§F1 remediasyonunun bir parçası,
KAPATILAN bir sapma olarak kaydedilir): non-terminal `JournalEntrySnapshot`
`observed_post_hash` alanı TAŞIMAZ — adapter'ın görevi bu değeri
DİSKTEN ÜRETMEKTİR, önceden var olan bir değeri doğrulamak DEĞİLDİR;
terminal `completed` yazımı bu evidence'tan yapılır. Facade'in completed
replay yolu, journal `observed_post_hash`'i AYRICA doğrular (adapter'dan
bağımsız ikinci bir kontrol noktası). Final re-review bu sapmayı **ACCEPT**
etti — bu bir güvenlik boşluğu değil, non-terminal reconciliation
sözleşmesinin doğru sonucudur; açık bir Medium bulgu KALMADI.

**G. F2 kapanışı** — İlk bağımsız review **F2 (Medium)**:
`pre_revision` yalnız `(canonical_sha256, attempt)`'ten türediği için,
3-durumlu ve geri alınabilir bir alanda döngü (ör. `u→v→u`) canonical
baytlarını önceki bir revizyona geri getiriyordu; aynı aktör +
`attempt=1` için identity daha önceki TAMAMLANMIŞ bir journal satırıyla
ÇAKIŞIYORDU — rutin bir aynı-transition tekrarı coordinator'da "safe
replay" sanılıp facade corroboration'ında yanıltıcı bir "audit-binding
failed / insan reconciliation'ı gerekir" hatasına düşüyordu; farklı bir
transition ise generic conflict veriyordu.

Remediasyon: identity formülü ve genel coordinator DEĞİŞTİRİLMEDİ;
genuine replay ayrımı korundu. Yeni `FactVerificationRevisionCycleConflictError`
(sabit mesaj, `--attempt N+1` yönlendirmesi, "otomatik ARTIRILMAZ"
uyarısı içerir; path/tmp/evidence-id/`reconciliation` kelimesi
İÇERMEZ) ve yeni `FactVerificationIdentityConflictError`
(hem `ApprovalUiError` HEM `IdempotencyConflictError` alt sınıfı,
mevcut `except IdempotencyConflictError` yollarını ve CLI'nın
`_is_known_domain_error` sınıflandırmasını bozmadan) eklendi. Tampered
bir audit ASLA cycle diye sınıflandırılmaz (full-binding kontrolü
ÖNCE koşar). `attempt` otomatik artırılmaz; `--attempt N+1` açık
operatör çıkış yoludur. Stale hash + artırılmış attempt HÂLÂ
`StaleViewError` verir (attempt staleness'ı BYPASS ETMEZ). State/
self-transition kuralları attempt ile bypass edilemez.

Final kanıt: F2 diagnostic **31/31**; MRO/CLI hata sınıflandırma
diagnostic'i **11/11**; gerçek PostgreSQL + gerçek CLI ile **12 adımlı**
attempt N+1 zinciri (ilk transition → immediate replay → h0'a dönüş →
aynı transition attempt=1 → RevisionCycleConflict → farklı target/
evidence attempt=1 → IdentityConflict → stale hash + attempt=2 →
StaleViewError → doğru hash + attempt=2 → başarı + yeni full-binding
audit → immediate replay(attempt=2) → attempt=3 self-transition →
NoOpError → tampered eski audit cycle'a asla düşmez). Red yollarının
HEPSİNDE sıfır yeni mutation/journal/audit/history.

**H. F3 kapanışı** — F7d/F7e testindeki `check(..., True)` false-PASS
dalı KALDIRILDI; gerçek `related_document_ids` dolu bir fact
(`facts[1]`) dinamik olarak bulunur, fixture yoksa `AssertionError`
(skip/koşullu PASS yok). Farklı-evidence conflict
(`secondary_input_hash` yolu) artık GERÇEKTEN çalışır ve test edilir.
F12a fixture'ı (eski `actor_label="iam_user"` — actor TİPİ) ve
reconciliation `(b)` fixture'ı (`secondary_input_hash=None` — kontratla
tutarsız) production sözleşmesine bağlandı (journal'ın gerçek `actor_ref`
değeri, gerçek `_compute_secondary_input_hash`). Final re-review bu
fixture düzeltmelerini ACCEPT etti — kanıt gücü ARTTI, hiçbir assertion
gevşetilmedi.

**I. Re-promotion guard** — Verified/partially_verified fact varsa
re-promotion varsayılan olarak fail-closed reddedilir; pre-lock VE
kilit-altı guard (iki kez). Explicit `--discard-verified-states`
gerekir. `src/fact_approval.py` READ-ONLY kaldı. Override'ın audit'te
açıkça kayıtlı OLMAMASI **F6 Low** olarak açık kalır (bkz. §O).

**J. Downstream gerçek zincirler** — Gerçek production fonksiyonları
kullanılarak (mock/warning-string DEĞİL) kanıtlandı:
- Gerçek `evidence_engine` `facts_input_hash` staleness'ı.
- Gerçek `evidence_validator` STALE INPUT ERROR.
- Gerçek `timeline_validator` downgrade ERROR.
- Gerçek `verification.fact → generation.timeline → promotion.timeline`
  zinciri, HEM upgrade HEM downgrade yönünde.
- Gerçek deadline zinciri: `blocked_unverified_anchor` → fact
  `verified` → timeline regenerasyonu/promosyonu → gerçek
  `generation.deadline` → `calculated`, `calculated_deadline=
  2026-03-12`, rule `iyuk_tax_court_general_lawsuit_filing` → gerçek
  `approval.deadline` → canonical `deadline.json`.
- Gerçek iki-fact concurrency: iki aktör, aynı belge, iki farklı fact;
  gerçek `pg_locks` üzerinden İKİ GERÇEK waiting satırı gözlemlendi;
  dinamik kilit sırasına göre TAM BİR winner tam başarı, DİĞERİ düz
  `StaleViewError`; tek journal/audit satırı; loser fact HİÇ
  değişmedi.
- Windows junction/path-escape matrisi (8 escape senaryosu, gerçek
  `mklink /J`) + repo-dışı `sys.addaudithook` ile pozitif-kontrollü
  proof-of-non-access (dış kök altında sıfır open/scandir/listdir
  olayı).

**K. Test kanıtı — aşamalar karıştırılmadan**:

İmplementasyon finali: targeted testler geçti; full sweep **70/70,
4394 passed, 0 failed, 8 counted skip, 14 informational skip**.

İlk bağımsız review: aynı **70/70** ve **4394/0/8/14** bağımsız olarak
yeniden üretildi; buna RAĞMEN F1/F2 Medium nedeniyle **NOT LOCK-READY**.

Remediasyon implementasyonu (final kod, guard ARMED, gerçek disposable
PostgreSQL): facade **149/0**; PostgreSQL integration **91/0/0**;
reconciliation **313/0**; reconciliation operator **95/0**; writer
**33/0**; CLI **240/0**; full sweep **70/70, 4490 passed, 0 failed, 8
counted skip, 14 informational skip**.

Final bağımsız re-review: hedefli sayılar (facade 149/0, PostgreSQL
integration 91/0/0, reconciliation 313/0, reconciliation operator
95/0, writer 33/0, CLI 240/0) birebir bağımsız yeniden üretildi; full
sweep **70/70, 4490/0/8/14** — yalnız ÜÇÜNCÜ, kesintisiz sweep kanıt
sayıldı: ilk iki sweep denemesi reviewer'ın KENDİ guard/secret-scrub
harness hatası (loopback guard'ın asyncio self-pipe'ı bloklaması;
secret-scrub filtresinin `VERGI_IAM_DATABASE_URL`'i de silmesi)
nedeniyle iptal edilip DB sıfırlanarak (DROP+CREATE) baştan
çalıştırıldı — bu iki aşamanın sonuçları KANIT SAYILMADI. Hiçbir skip
PASS sayılmadı.

**L. Güvenlik/invariance** — Sıfır external Python-level network;
sıfır DNS; sıfır gerçek `.env` open (guard pozitif kontrollerle
kanıtlandı — yem `.env`, `example.invalid` DNS, `203.0.113.1:9`
connect üçü de BLOKLANDI). Açık, yapısal sınır: `sys.addaudithook`
guard'ı libpq'nün C-seviyesi bağlantılarını GÖREMEZ — "0 external
network" iddiası Python-seviyesi socket'lerle SINIRLIDIR; gerçek
PostgreSQL sınırının asıl dayanağı child ortamlarının DSN'lerinin
`127.0.0.1` + disposable cluster'a PİNLENMESİDİR (audit-hook sayacı
değil). Protected manifest (`data/**`+`index/**`+`db/migrations/**`+
`CLAUDE.md`, 121 dosya): **byte-identical**. `case_0001` (65 dosya):
**byte-identical**. Branch/HEAD/stash/staged değişmedi. PostgreSQL ve
temp residue temizlendi.

**M. Sayaçlar (final)** — production Python **153**; test modülü
**70**; merged reconciliation routing key **50**; logical mutation
family **38**; CLI subcommand **6** (`approval, review, promotion,
generation, rag-bundle, verification`); migration **5**.

**N. Dürüst kronoloji ve süreç sapmaları**:

1. Read-only scope draft.
2. Fable scope review ve corrected exact 18-path karar (Fable FINAL'in
   kendi F1 High bulgusu: taslağın koşullu allowlist'i mekanik olarak
   yanlıştı — `test_promotion_mutation_integration_postgres.py` sayım
   assertion'ı TAŞIMIYORDU, `test_legal_research_case_law_mutation_
   integration_postgres.py` ve `test_rag_bundle_mutation_integration_
   postgres.py` (2 site) taşıyordu ve taslakta YOKTU; §M kaynaktan
   yeniden türetilmiş exact 18-dosyalık FINAL allowlist verdi).
3. Kullanıcı onayı.
4. İlk implementasyon (Sonnet 5) — kendi devam turunda 5 zorunlu kanıt
   kategorisini (downstream staleness, timeline propagation, deadline
   blocked→calculated, Windows junction matrisi, iki-farklı-fact
   concurrency) tamamladı; dört test-harness bug'ı (production kodu
   ETKİLEMEYEN) bulunup düzeltildi.
5. İlk bağımsız review (Claude Fable 5.1 — implementasyon oturumundan
   model VE bağlam olarak bağımsız): **F1 Medium**, **F2 Medium**,
   `NOT LOCK-READY`.
6. Exact 5-file remediasyon — bu tur fiilen **Claude Fable 5.1**
   üzerinde yürütüldü (talimat "Sonnet oturumunun devamı" derken fiili
   model Fable 5.1'dir, kendi raporunda açıkça beyan edilmiştir).
7. Final bağımsız re-review — bu tur da **Claude Fable 5.1** üzerinde
   yürütüldü; remediasyon oturumuyla **model bağımsızlığı YOKTUR**,
   yalnız OTURUM/BAĞLAM bağımsızlığı vardır (remediasyon oturumunun
   bağlamı/ara adımları/diagnostic'leri/fixture'ları bu oturumda
   mevcut değildi, hiçbir remediasyon komutu bu oturumda çalıştırılmadı).
   (İlk implementasyon→ilk bağımsız review çifti — Sonnet 5 → Fable
   5.1 — GERÇEKTEN model-bağımsızdır; yalnız remediasyon→re-review
   çifti model-bağımsız DEĞİLDİR.) Final verdict:
   `FACT VERIFICATION WORKFLOW LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`

Ayrıca: final re-review talimatı advisor/alt-ajan kullanımını
YASAKLIYORDU, ancak reviewer advisor'ı İKİ kez çağırdı — bu sapma
kendi raporunda AÇIKÇA disclose edilmiştir. İlk çağrı yalnız YÖNTEM
danışmasıydı (tamper matrisinin nasıl kurulacağı, hangi kaynak
gerçeklerinin önce doğrulanacağı). İkinci çağrı, rapor yazıldıktan
SONRA bir tamamlanmışlık kontrolüydü (üç ifadeyi düzeltti: §1.5'e
pinlenmiş DSN cümlesi, N2'ye bağlanmayan audit alanlarının listesi,
§18'in temizlik zaman kipi). Hiçbir bulgu, sayı veya verdict
advisor'dan ALINMADI — N2'deki alan listesi dahi advisor'ın iddiasına
güvenilmeden kaynaktan grep ile bağımsızca doğrulandı. Alt ajan
ÇAĞRILMADI. Bu süreç sapması GİZLENMEZ, ama güvenlik sonucunu
DEĞİŞTİRMEMİŞTİR — F1/F2 kapanışının kanıtı (kaynak inceleme +
bağımsız tamper matrisi + gerçek PostgreSQL diagnostic'leri) tamamen
bu oturumun kendi çalıştırdığı, advisor'a hiç sorulmayan kontrollere
dayanır.

**O. Açık Low bulgular — KAPATILMIŞ GÖSTERİLMEZ**:

- **F4 (Low, AÇIK):** audit yazımı fd açıldıktan sonra çökerse partial
  audit dosyası için unlink YOK (boş dosya kalır, reconciliation
  dual-false); `facts.json.tmp` artığı kalabilir; rollback-of-rollback
  `FactVerificationRollbackFailedError` orijinal exception'ın YERİNE
  fırlar; history backup fsync'siz. Hepsi fail-closed.
- **F5 (Low, AÇIK):** "key-order sapması reddi" iddiası kısmen
  YANLIŞTIR — referans serializer `sort_keys` KULLANMAZ, JSON
  round-trip key sırasını KORUR (yeniden sıralanmış top-level
  key'lerle canonical KABUL edilir); yalnız `indent` farkı reddedilir.
  Writer docstring'i, facade başlığı ve önceki rapor(lar) aksini
  söyler — bu ifade YANLIŞTIR. İşlevsel güvenlik etkisi YOK (writer
  aynı sırayı yazar, bayt-invariance korunur).
- **F6 (Low, AÇIK):** `--discard-verified-states` override'ı hiçbir
  audit alanında AÇIKÇA kayıtlı DEĞİLDİR (yalnız promotion history
  backup içeriğinden dolaylı çıkarılabilir); `_count_verified_states`
  okunamayan/parse edilemeyen canonical'ı **0** sayar — bozuk bir
  canonical'daki verified state'ler sessizce atılabilir (fail-open
  guard davranışı). Bu slice'ta DÜZELTİLMEDİ.
- Cross-case isolation için dedike, kalıcı bir test HÂLÂ YOKTUR
  (yalnız outer-authz testleri + bağımsız incelemenin diagnostic'i ile
  dolaylı kapsanır).
- Writer'ın post-write hash uyuşmazlığı için ayrı, isimli bir exception
  sınıfı (`FactVerificationWriterPostStateMismatchError` gibi) HÂLÂ
  TANIMLANMADI — çıplak `ValueError` → `reconciliation_required`
  (davranış doğru, yalnız isimlendirme kozmetik eksik).

**P. Eski Observation kayıtları — eksiksiz korunur**:

- **O1:** Adapter dosyasındaki "ONBİRİNCİ"→"ONUNCU" ifadesi
  remediasyon turunda DÜZELTİLDİ (allowlist içi); `ui/reconciliation_
  operator.py`'deki "SIXTH facade/adapter pair" kozmetik numaralandırması
  AÇIK kalır (o dosya remediasyon allowlist'i dışındadır).
- **O2 (AÇIK):** `FactVerificationFactNotFoundError` mesajı mutlak
  canonical path içerir (promotion emsaliyle aynı desen, yalnız
  yetkili aktöre görünür); audit `history_backup_path` alanı mutlak
  yerel path taşır.
- **O3 (AÇIK, gözlendi):** Bazı testler (facade-isolated,
  reconciliation-isolated) sentetik case dizinini GERÇEK
  `data/cases/` ağacının içinde oluşturup `finally`'de siler — emsal
  desendir; byte-invariance her turda ayrıca kanıtlanmıştır.
- **O4:** Önceki bağımsız incelemede `.git/FETCH_HEAD`'in oturum dışı
  bir git fetch (harness/IDE) tarafından güncellendiği gözlemlenmişti
  — hiçbir ref hareket etmedi (reflog/HEAD/stash aynı kaldı). Final
  re-review turunda bu konuda YENİ bir gözlem YOKTUR.
- **O5 (AÇIK):** CLI `verification` preview çıktısı, evidence
  zorunluluğunu hedef state'e göre açıklamaz (`--evidence-ref` yalnız
  genel şablonda gösterilir).
- **O6 (AÇIK):** Writer, `history_dir`/`reviews_dir`'i
  `mkdir(parents=True, exist_ok=True)` ile oluşturur (Fable'ın
  `resolve_for_create` beklentisinden sapma; facade zaten kilit
  altında containment doğruladığı için pratik risk düşük).

**Q. Yeni N1–N6 Observation kayıtları (final re-review'un kendi
bulguları — hiçbiri kaybolmaz)**:

- **N1 (Observation):** `target_ref`'ten doc/fact ayrıştırmasının
  (`rsplit(".",1)`) tekliği bugün şema `^[a-z0-9_-]+$` pattern'ine
  (fact_id/document_id'de nokta yasak) DAYANIR; `path_containment.
  validate_segment` noktayı KENDİ BAŞINA yasaklamaz. Bugün canonical'a
  girebilen hiçbir id nokta taşıyamaz; ileride şema gevşerse parse
  belirsizleşebilir — gelecek hardening notu.
- **N2 (Observation):** Adapter `_full_binding` ve facade
  `_replay_audit_fully_bound`, audit'in KAPALI bir anahtar setini
  ZORLAMAZ — bogus bir ek anahtar (ör. sahte `request_fingerprint`)
  eklenmiş bir audit yine KABUL edilir. Writer'ın 27 alanlık audit
  setinden matcher'ların BAĞLAMADIĞI dokuz alan: `schema_version`,
  `audit_type`, `case_id`, `evidence_document_sha256`,
  `source_locator_present`, `source_locator_sha256`, `channel`,
  `reviewer_ref`, `generated_at`. Audit `case_id` alanı özellikle
  `resource_key`'den türetilen case_id ile KARŞILAŞTIRILMAZ — ama
  dosya konumu yalnız `resource_key`→case_id türetimiyle belirlendiği
  için yanlış bir audit `case_id`'si hiçbir şeyi YÖNLENDİREMEZ; güvenlik
  etkisi YOKTUR, audit-şekil sertleştirme adayıdır.
- **N3 (Observation):** Facade replay, journal `actor_label` kolonunu
  DOĞRUDAN OKUMAZ — actor bağı `intent.actor_ref` (idempotency
  identity'sinin parçası) üzerinden DOLAYLIDIR. Yalnız DB-yazma
  yetkili bir tamper adapter reconciliation'da YAKALANIR.
- **N4 (Observation):** `FactVerificationIdentityConflictError`'ın
  sabit mesajı, generic exception'ın taşıdığı `journal_id`/
  `idempotency_key`'i kullanıcı mesajından DÜŞÜRÜR (yalnız `__cause__`
  üzerinden erişilebilir) — azalmış operatör tanısı, fail-closed
  davranışın kendisi doğrudur.
- **N5 (Observation, tasarım özelliği, disclosed):** Identity slotu
  `(canonical_sha256, attempt)` aynı aktörün AYNI byte-state'ten
  yaptığı TÜM transition'larca PAYLAŞILIR — bir state'ten çıkıp aynı
  byte-state'e dönüldükten sonra o state'ten yapılacak FARKLI bir
  transition da attempt-1'de IdentityConflict alabilir; Fable §E'nin
  "`--attempt N+1`" sözleşmesiyle TUTARLIDIR.
- **N6 (Observation, harness sınıfı):** `sys.addaudithook` guard'ları
  libpq'nün C-seviyesi bağlantılarını GÖREMEZ; bu turun ve önceki
  turların "0 external connect" iddiaları Python-seviyesi socket'lerle
  SINIRLIDIR (bkz. §L).

**R. Kalan pilot sırası**:

- Pilot Readiness Adım 0 (kullanıcı kararı) tamamlandı: ilk pilot
  concierge; Entra/P1 Adım 11'e ertelendi; hosting/Key Vault Adım
  12'ye ertelendi.
- Pilot Readiness Adım 1 — Fact Verification Workflow — **DONE /
  LOCKED** (bu checkpoint).
- Pilot Readiness Adım 2 — Case-Data Repository Protection — yalnız
  **read-only exact-scope reconciliation** olarak **ACTIVE / NEXT**
  (bkz. §5).
- Pilot Readiness Adım 3 ve sonrası BAŞLAMAMIŞTIR.
- Corpus acquisition/population bu görevle BAŞLAMAMIŞTIR.
- Roadmap-lock (bu checkpoint) commit EDİLMEDEN Adım 2 implementasyonu
  BAŞLAMAZ.

`FACT VERIFICATION WORKFLOW LOCK-READY — F1/F2 CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde
olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir
roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Pilot Readiness Adım 2 — Case-Data Repository Protection (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve final karar** — Bu slice, gerçek/yeni dava verisinin
normal Git staging yoluyla (`git add -A`, `git add .`, bir IDE'nin
"stage all"ı) kazara commit edilme riskini **dar** biçimde kapatır.
Bu, repo-dışı storage, encryption, masking veya veri-sızıntısının
diğer tüm yollarını (manual zip/e-posta/cloud-sync, `git add -f`,
zaten-tracked bir dosyaya gerçek veri yazımı, `git clean -fdx`/`git
stash --all`) kapatmaz — bu ayrım kasıtlı ve §O'da dar biçimde
kaydedilmiştir. Durum: **DONE / LOCKED**. Final verdict, exact olarak:
`PILOT READINESS STEP 2 CASE-DATA REPOSITORY PROTECTION LOCK-READY — NO BLOCKING FINDINGS`.

**B. Exact implementation scope** — **1 YENİ**:
`ui/tests/test_case_data_gitignore_guard_isolated.py`. **1
DEĞİŞTİRİLMİŞ**: `.gitignore`. **0** migration, **0** schema, **0**
production Python, **0** production data, **0** `case_0001` mutasyonu,
**0** implementasyon-anı `CLAUDE.md` değişikliği. Configurable-root
Slice 2 bu turda YOKTUR.

**C. Exact `.gitignore` sözleşmesi** — Exact tek pattern `/data/cases/`
— root-anchored, trailing-slash (yalnız dizin), negation YOK. Diff: 1
güvenlik-kuralı satırı + 4 yorum satırı + 1 boş ayırıcı satır = **6
insertion, 0 deletion**, tek `@@` hunk. LF-only, ASCII, final newline
var, 0 CR bayt. Eski tracked `case_0001` dosyaları ETKİLENMEZ; yeni
untracked case dosyaları ignore edilir; `/data/cases/` dışındaki
ilgisiz yollar (`data/schemas/`, `data/documents.json`,
`db/migrations/` vb.) bu kuralla ignore EDİLMEZ (bkz. M N1).

**D. `case_0001` tracked/untracked sınırı** — 65 tracked canonical
fixture dosyası korunur; tracked edit/delete görünür ve stageable
kalır. Yeni fixture dosyaları varsayılan olarak ignore edilir; kasıtlı
fixture ekleme açık `git add -f` + ayrı review gerektirir. Gerçek dava
verisi ASLA `case_0001` içine konmamalıdır. Yeni review/history fixture
artefaktları için fixture-drift protokolü: `git status --ignored --
data/cases/case_0001` + seçici, incelenmiş force-add.

**E. Kalıcı test sözleşmesi** — `ui/tests/test_case_data_gitignore_
guard_isolated.py`: production `.gitignore` baytlarını verbatim okur
(SHA-256 eşitliği assert edilir); disposable temp Git repository
kurar; fixture guard'dan ÖNCE commit edilir (gerçek tarihi yansıtır);
production baytlarından kuralı çıkaran bir rule-stripped pozitif
kontrol taşır (non-tautology); tracked edit/delete; new file/nested/
new case/stray dosya senaryoları; `add -A`/`add .`/force-add; root
anchoring (`other/data/cases/...` ignore edilmez); gerçek repo üzerinde
YALNIZ read-only `check-ignore --no-index` ve `ls-files`; Git yoksa
pure-Python kontroller + informational skip; gerçek repo içine sentetik
dosya YAZMAZ; temp cleanup ve production bytes invariance assert eder.

**F. Dürüst kronoloji** — 1) Sonnet scope DRAFT: 0 NEW + 1 MODIFIED ve
iki-pattern (`data/cases/*` + `!data/cases/case_0001`) önerisi. 2) İlk
Fable scope review: iki-pattern önerisini REDDETTİ; tek `/data/cases/`
+ kalıcı test kararını verdi; READY verdict; **advisor yasağını bir
kez ihlal etti** (kendi raporunda disclose edilmiş). 3) İmplementasyon:
**aynı Fable review oturumunda** yapıldı — model/bağlam bağımsızlığı
YOKTU; advisor **bir kez daha** kullanıldı; ilk test-harness ordering
bug'ı (`build_repo()` guard'lı `.gitignore`'u fixture'ların ilk `add
-A`'sından ÖNCE yazıyordu) düzeltildi; advisor sonrası üç küçük test
iyileştirmesi yapıldı (özet-satırı formatı, `onexc`, real-repo probe
global-config izolasyonu); implementer full sweep ÇALIŞTIRMADI. 4) Ayrı
bağımsız Fable review: yeni, temiz bir oturum; advisor VE alt ajan
KULLANILMADI; bütün yük taşıyan iddialar yeniden üretildi; full sweep
boşluğunu KAPATTI; `LOCK-READY` verdict. Süreç sapmaları (2 ve 3'teki
advisor kullanımı, implementasyon/ilk-review model/bağlam
bağımsızlığının yokluğu) GİZLENMEZ ve teknik bulgularla
KARIŞTIRILMAZ — bunlar bağımsız değildi, ama 4. adım GERÇEKTEN
bağımsızdı ve tüm yük taşıyan iddiaları kaynaktan yeniden üretti.

**G. Implementer test kanıtı — ayrı etiket** — Hedef `vergi_ui_runtime`
interpreter'ı, `-W error::DeprecationWarning`: **48 passed, 0 failed**.
Root `.venv`, aynı bayrak: **48 passed, 0 failed**. Plain hedef
interpreter (PASS satırı sayımı): **48 PASS**. Full 71-modül sweep
implementer tarafından ÇALIŞTIRILMADI (gerekçe: değişiklik hiçbir
Python production modülüne dokunmaz). İlk test-harness ordering bug'ı
ve düzeltmesi §F'de dürüstçe kaydedilmiştir.

**H. Bağımsız test/diagnostic kanıtı — ayrı etiket** — Reviewer'ın
kendi Git laboratuvarı: **79 LAB-PASS / 0 LAB-FAIL** (pozitif kontrol +
iki `core.autocrlf` varyantı). Fault-injection: **21/21** enjekte
edilmiş bozulma varyantı (V1-V17, V6b, V8b, V9b, V10b, V11b, V11c,
V12-V15) test tarafından REDDEDİLDİ. Targeted (bağımsız, ayrı koşular):
hedef interpreter **48/0**; root `.venv` **48/0**; plain **48/0**;
no-git **10/0 + 3 informational skip**. Full PostgreSQL sweep
(bağımsız, kendi fresh disposable PostgreSQL 16.15 kümesi, migration
0001-0005): **71/71 modül exit 0; 4538 passed; 0 failed; 8 counted
skipped; 14 informational skipped**. Implementer ve reviewer sayıları
AYRI koşulardan gelir, TEK bir sonuçmuş gibi BİRLEŞTİRİLMEZ.

**I. Network, `.env` ve process guard** — Full sweep sırasında **151**
Python process `GUARD_ARMED`; **150** connect'in TAMAMI loopback
PostgreSQL (`127.0.0.1`); **0** DNS; **0** external connect; **0**
`.env` open. Git subprocess'leri local-only (`fetch`/`push`/`pull`/
`clone`/`remote`/`ls-remote`: **0**). Gerçek repo üzerinde testin
çalıştırdığı yalnız iki read-only command class: `check-ignore
--no-index` ve `ls-files --error-unmatch`. Guard pozitif kontrollerle
kanıtlandı (decoy `.env`/DNS/connect blokları, loopback izinli).
Bilinen yapısal sınır: `sys.addaudithook` guard'ı libpq'nün C-seviyesi
socket'lerini GÖREMEZ — "0 external connect" iddiası Python-seviyesi
socket'lerle SINIRLIDIR; PostgreSQL sınırının asıl dayanağı child
ortamlarının DSN'lerinin `127.0.0.1` + disposable kümeye PİNLENMESİDİR.

**J. Data/protected-path invariance ve cleanup** — `data/**` **109**
dosya byte-identical (açılış↔kapanış); `data/cases/**` **65** dosya
byte-identical; `index/**` **6**; migrations **5**; `CLAUDE.md`
byte-identical. `data/cases` yalnız `case_0001` (65 disk = 65 tracked).
Ignored/untracked residue **0** (`git status --porcelain --ignored
-uall -- data/cases` boş). PostgreSQL durduruldu, port serbest,
pgdata/log/lab/guard/bytecode residue **0**. İki implementation dosyası
(`.gitignore`, yeni test) bağımsız review açılış↔kapanış
byte-identical.

**K. Sayaçlar** — test modülü **70 → 71**; production Python **153**
(değişmedi — tracked `*.py` − `ui/tests/**`); merged reconciliation
routing key **50**; logical mutation family **38**; CLI subcommand
**6**; migration **5**; tracked `data/cases` dosya sayısı **65**;
`CASES_DIR` birincil tanım/toplam referans **36/68** (değişmedi).

**L. R1–R11 residual dispositions** — hiçbiri kaybolmadı, her biri ayrı
etiketle:

- **R1** — `git add -f` bypass: **hâlâ açık**; normal iş akışında
  yasak, yalnız kasıtlı, incelenmiş fixture ekleme için.
- **R2** — tracked `case_0001` içine gerçek veri yazımı korunmaz:
  **hâlâ açık**; operatör sınırı — gerçek veri ASLA `case_0001` içine
  konmaz.
- **R3** — hook/CI yok: **hâlâ açık**; kalıcı test (§E) kısmi telafi.
- **R4** — `.gitignore` sonradan zayıflatılabilir: **daraldı** — 21
  fault-injection varyantının 21'i yakalanıyor; N1 kapsam sınırı ayrı
  kaydedilmiştir (madde M).
- **R5** — zip/e-posta/cloud-sync: **hâlâ açık**, kapsam dışı.
- **R6** — `git clean -fdx` / `git stash --all`: **hâlâ açık**; ignored
  gerçek veriyi silebilir/yakalayabilir; operatör kuralıyla YASAK.
- **R7** — fixture drift: **hâlâ açık**; `git status --ignored -- data/
  cases/case_0001` + reviewed force-add protokolü.
- **R8** — Windows `core.ignorecase=true` / Linux case-sensitive farkı:
  **hâlâ açık**; hosting/post-pilot (Row 19D) konusu.
- **R9** — working-tree stray CR: **implementasyonla kapandı**;
  `core.autocrlf` uyarısı kozmetik olarak kalır.
- **R10** — remote repository private beyanı: **hâlâ açık**,
  doğrulanmadı.
- **R11** — ignored test residue: **hâlâ açık ve BAĞLAYICI** —
  `/data/cases/` altında çöken bir testin bıraktığı sentetik residue
  plain `git status`'ta GÖRÜNMEYEBİLİR; bundan sonraki her sweep/
  inceleme raw `data/cases/**` manifesti VEYA `git status --ignored --
  data/cases` kontrolü kullanmalıdır — plain `git status` artık YETERLİ
  DEĞİLDİR.

**M. N1–N8 bağımsız-review bulguları** — sekizi de ayrı etiketle
korunur, hiçbiri toplu geçilmez:

- **N1 — Low** (bloklamaz): kalıcı test, case verisine dokunmayan
  kardeş production paths ignore genişlemelerini (`/data/schemas/`,
  `/data/corpus_policy/`, `/data/mevzuat/`, `/data/deadline_rules/`,
  `db/migrations/` vb.) YAKALAMAZ (W1-W6, W10 varyantları 48/0 ile
  GEÇTİ); case-data güvenlik kontrolü ZAYIFLAMAZ (case verisini de
  yutan HER `data/`-genelinde kural V9-V11c'de zaten yakalanıyor); bu,
  onaylı sözleşmenin (Fable §I) İSTEMEDİĞİ bir kapsamdır, implementasyon
  sapması DEĞİLDİR; gelecekte additive unrelated-data probe önerisi
  (yetki DEĞİL, yalnız kayıt).
- **N2 — Observation**: bazı overbroad varyantlar (V10b, V11c — kural
  `/data/**`/`/data/*` ÖNCESİNE eklendiğinde) yalnız pozitif kontrolün
  yan etkisiyle yakalanır, tasarlanmış bir ilgisiz-yol assert'i ile
  DEĞİL.
- **N3 — Observation**: "temp base repository DIŞINDA" kontrolü yumuşak
  (`check()`, abort etmez) bir check'tir; yazma-güvenliği asıl olarak
  `GIT_CEILING_DIRECTORIES` + `cwd=temp`'e dayanır (ampirik kanıtlı,
  V17 varyantında sahte kök HEAD/index/status DEĞİŞMEDİ).
- **N4 — Observation/Low**: real-repo probe env'i `GIT_DIR`/
  `GIT_WORK_TREE`/`GIT_INDEX_FILE`'ı temizlemiyor (temp env temizliyor);
  mevcut davranış fail-closed sahte FAIL yönündedir (saldırgan-kontrollü
  bir sahte PASS için tehdit modeli dışı bir önkoşul gerekir).
- **N5 — Observation**: `GIT_CONFIG_PARAMETERS`/`GIT_CONFIG_COUNT`
  hiçbir env'de temizlenmiyor (uzak ihtimal, yalnız üst süreçte `git
  -c` sarmalayıcısı varsa oluşur).
- **N6 — Observation**: junction cleanup kolu güvenli kanıtlandı
  (`shutil.rmtree` 3.14 junction'ı takip etmedi, dış canary hayatta
  kaldı); symlink-to-dir kolu bu makinede ayrıcalıksız
  oluşturulamadığından DOĞRULANAMADI.
- **N7 — Observation**: "`data/cases` alt-dizesi geçen tam BİR kural
  satırı" kontrolü alt-dize tabanlıdır; ileride meşru bir
  `/data/cases_archive/` benzeri kural bile aşırı katı FAIL üretebilir
  — fail-closed yönde bir sınır, boşluk DEĞİL.
- **N8 — Observation**: reviewer'ın ilk kaba `grep '[ \t]+$'`
  trailing-whitespace taraması (ERE'de `\t` harfi `t` sayıldığından) 9
  yanlış-pozitif verdi; bayt-düzeyi Python kontrolü **0** buldu;
  implementer'ın orijinal beyanı (0 trailing whitespace) DOĞRUYDU — bu
  bir reviewer-harness notu, dosya bulgusu DEĞİLDİR.

**N. Deferred configurable-root backlog** — Post-pilot, ayrı bir scope
turu (Adım 13c) gerektiren, bu turda KAPATILMAYAN maddeler: **36**
bağımsız `CASES_DIR` tanımı (35 `src/*.py` + `ui/services/paths.py`) +
**68** toplam referans; `qa_validator.py`'nin `BASE_DIR/"data"/"cases"`
hardcode'u; `ui/services/drafting_request.py`'nin by-value import'u;
**8** by-value `src/` zincir dosyası (`drafting_discovery.py`,
`drafting_engine.py`, `orchestrator_approval.py`, `orchestrator_
discovery.py`, `qa_approval.py`, `qa_engine.py`, `risk_strategy_
discovery.py`, `risk_strategy_engine.py`); test-redirect unutma riski
(birleşik seam YOK); kök-değeri (root value) için containment boşluğu
(`path_containment._resolve_root()` symlink/junction'ı takip edip
güvenir, reddetmez); OneDrive/junction/reparse-point riski; git-worktree
tespitinin production kodda YOKLUĞU (0 eşleşme); Windows reserved-name/
trailing-dot/trailing-space segment boşlukları (Row 19C-3a Slice 1
backlog'uyla AYNI); `case_0001` için sessiz dual-root merge YASAĞI
(ayrı `FIXTURE_CASES_DIR` türü açık kök gerektirir); gerçek migration'ın
bugün teorik olması (taşınacak veri yok); facade-only/monkeypatch-
bootstrap kısayolunun REDDİ gerekçesi (kalıcı olarak kayıtlı — Slice 2
bunu yeniden ARAMASIN); split-brain'in koşullu sessizliği (iki kökte
de var olan `case_id` senaryosu Slice 2 testlerinde AÇIKÇA kapatılmalı);
Windows/Linux case-sensitivity farkının configurable root'un kök/segment
doğrulamasında ele alınması gerektiği; configurable root'un post-pilot
Adım 13c'de, ayrı exact-scope/onayla ele alınacağı.

**O. Güvenlik iddiası ve operatör protokolü** — **Neyi kapattığı**
(dar): normal `git add -A` / `git add .` / IDE stage-all ile
`data/cases/` altındaki YENİ untracked case içeriğinin kazara Git'e
girmesi. **Neyi kapatmadığı**: tracked fixture'a yazım; force-add;
manual archive/e-posta/cloud; disk encryption; masking; repo-dışı
storage; `git clean -fdx`/`git stash --all`; gerçek case verisinin
filesystem erişimi. **Operatör sınırları**: gerçek veri `case_0001`
içine ASLA konmaz; force-add yalnız fixture değişikliğinde, review ile;
gerçek case verisi mevcutken `git clean -fdx` ve `git stash --all`
YASAK; her test/sweep raw `data/cases/**` manifesti veya `git status
--ignored -- data/cases` kontrolü kullanır (R11).

**P. LOCKED-file / §9 değerlendirmesi** — `.gitignore`, CLAUDE.md'nin
"LOCKED row" kavramının kapsamında DEĞİLDİR (kod/schema/migration/data
dosyası değil; §10 içeriğinin kaldırılmasını kullanıcı onayına bağlar,
ekleme/genişletme için §9 gerekçesi GEREKTİRMEZ) — bu değişiklik §10'un
ruhunu GÜÇLENDİRİR (yeni bir güvenlik exclusion'ı ekler, hiçbirini
kaldırmaz). Yeni test dosyası YENİ bir dosyadır, §9 uygulanmaz. Hiçbir
LOCKED production/schema/migration/data dosyası bu turda AÇILMADI.
Configurable-root Slice 2 için gelecekte LOCKED-file §9 gerekçeleri
(en az 36 dosya için ayrı ayrı) ZORUNLU olacaktır. Bu roadmap turunda
yalnız `CLAUDE.md` değişir.

**Q. Kalan pilot sırası** — Adım 3 (runner/env/skip reporting) —
sıradaki, salt-okunur scope reconciliation (bkz. §5). Adım 4 LLM
masking. Adım 5 resmî tatil takvimi. Adım 6 avukat altın örnekleri.
Adım 7 deadline hardening. Adım 8 yerel PostgreSQL/IAM. Adım 9 sentetik
concierge dry-run. Adım 10 ilk gerçek concierge pilotu. Adım 11 Entra/
P1. Adım 12 hosting/Key Vault. Adım 13 post-pilot configurable root ve
diğer genişletmeler.

`PILOT READINESS STEP 2 CASE-DATA REPOSITORY PROTECTION LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde
olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir
roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Pilot Readiness Adım 3 — Runner / Environment / Skip Reporting (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — Repo'nun 73 test modülünü tek, dürüst bir
komutla koşturan bir mekanizma yoktu: PATH'teki `python` yanlış
interpreter'a düşebiliyor (root `.venv`'de psycopg/authlib yok,
`vergi_ui_runtime`'da faiss/numpy/openai/pypdf/dotenv yok — hiçbir tek
interpreter tüm modülleri koşamaz); PostgreSQL gerektiren modüller DSN
yokken sessiz 0-check/exit-0 verebiliyor; counted skip ile informational
skip karışıyor; her modülün özet formatı farklı (`---`, `TOTAL:`, bare
summary); `.env`/network/secret koruması her test dosyasında ayrı ve
tutarsız. Bu slice bu boşlukları kapatan, stdlib-only, fail-closed tek bir
çalıştırıcı getirir — Pilot Readiness Priority Reconciliation
sıralamasında **Adım 3**'tür.

**B. Exact scope ve commit'ler** — Kullanıcı tarafından onaylanmış
koşulsuz allowlist: **4 YENİ + 1 DEĞİŞTİRİLMİŞ = 5 dosya**; allowlist
dışında hiçbir dosyaya dokunulmadı. İki yerel commit, ikisi de **push
edilmedi**:

- `4ee72ef3f4892b73c5c58264537429edfa3f638e` — beş yol (V1/V2
  remediasyonları dahil).
- `2afff40dbf1be465782d6c0490ed1ef14c11fb10` — RAG kapısı K.1
  daraltması (yalnız runner + T.1).

`git diff --stat HEAD~2 HEAD`: 5 dosya, 5552 ekleme, 1 silme.

| Dosya | Durum | SHA-256 (HEAD `2afff40`) |
|---|---|---|
| `scripts/run_ui_tests.py` | YENİ | `5e3d227c91ed725202808a76bfd00c3eb62912261468b8c9cbb0c01205fd75ee` |
| `scripts/sweep_env_guard.py` | YENİ | `ac3e70be7dc161d776c43004b0350c78f7f3dc30d6cfa8a963246c67a77988bd` |
| `ui/tests/test_run_ui_tests_isolated.py` | YENİ (T.1) | `bb32bcdf570e2920720dbb74fc1b841c230995a7c9563deb11f776a93dc899f9` |
| `ui/tests/test_run_ui_tests_integration_postgres.py` | YENİ (T.2) | `75c77e3459ff818906bef92c77bcfc81c808ed426783658a5d3c84b37b3dec98` |
| `ui/tests/test_rag_bundle_mutation_integration_postgres.py` | DEĞİŞTİRİLMİŞ (tek satır) | `ec4fdd6ec52545eb2dbc5a832c008753b9f80430486b0a4b735cd170a1157e81` |

Sıfır migration, sıfır schema, sıfır production-data, sıfır web/CLI
yüzeyi, sıfır bağımlılık (pin) değişikliği; `data/**`, `index/**`,
`db/migrations/**` ve `case_0001` (65 dosya) her turda byte-identical
kanıtlandı.

**C. Çalıştırıcı sözleşmesi (kısa)** — Üç profil: `production-parity`
(gerçek PostgreSQL, `vergi_ui_runtime`), `rag-dependency` (root `.venv`,
gerçek faiss/numpy/pypdf/openai/dotenv/httpx2), `developer`
(`--allow-untracked` YALNIZ developer profilinde; resmî profiller
untracked test modülünü reddeder — tracked küme ≡ dosya sistemi kümesi
zorunlu). Tek ve mekanik yetki sırası: exit code > özet varlığı/ad bağı
> sayılar > ham PASS/FAIL çapraz kontrolü > SKIPPED taraması; sıfır-kontrol
(`ZERO_CHECK_*`) sonuçları PASS SAYILMAZ; counted skip ile informational
skip ayrı raporlanır. Çocuk ortamı beyaz liste + denylist; `.env` ve dış
network için fail-closed audit-hook guard (`sweep_env_guard.py`, her
koşuda private run dizinine bayt-bayt `sitecustomize.py` olarak kopyalanır;
repo'da `sitecustomize.py` adlı dosya BULUNMAZ); modül başına Windows Job
Object (CREATE_SUSPENDED → assign → resume, kill-on-close, artık-süreç
tespiti); exit kodları 0 / 1 / 2 (refusal) / 3 (integrity) / 130; atomik
rapor (`report.json`, repo dışı run dizini); korunan-yol manifesti (tüm
izlenen dosyalar + `data/**` + `index/**` + git status özeti) koşu
öncesi/sonrası karşılaştırılır; `guard_accounting` (silahlanan process =
modül kökleri + sayılan python POPEN'ları; iç içe runner pencereleri V2
düzeltmesiyle sınırlı). Runner, `VERGI_IAM_DATABASE_URL` TÜRETMEZ ve
enjekte etmez (Fable kararı #1 — bağımlılık, rag testindeki tek satırlık
`authz_conn_factory=pg_connect` düzeltmesiyle kaldırıldı).

**D. Dürüst kronoloji (aşamalar birleştirilmeden)**

1. Salt-okunur scope DRAFT.
2. Bağımsız Fable scope/mimari incelemesi: taslağın dokuz kusuru (A1–A9;
   3 HIGH, 5 MEDIUM, 1 LOW) düzeltildi; allowlist 3+1'den 4+1'e
   yeniden kuruldu; üç açık karar kesinleşti (runner DSN türetmez; guard
   hem committed kaynak hem ephemeral `sitecustomize`; interpreter
   capability profili, varsayılan profil YOK).
3. Kullanıcı onayı: exact 5 dosya. İmplementasyon (Claude Fable 5.1;
   advisor iki kez kullanıldı — kendi raporunda disclose edilmiştir).
   İmplementasyon turunda resmî kapılar üretilemedi: makinede PostgreSQL
   kümesi yoktu ve yeni dosyalar untracked idi.
4. İlk bağımsız inceleme: **NOT LOCK-READY** — B1–B5 (3 HIGH + 2 MEDIUM):
   B1 Windows `.env` guard bypass, B2 Job Object / Ctrl-C exception
   safety, B3 RAG kapısı exact sözleşmesi (K.1), B4 büyük/küçük harf
   duyarsız subprocess desenleri, B5 PostgreSQL env değeri sızıntısı.
5. Dar remediasyon (yalnız 4 dosya, beşinci dosya byte-identical).
6. Bağımsız doğrulama (ayrı oturum, gerçek disposable PostgreSQL 16 ile):
   B2-R1 ve B5-R1 KAPANDI; ancak gerçek PostgreSQL'le ilk kez koşan
   yollar iki yeni engelleyici bulgu çıkardı: **V1 (HIGH)** — T.2
   gerçek-PG modunda deterministik kırmızı (54/1): B5 log taraması gerçek
   rag modülünün kendi başlık satırını sızıntı sayıyordu (test-harness
   kusuru); **V2 (HIGH)** — `guard_accounting` bare-pid dışlaması Windows
   pid yeniden kullanımı altında üç gerçek süpürmenin ikisinde yanlış
   integrity hatası (exit 3) üretiyordu, ayrıca fail-open yönü vardı.
7. Kullanıcı onayı: exact 3 dosya (runner, T.1, T.2) — V1: T.2'de tek,
   tam-satır banner muafiyet tablosu; V2: iç içe runner penceresi =
   [ilgili pid'in NESTED_RUNNER kaydından önceki son GUARD_ARMED,
   aynı pid'in sonraki GUARD_ARMED'ı); python POPEN yalnız pencerenin
   KESİN içindeyse dışlanır.
8. Ayrı bağımsız yeniden inceleme (Opus, kendi PostgreSQL kümesi): V1 ve
   V2 KAPANDI, engelleyici bulgu YOK — 20.000 izlik olasılıksal
   simülasyon (yeni mantık 20.000/20.000 doğru; eski mantık 18.786'sında
   yanlış), monotonluk özelliği ihlal edilmeden; V2'nin aynı zamanda gerçek
   bir fail-open'ı kapattığı gösterildi.
9. Resmî `production-parity` FULL (commit `4ee72ef`): exit 0, 73/73,
   4896 passed. Resmî `rag-dependency`: `RAG_GATE_FAIL` — yalnız builder
   testinin Windows'ta self-referanslı symlink oluşturamadığı için
   raporladığı, bağımlılıkla ilgisiz TEK informational skip yüzünden
   (**K.1**).
10. Kullanıcı kararı: K.1 daraltılarak çözülsün. `RAG_GATE_PLATFORM_SKIPS`
    tablosu: TEK modül (`test_rag_bundle_builder_isolated`), TEK platform
    (`win32`), TEK tam-satır kalıbı, en fazla 1 tekrar; kapı artık
    `informational_skips_effective == 0` (efektif = ham − muaf) arar; ham,
    muaf ve etkin sayı ayrı raporlanır ve muafiyet bir uyarı satırıyla
    duyurulur; smoke modülündeki skip, başka modül/platform/metin ve
    ikinci tekrar HÂLÂ kapıyı bozar. Kilitli builder testine dokunulmadı.
11. Ayrı bağımsız K.1 incelemesi (Opus, PostgreSQL'siz): doğru ve dar,
    engelleyici bulgu YOK — 81 saldırı senaryosu, 6 mutasyon testi.
12. Commit `2afff40` ve resmî kapıların son commit'li baytlarla
    tekrarı (Bölüm E).

**E. Final resmî kanıt (HEAD `2afff40`, çalışma ağacı temiz)**

- **`production-parity` FULL** — exit 0; kendi fresh disposable
  PostgreSQL 16 (yalnız `127.0.0.1`, `--no-locale`, migration 0001-0005),
  `VERGI_IAM_DATABASE_URL` yok, çocuk ortamı beyaz liste. Discovery: 73
  izlenen = 73 dosya sistemi, untracked `[]`. **73/73 modül PASS**:
  **4906 passed, 0 failed, 8 counted skipped, 14 informational**
  (4896 → 4906 = T.1'e eklenen 10 K.1 kontrolü). 14 `*_postgres` modülünün
  hepsi gerçekten koştu, sıfır-kontrol yok; T.2 gerçek modda **55/0**; rag
  modülü **68/0**. Guard: 10/10 pozitif kontrol; armed 193 = expected 193;
  `NET_BLOCKED` 0; `ENV_OPEN_BLOCKED` 0; suspicious `[]`; integrity
  failures `[]`; korunan manifest ok (371 giriş); secret taraması 146
  dosya 0 isabet; temp/DB/bytecode/süreç residue yok.
- **`rag-dependency`** — `RAG_GATE_PASS`, exit 0 (`.venv`, PG env yok):
  builder 122 (1 informational skip), reader 21, smoke 73 (marker tam
  satır); toplam 216 passed, 0 failed. `rag_gate`: ham 1 / muaf 1 (builder,
  win32) / **etkin 0**; muafiyet uyarı satırıyla duyuruldu.
- **T.1** — `vergi_ui_runtime` **313/0/0**; root `.venv` **311/0/1
  informational**. **T.2** — gerçek PostgreSQL **55/0/0**.
- Bağımsız incelemeler kaynak + repo-dışı diagnostic/simülatör + kendi
  PostgreSQL kümeleriyle yürütüldü; her turun sayıları AYRI etiketlidir,
  tek bir koşuymuş gibi BİRLEŞTİRİLMEZ.

**F. Sayaçlar** — `ui/tests/test_*.py` modülü **71 → 73**; production
Python (tracked `*.py` − `ui/tests/**`) **153 → 155** (yeni: iki
`scripts/*.py`); migration **5**, merged reconciliation routing key
**50**, logical mutation family **38**, CLI subcommand **6** —
değişmedi.

**G. Dürüst sınırlar ve açık kalanlar (kapatılmış gösterilmez)**

1. **Son resmî koşular implementer (Claude Sonnet 5) koşularıdır**;
   aynı son baytlarla ayrı bir oturum tarafından yeniden koşulmadı.
   Önceki bağımsız incelemeler aynı mantığı ve 73 modüllük süpürmeyi
   doğruladı. V1/V2 ve K.1 kodunu yazan oturum ile bunları inceleyen
   oturumlar ayrıdır; B1–B5 remediasyonunu yazan oturum (Fable 5.1) ile
   onu doğrulayan oturum (Sonnet 5) model olarak da ayrıdır.
2. **"0 external network" iddiası Python-seviyesi guard sayaçlarıyla
   SINIRLIDIR**: `sys.addaudithook` libpq'nun C-seviyesi soketlerini
   GÖRMEZ; PostgreSQL sınırının asıl dayanağı DSN'nin `127.0.0.1` +
   kendi disposable kümeye sabitlenmesidir.
3. **Low/Observation backlog (AÇIK):** (a) K.1 muafiyeti stdout log'unu
   diskten yeniden okur, `stdout_sha256` ile karşılaştırmaz (Low); (b) V2
   penceresi, kayıp `GUARD_ARMED` + pid yeniden kullanımı BİRLİKTE olursa
   hâlâ kördür (önceden var olan Observation); (c) T.2 başlığındaki bir
   yorum satırı (≈77–79) varsayılan bakım DB adının taranmadığını
   söyler, oysa taranır (yalnız dokümantasyon); (d) diğer Observation'lar
   ilgili bağımsız inceleme raporlarında kayıtlıdır.
4. Fable review E-27: `test_mutation_journal_postgres.py` ve
   `test_mutation_reconciliation_provenance_postgres.py` özet
   satırlarına skip sayacı ekleme maddesi **DEFER** olarak kalır (Low
   backlog; iki dosya allowlist DIŞINDA bırakıldı). Runner bu iki
   modülü kendi bağımsız SKIPPED taraması ve `passed+failed==0` kuralıyla
   mekanik olarak kapsar.
5. Operatör kuralları: resmî kapılar yalnız commit'li baytlarla ve tek
   sweep olarak koşulur; bir sweep sürerken repo dosyası düzenlenmez;
   iki sweep eşzamanlı koşulmaz (sentetik case dizinleri `data/cases/`
   içinde oluşur — bkz. Adım 2, R11: ham `data/cases/**` manifesti veya
   `git status --ignored -- data/cases` kullanılır).

**H. Kapsam dışı / başlamamış** — Bu checkpoint aşağıdakilerin HİÇBİRİNE
dosya-yazma veya implementasyon yetkisi VERMEZ: Adım 4 (LLM masking —
yalnız salt-okunur scope reconciliation, bkz. §5); Adım 5 resmî tatil
takvimi; Adım 6 avukat altın örnekleri; Adım 7 deadline hardening; Adım
8 yerel PostgreSQL/IAM adoption; Adım 9 sentetik concierge dry-run; Adım
10 ilk gerçek concierge pilotu; Adım 11 Entra/P1; Adım 12 hosting/Key
Vault; Adım 13c configurable case root; corpus acquisition/population;
Row 19D OS-ACL/service-identity/TOCTOU ve advisory-lock timeout
backlog'u; **push** (commit'ler yalnız yerel).

**I. §9 / LOCKED-file değerlendirmesi** — Dört dosya YENİDİR (§9
uygulanmaz). Beşinci dosya, LOCKED lineage'a (RAG Global-Resource Bundle
Foundation) ait bir TEST dosyasıdır ve yalnız tek satırla değişti
(`authz_conn_factory=pg_connect`): runner'ın `VERGI_IAM_DATABASE_URL`
türetmemesi kararının doğrudan sonucu; kaynak-kanıtlı gerekçe — tek
gerçek tetikleyici bu testin factory'yi atlamasıydı, 7 kardeş test
factory'yi zaten geçiyor; production kod, schema, migration ve data
dosyası açılmadı. Rag testi bu değişiklikle `VERGI_IAM_DATABASE_URL`
olmadan 68/68 PASS eder.

`PILOT READINESS STEP 3 RUNNER / ENVIRONMENT / SKIP REPORTING LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde
olduğu gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir
roadmap-lock işlemidir; hiçbir kaynak/migration/test/production
dosyasına dokunmaz.

### Pilot Readiness Adım 4a — LLM Gizlilik Sınırı: Fact Extraction Takma Adlandırma (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — İlk gerçek belge dış LLM'e (Anthropic) gitmeden
önce taraf adı/TCKN/VKN/IBAN/telefon/e-posta takma adlandırılmalıdır; bağlayıcı
kaynak: Pilot Readiness Priority Reconciliation §4 Adım 4 + D-17 (fact
extraction belge metninin TAMAMINI ve `parties[].display_name`'i maskesiz
gönderiyordu). Bu slice yalnız fact extraction'ı kapsar (Pipeline A'nın tek LLM
adımı); diğer ajanlar Dilim 4b'dir.

**B. Exact kapsam ve commit** — Kullanıcı tarafından ayrıca onaylanmış tam
allowlist: **2 YENİ + 9 DEĞİŞTİRİLMİŞ = 11 dosya**; allowlist dışında hiçbir
dosyaya dokunulmadı. Yerel commit `77f96c9f21425d825d4e50b0a098e7f35accf986`
(push YAPILMADI); 11 dosya, 5907 ekleme, 15 silme. Sıfır migration, sıfır schema,
sıfır production-data, sıfır bağımlılık (pin) değişikliği.

| Dosya | Durum | SHA-256 (HEAD `77f96c9`) |
|---|---|---|
| `src/llm_privacy_boundary.py` | YENİ | `72b2fe9d7f6fdb0bbb5a25226420eab3b3d6ae6ab5a09d2cbcfdb281bebe5984` |
| `ui/tests/test_llm_privacy_boundary_isolated.py` | YENİ | `615287f68e8a38ea1c2b2b6eb306e2804b1ea54680c79f1e6104798fbb061e39` |
| `src/fact_extraction_engine.py` | DEĞİŞTİRİLMİŞ (LOCKED Row 4 + 19C-3c-iii) | `8684b2c45fda56f6d2d24b735bdd73857bb8cccf425f9dbc40ed8f7cece040bf` |
| `ui/services/fact_extraction_mutation_facade.py` | DEĞİŞTİRİLMİŞ (LOCKED 19C-3c-iii) | `268278349b0c8f16c90f8d555bd6c9003dd16476fb198d0f9c1594436dba62be` |
| `ui/services/fact_extraction_mutation_adapters.py` | DEĞİŞTİRİLMİŞ (LOCKED 19C-3c-iii) | `c5da76eb84908a174e63b1ec8766bf11df62ee80aa795466a1f0bf8d7ccd03fc` |
| `ui/cli_mutate.py` | DEĞİŞTİRİLMİŞ (LOCKED 19C-3b/3c) | `546c0717cd38ba20bc7aa1c798f1bf73f21f96859e1d39a5a4dcb34a71090ad0` |
| beş test dosyası | DEĞİŞTİRİLMİŞ | `test_reconciliation_isolated`, `test_fact_extraction_mutation_facade_isolated`, `test_fact_extraction_engine_isolated`, `test_fact_extraction_mutation_integration_postgres`, `test_cli_mutate_isolated` |

**C. Tasarım (Tasarım R — geri çevrilebilir takma adlandırma)** — Tasarım I
(geri çevrilemez redaksiyon) REDDEDİLDİ: aynı üç LOCKED üretim dosyasını açar,
canonical `text_excerpt`'in kaynağa sadakatini bozar, token'ları 10 downstream
tüketiciye yayar ve kalıcı harita gerektirir ("eşleşme tablosu diske YAZILMAZ"
şartıyla çelişir). R'de: (1) prompt için context'in ve metnin KOPYASI aynı
haritayla maskelenir; `build_extraction`'a ORİJİNAL context verilir (aksi halde
`normalize_attribution` idare atfını hatasız düşürürdü); (2) geri çevirme
`parse_llm_json` ile `build_extraction` ARASINDA, `json.loads`'tan SONRA ağaç
üzerinde yapılır (dict ANAHTARINDA token görülürse REDDET); (3) token
`VGMASK_<NNNN><C>` — sınıf harfi SONDA (`P` isim, `T` 11 hane, `V` 10 hane, `B`
IBAN, `F` telefon, `E` e-posta), sıra numarası ilk-görülme sırasıyla
deterministik; (4) maksimal 10/11 haneli ASCII rakam dizisinin TAMAMI maskelenir
(sağlama yalnız etiket için; ayraç ASLA temizlenmez, kayan pencere yok — `12.345.678,90`
tutarı ve 17 haneli tebligat no yanlış kimlik olmasın diye); IBAN (biçim + mod-97,
boşluk/NBSP/tire/nokta gruplu), telefon, e-posta, tohum adları (sondaki `\b` YOK —
Türkçe ekler); boşluk/satır sonu/görünmez karakter esnek çok-kelimeli ad
eşleştirmesi; fixpoint'e kadar tekrar; en uzun eşleşme önce; (5) tohum
listesi: `parties[].display_name` (YALNIZ `party_type ∈ {individual, company}`
— kamu kurumu/mahkeme/idare adları BİLİNÇLİ maskelenmez, karar U2),
`reference_code`, dosya adı/`uploaded_by_ref`, operatör ek terimleri
(`--mask-term`, tekrarlanabilir, karar U3); şirket eki varyantları, ek'siz
çekirdek ad, ASCII transliterasyon; (6) fail-closed tablosu: boş tohum listesi
(koşulsuz ret, override yok), token öneki çakışması, hayatta kalan
TCKN/VKN/IBAN/e-posta/tohum adı, ASCII olmayan rakam, `case_id`/`party_id`/
`document_id`/`source_document_issuer_party_id` içinde tohum çekirdek adı
(opak olmayan kimlik), kelime-İÇİ görünmez karakter/NFD, bilinmeyen/bozuk/kesik/
büyük-küçük harf değişmiş/uzamış-rakamlı dönüş token'ı, dönüşte düşen/fazla
token, maskeli metnin `MAX_INPUT_CHARS` aşması; (7) maskeleme fact extraction
ajan yolunda ZORUNLUDUR (üretim ve enjekte-istemci; opt-out yok); modelin
token'ı aynen kopyalaması için sabit bir talimat bloğu YALNIZ maskeleme
aktifken USER prompt'a eklenir (`SYSTEM_PROMPT`/`PROMPT_VERSION` DEĞİŞMEZ;
blok `masking_policy_version` ile kapsanır); (8) identity_payload **7 → 9**
anahtar (`+ masking_policy_version`, `+ masking_extra_terms_digest`),
`_MANIFEST_VERSION` facade VE adapter'da birlikte `.v2` (`_SNAPSHOT_VERSION`
DEĞİŞMEDİ), üç çağrı noktasında; digest kilit altında yeniden hesaplanır;
`--mask-term` değişimi yeni, bağımsız idempotency slotu üretir; audit kaydı
iki alanı identity_payload'dan tek kaynaktan taşır, adapter bağlar
(`generation_parameters_digest is None` kuralı DEĞİŞMEDİ); (9) önizleme
belge metnini yükler, maskeler ve maskeli metin + sayaçlar + sınıf dağılımı +
ipucu sayaçlarını (`possible_over_masking`, `possible_split_identifier`,
`possible_squeeze_seed_match`) gösterir, haritayı ASLA; hatalar sabit mesajlı
`ApprovalUiError` alt sınıflarıdır (traceback yok); (10) `--mask-term` yalnız
fact_extraction satırında kabul edilir, diğer beş generation dalında usage-shape
ile authz/DB/dosya erişiminden ÖNCE reddedilir; önerilen apply komutu yalnız
güvenli-desenli terimleri gömer, aksi halde terimleri ayrı blokta listeler.

**D. Kullanıcı kararları ve delege edilen kararlar** — Kullanıcı onayı: U1 (iki
dilim: 4a sonra 4b), U2 (kamu kurumu adları maskelenmez), U3 (`--mask-term`);
ayrıca exact 11 dosyalık allowlist. Kullanıcının bana delege ettiği teknik takaslar
(kaynakta kayıtlı, sonradan itiraz edilebilir): bölünmüş TCKN/VKN için **b2**
(reddetme, yalnız önizleme sayacı — operatör düzeltemeyen haksız ret riski);
squeeze-only tohum isabetinin reddedilmek yerine sayaca indirilmesi (R1(iii));
kelime-içi `scan_fold`'un NFKD+birleştirici-at yerine NFKC olması (`TAS` çekirdeği
vs `taşınmaz` kalıcı haksız retini kaldırmak için); gerçek-model smoke testi
Adım 9'a ertelendi.

**E. Dürüst kronoloji (aşamalar birleştirilmeden)** — (1) Salt-okunur scope
reconciliation: üç bağımsız araştırma ajanı (fact extraction hattı; repo-geneli
çıkış envanteri; maskeleme tasarım kısıtları) + advisor; (2) taze bir bağımsız
inceleme scope taslağına 15 mekanik düzeltme getirdi (0 Blocker), hepsi FINAL'e
işlendi; (3) kullanıcı onayı; implementasyon (bağımsız bir Opus ajanı, ayrı
brief); (4) **ilk bağımsız inceleme: NOT LOCK-READY** — B1: maskeleyici ve
giden-metin taraması aynı `fold1to1` karşılaştırmasını paylaştığından satır
sonu/çift boşluk/sekme/NBSP/yumuşak tire/ZWSP ile bölünmüş veya NFD taraf adı
SESSİZCE LLM'e gidiyordu; ayrıca S1 (isim maskelenmeyen context alanlarında
hayatta kalıyordu), S2 (aşırı-maskeleme sayacı kör), S3 (önerilen komutta
güvensiz kabuk alıntılaması); (5) remediasyon 1 (B1 isim yarısı: normalize eden
bağımsız backstop + boşluk-esnek maskeleyici; kimlik yarısı b2); (6) ikinci
bağımsız inceleme: **READY WITH CORRECTIONS** — R1 (kelime-ortası tüm-boşluk
silen `scan_squeeze` operatörün düzeltemediği haksız ret üretiyordu: 25/249
gerçek-fixture kombinasyonu), R2 (`source_document_issuer_party_id` opaklık
kontrolünde yoktu), R3 (tire/nokta gruplu geçerli IBAN maskelenmiyordu);
(7) remediasyon 2 (R1 ii/iii, R2, R3) ve remediasyon 3 (NFKC); (8) son bağımsız
doğrulama: **LOCK-READY — NO BLOCKING FINDINGS**.

**F. Kanıt — implementer ve bağımsız inceleyici sayıları AYRI** —
Implementer (Opus ajanı) final: developer sweep 74/74 modül, 5535 passed, 0
failed; 34 mutasyon öldürüldü + 1 kanıtlı eşdeğer. Bağımsız inceleyicinin KENDİ
koşusu (kendi disposable PostgreSQL 16'sı): touched modüller yeşil (gizlilik
modülü 453/0), developer sweep **74/74, 5539 passed, 0 failed**, 8 counted /
14 informational skip, guard `net_blocked=0`/`env_open_blocked=0`, 10/10 pozitif
kontrol; 14/14 bağımsız mutasyon öldürüldü. **Resmî kapılar (commit `77f96c9`,
çalışma ağacı temiz, ben koştum):** `production-parity` FULL exit 0 — 74
izlenen = 74 dosya sistemi, **74/74 PASS, 5539 passed, 0 failed, 8 counted, 14
informational**; 14 `*_postgres` modülünün hepsi gerçekten koştu (fact extraction
entegrasyonu 58/0); guard armed 194 = expected 194, `NET_BLOCKED` 0,
`ENV_OPEN_BLOCKED` 0, 10/10 pozitif kontrol, secret taraması 148 dosya 0 isabet;
korunan-yol manifesti (122 giriş) kapıdan önce/sonra bayt-bayt aynı,
`data/cases` artığı 0. `rag-dependency` `RAG_GATE_PASS` exit 0 (216 passed; K.1
muafiyeti isimle, etkin skip 0). **Sınır:** resmî kapı koşuları implementer'ın
(ana oturumun) koşularıdır; bağımsız inceleyici aynı ağaca karşı kendi süpürmesini
ayrıca koştu. `sys.addaudithook` libpq C-seviyesi soketlerini görmez (Adım 3
sınırı geçerli).

**G. Sayaçlar** — `ui/tests/test_*.py` modülü **73 → 74**; production Python
**155 → 156**; routing key (50), logical mutation family (38), CLI subcommand
(6), migration (5) DEĞİŞMEDİ.

**H. AÇIK sınırlar (kapatılmış gösterilmez)**
1. **Bu takma adlandırmadır, anonimleştirme DEĞİLDİR.** Tarih+tutar+vergi
   türü+mahkeme birleşimi yeniden kimliklendirebilir; tohum listesinde olmayan
   (tanık, müdür, muhasebeci, karşı taraf, adres) ve **farklı yazılmış** isimler
   hayatta kalır — NER yok. Tohumda olmayan bir aksan taşıyan ad (`Ahmet` →
   `Ahmét`) maskelenmez VE reddedilmez (NFKC altında Türk alfabesinin 12 aksanlı
   harfinin tamamı yeniden birleştiği için NFD kodlanmış Türkçe ad tohumla
   eşleşmeye devam eder; NFC'de birleşmeyen işaret hâlâ reddedilir).
2. **Bölünmüş kimlik numarası (b2):** satır sonu/boşluk ile bölünmüş TCKN/VKN
   ne maskelenir ne reddedilir, yalnız `possible_split_identifier` önizleme
   sayacıyla raporlanır; avukat maskeli önizlemeyi kontrol etmelidir (apply
   önizleme digest'ine bağlıdır).
3. **Kelime İÇİNE sokulmuş düz boşluk/satır sonu/sekme veya satır sonu YUMUŞAK
   tirelemesi** (tek kelimelik tohum: `Ah met`, `Ah­\nmet`) reddedilmez,
   yalnız `possible_squeeze_seed_match` sayaçlanır. **Satır sonu GERÇEK tire
   (`Ah-\nmet`)** sayaç bile ateşlemez — tamamen sessizdir (bu turdan önce de
   böyleydi, regresyon DEĞİL).
4. Tireli/noktalı **telefon** (`0532-123-45-67`) ve baştaki `0`'sız cep telefonu
   maskelenmez; sağlaması bozuk TR IBAN maskelenmez; `party_type="other"` hiç
   tohumlanmaz; ASCII-dışı e-posta yerel kısmı kısmen maskelenir.
5. Kimlik sınıflarında (IBAN/telefon/e-posta/rakam) maskeleyici ve backstop
   HÂLÂ aynı regex'i paylaşır — B1'in yapısal deseni yalnız tohum sınıfı için
   kırıldı (mimari not).
6. `VGMASK_0001PP` (modelin token'ın hemen ardına harf eklemesi) sessiz
   `<ad>P` bozulmasıdır, sızıntı değil; maskeleyici sınırsız uzunlukta
   boşluk/görünmez dizisini köprüleyip iki ilgisiz kelimeyi tek token'a
   yutabilir (geri çevrilebilir, yalnız model anlaması zayıflar).
7. **Modelin token'ı aynen yansıtıp yansıtmadığı ÖLÇÜLMEDİ** (ağ yok; yalnız
   sahte istemci). Güvenlik ağı: bozuk/bilinmeyen token sessizce geçmez, pending
   YAZILMAZ. Maskelemenin çıkarım kalitesine etkisi ölçülmedi; ikisi de Adım
   9'da (gerçek Anthropic çağrısı, sentetik belge) ölçülür.
8. Süre: maliyet ≈ tohum × yerleştirme; 60k karakter + 20 terim ≈ 2,7 s, 300 terim
   ≈ 34 s (zaman aşımı yok, fail-closed etkilenmez).
9. `case_id`/`party_id`/`document_id` opaklık kontrolü, bir şirket çekirdeği
   bir kimlik parçasıyla çakışırsa (`Belge Ltd. Şti.` + `belge_9001`) yanlış
   pozitif üretebilir; `--mask-term` komut alıntılaması CRT/CMD tarzıdır
   (yalnız güvenli desenli terimler komuta gömülür, diğerleri ayrı blokta).
   Konsoldaki `Source actor:` satırı (yerel, yetkili operatör) ham kalır.
10. **LOCKED Row 4'te önceden var olan kusur (bu slice'ta DÜZELTİLMEDİ,
    Backlog):** `fact_extraction_engine.py` `text_contains_party_name`
    `display_name.casefold()` kullanır; `"İstanbul Vergi Mahkemesi".casefold()`
    büyük harfli `"İSTANBUL VERGİ MAHKEMESİ…".casefold()` içinde BULUNMAZ
    (İ → i + U+0307). Kamu kurumu maskelenmediği için Adım 4 bundan etkilenmez.
11. Anthropic veri-işleme/saklama şartları, avukatlık sırrı ve KVKK yurt dışı
    aktarım soruları KODLA KAPANMAZ — Adım 6'ya `EXTERNAL LEGAL VERIFICATION
    REQUIRED`.

**I. Kapsam dışı / başlamamış** — Bu checkpoint aşağıdakilerin HİÇBİRİNE
yetki VERMEZ: **Dilim 4b** (dört C3 ajanın mekanik kapatılması ve `app.py`);
Adım 5 resmî tatil takvimi; Adım 6 avukat doğrulaması; Adım 7 deadline
hardening; Adım 8 yerel PostgreSQL/IAM; Adım 9 sentetik concierge dry-run; Adım
10 ilk gerçek pilot; Adım 11 Entra/P1; Adım 12 hosting/Key Vault; Adım 13c
configurable case root; push.

**J. §9 / LOCKED-file gerekçesi** — Dört LOCKED üretim dosyası açıldı
(engine, facade, adapter, `ui/cli_mutate.py`); sebep hepsinde
**security/privacy** (§9 "security/safety ihlali"): prompt'un üretildiği TEK yer
engine'dir; `identity_payload`'ın TEK üretildiği yer facade'dir ve bağlayıcı
tanım `masking_version`'ı identity'ye sokmayı zorunlu kılar; adapter identity
anahtar kümesini EXACT doğruladığı için facade'le birlikte değişmek zorundadır
(aksi halde her reconciliation fail-closed çözümsüz kalırdı); `cli_mutate`
önizleme şartı ve `--mask-term` için. Değişiklikler katmasaldır (15 silinen
satırın tamamı tek tek incelenip meşru bulundu); `SYSTEM_PROMPT`,
`PROMPT_VERSION`, `_SNAPSHOT_VERSION`, `--with-agent`/`--allow-network` çift
kapısı ve Row 4 domain mantığı DEĞİŞMEDİ.

**K. Süreç notları (gizlenmez)** — İmplementasyon ve düzeltmeler bağımsız Opus
ajanları tarafından, incelemeler ayrı taze ajanlar tarafından yapıldı; ana oturum
koordinatör ve resmî kapı koşucusuydu. Advisor iki kez (scope başında ve
implementasyon başında) çağrıldı; hiçbir bulgu/sayı ondan alınmadı. İnceleyiciye
verilen bir brief "yalnız 2 dosya değişti" diyordu, gerçekte 7 dosya değişmişti
(5'i R1(iii) sayaç tesisatı; katmasal, silmeler birebir aynı) — inceleyici
düzeltti. Web araması yalnız VKN/TCKN algoritmasının yayımlanmış biçimini teyit
etmek için yapıldı (200.000 rastgele girdide 0 uyuşmazlık; yetkili GİB belgesi
BULUNAMADI — tasarım VKN'yi sağlamaya bağımlı kılmaz).

`PILOT READINESS STEP 4a LLM PRIVACY BOUNDARY LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu gibi
yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Pilot Readiness Adım 4a Remediation — Satır-Sonu Tire Maskeleme Açığının Kapatılması (DONE / LOCKED — checkpoint özeti)

**A. Neden yeniden açıldığı (§9 — security/privacy ihlali)** — Yukarıdaki Adım
4a checkpoint'i kendi §H madde 3'ünde şunu AÇIKÇA disclose etmişti: *"Satır
sonu GERÇEK tire (`Ah-\nmet`) sayaç bile ateşlemez — tamamen sessizdir."* Bu,
yalnız bir eksik uyarı sinyali DEĞİL, gerçek bir maskeleme AÇIĞIYDI: bir PDF'in
satır kaydırmasıyla gerçek ASCII tireye bölünmüş bir taraf adı, üç koruma
katmanının (ana maskeleyici, backstop, sayaç) HİÇBİRİNİ tetiklemeden,
tamamen maskesiz biçimde dış LLM'e (Anthropic) gidiyordu. Kullanıcı, gerçek
avukat müvekkil dosyası gönderilmeden ÖNCE bunun kapatılmasını AÇIKÇA istedi
(bkz. kullanıcı talebi: *"maskelemedeki satır-sonu açığı kapanmalı"*). Bu §9
"security/safety ihlali" gerekçesiyle LOCKED `src/llm_privacy_boundary.py`'nin
dar biçimde yeniden açılmasını haklı kılan somut bir bulgudur.

**B. Exact kapsam ve commit** — Kullanıcı tarafından onaylanmış, koşulsuz
2-dosyalık allowlist: **0 YENİ + 2 DEĞİŞTİRİLMİŞ**; allowlist dışında hiçbir
dosyaya dokunulmadı (commit öncesi `git status --porcelain=v1
--untracked-files=all` ile ayrıca doğrulandı). Yerel commit
`218c0813ba0419781cc79dc5c28bc04754e43377` (push YAPILMADI).

| Dosya | Diff (`git diff --numstat` 6a4adf6→218c081) |
|---|---|
| `src/llm_privacy_boundary.py` | 227 ekleme, 22 silme |
| `ui/tests/test_llm_privacy_boundary_isolated.py` | 489 ekleme, 0 silme |

Sıfır migration, sıfır schema, sıfır production-data, sıfır bağımlılık (pin)
değişikliği.

**C. Fix — iki katmanlı (R4 turu)** — (1) Backstop `scan_fold()`, whitespace
collapse'tan ÖNCE yeni bir `_LINE_WRAP_HYPHEN_RE =
re.compile(r"[ \t]*-[ \t]*\r?\n[ \t]*")` deseniyle satır-sonu tire köprüsünü
temizler — böylece tireyle bölünmüş bir tohum isim `SurvivingPatternError`
fail-closed reddine hâlâ yakalanır. (2) Ana maskeleyici (`_find_flexible()`)
YENİDEN yazıldı: artık kelime başına, dict-cache'li `_word_pattern(word)`
regex'i (her harf `re.escape(ch)`, harfler arasında opsiyonel
`_LINE_WRAP_BRIDGE_GROUP = r"(?:[ \t]*-[ \t]*\r?\n[ \t]*)?"` grubu) ile arama
yapar — yani artık yalnız TESPİT değil, gerçek MASKELEME de tire köprüsünü
geçer. Yanlış-pozitif koruması: 40 pozisyonluk ampirik bir tarama, sıfır
yanlış-pozitif (tire kendi kendine bir kelime içinde meşru şekilde
kullanılabilecek konumların hiçbiri yanlışlıkla köprülenmedi).

**D. `MASKING_POLICY_VERSION` v1 → v3 (v2 ATLANDI)** — İlk uygulama v2 önerdi,
ama implementer `ui/tests/test_reconciliation_isolated.py`'nin (3. dosya,
2-dosyalık allowlist DIŞINDA, kendisi de LOCKED) ZATEN bağımsız olarak
`"tr_pseudonymisation_v2"` literalini ilgisiz bir "farklı versiyon" test
sabiti olarak hardcode ettiğini keşfetti — v2 seçilirse gerçek bir test
çakışması/FAIL oluşuyordu. Üçüncü dosyayı allowlist'e eklemek yerine
(kapsamı genişletmemek için) `"tr_pseudonymisation_v3"` seçildi (`git grep`
ile çakışmasız olduğu doğrulandı). Bu sürüm `_build_identity_payload()`'ın
9 anahtarından biri olduğu için (bkz. Adım 4a §C madde 8) `input_digest` →
`pre_revision` → `idempotency_key` mutation-coordinator kimlik zincirine
girer — yani düzeltme ÖNCESİ "sızdırmış" tamamlanmış bir mutasyon, düzeltme
SONRASI safe-replay ile sessizce tekrar oynatılamaz (farklı identity, yeni
deneme).

**E. Bulgu F1 (birinci bağımsız incelemede tespit edildi) ve kapanışı** — R4'ün
global, tohum-farkında-olmayan tire temizlemesi, bir tohum ADIN KENDİ gerçek
iç tiresi (ör. "Ali-Mehmet") bir PDF satır-kaydırma noktasıyla ÇAKIŞTIĞINDA,
operatöre görünen `possible_squeeze_seed_match` bilgilendirme sayacının
sessizce sıfıra düşmesine neden oluyordu — maskeleme/red SONUCU DEĞİŞMEDİ
(yeni bir sızıntı YOK), yalnız bir UYARI SİNYALİ kayboluyordu. Bu nedenle R4
tek başına verdict **NOT LOCK-READY** aldı. Kapanış: `scan_fold()` özel
`_scan_fold_impl(text, *, strip_line_wrap_hyphen)`'e refaktör edildi; yeni
`_scan_fold_preserve_linewrap_hyphen()`/`_scan_squeeze_preserve_linewrap_hyphen()`
R4-ÖNCESİ davranışı (tire temizlenmeden) birebir tekrarlar;
`count_squeeze_only_seed_matches()` artık HER İKİ varyantla (OR mantığı)
hesaplama yapıp sayaç kaybını geri getirir — hiçbir maskeleme/red kararını
DEĞİŞTİRMEDEN. `MASKING_POLICY_VERSION` bu tur için TEKRAR BUMP EDİLMEDİ (bu
sayaç `_build_identity_payload()`'ın 9 anahtarına ASLA GİRMEZ, doğrulandı).

**F. Bağımsız inceleme zinciri (dürüst, ayrı ayrı)** — (1) Birinci bağımsız
inceleme (yalnız R4): Bulgu F1 nedeniyle **NOT LOCK-READY**;
`test_fact_extraction_mutation_integration_postgres.py`'yi (implementer zaman
kısıtıyla atlamıştı) kendi disposable PostgreSQL'iyle çalıştırıp **58/58
PASS** ile bağımsızca kapattı. (2) F1 remediasyonu uygulandı. (3) İkinci
(final) bağımsız inceleme: `git show HEAD:...`-tabanlı, F1 implementer'ının
kullandığı `git stash` yönteminden BİLİNÇLİ olarak FARKLI bir karşılaştırma
yöntemiyle, sayaç değerlerinin (1 ve 3, iki test senaryosunda) R4-ÖNCESİ
değerlerle BİREBİR eşleştiğini doğruladı; kendi AYRI, fresh disposable
PostgreSQL 16.15 kümesiyle `test_fact_extraction_mutation_integration_
postgres.py`'yi TEKRAR çalıştırıp **58/58 PASS, 0 FAIL, 0 SKIP** aldı. Final
verdict: **LOCK-READY**.

**G. Test kanıtı** — `ui/tests/test_llm_privacy_boundary_isolated.py`: 453
(Adım 4a baseline) → 472 (R4: +19 "R4 — line-wrap hyphen bridging" kontrolü)
→ **495** (F1 remediasyonu: +23 "F1 — squeeze-signal restoration" kontrolü).
Sıfır silme (`git diff --numstat`: 489 ekleme, 0 silme) — hiçbir mevcut
assertion zayıflatılmadı/kaldırılmadı.

**H. Bu session'ın resmî test kapıları (commit `218c081`, çalışma ağacı
temiz, ben koştum, fresh disposable PostgreSQL 16, migration 0001-0005)** —
`production-parity` FULL: exit 0, **76/76 modül PASS, 5789 passed, 0 failed,
8 counted skipped, 14 informational skipped** (`test_llm_privacy_boundary_
isolated PASS passed=495 failed=0` dahil; 14 `*_postgres` modülünün hepsi
gerçekten koştu, `test_fact_extraction_mutation_integration_postgres`
58/58 dahil). `rag-dependency`: `RAG_GATE_PASS`, exit 0, 216 passed, 0
failed. Kapı öncesi/sonrası `git status --porcelain=v1
--untracked-files=all` boş; PostgreSQL kümesi ve tüm temp dosyalar test
sonunda tamamen kaldırıldı.

**I. Kalan/AÇIK sınırlar (kapatılmış gösterilmez)** — Adım 4a'nın §H
listesindeki diğer TÜM maddeler (1, 2, 4-11) bu remediasyonla DEĞİŞMEDİ,
AÇIK kalmaya devam eder — özellikle: bölünmüş TCKN/VKN hâlâ yalnız sayaçlanır
(madde 2, b2); kelime-içi boşluk/sekme ile bölünmüş tohum hâlâ yalnız
sayaçlanır, reddedilmez (madde 3'ün YUMUŞAK-tire/boşluk yarısı — bu tur
YALNIZ gerçek ASCII tire ile bölünmüş isimleri kapsar, whitespace-only
squeeze senaryosu farklı, önceden bilinen bir sınırdır); modelin token'ı
aynen yansıtıp yansıtmadığı hâlâ ölçülmedi (madde 7, Adım 9'a bırakıldı);
Anthropic veri-işleme/KVKK soruları hâlâ KODLA KAPANMAZ (madde 11, Adım 6).
Bu remediasyon YALNIZ gerçek ASCII tire ile satır-sonu bölünmesi sınıfını
kapatır — pseudonymization/anonymization sınırı (madde 1) ve diğer tüm
disclosed limitler AYNEN geçerlidir.

**J. §9 / LOCKED-file gerekçesi** — `src/llm_privacy_boundary.py` yalnız
security/privacy gerekçesiyle (§A) dar biçimde açıldı; `SYSTEM_PROMPT`,
`PROMPT_VERSION`, tohum listesi mantığı, fail-closed red tablosu ve diğer
tüm Adım 4a tasarım kararları (Tasarım R, b2, U1-U3) DEĞİŞMEDİ — yalnız
maskeleme/backstop'un satır-sonu tire köprüleme davranışı ve buna bağlı
identity-version eklendi. `ui/tests/test_llm_privacy_boundary_isolated.py`
yalnız additive kanıt aldı.

**K. Süreç notları (gizlenmez)** — İmplementasyon ve F1 remediasyonu farklı
turlarda yapıldı; ilk bağımsız inceleme R4'ü NOT LOCK-READY olarak reddetti,
F1 remediasyonu sonrası ikinci bağımsız inceleme bilinçli olarak FARKLI bir
doğrulama yöntemi (git stash yerine git show) kullanarak LOCK-READY verdi.
Bu session, commit sonrası resmî `production-parity`/`rag-dependency`
kapılarını doğrudan kendi çalıştırdı (yukarıya bkz. §H) — bu ikisi
implementer/inceleyici turlarının PARÇASI DEĞİL, bu roadmap-lock'un kendi
kanıtıdır.

`PILOT READINESS STEP 4a LINE-WRAP HYPHEN REMEDIATION LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu gibi
yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Pilot Readiness Adım 4a Remediation 2 — Bölünmüş TCKN/VKN Fail-Closed Maskeleme (R5) (DONE / LOCKED — checkpoint özeti)

**A. Neden yeniden açıldığı (§9 — security/privacy ihlali)** — Yukarıdaki Adım 4a
Remediation checkpoint'i kendi §I'sinde şunu AÇIKÇA disclose etmişti: *"bölünmüş TCKN/VKN
hâlâ yalnız sayaçlanır"* (b2 kararı — maskelenmez, reddedilmez, yalnız bilgi amaçlı sayılır)
ve bu sayaç bile gerçek line-wrap-hyphen desenini hiç görmüyordu.

b2'nin kendisi — checksum-geçersiz düz-whitespace ayraçlı adayların informational-only
bırakılması — R5'in kapattığı blocker DEĞİLDİR; bu, bilinçli olarak kabul edilmiş bir
residual limitation olarak AÇIK KALMAYA devam eder. Bu adayların risksiz olduğu veya kişisel
veri içermediği İDDİA EDİLMEZ — yalnız, R5'in bu remediasyon turunda ele aldığı, dar tanımlı
blocker'ın DIŞINDA kaldığı belirtilir.

R5'in gerçekten kapattığı, dar tanımlı blocker şuydu: belirli GERÇEK line-wrap-hyphen
bölünmeleri, üç koruma katmanının (ana maskeleyici, backstop, sayaç) HİÇBİRİNİ tetiklemeden,
tamamen maskesiz biçimde dış LLM'e (Anthropic) gidebiliyordu — bu sayaç tarafından bile
GÖRÜLEMİYORDU, yani "bilinip kabul edilmiş" değil, gerçekten TESPİT EDİLEMEYEN bir kör
noktaydı. Kullanıcı, gerçek avukat müvekkil dosyası gönderilmeden ÖNCE bunun kapatılmasını
AÇIKÇA istedi. Bu §9 "security/safety ihlali" gerekçesiyle LOCKED
`src/llm_privacy_boundary.py`'nin dar biçimde yeniden açılmasını haklı kılan somut bir
bulgudur.

**B. Exact kapsam ve commit** — Kullanıcı tarafından, çok turlu bir plan-onayı sürecinden
(exact scope draft → revize plan → final onay [Karar #1a + 11 bağlayıcı şart + 10 zorunlu ek
test] → implementasyon) sonra onaylanmış, koşulsuz 2-dosyalık allowlist: **0 YENİ + 2
DEĞİŞTİRİLMİŞ**; allowlist dışında hiçbir dosyaya dokunulmadı (commit öncesi
`git status --porcelain=v1 --untracked-files=all` ile ayrıca doğrulandı, adım adım
onaylanmış bir 10-maddelik commit prosedürüyle). Yerel commit
`1aa709c3824889fd3d0184b551aeb4174038873d` (parent
`7b7ead6c99355be3926e63e320688b857780b5c6`, push YAPILMADI).

| Dosya | Diff (`git diff --numstat` 7b7ead6→1aa709c) |
|---|---|
| `src/llm_privacy_boundary.py` | 370 ekleme, 30 silme |
| `ui/tests/test_llm_privacy_boundary_isolated.py` | 1182 ekleme, 21 silme |

Sıfır migration, sıfır schema, sıfır production-data, sıfır bağımlılık (pin) değişikliği.
Tek bir yerel commit; ara adımların (ilk implementasyon, Karar A + mixed-kind düzeltmesi,
vacuous-assertion remediasyonu) HİÇBİRİ ayrı olarak commit edilmedi — HEPSİ tek commit'te
birleşti.

**C. Hibrit yüksek/düşük-sinyal tasarımı (Karar #1a) — çelişkisiz politika** — Karar #1a'nın
bağlayıcı metni: *"Bir adayın iç ayraçlarından EN AZ BİRİ yüksek-sinyalli ise adayın TAMAMI
yüksek-sinyalli kabul edilmelidir."* Yüksek-sinyal ayraçlar:
U+200B/U+200C/U+200D/U+2060/U+FEFF (zero-width), U+00AD (soft-hyphen), ve gerçek
line-wrap-hyphen (opsiyonel yatay boşluk + `-` + opsiyonel yatay boşluk + `\r?\n` +
opsiyonel yatay boşluk). R5 tarayıcısına (`_scan_split_digit_runs`) ULAŞAN yüksek-sinyalli
exact 10/11 haneli adaylar checksum ARANMADAN maskelenir.

Düz whitespace ayraçlı (tiresiz satır sonu DAHİL) bir aday için üç KESİN, birbirini dışlayan
sonuç vardır — hiçbir belirsizlik/gri alan YOKTUR:

1. `tckn_is_valid`/`vkn_is_valid` AÇIK bir `False` dönerse: aday informational-only kalır,
   MASKELENMEZ (b2'nin orijinal davranışı korunur).
2. AÇIK bir `True` dönerse: aday MASKELENİR.
3. Validator bir istisna fırlatırsa VEYA beklenmeyen (non-boolean) bir değer dönerse:
   fail-closed olarak yine MASKELENİR — belirsizlik ASLA "checksum'ı atla, sessizce gönder"
   (fail-open) anlamına GELMEZ.

Bu üçlü ayrım `_digit_checksum_permits_masking()` içinde `try/except Exception: return True`
+ `return result is not False` ile uygulanır — yalnız AÇIK bir `False` "izin verme"
(maskeleme yapma) sayılır, her başka durum (istisna dahil) maskeleme yönüne düşer.

**D. Doğrusal, regex-siz tarayıcı** — `_scan_split_digit_runs`, `_match_split_separator()`,
`_match_separator_atom()`, `_match_line_wrap_hyphen_linear()` tamamen backtracking-siz,
karakter-indeksleme tabanlı bir tarayıcıdır — örten ayraç alternatifli bir regex'in
taşıyacağı ReDoS riskinden yapısal olarak bağışıktır. ASCII `0-9` DIŞI hiçbir karakter dijit
sayılmaz (`isdigit()` KULLANILMAZ); candidate span ilk rakamdan son rakama kadardır (dış
whitespace maskelenmez); her candidate için en az bir iç ayraç ZORUNLUDUR; tarama
token-hariç her segmentte ayrı yürür (VGMASK sınırları asla geçilmez); maximal run yalnız
EXACT 10/11 hane ise candidate üretir (12+ haneli run'dan alt-dizi ÇIKARILMAZ).

Doğrusallık İKİ bağımsız kanıtla doğrulandı: (1) doubling-input-size zaman-oranı testi (8x
boyut artışında max/min oran sınırlı kaldı); (2) ZORUNLU, `_match_separator_atom()`'u sayan
bir monkeypatch wrapper'la elde edilen adım-sayısı kanıtı — üç adversarial şekilde
(`ZWSP+boşluk` alternatifleri, near-miss tire blokları, uzun boşluk + rakam-olmayan karakter
tekrarları) `calls/len(text)` oranı TAM SABİT kaldı (ölçülen: 1.0000/0.1667/0.0385), `C=4`
sınırı geniş bir güvenlik payıyla sağlandı.

**E. Karar A ve karışık-tür (mixed-kind) ayraç düzeltmesi — maskeleme/ret ayrımı kesin** —
**Karar A** (kullanıcı kararı, ilk bağımsız incelemenin "üretim kodu doğru" bulgusundan
sonra): PRE-EXISTING (R5'ten ÖNCE var olan, `git diff` ile bu diff'te SIFIR satır
değişikliği gösterdiği doğrulanan)
`find_unresolvable_zero_width_digit_runs()`/`ZeroWidthDigitRunError` guard'ı KORUNDU.

Bu noktada İKİ AYRI mekanizma vardır ve bunlar birbirine KARIŞTIRILMAMALIDIR:

- **Saf zero-width bölünmeler**: `mask_prompt_inputs()`'in en başında,
  `_collect_candidates()`/R5 tarayıcısı HİÇ ÇAĞRILMADAN, pre-existing
  `ZeroWidthDigitRunError` guard'ı tarafından TOPYEKÜN REDDEDİLİR. Bunlar R5'in yeni
  maskeleme mantığına hiçbir zaman ULAŞMAZ — bu yüzden "maskelenir" DENEMEZ, "reddedilir"
  denir.
- **R5 tarayıcısına GERÇEKTEN ulaşan yüksek-sinyalli adaylar** (gerçek line-wrap-hyphen,
  VEYA bir zero-width karakterin pre-existing guard'ın regex'ini kıran bir düz boşlukla
  KARIŞTIĞI mixed-kind bölünmeler): bunlar checksum aranmadan MASKELENİR.

Bu ikisinin FARKLI, ayrı sonuçlar olduğu — "bütün yüksek-sinyalli adaylar maskelenir" gibi
mutlak, tek bir iddiayla ÖZETLENEMEYECEĞİ — açıkça kayda geçirilir. Ret, R5'in
"mask-or-refuse-before-outbound" sözleşmesini karşılar; guard GEVŞETİLMEDİ.

Ancak bu guard'ın kendi regex'i (`[0-9<zero-width>]+`) düz whitespace'te KIRILDIĞI için, bir
zero-width karakterin hemen ardından düz boşluk gelen KARIŞIK-TÜRLÜ bir bölünme NE bu guard
NE R5'in İLK tarayıcısı (o zaman tek-atom eşleştirici) tarafından yakalanabiliyordu — böyle
bir kimlik numarası sessizce, hiçbir işaret bırakmadan dışarı sızabilirdi (Karar #1a'nın "EN
AZ BİRİ yüksek-sinyalliyse TAMAMI yüksek-sinyal" kuralının FİİLEN ihlali, VE §A'da
tanımlanan asıl kör-nokta sınıfının bir uzantısı).

Zorunlu düzeltme: `_match_split_separator()`, ardışık, FARKLI türden birden fazla ayraç
ATOMUNU (aralarında rakam yoksa) TEK blok halinde birleştiren bir döngüye dönüştürüldü —
blok, kapsadığı atomlardan HERHANGİ biri yüksek-sinyalliyse yüksek-sinyal SAYILIR (OR
mantığı); eski tek-atom mantığı `_match_separator_atom()` olarak İSİM DEĞİŞTİRİLEREK AYNEN
korundu. `MASKING_POLICY_VERSION` bu turda TEKRAR BUMP EDİLMEDİ (`v4`'te kaldı) — gerekçe:
bu düzeltme AYNI, henüz commit edilmemiş R5 değişim kümesinin tamamlanmasıdır, HEAD hiç
değişmedi ve ara-durum `v4` baytlarına karşı hiçbir production mutasyonu çalışmadı.

**F. Disclosed asymmetry (Karar A'nın doğrudan sonucu, kusur DEĞİL)** — Aynı rakamların SAF
zero-width bölünmesi (ör. yalnız ZWSP) hâlâ `ZeroWidthDigitRunError` ile TOPYEKÜN
reddedilir; AYNI rakamların bir zero-width karakter + ek bir düz boşluk ile KARIŞIK
bölünmesi ise pre-existing guard'ı tetiklemeyip R5'in kendi mixed-kind maskeleme mantığına
ulaşır ve MASKELENEREK başarıyla sonuçlanır. İkisi de fail-closed'dır ve "maskelenmeli veya
reddedilmeli" gereksinimini karşılar, ama hangi separator-türü karışımının kullanıldığına
bağlı olarak SONUÇ (ret vs. maskeleme) değişir — bu AÇIKÇA test edilmiş ve belgelenmiştir,
gizlenmemiştir.

**G. Bulgu — vacuous-assertion (bağımsız yeniden incelemede tespit edildi) ve kapanışı** —
İkinci turun (Karar A + mixed-kind düzeltmesi) kendi yeni testleri, R5(15)(a) ve R5(15)(b)
bölümlerinde, YALANCI-PASS (vacuous) assertion'lar içeriyordu:
`expect_absent not in res.masked_text` kontrolü, `expect_absent`'ın (TAM, BİTİŞİK TCKN/VKN
dizisi) maskeleme ÖNCESİNDE BİLE girdide HİÇ BULUNMADIĞI (girdi ayraçla BÖLÜNMÜŞ rakamlar
içeriyordu) gerçeğinden dolayı, maskeleme GERÇEKTEN çalışsın ya da çalışmasın HER ZAMAN
doğruydu — bu oturumda `INVALID_TCKN in doc` sorgusunun maskeleme öncesi bile `False`
döndüğü çalıştırılarak DOĞRULANDI. Ayrıca `"VGMASK" in res.masked_text` kontrolü,
fixture'daki İLGİSİZ "Ahmet Yılmaz" taraf adının kendi P-sınıfı token'ına maskelenmesinden
dolayı, split-digit adayı HİÇ maskelenmese bile doğru olabiliyordu.

Kapanış (ÜÇÜNCÜ, test-only tur — `src/llm_privacy_boundary.py`'ye HİÇ DOKUNULMADAN): her
vaka artık `exact_raw_split_span` (ayracıyla birlikte, maskeleme ÖNCESİ girdide GERÇEKTEN
mevcut olduğu bir `assert` ile doğrulanan tam span) +
`res.summary["class_distribution"][expected_class] == 1` +
`res.summary["possible_split_identifier"] == 0` üç bağımsız sinyalini BİRLİKTE talep ediyor;
"Ahmet Yılmaz" fixture'lardan TAMAMEN çıkarıldı. Ayrıca YENİ bir NEGATİF test-seam eklendi:
`_scan_split_digit_runs`, `_collect_candidates()`'in modül-global çözümlemesi üzerinden
monkeypatch edilerek KOŞULSUZ boş liste döndürecek şekilde devre dışı bırakıldı (üretim kodu
DOKUNULMADAN, `finally` ile KOŞULSUZ restore edilerek); kasıtlı olarak "Ahmet Yılmaz" İÇEREN
bir fixture ile, düzeltilmiş assertion kalıbının bu "candidate üretimi kaçırıldı"
senaryosunda GERÇEKTEN `False` döndüğü (ilgisiz bir VGMASK P-token'ı GERÇEKTEN mevcutken
bile) kanıtlandı — testin kendisinin artık non-vacuous olduğunun kanıtı.

**H. Bağımsız inceleme zinciri (dürüst, ayrı ayrı — bu session'ın kendi görünürlüğü sınırlı
belirtilerek)** — Bu conversation İÇİNDE "bağımsız inceleme" bulguları HER SEFERİNDE
kullanıcının kendi mesajları ARACILIĞIYLA relay edildi — implementer session bir ayrı
inceleyici agent'ın ham transkriptini DOĞRUDAN GÖRMEDİ, yalnız kullanıcının sentezlediği,
kesin teknik bulgular içeren talimatları aldı. Üç ayrı verdict mesajı: (1) Karar A onayı +
zorunlu mixed-kind remediasyon talimatı; (2) "INDEPENDENT R5 RE-REVIEW VERDICT: NOT
LOCK-READY" — R5(15)(a)/(b)'nin vacuous-assertion bulgusunun PRECISE kod-kalıbı
referanslarıyla belirtildiği; (3) "R5 COMMIT ACCEPTED... Bağımsız yeniden inceleme sonucu:
PASS — LOCK-READY". Implementer session HER turda kendi bağımsız doğrulamasını da EKLEDİ —
vacuous-assertion iddiasını `INVALID_TCKN in doc` sorgusunu GERÇEKTEN çalıştırarak,
mixed-kind düzeltmesini pre-fix tek-atom davranışını simüle edip düzeltilmiş assertion'ın
GERÇEKTEN `False` döndüğünü göstererek, ve diff'in byte-faithful uygulanabilirliğini geçici
bir `git worktree`'de GERÇEKTEN forward/reverse-apply ederek.

**I. Test kanıtı — zamanlama dürüstçe belirtilerek (yalnız fiilen çalıştırılmış sonuçlar)**
— Resmî kapılar commit'TEN ÖNCE çalıştırıldı; sonradan commit
`1aa709c3824889fd3d0184b551aeb4174038873d`'ye BYTE-IDENTICAL olarak alınan final
working-tree baytlarında koştu. Kapılar çalışırken çalışma ağacı TEMİZ DEĞİLDİ — yalnız iki
onaylı dosya (`src/llm_privacy_boundary.py`,
`ui/tests/test_llm_privacy_boundary_isolated.py`) modified durumdaydı, başka hiçbir dosya
değişmemişti. Commit SONRASINDA kapılar TEKRAR ÇALIŞTIRILMADI. Buna rağmen, commit'teki iki
dosyanın SHA-256 değerleri, kapıların çalıştırıldığı final baytlarla AYNIDIR — bu, commit
öncesi son adım olarak SHA-256'ların yeniden hesaplanıp beklenen değerlerle
karşılaştırılmasıyla (commit prosedürünün kendi 3. adımı) doğrudan doğrulanmıştır; gate
koşusu ile commit arasında dosyalar HİÇ değişmemiştir.

Bu session içinde gözlemlenen check-sayısı ilerlemesi: **580** (ilk tam koşu, ilk
implementasyon sonrası) → **616** (Karar A + mixed-kind düzeltmesi + R5(15) bölümü
eklendikten sonra) → **619** (vacuous-assertion remediasyonu + negatif test-seam eklendikten
sonra, FİNAL). Final odaklı koşu: `exit=0`, **619 passed, 0 failed**, stderr TAMAMEN BOŞ.

Resmî kapılar (final working-tree baytları, sonradan `1aa709c` commit'ine byte-identical,
fresh disposable PostgreSQL 16, migration 0001-0005): `production-parity` FULL: exit 0,
**77/77 modül PASS** (`test_llm_privacy_boundary_isolated PASS passed=619 failed=0` dahil),
guard positive controls **10/10**, sıfır beklenmeyen FAIL. `rag-dependency`:
`RAG_GATE_PASS`, exit 0, **3/3 modül PASS** (1 informational skip, R5'ten TAMAMEN bağımsız,
önceden bilinen Windows self-referenced symlink maddesi, K.1). Kapı öncesi/sonrası
`git status --porcelain=v1 --untracked-files=all` yalnız bu 2 dosyayı gösterdi; PostgreSQL
kümeleri (bu turda İKİ ayrı disposable küme kullanıldı — Karar A/mixed-kind turu ve final
vacuous-fix turu için AYRI AYRI) ve tüm temp dosyalar test sonunda tamamen kaldırıldı.

**J. Diff bütünlüğü ve SHA-256 zaman çizelgesi (byte-faithful doğrulama)** —
`src/llm_privacy_boundary.py`'nin SHA-256'sı R5 boyunca SABİT KALMADI — İLK implementasyon
turunda (`927220676907af8df72c44ef592da1b0e6db85618e7def238ff045505483a3f4` →
`15b17d2337d22b44a569285dfc86cd34b3be52c486b0488324e725025ed95d98`) ve ardından Karar A +
mixed-kind düzeltmesi turunda (`15b17d23...` →
`aa03ba5ee8684eb1420c31c6899b4ef0fc71ecea6cdb5e1d8debd96e75a19118`) İKİ KEZ değişti. Yalnız
ÜÇÜNCÜ, final vacuous-assertion/test-only remediasyon turu boyunca (bu turda
`src/llm_privacy_boundary.py`'ye hiç dokunulmadığı için) BYTE-IDENTICAL kaldı — commit'teki
nihai değer `aa03ba5e...`'dir. `ui/tests/test_llm_privacy_boundary_isolated.py`'nin
SHA-256'sı ise HER ÜÇ turda da değişti (her tur test dosyasına yeni/düzeltilmiş içerik
ekledi), commit'teki nihai değer
`f99655e03b8b35c3069d0d4f0dab594b261da6b3994e2339a6227a159fd07458`'tir.

Commit öncesi son doğrulama: diff, PowerShell `Out-File` KULLANILMADAN (Unicode/encoding
bozulma riski nedeniyle), bash `>` redirection ile ham `git diff` çıktısı olarak üretildi
(UTF-8, Türkçe karakterler bozulmadan doğrulandı). `git worktree add --detach <temp> HEAD`
ile TAMAMEN AYRI, temiz bir checkout oluşturulup diff bu worktree'ye GERÇEKTEN uygulandı
(`git apply --check` DEĞİL, gerçek `git apply`); sonuç dosyalarının SHA-256'sı hem
HEAD-worktree'deki hem mevcut çalışma ağacındaki dosyalarla BİREBİR eşleşti; ayrıca
`git apply --check --reverse` ana çalışma ağacına karşı da başarılı oldu. Geçici worktree
`git worktree remove --force` ile temizlendi.

**K. §9 / LOCKED-file gerekçesi** — `src/llm_privacy_boundary.py` yalnız security/privacy
gerekçesiyle (§A) dar biçimde açıldı; `SYSTEM_PROMPT`, `PROMPT_VERSION`, tohum listesi
mantığı, R4'ün isim maskeleme mekanizması, fail-closed red tablosu ve diğer tüm Adım 4a/Adım
4a Remediation tasarım kararları DEĞİŞMEDİ — yalnız bölünmüş TCKN/VKN'ye özgü yeni tarayıcı,
yeni istisna sınıfı (`SplitIdentifierSurvivedError(SurvivingPatternError)`, sabit mesajı
`MSG_SPLIT_SURVIVING` hiçbir ham rakam içermez), checksum-kapı fonksiyonu ve buna bağlı
identity-version (`v3`→`v4`) eklendi. `ui/tests/test_llm_privacy_boundary_isolated.py` bu üç
tur boyunca yalnız additive/düzeltici kanıt aldı — hiçbir mevcut assertion
zayıflatılmadı/kaldırılmadı (b2 emsalinin `expect_hint` değerleri GERÇEK davranış
değişikliğini yansıtacak şekilde 1→0 düzeltildi, bu gevşetme DEĞİL, doğruluk düzeltmesidir).

**L. Süreç notları (gizlenmez) — üretim bulguları ile test-yazımı hataları AYRI
sınıflandırılır** — İmplementasyon, çok turlu bir plan-onayı süreciyle (exact scope draft →
revize plan → final onay) başladı.

İmplementasyon sırasında BİR gerçek ÜRETİM-MANTIĞI TASARIM BULGUSU ortaya çıktı ve proaktif
olarak tasarımla kapatıldı: `_PHONE_RE`'nin plain-space-separated Türk telefon numaralarını
(11 hane) desteklemesi, yeni split-digit adaylarla `_mask_once()`'in
`(start, -length, priority)` collision-resolution sıralamasında ÇAKIŞABİLECEĞİ ve bir
telefon numarasının yanlışlıkla TCKN olarak sınıflandırılabileceği riskiydi — bu,
`_collect_candidates()`'te split-digit adaylarının zaten-toplanmış diğer sınıflarla
(parti/e-posta/telefon/IBAN) ÇAKIŞAN span'lerinin ELENMESİYLE tasarım aşamasında kapatıldı.

BUNDAN AYRI, bu session'ın KENDİ test yazımı sırasında ÜÇ DEĞİŞİK test-seam/test-yazımı
KULLANIM HATASI bulunup düzeltildi — bunların HİÇBİRİ üretim mantığında bir kusur DEĞİLDİR,
üçü de yalnız test dosyasının KENDİ inşasındaki hatalardır:

1. R5(1)'in ilk sürümü, altı zero-width ayracın `mask_prompt_inputs()` üzerinden başarıyla
   maskeleneceğini YANLIŞ varsaymıştı — gerçekte pre-existing `ZeroWidthDigitRunError`
   guard'ı bunları daha ERKEN yakalıyordu (bkz. §E). Test beklentisi düzeltildi.
2. R5(8)'in `_FakeMaskingResultForBackstop` sınıfı, `scan_outbound()`'un KENDİ dokümante
   ettiği düşük-seviye çağrı sözleşmesini ("result bir `MaskingResult` değilse düz bir tohum
   dizisidir") YANLIŞ kullanmıştı — özel bir fake nesne inşa etmişti, ama
   `scan_outbound()`'un `isinstance(result, MaskingResult)` False dalı `tuple(result)`
   çağırıyordu ve bu fake nesne iterable değildi. Bu `scan_outbound()`'un ÜRETİM
   davranışında bir kusur DEĞİLDİR — fonksiyon tam dokümante edildiği gibi çalıştı; test onu
   YANLIŞ çağırmıştı. Bu, bir üretim-mantığı bulgusu OLARAK SINIFLANDIRILMAZ — salt bir
   test-yazımı/test-seam kullanım hatasıdır. Düzeltme: özel sınıf kaldırıldı,
   `scan_outbound(masked_text, ())` — fonksiyonun kendi dokümante ettiği düşük-seviye seam'i
   kullanıldı.
3. R5(10)'un opak-kimlik test önermesi YANLIŞTI: `assert_identifiers_are_opaque()`'in gerçek
   implementasyonu okunduğunda, bu fonksiyonun YALNIZ isim-tabanlı seed'leri kontrol ettiği,
   TCKN/VKN rakam dizilerinden TAMAMEN HABERSIZ olduğu görüldü — yine ÜRETİM kodunda bir
   kusur DEĞİL, testin YANLIŞ bir varsayımıydı. Test artık bu gerçek, pre-existing, R5'in
   kapsamı DIŞINDAKİ boşluğu dürüstçe belgeliyor.

Karar A + mixed-kind remediasyonu ve vacuous-assertion remediasyonu AYRI, kullanıcı
tarafından relay edilen bağımsız inceleme turlarının SONUCUNDA yapıldı (bkz. §H). Tüm üç tur
TEK bir, unamended, yerel commit'te (`1aa709c`) birleşti — hiçbir ara commit YOKTUR. Gerçek
kişiye ait TCKN/VKN HİÇBİR turda kullanılmadı.

`PILOT READINESS STEP 4a SPLIT TCKN/VKN REMEDIATION (R5) LOCK-READY — VACUOUS-ASSERTION FINDING CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu gibi yalnız
`CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir; hiçbir
kaynak/migration/test/production dosyasına dokunmaz.

### Pilot Readiness Adım 4b — Ham Veri Taşıyan Ajanların ve `app.py`'nin Mekanik Kapatılması (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — Adım 4a yalnız fact extraction'ı maskeler. Diğer
ajanların "concierge pilotunda kapalı kalır" varsayımı MEKANİK olarak doğru
değildi: yedi ajan, aynı operatörün eklediği iki bayrakla
(`--with-agent --allow-network`) çalışabiliyor ve dördü ham veri taşıyordu.
Bu slice bu dört ailenin ajan modunu mekanik olarak kapatır.

**B. Exact kapsam ve commit** — Kullanıcı tarafından, yedi karar (K1-K7) ve
exact 7 dosyalık allowlist ile onaylandı: **0 YENİ + 7 DEĞİŞTİRİLMİŞ = 7
dosya**, allowlist dışında hiçbir dosyaya dokunulmadı. Yerel commit
`2097b9e3b84c205a8c0206411f7264594da2e9e2` (push YAPILMADI); 7 dosya, 1096
ekleme, 166 silme (üç test dosyasında silme YOK; `app.py`'deki silmeler
onaylı ölü sohbet gövdesidir). Sıfır migration, schema, production-data,
bağımlılık değişikliği.

| Dosya | SHA-256 (HEAD `2097b9e`) |
|---|---|
| `ui/cli_mutate.py` (LOCKED 19C-3b/3c + 4a) | `63513cc46196cc326bb6ef7feda9b5a78a14a8ef21e5c6f3dd26c54b51631494` |
| `ui/services/agent_generation_mutation_facade.py` (LOCKED 19C-3c-ii) | `bb2567d3ccb5ccd35b01f31c98330ea1417b50345d275239e1df5bf53e8c86cb` |
| `ui/services/legal_research_case_law_mutation_facade.py` (LOCKED 19C-3c-iv) | `8621a3a3acc14a169738923fe1f4772ee8a306ed936780eac14836debcb17435` |
| `app.py` | `89161317e7e4d681f6f63a800808683c40d3bca33c462585caafb7250dfe4f2d` |
| `ui/tests/test_cli_mutate_isolated.py` | `d9c91f0e1356d2d211f86d892c3a356ce4a45c795ededfc21e3c55b21cfde807` |
| `ui/tests/test_agent_generation_mutation_facade_isolated.py` | `2d9b979aa265386ebb6c0f08794500824acdda9e2b0024d606296a2d9ef41afe` |
| `ui/tests/test_legal_research_case_law_mutation_facade_isolated.py` | `5124b20b784ac4b500b26df693987f50dfe99df9a5763db44b66409938306ec2` |

**C. Tasarım ve kararlar (K1-K7)** — **K1 Seçenek B:** `issue_spotting`,
`legal_research`, `evidence`, `argument` için `--with-agent` önizlemede VE
uygulamada koşulsuz reddedilir. Seçenek A (yalnız `--with-agent
--allow-network`) REDDEDİLDİ: `_resolve_generation_provenance()` `allow_network`'ü
hiç görmediğinden, `--with-agent` tek başına apply'da kabul edilmeye devam eder ve
model HİÇ çağrılmadan `generation_mode="agent", model_id="claude-sonnet-4-6"`
yazan bir audit + tüketilmiş idempotency slotu üretirdi (Row 19C-3c-iv F3);
Seçenek A bunu kalıcı hâle getirirdi, B ortadan kaldırır. **K2 iki bağımsız
katman:** CLI usage-shape (`_validate_generation_args`, her bağlantı/authz/dosya/
model erişiminden ÖNCE; CLI `llm_client` HİÇBİR ZAMAN geçmez, bayrakla reddeder) ve
facade (`_check_argument_shapes`; ayrım `llm_client is None`; DI seam'i korunur);
frozenset ve ret mesajı facade'lerde TEK kaynaktır, CLI import eder. **Aile
bazlı:** `legal_research` ile `case_law` AYNI facade ve CLI dalını paylaşır; yalnız
`legal_research` reddedilir. **K3** `app.py`: modül-başı `src.rag` importu ve ~150
satırlık ölü sohbet gövdesi silindi (onaylı silme), hiçbir modül-seviyesi import
kalmadı, sabit mesaj + `SystemExit(2)`, hiçbir şeyi import etmeden. **K4**
`evaluation*.py` kapsam dışı; **K5** `src/rag.py` DEĞİŞMEDİ; **K6** `app.py`
"kapalı mutasyon giriş noktası" sayacına (29) katılmaz, ayrı bir "kapalı egress
giriş noktası: 1" satırıdır; **K7** yeni test modülü YOK.

**D. Dürüst kronoloji** — (1) Adım 4 scope çalışmasında Dilim 4b adayı belirlendi;
(2) bağımsız bir Opus ajanı 4b'nin exact kapsamını KAYNAKTAN çıkardı ve iki düzeltme
getirdi (bayrak birleşimi yetersizdi — F3; iki facade isolated testi eksikti) ve yeni
bir sızıntı vektörü buldu (issue `description`, `legal_basis_reference` kuralında ham
fact `statement`'ını birebir gömüyor ve `evidence`/`argument` prompt'larına giriyor —
bu iki aile zaten kapatılanlar arasında); `app.py`'nin bugün canlı değil GİZLİ
(latent) olduğunu buldu (ilk turda `history` boş → `rewrite_query` model çağırmadan
döner → aramada `RagBundleNotPinnedError`). **Bu 4b kapsam raporu, 4a'daki gibi ayrı
bir bağımsız incelemeden GEÇİRİLMEDİ** (slice küçük ve geri alınabilir sayıldı; hata
uygulama sonrası incelemede yakalanacaktı — yakalanmadı, çünkü bulgu çıkmadı);
(3) kullanıcı onayı; implementasyon (bağımsız bir Opus ajanı); (4) bağımsız inceleme:
**LOCK-READY — NO BLOCKING FINDINGS** (0 Blocker, 0 Should-fix, 5 Note).

**E. Kanıt — implementer ve bağımsız inceleyici sayıları AYRI** — Implementer:
dokunulan modüller `test_cli_mutate_isolated` 304→354/0,
`test_agent_generation_mutation_facade_isolated` 47→82/0,
`test_legal_research_case_law_mutation_facade_isolated` 55→70/0; developer sweep
74/74, 5639 passed, 0 failed; 8 mutasyon öldürüldü. **Bağımsız inceleyicinin KENDİ
koşusu:** CLI matrisi 10 row-key × 4 bayrak × preview/apply = 80 hücre × HEAD ağacı
vs çalışma ağacı — değişen hücreler TAM OLARAK dört ailenin `--with-agent` içeren
16 hücresi (hepsinde rc=2, bağlantı gözcüsü hiç tetiklenmedi, çıktı boş, sıfır
data/`.env` olayı, sıfır engine/agent modül importu); altı açık ailenin 48 hücresi
HEAD ile bayt-bayt aynı; `--allow-network` tek başına 10 ailede aynı; `app.py` gerçek
OS alt süreci exit 2, bayt-bayt sabit stderr, boş stdout, traceback yok, zehirli
`anthropic` paketiyle (ikinci pozitif kontrolle) hiç import edilmiyor, her iki
interpreter'da; 9/9 bağımsız mutasyon öldürüldü (retin DB erişiminden SONRAYA
taşınması ve `llm_client is None` ayrımının silinmesi dahil — yani testler yalnız
"exit 2"yi değil SIRALAMAYI ve DI seam'ini sabitler); developer sweep 74/74, 5639
passed, 0 failed, 8 counted / 14 informational skip, guard 197/197, ağ 0, `.env` 0.
**Resmî kapılar (commit `2097b9e`, çalışma ağacı temiz, ben koştum):**
`production-parity` FULL exit 0 — 74 izlenen = 74 dosya sistemi, **74/74 PASS, 5639
passed, 0 failed, 8 counted, 14 informational**; 14 `*_postgres` modülünün hepsi
gerçekten koştu; guard armed 197 = expected 197, `NET_BLOCKED` 0, `ENV_OPEN_BLOCKED`
0, 10/10 pozitif kontrol; korunan-yol manifesti (122 giriş) kapıdan önce/sonra
bayt-bayt aynı; secret taraması 148 dosya 0 isabet; artık yok. `rag-dependency`
`RAG_GATE_PASS` exit 0 (216 passed; etkin skip 0). **Sınır:** resmî kapı koşuları ana
oturumun koşularıdır; bağımsız inceleyici aynı ağaca karşı kendi developer süpürmesini
ayrıca koştu (runner bunu `DIAGNOSTIC` damgalar). Adım 3'ün libpq/audit-hook sınırı
geçerli. Uygulayıcının süpürme `report.json`'u temizlikte silinmiş, sayılar konsol
çıktısından yeniden sayılmıştır (resmî kapılar için bu sorun YOK).

**F. Sayaçlar** — `ui/tests/test_*.py` modülü **74 → 74**; production Python
**156 → 156**; refusal senaryosu konvansiyonu **44 → 45** (yalnız `app.py`'nin
gerçek-OS-subprocess ret senaryosu; dört ailenin CLI retleri usage-shape
kontrolüdür); routing key (50), logical mutation family (38), CLI subcommand (6),
migration (5), kapalı mutasyon giriş noktası (29) DEĞİŞMEDİ; kapalı egress giriş
noktası **1** (`app.py`).

**G. AÇIK sınırlar (kapatılmış gösterilmez)**
1. **Facade ayrımı `llm_client is None`:** yerel bir çağıran facade'e ANY non-`None`
   nesne (gerçek bir Anthropic sarmalayıcısı dahil) enjekte ederek reddi atlayabilir
   ve provenans `model_id="external_injected_client"` olarak yazılır. Onaylı K2
   tasarımıdır ve regresyon DEĞİLDİR (4b öncesi aynı çağıran aynı yola `None` ile
   ulaşırdı); kapatan kod-seviyesi engel yoktur (OS-seviyesi yerel kod sınırı Row
   19D). Yerel Python'un writer fonksiyonlarını doğrudan import etmesi de
   ENGELLENMEZ.
2. **Ajan modu bu dört ailede KAPALIDIR, maskelenmiş DEĞİLDİR:** yeniden açılmaları
   ayrı bir maskeleme dilimi ister (`argument`/`evidence` için ayrıca SİMETRİK
   geri-çevirme gerekir — doğrulayıcılar modelin döndürdüğü alıntıyı maskesiz
   `fact_index`'e karşı kontrol eder). `case_law`, `risk_strategy`, `drafting` açık
   kalır: prompt'ları yalnız kanonik kimlik/sabit-literal issue başlığı taşır (C1/C2,
   kaynaktan bağımsız doğrulandı; `drafting`'in `lawyer_provided_text`'i prompt'a
   GİRMEZ) — bu bilinçli, kanıtlı bir karardır; ancak Adım 4a sonrası kanonik fact
   `statement`/`text_excerpt` gerçek (geri çevrilmiş) metin taşır ve bu üç ailenin
   girdisi ileride bu metne yaklaşırsa sınıf yeniden değerlendirilmelidir.
3. **`src/rag.py` DEĞİŞMEDİ:** modül-başı `from anthropic import Anthropic` (`:53`) ve
   import-anı `client = Anthropic()` (`:108`) durur; `import src.rag` yapan herhangi bir
   kod hâlâ istemci kurar. `Anthropic()`'in import anındaki davranışı (hiçbir şey yapmaz
   mı, anahtar yoksa fırlatır mı) DOĞRULANMADI; her iki yön de "egress yok" der. RAG
   Slice 2 bu dosyayı zaten açacaktır. `src/evaluation.py`/`src/evaluation_v6.py`
   sabit mevzuat soruları çalıştırır (dava verisi taşımaz; soru setlerinin TAMAMI
   okunmadı), bugün `RagBundleNotPinnedError` ile fail-closed'dır — kapsam dışı.
4. **Diskteki eski agent-mod pending'ler:** doğrulandı — `data/` altında HİÇ
   `generation_mode` yok, dolayısıyla eski agent-mod pending kaydı yok; `src/*_approval.py`
   `generation_mode`'u incelemez.
5. Ret metni literali iki facade'de ayrı tanımlıdır (facade'ler birbirini import
   etmez); testler literali dört aile için pinler (kayma testle yakalanır). Yardım
   metni "ajan modu YOK" ifadesi CLI bağlamı için kesin doğrudur, facade katmanında
   enjekte test istemcisiyle ajan modu hâlâ çalışır. `app.py` çalışma kopyası CRLF
   (HEAD blob LF; `core.autocrlf` commit'te LF'e normalize eder, churn yok).
6. Kapatma, operatörün metni başka bir araca kopyalamasını veya ham fact
   `statement` içeren `issue.description` alanının bu dört ailenin dışındaki
   yollardan taşınmasını ENGELLEMEZ; issue `description`'ın ham fact cümlesi
   taşıması `evidence`/`argument` için ikinci, bağımsız bir sızıntı vektörüydü ve
   ikisi de artık kapalıdır.

**H. Kapsam dışı / başlamamış** — Bu checkpoint aşağıdakilerin HİÇBİRİNE yetki
VERMEZ: Adım 5 resmî tatil takvimi (yalnız salt-okunur reconciliation, bkz. §5);
Adım 6 avukat doğrulaması (yalnız repo dışı paket taslağı); Adım 7 deadline
hardening; Adım 8 yerel PostgreSQL/IAM; Adım 9 sentetik concierge dry-run; Adım 10
ilk gerçek pilot; Adım 11 Entra/P1; Adım 12 hosting/Key Vault; Adım 13c
configurable case root; maskelenmiş ajan modu (dört aile için ayrı slice); RAG
Slice 2; push.

**I. §9 / LOCKED-file gerekçesi** — Üç LOCKED üretim dosyası açıldı (`ui/cli_mutate.py`,
iki mutation facade); sebep **security/privacy** (ham case metninin dış LLM'e
gitmesinin mekanik olarak engellenmesi). Row 19C-3c-ii/iv'ün usage-shape sözleşmesi
DARALTILIYOR, genişletilmiyor; `_check_argument_shapes` imzası additive/defaultlu
genişletildi, ret `KeyError` korumasından SONRA yerleştirildi (hiçbir çağıran
istisna türü değişikliği görmez); `_resolve_generation_provenance`/`_invoke_builder`/
identity/writer/audit/reconciliation/adapters DEĞİŞMEDİ; fact_extraction/case_law/
risk_strategy/drafting/deadline/timeline dalları davranışça bayt-değişmezdir
(48/48 hücre kanıtı). `app.py` hiçbir LOCKED Row'a ait değildir; üç test dosyası
yalnız additive kanıt aldı.

**J. Süreç notları (gizlenmez)** — İmplementasyon bağımsız bir Opus ajanı,
kapsam çalışması ve inceleme ayrı taze ajanlar tarafından yapıldı; ana oturum
koordinatör ve resmî kapı koşucusuydu. Bağımsız doğrulama, karar ve sayılar
raporlardaki kaynak ve komut çıktılarına dayanır; ana oturum bunları yeniden
türetmedi.

`PILOT READINESS STEP 4b RAW-DATA AGENT CLOSURE LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu gibi
yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Pilot Readiness Adım 4c — Kalan Outbound LLM Yollarının Kapatılması (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — Adım 4b'nin "dört ajan kapalı" kilidi,
kullanıcının bugünkü, daha katı bar'ını KARŞILAMIYORDU. Kullanıcının
kendi ifadesiyle: *"pilot bar'ımız 'ham veri gitmiyor' değil, fact
extraction dışındaki outbound LLM yollarının teknik olarak
çalışamaması."* Bir bağımsız gap analizi (`outbound_llm_gap_analysis_
FINAL.md`) altı gerçek gap buldu: `case_law`/`risk_strategy`/`drafting`
ajan modu koordinatöre entegre, CLI-erişilebilir ve CANLIYDI (prompt
payload'ları ID/enum-only olsa BİLE — bu, "ham veri taşımıyor" iddiasını
YALANLAMAZ, ama "teknik olarak çalışamaz" bar'ını KARŞILAMAZ);
`python src/evaluation.py` bugün FİİLEN gerçek bir Anthropic çağrısı
tetikliyordu (T06 test senaryosu, gerçek, patch'lenmemiş
`rag.answer_question`'ı non-empty history ile çağırıyordu); `python
src/rag.py` doğrudan çalıştırma yalnız ilgisiz bir
`RagBundleNotPinnedError` çökmesiyle TESADÜFEN kapalıydı — RAG Slice 2
aktive olduğunda bu yol KENDİLİĞİNDEN açılacaktı.

**B. Exact kapsam** — Kullanıcı tarafından, salt-okunur bir scope
draft'tan (`pilot_step4c_scope_DRAFT.md`) sonra onaylanmış tam dosya
allowlist'i: **1 YENİ + 9 DEĞİŞTİRİLMİŞ = 10 dosya**, yerel commit
`9a3b3b299c05288271f950a33a929c071bb7d5b6` (kısa: `9a3b3b2`, push
YAPILMADI).

Yeni (1):
1. `ui/tests/test_rag_pilot_egress_gate_isolated.py`

Değiştirilmiş — LOCKED üretim (4):
2. `ui/services/agent_generation_mutation_facade.py`
3. `ui/services/legal_research_case_law_mutation_facade.py`
4. `ui/cli_mutate.py`
5. `src/rag.py` (bu turda İLK KEZ açıldı — RAG Bundle Foundation ve
   Adım 4b'nin K5 kararında AÇIKÇA dokunulmadan bırakılmıştı)

Değiştirilmiş — RAG lineage, kendi Row'u yok (2):
6. `src/evaluation.py`
7. `src/evaluation_v6.py`

Değiştirilmiş — test (3):
8. `ui/tests/test_cli_mutate_isolated.py`
9. `ui/tests/test_agent_generation_mutation_facade_isolated.py`
10. `ui/tests/test_legal_research_case_law_mutation_facade_isolated.py`

Sıfır migration, sıfır schema, sıfır production-data, sıfır web route,
sıfır RAG Slice 2 implementasyonu, sıfır DRAFT-3 değişikliği. Kullanıcının
açık "dokunma" listesi (`deadline`/`timeline`/`qa_agent`/`app.py`/web
`ui/`) beşi de kaynaktan tek tek doğrulanıp dokunulmadığı kanıtlandı.

**C. Tasarım — üç madde, tek invariant** — *"Pilot sırasında izin
verilen tek outbound AI yolu: fact extraction → llm_privacy_boundary →
maskelenmiş payload → provider. Bunun dışındaki bütün outbound LLM
yolları fail-closed olmalı."* Tek, paylaşılan ilke: kod-seviyesinde
KOŞULSUZ kapatma — hiçbir ortam-değişkenli "aç/kapa" anahtarı YOK
(kullanıcının "RAG Slice 2 aktive edildiğinde bu yol kendiliğinden
açılmamalı" şartı bunu doğrudan gerektirir).

1. **`case_law`/`risk_strategy`/`drafting`** — her iki facade'de
   (`agent_generation_mutation_facade.py`,
   `legal_research_case_law_mutation_facade.py`) AYRI, yeni
   `*_PILOT_POLICY_REFUSED_ROW_KEYS` kümeleri açıldı — Adım 4b'nin
   `*_RAW_TEXT_REFUSED_ROW_KEYS` kümelerine EKLENMEDİ, çünkü o mesaj
   "ham metin taşıyor" der ve bu üç aile için bu YANLIŞ olurdu (prompt'ları
   GERÇEKTEN ID/enum-only — kaynaktan bağımsızca iki kez doğrulandı).
   Yeni, DOĞRU gerekçeli exception sınıfları + mesaj fonksiyonları;
   `_check_argument_shapes()`'e mevcut raw-text kontrolünün hemen
   ardından, AYNI `with_agent AND llm_client is None` koşuluyla ikinci,
   bağımsız bir kontrol (DI-seam test muafiyeti otomatik korunuyor).
   `ui/cli_mutate.py`'de dört yeni lazy accessor + `_validate_generation_
   args()`'ın iki dalına birer yeni kontrol + yardım metninin artık
   YANLIŞ bir şey söylememesi (eskiden "risk_strategy/drafting/case_law
   only - optional" diyordu). Deterministik mod (`--with-agent` OLMADAN)
   HİÇ etkilenmedi. Adım 4b'nin mevcut üç ailelik (`issue_spotting`/
   `evidence`/`argument`) raw-text kümesi VE mesajı bayt-bayt DOKUNULMADI.
   Eski testlerdeki "case_law/risk_strategy/drafting NOT refused" diyen
   bloklar SİLİNMEDİ — Row 19B'nin `client_secret` emsaliyle AYNI
   disiplinle TERS ÇEVRİLDİ (artık "IS refused" doğruluyor).
2. **`src/rag.py`** — üç gerçek ağ-dokunan fonksiyon (`rewrite_query`,
   `rerank_candidates`, `generate_answer`) tek, paylaşılan bir
   `_get_client()` noktasına indirildi. Bu fonksiyon KOŞULSUZDUR (gövdesinde
   sıfır `os.environ`/`getenv` referansı — bağımsızca doğrulandı) ve
   `RagPilotPolicyEgressRefusedError` fırlatır — `anthropic` importundan
   ÖNCE. Modül-seviyesi `from anthropic import Anthropic` / `client =
   Anthropic()` kaldırıldı (RAG Bundle Foundation'ın `src/ingest.py`/
   `src/retriever.py`'de yaptığı AYNI import-hijyeni düzeltmesinin
   devamı). `__main__` bloğunun EN BAŞINA, hiçbir `print()`'den önce, bir
   ret eklendi — artık `RagBundleNotPinnedError`'a HİÇ ulaşmadan
   reddediyor. **"RAG Slice 2 simülasyonu" pozitif kontrolü** (yeni test
   dosyasında) retrieval'i BAŞARILI simüle ettikten SONRA bile gate'in
   tetiklendiğini kanıtlıyor — kapanış artık tesadüfi DEĞİL, kasıtlı.
   Repo genelinde `rag.client`/`rag_module.client`'a doğrudan erişen SIFIR
   kod olduğu grep ile iki bağımsız turda doğrulandı — kabul edilen tek
   residual risk, gelecekte biri doğrudan `rag.client`'a erişirse
   `AttributeError` alması (bugün canlı değil).
3. **`src/evaluation.py`/`src/evaluation_v6.py`** — `TEST_CASES`/
   `run_test`/`execute_test_case`/T06'nın GÖVDESİ HİÇ DOKUNULMADI. Her
   biri kendi, bağımsız `__main__`-seviyesi ret'ini aldı (sabit mesaj +
   `SystemExit(2)`, `app.py`/sekiz engine `main()` ile AYNI desen).
   `evaluation_v6.py`'nin KENDİ ret'i gerekliydi çünkü `run_all_tests()`
   `base_evaluation.run_all_tests()`'i `evaluation.py`'nin `__main__`
   guard'ından GEÇMEDEN doğrudan çağırıyor. Asıl güvenlik kontrolü
   madde 2'nin `_get_client()` gate'idir — bu madde yalnız UX/exit-code
   netliği sağlıyor (`run_all_tests()`'in kendisi hiçbir `SystemExit`
   üretmediği için, gate OLMASAYDI script "18 test PASS + 1 hata" ile
   exit code 0 verip yanıltıcı bir "başarı" görünümü bırakırdı).

**D. Kullanıcının açık kararları** — DI seam `rag.py`'ye EKLENMEDİ
(kullanıcı kararı — bu turun amacı RAG prompt/iş mantığını test etmek
değil, pilot outbound sınırını mekanik olarak enforce etmek; gelecekte
ayrı, küçük bir çalışma olabilir). `rag.py`'nin modül-seviyesi `client`
global'inin kaldırılması KABUL edildi (repo genelinde doğrudan kullanım
olmadığı doğrulandığı için). Ek invariant kullanıcı tarafından açıkça
belirtildi: credential/API-key yokluğu güvenlik kontrolü SAYILMAZ —
gap raporunun kendi ampirik testi de bunu doğrulamıştı (`Anthropic()`
API key olmadan bile sessizce kuruluyor).

**E. Yeni test dosyası** (`ui/tests/test_rag_pilot_egress_gate_isolated.py`,
50 kontrol, üç bölüm) — Bölüm A: gerçek, patch'lenmemiş
`rag.answer_question(question, history=<T06'nın aynı şekli>)` çağrısı
(mock DEĞİL) `RagPilotPolicyEgressRefusedError` fırlattığını kanıtlıyor;
"RAG Slice 2 simülasyonu"; poisoned-`anthropic`-on-`PYTHONPATH` import-
sıra kanıtı (4b'nin `app.py` testindeki teknikle aynı). Bölüm B: üç
script'in gerçek OS subprocess'lerle (normal VE poisoned-`anthropic`
ortamda) exit code 2, boş stdout, sabit mesaj verdiğini kanıtlıyor;
ağ/`.env` guard'ı mevcut `scripts/sweep_env_guard.py`'yi verbatim
yeniden kullanıyor. Bölüm C: repo-geneli, mekanik bir tarama —
`fact_extraction` dışında `--with-agent`'ı kabul eden sıfır aile
kaldığını (agent_generation'ın 5 + legal_research_case_law'ın 2 +
fact_extraction'ın kendisi = 8 ailelik evren) doğruluyor.

**F. Dürüst kronoloji ve F1 bulgu/remediasyon zinciri** — (1) Salt-okunur
gap analizi (bağımsız ajan) altı gap buldu. (2) Kullanıcı onayı üzerine
salt-okunur scope draft. (3) Kullanıcı onayı (iki açık noktayı — DI seam
ve `client` global kaldırma — kesin karara bağladı). (4) İmplementasyon
(bağımsız bir ajan) — en riskli kısımda (`rag.py`'nin `client` global'i
kaldırma) implementer bir inceliği ampirik olarak (varsaymadan)
keşfetti: "RAG Slice 2 simülasyonu" senaryosunda exception'ın nereden
geldiğini `traceback.extract_tb` ile izleyip, `rerank_candidates`'ın
(önceden var olan, dokunulmayan) sessiz `except Exception: return
candidates[:top_k]` fallback'inin gate exception'ını YUTTUĞUNU, gerçek
propagasyonun `generate_answer`'dan geldiğini buldu ve testi buna göre
tasarladı. (5) İlk bağımsız inceleme (implementasyondan AYRI oturum):
kapanış TASARIMININ TAMAMINI (dört LOCKED dosya dahil) kaynaktan ve
kendi bağımsız probe'larıyla (kendi traceback izleme scripti, kendi
poisoned-`anthropic` stub'ı, kendi fresh disposable PostgreSQL kümesiyle
tam 77-modül sweep) doğruladı — **F1 (HIGH, BLOCKING)** dışında hiçbir
sorun bulmadı: yeni test dosyasının kendi ağ-guard mekanizması (Bölüm
B), resmî sweep İÇİNDE çalıştığında sweep'in KENDİ guard muhasebesiyle
çakışıp `GUARD_INHERITANCE_MISMATCH` (exit code 3) üretiyordu — üç ayrı
bağımsız tekrarla (iki interpreter, PostgreSQL'li/PostgreSQL'siz)
kanıtlandı, dört farklı mevcut subprocess-ağır test dosyasıyla negatif
kontrolle bu dosyaya ÖZGÜ olduğu doğrulandı. Bu bulgu implementer
tarafından YAKALANMAMIŞ/DISCLOSE EDİLMEMİŞTİ. (6) Dar, TEK dosyalık bir
remediasyon (yalnız yeni test dosyası, dört LOCKED üretim dosyasının
hiçbirine dokunulmadan): `_run_src_script_with_env_guard()` artık
kendi process ortamında ZATEN miras alınmış bir guard olup olmadığını
tespit ediyor — varsa mevcut, miras alınan ortamı (override'sız)
kullanıyor (dosyanın diğer sekiz subprocess çağrısının ZATEN doğru
yaptığı gibi) ve paylaşılan ledger'ı yalnız KENDİ çocuklarının PID'lerine
göre filtreliyor; yoksa (standalone çalışıyorsa) önceki, kendi kendine
yeterli özel-ledger davranışı DEĞİŞMEDEN korunuyor. (7) Hedefli, ikinci
bir bağımsız inceleme (remediasyon oturumundan AYRI) F1'in GERÇEKTEN
kapandığını — kendi fresh PostgreSQL kümesiyle hem izole `--select` hem
tam 77-modül sweep'te `armed == expected`, `integrity.failures: []`,
`runner_exit_code: 0` — ve standalone regresyonun (50/50) korunduğunu
bağımsızca doğruladı. Final verdict: **LOCK-READY**.

**G. Bu session'ın resmî test kapıları (commit `9a3b3b2`, çalışma ağacı
temiz, ben koştum, fresh disposable PostgreSQL 16, migration 0001-0005)** —
`production-parity` FULL: exit 0, **77/77 modül PASS, 5890 passed, 0
failed, 8 counted skipped, 14 informational skipped**, guard positive
controls 10/10, `integrity.failures: []` (F1'in GERÇEKTEN kapandığının
resmî kapı üzerindeki kanıtı — `test_rag_pilot_egress_gate_isolated
PASS passed=50 failed=0` dahil). `rag-dependency`: `RAG_GATE_PASS`,
exit 0, 216 passed, 0 failed (3 sabit modül: builder/reader/dependency_
smoke). Kapı öncesi/sonrası `git status --porcelain=v1
--untracked-files=all` boş; PostgreSQL kümesi ve tüm temp dosyalar test
sonunda tamamen kaldırıldı.

**H. Kalan/AÇIK sınırlar (kapatılmış gösterilmez)** — `rag-dependency`
profilinin `RAG_GATE_MODULES`'i sabit, hardcoded 3 modülden oluşur
(dinamik keşif DEĞİL) — yeni test dosyası bu listeye DAHİL DEĞİLDİR;
dosyanın `anthropic`-kurulu ortamdaki davranışı bunun yerine hem
implementer hem iki bağımsız inceleme tarafından TEKRARLANAN standalone
koşularla (root `.venv`, 50/50 PASS, üç ayrı turda) doğrudan
doğrulanmıştır — bu bir kapsam boşluğu DEĞİL, scope draft'ın "rag-dependency
otomatik kapsar" beklentisiyle runner'ın gerçek (sabit-liste) mimarisi
arasındaki bir netleştirmedir. `rag.py`'ye DI seam EKLENMEDİ —
`evaluation.py`/`evaluation_v6.py`'nin iç mantığı (prompt şablonu,
citation mantığı) hâlâ fake client'a karşı test EDİLEMEZ; kullanıcı
kararıyla bilinçli olarak bırakılan, ayrı bir gelecekteki madde.
`rerank_candidates`'ın önceden var olan sessiz `except Exception`
fallback'i bu turda DEĞİŞTİRİLMEDİ (davranışı aynı kalıyor, yalnız
gate'in KENDİSİNE ulaştığı `RERANK_DEBUG` trace'iyle ayrıca
kanıtlanıyor). `case_law`/`risk_strategy`/`drafting`'in deterministik
generation yolu (`--with-agent` OLMADAN) HİÇ etkilenmedi ve devam
ediyor. `qa_agent.py` bu turda da dokunulmadan, önceden bilinen dormant/
erişilemez durumunu koruyor.

**I. §9 / LOCKED-file gerekçesi** — Dört LOCKED üretim dosyası açıldı
(`agent_generation_mutation_facade.py`, `legal_research_case_law_
mutation_facade.py`, `ui/cli_mutate.py`, `src/rag.py`); sebep hepsinde
**security** (kullanıcının açık pilot invariant'ı — fact_extraction
dışında hiçbir outbound yolun teknik olarak çalışmaması). Değişiklikler
katmasaldır: mevcut raw-text kümeleri/mesajları/davranışları,
deterministik mod, DI-seam test muafiyeti, `evaluation.py`/`evaluation_
v6.py`'nin TEST_CASES/run_test/execute_test_case/T06 gövdesi HİÇBİRİ
DEĞİŞMEDİ. `src/rag.py` bu turda İLK KEZ açıldı (RAG Bundle Foundation
ve Adım 4b'nin K5 kararında bilinçli olarak DOKUNULMADAN bırakılmıştı) —
tek non-refusal davranış değişikliği (`client` global'in kaldırılması)
kabul edilen, disclosed bir tavizdir (§D).

`PILOT READINESS STEP 4c LOCK-READY — F1 CLOSED, NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Pilot Readiness Adım 5 — Resmî Tatil Takvimi Registry'si + `calendar_complete` Türetimi (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — `calendar_complete`, denetlenmeyen bir
elle-beyan boolean'ıydı: boş bir `--holiday` listesiyle bile `True`
verilince sistem sessizce yalnız hafta sonu kaydırıp `calculated` diyordu
(P2-F4). Kaydedilen deadline hangi takvimle hesaplandığını hiçbir yerde
tutmuyordu. Bu slice elle beyanı kaldırıp git-governed bir registry'ye
bağlar — Pilot Readiness Priority Reconciliation'ın sıralamasında
**Adım 5**'tir.

**B. Exact kapsam** — Kullanıcı tarafından, iki ayrı bağımsız salt-okunur
inceleme turundan (kapsam + implementasyon) sonra onaylanmış tam dosya
allowlist'i: **5 YENİ + 9 DEĞİŞTİRİLMİŞ = 14 dosya**, yerel commit
`203c71a60f2bf3fb6d325d449eed6c1c950703a4` (push YAPILMADI).

Yeni (5):
1. `data/holiday_calendar.schema.json`
2. `data/holiday_calendar/holiday_calendar.json`
3. `src/holiday_calendar_validator.py`
4. `ui/tests/test_holiday_calendar_validator_isolated.py`
5. `ui/tests/test_deadline_calendar_derivation_isolated.py`

Değiştirilmiş (9):
6. `src/deadline_calculator.py` (**LOCKED Row 8**)
7. `src/deadline_engine.py` (**LOCKED Row 8**)
8. `ui/services/generation_mutation_facade.py`
9. `ui/cli_mutate.py`
10. `ui/tests/test_cli_mutate_isolated.py`
11. `ui/tests/test_generation_mutation_facade_isolated.py`
12. `ui/tests/test_deadline_engine_isolated.py`
13. `ui/tests/test_generation_mutation_integration_postgres.py`
14. `ui/tests/test_fact_verification_mutation_integration_postgres.py`

Dosya #13 allowlist onayında "koşullu — dokunulmadan da kalabilir"
işaretliydi; gerçek PostgreSQL'e karşı ilk koşuda dar, tek-senaryolu bir
gerçek başarısızlık bulundu (`G4a`, kaldırılmış `--calendar-complete`
bayrağını kullanıyordu) ve düzeltildi — dosya GERÇEKTEN değişti, bu
dürüstçe kaydedilir (Row 19C-3c-iii'nin "allowlist'te ama genuinely
untouched" emsalinin TERSİ). Sıfır migration, sıfır schema değişikliği
(`data/case_deadline.schema.json` DOKUNULMADI — K2), sıfır web route,
sıfır cloud/Entra değişikliği, sıfır `ui/services/generation_mutation_
adapters.py` değişikliği (K5).

**C. Tasarım kararı (K1–K9, kullanıcı tarafından, önerilen haliyle
onaylandı)** — **K1 (b):** doğrulanmamış veya kapsam dışı bir yılla motor
hesap yapmaz — `needs_review`, `calculated_deadline: null`. **K2 HAYIR:**
makine-okunur `calculation_block_reason` alanı bu slice'a EKLENMEDİ —
`needs_review` nedeni hâlâ yalnız serbest metin `notes`'tan okunur, LOCKED
`case_deadline.schema.json` AÇILMADI. **K3 HAYIR:** üretim
`holiday_calendar.json`'a HİÇBİR resmî tatil adı/tarihi yazılmadı — yalnız
yapı (2024–2035, HEPSİ `verified:false`, `holidays:[]`, `source_refs:[]`);
avukat paketinin "hiçbir tarih önerilmemiştir" taahhüdü korunur; sentetik
test tatili (12 Mart 2026) YALNIZ test fixture'larında yaşar (Prensip 18).
**K4 (C1):** `calculate_rule_deadline` imzası değişti; `holiday_dates`/
`calendar_complete` parametreleri TAMAMEN kalktı, yerine keyword-only,
default'suz `holiday_calendar` geldi — elle beyan yolunda geriye HİÇBİR
bypass kalmadı. **K5 HAYIR:** `generation_mutation_adapters.py`
dokunulmadı — `_audit_record_matches` yeni digest/audit alanlarını hiç
tüketmediği için (yalnız `mutation_idempotency_key`/`mutation_resource_
key`/`action_family`/`pending_sha256`/`outcome`), bir digest-formül
değişikliği bu dosyayı fonksiyonel olarak etkilemez. **K6 EVET:**
`src/deadline_calculator.py`'nin kendi `main()` CLI'ı da `--holiday`/
`--calendar-complete`'ten temizlendi, üretim takvimini otomatik kullanır.
**K7 HAYIR:** takvim yüklemesine path-containment eklenmedi — mevcut
`_read_global_resource_bytes` ruleset/provisions ile AYNI (containment'sız)
muameleyi görmeye devam eder; bu asimetri önceden var olan, kabul edilmiş
bir backlog maddesidir, iki ayrı bağımsız inceleme bunun gerçek bir drift
riski taşımadığını (üretim kod yolunun her yerde `calendar=` açıkça
geçirdiğini) doğruladı. **K8 EVET:** yıl aralığı 2024–2035, yalnız yapı
olarak. **K9:** 14 dosyalık allowlist onaylandı.

**D. Döngüsellik düzeltmesi — implementasyonun en riskli parçası** —
Bağımsız kapsam incelemesi bir döngüsellik buldu: önerilen "kapsanan yıl"
formülü `final_deadline.year`'a (kaydırma SONRASI değer) bağımlıydı, ama
mevcut kod kapıyı kaydırmadan ÖNCE çalıştırıyordu. Çözüm — kontrol akışı
`src/deadline_calculator.py` İÇİNDE yeniden sıralandı: (1) `verified is
True` tüm yılların birleşiminden `holiday_dates` önceden hesaplanır
(final.year'dan bağımsız); (2) adli tatil kontrolü DEĞİŞMEDEN çalışır; (3)
`move_to_next_business_day` ile kaydırma YAPILIR; (4) SONRA
`range(anchor.year, final_deadline.year+1)`'in TAMAMEN kapsanan yıllar
içinde olup olmadığı kontrol edilir — kapsanmıyorsa mevcut `needs_review`
şekliyle döner, `calculated_deadline` ASLA sızmaz. Bu, motor-seviyesi bir
post-check (REDDEDİLEN alternatif) DEĞİLDİR — karar `calculate_rule_
deadline`'ın KENDİ İÇİNDE, fonksiyon dönmeden ÖNCE, TEK bir dönüş
noktasında verilir. Bağımsız implementasyon incelemesi bunu (a) fonksiyonu
satır satır okuyarak VE (b) implementasyonun kendi test dosyasına
BAKMADAN ÖNCE kendi adversarial Python testlerini yazıp çalıştırarak
doğruladı: kapsanan bir yıldan gerçek bir tatille kapsanmayan bir sonraki
yıla kayan senaryo doğru şekilde `needs_review` verir, hiçbir yanlış
`calculated` tarih sızmaz; adli tatil sırası bu reorder'dan etkilenmemiştir.

**E. Sabit yerleşimi ve identity zinciri** — `DEFAULT_HOLIDAY_CALENDAR_
PATH` YALNIZ `src/deadline_calculator.py`'de tanımlıdır (`DEFAULT_
PROVISIONS_PATH` deseni — `deadline_calculator.py`, `deadline_engine.py`'yi
import EDEMEZ, yön tersinedir); `deadline_engine.py` ona `deadline_
calculator.DEFAULT_HOLIDAY_CALENDAR_PATH` üzerinden dotted-access ile
erişir (by-value import DEĞİL — bu, test monkeypatch seam'inin etkili
kalması için ZORUNLUDUR, bağımsız incelemede davranışsal olarak
kanıtlandı). `_compute_deadline_input_digest` takvim baytlarını ÜÇÜNCÜ üye
olarak alır (`digest_version` v2→v3); `_compute_deadline_generation_
parameters_digest` artık YALNIZ `judicial_recess_applicable` taşır
(v2→v3) — bu, Row 19C-3c-i'nin ruleset/provisions remediation'ıyla AYNI
sınıftaki bir düzeltmedir (ham baytların yanlış digest'te kalıp meşru
ikinci denemelerin kalıcı `IdempotencyConflictError`'a düşmesini önler).
Takvim, ruleset/provisions ile AYNI beş aşamalı global-kaynak snapshot
protokolüne (preview → pre-lock best-effort → kilit altında yeniden okuma
+ composite karşılaştırma → `TemporaryDirectory`'ye materialize + re-hash
→ `os.replace()`'ten hemen önce son karşılaştırma) üçüncü üye olarak
eklendi. `_check_argument_shapes` ve `apply_generation`'ın kendi imzası
(facade içinde, allowlist #8) eski `holiday_dates`/`calendar_complete`
parametrelerinden TEMİZLENDİ — aksi halde elle beyan yolu CLI'dan kalksa
bile doğrudan Python çağrısıyla facade üzerinden hâlâ erişilebilir
kalırdı.

**F. Şema/validator** — `data/holiday_calendar.schema.json`: kök + 5
alt-nesnede `additionalProperties:false`; yıllar 2024–2035,
`verification_ref`/`source_refs` alanları taşır. `src/holiday_calendar_
validator.py` (`corpus_policy_validator.py` deseni): `verified is True`
⇒ en az 1 `source_refs` + boş-olmayan `verification_ref` ZORUNLU (identity
kontrolü — `manifest_validator`'ın `anonymization_applied is True`
emsali, presence/truthiness DEĞİL); `half_day_policy=="not_decided"` iken
`verified:true` bir yılda `half_day` girdisi varsa ERROR; sıralama/
tekillik kuralları (yıl VE tarih düzeyinde). `run_self_test()` fixture'ları
`tempfile.TemporaryDirectory()`'ye yazılır, `data/` ağacına dokunmaz.

**G. CLI temizliği** — `ui/cli_mutate.py`'de `--holiday`/`--calendar-
complete` argparse'tan TAMAMEN kaldırıldı; 5 aile dalındaki iletim
temizlendi. Bağımsız incelemede bizzat çalıştırılarak kanıtlandı: kaldırılan
bayrağı kullanan bir komut `"unrecognized arguments"` ile exit 2 verir.

**H. Dürüst kronoloji** — 1) Salt-okunur scope draft (Claude Opus 5). 2)
Bağımsız salt-okunur kapsam incelemesi (Claude Sonnet 5, ayrı oturum,
`advisor` bir kez): taslağın on dokuz `dosya:satır` identity-zinciri
iddiasının TAMAMI dahil neredeyse tüm iddialar CONFIRMED; 2 kozmetik sayım
hatası + 3 gerçek teknik netleştirme (döngüsellik reorder, sabit
yerleşimi, facade'in iki ek dokunma noktası) bulundu — hepsi mevcut 14
dosyanın İÇİNDE çözülebilir, dosya sayısı DEĞİŞMEDİ; verdict `READY FOR
IMPLEMENTATION`. 3) Kullanıcı onayı. 4) İmplementasyon (bağımsız bir
ajan): 14 dosyanın TAMAMI + 5 zorunlu netleştirmenin TAMAMI uygulandı;
implementasyonun kendi öz-inceleme turu üç hata (uydurma `--stat` diff
rakamları, yanlış interpreter atfı, üretim takvim dosyasının Türkçe
metninin bash heredoc kaçış sorunlarından ASCII harf-çevirisiyle
yazılmış olması) yakalayıp düzeltti — Write tool ile doğru Türkçe
karakterlerle yeniden yazıldı, hedefli testlerle yeniden doğrulandı. 5)
Bağımsız implementasyon incelemesi (Claude Sonnet 5, implementasyon
oturumundan AYRI, `advisor` HİÇ çağrılmadı): en riskli bölüm (reorder
mantığı) implementasyonun kendi testine bakılmadan ÖNCE yazılan
adversarial testlerle doğrulandı; identity zinciri, K3/K5/K6/K7 kararları,
CLI/facade temizliği, P10 uçtan-uca zinciri hepsi kaynaktan ve kendi taze/
disposable bir PostgreSQL kümesiyle bağımsız doğrulandı; yalnız 2
Low-severity kozmetik sayım sapması bulundu (implementasyon raporundaki
iki dosyanın diff/satır sayısı birkaç birim yanlış — kod DEĞİL, yalnız
rapor metni); **0 Critical/High/Medium, 0 blocker**. Final verdict:
`ADIM 5 IMPLEMENTATION LOCK-READY`.

**I. Test kanıtı — implementasyon ve iki bağımsız inceleme, AYRI
etiketlerle**:

- İmplementasyon: yerel izole testler **586 PASS**; gerçek disposable
  PostgreSQL 16 (P10 zinciri dahil) **131 PASS**; tam sweep
  (`--profile developer --allow-untracked`, `production-parity` henüz
  commit öncesi untracked dosyaları yapısal olarak reddettiği için) **76/76
  modül, 5747 passed, 0 failed, 8 counted skip, 14 informational skip**.
- Bağımsız kapsam incelemesi: kendi salt-okunur kaynak doğrulaması,
  test/PostgreSQL koşulmadı (yasaktı).
- Bağımsız implementasyon incelemesi: kendi, implementer'ınkinden TAMAMEN
  AYRI, taze disposable PostgreSQL 16 kümesiyle 7 izole modül + 2
  PostgreSQL entegrasyon modülü + tam sweep BAĞIMSIZ olarak yeniden
  koşuldu — **implementer'ın TÜM sayılarıyla birebir eşleşti** (76/76
  modül, 5747 passed, 0 failed).
- **Commit sonrası, resmî kapılar** (bu roadmap-lock turunda, ana oturum
  tarafından, taze bir üçüncü disposable PostgreSQL 16 kümesiyle):
  `--profile production-parity` **exit 0, 76/76 modül PASS, 5747 passed,
  0 failed, 8 counted skip, 14 informational skip**, `git.clean=true`,
  `git.head=203c71a...`, `git.tracked_test_count=76`,
  `integrity.protected_manifest_ok=true`, `integrity.protected_path_diff=[]`,
  `integrity.secret_scan.hits=[]`. `--profile rag-dependency` **exit 0
  (RAG_GATE_PASS)**, 3 modül PASS (builder 122/0/1-informational, reader
  21/0, dependency-smoke 73/0). Disposable PostgreSQL kümesi işlem
  sonunda tamamen durduruldu ve silindi.

**J. Bilinen sınırlar / backlog (dürüstçe kaydedilir)**:

1. **K2 (`calculation_block_reason`) bu slice'a DAHİL EDİLMEDİ** —
   "takvim kapsamıyor" ile "adli tatil bilinmiyor" ayrımı hâlâ yalnız
   serbest metinden okunur; `case_view`/QA makine-okunur ayırt edemez.
2. **K7 (path-containment) bilinçli olarak eklenmedi** — ruleset/
   provisions/takvim üçü de aynı, containment'sız muameleyi görür;
   bağımsız incelemede gerçek risk taşımadığı doğrulandı, ama asimetri
   backlog'da kalır.
3. **Avukat doğrulaması (Adım 6) bu slice'ın KAPSAMI DIŞINDADIR** —
   üretim `holiday_calendar.json`'daki 12 yılın TAMAMI hâlâ
   `verified:false`'tur; bu yapı DEĞİŞTİRİLMEDEN, `next_business_day_if_
   holiday` policy'li HİÇBİR kural bugün gerçek bir dosyada `calculated`
   sonuç ÜRETEMEZ — P10'un `calculated` kanıtı YALNIZ test-injection
   seam'i üzerinden sentetik bir takvimle elde edilmiştir, ÜRETİM
   takvimiyle DEĞİL.
4. **İki ayrı module-level path sabiti** — `holiday_calendar_validator.
   HOLIDAY_CALENDAR_PATH` ile `deadline_calculator.DEFAULT_HOLIDAY_
   CALENDAR_PATH` aynı üretim dosyasına işaret eden İKİ AYRI sabittir
   (`corpus_policy_validator`'ın tek-tanım deseninden bilinçli bir
   sapma — §5.2/trap #3 gereği). Bağımsız incelemede hiçbir üretim kod
   yolunun `holiday_calendar_validator`'ın kendi path sabitine bağımlı
   OLMADIĞI (her üretim çağıranın `calendar=` açıkça geçirdiği)
   doğrulandı — düşük risk, gelecekte tek-sabit'e konsolide edilebilir.
5. `data/deadline_rules.json` (üst düzey, stale/duplicate kopya) bu
   turda İNCELENMEDİ — `CLAUDE.md` §6 backlog'unda zaten kayıtlı.
6. Sıra DEĞİŞMEZLİĞİ: bu slice adli tatil/hafta sonu kaydırma SIRASINI
   DEĞİŞTİRMEDİ, yalnız takvim kapısının kendi konumunu (kaydırma
   sonrası) düzeltti.
7. Migration/şema DEĞİŞMEDİ. Production `data/cases/case_0001` (65
   dosya) implementasyon, iki bağımsız inceleme VE resmî kapılar boyunca
   bayt-değişmez kaldı.

**K. §9 LOCKED-file gerekçesi** — `src/deadline_calculator.py` ve
`src/deadline_engine.py` (Row 8): kullanıcı talebi (bağlayıcı Pilot
Readiness tanımı §4 Adım 5) + downstream/güvenlik (denetlenmeyen elle
beyanın P2-F4 riskini — fazladan tatil → geç tarih → hak kaybı — kapatma
zorunluluğu) gerekçesiyle açıldı. `calculate_rule_deadline`'ın imzası ve
kapı mantığı değişti; `calculation_state` enum'u ve adli tatil sırası
DEĞİŞMEDİ; T02-T07 self-testleri registry-türevi hale getirildi, yeni
T07b (coverage-crossing) eklendi, 12/12 PASS. Diğer LOCKED dosyalar
(`data/case_deadline.schema.json`, `src/deadline_validator.py`,
`src/deadline_approval.py`, `src/deadline_rule_selection_policy.py`,
`src/deadline_rule_validator.py`, `src/path_containment.py`,
`ui/reconciliation_operator.py`, `ui/main.py`, `db/migrations/**`)
AÇILMADI. `ui/services/generation_mutation_facade.py`/`ui/cli_mutate.py`
Row 19C-3c-i/3b lineage'ındadır ve her slice'ta additive olarak
açılagelmiştir (19C-3b'den beri kabul edilen açılış sınıfı).

**Final verdict**:

`ADIM 5 IMPLEMENTATION LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Pilot Readiness Adım 7 — Mali Tatil (5604 sayılı Kanun) Deadline Handling (DONE / LOCKED — checkpoint özeti)

**A. Exact kapsam ve commit** — Kullanıcı tarafından, çok turlu bir
salt-okunur/dar-remediasyon sürecinden sonra onaylanmış tam dosya allowlist'i:
**1 YENİ + 5 DEĞİŞTİRİLMİŞ = 6 dosya**.

Yeni (1):

1. `ui/tests/test_deadline_calculator_mali_tatil_isolated.py`

Değiştirilmiş (5):

2. `data/deadline_rules/deadline_rules.json`
3. `data/documents.json`
4. `data/provisions.json`
5. `src/deadline_calculator.py` (**LOCKED Row 8**)
6. `ui/tests/test_deadline_calendar_derivation_isolated.py`

Sıfır migration, sıfır şema değişikliği, sıfır web/CLI yüzeyi, sıfır
`holiday_calendar` içerik değişikliği, sıfır `stopping_event_status`
implementasyonu. Yerel commit `ce3cb01c131728d3f26ce9af464b58161b46cdc5`
("Implement verified mali tatil deadline handling", 6 dosya, 4088 ekleme, 1270
silme) — **push YAPILMADI**.

**B. Hukuki dayanak ve avukat teyidi (haricî kanıt)** — 5604 sayılı Malî Tatil
İhdas Edilmesi Hakkında Kanun m.1, `data/documents.json` içine (`kanun_5604`)
ve `data/provisions.json` içine (`kanun_5604_m1`,
`verification_state: verified`) mevzuat.gov.tr konsolide metninden doğrudan
doğrulanarak eklendi; `data/deadline_rules/deadline_rules.json` dosyasındaki
`iyuk_tax_court_general_lawsuit_filing` kuralının `legal_basis_refs` alanına
`KANUN_5604_m1` yedinci referans olarak eklendi (toplam 7 ref). 5604
m.1/3'teki "vergiyle ilgili işlemlere ilişkin dava açma süreleri" hükmünün
İYUK m.7'deki genel vergi mahkemesi dava açma süresine uygulanabilirliği,
kaynağın (kanun metni) kendisinin kanıtladığı bir şey DEĞİLDİR (Prensip 3) —
bu, avukatın yazılı, kullanıcı tarafından doğrulanmış görüşüne dayanır; bu
görüş **repo dışında, haricî kanıt olarak saklanmaktadır** ve bu LOCK'un
kendisi tarafından ÜRETİLMEMİŞTİR, yalnız onun ışığında alınan mühendislik
kararı (`deadline_rules.json` içindeki `legal_basis_refs` bağlantısı) kayda
geçirilmiştir. `data/provisions.json` içindeki `kanun_2577_m8_f3` ve
`kanun_2577_m61_f1` kayıtları AYRICA doğrulandı (salt-okunur audit,
DEĞİŞTİRİLMEDİ) — İYUK m.8/3 uzatma TETİKLEYİCİSİ, m.61 dönem VE çalışmaya ara
vermeyen mahkeme İSTİSNASI olarak doğru şekilde ayrı referanslardır; bu ikisi
arasında bir kapsam karışıklığı YOKTUR.

**C. Üretim mantığı ve mekanizma** — LOCKED Row 8 `src/deadline_calculator.py`
dosyasına eklenen, exact 12 madde:

1. **5604 m.1/3 duraklama/devam mekanizması** —
   `apply_mali_tatil_pause_resume()` fonksiyonu, 5604 m.1/3'teki "vergiyle
   ilgili işlemlere ilişkin dava açma süreleri" hükmü kapsamındaki süreyi her
   yıl 1-20 Temmuz (20'si dahil, Haziran'ın son gününün tatil günü olması
   halinde ilk iş gününü takip eden günden başlayan fıkra-1 edge case dahil)
   mali tatil boyunca durdurur; süre mali tatilin bitiminden itibaren tekrar
   işlemeye başlar.
2. **Fiilen mali tatil İÇİNDE gerçekleşen tebligat** — fıkra 5 kapsamındaki
   özel süre başlangıcı, ilk sayılan gün mali tatilin bitimini izleyen 21
   Temmuz olacak şekilde hesaplanır (Test B: anchor `2026-07-10` → final
   `2026-09-07`).
3. **Hesaplayıcı tebligatın hukuka uygunluğuna karar VERMEZ** — canonical
   timeline'da ayrıca doğrulanmış fiilî tebliğ tarihi girdi olarak alınır;
   idarenin neden mali tatilde tebligat yaptığı veya tebligatın usule uygun
   olup olmadığı DEĞERLENDİRİLMEZ.
4. **5604 m.1/5 Kanun lafzı vs 1 Sıra No.lu Genel Tebliğ §7 idari yorumu
   ayrımı** — `data/provisions.json` içindeki `kanun_5604_m1` kaydının
   `ev_5604_m1_original_statute` evidence notu, kanunun m.1/5 lafzının farklı
   okumalara elverişli olduğunu, ANCAK 1 Sıra No.lu Mali Tatil Uygulaması
   Hakkında Genel Tebliğ'in 7. bölümündeki idari yoruma göre vergi ve ceza
   ihbarnamelerinin mali tatil süresince mükelleflere BİLDİRİLMEDİĞİNİ açıkça
   kaydeder; önceki taslaktaki ters çerçeveleme final remediasyon turunda
   düzeltilmiştir. Kanunun doğrulanmış statute_text alıntısı ("HARİÇ" ibaresi
   dahil) hiç değiştirilmedi.
5. **5604 m.1/6 güncel beş günlük taban** — 6661 sayılı Kanunun 18 inci
   maddesiyle "yedi gün"den "beş gün"e indirilen asgari süre
   (`MALI_TATIL_GRACE_PERIOD_DAYS = 5`); m.1/2'nin KENDİ "yedi gün" ibaresi
   2007'den bu yana DEĞİŞMEMİŞTİR — yalnız fıkra 6 değişti, fıkra 2 DEĞİL
   (önceki bir yorum yanlışlığı bu turda düzeltildi).
6. **Çalışmaya ara vermeyen mahkemede (`judicial_recess_applicable=False`)
   fail-closed `needs_review`** — sonuç YALNIZ m.1/6'nın beş günlük asgari
   süresiyle belirleniyorsa (`grace_floor_applied=True`) VE
   `judicial_recess_applicable is False` ise, `calculate_rule_deadline()`
   fonksiyonu artık `needs_review` döner (`reason` alanı içinde sabit
   `mali_tatil_grace_floor_unconfirmed_without_recess` literali) — avukat
   görüşündeki ihtiyat nedeniyle, çalışmaya ara vermeyen mahkemelerde nihai
   sonucu yalnız bu mekanizma belirliyorsa otomatik kesin tarih üretilmez
   (Test D: anchor `2026-06-01`, `judicial_recess_applicable=False` →
   `needs_review`, `mali_tatil_applied=True`, `calculated_deadline=None`).
   `judicial_recess_applicable=None` durumu mevcut, bu turdan önceki
   davranışla AYNI şekilde `needs_review` verir (Test E).
7. **5604 m.1/7 vergi/idare istisnaları** — `MALI_TATIL_EXCLUDED_TAX_TYPES`
   (özel tüketim vergisi/ötv, banka ve sigorta muameleleri vergisi/bsmv, özel
   iletişim vergisi/öiv, şans oyunları vergisi — 6661 sayılı Kanunla eklenen
   dört tür) ve `MALI_TATIL_EXCLUDED_AUTHORITY_KEYWORDS` (gümrük, belediye, il
   özel idaresi — 2007'den beri fıkrada mevcut, 2016'da EKLENMEMİŞ), dar ve
   doğrulanmış bir `MALI_TATIL_INCLUDED_TAX_TYPES` allowlist'ine (KDV,
   kurumlar/gelir/damga/veraset-intikal/motorlu taşıtlar vergisi, vergi
   ziyaı/usulsüzlük/özel usulsüzlük cezası) karşı deterministik olarak kontrol
   edilir; tanınmayan bir tax_type fail-closed `needs_review` döner. "Gecikme
   faizi"/"gecikme zammı" BİLİNÇLİ olarak allowlist'te DEĞİLDİR — bağımsız
   inceleme remediasyonu, m.1/2-b metninde yalnız "gecikme faizlerinin ödeme
   süresi"nin ismen geçtiğini ("gecikme zammı" bu fıkrada YOKTUR) ve bu ödeme
   süresinin fıkra 3'ün duraklama/devam mekanizmasından FARKLI olduğunu tespit
   etti; avukat teyidi olmadan bir varsayım İCAT EDİLMEDİ, iki negatif test
   eklendi.
8. **Mali tatil m.1/7 istisnası altında bile İYUK m.8/3 adli tatil uzatmasının
   BAĞIMSIZ çalışabilmesi** — `mali_tatil_applied=False` VE
   `judicial_recess_applied=True` AYNI kayıtta COEXIST edebilir (Test C:
   anchor `2026-06-25`, ÖTV, `judicial_recess_applicable=True` →
   `mali_tatil_applied=False`, `judicial_recess_applied=True`, final
   `2026-09-07`); mali tatilden istisna olmak adli tatil uzatmasını ETKİLEMEZ.
9. **İYUK m.8/3 = uzatma tetikleyicisi, m.61 = dönem + mahkeme istisnası** —
   bu turda salt-okunur audit ile doğrulandı (bkz. B); `deadline_rules.json`
   ve `data/provisions.json` içinde bu ayrımı bozan HİÇBİR değişiklik
   yapılmadı.
10. **Türkçe Unicode normalizasyonu ve fail-closed sınıflandırma** — yeni, dar
   `_normalize_mali_tatil_text()` fonksiyonu ("İ" harfinin Python `casefold()`
   çağrısında "i"+U+0307'ye dönüşüp alias eşleşmesini sessizce kırdığı,
   bağımsız incelemede bulunan bir Unicode fail-open riskini kapatır);
   tanınmayan/belirsiz bir tax_type veya issuing_authority HER ZAMAN
   `needs_review`'a düşer, sessiz tahmin YAPILMAZ; paylaşılan
   `normalize_string()` fonksiyonu DEĞİŞTİRİLMEDİ — düzeltme yalnız mali
   tatilin kendi, yeni fonksiyonuna sınırlıdır.
11. **Avukatın yazılı m.1/3 teyidi** — kullanıcı tarafından doğrulanmış, repo
   dışında saklanan haricî hukuk kanıtıdır (bkz. B).
12. **Commit ve test kanıtları** — bkz. D ve E.

**D. Dürüst kronoloji (aşamalar birleştirilmeden)** — (1) İlk hukuki
doğrulama, `legal_basis_refs` eklenmesi ve iki-katmanlı fıkra-7 scope kontrolü
tasarımı; `stopping_event_status` bilinçli olarak bu turun DIŞINDA bırakıldı.
(2)-(3) Resmî, değiştirilmemiş
`scripts/run_ui_tests.py --profile production-parity` koşucusu gerçek
disposable PostgreSQL ile ayrı ayrı çalıştırıldı; ilk tam koşuda
`ui/tests/test_deadline_calendar_derivation_isolated.py` dosyasının S10/S12
senaryoları GERÇEK bir regresyon olarak FAIL etti (anchor `2026-06-25` artık
`case_tax_context` olmadan mali tatil penceresini kesiyordu). (4) Zorunlu,
salt-okunur bir caller audit (her production/test çağıranın context erişimini
sınıflandıran) yapıldı; audit hiçbir production caller'ın context erişimden
yoksun olmadığını doğruladı; dar bir test düzeltmesi (yalnız S10/S12'nin
anchor'ı `2026-07-21`'e kaydırıldı, `case_tax_context` İCAT EDİLMEDİ)
uygulandı. (5) Bağımsız bir inceleme "NOT READY — REMEDIATION REQUIRED" verdi:
Unicode fail-open bulgusu (bkz. C.10), eksik bir mali-tatil+adli-tatil
birleşik testi, yanıltıcı bir provenance cümlesi ve "gecikme faizi"/"gecikme
zammı"nın avukat teyidi olmadan allowlist'e alınmış olması (bkz. C.7) — dar
bir remediasyon turuyla kapatıldı. (6) Ayrı bir "FINAL LEGAL ALIGNMENT AUDIT"
turunda, taze bir hukuk görüşü ışığında beş karar uygulandı: m.8/3 vs m.61
audit'inin DEĞİŞİKLİK GEREKTİRMEDİĞİ doğrulandı (bkz. B); üç LOW not (m.1/2
"yedi gün" yanlış yorumu, "gecikme zammı"nın m.1/2-b'ye yanlış atfı, bayat
T07m/T07n referansı) düzeltildi; genuine bir üretim mantığı değişikliği
eklendi (bkz. C.6, grace-floor-without-recess → `needs_review`); Test A-F
eklendi (bkz. E). (7) Ayrı, dar bir "FINAL LEGAL WORDING CORRECTION" turunda,
avukatın 1 Sıra No.lu Genel Tebliğ §7'ye dayanan netleştirmesi ışığında
`data/provisions.json` içindeki fıkra-5 notu düzeltildi (bkz. C.4) —
`src/deadline_calculator.py` DOKUNULMADI, hiçbir test literal olarak eski
yanlış cümleyi beklemediğinden STOP koşulu OLUŞMADI. (8) Kullanıcı onayıyla
tek, amendsiz commit oluşturuldu (`ce3cb01c131728d3f26ce9af464b58161b46cdc5`),
commit sonrası resmî production-parity commit'li baytlar üzerinde TEKRAR
çalıştırıldı.

**E. Test kanıtı — dürüst zaman ayrımıyla (yalnız fiilen çalıştırılmış
sonuçlar)**:

- `deadline_calculator.py --self-test`: **27/27 PASS**
- `ui/tests/test_deadline_calculator_mali_tatil_isolated.py`: **60/60 PASS** —
  Test A-F (bkz. C.1-C.9) dahil, gerçek `case_0001` kopyası üzerinden
  `build_deadline_record()` uçtan-uca zinciriyle
- `ui/tests/test_deadline_calendar_derivation_isolated.py`: **38/38 PASS**
- `ui/tests/test_deadline_engine_isolated.py`: **33/33 PASS**
- `provision_repository.py --self-test`: **7/7 PASS**
- `provision_manifest_validator.py --self-test`: **GEÇERLİ** (8 provision
  version, 0 hata, 7 pre-existing/ilgisiz uyarı — `ingest.enabled=False`)
- `deadline_legal_basis_resolver.py --self-test`: **15/15 PASS**
  (`KANUN_5604_m1` dahil 7 ref, hepsi `resolved_verified`/`activation=True`)

**Commit-öncesi son doğrulama koşusu** (fresh disposable PostgreSQL 16,
migration 0001-0005): **78/78 modül PASS, 6074 passed, 0 failed, 8 counted
skip, 14 informational skip**, guard 10/10
(`armed_count: 212 = expected_armed: 212`). Bu koşuda
`test_fact_verification_mutation_facade_isolated` modülü, ayrı, önceki bir
denemede bir kez `CRASH_MID_RUN` durumu verdi
(`PermissionError: [WinError 5]`, Windows'a özgü geçici bir dosya-kilidi
olayı, `os.replace()` çağrısı sırasında) — kalıntı bırakmadı (`data/cases/`
yalnız `case_0001`), aynı modül bir önceki VE sonraki tüm koşularda
(`149/149`) temiz PASS etti. Bu olay mali tatil kapsamı dışındaki,
değiştirilmemiş bir modülde gözlenmiş; sonraki bağımsız ve commit-sonrası
koşumlarda tekrar üretilememiş ve mali tatil implementasyonuna
atfedilememiştir. Runner/environment olayı olarak kayda geçirilmiştir; hiçbir
dosyada otomatik düzeltme/amend YAPILMADI.

**Commit-sonrası resmî `production-parity` koşusu** (üçüncü, tamamen taze
disposable PostgreSQL 16 kümesi, `ce3cb01c131728d3f26ce9af464b58161b46cdc5`
commit'li baytlar üzerinde):

- `runner_exit_code: 0`, `state: completed`, `SWEEP FULL`
- `git.head: ce3cb01c131728d3f26ce9af464b58161b46cdc5`, `git.clean: true`
- **78/78 modül PASS** (`modules_non_pass: 0`)
- **6074 passed, 0 failed, 8 counted skip, 14 informational skip**
- `test_fact_verification_mutation_facade_isolated`: **149/149 PASS** (bir
  önceki WinError 5 olayı TEKRARLANMADI)
- 14 `*_postgres` modülünün TAMAMI gerçek, loopback-only PostgreSQL ile PASS
- Guard: `armed_count: 212 = expected_armed: 212`, `net_blocked_count: 0`,
  `env_open_blocked_count: 0`, positive controls **10/10**
- `postgres.migrations_ok: true`, `migrations_missing: []`,
  `server_addr_loopback: true`
- `integrity.protected_manifest_ok: true`, `protected_path_diff: []`,
  `secret_scan.hits: []`, tüm residue alanları boş
- `refusals: []`, `warnings: []`, `tmp_dir_removed: true`

Raporlanan disposable PostgreSQL kümeleri ve geçici çıktı dizinleri koşumlar
sonunda temizlenmiştir; gerçek `data/` ağacı (özellikle `case_0001`, 65 dosya)
test/koşum boyunca DEĞİŞMEDİ.

**F. Kalan/AÇIK sınırlar (kapatılmış gösterilmez)**:

1. `data/holiday_calendar/holiday_calendar.json` içindeki 2024-2035 yıllarının
   TAMAMI hâlâ `verified:false`'tur — gerçek dosyalar bu nedenle
   `needs_review`'a düşebilir; bu LOCK takvim içeriğini DOĞRULAMAZ (bkz. Pilot
   Readiness Adım 5 checkpoint özeti).
2. 27.01.2016 (6661 sayılı Kanunun yürürlüğe girdiği tarih) öncesi mali tatil
   hükümlerinin (fıkra 6'nın eski "yedi gün"ü, fıkra 7'nin eski, dört türü
   kapsamayan hali) temporal modellemesi YOKTUR — Deadline Calculator V1
   yalnız GÜNCEL, yürürlükteki metni kullanır.
3. `stopping_event_status` bu turun kapsamında DEĞİLDİR ve ayrı, gelecekteki
   bir çalışma olarak açık kalır.
4. Gelecekte mali tatil ref'i (`KANUN_5604_m1`) taşıyıp İYUK adli tatil
   ref'lerini (`IYUK_2577_m8_3`/`IYUK_2577_m61_1`) TAŞIMAYAN yeni bir deadline
   rule eklenirse, grace-floor/recess birleşimi (bkz. C.6) yeniden
   doğrulanmalıdır — mevcut, tek üretim kuralında
   (`iyuk_tax_court_general_lawsuit_filing`, yedi ref'in TAMAMINI taşıyor) bu
   durum yapısal olarak erişilemezdir.
5. **Bu LOCK, pilotun genel hazır olduğunu, tatil takviminin doğrulandığını
   veya uygulamanın production-ready olduğunu İDDİA ETMEZ** — yalnız mali
   tatil (5604 sayılı Kanun) mekanizmasının kendisini, avukat teyidiyle
   birlikte, kapsar.

**Final verdict**:

`MALİ TATİL DEADLINE HANDLING LOCK-READY — NO BLOCKING FINDINGS`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu gibi
yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock işlemidir;
hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Holiday Calendar Schema V2 — Phase A Technical Plumbing (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve dar kapsam** — Pilot Readiness Adım 5, git-governed,
tarihsiz bir resmî tatil takvimi registry'si ve `calendar_complete`
türetimini kilitlemişti; Adım 6 (avukat doğrulaması) hâlâ ACTIVE /
NEXT'tir. Avukatın doğrulanmış tarihleri gerçekten girebilmesi için
takvimin, her tatil gününü kayıtlı bir canonical gözleme
(`observance_id`) bağlayan, yarım günü açık bir politikaya göre ele
alan ve doğrulanmış bir yılın tamlığını makine düzeyinde denetleyen
bir yapıya ihtiyacı vardı. Phase A yalnız bu **teknik tesisatı**
kurar: şema, registry, validator ve LOCKED Row 8 hesaplayıcı tarafı.
Phase A **hiçbir resmî tatil tarihi eklemez, hiçbir yılı
`verified:true` yapmaz, hiçbir `verification_ref` almaz ve avukat
doğrulamasını tamamlamaz.** Bu bölüm YALNIZ "Holiday Calendar Schema
V2 — Phase A Technical Plumbing" alt kapsamını DONE / LOCKED olarak
kaydeder; 2024–2035 resmî tatil tarihlerinin üretime eklenmesi,
`holiday_calendar` veri popülasyonu, herhangi bir yılın
`verified:true` yapılması, `verification_ref` alınması, avukat
doğrulamasının tamamlanması, Phase B ve pilotun genel olarak
production-ready olması BU BÖLÜMDE DONE / LOCKED DEĞİLDİR. Adım 5
checkpoint'inin §F'si şemanın V1 (`calendar_version` 1) durumunu
tanımlar ve kendi commit'i için tarihsel olarak doğru kalır —
DEĞİŞTİRİLMEDİ.

**B. Exact kapsam ve commit** — Kullanıcı tarafından, bağımsız final
re-review'ün `PHASE A READY FOR COMMIT AUTHORIZATION` verdict'inden
sonra açıkça yetkilendirilen tek commit: **0 YENİ + 7 DEĞİŞTİRİLMİŞ =
7 dosya**; `git show --numstat`: 1872 ekleme, 20 silme (şema 68/2,
registry 1/1, hesaplayıcı 122/13, validator 1241/2, derivation testi
83/0, engine testi 3/2, validator testi 354/0). Yerel commit
`1366e8e40d7923c304f4a818caa65b211764b593`, parent
`d2e66fe6b75bb95fa3fe3f00ffe3dbc241f99023`, subject
`Implement holiday calendar schema v2 phase A plumbing` (body/trailer
YOK; push YAPILMADI). Commit öncesi preflight, staged 7 blob'un
SHA-256'larını yetki listesiyle bayt-bayt eşleştirdi; commit sonrası
`HEAD:<path>`
blob'larının AYNI SHA-256'ları taşıdığı doğrulandı (hiçbir hook dosya
yeniden yazmadı); 7 blob da LF'dir (0 CR). Üretim verisinde YALNIZ
registry'nin `calendar_version` değeri değişti (tek satır);
`data/cases/**`, `data/documents.json`, `data/provisions.json`,
`data/deadline_rules/deadline_rules.json`, `data/corpus_policy/**`
DEĞİŞMEDİ. Sıfır migration, sıfır web/CLI yüzeyi, sıfır bağımlılık
değişikliği; `ui/services/generation_mutation_facade.py`,
`ui/services/generation_mutation_adapters.py`, `ui/cli_mutate.py`,
`src/deadline_engine.py`, `data/case_deadline.schema.json` ve
`data/deadline_rules/deadline_rules.json` bu commit'te DOKUNULMADI.

| Dosya | Durum | SHA-256 (commit blob, LF) |
|---|---|---|
| `data/holiday_calendar.schema.json` | DEĞİŞTİRİLMİŞ (Adım 5 LOCKED) | `d62b3e7574b0f1b33eb998e7bb0d4579fc490f466df29cb50ddbfd4a1a463117` |
| `data/holiday_calendar/holiday_calendar.json` | DEĞİŞTİRİLMİŞ (Adım 5 LOCKED; yalnız `calendar_version` 1→2) | `26741d7aa36d54d2a88f6d49fc166d14c6a94246857c96fc9b59c4db68220004` |
| `src/deadline_calculator.py` | DEĞİŞTİRİLMİŞ (**LOCKED Row 8**) | `ee03abefc74cb4227981f7c3017e1c6f9d0cc5e8e9a9ffcf67a526f355631385` |
| `src/holiday_calendar_validator.py` | DEĞİŞTİRİLMİŞ (Adım 5 LOCKED) | `0dc271c24313421e6c7d9456e04d024f50d9ff9f31ca46cdda661f0b5323a32a` |
| `ui/tests/test_deadline_calendar_derivation_isolated.py` | DEĞİŞTİRİLMİŞ (yalnız additive kanıt, 0 silme) | `b48c86d384a6897aa94a97e74fdc2c94e7bce338fe3030379c45d215f537bd93` |
| `ui/tests/test_holiday_calendar_validator_isolated.py` | DEĞİŞTİRİLMİŞ (yalnız additive kanıt, 0 silme) | `d740b94318bde3a3b952479c9e2dc4231351b153740c43c79eb1068b76e73e18` |
| `ui/tests/test_deadline_engine_isolated.py` | DEĞİŞTİRİLMİŞ (8b tutarlılık: sabit `1` yerine üretim dosyasından okunan `calendar_version`) | `0965195bfbd98d49443bf33d0e34d3e336eee0a7b31168219eb8b04c97f4e269` |

**C. Şema sözleşmesi (`data/holiday_calendar.schema.json`)** — Title
`"...Schema V1"` → `"...Schema V2"` (kozmetik); `schema_version` `const`
**1** DEĞİŞMEDİ; `calendar_id` `const "tr_official_holiday_calendar_v1"`
DEĞİŞMEDİ (bu bir kimlik literalidir, §H madde 4'teki kozmetik "V1"
başlık metinlerinden AYRIDIR). `calendar_version` şemada
`integer, minimum: 1` olarak kalır — şema 2'ye PİNLEMEZ; 1→2 artışı
üretim registry'sinin DEĞERİNDEDİR (§D). `half_day_policy` **top-level**
kaldı; eski üç değer `not_decided`, `counts_as_holiday`,
`counts_as_working_day` korundu; dördüncü, additive değer
`needs_review_if_deadline_day` eklendi (şema diff'inde görünen tek
"silinen" enum satırı, üçüncü değere sondaki virgülün eklenmesinden
ibarettir — üç eski değerin tamamı yerinde). `holiday_entry`'nin
zorunlu alanları (`date`, `name`, `kind`, `day_type`,
`source_ref_index`, `notes`) DEĞİŞMEDİ; **opsiyonel, additive
`observances[]`** (`minItems: 1`, her üye `$defs.observance`) eklendi —
`observances[]` taşımayan legacy flat kayıt şemada geçerli kalır.
`$defs.observance`: `observance_id` (kapalı enum, **17** değer:
`yilbasi`, `ulusal_egemenlik_cocuk_bayrami`, `emek_dayanisma_gunu`,
`ataturk_anma_genclik_spor_bayrami`, `demokrasi_milli_birlik_gunu`,
`zafer_bayrami`, `cumhuriyet_bayrami_arefe`, `cumhuriyet_bayrami`,
`ramazan_bayrami_arefe`, `ramazan_bayrami_gun1`..`gun3`,
`kurban_bayrami_arefe`, `kurban_bayrami_gun1`..`gun4`), `kind`
(`national`/`religious`), `day_type` (`full_day`/`half_day`),
`legal_basis_ref` (boş olmayan string), `block_index` (`integer ≥ 1`
veya `null`) — beşi de zorunlu; `additionalProperties: false`.

**D. Üretim registry'si (`data/holiday_calendar/holiday_calendar.json`)
— hâlâ tarihsiz** — Commit'teki TEK içerik değişikliği
`calendar_version` `1` → `2`'dir (tek satır). Commit'li baytlar
üzerinden doğrulanan güncel durum: 12 yıl (2024–2035); her yılda
`holidays: []` ve `source_refs: []`; `verified:true` sayısı **0** (12
yılın tamamı `false`); tüm `verification_ref` değerleri `null`; hiçbir
yerde `observances` anahtarı YOK; üretim `half_day_policy` hâlâ
`not_decided` — yani dördüncü politika şema ve hesaplayıcı düzeyinde
MEVCUT ama üretimde BENİMSENMEMİŞTİR ve Adım 5'in "`not_decided` iken
`verified:true` bir yılda `half_day` girdisi ERROR" kapısı AYNEN
yürürlüktedir. `calendar_version` artışı, takvim ham baytlarının
`generation.deadline` `input_digest`'ine (Adım 5, `digest_version`
`row19c3ci.deadline.v3`) girmesi nedeniyle tasarım gereği yeni
deadline generation identity'leri üretir (bkz. §H madde 6).

**E. Validator sözleşmesi (`src/holiday_calendar_validator.py`)** —
`HOLIDAY_CALENDAR_VALIDATOR_VERSION` `"1"` → `"2"`; dosyanın iki
silinen satırı bu literal ile eski `V1: 26/26 PASS` self-test
banner'ıdır (yerine `V2: 55/55 PASS`). **Canonical observance
registry**: `CANONICAL_OBSERVANCE_REGISTRY` tam **17** kayıt
(`assert len(...) == 17` modül yükünde), her kayıt aile/kind/
day_type/sequence_position taşır;
`validate_observance_registry_consistency()` bilinmeyen
`observance_id`'yi, aynı girdi içindeki tekrar eden `observance_id`'yi,
ulusal gözlemde `null` olmayan `block_index`'i ve dinî gözlemde pozitif
tam sayı olmayan `block_index`'i reddeder. **Duplicate anahtarları**:
ulusal gözlem yıl içinde TAM 1 kez (anahtar `observance_id`); dinî
gözlem anahtarı `(family, block_index, observance_id)` — aynı id'nin
FARKLI `block_index`'lerde bulunması meşrudur (2033'ün iki Ramazan
bloğu). **Çok bloklu yıllar**: her `(family, block_index)` bloğu
bağımsız doğrulanır (blok içi bitişiklik ve blok-başına tamlık);
kaynak yorumları, Phase A bağımsız incelemesinin bulduğu bir F1
remediation'ını kaydeder — eski last-wins `seen_oids` sözlüğü, iki
bloklu bir yılda ikinci bloğun birinci bloğun eksiğini MASKELEMESİNE
yol açıyordu (çok-bloklu tamlık fail-open); occurrence listeleri ile
blok-başına ayrı değerlendirmeye geçilerek kapatıldı (bkz. §G). **Exact
dinî
blok-sayısı sözleşmesi** (`REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT`,
`REV41_BLOCK_COUNT_SUPPORTED_YEARS` = 2024..2035, 12 yıl, modül-yükü
assert'leriyle): Ramazan 2033 = **2** blok, diğer tüm Ramazan yılları
= 1, Kurban her yıl = 1.
`validate_verified_year_observance_completeness()` yalnız
`verified is True` OLAN VE `observances[]` modelini en az bir girdide
kullanan yıllar için çalışır; destek aralığı DIŞINDA `verified:true` +
`observances[]` bir yıl **sessiz tahmin yerine fail-closed reddedilir**
("refusing to guess; extend the contract with lawyer-verified input").
Saf-legacy (`observances[]`'sız) `verified:true` yıl bu tamlık
kapısının KAPSAMI DIŞINDADIR — mevcut legacy structural kontroller
onu kapsamaya devam eder (bkz. §H madde 3). Kaynak yorumlarına göre
blok-sayısı tablosunun değerleri, bağımsız incelemeden geçmiş bir
"REV4.1 tasarım paketi"nden birebir taşınmıştır; o paket bu
repository'de DEĞİLDİR ve bu checkpoint onun içeriğini
doğrulamaz/üretmez — yalnız kaynak kodun kendi atfını kaydeder.

**F. Hesaplayıcı davranışı (`src/deadline_calculator.py`, LOCKED Row
8)** — `derive_effective_holiday_calendar()`: bir girdi `observances[]`
taşıyorsa efektif `day_type`, gözlemlerin `day_type` kümesinde
`full_day` VARSA `full_day`, yoksa `half_day` olarak türetilir
(**full-day + half-day çakışmasında full-day üstün gelir**);
`observances[]` yoksa legacy flat `day_type` okunur (uyumluluk).
`full_day` (ve `counts_as_holiday` altındaki `half_day`) tarihleri
eskisi gibi `holiday_dates`'e girer; YALNIZ
`half_day_policy == "needs_review_if_deadline_day"` iken ve YALNIZ
gerçekten yalnız-half-day kalan tarihler yeni, ayrı `half_day_only_dates`
kümesine girer; diğer üç politikada bu küme HER ZAMAN boştur.
`calculate_rule_deadline()`: adli tatil/hafta sonu/tatil kaydırması ve
Adım 5'in takvim-kapsam kapısı DEĞİŞMEDEN çalıştıktan sonra,
`final_deadline` `half_day_only_dates` içindeyse **fail-closed
`needs_review`** (`calculated_deadline: null`,
`holiday_adjustment_applied: false`,
`reason: holiday_calendar_half_day_deadline_requires_review`) döner;
`full_day` tarihleri zaten kaydırıldığı için bu dal yalnız gerçekten
yalnız-half-day final günlerde tetiklenir ve yalnız
`end_day_policy == next_business_day_if_holiday` dalına sınırlıdır
(bugün aktif tek kural). Commit diff'inde `calculate_rule_deadline` ve
`load_holiday_calendar` hunk'ları saf EKLEMEDİR (sıfır silme); silinen
13 satırın tamamı (11 içerikli + 2 boş)
`derive_effective_holiday_calendar`'ın iki hunk'ına — flat `day_type`
okumasının observance-farkındalı yeniden düzenlenmesine — aittir.
`calculation_state` sözlüğü, mali tatil (Adım 7) mantığı ve
`DEFAULT_HOLIDAY_CALENDAR_PATH` sabiti DEĞİŞMEDİ.
`load_holiday_calendar()` audit alanı olarak takvimin
`calendar_version`'ını taşımaya devam eder;
`ui/tests/test_deadline_engine_isolated.py`'nin 8b kontrolü, sabit `1`
literali yerine üretim dosyasından okunan `calendar_version` değerini
karşılaştırır — bir tutarlılık kontrolüdür, güçlendirilmiş veya
gevşetilmiş bir assertion DEĞİLDİR.

**G. Test ve inceleme kanıtı — attribution açık** — Bu roadmap-lock
taslağı turunda HİÇBİR test çalıştırılmadı ve HİÇBİR commit
oluşturulmadı. Aşağıdaki test sayıları, verdict'ler ve F1/F2
inceleme-remediasyon kaydı, kullanıcı tarafından sağlanan uygulama ve
bağımsız inceleme raporlarına dayanır; REV2 bunları attribution ile
kaydeder, bu taslak turunun doğrudan gözlemi olarak SUNMAZ. Testler
exact staged blob'lar üzerinde koşmuştur; commit blob'larının o staged
blob'larla SHA-256 düzeyinde birebir eşleştiği, önceki commit turunda
mekanik olarak doğrulanmıştır (bkz. §B) — kanıt bu nedenle commit'li
baytlara aittir. Commit sonrası yeni bir `production-parity` koşusu
kullanıcı kararıyla İSTENMEMİŞTİR: exact staged blob == commit blob
kanıtı ve bağımsız re-review koşumu yeterli kabul edilmiştir.

**Bağımsız inceleme ve remediasyon (gizlenmez)** — İlk bağımsız
inceleme verdict'i, exact olarak: `PHASE A NOT READY — STOP`. İki
Medium bulgu: **F1 (Medium)** — validator, cross-entry duplicate ve
çok-bloklu yıl tamlığında last-wins sözlükler nedeniyle fail-open
davranıyordu; somut risk: aynı ulusal `observance_id`'nin hayalet bir
tarihte tekrar edilmesi kabul edilebiliyor ve bu tarih `holiday_dates`
akışına girerek bir deadline'ı yanlış biçimde ileri kaydırabiliyordu;
çok-bloklu risk: tam bir ikinci blok, eksik birinci bloğu
maskeleyebiliyordu. **F2 (Medium)** — üç UI negatif testi, verified
fixture'ın ilgisiz completeness hataları nedeniyle vacuous biçimde
PASS ediyordu; hedeflenen registry mutasyonunu gerçekten
kanıtlamıyordu. Dar remediasyon YALNIZ iki dosyada yapıldı:
`src/holiday_calendar_validator.py` ve
`ui/tests/test_holiday_calendar_validator_isolated.py`. **F1
kapanışı**: occurrence-list yapısı, yıl-içi ulusal duplicate kontrolü,
dinî `(family, block_index, observance_id)` kontrolü, blok-başına
bağımsız tamlık ve exact block-count sözleşmesi ile. **F2 kapanışı**:
baseline 0 hata → tek mutasyon → spesifik hata → hedef validator
etkisizleştirilince testin FAIL olması → revert ile yeniden geçerli
düzeniyle. Remediasyon sonrası ayrı, bağımsız final re-review
verdict'i, exact olarak: `PHASE A READY FOR COMMIT AUTHORIZATION`.

Hedefli testler:

- `holiday_calendar_validator.py --self-test`: **55/55**
- `test_holiday_calendar_validator_isolated`: **79/79**
- `deadline_calculator.py --self-test`: **27/27**
- `test_deadline_calendar_derivation_isolated`: **44/44**
- `test_deadline_calculator_mali_tatil_isolated` (commit DIŞI,
  regresyon): **60/60**
- `test_deadline_engine_isolated`: **33/33**

Bağımsız final re-review verdict'i, exact olarak:
`PHASE A READY FOR COMMIT AUTHORIZATION`

Resmî `production-parity` (gerçek disposable PostgreSQL, migration
0001–0005): exit 0, `completed` / `SWEEP FULL`, **78/78 modül PASS**,
**6111 passed, 0 failed, 8 counted skip, 14 informational skip**,
guard `armed 212 = expected 212`, positive controls 10/10, protected
manifest temiz, secret scan 0 isabet, residue/refusal/warning yok.

**H. Residual sınırlar (kapatılmış gösterilmez)**

1. Üretim takvimi hâlâ BOŞ ve `verified` DEĞİLDİR (bkz. §D);
   `next_business_day_if_holiday` policy'li tek aktif kural, avukat en
   az bir yılı doğrulayıp `verified:true` yapana kadar hiçbir gerçek
   dosyada `calculated` tarih ÜRETMEZ (Adım 5 sınırı AYNEN geçerli).
2. Phase B, gerçek avukat `verification_ref`'i olmadan BAŞLAYAMAZ:
   **NOT STARTED / NOT AUTHORIZED / BLOCKED ON REAL LAWYER verification_ref**.
3. Saf legacy `verified:true` bir yıl `observances[]` taşımıyorsa yeni
   tamlık kapısı UYGULANMAZ — kaynakta belgelenmiş, bilinçli uyumluluk
   sınırıdır; legacy structural kontroller devam eder.
4. Validator içindeki bazı "V1" metinleri (modül başlığı, hata-mesajı
   öneki, `main()` banner'ları, self-test fixture `notes` metni,
   argparse `description`) kozmetik Low kaydıdır; davranışsal
   sürüm `HOLIDAY_CALENDAR_VALIDATOR_VERSION = "2"`dir ve self-test
   başarı banner'ı zaten `V2: 55/55 PASS` der. `calendar_id`
   const'ındaki `_v1` kimlik literalidir, bu maddenin KAPSAMINDA
   DEĞİLDİR.
5. Aynı kayıt içi duplicate `observance_id` hata metninde ifade
   tekrarı bulunabilir; fail-closed davranışı ETKİLEMEYEN Low kaydıdır.
6. `calendar_version` değişikliği, takvim baytları `input_digest`'e
   girdiği için deadline generation identity'lerini tasarım gereği
   değiştirir (yeni, bağımsız deneme) — kalıcı `IdempotencyConflict`
   DEĞİLDİR (Row 19C-3c-i / Adım 5 ruleset-provisions-takvim emsaliyle
   aynı sınıf).
7. `.gitattributes` yalnız `*.json`/`*.json.pending` için `eol=lf`
   zorlar; genel `*.py text eol=lf` kuralı YOKTUR. Bu nedenle Windows
   working-tree'de CRLF artefaktı oluşabilir (bu tur,
   `src/deadline_calculator.py`'nin working-tree kopyasında 5064 CR
   baytı gözlemledi; `core.autocrlf=true` altında `git status`
   temizdir). Commit blob'larının 7'si de LF'dir (0 CR — commit öncesi
   ve sonrası ayrı ayrı doğrulandı). Ayrı bir backlog konusudur; bu
   turda `.gitattributes` DEĞİŞTİRİLMEDİ.

**I. Kapsam dışı / başlamamış** — Bu checkpoint aşağıdakilerin
HİÇBİRİNE dosya-yazma, veri girişi veya implementasyon yetkisi VERMEZ:
Phase B (2024–2035 resmî tatil tarihlerinin/gözlemlerinin üretime
girişi, `source_refs`, herhangi bir yılın `verified:true` yapılması,
`verification_ref`); üretim `half_day_policy`'nin `not_decided`'dan
başka bir değere alınması (avukat kararı); Adım 6'nın kalan
soruları/altın örnekleri; Adım 7'nin mali tatil dışındaki kalan alt
kapsamları; Adım 8–13; `.gitattributes` EOL politikası; Row 19D; push.

**J. §9 LOCKED-file gerekçesi** — `src/deadline_calculator.py` (LOCKED
Row 8; Adım 5 ve Adım 7'de de dar biçimde açılmıştı): kullanıcı talebi
(Phase A onayı) + downstream uyumluluk (şema v2'nin additive
`observances[]`/dördüncü politikasının hesaplayıcı tarafından
tüketilmesi zorunludur, aksi halde şema ile hesap birbirinden kopar) +
fail-closed güvenlik (yalnız-yarım-günlük bir final gün otomatik kesin
tarih üretmemeli). Değişiklik additive'dir (deadline dalında sıfır
silme); diğer üç politika, adli tatil/mali tatil sırası, takvim-kapsam
kapısı ve `calculation_state` sözlüğü DEĞİŞMEDİ.
`data/holiday_calendar.schema.json`,
`data/holiday_calendar/holiday_calendar.json`,
`src/holiday_calendar_validator.py` (Adım 5 LOCKED): Phase A'nın
doğrudan nesneleridir; şema değişikliği additive (üç eski politika ve
legacy flat kayıt korunur), üretim registry'sinde yalnız sürüm değeri
değişir, validator yalnız yeni model için EK kontroller kazanır. Üç
test dosyası yalnız additive/tutarlılık kanıtı aldı; hiçbir mevcut
assertion gevşetilmedi. Bunların DIŞINDA hiçbir LOCKED dosya bu
commit'te açılmadı.

**K. Sayaçlar** — `ui/tests/test_*.py` modülü **78 → 78** (değişmedi);
production Python (tracked `*.py` − `ui/tests/**`) **157 → 157**
(değişmedi; Phase A yeni dosya eklemedi); migration **5 → 5**; merged
reconciliation routing key (50), logical mutation family (38), CLI
subcommand (6) — önceki checkpoint'ten aktarılır ve bu commit hiçbir
facade/registry/CLI/migration dosyasına dokunmadığı için yapısal olarak
DEĞİŞEMEZ; `data/holiday_calendar/holiday_calendar.json`
`calendar_version` **1 → 2**; `HOLIDAY_CALENDAR_VALIDATOR_VERSION`
`"1"` → `"2"`; şema title V1 → V2; `schema_version` const **1 → 1**.

**L. Süreç notu (gizlenmez)** — Bu roadmap-lock taslağı turu hiçbir
test çalıştırmadı ve hiçbir commit oluşturmadı. REV2, kullanıcı
tarafından sağlanan F1/F2 uygulama ve bağımsız inceleme sonuçlarını
attribution ile kaydeder; bunları bu taslak turunun doğrudan gözlemi
olarak sunmaz. §E'deki REV4.1 atfı commit'li kaynak kodun kendi
yorumundan alınmıştır. Commit, önceki commit turunda kullanıcının açık
yetkisi ve hash-doğrulamalı preflight sonrasında, body/trailer
eklenmeden oluşturulmuştur.

**Bağımsız final re-review verdict'i (exact)**:

`PHASE A READY FOR COMMIT AUTHORIZATION`

**DONE / LOCKED** — yalnız "Holiday Calendar Schema V2 — Phase A
Technical Plumbing" alt kapsamı için. **Phase B:
NOT STARTED / NOT AUTHORIZED / BLOCKED ON REAL LAWYER verification_ref.**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

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
- **Session-level advisory-lock için bounded acquisition / timeout**
  (Row 19C-2a'nın bağımsız final incelemesinde tespit edildi; **Row
  19C-2a'nın blocker'ı DEĞİLDİR ve o alt-fazın LOCK'unu engellememiştir**
  — Row 19D deployment hardening kapsamına taşınmıştır). `ui/services/
  mutation_lock.py` bloklayan `pg_advisory_lock` kullanır ve `ui/`,
  `src/` veya `db/` içinde hiçbir `lock_timeout`/`statement_timeout`
  tanımlı değildir; bu nedenle tutulan bir `case:<case_id>` kilidi bir
  onay isteğini süresiz bekletebilir. Row 19C-2a ilk gerçek production
  writer'ı bağladığı için bu durum artık fiilen erişilebilirdir. Olası
  yön: session-lock bağlantısında `SET lock_timeout`, veya
  `pg_try_advisory_lock` + sınırlı yeniden deneme, sonucu YENİ bir
  outcome sınıfı icat etmek yerine mevcut gated/409
  `MUTATION_REQUIRES_REVIEW` sözleşmesine eşleyerek. Bu turda
  `mutation_lock.py` ve bağlantı katmanı KASITLI olarak
  DEĞİŞTİRİLMEMİŞTİR.

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
