# Brownfield inventory — GREEN modules + NS gap map

**Machine source of truth:** `share_brownfield_inventory.json` (validated by `share_contracts.validate_brownfield_inventory`).  
**North Star:** `NORTH-STAR.md` criteria 1–9.

## Path + claim table (GREEN)

| Module | Path | Claims (summary) | Reuse marker | NS |
|--------|------|------------------|--------------|-----|
| distro | `distro.py` | deny-by-default manifest; `build_distro`; PII/host-path/secret scan; `PersonalDataError` | `reuse:distro` | 1,3,7,8 |
| vendor_skills | `vendor_skills.py` | git archive; denylist; residual scrub; SOURCES.md; full declared-suite roster + canary (W2) | `reuse:vendor_skills` | 1,3,8 |
| onboard | `onboard.py` | skills install refuse-dont-clobber; scaffold; token; service register seam | `reuse:onboard` | 2,4,5,6 |
| registrar | `anchor/registrar.py` | NSSM / systemd / launchd units | `reuse:registrar` | 6 |
| publish_distro | `distro.py` | `publish_distro` — scan then push | `reuse:publish_distro` | 1,3,8 |
| scrub / clean-scan | `distro.py` | clean-scan gate aborts leaky builds | `reuse:clean_scan` | 3,7 |
| default-deny auth | `paths.py` | `auth_ok` / token / cookie auth | `reuse:default_deny_auth` | 7 |
| doctor | `doctor.py` | `run_doctor`; CLI capability probe | `reuse:doctor` | 1,6 |

## NS criterion → GREEN or extension (gap map)

| NS # | Title | GREEN | Extension points |
|------|-------|-------|------------------|
| 1 | Dual packages, coupling | distro, vendor_skills | package_matrix, capability_matrix, roster_config |
| 2 | Dual audience | onboard | onboard_dialog; topology (`share_topology.py` W8) |
| 3 | No-leak distro | distro, vendor_skills, clean-scan | sources_freeze, roster_config |
| 4 | Plain-English onboard | onboard, doctor | onboard_dialog (`share_onboard.py`), readiness_stamp |
| 5 | Governance travels | — | governance_pack (W4) |
| 6 | Works-on-arrival | onboard, registrar, doctor | onboard_dialog, readiness_stamp |
| 7 | No safety regression | auth, distro, clean-scan | — (reuse only) |
| 8 | Plan now, ship after freeze | vendor_skills, publish_distro | sources_freeze, package_matrix |
| 9 | Opt-in friction feedback | — | feedback_sanitizer (W6 share_feedback / W7 share_feedback_intake) |

Every criterion maps to at least one GREEN module **or** a named extension point — proven by unit tests on the inventory JSON.

## Architecture note (extension-only)

Later waves may touch **only**:

1. Roster config on `vendor_skills.SKILL_SOURCES` (not archive/scrub rewrite)  
2. Denylist / residual scrub rule expansion  
3. Onboard dialog steps on `onboard.py`  
4. Governance pack generator (new, export-only)  
5. Feedback subsystem hooks (new, fail-closed)  
6. Package matrix / capability / freeze validators (W1)  
7. SOURCES writer + publish gates + verify_freeze_manifest (W3: `share_sources.py`, `share_publish.py`, `verify_freeze_manifest.py`)  
8. Dual-audience topology + CONTRIBUTING + captain checklist (W8: `share_topology.py`)  
9. CI matrices + stranger E2E + execute/ship gate (W9: `share_ci_ship_gate.py`)

**No greenfield distro rewrite.**
