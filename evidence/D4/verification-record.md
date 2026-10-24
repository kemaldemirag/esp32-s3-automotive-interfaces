# D4 yerel sürüm doğrulama kaydı

## Sonuç

- Yerel doğrulama: `PASS`
- Kayıt zamanı (UTC): `2026-10-24T12:09:28Z`
- Sürüm durumu: `BLOCKED`
- Engeller: `LICENSE_DECISION_REQUIRED`, `REMOTE_CI_NOT_RUN`
- Paket: `esp32-s3-automotive-interfaces==0.1.0`
- Wheel: `dist/esp32_s3_automotive_interfaces-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `83a4935a6347c6ce24299c8c3f9f293fd391482743fee7430dd2b665173a00d6`
- Tam unittest paketi: `207` test, `PASS`
- Test bağımlılıkları: `6` paket / `70b371112639af0da09ee84dce9ac6b0468cdf24ac2e4daf5a2f0c4401602419`
- Kaynak envanteri: `97` dosya
- Git tabanı: `9273237e8e884b3da6cde8271f119434b784b5b8`
- Git durum kaydı: `30` girdi / `5af3dd61f548cd5beaf9115ded9f9974fa259c58a7a197ee3609785cf0e4155d`

Yerel kapı; tam test paketini `python -I -S -B` ile ambient ve user
site-packages alanlarından yalıtır. Exact `requirements-test.txt` dağıtım
sürümleri ve kurulu dosya hashleri ayrıca doğrulanır. Wheel'in ağsız ve
bağımlılıksız temiz kurulumunu, paket
içe aktarmalarını, `repo03` konsol girişini, yedi komut yolunu ve Variant A
raporunun aynı girdide byte-deterministik olmasını doğrular. Bu sonuç uzak
GitHub Actions koşusunun gerçekleştiği veya bir sürümün yayımlandığı anlamına
gelmez.

## Açık kapılar ve iddia sınırı

`GAP-01`, `GAP-02`, `GAP-03` ve `GAP-04` `BLOCKED` kalır. Fiziksel doğrulama,
RF, EMC, AEC yeterliliği, ISO uygunluğu, gerçek Raspberry Pi kapanışı, canlı
adaptör yürütmesi ve uzak CI `NOT_RUN` durumundadır. Sentetik test ve temiz
kurulum sonuçları bu alanlarda donanım, araç veya uygunluk iddiası oluşturmaz.

## Yeniden üretim

Depo kökünden, exact `requirements-test.txt` içeriğinin ayrı bir hedef dizine
kurulduğu yolu zorunlu seçenek olarak vererek çalıştırın:

```powershell
python -m pip install --disable-pip-version-check --no-deps `
  --target <test-dependency-directory> -r requirements-test.txt
python -B scripts/record_d4_evidence.py `
  --wheel <esp32_s3_automotive_interfaces-0.1.0-py3-none-any.whl> `
  --test-dependency-path <test-dependency-directory>
```

`release-manifest.json.sha256` kabul işaretidir ve yalnız kaynaklar koşu boyunca
değişmediyse en son yazılır.
