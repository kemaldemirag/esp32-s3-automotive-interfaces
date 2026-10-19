# Tests

Test paketi Python `unittest` ile WF-03-01, WF-03-02 ve WF-03-03 kapsamını doğrular.

[`test_variant_contract.py`](test_variant_contract.py) şu WF-03-01 kontrollerini yürütür:

- A/B kapsam yalıtımı,
- birleşik profil, eksik varyant kimliği, bilinmeyen modül ve şema sürümü reddi,
- sızıntı neden kodları, iç içe bilinmeyen alanlar ve enum büyük/küçük harf duyarlılığı,
- G1/G2 öncesinde üst seviye ve modül içine gömülü donanım/OEM iddialarının reddi,
- eksik kaynak girdisinin `PASS` yerine `BLOCKED` üretmesi,
- modül ve nesne sırasından bağımsız deterministik profil/girdi özeti.

[`test_can_engine.py`](test_can_engine.py), normal frame, hata artışı, bus-off, recovery başarısı/timeout, transceiver-off, geçersiz sıra, D1 profil bağı ve fiziksel iddia kaçışlarını kapsayan 30 test yürütür.

[`test_lin_engine.py`](test_lin_engine.py), normal wake/frame/sleep, wake timeout, stuck-dominant, eksik/off transceiver, hızlı yeniden uyku, geçersiz sıra, kaynak/eşik izlenebilirliği ve sorumluluk ayrımını kapsayan 30 test yürütür.

Depo kökünden PowerShell ile:

```powershell
$env:PYTHONPATH = "firmware"
python -m unittest discover -s tests -v
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

19 Ekim 2026 tarihinde toplam 75 test `OK` sonucu vermiştir. Bu testler sentetiktir; bench, EMC, AEC, ISO veya saha doğrulaması değildir.
