# Yerel Gerçek Dava Pilotu (B Yolu) — Operatör Runbook'u

**Pilot Readiness Adım 10 / B yolu.** Bu belge, ilk gerçek vergi dosyasının
concierge modelde, tek dava ve tek tebliğ sınırı içinde, **tamamen yerel**
ve fail-closed biçimde işlenmesi için **operatör talimatı taslağıdır**.

> **Bu belge yazılırken hiçbir komut çalıştırılmamıştır.** Belge ve
> revizyonu (§34) yazılırken hiçbir CLI, `psql`, Python veya PowerShell
> betiği çalıştırılmadı; hiçbir gerçek belge alınmadı; hiçbir veritabanı
> satırı yazılmadı; hiçbir ağ isteği yapılmadı; hiçbir API anahtarı, `.env`
> veya passfile okunmadı. Komut bloklarının yanındaki kaynak atıfları yalnız
> repo kaynağının **okunmasıyla** türetilmiştir. `13f19d0` sürümünün
> komutları ayrı bir sentetik provada çalıştırılmıştır (§0); revizyon
> 1'in (`4f5c37e`) yeni ve değişen blokları §34.4 eşlemesine göre delta
> provasında (e11bab73, §0) çalıştırılmıştır. Revizyon 2'nin (§34.8) değişen ve yeni
> blokları delta2 provasında (709b329c, §0) ölçülmüş, prova
> `STOPPED_ON_UNEXPECTED_RESULT` ile bitmiş ve bulguları revizyon 3'e
> (§34.9) işlenmiştir. Revizyon 3'ün değişen ve yeni blokları (N4, N16,
> N17 ve Ek R3) için delta3 provasının Faz A'sı (86c4a7da, §0) A.0–A.9'u
> geçmiş, A.10'da `STOPPED_ON_UNEXPECTED_RESULT` ile durmuştur; kök neden
> N105 (`ac.ps1`) temizlik satırıdır ve revizyon 4'te (§34.10)
> düzeltilmiştir. Revizyon 4'ün kiti delta3 yeniden koşusunda
> (d9d67b7d, §0) insan penceresi 1'in `a4` adımına kadar çalıştı ve orada
> TEMP yönlendirmesi atlandığı için kilitlendi; **kit hâlâ uçtan uca
> çalıştırılmamıştır**. Revizyon 5'te (§34.11) değişen ve yeni bloklar
> yalnız PowerShell ayrıştırıcısı (`ParseInput`), AST taraması ve hash ile
> denetlenmiştir (AST taramasına N116'nın runbook'tan çıkarılmış kopyalar
> üzerinde çalıştırılması dahildir; N116 kurulum bağlamında
> çalıştırılmadı);
> revizyon 3/4/5 blokları bir sonraki delta provasına
> tabidir (§32/1).

---

## 0. Kaynak pinleri ve atıf biçimi

| Kaynak | Pin |
|---|---|
| Repo | `claude-dev`, HEAD `2c318ac` ("Add manual notification-date fact entry (generation.fact_manual)") |
| Temel runbook | `docs/operations/concierge-real-case-pilot.md` @ `2c318ac`, git blob `c2fee2d473df5f4b061c18de259cdacb469ff02f`, 3866 satır. Aşağıda **"Temel §N"** veya **"Temel L<a>–L<b>"** olarak anılır |
| Kod | Commit `2c318ac`: `ui/cli_mutate.py` (`manual-fact` alt komutu), `src/manual_fact_entry_engine.py`, `data/manual_fact_input.schema.json`, `ui/services/manual_fact_mutation_facade.py`, `ui/services/manual_fact_mutation_adapters.py` |
| Exact-scope | `vergi_step10_manual_fact_exact_scope_4161a431/exact-scope.md` (repo dışı); K-12, K-13, K-14, K-17, K-18, M-01…M-15 kodları oradan gelir |
| Kapsam çalışması | `vergi_step10_local_scope_92233ccf/scope.md` (repo dışı); §4 runbook bölüm sınıflaması oradan gelir |
| Avukat formu | **Sürüm 5** ("Yerel Pilot Hukuki Protokol İnceleme ve Onay Formu — Sürüm 5", 9 Ekim 2026; v3'ün yerine geçer). Protokol inceleyicisinin e-imzalı A–F + I birimi: UDF dosyası (repo dışı), SHA-256 `fd1d21aa31703303cead76b8e1b0d7ce78662386b0e31848c63c7b1c3a11f2a2`. Bu hash yürütmedeki `FORM_HASH unit=AF seq=1` satırının beklenen değeridir (§6.6/9). Ayrı imzalanan G bölümünün ve eklerin (Ek 1, Ek 2) hash'leri yürütmede ayrıca ölçülür (§6.6). v2 ve v3 bu runbook'ta kullanılmaz |
| Avukat kararı | DRAFT-4 SORU 6.7: "Gerçek müvekkil dosyası + tamamen local processing → KABUL, dar kapsamlı pilot" |
| Sentetik prova | `vergi_step10_local_rehearsal_ae129016` (repo dışı; plan v3 SHA-256 `587b45d953a1a018ac8783aa6362e3890b68277ab7085389a8f80cbe2de7df6e`), runbook `13f19d0` üzerinde. Özet `run\summary.md` SHA-256 `30c630c7bbb83caf7e882c8371b00b6b29a1db6babd814d0f697f03ad6ddeac0` |
| Prova incelemesi | Aynı kökte `run\review\20261010-independent-review.md`, SHA-256 `62e80d52d563c23c0b3bd459c8383f2989d1a6dc9f1bbe9ffa5578392bfbe640` (verdict `REHEARSAL_EVIDENCE_VERIFIED`; 207 dosyanın tam hash manifesti) |
| Delta prova (revizyon 1) | `vergi_step10_delta_e11bab73` (repo dışı), runbook `4f5c37e` (blob SHA-256 `1397ea07ad0c56e689d073ccbfc0b74177edc39847c5895f69596b1bf9f08699`; `c2a7dbc` ile aynı) üzerinde. Plan v7 SHA-256 `237990f4e6585ad567c02080c5e37183faa196a4c9a94471a2b12d8dd4378d08`; özet `run\summary-r2.md` SHA-256 `97df1d1f5e3e7a19cda95a37d8b94d90a4d11b72aa7a3bfcbd38af19b8f3ce86`; inceleme `run\review\20261012-161035-independent-review.md` SHA-256 `29d0038d4b4d65b39679b1cdceb69f1c04fa3e48436ba60c0060563cba4e6352` (verdict `REHEARSAL_EVIDENCE_VERIFIED`; 270 dosyanın tam hash manifesti) |
| Delta2 prova (revizyon 2) | `vergi_step10_delta2_709b329c` (repo dışı), runbook `977a5e7` üzerinde. Plan `vergi_step10_delta2_plan_3612696e\plan_v4.md` SHA-256 `7a85200d6ae92872e09f949308cc3b7548102f4efc2bf095037365e72ea2651c`; `run\findings.md` SHA-256 `ac1638fe796e5eb6f57b8403bf2eaffff9763850c3d49e1bad73503bffdab5e1`; `run\summary.md` SHA-256 `fdae7cba84fbdc4e8141f8231ee254935ae26adf96df77f42fee4fbcadbca587` (sonuç `STOPPED_ON_UNEXPECTED_RESULT`); inceleme `run\review\20261013-002359-independent-evidence-review.md` SHA-256 `94eb7299a9e4c5f74391c3edcd24b1ac5c5eea641762dec46386314cf41bfd51` (verdict `REHEARSAL_EVIDENCE_VERIFIED`; C0/H1/M2/L4/O6) |
| Revizyon 3 kapsamı | `vergi_step10_rev3_scope_e358b2d8\scope.md` SHA-256 `ed7fc1188e36438078dcbd8ec7b9975893bb3dbb4b78fc779c2fd503bcb5774a` ve `scope_addendum.md` SHA-256 `ed0b9792d992b4ecff9b0ee6583283af9e11713aca05ce735bc0c0eec37486e9` (repo dışı; çelişkide ek geçerli) |
| Delta3 prova Faz A (revizyon 3) | `C:\vd3_86c4a7da` (repo dışı; kök `86c4a7da`), runbook `fae0347` üzerinde; plan `plan_v4.md` SHA-256 `8fb46355fa032b99b0941d90833278f6719c780b9c64cd0dae356bd418436140`. Kapanış notu `run\close-delta3-run-a.txt` SHA-256 `90dfc08558978b80dce8ebb5981aaff8b783782e1c410597722b36420e318d13`; A.10 kaydı `run\stages\A\A.10.txt` SHA-256 `ae62bcb1d0e2cc6ef17b97b0c7f83a1bf9f823bfc6458a34c55e4cebbb161f5a`. Sonuç: A.0–A.9 PASS, A.10 `STOPPED_ON_UNEXPECTED_RESULT`; A.11–A.16 ve insan penceresi çalıştırılmadı; kök neden N105 (§34.10) |
| Revizyon 4 incelemesi | `vergi_step10_rev4_review_56d54d8b\independent-runbook-rev4-review.md` SHA-256 `9ab9e8ba20f06d4d4997a237ffe6962823cf705dc861afec0b8c3a825a9089c7` (repo dışı; ara sürüm `b9de07df…b720` üzerinde; `READY_FOR_COMMIT=YES`, 0C/0H/0M/2L/3O; bulgular §34.10'da işlendi) |
| Delta3 prova yeniden koşusu (revizyon 4) | `C:\vd3_d9d67b7d` (repo dışı; kök `d9d67b7d`), runbook `5153593` (SHA-256 `a00d89e5d69100cf4af1e0d20723a6d358e74c2b68e89b50b767b76a9e29caa6`) üzerinde; plan `vergi_step10_delta3_plan_0889a820\plan_v6.md` SHA-256 `941d0f2eefb3a5104907c287c01402955281f82df0346f6d04c98c30b0d2c42b`; `run\findings.md` SHA-256 `47176765503c8db8cbbe92f16af1985239c32ee3919d728b8dea9f0592e9df72`; `run\summary.md` SHA-256 `5c33047ef48ac08dc40bdf4e8b1fb4dcdac4e3529fb0cc8d07851f525f554467`; inceleme `run\review\20261018-113730-independent-evidence-review.md` SHA-256 `9d2aa6082b70dae81d05522ede83b80547e25bc83f56a8ba391e162e63f9eb84` (verdict `REHEARSAL_EVIDENCE_VERIFIED`; C0/H2/M3/L7/O8). Sonuç: Faz A PASS (A.16 üç ek turla), insan penceresi 1 `a4`'te `STOP KIT_TEMP_IN_CONTAINER=False`, pencere 2–3 açılmadı, Faz B yalnız kayıt; prova `STOPPED_ON_UNEXPECTED_RESULT`. Aynı planla önceki kök `C:\vd3_3fa3ee24` A.4'te bir prova yardımcısının değişken çakışmasıyla durdu (runbook bloklarına bağlı değil) |
| Revizyon | Bu sürüm `13f19d0` runbook'unun prova bulguları, avukat formu v5 ve kullanıcı kararlarıyla revizyonudur (revizyon 1), e11bab73 delta provası bulgularıyla revizyon 2'dir, delta2 provası (709b329c) bulgularıyla revizyon 3'tür, delta3 Faz A (86c4a7da) bulgusuyla revizyon 4'tür ve delta3 yeniden koşusu (d9d67b7d) bulgularıyla revizyon 5'tir; ID → bölüm eşlemesi **§34**'tedir (revizyon 2: §34.8; revizyon 3: §34.9; revizyon 4: §34.10; revizyon 5: §34.11) |

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

- **Dış çağrı YOK.** Bu runbook'un hiçbir komutu internete, bir model
  sağlayıcısına, bulut OCR'a veya başka bir dış hizmete bağlanmaz ve
  gerçek içerik cihazdan **çıkmaz**. Ağ iddiası beş sınıftan oluşur
  (§21): (1) **runbook komutları** — **sıfır** ağ işlemi; (2) **dosya
  aktarımı** — zincir içindeki **tek** dosya aktarımı, dosya avukatının
  belirlediği kanaldan şifreli aktarım dosyasının **içeri yönlü**
  alınmasıdır (form v5 E2; §6.4; evidence'a
  `E2_INBOUND_TRANSFER_RECEIVED=True`); (3) **ön-pencere insan ağ
  işlemleri** — araç kurulumları için indirme (zincir dışında) ve UYAP
  editörünün imza doğrulaması (zincir adım 2–3); ikisi de içerik
  penceresinden önce ve ayrı onayla yapılır; (4) **karar kanalı** —
  dosya avukatının yazılı kararları ve operatörün yazılı bildirimleri;
  **sayılı, hash'li ve içeriksizdir**; (5) **sesli görüşme** — dosya
  avukatı ile operatör arasındaki sesli telefon görüşmesi (E2 parolası,
  E3 olay bildirimi); cihaz dışıdır, bu cihazdan ağ işlemi değildir
  (§21).
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
- **Revizyon 5'in provası yapılmış değildir.** `13f19d0` sürümü sentetik
  olarak prova edilmiştir (§0, prova ae129016); revizyon 1'in (`4f5c37e`)
  yeniden yazılan ve yeni eklenen blokları delta provasından (§0, prova
  e11bab73) geçmiştir. Revizyon 2'nin (§34.8) blokları delta2 provasında
  (§0, prova 709b329c) ölçülmüş; prova `STOPPED_ON_UNEXPECTED_RESULT` ile
  bitmiş ve bulguları revizyon 3'e işlenmiştir. Delta3 provasının Faz A'sı (§0,
  prova 86c4a7da) A.10'da `STOPPED_ON_UNEXPECTED_RESULT` ile durmuş; kök
  neden (N105 `ac.ps1` temizlik satırı) revizyon 4'te (§34.10)
  düzeltilmiştir. Revizyon 4'ün kiti delta3 yeniden koşusunda (§0, prova
  d9d67b7d) insan penceresi 1'in `a4` adımında kilitlendi ve uçtan uca
  çalıştırılmadı; bulguları revizyon 5'e (§34.11) işlenmiştir. Revizyon
  5'te değişen ve yeni kit blokları (N105, N107, N108) ile tek sayfa ve
  not formu (N114, N115) hiç çalıştırılmamıştır; N116 yalnız yazım
  sırasında, runbook'tan çıkarılmış kopyalar üzerinde statik analiz aracı
  olarak çalıştırıldı, kurulum bağlamında (Ek R3/2 madde 7)
  çalıştırılmadı (§34.11). Revizyon 3'te (§34.9)
  yeniden yazılan ve yeni eklenen bloklar (N4, N16, N17 ve Ek R3 kiti)
  delta3 provasından geçmeden gerçek veriyle kullanılamaz (§34.4, §32/1).

### 1.5 Yazım kuralları (bağlayıcı)

Kaynak: Temel L61–L147. **Sapmalar:** yer tutucu tablosundan maskeleme,
probe, inference, harness, monitor, süreç-yardımcısı ve engel-dosyası yer
tutucuları çıkarıldı; `<attempt>`, `<journal-id>` ve `<reconcile-actor-ref>`
eklendi; `-m` istisnası (harness zinciri) kaldırıldı.

- **Yer tutucular** her zaman backtick veya kod bloğu içinde yazılır.

| Yer tutucu | Anlamı |
|---|---|
| `<repo-root>` | Pilot için `<pilot-root>` altına alınmış repository **klonunun** kök dizininin mutlak yolu (§4.4) |
| `<container-file>` | VeraCrypt dosya kapsayıcısının mutlak yolu; yerel, bulut senkronizasyonu olmayan bir dizinde; `<source-repo-root>`, `<repo-root>`, `<external-root>`, `<container-root>`, `<system-temp>`, `<container-temp>`, `<python-runtime-root>` ve `<pg-bin-dir>` ile örtüşmez (§4.4, §13.8) |
| `<system-temp>` | TEMP **yönlendirmesinden önceki** sistem Temp yollarının ortak adı: `<system-temp-user>` ve `<system-temp-windows>`. İçerik oturumu açılmadan önce bir kez okunur; evidence'a §1.5 gereği yolun kendisi değil SHA-256'sı yazılır (§4.4/5). Korunan listelerde `[System.IO.Path]::GetTempPath()` yerine kullanılır, çünkü yönlendirmeden sonra `GetTempPath()` `<container-temp>`'i döndürür |
| `<system-temp-user>` | Kullanıcının `AppData\Local\Temp` dizini: yönlendirme öncesi `[System.IO.Path]::GetTempPath()` değeri, sondaki `\` olmadan (§4.4/5) |
| `<system-temp-windows>` | `%SystemRoot%\Temp` dizini, sondaki `\` olmadan (§4.4/5) |
| `<container-root>` | Kapsayıcının bağlandığı **sürücü harfinin kökü** (ör. `X:\`); klasöre bağlama yoktur (§4.4) |
| `<pilot-root>` | `<container-root>`'un doğrudan altında, ACL'si sıkılaştırılmış tek pilot dizini; doğrudan altında yalnız `<repo-root>`, `<restricted-dir>`, `<container-temp>` ve `<intake-dir>` bulunur (§4.4, §13.8) |
| `<container-temp>` | İçerik oturumunda TEMP/TMP'nin yönlendirildiği, `<pilot-root>` altındaki dizin (§4.4/5) |
| `<intake-dir>` | `<pilot-root>` altında, şifreli aktarım dosyasının (`transfer.7z`) kaydedildiği ve açıldığı dizin (§6.4) |
| `<7z>` | 7-Zip komut satırı aracının (`7z.exe`) mutlak yolu; `<sevenzip-root>`'un doğrudan altında (§4.4/6, §13.8) |
| `<sevenzip-root>` | 7-Zip kurulum dizini (§4.4/6, §13.8) |
| `<pdftotext>` | Poppler `pdftotext.exe` dosyasının mutlak yolu; `<poppler-bin-dir>`'in doğrudan altında (§4.2/3, §13.8) |
| `<poppler-bin-dir>` | Poppler `bin` dizini (§4.4/6, §13.8) |
| `<file-name>` | `document.json` `file.file_name` değeri; opak, kişisel veri taşımaz (§10.3) |
| `<source-repo-root>` | Klonun alındığı, yürütme yetkisinde onaylı commit'i taşıyan yerel repository'nin mutlak yolu (§4.4/3) |
| `<veracrypt-version>`, `<pdftotext-version>`, `<7z-version>` | Araçların kendi çıktısından okunan sürüm dizgeleri; yalnız teknik kayda yazılır (§4.4/6) |
| `<form-file>` | Ölçülen e-imzalı form birimi dosyasının (UDF) mutlak yolu; yol kişisel veri taşımaz (§6.6/1) |
| `<container-file-bytes>` | §4.4/2'de kaydedilen `CONTAINER_FILE_BYTES` tamsayısı (§28.3.3) |
| `<case-root>` | Pilot case dizininin mutlak yolu: `<repo-root>\data\cases\<case-id>` |
| `<python>` | §13.3'teki yorumlayıcının mutlak yolu |
| `<psql>` | PostgreSQL 16 `psql.exe` dosyasının mutlak yolu (§13.5) |
| `<pilot-port>` | Adım 8'in kalıcı, yalnız-loopback pilot kümesinin TCP portu (`docs/operations/local-postgresql-iam-adoption.md`); bu belgeye, evidence'a ve commit'e yazılmaz (§1.5) |
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
| `<external-root>` | Repo ve kapsayıcı dışı, bulut senkronizasyonu olmayan, **yalnız bu pilot için ayrılmış** kök dizinin mutlak ve canonical yolu; `<evidence-dir>`'in ebeveyni. Sürücü kökü olamaz; `<repo-root>`'a eşit, onun altında veya atası olamaz; `<container-root>`, `<case-root>`, `<system-temp>`, `<container-temp>`, `<python-runtime-root>` ve `<pg-bin-dir>` ile örtüşemez; doğrudan altında **tam olarak** `<evidence-dir>` bulunur, başka öğe bulunmaz (§13.8, §28.3.2) |
| `<evidence-dir>` | `<external-root>` altında, **yalnız metadata** taşıyan, kapsayıcı imhasından sonra da kalan pilot evidence dizini (§26) |
| `<restricted-dir>` | `<pilot-root>` altında (kapsayıcı içinde), avukat kontrolündeki **dava-türevi içerik** dizini (§10.2, §10.5) |
| `<archive-dir>` | Yalnız şifreli arşiv kararında: formun F3'teki arşiv yerinin mutlak yolu (§28.5) |
| `<archive-parent>` | Yalnız şifreli arşiv kararında: F3'te önceden onaylanmış, `<archive-dir>`'in exact ebeveyni (§28.5) |
| `<python-runtime-root>` | §13.3'teki concierge runtime'ının kök dizini; `<python>` bunun altındadır (§13.8) |
| `<pg-bin-dir>` | PostgreSQL 16 `bin` dizini; `<psql>` bunun doğrudan altındadır (§13.8) |
| `<report-produced>` | Zincir adım 22 çıkış `0` ile tamamlandıysa `$true`, aksi hâlde `$false` (§28.2) |

- **Dizin ve dosya yer tutucuları mutlak, canonical ve önceden çözümlenmiş
  yollardır**: `<repo-root>`, `<case-root>`, `<python>`, `<psql>`,
  `<python-runtime-root>`, `<pg-bin-dir>`, `<external-root>`,
  `<evidence-dir>`, `<restricted-dir>`, `<archive-parent>`,
  `<archive-dir>`, `<container-file>`, `<container-root>`, `<pilot-root>`,
  `<container-temp>`, `<intake-dir>`, `<7z>`, `<sevenzip-root>`,
  `<pdftotext>`, `<poppler-bin-dir>`, `<source-repo-root>`,
  `<system-temp-user>`, `<system-temp-windows>` ve
  `<form-file>`. Göreli yol kabul
  **edilmez**. Her yol, kullanılmadan önce
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
- **Dar istisna — kit ayar dosyası (revizyon 3; kullanıcı kararı S-1=A).**
  `<evidence-dir>\kit\kit-values.txt` (Ek R3/2) mutlak yol taşır; yalnız
  şu altı değeri: `<repo-root>`, `<intake-dir>`, `<container-temp>`,
  `<7z>`, `<sevenzip-root>` ve `<poppler-bin-dir>`. Hiçbiri kullanıcı
  profili (`%USERPROFILE%`) altında olamaz; `<evidence-dir>` yolu bu
  dosyaya yazılmaz. Bu koşul kit kurulurken ajan tarafından ve her
  yüklemede `ac.ps1` tarafından mekanik olarak denetlenir; denetim
  başarısızsa kit **kurulmaz/yüklenmez** ve **DUR** — sessiz düzeltme
  yoktur. İstisna başka hiçbir evidence dosyasına uzanmaz.
- Bölüm numarası tek başına yazıldığında (ör. "§13") **bu runbook'un**
  bölümü kastedilir. Temel runbook "Temel §N", `CLAUDE.md` belge adıyla
  yazılır. "Zincir adım N" ifadesi §2.1 tablosundaki satır numarasıdır.
  "Form X" ifadesi avukat formundaki soru kodudur (A1, B4, F2 …).

### 1.6 Yürütme ön koşulları (bağlayıcı)

Kaynak: Temel L149–L269. **Sapmalar:** prova listesinden maskeleme, egress,
argv/DLL, ortam profili, harness ve probe kalemleri çıkarıldı; manuel
girdi, `manual-fact` ve reconciliation kalemleri eklendi; prova
veritabanı kararı (revizyonla kapandı, madde 3); silme yöntemi / yerel
şifreli kapsayıcı ön koşulu (madde 4) ve gerçek dosyadan önce zorunlu
kapılar (madde 5) eklendi.

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
   - dizin yol kapısı (tek çocuklu `<external-root>` sözleşmesi,
     `<container-root>` ve `<pilot-root>` sözleşmeleri dahil),
     `<python>`/`<psql>`/`<pdftotext>`/`<7z>` dosya kapısı ve `<archive-dir>`
     kapısı (§13.8, §28.5);
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
     nasıl üretileceği prova kapsam onayında belirlenir. Hata kasıtlı bir
     ACL deny kaydıyla üretilirse geri alma ölçütü şudur: gerçek
     `extractions` dizininin ham SDDL'i, kayıttan önceki snapshot'la
     **birebir** eşit olmalıdır (eşit değilse **DUR**); ayrı bir sonda
     dizininde ölçülen SDDL farkı yalnız **bilgi** amaçlıdır ve durdurmaz
     (kullanıcı kararı K2; prova bulgusu R-F-ACLAI);
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
   - **bu cihazdaki kapsayıcı yolunun kaydı (O-f; kullanıcı kararı K3).**
     Operatör, içerik taşımayan prova oturumunda §4.4'teki kapsayıcı
     sözleşmesini sentetik bir kapsayıcıyla uygular ve prova evidence'ına
     yalnız şu satırları yazar: `CONTAINER_TOOL_PRESENT=True/False`
     (VeraCrypt kurulu ve sürümü teknik kayda yazılabiliyor),
     `CONTAINER_MOUNTED_AS_DRIVE_LETTER=True/False`,
     `PATH_OK=container-root` ve harici disk için
     `EXTERNAL_DISK_PRESENT=True/False`. İlk iki boolean'dan biri `False`
     ise veya kapı `STOP` verirse pilot bu cihazda yapılamaz (§32/12).
     `EXTERNAL_DISK_PRESENT` bir **kapı değildir**, yalnız kayıttır:
     `False` (harici disk yok) pilotu engellemez; `True` ise §4.2/10'daki
     harici disk kuralı (içerik penceresi boyunca fiziksel olarak
     çıkarılmış) uygulanır. Tam disk şifrelemesi
     yolları (Windows "Cihaz şifrelemesi", BitLocker, üçüncü taraf tam disk
     şifreleme aracı) bu runbook'ta **artık tanımlı değildir**; onlara ait
     `*_PRESENT` boolean'ları yazılmaz. Prova sonrasında kapsayıcı aracı,
     sürümü veya işletim sistemi değişirse bu kayıt zincir adım 4'ten önce,
     içerik taşımayan bir oturumda yeniden yazılır; provanın tekrarlanıp
     tekrarlanmayacağı kullanıcı kararıdır;
   - kapsayıcının oluşturulması ve bağlanması, `<pilot-root>` ACL
     sıkılaştırması ve principal ölçümü, içerik oturumunda TEMP/TMP
     yönlendirmesi ve teknik kayıt (§4.4); sentetik bir PDF'ten `pdftotext`
     ile metin çıkarma (§11.2/6); sentetik bir AES-256 7z arşivinin
     `<intake-dir>`'e kaydedilip açılması (§6.4); `sign.sgn` biçim
     kontrolü (§6.6/1); kapsayıcı imhası (§28.3.3);
   - bu sentetik prova bir ajan oturumunda yürütülürse, ajan sürecinin
     Process kapsamındaki `CLAUDE*` adları (`CLAUDE_CODE_MESSAGING_TOKEN`
     dahil) prova planının muaf ad listesinde (E0) **tek tek** yazılır ve
     kullanıcıya bildirilir; gerçek pilotta bu adların sayısı her kapsamda
     **0**'dır (§13.6, kullanıcı kararı K6).

   **Prova veritabanı (karar; R-F-DBDEC, kullanıcı kararı K5).**
   `manual-fact` preview dahil veritabanlı adımlar bir PostgreSQL
   bağlantısı gerektirir
   (`ui/services/manual_fact_mutation_facade.py:634-643, 656-665`). Prova,
   Adım 8'in kalıcı pilot kümesinde (`<pilot-port>`), yalnız sentetik case'lerle ve
   prova başlamadan hemen önce alınmış yeni bir `pg_dump` yedeğiyle yapılır.
   Prova, gerçek pilotun journal'ında kalıcı sentetik izler (journal,
   assignment ve security-event satırları) bırakır; bunlar §28.4 gereği
   silinmez.

   **Revizyon sonrası delta prova (kullanıcı kararı D13).** `13f19d0`
   provasının (§0) kanıtı yalnız **bayt-bayt aynı kalmış** komut
   bloklarını kapsar ve §34.4'teki eşleme tablosuyla devralınır. Revizyon
   1'de yeniden yazılan veya yeni eklenen bloklar e11bab73 delta
   provasında prova edilmiştir (§0); revizyon 2'de (§34.8) yeniden
   yazılan veya yeni eklenen her blok, devralma tabanı e11bab73 olmak
   üzere (§34.4, K-R2-10) yeniden prova edilir. Her iki revizyonda da
   yeniden yazılan veya yeni eklenen her blok yeniden prova edilir.
   Revizyon 3'te (§34.9) yeniden yazılan bloklar (N4, N16, N17) ve yeni
   Ek R3 kiti (N105–N114) delta3 provasında prova edilir; devralma tabanı
   revizyon 2 ve delta2 kanıtıdır (§34.4). Delta3 Faz A (86c4a7da, §0)
   A.10'da `STOPPED_ON_UNEXPECTED_RESULT` ile durdu; kök neden (N105)
   revizyon 4'te düzeltildi (§34.10). Delta3 yeni kökte (d9d67b7d, §0)
   yeniden koşuldu: Faz A geçti, insan penceresi 1 `a4`'te kilitlendi
   (TEMP yönlendirmesi atlandı), prova `STOPPED_ON_UNEXPECTED_RESULT`
   ile bitti; bulgular revizyon 5'e (§34.11) işlendi. Revizyon 5'te
   değişen ve yeni bloklar (N105, N107, N108, N114–N116; N116 yazım
   sırasında yalnız çıkarılmış kopyalar üzerinde statik analiz aracı
   olarak çalıştırıldı, kurulum bağlamında çalıştırılmadı) ve insan
   tarafında hiç ölçülmemiş adımlar (kanıt incelemesinin 5B listesi) bir
   sonraki delta provasında prova edilir; o prova ayrı kullanıcı
   kararıdır (§34.4 revizyon 5 satırları). §4.2/10, §4.4, §13.8 ve §28 **tek-çalışımlık** olarak yeniden
   prova edilir. Ortam değiştiği için (kapsayıcı birimi, TEMP) ayrıca
   kapsayıcı içinde **bir** hafif uçtan uca sentetik geçiş (intake →
   `manual-fact` → promotion → verification → timeline → deadline →
   rapor → silme) yapılır (kullanıcı kararı D13a).

   Prova gerçek pilot **değildir**; kendi ayrı evidence'ını üretir, sentetik
   dizini kendi sonunda siler ve hiçbir gerçek belge kullanmaz. Provada bir
   komut bu belgede yazıldığı gibi çalışmazsa runbook **düzeltilir ve
   yeniden incelenir**; komut sahada doğaçlama değiştirilmez.

4. **Silme yöntemi ve yerel şifreli kapsayıcı (H-1; form v5 E1/F4).** Bu
   runbook'ta tanımlı tek silme yöntemi Form F4'ün **şifreli kapsayıcı
   yöntemidir**: bütün çalışma ve geçici dosyalar kapsayıcı içinde tutulur;
   pilot sonunda kapsayıcı kapatılır, kapsayıcı dosyası geri dönüşüm
   kutusu kullanılmadan silinir ve tek kullanımlık anahtar/parola kayıtları
   imha edilir; kapsayıcı dışına kopya veya geçici dosya yazılmaz (§4.4,
   §28.3). Bu yüzden gerçek belge teslim alınmadan önce şunların hepsi
   sağlanmıştır:
   - Form **E1** = "Tek dosyalık pilot alternatifi" (yerel şifreli
     kapsayıcı) ve Form **F4** = "Şifreli kapsayıcı yöntemi" (§6.4, §23);
   - kapsayıcı aracı (VeraCrypt) ve sürümü teknik kayda yazılmıştır
     (§4.4/6);
   - yürütme günü, zincir adım 4'te §4.2/10 ve §4.4 doğrulamaları
     `CONTAINER_VERIFIED=True` ve `PILOT_ACL_PRINCIPALS_OK=True` vermiştir.

   E1'de "Tam disk şifrelemesi" veya "Kabul değil" işaretliyse, F4'te
   "Tam disk şifrelemesi açıkken standart silme" veya "Diğer" işaretliyse,
   kapsayıcı doğrulanamıyorsa veya harici disk kuralı (§4.2/10)
   sağlanmıyorsa: **DUR — gerçek belge teslim alınmaz.** Tam disk
   şifrelemesi yolları bu revizyonda kaldırılmıştır (kullanıcı kararları K3,
   D15); bir tam disk şifrelemesi yolu ancak ayrı bir runbook revizyonu ve
   bağımsız inceleme ile yeniden eklenebilir.

5. **Gerçek dosyadan önce zorunlu operatör kapıları (bağlayıcı).**
   Aşağıdakilerin her biri sağlanıp evidence'a yazılmadan gerçek belge
   teslim alınmaz:
   - **Kanal kapısı.** Zincir adım 4'te ve içerik penceresi (zincir adım
     5–27) boyunca §4.3 (a)'daki altı kanal sınıfı kapalıdır ve
     `AI_CONTENT_CHANNELS_CLOSED=True` yazılmıştır. Bu, pencere boyunca
     Claude Code'un ve VS Code'un **hiç** kullanılmaması demektir:
     `claude`, `Code`, `ChatGPT`, `copilot-runtime`, `M365Copilot`,
     `OneDrive`, `OneDrive.Sync.Service` ve desene uyan her süreç §4.3
     (a)'daki kapatma prosedürüyle kapatılır; kapatılamayan veya ikinci
     taramada yeniden görünen → **DUR** (H40). Revizyon 3'ten itibaren
     iki tarama Ek R3 kitinin `a2` ve `a3` adımlarıyla, her içerik
     oturumunun kapanış taraması `a9` ile yapılır (§4.3 a). Revizyon
     5'ten itibaren ilk içerik oturumundan önce §4.3 (a)'daki bir
     kerelik bilgisayar hazırlığı (başlangıç öğeleri, OneDrive'ın üç
     zamanlanmış görevi, yeniden başlatma, Ayrıntılar denetimi) yapılmış
     olmalıdır (kullanıcı kararı D3).
   - **İnsan adım kiti (revizyon 3; Ek R3; kullanıcı kararları K-R3-1,
     K-R3-12).** Zincir adım 4'ten önce, içerik penceresinin dışında ve
     hiçbir gerçek içerik yokken, ayrı bir ajan oturumu kiti Ek R3/2'ye
     göre `<evidence-dir>\kit\` altına kurar ve `KIT_BUILD=OK` yazar; bu
     oturum kurulumdan sonra kapatılır (§4.3 a). Kit bloklardan bayt-bayt
     kopyalanır, yeniden üretilmez; hash'i Ek R3/1 tablosuyla eşit değilse
     veya `kit-values.txt` denetimi (§1.5) geçmezse kit kurulmaz: **DUR**.
     Revizyon 5'ten itibaren kurulumda değişken adı çakışma denetimi
     (Ek R3/7, N116) `KIT_VAR_COLLISIONS=0` vermelidir; aksi **DUR**.
     Değerleri doldurulmuş tek sayfalık adım listesi (Ek R3/5) ve boş
     not formu (Ek R3/6) kâğıda basılmıştır.
   - **Tek yazan oturum.** İçerik penceresi boyunca **sıfır** AI oturumu
     bulunur. Pencere dışındaki ajan işlerinde aynı repo, kapsayıcı ve
     evidence alanında tek yazan oturum kuralı (`CLAUDE.md` §14.4)
     geçerlidir; aynı alanda ikinci bir yazan oturum → **DUR**.
   - **PR-NOPROFILE.** İnsan-only, etkileşimli, kısa bir
     `powershell.exe -NoProfile` denemesi: §4.3 (b) bloğu, (c) "önce"
     bloğu, arada elle yazılmış sentetik bir komut (ör. `"SENTETIK"`),
     (c) "sonra" bloğu. Beklenen: §4.3 (b) değerleri ve
     `HISTORY_FILE_UNCHANGED=True`. Bu denemeyi hiçbir AI asistanı
     yürütmez; evidence'a yalnız sonuç satırları ve tarih yazılır.
     Beklenmeyen değer → runbook düzeltilir ve yeniden incelenir, **DUR**
     (H53).
   - **Kapsayıcı dışı izlerin bildirimi (kullanıcı kararları D9, D9a).**
     Kapsayıcı dışında kalabilen izler (sayfa dosyası, hazırda bekletme
     dosyası, Windows Search indeksi, antivirüs karantinası; şifresiz
     sistem sürücüsünde) ile formdaki "kapsayıcı dışına hiçbir şey
     yazılmaz" ifadesi arasındaki çelişki, **protokol inceleyicisine ve
     dosya avukatına** kişisel veri içermeyen yazılı bir notla bildirilir.
     Dosya avukatının yazılı cevabı `LEGAL_APPROVED` olarak alınır.
     Evidence: `CONTAINER_RESIDUAL_NOTICE_SENT=True` ve karar kanalı
     satırları (§21): bildirim `OUTBOUND_NOTICE_SENT seq=<n>
     sha256=<64-küçük-hex>`, cevap `INBOUND_DECISION_RECEIVED seq=<n>
     sha256=<64-küçük-hex>`. Bildirim yoksa, cevap yoksa veya cevap kabul
     etmiyorsa: **DUR** (Y19). Bu bir hukuki kapıdır, mühendislik kararı
     değildir (§32/25).
   - **E-imza geçerliliği (kullanıcı kararları D17, D17a).** E-imzalı her
     form birimi (A–F + I, G, Ek 2 ve e-imzalıysa Ek 1) için §6.6/1'deki
     `UDF_SIGNATURE_VALID=True` kaydı (`False`, ölçülmemiş veya belirsiz →
     **DUR**, Y20).
   - **E2 kanalı (kullanıcı kararı D6).** Dosya avukatının teslim kanalını
     yazılı olarak belirlemesi ve — kanal şifreli arşivin e-posta eki
     olarak gönderilmesiyse — §6.4'teki hukuki sorunun yazılı cevabı.

Bu beş ön koşuldan biri eksikse: **DUR — gerçek belge teslim alınmaz.**
Madde 1–3 zincir adım 1'de, madde 4 zincir adım 2 (form cevapları) ve
zincir adım 4'te (kapsayıcı, ACL ve harici disk ölçümü), madde 5 zincir
adım 2–4'te değerlendirilir.

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
- Ağ iddiası §21'deki beş sınıftır: (1) runbook komutları — **sıfır**
  dış ağ işlemi; (2) dosya aktarımı — zincir içindeki tek dosya
  aktarımı E2 aktarım dosyasının içeri yönlü alınmasıdır; (3) ön-pencere
  insan ağ işlemleri — kurulum indirmeleri ve UYAP editörü, içerik
  penceresinden önce ve ayrı onayla; (4) karar kanalı — sayılı, hash'li
  ve içeriksiz yazılı insan yazışmaları; (5) sesli görüşme — cihaz dışı,
  bu cihazdan ağ işlemi değildir. Gerçek içerik cihazdan çıkmaz (§1.2,
  §21).

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
| 1 | Yürütme ön koşulları: incelenmiş, commit'li ve push'lu runbook; sentetik prova | Kullanıcı | `REAL_ACTION_APPROVED` (yürütme yetkisi, gerçek veri işlenmesi) | §1.6/1–3'ten biri eksik (madde 4 adım 2 ve 4'te; madde 5 adım 2–4'te) | §1.6 |
| 2 | Protokol inceleyicisinin e-imzalı formu (A–F + I, v5) ve ekleri (Ek 1, operatör ve dosya avukatınca imzalı Ek 2); form kapılarının kontrolü; formun ve eklerin hash'i; `sign.sgn` biçim kontrolü ve `UDF_SIGNATURE_VALID`; `TWO_PERSON_CONTROL` kaydı; §1.6/5 kapıları | Protokol inceleyicisi ve dosya avukatı → operatör kontrol eder | `LEGAL_APPROVED` (form ve ek imzaları; D9 cevabı); UYAP editörünün ağ erişimi için ayrı `REAL_ACTION_APPROVED` (§6.6/1); B4 "aynı kişi" ise ayrıca `REAL_ACTION_APPROVED` (`WAIVED_B4`, §4.1) | Zorunlu bir soru boş veya kapıyı kapatan cevap; imza biçimi geçersiz; `UDF_SIGNATURE_VALID` `True` değil; E1 ≠ kapsayıcı seçeneği veya F4 ≠ kapsayıcı yöntemi; E1'e yazılmış ek koşul; Ek 2 iki imzalı değil; D9 cevabı yok (§1.6/5, §6, §23) | §1.6/5, §4.1, §6, §7, §9, §23 |
| 3 | Dosya seçimi: dosya avukatının ayrı imzalı G bölümü (G0–G11) ve hash'i; dosya avukatının bu dosya için işleme şartı teyidi (§6.3 B3) | Dosya avukatı | `LEGAL_APPROVED` (G imzası; işleme şartı teyidi) | G1–G7 veya G9'dan biri "Hayır" veya boş; G0 veya G8 boş; G10/G11 eksik; G10 tarihi bağlayıcı I3 tarihinden önce; e-imzalıysa `UDF_SIGNATURE_VALID` `True` değil; `PROCESSING_BASIS_CONFIRMED=True` yok (Y2) | §8, §6.3, §6.6 |
| 4 | Preflight: içerik oturumu, kanal kapısı, **sistem Temp kaydı (`<system-temp>`), kapsayıcı doğrulaması, `<pilot-root>` ACL'si, TEMP yönlendirmesi, teknik kayıt ve harici disk kaydı**, yol kapısı, repo/DB/ortam ölçümü, `<restricted-dir>` izinli küme ve hash kaydı | Operatör | Kapsayıcının oluşturulması ve `<pilot-root>` ACL sıkılaştırması için ayrı `REAL_ACTION_APPROVED` (§4.4); araç kurulumları ayrıca, içerik penceresinden önce (§4.4/6) | Herhangi bir `STOP` satırı; `CONTAINER_VERIFIED=True`, `PILOT_ACL_PRINCIPALS_OK=True` veya `TEMP_IN_CONTAINER=True` yok; teknik kayıt yok; harici disk çıkarılmamış | §4.2/10, §4.3, §4.4, §10.5, §13 |
| 5 | Belge teslimi (Form E2: uzaktan şifreli aktarım) ve manuel intake (`case.json`, `document.json` + **`page_count`**, orijinal, `pdftotext` ile `extracted/<document-id>.txt`) | Operatör | — | Form/G hash yeniden ölçümü kayıtla uyuşmuyor (§6.6/7 a); E2 taşıyıcısı kontrolü geçmedi veya taşıyıcı `ENCRYPTED_TRANSFER` değil (§6.4); case dizini önceden var; BOM; `page_count` boş; E4 dışı araç | §6.4, §6.6, §11.2 |
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
| 26 | Gerçek verinin silinmesi (kapsayıcı içindeki guard'lı silmeler, ardından kapsayıcı imhası ve anahtar imhası) veya şifreli arşivi | Operatör | Form F2–F4 (`LEGAL_APPROVED`) + **her hedef için** `REAL_ACTION_APPROVED` | Guard FAIL; F4 ≠ kapsayıcı yöntemi; silme günü kapsayıcı yeniden doğrulanamadı | §28.3, §28.5 |
| 27 | Geçici kopyaların (kapsayıcı içinde) F1 süresi içinde silinmesi ve imha kaydı | Operatör | `REAL_ACTION_APPROVED` (silme) | F1 süresi aşıldı; kopya kapsayıcı dışında; F5 kaydı yazılmadı | §28.6, §28.7 |
| 28 | Ortamın kapanış ölçümü | Operatör | — | Ad taramasında eşleşme | §13.6 |
| 29 | Postcondition'lar ve LOCK kaydı | Operatör; LOCK ayrı tur | LOCK onayı | Herhangi bir postcondition FAIL | §30, §31 |

**Sıra istisnaları (bağlayıcı):**

- **Zincir adım 2 ve 3** iki ayrı imzayla karşılanır: A–F bölümleri I
  bölümüyle (protokol inceleyicisi), G bölümü kendi G10/G11 alanıyla
  (dosya avukatı) imzalanır (form v5). Kapıları
  **ayrı ayrı** değerlendirilir. G bölümü, bağlayıcı (en son imzalı) A–F
  sürümünden **sonra** imzalanmış olmalıdır: G10 tarihi o sürümün I3
  tarihinden önce olamaz. A–F sonradan yeniden imzalanırsa G bölümü de
  yeniden imzalanmadıkça **DUR** (Y1, Y7; §6.6).
- **Zincir adım 27** yalnız zincir adım 23'e (veya §25.2 abort yolunun
  başlamasına) bağlıdır; 24–26'yı **beklemez** ve onlardan bağımsız olarak,
  F1 süresi içinde çalıştırılır. Bu adımın F1 süresini aşması **DUR**'dur
  (Y6); 24–26'nın sürmesi bu süreyi uzatmaz.
- **Zincir adım 26'nın son alt adımı (kapsayıcı imhası ve anahtar imhası,
  §28.3.3)** case ve `<restricted-dir>` silmelerinden (§28.3.1, §28.3.2)
  ve zincir adım 29'un kapsayıcıya bağlı postcondition'ları (§30/2–3,
  klondaki `git status`) kapsayıcı bağlıyken ölçüldükten **sonra**
  yapılır. Zincir adım 27 §28.6 (a) yoluyla yürüyorsa kapsayıcı imhası
  ondan da sonra gelir; (b) yolunda kapsayıcı imhası adım 27'yi de
  tamamlar ve F1 süresi içinde bitmelidir (§28.6). Zincir adım 29'un geri
  kalanı kapsayıcı imhasından sonra tamamlanır. Bu sıra dışında kapsayıcı
  imhası **yapılmaz**: **DUR** (Y6).

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
- Gerçek içeriğin veya ondan türeyen herhangi bir dosyanın kapsayıcı
  (`<pilot-root>`) dışına yazılması (§4.4).
- İçerik oturumunun Claude Code'dan veya herhangi bir ajan oturumundan
  başlatılması (kullanıcı kararı K6; §4.2/6, §13.6).
- Kapsayıcıdaki repo klonunun VS Code'da veya herhangi bir IDE/editörde
  açılması (içerik penceresi içinde **ve dışında**; kullanıcı kararı
  D18; §4.3 a).

---

## 4. Roller, sorumluluklar ve gerçek içerik güven sınırı

### 4.1 Roller ve iki kişi kuralı (K-12)

Kaynak: Temel L380–L395. **Sapmalar:** maskeli metin okuması çıkarıldı;
iki kişi kuralı manuel girdiye bağlandı ve Form B4 kapısı eklendi; avukat
rolü form v5'e göre protokol inceleyicisi ve dosya avukatı olarak ikiye
ayrıldı (revizyon, §34).

| Rol | Sorumluluk | Yapamayacağı |
|---|---|---|
| **Protokol inceleyicisi (avukat)** | Formun A–F bölümlerinin hukuki incelemesi ve I bölümüyle imzası (form v5 I0) | Pilot işletimi, gerçek dosya, veri güvenliği veya pilot içi hiçbir karar; veri sorumlusu, dosya sahibi, operatör veya veri işleyen değildir |
| **Dosya avukatı (veri sorumlusu; dosyanın sahibi veya dosyadan sorumlu avukat/hukuk bürosu)** | Formun G bölümünün doldurulması ve imzası; bu dosya için işleme şartının (KVKK m.5) yazılı teyidi (§6.3 B3); Ek 1'in dosyaya özgü doldurulması ve müvekkile teslimi; Ek 2'nin karşı imzası; teslim kanalının belirlenmesi; belge teslimi; intake alanlarının alan-alan doğrulanması; **manuel tebliğ girdisinin orijinal belgeyle karşılaştırılması**; fact kabulü; tebliğ tarihi verification kararı; adli tatil kararı; stopping-event beyanı; kör bağımsız hesap; deadline onayı; veri akıbeti kararı | — |
| **Müvekkil (veri sahibi)** | Form C'ye göre bilgilendirme/rıza | — |
| **Operatör (insan; veri sorumlusunun yazılı talimatıyla çalışan bireysel veri işleyen)** | Ek 2'nin imzası; kapsayıcı ve teknik kayıt (§4.4); ortam/DB ölçümü; manuel intake; **manuel tebliğ girdisinin yazılması**; mekanik kontroller; avukat kararlarının CLI ile birebir uygulanması; olay bildirimi (§4.2/11); evidence; imha kaydı (§28.7); cleanup | Hukuki karar vermek; avukat kararını yorumlamak; eksik kararı varsaymak; kendi girdisini doğrulamak; kapsam genişletmek |
| **Kullanıcı (proje sahibi)** | Yürütme yetkisi; her canonical mutasyon, manuel fact apply'ı, reconciliation apply'ı, assignment değişikliği ve silme için ayrı `REAL_ACTION_APPROVED`; LOCK onayı | — |
| **Bağımsız inceleyici** | Runbook ve yürütme evidence'ının ayrı oturumda incelenmesi | Yürütmeye katılmak; gerçek içeriği görmek |

**"Avukat" kelimesinin anlamı (bağlayıcı; form v5 B1, B2, I).** Bu runbook'ta
"avukat" kelimesi, aksi açıkça yazılmadıkça **dosya avukatını** (veri
sorumlusu) anlatır: zincirdeki bütün `LEGAL_APPROVED` kararları, G bölümü,
bu dosya için işleme şartı teyidi (§6.3 B3), Ek 1 ve Ek 2'nin karşı imzası
ondadır. Formun A–F bölümlerine verilen
cevaplar ve I bölümünün imzası **protokol inceleyicisine** aittir; o
imza, pilot içi bir kararın yerine geçmez. Kişi adları bu runbook'a,
evidence'a ve commit'e yazılmaz (§1.5).

**İki kişi kuralı (bağlayıcı).** Tebliğ tarihini **operatör girer, avukat
doğrular**: girdi dosyasını (§14.2) yazan kişi ile onu orijinal belgeyle
karşılaştıran (§14.3) ve verification kararını veren (§15.3) kişi **ayrı**
olmalıdır.

- Kod bu ayrımı **zorlamaz**: `manual-fact`, `promotion` ve `verification`
  yalnız aynı case için `mutate` yetkisini denetler; aynı IAM aktörü üçünü de
  yapabilir (exact-scope §8/4, K-12/O-2). Ayrım yalnız bu kuralla sağlanır.
- Dosya avukatı ile operatör **ayrı kişilerse** (B4 "Evet, ayrı
  kişiler"): durum zincir adım 2'de evidence'a
  `TWO_PERSON_CONTROL=SEPARATE` olarak yazılır. Protokol inceleyicisinin
  operatörden ayrı olması bu kuralı **karşılamaz**; karşılaştırma ve
  verification dosya avukatınındır.
- Avukat ile operatör **aynı kişiyse**: formun **B4** sorusunda "Hayır"
  seçeneği (form v5) işaretli olmalıdır **ve** dosya avukatı, formun B4
  notundaki sonucu ("aynı kişi olursa bu iki kişili kontrol ortadan
  kalkar") kabul ettiğini ayrıca yazılı olarak beyan etmelidir
  (`LEGAL_APPROVED`; karar kanalı satırı, §21); ikisinden biri yoksa
  **DUR** (Y4). Kabul varsa durum evidence'a
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
3. Metin çıkarma **yalnız** formun **E4** sorusunda onaylanan yerel ve
   çevrimdışı araçla, yani **Poppler `pdftotext`** ile yapılır (form v5 E4:
   "Bu koşulla onaylıyorum"). Kesin sürümü ve `<poppler-bin-dir>` dosya
   manifestinin SHA-256'sı pilot öncesi teknik kayda yazılır (§4.4/6);
   sürüm kaydı yoksa pilot başlamaz. Bu runbook'ta **OCR aracı yoktur**:
   metin katmanı olmayan (taranmış görüntü) bir PDF'ten metin
   çıkarılamazsa §11.2/4 kontrolü `STOP TEXT_VISIBLE=EMPTY` verir ve
   **DUR**'dur (revizyon 2; R-D-IMGPDF). E4 boş veya
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
   ve kaydedilir. İçerik oturumu Claude Code'dan veya herhangi bir ajan
   oturumundan **başlatılmaz** ve onun çocuk süreci değildir; bunun mekanik
   sinyali §13.6 (b) ad taramasının `CLAUDE.*` adları için de üç kapsamda
   **0** vermesidir (kullanıcı kararı K6; eşleşme → **DUR**, Y18). Bu sinyal
   bir kod guard'ı değildir (§32/29).
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

   Bilgi satırı (R-F-AUDITKEY; yalnız değer basar, içerik basmaz; standart
   Windows davranışından gelir, §1.6 provasında doğrulanır):

```powershell
if (Test-Path -LiteralPath $audit) { $auditVal = (Get-ItemProperty -LiteralPath $audit -ErrorAction SilentlyContinue).ProcessCreationIncludeCmdLine_Enabled; "CMDLINE_AUDIT_VALUE=$(if ($null -eq $auditVal) { 'ABSENT' } else { [string]$auditVal })" }
Remove-Variable auditVal -ErrorAction SilentlyContinue
```

   `PRESENT` çıkan her anahtar için, cihaz sahibi bu kaydın cihaz dışına
   aktarılmadığını yazılı olarak beyan etmedikçe **DUR**.
   `CMDLINE_AUDIT_VALUE` yalnız **bilgidir**: `0` veya `ABSENT` olması
   anahtar `PRESENT` iken yazılı beyan şartını **kaldırmaz** (kullanıcı
   kararı D10). **`CMDLINE_AUDIT_KEY=PRESENT` bir bulgudur** (revizyon 2;
   F-0.8-CMDLINE-AUDIT; kullanıcı kararı K-R2-9): bu cihazda delta
   provasında (e11bab73) `CMDLINE_AUDIT_KEY=PRESENT` ve
   `CMDLINE_AUDIT_VALUE=ABSENT` ölçüldü; bu yüzden gerçek koşuda yazılı
   beyan **zorunludur**. Beyan, cihaz sahibinin süreç-oluşturma denetim
   kaydının cihaz dışına (merkezi log, EDR, SIEM) aktarılmadığına dair
   kişisel veri içermeyen yazılı metnidir; repo dışında saklanır ve
   evidence'a yalnız `CMDLINE_AUDIT_DECLARATION sha256=<64-küçük-hex>`
   yazılır. Beyan yoksa: **DUR**. Bu ölçüm üçüncü
   taraf güvenlik yazılımının (antivirüs, EDR) kendi telemetrisini
   **göremez**; o sınır §32'de açık kalır. B yolunda belge içeriği süreç
   argümanı olarak **geçmez** (§1.5); komut satırı denetimi opak
   kimlikleri, tamsayıları, hash'leri, sabit literal'leri, opak
   `<attestation-ref>`'i ve Windows kullanıcı profil adını taşıyabilen
   **mutlak yolları** görebilir (§1.5, §32/21).
10. **Yerel şifreli kapsayıcı ve harici disk (bağlayıcı; F4 kapsayıcı
    yönteminin dayanağı).** Form **E1** "Tek dosyalık pilot alternatifi"
    (yerel şifreli kapsayıcı) olmalıdır (§1.6/4, §23). Operatör, **yürütme
    günü** zincir adım 4'te (intake'ten önce) ve **her silme gününde**
    silmeden hemen önce (§28.3, §28.6) §4.4'teki kapsayıcı sözleşmesini ve
    aşağıdaki harici disk kuralını doğrular. Silme günü doğrulaması
    daraltılmaz.

    - **Kapsam.** Gerçek içerik ve ondan türeyen her dosya (orijinal,
      extracted text, case dizini, rapor, aktarım dosyası, geçici dosyalar)
      **yalnız** `<pilot-root>` altında, yani kapsayıcı içinde bulunur
      (§4.4). `<evidence-dir>` kapsayıcı dışındadır ve **yalnız metadata**
      taşır (§26.1). Kapsayıcı dışında gerçek içerik taşıyan tek bir dosya
      fark edilirse: **DUR** (H40) ve Form E3 bildirimi.
    - **Tam disk şifrelemesi yolları kaldırıldı.** Windows "Cihaz
      şifrelemesi", BitLocker ve üçüncü taraf tam disk şifreleme aracı
      yolları bu revizyonda kaldırılmıştır (form v5 E1/F4; kullanıcı
      kararları K3, D15). Kapsayıcının doğrulanması §4.4'tedir.
    - **Avukatın E1'e yazdığı koşullar (N-L2).** E1'e (veya formun başka bir
      yerine) kapsayıcı yöntemi veya aracı hakkında yazılmış, §4.4'te
      karşılığı olmayan her araç adı ya da koşul §6.1 gereği bir **ek
      koşuldur**: runbook'a işlenip yeniden incelenene kadar **DUR**.
      Operatör ve kullanıcı bu koşulu yorumlamaz ve sahada uygulamaz.
    - **Harici disk kuralı (bağlayıcı).** Bu cihazda bir harici USB disk
      bulunur (yazım anında `D:`). Bu disk ve bağlı her başka harici veya
      çıkarılabilir sürücü, **içerik penceresi boyunca** (§4.3) cihazdan
      **fiziksel olarak çıkarılmıştır** ve pencere kapanana kadar yeniden
      takılmaz. Bu revizyonda E2 taşıyıcısı yoktur; harici bir sürücü
      **taşıyıcı olarak kullanılamaz** (§6.4). Tam disk şifrelemesi
      yolları kaldırıldığı için "şifreli harici disk" seçeneği de yoktur.
    - **Kayıt.** Zincir adım 4'te ve her silme gününde, her harici sürücü
      için sürücü harfiyle ayrı bir çift yazılır:
      `EXTERNAL_DISK_ENCRYPTED=False` ve `EXTERNAL_DISK_REMOVED=True`.
      Kabul edilen **tek** birleşim budur.
    - **Yerleşik optik sürücü (bağlayıcı; revizyon 2; R-D-EOPTICAL;
      kullanıcı kararı K-R2-7).** Cihaza **yerleşik** bir optik sürücü
      (yazım anında `E:`) fiziksel olarak çıkarılamaz; yukarıdaki harici
      disk çiftine tabi **değildir**, bunun yerine **medya takılı değil**
      kuralına tabidir: içerik penceresi boyunca sürücüde disk veya
      bağlanmış görüntü (ISO) bulunmaz. Zincir adım 4'te (§4.4/6 teknik
      kaydından **sonra**) ve her silme gününde, harici disk kaydının
      yanında şu blok çalıştırılır (yalnız sayı, sürücü harfi ve boolean
      basar; standart Windows/CIM davranışından gelir, delta provasında
      doğrulanır):

```powershell
$cdr = $null; try { $cdr = @(Get-CimInstance -ClassName Win32_CDROMDrive -ErrorAction Stop) } catch { $cdr = $null }
$cdTr = $null; try { $cdTr = @([System.IO.File]::ReadAllLines("<evidence-dir>\technical-record.txt", (New-Object System.Text.UTF8Encoding($false)))) } catch { $cdTr = $null }
if ($null -eq $cdr) { "STOP CDROM_QUERY=FAIL" } else { "CDROM_DRIVE_COUNT=$($cdr.Count)"; $cdL = [string[]]@($cdr | ForEach-Object { [string]$_.Drive }); [Array]::Sort($cdL, [System.StringComparer]::Ordinal); if (($null -ne $cdTr) -and ($cdTr -ccontains "CDROM_DRIVE_COUNT=$($cdr.Count)") -and ($cdTr -ccontains ('OPTICAL_DRIVE_LETTERS=' + ($cdL -join ',')))) { "OPTICAL_DRIVES_MATCH_RECORD=True" } else { "STOP OPTICAL_DRIVES_MATCH_RECORD=False" }; foreach ($cd in $cdr) { $cdMl = $cd.MediaLoaded; if ($cdMl -is [bool]) { "OPTICAL_MEDIA_LOADED=$cdMl drive=$($cd.Drive)" } else { "STOP OPTICAL_MEDIA_LOADED=UNKNOWN drive=$($cd.Drive)" } } }
Remove-Variable cdr, cdTr, cdL, cd, cdMl -ErrorAction SilentlyContinue
```

      Beklenen: `CDROM_DRIVE_COUNT=<n>`, `OPTICAL_DRIVES_MATCH_RECORD=True`
      (sayı ve sürücü harfleri §4.4/6 teknik kaydıyla **birebir** eşit;
      revizyon 2, L-2) ve her optik sürücü için
      `OPTICAL_MEDIA_LOADED=False drive=<sürücü-harfi>`. Bu kural yalnız
      **yerleşik** optik sürücü içindir; harici (USB) bir optik sürücü
      harici disk kuralına tabidir ve takılıysa kayıtla eşleşme bozulur.
    - **Açık DUR satırları (optik sürücü).**
      - **İçerik penceresinden önce:** `STOP
        OPTICAL_DRIVES_MATCH_RECORD=False` veya `OPTICAL_MEDIA_LOADED=True`
        çıkarsa (ör. bağlı bir ISO/sanal sürücü veya takılı disk),
        operatör sanal sürücüyü ayırır / medyayı çıkarır ve optik bloğu
        **bir kez** yeniden çalıştırır; ikinci ölçüm de eşleşmezse
        (`OPTICAL_DRIVES_MATCH_RECORD=True` ve her sürücüde
        `OPTICAL_MEDIA_LOADED=False` alınamazsa): **DUR** (Y5).
      - `STOP CDROM_QUERY=FAIL` veya `STOP OPTICAL_MEDIA_LOADED=UNKNOWN`
        (pencere öncesinde): **DUR** (Y5); yeniden çalıştırma yoktur.
      - **İçerik penceresi içinde** her uyuşmazlık — `STOP
        OPTICAL_DRIVES_MATCH_RECORD=False`, `OPTICAL_MEDIA_LOADED=True`,
        bir optik sürücüye medya takılması veya görüntü bağlanması —
        doğrudan **DUR** (H40); çıkarıp yeniden ölçme yoktur.
    - **Açık DUR satırları (harici disk).**
      - `EXTERNAL_DISK_REMOVED=False`, durum okunamıyor veya çift eksik:
        **DUR** (Y5).
      - Çiftin ikisi de `True` (çelişkili kayıt) veya
        `EXTERNAL_DISK_ENCRYPTED=True`: **DUR** (Y5).
      - Çıkarılmış bir sürücü pencere içinde yeniden takılırsa: **DUR**
        (H40).
      - Pencere içinde daha önce kayda girmemiş **yeni** bir harici veya
        çıkarılabilir sürücü takılırsa: **DUR** (H40).
    - **Yapılamayan her durum DUR'dur:** kapsayıcı §4.4'e göre
      doğrulanamıyorsa, harici disk kuralı sağlanmıyorsa ya da operatör
      durumu doğrulayamıyorsa: **DUR — gerçek belge teslim alınmaz** (adım
      4'te) veya **silme yapılmaz** (silme günü; veri §28.1/6 gereği
      korunur ve avukata bildirilir).
    - Kapsayıcının şifreli olduğu bir komutla değil, VeraCrypt arayüzünün
      ekran okumasıyla ve §4.4'teki yol/dosya sistemi ölçümleriyle
      doğrulanır (§32/12).
11. Bu sınırın ihlali veya ihlal şüphesi **DUR**'dur (H40) ve Form **E3**'e
    göre dosya avukatına **hemen telefonla** ve **aynı gün** kişisel veri
    içermeyen yazılı e-posta veya mesajla bildirilir; olay ve alınan
    önlemler kişisel veri içermeyen bir olay kaydına yazılır. Evidence:
    `INCIDENT_PHONE_NOTIFIED=True`, telefon bildirimi için sesli görüşme
    satırı `INCIDENT_NOTICE_CHANNEL=VOICE_CALL at=<zaman-damgası>` (§21/5),
    `INCIDENT_WRITTEN_NOTICE_SAME_DAY=True`, yazılı bildirim için karar
    kanalı satırı `OUTBOUND_NOTICE_SENT seq=<n> sha256=<64-küçük-hex>`
    (§21/4; bildirim dava içeriği ve kişisel veri taşımaz) ve olay kaydının
    SHA-256'sı. Telefon bildirimi sesli görüşmedir ve bu cihazdan
    yapılmaz (§21/5).

### 4.3 İçerik oturumunun açılması ve kanal kapısı (bağlayıcı)

Kaynak: Temel L473–L613. **Sapmalar:** içerik penceresinin bitiş adımı
zincir adım 26–27'ye bağlandı; handler sınıflandırmasındaki maskeleme
cümlesi çıkarıldı; (a)'ya Claude Code/VS Code ve IDE klon kuralı
paragrafı eklendi (revizyon, §34). Komut blokları **birebirdir**; tek
istisna (a) Adım 1 tarama bloğudur: revizyon 3'te kültürden bağımsız
eşleşmeye geçirilmiştir (F-D2-TRCULTURE; §34.9).

**İçerik penceresi**, gerçek belgenin teslim alındığı andan (zincir adım 5)
gerçek verinin, geçici kopyaların ve kapsayıcının silinmesinin veya
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

Bu, içerik penceresi boyunca Claude Code'un ve VS Code'un **hiç**
kullanılmaması demektir (§1.6/5). Ajana yalnız §4.2/7 kapsamındaki değerler,
çalışma ağacına erişimi olmayan bir oturuma aktarılabilir. Ayrıca
kapsayıcıdaki repo klonu (`<repo-root>`) **hiçbir zaman** — pencere içinde
ve dışında — VS Code'da veya herhangi bir IDE/editörde açılmaz; klon
üzerinde yalnız içerik oturumundaki `git` komutları (§13.2) çalışır. Bu
yüzden IDE'lerin git ayarları (otomatik fetch, staging) bu klonu etkilemez
(kullanıcı kararı D18).

Operatör bunu iki adımla ölçer ve kaydeder. **Asıl kapı Adım 2'deki
insan-only oturum beyanıdır**; Adım 1 yalnız yardımcı bir sinyaldir.

Adım 1 — yardımcı süreç adı taraması (yalnız süreç **adı** basar; liste
**tüketici değildir**, standart Windows davranışından gelir). Sabit adlı bir
tarama güvenlik garantisi **değildir**: `node`, `Code - Insiders`,
`python`, `powershell` veya tarayıcı gibi genel taşıyıcı süreçler AI
araçlarını veya eklentilerini barındırabilir ve bu desenle **ayırt
edilemez**. `0` sonucu tek başına kanalların kapalı olduğunu kanıtlamaz.
Eşleşme büyük-küçük harfe duyarsız ve **kültürden bağımsızdır**
(revizyon 3; F-D2-TRCULTURE): tr-TR kültüründe `-match` ile `(?i)`
büyük `I`'yı küçük `i` ile eşleştirmez (delta2 kaydı 0.6: tr-TR 0/3,
CultureInvariant 3/3):

```powershell
$channelPattern = 'claude|chatgpt|copilot|cursor|windsurf|^code$|pycharm|idea|webstorm|rider|teams|zoom|anydesk|teamviewer|quickassist|onedrive|dropbox|googledrive'
$channelOptions = [System.Text.RegularExpressions.RegexOptions]'IgnoreCase, CultureInvariant'
$channelNames = @(Get-Process | Select-Object -ExpandProperty ProcessName -Unique | Where-Object { [regex]::IsMatch($_, $channelPattern, $channelOptions) } | Sort-Object)
"AI_CHANNEL_PROCESS_COUNT=$($channelNames.Count)"; foreach ($n in $channelNames) { "AI_CHANNEL_PROCESS=$n" }
"AI_CHANNEL_SCAN at=$([DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz', [System.Globalization.CultureInfo]::InvariantCulture))"
Remove-Variable channelPattern, channelOptions, channelNames, n -ErrorAction SilentlyContinue
```

Beklenen: `AI_CHANNEL_PROCESS_COUNT=0`. Eşleşen her araç kapatılır ve tarama
yeniden çalıştırılır; kapatılamıyorsa **DUR**. Bu "kapat ve yeniden tara"
kuralı yalnız aşağıdaki kapatma prosedürünün **ilk** taramasından önceki
kapatma için geçerlidir; ilk taramadan sonra eşleşme görülürse kapatılıp
yeniden taranmaz (aşağıdaki madde 3). Operatör, bu desende olmayan
ama yukarıdaki altı sınıftan birine giren her aracı da kendi bilgisiyle
kapatır. Çalışma ağacına, `<restricted-dir>`'e veya içerik oturumunun
ekranına erişebilecek bir süreç **bilinmiyorsa** ya da altı sınıftan birine
girip girmediği **sınıflandırılamıyorsa**: **DUR — belge teslim alınmaz.**

**Pilot öncesi bilgisayar hazırlığı (bir kerelik; bağlayıcı; revizyon 5;
kullanıcı kararı D3).** Delta3 provasında (d9d67b7d, §0) kapatma
prosedürü tek başına yetmedi: `OneDrive.Sync.Service` başlangıç
listesinden kapatıldıktan sonra OneDrive'ın zamanlanmış görevleriyle geri
geldi ve VS Code ≥ 1.142 içinde gömülü `copilot-runtime` (VS Code'un
eklenti sunucusunun çocuk süreci; M365 Copilot değildir) çalıştı. Bu
yüzden pilottan **önce**, içerik penceresinin dışında ve hiçbir gerçek
içerik yokken, operatör bu cihazda bir kez şunları yapar:

1. Görev Yöneticisi → **Başlangıç** sekmesi: OneDrive, Microsoft 365
   Copilot (`M365Copilot`), ChatGPT ve Claude (masaüstü) → "Devre dışı
   bırak". Claude masaüstü (planlayıcı) gerektiğinde elle açılır ve her
   içerik penceresinden önce kapatılır (aşağıdaki kapatma prosedürü;
   revizyon 5 düzeltme turu, bağımsız inceleme L8).
2. Görev Zamanlayıcı → Görev Zamanlayıcı Kitaplığı: adı `OneDrive
   Startup Task`, `OneDrive Standalone Update Task` ve `OneDrive
   Reporting Task` ile başlayan **üç** görev → "Devre Dışı Bırak".
   OneDrive bir Windows hizmeti değildir; kullanıcı başına çalışan bir
   uygulamadır, bu yüzden Hizmetler'de görünmez.
3. Bilgisayar yeniden başlatılır.
4. Yeniden başlatmadan hemen sonra, **hiçbir uygulama açmadan** Görev
   Yöneticisi → **Ayrıntılar**: `Code`,
   `copilot-runtime`, `claude`, `ChatGPT`, `M365Copilot`, `OneDrive` ve
   `OneDrive.Sync.Service` (adların sonunda `.exe`) **görünmemelidir**.
   Biri görünüyorsa hazırlık tamamlanmamıştır; içerik penceresi
   açılmaz, ajana pencere dışında dönülür.

Bu hazırlık bu runbook'taki **tek** kalıcı sistem ayarı değişikliğidir
ve yalnız kullanıcı kararı D3 (`SCOPE_APPROVED at=2026-10-18T11:45+03:00`;
§34.11) ile yapılır; başka hiçbir sistem ayarı değiştirilmez. Hazırlık
kanal kapısının yerine geçmez: bağlayıcı ölçüm yine `a2`/`a3`/`a9`
taramalarıdır. Pilot (veya prova) bittikten sonra bu öğelerin yeniden
etkinleştirilmesi ayrı bir kullanıcı kararıdır (§32/40).

**Kapatma prosedürü (bağlayıcı; revizyon 2; L-1; kullanıcı kararı
K-R2-6).** Delta provasında (e11bab73) bu cihazda şu süreçlerin kendiliğinden
çalıştığı ölçüldü: `ChatGPT`, `M365Copilot`, `copilot-runtime`,
`OneDrive` (ve içerik penceresi dışında `claude`, `Code`). Operatör her
içerik oturumunun başında (yeniden başlatmadan sonra dahil):

1. Her uygulamayı kendi tepsi/menüsünden kapatır ("Çık"/"Quit");
   **önce VS Code** tamamen kapatılır (içindeki `copilot-runtime` onunla
   kapanır; revizyon 5); OneDrive için "Eşitlemeyi duraklat" **yeterli
   değildir**, "OneDrive'ı kapat" seçilir.
2. Süreç hâlâ listedeyse Görev Yöneticisi → Ayrıntılar → "Görevi
   sonlandır" kullanır; **yalnız** yukarıdaki hazırlık listesindeki
   adlar (madde 4) sonlandırılır, başka hiçbir süreç sonlandırılmaz
   (revizyon 5).
3. Yukarıdaki taramayı **iki kez** çalıştırır: kapatmadan hemen sonra ve
   **en az 2 dakika sonra**. İki taramada da `AI_CHANNEL_PROCESS_COUNT=0`
   gerekir; ikinci taramada yeniden görünen (kendini yeniden başlatan) bir
   süreç → **DUR** (H40). Her tarama kendi `AI_CHANNEL_SCAN
   at=<zaman-damgası>` satırını basar ve iki tarama da bu satırla birlikte
   evidence'a yazılır (revizyon 2; L-3); iki zaman damgası arasındaki
   süre kayıttan doğrulanır. Kısa aralıklı (< 2 dk) ikinci tarama
   geçersiz sayılır ve en az 2 dakika sonra yeniden yapılır; **ancak**
   geçersiz taramada da `AI_CHANNEL_PROCESS_COUNT` > 0 görülürse **DUR**
   (H40) — süreç kapatılıp yeniden taranmaz. Zaman damgası eksik veya
   okunamıyorsa **DUR** (H40).

**Kit ile yürütme (bağlayıcı; revizyon 3; kullanıcı kararları K-R3-4,
K-R3-8, K-R3-9; Ek R3).** Her içerik oturumu Ek R3/3'teki tek komutla
açılır. Madde 1–2'deki kapatma **`a2`'den önce** yapılır; insan
penceresinde "kapat ve yeniden tara" dalı **yoktur**. Tarama 1 `a2`,
tarama 2 `a3` ile yapılır. `a3`, tarama 1'in `at=` damgasından 120
saniye geçmeden **tarama yapmaz ve kayıt yazmaz**, yalnız kalan süreyi
basar; bu yüzden kit modunda kısa aralıklı (geçersiz) ikinci tarama
oluşmaz. İki taramadan birinde sayı ≠ 0 → `<evidence-dir>\DUR.txt` ve
**DUR** (H40); DUR kilidinden sonra kanal ve E2 adımlarının hiçbiri
çalışmaz (tek istisna aşağıdaki silme oturumunda `a2`/`a3`'tür). Her içerik oturumu `a9` ile biter: `a9`, kullanıcıdan ek işlem
istemeden otomatik bir **kapanış taraması** yapar; sayı ≠ 0 → `STOP
CLOSING_SCAN_OK=False`, bulgu kaydı ve `DUR.txt` (H40). Pencere boyunca
hiçbir sohbet, planlayıcı oturumu veya yardım sayfası açılmaz; tek yardım
pencereden önce basılmış tek sayfalık adım listesidir (Ek R3/5); gözlemler
yalnız basılı not formuna (Ek R3/6) kısa kodlarla yazılır. **DUR anında**
(revizyon 5; kullanıcı kararı D2; delta3 bulgusu H1): kâğıt varsa yırtılır
ve `a8`; sonra `a9` yazılır; sonra pencere kapatılır; kit yeniden
**açılmaz** (ajan, pencere kapandıktan sonra yazılı olarak silme oturumu
istemedikçe); hiçbir yapay zekâ aracı veya sohbet **açılmaz**, ekran
yapıştırılmaz veya fotoğraflanmaz; olan not formuna yazılır; ajana ancak
pencere kapandıktan sonra dönülür. DUR, gerçek dosya açıkken en olası
"yardım arama" anıdır; pencere açıkken bir yapay zekâ aracının veya
sohbetin açılması zaten H40'tır. Operatör
pencereye fare ile tıklamaz; başlıkta "Seç"/"Select" görünürse Esc'e
basar (konsol seçim kipi yazımı durdurabilir; kanıtlanmış bir neden
değildir, sertleştirmedir). Runbook'un kendisinin yapay zekâ özelliği
taşımayan yerel bir metin görüntüleyicide salt-okunur açık tutulması
yardım sayfası sayılmaz (R3 düzeltme turu; inceleme L-3).

**Silme (teardown) oturumu (R3 düzeltme turu; kullanıcı kararı
H-1=A).** `<evidence-dir>\DUR.txt` varken açılan pencere bir
**silme oturumudur**; `ac.ps1` bunu yükleme anında belirler ve
`KIT_TEARDOWN_SESSION=True` satırını `ac.txt`'ye ve o oturumun her adım
kaydına yazar. Silme oturumunda `a2` ve `a3` kilitte de çalışır ve
normal oturumla aynı denetimleri yapar (`CONTENT_SESSION_EP`, N6, iki
kanal taraması, 120 sn aralık; hiçbir kapı gevşemez); `a4`–`a7` bu
pencerede, kilit sonradan kaldırılmış olsa bile, çalışmaz; `a8` ve `a9`
değişmez. Silme oturumu yalnız §25.2/8–9 ve §28 işleri içindir ve
onların yazılı karar ve ayrı `REAL_ACTION_APPROVED` şartlarını
değiştirmez. Kilit bir pencerenin içinde oluşursa o pencere silme
oturumu olmaz: orada `a2`/`a3` çalışmaz; pencere kapatılır ve tek
sayfadaki komutla yeniden açılır.

Kapatma prosedürü yalnız pencere boyunca kapatmadır; **hiçbir sistem
ayarı değiştirmez**. Kalıcı ayar değişikliği yalnız yukarıdaki bir
kerelik bilgisayar hazırlığıdır (revizyon 5; kullanıcı kararı D3); o
listenin dışındaki her kalıcı değişiklik ayrı kullanıcı onayı gerektirir.

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
`powershell.exe -NoProfile` komutuyla (bayrak kısaltılmadan) açılır.
Revizyon 3'ten itibaren (kullanıcı kararı K-R3-2) oturum Ek R3/3'teki
komutla açılır: `powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit
-Command ". '<evidence-dir>\kit\ac.ps1'"`. `-ExecutionPolicy Bypass` yalnız
bu süreç içindir; sistem ayarı değişmez (bu cihazda tanımsız ilke
`Restricted` demektir ve `.ps1` dosyaları bayraksız çalışmaz). `ac.ps1`
yalnız pin, ayar ve kilit denetimi yapar ve kit komutlarını tanımlar;
içerik okumaz, araç çağırmaz. Aşağıdaki blok kit modunda `a2` içinde,
değişmeden çalışır; `a2` ayrıca `CONTENT_SESSION_EP=Bypass` yazar. Oturumun
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
`COMMAND_VALIDATION_HANDLER_STATE=NONE`, `HISTORY_SAVE_STYLE=SaveNothing`
(kit modunda ayrıca `CONTENT_SESSION_EP=Bypass`).
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

**(c) Geçmiş dosyasının değişmezliği (sentetik prova ve PR-NOPROFILE).** Temel
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
yeniden incelenir; gerçek veriyle yürütme başlamaz. (c) bloğu sentetik
provada ve gerçek dosyadan önceki insan-only PR-NOPROFILE denemesinde
(§1.6/5) kullanılır.

### 4.4 Yerel şifreli kapsayıcı sözleşmesi (bağlayıcı)

YENİ (revizyon; form v5 E1, E4, F4; kullanıcı kararları K4, D2, D3, D4,
D5, D8, D12). Bu bölümdeki komut blokları standart PowerShell/.NET ve
Windows davranışından gelir ve §1.6/3 delta provasında doğrulanır.

1. **Araç ve kurulum.** Kapsayıcı aracı **VeraCrypt**'tir: `<container-file>`
   bir VeraCrypt **dosya kapsayıcısıdır**, **NTFS** ile biçimlendirilir ve
   **bir sürücü harfine** (`<container-root>`) bağlanır; klasöre bağlama
   kullanılmaz. VeraCrypt, Poppler (`pdftotext`) ve 7-Zip kurulumları pilot
   öncesi hazırlıktır: içerik penceresinden **önce**, her biri **ayrı
   `REAL_ACTION_APPROVED`** ile yapılır. İndirme bir dış ağ işlemidir ve
   zincirin parçası değildir (§21). VeraCrypt'te parola önbelleği ve
   bağlama geçmişi kaydı kapalıdır; arayüzdeki adları provada doğrulanır.
2. **Oluşturma (tek-çalışım).** `<container-file>` için kapı **iki
   aşamalıdır** (§13.8): **(i) oluşturmadan önce** ebeveyn dizin kapısı
   `PATH_OK=container-file-parent` verir (yol ve ebeveyn çözümlü, ebeveyn
   mevcut ve reparse point içermez, korunan dizinlerle örtüşmez,
   `<container-file>` henüz **yoktur**); kapsayıcı ancak bundan sonra, ayrı
   `REAL_ACTION_APPROVED` ile, **bir kez** oluşturulur; **(ii)
   oluşturduktan sonra** yaprak-dosya kapısı `PATH_OK=container-file`
   verir. (i) `STOP` verirse oluşturma yapılmaz, **DUR** (H52); (ii) `STOP`
   verirse kapsayıcı kullanılmaz, yeniden oluşturulmaz, **DUR** (H52) ve
   kullanıcı kararı. Kapsayıcı **sabit boyutludur** (dinamik/seyrek
   değildir); böylece §28.3.3'teki boyut eşliği anlamlıdır. Parola/anahtar **tek kullanımlıktır**: yalnız bu
   pilot için üretilir, başka bir yerde kullanılmamıştır, parola
   yöneticisine, buluta, panoya veya bu runbook'un herhangi bir dosyasına
   yazılmaz; yalnız kâğıt veya çevrimdışı bir kayıtta durur ve pilot
   sonunda imha edilir (§28.3.3). Evidence: `CONTAINER_ONE_TIME_KEY=True`
   ve `CONTAINER_FILE_BYTES=<bayt>` (kapsayıcı dosyasının boyutu).
3. **Düzen.** `<container-root>`'un doğrudan altında yalnız `<pilot-root>`
   oluşturulur. `<pilot-root>` oluşturulur oluşturulmaz, içine başka hiçbir
   şey konmadan madde 4'teki ACL sıkılaştırması uygulanır. Ardından
   `<pilot-root>` altında yalnız şunlar oluşturulur: `<repo-root>` (klon),
   `<restricted-dir>`, `<container-temp>` ve `<intake-dir>`; başka her öğe
   **DUR**'dur (H52; §13.8 `Test-PilotPilotRoot`). Klon, içerik penceresinden
   önce, yürütme yetkisinde onaylı commit'te bulunan yerel repodan alınır:

```powershell
git clone --no-hardlinks -b claude-dev "<source-repo-root>" "<repo-root>"
```

   Klonun branch'i ve HEAD'i §13.2 ile ölçülür. `<evidence-dir>`
   kapsayıcının **dışındadır** (kullanıcı kararı D2); `<restricted-dir>`
   **içindedir**. PostgreSQL kümesi ve `<python-runtime-root>` kapsayıcı
   dışında kalır; kümede yalnız opak kimlikler ve hash'ler bulunur (§10.3,
   Form F6).
4. **ACL sıkılaştırması ve principal ölçümü (kullanıcı kararı D4; prova
   inceleme bulgusu M-3).** Yeni biçimlendirilmiş bir NTFS biriminin kökü
   varsayılan olarak geniş gruplara (ör. "Authenticated Users") yetki
   verebilir; bu gruplar bu cihazdaki yerel sandbox hesaplarını da kapsar.
   Bu yüzden içeriği kapsayıcıya taşımak (K4) prova incelemesinin M-3
   bulgusunu **tek başına kapatmaz**; kapatan, aşağıdaki sıkılaştırma ve
   ölçümdür. İzinli principal kümesi **yalnız** şudur: operatörün kendi
   kullanıcı SID'i, `SYSTEM` (`S-1-5-18`) ve `Administrators`
   (`S-1-5-32-544`). Sıkılaştırma `<pilot-root>` boşken, ayrı
   `REAL_ACTION_APPROVED` ile, **bir kez** uygulanır:

```powershell
$opSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& "$env:SystemRoot\System32\icacls.exe" "<pilot-root>" /inheritance:r /grant:r "*$($opSid):(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
"ICACLS_RC=$LASTEXITCODE"
Remove-Variable opSid -ErrorAction SilentlyContinue
```

   Beklenen: `ICACLS_RC=0`; aksi **DUR** (Y17). Ölçüm (zincir adım 4'te,
   her içerik oturumunun başında ve kapanış manifestinden önce; yalnız
   boolean basar):

```powershell
$aclAllowed = @([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18', 'S-1-5-32-544')
$aclBad = -1
try { $aclItems = @(Get-Item -LiteralPath "<pilot-root>" -Force) + @(Get-ChildItem -LiteralPath "<pilot-root>" -Recurse -Force -ErrorAction Stop); $aclBad = 0; foreach ($aclIt in $aclItems) { $acl = Get-Acl -LiteralPath $aclIt.FullName; if (($aclIt.FullName.TrimEnd('\') -eq ("<pilot-root>").TrimEnd('\')) -and ($acl.AreAccessRulesProtected -ne $true)) { $aclBad++ }; foreach ($r in $acl.Access) { $sid = $r.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; if (([string]$r.AccessControlType -cne 'Allow') -or ($aclAllowed -cnotcontains $sid)) { $aclBad++ } } } } catch { $aclBad = -1 }
if ($aclBad -eq 0) { "PILOT_ACL_PRINCIPALS_OK=True" } else { "STOP PILOT_ACL_PRINCIPALS_OK=False" }
Remove-Variable aclAllowed, aclBad, aclItems, aclIt, acl, r, sid -ErrorAction SilentlyContinue
```

   Beklenen: `PILOT_ACL_PRINCIPALS_OK=True`. İzinli küme dışındaki her
   principal (ör. "Authenticated Users", "Users", "Everyone", bir sandbox
   grubu veya çözülemeyen bir SID), her deny kaydı veya mirası kesilmemiş
   bir `<pilot-root>`: **DUR** (Y17).
5. **Geçici dizin (kullanıcı kararı D5).**
   - **Sistem Temp kaydı (`<system-temp>`; bağımsız inceleme H-1).**
     Zincir adım 4'te, ilk içerik oturumu açılmadan önce, TEMP'i
     yönlendirilmemiş, **insan-only** bir PowerShell oturumunda (§4.2/6;
     hiçbir AI asistanı bu oturumu yürütmez, ekranını veya çıktısını
     görmez) **bir kez** iki yol okunur ve ekranda gösterilir; operatör
     `<system-temp-user>` ve `<system-temp-windows>` yer tutucularını bu
     değerlerle **aynen** doldurur. Ekrandaki mutlak yollar Windows
     kullanıcı profil adını taşıyabilir (§32/21); §1.5 gereği evidence'a,
     bu belgeye veya bir AI oturumuna **yazılmaz/aktarılmaz**; yalnız
     SHA-256'ları exclusive-create ile
     `<evidence-dir>\system-temp.txt` dosyasına yazılır (önce §13.8
     `PATH_OK=evidence-dir` alınmıştır ve §10.5 yardımcıları tanımlıdır;
     `<system-temp>` kullanan `external-root-contract` ve kapsayıcı dosyası
     kapıları bu kayıttan **sonra** çalışır):

```powershell
function Get-PilotStringSha([string]$s) { $sha = [System.Security.Cryptography.SHA256]::Create(); try { return ([System.BitConverter]::ToString($sha.ComputeHash((New-Object System.Text.UTF8Encoding($false)).GetBytes($s)))).Replace('-', '').ToLowerInvariant() } finally { $sha.Dispose() } }
$stUser = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\'); $stWin = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($env:SystemRoot, 'Temp')).TrimEnd('\')
"SYSTEM_TEMP_USER=$stUser"; "SYSTEM_TEMP_WINDOWS=$stWin"
if (Write-PilotExclusive "<evidence-dir>\system-temp.txt" @('# kind=system-temp', ('SYSTEM_TEMP_USER_SHA256=' + (Get-PilotStringSha $stUser)), ('SYSTEM_TEMP_WINDOWS_SHA256=' + (Get-PilotStringSha $stWin)))) { "SYSTEM_TEMP_RECORDED=True" } else { "STOP SYSTEM_TEMP_RECORDED=False" }
Remove-Variable stUser, stWin -ErrorAction SilentlyContinue
```

     Beklenen: `SYSTEM_TEMP_RECORDED=True`; aksi **DUR** (H52). Kayıt
     yeniden üretilmez. §13.8 ve §28'deki korunan listeler
     `[System.IO.Path]::GetTempPath()` yerine `<system-temp-user>`,
     `<system-temp-windows>` ve `<container-temp>` kullanır; böylece
     kapıların sonucu TEMP yönlendirmesinden bağımsızdır.
   - **Yönlendirme.** Her içerik oturumunda, §4.3 (b) bloğundan hemen
     sonra ve gerçek içeriğe dokunan ilk komuttan önce, önce henüz
     yönlendirilmemiş Temp yolunun ve iki yer tutucunun kayıtla aynı
     olduğu doğrulanır; yalnız bu doğrulama geçerse, yalnız **o süreç
     kapsamında** TEMP ve TMP `<container-temp>` dizinine yönlendirilir
     (§13.8 ortak yardımcıları ve yukarıdaki `Get-PilotStringSha` aynı
     oturumda önce tanımlanır; yalnız fonksiyon tanımıdır, yan etkisi
     yoktur):

```powershell
$stRec = @([System.IO.File]::ReadAllLines("<evidence-dir>\system-temp.txt", (New-Object System.Text.UTF8Encoding($false))))
$stOk = (Test-PilotResolved "<system-temp-user>") -and (Test-PilotResolved "<system-temp-windows>") -and ([System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') -eq ("<system-temp-user>").TrimEnd('\')) -and ($stRec -ccontains ('SYSTEM_TEMP_USER_SHA256=' + (Get-PilotStringSha ("<system-temp-user>").TrimEnd('\')))) -and ($stRec -ccontains ('SYSTEM_TEMP_WINDOWS_SHA256=' + (Get-PilotStringSha ("<system-temp-windows>").TrimEnd('\'))))
if ($stOk) { "SYSTEM_TEMP_MATCH=True"; $env:TEMP = "<container-temp>"; $env:TMP = "<container-temp>" } else { "STOP SYSTEM_TEMP_MATCH=False" }
"TEMP_IN_CONTAINER=$([System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') -eq ("<container-temp>").TrimEnd('\'))"
Remove-Variable stRec, stOk -ErrorAction SilentlyContinue
```

   - Beklenen: `SYSTEM_TEMP_MATCH=True` ve `TEMP_IN_CONTAINER=True`
     (yönlendirilmiş Temp yolu `<container-temp>`'e **tam eşittir**; önek
     eşliği yetmez); değilse **DUR** (H52). `<container-temp>` §13.8 yol
     kapısından geçer.
   - **Kit modunda yönlendirme (revizyon 5; kullanıcı kararı D1; delta3
     bulgusu H2).** Aktarım (E2) günü kit penceresinde yönlendirmeyi `a4`
     (N108) kendisi, kendi kaydını oluşturmadan **önce** yapar: canlı
     Temp yolunu ve `%SystemRoot%\Temp` yolunu yukarıdaki
     `system-temp.txt` kaydının iki SHA-256'sıyla karşılaştırır (yollar
     hiçbir yere yazılmaz/basılmaz), `kit-values.txt`'deki
     `container-temp` dizininin var olduğunu denetler, TEMP ve TMP'yi o
     dizine yönlendirir ve sonucu doğrular. Biri geçmezse `a4` kayıt
     yazmaz, kilit koymaz ve `a4 BASLAMADI: …` iletisiyle ne yapılacağını
     söyler; geçerse kaydına `SYSTEM_TEMP_MATCH=True`,
     `KIT_TEMP_REDIRECT=True` ve yeniden ölçülmüş
     `KIT_TEMP_IN_CONTAINER=True` yazılır. Bu yüzden kit penceresinde
     yukarıdaki yönlendirme bloğu (N13) elle **çalıştırılmaz**; TEMP o
     pencerede zaten değiştirilmişse `a4` reddeder ve pencere `a9` ile
     kapatılıp yeniden açılır. E2 dışındaki içerik oturumlarında (§11–§28;
     silme oturumu dahil) N13 bu maddede yazıldığı gibi elle çalışır.
     Sistem Temp kaydı (N12) iki yolda da ön koşuldur. Kitin `container-temp`
     denetimi §13.8 `PATH_OK=container-temp` kapısının yerine geçmez.
     Yer gerekçesi (`a3` değil `a4`): `a3` içinde yönlendirme, kapsayıcının
     kanal kapısı geçmeden bağlanmasını gerektirirdi; `a4` ise kapı ve
     zincir adım 4'ün kalan blokları geçtikten sonra çalışır (§34.11).
   - User ve Machine kapsamındaki TEMP/TMP **değiştirilmez**; kayıt
     defterine yazılmaz.
   - Yönlendirme yalnız bu oturumdan başlatılan süreçleri etkiler.
     Tarayıcı, Dosya Gezgini ve başka GUI araçları etkilenmez. Bu yüzden
     indirme yalnız "Farklı kaydet" ile doğrudan `<intake-dir>`'e yapılır;
     arşiv yalnız bu oturumdan 7z komut satırıyla açılır; sürükle-bırak ile
     açma **yasaktır** (§6.4).
   - `<container-temp>` içindeki dosyalar F1 geçici kopyasıdır (§28.6).
6. **Teknik kayıt (form v5 E1, E4).** Kapsayıcı aracı ve sürümü, `pdftotext`
   sürümü ve iki araç dizininin dosya manifest hash'leri, zincir adım 4'te,
   intake'ten önce, **bir kez** `<evidence-dir>\technical-record.txt`
   dosyasına exclusive-create ile yazılır. Sürümler araçların kendi
   çıktısından okunur (`& "<pdftotext>" -v`; `& "<7z>"` çıktısının ilk
   satırı; VeraCrypt "Hakkında" ekranı) ve elle yazılır. Yardımcı fonksiyon
   ve kayıt (§10.5 ve §13.8 yardımcıları önce tanımlanmış olmalıdır):

```powershell
function Get-PilotBinManifestSha([string]$dir) { try { if (-not ((Test-PilotResolved $dir) -and (Test-Path -LiteralPath $dir -PathType Container) -and (Test-PilotNoReparse $dir))) { return $null }; $lines = [string[]]@(Get-ChildItem -LiteralPath $dir -Force -File -ErrorAction Stop | ForEach-Object { "{0}`t{1}" -f $_.Name, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() }); if ($lines.Count -lt 1) { return $null }; [Array]::Sort($lines, [System.StringComparer]::Ordinal); $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes(($lines -join "`n") + "`n"); $sha = [System.Security.Cryptography.SHA256]::Create(); try { return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() } finally { $sha.Dispose() } } catch { return $null } }
$popSha = Get-PilotBinManifestSha "<poppler-bin-dir>"; $szSha = Get-PilotBinManifestSha "<sevenzip-root>"
$cdRec = $null; try { $cdRec = [string[]]@(Get-CimInstance -ClassName Win32_CDROMDrive -ErrorAction Stop | ForEach-Object { [string]$_.Drive }) } catch { $cdRec = $null }
$cdRecOk = ($null -ne $cdRec) -and (@($cdRec | Where-Object { $_ -cnotmatch '^[A-Z]:$' }).Count -eq 0)
$cdRecLines = @(); if ($cdRecOk) { [Array]::Sort($cdRec, [System.StringComparer]::Ordinal); $cdRecLines = @("CDROM_DRIVE_COUNT=$($cdRec.Count)", ('OPTICAL_DRIVE_LETTERS=' + ($cdRec -join ','))) }
if (($null -ne $popSha) -and ($null -ne $szSha) -and $cdRecOk -and (Write-PilotExclusive "<evidence-dir>\technical-record.txt" (@('# kind=technical-record', 'CONTAINER_TOOL=VeraCrypt', 'CONTAINER_TOOL_VERSION=<veracrypt-version>', 'PDFTOTEXT_VERSION=<pdftotext-version>', "POPPLER_BIN_MANIFEST_SHA256=$popSha", 'SEVENZIP_VERSION=<7z-version>', "SEVENZIP_ROOT_MANIFEST_SHA256=$szSha") + $cdRecLines))) { "TECHNICAL_RECORD=WRITTEN" } else { "STOP TECHNICAL_RECORD=FAIL" }
Remove-Variable popSha, szSha, cdRec, cdRecOk, cdRecLines -ErrorAction SilentlyContinue
```

   Beklenen: `TECHNICAL_RECORD=WRITTEN`. Kayıt ayrıca yerleşik optik
   sürücülerin sayısını ve sürücü harflerini taşır (revizyon 2; L-2):
   `CDROM_DRIVE_COUNT=<n>` ve `OPTICAL_DRIVE_LETTERS=<harfler>`
   (sıralı, virgülle ayrılmış; sürücü yoksa boş). Blok çalıştırılmadan
   önce harici (USB) optik sürücüler harici disk kuralı gereği çıkarılmış
   olmalıdır (§4.2/10). Bu cihazda beklenen değerler `CDROM_DRIVE_COUNT=1`
   ve `OPTICAL_DRIVE_LETTERS=E:`'dir; operatör yazılan kaydı ekranda okur
   ve kayıt farklı değer taşıyorsa **DUR** (Y5) — kayıt yeniden üretilmez,
   runbook revizyonu gerekir. Sorgu başarısız olursa veya bir sürücünün
   harfi yoksa kayıt yazılmaz: `STOP TECHNICAL_RECORD=FAIL`. Kayıt yeniden üretilmez, üzerine
   yazılmaz; araç değişirse **DUR** ve runbook revizyonu. `pdftotext` veya
   `7z` her kullanılmadan önce aynı oturumda yeniden doğrulama yapılır:

```powershell
$tr = @([System.IO.File]::ReadAllLines("<evidence-dir>\technical-record.txt", (New-Object System.Text.UTF8Encoding($false))))
$toolOk = ($tr -ccontains ("POPPLER_BIN_MANIFEST_SHA256=" + (Get-PilotBinManifestSha "<poppler-bin-dir>"))) -and ($tr -ccontains ("SEVENZIP_ROOT_MANIFEST_SHA256=" + (Get-PilotBinManifestSha "<sevenzip-root>")))
if ($toolOk) { "TOOL_MANIFEST_MATCH=True" } else { "STOP TOOL_MANIFEST_MATCH=False" }
Remove-Variable tr, toolOk -ErrorAction SilentlyContinue
```

   `TOOL_MANIFEST_MATCH=True` dışındaki her sonuç: araç **çalıştırılmaz**,
   **DUR** (Y5). Kit modunda `a4`, teknik kayıt yoksa veya biçimi
   geçersizse kayıt ve kilit yazmadan reddeder ve eksiği adlandırır
   (revizyon 5 ek kararı; §34.11); biçimi geçerli bir kaydın araçlarla
   uyuşmaması kilitli kalır.
7. **Kapsayıcı doğrulaması.** Zincir adım 4'te, her içerik oturumunun
   başında ve her silme gününde operatör VeraCrypt arayüzünde kapsayıcının
   `<container-file>`'dan `<container-root>` sürücü harfine bağlı olduğunu
   ekranda okur; §13.8'deki `container-root`, `pilot-root` ve çocuk
   kapıları `PATH_OK` verir. Evidence: `CONTAINER_MOUNTED_AS_DRIVE_LETTER=True`
   ve hepsi sağlanınca `CONTAINER_VERIFIED=True`. Ekran görüntüsü alınmaz.
   Biri sağlanmazsa: **DUR** (Y5).
8. **Kapsayıcı dışında kalabilen izler.** Sayfa dosyası, hazırda bekletme
   dosyası, Windows Search indeksi ve antivirüs karantinası şifresiz sistem
   sürücüsünde kalabilir; bu runbook bunları mekanik olarak denetleyemez
   (§32/18, §32/25). Bu çelişki gerçek dosyadan önce §1.6/5'teki yazılı
   bildirim ve dosya avukatının `LEGAL_APPROVED` cevabıyla kapılanır.

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
dağıtılmıştır. Kullanılan form **sürüm 5**'tir (§0); soru kodları v5'e
göredir (A–I kodları v3 ile aynıdır; v5 ayrıca Ek 1 "Yerel Pilot
Aydınlatma Metni Taslağı" ve Ek 2 "Operatör Gizlilik ve Veri Güvenliği
Taahhüdü" içerir).

### 6.1 Genel kural

- Form v5 **iki ayrı imzalayanla** alınır: A–F bölümleri I bölümüyle
  (I2–I4) **protokol inceleyicisi** tarafından; G bölümü kendi G10/G11
  alanıyla **dosya avukatı** tarafından (§8). Ek 2, operatör ve dosya
  avukatı tarafından ayrıca imzalanır. A–F + I ve Ek 2 gerçek belge teslim
  alınmadan **önce**; G, dosya seçildiğinde ve yine teslimden **önce**
  alınır. İmza biçimi, e-imza geçerliliği, bağlayıcı sürüm ve hash
  kuralları §6.6'dadır.
- Formdaki her soru için kural aynıdır: **cevap yoksa (boş), kutu
  işaretsizse veya cevap aşağıdaki tabloda "DUR" olarak gösterilen
  seçenekse: DUR — gerçek belge teslim alınmaz.** Operatör ve kullanıcı
  cevabı **varsaymaz**, tamamlamaz veya yorumlamaz.
- Formun "Not" kısımlarına yazılan ve bir kapının anlamını değiştiren her
  ek koşul (ör. A1 "Evet, şu ek koşullarla") bu runbook'ta karşılığı
  olmadığı sürece **DUR**'dur: runbook değiştirilir, yeniden incelenir ve
  ancak ondan sonra yürütülür. Ek koşul sahada doğaçlama uygulanmaz.
- Kodla kapanmayan hukuki cevaplar yazılıdır; operatör onların
  doğruluğunu değerlendirmez, yalnız **varlığını** denetler. Rol ayrımı
  (form v5 B1, I): A–F + I cevapları ve imzası **protokol
  inceleyicisinindir** (ör. B3'teki **önerilen** işleme sebebi); G
  bölümü, Ek 2'nin karşı imzası ve **bu dosya için işleme şartının
  teyidi** (§6.3 B3) **dosya avukatınındır**. Protokol inceleyicisinin
  bir cevabı dosya avukatının teyidinin yerine geçmez.

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
| B3 | Protokol inceleyicisinin A–F'deki yazılı (önerilen) işleme sebebi **ve** dosya avukatının, **bu dosya için** uygulanan işleme şartını (6698 sayılı Kanun m.5/2-e; gerekirse m.5/2-c ve/veya m.5/2-ç) adıyla belirten yazılı teyidi (`LEGAL_APPROVED`; zincir adım 3'te, teslimden önce; karar kanalı satırı §21). Evidence: `PROCESSING_BASIS_CONFIRMED=True` ve teyidin `INBOUND_DECISION_RECEIVED` satırı. Form C2 notundaki "Nihai hukuki sebebi avukat teyit eder" ve Ek 1'deki "Uygun bir işleme şartı teyit edilmezse pilot başlamaz" koşulları bu teyitle karşılanır | Boş; dosya avukatının yazılı teyidi yok; teyit hiçbir işleme şartını adıyla belirtmiyor veya "şart yok" diyor: **pilot başlamaz** (Y2) |
| B4 | "Evet, ayrı kişiler" — veya — "Hayır" (form v5 seçeneği) **ve** dosya avukatının iki kişili kontrolün kalktığını kabul eden ayrı yazılı beyanı (form B4 notu; §4.1) | Boş; "Hayır" iken yazılı kabul yok; §4.1 iki kişi kuralı |
| B5 | "Hayır" — veya — "Evet" **ve** Ek 2 (Operatör Gizlilik ve Veri Güvenliği Taahhüdü) hem operatör hem dosya avukatı (veri sorumlusu) tarafından §6.6/1 biçiminde imzalanmış ve alınmış (§6.6/7 `ATT2`) | Boş; "Evet" iken Ek 2 yok veya iki imzadan biri eksik |

### 6.4 E — Cihaz ve güvenlik

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| E1 | "Tek dosyalık pilot alternatifi" (yerel şifreli kapsayıcı) **ve** §4.4 doğrulaması (`CONTAINER_VERIFIED=True`, `PILOT_ACL_PRINCIPALS_OK=True`) ve teknik kayıt | Boş; "Tam disk şifrelemesi" (bu revizyonda yol tanımlı değil, §1.6/4); "Kabul değil"; kapsayıcı doğrulanamadı; E1'e yazılmış, §4.4'te karşılığı olmayan araç adı veya koşul (§6.1, §4.2/10) |
| E2 | "Uzaktan şifreli dosya aktarımı; parola/anahtar ayrı iletişim kanalından" **ve** aşağıdaki taşıyıcı kontrolü; "ayrı iletişim kanalı" bu runbook'ta **yalnız** dosya avukatından operatöre sesli telefon görüşmesidir (`E2_KEY_CHANNEL=VOICE_CALL`; §21/5) | Boş; "Elden / şifreli USB" veya "Diğer" (bu revizyonda tanımlı değil); açık e-posta/mesajlaşma uygulaması eki (form E2 notu); parola sesli görüşme dışında bir kanaldan geldi (Y15); taşıyıcı kontrolü geçmedi |
| E3 | "Kabul" **ve** bildirim yolu yazılı (form v5: dosya avukatına hemen telefon + aynı gün kişisel veri içermeyen yazılı bildirim; §4.2/11) | Boş; yol yazılmamış |
| E4 | "Bu koşulla onaylıyorum" işaretli; araç Poppler `pdftotext`; kesin sürüm teknik kayıtta (§4.4/6) | Boş; onaysız; bulut tabanlı araç; teknik kayıtta sürüm yok |

Aktarım dosyası (`<intake-dir>\transfer.7z`), açılmış içerik ve `pdftotext`
çıktısı dışındaki ara dosyalar kapsayıcı içindeki **geçici kopyalardır**;
Form F1 süresine tabidir (§23, §28.6).

**E2 taşıyıcı kontrolü (bağlayıcı; N-L5; prova incelemesi L2, O3;
kullanıcı kararı D6).** Taşıyıcı, belge cihaza aktarılmadan **önce**
(zincir adım 5'in başında) kontrol edilir ve evidence'a yalnız şu satırlar
yazılır: `E2_CARRIER_KIND=ENCRYPTED_TRANSFER`,
`E2_CARRIER_ENCRYPTED=True/False`, `E2_KEY_SEPARATE_CHANNEL=True/False`,
`E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>`,
`E2_SAVED_DIRECTLY_TO_CONTAINER=True/False`,
`SEVENZIP_ALL_ENTRIES_7ZAES=True/False` ve
`E2_INBOUND_TRANSFER_RECEIVED=True/False`.

- **Kabul edilen tek taşıyıcı türü `ENCRYPTED_TRANSFER`'dır.**
  `E2_CARRIER_KIND=USB` veya `=PAPER` bu revizyonda tanımlı değildir:
  **DUR — belge cihaza aktarılmaz.** Bu yüzden `E2_CARRIER_ENCRYPTED`
  yalnız `ENCRYPTED_TRANSFER` için yazılır; kâğıt teslim ve yerel tarayıcı
  yolu yoktur (L2). Hiçbir harici veya çıkarılabilir sürücü (yazım anında
  `D:` dahil) taşıyıcı olarak kullanılamaz; harici sürücüler içerik
  penceresi boyunca çıkarılmış olmalıdır (§4.2/10; O3).
- **Kanal.** Teslim kanalını **dosya avukatı yazılı olarak** belirler;
  operatör kanal seçmez. Yazılı kanal belirlemesi bir karar kanalı
  kaydıdır: evidence'a `INBOUND_DECISION_RECEIVED seq=<n>
  sha256=<64-küçük-hex>` yazılır (§21).
- **Hukuki soru (`EXTERNAL LEGAL VERIFICATION REQUIRED`).** "AES-256 ile
  şifrelenmiş bir 7z arşivinin **e-posta eki** olarak gönderilmesi,
  formun E2 cevabındaki 'açık e-posta veya WhatsApp eki kullanılmaz'
  ifadesine aykırı mıdır?" sorusu dosya avukatına yazılı olarak sorulur.
  Yazılı cevap gelmeden e-posta eki kanalı **kullanılmaz** (**DUR**).
  Operatör ve ajan bu soruyu yorumlamaz veya cevaplamaz.
- **Biçim.** Aktarım dosyası **AES-256 ile şifrelenmiş bir 7z arşividir**.
  Parola/anahtar aktarım kanalından **ayrı** bir iletişim kanalıyla gelir.
  Bu runbook'ta ayrı kanal **yalnız** dosya avukatından operatöre **sesli
  telefon görüşmesidir** (§21/5; kullanıcı kararı, remediasyon turu 2):
  görüşme bu cihazdan yapılmaz ve bu cihazdan ağ işlemi değildir.
  Evidence'a yalnız `E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>`
  yazılır; `E2_KEY_SEPARATE_CHANNEL=True` **yalnız** bu satırla birlikte
  yazılır. Parola başka bir kanaldan (e-posta, mesajlaşma uygulaması,
  SMS, aktarım kanalının kendisi) gelirse: `E2_KEY_SEPARATE_CHANNEL=False`,
  **DUR** (Y15) ve parola kullanılmaz. Parola, parolanın hash'i veya
  herhangi bir türevi **hiçbir zaman** evidence'a, bir komut satırına,
  dosyaya veya panoya yazılmaz.
- **Arşivin gönderen tarafta hazırlanması (revizyon 2; R-D-7ZPROMPT,
  R-D-7ZFOLDER; kullanıcı kararı K-R2-1).** **Gönderen kuralı** (aşağıdaki
  yöntem kontrolü mekanik olarak daha geniş bir biçimi de — ör. boş
  klasör girdisi taşıyan bir arşivi — geçirebilir;
  `SEVENZIP_FOLDER_ENTRY_COUNT` yalnız bilgidir ve açmada
  `X_ENTRY_COUNT=1` şartı tek dosyayı ayrıca zorlar): arşiv
  **başlıkları açık** (`-mhe=off`) bir AES-256 7z arşividir; 7-Zip'te
  "Dosya adlarını şifrele" kutusu **işaretsizdir**. Arşiv **tek bir PDF**
  taşır, **klasör içermez**, ve PDF kişisel veri içermeyen **nötr** bir
  adla (ör. `belge.pdf`) arşivlenir: başlıklar açık olduğu için girdi adı
  aktarım kanalında görünür (§32/30). Bu biçim kuralı ve aşağıdaki parola
  kuralı dosya avukatına, kanal belirlemesiyle birlikte, karar kanalında
  içeriksiz bir teknik not olarak iletilir (`OUTBOUND_NOTICE_SENT`; §21/4).
  Başlıkları şifreli bir arşiv aşağıdaki yöntem kontrolünde **her zaman**
  `STOP` verir (parola istenmez; revizyon 3'ten itibaren 7z konsolsuz,
  standart girdisi kapalı ve 10 saniyelik bekçiyle çağrılır; bu davranış
  **delta3'te ölçülür**, ölçülene kadar varsayımdır); dosya avukatından
  bu biçimde yeni bir arşiv istenir.
- **Parola biçimi ve girişi (revizyon 2; R-D-TRKBDPW; kullanıcı kararları
  K-R2-3, K-R2-4).** Parolayı dosya avukatı **rastgele** üretir (sözcük,
  ad, tarih kullanılmaz) ve **yalnız** şu 29 sembolü kullanır: büyük harf
  `A B C D E F G H J K L M N P R S T U V Y Z` ve rakam `2 3 4 5 6 7 8 9`
  (I, İ, ı, i, O, Q, W, X, 0, 1, küçük harf ve Türkçe özel harfler
  **yoktur**). Uzunluk **20** karakterdir; sesli görüşmede **4'erli 5
  grup** hâlinde okunur ve operatör her grubu **geri okur**. Harfler
  Türk telefon alfabesiyle, rakamlar Türkçe adıyla, **harf harf** okunur
  ve aynı biçimde geri okunur (revizyon 2; O-7):

  | Sembol | Okunuş | Sembol | Okunuş | Sembol | Okunuş |
  |---|---|---|---|---|---|
  | A | Adana | K | Kars | V | Van |
  | B | Bolu | L | Lüleburgaz | Y | Yozgat |
  | C | Ceyhan | M | Muş | Z | Zonguldak |
  | D | Denizli | N | Niğde | 2 | iki |
  | E | Edirne | P | Polatlı | 3 | üç |
  | F | Fatsa | R | Rize | 4 | dört |
  | G | Giresun | S | Sinop | 5 | beş |
  | H | Hatay | T | Tokat | 6 | altı |
  | J | Jandarma | U | Uşak | 7 | yedi |
  | — | — | — | — | 8 | sekiz |
  | — | — | — | — | 9 | dokuz |

  Bu 29 sembol dışındaki bir okunuş (ör. "Isparta", "Ordu", "sıfır",
  "bir") alfabe dışıdır.
  - Operatör parolayı görüşme sırasında **yalnız kâğıda** yazar (dosya,
    pano, ekran, fotoğraf yok). Giriş **yalnız elle yazmadır**: parola
    panoya veya dosyaya yazılamadığı için yapıştırma bu runbook'ta
    mümkün değildir. Operatör Caps Lock açık yazar. Kit (Ek R3) Caps
    Lock kapalıyken 7z'yi **çağırmaz** ve deneme **harcamaz**; durum her
    denemede `CAPS_LOCK=True attempt=<k>` olarak kayda girer (revizyon
    3; kullanıcı kararı K-R3-7).
  - Operatör alfabe dışı bir karakter duyarsa veya geri okuma tutmazsa
    parola **kullanılmaz** (revizyon 2; L-4): o parolanın kâğıdı **hemen**
    imha edilir (`E2_PASSWORD_PAPER_DESTROYED=True at=<zaman-damgası>
    reason=rejected`), eski `transfer.7z` §28.6 geçici kopya kuralına
    göre exact-path silinir ve dosya avukatı yeni bir parolayla yeni bir
    arşiv üretip yeniden gönderir (parola arşive bağlıdır). Yeni parola
    için yeni bir `E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>` satırı
    yazılır. Yeniden gönderim **en fazla bir kez** yapılır: ikinci
    arşivin parolası da alfabe dışıysa veya geri okuması tutmazsa
    **DUR** (Y5); üçüncü arşiv istenmez. İkinci arşiv aşağıdaki yöntem
    kontrolü ve açma kurallarına aynen tabidir; açmadaki tek ek deneme
    pilot boyunca toplam **bir** kezdir (birinci arşivde kullanıldıysa
    ikinci arşivde yoktur). **Kit modunda (revizyon 3; kullanıcı kararı
    S-2):** geri okuma tutmazsa veya alfabe dışı bir karakter duyulursa
    `a6` `STOP HP_READBACK=fail` yazar ve **DUR** olur (Y5); kâğıt hemen
    imha edilir ve `a8` `reason=rejected` yazar. Bu maddedeki tek
    yeniden gönderim yolu kit ile **yürütülmez**; ancak yeni bir yazılı
    karar ve runbook revizyonu/provası ile açılabilir. Bu bir
    sıkılaştırmadır; hiçbir kapı gevşetilmez.
  - Kullanılan parolanın kâğıdı, açmada başarı (`SEVENZIP_RC=0` ve
    `X_ENTRY_COUNT=1`) alındıktan sonra **aynı gün** imha edilir;
    evidence: `E2_PASSWORD_PAPER_DESTROYED=True at=<zaman-damgası>
    reason=used`. Pilot DUR ile biterse kâğıt yine aynı gün imha edilir:
    `… reason=stopped`. **Kit modunda `reason` operatörden alınmaz**
    (revizyon 3; L-3; kullanıcı kararı K-R3-8): `a8` onu kayıtlardan
    türetir — geri okuma tutmadıysa `rejected`; son deneme kaydında
    (`a7` varsa o, yoksa `a6`) `ATTEMPT_OUTCOME=SUCCESS` ve
    `STEP_RESULT=PASS` varsa `used`; başka her durumda `stopped`. `a8`
    yalnız `steps\e2\a5.txt` `STEP_RESULT=PASS` taşıyorsa kayıt yazar
    (kâğıt ancak `a5` PASS'ten sonra oluşur); geri okuma kaydı yoksa
    `reason=stopped` (R3 düzeltme turu; inceleme M-3; onaylı E3.1 metninin
    kullanıcı onaylı değişikliği). `a8` DUR
    kilidinde de çalışır ve 7z çağırmaz; `a8`'den sonra `a6`/`a7`
    çalışmaz.
- **Kaydetme.** Dosya tarayıcının veya istemcinin "Farklı kaydet"
  iletişim kutusuyla **doğrudan** `<intake-dir>` içine, sabit
  `transfer.7z` adıyla kaydedilir; indirme dizinine veya kapsayıcı dışına
  hiç yazılmaz (`E2_SAVED_DIRECTLY_TO_CONTAINER=True`). Kapsayıcı dışında
  bir kopya oluşursa: **DUR** (H40).
- **Şifreleme yöntemi kontrolü (açmadan önce; remediasyon turu 1).**
  §4.4/6 `TOOL_MANIFEST_MATCH=True` alındıktan sonra, içerik oturumunda,
  arşiv **açılmadan önce** `7z l -slt` çıktısı yalnız bellekte okunur ve
  yalnız klasör sayısı ile sonuç satırı basılır (girdi adları basılmaz).
  **Revizyon 3 (H-1, M-1; kullanıcı kararları K-R3-5, K-R3-6):** 7z
  konsolsuz bir süreç olarak çağrılır; standart girdisi açılır açılmaz
  **kapatılır**, stdout ve stderr'i yakalanır. Böylece 7z operatörün
  konsoluna hiç bağlanmaz, ekrana hiçbir 7z metni düşmez, Ctrl+C 7z'ye
  ulaşmaz ve listelemede **hiçbir zaman** parola istenmez; komut satırına
  `-p` yazılmaz. Çağrıdan **önce** `SEVENZIP_PROC_COUNT_BEFORE` ve
  `LIST_CALL_AT`, dönüşten **sonra** `LIST_RETURN_AT`, `LIST_ELAPSED_MS`,
  `SEVENZIP_LIST_RC`, `SEVENZIP_TYPE_7Z_SEEN`,
  `SEVENZIP_STDERR_LINE_COUNT`, `SEVENZIP_STDERR_BREAK_SEEN`,
  `SEVENZIP_STDERR_ENC_OPEN_FAIL_SEEN` ve `SEVENZIP_PROC_COUNT_AFTER`
  yazılır (yalnız sayı ve boolean; 7z metni ve girdi adları yazılmaz).
  Kit, her satırı basıldığı anda hem dosyaya hem ekrana yazar; böylece
  kayıt ile ekran arasında görünmeyen bölge kalmaz. **Duvar saati
  bekçisi:** 7z 10 saniye içinde dönmezse süreç sonlandırılır
  (sonlandırmanın tamamlanması en çok 2 saniye beklenir) ve `STOP
  SEVENZIP_LIST_TIMEOUT=True` → **DUR** (Y5; K-R2-2: önceden onaylanmış
  yedek yöntem yoktur, ayrı kullanıcı kararı gerekir). 7z döndükten
  sonra çıktısının okunması da en çok 2 saniyeyle sınırlıdır; aşılırsa
  aynı `STOP` yazılır (R3 düzeltme turu; inceleme L-1). Asılma artık insan
  gözlemiyle değil bekçiyle ölçülür; "on saniye bekle, Ctrl+C bas" kuralı
  yoktur. Başlıkları şifreli bir arşiv listelenemez: `Type = 7z` görülmez
  ve çıkış `0` olmaz, sonuç `STOP`'tur (revizyon 2; R-D-7ZPROMPT,
  K-R2-1). Kesin çıkış kodu bu runbook'a **yazılmaz**; bağlayıcı kural
  yalnız "çıkış ≠ 0 → `STOP`"tur ve kesin değer delta3'te ölçülür
  (K-R3-6). Bu yöntemin insan konsolunda asılmadığı **varsayımdır**;
  delta3'te ölçülür (delta2 kanıt incelemesi §6/10).
  **"Break signaled" hipotezi (HK-1; kaynak okuması, ölçülmedi).** 7-Zip
  açık kaynak kodunun okunmasına göre (§34.9) standart girdisi boş veya
  kapalı bir 7z, başlıkları şifreli bir arşivi açarken parola okumada
  EOF görür ve **Ctrl+C olmadan** stderr'e "Break signaled" basıp
  milisaniyeler içinde, sıfır olmayan bir kodla çıkabilir. Bu, delta2
  H2'deki kullanıcı beyanının "Break signaled" kısmını açıklayabilir;
  **kanıtlanmış değildir** ve delta3'te `SEVENZIP_STDERR_BREAK_SEEN` ile
  ölçülür. Hiçbir kapı bu hipoteze dayanmaz. Arşiv türü
  `7z` olmalıdır. Bir girdi **yalnız** klasör işareti taşıyorsa (`Folder
  = +` satırı veya `Attributes` değerinin ilk sözcüğünde büyük `D`)
  **ve** `Size` ile `Packed Size` değerleri `0` veya boşsa klasör sayılır;
  diğer **her** girdi dosyadır, en az bir dosya bulunur ve **her** dosya
  `Encrypted = +` ve `7zAES` yöntemini taşımalıdır (revizyon 2;
  R-D-7ZFOLDER). 7-Zip 26.04, 7z arşivlerindeki klasörler için `Folder =
  +` satırını **basmaz**; bu sürümde klasör tanıma fiilen `Attributes`
  değerindeki büyük `D`'ye dayanır (delta2 D1.3: A2, A3 ve A5 kayıtları
  `SEVENZIP_FOLDER_ENTRY_COUNT=1`; revizyon 3). `Folder = +` alternatifi
  zararsız olduğu için blokta kalır; klasör sayımı başka bir satıra
  dayandırılmaz:

```powershell
$szAt = { [DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz', [System.Globalization.CultureInfo]::InvariantCulture) }
"SEVENZIP_PROC_COUNT_BEFORE=$(@(Get-Process -Name 7z -ErrorAction SilentlyContinue).Count)"
"LIST_CALL_AT=$(& $szAt)"
$szSw = [System.Diagnostics.Stopwatch]::StartNew(); $szTimeout = $null; $szLRc = $null; $szL = @(); $szE = @(); $szP = $null
try { $szPsi = New-Object System.Diagnostics.ProcessStartInfo; $szPsi.FileName = "<7z>"; $szPsi.Arguments = 'l -slt "' + "<intake-dir>\transfer.7z" + '"'; $szPsi.UseShellExecute = $false; $szPsi.CreateNoWindow = $true; $szPsi.RedirectStandardInput = $true; $szPsi.RedirectStandardOutput = $true; $szPsi.RedirectStandardError = $true; $szP = [System.Diagnostics.Process]::Start($szPsi); $szP.StandardInput.Close(); $szOutT = $szP.StandardOutput.ReadToEndAsync(); $szErrT = $szP.StandardError.ReadToEndAsync(); if ($szP.WaitForExit(10000)) { $szP.WaitForExit(); if ($szOutT.Wait(2000) -and $szErrT.Wait(2000)) { $szLRc = $szP.ExitCode; $szL = @($szOutT.Result -csplit "`r?`n"); $szE = @($szErrT.Result -csplit "`r?`n" | Where-Object { $_ -cne '' }); $szTimeout = $false } else { $szTimeout = $true } } else { $szTimeout = $true; try { $szP.Kill(); $null = $szP.WaitForExit(2000) } catch { } } } catch { $szTimeout = $null }
$szSw.Stop()
"LIST_RETURN_AT=$(& $szAt)"
"LIST_ELAPSED_MS=$($szSw.ElapsedMilliseconds)"
if ($szTimeout -eq $true) { "STOP SEVENZIP_LIST_TIMEOUT=True" } elseif ($null -eq $szTimeout) { "STOP SEVENZIP_LIST_START=FAIL" } else { "SEVENZIP_LIST_TIMEOUT=False"; "SEVENZIP_LIST_RC=$szLRc"; "SEVENZIP_TYPE_7Z_SEEN=$($szL -ccontains 'Type = 7z')"; "SEVENZIP_STDERR_LINE_COUNT=$($szE.Count)"; "SEVENZIP_STDERR_BREAK_SEEN=$(@($szE | Where-Object { $_.Contains('Break signaled') }).Count -gt 0)"; "SEVENZIP_STDERR_ENC_OPEN_FAIL_SEEN=$(@($szE | Where-Object { $_.Contains('Cannot open encrypted archive') }).Count -gt 0)" }
$szAfter = $false; $szEnt = @(); $szCur = $null
foreach ($szLn in $szL) { if ($szLn -ceq '----------') { $szAfter = $true; continue }; if (-not $szAfter) { continue }; if ($szLn -cmatch '^Path = ') { if ($null -ne $szCur) { $szEnt += ,$szCur }; $szCur = @{ DirMark = $false; Size0 = $false; Pack0 = $false; Enc = $false; Aes = $false } } elseif ($null -ne $szCur) { if (($szLn -ceq 'Folder = +') -or ($szLn -cmatch '^Attributes = \S*D')) { $szCur.DirMark = $true }; if (($szLn -ceq 'Size = 0') -or ($szLn -ceq 'Size = ')) { $szCur.Size0 = $true }; if (($szLn -ceq 'Packed Size = 0') -or ($szLn -ceq 'Packed Size = ')) { $szCur.Pack0 = $true }; if ($szLn -ceq 'Encrypted = +') { $szCur.Enc = $true }; if ($szLn -cmatch '^Method = .*7zAES') { $szCur.Aes = $true } } }
if ($null -ne $szCur) { $szEnt += ,$szCur }
$szDirs = @($szEnt | Where-Object { $_.DirMark -and $_.Size0 -and $_.Pack0 })
$szFiles = @($szEnt | Where-Object { -not ($_.DirMark -and $_.Size0 -and $_.Pack0) })
$szOk = ($szTimeout -eq $false) -and ($szLRc -eq 0) -and ($szL -ccontains 'Type = 7z') -and ($szFiles.Count -ge 1) -and (@($szFiles | Where-Object { -not ($_.Enc -and $_.Aes) }).Count -eq 0)
"SEVENZIP_FOLDER_ENTRY_COUNT=$($szDirs.Count)"
if ($szOk) { "SEVENZIP_ALL_ENTRIES_7ZAES=True" } else { "STOP SEVENZIP_ALL_ENTRIES_7ZAES=False" }
"SEVENZIP_PROC_COUNT_AFTER=$(@(Get-Process -Name 7z -ErrorAction SilentlyContinue).Count)"
Remove-Variable szAt, szSw, szTimeout, szLRc, szL, szE, szP, szPsi, szOutT, szErrT, szAfter, szEnt, szCur, szLn, szDirs, szFiles, szOk -ErrorAction SilentlyContinue
```

  `SEVENZIP_ALL_ENTRIES_7ZAES=True` dışındaki her sonuç (`STOP
  SEVENZIP_LIST_TIMEOUT=True` ve `STOP SEVENZIP_LIST_START=FAIL` dahil):
  arşiv **açılmaz**, `E2_CARRIER_ENCRYPTED=False` → **DUR**. Klasör işareti
  taşıyıp boyutu sıfır olmayan bir girdi dosya sayılır; şifreli değilse
  sonuç `STOP`'tur. macOS/Linux'ta oluşturulmuş bir arşivde klasör
  yalnız küçük `d` ile (ör. `drwxr-xr-x`) basılabilir; bu durumda klasör
  tanınmaz, dosya sayılır ve sonuç `STOP`'tur (fail-closed; gönderen
  kuralı "klasörsüz" bunu önler). `SEVENZIP_FOLDER_ENTRY_COUNT` yalnız
  bilgidir; kapı değildir.
- **Açma.** Yalnız `SEVENZIP_ALL_ENTRIES_7ZAES=True` alındıktan sonra,
  aynı içerik oturumunda, parola **etkileşimli istem** ile girilerek
  (komut satırına `-p` yazılmaz):

```powershell
$xCaps = [Console]::CapsLock
"CAPS_LOCK=$xCaps attempt=<attempt>"
if ($xCaps -ne $true) { "STOP CAPS_LOCK_ON=False attempt=<attempt>" } else {
"EXTRACT_CALL_AT=$([DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz', [System.Globalization.CultureInfo]::InvariantCulture)) attempt=<attempt>"
$xRc = 'UNKNOWN'
try { $xPsi = New-Object System.Diagnostics.ProcessStartInfo; $xPsi.FileName = "<7z>"; $xPsi.Arguments = 'x "' + "<intake-dir>\transfer.7z" + '" "-o' + "<intake-dir>\x" + '"'; $xPsi.UseShellExecute = $false; $xP = [System.Diagnostics.Process]::Start($xPsi); $xP.WaitForExit(); $xRc = [string]$xP.ExitCode } catch { $xRc = 'UNKNOWN' }
if ($xRc -ceq 'UNKNOWN') { "STOP SEVENZIP_RC=UNKNOWN attempt=<attempt>" } else { "SEVENZIP_RC=$xRc attempt=<attempt>" }
"EXTRACT_RETURN_AT=$([DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz', [System.Globalization.CultureInfo]::InvariantCulture)) attempt=<attempt>"
$xDir = "<intake-dir>\x"; try { $xCnt = if (Test-Path -LiteralPath $xDir) { @(Get-ChildItem -LiteralPath $xDir -Recurse -Force -ErrorAction Stop).Count } else { 0 }; "X_ENTRY_COUNT=$xCnt attempt=<attempt>" } catch { "STOP X_ENTRY_COUNT=UNKNOWN attempt=<attempt>" }
}
Remove-Variable xCaps, xRc, xPsi, xP, xDir, xCnt -ErrorAction SilentlyContinue
```

  `<attempt>` ilk çalıştırmada `1`'dir. **Revizyon 3 (kullanıcı kararı
  K-R3-7):** blok önce Caps Lock'u okur ve `CAPS_LOCK=True/False
  attempt=<k>` yazar; `False` ise 7z'yi çağırmaz (`STOP
  CAPS_LOCK_ON=False`). Kit (`a6`/`a7`) Caps Lock'u bloktan **önce** de
  denetler; kapalıysa kayıt açmaz ve deneme harcanmaz. 7z, konsolu
  operatörle paylaşan bir süreç olarak çağrılır (parola istemi ekranda
  görünür; standart girdi konsoldur); `EXTRACT_CALL_AT`, `SEVENZIP_RC`,
  `EXTRACT_RETURN_AT` ve `X_ENTRY_COUNT=<n> attempt=<k>` satırları yazılır.
  Çıkış kodu okunamazsa `STOP SEVENZIP_RC=UNKNOWN`. `E2_CARRIER_ENCRYPTED=True` yalnız
  `SEVENZIP_ALL_ENTRIES_7ZAES=True` **ve** 7z'nin açmada parola
  istemesinin ekran gözlemiyle birlikte yazılır. Parola istenmeden açılan
  bir arşiv `E2_CARRIER_ENCRYPTED=False` → **DUR**.
  **Parola hatası gözlemi (revizyon 2; M-1).** Her denemeden sonra
  operatör 7z'nin ekran çıktısında `Wrong password` alt dizesinin
  görünüp görünmediğini okur ve evidence'a yalnız
  `SEVENZIP_WRONG_PASSWORD_SHOWN=True/False attempt=<k>` yazar. Mesaj
  metni kopyalanmaz; 7-Zip 26.04'te mesaj `ERROR: Data Error in encrypted
  file. Wrong password? : <ad>` biçimindedir ve `<ad>` (girdi adı)
  evidence'a **yazılmaz**. **Kit modunda** (revizyon 3) operatör, 7z
  döndükten sonra iki soruyu **E/H tuşuyla** cevaplar: parola istemi
  ("Enter password") göründü mü ve `Wrong password` göründü mü. Kit
  `SEVENZIP_PASSWORD_PROMPT_SHOWN=True/False attempt=<k>` ve
  `SEVENZIP_WRONG_PASSWORD_SHOWN=True/False attempt=<k>` satırlarını
  kendisi yazar; iki geçersiz tuş → `STOP …=UNKNOWN`. İstem görülmediyse
  `STOP E2_CARRIER_ENCRYPTED=False` → **DUR**.
  **Sonuçlar (revizyon 2; R-D-TRKBDPW; kullanıcı kararı K-R2-5; L-1).**
  - **Başarı** yalnız `SEVENZIP_RC=0` **ve** `X_ENTRY_COUNT=1` (tek PDF)
    birleşimidir. Kit modunda başarı ayrıca
    `SEVENZIP_PASSWORD_PROMPT_SHOWN=True` ve
    `SEVENZIP_WRONG_PASSWORD_SHOWN=False` ister ve
    `ATTEMPT_OUTCOME=SUCCESS` olarak kaydedilir; ek deneme koşulu da
    `SEVENZIP_PASSWORD_PROMPT_SHOWN=True` ister ve
    `ATTEMPT_OUTCOME=RETRY_ALLOWED` olarak kaydedilir (ek deneme `a7`).
  - **Tek ek deneme:** yalnız `<attempt>` = `1` iken `SEVENZIP_RC=2`,
    `SEVENZIP_WRONG_PASSWORD_SHOWN=True attempt=1` ve `X_ENTRY_COUNT=0`
    **birlikte** gözlenirse blok, aynı oturumda ve aynı kâğıttan elle
    yeniden yazılarak, `<attempt>` = `2` ile **bir kez daha** çalıştırılır
    (pilot boyunca toplam bir kez).
  - **Başka her birleşim DUR'dur** (Y5): ör. `SEVENZIP_RC=0` ile
    `X_ENTRY_COUNT` ≠ `1` (birden fazla girdi veya klasör);
    `SEVENZIP_RC` ≠ `0` olup ek deneme koşullarından biri eksik
    (`SEVENZIP_WRONG_PASSWORD_SHOWN=False`, `X_ENTRY_COUNT` ≠ `0`, `STOP
    X_ENTRY_COUNT=UNKNOWN` veya `2` dışında bir `SEVENZIP_RC`); ikinci
    denemede başarı birleşimi dışındaki her sonuç. Üçüncü deneme
    yoktur. Yöntem
  ölçümünün kalan sınırı §32/30'dadır. Açılan dosyaların adları kişisel veri taşıyabilir;
  bunlar komut satırına veya evidence'a yazılmaz. Orijinal belge, opak
  `<file-name>` adıyla case dizinine elle kopyalanır (§11.2/2).

Bu kontrol, §28.6/2'deki "kapsayıcı dışında kalan kopya" durumunun zincir
adım 27'ye kadar fark edilmemesini önler.

### 6.5 F — Saklama, silme ve pilot sonu

Kapı tablosu §23'tedir; uygulaması §28'dedir. F2 boşsa, F2 "Şifreli
arşivlensin" iken F3'ün beş unsurundan biri boşsa veya F4 "Şifreli
kapsayıcı yöntemi" değilse: **DUR — gerçek belge teslim alınmaz** (H4,
Y6).

### 6.6 İmza biçimi, bağlayıcı sürüm, saklama ve hash kaydı

Kaynak: form v5, "I. Onay", "G." bölüm notları ve Ek 1, Ek 2. YENİ.

1. **İmza biçimi.** Geçerli imza yalnız şunlardan biridir: (a) yazdırılıp
   ıslak imzayla imzalanmış ve **taranmış PDF**; (b) **e-imza** ile
   imzalanmış dosya. Word dosyasına yazılmış bir isim, yazıyla "imza" veya
   imza resmi yapıştırılmış bir `.docx` imza **sayılmaz**: **DUR** (Y1, Y7).
   Operatör imzanın varlığını ve biçimini denetler; imzanın kime ait
   olduğunu **doğrulamaz** (§32/23).
   - **UDF biçim kontrolü (yalnız biçim; kullanıcı kararı D17).** UYAP UDF
     biçimindeki e-imzalı her birim için, dosyanın içinde boş olmayan bir
     `sign.sgn` parçası ve bir `content.xml` parçası bulunduğu ölçülür
     (yalnız boolean basar, içerik basmaz):

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$udfOk = $false
try { $udfZip = [System.IO.Compression.ZipFile]::OpenRead("<form-file>"); try { $udfSign = $udfZip.GetEntry('sign.sgn'); $udfContent = $udfZip.GetEntry('content.xml'); $udfOk = ($null -ne $udfSign) -and ($udfSign.Length -gt 0) -and ($null -ne $udfContent) } finally { $udfZip.Dispose() } } catch { $udfOk = $false }
if ($udfOk) { "UDF_SIGN_PART_PRESENT=True" } else { "STOP UDF_SIGN_PART_PRESENT=False" }
Remove-Variable udfOk, udfZip, udfSign, udfContent -ErrorAction SilentlyContinue
```

     `UDF_SIGN_PART_PRESENT=True` imzanın **geçerli** olduğunu
     göstermez; yalnız biçim kontrolüdür. `STOP` → **DUR** (Y1, Y7).
   - **E-imza geçerliliği kapısı (adlandırılmış; kullanıcı kararları D17,
     D17a).** Gerçek dosyadan önce, e-imzalı **her** birim (A–F + I, G,
     Ek 2 ve e-imzalıysa Ek 1) **bir kez**, insan tarafından UYAP
     editöründe açılır ve editörün gösterdiği imza durumu evidence'a
     `UDF_SIGNATURE_VALID=True/False unit=<birim> seq=<n>` olarak yazılır.
     Editör sertifika durumunu sorgulamak için ağa çıkabilir: bu bir dış ağ
     işlemidir, içerik penceresinin **dışında** ve form dosyası üzerinde
     yapılır ve **ayrı `REAL_ACTION_APPROVED`** ister. Bu işlemi hiçbir AI
     asistanı yürütmez. `False`, ölçülmemiş veya belirsiz: **DUR** (Y20).
     Kayıt, editörün kendi gösterimidir; sertifika zinciri ve iptal durumu
     bu runbook tarafından bağımsız doğrulanmaz (§32/23).
2. **İmzalı birimler.** (i) **A–F + I** (form v5 "I. Onay (A–F bölümleri
   için)"; imzalayan protokol inceleyicisi), (ii) **G bölümü** (G10
   ad/tarih, G11 imza; imzalayan dosya avukatı), (iii) **Ek 2** (operatör
   ve dosya avukatı imzaları), (iv) **Ek 1** (dosya avukatının dosyaya
   özgü doldurduğu aydınlatma metni). Her biri ayrı bir dosya olabilir;
   aynı dosyada ise gereken bütün imzalar bulunmalıdır.
3. **Bağlayıcı sürüm.** Her birim için **en son imzalı sürüm** geçerlidir
   (form v5, I bölümü notu). Yeni bir imzalı sürüm geldiğinde önceki sürümün
   hash kaydı silinmez; yeni sürümün hash'i ayrı satır olarak eklenir ve
   bağlayıcı olarak işaretlenir. A–F yeni sürümü bir kapının sonucunu
   değiştiriyorsa ilgili kapı yeniden değerlendirilir; zincir o kapıdan
   sonraki bir adımdaysa: **DUR**, kullanıcı kararı. İçerik penceresi
   içinde (zincir adım 5'ten sonra) herhangi bir birimin yeni bir
   e-imzalı sürümü gelirse: **DUR** (Y20) — o sürümün
   `UDF_SIGNATURE_VALID` kaydı için gereken UYAP editörü doğrulaması bir
   ağ işlemidir ve yalnız içerik penceresinin **dışında** yapılabilir
   (madde 1; §21/3).
4. **Tarih sırası.** G10 tarihi, bağlayıcı A–F sürümünün I3 tarihinden
   önce olamaz (form v5'in bağlayıcı sürümünde I3 = 09/10/2026). Operatör
   iki tarihi karşılaştırır; ek olarak dosya avukatının G
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
     `ATT2` …). Form v5'te `ATT1` = Ek 1 (dosya avukatının doldurduğu
     aydınlatma metni), `ATT2` = Ek 2 (operatör ve dosya avukatınca
     imzalı taahhüt). `seq` her birimde `1`'den başlar ve her yeni imzalı
     sürümde bir artar. Önceki satırlar silinmez.
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
   (ör. "A1 evet, B4 ayrı kişiler, B5 Ek 2, C1 Ek 1, D3 form yeterli,
   E1 kapsayıcı, E2 uzaktan şifreli aktarım, E4 pdftotext, F4 kapsayıcı
   yöntemi, F2 silme, F1 24 saat, G9 evet").
9. §0'daki form v5 hash'i, zincir adım 2'de ölçülen
   `FORM_HASH unit=AF seq=1` satırının **beklenen değeridir**: ölçülen
   hash §0'daki değerle birebir aynı değilse **DUR** (H16). Sonraki
   imzalı sürümler madde 3'e göre ayrı `seq` satırlarıyla kayda geçer.

### 6.7 I — Protokol onayı (I0) ve imza alanları

Kaynak: form v5, "I. Onay". YENİ (remediasyon turu 1). I0'ı protokol
inceleyicisi cevaplar; onay yalnız A–F protokolüne ilişkindir ve pilot
içi hiçbir kararın yerine geçmez (§4.1).

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| I0 | "Hukuki protokol bakımından kabul ediyorum" işaretli | Boş; iki kutu birden; "Şu değişiklik/koşullarla kabul ediyorum" (değişiklik veya koşul runbook'a işlenip yeniden incelenene kadar; §6.1) (Y1) |
| I1 | Ekler işaretli (form v5'te "Ek 1" ve "Ek 2") veya "Ek yok"; her durumda §6.6/5 ile çelişkisiz | Boş; çelişki (Y1) |
| I2–I4 | Ad/unvan ve tarih dolu; imza §6.6/1 biçiminde | Boş; imza biçimi geçersiz (Y1) |

---

## 7. Müvekkilin bilgilendirilmesi (Form C)

Temel §7'nin (dış aktarım için yazılı rıza, P2) yerine geçer: veri yurt
dışına ve bir model sağlayıcısına gitmediği için Temel §7.1/2'deki aktarım
kategorileri bu yolda **yoktur**. Avukatın DRAFT-4 6.3 cevabı aydınlatmayı
zorunlu, açık rızayı ise yalnız gerçekten rızaya dayanan bir faaliyet
varsa gerekli sayar (form C1–C2 notları).

| Soru | Kabul edilen cevap | DUR |
|---|---|---|
| C1 | "Hazırlandı" (form v5: Ek 1 "Yerel Pilot Aydınlatma Metni Taslağı") — veya — "Pilot öncesi hazırlanacak" **ve** dosya avukatı Ek 1'i dosyaya özgü bilgilerle doldurmuş (`ATT1`) ve gerçek belge teslim alınmadan önce müvekkile verdiğini yazılı olarak teyit etmiş (teyidin SHA-256'sı evidence'a) | Boş; Ek 1 doldurulmamış; teslimden önce verildiğine dair yazılı teyit yok |
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
v3'ün G9 (tarih biçimi) sorusu ve G10/G11 ayrı imzası eklendi (form v5'te
aynen; v5'te G bölümünü dosya avukatı doldurur ve imzalar).

Bu eleme **gerçek veri teslim alınmadan önce**, dosya avukatının belgeye bakarak
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

Başka hiçbir belge bu dizine konmaz. `<repo-root>` kapsayıcıdaki klon
olduğu için bu dizin de kapsayıcı içindedir (§4.4/3).

### 10.2 Repo dışında kalanlar

Kaynak: Temel L821–L846. **Sapmalar:** `<external-root>` tek çocuklu
(revizyon; kullanıcı kararı D2); `<restricted-dir>` kapsayıcı içindeki
`<pilot-root>` altına taşındı; probe/inference evidence dizinleri ve
`<restricted-dir>` içindeki maskeleme ve engel dosyaları çıkarıldı.

- Avukat formu ve ekleri, avukatın yazılı kararları ve kör bağımsız
  hesabı: repo dışında, avukatın kontrolünde.
- **`<external-root>`** — repo ve kapsayıcı dışındaki, yalnız bu pilot
  için ayrılmış kök dizin. Bulut senkronizasyonlu bir klasörde
  **değildir**, sürücü kökü **değildir**, repo ağacının içinde veya repo
  kökünün atası **değildir**, `<container-root>` ile örtüşmez. Doğrudan
  altında **yalnız** `<evidence-dir>` bulunur (§13.8). Kapsayıcı imhasından
  sonra da kalır.
- **`<restricted-dir>`** — dava-türevi içerik dizini; kapsayıcı içinde,
  `<pilot-root>` altındadır. Erişimi avukat ve operatörle sınırlıdır ve
  §28'deki veri akıbeti kararına **tabidir**. Bu pilotta **yalnız**
  deadline raporunu (§19) taşır. İzinli dosya adı intake'ten önce
  sabitlenir ve envanter mekanik olarak denetlenir (§10.5).
- **Kapsayıcı dışında kalan metadata.** PostgreSQL kümesindeki journal,
  assignment ve security-event satırları (yalnız opak kimlik ve hash;
  §10.3, §28.4, Form F6) ve `<evidence-dir>` kapsayıcı dışındadır ve
  gerçek içerik taşımaz.
- **`<evidence-dir>`**: **yalnız metadata** (§26). Gerçek tarih, sayfa
  numarası, alıntı, rapor metni veya herhangi bir gerçek içerik bu dizine
  girmez.
- **`<archive-dir>`** — yalnız eksiksiz bir şifreli arşiv kararı varsa
  kullanılır; `<external-root>`'un dışındadır ve kendi kapısından geçer
  (§28.5).
- Gerçek belge baytlarının veya metninin kapsayıcı dışında (Temp kökü,
  indirme dizini, evidence dizini dahil) **hiçbir kopyası alınmaz**.
  `<intake-dir>` içindeki aktarım dosyası ve açılmış içerik ile
  `<container-temp>` içindeki dosyalar kaçınılmaz geçici kopyalardır;
  kapsayıcı içindedir ve Form F1 süresine tabidir (§28.6).

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
L1072–L1073'te yoktur; davranışı değiştirmez); (2) uzaktan şifreli
aktarıma, (6) `pdftotext` komutuna bağlandı (revizyon, §34).

1. Ön kontrol: `<case-root>` **mevcut değildir**; varsa **DUR** (H29).
   Ebeveyni `<repo-root>\data\cases` §13.8 yol kapısından geçmiştir ve bu
   oturumda `PATH_OK=external-root-contract`, `PATH_OK=container-root`,
   `PATH_OK=pilot-root-contract`, `SYSTEM_TEMP_MATCH=True`,
   `TEMP_IN_CONTAINER=True` ve
   `PILOT_ACL_PRINCIPALS_OK=True` alınmıştır; alınmadıysa intake
   başlatılmaz, **DUR** (H52, Y17).
2. Belge Form **E2**'deki kanalla (uzaktan şifreli aktarım; §6.4), ancak
   §6.6/7 (a) form hash yeniden ölçümü (`FORM_HASH_RECHECK … match=True`)
   ve §6.4 taşıyıcı kontrolü geçtikten sonra teslim alınır. Orijinal belge
   `<intake-dir>\x` altından opak `<file-name>` adıyla case dizinine elle
   kopyalanır; kopyalama kapsayıcı içinde kalır. `<case-root>` altında
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
if ([regex]::Matches($txt, '\S').Count -ge 1) { Write-Output "TEXT_VISIBLE=OK" } else { Write-Output "STOP TEXT_VISIBLE=EMPTY" }
Remove-Variable txt -ErrorAction SilentlyContinue
```

   Beklenen: **`TEXT_LENGTH=OK`** ve **`TEXT_VISIBLE=OK`**. Başka her
   çıktı **DUR**'dur (H43). Üçüncü satır revizyon 2'de eklendi
   (R-D-IMGPDF; kullanıcı kararı K-R2-8): `pdftotext` metin katmanı
   olmayan (görüntü) bir sayfa için yalnız sayfa sonu karakteri (`\f`)
   üretir ve uzunluk kontrolü bunu geçer; .NET `\S` sayfa sonu, boşluk,
   satır sonu ve Unicode boşluk karakterlerini saymaz, bu yüzden metin
   katmanı hiç olmayan bir PDF `STOP TEXT_VISIBLE=EMPTY` verir. Eşik
   (en az 1 görünür karakter) yalnız **tamamen** boş metin katmanını
   yakalar; kısmen metinli bir PDF §11.3 (b) tarih token'ı kontrolünde
   ve `manual-fact` M-07'de (alıntı bulunamadı) durur.

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
   araçla, Poppler `pdftotext` ile yapılır (§4.2/3). Önce §4.4/6
   `TOOL_MANIFEST_MATCH=True` alınır ve `extracted` dizini oluşturulmuş
   olmalıdır. Komut (seçenekler sabittir; `-layout` kullanılmaz; çıktı
   BOM'suz UTF-8 ve LF satır sonudur; §1.6/3 delta provasında sentetik bir
   PDF'le doğrulanır):

```powershell
& "<pdftotext>" -enc UTF-8 -eol unix "<case-root>\documents\<document-id>\<file-name>" "<case-root>\documents\<document-id>\extracted\<document-id>.txt"
"PDFTOTEXT_RC=$LASTEXITCODE"
```

   Beklenen: `PDFTOTEXT_RC=0` ve ardından (4)'teki `TEXT_LENGTH=OK` ve
   `TEXT_VISIBLE=OK`.
   Başka her sonuç **DUR**'dur (Y5). `pdftotext` sayfa sınırlarını sayfa
   sonu karakteriyle işaretler; ayrı bir görüntüleyici kullanılmaz
   (kullanıcı kararı D7): sayfa numarası bu çıktıdan belirlenir ve dosya
   avukatı orijinalle kendi kopyası üzerinden karşılaştırır (§11.4,
   §14.3). Metin katmanı olmayan bir PDF için OCR yoktur: **DUR**.
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
(`docs/operations/local-postgresql-iam-adoption.md` §G.1, §G.2). OWNER
rolü bu runbook'ta **kullanılmaz**; bir yedek veya bakım için gerekirse
(ör. provadaki `pg_dump`) **tek rol, tek oturum** kuralıyla, ADMIN ve APP
oturumlarından ayrı bir oturumda kullanılır (prova ajan notu A-DEV-01).

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

Komutlar `<repo-root>`'ta, yani kapsayıcıdaki klonda (§4.4/3) çalıştırılır.
Beklenen: branch `claude-dev`; HEAD, yürütme yetkisinde kullanıcının
onayladığı commit; çalışma ağacı temiz; ignored görünümde intake'ten önce
**hiçbir girdi**, intake'ten sonra **yalnız** `!! data/cases/<case-id>/`; son
komut hatasız (runbook tracked). Aksi **DUR** (H30).

### 13.3 Yorumlayıcı ve runtime paritesi

Kaynak: Temel L1376–L1381 ve L1559–L1566 (yalnız runtime kısmı).
**Sapmalar:** harness/monitor/probe paritesi çıkarıldı; `pip check` komutu
açıkça yazıldı; paket kümesi karşılaştırma bloğu eklendi (revizyon, §34).

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
paketi ve `pip`, toplam 42 satır) karşı mekanik olarak karşılaştırılır.
Referans, `13f19d0` provasında kullanılan Adım 9 referans dosyasının
(SHA-256 `f297266592fd5f67e19a25a506e7018416b2681642285ba78207276761f29f38`,
42 satır) satırlarıdır ve aşağıya **birebir gömülmüştür**; runbook bir
geçici dizindeki dosyaya bağlı değildir (R-F-PKG; kullanıcı kararı D16).
Karşılaştırma boş satırları atar, iki kümeyi ordinal (büyük/küçük harf
duyarlı) sıralar ve birebir karşılaştırır; yalnız sonuç satırı basar
(`13f19d0` provası 0.7'de aynı yöntem `FREEZE_DIFF_COUNT=0` verdi):

```powershell
$pkgRef = [string[]]@('annotated-doc==0.0.5', 'annotated-types==0.8.0', 'anthropic==1.2.0', 'anyio==4.15.0', 'attrs==26.1.0', 'Authlib==1.8.0', 'certifi==2026.7.22', 'cffi==2.1.1', 'click==8.5.0', 'cryptography==50.0.1', 'docstring_parser==0.18.0', 'fastapi==0.141.1', 'h11==0.16.0', 'httpcore==1.0.9', 'httpcore2==2.12.0', 'httpx==0.28.1', 'httpx2==2.12.0', 'idna==3.19', 'Jinja2==3.1.6', 'jiter==0.16.0', 'joserfc==1.7.5', 'jsonschema==4.26.0', 'jsonschema-specifications==2025.9.1', 'MarkupSafe==3.0.3', 'pip==26.0.1', 'psycopg==3.3.5', 'psycopg-binary==3.3.5', 'psycopg-pool==3.3.1', 'pycparser==3.0', 'pydantic==2.13.5', 'pydantic_core==2.46.5', 'python-dotenv==1.2.3', 'python-multipart==0.0.32', 'referencing==0.37.0', 'rpds-py==2026.6.3', 'sniffio==1.3.1', 'starlette==1.6.0', 'truststore==0.10.4', 'typing-inspection==0.4.4', 'typing_extensions==4.16.0', 'tzdata==2026.3', 'uvicorn==0.52.4')
$pkgCur = [string[]]@(& "<python>" -m pip freeze --all | Where-Object { $_ -ne '' })
$pkgRc = $LASTEXITCODE
[Array]::Sort($pkgRef, [System.StringComparer]::Ordinal); [Array]::Sort($pkgCur, [System.StringComparer]::Ordinal)
if (($pkgRc -eq 0) -and ($pkgRef.Count -eq 42) -and (($pkgRef -join "`n") -ceq ($pkgCur -join "`n"))) { "RUNTIME_PACKAGE_SET=MATCH" } else { "STOP RUNTIME_PACKAGE_SET=MISMATCH" }
Remove-Variable pkgRef, pkgCur, pkgRc -ErrorAction SilentlyContinue
```

Beklenen: `RUNTIME_PACKAGE_SET=MATCH`. Uyuşmazlık: **DUR** (H31).

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
   - Bu çağırma biçimi `13f19d0` provasında (§0) statik olarak kontrol
     edildi ve pilot kümesinde sentetik case'lerle canlı olarak kullanıldı;
     `FAIL` dalı da gözlendi. Gerçek dosyada yine her çağrının çıktısı bu
     sözleşmeyle değerlendirilir.

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
L1512–L1513; **sapma:** desene `CLAUDE.*` eklendi — içerik oturumunun
Claude Code'dan veya başka bir ajan oturumundan türemediğinin sinyali,
kullanıcı kararları K6/D11; eşleşme → **DUR**, Y18):

```powershell
$pattern = '^(ANTHROPIC_.*|CLAUDE.*|.*PROXY.*|SSL_.*|.*CA_BUNDLE.*|.*CA_CERTS.*|SSLKEYLOGFILE|PYTHONHTTPSVERIFY|PG.*)$'
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
yalnız `<evidence-dir>`'e indirildi ve korunan listeye `<container-root>`
eklendi (revizyon; kullanıcı kararı D2); probe/inference satırları
çıkarıldı; Temel L1664'teki `Test-PilotExternalRoot` çağrısı buna göre
yeniden yazıldı; kapsayıcı kapıları (`container-root`, `pilot-root`,
`Test-PilotPilotRoot`, kapsayıcı dosyası) ve `pdftotext`/`7z` dosya
kapıları eklendi (revizyon, §34). Temelden alınan fonksiyon tanımları
**birebirdir**.

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

Repo dışı dizinler (**sapma:** yalnız bir çocuk; `<restricted-dir>`
kapsayıcı içindedir ve aşağıdaki kapsayıcı kapılarından geçer):

```powershell
Test-PilotPath 'external-root' "<external-root>" ''
Test-PilotPath 'evidence-dir' "<evidence-dir>" "<external-root>"
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
atası **değildir**; `<container-root>`, `<case-root>`, `<system-temp>`
(`<system-temp-user>`, `<system-temp-windows>`), `<container-temp>`,
`<python-runtime-root>` ve `<pg-bin-dir>` ile örtüşmez. Doğrudan altında
**tam olarak** `<evidence-dir>` yaprak adı bulunur: eksik `<evidence-dir>`
veya başka her öğe **DUR**'dur (H52). Kapı her içerik oturumunun başında
ve her durumda intake'ten **önce**, §4.4/5 sistem Temp kaydından sonra
çalıştırılır. Fonksiyon Temel L1663 birebir; çağrı (**Temel L1664'ten
sapma:** çocuk listesi tek elemanlı; korunan listeye `<container-root>`
eklendi; **remediasyon turu 1:** `GetTempPath()` yerine `<system-temp>`
ve `<container-temp>` — TEMP yönlendirmesinden sonra `GetTempPath()`
sistem Temp'ini göstermez (H-1); fonksiyonun alt-küme kontrolünün
ardından `13f19d0`'ın §28.3.2'deki **tam eşitlik** karşılaştırması
eklendi (H-2)):

```powershell
function Test-PilotExternalRoot([string]$ext, [string]$repo, [string[]]$children, [string[]]$protected) { $ErrorActionPreference = 'Stop'; try { if (-not (Test-PilotResolved $ext) -or -not (Test-PilotResolved $repo) -or ($children.Count -lt 1)) { return $false }; $e = $ext.TrimEnd('\'); if ($e -eq [System.IO.Path]::GetPathRoot($ext).TrimEnd('\')) { return $false }; if (-not (Test-Path -LiteralPath $e -PathType Container) -or -not (Test-PilotNoReparse $e) -or (Test-PilotOverlap $e $repo)) { return $false }; foreach ($p in $protected) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $e $p)) { return $false } }; $leaves = @(); foreach ($c in $children) { if (-not (Test-PilotResolved $c) -or ([System.IO.Path]::GetDirectoryName($c.TrimEnd('\')) -ne $e)) { return $false }; $leaves += [System.IO.Path]::GetFileName($c.TrimEnd('\')) }; if (@($leaves | Sort-Object -Unique).Count -ne $leaves.Count) { return $false }; $names = @(Get-ChildItem -LiteralPath $e -Force -ErrorAction Stop | ForEach-Object { $_.Name }); return (@($names | Where-Object { $leaves -cnotcontains $_ }).Count -eq 0) } catch { return $false } }
$extOk = Test-PilotExternalRoot "<external-root>" "<repo-root>" @("<evidence-dir>") @("<container-root>", "<case-root>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")
if ($extOk -eq $true) { try { $extNow = [string[]]@(Get-ChildItem -LiteralPath "<external-root>" -Force -ErrorAction Stop | ForEach-Object { $_.Name }); $extExpected = [string[]]@([System.IO.Path]::GetFileName(("<evidence-dir>").TrimEnd('\'))); [Array]::Sort($extNow, [System.StringComparer]::Ordinal); $extOk = (($extNow -join '|') -ceq ($extExpected -join '|')) } catch { $extOk = $false } }
if ($extOk -eq $true) { "PATH_OK=external-root-contract" } else { "STOP PATH_FAIL=external-root-contract" }
Remove-Variable extOk, extNow, extExpected -ErrorAction SilentlyContinue
```

**Kapsayıcı kapıları (YENİ; §4.4; kullanıcı kararları K4, D2, D3).**
`<container-root>` bir sürücü harfi köküdür (`X:\` biçiminde), sistem
sürücüsü değildir, NTFS biçimlidir ve reparse point değildir. `<pilot-root>`
onun doğrudan altındadır; `<repo-root>`, `<restricted-dir>`,
`<container-temp>` ve `<intake-dir>` `<pilot-root>`'un doğrudan altındadır
ve `<pilot-root>`'un doğrudan altında bunlardan başka öğe bulunmaz. Kapı
zincir adım 4'te, her içerik oturumunun başında ve her silme gününde
çalıştırılır; yalnız ad ve `PATH_OK` / `STOP PATH_FAIL` basar:

```powershell
$crOk = $false
try { $cr = "<container-root>"; $crOk = ($cr -cmatch '^[A-Z]:\\\z') -and ($cr -ne ($env:SystemDrive + '\')) -and (Test-Path -LiteralPath $cr -PathType Container) -and ((New-Object System.IO.DriveInfo $cr).DriveFormat -ceq 'NTFS') -and (-not ((Get-Item -LiteralPath $cr -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) } catch { $crOk = $false }
if ($crOk) { "PATH_OK=container-root" } else { "STOP PATH_FAIL=container-root" }
Remove-Variable cr, crOk -ErrorAction SilentlyContinue
Test-PilotPath 'pilot-root' "<pilot-root>" "<container-root>"
Test-PilotPath 'repo-root-parent' "<repo-root>" "<pilot-root>"
Test-PilotPath 'restricted-dir' "<restricted-dir>" "<pilot-root>"
Test-PilotPath 'container-temp' "<container-temp>" "<pilot-root>"
Test-PilotPath 'intake-dir' "<intake-dir>" "<pilot-root>"
function Test-PilotPilotRoot([string]$pilot, [string]$cRoot, [string[]]$children) { $ErrorActionPreference = 'Stop'; try { if (-not (Test-PilotResolved $pilot) -or -not (Test-PilotResolved $cRoot) -or ($children.Count -lt 1)) { return $false }; $p = $pilot.TrimEnd('\'); $c = $cRoot.TrimEnd('\'); if ($c -ne [System.IO.Path]::GetPathRoot($cRoot).TrimEnd('\')) { return $false }; if ([System.IO.Path]::GetDirectoryName($p).TrimEnd('\') -ne $c) { return $false }; if (-not (Test-Path -LiteralPath $p -PathType Container) -or -not (Test-PilotNoReparse $p)) { return $false }; $leaves = @(); foreach ($ch in $children) { if (-not (Test-PilotResolved $ch) -or ([System.IO.Path]::GetDirectoryName($ch.TrimEnd('\')) -ne $p)) { return $false }; $leaves += [System.IO.Path]::GetFileName($ch.TrimEnd('\')) }; if (@($leaves | Sort-Object -Unique).Count -ne $leaves.Count) { return $false }; $names = @(Get-ChildItem -LiteralPath $p -Force -ErrorAction Stop | ForEach-Object { $_.Name }); return (@($names | Where-Object { $leaves -cnotcontains $_ }).Count -eq 0) } catch { return $false } }
$pilotOk = Test-PilotPilotRoot "<pilot-root>" "<container-root>" @("<repo-root>", "<restricted-dir>", "<container-temp>", "<intake-dir>")
if ($pilotOk -eq $true) { "PATH_OK=pilot-root-contract" } else { "STOP PATH_FAIL=pilot-root-contract" }
Remove-Variable pilotOk -ErrorAction SilentlyContinue
```

`<container-root>` için `Get-Item` sürücü kökünü döndürür; davranış
§1.6/3 delta provasında doğrulanır. `Test-PilotPilotRoot` ortak
yardımcılardan **sonra** tanımlanır ve çağrılır.

**Kapsayıcı dosyası (YENİ; §4.4/2, §28.3.3; remediasyon turu 1: iki
aşamalı kapı, M-1).** Kapı iki aşamalıdır ve aşamalar ayrı ayrı
kaydedilir. Korunan liste her iki aşamada aynıdır.

**Aşama (i) — oluşturmadan önce, ebeveyn dizin kapısı.** `<container-file>`
ve ebeveyn dizini çözümlüdür; ebeveyn mevcut bir dizindir, kendisi ve
sürücü köküne kadar üst dizinleri reparse point değildir; yol korunan
dizinlerle örtüşmez; `<container-file>` henüz **mevcut değildir**:

```powershell
$cfPreOk = $false
try { $cf = "<container-file>"; $cfDir = [System.IO.Path]::GetDirectoryName($cf); $cfPreOk = (Test-PilotResolved $cf) -and (Test-PilotResolved $cfDir) -and (Test-Path -LiteralPath $cfDir -PathType Container) -and (Test-PilotNoReparse $cfDir) -and (-not (Test-Path -LiteralPath $cf)); foreach ($p in @("<source-repo-root>", "<repo-root>", "<external-root>", "<container-root>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $cf $p)) { $cfPreOk = $false } } } catch { $cfPreOk = $false }
if ($cfPreOk) { "PATH_OK=container-file-parent" } else { "STOP PATH_FAIL=container-file-parent" }
Remove-Variable cf, cfDir, cfPreOk, p -ErrorAction SilentlyContinue
```

Kapsayıcı yalnız `PATH_OK=container-file-parent` alındıktan sonra
oluşturulur; `STOP` → oluşturma yapılmaz, **DUR** (H52). Bulut
senkronizasyonlu bir klasör (ör. OneDrive) altında olmaması operatörün
beyanıdır ve evidence'a `CONTAINER_FILE_NOT_CLOUD_SYNCED=True` olarak
yazılır.

**Aşama (ii) — oluşturduktan sonra (bağlıyken de), yaprak-dosya kapısı.**
`<container-file>` bir yaprak dosyadır, reparse point içermez ve korunan
dizinlerle örtüşmez:

```powershell
$cfOk = $false
try { $cf = "<container-file>"; $cfOk = (Test-PilotLeafFile $cf); foreach ($p in @("<source-repo-root>", "<repo-root>", "<external-root>", "<container-root>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $cf $p)) { $cfOk = $false } } } catch { $cfOk = $false }
if ($cfOk) { "PATH_OK=container-file" } else { "STOP PATH_FAIL=container-file" }
Remove-Variable cf, cfOk, p -ErrorAction SilentlyContinue
```

Aşama (ii) `STOP` verirse kapsayıcı kullanılmaz ve yeniden
oluşturulmaz: **DUR** (H52), kullanıcı kararı.

Dosya yolları (Temel L1680–L1682 birebir; **sapma:** `pdftotext` ve `7z`
satırları eklendi):

```powershell
function Test-PilotExe([string]$name, [string]$path, [string]$root, [string]$leaf, [bool]$directChild) { $ok = [System.IO.Path]::IsPathRooted($root) -and ([System.IO.Path]::GetFullPath($root).TrimEnd('\') -eq $root.TrimEnd('\')) -and (Test-Path -LiteralPath $root -PathType Container) -and (Test-PilotNoReparse $root) -and (Test-PilotLeafFile $path) -and ([System.IO.Path]::GetFileName($path) -ceq $leaf); if ($ok) { $r = $root.TrimEnd('\'); if ($directChild) { $ok = ([System.IO.Path]::GetDirectoryName($path) -eq $r) } else { $ok = $path.ToLowerInvariant().StartsWith(($r + '\').ToLowerInvariant()) } }; if ($ok) { "PATH_OK=$name" } else { "STOP PATH_FAIL=$name" } }
Test-PilotExe 'python' "<python>" "<python-runtime-root>" 'python.exe' $false
Test-PilotExe 'psql' "<psql>" "<pg-bin-dir>" 'psql.exe' $true
Test-PilotExe 'pdftotext' "<pdftotext>" "<poppler-bin-dir>" 'pdftotext.exe' $true
Test-PilotExe '7z' "<7z>" "<sevenzip-root>" '7z.exe' $true
```

Bu kapı geçmeden `<python>`, `<psql>`, `<pdftotext>` veya `<7z>` ile
**hiçbir komut çalıştırılmaz**.

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
| `ManualFactPendingExistsError` | M-09 | PL/PC | Yok | **DUR**. Apply'da mesaj son journal satırının `id` ve `state` değerini gösterir (`ui/services/manual_fact_mutation_facade.py:504-515`); **preview**'da aynı sınıf ve kural kodu döner ama mesaj journal `id`/`state` taşımaz (`13f19d0` provası, R-F-M09MSG). İlk apply'da beklenmez; tamamlanmış bir apply'dan sonra aynı komut bunu verir (yeniden çalıştırılmaz) |
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

Salt-okunur kontrol bloğu (YENİ; R-F-DLB; `13f19d0` provasındaki
`dl_check.py` ile aynı alanları okur; yalnız sabit boolean satırları basar,
tarih basmaz; §1.6/3 delta provasında doğrulanır):

```powershell
$dl = $null
try { $dlFiles = @(Get-ChildItem -LiteralPath "<case-root>\deadlines" -Filter '*.json.pending' -File -Force -ErrorAction Stop); if ($dlFiles.Count -eq 1) { $dl = (New-Object System.Text.UTF8Encoding($false, $true)).GetString([System.IO.File]::ReadAllBytes($dlFiles[0].FullName)) | ConvertFrom-Json } } catch { $dl = $null }
$dlRecs = @(); if ($null -ne $dl) { $dlRecs = @($dl.deadlines) }
"DL_SINGLE_PENDING_FILE=$($null -ne $dl)"
"DL_SINGLE_RECORD=$($dlRecs.Count -eq 1)"
if ($dlRecs.Count -eq 1) { $x = $dlRecs[0]; "DL_CALCULATION_STATE_CALCULATED=$([string]$x.calculation_state -ceq 'calculated')"; "DL_EXPIRY_NOT_EVALUATED=$([string]$x.expiry_state -ceq 'not_evaluated')"; "DL_ANCHOR_VERIFIED=$([string]$x.anchor_verification_state -ceq 'verified')"; "DL_STOPPING_NONE=$([string]$x.stopping_event_status -ceq 'none')"; "DL_ATTESTATION_REF_PRESENT=$(([string]$x.stopping_event_attestation_ref).Trim().Length -gt 0)"; "DL_REQUIRES_HUMAN_REVIEW=$($x.requires_human_review -eq $true)"; "DL_CALCULATED_DEADLINE_PRESENT=$($null -ne $x.calculated_deadline)" }
Remove-Variable dl, dlFiles, dlRecs, x -ErrorAction SilentlyContinue
```

Beklenen: bütün satırlar `True`. Biri `False` veya satır eksikse: **DUR**
(H19, H20, H21). Evidence'a yalnız bu boolean satırlar yazılır.

**Bu blok yalnız approval'dan önceki kapıdır (revizyon 2;
R-D-E18PENDING).** Approval pending dosyasını **silmez**: pending içerik
değiştirilmeden canonical'a kopyalanır ve pending yerinde kalır
(`src/deadline_approval.py` L46, L50; kopya `atomic_copy_file`, L283–L342;
dosyadaki iki `unlink` çağrısı, L1408 ve L1476, yalnız hata dalında
canonical'ı geri alır). Bu yüzden approval'dan sonra blok yine `True`
satırları basar; bu bir kapı sonucu **değildir** ve blok approval'dan
sonra çalıştırılmaz. Kalan pending dosyaları §28.2 case manifestine girer
ve §28.3.1 case dizini silmesiyle imha edilir.

### 18.3 Pending tarihin sabitlenmiş hesapla karşılaştırılması

1. Pending'deki `calculated_deadline`, avukatın §17.2'de sabitlenmiş
   hesabındaki son günle **birebir** karşılaştırılır; önce sabitlenmiş
   kaydın SHA-256'sı yeniden ölçülür ve evidence'taki değerle aynı olduğu
   doğrulanır. Tarih yalnız içerik oturumunun **ekranında** okunur
   (aşağıdaki satır); evidence'a, bir dosyaya veya bir AI oturumuna
   yazılmaz (§4.2/8):

```powershell
$dlFiles = @(Get-ChildItem -LiteralPath "<case-root>\deadlines" -Filter '*.json.pending' -File -Force); if ($dlFiles.Count -eq 1) { "PENDING_CALCULATED_DEADLINE=$(@(((New-Object System.Text.UTF8Encoding($false, $true)).GetString([System.IO.File]::ReadAllBytes($dlFiles[0].FullName)) | ConvertFrom-Json).deadlines)[0].calculated_deadline)" } else { "STOP DL_SINGLE_PENDING_FILE=False" }
Remove-Variable dlFiles -ErrorAction SilentlyContinue
```
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

Approval'dan sonra `deadlines\deadline.json` ile kardeş `*.json.pending`
aynı baytları taşır; bu eşitlik yalnız deadline katmanı içindir. Fact ve
timeline pending'leri de yerinde kalır, ancak verification ve promotion
sonrasında canonical'dan **farklı** baytlar taşırlar (revizyon 2;
R-D-E18PENDING; delta prova incelemesi O-2).

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
| `ANTHROPIC_*`, `CLAUDE*`, proxy, TLS ve `PG*` ad taraması | §13.6 (b), her içerik oturumu, her `manual-fact` çağrısı öncesi ve kapanış | Üç kapsamda **0** |
| Pilot için API anahtarı oluşturulmadı | Kullanıcı beyanı, evidence'a `PILOT_API_KEY_CREATED=False` | `False` |
| `generation.fact_extraction` hiç çalışmadı | §14.7 SQL, kapanışta | `0` |
| `manual-fact` ağ bayrağı tanımaz | `ui/cli_mutate.py:525-546` (kaynak); `13f19d0` provasında `--with-agent` ve `--allow-network` ile çıkış `2` gözlendi (N-06, N-07) | Kaynakta bayrak yok |
| Manuel motor ağ/LLM kütüphanesi import etmez | `src/manual_fact_entry_engine.py:10-15, 52-66` (kaynak) | Kaynakta import yok |
| Pilot toplam dış ağ işlemi | §30/10 | Aşağıdaki beş sınıf: (1) runbook komutları — **sıfır**; (2) dosya aktarımı — zincir içindeki tek dosya aktarımı, E2 aktarım dosyasının içeri yönlü alınması (`E2_INBOUND_TRANSFER_RECEIVED=True`); (3) ön-pencere insan ağ işlemleri — `PRE_PILOT_NETWORK_ACTION` satırları; (4) karar kanalı — sayılı, hash'li ve içeriksiz; (5) sesli görüşme — cihaz dışı, `VOICE_CALL` satırları; gerçek içerik cihazdan çıkmaz |

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

**Ağ işlemlerinin tam listesi (revizyon; form v5 E2/E4 ve kullanıcı
kararı D17a'nın zorunlu sonucu; remediasyon turu 1: karar kanalı, M-2;
remediasyon turu 2: sesli görüşme, N-1).** Ağ iddiası şu beş sınıftan
oluşur; bu beş sınıf dışında sınıf yoktur:

1. **Runbook komutları:** bu runbook'un komutlarından **sıfır** ağ
   işlemi.
2. **Dosya aktarımı:** zincir içindeki **tek** dosya aktarımı, zincir adım
   5'te şifreli aktarım dosyasının dosya avukatının belirlediği kanaldan
   **içeri yönlü** alınmasıdır (§6.4); gerçek içerik cihazdan çıkmaz ve
   evidence'a `E2_INBOUND_TRANSFER_RECEIVED=True` yazılır.
3. **Ön-pencere insan ağ işlemleri:** içerik penceresinden **önce**, her
   biri ayrı `REAL_ACTION_APPROVED` ile, gerçek içerik taşımadan:
   VeraCrypt, Poppler ve 7-Zip kurulumları için indirme (zincir dışında,
   zincir adım 4'ten önce; §4.4/1) ve UYAP editörünün form dosyası
   üzerindeki imza doğrulaması (zincir adım 2–3; §6.6/1). Evidence'a her
   biri için `PRE_PILOT_NETWORK_ACTION=<tür>` ve onay zamanı yazılır.
4. **Karar kanalı (insan yazışmaları; kullanıcı kararı).** Dosya
   avukatının yazılı kararları (`LEGAL_APPROVED`; ör. E2 kanal belirlemesi,
   B3 işleme şartı teyidi, D9 cevabı, intake onayı, girdi karşılaştırması,
   fact kabulü, verification kararı, timeline onayı, adli tatil kararı,
   stopping-event beyanı, deadline onayı, veri akıbeti kararı) ve
   operatörün yazılı bildirimleri (E3 olay bildiriminin aynı gün yazılı
   kısmı §4.2/11, D9 bildirimi §1.6/5) **dava içeriği ve kişisel veri
   taşımaz**: yalnız opak
   kimlikler, sürüm numaraları, hash veya hash önekleri, sabit karar
   ifadeleri ve `yes`/`no`/`none` gibi literal'ler taşır. Bir karar dava
   içeriğine dayanıyorsa (ör. §17.2 kör hesap kaydı), içerik taşıyan kayıt
   kanala **girmez**, avukatın kontrolünde kalır; kanaldaki karar yalnız o
   kaydın SHA-256'sını anar ve içerik gerektiren karşılaştırma (§14.3,
   §18.3, §20) operatörün içerik oturumunun ekranında yapılır. Her gelen
   karar evidence'a `INBOUND_DECISION_RECEIVED seq=<n>
   sha256=<64-küçük-hex>`, her giden bildirim
   `OUTBOUND_NOTICE_SENT seq=<n> sha256=<64-küçük-hex>` olarak yazılır
   (`seq` her tür için `1`'den başlar, ardışıktır, satırlar silinmez);
   hash, kayda geçen mesaj metninin SHA-256'sıdır ve mesajın kendisi repo
   dışında saklanır. Karar kanalı bir dosya aktarımı **değildir**; dava
   içeriği veya kişisel veri taşıyan bir mesaj alınır ya da gönderilirse:
   **DUR** (H40, Y15).
5. **Sesli görüşme (kullanıcı kararı, remediasyon turu 2).** Dosya
   avukatı ile operatör arasındaki sesli telefon görüşmesi: E2 parolasının
   dosya avukatından operatöre iletilmesi (§6.4) ve E3 olay bildiriminin
   telefon kısmı (§4.2/11). Görüşme **cihaz dışıdır**: bu cihazdan
   yapılmaz ve bu cihazdan ağ işlemi değildir. Evidence'a yalnız
   `E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>` (E2 parolası) veya
   `INCIDENT_NOTICE_CHANNEL=VOICE_CALL at=<zaman-damgası>` (E3; karar
   kanalındaki `OUTBOUND_NOTICE_SENT` satırına **ek olarak**) yazılır.
   Parola, parolanın hash'i veya herhangi bir türevi **hiçbir zaman**
   yazılmaz. E2 parolası sesli görüşme dışında bir kanaldan gelirse:
   **DUR** (Y15; §6.4).

Bu beş sınıf dışındaki her ağ işlemi **DUR**'dur (Y15). Karar kanalı
mesajlarının içeriksiz olduğu operatörün ve dosya avukatının beyanına
dayanır; mekanik olarak doğrulanmaz (§32/38).

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
| F1 | "24 saat", "72 saat" veya açıklamalı "Diğer" (form v5: "24 saat") | Boş | §28.6: kapsayıcı içindeki geçici kopyalar (`<intake-dir>` içindeki aktarım dosyası ve açılmış içerik, `<container-temp>`) "iş bitince"den itibaren bu süre içinde silinir. "İş bitince" bu runbook'ta zincir adım 23'ün tamamlanması veya §25.2 abort yolunun başlaması anıdır |
| F2 | "Silinsin" veya "Şifreli arşivlensin" | Boş; iki kutu birden | §28.1, §28.3, §28.5 |
| F3 | F2 arşiv ise beş unsurun **hepsi** dolu | F2 arşiv iken bir unsur boş (H4) | §28.5 |
| F4 | **"Şifreli kapsayıcı yöntemi"** (form v5) — **yalnız** E1 = "Tek dosyalık pilot alternatifi" ve §4.4 doğrulaması (`CONTAINER_VERIFIED=True`, yürütme günü, zincir adım 4) ile birlikte | Boş; birden fazla kutu; E1 kapsayıcı seçeneği değil veya kapsayıcı doğrulanamadı. **"Tam disk şifrelemesi açıkken standart silme"**: bu revizyonda tanımlı değildir (§1.6/4) → **DUR**. **"Diğer"**: **DUR** (runbook'ta karşılığı yok; §6.1) (Y6) | §1.6/4, §4.2/10, §4.4, §28.3, §28.6 |
| F5 | İmha kaydını tutacak kişi/yer yazılı | Boş | §28.7 |
| F6 | "Kabul" | Boş; "Kabul değil, koşul:" (koşul runbook'a işlenip yeniden incelenene kadar) | §28.4 |
| F7 | "Kabul" | Boş; "Değişiklik:" (değişiklik runbook'a işlenene kadar) | §28.8 |

Bu tablodaki her DUR, gerçek belge **teslim alınmadan önce** kontrol edilir
(zincir adım 2). F4 kapısı yalnız silme anında değil, **teslimden önce** de
değerlendirilir: seçilen yöntem bu runbook'ta tanımlı değilse veya
kapsayıcı doğrulanamıyorsa gerçek belge teslim alınmaz, çünkü aksi hâlde
veri onaylı yöntemle silinemez hâlde diskte kalır. Kapsayıcı koşulu **her
silme gününde** silmeden hemen önce yeniden doğrulanır (§4.4/7, §28.3,
§28.6); o gün doğrulanamazsa silme yapılmaz ve veri korunur (§28.1/6).

**Kapsayıcı yönteminin anlamı (dürüst sınır).** Kapsayıcı dosyasının
geri dönüşüm kutusu kullanılmadan silinmesi içeriğin **üzerine yazmaz**;
gizlilik, verinin yalnız şifreli kapsayıcı içinde bulunmasına ve tek
kullanımlık anahtarın imha edilmesine dayanır (form v5 F4). Bu yüzden
koşul, gerçek verinin **yalnız** kapsayıcı içinde bulunmasıdır (§4.2/10,
§4.4). Kapsayıcı dışında kalmış bir kopya bu yöntemle "silinmiş" sayılmaz
(§28.6). İşletim sisteminin kapsayıcı dışına yazabildiği izler (sayfa
dosyası, hazırda bekletme dosyası, arama indeksi, antivirüs karantinası)
bu yöntemin kapsamı dışındadır; §1.6/5 bildirimi ve §32/25 sınırı geçerlidir.

---

## 24. Avukat formu ↔ runbook eşlemesi

| Form | Konu | Bölüm | DUR kodu |
|---|---|---|---|
| A1–A3 | Kapsam, 6.7 kararının teyidi, Bölüm 7 | §6.2 | Y1 |
| B1–B3 | Veri sorumlusu, operatör rolü, işleme sebebi (protokol inceleyicisinin önerisi + dosya avukatının bu dosya için işleme şartı teyidi) | §6.1, §6.3, §21 | Y2 |
| B4 | Dosya avukatı ≠ operatör (iki kişi kuralı) | §4.1, §14.3, §15.3 | Y4 |
| B5 | Operatör gizlilik taahhüdü (Ek 2, iki imzalı) | §6.3, §6.6 | Y2 |
| C1–C3 | Aydınlatma (Ek 1), açık rıza, avukatlık sırrı bilgilendirmesi | §7 | H3 |
| D 1–9, D2, D3 | Sisteme hiç alınmayacak belgeler | §9 | H2, H28 |
| E1 | Yerel şifreli kapsayıcı (F4 kapsayıcı yönteminin dayanağı) | §1.6/4, §4.2/10, §4.4, §6.4, §23 | Y5, Y6 |
| E2 | Teslim kanalı (uzaktan şifreli aktarım, 7z AES-256) | §1.6/5, §6.4, §11.2/2 | Y5 |
| E3 | Olay bildirimi (telefon + aynı gün yazılı) | §4.2/11, §25.2 | Y5 |
| E4 | Yerel metin aracı (Poppler `pdftotext`) | §4.2/3, §4.4/6, §11.2/6 | Y5 |
| F1 | Geçici dosya silme süresi | §23, §28.6 | Y6 |
| F2–F3 | Veri akıbeti, arşiv unsurları | §23, §28.1, §28.5 | H4, H55 |
| F4 | Silme yöntemi (yalnız şifreli kapsayıcı yöntemi yürütülebilir) | §1.6/4, §23, §28.3, §28.6 | Y6 |
| F5 | İmha kaydı | §23, §28.7 | Y6 |
| F6 | Kalan izler | §23, §28.4 | Y6 |
| F7 | 30 günlük silme talebi | §23, §28.8 | Y6 |
| G0–G8 | Dosya seçimi | §8 | H42, Y7 |
| G9 | Tebliğ tarihinin rakamla `GG.AA.YYYY` / `GG/AA/YYYY` yazılı olması | §8, §11.3 (b), §14.2 | H42, Y16 |
| G10–G11 | G bölümünün ayrı ad/tarih ve imzası | §6.6, §8 | Y7 |
| H | Pilot sırasında istenecek kararlar (bilgi) | §12.1 | — |
| I0 | Protokol onayı ("Hukuki protokol bakımından kabul ediyorum"); koşullu kabul runbook'a işlenene kadar DUR — yalnız A–F'yi kapsar; cevaplayan protokol inceleyicisi | §6.7 | Y1 |
| I1–I4 | Ekler ("Ek yok" dahil), ad, tarih, imza — yalnız A–F'yi kapsar; imzalayan protokol inceleyicisi | §6.1, §6.6, §6.7 | Y1, Y20 |
| Ek 1, Ek 2 | Aydınlatma metni (dosya avukatı); operatör taahhüdü (operatör + dosya avukatı) | §6.3, §6.6, §7 | H3, Y2, Y20 |

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
| H40 | Gerçek içerik güven sınırının ihlali veya şüphesi; kanal kapısı geçmedi; kapsayıcı dışında gerçek içerik; içerik penceresi içinde çıkarılmış bir harici sürücünün yeniden takılması veya **yeni** bir harici/çıkarılabilir sürücünün takılması; içerik penceresi içinde yerleşik optik sürücüye medya takılması, görüntü bağlanması veya optik sürücünün kayıtla eşleşmemesi (bu olayların **tek** kodu; §4.2/10; optik sürücü revizyon 2); §4.3 (a) kapatma prosedürünün ikinci (veya kısa aralıklı, geçersiz) taramasında görünen süreç (revizyon 2); kit modunda `a2`/`a3` taramalarında sayı ≠ 0 veya `a9` kapanış taramasında `STOP CLOSING_SCAN_OK=False` (revizyon 3; Ek R3) | §4.2, §4.3, §4.4 |
| H41 | Bağımsız inceleme, commit veya sentetik prova ön koşulu eksik | §1.6 |
| H42 | Form G'de "Hayır" veya boş | §8 |
| H43 | Intake alanlarından birinin avukat onayı eksik; `unverified` dışı `verification_state`; JSON'da BOM; metin uzunluğu sınır dışı; metinde görünür karakter yok (`STOP TEXT_VISIBLE=EMPTY`; revizyon 2) | §11.2, §11.4 |
| H44 | **Kaldırıldı** (`--mask-term` ve engel değerleri dosyası; §29) | — |
| H45 | Verification ön koşulu sağlanmıyor: locator yok, belge `active` değil veya avukatın ayrı verification kararı yok | §15.3 |
| H46 | Silme guard'ı başarısız veya silme kısmi/belirsiz; o hedef için silme anı onayı yok | §28.3 |
| H47 | Şifreli arşivin paritesi doğrulanamadı | §28.5 |
| H48 | Revoke ön koşulu: aktif assignment tam 1 değil | §27.1 |
| H49, H50 | **Kaldırıldı** (sonuçsuz POST tüketimi, pano/anahtar; §29) | — |
| H51 | `tax_type` sözlük kontrolü başarısız veya Form G8 ile eşleşmiyor; `manual-fact` çalıştırılmaz | §8, §11.3 |
| H52 | Yol kapısı başarısız; `<external-root>` sözleşmesi ihlali (`<evidence-dir>` dışında öğe veya eksik `<evidence-dir>` dahil); `<container-root>`, `<pilot-root>` sözleşmesi (izinli dört çocuk dışında öğe dahil) veya `<container-file>` kapısının iki aşamasından biri (`container-file-parent`, `container-file`) başarısız; `SYSTEM_TEMP_RECORDED=True`, `SYSTEM_TEMP_MATCH=True` veya `TEMP_IN_CONTAINER=True` yok; `<python>`/`<psql>`/`<pdftotext>`/`<7z>` beklenen dizin dışında; `<archive-dir>` kapısı başarısız. Kit modunda `a4`'ün ön koşul reddi (TEMP ön denetimi; ayrıca Y5'in "teknik kayıt yok", biçimi geçersiz teknik kayıt ve pencere öncesi optik sürücü medya/eşleşme durumları; `a4 BASLAMADI: …`; §34.11) kayıt ve kilit yazmaz; `a4` PASS olmadan E2 zinciri ilerlemez; kayıt oluştuktan sonraki `STOP KIT_TEMP_IN_CONTAINER=False` ve `STOP TOOL_MANIFEST_MATCH=False` kilit yazar (revizyon 5) | §4.4, §13.8, §28.5 |
| H53 | İçerik oturumu `-NoProfile` değil; aktif transcript; beklenmeyen modül; handler `UNKNOWN`; `SaveNothing` değil; kit modunda `CONTENT_SESSION_EP=Bypass` yok (revizyon 3) | §4.3 |
| H54 | Salt-okunur SQL sözleşmesi ihlali; düzeltici SQL gereği | §13.5 |
| H55 | Eksik veya belirsiz veri akıbeti kararı intake'ten sonra fark edildi: veri silinmez, arşivlenmez, korunur | §28.1 |
| H56 | `<restricted-dir>` içerik sözleşmesi ihlali (kayıt/hash, izinli küme dışı öğe, alt dizin, reparse point, manifest yazılamadı) | §10.5, §28.2 |
| H57–H59 | **Kaldırıldı** (harness zinciri, süreç yardımcısı, çocuk süreç ortam profili; §29) | — |
| Y1 | Form A'da kapıyı kapatan cevap veya runbook'a işlenmemiş ek koşul; I0 boş, iki kutu birden işaretli veya koşullu kabul (§6.7); I1–I4 eksik (I1'de ne "Ek yok" ne "Ekler" işaretli; "Ek yok" ile ek gerektiren bir cevap çelişiyor); A–F imzası §6.6/1 biçiminde değil veya `UDF_SIGN_PART_PRESENT=True` alınamadı; ölçülen `FORM_HASH unit=AF seq=1` §0'daki v5 hash'iyle aynı değil | §6.1, §6.2, §6.6 |
| Y2 | Form B1–B3 veya B5 kapısı; dosya avukatının bu dosya için işleme şartı teyidi yok veya hiçbir işleme şartını adıyla belirtmiyor (`PROCESSING_BASIS_CONFIRMED=True` yok; pilot başlamaz); B5 "Evet" iken Ek 2 yok veya operatör/dosya avukatı imzalarından biri eksik | §6.3 |
| Y3 | Kullanılmıyor (Form C kapısı H3 satırındadır) | — |
| Y4 | İki kişi kuralı: B4 boş; aynı kişi iken B4 "Hayır" veya dosya avukatının ayrı yazılı kabulü yok; `TWO_PERSON_CONTROL=SEPARATE` veya `=WAIVED_B4` kaydından tam biri yok | §4.1, §14.3 |
| Y5 | Form E kapısı: E1 kapsayıcı seçeneği değil veya E1'e §4.4'te karşılığı olmayan ek koşul yazılmış; kapsayıcı doğrulanamadı (`CONTAINER_VERIFIED=True` yok) veya teknik kayıt yok/uyuşmuyor (`TOOL_MANIFEST_MATCH=True` yok); harici disk çifti kabul edilen tek birleşim değil (`EXTERNAL_DISK_REMOVED=False`, okunamıyor, ikisi de `True` veya `EXTERNAL_DISK_ENCRYPTED=True`; §4.2/10); içerik penceresinden önce yerleşik optik sürücü kaydı alınamadı veya tek yeniden ölçümden sonra da medya takılı ya da kayıtla eşleşmiyor (`STOP CDROM_QUERY=FAIL`, `STOP OPTICAL_MEDIA_LOADED=UNKNOWN`, ikinci ölçümde `OPTICAL_MEDIA_LOADED=True` veya `STOP OPTICAL_DRIVES_MATCH_RECORD=False`; §4.2/10, revizyon 2); E2 kanalı veya taşıyıcı kontrolü (`ENCRYPTED_TRANSFER` dışı tür, `E2_CARRIER_ENCRYPTED=False`, parola aynı kanaldan veya sesli görüşme dışında bir kanaldan (ayrıca Y15), kapsayıcıya doğrudan kaydedilmedi, e-posta eki için hukuki cevap yok, `SEVENZIP_ALL_ENTRIES_7ZAES=True` yok); `PDFTOTEXT_RC` ≠ 0; açmada başarı birleşimi (`SEVENZIP_RC=0` ve `X_ENTRY_COUNT=1`) dışındaki her sonuç — tek istisna, ilk denemede `SEVENZIP_RC=2` + `SEVENZIP_WRONG_PASSWORD_SHOWN=True` + `X_ENTRY_COUNT=0` birleşiminden sonraki tek ek denemedir; ek denemede de başarı yoksa Y5 (§6.4, revizyon 2); alfabe dışı parola veya tutmayan geri okumadan sonra eski parolanın kullanılması, ya da ikinci arşivin parolasının da alfabe dışı olması veya geri okumasının tutmaması (§6.4, revizyon 2); optik sürücü sayısı veya harfleri teknik kayıtla eşleşmiyor (pencere öncesinde, tek yeniden ölçümden sonra; `STOP OPTICAL_DRIVES_MATCH_RECORD=False`; §4.2/10, §4.4/6, revizyon 2); 7z listelemesinin bekçi süresi içinde dönmemesi (`STOP SEVENZIP_LIST_TIMEOUT=True`) veya başlatılamaması (`STOP SEVENZIP_LIST_START=FAIL`; §6.4, K-R2-2, revizyon 3); kit modunda geri okumanın tutmaması (`STOP HP_READBACK=fail`, kullanıcı kararı S-2), parola isteminin görülmemesi (`STOP E2_CARRIER_ENCRYPTED=False`) veya kitin kurulamaması/yüklenememesi (`KIT_LOAD_*`; Ek R3); E3 bildirim yolu veya E4 aracı/onayı eksik. **Pencere içinde yeniden takılan veya yeni takılan sürücü Y5 değil, H40'tır.** Kit modunda `a4`'ün ön koşul reddi (teknik kayıt yok veya biçimi geçersiz; pencere öncesi optik ön ölçüm) kayıt ve kilit yazmaz (H52 notu; §34.11); sorgu başarısızlığı, okunamayan medya durumu ve biçimi geçerli kaydın araçlarla uyuşmaması kilitli kalır (revizyon 5 düzeltme turu; bağımsız inceleme L3) | §4.2, §4.4, §6.4, §11.2/6 |
| Y6 | Form F1, F4–F7 kapısı; F4 kapsayıcı yöntemi değil; silme günü kapsayıcı yeniden doğrulanamadı; F1 kopyası kapsayıcı dışında; F1 süresi aşıldı; kapsayıcı imhası veya anahtar imhası kaydı yok; imha kaydı yazılmadı | §1.6/4, §23, §28 |
| Y7 | G0 boş veya kişisel veri taşıyor; G8 boş; G10/G11 eksik veya imza §6.6/1 biçiminde değil; G10 tarihi bağlayıcı I3'ten önce veya avukatın sıra beyanı yok; A–F yeniden imzalandı ve G yeniden imzalanmadı | §6.6, §8 |
| Y8 | `PAGE_COUNT=OK` alınamadı (`file.page_count` boş, tamsayı değil veya < 1) | §11.2/5 |
| Y9 | `MANUAL_INPUT_ENCODING=OK` alınamadı | §14.2 |
| Y10 | Avukatın girdi karşılaştırması yok; kararda `r<input-revision>` veya hash öneki yok; `MANUAL_INPUT_HASH_RECORDED=True`, `MANUAL_INPUT_MATCHES_LAWYER_REVISION=True` veya `LAWYER_DECISION_CITES_RECORD=True` alınamadı; üçüncü bir girdi düzeltmesi gereği (`<input-revision>` > 3); sürüm sırası atlandı veya ileri bir sürüm kaydı mevcut | §14.3, §14.5.3 |
| Y11 | `manual-fact` preview/apply kabul kriterinden sapma: tarih/sayfa avukatın teyidinden farklı; `pending_sha256` farkı; `replayed=True`; journal ≠ 1 yeni `completed` satır; disk veya audit boolean'larından biri beklenen değerde değil (`AUDIT_FILE_BOUND`, `AUDIT_UNPARSEABLE_COUNT` dahil) | §14.4, §14.5 |
| Y12 | Pending içerik kontrolü (`method`, sağlayıcı/model, fact sayısı, `unverified`, `<fact-id>`, locator) başarısız | §15.1 |
| Y13 | §14.6: ayrıştırılamayan audit; temp artığı guard'ı (journal satırı `failed` değil, audit sayımı, temp SHA uyuşmazlığı) veya silme sonucu; dry-run ve apply sonuç farkı; `new_state=reconciliation_required`; ikinci yeniden deneme gereği; validator kaynaklı kök hata | §14.6 |
| Y14 | `generation --row-key fact_extraction` çalıştırıldı veya şüphe; kapanış SQL'i `0` değil | §14.7, §21 |
| Y15 | Herhangi bir model çağrısı, ağ bayrağı veya API anahtarı oluşturma girişimi; §21'deki beş sınıfın (runbook komutları, dosya aktarımı, ön-pencere insan ağ işlemleri, karar kanalı, sesli görüşme) dışında bir ağ işlemi; karar kanalında dava içeriği veya kişisel veri taşıyan bir mesaj; E2 parolasının sesli görüşme dışında bir kanaldan gelmesi | §1.2, §3, §6.4, §21 |
| Y16 | Form G9 "Hayır" veya boş; `TEXT_DATE_TOKEN_PRESENT=True` alınamadı (metinde tanınabilir biçimde tarih yok) | §8, §11.3 (b) |
| Y17 | `ICACLS_RC` ≠ 0 veya `PILOT_ACL_PRINCIPALS_OK=True` alınamadı (izinli küme dışı principal, deny kaydı veya mirası kesilmemiş `<pilot-root>`) | §4.4/4 |
| Y18 | İçerik oturumunda §13.6 (b) taramasında `CLAUDE.*` eşleşmesi veya oturumun bir ajan oturumundan başlatıldığı şüphesi | §4.2/6, §13.6 |
| Y19 | Kapsayıcı dışı izlerin protokol inceleyicisine ve dosya avukatına yazılı bildirimi yok, dosya avukatının yazılı `LEGAL_APPROVED` cevabı yok veya cevap kabul etmiyor | §1.6/5, §4.4/8 |
| Y20 | E-imzalı bir form biriminde `UDF_SIGNATURE_VALID=True` yok (`False`, ölçülmemiş veya belirsiz) | §1.6/5, §6.6/1 |

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
   eksik veya belirsizse, F4 kapsayıcı yöntemi değilse ya da silme günü
   kapsayıcı yeniden doğrulanamıyorsa (§4.4/7) veri
   **silinmez ve arşivlenmez**; değiştirilmeden korunur (H55, Y6). DUR tek
   başına bir silme talimatı **değildir**.
9. **Geçici kopyalar (kapsayıcı içinde).** Form F1 süresi DUR anından
   itibaren işler (§23); §28.6'ya göre ele alınır.
10. **Olay bildirimi.** DUR bir güvenlik olayıysa (H40; cihaz kaybı,
    virüs, yetkisiz erişim, yanlış alıcı, veri sızıntısı şüphesi) dosya
    avukatına Form E3'teki yolla **hemen telefonla** ve **aynı gün**
    kişisel veri içermeyen yazılı bildirimle bildirilir (§4.2/11).
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

**Kit modunda DUR sonrası içerik penceresi (R3 düzeltme turu;
kullanıcı kararı H-1=A).** Kit `DUR.txt` kilidini yazdıktan sonra 8.
ve 9. adımlar için gereken içerik penceresi, kilit kaldırılmadan, §4.3
(a)'daki **silme oturumu** olarak açılır: kanal kapısı `a2`/`a3` ile
aynen yapılır, `a4`–`a7` çalışmaz, oturum `a9` ile biter. Kilit yalnız
yazılı kullanıcı kararından sonra Ek R3/4 kural 1'deki yeniden
adlandırmayla kaldırılır.

---

## 26. Audit / evidence sözleşmesi

### 26.1 Konum

Kaynak: Temel L3080–L3087. **Sapma:** probe ve inference dizinleri
çıkarıldı.

`<evidence-dir>` repo ve kapsayıcı dışında, erişimi kısıtlı bir dizindir
ve **yalnız metadata** taşır; kapsayıcı imhasından sonra da kalır.
Revizyon 3'ten itibaren (kullanıcı kararı K-R3-12) `<evidence-dir>\kit\`
(kit betikleri, `pins.txt`, `kit-values.txt`), `<evidence-dir>\steps\`
(adım kayıtları), `<evidence-dir>\kit-build.txt`,
`<evidence-dir>\DUR.txt` ve kilit kaldırıldıysa
`<evidence-dir>\DUR-lifted-<n>.txt` ile `<evidence-dir>\dur-lift-<n>.txt`
(Ek R3/4 kural 1) de metadata'dır; gerçek içerik taşımaz.
`kit-values.txt`'nin dar yol istisnası §1.5'tedir; §26.4 tam manifesti
bu dosyaları da kapsar. Gerçek belge baytları, metin, girdi dosyası, alıntı, tarih,
sayfa numarası, ham stdout/stderr, traceback, deadline raporu veya kişisel
veri buraya **yazılmaz**. Dava-türevi içerik yalnız `<restricted-dir>`
içinde durur.

### 26.2 Zorunlu kayıtlar

Kaynak: Temel L3089–L3114. **Sapmalar:** maskeleme, ortam profili, süreç
yardımcısı, probe ve inference satırları çıkarıldı; form, manuel girdi,
`manual-fact`, reconciliation ve ağsızlık satırları eklendi.

| Kayıt | İçerik |
|---|---|
| Başlangıç | Branch, HEAD, temiz ağaç, runbook'un tracked olduğu, ignored görünüm, küme durumu, `pip check`, kayıt/telemetri ön kontrolü; `CMDLINE_AUDIT_KEY=PRESENT` ise `CMDLINE_AUDIT_DECLARATION sha256=<64-küçük-hex>` (§4.2/9; revizyon 2) |
| İçerik oturumu | §4.3 (b) çıktıları (her içerik oturumu için) |
| Kanal kapısı | §4.3 (a): süreç adı taraması sonucu (kapatma prosedürünün iki taraması, her biri kendi `AI_CHANNEL_SCAN at=<zaman-damgası>` satırıyla, ikisi de `AI_CHANNEL_PROCESS_COUNT=0`, iki zaman damgası arası en az 2 dakika; revizyon 2), altı sınıf boolean'ı ve `AI_CONTENT_CHANNELS_CLOSED=True`; kit modunda her içerik oturumu için `<evidence-dir>\steps\s<k>\a2.txt`, `a3.txt` (`SCAN_INTERVAL_SEC`, `SCAN_INTERVAL_OK=True`) ve `a9.txt` (`CLOSING_SCAN_OK=True`) (revizyon 3) |
| Kit | `<evidence-dir>\kit-build.txt` (`KIT_BUILD=OK`, her kit dosyası için SHA-256, `kit-values.txt` denetim sonucu; revizyon 5'ten itibaren `KIT_VAR_COLLISIONS=0` ve `KIT_VAR_CHECK_TOOL_SHA256`, Ek R3/7), her oturumun `steps\s<k>\ac.txt`'si (`KIT_LOAD=OK`, `KIT_PINS_SHA256`, `KIT_DUR_PRESENT`, `KIT_TEARDOWN_SESSION`) ve varsa `<evidence-dir>\DUR.txt` (`KIT_DUR step=<adım> at=<zaman-damgası>`, `KIT_DUR_REASON=<kod>`), kilit kaldırıldıysa `DUR-lifted-<n>.txt` ve `dur-lift-<n>.txt` (`KIT_DUR_LIFTED …`, karar SHA-256'sı) (revizyon 3; Ek R3) |
| Yol kapısı | §13.8: her yer tutucu adı için `PATH_OK`, `PATH_OK=external-root-contract`, `PATH_OK=container-root`, `PATH_OK=pilot-root-contract`, `PATH_OK=container-file-parent` (oluşturmadan önce) ve `PATH_OK=container-file` (oluşturduktan sonra) |
| Ön koşullar | Bağımsız inceleme sonucu, commit kimliği, sentetik prova evidence'ının hash'i (`13f19d0` provası ve bu revizyonun delta provası); §1.6/5 kapıları: `AI_CONTENT_CHANNELS_CLOSED=True`, tek yazan oturum beyanı, PR-NOPROFILE sonuç satırları, `CONTAINER_RESIDUAL_NOTICE_SENT=True` ve bildirim/cevap hash'leri, E2 kanal belirlemesinin ve (gerekiyorsa) hukuki cevabın hash'i |
| Avukat formu | Form v5 hash'i (§0) ve ölçülen `FORM_HASH unit=AF seq=1` ile eşliği; §6.6/7 biçimindeki bütün `FORM_HASH` ve `FORM_BINDING` satırları (her imzalı sürüm ve her ek — `ATT1` Ek 1, `ATT2` Ek 2 — ayrı satır) ve her `FORM_HASH_RECHECK` sonucu; imza biçimi (taranmış PDF / e-imza); her e-imzalı birim için `UDF_SIGN_PART_PRESENT=True` ve `UDF_SIGNATURE_VALID=True unit=<birim> seq=<n>` ile UYAP editörü ağ erişimi onayının zamanı; I3–G10 sıra kontrolü ve dosya avukatı beyanının hash'i; Ek 1 teslim teyidinin hash'i; redakte kapsam özeti; `TWO_PERSON_CONTROL=SEPARATE` veya `TWO_PERSON_CONTROL=WAIVED_B4` (ikincisinde kullanıcı onayının zamanı); girdi düzenleyicisinin adı |
| Kapsayıcı ve teknik kayıt | `technical-record.txt` ve SHA-256'sı; `system-temp.txt`, `SYSTEM_TEMP_RECORDED=True` ve her içerik oturumunda `SYSTEM_TEMP_MATCH=True` (§4.4/5); her ölçüm için (zincir adım 4, her içerik oturumu, her silme günü): `CONTAINER_MOUNTED_AS_DRIVE_LETTER=True`, `CONTAINER_VERIFIED=True`, `TEMP_IN_CONTAINER=True`, `PILOT_ACL_PRINCIPALS_OK=True`, `TOOL_MANIFEST_MATCH=True`; oluşturmada `CONTAINER_ONE_TIME_KEY=True`, `CONTAINER_FILE_BYTES`, `CONTAINER_FILE_NOT_CLOUD_SYNCED=True`, `ICACLS_RC=0`; harici disk için sürücü harfiyle `EXTERNAL_DISK_ENCRYPTED=False` / `EXTERNAL_DISK_REMOVED=True`; teknik kayıtta `CDROM_DRIVE_COUNT=<n>` ve `OPTICAL_DRIVE_LETTERS=<harfler>` (§4.4/6); yerleşik optik sürücü için her ölçümde `CDROM_DRIVE_COUNT=<n>`, `OPTICAL_DRIVES_MATCH_RECORD=True` ve her sürücü için `OPTICAL_MEDIA_LOADED=False drive=<sürücü-harfi>` (§4.2/10; revizyon 2); kurulum ve UYAP editörü için `PRE_PILOT_NETWORK_ACTION` satırları ve onay zamanları. Provadan: `CONTAINER_TOOL_PRESENT`, `CONTAINER_MOUNTED_AS_DRIVE_LETTER`, `PATH_OK=container-root`, `EXTERNAL_DISK_PRESENT` (§1.6/3) |
| E2 taşıyıcısı | `E2_CARRIER_KIND=ENCRYPTED_TRANSFER`, `SEVENZIP_ALL_ENTRIES_7ZAES`, `E2_CARRIER_ENCRYPTED`, `E2_KEY_SEPARATE_CHANNEL`, `E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>` (parola veya türevi yok; §21/5), `E2_SAVED_DIRECTLY_TO_CONTAINER`, `E2_INBOUND_TRANSFER_RECEIVED=True` (§21/2), `SEVENZIP_RC=<n> attempt=<k>`, `X_ENTRY_COUNT` ve `SEVENZIP_WRONG_PASSWORD_SHOWN=True/False attempt=<k>` (her deneme ayrı satır; mesaj metni ve girdi adı yok), `SEVENZIP_FOLDER_ENTRY_COUNT` (bilgi), her parola için `E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>` ve `E2_PASSWORD_PAPER_DESTROYED=True at=<zaman-damgası> reason=<neden>` (`<neden>` ∈ `used`, `rejected`, `stopped`; §6.4; revizyon 2); `PDFTOTEXT_RC` (§11.2/6); kit modunda `<evidence-dir>\steps\e2\` altındaki `a4`–`a8` kayıtları: `SYSTEM_TEMP_MATCH`, `KIT_TEMP_REDIRECT` (revizyon 5), `KIT_TEMP_IN_CONTAINER`, listeleme ölçüm satırları (`LIST_CALL_AT`, `LIST_RETURN_AT`, `LIST_ELAPSED_MS`, `SEVENZIP_LIST_TIMEOUT`, `SEVENZIP_LIST_RC`, `SEVENZIP_TYPE_7Z_SEEN`, stderr sayı ve boolean'ları, `SEVENZIP_PROC_COUNT_BEFORE/AFTER`), `HP_READBACK`, `CAPS_LOCK`, `SEVENZIP_PASSWORD_PROMPT_SHOWN`, `ATTEMPT_OUTCOME` ve kayıtlardan türetilmiş `reason` (revizyon 3) |
| Olay bildirimi | Varsa `INCIDENT_PHONE_NOTIFIED=True`, `INCIDENT_NOTICE_CHANNEL=VOICE_CALL at=<zaman-damgası>` (§21/5), `INCIDENT_WRITTEN_NOTICE_SAME_DAY=True`, olay kaydının SHA-256'sı (§4.2/11) |
| Karar kanalı | Her gelen yazılı karar için `INBOUND_DECISION_RECEIVED seq=<n> sha256=<64-küçük-hex>`, her giden bildirim için `OUTBOUND_NOTICE_SENT seq=<n> sha256=<64-küçük-hex>` (§21); `PROCESSING_BASIS_CONFIRMED=True` (§6.3 B3) |
| Restricted kümesi | `restricted-allowed-files.txt`, `ALLOWED_FILE_HASH_RECORDED=True`, hash kaydının bayt sayısı ve SHA-256'sı, her envanterde `ALLOWED_FILE_HASH_OK=True`, `RESTRICTED_INVENTORY=OK` ve dosya sayısı |
| Intake | `JSON_BOM=NONE`, `TEXT_LENGTH=OK`, `TEXT_VISIBLE=OK` (revizyon 2), `PAGE_COUNT=OK`, `INTAKE_HASH=MATCH`, `TEXT_DATE_TOKEN_PRESENT=True`, `INTAKE_HASHES_RECORDED=True`, her `manual-fact` çağrısı öncesi `SOURCE_HASHES_MATCH=True`, validator PASS/sayılar, `TAX_TYPE_VOCAB=OK`, ignore kontrolü, avukat intake onayının hash'i |
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
| Kapanış | İki manifest ve dosya sayıları, silme günü kapsayıcı doğrulaması, silme guard ve sonuç satırları, kapsayıcı imhası (`CONTAINER_DISMOUNTED=True`, `CONTAINER_FILE_GUARD=PASS`, `CONTAINER_FILE_ABSENT=True`) ve `CONTAINER_KEY_DESTROYED=True`, varsa `PATH_OK=archive-dir` ve arşiv paritesi, revoke sonucu, F1 silme kaydı (kopya sayısı, her kopyanın kapsayıcı içinde olduğu, zaman), F5 imha kaydının yeri ve dosya avukatına verilen kopyanın kaydı, form hash'lerinin kapanış yeniden ölçümü, postcondition'lar |
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

Kaynak: Temel L3135–L3138. **Sapma:** tam manifest şartı eklendi
(revizyon; prova incelemesi L-2).

Pilot sonunda kişisel veri içermeyen tek bir özet dosyası yazılır ve
SHA-256'sı kaydedilir. Özet, `<evidence-dir>` içindeki özet dışındaki
**bütün** dosyaların göreli yol, bayt ve SHA-256 manifestini taşır;
yalnız bir alt kümeyi sabitleyen özet yeterli değildir. Özet yoksa veya
manifest eksikse pilot kapanmış sayılmaz (H26).

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
  komutu ve `ui.reconciliation_operator --apply` için geçerlidir. Ayrıca
  şunlar için de geçerlidir: araç kurulumları (§4.4/1), kapsayıcının
  oluşturulması (§4.4/2), `<pilot-root>` ACL sıkılaştırması (§4.4/4),
  teknik kaydın yazılması (§4.4/6), her e-imzalı birimin UYAP editöründe
  açılması (§6.6/1), kapsayıcı imhası ve anahtar imhası (§28.3.3).
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
  raporu); oluşmuş olabilecek diğer kopyalar (§28.6); ardından
  kapsayıcının kendisi (kapsayıcıdaki repo klonu, `<container-temp>` ve
  `<intake-dir>` dahil) ve tek kullanımlık anahtarı (§28.3.3).
- **Şifreli arşiv** ("Şifreli arşivlensin"). Aynı kapsam ve Form **F3**'ün
  beş unsurunun **tamamı**: (1) arşiv yeri (`<archive-dir>` ve
  `<archive-parent>`); (2) şifreleme yöntemi; (3) erişebilecek kişiler veya
  roller; (4) saklama süresi / silinme tarihi; (5) arşiv doğrulandıktan sonra
  yerel kopyanın **silineceği** veya **korunacağı**.

**Teslimden önceki kapı.** F2 boşsa veya arşiv seçiliyken F3'ün bir unsuru
eksikse: gerçek belge teslim **alınmaz** (H4). F4 "Şifreli kapsayıcı
yöntemi" değilse veya kapsayıcı doğrulanamıyorsa da teslim alınmaz
(§1.6/4, §23, Y6).

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
bulunur. Approval'dan sonra da yerinde kalan pending dosyaları
(`documents\<document-id>\extractions\facts_llm_v1_3.json.pending`,
`timeline\…json.pending`, `deadlines\…json.pending`; §18.2) beklenen
yollardır (revizyon 2; R-D-E18PENDING). `facts_llm_…` adı tarihsel bir
sabittir; LLM kullanıldığını göstermez (§15.1, §22.1; delta prova
incelemesi O-3). Bir yol kişisel veri taşıyorsa manifest **oluşturulmadan DUR**
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
eklendi. **Revizyon (§34):** F4 kapısı kapsayıcı yöntemine çevrildi;
restricted guard'ının ebeveyn kapısı `<pilot-root>` sözleşmesine taşındı;
kapsayıcı imhası (§28.3.3) eklendi. **Remediasyon turu 1 (§34.6):** bütün
korunan listelerde `[System.IO.Path]::GetTempPath()` yerine
`<system-temp-user>`, `<system-temp-windows>` ve `<container-temp>`
kullanılır (H-1); `<external-root>` kalıntı kontrolü tam eşitliğe döndü
(H-2). Case guard fonksiyonu **birebirdir**.

**F4 kapısı.** §28.3.1 ve §28.3.2'deki silme `Remove-Item -Recurse
-Force`'tur: dosya sistemi kaydını kaldırır, geri dönüşüm kutusunu
kullanmaz, ama içeriğin **üzerine yazmaz**. Bu iki silme kapsayıcı
**içindedir**; gizliliği sağlayan, ardından gelen kapsayıcı imhası ve
anahtar imhasıdır (§28.3.3). Üçü birlikte Form F4 **"Şifreli kapsayıcı
yöntemi"**dir ve bu runbook'ta tanımlı **tek** yöntemdir. Bu bölüm yalnız
şunların hepsi sağlanırsa uygulanır:

1. Form F4 = "Şifreli kapsayıcı yöntemi" ve E1 = "Tek dosyalık pilot
   alternatifi" (§23);
2. **silme günü**, ilk silme komutundan hemen önce, §4.4/7 kapsayıcı
   doğrulaması (`CONTAINER_VERIFIED=True`), §4.4/4 ACL ölçümü ve §4.2/10
   harici disk kuralı yeniden yapılmış ve geçmiştir.

F4 başka bir seçenekse ya da madde 2 sağlanmazsa bu bölüm
**uygulanmaz**: **DUR** (Y6); veri değiştirilmeden korunur (§28.1/6) ve
avukata bildirilir.

Silme **yalnız** §28.1/3'teki açık ve eksiksiz yazılı kararla yapılır. Üç
hedef vardır ve her biri **ayrı** guard'dan, **ayrı** silme anı
`REAL_ACTION_APPROVED`'dan ve **tek** çalıştırmadan geçer: önce case dizini
(§28.3.1), sonra `<restricted-dir>` (§28.3.2), en son kapsayıcının
kendisi ve anahtarı (§28.3.3; kullanıcı kararı D12: içerideki guard'lı
silmeler, kapsayıcı imhasından önce korunur).

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
    $cProtected = @("<external-root>", "<evidence-dir>", "<restricted-dir>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")
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
    $cProtected = @("<external-root>", "<evidence-dir>", "<restricted-dir>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")
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
`$rManifest.Count -ge 1` (başlık-yalnız manifest kabul); **revizyon (§34;
kullanıcı kararı D2):** `<restricted-dir>` kapsayıcı içindeki `<pilot-root>`
altında olduğu için ebeveyn kapısı `Test-PilotExternalRoot` yerine
`Test-PilotPilotRoot` (§13.8) ile yapılır; silme sonrası kalıntı kontrolü
`<pilot-root>` çocuk kümesine ve ayrı `<external-root>` sözleşmesine
bölündü.

```powershell
$rDir = "<restricted-dir>"
$rParent = "<pilot-root>"
$rGuard = $false
$allowedHashOk = Test-PilotAllowedHash "<evidence-dir>\restricted-allowed-files.txt" "<evidence-dir>\restricted-allowed-files.sha256.txt"
"ALLOWED_FILE_HASH_OK=$allowedHashOk"
$rPrevEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Stop'
    $g = ($allowedHashOk -eq $true) -and (Test-PilotResolved $rDir) -and (Test-PilotResolved $rParent) -and (Test-Path -LiteralPath $rDir -PathType Container) -and (Test-PilotNoReparse $rDir) -and ([System.IO.Path]::GetDirectoryName($rDir.TrimEnd('\')) -eq $rParent.TrimEnd('\'))
    if ($g) { $g = ((Test-PilotPilotRoot $rParent "<container-root>" @("<repo-root>", "<restricted-dir>", "<container-temp>", "<intake-dir>")) -eq $true) }
    $rManifest = @(); $allowedLines = @()
    if ($g) { $rManifest = @([System.IO.File]::ReadAllLines("<evidence-dir>\closing-restricted-manifest.tsv", (New-Object System.Text.UTF8Encoding($false)))); $allowedLines = @([System.IO.File]::ReadAllLines("<evidence-dir>\restricted-allowed-files.txt", (New-Object System.Text.UTF8Encoding($false)))) }
    $allowedSet = @($allowedLines | Select-Object -Skip 1)
    $rExpected = @($rManifest | Select-Object -Skip 1)
    $g = $g -and ($rManifest.Count -ge 1) -and ($rManifest[0] -ceq '# kind=restricted') -and ($allowedLines.Count -ge 2) -and ($allowedLines[0] -ceq '# kind=restricted-allowed') -and (@($rExpected | Where-Object { $allowedSet -cnotcontains ($_ -split "`t")[0] }).Count -eq 0)
    if ($g) { foreach ($p in @("<repo-root>", "<case-root>", "<evidence-dir>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $rDir $p)) { $g = $false } } }
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
alındıysa, aynı oturumda, **bir kez** (**sapma:** kalıntı kontrolü
`<pilot-root>` ve `<external-root>` için ayrı):

```powershell
if ($rGuard -eq $true) { try { Remove-Item -LiteralPath $rDir -Recurse -Force -ErrorAction Stop; "RESTRICTED_DELETE_RESULT=COMPLETED" } catch { "STOP RESTRICTED_DELETE_RESULT=FAILED" } } else { "STOP RESTRICTED_DELETE_GUARD=FAIL" }
"RESTRICTED_DIR_ABSENT=$(-not (Test-Path -LiteralPath $rDir))"
"RESTRICTED_RESIDUE_COUNT=$(@(Get-ChildItem -LiteralPath $rDir -Force -Recurse -ErrorAction SilentlyContinue).Count)"
$pilotResidueOk = $false
try { $pilotResidueOk = ((Test-PilotPilotRoot $rParent "<container-root>" @("<repo-root>", "<container-temp>", "<intake-dir>")) -eq $true) } catch { $pilotResidueOk = $false }
"PILOT_ROOT_RESIDUE_OK=$pilotResidueOk"
$extResidueOk = $false
try { $extKept = @("<evidence-dir>"); if ((Test-PilotExternalRoot "<external-root>" "<repo-root>" $extKept @("<container-root>", "<case-root>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")) -eq $true) { $extNow = [string[]]@(Get-ChildItem -LiteralPath "<external-root>" -Force -ErrorAction Stop | ForEach-Object { $_.Name }); $extExpected = [string[]]@($extKept | ForEach-Object { [System.IO.Path]::GetFileName($_.TrimEnd('\')) }); [Array]::Sort($extNow, [System.StringComparer]::Ordinal); [Array]::Sort($extExpected, [System.StringComparer]::Ordinal); $extResidueOk = (($extNow -join '|') -ceq ($extExpected -join '|')) } } catch { $extResidueOk = $false }
"EXTERNAL_ROOT_RESIDUE_OK=$extResidueOk"
git status --porcelain=v1 --untracked-files=all
git status --ignored --porcelain -- data/cases
git status --porcelain -- data/cases/case_0001
```

Beklenen, hepsi birlikte: `RESTRICTED_DELETE_RESULT=COMPLETED`,
`RESTRICTED_DIR_ABSENT=True`, `RESTRICTED_RESIDUE_COUNT=0`,
`PILOT_ROOT_RESIDUE_OK=True` (`<pilot-root>` altında yalnız `<repo-root>`,
`<container-temp>` ve `<intake-dir>` kalır), `EXTERNAL_ROOT_RESIDUE_OK=True`
(`<external-root>` altında **tam olarak** `<evidence-dir>` kalır: sıralı ad
kümesi birebir eşit; eksik `<evidence-dir>` de `False` verir —
`13f19d0`'daki güç, remediasyon turu 1 H-2) ve üç
`git status` çıktısı **boş**. Aksi: tekrar veya doğaçlama düzeltme yok,
**DUR** (H46).

#### 28.3.3 Kapsayıcı imhası ve anahtar imhası

YENİ (revizyon; form v5 F4; kullanıcı kararı D12). §28.3.1 ve §28.3.2
tamamlandıktan, §28.6 geçici kopyaları ele alındıktan ve kapanış
postcondition'larından kapsayıcıya bağlı olanlar (§30/2–3: klondaki
`git status` satırları) ölçüldükten **sonra** uygulanır. Kapsayıcı
silindikten sonra klondaki repo durumu bir daha ölçülemez.

1. **Kapatma.** Operatör içerik oturumunu kapatır; kapsayıcıdaki hiçbir
   dosyanın açık olmadığını doğrular ve VeraCrypt arayüzünde kapsayıcıyı
   ayırır (dismount). Evidence: `CONTAINER_DISMOUNTED=True`.
2. **Guard.** Yeni bir oturumda, kapsayıcı ayrıldıktan sonra. Bu oturumda
   yalnız §13.8 **ortak yardımcıları** (`Test-PilotNoReparse`,
   `Test-PilotLeafFile`, `Test-PilotOverlap`, `Test-PilotResolved`)
   tanımlanır; kapsayıcı ayrıldığı için §13.8 kapsayıcı kapıları bu
   oturumda **çalıştırılmaz** (çalıştırılırsa beklendiği gibi `STOP` verir):

```powershell
$cfGuard = $false
try { $cf = "<container-file>"; $cfGuard = (-not (Test-Path -LiteralPath "<container-root>")) -and (Test-PilotLeafFile $cf) -and ((Get-Item -LiteralPath $cf -Force).Length -eq [long]'<container-file-bytes>'); foreach ($p in @("<source-repo-root>", "<repo-root>", "<external-root>", "<evidence-dir>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $cf $p)) { $cfGuard = $false } } } catch { $cfGuard = $false }
if ($cfGuard -eq $true) { "CONTAINER_FILE_GUARD=PASS" } else { "STOP CONTAINER_FILE_GUARD=FAIL" }
```

   `<container-file-bytes>`, §4.4/2'de kaydedilen `CONTAINER_FILE_BYTES`
   değeridir; tek tırnak içinde yalnız rakamlarla yazılır ve `[long]` ile
   dönüştürülür (değiştirilmemiş veya rakam dışı bir değer hata verir ve
   guard `FAIL` olur). Beklenen: `CONTAINER_FILE_GUARD=PASS`; aksi **DUR**
   (H46).
3. **Silme.** Guard PASS ise ve **bu hedef için silme anında ayrı
   `REAL_ACTION_APPROVED`** alındıysa, aynı oturumda, **bir kez** (geri
   dönüşüm kutusu kullanılmaz):

```powershell
if ($cfGuard -eq $true) { try { Remove-Item -LiteralPath $cf -Force -ErrorAction Stop; "CONTAINER_DELETE_RESULT=COMPLETED" } catch { "STOP CONTAINER_DELETE_RESULT=FAILED" } } else { "STOP CONTAINER_FILE_GUARD=FAIL" }
"CONTAINER_FILE_ABSENT=$(-not (Test-Path -LiteralPath $cf))"
Remove-Variable cf, cfGuard, p -ErrorAction SilentlyContinue
```

   Beklenen: `CONTAINER_DELETE_RESULT=COMPLETED` ve
   `CONTAINER_FILE_ABSENT=True`; aksi tekrar yok, **DUR** (H46).
4. **Anahtar imhası.** Operatör tek kullanımlık parolanın/anahtarın kâğıt
   veya çevrimdışı kaydını imha eder ve başka bir kopyası olmadığını
   beyan eder. Evidence: `CONTAINER_KEY_DESTROYED=True` ve zaman. Anahtar
   imha edilmeden kapsayıcı silmesi tamamlanmış **sayılmaz** (Y6).
5. Kapsayıcı dosyası SSD'de standart silmeyle kaldırıldığı için şifreli
   baytlar fiziksel olarak kalabilir; gizlilik, anahtarın imhasına
   dayanır (§23, §32/11).

### 28.4 Silinmeyenler (Form F6)

Kaynak: Temel L3526–L3532. Sapma yok (form bağı eklendi).

DB journal satırları (`generation.fact_manual` dahil), `mutation.mutation_resources`
satırı, assignment satırı ve security event'ler **silinmez**; uygulama
rollerinin bu tablolarda `DELETE` yetkisi yoktur ve bu izler kasıtlıdır.
Metadata manifestleri, evidence kayıtları ve özet de kalır. Bu izlerin
kalması Form **F6**'da "Kabul" ile kabul edilmiş olmalıdır.

### 28.5 Şifreli arşiv (yalnız F2 arşiv ve F3 eksiksizse)

Kaynak: Temel L3534–L3597. **Sapma:** kapsam iki manifestle sınırlı;
arşiv kapısı, korunan listesinde `GetTempPath()` yerine
`<system-temp-user>`, `<system-temp-windows>` ve `<container-temp>`
kullanılması dışında (remediasyon turu 1, H-1) **birebirdir**.

Arşivlemeden önce, aynı oturumda `<archive-dir>` denetlenir:

```powershell
$aDir = "<archive-dir>"
$aParent = "<archive-parent>"
$aOk = $false
$aPrevEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Stop'
    $a = (Test-PilotResolved $aDir) -and (Test-PilotResolved $aParent) -and ($aParent.TrimEnd('\') -ne [System.IO.Path]::GetPathRoot($aParent).TrimEnd('\')) -and (Test-Path -LiteralPath $aParent -PathType Container) -and (Test-PilotNoReparse $aParent) -and ([System.IO.Path]::GetDirectoryName($aDir.TrimEnd('\')) -eq $aParent.TrimEnd('\'))
    if ($a) { foreach ($p in @("<repo-root>", "<case-root>", "<external-root>", "<system-temp-user>", "<system-temp-windows>", "<container-temp>", "<python-runtime-root>", "<pg-bin-dir>")) { if (-not (Test-PilotResolved $p) -or (Test-PilotOverlap $aDir $p)) { $a = $false } } }
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
  kapısı, silme günü kapsayıcı doğrulaması ve §28.3.3 dahil); "korunsun"
  ise §28.1/5 uygulanır.
- Form v5'te F2 = "Silinsin"dir; bu bölüm ancak F2 değişirse uygulanır.

### 28.6 Geçici kopyalar (Form F1)

Kaynak: Temel L3599–L3603. **Sapma:** Form F1 süresi bağlandı;
**revizyon (§34):** kopyalar yalnız kapsayıcı içinde olabilir; F1 süresi
içinde kapsayıcı imhası seçeneği eklendi.

Pilotta oluşmuş olabilecek ikinci kopyalar — `<intake-dir>` içindeki
aktarım dosyası (`transfer.7z`) ve açılmış içerik (`x`), `<container-temp>`
içindeki dosyalar ve `pdftotext`'in olası ara dosyaları — **yalnız
kapsayıcı içinde** bulunabilir ve Form **F1**'deki süre içinde (§23'teki
"iş bitince" anından itibaren) silinir. F1 süresi içinde iki yoldan biri
tamamlanır: (a) aşağıdaki prosedürle tek tek silme, veya (b) kapsayıcı
imhasının (§28.3.3, anahtar imhası dahil) F1 süresi içinde tamamlanması.
Bu adım (zincir adım 27) revoke, manifest ve case silmesini (24–26)
**beklemez** (§2.1 sıra istisnaları); (b) yolu ancak 24–26 da F1 süresi
içinde tamamlanırsa kullanılabilir.

**Komut ve guard tanımlanmamıştır (bilinçli; §32).** Bu kopyaların yeri ve
adları önceden bilinmez ve adları gerçek içerik (ör. taraf adı) taşıyabilir;
§28.3 desenindeki gibi exact-path bir guard, bu adları komut satırına veya
evidence'a yazmayı gerektirirdi (§1.5, §4.2/8). Bu yüzden bu runbook bu
silmeler için PowerShell komutu veya mekanik guard **vermez**. Yerine
şu prosedür bağlayıcıdır:

1. **Listeleme.** Operatör kopyaları teslim ve metin çıkarma sırasında,
   oluştukları anda, repo dışında ve evidence dışında, yalnız kendisinin
   ve avukatın gördüğü bir **kâğıt veya çevrimdışı** listeye yazar (yer,
   tür, kapsayıcı içinde olup olmadığı; içerik değil). Evidence'a yalnız
   kopya **sayısı** girer.
2. **Ortam koşulu (F4 kapsayıcı yöntemi).** Her kopya `<pilot-root>`
   altında, yani kapsayıcı içinde bulunmalıdır. Bu koşul kopya **oluştuğu
   anda** (madde 1) değerlendirilir; kapsayıcı dışında oluşmuş tek bir
   kopya o anda **DUR**'dur (H40, Y6) — zincir adım 27'ye bırakılmaz.
   Kapsayıcı dışındaki bir kopya bu yöntemle "silinmiş" sayılmaz; dosya
   avukatına bildirilir ve yöntemi avukatın yazılı kararıyla belirlenir.
3. **Silme yöntemi ((a) yolu).** Her kopya, silme günü §4.4/7 kapsayıcı
   doğrulamasından sonra, ayrı `REAL_ACTION_APPROVED` ile, tek tek, **geri
   dönüşüm kutusu kullanılmadan** silinir (Dosya Gezgini'nde Shift+Delete
   veya eşdeğeri). Klasör toplu silinmez; `<repo-root>`, `<external-root>`,
   `<evidence-dir>`, `<restricted-dir>` ve `<archive-dir>` altında hiçbir
   şey bu yolla silinmez.
4. **Kontrol.** Operatör listedeki her kopyanın artık bulunmadığını ve
   geri dönüşüm kutusunda olmadığını ekranda doğrular. Avukat listeyi ve
   doğrulamayı yazılı olarak onaylar; evidence'a yalnız onayın hash'i
   girer.

Evidence'a yalnız kopya **sayısı**, silinme zamanı, kullanılan yol
(`TEMP_COPIES_PATH=INDIVIDUAL` veya `=CONTAINER_DESTRUCTION`),
`TEMP_COPIES_INSIDE_CONTAINER=True/False` ve
`TEMP_COPIES_DELETED_WITHIN_F1=True/False` yazılır. Süre aşılırsa veya
madde 1–4'ten biri sağlanmazsa: **DUR** (Y6) ve olay dosya avukatına
bildirilir.

### 28.7 İmha kaydı (Form F5)

YENİ. Her silme (case dizini, `<restricted-dir>`, §28.6 kopyaları,
kapsayıcı dosyası ve anahtar imhası) için bir imha kaydı tutulur: **ne**
silindi (kişisel veri içermeyen tanım ve manifest hash'i), **hangi
yöntemle** (F4), **ne zaman**, **kim tarafından**. Form v5 F5'e göre kayıt
**operatör** tarafından en az **3 yıl** saklanır ve bir kopyası **dosya
avukatına** verilir (kopyanın verildiği evidence'a
`DELETION_RECORD_COPY_TO_FILE_LAWYER=True` olarak yazılır); kayıt kişisel
veri ve belge metni içermez ve repo'ya girmez. Evidence'a yalnız kaydın SHA-256'sı ve
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
şifrelemesi ve form hash satırı (13) eklendi; revizyonda (§34) 11–13
kapsayıcı, Ek 2/F5 kopyası ve UDF imza kayıtlarına çevrildi.

Hepsi mekanik olarak ölçülür ve evidence'a yazılır:

1. `data/cases/<case-id>` mevcut değil: §28.3.1'de
   `CASE_DELETE_RESULT=COMPLETED` ve `CASE_DIR_ABSENT=True`.
2. `git status --ignored --porcelain -- data/cases` boş;
   `git status --porcelain -- data/cases/case_0001` boş.
3. `git status --porcelain=v1 --untracked-files=all` boş; HEAD başlangıçtaki
   commit. 2. ve 3. koşullar kapsayıcıdaki klonda, kapsayıcı imhasından
   **önce** ölçülür (§28.3.3); imhadan sonra yeniden ölçülemez.
4. `case:<case-id>` için aktif assignment **0**; journal'da `prepared`,
   `executing` veya `reconciliation_required` satırı **0**.
5. Yeni journal satırları yalnız §26.3'teki yedi aile için ve `completed`
   durumunda (yalnız §14.6 yolundan geçildiyse ayrıca kayda geçirilmiş
   `failed` satırlar).
6. §14.7 SQL'i: `generation.fact_extraction` satırı **0**.
7. Evidence dizininde gerçek içerik, rapor metni, gerçek tarih veya sayfa
   numarası yok; özet, `restricted-allowed-files.txt`,
   `restricted-allowed-files.sha256.txt`, `intake-hashes.tsv`,
   `manual-input-r*.sha256.txt`, `technical-record.txt`,
   `system-temp.txt` ve iki kapanış manifesti mevcut.
8. `<restricted-dir>` mevcut değil: `RESTRICTED_DIR_ABSENT=True`,
   `RESTRICTED_RESIDUE_COUNT=0`, `PILOT_ROOT_RESIDUE_OK=True`,
   `EXTERNAL_ROOT_RESIDUE_OK=True` (`<external-root>` altında **tam
   olarak** `<evidence-dir>`; §28.3.2).
9. `PENDING_MATCH` (§18.3) ve `MATCH` (§20).
10. **Ağ işlemleri yalnız §21'deki beş sınıftandır:** (1) runbook
    komutları — **dış ağ işlemi sıfır**; (2) dosya aktarımı — zincir
    içindeki tek dosya aktarımı E2 aktarım dosyasının içeri yönlü
    alınmasıdır (`E2_INBOUND_TRANSFER_RECEIVED=True`); (3) ön-pencere
    insan ağ işlemleri — yalnız §21/3'te sayılanlar, her biri onaylı
    (`PRE_PILOT_NETWORK_ACTION` satırları); (4) karar kanalı — sayılı,
    hash'li ve içeriksiz (her biri için `INBOUND_DECISION_RECEIVED` /
    `OUTBOUND_NOTICE_SENT` satırı, `seq` ardışık; §21/4); (5) sesli
    görüşme — cihaz dışı (`E2_KEY_CHANNEL=VOICE_CALL` ve varsa
    `INCIDENT_NOTICE_CHANNEL=VOICE_CALL`; parola veya türevi yok; §21/5).
    §21 tablosunun bütün satırları beklenen değerde; §13.6 kapanış
    taraması üç kapsamda 0.
11. İçerik penceresi kapandı: gerçek verinin yerel çalışma kopyası ve
    geçici kopyalar artık diskte değil (`TEMP_COPIES_DELETED_WITHIN_F1=True`);
    kapsayıcı imha edildi (`CONTAINER_FILE_ABSENT=True`,
    `CONTAINER_KEY_DESTROYED=True`, §28.3.3); §4.3 kanal kapısı kaydı
    pencere boyunca kesintisiz `AI_CONTENT_CHANNELS_CLOSED=True` gösteriyor.
12. İmha kaydı yazıldı (`DELETION_RECORD_WRITTEN=True`, §28.7) ve bir
    kopyası dosya avukatına verildi
    (`DELETION_RECORD_COPY_TO_FILE_LAWYER=True`).
13. Her silme günü için §4.4/7 kapsayıcı doğrulaması evidence'ta
    (`CONTAINER_VERIFIED=True`; her harici sürücü için
    `EXTERNAL_DISK_ENCRYPTED=False` ve `EXTERNAL_DISK_REMOVED=True`; her
    yerleşik optik sürücü için `OPTICAL_MEDIA_LOADED=False`, revizyon 2);
    E2 taşıyıcısı için `E2_CARRIER_KIND=ENCRYPTED_TRANSFER`,
    `E2_CARRIER_ENCRYPTED=True` (başka taşıyıcı türü yoktur, §6.4) ve
    alınan her parola için `E2_PASSWORD_PAPER_DESTROYED=True` (`reason`
    ile; revizyon 2); F1
    kopyaları için `TEMP_COPIES_INSIDE_CONTAINER=True`; her e-imzalı birim
    için `UDF_SIGNATURE_VALID=True`; form, G bölümü ve eklerin hash'lerinin
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

1. **Prova durumu.** `13f19d0` sürümü sentetik olarak prova edildi (§0;
   prova ae129016, inceleme `REHEARSAL_EVIDENCE_VERIFIED`). Revizyon 1'in
   (`4f5c37e`) yeniden yazılan ve yeni eklenen blokları delta provasında
   (e11bab73) prova edildi (inceleme `REHEARSAL_EVIDENCE_VERIFIED`; §0).
   Revizyon 2'de (§34.8) değişen ve yeni eklenen bloklar delta2
   provasında (709b329c) ölçüldü; prova `STOPPED_ON_UNEXPECTED_RESULT` ile
   bitti (inceleme `REHEARSAL_EVIDENCE_VERIFIED`; §0) ve bulguları revizyon
   3'e işlendi. Revizyon 3'te (§34.9) değişen ve yeni eklenen bloklar (N4,
   N16, N17, Ek R3) delta3 provasında kısmen ölçüldü: Faz A (86c4a7da)
   A.10'da N105 hatasıyla durdu (revizyon 4, §34.10); revizyon 4 kökü
   d9d67b7d'de Faz A'nın ajan ölçümleri (A.0–A.16; kit kurulumu, N4 kültür
   ölçümü, N16'nın on sentetik arşivde ve bekçi testinde ölçümü, yükleme
   ve kilit negatifleri) geçti — A.16 kapatma ön ölçümü ancak üç ek
   turla (kanıt incelemesi M2); insan penceresi 1'de `a2` ve `a3` PASS
   verdi, `a4` `STOP KIT_TEMP_IN_CONTAINER=False` ile kilitlendi (TEMP
   yönlendirmesi atlandı); pencere 2 ve 3 açılmadı; Faz B yalnız kayıt
   amaçlı yürüdü ve prova `STOPPED_ON_UNEXPECTED_RESULT` ile bitti
   (inceleme `REHEARSAL_EVIDENCE_VERIFIED`; §0). Bulgular revizyon 5'e
   (§34.11) işlendi. İnsan tarafında hiç ölçülmemiş adımlar (`a5`–`a9`,
   parola aktarımı, kasıtlı DUR ve silme oturumu; kanıt incelemesinin 5B
   listesi) ve revizyon 5'in değişen/yeni blokları (N105, N107, N108,
   N114–N116) bir sonraki delta provası olmadan gerçek veriyle
   kullanılamaz; provada yazıldığı gibi çalışmayan bir komut runbook
   düzeltmesi ve yeniden inceleme gerektirir. Prova veritabanı kararı kapanmıştır (§1.6/3).
   Runtime paket kümesi karşılaştırmasının komutu §13.3'te sabitlenmiştir.
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
6. **Reconciliation operatörü pilot kümesinde yalnız sentetik provada
   çalıştırıldı** (`13f19d0` provası: kasıtlı writer hatası →
   `reconciliation_required` → `failed` → `--attempt 2` `completed`).
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
11. **Silme yöntemi:** tanımlı tek yöntem Form F4 "Şifreli kapsayıcı
    yöntemi"dir (§28.3): kapsayıcı içinde guard'lı `Remove-Item`, ardından
    kapsayıcı dosyasının geri dönüşüm kutusu kullanılmadan silinmesi ve
    tek kullanımlık anahtarın imhası. Hiçbir adım içeriğin üzerine
    **yazmaz**; gizlilik verinin yalnız kapsayıcı içinde bulunmasına ve
    anahtarın imhasına dayanır (§23). Anahtar ele geçirilirse veya kapsayıcı
    dışında bir kopya oluşmuşsa (sayfa dosyası, hazırda bekletme dosyası,
    arama indeksi, antivirüs karantinası; madde 18, 25) veri
    kurtarılabilir. Tam disk şifrelemesi yolları bu revizyonda
    kaldırılmıştır. Şifreli arşiv aracı tanımlı değildir (§28.5).
12. **Kapsayıcı doğrulaması** (Form E1) VeraCrypt arayüzünün ekran
    okumasına ve §13.8'deki yol/dosya sistemi ölçümlerine dayanır; VeraCrypt
    durumunu okuyan bir komut tanımlanmamıştır. Ekran okuması yanlış
    okunabilir veya arayüz gerçeği yansıtmayabilir; bu doğrulama
    kriptografik bir kanıt değildir. Bu cihaz Windows 10 **Home**'dur;
    kapsayıcı yöntemi Pro yükseltmesi gerektirmez. Kapsayıcı yolu
    kullanılamazsa (araç kurulamıyor, sürücü harfine bağlanamıyor, NTFS
    değil) pilot bu cihazda yapılamaz. Harici diskin "fiziksel olarak
    çıkarılmış" olması yalnız operatörün gözlemine ve beyanına dayanır;
    pencere içinde yeniden veya yeni takılması mekanik olarak izlenmez
    (§4.2/10). E2 aktarım dosyasının şifreli olduğu, 7z'nin parola
    istemesinin ekran gözlemiyle kaydedilir (§6.4).
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
20. Avukat formu v5'in A–F + I birimi protokol inceleyicisi tarafından
    doldurulup e-imzalanmıştır (§0); G bölümü, Ek 1'in dosyaya özgü hâli
    ve iki imzalı Ek 2 henüz **yoktur** (gerçek dosya seçilmedi). Her form
    kapısı cevabı varsaymadan DUR olarak yazılmıştır (§6.1).
21. **Komut satırında mutlak yollar ve `<attestation-ref>` geçer** (§1.5):
    belge içeriği değildir, ama mutlak yollar Windows kullanıcı profil
    adını taşıyabilir; süreç-oluşturma komut satırı denetimi açıksa bu ad
    kayda geçer (§4.2/9). Bu runbook bunu önlemez; yalnız kullanıcı
    profil adının kişisel veri taşımadığı bir hesapla çalışılmasını önerir.
22. **F1 geçici kopyaları için komut ve exact-path guard yoktur**
    (§28.6). Silme, operatörün çevrimdışı listesine ve ekran
    doğrulamasına ya da kapsayıcı imhasına (§28.3.3) dayanır; tek tek
    silme yolunda mekanik bir "tümü silindi" kanıtı üretilmez. Kapsayıcı
    dışında, listeye girmemiş bir kopya (ör. bir uygulamanın kendi
    önbelleği) tespit edilemez.
23. **İmza ve tarih doğrulaması mekanik değildir** (§6.6): operatör imzanın
    biçimini (taranmış PDF / e-imza; UDF'de `sign.sgn`) ve tarih sırasını
    denetler; imzanın kime ait olduğunu veya tarihlerin gerçekliğini
    doğrulamaz. E-imza geçerliliği yalnız UYAP editörünün gösterimiyle
    (`UDF_SIGNATURE_VALID`) kaydedilir; sertifika zinciri ve iptal durumu
    bu runbook tarafından bağımsız doğrulanmaz.
24. **Avukat kararı ile girdi sürümü arasındaki bağ 12 hex karakterlik
    önekle kurulur** (§14.3): önek, aynı sürüm numarasında kazara değişimi
    yakalar; kriptografik bir imza değildir.
25. **Kapsayıcı dışında kalabilen işletim sistemi izleri** (kullanıcı
    kararları D9, D9a). Sayfa dosyası, hazırda bekletme dosyası, Windows
    Search indeksi ve antivirüs karantinası, şifresiz sistem sürücüsünde
    gerçek içerik parçaları taşıyabilir; bu, formdaki "kapsayıcı dışına
    hiçbir şey yazılmaz" ifadesiyle çelişebilir. Bu runbook bunları
    denetleyemez ve kapatmaz. Çelişki §1.6/5'teki yazılı bildirim ve dosya
    avukatının `LEGAL_APPROVED` cevabıyla kapılanır; bu bir hukuki kapıdır,
    mühendislik çözümü değildir.
26. **Pilot kümesinin günlük dosyası (ertelendi; kullanıcı kararı D1).**
    Adım 8'in kalıcı pilot kümesi (`<pilot-port>`) `--log=<DATA_DIR>\server.log` ile
    başlatılır; günlük dosyası veri klasörünün içindedir
    (`docs/operations/local-postgresql-iam-adoption.md` §D). O runbook
    LOCKED'dır ve günlük yerleşimini değiştirmeyi Row 19D / ayrı bir
    operasyon tasarımına bırakır; bu revizyon onu **değiştirmez**. Günlük
    yalnız opak kimlik ve sorgu metni taşıyabilir; gerçek içerik
    taşımaz (§10.3).
27. **ACL ölçümü yalnız `<pilot-root>`'u kapsar** (§4.4/4). Kapsayıcı
    biriminin kökü ve kapsayıcı dosyasının bulunduğu dizin daha geniş
    yetkilere sahip olabilir; içerik yalnız `<pilot-root>` altında
    bulunduğu için ölçüm oraya bağlanmıştır. Yönetici hakları olan bir
    hesap ACL'den bağımsız olarak erişebilir.
28. **Araç kurulumları ve UYAP editörü dış ağ işlemleridir** (§21): zincir
    dışında, içerik penceresinden önce, ayrı onayla yapılır; "sıfır dış ağ
    işlemi" sayımına girmez ve gerçek içerik taşımaz.
29. **Ajan kökenli oturum kontrolü bir kod guard'ı değildir** (kullanıcı
    kararı K6). §13.6'daki `CLAUDE.*` ad taraması yalnız bilinen ortam
    değişkenlerini görür; başka bir ajan aracının iz bırakmayan bir
    oturumunu tespit edemez. Asıl kapı insan-only oturum beyanıdır (§4.3 a).
30. **7z yöntem ölçümünün sınırı** (§6.4). `SEVENZIP_ALL_ENTRIES_7ZAES`
    yalnız 7z'nin `l -slt` çıktısında raporladığı arşiv türünü, `Encrypted`
    bayrağını ve yöntem adını (`7zAES`) okur. Parolanın gücünü, anahtar
    türetme parametrelerini, arşivin gönderen tarafta veya kanalda başka
    bir kopyasının bulunup bulunmadığını ve başlıkların şifreli olup
    olmadığını (girdi adlarının kanalda görünürlüğü) doğrulamaz. Revizyon
    2'den itibaren (R-D-7ZPROMPT, K-R2-1) listelemede parola istenmez
    (standart girdi boş bağlanır) ve başlıkları şifreli bir arşiv
    fail-closed `STOP` verir; kabul edilen biçim başlıkları açık arşiv
    olduğundan **girdi adları aktarım kanalında görünür** — bu yüzden
    gönderen kuralı nötr dosya adı ister (§6.4). Nötr adın gerçekten
    kişisel veri taşımadığı gönderenin beyanına dayanır; mekanik olarak
    doğrulanmaz. Revizyon 3'ten itibaren listeleme konsolsuz, standart
    girdisi kapalı ve 10 saniyelik bekçiyle yapılır; bekçinin ve kapalı
    girdinin insan konsolundaki davranışı ile başlıkları şifreli arşivde
    7z'nin kesin çıkış kodu delta3'te ölçülür ("Break signaled"
    hipotezi HK-1 dahil; 7-Zip kaynak okuması bu runbook'ta doğrulanmış
    sayılmaz). Stderr boolean'ları 7-Zip'in İngilizce ileti metnine
    dayanır; sürüm değişirse ölçülmeden güvenilmez. Klasör tanıma, 7-Zip'in `Attributes` satırındaki büyük
    `D` karakterine ve boyut-sıfır koşuluna dayanır (7-Zip 26.04 7z
    klasörleri için `Folder = +` basmaz; delta2 D1.3); büyük `D`'nin
    yalnız dizin bitine karşılık geldiği 7-Zip kaynağıyla bu runbook'ta
    doğrulanmamıştır (boyut-sıfır koşulu bu belirsizliği güvenli tarafta
    tutar). Bekçi yalnız 7z'nin çıkışını ve çıktısının okunmasını
    sınırlar; ekran donması (PowerShell'in ekrana yazarken bloklanması)
    satır başına damga olmadığından yalnız adım düzeyi damgalardan
    (`STARTED_AT`, `LIST_CALL_AT`, `LIST_RETURN_AT`, `ENDED_AT`) dolaylı
    çıkarılır (R3 düzeltme turu; inceleme L-1).
31. **D9 bildirim listesinde olmayan işletim sistemi izleri.** §1.6/5 ve
    §4.4/8'deki liste sayfa dosyası, hazırda bekletme dosyası, Windows
    Search indeksi ve antivirüs karantinasıyla sınırlıdır. Dosya
    Gezgini'nin küçük resim önbelleği (thumbnail cache) ve Recent/jump
    list kayıtları (son açılan dosya ve klasör adları) da şifresiz sistem
    sürücüsünde kalabilir; bu runbook bunları denetlemez ve D9 bildirimi
    bunları ayrıca anmaz.
32. **§11.2/2 "elle kopyalama" yöntemi tanımlı değildir.** Orijinal
    belgenin `<intake-dir>\x` altından opak `<file-name>` adıyla case
    dizinine kopyalanmasının aracı (Dosya Gezgini veya bir komut)
    yazılmamıştır. Kaynak dosya adı kişisel veri taşıyabileceği için bir
    komutun argümanına yazılması §1.5 ile çelişebilir; Dosya Gezgini
    kullanımı madde 31'deki izleri bırakabilir.
33. **§32/26'daki sunucu günlüğü iddiası ölçülmemiştir.** "Günlük gerçek
    içerik taşımaz" ifadesi kaynak okumasına dayanır; pilot kümesinin
    `server.log` dosyası bu runbook tarafından taranmaz veya ölçülmez.
34. **Form hash uyuşmazlığının iki kodu vardır.** §6.6/9 ölçülen
    `FORM_HASH unit=AF seq=1` §0'daki değerle uyuşmadığında H16'yı, §25.1
    Y1 ise aynı durumu Y1 olarak anar. İkisi de **DUR**'dur; evidence'ta
    hangi kodun yazılacağı tek bir koda bağlanmamıştır.
35. **AF birimi boş G, Ek 1 ve Ek 2 şablonlarını içerir.** §0'da hash'i
    sabitlenen form v5 UDF dosyası (A–F + I birimi) G bölümünün ve iki ekin
    **boş** şablonlarını da taşır. Bu boş şablonlar G veya `ATT<k>` birimi
    **değildir**; G, Ek 1 ve Ek 2 ayrı, doldurulmuş ve imzalı birimler
    olarak alınır (§6.6/2).
36. **§4.2/9 bilgi satırı bloğu önceki bloğa bağlıdır.**
    `CMDLINE_AUDIT_VALUE` bloğu, aynı oturumda hemen önceki blokta
    tanımlanan `$audit` değişkenini kullanır; tek başına çalıştırılırsa
    `$audit` tanımsızdır ve satır doğru değeri basmaz.
37. **`TWO_PERSON_CONTROL` sırası.** Kayıt zincir adım 2'de form B4'e göre
    yazılır; dosya avukatının kimliği ise ancak zincir adım 3'te (G10)
    belli olur. Adım 2'deki `SEPARATE` kaydı, adım 3'te G10'daki kişinin
    operatörden gerçekten ayrı olduğunun mekanik kanıtı değildir.
38. **Karar kanalının içeriksizliği beyana dayanır** (§21/4). Gelen
    kararların ve giden bildirimlerin dava içeriği ve kişisel veri
    taşımadığı operatörün ve dosya avukatının beyanıdır; mesaj metni
    mekanik olarak taranmaz. Kanalın kendisi (e-posta, mesajlaşma) bu
    runbook'un dışında bir sistemdir ve onun saklama davranışı ölçülmez.
39. **İnsan adım kitinin sınırları (revizyon 3; Ek R3).** (a) Bir adım
    çalışırken Ctrl+C basılırsa adım yarıda kalır; kayıtta `STEP_RESULT`
    satırı olmaz ve sonraki adımlar sıra kapısı yüzünden çalışmaz, ama
    `DUR.txt` **yazılmayabilir**; bu durum yalnız eksik `STEP_RESULT`
    satırından anlaşılır. `a5` sırasında Ctrl+C basılırsa konsolsuz 7z
    Ctrl+C'yi almaz ve bekçi de çalışmadığı için süreç yetim kalabilir;
    kayıtta `LIST_RETURN_AT` ve `STEP_RESULT` olmaz ve böyle bir süreç
    ancak sonraki bir `SEVENZIP_PROC_COUNT_BEFORE` ölçümünde görünür
    (R3 düzeltme turu; inceleme L-4). (b) Kit bütünlüğü yükleme ve her adım anında
    `pins.txt`'ye göre denetlenir; `pins.txt`'nin kendisi yalnız
    `kit-build.txt` ve her oturumun `KIT_PINS_SHA256` satırıyla
    sabitlenir — aynı kullanıcı hesabıyla iki dosyayı birlikte
    değiştirebilen bir süreç mekanik olarak dışlanmaz (kanal kapısı bu
    yüzden ilk adımdır). (c) Pencerenin Çalıştır (Win+R) kutusundan
    açılması komutu (yol dahil, içerik hariç) Windows'un son komutlar
    listesine yazar. (d) E/H cevapları operatörün ekran gözlemidir; kit
    onları doğrulayamaz. (e) Caps Lock denetimden sonra, yazma sırasında
    değiştirilirse yakalanmaz; ek deneme kuralı bu yüzden korunur. (f)
    `ac.ps1` yüklenemezse `a8`/`a9` da yoktur; kâğıt imhası ve saat
    kâğıda not edilir ve sonraki ajan oturumunda beyan olarak kayda
    geçer. (g) Kit modunda E2 adımlarının (`a4`–`a7`) tamamı aynı içerik
    oturumunda yürür; pencere kapanırsa zincir yeni oturumda devam
    etmez (fail-closed). (h) Adım bittikten sonra yazılmaya devam edilen
    tuşlar istem satırında ekranda görünebilir; diske/geçmişe gitmez; tek
    sayfadaki "istem yoksa hiçbir şey yazmayın" kuralı (Ek R3/5, madde 7:
    ekranda 7z'nin `Enter password` istemi yoksa hiçbir şey yazılmaz ve
    Enter'a basılmaz; kitin E/H soruları hariç — revizyon 5, final-check
    Obs-1) bunun içindir (R3 son dar düzeltme; inceleme Obs-7;
    kullanıcı kararı Obs-7=ii). (i) Değişken adı çakışma denetimi (Ek
    R3/7; revizyon 5) statiktir: yalnız adlandırılmış dot-source
    birleşimlerini modeller; `& $sb` ile çalışan bir betiğin çağıranın
    yerel değişkenlerini dinamik okuması ve `[scriptblock]::Create`
    sonrası oluşan başka kapsam ilişkileri denetlenmez; kit penceresinin
    genel kapsamında elle çalıştırılan madde 3 blokları taranmaz ve
    kapsamsız `Remove-Variable`'ın üst (genel olmayan) kapsamdaki aynı
    adlı değişkeni silebilmesi modellenmez (Ek R3/7 sınır paragrafı;
    revizyon 5 düzeltme turu, bağımsız inceleme L5). (j) Kitin TEMP
    yönlendirmesi (revizyon 5) yalnız aktarım (E2) günü `a4`'tedir; E2
    dışındaki içerik oturumlarında yönlendirme §4.4/5 N13 ile elle
    yapılır ve o yolda kit TEMP'i denetlemez (§2.1 zincir adım 4 kuralı
    aynen geçerlidir). (k) DUR kuralı (Ek R3/4 kural 1) bir talimattır;
    kit `a9`'un yazılmasını, pencerenin kapatılmasını veya hiçbir yapay
    zekâ aracının açılmamasını zorlayamaz; `a9`'un yokluğu yalnız sonraki
    ajan oturumunda kayıttan anlaşılır ve DUR sonrası kanal kapalılığının
    kapanış kanıtı (`CLOSING_SCAN_OK`) o zaman yoktur (delta3 bulgusu H1).
    (l) `a4`, teknik kaydın bu kit oturumunda yazıldığını denetlemez
    (revizyon 5 düzeltme turu; kullanıcı kararı L9; bağımsız inceleme
    L9). Teknik kayıt §4.4/6 gereği zincir adım 4'te **bir kez**,
    exclusive-create ile yazılır, yeniden üretilmez ve üzerine yazılmaz;
    her kullanımda yeniden yapılan yalnız araç manifesti doğrulamasıdır
    (N15; `a4` bunu kayıt içinde yapar). Kaydın bu pencereden önce
    yazılmış olması bu yüzden meşrudur; oturum zamanına bağlı bir denetim,
    önceki pencerede yazılmış kayıtla devam etmesi gereken bir `a4`'ü
    düzeltilemez biçimde reddederdi. Sonuç: `a4` PASS, bu pencerede
    madde 3'ün (altı sınıf beyanı ve `AI_CONTENT_CHANNELS_CLOSED=True`,
    oturum başı kapsayıcı doğrulaması `CONTAINER_VERIFIED=True`, yol
    kapısı `PATH_OK=container-temp`) yapıldığını göstermez. Bunlar
    revizyon 4'te de mekanik olarak denetlenmiyordu; ama madde 3'ü atlayan
    operatörü TEMP adımının kalıcı kilidi dolaylı olarak durduruyordu
    (delta3 H2) ve bu dolaylı kilit artık yoktur. Hafifletici: `a3` PASS
    iletisi madde 3'ü açıkça adlandırır; madde 3'ün yardımsız yapılması
    bir sonraki delta provasında gösterilir (§34.4). Tek sayfa madde 3
    bunu açıkça söyler (tek sayfa netleştirmesi, `USER_DECISION
    at=2026-10-18T14:45+03:00`): teknik kayıt bloğu YALNIZ
    `technical-record.txt` yoksa (ilk içerik penceresi) çalıştırılır,
    varsa atlanır (§4.4/6); kayıt varken §4.4/6 bloğu yeniden çalıştırılırsa
    exclusive-create nedeniyle `STOP TECHNICAL_RECORD=FAIL` verir.
40. **Pilot öncesi bilgisayar hazırlığının geri alınması (revizyon 5;
    kullanıcı kararı D3; delta3 bulgusu F-B9).** §4.3 (a)'daki bir
    kerelik hazırlık (başlangıç öğeleri, OneDrive'ın üç zamanlanmış
    görevi) pilot veya prova bittikten sonra kendiliğinden geri
    alınmaz; yeniden etkinleştirme ayrı bir kullanıcı kararıdır ve
    yapılırsa sonraki her içerik penceresinden önce hazırlık yeniden
    yapılır. Delta3 provasından kalan devre dışı görevler bu cihazda
    hâlâ devre dışıdır (findings F-B9; bu revizyonda ölçülmedi).

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
   tanımsızsa veri silinemez hâlde kalacağı için. Form v5 ile yalnız
   "Şifreli kapsayıcı yöntemi" yürütülebilirdir ve E1 = "Tek dosyalık
   pilot alternatifi" + yürütme günü kapsayıcı doğrulamasına bağlıdır
   (kullanıcı kararları 2026-10-08, K3, D15).
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
12. **Kapsayıcı yöntemi** (§4.2/10, §4.4): form v5 E1/F4 tam disk
    şifrelemesi yerine yerel şifreli kapsayıcıyı seçtiği için üç tam disk
    şifrelemesi yolu kaldırıldı (K3, D15). Araç VeraCrypt dosya
    kapsayıcısıdır (D3); kurulumu ayrı onayla yapılır. Avukat E1'e §4.4'te
    karşılığı olmayan bir araç veya koşul yazdıysa bu §6.1 gereği ek
    koşuldur ve runbook revizyonuna kadar DUR'dur; sahada yorumlanmaz.
    Doğrulama yürütme günü, her içerik oturumunda ve her silme günü
    tekrarlanır.
13. **F1 kopyaları için komut/guard tanımlanmadı** (§28.6, §32/22): exact-path
    guard, içerik taşıyabilen dosya adlarının komut satırına veya evidence'a
    girmesini gerektirirdi. Yerine çevrimdışı liste, kapsayıcı içinde olma
    koşulu, Shift+Delete veya F1 süresi içinde kapsayıcı imhası ve avukatın
    yazılı onayı kullanıldı.
14. **Girdi düzeltme döngüsü en fazla iki tur** (`<input-revision>` ≤ 3;
    kullanıcı önerisi). Sınır §14.3/1 bloğunda mekanik olarak uygulanır.
15. **Avukat kararının girdi hash önekini anması** (§14.3): önek
    `<lawyer-cited-prefix>` yer tutucusuyla mekanik olarak karşılaştırılır;
    12 karakter seçildi (insan tarafından aktarılabilir, kazara değişimi
    yakalar).
16. **G bölümünün ayrı imzası** (form v3'ten beri; v5'te imzalayan dosya
    avukatı): G10 tarihi bağlayıcı I3'ten önce olamaz; A–F yeniden
    imzalanırsa G de yeniden imzalanır (§6.6/4). Tarih sırası dosya
    avukatının beyanıyla desteklenir; mekanik değildir.
17. **Tarih token'ı ön kontrolü hash kaydına bağlandı** (§11.3 b): `False`
    sonucunda hash kaydı hiç yazılmaz; metin dosyası kalıcı olarak
    sabitlenmeden DUR verilir.
18. **Harici disk kuralı** (§4.2/10; kullanıcı kararı 2026-10-08; revizyonda
    prova incelemesi L1, O1, O2, O4 ile güncellendi): gövdedeki kural
    yalnız "bu cihazdaki harici USB disk"i değil, **bağlı her harici veya
    çıkarılabilir sürücüyü** kapsar. Tam disk şifrelemesi yolları
    kaldırıldığı için her harici sürücü içerik penceresi boyunca
    **fiziksel olarak çıkarılmış** olmalıdır; kabul edilen tek kayıt
    `EXTERNAL_DISK_ENCRYPTED=False` + `EXTERNAL_DISK_REMOVED=True`'dur ve
    başka her birleşim (ikisi de `True` dahil) açık **DUR**'dur (Y5).
    Pencere içinde yeniden takılan veya **yeni** takılan bir sürücü tek
    kodla **H40**'tır. Kâğıt teslim ve yerel tarayıcı yolu (eski §6.4)
    form v5 E2 ile kaldırıldığı için tarayıcı kararı artık gerekmez.
19. **E2 taşıyıcı kontrolü teslimden önce** (§6.4): kabul edilen tek tür
    uzaktan şifreli aktarımdır (`ENCRYPTED_TRANSFER`); USB ve kâğıt
    tanımlı değildir ve DUR verir (prova incelemesi L2, O3). Şifresiz bir
    aktarım dosyası belge cihaza aktarılmadan DUR verir; böylece §28.6/2'deki
    geç DUR öngörülebilir bir son adım hatası olmaktan çıkar.
20. **Girdi sürümleri sıralıdır** (§14.3/1): `r<N>` için `r1`…`r<N-1>`
    kayıtlarının hepsi mevcut, `r<N>`…`r3` kayıtlarının hiçbiri mevcut
    olmamalıdır; atlama DUR'dur.
21. **Form hash satır biçimi** (§6.6/7): `FORM_HASH` ve `FORM_BINDING`
    satırları; A–F ve G aynı dosyadaysa `unit=AFG` ve iki bağlayıcılık
    satırı. AF→AFG geçişi yalnız avukatın yazılı beyanıyla A–F'nin yeni
    sürümü sayılmaz.
22. **Evidence ve restricted dizinlerinin ayrılması** (§10.2, §13.8;
    kullanıcı kararı D2): `<evidence-dir>` yalnız metadata taşıdığı ve
    kapsayıcı imhasından sonra kalması gerektiği için kapsayıcının
    dışında; `<restricted-dir>` dava-türevi içerik taşıdığı için içindedir.
    Her biri kendi yol kapısından geçer.
23. **Kapsayıcı içinde guard'lı silmelerin korunması** (§28.3; kullanıcı
    kararı D12): kapsayıcı imhası tek başına yeterli olsa da case ve
    restricted dizinlerinin guard'lı silmeleri manifest eşliği kanıtı
    ürettiği için önce yapılır.
24. **TEMP yalnız süreç kapsamında yönlendirilir** (§4.4/5; kullanıcı
    kararı D5): kalıcı ortam değişikliği yapılmaz; GUI araçları için
    "Farklı kaydet" ve komut satırı açma kuralları kullanılır.
25. **E-imza geçerliliği UYAP editöründe ayrı kapıdır** (§6.6/1; kullanıcı
    kararları D17, D17a): `sign.sgn` biçim kontrolü geçerlilik kanıtı
    değildir; editörün ağ erişimi ayrı onaya bağlandı.

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

---

## 34. Revizyon kaydı

YENİ. Bu bölüm `13f19d0` runbook'unun (SHA-256
`26838760647b131ee4f64dd59e67eab0d43886bdc8fdf456522e3b04aaff97e9`)
revizyonunu kaydeder. Revizyon yalnız bu dosyayı değiştirir; kod, şema,
veri, başka runbook veya `CLAUDE.md` değişmez. Revizyon yazılırken hiçbir
komut çalıştırılmamıştır; yeni ve değişen bloklar §1.6/3 delta provasına
tabidir.

### 34.1 Girdiler

- `13f19d0` sentetik provasının bulguları ve bağımsız incelemesi (§0;
  `run\findings.md` ve `run\review\20261010-independent-review.md`).
- Runbook `13f19d0`'ın 8 Ekim 2026 tarihli bağımsız incelemesinin L1–L4
  ve O1–O5 bulguları (bu bölümdeki L/O kimlikleri **yalnız** bu listeye
  aittir; kullanıcı kararı D14: bağlayıcı kaynak bu incelemedir, plan v1
  L1/L2 aynı listedir, L3/L4 metni kayıptır).
- Avukat formu v5 (§0).
- Kullanıcı kararları K1–K6 ve D1–D19 (2026-10-10).
- Not: Adım 10 hazırlık kontrol listesinin kendi "O1–O5" satırları
  (kanal kapısı, içerik oturumu, IDE git ayarları, tek yazan oturum,
  tek-çalışım) **ayrı bir listedir**; içerikleri etiketsiz olarak §1.6/5,
  §4.3 (a) ve §27.2'ye işlenmiştir.

### 34.2 ID → bölüm eşlemesi

| ID | Kaynak | Bölüm | Değişiklik |
|---|---|---|---|
| L1 | 8 Ekim incelemesi | §33.1/18, §4.2/10 | §33.1 gövdeye eşitlendi: her harici/çıkarılabilir sürücü; kâğıt/tarayıcı yolu form v5 ile kalktı |
| L2 | 8 Ekim incelemesi | §6.4, §30/13, §25.1 Y5 | Tek taşıyıcı türü `ENCRYPTED_TRANSFER`; `PAPER`/`USB` → DUR; `E2_CARRIER_ENCRYPTED` yalnız bu tür için |
| L3 | 8 Ekim incelemesi | — | **Metin kayıp; kapatılamadı.** |
| L4 | 8 Ekim incelemesi | — | **Metin kayıp; kapatılamadı.** |
| O1 | 8 Ekim incelemesi | §4.2/10, §25.1 Y5 | Harici disk çiftinde ikisi de `True` → açık DUR satırı |
| O2 | 8 Ekim incelemesi | §25.1 H40, Y5 | Yeniden takma olayı tek kodla (H40); Y5'ten çıkarıldı |
| O3 | 8 Ekim incelemesi | §6.4, §4.2/10 | `D:` ve hiçbir harici sürücü taşıyıcı olamaz; pencere boyunca çıkarılmış olmalı |
| O4 | 8 Ekim incelemesi | §4.2/10, §25.1 H40 | Pencere içinde yeni takılan sürücü → açık DUR (kullanıcı kararı D19) |
| O5 | 8 Ekim incelemesi | §4.2/10 | `13f19d0`'daki çok uzun harici disk satırı kaldırıldı; kural madde listesine bölündü |
| N2 / PR-NOPROFILE | Prova planı | §1.6/5, §4.3 (c) | İnsan-only etkileşimli `-NoProfile` denemesi gerçek dosya öncesi zorunlu |
| Günlük dosyası | Kullanıcı | §32/26 | **Ertelendi** (D1=A): pilot kümesinin `--log=<DATA_DIR>\server.log` kullanımı Adım 8 §D'ye (LOCKED) dokunur; bu revizyona alınmadı, açık sınır olarak yazıldı |
| R-F-PKG | Prova bulgusu | §13.3 | 42 satırlık referans gömüldü; karşılaştırma bloğu |
| R-F-AUDITKEY | Prova bulgusu | §4.2/9 | Değer satırı (bilgi); yazılı beyan kuralı aynen (D10) |
| R-F-ACLAI | Prova bulgusu | §1.6/3 | Kasıtlı ACL hatasında SDDL eşitliği yalnız gerçek `extractions` dizininde DUR (K2) |
| R-F-DLB | Prova bulgusu | §18.2–§18.3 | Sabit boolean bloğu; tarih yalnız ekranda |
| R-F-EXTDIR | Prova bulgusu | — | Değişiklik yok: yalnız provanın kasıtlı hata yöntemine özgü; §11.2/2 kuralı aynen geçerli |
| R-F-M09MSG | Prova bulgusu | §14.5.3 | Preview/apply mesaj farkı yazıldı |
| R-F-DBDEC (L-3) | Prova incelemesi | §1.6/3, §32/1 | Prova DB kararı kapandı (K5) |
| M-1 | Prova incelemesi | §1.6/3 | K2 kuralıyla birlikte: sonda dizininin SDDL farkı bilgi amaçlı |
| M-2 / O-f | Prova incelemesi | §1.6/3, §1.6/4, §4.4, §32/12 | Kapsayıcıya göre yeniden tanımlandı; `THIRD_PARTY_FDE_PRESENT` kalktı (K3) |
| M-3 | Prova incelemesi | §4.4/4, §25.1 Y17, §32/27 | ACL sıkılaştırması ve principal ölçümü; K4 tek başına M-3'ü kapatmaz (D4) |
| L-1 | Prova incelemesi | — | Prova planına ait (muafiyet etiketleri); runbook değişikliği yok |
| L-2 | Prova incelemesi | §26.4 | Özet tam evidence manifesti taşır |
| L-4 | Prova incelemesi | §18.3 | Tarih yalnız ekranda; evidence'a boolean |
| L-5 | Prova incelemesi | §4.2/8 | Mevcut kural aynen geçerli (ham çıktı evidence'a kopyalanmaz); değişiklik yok |
| `CLAUDE_CODE_MESSAGING_TOKEN` gözlemi | Prova incelemesi | §13.6, §1.6/3, §4.2/6 | Desen += `CLAUDE.*`; prova planında E0'da tek tek (K6, D11) |
| K1 | Kullanıcı | §0 | Prova verdict'i inceleme dosyasının pinine bağlandı |
| K2 | Kullanıcı | §1.6/3 | Yukarıda |
| K3 | Kullanıcı | §1.6/3, §1.6/4, §4.2/10, §4.4 | Yukarıda |
| K4 | Kullanıcı | §1.5, §4.4, §10, §13.2, §13.8 | Repo klonu, çalışma, geçici ve çıktı dosyaları kapsayıcıda; reparse yok; kapsayıcı yol kapıları |
| K5 | Kullanıcı | §1.6/3 | Yukarıda |
| K6 | Kullanıcı | §3, §4.2/6, §13.6, §1.6/3, §32/29 | Gerçek pilot ajan oturumundan başlatılmaz |
| D2 | Kullanıcı | §1.5, §10.2, §13.8, §28.3.2, §33.1/22 | Evidence dışarıda, restricted içeride |
| D3 | Kullanıcı | §4.4/1–2 | VeraCrypt dosya kapsayıcısı, NTFS, sürücü harfi; kurulum ayrı onay |
| D5 | Kullanıcı | §4.4/5 | TEMP/TMP yalnız içerik oturumunda kapsayıcıya |
| D6 | Kullanıcı | §6.4, §1.6/5 | 7z AES-256; e-posta eki sorusu `EXTERNAL LEGAL VERIFICATION REQUIRED` |
| D7 | Kullanıcı | §11.2/6 | Ayrı görüntüleyici yok |
| D8 | Kullanıcı | §4.2/3, §4.4/6, §11.2/6, §1.6/3 | `pdftotext` pinleri; sentetik PDF provası |
| D9, D9a | Kullanıcı | §1.6/5, §4.4/8, §32/25, Y19 | Kapsayıcı dışı izlerin yazılı bildirimi ve `LEGAL_APPROVED` kapısı |
| D12 | Kullanıcı | §28.3 | Guard'lı iç silmeler, sonra kapsayıcı imhası |
| D13, D13a | Kullanıcı | §1.6/3, §34.4 | Delta prova; tek-çalışımlık yeniden prova; kapsayıcı içi hafif uçtan uca geçiş |
| D14 | Kullanıcı | §34.1 | D14 = L1–L4/O1–O5'in bağlayıcı kaynağı 8 Ekim 2026 incelemesidir; plan v1 L1/L2 aynı liste; L3/L4 metni kayıp — §34.1'de uygulandı (remediasyon turu 2, §34.7) |
| D15 | Kullanıcı | §1.6/4, §4.2/10 | Tam disk şifrelemesi yolu kaldırıldı |
| D16 | Kullanıcı | §13.3 | Referans gömüldü |
| D17, D17a | Kullanıcı | §6.6/1, §1.6/5, Y20, §32/23 | `sign.sgn` biçim kontrolü + `UDF_SIGNATURE_VALID` kapısı her e-imzalı birimde; editör ağ erişimi ayrı onay |
| D18 | Kullanıcı | §3, §4.3 (a) | Klon hiçbir zaman IDE'de açılmaz |
| D19 | Kullanıcı | §4.2/10 | O4 sıkılaştırması |
| Form v5 rolleri | Form v5 B1, B2, I | §2.1, §4.1, §6.1, §8 | Protokol inceleyicisi / dosya avukatı / operatör (veri işleyen) |
| Form v5 B5, Ek 2 | Form v5 | §6.3, §6.6, Y2 | Ek 2 operatör + dosya avukatı imzalı |
| Form v5 C1, Ek 1 | Form v5 | §7, §6.6 | Ek 1 doldurma ve teslim teyidi |
| Form v5 E1–E4 | Form v5 | §4.2/3, §4.2/11, §4.4, §6.4, §11.2/6, §25.2/10 | Kapsayıcı; uzaktan şifreli aktarım; telefon + aynı gün yazılı bildirim; `pdftotext` |
| Ağ iddiasının kapsamı | Form v5 E2/E4, D3, D17a | §1.2, §2, §21, §30/10 | "Sıfır dış ağ işlemi" iddiası §21'deki beş sınıfa daraltılarak yeniden tanımlandı: (1) runbook komutları — **sıfır**; (2) dosya aktarımı — E2 aktarım dosyasının içeri yönlü alınması (`E2_INBOUND_TRANSFER_RECEIVED=True`); (3) ön-pencere insan ağ işlemleri — kurulumlar ve UYAP editörü, içerik penceresinden önce, ayrı onaylı; (4) karar kanalı — sayılı, hash'li ve içeriksiz; (5) sesli görüşme — cihaz dışı; gerçek içerik cihazdan çıkmaz. **Remediasyon turu 1 (§34.6, M-2):** §21'deki dört sınıfa netleştirildi; UYAP editörü zincir adım 2–3'te, içerik penceresinden önce; insan yazışmaları karar kanalında sayılı, hash'li ve içeriksiz. **Remediasyon turu 2 (§34.7, N-1, L-c):** beş sınıf; 5. sınıf sesli görüşme (E2 parolası, E3 telefonu) |
| Form v5 F1, F4, F5 | Form v5 | §23, §28.3, §28.6, §28.7 | 24 saat; kapsayıcı yöntemi; imha kaydı operatörde + kopyası dosya avukatına |
| Form hash | Form v5 | §0, §6.6/9 | `FORM_HASH unit=AF seq=1` beklenen değeri = v5 UDF hash'i |
| A-DEV-01 | Prova ajan notu | §12.4 | OWNER rolü cümlesi |
| A-DEV-02 | Prova ajan notu | — | **Yalnız ajan notu**; runbook değişikliği yok |
| A-OBS-01 | Prova ajan notu | — | **Yalnız ajan notu**; runbook değişikliği yok |
| 0.11 tr-TR görüntüleme filtresi | Prova ajan notu | — | **Yalnız ajan notu**; runbook değişikliği yok |

### 34.3 Kapatılamayan veya ertelenen maddeler

- **L3, L4:** metinleri kayıp; kapatılamadı. Metin bulunursa ayrı
  revizyonla işlenir.
- **D14:** artık açık değildir. D14 = L1–L4/O1–O5'in bağlayıcı kaynağı
  8 Ekim 2026 incelemesidir; plan v1 L1/L2 aynı liste; L3/L4 metni kayıp
  — §34.1'de uygulandı (remediasyon turu 2, §34.7). Açık kalan yalnız
  L3/L4 metnidir (yukarıda).
- **Günlük dosyası (D1=A):** Adım 8 §D (LOCKED) değişmeden; §32/26.
- **E-posta eki hukuki sorusu (D6):** `EXTERNAL LEGAL VERIFICATION
  REQUIRED`; cevap gelene kadar e-posta eki kanalı DUR (§6.4).
- **Kapsayıcı dışı izler (D9):** hukuki kapı; mühendislikle kapanmaz
  (§32/25).

### 34.4 Delta prova devralma eşleme tablosu (kullanıcı kararı D13)

**Devralma kuralı.** Bir komut bloğu, `13f19d0` runbook'u ile bu revizyon
arasında **bayt-bayt aynıysa** `13f19d0` provasının kanıtıyla devralınır.
Delta prova planı her devralınan blok için eski ve yeni blok metninin
SHA-256'sını bu tabloya ekler; iki hash farklıysa blok yeniden prova
edilir. "Tek-çalışım" satırları ayrı onaylı, tekrarlanmayan adımlar olarak
yeniden prova edilir. Ayrıca kapsayıcı içinde bir hafif uçtan uca sentetik
geçiş yapılır (D13a; §1.6/3).

**Revizyon 2 devralma tabanı (kullanıcı kararı K-R2-10).** Revizyon 2'den
itibaren devralma tabanı, son prova edilmiş sürümdür: runbook `4f5c37e`
(= `c2a7dbc`, blob SHA-256 `1397ea07…`) ve onun delta provası e11bab73
(§0). Bu sürümle **bayt-bayt aynı** bir blok e11bab73 kanıtıyla (ve oradan
geçişli olarak, aşağıdaki tabloda "Devralınır" olan bloklar için
`13f19d0` kanıtıyla) devralınır. Revizyon 2'de değişen veya yeni eklenen
bloklar ve Δ5 aşağıdaki revizyon 2 satırlarında "Yeniden/Yeni"dir.
Sonraki prova planı kod bloğu ekini bu tabana göre yeniden üretir; yeni
optik blok (§4.2/10) kendisinden sonraki blok numaralarını bir kaydırır
(§34.8).

| Runbook bloğu | `13f19d0` provası kanıtı | Revizyonda | Prova |
|---|---|---|---|
| §4.3 (a) süreç adı deseni | 0.10 | Blok aynı (metin eklendi) | Devralınır |
| §4.3 (b), (c) | 0.11 (`MECHANICS_ONLY`) | Aynı | **Devralınmaz**: PR-NOPROFILE insan-only zorunlu (§1.6/5) |
| §4.2/9 | 0.9 | Değer satırı eklendi | Yeniden |
| §4.2/10 harici disk kuralı | 0.12 (muaf) | Yeniden yazıldı | **Yeniden, tek-çalışım** |
| §4.4/1–3 kurulum, oluşturma, düzen, klon (`-b claude-dev`) | — | Yeni | **Yeni, tek-çalışım** |
| §4.4/4 ACL sıkılaştırma ve ölçüm | — | Yeni | **Yeni, tek-çalışım** |
| §4.4/5 sistem Temp kaydı ve TEMP yönlendirmesi | — | Yeni (remediasyon turu 1: `<system-temp>`, tam eşitlik) | **Yeni, tek-çalışım** (kayıt bir kez yazılır) |
| §4.4/6 teknik kayıt ve araç doğrulaması | — | Yeni | **Yeni, tek-çalışım** |
| §6.4 aktarım, `7z l -slt` yöntem kontrolü ve açma | — | Yeni | Yeni (sentetik AES-256 7z; başlıkları şifreli ve şifresiz iki arşivle, ayrıca şifresiz bir arşivle `STOP` dalı) |
| §6.6/1 `sign.sgn` | — | Yeni | Yeni (sentetik UDF) |
| §6.6/7 `FORM_HASH` satırları | 0.17 | Biçim aynı | Devralınır |
| §10.5 izinli küme ve envanter | 0.16, A.27, G-11…G-13 | Blok aynı; yol kapsayıcıda | Yeniden (D2 yol kapısıyla) |
| §11.2/3–5 BOM, uzunluk, `page_count` | A.2–A.3, B.2 | Aynı | Devralınır |
| §11.2/6 `pdftotext` | — (metin elle) | Yeni | Yeni (sentetik PDF, D8) |
| §11.3 (a)–(d), (f) | A.5–A.9, B.3, B.4 | Aynı | Devralınır |
| §11.3 (e), §13.2 `git` | A.8, 0.1 | Klonda | Yeniden |
| §12.3, §27.1 assign/revoke | A.14, B.5, A.30, B.35 | Aynı | Devralınır |
| §13.3 paket kümesi | 0.6, 0.7 | Blok eklendi | Yeniden |
| §13.5 salt-okunur SQL | 1.4, 1.4b | Aynı | Devralınır |
| §13.6 (b) desen | 0.8 | `CLAUDE.*` eklendi | Yeniden (ajan provasında eşleşme beklenir; E0'da tek tek) |
| §13.8 `Test-PilotPath` tanımı, repo kökü/`cases-parent`, ortak yardımcılar ve case dizini kapısı (dört blok) | 0.15, Z.0, G-09, G-10 | Aynı (bayt-bayt) | Devralınır |
| §13.8 repo dışı dizinler, `<external-root>` sözleşmesi (tam eşitlik, `<system-temp>`), kapsayıcı kapıları, kapsayıcı dosyasının iki aşamalı kapısı, `pdftotext`/`7z` dosya kapıları | 0.15, Z.0, G-09, G-10 | Yeniden yazıldı / yeni (remediasyon turu 1 dahil) | **Yeniden, tek-çalışım** |
| §14.2–§14.6 `manual-fact` ve reconciliation | A.11–A.16, B.6a–B.27 | Bloklar aynı | Devralınır |
| §15–§18.1, §19–§20 | A.17–A.28, B.28–B.33 | Aynı | Devralınır |
| §18.2–§18.3 boolean bloğu | A.25 (`dl_check.py`) | Yeni | Yeni |
| §25.2 dosyasız dallar | B.34 | Metin | Devralınır |
| §26.4 tam manifest | Z.6 | Değişti | Yeniden |
| §28.2 iki metadata manifesti (üç blok) | A.31–A.35, B.36–B.40, Z.0 (ortak; blok bazında ayrılmadı) | Aynı (bayt-bayt) | Devralınır |
| §28.3.1 case guard fonksiyonu (ilk blok) | A.31–A.35, B.36–B.40, Z.0 (ortak) | Aynı (bayt-bayt) | Devralınır |
| §28.3.1 guard ve silme blokları (iki blok) | A.31–A.35, B.36–B.40, Z.0 (ortak) | Korunan listede `<system-temp>`/`<container-temp>` (remediasyon turu 1, H-1) | **Yeniden, tek-çalışım** |
| §28.3.2, §28.3.3, §28.5 arşiv kapısı, §28.6 F1 | A.31–A.35, B.36–B.40, Z.0 (ortak) | Yeniden yazıldı / yeni (remediasyon turu 1 dahil) | **Yeniden, tek-çalışım** |
| **Revizyon 2:** §6.4 `7z l -slt` yöntem kontrolü (klasör tanıma + boyut-sıfır, `$null` borusu, `SEVENZIP_FOLDER_ENTRY_COUNT`) | e11bab73 T.3/T.3u (eski blok) | Yeniden yazıldı | **Yeniden** (Δ1: A0, A0z, A1 [`STOP`, beklemeden dönüş], staging A2, A2b, yeni A3 [klasör + şifreli + şifresiz dosya → `STOP`; yapım yöntemi Δ1'de denenir, kurulamazsa sınır olarak yazılır], yeni A5 [yalnız boş klasör → `STOP`]) |
| **Revizyon 2:** §6.4 açma (`attempt`, `X_ENTRY_COUNT`, `SEVENZIP_WRONG_PASSWORD_SHOWN`, tek ek deneme, başarı = `SEVENZIP_RC=0` + `X_ENTRY_COUNT=1`) ve parola biçimi/girişi (telefon alfabesi, alfabe dışı → yeniden gönderim en fazla bir kez) | e11bab73 T.3u (eski blok) | Değişti | **Yeniden, insan-only** (Δ2: 29 sembollü 20 karakterlik parola; telefon alfabesiyle sesli okuma, kâğıt, geri okuma, elle yazma; bilinçli hata → `SEVENZIP_RC=2`, `SEVENZIP_WRONG_PASSWORD_SHOWN=True`, `X_ENTRY_COUNT=0` → tek ek deneme → `SEVENZIP_RC=0`, `X_ENTRY_COUNT=1`; kâğıt imhası `reason=used`) |
| **Revizyon 2:** §4.4/6 teknik kayıt bloğu (`CDROM_DRIVE_COUNT`, `OPTICAL_DRIVE_LETTERS`) | e11bab73 K.8 (eski blok) | Değişti | **Yeniden, tek-çalışım** (Δ3a: kayıt `CDROM_DRIVE_COUNT=1`, `OPTICAL_DRIVE_LETTERS=E:` taşır) |
| **Revizyon 2:** §4.2/10 yerleşik optik sürücü bloğu (teknik kayıtla eşleşme dahil) | e11bab73 K.0, M.5, R.4 (plan dışı ölçüm; blok yoktu) | Yeni | **Yeni, tek-çalışım** (Δ3b: `OPTICAL_DRIVES_MATCH_RECORD=True`, `OPTICAL_MEDIA_LOADED=False drive=E:`) |
| **Revizyon 2:** §11.2/4 uzunluk bloğu (`TEXT_VISIBLE`) | e11bab73 T.2, E.4 (eski blok) | Değişti | **Yeniden** (Δ4: metinli PDF → `TEXT_VISIBLE=OK`; görüntü PDF → `STOP TEXT_VISIBLE=EMPTY`) |
| **Revizyon 2:** §4.3 (a) kapatma prosedürü ve tarama bloğu (`AI_CHANNEL_SCAN at=` satırı eklendi) | e11bab73 E.0, R.4 (eski blok) | Değişti | **Yeniden, insan-only** (Δ5: ajan kapalıyken iki tarama, `at=` damgaları arası en az 2 dakika, ikisi de `AI_CHANNEL_PROCESS_COUNT=0`) |
| **Revizyon 2:** §4.2/9, §18.2, §18.4, §28.2 metinleri | e11bab73 0.8, E.16, Z | Yalnız metin; bloklar bayt-bayt aynı | Devralınır |
| **Revizyon 3:** §4.3 (a) tarama bloğu N4 (kültürden bağımsız eşleşme) | delta2 0.6 (eski blok; kültür bulgusu), H1 | Değişti | **Yeniden** (delta3: ajan bağlamında tr-TR altında büyük `I` taşıyan sentetik adlar 3/3; insan penceresinde `a2`, `a3`, `a9`) |
| **Revizyon 3:** §6.4 listeleme bloğu N16 (konsolsuz, kapalı stdin, 10 sn bekçi, ölçüm satırları) | delta2 D1.2, D1.3 (eski blok), H2 (BELİRSİZ) | Yeniden yazıldı | **Yeniden** (delta3 ajan fazı: A0, A0z, A1, A2, A2b, A3, A5, A6; A1'de kesin çıkış kodu ve `SEVENZIP_STDERR_BREAK_SEEN` ölçülür; bekçi testi; büyük çıktılı bir arşivde `SEVENZIP_TYPE_7Z_SEEN` ve çıktı okumasının tamlığı (addendum E3.2; R3 düzeltme turu, inceleme L-2); insan penceresinde `a5`, tek çalışım) |
| **Revizyon 3:** §6.4 açma bloğu N17 (Caps Lock, damgalar, `X_ENTRY_COUNT … attempt`) | delta2 H4, H5 (eski blok; Δ2 FAIL) | Değişti | **Yeniden, insan-only** (`a6`, `a7`; Caps Lock kapalıyken deneme harcanmaması dahil) |
| **Revizyon 3:** Ek R3 kiti (N105–N113) ve tek sayfa (N114) | — | Yeni | **Yeni, tek-çalışım** (kit kurulumu; negatif kontroller: `DUR.txt` varken adım araç çağırmadan çıkar, sıra atlama reddi, pin uyuşmazlığı, `kit-values.txt` profil yolu reddi, erken `a3`; R3 düzeltme turu: silme oturumu — kilitte `a2`/`a3` çalışır, `a4`–`a7` reddedilir —, `a5` PASS sonrası geri okuma kaydı yokken `a8` `reason=stopped`, oturum sınırı yok; insan penceresi tek sayfayla) |
| **Revizyon 3:** N3, N6, N14 (yalnız satır 1), N15, N51 | e11bab73 / delta2 kanıtı | Bayt-bayt aynı; kit içinde kopya olarak çalışır | Blok **devralınır**; kit içinden çağrılmaları delta3'te yeniden prova edilir |
| **Revizyon 5:** N105 (`ac.ps1`: ortak DUR kuralı, `Get-KitScript` tür denetimi, silme oturumu iletisi), N107 (`a3` iletisi), N108 (`a4` TEMP ön denetimi ve yönlendirmesi) | d9d67b7d Faz A (A.6, A.9, A.10, A.14) ve pencere 1 `a2`–`a4` (eski bloklar) | Değişti | **Yeniden, tek-çalışım** (kit kurulumu, N116 ve yükleme/kilit negatifleri yeniden; `a4`: kayıt ve kilit yazmayan red dallarının hepsi — teknik kayıt yok; teknik kayıt okunamıyor/biçimi geçersiz; optik ön ölçüm reddi (disk/görüntü takılı veya sürücü kümesi kayıtla uyuşmuyor; disk çıkarılıp `a4` aynı pencerede yeniden yazılınca doğru devam etmesi); sistem Temp kaydı yok (`NO_RECORD`); kayıtla uyuşmuyor (`MISMATCH`); `container-temp` yok (`NO_DIR`); TEMP pencerede zaten değişmiş (`ALREADY`); yönlendirme doğrulanamadı (`VERIFY`; eski TEMP/TMP geri konur) —, her kilitsiz redden sonra eksik giderilip `a4` yeniden yazılınca kaydın ve kilidin temiz kalması ve akışın doğru devam etmesi; ön ölçüm geçtikten sonra kayıt içindeki N3'ün kilitlemesi (sorgu başarısız/durum okunamıyor); `a3`'ten sonra madde 3'ün yardımsız yapılması (bağımsız inceleme L9); ve PASS dalı (PASS'te `a5`–`a7`'deki 7z çocuk sürecinin gerçekten `TEMP`/`TMP` = `container-temp` görmesi); DUR kuralının adım DUR'u, kilit uyarısı ve yükleme hatası iletilerinde basılması ve `SIMDI a9 YAZIN` satırının `a9` tanımlıyken ekranda görünmesi; insan penceresinde kanıt incelemesinin 5B listesi; revizyon 5 düzeltme turu, kullanıcı kararı M1) |
| **Revizyon 5:** tek sayfa N114 ve not formu N115 | d9d67b7d pencere 1 (eski N114; not formu doldurulmadı) | Değişti / yeni | **Yeniden, insan-only** (5B madde 1, 2, 10, 12: kapatma ve bir kerelik hazırlık, `a4`'ün TEMP adımı, DUR anı, kâğıt not formu) |
| **Revizyon 5:** değişken adı çakışma denetimi N116 (Ek R3/7) | — | Yeni | **Yeni** (kurulumda `KIT_VAR_COLLISIONS=0`; pozitif kontrol olarak revizyon 3'ün N105'i `STOP KIT_VAR_COLLISIONS` vermelidir) |
| **Revizyon 5:** N106, N109–N113 ve kit kopyaları N3, N4, N6, N14, N15, N16, N17, N51 | delta3 ajan fazları (86c4a7da, d9d67b7d); insan tarafında yalnız `a2`/`a3` | Bayt-bayt aynı | Blok **devralınır**; kopya bloklara bağlı ajan ölçümleri (5A madde 4, 5, 7: N16, bekçi, N4) devralınır; değişen N105 üzerinden çalıştıkları için kit adımlarının ajan ölçümleri (5A madde 1–3, 6, 8–11) yeniden yapılır; insan tarafında hiç ölçülmemiş adımlar (`a5`–`a9`, parola aktarımı, Caps Lock, kasıtlı DUR ve silme oturumu; 5B listesi) yeniden prova edilir |

### 34.5 Yazım sınırları

- Formdaki kişi adları bu runbook'a yazılmamıştır; roller adlarıyla değil
  işlevleriyle anılır (§1.5).
- Bu revizyon hiçbir LOCKED sözleşmeyi değiştirmez; Adım 8 runbook'una
  dokunan günlük dosyası maddesi bilinçli olarak ertelenmiştir (§32/26).

### 34.6 Remediasyon turu 1

YENİ. Bu revizyonun (SHA-256
`0e2e9c4e2ad7fac65aaf35791b8fd64684861c26d18977d2e3ef61078d154b66`, 4753
satır) bağımsız incelemesi `READY_FOR_NARROW_REMEDIATION` verdi; kullanıcı
dar remediasyonu onayladı. Yalnız aşağıdaki bulgular işlendi; kapsam
genişletilmedi. Yazılırken hiçbir komut çalıştırılmadı; değişen bloklar
yalnız PowerShell ayrıştırıcısıyla (`ParseInput`) denetlendi ve §1.6/3
delta provasına tabidir. "Eski satır" `0e2e9c4e` sürümündeki, "yeni satır"
remediasyon turu 1 sonundaki sürümdeki (SHA-256
`a95f82914ed8bc422717a008ccf5aa2afd4dda92e3316c5ec103ac5fbefe8b08`, 5040
satır) satır numarasıdır; remediasyon turu 2 bu numaraları kaydırmıştır
(§34.7).

| Bulgu | Eski satır | Yeni satır | Değişiklik |
|---|---|---|---|
| H-1 | L117, L152, L957, L2243, L2283, L3889, L3912, L3969, L3998, L4032, L4083 | L120–L123, L158, L988–L1032, L2349–L2363, L2397–L2431, L4063, L4086, L4143, L4172, L4208, L4264 | `<system-temp>` (`<system-temp-user>`, `<system-temp-windows>`) yer tutucusu; içerik oturumundan önce bir kez okunur, SHA-256'sı `system-temp.txt`'ye yazılır; her oturumda yönlendirmeden önce `SYSTEM_TEMP_MATCH`; bütün korunan listelerde `GetTempPath()` yerine `<system-temp-user>`, `<system-temp-windows>`, `<container-temp>`; `TEMP_IN_CONTAINER` tam eşitlik |
| H-2 | L2243, L3998, L4008–L4009 | L2349–L2363, L4172, L4182–L4185, L4423–L4424 | `<external-root>` altında **tam olarak** `<evidence-dir>`: `13f19d0`'ın sıralı ad kümesi tam eşitlik karşılaştırması §13.8 sözleşmesine ve §28.3.2 kalıntı kontrolüne geri geldi |
| M-1 | L891, L2276–L2289 | L920–L929, L2397–L2431 | Kapsayıcı dosyası için iki aşamalı kapı: (i) oluşturmadan önce `PATH_OK=container-file-parent`, (ii) oluşturduktan sonra `PATH_OK=container-file`; korunan listeye `<source-repo-root>` eklendi |
| M-2 | L52–L62, L382–L383, L418–L420, L730–L734, L1135–L1137, L3295, L3309–L3320, L3517, L4244–L4248 | L54–L65, L393–L396, L431–L434, L761–L764, L1211–L1214, L3435, L3449–L3488, L3686, L3776, L4426–L4433 | Karar kanalı tanımı (§21/4): gelen kararlar `INBOUND_DECISION_RECEIVED seq=<n> sha256=…`, giden bildirimler `OUTBOUND_NOTICE_SENT seq=<n> sha256=…`, içeriksiz; ağ iddiası dört sınıf; UYAP editörü zincir adım 2–3'te, içerik penceresinden önce; Y15 tanımı §21 ile hizalandı |
| M-3 | L441, L547, L1086, L1104 | L455, L570, L578–L580, L1157–L1163, L1179, L3578, L3673, L3776 | B3: dosya avukatının bu dosya için işleme şartını adıyla belirten yazılı teyidi zorunlu (`PROCESSING_BASIS_CONFIRMED=True`; yoksa pilot başlamaz, Y2); rol ayrımı: A–F + I protokol inceleyicisi, G/Ek 2/işleme şartı teyidi dosya avukatı |
| Low — O-f | L285 | L292–L297 | `EXTERNAL_DISK_PRESENT` kapı değil kayıt; harici disk olmaması pilotu engellemez |
| Low — yer tutucu | L4032 | L4208, L4211–L4216 | `[long]'<container-file-bytes>'`; blok ayrışıyor |
| Low — L3 | L4642 | L4873 | Tahmin cümlesi kaldırıldı: "Metin kayıp; kapatılamadı." |
| Low — B4 | L574–L576, L1105, L3506 | L598–L603, L1180, L3675 | v5 seçeneği "Hayır" + dosya avukatının ayrı yazılı kabulü |
| Low — I0 | — | L1387–L1397, L3597, L3672 | §6.7 I0/I1/I2–I4 kapı tablosu; §24 I0 satırı; Y1 |
| Low — §2.1 sıra | L478–L481 | L496–L504 | Kapsayıcı imhasının sırası "Sıra istisnaları"na eklendi |
| Low — 7z | L1153–L1167 | L1201–L1202, L1230–L1265, L3676 | Açmadan önce `7z l -slt` ile her girdi `Encrypted = +` ve `7zAES` (`SEVENZIP_ALL_ENTRIES_7ZAES=True`) |
| Low — git clone | L908 | L945 | `-b claude-dev` |
| Low — §34.4 | L4740, L4746 | L4974–L4975, L4981–L4984 | §13.8 dört blok, §28.2 üç blok ve §28.3.1 ilk blok "Aynı (bayt-bayt) / Devralınır"; H-1 nedeniyle değişen §28.3.1 iki blok "Yeniden" |
| Low — D14 | — | L4912, §34.3 | D14 satırı (remediasyon turu 2'de düzeltildi, §34.7 L-a): D14 = L1–L4/O1–O5'in bağlayıcı kaynağı 8 Ekim 2026 incelemesidir; plan v1 L1/L2 aynı liste; L3/L4 metni kayıp — §34.1'de uygulandı |
| Sonuç düzeltmeleri (tabloya remediasyon turu 2'de eklendi) | L167, L1616, L3497, L3601, L3604–L3605, L3819, L4071, L4238–L4239, L4690, L4724, L4726, L4728 | L173–L174, L1728–L1729, L3666, L3770, L3773–L3774, L3989–L3993, L4250–L4252, L4419–L4420, L4922, L4958, L4960, L4962 | Yukarıdaki bulguların doğrudan sonuçları: §1.5 çözümlü yol listesine `<system-temp-user>`/`<system-temp-windows>` (H-1); içerik oturumu beklenen satırlarına `SYSTEM_TEMP_MATCH=True` (H-1); H52 tanımı (H-1, H-2, M-1); §26.2 yol kapısı, kapsayıcı ve E2 satırları (M-1, H-1, 7z); §28.3 ve §28.5 sapma metinleri (H-1, H-2); §30/7'ye `system-temp.txt` (H-1); §34.2 ağ iddiası satırı notu (M-2); §34.4 git clone, §4.4/5 ve §6.4 satırları |
| Low/Observation → §32 | — | L4632–L4677 (§32/30–38) | 7z yöntem sınırı; D9 listesinde olmayan küçük resim önbelleği ve Recent/jump list; "elle kopyalama" yöntemi; sunucu günlüğü iddiasının ölçülmemişliği; H16/Y1 çift kod; AF biriminin boş şablonları; §4.2/9 bloğunun `$audit` bağımlılığı; `TWO_PERSON_CONTROL` sırası; karar kanalının içeriksizliğinin beyana dayanması |

**Uygulama notları.**

- **H-1 ve evidence kuralı.** Kullanıcı kararı, sistem Temp yollarının
  "evidence'a yazılmasını" istiyor; §1.5 ise mutlak yerel yolun evidence'a
  yazılmasını yasaklıyor. Daha kısıtlayıcı kural uygulandı: evidence'a
  yolların kendisi değil SHA-256'ları yazılır; yollar yalnız ekranda
  gösterilir ve yer tutuculara aynen girilir.
- **H-1 ve §34.4.** H-1, `13f19d0` ile bayt-bayt aynı olan §28.3.1'in iki
  bloğunu değiştirdi; bu iki blok artık "Aynı" değildir ve §34.4'te
  "Yeniden" olarak işaretlendi. §28.3.1'in ilk bloğu (guard fonksiyonu),
  §28.2'nin üç bloğu ve §13.8'in dört bloğu bayt-bayt aynı kaldı (blok
  hash'leriyle ölçüldü).
- **M-2 ve içerik taşıyan kayıtlar.** §17.2 kör hesap kaydı gibi içerik
  taşıyan kayıtlar karar kanalına girmez; kanaldaki karar yalnız kaydın
  SHA-256'sını anar (§21/4).
- **Ayrıştırma.** Bu sürümdeki 91 PowerShell bloğundan `13f19d0`'dan
  farklı olan 29 bloğun hepsi `ParseInput` ile hatasız ayrıştı (önceki
  sürümde ayrışmayan `<container-file-bytes>` bloğu dahil).

### 34.7 Remediasyon turu 2

YENİ. Remediasyon turu 1 sonundaki sürümün (SHA-256
`a95f82914ed8bc422717a008ccf5aa2afd4dda92e3316c5ec103ac5fbefe8b08`, 5040
satır) hedefli bağımsız yeniden incelemesi `READY_FOR_NARROW_REMEDIATION`
verdi (bir Medium: N-1; dört Low: L-a–L-d; dört Observation); kullanıcı
dar remediasyonu ve N-1 için kararı verdi. Yalnız aşağıdakiler işlendi;
kapsam genişletilmedi. Yazılırken hiçbir runbook komutu çalıştırılmadı;
bu turda hiçbir PowerShell kod bloğu değişmedi (değişiklikler yalnız
metin ve tablo satırlarıdır; blok hash'leriyle ölçüldü), bu yüzden §34.4
delta prova eşlemesi değişmez. "Eski satır" `a95f8291` sürümündeki,
"yeni satır" bu sürümdeki satır numarasıdır.

| Bulgu | Eski satır | Yeni satır | Değişiklik |
|---|---|---|---|
| N-1 (Medium) — E2 parola kanalı | L56–L65, L760, L763–L764, L1188, L1201–L1202, L1222–L1224, L3435, L3450–L3451, L3453, L3469–L3470, L3485–L3486, L3676, L3686, L3774–L3775, L4426–L4433 | L56–L69, L769–L770, L773–L775, L1203, L1216–L1219, L1239–L1249, L3465, L3480–L3482, L3484–L3485, L3501–L3503, L3518–L3530, L3720, L3730, L3818–L3819, L4470–L4481 | Kullanıcı kararı: E2 parolasının ayrı kanalı **yalnız** dosya avukatından operatöre sesli telefon görüşmesidir. §21'e 5. sınıf "sesli görüşme": cihaz dışı, bu cihazdan ağ işlemi değil; evidence'a yalnız `E2_KEY_CHANNEL=VOICE_CALL at=<zaman-damgası>`; parola, hash'i veya türevi asla yazılmaz. E3 telefon bildirimi de bu sınıfta (`INCIDENT_NOTICE_CHANNEL=VOICE_CALL`, `OUTBOUND_NOTICE_SENT`'e ek). §6.4 E2 satırı ve "Biçim" maddesi bu tanıma bağlandı; `E2_KEY_SEPARATE_CHANNEL=True` yalnız `VOICE_CALL` ile; başka kanal → DUR (Y15). Y5, Y15, §26.2 E2 ve olay bildirimi satırları, §30/10 güncellendi; "başka sınıf yoktur" cümlesi beş sınıfa göre yeniden yazıldı |
| L-a — D14 | L4859, L4912, L4934–L4935, L5020 | L4907–L4908, L4961, L4983–L4986, L5074 | D14 = L1–L4/O1–O5'in bağlayıcı kaynağı 8 Ekim 2026 incelemesidir; plan v1 L1/L2 aynı liste; L3/L4 metni kayıp — §34.1'de uygulandı |
| L-b — port numarası | L139 (sonrasına ekleme), L320, L4613 | L144, L325, L4661 | Port değeri kaldırıldı; `<pilot-port>` yer tutucusu §1.5 tablosuna eklendi (belgeye, evidence'a ve commit'e yazılmaz) |
| L-c — ağ iddiası sayıları | L56–L65, L431–L434, L3435, L3453, L4426–L4433, L4922 | L56–L69, L436–L443, L3465, L3480–L3485, L4470–L4481, L4971 | §1.2, §2, §21 tablosu, §21 listesi ve §30/10 aynı beş sınıfı aynı adlarla sayar: (1) runbook komutları, (2) dosya aktarımı, (3) ön-pencere insan ağ işlemleri, (4) karar kanalı, (5) sesli görüşme; §34.2 "Ağ iddiasının kapsamı" satırına tur-2 notu |
| L-d — §26.2 E2 satırı | L3774 | L3818 | `E2_INBOUND_TRANSFER_RECEIVED=True` (ve N-1 gereği `E2_KEY_CHANNEL`) eklendi; §6.4 evidence satır listesine de eklendi (L1216–L1219) |
| Observation — `<container-file>` tanımı | L120 | L124 | Örtüşmezlik listesine `<container-root>` ve `<container-temp>` eklendi; §13.8 koduyla eşit |
| Observation — sistem Temp kaydı | L990–L993 | L1001–L1008 | Kayıt oturumu insan-only; ekrandaki mutlak yol evidence'a, belgeye veya bir AI oturumuna yazılmaz/aktarılmaz |
| Observation — pencere içinde yeni form sürümü | L1326 | L1351–L1356 | §6.6/3: içerik penceresi içinde yeni e-imzalı sürüm → DUR (Y20); UYAP doğrulaması yalnız pencere dışında |
| Observation — §34.6 tablosu | L5002, L5020 | L5053–L5056, L5074–L5075 | Eksik sonuç hunk'ları (`0e2e9c4e` → `a95f8291`) tek satırla eklendi; "yeni satır" sütununun hangi sürüme ait olduğu yazıldı |
| Low — §34.2 (tur-2 yeniden inceleme) | L4922 | L4971 | tur-2 yeniden inceleme Low: §34.2 satırı düzeltildi |

**Uygulama notları.**

- **N-1 ve kapı yönü.** Değişiklik hiçbir kapıyı gevşetmez: sesli görüşme
  dışındaki her parola kanalı artık açıkça DUR'dur. Sesli görüşmenin
  gerçekten sesli olduğu ve bu cihazdan yapılmadığı operatörün beyanına
  dayanır; mekanik olarak doğrulanmaz (§32/38 ile aynı sınıf bir sınır).
- **`<zaman-damgası>`** yalnız zamanı taşır; görüşmenin içeriği, numarası
  veya karşı tarafın adı yazılmaz (§1.5).
- **Ayrıştırma.** Bu turda PowerShell kod bloğu eklenmedi veya
  değiştirilmedi; bütün blokların hash'i `a95f8291` sürümüyle aynıdır.

### 34.8 Revizyon 2

YENİ. Kaynak sürüm: `4f5c37e` (= `c2a7dbc`; SHA-256
`1397ea07ad0c56e689d073ccbfc0b74177edc39847c5895f69596b1bf9f08699`, 5132
satır). Girdi: e11bab73 delta provasının bağımsız incelemesi (§0; SHA-256
`29d0038d…6352`; verdict `REHEARSAL_EVIDENCE_VERIFIED`), §4 "Runbook
revizyonu için konsolide bulgu listesi" maddeleri 1–9, ve aynı kökteki
`run\findings.md` ile bağlı kayıtlar. Kullanıcı kararları K-R2-1…K-R2-10
(2026-10-12). Yalnız bu dosya değişti; kod, şema, veri, test, başka
runbook veya `CLAUDE.md` değişmedi; LOCKED bir sözleşmeye dokunulmadı.
Yazılırken hiçbir runbook komutu çalıştırılmadı; değişen ve yeni bloklar
yalnız `ParseInput` ile denetlendi. Aşağıdaki "Bulgu → satır eşlemesi"
tablosunda "eski satır" `4f5c37e`'deki, "yeni satır" remediasyondan
önceki revizyon 2 taslağındaki (SHA-256
`3eb5e745cb61b31773267c2d268da44ebe0e59ff8a4cc3fe3e2a579cf2c15975`, 5399
satır) satır numarasıdır; remediasyon (aşağıda) bu numaraları
kaydırmıştır. Bu tur §34.6 ve §34.7'deki "yeni satır" numaralarını da
kaydırmıştır.

**Kullanıcı kararları.**

| Karar | İçerik |
|---|---|
| K-R2-1 | Kabul edilen tek biçim başlıkları açık AES-256 7z; tek PDF, klasörsüz, nötr dosya adı; dosya avukatına karar kanalında teknik not |
| K-R2-2 | Önceden onaylı yedek yöntem **yok**: `$null` borusu davranışı Δ1'de ölçülür; 7z dönmezse DUR ve ayrı karar |
| K-R2-3 | Parola: 29 sembol (A–Z eksi I, O, Q, W, X; 2–9), 20 karakter, 4'erli 5 grup, geri okuma, rastgele üretim |
| K-R2-4 | Yalnız kâğıt; `SEVENZIP_RC=0`'dan sonra aynı gün imha; `E2_PASSWORD_PAPER_DESTROYED` |
| K-R2-5 | Tek ek deneme yalnız `SEVENZIP_RC=2` + "Wrong password" + `X_ENTRY_COUNT=0`; ikinci hata DUR |
| K-R2-6 | Yalnız pencere boyunca kapatma; tarama iki kez, en az 2 dakika arayla; sistem ayarı değişikliği yok; §1.6/5 listesine `ChatGPT` |
| K-R2-7 | Yerleşik optik sürücü: medya-yok kuralı; Y5/H40 |
| K-R2-8 | En az 1 görünür karakter; H43 |
| K-R2-9 | Komut satırı denetimi: yazılı beyan repo dışında; evidence'a yalnız `CMDLINE_AUDIT_DECLARATION sha256=` |
| K-R2-10 | §0 e11bab73 pinleri; bu bölüm; §34.4 tabanı e11bab73; değişen/yeni bloklar ve Δ5 "Yeniden/Yeni" |

**Bulgu → satır eşlemesi.**

| Bulgu | Eski satır | Yeni satır | Değişiklik |
|---|---|---|---|
| R-D-7ZFOLDER (zorunlu) | L1258–L1262, L1265–L1272, L1276, L4685–L4687 | L1352–L1365, L1368–L1377, L1381–L1387, L4845–L4857 | Klasör = klasör işareti (`Folder = +` veya `Attributes`'ta büyük `D`) **ve** `Size`/`Packed Size` 0 veya boş; diğer her girdi dosya, her dosya `Encrypted = +` ve `7zAES`; `SEVENZIP_FOLDER_ENTRY_COUNT` bilgi satırı; küçük `d` (Unix) → tanınmaz → `STOP`; §32/30 sınır cümlesi |
| R-D-7ZPROMPT (zorunlu) | L1249 sonrası, L1258–L1262, L1265, L4685–L4687 | L1313–L1324, L1352–L1365, L1368, L4845–L4857 | `7z l -slt` standart girdisi `$null` borusu ile boş; listelemede parola istenmez; başlıkları şifreli arşiv → `STOP`; gönderen kuralı (başlık açık, tek PDF, klasörsüz, nötr ad; karar kanalında teknik not); dönmezse DUR (K-R2-2); §32/30 |
| R-D-TRKBDPW (zorunlu) | L1249 sonrası, L1283–L1289, L3720, L3818, L4492–L4494 | L1325–L1343, L1394–L1411, L3871, L3969, L4648–L4652 | Parola alfabesi/uzunluğu/okuma; yalnız kâğıt ve elle yazma (yapıştırma kural gereği yok); alfabe dışı karakter → yeni parola + yeni arşiv; kâğıt imhası; açma bloğu `attempt` + `X_ENTRY_COUNT`; tek ek deneme kuralı (K-R2-5); Y5, §26.2 E2, §30/13 |
| R-D-E18PENDING (zorunlu) | L3363 sonrası, L3400 sonrası, L3991 | L3499–L3508, L3546–L3551, L4142–L4147 | Durum bloğu yalnız approval öncesi kapı; approval pending'i silmez (`src/deadline_approval.py` L46, L50, L283–L342, L1408, L1476); bayt eşitliği yalnız deadline katmanında (O-2); kalıcı pending'ler §28.2 beklenen yollarında |
| L-1 kanal süreçleri (zorunlu) | L376–L378, L838 sonrası, L3699, L3813 | L381–L384, L881–L901, L3850, L3964 | §1.6/5 listesine `ChatGPT`; §4.3 (a) kapatma prosedürü (tepsi "Çık", "OneDrive'ı kapat", Görev Yöneticisi; iki tarama ≥ 2 dk); sistem ayarı değişikliği yok; H40; §26.2 Kanal |
| R-D-EOPTICAL (önerilen) | L747 sonrası, L3699, L3720, L3817, L4492–L4494 | L763–L789, L3850, L3871, L3968, L4648–L4652 | Yerleşik optik sürücü medya-yok kuralı ve yeni blok; DUR satırları (Y5, H40); §26.2 Kapsayıcı; §30/13 |
| R-D-IMGPDF (önerilen) | L646, L1795 sonrası, L1798 sonrası, L1830, L3702, L3822 | L652–L653, L1918, L1922–L1932, L1964–L1965, L3853, L3973 | `TEXT_VISIBLE` satırı (en az 1 görünür karakter); `STOP TEXT_VISIBLE=EMPTY` → H43; §4.2/3, §11.2/6, §26.2 Intake |
| F-0.8-CMDLINE-AUDIT (önerilen) | L707, L3811 | L714–L722, L3962 | `CMDLINE_AUDIT_KEY=PRESENT` bulgudur; bu cihazda ölçüldü; yazılı beyan zorunlu; `CMDLINE_AUDIT_DECLARATION sha256=`; §26.2 Başlangıç |
| O-3 (açıklama) | L3991 | L4142–L4147 | `facts_llm_…` adı tarihsel sabit (§15.1, §22.1); kod değişikliği yok, ayrı backlog |
| K-R2-10 (kayıt) | L13–L14, L31, L4531–L4533, L5002 sonrası, L5035 sonrası, — | L13–L18, L35–L36, L4689–L4693, L5173–L5183, L5217–L5222, §34.8 | Üst uyarı; §0 e11bab73 pinleri; §32/1; §34.4 devralma tabanı ve revizyon 2 satırları; bu bölüm |

**Kod blokları.** Numara, son prova planının kod bloğu ekindeki
numaralandırmadır (§1.5 bloğu = N0); SHA-256 blok gövdesinin (çit
satırları hariç, LF ile birleştirilmiş, sonda LF) baytları üzerindedir.

| Eski | Yeni | Bölüm | Eski SHA-256 | Yeni SHA-256 | `ParseInput` |
|---|---|---|---|---|---|
| — | N3 | §4.2/10 | — | `6bbb9e0c0422baa967edb15d56e94b350a078de37ab6de8f3d5fc892c455a1d4` | 0 hata |
| N3 | N4 | §4.3 (a) | `c8699639a33af810b73064c7cbdd378175996580618ae87d5f4754c5c3cefe8d` | `53c05a95ca3560b98d4a1381624e241017c3a3e6507bba834cb5eb61021443b1` | 0 hata |
| N13 | N14 | §4.4/6 | `2938bf33bc3d83c335584fe62534c534761fed6594fdf295aa2815e096454f91` | `60fe475b9308a068dac695533e8b7dfaf00aab7b339b7ff39541fba12f681403` | 0 hata |
| N15 | N16 | §6.4 | `d35981072b3fa8c5e4c547c26083541d77a82cc61bc98be7baddd5dbb3c3980c` | `3f17c6eb77097217f5ee780c3b304266d0b1c3189827b1b9d92b488e1b96e4eb` | 0 hata |
| N16 | N17 | §6.4 | `9f938954e69168215027476377d3129e519dc4bbad658cefc7bfca3f1e5c75d9` | `e4e3552154c7f8488b103c0ab381708eb634325bcda523af1c06b2640580c091` | 0 hata |
| N23 | N24 | §11.2 | `420cedb044e981601da4127bee2c2501419686ca70bf03d7ca6e2b69699acbc7` | `f0db8ae3037fcfea9dd07ad202d27635bb03fe8e4cbbddfbfd06a4a084805c54` | 0 hata |

Blok sayısı 104 → 105 (5 değişen + 1 yeni). Kalan 99 blok `4f5c37e` ile bayt-bayt aynıdır ve
aynı sırada durur (blok hash'leriyle ölçüldü); eski N3 ve sonrasındaki her
blok numarası yeni optik blok nedeniyle bir artar. (Remediasyondan önceki
taslakta yeni N3 `d2fc34dc…`, N4 ve N14 değişmemişti; remediasyon bu üç
bloğu değiştirdi, aşağıda.)

**Uygulama notları.**

- **Kapı yönü.** Hiçbir kapı gevşetilmedi. Klasör tanıma yalnız boyutu
  sıfır girdileri atlar; her dosya girdisi yine `Encrypted = +` ve
  `7zAES` taşımalıdır. İstem bastırıldığında başlıkları şifreli arşiv
  fail-closed `STOP` verir. Parola, alfabe, kâğıt ve elle yazma kuralları
  sıkılaştırmadır; kâğıt yeni bir fiziksel kopya yaratır ve imhası
  kayda bağlıdır (K-R2-4). Tek ek deneme (K-R2-5) şifreleme kapısını
  değil, yalnız "ilk `SEVENZIP_RC` ≠ 0 → DUR" kuralını üç koşulla bir kez
  yumuşatır; bilinçli bir kullanıcı kararıdır. Optik sürücü kuralı
  (K-R2-7), yerleşik ve çıkarılamayan bir sürücü için harici disk
  çiftinin yerine "medya takılı değil" ölçümünü koyan kapsamlı bir
  istisnadır; ölçülemeyen değer `STOP`'tur.
- **Kapsam dışı.** İncelemenin M-1, L-2…L-8 bulguları prova planı ve ajan
  disiplini maddeleridir; runbook değişikliği gerektirmez. O-1, O-2 (§18.4
  notunda kullanıldı) ve O-4…O-11 runbook değişikliği gerektirmez. O-3'ün
  kod tarafı (pending adı) ayrı backlog maddesidir.
- **Delta prova.** Δ1–Δ5 (§34.4 revizyon 2 satırları) ayrı bir turda ve
  ayrı kullanıcı yetkisiyle yapılır; bu tur onları yetkilendirmez.

**Remediasyon (rev2).** Revizyon 2 taslağının (SHA-256 `3eb5e745…5975`)
bağımsız incelemesi `READY_FOR_NARROW_REMEDIATION` verdi; kullanıcı dar
remediasyonu onayladı. Aşağıdaki kimlikler (M-1, L-1…L-5, O-1, O-2, O-6,
O-7) **bu incelemeye** aittir; e11bab73 incelemesinin aynı adlı
kimlikleriyle karıştırılmaz. Yalnız bunlar işlendi; kapsam genişletilmedi.
"Eski satır" `3eb5e745` taslağındaki, "yeni satır" bu sürümdeki satır
numarasıdır.

| Bulgu | Eski satır | Yeni satır | Değişiklik |
|---|---|---|---|
| M-1 — parola hatası gözlemi | L1403–L1411, L3969 | L1466–L1487, L4045 | Operatörün ekran gözlemi boolean olarak kayda girer: `SEVENZIP_WRONG_PASSWORD_SHOWN=True/False attempt=<k>`; ölçüt `Wrong password` alt dizesi; mesaj metni ve girdi adı evidence'a yazılmaz; ek deneme yalnız `SEVENZIP_RC=2` + `SEVENZIP_WRONG_PASSWORD_SHOWN=True` + `X_ENTRY_COUNT=0`; §26.2 E2 |
| L-1 — başarı tanımı ve DUR dalı | L1403–L1411, L3871 | L1466–L1487, L3947 | Başarı = `SEVENZIP_RC=0` **ve** `X_ENTRY_COUNT=1`; DUR cümlesi ve Y5 yalnız hata dalına uygulanacak biçimde; başka her birleşim DUR |
| L-2 — optik sürücü teknik kaydı | L768–L787, L1130–L1134, L3871, L3968 | L773–L797, L1146–L1162, L3947, L4044 | Teknik kayıt bloğu (§4.4/6) `CDROM_DRIVE_COUNT` ve `OPTICAL_DRIVE_LETTERS` yazar (bu cihazda `1`, `E:`; farklıysa DUR, Y5); optik blok her ölçümde kayıtla birebir eşleşmeyi denetler (`OPTICAL_DRIVES_MATCH_RECORD`; eşleşmezse DUR, Y5); USB optik sürücü harici disk kuralına tabi; §26.2 Kapsayıcı |
| L-3 — kanal taraması zaman damgası | L871 sonrası, L895, L3964 | L882, L906–L911, L4040 | Tarama bloğu `AI_CHANNEL_SCAN at=<zaman-damgası>` basar; iki tarama damgalarıyla kaydedilir; aradaki ≥ 2 dk kayıttan doğrulanır; damga eksik → DUR (H40); §26.2 Kanal |
| L-4 — alfabe dışı karakter | L1337–L1343, L3871, L3969, L4652 | L1390–L1406, L3947, L4045, L4728–L4729 | Eski kâğıt hemen imha (`reason=rejected`); eski `transfer.7z` exact-path silinir; yeniden gönderim en fazla bir kez; ikinci arşivde de alfabe dışı/geri okuma tutmazsa DUR (Y5); kâğıt imhası `reason=used/rejected/stopped`; ek deneme pilot boyunca toplam bir kez; §26.2 E2, §30/13 |
| L-5 — §34.4 optik satırı | L5218–L5219, L5221 | L5295–L5297, L5299 | Optik blok satırı "Yeni, tek-çalışım"; teknik kayıt bloğu için yeni "Yeniden, tek-çalışım" satırı; açma ve kanal satırları güncellendi |
| O-1 — gönderen kuralı | L1314–L1315 | L1342–L1347 | "Kabul edilen tek biçim" → "Gönderen kuralı"; kapı daha geniş biçimi geçirebilir, `SEVENZIP_FOLDER_ENTRY_COUNT` yalnız bilgi |
| O-2 — `$null` borusu çekincesi | L1323 | L1355–L1357 | "Δ1'de doğrulanır; doğrulanana kadar varsayımdır" |
| O-6 — revizyon 1/2 ayrımı | L112–L115, L338–L340 | L112–L117, L340–L345 | §1.4 ve §1.6/3 D13 paragrafı revizyon 1 (e11bab73'te prova edildi) ile revizyon 2'yi (henüz prova edilmedi) ayırır |
| O-7 — telefon alfabesi | L1331 | L1365–L1384 | 29 sembol için Türk telefon alfabesi tablosu; harf harf okuma ve geri okuma |
| Low-A — geçersiz ikinci tarama (ikinci inceleme) | `85e67f0c` L886, L909–L911, L3926 | L892–L895, L918–L922, L3937 | Genel "kapat ve yeniden tara" kuralı yalnız ilk taramadan önceki kapatma için; kısa aralıklı (< 2 dk) ikinci tarama geçersiz sayılır ve yeniden yapılır, **ancak** geçersiz taramada da `AI_CHANNEL_PROCESS_COUNT` > 0 → DUR (H40), kapatılıp yeniden taranmaz; H40 satırı hizalandı |
| Low-B — optik sürücü pencere öncesi/içi (ikinci inceleme) | `85e67f0c` L789–L793, L795–L799, L3926, L3947 | L789–L791, L793–L805, L3937, L3958 | Pencere öncesinde `OPTICAL_DRIVES_MATCH_RECORD=False` veya `OPTICAL_MEDIA_LOADED=True` → sanal sürücü/medya çıkarılır, optik blok **bir kez** yeniden çalıştırılır, ikinci ölçüm de eşleşmezse DUR (Y5); `CDROM_QUERY=FAIL`/`UNKNOWN` → yeniden çalıştırma yok, DUR (Y5); pencere içinde her uyuşmazlık doğrudan DUR (H40); "Beklenen" paragrafı ile DUR satırları arasındaki çelişki kaldırıldı; Y5 ve H40 satırları hizalandı |

Remediasyonda değişen bloklar: yeni N3 (`d2fc34dc…` → `6bbb9e0c…`), N4
(`c8699639…` → `53c05a95…`), N14 (`2938bf33…` → `60fe475b…`); üçü de
`ParseInput` 0 hata. Taslağın diğer 102 bloğu bayt-bayt aynı kaldı
(ölçüldü).

- **Kapı yönü (remediasyon).** M-1 ek deneme koşulunu ölçülebilir bir
  gözleme bağlar (daraltır). L-1 başarıyı `X_ENTRY_COUNT=1` ile daraltır.
  L-2 optik sürücüye kayıtla eşleşme şartı ekler. L-3 ikinci taramanın
  zamanını kayıttan doğrulanabilir kılar; 2 dakikadan kısa aralıklı ikinci
  tarama yalnız yeniden yapılır, kabul edilmez. L-4 yeniden gönderimi bir
  kezle sınırlar. O-1/O-2/O-6/O-7 metindir; kapıyı değiştirmez.

### 34.9 Revizyon 3

YENİ. Kaynak sürüm: `977a5e7` (revizyon 2; SHA-256
`b4f4f53f0d8f93166b015f5c2ef40fad8b23adee549ae2a7485a87e8dd7ce802`, 5531
satır). Girdi: delta2 provası (709b329c) ve onun bağımsız kanıt
incelemesi (§0; SHA-256 `94eb7299…fd51`; verdict
`REHEARSAL_EVIDENCE_VERIFIED`; Critical 0, High 1, Medium 2, Low 4,
Observation 6), aynı kökteki `run\findings.md` ve bağlı kayıtlar, ve
revizyon 3 kapsam önerisi (§0; `scope.md` + `scope_addendum.md`; çelişkide
ek geçerli). Yalnız bu dosya değişti; kod, şema, veri, test, başka runbook
veya `CLAUDE.md` değişmedi; LOCKED bir sözleşmeye dokunulmadı. Yazılırken
hiçbir runbook komutu, kit betiği, 7z, PostgreSQL, CLI veya test
çalıştırılmadı; değişen ve yeni bloklar yalnız `ParseInput` ile denetlendi
ve büyük-küçük harfe duyarsız karşılaştırma operatörleri için mekanik
olarak tarandı (bulgu yok).

**Karar günlüğü.**

| Kayıt | İçerik |
|---|---|
| `SCOPE_APPROVED at=2026-10-13T09:40+03:00` | Kullanıcı onayı (planlayıcı önerisiyle): kapsam `scope.md` (`ed7fc118…774a`) + `scope_addendum.md` (`ed0b9792…86e9`); iki hash diskten doğrulandı |
| Zaman damgası düzeltmesi | Onay mesajındaki `SCOPE_APPROVED at=2026-10-13T01:00+03:00 (yaklaşık)` yanlıştı; kullanıcının düzeltmesiyle doğru değer `at=2026-10-13T09:40+03:00`'dır (onayın ve mesajın gönderildiği an) |
| `USER_DECISION S-1=A, S-2=öneri at=2026-10-13T09:50+03:00` | Yazım sırasında açılan iki açık soru (planlayıcı önerisiyle, kullanıcı onayı). S-1 notu: `kit-values.txt`'nin `%USERPROFILE%` altında yol taşımadığı mekanik denetimi başarısız olursa kit kurulmaz ve **DUR** olur; sessiz düzeltme yoktur |
| `USER_DECISION at=2026-10-13T10:30+03:00` | Bağımsız inceleme (`review\20261013-101756-independent-runbook-rev3-review.md`, `565039ea…c4c6`; `READY_FOR_NARROW_REMEDIATION`) sonrası kararlar (planlayıcı önerisiyle, kullanıcı onayı): H-1=A, M-1 (sınır kaldırılır), M-3 (`a8` ön koşulu `a5` PASS), M-2/L-1/L-2/L-3/L-4/O-3 incelemenin dar düzeltmeleriyle, O-1/O-2/O-4…O-9 değişiklik yok; ayrıntı aşağıda "R3 düzeltme turu" |
| `USER_DECISION at=2026-10-13T17:10+03:00` | Bağımsız yeniden inceleme (`review\20261013-170139-independent-runbook-rev3-rereview.md`, `16af7b62…bbf`; `READY_FOR_COMMIT=YES`, 0C/0H/0M/1L/9O) sonrası kararlar (planlayıcı önerisiyle, kullanıcı onayı): Obs-1 — "K-R3-3 yalnız operatörün yazdığı adlara uygulanır" yorumu onaylandı, K-R3-3 satırı bu kapsamı açıkça söyler; Low-1 — `a6`'daki DUR iletisi `Write-KitDur 'a6' 'READBACK_RECORD_INVALID'` ile değiştirildi; Obs-7 — §32/39'a tek cümle; diğer gözlemler değişiklik yok; ayrıntı aşağıda "R3 son dar düzeltme" |
| `USER_DECISION Obs-7=ii at=2026-10-13T17:20+03:00` | Obs-7 cümlesinin atıf yaptığı kural tek sayfada yoktu (açık soru). Karar (planlayıcı önerisiyle, kullanıcı onayı): tek sayfaya (N114) parola adımlarının yanına "Ekranda 7z'nin 'Enter password' istemi yoksa HİÇBİR ŞEY yazmayın ve Enter'a basmayın." kuralı eklenir; §32/39'daki Obs-7 cümlesi bu kurala atıf yapar. Bu değişiklik liste dışı değildir, bu kullanıcı kararıyla yapılır |

**Kullanıcı kararları.**

| Karar | İçerik |
|---|---|
| K-R3-1 | **EVET, değişiklikle:** adım betiklerinin tam metni bu runbook'ta hash'i sabitlenmiş kod blokları olarak yer alır (Ek R3); her koşuda ajan onları bayt-bayt kopyalar ve hash'i doğrular, **yeniden üretmez**. Betikler repoya ayrı dosya olarak girmez |
| K-R3-2 | Pencere kâğıttaki tek komutla açılır (`-NoProfile -ExecutionPolicy Bypass -NoExit -Command`), pinli önyükleyici `ac.ps1` yalnız `a2`…`a9` komutlarını tanımlar; `$hk`, `iex` yükleyici satırı ve değişken ataması yoktur (§4.3 b, Ek R3/3) |
| K-R3-3 | Adlar `a2`…`a9`: küçük `a` + 2–9; `0`, `1`, `O`, `I`, `l`, `i`, `ı`, `İ` operatörün yazdığı hiçbir komut veya kayıt adında yok. Kural **yalnız operatörün yazdığı adlara** uygulanır; kitin ve ajanın kendisinin oluşturduğu adlar (oturum dizini `s<k>`, `pins.txt`, `kit-values.txt`, `DUR-lifted-<n>.txt`, `dur-lift-<n>.txt` vb.) kapsam dışıdır (kullanıcı kararı `at=2026-10-13T17:10+03:00`) |
| K-R3-4 | **EVET, ekle:** iki kanal taraması pencere başında (`a2`, `a3`; 120 sn mekanik bekleme, erken `a3` kayıt yazmaz); ayrıca son adım `a9` kullanıcıdan ek işlem istemeden otomatik bir kapanış taraması yapar ve sonuç sıfır değilse bulgu/DUR kaydı yazar (§4.3 a) |
| K-R3-5 | N16: konsolsuz süreç, kapalı stdin, stdout/stderr yakalama, 10 sn duvar saati bekçisi, öncesi/sonrası damgaları ve süreç sayıları (§6.4) |
| K-R3-6 | Runbook'a yalnız "çıkış ≠ 0 → STOP" ve yeni boolean'lar yazılır; A1'in kesin çıkış kodu delta3 ajan fazında ölçülüp prova beklentisine sabitlenir |
| K-R3-7 | 7z'nin kendi parola istemi korunur; Caps Lock kapalıyken 7z çağrılmaz, deneme harcanmaz; `CAPS_LOCK` her denemede kayda girer |
| K-R3-8 | `<evidence-dir>\DUR.txt` küresel kilidi (CreateNew), sıra kapısı (her adım öncekinin `STEP_RESULT=PASS`'ini ister), pin uyuşmazlığı da kilitler; `a8` ve `a9` kilitliyken de çalışır; kâğıt imhası `reason`'u kayıtlardan türetilir |
| K-R3-9 | Konsol seçim kipine karşı yalnız talimat ("fare ile tıklamayın; 'Seç' görürseniz Esc"); süreç içi QuickEdit kapatma yok |
| K-R3-10 | Tek sayfalık, sade Türkçe, yazdırılabilir adım listesi şablonu (Ek R3/5, N114); değerler kit kurulumunda doldurulup kâğıda basılır |
| K-R3-11 | Kapsam yalnız pencere açılışı (kanal kapısı) ve E2 aktarım/listeleme/açma/kâğıt; kanal adımları (`a2`, `a3`, `a9`) her içerik oturumunda yeniden, E2 adımları (`a4`–`a8`) bir kez; zincirin geri kalanı (§11–§28) revizyon 2 bloklarıyla |
| K-R3-12 | Kit `<evidence-dir>\kit\`, kayıtlar `<evidence-dir>\steps\s<k>\` ve `<evidence-dir>\steps\e2\`, kilit `<evidence-dir>\DUR.txt`; §10.5 ve §13.8 değişmez (kontrol edildi: `<external-root>` altında yeni çocuk yok, `<restricted-dir>`'e dosya girmez) |
| S-1 = A | §1.5'e dar istisna: `kit-values.txt` yalnız kapsayıcı ve araç yollarını taşır, `%USERPROFILE%` altında yol taşımaz; ajan (kurulumda) ve `ac.ps1` (her yüklemede) mekanik denetler; başarısız → **DUR** |
| S-2 = öneri | Kit modunda geri okuma tutmazsa veya alfabe dışı karakter duyulursa **DUR** ve `reason=rejected`; revizyon 2'nin tek yeniden gönderim yolu kit ile yürütülmez (sıkılaştırma) |

**Bulgu → değişiklik eşlemesi (delta2 kanıt incelemesi, `94eb7299…`).**

| Bulgu | Değişiklik (bölüm) |
|---|---|
| H-1 — H2 enstrümantasyonu asılma / ekran donması / ikinci süreç ayrımını yapamıyor | N16 yeniden yazıldı: konsolsuz 7z, kapalı stdin, stdout/stderr yakalama, 10 sn bekçi (`STOP SEVENZIP_LIST_TIMEOUT=True` → DUR), `LIST_CALL_AT`/`LIST_RETURN_AT`, `SEVENZIP_PROC_COUNT_BEFORE/AFTER`; kit her satırı anında dosya + ekrana yazar (§6.4, Ek R3/4) |
| M-1 — A1 beklenen sonucu ayırt edici değil | `SEVENZIP_LIST_RC`, `SEVENZIP_TYPE_7Z_SEEN`, `SEVENZIP_STDERR_LINE_COUNT`, `SEVENZIP_STDERR_BREAK_SEEN`, `SEVENZIP_STDERR_ENC_OPEN_FAIL_SEEN`; kesin RC delta3'te (K-R3-6) |
| M-2 — Pencere H prosedürü insan tarafında üç kez kırıldı | Ek R3 kiti: tek açılış komutu, `a2`…`a9`, küresel `DUR.txt` kilidi, sıra kapısı, kanal kapısı ilk adım, kapanış taraması `a9`, tek sayfa (§4.3, Ek R3) |
| L-1 — A-DEV-D1.0-DIR anlatıda yok | Prova disiplini maddesi; runbook değişikliği gerektirmez (delta3 planı: her sapma `findings.md`'de ayrı satır ve mekanik sayım) |
| L-2 — `PAPER_AFTER_SUCCESS` başarıyı aramıyor | Prova planı kuralıdır (Faz B); runbook karşılığı `a8`'in `reason` türetmesidir (başarı = `ATTEMPT_OUTCOME=SUCCESS` + `STEP_RESULT=PASS`); delta3 planında kurala son denemenin `SEVENZIP_RC=0` ve `X_ENTRY_COUNT=1` koşulu eklenir |
| L-3 — H6 `reason` serbest girdi | `a8` `reason`'u türetir; operatörden almaz (§6.4) |
| L-4 / F-D2-TRCULTURE — N4 tr-TR'de büyük `I` | N4: `[regex]::IsMatch(…, 'IgnoreCase, CultureInvariant')` (§4.3 a) |
| 7ZFOLDER sayım dersi (A-DEV-D1.0-DIR) — 7-Zip 26.04 `Folder = +` basmıyor | Metin: klasör tanıma fiilen `Attributes` büyük `D`'ye dayanır; blok mantığı değişmedi (§6.4, §32/30) |
| O-1 — günlük/geçmiş okunamadı; H2 BELİRSİZ | Planlayıcı kararı gereği geriye dönük inceleme yok; çözüm ölçüm aracının düzeltilmesi ve delta3'te yeniden ölçümdür |
| O-2 — Δ5 FAIL nedeni U-2'nin yapılmaması | Kapatma `a2`'den önce; `a2` sayı ≠ 0 → kilit (§4.3 a) |
| O-3, O-4 — Oturum B betikleri ve Oturum A yazıcı kodu kökte pinli değil | Prova disiplini (delta3 planı: her fazın betikleri kök içinde pinli) |
| O-5 — `$LASTEXITCODE` alma yeri | N17 artık çıkış kodunu süreç nesnesinden alır (`SEVENZIP_RC` veya `STOP SEVENZIP_RC=UNKNOWN`) |
| O-6 — `pw.txt`, arşivler ve boş `x\` delta2 kökünde | Kapsam dışı; silme ayrı kullanıcı kararıdır |
| İnceleme §6/1–4, 7, 8 | Ek R3 kiti, §4.3 a, §6.4 |
| İnceleme §6/5 | N16 (H-1, M-1) |
| İnceleme §6/6 | Yalnız talimat (K-R3-9) |
| İnceleme §6/9 | N4 (L-4) |
| İnceleme §6/10 | Runbook "asılmaz" demez; davranış delta3'te ölçülür, o zamana kadar varsayımdır (§6.4, §32/30) |

**"Break signaled" hipotezi (HK-1; kaynak okuması, ölçülmedi).** Kapsam
oturumunda 7-Zip açık kaynak kodu (GitHub `ip7z/7zip`, `main` dalı;
26.04 ile birebir aynı olduğu doğrulanmadı) okundu:
`OpenCallbackConsole.cpp` parolayı yalnız tanımlı değilse ister;
`UserInputUtils.cpp` boş girdide EOF'ta `E_ABORT` döndürür; `List.cpp`
`E_ABORT`'u yukarı taşır; `MainAr.cpp` `E_ABORT`'ta stderr'e "Break
signaled" basar ve kullanıcı kesmesi koduyla çıkar. Buna göre delta2
H2'deki "Break signaled" iletisi, kaydın 55 ms dönüşüyle çelişmeden, 7z'nin
kendisi tarafından Ctrl+C olmadan basılmış olabilir. Bu **kanıtlanmış
değildir**; delta2 için olay günlüğü ve geçmiş dosyası okunmamıştır
(planlayıcı kararı). Delta3 bunu A1 listelemesinde
`SEVENZIP_STDERR_BREAK_SEEN`, `SEVENZIP_LIST_RC` ve bekçi satırlarıyla
ölçer. Hiçbir kapı bu hipoteze dayanmaz.

**Bölüm → değişiklik.**

| Bölüm | Değişiklik |
|---|---|
| Üst uyarı, §0, §1.4, §1.6/3, §32/1 | Delta2 pinleri, revizyon 3 kapsam pinleri, prova durumu |
| §1.5 | Dar istisna: `kit-values.txt` (S-1) |
| §1.6/5 | Kanal kapısının kitle yürütülmesi; yeni "İnsan adım kiti" maddesi |
| §4.3 (a) | N4 kültür düzeltmesi; "Kit ile yürütme" paragrafı (`a2`, `a3`, `a9`, kilit, yardım yok, fare uyarısı) |
| §4.3 (b) | Açılış komutu (`-ExecutionPolicy Bypass`, `ac.ps1`), `CONTENT_SESSION_EP=Bypass`; N6 değişmedi |
| §6.4 | Listeleme metni ve N16; HK-1 notu; `Folder = +` notu; Caps Lock; N17; E/H gözlem soruları; kit başarı/ek deneme koşulları; S-2; `reason` türetme |
| §25.1 | H40, H53, Y5 satırları |
| §26.1, §26.2 | Kit ve adım kayıtları metadata'dır; Kanal, Kit (yeni satır) ve E2 satırları |
| §32/30, §32/39 (yeni) | Yöntem sınırı; kit sınırları |
| §34.4 | Revizyon 3 devralma satırları |
| §34.9, Ek R3 | Bu bölüm; kit blokları ve tek sayfa |

**Kod blokları.** Numara, §34.8'deki numaralandırmadır (§1.5 bloğu = N0);
SHA-256 blok gövdesinin (çit satırları hariç, LF ile birleştirilmiş, sonda
LF) baytları üzerindedir. Kit dosyalarının baytları bu gövdeye **eşittir**
(Ek R3/1).

| Eski | Yeni | Bölüm | Eski SHA-256 | Yeni SHA-256 | `ParseInput` |
|---|---|---|---|---|---|
| N4 | N4 | §4.3 (a) | `53c05a95ca3560b98d4a1381624e241017c3a3e6507bba834cb5eb61021443b1` | `b216d82434a36e5b79963cedfff578c7bd065fb13fe03c2b5ca9557a480e520d` | 0 hata |
| N16 | N16 | §6.4 | `3f17c6eb77097217f5ee780c3b304266d0b1c3189827b1b9d92b488e1b96e4eb` | `326c9216f8eeedd922b1d7fca8b8584e87ccb29b2c21e2151a23b4199449b609` | 0 hata |
| N17 | N17 | §6.4 | `e4e3552154c7f8488b103c0ab381708eb634325bcda523af1c06b2640580c091` | `1ea37c4b84d31a24c1e938892a35c6375546d0461e8b89a9fb18c76fe0380cbb` | 0 hata |
| — | N105 | Ek R3 (`ac.ps1`) | — | `fd5f352d8c1abf9426af5d38642e7f51d040198db2fac9325b62880f4c193d17` | 0 hata |
| — | N106 | Ek R3 (`a2.ps1`) | — | `4cda7f064c96b7fb38cadd44088e473ab83901875dce852e85ae50a90cba6b5b` | 0 hata |
| — | N107 | Ek R3 (`a3.ps1`) | — | `2d2c79ebcf9cc4788ba7627ed4756689f6991aa22de4dfe454907ee098a5ce3f` | 0 hata |
| — | N108 | Ek R3 (`a4.ps1`) | — | `e1b73dafb2bb8201e4ce63676e3eda86f128251bc6278ec5174f786769d9a1b6` | 0 hata |
| — | N109 | Ek R3 (`a5.ps1`) | — | `81f7fc797ea98052143b8ab74d32473ca29bf865cb3ec9326c0cf4a212e6dfe4` | 0 hata |
| — | N110 | Ek R3 (`a6.ps1`) | — | `cd45441ad65352cba263415d8fd99432f1b3502fed7a645226b3218d9f53a0ef` | 0 hata |
| — | N111 | Ek R3 (`a7.ps1`) | — | `0e2da5ebefb7a94eaaae627b7f93d59cb7a8ba5d0f4b038877d3c8c559d00011` | 0 hata |
| — | N112 | Ek R3 (`a8.ps1`) | — | `73ed1b599c22e52dbb4c065f76cb11723f6da1e17d6d0a370a45b1307b57f940` | 0 hata |
| — | N113 | Ek R3 (`a9.ps1`) | — | `9193eab4b4ba28472c624ef54a5d2464c8821abdbef2950ed7236c49c91c3ea4` | 0 hata |
| — | N114 | Ek R3/5 (tek sayfa, `text`) | — | `ba942c6f221c198de49409a16beb97e06effae4fe9f11ae064fb25ecaa0cd1aa` | — (PowerShell değil) |

Tablodaki "Yeni SHA-256" değerleri R3 düzeltme turundan, R3 son dar
düzeltmeden, revizyon 4'ten ve revizyon 5'ten sonraki değerlerdir (N16,
N105, N112, N114 R3 düzeltme turunda, N110 ve N114 R3 son dar düzeltmede,
N105 revizyon 4'te, N105, N107, N108 ve N114 revizyon 5'te, N114 ayrıca
revizyon 5 tek sayfa netleştirmesinde değişti; aşağıda, §34.10 ve §34.11). Revizyon 5'in yeni blokları N115 ve N116
§34.11 tablosundadır.

Blok sayısı 105 → 115 (3 değişen + 10 yeni). Kalan 102 blok (N0–N3,
N5–N15, N18–N104) `977a5e7` ile bayt-bayt aynıdır ve aynı sırada durur
(blok hash'leriyle ölçüldü); yeni bloklar dosyanın sonundadır, mevcut
numaralar kaymaz.

**Uygulama notları.**

- **Kapı yönü.** Hiçbir kapı gevşetilmedi. Bekçi yeni bir `STOP` ekler;
  Caps Lock denetimi 7z'yi çağırmaz ve deneme harcamaz; kilit, sıra kapısı
  ve kapanış taraması yalnız durdurur; kit başarısı ve ek deneme koşulu
  revizyon 2'ye ek olarak parola isteminin görülmesini ister; S-2
  yeniden gönderim yolunu kit modunda kapatır. §1.5 istisnası (S-1) dar
  ve adlıdır, mekanik denetime bağlıdır.
- **Kapsam dışı.** §11–§28 bloklarının kite bağlanması; delta2 kökündeki
  sentetik artıkların silinmesi; QuickEdit'in süreç içi kapatılması;
  istem açmayan sahte `-p` yöntemi (kullanılmadı).
- **Delta3.** Revizyon 3'ün değişen ve yeni blokları ayrı bir turda ve
  ayrı kullanıcı yetkisiyle prova edilir (§34.4 revizyon 3 satırları);
  bu revizyon onları yetkilendirmez. Taslak kapsam: ajan fazı (kit
  kurulumu, N4 kültür ölçümü, N16'nın sekiz sentetik arşivde ve bekçi
  testinde ölçülmesi, A1'in kesin çıkış kodu ve HK-1, negatif
  kontroller), insan penceresi (tek sayfayla `a2`…`a9`, gerçek kapatma
  prosedürü), yeni ajan oturumunda kayıt ve ayrı bağımsız inceleme.

**R3 düzeltme turu (bağımsız revizyon 3 incelemesi `565039ea…c4c6`;
kullanıcı kararı `at=2026-10-13T10:30+03:00`).** Bu turun adı §34.6'daki
"remediasyon turu 1" ile karışmasın diye "R3 düzeltme turu"dur; bu
bölümdeki ve gövdedeki "inceleme H-1/M-1…/O-9" kodları bu incelemenin
bulgularıdır, yukarıdaki delta2 kanıt incelemesinin aynı adlı
bulguları değildir. Girdi: runbook SHA-256
`2683d088…56fa` (diskten doğrulandı) ve inceleme dosyası (diskten
doğrulandı). Yalnız bu dosya değişti; hiçbir runbook komutu, kit
betiği, 7z, PostgreSQL, CLI veya test çalıştırılmadı; değişen bloklar
yalnız `ParseInput` ile denetlendi ve hash'lendi.

| Bulgu | Karar | Değişiklik | Bölüm / blok |
|---|---|---|---|
| H-1 — kilitte silme oturumu tanımsız | A | `DUR.txt` varken açılan pencere **silme oturumudur** (yükleme anında belirlenir; `KIT_TEARDOWN_SESSION=True` `ac.txt`'ye ve her adım başlığına yazılır); `a2`/`a3` bu oturumda kilitte çalışır, `a4`–`a7` oturum bayrağıyla reddedilir (kilit sonradan kaldırılsa bile), `a8`/`a9` değişmez. Kilidin kaldırılması: yazılı kullanıcı kararından sonra ajan `DUR.txt`'yi silmeden yeniden adlandırır ve kayda yazar (tek cümle). Yorum notu: karardaki "yalnız taramayı yapan" ifadesi E2 ve ilerletme adımlarına karşıtlık olarak okundu; silme oturumu da bir içerik oturumu olduğundan (§4.3 b, §25.2) `a2` N6 ve `CONTENT_SESSION_EP` denetimlerini aynen yapar — kapı gevşemez | §4.3 (a) yeni paragraf ve "tek istisna" eki; §25.2 yeni paragraf; Ek R3/3; Ek R3/4 tablo (`a2`, `a3`) ve kural 1; N105 |
| M-1 — onaysız 9 oturum sınırı | Kaldırılır | Oturum numarası `s1, s2, …` üst sınırsız; `KIT_SESSION_LIMIT` dalı kaldırıldı. **K-R3-3 yalnız operatörün yazdığı adlara uygulanır** (oturum adı `s<k>`'yı operatör yazmaz) | Ek R3/3; N105 |
| M-2 — parola tuşlarının istemine taşması | İnceleme önerisi | `Clear-KitKeys` (tuş tamponu boşaltma) `Read-KitYesNo` başında, `Invoke-KitAttempt` sonunda ve `Invoke-KitStep` çıkışında | N105 |
| M-3 — kâğıt varken `a8` kayıt yazmayabiliyor | Ön koşul `a5` PASS | `a8` ön koşulu `steps\e2\a5.txt` `STEP_RESULT=PASS` (herhangi bir oturumda); geri okuma kaydı yoksa `reason=stopped`, varsa türetme değişmedi. **Bu, onaylı addendum E3.1 metninin kullanıcı onaylı değişikliğidir.** Yan etki: `a8` `a5` PASS ile `a6` arasında yazılırsa `a6` artık çalışmaz (kâğıt imha edilmiştir; doğru davranış) | §6.4; Ek R3/4 tablo (`a8`); N112 |
| L-1 — N16 bekçisinin iki zayıflığı | İnceleme önerisi | `Kill()` sonrası en çok 2 sn `WaitForExit`; çıkıştan sonra stdout/stderr okuması en çok 2'şer sn, aşılırsa `STOP SEVENZIP_LIST_TIMEOUT=True`; ekran donmasının yalnız adım düzeyi damgalardan dolaylı çıkarıldığı cümlesi | §6.4 bekçi metni; §32/30; N16 |
| L-2 — addendum E1 ve E3.2 eksik | İnceleme önerisi | Ek R3/2'ye yeni madde 6 (`Get-Command a2,…,a9` yeni `-NoProfile` alt süreçte boş olmalı; değilse DUR) ve `kit-build.txt`'ye `KIT_NAME_COLLISION_COUNT=0`; eski 6–8 → 7–9, Ek R3/5'teki atıf "madde 8" oldu. §34.4 N16 satırına büyük çıktılı arşiv ölçümü | Ek R3/2, Ek R3/5 giriş metni, §34.4 |
| L-3 — tek sayfa tek başına izlenebilir değil | İnceleme önerisi | §4.3 (a): runbook'un yapay zekâ özelliği taşımayan yerel bir görüntüleyicide salt-okunur açık tutulması yardım sayfası sayılmaz. Tek sayfa madde 3'e altı sınıf beyanı (§4.3 a Adım 2'nin mevcut kaydı; yeni kit adımı değildir) ve aynı görüntüleyici notu | §4.3 (a); N114 |
| L-4 — Ctrl+C ile yetim 7z | İnceleme önerisi | §32/39(a)'ya bir cümle (yetim süreç, eksik `LIST_RETURN_AT`/`STEP_RESULT`, sonraki `SEVENZIP_PROC_COUNT_BEFORE`) | §32/39 |
| O-3 — `<evidence-dir>` karakter denetimi yok | İnceleme önerisi | `ac.ps1` `KitEvid`'e `kit-values.txt` ile aynı karakter kümesi regex'ini uygular; geçmezse `KIT_LOAD_EVID_CHARS` → DUR | Ek R3/3; N105 |
| O-1, O-2, O-4…O-9 | Değişiklik yok | — | — |

**Liste dışı değişiklikler (zorunlu sonuç olarak yapıldı).**

1. Tek sayfaya (N114) silme oturumu satırı: "DUR GÖRÜRSENİZ: başka adım
   çalışmaz" ifadesi H-1 sonrası silme oturumuyla çelişeceği için
   (H-1'in tek sayfadaki karşılığı). Aynı nedenle tek sayfanın DUR
   tetikleyicisi "bir satır `DUR` ile başlıyorsa" oldu: silme
   oturumunun yükleme iletisi `KIT YUKLENDI, ama DUR kilidi var …`
   ile başlar ve pencerenin kapatılmasını tetiklememelidir; kitin
   bütün DUR iletileri `DUR` ile başlar.
2. §34.4 kit satırının negatif kontrollerine silme oturumu, `a5` PASS
   sonrası `a8` `reason=stopped` ve oturum sınırının yokluğu (H-1, M-3,
   M-1'in delta3 karşılığı).
3. N105'te sınır dalının yerine oturum dizini oluşturulamazsa
   `KIT_SESSION_CREATE_FAIL` ile DUR (M-1 sonrası döngü artık sınırsız
   olduğundan, dizin oluşturma hatasında komut tanımlanmaması için).
4. `ac.ps1`'in DUR kilidindeki yükleme iletisi ("SILME OTURUMU …";
   eski ileti yalnız `a8`/`a9` diyordu) ve §4.3 (a)'daki "DUR
   kilidinden sonra … hiçbiri çalışmaz" cümlesine "tek istisna" eki.
5. §26.1 ve §26.2: kilit kaldırma dosyaları (`DUR-lifted-<n>.txt`,
   `dur-lift-<n>.txt`) ve `KIT_TEARDOWN_SESSION` satırı metadata
   listesine eklendi (H-1'in evidence sözleşmesindeki karşılığı). Bu iki
   dosyanın adları yazıcının seçimidir; kullanıcı kararı yalnız "silmeden
   yeniden adlandır ve kayda yaz" der.

**Kabul edilen kalıntılar (bu turda değiştirilmedi).** (a) Silme
oturumunda `a3`'ün PASS iletisi hâlâ "siradaki adim a4" der; N107
daralık için değiştirilmedi, `a4` ise "SILME OTURUMU: a4-a7 bu pencerede
calismaz" diyerek reddeder. (b) N16'da 7z çıktıktan sonra okuma görevi
hata verirse `Wait()` istisnası dış `catch`'e düşer ve satır `STOP
SEVENZIP_LIST_START=FAIL` olur (`…TIMEOUT` değil); sonuç yine `STOP`'tur,
yalnız etiket kesin değildir.

**Bu turda hash'i değişen bloklar (revizyon 3 → R3 düzeltme turu).**

| Blok | Eski SHA-256 | Yeni SHA-256 | `ParseInput` |
|---|---|---|---|
| N16 (`n016.ps1`) | `38cfb35ea97727e7234656ba099b2fbf34dc1fd78f1e76c62e9b8af55a8767ae` | `326c9216f8eeedd922b1d7fca8b8584e87ccb29b2c21e2151a23b4199449b609` | 0 hata |
| N105 (`ac.ps1`) | `9275aa7d4b4d685107da00020aa94a70168f54f6d6dce47d2c83ad3700c4d599` | `635e0767513a562eff2734ea67f8fe8a2ee4737a941f8e3cdb4d27208c57bd0d` | 0 hata |
| N112 (`a8.ps1`) | `0ab9214e5c36999cea9ac633d6ba0827ea2bca849b19b4991e8fa42fcf473431` | `73ed1b599c22e52dbb4c065f76cb11723f6da1e17d6d0a370a45b1307b57f940` | 0 hata |
| N114 (tek sayfa) | `fb48f3cb22daba605b5e6831841343e28efe765b0749db021ee7ff0f589f81c6` | `08af40a6702b7cbd6259abcbce0675ffd3fabd8cbf21e355b8b1ebc6fc6c36d3` | — |

N4, N17 ve N106–N111, N113 bu turda değişmedi (hash'leri yukarıdaki
tabloyla aynı); kalan 102 blok `977a5e7` ile bayt-bayt aynıdır. Yeni kit
kodu büyük-küçük harfe duyarsız dizge operatörü taşımaz (yalnız `-c…`
biçimleri; kalan `-eq/-ne/-gt` sayı, bool veya `$null` karşılaştırması).

**R3 son dar düzeltme (bağımsız yeniden inceleme `16af7b62…bbf`;
kullanıcı kararı `at=2026-10-13T17:10+03:00`).** Girdi runbook
`3b1cf29d…ff40` ve inceleme dosyası diskten doğrulandı. Yalnız bu dosya
değişti; hiçbir şey çalıştırılmadı, değişen blok yalnız `ParseInput` ile
denetlendi ve hash'lendi.

| Bulgu | Karar | Değişiklik | Bölüm / blok |
|---|---|---|---|
| Obs-1 — K-R3-3'ün kapsamı | Yorum onaylandı | K-R3-3 karar satırı "yalnız operatörün yazdığı adlar" kapsamını ve kapsam dışı adları açıkça söyler | §34.9 kullanıcı kararları tablosu |
| Low-1 — `a6`'nın DUR iletisi `DUR` ile başlamıyor, kilit yazmıyor | İnceleme önerisi (a) | `a6`'da geçersiz geri okuma kaydı dalı artık `Write-KitDur 'a6' 'READBACK_RECORD_INVALID'`: kilit yazılır, ileti `DUR.` ile başlar. Bununla liste dışı değişiklik 1'deki "kitin bütün DUR iletileri `DUR` ile başlar" iddiası doğru hâle gelir | N110 |
| Obs-7 — son boşaltmadan sonra yazılan tuşlar ekrana düşebilir | Obs-7=ii (kullanıcı kararı `at=2026-10-13T17:20+03:00`; liste dışı değil) | Tek sayfa madde 7'ye kural: "Ekranda 7z'nin "Enter password" istemi yoksa HİÇBİR ŞEY yazmayın ve Enter'a basmayın." (tek sayfanın tırnak biçimine uyuldu); §32/39'a (h) cümlesi, bu kurala atıfla | N114; §32/39 |
| Diğer gözlemler | Değişiklik yok | — | — |

**DUR iletisi taraması (mekanik; N105–N113 dizge sabitleri).** `DUR`
içerip `DUR` ile başlamayan iki sabit vardı: N110'daki eski ileti (bu
düzeltmeyle kalktı) ve N105'in silme oturumu yükleme iletisi `KIT
YUKLENDI, ama DUR kilidi var: SILME OTURUMU …` (kasıtlıdır; tek sayfanın
"satır `DUR` ile başlıyorsa" kuralı onu tetiklememelidir). `DUR` ile
başlayıp kilit yazmayan iletiler yalnız şunlardır: `Test-KitLock`'un
`DUR - devam yok …` iletisi (kilit zaten vardır) ve kilit yazılamadığında
`STOP KIT_DUR_WRITE=FAIL` satırının ardından gelen `DUR.` iletisi. N3, N4,
N6, N14–N17 ve N51 kopyalarında `DUR` dizgesi yoktur.

**Bu düzeltmede hash'i değişen bloklar.**

| Blok | Eski SHA-256 | Yeni SHA-256 | `ParseInput` |
|---|---|---|---|
| N110 (`a6.ps1`) | `281969b6ab654310682bdc954c1b456adf78b7aedd11f939795ea25544e0d659` | `cd45441ad65352cba263415d8fd99432f1b3502fed7a645226b3218d9f53a0ef` | 0 hata |
| N114 (tek sayfa) | `08af40a6702b7cbd6259abcbce0675ffd3fabd8cbf21e355b8b1ebc6fc6c36d3` | `77a2186ff9bc6f0ff1304599095d95887ebe2f5d305d02e9533b95d130a916da` | — (PowerShell değil) |

Diğer 113 blok bu düzeltmede değişmedi. Ek R3/1 N114'ü listelemez (tek sayfa bir kit dosyası değildir); `a6.ps1` için Ek R3/1 bu tabloya atıf yapar.

### 34.10 Revizyon 4

YENİ (kullanıcı kararı `SCOPE_APPROVED at=2026-10-13T21:30+03:00`; dar
düzeltme). Girdi: `fae0347` runbook'u (SHA-256
`267e197e1e36a62acaab1a42efaf4d9692d5e36deb7042bb96d6f42a2aa00783`,
diskten doğrulandı). Yalnız bu dosya değişti; hiçbir runbook komutu, kit
betiği, 7z, PostgreSQL, CLI veya test çalıştırılmadı; yalnız blok
ayrıştırma (`ParseInput`), AST tabanlı statik tarama ve hash yapıldı.

**Neden.** Delta3 Faz A (kök `C:\vd3_86c4a7da`, revizyon 3 / `fae0347`)
A.10'da `STOPPED_ON_UNEXPECTED_RESULT` ile durdu: G-20 `KIT_EXCEPTION`
`ok=False`. Kanıt (salt-okunur): `C:\vd3_86c4a7da\run\stages\A\A.10.txt`
ve kapanış notu `C:\vd3_86c4a7da\run\close-delta3-run-a.txt`
(`DIAG_ERR1`, `DIAG_ERR2`, `ROOT_CAUSE`; tanı koşusu `<R>\en\diag1`).

**Tanı.** N105 (`ac.ps1`) Ek R3/3 gereği genel kapsamda dot-source
edilir; bu kapsamda `$kitPins` ile `$global:KitPins` ve `$kitVal` ile
`$global:KitVal` **aynı değişkendir** (PowerShell değişken adları
büyük-küçük harfe duyarsızdır). Bloğun son satırındaki `Remove-Variable
… kitPins, … kitVal, …` bu nedenle başarılı yüklemeden hemen sonra
`$global:KitPins`'i ve `$global:KitVal`'ı siler (bu silme mekanizması
kod okumasıyla ve PowerShell'in statik kapsam semantiğiyle çıkarılmıştır;
çalışma anında ölçülmedi); `a2` →
`Get-KitHeader`/`Get-KitScript` "Cannot index into a null array" →
`KIT_EXCEPTION`, `a2.txt` yazılmaz. `KitPins`'in null olduğu tanı
koşusunda ölçüldü; `KitVal` çakışması bu revizyonda **statik olarak**
doğrulandı (çalışma anında ölçülmedi). İnsan penceresi kiti aynı yolla
yüklediğinden `a2`'nin orada da düşmesi beklenir (ölçülmedi). G-20 dışındaki
A.10 satırlarının (G-21, G-23–G-26, `PRESIGNAL_*`) aynı nedene bağlı olup
olmadığı bu revizyonda ölçülmedi.

**Karar ve değişiklik.** Çakışan iki yerel değişken yeniden adlandırıldı:
`$kitPins` → `$kitPinsTbl`, `$kitVal` → `$kitValTbl` (oluşturma,
`ContainsKey`, dizinleyiciler, `.Count`, `ac.txt` kaydındaki
`$kitPinsTbl['ac.ps1']`, iki `$global:` devri ve `Remove-Variable`
listesi; 15 satır). Temizlik listesinden yalnız iki adı çıkarmak da
başarılı yolu düzeltirdi, ama yükleme denetimi DUR'unda
(`KIT_LOAD_<kod>`) `$global:KitPins`/`$global:KitVal` yarım kurulmuş
tablolarla kalır ve bloğun başındaki `= $null` ilklendirmeleri ile
`$global:KitPins = $kitPins` devri anlamsız öz-atamalar olurdu. Yeniden
adlandırma yazarın amaçladığı ayrımı geri getirir: yükleme geçerse genel
değişkenler doldurulur ve korunur; yükleme denetimi DUR'unda `$null`
kalır. `KIT_SESSION_CREATE_FAIL` dalı iki `$global:` devrinden sonra
geldiği için o dalda genel tablolar dolu kalır. Revizyon 3'te iki dalda
da genel değişkenler silinirdi; iki dalda da hiçbir komut
tanımlanmadığından bu farkın etkisi yoktur. Başka hiçbir davranış
değişmedi.

**Statik tarama (mekanik; N105–N113).** Yöntem: her blok
`Parser.ParseInput` ile ayrıştırıldı; genel ad kümesi N105–N113'teki bütün
`$global:<ad>` başvurularından türetildi: `KitSess`, `KitDir`, `KitEvid`,
`KitVal`, `KitPins`, `KitSessDir`, `KitE2Dir`, `KitTeardown`, `KitRx`.
Her blokta (a) `Remove-`/`Clear-`/`Set-`/`New-Variable` ile adı geçen her
ad ve (b) atanan veya döngü değişkeni olan her nitelendirilmemiş yerel ad
bu kümeyle büyük-küçük harf duyarsız karşılaştırıldı (`$null =`
sözde-atamaları ve `$env:` atamaları değişken değildir, dışarıda tutuldu).

| Blok | Yürütme kapsamı | (a) Değişken cmdlet'i ile adı geçen | (b) Atanan yerel adlar | Çakışma (rev. 3 → rev. 4) |
|---|---|---|---|---|
| N105 üst düzey (`ac.ps1`) | **Genel kapsamda dot-source** (Ek R3/3) | `Remove-Variable`: 18 ad (`kitWhy`, `kitNames`, `kitValNames`, `kitPinBytes`, `kitPins`→`kitPinsTbl`, `kitL`, `kitM`, `kitN`, `kitItems`, `kitI`, `kitVal`→`kitValTbl`, `kitUp`, `kitV`, `kitDurP`, `kitSteps`, `kitK`, `kitS`, `kitDurOn`) | Aynı 18 ad | **2 → 0** (`kitPins`↔`KitPins`, `kitVal`↔`KitVal`; hem atama hem silme) |
| N105 fonksiyon gövdeleri | Fonksiyon kapsamı | — | `b`, `c`, `fs`, `h`, `i`, `k`, `kitEr`, `kitLn`, `kitNs`, `l`, `noStop`, `ok`, `p`, `q`, `r`, `rec`, `retry`, `s`, `sb`, `succ`, `t`, `w`, `x` | 0 → 0 |
| N106 (`a2.ps1`) | `Invoke-KitStep` içinde `& $sb` (çocuk kapsam) | — | `kitRec`, `kitR` | 0 → 0 |
| N107 (`a3.ps1`) | Aynı | — | `kitA2`, `kitFmt`, `kitInv`, `kitD1`, `kitWait`, `kitRec`, `kitT2`, `kitSec` | 0 → 0 |
| N108 (`a4.ps1`) | Aynı; N51 ve N14 satır 1 bu çocuk kapsama dot-source edilir | — | `kitRec`, `kitTmp`, `kitDef51`, `kitDef14` | 0 → 0 |
| N109 (`a5.ps1`) | Aynı | — | `kitRec` | 0 → 0 |
| N110 (`a6.ps1`) | Aynı | — | `kitRb`, `kitAns` | 0 → 0 |
| N111 (`a7.ps1`) | Aynı | — | `kitA6` | 0 → 0 |
| N112 (`a8.ps1`) | Aynı | — | `kitRb`, `kitRec`, `kitWhy`, `kitLast`, `kitL` | 0 → 0 |
| N113 (`a9.ps1`) | Aynı | — | `kitRec` | 0 → 0 |
| Bilgi: kit kopyaları N3, N4, N6, N14, N15, N16, N17, N51 (kapsam dışı; değişmedi) | `Invoke-KitBlock` içinde `& $sb`; N51 ve N14 satır 1 `a4` çocuk kapsamına dot-source | N3 5, N4 4, N6 2, N14 5, N15 2, N16 17, N17 6 ad (`cd…`, `channel…`, `hh`/`defaultHistoryHandler`, `popSha`/`szSha`/`cdRec…`, `tr`/`toolOk`, `sz…`, `x…`, `n`) | Aynı adlar ve N6 `extraModules`, `m`, `rl`; N14/N51 fonksiyon yerelleri | 0 → 0 |

Sonuç: çakışan adlar yalnız N105'teki bu ikisidir; revizyon 4'ten sonra
N105–N113'te ve kit kopyalarında büyük-küçük harf duyarsız çakışma
**0**'dır. Değişen blok `ParseInput` 0 hata verdi; yalnız ASCII, CR yok
(LF).

**Revizyon 4 inceleme düzeltme turu (bağımsız inceleme `9ab9e8ba…9c7`;
kullanıcı kararı `USER_DECISION at=2026-10-13T23:10+03:00`).** Girdi:
ara sürüm `b9de07df…b720` ve inceleme dosyası (`READY_FOR_COMMIT=YES`,
0C/0H/0M/2L/3O), ikisi de diskten doğrulandı. Yalnız bu dosya değişti;
hiçbir şey çalıştırılmadı (yalnız `ParseInput`, AST taraması ve hash).

| Bulgu | Karar | Değişiklik | Bölüm / blok |
|---|---|---|---|
| L-1 — `Get-KitScript` pin denetimi `$global:KitPins` null iken açık başarısız (fail-open) | Fail-closed denetim | `Get-KitScript` artık ilk iş olarak `$global:KitPins`'in yokluğunu veya boşluğunu (`Count` 0) denetler; öyleyse `$null` döner ve betik yüklenmez. Çağıranların mevcut DUR yolları uygulanır: `Invoke-KitStep` → `KIT_SCRIPT_LOAD_FAIL` kilidi; `Invoke-KitBlock` → `STOP KIT_SCRIPT_LOAD=FAIL file=<ad>`; `a4` → `STOP KIT_SCRIPT_LOAD=FAIL file=n051,n014`. Revizyon 3'te null tabloda pin karşılaştırması ölümcül olmayan bir hatayla atlanmış ve betik pin denetimi olmadan çalışmıştı (delta3 kanıtında DUR nedeni `KIT_EXCEPTION`, `KIT_SCRIPT_LOAD_FAIL` değil; inceleme L-1). Başka davranış değişmedi; yeni yerel ad yok | N105 (1 yeni satır) |
| L-2 — üst uyarı, §0 ve §1.6 delta3 Faz A'yı ve revizyon 4'ü yansıtmıyor | Güncellenir | Üst uyarı, §0 (delta3 Faz A ve revizyon 4 incelemesi pin satırları; "Revizyon" satırı), §1.4 "Bu belge ne DEĞİLDİR" maddesi (inceleme L-2'nin andığı L117–L125; başlığı "Revizyon 4'ün provası yapılmış değildir") ve §1.6/3 delta prova paragrafı: A.10'da durdu, kök neden N105, revizyon 4 ile düzeltildi, kit henüz uçtan uca çalıştırılmadı. "delta3 provasından geçmeden gerçek veriyle kullanılamaz" bağlayıcı cümlesi aynen korundu | Üst uyarı; §0; §1.4; §1.6/3 |
| O-1 — "DUR dalında `$null` kalır" `KIT_SESSION_CREATE_FAIL` dalını kapsamıyor | Düzeltilir | Yukarıdaki "Karar ve değişiklik" paragrafı iki dalı ayrı anlatır | §34.10 |
| O-2 — silme mekanizması ölçülmüş gibi | Düzeltilir | "Tanı" paragrafına: mekanizma kod okumasıyla çıkarıldı, çalışma anında ölçülmedi | §34.10 |
| O-3 — N105 ilk satırı "revizyon 3" | Düzeltilir | Yorum "runbook revizyon 4" oldu | N105 (1 satır) |

Düzeltme turundan sonra statik tarama yeniden yapıldı: genel ad kümesi
ve yukarıdaki tablo değişmedi (çakışma 0; yeni satır yalnız
`$global:KitPins` okur). N105'te revizyon 3'e göre toplam değişiklik:
15 yeniden adlandırma satırı, 1 yorum satırı, 1 yeni satır (187 → 188
satır).

**Bu revizyonda hash'i değişen bloklar.**

| Blok | Eski SHA-256 | Yeni SHA-256 | `ParseInput` |
|---|---|---|---|
| N105 (`ac.ps1`) | `635e0767513a562eff2734ea67f8fe8a2ee4737a941f8e3cdb4d27208c57bd0d` | `fdb0e55502e70ed3f54969291b2f4d2ebaa2a46456bed3169311f4357c7f6ca5` | 0 hata |

İncelenen ara sürümde (`b9de07df…b720`) N105 hash'i
`5788dda15245f17d649641a9a2eb79a5396340aa449f1ffa62a635712c62340e` idi;
düzeltme turu onu yukarıdaki son değere değiştirdi.

Blok sayısı 115'tir; diğer 114 blok `fae0347` ile bayt-bayt aynıdır (blok
hash'leriyle ölçüldü). §34.9 ana tablosundaki N105 satırı ve Ek R3/1'deki
`ac.ps1` satırı yeni değere güncellendi; §34.9 R3 düzeltme turu
tablosundaki N105 satırı tarihsel kayıttır, değişmedi. Revizyon 4 delta3
yeniden koşusunu yetkilendirmez; o ayrı bir kullanıcı kararıdır (yeni
kök).

**Ders.** Revizyon 3 incelemeleri kit kodunu büyük-küçük harfe duyarsız
**dizge operatörleri** için taradı (§34.9, R3 düzeltme turu son
paragrafı); bu hata ise büyük-küçük harfe duyarsız **değişken adlarının**
genel kapsamda dot-source ile birleşmesidir. Statik incelemeler bu sınıfı
yakalayamadı; delta3 PS-1 kapısı yakaladı.

### 34.11 Revizyon 5

YENİ (kullanıcı kararı `SCOPE_APPROVED at=2026-10-18T11:45+03:00`;
planlayıcı önerisiyle, kullanıcı onayı; oturum RUNBOOK-REV5). Girdi:
`5153593` runbook'u (SHA-256
`a00d89e5d69100cf4af1e0d20723a6d358e74c2b68e89b50b767b76a9e29caa6`, 6648
satır; HEAD = `origin/claude-dev` = `5153593`, çalışma ağacı temiz; diskten
doğrulandı); delta3 yeniden koşusunun (d9d67b7d) `run\findings.md`,
`run\summary.md` ve bağımsız kanıt incelemesi (§0; inceleme SHA-256
`9d2aa6082b70dae81d05522ede83b80547e25bc83f56a8ba391e162e63f9eb84`
diskten doğrulandı; verdict `REHEARSAL_EVIDENCE_VERIFIED`; Critical 0,
High 2, Medium 3, Low 7, Observation 8; özellikle H1, H2, M1–M3, liste 5A
ve 5B ve "revizyon 5 önerileri"); plan `plan_v6.md` (`941d0f2e…c2b`).
Yalnız bu dosya değişti; kod, şema, veri, test, başka runbook veya
`CLAUDE.md` değişmedi; LOCKED bir sözleşmeye dokunulmadı. Yazılırken
hiçbir runbook komutu, kit betiği, 7z, PostgreSQL, CLI veya test
çalıştırılmadı; yalnız blok ayrıştırma (`ParseInput`), AST tabanlı statik
tarama (N116 dahil; yalnız bu runbook'tan çıkarılmış blok kopyaları
üzerinde, oturumun geçici dizininde) ve hash yapıldı.

**Karar günlüğü.**

| Kayıt | İçerik |
|---|---|
| `SCOPE_APPROVED at=2026-10-18T11:45+03:00` | Planlayıcı önerisiyle, kullanıcı onayı. Yazma kapsamı yalnız bu dosya (`claude-dev`); hiçbir şey çalıştırılmaz (yalnız `ParseInput`/AST/hash ve statik tarama); commit/push yok; kararlar D1–D6; daha iyi bir dar çözüm görülürse uygulamadan önce açık soru |
| D1 — TEMP | Kit modunda geçici klasör yönlendirmesi kitin içine alınır ve otomatik yapılır; `kit-values.txt`'deki `container-temp` kullanılır, doğrulanır, kayda yazılır; elle adım (t4/N12 — bkz. yorum 1) kit modunda gereksiz kalır. Yönlendirme yapılamaz/doğrulanamazsa kilit koymadan, kayıt yazmadan red ve ne yapılacağını söyleyen ileti (`a3`'ün "BEKLEYIN … (Kayit yazilmadi.)" emsali). `a3`'ün "sıradaki adım" iletisi buna göre düzeltilir. **Uygulama:** `a4` (N108) başı — yer gerekçesi yorum 2 |
| D2 — DUR anı | Kitin bütün DUR iletileri, N114 ve tek sayfa aynı kuralı söyler: "`a9` yazın; sonra pencereyi kapatın; kiti yeniden açmayın; hiçbir yapay zekâ aracı/sohbet açmayın; ne olduğunu not formuna yazın; ajana ancak pencere kapandıktan sonra dönün." Silme oturumu yükleme iletisine "silme günü değilse pencereyi kapatın" eklenir. **Uygulama:** N105 `Write-KitDurRule`; N114 DUR kuralı; §4.3 (a); Ek R3/3; Ek R3/4 kural 1 |
| D3 — Ortam hazırlığı | Yeni "pilot öncesi bilgisayar hazırlığı (bir kerelik)": Görev Yöneticisi → Başlangıç'ta OneDrive/Copilot/ChatGPT devre dışı; Görev Zamanlayıcı'da OneDrive'ın üç görevi devre dışı; yeniden başlatma; Ayrıntılar'da kontrol. N114 madde 0: VS Code pencereden önce tamamen kapatılır (gömülü `copilot-runtime`, VS Code ≥ 1.142); Görev Yöneticisi'nde yalnız listelenen süreçler sonlandırılır. **Uygulama:** §4.3 (a) yeni alt başlık (yeni üst düzey bölüm açılmadı) ve kapatma prosedürü madde 1–2; "bu runbook bunu önermez" cümlesi bu karara bağlanarak yeniden yazıldı; §1.6/5; N114 madde 0; §32/40 |
| D4 — Not formu | Kısa kodlu (E/H kutuları), en fazla ~10 satırlık şablon; mekanik ölçülebilen sorular formdan çıkar. **Uygulama:** Ek R3/6 (N115): iki başlık satırı + dokuz kod satırı (K1–K9) |
| D5 — Değişken çakışması ve birikmiş küçük düzeltmeler | Ek R3/2 kit kurulumuna pinli, mekanik AST kontrolü (aynı kapsamda büyük-küçük harf duyarsız çakışan değişken adı ve `$global:` adlarıyla çakışma; `KIT_VAR_COLLISIONS=0`, değilse DUR). Birikmiş: §32/1'deki eski "henüz çalıştırılmamıştır" ifadesi; `Get-KitScript`'e `$global:KitPins -is [hashtable]` denetimi; final-check Obs-1 (tek sayfadaki "istem yoksa HİÇBİR ŞEY yazmayın" kuralı "kitin E/H soruları hariç" diye netleşir). **Uygulama:** Ek R3/7 (N116), Ek R3/2 madde 7–8; §32/1; N105; N114 madde 7; §32/39 (h) |
| D6 — Kapsam dışı | Runbook'a girmez; aşağıda "sonraki prova planına notlar" olarak listelenir |
| `USER_DECISION at=2026-10-18T12:30+03:00` (ek karar) | Planlayıcı önerisiyle, kullanıcı onayı. İlk yazımdaki açık nokta ("teknik kayıt yoksa `a4` kilitleniyor"): **kilitsiz red**. İlke aşağıda "ön koşul ilkesi" başlığı altında aynen; uygulama `a4` (N108) ve sınıflandırma tablosu. Aynı tur ilk raporun kesik kalan "Yorumladığım yerler" 2–5'ini yeniden yazdırır (rapor; bu dosyaya girmez) |
| `USER_DECISION at=2026-10-18T12:50+03:00` (madde 7 kararı) | Planlayıcı önerisiyle, kullanıcı onayı. Optik sürücü ön koşulu = A: kilitsiz red; madde 8 ve 9–11 kilitli; yazarın 3, 4, 5 numaralı rapor yorumları onaylandı; §4.2/10 değişmez, kit modu farkı bu bölümde. Ayrıntı aşağıda "Madde 7 kararı" |
| `USER_DECISION at=2026-10-18T13:30+03:00` (dar düzeltme turu) | Planlayıcı önerisiyle, kullanıcı onayı. Bağımsız inceleme `C:\Users\Burki\vergi_step10_rev5_review_31d27c7f\independent-runbook-rev5-review.md` (SHA-256 `6399dd0d8d45a75f4f58ec03c2b3e2d38082e5e5a21b37f20bdd0a6e9dc8595a`; `READY_FOR_NARROW_REMEDIATION`; Critical 0, High 0, Medium 1, Low 9, Observation 7; diskten doğrulandı, runbook o anda `54ce8520…1d58`). M1: prova listesi (§34.4) ve çalışma anında denenmeyen varsayımlar 12:30 ve 12:50 kararlarıyla güncellenir; L9: teknik kaydın her içerik penceresinde yeniden yazılması gerekiyorsa oturum denetimi + kilitsiz red, gerekmiyorsa denetim yok, L6 cümlesi düzeltilir ve sınır §32/39'a yazılır; L8: bir kerelik hazırlığa Claude masaüstü başlangıç öğesi; L1–L7 incelemenin önerdiği dar düzeltmelerle; Observation'lar değişmez, burada listelenir. Ayrıntı aşağıda "Düzeltme turu" |
| `USER_DECISION at=2026-10-18T14:45+03:00` (tek sayfa netleştirmesi) | Planlayıcı önerisiyle, kullanıcı onayı. Düzeltme turunda açık bırakılan gözlem (tek sayfa madde 3'teki "(kapsayıcı, teknik kayıt, yol kapısı)" ifadesi, ikinci veya sonraki bir içerik penceresinde harfiyen okunursa teknik kayıt bloğunun yeniden çalıştırılmasına yol açabilir; kayıt varken blok `STOP TECHNICAL_RECORD=FAIL` verir) düzeltilir: N114 madde 3, teknik kayıt bloğunun YALNIZ `technical-record.txt` yoksa (ilk içerik penceresi) çalıştırılacağını ve kayıt varsa atlanacağını en kısa biçimde söyler; N114'ün başka hiçbir satırı değişmez. §32/39 (l) bu düzeltmeye atıf yapar; §34.9 hash tablosu ve §34.11 (bu satır, blok tablosu, Bölüm → değişiklik tablosu) güncellenir. Bu kararla yapılır, liste dışı değildir. Runbook o anda `c9dd2341…f9f8` (diskten doğrulandı) |

**Yorumlar (sessizce seçilmedi; inceleyicinin değerlendirmesi için).**

1. **"t4/N12".** §34.8 numaralandırmasına göre TEMP yönlendirme bloğu
   **N13**'tür; N12 bir kerelik sistem Temp kaydıdır (`system-temp.txt`)
   ve `a4`'ün karşılaştırma dayanağıdır, gereksiz olamaz. Karardaki
   "t4/N12" N13 (ve provadaki karşılığı `t4.ps1`) olarak okundu. N12 ve
   N13 değişmedi (hash'leri `5153593` ile aynı).
2. **Yer: `a4` başı, `a3` değil.** (i) `a3` içinde yönlendirme
   `container-temp`'in, dolayısıyla kapsayıcının, kanal kapısı geçmeden
   bağlı olmasını gerektirirdi; mevcut sıra kapı → kapsayıcı →
   yönlendirmedir (tek sayfa madde 3) ve `a3` bu sırayı gevşetirdi. (ii)
   K-R3-11 kit kapsamını kanal kapısı ve E2 ile sınırlar; E2 dışı
   oturumlar revizyon 2 bloklarıyla (N13 dahil) yürür. (iii) Delta3'ün
   durduğu adım `a4`'tür. Sonuç: "kit modu" = E2 günü kit penceresi; orada
   N13 elle çalıştırılmaz; E2 dışı içerik oturumlarında (silme oturumu
   dahil; orada `a4` zaten çalışmaz) N13 elle çalışır (§4.4/5, §32/39 j).
3. **TEMP pencerede zaten değişmişse** (elle N13 veya yarım kalmış önceki
   `a4`): `a4` kabul etmez (`ALREADY`), çünkü sistem Temp eşleşmesi artık
   ölçülemez; pencere `a9` ile kapatılıp yeniden açılır. Kayıt-var
   denetimi TEMP denetiminden **önce** gelir: `a4` PASS'ten sonra ikinci
   bir `a4` "Bu adim zaten calisti" der ve pencereyi kapattırmaz
   (§32/39 g gereği E2 zinciri yeni oturumda devam etmez).
4. **"kayda yazılır".** Kayda yol değil, yalnız boolean satırlar yazılır
   (`SYSTEM_TEMP_MATCH=True`, `KIT_TEMP_REDIRECT=True`,
   `KIT_TEMP_IN_CONTAINER=True`); sistem Temp yolları ve `container-temp`
   değeri ne ekrana ne kayda basılır (§1.5).
5. **"N114 ve tek sayfa".** Bu runbook'ta N114 tek sayfanın kendisidir; D2
   kuralı N114'e, kitin DUR iletilerine ve gövde metnine (§4.3 a "Kit ile
   yürütme", Ek R3/4 kural 1) yazıldı.
6. **"Yalnız ASCII".** PowerShell blokları (N105, N107, N108, N116) için
   uygulandı ve ölçüldü. N114 ve N115 `text` bloklarıdır, basılı Türkçe
   sayfalardır; N114 tabanda da ASCII değildi; bunlarda ASCII şartı
   uygulanmadı.
7. **Kit iletisi** `Istem yoksa hicbir sey yazmayin.` (N105
   `Invoke-KitAttempt`) değiştirilmedi; D5 yalnız tek sayfa kuralını
   adlandırır.
8. **"Kiti yeniden açmayın"** ifadesine silme oturumu istisnası
   ("ajan, pencere kapandıktan sonra yazılı olarak söylemedikçe") eklendi;
   aksi hâlde N114'ün silme oturumu kuralıyla çelişirdi.

**Bulgu → değişiklik eşlemesi (kanıt incelemesi `9d2aa608…` ve
`findings.md`'nin "Runbook revizyon 5 için zorunlu bulgular" 1–6).**

| Bulgu | Değişiklik | Bölüm / blok |
|---|---|---|
| H1 — DUR anında insan protokolü çöktü; `a9` iki oturumda atlandı; DUR'dan sonra yapay zekâ aracı açıldı ve ekran yapıştırıldı | D2: ortak DUR kuralı (`Write-KitDurRule`) bütün DUR iletilerinde; `SIMDI a9 YAZIN` ayrı satır; silme oturumu yükleme iletisi; tek sayfa DUR kuralı; not formu K3–K6; §32/39 (k). Faz B'nin `a9` yokluğunu sapma sayması prova planı kuralıdır (aşağıdaki öneriler) | §4.3 (a); Ek R3/3; Ek R3/4 kural 1; N105, N114, N115 |
| H2 — TEMP yönlendirmesi kit dışında; `a3` iletisi kullanıcıyı `a4`'e yönlendiriyor | D1: `a4` kayıttan önce TEMP ön denetimi ve yönlendirmesi, kayıtsız ve kilitsiz red (`a4 BASLAMADI: …`); `a3` PASS iletisi; tek sayfa madde 3–4 | §4.4/5; Ek R3/4 tablo ve kural 2; §25.1 H52; §26.2; N107, N108, N114 |
| M1 — A.16-r2/r3/r4 kodu kullanım anında pinli değil | Prova disiplini; runbook değişikliği yok (D6 notu 1) | — |
| M2 — kapatma ön ölçümü üç ek tur gerektirdi | D3: bir kerelik bilgisayar hazırlığı; kapatma sırası (önce VS Code) ve yalnız listelenen süreçlerin sonlandırılması; A.16'nın yeniden tasarımı D6 notu 5 | §4.3 (a); §1.6/5; §32/40; N114 |
| M3 — not formu doldurulmadı; `STUCK_NOTE_COUNT=0` ölçüm değil | D4: kısa kodlu not formu; doldurulmamış form "takılma yok" değildir (N/A) | Ek R3/6; N115 |
| L1 — B.6'da `DELTA=` satırları yok | D6 notu 2 | — |
| L2 — `NON_PLAN_LINE_COUNT=43` sunumu | Prova raporlama kuralı; değişiklik yok | — |
| L3 — D3-ORDER E-main'in DUR sonrası açılışını görmüyor | D6 notu 4 | — |
| L4 — F-B2'nin yan kanıt ifadesi abartılı | Prova raporu; değişiklik yok | — |
| L5 — `fakeprofile\`; manifestin dizin kör noktası | D6 notu 3 | — |
| L6 — Faz B devam kararının sonradan onayı | İncelemede kapandı; değişiklik yok | — |
| L7 — `HELPER_VAR_COLLISIONS=0`'ın tanımı ve kodu kayıtsız | D5: kural Ek R3/7'de tanımlı, kod pinli (N116), kurulumda zorunlu; `kit-build.txt` satırları | Ek R3/2 madde 7–8; Ek R3/7; §26.2; N116 |
| O1 — `copilot-runtime` VS Code ile kapanır | Önce VS Code; VS Code ≥ 1.142 gömülü `copilot-runtime` hazırlık metninde adlandırıldı | §4.3 (a); N114 madde 0 |
| O2 — revizyon 4 `$global:KitPins` düzeltmesi insan penceresinde işledi | Değişiklik yok (5A madde 8) | — |
| O3 — `a4` TEMP STOP'undan sonra `n003`/`n015`'i yine çalıştırıyordu | TEMP reddi artık kayıttan önce; kayıttaki `STOP KIT_TEMP_IN_CONTAINER=False` yalnız yönlendirme sonrası yeniden ölçümde oluşabilir | N108 |
| O4–O8 | Prova kaydı gözlemleri; değişiklik yok | — |
| `findings` 1 (TEMP kit dışında) | = H2 | — |
| `findings` 2 (yazıcısız ortam, not formu) | = M3; yazıcısız düzen (X31) prova planına aittir (öneri) | — |
| `findings` 3 (VS Code ≥ 1.142 `copilot-runtime`) | = O1 | — |
| `findings` 4 (OneDrive zamanlanmış görevleri) | D3: hazırlık madde 2 | §4.3 (a) |
| `findings` 5 (değişken adı çakışmaları) | = L7 / D5 | — |
| `findings` 6 (A.16 tek yeniden ölçüm kuralı yetmedi) | = M2 (D3) ve D6 notu 5 | — |

**Liste 5A ve 5B (kanıt incelemesi §7, §8).** 5A'daki 11 mekanizmadan
bayt-bayt aynı kalan blok kopyalarına bağlı olanların ajan kanıtı
devralınır (5A madde 4, 5 ve 7: N16 listeleme kararları, bekçi, N4
kültür eşleşmesi). N105 bütün kit adımlarının ortak yükleyicisi olduğu ve
N107/N108 değiştiği için kit adımlarının ajan ölçümleri (5A madde 1–3, 6
ve 8–11) bir sonraki delta provasında yeniden yapılır (§34.4 revizyon 5
satırları). 5B'nin 13 adımı, gerçek veriden önce bir insanın elle göstermesi
gereken adımlardır; revizyon 5 bunlardan madde 1 (kapatma ve bir kerelik
hazırlık), 2 (TEMP adımı artık `a4` içinde), 10 (DUR anı) ve 12 (kâğıt not
formu) için metin veya kod değiştirdi. **Hiçbiri bu revizyonla
gösterilmiş değildir.**

**Sonraki prova planına notlar (D6; runbook'a girmez).**

1. Devam ve yeniden ölçüm betikleri (A.16-r2/r3/r4 türü) prova kökünde
   CreateNew ile yazılır ve pinlenir; kayıt yazan adımlarda satır içi kod
   yoktur (M1).
2. B.6 `DELTA=<ID> result=…` satırlarını yazar (L1, F-B8).
3. Kök manifesti dosyaların yanında dizinleri de listeler (L5).
4. D3-ORDER ölçütü E-main'in DUR sonrası yeniden açılışlarını (silme
   oturumu dahil) da sayar (L3).
5. A.16 kapatma ön kontrolü, açık bir tur sınırıyla ve pinli bir
   yardımcıyla "ölç → listele → kullanıcı düzeltir → yeniden ölç" döngüsü
   olarak yeniden tasarlanır (M2, `findings` 6).

Bu revizyonun ayrıca önerdiği, bağlayıcı olmayan plan kuralları:
Faz B'de DUR sonrası `a9` yokluğu sapma sayılır (`reason=skipped_after_dur`;
H1); not formu yoksa `STUCK_NOTE_COUNT=N/A` yazılır (M3); prova kitinin
`<evidence-dir>`'inde N12 karşılığı `system-temp.txt` bulunur, aksi hâlde
yeni `a4` kayıtsız olarak reddeder; yazıcısız düzen (X31) ve
Win+R kopyala-yapıştır/pano geçmişi kuralı prova planında kalır.

**Uygulama notları.**

- **Kapı yönü.** Kapıların kendisi gevşetilmedi: `a4` PASS olmadan
  `a5`–`a7` çalışmaz ve içerik yalnız `a4 TAMAM`'dan sonra kaydedilir.
  Kilidin kalıcılığı üç ön koşul sınıfında (TEMP ön denetimi, teknik
  kaydın varlığı/biçimi, pencere öncesi optik ön ölçüm) kullanıcı
  kararlarıyla (D1, 12:30, 12:50) kaldırıldı. Bunun bilinen iki yan
  etkisi vardır (bağımsız inceleme L6, L9, O1): (i) reddedilen denemeler
  hiçbir iz bırakmaz (örneğin pencere öncesi takılı bir disk sonradan
  kanıttan anlaşılamaz); (ii) revizyon 4'te madde 3'ü atlayan operatörü
  TEMP adımının kalıcı kilidi dolaylı olarak durduruyordu; artık teknik
  kayıt önceden yazılmışsa ve kapsayıcı bağlıysa `a4`, altı sınıf
  beyanı, oturum başı kapsayıcı doğrulaması ve yol kapısı yapılmadan da
  PASS verebilir (bunlar önceden de mekanik olarak denetlenmiyordu;
  §32/39 l). `a4`'ün TEMP ön denetimi
  geçmezse `a4` hiç çalışmaz (önceden kayıt + `STOP` + kilit vardı; şimdi
  kayıt ve kilit yoktur, ama `a5`–`a7` `a4` PASS olmadan yine çalışmaz);
  yönlendirmeden sonra `KIT_TEMP_IN_CONTAINER` kayıt içinde yeniden ölçülür
  ve `STOP` → kilit korunur; `a4` PASS'i iki yeni zorunlu satır
  (`SYSTEM_TEMP_MATCH=True`, `KIT_TEMP_REDIRECT=True`) ister. Doğrulama
  başarısızsa eski TEMP/TMP geri konur. `Get-KitScript`'in yeni tür
  denetimi yalnız reddeder. DUR kuralı yalnız ileti metnidir; hiçbir kilit
  dalı değişmedi. Kurulum, N116 çakışma denetimiyle ek bir DUR koşulu
  kazandı.
- **Kilit yazmayan red dalının riski.** Operatör `a4`'ü tekrar
  deneyebilir; her deneme kayıt yazmaz ve TEMP'i yalnız bütün denetimler
  geçince değiştirir. Teknik kayıt yok, `NO_DIR` ve optik ön ölçüm
  redleri eksiğin aynı pencerede giderilip `a4`'ün yeniden yazılmasını
  söyler (optik redde aynı ileti yine çıkarsa `a9`, teknik kayıt
  bloğu `STOP` verdiyse yeniden deneme yoktur, yine `a9`); diğer redler
  (biçimi geçersiz teknik kayıt, `NO_RECORD`, `MISMATCH`, `ALREADY`,
  `VERIFY`) pencerenin `a9` ile kapatılmasını söyler. Ek karardan sonra ön koşul
  denetimlerinin sırası: `a3` PASS → `a4.txt` yok → teknik kayıt var →
  teknik kayıt biçimi → optik sürücü ön ölçümü (madde 7 kararı) → TEMP
  denetimleri → TEMP/TMP ataması ve doğrulama → kayıt; TEMP/TMP
  atamasından önceki her denetim yan etkisizdir.
- **Tek sayfa** 49 → 59 satır (tek sayfa netleştirmesinde 60); en uzun satır açılış komutudur (101
  karakter); tabandaki 103 karakterlik satır yeniden akıtıldı. Basılı bir
  sayfaya sığdığı ölçülmedi (yazdırma yapılmadı).
- **§34.9'un "kabul edilen kalıntı (a)"sı** (silme oturumunda `a3`
  iletisi "siradaki adim a4") tarihsel kayıttır: `a3` iletisi artık
  "Aktarim gununde: once kagittaki madde 3 bloklari, sonra a4 …" der;
  silme oturumunda `a4` yine "SILME OTURUMU: a4-a7 bu pencerede
  calismaz" ile reddeder.
- **Teknik kayıt yoksa `a4` kilitleniyordu (ilk yazımda açık nokta; ek
  karar `USER_DECISION at=2026-10-18T12:30+03:00` ile kapandı).** İlk
  yazımda `a4`, `technical-record.txt` yoksa kayıt yazıp `STOP
  TOOL_MANIFEST_MATCH=False` ile kilitleniyordu (H2'nin aynı sınıftan
  eşi). Artık kayıttan önce dosyanın varlığı ve biçimi denetlenir;
  aşağıdaki "ön koşul ilkesi" ve sınıflandırma listesi.

**Ön koşul ilkesi (ek karar `USER_DECISION at=2026-10-18T12:30+03:00`;
planlayıcı önerisiyle, kullanıcı onayı; aynen).** "a4'ün içeriğe
dokunmadan önce denetlenen ÖN KOŞULLARI (TEMP yönlendirmesi,
technical-record.txt varlığı/geçerliliği ve aynı sınıftan, içerik
işlenmeden önce kullanıcının düzeltebileceği diğer eksikler) sağlanmazsa:
DUR kilidi YOK, kayıt YOK; eksik olanı ve yapılacağı adlandıran ileti
(a3'ün "BEKLEYIN … (Kayit yazilmadi.)" kalıbı). İçeriğe dokunulduktan
SONRAKİ her beklenmeyen sonuç önceki gibi kalıcı DUR kilidi verir. a4'te
bu sınıfa giren başka ön koşul varsa listele ve aynı biçimde uygula; emin
olmadığın birini sınıflandırma, AÇIK SORU yaz ve DUR."

"Geçerlilik" şöyle uygulandı: dosya bir yaprak dosyadır, okunabilir, ilk
satırı `# kind=technical-record`'dur ve `a4`'ün kullandığı dört satırın
her biri tam bir kez ve beklenen biçimde vardır
(`POPPLER_BIN_MANIFEST_SHA256=<64-küçük-hex>`,
`SEVENZIP_ROOT_MANIFEST_SHA256=<64-küçük-hex>`, `CDROM_DRIVE_COUNT=<n>`,
`OPTICAL_DRIVE_LETTERS=<harfler>` — §4.4/6 bloğunun yazdığı biçim). Dosya
yoksa ileti teknik kaydın tek sayfa madde 3'te yazılmasını ve yeniden
`a4`'ü söyler (teknik kayıt bloğu `STOP` verdiyse yeniden denemeyi değil
`a9`'u; düzeltme turu, L7); biçim geçersizse kayıt §4.4/6 gereği yeniden yazılamadığı
için ileti pencerenin `a9` ile kapatılıp ajana dönülmesini söyler. Biçimi
geçerli bir kaydın **araçlarla uyuşmaması** (`TOOL_MANIFEST_MATCH=False`)
bir eksik değil, araç değişikliği/bütünlük sonucudur (§4.4/6: "araç
değişirse **DUR** ve runbook revizyonu") ve kilitli kalır.

**`a4` ön koşul sınıflandırması (revizyon 5 ek karar).**

| # | Denetim | Sınıf | Davranış |
|---|---|---|---|
| 1 | Aynı oturumda `a3` PASS | Kullanıcının düzeltebileceği eksik | Kayıtsız, kilitsiz red (değişmedi: `Once bu oturumda a3 TAMAM olmali.`) |
| 2 | `a4.txt` zaten var | Tek çalışım kuralı | Kayıtsız, kilitsiz red (`Bu adim zaten calisti`) |
| 3 | Silme oturumu / mevcut DUR kilidi | `Invoke-KitStep` kuralı | Değişmedi (red; kilit zaten vardır) |
| 4 | `technical-record.txt` yok | Kullanıcının düzeltebileceği eksik | **Kayıtsız, kilitsiz red** (bu ek karar; düzeltme turunda ileti, teknik kayıt bloğu `STOP` verdiyse yeniden denemeyi değil `a9`'u, pencerenin kapatılmasını ve ajana dönülmesini söyler — bağımsız inceleme L7; sınıf değişmedi) |
| 5 | `technical-record.txt` okunamıyor veya biçimi geçersiz | Kararda adlandırılmış ("geçerliliği") | **Kayıtsız, kilitsiz red** (bu ek karar; ileti: `a9`, pencere kapanır, ajana dönülür) |
| 6 | Sistem Temp kaydı yok / uyuşmuyor; `container-temp` dizini yok; TEMP pencerede zaten değişmiş; yönlendirme doğrulanamadı | TEMP yönlendirmesi (D1) | Kayıtsız, kilitsiz red (revizyon 5) |
| 7 | Optik sürücüde medya/görüntü (`MediaLoaded=True`) veya sürücü sayısı/harfleri kayıtla uyuşmuyor | Kullanıcının düzeltebileceği eksik (madde 7 kararı A) | **Kayıtsız, kilitsiz red** (kayıttan önceki ön ölçüm; ileti diskin çıkarılmasını / sanal sürücünün ayrılmasını, aynı ileti yine çıkarsa `a9`, pencerenin kapatılmasını ve ajana dönülmesini söyler) |
| 8 | `STOP CDROM_QUERY=FAIL`, `STOP OPTICAL_MEDIA_LOADED=UNKNOWN` | Ölçüm başarısızlığı; §4.2/10 "yeniden çalıştırma yoktur" | Kilitli (değişmedi): ön ölçümde sorgu başarısızsa veya bir sürücünün durumu okunamıyorsa ön ölçüm **reddetmez**; `a4` kaydı oluşturur ve kayıt içindeki N3 aynı durumu `STOP` olarak yazıp kilitler (uyuşmazlıkla birlikte okunamayan durum da bu yola düşer) |
| 9 | N51 / N14 satır 1 yüklenemedi (pin, ASCII, ilk satır) | Kit bütünlüğü | Kilitli (değişmedi) |
| 10 | Biçimi geçerli teknik kayıtla araç manifesti uyuşmuyor (`STOP TOOL_MANIFEST_MATCH=False`) | Araç bütünlüğü (§4.4/6, Y5) | Kilitli (değişmedi) |
| 11 | Yönlendirmeden sonra `STOP KIT_TEMP_IN_CONTAINER=False`; blok kopyalarında `KIT_NONSTATUS_LINE_COUNT` ≠ 0 veya `KIT_ERROR_RECORD_COUNT` > 0 | Ön denetim geçtikten sonraki beklenmeyen sonuç | Kilitli (değişmedi) |

`a4` gerçek içeriğe dokunmaz (aktarım dosyası `a4 TAMAM`'dan **sonra**
kaydedilir); bu yüzden ilkenin "içeriğe dokunulduktan sonra" kolu `a5`
ve sonrasına uygulanır ve orada hiçbir şey değişmedi.

**Madde 7 kararı (`USER_DECISION at=2026-10-18T12:50+03:00`; planlayıcı
önerisiyle, kullanıcı onayı).** Madde 7 = A: kilitsiz red. `a4`, kaydını
oluşturmadan önce optik sürücüyü N3 ile aynı sorguyla
(`Get-CimInstance Win32_CDROMDrive`; sayı, sıralı sürücü harfleri ve her
sürücünün `MediaLoaded` değeri; teknik kaydın `CDROM_DRIVE_COUNT` ve
`OPTICAL_DRIVE_LETTERS` satırlarıyla birebir karşılaştırma) ölçer. Disk
veya görüntü varsa ya da sürücü kümesi kayıtla uyuşmuyorsa kayıt ve kilit
yoktur; ileti kararın metnini ASCII olarak taşır ("Optik surucudeki diski
cikarin veya sanal surucuyu ayirin, sonra yeniden a4 yazin. Ayni ileti
yine cikarsa a9 yazin, pencereyi kapatin ve ajana donun."). Madde 8 ve
9–11 kilitli kalır. Ön ölçüm geçtikten sonra kayıt içindeki N3 ve
`STOP KIT_OPTICAL_MEDIA_LOADED=True` denetimi aynen çalışır; ön ölçüm ile
N3 arasında takılan bir disk kilitler. Aynı kararla yazarın ilk
raporundaki 3, 4 ve 5 numaralı yorumları onaylandı; bunlar bu bölümün
"Yorumlar" listesindeki 3 (TEMP pencerede zaten değişmişse red), 6
(ASCII şartı yalnız PowerShell bloklarında) ve 8 ("kiti yeniden
açmayın"a silme oturumu istisnası) maddeleridir.

**Kit modu ile §4.2/10 arasındaki fark (bu karar gereği yalnız burada
yazılır; §4.2/10 değişmedi).** §4.2/10'un pencere öncesi kuralı (medya
veya uyuşmazlık görülürse çıkar ve optik bloğu **bir kez** yeniden
çalıştır; ikinci ölçüm de tutmazsa **DUR**, Y5) ajan ve elle yürütme
bağlamı için değişmeden geçerlidir. Kit modunda `a4`'ün ön ölçümü
reddettiğinde kayıt yazılmadığı için deneme sayılamaz; "bir kez" sınırı
mekanik değildir ve yerini iletinin "aynı ileti yine çıkarsa `a9`,
pencereyi kapatın, ajana dönün" talimatı alır. `CDROM_QUERY=FAIL` ve
`OPTICAL_MEDIA_LOADED=UNKNOWN` için §4.2/10'un "yeniden çalıştırma
yoktur" kuralı kit modunda da aynen geçerlidir (kayıt içinde N3 →
kilit). İçerik penceresi içindeki her uyuşmazlığın H40 olduğu kural
değişmedi; `a4` içerik penceresinden (zincir adım 5) önce çalışır.

**DUR iletisi taraması (mekanik; N105–N113 dizge sabitleri; revizyon 5).**
`Write-Host` ile basılan, `DUR` içerip `DUR` ile başlamayan sabitler:
silme oturumu yükleme iletisi (kasıtlı; §34.9) ve `a4`'ün yedi `a4
BASLAMADI: … (Kayit yazilmadi; DUR kilidi yok.)` iletisi (teknik kayıt
yok; teknik kayıt biçimi geçersiz; optik ön ölçüm; `NO_DIR`; `ALREADY`;
`VERIFY`; `NO_RECORD`/`MISMATCH` ortak iletisi — ilk yazımda üç, 12:30
ve 12:50 kararlarıyla altı, düzeltme turunda `VERIFY`'ın ayrı iletisiyle
yedi; bağımsız inceleme M1, L4) (kasıtlı: kilit
yazmazlar ve tek sayfanın "satır `DUR` ile başlıyorsa" tetikleyicisini
tetiklememelidir). `DUR` ile başlayan iletiler: `Write-KitDur`'un `DUR.
Adim …` ve yükleme hatasının `DUR. KIT YUKLENEMEDI …` iletileri (ikisi de
kilidi yazar; yazamazsa önce `STOP KIT_DUR_WRITE=FAIL` basılır) ve
`Test-KitLock`'un `DUR - devam yok.` iletisi (kilit zaten vardır); üçünün
ardından da `Write-KitDurRule` aynı kuralı basar. `Write-KitDurRule`,
`a9` fonksiyonu tanımlı değilse (yükleme hatası,
`KIT_SESSION_CREATE_FAIL`) veya bu oturumun `a9.txt`'si zaten varsa
(`a9`'un kendi `STOP`'u) `a9` satırını basmaz; birinci durumda `a8` yerine
saatin not formuna yazılmasını söyler.

**Statik denetimler (mekanik).**

- `ParseInput`: N105, N107, N108 ve N116 — her biri 0 hata.
- Büyük-küçük harf duyarsız operatör taraması (token düzeyinde, `I…`
  ikili operatörler): dört blokta yalnız sayı veya `$null`
  karşılaştırması (`-eq`, `-ne`, `-gt`, `-ge`, `-lt`); `-match`, `-like`,
  `-replace`, `-split`, `-contains`, `-in` ve `switch` yoktur. Dizge
  karşılaştırmaları `-c…` biçimleriyle veya açık
  `[System.StringComparison]::Ordinal`/`OrdinalIgnoreCase` ile yapılır.
- Değişken adı çakışması (N116; bu runbook'tan çıkarılmış 17 kit kopyası
  üzerinde): `KIT_VAR_SCAN_FILE_COUNT=17`, `KIT_VAR_GLOBAL_NAME_COUNT=9`,
  **`KIT_VAR_COLLISIONS=0`**; bilgi: `KIT_VAR_CROSS_SCOPE_CASE_PAIR_COUNT=4`
  (`Bytes|bytes`, `Lines|lines`, `Path|path`, `Rec|rec`; hepsi farklı
  fonksiyonlardaki parametre/yerel). Revizyon 4 kiti (`5153593`) de 0
  verir. Pozitif kontrol: revizyon 3 kiti (`fae0347`) → `STOP
  KIT_VAR_COLLISIONS=4` (`KitPins|kitPins` ve `KitVal|kitVal`, her biri
  `SAME_SCOPE_CASE` ve `GLOBAL_NAME` olarak) — §34.10'daki hata sınıfı
  yakalanır.
- Yalnız ASCII: N105, N107, N108, N116 (yorum 6). Dosyada CR yok (LF).
- Ek kararlardan sonra (12:30 ve 12:50; N108 iki kez yeniden yazıldı) 17 kit kopyasının ve N116'nın
  hepsi yeniden ayrıştırıldı (0 hata), operatör taraması tekrarlandı
  (yeni satırlarda yalnız sayı veya `$null` karşılaştırması ve büyük-küçük harfe duyarlı `-cmatch`) ve N116
  yeniden `KIT_VAR_COLLISIONS=0` verdi.
- Düzeltme turundan sonra (`USER_DECISION at=2026-10-18T13:30+03:00`;
  N108'de yalnız iki ileti: teknik kayıt yok iletisine L7 cümlesi,
  `VERIFY` için ayrı ileti satırı) 17 kit kopyası ve N116 yeniden
  çıkarılıp ayrıştırıldı (0 hata), operatör taraması tekrarlandı (N108'de
  yeni işleç yalnız `-ceq`) ve N116 geçici dizindeki kopyalar üzerinde
  yeniden `KIT_VAR_SCAN_FILE_COUNT=17`, `KIT_VAR_GLOBAL_NAME_COUNT=9`,
  `KIT_VAR_CROSS_SCOPE_CASE_PAIR_COUNT=4`, **`KIT_VAR_COLLISIONS=0`**
  verdi.
- Tek sayfa netleştirmesinden sonra (`USER_DECISION at=2026-10-18T14:45+03:00`;
  yalnız N114 değişti; N114 bir `text` bloğudur, kit `.ps1` dosyası
  değildir ve N116'nın tarama girdisine girmez) 17 kit kopyası ve N116
  yeniden çıkarılıp ayrıştırıldı (0 hata) ve N116 kopyalar üzerinde
  yeniden `KIT_VAR_SCAN_FILE_COUNT=17`, `KIT_VAR_GLOBAL_NAME_COUNT=9`,
  `KIT_VAR_CROSS_SCOPE_CASE_PAIR_COUNT=4`, **`KIT_VAR_COLLISIONS=0`**
  verdi; tarama girdisi değişmediği için bu yeni bir ölçüm değil,
  doğrulamadır.
- **Çalışma anında denenmeyen varsayımlar** (bu revizyonda kapsam
  gereği hiçbir kit bloğu çalıştırılmadığı için hiçbiri ölçülmedi; her
  biri bir sonraki delta provasında gösterilir, §34.4 revizyon 5
  satırları; düzeltme turunda genişletildi, kullanıcı kararı M1):
  1. `Write-KitDurRule`'un ileti seçimi `Test-Path -LiteralPath
     'Function:\a9'`'nin, `a9` genel fonksiyon olarak tanımlıyken
     `True`, tanımsızken `False` döndürmesine dayanır (PowerShell
     `Function:` sürücüsünün belgelenmiş davranışı); DUR iletilerinin üç
     biçimi (adım DUR'u, kilit uyarısı, yükleme hatası) ve `SIMDI a9
     YAZIN` satırının görünüp görünmemesi ekranda doğrulanır.
  2. `a4`'ün `$env:TEMP`/`$env:TMP` ataması `Invoke-KitStep`'in alt
     kapsamında yapılır ve süreç ortamını değiştirdiği için oturumun
     sonraki adımlarına (`a5`–`a7`) kalır; N16/N17'nin
     `UseShellExecute=$false` ile başlattığı 7z çocuk süreci bu ortamı
     devralır. Hiçbir provada çocuk sürecin Temp'i ölçülmedi (N13'ün elle
     yolunda da aynı mekanizma geçerlidir).
  3. `VERIFY` dalında eski TEMP/TMP değerlerinin geri konması ve bir
     sonraki `a4` denemesinin `ALREADY`'ye düşmemesi.
  4. Optik ön ölçümün kayıt içindeki N3 ile aynı sonucu vermesi (aynı
     sorgu ve karşılaştırma; iki ölçüm arasında yalnız birkaç okuma
     işlemi vardır).
  5. Her kilitsiz redden sonra eksik giderilip `a4` yeniden yazılınca
     akışın temiz devam etmesi (kayıt ve `DUR.txt` yok; statik olarak
     gösterildi, çalışma anında denenmedi).
  6. §4.3 (a)'daki bir kerelik hazırlığın yeniden başlatmadan sonra
     kalıcı olması (başlangıç öğeleri ve üç zamanlanmış görev).

**Düzeltme turu (`USER_DECISION at=2026-10-18T13:30+03:00`; bağımsız
inceleme `6399dd0d…595a`).** Bulgu → değişiklik:

| Bulgu | Karar / seçilen yol | Değişiklik |
|---|---|---|
| M1 — yeniden prova yükümlülüğü 12:30/12:50'den sonra güncellenmemiş | Kullanıcı kararı M1 | §34.4 revizyon 5 satırı: `a4`'ün bütün kilitsiz red dalları, optik red → disk çıkar → yeniden `a4`, teknik kayıt yok/bozuk reddi, `VERIFY`, kilitsiz red sonrası yeniden `a4`'ün doğru devamı, ön ölçüm sonrası kayıt içi N3 kilidi, madde 3'ün yardımsız yapılması, PASS'te 7z çocuk sürecinin TEMP'i, `SIMDI a9 YAZIN` satırının görünmesi; "Uygulama notları"nda kilitsiz red iletilerinin dökümü (optik istisnası); "DUR iletisi taraması"nda ileti sayısı (üç → yedi); "Statik denetimler"de varsayım listesi (1 → 6 madde) |
| L1 — N116 "hiç çalıştırılmamış" sayılıyor | İncelemenin dar düzeltmesi | Üst uyarı, §1.4, §1.6/3: N116 yazım sırasında yalnız çıkarılmış kopyalar üzerinde statik analiz aracı olarak çalıştırıldı, kurulum bağlamında çalıştırılmadı |
| L2 — "Bölüm → değişiklik" tablosunda §4.4/6 yok | İncelemenin dar düzeltmesi | Aşağıdaki tabloya §4.4/6 satırı |
| L3 — Y5 satırı uzlaştırılmamış | İncelemenin dar düzeltmesi | §25.1 Y5: kit modunda `a4` ön koşul reddinin kilitsiz olduğu ve kilitli kalan durumlar (H52 notuna atıf) |
| L4 — `VERIFY` iletisi yanlış etiketli | İncelemenin birinci seçeneği (ayrı ileti; N108 değişir) | N108: `VERIFY` için ayrı satır `a4 BASLAMADI: TEMP yonlendirmesi dogrulanamadi; eski TEMP/TMP geri kondu. …`; ortak ileti artık yalnız `NO_RECORD`/`MISMATCH` taşır. Seçim gerekçesi: insan operatöre ekranda yanlış neden söyleyen ileti, açıklamayla değil iletinin kendisiyle düzeltilir; N108 zaten yeniden prova edilecektir |
| L5 — N116 sınır metninde iki modellenmeyen sınıf yok | İncelemenin dar düzeltmesi (tarama listesi genişletilmedi; o ayrı karar) | Ek R3/7 sınır paragrafı ve §32/39 (i): madde 3 blokları taranmaz; kapsamsız `Remove-Variable`'ın üst kapsamda silmesi modellenmez |
| L6 — "Hiçbir kapı gevşetilmedi" mutlak | İncelemenin dar düzeltmesi, kilitsiz optik red ve L9 sonucuyla | "Uygulama notları" → "Kapı yönü": kapıların kendisi gevşetilmedi; kilidin kalıcılığı üç ön koşul sınıfında kullanıcı kararlarıyla kaldırıldı; iki yan etki (iz yok; madde 3 atlamasını durduran dolaylı kilit yok) |
| L7 — teknik kayıt yok iletisi N14'ün kendi `STOP`'unu ayırmıyor | İncelemenin dar düzeltmesi, ileti seçeneği (tek sayfa değişmedi) | N108 teknik kayıt yok iletisine: `Teknik kayit blogu STOP verdiyse yeniden denemeyin: a9 yazin, pencereyi kapatin; ajana ancak pencere kapandiktan sonra donun.` Sınıflandırma (madde 4) değişmedi |
| L8 — bir kerelik hazırlıkta Claude masaüstü yok | Kullanıcı kararı L8 | §4.3 (a) hazırlık adım 1: Claude (masaüstü) başlangıç öğesi; Claude masaüstü (planlayıcı) gerektiğinde elle açılır, her içerik penceresinden önce kapatılır |
| L9 — `a4` PASS madde 3'ün yapıldığını dolaylı olarak da göstermiyor | Kullanıcı kararı L9: **denetim eklenmedi** (gerekçe aşağıda) | §32/39 (l) yeni; "Kapı yönü" (L6); §34.4 listesine "madde 3'ün yardımsız yapılması" |

**L9 için seçilen yol ve gerekçesi.** Kullanıcı kararı koşulludur: teknik
kayıt her içerik penceresinde yeniden yazılıyorsa oturum denetimi
eklenir, yazılmıyorsa eklenmez. Runbook metni bu noktada belirsiz
değildir: §4.4/6 kaydı zincir adım 4'te, intake'ten önce, **bir kez** ve
exclusive-create ile yazdırır; "Kayıt yeniden üretilmez, üzerine
yazılmaz" ve "araç değişirse **DUR** ve runbook revizyonu" der; her
kullanımda yeniden yapılan yalnız N15 araç manifesti doğrulamasıdır.
§2.1 zincir adım 4 tek bir preflight adımıdır ve `a4` pilot boyunca bir
kez çalışır (`steps\e2\a4.txt`). Kayıt bu yüzden her pencerede yeniden
yazılmaz; bir `LOADED_AT` denetimi, önceki bir pencerede meşru olarak
yazılmış kayıtla (örneğin `a9` + pencere kapatma isteyen bir kilitsiz
redden sonra) devam etmesi gereken `a4`'ü, kayıt yeniden yazılamadığı
için düzeltilemez biçimde reddederdi. Tek sayfa madde 3'teki "zincir
adım 4'ün kalan blokları (kapsayıcı, teknik kayıt, yol kapısı)" ifadesi
gevşek bir özettir ve §4.4/6'ya tabidir; bu turda değiştirilmedi
(§32/39 l o turda bunu yazıyordu). Sonradan tek sayfa netleştirmesiyle
(`USER_DECISION at=2026-10-18T14:45+03:00`; karar günlüğü) netleştirildi.

**Observation'lar (değerlendirildi, değişiklik yok; kullanıcı kararı).**

| Gözlem | Değerlendirme |
|---|---|
| O1 — kilitsiz redler iz bırakmaz | 12:50 kararının bilinçli sonucu; "Kapı yönü"nde yan etki (i) olarak anıldı |
| O2 — sonlandırma listesinde `claude` | Gerçek pilotta pencere öncesi ajan kapalıdır; ajanın kendi terminalinden kapatılıp ancak ondan sonra sürecin sonlandırılması prova planının konusudur |
| O3 — not formu K4 yükleme hatası DUR'unu ayırmaz | Değişiklik yok; §32/39 (f) ve tek sayfa madde 1 ("a8/a9 burada yok") yükleme hatasında `a9` olmadığını yazar |
| O4 — `ALREADY` iletisi madde 3'ü anmaz | Değişiklik yok; `a3` PASS iletisi madde 3'ü adlandırır |
| O5 — `Invoke-KitAttempt`'in "Istem yoksa hicbir sey yazmayin" iletisi | Değişiklik yok; E/H istisnası tek sayfadadır (yorum 7) |
| O6 — yazıcı ön koşulu §1.6'da ayrıca adlandırılmamış | Değişiklik yok; yazıcısız düzen prova planındadır; gerçek koşuda yazıcı yoksa kurulum ilerleyemez (fail-closed) |
| O7 — N108 ara hash'leri diskte doğrulanamıyor | Değişiklik yok; ara hash'ler tarihsel kayıttır, nihai hash'ler doğrulanabilir |

**Bu revizyonda hash'i değişen ve eklenen bloklar.**

| Blok | Eski SHA-256 | Yeni SHA-256 | `ParseInput` |
|---|---|---|---|
| N105 (`ac.ps1`) | `fdb0e55502e70ed3f54969291b2f4d2ebaa2a46456bed3169311f4357c7f6ca5` | `fd5f352d8c1abf9426af5d38642e7f51d040198db2fac9325b62880f4c193d17` | 0 hata |
| N107 (`a3.ps1`) | `790e247cdafe671321033c559adff15b7a2360d963dc6d7610cad71e07c351c1` | `2d2c79ebcf9cc4788ba7627ed4756689f6991aa22de4dfe454907ee098a5ce3f` | 0 hata |
| N108 (`a4.ps1`) | `92888495ca90b009cd65ee1808c0a96cdfff531d909bff3af4307125cf0a98c1` | `e1b73dafb2bb8201e4ce63676e3eda86f128251bc6278ec5174f786769d9a1b6` | 0 hata |
| N114 (tek sayfa, `text`) | `77a2186ff9bc6f0ff1304599095d95887ebe2f5d305d02e9533b95d130a916da` | `ba942c6f221c198de49409a16beb97e06effae4fe9f11ae064fb25ecaa0cd1aa` | — (PowerShell değil) |
| N115 (not formu, Ek R3/6, `text`; yeni) | — | `89f25247adf08466e481a8768cb6eccb52fa5b88579ed8f9b612d6336e276eae` | — (PowerShell değil) |
| N116 (`kvc.ps1`, Ek R3/7; yeni; kit dosyası değil) | — | `a8524ff98356dccb11e83a9b5ee25e5568bf38440cccce504c75ca9f8a9b5a61` | 0 hata |

Blok sayısı 115 → 117. Diğer 111 blok (N0–N104, N106, N109–N113)
`5153593` ile bayt-bayt aynıdır ve aynı sırada durur (blok hash'leriyle
ölçüldü); yeni bloklar dosyanın sonundadır, mevcut numaralar kaymaz.
§34.9 ana tablosundaki N105, N107, N108 ve N114 satırları ile Ek R3/1'deki
`ac.ps1` satırı yeni değerlere güncellendi; §34.9 ve §34.10'daki ara tur
tabloları tarihsel kayıttır, değişmedi. N105 188 → 197 satır: yorum
satırı ("runbook revizyon 5"), yeni `Write-KitDurRule` (9 satır),
`Write-KitDur`, `Test-KitLock` ve yükleme hatası iletilerinin bu kurala
bağlanması (satır sayısı değişmeden), `Get-KitScript`'in tür denetimi ve
silme oturumu iletisi. N108 17 → 50 satır (ilk yazımda 35, ara hash `687af3d5…30cd`; 12:30 ek kararıyla teknik kayıt ön denetimi +6 satır, ara hash `758afd33…be8a`; 12:50 madde 7 kararıyla optik ön ölçüm +8 satır, ara hash `dc579867…26ad6c` — bağımsız incelemenin doğruladığı değer; 13:30 düzeltme turunda `VERIFY` iletisi +1 satır ve teknik kayıt yok iletisine L7 cümlesi). N107'de yalnız PASS iletisi
değişti. N114'ün revizyon 5 ilk yazımındaki değeri `18f0af14…6015`'tir
(bağımsız incelemenin doğruladığı değer); tek sayfa netleştirmesinde
(`USER_DECISION at=2026-10-18T14:45+03:00`) madde 3'ün parantezli satırı iki satıra
çıktı, N114'ün diğer satırları bayt-bayt aynıdır.

**Bölüm → değişiklik.**

| Bölüm | Değişiklik |
|---|---|
| Üst uyarı, §0, §1.4, §1.6/3, §32/1 | Delta3 yeniden koşusu (d9d67b7d) pinleri ve sonucu; revizyon 5 durumu; §32/1'deki eski "henüz çalıştırılmamıştır" ifadesi gerçek durumla değiştirildi (D5); düzeltme turunda üst uyarı, §1.4 ve §1.6/3'te N116'nın yalnız çıkarılmış kopyalar üzerinde çalıştırıldığı (L1) |
| §1.6/5 | Kanal kapısına bir kerelik hazırlık; kit maddesine N116 ve not formu |
| §4.3 (a) | Bir kerelik bilgisayar hazırlığı (D3); kapatma prosedürü madde 1–2 (önce VS Code; yalnız listelenen süreçler); sistem ayarı cümlesi D3'e bağlandı; "Kit ile yürütme": not formu ve DUR anı kuralı (D2); düzeltme turunda hazırlık adım 1'e Claude (masaüstü) (L8) |
| §4.4/5 | Kit modunda yönlendirme `a4`'te (D1); N13'ün kit penceresinde elle çalıştırılmaması; yer gerekçesi |
| §4.4/6 | Kit modunda teknik kayıt ön denetimi (12:30): kayıt yok veya biçimi geçersizse `a4` kayıt ve kilit yazmadan reddeder; biçimi geçerli kaydın araçlarla uyuşmaması kilitli kalır (düzeltme turunda eklendi, L2) |
| §25.1 H52, Y5 | H52: `a4` kilitsiz reddi ve kayıt sonrası `STOP` ayrımı; Y5: kit modu istisnasına atıf (düzeltme turu, L3) |
| §26.2 | Kit satırına `KIT_VAR_COLLISIONS`, `KIT_VAR_CHECK_TOOL_SHA256`; E2 satırına `SYSTEM_TEMP_MATCH`, `KIT_TEMP_REDIRECT` |
| §32/39 (h)–(l), §32/40 (yeni) | Obs-1 kuralı; N116 sınırı (düzeltme turunda iki modellenmeyen sınıf, L5); TEMP'in yalnız E2'de kitte olması; DUR kuralının zorlanamaması; `a4`'ün teknik kaydın bu oturumda yazıldığını denetlememesi (l; düzeltme turu, L9; tek sayfa netleştirmesine atıf, 14:45); hazırlığın geri alınması |
| §34.4 | Revizyon 5 devralma satırları; düzeltme turunda `a4` red dalları ve prova edilecek davranışlar (M1) |
| §34.9 | Ana tablo N105, N107, N108, N114 ve açıklama cümlesi; tek sayfa netleştirmesinde (14:45) N114 satırı ve açıklama cümlesi |
| §34.11, Ek R3 giriş, Ek R3/1, Ek R3/2 (madde 7 yeni; 7–9 → 8–10), Ek R3/3, Ek R3/4 (tablo `a3`/`a4`, kural 1 ve 2), Ek R3/5 girişi (madde 9 atfı), Ek R3/6 ve Ek R3/7 (yeni) | Bu bölüm; kit blokları, tek sayfa, not formu ve çakışma denetimi; düzeltme turunda N108'in iki iletisi (L4, L7), Ek R3/7 sınır paragrafı (L5) ve bu bölümün düzeltme turu kayıtları; tek sayfa netleştirmesinde (14:45) Ek R3/5 madde 3 (N114) ve bu bölümün ilgili kayıtları (karar günlüğü, blok tablosu, statik denetimler) |

Revizyon 5 bir sonraki delta provasını yetkilendirmez; o ayrı bir
kullanıcı kararıdır (yeni kök).

---

## Ek R3 — İnsan adım kiti ve tek sayfalık adım listesi (revizyon 3)

YENİ (revizyon 3; kullanıcı kararları K-R3-1…K-R3-12, S-1, S-2; §34.9).
Bu ekteki bloklar yazılırken **çalıştırılmadı**; yalnız `ParseInput` ile
denetlendi ve delta3 provasına tabidir. Revizyon 5 (§34.11) N105, N107,
N108 ve N114'ü değiştirdi, Ek R3/6 (not formu, N115) ve Ek R3/7
(değişken adı çakışma denetimi, N116) eklendi; bunlar da yalnız
`ParseInput`, AST ve hash ile denetlendi ve bir sonraki delta provasına
tabidir. Kit gerçek içerik okumaz; ekrana ve
kayda yalnız durum satırları (`^(STOP )?[A-Z0-9_]+(=| )`) yazar.

### Ek R3/1 Kit dosyaları

Kit `<evidence-dir>\kit\` altında **tam olarak** şu 19 dosyadan oluşur.
`.ps1` dosyalarının baytları, kaynak bloğun gövdesine (çit satırları
hariç, LF ile birleştirilmiş, sonda LF; BOM yok, yalnız ASCII) **eşittir**;
SHA-256 değerleri §34.9 ve aşağıdaki tablodadır.

| Kit dosyası | Kaynak blok | SHA-256 |
|---|---|---|
| `ac.ps1` | N105 (Ek R3/3) | `fd5f352d8c1abf9426af5d38642e7f51d040198db2fac9325b62880f4c193d17` (revizyon 5) |
| `a2.ps1` … `a9.ps1` | N106 … N113 (Ek R3/4) | §34.9 tablosu (`a3.ps1` ve `a4.ps1` revizyon 5 değerleriyle) |
| `n003.ps1` | N3 (§4.2/10 optik sürücü) | `6bbb9e0c0422baa967edb15d56e94b350a078de37ab6de8f3d5fc892c455a1d4` |
| `n004.ps1` | N4 (§4.3 a tarama) | `b216d82434a36e5b79963cedfff578c7bd065fb13fe03c2b5ca9557a480e520d` |
| `n006.ps1` | N6 (§4.3 b oturum denetimi) | `0fed2f837dc22f54f28b556021394d14fb5f85138cc9f6d1cab21e69233cd0e8` |
| `n014.ps1` | N14 (§4.4/6 teknik kayıt; kit **yalnız satır 1**'i, `Get-PilotBinManifestSha` tanımını çalıştırır) | `60fe475b9308a068dac695533e8b7dfaf00aab7b339b7ff39541fba12f681403` |
| `n015.ps1` | N15 (§4.4/6 araç yeniden doğrulaması) | `6ddbb71576078e321864ca5b145996849df3e15f4eee4aec7ec970deefa98e59` |
| `n016.ps1` | N16 (§6.4 listeleme) | `326c9216f8eeedd922b1d7fca8b8584e87ccb29b2c21e2151a23b4199449b609` |
| `n017.ps1` | N17 (§6.4 açma) | `1ea37c4b84d31a24c1e938892a35c6375546d0461e8b89a9fb18c76fe0380cbb` |
| `n051.ps1` | N51 (§13.8 ortak yardımcılar) | `3204b405edadff06f14619bcff3f143750557fbba2a59c6654cd8c60d5f27e3f` |
| `kit-values.txt` | Koşuya özgü; tam altı satır `<ad>=<değer>`: `repo-root`, `intake-dir`, `container-temp`, `7z`, `sevenzip-root`, `poppler-bin-dir` (§1.5 dar istisna) | Kurulumda `pins.txt`'ye yazılır |
| `pins.txt` | Koşuya özgü; yukarıdaki 18 dosya için birer satır `<ad> <64-küçük-hex>`, LF | `kit-build.txt` ve her `ac.txt` (`KIT_PINS_SHA256`) |

Blok kopyaları içindeki yer tutucular (`<repo-root>`, `<evidence-dir>`,
`<intake-dir>`, `<7z>`, `<sevenzip-root>`, `<poppler-bin-dir>`,
`<attempt>`) dosyada **değiştirilmez**; kit onları çalıştırmadan hemen önce
yalnız bellekte `kit-values.txt` değerleriyle ve `<evidence-dir>` için
kitin kendi konumuyla doldurur. Doldurmadan sonra `<…>` biçiminde bir yer
tutucu kalırsa blok çalıştırılmaz: `STOP KIT_SCRIPT_LOAD=FAIL`.

### Ek R3/2 Kitin kurulumu (ajan; zincir adım 4'ten önce; tek-çalışım)

1. İçerik penceresinin **dışında**, hiçbir gerçek içerik yokken, tek
   yazan bir ajan oturumunda yapılır; `<evidence-dir>` §13.8
   `PATH_OK=evidence-dir` vermiş olmalıdır.
2. `<evidence-dir>\kit\` **yoksa** oluşturulur; varsa kurulum yapılmaz:
   **DUR** (kit yeniden kurulmaz, üzerine yazılmaz).
3. 17 `.ps1` dosyası Ek R3/1'deki bloklardan bayt-bayt kopyalanır
   (CreateNew); her birinin SHA-256'sı tabloyla eşit ve baytları yalnız
   ASCII olmalıdır. Biri eşit değilse: **DUR**.
4. `kit-values.txt` tam altı satırla yazılır (CreateNew). Her değer köklü
   ve canonical bir yoldur, yalnız sürücü harfi, `\` ve `[A-Za-z0-9 ._()-]`
   karakterlerini taşır, `%USERPROFILE%` altında **değildir**. Denetim
   başarısızsa kit **kurulmaz**: **DUR**; değer sessizce düzeltilmez
   (kullanıcı kararı S-1 notu).
5. `pins.txt` 18 satırla yazılır (CreateNew).
6. Komut adı çakışma ölçümü (addendum E1; R3 düzeltme turu, inceleme L-2):
   ajanın kendi kabuğunda değil, yeni bir `powershell.exe -NoProfile`
   alt sürecinde `Get-Command a2,a3,a4,a5,a6,a7,a8,a9 -ErrorAction
   SilentlyContinue` çalıştırılır ve hiçbir sonuç döndürmemelidir
   (takma ad, fonksiyon, cmdlet veya `PATH`'teki uygulama). Sonuç
   dönerse kit kullanılmaz: **DUR**.
7. Değişken adı çakışma denetimi (revizyon 5; kullanıcı kararı D5;
   Ek R3/7): kurulan 17 `.ps1` dosyası, pinli N116 bloğuyla (SHA-256
   §34.11) yeni bir `powershell.exe -NoProfile` alt sürecinde, yalnız
   AST ayrıştırmasıyla denetlenir. Sonuç `KIT_VAR_COLLISIONS=0`
   değilse (aynı kapsamda büyük-küçük harf duyarsız çakışan yazım,
   `$global:` adlarıyla çakışan ad, ayrıştırma hatası veya eksik dosya)
   kit kullanılmaz: **DUR**; kit dosyası sessizce düzeltilmez (runbook
   revizyonu gerekir).
8. `<evidence-dir>\kit-build.txt` (CreateNew; yol yok): `KIT_BUILD=OK`,
   her dosya için `KIT_FILE_SHA256=<ad> <64-küçük-hex>`,
   `KIT_VALUES_USERPROFILE_FREE=True`, `KIT_NAME_COLLISION_COUNT=0`,
   `KIT_VAR_COLLISIONS=0`, `KIT_VAR_CHECK_TOOL_SHA256=<64-küçük-hex>`
   (N116), `KIT_PINS_SHA256=<64-küçük-hex>`, `KIT_BUILT_AT=<zaman-damgası>`.
9. Tek sayfa (N114) `<case-id>`, `<evidence-dir>` ve `<intake-dir>` doldurularak kâğıda
   basılır; doldurulmuş sayfa evidence'a ve bu belgeye yazılmaz. Not
   formu (N115, Ek R3/6) boş olarak aynı anda basılır.
10. Ajan oturumu kapatılır; içerik penceresinden önce §4.3 (a) kapatma
    prosedürü uygulanır (bir kerelik bilgisayar hazırlığı daha önce
    yapılmış olmalıdır; §4.3 a). Kit pilot boyunca değişmez; değişiklik
    gereği **DUR** ve runbook revizyonudur.

### Ek R3/3 Pencerenin açılması ve kitin yüklenmesi

Operatör Win+R kutusuna kâğıttaki tek satırı yazar:

`powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -Command ". '<evidence-dir>\kit\ac.ps1'"`

`ac.ps1` (N105) şunları denetler: kit dizininde tam olarak 19 dosya ve
hiç alt dizin; `pins.txt` biçimi ve 18 adın her biri; her dosyanın
SHA-256'sı; `kit-values.txt` biçimi ve §1.5 koşulları. Hepsi geçerse
`<evidence-dir>\steps\s<k>\` (k = 1, 2, 3, …; ilk var olmayan; üst
sınır yok) oturum dizinini ve `ac.txt` kaydını (`KIT_LOAD=OK`,
`KIT_PINS_SHA256`, `KIT_DUR_PRESENT`, `KIT_TEARDOWN_SESSION`) yazar ve
`a2`…`a9` komutlarını tanımlar. Herhangi bir denetim geçmezse (kitin
kendi konumundan türetilen `<evidence-dir>`'in `kit-values.txt` ile aynı
karakter kümesi denetimi dahil: `KIT_LOAD_EVID_CHARS`; R3 düzeltme
turu, inceleme O-3) `<evidence-dir>\DUR.txt` (`KIT_DUR_REASON=KIT_LOAD_<kod>`)
yazılır ve hiçbir komut tanımlanmaz. Oturum dizini oluşturulamazsa
`KIT_SESSION_CREATE_FAIL` ile **DUR** olur ve hiçbir komut tanımlanmaz.
`DUR.txt` zaten varsa kit yüklenir ve pencere bir **silme oturumudur**
(§4.3 a): yalnız `a2`, `a3`, `a8` ve `a9` çalışır, `a4`–`a7` çalışmaz;
yükleme iletisi, silme günü değilse pencerenin `a2` yazılmadan hemen
kapatılmasını söyler (revizyon 5; kullanıcı kararı D2). Kitin bütün DUR
iletileri aynı DUR kuralını basar (Ek R3/4 kural 1). Oturum sayısına sınır yoktur (R3 düzeltme turu; kullanıcı kararı
M-1: oturum adını operatör yazmaz).

```powershell
# ac.ps1 - Ek R3 kit onyukleyicisi (runbook revizyon 5). ASCII. Yalniz dot-source ile yuklenir (Ek R3/3).
# Pinleri, kit-values.txt'yi ve DUR kilidini denetler; kit fonksiyonlarini ve a2..a9 komutlarini tanimlar.
# Icerik okumaz, 7z veya baska arac cagirmaz.
if ($null -ne $global:KitSess) { Write-Host 'KIT zaten yuklu. Yeni oturum icin pencereyi kapatip kagittaki komutla yeniden acin.'; return }
$global:KitDir = $PSScriptRoot
$global:KitEvid = Split-Path -Parent $PSScriptRoot
$global:KitVal = $null
$global:KitPins = $null
$global:KitSessDir = $null
$global:KitE2Dir = $null
$global:KitTeardown = $false
$global:KitRx = '^(STOP )?[A-Z0-9_]+(=| )'
function global:Get-KitNow { return [DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz', [System.Globalization.CultureInfo]::InvariantCulture) }
function global:Get-KitSha([byte[]]$Bytes) { $s = [System.Security.Cryptography.SHA256]::Create(); try { return ([System.BitConverter]::ToString($s.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() } finally { $s.Dispose() } }
function global:Write-KitBytes([string]$Path, [string[]]$Lines, [System.IO.FileMode]$Mode) {
    $fs = [System.IO.File]::Open($Path, $Mode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try { foreach ($l in $Lines) { $b = [System.Text.Encoding]::UTF8.GetBytes($l + "`n"); $fs.Write($b, 0, $b.Length) } } finally { $fs.Dispose() }
}
function global:Write-KitDurRule {
    $kitHasCmd = Test-Path -LiteralPath 'Function:\a9'
    $kitA9Done = ($null -ne $global:KitSessDir) -and (Test-Path -LiteralPath (Join-Path $global:KitSessDir 'a9.txt'))
    if ($kitHasCmd) { Write-Host 'Parola kagidi varsa yirtin ve a8 yazin.' } else { Write-Host 'Parola kagidi varsa yirtin. Bu pencerede a8 ve a9 yok; saati not formuna yazin.' }
    if ($kitHasCmd -and (-not $kitA9Done)) { Write-Host 'SIMDI a9 YAZIN (kapanis taramasi).' }
    Write-Host 'Sonra pencereyi kapatin. Kiti yeniden ACMAYIN (ajan, pencere kapandiktan sonra yazili olarak soylemedikce).'
    Write-Host 'Hicbir yapay zeka araci veya sohbet ACMAYIN; ekrani hicbir yere yapistirmayin, fotograflamayin.'
    Write-Host 'Ne oldugunu not formuna yazin. Ajana ancak pencere kapandiktan sonra donun.'
}
function global:Write-KitDur([string]$Step, [string]$Reason) {
    $p = Join-Path $global:KitEvid 'DUR.txt'
    if (-not (Test-Path -LiteralPath $p)) { try { Write-KitBytes $p @("KIT_DUR step=$Step at=$(Get-KitNow)", "KIT_DUR_REASON=$Reason") ([System.IO.FileMode]::CreateNew) } catch { Write-Host 'STOP KIT_DUR_WRITE=FAIL' } }
    Write-Host "DUR. Adim $Step durdu ($Reason). Kalan adimlari yapmayin."
    Write-KitDurRule
}
function global:Test-KitLock {
    if (Test-Path -LiteralPath (Join-Path $global:KitEvid 'DUR.txt')) { Write-Host 'DUR - devam yok.'; Write-KitDurRule; return $true }
    return $false
}
function global:New-KitRecord([string]$Path, [string[]]$Lines) {
    if (Test-Path -LiteralPath $Path) { Write-Host "Bu adim zaten calisti: $(Split-Path -Leaf $Path). Tekrar calismaz."; return $false }
    try { Write-KitBytes $Path $Lines ([System.IO.FileMode]::CreateNew) } catch { Write-Host 'STOP KIT_RECORD_CREATE=FAIL'; return $false }
    foreach ($l in $Lines) { Write-Host $l }
    return $true
}
function global:Add-KitLine([string]$Path, [string]$Line) { Write-KitBytes $Path @($Line) ([System.IO.FileMode]::Append); Write-Host $Line }
function global:Read-KitRecord([string]$Path) {
    try { if (Test-Path -LiteralPath $Path -PathType Leaf) { [string[]][System.IO.File]::ReadAllLines($Path, (New-Object System.Text.UTF8Encoding($false))) } } catch { }
}
function global:Get-KitField([string[]]$Lines, [string]$Prefix) {
    foreach ($l in $Lines) { if ($l.StartsWith($Prefix, [System.StringComparison]::Ordinal)) { return $l.Substring($Prefix.Length) } }
    return $null
}
function global:Test-KitPass([string]$Path, [bool]$SameSession) {
    $r = @(Read-KitRecord $Path)
    if ($r.Count -eq 0) { return $false }
    if ($r -cnotcontains 'STEP_RESULT=PASS') { return $false }
    if ($SameSession -and ($r -cnotcontains "KIT_SESSION=$($global:KitSess)")) { return $false }
    return $true
}
function global:Get-KitHeader([string]$Name) { $h = @("STEP=$Name", "KIT_SESSION=$($global:KitSess)", "KIT_FILE_SHA256=$Name.ps1 $($global:KitPins[$Name + '.ps1'])", "STARTED_AT=$(Get-KitNow)"); if ($global:KitTeardown) { $h += 'KIT_TEARDOWN_SESSION=True' }; return $h }
function global:Get-KitScript([string]$Name, [hashtable]$Subst, [string]$FirstLine) {
    if (($null -eq $global:KitPins) -or (-not ($global:KitPins -is [hashtable])) -or ($global:KitPins.Count -eq 0)) { return $null }
    try { $b = [System.IO.File]::ReadAllBytes((Join-Path $global:KitDir "$Name.ps1")) } catch { return $null }
    if ((Get-KitSha $b) -cne [string]$global:KitPins[$Name + '.ps1']) { return $null }
    foreach ($x in $b) { if ($x -gt 127) { return $null } }
    $t = [System.Text.Encoding]::ASCII.GetString($b)
    if ($FirstLine -cne '') { $t = $t.Split([char]10)[0]; if (-not $t.StartsWith($FirstLine, [System.StringComparison]::Ordinal)) { return $null } }
    if ($null -ne $Subst) { foreach ($k in $Subst.Keys) { $t = $t.Replace('<' + $k + '>', [string]$Subst[$k]) } }
    if ($t -cmatch '<[a-z][a-z0-9-]*>') { return $null }
    try { return [scriptblock]::Create($t) } catch { return $null }
}
function global:Invoke-KitBlock([string]$Rec, [string]$Name, [hashtable]$Subst) {
    $sb = Get-KitScript $Name $Subst ''
    if ($null -eq $sb) { Add-KitLine $Rec "STOP KIT_SCRIPT_LOAD=FAIL file=$Name"; return }
    Add-KitLine $Rec "--- $Name"
    $kitNs = 0; $kitEr = 0
    & $sb 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $kitEr++ } else { $kitLn = [string]$_; if ($kitLn -cmatch $global:KitRx) { Add-KitLine $Rec $kitLn } else { $kitNs++ } } }
    if ($kitNs -eq 0) { Add-KitLine $Rec 'KIT_NONSTATUS_LINE_COUNT=0' } else { Add-KitLine $Rec "STOP KIT_NONSTATUS_LINE_COUNT=$kitNs" }
    if ($kitEr -gt 0) { Add-KitLine $Rec "STOP KIT_ERROR_RECORD_COUNT=$kitEr" }
}
function global:Complete-KitStep([string]$Rec, [string]$Name, [string[]]$Required, [string]$PassMsg) {
    $r = @(Read-KitRecord $Rec)
    $ok = ($r.Count -gt 0) -and (@($r | Where-Object { $_.StartsWith('STOP ', [System.StringComparison]::Ordinal) }).Count -eq 0)
    foreach ($q in $Required) { if ($r -cnotcontains $q) { $ok = $false } }
    if ($ok) { Add-KitLine $Rec 'STEP_RESULT=PASS' } else { Add-KitLine $Rec 'STEP_RESULT=STOP' }
    Add-KitLine $Rec "ENDED_AT=$(Get-KitNow)"
    if ($ok) { Write-Host $PassMsg } else { Write-KitDur $Name 'STEP_STOP' }
    return $ok
}
function global:Clear-KitKeys { try { while ([Console]::KeyAvailable) { $null = [Console]::ReadKey($true) } } catch { } }
function global:Read-KitYesNo([string]$Question) {
    Clear-KitKeys
    for ($i = 0; $i -lt 2; $i++) {
        Write-Host "$Question   Evet: E tusu   Hayir: H tusu"
        $c = [string]([Console]::ReadKey($true).KeyChar)
        if (($c -ceq 'E') -or ($c -ceq 'e')) { Write-Host 'E'; return 'E' }
        if (($c -ceq 'H') -or ($c -ceq 'h')) { Write-Host 'H'; return 'H' }
        Write-Host 'Gecersiz tus.'
    }
    return 'X'
}
function global:Invoke-KitAttempt([int]$Attempt, [string]$Name) {
    if (-not [Console]::CapsLock) { Write-Host "CAPS LOCK KAPALI. Caps Lock tusuna basin ve yeniden $Name yazin. Deneme harcanmadi."; return }
    $rec = Join-Path $global:KitE2Dir "$Name.txt"
    if (-not (New-KitRecord $rec (@(Get-KitHeader $Name) + @("ATTEMPT=$Attempt")))) { return }
    Write-Host 'Parolayi kagittan, YALNIZ ekranda Enter password istemi gorunurken yazin. Istem yoksa hicbir sey yazmayin.'
    Invoke-KitBlock $rec 'n017' @{ '7z' = $global:KitVal['7z']; 'intake-dir' = $global:KitVal['intake-dir']; 'attempt' = [string]$Attempt }
    $p = Read-KitYesNo 'Ekranda parola istemi (Enter password) gorundu mu?'
    if ($p -ceq 'E') { Add-KitLine $rec "SEVENZIP_PASSWORD_PROMPT_SHOWN=True attempt=$Attempt" } elseif ($p -ceq 'H') { Add-KitLine $rec "STOP SEVENZIP_PASSWORD_PROMPT_SHOWN=False attempt=$Attempt"; Add-KitLine $rec 'STOP E2_CARRIER_ENCRYPTED=False' } else { Add-KitLine $rec "STOP SEVENZIP_PASSWORD_PROMPT_SHOWN=UNKNOWN attempt=$Attempt" }
    $w = Read-KitYesNo 'Ekranda Wrong password yazisi gorundu mu?'
    if ($w -ceq 'E') { Add-KitLine $rec "SEVENZIP_WRONG_PASSWORD_SHOWN=True attempt=$Attempt" } elseif ($w -ceq 'H') { Add-KitLine $rec "SEVENZIP_WRONG_PASSWORD_SHOWN=False attempt=$Attempt" } else { Add-KitLine $rec "STOP SEVENZIP_WRONG_PASSWORD_SHOWN=UNKNOWN attempt=$Attempt" }
    $r = @(Read-KitRecord $rec)
    $noStop = (@($r | Where-Object { $_.StartsWith('STOP ', [System.StringComparison]::Ordinal) }).Count -eq 0)
    $succ = $noStop -and ($r -ccontains "SEVENZIP_RC=0 attempt=$Attempt") -and ($r -ccontains "X_ENTRY_COUNT=1 attempt=$Attempt") -and ($r -ccontains "SEVENZIP_PASSWORD_PROMPT_SHOWN=True attempt=$Attempt") -and ($r -ccontains "SEVENZIP_WRONG_PASSWORD_SHOWN=False attempt=$Attempt")
    $retry = ($Attempt -eq 1) -and $noStop -and ($r -ccontains 'SEVENZIP_RC=2 attempt=1') -and ($r -ccontains 'X_ENTRY_COUNT=0 attempt=1') -and ($r -ccontains 'SEVENZIP_PASSWORD_PROMPT_SHOWN=True attempt=1') -and ($r -ccontains 'SEVENZIP_WRONG_PASSWORD_SHOWN=True attempt=1')
    if ($succ) { Add-KitLine $rec 'ATTEMPT_OUTCOME=SUCCESS'; Add-KitLine $rec 'E2_CARRIER_ENCRYPTED=True'; $null = Complete-KitStep $rec $Name @('ATTEMPT_OUTCOME=SUCCESS') 'Acma basarili. Parola kagidini BUGUN yirtin, sonra a8 yazin.' }
    elseif ($retry) { Add-KitLine $rec 'ATTEMPT_OUTCOME=RETRY_ALLOWED'; $null = Complete-KitStep $rec $Name @('ATTEMPT_OUTCOME=RETRY_ALLOWED') 'Tek ek deneme hakki var. Caps Lock acik olsun, sonra a7 yazin.' }
    else { Add-KitLine $rec 'STOP ATTEMPT_OUTCOME=FAIL'; $null = Complete-KitStep $rec $Name @('ATTEMPT_OUTCOME=SUCCESS') '' }
    Clear-KitKeys
}
function global:Invoke-KitStep([string]$Name, [bool]$LockExempt) {
    if ($global:KitTeardown -and (@('a4', 'a5', 'a6', 'a7') -ccontains $Name)) { Write-Host 'SILME OTURUMU: a4-a7 bu pencerede calismaz.'; return }
    if ((-not $LockExempt) -and (Test-KitLock)) { return }
    $sb = Get-KitScript $Name $null ''
    if ($null -eq $sb) { Write-KitDur $Name 'KIT_SCRIPT_LOAD_FAIL'; return }
    try { & $sb } catch { Write-KitDur $Name 'KIT_EXCEPTION' }
    Clear-KitKeys
    Write-Host 'Bu ekrani hicbir yere yapistirmayin, fotografini cekmeyin.'
}
$kitWhy = ''
$kitNames = @('ac.ps1', 'a2.ps1', 'a3.ps1', 'a4.ps1', 'a5.ps1', 'a6.ps1', 'a7.ps1', 'a8.ps1', 'a9.ps1', 'n003.ps1', 'n004.ps1', 'n006.ps1', 'n014.ps1', 'n015.ps1', 'n016.ps1', 'n017.ps1', 'n051.ps1', 'kit-values.txt')
$kitValNames = @('repo-root', 'intake-dir', 'container-temp', '7z', 'sevenzip-root', 'poppler-bin-dir')
try {
    $kitPinBytes = [System.IO.File]::ReadAllBytes((Join-Path $global:KitDir 'pins.txt'))
    $kitPinsTbl = New-Object System.Collections.Hashtable ([System.StringComparer]::Ordinal)
    foreach ($kitL in [System.Text.Encoding]::ASCII.GetString($kitPinBytes).Split([char]10)) {
        if ($kitL -ceq '') { continue }
        $kitM = [regex]::Match($kitL, '^([a-z0-9.-]+) ([0-9a-f]{64})$')
        if ((-not $kitM.Success) -or $kitPinsTbl.ContainsKey($kitM.Groups[1].Value)) { $kitWhy = 'PINS_FORMAT'; break }
        $kitPinsTbl[$kitM.Groups[1].Value] = $kitM.Groups[2].Value
    }
    if (($kitWhy -ceq '') -and ($global:KitEvid -cnotmatch '^[A-Za-z]:\\[A-Za-z0-9 ._()\\-]*$')) { $kitWhy = 'EVID_CHARS' }
    if (($kitWhy -ceq '') -and ($kitPinsTbl.Count -ne $kitNames.Count)) { $kitWhy = 'PINS_COUNT' }
    if ($kitWhy -ceq '') { foreach ($kitN in $kitNames) { if (-not $kitPinsTbl.ContainsKey($kitN)) { $kitWhy = 'PINS_NAME' } } }
    if ($kitWhy -ceq '') {
        $kitItems = @(Get-ChildItem -LiteralPath $global:KitDir -Force -ErrorAction Stop)
        if ($kitItems.Count -ne ($kitNames.Count + 1)) { $kitWhy = 'KIT_DIR_COUNT' }
        foreach ($kitI in $kitItems) { if ($kitI.PSIsContainer -or (($kitNames -cnotcontains $kitI.Name) -and ($kitI.Name -cne 'pins.txt'))) { $kitWhy = 'KIT_DIR_ITEM' } }
    }
    if ($kitWhy -ceq '') { foreach ($kitN in $kitNames) { if ((Get-KitSha ([System.IO.File]::ReadAllBytes((Join-Path $global:KitDir $kitN)))) -cne $kitPinsTbl[$kitN]) { $kitWhy = 'PIN_MISMATCH' } } }
    if ($kitWhy -ceq '') {
        $kitValTbl = New-Object System.Collections.Hashtable ([System.StringComparer]::Ordinal)
        $kitUp = [System.IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\') + '\'
        foreach ($kitL in [System.IO.File]::ReadAllLines((Join-Path $global:KitDir 'kit-values.txt'), (New-Object System.Text.UTF8Encoding($false)))) {
            $kitM = [regex]::Match($kitL, '^([a-z0-9-]+)=(.+)$')
            if ((-not $kitM.Success) -or ($kitValNames -cnotcontains $kitM.Groups[1].Value) -or $kitValTbl.ContainsKey($kitM.Groups[1].Value)) { $kitWhy = 'VALUES_FORMAT'; break }
            $kitV = $kitM.Groups[2].Value
            if ($kitV -cnotmatch '^[A-Za-z]:\\[A-Za-z0-9 ._()\\-]*$') { $kitWhy = 'VALUES_CHARS'; break }
            if ([System.IO.Path]::GetFullPath($kitV).TrimEnd('\') -cne $kitV.TrimEnd('\')) { $kitWhy = 'VALUES_CANONICAL'; break }
            if (($kitV.TrimEnd('\') + '\').StartsWith($kitUp, [System.StringComparison]::OrdinalIgnoreCase)) { $kitWhy = 'VALUES_USERPROFILE'; break }
            $kitValTbl[$kitM.Groups[1].Value] = $kitV
        }
        if (($kitWhy -ceq '') -and ($kitValTbl.Count -ne $kitValNames.Count)) { $kitWhy = 'VALUES_COUNT' }
    }
} catch { if ($kitWhy -ceq '') { $kitWhy = 'LOAD_EXCEPTION' } }
if ($kitWhy -cne '') {
    $kitDurP = Join-Path $global:KitEvid 'DUR.txt'
    if (-not (Test-Path -LiteralPath $kitDurP)) { try { Write-KitBytes $kitDurP @("KIT_DUR step=ac at=$(Get-KitNow)", "KIT_DUR_REASON=KIT_LOAD_$kitWhy") ([System.IO.FileMode]::CreateNew) } catch { Write-Host 'STOP KIT_DUR_WRITE=FAIL' } }
    Write-Host "DUR. KIT YUKLENEMEDI (KIT_LOAD_$kitWhy). Hicbir adim calismaz."
    Write-KitDurRule
} else {
    $global:KitPins = $kitPinsTbl
    $kitValTbl['evidence-dir'] = $global:KitEvid
    $global:KitVal = $kitValTbl
    $kitSteps = Join-Path $global:KitEvid 'steps'
    $null = [System.IO.Directory]::CreateDirectory($kitSteps)
    $global:KitE2Dir = Join-Path $kitSteps 'e2'
    $null = [System.IO.Directory]::CreateDirectory($global:KitE2Dir)
    try { for ($kitK = 1; $null -eq $global:KitSess; $kitK++) { $kitS = Join-Path $kitSteps "s$kitK"; if (-not (Test-Path -LiteralPath $kitS)) { $null = [System.IO.Directory]::CreateDirectory($kitS); $global:KitSessDir = $kitS; $global:KitSess = "s$kitK" } } } catch { }
    if ($null -eq $global:KitSess) {
        $global:KitSess = 'none'
        Write-KitDur 'ac' 'KIT_SESSION_CREATE_FAIL'
    } else {
        $kitDurOn = Test-Path -LiteralPath (Join-Path $global:KitEvid 'DUR.txt')
        $global:KitTeardown = $kitDurOn
        $null = New-KitRecord (Join-Path $global:KitSessDir 'ac.txt') @('STEP=ac', "KIT_SESSION=$($global:KitSess)", "KIT_FILE_SHA256=ac.ps1 $($kitPinsTbl['ac.ps1'])", "KIT_PINS_SHA256=$(Get-KitSha $kitPinBytes)", "KIT_DUR_PRESENT=$kitDurOn", "KIT_TEARDOWN_SESSION=$kitDurOn", 'KIT_LOAD=OK', "LOADED_AT=$(Get-KitNow)")
        function global:a2 { Invoke-KitStep 'a2' $global:KitTeardown }
        function global:a3 { Invoke-KitStep 'a3' $global:KitTeardown }
        function global:a4 { Invoke-KitStep 'a4' $false }
        function global:a5 { Invoke-KitStep 'a5' $false }
        function global:a6 { Invoke-KitStep 'a6' $false }
        function global:a7 { Invoke-KitStep 'a7' $false }
        function global:a8 { Invoke-KitStep 'a8' $true }
        function global:a9 { Invoke-KitStep 'a9' $true }
        if ($kitDurOn) { Write-Host "KIT YUKLENDI, ama DUR kilidi var: SILME OTURUMU $($global:KitSess). Silme gunu degilse a2 yazmadan pencereyi simdi kapatin. Yalniz a2, a3 (kanal kapisi), a8 ve a9 calisir; a4-a7 calismaz." } else { Write-Host "KIT YUKLENDI. Oturum $($global:KitSess). Siradaki: a2 yazip Enter." }
    }
}
Remove-Variable kitWhy, kitNames, kitValNames, kitPinBytes, kitPinsTbl, kitL, kitM, kitN, kitItems, kitI, kitValTbl, kitUp, kitV, kitDurP, kitSteps, kitK, kitS, kitDurOn -ErrorAction SilentlyContinue
```

### Ek R3/4 Adımlar ve ortak kurallar

| Komut | İş | Ön koşul | Kayıt | DUR kilidinde |
|---|---|---|---|---|
| `a2` | `CONTENT_SESSION_EP`, N6, kanal taraması 1 (N4) | Yeni oturum | `steps\s<k>\a2.txt` | Yalnız silme oturumunda (kilitle açılmış pencere) çalışır |
| `a3` | Kanal taraması 2 (N4); 120 sn dolmadan tarama ve kayıt yok; PASS iletisi aktarım günü önce tek sayfa madde 3'ün kalan bloklarını, sonra `a4`'ü adlandırır (revizyon 5) | Aynı oturumda `a2` PASS | `steps\s<k>\a3.txt` | Yalnız silme oturumunda çalışır |
| `a4` | Kayıttan **önce** ön koşul denetimi: `technical-record.txt`'nin varlığı ve biçimi (revizyon 5 ek kararı), optik sürücü ön ölçümü (disk/görüntü yok, sürücü kümesi kayıtla aynı; sorgu başarısız veya durum okunamıyorsa ön ölçüm reddetmez, kayıt içindeki N3 kilitler; revizyon 5 madde 7 kararı), TEMP ön denetimi ve yönlendirmesi (sistem Temp kaydıyla eşleşme, `container-temp` dizini, yönlendirme sonrası doğrulama); geçmezse kayıt ve kilit yok, `a4 BASLAMADI: …` iletisi eksiği ve yapılacağı adlandırır; kayıtta `SYSTEM_TEMP_MATCH`, `KIT_TEMP_REDIRECT`, `KIT_TEMP_IN_CONTAINER`, optik sürücü (N3), araç manifesti (N51, N14 satır 1, N15) (revizyon 5; kullanıcı kararı D1) | Aynı oturumda `a3` PASS; `<evidence-dir>\system-temp.txt` (§4.4/5, N12) var; zincir adım 4'ün elle çalıştırılan blokları (kapsayıcı doğrulaması, teknik kayıt N14, yol kapısı) tamam; TEMP bu pencerede elle yönlendirilmemiş (N13 kit modunda elle çalıştırılmaz) | `steps\e2\a4.txt` | Çalışmaz |
| `a5` | `transfer.7z` listeleme yöntem kontrolü (N16) | Aynı oturumda `a4` PASS | `steps\e2\a5.txt` | Çalışmaz |
| `a6` | Geri okuma sorusu (E/H), açma denemesi 1 (N17), iki gözlem sorusu (E/H) | Aynı oturumda `a5` PASS; `a8` yok | `steps\e2\a6-readback.txt`, `steps\e2\a6.txt` | Çalışmaz |
| `a7` | Tek ek deneme (N17, deneme 2) | Aynı oturumda `a6` `ATTEMPT_OUTCOME=RETRY_ALLOWED`; `a8` yok | `steps\e2\a7.txt` | Çalışmaz |
| `a8` | Kâğıt imhası; `reason` türetilir (geri okuma kaydı yoksa `stopped`) | `steps\e2\a5.txt` `STEP_RESULT=PASS` (herhangi bir oturumda); operatör "imha ettim" için E | `steps\e2\a8.txt` | **Çalışır** |
| `a9` | Otomatik kapanış taraması (N4) | Aynı oturumda `a2` kaydı var | `steps\s<k>\a9.txt` | **Çalışır** |

Ortak kurallar (hepsi kitin içinde mekaniktir):

1. **Kilit.** Herhangi bir `STOP` satırı adımı `STEP_RESULT=STOP` ile
   bitirir ve `<evidence-dir>\DUR.txt`'yi CreateNew ile yazar
   (`KIT_DUR step=<adım> at=<zaman-damgası>`, `KIT_DUR_REASON=<kod>`).
   `a2`…`a7` ilk iş olarak bu dosyaya bakar; varsa hiçbir araç çağırmadan
   çıkar (istisna: silme oturumunda `a2`/`a3`, §4.3 a; orada `a4`–`a7`
   oturum bayrağıyla reddedilir). Kilidi kaldıran bir kit komutu yoktur.
   Kilit yalnız yazılı kullanıcı kararından sonra kaldırılır: ajan
   `DUR.txt`'yi **silmeden** `DUR-lifted-<n>.txt` (n = ilk var olmayan
   sıra numarası) olarak yeniden adlandırır ve bunu CreateNew ile
   `<evidence-dir>\dur-lift-<n>.txt` kaydına (`KIT_DUR_LIFTED
   from=DUR.txt to=DUR-lifted-<n>.txt at=<zaman-damgası>` ve kararın
   SHA-256'sı) yazar (R3 düzeltme turu; kullanıcı kararı H-1=A).
   **DUR kuralı (revizyon 5; kullanıcı kararı D2).** Kitin her DUR
   iletisi (adım DUR'u, kilit uyarısı, yükleme hatası) aynı kuralı basar:
   kâğıt varsa yırtılır ve `a8`; sonra `a9` (ayrı satırda; `a9` zaten
   çalıştıysa veya kit yüklenmediyse bu satır basılmaz); sonra pencere
   kapatılır; kit yeniden **açılmaz** (ajan, pencere kapandıktan sonra
   yazılı olarak söylemedikçe); hiçbir yapay zekâ aracı veya sohbet
   **açılmaz**, ekran yapıştırılmaz/fotoğraflanmaz; olan not formuna
   (Ek R3/6) yazılır; ajana ancak pencere kapandıktan sonra dönülür.
2. **Sıra ve tek çalışım.** Her adım ön koşul kaydını ve onun
   `STEP_RESULT=PASS` satırını ister; `a4`–`a7` ayrıca aynı oturumu
   (`KIT_SESSION=s<k>`) ister (`a8` istemez: kâğıt kaydı sonraki bir
   pencerede de yazılabilir). Kaydı zaten var olan adım yeniden
   çalışmaz. İstisnalar yalnız kayıt yazmayan dallardır: `a3`'ün erken
   çağrısı, `a4`'ün ön koşul reddi (teknik kayıt yok veya biçimi
   geçersiz, optik sürücüde disk/görüntü veya kayıtla uyuşmayan sürücü
   kümesi, TEMP ön denetimi; `a4 BASLAMADI: …`; kilit yok; revizyon 5)
   ve `a6`/`a7`'nin Caps Lock kapalı dalı.
3. **Ekran = kayıt.** Her durum satırı basıldığı anda önce dosyaya
   (Append), sonra ekrana yazılır; 7z gibi uzun sürebilecek bir çağrıdan
   önceki satırlar çağrıdan önce dosyadadır. Durum satırı olmayan çıktı
   kayda girmez, yalnız sayılır; sayı ≠ 0 → `STOP
   KIT_NONSTATUS_LINE_COUNT`. PowerShell hata kaydı → `STOP
   KIT_ERROR_RECORD_COUNT`. Her adım "Bu ekranı hiçbir yere
   yapıştırmayın, fotoğrafını çekmeyin" satırıyla biter.
4. **Pin.** Her adım ve her blok kopyası çalıştırılmadan hemen önce
   yeniden hash'lenir; uyuşmazlık → `STOP KIT_SCRIPT_LOAD=FAIL` veya
   `KIT_SCRIPT_LOAD_FAIL` kilidi.
5. **Oturum ve E2.** `a2`, `a3`, `a9` her içerik oturumunda yeniden çalışır
   (`steps\s<k>\`); `a4`–`a8` pilot boyunca bir kez çalışır
   (`steps\e2\`).

```powershell
# a2.ps1 - Ek R3: oturum acilis denetimi (N6) ve kanal taramasi 1 (N4). ASCII. Yalniz a2 komutuyla calisir.
$kitRec = Join-Path $global:KitSessDir 'a2.txt'
if (-not (New-KitRecord $kitRec @(Get-KitHeader 'a2'))) { return }
Add-KitLine $kitRec "CONTENT_SESSION_EP=$(Get-ExecutionPolicy -Scope Process)"
Invoke-KitBlock $kitRec 'n006' @{ 'repo-root' = $global:KitVal['repo-root'] }
$kitR = @(Read-KitRecord $kitRec)
if (($kitR -ccontains 'HISTORY_HANDLER_STATE=NONE') -or ($kitR -ccontains 'HISTORY_HANDLER_STATE=DEFAULT')) { Add-KitLine $kitRec 'KIT_HISTORY_HANDLER_OK=True' } else { Add-KitLine $kitRec 'STOP KIT_HISTORY_HANDLER_OK=False' }
Invoke-KitBlock $kitRec 'n004' $null
if ($null -eq (Get-KitField @(Read-KitRecord $kitRec) 'AI_CHANNEL_SCAN at=')) { Add-KitLine $kitRec 'STOP KIT_SCAN_AT=MISSING' }
$null = Complete-KitStep $kitRec 'a2' @('CONTENT_SESSION_EP=Bypass', 'CONTENT_SESSION_NOPROFILE=True', 'TRANSCRIPT_ACTIVE=False', 'EXTRA_MODULE_COUNT=0', 'KIT_HISTORY_HANDLER_OK=True', 'COMMAND_VALIDATION_HANDLER_STATE=NONE', 'HISTORY_SAVE_STYLE=SaveNothing', 'AI_CHANNEL_PROCESS_COUNT=0') 'a2 TAMAM. En az 2 dakika bekleyin, sonra a3 yazin.'
```

```powershell
# a3.ps1 - Ek R3: kanal taramasi 2 (N4), taramadan en az 120 saniye sonra. ASCII. Yalniz a3 komutuyla calisir.
$kitA2 = @(Read-KitRecord (Join-Path $global:KitSessDir 'a2.txt'))
if ($kitA2 -cnotcontains 'STEP_RESULT=PASS') { Write-Host 'Once bu oturumda a2 TAMAM olmali.'; return }
$kitFmt = 'yyyy-MM-ddTHH:mm:sszzz'
$kitInv = [System.Globalization.CultureInfo]::InvariantCulture
$kitD1 = [DateTimeOffset]::ParseExact((Get-KitField $kitA2 'AI_CHANNEL_SCAN at='), $kitFmt, $kitInv)
$kitWait = 120 - [int][Math]::Floor(([DateTimeOffset]::Now - $kitD1).TotalSeconds)
if ($kitWait -gt 0) { Write-Host "BEKLEYIN: $kitWait saniye daha. Sonra yeniden a3 yazin. (Kayit yazilmadi.)"; return }
$kitRec = Join-Path $global:KitSessDir 'a3.txt'
if (-not (New-KitRecord $kitRec @(Get-KitHeader 'a3'))) { return }
Invoke-KitBlock $kitRec 'n004' $null
$kitT2 = Get-KitField @(Read-KitRecord $kitRec) 'AI_CHANNEL_SCAN at='
if ($null -eq $kitT2) { Add-KitLine $kitRec 'STOP KIT_SCAN_AT=MISSING' } else {
    $kitSec = [int][Math]::Floor(([DateTimeOffset]::ParseExact($kitT2, $kitFmt, $kitInv) - $kitD1).TotalSeconds)
    Add-KitLine $kitRec "SCAN_INTERVAL_SEC=$kitSec"
    if ($kitSec -ge 120) { Add-KitLine $kitRec 'SCAN_INTERVAL_OK=True' } else { Add-KitLine $kitRec 'STOP SCAN_INTERVAL_OK=False' }
}
$null = Complete-KitStep $kitRec 'a3' @('AI_CHANNEL_PROCESS_COUNT=0', 'SCAN_INTERVAL_OK=True') 'a3 TAMAM. Kanal kapisi gecti. Aktarim gununde: once kagittaki madde 3 bloklari, sonra a4 (TEMP yonlendirmesini a4 yapar). Diger gunlerde: runbook adimlari. Oturum sonunda a9.'
```

```powershell
# a4.ps1 - Ek R3: TEMP yonlendirmesi (kit; revizyon 5), optik surucu (N3) ve arac manifesti (N51, N14 satir 1, N15). ASCII. Yalniz a4 komutuyla calisir.
if (-not (Test-KitPass (Join-Path $global:KitSessDir 'a3.txt') $true)) { Write-Host 'Once bu oturumda a3 TAMAM olmali.'; return }
$kitRec = Join-Path $global:KitE2Dir 'a4.txt'
if (Test-Path -LiteralPath $kitRec) { Write-Host 'Bu adim zaten calisti: a4.txt. Tekrar calismaz.'; return }
$kitCt = ([string]$global:KitVal['container-temp']).TrimEnd('\')
$kitStRec = @(Read-KitRecord (Join-Path $global:KitEvid 'system-temp.txt'))
$kitStUser = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
$kitStWin = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($env:SystemRoot, 'Temp')).TrimEnd('\')
$kitEnc = New-Object System.Text.UTF8Encoding($false)
$kitTrP = Join-Path $global:KitEvid 'technical-record.txt'
$kitTr = @(Read-KitRecord $kitTrP)
if (-not (Test-Path -LiteralPath $kitTrP -PathType Leaf)) { Write-Host 'a4 BASLAMADI: teknik kayit (technical-record.txt) yok. Once kagittaki madde 3 bloklarindan teknik kaydi yazin, sonra yeniden a4 yazin. Teknik kayit blogu STOP verdiyse yeniden denemeyin: a9 yazin, pencereyi kapatin; ajana ancak pencere kapandiktan sonra donun. (Kayit yazilmadi; DUR kilidi yok.)'; return }
$kitTrOk = ($kitTr.Count -gt 0) -and ($kitTr[0] -ceq '# kind=technical-record')
foreach ($kitTrRx in @('^POPPLER_BIN_MANIFEST_SHA256=[0-9a-f]{64}$', '^SEVENZIP_ROOT_MANIFEST_SHA256=[0-9a-f]{64}$', '^CDROM_DRIVE_COUNT=[0-9]+$', '^OPTICAL_DRIVE_LETTERS=([A-Z]:(,[A-Z]:)*)?$')) { if (@($kitTr | Where-Object { $_ -cmatch $kitTrRx }).Count -ne 1) { $kitTrOk = $false } }
if (-not $kitTrOk) { Write-Host 'a4 BASLAMADI: teknik kayit (technical-record.txt) okunamiyor veya bicimi gecersiz; kayit yeniden yazilmaz. a9 yazin, pencereyi kapatin; ajana ancak pencere kapandiktan sonra donun. (Kayit yazilmadi; DUR kilidi yok.)'; return }
$kitCd = $null; try { $kitCd = @(Get-CimInstance -ClassName Win32_CDROMDrive -ErrorAction Stop) } catch { $kitCd = $null }
if ($null -ne $kitCd) {
    $kitCdL = [string[]]@($kitCd | ForEach-Object { [string]$_.Drive }); [Array]::Sort($kitCdL, [System.StringComparer]::Ordinal)
    $kitCdBad = ($kitTr -cnotcontains "CDROM_DRIVE_COUNT=$($kitCd.Count)") -or ($kitTr -cnotcontains ('OPTICAL_DRIVE_LETTERS=' + ($kitCdL -join ',')))
    $kitCdUnk = $false
    foreach ($kitC in $kitCd) { if ($kitC.MediaLoaded -is [bool]) { if ($kitC.MediaLoaded) { $kitCdBad = $true } } else { $kitCdUnk = $true } }
    if ($kitCdBad -and (-not $kitCdUnk)) { Write-Host 'a4 BASLAMADI: optik surucude disk veya goruntu var ya da surucu kumesi teknik kayitla uyusmuyor. Optik surucudeki diski cikarin veya sanal surucuyu ayirin, sonra yeniden a4 yazin. Ayni ileti yine cikarsa a9 yazin, pencereyi kapatin ve ajana donun. (Kayit yazilmadi; DUR kilidi yok.)'; return }
}
$kitNo = ''
if ([string]::Equals($kitStUser, $kitCt, [System.StringComparison]::OrdinalIgnoreCase)) { $kitNo = 'ALREADY' } elseif ($kitStRec.Count -eq 0) { $kitNo = 'NO_RECORD' } elseif (($kitStRec -cnotcontains ('SYSTEM_TEMP_USER_SHA256=' + (Get-KitSha ($kitEnc.GetBytes($kitStUser))))) -or ($kitStRec -cnotcontains ('SYSTEM_TEMP_WINDOWS_SHA256=' + (Get-KitSha ($kitEnc.GetBytes($kitStWin)))))) { $kitNo = 'MISMATCH' } elseif (-not (Test-Path -LiteralPath $kitCt -PathType Container)) { $kitNo = 'NO_DIR' }
if ($kitNo -ceq '') {
    $kitOldTemp = $env:TEMP; $kitOldTmp = $env:TMP
    $env:TEMP = [string]$global:KitVal['container-temp']; $env:TMP = [string]$global:KitVal['container-temp']
    if (-not [string]::Equals([System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\'), $kitCt, [System.StringComparison]::OrdinalIgnoreCase)) { $env:TEMP = $kitOldTemp; $env:TMP = $kitOldTmp; $kitNo = 'VERIFY' }
}
if ($kitNo -ceq 'NO_DIR') { Write-Host 'a4 BASLAMADI: kapsayici Temp klasoru yok. VeraCrypt kapsayicisini baglayin, kagittaki madde 3 bloklarini tamamlayin, sonra yeniden a4 yazin. (Kayit yazilmadi; DUR kilidi yok.)'; return }
if ($kitNo -ceq 'ALREADY') { Write-Host 'a4 BASLAMADI: TEMP bu pencerede zaten degistirilmis. a9 yazin, pencereyi kapatin, kagittaki komutla yeniden acin; sonra a2, a3, a4. (Kayit yazilmadi; DUR kilidi yok.)'; return }
if ($kitNo -ceq 'VERIFY') { Write-Host 'a4 BASLAMADI: TEMP yonlendirmesi dogrulanamadi; eski TEMP/TMP geri kondu. a9 yazin, pencereyi kapatin; ajana ancak pencere kapandiktan sonra donun. (Kayit yazilmadi; DUR kilidi yok.)'; return }
if ($kitNo -cne '') { Write-Host "a4 BASLAMADI: sistem Temp kaydi yok veya uyusmuyor ($kitNo). a9 yazin, pencereyi kapatin; ajana ancak pencere kapandiktan sonra donun. (Kayit yazilmadi; DUR kilidi yok.)"; return }
if (-not (New-KitRecord $kitRec @(Get-KitHeader 'a4'))) { return }
Add-KitLine $kitRec 'SYSTEM_TEMP_MATCH=True'
Add-KitLine $kitRec 'KIT_TEMP_REDIRECT=True'
$kitTmp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
if ([string]::Equals($kitTmp, ([string]$global:KitVal['container-temp']).TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)) { Add-KitLine $kitRec 'KIT_TEMP_IN_CONTAINER=True' } else { Add-KitLine $kitRec 'STOP KIT_TEMP_IN_CONTAINER=False' }
Invoke-KitBlock $kitRec 'n003' @{ 'evidence-dir' = $global:KitEvid }
if (@(Read-KitRecord $kitRec | Where-Object { $_.StartsWith('OPTICAL_MEDIA_LOADED=True', [System.StringComparison]::Ordinal) }).Count -gt 0) { Add-KitLine $kitRec 'STOP KIT_OPTICAL_MEDIA_LOADED=True' }
$kitDef51 = Get-KitScript 'n051' $null ''
$kitDef14 = Get-KitScript 'n014' $null 'function Get-PilotBinManifestSha('
if (($null -eq $kitDef51) -or ($null -eq $kitDef14)) { Add-KitLine $kitRec 'STOP KIT_SCRIPT_LOAD=FAIL file=n051,n014' } else {
    . $kitDef51
    . $kitDef14
    Add-KitLine $kitRec 'KIT_DEFS=n051,n014:1'
    Invoke-KitBlock $kitRec 'n015' @{ 'evidence-dir' = $global:KitEvid; 'poppler-bin-dir' = $global:KitVal['poppler-bin-dir']; 'sevenzip-root' = $global:KitVal['sevenzip-root'] }
}
$null = Complete-KitStep $kitRec 'a4' @('SYSTEM_TEMP_MATCH=True', 'KIT_TEMP_REDIRECT=True', 'KIT_TEMP_IN_CONTAINER=True', 'OPTICAL_DRIVES_MATCH_RECORD=True', 'TOOL_MANIFEST_MATCH=True') 'a4 TAMAM. Dosyayi Farkli kaydet ile intake klasorune transfer.7z adiyla kaydedin, sonra a5 yazin.'
```

```powershell
# a5.ps1 - Ek R3: transfer.7z listeleme yontem kontrolu (N16, bekcili). ASCII. Yalniz a5 komutuyla calisir.
if (-not (Test-KitPass (Join-Path $global:KitE2Dir 'a4.txt') $true)) { Write-Host 'Once bu oturumda a4 TAMAM olmali.'; return }
$kitRec = Join-Path $global:KitE2Dir 'a5.txt'
if (-not (New-KitRecord $kitRec @(Get-KitHeader 'a5'))) { return }
Invoke-KitBlock $kitRec 'n016' @{ '7z' = $global:KitVal['7z']; 'intake-dir' = $global:KitVal['intake-dir'] }
$null = Complete-KitStep $kitRec 'a5' @('SEVENZIP_LIST_TIMEOUT=False', 'SEVENZIP_ALL_ENTRIES_7ZAES=True') 'a5 TAMAM. Simdi dosya avukatini arayin; parolayi YALNIZ kagida yazin ve geri okuyun. Sonra a6 yazin.'
```

```powershell
# a6.ps1 - Ek R3: geri okuma kaydi ve acma denemesi 1 (N17). ASCII. Yalniz a6 komutuyla calisir.
if (-not (Test-KitPass (Join-Path $global:KitE2Dir 'a5.txt') $true)) { Write-Host 'Once bu oturumda a5 TAMAM olmali.'; return }
if (Test-Path -LiteralPath (Join-Path $global:KitE2Dir 'a8.txt')) { Write-Host 'Parola kagidi imha edilmis; deneme yapilamaz.'; return }
$kitRb = Join-Path $global:KitE2Dir 'a6-readback.txt'
if (-not (Test-Path -LiteralPath $kitRb)) {
    if (-not (New-KitRecord $kitRb @(Get-KitHeader 'a6'))) { return }
    $kitAns = Read-KitYesNo 'Kagittan geri okuma tuttu mu? (Her karakter alfabede ve geri okumada ayni)'
    Add-KitLine $kitRb "HP_READBACK_AT=$(Get-KitNow)"
    if ($kitAns -ceq 'E') { Add-KitLine $kitRb 'HP_READBACK=ok' } elseif ($kitAns -ceq 'H') { Add-KitLine $kitRb 'STOP HP_READBACK=fail' } else { Add-KitLine $kitRb 'STOP HP_READBACK=invalid' }
    if (-not (Complete-KitStep $kitRb 'a6' @('HP_READBACK=ok') 'Geri okuma kaydedildi.')) { return }
} elseif (-not (Test-KitPass $kitRb $true)) { Write-KitDur 'a6' 'READBACK_RECORD_INVALID'; return }
Invoke-KitAttempt 1 'a6'
```

```powershell
# a7.ps1 - Ek R3: tek ek acma denemesi (N17, deneme 2). ASCII. Yalniz a7 komutuyla calisir.
$kitA6 = @(Read-KitRecord (Join-Path $global:KitE2Dir 'a6.txt'))
if (-not (($kitA6 -ccontains 'ATTEMPT_OUTCOME=RETRY_ALLOWED') -and ($kitA6 -ccontains 'STEP_RESULT=PASS') -and ($kitA6 -ccontains "KIT_SESSION=$($global:KitSess)"))) { Write-Host 'Ek deneme hakki yok (a6 bu oturumda RETRY_ALLOWED yazmadi).'; return }
if (Test-Path -LiteralPath (Join-Path $global:KitE2Dir 'a8.txt')) { Write-Host 'Parola kagidi imha edilmis; deneme yapilamaz.'; return }
Invoke-KitAttempt 2 'a7'
```

```powershell
# a8.ps1 - Ek R3: parola kagidi imha kaydi; gerekce kayitlardan turetilir. DUR kilidinde de calisir. ASCII.
if (-not (Test-KitPass (Join-Path $global:KitE2Dir 'a5.txt') $false)) { Write-Host 'a5 hic TAMAM olmadi; parola kagidi olusmadi. a8 kaydi gerekmez.'; return }
$kitRb = @(Read-KitRecord (Join-Path $global:KitE2Dir 'a6-readback.txt'))
$kitRec = Join-Path $global:KitE2Dir 'a8.txt'
if (Test-Path -LiteralPath $kitRec) { Write-Host 'a8 zaten kaydedildi.'; return }
if ((Read-KitYesNo 'Parola kagidini yirtarak imha ettiniz mi?') -cne 'E') { Write-Host 'Once kagidi yirtin, sonra yeniden a8 yazin. (Kayit yazilmadi.)'; return }
$kitWhy = 'stopped'
if ($kitRb.Count -eq 0) { $kitWhy = 'stopped' } elseif ($kitRb -cnotcontains 'HP_READBACK=ok') { $kitWhy = 'rejected' } else {
    $kitLast = Join-Path $global:KitE2Dir 'a7.txt'
    if (-not (Test-Path -LiteralPath $kitLast)) { $kitLast = Join-Path $global:KitE2Dir 'a6.txt' }
    $kitL = @(Read-KitRecord $kitLast)
    if (($kitL -ccontains 'ATTEMPT_OUTCOME=SUCCESS') -and ($kitL -ccontains 'STEP_RESULT=PASS')) { $kitWhy = 'used' }
}
if (New-KitRecord $kitRec (@(Get-KitHeader 'a8') + @("E2_PASSWORD_PAPER_DESTROYED=True at=$(Get-KitNow) reason=$kitWhy", 'STEP_RESULT=PASS', "ENDED_AT=$(Get-KitNow)"))) { Write-Host "a8 kaydedildi (reason=$kitWhy). Oturum sonunda a9 yazin." }
```

```powershell
# a9.ps1 - Ek R3: otomatik kapanis taramasi (N4). DUR kilidinde de calisir. ASCII. Yalniz a9 komutuyla calisir.
if (@(Read-KitRecord (Join-Path $global:KitSessDir 'a2.txt')).Count -eq 0) { Write-Host 'Bu oturumda a2 calismamis; a9 kaydi yok.'; return }
$kitRec = Join-Path $global:KitSessDir 'a9.txt'
if (-not (New-KitRecord $kitRec @(Get-KitHeader 'a9'))) { return }
Invoke-KitBlock $kitRec 'n004' $null
if (@(Read-KitRecord $kitRec) -ccontains 'AI_CHANNEL_PROCESS_COUNT=0') { Add-KitLine $kitRec 'CLOSING_SCAN_OK=True' } else { Add-KitLine $kitRec 'STOP CLOSING_SCAN_OK=False' }
$null = Complete-KitStep $kitRec 'a9' @('CLOSING_SCAN_OK=True') 'a9 TAMAM. Pencereyi kapatabilirsiniz.'
```

### Ek R3/5 Tek sayfalık adım listesi (şablon; K-R3-10)

Kâğıda basılır; ekranda açık tutulmaz. `<case-id>`, `<evidence-dir>` ve
`<intake-dir>` kit kurulumunda doldurulur (Ek R3/2 madde 9). Rehearsal'a özgü talimatlar
(ör. bilinçli hatalı parola) bu sayfaya değil, prova planına yazılır.

```text
İÇERİK PENCERESİ — ADIM LİSTESİ (tek sayfa; yazdırın, ekranda açık tutmayın)
Dosya: <case-id>     Tarih: ____________     Oturum (ekranda yazar): s__

0. ÖNCE KAPATIN (pencereden önce): önce VS Code'u tamamen kapatın (içindeki
   copilot-runtime onunla kapanır); sonra Claude Code, Claude masaüstü,
   ChatGPT, M365Copilot, OneDrive ("OneDrive'ı kapat"), başka her yapay
   zekâ, paylaşım veya eşitleme aracı. Kapanmayan varsa Görev Yöneticisi >
   Ayrıntılar'da YALNIZ şunları sonlandırın: Code, copilot-runtime, claude,
   ChatGPT, M365Copilot, OneDrive, OneDrive.Sync.Service (sonlarında .exe).
   Başka süreç sonlandırmayın. Harici diskleri çıkarın. Optik sürücü boş.
   (Bir kerelik bilgisayar hazırlığı pilottan önce yapılır: runbook §4.3 a.)
1. Win+R tuşlarına basın, kutuya aşağıdaki satırı AYNEN yazın, Enter:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -Command ". '<evidence-dir>\kit\ac.ps1'"
   Beklenen: "KIT YUKLENDI" (silme oturumunda ayrıca "SILME OTURUMU").
   Bir satır "DUR" ile BAŞLIYORSA: aşağıdaki DUR kuralı (a8/a9 burada yok).
2. a2 yazın, Enter.                      Beklenen: "a2 TAMAM".
3. 2 dakika bekleyin, a3 yazın.          Beklenen: "a3 TAMAM".
   "BEKLEYIN" yazarsa söylenen süre kadar bekleyip yeniden a3 yazın.
   Altı sınıf beyanını runbook §4.3 (a) Adım 2'deki gibi kayda yazın
   (altı satır ve AI_CONTENT_CHANNELS_CLOSED=True).
   Sonra runbook zincir adım 4'ün kalan bloklarını elle çalıştırın
   (kapsayıcı; teknik kayıt YALNIZ technical-record.txt yoksa, ilk içerik
   penceresinde; varsa atlayın; yol kapısı). Aktarım günü TEMP'i elle
   YÖNLENDİRMEYİN: a4 kendisi yapar. Aktarım günü değilse: runbook
   adımlarına devam edin (TEMP yönlendirmesi dahil); sonunda madde 10.
4. Aktarım günü: a4 yazın.               Beklenen: "a4 TAMAM".
   "a4 BASLAMADI" yazarsa ekrandaki talimatı uygulayın (kayıt yazılmadı).
   Sonra dosyayı tarayıcıda "Farklı kaydet" ile şu klasöre,
   transfer.7z adıyla kaydedin: <intake-dir>
5. a5 yazın.                             Beklenen: "a5 TAMAM".
   (En fazla 10 saniye sürer; hiçbir tuşa basmayın.)
6. Dosya avukatını arayın. Parolayı harf harf YALNIZ kâğıda yazın;
   her 4'lü grubu geri okuyun. Caps Lock'u AÇIN.
7. a6 yazın. "Geri okuma tuttu mu?" sorusuna E (evet) veya H (hayır).
   "Enter password" istemi görününce parolayı kâğıttan yazın, Enter.
   Ekranda 7z'nin "Enter password" istemi yoksa HİÇBİR ŞEY yazmayın
   ve Enter'a basmayın (kitin E/H soruları hariç: onlara yalnız E veya H).
   Sonra iki soruya E/H: istem göründü mü; "Wrong password" göründü mü.
   "CAPS LOCK KAPALI" yazarsa: Caps Lock'u açıp yeniden a6 (deneme harcanmaz).
8. Yalnız ekran "a7 yazin" derse: a7 (tek ek deneme; aynı kurallar).
9. Kâğıdı yırtın. a8 yazın, soruya E. Neden kendiliğinden yazılır.
10. Oturum sonunda HER ZAMAN: a9 yazın.  Beklenen: "a9 TAMAM". Pencereyi kapatın.

DUR KURALI — BİR SATIR "DUR" İLE BAŞLIYORSA: başka adım çalışmaz. Kâğıt varsa
yırtın ve a8 yazın. Sonra a9 yazın. Sonra pencereyi kapatın. Kiti yeniden
AÇMAYIN. Hiçbir yapay zekâ aracı veya sohbet AÇMAYIN. Ne olduğunu not
formuna yazın. Ajana ancak pencere kapandıktan sonra dönün.
SİLME OTURUMU (yalnız ajan, pencere kapandıktan sonra, yazılı olarak
söylerse): madde 0–3 aynı; ekran "SILME OTURUMU" der; silme günü değilse
a2 yazmadan pencereyi kapatın; a4–a7 çalışmaz; runbook §25.2/§28
adımları; sonunda madde 10. Pencere açıkken hiçbir sohbet, yardım sayfası
veya yapay zekâ aracı açılmaz (runbook, yapay zekâ özelliği olmayan yerel
bir görüntüleyicide açık olabilir). Pencereye fare ile tıklamayın;
başlıkta "Seç" görürseniz Esc. Ekranı hiçbir yere yapıştırmayın,
fotoğraflamayın. Parola yalnız 7z'nin "Enter password" istemine yazılır.

ALFABE (29 sembol): A Adana  B Bolu  C Ceyhan  D Denizli  E Edirne  F Fatsa
G Giresun  H Hatay  J Jandarma  K Kars  L Lüleburgaz  M Muş  N Niğde
P Polatlı  R Rize  S Sinop  T Tokat  U Uşak  V Van  Y Yozgat  Z Zonguldak
2 iki  3 üç  4 dört  5 beş  6 altı  7 yedi  8 sekiz  9 dokuz
```

### Ek R3/6 Not formu (şablon; revizyon 5; kullanıcı kararı D4)

YENİ (revizyon 5; §34.11). Tek sayfayla (N114) birlikte, boş olarak
kâğıda basılır (Ek R3/2 madde 9). Pencere içinde yalnız kalemle ve kısa
kodlarla doldurulur: her kutuya `E` veya `H`; istenen yerde madde
numarası, saat (`SS:DD`) ve tek kelime. Forma parola, parolanın bir
karakteri, dosya içeriği, kişi/kurum adı, kimlik veya vergi numarası,
dosya yolu ya da ekrandaki metin **yazılmaz**. Kitin mekanik olarak
ölçtüğü şeyler (adım sonuçları, tarama sayıları ve saatleri, parola
isteminin ve `Wrong password` yazısının görülmesi, Caps Lock, 7z sonucu,
listeleme süresi) formda sorulmaz. Form kâğıtta kalır; kodlar pencere
kapandıktan **sonra** ajan oturumuna bildirilir ve kayda yalnız bu kodlar
beyan olarak geçer (§32/39 f emsali). Doldurulmamış bir form "takılma
yok" beyanı **değildir**; değeri bilinmiyordur (N/A). Provaya özgü
sorular bu şablona değil, prova planına yazılır.

```text
NOT FORMU — kalemle, kısa kodla. Parola, karakteri, içerik, ad, numara, yol YAZMAYIN.
Tarih: ________  Oturum: s__   Kutuya E/H; gerekirse: madde no, saat SS:DD, tek kelime
K1 [ ] Madde 0'daki kapatmayı kâğıttan, yardımsız yaptım ..... H ise: ___ __:__ _____
K2 [ ] Bir maddede takıldım .................................. E ise: ___ __:__ _____
K3 [ ] Ekranda DUR gördüm .................................... E ise: ___ __:__ _____
K4 [ ] DUR'dan sonra a9 yazdım ve pencereyi kapattım (DUR yoksa boş bırakın)
K5 [ ] Pencere açıkken bir sohbet veya yapay zekâ aracı açıldı E ise: ___ __:__ _____
K6 [ ] Ekran bir yere yapıştırıldı veya fotoğraflandı ......... E ise: ___ __:__ _____
K7 [ ] Bir şey yanlış pencereye veya Not Defteri'ne yazıldı ... E ise: ___ __:__ _____
K8 [ ] Planlı parola okuması dışında dış yardım gerekti ...... E ise: ___ __:__ _____
K9 [ ] Win+R satırını kopyaladım (H: elle yazdım)
```

### Ek R3/7 Değişken adı çakışma denetimi (kurulum; pinli; revizyon 5; kullanıcı kararı D5)

YENİ (revizyon 5; §34.11). Ek R3/2 madde 7'de kurulum ajanı bu bloğu
kullanır. Blok bir kit dosyası **değildir** ve `<evidence-dir>\kit\`'e
kopyalanmaz (N105'in 19 dosya denetimi değişmez). Ajan bloğun gövdesini
(çit satırları hariç, LF ile birleştirilmiş, sonda LF; yer tutucu yoktur)
kendi oturum geçici dizinine — `<evidence-dir>`, kapsayıcı ve repo
dışında — CreateNew ile `kvc.ps1` adıyla yazar, SHA-256'sının §34.11
tablosundaki N116 değerine eşit olduğunu doğrular ve yeni bir
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File` alt sürecinde,
`-ScanKitDir` değeri `<evidence-dir>\kit` olarak çalıştırır. Blok kit
dosyalarını yalnız okur ve `Parser.ParseFile` ile ayrıştırır; hiçbir kit
kodu çalıştırmaz. Kural (mekanik):

1. **Kapsam.** Her dosyanın üst düzeyi ve her fonksiyon gövdesi
   (parametreleri dahil) ayrı bir kapsamdır; `ForEach-Object` /
   `Where-Object` gibi betik blokları bulundukları kapsama katılır (geniş
   yorum). Dot-source ilişkileri birleştirilir: `ac.ps1` üst düzeyi genel
   kapsamdır (`GLOBAL`; Ek R3/3) ve her `$global:<ad>` başvurusu da
   `GLOBAL`'a sayılır; `a4.ps1` üst düzeyi ile `n051.ps1` ve `n014.ps1`
   üst düzeyleri tek kapsamdır (N108 ikisini dot-source eder).
2. **Ad kaynakları.** Her değişken başvurusu (atama, okuma, parametre,
   döngü değişkeni) ve `Remove-`/`Clear-`/`Set-`/`New-`/`Get-Variable`
   (ve kısa adları) ile adı verilen her ad. Sürücü nitelikli adlar
   (`$env:` gibi) ve bloktaki sabit listede adı geçen otomatik
   değişkenler (`$_`, `$null`, `$true`, `$false`, `$args`,
   `$PSScriptRoot`, `$LASTEXITCODE`, `$Matches` …) sayılmaz. Bir
   değişken cmdlet'inin çözümlenemeyen biçimi `STOP
   KIT_VAR_CMD_UNPARSED`'dır.
3. **Çakışma.** (a) Aynı kapsamda yalnız büyük-küçük harfle ayrılan iki
   yazım (`KIT_VAR_COLLISION kind=SAME_SCOPE_CASE`); (b) herhangi bir
   kapsamda nitelendirilmemiş bir adın bir `$global:` adıyla büyük-küçük
   harf duyarsız eşitliği (`kind=GLOBAL_NAME`; revizyon 4'ün hata
   sınıfı, §34.10). Farklı kapsamlardaki yazım çiftleri çakışma değildir;
   `KIT_VAR_CROSS_SCOPE_CASE_PAIR` satırlarıyla yalnız bilgi olarak
   listelenir.
4. **Sonuç.** 17 dosyanın hepsi ayrıştırılmış
   (`KIT_VAR_SCAN_FILE_COUNT=17`) ve çakışma yoksa `KIT_VAR_COLLISIONS=0`;
   aksi hâlde `STOP KIT_VAR_COLLISIONS=<n>` (veya `STOP
   KIT_VAR_PARSE_ERRORS`, `STOP KIT_VAR_SCAN_FILE_MISSING`, `STOP
   KIT_VAR_SCAN_FILE_COUNT`, `STOP KIT_VAR_CMD_UNPARSED`, `STOP
   KIT_VAR_SCAN=EXCEPTION`) ve kit kullanılmaz: **DUR**. Çıktı yalnız
   durum satırıdır; değişken adları dışında bir şey taşımaz.

Sınır: denetim statiktir; çalışma anındaki ilişkilerden yalnız yukarıda
adlandırılan dot-source birleşimleri modellenir; `& $sb` ile çalışan bir
betiğin çağıranın yerel değişkenlerini dinamik olarak okuması denetlenmez
(§32/39 i). Ayrıca modellenmeyen iki sınıf (revizyon 5 düzeltme turu;
bağımsız inceleme L5): (a) kit penceresinin genel kapsamında elle
çalıştırılan madde 3 blokları (zincir adım 4'ün kalan blokları, §13.8,
altı sınıf beyanı) taranmaz — revizyon 3'ün hatası tam bu kapsamdaydı;
(b) kapsam belirtilmeden çağrılan `Remove-Variable`'ın, ad yerel
kapsamda yoksa üst kapsamdaki aynı adlı değişkeni silebilmesi
modellenmez (PowerShell davranışı; statik çıkarım, ölçülmedi); ad bir
`$global:` adıyla eşleşiyorsa yalnız `GLOBAL_NAME` kuralı yakalar.
Bağımsız incelemenin bu
revizyondaki statik ölçümünde ikisinde de çakışma yoktu.

```powershell
# kvc.ps1 - Ek R3/7: kit degisken adi cakisma denetimi (AST; runbook revizyon 5). ASCII. Kit dizinine kopyalanmaz; dosyalari yalniz okur.
param([string]$ScanKitDir)
$scanCount = 0; $scanStop = 0
try {
    $scanNames = @('ac.ps1', 'a2.ps1', 'a3.ps1', 'a4.ps1', 'a5.ps1', 'a6.ps1', 'a7.ps1', 'a8.ps1', 'a9.ps1', 'n003.ps1', 'n004.ps1', 'n006.ps1', 'n014.ps1', 'n015.ps1', 'n016.ps1', 'n017.ps1', 'n051.ps1')
    $scanRootScope = New-Object System.Collections.Hashtable ([System.StringComparer]::Ordinal)
    $scanRootScope['ac.ps1'] = 'GLOBAL'
    foreach ($scanF in @('a4.ps1', 'n051.ps1', 'n014.ps1')) { $scanRootScope[$scanF] = 'a4.ps1+n051.ps1+n014.ps1:root' }
    $scanAuto = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($scanA in @('_', 'PSItem', 'null', 'true', 'false', 'args', 'input', 'this', 'PSScriptRoot', 'PSCommandPath', 'LASTEXITCODE', 'Error', 'Host', 'PID', 'Matches', 'foreach', 'switch', 'MyInvocation', 'PSBoundParameters', 'ExecutionContext', 'HOME', 'PWD', 'ErrorActionPreference')) { $null = $scanAuto.Add($scanA) }
    $scanVarCmds = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($scanA in @('Remove-Variable', 'Clear-Variable', 'Set-Variable', 'New-Variable', 'Get-Variable', 'rv', 'clv', 'sv', 'nv', 'gv')) { $null = $scanVarCmds.Add($scanA) }
    $scanValParams = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($scanA in @('Scope', 'Value', 'Include', 'Exclude', 'Option', 'Description', 'Visibility', 'ErrorAction', 'ErrorVariable', 'WarningAction', 'WarningVariable', 'InformationAction', 'InformationVariable', 'OutVariable', 'OutBuffer', 'PipelineVariable')) { $null = $scanValParams.Add($scanA) }
    $scanSwitches = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($scanA in @('Force', 'PassThru', 'ValueOnly', 'WhatIf', 'Confirm', 'Verbose', 'Debug')) { $null = $scanSwitches.Add($scanA) }
    $scanRefs = New-Object System.Collections.ArrayList
    $scanOnDisk = @(Get-ChildItem -LiteralPath $ScanKitDir -Force -File -ErrorAction Stop | Where-Object { $_.Extension -ceq '.ps1' } | ForEach-Object { $_.Name })
    foreach ($scanF in $scanNames) { if ($scanOnDisk -cnotcontains $scanF) { "STOP KIT_VAR_SCAN_FILE_MISSING=$scanF"; $scanStop++ } }
    if ($scanOnDisk.Count -ne $scanNames.Count) { "STOP KIT_VAR_SCAN_FILE_COUNT=$($scanOnDisk.Count)"; $scanStop++ }
    foreach ($scanF in $scanNames) {
        if ($scanOnDisk -cnotcontains $scanF) { continue }
        $scanTok = $null; $scanErr = $null
        $scanAst = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $ScanKitDir $scanF), [ref]$scanTok, [ref]$scanErr)
        if (@($scanErr).Count -gt 0) { "STOP KIT_VAR_PARSE_ERRORS=$(@($scanErr).Count) file=$scanF"; $scanStop++; continue }
        $scanCount++
        $scanRoot = $scanF + ':root'
        if ($scanRootScope.ContainsKey($scanF)) { $scanRoot = [string]$scanRootScope[$scanF] }
        $scanScopeOf = {
            param($scanNode)
            $scanUp = $scanNode.Parent
            while ($null -ne $scanUp) {
                if ($scanUp -is [System.Management.Automation.Language.FunctionDefinitionAst]) { return ($scanF + ':' + $scanUp.Name + '@' + $scanUp.Extent.StartLineNumber) }
                $scanUp = $scanUp.Parent
            }
            return $scanRoot
        }
        foreach ($scanV in $scanAst.FindAll({ param($scanN) $scanN -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)) {
            $scanP = $scanV.VariablePath
            if ($scanP.IsDriveQualified) { continue }
            $scanName = $scanP.UserPath
            $scanColon = $scanName.IndexOf(':')
            if ($scanColon -ge 0) { $scanName = $scanName.Substring($scanColon + 1) }
            if ($scanAuto.Contains($scanName)) { continue }
            if ($scanP.IsGlobal) { $null = $scanRefs.Add(@('GLOBAL', $scanName, $true)) } else { $null = $scanRefs.Add(@((& $scanScopeOf $scanV), $scanName, $false)) }
        }
        foreach ($scanC in $scanAst.FindAll({ param($scanN) $scanN -is [System.Management.Automation.Language.CommandAst] }, $true)) {
            $scanCn = $scanC.GetCommandName()
            if (($null -eq $scanCn) -or (-not $scanVarCmds.Contains($scanCn))) { continue }
            $scanScope = & $scanScopeOf $scanC
            $scanEls = @($scanC.CommandElements)
            $scanPos = 0; $scanNameEls = @(); $scanBad = $false
            for ($scanI = 1; $scanI -lt $scanEls.Count; $scanI++) {
                $scanE = $scanEls[$scanI]
                if ($scanE -is [System.Management.Automation.Language.CommandParameterAst]) {
                    $scanPn = $scanE.ParameterName
                    if ([string]::Equals($scanPn, 'Name', [System.StringComparison]::OrdinalIgnoreCase)) {
                        if ($null -ne $scanE.Argument) { $scanNameEls += $scanE.Argument } else { $scanI++; if ($scanI -lt $scanEls.Count) { $scanNameEls += $scanEls[$scanI] } else { $scanBad = $true } }
                    } elseif ($scanValParams.Contains($scanPn)) {
                        if ($null -eq $scanE.Argument) { $scanI++ }
                    } elseif (-not $scanSwitches.Contains($scanPn)) { $scanBad = $true }
                } else {
                    if ($scanPos -eq 0) { $scanNameEls += $scanE }
                    $scanPos++
                }
            }
            foreach ($scanE in $scanNameEls) {
                $scanItems = @($scanE)
                if ($scanE -is [System.Management.Automation.Language.ArrayLiteralAst]) { $scanItems = @($scanE.Elements) }
                foreach ($scanX in $scanItems) {
                    if ($scanX -is [System.Management.Automation.Language.StringConstantExpressionAst]) { $null = $scanRefs.Add(@($scanScope, [string]$scanX.Value, $false)) } else { $scanBad = $true }
                }
            }
            if ($scanBad) { "STOP KIT_VAR_CMD_UNPARSED file=$scanF line=$($scanC.Extent.StartLineNumber)"; $scanStop++ }
        }
    }
    $scanGlobals = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $scanSame = New-Object System.Collections.Hashtable ([System.StringComparer]::Ordinal)
    $scanAll = New-Object System.Collections.Hashtable ([System.StringComparer]::Ordinal)
    foreach ($scanR in $scanRefs) {
        if ($scanR[2]) { $null = $scanGlobals.Add([string]$scanR[1]) }
        $scanLow = ([string]$scanR[1]).ToLowerInvariant()
        $scanK = [string]$scanR[0] + "`t" + $scanLow
        if (-not $scanSame.ContainsKey($scanK)) { $scanSame[$scanK] = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal) }
        $null = $scanSame[$scanK].Add([string]$scanR[1])
        if (-not $scanAll.ContainsKey($scanLow)) { $scanAll[$scanLow] = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal) }
        $null = $scanAll[$scanLow].Add([string]$scanR[1])
    }
    $scanColl = 0
    $scanSameLow = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $scanKeys = [string[]]@($scanSame.Keys); [Array]::Sort($scanKeys, [System.StringComparer]::Ordinal)
    foreach ($scanK in $scanKeys) {
        $scanSp = [string[]]@($scanSame[$scanK]); [Array]::Sort($scanSp, [System.StringComparer]::Ordinal)
        $scanParts = $scanK.Split([char]9)
        if ($scanSp.Count -gt 1) { $scanColl++; $null = $scanSameLow.Add($scanParts[1]); "KIT_VAR_COLLISION kind=SAME_SCOPE_CASE scope=$($scanParts[0]) names=$($scanSp -join '|')" }
    }
    $scanGlobalHit = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($scanR in $scanRefs) {
        if ((-not $scanR[2]) -and $scanGlobals.Contains([string]$scanR[1])) { $scanK = [string]$scanR[0] + "`t" + [string]$scanR[1]; if ($scanGlobalHit.Add($scanK)) { $scanColl++; "KIT_VAR_COLLISION kind=GLOBAL_NAME scope=$($scanR[0]) name=$($scanR[1])" } }
    }
    $scanInfo = 0
    $scanKeys = [string[]]@($scanAll.Keys); [Array]::Sort($scanKeys, [System.StringComparer]::Ordinal)
    foreach ($scanK in $scanKeys) {
        if (($scanAll[$scanK].Count -gt 1) -and (-not $scanSameLow.Contains($scanK))) { $scanSp = [string[]]@($scanAll[$scanK]); [Array]::Sort($scanSp, [System.StringComparer]::Ordinal); $scanInfo++; "KIT_VAR_CROSS_SCOPE_CASE_PAIR names=$($scanSp -join '|')" }
    }
    "KIT_VAR_SCAN_FILE_COUNT=$scanCount"
    "KIT_VAR_GLOBAL_NAME_COUNT=$($scanGlobals.Count)"
    "KIT_VAR_CROSS_SCOPE_CASE_PAIR_COUNT=$scanInfo"
    if (($scanColl -eq 0) -and ($scanStop -eq 0) -and ($scanCount -eq $scanNames.Count)) { 'KIT_VAR_COLLISIONS=0' } else { "STOP KIT_VAR_COLLISIONS=$scanColl" }
} catch { 'STOP KIT_VAR_SCAN=EXCEPTION' }
```
