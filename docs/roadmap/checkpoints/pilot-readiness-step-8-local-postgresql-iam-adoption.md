# Pilot Readiness Adım 8 — Yerel PostgreSQL / IAM Adoption

**DONE / LOCKED FOR CURRENT PILOT.** Bu dosya tarihsel kanıttır, canlı politika
değildir. Canlı kurallar yalnız `CLAUDE.md` §1–§13'tedir.

**Redaksiyon sözleşmesi (bağlayıcı).** Bu belge gerçek port, gerçek Windows
kullanıcı yolu, DSN, parola, passfile içeriği, `issuer`/`subject` değeri veya
bunların türevlerini **içermez**; backup arşivinin tam hash'i ve sweep
dizinlerinin yerel yolları da **yazılmamıştır**. Yer tutucular runbook'un §A.2
konvansiyonuyla aynıdır (`«PORT»`, `«DATA_DIR»`, `«SECURE_DIR»`, `«PASSFILE»`,
`«BACKUP_DIR»`, `«PILOT_DB»`, `«VERIFY_DB»`). IAM kullanıcıları numeric id ile
değil, **"ilk admin"** ve **"avukat kullanıcısı"** olarak anılır; display name'ler
yazılmamıştır. Commit SHA'ları, test sayıları ve gate sonuçları gerçektir.

---

## A. Amaç ve exact kapanış statüsü

Adım 8'in amacı, Row 19B/19C'nin IAM ve mutation altyapısını **gerçek, kalıcı
bir yerel veritabanı üzerinde** işletilebilir hâle getirmekti: least-privilege
rol sözleşmesi, operatör talimatı ve o talimatın **fiilen uygulanması**.

Kapanış statüsü:

| Alt-faz | Durum |
|---|---|
| Slice 8A — IAM Runtime Privilege Contract | **DONE / LOCKED** |
| Slice 8B — Local PostgreSQL/IAM Operator Runbook | **DONE / LOCKED** |
| Slice 8C — Operational Adoption | **DONE / LOCKED** |
| **Pilot Readiness Adım 8** | **DONE / LOCKED FOR CURRENT PILOT** |
| Sıradaki iş | **Adım 9 — ACTIVE / NEXT** |

Bu kapanış **yalnız mevcut yerel CLI pilot kapsamı** bakımındandır ve Slice 8A
pointer'ının "**Adım 8'in KENDİSİ ACTIVE / NEXT olarak KALIR**" ifadesini
SUPERSEDE eder; o ifade kendi LOCK anının tarihsel kaydı olarak
DEĞİŞTİRİLMEDEN bırakılmıştır. **Pilotun production-ready olduğu İDDİA
EDİLMEZ** (bkz. §K).

---

## B. Commit zinciri ve tarihsel sıra

| # | Commit | Kapsam |
|---|---|---|
| 1 | `229489c34574f4718e1f65b6d4f8478c308ed6a2` | Slice 8A — `0006` least-privilege migration + gerçek PostgreSQL testi (2 YENİ + 4 DEĞİŞTİRİLMİŞ) |
| 2 | `cb40f30` | Slice 8A checkpoint kaydı (doküman) |
| 3 | `5186db94b427fae7ef9b53bb96a2a02af669dc9b` | Slice 8B — operatör runbook'u (doküman) |
| 4 | `b8048015ae19a6995790df4b1ee2943b3d026b27` | Slice 8C / R1 — §I.3 privilege-ordering sorgusunun düzeltilmesi (1 M, +1/−1) |
| 5 | `82fc0bed4051826f0403e12aac2f2e1485d8148f` | Slice 8C / R-A — §K.3 sentetik-fixture doğrulama ölçütünün düzeltilmesi (1 M, +33/−6) |
| 6 | `4fa2d1ca67b08f5767650d98df0a931dd2def471` | Slice 8C — final passfile/konsol hardening (1 M, +72/−0) |

Sıra bağlayıcıydı: Slice 8C'nin **operasyonel** işi hiçbir repo dosyası
değiştirmeden yürütüldü; 4, 5 ve 6 numaralı commit'ler **yalnız runbook
metnini** düzelten, ayrı ayrı yetkilendirilmiş **doküman-only** turlardır.
Slice 8C'nin kendisinde kaynak/test/migration/data değişikliği **sıfırdır**.

---

## C. Slice 8A — least-privilege rol sözleşmesi

`db/migrations/0006_iam_runtime_privileges.sql` üç canonical rol için exact bir
GRANT matrisi, `PUBLIC` schema ACL revoke'u ve sekiz fail-closed precondition
getirir; tek transaction'dır ve `ON_ERROR_STOP`'u kendi içinde ayarlar. Herhangi
bir precondition tutmazsa **tek bir GRANT bile uygulamadan** durur ve geri alır.

Sözleşmenin Slice 8C'de kalıcı veritabanı üzerinde ölçülen hâli:

| Rol | Doğrudan yetki |
|---|---|
| `vergi_app` | **tam 11** |
| `vergi_iam_admin` | **tam 32** |
| `PUBLIC` (`iam` + `mutation` şema `USAGE`/`CREATE`) | **0** |

`vergi_iam_admin`'in 32 satırı, `0006`'nın kendi postcondition dizisiyle
mekanik olarak karşılaştırıldı: **fark 0**. Üç dikkat noktası da doğrulandı —
tek `DELETE` yalnız `iam.user_roles` üzerinde; `iam.sessions`'ta `INSERT`
**yok** (yalnız `SELECT`, `UPDATE`); `mutation.mutation_journal` admin
listesinde **hiç geçmiyor**.

**0001–0006 immutable kalır.** Uygulanmış bir migration ad-hoc
`GRANT`/`REVOKE`/`ALTER` ile düzeltilmez; her değişiklik yeni, ayrı numaralı ve
ayrıca onaylanmış bir migration gerektirir.

---

## D. Slice 8B — runbook ve üç remediation

Slice 8B, `docs/operations/local-postgresql-iam-adoption.md` dosyasını
**talimat** olarak üretti; yazıldığı turda hiçbir şey çalıştırılmadı.

Slice 8C'nin uygulaması sırasında runbook'ta **üç gerçek boşluk** gözlendi ve
**hiçbiri sessizce düzeltilmedi**; her biri durduruldu, kanıtlandı ve ayrı
onayla giderildi:

| # | Boşluk | Sonuç |
|---|---|---|
| R1 | §I.3'ün `ORDER BY priv COLLATE "C"` satırı, çıktı alias'ını bir `COLLATE` ifadesi içinde kullandığı için **hiçbir kümede çalışmaz** | İfade tekrarlanarak düzeltildi; §I.4 aynı sorguyu kullandığı için otomatik yararlandı |
| R-A | §K.3'ün "yeniden yazma sonrası yalnız `document.json` listelenir" beklentisi **ulaşılamazdı**: dizgi altı hedef ve üç `document.json` dışında onlarca dosyada da geçiyor | Beklenti, altı hedefin exact sayımını ve üç `document.json`'un bayt-özdeşliğini sınayan **fail-closed** bir kontrolle değiştirildi |
| Final | §F.2 passfile kaçış kuralını (`\:`, `\\`, kenar boşluğu, joker, BOM) söylemiyordu; §D, başlatan konsolun kapanmasının kümeyi düşürdüğünü uyarmıyordu; §D'nin `server.log` yerleşimi geçici bir sharing-violation uyarısı üretiyordu | Üçü de kalıcı metne eklendi (**+72/−0**, komut/port/yol değişikliği **yok**) |

R1 ve R-A birer **runbook defect**'iydi; final tur ise gözlenmiş üç operasyonel
tuzağın metne yazılmasıdır. Yeni §F.2 kontrolünün **boş bir iddia olmadığı**,
sentetik fixture'lara karşı sekiz senaryoyla kanıtlandı: geçerli dosya ve
**doğru kaçırılmış** `\:` PASS; kenar boşluğu, kaçırılmamış `:`, kaçırılmamış
`\`, joker, BOM ve eksik satır FAIL.

---

## E. Kalıcı cluster sözleşmesi

Kurulan küme, repo dışındaki `«DATA_DIR»` üzerinde, **`«PORT»`** üzerinde ve
**yalnız loopback** dinleyerek çalışır. Windows servisi olarak **kaydedilmedi**.

| Sözleşme | Ölçülen durum |
|---|---|
| `initdb` | açık `--encoding=UTF8` + `--no-locale`; bootstrap superuser parolası **interaktif** soruldu, diske bootstrap parola dosyası yazılmadı |
| `listen_addresses` / `port` / `password_encryption` | üçü de **açıkça pinlendi**; dinleyen soket tek ve loopback |
| `pg_hba.conf` | **yalnız iki aktif kural**, ikisi de loopback + `scram-sha-256`; dosyada literal `trust` **0 kez** |
| Blanket-trust | `pg_hba_file_rules` üzerinden **0** |
| Encoding / collation | `UTF8` / `C` |
| Üç rol | `LOGIN`; `rolsuper`/`rolcreatedb`/`rolcreaterole`/`rolreplication`/`rolbypassrls` **beşi de `f`** |
| Parola biçimi | üç rolde de SCRAM-SHA-256 (boolean sorgu; hash **yazdırılmadı**) |
| Sahiplik | `«PILOT_DB»` ve `iam` + `mutation` şemaları **`vergi_owner`** |
| Migration | 0001–0005 açık `ON_ERROR_STOP=1` ile, 0006 kendi guard'ıyla; **altısı da `COMMIT`** |

Credential sözleşmesi: parola **yalnız** libpq'nun `passfile` **bağlantı
parametresiyle** taşındı; `PGPASSWORD` ve `PGPASSFILE` **hiç kullanılmadı**;
hiçbir DSN'de parola bölümü yok. `«SECURE_DIR»` ve `«PASSFILE»`, inherited ACE
bırakmayacak biçimde yalnız geçerli kullanıcıya daraltıldı. Passfile
**exact-tuple**'dır, joker içermez ve implementasyon sırasında **hiç
okunmamıştır**; biçim doğruluğunun kanıtı yalnız ACL çıktısı ve **başarılı
parolasız bağlantılardır**.

**Gözlenmiş olay (kayda geçirilmiştir).** Kümeyi başlatan konsol penceresi
kapandığında `postmaster` `STATUS_CONTROL_C_EXIT` ile düştü; log
`background worker ... terminated by exception` ve ardından
`terminating any other active server processes` yazdı. Küme **mevcut
`«DATA_DIR»` ile** yeniden başlatıldı, crash recovery temiz tamamlandı
(`automatic recovery in progress` → `redo done` → `ready to accept
connections`) ve roller, veritabanı ve parolalar sağ çıktı. Veri kaybı
**olmadı**; `initdb` **tekrar çalıştırılmadı**. Bu davranış artık runbook
§D'de yazılıdır.

---

## F. IAM adoption ve kimlik sınırları

Yerel issuer konvansiyonu üzerinden **ilk admin** ve **avukat kullanıcısı**
oluşturuldu. Her ikisinin `subject` değeri operatör tarafından **gerçek bir
konsolda**, echo'suz biçimde girildi; bu değerler implementasyona **hiç
gösterilmedi** ve hiçbir yere yazılmadı. `iam.external_identities.subject`
alanı **hiçbir sorguda seçilmedi**.

| Ölçüm | Sonuç |
|---|---|
| `iam.bootstrap_state` / `iam.users` / `iam.external_identities` / `iam.user_roles` / `iam.security_events` | bootstrap sonrası **beşi de 1 satır** |
| `provision-user` sonrası | `iam.users` 2, `iam.external_identities` 2, `iam.user_roles` **hâlâ 1** |
| Security event türleri | `bootstrap_first_admin`, `user_provisioned` |
| Her iki kullanıcı | `disabled = f` |

**`grant-role` bilinçli olarak atlandı.** `admin` rolü **tek başına sıfır
case-içerik yeteneği** taşır; avukatın ihtiyacı olan şey `lawyer` **case
assignment**'ıdır. Bu yüzden avukat kullanıcısına global rol **verilmedi** ve
`iam.user_roles` tek satırda kaldı.

`bootstrap-first-admin` ikinci kez başarılı olamaz; tekillik veritabanı
tarafından zorlanır. `scripts/iam_bootstrap_probe.py` bu adımda
**kullanılmadı** — sekiz `VERGI_ENTRA_*` değişkenini ve gerçek bir Entra
tenant'ını zorunlu kılar, bu da Adım 11'e aittir.

**Kimlik yeniden bağlama komutu yoktur.** Aynı kişi Adım 11'de bir Entra
kimliği aldığında **ikinci bir `iam.users` satırına** düşer; mevcut yerel
kimliğe Entra kimliği **ekleyen** bir `link-identity` komutu yoktur ve bu, elle
`INSERT` ile kapatılacak bir boşluk değildir.

---

## G. Sentetik smoke ve mutation journal kanıtı

Smoke **yalnız** sentetik `case_adim8_smoke` dizini üzerinde koşuldu. Tracked
fixture `data/cases/case_0001` **yalnız kaynak olarak okundu**: üzerinde
assignment verilmedi, preview/apply koşulmadı, hiçbir mutasyon yapılmadı.

Zincir ve kanıtları:

| Adım | Kanıt |
|---|---|
| Fixture | 71 dosya kopyalandı; evidence pending yeniden adlandırıldı; **yalnız altı hedefte** `case_id` yeniden yazıldı; fail-closed doğrulama **PASS** |
| `case_id` ölçümü | kopyada altı dosya yeni `case_id`'yi taşıyor; üç `document.json` kaynakla **bayt-özdeş** ve bilinçli olarak eski değeri taşımaya devam ediyor |
| Assignment | avukat kullanıcısına `lawyer` rolüyle, aktör **ilk admin**; **tam 1 aktif** assignment |
| Registry | on row-key listelendi; seçilen exact kayıt **`evidence`** (o dizinde canonical dosya ve `reviews/` yoktu) |
| Baseline | journal boş, kaynak satırı yok, pending sha256 kaydedildi |
| Preview | `validation_valid=True`, pending hash preview'ın bastığı değerle aynı, exit **0** |
| Apply | **tek** apply, retry yok, exit **0**; canonical dosya + **tek** approval kaydı üretildi |
| Journal deltası | **tam 1 yeni satır**, `state=completed`, aktör **avukat kullanıcısı**, doğru `resource_key`/`action_family`, `resolved_at` dolu, `observed_post_hash` = canonical hash |
| Dosya etkisi | kaynakla karşılaştırmada **65 özdeş, 6 farklı (tam olarak yeniden yazılanlar), 2 fazla (tam olarak apply çıktıları)** — seçilmeyen dokuz row'un hiçbir dosyası değişmedi |
| Revoke | exit 0; satır **korundu**, `revoked_at` doldu, aktif assignment **0**, `case_assignment_revoked` **tam 1** |

Apply'ın aktörü **avukat kullanıcısıdır**; **ilk admin** yalnız `assign-case`
ve `revoke-assignment`'ın aktörüdür. İkisi ayrı oturumlarda, her çağrıda tek
DSN ile kullanıldı.

**Dört kalıcı audit izi kasıtlıdır ve temizlenmedi:** soft-revoked assignment
satırı, iki assignment security event'i, `completed` journal satırı ve case
kaynak satırı. Veritabanında **hiçbir `DELETE` çalıştırılmadı**.

Runbook §P, yeniden adlandırılmış sentetik kopya üzerinde uçtan uca
validation'ın geçeceğinin **kanıtlanmadığını** açıkça söylüyordu. Bu bilinmeyen
bu turda **ampirik olarak kapandı**: `validation_valid=True` ve apply exit 0.

---

## H. Dump/restore kanıtı ve dürüst sınırlar

Komut sözleşmesi, koşulmadan **önce** 14 maddelik mekanik kontrolden geçti
(19 ayrı kontrol, hepsi PASS): `--format=custom` ×1, `--no-privileges` ×1,
`pg_dump`'ta `--no-owner` **×0**, `pg_restore`'da `--no-owner`/
`--single-transaction`/`--exit-on-error` ×1, her iki satırda `--no-password` ×1
ve `passfile=` ×1, URI'de parola bölümü **yok**, çelişen `--host`/`--port`/
`--username` **×0**, `PGPASSWORD`/`PGPASSFILE` **×0**, arşiv **açık positional
girdi**, restore hedefi `«VERIFY_DB»`.

`«BACKUP_DIR»` repo dışındadır; ACL'i yalnız geçerli kullanıcıya daraltıldı ve
`Everyone` / `BUILTIN\Users` / `Authenticated Users` **hiçbiri** bulunmadı.
Dump exit 0, tek dosya, 45173 bayt; SHA-256 kaydedildi (bu belgeye
**yazılmamıştır**) ve restore sonrası **değişmediği** doğrulandı — arşiv
salt-okunur tüketildi. `pg_restore --list` exit 0, 114 TOC girdisi, `CUSTOM`
format.

Restore **yalnız boş `«VERIFY_DB»`'ya** yapıldı, exit 0. Canlı veritabanı
üzerine restore **YOKTUR**.

| Karşılaştırma | Sonuç |
|---|---|
| Nesne sayıları (`iam` + `mutation`, tablo + sequence) | **fark 0** |
| 12 tablonun satır sayıları | **fark 0** |
| İçerik (kullanıcı, kimlik satırı sayısı, rol, soft-revoked assignment, event türleri, bootstrap, `completed` journal satırı post-hash dahil, kaynak satırları) | **fark 0** |
| Kaynak veritabanı restore öncesi/sonrası | **aynı** |

**Dürüst sınırlar (ölçülmüş, iddia edilmemiş):**

1. Bu restore **`0006` privilege parity kanıtı DEĞİLDİR.** `--no-privileges`
   yüzünden doğrudan yetkiler restore edilmez; bu somut olarak ölçüldü —
   `vergi_app` **11 → 0**, `vergi_iam_admin` **32 → 0**.
2. `PUBLIC` sayısının iki tarafta da 0 olması **parite değildir**: canlıda bu
   `0006`'nın açık `REVOKE`'unun sonucu, restore edilen kopyada ise hiç grant
   gelmemiş olmasının sonucudur. Aynı sayı, farklı sebep.
3. **`--no-owner`** yüzünden sahiplik arşivden değil **restore eden rolden**
   gelir; iki tarafta eşleşmesi **prosedürün** sonucudur, arşivin taşıdığı bir
   kanıt değildir.
4. Custom-format dump **database düzeyi ACL'leri** hiç taşımaz;
   database-level ACL paritesi **iddia edilmez**.
5. Dump **kişisel ve hukuki veri içerir** (kimlik çiftleri, görünen adlar,
   session token hash'leri). Repo dışında, ACL-korumalı tutulur; içeriği hiçbir
   rapora kopyalanmaz.
6. Bu **gerçek bir yedekleme sözleşmesi DEĞİLDİR**; manuel bir güvenlik
   ağıdır. Zamanlama, saklama, şifreleme, taşıma ve rotasyon **tanımsızdır**
   ve Row 19D'de açıktır.

`«VERIFY_DB»` turun sonunda düşürüldü ve passfile'daki ilgili satır silindi;
silinmenin kanıtı, o dörtlüyle kurulan bağlantının artık **parola
bulunamadığı** için reddedilmesidir.

---

## I. Resmî production-parity ve RAG kapıları

Kapılar **commit'li baytlarla**, temiz ve detached bir exact-commit
worktree'sinde (`core.autocrlf=false`, `core.eol=lf`, başlangıç status boş),
**tek sweep** hâlinde ve eşzamanlı olmadan koşuldu. Hiçbir kapı **kalıcı pilot
veritabanına karşı koşulmadı**; `VERGI_IAM_DATABASE_URL` gate ortamında
**UNSET**'ti.

Disposable gate kümesi ayrı bir boş portta kuruldu ve şu sözleşmeyi taşıdı:
**tam bir** `trust` kuralı, exact bootstrap superuser ve exact loopback
adresine bağlı; diğer tüm roller `scram-sha-256`; **blanket trust 0**;
`log_statement='none'`; disposable veritabanının sahibi `vergi_owner`; üç
canonical rol minimum niteliklerle oluşturuldu; 0001–0006 **`vergi_owner` ile,
sırayla ve `ON_ERROR_STOP=1` altında** uygulandı, altısı da `COMMIT`. Rol
parolaları tek bir Python süreci içinde üretildi ve **hiçbir komut satırına,
ortam değişkenine veya log'a düşmedi**. Gate başlatılmadan önce sözleşme
probe'u **11/11 true** verdi.

**Gate A — `production-parity`** (hedef interpreter: `vergi_ui_runtime`):

| Alan | Değer |
|---|---|
| exit / state / sweep_label | **0** / `completed` / **FULL** |
| Modüller | **84/84 PASS**, `modules_non_pass=0`, `modules_not_spawned=0` |
| Kontroller | **6864 passed**, **0 failed**, counted_skips **8**, informational_skips **14** |
| `refusals` / `warnings` | `[]` / `[]` |
| Discovery | `git_and_fs`, tracked = run = **84**, `missing`/`untracked`/`rejected` `[]` |
| PostgreSQL | `connected` / `migrations_ok` / `server_addr_loopback` **True**, `contract_probe=ok`, `migrations_missing=[]` |
| `*_postgres` modülleri | **16/16 gerçekten koştu**, hepsi PASS, hepsi `passed > 0` |
| Guard | armed **221 = expected 221**, positive controls **10/10**, `inheritance_ok=True`, `malformed_lines=0`, `suspicious_popens=[]`, shim SHA = source SHA |
| Integrity | `failures=[]`, `protected_manifest_ok=True` (**393** girdi), `protected_path_diff=[]`, secret scan **168** dosya `hits=[]`, process/temp/db/bytecode residue **hepsi `[]`** |
| Git | `clean=true`, `head` exact |

**Gate B — `rag-dependency`** (hedef interpreter: root `.venv`; tüm PostgreSQL
env değişkenleri unset; Gate A tamamlandıktan sonra, eşzamanlı değil):

| Alan | Değer |
|---|---|
| exit / state / sweep_label | **0** / `completed` / **RAG_GATE_PASS** |
| Modüller | **3/3 PASS**, **216 passed**, **0 failed** |
| RAG gate | `marker_present=True`, `informational_skips_effective=0` (ham 1 eksi adıyla muaf tutulan 1 platform-gated skip) |
| `refusals` / `warnings` | `[]` / **tek** disclosed uyarı: K.1 adlı platform muafiyeti |
| Guard / integrity | armed **7 = expected 7**, positive controls **10/10**, integrity temiz, secret scan **6** dosya `hits=[]` |
| Git | `clean=true`, `head` exact |

**İki dürüstlük notu.** (i) Sweep raporu `TALLY_MISMATCH` diye bir alan
**taşımaz**; yerine bağımsız bir çapraz kontrol yapıldı — modül-başı toplamlar
dört sayacın dördünde de `totals` ile eşleşti, `warnings=[]` ve
`integrity.failures=[]`. (ii) `stderr` yazan dokuz modül incelendi: sekizi
bilinen `Starlette`/`Authlib` deprecation uyarısı (Row 19B'nin kayıtlı backlog
maddesi), kalanlar testlerin **kasten** tetiklediği ret mesajları ve
fault-injection'ın kendi `injected:` çıktılarıdır — gerçek hata yok.

**İki disclosed sapma, yalnız disposable kümede:** küme, tool konsoluyla
birlikte ölmemesi için detached biçimde başlatıldı (runbook §D'nin kalıcı küme
için verdiği `pg_ctl start` komutu değil); `initdb` trust bayraklarıyla koştu
ama `pg_hba` **ilk başlatmadan önce** dar tek kurala yeniden yazıldı — küme
blanket-trust ile **hiç çalışmadı**.

Bu turun doküman-only commit'leri için kapılar **yeniden koşulmadı**; yukarıdaki
kanıtlar geçerliliğini korur.

---

## J. Veri/repo bütünlüğü ve cleanup

| Kontrol | Sonuç |
|---|---|
| Slice 8C'nin operasyonel işinde repo dosyası değişikliği | **0** |
| `data/cases` tracked = filesystem | **71 / 71**, her aşamada `MANIFEST_IDENTICAL` |
| `data/cases` ignored/untracked residue | **0** |
| `case_0001` | her aşamada HEAD ile **bayt-özdeş** |
| Sentetik dizin | yaşadığı sürece **tek** `!!` (ignored) girdisi olarak göründü — `??` **hiç** görünmedi, yani Adım 2'nin kök-bağlı koruması çalıştı |
| Sentetik dizinin silinmesi | hedef literal ve exact çözüldü, **reparse point değil** olduğu doğrulandı; silme sonrası ABSENT, 71/71, residue 0, repo temiz |
| Disposable küme | fast-stop exit 0, `no server running`, port boşaldı, disposable postgres süreci **0** |
| Geçici gate passfile ve küme dizini | **exact yollarıyla** silindi |
| Detached worktree | `remove` + `prune`, metadata dizini kalmadı |
| Kalıcı küme | çalışır durumda ve **değişmemiş**; veri dizini, passfile ve backup arşivi yerinde |
| Kalıcı veritabanı içeriği | kapılardan **etkilenmedi** (kullanıcı, assignment, event, journal ve kaynak sayıları aynı kaldı) |

**Ham manifest kuralı uygulandı:** her aşamada plain `git status` yerine ham
`data/cases/**` manifesti **veya** `git status --ignored` kullanıldı.
`git clean -fdx` ve `git stash --all` **hiç kullanılmadı**.

Sayaçlar bu turda `git ls-files` ile **yeniden türetildi**: test modülü **84**,
`*_postgres.py` **16**, migration **6**.

---

## K. Açık sınırlar ve production-ready olmayan alanlar

Bu LOCK **yalnız** Adım 8'i ve **yalnız mevcut yerel CLI pilot** bakımından
kapsar. Aşağıdakiler **kapanmamıştır** ve bu belge bunların kapandığını
**İDDİA ETMEZ**:

1. **Küme bir Windows servisi değildir**; manuel yaşam döngüsündedir. Onu
   başlatan pencere kapanırsa düşer (§E'deki gözlenmiş olay).
2. **Reboot sonrası otomatik başlamaz.** Servis kimliği, servis hesabı ve
   boot-time başlatma sözleşmesi **Row 19D**'dedir.
3. **Web/OIDC login Adım 11'i bekler.** `0006` **hiçbir role**
   `iam.sessions` veya `iam.oidc_login_transactions` üzerinde `INSERT`
   vermez; tarayıcı girişi veritabanı katmanında kapalıdır. Bu bir login
   bypass'ı **değildir** — açılması yeni, ayrı numaralı bir migration ve büyük
   olasılıkla dördüncü bir rol gerektirir. Gerçek Entra tenant/app kaydı,
   `acrs` claim doğrulaması, Conditional Access ön kontrolü ve Key Vault rol
   dağıtımı da Adım 11/12'ye aittir.
4. **Backup manuel bir güvenlik ağıdır**, gerçek bir backup/retention/rotation
   sözleşmesi **değildir**.
5. **Restore, privilege veya database-level ACL paritesi kanıtı değildir**
   (§H'deki altı sınır).
6. **`PUBLIC CONNECT` varsayılanı değiştirilmedi.** `0006` yalnız
   `TEMPORARY`'yi `PUBLIC`'ten geri alır.
7. **`ALTER DEFAULT PRIVILEGES` yoktur**; gelecekteki nesnelere blanket yetki
   verilmez, her yeni migration kendi grant'ını açıkça yazar.
8. **Secret/key rotation yoktur**; aralık, prosedür ve kanıt tanımsızdır.
9. **Session advisory-lock timeout açıktır.** `ui/services/mutation_lock.py`
   bloklayan bir advisory lock kullanır ve `lock_timeout`/`statement_timeout`
   tanımlı değildir; tutulan bir case kilidi bir onay isteğini süresiz
   bekletebilir.
10. **İşletim sistemi ACL'leri operatör adımıdır**, mekanik olarak doğrulanan
    bir sözleşme değildir.
11. **Row 19D açık kalır.**
12. **Event-specific hukuki aritmetik kapsam dışıdır** (Adım 7'nin sekiz
    olayı; bkz. o kapanışın kendi checkpoint'i).
13. **Adım 9–13, corpus edinim/populasyonu** kapanmamıştır.
14. **Pilotun production-ready olduğu İDDİA EDİLMEZ.**

---

## L. Sıradaki iş

**Pilot Readiness Adım 9 — ACTIVE / NEXT.** Bu checkpoint Adım 9 için hiçbir
dosya değişikliğini yetkilendirmez; kapsamı ve dosya allowlist'i kendi turunda
ayrıca sunulup onaylanacaktır.
