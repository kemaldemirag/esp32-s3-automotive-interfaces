# REP-03 dokümantasyonu

Bu dizin; CAN/TWAI, LIN, GNSS, otomotiv güç ve kontrollü kapatma davranışlarının kaynak izli sözleşmeleri için ayrılmıştır. Mevcut uygulama yalnızca sentetik sözleşme, fixture ve test kapsamındadır.

## Aşamalar ve kapılar

| Aşama/kapı | Durum | Kanıt sınırı |
| --- | --- | --- |
| D1 — varyant sözleşmesi | `APPROVED_TO_PROCEED` | Kullanıcının 18 Ekim 2026 tarihli “Devam et” talebi sentetik çalışmaya geçiş onayıdır. |
| D2 — sentetik uygulama | `IN_PROGRESS_SESSION_2_COMPLETE` | WF-03-01 sözleşmesi ile WF-03-02 CAN/TWAI ve WF-03-03 LIN motorları tamamlandı. D2, Oturum 3 sonuna kadar açık kalır. |
| D3 — otomatik doğrulama | `WF-03-01_02_03_PASS` | 75 test 19 Ekim 2026 tarihinde geçti; sonuç yalnız sentetik sözleşme ve olay modellerini kapsar. |
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

## Varyant sınırları

**Varyant A’ya özgü:** CAN/TWAI olayları, LIN durum makinesi ve GNSS doğrulaması.

**Varyant B’ye özgü:** otomotiv güç profilleri ve ignition kontrollü Raspberry Pi kapatma durum makinesi.

**Ortak:** şema sürümü, varyant kimliği, kanıt metadatası, doğrulama sonucu ve neden kodları.

## Açık girdiler

- Fiziksel CAN/LIN transceiver davranışı ve exact part bilgisi: `BLOCKED_SOURCE_VERIFICATION`.
- GNSS modül, anten ve RF entegrasyonu: `BLOCKED_SOURCE_VERIFICATION`.
- OEM transient/cold-crank ve ignition profili: `BLOCKED_SOURCE_VERIFICATION`.
- Raspberry Pi modeli ve host shutdown protokolü: `BLOCKED_CLIENT_INPUT`.

Bu girdiler kapanmadan KiCad şeması, PCB, parça seçimi veya fiziksel uygunluk iddiası üretilmez. Oturum 2 doğrulama kaydı [`../evidence/D2_session2_validation_record.md`](../evidence/D2_session2_validation_record.md) dosyasındadır.
