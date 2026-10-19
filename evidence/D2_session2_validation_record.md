# REP-03 Oturum 2 sentetik doğrulama kaydı

## Kayıt kimliği

- Proje: `esp32-s3-automotive-interfaces`
- Kayıt tarihi: 19 Ekim 2026
- Başlangıç commit’i: `e48f53c`
- İş akışları: `WF-03-02 CAN/TWAI` ve `WF-03-03 LIN`
- Doğrulama seviyesi: `SYNTHETIC`
- D1 Varyant A profil özeti: `f74c42bb2a2519ab563a91cb05cfb6d4e5accd9d6f2570ed89604bbad5e0367e`
- Kaynak belgeler:
  - `REP-03_Is_Akisi_Raporu_v1.pdf`
  - `REP-03_Codex_Gorev_Plani_Pozisyon_Bazli_v1.docx`
  - `evidence/D1_validation_record.md`

## Sonuç

Oturum 2 kapsamındaki iki sentetik motor tamamlandı. CAN/TWAI motoru controller, external transceiver ve bus gözlemini ayrı alanlarda izler. LIN motoru UART/peripheral, LIN transceiver, bus ve durum makinesi sorumluluklarını ayırır. Her iki motor da tam Varyant A modül kümesini ve onaylı D1 profil özetini zorunlu tutar.

19 Ekim 2026 tarihli bağımsız çalıştırmada 75 testin tamamı geçti. Bu sonuç yalnızca sürümlü sentetik sözleşmelerin ve olay motorlarının teknik davranışını doğrular. Fiziksel CAN/LIN katmanı, exact part, gerilim, ölçüm, EMC, AEC, ISO veya saha uygunluğu doğrulanmış değildir.

## Durum özeti

| Aşama veya iş akışı | Durum | Kanıt sınırı |
| --- | --- | --- |
| D1 varyant sözleşmesi | `APPROVED_TO_PROCEED` | Varyant A profil özeti iki motor tarafından doğrulanır. |
| WF-03-01 | `COMPLETE` | 15 sözleşme testi geçti. |
| WF-03-02 CAN/TWAI | `COMPLETE_SYNTHETIC` | 30 motor ve kaçış testi geçti. |
| WF-03-03 LIN | `COMPLETE_SYNTHETIC` | 30 FSM, kaynak ve kaçış testi geçti. |
| D2 sentetik uygulama | `IN_PROGRESS_SESSION_2_COMPLETE` | Oturum 3 kapsamı henüz başlamadı. |
| G1 gereksinim ve kaynak kapanışı | `BLOCKED` | Exact transceiver ve fiziksel katman kaynakları açık. |
| G2 donanım tasarım başlangıcı | `NOT_STARTED` | G1 kapanmadan şema veya PCB çalışması yapılmaz. |

## Teslim edilen teknik içerik

### WF-03-02 CAN/TWAI

- `firmware/repo03_can/engine.py`: standart kütüphane tabanlı deterministik olay motoru.
- `variants/schema/repo03.can.scenario.v1.json`: kapalı input, trace ve report sözleşmesi.
- `variants/fixtures/can/`: normal frame, hata artışı ve recovery, recovery timeout, missing recovery, transceiver-off ve invalid order fixture’ları.
- `tests/test_can_engine.py`: 30 otomatik test.
- Olaylar: `NORMAL_FRAME`, `ERROR_COUNTER_UPDATE`, `BUS_OFF`, `RECOVERY_REQUEST`, `RECOVERY_COMPLETE`, `RECOVERY_TIMEOUT`, `TRANSCEIVER_OFF`.
- Her trace satırı previous/next state, controller/transceiver/bus alanları, sayaçlar, elapsed/timeout, threshold source, status, `rule_id` ve `reason_code` taşır.

### WF-03-03 LIN

- `firmware/repo03_lin/engine.py`: standart kütüphane tabanlı deterministik FSM.
- `variants/schema/repo03.lin.scenario.v1.json`: kapalı input, trace ve report sözleşmesi.
- `variants/fixtures/lin/`: normal wake/frame/sleep, wake timeout, stuck-dominant, missing transceiver, off transceiver, rapid re-sleep ve invalid order fixture’ları.
- `tests/test_lin_engine.py`: 30 otomatik test.
- Durumlar: `sleep`, `wake-request`, `awake`, `frame-wait`, `timeout`, `stuck-dominant`, `fault`.
- Wake olayları `wake_source`; dominant bus olayı ayrı `observation_duration_ms`; karar veren her eşik kaynak referansı ve sürüm taşır.
- UART, transceiver ve bus gözlem alanları yalnız kendi domain olaylarıyla değişir.

## Fixture çalıştırma kaydı

| Motor | Fixture | Durum | Neden kodu | Girdi SHA-256 |
| --- | --- | --- | --- | --- |
| CAN | `error_escalation_recovery_success.json` | `PASS` | `SYNTHETIC_ERROR_STATE_UPDATED` | `bbae95456685e5f0a60e8ed5b19b65cebe13df41c250b67d43832ca0fbaa7b35` |
| CAN | `invalid_sequence.json` | `FAIL` | `RECOVERY_COMPLETE_WITHOUT_REQUEST` | `eb5c74d0182765eb6ac47b3596d85cdc27d73cc8fac66f78e5751a65f908bc39` |
| CAN | `missing_recovery.json` | `FAIL` | `RECOVERY_NOT_REQUESTED` | `9936244004f14e0da07fbe77c77d69e342c6d25e68e287016cc8ca80214bea40` |
| CAN | `normal_frame.json` | `PASS` | `SYNTHETIC_CONTROLLER_FRAME_ACCEPTED` | `f1cd93eca554135af9f2958e003cb1242b95df43e14055ed9999af6d9a9aa2f2` |
| CAN | `recovery_timeout.json` | `FAIL` | `RECOVERY_TIMEOUT_EXCEEDED` | `2e66c1cbcd64794764e6e9bcb328cc7488327bf1caa420b78a51e026a37dac34` |
| CAN | `transceiver_off_unknown.json` | `BLOCKED` | `GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED` | `5e42629047577f10f5705e527709f4f6c7f4ba8fc1bcc3a0ccfcf6a63e04c684` |
| LIN | `invalid_order.json` | `FAIL` | `INVALID_EVENT_ORDER` | `4b18d70e866430da3160d9a73a2ac0b52932e21305e334aa65f945bc3cd22b96` |
| LIN | `missing_transceiver_profile.json` | `BLOCKED` | `TRANSCEIVER_PROFILE_MISSING` | `a7764480858d041d639dd3b4012059e276457a95d90efbc4e1bb6ba935f4f4b0` |
| LIN | `normal_wake_sleep.json` | `PASS` | `LIN_SCENARIO_COMPLETED` | `c21b24e9522bbf40e085f6a632b8b07bb0aa79b473cd46e82401cd2f5e7ac501` |
| LIN | `off_transceiver.json` | `BLOCKED` | `TRANSCEIVER_UNAVAILABLE` | `be57995bde37e95aa5f33d737f4698eed80200b295f1590fdf488e5838efb002` |
| LIN | `rapid_re_sleep.json` | `FAIL` | `RAPID_RE_SLEEP` | `55ea517cf1f3676e2163a02c9a369603631a24aa473b698c22e63f52e7a22150` |
| LIN | `stuck_dominant.json` | `FAIL` | `STUCK_DOMINANT` | `b07790345d1b547539afe07eaf908be64ac38822942d3267dc505926e904523d` |
| LIN | `wake_timeout.json` | `FAIL` | `WAKE_TIMEOUT` | `8ec7fa7284ef8cf47b6aaa98ab6ac10ff3b577b3cadb2ad87673f6079f0279be` |

Negatif fixture’ların `FAIL` veya `BLOCKED` üretmesi beklenen kabul davranışıdır; test paketi bu sonuçları başarıyla doğrular.

## Otomatik test kaydı

- Tarih/saat: `2026-10-19 14:49:42 +03:00`
- Python sürümü: `3.12.14`
- Toplam test: `75`
- Sonuç: `75/75 OK`
- Dağılım: WF-03-01 `15`, WF-03-02 `30`, WF-03-03 `30`
- Komut: `$env:PYTHONPATH='firmware'; python -B -m unittest discover -s tests -v`

Ek doğrulamalar:

- Tüm Python kaynakları bytecode yazmadan derlendi.
- Tüm JSON şema ve fixture dosyaları ayrıştırıldı; iç `$ref` hedefleri denetlendi.
- Aynı canonical girdi aynı SHA-256, trace ve raporu üretti.
- Yanlış tipli fakat JSON-geçerli girdiler istisna yerine açıklamalı `FAIL` raporu üretti.
- `git diff --check` ve satır sonu/whitespace denetimi temiz sonuç verdi.

## Bağımsız kabul bulgularının kapanışı

- CAN ve LIN motorlarında tam `can`, `lin`, `gnss` Varyant A kümesi zorunlu hale getirildi.
- İki motor da D1 Varyant A profilinin sabit SHA-256 özetini doğruluyor.
- CAN `known_gaps` girdisi yalnız benzersiz `GAP-01` değerini kabul ediyor.
- LIN missing/off transceiver senaryoları input şemasında temsil ediliyor ve `BLOCKED` üretiyor.
- LIN bus/timer/state-control olayları transceiver gözlemi gibi raporlanmıyor.
- CAN controller sonucu, external transceiver engeliyle karıştırılmıyor.
- Varsayımsal veya çözümsüz kaynaklar genel `PASS` içinde kaybolmuyor.
- Input ve output sözleşmeleri ek alanlara kapalıdır; fiziksel parça, gerilim, ölçüm ve uygunluk iddiaları reddedilir.

## Donanım ve uygunluk sınırı

`GAP-01` açıktır. External CAN/LIN transceiver kimliği, güç kontrolü ve exact power-off davranışı doğrulanmış değildir. Aşağıdaki sonuçlar bu kayıtla kanıtlanmış sayılmaz:

- fiziksel CAN veya LIN haberleşmesi,
- transceiver exact part seçimi veya elektriksel eşikler,
- bus voltajı, timing, EMC, transient veya bench ölçümü,
- AEC, ISO veya saha uygunluğu,
- KiCad şeması, PCB, ERC veya DRC sonucu.

Normal frame, recovery veya UART/frame `PASS` değerleri yalnız ilgili sentetik controller/peripheral kuralının geçtiğini gösterir. Fiziksel transceiver ve bus iddiaları `UNKNOWN` veya `BLOCKED` kalır.

## Tekrar üretim

Depo kökünde harici paket kurmadan:

```powershell
$env:PYTHONPATH = "firmware"
python -B -m unittest discover -s tests -v
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

## Sonraki planlı kapsam

Oturum 3, `WF-03-04 GNSS` validator ve kaynak matrisi ile `WF-03-05 automotive-power` sentetik profillerini kapsar. Bu çalışma D2 sentetik uygulamayı tamamlamayı hedefler; G1/G2 kapıları ayrıca kapanmadıkça donanım tasarımı başlatmaz.

Bu değişiklikler çalışma ağacındadır. Commit veya push yapılmamıştır.
