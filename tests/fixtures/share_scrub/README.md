# Share scrub dual fixtures (W2)

| Fixture | Purpose | Clean-scan |
|---------|---------|------------|
| `planted_leak/` | Absolute author host path + secret-shaped token | **MUST FAIL** |
| `planted_legit/` | Legitimate relative skill-prose paths only | **MUST PASS** |

`planted_leak` is intentionally **not** listed in `dist_manifest.txt` (same
convention as `tests/fixtures/planted_secret/`). Tests stage these trees into
temp exports; they never ship in a real distro.
