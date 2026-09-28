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

