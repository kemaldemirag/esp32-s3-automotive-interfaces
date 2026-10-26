# esp32-s3-automotive-interfaces

Durum: **D1_APPROVED / WF-03-01_02_03_04_05_06_COMPLETE / D2_COMPLETE / D3_SESSION_4_COMPLETE / INT-02A_COMPLETE / D4_LOCAL_PASS_RELEASE_BLOCKED / G1_BLOCKED / G2_NOT_STARTED**

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
- REP-02 `0.5.0` wheel'ini exact SHA-256 ile sabitleyip gerçek `validate_file_api_file()` API'siyle descriptor ve artifact byte bütünlüğünü doğrulayan INT-02A offline handoff'u.
- Mevcut public motorları çağıran yedi komutlu, A/B yüzeylerini ayıran ve kanonik JSON üreten `repo03` CLI'sı.
- Python `firmware/` source-layout wheel paketi, paket içi INT-02A dependency kaydı, temiz-kurulum doğrulayıcısı ve salt-okunur GitHub Actions CI workflow'u.
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

INT-02A ilk entegrasyon dilimi de tamamlanmıştır:

- [`firmware/repo03_integration/rep02_file_api.py`](firmware/repo03_integration/rep02_file_api.py): nominal Varyant B raporunu deterministik byte dizisine ve kapalı REP-02 descriptor'ına dönüştüren bağımsız handoff katmanı.
- [`firmware/repo03_integration/rep02_dependency.v1.json`](firmware/repo03_integration/rep02_dependency.v1.json): REP-02 `0.5.0`, file API `1.0.0`, contract hash'i ve exact wheel hash'ini sabitleyen dependency kaydı.
- [`scripts/verify_int02a_wheel.py`](scripts/verify_int02a_wheel.py): wheel'i yalnız yerel dosyadan `--no-index --no-deps` ile geçici ortama kurup public REP-02 API'sini pozitif ve fail-closed negatif vakalarla çalıştıran kabul kapısı.
- [`evidence/INT-02A/verification-record.md`](evidence/INT-02A/verification-record.md): exact artifact/descriptor hashleri ve sekiz negatif vakanın kabul kaydı.

Bu entegrasyon `PASS` sonucu yalnız offline descriptor ve exact-byte bütünlüğü içindir. Tarihsel D2 capability map `integration_status=BLOCKED` ve `execution_status=NOT_RUN`, REP-02 `adapter_results` ise `NOT_RUN` kalır; rail-budget/sequencing motoru veya canlı adaptör çalıştırılmış sayılmaz.

WF-03-07 / D4'ün yerel yazılım dilimi de tamamlanmıştır:

- [`firmware/repo03_cli/`](firmware/repo03_cli/): `validate`, `can`, `lin`, `gnss`, `automotive-power`, `shutdown` ve `report` komutları.
- [`pyproject.toml`](pyproject.toml): `0.1.0` wheel metadata'sı, `repo03` console entry point'i ve yalnız gerekli INT-02A JSON package-data kaydı.
- [`scripts/verify_d4_release.py`](scripts/verify_d4_release.py): wheel'i kaynak checkout'u dışında `--no-index --no-deps` ile kurup A/B CLI akışlarını ve package-data'yı sınayan yerel kabul kapısı.
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml): unit-test ve wheel-smoke işlerini tanımlayan, publish adımı içermeyen CI taslağı.

Yerel D4 sonucu yazılım/paketleme için `PASS`, dağıtım için `BLOCKED` durumundadır. Lisans seçimi yapılmamıştır; `LICENSE`, SPDX ifadesi ve lisans classifier'ı bilerek eklenmemiştir. `cf4b691` commit'i `main` dalına push edilmiş, GitHub Actions koşusu `40092982367` ise Python 3.10 bağımlılık kurulumundaki uyumsuz `rpds-py` pini nedeniyle `FAILED` olmuştur. Python 3.13 işi 207 testi geçirmiş, wheel-smoke işi atlanmıştır. Bu çalışma ağacındaki pin düzeltmesi uzak CI yeniden çalışıp geçene kadar `REMOTE_CI_FAILED / PENDING_RERUN` kabul edilir; release yapılmamıştır.

Eksik kaynak veya müşteri girdisi hiçbir zaman varsayımla `PASS` yapılmaz.
G1/G2 açılana kadar donanıma duyarlı `value` alanları zorunlu `null`, davranış alanları ise yalnız `null` veya `SYNTHETIC_ONLY` olabilir.

## Donanım sınırı

G1 ve G2 tamamlanmadan aşağıdaki çalışmalar başlatılmaz:

- KiCad şeması veya PCB yerleşimi,
- fiziksel CAN/LIN transceiver ya da GNSS modül/anten/RF seçimi,
- exact part, otomotiv transient profili veya Raspberry Pi kapanış protokolü hakkında kesin kabul,
- AEC, ISO, EMC, saha uygunluğu ya da fiziksel doğrulama iddiası.

Bu başlıklar doğrulanmış kaynak veya müşteri girdisi gelene kadar `UNKNOWN`/`BLOCKED` kalır.

## CLI hızlı başlangıç

Paket kurulumundan sonra `repo03` komutu kullanılır. Kaynak ağacından geçici deneme için `PYTHONPATH=firmware python -m repo03_cli`, wheel kurulumunda ise doğrudan `repo03` eşdeğerdir.

```powershell
repo03 --version
repo03 can --variant A variants/fixtures/can/normal_frame.json
repo03 automotive-power --variant B variants/fixtures/automotive_power/nominal.json
repo03 report --variant A `
  --profile variants/fixtures/valid_variant_a.json `
  --can variants/fixtures/can/normal_frame.json `
  --lin variants/fixtures/lin/normal_wake_sleep.json `
  --gnss variants/fixtures/gnss/valid_synthetic_fix.json
```

İlk iki motor örneği sentetik sözleşme kapsamında `PASS` ve çıkış kodu `0` üretir. Toplu Varyant A raporu, profil kaynak kapıları açık olduğu için bilinçli olarak `BLOCKED` ve çıkış kodu `12` üretir; bu paketleme hatası değildir. Durum/çıkış kodları `PASS=0`, `FAIL=10`, `UNKNOWN=11`, `BLOCKED=12`, `NOT_RUN=13`; CLI/veri/girdi/iç hata/çıktı hataları sırasıyla `64/65/66/70/73` olarak sabittir. `--output` verilmezse kanonik JSON ve tek LF stdout'a yazılır; `INPUT=-` strict UTF-8 JSON'u stdin'den okur.

## Test ve yerel release doğrulaması

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

WF-03-01 ile WF-03-07, kaynak kaydı, Draft 2020-12 regresyonu, INT-02A handoff/kanıt bütünlüğü, CLI ve paketleme politikası için normal paket 207 teste genişletilmiştir. INT-02A'nın gerçek wheel kapısı ayrıca şu komutla çalıştırılır:

```powershell
python scripts/verify_int02a_wheel.py `
  --rep02-wheel ..\power-rail-validation-and-review\dist\power_rail_validation-0.5.0-py3-none-any.whl
```

D4 wheel'i pinli yerel build araçlarıyla oluşturup kaynak checkout'u dışındaki temiz ortamda sınamak için:

```powershell
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
python scripts/verify_d4_release.py `
  --wheel dist\esp32_s3_automotive_interfaces-0.1.0-py3-none-any.whl

python -m pip install --disable-pip-version-check --no-deps `
  --target tmp\d4-test-dependencies -r requirements-test.txt
python -B scripts/record_d4_evidence.py `
  --wheel dist\esp32_s3_automotive_interfaces-0.1.0-py3-none-any.whl `
  --test-dependency-path tmp\d4-test-dependencies
```

`pyproject.toml`, build backend'i için `setuptools==84.0.0` ve `wheel==0.48.0` ister. D4 kayıt aracı testleri ambient/user site-packages alanından yalıtır; exact test dağıtımlarını, kurulu dosya hashlerini, wheel–kaynak/README bağını ve UTC koşu zamanını manifestte saklar. Uzak CI'nin son bilinen sonucu `FAILED` durumundadır; yerel düzeltme ve yerel kanıt, başarılı yeni bir uzak koşu veya yayımlanmış release anlamına gelmez.

Bu sentetik ve offline sonuçlar donanım, RF veya otomotiv uygunluğu kanıtı değildir. Oturum 4 kaydı için [`evidence/D3_session4_validation_record.md`](evidence/D3_session4_validation_record.md), entegrasyon kabulü için [`evidence/INT-02A/verification-record.md`](evidence/INT-02A/verification-record.md), D4 yerel release durumu için [`evidence/D4/verification-record.md`](evidence/D4/verification-record.md) dosyasına bakın.
