# North Star — Canonical skills root + full A/B onboard

**LOCKED by John 2026-07-24**  
**Depth:** LITE (ceremony) — objective is multi-surface but plan is already framed in CANONICAL-SKILLS-AND-ONBOARD-PLAN.md  
**Canonical plan (locked):** `CANONICAL-SKILLS-AND-ONBOARD-PLAN.md`

---

## Statement

Build a **single agent-independent skills topology** and a **full guided onboard** so any host (Claude, Grok, Gemini/agy, Anchor) sees the **same** skill set from one **SKILLS_ROOT**, journals always land under each skill for Foundry sleep, friction share-back stays **opt-in fail-closed**, and strangers can clone → run onboard for **Package A (skills-only)** or **Package B (Anchor + skills)** ending in a working environment — Package B starts the Anchor service and places a **local desktop icon**.

## Success criteria

1. **SKILLS_ROOT** is the one truth (`<HOME>/skills/<id>/` on recipients; author keeps Foundry + trio with hub/index). Claude/Grok/Gemini/Anchor are **adapters only** — never “skills live under Claude.”
2. After onboard, Claude, Grok, and Anchor list the **same portfolio skill IDs**.
3. Skill runs write journals only under `SKILLS_ROOT/<skill>/journal/` (human NNNN + machine runs/); ship packages still **deny journal/**.
4. Feedback export **impossible** without explicit opt-in (default off); sanitized allowlist + de-id install key; intake never auto-merges to main.
5. **Package A:** skills + governance + multi-host register + readiness; no Anchor service required.
6. **Package B:** all of A + Anchor install/scaffold + **service running** + **desktop icon** to local dashboard.
7. Interactive onboard (CLI and/or `/onboard`): home picker, Python check/PATH, permissions, seats ≥1 subscription, feedback question — not progress-only silent `onboard.py`.
8. Reuse existing GREEN share modules (`share_onboard`, `share_home_config`, `share_governance`, `share_feedback`, `vendor_skills`, `onboard.install_skills`); **no second distro stack**.
9. No open-source license stamp (rights reserved, per John 2026-07-24).
10. Sandbox transcript of onboard is the honest “what the user sees.”

## Non-goals

- Auto-install every CLI (Claude/agy/Grok) beyond detect + fix links (Python is the hard dependency).
- Merging Foundry + trio monorepos in this effort.
- Auto-merge of recipient friction into skill sources.
- Shipping author journals or personal data.
- Open-source license / public GitHub as a gate for this build.
- Moving Gandalf: already at Foundry `skills/gandalf` (Claude path is junction only).

## Risk taxonomy

| Risk | Mitigation |
|------|------------|
| Host adapters drift | skills_root.json registry + tests per host register |
| Copy vs junction split-brain | Author junction; recipient copy+seal default |
| Second onboard stack | Extend share_onboard / onboard_cli only |
| Service “registered” but not running | W4 acceptance: prove dashboard responds OR honest failure |
| LITE under-planning multi-host | Locked plan document is mandatory input; inclusion test vs criteria |

## Foresight

After this, Foundry sleep can consume author journals + optional intake; collaborators get one `/onboard` story; later hub at `C:\dev\skills` is optional cleanup, not required for GREEN.

## Process depth

**LITE** — single-pass Master Plan + Implementation Plan from locked CANONICAL plan; ≤1 Shark round; then Foreman build.
