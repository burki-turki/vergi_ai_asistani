### Pilot Readiness Adım 8 / Slice 8A — IAM Runtime Privilege Contract (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve Slice 8A sınırı**

Adım 8'in discovery turunda ortaya çıkan bloklayıcı bulgu şuydu: `db/migrations/`
içindeki 0001–0005'in hiçbiri **tek bir SQL `GRANT`/`CREATE ROLE`/`OWNER TO`**
ifadesi taşımıyordu. PostgreSQL varsayılanlarında özel şemalarda `PUBLIC`'in
`USAGE`'ı olmadığı için bu, uygulamanın ancak **nesneleri oluşturan owner rolüyle
ya da superuser ile** çalışabileceği anlamına geliyordu. Kullanıcının bağlayıcı
güvenlik sınırı ("uygulama ve CLI smoke cluster superuser ile çalıştırılamaz;
migration/owner credential'ı runtime DSN olarak kullanılamaz") bu sözleşmeyle
karşılanamıyordu; bu yüzden Adım 8, runbook'tan ÖNCE versiyonlanmış bir
least-privilege rol sözleşmesi gerektirdi ve dört slice'a bölündü.

Slice 8A **yalnız** bu sözleşmeyi ve onun gerçek PostgreSQL kanıtını kapsar.
**Adım 8'in KENDİSİ ACTIVE / NEXT olarak KALIR.**

**B. Exact commit / kapsam**

- SHA: `229489c34574f4718e1f65b6d4f8478c308ed6a2`
- Parent: `a14603e288b2a983b83ee4632387b08d43676a04`
- Subject: `Enforce least-privilege IAM database access` (body yok, trailer yok)
- Kapsam: **2 A + 4 M = 6 dosya**, 1346 insertion / 21 deletion

| Durum | Dosya |
|---|---|
| A | `db/migrations/0006_iam_runtime_privileges.sql` (362 satır) |
| A | `ui/tests/test_iam_runtime_privileges_postgres.py` (643 satır) |
| M | `scripts/run_ui_tests.py` |
| M | `ui/tests/test_run_ui_tests_isolated.py` |
| M | `ui/tests/test_run_ui_tests_integration_postgres.py` |
| M | `ui/tests/test_iam_migrations_isolated.py` |

**C. Üç canonical DB rolü ve exact privilege matrisi**

Roller: `vergi_owner` (şema/tablo/sequence sahibi, migration DDL, dump/restore),
`vergi_app` (`ui/cli_mutate.py` runtime), `vergi_iam_admin`
(`scripts/iam_admin.py` + `scripts/global_resource_grants.py`). Üçü de
`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`. Her yetki
kaynak çağrı noktasından türetilmiştir; `ALL TABLES`/`ALL SEQUENCES`
kullanılmamıştır.

`vergi_app` — **exact 11 doğrudan yetki**: `SELECT` on `iam.users`,
`iam.case_assignments`, `iam.sessions`, `iam.user_roles`,
`iam.global_resource_grants` · `SELECT, INSERT` on
`mutation.mutation_resources` (`mutation_lock.py`'nin case-scoped
`INSERT … ON CONFLICT DO NOTHING` get-or-create yolu) · `SELECT, INSERT,
UPDATE` on `mutation.mutation_journal` · `USAGE` on
`mutation.mutation_journal_id_seq`. `iam.security_events`,
`iam.oidc_login_transactions`, `iam.external_identities`,
`iam.bootstrap_state`, `iam.global_resource_grant_events` üzerinde **sıfır
yetki**; hiçbir yerde `DELETE` yok, DDL yok.

`vergi_iam_admin` — **exact 32 doğrudan yetki**: `SELECT, INSERT, UPDATE` on
`iam.users`, `iam.external_identities`, `iam.case_assignments`,
`iam.security_events`, `iam.bootstrap_state`, `iam.user_roles`,
`iam.global_resource_grants` · **`DELETE` yalnız `iam.user_roles`**
(`iam_admin.py`'nin `revoke-role` satırı, üretimdeki tek `DELETE`) ·
`SELECT, UPDATE` on `iam.sessions` (INSERT **yok** — yalnız revoke) ·
**`INSERT` only** on `iam.global_resource_grant_events` (üretimde tek erişim
biçimi) · `USAGE` on altı `BIGSERIAL` sequence · `SELECT` **only** on
`mutation.mutation_resources`. `mutation.mutation_journal` ve
`iam.oidc_login_transactions` üzerinde **sıfır yetki**.

`mutation.mutation_resources.advisory_lock_id` `GENERATED ALWAYS AS IDENTITY`
olduğu için ayrı bir sequence grant'i gerekmez.

**D. 0006'nın sözleşmesi**

*Fail-closed precondition'lar* (hiçbiri tutmazsa tek bir GRANT bile
uygulanmaz): rol parametreleri boş olamaz ve sessizce canonical ada düşemez;
üç rol birbirinden farklı olmalı; üçü de `pg_roles`'ta var olmalı; hiçbiri
`rolsuper`/`rolcreatedb`/`rolcreaterole`/`rolreplication`/`rolbypassrls`
taşımamalı; `current_database()` sahibi owner rolü olmalı; `iam` ve `mutation`
şemaları var olmalı ve owner rolüne ait olmalı; migration owner rolü tarafından
uygulanmalı; her grant hedefi (12 tablo + 7 sequence) mevcut olmalı.

*Atomiklik*: tek transaction — `\set ON_ERROR_STOP on` → `BEGIN;` →
`set_config` → precondition `DO` → `REVOKE`/`GRANT` → postcondition `DO` →
`COMMIT;`. `GRANT`/`REVOKE` PostgreSQL'de transactional olduğundan kısmi
privilege durumu hayatta kalamaz.

*Postcondition*: `vergi_app` ve `vergi_iam_admin` için **exact-set match** —
eksik **ve fazla** yetkinin ikisi de fail eder.

*Idempotency*: `GRANT`/`REVOKE` doğası gereği idempotenttir ve postcondition
exact-set olduğu için yeniden uygulama güvenlidir ve no-op'tur.

*Parametrik rol mekanizması*: rol adları psql değişkenleridir
(`owner_role`/`app_role`/`admin_role`), set edilmemişse canonical adlara
düşerler. psql dollar-quoted gövdelerin içinde değişken genişletmediği için
`:'var'` **hiçbir `DO` gövdesine yazılmaz**; değerler dollar-quote'un DIŞINDA
`SELECT set_config(...) … \gset` ile session-scoped custom GUC'lere yazılır ve
`DO` blokları `current_setting(..., true)` ile okur. Dinamik identifier'ların
tamamı `format('%I')`'den geçer; raw string interpolation yoktur. Bu mekanizma
sayesinde privilege testi, canonical cluster-wide rolleri hiç oluşturmadan veya
silmeden "rol yok"/"rol fazla yetkili" dallarını çalıştırabilir.

*Rollback (bağlayıcı)*: 0006 uygulanmadıysa rollback = **uygulamamak**.
**Uygulandıktan sonra privilege durumu ad-hoc `GRANT`/`REVOKE`/`ALTER` ile ASLA
düzeltilmez**; her değişiklik veya geri alma **yeni, versiyonlanmış ve ayrıca
onaylanmış bir migration** gerektirir. **0001–0006 immutable kalır.** Runbook
veya operatör SQL oturumu migration geçmişinin yerine geçemez.

**E. PUBLIC ACL, credential ve disposable-cluster authentication sözleşmesi**

`has_schema_privilege('public', …)` **KULLANILMAZ** — PostgreSQL `PUBLIC`
pseudo-role'ünü bu fonksiyonun user argümanı olarak kabul etmez. PUBLIC, ACL
içinde **grantee OID 0**'dır; kontrol `pg_namespace.nspacl` + `aclexplode()` +
`coalesce(nspacl, acldefault('n'::"char", nspowner))` üzerinden yapılır ve her
iki şemanın varlığı ayrıca doğrulanır (eksik şemada `true`'ya düşmez). Aynı
mekanizma üç yerde kullanılır: 0006 postcondition'ı, runner'ın birleşik sentinel
sorgusu ve gerçek PostgreSQL integration testi.

Credential sözleşmesi (G3): `PGPASSWORD` `ENV_ALLOWLIST_PG`'den çıkarılıp
`ENV_DENY_EXACT`'e alındı, `is_denylisted_name`'deki tek istisna kaldırıldı;
`PGPASSFILE` deny olarak kaldı. **Runner hiçbir child process'e parola veya
passfile environment değeri taşımaz**; parola gereken test bunu libpq'nun
`passfile` **connection parameter**'ı ile verir. Redaction kırılmadı —
`collect_parent_secret_values` artık aynı değeri denylist üzerinden yakalar.

Disposable test cluster'ı için authentication sözleşmesi `--help` precondition
metnine yazıldı ve teste pinlendi: trust **yalnız disposable cluster** içindir
ve **yalnız exact bootstrap superuser + exact `127.0.0.1/32`** satırıyla
(`host all <superuser> 127.0.0.1/32 trust`); `host all all 127.0.0.1/32 trust`
ve her blanket-trust kuralı **YASAKTIR** ve privilege modülünün **P1** kontrolü
tarafından reddedilir; diğer tüm roller `scram-sha-256` kullanır; **kalıcı pilot
cluster'ında superuser dahil hiçbir rol için trust yoktur**. Bu kural olmadan
passfile negative control'ü vacuous olurdu.

Runner sentinel'i: 0006 hiçbir nesne yaratmadığı için `table`/`column` sentinel
tipleri onu göremez ve tek bir probe kısmen uygulanmış bir 0006'yı yakalayamaz.
Bu yüzden **`contract` tipi** eklendi ve **sekiz bağımsız etiket** pinlendi
(`roles_exist`, `roles_not_privileged`, `owner_is_vergi_owner`,
`app_can_write_journal`, `admin_can_insert_grants`, `app_cannot_insert_oidc`,
`admin_cannot_insert_journal`, `public_has_no_schema_access`). Her probe
`EXISTS(pg_roles)` + `to_regclass()` guard'ları arkasındadır; sorgu hata
verirse tüm etiketler eksik sayılır (fail-closed), SQL exception'ıyla
çökülmez. Yeni migration-history tablosu **açılmadı**.

**F. Test matrisi ve targeted sonuçlar**

Yeni `test_iam_runtime_privileges_postgres` (47 kontrol) kendi tokenized
rolleriyle kendi throwaway veritabanlarında çalışır: P1–P3 (blanket-trust reddi,
ad çakışması guard'ı), S1–S3 (ACL doğrulaması, env temizliği, 0001–0005),
C1–C2 (doğru passfile bağlanır; yanlış/eksik passfile **reddedilir**),
F1–F8 (boş parametre, eksik rol, aynı rol iki kez, fazla yetkili rol, yanlış DB
owner, yanlış schema owner, yanlış uygulayıcı rol, eksik grant hedefi — hepsi
fail-closed), A1–A3 (postcondition patlaması → 0006'nın kendi grant'ları
rollback, önceden commit'li fazla grant hayatta), G1–G5 (pozitif apply, exact
app/admin kümeleri, idempotent yeniden uygulama, PUBLIC ACL), M1–M20 (gerçek
bağlantılarla pozitif/negatif matris; web-login yazmalarının ve DDL'in
reddedilmesi; `global_resource_grants.py` dizisinin başarısı), Z1–Z2 (sıfır
tokenized residue, temp dizini silinmiş).

Targeted sonuçlar (remediation sonrası): `test_iam_runtime_privileges_postgres`
**47/0** · `test_iam_migrations_isolated` **43/0** (0004/0005 boşluğu kapatıldı;
0006 burada **bilerek test edilmez** — karar III-a) ·
`test_run_ui_tests_integration_postgres` **70/0** ·
`test_run_ui_tests_isolated` **336/0** · örneklenmiş regresyon
`test_mutation_journal_postgres` **61/0**, `test_cli_mutate_integration_postgres`
**150/0**.

**G. İlk uygulama / remediasyon süreci**

Gerçek küme üzerinde çalıştırma üç kusuru yakaladı ve düzeltildi: (1)
`acldefault`'un ilk argümanı `"char"`'dır, `text` değil — ilk koşumda 0006
patladı ve transaction tamamen geri alındı (atomikliğin ilk canlı kanıtı);
(2) `CREATE ROLE` bir utility statement olduğu için bind parametresi kabul
etmez — parola `psycopg.sql.Literal` ile injection-güvenli biçimde compose
edildi; (3) `mutation_journal` ve `global_resource_grant_events`'in zorunlu
kolonları test fixture'larına eklendi.

Ardından kullanıcı üç kapanış düzeltmesi istedi ve uygulandı: **(i)** `--help`
trust metni daraltıldı (belirsiz "expose a passfile" dili kaldırıldı, blanket
trust yasağı ve P1 reddi açıkça yazıldı) ve yedi kontrolle teste pinlendi;
**(ii)** `test_run_ui_tests_integration_postgres.py`'deki **vacuous** secret
kontrolü kaldırıldı — `PGPASSWORD` `os.environ`'dan okunuyordu ve sweep altında
strip edildiği için `all([])` her zaman `True` dönüyordu; yerine bilinen bir
canary enjekte eden deterministik kontroller ve child process'in kendi
ortamının tanıklığı kondu (`PGPASSFILE` dahil); **(iii)** bu koşulara ait exact
bytecode yolları listelenip yalnız onlar silindi (`git clean -fdx` veya geniş
temizlik **kullanılmadı**).

**H. Resmî kapı kanıtları**

Temiz detached worktree (`core.autocrlf=false`, `core.eol=lf`, başlangıç
status boş), commit'li baytlar, taze/disposable loopback-only PostgreSQL 16
(OS'un seçtiği boş port, blanket-trust kuralı 0, `log_statement='none'`),
0001→0006 `vergi_owner` ile ve `ON_ERROR_STOP` altında uygulandı.

`production-parity` (`vergi_ui_runtime`): **exit 0**, state `completed`,
sweep_label **FULL**, **84/84 modül PASS**, `modules_non_pass=0`,
`modules_not_spawned=0`, **6864 passed / 0 failed**, counted_skips 8,
informational_skips 14, TALLY_MISMATCH **0 modül**, yeni privilege modülü
**PASS passed=47**, `*_postgres.py` **16/16 gerçekten çalıştı, hepsi PASS ve
passed>0**, discovery `git_and_fs` **tracked=filesystem=run=84**
(missing/untracked/rejected `[]`), `migrations_missing=[]`, `contract_probe=ok`
ve **0006 sözleşmesi 8/8 true**, postgres `connected`/`migrations_ok`/
`server_addr_loopback` **True**, guard **221 = 221** (`inheritance_ok=True`,
`malformed_lines=0`, `suspicious_popens=[]`), positive controls **10/10**,
protected manifest **391 girdi, `protected_manifest_ok=True`,
`protected_path_diff=[]`**, secret scan **168 dosya, `hits=[]`**, process/temp/
db/bytecode residue **hepsi `[]`**, `refusals=[]`, `warnings=[]`,
`git.head=229489c34574f4718e1f65b6d4f8478c308ed6a2`, `git.clean=true`.

`rag-dependency` (root `.venv`, tüm PostgreSQL env değişkenleri unset, parity
tamamlandıktan sonra ve eşzamanlı değil): **exit 0**, state `completed`,
**RAG_GATE_PASS**, **3/3 PASS**, **216 passed / 0 failed**, marker
`DEPENDENCY GATE: PASS` mevcut, guard **7/7** ve positive controls **10/10**,
integrity temiz, `git.head` exact ve `clean=true`. Informational skip: **ham 1
/ K.1 muafiyeti 1 / etkin 0** (adıyla muaf tutulan tek platform-gated skip,
`test_rag_bundle_builder_isolated`, win32).

`stderr` yazan dokuz modül incelendi: sekizi bilinen
`StarletteDeprecationWarning` (Row 19B'nin kayıtlı backlog maddesi), biri
testlerin kasten tetiklediği reddetme mesajlarıdır — gerçek hata/uyarı değil.

**I. Sabit sayaçlar ve bütünlük**

Commit sonrası tracked sayaçlar (§13.1.8 uyarınca bu turda yeniden türetildi):
test modülü **84**, `*_postgres.py` **16**, migration **6**.
Worktree `data/**` manifesti sweep öncesi ve sonrası **110 → 110 dosya,
byte-identical** (differing **0**, aggregate
`773800ba2ebdb463042bd01d8e1102c060d682b4569497f5323f97eca5817f17`).
`data/cases` tracked ve ignored residue **yok**; canonical/pending/audit/
history/backup üretimi **yok**. 0001–0005 commit'te **bulunmaz** ve parent ile
**5/5 byte-identical**. Disposable cluster fast-stop edildi, port boşaldı,
postgres process 0, cluster ve geçici passfile dizinleri kaldırıldı, detached
worktree remove + prune edildi.

**J. Açık kapsam, sonraki slice ve final verdict**

Bu LOCK'un **KAPSAMADIĞI**, açıkça yazılı sınırlar:

- **0006 rol OLUŞTURMAZ**; üç canonical rol operatörce, migration dışında
  önceden oluşturulur. `CREATE ROLE` cluster düzeyinde olduğu için bilinçli
  olarak migration dışında bırakılmıştır.
- **0001–0006 immutable**; uygulanmış bir migration ad-hoc `GRANT`/`REVOKE`
  ile geri alınamaz — düzeltme **yeni versiyonlanmış bir migration** ister.
- **PUBLIC `CONNECT` varsayılanı bu slice'ta DEĞİŞTİRİLMEDİ** (üç role
  açıkça `CONNECT` verilir; PUBLIC'ten yalnız `TEMPORARY` revoke edilir).
- **`ALTER DEFAULT PRIVILEGES` YOKTUR**; gelecekteki nesnelere blanket yetki
  verilmez, her yeni migration kendi grant'ını açıkça yazar.
- **Web/OIDC/session yazma yolu hâlâ YETKİSİZDİR** ve **Adım 11**'i bekler;
  bu fail-closed davranış bir login bypass'ı değil, veritabanı katmanının
  uygulama katmanıyla aynı fikirde olmasıdır.
- **Kalıcı cluster, operatör runbook'u, gerçek IAM kullanıcıları, case
  assignment, dump/restore kanıtı ve operational smoke bu slice'ın kapsamı
  DEĞİLDİR.**
- **Row 19D** servis kimliği / OS ACL / rotation / backup sözleşmeleri ve
  session advisory-lock timeout backlog'u **AÇIK KALIR**.
- **Adım 8 TAMAMLANMIŞ DEĞİLDİR** ve **ACTIVE / NEXT** olarak kalır.
- **Pilotun production-ready olduğu İDDİA EDİLMEZ.**

**Sıradaki exact iş: Slice 8B — operatör runbook'u**
(`docs/operations/local-postgresql-iam-adoption.md`), ardından **Slice 8C —
kalıcı yerel cluster ve IAM operational adoption**, ardından **Slice 8D — Adım
8 final roadmap checkpoint'i**.

`POST-COMMIT OFFICIAL GATES PASS — READY FOR SLICE 8A ROADMAP CHECKPOINT`
