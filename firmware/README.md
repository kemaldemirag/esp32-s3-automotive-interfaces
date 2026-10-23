# Firmware

Bu dizinde donanımdan bağımsız REP-03 sözleşme ve sentetik olay motorları bulunur:

- [`repo03_contract/validator.py`](repo03_contract/validator.py): A/B kapsam yalıtımı, kaynak durumu, neden kodları ve deterministik SHA-256 özetleri.
- [`repo03_contract/__init__.py`](repo03_contract/__init__.py): kararlı Python API yüzeyi.
- [`repo03_can/engine.py`](repo03_can/engine.py): Varyant A CAN/TWAI controller, transceiver ve bus gözlemini ayrı izleyen sentetik bus-off/recovery motoru.
- [`repo03_lin/engine.py`](repo03_lin/engine.py): Varyant A UART, LIN transceiver ve bus sorumluluklarını ayrı izleyen sentetik sleep/wake/frame FSM’i.
- [`repo03_gnss/validator.py`](repo03_gnss/validator.py): Varyant A fix quality, freshness, timestamp, antenna status ve GAP-02 kaynak matrisini değerlendiren sentetik doğrulayıcı.
- [`repo03_power/engine.py`](repo03_power/engine.py): Varyant B otomotiv güç profillerini ve REP-02 adapter sözleşmesini değerlendiren sentetik motor.
- [`repo03_shutdown/engine.py`](repo03_shutdown/engine.py): Varyant B ignition-off, host notification, ACK, grace-period, sentetik power-cut ve restart akışını GAP-04 fail-closed olarak değerlendiren durum makinesi.

Uygulama yalnızca Python standart kütüphanesini kullanır; `jsonschema` yalnız test bağımlılığıdır. Motorlar fiziksel CAN/LIN/GNSS sürücüsü, transient simülatörü veya gerçek host/power kontrolü değildir. REP-02 motoru bu depoda çalıştırılmaz; transceiver kontrolü, RF ölçümü, güç elektroniği ve donanım firmware’i G1/G2 açılmadan bu kapsamda değildir.
