# SUPERSEDES + REUSE map — Shareable Anchor + Skills

**Status:** W1 contracts (machine-checkable markers in `share_contracts.py`)  
**Scope:** This product cut only. Does not rewrite older plans in place; it supersedes conflicting *product* decisions for Shareable Anchor + Skills.

## Reuse rule (hard)

- **Extend** the GREEN share-distro / shareable stack.  
- **Forbid** a second distro, scrub, or publish path without a **gap-proof ticket**.  
- Foreman wave templates for this effort must cite a **reuse-proof path** (one of the markers below) or a named extension point before new packaging code.

### Machine markers (`share_contracts.REUSE_MARKERS`)

| Marker | Path | Meaning |
|--------|------|---------|
| `reuse:distro` | `distro.py` | deny-by-default manifest + `build_distro` |
| `reuse:vendor_skills` | `vendor_skills.py` | git-archive + denylist + residual scrub; full roster + canary (W2) |
| `reuse:onboard` | `onboard.py` | install / scaffold / token |
| `reuse:registrar` | `anchor/registrar.py` | service unit generators |
| `reuse:publish_distro` | `distro.py` (`publish_distro`) | publish after clean-scan |
| `reuse:clean_scan` | `distro.py` | PersonalDataError gate |
| `reuse:default_deny_auth` | `paths.py` | token auth |
| `reuse:doctor` | `doctor.py` | capability probe / system check |

## SUPERSEDES (this cut)

| Prior decision | Superseded by |
|----------------|---------------|
| share-distro **4-skill-only** roster | Full Trio + Foundry roster via config expansion (W2); baseline APIs frozen |
| ship-anchor **Tailscale / onboard2** in v1 | **Local-only** v1; remote multi-machine deferred by name |
| ship-anchor **Tidy-Idy exclusion** | Tidy-Idy **in** roster (`degraded-without-Anchor`, stub on package A) |
| July topology hand-edited public mirrors | One-way public mirror; bot-only public write (W8) |

## Forbidden without gap-proof

- Re-implementing GREEN security / auth / scrub waves  
- Greenfield second `build_distro` / alternate publish stack  
- Shipping **Anchor-only** packages (blocked by package matrix)  
- Vendoring from dirty live trees mid skill-run (freeze tags + clean-scan)

## Extension points (named; not second stacks)

See `share_brownfield_inventory.json` → `extension_points`:

- `ext:roster_config` — W2 roster config only  
- `ext:package_matrix` — this wave (`share_package_matrix.py`)  
- `ext:capability_matrix` — this wave (`share_capability_matrix.py`)  
- `ext:readiness_stamp` — schema frozen W1; compute/write in `share_readiness.py` (W4); seat probes W5  
- `ext:sources_freeze` — schema frozen; writer + verify_freeze_manifest + publish gates (`share_sources.py`, `share_publish.py`, `verify_freeze_manifest.py`) W3  

- `ext:governance_pack` — W4 (`share_governance.py` + `share_skill_journal.py` + `share_skill_seal.py` + `share_home_config.py`)  
- `ext:feedback_sanitizer` — W6 schema/sanitizer/key/queue (`share_feedback.py`); W7 intake transport (`share_feedback_intake.py`)  
- `ext:onboard_dialog` — W5 dialog extension (`share_onboard.py` extends GREEN `onboard.py`)
- `ext:topology` — W8 dual-audience topology (`share_topology.py`: one-way mirror, CONTRIBUTING, captain checklist)
- `ext:ci_ship_gate` — W9 CI matrices + stranger E2E + execute/ship gate (`share_ci_ship_gate.py`); plan-workspace `SHIP-GATE-CHECKLIST.md` + `FOREMAN-WAVE-TEMPLATE.md`

## Ship gate reminder

**Plan-complete ≠ ship-allowed.** Freeze tags in W1 data files are `PLACEHOLDER` only. Real tags + John go-ahead are required before public ship (NS criterion 8). W9 `share_ci_ship_gate.evaluate_execute_ship_gate` fails closed until concurrent skill-run merge + multi-repo tags + clean-scan + captain sign-off + John go-ahead — live skill-tree vendoring is forbidden until then.
