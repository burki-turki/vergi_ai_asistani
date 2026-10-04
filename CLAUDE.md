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
- **Pilot Readiness Adım 6 — Avukat Doğrulaması — DONE / LOCKED.** Adım 6'nın
  `CLAUDE.md`'de tanımlı ÜÇ zorunlu kabul ölçütünün tamamı karşılanmıştır:
  (i) avukatın **SORU 3.1-3.8 / 5.1-5.4**'ü yanıtlaması, (ii) **altın
  örnekleri doldurması**, (iii) **takvim içeriğinin doğrulanması**
  (`data/holiday_calendar/holiday_calendar.json`'daki ilgili yılların
  `verified:true`'ya çevrilmesi). (iii) Holiday Calendar Phase B ile
  kapanmıştır (12/12 yıl `verified:true`, imzalı `HC-LAWYER-VERIFY-v1-2024-
  2035-fb79b85fcf114c95`). (i) ve (ii), **kullanıcının bu turdaki bağlayıcı
  kararıyla**, repo DIŞINDA saklanan `burki_avukat_dogrulama_paketi_DRAFT4_
  DOLDURULABILIR (1).docx` (SHA-256 `dcf4df690bf8298830a3e19b9041d148cb331
  ccd198f16bceb73129cf186ecd1`) üzerinden karşılanmıştır; bu belge **avukat
  tarafından incelenmiş/onaylanmış hukuki girdi** olarak kabul edilir ve
  cevaplarının doğrulanması için **yeniden bir avukat provenance formu
  İSTENMEYECEKTİR** (kullanıcı kararı). **DRAFT-4 elektronik imzalı DEĞİLDİR
  ve öyleymiş gibi SUNULMAZ** — e-imzalı olan tek artefakt takvim
  doğrulamasıdır (`sonn_avukat_onay.udf`); DRAFT-4, kullanıcı tarafından
  teyit edilen avukat-onaylı kaynak olarak kaydedilir. Hazırlanan
  `LAWYER-CONFIRM` (v3/v4/FINAL) ek teyit formu taslakları **KULLANILMAMIŞTIR
  ve canonical kanıt DEĞİLDİR** — repo dışındadır, hiçbir roadmap maddesi
  onlara dayanmaz ve bloklayıcı veya yapılacak iş olarak bırakılmamıştır.
  DRAFT-4'ün 14 altın örneği, üretim `deadline_calculator` zincirine karşı
  mekanik olarak doğrulanmıştır — bkz. **Adım 6 — Altın Örnek Diferansiyel
  Doğrulama** checkpoint özeti (§5 sonrası); S05 ve S11 için alınan iki
  bağlayıcı yorum kararı orada kayıtlıdır. Avukat doğrulamasının mali tatil
  alt-bölümüne ilişkin yazılı cevap daha önce alınmış ve bu cevap
  doğrultusunda Adım 7'nin mali tatil alt-kapsamı ayrı, dar bir implementasyon
  turuyla DONE/LOCKED olmuştur (bkz. aşağıdaki Pilot Readiness Adım 7 — Mali
  Tatil pointer ve checkpoint özeti). **Dar, exact iddia** (abartılmaz): bu
  LOCK YALNIZ Adım 6'nın kendi üç ölçütünü kapsar. **Adım 7'nin mali tatil
  DIŞINDAKİ kalan deadline hardening alt-kapsamları hâlâ AÇIKTIR** ve bu LOCK
  onları kapatmaz veya yetkilendirmez; eski Adım 6 pointer'ı bu Adım 7
  maddesini kendi ACTIVE gerekçeleri arasında saymıştı — bu bir kategori
  hatasıydı (Adım 7, Adım 6'dan SONRA gelir; Adım 6'yı Adım 7'ye bağlamak
  döngüsel olurdu) ve bu turda düzeltilmiştir. Açıkça
  BAŞLAMAMIŞ/YETKİLENDİRİLMEMİŞ: Adım 7'nin kalan alt-kapsamları; Adım 8 yerel
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
  production-ready olduğu İDDİA EDİLMEZ. Yukarıdaki bu paragraf Phase A
  LOCK anının TARİHSEL kaydıdır ve DEĞİŞTİRİLMEMİŞTİR. **Phase B (veri
  popülasyonu) artık DONE / LOCKED'dır** — Phase A turundaki "NOT
  STARTED / NOT AUTHORIZED / BLOCKED ON REAL LAWYER verification_ref"
  durumu bir sonraki madde tarafından SUPERSEDE EDİLMİŞTİR (bkz. Holiday
  Calendar Phase B pointer'ı ve checkpoint özeti).
- **Holiday Calendar Phase B — Veri Popülasyonu + Portable QA/Case-View
  Publisher'ları — DONE / LOCKED.** Phase A'nın teknik tesisatı üzerine,
  gerçek avukat doğrulamasına dayanan takvim verisi üretime alındı ve
  Row 16/17 için İLK resmî pending publisher'ları eklendi. Kapsam DÖRT
  yerel commit'tir (`fa6874a..dcba4db`, push YAPILMADI): `9773ffd`
  (takvim popülasyonu + şema/validator genişletmesi), `073fc6b`
  (`.gitattributes`'e tek satır `.gitignore text eol=lf`), `1c7d956`
  (Phase B Commit A — portable QA locator + koordineli QA/case-view
  publisher'ları), `dcba4db` (Phase B Commit B — `case_0001` QA ve
  case-view snapshot'larının koordineli publisher'larla yeniden
  üretilmesi). Toplam exact değişiklik: **10 YENİ + 25 DEĞİŞTİRİLMİŞ =
  35 dosya**; sıfır migration (5'te kaldı). Üretim takvimi artık
  TARİHSİZ DEĞİLDİR: `calendar_version` 2→**3**, 12 yılın **12'si de
  `verified: true`** ve non-null `verification_ref` taşıyor, **205
  tatil girdisi** ve **205'inin TAMAMI `observances`** taşıyor, 24
  `source_refs`, üretim `half_day_policy` `not_decided`→
  **`needs_review_if_deadline_day`** (Phase A'nın şema+hesaplayıcı
  düzeyinde MEVCUT ama üretimde BENİMSENMEMİŞ dördüncü politikası artık
  BENİMSENDİ). İki YENİ, case-scoped, **deterministik-only** action
  family (`generation.qa` / `generation.case_view`) YEDİNCİ, AYRI bir
  facade/adapters çiftiyle bağlandı — diğer altı çiftin HİÇBİRİ
  GENİŞLETİLMEDİ; merged reconciliation routing key **50→52**, logical
  action family **38→40**, test modülü **78→80**, `*_postgres` modülü
  **14→15**, production Python **157→159**, CLI subcommand **6**
  (DEĞİŞMEDİ — `qa`/`case_view` mevcut `generation` subcommand'ının yeni
  row key'leridir). İki resmî kapı, `dcba4db` commit'inin baytlarına
  karşı, TEMİZ bir exact-commit LF worktree'sinde ve taze/disposable bir
  PostgreSQL 16.15 örneğinde (yalnız loopback, migration 0001-0005)
  çalıştırıldı: `production-parity` **exit 0, SWEEP FULL, 80/80 modül
  PASS, 6400 passed, 0 failed** (15/15 `*_postgres` modülü GERÇEKTEN
  koştu) ve `rag-dependency` **exit 0, RAG_GATE_PASS, 3/3, 216 passed,
  0 failed**. Ayrı, salt-okunur bir post-commit doğrulama turu 12
  commit blob'unu, imzalı avukat artefaktını, 13 tarihsel audit
  kaydının bayt-değişmezliğini ve bütünlük alanlarını bağımsızca
  doğruladı; final verdict, exact olarak:
  `PHASE B POST-COMMIT GATES PASS — READY FOR ROADMAP LOCK`
  (bkz. Holiday Calendar Phase B checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce). **Dar, exact iddia**
  (abartılmaz): bu LOCK YALNIZ takvim verisinin popülasyonunu, QA/
  case-view publisher'larını ve bu dört commit'in kapılarını kapsar.
  Avukat doğrulamasının (Adım 6) TAKVİM alt-maddesi bu turla
  karşılanmıştır, ancak **Adım 6'nın kalan soruları (SORU 3.1-3.8 /
  5.1-5.4) ve altın örnekleri TAMAMLANMAMIŞTIR ve Adım 6 ACTIVE / NEXT
  olarak KALIR**; Adım 7'nin mali tatil dışındaki alt-kapsamları,
  Adım 8-13 ve corpus acquisition/population BAŞLAMAMIŞTIR; pilotun
  genel olarak production-ready olduğu İDDİA EDİLMEZ. Sertifika zinciri
  ile OCSP/CRL iptal durumu **bağımsız doğrulanmış SAYILMAZ** (bkz.
  checkpoint özeti §C).
- **Pilot Readiness Adım 7 / Slice 1 — Stopping-Event Attestation Gate —
  DONE / LOCKED.** **Adım 7'nin KENDİSİ ACTIVE / NEXT olarak KALIR** — bu
  pointer YALNIZ Slice 1'i kilitler. Slice 1, bildirim/tebliğ sonrasında
  süreyi durdurabilecek, kesebilecek veya başlangıcını değiştirebilecek bir
  işlemin bulunup bulunmadığı BİLİNMEDEN sistemin kesin son gün üretmesini
  engelleyen fail-closed bir kapıdır; `stopping_event_status ∈ {none,
  present, unknown}` + `stopping_event_attestation_ref` sözleşmesi, kapı
  sırası (`blocked_unverified_anchor` → stopping-event gate → hesaplama) ve
  generation-audit izi ile sınırlıdır. Exact kapsam: implementasyon commit'i
  `3f80945968f1429b39b47b69d7860934a5bb17b5` (**1 YENİ + 8 DEĞİŞTİRİLMİŞ = 9
  dosya**, 1555 insertion / 5 deletion) + dar entegrasyon-testi remediasyon
  commit'i `7428d00638cec619c7e2b0d6b8a74aa35f00896a` (**0 YENİ + 1
  DEĞİŞTİRİLMİŞ = 1 dosya**, 6 insertion / 0 deletion); sıfır schema, sıfır
  migration, sıfır web route, sıfır production data. Resmî kapılar exact
  commit `7428d006`'nın baytlarına karşı, TEMİZ bir exact-commit LF
  worktree'sinde ve taze/disposable bir PostgreSQL 16.15 örneğinde
  çalıştırıldı: `production-parity` **exit 0, SWEEP FULL, 82/82 modül PASS,
  6559 passed, 0 failed** ve `rag-dependency` **exit 0, RAG_GATE_PASS, 3/3,
  216 passed, 0 failed** (bkz. Adım 7 / Slice 1 checkpoint özeti, §5
  sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce). **Sıradaki iş**
  Adım 7'nin event-specific hukuki modelleme ve görünürlük alt-kapsamlarıdır:
  uzlaşma süresi ve etkileri, İYUK m.11 başvurusunun kalan süre/zımni ret
  hesabı, VUK m.35/376 kaynaklı başlangıç veya süre değişiklikleri, usulsüz
  tebligat/öğrenme tarihi etkileri, pişmanlık ihlali, değerleme komisyonu
  veya eksik matrah temeli, tarihsel çalışmaya-ara-verme dönemleri (SORU
  5.5) ve `stopping_event_status`/`stopping_event_attestation_ref`'in
  canonical `deadline.json` ile `case_view`/UI görünürlüğü — **hiçbiri bu
  Slice ile modellenmemiştir**. **Dar, exact iddia** (abartılmaz): bu LOCK
  YALNIZ fail-closed durdurma + audit izini kapsar; Adım 7'nin
  TAMAMLANDIĞINI, Adım 8-13'ün kapandığını, corpus veya Row 19D'nin
  kapandığını veya pilotun production-ready olduğunu **İDDİA ETMEZ**.
- **Pilot Readiness Adım 7 / Slice 2 — Stopping-Event Canonical and UI
  Visibility — DONE / LOCKED.** **Adım 7'nin KENDİSİ ACTIVE / NEXT olarak
  KALIR** — bu pointer YALNIZ Slice 2'yi kilitler ve Slice 1'in DONE /
  LOCKED durumunu DEĞİŞTİRMEZ. Slice 1'in yalnız generation-audit düzeyinde
  bıraktığı stopping-event beyanı, Slice 2 ile (i) yeni üretilen canonical
  deadline kayıtlarına, (ii) `case_view` projeksiyonuna ve (iii) avukat
  arayüzüne deterministik, doğrulanmış ve fail-closed biçimde taşınmıştır;
  ayrıca legacy/bozuk pending'in promosyonu writer ve journal satırından
  ÖNCE fail-closed reddedilir. Exact kapsam: kod commit'i
  `8e2ec896c6ed0ece0a61d61654b992cc80ba822e` ("Expose stopping-event
  attestations in deadline views", **1 YENİ + 20 DEĞİŞTİRİLMİŞ = 21 dosya**)
  + tally remediasyon commit'i `728c880803f6703ae8831c539c22ae8057c3c6b8`
  ("Fix template test pass tally", **0 YENİ + 1 DEĞİŞTİRİLMİŞ = 1 dosya**,
  yalnız `ui/tests/test_templates_isolated.py`; ilk commit amend
  EDİLMEDİ); sıfır migration, sıfır `data/cases/**` değişikliği, sıfır
  canonical/pending/audit üretimi, sıfır web route, sıfır yeni CLI
  subcommand. Resmî kapılar exact commit `728c880`'in baytlarına karşı,
  TEMİZ bir exact-commit LF worktree'sinde ve taze/disposable bir
  PostgreSQL 16 örneğinde çalıştırıldı: `production-parity` **exit 0,
  SWEEP FULL, 83/83 modül PASS, 6774 passed, 0 failed** ve
  `rag-dependency` **exit 0, RAG_GATE_PASS, 3/3, 216 passed, 0 failed**
  (bkz. Adım 7 / Slice 2 checkpoint özeti, §5 sonrası, "## 6.
  Cross-Cutting Backlog"dan hemen önce). **Sıradaki iş** Adım 7'nin
  event-specific hukuki modellemesi ve bunun süre hesabına GERÇEK
  etkileridir: uzlaşma, İYUK m.11 başvurusunun kalan süre/zımni ret
  hesabı, VUK m.35, VUK m.376, usulsüz tebligat/öğrenme tarihi etkileri,
  pişmanlık ihlali, değerleme komisyonu veya eksik matrah temeli ve
  tarihsel çalışmaya-ara-verme dönemleri (SORU 5.5) — bunların süre
  başlangıcı, durması ve yeniden başlaması üzerindeki hukuki aritmetiği
  **HİÇBİRİ bu Slice ile modellenmemiştir**. **Dar, exact iddia**
  (abartılmaz): bu LOCK YALNIZ görünürlüğü ve mutasyon güvenliğini
  kapsar; Adım 7'nin TAMAMLANDIĞINI, Adım 8-13'ün kapandığını, corpus
  veya Row 19D'nin kapandığını veya pilotun production-ready olduğunu
  **İDDİA ETMEZ**.

- **Pilot Readiness Adım 7 — Deadline Hardening — DONE / LOCKED FOR
  CURRENT PILOT — EVENT-SPECIFIC LEGAL ARITHMETIC EXPLICITLY EXCLUDED,
  NOT IMPLEMENTED.** Bu pointer Adım 7'yi **YALNIZ mevcut pilot
  bakımından** kapatır ve Slice 1 / Slice 2 pointer'larının "**Adım
  7'nin KENDİSİ ACTIVE / NEXT olarak KALIR**" ifadelerini SUPERSEDE
  eder; o ifadeler kendi LOCK anlarının TARİHSEL kaydı olarak
  DEĞİŞTİRİLMEDEN bırakılmıştır ve Slice 1 / Slice 2'nin kendi DONE /
  LOCKED durumları DEĞİŞMEZ. Kapanış **"olaylar modellendi" ANLAMINA
  GELMEZ**: tek dayanağı, avukatın DRAFT-4 **SORU 8.5(iii)** bağlayıcı
  talimatına uyularak bu olayların bilinçli olarak kapsam dışı
  bırakılması ve fail-closed davranışın tamamlanmış olmasıdır.

  **Altı bağlayıcı sınır:** (1) sekiz olayın (uzlaşma, İYUK m.11
  başvurusu, VUK m.35, VUK m.376, usulsüz tebligat/öğrenme tarihi,
  pişmanlık ihlali, değerleme/takdir komisyonu, SORU 5.5 tarihsel
  çalışmaya-ara-verme dönemleri) hukuki aritmetiği **MODELLENMEDİ**;
  (2) `stopping_event_status` `present` veya `unknown` iken **KESİN
  TARİH ÜRETİLMEZ** (`needs_review`, `calculated_deadline=null`);
  (3) **operatör hukuki etkiyi YORUMLAYAMAZ** — buna izin veren
  parametre/bayrak/override YOKTUR; (4) sonuç **avukat incelemesine
  gider** (`requires_human_review=True`); (5) bu olaylar gelecekte
  **ANCAK yeni ve açık YAZILI avukat kararıyla** yeniden açılabilir —
  genel bir "Adım 7 kapandı" ifadesi böyle bir kararın YERİNE GEÇMEZ;
  (6) **kapanış, bu olayların otomatik hesaplandığı ANLAMINA GELMEZ.**

  **K2 — SORMA:** mevcut pilot için yeni avukat sorusu/formu
  **HAZIRLANMAYACAKTIR**; avukat bu olayları zaten mevcut sürümün
  dışında bırakmıştır, aynı konu yeniden GÖNDERİLMEZ. Kapsam
  genişletilirse **ayrı bir sürüm kararı** olarak sorulur. **K3 —
  ERTELE:** yapılandırılmış olay intake'i ŞİMDİ YAPILMAYACAKTIR; bugün
  kaynakta gözlenen gerçek, `case.json` için koordineli bir production
  writer BULUNMADIĞIDIR, bu nedenle intake mevcut Slice'ın küçük bir
  uzantısı DEĞİLDİR ve gelecekte ayrı bir exact-scope ve sözleşme planı
  gerektirir. **K4 — Sıradaki canlı iş: PILOT READINESS ADIM 8 — YEREL
  PostgreSQL / IAM ADOPTION — ACTIVE / NEXT**; Adım 8 için hiçbir dosya
  değişikliği bu pointer ile YETKİLENDİRİLMEZ.

  **Dar, exact iddia (abartılmaz):** bu kapanış YALNIZ Adım 7'yi ve
  yalnız mevcut pilot bakımından kapsar; Adım 9-13, corpus
  acquisition/population ve Row 19D **KAPANMAMIŞTIR**. **Pilotun
  production-ready olduğu İDDİA EDİLMEZ.** Kaynak envanteri, sekiz
  olayın durumu, bugünkü fail-closed teknik yol ve SORU 5.5'e ilişkin
  sınırlı disclosure için bkz. Adım 7 kapanış checkpoint özeti, §5
  sonrası, "## 6. Cross-Cutting Backlog"dan hemen önce.

- **Pilot Readiness Adım 8 / Slice 8A — IAM Runtime Privilege Contract —
  DONE / LOCKED.** **Adım 8'in KENDİSİ ACTIVE / NEXT olarak KALIR** — bu
  pointer YALNIZ Slice 8A'yı kilitler. Implementasyon commit'i
  `229489c34574f4718e1f65b6d4f8478c308ed6a2` (2 YENİ + 4 DEĞİŞTİRİLMİŞ =
  6 dosya): `db/migrations/0006_iam_runtime_privileges.sql` least-privilege
  rol/ACL sözleşmesini (üç canonical rol, exact GRANT matrisi, PUBLIC
  schema ACL revoke'u) fail-closed, atomik ve idempotent biçimde getirir;
  `ui/tests/test_iam_runtime_privileges_postgres.py` bunu gerçek
  PostgreSQL üzerinde kanıtlar. Resmî kapılar commit'li baytlara karşı,
  temiz detached worktree ve taze disposable cluster ile çalıştırıldı:
  `production-parity` **exit 0, SWEEP FULL, 84/84 modül PASS, 6864 passed,
  0 failed** ve `rag-dependency` **exit 0, RAG_GATE_PASS, 3/3, 216 passed,
  0 failed**. **Sıradaki exact iş: Slice 8B — operatör runbook'u**;
  ardından **Slice 8C — kalıcı yerel cluster ve IAM operational adoption**.
  **Dar, exact iddia (abartılmaz):** kalıcı pilot cluster'ı **HENÜZ
  KURULMADI**; kalıcı bir veritabanına 0001–0006 **UYGULANMADI**; IAM
  admin/avukat kullanıcısı ve case assignment **OLUŞTURULMADI**; **Adım 8
  DONE/LOCKED DEĞİLDİR**; **pilotun production-ready olduğu İDDİA
  EDİLMEZ**. Ayrıntılar için bkz.
  [`pilot-readiness-step-8-slice-8a-iam-runtime-privileges.md`](docs/roadmap/checkpoints/pilot-readiness-step-8-slice-8a-iam-runtime-privileges.md).
- **Pilot Readiness Adım 8 — Yerel PostgreSQL / IAM Adoption — DONE / LOCKED
  FOR CURRENT PILOT.** Slice 8B (operatör runbook'u) ve Slice 8C (operational
  adoption) **DONE / LOCKED**. Kapanış **yalnız mevcut yerel CLI pilot kapsamı**
  bakımındandır ve Slice 8A pointer'ının "Adım 8'in KENDİSİ ACTIVE / NEXT olarak
  KALIR" ifadesini SUPERSEDE eder. Commit zinciri: `5186db94` runbook →
  `b8048015` privilege-ordering remediation → `82fc0bed` synthetic-fixture
  remediation → `4fa2d1ca` final passfile/console hardening. Kalıcı,
  loopback-only, servissiz cluster kuruldu; 0001–0006 uygulandı; ilk admin ve
  avukat kullanıcısı oluşturuldu; sentetik case üzerinde tek preview + tek apply
  ve `completed` journal satırı kanıtlandı; dump/restore paritesi kanıtlandı.
  Resmî kapılar: `production-parity` **84/84 PASS, 6864 passed, 0 failed**;
  `rag-dependency` **3/3 RAG_GATE_PASS, 216 passed, 0 failed**. **Sıradaki iş:
  Adım 9 — ACTIVE / NEXT.** Web login hâlâ **Adım 11'in gerçek Entra
  tenant'ını** bekler; **Row 19D ve Adım 9–13 açıktır**; **pilotun
  production-ready olduğu İDDİA EDİLMEZ**. Ayrıntılar:
  [`pilot-readiness-step-8-local-postgresql-iam-adoption.md`](docs/roadmap/checkpoints/pilot-readiness-step-8-local-postgresql-iam-adoption.md).
- **Pilot Readiness Adım 9 — Sentetik Concierge Dry Run ve Deadline Raporu —
  DONE / LOCKED FOR CURRENT PILOT.** Adım 8 pointer'ındaki "Adım 9 — ACTIVE /
  NEXT" ifadesini SUPERSEDE eder (o kayıt değiştirilmedi). "Dry run" ağsız
  anlamına gelmez; başarılı model çıkarımını yalnız son yetkili POST üretti.
  Tamamen sentetik tek dosyada: 9A offline concierge runtime (41 wheel, offline kurulum); egress
  harness + outer monitor; auth probe ve **tek** başarılı, maskeli sentetik
  model gönderimi; fact extraction → promotion → tebliğ tarihi verification;
  timeline generation/promotion; deadline generation/approval; salt-okunur
  avukat deadline raporu. Remediation A: fact-verification downstream sırasına
  qa/case_view eklendi. Remediation B: warnings/notes token redaksiyonu,
  masking policy v5, forward-only. Commit zinciri: `50bba37` fail-closed
  deadline report CLI → `bcf2842` downstream rerun order → `940c26b`
  warning/note redaksiyonu + masking v5. Resmî kapılar (`940c26b`):
  `production-parity` **86/86 PASS, 7192 passed, 0 failed**; `rag-dependency`
  **3/3 RAG_GATE_PASS, 216 passed, 0 failed**. Sentetik assignment revoke
  edildi; final snapshot alındı ve ignored fixture kaldırıldı; DB audit/journal
  izleri korundu. **Sıradaki iş: Adım 10 — ACTIVE / NEXT.** Web login **Adım
  11**'i bekler; **Row 19D ve Adım 10–13 açıktır**; **pilotun production-ready
  olduğu İDDİA EDİLMEZ**. Ayrıntılar:
  [`pilot-readiness-step-9-synthetic-concierge-dry-run.md`](docs/roadmap/checkpoints/pilot-readiness-step-9-synthetic-concierge-dry-run.md).

### Tarihsel Checkpoint Arşivi

Tamamlanmış Row / Phase / Step / Slice checkpoint gövdeleri (original
`CLAUDE.md` `L1166`–`L11037`, **48 blok**, 572829 karakter) bu dosyadan
**birebir (byte-exact)** çıkarılıp `docs/roadmap/checkpoints/` altına taşınmıştır.
Manifest ve reconstruction kanıtı: [`INDEX.md`](docs/roadmap/checkpoints/INDEX.md).

- [`rows-09-17-agent-layer.md`](docs/roadmap/checkpoints/rows-09-17-agent-layer.md) — blok 0–8 (original L1166–1717)
- [`row-18-lawyer-ui.md`](docs/roadmap/checkpoints/row-18-lawyer-ui.md) — blok 9–9 (original L1718–2087)
- [`row-19a-19b-threat-model-and-identity.md`](docs/roadmap/checkpoints/row-19a-19b-threat-model-and-identity.md) — blok 10–11 (original L2088–2351)
- [`row-19c-mutation-integrity.md`](docs/roadmap/checkpoints/row-19c-mutation-integrity.md) — blok 12–23 (original L2352–4896)
- [`rag-bundle-corpus-and-schema-patches.md`](docs/roadmap/checkpoints/rag-bundle-corpus-and-schema-patches.md) — blok 24–28 (original L4897–6581)
- [`row-19d-auth-and-oidc-remediation.md`](docs/roadmap/checkpoints/row-19d-auth-and-oidc-remediation.md) — blok 29–31 (original L6582–7384)
- [`pilot-readiness-steps-1-5-and-mali-tatil.md`](docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md) — blok 32–41 (original L7385–9747)
- [`holiday-calendar-and-deadline-hardening.md`](docs/roadmap/checkpoints/holiday-calendar-and-deadline-hardening.md) — blok 42–47 (original L9748–11037)

**Bu arşivler canonical historical evidence'dır; canlı politika DEĞİLDİR.**
Canlı kurallar yalnız bu dosyadadır (§1–§13). Arşivler **otomatik project
memory'ye yüklenmez**: yukarıdaki atıflar normal Markdown bağlantısıdır;
otomatik import sözdizimi (satır başında `@` önekli dosya yolu) kullanılmamıştır.

**§9 bağı:** §9, LOCKED bir row'a dokunmadan önce "hangi locked contract'ın
etkilendiği"nin raporlanmasını şart koşar. Bu nedenle bir LOCKED sözleşmeye
dokunmadan ÖNCE ilgili checkpoint'in arşiv dosyası **açıkça okunur**; arşiv
§9'un referans metnidir, ölü metin değildir.

**§5 atıf notu:** §5 maddelerindeki "bkz. ... checkpoint özeti, §5 sonrası,
'## 6. Cross-Cutting Backlog'dan hemen önce" ifadeleri artık yukarıdaki arşiv
dosyalarına işaret eder. §5'in hiçbir baytı değiştirilmemiştir.

**Bundan sonra:** her roadmap-lock turunda yeni `###` checkpoint gövdesi
**doğrudan uygun arşiv dosyasına** yazılır ve `INDEX.md`'ye kaydedilir; gövde
mevcut bir aileye aitse o dosyaya eklenir, **yeni bir faz ise** başlığından
türetilmiş slug'la **yeni bir arşiv dosyası** açılır (aynı turda INDEX'e
kaydedilir). `CLAUDE.md`'ye yalnız **kısa canlı pointer/status** yazılır —
tarihsel gövde bir daha bu dosyaya eklenmez.

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
- **Ürün Genişletme Backlog'u (öneri — 2026-10-03; roadmap sırasını
  DEĞİŞTİRMEZ).** Aşağıdaki B-01…B-20 maddeleri, pazardaki genel amaçlı
  hukuki araştırma/yazım platformlarıyla yapılan bir karşılaştırma
  sonucunda tespit edilen ürün açıklarıdır. Hiçbiri bir roadmap Row'u
  DEĞİLDİR, hiçbiri bu kayıtla YETKİLENDİRİLMEZ; her biri uygulamadan
  ÖNCE kendi exact dosya allowlist'i, kapsamı ve ayrı kullanıcı onayını
  gerektirir. LOCKED bir row'a dokunan madde §9 raporu (neden, etkilenen
  locked contract, regression riski) olmadan başlatılamaz. Hukuki dış
  görüş gerektiren maddeler `EXTERNAL LEGAL VERIFICATION REQUIRED`
  olarak işaretlidir ve kodla kapanmaz.
  §6 giriş cümlesindeki "production/pilot öncesi kapatılmalıdır"
  ifadesi bu maddelere UYGULANMAZ; B-01…B-20 isteğe bağlı ürün
  genişletme adaylarıdır, pilot veya production için ön koşul
  DEĞİLDİR (B-14 yalnız kapalı ajanların yeniden açılması için ön
  koşuldur).

  **A. Corpus / veri**
  - **B-01 — Kaynak hukuki ön değerlendirmesi** (`EXTERNAL LEGAL
    VERIFICATION REQUIRED`): her resmî kaynağın (Danıştay/Yargıtay karar
    arama, UYAP Emsal, AYM Kararlar Bilgi Bankası, mevzuat.gov.tr,
    Resmî Gazete, GİB mevzuat/özelge) kullanım şartları, otomatik erişim
    izni, FSEK m.31 kapsamı ve KVKK/anonimleştirme yükümlülüğü hakkında
    yazılı avukat görüşü. Corpus işinin (B-02…B-07) ön koşuludur.
  - **B-02 — Vergi corpus V1 kapsam tanımı**: VUK, İYUK, 213, GVK, KVK,
    KDV, ÖTV, AATUHK ve ilgili tebliğler; Danıştay VDDK ve vergi
    daireleri kararları; BİM vergi dava daireleri kararları; GİB
    özelgeleri. Kapsam LOCKED `data/corpus_policy/corpus_policy.json`
    sözleşmesi içinde ifade edilir; policy değişikliği git-governed
    kalır. Bağımlılık: B-01.
  - **B-03 — Kaynak başına içe aktarım bağlayıcıları**: önce elle
    edinim + manifest; otomatik erişim YALNIZ B-01 izin verirse. Mevcut
    `ingest.py` + `rag_bundle.build`/`rag_bundle.activate` zincirine
    bağlanır; yeni bir action family gerekirse ayrı onay. Bağımlılık:
    B-01, B-02.
  - **B-04 — Karar meta-veri çıkarımı ve doğrulaması**: `daire`,
    `esas_no`, `karar_no`, `karar_tarihi`, `temyiz_kesinlesme_durumu`
    alanlarının (RAG Corpus Prerequisite Documents-Schema Patch ile
    şemada MEVCUT) gerçek veriyle doldurulması; mevcut
    `manifest_validator.py` kuralları fail-closed kalır. Bağımlılık:
    B-03.
  - **B-05 — İçe alınan kararlarda anonimleştirme kontrolü**: kişisel
    veri taraması, şüphede fail-closed red; `llm_privacy_boundary.py`
    tarayıcılarının yeniden kullanımı değerlendirilir. Bağımlılık:
    B-01, B-03.
  - **B-06 — Düzenli güncelleme süreci**: yeni karar ve mevzuat
    değişikliklerinin periyodik alınması; yürürlük/sürüm çözümü yalnız
    Legal Knowledge Engine (§3 Prensip 20) üzerinden. Bağımlılık: B-03.
  - **B-07 — Araştırma değerlendirme seti**: avukat hazırlı soru →
    beklenen karar/madde altın seti ve ölçüm. Row 20 (Pilot /
    Evaluation) ile ilişkilidir. Bağımlılık: B-03.

  **B. Dilekçe / taslak**
  - **B-08 — Drafting agent modunun yeniden açılması**: Pilot Readiness
    Adım 4c ile pilot politikası gereği kapatıldı. Yeniden açma yalnız
    yazılı kullanıcı kararı + B-14 ile. Bağımlılık: B-14.
  - **B-09 — Vergi dava dilekçesi montaj şablonu**: canonical, onaylı
    `draft_sections[]`'ı (facts_summary, legal_basis, argument_summary,
    request, procedural_history) standart dilekçe yapısında (başlık,
    mahkeme, taraflar, konu, açıklamalar, hukuki nedenler, deliller,
    netice-i talep, ekler) birleştiren deterministik katman. LOCKED Row
    15 sözleşmesine dokunmadan, onun ÜSTÜNE eklenir; `submission_status
    = "draft_only"` korunur. Bağımlılık: B-08 veya avukat girdisi.
  - **B-10 — .docx / PDF dışa aktarma**: "TASLAK" ibaresi zorunlu;
    avukat onayı olmadan "sunulabilir" ibaresi üretilmez. Bağımlılık:
    B-09.
  - **B-11 — Avukat arayüzünde bölüm bazlı taslak düzenleme**:
    düzeltmeler pending → validation → human approval → canonical
    akışından geçer (§3 Prensip 16). Bağımlılık: B-09, Pilot Readiness
    Adım 11/12.
  - **B-12 — Dilekçe türleri genişletme**: iptal davası, tarhiyata
    itiraz, yürütmeyi durdurma talebi, istinaf, temyiz, uzlaşma
    başvurusu, VUK m.122 düzeltme başvurusu; her tür için ayrı şablon
    ve kural seti. Bağımlılık: B-09.

  **C. Entegrasyon / kullanılabilirlik**
  - **B-13 — UYAP UDF belge okuma**: tebligat/karar/dilekçe UDF'lerinin
    Case Document Layer'a (Row 3, LOCKED) yüklenmesi; çıkarılan tarih
    otomatik `verified` YAPILMAZ.
  - **B-14 — Dış LLM kullanımının hukuki çerçevesi** (`EXTERNAL LEGAL
    VERIFICATION REQUIRED`): sağlayıcı veri-işleme şartları, KVKK yurt
    dışı aktarım, avukatlık sırrı. Adım 4b/4c ile kapatılan ajanların
    (B-08 dahil) yeniden açılmasının ön koşuludur.
  - **B-15 — Kaynaklı, dosya-bağlamlı araştırma sorgu modu**: serbest
    sohbet DEĞİL; yalnız corpus'a dayanan, atıfsız cevap üretmeyen,
    deterministik cevap varken LLM'in onunla çelişemediği sınırlı
    sorgu. Kapatılmış `app.py` yolu yeniden AÇILMAZ; ayrı ürün kararı
    gerektirir. Bağımlılık: B-03, B-14.
  - **B-16 — UETS / e-tebligat tarihinin içe aktarılması**: tebliğ
    tarihi süre hesabının çapasıdır; içe aktarılan değer
    `unverified` olarak girer, `verification.fact` akışı olmadan
    yükseltilmez (§3 Prensip 8). Bağımlılık: B-13.

  **D. Ticari / operasyon**
  - **B-17 — Çok kullanıcılı büro modeli**: büro/avukat/stajyer rolleri,
    dosya paylaşımı; Row 19B IAM altyapısı üzerine. Bağımlılık: Pilot
    Readiness Adım 11.
  - **B-18 — Abonelik ve faturalama**: Row 21 (Commercial V1) kapsamında
    planlanır. Bağımlılık: B-17.
  - **B-19 — Süre hatırlatma / bildirim**: yalnız canonical, onaylı ve
    `calculated` deadline'lar için; `needs_review` veya
    `blocked_unverified_anchor` durumundaki kayıtlar için kesin tarih
    bildirimi ÜRETİLMEZ. Bağımlılık: Pilot Readiness Adım 12.
  - **B-20 — Sekiz olayın süre aritmetiği** (uzlaşma, İYUK m.11, VUK
    m.35, VUK m.376, usulsüz tebligat/öğrenme tarihi, pişmanlık ihlali,
    değerleme/takdir komisyonu, SORU 5.5 dönemleri): §5 Adım 7 kapanışı
    ve §13.2 gereği YALNIZ yeni ve açık YAZILI avukat kararıyla
    açılabilir.

  **Önerilen öncelik (bağlayıcı DEĞİL):** (1) B-01 ve B-14 — kod
  gerektirmeyen, paralel yürüyebilen dış hukuki ön koşullar; (2) Adım 10
  sonrasında B-09 → B-10; (3) Adım 11/12 ile birlikte B-02 → B-03 →
  B-04 → B-05, ardından B-07; (4) ticari öncesi B-13, B-11, B-17, B-19;
  (5) ürün kararına bağlı B-15, B-12, B-16, B-18, B-20.

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

## 13. Operasyonel Test / Gate Kuralları (canlı)

Bu bölüm, tarihsel checkpoint gövdeleri arşive taşındığı için otomatik
memory'den çıkacak olan **canlı ve bağlayıcı** operasyonel kuralları taşır.
İfadeler kaynak checkpoint'lerden **birebir** alınmıştır (yalnız satır kaydırma
mekanik olarak açılmıştır); her maddenin kaynağı ve arşiv yolu verilmiştir.

### 13.1 Promote edilmiş evrensel kurallar

**13.1.1 Resmî gate sözleşmesi ve profil/interpreter eşlemesi.**
Üç profil: `production-parity` (gerçek PostgreSQL, `vergi_ui_runtime`),
`rag-dependency` (root `.venv`, gerçek faiss/numpy/pypdf/openai/dotenv/httpx2),
`developer` (`--allow-untracked` YALNIZ developer profilinde; resmî profiller
untracked test modülünü reddeder — tracked küme ≡ dosya sistemi kümesi
zorunlu). **Hiçbir tek interpreter iki resmî profili birden karşılamaz:**
`production-parity` `vergi_ui_runtime` ile, `rag-dependency` root `.venv` ile
koşulur. Tek ve mekanik yetki sırası: exit code > özet varlığı/ad bağı >
sayılar > ham PASS/FAIL çapraz kontrolü > SKIPPED taraması; sıfır-kontrol
(`ZERO_CHECK_*`) sonuçları PASS SAYILMAZ; counted skip ile informational skip
ayrı raporlanır ve **hiçbir skip PASS sayılmaz**.
Komutlar: `python scripts/run_ui_tests.py --profile production-parity` ve
`python scripts/run_ui_tests.py --profile rag-dependency`.
*Kaynak: Pilot Readiness Adım 3, §C (original L8103–8123) —*
[`docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md`](docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md)

**13.1.2 Ham case-dizini manifest kuralı (BAĞLAYICI).**
`/data/cases/` altında çöken bir testin bıraktığı sentetik residue plain
`git status`'ta GÖRÜNMEYEBİLİR; bundan sonraki her sweep/inceleme raw
`data/cases/**` manifesti VEYA `git status --ignored -- data/cases` kontrolü
kullanmalıdır — plain `git status` artık YETERLİ DEĞİLDİR.
*Kaynak: Pilot Readiness Adım 2, §L R11 (original L7952–7957) —*
[`docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md`](docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md)

**13.1.3 `git clean -fdx` ve `git stash --all` YASAK.**
Bu iki komut ignored gerçek veriyi silebilir/yakalayabilir; gerçek case verisi
mevcutken `git clean -fdx` ve `git stash --all` YASAK.
*Kaynak: Pilot Readiness Adım 2, §L R6 + §O (original L7942–7943, L8032–8033) —*
[`docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md`](docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md)

**13.1.4 `case_0001`'e gerçek veri yasağı ve fixture protokolü.**
Operatör sınırları: gerçek veri `case_0001` içine ASLA konmaz; force-add yalnız
fixture değişikliğinde, review ile. Fixture-drift:
`git status --ignored -- data/cases/case_0001` + reviewed force-add protokolü.
*Kaynak: Pilot Readiness Adım 2, §E / §L R7 / §O (original L7844–7846,
L7944–7945, L8030–8034) —* [`docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md`](docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md)

**13.1.5 Tek-sweep / committed-bytes kuralı.**
Operatör kuralları: resmî kapılar yalnız commit'li baytlarla ve tek sweep olarak
koşulur; bir sweep sürerken repo dosyası düzenlenmez; iki sweep eşzamanlı
koşulmaz (sentetik case dizinleri `data/cases/` içinde oluşur — bkz. 13.1.2).
*Kaynak: Pilot Readiness Adım 3, §G.5 (original L8231–8235) —*
[`docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md`](docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md)

**13.1.6 Migration immutability.**
Bu commit'ten İTİBAREN `0003` **immutable** kabul edilir; gelecekteki HERHANGİ
bir şema değişikliği (constraint, kolon, index) `0003`'ü değiştirmek yerine
YENİ, ayrı numaralı bir migration dosyasına gitmelidir
(`CREATE TABLE IF NOT EXISTS` deseni var olan bir tabloyu ASLA yükseltmez — bu,
gelecekte gerçek bir kalıcı veritabanı üzerinde `0003` sonrası bir değişiklik
gerektiğinde hatırlanması gereken genel bir kısıttır, yalnız bu migration'a
özgü değildir).
*Kaynak: Row 19C-1, "Migration history note" (original L2496–2503) —*
[`docs/roadmap/checkpoints/row-19c-mutation-integrity.md`](docs/roadmap/checkpoints/row-19c-mutation-integrity.md)

**13.1.7 `rag-dependency` require-gate ön koşulu.**
Bu gate, corpus population ve RAG-bağımlı Slice 2'den ÖNCE **zorunlu bir
açılış kapısıdır** — o iki faz `require` modunda bu gate'in GERÇEKTEN PASS
ettiği bir ortam gerektirir.
*Kaynak: RAG Real-Dependency Validation + Synthetic E2E Gate (original
L5257–5259) —* [`docs/roadmap/checkpoints/rag-bundle-corpus-and-schema-patches.md`](docs/roadmap/checkpoints/rag-bundle-corpus-and-schema-patches.md)

**13.1.8 Sayaçlar sabit metinle değil git/filesystem üzerinden türetilir.**
"Bundan sonraki hiçbir turda 78/78 veya 14 beklentisi kullanılmamalıdır."
Sweep/test sayaç beklentileri **her turda yeniden türetilir**; önceki turların
sayıları yeniden kullanılmaz. Bu bölüme **hiçbir güncel sayı gömülmez**
(gömmek §12'nin "yalnız üç bölüm güncellenebilir" kuralıyla çelişir ve
bayatlamayı garanti eder). Türetme komutları:

```
git ls-files 'ui/tests/test_*.py' | wc -l
git ls-files 'ui/tests/test_*_postgres.py' | wc -l
git ls-files 'db/migrations/*.sql' | wc -l
```

Güncel resmî sayılar için en son roadmap-lock checkpoint'inin kendi sayaç
tablosu okunur (arşivde).
*Kaynak: Holiday Calendar Phase B (original L10170–10172) —*
[`docs/roadmap/checkpoints/holiday-calendar-and-deadline-hardening.md`](docs/roadmap/checkpoints/holiday-calendar-and-deadline-hardening.md)

### 13.2 §9 üzerinden bağlayıcı kalan kapsam-sınırlı sözleşmeler

Aşağıdaki maddeler **arşivde kalır** ve §9 üzerinden bağlayıcıdır: bir LOCKED
row'a dokunmadan önce ilgili arşiv dosyası okunur. Metinleri buraya
kopyalanmamıştır — yalnız checkpoint adı ve exact arşiv yolu verilmiştir.

| Sözleşme | Checkpoint | Arşiv yolu |
|---|---|---|
| Alt-faz başına tam dosya allowlist'i + ayrı onay (original L2110–2112). **Not:** sonraki Pilot Readiness adımları fiilen aynı pratiği uyguladı; bu kuralın §8'e evrensel olarak taşınması **ayrı bir kullanıcı kararıdır** | Row 19A — Threat Model & Deployment Contract | `docs/roadmap/checkpoints/row-19a-19b-threat-model-and-identity.md` |
| Row 10/11 şema yamasının ayrı onay maddesi olması (original L2123–2128; yama sonradan uygulandı) | Row 19A — Threat Model & Deployment Contract | `docs/roadmap/checkpoints/row-19a-19b-threat-model-and-identity.md` |
| Kilit-sonrası otoriter yeniden-kontrol zorunluluğu (original L2198–2200) | Row 19C-1 — Coordinator Core & Path Safety | `docs/roadmap/checkpoints/row-19c-mutation-integrity.md` |
| Ham/kullanıcı-kontrollü segmenti `resolve_for_create()`'e bağlayan her yeni writer önce `validate_segment()`'i güçlendirmeli VEYA yalnız güvenli, allowlisted dosya adları ürettiğini kanıtlamalı (original L3253–3258) | Row 19C-3a Slice 1 — Shared Path-Containment Foundation | `docs/roadmap/checkpoints/row-19c-mutation-integrity.md` |
| Builder'ın manifest dışı yeni file read eklememesi manuel code-review invariant'ıdır; runtime cross-check VARMIŞ GİBİ sunulamaz (original L4189–4191) | Row 19C-3c-ii — Agent-Gated Pending Generation | `docs/roadmap/checkpoints/row-19c-mutation-integrity.md` |
| Configurable case root (Adım 13c) için en az 36 dosya başına ayrı LOCKED-file §9 gerekçesi ZORUNLU olacaktır (original L8043–8044) | Pilot Readiness Adım 2 — Case-Data Repository Protection | `docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md` |
| Mali tatil ref'i taşıyıp İYUK adli tatil ref'lerini taşımayan yeni bir deadline rule eklenirse grace-floor/recess birleşimi yeniden doğrulanmalıdır (original L9729–9731) | Pilot Readiness Adım 7 — Mali Tatil | `docs/roadmap/checkpoints/pilot-readiness-steps-1-5-and-mali-tatil.md` |
| İki `*.generation_audit.json` çalışma kopyasının CRLF/LF sapması; ham SHA-256'sını pinleyen bir test yazılırsa sapma oluşur (original L10238–10240) | Holiday Calendar Phase B | `docs/roadmap/checkpoints/holiday-calendar-and-deadline-hardening.md` |
| Sekiz olayın hukuki aritmetiği yalnız YENİ ve açık YAZILI avukat kararıyla yeniden açılabilir (original L10913–10915; ayrıca §5'te canlı) | Adım 7 — Deadline Hardening Pilot-Scope Closure | `docs/roadmap/checkpoints/holiday-calendar-and-deadline-hardening.md` |

Supersede edilmiş (kapanmış) kurallar yalnız arşivde kalır ve canlı kural
olarak okunmaz.
