# Pilot Readiness Step 9 — Synthetic Concierge Dry Run and Deadline Report Lock

**DONE / LOCKED FOR CURRENT PILOT.** Bu dosya tarihsel kanıttır, canlı politika
değildir. Canlı kurallar yalnız `CLAUDE.md` §1–§13'tedir.

**Redaksiyon sözleşmesi (bağlayıcı).** Bu belge gerçek port, gerçek veritabanı
adı, Windows kullanıcı adı veya mutlak yerel yol, DSN, parola, passfile yolu
veya içeriği, API anahtarı (öneki dahil), Console hesap/workspace adı, taraf
adı, kimlik/vergi numarası, e-posta, numeric IAM kullanıcı id'si, süreç id'si,
tam attestation ref'i, istek/yanıt gövdesi veya sentetik düz-değer dosyasının
içeriğini **içermez**. Yer tutucular: `«PORT»`, `«PILOT_DB»`, `«PASSFILE»`,
`«EVIDENCE_DIR»`, `«RUNTIME_DIR»`, `«SYNTHETIC_CASE»`, `«SYNTHETIC_DOCUMENT»`.
IAM kullanıcıları **"ilk admin"** ve **"avukat kullanıcısı"** olarak anılır.
Commit SHA'ları, artefakt SHA-256 değerleri, test sayaçları, sentetik tarihler
ve hesaplanan deadline gerçektir.

---

## A. Status, scope, and evidence boundary

| Kalem | Durum |
|---|---|
| **Pilot Readiness Adım 9** | **DONE / LOCKED FOR CURRENT PILOT** |
| Sıradaki iş | **Adım 10 — ACTIVE / NEXT** |
| Web login | Adım 11'in gerçek Entra tenant/app kaydını bekler |
| Row 19D ve Adım 10–13 | **Açık** |
| Pilot production-ready mi? | **HAYIR — iddia edilmez** |

Bu kapanış, Adım 8 pointer'ındaki "**Adım 9 — ACTIVE / NEXT**" ifadesini
SUPERSEDE eder; o ifade kendi LOCK anının tarihsel kaydı olarak değiştirilmeden
bırakılmıştır.

Kapsam: Adım 9, concierge pilot operasyon zincirinin **tamamen sentetik** tek
bir dosya (`«SYNTHETIC_CASE»` / `«SYNTHETIC_DOCUMENT»`) üzerinde, uçtan uca ve
gerçek kalıcı yerel PostgreSQL/IAM altyapısıyla yürütülebildiğini kanıtlar:
offline runtime → egress denetimi → **tek kontrollü gerçek model çağrısı** →
fact extraction/inceleme/promotion/verification → timeline → deadline →
salt-okunur avukat raporu. Zincirin her canonical adımında **insan/avukat
onayı zorunludur**; hiçbir model çıktısı onaysız canonical olmamıştır.

"Dry run" ifadesi burada **sentetik, production-dışı pilot kapsamını** anlatır;
**ağsız yürütme anlamına gelmez**. Adım 9'da dış HTTP istekleri yapıldı:
iki single-send POST denemesi kimlik doğrulama aşamasında **401** ile
reddedildi; üç yalnız-auth `GET /v1/models` probe isteği sırasıyla **401**,
**400** ve **200** döndü; final single-send POST **200** ile başarılı oldu.
Model mesajı ve token kullanımı **yalnız** bu final başarılı POST'tan üretildi.
Başarısız POST denemeleri dosya veya DB deltası üretmedi; yalnız-auth probe'lar
pilot DB'ye veya fixture'a bağlanmadı.

Kanıt sınırı: repo dışındaki evidence (`«EVIDENCE_DIR»`) bu dosyada **özet**
olarak aktarılır; hiçbir secret, credential veya gerçek kişi/müvekkil verisi bu
belgeye taşınmamıştır. Gönderilen tek veri sentetik fixture'dır.

---

## B. Committed implementation lineage

| # | Commit | Kapsam | Rol |
|---|---|---|---|
| 1 | `50bba3768f8c38b9aad56154d5ae9ee21103b5f9` | **3 YENİ** (`ui/deadline_report.py`, `ui/tests/test_deadline_report_isolated.py`, `ui/tests/test_deadline_report_integration_postgres.py`) | Fail-closed, salt-okunur avukat deadline report CLI'ı ve iki testi |
| 2 | `bcf2842061740021ed457d74704da07230b2eec9` | **2 DEĞİŞTİRİLMİŞ** (`ui/services/fact_verification_mutation_facade.py`, `ui/tests/test_fact_verification_mutation_facade_isolated.py`) | Remediation A — fact verification downstream rerun sırası |
| 3 | `940c26bfba0f701e312318b7e8ce5fc50166f5ae` | **4 DEĞİŞTİRİLMİŞ** (`src/llm_privacy_boundary.py`, `src/fact_extraction_engine.py`, `ui/tests/test_llm_privacy_boundary_isolated.py`, `ui/tests/test_fact_extraction_engine_isolated.py`) | Remediation B — token taşıyan warnings/notes redaksiyonu + masking v5 |

Üç commit de `claude-dev` üzerinde normal fast-forward ile yayımlandı. Adım 9'un
operasyonel işi (runtime kurulumu, harness, gönderim, onaylar, cleanup) repo
dosyası **değiştirmeden** yürütüldü; repo değişiklikleri yalnız bu üç commit'tir.

---

## C. Step 9A offline concierge runtime

- **41 wheel**, manifest kapanışı **41/41**.
- Kurulum **offline**: `pip install --no-index --no-deps`, yalnız yerel wheel
  dizininden.
- `pip check` **PASS** ("No broken requirements found").
- Manifestteki **41 wheel** offline kuruldu. `pip freeze --all` toplam **42
  satır** verdi: 41 manifest paketi + runtime ile gelen `pip`. Beklenen
  normalize paket kümesiyle fark **0**.
- Ağ yalnız **izin verilen wheel indirme aşamasında** kullanıldı; kurulum ve
  sonrası offline'dır.
- Kurulum sırasında gözlenen yerel `::1:0` bind olayı, deterministik offline
  replay ile açıklandı (dış bağlantı değil; offline wrapper sayaçları
  `getaddrinfo=0 connect=0 other_net=0`).
- Runtime repo **dışındadır** (`«RUNTIME_DIR»`); repo ve root `.venv`
  **değiştirilmedi**.
- Wheel'ler ve runtime, LOCK tamamlanana kadar korunur.

---

## D. Egress harness, monitor, and authentication evidence

- İlk egress harness incelemesi bir **redirect bypass** bulgusu üretti; harness
  redirect ve proxy yolları için düzeltildi (redirect ve proxy fail-closed
  reddedilir). Düzeltilmiş harness'in bağımsız incelemesi **READY** verdi.
- Dış katmanda ayrı bir **outer egress monitor** çalıştı; sınırı: Python audit
  hook tabanlıdır, **C seviyesindeki ağ davranışları için tam bir OS sandbox'ı
  değildir**.
- Auth probe'lar, yalnız kimlik doğrulamayı sınayan **gerçek dış HTTP `GET
  /v1/models`** istekleridir (model çıkarımı değildir): **V1** → 401, **V2** →
  400, **V3** → 200 / **`AUTH_VALID`**. Her biri tek denemedir; yanıt gövdesi
  yazılmadı.
- Probe'lar production inference değildir; pilot DB'ye veya fixture'a
  bağlanmadılar ve **DB/fixture mutasyonu yapmadılar**.
- Credential değeri **hiçbir** evidence dosyasına, log'a veya bu belgeye
  yazılmadı.
- Proxy, redirect ve retry kapıları fail-closed'dur.

---

## E. Masked single-send execution

Başarılı operatör koşusunun etiketi **"single-send capsule V5"**'tir. Bu etiket
yalnız kapsülün beşinci sürümünü adlandırır ve **masking policy v5 ile aynı
şey DEĞİLDİR**: gerçek çağrı, o tarihte yürürlükte olan **masking policy v4**
(`tr_pseudonymisation_v4`) altında yapıldı. Masking v5 bu çağrıdan **sonra**
Remediation B ile geldi (bkz. §I).

| Ölçüt | Değer |
|---|---|
| Model | `claude-sonnet-4-6` |
| POST sayısı | **1** |
| Redirect | 0 |
| Retry | 0 |
| Denied egress event | 0 |
| Başka dış hedef | 0 |
| İstekteki maskeleme token'ı | **5** |
| Yanıtta bilinmeyen token | **0** (yanıt token'ları istek token'larının alt kümesi) |
| Input token | 4323 |
| Output token | 4097 |
| HTTP durumu | 200 |

Yalnız sentetik fixture gönderildi; gerçek kişi veya müvekkil verisi
gönderilmedi. Model yanıtı validator'dan geçti. İstek ve yanıt gövdeleri bu
belgeye **konmamıştır**.

---

## F. Fact extraction, review, promotion, and verification

- Model yanıtından **9 fact** üretildi; hepsi başlangıçta `unverified`.
- İnsan incelemesi: **9 ACCEPT, 0 CORRECT, 0 REJECT**.
- Pending → canonical fact promotion koordineli yoldan (journal) yapıldı.
- Fact Verification Workflow ile **yalnız tebliğ (notification-date) fact'i**
  `verified` yapıldı; sentetik tebliğ tarihi **`2026-03-16`**.
- Diğer **sekiz fact `unverified`** kaldı.
- Fact validator: **0 error / 0 warning**.
- Pending, canonical, approval ve verification audit dosyalarının hash bağları
  doğrulandı (pending → promotion → verification zinciri; her audit kaydındaki
  hash'ler mevcut dosyalara bağlanır).
- Ham sentetik kimlik veya iletişim değerleri bu belgeye yazılmadı.

---

## G. Timeline and deadline chain

- Canonical timeline **iki olay** içerir; deadline açısından ilgili tek
  verified olay tebliğ tarihidir.
- Anchor: sentetik tebliğ olayı (`2026-03-16`).
- Kural: İYUK genel vergi mahkemesi dava açma süresi — **30 takvim günü**,
  ertesi günden sayım.
- Hesaplanan son gün: **`2026-04-15`**; son gün iş günüdür, ek kaydırma yoktur.
- Adli tatil uygulanabilirlik bayrağı `true`'dur ancak bu tarihe **etkisi
  yoktur**.
- `stopping_event_status = none`; geçerli bir sentetik attestation ref'i
  mevcuttur (exact ref metni yazılmaz).
- Deadline validator: **0 error / 0 warning**.
- `requires_human_review = true`; `expiry_state = not_evaluated`.

---

## H. Read-only lawyer deadline report

- Araç: `ui.deadline_report` (commit `50bba37`).
- Aktör, aktif ve case'e **atanmış avukat kullanıcısı** iken çalıştırıldı.
- Transaction **read-only**; yalnız `SELECT`.
- Tam olarak bir approval audit kaydı ile bir `completed` journal satırı
  eşleştirildi.
- Çıktı yalnız allowlist'teki alanları içerdi; taraf adı, kimlik, vergi
  numarası, e-posta, `notes`, `warnings`, audit metni veya display name
  **sızmadı**.
- Rapor son günü `2026-04-15` olarak gösterdi; "süre aşımı değerlendirilmedi"
  ve "hukuki karar değildir" sınırlarını açıkça taşıdı.
- Exit kodu **0**.
- Canonical deadline SHA-256:
  `90f286a4150639e959d5ab3b95ed69ea3a14463e8846b155e38e6de78153f3b9`
- 15 satırlık canonical render SHA-256:
  `e9e2c25976167e67c320afba0fccbcf0fbec72f54d378c08f28b76a7c111cd52`

---

## I. Remediation A and B

**Remediation A** (commit `bcf2842`):

- Fact verification sonrası operatöre basılan downstream rehberindeki eski
  `NO_COORDINATED_PATH: qa case_view` bilgisi kaldırıldı.
- `qa` ve `case_view` için generation/approval adımları eklendi; rerun sırası
  **22 adım / 11 aile** (timeline ailesi generation → promotion).
- `NO_COORDINATED_PATH: none`.
- DB, journal, yetkilendirme veya dosya yazma yollarına etkisi yoktur.
- Bağımsız inceleme: **READY**.

**Remediation B** (commit `940c26b`):

- Top-level `warnings` ve fact düzeyi `notes` içinde maskeleme token'ı taşıyan
  serbest metin, geri çevrilmeden **önce tamamen redakte** edilir.
- Warning sayısı, yalnız redakte edilenler arasında artan deterministik sıra
  numarasıyla (`[REDAKTE #n] …`) korunur; aynı içerikli uyarılar birleşmez.
- P/T/V/B/F/E sınıflarının tamamı kapsanır; mevcut bilinmeyen/bozuk token
  fail-closed davranışı gevşetilmedi (redaksiyondan önce bütünlük doğrulaması).
- `statement`, `normalized_statement`, `text_excerpt` ve `structured_values`
  redakte edilmez, geri-maskelenmeye devam eder.
- Masking policy **`tr_pseudonymisation_v5`**.
- Politika **forward-only**; geçmiş v4 artefaktları backfill edilmedi. Adım 9
  final snapshot'ı v4 zamanında üretilmiş, tamamen sentetik artefaktları
  içerir.
- Bağımsız inceleme: **READY** (0 Critical / 0 High / 0 Medium).
- Low sınır: hem token hem `ignored_phrases` ifadesi içeren bir uyarı, artık
  sessizce silinmek yerine redaksiyon marker'ı olarak kalır.

---

## J. Formal post-commit gates

Her iki kapı da commit'li baytlar üzerinde, temiz bir detached worktree'de
çalıştırıldı.

**Gate A — `production-parity`:**

| Ölçüt | Değer |
|---|---|
| Test edilen HEAD | `940c26b` |
| Etiket | `FULL` |
| Modül | **86/86 PASS** |
| Passed / failed | **7192 / 0** |
| Counted skip / informational skip | 8 / 14 |
| PostgreSQL modülleri | **17/17 PASS** |
| Protected manifest | 397 giriş, temiz |
| Secret scan | 172 dosya, 0 eşleşme |
| Guard | 229/229 armed; positive controls 10/10 |
| PostgreSQL | Yeni, disposable, yalnız loopback küme; kalıcı pilot kümesi **hedeflenmedi** |
| Rapor SHA-256 | `30c69c76bc121057e1ebe5dfa794c3294f7dfe1ab367da3317fb5e5c40e4ce06` |

**Gate B — `rag-dependency`:**

| Ölçüt | Değer |
|---|---|
| Test edilen HEAD | `940c26b` |
| Etiket | `RAG_GATE_PASS` |
| Modül | **3/3 PASS** |
| Passed / failed | **216 / 0** |
| Rapor SHA-256 | `552d972bdad8afc26ab2635440ee3bf6f65bae4111bc56b9d3fc691bb1883d72` |

Runner'ın önceden belgelenmiş beş deviation'ı, skip profili (modül bazında) ve
Gate B'deki K.1 adlı win32 informational skip muafiyeti, önceki başarılı
kapılarla **birebir aynıdır**; yeni bir hata değildir. Gate A'daki +90 passed
farkının tamamı üç remediation test modülünden gelir.

---

## K. Cleanup, revocation, and retained audit

- Sentetik avukat assignment'ı, canonical IAM CLI (`scripts.iam_admin
  revoke-assignment`, `vergi_iam_admin` rolüyle) üzerinden **tam bir kez**
  revoke edildi; aktör **ilk admin**, hedef **avukat kullanıcısı**. Exit 0,
  stdout `OK`.
- Bir `case_assignment_revoked` security event'i oluştu; grant ve revoke audit
  izleri korunur.
- Adım 9'un **yedi mutation journal satırı** (`completed`) ve case mutation
  resource satırı **korunur**; journal veya resource silinmedi, düzeltici SQL
  çalıştırılmadı.
- Revoke komutu **ikinci kez çalıştırılmadı**.
- **Bilinen sınır:** mevcut revoke CLI idempotent değildir; zaten revoke
  edilmiş bir assignment üzerinde tekrar çalıştırılırsa `role` alanı boş,
  sahte bir revoke event'i yazıp yine başarı döner. Bu nedenle tek-çalıştırma
  operasyon kuralı uygulanmıştır. Bu bir production-ready iddiası değildir.
- Final snapshot, 17 fixture dosyasını **17/17** yol + bayt + SHA-256
  paritesiyle korur. Kontrol dosyaları:

| Dosya | SHA-256 |
|---|---|
| `manifest.tsv` | `0c05002fb87690728fee2263f657684d74b626f2e10894396b6eb89c4b4a6b79` |
| `db_closing_snapshot.json` | `078e41a0c03345b9c0f36895530daff9b7ada98d4fa181b75b9ec3437b45d637` |
| `repo_and_gates.txt` | `d48d3020e129add6d47872a62ca228b9bd7d6eb7bb013b486bb710a9d5bd745a` |

- Snapshot repo **dışındadır**.
- Ignored sentetik fixture, snapshot paritesi doğrulandıktan sonra exact yoldan
  kaldırıldı; `data/cases` altında yalnız tracked `case_0001` kaldı (**71/71**
  HEAD paritesi).
- Repo temiz kaldı; DB audit izleri snapshot sonrasında değişmedi (fixture
  silme DB'de sıfır değişiklik üretti).

---

## L. Honest boundaries and next step

1. Kanıt **yalnız sentetik** bir dosya üzerindeki operasyon zinciridir.
2. Yalnız **bir** gerçek model çağrısı yapıldı.
3. Production yükü, erişilebilirlik veya model kararlılığı kanıtı **değildir**;
   tek başarılı çağrı genel üretim güvenilirliği, hukuki doğruluk veya geniş
   veri kapsamı kanıtı değildir.
4. Avukat raporu **hukuki karar değildir**.
5. Süre aşımı (expiry) **değerlendirilmedi**.
6. Sekiz fact hâlâ **unverified**'dır.
7. Masking v5 forward-only'dir; snapshot v4 dönemine ait sentetik artefaktlar
   içerir.
8. Python outer monitor tam bir OS sandbox'ı **değildir**.
9. Yalnız **sync** client yolu kanıtlandı; async client yolu kapsam dışıdır.
10. Revoke CLI'ın tekrar çalıştırma davranışı **idempotent değildir**.
11. Advisory-lock zaman aşımı (bounded acquisition) hâlâ açık bir sınırdır
    (`CLAUDE.md` §6).
12. Kalıcı küme bir servis **değildir**; reboot'ta otomatik başlamaz.
13. Backup manuel bir güvenlik ağıdır; restore paritesi üretim hazırlığı
    değildir.
14. Web login, Adım 11'deki gerçek Entra tenant/app kaydını bekler.
15. Console API anahtarının revoke edilmesi ve kullanıcı kapsamındaki ortam
    değişkeninin temizlenmesi LOCK sonrası operasyonel hygiene işidir;
    credential değeri repoya veya evidence'a yazılmadı.
16. Evidence, wheel'ler, harness, fixture kaynağı, runtime'lar ve scratchpad'ler
    LOCK tamamlanana kadar korunur.
17. Yerel çalışma kopyalarındaki EOL bakım konusu commit'li-bayt kapı sonucunu
    etkilemedi; ayrı bakım turuna ertelendi.
18. Row 19D ve Adım 10–13 **açıktır**.
19. **Adım 10 — ACTIVE / NEXT.**
20. **Pilot production-ready değildir.**
