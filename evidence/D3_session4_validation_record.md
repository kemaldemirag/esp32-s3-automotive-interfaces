# REP-03 Oturum 4 D3 Doğrulama Kaydı

Tarih: 24 Ekim 2026
Kapsam: P0 doğruluk düzeltmeleri, kaynak/kanıt kaydı, WF-03-06 ignition shutdown ve gerçek Draft 2020-12 regresyonu
Sonuç: `ACCEPTED_SYNTHETIC_SCOPE`
Fiziksel doğrulama: `NOT_RUN`
G1: `BLOCKED`
G2: `NOT_STARTED`

## Başlangıç ve çalışma ağacı

- Repo: `esp32-s3-automotive-interfaces`
- Dal: `main`
- Upstream: `origin/main`
- Başlangıç commit'i: `9c06fce366c4c65df2e13c5e48846f0c977d6b0d`
- Bu kayıttan hemen önceki durum: 10 değiştirilmiş tracked dosya ve 45 untracked dosya.
- Oturum 3, P0 ve Oturum 4 çalışmaları hâlâ çalışma ağacındadır. Commit veya push yapılmamıştır.

Bu kayıt, kirli çalışma ağacını temiz bir Git baseline'la karıştırmaz. Oturum sonunda ayrı bir geri dönüş paketi oluşturulmuştur:

- Arşiv: `../../_snapshots/REP-03_WIP_2026-10-24_WF03-06.zip`
- Boyut: `600171` bayt
- SHA-256: `948b4838a0ea1a1463ed3f2a7ee400045998fc3994d37df56ea997519cfd4199`
- Ayrık özet: `../../_snapshots/REP-03_WIP_2026-10-24_WF03-06.zip.sha256`
- Kapsam: çalışma ağacındaki proje dosyaları; `.git/` bilerek arşive alınmamıştır.

Arşiv bu kimlik satırları eklenmeden hemen önce alınmıştır; arşivdeki proje içeriği ile güncel çalışma ağacı arasındaki bilinçli fark yalnız bu geri dönüş paketi metadata paragrafıdır.

## P0 doğruluk kapanışları

| Bulgu | Uygulanan kapanış | Regresyon |
| --- | --- | --- |
| D1 `NaN`/`Infinity` girdisinde exception | Non-finite değerler deterministik işaretleniyor; tam yol ile `FAIL / REP03-SCHEMA-010 / NON_FINITE_NUMBER` üretiliyor. Kök kimlik alanları string değilse rapora `null` yazılıyor. | NaN, +Infinity, -Infinity, dizi konumu, `schema_version` ve `variant_id`; `allow_nan=False` ile serileştirme. |
| Automotive transient kaynak fail-open | `ENGINEERING_RULE + OEM` geçişi kapatıldı. GAP-03 kaydında onaylı OEM kaynağı olmadığından keyfi `SOURCE_EXPLICIT + OEM` etiketi de `BLOCKED / OEM_PROFILE_SOURCE_NOT_APPROVED` üretiyor. | Beş transient türü ve keyfi OEM reference/version etiketi. |
| Şemalar yalnız yüzeysel kontrol ediliyordu | `jsonschema` Draft 2020-12 test bağımlılığı olarak sabitlendi. Altı şema belgesi, 44 fixture girdisi ve bu girdilerden üretilen 44 rapor gerçek validator ile kontrol ediliyor. | Şema envanteri birebir eşitliği, unknown-field reddi, kapalı iç içe nesneler ve strict JSON serileştirme. |

## Kaynak ve kanıt kaydı

[`source_evidence_register.v1.json`](source_evidence_register.v1.json) GAP-01 ile GAP-04 arasındaki kaynak sahipliğini tek kapalı kayıtta toplar.

| GAP | Durum | Eksik kapanış otoritesi | Geçerli iddia sınırı |
| --- | --- | --- | --- |
| GAP-01 | `BLOCKED` | Onaylı BOM ve CAN/LIN parça üreticisi kaynakları | Sentetik controller/UART/FSM |
| GAP-02 | `BLOCKED` | Onaylı GNSS modül/anten kaynakları ve proje RF incelemesi | Sentetik fix veri kalitesi |
| GAP-03 | `BLOCKED` | Onaylı OEM/araç transient gereksinimi, exact power-path BOM ve üretici kaynakları | Sentetik profil sözleşmesi |
| GAP-04 | `BLOCKED` | Onaylı Raspberry Pi modeli, platform kaynağı ve host yazılım protokolü | Sentetik shutdown olay izi |

23 Ekim 2026 Drive literatürü `RESEARCH_GUIDANCE`, yerel görev planı `PROJECT_CONTRACT_GUIDANCE` rolündedir. Bu kaynaklar kontrol listesi ve akış semantiği sağlar; tek başlarına GAP kapatamaz.

## WF-03-06 ignition shutdown

Uygulama [`../firmware/repo03_shutdown/engine.py`](../firmware/repo03_shutdown/engine.py), kapalı sözleşme [`../variants/schema/repo03.shutdown.scenario.v1.json`](../variants/schema/repo03.shutdown.scenario.v1.json) dosyasındadır.

Durumlar:

`IGNITION_ON → NOTIFY_PENDING → WAIT_ACK → GRACE_PERIOD → READY_TO_CUT → POWER_CUT → RESTART`

Olaylar:

`ignition-off`, `host-notify`, `ACK`, `timeout`, `cut`, `restart`

Her geçiş; `previous_state`, `event`, `next_state`, `elapsed_time`, `threshold_source`, `status`, `rule_id` ve `reason_code` taşır. Raspberry Pi modeli, host protokolü, ACK timeout, grace period, debounce ve restart minimumu için varsayılan sayı uydurulmaz.

### Fixture sonuçları

| Fixture | Genel durum | Baskın neden | Son durum | Girdi SHA-256 |
| --- | --- | --- | --- | --- |
| `duplicate_ack.json` | `BLOCKED` | `HOST_MODEL_UNRESOLVED` | `POWER_CUT` | `f5efc7c666c425cb7516190c43f08daa1ae3df2e528f59c1dafa8b9d7ab6f3d3` |
| `early_power_cut.json` | `FAIL` | `EARLY_POWER_CUT` | `POWER_CUT` | `5f1bb8f0a315028ce8c406b5305cb899d03dc068c2ed773fd348415d5c14f7cc` |
| `ignition_bounce.json` | `BLOCKED` | `HOST_MODEL_UNRESOLVED` | `WAIT_ACK` | `0e62613ee09b540522c7bfa5620c0d25a25ee61bed90e776111ade40834ca96e` |
| `late_ack.json` | `FAIL` | `LATE_ACK_REJECTED` | `WAIT_ACK` | `465594d6e50a7e8200ff013e421120df1431101adbb9102908793668742de3be` |
| `missing_ack.json` | `BLOCKED` | `HOST_MODEL_UNRESOLVED` | `WAIT_ACK` | `a4365790605b2733482a2d9ca8abd63bea18fea7bc1a4999fa5fa5df778b3ceb` |
| `missing_protocol.json` | `BLOCKED` | `HOST_MODEL_UNRESOLVED` | `WAIT_ACK` | `58d06a5c8fd7688cc740d85a1655fa53dd48d48c9fd2546162d5da40401ab6b4` |
| `normal_ack.json` | `BLOCKED` | `HOST_MODEL_UNRESOLVED` | `POWER_CUT` | `215b392b44d18bf5d0d6687bde9dd728457950092bcc32a97838c884609f030f` |
| `rapid_restart.json` | `BLOCKED` | `HOST_MODEL_UNRESOLVED` | `RESTART` | `bb932203c2630a8f9e01db978eb04effa30cec759b2eae4ffa1201778c9f2516` |

`duplicate ACK`, ignition bounce ve rapid restart kararları ayrı trace neden kodları taşır. Genel sonucun `BLOCKED` olması, bu nedenleri gizlemez; GAP-04'teki eksik host/platform kaynağının daha yüksek engel olduğunu gösterir.

## Otomatik doğrulama

Ortam:

- Python `3.12.10`
- `jsonschema==4.25.1`
- Doğrudan ve transitif test sürümleri `requirements-test.txt` içinde sabit
- Runtime motorları yalnız Python standart kütüphanesini kullanıyor

Yeniden üretim:

```powershell
$testPython = ".\.venv-test\Scripts\python.exe"
python -m venv .venv-test
& $testPython -m pip install --disable-pip-version-check -r requirements-test.txt
$env:PYTHONPATH = "firmware"
& $testPython -B -m unittest discover -s tests -v
$testExit = $LASTEXITCODE
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
exit $testExit
```

24 Ekim 2026 gerçek çalıştırma sonucu:

```text
Ran 174 tests in 4.250s
OK
```

| Test ailesi | Test sayısı | Sonuç |
| --- | ---: | --- |
| D1 varyant sözleşmesi | 18 | `PASS` |
| CAN/TWAI | 30 | `PASS` |
| LIN | 30 | `PASS` |
| GNSS | 33 | `PASS` |
| Automotive power | 29 | `PASS` |
| Ignition shutdown | 22 | `PASS` |
| Draft 2020-12 genel regresyon | 6 | `PASS` |
| Kaynak/kanıt kaydı | 6 | `PASS` |
| Toplam | 174 | `PASS` |

Bağımsız kod ve sözleşme incelemesinde açık blocker/high bulgu kalmamıştır. Shutdown motoru ayrı incelemede `ACCEPTED` olmuş ve 47 bozuk girdi mutasyonu istisnasız, kapalı rapor şemasıyla uyumlu sonuç üretmiştir.

## Ana dosya özetleri

| Dosya | Bayt | SHA-256 |
| --- | ---: | --- |
| `requirements-test.txt` | 133 | `32e7fd1a7ef54c6d16017a34ccdd72f48619c0578fde66735961aad570a7d3f3` |
| `firmware/repo03_contract/validator.py` | 27.624 | `18c65c54a63654c177d693e438b2d83ad03029a978303c0efe9e0017a3b400cf` |
| `firmware/repo03_power/engine.py` | 48.872 | `359e8b3c03ec7256c676b931415c1bbd63139281c27a1163f8ddfb33a9c009b4` |
| `firmware/repo03_shutdown/engine.py` | 37.229 | `91a37eae0eda2855541898603ac2dad0f29d3b1e479ab5e3d44df4b2e7a4c0e8` |
| `variants/schema/repo03.variant.schema.v1.json` | 8.985 | `8d137c7353a4c9b4e12c04d316f8830dc61c84a84a4b783dc0af8330206fb156` |
| `variants/schema/repo03.shutdown.scenario.v1.json` | 11.918 | `eaa4e837fe425b1e24ef2a7f7d69b6e7cba85759448cc5d9360c794217d45581` |
| `tests/test_json_schema_regression.py` | 10.553 | `6a0e6de4412ec93e20408f355b6d800777d806b4a05c4ef1b49d344d850b720d` |
| `tests/test_shutdown_engine.py` | 17.510 | `daf60a8b7d2dae4b5c84ffeefe7cb5664eae59ae6d3db26c5f363544ec71d918` |
| `evidence/source_evidence_register.v1.json` | 19.887 | `746f6f13374a966edcd6f1d8510b035db5e68dbc90b4f3e513ca7a0b186b0f07` |

## Kabul sınırı ve sonraki kritik yol

Oturum 4 yalnız sentetik yazılım sözleşmesi kapsamında kabul edilmiştir. Aşağıdaki iddialar yapılmamıştır:

- gerçek Raspberry Pi işletim sistemi kapanışı veya dosya sistemi güvenliği,
- fiziksel power-cut, ray deşarjı, PGOOD, back-power veya power-down sırası,
- OEM transient dayanımı, exact regulator/protection seçimi,
- bench, RF, EMC, AEC, ISO veya araç uygunluğu,
- canlı REP-02 file API entegrasyonu.

Sonraki en kısa yol, REP-02 `0.4.0` file API çalışma ağacını ayrı olarak stabilize edip değişmez commit/snapshot'a bağlamak; ardından yalnız byte hash ve provenance doğrulayan dar INT-02A dilimini uygulamaktır. Dashboard, DART, waveform simülasyonu, KiCad ve fiziksel uygunluk çalışmaları kritik yol dışında tutulur.
