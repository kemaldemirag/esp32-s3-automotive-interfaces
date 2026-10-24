# Firmware

Bu dizinde donanımdan bağımsız REP-03 sözleşme ve sentetik olay motorları bulunur:

- [`repo03_contract/validator.py`](repo03_contract/validator.py): A/B kapsam yalıtımı, kaynak durumu, neden kodları ve deterministik SHA-256 özetleri.
- [`repo03_contract/__init__.py`](repo03_contract/__init__.py): kararlı Python API yüzeyi.
- [`repo03_can/engine.py`](repo03_can/engine.py): Varyant A CAN/TWAI controller, transceiver ve bus gözlemini ayrı izleyen sentetik bus-off/recovery motoru.
- [`repo03_lin/engine.py`](repo03_lin/engine.py): Varyant A UART, LIN transceiver ve bus sorumluluklarını ayrı izleyen sentetik sleep/wake/frame FSM’i.
- [`repo03_gnss/validator.py`](repo03_gnss/validator.py): Varyant A fix quality, freshness, timestamp, antenna status ve GAP-02 kaynak matrisini değerlendiren sentetik doğrulayıcı.
- [`repo03_power/engine.py`](repo03_power/engine.py): Varyant B otomotiv güç profillerini ve REP-02 adapter sözleşmesini değerlendiren sentetik motor.
- [`repo03_shutdown/engine.py`](repo03_shutdown/engine.py): Varyant B ignition-off, host notification, ACK, grace-period, sentetik power-cut ve restart akışını GAP-04 fail-closed olarak değerlendiren durum makinesi.
- [`repo03_integration/rep02_file_api.py`](repo03_integration/rep02_file_api.py): nominal Varyant B raporunu exact-byte artifact ve gerçek REP-02 file-API descriptor'ına dönüştüren INT-02A handoff katmanı.
- [`repo03_integration/rep02_dependency.v1.json`](repo03_integration/rep02_dependency.v1.json): kabul edilen REP-02 wheel, paket, API, schema ve sözleşme hashlerini sabitleyen dependency kaydı.
- [`repo03_cli/cli.py`](repo03_cli/cli.py): public motor API'lerini çağıran, strict JSON girdi ve kanonik JSON çıktı sözleşmeli yedi komutlu D4 CLI yüzeyi.
- [`repo03_cli/report.py`](repo03_cli/report.py): Varyant A ve B'nin exact modül kümelerini ayrı tutan deterministik `repo03.variant-report.v1` toplu raporu.

Normal uygulama yalnızca Python standart kütüphanesini kullanır; `jsonschema` yalnız test bağımlılığıdır. `pyproject.toml`, sekiz `repo03_*` paketini wheel'e alır; runtime dosyası olarak yalnız `repo03_integration/rep02_dependency.v1.json` eklenir. INT-02A'nın ayrı kabul betiği, hash'i sabit REP-02 wheel'ini geçici ortama `--no-index --no-deps` ile kurar ve yalnız public file API'yi çağırır. Motorlar fiziksel CAN/LIN/GNSS sürücüsü, transient simülatörü veya gerçek host/power kontrolü değildir. REP-02 rail-budget/sequencing motoru çalıştırılmaz; transceiver kontrolü, RF ölçümü, güç elektroniği ve donanım firmware'i G1/G2 açılmadan bu kapsamda değildir.
