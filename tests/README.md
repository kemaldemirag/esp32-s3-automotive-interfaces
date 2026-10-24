# Tests

Test paketi Python `unittest` ile WF-03-01 ile WF-03-07 arasındaki kapsamı, kaynak/kanıt kaydını, Draft 2020-12 şema regresyonunu, INT-02A handoff/kanıt bütünlüğünü ve D4 CLI/paketleme politikasını doğrular.

[`test_variant_contract.py`](test_variant_contract.py) şu WF-03-01 kontrollerini yürütür:

- A/B kapsam yalıtımı,
- birleşik profil, eksik varyant kimliği, bilinmeyen modül ve şema sürümü reddi,
- sızıntı neden kodları, iç içe bilinmeyen alanlar ve enum büyük/küçük harf duyarlılığı,
- G1/G2 öncesinde üst seviye ve modül içine gömülü donanım/OEM iddialarının reddi,
- eksik kaynak girdisinin `PASS` yerine `BLOCKED` üretmesi,
- modül ve nesne sırasından bağımsız deterministik profil/girdi özeti.

[`test_can_engine.py`](test_can_engine.py), normal frame, hata artışı, bus-off, recovery başarısı/timeout, transceiver-off, geçersiz sıra, D1 profil bağı ve fiziksel iddia kaçışlarını kapsayan 30 test yürütür.

[`test_lin_engine.py`](test_lin_engine.py), normal wake/frame/sleep, wake timeout, stuck-dominant, eksik/off transceiver, hızlı yeniden uyku, geçersiz sıra, kaynak/eşik izlenebilirliği ve sorumluluk ayrımını kapsayan 30 test yürütür.

[`test_gnss_validator.py`](test_gnss_validator.py), valid/no-fix, freshness sınırları, timestamp rollback, antenna fault, GAP-02 kaynak matrisi, D1 bağı ve fiziksel iddia kaçışlarını kapsayan 33 test yürütür.

[`test_power_profiles.py`](test_power_profiles.py), dokuz güç profili, kaynak sınıfları, Varyant B bağı, REP-02 sürüm/hash/alan uyumluluğu, keyfi OEM etiketine karşı fail-closed kaynak kapısı ve fiziksel iddia kaçışlarını kapsayan 29 test yürütür.

[`test_shutdown_engine.py`](test_shutdown_engine.py), sekiz zorunlu fixture kategorisi, yedi durum, altı olay, GAP-04 kapısı, kapalı şema, deterministik iz ve fiziksel iddia reddini kapsayan 22 test yürütür.

[`test_json_schema_regression.py`](test_json_schema_regression.py), altı şema ailesinin metasını, 44 fixture girdisini, bunlardan üretilen 44 raporu, şema envanterini ve kapalı nesne davranışını gerçek `Draft202012Validator` ile kapsayan 6 test yürütür.

[`test_source_evidence_register.py`](test_source_evidence_register.py), GAP-01–04 kayıtlarının kapalı, otorite eşlemeli ve fail-closed kalmasını kapsayan 6 test yürütür.

[`test_int02a_handoff.py`](test_int02a_handoff.py), nominal Varyant B raporunun sabit byte/hash vektörünü, descriptor kimliklerini, A/B karışımı ve gerçek-dünya iddiası reddini, tarihsel D2 sınırını, REP-02 dependency pinlerini ve üretilen INT-02A kanıt manifestini kapsayan 17 test yürütür. Bu normal test dosyası REP-02 kurulumu veya sibling repo gerektirmez; gerçek wheel kabulü [`../scripts/verify_int02a_wheel.py`](../scripts/verify_int02a_wheel.py) ile ayrı ve zorunlu bir kapıdır.

[`test_cli.py`](test_cli.py), yedi alt komutu, A/B varyant kapılarını, strict JSON/UTF-8 girdisini, kanonik çıktıyı, atomik dosya yazımını, durum çıkış kodlarını ve iki deterministik toplu raporu kapsayan 12 test yürütür.

[`test_release_packaging.py`](test_release_packaging.py), `pyproject.toml` allowlist'ini, sekiz paketlik source-layout envanterini, console entry point'i ve wheel'e alınan tek runtime JSON kaydını kapsayan 4 test yürütür. Ağır wheel build/clean-install smoke normal unit-test toplamına dahil değildir; [`../scripts/verify_d4_release.py`](../scripts/verify_d4_release.py) ile checkout dışında ayrı çalıştırılır.

Depo kökünden PowerShell ile:

```powershell
$testPython = ".\.venv-test\Scripts\python.exe"
python -m venv .venv-test
& $testPython -m pip install --disable-pip-version-check -r requirements-test.txt
$env:PYTHONPATH = "firmware"
& $testPython -m unittest discover -s tests -v
$testExit = $LASTEXITCODE
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
exit $testExit
```

Test bağımlılıkları [`../requirements-test.txt`](../requirements-test.txt) içinde doğrudan ve transitif sürümleriyle sabitlenmiştir; bunlar firmware çalışma zamanına eklenmez. Güncel normal paket toplam 207 testtir. Gerçek REP-02 wheel kabulü normal toplamdan ayrıdır ve bir pozitif doğrulama ile sekiz negatif fail-closed vaka çalıştırır. D4 clean-install kapısı da ayrıdır; wheel package-data'sını, `pip check` sonucunu, yedi komutu, iki toplu raporu ve byte-determinism'i sınar. D4 kanıt kaydı, `--test-dependency-path` altındaki dağıtımların ad/sürüm allowlist'ini ve RECORD/dosya hashlerini doğrulayıp testleri `python -I -S -B` yalıtımında yeniden çalıştırır. Bu testler sentetik/offline kapsamlıdır; bench, RF, EMC, AEC, ISO veya saha doğrulaması değildir.
