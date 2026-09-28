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

