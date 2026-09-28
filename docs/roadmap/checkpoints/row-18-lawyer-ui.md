### Row 18 — Lawyer UI (DONE / LOCKED — 18a: DONE/LOCKED, 18b: DONE/LOCKED, 18c: DONE/LOCKED — checkpoint özeti)

**Kapsam kararı (kullanıcı, 2026-09-04): Seçenek C** — tam etkileşimli kapsam
(dosya/kaynak görüntüleme, Layer A onay tetikleme, Layer B inceleme kararları,
Row 15 yapılandırılmış avukat talebi girişi, sonuç/hata/audit görüntüleme) +
**yerel, tek kullanıcılı FastAPI + Jinja2 (server-rendered) web uygulaması**,
yalnız `127.0.0.1` üzerinde. Kimlik doğrulama, çoklu kullanıcı, HTTPS/production
deployment, kalıcı oturum/veritabanı Row 19'a bırakıldı. Kullanıcı işi
**18a/18b/18c** olarak fazlandırdı; her faz kendi içinde test edilip
onaylanacak, tam Row 18 LOCK'u yalnız üçü de bittiğinde verilecek.

**Mutasyon sınırı (kullanıcı spesifikasyonu, her mutasyon için ZORUNLU)**:
(a) ilgili validator işlem anında yeniden çalışır, (b) kullanıcıya hedef kayıt/
mevcut durum/değişiklik gösterilir, (c) açık ikinci onay istenir (checkbox +
ayrı submit), (d) görüntülenen kaynak hash'i işlem anında yeniden kontrol
edilir ve değiştiyse işlem REDDEDİLİR, (e) yalnız var olan approval/review
Python fonksiyonları DOĞRUDAN çağrılır (asla shell/subprocess ile
`python ... --approve` çalıştırılmaz), (f) başarıda audit yolu + yeni hash
gösterilir, (g) hatada ASLA başarı ekranı gösterilmez. Generic "dosya yaz",
"komut çalıştır" veya kullanıcıdan keyfi path alan endpoint YOKTUR — bir
pending dosya kimliği yalnız ilgili modülün KENDİ listeleme fonksiyonunun
döndürdüğü gerçek bir adayla eşleşiyorsa kabul edilir (path traversal engeli).

**18a kapsamı — DONE / LOCKED** (kullanıcı onayı, hedeflenen
`vergi_ui_runtime` ortamında `pip check` PASS + 117/117 test PASS ile):
tüm 12 row için görüntüleme + Layer A onay tetikleme (Layer B ve Row 15
girişi 18a'da YOK — 18b/18c'ye bırakıldı). 23 dosya, tamamı `ui/` altında,
tamamı untracked: `main.py`, `__init__.py`, `requirements.txt`,
`services/{__init__,paths,common,live_view,security,approval_registry}.py`,
`templates/*.html` (9 dosya) + `static/style.css`,
`tests/{__init__,test_routes,test_service_isolated,test_templates_isolated}.py`.

**18a final güvenlik/mimari durumu** (bir statik inceleme + hedefli
remediation turu + iki route-test düzeltme turuyla ulaşıldı — kod tekrar
okunarak doğrulandı, varsayılmadı):

- **Yerel-only FastAPI/Jinja2 avukat arayüzü**: `ui/` gerçek bir Python
  paketi (`__init__.py`'lar, bağıl importlar) — desteklenen tek çalıştırma
  biçimi `python -m ui.main` / `uvicorn ui.main:app`; eski sys.path
  bootstrap'ı kaldırıldı.
- **Canonical/canlı case-view ayrımı korunuyor** (bkz. yukarıdaki EK) —
  görüntüleme öncesi canlı görünüm Row 17'nin gerçek
  `orchestrator_validator` fonksiyonlarından (`validate_schema`,
  `validate_case_id`, `validate_generated_at`,
  `validate_generation_status_consistency`) geçiyor; doğrulama
  başarısızsa fail-closed genel hata sayfası (`LiveViewInvalidError`),
  görünüm ASLA doğrulanmadan render edilmiyor.
- **Yalnız Layer A onay tetikleme** — case-scoped 10 modül (Row 8-17)
  `get_pending_path`/`get_canonical_path`/`inspect_pending`/`run_approve`
  tekdüze arayüzüyle tetikleniyor.
- **Fact (Row 6) / Timeline (Row 7) onayı DEVRE DIŞI** — kaynak kod
  (`fact_approval.py`, `timeline_approval.py`) tam okunarak doğrulandı:
  case_id başına "hangi pending güncel" sorusunu çözen yetkili bir
  resolver YOK. Bu iki aile `kind="unsupported_pending_resolution"`
  olarak yalnız bilgi amaçlı listeleniyor, onay butonu/route'u YOK — Row
  1-17'ye bu boşluğu kapatan bir resolver İCAT EDİLMEDİ.
- **Enumerated case_id ve row_key kontrolü** — tek bir allowlist
  çözücü (`paths.resolve_case_id`) hem route hem servis katmanında, her
  case_id alan noktanın başında; traversal/encode edilmiş
  traversal/separator/bilinmeyen-case reddi doğrudan test edildi.
  `row_key` sabit `CASE_SCOPED_ROWS_BY_KEY` evrenine karşı kontrol
  ediliyor.
- **Loopback-only middleware** — gerçek bağlanan istemci IP'sini
  kontrol ediyor, bind adresine güvenmiyor (`--host 0.0.0.0` yanlışlıkla
  verilse bile LAN'dan gelen istekler reddedilir).
- **HMAC CSRF token** — case_id + row_key + expected_hash'e bağlı,
  süreç-ömürlü sırla üretilen, sabit-zamanlı (`hmac.compare_digest`)
  doğrulanan token; expected-hash kontrolünün YERİNE GEÇMİYOR, ayrı bir
  katman.
- **Aynı-origin (Origin/Referer) doğrulaması** — header varsa host
  eşleşmesi zorunlu, CSRF token'a ek bir katman.
- **Mutasyon öncesi stale-hash koruması** — review ekranı render
  edildiğindeki pending hash, onay anında yeniden kontrol ediliyor;
  değiştiyse `run_approve` HİÇ ÇAĞRILMIYOR (`StaleViewError`).
- **Tarayıcıya genel hatalar** — `str(exception)`/ham mutlak path asla
  HTTP yanıtına girmiyor; sabit kod/mesaj tablosu kullanılıyor, ayrıntılı
  exception yalnız yerel konsola (`logging`) yazılıyor, repoya/dosyaya
  YAZILMIYOR.
- **Repo-göreli sonuç path'leri** — `approval_result.html`'e geçen
  canonical/audit path'leri `paths.to_repo_relative()`'ten geçiyor.
- **İzole mutasyon testleri + gerçek data/src byte-bütünlüğü** — tüm
  mutasyon/rollback/audit-failure testleri `TemporaryDirectory` + sahte
  adaptör modülüyle çalışıyor; eski `VERGI_UI_RUN_DESTRUCTIVE_TEST`
  yıkıcı test yolu tamamen kaldırıldı; gerçek `data/`/`src/` ağacının
  test öncesi/sonrası byte-düzeyinde değişmediği her test turunda
  ayrıca kanıtlandı.
- **`pip check` PASS ve 117/117 test sonucu** — 50 (saf-servis) + 17
  (Jinja2 şablon) + 50 (FastAPI route, TestClient) — hedeflenen
  `vergi_ui_runtime` ortamında kullanıcı tarafından fiilen çalıştırıldı.
- **Pinned `ui/requirements.txt`** — kök (UTF-16, ilgisiz anomalili)
  `requirements.txt`'den AYRI: `fastapi==0.141.1`, `starlette==1.6.0`,
  `httpx==0.28.1`, `jsonschema==4.26.0`, `pydantic==2.13.5`,
  `uvicorn==0.52.4`, `python-multipart==0.0.32`, `Jinja2==3.1.6`.
- **Bilinen, bloklayıcı olmayan backlog maddesi**: `StarletteDeprecationWarning:
  Using httpx with starlette.testclient is deprecated; install httpx2
  instead.` — yalnız test altyapısını (`TestClient`) ilgilendiriyor,
  üretim `uvicorn`/`fastapi` çalışma zamanını ETKİLEMİYOR; 117/117
  fonksiyonel geçiş bunu doğruluyor. `httpx2` bu fazda KURULMADI/ikame
  EDİLMEDİ (kullanıcı kararı) - gelecekteki bir bağımlılık yükseltme
  turuna bırakıldı.

**18a KAPSAM DIŞI (bilinçli, Row 19/18b/18c'ye bırakıldı)**: Layer B
inceleme kararları, Row 15 yapılandırılmış avukat talebi girişi, kimlik
doğrulama, çoklu kullanıcı erişimi, production/dış deployment.

**18b kapsamı — DONE / LOCKED** (kullanıcı onayı, hedeflenen
`vergi_ui_runtime` ortamında `pip check` PASS + Row 18A 117/117 + Row
18B servis 69/69 + şablon 42/42 + route 115/115 = **343/343** test PASS
ile): mevcut Layer B ("kayıt bazlı inceleme kararı": `needs_review` ->
`confirmed`/`rejected` veya `needs_review` -> `accepted_for_follow_up`/
`dismissed`) akışı, 5 ailenin (Evidence/Argument/Risk-Strategy/
Drafting/QA) **12 review-kind adaptörü** üzerinden TEK bir arayüzde
toplanır: `evidence.candidate`, `evidence.suggestion`,
`argument.claim`, `argument.counterargument`, `argument.rebuttal`,
`argument.suggestion`, `risk_strategy.risk`, `risk_strategy.strategy`,
`risk_strategy.suggestion`, `drafting.section`, `drafting.suggestion`,
`qa.suggestion`. Tam **11 dosyalık** Row 18B uygulama kapsamı — 4'ü
18a'nın var olan `ui/` dosyalarında değişiklik, 7'si yeni dosya:
`main.py` (değişiklik — Layer B route seti + CSRF üretim/doğrulama
yardımcıları eklendi), `services/common.py` (değişiklik — 6 yeni
`ReviewUiError` alt sınıfı eklendi), `static/style.css` (değişiklik —
salt-sunumsal `.confirm-form`/`.confirm-check`/`code.hash` eklendi),
`templates/case_view.html` (değişiklik — "İncelemeler (Layer B)" nav
linki eklendi), `services/review_registry.py` (yeni — 12 review-kind
registry), `templates/review_detail.html`, `templates/review_result.html`,
`templates/reviews_list.html` (yeni), `tests/test_review_routes.py`,
`tests/test_review_service_isolated.py`, `tests/test_review_templates_isolated.py`
(yeni).

**18b final güvenlik/mimari durumu** (bir hedefli remediation turu, bir
script-context JSON serialization sertleştirme turu, bir salt-okunur
LOCK-hazırlık incelemesi ve bir domain-error redaksiyon remediation
turuyla ulaşıldı — kod tekrar okunarak doğrulandı, varsayılmadı):

- **Backend-otoriter doğrulama/hedef-durum/geçiş kuralları** —
  `review_registry.py` var olan `src/*_review.py` (Row 12-16) modüllerinin
  İÇ MANTIĞINI (parent-dependency, R1-R6, stale-source, previous_state
  kontrolü, backup/atomic-write/rollback) YENİDEN YAZMAZ/KOPYALAMAZ;
  array/id/state alan adları ve hedef-durum allowlist'i HER ZAMAN ilgili
  backend modülünün KENDİ canlı sabitinden okunur (evidence/qa için
  registry'nin kendi, koddan doğrulanmış sabit metadata'sı — bu iki modül
  BY_TYPE sözlüğü taşımadığı için). R1-R6 parent-dependency semantiği
  aynen korunur; Risk/Strategy R2 hem reddi HEM DE `dismissed` kabul
  yolu, backend'in kendi `run_self_test()` fixture-üretim deseni
  (`FakeRiskStrategyLLMClient` + `build_risk_strategy_engine_output` +
  `_recompute_coverage`) yeniden kullanılarak bağımsız doğrulandı.
- **case_id ve review_kind allowlist'leri** — `_resolve_case` (case_id)
  ve `REVIEW_KIND_REGISTRY` (review_kind, sabit 12 değer) her route'un
  en başında; bilinmeyen/geçersiz değer her zaman aynı genel 404/hata.
- **Loopback-only erişim + aynı-origin doğrulaması** — 18a'nın middleware/
  `_check_csrf_and_origin` deseniyle AYNI, Layer B route'larında da
  uygulanıyor.
- **Beş parçalı CSRF bağlama** — `case_id + review_kind + record_id +
  target_state + canonical_hash` (HMAC, sabit-zamanlı doğrulama);
  `target_state` GET anında henüz seçilmediğinden her olası hedef için
  ayrı bir token üretilip sayfaya gömülür, `<select>` değiştikçe JS ile
  o hedefin token'ına güncellenir — POST anındaki `target_state` üretim
  hedefinden FARKLIYSA doğrulama BAŞARISIZ olur.
- **Mutasyon öncesi stale canonical-hash reddi** — `reviewreg.apply_transition`
  dosya varlığı + güncel hash'i, HERHANGİ bir backend adaptörü
  çağrılmadan ÖNCE kontrol eder; değiştiyse `ReviewStaleViewError`, sıfır
  mutasyon.
- **Fail-closed canonical yükleme/doğrulama** — `_load_and_validate_canonical`
  dosya okuma + ilgili ailenin KENDİ validator'ını (`raise_on_error=False`)
  TEK korumalı blokta çalıştırır; validator'ın ÖN KOŞUL yüklemesinde
  (`raise_on_error` bayrağından bağımsız) fırlayabilecek HERHANGİ bir
  beklenmeyen exception `ReviewLiveViewInvalidError`'a çevrilir — hiçbir
  kayıt doğrulanmadan render edilmez.
- **Tarayıcıya sabit, güvenli hata mesajları; domain exception'lar
  redakte edilir** — `_error_page` 18a'daki ilkeyle AYNI (sabit kod/mesaj
  tablosu, ham `str(exception)`/traceback/mutlak path asla yanıta
  girmez). Ayrıca 5 GERÇEK backend domain hata sınıfı
  (`EvidenceReviewError`/`ArgumentReviewError`/`RiskStrategyReviewError`/
  `DraftingReviewError`/`QaReviewError`) için `_domain_error_page`
  **ARTIK bu sınıfların KENDİ mesajını (`str(error)`) DA tarayıcıya
  geçirmez** — LOCK-hazırlık incelemesinde 5 backend'in TAMAMININ aynı
  domain sınıflarıyla mutlak dosya yolu içeren bir mesaj ("Canonical
  X.json bulunamadı:\n{mutlak_path}") fırlatabildiği kanıtlandı; tarayıcı
  artık HER ZAMAN tek bir sabit `REVIEW_DOMAIN_REJECTED` mesajı görür,
  orijinal exception TÜRÜ + TAM mesaj yalnız yerel `logging`'e (repoya/
  diske YAZILMADAN) yazılır — tanı için tam ayrıntı yerelde SAKLI kalır.
- **Script-context güvenli JSON serialization** — `review_detail.html`
  beş hedefe ait CSRF token haritasını (`csrf_tokens_by_target`) ham
  Python sözlüğü olarak main.py'den alır ve Jinja'nın KENDİ `|tojson`
  filtresiyle (elle `json.dumps(...)` + `|safe` YERİNE) serileştirir —
  `<`, `>`, `&`, `'` Unicode kaçışa çevrilir, `</script>` gibi
  script-kıran diziler HİÇBİR ZAMAN ham/çalıştırılabilir biçimde
  görünmez; script-breakout test kapsamı bunu doğrudan kanıtlıyor.
- **İzole mutasyon testleri + gerçek data/src byte-bütünlüğü** — tüm
  Row 18B mutasyon/CSRF/stale-hash/domain-redaksiyon testleri
  `TemporaryDirectory` + sahte/geçici olarak değiştirilmiş modül
  attribute'larıyla (backend'in KENDİ kodu hiç değiştirilmeden) çalışır;
  gerçek `data/`/`src/` ağacının test öncesi/sonrası byte-düzeyinde
  DEĞİŞMEDİĞİ her test turunda ayrıca kanıtlandı. `case_0001` üzerinde
  GERÇEK bir Layer B inceleme mutasyonu HİÇ ÇALIŞTIRILMADI; Row 18B
  testleri hiçbir canonical, approval-audit, review-audit, history veya
  backup verisi ÜRETMEDİ.
- **`pip check` PASS ve 343/343 toplam test sonucu** — Row 18A 117/117 +
  Row 18B servis (saf-Python) 69/69 + Row 18B şablon (Jinja2) 42/42 +
  Row 18B route (FastAPI, TestClient) 115/115 — hedeflenen
  `vergi_ui_runtime` ortamında kullanıcı tarafından fiilen çalıştırıldı.

**18b KAPSAM DIŞI (bilinçli, Row 19/18c'ye bırakıldı, DÜZELTİLMEYECEK)**:

- `StarletteDeprecationWarning: Using httpx with starlette.testclient is
  deprecated; install httpx2 instead.` — 18a'dan devralınan, yalnız test
  altyapısını ilgilendiren, üretim çalışma zamanını ETKİLEMEYEN bağımlılık
  bakım backlog maddesi; `httpx2` bu fazda KURULMADI/ikame EDİLMEDİ.
- **Çapraz-süreç eşzamanlılık / lost-update koruması** — mevcut
  stale-hash kontrolü atomik bir compare-and-swap DEĞİLDİR; backend'in
  kendi bağımsız yeniden-okumasıyla arada dar bir TOCTOU penceresi
  vardır (18a'nın `approval_registry.case_scoped_approve`'ıyla AYNI
  şekilde, zaten kabul edilmiş desen). Atomik CAS/kilitleme, kimlik
  doğrulama, çoklu kullanıcı yetkilendirme ve ilgili production
  sertleştirme kontrolleri Row 19'a bırakıldı.
- Row 18b, 18a ile AYNI şekilde yerel, loopback, tek-kullanıcılı bir araç
  sınırı içinde kalır.

**18c kapsamı — DONE / LOCKED** (kullanıcı onayı ve bağımsız bir
salt-okunur LOCK-hazırlık incelemesi, hedeflenen `vergi_ui_runtime`
ortamında `pip check` PASS + Row 18A 117/117 + Row 18B 226/226 + Row
18C servis 77/77 + şablon 15/15 + route 51/51 + CLI 26/26 =
**169/169** (Row 18 toplamı **512/512**) test PASS ile): Row 15'in
yapılandırılmış avukat talebi girişinin görüntülenmesi, doğrulanması
ve kaydedilmesi. Row 18C uygulama kapsamı — 4'ü 18a/18b'nin var olan
`ui/` dosyalarında değişiklik, geri kalanı yeni dosya: `main.py`
(değişiklik — Row 18C route seti + case_id'ye özgü 128 KiB ASGI
gövde-boyutu ara-katmanı eklendi), `services/common.py` (değişiklik —
yeni `DraftingRequestUiError` alt sınıfları eklendi), `static/
style.css` (değişiklik — salt-sunumsal eklemeler), `templates/
case_view.html` (değişiklik — "Yapılandırılmış Avukat Girdisi (Row
18C)" nav linki eklendi), `data/case_lawyer_input.schema.json` (yeni
— wrapper şeması), `services/drafting_request.py` (yeni — Row 18C
servis katmanı), `templates/drafting_request.html`, `templates/
drafting_request_result.html` (yeni), `run_drafting_request.py` (yeni
— salt-okunur varsayılan CLI köprüsü), `tests/
test_drafting_request_service_isolated.py`, `tests/
test_drafting_request_templates_isolated.py`, `tests/
test_drafting_request_routes.py`, `tests/
test_run_drafting_request_isolated.py` (yeni).

**18c final güvenlik/mimari durumu** (bir hedefli route-safety
remediation turu, bir ExceptionGroup body-limit remediation turu, bir
BaseException safety-order düzeltme turu ve bağımsız bir salt-okunur
LOCK-hazırlık incelemesiyle ulaşıldı — kod tekrar okunarak doğrulandı,
varsayılmadı):

- **Mimari sınır (Option A-prime, kullanıcı kararı)** — Row 18C
  route'ları YALNIZ `ui.services.drafting_request`'i çağırır; Drafting
  Engine'i (`build_drafting_engine_output`), `write_pending`'i, bir
  agent'ı veya bir network/LLM çağrısını HİÇBİR ZAMAN TETİKLEMEZ.
  Gerçek üretim yalnız ayrı, elle çalıştırılan `ui/run_drafting_request.py`
  CLI köprüsünün (`--generate-pending` bayrağı ARKASINDA) işidir;
  `main.py` bu modülü ASLA import ETMEZ.
- **Sabit case-scoped kayıt yolu** — `data/cases/<case_id>/drafting/
  inputs/lawyer_input.json`; kullanıcı-kontrollü path YOK.
- **Yerel `$ref` ile şema bütünlüğü** — `case_lawyer_input.schema.json`,
  `lawyer_input` alanı için YEREL, önceden diskten yüklenmiş bir
  `referencing.Registry` üzerinden Row 15'in LOCKED
  `case_drafting.schema.json#/$defs/lawyer_input` tanımına atıf yapar;
  hiçbir `retrieve=` callback'i TANIMLANMAZ (network'e ULAŞAMAZ),
  kayıtlı olmayan bir referans fail-closed `Unresolvable` fırlatır.
- **Issue seçim tri-state'i + canonical üyelik** — "sağlanmadı" /
  "açıkça hiçbiri" / "açıkça seçilmiş" ayrımı korunuyor; yinelenen/
  sahte/bilinmeyen issue id'leri reddediliyor, kabul edilenler
  deterministik (lexicographic) sıralanıyor. `selected_source_ids`
  editable UI'da HİÇ GÖSTERİLMİYOR, her zaman onaylı boş yapı olarak
  kaydediliyor.
- **request_input / lawyer_provided_text bağımsızlığı** — Row 15'in
  Q1 (dayanak var mı) / Q2 (avukat açıkça üretim istedi mi) ayrımı
  DEĞİŞTİRİLMEDEN kullanılıyor; boş/yalnız-boşluk değerler YETKİ
  ÜRETMİYOR.
- **Atomik yazma + tam rollback** — kaydetme öncesi TAM paylaşılan
  doğrulayıcı (pre-write), atomik `os.replace` yazımı, post-write
  yeniden doğrulama, ve başarısızlıkta TAM rollback: ilk-kayıt
  başarısızlığı yeni dosyayı/audit'i/history'yi/`.tmp`'yi tamamen
  temizliyor; üzerine-yazma başarısızlığı orijinal içeriği BAYT-BAYT
  ve izin bitleriyle GERİ YÜKLÜYOR; audit-yazma başarısızlığı da AYNI
  rollback'i tetikliyor. Geçmiş/audit dosya adları `O_CREAT|O_EXCL` +
  sayısal sonekle çakışmaya dayanıklı. Audit kayıtları yalnız
  metadata/hash taşıyor, asla hukuki serbest metin.
- **Mutasyon öncesi zorunlu kontroller** — case_id allowlist çözümü,
  loopback-only erişim, aynı-origin doğrulaması, HMAC CSRF (case_id +
  "drafting_request" + "save" + expected_current_input_hash'e bağlı),
  onay checkbox'ı ve stale-hash reddi HEPSİ herhangi bir mutasyondan
  ÖNCE uygulanıyor; loopback ara-katmanı, Row 18C'ye özgü gövde-boyutu
  ara-katmanından ÖNCE çalışıyor (Starlette middleware sırası doğrudan
  doğrulandı).
- **128 KiB gövde sınırı + ExceptionGroup/BaseExceptionGroup güvenliği**
  — hem beyan edilen `Content-Length` hem GERÇEK kümülatif bayt sayımı
  kontrol ediliyor; tam 128 KiB kabul, 128 KiB+1 red. AnyIO/Starlette'in
  hedef istisnayı bir `ExceptionGroup` içine sarmalayabilmesi
  ihtimaline karşı, saf `isinstance` tabanlı yinelemeli bir ağaç
  kontrolü (`_exception_tree_contains_body_too_large`) kullanılıyor -
  string eşleştirmesi YOK. **BaseException güvenlik sırası**: hem
  route'un hem ara-katmanın yakalama noktaları `except BaseException`
  DEĞİL `except Exception` kullanıyor, ve yardımcı fonksiyon en dış
  çağrıda dahi önce `isinstance(error, Exception)` kontrolü yapıyor -
  bu yüzden `_DraftingRequestBodyTooLarge` + iptal/`CancelledError`/
  `SystemExit`/`KeyboardInterrupt` TAŞIYAN karışık bir
  `BaseExceptionGroup` ASLA 413'e dönüştürülüp kontrol-akışı sinyali
  YUTULMUYOR (standalone script + gömülü birim testleriyle doğrudan
  doğrulandı).
- **Tarayıcıya sabit, güvenli hata mesajları** — `_error_page` 18a/18b
  ile AYNI ilkeyle çalışıyor; ham exception/traceback/mutlak path/
  gönderilen hukuki serbest metin ASLA yanıta/audit'e/dosya adına
  YANSIMIYOR.
- **Script-context güvenli şablonlar** — `drafting_request.html`
  yalnız sabit bir sunucu-sabiti `|tojson` ile JS'e gömüyor; hiçbir
  kullanıcı girdisi `<script>` içine GİRMİYOR; üç Row 18C şablonunda
  da `|safe` bypass'ı YOK (Jinja2 varsayılan autoescape korunuyor).
- **Salt-okunur varsayılan CLI köprüsü** — `python -m ui.run_drafting_request
  --case <case_id>` bayraksız TAMAMEN salt-okunur; `--generate-pending`
  olmadan üretim/agent/network TETİKLENEMEZ; `--with-agent`/
  `--allow-network`, `--generate-pending` olmadan veya `--allow-network`,
  `--with-agent` olmadan verilirse hiçbir mutasyon olmadan reddediliyor;
  üretim öncesi kaydedilmiş wrapper yeniden doğrulanıyor; `--case`
  DIŞINDA hiçbir path/dosya argümanı YOK.
- **İzole mutasyon testleri + gerçek data/src byte-bütünlüğü** — tüm
  Row 18C mutasyon/rollback/audit/CSRF/stale-hash/body-limit testleri
  `TemporaryDirectory` + sentetik case_id ile çalışıyor; gerçek
  `data/`/`src/` ağacının ve gerçek `case_0001`'in test öncesi/sonrası
  byte-düzeyinde DEĞİŞMEDİĞİ her test turunda ayrıca kanıtlandı.
  `case_0001` üzerinde GERÇEK bir Row 18C girdi kaydı HİÇ ÇALIŞTIRILMADI;
  implementasyon/test boyunca hiçbir gerçek Drafting Engine/LLM/network
  çalıştırması YAPILMADI ve hiçbir gerçek case verisi mutasyona
  uğratılMADI.
- **`pip check` PASS ve Row 18C 169/169 test sonucu** — servis
  (saf-Python) 77/77 + şablon (Jinja2) 15/15 + route (FastAPI,
  TestClient) 51/51 + CLI 26/26 — hedeflenen `vergi_ui_runtime`
  ortamında kullanıcı tarafından fiilen çalıştırıldı; Row 18A 117/117
  + Row 18B 226/226 ile birlikte **Row 18 toplamı 512/512**.
- **Bağımsız salt-okunur LOCK-hazırlık incelemesi** — ayrı bir
  incelemede git preflight (branch/HEAD/staged set/13 dosyalık kapsam),
  şema/$ref izolasyonu, storage/rollback sırası, HTTP/CSRF/loopback/
  body-limit/exception-safety davranışı ve CLI kapıları KODUN
  KENDİSİNDEN doğrudan yeniden doğrulandı (yalnız test isimlerine/
  raporlara güvenilmedi); hiçbir engelleyici bulgu RAPORLANMADI - tek
  kozmetik not aşağıda listeleniyor.

**18c KAPSAM DIŞI / bilinen backlog (bilinçli, Row 19'a bırakıldı,
DÜZELTİLMEYECEK)**:

- `DraftingRequestCsrfError` (`services/common.py`) şu an TANIMLI ama
  hiç fırlatılmıyor - kullanılmayan ölü kod, güvenlik açığı DEĞİL
  (CSRF zaten `_check_csrf_and_origin` ile ayrıca uygulanıyor); yalnız
  kozmetik bir temizlik maddesi.
- `StarletteDeprecationWarning: Using httpx with starlette.testclient
  is deprecated; install httpx2 instead.` — 18a'dan devralınan, yalnız
  test altyapısını ilgilendiren bağımlılık bakım backlog maddesi;
  `httpx2` bu fazda KURULMADI/ikame EDİLMEDİ.
- Kimlik doğrulama, çoklu kullanıcı yetkilendirme, production/dış
  deployment ve çapraz-süreç eşzamanlılık/atomik CAS koruması (18b'de
  de not edilen TOCTOU penceresiyle AYNI, zaten kabul edilmiş desen)
  — Row 18'in TAMAMI için Row 19'a bırakılmış kapsam dışı maddelerdir.
- Row 18c, 18a/18b ile AYNI şekilde yerel, loopback, tek-kullanıcılı
  bir araç sınırı içinde kalır.
- **Önemli netlik**: bu fazda bir avukat girdisinin KAYDEDİLMESİ, bir
  taslağın (draft) ÜRETİLDİĞİ anlamına GELMEZ - kaydetme ve pending
  taslak üretimi (yalnız ayrı CLI köprüsüyle, `--generate-pending` ile)
  TAMAMEN AYRI işlemlerdir.

**ROW 18 — LAWYER UI TAMAMLANDI VE LOCKED** (18a + 18b + 18c üçü de
DONE/LOCKED) — kullanıcı onayı ve bağımsız bir salt-okunur
LOCK-hazırlık incelemesiyle.

**Sonraki adım**: **ROW 19 — PRODUCTION / SECURITY** — **ACTIVE / NEXT**
— 19A tamamlandı (aşağıya bkz.); 19B/19C/19D için henüz implementasyona
BAŞLANMADI.

