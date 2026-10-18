# Variants

REP-03 varyant sözleşmesi iki yalıtılmış profili tanımlar:

- A: `can`, `lin`, `gnss`
- B: `automotive_power`, `shutdown` ve sürümlü REP-02 entegrasyon alanı

Makinece okunabilir sözleşme [`schema/repo03.variant.schema.v1.json`](schema/repo03.variant.schema.v1.json), sentetik örnekler ise [`fixtures/`](fixtures/) altındadır. Yapısal olarak geçerli A/B fixture’larının genel sonucu, exact-part/OEM/host kaynakları çözülmediği için bilinçli olarak `BLOCKED` kalır.

Kapı kilidi yalnız üst seviye alanları değil, modül içindeki `value` alanlarını da kapsar: donanıma duyarlı yollar `null`, davranış yolları `null` veya `SYNTHETIC_ONLY` ile sınırlıdır.

Bu dizin herhangi bir parça seçimi, RF uygunluğu veya fiziksel doğrulama iddiası içermez.
