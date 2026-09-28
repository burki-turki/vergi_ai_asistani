### Holiday Calendar Schema V2 — Phase A Technical Plumbing (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve dar kapsam** — Pilot Readiness Adım 5, git-governed,
tarihsiz bir resmî tatil takvimi registry'si ve `calendar_complete`
türetimini kilitlemişti; Adım 6 (avukat doğrulaması) hâlâ ACTIVE /
NEXT'tir. Avukatın doğrulanmış tarihleri gerçekten girebilmesi için
takvimin, her tatil gününü kayıtlı bir canonical gözleme
(`observance_id`) bağlayan, yarım günü açık bir politikaya göre ele
alan ve doğrulanmış bir yılın tamlığını makine düzeyinde denetleyen
bir yapıya ihtiyacı vardı. Phase A yalnız bu **teknik tesisatı**
kurar: şema, registry, validator ve LOCKED Row 8 hesaplayıcı tarafı.
Phase A **hiçbir resmî tatil tarihi eklemez, hiçbir yılı
`verified:true` yapmaz, hiçbir `verification_ref` almaz ve avukat
doğrulamasını tamamlamaz.** Bu bölüm YALNIZ "Holiday Calendar Schema
V2 — Phase A Technical Plumbing" alt kapsamını DONE / LOCKED olarak
kaydeder; 2024–2035 resmî tatil tarihlerinin üretime eklenmesi,
`holiday_calendar` veri popülasyonu, herhangi bir yılın
`verified:true` yapılması, `verification_ref` alınması, avukat
doğrulamasının tamamlanması, Phase B ve pilotun genel olarak
production-ready olması BU BÖLÜMDE DONE / LOCKED DEĞİLDİR. Adım 5
checkpoint'inin §F'si şemanın V1 (`calendar_version` 1) durumunu
tanımlar ve kendi commit'i için tarihsel olarak doğru kalır —
DEĞİŞTİRİLMEDİ.

**B. Exact kapsam ve commit** — Kullanıcı tarafından, bağımsız final
re-review'ün `PHASE A READY FOR COMMIT AUTHORIZATION` verdict'inden
sonra açıkça yetkilendirilen tek commit: **0 YENİ + 7 DEĞİŞTİRİLMİŞ =
7 dosya**; `git show --numstat`: 1872 ekleme, 20 silme (şema 68/2,
registry 1/1, hesaplayıcı 122/13, validator 1241/2, derivation testi
83/0, engine testi 3/2, validator testi 354/0). Yerel commit
`1366e8e40d7923c304f4a818caa65b211764b593`, parent
`d2e66fe6b75bb95fa3fe3f00ffe3dbc241f99023`, subject
`Implement holiday calendar schema v2 phase A plumbing` (body/trailer
YOK; push YAPILMADI). Commit öncesi preflight, staged 7 blob'un
SHA-256'larını yetki listesiyle bayt-bayt eşleştirdi; commit sonrası
`HEAD:<path>`
blob'larının AYNI SHA-256'ları taşıdığı doğrulandı (hiçbir hook dosya
yeniden yazmadı); 7 blob da LF'dir (0 CR). Üretim verisinde YALNIZ
registry'nin `calendar_version` değeri değişti (tek satır);
`data/cases/**`, `data/documents.json`, `data/provisions.json`,
`data/deadline_rules/deadline_rules.json`, `data/corpus_policy/**`
DEĞİŞMEDİ. Sıfır migration, sıfır web/CLI yüzeyi, sıfır bağımlılık
değişikliği; `ui/services/generation_mutation_facade.py`,
`ui/services/generation_mutation_adapters.py`, `ui/cli_mutate.py`,
`src/deadline_engine.py`, `data/case_deadline.schema.json` ve
`data/deadline_rules/deadline_rules.json` bu commit'te DOKUNULMADI.

| Dosya | Durum | SHA-256 (commit blob, LF) |
|---|---|---|
| `data/holiday_calendar.schema.json` | DEĞİŞTİRİLMİŞ (Adım 5 LOCKED) | `d62b3e7574b0f1b33eb998e7bb0d4579fc490f466df29cb50ddbfd4a1a463117` |
| `data/holiday_calendar/holiday_calendar.json` | DEĞİŞTİRİLMİŞ (Adım 5 LOCKED; yalnız `calendar_version` 1→2) | `26741d7aa36d54d2a88f6d49fc166d14c6a94246857c96fc9b59c4db68220004` |
| `src/deadline_calculator.py` | DEĞİŞTİRİLMİŞ (**LOCKED Row 8**) | `ee03abefc74cb4227981f7c3017e1c6f9d0cc5e8e9a9ffcf67a526f355631385` |
| `src/holiday_calendar_validator.py` | DEĞİŞTİRİLMİŞ (Adım 5 LOCKED) | `0dc271c24313421e6c7d9456e04d024f50d9ff9f31ca46cdda661f0b5323a32a` |
| `ui/tests/test_deadline_calendar_derivation_isolated.py` | DEĞİŞTİRİLMİŞ (yalnız additive kanıt, 0 silme) | `b48c86d384a6897aa94a97e74fdc2c94e7bce338fe3030379c45d215f537bd93` |
| `ui/tests/test_holiday_calendar_validator_isolated.py` | DEĞİŞTİRİLMİŞ (yalnız additive kanıt, 0 silme) | `d740b94318bde3a3b952479c9e2dc4231351b153740c43c79eb1068b76e73e18` |
| `ui/tests/test_deadline_engine_isolated.py` | DEĞİŞTİRİLMİŞ (8b tutarlılık: sabit `1` yerine üretim dosyasından okunan `calendar_version`) | `0965195bfbd98d49443bf33d0e34d3e336eee0a7b31168219eb8b04c97f4e269` |

**C. Şema sözleşmesi (`data/holiday_calendar.schema.json`)** — Title
`"...Schema V1"` → `"...Schema V2"` (kozmetik); `schema_version` `const`
**1** DEĞİŞMEDİ; `calendar_id` `const "tr_official_holiday_calendar_v1"`
DEĞİŞMEDİ (bu bir kimlik literalidir, §H madde 4'teki kozmetik "V1"
başlık metinlerinden AYRIDIR). `calendar_version` şemada
`integer, minimum: 1` olarak kalır — şema 2'ye PİNLEMEZ; 1→2 artışı
üretim registry'sinin DEĞERİNDEDİR (§D). `half_day_policy` **top-level**
kaldı; eski üç değer `not_decided`, `counts_as_holiday`,
`counts_as_working_day` korundu; dördüncü, additive değer
`needs_review_if_deadline_day` eklendi (şema diff'inde görünen tek
"silinen" enum satırı, üçüncü değere sondaki virgülün eklenmesinden
ibarettir — üç eski değerin tamamı yerinde). `holiday_entry`'nin
zorunlu alanları (`date`, `name`, `kind`, `day_type`,
`source_ref_index`, `notes`) DEĞİŞMEDİ; **opsiyonel, additive
`observances[]`** (`minItems: 1`, her üye `$defs.observance`) eklendi —
`observances[]` taşımayan legacy flat kayıt şemada geçerli kalır.
`$defs.observance`: `observance_id` (kapalı enum, **17** değer:
`yilbasi`, `ulusal_egemenlik_cocuk_bayrami`, `emek_dayanisma_gunu`,
`ataturk_anma_genclik_spor_bayrami`, `demokrasi_milli_birlik_gunu`,
`zafer_bayrami`, `cumhuriyet_bayrami_arefe`, `cumhuriyet_bayrami`,
`ramazan_bayrami_arefe`, `ramazan_bayrami_gun1`..`gun3`,
`kurban_bayrami_arefe`, `kurban_bayrami_gun1`..`gun4`), `kind`
(`national`/`religious`), `day_type` (`full_day`/`half_day`),
`legal_basis_ref` (boş olmayan string), `block_index` (`integer ≥ 1`
veya `null`) — beşi de zorunlu; `additionalProperties: false`.

**D. Üretim registry'si (`data/holiday_calendar/holiday_calendar.json`)
— hâlâ tarihsiz** — Commit'teki TEK içerik değişikliği
`calendar_version` `1` → `2`'dir (tek satır). Commit'li baytlar
üzerinden doğrulanan güncel durum: 12 yıl (2024–2035); her yılda
`holidays: []` ve `source_refs: []`; `verified:true` sayısı **0** (12
yılın tamamı `false`); tüm `verification_ref` değerleri `null`; hiçbir
yerde `observances` anahtarı YOK; üretim `half_day_policy` hâlâ
`not_decided` — yani dördüncü politika şema ve hesaplayıcı düzeyinde
MEVCUT ama üretimde BENİMSENMEMİŞTİR ve Adım 5'in "`not_decided` iken
`verified:true` bir yılda `half_day` girdisi ERROR" kapısı AYNEN
yürürlüktedir. `calendar_version` artışı, takvim ham baytlarının
`generation.deadline` `input_digest`'ine (Adım 5, `digest_version`
`row19c3ci.deadline.v3`) girmesi nedeniyle tasarım gereği yeni
deadline generation identity'leri üretir (bkz. §H madde 6).

**E. Validator sözleşmesi (`src/holiday_calendar_validator.py`)** —
`HOLIDAY_CALENDAR_VALIDATOR_VERSION` `"1"` → `"2"`; dosyanın iki
silinen satırı bu literal ile eski `V1: 26/26 PASS` self-test
banner'ıdır (yerine `V2: 55/55 PASS`). **Canonical observance
registry**: `CANONICAL_OBSERVANCE_REGISTRY` tam **17** kayıt
(`assert len(...) == 17` modül yükünde), her kayıt aile/kind/
day_type/sequence_position taşır;
`validate_observance_registry_consistency()` bilinmeyen
`observance_id`'yi, aynı girdi içindeki tekrar eden `observance_id`'yi,
ulusal gözlemde `null` olmayan `block_index`'i ve dinî gözlemde pozitif
tam sayı olmayan `block_index`'i reddeder. **Duplicate anahtarları**:
ulusal gözlem yıl içinde TAM 1 kez (anahtar `observance_id`); dinî
gözlem anahtarı `(family, block_index, observance_id)` — aynı id'nin
FARKLI `block_index`'lerde bulunması meşrudur (2033'ün iki Ramazan
bloğu). **Çok bloklu yıllar**: her `(family, block_index)` bloğu
bağımsız doğrulanır (blok içi bitişiklik ve blok-başına tamlık);
kaynak yorumları, Phase A bağımsız incelemesinin bulduğu bir F1
remediation'ını kaydeder — eski last-wins `seen_oids` sözlüğü, iki
bloklu bir yılda ikinci bloğun birinci bloğun eksiğini MASKELEMESİNE
yol açıyordu (çok-bloklu tamlık fail-open); occurrence listeleri ile
blok-başına ayrı değerlendirmeye geçilerek kapatıldı (bkz. §G). **Exact
dinî
blok-sayısı sözleşmesi** (`REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT`,
`REV41_BLOCK_COUNT_SUPPORTED_YEARS` = 2024..2035, 12 yıl, modül-yükü
assert'leriyle): Ramazan 2033 = **2** blok, diğer tüm Ramazan yılları
= 1, Kurban her yıl = 1.
`validate_verified_year_observance_completeness()` yalnız
`verified is True` OLAN VE `observances[]` modelini en az bir girdide
kullanan yıllar için çalışır; destek aralığı DIŞINDA `verified:true` +
`observances[]` bir yıl **sessiz tahmin yerine fail-closed reddedilir**
("refusing to guess; extend the contract with lawyer-verified input").
Saf-legacy (`observances[]`'sız) `verified:true` yıl bu tamlık
kapısının KAPSAMI DIŞINDADIR — mevcut legacy structural kontroller
onu kapsamaya devam eder (bkz. §H madde 3). Kaynak yorumlarına göre
blok-sayısı tablosunun değerleri, bağımsız incelemeden geçmiş bir
"REV4.1 tasarım paketi"nden birebir taşınmıştır; o paket bu
repository'de DEĞİLDİR ve bu checkpoint onun içeriğini
doğrulamaz/üretmez — yalnız kaynak kodun kendi atfını kaydeder.

**F. Hesaplayıcı davranışı (`src/deadline_calculator.py`, LOCKED Row
8)** — `derive_effective_holiday_calendar()`: bir girdi `observances[]`
taşıyorsa efektif `day_type`, gözlemlerin `day_type` kümesinde
`full_day` VARSA `full_day`, yoksa `half_day` olarak türetilir
(**full-day + half-day çakışmasında full-day üstün gelir**);
`observances[]` yoksa legacy flat `day_type` okunur (uyumluluk).
`full_day` (ve `counts_as_holiday` altındaki `half_day`) tarihleri
eskisi gibi `holiday_dates`'e girer; YALNIZ
`half_day_policy == "needs_review_if_deadline_day"` iken ve YALNIZ
gerçekten yalnız-half-day kalan tarihler yeni, ayrı `half_day_only_dates`
kümesine girer; diğer üç politikada bu küme HER ZAMAN boştur.
`calculate_rule_deadline()`: adli tatil/hafta sonu/tatil kaydırması ve
Adım 5'in takvim-kapsam kapısı DEĞİŞMEDEN çalıştıktan sonra,
`final_deadline` `half_day_only_dates` içindeyse **fail-closed
`needs_review`** (`calculated_deadline: null`,
`holiday_adjustment_applied: false`,
`reason: holiday_calendar_half_day_deadline_requires_review`) döner;
`full_day` tarihleri zaten kaydırıldığı için bu dal yalnız gerçekten
yalnız-half-day final günlerde tetiklenir ve yalnız
`end_day_policy == next_business_day_if_holiday` dalına sınırlıdır
(bugün aktif tek kural). Commit diff'inde `calculate_rule_deadline` ve
`load_holiday_calendar` hunk'ları saf EKLEMEDİR (sıfır silme); silinen
13 satırın tamamı (11 içerikli + 2 boş)
`derive_effective_holiday_calendar`'ın iki hunk'ına — flat `day_type`
okumasının observance-farkındalı yeniden düzenlenmesine — aittir.
`calculation_state` sözlüğü, mali tatil (Adım 7) mantığı ve
`DEFAULT_HOLIDAY_CALENDAR_PATH` sabiti DEĞİŞMEDİ.
`load_holiday_calendar()` audit alanı olarak takvimin
`calendar_version`'ını taşımaya devam eder;
`ui/tests/test_deadline_engine_isolated.py`'nin 8b kontrolü, sabit `1`
literali yerine üretim dosyasından okunan `calendar_version` değerini
karşılaştırır — bir tutarlılık kontrolüdür, güçlendirilmiş veya
gevşetilmiş bir assertion DEĞİLDİR.

**G. Test ve inceleme kanıtı — attribution açık** — Bu roadmap-lock
taslağı turunda HİÇBİR test çalıştırılmadı ve HİÇBİR commit
oluşturulmadı. Aşağıdaki test sayıları, verdict'ler ve F1/F2
inceleme-remediasyon kaydı, kullanıcı tarafından sağlanan uygulama ve
bağımsız inceleme raporlarına dayanır; REV2 bunları attribution ile
kaydeder, bu taslak turunun doğrudan gözlemi olarak SUNMAZ. Testler
exact staged blob'lar üzerinde koşmuştur; commit blob'larının o staged
blob'larla SHA-256 düzeyinde birebir eşleştiği, önceki commit turunda
mekanik olarak doğrulanmıştır (bkz. §B) — kanıt bu nedenle commit'li
baytlara aittir. Commit sonrası yeni bir `production-parity` koşusu
kullanıcı kararıyla İSTENMEMİŞTİR: exact staged blob == commit blob
kanıtı ve bağımsız re-review koşumu yeterli kabul edilmiştir.

**Bağımsız inceleme ve remediasyon (gizlenmez)** — İlk bağımsız
inceleme verdict'i, exact olarak: `PHASE A NOT READY — STOP`. İki
Medium bulgu: **F1 (Medium)** — validator, cross-entry duplicate ve
çok-bloklu yıl tamlığında last-wins sözlükler nedeniyle fail-open
davranıyordu; somut risk: aynı ulusal `observance_id`'nin hayalet bir
tarihte tekrar edilmesi kabul edilebiliyor ve bu tarih `holiday_dates`
akışına girerek bir deadline'ı yanlış biçimde ileri kaydırabiliyordu;
çok-bloklu risk: tam bir ikinci blok, eksik birinci bloğu
maskeleyebiliyordu. **F2 (Medium)** — üç UI negatif testi, verified
fixture'ın ilgisiz completeness hataları nedeniyle vacuous biçimde
PASS ediyordu; hedeflenen registry mutasyonunu gerçekten
kanıtlamıyordu. Dar remediasyon YALNIZ iki dosyada yapıldı:
`src/holiday_calendar_validator.py` ve
`ui/tests/test_holiday_calendar_validator_isolated.py`. **F1
kapanışı**: occurrence-list yapısı, yıl-içi ulusal duplicate kontrolü,
dinî `(family, block_index, observance_id)` kontrolü, blok-başına
bağımsız tamlık ve exact block-count sözleşmesi ile. **F2 kapanışı**:
baseline 0 hata → tek mutasyon → spesifik hata → hedef validator
etkisizleştirilince testin FAIL olması → revert ile yeniden geçerli
düzeniyle. Remediasyon sonrası ayrı, bağımsız final re-review
verdict'i, exact olarak: `PHASE A READY FOR COMMIT AUTHORIZATION`.

Hedefli testler:

- `holiday_calendar_validator.py --self-test`: **55/55**
- `test_holiday_calendar_validator_isolated`: **79/79**
- `deadline_calculator.py --self-test`: **27/27**
- `test_deadline_calendar_derivation_isolated`: **44/44**
- `test_deadline_calculator_mali_tatil_isolated` (commit DIŞI,
  regresyon): **60/60**
- `test_deadline_engine_isolated`: **33/33**

Bağımsız final re-review verdict'i, exact olarak:
`PHASE A READY FOR COMMIT AUTHORIZATION`

Resmî `production-parity` (gerçek disposable PostgreSQL, migration
0001–0005): exit 0, `completed` / `SWEEP FULL`, **78/78 modül PASS**,
**6111 passed, 0 failed, 8 counted skip, 14 informational skip**,
guard `armed 212 = expected 212`, positive controls 10/10, protected
manifest temiz, secret scan 0 isabet, residue/refusal/warning yok.

**H. Residual sınırlar (kapatılmış gösterilmez)**

1. Üretim takvimi hâlâ BOŞ ve `verified` DEĞİLDİR (bkz. §D);
   `next_business_day_if_holiday` policy'li tek aktif kural, avukat en
   az bir yılı doğrulayıp `verified:true` yapana kadar hiçbir gerçek
   dosyada `calculated` tarih ÜRETMEZ (Adım 5 sınırı AYNEN geçerli).
2. Phase B, gerçek avukat `verification_ref`'i olmadan BAŞLAYAMAZ:
   **NOT STARTED / NOT AUTHORIZED / BLOCKED ON REAL LAWYER verification_ref**.
3. Saf legacy `verified:true` bir yıl `observances[]` taşımıyorsa yeni
   tamlık kapısı UYGULANMAZ — kaynakta belgelenmiş, bilinçli uyumluluk
   sınırıdır; legacy structural kontroller devam eder.
4. Validator içindeki bazı "V1" metinleri (modül başlığı, hata-mesajı
   öneki, `main()` banner'ları, self-test fixture `notes` metni,
   argparse `description`) kozmetik Low kaydıdır; davranışsal
   sürüm `HOLIDAY_CALENDAR_VALIDATOR_VERSION = "2"`dir ve self-test
   başarı banner'ı zaten `V2: 55/55 PASS` der. `calendar_id`
   const'ındaki `_v1` kimlik literalidir, bu maddenin KAPSAMINDA
   DEĞİLDİR.
5. Aynı kayıt içi duplicate `observance_id` hata metninde ifade
   tekrarı bulunabilir; fail-closed davranışı ETKİLEMEYEN Low kaydıdır.
6. `calendar_version` değişikliği, takvim baytları `input_digest`'e
   girdiği için deadline generation identity'lerini tasarım gereği
   değiştirir (yeni, bağımsız deneme) — kalıcı `IdempotencyConflict`
   DEĞİLDİR (Row 19C-3c-i / Adım 5 ruleset-provisions-takvim emsaliyle
   aynı sınıf).
7. `.gitattributes` yalnız `*.json`/`*.json.pending` için `eol=lf`
   zorlar; genel `*.py text eol=lf` kuralı YOKTUR. Bu nedenle Windows
   working-tree'de CRLF artefaktı oluşabilir (bu tur,
   `src/deadline_calculator.py`'nin working-tree kopyasında 5064 CR
   baytı gözlemledi; `core.autocrlf=true` altında `git status`
   temizdir). Commit blob'larının 7'si de LF'dir (0 CR — commit öncesi
   ve sonrası ayrı ayrı doğrulandı). Ayrı bir backlog konusudur; bu
   turda `.gitattributes` DEĞİŞTİRİLMEDİ.

**I. Kapsam dışı / başlamamış** — Bu checkpoint aşağıdakilerin
HİÇBİRİNE dosya-yazma, veri girişi veya implementasyon yetkisi VERMEZ:
Phase B (2024–2035 resmî tatil tarihlerinin/gözlemlerinin üretime
girişi, `source_refs`, herhangi bir yılın `verified:true` yapılması,
`verification_ref`); üretim `half_day_policy`'nin `not_decided`'dan
başka bir değere alınması (avukat kararı); Adım 6'nın kalan
soruları/altın örnekleri; Adım 7'nin mali tatil dışındaki kalan alt
kapsamları; Adım 8–13; `.gitattributes` EOL politikası; Row 19D; push.

**J. §9 LOCKED-file gerekçesi** — `src/deadline_calculator.py` (LOCKED
Row 8; Adım 5 ve Adım 7'de de dar biçimde açılmıştı): kullanıcı talebi
(Phase A onayı) + downstream uyumluluk (şema v2'nin additive
`observances[]`/dördüncü politikasının hesaplayıcı tarafından
tüketilmesi zorunludur, aksi halde şema ile hesap birbirinden kopar) +
fail-closed güvenlik (yalnız-yarım-günlük bir final gün otomatik kesin
tarih üretmemeli). Değişiklik additive'dir (deadline dalında sıfır
silme); diğer üç politika, adli tatil/mali tatil sırası, takvim-kapsam
kapısı ve `calculation_state` sözlüğü DEĞİŞMEDİ.
`data/holiday_calendar.schema.json`,
`data/holiday_calendar/holiday_calendar.json`,
`src/holiday_calendar_validator.py` (Adım 5 LOCKED): Phase A'nın
doğrudan nesneleridir; şema değişikliği additive (üç eski politika ve
legacy flat kayıt korunur), üretim registry'sinde yalnız sürüm değeri
değişir, validator yalnız yeni model için EK kontroller kazanır. Üç
test dosyası yalnız additive/tutarlılık kanıtı aldı; hiçbir mevcut
assertion gevşetilmedi. Bunların DIŞINDA hiçbir LOCKED dosya bu
commit'te açılmadı.

**K. Sayaçlar** — `ui/tests/test_*.py` modülü **78 → 78** (değişmedi);
production Python (tracked `*.py` − `ui/tests/**`) **157 → 157**
(değişmedi; Phase A yeni dosya eklemedi); migration **5 → 5**; merged
reconciliation routing key (50), logical mutation family (38), CLI
subcommand (6) — önceki checkpoint'ten aktarılır ve bu commit hiçbir
facade/registry/CLI/migration dosyasına dokunmadığı için yapısal olarak
DEĞİŞEMEZ; `data/holiday_calendar/holiday_calendar.json`
`calendar_version` **1 → 2**; `HOLIDAY_CALENDAR_VALIDATOR_VERSION`
`"1"` → `"2"`; şema title V1 → V2; `schema_version` const **1 → 1**.

**L. Süreç notu (gizlenmez)** — Bu roadmap-lock taslağı turu hiçbir
test çalıştırmadı ve hiçbir commit oluşturmadı. REV2, kullanıcı
tarafından sağlanan F1/F2 uygulama ve bağımsız inceleme sonuçlarını
attribution ile kaydeder; bunları bu taslak turunun doğrudan gözlemi
olarak sunmaz. §E'deki REV4.1 atfı commit'li kaynak kodun kendi
yorumundan alınmıştır. Commit, önceki commit turunda kullanıcının açık
yetkisi ve hash-doğrulamalı preflight sonrasında, body/trailer
eklenmeden oluşturulmuştur.

**Bağımsız final re-review verdict'i (exact)**:

`PHASE A READY FOR COMMIT AUTHORIZATION`

**DONE / LOCKED** — yalnız "Holiday Calendar Schema V2 — Phase A
Technical Plumbing" alt kapsamı için. **Phase B:
NOT STARTED / NOT AUTHORIZED / BLOCKED ON REAL LAWYER verification_ref.**

*(Bu iki satır Phase A LOCK anının TARİHSEL kaydıdır ve bilinçli olarak
DEĞİŞTİRİLMEMİŞTİR. Phase B o turda gerçekten başlamamıştı. Güncel durum
için bir sonraki bölüme bakın: Phase B artık DONE / LOCKED'dır ve bu iki
satırı SUPERSEDE eder.)*

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production dosyasına dokunmaz.

### Holiday Calendar Phase B — Veri Popülasyonu + Portable QA/Case-View Publisher'ları (DONE / LOCKED — checkpoint özeti)

**A. Kapsam ve commit'ler** — Phase B, Phase A LOCK commit'i `fa6874a`'dan
HEAD'e kadar **DÖRT yerel commit**tir; hiçbiri push EDİLMEMİŞTİR:

| Commit | Subject | Dosya |
|---|---|---|
| `9773ffd` | Populate lawyer-verified 2024-2035 holiday calendar | 6 |
| `073fc6b` | Pin root gitignore to LF in clean checkouts | 1 |
| `1c7d956` | Add portable QA locator and coordinated QA/case-view pending publishers (Commit A) | 20 |
| `dcba4db` | Regenerate case_0001 QA and case-view snapshots via coordinated publishers (Commit B) | 12 |

Doğrulanan hedef commit (kullanıcı onayında exact olarak verilen):
`dcba4db3c342f8535458b55c57899068b466eae4`, parent
`1c7d956eecb0034bfa0137a430494a367cc730ae`, branch `claude-dev`.
`fa6874a..dcba4db` birleşik exact değişiklik: **10 YENİ + 25
DEĞİŞTİRİLMİŞ = 35 dosya** (bir test dosyası iki commit'te yer aldığı
için 6+1+20+12=39 commit-başı satırı 35 benzersiz dosyaya indirgenir).
**Sıfır migration** (5'te kaldı), sıfır web route, sıfır yeni CLI
subcommand, sıfır cloud/Entra değişikliği.

**B. Üretim takvimi artık popüle ve doğrulanmış** — Phase A'nın "üretim
takvimi HÂLÂ TARİHSİZDİR" iddiası bu turla SUPERSEDE edilmiştir.
`data/holiday_calendar/holiday_calendar.json`'ın canlı durumu, bu
roadmap-lock turunda commit'li baytlardan mekanik olarak yeniden
sayılmıştır:

| Alan | Phase A (`fa6874a`) | Phase B (`dcba4db`) |
|---|---|---|
| `schema_version` (const) | **1** | **1 (DEĞİŞMEDİ)** |
| `calendar_version` | 2 | **3** |
| yıl sayısı | 12 (2024–2035) | **12 (2024–2035)** |
| `verified: true` yıl | **0** | **12** |
| non-null `verification_ref` | 0 | **12** |
| toplam tatil girdisi | **0** (`holidays: []`) | **205** |
| `observances` taşıyan girdi | **0** | **205 (tamamı)** |
| `source_refs` toplamı | **0** | **24** |
| `half_day_policy` | `not_decided` | **`needs_review_if_deadline_day`** |
| `verifications` kaydı | (alan YOK) | **1** |

Yani Phase A'da şema ve hesaplayıcı düzeyinde MEVCUT ama üretimde
BENİMSENMEMİŞ olan dördüncü half-day politikası artık üretimde
BENİMSENMİŞTİR. Şema `title` `V2`→`V2.1` (kozmetik), `schema_version`
`const` **1** ve top-level `required` (10 anahtar) ile
`half_day_policy` enum'u (4 değer) DEĞİŞMEDİ; `$defs` **4 → 9**
(eklenen: `referenced_source_artifact`, `signed_artifact`,
`verification_record`, `verification_scope`, `verifying_lawyer`).
`HOLIDAY_CALENDAR_VALIDATOR_VERSION` `"2"` → **`"3"`**.

**C. İmzalı avukat artefaktı — bağlama PASS, sınır AYNEN korunur** —
Takvimin tek `verifications` kaydı repo DIŞINDA tutulan imzalı bir
avukat dosyasına bağlıdır ve bağlama, temiz exact-commit worktree'sinin
KENDİ validator'ıyla (dosya worktree'ye veya repoya KOPYALANMADAN,
salt-okunur) doğrulanmıştır: boyut **9182**, SHA-256
**`fb79b85fcf114c951f3f08a03a437e867430ecbf6cca0f477d77b9df6fd364e2`**,
validator **exit 0**, `ok: True`, **12/12 yıl verified**, tek kayıt
`HC-LAWYER-VERIFY-v1-2024-2035-fb79b85fcf114c95`, `final_decision
KABUL`, `half_day_policy_decision needs_review_if_deadline_day`.

**Sınır (aynen korunur, genişletilmez):** ham kriptografik imza ve gömülü
sertifika CN'i daha önce doğrulanmıştır; **sertifika zinciri ile OCSP/CRL
iptal durumu bağımsız doğrulanmış SAYILMAZ.** Bu dosya git'e
GİRMEMİŞTİR — commit ağacında hiçbir
`.udf/.sgn/.p7s/.pem/.cer/.crt/.pfx/.der/.p12` dosyası yoktur ve 12
commit dosyasının hiçbirinde sertifika/imza yükü (`-----BEGIN`, `BEGIN
CERTIFICATE`, `PKCS7`, `sign.sgn`) bulunmaz.

**D. Row 16/17 için İLK resmî pending publisher'ları** — Row 19A'nın
"QA/Orchestrator pending-generation publisher'ları şu an YOK —
belgelenmemiş operasyonel boşluklardır" tespiti bu turla KAPANMIŞTIR.
Commit A iki YENİ, case-scoped, **deterministik-only** action family
ekledi: **`generation.qa`** ve **`generation.case_view`**. Bunlar
YEDİNCİ, AYRI bir facade/adapters çiftiyle
(`ui/services/qa_case_view_generation_mutation_facade.py` +
`..._adapters.py`, ikisi de YENİ) mutation coordinator/journal
altyapısına bağlandı — **önceki altı çiftin HİÇBİRİ GENİŞLETİLMEDİ**.
Bu iki aile için **agent modu YOKTUR** (deterministik-only
publisher'lar); mevcut `generation` CLI subcommand'ı yeni `qa`/
`case_view` row key'leriyle additive olarak genişletildi, YENİ bir
subcommand EKLENMEDİ. Ayrıca Commit A, Row 16'nın QA locator'ını
**repo-relative (portable)** hale getirdi.

**E. Sabit sayımlar (Phase A → Phase B), mekanik olarak doğrulanmış**:

| Sayaç | Phase A | Phase B |
|---|---|---|
| `ui/tests/test_*.py` modülü | 78 | **80** |
| `*_postgres` modülü | 14 | **15** |
| merged reconciliation routing key | 50 | **52** |
| logical action family | 38 | **40** |
| production Python (tracked `*.py` − `ui/tests/**`) | 157 | **159** |
| `db/migrations/*.sql` | 5 | **5 (DEĞİŞMEDİ)** |
| CLI subcommand | 6 | **6 (DEĞİŞMEDİ)** |

**Bağlayıcı not:** sweep artık **80 modül ve 15 `*_postgres`**'tir. Eski
**78/78 ve 14** beklentisi `073fc6b` ve öncesine aittir ve
**BAYATTIR** — Commit A (`1c7d956`) tam olarak
`test_qa_case_view_generation_mutation_facade_isolated.py` ve
`..._integration_postgres.py` modüllerini EKLEMİŞTİR (git ile
türetilmiştir, varsayılmamıştır). Bundan sonraki hiçbir turda 78/78 veya
14 beklentisi kullanılmamalıdır; 80 ile 78 arasındaki fark bir
BAŞARISIZLIK DEĞİLDİR.

**F. Resmî kapılar — `dcba4db` baytlarına karşı** — Değiştirilmemiş
`scripts/run_ui_tests.py`, modül seçimi/atlaması olmadan, tek ve
kesintisiz, TEMİZ bir exact-commit worktree'sinde (detached,
`-c core.autocrlf=false -c core.eol=lf`, ana repoda hiç test
çalıştırılmadan) ve taze/disposable bir **PostgreSQL 16.15** örneğinde
(yalnız loopback, yeni port, migration **0001-0005** sırasıyla
`ON_ERROR_STOP=1` ile worktree'nin kendi `db/migrations/`'inden)
çalıştırıldı:

- **`production-parity`**: `runner_exit_code 0`, `state completed`,
  `SWEEP FULL`, **80/80 modül PASS** (`modules_non_pass 0`,
  `modules_not_spawned 0`), **6400 passed, 0 failed**, 8 counted / 14
  informational skip (hiçbir skip PASS SAYILMADI); discovery
  `tracked_count 80 == run_count 80`, `missing []`, `untracked []`,
  `rejected []`; guard `armed_count 214 == expected_armed 214`,
  `inheritance_ok true`, positive controls **10/10**,
  `net_blocked_count 0`, `env_open_blocked_count 0`,
  `suspicious_popens []`; PostgreSQL `connected true`,
  `migrations_ok true`, `migrations_missing []`,
  `server_addr_loopback true`; **15/15 `*_postgres` modülü GERÇEKTEN
  koştu** (sıfır zero-check); `protected_manifest_ok true` (377 giriş),
  `protected_path_diff []`, `secret_scan` 160 dosya `hits []`; tüm
  residue listeleri (`process`/`temp`/`db`/`bytecode`) boş,
  `tmp_dir_removed true`; `refusals []`, `warnings []`; `git.clean true`,
  `git.head dcba4db3c342f8535458b55c57899068b466eae4`. stderr boş.
  `deviations`: 3 girdi — runner'ın kendi tasarım davranışının
  dokümantasyonu (child `TEMP`→`vsw_<pid>`, NESTED_RUNNER V2 exclusion
  penceresi, K.1 kuralı); kapı alanı DEĞİLDİR, başarısızlık DEĞİLDİR.
- **`rag-dependency`**: exit **0**, **`RAG_GATE_PASS`**, 3/3 modül PASS,
  **216 passed, 0 failed**, counted skip **0**, informational ham **1** /
  K.1-muaf **1** / **etkin 0**, `marker_present true`, guard 7/7 ve
  10/10, integrity temiz. Dürüst disclosure: `.venv` gitignore'lu olduğu
  için temiz worktree'de yoktur; interpreter MUTLAK yolla, cwd =
  worktree olarak çağrılmıştır (runner interpreter'ı yola göre değil
  yeteneğe göre doğrular).

**G. Post-commit bağımsız doğrulama turu** — Ayrı, salt-okunur bir tur
12 commit blob'unun SHA-256'sını (hepsi **CR=0**) gerçek önceki commit
raporuyla birebir eşleştirdi; `data/cases` tracked 71 == on-disk 71;
`qa.json` ≡ pending'i (`dad0e73b…`) ve `case_view.json` ≡ pending'i
(`6bbd518f…`) bayt-bayt aynı; `case_view`'ın `dependency_manifest`'i
canlı `qa.json` digest'ini (`dad0e73b…`) bağlıyor ve 11 girdinin
10'unun digest'i diskteki baytlarla eşleşiyor (`evidence` doğru şekilde
`absent`); her iki generation audit'in `history_backup_path`'i
**repo-relative**; **13 tarihsel audit kaydının TAMAMI bayt-bayt
DEĞİŞMEDİ** (diff 6 A + 6 M'dir, hiçbiri audit değildir, ve 13'ünün her
biri `parent → HEAD` blob-hash'iyle ayrıca doğrulandı); 6 yeni
provenance dosyası mevcut; commit ağacında **sıfır `.bak`**; 12 dosyanın
hiçbirinde geçici-worktree yol token'ı yok. Final verdict, exact olarak:
`PHASE B POST-COMMIT GATES PASS — READY FOR ROADMAP LOCK`

**H. Non-blocking / deferred hygiene notu (bu turda DÜZELTİLMEDİ)** —
Commit B'nin eklediği iki `*.generation_audit.json` dosyası, yeni
publisher'lar tarafından **platform (CRLF) satır sonlarıyla** ve
sondaki newline olmadan yazılmıştır; kardeş yazıcıları
(`history/*.json.pending`, `*.approval.json`) LF yazar.
`.gitattributes`'in `*.json text eol=lf` kuralı bunları commit anında
LF'e normalize etti, bu yüzden blob'lar LF'tir (`a1d7375c…`,
`74027038…`) ama **ana repo çalışma kopyaları CRLF kalır** (135 / 161
CR; disk `4335fc42…` / `4e097729…`) ve `git status` bunu yine de temiz
sayar. Fark **YALNIZCA EOL kaynaklıdır, sıfır içerik değişikliği**
vardır (blob'un LF'lerini CRLF'e çevirmek çalışma-kopyası hash'lerini
birebir yeniden üretir). Bu turun kapılarında ve reconciliation
adapter'larında (audit'in KENDİ hash'ini değil İÇERİĞİNİ ayrıştırır)
hiçbir kontrol bu iki dosyanın ham SHA-256'sına dayanmaz; ancak
ileride bu iki dosyanın ham SHA-256'sını pinleyen bir test yazılırsa
ana ağaç ile temiz checkout arasında sapma oluşur — F1'in daha önce
kapattığı sınıfın aynısı. **Yazıcı-tutarlılığı backlog maddesi olarak
AÇIK kalır; bu turda düzeltilmemiştir.**

**I. Kapsam dışı / kapanmayanlar** — Bu LOCK YALNIZ takvim verisi
popülasyonunu, portable QA locator'ı, iki yeni deterministik publisher'ı
ve yukarıdaki dört commit'in kapılarını kapsar. Kapanmayanlar:
**Adım 6** — takvim alt-maddesi karşılandı, ancak SORU 3.1-3.8 /
5.1-5.4 ve altın örnekler TAMAMLANMADI, **Adım 6 ACTIVE / NEXT olarak
KALIR**; Adım 7'nin mali tatil DIŞINDAKİ alt-kapsamları;
`stopping_event_status`; 27.01.2016 öncesi mali tatil temporal
modellemesi; Adım 8 yerel PostgreSQL/IAM adoption; Adım 9 sentetik
concierge dry-run; Adım 10 ilk gerçek concierge pilotu; Adım 11
Entra/P1; Adım 12 hosting/Key Vault; Adım 13c configurable case root;
corpus politikası/edinimi/population ve RAG-bağımlı Slice 2; Row 19D
(OS ACL / service identity / TOCTOU, advisory-lock timeout backlog'u).
Pilotun genel olarak production-ready olduğu **İDDİA EDİLMEZ**.

**J. §9 LOCKED-file gerekçesi** — Phase B, LOCKED Row 8'in
`src/holiday_calendar_validator.py`'sini ve Phase A'da kilitlenen
`data/holiday_calendar.schema.json` / `holiday_calendar.json`'ı, Phase
A'nın kendi sözleşmesinin ZORUNLU kıldığı veri popülasyonu için açtı
(kullanıcı talebi + Phase A'nın açık prerequisite'i: "BLOCKED ON REAL
LAWYER verification_ref" — o önkoşul bu turda sağlandı). Şema
değişikliği additive'dir (`schema_version` const 1, top-level
`required` ve `half_day_policy` enum'u DEĞİŞMEDİ; yalnız 5 yeni `$def`).
LOCKED Row 16/17 tarafında `src/qa_engine.py`, `src/qa_discovery.py`,
`src/qa_approval.py`, `src/orchestrator_engine.py`,
`src/orchestrator_approval.py` yalnız portable locator ve resmî
pending-publisher seam'i için açıldı — Row 19A'nın "var olan saf
builder/validator fonksiyonlarını yeniden kullan, domain mantığını
DEĞİŞTİRME veya KOPYALAMA" şartıyla; `ui/cli_mutate.py` ve
`ui/reconciliation_operator.py` yalnız additive (19C-3b'den beri kabul
edilen açılış sınıfı). Bunların DIŞINDA hiçbir LOCKED dosya açılmadı.

**K. Final verdict**

`PHASE B POST-COMMIT GATES PASS — READY FOR ROADMAP LOCK`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren, salt-okunur bir roadmap-lock
işlemidir; hiçbir kaynak/migration/test/production/canonical/pending/
provenance dosyasına ve 13 tarihsel audit kaydına dokunmaz; `dcba4db`
commit'i amend EDİLMEZ; stash/reset/cleanup/push YAPILMAZ.

### Adım 6 — Altın Örnek Diferansiyel Doğrulama (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve exact kapsam** — Avukatın doldurduğu DRAFT-4 belgesindeki 14
altın örneğin (Bölüm 4-B S01-S12, Bölüm 4-C S13, Bölüm 4-D A-1), üretim
`src/deadline_calculator.py` zincirine karşı mekanik olarak
karşılaştırılmasıdır. Exact uygulama kapsamı: **1 YENİ + 0 DEĞİŞTİRİLMİŞ =
1 dosya**.

| | |
|---|---|
| Yeni dosya | `ui/tests/test_deadline_lawyer_golden_examples_isolated.py` |
| SHA-256 | `4efa0815676acdc83a37757f7467a3b64bab5394671f473c1ee5401057fecd5f` |
| Boyut / satır | 19.025 bayt · 499 satır · saf LF (0 CR) |
| Commit | **`2ba8f11e4116819b76db8e02ee870c2003e09e90`** (parent `34cc7748afb1bc54c8c0562ca0ea4ca2ad478b3a`) |

Sıfır üretim kodu, sıfır şema, sıfır migration, sıfır `data/`, sıfır mevcut
test değişikliği, sıfır web/CLI yüzeyi. Test SALT-OKUNURDUR: case dizini,
PostgreSQL, mutation coordinator, ağ/API ve gerçek müvekkil verisi
KULLANILMAZ; tüm senaryolar sentetiktir.

**B. Provenance (kullanıcının bağlayıcı kararı)** — Kaynak, repo DIŞINDA
saklanan `burki_avukat_dogrulama_paketi_DRAFT4_DOLDURULABILIR (1).docx`,
SHA-256 `dcf4df690bf8298830a3e19b9041d148cb331ccd198f16bceb73129cf186ecd1`.
DRAFT-4 **avukat tarafından incelenmiş/onaylanmış hukuki girdidir**; yeniden
provenance formu İSTENMEYECEKTİR. **DRAFT-4 e-imzalı DEĞİLDİR ve öyle
GÖSTERİLMEZ** — belge içinde imza, değişiklik izleme veya yorum kaydı yoktur;
kullanıcı tarafından teyit edilen avukat-onaylı kaynak olarak kaydedilir.
E-imzalı tek artefakt takvim doğrulamasıdır (`verification_ref
HC-LAWYER-VERIFY-v1-2024-2035-fb79b85fcf114c95`). Hazırlanan `LAWYER-CONFIRM`
ek teyit formu taslakları (v3/v4/FINAL/FINAL_WORD) **kullanılmamıştır,
canonical kanıt DEĞİLDİR ve bloklayıcı/yapılacak iş olarak BIRAKILMAMIŞTIR**.
Her iki kimlik de test dosyasının başlık bloğunda provenance notu olarak
kayıtlıdır.

**C. İki bağlayıcı yorum kararı** — **S05 (yarım gün):** DRAFT-4 SORU 3.4
"süre o gün dolar" demiş ve tabloya `28.10.2026` yazmıştır; buna karşılık
**26.09.2026 tarihli, DAHA SONRAKİ ve e-imzalı** takvim doğrulaması yarım gün
politikası olarak `needs_review_if_deadline_day` KABUL etmiştir. **Sonraki
tarihli imzalı politika ÜSTÜNDÜR**: beklenen sonuç kesin tarih DEĞİL,
fail-closed `needs_review` + sabit `reason =
holiday_calendar_half_day_deadline_requires_review`tir; `28.10.2026` yalnız
insan onayına sunulacak değer olarak kayıt altındadır. **S11 (Cumartesi):**
DRAFT-4 tablosu `07.09.2030` yazmıştır, ancak o gün **CUMARTESİ**dir; avukatın
KENDİ onayladığı **SORU 5.4** kuralı gereği İYUK m.8/2 devreye girer ve son
gün **`09.09.2030` PAZARTESİ**dir. Tablodaki `07.09.2030` bir
**aritmetik/yazım hatasıdır** ve KULLANILMAZ.

**D. 14 senaryo ve sonuçları — 14/14 PASS**

| Case | Anchor | Beklenen | Mekanizma |
|---|---|---|---|
| S01 | 2026-02-10 | 2026-03-12 | düz 30 gün |
| S02 | 2026-01-15 | 2026-02-16 | m.8/2 (Cmt) |
| S03 | 2026-01-16 | 2026-02-16 | m.8/2 (Paz) |
| S04 | 2026-12-02 | 2027-01-04 | m.8/2 (Yılbaşı) |
| **S05** | 2026-09-28 | **`needs_review`** + `holiday_calendar_half_day_deadline_requires_review` | yarım gün, imzalı politika |
| S06 | 2026-09-29 | 2026-10-30 | m.8/2 (tam gün bayram) |
| S07 | 2026-06-19 | 2026-09-07 | mali tatil + m.8/3 |
| S08 | 2026-06-20 | 2026-09-07 | mali tatil + m.8/3 |
| S09 | 2026-08-01 | 2026-09-07 | m.8/3 |
| S10 | 2026-08-02 | 2026-09-01 | m.8/3 UYGULANMAZ (SORU 5.2 ayrımı) |
| **S11** | 2030-07-01 | **2030-09-09** | mali tatil + m.8/3 + m.8/2 |
| S12 | 2028-01-30 | 2028-02-29 | artık yıl, tatil yok |
| S13 | 2032-12-03 | 2033-01-05 | dinî bayram zinciri |
| A-1 | 2029-03-22 | 2029-04-30 | hafta sonu + ulusal + Kurban zinciri |

S07-S11'de `judicial_recess_applicable=True` AÇIKÇA geçirilir. Hiçbir senaryo
skip/xfail/karantina DEĞİLDİR. **Hiçbir senaryoda sapma çıkmamıştır — üretim
koduna yama GEREKMEMİŞ ve YAPILMAMIŞTIR.**

**E. Modülün tamamı: 48/48** — 14 altın örneğin yanında 4 ön koşul (takvim
2024-2035 kapsamı, kuralın m.8/3 + 5604 dayanakları, 2026-10-28'in gerçekten
yalnız-yarım-gün olması — tautolojik geçişi önler), 13 mekanizma-atfı kontrolü
(`mali_tatil_applied` / `judicial_recess_applied` /
`holiday_adjustment_applied` / `provisional_deadline=2030-09-07`), 14
determinizm kontrolü ve `data/` bayt-değişmezliği.

**F. Kanıt — commit `2ba8f11` baytlarına karşı iki resmî kapı** — Temiz,
detached, exact-commit LF worktree'sinde; gerçek, disposable **PostgreSQL 16**
(yalnız loopback, migration 0001-0005):

- **`production-parity`**: `runner_exit_code 0`, `state completed`, `SWEEP
  FULL`, **81/81 modül PASS** (`outcomes {"PASS": 81}`, `modules_non_pass 0`,
  `modules_not_spawned 0`), **6448 passed, 0 failed**, 8 counted skip, 14
  informational skip. `git.head 2ba8f11…`, `git.clean true`,
  `tracked_test_count 81`; discovery `tracked 81 / filesystem 81 / run 81`,
  `missing [] untracked [] rejected []`. PostgreSQL `connected true`,
  `migrations_ok true`, `migrations_missing []`, `server_addr_loopback true`;
  **15/15 `*_postgres` modülü GERÇEKTEN koştu** (hepsi PASS, `passed > 0`).
  Guard `armed 215 = expected 215`, `inheritance_ok true`, `net_blocked 0`,
  `env_open_blocked 0`, positive controls **10/10**, `suspicious_popens []`.
  Integrity `protected_manifest_ok true` (**378 giriş**),
  `protected_path_diff []`, secret scan 162 dosya `hits []`, process/temp/db/
  bytecode residue hepsi `[]`; `refusals []`, `warnings []`,
  `tmp_dir_removed true`. Yeni modül sweep içinde: `PASS passed=48 failed=0`.
- **`rag-dependency`**: `SWEEP RAG_GATE_PASS`, exit 0, **3/3 modül PASS**,
  **216 passed, 0 failed**, `informational_skips_effective 0` (ham 1, K.1
  platform muafiyeti 1), `marker_present true`, guard 10/10, integrity temiz.

Disposable PostgreSQL kümesi ve geçici worktree işlem sonunda tamamen
kaldırıldı; `data/`, `src/`, `index/`, `db/` ve `CLAUDE.md` commit öncesine
göre DEĞİŞMEDİ.

**G. Sabit sayımlar** — `ui/tests/test_*.py` modülü **80 → 81**;
`*_postgres` modülü **15 → 15 (DEĞİŞMEDİ)**; protected manifest girdisi
**378**; production Python **159 → 159 (değişmedi)**; migration **5 → 5**;
merged reconciliation routing key **52**, logical action family **40**, CLI
subcommand **6** — hiçbiri değişmedi (bu tur hiçbir facade/registry/CLI/
migration dosyasına dokunmadı).

**H. Disclosure — DRAFT-4'te boş kalan alanlar (bloklayıcı DEĞİL, yapılacak
iş olarak BIRAKILMAMIŞTIR)** — Dürüstlük gereği kaydedilir; kullanıcı kararı
uyarınca bunlar için ek avukat formu İSTENMEYECEKTİR: SORU 3.8'in
`Kanıt/kaynak` ve `Belgeleme biçimi` alt-alanları DRAFT-4'te boştur (ancak
usul 26.09.2026'da FİİLEN uygulanmıştır: e-imzalı belge + SHA-256/kapsam
kaydı); S13'ün üç alt sorusu ve gerekçe alanı boştur (S13 satırının kendisi
dolu ve takvime karşı doğrulanmıştır); Bölüm 4-D'de istenen 3-5 ek
senaryodan 1'i (A-1) gelmiştir (A-1 doğrulanmıştır); SORU 5.6'nın soru metni
DRAFT-4'te teknik bir hatayla kaybolmuştur ve `BEKLİYOR / ONAYLANDI /
OVERRIDE` işareti belirsizdir (5.6, `CLAUDE.md`'nin Adım 6 ölçütü olan
SORU 5.1-5.4 aralığının DIŞINDADIR).

**I. Bu LOCK'un KAPSAMADIĞI** — Adım 7'nin mali tatil dışındaki kalan
deadline hardening alt-kapsamları (`stopping_event_status`, SORU 5.5'in
tarihsel çalışmaya-ara-verme dönemleri, VUK m.35/376 ve uzlaşma/usulsüz
tebligat gibi süre başlangıcını/işleyişini değiştiren hâller); Adım 8-13;
DRAFT-4 Bölüm 6'nın dış sağlayıcıya aktarım (KVKK/DPA/veri lokasyonu)
soruları ve 6.4'ün 9 hard-block belge sınıfı; corpus acquisition/population;
Row 19D. **Bu LOCK, pilotun genel olarak production-ready olduğunu,
yazılımın hukuken hatasız olduğunu veya gerçek bir dosyada kullanıma hazır
olduğunu İDDİA ETMEZ** — yalnız 14 sentetik avukat örneğinin, üretim
hesaplayıcısının bugünkü davranışıyla mekanik olarak uyuştuğunu kayda geçirir.

**J. Final verdict**

`POST-COMMIT GATES PASS — READY FOR ROADMAP UPDATE`

**DONE / LOCKED**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren bir roadmap-lock işlemidir; hiçbir
kaynak/migration/test/production/canonical/pending dosyasına dokunmaz;
`2ba8f11` commit'i amend EDİLMEZ; stash/reset/cleanup/push YAPILMAZ.

### Adım 7 / Slice 1 — Stopping-Event Attestation Gate (DONE / LOCKED — checkpoint özeti)

**A. Amaç ve pilot blocker** — Bir bildirimin/tebliğin ARDINDAN, süreyi
durdurabilecek, kesebilecek veya başlangıcını değiştirebilecek bir işlemin
(uzlaşma başvurusu, düzeltme şikâyeti vb.) bulunup bulunmadığı BİLİNMEDEN,
sistem yine de kesin bir son gün üretebiliyordu. Slice 1 bunu fail-closed
bir kapıyla engeller: böyle bir işlemin YOKLUĞU AÇIKÇA beyan edilmedikçe
hiçbir kesin tarih üretilmez (Prensip 9 — belirsizlik → hesaplama yok,
onay bekle). Slice 1 hiçbir olayın hukuki aritmetiğini MODELLEMEZ (bkz. §H).

**B. Exact kapsam — iki commit**

| | Implementasyon | Remediasyon |
|---|---|---|
| SHA | `3f80945968f1429b39b47b69d7860934a5bb17b5` | `7428d00638cec619c7e2b0d6b8a74aa35f00896a` |
| subject | `Add fail-closed stopping-event attestation gate` | `Pass stopping-event attestation in fact verification integration` |
| parent | `5bffcb6e8974994464cdcdb0685058c5d8bfec94` | `3f80945968f1429b39b47b69d7860934a5bb17b5` |
| kapsam | **1 YENİ + 8 DEĞİŞTİRİLMİŞ = 9 dosya** | **0 YENİ + 1 DEĞİŞTİRİLMİŞ = 1 dosya** |
| diff | 1555 insertion / 5 deletion | 6 insertion / 0 deletion |
| body/trailer | yok | yok |

Implementasyon dosyaları: `src/deadline_calculator.py` (**LOCKED Row 8**),
`src/deadline_engine.py` (**LOCKED Row 8**), `ui/cli_mutate.py`,
`ui/services/generation_mutation_facade.py`,
`ui/tests/test_deadline_stopping_events_isolated.py` (**YENİ**),
`ui/tests/test_deadline_calculator_mali_tatil_isolated.py`,
`ui/tests/test_deadline_engine_isolated.py`,
`ui/tests/test_cli_mutate_isolated.py`,
`ui/tests/test_generation_mutation_facade_isolated.py`. Remediasyon dosyası:
`ui/tests/test_fact_verification_mutation_integration_postgres.py`.
**Sıfır** schema, migration, `data/`, web route, cloud/Entra değişikliği;
her iki commit de yalnız YEREL — **push YAPILMADI**.

**C. Kaydedilen sözleşme (fail-closed)** — `stopping_event_status ∈ {none,
present, unknown}`; `stopping_event_attestation_ref: string | null`
(printable, 1-200 karakter, CR/LF/kontrol karakteri yok).

| Girdi | Sonuç |
|---|---|
| `none` + geçerli ref + case çelişkisi yok | **hesaplamaya DEVAM** |
| `none` + eksik/geçersiz ref | `needs_review` / `stopping_event_none_requires_attestation_ref` |
| `none` + `settlement` veya `correction_complaint` sinyali | `needs_review` / `stopping_event_attestation_conflicts_with_case_record` |
| `present` | `needs_review` / `stopping_event_present_requires_lawyer_review` |
| `unknown` **veya parametre hiç verilmedi** | `needs_review` / `stopping_event_status_unknown` |
| CLI'da tanınmayan değer | **exit 2**, herhangi bir mutation/authz/connection/file I/O'dan ÖNCE |

**Kapı sırası:** `blocked_unverified_anchor` → **stopping-event gate** →
deadline hesaplaması. Kapı YALNIZ case-aware `build_deadline_record`
katmanındadır; saf tarih aritmetiği olan `calculate_rule_deadline`'a
YERLEŞTİRİLMEMİŞTİR.

**D. Audit / digest ve bunların DÜRÜST sınırları** —
`generation_parameters_digest` `digest_version`
`row19c3ci.deadline_params.v3` → **`v4`**; digest girdileri:
`judicial_recess_applicable`, `stopping_event_status`,
`stopping_event_attestation_ref`. Generation audit'e HAM olarak eklenen iki
alan: `stopping_event_status`, `stopping_event_attestation_ref`.

Sınırlar (abartılmaz):

- Bu iki alan canonical `deadline.json` içinde **YOKTUR**.
- `case_view`/UI içinde **görünmez**.
- Yalnız **generation audit runtime dosyasında** bulunur; `data/cases`
  gitignore kapsamında olduğundan **git ile versiyonlanmaz**.
- Ref yalnız **biçimsel** olarak doğrulanır; gerçekliği veya gerçekten bir
  avukat tarafından verildiği **DOĞRULANMAZ**.
- Cross-check YALNIZ `action_category` alanındaki `settlement` ve
  `correction_complaint` sinyallerini yakalar; **başka hiçbir olayın
  otomatik tespit edildiği İDDİA EDİLMEZ**.

**E. Remediasyon gerekçesi (dürüst kayıt)** — Implementasyon commit'inin
resmî `production-parity` koşusu **exit 1 / SWEEP PARTIAL** verdi: 82/82
modül spawn edildi, 81 PASS + **1 FAIL**
(`test_fact_verification_mutation_integration_postgres`, 89 passed / **2
failed**, P10l ve P10o). Neden mekanik olarak açıklandı: bu modül Slice
1'in 9 dosyalık kapsamında DEĞİLDİ (`git show --name-only` → 0 eşleşme) ve
P10 zincirinin gerçek deadline CLI çağrısı yeni iki parametreyi HİÇ
geçirmiyordu (dosyada `stopping_event` 0 kez) — dolayısıyla yeni
fail-closed varsayılan gereği `calculation_state='needs_review'`,
`calculated_deadline=None`, `notes='stopping_event_status_unknown'`
(`anchor_verification_state='verified'` iken) üretiliyordu. Kullanıcı
kararıyla (Seçenek a) **production varsayılanı ve kapı GEVŞETİLMEDİ**;
yalnız testin P10 apply çağrısına sentetik olarak
`--stopping-event-status none` ve
`--stopping-event-attestation-ref TEST-P10-SYNTHETIC-NO-STOPPING-EVENT-ATTESTATION`
eklendi. Bu ref **sentetik bir test değeridir; gerçek avukat veya müvekkil
beyanı DEĞİLDİR** ve hiçbir hukuki anlam taşımaz. P10l/P10o assertion
blokları HEAD ile **byte-identical** kaldı (`cmp` ile doğrulandı); `check(`
çağrı sayısı **93 = 93**; sıfır silme; skip/xfail/mock/monkeypatch
eklenmedi; preview çağrısı ve unverified-anchor apply çağrısı
DOKUNULMADI. `--expected-input-digest` geçerliliği korundu — kaynaktan
doğrulandı ki iki parametre `generation_parameters_digest`'e girer,
`_compute_deadline_input_digest`'e **GİRMEZ**.

**F. Resmî kapı kanıtı — exact commit `7428d006`** — Değiştirilmemiş
`scripts/run_ui_tests.py`, modül seçimi olmadan, tek kesintisiz sweep,
TEMİZ detached exact-commit worktree'de (`core.autocrlf=false`,
`core.eol=lf`, başlangıç status'ü `--ignored` dahil tamamen boş, `work/` ve
`vacuum.wav` worktree'de yok) ve taze/disposable PostgreSQL 16.15'te
(yalnız `127.0.0.1`, yeni boş cluster/DB, migration **0001→0005**
`ON_ERROR_STOP=1`, `VERGI_IAM_DATABASE_URL` **UNSET**):

`production-parity`: `runner_exit_code 0`, `state completed`, **SWEEP
FULL**, `outcomes {"PASS": 82}`, `modules_non_pass 0`,
`modules_not_spawned 0`, **6559 passed, 0 failed**, **8 counted skip**,
**14 informational skip**; discovery `tracked=82 / filesystem=82 / run=82`,
`missing=[] untracked=[] rejected=[]`; PostgreSQL `connected=true`,
`migrations_ok=true`, `migrations_missing=[]`,
`server_addr_loopback=true`, **15/15 `*_postgres` modülü GERÇEKTEN koştu**
(hepsi `outcome=PASS`, hepsi `passed>0`, zero-check yok); guard
`armed_count 216 == expected_armed 216`, `inheritance_ok true`, positive
controls **10/10**, `net_blocked_count 0`, `env_open_blocked_count 0`,
`malformed_lines 0`, `suspicious_popens []`; integrity
`protected_manifest_ok true` (**379 giriş**), `protected_path_diff []`,
secret scan **164 dosya, hits []**, `process/temp/db/bytecode residue []`,
`failures []`; `refusals []`, **`warnings []`**, `tmp_dir_removed true`,
`git.clean true`, `git.head 7428d006…`, stderr **0 bayt**.

Özel modüller ve P10 zinciri:

- `test_deadline_stopping_events_isolated`: **69 passed, 0 failed** (YENİ modül)
- `test_fact_verification_mutation_integration_postgres`: **91 passed, 0 failed**
- **P10k, P10l, P10m, P10n, P10o: beşi de PASS**
- gerçek sonuç: `calculation_state = calculated`,
  `calculated_deadline = 2026-03-12`,
  `anchor_verification_state = verified`

`rag-dependency` (yalnız `production-parity` tamamen PASS olduktan SONRA,
aynı temiz worktree'de): `exit 0`, **RAG_GATE_PASS**, **3/3 modül PASS**,
**216 passed, 0 failed**, `counted_skips 0`, informational **ham 1** / K.1
win32 muafiyeti **1** / **etkin 0**, `marker_present true`, guard **7/7** +
positive controls **10/10**, `net 0`, `env 0`, integrity temiz,
`git.head 7428d006…`, `git.clean true`. **K.1 uyarı satırı** (`"rag gate:
K.1 amendment exempted 1 platform-gated informational skip(s) by name on
win32 (test_rag_bundle_builder_isolated=1)"`) sözleşme gereği **bildirilen
platform muafiyetidir — bir gate başarısızlığı DEĞİLDİR** (Adım 3
checkpoint'inde de "muafiyet bir uyarı satırıyla duyuruldu" olarak
kayıtlıdır).

Değişmezlik: ana repo `data/**` **117 dosya, kapılar öncesi/sonrası
SHA-256 manifesti BİREBİR AYNI**; `data/cases` yalnız `case_0001` ve
`git status --porcelain --ignored -uall -- data/cases` **boş** (Adım 2
R11); canonical/pending/generation-audit ve sentetik temp residue **0**;
disposable PostgreSQL durduruldu, portlar boş, cluster dizinleri ve
detached worktree'ler kaldırıldı + `git worktree prune`.

**G. Sabit sayımlar**

| Sayaç | Öncesi | Sonrası |
|---|---|---|
| tracked `ui/tests/test_*.py` | 81 | **82** |
| `*_postgres` modülü | 15 | **15 (değişmedi)** |
| production Python | 159 | **159 (değişmedi)** |
| `db/migrations/*.sql` | 5 | **5 (değişmedi)** |
| merged reconciliation routing key | 52 | **52 (değişmedi)** |
| logical action family | 40 | **40 (değişmedi)** |
| CLI subcommand | 6 | **6 (değişmedi)** |
| protected manifest girdisi | 378 | **379** |

İki yeni CLI seçeneği — `--stopping-event-status` ve
`--stopping-event-attestation-ref` — **yeni subcommand DEĞİLDİR**; mevcut
`generation` subcommand'ının `--row-key deadline` + `--apply` dalına ait
apply-only bayraklardır (preview'da reddedilirler). CLI subcommand sayısı
bu yüzden **6'da kalır**.

**H. Kapsam dışı / AÇIK kalan işler — Slice 1 bunları MODELLEMEDİ**

- uzlaşma süresi ve etkileri
- İYUK m.11 başvurusunun kalan süre / zımni ret hesabı
- VUK m.35/376 kaynaklı başlangıç veya süre değişiklikleri
- usulsüz tebligat / öğrenme tarihi etkileri
- pişmanlık ihlali
- değerleme komisyonu veya eksik matrah temeli
- tarihsel çalışmaya-ara-verme dönemleri / SORU 5.5
- diğer event-specific hukuki aritmetik
- canonical `deadline.json` veya `case_view` görünürlüğü

Bu nedenle: **Adım 7 ACTIVE / NEXT KALIR**; Slice 1'in görevi YALNIZ
fail-closed durdurma ve audit izidir; **Adım 7 DONE/LOCKED DEĞİLDİR**;
Adım 8-13 KAPANMAMIŞTIR; corpus ve Row 19D KAPANMAMIŞTIR; **pilot
production-ready DEĞİLDİR**. Avukata yeni bir form veya yeniden onay
GEREKMEMİŞTİR; DRAFT/LAWYER-CONFIRM formları canonical kanıt DEĞİLDİR ve
yeniden gündeme GETİRİLMEMİŞTİR.

**I. §9 LOCKED-file gerekçesi** — `src/deadline_calculator.py` ve
`src/deadline_engine.py` (LOCKED Row 8; Adım 5, Adım 7-mali-tatil ve
Holiday Calendar Phase A'da da dar biçimde açılmıştı): kullanıcı talebi +
fail-closed güvenlik (durdurucu bir işlemin varlığı bilinmeden kesin tarih
üretilmemesi). Değişiklikler additive'dir; `calculation_state` sözlüğü,
adli tatil/mali tatil sırası, takvim-kapsam kapısı ve saf
`calculate_rule_deadline` aritmetiği DEĞİŞMEDİ.
`ui/services/generation_mutation_facade.py` ve `ui/cli_mutate.py` Row
19C-3c-i/3b lineage'ındadır ve her slice'ta additive olarak
açılagelmiştir (19C-3b'den beri kabul edilen açılış sınıfı). Beş test
dosyası yalnız additive kanıt/mekanik uyum aldı; hiçbir mevcut assertion
gevşetilmedi veya kaldırılmadı.

**J. Final verdict**

`POST-COMMIT GATES PASS — READY FOR SLICE 1 ROADMAP CHECKPOINT`

**DONE / LOCKED** — YALNIZ "Adım 7 / Slice 1 — Stopping-Event Attestation
Gate" alt kapsamı için. **Adım 7'nin kendisi ACTIVE / NEXT'tir.**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren bir roadmap-lock işlemidir; hiçbir
kaynak/migration/test/production/canonical/pending/audit dosyasına
dokunmaz; `3f80945` ve `7428d006` commit'leri amend EDİLMEZ;
stash/reset/cleanup/push YAPILMAZ.

### Adım 7 / Slice 2 — Stopping-Event Canonical and UI Visibility (DONE / LOCKED — checkpoint özeti)

**A. Amaç** — Slice 1'in YALNIZ generation-audit düzeyinde bıraktığı
stopping-event beyanının (`stopping_event_status` /
`stopping_event_attestation_ref`) üç katmanda deterministik, doğrulanmış ve
fail-closed biçimde görünür hale getirilmesi: (i) yeni üretilen canonical
deadline kayıtları, (ii) `case_view` projeksiyonu, (iii) avukat arayüzü.
**Bu Slice event-specific hukuki süre hesabını MODELLEMEZ** ve avukata yeni
bir soru/form GETİRMEZ.

**B. Exact commit zinciri**

| | Kod commit'i | Tally remediasyonu |
|---|---|---|
| SHA | `8e2ec896c6ed0ece0a61d61654b992cc80ba822e` | `728c880803f6703ae8831c539c22ae8057c3c6b8` |
| subject | `Expose stopping-event attestations in deadline views` | `Fix template test pass tally` |
| parent | `d757f45ec3d6a3097aaae7fc2aa661ff19ee9bac` | `8e2ec896c6ed0ece0a61d61654b992cc80ba822e` |
| kapsam | **1 A + 20 M = 21 dosya** | **yalnız `ui/tests/test_templates_isolated.py`** |
| body / trailer | yok / yok | yok / yok |

Her iki commit'te de `CLAUDE.md` ve `data/cases/**` **YOKTUR**. İlk commit
**amend EDİLMEDİ**; remediasyon AYRI bir commit olarak kaydedildi.

**C. Canonical sözleşmesi** — Yeni üretilen HER deadline entry iki anahtarı
**fiziksel olarak** taşır: `stopping_event_status` ve
`stopping_event_attestation_ref`. Kurallar:

- `status` enum: **`none` / `present` / `unknown`**
- geçersiz veya doğrulanamayan `ref` canonical'da **`null`** yazılır
- **legacy canonical OKUNABİLİR KALIR** (iki alan da optional; şema
  `schema_version` const 1 DEĞİŞMEDİ)
- legacy canonical'da eksik alanlar **`unknown` / `null`** olarak yorumlanır
- eksik alanlar **HİÇBİR ZAMAN sessizce `none` SAYILMAZ**
- stopping-event kapısını geçmek sonucun mutlaka `calculated` olacağını
  **GARANTİ ETMEZ** — yarım gün politikası
  (`needs_review_if_deadline_day`) ve diğer downstream kurallar (hafta
  sonu/resmî tatil/adli tatil/mali tatil/takvim kapsamı) yine
  `needs_review` üretebilir

**D. Promosyon sözleşmesi (fail-closed, writer ve journal'dan ÖNCE)** —
Legacy veya bozuk bir pending, aşağıdaki SEKİZ koşuldan HERHANGİ biri
gerçekleştiğinde reddedilir:

1. root `dict` değil
2. `deadlines` yok veya `list` değil
3. schema/semantic validator başarısız
4. `stopping_event_status` anahtarı **fiziksel olarak** yok
5. `stopping_event_attestation_ref` anahtarı **fiziksel olarak** yok
6. `stopping_event_status` değeri enum dışı
7. `stopping_event_attestation_ref` tipi/biçimi geçersiz
8. diğer deadline semantic kuralı başarısız

Kapı, LOCKED Layer A facade'inin `precondition_callback`'inde (adım 5,
`_insert_prepared`'dan ÖNCE) çalışır. **On vaka × sekiz güvence = 80/80
PASS**, gerçek/disposable PostgreSQL'e karşı:

- `prepared` journal satırı **0**
- writer invocation **0**
- canonical yazımı **0**
- history/backup **0**
- generation/approval audit **0**
- pending **bayt-değişmez**
- `reconciliation_required` / resource gate **YOK**
- red sonrası **sonraki geçerli mutasyon BLOKE DEĞİL**

Ayrıca kaydedilir: **geçerli** bir belge sonrası **enjekte edilen gerçek
writer failure**, Row 19C-2a'nın mevcut
`writer failure → reconciliation_required` sözleşmesini **AYNEN KORUR** —
bu senaryo silinmedi veya zayıflatılmadı.

**E. Digest / revision / attempt — üç namespace KARIŞTIRILMAZ**

| Rol | Literal | Durum |
|---|---|---|
| ham `input_digest` (saf dosya girdisi) | `row19c3ci.deadline.v3` | **DEĞİŞMEDİ** |
| `generation_parameters_digest` (fingerprint) | `row19c3ci.deadline_params.v4` | **DEĞİŞMEDİ** |
| composite `pre_revision` (identity) | `row19c3ci.deadline_revision.v1` | **YENİ** |

```
pre_revision = sha256(canonical_json({revision_version, input_digest, attempt}))
```

Semantik:

- `attempt` varsayılan **1**, apply-only, `>= 1`, **ASLA otomatik
  ARTIRILMAZ**
- aynı `attempt` + aynı parametreler → **safe replay** (writer ikinci kez
  çağrılmaz)
- aynı `attempt` + farklı parametreler → **deterministic conflict**
  (`IdempotencyConflictError`, sıfır mutasyon)
- `--attempt N+1` → **açık yeni revision**
- `N+1` **yan etkisiz bir kimlik rotasyonu DEĞİLDİR**: aktif pending
  KASITLI olarak yeniden üretilir, önceki pending `history/` altına
  taşınabilir
- generation audit'teki `input_digest` **ham dosya digest'i** olarak kalır
- `attempt` audit'e **ayrı bir alan** olarak kaydedilir

**F. Case-view ve UI**

- `case_view` **YALNIZ canonical deadline'dan** türetilir — generation
  audit'ten **ASLA**
- `status` / `ref` / `notes` projekte edilir
- `notes` başlığı: **`Hesaplama notu`**
- `ref` `null` ise o satır **HİÇ render edilmez**
- `status` için üç Türkçe etiket **deterministiktir**
- **Markdown veya otomatik hyperlink YOK**; HTML autoescape korunur
- dört XSS payload'u ham biçimde **SIZMAZ**
- bidi / zero-width taşıyan `ref` **reddedilir**
- **duplicate deadline paneli YOK** (generic dump'tan hariç tutuldu)
- **cross-case veri sızıntısı YOK**
- legacy canonical görünümü **`unknown` / `null`** olarak fail-closed kalır

**G. İlk gate STOP ve remediasyon (tarihsel doğrulukla)** — `8e2ec896`
üzerindeki İLK resmî `production-parity` koşumu **başarısız** oldu:

- 83 attempted, **82 PASS**, **1 `TALLY_MISMATCH`**
- **gerçek test failure = 0**
- `test_templates_isolated`: raw PASS satırı **18**, summary **17**
- STOP kuralı gereği **RAG kapısı ÇALIŞTIRILMADI**
- **roadmap GÜNCELLENMEDİ**

Kök neden: Slice 2'nin eklediği yeni kontrol çıplak `assert` + `print("PASS …")`
kullanmış, modülün kendi `check()` sayacını **artırmamıştı**.

Remediasyon: AYRI commit `728c880`; **üretim davranışı DEĞİŞTİRİLMEDİ**,
**assertion GEVŞETİLMEDİ veya SİLİNMEDİ** (doğrulanan koşul hâlâ
`case_scoped_review("case_view", …)`'in `ValueError` fırlatmasıdır; fırlatmazsa
kontrol FAIL olur), `TOTAL` satırı **elle 18'e SABİTLENMEDİ** (hâlâ
`f"TOTAL: {passed} passed, {failed} failed"`), raw ve summary **doğal olarak
18/18** eşitlendi; `8e2ec896` **amend EDİLMEDİ**.

**H. Başarılı resmî kapılar (exact HEAD `728c880`)**

`production-parity` — temiz detached exact-commit LF worktree, taze/disposable
PostgreSQL 16 (yalnız loopback, migration **0001→0005**), değiştirilmemiş
runner, modül seçimi/filtresi yok, tek kesintisiz koşu:

- `runner_exit_code` **0**, `state` **completed**, **SWEEP FULL**
- discovery `tracked = filesystem = run = **83**`, `missing [] untracked []
  rejected []`
- **83/83 PASS** (`modules_non_pass 0`, `modules_not_spawned 0`)
- **6774 passed, 0 failed**
- **8 counted skip** / **14 informational skip**
- `test_templates_isolated` **18/18**, `TALLY_MISMATCH` **YOK**
- `test_deadline_stopping_event_visibility_isolated` **35/35**
- **15/15 `*_postgres` modülü**, her biri `passed > 0` (zero-check yok)
- guard **armed 217 = expected 217**, `inheritance_ok true`,
  `net_blocked 0`, `env_open_blocked 0`, positive controls **10/10**
- `protected_manifest_ok true`, **entries 380**, `protected_path_diff []`
- secret scan **166 dosya**, `hits []`
- process/temp/db/bytecode residue **hepsi `[]`**, `failures []`
- `refusals []`, `warnings []`, `tmp_dir_removed true`, `git.clean true`

`rag-dependency`:

- **`RAG_GATE_PASS`**, exit **0**
- **3/3 PASS**, **216 passed, 0 failed**
- informational **ham 1** / K.1 muafiyeti **1** / **etkin 0**
- `marker_present true`
- guard **armed 7 = expected 7**, positive controls **10/10**
- integrity temiz (`manifest_ok true`, `diff []`, `hits []`)

**I. Veri bütünlüğü ve dürüst disclosure**

- Temiz detached worktree'de `data/**` **110/110 bayt-değişmez** (her iki
  kapıdan önce ve sonra; added/removed/changed hepsi boş)
- `data/cases` **71 tracked dosya**; `git status --ignored -- data/cases`
  **boş**
- Bu turda **hiçbir canonical / pending / audit / history artefaktı
  ÜRETİLMEDİ**
- Ana repo `git status` **temiz**
- Ana repo diskindeki **117** sayısı = **110 tracked + 7 ignored `.bak`**
- **Ana repo için bu turda koşu-öncesi/sonrası disk-bayt manifesti
  ALINMADIĞI için "ana repo `data/**` bayt-değişmez" iddiası YAPILMAZ** —
  kullanılan kanıt git temizliğidir
- Ana repo çalışma kopyalarındaki CRLF ile blob/worktree LF farkı, daha
  önce kayıtlı (Holiday Calendar Phase B §H) **residual EOL gözlemidir**;
  içerik farkı DEĞİLDİR
- `src/deadline_validator.py --self-test`, **mevcut fixture-mutation
  kusuru** (üretim `data/` altındaki yedi `deadline_validator_v1_*.json`
  dosyasını taze `generated_at` ile yeniden yazması, Prensip 18 ihlali)
  nedeniyle **ÇALIŞTIRILMADI**; bu kusur **bu Slice'ta DÜZELTİLMEDİ** ve
  açık backlog olarak kalır

**J. Sabit sayımlar (git ve dosya sisteminden yeniden türetildi)**

| Sayaç | Öncesi | Sonrası |
|---|---|---|
| tracked `ui/tests/test_*.py` | 82 | **83** |
| `*_postgres.py` | 15 | **15 (değişmedi)** |
| production Python (tracked `*.py` − `ui/tests/**`) | 159 | **159 (değişmedi)** |
| `db/migrations/*.sql` | 5 | **5 (değişmedi)** |
| `data/*.schema.json` | 20 | **20 (değişmedi)** |
| protected manifest girdisi | 379 | **380** |
| merged reconciliation routing key | 52 | **52 (değişmedi)** |
| logical action family | 40 | **40 (değişmedi)** |
| CLI subcommand | 6 | **6 (değişmedi)** |

Son üç sayaç bu turda **mekanik olarak yeniden doğrulandı** (üretim
`_default_registry_factory()` ve `ui/cli_mutate.py`'nin gerçek
`add_parser(...)` çağrıları sayılarak), tahmin edilmedi. `--attempt`, mevcut
`generation` subcommand'ına eklenen bir **bayraktır** — yeni bir subcommand
DEĞİLDİR.

**K. Açık kapsam (abartılmaz)**

- Slice 2 **YALNIZ görünürlüğü ve mutasyon güvenliğini** tamamlar
- **event-specific hukuki modelleme YAPILMADI**
- **durdurucu olayların süre aritmetiği UYGULANMADI**
- **Adım 7 ACTIVE / NEXT olarak KALIR**
- Adım 8-13, corpus acquisition/population ve diğer roadmap işleri
  **AÇIKTIR**
- **pilot production-ready DEĞİLDİR**
- **yeni avukat formu GEREKMEDİ ve ÜRETİLMEDİ**

`POST-COMMIT GATES PASS — READY FOR SLICE 2 ROADMAP CHECKPOINT`

**DONE / LOCKED** — YALNIZ "Adım 7 / Slice 2 — Stopping-Event Canonical and
UI Visibility" alt kapsamı için. **Adım 7'nin kendisi ACTIVE / NEXT'tir.**

**Bu checkpoint'in kendisi** — önceki tüm checkpoint'ler örneğinde olduğu
gibi yalnız `CLAUDE.md`'yi değiştiren bir roadmap-lock işlemidir; hiçbir
kaynak/migration/test/production/canonical/pending/audit dosyasına
dokunmaz; `8e2ec896` ve `728c880` commit'leri amend EDİLMEZ;
stash/reset/cleanup/push YAPILMAZ.

### Adım 7 — Deadline Hardening Pilot-Scope Closure (DONE / LOCKED FOR CURRENT PILOT — checkpoint özeti)

**A. İki ayrı işlem, iki ayrı mutasyon durumu** — Bu kapanışın
dayandığı kaynak denetimi (Adım 7 / Slice 3 — Event-Specific Legal
Modeling Discovery) **read-only** yürütülmüş ve repository'de **sıfır
mutasyona** yol açmıştır: preflight ve kapanışta `git status
--porcelain --untracked-files=all` boş, HEAD
`4f54c7ed4d385a5e0fef314480a52fe51a99cf51` değişmedi, `data/` ağacı **117
dosya bayt-değişmez**, bytecode/temp artığı yok. Bu checkpoint turu ise
AYRI bir işlemdir ve **documentation-only**'dir: yalnız `CLAUDE.md`
değişir (iki saf ekleme, 0 silme). Bu tur "salt-okunur" DEĞİLDİR —
ayırım bilinçli olarak kayıttadır.

**B. Kapanışın dayanağı — DRAFT-4 SORU 8.5(iii)** — Avukatın kendi
bağlayıcı talimatı `src/deadline_calculator.py:1394-1401`'de birebir
kayıtlıdır: *"bu tür bir başvuru/işlem yapılmış dosyalar mevcut
sürümde kapsam dışı bırakılmalı. İşletmeci hukuki etkiyi KENDİSİ
YORUMLAMAMALI; avukat 'bu olay süreyi etkilemez' diye ayrıca YAZILI
karar vermedikçe işlemeyi durdurmalı."* ve *"HAYIR → pilot devam
edebilir. EVET / BİLİNMİYOR → pilot durur; son gün üretilmez ve avukat
incelemesi gerekir."* Adım 7, bu talimata uyularak yapılan **bilinçli
kapsam dışı bırakma** ve **fail-closed davranışın tamamlanmış olması**
nedeniyle kapanmıştır — "olaylar modellendi" anlamında DEĞİL.

**C. Mevcut lawyer-approved kaynak envanteri** — DRAFT-4 Avukat
Doğrulama Paketi (repo DIŞI, SHA-256
`dcf4df690bf8298830a3e19b9041d148cb331ccd198f16bceb73129cf186ecd1`;
SORU 3.1-3.8, SORU 5.1-5.4, 14 altın örnek, SORU 8.5(iii)); imzalı
resmî tatil takvimi doğrulaması (repo İÇİ,
`HC-LAWYER-VERIFY-v1-2024-2035-fb79b85fcf114c95`); mali tatil (5604
m.1/3) uygulanabilirlik görüşü (repo DIŞI, ilgili checkpoint'te
kayıtlı); `data/provisions.json` **8 provision** (`kanun_6736_m5_f3`,
`kanun_2577_m7_f1`, `m7_f2_b`, `m8_f1`, `m8_f2`, `m8_f3`, `m61_f1`,
`kanun_5604_m1`); `data/deadline_rules/deadline_rules.json` **1 aktif
kural** (`iyuk_tax_court_general_lawsuit_filing`, 7 `legal_basis_refs`);
`ui/tests/test_deadline_lawyer_golden_examples_isolated.py` **14 altın
örnek + `lawyer_note` provenance**. LAWYER-CONFIRM-v3/v4 taslakları
canonical kaynak SAYILMAMIŞTIR; bu turda yeni avukat formu
ÜRETİLMEMİŞ, internet/dış API KULLANILMAMIŞTIR.

**D. Sekiz olayın mevcut pilot kapsamı dışındaki durumu** — Sekiz olay
şunlardır: uzlaşma; İYUK m.11 başvurusu; VUK m.35; VUK m.376; usulsüz
tebligat/öğrenme tarihi; pişmanlık ihlali; değerleme/takdir komisyonu;
SORU 5.5 tarihsel çalışmaya-ara-verme dönemleri. Bunların her biri için
durum **aynıdır ve dar biçimde şöyledir**: mevcut pilotta **bilinçli
olarak kapsam dışıdır**; **mevcut pilotun bloklayıcısı DEĞİLDİR**
(SORU 8.5(iii) bu dışarda bırakmayı zaten talimatlandırmıştır);
**hukuki aritmetik UYGULANMIYOR**; ve **gelecekte kapsam yeniden
açılırsa lawyer confirmation required** olacaktır.

Kaynak denetiminin mekanik bulgusu: sekiz olayın HİÇBİRİ için
`data/provisions.json` içinde provision, `deadline_rules.json` içinde
kural, canonical şemalarda tarih alanı veya kodda aritmetik YOKTUR.
Yalnız ikisi (`settlement`, `correction_complaint`) `case.schema.json`
→ `administrative_actions[].action_category` enum'unda bir değer
taşır; bu çapraz kontrol (`case_has_stopping_event_signal()`) **bir
DEDEKTÖR DEĞİLDİR** ve
`ui/tests/test_deadline_stopping_events_isolated.py` test K bunu kalıcı
olarak pinler. Kalan altı hâlin enum karşılığı YOKTUR ve tamamen
avukatın `none` beyanına dayanır (disclosure, kusur değil). Ek dar
gözlem (kusur iddiası DEĞİL): `case_has_stopping_event_signal()` YALNIZ
`administrative_actions[].action_category`'yi tarar;
`case.schema.json`'ın `case_type` enum'undaki `correction_complaint`
değeri TARANMAZ.

**SORU 5.5 — sınırlı disclosure (dar, abartılmaz):** SORU 5.5 bir
durdurucu olay değil, temporal-versioning konusudur ve avukat
tarafından **CEVAPLANMAMIŞTIR; UNRESOLVED kalır** (Adım 6 YALNIZ SORU
5.1-5.4'ü kapsar). Mevcut `kanun_2577_m61_f1` kaydının
`formal.valid_from = "2016-07-23"` kapısı, denetimde test edilen 2014 ve
erken 2016 anchor tarihlerini **tarih aritmetiğinden ÖNCE**
`needs_review`'a düşürmüştür. Bu **yalnız gözlenen mevcut fail-closed
davranıştır**; SORU 5.5'e **hukuki bir cevap DEĞİLDİR**, tüm tarihsel
dönemlerin doğru modellendiğini veya riskin tamamen kapandığını
**GÖSTERMEZ**. Gelecekte tarihsel kapsam açılırsa **ayrıca avukat onayı
gerekir**.

**E. Bugünkü fail-closed teknik yol (salt-okunur doğrulandı)** —
`build_deadline_record()` kapı sırası: rule çözümü →
`blocked_unverified_anchor` → rule selection policy → historical legal
basis check → **stopping-event gate** (Slice 1) →
`calculate_rule_deadline()`. Sözleşme kaynakta yazılıdır: kapı
`calculate_rule_deadline()`'ın İÇİNE KONMAZ — o fonksiyon saf tarih
aritmetiği olarak KALIR. `stopping_event_status` `present` veya
`unknown` iken sonuç `calculation_state="needs_review"`,
`calculated_deadline=null`, `requires_human_review=True`'dur. Promosyon
`src/deadline_approval.py`'nin **8-koşullu fail-closed** kapısındadır
(`_insert_prepared`'dan ÖNCE; sıfır journal/writer/canonical/audit).
`case_view` projeksiyonu (`src/orchestrator_engine.py:233`) canonical'da
alan YOKSA **`unknown`** üretir, ASLA `none`. Avukat arayüzü
(`ui/templates/macros.html`) "Durdurucu olay", "Beyan referansı" ve
"Hesaplama notu" satırlarını gösterir. Bu checkpoint, gelecekteki bir
event-modeling sürümünün şema/digest/migration/registry etkileri
hakkında **HİÇBİR ön-karar VERMEZ**; bunlar ayrı bir tasarım turunun
konusudur.

**F. K1-K4 kullanıcı kararları** — **K1 KAPAT**: Adım 7 mevcut pilot
bakımından kapanır, "modellendi" anlamında DEĞİL. **K2 SORMA**: mevcut
pilot için yeni avukat sorusu/formu hazırlanmaz; aynı konu yeniden
avukata gönderilmez; kapsam genişletilirse ayrı bir sürüm kararı olarak
sorulur. Denetim turunda taslağı çıkarılan ek avukat soruları
**KULLANILMAMIŞTIR, canonical kanıt DEĞİLDİR** ve bloklayıcı veya
yapılacak iş olarak BIRAKILMAMIŞTIR. **K3 ERTELE**: yapılandırılmış olay
intake'i şimdi yapılmaz; bugün kaynakta gözlenen gerçek, `case.json`
için koordineli bir production writer bulunmadığıdır (tüm
`ui/services/*facade*` ve `src/*approval*` tarandı; tek yazma çağrıları
`src/qa_engine.py:1705-1717`'deki geçici self-test fixture'larıdır), bu
nedenle intake mevcut Slice'ın küçük bir uzantısı değildir ve gelecekte
ayrı bir exact-scope ve sözleşme planı gerektirir. **K4 ADIM-8**:
sıradaki canlı iş Pilot Readiness Adım 8 — yerel PostgreSQL / IAM
adoption, **ACTIVE / NEXT**.

**G. Son doğrulanmış resmî gate kanıtı** — Bu tur hiçbir
kaynak/test/production dosyasına dokunmadığı için resmî kapı koşusu
GEREKMEMİŞ ve ÇALIŞTIRILMAMIŞTIR. Yürürlükteki son doğrulanmış sonuç,
exact commit `728c880803f6703ae8831c539c22ae8057c3c6b8`'in baytlarına
karşı, temiz bir exact-commit LF worktree'sinde ve taze/disposable bir
PostgreSQL 16 örneğinde alınmıştır:

- `production-parity`: **exit 0**, `state completed`, **SWEEP FULL**,
  **83/83 modül PASS**, **6774 passed, 0 failed**, **8 counted skip**,
  **14 informational skip**; **15/15 `*_postgres` modülü gerçekten
  koştu**; guard `armed 217 = expected 217`, positive controls
  **10/10**, `net_blocked 0`, `env_open_blocked 0`; integrity
  `protected_manifest_ok true` (**380 giriş**), `protected_path_diff []`,
  secret scan **166 dosya, hits []**; `refusals []`, `warnings []`.
- `rag-dependency`: **`RAG_GATE_PASS`**, **exit 0**, **3/3 modül PASS**,
  **216 passed**, **0 failed**, informational **ham 1**, K.1 muafiyeti
  **1**, **etkin informational skip 0**, `marker_present true`, guard
  `armed 7 = expected 7` ve positive controls **10/10**, integrity temiz
  (`manifest_ok true`, `diff []`, `hits []`).

Bu tur o sonuçları DEĞİŞTİRMEZ ve yeniden ÜRETMEZ.

**H. §9 / §12 değerlendirmesi** — Bu turda **hiçbir LOCKED
üretim/şema/migration/data dosyası AÇILMAMIŞTIR**; **§9 gerekçesi
GEREKMEZ**. Tek değişen dosya `CLAUDE.md`'dir ve değişiklik **§12
kapsamındadır** (yalnız §5 checkpoint durumu + next-active
güncellemesi). **§3 temel mimari prensipler ve §4 roadmap sırası
DEĞİŞMEMİŞTİR**; Pilot Readiness adımları §4 row'u değildir ve
`19. Production / Security — ACTIVE / NEXT` ile `20. Pilot /
Evaluation` satırları AYNEN KALMIŞTIR. Eski Adım 6 / Slice 1 / Slice 2
pointer'ları, eski checkpoint bölümleri ve §6 backlog'a
DOKUNULMAMIŞTIR.

**I. Değişmeyen mekanik sayaçlar** — tracked test modülü **83**;
`*_postgres` modülü **15**; production Python **159**; migration **5**;
merged reconciliation routing key **52**; logical action family **40**;
CLI subcommand **6**; `data/*.schema.json` **20**. Bu turda hiçbiri
değişmemiştir.

**J. Kapanmayan roadmap alanları** — Sekiz olayın hukuki aritmetiği
(gelecekte kapsam yeniden açılırsa lawyer confirmation required); SORU
5.5 (cevaplanmadı, UNRESOLVED); Adım 9 sentetik concierge dry-run; Adım
10 ilk gerçek concierge pilotu; Adım 11 Entra/P1; Adım 12 hosting/Key
Vault; Adım 13c configurable case root; corpus acquisition/population;
Row 19D (OS ACL / service identity / TOCTOU, advisory-lock timeout
backlog'u). **Pilotun production-ready olduğu İDDİA EDİLMEZ.**

**K. Final verdict**

`ADIM 7 DONE / LOCKED FOR CURRENT PILOT — EVENT-SPECIFIC LEGAL ARITHMETIC EXPLICITLY EXCLUDED, NOT IMPLEMENTED`

**DONE / LOCKED FOR CURRENT PILOT**

**Bu checkpoint'in kendisi** — **documentation-only** bir roadmap-lock
işlemidir: yalnız `CLAUDE.md`'yi değiştirir (iki saf ekleme, 0 silme);
hiçbir kaynak/migration/test/production/canonical/pending/audit
dosyasına dokunmaz; hiçbir commit amend EDİLMEZ;
stash/reset/cleanup/push YAPILMAZ.

