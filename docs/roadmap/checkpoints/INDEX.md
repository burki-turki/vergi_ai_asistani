# Tarihsel Checkpoint Arşivi — INDEX

Bu dizin, `CLAUDE.md`'den **birebir (byte-exact)** çıkarılmış tamamlanmış
Row / Phase / Step / Slice checkpoint gövdelerini taşır. Bu dosyalar
**canonical historical evidence**'dır; **canlı politika değildir**.
Canlı çalışma kuralları yalnız `CLAUDE.md`'dedir.

Bu arşivler **live project memory'ye otomatik import EDİLMEZ**:
`CLAUDE.md` bu dosyalara yalnız **normal Markdown bağlantısı** ile atıf
yapar, otomatik import sözdizimi (satır başında `@` önekli dosya yolu)
kullanılmamıştır. Gerektiğinde, özellikle **§9 kapsamında** bir LOCKED
sözleşmeye dokunmadan önce, ilgili arşiv dosyası **açıkça okunur**.

## Migration kanıtı

| Alan | Değer |
|---|---|
| Kaynak commit | `3fd681d6942547ae32ff73340452ca8ad3fe59a7` |
| Kaynak `CLAUDE.md` git blob | `c171de63b872373b196d2d686a469bd00fed2459` |
| Kaynak içerik SHA-256 | `fa77d7525e11afef5f097d1a1db076be5645d137210e0cab9a6cf50fb3cc7112` |
| Original span | `L1166`–`L11037` |
| Toplam satır | 9872 |
| Toplam karakter | 572829 |
| Toplam bayt | 605837 |
| Blok sayısı | 48 |
| Original span SHA-256 | `2d9d3fcd00213ed9cba55a41b1eaa986e3128792bc79b1a8d42be9c590f5a926` |
| Reconstruction SHA-256 (8 dosya birleşimi) | `2d9d3fcd00213ed9cba55a41b1eaa986e3128792bc79b1a8d42be9c590f5a926` |
| Reconstruction eşliği | **byte-identical** |

Sekiz içerik dosyası **aşağıdaki sırayla** birleştirildiğinde original
`L1166`–`L11037` bayt dizisi birebir yeniden üretilir.

## Dosya sırası

| # | Dosya | Bloklar | Original span | Satır | Karakter | Bayt | SHA-256 |
|---|---|---|---|---|---|---|---|
| 1 | [`rows-09-17-agent-layer.md`](rows-09-17-agent-layer.md) | 0–8 | L1166–1717 | 552 | 35267 | 37119 | `e7b44e0248f366b6eb6dfd3d474d3dbafff4f66e2adfe2b73464a1364b7b51db` |
| 2 | [`row-18-lawyer-ui.md`](row-18-lawyer-ui.md) | 9–9 | L1718–2087 | 370 | 22579 | 24052 | `5c29882996d6a096b2a309433d6d7c24c2c5128fbabec6d446506e288acdbd2d` |
| 3 | [`row-19a-19b-threat-model-and-identity.md`](row-19a-19b-threat-model-and-identity.md) | 10–11 | L2088–2351 | 264 | 14655 | 15571 | `2cd6588f17d844b9ff78584d6fbed6c43ee5d8238f70db7cb8e5a4f97329754e` |
| 4 | [`row-19c-mutation-integrity.md`](row-19c-mutation-integrity.md) | 12–23 | L2352–4896 | 2545 | 135468 | 142159 | `ed0868a66ecbf4c8374376e7a61106d49129f419adabeeb965207b2b3cd8984a` |
| 5 | [`rag-bundle-corpus-and-schema-patches.md`](rag-bundle-corpus-and-schema-patches.md) | 24–28 | L4897–6581 | 1685 | 104874 | 110976 | `900c77f8f1e547e175c28d8b64b2b813e4f1c5edabf235d2d2813500f6721368` |
| 6 | [`row-19d-auth-and-oidc-remediation.md`](row-19d-auth-and-oidc-remediation.md) | 29–31 | L6582–7384 | 803 | 43815 | 46190 | `34eba19687dcca3d3568b1ca860b199d46b76ad5d1cbdad14b3bb42e00e201a8` |
| 7 | [`pilot-readiness-steps-1-5-and-mali-tatil.md`](pilot-readiness-steps-1-5-and-mali-tatil.md) | 32–41 | L7385–9747 | 2363 | 145449 | 155176 | `f9fabc211d5d6a68bd80300faffa37ce4904df5e8e8e6eaeb11e8f1ae3b5aa29` |
| 8 | [`holiday-calendar-and-deadline-hardening.md`](holiday-calendar-and-deadline-hardening.md) | 42–47 | L9748–11037 | 1290 | 70722 | 74594 | `f69f1dacfd6569d56f806da7f4eeb02014349dab166f78cde34c32376edd8777` |

## Blok manifesti (48 blok)

| # | Checkpoint başlığı | Original span | Satır | Karakter | Blok SHA-256 | Dosya |
|---|---|---|---|---|---|---|
| 0 | Row 9 — Issue Spotting Agent (DONE / LOCKED — checkpoint özeti) | L1166–1177 | 12 | 786 | `3d99494e6b9421edfb0ee8987fe635b86c18ecc6856dd043f5c7be8b4198fa31` | `rows-09-17-agent-layer.md` |
| 1 | Row 10 — Legal Research Agent (DONE / LOCKED — checkpoint özeti) | L1178–1195 | 18 | 1184 | `1348df21f7d2c3ef8ba578b885c9f097ef9b7ffe8236ca08fa78c0daf7678dd0` | `rows-09-17-agent-layer.md` |
| 2 | Row 11 — Case Law Agent (DONE / LOCKED — checkpoint özeti) | L1196–1216 | 21 | 1481 | `33049554c916d186391d0797a991c19db3c527ca77314df295f37305e95e76d7` | `rows-09-17-agent-layer.md` |
| 3 | Row 12 — Evidence Agent (DONE / LOCKED — checkpoint özeti) | L1217–1285 | 69 | 4256 | `bb491e1c881c55204270ec5137c18401ad60bc0ac531b207c4a46e51beb03426` | `rows-09-17-agent-layer.md` |
| 4 | Row 13 — Argument Agent (DONE / LOCKED — checkpoint özeti) | L1286–1329 | 44 | 2830 | `11d7908af1aedfb8128cc33fddfc5d726e48ed9421facb8ba22c17746488a7c9` | `rows-09-17-agent-layer.md` |
| 5 | Row 14 — Risk / Strategy Agent (DONE / LOCKED — checkpoint özeti) | L1330–1423 | 94 | 5947 | `cda9190e2440322ca1a31c93d87c8ed403b25d3d6b7d76ab621821d2615a4035` | `rows-09-17-agent-layer.md` |
| 6 | Row 15 — Drafting Agent (DONE / LOCKED — checkpoint özeti) | L1424–1514 | 91 | 5837 | `bd8b504362121405ce8ca81fce18cedf1d729aefa62674bee2be6c17ab5073ea` | `rows-09-17-agent-layer.md` |
| 7 | Row 16 — QA Agent (DONE / LOCKED — checkpoint özeti) | L1515–1595 | 81 | 4726 | `87aa5c61971972c9c7d2f76775ec3551a68ba3d9d1d3063eeace32be8e98a132` | `rows-09-17-agent-layer.md` |
| 8 | Row 17 — Product Orchestrator Agent (DONE / LOCKED — checkpoint özeti) | L1596–1717 | 122 | 8220 | `98bc978b246d2e988e175fbbd4b598b71042426c7d74176f63044be16f06f99e` | `rows-09-17-agent-layer.md` |
| 9 | Row 18 — Lawyer UI (DONE / LOCKED — 18a: DONE/LOCKED, 18b: DONE/LOCKED, 18c: DONE/LOCKED — checkpoint özeti) | L1718–2087 | 370 | 22579 | `5c29882996d6a096b2a309433d6d7c24c2c5128fbabec6d446506e288acdbd2d` | `row-18-lawyer-ui.md` |
| 10 | Row 19A — Threat Model & Deployment Contract (DONE / LOCKED — checkpoint özeti) | L2088–2262 | 175 | 9962 | `b5a012ae1ec67784968dd70e61572e1bb247c27598f82762e842529a5a032ccb` | `row-19a-19b-threat-model-and-identity.md` |
| 11 | Row 19B — Identity / Session / Authorization (DONE / LOCKED — checkpoint özeti) | L2263–2351 | 89 | 4693 | `e91d2a1868e902b3448a97d96d4422b5fb6daa75cb392dc54845b7a8c99c84ff` | `row-19a-19b-threat-model-and-identity.md` |
| 12 | Row 19C-1 — Coordinator Core & Path Safety (DONE / LOCKED — checkpoint özeti) | L2352–2504 | 153 | 8443 | `8860545e38de4ed7302cde88e6c4ffa2b3f20a6c74492128024013b0005eb7bc` | `row-19c-mutation-integrity.md` |
| 13 | Row 19C-2a — Layer A Approval Mutation Integration (DONE / LOCKED — checkpoint özeti) | L2505–2673 | 169 | 9075 | `dffe049a9fd8c11300d23a0622da35b2f2603a26e771154f3f930b99871f9b64` | `row-19c-mutation-integrity.md` |
| 14 | Row 19C-2b — Layer B Review Mutation Integration (DONE / LOCKED — checkpoint özeti) | L2674–2929 | 256 | 15399 | `820f2ef8f0d2adaad9ad6c7ad1332424da5437f57edea03c8bf51761c37e46f4` | `row-19c-mutation-integrity.md` |
| 15 | Row 19C-2c — Drafting-Request Mutation Integration (DONE / LOCKED — checkpoint özeti) | L2930–3119 | 190 | 10601 | `776fef9b324a0a731ae36d0610c2ed8c516194ca901010412b91e718e2b0e8a8` | `row-19c-mutation-integrity.md` |
| 16 | Row 19C-3a Slice 1 — Shared Path-Containment Foundation (DONE / LOCKED — checkpoint özeti) | L3120–3281 | 162 | 9256 | `7874ef0685f726d66c911114d1e90fb2064cb5723c37f6d045f6a7c25d2375a2` | `row-19c-mutation-integrity.md` |
| 17 | Row 19C-3a Slice 2 — Layer A/B Nested Path-Containment Closure (DONE / LOCKED — checkpoint özeti) | L3282–3436 | 155 | 7357 | `01f3302566796c0f818214aaccca5ec33699b8ff4595d1154ca6fd1da8730afa` | `row-19c-mutation-integrity.md` |
| 18 | Row 19C-3b Slice 1 — Facade-Backed Legacy CLI Mutation Integration (DONE / LOCKED — checkpoint özeti) | L3437–3677 | 241 | 9137 | `6930271d7221e083ed33df1fdf274f72debe557865e56f7a1700d3bfa4181812` | `row-19c-mutation-integrity.md` |
| 19 | Row 19C-3b Slice 2 — Fact/Timeline Canonical Promotion Integration (DONE / LOCKED — checkpoint özeti) | L3678–3878 | 201 | 10322 | `b8abc463162aa6624c3565d48a58cd71fc394d4c3e71f394fac3097a70103c7e` | `row-19c-mutation-integrity.md` |
| 20 | Row 19C-3c-i — Deterministic Generation Integration (DONE / LOCKED — checkpoint özeti) | L3879–4089 | 211 | 11458 | `a81b22a77ed4e229b478ad153999e9b3b2276e893fc1c69fa48e078c53e821a6` | `row-19c-mutation-integrity.md` |
| 21 | Row 19C-3c-ii — Case-Scoped Agent-Gated Pending Generation Integration (DONE / LOCKED — checkpoint özeti) | L4090–4391 | 302 | 16099 | `40a2a68cfa3ef5c112a359405291efb3c37b2f629c4223c07e5574ab9b8d29ec` | `row-19c-mutation-integrity.md` |
| 22 | Row 19C-3c-iii — Fact Extraction Generation Integration (DONE / LOCKED — checkpoint özeti) | L4392–4634 | 243 | 13734 | `ecc57fbbdf44191c624ecc9779589119be4db1ceb69b12b82d116818c7f37e1d` | `row-19c-mutation-integrity.md` |
| 23 | Row 19C-3c-iv Slice 1 — Deterministic + Agent Legal Research / Case Law Pending-Generation Integration (retrieval/discovery deferred) (DONE / LOCKED — checkpoint özeti) | L4635–4896 | 262 | 14587 | `0f2374d940e733024962d268ced23d49b91b8cd66832dd7b44cad3aca1ac9fd4` | `row-19c-mutation-integrity.md` |
| 24 | RAG Global-Resource Bundle Foundation (DONE / LOCKED — checkpoint özeti) | L4897–5220 | 324 | 19483 | `541572ee66abd3d777fc3235f6cbf96aac0fb522eeb90a95e7a5f9f683f3ddd8` | `rag-bundle-corpus-and-schema-patches.md` |
| 25 | RAG Real-Dependency Validation + Synthetic E2E Gate (DONE / LOCKED — checkpoint özeti) | L5221–5424 | 204 | 11505 | `6d68888c22b44885cd49a2be6817a9386ff3f6cb10dbfa8100eb3e6537a17b7c` | `rag-bundle-corpus-and-schema-patches.md` |
| 26 | Row 10/11 Legal Research + Case Law Schema Patch (DONE / LOCKED — checkpoint özeti) | L5425–5668 | 244 | 13890 | `6e3470b80c313323f2675de127e7668bf495aff294b0fa130a743dafbbac84e7` | `rag-bundle-corpus-and-schema-patches.md` |
| 27 | RAG Corpus Policy Foundation (DONE / LOCKED — checkpoint özeti) | L5669–6096 | 428 | 28689 | `fddcf3b2070cc040ead4a075d9468eefb8d3e076b0ba0a938aebfcedf5bb3a2e` | `rag-bundle-corpus-and-schema-patches.md` |
| 28 | RAG Corpus Prerequisite Documents-Schema Patch (DONE / LOCKED — checkpoint özeti) | L6097–6581 | 485 | 31307 | `bda20735527a66cb8f2b1dc447bc87347c7ceb5850f9db8a77909704de631ff8` | `rag-bundle-corpus-and-schema-patches.md` |
| 29 | Row 19D Authentication Enablement Slice 1 — Local Key Custody and Auth Seam Enablement (DONE / LOCKED) | L6582–6724 | 143 | 7992 | `552ee4d4e3f4b61d1b252753d35783a3c0327b497f373a5d35acbe6f0952b3c0` | `row-19d-auth-and-oidc-remediation.md` |
| 30 | Row 19D Authentication Enablement Slice 2 — Azure Key Vault Secrets Custody Provider Foundation (DONE / LOCKED — checkpoint özeti) | L6725–7030 | 306 | 16017 | `3233ab7350f9c102313d4d4b2484dd5c0bbcfbc5e70235ca27013e72107c577e` | `row-19d-auth-and-oidc-remediation.md` |
| 31 | Row 19B OIDC Confidential-Client Remediation — DONE / LOCKED | L7031–7384 | 354 | 19806 | `ff7291f58a494327c5affcd3359d0db6e6e214f46745cb5cee676c7ae05735f6` | `row-19d-auth-and-oidc-remediation.md` |
| 32 | Fact Verification Workflow (DONE / LOCKED — checkpoint özeti) | L7385–7812 | 428 | 23692 | `d64297574bd22e0f8a19bc554e88ff42cc22cb787901a963fca522bf192f0799` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 33 | Pilot Readiness Adım 2 — Case-Data Repository Protection (DONE / LOCKED — checkpoint özeti) | L7813–8063 | 251 | 14644 | `2af2703955d93821670e3feff0063aeeb0b67ccb5cccfb6aa7e2cc97eb763710` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 34 | Pilot Readiness Adım 3 — Runner / Environment / Skip Reporting (DONE / LOCKED — checkpoint özeti) | L8064–8265 | 202 | 12045 | `a0ee042fba9da95feea7b3c54f17e5f45c59cb0674b29723ec8cc4eb71a2d601` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 35 | Pilot Readiness Adım 4a — LLM Gizlilik Sınırı: Fact Extraction Takma Adlandırma (DONE / LOCKED — checkpoint özeti) | L8266–8472 | 207 | 14405 | `f5879bed4cb9bcead0d844b8d3f430e8c5bfafb01406770e78b0d375c0e223b2` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 36 | Pilot Readiness Adım 4a Remediation — Satır-Sonu Tire Maskeleme Açığının Kapatılması (DONE / LOCKED — checkpoint özeti) | L8473–8610 | 138 | 8376 | `1ae013f242105a53bbf7507dc03a9106742173b051bb8dad998ed66bb44c78db` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 37 | Pilot Readiness Adım 4a Remediation 2 — Bölünmüş TCKN/VKN Fail-Closed Maskeleme (R5) (DONE / LOCKED — checkpoint özeti) | L8611–8880 | 270 | 18778 | `03d1c88cd96c6f478e1d9ab8de5e5ba41d5b8eae4ebcaa72938a7719bfd3dd79` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 38 | Pilot Readiness Adım 4b — Ham Veri Taşıyan Ajanların ve `app.py`'nin Mekanik Kapatılması (DONE / LOCKED — checkpoint özeti) | L8881–9045 | 165 | 11618 | `2c627755bbce12672489ff9de33c6a813bc3612678e6bbea49f04837ca78f2cf` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 39 | Pilot Readiness Adım 4c — Kalan Outbound LLM Yollarının Kapatılması (DONE / LOCKED — checkpoint özeti) | L9046–9264 | 219 | 13129 | `c3aa0d85e31887255e47cf9eb7463a888a3261444ce7123ea31ae4fd321d0b8d` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 40 | Pilot Readiness Adım 5 — Resmî Tatil Takvimi Registry'si + `calendar_complete` Türetimi (DONE / LOCKED — checkpoint özeti) | L9265–9504 | 240 | 14317 | `9334c7535c9a300e54c2750fa9d253500d018bd7866c6162eab5322dbba39f52` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 41 | Pilot Readiness Adım 7 — Mali Tatil (5604 sayılı Kanun) Deadline Handling (DONE / LOCKED — checkpoint özeti) | L9505–9747 | 243 | 14445 | `4b5f745a0e23ea5b229222d860ab399c28a62a7717b980f35d5a9ce6a9f996df` | `pilot-readiness-steps-1-5-and-mali-tatil.md` |
| 42 | Holiday Calendar Schema V2 — Phase A Technical Plumbing (DONE / LOCKED — checkpoint özeti) | L9748–10070 | 323 | 19398 | `67d03f91264fd534a1754ea01bc0a4ab9e017ed398be32d66d4344981ef12afb` | `holiday-calendar-and-deadline-hardening.md` |
| 43 | Holiday Calendar Phase B — Veri Popülasyonu + Portable QA/Case-View Publisher'ları (DONE / LOCKED — checkpoint özeti) | L10071–10286 | 216 | 11950 | `91cc42896529bcf584b0f34d318a08209a7ddcfe9d49b3ff0a84ada16f3b3daf` | `holiday-calendar-and-deadline-hardening.md` |
| 44 | Adım 6 — Altın Örnek Diferansiyel Doğrulama (DONE / LOCKED — checkpoint özeti) | L10287–10430 | 144 | 8154 | `7e8ef8ebc56021895eedf4bc9bc7904247f09b09c5c1e6f6ddd76562086ced9b` | `holiday-calendar-and-deadline-hardening.md` |
| 45 | Adım 7 / Slice 1 — Stopping-Event Attestation Gate (DONE / LOCKED — checkpoint özeti) | L10431–10640 | 210 | 11286 | `bfcac4111951f3f536ea35840dbac19983e05de72d31ca22b28d5979a8f7d739` | `holiday-calendar-and-deadline-hardening.md` |
| 46 | Adım 7 / Slice 2 — Stopping-Event Canonical and UI Visibility (DONE / LOCKED — checkpoint özeti) | L10641–10866 | 226 | 10314 | `a07b90adcc18abb705b8f9abd6daeb4929f64ba31330aedf1a05617eefb60fdb` | `holiday-calendar-and-deadline-hardening.md` |
| 47 | Adım 7 — Deadline Hardening Pilot-Scope Closure (DONE / LOCKED FOR CURRENT PILOT — checkpoint özeti) | L10867–11037 | 171 | 9620 | `e9bed98ba97b972d94e080912fe676ba73038eba03faa9790ae6856a73688375` | `holiday-calendar-and-deadline-hardening.md` |
