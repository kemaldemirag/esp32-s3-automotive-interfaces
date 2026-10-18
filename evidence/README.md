# Evidence

Bu dizin, REP-03 kararlarını ve doğrulama çalışmalarını sohbet geçmişinden bağımsız olarak yeniden üretmeye yarayan kanıt kayıtlarını barındırır.

## Mevcut kayıt

- [`D1_validation_record.md`](D1_validation_record.md): D1 geçiş onayı, sentetik çalışma sınırı ve D2/D3 doğrulama durumu.

## Kanıt kuralları

- Test `PASS` durumu yalnızca gerçek komut, tarih ve sonuç kaydedildiğinde kullanılır.
- Çalıştırılmamış veya doğrulanmamış kontrol `NOT_RUN`, `UNKNOWN` ya da `BLOCKED` olarak kalır.
- Sentetik test başarısı fiziksel donanım, EMC, AEC, ISO veya saha uygunluğu kanıtı sayılmaz.
- G1/G2 tamamlanmadan ERC/DRC, PCB, parça seçimi veya bench doğrulama kanıtı beklenmez ve bu konularda başarı iddiası yapılmaz.

Kaynak izli hesaplar, ilerideki ERC/DRC, simülasyon ve bench çıktıları ancak ilgili kapılar açıldıktan ve gerçek araç çıktıları üretildikten sonra bu dizine eklenir.
