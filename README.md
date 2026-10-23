# esp32-s3-automotive-interfaces

Durum: **D1_APPROVED / WF-03-01_02_03_04_05_06_COMPLETE / D2_COMPLETE / D3_SESSION_4_COMPLETE / G1_BLOCKED / G2_NOT_STARTED**

Bu depo, REP-03 kapsamında birbirinden yalıtılmış iki ürün varyantının sözleşme ve sentetik doğrulama çalışmalarını barındırır:

- **Varyant A:** ESP32-S3 tabanlı CAN/TWAI, LIN ve GNSS arayüzü.
- **Varyant B:** Raspberry Pi için otomotiv güç ve kontrollü kapatma akışı.

Kullanıcının 18 Ekim 2026 tarihli “Devam et” talebi, D1 varyant sözleşmesini izleyen sentetik uygulama çalışmalarına geçiş onayı olarak kaydedilmiştir. Bu onay donanım tasarımı veya parça seçimi onayı değildir.

## Mevcut çalışma kapsamı

- Standart Python kütüphanesiyle çalışan, sürümlenebilir varyant sözleşmesi ve doğrulayıcı.
- A ve B varyantları için sentetik fixture’lar.
- Varyant sızıntısını, birleşik profil kullanımını ve eksik/geçersiz girdileri sınayan otomatik testler.
- Sonuçların `PASS`, `FAIL`, `UNKNOWN` veya `BLOCKED` olarak, neden kodlarıyla kayda geçirilmesi.
- Varyant A için controller, transceiver ve bus sorumluluklarını ayıran sentetik CAN/TWAI olay motoru.
- Varyant A için UART, LIN transceiver ve bus gözlemlerini ayıran sentetik LIN durum makinesi.
- Varyant A için no-fix, freshness, timestamp ve antenna-fault kurallarını değerlendiren sentetik GNSS doğrulayıcısı.
- Varyant B için kaynak sınıflı otomotiv güç profilleri ve REP-02 sözleşme uyumluluğunu fail-closed değerlendiren sözleşme adaptörü.
- Varyant B için hosttan bağımsız, GAP-04 fail-closed ignition-shutdown durum makinesi.
- Altı şema ailesindeki 44 fixture girdisini ve 44 motor raporunu gerçek Draft 2020-12 doğrulayıcısıyla sınayan regresyon paketi.
- GAP-01–04 kaynak sahipliğini, kapanış ölçütlerini ve fiziksel iddia sınırlarını tek dosyada tutan kaynak/kanıt kaydı.

WF-03-01 sözleşme dilimi tamamlanmıştır. Şema, doğrulayıcı, yedi fixture ve 15 test için başlangıç noktaları:

- [`variants/schema/repo03.variant.schema.v1.json`](variants/schema/repo03.variant.schema.v1.json)
- [`firmware/repo03_contract/validator.py`](firmware/repo03_contract/validator.py)
- [`variants/fixtures/`](variants/fixtures/)
- [`tests/test_variant_contract.py`](tests/test_variant_contract.py)

WF-03-02 ve WF-03-03 sentetik motorları da tamamlanmıştır:

- [`firmware/repo03_can/engine.py`](firmware/repo03_can/engine.py) ve [`variants/schema/repo03.can.scenario.v1.json`](variants/schema/repo03.can.scenario.v1.json)
- [`firmware/repo03_lin/engine.py`](firmware/repo03_lin/engine.py) ve [`variants/schema/repo03.lin.scenario.v1.json`](variants/schema/repo03.lin.scenario.v1.json)
- [`variants/fixtures/can/`](variants/fixtures/can/) ve [`variants/fixtures/lin/`](variants/fixtures/lin/)
- [`tests/test_can_engine.py`](tests/test_can_engine.py) ve [`tests/test_lin_engine.py`](tests/test_lin_engine.py)

Her iki motor onaylı D1 Varyant A profilinin deterministik özetine bağlıdır. Kaynaksız veya varsayımsal eşikler sentetik `PASS` üretemez.

WF-03-04 ve WF-03-05 Oturum 3 kapsamında tamamlanmıştır:

- [`firmware/repo03_gnss/validator.py`](firmware/repo03_gnss/validator.py) ve [`variants/schema/repo03.gnss.scenario.v1.json`](variants/schema/repo03.gnss.scenario.v1.json)
- [`firmware/repo03_power/engine.py`](firmware/repo03_power/engine.py) ve [`variants/schema/repo03.automotive-power.scenario.v1.json`](variants/schema/repo03.automotive-power.scenario.v1.json)
- [`variants/fixtures/gnss/`](variants/fixtures/gnss/) ve [`variants/fixtures/automotive_power/`](variants/fixtures/automotive_power/)
- [`tests/test_gnss_validator.py`](tests/test_gnss_validator.py) ve [`tests/test_power_profiles.py`](tests/test_power_profiles.py)

GNSS veri kalitesi sonucu RF uygunluğundan ayrıdır; GAP-02 açıkken `rf_suitability` `BLOCKED` kalır. REP-02 adapter uyumluluğu `PASS` olsa da canlı entegrasyon `BLOCKED`, motor çalıştırması `NOT_RUN` durumundadır.

WF-03-06 Oturum 4 kapsamında tamamlanmıştır:

- [`firmware/repo03_shutdown/engine.py`](firmware/repo03_shutdown/engine.py) ve [`variants/schema/repo03.shutdown.scenario.v1.json`](variants/schema/repo03.shutdown.scenario.v1.json)
- [`variants/fixtures/shutdown/`](variants/fixtures/shutdown/) altında sekiz zorunlu fixture kategorisi
- [`tests/test_shutdown_engine.py`](tests/test_shutdown_engine.py)
- [`evidence/source_evidence_register.v1.json`](evidence/source_evidence_register.v1.json)

Raspberry Pi modeli, onaylı host protokolü ve kaynaklı zaman eşikleri sağlanmadığı için normal sentetik akış dahil protokole bağlı sonuçlar `BLOCKED` kalır. Sentetik ACK gerçek işletim sistemi kapanışını, sentetik `cut` olayı fiziksel güç kesmeyi kanıtlamaz.

Eksik kaynak veya müşteri girdisi hiçbir zaman varsayımla `PASS` yapılmaz.
G1/G2 açılana kadar donanıma duyarlı `value` alanları zorunlu `null`, davranış alanları ise yalnız `null` veya `SYNTHETIC_ONLY` olabilir.

## Donanım sınırı

G1 ve G2 tamamlanmadan aşağıdaki çalışmalar başlatılmaz:

- KiCad şeması veya PCB yerleşimi,
- fiziksel CAN/LIN transceiver ya da GNSS modül/anten/RF seçimi,
- exact part, otomotiv transient profili veya Raspberry Pi kapanış protokolü hakkında kesin kabul,
- AEC, ISO, EMC, saha uygunluğu ya da fiziksel doğrulama iddiası.

Bu başlıklar doğrulanmış kaynak veya müşteri girdisi gelene kadar `UNKNOWN`/`BLOCKED` kalır.

## Hızlı başlangıç

Komutları depo kök dizininden çalıştırın. Motorların çalışma zamanı yalnız Python standart kütüphanesini kullanır. Tam test paketi gerçek Draft 2020-12 doğrulaması için [`requirements-test.txt`](requirements-test.txt) içindeki sabitlenmiş test bağımlılıklarını gerektirir.

Linux/macOS:

```sh
python -m venv .venv-test
. .venv-test/bin/activate
python -m pip install --disable-pip-version-check -r requirements-test.txt
PYTHONPATH=firmware python -m unittest discover -s tests -v
```

Windows PowerShell:

```powershell
$testPython = ".\.venv-test\Scripts\python.exe"
python -m venv .venv-test
& $testPython -m pip install --disable-pip-version-check -r requirements-test.txt
$env:PYTHONPATH = "firmware"
& $testPython -m unittest discover -s tests -v
$testExit = $LASTEXITCODE
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
exit $testExit
```

WF-03-01 ile WF-03-06, kaynak kaydı ve Draft 2020-12 regresyon kapsamı için 24 Ekim 2026 tarihinde 174 testin tamamı gerçek komut çıktısıyla geçmiştir. Bu sentetik test sonucu donanım, RF veya otomotiv uygunluğu kanıtı değildir. Güncel denetim durumu için [`evidence/D3_session4_validation_record.md`](evidence/D3_session4_validation_record.md) dosyasına bakın.
