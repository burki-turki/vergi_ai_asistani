# Yerel Gerçek Dava Pilotu (B Yolu) — Operatör Runbook'u

**Pilot Readiness Adım 10 / B yolu.** Bu belge, ilk gerçek vergi dosyasının
concierge modelde, tek dava ve tek tebliğ sınırı içinde, **tamamen yerel**
ve fail-closed biçimde işlenmesi için **operatör talimatı taslağıdır**.

> **Bu belgedeki hiçbir komut çalıştırılmamıştır.** Belge yazılırken hiçbir
> CLI, `psql`, Python veya PowerShell betiği çalıştırılmadı; hiçbir gerçek
> belge alınmadı; hiçbir veritabanı satırı yazılmadı; hiçbir ağ isteği
> yapılmadı; hiçbir API anahtarı, `.env` veya passfile okunmadı. Komut
> bloklarının yanındaki kaynak atıfları yalnız repo kaynağının **okunmasıyla**
> türetilmiştir.

---

## 0. Kaynak pinleri ve atıf biçimi

| Kaynak | Pin |
|---|---|
| Repo | `claude-dev`, HEAD `2c318ac` ("Add manual notification-date fact entry (generation.fact_manual)") |
| Temel runbook | `docs/operations/concierge-real-case-pilot.md` @ `2c318ac`, git blob `c2fee2d473df5f4b061c18de259cdacb469ff02f`, 3866 satır. Aşağıda **"Temel §N"** veya **"Temel L<a>–L<b>"** olarak anılır |
| Kod | Commit `2c318ac`: `ui/cli_mutate.py` (`manual-fact` alt komutu), `src/manual_fact_entry_engine.py`, `data/manual_fact_input.schema.json`, `ui/services/manual_fact_mutation_facade.py`, `ui/services/manual_fact_mutation_adapters.py` |
| Exact-scope | `vergi_step10_manual_fact_exact_scope_4161a431/exact-scope.md` (repo dışı); K-12, K-13, K-14, K-17, K-18, M-01…M-15 kodları oradan gelir |
| Kapsam çalışması | `vergi_step10_local_scope_92233ccf/scope.md` (repo dışı); §4 runbook bölüm sınıflaması oradan gelir |
| Avukat formu | **Sürüm 3** (v2'nin yerine geçer). Boş şablon: `Yerel_Pilot_Avukat_Formu_v3_SABLON.docx` (repo dışı, değişmez salt-okunur kopya), SHA-256 `97b1ae5417d7de795fda8185cc0fcee291481ada614964cdfc9d7278d8e55c44`. Bu hash yalnız **boş şablonun** kimliğidir; avukat şablonun bir kopyasını doldurur. **Doldurulmuş ve imzalanmış** formun (A–F + I) ve ayrı imzalanan G bölümünün hash'leri yürütmede ayrıca ölçülür (§6.6). v2 bu runbook'ta kullanılmaz |
| Avukat kararı | DRAFT-4 SORU 6.7: "Gerçek müvekkil dosyası + tamamen local processing → KABUL, dar kapsamlı pilot" |

**Kopyalama ilkesi.** Temel runbook'tan alınan bölümler **atıf yerine
kopyalanmıştır**: operatör yürütme sırasında tek belgeyle çalışır ve temel
runbook'un komşu (ağ/maskeleme) bloklarını yanlışlıkla çalıştırma riski
doğmaz. Her kopyalanan bölümün başında kaynak satır aralığı ve **sapmalar**
yazılıdır. "Sapma yok" yazan bir bölüm, kaynak aralığın ağ, anahtar ve
maskeleme referansları çıkarılmış birebir karşılığıdır.

---

## 1. Amaç ve belge statüsü

### 1.1 Amaç

Adım 9'da sentetik dosya üzerinde kanıtlanan fact → timeline → deadline →
salt-okunur avukat raporu zincirini, **tek bir gerçek dosya** üzerinde,
**hiçbir dış çağrı ve hiçbir yapay zekâ kullanılmadan** yürütmek. Tebliğ
tarihi modelden değil, operatörün belgeden elle girdiği ve avukatın orijinal
belgeyle karşılaştırdığı tek bir girdiden gelir.

### 1.2 B yolu tanımı (bağlayıcı)

- **Dış çağrı YOK.** Bu runbook'ta hiçbir adım internete, bir model
  sağlayıcısına, bulut OCR'a veya başka bir dış hizmete bağlanmaz. Pilot
  toplam **sıfır** dış ağ işlemi olarak raporlanır.
- **Yapay zekâ YOK.** Hiçbir ajan modu (`--with-agent`) ve hiçbir model
  çağrısı kullanılmaz. `generation --row-key fact_extraction` bu runbook'ta
  **ASLA** çalıştırılmaz (§14.7).
- **API anahtarı YOK.** Pilot için anahtar **oluşturulmaz**; hiçbir kapsamda
  `ANTHROPIC_*` değişkeni bulunmaz (§13.6).
- **Maskeleme YOK.** Veri makineden çıkmadığı için takma adlandırma
  katmanı kullanılmaz; `--mask-term`, maskeleme tohumu ve engel değerleri
  dosyası bu runbook'ta yoktur.
- Tebliğ tarihi **yeni** `manual-fact` alt komutuyla
  (`ui/cli_mutate.py:529-546`, action family `generation.fact_manual`) tek
  bir, her zaman `unverified` pending fact olarak sisteme girer
  (`src/manual_fact_entry_engine.py:450-481`). Doğrulama ayrı
  `verification` adımıdır (§15.3).

### 1.3 Dayanak

Avukatın DRAFT-4 SORU 6.7 cevabı: gerçek müvekkil dosyası + tamamen yerel
işlem **kabul — dar kapsamlı pilot**; takma adlı gerçek verinin dış
sağlayıcıya aktarılması Bölüm 6-D kapanmadan **kabul değil**. Bu runbook
yalnız birinci satıra dayanır. Avukat bu kararın yerel pilot için aynen
geçerli olduğunu formun **A1** sorusunda ayrıca teyit eder (§6.2).

### 1.4 Bu belge ne DEĞİLDİR

- **Yürütme yetkisi değildir.** Varlığı pilotun başlamasına izin vermez;
  §1.6 ön koşulları ve §6 form kapıları sağlandıktan sonra ayrı ve açık
  kullanıcı onayı (`REAL_ACTION_APPROVED`) gerekir.
- **Canonical roadmap kaydı değildir.** Canlı kurallar `CLAUDE.md`
  §1–§14'tedir; çelişkide `CLAUDE.md` geçerlidir.
- **Hukuki görüş değildir** ve avukatın hiçbir yazılı kararının yerine
  geçmez.
- **Temel runbook'un yerine geçmez ve onu değiştirmez.** Temel runbook
  (dış model yolu) R5 provasıyla pinlidir ve bu turda dokunulmamıştır.
- **Yapay zekâlı bir yolun ara sürümü değildir.** Bu belgedeki hiçbir adım
  sonradan bir model çağrısına "yükseltilerek" kullanılamaz; dış yol
  yalnız temel runbook ve Bölüm 6-D kapanışıyla mümkündür.
- **Production-ready iddiası değildir.**
- **Provası yapılmış bir belge değildir** (§1.6/3, §32).

### 1.5 Yazım kuralları (bağlayıcı)

Kaynak: Temel L61–L147. **Sapmalar:** yer tutucu tablosundan maskeleme,
probe, inference, harness, monitor, süreç-yardımcısı ve engel-dosyası yer
tutucuları çıkarıldı; `<attempt>`, `<journal-id>` ve `<reconcile-actor-ref>`
eklendi; `-m` istisnası (harness zinciri) kaldırıldı.

- **Yer tutucular** her zaman backtick veya kod bloğu içinde yazılır.

| Yer tutucu | Anlamı |
|---|---|
| `<repo-root>` | Repository kök dizininin mutlak yolu |
| `<case-root>` | Pilot case dizininin mutlak yolu: `<repo-root>\data\cases\<case-id>` |
| `<python>` | §13.3'teki yorumlayıcının mutlak yolu |
| `<psql>` | PostgreSQL 16 `psql.exe` dosyasının mutlak yolu (§13.5) |
| `<select-statement>` | §13.5, §26.3, §27.1 veya §14.6'daki `SELECT` ifadelerinden biri, tek satırda |
| `<case-id>` | Pilot dosyasının opak case kimliği (§10.3) |
| `<document-id>` | Tebliğ belgesinin opak document kimliği |
| `<fact-id>` | Manuel tebliğ fact'inin kimliği: `fact_<document-id>_manual_v1_<input_digest'in ilk 12 karakteri>_001` (`src/manual_fact_entry_engine.py:448-451`) |
| `<actor-user-id>` | Avukat kullanıcısının `iam.users.id` değeri |
| `<admin-user-id>` | İlk admin kullanıcısının `iam.users.id` değeri |
| `<anchor-event-id>` | Canonical timeline'daki tebliğ olayının `event_id` değeri |
| `<expected-hash>` | Önceki preview'ın bastığı SHA-256 |
| `<expected-input-digest>` | Önceki preview'ın bastığı `input_digest` |
| `<attempt>` | `manual-fact` apply deneme sayacı; ilk apply'da `1`, yalnız §14.6 yolu sonunda artırılır |
| `<pending-sha256>` | `manual-fact` preview'ın bastığı `pending_sha256` (§14.4) |
| `<lawyer-cited-prefix>` | Avukatın §14.3 yazılı kararında andığı, girdi sürüm hash'inin ilk 12 küçük hex karakteri |
| `<audit-file>` | `manual-fact` apply'ın bastığı `audit_file=` değeri (yalnız dosya adı; §14.5.2) |
| `<input-revision>` | Avukatın karşılaştırdığı girdi dosyası sürümünün sıra numarası; ilk sürüm `1`, en fazla `3` (§14.3, §14.5.3) |
| `<journal-id>` | İncelenecek `mutation.mutation_journal` satırının `id` değeri (§14.6) |
| `<reconcile-actor-ref>` | Reconciliation apply'ının teknik etiketi; bu pilotta **sabit** `local-pilot-operator` (kişisel veri taşımaz; ≤255 karakter; `ui/reconciliation_operator.py:198-210`) |
| `<attestation-ref>` | Avukatın stopping-event beyanının opak referansı |
| `<baseline-max-id>` | Bir apply'dan önce ölçülen en büyük journal `id` değeri (§26.3) |
| `<external-root>` | Repo dışı, bulut senkronizasyonu olmayan, **yalnız bu pilot için ayrılmış** kök dizinin mutlak ve canonical yolu; aşağıdaki **iki** dizinin ebeveyni. Sürücü kökü olamaz; `<repo-root>`'a eşit, onun altında veya atası olamaz; `<case-root>`, Temp kökü, `<python-runtime-root>` ve `<pg-bin-dir>` ile örtüşemez; doğrudan altında yalnız bu iki dizin bulunabilir (§13.8) |
| `<evidence-dir>` | `<external-root>` altında, **yalnız metadata** taşıyan pilot evidence dizini (§26) |
| `<restricted-dir>` | `<external-root>` altında, avukat kontrolündeki **dava-türevi içerik** dizini (§10.2, §10.5) |
| `<archive-dir>` | Yalnız şifreli arşiv kararında: formun F3'teki arşiv yerinin mutlak yolu (§28.5) |
| `<archive-parent>` | Yalnız şifreli arşiv kararında: F3'te önceden onaylanmış, `<archive-dir>`'in exact ebeveyni (§28.5) |
| `<python-runtime-root>` | §13.3'teki concierge runtime'ının kök dizini; `<python>` bunun altındadır (§13.8) |
| `<pg-bin-dir>` | PostgreSQL 16 `bin` dizini; `<psql>` bunun doğrudan altındadır (§13.8) |
| `<report-produced>` | Zincir adım 22 çıkış `0` ile tamamlandıysa `$true`, aksi hâlde `$false` (§28.2) |

- **Dizin ve dosya yer tutucuları mutlak, canonical ve önceden çözümlenmiş
  yollardır**: `<repo-root>`, `<case-root>`, `<python>`, `<psql>`,
  `<python-runtime-root>`, `<pg-bin-dir>`, `<external-root>`,
  `<evidence-dir>`, `<restricted-dir>`, `<archive-parent>` ve
  `<archive-dir>`. Göreli yol kabul **edilmez**. Her yol, kullanılmadan önce
  §13.8'deki yol kapısından geçer; geçmeyen yol **DUR**'dur.
- Yer tutucular **aynen kopyalanarak çalıştırılmaz**; her biri gerçek değerle
  değiştirilir.
- `yes`, `no`, `none`, `verified`, `lawyer`, `fact`, `timeline`, `deadline` ve
  `manual-fact` yer tutucu **değil**, CLI'ın kabul ettiği **literal**
  değerlerdir.
- Bütün komutlar repo kökünden (`<repo-root>`) ve Windows PowerShell içinde
  çalıştırılır. Python modülleri **yalnız `-m` biçimiyle** çağrılır
  (`docs/operations/local-postgresql-iam-adoption.md` §B.3). Bu runbook'ta
  istisna **yoktur**.
- Bu runbook'taki Python ve `psql` çağrılarının argümanları opak
  kimlikler, tamsayılar, 64 küçük hex digest/hash, sabit literal'ler,
  **mutlak yollar** (`<case-root>\case.json`, `<case-root>`,
  `<restricted-dir>\deadline-report.txt`) ve opak
  `<attestation-ref>`'tir. Belge içeriği (tarih, sayfa, alıntı, taraf adı,
  metin) hiçbir zaman süreç argümanı olarak **geçmez**; ancak mutlak yollar
  Windows kullanıcı profil adını taşıyabilir ve komut satırı denetimi
  açıksa bu ad görünür (§4.2/9, §32). Bu yüzden native `&` çağrı operatörü
  kullanılır (temel runbook'un §13.9 süreç yardımcısı bu yolda gerekmez;
  §29).
- Her Python oturumunda önce şu ayarlanır:

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

- Bu belgede gerçek kullanıcı adı, mutlak yerel yol, port, veritabanı adı,
  bağlantı dizesi, kimlik bilgisi dosyası, anahtar, kişi/kurum adı, iletişim
  bilgisi, kimlik veya vergi numarası **bulunmaz** ve operatör de bunları bu
  belgeye, commit'e veya evidence dizinine **yazmaz**.
- Bölüm numarası tek başına yazıldığında (ör. "§13") **bu runbook'un**
  bölümü kastedilir. Temel runbook "Temel §N", `CLAUDE.md` belge adıyla
  yazılır. "Zincir adım N" ifadesi §2.1 tablosundaki satır numarasıdır.
  "Form X" ifadesi avukat formundaki soru kodudur (A1, B4, F2 …).

### 1.6 Yürütme ön koşulları (bağlayıcı)

Kaynak: Temel L149–L269. **Sapmalar:** prova listesinden maskeleme, egress,
argv/DLL, ortam profili, harness ve probe kalemleri çıkarıldı; manuel
girdi, `manual-fact` ve reconciliation kalemleri eklendi; prova
veritabanı kararı açık bırakıldı; silme yöntemi / disk şifrelemesi ön
koşulu (madde 4) eklendi.

Gerçek veri alınmadan **önce**, aşağıdakilerin hepsi sağlanmış olmalıdır:

1. **Bağımsız inceleme.** Bu runbook, yazar oturumundan ayrı ve temiz bir
   oturumda incelenmiş ve blocking bulgu kalmamıştır.
2. **Commit ve push.** Runbook commit'lenmiş, push edilmiş ve yürütme
   yetkisinde kullanıcının onayladığı HEAD'de **tracked** olarak
   bulunmaktadır (§13.2 bunu ayrıca zorlar).
3. **Sentetik prova.** 1 ve 2'den sonra, ayrı bir turda ve ayrı kullanıcı
   yetkisiyle; **ağsız, API anahtarsız** ve yalnız sentetik, yeniden
   üretilebilir girdilerle şu adımlar prova edilmiştir:
   - içerik oturumunun açılması, profil/transcript kontrolleri, PSReadLine
     handler sınıflandırması, yardımcı süreç adı taraması ve geçmiş
     dosyasının değişmezliği (§4.3);
   - dizin yol kapısı (iki çocuklu `<external-root>` sözleşmesi dahil),
     `<python>`/`<psql>` dosya kapısı ve `<archive-dir>` kapısı (§13.8,
     §28.5);
   - manuel intake dosya biçimi ve kodlama kontrolleri; `page_count`
     kontrolü (§11.2); metin dosyasında tarih token'ı ön kontrolünün hem
     `True` hem `False` dalı (§11.3 b);
   - orijinal belge / `file.sha256` hash eşlemesi, intake hash kaydı ve
     yeniden karşılaştırma (§11.3 a, b);
   - açık argümanlı validator çağrıları (§11.3 c, d) ve vergi türü sözlük
     kontrolü (§11.3 f);
   - ortam değişkeni ad taraması ve `.env` boyut kontrolü (§13.6);
   - `<restricted-dir>` izinli dosya kümesi kaydı, hash kaydı ve envanter;
     beklenmeyen dosya, alt dizin ve reparse point reddi (§10.5);
   - manuel tebliğ girdisi dosyasının BOM/kodlama ön kontrolü (§14.2);
   - `manual-fact` preview ve apply'ın sentetik bir case üzerinde; §14.5
     hata tablosundaki en az şu satırların gözlenmesi: M-04 (`page_count`
     boş), M-07 (alıntı bulunamadı), M-08 (alıntıda farklı tarih), M-09
     (pending mevcut), `StaleViewError` (preview sonrası girdi değişti) ve
     usage exit `2` (`--with-agent` verilmesi); §14.3 hash-önce kaydı,
     revizyon sınırı guard'ı (`<input-revision>` = `4` reddi) ve sıra
     guard'ı (`r1` kaydı yokken `r2` reddi); §14.5.2 audit kontrol bloğu;
   - §14.6 yeniden deneme yolu: temp artığı ve audit ayrıştırma
     kontrollerinin yalnız boolean basması; reconciliation operatörünün
     dry-run ve apply çıktısının okunması ve `--attempt 2` ile tamamlanma;
     §14.6/6 temp silme guard'ının PASS dalı ve en az iki FAIL dalı (journal
     satırı `failed` değil; temp SHA uyuşmuyor).
     Bunun için sentetik case'te bir writer hatasının
     (`reconciliation_required` satırı) **kasıtlı olarak üretilmesi**
     gerekir; `completed` bir satır reconciliation'a uygun değildir. Hatanın
     nasıl üretileceği prova kapsam onayında belirlenir;
   - promotion → verification → timeline → deadline → rapor zincirinin aynı
     sentetik case üzerinde `calculated` ile tamamlanması;
   - iki ayrı metadata manifestinin exclusive-create davranışı ve
     **başlık-yalnız** restricted manifesti (rapor üretilmeden DUR senaryosu)
     dahil restricted silme guard'ının PASS/FAIL dalları (§28.2, §28.3);
   - case ve `<restricted-dir>` exact-path silme guard'larının negatif
     kontrolleri (temel runbook'taki liste: yanlış ebeveyn, `case_0001`,
     `<repo-root>`, manifest sonrası dosya ekleme/değiştirme/silme,
     yer tutucu bırakılmış korunan yol, bozulmuş hash kaydı, sürücü kökü
     veya repo atası `<external-root>`); negatif kontrollerde **yalnız
     guard bloğu** çalıştırılır;
   - salt-okunur SQL çağırma ve çıktı sözleşmesinin statik kontrolü
     (§13.5);
   - rapor satırı boolean kontrolü (§19) ve güvenli DUR/abort akışının
     dosya içermeyen dalları (§25.2);
   - **bu cihazdaki şifreleme yolunun kaydı (O-f).** Operatör, içerik
     taşımayan prova oturumunda §4.2/10'daki üç yolun bu cihazda bulunup
     bulunmadığını ekranda okur ve prova evidence'ına yalnız boolean
     yazar: `DEVICE_ENCRYPTION_PAGE_PRESENT=True/False`,
     `BITLOCKER_PANEL_PRESENT=True/False`,
     `THIRD_PARTY_FDE_PRESENT=True/False` ve harici disk için
     `EXTERNAL_DISK_PRESENT=True/False`. Üçü de `False` ise pilot bu
     cihazda yapılamaz (§32/12). Prova sonrasında cihazda işletim sistemi
     sürümü (ör. Pro yükseltmesi) veya şifreleme durumu değişirse bu kayıt
     zincir adım 4'ten önce, içerik taşımayan bir oturumda yeniden yazılır;
     provanın tekrarlanıp tekrarlanmayacağı kullanıcı kararıdır.

   **Prova veritabanı (açık karar).** `manual-fact` preview dahil
   veritabanlı adımlar bir PostgreSQL bağlantısı gerektirir
   (`ui/services/manual_fact_mutation_facade.py:634-643, 656-665`). Provada
   hangi kümenin (disposable küme veya pilot kümesinde sentetik case)
   kullanılacağı bu runbook'ta **sabitlenmemiştir**; prova kapsam onayında
   ayrıca kararlaştırılır.

   Prova gerçek pilot **değildir**; kendi ayrı evidence'ını üretir, sentetik
   dizini kendi sonunda siler ve hiçbir gerçek belge kullanmaz. Provada bir
   komut bu belgede yazıldığı gibi çalışmazsa runbook **düzeltilir ve
   yeniden incelenir**; komut sahada doğaçlama değiştirilmez.

4. **Silme yöntemi ve disk şifrelemesi (H-1).** Bu runbook'ta tanımlı tek
   silme yöntemi Form F4 seçenek (1)'dir: geri dönüşüm kutusu kullanılmadan
   standart silme, **tam disk şifrelemesi açıkken**. Bu yüzden gerçek belge
   teslim alınmadan önce şunların hepsi sağlanmıştır:
   - Form **E1** = "Evet" ve Form **F4** = seçenek (1) (§23);
   - yürütme günü, zincir adım 4'te §4.2/10'daki şifreleme doğrulaması
     `FULL_DISK_ENCRYPTION_CONFIRMED=True` vermiştir; doğrulama gerçek
     verinin dokunacağı **her** sürücüyü kapsar (§4.2/10).

   F4 seçenek (2) (üzerine yazan araç) veya (3) ("Diğer") işaretliyse, E1
   "Hayır" ise, şifreleme doğrulanamıyorsa veya harici disk kuralı
   (§4.2/10) sağlanmıyorsa: **DUR — gerçek belge teslim alınmaz.** Bu cihaz
   runbook yazılırken Windows 10 **Home**'dur (BitLocker yok); kullanıcı
   cihazı Windows 10 Pro'ya yükseltip BitLocker kullanmayı planlamaktadır
   (henüz yapılmadı). Şifreleme yalnız §4.2/10'da tanımlanan **üç** yoldan
   biriyle doğrulanır. Seçenek (2) yalnız aracı ve sürümünü tanımlayan ayrı
   bir runbook revizyonu ve bağımsız inceleme ile kullanılabilir hâle gelir.

Bu dört ön koşuldan biri eksikse: **DUR — gerçek belge teslim alınmaz.**
Madde 1–3 zincir adım 1'de, madde 4 zincir adım 2 (form cevapları) ve
zincir adım 4'te (şifreleme ve harici disk ölçümü) değerlendirilir.

---

## 2. Pilot kapsamı

- **Bir** gerçek vergi dosyası (`<case-id>`).
- Bu dosyada **bir** tebliğ ve ondan doğan **bir** dava açma süresi.
- Tebliğ bilgisini taşıyan **tek** belge (`<document-id>`); türü
  `vergi_ceza_ihbarnamesi` (`src/manual_fact_entry_engine.py:102, 353-356`).
- **Tek** manuel fact: tebliğ tarihi (`role = notification_date`), sayfa
  numarası ve belgeden birebir alıntıyla
  (`data/manual_fact_input.schema.json:39-88`).
- Mevcut koordineli CLI aileleri: `manual-fact` (yeni), `promotion` (`fact`,
  `timeline`), `verification`, `generation` (`timeline`, `deadline`),
  `approval` (`deadline`) ve salt-okunur `ui.deadline_report`.
- Adım 8'de kurulan kalıcı yerel PostgreSQL kümesi ve mevcut IAM kullanıcıları.
- Avukatın yazılı kararlarının mevcut lawyer IAM aktörü üzerinden birebir
  uygulanması.
- Pilot sonunda formun F bölümüne göre gerçek verinin silinmesi veya
  şifreli arşivi (§28).
- **Sıfır** dış ağ işlemi.

### 2.1 Operasyon zinciri (bağlayıcı sıra)

Sıra değiştirilemez; bir adım PASS olmadan sonrakine geçilmez. Tek istisna
§25.2'deki güvenli DUR/abort yolu ve §14.6'daki reconciliation/yeniden
deneme yoludur (ikisi de ayrı onaylıdır).

**Onay türleri** (`CLAUDE.md` §14.9, §14.10, §8):

- **`REAL_ACTION_APPROVED`** — kullanıcının (proje sahibinin) o adım ve o
  hedef için ayrı, açık onayı. Bir önceki onay sonrakinin yerine geçmez.
- **`LEGAL_APPROVED`** — avukatın o konudaki yazılı kararı/onayı. Repo
  dışında saklanır; evidence'a yalnız SHA-256'sı girer.
- **—** — ayrı onay gerekmez; adım yürütme yetkisi kapsamındadır (yan
  etkisiz ölçüm veya pending üretimi; Temel §2.1 son paragrafı emsali).

| # | Adım | Kim | Onay türü | DUR koşulu (özet) | Bölüm |
|---|---|---|---|---|---|
| 1 | Yürütme ön koşulları: incelenmiş, commit'li ve push'lu runbook; sentetik prova | Kullanıcı | `REAL_ACTION_APPROVED` (yürütme yetkisi, gerçek veri işlenmesi) | §1.6/1–3'ten biri eksik (madde 4 adım 2 ve 4'te) | §1.6 |
| 2 | Doldurulmuş, imzalı avukat formu (A–F + I) ve ekleri; form kapılarının kontrolü; formun ve eklerin hash'i; `TWO_PERSON_CONTROL` kaydı | Avukat → operatör kontrol eder | `LEGAL_APPROVED` (form imzası); B4 "aynı kişi" ise ayrıca `REAL_ACTION_APPROVED` (`WAIVED_B4`, §4.1) | Zorunlu bir soru boş veya kapıyı kapatan cevap; imza biçimi geçersiz; E1 ≠ "Evet" veya F4 ≠ seçenek (1); E1'e yazılmış ek koşul (§6, §23) | §4.1, §6, §7, §9, §23 |
| 3 | Dosya seçimi: formun ayrı imzalı G bölümü (G0–G11) ve hash'i | Avukat | `LEGAL_APPROVED` (G imzası) | G1–G7 veya G9'dan biri "Hayır" veya boş; G0 veya G8 boş; G10/G11 eksik; G10 tarihi bağlayıcı I3 tarihinden önce | §8, §6.6 |
| 4 | Preflight: içerik oturumu, kanal kapısı, **disk şifrelemesi doğrulaması ve harici disk kaydı**, yol kapısı, repo/DB/ortam ölçümü, `<restricted-dir>` izinli küme ve hash kaydı | Operatör; şifreleme aracı kabulü kullanıcı | Yalnız yol 2 (BitLocker) veya yol 3 (üçüncü taraf araç) kullanılıyorsa: aracın kabulü için `REAL_ACTION_APPROVED` (§4.2/10) | Herhangi bir `STOP` satırı; `FULL_DISK_ENCRYPTION_CONFIRMED=True` yok; yol 2/3'te `ENCRYPTION_TOOL_USER_ACCEPTED=True` yok; harici disk ne şifreli ne çıkarılmış | §4.2/10, §4.3, §10.5, §13 |
| 5 | Belge teslimi (Form E2 kanalı) ve manuel intake (`case.json`, `document.json` + **`page_count`**, orijinal, `extracted/<document-id>.txt`) | Operatör | — | Form/G hash yeniden ölçümü kayıtla uyuşmuyor (§6.6/7 a); E2 taşıyıcısı kontrolü geçmedi (§6.4); case dizini önceden var; BOM; `page_count` boş; E4 dışı araç | §6.4, §6.6, §11.2 |
| 6 | Mekanik kontroller ve avukatın alan-alan intake onayı | Operatör + avukat | `LEGAL_APPROVED` | Hash/validator/sözlük/ignore kontrolü veya alan onayı eksik | §11.3, §11.4 |
| 7 | Manuel tebliğ girdisi dosyasının yazılması ve sürüm hash kaydı (`manual-input-r<input-revision>`) | Operatör | — | BOM/kodlama ön kontrolü geçmedi; hash kaydı yazılamadı; revizyon sınırı aşıldı | §14.2, §14.3 |
| 8 | Avukatın girdi dosyasını orijinal belgeyle karşılaştırması (iki kişi kuralı); yazılı karar `r<input-revision>` ve hash önekini anar | Avukat | `LEGAL_APPROVED` | Karşılaştırma yok; kararda sürüm/hash öneki yok veya kayıtla uyuşmuyor; aynı kişi ve Form B4 kabulü yok | §14.3 |
| 9 | `assign-case` | Operatör (ADMIN) | `REAL_ACTION_APPROVED` | Sonuç belirsiz; aktif assignment ≠ 1 | §12.3 |
| 10 | `manual-fact` preview | Operatör (APP) | — | Çıkış ≠ 0; tarih/sayfa avukatın teyit ettiği değerden farklı | §14.4 |
| 11 | `manual-fact` apply | Operatör (APP) | `REAL_ACTION_APPROVED` | Çıkış ≠ 0; `replayed=True`; journal ≠ 1 yeni `completed` satır | §14.5 |
| 12 | Pending içerik kontrolü (yöntem, sayı, hash) | Operatör + avukat | — | `method` ≠ `manual`, fact ≠ 1, hash farkı | §15.1 |
| 13 | Fact promotion | Operatör (APP) | `LEGAL_APPROVED` (kabul) + `REAL_ACTION_APPROVED` | Preview/kapı eksik; `validation_ready` ≠ `True` | §15.2 |
| 14 | Tebliğ fact'inin verification'ı | Operatör (APP) | `LEGAL_APPROVED` (verification kararı) + `REAL_ACTION_APPROVED` | Locator/aktiflik/avukat karşılaştırması eksik | §15.3 |
| 15 | Timeline generation | Operatör (APP) | — | Çıkış ≠ 0 | §16 |
| 16 | Timeline promotion | Operatör (APP) | `LEGAL_APPROVED` + `REAL_ACTION_APPROVED` | İkinci tebliğ olayı; anchor `verified` değil | §16 |
| 17 | Stopping-event beyanı ve adli tatil kararı | Avukat | `LEGAL_APPROVED` | `present`/`unknown`; adli tatil `yes`/`no` değil | §17.1 |
| 18 | Kör bağımsız hesabın sabitlenmesi | Avukat | `LEGAL_APPROVED` (hesap kaydı + hash) | Hash evidence'ta değil | §17.2 |
| 19 | Deadline generation | Operatör (APP) | — | Çıkış ≠ 0 | §18.1 |
| 20 | Pending tarihin sabitlenmiş hesapla karşılaştırılması | Operatör + avukat | — | Eşleşmeme | §18.3 |
| 21 | Deadline approval | Operatör (APP) | `LEGAL_APPROVED` + `REAL_ACTION_APPROVED` | Kabul kriterleri veya `PENDING_MATCH` yok | §18.4 |
| 22 | Salt-okunur deadline raporu | Operatör (APP) | — | Rapor reddi; zorunlu satır eksik | §19 |
| 23 | Rapor tarihinin son karşılaştırması | Operatör + avukat | — | Eşleşmeme | §20 |
| 24 | Assignment revoke | Operatör (ADMIN) | `REAL_ACTION_APPROVED` | Aktif assignment ≠ 1 | §27 |
| 25 | İki metadata-only kapanış manifesti | Operatör | — | Exclusive-create başarısız | §28.2 |
| 26 | Gerçek verinin silinmesi veya şifreli arşivi | Operatör | Form F2–F4 (`LEGAL_APPROVED`) + **her hedef için** `REAL_ACTION_APPROVED` | Guard FAIL; F4 ≠ seçenek (1); silme günü şifreleme yeniden doğrulanamadı | §28.3, §28.5 |
| 27 | Repo dışı geçici kopyaların F1 süresi içinde silinmesi ve imha kaydı | Operatör | `REAL_ACTION_APPROVED` (silme) | F1 süresi aşıldı; kopya şifresiz ortamda; F5 kaydı yazılmadı | §28.6, §28.7 |
| 28 | Ortamın kapanış ölçümü | Operatör | — | Ad taramasında eşleşme | §13.6 |
| 29 | Postcondition'lar ve LOCK kaydı | Operatör; LOCK ayrı tur | LOCK onayı | Herhangi bir postcondition FAIL | §30, §31 |

**Sıra istisnaları (bağlayıcı):**

- **Zincir adım 2 ve 3** iki ayrı imzayla karşılanır: A–F bölümleri I
  bölümüyle, G bölümü kendi G10/G11 alanıyla imzalanır (form v3). Kapıları
  **ayrı ayrı** değerlendirilir. G bölümü, bağlayıcı (en son imzalı) A–F
  sürümünden **sonra** imzalanmış olmalıdır: G10 tarihi o sürümün I3
  tarihinden önce olamaz. A–F sonradan yeniden imzalanırsa G bölümü de
  yeniden imzalanmadıkça **DUR** (Y1, Y7; §6.6).
- **Zincir adım 27** yalnız zincir adım 23'e (veya §25.2 abort yolunun
  başlamasına) bağlıdır; 24–26'yı **beklemez** ve onlardan bağımsız olarak,
  F1 süresi içinde çalıştırılır. Bu adımın F1 süresini aşması **DUR**'dur
  (Y6); 24–26'nın sürmesi bu süreyi uzatmaz.

Zincir adım 15 ve 19 pending üretir; canonical mutasyon değildir ve yürütme
yetkisi kapsamında ayrı onay olmadan çalışır (Temel L340–L343). Zincir adım
11 de pending üretir, ama **ayrı** `REAL_ACTION_APPROVED` ister: gerçek
veriden insan girdisiyle ilk sistem kaydını oluşturan adımdır
(`CLAUDE.md` §14.9, "gerçek kaydın oluşturulması") ve iki kişi kuralı
(K-12) yalnız runbook'la sağlanır. Bu seçim inceleyici için §33'te ayrıca
kaydedilmiştir.

---

## 3. Kapsam dışı işler

Kaynak: Temel L347–L374. **Sapmalar:** model çağrısı satırları "hiçbir
model çağrısı" ile değiştirildi; `fact_extraction` ve ağ satırları eklendi.

Aşağıdakiler bu pilotta **yapılmaz**; görülürse **DUR**:

- İkinci dava, ikinci tebliğ, ikinci deadline adayı veya ikinci manuel fact.
- **Herhangi bir** model çağrısı, ajan modu (`--with-agent`), ağ bayrağı
  (`--allow-network`) veya `generation --row-key fact_extraction` (§14.7).
- Herhangi bir dış ağ işlemi; API anahtarı oluşturulması veya ortama
  konması.
- Bulut OCR, çeviri veya dönüştürme hizmeti.
- Tebliğ belgesi dışındaki belgelerden fact girilmesi.
- `qa` ve `case_view` generation/approval (rapor yalnız canonical
  `deadlines/deadline.json` ile `approval.deadline` journal kaydını okur;
  Temel L356–L359).
- Issue spotting, legal research, case law, evidence, argument,
  risk/strategy, drafting.
- Süre aşımı (expiry) değerlendirmesi.
- Sekiz event-specific hukuki aritmetik (uzlaşma, İYUK m.11 başvurusu, VUK
  m.35, VUK m.376, usulsüz tebligat/öğrenme tarihi, pişmanlık ihlali,
  değerleme/takdir komisyonu, SORU 5.5 tarihsel dönemleri) — `CLAUDE.md`
  §5, Adım 7 kapanışı.
- Web arayüzü, OIDC/Entra login (Adım 11); hosting, Key Vault (Adım 12).
- Çoklu deadline ve configurable case root.
- RAG corpus edinimi veya bundle aktivasyonu.
- Herhangi bir repo dosyasının değiştirilmesi, commit veya push (yürütme
  turunda; LOCK kaydı ayrı bir turdur).
- Pending, canonical, audit veya journal dosyasının/satırının **elle**
  düzenlenmesi; düzeltici SQL.
- Gerçek içeriğin §4.2'deki güven sınırının dışına çıkarılması.

---

## 4. Roller, sorumluluklar ve gerçek içerik güven sınırı

### 4.1 Roller ve iki kişi kuralı (K-12)

Kaynak: Temel L380–L395. **Sapmalar:** maskeli metin okuması çıkarıldı;
iki kişi kuralı manuel girdiye bağlandı ve Form B4 kapısı eklendi.

| Rol | Sorumluluk | Yapamayacağı |
|---|---|---|
| **Avukat** | Formun doldurulması ve imzası; belge teslimi; dosya seçimi (G); intake alanlarının alan-alan doğrulanması; **manuel tebliğ girdisinin orijinal belgeyle karşılaştırılması**; fact kabulü; tebliğ tarihi verification kararı; adli tatil kararı; stopping-event beyanı; kör bağımsız hesap; deadline onayı; veri akıbeti kararı | — |
| **Müvekkil (veri sahibi)** | Form C'ye göre bilgilendirme/rıza | — |
| **Operatör (insan)** | Ortam/DB ölçümü; manuel intake; **manuel tebliğ girdisinin yazılması**; mekanik kontroller; avukat kararlarının CLI ile birebir uygulanması; evidence; cleanup | Hukuki karar vermek; avukat kararını yorumlamak; eksik kararı varsaymak; kendi girdisini doğrulamak; kapsam genişletmek |
| **Kullanıcı (proje sahibi)** | Yürütme yetkisi; her canonical mutasyon, manuel fact apply'ı, reconciliation apply'ı, assignment değişikliği ve silme için ayrı `REAL_ACTION_APPROVED`; LOCK onayı | — |
| **Bağımsız inceleyici** | Runbook ve yürütme evidence'ının ayrı oturumda incelenmesi | Yürütmeye katılmak; gerçek içeriği görmek |

**İki kişi kuralı (bağlayıcı).** Tebliğ tarihini **operatör girer, avukat
doğrular**: girdi dosyasını (§14.2) yazan kişi ile onu orijinal belgeyle
karşılaştıran (§14.3) ve verification kararını veren (§15.3) kişi **ayrı**
olmalıdır.

- Kod bu ayrımı **zorlamaz**: `manual-fact`, `promotion` ve `verification`
  yalnız aynı case için `mutate` yetkisini denetler; aynı IAM aktörü üçünü de
  yapabilir (exact-scope §8/4, K-12/O-2). Ayrım yalnız bu kuralla sağlanır.
- Avukat ile operatör **ayrı kişilerse** (B4 "Evet, ayrı kişiler"): durum
  zincir adım 2'de evidence'a `TWO_PERSON_CONTROL=SEPARATE` olarak yazılır.
- Avukat ile operatör **aynı kişiyse**: formun **B4** sorusunda "Hayır, aynı
  kişi; iki kişili kontrolün kalkmasını kabul ediyorum" seçeneği işaretli
  olmalıdır; değilse **DUR** (Y4). Kabul varsa durum evidence'a
  `TWO_PERSON_CONTROL=WAIVED_B4` olarak yazılır; ayrıca
  `REAL_ACTION_APPROVED` ile kullanıcı tarafından onaylanır (Temel L390–L395
  emsali).
- Evidence'ta bu iki satırdan **tam biri** bulunmadan zincir adım 7'ye
  geçilmez (Y4).
- B4 boşsa: **DUR**.
- Müvekkil rolü hiçbir durumda operatör rolüyle birleşmez.

### 4.2 Gerçek içerik güven sınırı (bağlayıcı)

Kaynak: Temel L397–L471. **Sapmalar:** maskeli metin, `--mask-term`,
engel değerleri, harness/monitor ve `Source actor:` maddeleri çıkarıldı;
manuel girdi dosyası ve `manual-fact` çıktıları eklendi; OCR aracı Form
E4'e bağlandı.

**Gerçek içerik** şunların tamamıdır: orijinal belge; extracted text;
`case.json` ve `document.json`; **manuel tebliğ girdisi dosyası**
(`manual_facts.input.json`); pending ve canonical fact, timeline ve deadline
dosyalarının içeriği; generation/approval audit kayıtları; deadline raporu;
avukatın kör hesap kaydı; bu komutların ham stdout/stderr çıktısı
(özellikle `manual-fact` preview'ın bastığı `notification_date` ve `page`
satırları ve her Python traceback'i).

1. Gerçek içeriğe **yalnız insan operatör ve avukat** erişir.
2. Claude Code, ChatGPT veya başka herhangi bir AI asistanı; bulut OCR,
   çeviri veya dönüştürme hizmeti; bulut pano; ekran paylaşımı; otomatik ekran
   kaydı; uzaktan destek oturumu gerçek içeriği **göremez**.
3. OCR ve metin çıkarma **yalnız** formun **E4** sorusunda adı ve sürümü
   yazılmış ve "Bu aracı onaylıyorum" işaretlenmiş **yerel ve çevrimdışı**
   araçla yapılır. Aracın adı ve sürümü evidence'a yazılır. E4 boş veya
   onaysızsa: **DUR** (Y5).
4. Bulut senkronizasyonlu klasör ve bulut senkronizasyonlu pano kullanılmaz.
5. Gerçek içerik veya onu gösteren bir ekran görüntüsü hiçbir sohbet veya
   ajan oturumuna **yapıştırılmaz**.
6. İçeriğe dokunan her adım (intake, metin çıkarma, manuel girdi yazımı,
   validator'lar, `manual-fact` preview/apply, pending/canonical okuma,
   rapor, manifest, silme) **insan-only bir PowerShell oturumunda** yürütülür.
   Bu oturum, AI asistanının çalıştığı oturumdan **tamamen ayrıdır**: AI
   asistanı bu kabuğu süremez, çıktısını okuyamaz, `<case-root>` veya
   `<restricted-dir>` altındaki hiçbir dosyayı açamaz. İçerik penceresi
   boyunca bu kanalların **kapalı** olduğu §4.3'teki kanal kapısıyla ölçülür
   ve kaydedilir.
7. Bir AI oturumuna **yalnız** şunlar aktarılabilir: opak kimlikler, hash'ler,
   sayaçlar, `PASS`/`FAIL` değerleri ve kişisel veri içermeyen sabit hata
   kodları (ör. `ManualFactExcerptRejectedError`, `M-08`). Bu aktarım, içerik
   penceresi boyunca ancak çalışma ağacına, `<restricted-dir>`'e ve içerik
   oturumunun ekranına erişimi **olmayan** bir oturuma yapılabilir.
8. **Ham stdout/stderr dava-türevi içerik sayılır**; evidence'a veya bir AI
   oturumuna taşınmaz. Somut sınırlar:
   - `manual-fact` preview `notification_date` ve `page` değerlerini
     stdout'a basar (`ui/cli_mutate.py:1877-1890`). Alıntı metnini **basmaz**,
     yalnız SHA-256'sını basar (K-18; aynı satırlar).
   - Bilinen hata satırları (`ERROR: <Sınıf>: <mesaj>`) sabit metin + kural
     kodu taşır; alıntı metni, girdi içeriği ve mutlak yol mesaja girmez
     (`ui/services/manual_fact_mutation_facade.py:25-28`). Bu bir tasarım
     sözleşmesidir; ham satır yine de evidence'a kopyalanmaz, yalnız sınıf
     adı ve kural kodu yazılır.
   - **Traceback** (bilinmeyen hata; §14.5) mutlak yol ve içerik taşıyabilir;
     hiçbir yere kopyalanmaz.
   - Validator çıktısı kimlik ve yol taşır.
9. **Kayıt ve telemetri.** PowerShell transcription, script-block logging,
   modül logging veya süreç-oluşturma komut satırı denetimi gerçek değerleri
   cihazın dışına (merkezi log, EDR, SIEM) çıkarıyorsa: **DUR**. Bu runbook
   güvenlik kontrollerinin kapatılmasını **önermez**; uygun güvenli ortam
   yoksa pilot bu cihazda **yapılmaz**. Ölçüm (yalnız anahtar varlığı;
   standart Windows davranışından gelir, repo kaynağından değil; Temel
   L457–L461 birebir):

```powershell
foreach ($k in 'ScriptBlockLogging', 'Transcription', 'ModuleLogging') { foreach ($hive in 'HKLM:', 'HKCU:') { $p = "$hive\SOFTWARE\Policies\Microsoft\Windows\PowerShell\$k"; if (Test-Path -LiteralPath $p) { "PS_POLICY_KEY_PRESENT=$hive/$k" } else { "PS_POLICY_KEY_ABSENT=$hive/$k" } } }
$audit = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit'
if (Test-Path -LiteralPath $audit) { "CMDLINE_AUDIT_KEY=PRESENT" } else { "CMDLINE_AUDIT_KEY=ABSENT" }
```

   `PRESENT` çıkan her anahtar için, cihaz sahibi bu kaydın cihaz dışına
   aktarılmadığını yazılı olarak beyan etmedikçe **DUR**. Bu ölçüm üçüncü
   taraf güvenlik yazılımının (antivirüs, EDR) kendi telemetrisini
   **göremez**; o sınır §32'de açık kalır. B yolunda belge içeriği süreç
   argümanı olarak **geçmez** (§1.5); komut satırı denetimi opak
   kimlikleri, tamsayıları, hash'leri, sabit literal'leri, opak
   `<attestation-ref>`'i ve Windows kullanıcı profil adını taşıyabilen
   **mutlak yolları** görebilir (§1.5, §32/21).
10. **Cihaz ve disk şifrelemesi (bağlayıcı; F4 seçenek (1)'in dayanağı).**
    Form **E1** "Evet" olmalıdır (§1.6/4, §23). Operatör, **yürütme günü**
    zincir adım 4'te (intake'ten önce) ve **her silme gününde** silmeden
    hemen önce (§28.3, §28.6) tam disk şifrelemesini ve harici disk
    kuralını doğrular. Her doğrulama aşağıdaki kapsamın **tamamını**
    kapsar; silme günü doğrulaması da daraltılmaz.

    - **Kapsam.** Doğrulama, gerçek verinin dokunabileceği **her** yerel
      sürücüyü kapsar: `<repo-root>`, `<external-root>`, Temp kökü,
      indirme dizini ve Form E4 aracının ara dosyalarını yazdığı sürücü;
      ayrıca bağlı kalan her harici sürücü (aşağıdaki harici disk kuralı).
      Operatör bu sürücülerin **harf listesini** (yalnız harfler, ör. `C:`)
      evidence'a yazar. Listelenemeyen veya şifreli olduğu aşağıdaki üç
      yoldan biriyle **sürücü bazında** gösterilemeyen tek bir sürücü:
      **DUR** (Y5).
    - **Bu cihazın durumu.** Cihaz bu runbook yazılırken Windows 10
      **Home**'dur ve BitLocker yönetim arayüzü yoktur. Kullanıcı cihazı
      Windows 10 Pro'ya yükseltip BitLocker kullanmayı planlamaktadır
      (henüz yapılmadı). Hangi yolun bulunduğu §1.6/3 provasında boolean
      olarak kaydedilir (O-f). Şifreleme yalnız şu **üç** yoldan biriyle
      doğrulanır; başka bir yol bu runbook'ta tanımlı değildir:
      1. **Windows "Cihaz şifrelemesi"** (yalnız destekleyen donanımda):
         Ayarlar → Güncelleştirme ve Güvenlik → **Cihaz şifrelemesi** sayfası
         "Cihaz şifrelemesi açık" gösterir. Bu sayfa yoksa cihaz bu özelliği
         desteklemiyordur ve bu yol kullanılamaz. **Sınır (N-L4):** sayfa
         sürücü bazında durum göstermez; bu yol yalnız **sistem sürücüsünü**
         kanıtlar. Kapsam listesinde sistem sürücüsü dışında bir sürücü
         varsa o sürücü yol 2 veya 3 ile ayrıca gösterilmedikçe **DUR**.
         Sayfa "Microsoft hesabıyla oturum açın", "etkinleştirme bekliyor"
         veya benzeri tamamlanmamış bir durum gösteriyorsa: **DUR**.
      2. **BitLocker** (yalnız Windows 10 Pro veya üstünde; Pro yükseltmesi
         yapılmadan bu yol yoktur): Denetim Masası → Sistem ve Güvenlik →
         **BitLocker Sürücü Şifrelemesi** ekranında kapsamdaki **her**
         sürücü için "BitLocker açık" görünür ve şifreleme tamamlanmıştır.
         "BitLocker şifreleniyor", "BitLocker askıya alındı", "BitLocker
         kapalı" veya belirsiz bir durum gösteren tek bir sürücü: **DUR**.
         BitLocker bu runbook'ta bir **kullanıcının kabul ettiği araç**
         sayılır: kullanıcının kabulü zincir adım 4'te alınır ve evidence'a
         yazılır (aşağıda "Kayıt").
      3. **Üçüncü taraf yerel bir tam disk şifreleme aracı** (ör. sistem
         şifrelemesi yapan bir araç): adı ve sürümü evidence'a yazılır ve
         kullanıcı tarafından zincir adım 4'te açıkça kabul edilir. Aracın
         kendi arayüzü kapsamdaki **her** sürücünün "tamamen şifrelenmiş"
         olduğunu gösterir; şifreleme işleminin hâlâ sürüyor olması
         "şifreli" sayılmaz.
    - **Avukatın E1'e yazdığı koşullar (N-L2).** E1'e (veya formun başka bir
      yerine) şifreleme yöntemi veya aracı hakkında yazılmış her araç adı ya
      da koşul §6.1 gereği bir **ek koşuldur**: runbook'a işlenip yeniden
      incelenene kadar **DUR**. Operatör ve kullanıcı bu koşulu yorumlamaz
      ve sahada uygulamaz.
    - **Harici disk kuralı (bağlayıcı).** Bu cihazda bir harici USB disk
      bulunur (yazım anında `D:`). Bu disk ve — E2 taşıyıcısı hariç — bağlı
      her başka harici veya çıkarılabilir sürücü, **içerik penceresi boyunca**
      (§4.3) ya (a) yukarıdaki üç yoldan biriyle **şifreli** olduğu
      gösterilmiş ve kapsam listesine yazılmıştır, ya da (b) cihazdan
      **fiziksel olarak çıkarılmıştır** ve pencere kapanana kadar yeniden
      takılmaz. Zincir adım 4'te ve her silme gününde evidence'a
      `EXTERNAL_DISK_ENCRYPTED=True/False` ve
      `EXTERNAL_DISK_REMOVED=True/False` yazılır (birden fazla harici
      sürücü varsa her biri için sürücü harfiyle ayrı çift); her çiftte
      **tam biri** `True` olmalıdır. İkisi de `False` ise (veya durum okunamıyorsa): **DUR**
      (Y5). (b) seçildiyse disk pencere içinde yeniden takılırsa: **DUR**
      (H40). E2 taşıyıcısının kuralı §6.4'tedir.
    - **Kayıt.** Evidence'a yalnız şunlar yazılır:
      `DISK_ENCRYPTION_METHOD=WINDOWS_DEVICE_ENCRYPTION`,
      `DISK_ENCRYPTION_METHOD=BITLOCKER` veya
      `DISK_ENCRYPTION_METHOD=THIRD_PARTY_FDE` (sürücü bazında farklı yol
      kullanıldıysa her sürücü için ayrı satır; üçüncü yolda aracın adı ve
      sürümü), sürücü harfleri, ölçüm zamanı, harici disk boolean'ları ve
      `FULL_DISK_ENCRYPTION_CONFIRMED=True`. Yol 2 veya 3 kullanıldıysa
      ayrıca `ENCRYPTION_TOOL_USER_ACCEPTED=True` ve kullanıcı onayının
      (`REAL_ACTION_APPROVED`) zamanı yazılır (N-L3). Ekran görüntüsü
      alınmaz.
    - **Yapılamayan her durum DUR'dur:** üç yoldan hiçbiri yoksa, arayüz
      "kapalı", "askıya alındı", "şifreleniyor" veya belirsiz bir durum
      gösteriyorsa, yol 2/3'te kullanıcı kabulü yoksa, harici disk kuralı
      sağlanmıyorsa ya da operatör durumu doğrulayamıyorsa: **DUR — gerçek
      belge teslim alınmaz** (adım 4'te) veya **silme yapılmaz** (silme
      günü; veri §28.1/6 gereği korunur ve avukata bildirilir).
    - Bu runbook şifreleme durumunu okuyan bir **komut** tanımlamaz
      (`manage-bde` yönetici yetkisi ister; Home sürümünde BitLocker
      yönetimi yoktur ve bu runbook yönetici oturumu açmaz); doğrulama
      operatörün ekran okumasına dayanır (§32/12).
11. Bu sınırın ihlali veya ihlal şüphesi **DUR**'dur (H40) ve Form **E3**'te
    yazılı bildirim yoluyla avukata bildirilir; kişisel veri içermeyen bir
    olay kaydı açılır.

### 4.3 İçerik oturumunun açılması ve kanal kapısı (bağlayıcı)

Kaynak: Temel L473–L613. **Sapmalar:** içerik penceresinin bitiş adımı
zincir adım 26–27'ye bağlandı; handler sınıflandırmasındaki maskeleme
cümlesi çıkarıldı. Komut blokları **birebirdir**.

**İçerik penceresi**, gerçek belgenin teslim alındığı andan (zincir adım 5)
gerçek verinin ve repo dışı geçici kopyaların silinmesinin veya
arşivlenmesinin tamamlandığı ana (zincir adım 26–27) kadar süren aralıktır.
Veri yeni bir yazılı karar beklenirken (§28.1/6) veya doğrulanmış arşivden
sonra yerel çalışma kopyası korunurken (§28.1/5) pencere **açık kalır**.

Runbook'un yazılması, incelenmesi ve sentetik provası içerik penceresinin
**dışında** ve insan-only içerik oturumundan **ayrı** tutulur; bu işler için
kullanılan hiçbir oturum içerik oturumu olarak yeniden kullanılmaz.

**(a) Kanal kapısı.** Gerçek belge teslim alınmadan önce ve içerik penceresi
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
girip girmediği **sınıflandırılamıyorsa**: **DUR — belge teslim alınmaz.**

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

Kayıt yalnız boolean ve süreç adı taşır. `AI_CONTENT_CHANNELS_CLOSED=True`
yalnız altı satırın hepsi `True` ise yazılır. Bir sınıf ölçülemiyor veya
doğrulanamıyorsa: **DUR.** Kapı, içerik taşıyan her yeni oturumun başında
yeniden ölçülür.

**(b) İçerik oturumunun açılması.** İçerik taşıyan her PowerShell oturumu
`powershell.exe -NoProfile` komutuyla (bayrak kısaltılmadan) açılır. Oturumun
ilk komutları (Temel L546–L561 birebir):

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
Başka her çıktı veya doğrulanamayan bir durum: **DUR** (H53).

**Handler sınıflandırması (bağlayıcı).** Yalnız varsayılan bir geçmiş
handler'ının **varlığı** DUR sebebi **değildir**. Bağlayıcı güvenlik sonucu
şu birleşimden gelir: oturum `-NoProfile` ile açılmıştır; aktif transcript
yoktur; `HistorySaveStyle=SaveNothing` zorunludur; gerçek değerler komut
satırına literal olarak yazılmaz. `UNKNOWN`, handler'ın PSReadLine
varsayılanıyla aynı nesne olduğunun gösterilemediği anlamına gelir ve
**DUR**'dur. Provada temiz bir `-NoProfile` oturumu `UNKNOWN` verirse runbook
**düzeltilir ve yeniden incelenir**.

- Aktif transcript bulunursa durdurulur; oturum **DUR** ile kapatılır ve
  içerik işlenmez.
- `SaveNothing` yalnız geçmiş dosyasını kapatır; transcript kontrolünün
  yerine geçmez.

**(c) Geçmiş dosyasının değişmezliği (yalnız sentetik prova).** Temel
L596–L613 birebir:

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

Kaynak: Temel L617–L644. **Sapmalar:** "ikinci model gönderimi" maddesi
"hiçbir model çağrısı" ile değiştirildi; `manual-fact` ve reconciliation
eklendi.

1. `CLAUDE.md` §3'teki mimari prensipler aynen geçerlidir; özellikle 1, 4
   (confidence ≠ verification: manuel fact'in `confidence = 1.0` değeri
   model güveni değildir ve doğrulama değildir —
   `src/manual_fact_entry_engine.py:104-107, 478-480`), 5 (approval ≠
   verification), 8 (unverified anchor üzerinden kesin deadline
   hesaplanmaz), 9, 15 ve 16.
2. `CLAUDE.md` §13.1.2–§13.1.5 operasyon kuralları aynen geçerlidir: case
   dizini kontrolü için düz `git status` yetmez; `git clean -fdx` ve
   `git stash --all` **yasaktır**; `data/cases/case_0001` fixture'ına gerçek
   veri konmaz ve o dizin bu pilotta okunmaz, değiştirilmez; resmî test
   kapıları pilot sürerken koşulmaz.
3. Operatör hukuki karar vermez; her hukuki giriş avukatın yazılı kararıdır.
   Operatör kendi girdiği tebliğ tarihini **doğrulamaz** (§4.1).
4. Gerçek içerik §4.2'deki güven sınırının dışına çıkmaz; Git'e, loglara,
   hata mesajlarına veya evidence dizinine **yazılmaz**.
5. **Otomatik retry yoktur.** Başarısız bir apply yeniden denenmez; tek
   istisna §14.6'daki, ayrı onaylı ve önce reconciliation gerektiren
   `--attempt` yoludur. Düzeltici SQL çalıştırılmaz. Hiçbir model çağrısı
   yapılmaz.
6. Her başarısızlık **DUR**'dur ve §25.2'deki güvenli DUR/abort yolunu
   çağırır. Preview aşamasındaki girdi reddi için §14.5'teki "girdi düzeltme
   döngüsü" de bir DUR'dur ve yalnız avukatın yazılı kararıyla sürdürülür.
7. Hiçbir force/bypass bayrağı yoktur; `manual-fact` alt komutu
   `--with-agent`, `--allow-network`, `--mask-term`, `--text-path` ve
   `--model` bayraklarını **tanımaz** (`ui/cli_mutate.py:525-528`;
   argparse kendi çıkış `2`'sini verir).
8. **Preview ve apply ayrı kod bloklarıdır.** Her mutasyonda sıra: preview
   bloğu → preview postcondition'ları ve gereken avukat kararı ile kullanıcı
   onayı (ayrı kapı) → apply bloğu. Apply bloğu, preview'ın bastığı hash veya
   digest yerine konmadan veya biçimi 64 küçük harfli onaltılık değilse CLI'ı
   **hiç çağırmaz**; CLI ayrıca değeri canlı durumla karşılaştırır ve
   uyuşmazlıkta fail-closed reddeder. Preview'ın stdout'a bastığı "Uygulamak
   için:" / "Sonraki adım:" satırları **kopyalanıp çalıştırılmaz**
   (`ui/cli_mutate.py:1887-1889, 1903-1905`); yalnız bu runbook'taki apply
   blokları kullanılır.

---

## 6. Avukat formu kapıları (bağlayıcı)

Bu bölüm temel runbook'un §6 (hukuki onay, P1) ve §7 (rıza, P2) yerine
geçer. Temel §6.1'deki sekiz kalemden sağlayıcı/DPA (2), yurt dışı aktarım
(3) ve kamu kurumu adının maskelenmeden aktarılması (7) B yolunda **sorulmaz**:
veri yurt dışına çıkmaz ve model sağlayıcısı yoktur (form, paragraf
"Bu yolda sorulmayan konular"). Kalan kalemler formun A–F bölümlerine
dağıtılmıştır. Kullanılan form **sürüm 3**'tür (§0); soru kodları v3'e
göredir.

### 6.1 Genel kural

- Form v3 **iki ayrı imzayla** alınır: A–F bölümleri I bölümüyle (I2–I4),
  G bölümü kendi G10/G11 alanıyla (§8). A–F + I, gerçek belge teslim
  alınmadan **önce**; G, dosya seçildiğinde ve yine teslimden **önce**
  alınır. İmza biçimi, bağlayıcı sürüm ve hash kuralları §6.6'dadır.
- Formdaki her soru için kural aynıdır: **cevap yoksa (boş), kutu
  işaretsizse veya cevap aşağıdaki tabloda "DUR" olarak gösterilen
  seçenekse: DUR — gerçek belge teslim alınmaz.** Operatör ve kullanıcı
  cevabı **varsaymaz**, tamamlamaz veya yorumlamaz.
- Formun "Not" kısımlarına yazılan ve bir kapının anlamını değiştiren her
  ek koşul (ör. A1 "Evet, şu ek koşullarla") bu runbook'ta karşılığı
  olmadığı sürece **DUR**'dur: runbook değiştirilir, yeniden incelenir ve
  ancak ondan sonra yürütülür. Ek koşul sahada doğaçlama uygulanmaz.
- Formda olmayan, kodla kapanmayan sorular (B3'teki işleme sebebi gibi)
  avukatın yazılı cevabıdır; operatör onların doğruluğunu
  değerlendirmez, yalnız **varlığını** denetler.

### 6.2 A — Kapsam

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| A1 | "Evet" | Boş; "Hayır"; "Evet, şu ek koşullarla" (koşul runbook'a işlenip yeniden incelenene kadar) |
| A2 | "Kabul" | Boş; "Şu değişiklikle" (değişiklik runbook'a işlenene kadar) |
| A3 | "Aynen geçerli" | Boş; "Şu değişikliklerle" (değişiklik runbook'a işlenene kadar) |

### 6.3 B — Roller ve hukuki dayanak

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| B1 | Bir kutu işaretli ("Diğer" ise açıklama dolu) | Boş |
| B2 | Bir kutu işaretli ("Diğer" ise açıklama dolu) | Boş |
| B3 | Yazılı işleme sebebi | Boş |
| B4 | "Evet, ayrı kişiler" — veya — "Hayır, aynı kişi; iki kişili kontrolün kalkmasını kabul ediyorum" | Boş; §4.1 iki kişi kuralı |
| B5 | "Hayır" — veya — "Evet" **ve** imzalı gizlilik taahhüdü eki alınmış | Boş; "Evet" iken ek yok |

### 6.4 E — Cihaz ve güvenlik

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| E1 | "Evet" **ve** §4.2/10 doğrulaması (`FULL_DISK_ENCRYPTION_CONFIRMED=True`) | Boş; "Evet" iken doğrulanamadı; **"Hayır"** — F4 seçenek (1) disk şifrelemesine dayanır ve bu runbook'ta başka bir silme yöntemi tanımlı değildir (§1.6/4, §23); E1'e yazılmış araç adı veya koşul (§6.1, §4.2/10) |
| E2 | "Elden / şifreli USB", "Şifreli dosya aktarımı" veya açıklamalı "Diğer" **ve** aşağıdaki taşıyıcı kontrolü | Boş; açık e-posta/mesajlaşma uygulaması (form E2 notu); taşıyıcı kontrolü geçmedi |
| E3 | "Kabul" **ve** bildirim yolu yazılı | Boş; yol yazılmamış |
| E4 | Araç ve sürüm yazılı **ve** "Bu aracı onaylıyorum" işaretli | Boş; onaysız; bulut tabanlı araç |

E2 ile teslim alınan taşıyıcı (USB, aktarım dosyası) ve E4 aracının ara
dosyaları **repo dışı geçici kopyadır**; Form F1 süresine tabidir (§23,
§28.6).

**E2 taşıyıcı kontrolü (bağlayıcı; N-L5).** Taşıyıcı, belge cihaza
aktarılmadan **önce** (zincir adım 5'in başında) kontrol edilir ve
evidence'a yalnız şu satırlar yazılır: `E2_CARRIER_KIND=USB`,
`=ENCRYPTED_TRANSFER` veya `=PAPER` ve `E2_CARRIER_ENCRYPTED=True/False`.

- **USB:** taşıyıcı donanım veya yazılım şifrelidir; operatör, içeriğin
  ancak parola/kilit açma adımından **sonra** göründüğünü ekranda
  gözlemler. Şifresiz veya durumu okunamayan bir USB:
  `E2_CARRIER_ENCRYPTED=False` → **DUR — belge cihaza aktarılmaz**;
  avukata bildirilir ve kanal avukatın yazılı kararıyla yeniden belirlenir.
- **Şifreli dosya aktarımı:** aktarım dosyası parolalı/şifrelidir ve
  çözülmüş çıktı yalnız §4.2/10 kapsamındaki şifreli bir sürücüye yazılır.
  Şifresiz bir aktarım dosyası: **DUR**.
- **Kâğıt (elden):** dijital taşıyıcı yoktur; tarama yalnız çıktısını
  doğrudan §4.2/10 kapsamındaki şifreli bir sürücüye yazan yerel bir
  tarayıcıyla yapılır; ağ veya bulut tarama kullanılmaz (§4.2/2). Bu
  sağlanamıyorsa: **DUR**.

Bu kontrol, §28.6/2'deki "şifresiz ortamda kalan kopya" durumunun zincir
adım 27'ye kadar fark edilmemesini önler.

### 6.5 F — Saklama, silme ve pilot sonu

Kapı tablosu §23'tedir; uygulaması §28'dedir. F2 boşsa, F2 "Şifreli
arşivlensin" iken F3'ün beş unsurundan biri boşsa veya F4 seçenek (1)
değilse: **DUR — gerçek belge teslim alınmaz** (H4, Y6).

### 6.6 İmza biçimi, bağlayıcı sürüm, saklama ve hash kaydı

Kaynak: form v3, "I. Onay" ve "G." bölüm notları. YENİ.

1. **İmza biçimi.** Geçerli imza yalnız şunlardan biridir: (a) yazdırılıp
   ıslak imzayla imzalanmış ve **taranmış PDF**; (b) **e-imza** ile
   imzalanmış dosya. Word dosyasına yazılmış bir isim, yazıyla "imza" veya
   imza resmi yapıştırılmış bir `.docx` imza **sayılmaz**: **DUR** (Y1, Y7).
   Operatör imzanın varlığını ve biçimini denetler; imzanın kime ait
   olduğunu veya e-imzanın kriptografik geçerliliğini **doğrulamaz** (§32).
2. **İki ayrı imzalı birim.** (i) **A–F + I** (form v3 "I. Onay (A–F
   bölümleri için)"), (ii) **G bölümü** (G10 ad/tarih, G11 imza). Her biri
   ayrı bir dosya olabilir; aynı dosyada ise her iki imza da bulunmalıdır.
3. **Bağlayıcı sürüm.** Her birim için **en son imzalı sürüm** geçerlidir
   (form v3, I bölümü notu). Yeni bir imzalı sürüm geldiğinde önceki sürümün
   hash kaydı silinmez; yeni sürümün hash'i ayrı satır olarak eklenir ve
   bağlayıcı olarak işaretlenir. A–F yeni sürümü bir kapının sonucunu
   değiştiriyorsa ilgili kapı yeniden değerlendirilir; zincir o kapıdan
   sonraki bir adımdaysa: **DUR**, kullanıcı kararı.
4. **Tarih sırası.** G10 tarihi, bağlayıcı A–F sürümünün I3 tarihinden
   önce olamaz. Operatör iki tarihi karşılaştırır; ek olarak avukatın G
   bölümünü **bağlayıcı A–F sürümünü ve belgeyi görerek** doldurduğuna dair
   yazılı beyanı alınır (G10'un yanındaki not veya ayrı yazılı not). Sıra
   tutmuyorsa veya beyan yoksa: **DUR** (Y7). Tarihlerin gerçekliği
   mekanik olarak doğrulanamaz (§32).
5. **Ekler (I1).** I1 "Ek yok" işaretliyse, B5 "Evet", C1 "Hazırlandı (ek
   olarak)", C2 "Gerekli (ek olarak)" veya D3 "Hayır, ayrı imzalı ek
   vereceğim" cevaplarından hiçbiri bulunmamalıdır; aksi hâlde çelişkidir:
   **DUR** (Y1). I1 "Ekler" işaretliyse her ek ayrı dosya olarak alınır.
6. **Saklama.** Form, ekler ve G bölümü **repo dışında**, avukatın
   kontrolünde saklanır (form, "Nasıl doldurulur?" bölümü).
7. **Hash kaydı (zamanlama ve satır biçimi bağlayıcıdır; O-c).**
   - **Satır biçimi.** Her ölçülen dosya bir satırdır:
     `FORM_HASH unit=<birim> seq=<n> sha256=<64-küçük-hex>`. `<birim>`
     şunlardan biridir: `AF` (yalnız A–F + I), `G` (yalnız G bölümü),
     `AFG` (A–F + I ve G aynı dosyada), `ATT<k>` (k'inci ek; `ATT1`,
     `ATT2` …). `seq` her birimde `1`'den başlar ve her yeni imzalı sürümde
     bir artar. Önceki satırlar silinmez.
   - **Bağlayıcılık satırı.** Hangi kaydın bağlayıcı olduğu ayrı satırla
     yazılır: `FORM_BINDING part=AF unit=<AF|AFG> seq=<n>` ve
     `FORM_BINDING part=G unit=<G|AFG> seq=<n>`; her ek için
     `FORM_BINDING part=ATT<k> unit=ATT<k> seq=<n>`. Her `part` için en son
     yazılan `FORM_BINDING` satırı geçerlidir.
   - **Zincir adım 2, teslimden önce:** A–F + I dosyası
     `FORM_HASH unit=AF seq=1 …` ve `FORM_BINDING part=AF unit=AF seq=1`;
     her ek kendi `ATT<k>` satırlarıyla yazılır.
   - **Zincir adım 3, teslimden önce:** G ayrı dosyadaysa
     `FORM_HASH unit=G seq=1 …` ve `FORM_BINDING part=G unit=G seq=1`.
     G, A–F ile **aynı dosyaya** eklenmişse (ör. iki imzayı taşıyan yeni
     taranmış PDF) bu dosya `FORM_HASH unit=AFG seq=1 …` olarak yazılır ve
     **iki** bağlayıcılık satırı birlikte eklenir:
     `FORM_BINDING part=AF unit=AFG seq=1` ve
     `FORM_BINDING part=G unit=AFG seq=1`. Önceki `unit=AF` satırı silinmez
     ama artık bağlayıcı değildir. Bu geçiş A–F'nin yeni bir sürümü
     **sayılmaz** yalnız avukat, AFG dosyasındaki A–F + I sayfalarının
     bağlayıcı AF sürümüyle aynı olduğunu madde 4'teki yazılı beyanında
     belirtirse; beyan yoksa A–F yeniden imzalanmış sayılır ve madde 3–4
     uygulanır.
   - **Yeniden ölçüm:** her `part` için, o anda geçerli `FORM_BINDING`
     satırının gösterdiği dosya (a) belge teslimi anında (zincir adım 5'in
     başında), (b) zincir adım 26'daki her silme veya arşiv onayından önce ve
     (c) kapanışta (zincir adım 29) yeniden ölçülür ve gösterilen
     `FORM_HASH` satırıyla birebir karşılaştırılır. Sonuç evidence'a
     `FORM_HASH_RECHECK part=<part> match=True/False` olarak yazılır. Fark
     varsa ve yeni sürüm madde 3'e göre kayda geçirilmemişse: **DUR** (H16).
   - Hash ölçümü dosya içeriğini basmaz; dosya repo içine veya evidence'a
     kopyalanmaz.
8. Evidence'a ayrıca kişisel veri içermeyen kısa bir kapsam özeti yazılır
   (ör. "A1 evet, B4 ayrı kişiler, D3 form yeterli, E1 evet, F4 (1), F2
   silme, F1 72 saat, G9 evet").
9. §0'daki **boş şablonun** hash'i bu kayıtların yerine **geçmez**; yalnız
   kullanılan şablon sürümünü tanımlar.

---

## 7. Müvekkilin bilgilendirilmesi (Form C)

Temel §7'nin (dış aktarım için yazılı rıza, P2) yerine geçer: veri yurt
dışına ve bir model sağlayıcısına gitmediği için Temel §7.1/2'deki aktarım
kategorileri bu yolda **yoktur**. Avukatın DRAFT-4 6.3 cevabı aydınlatmayı
zorunlu, açık rızayı ise yalnız gerçekten rızaya dayanan bir faaliyet
varsa gerekli sayar (form C1–C2 notları).

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| C1 | "Hazırlandı (ek olarak)" — veya — "Pilot öncesi hazırlanacak" **ve** metin gerçek belge teslim alınmadan önce hazırlanıp müvekkile verilmiş | Boş; metin teslimden önce verilmemiş |
| C2 | "Gerekli değil" **ve** gerekçe yazılı — veya — "Gerekli (ek olarak)" **ve** imzalı rıza alınmış | Boş; gerekçesiz "Gerekli değil"; "Gerekli" iken rıza yok |
| C3 | "Gerekli değil" — veya — "Gerekli" **ve** bilgilendirme teslimden önce yapılmış | Boş; "Gerekli" iken bilgilendirme yok |

- Aydınlatma metni, rıza ve bilgilendirme kayıtları **repo dışında**
  saklanır; evidence'a yalnız SHA-256'ları ve kapsam özeti girer.
- Bu kapılardan biri sağlanmazsa: **DUR — gerçek belge teslim alınmaz**
  (H3).

---

## 8. Dosya seçimi (Form G) ve tek dava / tek tebliğ kabul kriterleri

Kaynak: Temel L746–L780. **Sapmalar:** sekiz kalem formun G1–G8
sorularına bağlandı; 60.000 karakter sınırının kaynağı düzeltildi; form
v3'ün G9 (tarih biçimi) sorusu ve G10/G11 ayrı imzası eklendi.

Bu eleme **gerçek veri teslim alınmadan önce**, avukatın belgeye bakarak
formun G bölümünü doldurup **ayrıca imzalamasıyla** yapılır (§6.6). Form:
"Sorulardan birine 'Hayır' denirse dosya bu pilota alınmaz; başka bir dosya
seçilir."

| Soru | İçerik | Kabul | Temel karşılık |
|---|---|---|---|
| G0 | Dosyanın kısa kodu (isim yok) | Dolu; kişisel veri yok (§10.3) | — |
| G1 | Tek tebliğ, tek dava açma süresi | "Evet" | Temel §8/1 |
| G2 | Tebliğ bilgisi tek belgede | "Evet" | Temel §8/2 |
| G3 | Belge D bölümündeki "hiç alınmaz" sınıflarından hiçbirine girmiyor | "Evet" | Temel §8/3 |
| G4 | Belge türü vergi ceza ihbarnamesi | "Evet" | Temel §8/4 |
| G5 | Süre ve kaydırmalar 2024–2035 içinde | "Evet" | Temel §8/5 |
| G6 | Sekiz event-specific olaydan hiçbiri yok (ön değerlendirme) | "Evet" | Temel §8/6 |
| G7 | Belge metne aktarılabiliyor, metin ≤ 60.000 karakter | "Evet" | Temel §8/7 |
| G8 | Her uyuşmazlık kaleminin vergi türü | Her kalem için dolu | Temel §8/8 |
| G9 | Tebliğ tarihi belgede rakamla `GG.AA.YYYY` veya `GG/AA/YYYY` biçiminde yazılı | "Evet" | — (YENİ; M-08) |
| G10 | G bölümü için ad, soyad, unvan ve tarih | Dolu; tarih §6.6/4 sırasına uygun | — |
| G11 | G bölümü için imza | §6.6/1 biçiminde imza | — |

- G4 kod düzeyinde de zorunludur: belge türü `vergi_ceza_ihbarnamesi`
  değilse `manual-fact` reddeder (`src/manual_fact_entry_engine.py:353-356`,
  kural M-05) ve tek aktif deadline kuralı da yalnız bu türe uygulanır
  (`data/deadline_rules/deadline_rules.json`, `applicability.document_types`).
- G6 ön değerlendirmedir; §17.1'deki yazılı stopping-event beyanının yerine
  **geçmez**.
- G7: 60.000 karakter sınırı temel runbook'ta fact extraction motorunun
  sınırıydı; manuel motor bu sınırı **uygulamaz**. Bu runbook sınırı avukatın
  formdaki kriteri olarak korur ve §11.2/4'te ölçer.
- G8 her kalem için §11.3 (f) sözlüğünde **birebir** bulunan bir terimle
  ifade edilebilmelidir; sözlükte karşılığı olmayan bir vergi türü veya dahil
  ve istisna terimlerinin karışması varsa dosya kabul edilmez (Temel §8/8).
- G9 kod düzeyinde de zorunludur: `manual-fact` alıntıdaki tarihi yalnız
  iki haneli gün, iki haneli ay, dört haneli yıl ve aynı ayraçla (`.` veya
  `/`) tanır (`src/manual_fact_entry_engine.py:116-117, 406-430`, kural
  M-08). "16 Mart 2026" veya "16.3.2026" gibi yazılmış bir tarih
  **tanınmaz** ve metin dosyası intake'ten sonra düzeltilemez (§11.3 b);
  bu yüzden kapı teslimden önce sorulur. G9 avukatın beyanıdır;
  çıkarılan metinde bu biçimin bulunduğu ayrıca §11.3 (b)'deki ön kontrolle
  mekanik olarak ölçülür.

Bir kalem sağlanmazsa, G10/G11 eksikse veya avukat tereddüt ederse:
**DUR — gerçek belge teslim alınmaz** (H42, Y7). İkinci bir tebliğ, ikinci bir deadline ihtimali veya
aynı belgede birden fazla ihbarname/tebliğ zincirin **herhangi bir**
adımında fark edilirse de **DUR** geçerlidir (H5).

---

## 9. Sisteme hiç alınmayacak belgeler (Form D)

Kaynak: Temel L784–L801. **Sapmalar:** "imzalı hard-block eki" şartı formun
D tablosu ve D3 sorusuyla değiştirildi.

### 9.1 Kaynak durumu

Dokuz sınıfın listesi bu repository'de **bulunmaz**; bu runbook sınıfları
tahmin etmez. Liste avukatın DRAFT-4 6.4 cevabından ve Bölüm 7
yorumlarından gelir ve formun D tablosunda avukatın kararına sunulur.

### 9.2 Kapı

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| D tablosu 1–9 | **Her** satırda tam bir kutu işaretli ("Hiç alınmaz" veya "Avukat kararıyla alınabilir / geçerli değil") | Herhangi bir satır işaretsiz veya iki kutu birden işaretli |
| D2 | "Yok" — veya — "Var" **ve** eklenen türler yazılı | Boş; "Var" iken tür yazılmamış |
| D3 | "Evet, bu formun imzası yeterli" — veya — "Hayır, ayrı imzalı ek vereceğim" **ve** ek alınmış | Boş; "Hayır" iken ek yok |

### 9.3 Kural (fail-closed)

- D tablosunda "Hiç alınmaz" işaretli bir sınıfa veya D2'de eklenen bir
  türe giren belge **teslim alınmaz** ve operatör bilgisayarına **hiç
  girmez**.
- Her aday belge, bu kararlara karşı **avukat tarafından** yazılı olarak
  kontrol edilir (G3). Operatör sınıflandırma yapmaz.
- Şüphe = blok (H28).
- Formun ve varsa ayrı ekin SHA-256'sı evidence'a yazılır; içeriği yazılmaz.

---

## 10. Veri minimizasyonu ve saklama

### 10.1 Repo içine giren gerçek veri (yalnız ignored case dizini)

Kaynak: Temel L807–L819. **Sapmalar:** manuel girdi dosyası eklendi.

Yalnız `data/cases/<case-id>/` altında, `.gitignore`'un kök-bağlı
`/data/cases/` kuralıyla ignored olarak:

- `case.json`,
- `documents/<document-id>/document.json`,
- `documents/<document-id>/` altında orijinal belge baytları,
- `documents/<document-id>/extracted/<document-id>.txt`,
- `documents/<document-id>/manual_input/manual_facts.input.json` (§14.2),
- zincirin ürettiği pending/canonical/review/history/audit dosyaları.

Başka hiçbir belge bu dizine konmaz.

### 10.2 Repo dışında kalanlar

Kaynak: Temel L821–L846. **Sapmalar:** `<external-root>` iki çocuklu;
probe/inference evidence dizinleri ve `<restricted-dir>` içindeki maskeleme
ve engel dosyaları çıkarıldı.

- Avukat formu ve ekleri, avukatın yazılı kararları ve kör bağımsız
  hesabı: repo dışında, avukatın kontrolünde.
- **`<external-root>`** — repo dışındaki, yalnız bu pilot için ayrılmış
  kök dizin. Bulut senkronizasyonlu bir klasörde **değildir**, sürücü kökü
  **değildir**, repo ağacının içinde veya repo kökünün atası **değildir**.
  Doğrudan altında **yalnız** `<evidence-dir>` ve `<restricted-dir>`
  bulunur (§13.8).
- **`<restricted-dir>`** — dava-türevi içerik dizini. Erişimi avukat ve
  operatörle sınırlıdır ve §28'deki veri akıbeti kararına **tabidir**. Bu
  pilotta **yalnız** deadline raporunu (§19) taşır. İzinli dosya adı
  intake'ten önce sabitlenir ve envanter mekanik olarak denetlenir (§10.5).
- **`<evidence-dir>`**: **yalnız metadata** (§26). Gerçek tarih, sayfa
  numarası, alıntı, rapor metni veya herhangi bir gerçek içerik bu dizine
  girmez.
- **`<archive-dir>`** — yalnız eksiksiz bir şifreli arşiv kararı varsa
  kullanılır; `<external-root>`'un dışındadır ve kendi kapısından geçer
  (§28.5).
- Gerçek belge baytlarının veya metninin Temp, indirme dizini veya evidence
  dizininde **ikinci bir düz kopyası alınmaz**. E2 taşıyıcısı ve E4 aracının
  ara dosyaları kaçınılmaz geçici kopyalardır; Form F1 süresine tabidir
  (§28.6).

### 10.3 Opak kimlikler (bağlayıcı)

Kaynak: Temel L848–L875. **Sapmalar:** maskeleme katmanına ait iki madde
çıkarıldı; manuel fact kimlik biçimi eklendi.

Veritabanı journal, mutation resource, assignment ve security-event satırları
**silinmez** (§28.4) ve şu değerleri kalıcı olarak taşır: `case:<case-id>`
resource anahtarı, `fact.<document-id>.pending`
(`ui/services/manual_fact_mutation_facade.py:102-103`) ve
`fact.<document-id>.<fact-id>.verification` gibi target ref'ler ve hash'ler.
Bu nedenle:

- `<case-id>`, `<document-id>`, `<fact-id>`, `file.file_name`,
  `<attestation-ref>` ve Form G0 kısa kodu **hiçbir kişisel veri, taraf
  adı, kimlik/vergi numarası veya dava numarası taşımaz**.
- `document.json` içindeki `title` de kişisel veri taşımaz; jenerik bir
  başlık kullanılır.
- `<case-id>` biçimi iki kaynağın kesişimidir: şema `^[a-z0-9_-]+$` ve en az
  3 karakter (`data/case.schema.json`); yetkilendirme `^[A-Za-z0-9_-]{1,64}$`
  (`ui/services/authz.py`, `_CASE_ID_PATTERN`). Yani: küçük harf, rakam, `_`
  ve `-`; 3–64 karakter. `<case-id>` hiçbir durumda `case_0001` olamaz.
- `<document-id>` manuel girdi şemasında da `^[a-z0-9_-]+$` ve en az 3
  karakterdir (`data/manual_fact_input.schema.json:33-37`).
- `<case-id>` ve `<document-id>` paylaşılan path-containment denetiminin
  yasak alt dizgilerini içermez (`src/path_containment.py`,
  `FORBIDDEN_SEGMENT_SUBSTRINGS`); `manual-fact` bunu her G/Ç'den önce
  denetler (`ui/services/manual_fact_mutation_facade.py:228-235`).
- `<fact-id>` kodda girdinin `input_digest`'inden türetilir
  (`src/manual_fact_entry_engine.py:448-451`): yalnız belge kimliği ve
  hex'ten oluşur, kişisel veri taşımaz.
- Promotion `--note` bu pilotta **kullanılmaz**.

### 10.4 Çalışma ortamındaki ikincil kopyalar

Kaynak: Temel L877–L885. **Sapmalar:** anahtar ve `$maskArgs` cümleleri
çıkarıldı.

PowerShell geçmişi ve konsol çıktısı gerçek değer taşıyabilir. Bu nedenle
§4.2 ve §4.3'teki kabuk kuralları uygulanır; preview'ın bastığı içerik yalnız
ekranda okunur, dosyaya yönlendirilmez. İçeriğe dokunan her insan-only
oturum, işi biter bitmez **kapatılır**. Hiçbir değişken bir sonraki oturuma
**taşınmaz**; her yeni içerik oturumu §4.3 (b) ile açılır.

### 10.5 `<restricted-dir>` içerik sözleşmesi (bağlayıcı)

Kaynak: Temel L887–L1025. **Sapmalar:** izinli küme `deadline-report.txt`
tek adına indirildi (Temel L965'teki `$allowedNames`); harness çıktı adları
çıkarıldı. Yardımcı fonksiyonlar ve hash kaydı blokları **birebirdir**.

1. **Düz yapı.** `<restricted-dir>` yalnız doğrudan altında **normal
   dosyalar** taşır. Alt dizin, reparse point veya normal dosya dışında
   herhangi bir öğe bulunursa: **DUR** (H56).
2. **Genel ve sabit ad.** İzinli tek dosya adı `deadline-report.txt`'dir
   (§19).
3. **Önceden kayıt.** İzinli küme, intake'ten önce (zincir adım 4),
   `<restricted-dir>` **boşken** `<evidence-dir>\restricted-allowed-files.txt`
   dosyasına exclusive-create ile yazılır. Hemen ardından aynı oturumda hash
   kaydı `<evidence-dir>\restricted-allowed-files.sha256.txt` dosyasına
   exclusive-create ile tek satır olarak yazılır:
   `restricted_allowed_files_sha256=<64-küçük-hex>` ve son bayt LF. Hash
   **basılmaz** ve elle kopyalanmaz. Kayıt sonradan yeniden üretilemez,
   silinemez veya üzerine yazılamaz; değişiklik gereği **DUR** ve yeni
   inceleme demektir. Hash kaydı olmadan intake başlatılamaz.
4. **Kaydın yeniden doğrulanması.** Her envanterden önce ve §28.3.2'deki
   restricted silme guard'ından hemen önce `Test-PilotAllowedHash` ile
   doğrulanır; çıktı yalnız `ALLOWED_FILE_HASH_OK=True` veya `False`'tur.
   `False` envanteri geçersiz kılar: **DUR** (H56). Bu mekanizma
   yanlışlıkla değişimi tespit eder; kriptografik imza **iddiası taşımaz**.
5. **Envanter.** Her içerik oturumunun başında, rapor yazıldıktan sonra ve
   kapanış manifestinden önce alınır. İzinli küme dışındaki her dosya veya
   dizin: **DUR** (H56).

Ortak yardımcılar (Temel L944–L948 birebir; her oturumda yeniden tanımlanır;
§13.8 ortak yardımcıları **önce** tanımlanmış olmalıdır):

```powershell
function Write-PilotExclusive([string]$path, [string[]]$lines) { if (Test-Path -LiteralPath $path) { return $false }; try { $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None) } catch { return $false }; $w = New-Object System.IO.StreamWriter($fs, (New-Object System.Text.UTF8Encoding($false))); try { $w.NewLine = "`n"; foreach ($l in $lines) { $w.WriteLine($l) } } finally { $w.Dispose() }; return $true }
function Get-PilotRestrictedState([string]$rDir) { try { $items = @(Get-ChildItem -LiteralPath $rDir -Force -Recurse -ErrorAction Stop) } catch { return $null }; $bad = @($items | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or ($_.DirectoryName -ne $rDir.TrimEnd('\')) }).Count; return [pscustomobject]@{ Bad = $bad; Files = @($items | Where-Object { -not $_.PSIsContainer } | Sort-Object Name) } }
function Test-PilotAllowedHash([string]$listPath, [string]$recordPath) { try { if (-not ((Test-PilotLeafFile $listPath) -and (Test-PilotLeafFile $recordPath))) { return $false }; $txt = (New-Object System.Text.UTF8Encoding($false)).GetString([System.IO.File]::ReadAllBytes($recordPath)); if ($txt -cnotmatch '^restricted_allowed_files_sha256=[0-9a-f]{64}\n\z') { return $false }; $expected = $txt.Substring('restricted_allowed_files_sha256='.Length, 64); $h = (Get-FileHash -LiteralPath $listPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant(); return [string]::Equals($h, $expected, [System.StringComparison]::Ordinal) } catch { return $false } }
```

`Write-PilotExclusive`, hedef zaten mevcutsa **hiç yazmaz** ve `False`
döner. Yazma sırasında bir hata oluşursa: **DUR**.

İzinli kümenin kaydı (zincir adım 4, `Test-PilotPath 'restricted-dir'`
`PATH_OK` verdikten sonra, bir kez). **Temel L965'ten sapma:** `$allowedNames`
yalnız `deadline-report.txt` taşır:

```powershell
$allowedNames = @('deadline-report.txt')
$namesOk = ($allowedNames.Count -eq @($allowedNames | Sort-Object -Unique).Count) -and (@($allowedNames | Where-Object { $_ -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}\.(txt|log|jsonl)$' }).Count -eq 0)
$rState = Get-PilotRestrictedState "<restricted-dir>"
if ($namesOk -and ($null -ne $rState) -and ($rState.Bad -eq 0) -and ($rState.Files.Count -eq 0) -and (Write-PilotExclusive "<evidence-dir>\restricted-allowed-files.txt" (@('# kind=restricted-allowed') + $allowedNames))) { "RESTRICTED_ALLOWED_RECORD=WRITTEN" } else { "STOP RESTRICTED_ALLOWED_RECORD=FAIL" }
```

Hash kaydı (`RESTRICTED_ALLOWED_RECORD=WRITTEN` alındıktan hemen sonra, bir
kez; Temel L979–L999 birebir):

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

Beklenen: **`ALLOWED_FILE_HASH_RECORDED=True`**. Başka her sonuç **DUR**
(H56): kayıt silinmez, yeniden üretilmez ve üzerine yazılmaz.

Envanter kontrolü (Temel L1010–L1018 birebir):

```powershell
$allowedHashOk = Test-PilotAllowedHash "<evidence-dir>\restricted-allowed-files.txt" "<evidence-dir>\restricted-allowed-files.sha256.txt"
"ALLOWED_FILE_HASH_OK=$allowedHashOk"
$allowedLines = @(); $rState = $null
if ($allowedHashOk -eq $true) { try { $allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false)))); $rState = Get-PilotRestrictedState "<restricted-dir>" } catch { $allowedLines = @(); $rState = $null } }
$allowedSet = @($allowedLines | Select-Object -Skip 1)
$rUnexpected = @($rState.Files | Where-Object { $allowedSet -cnotcontains $_.Name }).Count
if (($allowedHashOk -eq $true) -and ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and ($null -ne $rState) -and ($rState.Bad -eq 0) -and ($rUnexpected -eq 0)) { "RESTRICTED_INVENTORY=OK"; "RESTRICTED_FILE_COUNT=$($rState.Files.Count)" } else { "STOP RESTRICTED_INVENTORY=FAIL" }
```

Beklenen: her envanterde `ALLOWED_FILE_HASH_OK=True` ve
`RESTRICTED_INVENTORY=OK`. Rapor yazılmadan önce `RESTRICTED_FILE_COUNT=0`,
sonra `1`.

---

## 11. Manuel intake ve iki katmanlı doğrulama

### 11.1 İlke

Kaynak: Temel L1031–L1038. Sapma yok.

`case.json` için koordineli bir production writer **bulunmaması** tek başına
bir kod bloklayıcısı değildir; intake iki bağımsız katmanla doğrulanır.
**Mekanik kontrol ile avukat kontrolü birbirinin yerine geçmez**; ikisi de
zorunludur. Operatörün yazdığı her alan, avukat orijinal belgeye karşı
**alan-alan yazılı olarak doğrulamadan** kullanılamaz (§11.4).

### 11.2 Intake adımları (operatör, insan-only oturum)

Kaynak: Temel L1040–L1091. **Sapmalar:** maskeleme tohumu gerekçeleri
çıkarıldı; metin aracı Form E4'e bağlandı; **`file.page_count` adımı (5)
eklendi**; 60.000 sınırının kaynağı Form G7 olarak düzeltildi; (4)'teki
uzunluk bloğuna temizlik satırı `Remove-Variable txt` eklendi (Temel
L1072–L1073'te yoktur; davranışı değiştirmez).

1. Ön kontrol: `<case-root>` **mevcut değildir**; varsa **DUR** (H29).
   Ebeveyni `<repo-root>\data\cases` §13.8 yol kapısından geçmiştir ve bu
   oturumda `PATH_OK=external-root-contract` alınmıştır; alınmadıysa intake
   başlatılmaz, **DUR** (H52).
2. Belge Form **E2**'deki kanalla, ancak §6.6/7 (a) form hash yeniden
   ölçümü (`FORM_HASH_RECHECK … match=True`) ve §6.4 taşıyıcı kontrolü
   geçtikten sonra teslim alınır. `<case-root>` altında
   `case.json`, `documents/<document-id>/document.json`, orijinal belge
   dosyası ve `documents/<document-id>/extracted/<document-id>.txt`
   oluşturulur. `document.json` içindeki `file.relative_path` değeri
   `cases/<case-id>/documents/<document-id>/` önekini ve `file.file_name`
   değerini taşır (`src/case_document_validator.py`, `validate_file_paths`).
   `documents/<document-id>/extractions/` dizini **önceden oluşturulmaz**;
   `manual-fact` writer'ı onu ve `generation_reviews/` alt dizinini kendisi
   oluşturur (`src/manual_fact_entry_engine.py:683-684`).
3. **JSON dosyaları BOM'suz UTF-8'dir.** Windows PowerShell'in
   `Set-Content -Encoding UTF8` ve `Out-File -Encoding utf8` komutları BOM
   yazar; JSON dosyaları bu komutlarla **yazılmaz**. Kontrol (Temel L1059
   birebir):

```powershell
foreach ($f in @("<case-root>\case.json", "<case-root>\documents\<document-id>\document.json")) { $b = [System.IO.File]::ReadAllBytes($f); if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { Write-Output "STOP JSON_BOM=PRESENT" } else { Write-Output "JSON_BOM=NONE" } }
```

   Beklenen: iki kez **`JSON_BOM=NONE`**. Başka her çıktı **DUR**'dur (H43).
4. **Metin dosyası.** Yol sabittir: `manual-fact` metni yalnız
   `documents/<document-id>/extracted/<document-id>.txt` yolundan okur
   (`ui/services/manual_fact_mutation_facade.py:544-553`). Dosya BOM'suz
   UTF-8 yazılır (motor BOM'u tolere eder:
   `src/manual_fact_entry_engine.py:383-395`). Metin boş olamaz (kural M-06).
   Form G7 gereği 60.000 karakteri aşamaz; ön kontrol (Temel L1072–L1073
   birebir; son satır eklendi):

```powershell
$txt = [System.IO.File]::ReadAllText("<case-root>\documents\<document-id>\extracted\<document-id>.txt", [System.Text.Encoding]::UTF8)
if ($txt.Length -gt 0 -and $txt.Length -le 60000) { Write-Output "TEXT_LENGTH=OK" } else { Write-Output "STOP TEXT_LENGTH=OUT_OF_RANGE" }
Remove-Variable txt -ErrorAction SilentlyContinue
```

5. **`file.page_count` operatör tarafından DOLDURULUR.** Repoda
   `page_count` dolduran bir kod yoktur ve şema alanın `null` olmasına izin
   verir; ancak `manual-fact`, `page_count` bir tamsayı ve ≥ 1 değilse
   girdiyi **reddeder** (`src/manual_fact_entry_engine.py:361-371`, kural
   M-04; `True` gibi bir boolean da reddedilir). Operatör, orijinal
   belgenin sayfa sayısını `document.json` `file.page_count` alanına
   tamsayı olarak yazar; değer §11.4'te avukat tarafından onaylanır. Boşsa
   veya tamsayı değilse intake **reddedilir**. Ön kontrol (yalnız sonuç
   basar, değer basmaz; standart PowerShell davranışından gelir, §1.6
   provasında doğrulanır):

```powershell
$pcDoc = (New-Object System.Text.UTF8Encoding($false, $true)).GetString([System.IO.File]::ReadAllBytes("<case-root>\documents\<document-id>\document.json")) | ConvertFrom-Json
$pc = $pcDoc.file.page_count
if ((($pc -is [int]) -or ($pc -is [long])) -and ($pc -ge 1)) { "PAGE_COUNT=OK" } else { "STOP PAGE_COUNT=INVALID" }
Remove-Variable pcDoc, pc -ErrorAction SilentlyContinue
```

   Beklenen: **`PAGE_COUNT=OK`**. Başka her çıktı **DUR**'dur (Y8).
6. **Metin çıkarma** yalnız Form **E4**'te onaylanan, yerel ve çevrimdışı
   araçla yapılır (§4.2/3).
7. Intake dosyalarındaki **bütün** `verification_state` alanları `unverified`
   yazılır. Doğrulama durumunu yükseltmek yalnız koordineli Fact Verification
   Workflow ile ve avukat kararıyla yapılır (`CLAUDE.md` §8).
8. `document.json` içinde `active` değeri `true` ve `document_type` değeri
   `vergi_ceza_ihbarnamesi` olmalıdır; `manual-fact` ikisini de denetler
   (`src/manual_fact_entry_engine.py:353-359`, kural M-05) ve verification
   evidence belgesi olarak kullanılabilmesi `active` değerine bağlıdır
   (§15.3).
9. `case.json` `case_id` değeri `<case-id>`'ye, `document.json`
   `case_id` ve `document_id` değerleri sırasıyla `<case-id>` ve
   `<document-id>`'ye, belge dizininin adı `<document-id>`'ye **birebir**
   eşittir; `manual-fact` bu kimlikleri girdi dosyası, `--case`/`--document`
   argümanı, `document.json`, `case.json` ve belge dizini adı arasında
   karşılaştırır (`ui/services/manual_fact_mutation_facade.py:593-614`, kural
   M-13; kod yorumu bunu "üç yönlü" diye adlandırır, `case_id` için fiilen
   dört değer karşılaştırılır).
10. `documents/` altında **hiçbir** symlink veya junction bulunmaz:
    `manual-fact` bütün `documents/*/document.json` dosyalarını
    containment-first tarar ve tek bir alias'ta bütün taramayı durdurur
    (`ui/services/manual_fact_mutation_facade.py:314-353`).

### 11.3 Katman 1 — mekanik kontroller

Kaynak: Temel L1093–L1234. **Sapmalar:** "preview/POST öncesi" ifadeleri
`manual-fact` preview ve apply öncesine; (f)'deki "model POST'u" ifadesi
`manual-fact`'e çevrildi; (b)'ye hash kaydından **önce** çalışan tarih
token'ı ön kontrolü (YENİ blok) eklendi ve kayıt satırı bu kontrolün
`True` sonucuna bağlandı (`($dtOk -eq $true)` koşulu). Diğer komut
blokları **birebirdir**.

Her biri ilk `manual-fact` preview'dan **önce**, insan-only oturumda ve
sonucu evidence'a yazılarak yapılır.

**(a) Orijinal belge hash'i.** `case-document validator` fiziksel dosyayı veya
`file.sha256` alanını **denetlemez**; bu karşılaştırma **operatörün zorunlu
adımıdır**:

```powershell
$docPath = "<case-root>\documents\<document-id>\document.json"
$doc = [System.IO.File]::ReadAllText($docPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$declared = [string]$doc.file.sha256
if ($declared -notmatch '^[0-9a-fA-F]{64}\z') { Write-Output "STOP sha256 beyani yok veya gecersiz" } else { $orig = (Resolve-Path -LiteralPath (Join-Path "<repo-root>\data" $doc.file.relative_path)).Path; $actual = (Get-FileHash -LiteralPath $orig -Algorithm SHA256).Hash; if ($actual.ToLowerInvariant() -eq $declared.ToLowerInvariant()) { Write-Output "INTAKE_HASH=MATCH" } else { Write-Output "STOP INTAKE_HASH=MISMATCH" } }
```

Beklenen: **`INTAKE_HASH=MATCH`**. Başka her çıktı **DUR**'dur (H6).

**(b) Metin dosyası ve orijinal belge hash'i — kayıt ve yeniden
karşılaştırma.** Hash'ler intake'te, (a) `INTAKE_HASH=MATCH` verdikten sonra
**bir kez** hesaplanır ve stdout'a basılmadan `<evidence-dir>\intake-hashes.tsv`
dosyasına exclusive-create ile yazılır. Avukatın intake onayı (Katman 2) bu
kayıttaki metin hash'ine bağlanır.

Ortak hedef tanımı (her iki komuttan önce, aynı oturumda):

```powershell
$hashDoc = [System.IO.File]::ReadAllText("<case-root>\documents\<document-id>\document.json", [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$hashOrig = [System.IO.Path]::Combine("<repo-root>\data", ([string]$hashDoc.file.relative_path).Replace('/', '\'))
$hashText = "<case-root>\documents\<document-id>\extracted\<document-id>.txt"
$hashPathsOk = (Test-PilotLeafFile $hashOrig) -and (Test-PilotLeafFile $hashText) -and $hashOrig.ToLowerInvariant().StartsWith(("<case-root>\documents\<document-id>\").ToLowerInvariant())
```

**Tarih token'ı ön kontrolü (YENİ; M-1; hash kaydından ÖNCE, aynı
oturumda, ortak hedef tanımından sonra).** Metin dosyasında `manual-fact`'in
tanıdığı biçimde (`GG.AA.YYYY` veya `GG/AA/YYYY`; motor deseni
`src/manual_fact_entry_engine.py:117` ile aynı: ASCII rakam, aynı ayraç,
rakam sınırları) **en az bir** token bulunup bulunmadığını ölçer. Yalnız
boolean basar; ne tarih, ne sayı, ne metin basılır. Standart PowerShell/.NET
davranışından gelir ve §1.6 provasında doğrulanır:

```powershell
$dtOk = $false
try { if ($hashPathsOk) { $dtTxt = (New-Object System.Text.UTF8Encoding($false, $true)).GetString([System.IO.File]::ReadAllBytes($hashText)).TrimStart([char]0xFEFF); $dtOk = ([regex]::Matches($dtTxt, '(?<![0-9])[0-9]{2}([./])[0-9]{2}\1[0-9]{4}(?![0-9])').Count -gt 0) } } catch { $dtOk = $false }
Remove-Variable dtTxt -ErrorAction SilentlyContinue
if ($dtOk -eq $true) { "TEXT_DATE_TOKEN_PRESENT=True" } else { "STOP TEXT_DATE_TOKEN_PRESENT=False" }
```

Beklenen: **`TEXT_DATE_TOKEN_PRESENT=True`**. `False` ise metinde tebliğ
tarihi tanınabilir biçimde yoktur (Form G9 cevabıyla veya metin
çıkarmayla çelişki): hash kaydı **yazılmaz**, `manual-fact` çalıştırılmaz,
**DUR** (Y16). Bu kontrol gerekli ama yeterli değildir: bulunan token'ın
tebliğ tarihi olduğunu ve doğru okunduğunu göstermez; o, avukatın §11.4/1
onayıdır.

Kayıt (intake'te, bir kez; `TEXT_DATE_TOKEN_PRESENT=True` alındıktan
sonra):

```powershell
if ($hashPathsOk -and ($dtOk -eq $true) -and (Write-PilotExclusive "<evidence-dir>\intake-hashes.tsv" @('# kind=intake-hashes', ("original`t" + (Get-FileHash -LiteralPath $hashOrig -Algorithm SHA256).Hash.ToLowerInvariant()), ("extracted-text`t" + (Get-FileHash -LiteralPath $hashText -Algorithm SHA256).Hash.ToLowerInvariant())))) { "INTAKE_HASHES_RECORDED=True" } else { "STOP INTAKE_HASHES_RECORDED=False" }
```

Yeniden karşılaştırma (`manual-fact` preview'dan önce **ve** `manual-fact`
apply'dan önce, aynı oturumda ortak hedef tanımından sonra):

```powershell
$hashRec = @([System.IO.File]::ReadAllLines("<evidence-dir>\intake-hashes.tsv", (New-Object System.Text.UTF8Encoding($false))))
$hashMatch = $hashPathsOk -and ($hashRec.Count -eq 3) -and ($hashRec[0] -ceq '# kind=intake-hashes') -and ($hashRec[1] -ceq ("original`t" + (Get-FileHash -LiteralPath $hashOrig -Algorithm SHA256).Hash.ToLowerInvariant())) -and ($hashRec[2] -ceq ("extracted-text`t" + (Get-FileHash -LiteralPath $hashText -Algorithm SHA256).Hash.ToLowerInvariant()))
if ($hashMatch) { "SOURCE_HASHES_MATCH=True" } else { "STOP SOURCE_HASHES_MATCH=False" }
Remove-Variable hashDoc, hashOrig, hashText, hashPathsOk, hashRec, hashMatch -ErrorAction SilentlyContinue
```

`SOURCE_HASHES_MATCH=True` dışındaki her sonuç: `manual-fact` **çalıştırılmaz**,
**DUR** (H16).

**(c) Case validator** (`src/case_validator.py`, `main`):

```powershell
& "<python>" -m src.case_validator "<case-root>\case.json"
```

**(d) Case-document validator** (`src/case_document_validator.py`, `main`):

```powershell
& "<python>" -m src.case_document_validator "<case-root>"
```

**Argümansız validator çağrısı YASAKTIR**: argüman verilmezse iki validator
da sessizce `data/cases/case_0001` fixture'ını doğrular. Her çağrıdan sonra
çıktının başında basılan yolun `<case-root>` altını gösterdiği ve
`Case ID:` satırının `<case-id>` olduğu doğrulanır; değilse **DUR** (H7).
"Hatasız" şu demektir: traceback yok, hata satırı yok, uyarı satırı yok.
Evidence'a yalnız `PASS`/`FAIL` ve hata/uyarı **sayısı** yazılır. Herhangi
bir hata **DUR**'dur; herhangi bir uyarı, avukat ile kullanıcı onu yazılı
olarak kabul edilebilir saymadıkça **DUR**'dur.

**(e) Ignore ve tracked sınırı.**

```powershell
git status --porcelain -- data/cases/case_0001
git status --ignored --porcelain -- data/cases
git check-ignore -v "data/cases/<case-id>/case.json"
```

Beklenen: ilk komut **boş**; ikinci komut **yalnız** `!! data/cases/<case-id>/`;
üçüncü komut `.gitignore` içindeki `/data/cases/` kuralını gösterir. `??`
öneki veya `case_0001` için herhangi bir çıktı **DUR**'dur (H8).

**(f) Vergi türü sözlük kontrolü.** Mali tatil sınıflandırması
`dispute_items[].tax_type` değerlerini iki dar sözlüğe karşı **exact**
eşleştirir (`src/deadline_calculator.py`, `MALI_TATIL_INCLUDED_TAX_TYPES`,
`MALI_TATIL_EXCLUDED_TAX_TYPES`, `classify_mali_tatil_tax_type`). Sözlük
uyumu **her dosyada** ve `manual-fact` preview'dan **önce** şart koşulur.

- Dahil (11): `katma değer vergisi`, `kdv`, `kurumlar vergisi`,
  `gelir vergisi`, `damga vergisi`, `veraset ve intikal vergisi`,
  `motorlu taşıtlar vergisi`, `mtv`, `vergi ziyaı cezası`,
  `usulsüzlük cezası`, `özel usulsüzlük cezası`.
- İstisna (7): `özel tüketim vergisi`, `ötv`,
  `banka ve sigorta muameleleri vergisi`, `bsmv`, `özel iletişim vergisi`,
  `öiv`, `şans oyunları vergisi`.

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

Beklenen: **`TAX_TYPE_VOCAB=OK`** ve her değerin avukatın Form G8
sınıflandırmasıyla aynı olması. Aksi hâlde `manual-fact` **çalıştırılmaz**,
**DUR** (H51).

### 11.4 Katman 2 — avukatın alan-alan kontrolü

Kaynak: Temel L1236–L1285. **Sapmalar:** `file.page_count` satırı
eklendi; "modele giden bağlam" ifadesi çıkarıldı.

Avukat, orijinal belgeyi elindeki kaynakla karşılaştırarak aşağıdakilerin her
birini **ayrı ayrı ve yazılı** olarak onaylar (`LEGAL_APPROVED`).

**Metin ve taraflar:**

1. `extracted/<document-id>.txt` metninin (hash'iyle tanımlanan sürüm)
   orijinal belgeyi doğru ve eksiksiz aktardığı. **Özellikle tebliğ
   tarihinin metinde doğru ve `GG.AA.YYYY` / `GG/AA/YYYY` biçiminde
   yazıldığı** (Form G9): `manual-fact` alıntıyı bu metinde arar ve
   alıntıdaki tarihin girilen tarihle birebir eşleşmesini ister (§14.2);
   metinde yanlış okunmuş veya başka biçimde yazılmış bir tarih manuel
   girişi imkânsız kılar (§32).
2. `case.json` `parties[]` kayıtlarının doğru ve eksiksiz olduğu.
3. `document.json` `file.page_count` değerinin orijinal belgenin sayfa
   sayısına eşit olduğu (§11.2/5).

**Deadline kural seçimini veya hesabını etkileyen alanlar** (kaynak:
`src/deadline_rule_selection_policy.py`, `build_case_context` ve
`rule_matches_context`; `src/deadline_calculator.py`):

| Alan | Dosya | Kaynaktaki etkisi |
|---|---|---|
| `document_type` | `document.json` | Kural uygulanabilirliği; ayrıca `manual-fact` M-05 |
| `dispute_items[].tax_type` | `case.json` | Kuralın `tax_types` filtresi ve mali tatil m.1/7 istisna sınıflandırması; §11.3 (f) sözlüğünden birebir bir terim |
| `administrative_actions[].issuing_authority` | `case.json` | Mali tatil istisna kontrolü (gümrük, belediye, il özel idaresi anahtar sözcükleri) |
| `administrative_actions[].action_category` | `case.json` | Stopping-event beyanıyla çelişki kontrolü (`settlement`, `correction_complaint`) |
| `case_type` / `dispute_type` | `case.json` | Kuralın `case_types` filtresi |
| `stage` / `case_stage` / `procedural_stage` ve `proceedings` içindeki `stage`, `status`, `case_stage` | `case.json` | Kuralın `case_stages` filtresi |

**Diğer hukuki sınıflandırma ve tarih alanları:**

4. `dispute_items[].period` ve `asserted_legal_basis_refs`.
5. `document.json` içindeki `document_category`, `document_subtype`,
   `issuer_party_id`, `dates[]` ve `reference_numbers[]`.
6. `administrative_actions[]` içindeki `action_type`, `action_date` ve
   `notification_date`. Bu onay §14.3'teki manuel girdi karşılaştırmasının
   ve §15.3'teki verification kararının **yerine geçmez**; deadline'ın
   anchor'ı bu alandan değil, doğrulanmış fact'ten türeyen timeline
   olayından gelir (§16).
7. `events[]` ve `proceedings` alanlarına intake'te veri girildiyse her biri.
8. Bütün `verification_state` alanlarının `unverified` olduğu (§11.2/7).

Yazılı onay repo dışında saklanır; evidence'a yalnız hash ve kişisel veri
içermeyen kapsam özeti girer. Avukat onayı yoksa veya bir alan onaysızsa:
**DUR** (H9, H43).

---

## 12. IAM aktörü ve yazılı avukat kararları

### 12.1 Avukat kararları

Kaynak: Temel L1291–L1306. **Sapmalar:** manuel girdi karşılaştırması
eklendi.

| Karar | Uygulandığı yer |
|---|---|
| Manuel tebliğ girdisinin orijinal belgeyle karşılaştırılması | §14.3 (`manual-fact` apply'ın ön koşulu) |
| Fact kabulü | §15.2, `promotion --row-key fact` |
| Tebliğ tarihi fact'inin verification'ı | §15.3, `verification` |
| Timeline onayı | §16, `promotion --row-key timeline` |
| Adli tatil uygulanabilirliği | §18.1, `--judicial-recess-applicable` |
| Stopping-event beyanı ve referansı | §17.1, `--stopping-event-status`, `--stopping-event-attestation-ref` |
| Deadline onayı | §18.4, `approval --row-key deadline` |

### 12.2 IAM aktörünün anlamı (dürüst sınır)

Kaynak: Temel L1308–L1316. Sapma yok.

- Mutasyonlar Adım 8'de oluşturulan **mevcut** avukat kullanıcısı
  (`<actor-user-id>`) ile yapılır.
- Bu aktör avukatın **gerçek kimliğini veya elektronik imzasını kanıtlamaz**;
  yalnız concierge operasyon aktörüdür (`ui/cli_mutate.py` başlığı:
  "trusted-local-shell, NOT cryptographic OS identity").
- Aynı aktör operatörün çalıştırdığı her komutta kullanılır; bu yüzden
  journal'daki `actor_user_id` iki kişi kuralının (§4.1) kanıtı **değildir**.

### 12.3 Assignment (ADMIN oturumu, tek çalıştırma)

Kaynak: Temel L1318–L1331. **Sapmalar:** zamanlama zincir adım 8 ile 10
arasına bağlandı.

Assignment mümkün olan **en geç** aşamada verilir: intake, mekanik kontroller,
avukatın intake onayı, manuel girdi yazımı ve avukatın girdi karşılaştırması
(zincir adım 5–8) tamamlandıktan sonra ve ilk veritabanlı preview'dan (zincir
adım 10, `manual-fact` preview yetkilendirme için veritabanı okur:
`ui/services/manual_fact_mutation_facade.py:660-664`) **hemen önce**.

```powershell
& "<python>" -m scripts.iam_admin assign-case --user-id <actor-user-id> --case-id <case-id> --role lawyer --actor-user-id <admin-user-id>
```

Komut ayrı `REAL_ACTION_APPROVED` ile ve **bir kez** çalıştırılır; sonuç
belirsizse §27.2'ye göre **DUR**.

### 12.4 İşlem türüne göre oturum ve IAM beklentisi

Kaynak: Temel L1333–L1348. **Sapmalar:** `manual-fact` ve reconciliation
operatörü satırları eklendi.

İki veritabanı rolü **asla aynı PowerShell oturumunda** bulunmaz
(`docs/operations/local-postgresql-iam-adoption.md` §G.1, §G.2).

| İşlem | Oturum (DB rolü) | IAM aktörü | Beklenti |
|---|---|---|---|
| `assign-case`, `revoke-assignment` | ADMIN (`vergi_iam_admin`) | `--actor-user-id <admin-user-id>` | Aktör global `admin` |
| `manual-fact` preview, diğer preview'lar | APP (`vergi_app`) | `--actor-user-id <actor-user-id>` | Aktör mevcut, `disabled = false`, case için aktif `lawyer` assignment'ı var |
| `manual-fact` apply, diğer apply/approve | APP (`vergi_app`) | `--actor-user-id <actor-user-id>` | Aynı; `lawyer` rolü `read` ve `mutate` taşır |
| `ui.reconciliation_operator` (yalnız §14.6) | APP (`vergi_app`) | — (`--actor-ref <reconcile-actor-ref>`, aktör türü sabit `cli_service`) | `vergi_app` journal üzerinde `SELECT, INSERT, UPDATE` taşır (`db/migrations/0006_iam_runtime_privileges.sql:208`) |
| `ui.deadline_report` | APP (`vergi_app`), salt-okunur transaction | `--actor-user-id <actor-user-id>` | Aktif assignment rolü tam olarak `lawyer` |
| Salt-okunur SQL | APP (`vergi_app`) | — | `vergi_app` bu tablolarda `SELECT` yetkisine sahiptir |

`vergi_iam_admin` rolünün `mutation.mutation_journal` üzerinde **hiçbir
yetkisi yoktur**; bu yüzden rapor, journal sorguları ve reconciliation ADMIN
oturumunda **koşulmaz**.

---

## 13. Pilot DB ve çalışma ortamı preflight'ı

### 13.1 İlke

Kaynak: Temel L1354–L1359. **Sapma:** "harness" kelimesi çıkarıldı.

Kümenin açık veya kapalı olduğu, runtime'ın veya ortamın "değişmediği"
**varsayılmaz**. Her operasyon oturumunun başında ve her mutasyondan önce
durum **mekanik olarak ölçülür** ve sonucu evidence'a yazılır.

### 13.2 Repo durumu

Kaynak: Temel L1361–L1374. **Sapma:** son komut **bu** runbook'u adlandırır.

```powershell
git branch --show-current
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=all
git status --ignored --porcelain -- data/cases
git ls-files --error-unmatch docs/operations/concierge-local-case-pilot.md
```

Beklenen: branch `claude-dev`; HEAD, yürütme yetkisinde kullanıcının
onayladığı commit; çalışma ağacı temiz; ignored görünümde intake'ten önce
**hiçbir girdi**, intake'ten sonra **yalnız** `!! data/cases/<case-id>/`; son
komut hatasız (runbook tracked). Aksi **DUR** (H30).

### 13.3 Yorumlayıcı ve runtime paritesi

Kaynak: Temel L1376–L1381 ve L1559–L1566 (yalnız runtime kısmı).
**Sapmalar:** harness/monitor/probe paritesi çıkarıldı; `pip check` komutu
açıkça yazıldı.

`<python>`, Adım 9A'da offline kurulan, repo dışındaki concierge runtime'ın
yorumlayıcısıdır. Yürütme oturumunda:

```powershell
& "<python>" -m pip check
```

`manual-fact` motoru `jsonschema.Draft202012Validator` kullanır
(`src/manual_fact_entry_engine.py:62`); aynı sınıfı Adım 9'da bu runtime'da
koşmuş olan `src/case_fact_validator.py:43-44` de kullanır.

Beklenen: `No broken requirements found`; değilse **DUR** (H31). Runtime'ın
paket kümesi Adım 9 checkpoint'i §C'nin kaydettiği kümeye (41 manifest
paketi ve `pip`, toplam 42 satır) karşı mekanik olarak karşılaştırılır;
temel runbook bu karşılaştırmanın exact komutunu yazmaz ve bu runbook da
yazmaz — komut §1.6 provasında sabitlenir (§32). Uyuşmazlık: **DUR** (H31).

### 13.4 Küme ve oturumlar

Kaynak: Temel L1383–L1394. Sapma yok.

- Küme, Adım 8'in kalıcı, yalnız-loopback, servissiz kümesidir. Başlatma,
  durdurma ve durum ölçümü
  `docs/operations/local-postgresql-iam-adoption.md` §D'ye göre yapılır.
  Küme bir servis değildir; pencere kapanırsa durur — bu yüzden her adımdan
  önce yeniden ölçülür (H27).
- ADMIN ve APP oturumları aynı runbook'un §G.2'sine göre **ayrı PowerShell
  oturumlarında** kurulur. Bağlantı dizesi ve kimlik bilgisi dosyası bu
  belgeye ve evidence'a yazılmaz.
- İçeriğe dokunan bütün oturumlar insan-only oturumlardır (§4.2) ve §4.3
  (b)'ye göre `-NoProfile` ile açılır.

### 13.5 Salt-okunur SQL sözleşmesi ve DB kontrolleri (APP oturumu)

Kaynak: Temel L1396–L1486. **Sapmalar:** beklenti tablosu bu zincirin
adımlarına göre yeniden yazıldı; çağırma bloğu **birebirdir**.

**Sözleşme (bağlayıcı):**

1. SQL yalnız **ölçüm** içindir: yalnız `SELECT` ve durumu okuyan `SHOW`.
   IAM mutasyonu yalnız `scripts.iam_admin` ile, journal yazımı yalnız
   `ui.cli_mutate` ve (§14.6) `ui.reconciliation_operator` ile yapılır.
   **Düzeltici SQL yasaktır** (H54).
2. Sorgular **APP oturumunda** çalıştırılır; bağlantı bilgisi yalnız
   `VERGI_IAM_DATABASE_URL` değişkeninin **adıyla** geçer.
3. Her çağrı açık bir **salt-okunur transaction** içinde koşar.
4. Çağırma biçimi (Temel L1422–L1426 birebir):

```powershell
$psqlOut = @(& "<psql>" --dbname="$env:VERGI_IAM_DATABASE_URL" --no-password --no-psqlrc -v ON_ERROR_STOP=1 -q -A -t -c "BEGIN TRANSACTION READ ONLY" -c "SHOW transaction_read_only" -c "<select-statement>" -c "ROLLBACK")
$psqlRc = $LASTEXITCODE
$psqlReadOnly = ($psqlOut.Count -ge 1) -and ($psqlOut[0] -ceq 'on')
if (($psqlRc -eq 0) -and $psqlReadOnly) { "PSQL_EXIT=0"; "PSQL_READ_ONLY=True"; $psqlRows = @($psqlOut | Select-Object -Skip 1); "PSQL_ROW_COUNT=$($psqlRows.Count)"; foreach ($row in $psqlRows) { "PSQL_ROW=$row" } } else { "STOP PSQL_EXIT_OR_READ_ONLY=FAIL" }
Remove-Variable psqlOut, psqlRows, row -ErrorAction SilentlyContinue
```

   - `PSQL_EXIT` 0 değilse veya `PSQL_READ_ONLY=True` basılmadıysa sonuç
     **kullanılmaz**: **DUR** (H54).
   - `PSQL_ROW` satırları yalnız ekranda okunur; evidence'a yalnız çıkış
     kodu, read-only boolean'ı ve izin verilen sayaçlar yazılır.
   - Bu çağırma biçimi canlı kümede henüz **denenmemiştir** (Temel
     L1440–L1452); provada statik olarak kontrol edilir.

**Kontroller.** Aşağıdaki her ifade yukarıdaki biçimle ayrı ayrı
çalıştırılır (Temel L1457–L1475 birebir):

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

| Ölçüm noktası | Case journal satırı | Çözülmemiş journal satırı | Aktif assignment | Toplam assignment satırı |
|---|---|---|---|---|
| `assign-case` öncesi (zincir adım 4 ve 9) | 0 | 0 | 0 | 0 |
| Assignment sonrası, her preview ve apply öncesi | O ana kadar tamamlanan apply sayısı; hepsi `completed` (yalnız §14.6 yolundan geçildiyse ayrıca `failed` satırlar) | 0 | 1 | 1 |
| Revoke sonrası (zincir adım 24) | Değişmedi | 0 | 0 | 1 |

Bu zincirin normal yolunda beklenen aileler, sırasıyla: `generation.fact_manual`,
`promotion.fact`, `verification.fact`, `generation.timeline`,
`promotion.timeline`, `generation.deadline`, `approval.deadline` (yedi
`completed` satır). Her ölçüm noktasında iki kullanıcı mevcut ve
`disabled = false` olmalıdır. Aksi **DUR** (H17).

### 13.6 Ortam değişkenleri ve `.env` (bağlayıcı)

Kaynak: Temel L1488–L1545. **Sapmalar:** "anahtar ayarlandıktan sonra"
ölçüm satırı ve çocuk süreç profili (c) çıkarıldı; beklenen her ölçüm
noktasında **sıfır** eşleşmedir.

B yolunda hiçbir adım bir model sağlayıcısına bağlanmaz ve `manual-fact`
zinciri `.env` yüklemez; yine de `.env` ve ortam ölçümü **ağsızlık
kanıtının** parçasıdır (§21).

**(a) `.env` — içeriği okunmaz.** Dosya ya **mevcut değildir** ya da **tam 0
bayttır** (Temel L1501 birebir):

```powershell
if (Test-Path -LiteralPath "<repo-root>\.env") { "ENV_FILE_BYTES=$((Get-Item -LiteralPath "<repo-root>\.env" -Force).Length)" } else { "ENV_FILE=ABSENT" }
```

Beklenen: `ENV_FILE=ABSENT` veya `ENV_FILE_BYTES=0`. Boyut sıfırdan büyükse
**DUR** (H13). Dosya açılmaz, içeriği okunmaz; `.env` üzerinde değişiklik
bu runbook'un adımı **değildir**.

**(b) Üç kapsamda değişken adları — değerler okunmaz, basılmaz** (Temel
L1512–L1513 birebir):

```powershell
$pattern = '^(ANTHROPIC_.*|.*PROXY.*|SSL_.*|.*CA_BUNDLE.*|.*CA_CERTS.*|SSLKEYLOGFILE|PYTHONHTTPSVERIFY|PG.*)$'
foreach ($scope in 'Process', 'User', 'Machine') { $names = @([System.Environment]::GetEnvironmentVariables($scope).Keys | Where-Object { $_ -match $pattern } | Sort-Object); "ENV_SCOPE=$scope MATCH_COUNT=$($names.Count)"; foreach ($n in $names) { "ENV_NAME=$scope/$n" } }
```

| Ölçüm noktası | Process | User | Machine |
|---|---|---|---|
| Her içerik oturumunun başı, her `manual-fact` çağrısı öncesi ve kapanışta (zincir adım 28) | 0 eşleşme | 0 eşleşme | 0 eşleşme |

Herhangi bir eşleşme **DUR**'dur (H13). `VERGI_IAM_DATABASE_URL` ve
`PYTHONIOENCODING` bu desenin dışındadır ve beklenen değişkenlerdir.

**Dürüst sınır:** Windows'un kayıt defterindeki sistem proxy ayarı bu ad
taramasında görünmez. B yolunda hiçbir komut dış bağlantı kurmadığı için bu
ayar zincirin davranışını etkilemez; ağsızlık kanıtının sınırı §21'dedir.

### 13.7 Harness ve runtime paritesi — kaldırıldı

Temel §13.7'nin harness, monitor ve probe paritesi bu yolda yoktur (§29).
Runtime paritesi §13.3'e taşındı.

### 13.8 Yol kapısı (bağlayıcı)

Kaynak: Temel L1597–L1704. **Sapmalar:** `<external-root>` çocuk kümesi
`<evidence-dir>` ve `<restricted-dir>`'e indirildi; probe/inference
satırları çıkarıldı; Temel L1664'teki `Test-PilotExternalRoot` çağrısı
buna göre yeniden yazıldı. Fonksiyon tanımları **birebirdir**.

Bir yol şu koşulların **hepsini** sağlar: köklüdür ve kendi tam çözümüne
birebir eşittir; mevcut bir dizindir; kendisi ve sürücü köküne kadar bütün
üst dizinleri reparse point **değildir**; beklenen ebeveynin doğrudan alt
dizinidir. Kapı yalnız ad ve `PATH_OK` / `STOP PATH_FAIL` basar, yol
**basmaz**.

```powershell
function Test-PilotPath([string]$name, [string]$path, [string]$expectedParent) { $ok = $false; if ([System.IO.Path]::IsPathRooted($path) -and (Test-Path -LiteralPath $path -PathType Container)) { $full = [System.IO.Path]::GetFullPath($path).TrimEnd('\'); $item = Get-Item -LiteralPath $full -Force; $reparse = $false; $cur = $item; while ($cur -ne $null) { if ($cur.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $reparse = $true }; $cur = $cur.Parent }; $parentOk = ($expectedParent -eq '') -or (($item.Parent -ne $null) -and ($item.Parent.FullName.TrimEnd('\') -eq $expectedParent.TrimEnd('\'))); $ok = ($full -eq $path.TrimEnd('\')) -and (-not $reparse) -and $parentOk }; if ($ok) { "PATH_OK=$name" } else { "STOP PATH_FAIL=$name" } }
```

Repo kökü ve oturum konumu:

```powershell
$top = (git rev-parse --show-toplevel).Replace('/', '\')
if ((Get-Location).Path -eq "<repo-root>" -and $top -eq "<repo-root>" -and [System.IO.Path]::GetFullPath("<repo-root>").TrimEnd('\') -eq "<repo-root>") { "PATH_OK=repo-root" } else { "STOP PATH_FAIL=repo-root" }
Test-PilotPath 'cases-parent' "<repo-root>\data\cases" "<repo-root>\data"
```

Repo dışı dizinler (**sapma:** yalnız iki çocuk):

```powershell
Test-PilotPath 'external-root' "<external-root>" ''
Test-PilotPath 'evidence-dir' "<evidence-dir>" "<external-root>"
Test-PilotPath 'restricted-dir' "<restricted-dir>" "<external-root>"
```

Ortak yardımcılar (Temel L1638–L1641 birebir):

```powershell
function Test-PilotNoReparse([string]$full) { $cur = Get-Item -LiteralPath $full -Force; while ($cur -ne $null) { if ($cur.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $false }; if ($cur -is [System.IO.FileInfo]) { $cur = $cur.Directory } else { $cur = $cur.Parent } }; return $true }
function Test-PilotLeafFile([string]$path) { if (-not [System.IO.Path]::IsPathRooted($path)) { return $false }; if ([System.IO.Path]::GetFullPath($path) -ne $path) { return $false }; if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }; return (Test-PilotNoReparse $path) }
function Test-PilotOverlap([string]$a, [string]$b) { $x = ([System.IO.Path]::GetFullPath($a).TrimEnd('\') + '\').ToLowerInvariant(); $y = ([System.IO.Path]::GetFullPath($b).TrimEnd('\') + '\').ToLowerInvariant(); return ($x.StartsWith($y) -or $y.StartsWith($x)) }
function Test-PilotResolved([string]$p) { try { if ([string]::IsNullOrWhiteSpace($p) -or $p.Contains('<') -or $p.Contains('>') -or (-not [System.IO.Path]::IsPathRooted($p))) { return $false }; return ([System.IO.Path]::GetFullPath($p).TrimEnd('\') -eq $p.TrimEnd('\')) } catch { return $false } }
```

`Test-PilotOverlap` yalnız `try` içinde ve `Test-PilotResolved`'dan sonra
çağrılır. `Test-PilotResolved`, yol tanımsız, boş, hâlâ `<...>` biçiminde,
köksüz veya canonical çözümüne eşit değilse `False` döner.

**`<external-root>` sözleşmesi.** `<external-root>` mutlak ve canonical bir
dizindir; sürücü kökü **değildir**; `<repo-root>`'a eşit, onun altında veya
atası **değildir**; `<case-root>`, Temp kökü, `<python-runtime-root>` ve
`<pg-bin-dir>` ile örtüşmez. Doğrudan altında **yalnız** `<evidence-dir>` ve
`<restricted-dir>` yaprak adları bulunur; başka her öğe **DUR**'dur (H52).
Kapı her içerik oturumunun başında ve her durumda intake'ten **önce**
çalıştırılır. Fonksiyon Temel L1663 birebir; çağrı (**Temel L1664'ten
sapma:** çocuk listesi iki elemanlı):

```powershell
function Test-PilotExternalRoot([string]$ext, [string]$repo, [string[]]$children, [string[]]$protected) { $ErrorActionPreference = 'Stop'; try { if (-not (Test-PilotResolved $ext) -or -not (Test-PilotResolved $repo) -or ($children.Count -lt 1)) { return $false }; $e = $ext.TrimEnd('\'); if ($e -eq [System.IO.Path]::GetPathRoot($ext).TrimEnd('\')) { return $false }; if (-not (Test-Path -LiteralPath $e -PathType Container) -or -not (Test-PilotNoReparse $e) -or (Test-PilotOverlap $e $repo)) { return $false }; foreach ($p in $protected) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $e $p)) { return $false } }; $leaves = @(); foreach ($c in $children) { if (-not (Test-PilotResolved $c) -or ([System.IO.Path]::GetDirectoryName($c.TrimEnd('\')) -ne $e)) { return $false }; $leaves += [System.IO.Path]::GetFileName($c.TrimEnd('\')) }; if (@($leaves | Sort-Object -Unique).Count -ne $leaves.Count) { return $false }; $names = @(Get-ChildItem -LiteralPath $e -Force -ErrorAction Stop | ForEach-Object { $_.Name }); return (@($names | Where-Object { $leaves -cnotcontains $_ }).Count -eq 0) } catch { return $false } }
$extOk = Test-PilotExternalRoot "<external-root>" "<repo-root>" @("<evidence-dir>", "<restricted-dir>") @("<case-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")
if ($extOk -eq $true) { "PATH_OK=external-root-contract" } else { "STOP PATH_FAIL=external-root-contract" }
```

Dosya yolları (Temel L1680–L1682 birebir):

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
çalıştırılır. Beklenen: her satır için `PATH_OK` (veya intake öncesinde
`CASE_ROOT_ABSENT`). Herhangi bir `STOP` satırı **DUR**'dur (H52).

---

## 14. Elle tebliğ tarihi girişi (`manual-fact`) — YENİ

Bu bölüm temel runbook'ta karşılığı olmayan yeni bölümdür. Temel §15–§18'in
(maskeleme, egress, ağsız preview ve tek inference) yerine geçer.

### 14.1 İlke ve akış

- Tebliğ tarihi, operatörün yazdığı **tek** bir girdi dosyasından,
  modelsiz ve ağsız, **deterministik** bir pending extraction'a çevrilir
  (`src/manual_fact_entry_engine.py:1-27`). Aynı girdi her zaman aynı
  pending baytlarını üretir; kimliklerde zaman damgası yoktur
  (`src/manual_fact_entry_engine.py:442-500`).
- Üretilen fact her zaman `verification_state = "unverified"` taşır;
  manuel giriş **doğrulama değildir** (`src/manual_fact_entry_engine.py:16-19,
  479`). Doğrulama ayrı `verification` adımıdır (§15.3).
- Akış: girdi yazımı (§14.2) → avukatın karşılaştırması (§14.3) →
  assignment (§12.3) → preview (§14.4) → onaylar → apply (§14.5) → pending
  kontrolü ve promotion (§15).
- **Kural yerleri ve journal etkisi**
  (`ui/services/manual_fact_mutation_facade.py:20-23`): pre-lock (PL) ve
  kilit-altı precondition (PC) reddi **sıfır** journal satırı ve **sıfır**
  dosya bırakır; writer (W) hatası journal satırını
  `reconciliation_required` yapar ve case'i gate'ler (§14.6).
- **Writer yazım sırası** (`src/manual_fact_entry_engine.py:29-49, 690-717`):
  (1) geçici dosya `facts_llm_v1_3.json.pending.manual.tmp`; (2) tam dosya
  validator'ı; (3) generation audit (`O_CREAT|O_EXCL`, fsync); (4)
  `os.replace` ile pending; (5) diskten yeniden okunan pending hash'inin
  doğrulanması. Süreç hayattayken bir hata olursa writer **yalnız bu
  çağrıda kendi oluşturduğu** dosyaları geri alır. Bu sıra, exact-scope
  §2.7 hücre (c) ve §8/7'deki kalıcı "pending var / audit yok" penceresinin
  **yerini almıştır** (N-M1); exact-scope'un o iki satırı uygulanan kod için
  geçerli değildir.

### 14.2 Girdi dosyası (operatör, insan-only oturum)

**Yol (sabit; CLI'da yol argümanı yoktur):**
`<case-root>\documents\<document-id>\manual_input\manual_facts.input.json`
(`src/manual_fact_entry_engine.py:96-98`;
`ui/services/manual_fact_mutation_facade.py:535-539`). Operatör
`manual_input` dizinini ve dosyayı oluşturur. Bu dosya gerçek içeriktir
(§4.2), case dizininin parçasıdır ve onunla birlikte silinir veya
arşivlenir (§28).

**Alanlar** (`data/manual_fact_input.schema.json`; her düzeyde
`additionalProperties: false`, L11 ve L55):

| Alan | Tür ve kural | Kaynak |
|---|---|---|
| `schema_version` | Tamsayı, tam olarak `1` | schema L22-25; engine L303-304 |
| `case_id` | `^[a-z0-9_-]+$`, en az 3 karakter; `<case-id>`'ye birebir eşit | schema L27-31; facade L597-605 (M-13) |
| `document_id` | `^[a-z0-9_-]+$`, en az 3 karakter; `<document-id>`'ye ve belge dizini adına birebir eşit | schema L33-37; facade L606-614 (M-13) |
| `facts` | Dizi; **tam olarak 1** eleman | schema L39-47 (M-02) |
| `facts[0].role` | Tam olarak `notification_date` | schema L66-69 |
| `facts[0].date` | `YYYY-MM-DD`; gerçek bir takvim günü ve ISO biçimine birebir geri dönüş | schema L71-74; engine L331-342 (M-03) |
| `facts[0].page` | Tamsayı, ≥ 1 ve ≤ `document.json` `file.page_count` | schema L76-79; engine L313-314, L373-374 (M-04) |
| `facts[0].text_excerpt` | 1–500 karakter; en az bir boşluk-dışı karakter; **tek satır**; Unicode NFC; sekme dışında kontrol karakteri yok | schema L81-86; engine L318-326 (M-15) |

Bilinçli olarak **olmayan** alanlar: `verification_state`, `confidence`,
not/açıklama alanları (schema L7). Bu alanlardan biri eklenirse girdi
reddedilir (M-02).

**Kodlama** (`src/manual_fact_entry_engine.py:272-293`): katı UTF-8,
**BOM yok** (BOM varsa red), tekrarlanan JSON anahtarı yok (red,
L230-238), geçerli JSON.

**Şablon.** Değerler bilinçli olarak geçersiz bırakılmıştır: şablon
değiştirilmeden kullanılırsa `date` ve `page` şemadan, alıntı M-07/M-08'den
**reddedilir**:

```json
{
  "schema_version": 1,
  "case_id": "__CASE_ID__",
  "document_id": "__DOCUMENT_ID__",
  "facts": [
    {
      "role": "notification_date",
      "date": "__TEBLIG_TARIHI_YYYY-AA-GG__",
      "page": 0,
      "text_excerpt": "__BELGEDEN_BIREBIR_TEK_SATIR_ALINTI__"
    }
  ]
}
```

**Alıntı seçme kuralları (bağlayıcı):**

1. Alıntı `extracted/<document-id>.txt` metninde **birebir** geçmelidir.
   Karşılaştırma Unicode NFC ve "her boşluk dizisi tek boşluk + baş/son
   kırpma" normalizasyonundan sonra yapılır; **büyük/küçük harf
   duyarlıdır** (`src/manual_fact_entry_engine.py:251-256, 398-403`, kural
   M-07). Metindeki bir satır sonu tek boşluk sayılır; alıntı tek satır
   olarak yazılır.
2. Alıntı, tebliğ tarihini **`GG.AA.YYYY` veya `GG/AA/YYYY`** biçiminde
   taşımalıdır: iki haneli gün, iki haneli ay, dört haneli yıl, iki ayraç
   aynı ve ASCII rakam (`src/manual_fact_entry_engine.py:116-117`).
   `16.3.2026`, `16 Mart 2026` gibi biçimler **tanınmaz**; alıntıda
   tanınan tarih yoksa girdi **reddedilir** (M-08). Bu sınır teslimden önce
   Form G9 ile ve intake'te §11.3 (b) tarih token'ı ön kontrolüyle
   kapılanır.
3. Alıntıdaki **bütün** tanınan tarihlerin kümesi tam olarak `{date}`
   olmalıdır: alıntı tebliğ tarihinden **başka hiçbir tarih** içermez
   (aynı tarihin iki kez geçmesi kabul); geçersiz bir tarih token'ı da
   red sebebidir (`src/manual_fact_entry_engine.py:406-430`, kural M-08).
   Operatör tebliğ tarihini içeren ve başka tarih içermeyen bir cümle
   seçer.
4. Alıntı orijinal belgeden değil, `extracted` metinden kopyalanır; orijinal
   belgeyle karşılaştırma avukatındır (§14.3; exact-scope §8/5). Metinde
   tarih yanlış okunmuşsa doğru tarihle eşleşen bir alıntı bulunamaz:
   **DUR** (§14.5.3, §32).
5. Alıntı, `page` alanındaki sayfadan alınır. Kod sayfa ile alıntının
   aynı sayfada olduğunu **denetleyemez** (metin sayfalara bölünmüş
   değildir); bu yalnız avukatın karşılaştırmasıyla sağlanır (§14.3).

**Yazım aracı.** Dosya, insan-only oturumda, §4.3 (a)'daki altı kanal
sınıfından hiçbirine girmeyen yerel bir düz metin düzenleyicisiyle, BOM'suz
UTF-8 olarak yazılır. Düzenleyicinin adı evidence'a yazılır. Gerçek değerler
PowerShell komut satırına literal olarak **yazılmaz**.

**Ön kontrol** (YENİ; yalnız sabit sonuç basar; asıl doğrulama
`manual-fact`'in kendisidir; standart PowerShell/.NET davranışından gelir ve
§1.6 provasında doğrulanır). Bu oturumda §13.8 ve §10.5 ortak yardımcıları
**önce** tanımlanmış olmalıdır:

```powershell
$miPath = "<case-root>\documents\<document-id>\manual_input\manual_facts.input.json"
$miOk = $false
try { if (Test-PilotLeafFile $miPath) { $miBytes = [System.IO.File]::ReadAllBytes($miPath); $miBom = ($miBytes.Length -ge 3) -and ($miBytes[0] -eq 0xEF) -and ($miBytes[1] -eq 0xBB) -and ($miBytes[2] -eq 0xBF); $null = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($miBytes); $miOk = (-not $miBom) -and ($miBytes.Length -gt 0) } } catch { $miOk = $false }
Remove-Variable miBytes, miBom -ErrorAction SilentlyContinue
if ($miOk) { "MANUAL_INPUT_ENCODING=OK" } else { "STOP MANUAL_INPUT_ENCODING=FAIL" }
```

Beklenen: **`MANUAL_INPUT_ENCODING=OK`**. Başka her çıktı **DUR** (Y9).

### 14.3 Avukatın girdi karşılaştırması (iki kişi kuralı, K-12)

Sıra bağlayıcıdır: **önce** girdi sürümünün hash'i kaydedilir, **sonra**
avukat o sürümü karşılaştırır ve yazılı kararında sürüm numarasını ve hash
önekini anar, **en son** operatör kararın kayıtla eşleştiğini mekanik olarak
doğrular. Bu bölümdeki iki blok YENİ'dir (standart PowerShell/.NET; §1.6
provasında doğrulanır) ve bu oturumda §13.8 ve §10.5 ortak yardımcıları
**önce** tanımlanmış olmalıdır.

1. **Sürüm hash kaydı (operatör, avukat dosyayı görmeden hemen önce).**
   Aşağıdaki blok girdi dosyasının SHA-256'sını ölçer,
   `<evidence-dir>\manual-input-r<input-revision>.sha256.txt` dosyasına
   exclusive-create ile yazar ve ekrana **yalnız ilk 12 hex karakterini**
   basar (hash bir parmak izidir, içerik değildir; §32/16). İlk sürüm için
   `<input-revision>` = `1`; §14.5.3'teki girdi düzeltme döngüsünde her yeni
   sürüm bir sonraki sayıyı alır ve **en fazla `3`** olabilir (ilk sürüm +
   en fazla iki düzeltme). Blok `1`–`3` dışındaki bir değeri reddeder.
   Sürümler **sıralıdır** (O-e): `r<N>` yazılmadan önce `r1`…`r<N-1>`
   kayıtlarının **hepsi** mevcut, `r<N>`…`r3` kayıtlarının **hiçbiri**
   mevcut olmamalıdır; aksi hâlde (atlama veya ileri bir kayıt) blok yazmaz
   ve `STOP` basar. Önceki kayıtlar silinmez.

```powershell
$miPath = "<case-root>\documents\<document-id>\manual_input\manual_facts.input.json"
$miRec = "<evidence-dir>\manual-input-r<input-revision>.sha256.txt"
$miRecOk = $false; $miPrefix = $null; $miSeqOk = $false
try { if ("<input-revision>" -cmatch '^[1-3]\z') { $miRev = [int]"<input-revision>"; $miSeqOk = $true; for ($k = 1; $k -le 3; $k++) { $kExists = Test-Path -LiteralPath "<evidence-dir>\manual-input-r$($k).sha256.txt"; if ((($k -lt $miRev) -and -not $kExists) -or (($k -ge $miRev) -and $kExists)) { $miSeqOk = $false } } } } catch { $miSeqOk = $false }
try { if ($miSeqOk -and (Test-PilotLeafFile $miPath)) { $h = (Get-FileHash -LiteralPath $miPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant(); if (($h -cmatch '^[0-9a-f]{64}\z') -and (Write-PilotExclusive $miRec @("manual_input_sha256=$h"))) { $back = (New-Object System.Text.UTF8Encoding($false)).GetString([System.IO.File]::ReadAllBytes($miRec)); $miRecOk = ($back -ceq ("manual_input_sha256=" + $h + "`n")); if ($miRecOk) { $miPrefix = $h.Substring(0, 12) } } } } catch { $miRecOk = $false }
$h = $null
if ($miRecOk) { "MANUAL_INPUT_HASH_RECORDED=True"; "MANUAL_INPUT_REVISION=r<input-revision>"; "MANUAL_INPUT_SHA256_PREFIX=$miPrefix" } else { "STOP MANUAL_INPUT_HASH_RECORD=FAIL" }
Remove-Variable miPrefix -ErrorAction SilentlyContinue
```

   Beklenen: `MANUAL_INPUT_HASH_RECORDED=True`. Başka her çıktı (revizyon
   `3`'ü aşıyorsa veya sıra atlanmışsa dahil): **DUR** (Y10). Operatör sürüm numarasını ve
   12 karakterlik öneki avukata iletir; kayıttan sonra dosya **açılıp
   kaydedilmez**.

2. **Avukatın karşılaştırması.** Avukat, insan-only oturumda girdi
   dosyasını ekranda okur ve **orijinal belgeyle** karşılaştırır:
   - `date`, belgedeki tebliğ tarihiyle aynıdır;
   - `page`, tarihin geçtiği sayfadır;
   - `text_excerpt`, o sayfada birebir geçer ve tebliğ tarihinden başka
     tarih içermez;
   - `case_id` ve `document_id` bu dosyanın opak kimlikleridir.
3. **Yazılı karar** (`LEGAL_APPROVED`). Karar, karşılaştırılan sürümü
   **`r<input-revision>`** ve madde 1'deki **12 karakterlik hash önekiyle**
   açıkça anar. Yazılı kayıt repo dışında saklanır ve evidence'a yalnız
   SHA-256'sı girer. Sürüm veya önek kararda yoksa: **DUR** (Y10).
4. **Kararın kayıtla eşleştirilmesi ve yeniden doğrulama.** Aşağıdaki blok
   (a) dosyanın kayıttaki hash'le hâlâ aynı olduğunu ve (b) avukatın
   kararında andığı öneki (`<lawyer-cited-prefix>`, 12 küçük hex) kayıttaki
   hash'in ilk 12 karakteriyle karşılaştırır. Avukatın kararından hemen
   sonra **ve** her `manual-fact` preview ve apply öncesi, aynı
   `<input-revision>` ile çalıştırılır:

```powershell
$miPath = "<case-root>\documents\<document-id>\manual_input\manual_facts.input.json"
$miRec = "<evidence-dir>\manual-input-r<input-revision>.sha256.txt"
$miMatch = $false; $miCiteOk = $false
try { if ((Test-PilotLeafFile $miPath) -and (Test-PilotLeafFile $miRec)) { $txt = (New-Object System.Text.UTF8Encoding($false)).GetString([System.IO.File]::ReadAllBytes($miRec)); if ($txt -cmatch '^manual_input_sha256=[0-9a-f]{64}\n\z') { $recHash = $txt.Substring('manual_input_sha256='.Length, 64); $miMatch = [string]::Equals((Get-FileHash -LiteralPath $miPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant(), $recHash, [System.StringComparison]::Ordinal); $miCiteOk = ("<lawyer-cited-prefix>" -cmatch '^[0-9a-f]{12}\z') -and [string]::Equals($recHash.Substring(0, 12), "<lawyer-cited-prefix>", [System.StringComparison]::Ordinal) } } } catch { $miMatch = $false; $miCiteOk = $false }
Remove-Variable txt, recHash -ErrorAction SilentlyContinue
if ($miMatch -and $miCiteOk) { "MANUAL_INPUT_MATCHES_LAWYER_REVISION=True"; "LAWYER_DECISION_CITES_RECORD=True" } else { "STOP MANUAL_INPUT_MATCHES_LAWYER_REVISION=False" }
```

   Beklenen: iki satır da `True`. Başka her çıktı: **DUR** (Y10).

5. **İki kişi kuralı:** girdi dosyasını yazan ile bu karşılaştırmayı yapan
   **ayrı kişilerdir** (§4.1). Aynı kişiyse yalnız Form B4'teki açık kabulle
   ve `TWO_PERSON_CONTROL=WAIVED_B4` kaydıyla devam edilir; aksi **DUR**
   (Y4). Kod bu kuralı **zorlamaz** (§32).
6. Karşılaştırmanın yazılı sonucu yoksa, kayıt bloğu
   `MANUAL_INPUT_HASH_RECORDED=True` vermediyse veya madde 4'teki blok iki
   `True` satırını basmadıysa: `manual-fact` **çalıştırılmaz**, **DUR**
   (Y10).

### 14.4 Preview (APP oturumu, insan-only)

**Önkoşullar (bu oturumda, hepsi):** §4.3 (b) çıktıları; §13.8 yol
kapıları; §13.6 ad taraması **0** eşleşme; §11.3 (b) yeniden karşılaştırma
`SOURCE_HASHES_MATCH=True`; §14.3/4 `MANUAL_INPUT_MATCHES_LAWYER_REVISION=True` ve `LAWYER_DECISION_CITES_RECORD=True`;
§13.5 aktif assignment **1**, çözülmemiş journal satırı **0**; case journal
satır sayısı ölçüldü.

Preview salt-okunurdur: dış `read` yetkilendirmesinden sonra girdiyi ve
bağlı dosyaları değerlendirir, journal **okumaz ve yazmaz**, dosya
**yazmaz** (`ui/services/manual_fact_mutation_facade.py:652-681`).

```powershell
& "<python>" -m ui.cli_mutate manual-fact --case <case-id> --document <document-id> --actor-user-id <actor-user-id>
```

Kaynak: `ui/cli_mutate.py:529-546` (ayrıştırıcı), `ui/cli_mutate.py:1130-1153`
(kullanım kuralları: preview'da `--expected-input-digest` verilmez ve
`--attempt` varsayılan dışı olamaz; aksi çıkış `2`),
`ui/cli_mutate.py:1873-1890` (çıktı).

**Çıktı satırları ve kabul** (`ui/cli_mutate.py:1877-1890`):

| Satır öneki | İçerik | Kabul | Evidence'a |
|---|---|---|---|
| `PREVIEW manual-fact case_id=… document=…` | Opak kimlikler | `<case-id>`, `<document-id>` | Evet |
| `target_ref=` | `fact.<document-id>.pending` | Birebir | Evet |
| `input_digest=` | 64 küçük hex (girdi, şema, `case.json`, hedef `document.json`, metin dosyası ve bütün `documents/*/document.json` baytlarının manifest digest'i; `ui/services/manual_fact_mutation_facade.py:562-577`) | 64 küçük hex; `<expected-input-digest>` olarak kaydedilir | Evet |
| `pending_sha256=` | Üretilecek pending baytlarının SHA-256'sı | 64 küçük hex; `<pending-sha256>` olarak kaydedilir | Evet |
| `notification_date=` | **Gerçek tebliğ tarihi** | Avukatın §14.3 yazılı karşılaştırmasındaki tarihle birebir aynı | **Hayır** (yalnız `PREVIEW_DATE_MATCHES_LAWYER=True/False`) |
| `page=` | **Gerçek sayfa numarası** | §14.3'teki sayfa ile aynı | **Hayır** (yalnız `PREVIEW_PAGE_MATCHES_LAWYER=True/False`) |
| `excerpt_found=` | Başarıda her zaman `true` (`ui/services/manual_fact_mutation_facade.py:674`); bulunamayan alıntı `false` satırı değil, çıkış `1` hatasıdır (§14.5.3) | `true` | Evet |
| `text_excerpt_sha256=` | Alıntının UTF-8 baytlarının SHA-256'sı; alıntı metni **basılmaz** (K-18) | 64 küçük hex | Evet |
| `verification_state=unverified (…)` | Sabit satır | Mevcut | Evet (boolean) |
| `Uygulamak için: …` | Önerilen komut | **Kopyalanmaz, çalıştırılmaz** (§5/8) | Hayır |

**Ek kabul:** çıkış `0`; preview'dan önce ve sonra ölçülen case journal satır
sayısı **aynı** (H17). `<fact-id>` bu noktada `input_digest`'in ilk 12
karakterinden türetilir ve evidence'a yazılır (§1.5 tablo). Biri sağlanmazsa
apply bloğu **kullanılmaz**: **DUR**.

### 14.5 Apply (APP oturumu, insan-only, tek çalıştırma)

#### 14.5.1 Önkoşullar ve komut

**Önkoşullar (hepsi):** §14.4 kabul edildi; avukatın §14.3 yazılı kararı ve
hash'i evidence'ta; **`REAL_ACTION_APPROVED`** alındı ve
`<expected-input-digest>` değerine bağlandı; bu oturumda §11.3 (b)
`SOURCE_HASHES_MATCH=True`, §14.3/4 `MANUAL_INPUT_MATCHES_LAWYER_REVISION=True` ve `LAWYER_DECISION_CITES_RECORD=True`,
§13.6 **0** eşleşme yeniden ölçüldü; §26.3 baseline ölçüldü; §13.5
çözülmemiş journal satırı **0**.

İlk apply'da `<attempt>` = `1`. Varsayılan dışı değer yalnız §14.6 yolu
sonunda kullanılır.

```powershell
if (("<expected-input-digest>" -cnotmatch '^[0-9a-f]{64}\z') -or ("<attempt>" -cnotmatch '^[1-9][0-9]{0,2}\z')) { "STOP MANUAL_FACT_APPLY_ARGS=INVALID" } else { & "<python>" -m ui.cli_mutate manual-fact --case <case-id> --document <document-id> --actor-user-id <actor-user-id> --apply --expected-input-digest <expected-input-digest> --attempt <attempt> }
```

Kaynak: `ui/cli_mutate.py:529-546`, `ui/cli_mutate.py:1130-1153`
(`--apply` ⇒ 64 küçük hex `--expected-input-digest`, `--attempt` ≥ 1),
`ui/cli_mutate.py:1892-1906` (çıktı),
`ui/services/manual_fact_mutation_facade.py:817-1035` (sıra: argüman şekli →
dış `mutate` yetkilendirmesi → PL kuralları ve digest karşılaştırması →
bağlantı ve case kilidi → iç yetkilendirme → gate → idempotency → PC → journal
`prepared` → `executing` → writer).

#### 14.5.2 Beklenen çıktı ve kabul

Çıktı satırları (`ui/cli_mutate.py:1896-1906`):

| Satır öneki | Kabul | Evidence'a |
|---|---|---|
| `APPLIED manual-fact case_id=… document=…` | Opak kimlikler doğru | Evet |
| `pending_sha256=` | §14.4'teki `<pending-sha256>` ile **birebir** aynı (aynı girdi aynı baytları üretir; kilit altında ayrıca doğrulanır: `ui/services/manual_fact_mutation_facade.py:912-915`; writer sonrası: `src/manual_fact_entry_engine.py:704-708`) | Evet |
| `audit_file=` | `manual_<document-id>_` ile başlar, `.generation_audit.json` ile biter (`src/manual_fact_entry_engine.py:616-621`) | Evet (ad) |
| `journal_id=` | Pozitif tamsayı | Evet |
| `attempt=` | `<attempt>` ile aynı | Evet |
| `replayed=` | `False`. `True` normal yolda oluşmaz (tamamlanmış apply sonrası aynı komut M-09 ile pre-lock'ta reddedilir); görülürse **DUR** (Y11) | Evet |
| `Sonraki adım: …` | **Kopyalanmaz, çalıştırılmaz** (§5/8) | Hayır |

Ek kabul (hepsi):

- Çıkış `0`.
- §26.3: tam **1** yeni journal satırı; `state = 'completed'`;
  `action_family = 'generation.fact_manual'`; `actor_user_id` avukat aktörü.
- Disk durumu (YENİ, standart PowerShell; yalnız boolean basar; dosya adları
  `src/fact_approval.py:122` ve `src/manual_fact_entry_engine.py:88-94`):

```powershell
$extDir = "<case-root>\documents\<document-id>\extractions"
"PENDING_SHA_MATCH=$((Test-PilotLeafFile "$extDir\facts_llm_v1_3.json.pending") -and ((Get-FileHash -LiteralPath "$extDir\facts_llm_v1_3.json.pending" -Algorithm SHA256).Hash.ToLowerInvariant() -ceq '<pending-sha256>'))"
"TEMP_RESIDUE_ABSENT=$(-not (Test-Path -LiteralPath "$extDir\facts_llm_v1_3.json.pending.manual.tmp"))"
"CANONICAL_ABSENT=$(-not (Test-Path -LiteralPath "$extDir\facts.json"))"
```

  Beklenen: üçü de `True`.

- Audit kaydı (YENİ, L-6; standart PowerShell/.NET; yalnız boolean ve sayı
  basar, audit içeriği basılmaz; §1.6 provasında doğrulanır). `<audit-file>`
  apply'ın bastığı `audit_file=` değeridir. Blok (a) bu adın beklenen
  biçimde olduğunu, (b) `generation_reviews` altında normal bir dosya
  olarak bulunduğunu, (c) ayrıştırılabildiğini ve aile, kanal, sonuç ve
  pending hash alanlarının beklenen değerleri taşıdığını, (d) dizinde
  ayrıştırılamayan başka audit bulunmadığını ölçer. Alan adları
  `ui/services/manual_fact_mutation_facade.py:917-939` ve
  `src/manual_fact_entry_engine.py:679-681`'den gelir:

```powershell
$revDir = "<case-root>\documents\<document-id>\extractions\generation_reviews"
$u8s = New-Object System.Text.UTF8Encoding($false, $true)
$afName = "<audit-file>"
$afNameOk = ($afName -cmatch '^manual_[a-z0-9_-]+_[0-9]{8}_[0-9]{6}(_[0-9]+)?\.generation_audit\.json\z') -and $afName.StartsWith("manual_<document-id>_", [System.StringComparison]::Ordinal)
$afBound = $false; $auditListOk = $true; $auditUnparseable = 0
try { if ($afNameOk -and (Test-PilotLeafFile "$revDir\$afName")) { $aj = $u8s.GetString([System.IO.File]::ReadAllBytes("$revDir\$afName")) | ConvertFrom-Json -ErrorAction Stop; $afBound = ($aj -is [System.Management.Automation.PSCustomObject]) -and ($aj.action_family -ceq 'generation.fact_manual') -and ($aj.channel -ceq 'local_lawyer_manual_fact_cli') -and ($aj.outcome -ceq 'generated') -and ($aj.case_id -ceq '<case-id>') -and ($aj.document_id -ceq '<document-id>') -and ($aj.pending_sha256 -ceq '<pending-sha256>') } } catch { $afBound = $false }
try { $auditFiles = @(Get-ChildItem -LiteralPath $revDir -Force -ErrorAction Stop | Where-Object { $_.Name -clike '*.generation_audit.json' }) } catch { $auditListOk = $false; $auditFiles = @() }
foreach ($af in $auditFiles) { try { if ($af.PSIsContainer -or ($af.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { $auditUnparseable++; continue }; $x = $u8s.GetString([System.IO.File]::ReadAllBytes($af.FullName)) | ConvertFrom-Json -ErrorAction Stop; if (($null -eq $x) -or ($x -isnot [System.Management.Automation.PSCustomObject])) { $auditUnparseable++ } } catch { $auditUnparseable++ } }
"AUDIT_FILE_BOUND=$($afNameOk -and $afBound)"
"AUDIT_LIST_OK=$auditListOk"
"AUDIT_UNPARSEABLE_COUNT=$auditUnparseable"
Remove-Variable aj, x, af, auditFiles -ErrorAction SilentlyContinue
```

  Beklenen: `AUDIT_FILE_BOUND=True`, `AUDIT_LIST_OK=True`,
  `AUDIT_UNPARSEABLE_COUNT=0`. Bu blok idempotency anahtarı ve
  `pre_revision` bağını **ölçmez** (operatör bu değerleri görmez); o bağ
  kilit altında facade tarafından kurulur ve gerektiğinde §14.6 dry-run'ı ile
  bağımsız ölçülür. Bu PowerShell ayrıştırması Python `json.loads` ile
  birebir aynı değildir (§32/14).

Bunlardan biri sağlanmazsa: **DUR**; sonucu belirsiz bir apply **tekrar
çalıştırılmaz** (§27.2) ve durum §14.6 adım 1–3 ile ölçülür.

#### 14.5.3 Çıkış kodları, hata sınıfları ve her birinde yapılacak

**Çıkış kodunun okunması** (`ui/cli_mutate.py:141-143, 1190-1214,
1279-1292`):

| Gözlem | Anlamı | Journal etkisi |
|---|---|---|
| Çıkış `0` | Başarı | Preview: yok. Apply: 1 `completed` satır |
| Çıkış `2`, `usage:`/`error:` satırı | Kullanım hatası (argparse veya `manual-fact` kullanım kuralı); her bağlantıdan önce | Yok |
| Çıkış `1`, `ERROR: yetkisiz veya bilinmeyen case/actor/kayıt - erişim reddedildi …` | Yetkilendirme reddi (`ui/cli_mutate.py:152-155`) | Yok |
| Çıkış `1`, `ERROR: <Sınıf>: <mesaj>` | Tanınan alan hatası; aşağıdaki tablo | Tabloya göre |
| `Traceback (most recent call last):` ile başlayan stderr | **Tanınmayan hata**; ham traceback (`ui/cli_mutate.py:1289-1290`). Python'un kendi çıkış kodu da `1`'dir; bu yüzden çıkış kodu tek başına ayırt etmez | **Belirsiz** (L-E; aşağıda) |

Evidence'a yalnız çıkış kodu, **sınıf adı** ve mesajdaki **kural kodu**
(ör. `M-08`) yazılır; mesajın geri kalanı ve traceback yazılmaz (§4.2/8).

**Hata sınıfları** (`ui/services/manual_fact_mutation_facade.py:117-220`;
motor kural kodları `src/manual_fact_entry_engine.py:160-213`; mesaj
biçimi `Manuel fact girişi reddedildi (kural M-xx; <MotorSınıfı>)`,
facade L211-220). "Yer": PL = pre-lock, PC = kilit altı precondition,
W = writer, K = coordinator.

| Sınıf (`ERROR:` satırında) | Kural | Yer | Journal | Yapılacak |
|---|---|---|---|---|
| `ManualFactArgumentError` | Argüman şekli | PL | Yok | **DUR**. CLI zaten aynı kuralları uygular (§14.4); bu satır runbook komutunun bozulduğunu gösterir |
| (yetkilendirme reddi satırı) | — | PL | Yok | **DUR**. §13.5 assignment ve kullanıcı ölçümleri |
| `ManualFactInputContainmentError` | M-01 | PL/PC | Yok | **DUR**. Girdi/case/belge yolunda eksik dosya, link/junction veya alias var (§11.2/10). Düzeltme kullanıcı kararıdır |
| `ManualFactInputInvalidError` | M-02, M-03, M-15 | PL/PC | Yok | **DUR** → girdi düzeltme döngüsü (aşağıda). Mesaj "Repo şema dosyaları okunamadı" veya "case.json geçerli JSON değil" diyorsa döngü **uygulanmaz**: DUR |
| `ManualFactDocumentIneligibleError` | M-04 | PL/PC | Yok | **DUR**. `page_count` boş/geçersizse intake düzeltmesi (aşağıda); `page` > `page_count` ise girdi düzeltme döngüsü |
| `ManualFactDocumentIneligibleError` | M-05 | PL/PC | Yok | **DUR**. Belge türü veya `active` yanlış: Form G4 / intake ile çelişki; kullanıcı ve avukat kararı |
| `ManualFactSourceTextUnavailableError` | M-06 | PL/PC | Yok | **DUR**. Metin dosyası yok, boş veya geçersiz UTF-8. Metin intake'te hash'lenmiştir (§11.3 b) ve kayıt yeniden yazılamaz: bu çalıştırmada düzeltilmez |
| `ManualFactExcerptRejectedError` | M-07 | PL/PC | Yok | **DUR** → girdi düzeltme döngüsü (alıntı metinde birebir yok) |
| `ManualFactExcerptRejectedError` | M-08 | PL/PC | Yok | **DUR** → girdi düzeltme döngüsü (alıntıda tanınan tarih yok, farklı/ikinci tarih var veya geçersiz tarih token'ı). Metinde tarih yanlış okunmuşsa döngü çözmez: DUR |
| `ManualFactPendingExistsError` | M-09 | PL/PC | Yok | **DUR**. Mesaj son journal satırının `id` ve `state` değerini gösterir (`ui/services/manual_fact_mutation_facade.py:504-515`). İlk apply'da beklenmez; tamamlanmış bir apply'dan sonra aynı komut bunu verir (yeniden çalıştırılmaz) |
| `ManualFactCanonicalExistsError` | M-10 | PL/PC | Yok | **DUR**. Bu belge için canonical zaten var |
| `ManualFactCandidateInvalidError` | M-11a | PL/PC | Yok | **DUR**. Programlama düzeyi; düzeltme denenmez |
| `ManualFactIdentityMismatchError` | M-13 | PL/PC | Yok | **DUR**. Fark girdi dosyasındaysa girdi düzeltme döngüsü; `case.json`/`document.json`/dizin adındaysa intake düzeltmesi (kullanıcı ve avukat kararı) |
| `ManualFactTempResidueError` | M-14 | PL/PC | Yok | **DUR** → §14.6. Önceki bir sert çöküşün artığı; kod onu **silmez** (`ui/services/manual_fact_mutation_facade.py:516-520`) |
| `StaleViewError` | M-12 | PL/PC | Yok | **DUR**. Preview'dan sonra girdi veya bağlı dosyalardan biri değişti. §14.3 yeniden doğrulama ve §11.3 (b) ile neyin değiştiği ölçülür; yeni preview yeni digest ve **yeni** `REAL_ACTION_APPROVED` ister |
| `PreconditionRaceDetectedError` | M-12 | PC | Yok | **DUR**. Kilit beklenirken bir dosya değişti; tek operatörlü pilotta beklenmez |
| `ManualFactResolvedCaseIdMismatchError` | — | Yetkilendirme | Yok | **DUR** |
| `ResourceGatedError` | — | K | Yeni satır yok | **DUR** → §14.6. Case'te `prepared`/`executing`/`reconciliation_required` satır var |
| `PriorAttemptFailedError` | — | K | Yeni satır yok | **DUR** → §14.6. Bu `<attempt>` değeri için `failed` satır zaten var |
| `IdempotencyConflictError` | — | K | Yeni satır yok | **DUR** |
| `JournalExecutingTransitionFailedError` | — | K | `prepared` satırı kalabilir | **DUR** → §14.6 |
| `JournalCompletionUncertainError` | — | K | `executing` satırı kalabilir | **DUR** → §14.6 |
| `ManualFactWriteFailedError` | M-11b / G/Ç | **W** | `reconciliation_required`; **case gate'li** | **DUR** → §14.6. Mesaj `journal_id=… state=…` ve parantez içinde kök hata sınıfını taşır (`ui/services/manual_fact_mutation_facade.py:955-993`) |
| `ManualFactAuditBindingVerificationFailedError` | — | Replay | Satır `completed`, kanıt tutmuyor | **DUR** → §14.6 adım 1–4 (yalnız ölçüm) |
| Traceback: `ManualFactPostWriteInvariantError` | — | **W** | `reconciliation_required` | **DUR** → §14.6. Bilinçli olarak tanınan sınıf **değildir**; ham traceback verir (`src/manual_fact_entry_engine.py:209-213`; facade L953-954) |
| Traceback: başka herhangi bir sınıf | — | Herhangi biri | **Belirsiz** | **DUR** → §14.6 adım 1–3. L-E: writer yalnız motor hatalarını, `OSError`, `ValueError` ve containment hatasını tanınan sınıfa çevirir (facade L955-959); writer içinde oluşan başka bir istisna (ör. validator'dan `KeyError`/`TypeError`) satırı `reconciliation_required` bırakıp **ham traceback** olarak görünür. Veritabanı bağlantı hatası da traceback verir ama satır bırakmaz. Ayrım yalnız §14.6 adım 2'deki SQL ile yapılır |

**Girdi düzeltme döngüsü (bağlayıcı).** Yalnız yukarıda "girdi düzeltme
döngüsü" yazan satırlar için ve **yalnız** journal satırı oluşmamışsa:

1. DUR kaydı yazılır (sınıf + kural kodu).
2. Avukat düzeltmeye **yazılı** olarak karar verir (`LEGAL_APPROVED`);
   operatör kendi başına düzeltmez.
3. Operatör **yalnız** girdi dosyasını düzeltir; `case.json`,
   `document.json` ve metin dosyası bu döngüde değiştirilmez.
4. §14.2 ön kontrolü (`MANUAL_INPUT_ENCODING=OK`).
5. §14.3 baştan, aynı sırayla: `<input-revision>` bir artırılarak **önce**
   yeni hash kaydı, **sonra** avukatın yeni yazılı kararı (yeni sürüm ve
   önekle), en son eşleştirme bloğu. Önceki sürümün onayı geçersizdir.
6. Yeni preview (§14.4); önceki `<expected-input-digest>` ve ona bağlı
   kullanıcı onayı geçersizdir.

**Sayı sınırı (bağlayıcı):** döngü bu pilotta en fazla **iki** kez
uygulanır (`<input-revision>` en fazla `3`; §14.3/1'deki blok `4`'ü
reddeder). Üçüncü bir düzeltme gereği: **DUR**, kullanıcı ve avukat kararı
(Y10).

**Intake düzeltmesi** (`page_count`, kimlik alanları): yalnız
`document.json` / `case.json` alanı için, avukatın o alanı §11.4'e göre
yeniden yazılı onaylaması, §11.2/3 ve §11.2/5 kontrolleri ve §11.3 (c), (d)
validator'larının yeniden PASS vermesiyle. Metin dosyası ve orijinal belge
bu yolla **değiştirilemez** (hash kayıtları yeniden yazılamaz; §11.3 b).

Bu iki yol dışındaki her DUR, §14.6 veya §25.2'ye gider.

### 14.6 Reconciliation ve `--attempt` ile yeniden deneme (L-A)

**Ne zaman:** `ManualFactWriteFailedError`, `ManualFactTempResidueError`,
`ResourceGatedError`, `PriorAttemptFailedError`,
`JournalExecutingTransitionFailedError`, `JournalCompletionUncertainError`,
`ManualFactAuditBindingVerificationFailedError` veya traceback. Bu yol
temel runbook'ta **yoktur**; her adımı ayrı onaylıdır ve **otomatik değildir**.

**1. Durdur.** Yeni mutasyon yapılmaz; apply tekrar çalıştırılmaz.

**2. Journal ölçümü** (§13.5 biçimiyle, APP oturumu):

```sql
SELECT id, state, action_family, target_ref FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>' AND state IN ('prepared', 'executing', 'reconciliation_required') ORDER BY id;
```

```sql
SELECT id, state FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>' AND action_family = 'generation.fact_manual' ORDER BY id;
```

Çözülmemiş satır yoksa ve `id`'si o apply'dan önce ölçülen
`<baseline-max-id>`'den büyük olan bir `generation.fact_manual` satırı
`completed` ise apply başarılı olmuş olabilir; bu ancak §22.3'ün dört
koşulu ve §14.5.2 disk kontrolleri sağlanırsa başarı sayılır ve §15 ile
devam edilir. Çözülmemiş satır yoksa ve yeni satır da yoksa (ör. bağlantı
hatası traceback'i) hiçbir şey yazılmamıştır; **DUR** ve kullanıcı kararı.
Çözülmemiş satır birden fazlaysa: **DUR**, kullanıcı kararı.
Tek çözülmemiş satır varsa onun `id`'si `<journal-id>`'dir.

**3. Disk ölçümü — yalnız boolean ve sayı basar (L-A).** Audit dosyalarının
her biri ayrıştırılmaya çalışılır; içerik basılmaz. Blok YENİ'dir (standart
PowerShell/.NET; dosya adları `src/fact_approval.py:122`,
`src/manual_fact_entry_engine.py:88-100`; §1.6 provasında doğrulanır):

```powershell
$extDir = "<case-root>\documents\<document-id>\extractions"
$revDir = "$extDir\generation_reviews"
$u8s = New-Object System.Text.UTF8Encoding($false, $true)
"PENDING_PRESENT=$(Test-Path -LiteralPath "$extDir\facts_llm_v1_3.json.pending")"
"TEMP_RESIDUE_PRESENT=$(Test-Path -LiteralPath "$extDir\facts_llm_v1_3.json.pending.manual.tmp")"
$auditFiles = @(); $auditListOk = $true
try { if (Test-Path -LiteralPath $revDir) { $auditFiles = @(Get-ChildItem -LiteralPath $revDir -Force -ErrorAction Stop | Where-Object { $_.Name -clike '*.generation_audit.json' }) } } catch { $auditListOk = $false }
$auditUnparseable = 0
foreach ($af in $auditFiles) { try { if ($af.PSIsContainer -or ($af.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { $auditUnparseable++; continue }; $aj = $u8s.GetString([System.IO.File]::ReadAllBytes($af.FullName)) | ConvertFrom-Json -ErrorAction Stop; if (($null -eq $aj) -or ($aj -isnot [System.Management.Automation.PSCustomObject])) { $auditUnparseable++ } } catch { $auditUnparseable++ } }
"AUDIT_LIST_OK=$auditListOk"
"AUDIT_FILE_COUNT=$($auditFiles.Count)"
"AUDIT_UNPARSEABLE_COUNT=$auditUnparseable"
Remove-Variable aj, af, auditFiles -ErrorAction SilentlyContinue
```

- **`AUDIT_UNPARSEABLE_COUNT` > 0 veya `AUDIT_LIST_OK=False`: DUR — yeniden
  deneme YAPILMAZ.** Ayrıştırılamayan tek bir audit (ör. yazımı sırasında
  güç kesintisiyle yarım kalmış dosya; engine yarım audit'i yalnız süreç
  hayattayken siler, L633-639) bu belgenin `generation_reviews`
  dizinindeki post-state kanıtını **her iki aile için kalıcı olarak**
  `False` yapar (`ui/services/manual_fact_mutation_adapters.py:279-280`;
  facade replay L779-780). Repoda bunu çözen bir araç **yoktur**. Dosyanın
  kaldırılması ayrı kullanıcı kararı ve ayrı inceleme gerektiren, bu
  runbook'ta tanımlı **olmayan** bir silme işlemidir.
- Bu PowerShell ayrıştırması Python `json.loads` ile birebir aynı değildir;
  yalnız ön kontroldür. Bağlayıcı sonuç adım 4'teki dry-run'dır.

**4. Reconciliation dry-run** (APP oturumu; sıfır UPDATE;
`ui/reconciliation_operator.py:14-21`):

```powershell
& "<python>" -m ui.reconciliation_operator --journal-id <journal-id>
```

Çıktı (`ui/reconciliation_operator.py:304-308, 362-383`):
`DRY RUN journal_id=<journal-id> (…)` ve ardından
`  new_state=… resolution_code=… observed_post_hash=…`. Çıkış kodları:
`0` rapor üretildi, `1` bilinen reconciliation hatası, `2` kullanım
(`ui/reconciliation_operator.py:110-112`).

Karar (`ui/services/manual_fact_mutation_adapters.py:30-32`;
`src/manual_fact_entry_engine.py:37-40`):

| Disk durumu | Beklenen `new_state` | Sonraki adım |
|---|---|---|
| Pending yok (temp ve/veya ayrıştırılabilir audit olabilir) | `failed` | Adım 5, ardından adım 6–7 |
| Pending var, sha'sı ve tam bağlamalı tek audit tutuyor | `completed` | Adım 5; ardından §14.5.2 disk kontrolleri ve §15 (apply aslında tamamlanmıştır) |
| Başka her durum veya `new_state=reconciliation_required` | Kesin kanıt yok | **DUR**. Apply yapılmaz; case gate'li kalır; kullanıcı kararı (§32) |

**5. Reconciliation apply** (ayrı **`REAL_ACTION_APPROVED`**, bir kez):

```powershell
& "<python>" -m ui.reconciliation_operator --journal-id <journal-id> --apply --actor-ref <reconcile-actor-ref>
```

Beklenen: çıkış `0`, `APPLIED journal_id=<journal-id> resolved_by_actor_type=cli_service resolved_by_actor_ref=<reconcile-actor-ref>`
ve `new_state` dry-run ile **aynı**. Farklıysa: **DUR**. Ardından §13.5 ile
çözülmemiş satır sayısı **0** doğrulanır. Bu CLI pilot kümesinde henüz hiç
çalıştırılmamıştır (§32).

**6. Temp artığı (yalnız `TEMP_RESIDUE_PRESENT=True` ise).** Kod onu
silmez. Kaldırma yalnız adım 5 apply'ından sonra, ayrı
**`REAL_ACTION_APPROVED`** ile ve **bir kez** yapılır. Aşağıdaki guard
şunların **hepsini** mekanik olarak ölçmeden silmez:

- journal satırı `<journal-id>`, bu case ve `generation.fact_manual` için
  veritabanında `state = 'failed'` (adım 5'in `new_state=failed` sonucu;
  §13.5 salt-okunur çağırma biçimiyle, APP oturumunda);
- `generation_reviews` listelenebiliyor ve `AUDIT_UNPARSEABLE_COUNT=0`;
- pending yok; artık normal bir dosya ve SHA-256'sı `<pending-sha256>` ile
  **birebir aynı**. SHA uyuşmuyorsa artık bu apply'ın dondurulmuş adayı
  değildir: silme yapılmaz, **DUR** (Y13).

Blok YENİ'dir (standart PowerShell/.NET ve §13.5 `psql` biçimi; §1.6
provasında PASS ve FAIL dalları doğrulanır); bu oturumda §13.8 yardımcıları
**önce** tanımlanmış ve `Test-PilotExe 'psql'` `PATH_OK` vermiş olmalıdır:

```powershell
$extDir = "<case-root>\documents\<document-id>\extractions"
$tmp = "$extDir\facts_llm_v1_3.json.pending.manual.tmp"
$revDir = "$extDir\generation_reviews"
$tmpGuard = $false; $rcFailed = $false; $listOk = $false; $unp = -1; $tmpShaOk = $false
try {
    $u8s = New-Object System.Text.UTF8Encoding($false, $true)
    if ("<journal-id>" -cmatch '^[1-9][0-9]{0,18}\z') {
        $rcOut = @(& "<psql>" --dbname="$env:VERGI_IAM_DATABASE_URL" --no-password --no-psqlrc -v ON_ERROR_STOP=1 -q -A -t -c "BEGIN TRANSACTION READ ONLY" -c "SHOW transaction_read_only" -c "SELECT state FROM mutation.mutation_journal WHERE id = <journal-id> AND resource_key = 'case:<case-id>' AND action_family = 'generation.fact_manual'" -c "ROLLBACK")
        $rcFailed = ($LASTEXITCODE -eq 0) -and ($rcOut.Count -eq 2) -and ($rcOut[0] -ceq 'on') -and ($rcOut[1] -ceq 'failed')
    }
    $listOk = $true; $unp = 0; $afs = @()
    try { if (Test-Path -LiteralPath $revDir) { $afs = @(Get-ChildItem -LiteralPath $revDir -Force -ErrorAction Stop | Where-Object { $_.Name -clike '*.generation_audit.json' }) } } catch { $listOk = $false }
    foreach ($af in $afs) { try { if ($af.PSIsContainer -or ($af.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { $unp++; continue }; $aj = $u8s.GetString([System.IO.File]::ReadAllBytes($af.FullName)) | ConvertFrom-Json -ErrorAction Stop; if (($null -eq $aj) -or ($aj -isnot [System.Management.Automation.PSCustomObject])) { $unp++ } } catch { $unp++ } }
    $tmpLeafOk = (Test-PilotLeafFile $tmp) -and ([System.IO.Path]::GetFileName($tmp) -ceq 'facts_llm_v1_3.json.pending.manual.tmp') -and (-not (Test-Path -LiteralPath "$extDir\facts_llm_v1_3.json.pending"))
    $tmpShaOk = $tmpLeafOk -and ((Get-FileHash -LiteralPath $tmp -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -ceq '<pending-sha256>')
    $tmpGuard = $rcFailed -and $listOk -and ($unp -eq 0) -and $tmpShaOk
}
catch {
    $tmpGuard = $false
}
"JOURNAL_ROW_STATE_FAILED=$rcFailed"
"AUDIT_LIST_OK=$listOk"
"AUDIT_UNPARSEABLE_COUNT=$unp"
"TEMP_RESIDUE_SHA_MATCHES_PREVIEW=$tmpShaOk"
if ($tmpGuard -eq $true) { try { Remove-Item -LiteralPath $tmp -Force -ErrorAction Stop; "TEMP_RESIDUE_REMOVED=True" } catch { "STOP TEMP_RESIDUE_REMOVE=FAIL" } } else { "STOP TEMP_RESIDUE_GUARD=FAIL" }
"TEMP_RESIDUE_PRESENT=$(Test-Path -LiteralPath $tmp)"
Remove-Variable rcOut, afs, af, aj -ErrorAction SilentlyContinue
```

Beklenen, hepsi birlikte: `JOURNAL_ROW_STATE_FAILED=True`,
`AUDIT_LIST_OK=True`, `AUDIT_UNPARSEABLE_COUNT=0`,
`TEMP_RESIDUE_SHA_MATCHES_PREVIEW=True`, `TEMP_RESIDUE_REMOVED=True` ve
`TEMP_RESIDUE_PRESENT=False`. Başka her sonuç: silme yapılmaz veya yarım
kalmıştır, **DUR** (Y13); tekrar denenmez.

**7. Yeniden deneme kararı.** `--attempt <N+1>` **yalnız** şunların
hepsi sağlanırsa:

- adım 5 `new_state=failed` verdi ve çözülmemiş satır **0**;
- `PENDING_PRESENT=False`, `TEMP_RESIDUE_PRESENT=False`,
  `AUDIT_UNPARSEABLE_COUNT=0`;
- kök hata **geçici G/Ç** sınıfındandır (`ManualFactWriteFailedError`
  mesajında parantez içi `OSError`/`PermissionError`; ya da
  `JournalExecutingTransitionFailedError`/`JournalCompletionUncertainError`).
  Kök hata validator kaynaklıysa (`ManualFactWriteError`, `ValueError`,
  `FileNotFoundError`) aynı girdi aynı sonucu verir: yeniden deneme
  **yapılmaz**, **DUR**;
- §14.3/4 bloğu ve §11.3 (b) bu oturumda `True`; yeni preview
  (§14.4) **aynı** `input_digest` ve **aynı** `pending_sha256`'yı bastı;
- ayrı **`REAL_ACTION_APPROVED`** alındı.

Komut §14.5.1'deki apply bloğudur; `<expected-input-digest>` **aynı** kalır
(`attempt` `input_digest`'e girmez: `ui/services/manual_fact_mutation_facade.py:562-577, 861`),
`<attempt>` bir artırılır. Aynı `<attempt>` ile tekrar
`PriorAttemptFailedError` verir ve yeni satır açılmaz
(`ui/services/mutation_coordinator.py:178-200`). **Bu pilotta en fazla bir
yeniden deneme** (`<attempt>` = `2`) yapılır; ikinci başarısızlık **DUR** ve
kullanıcı kararıdır (§33).

**8. Kanıt yorumlama.** `failed` bir journal satırının yanında kalan audit
dosyası **başarı kanıtı değildir** (§22.2).

### 14.7 `fact_extraction` bu runbook'ta ASLA çalıştırılmaz (K-14)

**`generation --row-key fact_extraction` — preview dahil — bu runbook'un
hiçbir adımında, hiçbir koşulda çalıştırılmaz.** Görülürse veya
çalıştırıldığından şüphe edilirse: **DUR** (Y14).

- Bu aile bir model sağlayıcısına bağlanır ve anahtar ister; B yolunun
  tanımı dışındadır (§1.2).
- LLM ailesi, mevcut bir pending'i — manuel olanı dahil — kendi
  `history/` dizinine taşıyabilir (`src/fact_extraction_engine.py:700`,
  `preserve_previous_pending`; exact-scope §8/3). Bu, `generation.fact_manual`
  satırının post-state kanıtını reconcile edilemez kılar.
- Kod bunu engelleyen bir guard **taşımaz**; tek koruma bu DUR satırıdır
  (§32).
- Kapanışta mekanik olarak ölçülür (§21):

```sql
SELECT count(*) FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>' AND action_family = 'generation.fact_extraction';
```

  Beklenen: `0`.

---

## 15. Pending kontrolü, fact promotion ve verification

### 15.1 Pending içerik kontrolü

Kaynak: Temel L2638–L2660. **Sapmalar:** "her fact'i orijinal belgeyle
karşılaştır" kuralı tek manuel fact'e uyarlandı; mekanik yöntem kontrolü ve
pending adı notu eklendi.

**Pending adı provenance değildir (K-13).** Pending dosyasının adı
`facts_llm_v1_3.json.pending`'dir ve "llm" der; içerik `extractor.method =
"manual"` taşır. Ad, promotion zincirinin aradığı sabittir
(`src/fact_approval.py:122`; `src/manual_fact_entry_engine.py:85-88`).
**Otorite içerik + generation audit + journal'dır** (exact-scope §8/1):
`extractor.method`, `generation_reviews/manual_<document-id>_….generation_audit.json`
(`action_family = generation.fact_manual`,
`channel = local_lawyer_manual_fact_cli`) ve `generation.fact_manual`
journal satırı.

Mekanik kontrol (yalnız boolean basar):

```powershell
$pend = (New-Object System.Text.UTF8Encoding($false, $true)).GetString([System.IO.File]::ReadAllBytes("<case-root>\documents\<document-id>\extractions\facts_llm_v1_3.json.pending")) | ConvertFrom-Json
"PENDING_METHOD_MANUAL=$($pend.extractor.method -ceq 'manual')"
"PENDING_PROVIDER_MODEL_NULL=$(($null -eq $pend.extractor.provider) -and ($null -eq $pend.extractor.model))"
"PENDING_FACT_COUNT_ONE=$(@($pend.facts).Count -eq 1)"
"PENDING_ALL_UNVERIFIED=$(@($pend.facts | Where-Object { $_.verification_state -cne 'unverified' }).Count -eq 0)"
"PENDING_FACT_ID_MATCH=$((@($pend.facts).Count -eq 1) -and ($pend.facts[0].fact_id -ceq '<fact-id>'))"
"PENDING_LOCATOR_PRESENT=$((@($pend.facts).Count -eq 1) -and ($null -ne $pend.facts[0].source.page) -and (([string]$pend.facts[0].source.text_excerpt).Trim().Length -gt 0))"
Remove-Variable pend -ErrorAction SilentlyContinue
```

Beklenen: altısı da `True` ve §14.5.2 `PENDING_SHA_MATCH=True`. Aksi
**DUR** (Y12). Kaynak: `src/manual_fact_entry_engine.py:450-500`
(`method`, `provider`, `model`, tek fact, `unverified`, `source.page` ve
`source.text_excerpt`).

Avukat, pending'deki tek fact'i (`statement`, `source.page`,
`source.text_excerpt`, `structured_values[0].date_value`) ekranda okur ve
§14.3'te onayladığı girdiyle aynı olduğunu **yazılı** kabul eder (fact
kabulü). Fact bazında düzeltme yazıcısı yoktur; farklılık görülürse
promotion **yapılmadan DUR** (H18). Pending dosyası **elle düzenlenmez**.

### 15.2 Fact promotion (APP oturumu)

Kaynak: Temel L2662–L2683. **Sapma:** `validation_ready` kapısı eklendi
(K-16).

Preview:

```powershell
& "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key fact --document <document-id> --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; `pending_hash=` satırı `<pending-sha256>` ile aynı
ve `<expected-hash>` olarak kaydedildi; `canonical_exists=False`;
**`validation_ready=True`** (`ui/cli_mutate.py:1336-1380`). Promotion,
`method=manual` dahil **her** yöntemde `unverified` dışı fact'i reddeder
(`src/fact_approval.py:429-449`, K-3) ve geçersiz bir fact pending'ini
pre-lock'ta, **sıfır journal satırıyla** `PromotionPendingInvalidError`
olarak reddeder (`ui/services/promotion_mutation_facade.py:222-241, 840-844,
933-936`, K-16). §15.1 kabulü, avukatın yazılı kabulü
(`LEGAL_APPROVED`), ayrı **`REAL_ACTION_APPROVED`** ve §26.3 baseline
alınmış olmalıdır. Biri eksikse apply bloğu kullanılmaz: **DUR**.

Apply (tek çalıştırma; Temel L2678 birebir):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}\z') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key fact --document <document-id> --actor-user-id <actor-user-id> --approve --expected-hash <expected-hash> }
```

`--discard-verified-states` ve `--note` bu pilotta **kullanılmaz** (H35,
§10.3). Beklenen journal: 1 yeni `completed` `promotion.fact` satırı.

### 15.3 Tebliğ fact'inin verification'ı

Kaynak: Temel L2685–L2727. **Sapmalar:** `<fact-id>` türetimi; avukatın
§14.3 karşılaştırmasının verification kararının yerine geçmediği notu.

Yalnız `<fact-id>` `verified` yapılır. Kaynaktaki ön koşullar
(`ui/services/fact_verification_mutation_facade.py`): `--evidence-ref`
fact'in kaynak belgesidir (`<document-id>`); evidence belgesinin `active`
değeri tam olarak `true`; `verified` hedefi için fact'in `source` nesnesi
locator taşır (manuel fact'te `page` ve `text_excerpt` yapı gereği doludur);
self-transition reddedilir.

**Approval ≠ verification (`CLAUDE.md` §3 Prensip 5).** Avukatın §14.3
karşılaştırması ve §15.1 fact kabulü bu kararın **yerine geçmez**. Avukat
verification kararını **ayrı ve yazılı** olarak verir; kararda locator'ın
gösterdiği yeri (sayfa ve alıntı) orijinal belgeyle karşılaştırdığını
belirtir. İki kişi kuralı (§4.1) burada da geçerlidir. Biri yoksa
verification **uygulanmaz**: **DUR** (H45).

Preview:

```powershell
& "<python>" -m ui.cli_mutate verification --case <case-id> --document <document-id> --fact-id <fact-id> --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı hash `<expected-hash>` olarak kaydedildi;
yukarıdaki koşullar sağlandı; avukatın yazılı verification kararı
(`LEGAL_APPROVED`) ve ayrı **`REAL_ACTION_APPROVED`** alındı; §26.3 baseline
ölçüldü. Biri eksikse: **DUR**.

Apply (tek çalıştırma; Temel L2720 birebir):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}\z') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate verification --case <case-id> --document <document-id> --fact-id <fact-id> --actor-user-id <actor-user-id> --apply --target-state verified --expected-hash <expected-hash> --evidence-ref <document-id> }
```

Verification sonrası basılan downstream rehberinden bu pilotta yalnız §16 ve
§18 adımları koşulur; `qa` ve `case_view` koşulmaz (§3).

---

## 16. Timeline generation ve promotion

Kaynak: Temel L2731–L2771. Sapma yok (yalnız bölüm atıfları). Timeline,
manuel fact'i `Tebliğ Tarihi` etiketinden tebliğ olayı olarak sınıflandırır
(exact-scope §1/17; `src/manual_fact_entry_engine.py:453, 467`).

Generation preview:

```powershell
& "<python>" -m ui.cli_mutate generation --case <case-id> --row-key timeline --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı `input_digest` `<expected-input-digest>`
olarak kaydedildi; §26.3 baseline ölçüldü. Bu pending adımı ayrı onay
gerektirmez (§2.1). Biri eksikse: **DUR**.

Generation apply (tek çalıştırma):

```powershell
if ("<expected-input-digest>" -cnotmatch '^[0-9a-f]{64}\z') { "STOP EXPECTED_INPUT_DIGEST=INVALID" } else { & "<python>" -m ui.cli_mutate generation --case <case-id> --row-key timeline --actor-user-id <actor-user-id> --apply --expected-input-digest <expected-input-digest> }
```

Promotion preview:

```powershell
& "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key timeline --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı pending hash `<expected-hash>` olarak
kaydedildi; aşağıdaki kabul koşulu avukat tarafından incelendi; avukatın
yazılı onayı (`LEGAL_APPROVED`) ve ayrı **`REAL_ACTION_APPROVED`** alındı;
§26.3 baseline ölçüldü. Biri eksikse: **DUR**.

Promotion apply (tek çalıştırma):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}\z') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate promotion --case <case-id> --row-key timeline --actor-user-id <actor-user-id> --approve --expected-hash <expected-hash> }
```

Kabul: canonical timeline'da tebliğ olayı **tam bir** tanedir ve `verified`
fact'e bağlıdır; bunun `event_id` değeri `<anchor-event-id>`'dir. İkinci bir
tebliğ olayı veya anchor adayı varsa **DUR** (H5). Deadline anchor'ı
otomatik seçilmez; `--anchor` ile açıkça verilir (exact-scope §1/17).

---

## 17. Stopping-event beyanı ve kör bağımsız hesap

Kaynak: Temel L2775–L2812. Sapma yok.

### 17.1 Stopping-event beyanı ve adli tatil kararı

- Avukat, tebliğden sonra süreyi durdurabilecek, kesebilecek veya
  başlangıcını değiştirebilecek bir işlemin **bulunmadığını** yazılı olarak
  beyan eder ve beyana opak bir referans verir (`<attestation-ref>`, 1–200
  yazdırılabilir karakter, satır sonu yok, kişisel veri yok).
- Avukat adli tatilin uygulanabilirliğini yazılı olarak `yes` veya `no` diye
  kararlaştırır; aksi **DUR**.
- CLI'da `--stopping-event-status` verilmezse değer `unknown` sayılır ve sonuç
  `needs_review` olur; varsayılan **asla** `none` değildir.
- Avukat beyanı `present` veya `unknown` ise kesin tarih üretilmez; bu
  pilotta bu durum **DUR**'dur (H20). Operatör olayın hukuki etkisini
  yorumlayamaz (Adım 7 kapanışı).

### 17.2 Kör bağımsız hesabın sabitlenmesi (deadline generation'dan ÖNCE)

1. Avukat, **yalnız** orijinal belgeyi ve kendi hukuk bilgisini kullanarak
   son günü hesaplar. Bu hesaptan önce sistemin ürettiği hiçbir deadline,
   pending, canonical veya rapor sonucu avukata **gösterilmez**.
2. Hesap yazılı kayda alınır: tebliğ tarihi, hesaplanan son gün, hesabın
   kapsamı (uygulanan kural, adli tatil ve mali tatil değerlendirmesi) ve
   kaydın zamanı.
3. Kayıt dosyasının SHA-256'sı ve kayıt zamanı evidence'a yazılır; kaydın
   kendisi repo dışında, avukatın kontrolünde saklanır.
4. Ancak bundan **sonra** §18.1'deki deadline generation apply çalıştırılır.

Hash evidence'a yazılmadan deadline generation apply çalıştırılırsa:
**DUR** (H23).

---

## 18. Deadline generation, karşılaştırma ve approval

Kaynak: Temel L2816–L2895. Sapma yok (yalnız bölüm atıfları).

### 18.1 Generation

Parser davranışı (`ui/cli_mutate.py`, `_validate_generation_args`):
`--anchor` hem preview hem apply için zorunludur;
`--stopping-event-status` ve `--stopping-event-attestation-ref` **yalnız
apply'da** kabul edilir; `--judicial-recess-applicable` preview'da
**verilmez**; deadline `--attempt` varsayılan `1`'dir ve bu pilotta
değiştirilmez.

Preview:

```powershell
& "<python>" -m ui.cli_mutate generation --case <case-id> --row-key deadline --anchor <anchor-event-id> --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı `input_digest` `<expected-input-digest>`
olarak kaydedildi; §17.1 yazılı beyanı ve adli tatil kararı alındı; §17.2
hash'i evidence'ta; §26.3 baseline ölçüldü. Biri eksikse: **DUR**.

Apply (tek çalıştırma). `none` ve `yes` literal CLI değerleridir; avukatın
yazılı kararı `no` ise `yes` yerine `no` yazılır:

```powershell
if ("<expected-input-digest>" -cnotmatch '^[0-9a-f]{64}\z') { "STOP EXPECTED_INPUT_DIGEST=INVALID" } else { & "<python>" -m ui.cli_mutate generation --case <case-id> --row-key deadline --anchor <anchor-event-id> --actor-user-id <actor-user-id> --apply --expected-input-digest <expected-input-digest> --stopping-event-status none --stopping-event-attestation-ref "<attestation-ref>" --judicial-recess-applicable yes }
```

### 18.2 Pending deadline kabul kriterleri

Pending deadline şunları taşımadıkça karşılaştırmaya ve approval'a geçilmez
(`data/case_deadline.schema.json`): `calculation_state` `calculated`;
`expiry_state` `not_evaluated`; `anchor_verification_state` `verified`;
`stopping_event_status` `none` ve `stopping_event_attestation_ref` mevcut;
`requires_human_review = true`; tek deadline kaydı.
`blocked_unverified_anchor`, `needs_review` veya başka bir durum **DUR**'dur
(H19, H20, H21).

### 18.3 Pending tarihin sabitlenmiş hesapla karşılaştırılması

1. Pending'deki `calculated_deadline`, avukatın §17.2'de sabitlenmiş
   hesabındaki son günle **birebir** karşılaştırılır; önce sabitlenmiş
   kaydın SHA-256'sı yeniden ölçülür ve evidence'taki değerle aynı olduğu
   doğrulanır.
2. **Eşleşmezse:** deadline approval **çalıştırılmaz**. **DUR** (H23);
   düzeltme denenmez.
3. **Eşleşirse:** `PENDING_MATCH` evidence'a yazılır.

### 18.4 Approval (APP oturumu)

Preview:

```powershell
& "<python>" -m ui.cli_mutate approval --case <case-id> --row-key deadline --actor-user-id <actor-user-id>
```

Kapı: preview çıkış `0`; bastığı pending hash `<expected-hash>` olarak
kaydedildi; §18.2 ve §18.3 `PENDING_MATCH` sağlandı; avukatın yazılı deadline
onayı (`LEGAL_APPROVED`) ve ayrı **`REAL_ACTION_APPROVED`** alındı; §26.3
baseline ölçüldü. Avukatın onayı hiçbir durumda §17.2'den veya §18.3'ten
**önce** verilemez. Biri eksikse: **DUR**.

Apply (tek çalıştırma):

```powershell
if ("<expected-hash>" -cnotmatch '^[0-9a-f]{64}\z') { "STOP EXPECTED_HASH=INVALID" } else { & "<python>" -m ui.cli_mutate approval --case <case-id> --row-key deadline --actor-user-id <actor-user-id> --approve --expected-hash <expected-hash> }
```

---

## 19. Salt-okunur deadline raporu

Kaynak: Temel L2899–L2937. **Sapma:** boolean bloğuna temizlik satırı
`Remove-Variable r` eklendi (temelde yoktur; davranışı değiştirmez).

Rapor dava-türevi içeriktir; `<restricted-dir>` içine yazılır ve §28'e
tabidir.

```powershell
& "<python>" -m ui.deadline_report --case <case-id> --actor-user-id <actor-user-id> --output "<restricted-dir>\deadline-report.txt"
```

- APP oturumunda (insan-only) çalıştırılır; bağlantı salt-okunur
  transaction'dır. Aktif `lawyer` assignment'ı zorunludur. `--output` mutlak,
  repo dışı, henüz var olmayan ve parent'ı mevcut bir yoldur.
- Çıkış kodları: `0` rapor üretildi, `1` ret, `2` kullanım. Ret durumunda
  stderr tek satır `RAPOR REDDEDİLDİ: <sabit_kod>` taşır; her ret **DUR**'dur
  (H22). Başarıda stdout'taki `RAPOR YAZILDI: ` satırı evidence'a yazılmaz.
- Rapor şu iki satırı **birebir** taşımalıdır; yoksa **DUR**:
  - `Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.`
  - `Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.`

```powershell
$r = [System.IO.File]::ReadAllLines("<restricted-dir>\deadline-report.txt", [System.Text.Encoding]::UTF8)
"EXPIRY_LINE_PRESENT=$($r -ccontains 'Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.')"
"DISCLAIMER_LINE_PRESENT=$($r -ccontains 'Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.')"
(Get-FileHash -LiteralPath "<restricted-dir>\deadline-report.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
Remove-Variable r -ErrorAction SilentlyContinue
```

Evidence'a **yalnız** çıkış kodu, rapor dosyasının SHA-256'sı ve iki
boolean yazılır. Ardından §10.5 envanteri alınır (`RESTRICTED_FILE_COUNT=1`).

---

## 20. Rapor tarihinin son karşılaştırması

Kaynak: Temel L2941–L2953. Sapma yok.

1. Rapordaki `calculated_deadline`, avukatın §17.2'de sabitlenmiş hesabıyla
   **birebir** karşılaştırılır.
2. Eşleşme: `MATCH` evidence'a yazılır.
3. Eşleşmeme: **DUR** (H23). Rapor kullanılmaz, düzeltme denenmez.
4. Rapor süre aşımını **değerlendirmez** ve hukuki karar **değildir**.

---

## 21. Ağsızlık kanıtları (B yolu)

Kaynak: kapsam çalışması §4.4 (d). YENİ bölüm.

"Tamamen yerel" iddiası şu ölçümlerin **birleşimine** dayanır; hiçbiri tek
başına bir işletim sistemi düzeyinde ağ yasağı **değildir** (§32):

| Ölçüm | Nerede | Beklenen |
|---|---|---|
| `.env` yok veya 0 bayt | §13.6 (a), her içerik oturumu ve kapanış | `ENV_FILE=ABSENT` veya `ENV_FILE_BYTES=0` |
| `ANTHROPIC_*`, proxy, TLS ve `PG*` ad taraması | §13.6 (b), her içerik oturumu, her `manual-fact` çağrısı öncesi ve kapanış | Üç kapsamda **0** |
| Pilot için API anahtarı oluşturulmadı | Kullanıcı beyanı, evidence'a `PILOT_API_KEY_CREATED=False` | `False` |
| `generation.fact_extraction` hiç çalışmadı | §14.7 SQL, kapanışta | `0` |
| `manual-fact` ağ bayrağı tanımaz | `ui/cli_mutate.py:525-546` (kaynak); §1.6 provasında `--with-agent` ile çıkış `2` gözlenir | Kaynakta bayrak yok |
| Manuel motor ağ/LLM kütüphanesi import etmez | `src/manual_fact_entry_engine.py:10-15, 52-66` (kaynak) | Kaynakta import yok |
| Pilot toplam dış ağ işlemi | §30/10 | **Sıfır** olarak raporlanır |

Bu runbook bir ağ izleme aracı (monitor, harness, güvenlik duvarı kuralı)
**kullanmaz** (§29). Ağsızlık şunlara dayanır: (1) bu runbook'un yalnız
kaynakta ağ yolu taşımayan alt komutları kullanması; (2) bu pilotta erişilebilir
tek model yolunun (`generation --row-key fact_extraction`) yasak olması ve
anahtarın bulunmaması (§14.7, §13.6); (3) repodaki diğer model/ağ yollarının
— ham veri taşıyan ajan aileleri, kalan ajan aileleri ve `src/rag.py` — Pilot
Readiness Adım 4b/4c kod kapılarıyla kapalı olması (`CLAUDE.md` §5). Bu
runbook bu kapıların hiçbirini çağırmaz ve doğrulamaz; onlar repo
sözleşmesidir. Üçüncü taraf yazılımların (antivirüs, yedekleme,
işletim sistemi telemetrisi) ağ davranışı bu ölçümün kapsamı dışındadır
(§32).

---

## 22. Provenance ve kanıt yorumlama kuralları

YENİ bölüm.

### 22.1 Pending adı

Pending'in adı (`facts_llm_v1_3.json.pending`) provenance **değildir**
(§15.1, K-13). Bir fact'in kaynağı yalnız şunlarla belirlenir: pending/
canonical içindeki `extractor.method` ve `extractor_version`
(`manual`, `manual_fact_entry_v1`), `generation_reviews` altındaki audit
kaydının `action_family` ve `channel` alanları ve journal'daki
`action_family`.

### 22.2 `failed` satır + kalan audit ≠ başarı

N-M1 yazım sırası gereği audit, pending'den **önce** yazılır
(`src/manual_fact_entry_engine.py:29-40`). Bu yüzden audit yazıldıktan
sonra, `os.replace`'ten önce oluşan bir sert çöküşte disk "audit var /
pending yok" durumunda kalır ve satır `failed`'a reconcile olur. Bu audit
dosyası `outcome = generated` ve bir `pending_sha256` taşısa da **başarı
kanıtı değildir**. Başarının tek tanımı §22.3'tür.

### 22.3 Başarının tanımı (bağlayıcı)

Bir `manual-fact` apply'ı ancak şunların **hepsi** birlikte sağlanırsa
başarılıdır:

1. Journal'da o apply'a ait `generation.fact_manual` satırı
   `state = 'completed'`;
2. pending dosyası mevcut ve SHA-256'sı `<pending-sha256>` ile aynı
   (`PENDING_SHA_MATCH=True`);
3. `generation_reviews` altında `audit_file` satırındaki adla, aile, kanal,
   sonuç ve pending hash alanları beklenen değerde bir audit
   (`AUDIT_FILE_BOUND=True`) ve ayrıştırılamayan audit yok
   (`AUDIT_UNPARSEABLE_COUNT=0`) — §14.5.2 audit bloğu. İdempotency anahtarı
   bağı operatör bloğuyla ölçülmez; kuşkuda §14.6 dry-run'ı bağlayıcıdır;
4. temp artığı ve canonical yok (`TEMP_RESIDUE_ABSENT=True`,
   `CANONICAL_ABSENT=True`, promotion'dan önce).

Bunlardan biri tutmuyorsa sonuç **başarı sayılmaz**; §14.6 adım 1–4 ile
ölçülür.

---

## 23. Saklama ve imha takvimi (Form F)

Kaynak: Temel L3184–L3227 (silme/arşiv kararı) ve avukatın DRAFT-4 6.6
önerileri. **Sapmalar:** karar formun F1–F7 sorularına bağlandı; repo dışı
geçici dosya süresi (F1), imha kaydı (F5) ve 30 günlük silme talebi (F7)
eklendi.

| Soru | Kabul edilen cevap | DUR | Uygulandığı yer |
|---|---|---|---|
| F1 | "24 saat", "72 saat" veya açıklamalı "Diğer" | Boş | §28.6: repo dışı geçici kopyalar (E2 taşıyıcısı, E4 aracının ara dosyaları, indirme kopyaları) "iş bitince"den itibaren bu süre içinde silinir. "İş bitince" bu runbook'ta zincir adım 23'ün tamamlanması veya §25.2 abort yolunun başlaması anıdır |
| F2 | "Silinsin" veya "Şifreli arşivlensin" | Boş; iki kutu birden | §28.1, §28.3, §28.5 |
| F3 | F2 arşiv ise beş unsurun **hepsi** dolu | F2 arşiv iken bir unsur boş (H4) | §28.5 |
| F4 | **Seçenek (1)** "Standart silme (geri dönüşüm kutusu kullanılmadan), tam disk şifrelemesi açıkken" — **yalnız** E1 = "Evet" ve §4.2/10 doğrulaması `FULL_DISK_ENCRYPTION_CONFIRMED=True` (yürütme günü, zincir adım 4) ile birlikte | Boş; birden fazla kutu; seçenek (1) iken E1 ≠ "Evet" veya şifreleme doğrulanamadı. **Seçenek (2)** (üzerine yazan güvenli silme aracı): araç bu runbook'ta tanımlı değildir; aracı ve sürümünü tanımlayan ayrı bir runbook revizyonu ve bağımsız inceleme olmadan **DUR**. **Seçenek (3)** ("Diğer"): **DUR** (runbook'ta karşılığı yok; §6.1) (Y6) | §1.6/4, §4.2/10, §28.3, §28.6 |
| F5 | İmha kaydını tutacak kişi/yer yazılı | Boş | §28.7 |
| F6 | "Kabul" | Boş; "Kabul değil, koşul:" (koşul runbook'a işlenip yeniden incelenene kadar) | §28.4 |
| F7 | "Kabul" | Boş; "Değişiklik:" (değişiklik runbook'a işlenene kadar) | §28.8 |

Bu tablodaki her DUR, gerçek belge **teslim alınmadan önce** kontrol edilir
(zincir adım 2). F4 kapısı yalnız silme anında değil, **teslimden önce** de
değerlendirilir: seçilen yöntem bu runbook'ta tanımlı değilse veya
şifreleme doğrulanamıyorsa gerçek belge teslim alınmaz, çünkü aksi hâlde
veri onaylı yöntemle silinemez hâlde diskte kalır. Seçenek (1) ile şifreleme
koşulu **her silme gününde** silmeden hemen önce yeniden doğrulanır
(§28.3, §28.6); o gün doğrulanamazsa silme yapılmaz ve veri korunur
(§28.1/6).

**Seçenek (1)'in anlamı (dürüst sınır).** Standart silme dosya içeriğinin
üzerine yazmaz; gizlilik, verinin şifreli bir disk üzerinde bulunmasına
dayanır (form v3 F4 notu: SSD'de üzerine yazma güvenilir değildir). Bu yüzden
koşul, gerçek verinin dokunduğu **her** sürücünün şifreli olmasıdır
(§4.2/10). Şifresiz bir ortamda (ör. şifresiz USB) kalmış bir kopya bu
yöntemle "silinmiş" sayılmaz (§28.6).

---

## 24. Avukat formu ↔ runbook eşlemesi

| Form | Konu | Bölüm | DUR kodu |
|---|---|---|---|
| A1–A3 | Kapsam, 6.7 kararının teyidi, Bölüm 7 | §6.2 | Y1 |
| B1–B3 | Veri sorumlusu, operatör rolü, işleme sebebi | §6.3 | Y2 |
| B4 | Avukat ≠ operatör (iki kişi kuralı) | §4.1, §14.3, §15.3 | Y4 |
| B5 | Operatör gizlilik taahhüdü | §6.3 | Y2 |
| C1–C3 | Aydınlatma, açık rıza, avukatlık sırrı bilgilendirmesi | §7 | H3 |
| D 1–9, D2, D3 | Sisteme hiç alınmayacak belgeler | §9 | H2, H28 |
| E1 | Tam disk şifrelemesi (F4 seçenek (1)'in dayanağı) | §1.6/4, §4.2/10, §6.4, §23 | Y5, Y6 |
| E2 | Teslim kanalı | §6.4, §11.2/2 | Y5 |
| E3 | Olay bildirimi | §4.2/11, §25.2 | Y5 |
| E4 | Yerel OCR/metin aracı | §4.2/3, §11.2/6 | Y5 |
| F1 | Geçici dosya silme süresi | §23, §28.6 | Y6 |
| F2–F3 | Veri akıbeti, arşiv unsurları | §23, §28.1, §28.5 | H4, H55 |
| F4 | Silme yöntemi (yalnız seçenek (1) yürütülebilir) | §1.6/4, §23, §28.3, §28.6 | Y6 |
| F5 | İmha kaydı | §23, §28.7 | Y6 |
| F6 | Kalan izler | §23, §28.4 | Y6 |
| F7 | 30 günlük silme talebi | §23, §28.8 | Y6 |
| G0–G8 | Dosya seçimi | §8 | H42, Y7 |
| G9 | Tebliğ tarihinin rakamla `GG.AA.YYYY` / `GG/AA/YYYY` yazılı olması | §8, §11.3 (b), §14.2 | H42, Y16 |
| G10–G11 | G bölümünün ayrı ad/tarih ve imzası | §6.6, §8 | Y7 |
| H | Pilot sırasında istenecek kararlar (bilgi) | §12.1 | — |
| I1–I4 | Ekler ("Ek yok" dahil), ad, tarih, imza — yalnız A–F'yi kapsar | §6.1, §6.6 | Y1 |

---

## 25. Başarısızlık, DUR matrisi ve güvenli DUR/abort yolu

### 25.1 DUR matrisi

Kaynak: Temel L2959–L3026. **Sapmalar:** temel runbook'un H numaraları
korunan satırlar için **aynı kaldı** (inceleme farkı için); B yolunda anlamı
kalmayan H satırları "kaldırıldı" olarak işaretlendi; yeni satırlar `Y`
önekiyle eklendi.

Aşağıdaki her satır **DUR**'dur. Matris **tüketici değildir**: gövdede
"DUR" yazan her koşul bağlayıcıdır. Her DUR §25.2'yi çağırır. DUR'da:
otomatik retry **yok**, düzeltici SQL **yok**, model çağrısı **yok**, elle
dosya düzeltmesi **yok** (tek istisnalar: §14.5.3 girdi düzeltme döngüsü ve
intake düzeltmesi, §14.6 — ikisi de ayrı yazılı kararla).

| # | Tetikleyici | Bölüm |
|---|---|---|
| H1 | Avukat formu yok, imzasız veya A/B/C/E/F'de zorunlu bir soru boş | §6 |
| H2 | Form D tablosu eksik işaretli; D3 "ayrı ek" iken ek yok | §9 |
| H3 | Form C kapısı (aydınlatma, rıza, bilgilendirme) sağlanmadı | §7 |
| H4 | F2 boş; F2 arşiv iken F3'ün beş unsurundan biri boş. Gerçek belge teslim alınmaz | §23, §28.1 |
| H5 | Birden fazla dava, tebliğ veya deadline adayı | §8, §15, §16 |
| H6 | `file.sha256` yok/geçersiz veya orijinal bayt hash'i uyuşmuyor | §11.3 |
| H7 | Validator hatası veya kabul edilmemiş uyarı; argümansız veya yanlış case'i gösteren validator çağrısı | §11.3 |
| H8 | `??` görünümü, `case_0001` değişikliği veya ignore sapması | §11.3, §13.2 |
| H9 | Avukatın intake onayı yok | §11.4 |
| H10–H12 | **Kaldırıldı** (maskeleme tohumu, maskeli metin, maskeleme sayaçları; §29) | — |
| H13 | `.env` boyutu sıfırdan büyük; **herhangi bir** kapsamda §13.6 desenine uyan ad | §13.6 |
| H14, H15 | **Kaldırıldı** (egress sapması, ağ onayı; §29) | — |
| H16 | Digest veya hash değişmesi (preview ile apply arası, metin dosyası, girdi dosyası sürümü, sabitlenmiş hesap kaydı, kayda geçirilmemiş bir form/G bölümü sürümü) | §6.6, §11.3, §14, §17, §18 |
| H17 | Beklenmeyen DB deltası (journal, assignment) veya dosya deltası; preview öncesi/sonrası journal sayısı farklı | §13.5, §14.4, §26 |
| H18 | Fact için düzeltme/ret gereği | §15.1 |
| H19 | Unverified anchor (`blocked_unverified_anchor`) | §18.2 |
| H20 | Stopping-event `present` veya `unknown`; `needs_review`; adli tatil kararı `yes`/`no` değil | §17.1, §18.2 |
| H21 | `expiry_state` `not_evaluated` değil | §18.2 |
| H22 | Rapor reddi veya zorunlu satır eksik | §19 |
| H23 | Kör hesapla eşleşmeme; hesap sabitlenmeden deadline üretilmesi | §17.2, §18.3, §20 |
| H24 | Tek-çalıştırma komutunun sonucu belirsiz | §27.2 |
| H25 | Revoke veya cleanup postcondition'ı başarısız | §27–§30 |
| H26 | Evidence veya özet eksik | §26 |
| H27 | Küme durumu ölçülmedi veya beklenenden farklı | §13 |
| H28 | Belgenin Form D'de "hiç alınmaz" bir sınıfa girmesi veya şüphe | §9.3 |
| H29 | Case dizini intake'ten önce zaten mevcut | §11.2 |
| H30 | Branch, HEAD veya çalışma ağacı beklenenden farklı; runbook onaylı HEAD'de tracked değil | §1.6, §13.2 |
| H31 | `pip check` başarısız veya runtime paket kümesi sapması | §13.3 |
| H32, H33 | **Kaldırıldı** (harness/monitor/probe pinleri, maskeleme politikası sürümü; §29) | — |
| H34 | Beklenmeyen pending veya canonical (`ManualFactPendingExistsError`, `ManualFactCanonicalExistsError`) | §14.5.3 |
| H35 | `--discard-verified-states` gereği | §15.2 |
| H36 | Manifestin göreli yolunda kişisel veri | §28.2 |
| H37 | Herhangi bir komutta sıfır olmayan çıkış kodu, traceback veya yetkilendirme reddi | Genel, §14.5.3 |
| H38 | **Kaldırıldı** (auth probe; §29) | — |
| H39 | Güvenli DUR/abort veya teardown adımı başarısız ya da belirsiz | §25.2 |
| H40 | Gerçek içerik güven sınırının ihlali veya şüphesi; kanal kapısı geçmedi | §4.2, §4.3 |
| H41 | Bağımsız inceleme, commit veya sentetik prova ön koşulu eksik | §1.6 |
| H42 | Form G'de "Hayır" veya boş | §8 |
| H43 | Intake alanlarından birinin avukat onayı eksik; `unverified` dışı `verification_state`; JSON'da BOM; metin uzunluğu sınır dışı | §11.2, §11.4 |
| H44 | **Kaldırıldı** (`--mask-term` ve engel değerleri dosyası; §29) | — |
| H45 | Verification ön koşulu sağlanmıyor: locator yok, belge `active` değil veya avukatın ayrı verification kararı yok | §15.3 |
| H46 | Silme guard'ı başarısız veya silme kısmi/belirsiz; o hedef için silme anı onayı yok | §28.3 |
| H47 | Şifreli arşivin paritesi doğrulanamadı | §28.5 |
| H48 | Revoke ön koşulu: aktif assignment tam 1 değil | §27.1 |
| H49, H50 | **Kaldırıldı** (sonuçsuz POST tüketimi, pano/anahtar; §29) | — |
| H51 | `tax_type` sözlük kontrolü başarısız veya Form G8 ile eşleşmiyor; `manual-fact` çalıştırılmaz | §8, §11.3 |
| H52 | Yol kapısı başarısız; `<external-root>` sözleşmesi ihlali (iki çocuklu küme dışında öğe dahil); `<python>`/`<psql>` beklenen dizin dışında; `<archive-dir>` kapısı başarısız | §13.8, §28.5 |
| H53 | İçerik oturumu `-NoProfile` değil; aktif transcript; beklenmeyen modül; handler `UNKNOWN`; `SaveNothing` değil | §4.3 |
| H54 | Salt-okunur SQL sözleşmesi ihlali; düzeltici SQL gereği | §13.5 |
| H55 | Eksik veya belirsiz veri akıbeti kararı intake'ten sonra fark edildi: veri silinmez, arşivlenmez, korunur | §28.1 |
| H56 | `<restricted-dir>` içerik sözleşmesi ihlali (kayıt/hash, izinli küme dışı öğe, alt dizin, reparse point, manifest yazılamadı) | §10.5, §28.2 |
| H57–H59 | **Kaldırıldı** (harness zinciri, süreç yardımcısı, çocuk süreç ortam profili; §29) | — |
| Y1 | Form A'da kapıyı kapatan cevap veya runbook'a işlenmemiş ek koşul; I1–I4 eksik (I1'de ne "Ek yok" ne "Ekler" işaretli; "Ek yok" ile ek gerektiren bir cevap çelişiyor); A–F imzası §6.6/1 biçiminde değil | §6.1, §6.2, §6.6 |
| Y2 | Form B1–B3 veya B5 kapısı | §6.3 |
| Y3 | Kullanılmıyor (Form C kapısı H3 satırındadır) | — |
| Y4 | İki kişi kuralı: B4 boş; aynı kişi ve B4 açık kabul yok; `TWO_PERSON_CONTROL=SEPARATE` veya `=WAIVED_B4` kaydından tam biri yok | §4.1, §14.3 |
| Y5 | Form E kapısı: E1 "Evet" değil veya E1'e ek koşul yazılmış; şifreleme doğrulanamadı veya bir sürücü sürücü bazında gösterilemedi (§4.2/10); yol 2/3'te kullanıcı kabulü yok; harici disk ne şifreli ne çıkarılmış veya pencere içinde yeniden takıldı; E2 kanalı veya taşıyıcı kontrolü (`E2_CARRIER_ENCRYPTED=False`); E3 bildirim yolu veya E4 aracı/onayı eksik | §4.2, §6.4 |
| Y6 | Form F1, F4–F7 kapısı; F4 seçenek (1) değil; silme günü şifreleme yeniden doğrulanamadı; F1 kopyası şifresiz ortamda; F1 süresi aşıldı; imha kaydı yazılmadı | §1.6/4, §23, §28 |
| Y7 | G0 boş veya kişisel veri taşıyor; G8 boş; G10/G11 eksik veya imza §6.6/1 biçiminde değil; G10 tarihi bağlayıcı I3'ten önce veya avukatın sıra beyanı yok; A–F yeniden imzalandı ve G yeniden imzalanmadı | §6.6, §8 |
| Y8 | `PAGE_COUNT=OK` alınamadı (`file.page_count` boş, tamsayı değil veya < 1) | §11.2/5 |
| Y9 | `MANUAL_INPUT_ENCODING=OK` alınamadı | §14.2 |
| Y10 | Avukatın girdi karşılaştırması yok; kararda `r<input-revision>` veya hash öneki yok; `MANUAL_INPUT_HASH_RECORDED=True`, `MANUAL_INPUT_MATCHES_LAWYER_REVISION=True` veya `LAWYER_DECISION_CITES_RECORD=True` alınamadı; üçüncü bir girdi düzeltmesi gereği (`<input-revision>` > 3); sürüm sırası atlandı veya ileri bir sürüm kaydı mevcut | §14.3, §14.5.3 |
| Y11 | `manual-fact` preview/apply kabul kriterinden sapma: tarih/sayfa avukatın teyidinden farklı; `pending_sha256` farkı; `replayed=True`; journal ≠ 1 yeni `completed` satır; disk veya audit boolean'larından biri beklenen değerde değil (`AUDIT_FILE_BOUND`, `AUDIT_UNPARSEABLE_COUNT` dahil) | §14.4, §14.5 |
| Y12 | Pending içerik kontrolü (`method`, sağlayıcı/model, fact sayısı, `unverified`, `<fact-id>`, locator) başarısız | §15.1 |
| Y13 | §14.6: ayrıştırılamayan audit; temp artığı guard'ı (journal satırı `failed` değil, audit sayımı, temp SHA uyuşmazlığı) veya silme sonucu; dry-run ve apply sonuç farkı; `new_state=reconciliation_required`; ikinci yeniden deneme gereği; validator kaynaklı kök hata | §14.6 |
| Y14 | `generation --row-key fact_extraction` çalıştırıldı veya şüphe; kapanış SQL'i `0` değil | §14.7, §21 |
| Y15 | Herhangi bir model çağrısı, ağ bayrağı veya API anahtarı oluşturma girişimi | §1.2, §3 |
| Y16 | Form G9 "Hayır" veya boş; `TEXT_DATE_TOKEN_PRESENT=True` alınamadı (metinde tanınabilir biçimde tarih yok) | §8, §11.3 (b) |

### 25.2 Güvenli DUR/abort yolu (bağlayıcı)

Kaynak: Temel L3028–L3074. **Sapmalar:** anahtar ve Console revoke adımları
(Temel 2–3) çıkarıldı; reconciliation durumu ve olay bildirimi (E3)
eklendi; F1 süresi bağlandı.

Her DUR bu yolu çağırır. Bu yol yalnız **aşağıdaki güvenli kapatma
adımlarına** izin verir; zincirin ilerletilmesine izin vermez. Sıra
bağlayıcıdır:

1. **Durdur.** Yeni mutasyon ve yeniden deneme yapılmaz.
2. **DB oturumları.** Açık etkileşimli veritabanı oturumlarında işlem geri
   alınır (`ROLLBACK`) ve oturum kapatılır.
3. **Journal ölçümü.** Çözülmemiş satırlar §14.6 adım 2 ile salt-okunur
   ölçülür. Çözülmemiş satır varsa §14.6 adım 3–5 **yalnız ayrı onayla**
   uygulanabilir; uygulanmazsa satır ve case gate'li kalır ve bu durum
   raporlanır. Yeniden deneme (§14.6 adım 7) abort yolunun parçası
   **değildir**.
4. **Assignment ölçümü.** Aktif assignment sayısı salt-okunur ölçülür
   (§13.5).
5. **Tam 1 aktif assignment varsa:** revoke ayrı `REAL_ACTION_APPROVED` ile
   ve **yalnız bir kez** çalıştırılır (§27.1).
6. **0 aktif assignment varsa:** revoke **çalıştırılmaz**.
7. **Birden fazla veya belirsiz sayıda assignment varsa:** **DUR**; düzeltici
   SQL yok.
8. **Gerçek veri.** Diskte gerçek veri varsa akıbeti **yalnız** Form F'deki
   **eksiksiz** yazılı karara göre belirlenir (§28.1); her silme hedefi için
   ayrı guard ve silme anındaki ayrı `REAL_ACTION_APPROVED` gerekir. Karar
   eksik veya belirsizse, F4 seçenek (1) değilse ya da silme günü disk
   şifrelemesi yeniden doğrulanamıyorsa (§4.2/10) veri
   **silinmez ve arşivlenmez**; değiştirilmeden korunur (H55, Y6). DUR tek
   başına bir silme talimatı **değildir**.
9. **Repo dışı geçici kopyalar.** Form F1 süresi DUR anından itibaren işler
   (§23); §28.6'ya göre ele alınır.
10. **Olay bildirimi.** DUR bir güvenlik olayıysa (H40; cihaz kaybı,
    virüs, yetkisiz erişim) avukata Form E3'teki yolla hemen bildirilir.
11. **Evidence.** Yalnız opak durum, hash'ler ve kişisel veri içermeyen hata
    kodu (sınıf adı, kural kodu) yazılır.
12. **Kalan durum raporu.** Açık kalan her kaynak ve veri durumu (assignment
    aktif mi, veri diskte mi, hangi journal satırları var ve hangisi
    çözülmemiş) kullanıcıya açıkça raporlanır.
13. **Cleanup başarısızsa:** otomatik tekrar **yok**; kalan risk kaydedilir ve
    insan kararı beklenir (H39).

Gerçek veri henüz teslim alınmadıysa 8. ve 9. adımlar "uygulanmadı" olarak
kaydedilir. Journal satırları, mutation resource satırı ve security event'ler
abort'ta da **silinmez** (§28.4). Veri diskte kaldığı sürece §4.3 içerik
penceresi **açıktır**.

---

## 26. Audit / evidence sözleşmesi

### 26.1 Konum

Kaynak: Temel L3080–L3087. **Sapma:** probe ve inference dizinleri
çıkarıldı.

`<evidence-dir>` repo dışında, erişimi kısıtlı bir dizindir ve **yalnız
metadata** taşır. Gerçek belge baytları, metin, girdi dosyası, alıntı, tarih,
sayfa numarası, ham stdout/stderr, traceback, deadline raporu veya kişisel
veri buraya **yazılmaz**. Dava-türevi içerik yalnız `<restricted-dir>`
içinde durur.

### 26.2 Zorunlu kayıtlar

Kaynak: Temel L3089–L3114. **Sapmalar:** maskeleme, ortam profili, süreç
yardımcısı, probe ve inference satırları çıkarıldı; form, manuel girdi,
`manual-fact`, reconciliation ve ağsızlık satırları eklendi.

| Kayıt | İçerik |
|---|---|
| Başlangıç | Branch, HEAD, temiz ağaç, runbook'un tracked olduğu, ignored görünüm, küme durumu, `pip check`, kayıt/telemetri ön kontrolü |
| İçerik oturumu | §4.3 (b) çıktıları (her içerik oturumu için) |
| Kanal kapısı | §4.3 (a): süreç adı taraması sonucu, altı sınıf boolean'ı ve `AI_CONTENT_CHANNELS_CLOSED=True` |
| Yol kapısı | §13.8: her yer tutucu adı için `PATH_OK` ve `PATH_OK=external-root-contract` |
| Ön koşullar | Bağımsız inceleme sonucu, commit kimliği, sentetik prova evidence'ının hash'i |
| Avukat formu | Form v3 boş şablon hash'i; §6.6/7 biçimindeki bütün `FORM_HASH` ve `FORM_BINDING` satırları (her imzalı sürüm ve her ek ayrı satır) ve her `FORM_HASH_RECHECK` sonucu; imza biçimi (taranmış PDF / e-imza); I3–G10 sıra kontrolü ve avukat beyanının hash'i; redakte kapsam özeti; `TWO_PERSON_CONTROL=SEPARATE` veya `TWO_PERSON_CONTROL=WAIVED_B4` (ikincisinde kullanıcı onayının zamanı); E4 aracının adı ve sürümü; girdi düzenleyicisinin adı |
| Disk şifrelemesi | Her ölçüm için (zincir adım 4 ve her silme günü): `DISK_ENCRYPTION_METHOD` (sürücü bazında farklıysa her sürücü için), yol 3'te aracın adı/sürümü, sürücü harfleri, ölçüm zamanı, `FULL_DISK_ENCRYPTION_CONFIRMED=True`; yol 2/3'te `ENCRYPTION_TOOL_USER_ACCEPTED=True` ve kullanıcı onayının zamanı; harici disk için `EXTERNAL_DISK_ENCRYPTED` / `EXTERNAL_DISK_REMOVED`. Provadan: üç yolun ve harici diskin `*_PRESENT` boolean'ları (§1.6/3) |
| E2 taşıyıcısı | `E2_CARRIER_KIND`, `E2_CARRIER_ENCRYPTED` (§6.4) |
| Restricted kümesi | `restricted-allowed-files.txt`, `ALLOWED_FILE_HASH_RECORDED=True`, hash kaydının bayt sayısı ve SHA-256'sı, her envanterde `ALLOWED_FILE_HASH_OK=True`, `RESTRICTED_INVENTORY=OK` ve dosya sayısı |
| Intake | `JSON_BOM=NONE`, `TEXT_LENGTH=OK`, `PAGE_COUNT=OK`, `INTAKE_HASH=MATCH`, `TEXT_DATE_TOKEN_PRESENT=True`, `INTAKE_HASHES_RECORDED=True`, her `manual-fact` çağrısı öncesi `SOURCE_HASHES_MATCH=True`, validator PASS/sayılar, `TAX_TYPE_VOCAB=OK`, ignore kontrolü, avukat intake onayının hash'i |
| Manuel girdi | Her sürüm için `MANUAL_INPUT_ENCODING=OK`, `MANUAL_INPUT_HASH_RECORDED=True`, `manual-input-r<input-revision>.sha256.txt` kayıtları, avukat karşılaştırmasının hash'i, `MANUAL_INPUT_MATCHES_LAWYER_REVISION=True` ve `LAWYER_DECISION_CITES_RECORD=True`, girdi düzeltme döngüsü sayısı (en fazla 2) ve her turun sınıf/kural kodu |
| `manual-fact` preview | Çıkış kodu, `input_digest`, `pending_sha256`, `text_excerpt_sha256`, `excerpt_found`, `PREVIEW_DATE_MATCHES_LAWYER`, `PREVIEW_PAGE_MATCHES_LAWYER`, `<fact-id>`, preview öncesi/sonrası journal sayısı |
| `manual-fact` apply | Çıkış kodu, `pending_sha256`, `audit_file`, `journal_id`, `attempt`, `replayed`, `PENDING_SHA_MATCH`, `TEMP_RESIDUE_ABSENT`, `CANONICAL_ABSENT`, `AUDIT_FILE_BOUND`, `AUDIT_LIST_OK`, `AUDIT_UNPARSEABLE_COUNT`, kullanıcı onayının zamanı |
| Reconciliation (yalnız §14.6) | Journal ölçüm sonuçları, `PENDING_PRESENT`, `TEMP_RESIDUE_PRESENT`, `AUDIT_FILE_COUNT`, `AUDIT_UNPARSEABLE_COUNT`, dry-run ve apply `new_state`/`resolution_code`, temp guard satırları (`JOURNAL_ROW_STATE_FAILED`, `TEMP_RESIDUE_SHA_MATCHES_PREVIEW`, `TEMP_RESIDUE_REMOVED`), yeniden deneme kararı ve onay zamanları |
| Pending kontrolü | §15.1'in altı boolean'ı |
| Her mutasyon | Komut ailesi ve row-key, çıkış kodu, preview hash/digest, apply sonrası dosya SHA-256'sı, yeni journal satırı sayısı ve durumu, kullanıcı onayının zamanı |
| Avukat kararları | Her yazılı kararın hash'i |
| Kör hesap | Sabitlenmiş kaydın SHA-256'sı ve zamanı |
| Karşılaştırma | `PENDING_MATCH` ve `MATCH` |
| Rapor | Çıkış kodu, rapor SHA-256'sı, iki boolean |
| Ağsızlık | §21 tablosunun her satırının sonucu; `PILOT_API_KEY_CREATED=False` |
| Kapanış | İki manifest ve dosya sayıları, silme günü şifreleme doğrulaması, silme guard ve sonuç satırları, varsa `PATH_OK=archive-dir` ve arşiv paritesi, revoke sonucu, F1 silme kaydı (kopya sayısı, her kopyanın ortamının şifreli olduğu, zaman), F5 imha kaydının yeri, form hash'lerinin kapanış yeniden ölçümü, postcondition'lar |
| DUR | Tetiklenen satır, §25.2 adımlarının sonucu, kalan durum |

### 26.3 Journal kontrolü

Kaynak: Temel L3116–L3133. **Sapma:** beklenen aileler listelendi.

Her apply'dan önce `case:<case-id>` için en büyük journal `id` değeri
(`<baseline-max-id>`) alınır; apply'dan sonra yalnız bu değerden büyük
satırlar sorgulanır (§13.5 biçimiyle, APP oturumunda):

```sql
SELECT coalesce(max(id), 0) FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>';
```

```sql
SELECT id, state, actor_user_id, action_family FROM mutation.mutation_journal WHERE resource_key = 'case:<case-id>' AND id > <baseline-max-id> ORDER BY id;
```

Beklenen: tam **1** yeni satır, `state = 'completed'`, `actor_user_id` avukat
aktörü ve `action_family` çalıştırılan aile: `manual-fact` →
`generation.fact_manual`; fact promotion → `promotion.fact`; verification →
`verification.fact`; timeline generation → `generation.timeline`; timeline
promotion → `promotion.timeline`; deadline generation →
`generation.deadline`; deadline approval → `approval.deadline`.

### 26.4 Özet

Kaynak: Temel L3135–L3138. Sapma yok.

Pilot sonunda kişisel veri içermeyen tek bir özet dosyası yazılır ve
SHA-256'sı kaydedilir. Özet yoksa pilot kapanmış sayılmaz.

---

## 27. Assignment revoke ve tek-çalıştırma kuralları

Kaynak: Temel L3142–L3178. **Sapma:** tek-çalıştırma listesine
`manual-fact` apply'ı ve reconciliation apply'ı eklendi; auth probe ve
gönderim çıkarıldı.

### 27.1 Revoke (ADMIN oturumu, tam bir kez)

**Ön koşul.** Rapor ve son karşılaştırma tamamlanmıştır (veya §25.2 abort
yolu çağrılmıştır) ve APP oturumunda ölçülen aktif assignment sayısı **tam
1**'dir:

```sql
SELECT count(*) FROM iam.case_assignments WHERE case_id = '<case-id>' AND revoked_at IS NULL;
```

Sayı 1 değilse revoke **çalıştırılmaz**: 0 ise gerek yoktur; 1'den büyükse
veya belirsizse **DUR** (H48).

Ayrı `REAL_ACTION_APPROVED` ile:

```powershell
& "<python>" -m scripts.iam_admin revoke-assignment --user-id <actor-user-id> --case-id <case-id> --actor-user-id <admin-user-id>
```

Beklenen: çıkış `0` ve `OK`. Ardından aynı sorguyla aktif assignment sayısı
**0** olarak doğrulanır.

### 27.2 Tek-çalıştırma kuralı

- `revoke-assignment` **idempotent değildir** (`scripts/iam_admin.py`,
  `revoke_assignment`); **asla ikinci kez** çalıştırılmaz.
- Aynı kural `assign-case`, `manual-fact --apply` (tek istisna: §14.6
  adım 7'deki ayrı onaylı `--attempt 2`), her `--apply`/`--approve`
  komutu ve `ui.reconciliation_operator --apply` için geçerlidir.
- Sonuç belirsizse komut tekrar **edilmez**; durum yalnız salt-okunur SQL ve
  dosya hash'iyle ölçülür ve **DUR** kaydı yazılır (H24).

---

## 28. Veri silme veya şifreli arşiv (Form F)

### 28.1 Yazılı karar her zaman zorunludur ve eksiksiz olmalıdır

Kaynak: Temel L3184–L3227. **Sapmalar:** karar Form F2–F3'e bağlandı;
`<restricted-dir>` kapsamı yalnız rapora indirildi.

Avukat pilot sonunda verinin akıbetini Form **F2**'de yazılı olarak
kararlaştırır:

- **Silme** ("Silinsin"). Kapsam: case dizini (manuel girdi dosyası ve
  `extracted` metin dahil); `<restricted-dir>` dizini ve içeriği (deadline
  raporu); oluşmuş olabilecek diğer kopyalar (§28.6).
- **Şifreli arşiv** ("Şifreli arşivlensin"). Aynı kapsam ve Form **F3**'ün
  beş unsurunun **tamamı**: (1) arşiv yeri (`<archive-dir>` ve
  `<archive-parent>`); (2) şifreleme yöntemi; (3) erişebilecek kişiler veya
  roller; (4) saklama süresi / silinme tarihi; (5) arşiv doğrulandıktan sonra
  yerel kopyanın **silineceği** veya **korunacağı**.

**Teslimden önceki kapı.** F2 boşsa veya arşiv seçiliyken F3'ün bir unsuru
eksikse: gerçek belge teslim **alınmaz** (H4). F4 seçenek (1) değilse veya
disk şifrelemesi doğrulanamıyorsa da teslim alınmaz (§1.6/4, §23, Y6).

**Bağlayıcı kurallar** (Temel L3206–L3227 birebir anlamda):

1. Silme önerilen seçenektir ama **varsayılan değildir**.
2. Eksik bir arşiv kararı hiçbir koşulda örtülü silme talimatına
   dönüştürülemez.
3. Silme **yalnız** açık ve eksiksiz yazılı kararla yapılır ve §28.3'ün
   mekanik guard'larına ve silme anındaki ayrı `REAL_ACTION_APPROVED`'a
   tabidir.
4. Arşiv paritesi (§28.5) kurulmadan **hiçbir** çalışma kopyası silinmez.
5. F3/5'te "korunsun" seçilmişse doğrulanmış arşivden sonra çalışma kopyası
   silinmez; içerik penceresi açık kalır ve §30'daki 1., 8. ve 11. koşullar
   sağlanmamış olur.
6. Eksiklik intake'ten sonra fark edilirse veri otomatik **silinmez** ve
   **arşivlenmez**; değiştirilmeden korunur; yeni ve eksiksiz yazılı karar
   beklenir (H55).

### 28.2 Silme öncesi metadata manifestleri

Kaynak: Temel L3229–L3290. **Sapmalar:** restricted manifestinin
`$rSetOk` koşulu (Temel L3282) yeniden yazıldı: maskeleme ve engel dosyası
şartları çıkarıldı; rapor üretilmediyse **başlık-yalnız** manifest kabul
edilir. Ayrıca `$rLines = @()` başlatma satırı eklendi (temelde yoktur;
önceki bir oturumdan kalan değerin manifeste girmesini önler).

İçerik snapshot'ı **alınmaz**. İki **ayrı** manifest üretilir:

| Manifest | Dosya | İlk satır | Göreli yol tabanı |
|---|---|---|---|
| Case | `<evidence-dir>\closing-case-manifest.tsv` | `# kind=case` | `<case-root>` |
| Restricted | `<evidence-dir>\closing-restricted-manifest.tsv` | `# kind=restricted` | `<restricted-dir>` |

Her iki manifest exclusive-create ile yazılır; ilk satırdan sonraki her
satır göreli yol, bayt sayısı ve SHA-256 taşır. Yazma `False` dönerse:
**DUR** (H56).

**Case manifesti — Aşama 1 (göreli yolların ekranda kontrolü; dosyaya
yazılmaz; Temel L3252–L3254 birebir):**

```powershell
$root = "<case-root>"
$files = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File | Sort-Object FullName)
$files | ForEach-Object { $_.FullName.Substring($root.Length + 1) }
```

Göreli yollar §10.3'teki opak kimlikler sayesinde kişisel veri taşımamalıdır.
Beklenen yollar arasında `documents\<document-id>\manual_input\manual_facts.input.json`,
`documents\<document-id>\extractions\…` ve
`documents\<document-id>\extractions\generation_reviews\manual_<document-id>_….generation_audit.json`
bulunur. Bir yol kişisel veri taşıyorsa manifest **oluşturulmadan DUR**
(H36).

**Aşama 2 — case manifestinin yazılması** (Temel L3264–L3265 birebir):

```powershell
$lines = @($files | ForEach-Object { "{0}`t{1}`t{2}" -f $_.FullName.Substring($root.Length + 1).Replace('\', '/'), $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() })
if (($lines.Count -ge 1) -and (Write-PilotExclusive "<evidence-dir>\closing-case-manifest.tsv" (@('# kind=case') + $lines))) { "CASE_MANIFEST=WRITTEN"; "CASE_FILE_COUNT=$($lines.Count)" } else { "STOP CASE_MANIFEST=FAIL" }
```

**Restricted manifesti.** Önce §10.5 envanteri `RESTRICTED_INVENTORY=OK`
vermiş olmalıdır. `deadline-report.txt` yalnız ve yalnız zincir adım 22 çıkış
`0` ile tamamlandıysa (`<report-produced>` `$true`) bulunur; değilse dizin
boştur ve manifest **yalnız başlık** satırını taşır. **Temel L3282'den
sapma:**

```powershell
$rDir = "<restricted-dir>"
$allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false))))
$allowedSet = @($allowedLines | Select-Object -Skip 1)
$rState = Get-PilotRestrictedState $rDir
$rNames = @($rState.Files | ForEach-Object { $_.Name })
$rSetOk = ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and ($null -ne $rState) -and ($rState.Bad -eq 0) -and (@($rNames | Where-Object { $allowedSet -cnotcontains $_ }).Count -eq 0) -and (($rNames -ccontains 'deadline-report.txt') -eq <report-produced>) -and ($rNames.Count -eq $(if (<report-produced>) { 1 } else { 0 }))
$rLines = @()
if ($rSetOk) { $rLines = @($rState.Files | ForEach-Object { "{0}`t{1}`t{2}" -f $_.Name, $_.Length, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }) }
if ($rSetOk -and (Write-PilotExclusive "<evidence-dir>\closing-restricted-manifest.tsv" (@('# kind=restricted') + $rLines))) { "RESTRICTED_MANIFEST=WRITTEN"; "RESTRICTED_FILE_COUNT=$($rLines.Count)" } else { "STOP RESTRICTED_MANIFEST=FAIL" }
```

Komutlar yalnız sabit durum satırı ve dosya sayısı basar. Dosya
SHA-256'ları, içeriğe sahip biri için bir parmak izidir; bu kalıcı iz Form
F6 ile kabul edilmiş olmalıdır. Tarih taşıyan dosyaların hash'ine ilişkin
sınır §32'dedir.

### 28.3 Silme

Kaynak: Temel L3292–L3524. **Sapmalar:** korunan yol listelerinden ve
`<external-root>` çocuk kümelerinden probe/inference dizinleri çıkarıldı
(Temel L3351, L3397, L3468, L3474, L3501); restricted guard'ı
**başlık-yalnız** manifesti kabul edecek biçimde yeniden yazıldı (Temel
L3473'teki `$rManifest.Count -ge 2` şartı `-ge 1` oldu); Form F4 kapısı
eklendi. Case guard fonksiyonu **birebirdir**.

**F4 kapısı.** Bu bölümdeki silme `Remove-Item -Recurse -Force`'tur: dosya
sistemi kaydını kaldırır, geri dönüşüm kutusunu kullanmaz, ama dosya
içeriğinin **üzerine yazmaz**. Bu, Form F4 **seçenek (1)**'dir ("Standart
silme, tam disk şifrelemesi açıkken") ve bu runbook'ta tanımlı **tek**
yöntemdir. Bu bölüm yalnız şunların hepsi sağlanırsa uygulanır:

1. Form F4 = seçenek (1) ve E1 = "Evet" (§23);
2. **silme günü**, ilk silme komutundan hemen önce, §4.2/10'daki
   şifreleme doğrulaması ve harici disk kuralı **tam kapsamla** (§4.2/10
   "Kapsam": bütün sürücüler, harici disk dahil; daraltılmaz) yeniden
   yapılmış ve `FULL_DISK_ENCRYPTION_CONFIRMED=True` vermiştir.

F4 seçenek (2) veya (3) ise ya da madde 2 sağlanmazsa bu bölüm
**uygulanmaz**: **DUR** (Y6); veri değiştirilmeden korunur (§28.1/6) ve
avukata bildirilir.

Silme **yalnız** §28.1/3'teki açık ve eksiksiz yazılı kararla yapılır. İki
hedef vardır ve her biri **ayrı** guard'dan, **ayrı** silme anı
`REAL_ACTION_APPROVED`'dan ve **tek** çalıştırmadan geçer: önce case dizini
(§28.3.1), sonra `<restricted-dir>` (§28.3.2).

#### 28.3.1 Case dizini

Guard fonksiyonu (Temel L3313–L3340 birebir):

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

Önce durum ve guard (**sapma:** korunan liste):

```powershell
git status --porcelain -- data/cases/case_0001
git status --ignored --porcelain -- data/cases
$target = "<case-root>"
$cGuard = $false
try {
    $cProtected = @("<external-root>", "<evidence-dir>", "<restricted-dir>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")
    $cChecks = @(Test-PilotCaseDeleteChecks $target "<repo-root>\data\cases" '<case-id>' "<evidence-dir>\closing-case-manifest.tsv" $cProtected)
    if (($cChecks.Count -eq 1) -and ($cChecks[0] -is [bool]) -and ($cChecks[0] -eq $true)) { $cGuard = $true }
}
catch {
    $cGuard = $false
}
if ($cGuard -eq $true) { "CASE_DELETE_GUARD=PASS" } else { "STOP CASE_DELETE_GUARD=FAIL" }
```

Beklenen: ilk komut **boş**; ikinci komut **yalnız**
`!! data/cases/<case-id>/`; **`CASE_DELETE_GUARD=PASS`**. Guard: hedefin
yaprak adı `<case-id>` ve `case_0001` değil; ebeveyni `data\cases`; korunan
yollarla örtüşme yok; reparse point yok; manifest `# kind=case` ve geçerli;
canlı dosya kümesi, bayt sayıları ve SHA-256'lar manifestle birebir.
Başarısızsa silme **yapılmaz**: **DUR** (H46).

Guard PASS ise ve **silme anında ayrı `REAL_ACTION_APPROVED`** alındıysa,
aynı oturumda, **bir kez**, tek parça (guard baştan yeniden hesaplanır):

```powershell
$cGuard = $false
try {
    $cProtected = @("<external-root>", "<evidence-dir>", "<restricted-dir>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")
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
**boş**. `git clean -fdx` ve `git stash --all` **kullanılmaz**. Aksi:
tekrar veya doğaçlama düzeltme yok, **DUR** (H46).

#### 28.3.2 `<restricted-dir>`

Hedef, §13.8'de `PATH_OK=restricted-dir` almış **exact** `<restricted-dir>`
dizinidir. Guard, case silmesinden sonra aynı oturumda çalışır. **Sapmalar:**
`<external-root>` çocuk ve korunan listeleri iki dizine indirildi;
`$rManifest.Count -ge 1` (başlık-yalnız manifest kabul).

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
    if ($g) { $g = ((Test-PilotExternalRoot $rParent "<repo-root>" @("<evidence-dir>", "<restricted-dir>") @("<case-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) -eq $true) }
    $rManifest = @(); $allowedLines = @()
    if ($g) { $rManifest = @([System.IO.File]::ReadAllLines("<evidence-dir>\closing-restricted-manifest.tsv", (New-Object System.Text.UTF8Encoding($false)))); $allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false)))) }
    $allowedSet = @($allowedLines | Select-Object -Skip 1)
    $rExpected = @($rManifest | Select-Object -Skip 1)
    $g = $g -and ($rManifest.Count -ge 1) -and ($rManifest[0] -ceq '# kind=restricted') -and ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and (@($rExpected | Where-Object { $allowedSet -cnotcontains ($_ -split "`t")[0] }).Count -eq 0)
    if ($g) { foreach ($p in @("<repo-root>", "<case-root>", "<evidence-dir>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $rDir $p)) { $g = $false } } }
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
**`RESTRICTED_DELETE_GUARD=PASS`**. Başarısızsa silme **yapılmaz**: **DUR**
(H46; `ALLOWED_FILE_HASH_OK=False` ayrıca H56).

Guard PASS ise ve **bu hedef için silme anında ayrı `REAL_ACTION_APPROVED`**
alındıysa, aynı oturumda, **bir kez** (**sapma:** `$extKept` yalnız
`<evidence-dir>`):

```powershell
if ($rGuard -eq $true) { try { Remove-Item -LiteralPath $rDir -Recurse -Force -ErrorAction Stop; "RESTRICTED_DELETE_RESULT=COMPLETED" } catch { "STOP RESTRICTED_DELETE_RESULT=FAILED" } } else { "STOP RESTRICTED_DELETE_GUARD=FAIL" }
"RESTRICTED_DIR_ABSENT=$(-not (Test-Path -LiteralPath $rDir))"
"RESTRICTED_RESIDUE_COUNT=$(@(Get-ChildItem -LiteralPath $rDir -Force -Recurse -ErrorAction SilentlyContinue).Count)"
$extResidueOk = $false
try { $extKept = @("<evidence-dir>"); if ((Test-PilotExternalRoot $rParent "<repo-root>" $extKept @("<case-root>", [System.IO.Path]::GetTempPath(), "<python-runtime-root>", "<pg-bin-dir>")) -eq $true) { $extNow = [string[]]@(Get-ChildItem -LiteralPath $rParent -Force -ErrorAction Stop | ForEach-Object { $_.Name }); $extExpected = [string[]]@($extKept | ForEach-Object { [System.IO.Path]::GetFileName($_.TrimEnd('\')) }); [Array]::Sort($extNow, [System.StringComparer]::Ordinal); [Array]::Sort($extExpected, [System.StringComparer]::Ordinal); $extResidueOk = (($extNow -join '|') -ceq ($extExpected -join '|')) } } catch { $extResidueOk = $false }
"EXTERNAL_ROOT_RESIDUE_OK=$extResidueOk"
git status --porcelain=v1 --untracked-files=all
git status --ignored --porcelain -- data/cases
git status --porcelain -- data/cases/case_0001
```

Beklenen, hepsi birlikte: `RESTRICTED_DELETE_RESULT=COMPLETED`,
`RESTRICTED_DIR_ABSENT=True`, `RESTRICTED_RESIDUE_COUNT=0`,
`EXTERNAL_ROOT_RESIDUE_OK=True` (`<external-root>` altında yalnız
`<evidence-dir>` kalır) ve üç `git status` çıktısı **boş**. Aksi: tekrar
veya doğaçlama düzeltme yok, **DUR** (H46).

### 28.4 Silinmeyenler (Form F6)

Kaynak: Temel L3526–L3532. Sapma yok (form bağı eklendi).

DB journal satırları (`generation.fact_manual` dahil), `mutation.mutation_resources`
satırı, assignment satırı ve security event'ler **silinmez**; uygulama
rollerinin bu tablolarda `DELETE` yetkisi yoktur ve bu izler kasıtlıdır.
Metadata manifestleri, evidence kayıtları ve özet de kalır. Bu izlerin
kalması Form **F6**'da "Kabul" ile kabul edilmiş olmalıdır.

### 28.5 Şifreli arşiv (yalnız F2 arşiv ve F3 eksiksizse)

Kaynak: Temel L3534–L3597. **Sapma:** kapsam iki manifestle sınırlı;
arşiv kapısı **birebirdir**.

Arşivlemeden önce, aynı oturumda `<archive-dir>` denetlenir:

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

Beklenen: `PATH_OK=archive-dir`; aksi **DUR** (H52).

- Çalışma kopyası silinmeden **önce** arşivin paritesi, `# kind=case` ve
  `# kind=restricted` manifestlerinin her biriyle birebir doğrulanır;
  doğrulanamazsa **DUR** (H47).
- Parite doğrulaması düz metin bir kopyayı diske yazmadan yapılamıyorsa
  **DUR**.
- Şifreleme aracı bu runbook'ta **tanımlı değildir**; F3'teki yöntem bir
  araç ve sürümle bu runbook'a ayrı revizyonla eklenip incelenmeden arşiv
  yapılmaz (§32).
- Parite doğrulandıktan sonra F3/5 "silinsin" ise §28.3 uygulanır (F4
  kapısı ve silme günü şifreleme doğrulaması dahil); "korunsun" ise §28.1/5
  uygulanır.

### 28.6 Repo dışı geçici kopyalar (Form F1)

Kaynak: Temel L3599–L3603. **Sapma:** Form F1 süresi bağlandı.

Pilotta oluşmuş olabilecek ikinci kopyalar — E2 taşıyıcısı (USB veya
aktarım dosyası), E4 aracının ara ve çıktı dosyaları, indirme dizinindeki
kopyalar — Form **F1**'deki süre içinde (§23'teki "iş bitince" anından
itibaren) silinir. Bu adım (zincir adım 27) revoke, manifest ve case
silmesini (24–26) **beklemez** (§2.1 sıra istisnaları).

**Komut ve guard tanımlanmamıştır (bilinçli; §32).** Bu kopyaların yeri ve
adları önceden bilinmez ve adları gerçek içerik (ör. taraf adı) taşıyabilir;
§28.3 desenindeki gibi exact-path bir guard, bu adları komut satırına veya
evidence'a yazmayı gerektirirdi (§1.5, §4.2/8). Bu yüzden bu runbook bu
silmeler için PowerShell komutu veya mekanik guard **vermez**. Yerine
şu prosedür bağlayıcıdır:

1. **Listeleme.** Operatör kopyaları teslim ve metin çıkarma sırasında,
   oluştukları anda, repo dışında ve evidence dışında, yalnız kendisinin
   ve avukatın gördüğü bir **kâğıt veya çevrimdışı** listeye yazar (yer,
   tür, ortamın şifreli olup olmadığı; içerik değil). Evidence'a yalnız
   kopya **sayısı** girer.
2. **Ortam koşulu (F4 seçenek (1)).** Her kopya, §4.2/10'da şifreli olduğu
   doğrulanmış bir yerel sürücüde **veya** §6.4 taşıyıcı kontrolünden
   `E2_CARRIER_ENCRYPTED=True` ile geçmiş bir taşıyıcıda bulunmalıdır. Bu
   koşul kopya **oluştuğu anda** (madde 1) değerlendirilir; şifresiz bir
   ortamda oluşmuş tek bir kopya o anda **DUR**'dur (Y6) — zincir adım
   27'ye bırakılmaz. Şifresiz ortamdaki bir kopya standart silmeyle
   "silinmiş" sayılmaz; avukata bildirilir ve yöntemi avukatın yazılı
   kararıyla belirlenir.
3. **Silme yöntemi.** Her kopya, silme günü §4.2/10 yeniden doğrulamasından
   sonra, ayrı `REAL_ACTION_APPROVED` ile, tek tek, **geri dönüşüm kutusu
   kullanılmadan** silinir (Dosya Gezgini'nde Shift+Delete veya eşdeğeri).
   Klasör toplu silinmez; `<repo-root>`, `<external-root>`,
   `<evidence-dir>`, `<restricted-dir>` ve `<archive-dir>` altında hiçbir
   şey bu yolla silinmez.
4. **Kontrol.** Operatör listedeki her kopyanın artık bulunmadığını ve
   geri dönüşüm kutusunda olmadığını ekranda doğrular. Avukat listeyi ve
   doğrulamayı yazılı olarak onaylar; evidence'a yalnız onayın hash'i
   girer.

Evidence'a yalnız kopya **sayısı**, silinme zamanı,
`TEMP_COPIES_ON_ENCRYPTED_MEDIA=True/False` ve
`TEMP_COPIES_DELETED_WITHIN_F1=True/False` yazılır. Süre aşılırsa veya
madde 1–4'ten biri sağlanmazsa: **DUR** (Y6) ve olay avukata bildirilir.

### 28.7 İmha kaydı (Form F5)

YENİ. Her silme (case dizini, `<restricted-dir>`, §28.6 kopyaları) için bir
imha kaydı tutulur: **ne** silindi (kişisel veri içermeyen tanım ve
manifest hash'i), **hangi yöntemle** (F4), **ne zaman**, **kim
tarafından**. Kayıt Form **F5**'te belirtilen kişide/yerde, en az **3 yıl**
saklanır; repo'ya girmez. Evidence'a yalnız kaydın SHA-256'sı ve
`DELETION_RECORD_WRITTEN=True` yazılır. Kayıt yoksa pilot kapanmaz (Y6).

### 28.8 Müvekkilin silme talebi (Form F7)

YENİ. Müvekkil pilot sırasında veya sonrasında silme talep ederse talep
**en geç 30 gün** içinde sonuçlandırılır (Form F7 "Kabul"). Talep, zincirin
neresinde olunursa olsun bir **DUR** sebebidir (§25.2): yeni mutasyon
yapılmaz, veri §28.1–§28.3'e göre ve F4 kapısıyla silinir veya — F2 arşiv
ise — talebin arşivi de kapsayıp kapsamadığı avukatın yazılı kararıyla
belirlenir. Talebin tarihi ve sonuçlandırılma tarihi imha kaydına (§28.7)
yazılır.

---

## 29. Çıkarılan bölümler ve neden gerekmedikleri

| Temel bölüm (satırlar) | İçerik | Neden gerekmiyor |
|---|---|---|
| §13.6 (c) (L1538–L1545) | Çocuk süreç ortam profili | Çocuk süreç hiçbir anahtar veya ağ değişkeni okumaz; üst oturumun ad taraması üç kapsamda 0 olmak zorundadır (§13.6) |
| §13.7 (L1547–L1595), harness/monitor/probe kısmı | Pinli harness, monitor ve probe paritesi | Dış ağ işlemi yoktur; bu araçlar yalnız tek model POST'unu sınırlamak içindi (runtime paritesi §13.3'te kalır) |
| §13.9 (L1706–L1894) | Süreç başlatma yardımcısı, argv DLL, ortam profilleri | Yardımcı yalnız gerçek `--mask-term` değerlerini süreç argümanı olarak taşıyan iki çağrı içindi; B yolunda argümanlar opak kimlik, tamsayı, hex, sabit literal, mutlak yol ve opak `<attestation-ref>`'tir ve hiçbiri belge içeriği taşımaz (§1.5, §32/21); native `&` yeterlidir |
| §14 (L1898–L1956) | API credential (P3), `ANTHROPIC_API_KEY`, pano kuralı, revoke | Anahtar **oluşturulmaz**; ortamda anahtar bulunmaz (§13.6, §21) |
| §15.1–§15.4 (L1960–L2088) | Maskeleme ilkesi, tohum, `--mask-term`, gönderim yasağı | Veri makineden çıkmaz; takma adlandırma yalnız dış sağlayıcıya gönderim içindi |
| §15.5 (L2090–L2297) | Egress engel değerleri dosyası | Harness ve dış gönderim yoktur |
| §16 (L2301–L2377) | Egress harness, outer monitor, auth probe | Dış ağ işlemi yoktur; ağsızlık §21 ile ölçülür |
| §17 (L2381–L2457) | `fact_extraction` ağsız preview | Fact model tarafından değil, `manual-fact` ile girilir (§14.4); `fact_extraction` bu runbook'ta yasaktır (§14.7) |
| §18 (L2461–L2632) | Tek yetkili inference | Model çağrısı yoktur |
| §29 (L3607–L3628) | API anahtarı revoke ve ortam temizliği | Anahtar yoktur; kapanış ad taraması §13.6 (b) ve zincir adım 28'de kalır |
| §6.1/2, /3, /7 (L656–L664) | Sağlayıcı DPA, yurt dışı aktarım, kamu kurumu adının maskesiz aktarımı | Veri yurt dışına ve bir sağlayıcıya gitmez (form, "Bu yolda sorulmayan konular") |
| §7.1/2–/5 (L691–L717) | Dış aktarım veri kategorileri ve maskeleme sınırları | Aktarım yoktur; müvekkil bilgilendirmesi Form C ile yapılır (§7) |
| §10.5 izinli küme: `mask-terms.txt`, `egress-deny-values.txt`, harness çıktıları (L965) | `<restricted-dir>` dosyaları | Bu dosyalar oluşturulmaz; izinli küme yalnız rapordur |
| §13.8 probe/inference dizinleri (L1629–L1630, L1664) | `<external-root>` çocukları | Bu evidence dizinleri yalnız ağ turları içindi |
| §25.1 H10–H12, H14, H15, H32, H33, H38, H44, H49, H50, H57–H59 | Ağ, anahtar, maskeleme ve süreç yardımcısı DUR satırları | Tetikleyicileri bu yolda yoktur (§25.1'de "kaldırıldı" olarak işaretli) |
| §25.2/2–3 (L3036–L3040) | Process anahtarı ve Console revoke | Anahtar yoktur |
| §30/6, /10 (L3648–L3659) | Anahtar revoke; "iki dış ağ işlemi" | Anahtar yoktur; beklenen dış ağ işlemi **sıfırdır** (§30) |
| §32/2, /5, /9, /14 (kısmen), /15, /16, /21, /27–/31 | Maskeleme, tek POST, egress, argv ve SDK sınırları | Karşılık gelen mekanizmalar bu yolda yoktur |

---

## 30. Kapanış postcondition'ları

Kaynak: Temel L3632–L3671. **Sapmalar:** anahtar satırı çıkarıldı; dış ağ
işlemi sayısı sıfır; F1/F5 ve `fact_extraction` satırları eklendi; disk
şifrelemesi ve form hash satırı (13) eklendi.

Hepsi mekanik olarak ölçülür ve evidence'a yazılır:

1. `data/cases/<case-id>` mevcut değil: §28.3.1'de
   `CASE_DELETE_RESULT=COMPLETED` ve `CASE_DIR_ABSENT=True`.
2. `git status --ignored --porcelain -- data/cases` boş;
   `git status --porcelain -- data/cases/case_0001` boş.
3. `git status --porcelain=v1 --untracked-files=all` boş; HEAD başlangıçtaki
   commit.
4. `case:<case-id>` için aktif assignment **0**; journal'da `prepared`,
   `executing` veya `reconciliation_required` satırı **0**.
5. Yeni journal satırları yalnız §26.3'teki yedi aile için ve `completed`
   durumunda (yalnız §14.6 yolundan geçildiyse ayrıca kayda geçirilmiş
   `failed` satırlar).
6. §14.7 SQL'i: `generation.fact_extraction` satırı **0**.
7. Evidence dizininde gerçek içerik, rapor metni, gerçek tarih veya sayfa
   numarası yok; özet, `restricted-allowed-files.txt`,
   `restricted-allowed-files.sha256.txt`, `intake-hashes.tsv`,
   `manual-input-r*.sha256.txt` ve iki kapanış manifesti mevcut.
8. `<restricted-dir>` mevcut değil: `RESTRICTED_DIR_ABSENT=True`,
   `RESTRICTED_RESIDUE_COUNT=0`, `EXTERNAL_ROOT_RESIDUE_OK=True`.
9. `PENDING_MATCH` (§18.3) ve `MATCH` (§20).
10. **Toplam dış ağ işlemi: sıfır** (§21 tablosunun bütün satırları
    beklenen değerde; §13.6 kapanış taraması üç kapsamda 0).
11. İçerik penceresi kapandı: gerçek verinin yerel çalışma kopyası ve repo
    dışı geçici kopyalar artık diskte değil (`TEMP_COPIES_DELETED_WITHIN_F1=True`);
    §4.3 kanal kapısı kaydı pencere boyunca kesintisiz
    `AI_CONTENT_CHANNELS_CLOSED=True` gösteriyor.
12. İmha kaydı yazıldı (`DELETION_RECORD_WRITTEN=True`, §28.7).
13. Her silme günü için §4.2/10 doğrulaması evidence'ta
    (`FULL_DISK_ENCRYPTION_CONFIRMED=True`; harici disk çiftinde tam bir
    `True`); E2 taşıyıcısı için `E2_CARRIER_ENCRYPTED=True` (kâğıt
    dışında); F1 kopyaları için
    `TEMP_COPIES_ON_ENCRYPTED_MEDIA=True`; form ve G bölümü hash'lerinin
    kapanış yeniden ölçümü kayıtla aynı (§6.6/7).

Veri §28.1/6 gereği korunuyorsa veya F3/5 "korunsun" ise 1., 8. ve 11.
koşullar sağlanmamıştır; pilot **kapanmamıştır** (Temel L3665–L3671 ile
aynı kural; arşiv durumunda `ARCHIVE_VERIFIED_WORKING_COPY_RETAINED`
yazılır).

---

## 31. Roadmap LOCK kabul kriterleri

Kaynak: Temel L3675–L3693. Sapma yok.

Adım 10 B yolu ancak şunların **hepsi** sağlandığında LOCK için
önerilebilir:

1. §30'daki bütün postcondition'lar PASS.
2. §25.1'deki hiçbir DUR tetiklenmemiş veya tetiklenen her DUR için §25.2
   yolu tamamlanmış ve kullanıcı tarafından yazılı olarak kapatılmış.
3. Evidence özeti ve hash'leri tam.
4. Yürütmeden ayrı bir oturumda bağımsız inceleme blocking bulgu vermemiş.
   İnceleyici gerçek içeriği görmez; yalnız metadata-only evidence ile
   çalışır.
5. Kullanıcının açık LOCK onayı.

LOCK kaydı ayrı bir roadmap-lock turunda yapılır (`CLAUDE.md` §5 "Bundan
sonra" kuralı) ve yalnız hash'ler, sayaçlar ve redakte kapsam özetleri
taşır.

---

## 32. Açık sınırlar

1. **Prova henüz yapılmadı.** Bu belgedeki PowerShell, `psql` ve CLI
   komutlarının hiçbiri çalıştırılmamıştır. §1.6/3 sentetik provası
   zorunludur; provada yazıldığı gibi çalışmayan bir komut runbook
   düzeltmesi ve yeniden inceleme gerektirir. Prova veritabanı kararı
   açıktır (§1.6). Runtime paket kümesi karşılaştırmasının exact komutu
   tanımlı değildir (§13.3).
2. **L-E — tanınmayan hata ham traceback verir.** Writer yalnız motor
   hatalarını, `OSError`, `ValueError` ve containment hatasını tanınan
   sınıfa çevirir (`ui/services/manual_fact_mutation_facade.py:955-959`);
   başka bir istisna ve bilinçli olarak `ManualFactPostWriteInvariantError`
   (`src/manual_fact_entry_engine.py:209-213`) ham traceback olarak
   görünür (`ui/cli_mutate.py:1289-1290`). Traceback mutlak yol ve içerik
   taşıyabilir; çıkış kodu tanınan hatayla aynıdır (`1`). Satırın
   `reconciliation_required` kalıp kalmadığı yalnız §14.6 adım 2 SQL'iyle
   ayırt edilir.
3. **K-12 — iki kişi kuralı kodda yok.** `manual-fact`, `promotion` ve
   `verification` aynı IAM aktörüne izin verir; görev ayrılığı yalnız bu
   runbook'un kuralı ve evidence beyanıyla sağlanır (§4.1). Journal'daki
   `actor_user_id` bunun kanıtı değildir.
4. **O-1 — timeline promotion doğrulamayı yalnız writer içinde yapar.**
   Geçersiz bir timeline pending'i promotion'da `reconciliation_required`
   üretip case'i gate'leyebilir (exact-scope §3.3, §8/9). Bu yolda timeline
   pending'i deterministik olarak üretilir; risk bu runbook'la kapanmaz,
   yalnız §16 kapılarıyla sınırlanır.
5. **L-A — yarım audit riski.** Audit yazımı sırasında süreç sert biçimde
   sonlanırsa (güç kesintisi, süreç öldürme) yarım veya boş bir audit
   kalabilir; engine onu yalnız süreç hayattayken siler
   (`src/manual_fact_entry_engine.py:633-639`). Ayrıştırılamayan bir audit,
   o belgenin `generation_reviews` dizininde manuel ve LLM ailelerinin
   post-state kanıtını kalıcı olarak `False` yapar
   (`ui/services/manual_fact_mutation_adapters.py:279-280`). Repoda bunu
   çözen bir araç yoktur; §14.6 bu durumda yeniden denemeyi yasaklar.
6. **Reconciliation operatörü pilot kümesinde hiç çalıştırılmadı** ve
   `new_state=reconciliation_required` kalan bir satırı elle çözme yolu
   yoktur (exact-scope §1/4); case o durumda gate'li kalır.
7. **`fact_extraction` için kod guard'ı yok** (K-14); yalnız §14.7 DUR satırı
   ve kapanış SQL'i vardır.
8. **Alıntı OCR metnine karşı eşleşir**, orijinal belgeye karşı değil;
   orijinalle karşılaştırma avukatındır. Metinde tarih yanlış okunmuşsa
   veya tarih `GG.AA.YYYY`/`GG/AA/YYYY` dışında yazılmışsa (ör. `16 Mart
   2026`) manuel giriş yapılamaz; metin dosyası bu çalıştırmada
   düzeltilemez (§11.3 b). Biçim teslimden önce Form G9 ile ve intake'te
   §11.3 (b) token ön kontrolüyle kapılanır; ön kontrol yalnız **bir**
   tanınabilir token'ın varlığını gösterir, onun tebliğ tarihi olduğunu veya
   doğru okunduğunu göstermez (o avukatın §11.4/1 onayıdır).
9. **Sayfa ile alıntının aynı sayfada olduğu kodla denetlenmez**; yalnız
   avukatın karşılaştırmasıyla sağlanır (§14.2/5).
10. **`page_count` dolduran kod yok**; değer operatör tarafından yazılır ve
    avukat tarafından onaylanır (§11.2/5, §11.4/3).
11. **Silme yöntemi:** tanımlı tek yöntem Form F4 seçenek (1)'dir:
    `Remove-Item` / geri dönüşüm kutusu kullanılmadan standart silme. Bu
    yöntem içeriğin üzerine **yazmaz**; gizlilik tamamen verinin şifreli bir
    sürücüde veya şifreli taşıyıcıda bulunmasına dayanır (§23). Şifreleme
    anahtarı ele geçirilirse veya şifreleme kapsamı dışında bir kopya
    oluşmuşsa (sayfa dosyası, hazırda bekletme dosyası şifresiz bir
    bölümdeyse, antivirüs karantinası; madde 18) silinmiş veri
    kurtarılabilir. F4 seçenek (2) için araç tanımlı değildir; seçilirse
    pilot ayrı bir runbook revizyonuna kadar başlamaz. Şifreli arşiv aracı da
    tanımlı değildir (§28.5).
12. **Tam disk şifrelemesi** (Form E1) bu runbook'ta bir komutla
    ölçülmez; operatörün Windows "Cihaz şifrelemesi" sayfasını, BitLocker
    Sürücü Şifrelemesi ekranını veya üçüncü taraf aracın arayüzünü ekranda
    okumasına dayanır (§4.2/10). Bu cihaz runbook yazılırken Windows 10
    Home'dur; BitLocker yönetimi yoktur (Pro yükseltmesi planlanmış, henüz
    yapılmamıştır) ve "Cihaz şifrelemesi" yalnız destekleyen donanımda
    bulunur ve yalnız sistem sürücüsünü kanıtlar. Üç yoldan hiçbiri yoksa
    pilot bu cihazda yapılamaz. Ekran okuması yanlış okunabilir veya arayüz
    gerçeği yansıtmayabilir; bu doğrulama kriptografik bir kanıt değildir.
    Harici diskin "fiziksel olarak çıkarılmış" olması da yalnız operatörün
    gözlemine ve beyanına dayanır; pencere içinde yeniden takılması mekanik
    olarak izlenmez. E2 taşıyıcısının şifreli olduğu da ekran gözlemiyle
    (parola/kilit açma adımı) kaydedilir (§6.4).
13. **Ağsızlık bir işletim sistemi sandbox'ı değildir.** §21, ağ açabilecek
    kod yolunun kullanılmamasına ve anahtar yokluğuna dayanır; üçüncü taraf
    yazılımların (antivirüs, EDR, yedekleme, işletim sistemi telemetrisi)
    ağ davranışı ölçülmez. Sistem proxy ayarı ad taramasında görünmez.
14. **Audit ayrıştırma ön kontrolü yaklaşıktır** (PowerShell
    `ConvertFrom-Json` ile Python `json.loads` birebir aynı değildir);
    bağlayıcı sonuç reconciliation dry-run'ıdır (§14.6).
15. **`replayed=True` normal yolda oluşmaz** ama eşzamanlı iki apply'da
    yapısal olarak mümkündür (exact-scope §10 N-L3); bu runbook tek
    operatör ve tek oturumla bunu dışlar ve görülürse DUR'dur.
16. **Hash tek başına gizlilik sağlamaz** (Temel §32/19): rapor, kör hesap
    kaydı ve girdi dosyası düşük entropili tarihler taşır; hash'leri
    yalnız evidence'ta, gerçek içerik yalnız kısıtlı konumlardadır.
17. Pilot **production-ready iddiası değildir**; sonuç **hukuki karar
    değildir**; süre aşımı **değerlendirilmez**; sekiz event-specific hukuki
    aritmetik modellenmemiştir; fact bazında düzeltme yazıcısı yoktur; IAM
    aktörü avukatın kimliğini veya imzasını kanıtlamaz; advisory-lock
    bounded acquisition açıktır (`CLAUDE.md` §6); revoke CLI idempotent
    değildir; Windows 8.3 kısa adları yol kapısında modellenmemiştir
    (Temel §32/1, /3, /4, /6–/8, /11, /12, /26).
18. Kalıcı ikincil kopyalar (sayfa dosyası, antivirüs karantinası, yedekleme
    yazılımı) mekanik olarak **denetlenemez** (Temel §32/14).
19. Web arayüzü ve Entra login Adım 11'e, hosting ve Key Vault Adım 12'ye
    aittir; Row 19D ve Adım 11–13 açıktır.
20. Avukat formu (v3) bu belge yazılırken **doldurulmamıştı**; her form
    kapısı cevabı varsaymadan DUR olarak yazılmıştır (§6.1).
21. **Komut satırında mutlak yollar ve `<attestation-ref>` geçer** (§1.5):
    belge içeriği değildir, ama mutlak yollar Windows kullanıcı profil
    adını taşıyabilir; süreç-oluşturma komut satırı denetimi açıksa bu ad
    kayda geçer (§4.2/9). Bu runbook bunu önlemez; yalnız kullanıcı
    profil adının kişisel veri taşımadığı bir hesapla çalışılmasını önerir.
22. **F1 geçici kopyaları için komut ve exact-path guard yoktur**
    (§28.6). Silme, operatörün çevrimdışı listesine ve ekran
    doğrulamasına dayanır; mekanik bir "tümü silindi" kanıtı üretilmez.
    Listeye girmemiş bir kopya (ör. bir uygulamanın kendi önbelleği)
    tespit edilemez.
23. **İmza ve tarih doğrulaması mekanik değildir** (§6.6): operatör imzanın
    biçimini (taranmış PDF / e-imza) ve tarih sırasını denetler; imzanın
    kime ait olduğunu, e-imzanın geçerliliğini veya tarihlerin gerçekliğini
    doğrulamaz.
24. **Avukat kararı ile girdi sürümü arasındaki bağ 12 hex karakterlik
    önekle kurulur** (§14.3): önek, aynı sürüm numarasında kazara değişimi
    yakalar; kriptografik bir imza değildir.

---

## 33. İnceleyici için yorum tercihleri ve kaynak atıf listesi

### 33.1 Yorum tercihleri (sessizce seçilmedi; inceleyicinin değerlendirmesi için)

1. **`manual-fact` apply için ayrı `REAL_ACTION_APPROVED`** (§2.1 adım 11).
   Temel runbook pending üreten adımları ayrı onaysız bırakır; bu adım gerçek
   veriden insan girdisiyle ilk sistem kaydını oluşturduğu ve iki kişi
   kuralı kodda olmadığı için daha sıkı tutuldu.
2. **Girdi düzeltme döngüsü** (§14.5.3). Preview/PL/PC aşamasındaki girdi
   reddi, "elle dosya düzeltmesi yok" genel kuralına istisna olarak, yalnız
   girdi dosyası için ve avukatın yazılı kararı + yeni karşılaştırmayla
   izinlidir. Hiçbir journal satırı oluşmamışken uygulanır.
3. **En fazla bir yeniden deneme** (`--attempt 2`) ve validator kaynaklı kök
   hatada yeniden deneme yasağı (§14.6/7). Kodda böyle bir sınır yoktur; bu
   bir runbook sınırıdır.
4. **Temp artığının kaldırılması** (§14.6/6) runbook'a guard'lı tek-dosya
   silme olarak eklendi. Gerekçe **dardır**: yeniden deneme (§14.6/7) yalnız
   kök hata geçici G/Ç (`OSError`/`PermissionError`) iken açıktır ve temp
   artığı bu durumda yalnız writer'ın rollback'indeki temp silmesi
   başarısız olduğunda (ör. antivirüs kilidi;
   `src/manual_fact_entry_engine.py:709-717`) kalır; aksi hâlde M-14 bu
   yeniden denemeyi kalıcı olarak kapatırdı. Sert çökmeden (güç kesintisi,
   süreç öldürme) kalan bir artık bu kuralla yeniden denemeyi **açmaz**: o
   kök hata izinli listede değildir ve §14.6/7 DUR verir. Guard, journal
   satırının `failed` olduğunu, audit sayımını ve temp SHA eşleşmesini
   mekanik olarak ölçer; SHA uyuşmazlığı DUR'dur.
5. **Girdi sürüm hash kaydı** (`manual-input-r<input-revision>.sha256.txt`,
   §14.3) avukatın karşılaştırmasını exact baytlara bağlamak için eklendi;
   koddaki `input_digest` bu bağın yerine geçmez, çünkü avukat digest'i
   değil dosyayı onaylar.
6. **F4 kapısının teslimden önce** değerlendirilmesi (§23): yöntem
   tanımsızsa veri silinemez hâlde kalacağı için. Form v3 ile yalnız
   seçenek (1) yürütülebilirdir ve E1 = "Evet" + yürütme günü şifreleme
   doğrulamasına bağlıdır (kullanıcı kararı, 2026-10-08).
7. **§13.9'un tamamen çıkarılması.** Görev metni "yalnız ağ için gereken
   kısımlar" diyordu; süreç yardımcısının kalan kısmı (argv sadakati) da
   yalnız `--mask-term` değerleri içindi ve bu yolda karşılığı yoktur
   (§29).
8. **Kopyalama vs atıf.** Ortak bölümler atıf yerine kopyalandı (§0); her
   kopyada kaynak aralık ve sapmalar yazılıdır.
9. **G7 (60.000 karakter)** manuel motorda kod sınırı olmadığı hâlde formun
   kriteri olarak korundu (§8).
10. **Zincir adım 27 (F1 silmesi)** 24–26'yı beklemez; aksi hâlde kısa bir F1
    süresi (ör. 24 saat) revoke ve guard'lı silmelerin onay süresiyle
    yapısal olarak aşılırdı (§2.1 sıra istisnaları).
11. **"İş bitince" anı** zincir adım 23'ün tamamlanması veya abort yolunun
    başlaması olarak tanımlandı (§23); form bu anı tanımlamaz.
12. **Disk şifrelemesi doğrulama yolları** (§4.2/10): Windows "Cihaz
    şifrelemesi" sayfası (yalnız sistem sürücüsü), BitLocker (Pro
    yükseltmesinden sonra; kullanıcı kararı, 2026-10-08) veya üçüncü taraf
    tam disk şifreleme aracı. Form v3 E1 araç adı sormadığı için BitLocker ve
    üçüncü taraf aracın kabulü avukat yerine kullanıcıya bağlandı; kabul
    zincir adım 4'te `REAL_ACTION_APPROVED` ile alınır ve
    `ENCRYPTION_TOOL_USER_ACCEPTED=True` olarak yazılır. Avukat E1'e bir
    araç veya koşul yazdıysa bu §6.1 gereği ek koşuldur ve runbook
    revizyonuna kadar DUR'dur; sahada yorumlanmaz. Doğrulama yürütme günü
    ve her silme günü, tam kapsamla tekrarlanır.
13. **F1 kopyaları için komut/guard tanımlanmadı** (§28.6, §32/22): exact-path
    guard, içerik taşıyabilen dosya adlarının komut satırına veya evidence'a
    girmesini gerektirirdi. Yerine çevrimdışı liste, şifreli ortam koşulu,
    Shift+Delete ve avukatın yazılı onayı kullanıldı.
14. **Girdi düzeltme döngüsü en fazla iki tur** (`<input-revision>` ≤ 3;
    kullanıcı önerisi). Sınır §14.3/1 bloğunda mekanik olarak uygulanır.
15. **Avukat kararının girdi hash önekini anması** (§14.3): önek
    `<lawyer-cited-prefix>` yer tutucusuyla mekanik olarak karşılaştırılır;
    12 karakter seçildi (insan tarafından aktarılabilir, kazara değişimi
    yakalar).
16. **G bölümünün ayrı imzası** (form v3): G10 tarihi bağlayıcı I3'ten önce
    olamaz; A–F yeniden imzalanırsa G de yeniden imzalanır (§6.6/4). Tarih
    sırası avukat beyanıyla desteklenir; mekanik değildir.
17. **Tarih token'ı ön kontrolü hash kaydına bağlandı** (§11.3 b): `False`
    sonucunda hash kaydı hiç yazılmaz; metin dosyası kalıcı olarak
    sabitlenmeden DUR verilir.
18. **Harici disk kuralı** (§4.2/10; kullanıcı kararı, 2026-10-08): bu
    cihazdaki harici USB disk içerik penceresi boyunca ya şifreli ya da
    fiziksel olarak çıkarılmış olur; hangisi olduğu boolean çiftiyle
    kaydedilir ve tam biri `True` olmalıdır.
19. **E2 taşıyıcı kontrolü teslimden önce** (§6.4): şifresiz bir taşıyıcı
    belge cihaza aktarılmadan DUR verir; böylece §28.6/2'deki geç DUR
    öngörülebilir bir son adım hatası olmaktan çıkar.
20. **Girdi sürümleri sıralıdır** (§14.3/1): `r<N>` için `r1`…`r<N-1>`
    kayıtlarının hepsi mevcut, `r<N>`…`r3` kayıtlarının hiçbiri mevcut
    olmamalıdır; atlama DUR'dur.
21. **Form hash satır biçimi** (§6.6/7): `FORM_HASH` ve `FORM_BINDING`
    satırları; A–F ve G aynı dosyadaysa `unit=AFG` ve iki bağlayıcılık
    satırı. AF→AFG geçişi yalnız avukatın yazılı beyanıyla A–F'nin yeni
    sürümü sayılmaz.

### 33.2 Kaynak atıf listesi (inceleyici için)

Bütün atıflar commit `2c318ac`'taki dosyalaradır.

| Kaynak | Satırlar | Kullanıldığı yer |
|---|---|---|
| `ui/cli_mutate.py` | 141–143 (çıkış kodları) | §14.5.3 |
| `ui/cli_mutate.py` | 152–155 (yetkilendirme reddi mesajı) | §14.5.3 |
| `ui/cli_mutate.py` | 525–546 (`manual-fact` ayrıştırıcısı, ağ bayrağı yok) | §1.2, §5/7, §14.4, §14.5.1, §21 |
| `ui/cli_mutate.py` | 1130–1153 (`_validate_manual_fact_args`) | §14.4, §14.5.1 |
| `ui/cli_mutate.py` | 1190–1214 (ayrıştırma ve kullanım dalı) | §14.5.3 |
| `ui/cli_mutate.py` | 1279–1292 (yetkilendirme reddi, tanınan hata, traceback) | §14.5.3, §32/2 |
| `ui/cli_mutate.py` | 1336–1380 (promotion preview çıktısı, `validation_ready`) | §15.2 |
| `ui/cli_mutate.py` | 1865–1906 (`_run_manual_fact` preview/apply çıktısı) | §4.2/8, §5/8, §14.4, §14.5.2 |
| `src/manual_fact_entry_engine.py` | 1–49 (sınırlar, yazım sırası, rollback) | §14.1, §22.2 |
| `src/manual_fact_entry_engine.py` | 85–107 (sabitler, dosya adları, notlar) | §11.2, §14.2, §14.5.2, §15.1 |
| `src/manual_fact_entry_engine.py` | 116–117, 230–256 (tarih deseni, anahtar tekrarı, normalizasyon) | §14.2 |
| `src/manual_fact_entry_engine.py` | 160–213 (hata hiyerarşisi, kural kodları) | §14.5.3 |
| `src/manual_fact_entry_engine.py` | 272–342 (girdi, kodlama, tarih) | §14.2 |
| `src/manual_fact_entry_engine.py` | 349–376 (belge türü, aktiflik, `page_count`) | §8, §11.2 |
| `src/manual_fact_entry_engine.py` | 383–430 (metin, alıntı, alıntı tarihi) | §11.2, §14.2 |
| `src/manual_fact_entry_engine.py` | 442–500 (deterministik extraction, `<fact-id>`) | §1.5, §14.1, §15.1, §16 |
| `src/manual_fact_entry_engine.py` | 616–639 (audit adı, yarım audit silme) | §14.5.2, §14.6, §32/5 |
| `src/manual_fact_entry_engine.py` | 683–717 (dizin oluşturma, writer, rollback; 679–681 audit'e `pending_sha256` eklenmesi; 709–717 rollback silmeleri) | §11.2, §14.1, §14.5.2, §33.1/4 |
| `src/manual_fact_entry_engine.py` | 406–430 (alıntı tarih token'ları, M-08) | §8 (G9), §11.3 (b) |
| `ui/services/manual_fact_mutation_facade.py` | 917–939 (audit kaydı alanları) | §14.5.2 |
| `data/manual_fact_input.schema.json` | 7–86 | §10.3, §14.2 |
| `ui/services/manual_fact_mutation_facade.py` | 20–28 (kural yerleri, mesaj sözleşmesi) | §4.2/8, §14.1 |
| `ui/services/manual_fact_mutation_facade.py` | 102–103 (`target_ref`) | §10.3 |
| `ui/services/manual_fact_mutation_facade.py` | 117–220 (hata sınıfları ve çeviri) | §14.5.3 |
| `ui/services/manual_fact_mutation_facade.py` | 228–235 (argüman şekli) | §10.3 |
| `ui/services/manual_fact_mutation_facade.py` | 314–353 (belge taraması) | §11.2/10 |
| `ui/services/manual_fact_mutation_facade.py` | 504–520 (M-09, M-10, M-14) | §14.5.3 |
| `ui/services/manual_fact_mutation_facade.py` | 530–626 (değerlendirme, manifest, M-13) | §11.2, §14.2, §14.4 |
| `ui/services/manual_fact_mutation_facade.py` | 634–681 (yetkilendirme ve preview) | §1.6, §12.3, §14.4 |
| `ui/services/manual_fact_mutation_facade.py` | 779–780 (replay: ayrıştırılamayan audit) | §14.6, §32/5 |
| `ui/services/manual_fact_mutation_facade.py` | 817–1035 (apply sırası, writer hata çevirisi, journal mesajı) | §14.5, §14.6, §32/2 |
| `ui/services/manual_fact_mutation_adapters.py` | 30–32, 279–280 | §14.6, §32/5 |
| `ui/reconciliation_operator.py` | 14–21, 110–112, 198–210, 304–308, 362–383 | §1.5, §14.6 |
| `ui/services/mutation_coordinator.py` | 178–200 (`PriorAttemptFailedError`) | §14.6 |
| `ui/services/promotion_mutation_facade.py` | 222–241, 840–844, 933–936 (K-16) | §15.2 |
| `src/fact_approval.py` | 122 (pending adı), 429–449 (K-3) | §14.5.2, §15.1, §15.2 |
| `src/fact_extraction_engine.py` | 700 (`preserve_previous_pending`) | §14.7 |
| `src/manual_fact_entry_engine.py` | 62 (`Draft202012Validator`) | §13.3 |
| `src/case_fact_validator.py` | 43–44 (aynı sınıf, Adım 9'da koştu) | §13.3 |
| `db/migrations/0006_iam_runtime_privileges.sql` | 208 | §12.4 |
| `docs/operations/concierge-real-case-pilot.md` (Temel) | Her kopyalanan bölümün başında | Bütün belge |
