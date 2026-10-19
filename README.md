# esp32-s3-automotive-interfaces

Durum: **D1_APPROVED / WF-03-01_02_03_COMPLETE / D2_IN_PROGRESS / G1_BLOCKED / G2_NOT_STARTED**

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

Komutları depo kök dizininden çalıştırın. Harici Python paketi gerekmez.

Linux/macOS:

```sh
PYTHONPATH=firmware python -m unittest discover -s tests -v
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "firmware"
python -m unittest discover -s tests -v
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

WF-03-01, WF-03-02 ve WF-03-03 için 75 testin tamamı gerçek komut çıktısıyla geçmiştir. Bu sentetik test sonucu donanım veya otomotiv uygunluğu kanıtı değildir. Güncel denetim durumu için [`evidence/D2_session2_validation_record.md`](evidence/D2_session2_validation_record.md) dosyasına bakın.
