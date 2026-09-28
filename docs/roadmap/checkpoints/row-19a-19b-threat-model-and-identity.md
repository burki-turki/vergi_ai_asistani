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

