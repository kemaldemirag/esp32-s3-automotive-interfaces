# Evidence

Bu dizin, REP-03 kararlarını ve doğrulama çalışmalarını sohbet geçmişinden bağımsız olarak yeniden üretmeye yarayan kanıt kayıtlarını barındırır.

## Mevcut kayıtlar

- [`D1_validation_record.md`](D1_validation_record.md): D1 geçiş onayı, sentetik çalışma sınırı ve D2/D3 doğrulama durumu.
- [`D2_session2_validation_record.md`](D2_session2_validation_record.md): WF-03-02 CAN/TWAI ve WF-03-03 LIN motorlarının fixture, test, kaynak ve kabul kaydı.
- [`REP-03_Oturum_2_Sentetik_Dogrulama_Raporu_2026-10-19.docx`](REP-03_Oturum_2_Sentetik_Dogrulama_Raporu_2026-10-19.docx): Oturum 2 sonucunu sohbet geçmişinden bağımsız sunan düzenlenebilir teslim raporu.

## Kanıt kuralları

- Test `PASS` durumu yalnızca gerçek komut, tarih ve sonuç kaydedildiğinde kullanılır.
- Çalıştırılmamış veya doğrulanmamış kontrol `NOT_RUN`, `UNKNOWN` ya da `BLOCKED` olarak kalır.
- Sentetik test başarısı fiziksel donanım, EMC, AEC, ISO veya saha uygunluğu kanıtı sayılmaz.
- G1/G2 tamamlanmadan ERC/DRC, PCB, parça seçimi veya bench doğrulama kanıtı beklenmez ve bu konularda başarı iddiası yapılmaz.

Kaynak izli hesaplar, ilerideki ERC/DRC, simülasyon ve bench çıktıları ancak ilgili kapılar açıldıktan ve gerçek araç çıktıları üretildikten sonra bu dizine eklenir.
