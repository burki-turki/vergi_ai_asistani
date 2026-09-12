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
- **Sıradaki adım: RAG Real-Dependency Validation and Corpus
  Population Scope Reconciliation — ACTIVE / NEXT.**
  İmplementasyona HENÜZ BAŞLANMADI; corpus population da
  BAŞLAMAMIŞTIR. İlk adım, ayrı ve TAMAMEN salt-okunur bir
  exact-scope/allowlist reconciliation'dır. `faiss`/`numpy`/`openai`/
  `pypdf`/`python-dotenv` bu ortamda KURULU DEĞİLDİR — gerçek kurulum
  ve API uyumluluğu (özellikle FAISS serialize/deserialize şekli ve
  embedding dimension/count doğrulaması) bu fazda AYRICA
  doğrulanmalıdır. Gerçek bir build→publish→activate→
  load_pinned_bundle round-trip'i (küçük bir synthetic corpus ile) bu
  fazın ZORUNLU açılış kapısıdır. Mevzuat ve içtihat corpus'unun
  kaynak/provenance/lisans/güncelleme politikası ayrıca
  kararlaştırılmalıdır. **Bu pointer mevcut `data/**` ve `index/**`
  için hiçbir dosyaya yazma yetkisi VERMEZ.** Row 10/11
  `rag_index_version_used` şema yaması, **ROW 19C-3c-iv Slice 2 —
  Retrieval/Discovery-Dependent Generation**, GC/retention/
  maintenance işleri ve Row 19D (deployment/OS hardening, OS ACL/
  service identity dahil) bu checkpoint ile BAŞLAMAMIŞTIR ve
  YETKİLENDİRİLMEMİŞTİR. Bu pointer için yeni bir Row numarası İCAT
  EDİLMEMİŞTİR ve hiçbir dosyaya implementasyon yetkisi VERMEZ.

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
