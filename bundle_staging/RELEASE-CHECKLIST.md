# Release Checklist

This checklist gates each release. It must be completed prior to shipping.

- [ ] **All machine gates green**: CI, tests, and acceptance suites pass without errors.
- [ ] **External red-team pass**: One external red-team pass per release cycle against the staged bundle. The pass must cover:
  - Claim flow
  - Pairing flow
  - WS upgrade
  - Control channel
  - Exposure refusals
- [ ] **Triage findings**: All external red-team findings triaged to closure before ship.
- [ ] **Human spot-check**: Asynchronous human spot-check of the staged bundle as a deliberate release act (not per-commit).
- [ ] **Tagging**: SSH-signed release tags (`gpg.format=ssh`) created author-side.
- [ ] **Release Mapping**: `release-map.json` recording (source SHA → release SHA) updated at tag time.
