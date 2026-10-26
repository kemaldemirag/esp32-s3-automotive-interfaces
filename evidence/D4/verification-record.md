# D4 yerel sürüm doğrulama kaydı

## Sonuç

- Yerel doğrulama: `PASS`
- Kayıt zamanı (UTC): `2026-10-26T22:55:29Z`
- Sürüm durumu: `BLOCKED`
- Engeller: `LICENSE_DECISION_REQUIRED`, `REMOTE_CI_PASS_NOT_EVIDENCED`
- Paket: `esp32-s3-automotive-interfaces==0.1.0`
- Wheel: `esp32_s3_automotive_interfaces-0.1.0-py3-none-any.whl`
- Wheel SHA-256: `a22f99e1cb5800b8f5e9ff1700a980d53d10e86408b5f988be29dc5b180c82dc`
- Tam unittest paketi: `207` test, `PASS`
- Test bağımlılıkları: `6` paket / `c16ded7d52c4ca0700c644d4f202b71ffac2676bf4e8a596de8c6b96e56f89bb`
- Kaynak envanteri: `97` dosya
- Git tabanı: `cf4b691e516a9605e1c62fa925efe78345931b76`
- Git durum kaydı: `5` girdi / `aa57b1cc7aec0ecce59b4a62aec644d3b3af3934a09fe373ca805c0573f9972a`

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
RF, EMC, AEC yeterliliği, ISO uygunluğu, gerçek Raspberry Pi kapanışı ve canlı
adaptör yürütmesi `NOT_RUN` durumundadır. Uzak CI başarısı bu yerel kayıtta
kanıtlanmamıştır. Sentetik test ve temiz kurulum sonuçları bu alanlarda donanım,
araç veya uygunluk iddiası oluşturmaz.

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
