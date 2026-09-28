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

