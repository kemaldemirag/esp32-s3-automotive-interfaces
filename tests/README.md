# Tests

[`test_variant_contract.py`](test_variant_contract.py), Python `unittest` ile şu WF-03-01 kontrollerini yürütür:

- A/B kapsam yalıtımı,
- birleşik profil, eksik varyant kimliği, bilinmeyen modül ve şema sürümü reddi,
- sızıntı neden kodları, iç içe bilinmeyen alanlar ve enum büyük/küçük harf duyarlılığı,
- G1/G2 öncesinde üst seviye ve modül içine gömülü donanım/OEM iddialarının reddi,
- eksik kaynak girdisinin `PASS` yerine `BLOCKED` üretmesi,
- modül ve nesne sırasından bağımsız deterministik profil/girdi özeti.

Depo kökünden PowerShell ile:

```powershell
$env:PYTHONPATH = "firmware"
python -m unittest discover -s tests -v
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

Bu testler sentetiktir; bench, EMC, AEC, ISO veya saha doğrulaması değildir.
