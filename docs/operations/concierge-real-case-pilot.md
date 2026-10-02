# Gerçek Dava Concierge Pilotu — Operatör Runbook'u

**Pilot Readiness Adım 10 / Slice 10A.** Bu belge, ilk gerçek vergi dosyasının
concierge modelde, tek dava ve tek tebliğ sınırı içinde, fail-closed biçimde
işlenmesi için **operatör talimatıdır**.

---

## 1. Amaç ve belge statüsü

### 1.1 Amaç

Adım 9'da tamamen sentetik bir dosya üzerinde kanıtlanan concierge zincirini
(maskeli tek model çağrısı → fact inceleme/promotion/verification → timeline →
deadline → salt-okunur avukat raporu) **tek bir gerçek dosya** üzerinde, gerçek
veriye özgü hukuki, rıza, gizlilik, saklama ve silme kapılarıyla birlikte
yürütmek.

### 1.2 Bu belge nedir, ne değildir

- Bu belge **talimattır**. Yazıldığı ve düzeltildiği turlarda bu belgedeki
  hiçbir komut çalıştırılmamış, hiçbir gerçek belge alınmamış, hiçbir
  veritabanı satırı yazılmamış, hiçbir ağ isteği yapılmamış ve hiçbir API
  anahtarı oluşturulmamıştır.
- Bu belge **canonical roadmap kaydı değildir**. Canlı kurallar yalnız
  `CLAUDE.md` §1–§13'tedir; çelişki hâlinde `CLAUDE.md` geçerlidir.
- Bu belge **hukuki görüş değildir** ve hiçbir hukuki onayın yerine geçmez.
- Bu belgenin varlığı Adım 10'un yürütülmesini **yetkilendirmez**. Yürütme,
  §1.5'teki ön koşullar sağlandıktan ve §6, §7 ile §28.1'deki belgeler
  alındıktan sonra ayrı ve açık bir kullanıcı onayı ister.

### 1.3 Politika statüsü — iki ayrı durum (bağlayıcı ayrım)

§6–§12, §14, §15 ve §28'de kaydedilen **yedi pilot politikası** (P1–P7),
Adım 10 preflight'ında kullanıcı tarafından **bu runbook'un tasarımı için
onaylanmıştır**. Bağımsız incelemeden sonra kullanıcı ayrıca dört karar
vermiştir:

| Karar | İçerik | Bölüm |
|---|---|---|
| K1-A | Gerçek veri gönderilmeden önce ayrı onaylı, tek denemelik, gövdesiz ve retry'sız `GET /v1/models` auth probe | §16.4 |
| K2-A | Kamu kurumu adları maskelenmez; aktarım ve rıza kapsamında açıkça belirtilir. Gerçek personel adları ve iletişim bilgileri maskelenir | §7.1, §15.2 |
| K3-A | Gerçek veriden önce ağsız, anahtarsız ve DB'siz sentetik prova zorunludur | §1.5 |
| K4-A | İlk bağımsız inceleme, içinde danışma (advisor) aracı kullanıldığı çekincesiyle kabul edilmiştir; düzeltme sonrası inceleme alt-ajan, Fable modeli ve advisor aracı **kullanılmadan** yapılır | §1.5 |

Bu onay ve kararlar şu anlama **gelmez**:

| Kalem | Durum |
|---|---|
| Yedi politikanın ve K1–K4 kararlarının runbook tasarımı için kullanıcı onayı | **ALINDI** |
| Avukatın yazılı hukuki onayı (P1) | **ALINMADI** |
| Dokuz hard-block belge sınıfını sayan imzalı hukuki ek (P1) | **ALINMADI** |
| İmzalı yazılı rıza (P2) | **ALINMADI** |
| Pilot sonu veri akıbeti yazılı kararı (P6) | **ALINMADI** |
| Pilota özel API anahtarı (P3) | **OLUŞTURULMADI** |

Bu tabloda **ALINMADI** veya **OLUŞTURULMADI** olan her kalem, ilgili kapıda
**DUR** sebebidir. Tablo belgenin yazıldığı andaki durumu gösterir; yürütme
anındaki durum evidence'ta ölçülür.

### 1.4 Yazım kuralları (bağlayıcı)

- **Yer tutucular** her zaman backtick veya kod bloğu içinde yazılır; çıplak
  köşeli-parantez biçimi GFM görüntüleyicilerinde HTML etiketi sanılıp
  kaybolabilir. Kullanılan yer tutucular:

| Yer tutucu | Anlamı |
|---|---|
| `<repo-root>` | Repository kök dizininin mutlak yolu |
| `<case-root>` | Pilot case dizininin mutlak yolu: `<repo-root>\data\cases\<case-id>` |
| `<python>` | §13.3'te tanımlanan yorumlayıcının mutlak yolu |
| `<psql>` | PostgreSQL 16 `psql.exe` dosyasının mutlak yolu (§13.5) |
| `<select-statement>` | §13.5, §26.3 veya §27.1'deki `SELECT` ifadelerinden biri, tek satırda |
| `<case-id>` | Pilot dosyasının opak case kimliği (§10.3) |
| `<document-id>` | Tebliğ belgesinin opak document kimliği |
| `<fact-id>` | Tebliğ tarihini taşıyan fact'in kimliği |
| `<actor-user-id>` | Avukat kullanıcısının `iam.users.id` değeri |
| `<admin-user-id>` | İlk admin kullanıcısının `iam.users.id` değeri |
| `<anchor-event-id>` | Canonical timeline'daki tebliğ olayının `event_id` değeri |
| `<expected-hash>` | Önceki preview'ın bastığı SHA-256 |
| `<expected-input-digest>` | Önceki preview'ın bastığı `input_digest` |
| `<attestation-ref>` | Avukatın stopping-event beyanının opak referansı |
| `<baseline-max-id>` | Bir apply'dan önce ölçülen en büyük journal `id` değeri (§26.3) |
| `<mask-term-count>` | Avukatın tohum teyidinde onaylanan ek maskeleme terimi sayısı (§15.3) |
| `<mask-file-sha256>` | Aynı teyitte onaylanan terim dosyasının SHA-256'sı (§15.3) |
| `<external-root>` | Repo dışı, bulut senkronizasyonu olmayan, **yalnız bu pilot için ayrılmış** pilot kök dizininin mutlak ve canonical yolu; aşağıdaki dört dizinin ebeveyni. Sürücü kökü olamaz; `<repo-root>`'a eşit, onun altında veya atası olamaz; `<case-root>`, Temp kökü, `<python-runtime-root>` ve `<pg-bin-dir>` ile örtüşemez; doğrudan altında yalnız bu dört dizin bulunabilir (§13.8) |
| `<evidence-dir>` | `<external-root>` altında, **yalnız metadata** taşıyan genel pilot evidence dizini (§26) |
| `<probe-evidence-dir>` | `<external-root>` altında, auth probe'a ait ayrı ve yeni metadata-only evidence dizini (§16.4) |
| `<inference-evidence-dir>` | `<external-root>` altında, tek inference'a ait ayrı ve yeni metadata-only evidence dizini (§18) |
| `<restricted-dir>` | `<external-root>` altında, avukat kontrolündeki **dava-türevi içerik** dizini (§10.2, §10.5) |
| `<archive-dir>` | Yalnız şifreli arşiv kararında: yazılı karardaki arşiv yerinin mutlak yolu (§28.5) |
| `<archive-parent>` | Yalnız şifreli arşiv kararında: yazılı kararda önceden onaylanmış, `<archive-dir>`'in exact ebeveyni (§28.5) |
| `<python-runtime-root>` | §13.3'teki concierge runtime'ının kök dizini; `<python>` bunun altındadır (§13.8) |
| `<pg-bin-dir>` | PostgreSQL 16 `bin` dizini; `<psql>` bunun doğrudan altındadır (§13.8) |
| `<harness-output-names>` | Harness'in pinli manifestinin sabitlediği kalıcı çıktı dosyası adlarının PowerShell dizi literal'i; harness kalıcı dosya yazmıyorsa `@()` (§10.5) |
| `<report-produced>` | Zincir adım 25 çıkış `0` ile tamamlandıysa `$true`, aksi hâlde `$false` (§28.2) |

- **Dizin ve dosya yer tutucuları mutlak, canonical ve önceden çözümlenmiş
  yollardır**: `<repo-root>`, `<case-root>`, `<python>`, `<psql>`,
  `<python-runtime-root>`, `<pg-bin-dir>`, `<external-root>`,
  `<evidence-dir>`, `<probe-evidence-dir>`, `<inference-evidence-dir>`,
  `<restricted-dir>`, `<archive-parent>` ve `<archive-dir>`. Göreli
  yol kabul **edilmez**: .NET dosya çağrıları göreli bir yolu PowerShell
  konumuna göre değil, sürecin çalışma dizinine göre çözer. Her yol,
  kullanılmadan önce §13.8'deki yol kapısından geçer; geçmeyen yol **DUR**'dur.
- Yer tutucular **aynen kopyalanarak çalıştırılmaz**; her biri gerçek değerle
  değiştirilir. Ek maskeleme terimleri için yer tutucu **yoktur**: terimler
  komut satırına elle yazılmaz, §15.3'teki argüman dizisiyle geçirilir.
- `yes`, `no`, `none`, `verified`, `lawyer`, `fact`, `timeline`, `deadline` ve
  `fact_extraction` yer tutucu **değil**, CLI'ın kabul ettiği **literal**
  değerlerdir.
- Bütün komutlar repo kökünden (`<repo-root>`) ve Windows PowerShell içinde
  çalıştırılır. Python modülleri **yalnız `-m` biçimiyle** çağrılır
  (`docs/operations/local-postgresql-iam-adoption.md` §B.3).
- Her Python oturumunda, aynı runbook'un §B.2 emsaliyle, önce şu ayarlanır
  (`ui/cli_mutate.py`, `scripts/iam_admin.py` ve iki validator kendi çıktı
  kodlamasını ayarlamaz; yalnız `ui/deadline_report.py` ayarlar):

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

- Bu belgede gerçek kullanıcı adı, mutlak yerel yol, port, veritabanı adı,
  bağlantı dizesi, kimlik bilgisi dosyası, anahtar, kişi/kurum adı, iletişim
  bilgisi, kimlik veya vergi numarası **bulunmaz** ve operatör de bunları bu
  belgeye, commit'e veya genel evidence dizinine **yazmaz**.
- Bu belgede bölüm numarası tek başına yazıldığında (ör. "§13") **bu
  runbook'un** bölümü kastedilir. `CLAUDE.md` ve başka belgelerin bölümleri
  her zaman belge adıyla birlikte yazılır. "Zincir adım N" ifadesi §2.1
  tablosundaki satır numarasını gösterir.

### 1.5 Yürütme ön koşulları (bağlayıcı)

Gerçek veri alınmadan **önce**, aşağıdakilerin hepsi sağlanmış olmalıdır:

1. **Bağımsız inceleme.** Bu runbook, düzeltme sonrasında yazar oturumundan
   ayrı ve temiz bir oturumda, alt-ajan, Fable modeli ve advisor aracı
   kullanılmadan (K4-A) incelenmiş ve blocking bulgu kalmamıştır.
2. **Commit ve push.** Runbook commit'lenmiş, push edilmiş ve yürütme
   yetkisinde kullanıcının onayladığı HEAD'de **tracked** olarak
   bulunmaktadır. Untracked veya değiştirilmiş bir runbook ile yürütme
   yapılmaz; §13.2'nin temiz ağaç beklentisi bunu ayrıca zorlar.
3. **Sentetik prova (K3-A).** 1 ve 2'den sonra, ayrı bir turda ve ayrı
   kullanıcı yetkisiyle; **ağsız, API anahtarsız, pilot veritabanısız** ve
   yalnız sentetik, yeniden üretilebilir girdilerle şu yeni mekanik adımlar
   prova edilmiştir:
   - içerik oturumunun açılması, profil/transcript kontrolleri, PSReadLine
     handler sınıflandırması ve yardımcı süreç adı taraması (§4.3);
   - PSReadLine geçmiş dosyasının prova oturumu boyunca hash ve zaman
     bilgisiyle değişmediği (§4.3 c);
   - dizin yol kapısı, `<python>`/`<psql>` dosya kapısı ve `<archive-dir>`
     kapısı (§13.8, §28.5);
   - manuel intake dosya biçimi ve kodlama kontrolleri (§11.2);
   - orijinal belge / `file.sha256` hash eşlemesi, intake hash kaydı ve
     yeniden karşılaştırma (§11.3 a, b);
   - açık argümanlı validator çağrıları (§11.3 c, d);
   - vergi türü sözlük kontrolü (§11.3 f);
   - ortam değişkeni ad taraması ve `.env` boyut kontrolü (§13.6);
   - `<restricted-dir>` izinli dosya kümesi kaydı ve envanter kontrolü;
     beklenmeyen dosya, alt dizin ve reparse point/symlink reddi (§10.5);
   - iki ayrı metadata manifestinin (`closing-case-manifest.tsv`,
     `closing-restricted-manifest.tsv`) exclusive-create davranışı: var olan
     hedefe ikinci yazma denemesinin reddi ve manifest türlerinin birbirinin
     yerine kabul edilmemesi (§28.2, §28.3);
   - case ve `<restricted-dir>` exact-path silme guard'ları; silme
     komutunun sentetik exact hedefte provası; silme sonrası hedefin
     yokluğu, kalıntı sayısı ve ebeveyn altındaki kalıntı kontrolü (§28.3);
   - silme guard'larının negatif kontrolleri: hedef olarak yanlış ebeveynli
     bir dizin, `data/cases/case_0001` ve `<repo-root>` verildiğinde; case
     manifestinden sonra bir dosya eklendiğinde, değiştirildiğinde veya
     silindiğinde; korunan bir yol yer tutucu bırakıldığında; izinli küme
     kaydı veya hash kaydı değiştirildiğinde ya da bozulduğunda
     (`ALLOWED_FILE_HASH_OK=False`); ve
     `<external-root>` olarak bir sürücü kökü, repo kökünün atası veya küme
     dışı öğe taşıyan bir dizin verildiğinde guard'ın `STOP` basması. Negatif kontrollerde **yalnız guard bloğu** çalıştırılır;
     silme bloğu **hiç çalıştırılmaz** (§28.3);
   - `--mask-term` argüman dizisinin fail-closed kurulması ve tırnaklama
     (§15.3);
   - harness wrapper'ı ile iç argv'nin birleşimi (§18.2): iç argv dizisi,
     harness'in pinli manifestindeki çağırma biçimiyle, boşluk, Türkçe
     karakter, tek tırnak, `;` ve `$` içeren sentetik terimlerle verilir; iç
     hedef yerine yalnız aldığı eleman sayısını ve beklenen diziyle
     eleman-eleman eşitlik boolean'ını basan sentetik bir hedef kullanılır.
     Beklenen: eleman sayısı aynı, eşitlik `True`, harness sayaçlarında
     reddedilmiş olay 0 ve dış bağlantı 0;
   - rapor satırı boolean kontrolü, sentetik bir metin dosyasıyla (§23);
   - salt-okunur SQL çağırma ve çıktı sözleşmesinin **bağlantı açmadan**
     statik kontrolü (§13.5);
   - güvenli DUR/abort akışının dosya ve credential içermeyen dalları
     (§25.2).

Prova gerçek pilot **değildir**; kendi ayrı evidence'ını üretir, sentetik
dizini kendi sonunda siler ve hiçbir gerçek belge, anahtar veya pilot
veritabanı satırı kullanmaz. Provada bir komut bu belgede yazıldığı gibi
çalışmazsa runbook **düzeltilir ve yeniden incelenir**; komut sahada
doğaçlama değiştirilmez.

Bu üç ön koşuldan biri eksikse: **DUR — gerçek belge teslim alınmaz.**

---

## 2. Pilot kapsamı

- **Bir** gerçek vergi dosyası (`<case-id>`).
- Bu dosyada **bir** tebliğ ve ondan doğan **bir** dava açma süresi.
- Modele gönderilen **tek** belge: tebliğ bilgisini taşıyan belge
  (`<document-id>`).
- **Tek** yetkili model çağrısı (fact extraction, `generation.fact_extraction`).
  "Tek gönderim" yalnız **tek gerçek model POST'u** anlamına gelir; ondan
  önceki auth probe (§16.4) ayrı bir dış ağ işlemidir. Pilot toplam **iki**
  ayrı dış ağ işlemi olarak raporlanır: bir gövdesiz `GET`, bir model `POST`.
- Mevcut koordineli CLI aileleri: `generation` (`fact_extraction`, `timeline`,
  `deadline`), `promotion` (`fact`, `timeline`), `verification`, `approval`
  (`deadline`) ve salt-okunur `ui.deadline_report`.
- Adım 8'de kurulan kalıcı yerel PostgreSQL kümesi ve mevcut IAM kullanıcıları.
- Avukatın yazılı kararlarının mevcut lawyer IAM aktörü üzerinden birebir
  uygulanması.
- Pilot sonunda, avukatın yazılı veri akıbeti kararına göre gerçek verinin
  silinmesi veya şifreli arşivi (§28).

### 2.1 Operasyon zinciri (bağlayıcı sıra)

Sıra değiştirilemez; bir adım PASS olmadan sonrakine geçilmez. Tek istisna
§25.2'deki güvenli DUR/abort yoludur: o yol, herhangi bir adımda DUR
oluştuğunda **yalnız güvenli kapatma adımlarına** izin verir.

"Preview / apply" sütunu, mutasyonun önce yan etkisiz bir preview ile görülüp
ardından preview'ın bastığı hash veya digest ile ayrı bir apply olarak
çalıştırıldığını gösterir. "Avukat kararı" ve "Kullanıcı onayı" sütunları, o
adımdan **önce** alınması gereken ve bir önceki onayın yerine geçmeyen ayrı
kararları gösterir. Canonical mutasyonlar, ağ işlemleri, assignment
değişiklikleri ve silme için kullanıcı onayı **her seferinde ayrıca** alınır
(`CLAUDE.md` §8).

| # | Adım | Preview / apply | Avukat kararı | Kullanıcı onayı | Bölüm |
|---|---|---|---|---|---|
| 1 | Yürütme ön koşulları: incelenmiş ve commit'li runbook, sentetik prova | — | — | Yürütme yetkisi | §1.5 |
| 2 | Hukuki onay ve imzalı hard-block eki | — | Yazılı | — | §6, §9 |
| 3 | Yazılı rıza ve eksiksiz veri akıbeti kararı | — | Müvekkil imzası + avukatın yazılı kararı | — | §7, §28.1 |
| 4 | Kapsam ön elemesi (gerçek veri alınmadan) | — | Yazılı | — | §8 |
| 5 | İçerik oturumu, kanal kapısı, yol kapısı, repo ve DB durumunun ölçülmesi; `<restricted-dir>` izinli dosya kümesinin ve SHA-256 kaydının oluşturulması | Salt-okunur + iki kayıt dosyası | — | — | §4.3, §10.5, §13 |
| 6 | Manuel intake | Dosya oluşturma | — | — | §11.2 |
| 7 | Mekanik kontroller ve avukatın alan-alan intake onayı | Salt-okunur | Yazılı | — | §11.3, §11.4 |
| 8 | Tam maskeleme tohumu | — | Yazılı tamlık teyidi | — | §15.2 |
| 9 | `assign-case` | Tek çalıştırma | — | Ayrı onay | §12.3 |
| 10 | Ağsız preview ve `input_digest` | Preview | Yazılı (maskeli metin ve maskeli context okuması) | — | §17 |
| 11 | Ortam preflight'ı, harness paritesi ve anahtarın oluşturulması | Salt-okunur + anahtar | — | — | §13.6, §13.7, §14 |
| 12 | Auth probe | Tek `GET` | — | Ayrı ağ onayı | §16.4 |
| 13 | Tek inference | Apply (`--allow-network`), yalnız harness zinciri içinden, tek `POST` | — | Ayrı ağ onayı | §18 |
| 14 | Anahtarın revoke edilmesi ve Process temizliği | — | — | — | §29 |
| 15 | Fact içerik incelemesi | Salt-okunur | Yazılı, her fact | — | §19.1 |
| 16 | Fact promotion | Preview → apply | Yazılı kabul | Ayrı onay | §19.2 |
| 17 | Yalnız tebliğ fact'inin verification'ı | Preview → apply | Yazılı karar | Ayrı onay | §19.3 |
| 18 | Timeline generation | Preview → apply | — | — | §20 |
| 19 | Timeline promotion | Preview → apply | Yazılı onay | Ayrı onay | §20 |
| 20 | Stopping-event beyanı ve adli tatil kararı | — | Yazılı beyan + referans | — | §21.1 |
| 21 | Kör bağımsız hesabın sabitlenmesi | — | Yazılı hesap + hash | — | §21.2 |
| 22 | Deadline generation | Preview → apply | — | — | §22.1 |
| 23 | Pending tarihin sabitlenmiş hesapla karşılaştırılması | Salt-okunur | — | — | §22.3 |
| 24 | Deadline approval | Preview → apply | Yazılı onay | Ayrı onay | §22.4 |
| 25 | Salt-okunur deadline raporu | Salt-okunur | — | — | §23 |
| 26 | Rapor tarihinin son karşılaştırması | Salt-okunur | — | — | §24 |
| 27 | Assignment revoke | Tek çalıştırma | — | Ayrı onay | §27 |
| 28 | İki ayrı metadata-only kapanış manifesti (case ve `<restricted-dir>`) | Salt-okunur + exclusive-create | — | — | §28.2 |
| 29 | Gerçek verinin silinmesi veya şifreli arşivi | Her hedef için tek çalıştırma | Adım 3'teki eksiksiz yazılı karar | Her silme hedefi için silme anında ayrı onay | §28 |
| 30 | Ortamın kapanış ölçümü | Salt-okunur | — | — | §29 |
| 31 | Postcondition'lar ve LOCK kaydı | Salt-okunur; LOCK ayrı tur | — | LOCK onayı | §30, §31 |

Pending üreten adımlar (zincir adım 18 ve 22) canonical mutasyon değildir;
yürütme yetkisi kapsamında, ayrı kullanıcı onayı olmadan çalıştırılır. Zincir
adım 14, adım 13 biter bitmez yapılır; anahtar bir sonraki adıma
**taşınmaz**.

---

## 3. Kapsam dışı işler

Aşağıdakiler bu pilotta **yapılmaz**; görülürse **DUR**:

- İkinci dava, ikinci tebliğ, ikinci deadline adayı veya ikinci model çağrısı.
- Tebliğ belgesi dışındaki belgelerin modele gönderilmesi veya fact
  extraction'a sokulması.
- `fact_extraction` dışındaki herhangi bir ajan modu (`--with-agent`); bunlar
  Adım 4b/4c ile kaynakta zaten fail-closed reddedilir.
- `qa` ve `case_view` generation/approval: fact verification sonrası basılan
  downstream rehberinde yer alırlar, ancak salt-okunur rapor yalnız canonical
  `deadlines/deadline.json` ile `approval.deadline` journal kaydını okur
  (`ui/deadline_report.py` başlık yorumu). Bu iki aile bu zincirde koşulmaz.
- Issue spotting, legal research, case law, evidence, argument, risk/strategy,
  drafting.
- Süre aşımı (expiry) değerlendirmesi.
- Sekiz event-specific hukuki aritmetik (uzlaşma, İYUK m.11 başvurusu, VUK
  m.35, VUK m.376, usulsüz tebligat/öğrenme tarihi, pişmanlık ihlali,
  değerleme/takdir komisyonu, SORU 5.5 tarihsel dönemleri) — `CLAUDE.md` §5,
  Adım 7 kapanışı.
- Web arayüzü, OIDC/Entra login (Adım 11).
- Hosting, Key Vault, servis kimliği (Adım 12).
- Çoklu deadline ve configurable case root (sonraki adımlar; `CLAUDE.md`
  yalnız configurable case root'u Adım 13c olarak kaydeder).
- RAG corpus edinimi veya bundle aktivasyonu.
- Herhangi bir repo dosyasının değiştirilmesi, commit veya push (yürütme
  turunda da; LOCK kaydı ayrı bir turdur).
- Gerçek içeriğin §4.2'deki güven sınırının dışına çıkarılması.

---

## 4. Roller, sorumluluklar ve gerçek içerik güven sınırı

### 4.1 Roller

| Rol | Sorumluluk | Yapamayacağı |
|---|---|---|
| **Avukat** | Hukuki onay; rıza sürecinin yürütülmesi; belge teslimi; kapsam ön elemesi; intake alanlarının alan-alan doğrulanması; fact kabulü; tebliğ tarihi verification kararı; adli tatil uygulanabilirliği kararı; stopping-event beyanı; kör bağımsız hesap; deadline onayı; veri akıbeti kararı | — |
| **Müvekkil (veri sahibi)** | Yazılı rızanın imzalanması | — |
| **Operatör (insan)** | Ortam/DB ölçümü; manuel intake; mekanik hash ve validator kontrolleri; avukat kararlarının CLI ile birebir uygulanması; evidence; cleanup | Hukuki karar vermek, avukat kararını yorumlamak, eksik kararı varsaymak, kapsam genişletmek |
| **Kullanıcı (proje sahibi)** | Yürütme yetkisi; her canonical mutasyon, ağ işlemi, assignment değişikliği ve silme için ayrı açık onay; LOCK onayı | — |
| **Bağımsız inceleyici** | Runbook ve yürütme evidence'ının ayrı oturumda incelenmesi | Yürütmeye katılmak; gerçek içeriği görmek |

Avukat ile operatör rollerinin aynı kişide birleşmesi bu runbook tarafından
öngörülmez. Birleşirse **iki kişili kontrol ortadan kalkar**: §11.4'teki
intake karşılaştırması, §17.3'teki maskeli metin okuması ve §22.3'teki
karşılaştırma tek kişinin kendi işini kendisinin denetlemesine iner. Bu durum
evidence'a açıkça yazılır ve ayrı kullanıcı onayı gerektirir; müvekkil rolü
hiçbir durumda operatör rolüyle birleşmez.

### 4.2 Gerçek içerik güven sınırı (bağlayıcı)

**Gerçek içerik** şunların tamamıdır: orijinal belge; maskesiz extracted text;
`case.json` ve `document.json`; preview'ın bastığı maskeli case context ve
maskeli belge metni; `--mask-term` değerleri; pending ve canonical fact,
timeline ve deadline dosyalarının içeriği; deadline raporu; bu komutların ham
stdout/stderr çıktısı.

1. Gerçek içeriğe **yalnız insan operatör ve avukat** erişir.
2. Claude Code, ChatGPT veya başka herhangi bir AI asistanı; bulut OCR,
   çeviri veya dönüştürme hizmeti; bulut pano; ekran paylaşımı; otomatik ekran
   kaydı; uzaktan destek oturumu gerçek içeriği **göremez**.
3. OCR ve metin çıkarma **yalnız** kullanıcı ve avukat tarafından önceden
   yazılı olarak onaylanmış, **yerel ve çevrimdışı** bir araçla yapılır.
   Aracın adı ve sürümü evidence'a yazılır.
4. Bulut senkronizasyonlu klasör ve bulut senkronizasyonlu pano kullanılmaz.
5. Gerçek içerik veya onu gösteren bir ekran görüntüsü hiçbir sohbet veya
   ajan oturumuna **yapıştırılmaz**.
6. İçeriğe dokunan her adım (intake, metin çıkarma, validator'lar, preview,
   inference, fact incelemesi, pending/canonical okuma, rapor, manifest,
   silme) **insan-only bir PowerShell oturumunda** yürütülür. Bu oturum, AI
   asistanının çalıştığı oturumdan **tamamen ayrıdır**: AI asistanı bu
   kabuğu süremez, çıktısını okuyamaz, `<case-root>` veya `<restricted-dir>`
   altındaki hiçbir dosyayı açamaz. Bu yalnız bir politika cümlesi değildir:
   içerik penceresi boyunca bu kanalların **kapalı** olduğu §4.3'teki kanal
   kapısıyla ölçülür ve kaydedilir.
7. Bir AI oturumuna **yalnız** şunlar aktarılabilir: opak kimlikler, hash'ler,
   sayaçlar, `PASS`/`FAIL` değerleri ve kişisel veri içermeyen sabit hata
   kodları. Bu aktarım, §4.3'teki içerik penceresi boyunca ancak çalışma
   ağacına, `<restricted-dir>`'e ve içerik oturumunun ekranına erişimi
   **olmayan** bir oturuma yapılabilir.
8. **Ham stdout/stderr dava-türevi içerik sayılır**; genel evidence'a veya bir
   AI oturumuna taşınmaz. Somut sınırlar:
   - Preview maskeli case context'i ve maskeli belge metnini stdout'a basar;
     önerdiği apply komutu veya ayrı bloğu **gerçek `--mask-term` değerlerini
     düz metin olarak** taşır (`ui/cli_mutate.py`,
     `_format_mask_terms_for_operator`).
   - Motor, apply sırasında maskesiz context'ten türeyen `Source actor:`
     etiketini stdout'a basar (`src/fact_extraction_engine.py`, "LLM fact
     extraction başlatılıyor..." bloğu). Bu satırın konsola ulaşıp
     ulaşmadığından bağımsız olarak apply çıktısı gerçek içerik sayılır.
   - Validator çıktısı kimlik ve yol taşır.
   - Harness veya monitor stdout/stderr'i kalıcı yazıyorsa bu dosyalar
     `<restricted-dir>` içinde tutulur ve veri akıbeti kararına tabidir.
9. **Kayıt ve telemetri.** PowerShell transcription, script-block logging,
   modül logging veya süreç-oluşturma komut satırı denetimi gerçek değerleri
   cihazın dışına (merkezi log, EDR, SIEM) çıkarıyorsa: **DUR**. Bu runbook
   güvenlik kontrollerinin kapatılmasını **önermez**; uygun güvenli ortam
   yoksa pilot bu cihazda **yapılmaz**. Ölçüm (yalnız anahtar varlığı; standart
   Windows davranışından gelir, repo kaynağından değil):

```powershell
foreach ($k in 'ScriptBlockLogging', 'Transcription', 'ModuleLogging') { foreach ($hive in 'HKLM:', 'HKCU:') { $p = "$hive\SOFTWARE\Policies\Microsoft\Windows\PowerShell\$k"; if (Test-Path -LiteralPath $p) { "PS_POLICY_KEY_PRESENT=$hive/$k" } else { "PS_POLICY_KEY_ABSENT=$hive/$k" } } }
$audit = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit'
if (Test-Path -LiteralPath $audit) { "CMDLINE_AUDIT_KEY=PRESENT" } else { "CMDLINE_AUDIT_KEY=ABSENT" }
```

   `PRESENT` çıkan her anahtar için, cihaz sahibi bu kaydın cihaz dışına
   aktarılmadığını yazılı olarak beyan etmedikçe **DUR**. Bu ölçüm üçüncü
   taraf güvenlik yazılımının (antivirüs, EDR) kendi telemetrisini
   **göremez**; o sınır §32'de açık kalır ve cihaz sahibinin yazılı beyanıyla
   karşılanır. İlke anahtarları, bir profil betiğinin veya elle başlatılmış
   bir `Start-Transcript` çağrısının açtığı transcript'i de **göstermez**; o
   kanal §4.3 (b)'deki `-NoProfile` ve aktif transcript kontrolüyle kapatılır.
10. Bu sınırın ihlali veya ihlal şüphesi **DUR**'dur (§25, H40) ve bir olay
    kaydı açılır.

### 4.3 İçerik oturumunun açılması ve kanal kapısı (bağlayıcı)

**İçerik penceresi**, gerçek intake'in başladığı andan (zincir adım 6)
gerçek verinin silinmesinin veya arşivlenmesinin tamamlandığı ana (zincir
adım 29) kadar süren aralıktır. Veri §28.1/6 gereği yeni bir yazılı karar
beklenirken veya §28.1/5 gereği doğrulanmış arşivden sonra yerel çalışma
kopyası korunurken pencere **açık kalır**.

Runbook'un yazılması, incelenmesi ve sentetik provası içerik penceresinin
**dışında** ve insan-only içerik oturumundan **ayrı** tutulur; bu işler için
kullanılan hiçbir oturum içerik oturumu olarak yeniden kullanılmaz.

**(a) Kanal kapısı.** Gerçek intake başlamadan önce ve içerik penceresi
boyunca, gerçek case çalışma ağacına (`<repo-root>` ve altı),
`<restricted-dir>`'e veya içerik oturumunun ekranına erişebilen şunların
**hepsi kapalıdır**:

- AI kodlama asistanı (terminal, masaüstü veya tarayıcı oturumu);
- AI eklentili IDE veya editör;
- bulut OCR, çeviri veya dönüştürme aracı;
- ekran paylaşımı, ekran kaydı ve uzaktan destek;
- bulut pano senkronizasyonu ve pano geçmişi;
- içerik veya telemetri gönderebilen başka herhangi bir yardımcı araç (dosya
  indeksleyici, bulut yedekleme veya senkronizasyon istemcisi dahil).

Operatör bunu iki adımla ölçer ve kaydeder. **Asıl kapı Adım 2'deki
insan-only oturum beyanıdır**; Adım 1 yalnız yardımcı bir sinyaldir.

Adım 1 — yardımcı süreç adı taraması (yalnız süreç **adı** basar; liste
**tüketici değildir**, standart Windows davranışından gelir). Sabit adlı bir
tarama güvenlik garantisi **değildir**: `node`, `Code - Insiders`,
`python`, `powershell` veya tarayıcı gibi genel taşıyıcı süreçler AI
araçlarını veya eklentilerini barındırabilir ve bu desenle **ayırt
edilemez**. `0` sonucu tek başına kanalların kapalı olduğunu kanıtlamaz:

```powershell
$channelPattern = '(?i)claude|chatgpt|copilot|cursor|windsurf|^code$|pycharm|idea|webstorm|rider|teams|zoom|anydesk|teamviewer|quickassist|onedrive|dropbox|googledrive'
$channelNames = @(Get-Process | Select-Object -ExpandProperty ProcessName -Unique | Where-Object { $_ -match $channelPattern } | Sort-Object)
"AI_CHANNEL_PROCESS_COUNT=$($channelNames.Count)"; foreach ($n in $channelNames) { "AI_CHANNEL_PROCESS=$n" }
```

Beklenen: `AI_CHANNEL_PROCESS_COUNT=0`. Eşleşen her araç kapatılır ve tarama
yeniden çalıştırılır; kapatılamıyorsa **DUR**. Operatör, bu desende olmayan
ama yukarıdaki altı sınıftan birine giren her aracı da kendi bilgisiyle
kapatır. Çalışma ağacına, `<restricted-dir>`'e veya içerik oturumunun
ekranına erişebilecek bir süreç **bilinmiyorsa** ya da altı sınıftan birine
girip girmediği **sınıflandırılamıyorsa** (genel taşıyıcı süreçler dahil):
**DUR — intake başlamaz.**

Adım 2 — kontrol kaydı. Altı sınıfın her biri için bir boolean ve sonuç
satırı `<evidence-dir>` içine yazılır:

```text
AI_CODING_ASSISTANT_CLOSED=True
AI_IDE_EXTENSION_CLOSED=True
CLOUD_OCR_TRANSLATION_CLOSED=True
SCREEN_SHARE_REMOTE_SUPPORT_CLOSED=True
CLOUD_CLIPBOARD_CLOSED=True
OTHER_CONTENT_TELEMETRY_TOOL_CLOSED=True
AI_CONTENT_CHANNELS_CLOSED=True
```

Kayıt yalnız boolean ve süreç adı taşır; gerçek yol, kullanıcı adı veya içerik
**taşımaz**. `AI_CONTENT_CHANNELS_CLOSED=True` yalnız altı satırın hepsi
`True` ise yazılır. Bir sınıf ölçülemiyor veya doğrulanamıyorsa: **DUR —
intake başlamaz.** Kapı, içerik taşıyan her yeni oturumun başında yeniden
ölçülür.

**(b) İçerik oturumunun açılması.** İçerik taşıyan her PowerShell oturumu
`powershell.exe -NoProfile` komutuyla (bayrak kısaltılmadan) açılır. Profil
betiği, prompt hook'u, komut kaydedici veya transcript başlatabilecek hiçbir
mekanizma bu oturumda **yüklenmez**. Oturumun ilk komutları:

```powershell
"CONTENT_SESSION_NOPROFILE=$([bool](@([System.Environment]::GetCommandLineArgs()) -contains '-NoProfile'))"
try { Stop-Transcript | Out-Null; "STOP TRANSCRIPT_ACTIVE=True" } catch { "TRANSCRIPT_ACTIVE=False" }
$extraModules = @(Get-Module | Select-Object -ExpandProperty Name | Where-Object { $_ -notmatch '^(Microsoft\.PowerShell\.(Management|Utility|Security|Host|Diagnostics)|PSReadLine)$' } | Sort-Object)
"EXTRA_MODULE_COUNT=$($extraModules.Count)"; foreach ($m in $extraModules) { "EXTRA_MODULE=$m" }
$rl = Get-PSReadLineOption
$defaultHistoryHandler = $null; try { $defaultHistoryHandler = [Microsoft.PowerShell.PSConsoleReadLineOptions]::DefaultAddToHistoryHandler } catch { $defaultHistoryHandler = $null }
$hh = $rl.AddToHistoryHandler
"HISTORY_HANDLER_STATE=$(if ($null -eq $hh) { 'NONE' } elseif (($null -ne $defaultHistoryHandler) -and [object]::ReferenceEquals($hh, $defaultHistoryHandler)) { 'DEFAULT' } else { 'UNKNOWN' })"
"COMMAND_VALIDATION_HANDLER_STATE=$(if ($null -eq $rl.CommandValidationHandler) { 'NONE' } else { 'UNKNOWN' })"
Remove-Variable hh, defaultHistoryHandler -ErrorAction SilentlyContinue
Set-PSReadLineOption -HistorySaveStyle SaveNothing
"HISTORY_SAVE_STYLE=$((Get-PSReadLineOption).HistorySaveStyle)"
Set-Location -LiteralPath "<repo-root>"
$env:PYTHONIOENCODING = "utf-8"
```

Beklenen, hepsi birlikte: `CONTENT_SESSION_NOPROFILE=True`,
`TRANSCRIPT_ACTIVE=False`, `EXTRA_MODULE_COUNT=0`,
`HISTORY_HANDLER_STATE=NONE` veya `HISTORY_HANDLER_STATE=DEFAULT`,
`COMMAND_VALIDATION_HANDLER_STATE=NONE`, `HISTORY_SAVE_STYLE=SaveNothing`.
Başka her çıktı veya doğrulanamayan bir durum: **DUR — intake başlamaz**
(H53). Çıktı yalnız boolean, durum adı ve modül adı taşır; değer, handler
içeriği veya yol basmaz.

**Handler sınıflandırması (bağlayıcı).** Yalnız varsayılan bir geçmiş
handler'ının **varlığı** DUR sebebi **değildir**; PSReadLine'ın kendi
varsayılan handler'ı her makinede bulunabilir ve bu yüzden her makinede yanlış
DUR üretmemelidir. Bağlayıcı güvenlik sonucu şu birleşimden gelir: oturum
`-NoProfile` ile açılmıştır; aktif transcript yoktur;
`HistorySaveStyle=SaveNothing` zorunludur; gerçek değerler komut satırına
literal olarak yazılmaz; maskeleme terimleri dosyadan bellekte argv dizisine
alınır (§15.3). `UNKNOWN`, handler'ın PSReadLine varsayılanıyla aynı nesne
olduğunun gösterilemediği anlamına gelir: handler bir profilden, prompt
hook'undan veya özel koddan gelmiş olabilir ve komut içeriğini kalıcı
yazabilir veya dışarı aktarabilir; güvenli olup olmadığı belirlenemediği için
**DUR**'dur. Varsayılan handler'ın ayırt
edildiği alan adı repo kaynağından değil, PSReadLine'ın kendi davranışından
gelir ve §1.5'teki provada doğrulanır; provada temiz bir `-NoProfile`
oturumu `UNKNOWN` verirse runbook **düzeltilir ve yeniden incelenir**, sahada
doğaçlama yapılmaz.

- Aktif transcript kontrolü, transcript açık bulunursa onu **durdurur**; bu
  durumda oturum zaten **DUR** ile kapatılır ve içerik işlenmez.
- PSReadLine ve geçmiş önlemleri (`SaveNothing`) korunur, ancak transcript
  kontrolünün **yerine geçmez**: `SaveNothing` yalnız geçmiş dosyasını
  kapatır.
- Bu komutlar repo kaynağından değil, standart PowerShell davranışından
  gelir ve §1.5'teki provada doğrulanır.

**(c) Geçmiş dosyasının değişmezliği (yalnız sentetik prova).** Provada,
başka hiçbir PowerShell penceresi açık değilken, (b)'deki komutlardan hemen
sonra ve prova oturumu kapanmadan hemen önce aynı oturumda ölçülür; hash ve
zaman yalnız bellekte tutulur, basılmaz:

```powershell
$histPath = (Get-PSReadLineOption).HistorySavePath
$histBefore = if (Test-Path -LiteralPath $histPath -PathType Leaf) { (Get-FileHash -LiteralPath $histPath -Algorithm SHA256).Hash + '|' + (Get-Item -LiteralPath $histPath -Force).LastWriteTimeUtc.Ticks } else { 'ABSENT' }
```

```powershell
$histAfter = if (Test-Path -LiteralPath $histPath -PathType Leaf) { (Get-FileHash -LiteralPath $histPath -Algorithm SHA256).Hash + '|' + (Get-Item -LiteralPath $histPath -Force).LastWriteTimeUtc.Ticks } else { 'ABSENT' }
"HISTORY_FILE_UNCHANGED=$($histBefore -ceq $histAfter)"
Remove-Variable histPath, histBefore, histAfter -ErrorAction SilentlyContinue
```

Beklenen: `HISTORY_FILE_UNCHANGED=True`. Aksi hâlde runbook düzeltilir ve
yeniden incelenir; gerçek veriyle yürütme başlamaz.

---

## 5. Değiştirilemez güvenlik ilkeleri

1. `CLAUDE.md` §3'teki mimari prensipler bu pilotta aynen geçerlidir;
   özellikle 1 (model çıktısı canonical gerçek değildir), 8 (unverified
   anchor üzerinden kesin deadline hesaplanmaz), 9 (belirsizlik → hesaplama
   yok), 15 ve 16 (pending → validation → insan onayı → canonical).
2. `CLAUDE.md` §13.1.2–§13.1.5 operasyon kuralları aynen geçerlidir: case
   dizini kontrolü için düz `git status` yetmez; `git clean -fdx` ve
   `git stash --all` **yasaktır**; `data/cases/case_0001` fixture'ına gerçek
   veri konmaz ve o dizin bu pilotta okunmaz, değiştirilmez; resmî test
   kapıları pilot sürerken koşulmaz.
3. Operatör hukuki karar vermez; her hukuki giriş avukatın yazılı kararıdır.
4. Gerçek içerik §4.2'deki güven sınırının dışına çıkmaz; Git'e, loglara, hata
   mesajlarına veya genel evidence dizinine **yazılmaz**.
5. **Otomatik retry yoktur.** Başarısız bir adım yeniden denenmez; düzeltici
   SQL çalıştırılmaz; ikinci model gönderimi yapılmaz.
6. Her başarısızlık **DUR**'dur ve §25.2'deki güvenli DUR/abort yolunu
   çağırır.
7. Hiçbir force/bypass bayrağı yoktur; `ui.cli_mutate` bunu yapı gereği
   sunmaz (`ui/cli_mutate.py` başlık yorumu).
8. **Preview ve apply ayrı kod bloklarıdır.** Her mutasyonda sıra: preview
   bloğu → preview postcondition'ları ve gereken avukat kararı ile kullanıcı
   onayı (ayrı kapı) → apply bloğu. Apply bloğu yalnız önceki kapıların
   hepsi PASS ise kullanılır. Apply bloğu, preview'ın bastığı hash veya
   digest yerine konmadan veya biçimi 64 küçük harfli onaltılık değilse CLI'ı
   **hiç çağırmaz**; CLI ayrıca değeri canlı durumla karşılaştırır ve
   uyuşmazlıkta fail-closed reddeder. Yorum satırı veya yer tutucu tek başına
   bir güvenlik kapısı sayılmaz.

---

## 6. Gerçek veriden önceki hukuki kapılar (P1)

### 6.1 Zorunlu yazılı hukuki onay

Gerçek bir belge **teslim alınmadan önce** avukattan şu konuları kapsayan
yazılı cevap alınır:

1. KVKK kapsamında işleme dayanağı.
2. Model sağlayıcısının veri işleme şartları (DPA) ve sağlayıcı tarafındaki
   saklama.
3. Yurt dışına aktarım; aktarılan veri kategorilerinin tamamı §7.1'deki
   listeyle **aynı** olarak.
4. Avukatlık sırrı.
5. Belgelerin operatör makinesinde tutulması ve §4.2'deki güven sınırı.
6. Dokuz hard-block belge sınıfı — **hukuki onayın ekinde açıkça sayılmış
   olarak** (§9).
7. Kamu kurumu adlarının maskelenmeden aktarılması (K2-A, §15.2).
8. Silme sonrasında kalan izler (§28.4): veritabanı journal, assignment ve
   security-event kayıtları, hash manifestleri ve redakte operasyon özetleri.

Bu sorular kodla kapanmaz; Adım 4a checkpoint'i bunları `EXTERNAL LEGAL
VERIFICATION REQUIRED` olarak kaydetmiştir.

### 6.2 Saklama ve kayıt

- Yazılı onay **repo dışında** saklanır.
- Evidence'a yalnız onay belgesinin **SHA-256'sı** ve kişisel veri içermeyen
  kısa bir kapsam özeti yazılır.

### 6.3 Kapı

Yazılı hukuki onay veya imzalı ek yoksa ya da §6.1'deki sekiz kalemden biri
cevapsızsa: **DUR — gerçek belge teslim alınmaz.**

---

## 7. Yazılı rıza sözleşmesi (P2)

### 7.1 Rızanın kapsaması gerekenler

İmzalı rıza en az şunları **açıkça** kapsar:

1. **Tek** dava ve **tek** tebliğ.
2. Yurt dışındaki bir dış model sağlayıcısına gidebilecek veri kategorilerinin
   **tamamı**:
   - **(a)** maskelenmiş belge metni (extracted text);
   - **(b)** maskelenmiş dosya bağlamı (`src/fact_extraction_engine.py`,
     `build_allowed_context`): opak case, belge, taraf ve uyuşmazlık kalemi
     kimlikleri; tarafların rolleri ve takma adlandırılmış görünen adları;
     uyuşmazlık kalemlerinin vergi türü, dönemi ve ileri sürülen hukuki
     dayanak referansları; belgenin başlığı, kategorisi, türü, alt türü ve
     düzenleyen taraf kimliği; kaynak aktör etiketi;
   - **(c)** belge metninde geçen ve maskelemenin değiştirmediği bilgiler:
     işlemin türü ve kategorisi, düzenleyen idarenin (kamu kurumunun) adı,
     tarihler ve tutarlar;
   - **(d)** istek metadata'sı: sistem istemi, model kimliği ve istek
     parametreleri;
   - **(e)** sağlayıcının görebileceği bağlantı metadata'sı: IP adresi, zaman
     bilgisi ve API hesabı/anahtar kimliği;
   - **(f)** dava verisi taşımayan ayrı bir kimlik doğrulama isteği (auth
     probe, §16.4).
3. **Kamu kurumu adları mevcut tasarım gereği maskelenmez** (K2-A): vergi
   dairesi, mahkeme ve idare adları süre ve yetki analizinin girdisi olarak
   aktarılır ve rıza kapsamında açıkça kabul edilir.
4. Kamu kurumu **personelinin** gerçek adı, iletişim bilgileri ve diğer kişi
   tanımlayıcıları maskelenir.
5. Maskeleme **takma adlandırmadır, anonimleştirme değildir**; tohum listesinde
   olmayan veya farklı yazılmış dizgiler maskelenmeden kalabilir. Şirket adı,
   vergi dairesi, tutar ve tarih birleşimi yeniden kimliklendirici olabilir
   (`src/llm_privacy_boundary.py`, tohum bölümündeki açık sınır notu).
6. Pilot sonunda verinin akıbeti: avukatın açık ve eksiksiz yazılı kararına
   göre **silme** veya **şifreli arşiv** (§28.1). Karar eksikse veri ne
   silinir ne arşivlenir; yeni yazılı karara kadar korunur.
7. Silme sonrasında **kalan izler**: opak kimliklerle veritabanı journal,
   assignment ve security-event kayıtları; hash manifestleri; redakte
   operasyon özetleri (§28.4).

`case.json` içindeki `administrative_actions[]` alanları (işlem kategorisi,
düzenleyen idare, tarihler) dosya bağlamında modele **gönderilmez**
(`build_allowed_context` bu alanları içermez); aynı bilgi (c) kalemindeki
belge metninde ve (b) kalemindeki belge türü/kategorisi alanlarında yer
alabilir.

### 7.2 Saklama ve kayıt

- İmzalı rıza **repo dışında** saklanır.
- Repo'ya veya LOCK kaydına yalnız **SHA-256** ve kişisel veri içermeyen kısa
  bir kapsam özeti girer (ör. "tek dava, tek tebliğ, dış model aktarımı,
  kamu kurumu adı maskesiz, pilot sonu silme, kalan audit izleri").
- Rızanın kendisi, imzalayanın adı veya iletişim bilgisi evidence'a girmez.

### 7.3 Kapı

İmzalı rıza yoksa veya §7.1'deki yedi kalemden biri (2. kalemin altı alt
kategorisi dahil) eksikse: **DUR — gerçek belge teslim alınmaz.**

---

## 8. Kapsam ön elemesi ve tek dava / tek tebliğ kabul kriterleri

Bu eleme **gerçek veri teslim alınmadan önce**, avukatın elindeki belgeye
bakarak yaptığı **yazılı** beyanla yapılır. Dosya ancak aşağıdakilerin
**hepsi** sağlanırsa kabul edilir:

1. Dosyada **tek bir** tebliğ ve bundan doğan **tek bir** dava açma süresi
   bulunur; ikinci bir deadline adayı yoktur.
2. Tebliğ bilgisi **tek bir** belgede bulunur.
3. Belge §9'daki hiçbir hard-block sınıfına girmez (imzalı ekle kontrol).
4. **Belge türü desteklenir.** Bugün tek aktif deadline kuralı yalnız belge
   türü `vergi_ceza_ihbarnamesi` olan belgelere uygulanır
   (`data/deadline_rules/deadline_rules.json`, `applicability.document_types`).
   Avukat belgenin bu türde olduğunu yazılı olarak teyit eder. Başka türde bir
   belge için kural seçilemez ve zincir sonuçsuz DUR'a gider.
5. **Takvim kapsamı.** Tebliğ tarihinden itibaren sürenin ve olası
   kaydırmaların düştüğü yıllar resmî tatil takviminin kapsadığı 2024–2035
   aralığındadır (`CLAUDE.md` §5, Holiday Calendar Phase B).
6. Avukat, sekiz event-specific olaydan (§3) hiçbirinin dosyada bulunmadığını
   ön değerlendirme olarak beyan eder; bu, §21.1'deki yazılı stopping-event
   beyanının yerine **geçmez**.
7. Belge fact extraction için metne aktarılabilir ve metin 60.000 karakter
   sınırını aşmaz (§11.2).
8. **Vergi türü sözlüğü.** Avukat, dosyadaki her uyuşmazlık kaleminin vergi
   türünü yazılı olarak sınıflandırır ve her birinin §11.3 (f)'deki sözlükte
   **birebir** bulunan bir terimle ifade edilebildiğini teyit eder. Sözlükte
   karşılığı olmayan bir vergi türü (ör. sözlükte bilinçli olarak yer almayan
   gecikme faizi veya gecikme zammı) veya dahil ve istisna terimlerinin aynı
   dosyada karışması varsa dosya kabul edilmez.

Bu sekiz kalemden biri sağlanmazsa veya avukat tereddüt ederse: **DUR — gerçek
belge teslim alınmaz.** İkinci bir tebliğ, ikinci bir deadline ihtimali veya
aynı belgede birden fazla ihbarname/tebliğ zincirin **herhangi bir** adımında
(intake, fact inceleme, timeline, deadline) fark edilirse de **DUR**
geçerlidir.

---

## 9. Hard-block belge politikası

### 9.1 Kaynak durumu (dürüst)

Dokuz hard-block belge sınıfının listesi **bu repository'de bulunmaz**.
Repository yalnız bu listenin avukat doğrulama paketinin ilgili bölümünde açık
kaldığını kaydeder (`docs/roadmap/checkpoints/holiday-calendar-and-deadline-hardening.md`,
Adım 6 kapsamı dışı kalan kalemler). Bu runbook sınıfları **tahmin etmez**,
listelemez ve örneklemez.

### 9.2 Kural (fail-closed)

- Dokuz sınıfı **açıkça sayan imzalı hukuki ek** alınana kadar **bütün
  gerçek belgeler bloklanır**; hiçbir gerçek belge teslim alınmaz.
- Ek alındıktan sonra her aday belge, ekteki sınıflara karşı **avukat
  tarafından** yazılı olarak kontrol edilir. Operatör sınıflandırma yapmaz.
- Sınıflardan birine girdiğinden şüphe edilen belge alınmaz; şüphe = blok.
- Ekin SHA-256'sı evidence'a yazılır; içeriği yazılmaz.

---

## 10. Veri minimizasyonu ve saklama

### 10.1 Repo içine giren gerçek veri (yalnız ignored case dizini)

Yalnız `data/cases/<case-id>/` altında, `.gitignore`'un kök-bağlı
`/data/cases/` kuralıyla ignored olarak:

- `case.json` (taraflar dahil — maskeleme tohumunun kaynağı, §15.2),
- `documents/<document-id>/document.json`,
- `documents/<document-id>/` altında orijinal belge baytları,
- `documents/<document-id>/extracted/<document-id>.txt` (modele gidecek
  metnin kaynağı),
- zincirin ürettiği pending/canonical/review/history/audit dosyaları.

Başka hiçbir belge bu dizine konmaz.

### 10.2 Repo dışında kalanlar

- Hukuki onay, imzalı ek, imzalı rıza, avukatın yazılı kararları ve kör
  bağımsız hesabı: repo dışında, avukatın kontrolünde.
- **`<external-root>`** — repo dışındaki, yalnız bu pilot için ayrılmış
  kök dizin. Bulut senkronizasyonlu bir klasörde **değildir**, sürücü kökü
  **değildir**, repo ağacının içinde veya repo kökünün atası **değildir**.
  Aşağıdaki dört dizin onun doğrudan alt dizinidir ve doğrudan altında
  **başka hiçbir** dosya veya dizin bulunamaz; prova artefaktı, özet dosyası
  veya başka bir iş yükü bu kökte bırakılmaz (§13.8).
- **`<restricted-dir>`** — dava-türevi içerik dizini. Erişimi avukat ve
  operatörle sınırlıdır ve §28'deki veri akıbeti kararına **tabidir**. Yalnız
  şunları taşır: deadline raporu (§23); ek maskeleme terimleri dosyası
  (§15.3); varsa harness'in kalıcı yazdığı ham stdout/stderr dosyaları (§4.2).
  İzinli dosya adları intake'ten önce sabitlenir ve envanter mekanik olarak
  denetlenir (§10.5).
- **`<evidence-dir>`**, `<probe-evidence-dir>` ve `<inference-evidence-dir>`:
  **yalnız metadata** (§26). Gerçek tarih, rapor metni, maskeli metin veya
  herhangi bir gerçek içerik bu dizinlere girmez.
- **`<archive-dir>`** — yalnız eksiksiz bir şifreli arşiv kararı varsa
  kullanılır; `<external-root>`'un dışındadır ve kendi mekanik kapısından
  geçer (§28.5).
- Gerçek belge baytlarının veya metninin Temp, scratchpad, indirme dizini veya
  evidence dizininde **ikinci bir düz kopyası alınmaz**. Gerçek içerikli düz
  metin snapshot **oluşturulmaz**.

### 10.3 Opak kimlikler (bağlayıcı)

Veritabanı journal, mutation resource, assignment ve security-event satırları
**silinmez** (§28.4) ve şu değerleri kalıcı olarak taşır: `case:<case-id>`
resource anahtarı, `fact.<document-id>.<fact-id>.verification` gibi target
ref'ler ve hash'ler. Bu nedenle:

- `<case-id>`, `<document-id>`, `<fact-id>`, `file.file_name`,
  `<attestation-ref>` ve varsa promotion `--note` değeri **hiçbir kişisel
  veri, taraf adı, kimlik/vergi numarası veya dava numarası taşımaz**.
- `document.json` içindeki `title` de kişisel veri taşımaz: başlık modele
  gider ve yalnız tohum terimleri için maskelenir; kaynakta korunan kimlik
  anahtarları dışındaki her metin yaprağı aynı biçimde yalnız tohum
  eşleşmeleri için maskelenir (`src/llm_privacy_boundary.py`,
  `mask_context`). Jenerik bir başlık kullanılır.
- `<case-id>` biçimi iki kaynağın kesişimidir: şema `^[a-z0-9_-]+$` ve en az
  3 karakter ister (`data/case.schema.json`); yetkilendirme
  `^[A-Za-z0-9_-]{1,64}$` ister (`ui/services/authz.py`, `_CASE_ID_PATTERN`).
  Yani: küçük harf, rakam, `_` ve `-`; 3–64 karakter. `<case-id>` hiçbir
  durumda `case_0001` olamaz.
- `<case-id>` ve `<document-id>` paylaşılan path-containment denetiminin yasak
  alt dizgilerini içermez (`src/path_containment.py`,
  `FORBIDDEN_SEGMENT_SUBSTRINGS`).
- Maskeleme katmanı, bir taraf adı çekirdeğini taşıyan kimliği ayrıca
  fail-closed reddeder (`src/llm_privacy_boundary.py`,
  `assert_identifiers_are_opaque`). Bu ikinci savunma, opak kimlik seçme
  yükümlülüğünün yerine geçmez.
- Promotion `--note` bu pilotta **kullanılmaz**.

### 10.4 Çalışma ortamındaki ikincil kopyalar

PowerShell geçmişi, komut satırları ve konsol çıktısı gerçek değer
taşıyabilir. Bu nedenle §4.2, §14.4 ve §15.3'teki kabuk kuralları uygulanır;
preview'ın bastığı içerik yalnız ekranda okunur, dosyaya yönlendirilmez.
İçeriğe dokunan her insan-only oturum, işi biter bitmez **kapatılır**;
oturum içi komut geçmişi oturumla birlikte yok olur. Hiçbir değişken —
`$maskArgs` dahil — bir sonraki oturuma **taşınmaz**; her yeni içerik oturumu
§4.3 (b) ile açılır ve §15.3'teki dizi yeniden kurulur.

### 10.5 `<restricted-dir>` içerik sözleşmesi (bağlayıcı)

1. **Düz yapı.** `<restricted-dir>` yalnız doğrudan altında **normal
   dosyalar** taşır. Alt dizin, reparse point (symlink veya junction) veya
   normal dosya dışında herhangi bir öğe bulunursa: **DUR** (H56).
2. **Genel ve sabit adlar.** İzinli dosya adları gerçek kişi, kurum, case,
   belge veya tarih değeri **taşımaz**: `mask-terms.txt` (§15.3),
   `deadline-report.txt` (§23) ve harness kalıcı çıktı yazıyorsa
   `<harness-output-names>`. Harness'in kalıcı çıktı adları yalnız onun pinli
   manifestinden alınır (§13.7); manifest adları sabitlemiyorsa veya bir ad
   aşağıdaki biçime uymuyorsa: **DUR** (H56).
3. **Önceden kayıt.** İzinli küme, intake'ten önce (zincir adım 5),
   `<restricted-dir>` **boşken** ve hiçbir gerçek içerik oluşturulmadan
   `<evidence-dir>\restricted-allowed-files.txt` dosyasına exclusive-create
   ile yazılır. Bu dosya yalnız genel adlar taşıdığı için metadata'dır.
   **Hash kaydı.** İzinli liste yazıldıktan **hemen sonra**, aynı oturumda ve
   operatör tarafından, aşağıdaki kayıt bloğu bir kez çalıştırılır: liste
   dosyasının SHA-256'sı bir kez ölçülür, küçük harfe çevrilir, 64 küçük hex
   olduğu doğrulanır ve **stdout'a yazılmaz**; `<evidence-dir>` altında
   (`<restricted-dir>` dışında) sabit genel adlı
   `restricted-allowed-files.sha256.txt` dosyasına exclusive-create ile tek
   satır olarak yazılır: `restricted_allowed_files_sha256=<64-küçük-hex>` ve
   son bayt LF. Yazımdan sonra dosya yeniden okunur ve değer, bellekte az
   önce hesaplanan hash ile ordinal ve büyük/küçük harf duyarlı biçimde
   eşleşmelidir. Hash'in elle kopyalanması veya yer tutucuya yazılması
   **yoktur**. Kayıt gerçek yol, case kimliği, kişi/kurum adı veya dosya
   içeriği taşımaz; izinli liste yalnız genel ve sabit adlardan oluştuğu için
   generic metadata'dır. Kayıt sonradan yeniden üretilemez, silinemez veya
   üzerine yazılamaz; değişiklik gereği **DUR** ve yeni inceleme demektir.
   Hash kaydı olmadan intake başlatılamaz, restricted envanteri alınamaz ve
   restricted silme guard'ı geçemez.
4. **Kaydın yeniden doğrulanması.** Kaydın değişmediği iki noktada mekanik
   olarak doğrulanır: her envanterden önce (aşağıda) ve §28.3.2'deki
   restricted silme guard'ı çalışmadan hemen önce. Beklenen hash her
   kullanımda `<evidence-dir>\restricted-allowed-files.sha256.txt`
   kaydından alınır: kayıt yolu §13.8 dosya kapısından geçer (`Test-PilotLeafFile`:
   mutlak, canonical, normal dosya, reparse point yok); kayıt tam olarak bir
   satırdır, label exact `restricted_allowed_files_sha256=` ve değer 64
   küçük hex'tir; ardından `restricted-allowed-files.txt` yeniden hash'lenir
   ve iki değer ordinal ve büyük/küçük harf duyarlı karşılaştırılır. Çıktı
   yalnız `ALLOWED_FILE_HASH_OK=True` veya `ALLOWED_FILE_HASH_OK=False`'tur;
   gerçek hash basılmaz. Kayıt eksik, okunamıyor, bozuk veya değişmişse,
   herhangi bir ayrıştırma, G/Ç veya hash hatası olursa ya da hash
   eşleşmezse sonuç `False` olur: envanter güvenilir sayılmaz,
   `$rGuard` `False` kalır, silme yapılmaz, **DUR** (H56). Bu mekanizma
   yanlışlıkla değişimi tespit eder; iki dosyayı aynı anda değiştiren kötü
   niyetli bir operatöre karşı kriptografik imza **iddiası taşımaz**.
5. **Envanter.** Her içerik oturumunun başında, terim dosyası yazıldıktan
   sonra, rapor yazıldıktan sonra ve kapanış manifestinden önce envanter
   alınır. İzinli küme dışındaki her dosya veya dizin: **DUR** (H56).

Ortak yardımcılar. Fonksiyonlar ve değişkenler bir oturumdan diğerine
**taşınmaz**; kullanılan her oturumda yeniden tanımlanır. Bu komutlar repo
kaynağından değil, standart PowerShell ve .NET davranışından gelir ve
§1.5'teki provada doğrulanır:

```powershell
function Write-PilotExclusive([string]$path, [string[]]$lines) { if (Test-Path -LiteralPath $path) { return $false }; try { $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None) } catch { return $false }; $w = New-Object System.IO.StreamWriter($fs, (New-Object System.Text.UTF8Encoding($false))); try { $w.NewLine = "`n"; foreach ($l in $lines) { $w.WriteLine($l) } } finally { $w.Dispose() }; return $true }
function Get-PilotRestrictedState([string]$rDir) { try { $items = @(Get-ChildItem -LiteralPath $rDir -Force -Recurse -ErrorAction Stop) } catch { return $null }; $bad = @($items | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or ($_.DirectoryName -ne $rDir.TrimEnd('\')) }).Count; return [pscustomobject]@{ Bad = $bad; Files = @($items | Where-Object { -not $_.PSIsContainer } | Sort-Object Name) } }
function Test-PilotAllowedHash([string]$listPath, [string]$recordPath) { try { if (-not ((Test-PilotLeafFile $listPath) -and (Test-PilotLeafFile $recordPath))) { return $false }; $txt = (New-Object System.Text.UTF8Encoding($false)).GetString([System.IO.File]::ReadAllBytes($recordPath)); if ($txt -cnotmatch '^restricted_allowed_files_sha256=[0-9a-f]{64}\n\z') { return $false }; $expected = $txt.Substring('restricted_allowed_files_sha256='.Length, 64); $h = (Get-FileHash -LiteralPath $listPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant(); return [string]::Equals($h, $expected, [System.StringComparison]::Ordinal) } catch { return $false } }
```

`Test-PilotAllowedHash`, §13.8'in `Test-PilotLeafFile` ve `Test-PilotNoReparse`
yardımcılarını çağırır; bu yüzden §13.8 ortak yardımcıları aynı oturumda
**önce** tanımlanmış olmalıdır, aksi hâlde sonuç `False`'tur (istisna yakalanır).
Kayıt dosyası tam olarak `restricted_allowed_files_sha256=<64 küçük hex>` ve
tek bir LF'den oluşmalıdır; CR, BOM, ek satır veya ek bayt `False` üretir.

`Write-PilotExclusive`, hedef zaten mevcutsa **hiç yazmaz** ve `False`
döner; .NET `CreateNew` kipi, kontrol ile oluşturma arasında başka bir
sürecin dosyayı oluşturması hâlinde de var olan dosyanın üzerine yazmayı
reddeder. Yazma sırasında bir hata oluşursa komut hata verir: **DUR**.

İzinli kümenin kaydı (zincir adım 5, `Test-PilotPath 'restricted-dir'`
`PATH_OK` verdikten sonra, bir kez):

```powershell
$allowedNames = @('mask-terms.txt', 'deadline-report.txt') + <harness-output-names>
$namesOk = ($allowedNames.Count -eq @($allowedNames | Sort-Object -Unique).Count) -and (@($allowedNames | Where-Object { $_ -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}\.(txt|log|jsonl)$' }).Count -eq 0)
$rState = Get-PilotRestrictedState "<restricted-dir>"
if ($namesOk -and ($null -ne $rState) -and ($rState.Bad -eq 0) -and ($rState.Files.Count -eq 0) -and (Write-PilotExclusive "<evidence-dir>\restricted-allowed-files.txt" (@('# kind=restricted-allowed') + $allowedNames))) { "RESTRICTED_ALLOWED_RECORD=WRITTEN" } else { "STOP RESTRICTED_ALLOWED_RECORD=FAIL" }
```

`RESTRICTED_ALLOWED_RECORD=WRITTEN` alındıktan hemen sonra, intake'ten
**önce** ve `<restricted-dir>` hâlâ boşken, aynı oturumda ve operatör
tarafından, **bir kez** hash kaydı yazılır (madde 3). Blok dosyanın mevcut ve
normal dosya olduğunu, reparse point olmadığını doğrular (`Test-PilotLeafFile`),
SHA-256'yı bir kez ölçer, küçük harfe çevirir, 64 küçük hex desenini denetler,
hash'i **basmaz**, kaydı exclusive-create ile yazar, yeniden okur ve bellekteki
değerle birebir karşılaştırır:

```powershell
$allowedListPath = "<evidence-dir>\restricted-allowed-files.txt"
$allowedRecPath = "<evidence-dir>\restricted-allowed-files.sha256.txt"
$recOk = $false
try {
    if (Test-PilotLeafFile $allowedListPath) {
        $h = (Get-FileHash -LiteralPath $allowedListPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        if ($h -cmatch '^[0-9a-f]{64}\z') {
            if (Write-PilotExclusive $allowedRecPath @("restricted_allowed_files_sha256=$h")) {
                $back = (New-Object System.Text.UTF8Encoding($false)).GetString([System.IO.File]::ReadAllBytes($allowedRecPath))
                $recOk = ($back -ceq ("restricted_allowed_files_sha256=" + $h + "`n")) -and ((Test-PilotAllowedHash $allowedListPath $allowedRecPath) -eq $true)
            }
        }
    }
}
catch {
    $recOk = $false
}
$h = $null
if ($recOk -eq $true) { "ALLOWED_FILE_HASH_RECORDED=True" } else { "STOP ALLOWED_FILE_HASH_RECORD=FAIL" }
```

Beklenen: **`ALLOWED_FILE_HASH_RECORDED=True`**. Başka her sonuç — kayıt zaten
mevcut (`CreateNew` reddi), yazma veya okuma hatası, desen uyuşmazlığı, read-back
farkı — **DUR** (H56): kayıt silinmez, yeniden üretilmez ve üzerine yazılmaz;
durum raporlanır ve yeni inceleme beklenir. Bu bloğun kendisi `<restricted-dir>`'e
hiçbir şey yazmaz; kayıt yalnız `<evidence-dir>` altındadır. Hash kaydı
`ALLOWED_FILE_HASH_RECORDED=True` olmadan intake başlatılmaz.

Envanter kontrolü (önce kaydın yeniden doğrulanması, madde 4):

```powershell
$allowedHashOk = Test-PilotAllowedHash "<evidence-dir>\restricted-allowed-files.txt" "<evidence-dir>\restricted-allowed-files.sha256.txt"
"ALLOWED_FILE_HASH_OK=$allowedHashOk"
$allowedLines = @(); $rState = $null
if ($allowedHashOk -eq $true) { try { $allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false)))); $rState = Get-PilotRestrictedState "<restricted-dir>" } catch { $allowedLines = @(); $rState = $null } }
$allowedSet = @($allowedLines | Select-Object -Skip 1)
$rUnexpected = @($rState.Files | Where-Object { $allowedSet -cnotcontains $_.Name }).Count
if (($allowedHashOk -eq $true) -and ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and ($null -ne $rState) -and ($rState.Bad -eq 0) -and ($rUnexpected -eq 0)) { "RESTRICTED_INVENTORY=OK"; "RESTRICTED_FILE_COUNT=$($rState.Files.Count)" } else { "STOP RESTRICTED_INVENTORY=FAIL" }
```

Beklenen: `RESTRICTED_ALLOWED_RECORD=WRITTEN` (bir kez) ve her envanterde
`ALLOWED_FILE_HASH_OK=True` ile `RESTRICTED_INVENTORY=OK`.
`ALLOWED_FILE_HASH_OK=False` envanteri geçersiz kılar: **DUR** (H56). Komutlar
dosya adı, yol, hash veya içerik basmaz;
yalnız sabit durum satırı ve dosya sayısı basar. Envanter `-Force` ile gizli
ve sistem öğelerini de kapsar.

---

## 11. Manuel intake ve iki katmanlı doğrulama (P5)

### 11.1 İlke

Manuel intake concierge tasarımının parçasıdır. `case.json` için koordineli
bir production writer **bulunmaması** (Adım 7 kapanışı, K3) tek başına bir kod
bloklayıcısı değildir; bunun yerine intake iki bağımsız katmanla doğrulanır.
**Mekanik kontrol ile avukat kontrolü birbirinin yerine geçmez**; ikisi de
zorunludur. Operatörün yazdığı her alan, avukat orijinal belgeye karşı
**alan-alan yazılı olarak doğrulamadan** kullanılamaz (§11.4).

### 11.2 Intake adımları (operatör, insan-only oturum)

1. Ön kontrol: `<case-root>` **mevcut değildir**; varsa **DUR**. Ebeveyni
   `<repo-root>\data\cases` §13.8 yol kapısından geçmiştir ve bu oturumda
   `PATH_OK=external-root-contract` alınmıştır; alınmadıysa intake
   başlatılmaz, **DUR** (H52).
2. `<case-root>` altında `case.json`, `documents/<document-id>/document.json`,
   orijinal belge dosyası ve `documents/<document-id>/extracted/<document-id>.txt`
   oluşturulur. `document.json` içindeki `file.relative_path` değeri
   `cases/<case-id>/documents/<document-id>/` önekini ve `file.file_name`
   değerini taşır (`src/case_document_validator.py`, `validate_file_paths`).
3. **JSON dosyaları BOM'suz UTF-8'dir.** Motor JSON'u `utf-8` ile açar,
   `utf-8-sig` ile değil (`src/fact_extraction_engine.py`, `load_json`);
   verification katmanı da `document.json` baytlarını `utf-8` olarak çözer
   (`ui/services/fact_verification_mutation_facade.py`). Windows PowerShell'in
   `Set-Content -Encoding UTF8` ve `Out-File -Encoding utf8` komutları BOM
   yazar; JSON dosyaları bu komutlarla **yazılmaz**. Kontrol:

```powershell
foreach ($f in @("<case-root>\case.json", "<case-root>\documents\<document-id>\document.json")) { $b = [System.IO.File]::ReadAllBytes($f); if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { Write-Output "STOP JSON_BOM=PRESENT" } else { Write-Output "JSON_BOM=NONE" } }
```

   Beklenen: iki kez **`JSON_BOM=NONE`**. Başka her çıktı **DUR**'dur.
4. **Metin dosyası.** Yolu, fact extraction motorunun **gözlemlenen
   konvansiyonudur** (`src/fact_extraction_engine.py`,
   `get_extracted_text_path`); şema tarafından zorlanan bir garanti
   **değildir**. Dosya UTF-8 olarak, BOM'suz yazılır (motor metni `utf-8-sig`
   ile okur ve BOM'u tolere eder). Metin boş olamaz ve **60.000 karakteri
   aşamaz** (`MAX_INPUT_CHARS`); maskelenmiş metin de aynı sınıra tabidir
   (`assert_masked_length_within`). Ön kontrol:

```powershell
$txt = [System.IO.File]::ReadAllText("<case-root>\documents\<document-id>\extracted\<document-id>.txt", [System.Text.Encoding]::UTF8)
if ($txt.Length -gt 0 -and $txt.Length -le 60000) { Write-Output "TEXT_LENGTH=OK" } else { Write-Output "STOP TEXT_LENGTH=OUT_OF_RANGE" }
```

   Bu sayım UTF-16 birimiyledir ve motorun karakter sayımından küçük olamaz;
   kontrol muhafazakârdır. Kesin sınırı motor uygular.
5. **Metin çıkarma** yalnız §4.2/3'teki onaylı, yerel ve çevrimdışı araçla
   yapılır.
6. `case.json` `parties[]` dizisi, belgede geçen bütün gerçek kişi ve özel
   hukuk tüzel kişisi taraflarını `party_type` `individual` veya `company`
   ile ve tam yazımıyla içerir (maskeleme tohumu, §15.2). `party_type`
   `other` olan bir tarafın adı tohuma **girmez**; gerçek kişi veya şirket
   `other` olarak yazılmaz. Kamu kurumları `public_authority` olarak yazılır.
7. Intake dosyalarındaki **bütün** `verification_state` alanları `unverified`
   yazılır. Doğrulama durumunu yükseltmek yalnız koordineli Fact Verification
   Workflow ile ve avukat kararıyla yapılır (`CLAUDE.md` §8). Bu alanların
   deadline hesabına etkisi bu runbook için satır düzeyinde izlenmemiştir;
   kural bu yüzden fail-closed yazılmıştır.
8. `document.json` içinde `active` değeri `true` olmalıdır; verification
   evidence belgesi olarak kullanılabilmesi buna bağlıdır (§19.3).

### 11.3 Katman 1 — mekanik kontroller

Her biri ilk preview'dan **önce**, insan-only oturumda ve sonucu evidence'a
yazılarak yapılır.

**(a) Orijinal belge hash'i.** `case-document validator` fiziksel dosyayı veya
`file.sha256` alanını **denetlemez** (`validate_file_paths` içindeki "V1'de
sadece bilgi amaçlı" notu); şema `file.sha256` için `null` değerine izin
verir. Bu karşılaştırma bu yüzden **operatörün zorunlu adımıdır**:

```powershell
$docPath = "<case-root>\documents\<document-id>\document.json"
$doc = [System.IO.File]::ReadAllText($docPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$declared = [string]$doc.file.sha256
if ($declared -notmatch '^[0-9a-fA-F]{64}$') { Write-Output "STOP sha256 beyani yok veya gecersiz" } else { $orig = (Resolve-Path -LiteralPath (Join-Path "<repo-root>\data" $doc.file.relative_path)).Path; $actual = (Get-FileHash -LiteralPath $orig -Algorithm SHA256).Hash; if ($actual.ToLowerInvariant() -eq $declared.ToLowerInvariant()) { Write-Output "INTAKE_HASH=MATCH" } else { Write-Output "STOP INTAKE_HASH=MISMATCH" } }
```

Bu komut dosya adını veya yolunu basmaz. Beklenen: **`INTAKE_HASH=MATCH`**.
Başka her çıktı **DUR**'dur.

**(b) Metin dosyası ve orijinal belge hash'i — kayıt ve yeniden
karşılaştırma.** `extracted/<document-id>.txt` dosyasının ve orijinal belge
dosyasının SHA-256'ları intake'te, (a) `INTAKE_HASH=MATCH` verdikten sonra
**bir kez** hesaplanır ve stdout'a basılmadan, yalnız genel etiketlerle
`<evidence-dir>\intake-hashes.tsv` dosyasına exclusive-create ile yazılır
(§10.5'teki `Write-PilotExclusive`). Avukatın intake onayı (Katman 2) bu
kayıttaki metin hash'ine bağlanır. Her iki yol da mutlak, canonical, normal
dosya olmalı ve kendisi ile üst dizinleri reparse point olmamalıdır
(§13.8'deki `Test-PilotLeafFile`); orijinal belgenin yolu ayrıca
`<case-root>\documents\<document-id>\` altında olmalıdır.

Ortak hedef tanımı (her iki komuttan önce, aynı oturumda):

```powershell
$hashDoc = [System.IO.File]::ReadAllText("<case-root>\documents\<document-id>\document.json", [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$hashOrig = [System.IO.Path]::Combine("<repo-root>\data", ([string]$hashDoc.file.relative_path).Replace('/', '\'))
$hashText = "<case-root>\documents\<document-id>\extracted\<document-id>.txt"
$hashPathsOk = (Test-PilotLeafFile $hashOrig) -and (Test-PilotLeafFile $hashText) -and $hashOrig.ToLowerInvariant().StartsWith(("<case-root>\documents\<document-id>\").ToLowerInvariant())
```

Kayıt (intake'te, bir kez):

```powershell
if ($hashPathsOk -and (Write-PilotExclusive "<evidence-dir>\intake-hashes.tsv" @('# kind=intake-hashes', ("original`t" + (Get-FileHash -LiteralPath $hashOrig -Algorithm SHA256).Hash.ToLowerInvariant()), ("extracted-text`t" + (Get-FileHash -LiteralPath $hashText -Algorithm SHA256).Hash.ToLowerInvariant())))) { "INTAKE_HASHES_RECORDED=True" } else { "STOP INTAKE_HASHES_RECORDED=False" }
```

Yeniden karşılaştırma (preview'dan önce ve §18.1/2 gereği POST'tan önce):

```powershell
$hashRec = @([System.IO.File]::ReadAllLines("<evidence-dir>\intake-hashes.tsv", (New-Object System.Text.UTF8Encoding($false))))
$hashMatch = $hashPathsOk -and ($hashRec.Count -eq 3) -and ($hashRec[0] -ceq '# kind=intake-hashes') -and ($hashRec[1] -ceq ("original`t" + (Get-FileHash -LiteralPath $hashOrig -Algorithm SHA256).Hash.ToLowerInvariant())) -and ($hashRec[2] -ceq ("extracted-text`t" + (Get-FileHash -LiteralPath $hashText -Algorithm SHA256).Hash.ToLowerInvariant()))
if ($hashMatch) { "SOURCE_HASHES_MATCH=True" } else { "STOP SOURCE_HASHES_MATCH=False" }
Remove-Variable hashDoc, hashOrig, hashText, hashPathsOk, hashRec, hashMatch -ErrorAction SilentlyContinue
```

Komutlar hash değerini veya gerçek yolu stdout'a **basmaz**; yalnız eşitlik
boolean'ını basar. `SOURCE_HASHES_MATCH=True` dışındaki her sonuç: preview
veya POST **yapılmaz**, **DUR** (H16). Kayıt dosyası yalnız genel etiket ve
hash taşır; §28.2'deki parmak izi notu ona da uygulanır.

**(c) Case validator.** Argüman `case.json` yoludur (`src/case_validator.py`,
`main`):

```powershell
& "<python>" -m src.case_validator "<case-root>\case.json"
```

**(d) Case-document validator.** Argüman case dizinidir
(`src/case_document_validator.py`, `main`):

```powershell
& "<python>" -m src.case_document_validator "<case-root>"
```

**Argümansız validator çağrısı YASAKTIR.** Argüman verilmezse iki validator da
sessizce `data/cases/case_0001` fixture'ını doğrular (`DEFAULT_CASE_PATH`,
`DEFAULT_CASE_DIR`) ve pilot dosyası hakkında hiçbir şey söylemeyen bir PASS
basar. Her çağrıdan sonra çıktının başında basılan yolun `<case-root>` altını
gösterdiği ve `Case ID:` satırının `<case-id>` olduğu doğrulanır; değilse
**DUR**.

Validator'lar hata durumunda istisna yükseltir; bu runbook onlara ayrı bir
çıkış-kodu sözleşmesi **atfetmez**. "Hatasız" şu demektir: traceback yok,
hata satırı yok, uyarı satırı yok. Validator çıktısı kimlik ve yol taşır;
evidence'a **yalnız** `PASS`/`FAIL` ve hata/uyarı **sayısı** yazılır, metni
yazılmaz. Herhangi bir hata **DUR**'dur; herhangi bir uyarı, avukat ile
kullanıcı onu yazılı olarak kabul edilebilir saymadıkça **DUR**'dur.

**(e) Ignore ve tracked sınırı.**

```powershell
git status --porcelain -- data/cases/case_0001
git status --ignored --porcelain -- data/cases
git check-ignore -v "data/cases/<case-id>/case.json"
```

Beklenen: ilk komut **boş**; ikinci komut **yalnız** `!! data/cases/<case-id>/`;
üçüncü komut `.gitignore` içindeki `/data/cases/` kuralını gösterir. `??`
öneki veya `case_0001` için herhangi bir çıktı **DUR**'dur. Bu üç komut repo
köküne göreli yol kullanır; oturumun konumu §13.8'de `<repo-root>` olarak
doğrulanmış olmalıdır.

**(f) Vergi türü sözlük kontrolü.** Mali tatil sınıflandırması,
`dispute_items[].tax_type` değerlerini iki dar sözlüğe karşı **exact**
eşleştirir (`src/deadline_calculator.py`, `MALI_TATIL_INCLUDED_TAX_TYPES`,
`MALI_TATIL_EXCLUDED_TAX_TYPES`, `classify_mali_tatil_tax_type`). Sözlükte
olmayan veya boş bir değer `unrecognized`, dahil ve istisna terimlerinin
karışması `mixed` sayılır; sayım penceresi mali tatille ilişkiliyse sonuç
`needs_review` olur ve kesin tarih üretilmez. Pencerenin ilişkili olup
olmadığını operatör yorumlayamaz; bu yüzden bu runbook sözlük uyumunu **her
dosyada** ve **gerçek inference'tan önce** şart koşar. Kontrol fact
extraction'dan sonraya **bırakılmaz**.

Kaynaktaki sözlük, birebir:

- Dahil (11): `katma değer vergisi`, `kdv`, `kurumlar vergisi`,
  `gelir vergisi`, `damga vergisi`, `veraset ve intikal vergisi`,
  `motorlu taşıtlar vergisi`, `mtv`, `vergi ziyaı cezası`,
  `usulsüzlük cezası`, `özel usulsüzlük cezası`.
- İstisna (7): `özel tüketim vergisi`, `ötv`,
  `banka ve sigorta muameleleri vergisi`, `bsmv`, `özel iletişim vergisi`,
  `öiv`, `şans oyunları vergisi`.

Kaynak, karşılaştırmadan önce büyük/küçük harfi katlar; bu runbook daha dar
davranır ve `tax_type` değerlerinin intake'te yukarıdaki yazımla **birebir,
küçük harfle** yazılmasını ister. Kontrol değer basmaz:

```powershell
$taxIncluded = @('katma değer vergisi', 'kdv', 'kurumlar vergisi', 'gelir vergisi', 'damga vergisi', 'veraset ve intikal vergisi', 'motorlu taşıtlar vergisi', 'mtv', 'vergi ziyaı cezası', 'usulsüzlük cezası', 'özel usulsüzlük cezası')
$taxExcluded = @('özel tüketim vergisi', 'ötv', 'banka ve sigorta muameleleri vergisi', 'bsmv', 'özel iletişim vergisi', 'öiv', 'şans oyunları vergisi')
$caseDoc = [System.IO.File]::ReadAllText("<case-root>\case.json", [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$taxItems = @($caseDoc.dispute_items)
$taxUnknown = @($taxItems | Where-Object { ($taxIncluded + $taxExcluded) -cnotcontains [string]$_.tax_type }).Count
$taxInc = @($taxItems | Where-Object { $taxIncluded -ccontains [string]$_.tax_type }).Count
$taxExc = @($taxItems | Where-Object { $taxExcluded -ccontains [string]$_.tax_type }).Count
if ($taxItems.Count -ge 1 -and $taxUnknown -eq 0 -and -not ($taxInc -gt 0 -and $taxExc -gt 0)) { "TAX_TYPE_VOCAB=OK" } else { "STOP TAX_TYPE_VOCAB=FAIL" }
```

Beklenen: **`TAX_TYPE_VOCAB=OK`** ve her değerin avukatın §8/8'deki yazılı
sınıflandırmasıyla aynı olması. Değer tanınmıyorsa, karışıksa veya avukatın
sınıflandırmasıyla eşleşmiyorsa: model POST'u **yapılmaz**, tek gönderim hakkı
**harcanmaz**, **DUR** (H51).

### 11.4 Katman 2 — avukatın alan-alan kontrolü

Avukat, orijinal belgeyi elindeki kaynakla karşılaştırarak aşağıdakilerin her
birini **ayrı ayrı ve yazılı** olarak onaylar. Operatör bu alanları yazabilir,
ancak hiçbiri avukat onayı olmadan kullanılamaz.

**Metin ve taraflar:**

1. `extracted/<document-id>.txt` metninin (hash'iyle tanımlanan sürüm)
   orijinal belgeyi doğru ve eksiksiz aktardığı.
2. `case.json` `parties[]` kayıtlarının (ad, rol, `party_type`) doğru ve
   eksiksiz olduğu.

**Deadline kural seçimini veya hesabını etkileyen alanlar** (kaynak:
`src/deadline_rule_selection_policy.py`, `build_case_context` ve
`rule_matches_context`; `src/deadline_calculator.py`):

| Alan | Dosya | Kaynaktaki etkisi |
|---|---|---|
| `document_type` | `document.json` | Kural uygulanabilirliği: anchor olayının kaynak belgesinin türü kuralın `document_types` listesiyle eşleşmelidir |
| `dispute_items[].tax_type` | `case.json` | Kuralın `tax_types` filtresi ve mali tatil m.1/7 istisna sınıflandırması; değer §11.3 (f) sözlüğünden birebir bir terim olmalı ve avukatın yazılı sınıflandırmasıyla eşleşmelidir |
| `administrative_actions[].issuing_authority` | `case.json` | Mali tatil istisna kontrolü (gümrük, belediye, il özel idaresi anahtar sözcükleri) |
| `administrative_actions[].action_category` | `case.json` | Stopping-event beyanıyla çelişki kontrolü (`settlement`, `correction_complaint`) |
| `case_type` / `dispute_type` | `case.json` | Kuralın `case_types` filtresi |
| `stage` / `case_stage` / `procedural_stage` ve `proceedings` içindeki `stage`, `status`, `case_stage` | `case.json` | Kuralın `case_stages` filtresi |

Bugünkü tek aktif kuralda `case_types`, `tax_types` ve `case_stages` listeleri
boştur ve boş liste kaynakta joker sayılır (`applicability_matches`); bu üç
filtre bugün seçimi daraltmaz, ama alanlar yine de hukuki sınıflandırmadır ve
`tax_type` ile `issuing_authority` mali tatil hesabını doğrudan etkiler.

**Diğer hukuki sınıflandırma ve tarih alanları:**

3. `dispute_items[].period` ve `asserted_legal_basis_refs` (ikisi de modele
   giden bağlamdadır).
4. `document.json` içindeki `document_category`, `document_subtype`,
   `issuer_party_id`, `dates[]` ve `reference_numbers[]`.
5. `administrative_actions[]` içindeki `action_type`, `action_date` ve
   `notification_date`. Tebliğ tarihinin belgedeki tarihle aynı olduğu burada
   onaylanır; bu, §19.3'teki verification kararının **girdisidir**, onun
   yerine **geçmez**. Deadline'ın anchor'ı bu alandan değil, doğrulanmış
   fact'ten türeyen timeline olayından gelir (§20); `notification_date`
   alanının hesaba doğrudan etkisi bu runbook için satır düzeyinde
   izlenmemiştir.
6. `events[]` ve `proceedings` alanlarına intake'te veri girildiyse her biri.
7. Bütün `verification_state` alanlarının `unverified` olduğu (§11.2/7).

Yazılı onay repo dışında saklanır; evidence'a yalnız hash ve kişisel veri
içermeyen kapsam özeti girer. Avukat onayı yoksa veya bir alan onaysızsa:
**DUR.**

---

## 12. IAM aktörü ve yazılı avukat kararları (P4)

### 12.1 Avukat kararları

Aşağıdakiler **avukatın yazılı kararıdır**; operatör onları **birebir**
uygular, yorumlamaz, tamamlamaz:

| Karar | Uygulandığı yer |
|---|---|
| Fact kabulü (bütün fact'ler) | §19.2, `promotion --row-key fact` |
| Tebliğ tarihi fact'inin verification'ı | §19.3, `verification` |
| Adli tatil uygulanabilirliği | §22.1, `--judicial-recess-applicable` |
| Stopping-event beyanı ve referansı | §21.1, `--stopping-event-status`, `--stopping-event-attestation-ref` |
| Deadline onayı | §22.4, `approval --row-key deadline` |

Adli tatil uygulanabilirliği P4'ün sayılan dört kararından biri değildir; bu
runbook onu `CLAUDE.md` §11'den ("uygulanabilirliği varsayamaz") türeterek
avukat kararı sayar.

### 12.2 IAM aktörünün anlamı (dürüst sınır)

- Mutasyonlar Adım 8'de oluşturulan **mevcut** avukat kullanıcısı
  (`<actor-user-id>`) ile yapılır.
- Bu aktör avukatın **gerçek kimliğini veya elektronik imzasını kanıtlamaz**;
  yalnız concierge operasyon aktörüdür (`ui/cli_mutate.py` başlığı:
  "trusted-local-shell, NOT cryptographic OS identity").
- Yazılı kararlar repo dışında saklanır; evidence'a yalnız hash ve redakte
  kapsam özeti girer.

### 12.3 Assignment (ADMIN oturumu, tek çalıştırma)

Assignment mümkün olan **en geç** aşamada verilir: intake, mekanik kontroller,
avukatın intake onayı ve maskeleme tohumu teyidi (zincir adım 6–8)
tamamlandıktan sonra ve ilk veritabanlı preview'dan (zincir adım 10) **hemen
önce**. Yerel
validator'lar ve hash kontrolleri veritabanı veya assignment gerektirmez.

```powershell
& "<python>" -m scripts.iam_admin assign-case --user-id <actor-user-id> --case-id <case-id> --role lawyer --actor-user-id <admin-user-id>
```

Komut ayrı kullanıcı onayıyla ve **bir kez** çalıştırılır; sonuç belirsizse
§27.2'ye göre **DUR**.

### 12.4 İşlem türüne göre oturum ve IAM beklentisi

İki veritabanı rolü **asla aynı PowerShell oturumunda** bulunmaz
(`docs/operations/local-postgresql-iam-adoption.md` §G.1, §G.2).

| İşlem | Oturum (DB rolü) | IAM aktörü | Beklenti |
|---|---|---|---|
| `assign-case`, `revoke-assignment` | ADMIN (`vergi_iam_admin`) | `--actor-user-id <admin-user-id>` | Aktör global `admin`; `admin` rolü tek başına case içeriği yeteneği taşımaz (aynı runbook §J.5) |
| Preview (`generation`, `promotion`, `verification`, `approval`) | APP (`vergi_app`) | `--actor-user-id <actor-user-id>` | Aktör mevcut, `disabled = false`, case için aktif `lawyer` assignment'ı var |
| Apply / approve | APP (`vergi_app`) | `--actor-user-id <actor-user-id>` | Aynı; `lawyer` rolü `read` ve `mutate` taşır |
| `ui.deadline_report` | APP (`vergi_app`), salt-okunur transaction | `--actor-user-id <actor-user-id>` | Aktif assignment rolü tam olarak `lawyer` (`ui/deadline_report.py` başlığı) |
| Salt-okunur SQL (journal, assignment, kullanıcı) | APP (`vergi_app`) | — | `vergi_app` bu tablolarda `SELECT` yetkisine sahiptir (aynı runbook §I.3) |

`vergi_iam_admin` rolünün `mutation.mutation_journal` üzerinde **hiçbir
yetkisi yoktur** (aynı runbook §I.4); bu yüzden rapor ve journal sorguları
ADMIN oturumunda **koşulmaz**.

---

## 13. Pilot DB ve çalışma ortamı preflight'ı

### 13.1 İlke

Kümenin açık veya kapalı olduğu **varsayılmaz**; harness'in, runtime'ın veya
ortamın "değişmediği" de **varsayılmaz**. Her operasyon oturumunun başında ve
her mutasyondan önce durum **mekanik olarak ölçülür** ve sonucu evidence'a
yazılır.

### 13.2 Repo durumu

```powershell
git branch --show-current
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=all
git status --ignored --porcelain -- data/cases
git ls-files --error-unmatch docs/operations/concierge-real-case-pilot.md
```

Beklenen: branch `claude-dev`; HEAD, yürütme yetkisinde kullanıcının
onayladığı commit; çalışma ağacı temiz; ignored görünümde intake'ten önce
**hiçbir girdi**, intake'ten sonra **yalnız** `!! data/cases/<case-id>/`; son
komut hatasız (runbook tracked). Aksi **DUR**.

### 13.3 Yorumlayıcı

`<python>`, Adım 9A'da offline kurulan, repo dışındaki concierge runtime'ın
yorumlayıcısıdır (Adım 9 checkpoint'i §C). Yürütme oturumunda `pip check`
yeniden ölçülür; sonuç `No broken requirements found` değilse **DUR**.
Runtime'ın paket kümesi §13.7'ye göre ayrıca karşılaştırılır.

### 13.4 Küme ve oturumlar

- Küme, Adım 8'in kalıcı, yalnız-loopback, servissiz kümesidir. Başlatma,
  durdurma ve durum ölçümü
  `docs/operations/local-postgresql-iam-adoption.md` §D'ye göre yapılır.
  Küme bir servis değildir; pencere kapanırsa durur — bu yüzden her adımdan
  önce yeniden ölçülür.
- ADMIN ve APP oturumları aynı runbook'un §G.2'sine göre **ayrı PowerShell
  oturumlarında** kurulur. Bağlantı dizesi ve kimlik bilgisi dosyası bu
  belgeye ve evidence'a yazılmaz.
- İçeriğe dokunan bütün oturumlar insan-only oturumlardır (§4.2) ve §4.3
  (b)'ye göre `-NoProfile` ile açılır.

### 13.5 Salt-okunur SQL sözleşmesi ve DB kontrolleri (APP oturumu)

**Sözleşme (bağlayıcı):**

1. Bu runbook'taki SQL yalnız **ölçüm** içindir: yalnız `SELECT` ve durumu
   okuyan `SHOW` içerir. IAM mutasyonu yalnız canonical IAM CLI ile
   (`scripts.iam_admin`; §12.3, §27.1), journal yazımı yalnız `ui.cli_mutate`
   ile yapılır. **Düzeltici SQL yasaktır**: `INSERT`, `UPDATE`, `DELETE` veya
   DDL hiçbir koşulda çalıştırılmaz.
2. Sorgular **APP oturumunda** (`vergi_app`) çalıştırılır. Bağlantı bilgisi
   yalnız o oturumun `VERGI_IAM_DATABASE_URL` değişkeninden okunur
   (`docs/operations/local-postgresql-iam-adoption.md` §G.1, §G.2). Komut ve
   SQL metni parola, kimlik bilgisi dosyası yolu veya bağlantı dizesi
   **içermez**; yalnız değişkenin **adı** ve opak kimlikler geçer.
3. Her çağrı açık bir **salt-okunur transaction** içinde koşar:
   `BEGIN TRANSACTION READ ONLY`, ardından `SHOW transaction_read_only`,
   ardından **tek** bir `SELECT`, ardından `ROLLBACK`. `psql` süreci çıkınca
   bağlantı kapanır. `SHOW` satırı `on` değilse sonuç kullanılmaz: **DUR**
   (H54). `ui/deadline_report.py` aynı koşulu kendi bağlantısında zorlar.
4. Çağırma biçimi ve çıkış/çıktı sözleşmesi. Çıktı önce bir değişkene
   alınır, çıkış kodu **hemen** yakalanır; `-q` (quiet) `BEGIN` ve
   `ROLLBACK` komut etiketlerini bastırır, `-A -t` başlık ve altbilgiyi
   kaldırır. Böylece çıktının ilk satırı yalnız `SHOW` sonucu, kalan satırlar
   yalnız `SELECT` sonucudur:

```powershell
$psqlOut = @(& "<psql>" --dbname="$env:VERGI_IAM_DATABASE_URL" --no-password --no-psqlrc -v ON_ERROR_STOP=1 -q -A -t -c "BEGIN TRANSACTION READ ONLY" -c "SHOW transaction_read_only" -c "<select-statement>" -c "ROLLBACK")
$psqlRc = $LASTEXITCODE
$psqlReadOnly = ($psqlOut.Count -ge 1) -and ($psqlOut[0] -ceq 'on')
if (($psqlRc -eq 0) -and $psqlReadOnly) { "PSQL_EXIT=0"; "PSQL_READ_ONLY=True"; $psqlRows = @($psqlOut | Select-Object -Skip 1); "PSQL_ROW_COUNT=$($psqlRows.Count)"; foreach ($row in $psqlRows) { "PSQL_ROW=$row" } } else { "STOP PSQL_EXIT_OR_READ_ONLY=FAIL" }
Remove-Variable psqlOut, psqlRows, row -ErrorAction SilentlyContinue
```

   - `PSQL_EXIT` 0 değilse veya `PSQL_READ_ONLY=True` basılmadıysa sonuç
     **kullanılmaz**: **DUR** (H54). `STOP` dalında sorgu sonucu basılmaz.
   - `PSQL_ROW` satırları yalnız ekranda okunur ve bu bölümdeki beklenti
     tablosuyla karşılaştırılır. Evidence'a **yalnız** çıkış kodu,
     read-only boolean'ı ve izin verilen sayaçlar (sayım sonuçları, satır
     sayısı, journal `state` değerleri, beklentiyle eşleşme boolean'ı)
     yazılır. Bağlantı dizesi, kimlik bilgisi dosyası, gerçek case değeri ve
     sorgu sonucunun başka içeriği evidence'a veya bir dosyaya **yazılmaz**.
   - `psql`'in stderr çıktısı yönlendirilmez ve dosyaya yazılmaz; bağlantı
     hatası ayrıntısı taşıyabilir.

**Türetim ve sınır (dürüst).** Bu biçim, Adım 8 runbook'unun kendi `psql`
çağrısından (`--dbname` ile parolasız URI, `--no-password`, `ON_ERROR_STOP`;
aynı runbook §H.2) ve §G.2'deki oturum değişkeninden türetilmiştir. Adım 8
runbook'u APP oturumundaki sorgular için exact bir komut **yazmaz**; yukarıdaki
satır canlı kümede **denenmemiştir**. Bu yüzden §1.5'teki provada **bağlantı
açılmadan** statik olarak kontrol edilir: komut satırı bu belgedekiyle birebir
aynıdır; `<psql>` yolu §13.8'den geçer; kullanılan her bayrak (`-q`, `-A`,
`-t` dahil) `<psql>`'in `--help` çıktısında bulunur. `-q`'nun komut
etiketlerini bastırdığı ve çıkış kodunun hata hâlinde 0 olmadığı
`psql`'in kendi davranışıdır, repo kaynağından gelmez; canlı kümedeki ilk
kullanımda ilk satır `on` değilse sonuç **DUR**'dur, yorumlanmaz. Bağlantı
dizesi `psql` sürecinin argümanı olarak geçer (parola içermez);
süreç-argümanı telemetri sınırı §4.2/9'dadır.

**Kontroller.** Aşağıdaki her ifade yukarıdaki biçimle, `<select-statement>`
yerine konarak ayrı ayrı çalıştırılır:

```sql
SELECT count(*) FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>';
```

```sql
SELECT count(*) FROM mutation.mutation_journal WHERE state IN ('prepared', 'executing', 'reconciliation_required');
```

```sql
SELECT count(*) FROM iam.case_assignments WHERE case_id = '<case-id>' AND revoked_at IS NULL;
```

```sql
SELECT count(*) FROM iam.case_assignments WHERE case_id = '<case-id>';
```

```sql
SELECT id, disabled FROM iam.users WHERE id IN (<actor-user-id>, <admin-user-id>) ORDER BY id;
```

Beklenti ölçüm noktasına göre **farklıdır**:

| Ölçüm noktası | Case journal satırı | Çözülmemiş journal satırı | Aktif assignment | Toplam assignment satırı |
|---|---|---|---|---|
| `assign-case` öncesi (zincir adım 5 ve 9) | 0 | 0 | 0 | 0 |
| Assignment sonrası, her preview ve apply öncesi | O ana kadar tamamlanan apply sayısı; hepsi `completed` | 0 | 1 | 1 |
| Revoke sonrası (zincir adım 27) | Değişmedi | 0 | 0 | 1 |

Her ölçüm noktasında iki kullanıcı mevcut ve `disabled = false` olmalıdır.
Aksi **DUR**.

### 13.6 Ortam değişkenleri ve `.env` (bağlayıcı)

Fact extraction motorunun production dalı, `src/fact_extraction_engine.py`
içindeki `call_llm` fonksiyonunda repo kökündeki `.env` dosyasını yükler
(`load_dotenv`, `override` verilmeden) ve ardından `ANTHROPIC_API_KEY`
değişkenini okur; repo kökünde ignored bir `.env` dosyası **mevcuttur**. Bu
runbook dotenv'in hangi değerin öncelikli olduğuna dair davranışını bir
güvenlik özelliği olarak **kabul etmez**.

**(a) `.env` — içeriği okunmaz.** Dosya ya **mevcut değildir** ya da **tam 0
bayttır**:

```powershell
if (Test-Path -LiteralPath "<repo-root>\.env") { "ENV_FILE_BYTES=$((Get-Item -LiteralPath "<repo-root>\.env" -Force).Length)" } else { "ENV_FILE=ABSENT" }
```

Beklenen: `ENV_FILE=ABSENT` veya `ENV_FILE_BYTES=0`. Boyut sıfırdan büyükse
**DUR**. Dosya açılmaz, içeriği veya anahtar adları okunmaz. `.env` üzerinde
herhangi bir değişiklik bu runbook'un adımı **değildir**; ayrı bir kullanıcı
onayı ve ayrı bir tur gerektirir.

**(b) Üç kapsamda değişken adları — değerler okunmaz, basılmaz.**

```powershell
$pattern = '^(ANTHROPIC_.*|.*PROXY.*|SSL_.*|.*CA_BUNDLE.*|.*CA_CERTS.*|SSLKEYLOGFILE|PYTHONHTTPSVERIFY|PG.*)$'
foreach ($scope in 'Process', 'User', 'Machine') { $names = @([System.Environment]::GetEnvironmentVariables($scope).Keys | Where-Object { $_ -match $pattern } | Sort-Object); "ENV_SCOPE=$scope MATCH_COUNT=$($names.Count)"; foreach ($n in $names) { "ENV_NAME=$scope/$n" } }
```

Eşleşme büyük/küçük harfe duyarsızdır; komut yalnız **ad** basar. Kapsam:
bütün `ANTHROPIC_*` adları; büyük ve küçük harfli proxy değişkenleri;
sertifika/CA ve TLS anahtar-kaydı değişkenleri; bütün `PG*` adları
(`PGPASSWORD` ve `PGPASSFILE` bu projede zaten yasaktır —
`docs/operations/local-postgresql-iam-adoption.md` §A.3).

| Ölçüm noktası | Process | User | Machine |
|---|---|---|---|
| Anahtar ayarlanmadan önce (her oturum başı) | 0 eşleşme | 0 eşleşme | 0 eşleşme |
| Anahtar ayarlandıktan sonra, probe ve POST öncesi | Tam 1: `ANTHROPIC_API_KEY` | 0 eşleşme | 0 eşleşme |
| Temizlikten sonra, yeni oturumda | 0 eşleşme | 0 eşleşme | 0 eşleşme |

Tabloda izin verilen tek ad dışındaki her eşleşme **DUR**'dur. Adım 9'dan
kalan kullanıcı kapsamındaki `ANTHROPIC_API_KEY` değişkeninin kaldırılması bu
runbook'un önkoşuludur. `VERGI_IAM_DATABASE_URL` ve `PYTHONIOENCODING` bu
desenin dışındadır ve beklenen değişkenlerdir.

**Dürüst sınır:** Windows'un kayıt defterindeki sistem proxy ayarı bu ad
taramasında görünmez; proxy'nin reddi harness sözleşmesine dayanır (§16.2/3).
Bu, repo kaynağından değil, işletim sisteminin genel davranışından gelen bir
nottur.

### 13.7 Harness ve runtime paritesi (bağlayıcı)

"Değişmedi" varsayımı **kullanılmaz**.

1. Egress harness, outer monitor, auth probe aracı, harness'in düz-değer
   (plain-values) ve politika dosyaları ile runtime'ın `pip freeze` çıktısı
   için **pinli SHA-256 değerleri veya bir manifest** gerekir.
2. Bu bileşenlerin her biri, kullanılmadan önce, Adım 9 kanıtındaki pinli
   kayda karşı **mekanik olarak** (SHA-256 ile) karşılaştırılır. Runtime için
   Adım 9 checkpoint'i §C'nin kaydettiği paket kümesi (41 manifest paketi ve
   `pip`, toplam 42 satır) esas alınır.
3. Pinli kayıt mevcut değilse veya karşılaştırma uyuşmuyorsa bileşen
   **kullanılmaz**; yeni bir bağımsız inceleme gerekir ve o olmadan **DUR**.
4. Bu bileşenlerin adları, sayısı ve çağırma biçimi repo içinden
   **doğrulanamaz**; hepsi repo dışındadır (Adım 9 checkpoint'i §D). Bu
   runbook onları tahmin etmez; harness'in kendi manifesti esas alınır.
5. Her gerçek ağ turu **yeni** bir evidence dizini kullanır
   (`<probe-evidence-dir>`, `<inference-evidence-dir>`); önceki bir turun
   dizini yeniden kullanılmaz.

### 13.8 Yol kapısı (bağlayıcı)

§1.4'teki dizin ve dosya yer tutucularının her biri **mutlak, canonical ve
önceden çözümlenmiş** bir yoldur. Kapı, her içerik oturumunun başında ve bir
yol ilk kez kullanılmadan önce çalıştırılır; yalnız ad ve `PATH_OK` /
`STOP PATH_FAIL` basar, yol **basmaz**.

Bir yol şu koşulların **hepsini** sağlar: köklüdür ve kendi tam çözümüne
birebir eşittir (göreli parça, `..` veya sürücü-göreli biçim yoktur); mevcut
bir dizindir; kendisi ve sürücü köküne kadar bütün üst dizinleri reparse point
(symlink veya junction) **değildir**; beklenen ebeveynin doğrudan alt
dizinidir.

```powershell
function Test-PilotPath([string]$name, [string]$path, [string]$expectedParent) { $ok = $false; if ([System.IO.Path]::IsPathRooted($path) -and (Test-Path -LiteralPath $path -PathType Container)) { $full = [System.IO.Path]::GetFullPath($path).TrimEnd('\'); $item = Get-Item -LiteralPath $full -Force; $reparse = $false; $cur = $item; while ($cur -ne $null) { if ($cur.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $reparse = $true }; $cur = $cur.Parent }; $parentOk = ($expectedParent -eq '') -or (($item.Parent -ne $null) -and ($item.Parent.FullName.TrimEnd('\') -eq $expectedParent.TrimEnd('\'))); $ok = ($full -eq $path.TrimEnd('\')) -and (-not $reparse) -and $parentOk }; if ($ok) { "PATH_OK=$name" } else { "STOP PATH_FAIL=$name" } }
```

Repo kökü ve oturum konumu:

```powershell
$top = (git rev-parse --show-toplevel).Replace('/', '\')
if ((Get-Location).Path -eq "<repo-root>" -and $top -eq "<repo-root>" -and [System.IO.Path]::GetFullPath("<repo-root>").TrimEnd('\') -eq "<repo-root>") { "PATH_OK=repo-root" } else { "STOP PATH_FAIL=repo-root" }
Test-PilotPath 'cases-parent' "<repo-root>\data\cases" "<repo-root>\data"
```

Repo dışı dizinler. Dört dizin `<external-root>`'un doğrudan alt dizinidir;
`<external-root>`'un kendi sözleşmesi aşağıdaki ortak yardımcılardan sonra
ayrıca denetlenir:

```powershell
Test-PilotPath 'external-root' "<external-root>" ''
Test-PilotPath 'evidence-dir' "<evidence-dir>" "<external-root>"
Test-PilotPath 'probe-evidence-dir' "<probe-evidence-dir>" "<external-root>"
Test-PilotPath 'inference-evidence-dir' "<inference-evidence-dir>" "<external-root>"
Test-PilotPath 'restricted-dir' "<restricted-dir>" "<external-root>"
```

Ortak yardımcılar (dosya yolları, §11.3 (b), §28.3 ve §28.5 bunları
kullanır; her oturumda yeniden tanımlanır):

```powershell
function Test-PilotNoReparse([string]$full) { $cur = Get-Item -LiteralPath $full -Force; while ($cur -ne $null) { if ($cur.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $false }; if ($cur -is [System.IO.FileInfo]) { $cur = $cur.Directory } else { $cur = $cur.Parent } }; return $true }
function Test-PilotLeafFile([string]$path) { if (-not [System.IO.Path]::IsPathRooted($path)) { return $false }; if ([System.IO.Path]::GetFullPath($path) -ne $path) { return $false }; if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }; return (Test-PilotNoReparse $path) }
function Test-PilotOverlap([string]$a, [string]$b) { $x = ([System.IO.Path]::GetFullPath($a).TrimEnd('\') + '\').ToLowerInvariant(); $y = ([System.IO.Path]::GetFullPath($b).TrimEnd('\') + '\').ToLowerInvariant(); return ($x.StartsWith($y) -or $y.StartsWith($x)) }
function Test-PilotResolved([string]$p) { try { if ([string]::IsNullOrWhiteSpace($p) -or $p.Contains('<') -or $p.Contains('>') -or (-not [System.IO.Path]::IsPathRooted($p))) { return $false }; return ([System.IO.Path]::GetFullPath($p).TrimEnd('\') -eq $p.TrimEnd('\')) } catch { return $false } }
```

`Test-PilotOverlap`, iki yol eşitse veya biri diğerinin üst dizini ise
`True` döner; yol çözümlenemezse istisna verir, bu yüzden §28.3 ve §28.5'te
yalnız `try` içinde ve `Test-PilotResolved`'dan sonra çağrılır.
`Test-PilotResolved`, yol tanımsız, boş, hâlâ `<...>` biçiminde, köksüz veya
canonical çözümüne eşit değilse ya da çözümleme istisna verirse `False`
döner; istisna metnini veya yolu basmaz.

**`<external-root>` sözleşmesi.** `<external-root>` mutlak ve canonical bir
dizindir; sürücü kökü **değildir**; `<repo-root>`'a eşit, onun altında veya
atası **değildir**; `<case-root>`, Temp kökü, `<python-runtime-root>` ve
`<pg-bin-dir>` ile örtüşmez; yalnız bu pilot için ayrılmıştır. Doğrudan
altında bulunmasına izin verilen çocuk kümesi, yer tutuculardan mekanik
olarak türetilir: `<evidence-dir>`, `<probe-evidence-dir>`,
`<inference-evidence-dir>` ve `<restricted-dir>` yaprak adları. Bu küme
dışındaki her dosya veya dizin — prova artefaktı, özet dosyası veya başka
bir iş yükü dahil — **DUR**'dur (H52). Kapı her içerik oturumunun başında ve
her durumda intake'ten **önce** çalıştırılır:

```powershell
function Test-PilotExternalRoot([string]$ext, [string]$repo, [string[]]$children, [string[]]$protected) { $ErrorActionPreference = 'Stop'; try { if (-not (Test-PilotResolved $ext) -or -not (Test-PilotResolved $repo) -or ($children.Count -lt 1)) { return $false }; $e = $ext.TrimEnd('\'); if ($e -eq [System.IO.Path]::GetPathRoot($ext).TrimEnd('\')) { return $false }; if (-not (Test-Path -LiteralPath $e -PathType Container) -or -not (Test-PilotNoReparse $e) -or (Test-PilotOverlap $e $repo)) { return $false }; foreach ($p in $protected) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $e $p)) { return $false } }; $leaves = @(); foreach ($c in $children) { if (-not (Test-PilotResolved $c) -or ([System.IO.Path]::GetDirectoryName($c.TrimEnd('\')) -ne $e)) { return $false }; $leaves += [System.IO.Path]::GetFileName($c.TrimEnd('\')) }; if (@($leaves | Sort-Object -Unique).Count -ne $leaves.Count) { return $false }; $names = @(Get-ChildItem -LiteralPath $e -Force -ErrorAction Stop | ForEach-Object { $_.Name }); return (@($names | Where-Object { $leaves -cnotcontains $_ }).Count -eq 0) } catch { return $false } }
$extOk = Test-PilotExternalRoot "<external-root>" "<repo-root>" @("<evidence-dir>", "<probe-evidence-dir>", "<inference-evidence-dir>", "<restricted-dir>") @("<case-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")
if ($extOk -eq $true) { "PATH_OK=external-root-contract" } else { "STOP PATH_FAIL=external-root-contract" }
```

Fonksiyon yalnız sabit durum satırı üretir; yol, ad veya istisna metni
basmaz. Sürücü kökü, repo kökü veya onun bir atası (ör. genel kullanıcı
dizini) verilirse kapı `False` döner ve hiçbir alt öğeyi temiz beklemeye
çalışmaz.

Dosya yolları. `<python>` ve `<psql>` mutlak, canonical, normal bir
dosyadır; dosya ve bütün üst dizinleri reparse point değildir; dosya adı
birebir beklenen addır; `<python>` `<python-runtime-root>` altında,
`<psql>` `<pg-bin-dir>`'in doğrudan altındadır. Kök dizinlerin kendisi de
canonical, mevcut ve reparse point'siz olmalıdır:

```powershell
function Test-PilotExe([string]$name, [string]$path, [string]$root, [string]$leaf, [bool]$directChild) { $ok = [System.IO.Path]::IsPathRooted($root) -and ([System.IO.Path]::GetFullPath($root).TrimEnd('\') -eq $root.TrimEnd('\')) -and (Test-Path -LiteralPath $root -PathType Container) -and (Test-PilotNoReparse $root) -and (Test-PilotLeafFile $path) -and ([System.IO.Path]::GetFileName($path) -ceq $leaf); if ($ok) { $r = $root.TrimEnd('\'); if ($directChild) { $ok = ([System.IO.Path]::GetDirectoryName($path) -eq $r) } else { $ok = $path.ToLowerInvariant().StartsWith(($r + '\').ToLowerInvariant()) } }; if ($ok) { "PATH_OK=$name" } else { "STOP PATH_FAIL=$name" } }
Test-PilotExe 'python' "<python>" "<python-runtime-root>" 'python.exe' $false
Test-PilotExe 'psql' "<psql>" "<pg-bin-dir>" 'psql.exe' $true
```

Bu kapı geçmeden `<python>` veya `<psql>` ile **hiçbir komut
çalıştırılmaz**.

Case dizini. Intake'ten **önce** mevcut olmamalıdır; intake'ten **sonra**
kapıdan geçmelidir:

```powershell
if (Test-Path -LiteralPath "<case-root>") { "STOP CASE_ROOT_EXISTS" } else { "CASE_ROOT_ABSENT" }
Test-PilotPath 'case-root' "<case-root>" "<repo-root>\data\cases"
```

İlk satır yalnız intake'ten önce, ikinci satır yalnız intake'ten sonra
çalıştırılır. `<archive-dir>` yalnız eksiksiz bir arşiv kararı varsa ve §28.5'e
göre denetlenir.

Beklenen: her satır için `PATH_OK` (veya intake öncesinde `CASE_ROOT_ABSENT`).
Herhangi bir `STOP` satırı **DUR**'dur (H52). `<external-root>` için beklenen
ebeveyn bu runbook'ta tanımlı değildir; konumu, bulut senkronizasyonu
olmadığı operatörce §4.3 (a) kaydında doğrulanan bir yerdir. Bu komutlar
standart PowerShell davranışından gelir ve §1.5'teki provada doğrulanır.

---

## 14. API credential sözleşmesi (P3)

### 14.1 Anahtar ve yaşam döngüsü

- **Yeni** ve **yalnız bu pilota ait** bir anahtar oluşturulur.
- Console'da bu anahtar veya çalışma alanı için **harcama limiti** tanımlanır.
- Hukuki kapılar, intake, maskeleme tohumu ve ağsız preview (zincir adım
  2–10) tamamlanmadan anahtar **oluşturulmaz**. Anahtar, auth probe'dan (§16.4)
  **hemen önce** oluşturulur ve o ana kadar ortamda **bulunmaz**.
- Anahtar gerçek POST tamamlanır tamamlanmaz **revoke edilir** (§29); pilot
  sonuna bırakılmaz.
- Her DUR/abort yolunda anahtar derhal Process'ten kaldırılır ve revoke edilir
  (§25.2).

### 14.2 Kapsam

- Yalnız **Process** kapsamı (tek, insan-only PowerShell oturumu).
- `.env`, HKCU, kullanıcı veya makine kapsamında kalıcı ortam değişkeni ve
  kalıcı PowerShell profili **YASAKTIR**.

### 14.3 Kayıt yasağı

Anahtarın değeri, uzunluğu, öneki, son karakterleri, hash'i veya başka bir
türevi **hiçbir yere** yazılmaz: evidence, log, ekran görüntüsü, bu belge,
commit, sohbet veya ajan oturumu.

### 14.4 Kabukta ayarlanması (operatör ortamı talimatı)

Aşağıdakiler repo kaynağından değil, standart PowerShell davranışından gelir.
Değer komut satırına yazılmaz; böylece PowerShell geçmişine düşmez.

```powershell
Set-PSReadLineOption -HistorySaveStyle SaveNothing
$secure = Read-Host -AsSecureString
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new('', $secure).Password
Remove-Variable secure
```

- Pano: Windows ayarlarında **pano geçmişi** ve **cihazlar arası eşitleme**
  kapalı olmalıdır; operatör bunu ekranda doğrular ve sonucu boolean olarak
  evidence'a yazar. Açıksa **DUR**. Anahtar yapıştırıldıktan sonra pano,
  zararsız bir metin kopyalanarak üzerine yazılır.
- `SaveNothing` yalnız PSReadLine geçmiş **dosyasını** kapatır; oturum içi
  geçmişi, §4.2/9'daki kayıt ve telemetri katmanlarını kapatmaz. Bu yüzden
  oturum §29'a göre işi biter bitmez kapatılır.

### 14.5 Ağ onayı

Anahtarın var olması ağ yetkisi **değildir**. Bu pilotta tam **iki** dış ağ
işlemi öngörülür ve her biri **ayrı açık kullanıcı onayı** gerektirir: auth
probe (§16.4) ve tek inference (§18). Başka hiçbir ağ işlemi yapılmaz.

### 14.6 Revoke

Anahtar, gerçek POST biter bitmez veya herhangi bir DUR/abort anında Console'dan
**revoke** edilir (§29). Revoke yapılmadıkça sonraki adıma geçilmez ve pilot
kapanmış sayılmaz. Revoke'un sonucu belirsizse doğrulamak için **yeni bir API
isteği yapılmaz**; durum Console ekranından okunur ve belirsizlik §25.2'ye
göre raporlanır.

---

## 15. Masking ve privacy boundary (P7)

### 15.1 İlke

- Masking **takma adlandırmadır, anonimleştirme değildir** (Adım 4a).
  Tohum listesinde olmayan veya farklı yazılmış bir ad hayatta kalabilir.
- Yürürlükteki politika `tr_pseudonymisation_v5`'tir
  (`src/llm_privacy_boundary.py`, `MASKING_POLICY_VERSION`).
- Eşleşme tablosu yalnız bellekte tutulur; preview onu **göstermez**.

### 15.2 Tam maskeleme tohumu ve kamu kurumu adları (K2-A)

Tohum, `build_seed_terms` tarafından bu sırayla üretilir:
`parties[].display_name` (yalnız `individual`/`company`),
`parties[].reference_code`, case `reference_code`,
`provenance.original_file_name`, `provenance.uploaded_by_ref`,
`file.file_name` ve operatörün `--mask-term` terimleri.

**Maskelenmesi zorunlu olanlar.** Belgede geçen **her** gerçek kişi ve özel
hukuk tüzel kişisi adı — taraf, temsilci, yetkili, müşavir, eski unvan ve
**kamu kurumu personelinin gerçek adı** — ya `case.json` `parties[]` içinde
(`individual`/`company`) ya da bir `--mask-term` olarak bulunur. Kimlik ve
vergi numarası, IBAN, telefon ve e-posta desenleri ayrıca kendi desen
kurallarıyla maskelenir (Adım 4a). Desenle yakalanmayan iletişim bilgileri ve
adresler de `--mask-term` olarak eklenir.

**Maskelenmeyenler (K2-A).** Vergi dairesi, mahkeme ve idare gibi **kamu
kurumu adları** kaynakta bilinçli olarak maskelenmez: taraf adlarından
yalnız `individual` ve `company` olanlar tohuma girer, çünkü kamu kurumu
adları süre ve yetki analizinin taşıyıcı girdisidir
(`src/llm_privacy_boundary.py`, `_MASKABLE_PARTY_TYPES` üzerindeki karar
notu). Bu adlar `--mask-term` olarak **eklenmez**; aktarımları §6.1/7 ve
§7.1/3 ile hukuki onay ve rıza kapsamında açıkça kabul edilmiş olmalıdır.

Tohumun tamlığını **avukat** yazılı olarak teyit eder. Teyit, ek maskeleme
terimleri dosyasının SHA-256'sına (`<mask-file-sha256>`) ve içindeki terim
sayısına (`<mask-term-count>`) **bağlanır** (§15.3). Eksik tohum: **DUR**.

### 15.3 `--mask-term` değerlerinin geçirilmesi

`--mask-term` değerleri gerçek adlardır. Komut satırına **elle literal olarak
yazılmazlar**.

- Adlar mümkün olduğunca `case.json` `parties[]` içine konur; `--mask-term`
  yalnız taraf olmayan adlar ve desenle yakalanmayan tanımlayıcılar için
  kullanılır.
- Ek terimler, her satırda bir terim olacak şekilde, BOM'suz UTF-8 olarak
  `<restricted-dir>\mask-terms.txt` dosyasında tutulur. Bu dosya gerçek
  içeriktir ve veri akıbeti kararına tabidir.
- Bu pilotta dosya **zorunludur ve boş olamaz**: en az bir terim taşır. Ek
  terim gerektirmeyen bir dosya bu sözleşmeyle yürütülemez; o durum ayrı
  kullanıcı kararı ve runbook değişikliği gerektirir (**DUR**).
- Dosyanın SHA-256'sı ve terim sayısı intake'te, avukatın tohum teyidiyle
  birlikte **sabitlenir** (§15.2). Hash şöyle ölçülür ve `<mask-file-sha256>`
  olarak, sayı `<mask-term-count>` olarak kaydedilir:

```powershell
(Get-FileHash -LiteralPath "<restricted-dir>\mask-terms.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
```

- **`$maskArgs` önceki bir PowerShell oturumundan miras alınamaz.** İçerik
  taşıyan **her yeni oturumda**, preview'dan ve apply'dan önce, dizi kısıtlı
  dosyadan **yeniden ve fail-closed** kurulur:

```powershell
Set-PSReadLineOption -HistorySaveStyle SaveNothing
Remove-Variable maskArgs, maskOk -ErrorAction SilentlyContinue
$maskOk = $false
$maskFile = "<restricted-dir>\mask-terms.txt"
if (Test-Path -LiteralPath $maskFile -PathType Leaf) { $maskTerms = @([System.IO.File]::ReadAllLines($maskFile, [System.Text.Encoding]::UTF8) | Where-Object { $_.Length -gt 0 }); $maskUnsafe = @($maskTerms | Where-Object { $_ -ne $_.Trim() -or $_.Contains('"') }).Count; $maskSha = (Get-FileHash -LiteralPath $maskFile -Algorithm SHA256).Hash.ToLowerInvariant(); if ($maskTerms.Count -ge 1 -and $maskTerms.Count -eq <mask-term-count> -and $maskUnsafe -eq 0 -and $maskSha -eq "<mask-file-sha256>".ToLowerInvariant()) { $maskArgs = @(); foreach ($t in $maskTerms) { $maskArgs += @('--mask-term', $t) }; $maskOk = ($maskArgs.Count -eq (2 * <mask-term-count>)) } }
if ($maskOk) { "MASK_ARGS=OK" } else { Remove-Variable maskArgs -ErrorAction SilentlyContinue; "STOP MASK_ARGS=FAIL" }
Remove-Variable maskTerms, maskUnsafe, maskSha -ErrorAction SilentlyContinue
```

  Beklenen: **`MASK_ARGS=OK`**. Komut terim değerlerini, terim sayısını veya
  dosyanın başka bir özelliğini **basmaz**; yalnız bu iki sabit satırdan
  birini basar. `MASK_ARGS=OK` şu koşulların hepsi sağlanırsa çıkar: dosya
  mevcut; en az bir terim var; terim sayısı `<mask-term-count>` ile aynı;
  dosya hash'i `<mask-file-sha256>` ile aynı; hiçbir terim baştaki veya
  sondaki boşluk ya da çift tırnak içermiyor.
- `$maskArgs` tanımsızsa, boşsa veya sayı ya da hash eşleşmiyorsa preview ve
  apply **çalıştırılmaz**: **DUR** (H44). §17.1 ve §18.2'deki komutlar bu
  koşulu kendi satırlarında yeniden denetler; tanımsız bir `$maskArgs` hiçbir
  koşulda sessizce "sıfır terim" olarak geçmez.
- **Aynı** dosyadan kurulan dizi preview ve apply'da birebir kullanılır;
  listenin digest'i `input_digest`'in parçasıdır, farklı bir liste farklı ve
  bağımsız bir denemedir (`ui/cli_mutate.py`, `--mask-term` yardımı).
- Terimler evidence'a yazılmaz; yalnız `<mask-file-sha256>`,
  `<mask-term-count>` ve preview'ın bastığı `masking_extra_terms_digest` ile
  `mask_term_count` yazılır.

**Üçlü kapı (preview tarafı).** Gönderim ancak üçü birlikte sağlanırsa
düşünülebilir: (1) bu oturumda `MASK_ARGS=OK`; (2) preview'ın bastığı
`mask_term_count` değerinin `<mask-term-count>` ile aynı olması (kaynakta bu
değer, komuta geçen `--mask-term` sayısıdır —
`ui/services/fact_extraction_mutation_facade.py`); (3) avukatın maskeli case
context ve maskeli belge metni incelemesi (§17.3). Biri eksikse **DUR**.

Bu üçlü kapı, apply tarafındaki `input_digest` kapısını **tamamlar; onun
yerine geçmez**: apply, terim listesinin digest'ini içeren `input_digest`
beklenen değerle eşleşmezse model çağrısından **önce** reddedilir
(`apply_generation`, `StaleViewError`).

**Dürüst sınırlar:**

- Terimler Python sürecinin **argümanları** olarak geçer. Süreç-oluşturma
  komut satırı denetimi veya EDR telemetrisi açıksa gerçek adlar o kayda
  düşer; bu kayıt cihaz dışına çıkıyorsa §4.2/9'a göre **DUR**.
- Preview çıktısı bu terimleri düz metin olarak geri basar (§4.2/8).
- Ek maskeleme terimlerinin güvenli biçimde geçirilemediği bir ortamda pilot
  **yapılmaz**.

### 15.4 Gönderim yasağı

Preview'daki maskeli metinde, maskeli context'te veya gönderim gövdesi/log
taramasında maskesiz bir **gerçek kişi adı, özel hukuk tüzel kişisi adı veya
kişi tanımlayıcısı** (kimlik/vergi numarası, IBAN, telefon, e-posta, adres)
görülürse gönderim **yapılmaz**; bir olay kaydı açılır (kişisel veri
içermeden) ve inceleme beklenir. Bu bir **DUR**'dur. Kamu kurumu **adı** bu
kuralın istisnasıdır (§15.2); kamu kurumu **personelinin** adı istisna
değildir.

---

## 16. Egress harness, outer monitor, auth probe ve tek gönderim sınırı

### 16.1 Kaynak durumu

Egress harness, outer monitor ve auth probe aracı **repo dışındadır** (Adım 9
checkpoint'i §D). Bu runbook onların çağırma biçimini veya bayraklarını
**tanımlamaz**; yalnız karşılamaları gereken sözleşmeyi kaydeder.

### 16.2 Sözleşme

1. Kullanılan her bileşen §13.7'deki parite kontrolünden geçmiştir. Geçmediyse
   yeni bir bağımsız inceleme gerekir; o olmadan **DUR**.
2. Tek izinli dış hedef, model sağlayıcısının (Anthropic) API origin'i ve
   portudur. Başka her hedef reddedilir.
3. Redirect, proxy ve retry **fail-closed** reddedilir. Motor istemciyi
   varsayılan ağ ayarlarıyla kurduğu için proxy'nin reddi motora değil
   harness'e dayanır.
4. Gerçek inference için tam olarak **bir** `/v1/messages` POST'u yapılır.
   İkinci bir POST denemesi, harness tarafından reddedilmiş olsa bile, sapma
   kaydıdır ve **DUR**'dur.
5. Outer monitor ayrıca çalışır ve izin verilmeyen bağlantı olayı sayısını
   kaydeder; beklenen **0**'dır.
6. Motor `Anthropic(...)` istemcisini kaynakta yeniden deneme, zaman aşımı
   veya temel URL ayarı vermeden kurar (`call_llm`). SDK'nın varsayılan
   yeniden deneme davranışı repo içinden doğrulanamaz. Bu yüzden tek-gönderim
   sınırı motor tarafından değil, **harness tarafından** zorlanır: SDK'nın
   bir yeniden denemesi ikinci bir ağ çıkışı **üretemez**.
7. Harness'in yazdığı kayıtlar ve yanıt işleme gerçek içerik taşıyabilir;
   metadata-only evidence'a yalnız §16.4 ve §18.4'teki sayaçlar girer.

### 16.3 Dürüst sınır

Outer monitor Python audit-hook tabanlıdır; C seviyesindeki ağ davranışları
için **tam bir işletim sistemi sandbox'ı değildir** (Adım 9 checkpoint'i §D,
§L/8). Adım 9'da yalnız eşzamanlı (sync) istemci yolu kanıtlanmıştır (Adım 9
checkpoint'i §L/9).

### 16.4 Auth probe (K1-A)

**Gerekçe.** Adım 9'da iki gerçek POST kimlik doğrulama aşamasında 401 ile
reddedilmiş, anahtar sorunu ancak üç yalnız-auth `GET /v1/models` isteğiyle
(401, 400, 200) çözülmüştür (Adım 9 checkpoint'i §A, §D). Gerçek veriyle aynı
hata, maskeli gövdenin sonuç alınmadan iletilmesi demektir.

**Sözleşme (hepsi):**

1. Gerçek inference'tan önce, ayrı açık kullanıcı ağ onayıyla, tam **bir**
   adet `GET /v1/models` isteği.
2. İstek gövdesi **yok**, sorgu parametresi **yok**.
3. Retry **yok**; redirect **yok**; proxy ve `trust_env` **kapalı**.
4. Yalnız §16.2/2'deki izinli origin ve port.
5. **Tek deneme.** İkinci bir probe yapılmaz.
6. Probe model çıkarımı **değildir** ve dava verisi **taşımaz**; case dizinini
   ve pilot veritabanını kullanmaz.
7. Yanıt gövdesi yazılmaz. `<probe-evidence-dir>` içine yalnız şunlar girer:
   HTTP durum kodu, `GET` sayısı (1), redirect sayısı (0), retry sayısı (0),
   reddedilmiş egress olayı sayısı (0), kullanıcının ağ onayının zamanı.

**Sonuç:**

- **200:** probe geçti. Bu, model erişimini, harcama limitini veya gerçek
  POST'un başarısını **garanti etmez**; yalnız anahtarın kimlik doğrulamadan
  geçtiğini gösterir.
- **200 dışındaki her sonuç** veya sözleşmeden herhangi bir sapma: **DUR**.
  Gerçek POST **yapılmaz**; anahtar derhal revoke edilir ve Process ortamı
  temizlenir (§29, §25.2). Yeni bir anahtarla yeni bir deneme ancak yeni bir
  kullanıcı kararıyla ve ayrı bir turda düşünülebilir.

**Araç sınırı.** Adım 9'da probe'ların kullanıldığı kayıtlıdır, ancak probe
aracının kimliği, hash'i ve harness ile ilişkisi repo içinden doğrulanamaz.
Adım 9'daki harness `GET` isteğini desteklemiyorsa **tahminle
değiştirilmez**; pinli hash'e sahip ve bağımsız incelenmiş bir probe aracı
veya harness olmadan **DUR** (§13.7).

---

## 17. Ağsız preview

### 17.1 Komut (APP oturumu, insan-only)

Preview `--allow-network` kabul **etmez** (CLI bunu kullanım hatasıyla
reddeder); ağ, kilit veya journal yazımı yoktur. `--with-agent` bu ailede
preview için de zorunludur. Preview sırasında ortamda API anahtarı
**bulunmaz** (§14.1). Preview'dan önce bu oturumda §11.3 (b)'deki yeniden
karşılaştırma `SOURCE_HASHES_MATCH=True` vermiş olmalıdır.

```powershell
if (-not $maskOk -or $maskArgs.Count -ne (2 * <mask-term-count>)) { "STOP MASK_ARGS=FAIL" } else { & "<python>" -m ui.cli_mutate generation --case <case-id> --row-key fact_extraction --document <document-id> --with-agent @maskArgs --actor-user-id <actor-user-id> }
```

`$maskArgs`, **bu oturumda** §15.3'e göre yeniden kurulmuş dizidir. Komut,
dizi tanımsızsa veya beklenen uzunlukta değilse CLI'ı **hiç çağırmaz** ve
`STOP MASK_ARGS=FAIL` basar: **DUR**.

### 17.2 Okunacak çıktı

Preview stdout'a şu etiketleri basar (`ui/cli_mutate.py`, `_run_generation`):

- `input_digest`, `generation_mode`, `model_id`, `engine_version`,
  `prompt_agent_version`, `pending_exists`, `pending_sha256`;
- `masking_policy_version`, `masking_extra_terms_digest`, `mask_term_count`;
- `masking_token_count`, `masking_class_distribution`;
- `masking_possible_over_masking` — **beş** alt sayaçlı tek satır:
  `party_name_midword_matches`, `reference_or_filename_seed_matches`,
  `tckn_checksum_failed`, `vkn_checksum_failed`, `vkn_without_context_word`
  (`src/llm_privacy_boundary.py`);
- `masking_possible_split_identifier`, `masking_possible_squeeze_seed_match`;
- `masking_chars` (orijinal → maskeli karakter sayısı);
- "MODELE GİDECEK MASKELİ CASE CONTEXT" bloğu;
- "MODELE GİDECEK MASKELİ BELGE METNİ" bloğu;
- önerilen apply komutu ve, terimler komuta gömülemiyorsa, ayrı bir
  `--mask-term` değerleri bloğu. **Bu son kısım gerçek terimleri düz metin
  olarak taşır** (§4.2/8). Önerilen komut kopyalanmaz ve **doğrudan
  çalıştırılmaz**; apply yalnız §18.2'deki iç argv ve harness zinciriyle, o
  oturumda §15.3'e göre yeniden kurulan diziyle yapılır.

### 17.3 Kabul kriterleri

- Avukat ve operatör **hem maskeli case context'i hem maskeli belge metnini**
  ekranda birlikte okur. §15.4 kapsamında maskesiz bir tanımlayıcı yoksa
  avukat yazılı olarak teyit eder.
- `masking_possible_split_identifier`, `masking_possible_squeeze_seed_match`
  veya `masking_possible_over_masking` satırındaki beş alt sayaçtan **herhangi
  biri** sıfırdan büyükse, avukatın bunu açıklayan yazılı kabulü olmadan
  **DUR**.
- §15.3'teki üçlü kapı sağlanmalıdır: bu oturumda `MASK_ARGS=OK`; preview'ın
  bastığı `mask_term_count` `<mask-term-count>` ile aynı; avukatın yukarıdaki
  okuması tamamlandı. Biri eksikse **DUR**.
- `masking_policy_version` `tr_pseudonymisation_v5` değilse **DUR**.
- `pending_exists` `True` ise (yeni bir case için beklenmez) **DUR**.
- `masking_chars` satırındaki maskeli karakter sayısı 60.000'i aşıyorsa
  **DUR**.

### 17.4 Kayıt

Evidence'a yalnız `input_digest`, `masking_policy_version`,
`masking_extra_terms_digest`, `mask_term_count`, `masking_token_count`,
`masking_class_distribution`, iki tekil sayaç ve beş alt sayaç yazılır.
Maskeli metin, maskeli context ve önerilen komut **gerçek içeriktir**;
evidence'a yazılmaz, dosyaya yönlendirilmez, bir AI oturumuna aktarılmaz.

---

## 18. Tek yetkili inference

### 18.1 Önkoşullar (hepsi)

1. §1.5, §4.3, §6, §7, §8, §9, §11, §12, §13, §15.2 (avukatın tohum tamlık
   teyidi), §17 ve §28.1 (eksiksiz yazılı veri akıbeti kararı) kapıları PASS.
   §11.3 (f) vergi türü sözlük kontrolü `TAX_TYPE_VOCAB=OK` verdi; bu kontrol
   POST'tan **önce** tamamlanmış olmalıdır.
2. Metin dosyası ve orijinal belge SHA-256'ları bu oturumda §11.3 (b)'deki
   yeniden karşılaştırmayla ölçüldü ve `SOURCE_HASHES_MATCH=True` verdi.
   `$maskArgs` bu oturumda §15.3'e göre yeniden kuruldu ve `MASK_ARGS=OK`
   verdi.
3. §13.6 ortam kontrolleri bu oturumda yeniden ölçüldü: `.env` yok veya 0
   bayt; Process kapsamında yalnız `ANTHROPIC_API_KEY`; kullanıcı ve makine
   kapsamında eşleşme yok.
4. §13.7 harness ve runtime paritesi PASS; outer monitor hazır.
5. Anahtar §14.4'e göre yalnız bu oturumda ayarlandı.
6. §16.4 auth probe **200** döndü.
7. Kullanıcının bu tek POST için **ayrı, açık ağ onayı** alındı; onay
   `<expected-input-digest>` değerine bağlıdır ve probe onayının yerine
   geçmez.

### 18.2 İç argv ve harness çağrı zinciri (APP oturumu, insan-only, tek çalıştırma)

**Bu bölüm doğrudan çalıştırılacak bir model komutu vermez.** Gerçek apply
**yalnız** doğrulanmış outer monitor + pinli single-send harness zinciri
içinden çalışabilir. Operatör çıplak bir
`& "<python>" -m ui.cli_mutate ... --apply` çağrısını **çalıştıramaz**;
böyle bir çağrı harness'in tek-POST, retry, redirect ve proxy sınırlarını
atlar ve kendisi bir sapmadır: **DUR** (H57).

Aşağıdaki blok yalnız harness'in **iç hedef argv'sini** bir dizi olarak
kurar; hiçbir süreç başlatmaz. Dizi önceki oturumdan **taşınmaz**: bu
oturumda §15.3'e göre, preview'da kullanılan **aynı** dosyadan yeniden
kurulmuş `$maskArgs` ile oluşturulur. `$maskArgs` elemanları dizi
birleştirmesiyle eklenir; hiçbir eleman bir dizgiye birleştirilmez:

```powershell
Remove-Variable innerArgv -ErrorAction SilentlyContinue
if (-not $maskOk -or $maskArgs.Count -ne (2 * <mask-term-count>) -or ("<expected-input-digest>" -cnotmatch '^[0-9a-f]{64}$')) { "STOP INNER_ARGV=FAIL" } else { $innerArgv = @('-m', 'ui.cli_mutate', 'generation', '--case', '<case-id>', '--row-key', 'fact_extraction', '--document', '<document-id>', '--with-agent', '--allow-network') + $maskArgs + @('--actor-user-id', '<actor-user-id>', '--apply', '--expected-input-digest', '<expected-input-digest>'); if ($innerArgv.Count -eq (16 + 2 * <mask-term-count>)) { "INNER_ARGV=OK" } else { Remove-Variable innerArgv; "STOP INNER_ARGV=FAIL" } }
```

Beklenen: `INNER_ARGV=OK`. Blok argüman değerlerini basmaz.

**Harness çağrısı.** İç hedef programı `<python>`, argümanları `$innerArgv`
dizisinin elemanlarıdır. Bu dizinin harness'e hangi biçimle verileceği repo
dışındaki harness'in **pinli manifestinde** tanımlıdır (§13.7, §16.1); bu
runbook o biçimi **tanımlamaz ve tahmin etmez**. Apply'dan önce şunların
hepsi mekanik olarak ölçülmüş ve evidence'a yazılmış olmalıdır:

1. Harness, outer monitor ve politika dosyalarının SHA-256'ları pinli
   kayıtla aynı (§13.7).
2. Harness sözleşmesi: tek POST; retry yok; redirect yok; proxy ve
   `trust_env` kapalı; yalnız §16.2/2'deki izinli host; `allowed_sends=1`;
   başlangıçta `refused_total=0`.
3. Pinli manifest, `<python>` ile `$innerArgv` elemanlarının iç sürece
   **değer kaybı, yeniden tırnaklama veya dizgi birleştirmesi olmadan**,
   eleman-eleman iletildiği çağırma biçimini açıkça tanımlıyor.
4. Bu wrapper/argv birleşimi §1.5'teki anahtarsız, DB'siz ve ağsız
   sentetik provada PASS verdi.

Bunlardan biri sağlanmıyorsa — özellikle harness'in çağırma biçimi pinli
manifest ve prova ile doğrulanamıyorsa — komut **uydurulmaz**: gerçek apply
kapısı **DUR** olarak kalır ve yeni bir bağımsız inceleme gerekir (H57).

`STOP INNER_ARGV=FAIL` çıkarsa harness çağrılmaz ve gönderim yapılmaz:
**DUR**. Bu satır-içi kontrol, kaynaktaki `input_digest` kapısının yerine
geçmez; onu tamamlar (§15.3).

### 18.3 Sonuç

- Başarı: çıkış kodu `0`, harness'te tam **1** POST, **0** redirect, **0**
  retry, **0** reddedilmiş egress olayı, yanıtta bilinmeyen maskeleme
  belirteci **0**.
- Herhangi bir sapma, `1`/`2` çıkış kodu veya belirsiz sonuç: **DUR**. Yeniden
  deneme yapılmaz; farklı bir terim listesiyle veya yeni bir anahtarla yeni
  bir deneme ancak yeni bir kullanıcı kararıyla ve ayrı bir turda
  düşünülebilir.
- POST biter bitmez — başarılı da olsa başarısız da olsa — §29'daki Process
  temizliği ve Console revoke yapılır; anahtar bir sonraki adıma taşınmaz.

**Dürüst sınır.** Model yanıtı, journal ve pending yazımı tamamlanana kadar
yalnız bellektedir. POST ile journal yazımı arasında veritabanı düşerse tek
gönderim **sonuçsuz tüketilmiş** olur: maskeli veri iletilmiştir, pending
yoktur ve yeniden gönderim yasaktır. Bu durum **DUR**'dur; ikinci bir gönderim
yeni rıza değerlendirmesi ve yeni kullanıcı kararı gerektirir.

### 18.4 Kayıt

`<inference-evidence-dir>` içine: model kimliği, HTTP durum kodu,
POST/redirect/retry/denied sayıları, istekteki ve yanıttaki maskeleme
belirteci sayıları, input/output token kullanımı, oluşan pending dosyasının
SHA-256'sı, kullanıcının ağ onayının zamanı. İstek ve yanıt **gövdeleri** ile
ham stdout/stderr **yazılmaz**.

---

## 19. Fact inceleme, promotion ve verification

### 19.1 Fact içerik incelemesi

Avukat, pending extraction'daki **her** fact'i orijinal belgeyle karşılaştırır
(insan-only oturum). `src/fact_approval.py` extraction'ı **bir bütün olarak**
`approved_for_canonical_use` kararıyla promote eder; repository'de fact
bazında düzeltme veya ret yazıcısı **yoktur**. Bu yüzden:

- Bütün fact'ler kabul edilirse §19.2'ye geçilir.
- Herhangi bir fact için düzeltme veya ret gerekirse: promotion
  **yapılmadan DUR.** Pending dosyası elle düzenlenmez (hash ve audit
  zincirini bozar).
- Tebliğ tarihini taşıyan fact yoksa veya birden fazla tebliğ tarihi
  fact'i varsa: **DUR** (§8).
- **Source locator.** Bir fact'in kaynak konumu (locator), `source` nesnesinin
  şu dört alanından **en az birinin** anlamlı biçimde dolu olmasıdır: `page`,
  `section`, `paragraph`, `text_excerpt` (`src/case_fact_validator.py`,
  `source_has_locator`). Kaynak yalnız `null` ve boş dizgiyi "yok" sayar; bu
  runbook daha dar davranır: yalnız boşluk karakterlerinden oluşan bir değer
  veya boş bir koleksiyon da **mevcut sayılmaz**.
- Tebliğ tarihini taşıyan fact bu anlamda bir locator taşımıyorsa veya avukat
  locator'ın gösterdiği yeri orijinal belgede bulamıyorsa: promotion
  **yapılmadan DUR**. Locator'sız bir fact kaynakta `verified` yapılamaz
  (§19.3) ve promotion'dan sonra düzeltilemez.

### 19.2 Fact promotion (APP oturumu)

Preview:

```powershell
& "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key fact --document <document-id> --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı pending hash `<expected-hash>` olarak
kaydedildi; §19.1 incelemesi tamamlandı; avukatın yazılı kabulü ve ayrı
kullanıcı onayı alındı; §26.3 baseline ölçüldü. Biri eksikse apply bloğu
kullanılmaz: **DUR**.

Apply (tek çalıştırma):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}$') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key fact --document <document-id> --actor-user-id <actor-user-id> --approve --expected-hash <expected-hash> }
```

`--discard-verified-states` bu pilotta **kullanılmaz**; yalnız
yeniden-promotion içindir. Onun gerektiği bir durum **DUR**'dur. `--note`
kullanılmaz (§10.3).

### 19.3 Yalnız tebliğ fact'inin verification'ı

Yalnız tebliğ tarihini taşıyan `<fact-id>` `verified` yapılır; diğer fact'ler
`unverified` kalır. Kaynaktaki ön koşullar
(`ui/services/fact_verification_mutation_facade.py`):

- `--evidence-ref`, fact'in kaynak belgesi veya ilişkili belgelerinden biri
  olmalıdır; bu pilotta `<document-id>`'dir.
- Evidence belgesinin `document.json` dosyasında `active` değeri tam olarak
  `true` olmalıdır; değilse reddedilir.
- `verified` hedefi için fact'in `source` nesnesi §19.1'de tanımlanan
  locator'ı taşımalıdır; taşımıyorsa reddedilir.
- Self-transition fail-closed reddedilir.

`verified` geçişi ancak şu üçü **birlikte** sağlanırsa uygulanır: (1) locator
§19.1'deki dar tanımla mevcut; (2) evidence belgesi `active`; (3) avukat,
locator'ın gösterdiği yeri (sayfa, bölüm, paragraf veya alıntı) orijinal
belgeyle karşılaştırmış ve bunu yazılı verification kararında belirtmiştir.
Bunlardan biri yoksa verification **uygulanmaz**: **DUR** (H45); düzeltme
denenmez.

Preview:

```powershell
& "<python>" -m ui.cli_mutate verification --case <case-id> --document <document-id> --fact-id <fact-id> --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı hash `<expected-hash>` olarak kaydedildi;
yukarıdaki üç koşul sağlandı; avukatın yazılı verification kararı ve ayrı
kullanıcı onayı alındı; §26.3 baseline ölçüldü. Biri eksikse apply bloğu
kullanılmaz: **DUR**.

Apply (tek çalıştırma):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}$') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate verification --case <case-id> --document <document-id> --fact-id <fact-id> --actor-user-id <actor-user-id> --apply --target-state verified --expected-hash <expected-hash> --evidence-ref <document-id> }
```

`--target-state` için CLI yalnız `unverified`, `partially_verified` ve
`verified` değerlerini kabul eder; fact'i reddetmenin veya itirazlı
işaretlemenin CLI yolu **yoktur**. Verification sonrası basılan downstream
rehberinden bu pilotta yalnız §20 ve §22 adımları koşulur; `qa` ve
`case_view` koşulmaz (§3).

---

## 20. Timeline generation ve promotion

Timeline ailesi `--anchor`, `--document` ve `--mask-term` almaz.

Generation preview:

```powershell
& "<python>" -m ui.cli_mutate generation --case <case-id> --row-key timeline --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı `input_digest` `<expected-input-digest>`
olarak kaydedildi; §26.3 baseline ölçüldü. Pending üreten bu adım ayrı
kullanıcı onayı gerektirmez (§2.1). Biri eksikse apply bloğu kullanılmaz:
**DUR**.

Generation apply (tek çalıştırma):

```powershell
if ("<expected-input-digest>" -cnotmatch '^[0-9a-f]{64}$') { "STOP EXPECTED_INPUT_DIGEST=INVALID" } else { & "<python>" -m ui.cli_mutate generation --case <case-id> --row-key timeline --actor-user-id <actor-user-id> --apply --expected-input-digest <expected-input-digest> }
```

Promotion preview:

```powershell
& "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key timeline --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı pending hash `<expected-hash>` olarak
kaydedildi; aşağıdaki kabul koşulu pending üzerinde avukat tarafından
incelendi; avukatın yazılı onayı ve ayrı kullanıcı onayı alındı; §26.3
baseline ölçüldü. Biri eksikse apply bloğu kullanılmaz: **DUR**.

Promotion apply (tek çalıştırma):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}$') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key timeline --actor-user-id <actor-user-id> --approve --expected-hash <expected-hash> }
```

Kabul: canonical timeline'da tebliğ olayı **tam bir** tanedir ve
`verified` fact'e bağlıdır; bunun `event_id` değeri `<anchor-event-id>`'dir.
İkinci bir tebliğ olayı veya anchor adayı varsa **DUR**.

---

## 21. Stopping-event beyanı ve kör bağımsız hesap

### 21.1 Stopping-event beyanı ve adli tatil kararı

- Avukat, tebliğden sonra süreyi durdurabilecek, kesebilecek veya
  başlangıcını değiştirebilecek bir işlemin **bulunmadığını** yazılı olarak
  beyan eder ve beyana opak bir referans verir (`<attestation-ref>`, 1–200
  yazdırılabilir karakter, satır sonu yok, kişisel veri yok).
- Avukat adli tatilin uygulanabilirliğini yazılı olarak `yes` veya `no` diye
  kararlaştırır. CLI'ın varsayılanı `unknown`'dır; karar `yes` veya `no`
  değilse **DUR**.
- CLI'da `--stopping-event-status` verilmezse değer `unknown` sayılır ve sonuç
  `needs_review` olur; varsayılan **asla** `none` değildir
  (`ui/cli_mutate.py`).
- Avukat beyanı `present` veya `unknown` ise kesin tarih üretilmez
  (`calculated_deadline = null`); bu pilotta bu durum **DUR**'dur. Operatör
  olayın hukuki etkisini yorumlayamaz; buna izin veren bayrak yoktur (Adım 7
  kapanışı).

### 21.2 Kör bağımsız hesabın sabitlenmesi (deadline generation'dan ÖNCE)

Bağımsız hesap ancak avukat sistemin tarihini **görmeden** yapılırsa
bağımsızdır. Bu yüzden sıra bağlayıcıdır:

1. Avukat, **yalnız** orijinal belgeyi ve kendi hukuk bilgisini kullanarak
   son günü hesaplar. Bu hesaptan önce sistemin ürettiği hiçbir deadline,
   pending, canonical veya rapor sonucu avukata **gösterilmez**; bu noktada
   sistem henüz bir deadline üretmemiştir.
2. Hesap yazılı kayda alınır. Kayıt şunları taşır: tebliğ tarihi, hesaplanan
   son gün, hesabın kapsamı (uygulanan kural, adli tatil ve mali tatil
   değerlendirmesi) ve kaydın zamanı.
3. Kayıt dosyasının SHA-256'sı ve kayıt zamanı evidence'a yazılır. Kaydın
   kendisi gerçek tarih taşıdığı için evidence'a **girmez**; repo dışında,
   avukatın kontrolünde saklanır.
4. Ancak bundan **sonra** §22.1'deki deadline generation apply çalıştırılır.

Sabitlenmiş hash'i olmayan bir hesap bağımsız sayılmaz. Hash evidence'a
yazılmadan deadline generation apply çalıştırılırsa: **DUR**.

---

## 22. Deadline generation, karşılaştırma ve approval

### 22.1 Generation

Parser davranışı (`ui/cli_mutate.py`, `_validate_generation_args`):

- `--anchor` hem preview hem apply için zorunludur.
- `--stopping-event-status` ve `--stopping-event-attestation-ref` **yalnız
  apply'da** kabul edilir; preview'da verilirse CLI kullanım hatasıyla
  (çıkış `2`) reddeder.
- `--judicial-recess-applicable` yardım metnine göre apply'a özgüdür; deadline
  preview'ında reddedilmez ama kullanılmaz. Preview'da **verilmez**.
- `--attempt` varsayılan `1`'dir ve otomatik artmaz; varsayılan dışı değer
  yalnız apply'da kabul edilir. Bu pilotta değiştirilmez.

Preview:

```powershell
& "<python>" -m ui.cli_mutate generation --case <case-id> --row-key deadline --anchor <anchor-event-id> --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı `input_digest` `<expected-input-digest>`
olarak kaydedildi; §21.1 yazılı beyanı ve adli tatil kararı alındı; §21.2
sabitlemesinin hash'i evidence'ta; §26.3 baseline ölçüldü. Biri eksikse apply
bloğu kullanılmaz: **DUR**.

Apply (tek çalıştırma). `none` ve `yes` literal CLI değerleridir; `yes`
yerine avukatın yazılı kararı `no` ise `no` yazılır. `<attestation-ref>`
tırnak içinde verilir:

```powershell
if ("<expected-input-digest>" -cnotmatch '^[0-9a-f]{64}$') { "STOP EXPECTED_INPUT_DIGEST=INVALID" } else { & "<python>" -m ui.cli_mutate generation --case <case-id> --row-key deadline --anchor <anchor-event-id> --actor-user-id <actor-user-id> --apply --expected-input-digest <expected-input-digest> --stopping-event-status none --stopping-event-attestation-ref "<attestation-ref>" --judicial-recess-applicable yes }
```

### 22.2 Pending deadline kabul kriterleri

Pending deadline şunları taşımadıkça karşılaştırmaya ve approval'a geçilmez
(alanlar: `data/case_deadline.schema.json`):

- `calculation_state` `calculated`;
- `expiry_state` **`not_evaluated`**;
- `anchor_verification_state` `verified`;
- `stopping_event_status` `none` ve `stopping_event_attestation_ref` mevcut;
- `requires_human_review = true`;
- tek deadline kaydı.

`blocked_unverified_anchor`, `needs_review` veya başka bir durum **DUR**'dur.

### 22.3 Pending tarihin sabitlenmiş hesapla karşılaştırılması (approval'dan ÖNCE)

1. Pending kayıttaki `calculated_deadline`, avukatın §21.2'de sabitlenmiş
   hesabındaki son günle **birebir** karşılaştırılır. Karşılaştırmadan önce
   sabitlenmiş kaydın SHA-256'sı yeniden ölçülür ve evidence'taki değerle aynı
   olduğu doğrulanır.
2. **Eşleşmezse:** deadline approval **çalıştırılmaz**. **DUR**; §25.2 abort
   yolu uygulanır. Düzeltme denenmez, hesap sonradan değiştirilmez.
3. **Eşleşirse:** sonuç `PENDING_MATCH` olarak evidence'a yazılır. Avukat
   ancak bundan sonra sistemin gerekçesini (kural, başlangıç, kaydırmalar)
   ayrıca inceler ve approval kararını verir.

### 22.4 Approval (APP oturumu)

Preview:

```powershell
& "<python>" -m ui.cli_mutate approval --case <case-id> --row-key deadline --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı pending hash `<expected-hash>` olarak
kaydedildi; §22.2 kabul kriterleri ve §22.3 `PENDING_MATCH` sağlandı;
avukatın yazılı deadline onayı ve ayrı kullanıcı onayı alındı; §26.3 baseline
ölçüldü. Biri eksikse apply bloğu kullanılmaz: **DUR**. Avukatın deadline
onayı hiçbir durumda kör bağımsız hesabın sabitlenmesinden veya §22.3
karşılaştırmasından **önce** verilemez.

Apply (tek çalıştırma):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}$') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate approval --case <case-id> --row-key deadline --actor-user-id <actor-user-id> --approve --expected-hash <expected-hash> }
```

---

## 23. Salt-okunur deadline raporu

Rapor **metadata değildir**: tebliğ tarihini ve hesaplanan son günü taşıyan
dava-türevi içeriktir (`ui/deadline_report.py`, `_render_report`). Bu yüzden
genel evidence dizinine **yazılmaz**; `<restricted-dir>` içine yazılır ve
§28'deki veri akıbeti kararına tabidir.

```powershell
& "<python>" -m ui.deadline_report --case <case-id> --actor-user-id <actor-user-id> --output "<restricted-dir>\deadline-report.txt"
```

- Rapor **APP oturumunda** (insan-only) çalıştırılır; bağlantı salt-okunur
  transaction'dır ve yalnız `SELECT` içerir. ADMIN oturumunda çalıştırılmaz
  (§12.4).
- PostgreSQL yetkilendirmesi ve aktif `lawyer` assignment'ı zorunludur.
  `--output` mutlak, repo dışı, henüz var olmayan ve parent'ı mevcut bir yol
  olmalıdır.
- Çıkış kodları: `0` rapor üretildi, `1` ret, `2` kullanım.
- Ret durumunda stdout boştur ve stderr tek satır
  `RAPOR REDDEDİLDİ: <sabit_kod>` taşır; her ret **DUR**'dur.
- Başarıda stdout tek satır `RAPOR YAZILDI: ` ve yerel yoldur; bu satır
  evidence'a yazılmaz.
- Rapor şu iki satırı **birebir** taşımalıdır; yoksa **DUR**:
  - `Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.`
  - `Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.`

Kontrol, rapor metnini basmadan yapılır:

```powershell
$r = [System.IO.File]::ReadAllLines("<restricted-dir>\deadline-report.txt", [System.Text.Encoding]::UTF8)
"EXPIRY_LINE_PRESENT=$($r -ccontains 'Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.')"
"DISCLAIMER_LINE_PRESENT=$($r -ccontains 'Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.')"
(Get-FileHash -LiteralPath "<restricted-dir>\deadline-report.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
```

Genel evidence'a **yalnız** şunlar yazılır: çıkış kodu, rapor dosyasının
SHA-256'sı ve iki zorunlu satırın bulunduğuna ilişkin iki boolean sonuç.
Rapor metni, gerçek tarih, case adı veya kişi/kurum adı evidence'ta
**bulunmaz**.

---

## 24. Rapor tarihinin son karşılaştırması

Bu, §22.3'teki asıl karşılaştırmanın **ikinci** kontrolüdür; onun yerine
geçmez.

1. Rapordaki `calculated_deadline`, avukatın §21.2'de sabitlenmiş hesabıyla
   **birebir** karşılaştırılır.
2. Eşleşme: sonuç `MATCH` olarak evidence'a yazılır.
3. Eşleşmeme: **DUR.** Rapor kullanılmaz, düzeltme denenmez; olay kaydı
   açılır ve inceleme beklenir.
4. Rapor süre aşımını (expiry) **değerlendirmez** ve hukuki karar
   **değildir**. Avukatın kendi hesabı her durumda onun hukuki
   sorumluluğundadır.

---

## 25. Başarısızlık, DUR matrisi ve güvenli DUR/abort yolu

### 25.1 DUR matrisi

Aşağıdaki her satır **DUR**'dur. Matris **tüketici değildir**: gövdede "DUR"
yazan her koşul, matriste satırı olsun olmasın bağlayıcıdır. Her DUR §25.2'yi
çağırır. DUR'da: otomatik retry **yok**, düzeltici SQL **yok**, ikinci model
gönderimi **yok**, elle dosya düzeltmesi **yok**.

| # | Tetikleyici | Bölüm |
|---|---|---|
| H1 | Yazılı hukuki onay yok veya eksik | §6 |
| H2 | Dokuz hard-block sınıfını sayan imzalı ek yok | §9 |
| H3 | İmzalı rıza yok veya kapsamı eksik | §7 |
| H4 | Veri akıbeti yazılı kararı yok; seçenek açıkça adlandırılmamış; ya da seçilen seçeneğin zorunlu unsurları eksik (silme: açık "sil" ifadesi ve kapsam; şifreli arşiv: arşiv yeri ve ebeveyni, şifreleme yöntemi, erişim, saklama süresi ve nihai silme koşulu ile yerel çalışma kopyasının silinmesi veya korunması — beş unsurun tamamı). Gerçek belge teslim alınmaz | §28.1 |
| H5 | Birden fazla dava, tebliğ veya deadline adayı | §8, §19, §20 |
| H6 | `file.sha256` yok/geçersiz veya orijinal bayt hash'i uyuşmuyor | §11.3 |
| H7 | Validator hatası veya yazılı kabul edilmemiş uyarı; argümansız veya yanlış case'i gösteren validator çağrısı | §11.3 |
| H8 | `??` görünümü, `case_0001` değişikliği veya ignore sapması | §11.3, §13.2 |
| H9 | Avukatın intake onayı yok | §11.4 |
| H10 | Eksik maskeleme tohumu | §15.2 |
| H11 | Maskeli metinde, maskeli context'te veya gövde/log taramasında maskesiz kişi tanımlayıcısı | §15.4, §17.3 |
| H12 | Preview sayaçlarından biri sıfırdan büyük ve avukat kabulü yok | §17.3 |
| H13 | `.env` boyutu sıfırdan büyük; Process, kullanıcı veya makine kapsamında izinsiz ortam değişkeni adı | §13.6 |
| H14 | Egress hedefi, proxy, redirect, retry veya ikinci gönderim sapması | §16, §18 |
| H15 | Kullanıcının probe veya tek inference için ayrı ağ onayı yok | §16.4, §18.1 |
| H16 | Digest veya hash değişmesi (preview ile apply arası, metin dosyası, sabitlenmiş hesap kaydı) | §17–§22 |
| H17 | Beklenmeyen DB deltası (journal, assignment) veya dosya deltası | §13.5, §26 |
| H18 | Fact için düzeltme/ret gereği | §19.1 |
| H19 | Unverified anchor (`blocked_unverified_anchor`) | §22.2 |
| H20 | Stopping-event `present` veya `unknown`; `needs_review`; adli tatil kararı `yes`/`no` değil | §21.1, §22.2 |
| H21 | `expiry_state` değeri `not_evaluated` değil | §22.2 |
| H22 | Rapor reddi veya zorunlu expiry/hukuki-karar satırı eksik | §23 |
| H23 | Avukatın sabitlenmiş bağımsız hesabıyla eşleşmeme (pending veya rapor aşamasında); hesap sabitlenmeden deadline üretilmesi | §21.2, §22.3, §24 |
| H24 | Tek-çalıştırma komutunun sonucu belirsiz | §27.2 |
| H25 | Revoke veya cleanup postcondition'ı başarısız | §27–§30 |
| H26 | Evidence veya özet eksik | §26 |
| H27 | Küme durumu ölçülmedi veya beklenenden farklı | §13 |
| H28 | Belgenin bir hard-block sınıfına girmesi veya girdiğinden şüphe | §9.2 |
| H29 | Case dizini intake'ten önce zaten mevcut | §11.2 |
| H30 | Branch, HEAD veya çalışma ağacı beklenenden farklı; runbook onaylı HEAD'de tracked değil | §1.5, §13.2 |
| H31 | `pip check` başarısız veya runtime paket kümesi sapması | §13.3, §13.7 |
| H32 | Harness, monitor veya probe bileşeninin hash/manifest sapması ya da pinli kaydın yokluğu | §13.7, §16 |
| H33 | `masking_policy_version` beklenen sürüm değil | §17.3 |
| H34 | Beklenmeyen pending (`pending_exists` `True`) | §17.3 |
| H35 | `--discard-verified-states` gereği | §19.2 |
| H36 | Manifestin göreli yolunda kişisel veri | §28.2 |
| H37 | Herhangi bir komutta sıfır olmayan çıkış kodu, traceback veya yetkilendirme reddi | Genel |
| H38 | Auth probe 200 dışında sonuç verdi veya probe sözleşmesinden sapıldı | §16.4 |
| H39 | Güvenli DUR/abort veya teardown adımı başarısız ya da sonucu belirsiz | §25.2 |
| H40 | Gerçek içerik güven sınırının ihlali veya ihlal şüphesi; kayıt/telemetri ön kontrolü geçmedi; içerik penceresinde bir AI/IDE/OCR/ekran paylaşımı/bulut pano/telemetri kanalı açık; `AI_CONTENT_CHANNELS_CLOSED=True` kaydı yok veya kanal durumu doğrulanamıyor | §4.2, §4.3 |
| H41 | Bağımsız inceleme, commit veya sentetik prova ön koşulu eksik | §1.5 |
| H42 | Kapsam ön elemesi başarısız (belge türü, takvim yılı, tek dava/tebliğ/deadline) | §8 |
| H43 | Intake alanlarından birinin avukat onayı eksik; intake'te `unverified` dışı `verification_state`; JSON'da BOM; metin uzunluğu sınır dışı | §11.2, §11.4 |
| H44 | `MASK_ARGS=OK` alınamadı: `$maskArgs` tanımsız veya boş; terim dosyası yok, boş, sayısı ya da hash'i onaylanan değerle eşleşmiyor; terim güvenli biçimde geçirilemiyor; preview `mask_term_count` değeri `<mask-term-count>` ile aynı değil | §15.3, §17, §18.2 |
| H45 | Verification ön koşulu sağlanmıyor: locator dar tanımla mevcut değil, evidence belgesi `active` değil veya avukat locator'ı orijinal belgeyle karşılaştırmadı | §19.1, §19.3 |
| H46 | Silme guard'ı başarısız — case: hedef yol, `case_0001`, ebeveyn, örtüşme, reparse point veya normal dosya/dizin dışı öğe, case manifesti türü, ayrıştırma hatası veya yinelenen göreli yol, canlı dosya kümesi, bayt veya SHA-256'nın kapanış manifestinden sapması; `<restricted-dir>`: exact yol, ebeveyn, `<external-root>` sözleşmesi, örtüşme, reparse point, dosya kümesi, bayt veya SHA-256'nın kapanış manifestinden sapması; her iki hedefte korunan bir yolun tanımsız, yer tutucu veya çözümlenemez olması ya da guard istisnası — ya da o hedef için silme anı onayı yok; silme başarısız, kısmi veya sonrası ölçüm (`CASE_DIR_ABSENT`, `RESTRICTED_DIR_ABSENT`, kalıntı ölçümleri) beklenenden farklı | §28.3 |
| H47 | Şifreli arşivin paritesi, iki manifestin her biriyle, çalışma kopyası silinmeden önce doğrulanamadı | §28.5 |
| H48 | Revoke ön koşulu sağlanmıyor: aktif assignment sayısı tam 1 değil | §27.1 |
| H49 | POST yapıldı ama sonuç alınamadı veya pending yazılamadı (sonuçsuz tüketim) | §18.3 |
| H50 | Pano geçmişi veya cihazlar arası pano eşitlemesi açık | §14.4 |
| H51 | `tax_type` sözlük kontrolü başarısız (`unrecognized` veya `mixed` karşılığı) ya da değer avukatın yazılı sınıflandırmasıyla eşleşmiyor; model POST'u yapılmaz | §8, §11.3 |
| H52 | Yol kapısı başarısız: göreli veya canonical olmayan yol, reparse point, beklenen ebeveynin dışında, oturum konumu `<repo-root>` değil; `<external-root>` sözleşmesi ihlali (sürücü kökü; `<repo-root>`'a eşit, onun altında veya atası; korunan bir dizinle örtüşme; doğrudan altında pilot-owned küme dışında öğe; `PATH_OK=external-root-contract` intake'ten önce alınmadı); `<python>`/`<psql>` beklenen runtime dizininin dışında veya adı beklenenden farklı; `<archive-dir>` yanlış ebeveyne çözülüyor, korunan bir dizinle örtüşüyor, korunan bir yol çözümlenemiyor veya boş değil | §13.8, §28.5 |
| H53 | İçerik oturumu `-NoProfile` ile açılmadı; aktif transcript; beklenmeyen modül; PSReadLine handler'ı `UNKNOWN`; `HistorySaveStyle` `SaveNothing` değil; durum doğrulanamıyor | §4.3 |
| H54 | Salt-okunur SQL sözleşmesi ihlali: `psql` çıkış kodu 0 değil, `transaction_read_only` `on` değil, `SELECT`/`SHOW` dışı ifade, düzeltici SQL gereği veya IAM mutasyonunun CLI dışında denenmesi | §13.5 |
| H55 | Eksik veya belirsiz veri akıbeti kararı (arşivde beşinci unsurun yokluğu dahil) intake'ten sonra fark edildi: veri silinmez, arşivlenmez; değiştirilmeden korunur ve yeni yazılı karar beklenir | §28.1 |
| H56 | `<restricted-dir>` içerik sözleşmesi ihlali: izinli küme kaydı veya `restricted-allowed-files.sha256.txt` hash kaydı yok, sonradan değişti (`ALLOWED_FILE_HASH_OK=True` alınamadı: hash kaydı eksik/bozuk/tek satır ve exact label biçiminde değil, 64 küçük hex değil, kayıt okunamıyor ya da hash eşleşmiyor) veya intake'ten önce yazılamadı ya da `ALLOWED_FILE_HASH_RECORDED=True` alınamadı; izinli küme dışında dosya, herhangi bir alt dizin, reparse point veya symlink; genel olmayan dosya adı; bir manifestin exclusive-create ile yazılamaması veya türünün beklenenden farklı olması | §10.5, §28.2 |
| H57 | Harness çağrı zinciri doğrulanamadı: çıplak `ui.cli_mutate ... --apply` çağrısı; iç argv `INNER_ARGV=OK` vermedi; harness'in çağırma biçimi pinli manifest ve prova ile doğrulanmadı; harness sözleşme ölçümü eksik | §18.2 |

### 25.2 Güvenli DUR/abort yolu (bağlayıcı)

Her DUR bu yolu çağırır. Bu yol, zincirin "bir adım PASS olmadan sonrakine
geçilmez" kuralından **muaftır**, ancak **yalnız aşağıdaki güvenli kapatma
adımlarına** izin verir; zincirin ilerletilmesine izin vermez. Sıra
bağlayıcıdır:

1. **Durdur.** Yeni mutasyon, yeniden deneme ve ağ işlemi yapılmaz.
2. **Process anahtarı.** Ortamda `ANTHROPIC_API_KEY` varsa derhal kaldırılır
   (`Remove-Item Env:ANTHROPIC_API_KEY`).
3. **Console revoke.** Anahtar oluşturulduysa Console'dan revoke edilir.
   Sonuç belirsizse doğrulamak için **yeni bir API isteği yapılmaz**; durum
   Console ekranından okunur.
4. **DB oturumları.** Açık etkileşimli veritabanı oturumlarında işlem geri
   alınır (`ROLLBACK`) ve oturum kapatılır.
5. **Assignment ölçümü.** Aktif assignment sayısı salt-okunur ölçülür
   (§13.5).
6. **Tam 1 aktif assignment varsa:** revoke komutu ayrı kullanıcı onayıyla ve
   **yalnız bir kez** çalıştırılır (§27.1).
7. **0 aktif assignment varsa:** revoke **çalıştırılmaz**.
8. **Birden fazla veya belirsiz sayıda assignment varsa:** **DUR**; düzeltici
   SQL yok, durum kullanıcıya raporlanır.
9. **Gerçek veri.** Diskte gerçek veri varsa akıbeti **yalnız** zincir adım
   3'teki **eksiksiz** yazılı karara göre belirlenir (§28.1): açık bir "sil"
   kararı varsa veri §28.2–§28.3'e göre, her silme hedefi için ayrı guard ve
   silme anındaki ayrı kullanıcı onayıyla silinir; eksiksiz bir arşiv kararı
   varsa §28.5'e göre arşivlenir ve yerel çalışma kopyası yalnız beşinci
   unsur "sil" ise ve arşiv paritesi doğrulandıktan sonra silinir, "koru" ise
   korunur. Karar eksik veya belirsiz çıkarsa veri **silinmez ve
   arşivlenmez**; olduğu yerde değiştirilmeden korunur ve yeni yazılı karar
   beklenir (§28.1/6, H55).
   DUR tek başına bir silme talimatı **değildir**. İnceleme için verinin
   bekletilmesi yalnız avukatın ve kullanıcının **yazılı** kararıyla ve o
   kararda yazılı bir **bitiş tarihiyle** mümkündür.
10. **Evidence.** Genel evidence'a yalnız opak durum, hash'ler ve kişisel veri
    içermeyen hata kodu yazılır.
11. **Kalan durum raporu.** Açık kalan her kaynak, credential ve veri durumu
    (anahtar revoke edildi mi, assignment aktif mi, veri diskte mi, hangi
    journal satırları var) kullanıcıya açıkça raporlanır.
12. **Cleanup başarısızsa:** otomatik tekrar **yok**; kalan risk kaydedilir ve
    insan kararı beklenir (H39).

Gerçek veri henüz teslim alınmadıysa ve anahtar oluşturulmadıysa bu listenin
2., 3. ve 9. adımları "uygulanmadı" olarak kaydedilir. Journal satırları,
mutation resource satırı ve security event'ler abort'ta da **silinmez**
(§28.4). Veri diskte kaldığı sürece §4.3 içerik penceresi **açıktır** ve
kanal kapısı geçerliliğini korur.

---

## 26. Audit / evidence sözleşmesi

### 26.1 Konum

`<evidence-dir>`, `<probe-evidence-dir>` ve `<inference-evidence-dir>` repo
dışında, erişimi kısıtlı dizinlerdir ve **yalnız metadata** taşır. Gerçek
belge baytları, metin, maskeli metin, maskeli context, istek/yanıt gövdesi,
ham stdout/stderr, deadline raporu, gerçek tarih veya kişisel veri buralara
**yazılmaz**. Dava-türevi içerik yalnız `<restricted-dir>` içinde durur
(§10.2).

### 26.2 Zorunlu kayıtlar

| Kayıt | İçerik |
|---|---|
| Başlangıç | Branch, HEAD, temiz ağaç, runbook'un tracked olduğu, ignored görünüm, küme durumu, `pip check`, kayıt/telemetri ve pano ön kontrolleri |
| İçerik oturumu | §4.3 (b) çıktıları: `-NoProfile`, transcript, modül ve handler boolean'ları (her içerik oturumu için) |
| Kanal kapısı | §4.3 (a): süreç adı taraması sonucu, altı sınıf boolean'ı ve `AI_CONTENT_CHANNELS_CLOSED=True` |
| Yol kapısı | §13.8: her yer tutucu adı için `PATH_OK` ve `PATH_OK=external-root-contract` (yol yazılmaz) |
| Ön koşullar | Bağımsız inceleme sonucu, commit kimliği, sentetik prova evidence'ının hash'i |
| Hukuki/rıza | Onay, ek, rıza ve veri-akıbeti belgelerinin SHA-256'ları ve redakte kapsam özetleri |
| Restricted kümesi | `restricted-allowed-files.txt` kaydı, `ALLOWED_FILE_HASH_RECORDED=True`, `restricted-allowed-files.sha256.txt` kaydının kendi bayt sayısı ve SHA-256'sı, her envanterde `ALLOWED_FILE_HASH_OK=True`, `RESTRICTED_INVENTORY=OK` ve dosya sayısı (§10.5) |
| Intake | BOM ve uzunluk kontrolleri, `INTAKE_HASH=MATCH`, `INTAKE_HASHES_RECORDED=True`, her preview ve POST öncesinde `SOURCE_HASHES_MATCH=True`, validator PASS/sayılar, `TAX_TYPE_VOCAB=OK`, ignore kontrolü, metin çıkarma aracının adı ve sürümü, avukat intake onayının hash'i |
| Maskeleme tohumu | `<mask-file-sha256>`, `<mask-term-count>`, her içerik oturumunda `MASK_ARGS=OK`, avukat tohum teyidinin hash'i |
| Ortam | §13.6 eşleşme sayıları ve adları, `.env` durumu, §13.7 parite sonuçları |
| Preview | §17.4'teki alanlar |
| Auth probe | §16.4'teki alanlar (ayrı dizin) |
| Inference | §18.4'teki alanlar (ayrı dizin) |
| Her mutasyon | Komut ailesi ve row-key, çıkış kodu, preview hash/digest, apply sonrası dosya SHA-256'sı, yeni journal satırı sayısı ve durumu, kullanıcı onayının zamanı |
| Avukat kararları | Her yazılı kararın hash'i |
| Kör hesap | Sabitlenmiş kaydın SHA-256'sı ve zamanı (§21.2) |
| Karşılaştırma | `PENDING_MATCH` (§22.3) ve `MATCH` (§24) sonuçları |
| Rapor | Çıkış kodu, rapor dosyası SHA-256'sı, iki boolean (§23) |
| Inference zinciri | `INNER_ARGV=OK`, harness sözleşme ölçümleri ve wrapper/argv prova sonucu (§18.2) |
| Kapanış | §28.2'deki iki ayrı manifest ve dosya sayıları, `CASE_DELETE_GUARD`, `CASE_DELETE_RESULT`, `CASE_DIR_ABSENT`, `ALLOWED_FILE_HASH_OK` ve `RESTRICTED_DELETE_GUARD` sonuçları, §28.3.2 son ölçüm satırları, varsa `PATH_OK=archive-dir` ve arşiv paritesi, revoke ve temizlik sonuçları, postcondition'lar |
| DUR | Tetiklenen satır, §25.2 adımlarının sonucu, kalan durum |

### 26.3 Journal kontrolü

Her apply'dan önce `case:<case-id>` için en büyük journal `id` değeri
(`<baseline-max-id>`) alınır; apply'dan sonra yalnız bu değerden büyük
satırlar sorgulanır. İki ifade de §13.5'teki salt-okunur sözleşmeyle ve aynı
çağırma biçimiyle, APP oturumunda çalıştırılır:

```sql
SELECT coalesce(max(id), 0) FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>';
```

```sql
SELECT id, state, actor_user_id, action_family FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>' AND id > <baseline-max-id> ORDER BY id;
```

Beklenen: tam **1** yeni satır, `state = 'completed'`, `actor_user_id` avukat
aktörü, `action_family` çalıştırılan aile. Rerun-güvenli baseline deseni
`docs/operations/local-postgresql-iam-adoption.md` §K.6 ile aynıdır.

### 26.4 Özet

Pilot sonunda kişisel veri içermeyen tek bir özet dosyası yazılır ve
SHA-256'sı kaydedilir. Özet yoksa pilot kapanmış sayılmaz.

---

## 27. Assignment revoke ve tek-çalıştırma kuralları

### 27.1 Revoke (ADMIN oturumu, tam bir kez)

**Ön koşul.** Rapor ve son karşılaştırma tamamlanmıştır (veya §25.2 abort
yolu çağrılmıştır) ve APP oturumunda, §13.5'teki salt-okunur sözleşme ve
çağırma biçimiyle ölçülen aktif assignment sayısı **tam 1**'dir:

```sql
SELECT count(*) FROM iam.case_assignments WHERE case_id = '<case-id>' AND revoked_at IS NULL;
```

Sayı 1 değilse revoke **çalıştırılmaz**: 0 ise gerek yoktur; 1'den büyükse
veya belirsizse **DUR**. Assignment durumu yalnız aşağıdaki canonical IAM CLI
komutuyla değiştirilir; SQL ile düzeltilmez (§13.5/1).

Ayrı kullanıcı onayıyla:

```powershell
& "<python>" -m scripts.iam_admin revoke-assignment --user-id <actor-user-id> --case-id <case-id> --actor-user-id <admin-user-id>
```

Beklenen: çıkış `0` ve `OK`. Ardından aynı sorguyla aktif assignment sayısı
**0** olarak doğrulanır.

### 27.2 Tek-çalıştırma kuralı

- `revoke-assignment` **idempotent değildir**: zaten revoke edilmiş bir
  assignment üzerinde tekrar çalıştırılırsa `role` alanı boş, sahte bir
  revoke olayı yazıp yine başarı döner (`scripts/iam_admin.py`,
  `revoke_assignment`; Adım 9 checkpoint'i §K). Bu yüzden **asla ikinci kez**
  çalıştırılmaz.
- Aynı kural `assign-case`, her `--apply`/`--approve` komutu, auth probe ve
  §18'deki gönderim için geçerlidir.
- Sonuç belirsizse (kesilen oturum, okunamayan çıktı) komut tekrar
  **edilmez**; durum yalnız salt-okunur SQL ve dosya hash'iyle ölçülür ve
  **DUR** kaydı yazılır.

---

## 28. Veri silme veya şifreli arşiv (P6)

### 28.1 Yazılı karar her zaman zorunludur ve eksiksiz olmalıdır

Gerçek veri teslim alınmadan **önce** avukat, pilot sonunda verinin akıbetini
yazılı olarak kararlaştırır. Karar iki seçenekten birini **açıkça** adlandırır
ve seçilen seçeneğin zorunlu unsurlarını **eksiksiz** taşır:

- **Silme.** Açık bir "sil" ifadesi ve kapsam: case dizini; `<restricted-dir>`
  dizininin kendisi ve içeriği (deadline raporu, ek maskeleme terimleri
  dosyası, varsa ham çıktı dosyaları — §10.5'teki izinli küme); oluşmuş
  olabilecek diğer kopyalar.
- **Şifreli arşiv.** Aynı kapsam ve şu beş unsurun **tamamı**: (1) arşiv
  yeri (`<archive-dir>` ve önceden onaylanmış ebeveyni `<archive-parent>`);
  (2) şifreleme yöntemi; (3) erişebilecek kişiler veya roller; (4) saklama
  süresi ve arşivin nihai silme tarihi veya koşulu; (5) arşiv paritesi
  doğrulandıktan sonra yerel çalışma kopyasının (case dizini ve
  `<restricted-dir>`) **silineceği** veya **korunacağı**.

**Teslimden önceki kapı.** Karar yoksa, seçenek açıkça adlandırılmamışsa veya
seçilen seçeneğin unsurlarından biri — arşivde beşinci unsur dahil — eksikse:
gerçek belge teslim **alınmaz**, intake **başlatılmaz**, pilot **DUR** olur
(H4).

**Bağlayıcı kurallar:**

1. Silme önerilen seçenektir, ama **varsayılan değildir**: kararın yokluğu
   veya eksikliği hiçbir koşulda silme talimatı sayılmaz.
2. Eksik bir arşiv kararı hiçbir koşulda **örtülü silme talimatına
   dönüştürülemez**.
3. Silme **yalnız** açık ve eksiksiz yazılı kararla yapılır: ya "sil"
   seçeneği ya da beşinci unsurunda "doğrulanmış arşivden sonra yerel
   çalışma kopyasını sil" açıkça seçilmiş eksiksiz bir arşiv kararı. İkinci
   durumda silme, o yazılı kararın **açık parçasıdır**; örtülü silme
   sayılmaz. Her iki durumda da silme §28.3'ün mekanik guard'larına ve silme
   anındaki ayrı kullanıcı onayına tabidir.
4. Arşiv paritesi (§28.5) kurulmadan **hiçbir** çalışma kopyası silinmez.
5. Beşinci unsurda "koru" seçilmişse doğrulanmış arşivden sonra çalışma
   kopyası silinmez; veri diskte kaldığı için §4.3 içerik penceresi açık
   kalır ve §30'daki 1., 8. ve 11. koşullar sağlanmamış olur (§30).
6. Eksiklik intake'ten sonra — pilot sırasında veya sonunda — fark edilirse
   (arşivde beşinci unsurun yokluğu dahil): veri otomatik **silinmez**; veri
   **arşivlenmez**; mevcut veri olduğu yerde, **değiştirilmeden ve güvenli
   biçimde** korunur; §4.3 içerik penceresi açık kalır ve kanal kapısı
   geçerliliğini korur; yeni ve eksiksiz yazılı avukat kararı beklenir. Bu
   bir **DUR**'dur (H55) ve pilot kapanmış sayılmaz.

### 28.2 Silme öncesi metadata manifestleri

İçerik snapshot'ı **alınmaz**. İki **ayrı** manifest üretilir ve birbirinin
yerine kullanılamaz:

| Manifest | Dosya | İlk satır | Göreli yol tabanı |
|---|---|---|---|
| Case | `<evidence-dir>\closing-case-manifest.tsv` | `# kind=case` | `<case-root>` |
| Restricted | `<evidence-dir>\closing-restricted-manifest.tsv` | `# kind=restricted` | `<restricted-dir>` |

Her iki manifest için: hedef yazılmadan önce **mevcut olmamalıdır**; var olan
bir manifestin üzerine **yazılmaz** (exclusive-create, §10.5'teki
`Write-PilotExclusive`); ilk satırdan sonraki her satır yalnız üç alan taşır:
göreli yol, bayt sayısı, SHA-256. Manifest gerçek mutlak yol veya gerçek
içerik **taşımaz**. İlk satır türü belirler; §28.3 ve §28.5'teki guard'lar
türü denetler, bu yüzden bir manifest diğerinin yerine kabul edilmez. Yazma
`False` dönerse veya hata verirse: **DUR** (H56); yeniden yazma denenmez.

**Case manifesti** iki aşamada, insan-only oturumda üretilir.

**Aşama 1 — göreli yolların ekranda kontrolü (dosyaya yazılmaz):**

```powershell
$root = "<case-root>"
$files = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File | Sort-Object FullName)
$files | ForEach-Object { $_.FullName.Substring($root.Length + 1) }
```

Göreli yollar §10.3'teki opak kimlikler sayesinde kişisel veri taşımamalıdır.
Bir yol kişisel veri taşıyorsa manifest **oluşturulmadan DUR**; opak
adlandırma olmadan manifest yazılmaz.

**Aşama 2 — case manifestinin yazılması:**

```powershell
$lines = @($files | ForEach-Object { "{0}`t{1}`t{2}" -f $_.FullName.Substring($root.Length + 1).Replace('\', '/'), $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
if (($lines.Count -ge 1) -and (Write-PilotExclusive "<evidence-dir>\closing-case-manifest.tsv" (@('# kind=case') + $lines))) { "CASE_MANIFEST=WRITTEN"; "CASE_FILE_COUNT=$($lines.Count)" } else { "STOP CASE_MANIFEST=FAIL" }
```

**Restricted manifesti.** `<restricted-dir>` dosya adları §10.5 gereği
baştan genel ve sabit olduğu için manifest gerçek ad **sızdırmaz**; ayrı bir
ekran aşamasına gerek yoktur. Önce §10.5 envanteri `RESTRICTED_INVENTORY=OK`
vermiş olmalıdır. Kapanış kümesi izinli kümenin alt kümesidir;
`mask-terms.txt` her zaman bulunur; `deadline-report.txt` yalnız ve yalnız
zincir adım 25 çıkış `0` ile tamamlandıysa (`<report-produced>` `$true`)
bulunur:

```powershell
$rDir = "<restricted-dir>"
$allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false))))
$allowedSet = @($allowedLines | Select-Object -Skip 1)
$rState = Get-PilotRestrictedState $rDir
$rNames = @($rState.Files | ForEach-Object { $_.Name })
$rSetOk = ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and ($null -ne $rState) -and ($rState.Bad -eq 0) -and (@($rNames | Where-Object { $allowedSet -cnotcontains $_ }).Count -eq 0) -and ($rNames -ccontains 'mask-terms.txt') -and (($rNames -ccontains 'deadline-report.txt') -eq <report-produced>)
if ($rSetOk) { $rLines = @($rState.Files | ForEach-Object { "{0}`t{1}`t{2}" -f $_.Name, $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }) }
if ($rSetOk -and (Write-PilotExclusive "<evidence-dir>\closing-restricted-manifest.tsv" (@('# kind=restricted') + $rLines))) { "RESTRICTED_MANIFEST=WRITTEN"; "RESTRICTED_FILE_COUNT=$($rLines.Count)" } else { "STOP RESTRICTED_MANIFEST=FAIL" }
```

Komutlar yalnız sabit durum satırı ve dosya sayısı basar. Belge baytlarının
ve restricted dosyalarının SHA-256'ları, içeriğe sahip biri için bir parmak
izidir; bu kalıcı iz §6.1/8 ve §7.1/7 kapsamında kabul edilmiş olmalıdır.
Tarih taşıyan dosyaların hash'ine ilişkin sınır §32/19'dadır.

### 28.3 Silme

Silme **yalnız** §28.1/3'teki açık ve eksiksiz yazılı kararla yapılır:
"sil" kararında doğrudan; arşiv kararında ise yalnız beşinci unsurda "sil"
açıkça seçilmişse ve §28.5'teki parite doğrulandıktan sonra. Karar eksikse
veya beşinci unsur "koru" ise bu bölüm **uygulanmaz** (§28.1/5, §28.1/6).
İki silme hedefi vardır ve her biri **ayrı** guard'dan, **ayrı** silme anı
kullanıcı onayından ve **tek** çalıştırmadan geçer: önce case dizini (§28.3.1),
sonra `<restricted-dir>` (§28.3.2). Bir hedefin silinmesi diğerinin
silinmesini yetkilendirmez.

#### 28.3.1 Case dizini

Silme hedefi **exact, çözümlenmiş case yoludur** ve §13.8 yol kapısından
(`PATH_OK=case-root`) bu oturumda geçmiştir. Guard, §13.8 ve §10.5'teki
ortak yardımcıları kullanan bir fonksiyondur; her oturumda yeniden tanımlanır.
Fonksiyon yalnız tek bir boolean döndürür, hiçbir şey basmaz; bütün
doğrulamaları `try` içinde yapar ve `True`'yu yalnız en sonda, her doğrulama
geçtikten sonra üretir:

```powershell
function Test-PilotCaseDeleteChecks([string]$target, [string]$casesRoot, [string]$caseId, [string]$manifestPath, [string[]]$protected) {
    $ErrorActionPreference = 'Stop'
    $ok = $false
    try {
        if (-not ((Test-PilotResolved $target) -and (Test-PilotResolved $casesRoot) -and (Test-PilotResolved $manifestPath) -and ($protected.Count -ge 1))) { return $false }
        foreach ($p in $protected) { if (-not (Test-PilotResolved $p)) { return $false } }
        $t = $target.TrimEnd('\')
        $leaf = [System.IO.Path]::GetFileName($t)
        if (-not (($leaf -ceq $caseId) -and ($leaf -ne 'case_0001') -and ([System.IO.Path]::GetDirectoryName($t) -eq $casesRoot.TrimEnd('\')))) { return $false }
        if (-not ((Test-Path -LiteralPath $target -PathType Container) -and (Test-PilotNoReparse $target))) { return $false }
        foreach ($p in $protected) { if (Test-PilotOverlap $target $p) { return $false } }
        $cManifest = @([System.IO.File]::ReadAllLines($manifestPath, (New-Object System.Text.UTF8Encoding($false))))
        if (($cManifest.Count -lt 2) -or ($cManifest[0] -cne '# kind=case')) { return $false }
        $cExpected = [string[]]@($cManifest | Select-Object -Skip 1)
        $seen = @{}
        foreach ($l in $cExpected) { $f = $l -split "`t"; if (($f.Count -ne 3) -or [string]::IsNullOrEmpty($f[0]) -or ($f[1] -cnotmatch '^[0-9]+\z') -or ($f[2] -cnotmatch '^[0-9a-f]{64}\z') -or $seen.ContainsKey($f[0])) { return $false }; $seen[$f[0]] = $true }
        $cItems = @(Get-ChildItem -LiteralPath $target -Recurse -Force)
        if (@($cItems | Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or -not (($_ -is [System.IO.FileInfo]) -or ($_ -is [System.IO.DirectoryInfo])) }).Count -ne 0) { return $false }
        $cLive = [string[]]@($cItems | Where-Object { $_ -is [System.IO.FileInfo] } | ForEach-Object { "{0}`t{1}`t{2}" -f $_.FullName.Substring($target.Length + 1).Replace('\', '/'), $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
        [Array]::Sort($cExpected, [System.StringComparer]::Ordinal)
        [Array]::Sort($cLive, [System.StringComparer]::Ordinal)
        if (($cLive.Count -eq $cExpected.Count) -and (($cLive -join "`n") -ceq ($cExpected -join "`n"))) { $ok = $true }
    }
    catch {
        $ok = $false
    }
    return $ok
}
```

Önce durum ve guard:

```powershell
git status --porcelain -- data/cases/case_0001
git status --ignored --porcelain -- data/cases
$target = "<case-root>"
$cGuard = $false
try {
    $cProtected = @("<external-root>", "<evidence-dir>", "<probe-evidence-dir>", "<inference-evidence-dir>", "<restricted-dir>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")
    $cChecks = @(Test-PilotCaseDeleteChecks $target "<repo-root>\data\cases" '<case-id>' "<evidence-dir>\closing-case-manifest.tsv" $cProtected)
    if (($cChecks.Count -eq 1) -and ($cChecks[0] -is [bool]) -and ($cChecks[0] -eq $true)) { $cGuard = $true }
}
catch {
    $cGuard = $false
}
if ($cGuard -eq $true) { "CASE_DELETE_GUARD=PASS" } else { "STOP CASE_DELETE_GUARD=FAIL" }
```

Beklenen: ilk komut **boş**; ikinci komut **yalnız**
`!! data/cases/<case-id>/`; guard **`CASE_DELETE_GUARD=PASS`**. Guard şunları
birlikte zorlar:

- hedefin yaprak adı tam olarak `<case-id>`; hedef kesinlikle `case_0001`
  değil; hedefin ebeveyni tam olarak `data\cases`;
- hedef ve korunan yolların her biri tanımlı, yer tutucu olmaktan çıkarılmış
  ve canonical çözümlenebiliyor; hedef `<external-root>`, üç evidence dizini,
  `<restricted-dir>`, Temp kökü, `<python-runtime-root>` ve `<pg-bin-dir>`
  ile örtüşmüyor;
- hedefin kendisi, sürücü köküne kadar üst dizinleri ve ağaçtaki hiçbir öğe
  reparse point (symlink veya junction) değil; ağaçta normal dosya ve dizin
  dışında öğe yok;
- case manifesti mevcut, ilk satırı tam olarak `# kind=case` (restricted
  manifesti yerine geçemez); her satır tam üç alan (göreli yol, ondalık bayt
  sayısı, 64 küçük harfli hex SHA-256) taşıyor; yinelenen göreli yol yok;
- **canlı parite:** `-Force` ile gizli dosyalar dahil alınan canlı göreli
  dosya kümesi, dosya sayısı, her dosyanın bayt sayısı ve SHA-256'sı kapanış
  manifestiyle birebir aynı. Manifestten sonra eklenen, değişen veya silinen
  her dosya guard'ı `False` yapar. Karşılaştırma bellek içinde yapılır;
  geçici dosya oluşturulmaz.

Ayrıştırma hatası, yol çözümleme hatası veya herhangi bir istisna guard'ı
`False` bırakır; çıktı yalnız genel `STOP CASE_DELETE_GUARD=FAIL` satırıdır,
yol, içerik veya istisna metni basılmaz. Guard başarısızsa silme
**yapılmaz**: **DUR** (H46).

Guard PASS ise ve **silme anında ayrı, açık kullanıcı onayı** alındıysa
(`CLAUDE.md` §8), aynı oturumda ve aynı `$target` değişkeniyle, **bir kez**,
aşağıdaki blok **tek parça** çalıştırılır. Blok guard'ı silmeden hemen önce
aynı scope'ta baştan yeniden hesaplar; önceki bir çalıştırmadan kalmış
`$cGuard` değeri kullanılamaz:

```powershell
$cGuard = $false
try {
    $cProtected = @("<external-root>", "<evidence-dir>", "<probe-evidence-dir>", "<inference-evidence-dir>", "<restricted-dir>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")
    $cChecks = @(Test-PilotCaseDeleteChecks $target "<repo-root>\data\cases" '<case-id>' "<evidence-dir>\closing-case-manifest.tsv" $cProtected)
    if (($cChecks.Count -eq 1) -and ($cChecks[0] -is [bool]) -and ($cChecks[0] -eq $true)) { $cGuard = $true }
}
catch {
    $cGuard = $false
}
if ($cGuard -eq $true) {
    try {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
        "CASE_DELETE_RESULT=COMPLETED"
    }
    catch {
        "STOP CASE_DELETE_RESULT=FAILED"
    }
}
else {
    "STOP CASE_DELETE_GUARD=FAIL"
}
$caseDirAbsent = -not (Test-Path -LiteralPath $target)
"CASE_DIR_ABSENT=$caseDirAbsent"
git status --ignored --porcelain -- data/cases
git status --porcelain -- data/cases/case_0001
```

Beklenen, hepsi birlikte: `CASE_DELETE_RESULT=COMPLETED`,
`CASE_DIR_ABSENT=True`, ignored görünüm **boş** ve `case_0001` görünümü
**boş**. `git status` çıktısının boşluğu `CASE_DIR_ABSENT=True` ölçümünün
**yerine geçmez**. `git clean -fdx` ve `git stash --all` **kullanılmaz**.
`STOP CASE_DELETE_GUARD=FAIL`, `STOP CASE_DELETE_RESULT=FAILED` veya
`CASE_DIR_ABSENT=False` çıkarsa ya da silme kısmi kalırsa tekrar, otomatik
retry veya doğaçlama düzeltme **yapılmaz**: **DUR** (H46); mevcut durum
yalnız bu bloktaki salt-okunur ölçüm satırlarıyla ölçülür ve raporlanır.

#### 28.3.2 `<restricted-dir>`

Hedef, §13.8'de `PATH_OK=restricted-dir` almış **exact** `<restricted-dir>`
dizinidir; glob, çözülmemiş değişken, üst dizin veya `git clean`
**kullanılmaz**. Silme öncesi guard, aynı oturumda ve case silmesinden sonra
çalıştırılır; şunların **hepsini** mekanik olarak doğrular:

- yol köklü, canonical ve kendi tam çözümüne birebir eşit;
- mevcut bir dizin; kendisi ve sürücü köküne kadar bütün üst dizinleri
  reparse point değil;
- ebeveyni tam olarak `<external-root>` (doğrudan çocuk);
- `<repo-root>`, `<case-root>`, üç evidence dizini, Temp kökü,
  `<python-runtime-root>` ve `<pg-bin-dir>` ile örtüşmüyor: hiçbirine eşit,
  hiçbirinin üst dizini veya alt dizini değil;
- bütün alt öğeleri normal dosya; alt dizin, reparse point veya symlink yok
  (§10.5);
- manifest dosyası `# kind=restricted` ile başlıyor ve adları §10.5 izinli
  kümesinin alt kümesi;
- mevcut göreli dosya kümesi, her dosyanın bayt sayısı ve SHA-256'sı —
  dolayısıyla dosya sayısı ve toplam bayt — kapanış manifestiyle
  (`closing-restricted-manifest.tsv`) birebir aynı;
- `<external-root>` hâlâ §13.8 sözleşmesini sağlıyor;
- `restricted-allowed-files.txt` kaydı, `restricted-allowed-files.sha256.txt`
  hash kaydındaki değerle yeniden doğrulandı (§10.5/4); doğrulanamazsa guard `False` kalır;
- karşılaştırılan her korunan yol tanımlı, yer tutucu olmaktan çıkarılmış ve
  canonical çözümlenebiliyor; çözümleme istisnası guard'ı `False` yapar.

```powershell
$rDir = "<restricted-dir>"
$rParent = "<external-root>"
$rGuard = $false
$allowedHashOk = Test-PilotAllowedHash "<evidence-dir>\restricted-allowed-files.txt" "<evidence-dir>\restricted-allowed-files.sha256.txt"
"ALLOWED_FILE_HASH_OK=$allowedHashOk"
$rPrevEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Stop'
    $g = ($allowedHashOk -eq $true) -and (Test-PilotResolved $rDir) -and (Test-PilotResolved $rParent) -and (Test-Path -LiteralPath $rDir -PathType Container) -and (Test-PilotNoReparse $rDir) -and ([System.IO.Path]::GetDirectoryName($rDir.TrimEnd('\')) -eq $rParent.TrimEnd('\'))
    if ($g) { $g = ((Test-PilotExternalRoot $rParent "<repo-root>" @("<evidence-dir>", "<probe-evidence-dir>", "<inference-evidence-dir>", "<restricted-dir>") @("<case-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) -eq $true) }
    $rManifest = @(); $allowedLines = @()
    if ($g) { $rManifest = @([System.IO.File]::ReadAllLines("<evidence-dir>\closing-restricted-manifest.tsv", (New-Object System.Text.UTF8Encoding($false)))); $allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false)))) }
    $allowedSet = @($allowedLines | Select-Object -Skip 1)
    $rExpected = @($rManifest | Select-Object -Skip 1)
    $g = $g -and ($rManifest.Count -ge 2) -and ($rManifest[0] -ceq '# kind=restricted') -and ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and (@($rExpected | Where-Object { $allowedSet -cnotcontains ($_ -split "`t")[0] }).Count -eq 0)
    if ($g) { foreach ($p in @("<repo-root>", "<case-root>", "<evidence-dir>", "<probe-evidence-dir>", "<inference-evidence-dir>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $rDir $p)) { $g = $false } } }
    if ($g) { $rState = Get-PilotRestrictedState $rDir; $rNow = @($rState.Files | ForEach-Object { "{0}`t{1}`t{2}" -f $_.Name, $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }); $g = ($null -ne $rState) -and ($rState.Bad -eq 0) -and ($rNow.Count -eq $rExpected.Count) -and (($rNow -join "`n") -ceq ($rExpected -join "`n")) }
    if ($g -eq $true) { $rGuard = $true }
}
catch {
    $rGuard = $false
}
finally {
    $ErrorActionPreference = $rPrevEap
}
if ($rGuard -eq $true) { "RESTRICTED_DELETE_GUARD=PASS" } else { "STOP RESTRICTED_DELETE_GUARD=FAIL" }
```

Beklenen: **`ALLOWED_FILE_HASH_OK=True`** ve
**`RESTRICTED_DELETE_GUARD=PASS`**. Komut yol, ad, hash veya istisna metni
basmaz. Guard başarısızsa silme **yapılmaz**: **DUR** (H46);
`ALLOWED_FILE_HASH_OK=False` ayrıca H56'dır.

Guard PASS ise ve **bu hedef için silme anında son ve ayrı, açık kullanıcı
onayı** alındıysa (`CLAUDE.md` §8), aynı oturumda ve aynı `$rDir` ile
`$rGuard` değişkenleriyle, **bir kez**:

```powershell
if ($rGuard -eq $true) { try { Remove-Item -LiteralPath $rDir -Recurse -Force -ErrorAction Stop; "RESTRICTED_DELETE_RESULT=COMPLETED" } catch { "STOP RESTRICTED_DELETE_RESULT=FAILED" } } else { "STOP RESTRICTED_DELETE_GUARD=FAIL" }
"RESTRICTED_DIR_ABSENT=$(-not (Test-Path -LiteralPath $rDir))"
"RESTRICTED_RESIDUE_COUNT=$(@(Get-ChildItem -LiteralPath $rDir -Force -Recurse -ErrorAction SilentlyContinue).Count)"
$extResidueOk = $false
try { $extKept = @("<evidence-dir>", "<probe-evidence-dir>", "<inference-evidence-dir>"); if ((Test-PilotExternalRoot $rParent "<repo-root>" $extKept @("<case-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) -eq $true) { $extNow = [string[]]@(Get-ChildItem -LiteralPath $rParent -Force -ErrorAction Stop | ForEach-Object { $_.Name }); $extExpected = [string[]]@($extKept | ForEach-Object { [System.IO.Path]::GetFileName($_.TrimEnd('\')) }); [Array]::Sort($extNow, [System.StringComparer]::Ordinal); [Array]::Sort($extExpected, [System.StringComparer]::Ordinal); $extResidueOk = (($extNow -join '|') -ceq ($extExpected -join '|')) } } catch { $extResidueOk = $false }
"EXTERNAL_ROOT_RESIDUE_OK=$extResidueOk"
git status --porcelain=v1 --untracked-files=all
git status --ignored --porcelain -- data/cases
git status --porcelain -- data/cases/case_0001
```

Beklenen, hepsi birlikte: `RESTRICTED_DELETE_RESULT=COMPLETED`,
`RESTRICTED_DIR_ABSENT=True`, `RESTRICTED_RESIDUE_COUNT=0`,
`EXTERNAL_ROOT_RESIDUE_OK=True` (`<external-root>` altında yalnız üç
metadata evidence dizini kalır) ve üç `git status` komutunun çıktısı **boş**
(tracked repo ve `case_0001` paritesi korunmuş, Git temiz). Kalıntı ölçümü
yalnız §13.8'deki pilot-owned çocuk kümesini değerlendirir ve önce
`<external-root>` sözleşmesini yeniden doğrular; bu yüzden hiçbir koşulda
bir sürücü kökünü veya genel kullanıcı dizinini temiz beklemez. Küme dışı
bir öğe intake'ten önce zaten §13.8 kapısında **DUR** üretmiş olmalıdır;
sonradan belirirse ölçüm `False` döner. Bu adım veritabanına bağlanmaz;
journal, assignment ve audit izlerine **dokunulmaz** (§28.4).

Silme hata verir veya kısmi kalırsa (`STOP RESTRICTED_DELETE_RESULT=FAILED`,
hedef hâlâ mevcut, kalıntı sayısı 0 değil veya
`EXTERNAL_ROOT_RESIDUE_OK=False`): tekrar veya doğaçlama
düzeltme **yapılmaz**; **DUR** (H46). Mevcut durum yalnız bu bloktaki
salt-okunur ölçüm satırlarıyla ölçülür ve §25.2'ye göre raporlanır.

### 28.4 Silinmeyenler

DB journal satırları, `mutation.mutation_resources` satırı, assignment satırı
ve security event'ler **silinmez**; uygulama rollerinin bu tablolarda `DELETE`
yetkisi yoktur ve bu izler kasıtlıdır (Adım 8 runbook'u §K.10). Metadata
manifestleri ve redakte operasyon özeti de kalır. Bu kalıcı izler hukuki onay
ve rıza kapsamında anılmış olmalıdır (§6.1/8, §7.1/7).

### 28.5 Şifreli arşiv (yalnız eksiksiz yazılı karar varsa)

Şifreli arşiv yalnız §28.1'deki yazılı karar onu **açıkça** seçtiyse ve beş
unsurun **tamamını** (arşiv yeri ve önceden onaylanmış ebeveyni, şifreleme
yöntemi, erişebilecek kişiler veya roller, saklama süresi ve nihai silme
tarihi veya koşulu, doğrulanmış arşivden sonra yerel çalışma kopyasının
silinmesi veya korunması) taşıyorsa uygulanır. Bu unsurların tamlığı gerçek
belge teslim alınmadan **önce** denetlenir (H4). Bir unsurun eksik olduğu
sonradan fark edilirse arşiv **yapılmaz** ve veri **silinmez**: §28.1/6
uygulanır.

**Arşiv hedefi kapısı.** Arşivlemeden önce, aynı oturumda `<archive-dir>`
mekanik olarak denetlenir: köklü ve canonical; ebeveyni tam olarak yazılı
kararda onaylanmış `<archive-parent>` (canonical, mevcut, kendisi ve üst
dizinleri reparse point değil; sürücü kökü olamaz); `<repo-root>`,
`<case-root>`, `<external-root>` (dolayısıyla evidence dizinleri ve
`<restricted-dir>`), Temp kökü, `<python-runtime-root>` ve `<pg-bin-dir>`
ile örtüşmüyor (eşit, üst veya alt dizin değil); mevcutsa reparse point'siz,
**boş** bir dizin. Yalnız metinsel yasak yeterli değildir:

```powershell
$aDir = "<archive-dir>"
$aParent = "<archive-parent>"
$aOk = $false
$aPrevEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Stop'
    $a = (Test-PilotResolved $aDir) -and (Test-PilotResolved $aParent) -and ($aParent.TrimEnd('\') -ne [System.IO.Path]::GetPathRoot($aParent).TrimEnd('\')) -and (Test-Path -LiteralPath $aParent -PathType Container) -and (Test-PilotNoReparse $aParent) -and ([System.IO.Path]::GetDirectoryName($aDir.TrimEnd('\')) -eq $aParent.TrimEnd('\'))
    if ($a) { foreach ($p in @("<repo-root>", "<case-root>", "<external-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $aDir $p)) { $a = $false } } }
    if ($a -and (Test-Path -LiteralPath $aDir)) { $a = (Test-Path -LiteralPath $aDir -PathType Container) -and (Test-PilotNoReparse $aDir) -and (@(Get-ChildItem -LiteralPath $aDir -Force).Count -eq 0) }
    if ($a -eq $true) { $aOk = $true }
}
catch {
    $aOk = $false
}
finally {
    $ErrorActionPreference = $aPrevEap
}
if ($aOk -eq $true) { "PATH_OK=archive-dir" } else { "STOP PATH_FAIL=archive-dir" }
```

Beklenen: `PATH_OK=archive-dir`. Komut yol veya istisna metni basmaz;
korunan bir yolun tanımsız, boş, hâlâ `<...>` biçiminde veya canonical
çözümlenemez olması ya da herhangi bir yol çözümleme istisnası `$aOk`'u
`False` bırakır. Hedefin yanlış ebeveyne
çözülmesi dahil başka her sonuç: arşivleme **yapılmaz**, **DUR** (H52). Hedef
dizinin yalnız bu pilot için ayrıldığı yazılı kararda belirtilir; boşluk
kontrolü bunun mekanik karşılığıdır. Bu komutlar standart PowerShell
davranışından gelir ve §1.5'teki provada doğrulanır.

- Çalışma kopyası silinmeden **önce** arşivin paritesi doğrulanır: case ve
  restricted kapsamının dosya kümesi, bayt sayıları ve SHA-256 değerleri,
  sırasıyla `# kind=case` ve `# kind=restricted` ile başlayan iki §28.2
  manifestiyle birebir eşleşmelidir; bir manifest diğerinin yerine
  kullanılmaz. Eşleşmezse veya doğrulanamazsa **DUR** (H47); hiçbir çalışma
  kopyası silinmez.
- Parite doğrulaması düz metin bir kopyayı diske yazmadan yapılamıyorsa
  **DUR**; arşiv yöntemi önceden bunu sağlayacak biçimde seçilmelidir.
- Parite doğrulandıktan sonra:
  - beşinci unsur **"sil"** ise case dizini ve `<restricted-dir>` §28.3'e
    göre, her hedef için ayrı guard ve silme anı onayıyla silinir; bu silme
    yazılı arşiv kararının açık parçasıdır (§28.1/3);
  - beşinci unsur **"koru"** ise hiçbir çalışma kopyası silinmez; §28.1/5
    ve §30 uygulanır.

### 28.6 Diğer kopyalar

Pilotta oluşmuş olabilecek ikinci kopyalar (indirme dizini, geçici dosyalar,
metin çıkarma aracının ara dosyaları) avukatın kararı doğrultusunda kaldırılır
ve sonucu evidence'a yazılır.

---

## 29. API anahtarı revoke ve ortam temizliği

Gerçek POST biter bitmez — sonucu ne olursa olsun — veya herhangi bir
DUR/abort anında, inference oturumunda değişken kaldırılır ve oturum
kapatılır:

```powershell
Remove-Item Env:ANTHROPIC_API_KEY
```

Ardından, bir sonraki zincir adımına geçmeden:

1. Pilot anahtarı Console'dan **revoke** edilir; revoke'un yapıldığı yalnız
   tarih/saat ve "revoked" durumu olarak kaydedilir (anahtarın hiçbir türevi
   yazılmaz). Sonuç belirsizse doğrulamak için yeni bir API isteği
   **yapılmaz**.
2. Yeni bir PowerShell oturumunda §13.6 (b) taraması yeniden çalıştırılır;
   beklenen üç kapsamda da **0 eşleşme**.
3. Pano, zararsız bir metinle üzerine yazılmış olmalıdır (§14.4).

Kapanışta (zincir adım 30) aynı tarama bir kez daha çalıştırılır. Bu
adımlardan biri başarısızsa pilot kapanmaz (H25).

---

## 30. Kapanış postcondition'ları

Hepsi mekanik olarak ölçülür ve evidence'a yazılır:

1. `data/cases/<case-id>` mevcut değil: ya "sil" kararıyla ya da beşinci
   unsuru "sil" olan bir arşiv kararında §28.5 paritesi doğrulandıktan sonra
   §28.3.1'e göre silindi; §28.3.1'de `CASE_DELETE_RESULT=COMPLETED` ve
   `CASE_DIR_ABSENT=True`.
2. `git status --ignored --porcelain -- data/cases` boş;
   `git status --porcelain -- data/cases/case_0001` boş.
3. `git status --porcelain=v1 --untracked-files=all` boş; HEAD başlangıçtaki
   commit.
4. `case:<case-id>` için aktif assignment **0**; journal'da `prepared`,
   `executing` veya `reconciliation_required` satırı **0**.
5. Yeni journal satırları yalnız beklenen aileler için ve `completed`
   durumunda.
6. Pilot anahtarı revoke edildi; hiçbir kapsamda §13.6 deseniyle eşleşen ad
   yok.
7. Genel evidence dizinlerinde gerçek içerik, rapor metni veya gerçek tarih
   yok; özet, `restricted-allowed-files.txt`, `restricted-allowed-files.sha256.txt`, `intake-hashes.tsv` ve iki
   ayrı kapanış manifesti (`closing-case-manifest.tsv`,
   `closing-restricted-manifest.tsv`) mevcut.
8. `<restricted-dir>` mevcut değil: §28.3.2'de `RESTRICTED_DIR_ABSENT=True`,
   `RESTRICTED_RESIDUE_COUNT=0` ve `EXTERNAL_ROOT_RESIDUE_OK=True`; arşiv
   kararında bundan önce §28.5 paritesi doğrulandı.
9. §22.3 `PENDING_MATCH` ve §24 `MATCH`.
10. Auth probe ve tek inference ayrı ayrı raporlandı: toplam iki dış ağ
    işlemi, bir `GET` ve bir `POST`.
11. İçerik penceresi kapandı: gerçek verinin yerel çalışma kopyası artık
    diskte değil (arşiv kararında önce paritesi doğrulanmış arşive alındı);
    §4.3 kanal kapısı kaydı pencere boyunca kesintisiz
    `AI_CONTENT_CHANNELS_CLOSED=True` gösteriyor.

Veri, eksik bir akıbet kararı yüzünden §28.1/6 gereği korunuyorsa 1., 8. ve
11. koşullar sağlanmamıştır; pilot **kapanmamıştır** ve silme bu yüzden
yapılamaz. Eksiksiz arşiv kararının beşinci unsuru "koru" ise ve parite
doğrulandıysa durum evidence'a `ARCHIVE_VERIFIED_WORKING_COPY_RETAINED`
olarak yazılır; 1., 8. ve 11. koşullar yine sağlanmamıştır, içerik penceresi
açıktır ve pilot ancak çalışma kopyası için yeni bir yazılı karar
uygulandıktan sonra kapanmış sayılır.

---

## 31. Roadmap LOCK kabul kriterleri

Adım 10 ancak şunların **hepsi** sağlandığında LOCK için önerilebilir:

1. §30'daki bütün postcondition'lar PASS.
2. §25.1'deki hiçbir DUR tetiklenmemiş veya tetiklenen her DUR için §25.2
   yolu tamamlanmış ve kullanıcı tarafından yazılı olarak kapatılmış.
3. Evidence özeti ve hash'leri tam.
4. Yürütmeden ayrı bir oturumda **bağımsız inceleme** blocking bulgu
   vermemiş. İnceleyici gerçek içeriği görmez; yalnız metadata-only evidence
   ile çalışır (§4.2).
5. Kullanıcının açık LOCK onayı.

LOCK kaydı ayrı bir roadmap-lock turunda yapılır: checkpoint gövdesi
`docs/roadmap/checkpoints/` altına yeni bir arşiv dosyası olarak yazılır ve
`INDEX.md`'ye kaydedilir; `CLAUDE.md`'ye yalnız kısa pointer girer
(`CLAUDE.md` §5 "Bundan sonra" kuralı). LOCK kaydı yalnız hash'ler, sayaçlar
ve redakte kapsam özetleri taşır; gerçek tarih, taraf, kimlik veya belge
içeriği taşımaz.

---

## 32. Açık sınırlar ve sonraki adımlar

1. Bu pilot **production-ready iddiası değildir**.
2. Masking **anonimleştirme değildir**; kamu kurumu adları maskelenmez ve
   tohumda olmayan dizgiler hayatta kalabilir (§15).
3. Sonuç **hukuki karar değildir**; avukat kendi hesabını sistemden önce ve
   bağımsız yapar (§21.2).
4. Süre aşımı (expiry) **değerlendirilmez**.
5. Sınır **tek dava / tek tebliğ / tek deadline / tek model POST'udur**; auth
   probe ayrı ve ikinci bir dış ağ işlemidir.
6. Sekiz event-specific hukuki aritmetik modellenmemiştir; yalnız fail-closed
   durdurma vardır.
7. Fact bazında düzeltme/ret yazıcısı yoktur; gereği promotion yapılmadan
   DUR'dur.
8. IAM aktörü avukatın kimliğini veya imzasını kanıtlamaz.
9. Egress katmanları tam bir işletim sistemi sandbox'ı değildir; harness,
   monitor ve probe aracı repo dışındadır ve kimlikleri repo içinden
   doğrulanamaz (§13.7).
10. Kümenin, harness'in veya ortamın durumu varsayılmaz; her operasyon
    öncesinde mekanik olarak ölçülür. Küme bir servis değildir.
11. Advisory-lock bounded acquisition hâlâ açıktır (`CLAUDE.md` §6).
12. Revoke CLI idempotent değildir; tek-çalıştırma kuralı bu yüzden vardır.
13. KVKK, DPA, yurt dışı aktarım ve avukatlık sırrı soruları kodla kapanmaz;
    yalnız §6'daki yazılı hukuki onayla kapanır.
14. İşletim sistemi düzeyindeki ikincil kopyalar (sayfa dosyası, antivirüs ve
    EDR telemetrisi, yedekleme yazılımı, sistem proxy ayarı) bu runbook
    tarafından mekanik olarak **denetlenemez**; yalnız §4.2/9 ölçümü ve cihaz
    sahibinin yazılı beyanıyla sınırlanır. `--mask-term` değerleri süreç
    argümanı olarak geçer (§15.3).
15. Motor apply sırasında maskesiz `Source actor:` etiketini stdout'a basar ve
    preview gerçek `--mask-term` değerlerini geri basar; ikisi de kod
    değişikliği gerektirir ve bu pilotta yalnız §4.2 sınırıyla karşılanır.
16. POST ile journal yazımı arasındaki bir veritabanı kesintisi tek gönderimi
    sonuçsuz tüketebilir (§18.3).
17. Intake'teki `verification_state` ve `notification_date` alanlarının
    deadline hesabına etkisi bu runbook için satır düzeyinde izlenmemiştir;
    ilgili kurallar bu yüzden fail-closed yazılmıştır (§11.2, §11.4).
18. Bu belgedeki PowerShell ve `psql` komutlarının hiçbiri henüz
    çalıştırılmamıştır; §1.5'teki sentetik prova bunun için zorunludur.
    Salt-okunur SQL çağırma biçimi provada yalnız statik olarak kontrol
    edilir; canlı kümedeki ilk kullanımı pilotun kendisindedir (§13.5).
19. **Hash tek başına gizlilik sağlamaz.** Deadline raporu ve kör hesap kaydı
    az sayıda olası değer taşıyan (düşük entropili) tarihler içerir; bu
    dosyaların SHA-256'ları, diğer alanları bilen biri için tarihleri
    çevrimdışı deneme-yanılmayla tahmine açık bırakabilir. Bu yüzden tarih
    taşıyan rapor ve kör hesap kaydı gerçek-veri kapsamındadır ve yalnız
    kısıtlı konumlarda durur (§10.2, §21.2, §23); genel evidence yalnız izin
    verilen asgari metadata'yı taşır (§26). Bu kalan risk kabul edilmiş bir
    sınırdır; bu runbook onun için yeni bir kriptografik tasarım tanımlamaz.
20. §4.3'teki süreç adı taraması tüketici değildir ve yalnız yardımcı bir
    sinyaldir: `node`, `Code - Insiders`, `python` veya tarayıcı gibi genel
    taşıyıcı süreçler sabit adla ayırt edilemez. Kanal kapısı sonuçta
    insan-only oturuma ve operatörün ölçüp kaydettiği
    `AI_CONTENT_CHANNELS_CLOSED=True` beyanına dayanır; bilinmeyen veya
    sınıflandırılamayan, içeriğe erişebilecek bir süreç **DUR**'dur.
21. Ek maskeleme terimi gerektirmeyen bir dosya bu runbook'la yürütülemez
    (§15.3).
22. Web arayüzü ve Entra login **Adım 11**'e aittir.
23. Hosting ve Key Vault **Adım 12**'ye aittir.
24. Çoklu deadline, expiry değerlendirmesi ve configurable case root sonraki
    adımlara aittir.
25. Row 19D ve Adım 11–13 açıktır.
26. Windows 8.3 kısa adları: yol kapıları canonical eşitliği verilen yazımla
    karşılaştırır; bir yer tutucunun 8.3 kısa adla verilmesi kapıyı **DUR**'a
    düşürebilir ve örtüşme kontrolü iki farklı yazımın aynı dizini
    gösterdiğini tanımayabilir. Bu davranış bu runbook'ta ayrıca
    modellenmemiştir; yer tutucular uzun adla verilir.
27. Gerçek inference'ın harness çağırma biçimi repo dışındadır; bu runbook
    yalnız iç argv'yi kurar (§18.2). Biçim pinli manifest ve prova ile
    doğrulanmadıkça gerçek apply kapısı **DUR** olarak kalır.

**Sonraki adım:** bu runbook'un yazar oturumundan ayrı ve temiz bir oturumda,
alt-ajan, Fable modeli ve advisor aracı kullanılmadan bağımsız incelenmesi;
ardından commit ve push, sentetik prova ve §6, §7 ile §28.1 belgeleri alınana
kadar yürütme **başlamaz**.
