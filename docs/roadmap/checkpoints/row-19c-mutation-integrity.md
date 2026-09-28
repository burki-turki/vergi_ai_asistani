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

