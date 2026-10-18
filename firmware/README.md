# Firmware

Bu dizinde şu anda yalnızca donanımdan bağımsız REP-03 varyant sözleşmesi doğrulayıcısı bulunur:

- [`repo03_contract/validator.py`](repo03_contract/validator.py): A/B kapsam yalıtımı, kaynak durumu, neden kodları ve deterministik SHA-256 özetleri.
- [`repo03_contract/__init__.py`](repo03_contract/__init__.py): kararlı Python API yüzeyi.

Uygulama yalnızca Python standart kütüphanesini kullanır. CAN/LIN/GNSS sürücüleri, fiziksel transceiver davranışı ve donanım firmware’i G1/G2 açılmadan bu kapsamda değildir.
