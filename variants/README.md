# Variants

REP-03 varyant sözleşmesi iki yalıtılmış profili tanımlar:

- A: `can`, `lin`, `gnss`
- B: `automotive_power`, `shutdown` ve sürümlü REP-02 entegrasyon alanı

Makinece okunabilir temel sözleşme [`schema/repo03.variant.schema.v1.json`](schema/repo03.variant.schema.v1.json), sentetik örnekler ise [`fixtures/`](fixtures/) altındadır. Yapısal olarak geçerli A/B fixture’larının genel sonucu, exact-part/OEM/host kaynakları çözülmediği için bilinçli olarak `BLOCKED` kalır.

Oturum 2 olay sözleşmeleri temel Varyant A sözleşmesine bağlı ayrı şemalardır:

- [`schema/repo03.can.scenario.v1.json`](schema/repo03.can.scenario.v1.json): CAN/TWAI controller olayları, bus-off ve recovery izleri.
- [`schema/repo03.lin.scenario.v1.json`](schema/repo03.lin.scenario.v1.json): LIN sleep/wake/frame olayları, kaynaklı eşikler ve domain izleri.
- [`fixtures/can/`](fixtures/can/): altı pozitif/negatif sentetik CAN senaryosu.
- [`fixtures/lin/`](fixtures/lin/): yedi pozitif/negatif sentetik LIN senaryosu.

Her senaryo tam `can`, `lin`, `gnss` Varyant A modül kümesini ve onaylı profilin SHA-256 özetini taşır. Ek alanlar kapalıdır; parça, gerilim, ölçüm veya fiziksel `PASS` iddiası kabul edilmez.

Kapı kilidi yalnız üst seviye alanları değil, modül içindeki `value` alanlarını da kapsar: donanıma duyarlı yollar `null`, davranış yolları `null` veya `SYNTHETIC_ONLY` ile sınırlıdır.

Bu dizin herhangi bir parça seçimi, RF uygunluğu veya fiziksel doğrulama iddiası içermez.
