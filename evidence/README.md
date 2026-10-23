# Evidence

Bu dizin, REP-03 kararlarını ve doğrulama çalışmalarını sohbet geçmişinden bağımsız olarak yeniden üretmeye yarayan kanıt kayıtlarını barındırır.

## Mevcut kayıtlar

- [`D1_validation_record.md`](D1_validation_record.md): D1 geçiş onayı, sentetik çalışma sınırı ve D2/D3 doğrulama durumu.
- [`D2_session2_validation_record.md`](D2_session2_validation_record.md): WF-03-02 CAN/TWAI ve WF-03-03 LIN motorlarının fixture, test, kaynak ve kabul kaydı.
- [`REP-03_Oturum_2_Sentetik_Dogrulama_Raporu_2026-10-19.docx`](REP-03_Oturum_2_Sentetik_Dogrulama_Raporu_2026-10-19.docx): Oturum 2 sonucunu sohbet geçmişinden bağımsız sunan düzenlenebilir teslim raporu.
- [`D2_session3_validation_record.md`](D2_session3_validation_record.md): WF-03-04 GNSS ve WF-03-05 automotive-power uygulamalarının D2 kapanış, fixture, kaynak, REP-02 adapter ve kabul kaydı.
- [`REP-03_Oturum_3_D2_Kapanis_Raporu_2026-10-19.docx`](REP-03_Oturum_3_D2_Kapanis_Raporu_2026-10-19.docx): Oturum 3 ve D2 kapanışını sohbet geçmişinden bağımsız sunan düzenlenebilir teslim raporu.
- [`REP-03_23-10-2026_Literatur_Entegrasyon_ve_Bitis_Yolu_Analizi.docx`](REP-03_23-10-2026_Literatur_Entegrasyon_ve_Bitis_Yolu_Analizi.docx): 23 Ekim literatür ve entegrasyon klasörlerini repo gerçekliğiyle karşılaştıran, kısaltılmış bitirme yolunu belirleyen analiz.
- [`source_evidence_register.v1.json`](source_evidence_register.v1.json): GAP-01–04 için kaynak sahipliği, otorite, kapanış ölçütleri ve fiziksel iddia sınırlarını tutan kapalı makine kaydı.
- [`D3_session4_validation_record.md`](D3_session4_validation_record.md): P0 doğruluk düzeltmeleri, WF-03-06 shutdown FSM’i, 44 fixture/rapor şema regresyonu ve 174 testlik Oturum 4 kabul kaydı.

## Kanıt kuralları

- Test `PASS` durumu yalnızca gerçek komut, tarih ve sonuç kaydedildiğinde kullanılır.
- Çalıştırılmamış veya doğrulanmamış kontrol `NOT_RUN`, `UNKNOWN` ya da `BLOCKED` olarak kalır.
- Sentetik test başarısı fiziksel donanım, EMC, AEC, ISO veya saha uygunluğu kanıtı sayılmaz.
- G1/G2 tamamlanmadan ERC/DRC, PCB, parça seçimi veya bench doğrulama kanıtı beklenmez ve bu konularda başarı iddiası yapılmaz.

Kaynak izli hesaplar, ilerideki ERC/DRC, simülasyon ve bench çıktıları ancak ilgili kapılar açıldıktan ve gerçek araç çıktıları üretildikten sonra bu dizine eklenir.
