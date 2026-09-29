# Yerel PostgreSQL / IAM Adoption — Operatör Runbook'u

**Pilot Readiness Adım 8 / Slice 8B.** Bu belge, kalıcı yerel pilot PostgreSQL
kümesinin kurulması, migration 0001–0006'nın uygulanması, üç canonical veritabanı
rolünün ve ilk IAM kullanıcılarının oluşturulması, tek bir sentetik uygulama
smoke'unun koşulması ve tek bir doğrulama amaçlı dump/restore turunun yapılması
için **operatör talimatıdır**.

---

## A. Kapsam, kapsam-dışı ve yazım kuralları

### A.1 Bu belge nedir, ne değildir

Bu belge **talimattır**. Kendisi hiçbir şey çalıştırmaz ve yazıldığı tur içinde
hiçbir küme kurulmamış, hiçbir migration uygulanmamış, hiçbir IAM kullanıcısı
oluşturulmamış, hiçbir smoke koşulmamış ve hiçbir yedek alınmamıştır.

**Kapsam dahilindedir:** kalıcı loopback-only küme kurulumu; üç rolün
oluşturulması ve parolalandırılması; 0001–0006'nın `vergi_owner` ile
uygulanması; privilege sözleşmesinin salt-okunur doğrulanması; ilk admin ve ilk
avukat kullanıcısının oluşturulması; **tek** sentetik case üzerinde **tek**
gerçek preview + **tek** gerçek apply; **tek** doğrulama amaçlı dump/restore.

**Kapsam dışıdır:** Windows servis kaydı ve servis kimliği; işletim sistemi ACL
sözleşmesi; parola/anahtar rotasyonu; gerçek yedekleme/saklama sözleşmesi;
session advisory-lock timeout; web/OIDC login; Entra tenant/app kaydı; RAG
corpus edinimi veya bundle aktivasyonu; `scripts/global_resource_grants.py`
üzerinden global kaynak grant'ları. Bunların hepsi **Row 19D** ve **Pilot
Readiness Adım 11/12**'ye aittir.

### A.2 Placeholder yazım kuralı (bağlayıcı)

Bu belgede her yer tutucu **yalnız** `«...»` biçiminde veya backtick içinde
yazılır. Çıplak HTML-benzeri yer tutucu **hiç kullanılmaz**: GFM prose içinde
köşeli-parantez biçimli bir yer tutucu HTML etiketi olarak ayrıştırılır ve pek
çok görüntüleyicide **sessizce kaybolur**; bu, başlıkların eksik ve satırların
yarım görünmesine yol açar.

Kullanılan yer tutucular:

| Yer tutucu | Anlamı |
|---|---|
| `«PGBIN»` | PostgreSQL 16 `bin` dizini |
| `«DATA_DIR»` | Kalıcı kümenin veri dizini (repo dışında) |
| `«PORT»` | Kalıcı pilot kümesinin dinleme portu |
| `«BOOTSTRAP_SUPERUSER»` | `initdb` ile yaratılan bootstrap superuser adı |
| `«PILOT_DB»` | Kalıcı pilot veritabanı adı |
| `«VERIFY_DB»` | Geçici, boş doğrulama veritabanı adı |
| `«SECURE_DIR»` | Passfile'ın tutulduğu, ACL-korumalı dizin (repo dışında) |
| `«PASSFILE»` | Passfile'ın tam yolu |
| `«PASSFILE_URL»` | Aynı yolun URI query parametresine uygun hâli |
| `«BACKUP_DIR»` | Yedek dizini (repo dışında, ACL-korumalı) |
| `«STAMP»` | Yedek dosyası için zaman damgası |
| `«ADMIN_ID»` | İlk admin kullanıcısının `iam.users.id` değeri |
| `«LAWYER_ID»` | Avukat kullanıcısının `iam.users.id` değeri |
| `«LOCAL_SUBJECT»` | Yerel kimlik konvansiyonunun `subject` değeri |
| `«BASELINE_MAX_ID»` | Smoke öncesi journal baseline değeri |

### A.3 Gizlilik kuralı (bağlayıcı)

Bu belge hiçbir gerçek parola, gerçek DSN, gerçek port, gerçek `subject` veya
gerçek kullanıcı verisi içermez ve operatör de bu değerleri hiçbir rapora,
hiçbir commit'e ve bu belgeye **yazmaz**.

`PGPASSWORD` ve `PGPASSFILE` ortam değişkenleri bu projede **yasaktır** ve bu
runbook onları **hiçbir yerde önermez**. Parola her zaman libpq'nun `passfile`
**bağlantı parametresi** ile taşınır (bkz. §F, §G).

### A.4 Kabuk

Bütün komutlar **Windows PowerShell** içindir. `cmd.exe` satır devamı ve Bash
satır devamı **kullanılmaz**. Güvenlik-kritik komutlar tek satır yazılmıştır.
`psql` oturumu içinde geçen `\password` bir **psql meta-komutudur** ve bir kabuk
devam karakteri değildir.

---

## B. Ön koşullar

### B.1 Yollar ve sürüm

PostgreSQL 16 kurulu olmalıdır ve `«PGBIN»` altında `initdb.exe`, `pg_ctl.exe`,
`psql.exe`, `pg_dump.exe`, `pg_restore.exe`, `pg_isready.exe` bulunmalıdır.

```powershell
& "«PGBIN»\pg_ctl.exe" --version
```

### B.2 Python yorumlayıcısı

IAM ve mutation CLI'ları `psycopg` gerektirir. Bu runbook'un tüm Python
komutları **`vergi_ui_runtime`** sanal ortamının yorumlayıcısıyla ve **repo
kökünden** çalıştırılır.

```powershell
Set-Location C:\Users\Burki\vergi_ai_asistani
$env:PYTHONIOENCODING = "utf-8"
```

### B.3 Çağırma biçimi (bağlayıcı)

`scripts/` bir Python paketi değildir (`scripts/__init__.py` yoktur) ve
`scripts/iam_admin.py` modül düzeyinde `from ui.services import ...` yapar
(`scripts/iam_admin.py:39`). Bu nedenle betiği doğrudan dosya yolu ile
çalıştırmak `ModuleNotFoundError: No module named 'ui'` ile başarısız olur.

**Doğru biçim yalnız `-m`'dir:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m scripts.iam_admin --help
```

Aynı kural `ui.cli_mutate` için de geçerlidir: `python -m ui.cli_mutate ...`.

---

## C. Kalıcı kümenin kurulması

### C.1 `initdb`

Küme, **açıkça UTF8** kodlamayla ve **her iki authentication yolunda
`scram-sha-256`** ile kurulur. Bootstrap superuser parolası **interaktif olarak**
sorulur; diskte geçici bir bootstrap parola dosyası **oluşturulmaz** (bu yüzden
`--pwfile` kullanılmaz).

```powershell
& "«PGBIN»\initdb.exe" --pgdata="«DATA_DIR»" --username="«BOOTSTRAP_SUPERUSER»" --pwprompt --encoding=UTF8 --no-locale --auth-host=scram-sha-256 --auth-local=scram-sha-256
```

**Neden `--encoding=UTF8` açıkça pinlenir:** `--no-locale` tek başına yeterli
değildir. Varsayılan libc collation provider'ı ile küme kodlaması `SQL_ASCII`'ye
düşebilir; `SQL_ASCII` bir kodlama doğrulaması yapmaz ve Türkçe metin taşıyan
canonical artefaktlar için kabul edilemez.

**Neden `--no-locale` zorunludur:** Türkçe Windows locale adı ASCII-dışı karakter
taşır ve `initdb` bu durumda locale adını reddederek durur.

### C.2 `postgresql.conf` — loopback ve parola şifrelemesi

`«DATA_DIR»\postgresql.conf` içinde aşağıdaki iki değer **açıkça** pinlenir:

```ini
listen_addresses = '127.0.0.1'
port = «PORT»
password_encryption = 'scram-sha-256'
```

### C.3 `pg_hba.conf` — yalnız loopback, yalnız SCRAM

`«DATA_DIR»\pg_hba.conf` içinde **yalnız** loopback ve **yalnız** `scram-sha-256`
satırları bırakılır:

```text
host    all    all    127.0.0.1/32    scram-sha-256
host    all    all    ::1/128         scram-sha-256
```

### C.4 Trust yasağı (bağlayıcı)

**Kalıcı pilot kümesinde superuser dahil hiçbir rol için `trust` yoktur.**

`trust` yalnız ve yalnız **atılabilir (disposable) test kümesinde** kullanılabilir
ve orada da yalnız exact bootstrap superuser ile exact loopback adresini eşleyen
tek satır biçiminde. Her türlü blanket-trust kuralı **yasaktır** ve
`ui/tests/test_iam_runtime_privileges_postgres.py`'nin P1 kontrolü tarafından
reddedilir (sözleşme metni: `scripts/run_ui_tests.py:1745-1752`).

Kurulumdan sonra bu kümede blanket-trust bulunmadığı doğrulanır:

```sql
SELECT count(*) AS blanket_trust_rules
FROM pg_hba_file_rules
WHERE auth_method = 'trust';
```

Beklenen sonuç: `0`.

---

## D. Kümenin başlatılması ve durdurulması

Bu runbook kümeyi **operatörün kendi PowerShell oturumundan** başlatır ve
durdurur. Windows servis kaydı (`pg_ctl register`) **bilinçli olarak
kullanılmaz**: servis kimliği, servis hesabı ve boot-time başlatma sözleşmesi
**Row 19D**'ye açıktır ve `pg_ctl register`'ın parola argümanı bir komut satırına
parola yazmayı gerektirir — bu §A.3 ile çelişir.

```powershell
& "«PGBIN»\pg_ctl.exe" --pgdata="«DATA_DIR»" --log="«DATA_DIR»\server.log" start
```

```powershell
& "«PGBIN»\pg_ctl.exe" --pgdata="«DATA_DIR»" status
```

```powershell
& "«PGBIN»\pg_isready.exe" --host=127.0.0.1 --port=«PORT»
```

`postgresql.conf` değişikliğinden sonra yeniden yükleme:

```powershell
& "«PGBIN»\pg_ctl.exe" --pgdata="«DATA_DIR»" reload
```

Durdurma:

```powershell
& "«PGBIN»\pg_ctl.exe" --pgdata="«DATA_DIR»" --mode=fast stop
```

---

## E. Superuser'ın exact minimal görevleri ve parola sözleşmesi

### E.1 Superuser yalnız şunları yapar

1. Üç LOGIN rolünü oluşturur (roller `NOCREATEROLE` olduğu için kendileri rol
   yaratamaz).
2. `«PILOT_DB»` veritabanını `vergi_owner` sahipliğiyle yaratır (roller
   `NOCREATEDB` olduğu için kendileri veritabanı yaratamaz).
3. Daha sonra `«VERIFY_DB»`'yi yaratır ve düşürür (§L).
4. `pg_authid` üzerinden boolean parola-biçimi doğrulaması yapar (§E.4).

**Başka hiçbir şey yapmaz.** Uygulama, CLI ve migration **asla** superuser ile
çalıştırılmaz.

Superuser bağlantıları **interaktif** kurulur; superuser için **kalıcı passfile
veya kalıcı DSN oluşturulmaz**:

```powershell
& "«PGBIN»\psql.exe" --dbname="postgresql://«BOOTSTRAP_SUPERUSER»@127.0.0.1:«PORT»/postgres" --password
```

### E.2 `password_encryption` doğrulaması

Rolleri oluşturmadan **önce**, §C.2'deki değerin gerçekten etkin olduğu
doğrulanır. `password_encryption` çalışma zamanında ayarlanabilir bir
parametredir, bu yüzden §D'deki `reload` yeterlidir:

```sql
SHOW password_encryption;
```

Beklenen sonuç: `scram-sha-256`. Başka bir değer görülürse **DUR**.

### E.3 Rollerin parola literal'i olmadan oluşturulması

Üç rol **parola verilmeden** oluşturulur; parola ayrı bir interaktif adımda
atanır. Attribute kümesi 0006'nın precondition'ı tarafından zorunludur
(`db/migrations/0006_iam_runtime_privileges.sql:116-128`); aynı attribute kümesi
`ui/tests/test_iam_runtime_privileges_postgres.py:319-322`'de kanıtlanmıştır.

```sql
CREATE ROLE vergi_owner     LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE vergi_app       LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE vergi_iam_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
```

Ardından veritabanı, sahibi `vergi_owner` olacak şekilde yaratılır:

```sql
CREATE DATABASE "«PILOT_DB»" OWNER vergi_owner;
```

Bu sahiplik 0006'nın precondition'larından biridir
(`0006:131-140`); şema sahipliği de öyledir (`0006:143-155`), bu yüzden §H'deki
**bütün** migration'lar `vergi_owner` ile uygulanır.

### E.4 Parolaların atanması

Parola, **gerçek interaktif `psql` oturumunda** psql meta-komutu ile atanır:

```psql
\password vergi_owner
\password vergi_app
\password vergi_iam_admin
```

Bu meta-komutun bu runbook'ta dayandığı tek iddia, PostgreSQL'in kendi
belgelenmiş davranışıdır: açık parolanın **komut geçmişinde veya server
log'unda görünmesini önler**. Bunun ötesinde bir iç mekanizma iddiası
yapılmaz.

Parola **komut satırına, ortam değişkenine, kabuk geçmişine, bu runbook'a veya
herhangi bir rapora yazılmaz**.

### E.5 Parola biçiminin boolean doğrulanması

Superuser, **gerçek hash'i yazdırmadan**, yalnız boolean bir sorgu ile üç rolün
parolasının SCRAM-SHA-256 biçiminde olduğunu doğrular. `pg_authid` yalnız
superuser tarafından okunabilir ve aşağıdaki sorgu hash değerini **döndürmez**:

```sql
SELECT rolname, rolpassword LIKE 'SCRAM-SHA-256$%' AS is_scram
FROM pg_authid
WHERE rolname IN ('vergi_owner', 'vergi_app', 'vergi_iam_admin')
ORDER BY rolname;
```

Beklenen: üç satır, hepsinde `is_scram = t`. Aksi hâlde **DUR**.

---

## F. Passfile

### F.1 Dizin ve dosya

Passfile **repo dışında**, `«SECURE_DIR»` altında tutulur ve ACL'i yalnız
geçerli kullanıcıya daraltılır. Kanıtlı desen
`ui/tests/test_iam_runtime_privileges_postgres.py:328-330`:

```powershell
& icacls.exe "«SECURE_DIR»" /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F"
```

```powershell
& icacls.exe "«PASSFILE»" /inheritance:r /grant:r "$($env:USERNAME):F"
```

ACL beklentisi: yalnız geçerli kullanıcı, **inherited ACE yok**
(`scripts/run_ui_tests.py:1105`).

### F.2 Exact-tuple satır biçimi (bağlayıcı)

Passfile satırları **exact-tuple**'dır; **joker (wildcard) kullanılmaz**. Her
`(veritabanı, rol)` çifti için ayrı bir satır yazılır. Biçim
`ui/tests/test_iam_runtime_privileges_postgres.py:335-337`'den alınmıştır:

```text
127.0.0.1:«PORT»:«PILOT_DB»:vergi_owner:«…»
127.0.0.1:«PORT»:«PILOT_DB»:vergi_app:«…»
127.0.0.1:«PORT»:«PILOT_DB»:vergi_iam_admin:«…»
127.0.0.1:«PORT»:«VERIFY_DB»:vergi_owner:«…»
```

Son alan gerçek paroladır ve bu belgeye **yazılmaz**; yukarıdaki `«…»` yalnız
alanın yerini gösterir.

Bootstrap superuser için passfile satırı **yazılmaz** (§E.1).

### F.3 URI için yol biçimi

`«PASSFILE_URL»`, `«PASSFILE»` yolunun URI query parametresine uygun hâlidir:
ters bölü işaretleri **ileri bölü** ile değiştirilir ve URL-güvenli olmayan
karakterler yüzde-kodlanır. Commit'li referans uygulamada dönüştürme
`ui/tests/test_iam_runtime_privileges_postgres.py:162-165`'tedir: yol ileri
bölüye çevrilir ve `/` ile `:` güvenli sayılarak yüzde-kodlama uygulanır.

---

## G. Parolasız DSN ve kabuk ayrımı

### G.1 Tek DSN değişkeni gerçeği (bağlayıcı)

Bu projede **tek bir** veritabanı DSN ortam değişkeni vardır:
`VERGI_IAM_DATABASE_URL` (`ui/services/db.py:32`). Değişken tanımlı değilse
bağlantı fail-closed reddedilir (`ui/services/db.py:34-36`). Hem
`ui/cli_mutate.py`'nin authz bağlantısı (`ui/cli_mutate.py:1116`) hem mutation
tarafı hem de `scripts/iam_admin.py` (`scripts/iam_admin.py:219-223`) **aynı**
değişkeni okur.

**Sonuç:** rol seçimi DSN'in kullanıcı kısmıyla yapılır ve **her rol için ayrı
bir PowerShell oturumu** kullanılır. İki rolün DSN'i **asla aynı oturumda**
bulunmaz.

### G.2 Üç oturum

**OWNER oturumu** — yalnız migration ve dump/restore:

```powershell
$env:VERGI_IAM_DATABASE_URL = "postgresql://vergi_owner@127.0.0.1:«PORT»/«PILOT_DB»?passfile=«PASSFILE_URL»"
```

**ADMIN oturumu** — yalnız `scripts.iam_admin`:

```powershell
$env:VERGI_IAM_DATABASE_URL = "postgresql://vergi_iam_admin@127.0.0.1:«PORT»/«PILOT_DB»?passfile=«PASSFILE_URL»"
```

**APP oturumu** — yalnız `ui.cli_mutate`:

```powershell
$env:VERGI_IAM_DATABASE_URL = "postgresql://vergi_app@127.0.0.1:«PORT»/«PILOT_DB»?passfile=«PASSFILE_URL»"
```

URI'de **parola yoktur**; parola yalnız `passfile` parametresinin gösterdiği
dosyadan gelir.

### G.3 Gerekmeyen değişkenler

Bu CLI-only pilot için **gerekmez**:

- `VERGI_KEY_PROVIDER_KIND` — `key_custody` yalnız web auth yolları
  (`ui/auth_routes.py:174,196,475,481,491,502`) ve kendi admin betiği
  (`scripts/key_custody_admin.py:15`) tarafından kullanılır; web login yolu
  veritabanı düzeyinde kapalıdır (§N).
- `VERGI_ENTRA_*` — `scripts/iam_bootstrap_probe.py` sekiz Entra değişkenini
  zorunlu kılar (`scripts/iam_bootstrap_probe.py:123-136`), bu yüzden o betik
  yerel pilotta kullanılmaz (§J.1).
- `PGPASSWORD`, `PGPASSFILE` — **yasak** (§A.3).

---

## H. Migration'ların uygulanması

### H.1 Sıra ve uygulayıcı rol (bağlayıcı)

Altı migration **sırayla** ve **hepsi `vergi_owner` ile** uygulanır. Bağımlılık
zinciri kaynaktan doğrudur: `0003` 0001+0002'yi
(`db/migrations/0003_mutation_journal.sql:5-7`), `0004` 0001–0003'ü
(`0004:4-6`), `0005` 0001'i (`0005:3`), `0006` 0001–0005'i (`0006:3`) gerektirir.

`vergi_owner` ile uygulama iki ayrı 0006 precondition'ı yüzünden zorunludur:
şemaların owner rolüne ait olması (`0006:143-155`) ve migration'ın owner rolü
tarafından uygulanması (`0006:158-162`).

### H.2 0001–0005

0001–0005 kendi içlerinde `ON_ERROR_STOP` **tanımlamaz**; bu yüzden operatör onu
**açıkça** verir:

```powershell
& "«PGBIN»\psql.exe" --dbname="postgresql://vergi_owner@127.0.0.1:«PORT»/«PILOT_DB»?passfile=«PASSFILE_URL»" --no-password -v ON_ERROR_STOP=1 -f "db\migrations\0001_iam_schema.sql"
```

Aynı komut, dosya adı değiştirilerek sırayla şu dosyalar için tekrarlanır:
`0002_mutation_resources.sql`, `0003_mutation_journal.sql`,
`0004_mutation_reconciliation_provenance.sql`,
`0005_global_resource_grants.sql`.

### H.3 0006

0006 `ON_ERROR_STOP`'u kendi içinde ayarlar
(`0006:57`) ve tek transaction olarak çalışır (`0006:74`, `0006:362`):

```powershell
& "«PGBIN»\psql.exe" --dbname="postgresql://vergi_owner@127.0.0.1:«PORT»/«PILOT_DB»?passfile=«PASSFILE_URL»" --no-password -f "db\migrations\0006_iam_runtime_privileges.sql"
```

0006 rol adlarını psql değişkeni olarak alır ve verilmezse canonical adlara
düşer (`0006:59-72`); pilot **her zaman varsayılanları kullanır**, yani ek
`-v` argümanı verilmez.

### H.4 0006'nın reddetme koşulları (operatör okuması)

0006 aşağıdakilerden **herhangi biri** tutmazsa **tek bir GRANT bile
uygulamadan** durur ve her şeyi geri alır:

| # | Koşul | Kaynak |
|---|---|---|
| 1 | Rol parametreleri boş olamaz ve sessizce canonical ada düşemez | `0006:96-100` |
| 2 | Üç rol birbirinden farklı olmalı | `0006:102-104` |
| 3 | Üç rol de `pg_roles`'ta var olmalı | `0006:107-113` |
| 4 | Hiçbiri superuser/createdb/createrole/replication/bypassrls olmamalı | `0006:116-128` |
| 5 | Veritabanının sahibi owner rolü olmalı | `0006:131-140` |
| 6 | `iam` ve `mutation` şemaları var ve owner rolüne ait olmalı | `0006:143-155` |
| 7 | Uygulayıcı `current_user` owner rolü olmalı | `0006:158-162` |
| 8 | 12 tablo ve 7 sequence'in hepsi mevcut olmalı | `0006:165-181` |

### H.5 Ad-hoc GRANT/REVOKE yasağı (bağlayıcı)

0006 uygulandıktan sonra privilege durumu **asla** ad-hoc `GRANT`, `REVOKE` veya
`ALTER` ile düzeltilmez. Her değişiklik veya geri alma **yeni, ayrı numaralı ve
ayrıca onaylanmış bir migration** gerektirir (`0006:37-41`). **0001–0006
immutable'dır.** Bir runbook veya operatör SQL oturumu migration geçmişinin
yerine geçemez.

---

## I. Doğrulama sorguları (salt-okunur)

Aşağıdaki sorgular hiçbir şeyi değiştirmez. 1–7 `vergi_owner` oturumunda,
8 superuser oturumunda koşulur (`pg_authid` için, bkz. §E.5 — burada yalnız
attribute'lar okunduğu için 8 de owner ile koşulabilir).

### I.1 Üç rol mevcut ve aşırı yetkili değil

```sql
SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname IN ('vergi_owner', 'vergi_app', 'vergi_iam_admin')
ORDER BY rolname;
```

Beklenen: üç satır; `rolcanlogin = t`; diğer beş sütun **hepsinde `f`**.

### I.2 Veritabanı ve şema sahipliği

```sql
SELECT d.datname, r.rolname AS owner
FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba
WHERE d.datname = current_database();
```

```sql
SELECT n.nspname, r.rolname AS owner
FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner
WHERE n.nspname IN ('iam', 'mutation')
ORDER BY n.nspname;
```

Beklenen: her üçünde de owner `vergi_owner`.

### I.3 `vergi_app`'in exact yetki kümesi

0006'nın postcondition'ı `vergi_app` için **tam 11** doğrudan yetki bekler
(`0006:255-267`). Aynı küme şöyle okunur:

```sql
SELECT n.nspname || '.' || c.relname || ':' || a.privilege_type AS priv
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) AS a
WHERE n.nspname IN ('iam', 'mutation')
  AND c.relkind IN ('r', 'S')
  AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'vergi_app')
ORDER BY (n.nspname || '.' || c.relname || ':' || a.privilege_type) COLLATE "C";
```

Beklenen 11 satır: `iam.case_assignments:SELECT`,
`iam.global_resource_grants:SELECT`, `iam.sessions:SELECT`,
`iam.user_roles:SELECT`, `iam.users:SELECT`,
`mutation.mutation_journal:INSERT`, `mutation.mutation_journal:SELECT`,
`mutation.mutation_journal:UPDATE`, `mutation.mutation_journal_id_seq:USAGE`,
`mutation.mutation_resources:INSERT`, `mutation.mutation_resources:SELECT`.

### I.4 `vergi_iam_admin`'in exact yetki kümesi

Aynı sorgu, rol adı `vergi_iam_admin` ile koşulur. Beklenen **tam 32** satırdır
ve tam liste `0006:293-326`'dadır. Dikkat edilecek üç nokta: tek `DELETE`
yalnız `iam.user_roles` üzerindedir (`0006:217`); `iam.sessions` üzerinde
`INSERT` **yoktur**, yalnız `SELECT, UPDATE` vardır (`0006:218`);
`mutation.mutation_journal` üzerinde **hiçbir yetki yoktur**.

### I.5 PUBLIC'in şema erişimi yok

`PUBLIC` bir pseudo-role'dür ve `has_schema_privilege()`'nin kullanıcı argümanı
olarak **kabul edilmez**; ACL içinde **grantee OID 0**'dır. Kontrol 0006'nın
kendi postcondition'ıyla aynı yoldan yapılır (`0006:337-358`):

```sql
SELECT n.nspname, a.privilege_type
FROM pg_namespace n
CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl, acldefault('n'::"char", n.nspowner))) AS a
WHERE n.nspname IN ('iam', 'mutation')
  AND a.grantee = 0
  AND a.privilege_type IN ('USAGE', 'CREATE');
```

Beklenen: **sıfır satır**.

### I.6 Lock kaynak satırlarının varlığı

Dokuz IAM admin komutu `global:iam` kilidini alır; kilit alma yolu
**yalnız SELECT** yapar ve satır yoksa fail-closed patlar
(`ui/services/mutation_lock.py:62-75`). Satır `0002:23`'te seed edilir.

```sql
SELECT resource_key FROM mutation.mutation_resources ORDER BY resource_key;
```

Beklenen: en az `global:iam`, `global:rag_index`, `global:deadline_rules`,
`global:legal_provisions` (`0002:23`, `0003:32-35`).

### I.7 Negatif kontroller — gerçek bağlantılarla

**APP oturumunda** (`vergi_app`), aşağıdaki iki sorgu **farklı** sonuç
vermelidir:

```sql
SELECT count(*) FROM mutation.mutation_journal;
```

Beklenen: başarılı (yetki `0006:208`).

```sql
INSERT INTO iam.security_events(event_type) VALUES ('logout');
```

Beklenen: **izin hatası ile reddedilir** — `vergi_app`'e `iam.security_events`
üzerinde hiçbir yetki verilmemiştir (`0006:51-53`). Reddedilmezse **DUR**.

**ADMIN oturumunda** (`vergi_iam_admin`):

```sql
SELECT count(*) FROM iam.users;
```

Beklenen: başarılı (`0006:321-323`).

```sql
INSERT INTO mutation.mutation_journal(resource_key, action_family, actor_label, target_ref, idempotency_key, request_fingerprint, state) VALUES ('global:iam', 'x', 'x', 'x', 'x', 'x', 'prepared');
```

Beklenen: **izin hatası ile reddedilir** — admin rolünün
`mutation.mutation_journal` üzerinde hiçbir yetkisi yoktur (`0006:54-55`).
Reddedilmezse **DUR**.

### I.8 Bu doğrulamanın kapsamadığı şey

Bu bölüm privilege **sözleşmesini** doğrular. Kümenin işletim sistemi
düzeyindeki güvenliğini, yedeklemesini veya servis kimliğini **doğrulamaz**
(§O).

---

## J. Kimlik ve ilk IAM kullanıcıları

### J.1 Yerel issuer konvansiyonu

`iam.external_identities.issuer` serbest bir `TEXT` alanıdır ve
`UNIQUE (issuer, subject)` kısıtı taşır
(`db/migrations/0001_iam_schema.sql:33-36`). Kodda sabit bir yerel issuer
değeri **yoktur**.

Bu pilot **operatör konvansiyonu** olarak `urn:vergi:local-cli` issuer'ını
kullanır (aynı değer commit'li privilege testinde de kullanılmıştır:
`ui/tests/test_iam_runtime_privileges_postgres.py:565`). `«LOCAL_SUBJECT»`,
operatörün seçtiği kararlı bir yerel tanımlayıcıdır ve bu belgeye **yazılmaz**.

`scripts/iam_bootstrap_probe.py` bu adımda **kullanılmaz**: sekiz `VERGI_ENTRA_*`
değişkenini zorunlu kılar (`scripts/iam_bootstrap_probe.py:123-136`) ve gerçek
bir Entra tenant'ı gerektirir — bu, Pilot Readiness Adım 11'e aittir.

### J.2 İlk admin

`bootstrap-first-admin` argüman almaz (`scripts/iam_admin.py:308`) ve
`issuer`/`subject`/`display name` değerlerini **interaktif** sorar
(`scripts/iam_admin.py:321-323`); bu nedenle **gerçek bir konsolda** koşulur,
pipe veya dosya yönlendirmesiyle beslenmez. Tekillik veritabanı tarafından
zorlanır (`scripts/iam_admin.py:205`), bu komut ikinci kez başarılı olamaz.
Aktör doğrulaması **yoktur**, çünkü henüz aktör yoktur
(`scripts/iam_admin.py:254-260`).

**ADMIN oturumunda:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m scripts.iam_admin bootstrap-first-admin
```

Komut yalnız `OK` basar (`scripts/iam_admin.py:325`) ve **kullanıcı id'sini
göstermez**.

Bu komut dört tabloya yazar ve bir security event bırakır
(`scripts/iam_admin.py:205-210`); `vergi_iam_admin`'in dördünün de `INSERT`
yetkisi vardır: `iam.bootstrap_state` (`0006:294`), `iam.users` (`0006:321`),
`iam.external_identities` (`0006:301`), `iam.user_roles` (`0006:318`) ve
`iam.security_events` (`0006:311`), ilgili sequence'lerle birlikte. Aynı zincir
gerçek PostgreSQL üzerinde kanıtlanmıştır
(`ui/tests/test_iam_runtime_privileges_postgres.py:578`).

### J.3 Id'lerin SQL ile geri okunması (zorunlu)

`--actor-user-id` / `--user-id` gereken her adımdan **önce** id'ler
veritabanından okunur. `vergi_iam_admin`'in `iam.users` SELECT yetkisi vardır
(`0006:321-323`).

```sql
SELECT u.id, u.display_name, u.disabled
FROM iam.users u
ORDER BY u.id;
```

```sql
SELECT ur.user_id, ur.role FROM iam.user_roles ur ORDER BY ur.user_id;
```

İlk sorgudaki admin satırının `id` değeri `«ADMIN_ID»`'dir.

### J.4 Avukat kullanıcısı

`provision-user` `--display-name` ve `--actor-user-id` alır
(`scripts/iam_admin.py:273-275`), `issuer`/`subject` değerlerini interaktif
sorar (`scripts/iam_admin.py:313-314`) ve **gerçek, aktif bir admin aktörü**
zorunlu kılar (`scripts/iam_admin.py:226-251`).

**ADMIN oturumunda:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m scripts.iam_admin provision-user --display-name "«…»" --actor-user-id «ADMIN_ID»
```

Ardından §J.3 tekrar koşulur; yeni satırın `id` değeri `«LAWYER_ID»`'dir.

### J.5 Admin rolü ve yetenek modeli

`grant-role` yalnız **global admin** rolünü verir; `lawyer`/`analyst` bu tabloda
ifade **edilemez** (`db/migrations/0001_iam_schema.sql:47-52`).

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m scripts.iam_admin grant-role --user-id «LAWYER_ID» --actor-user-id «ADMIN_ID»
```

Yukarıdaki komut yalnız gerçekten ikinci bir **admin** isteniyorsa koşulur.

**Yetenek modeli (bağlayıcı okuma):** `lawyer` rolü `read` ve `mutate`,
`analyst` rolü yalnız `read` taşır (`ui/services/authz.py:48-50`). `admin`
rolü **tek başına sıfır case-içerik yeteneği** taşır
(`ui/services/authz.py:193-200`). Bu yüzden §K'deki smoke için `«LAWYER_ID»`,
**`lawyer` assignment'ını tutan** kullanıcıdır.

---

## K. Sentetik uygulama smoke'u

### K.1 Bağlayıcı sınırlar

- Tracked fixture `data/cases/case_0001` **yalnız kaynak olarak okunur**.
  Üzerinde **assignment verilmez**, **preview koşulmaz**, **apply koşulmaz**,
  hiçbir mutasyon yapılmaz.
- Smoke yalnız sentetik `data/cases/case_adim8_smoke/` üzerinde ve yalnız
  **`lawyer`** rolüyle koşulur.
- Zorunlu SQL privilege kontrolleri (§I.7) bu uygulama smoke'unun **yerine
  geçmez**; ikisi de zorunludur.
- **Apply başarısız olursa DUR.** İkinci bir row-key veya başka bir aksiyon
  denenerek sonuç gizlenmez.

### K.2 Sıra

| # | Adım | Oturum |
|---|---|---|
| 1 | Sentetik fixture oluşturulur (§K.3) | OS |
| 2 | §I.7 privilege kontrolleri koşulur | APP + ADMIN |
| 3 | `assign-case` (§K.4) | ADMIN |
| 4 | Registry/row-key enumerasyonu (§K.5) | APP |
| 5 | Journal baseline alınır (§K.6) | APP |
| 6 | Tek gerçek preview (§K.7) | APP |
| 7 | Tek gerçek apply (§K.7) | APP |
| 8 | Yeni journal satırı doğrulanır (§K.6) | APP |
| 9 | `revoke-assignment` (§K.8) | ADMIN |
| 10 | Sentetik dizin silinir ve residue doğrulanır (§K.9) | OS |

Sıra bağlayıcıdır: `assign-case` dosya sistemine bakmayan düz bir `INSERT`'tir
(`scripts/iam_admin.py:156-164`), ama preview dizinin **var olmasını** ve
`case.json` taşımasını gerektirir (`ui/services/paths.py:49-68`, `:169`).

### K.3 Sentetik fixture'ın hazırlanması

Kopyalama:

```powershell
Copy-Item -LiteralPath "data\cases\case_0001" -Destination "data\cases\case_adim8_smoke" -Recurse
```

Dosya adı değişikliği — pending yolu `evidence_«case_id»_v1.json.pending`
olarak hesaplanır (`src/evidence_approval.py:141-148`):

```powershell
Rename-Item -LiteralPath "data\cases\case_adim8_smoke\evidence\evidence_case_0001_v1.json.pending" -NewName "evidence_case_adim8_smoke_v1.json.pending"
```

**KURAL — dört dosya grubunda üst düzey `case_id` yeniden yazılır.** Her hedef
dosyada `"case_id": "case_0001"` dizgisi **tam bir kez** bulunur:

```powershell
$targets = @("data\cases\case_adim8_smoke\case.json", "data\cases\case_adim8_smoke\issues\issues.json", "data\cases\case_adim8_smoke\evidence\evidence_case_adim8_smoke_v1.json.pending")
$targets += (Get-ChildItem -LiteralPath "data\cases\case_adim8_smoke\documents" -Recurse -Filter "facts.json" | Where-Object { $_.FullName -like "*\extractions\facts.json" } | ForEach-Object { $_.FullName })
foreach ($t in $targets) { $raw = [System.IO.File]::ReadAllText($t); $new = $raw.Replace('"case_id": "case_0001"', '"case_id": "case_adim8_smoke"'); [System.IO.File]::WriteAllText($t, $new, (New-Object System.Text.UTF8Encoding($false))) }
```

**İSTİSNA — `documents\*\document.json` dosyalarına DOKUNULMAZ.** Bunlar
bayt-bayt aynı kalır ve içlerinde `case_0001` demeye devam eder.

Doğrulama:

```powershell
Get-ChildItem -LiteralPath "data\cases\case_adim8_smoke" -Recurse -File | Select-String -SimpleMatch '"case_id": "case_0001"' | Select-Object Path
```

Beklenen: **yalnız** `documents\*\document.json` dosyaları listelenir; başka
hiçbir dosya listelenmez.

#### K.3.1 Neden bu kural, neden bu istisna

**Yeniden yazma zorunludur** — dört yükleyici `case_id` eşitliğini fail-closed
arar:

| Dosya | Kontrol |
|---|---|
| `case.json` | `src/evidence_validator.py:229-256` |
| evidence pending | `src/evidence_validator.py:1103-1116` (çağrı `src/evidence_approval.py:356-370`) |
| `issues/issues.json` | `src/legal_research_validator.py:308-332` |
| `documents/*/extractions/facts.json` | `src/timeline_validator.py:425-440` |

**Yeniden yazma hash-güvenlidir** — validator `analysis_metadata`'daki üç
hash'i yeniden hesaplar (`src/evidence_validator.py:421-443`).
`issues_input_hash` **issue index** üzerindedir
(`src/legal_research_validator.py:333-355`) ve issue kayıtlarında `case_id`
alanı yoktur. `facts_input_hash` `{fact_id: record["fact"]}` üzerindedir ve
fact kayıtlarında `case_id` alanı yoktur.

**İstisna zorunludur** — `documents_input_hash`, `document.json`'un **tüm
sözlüğü** üzerinden hesaplanır (`src/evidence_policy.py:305-343` →
`index[document_id] = data`; hash `src/evidence_validator.py:437-441`) ve
`load_case_documents()` **hiçbir `case_id` kontrolü yapmaz**
(`src/case_document_validator.py:118-149`). Bu dosyalar yeniden yazılırsa hash
uyuşmazlığı oluşur ve apply reddedilir.

`evidence_analysis_id` alanı hiçbir yerde `case_id`'ye karşı doğrulanmaz
(`data/case_evidence.schema.json` yalnız boş olmayan bir dizgi ister); yeniden
yazılması **isteğe bağlıdır**, zorunlu değildir.

`case_adim8_smoke` adı paylaşılan choke point'ten geçer: yasak alt dizgiler
(`src/path_containment.py:88`) arasından hiçbirini içermez ve dizin `case.json`
taşıdığı için keşfedilir (`ui/services/paths.py:49-68`, `:169`).

**Dürüst sınır:** yeniden adlandırılmış kopya üzerinde uçtan uca validation'ın
geçeceği bu runbook tarafından **kanıtlanmamıştır**; §K.1'in STOP kuralı bu
riski kapsar.

### K.4 Assignment

**ADMIN oturumunda:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m scripts.iam_admin assign-case --user-id «LAWYER_ID» --case-id case_adim8_smoke --role lawyer --actor-user-id «ADMIN_ID»
```

Dikkat: buradaki `--actor-user-id` **admin** kullanıcısıdır; §K.7'deki
`--actor-user-id` ise **avukat** kullanıcısıdır. İkisi farklı id'lerdir ve
farklı oturumlarda kullanılırlar.

### K.5 Case-scoped registry / row-key enumerasyonu

Bu adım **salt-okunurdur**: hiçbir veritabanı bağlantısı, hiçbir authz kontrolü
ve hiçbir dosya mutasyonu yoktur. `--row-key` seçenekleri doğrudan
`ui/services/approval_registry.py`'nin kayıt defterinden üretilir
(`ui/cli_mutate.py:192-195`).

**APP oturumunda:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m ui.cli_mutate approval --help
```

Bu bir "action list komutu" **değildir**; `approval` alt komutunda `--action`
diye bir bayrak **yoktur**. Bu adım yalnız kayıt defteri enumerasyonudur.

**Kullanılacak row-key `evidence`'tır ve uydurulmamıştır.** Commit'li
fixture'da `evidence/` dizini yalnız pending dosyasını içerir: canonical
`evidence.json` **yoktur** ve `evidence/reviews/` **yoktur**, bu yüzden
`_mark_already_approved()` bu pending'i "zaten onaylanmış" saymaz
(`ui/services/approval_registry.py:158-182`). Diğer dokuz row'un hepsinde
canonical dosya ve `reviews/*.approval.json` kaydı vardır. Row tanımı:
`ui/services/approval_registry.py:193`.

### K.6 Journal kontrolü — rerun-güvenli

Tabloda bu kaynak ve aksiyon ailesi için **eski veya başarısız koşu kayıtları
bulunabilir**. Bu yüzden "tabloda toplam tam bir satır olmalı" **denmez**;
apply'dan önce bir baseline alınır ve sonra **yalnız baseline'dan sonra oluşan**
satırlar sorgulanır.

**Apply'dan ÖNCE**, APP oturumunda:

```sql
SELECT coalesce(max(id), 0) AS baseline_max_id, count(*) AS baseline_rows
FROM mutation.mutation_journal
WHERE resource_key = 'case:case_adim8_smoke'
  AND action_family = 'approval.evidence';
```

Dönen `baseline_max_id` değeri `«BASELINE_MAX_ID»` olarak not edilir.

**Apply'dan SONRA:**

```sql
SELECT id, state, actor_user_id, actor_label, resource_key, action_family, resolved_at, observed_post_hash
FROM mutation.mutation_journal
WHERE resource_key = 'case:case_adim8_smoke'
  AND action_family = 'approval.evidence'
  AND id > «BASELINE_MAX_ID»
ORDER BY id;
```

Beklenen, **hepsi birlikte**:

- **tam 1 YENİ satır**
- `state = 'completed'`
- `actor_user_id = «LAWYER_ID»`
- `resolved_at` dolu
- `observed_post_hash` dolu
- `resource_key` ve `action_family` exact eşleşiyor

**Apply başarısızsa veya birden fazla yeni satır çıkarsa DUR.**

Kanıt: `action_family` tek noktadan `approval.` öneki ile türetilir
(`ui/services/mutation_approval_facade.py:285`, `:312-319`; çağrı `:1035`);
`state` değer kümesi `db/migrations/0003_mutation_journal.sql:113-115`;
`completed` yazıcısı `state='completed'`, `observed_post_hash` ve
`resolved_at = now()` alanlarını birlikte yazar
(`ui/services/mutation_coordinator.py:374-381`); `vergi_app`'in journal SELECT
yetkisi `0006:208`.

### K.7 Tek preview, tek apply

Preview `--approve` taşımaz; bu modda **sıfır mutasyon, sıfır kilit, sıfır
journal erişimi** vardır (`ui/cli_mutate.py:46-53`).

**APP oturumunda:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m ui.cli_mutate approval --case case_adim8_smoke --row-key evidence --actor-user-id «LAWYER_ID»
```

Preview'ın bastığı pending sha256 değeri, apply'ın `--expected-hash`
argümanıdır. `--expected-hash` `--approve` ile **zorunludur** ve `--approve`
olmadan **reddedilir** (`ui/cli_mutate.py:198-202`); bu değer dispatcher
tarafından **asla** yeniden hesaplanmaz veya sessizce ikame edilmez
(`ui/cli_mutate.py:62-66`).

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m ui.cli_mutate approval --case case_adim8_smoke --row-key evidence --actor-user-id «LAWYER_ID» --approve --expected-hash «…»
```

Bu, **tek** gerçek apply'dır. Çıkış kodları: `0` başarı, `1` domain hatası,
`2` kullanım hatası (`ui/cli_mutate.py:133-135`).

### K.8 Assignment'ın geri alınması

**ADMIN oturumunda:**

```powershell
& "C:\Users\Burki\vergi_ui_runtime\Scripts\python.exe" -m scripts.iam_admin revoke-assignment --user-id «LAWYER_ID» --case-id case_adim8_smoke --actor-user-id «ADMIN_ID»
```

### K.9 Sentetik dizinin silinmesi ve residue doğrulaması

Silmeden **önce** `case_0001`'in dokunulmadığı kanıtlanır:

```powershell
git status --porcelain -- data/cases/case_0001
```

Beklenen: **boş çıktı**.

```powershell
git status --ignored --porcelain -- data/cases
```

Beklenen: **yalnız** `!! data/cases/case_adim8_smoke/` satırı. `!!` öneki
"ignored" anlamındadır ve beklenen durumdur: `.gitignore` kök-bağlı
`/data/cases/` kuralı yüzünden yeni case içeriği kazara stage edilmekten
korunur (Pilot Readiness Adım 2). `??` öneki görülürse **DUR** — bu, korumanın
beklendiği gibi çalışmadığı anlamına gelir.

Silme, exact yol ile:

```powershell
Remove-Item -LiteralPath "data\cases\case_adim8_smoke" -Recurse -Force
```

Silmeden **sonra**:

```powershell
git status --ignored --porcelain -- data/cases
```

Beklenen: **sıfır ignored girdi** ve ham `data/cases` manifesti üzerinde
değişiklik yok.

```powershell
Get-ChildItem -LiteralPath "data\cases" -Recurse -File | Measure-Object | Select-Object -ExpandProperty Count
```

**`git clean -fdx` ve `git stash --all` YASAKTIR.** Bu iki komut ignored gerçek
veriyi silebilir veya yakalayabilir. Ayrıca düz `git status` bu kontrol için
**yeterli değildir**; `--ignored` veya ham manifest kullanılır.

### K.10 Kalıcı audit izi — dört kalem (bağlayıcı, dürüst)

Smoke tamamlandıktan sonra veritabanında **kalıcı** olarak şu dört kayıt kalır
ve bunlar **ad-hoc `DELETE` ile temizlenmez**:

1. **Soft-revoked assignment satırı.** `revoke-assignment` yalnız
   `revoked_at` alanını doldurur (`scripts/iam_admin.py:167-176`); admin
   rolünün `iam.case_assignments` üzerinde `DELETE` yetkisi **yoktur**
   (`0006:293-300`).
2. **İki security event.** `case_assignment_granted`
   (`scripts/iam_admin.py:164`) **ve** `case_assignment_revoked`
   (`scripts/iam_admin.py:176`); admin rolünün `iam.security_events` üzerinde
   `DELETE` yetkisi **yoktur**.
3. **`completed` journal satırı.** `mutation.mutation_journal`;
   `vergi_app`'e `DELETE` verilmemiştir (`0006:208`).
4. **`mutation.mutation_resources` satırı `case:case_adim8_smoke`.** Case
   kaynakları seed edilmez, talep anında yaratılır
   (`db/migrations/0003_mutation_journal.sql:25-30`); `vergi_app`'in `INSERT`
   yetkisi vardır, `DELETE` yetkisi **yoktur** (`0006:207`).

Bu izler **kasıtlıdır**: mutation journal'ın amacı budur. Temizlenmeye
çalışılmaz.

---

## L. Doğrulama amaçlı dump ve restore

### L.1 Dump

Bağlantı, `passfile` bağlantı parametresi taşıyan **parolasız URI** ile verilir;
URI kullanıldığında ayrıca ve çelişkili biçimde host/port/kullanıcı argümanları
**yazılmaz**.

**OWNER oturumunda:**

```powershell
& "«PGBIN»\pg_dump.exe" --dbname="postgresql://vergi_owner@127.0.0.1:«PORT»/«PILOT_DB»?passfile=«PASSFILE_URL»" --no-password --format=custom --no-privileges --file="«BACKUP_DIR»\«STAMP».dump"
```

`«BACKUP_DIR»` **repo dışındadır** ve ACL'i §F.1'deki desenle daraltılır.

**`--no-owner` bu komutta BİLİNÇLİ OLARAK YOKTUR.** `pg_dump`'ın `--no-owner`
bayrağı **yalnız plain-text çıktı** için tanımlıdır — PostgreSQL 16 `pg_dump
--help` çıktısı bunu birebir söyler: *"skip restoration of object ownership in
plain-text format"*. Burada `--format=custom` kullanıldığı için bu bayrak
**etkisiz** olurdu; sahiplik bastırma **restore aşamasında** yapılır (§L.3).

### L.2 Boş doğrulama veritabanı

Superuser, **interaktif** bağlantıyla (§E.1) boş bir doğrulama veritabanı
yaratır:

```sql
CREATE DATABASE "«VERIFY_DB»" OWNER vergi_owner;
```

Passfile'a `«VERIFY_DB»` için `vergi_owner` satırı eklenir (§F.2).

### L.3 Restore

Restore **yalnız** bu ayrı ve boş veritabanına, **`vergi_owner` olarak**
yapılır. Arşiv dosyası **açık positional girdi**dir. Sahiplik ve ACL bastırma
**burada**, `pg_restore` aşamasında yapılır — `pg_dump` aşamasında değil
(§L.1).

```powershell
& "«PGBIN»\pg_restore.exe" --dbname="postgresql://vergi_owner@127.0.0.1:«PORT»/«VERIFY_DB»?passfile=«PASSFILE_URL»" --no-password --single-transaction --exit-on-error --no-owner --no-privileges "«BACKUP_DIR»\«STAMP».dump"
```

**Canlı pilot veritabanı üzerine restore YOKTUR.**

#### L.3.1 Sahiplik ve ACL semantiği (exact)

- **`--no-owner`**, arşivdeki `ALTER ... OWNER TO` / `SET SESSION
  AUTHORIZATION` sahiplik geri yüklemesini **bastırır**. PostgreSQL 16
  `pg_restore --help` bu bayrağı plain-text ile sınırlamaz: *"skip restoration
  of object ownership"*.
- Restore bağlantısı **`vergi_owner`** olduğu için, oluşturulan nesnelerin
  sahibi **`vergi_owner`** olur.
- Bu, **kaynak sahiplik paritesini kanıtlayan genel bir restore sözleşmesi
  DEĞİLDİR.** Bu runbook'ta kaynak nesnelerin de `vergi_owner`'a ait olması
  **beklenir** (§H.1, §I.2); eşleşme bu beklentinin sonucudur, arşivin taşıdığı
  bir kanıt değildir.
- **`--no-privileges`**, `GRANT`/`REVOKE` ACL kayıtlarının restore edilmesini
  **engeller**. PostgreSQL 16 `pg_restore --help`: *"skip restoration of access
  privileges (grant/revoke)"*.
- **Verification restore, 0006 privilege parity veya database-level ACL kanıtı
  DEĞİLDİR** (§L.6).

### L.4 Sayım karşılaştırması

İki tarafta da salt-okunur olarak koşulur ve sonuçlar karşılaştırılır.

```sql
SELECT n.nspname, c.relkind, count(*) AS objects
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('iam', 'mutation') AND c.relkind IN ('r', 'S')
GROUP BY n.nspname, c.relkind
ORDER BY n.nspname, c.relkind;
```

Ardından on iki tablonun her biri için satır sayısı:

```sql
SELECT 'iam.users' AS t, count(*) FROM iam.users
UNION ALL SELECT 'iam.external_identities', count(*) FROM iam.external_identities
UNION ALL SELECT 'iam.user_roles', count(*) FROM iam.user_roles
UNION ALL SELECT 'iam.case_assignments', count(*) FROM iam.case_assignments
UNION ALL SELECT 'iam.sessions', count(*) FROM iam.sessions
UNION ALL SELECT 'iam.oidc_login_transactions', count(*) FROM iam.oidc_login_transactions
UNION ALL SELECT 'iam.bootstrap_state', count(*) FROM iam.bootstrap_state
UNION ALL SELECT 'iam.security_events', count(*) FROM iam.security_events
UNION ALL SELECT 'iam.global_resource_grants', count(*) FROM iam.global_resource_grants
UNION ALL SELECT 'iam.global_resource_grant_events', count(*) FROM iam.global_resource_grant_events
UNION ALL SELECT 'mutation.mutation_resources', count(*) FROM mutation.mutation_resources
UNION ALL SELECT 'mutation.mutation_journal', count(*) FROM mutation.mutation_journal
ORDER BY 1;
```

### L.5 Doğrulama veritabanının düşürülmesi

Test bittiğinde superuser, interaktif bağlantıyla doğrulama veritabanını
düşürür ve passfile'daki `«VERIFY_DB»` satırı silinir:

```sql
DROP DATABASE "«VERIFY_DB»";
```

### L.6 Dört dürüst sınır (bağlayıcı)

1. **Bu işlem DB düzeyi ACL veya 0006 privilege parity kanıtı DEĞİLDİR.**
   `--no-privileges` hem 0006'nın `GRANT`'larını **hem de** `PUBLIC`
   revoke'larını (`0006:194-196`) dump dışında bırakır; doğrulama veritabanı
   canlıdan **iki eksende** farklıdır. `pg_restore --no-owner` ile sahiplik,
   arşivden değil **restore eden rolden** gelir; bu runbook restore'u
   `vergi_owner` ile ve sahibi `vergi_owner` olan bir veritabanına yaptığı için
   sahiplik fiilen eşleşir — ama bu, arşivin taşıdığı bir kanıt değil,
   **prosedürün** sonucudur (§L.3.1).
2. Custom-format dump, veritabanı düzeyindeki ACL'leri
   (`GRANT CONNECT` / `REVOKE TEMPORARY ... ON DATABASE`, `0006:196-199`) hiç
   taşımaz.
3. Dump **kişisel ve hukuki veri içerir**: `(issuer, subject)` çiftleri
   (`db/migrations/0001_iam_schema.sql:33-34`), görünen adlar ve session token
   hash'leri (`0001:85`). Bu yüzden repo dışında, ACL-korumalı bir dizinde
   tutulur ve hiçbir rapora kopyalanmaz.
4. Bu **gerçek bir yedekleme sözleşmesi DEĞİLDİR.** Zamanlama, saklama süresi,
   şifreleme, taşıma ve rotasyon **Row 19D'de açık kalır** (§O).

### L.7 Komut sözleşmesinin mekanik doğrulaması

§L.1 ve §L.3'ün komut satırları, koşulmadan **önce** bu tablodaki beklentilere
karşı kontrol edilir. Herhangi bir satır tutmazsa **DUR**.

| # | Beklenti | Nerede |
|---|---|---|
| 1 | `--format=custom` **tam 1** | `pg_dump` satırı |
| 2 | `--no-privileges` **tam 1** | `pg_dump` satırı |
| 3 | `--no-owner` **tam 0** | `pg_dump` satırı (custom formatta etkisiz) |
| 4 | `--no-owner` **tam 1** | `pg_restore` satırı |
| 5 | `--no-privileges` **tam 1** | `pg_restore` satırı |
| 6 | `--single-transaction` **tam 1** | `pg_restore` satırı |
| 7 | `--exit-on-error` **tam 1** | `pg_restore` satırı |
| 8 | `--no-password` **tam 1** | **her iki** satır |
| 9 | `passfile=` bağlantı parametresi **tam 1** | **her iki** URI |
| 10 | URI'de parola bölümü **yok** | her iki URI |
| 11 | Çelişen `--host` / `--port` / `--username` **tam 0** | her iki satır |
| 12 | `PGPASSWORD` / `PGPASSFILE` ortam değişkeni kullanımı **tam 0** | her iki adım |
| 13 | Arşiv dosyası **açık positional girdi** | `pg_restore` satırı |
| 14 | `--dbname` veritabanı adı `«VERIFY_DB»` | `pg_restore` URI'si |

Bu tablo, yalnız §L.1 ve §L.3'ün iki `powershell` bloğuna uygulanır.

---

## M. Kalıcı küme ile test kümesinin ayrılığı

### M.1 İki küme asla karışmaz

Kalıcı pilot kümesi, resmî test kapılarının kullandığı **atılabilir** kümeden
**farklı bir port ve farklı bir veritabanı adı** kullanır.

Resmî koşucu, `VERGI_IAM_DATABASE_URL` ile test hedefi aynı
`(host, port, dbname)` üçlüsünü gösteriyorsa çalışmayı **reddeder**
(`scripts/run_ui_tests.py:1929-1936`; karşılaştırma `:612-623`, loopback
alias'ları eşit sayılır). `production-parity` profilinde parse edilemeyen bir
DSN de reddedilir (`:1933-1934`).

### M.2 Operatör kuralı

**Resmî kapıları çalıştıran PowerShell oturumunda
`VERGI_IAM_DATABASE_URL` hiç tanımlanmaz.** En temiz kural budur ve yukarıdaki
reddetmelerin hiçbirine takılmaz.

Resmî kapılar yalnız commit'li baytlarla ve **tek sweep** olarak koşulur; bir
sweep sürerken repo dosyası düzenlenmez ve **iki sweep eşzamanlı koşulmaz**
(sentetik case dizinleri `data/cases/` içinde oluşur).

```powershell
python scripts\run_ui_tests.py --profile production-parity
```

```powershell
python scripts\run_ui_tests.py --profile rag-dependency
```

Hiçbir resmî kapı **kalıcı pilot veritabanına karşı koşulmaz**.

### M.3 Sayaçlar

Sweep ve test sayaç beklentileri her turda **yeniden türetilir**; önceki
turların sayıları yeniden kullanılmaz:

```powershell
git ls-files "ui/tests/test_*.py" | Measure-Object -Line
```

```powershell
git ls-files "ui/tests/test_*_postgres.py" | Measure-Object -Line
```

```powershell
git ls-files "db/migrations/*.sql" | Measure-Object -Line
```

---

## N. Pilot Readiness Adım 11'e geçişin maliyeti

Bu bölüm bir **uyarıdır**, bir plan değildir. Aşağıdakiler bu runbook'un
kapsamı dışındadır ve Adım 11'de ayrı bir onay turu gerektirir.

### N.1 Web login yolu veritabanı düzeyinde kapalıdır

0006 **hiçbir role** `iam.sessions` veya `iam.oidc_login_transactions` üzerinde
`INSERT` vermez (`0006:43-55`). Tarayıcı ile giriş bu yüzden veritabanına
ulaşamaz. Bu bir login bypass'ı **değildir**: veritabanı katmanı uygulama
katmanıyla aynı fikirdedir. Açılması **yeni, ayrı numaralı ve ayrıca
onaylanmış bir migration** (`0007`) ve büyük olasılıkla **dördüncü bir rol**
gerektirir.

### N.2 Kimlik yeniden bağlama komutu yoktur

`provision_user`, yeni bir `(issuer, subject)` çifti için **her zaman yeni bir
`iam.users` satırı** yaratır (`scripts/iam_admin.py:88-98`). Mevcut yerel
bootstrap admin'ine bir Entra kimliği **eklemek** için bir `link-identity`
komutu **yoktur** ve elle `INSERT` ile kapatılacak bir boşluk değildir; bu,
LOCKED Row 19B'ye dokunan **yeni bir komut** ve dolayısıyla açık bir §9
gerekçesi gerektirir.

`UNIQUE (issuer, subject)` kısıtı (`0001:36`) yüzünden yerel
`urn:vergi:local-cli` satırları Entra satırlarıyla çakışmaz — ama aynı kişi
**iki farklı `iam.users` satırına** düşer.

### N.3 Ek yapılandırma yükü

Adım 11'de sekiz `VERGI_ENTRA_*` değişkeni ve client secret
(`scripts/iam_bootstrap_probe.py:123-136`) ile custody sağlayıcı seçimi
(`ui/services/key_custody.py:712-718`) devreye girer. Gerçek Entra
tenant/uygulama kaydı, authentication-context ön kontrolü, Conditional Access
ve Key Vault rol dağıtımı **hâlâ açıktır** ve Adım 11/12'ye aittir.

---

## O. Row 19D'de açık kalan maddeler

Aşağıdakiler bu runbook tarafından **kapatılmamıştır** ve Row 19D'ye aittir:

- **Servis kimliği ve boot-time başlatma.** Bu runbook kümeyi operatörün kendi
  oturumundan başlatır (§D); Windows servis kaydı, servis hesabı ve o hesabın
  yetkileri sözleşmesi yoktur.
- **İşletim sistemi ACL sözleşmesi.** Veri dizini, passfile ve yedek dizini
  için §C/§F/§L'de verilen daraltmalar operatör adımlarıdır; mekanik olarak
  doğrulanan bir ACL sözleşmesi değildir.
- **Parola ve anahtar rotasyonu.** Rotasyon aralığı, prosedürü ve kanıtı
  tanımlı değildir.
- **Gerçek yedekleme sözleşmesi.** §L tek seferlik bir doğrulama turudur;
  zamanlama, saklama, şifreleme ve taşıma tanımlı değildir (§L.6 madde 4).
- **Session advisory-lock timeout.** `ui/services/mutation_lock.py` bloklayan
  bir advisory lock kullanır ve `lock_timeout` / `statement_timeout` tanımlı
  değildir; tutulan bir case kilidi bir onay isteğini süresiz bekletebilir.
- **`PUBLIC CONNECT` varsayılanı.** 0006 yalnız `TEMPORARY`'yi `PUBLIC`'ten
  geri alır (`0006:196`); veritabanı düzeyinde `PUBLIC CONNECT` bu slice'ta
  **değiştirilmemiştir**.
- **`ALTER DEFAULT PRIVILEGES` yoktur.** Gelecekteki nesnelere blanket yetki
  verilmez; her yeni migration kendi grant'ını açıkça yazar.

---

## P. Dar ve exact iddia

Bu belge bir **talimattır** ve yazıldığı tur içinde **hiçbir şey
çalıştırılmamıştır**: hiçbir küme kurulmadı, hiçbir migration uygulanmadı,
hiçbir rol veya IAM kullanıcısı oluşturulmadı, hiçbir sentetik case
yaratılmadı, hiçbir smoke koşulmadı, hiçbir yedek alınmadı.

Bu belge **iddia etmez**:

- Pilot Readiness **Adım 8'in tamamlandığını**. Adım 8 tamamlanmamıştır.
- Adım 9–13'ün, corpus edinim/populasyonunun veya Row 19D'nin kapandığını.
- **Pilotun production-ready olduğunu.**
- Kalıcı kümenin, passfile'ın veya yedek dizininin işletim sistemi düzeyinde
  güvenli olduğunun mekanik olarak doğrulandığını.
- §K.3'teki yeniden adlandırılmış sentetik kopya üzerinde uçtan uca
  validation'ın geçeceğini; bu **çalıştırmayla kanıtlanmamıştır** ve §K.1'in
  STOP kuralı geçerlidir.

Bu belgenin **iddia ettiği** tek şey şudur: burada verilen adımlar, commit'li
kaynaklardan (`db/migrations/0001`–`0006`, `scripts/iam_admin.py`,
`ui/cli_mutate.py`, `ui/services/*`, `src/*`, `scripts/run_ui_tests.py`) ve
PostgreSQL 16 komut satırı yardım çıktılarından okunmuştur ve o kaynakların
bugünkü sözleşmesiyle tutarlıdır.
