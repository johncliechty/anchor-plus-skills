# Agent operating rules (exportable governance pack)

> **Canonical rules for this install.** Thin engine pointers (`CLAUDE.md`,
> `GEMINI.md`) defer here. Skill-behavior tiers live WITH the skills (Foundry
> `AGENTS.md` → Skill tiers). Do not hardcode forever-product model IDs.

## AGENTS.md is the canonical source of truth

In ANY project, treat **`AGENTS.md`** as the canonical, current source of agent
instructions. At the start of work, if an `AGENTS.md` exists at (or above) the
working directory, **read it first**. Per-engine pointer files defer to this
file; keep edits in `AGENTS.md`, not the pointers.

## Long-run progress updates — the 10-minute rule (Status table)

During any long-running background run (trio skills, foundry skills, multi-minute
orchestration), give a progress update **about every 10 minutes**, unprompted,
until it finishes. Arm the cadence at launch; stop only on halt/done.

**Locked standard format — the "Status table".** Every 10-minute update MUST use
this exact shape: a header line `[HH:MM] <run type> · <project>`, a bordered
field/value block, then the `ETA` + `To do` footer. Fixed field order:

```
[HH:MM] <run type, e.g. Foreman build> · <project>
─────────────────────────────────
Summary  <High-level, human-readable summary of what the run is accomplishing>
Effort   <effort/plan name> (<N> waves)
Doing    <the concrete thing happening right now>
Status   <k/N waves · phase>
Tests    <pass ✓ / fail ✗ · last gate note>
Blocker  <none | the blocker; REPORT any death + restart/investigation here>
Procs    <py N · claude N⚠ · node N   (⚠ when a count is elevated)>
Journal  <friction/failures/fixes journaled since the last update · none>
─────────────────────────────────
ETA      <phase ETA → next-wave ETA → whole-run ETA>
To do    <short remaining-work sequence>
```

Rules: lead with the timestamp; **Summary** is a plain-English "what this effort
is FOR" line (goal, not mechanics); include elapsed + ETA + process census every
tick; `Journal` recaps friction/failures/fixes since last tick (`none` when empty).
This block is the ONE canonical definition of the 10-minute status format —
skills POINT here and must not redefine it.

## UNIVERSAL SEATING LAW — prefs → family → subscription CLI

**Every** model seat in trio skills (Crucible / Foreman / researchPrime), foundry
skills, and any new engine MUST resolve seats from **Anchor model prefs** — never
from hard-coded Claude/Gemini/Grok product IDs in skill prose or one-off scripts.

### Resolve order
1. **Primary:** Anchor data-dir `settings.json` fields `default_cli`,
   `coding_family`, `review_family`
2. **Mirror (when prefs change):** `~/.anchor/model_prefs.json`
3. **Env only if still unset:** `CODING_FAMILY` / `REVIEW_FAMILY` /
   `ANCHOR_CODING_FAMILY` / `ANCHOR_REVIEW_FAMILY` / `CROSS_MODEL`
4. **Last resort only:** historical default (coding=claude, review=gemini) —
   a DEFAULT, not a law

### Family → transport (subscription CLIs — NOT API keys for production seats)
| Family | Seat transport (subscription login) | Do NOT use for production seats |
|--------|--------------------------------------|----------------------------------|
| **claude** | `claude` CLI / trio driver `claude` | Anthropic API-key raw backends for skill seats |
| **gemini** | `agy` via trio `gemini-cli` / `agy-dispatch` | bare `gemini` binary; API-style model ids that degrade |
| **grok** | **`grok` CLI `-p`** / trio driver **`grok-cli`** | raw xAI HTTP + API key for production skill seats |

- **coding_family** → code / reason / orchestrate / synthesize / execute / fix
- **review_family** → adversarial review / Shark / judge / refuter / debate
- Same family on coding + review is **allowed** — stamp `cross_model:false` honestly
- Heavy = frontier of that family; regular = one notch below
- **Never hardcode forever-product model IDs**

## Skill immutability vs Foundry edit path

> Required marker phrase (machine check): **skill immutability**

- **Consumer default:** vendored skills are **read-only by intent** (skill immutability). Local edits
  stay local and do not flow back to upstream.
- **Immutability seal:** post-onboard checksum/manifest of the vendored skill
  tree. Local edits yield a **degraded forked** status and **block feedback
  export** until re-vendor from a release.
- **Updates:** re-vendor from a release tag/snapshot — do not edit-in-place as
  the improvement path.
- **Foundry edit path:** skill internals improve via Foundry sleep / release
  updates (and optional consented friction feedback). Recipients who are invited
  collaborators push feature branches/PRs — never straight to main.

## Journal / run-capture expectations

After every **real** (non-test) skill run, append a structured journal record
with mandatory fields: `skill_id`, `skill_version`, outcome class, structural
failure codes (schema-versioned semver). Full local journals stay on the machine.
Optional opt-in sanitized friction export is a separate channel (default off).

## Foundry sleep — future-ready (not v1-complete)

**Foundry sleep** (automatic global skill improvement from journals/friction) is
labeled **future-ready**: hooks, layout, and contracts ship so journals land in
the right place, but sleep consumption is **not** claimed complete in package v1.
Incomplete Foundry does **not** block package use; readiness may warn
`journal_contract_unproven` without claiming the improvement loop is live.
