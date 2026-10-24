# INT-02A REP-03 → REP-02 offline file-API doğrulama kaydı

## Sonuç

INT-02A, hash'i sabit REP-02 `0.5.0` wheel'i geçici bir ortama yalnız yerel
wheel kullanılarak (`--no-index --no-deps`) kurulmuş ve gerçek
`validate_file_api_file()` public
API'si üzerinden doğrulanmıştır.

- Genel sonuç: `PASS / REP02_FILE_API_EXACT_BYTES_VERIFIED`
- REP-03 taban commit'i: `9273237e8e884b3da6cde8271f119434b784b5b8`
- Wheel: `power_rail_validation-0.5.0-py3-none-any.whl`
- Wheel SHA-256: `27ba10f6e14345c39f70241e56abd67469eb7e8130dc6a0abfdb37ca1a8c5027`
- Artifact: `artifacts/power-nominal-001.report.json`
- Artifact boyutu: `6036` bayt
- Artifact SHA-256: `283b71938deefb22a2cc89192f2193c2f52967224cd5408d63e8d0cae900c256`
- Descriptor input hash: `d4eb1b548689adf7cf7e217310ec1ea631c7a8ec9e4dc01233d2525890d39336`
- REP-02 sonucu: `PASS / FILE_API_DESCRIPTOR_VALID`

## Kanıt sınırı

Bu `PASS` yalnız descriptor yapısı, pinlenmiş sözleşme provenance'ı ve dosyanın
exact-byte SHA-256 bütünlüğü içindir. REP-03 raporunun içindeki tarihsel D2
capability map hâlâ `integration_status=BLOCKED` ve `execution_status=NOT_RUN`
durumundadır. REP-02 `adapter_results` kayıtları da `NOT_RUN` kalır.

Kanıt; semantik güç eşlemesi, REP-02 rail-budget/sequencing motor yürütmesi,
canlı adaptör, gerçek Raspberry Pi kapanışı, fiziksel power-cut, OEM/ISO/AEC,
EMC, RF veya donanım uygunluğu iddiası değildir.

## Negatif doğrulamalar

| Vaka | Gözlenen durum | Zorunlu neden | Sonuç |
| --- | --- | --- | --- |
| `artifact_hash_mismatch` | `BLOCKED` | `ARTIFACT_HASH_MISMATCH` | `PASS` |
| `missing_artifact` | `BLOCKED` | `ARTIFACT_FILE_MISSING` | `PASS` |
| `api_version_mismatch` | `BLOCKED` | `API_VERSION_INCOMPATIBLE` | `PASS` |
| `endpoint_version_mismatch` | `BLOCKED` | `ENDPOINT_API_VERSION_INCOMPATIBLE` | `PASS` |
| `path_traversal` | `BLOCKED` | `PATH_TRAVERSAL_BLOCKED` | `PASS` |
| `malformed_json` | `BLOCKED` | `MALFORMED_JSON` | `PASS` |
| `variant_a_and_combined_profile` | `BLOCKED` | `VARIANT_B_REQUIRED` | `PASS` |
| `wrong_wheel_sha256` | `BLOCKED` | `WHEEL_SHA256_MISMATCH` | `PASS` |

## Yeniden üretim

Depo kökünden:

```powershell
python scripts/verify_int02a_wheel.py `
  --rep02-wheel ..\power-rail-validation-and-review\dist\power_rail_validation-0.5.0-py3-none-any.whl
```

Normal REP-03 test paketi sibling repo veya REP-02 kurulumu gerektirmez. Gerçek
wheel kapısı ayrı çalışır ve wheel yoksa ya da hash uyuşmazsa başarıya düşmez.

## Provenance notu

Dependency kaydı mevcut wheel'in gerçek build kaydını (`b0a823e... + DIRTY`
yalnız `.gitattributes` değişikliği) korur. Güncel incelenen REP-02 kaynak tabanı
`000c884...` olarak ayrıca yazılmıştır; aynı committen yeniden build edilen
wheel'in byte-identical olacağı iddia edilmez. Kabul kimliği exact wheel
SHA-256'sıdır.
