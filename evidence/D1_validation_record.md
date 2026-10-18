# REP-03 D1 doğrulama kaydı

## Kayıt kimliği

- Proje: `esp32-s3-automotive-interfaces`
- Kayıt tarihi: 18 Ekim 2026
- İş akışı: `WF-03-01`
- Kapsam: varyant sözleşmesi, sentetik fixture’lar ve otomatik testler
- Kaynak belgeler:
  - `REP-03_Is_Akisi_Raporu_v1.pdf`
  - `REP-03_Codex_Gorev_Plani_Pozisyon_Bazli_v1.docx`
  - `REP-03_D1_Varyant_Sozlesmesi_Inceleme_Matrisi_2026-10-17.xlsx`

## Onay ve yorum

Kullanıcının 18 Ekim 2026 tarihli “Devam et” talebi, D1 varyant sözleşmesi incelemesinden sonra D2 sentetik uygulamaya geçme onayı olarak yorumlanmıştır.

Bu onayın sınırı:

- sürümlü, makinece doğrulanabilir varyant sözleşmesi,
- Varyant A ve Varyant B için sentetik fixture’lar,
- birleşik/geçersiz profil ve varyant sızıntısı testleri,
- kaynak eksikliğini `UNKNOWN`/`BLOCKED` olarak raporlayan doğrulama kayıtlarıdır.

Bu onay, G1/G2 kapılarını açmaz; fiziksel bileşen seçimi, KiCad şeması, PCB yerleşimi veya otomotiv uygunluk iddiası için yetki ya da kanıt oluşturmaz.

## Durum özeti

| Aşama/kapı | Durum | Açıklama |
| --- | --- | --- |
| D1 | `APPROVED_TO_PROCEED` | Sentetik sözleşme kapsamına geçiş onaylandı. |
| D2 | `IN_PROGRESS` | WF-03-01 şema/doğrulayıcı/fixture dilimi tamamlandı; sonraki sentetik motorlar başlamadı. |
| D3 | `WF-03-01_PASS` | Sözleşme dilimindeki 15 test gerçek komutla geçti. |
| G1 | `BLOCKED` | Kaynak/müşteri girdileri kapanmadı. |
| G2 | `NOT_STARTED` | G1 kapanmadan donanım tasarımı başlamaz. |

## D1/D2 doğrulama hedefleri

- [x] Varyant A profili yapısal olarak kabul edilir, yalnızca A modüllerini açar ve çözülmemiş kaynaklarla `BLOCKED` kalır.
- [x] Varyant B profili yapısal olarak kabul edilir, yalnızca B modüllerini açar ve çözülmemiş kaynaklarla `BLOCKED` kalır.
- [x] A+B birleşik profil `FAIL` olur.
- [x] Eksik `variant_id` `FAIL` olur.
- [x] Bilinmeyen modül `FAIL` olur.
- [x] Desteklenmeyen şema sürümü `FAIL` olur.
- [x] Eksik kaynak/müşteri girdisi sahte `PASS` yerine `UNKNOWN` veya `BLOCKED` üretir.
- [x] Aynı profil aynı deterministik özeti üretir.
- [x] A/B sızıntıları ayrı neden kodlarıyla raporlanır.
- [x] JSON Şema ile uyumsuz iç içe alanlar ve enum yazımları `FAIL` olur.
- [x] G1/G2 öncesinde exact-part, RF, OEM transient, şema veya PCB taşıyabilecek tüm `hardware` içeriği `FAIL` olur.
- [x] Exact-part/RF iddiası modül `value` alanına, OEM profil verisi sentetik olay alanına gömülse bile `FAIL` olur.

İşaretler 18 Ekim 2026 tarihindeki gerçek test çalıştırması incelendikten sonra tamamlanmıştır.

## Tekrar üretim komutu

Depo kök dizininden, harici paket kurmadan:

Linux/macOS:

```sh
PYTHONPATH=firmware python -m unittest discover -s tests -v
```

Windows PowerShell:

```powershell
$env:PYTHONPATH = "firmware"
python -m unittest discover -s tests -v
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

## Test çalıştırma kaydı

- Durum: `WF-03-01_PASS`
- Tarih/saat: `2026-10-18 19:20:25 +03:00`
- Python sürümü: `3.12.14`
- Test sayısı: `15`
- Sonuç: `15/15 OK`
- Komut: `$env:PYTHONPATH='firmware'; python -m unittest discover -s tests -v`
- Ek denetimler: tüm şema/fixture JSON dosyaları ayrıştırıldı; `git diff --check` temiz.

Geçerli A ve B fixture’ları sözleşme sınırını doğrular; çözülmemiş fiziksel kaynaklar nedeniyle beklenen genel durumları `BLOCKED` değeridir. Bu kayıt yalnızca WF-03-01 sözleşme dilimi için `PASS` belirtir; REP-03’ün diğer sentetik motorları ve hiçbir fiziksel doğrulama kapsamda değildir.

Son salt-okunur kalite denetiminde dokuz donanıma duyarlı yol ve beş sentetik davranış yolu ayrı ayrı kaçış payloadlarıyla sınandı. Donanım yollarının tamamı `GATE_LOCKED_VALUE_PRESENT`, davranış yollarının tamamı `NON_SYNTHETIC_VALUE_FORBIDDEN` gerekçesiyle `FAIL` üretti; yeni yüksek veya orta önem bulgusu kalmadı.

## Donanım ve uygunluk dışlamaları

Aşağıdaki başlıklar bu kayıtla doğrulanmış değildir:

- CAN/LIN fiziksel transceiver ve exact part seçimi,
- GNSS modül/anten/RF entegrasyonu,
- OEM transient, cold-crank veya ignition sayısal profilleri,
- Raspberry Pi modeli ve host shutdown protokolü,
- KiCad şeması, PCB, ERC/DRC, simülasyon veya bench ölçümü,
- AEC, ISO, EMC ya da saha uygunluğu.

Bu başlıklar doğrulanmış kaynak veya müşteri girdisi gelene kadar `UNKNOWN`/`BLOCKED` olarak kalır.
