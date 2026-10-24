# REP-03 dokümantasyonu

Bu dizin; CAN/TWAI, LIN, GNSS, otomotiv güç ve kontrollü kapatma davranışlarının kaynak izli sözleşmeleri için ayrılmıştır. Mevcut uygulama yalnızca sentetik sözleşme, fixture ve test kapsamındadır.

## Aşamalar ve kapılar

| Aşama/kapı | Durum | Kanıt sınırı |
| --- | --- | --- |
| D1 — varyant sözleşmesi | `APPROVED_TO_PROCEED` | Kullanıcının 18 Ekim 2026 tarihli “Devam et” talebi sentetik çalışmaya geçiş onayıdır. |
| D2 — sentetik uygulama | `COMPLETE_SESSION_3` | WF-03-01 sözleşmesi ile WF-03-02 CAN/TWAI, WF-03-03 LIN, WF-03-04 GNSS ve WF-03-05 automotive-power tamamlandı. |
| D3 — test ve kanıt | `SESSION_4_COMPLETE` | WF-03-06, kaynak/kanıt kaydı ve altı şema ailesindeki 44 girdi + 44 rapor için Draft 2020-12 regresyonu tamamlandı; toplam 174 test geçti. |
| INT-02A — REP-02 offline file API | `COMPLETE` | REP-02 `0.5.0` exact wheel SHA'sı, gerçek `validate_file_api_file()` çağrısı, artifact byte hash'i ve sekiz fail-closed vaka doğrulandı; normal paket 191 teste çıktı. |
| D4 / WF-03-07 — CLI, paket ve release kapısı | `LOCAL_PASS_RELEASE_BLOCKED` | Yedi CLI komutu, A/B toplu raporları, wheel package-data ve checkout dışı temiz kurulum yerelde geçti. Lisans kararı ve gerçek uzak CI koşusu eksik; push/release yapılmadı. |
| G1 — gereksinim/kaynak kapanışı | `BLOCKED` | Fiziksel arayüz, RF ve OEM profili kaynakları eksiktir. |
| G2 — donanım tasarım başlangıcı | `NOT_STARTED` | G1 kapanmadan şema/PCB çalışması yapılmaz. |

## Sözleşme ilkeleri

- Her profil açık bir `variant_id` ve şema sürümü taşır.
- A ve B kapsamları karşılıklı yalıtılır; birleşik profil geçersizdir.
- Bilinmeyen modül ve desteklenmeyen şema sürümü reddedilir.
- Eksik doğrulama girdisi `UNKNOWN` veya `BLOCKED` üretir; varsayımsal başarı üretilmez.
- Her karar makinece okunabilir `rule_id` ve `reason_code` ile açıklanır.
- Girdi/profil özeti ve araç sürümü tekrar üretilebilir kanıta eklenir.
- G1/G2 kapalıyken donanıma duyarlı değerler `null` kalır; sentetik davranış alanlarında yalnız `SYNTHETIC_ONLY` işaretçisi kullanılabilir.
- CAN ve LIN senaryoları tam Varyant A modül kümesini ve onaylı D1 profil özetini taşır.
- Kaynağı eksik, çelişkili veya varsayımsal eşikler genel sonucu `PASS` yapamaz.
- Controller/UART sonucu, transceiver veya fiziksel bus başarısı olarak yorumlanmaz.
- GNSS fix sonucu anten veya RF yerleşim uygunluğu olarak yorumlanmaz; GAP-02 ayrı bağımlılık olarak raporlanır.
- Automotive-power sonuçları tam Varyant B sözleşmesine bağlıdır; GAP-03 açıkken exact-part ve gerçek transient eşikleri `BLOCKED` kalır.
- Shutdown sonuçları tam Varyant B sözleşmesine bağlıdır; GAP-04 açıkken sentetik ACK, timeout ve cut izleri gerçek host kapanışı veya fiziksel güç kesme kanıtı sayılmaz.
- Tarihsel D2 REP-02 capability map uyumluluğu, canlı REP-02 entegrasyonu veya motor çalıştırması anlamına gelmez.
- INT-02A `PASS`, yalnız pinli REP-02 file-API sözleşmesi ve exact artifact byte bütünlüğüdür; REP-02 `adapter_results=NOT_RUN`, semantik mapping ve güç motoru yürütmesi `false` kalır.
- D4 `LOCAL_PASS`, yalnız CLI, paket içeriği ve yerel temiz-kurulum kapısıdır; uzak CI, lisanslama, yayımlama veya fiziksel ürün kabulü değildir.
- Lisans metni ve SPDX ifadesi kullanıcı kararı olmadan uydurulmaz. Uzak workflow gerçekten çalışmadan CI sonucu `NOT_RUN` kalır.

## Varyant sınırları

**Varyant A’ya özgü:** CAN/TWAI olayları, LIN durum makinesi ve GNSS doğrulaması.

**Varyant B’ye özgü:** otomotiv güç profilleri ve ignition kontrollü Raspberry Pi kapatma durum makinesi.

**Ortak:** şema sürümü, varyant kimliği, kanıt metadatası, doğrulama sonucu ve neden kodları.

## Açık girdiler

- Fiziksel CAN/LIN transceiver davranışı ve exact part bilgisi: `BLOCKED_SOURCE_VERIFICATION`.
- GNSS modül, anten ve RF entegrasyonu: `BLOCKED_SOURCE_VERIFICATION`.
- OEM transient/cold-crank ve ignition profili: `BLOCKED_SOURCE_VERIFICATION`.
- Raspberry Pi modeli ve host shutdown protokolü: `BLOCKED_CLIENT_INPUT`.

Bu girdiler kapanmadan KiCad şeması, PCB, parça seçimi veya fiziksel uygunluk iddiası üretilmez. D2 kapanış kaydı [`../evidence/D2_session3_validation_record.md`](../evidence/D2_session3_validation_record.md), Oturum 4/D3 kaydı [`../evidence/D3_session4_validation_record.md`](../evidence/D3_session4_validation_record.md), INT-02A kabulü [`../evidence/INT-02A/verification-record.md`](../evidence/INT-02A/verification-record.md) dosyasındadır.
