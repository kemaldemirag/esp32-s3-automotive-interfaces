# Firmware

Bu dizinde donanımdan bağımsız REP-03 sözleşme ve sentetik olay motorları bulunur:

- [`repo03_contract/validator.py`](repo03_contract/validator.py): A/B kapsam yalıtımı, kaynak durumu, neden kodları ve deterministik SHA-256 özetleri.
- [`repo03_contract/__init__.py`](repo03_contract/__init__.py): kararlı Python API yüzeyi.
- [`repo03_can/engine.py`](repo03_can/engine.py): Varyant A CAN/TWAI controller, transceiver ve bus gözlemini ayrı izleyen sentetik bus-off/recovery motoru.
- [`repo03_lin/engine.py`](repo03_lin/engine.py): Varyant A UART, LIN transceiver ve bus sorumluluklarını ayrı izleyen sentetik sleep/wake/frame FSM’i.

Uygulama yalnızca Python standart kütüphanesini kullanır. Motorlar fiziksel CAN/LIN sürücüsü değildir; transceiver kontrolü, bus ölçümü ve donanım firmware’i G1/G2 açılmadan bu kapsamda değildir.
