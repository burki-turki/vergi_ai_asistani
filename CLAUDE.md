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
12. **Evidence Agent — ACTIVE / NEXT**
13. Argument Agent
14. Risk / Strategy Agent
15. Drafting Agent
16. QA Agent
17. Product Orchestrator Agent
18. Lawyer UI
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
- Rows 1-11 tamamlandı ve **LOCKED**
- Sıradaki canonical development row: **ROW 12 — EVIDENCE AGENT** (henüz implement
  edilmedi)

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

### Row 12 — Evidence Agent (ACTIVE / NEXT)

Henüz implement edilmedi. Row 9/10/11 tamamlanma paterni (deterministic policy/engine →
validator → agent/LLM task → approval) referans alınmalı; standart geliştirme sırası
için bkz. §4 "Her row için standart geliştirme sırası".

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
