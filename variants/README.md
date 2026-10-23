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

Oturum 3 sözleşmeleri D2 sentetik uygulamayı tamamlar:

- [`schema/repo03.gnss.scenario.v1.json`](schema/repo03.gnss.scenario.v1.json): GNSS fix/freshness, timestamp, antenna status ve 11 satırlı kaynak matrisi.
- [`fixtures/gnss/`](fixtures/gnss/): yedi pozitif, sınır ve negatif GNSS senaryosu.
- [`schema/repo03.automotive-power.scenario.v1.json`](schema/repo03.automotive-power.scenario.v1.json): Varyant B güç profili ve REP-02 adapter input/report sözleşmesi.
- [`fixtures/automotive_power/`](fixtures/automotive_power/): nominal, transient, eksik kaynak, sürüm uyuşmazlığı ve exact-threshold engeli dahil dokuz senaryo.

GNSS senaryoları tam Varyant A, automotive-power senaryoları tam Varyant B modül kümesini ve ilgili D1 profil özetini zorunlu tutar. GAP-03’te kayıtlı/onaylı OEM kaynağı bulunmadığından, yalnız kendisini `OEM` olarak etiketleyen bir transient kaynağı `PASS` üretemez; exact-part ve gerçek eşik kararları `BLOCKED` kalır.

Oturum 4 WF-03-06 sözleşmesi Varyant B shutdown akışını ayrı bir şema ve fixture kümesi olarak ekler:

- [`schema/repo03.shutdown.scenario.v1.json`](schema/repo03.shutdown.scenario.v1.json): ignition-off, host notification, ACK, timeout, sentetik cut ve restart olayları ile kapalı rapor sözleşmesi.
- [`fixtures/shutdown/`](fixtures/shutdown/): normal ACK, ACK yok, geç ACK, erken power-cut, duplicate ACK, ignition bounce, hızlı restart ve eksik protokol kategorileri.

Shutdown fixture’larında Raspberry Pi modeli, host protokolü ve zaman eşikleri bilerek `null` tutulur. GAP-04 kapanmadığı için sentetik iz oluşsa da güvenli shutdown veya fiziksel power-cut sonucu `PASS` yapılmaz.

Kapı kilidi yalnız üst seviye alanları değil, modül içindeki `value` alanlarını da kapsar: donanıma duyarlı yollar `null`, davranış yolları `null` veya `SYNTHETIC_ONLY` ile sınırlıdır.

Bu dizin herhangi bir parça seçimi, RF uygunluğu veya fiziksel doğrulama iddiası içermez.
