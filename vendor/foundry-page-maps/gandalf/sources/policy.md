# Skill Foundry

R&D project managed by Anchor — research/plan/build via the trio.

## Operating mode (standing, set 2026-06-28)

- **Human-summaries only.** Replies are conclusions, not command/output transcripts.
  Grunt work is routed through background sub-agents (isolated context → summary
  only) so John's main view stays clean.
- **Control model (set 2026-06-28): Claude orchestrates + verifies; Gemini bulk-builds
  under Claude's bounded dispatch.** Claude is the single controller — it owns the work
  order, dispatches **discrete, capped** build tasks to Gemini via the `agy` CLI (one-shot
  per call; never a free-running autonomous Gemini session), supervises concurrency so
  there is **no uncapped swarm**, and does the **verification with Claude** tokens. Rationale:
  Gemini does the heavy/voluminous building (cheaper tokens); Claude spends its tokens on
  the lighter orchestration + cross-verification. Either side's GREEN still requires the
  OTHER model to reproduce the gate (PLAN.md §6); verdicts logged to §7.
- **Swarm safety (hard rule).** Before/after dispatching workers, Claude checks for
  orphaned `claude -p` / `agy` / stuck `pytest` process trees and reaps them. No spawn path
  runs uncapped. (The 2026-06-27 crash and a 9h/14-zombie stuck-pytest on 2026-06-28 were
  both this failure mode.)
- **No background process pops a console window** (claude or gemini): `windowsHide`,
  `shell:false`, `CREATE_NO_WINDOW`. Enforced in every spawn.
- **Either model can drive; the other verifies — see [`HANDOFF.md`](./HANDOFF.md).**
  It carries the role-swap mechanics (transports: `agy` for Gemini, `claude` for Claude)
  so John can hand the wheel to Gemini when the Claude window gets full. **Whoever is
  driving keeps HANDOFF.md §5 (current focus) + §6 (next steps) current** at the end of
  every chunk, alongside PLAN.md §3/§7.

## Skill tiers — Heavy vs regular, and always-cross-model (CANONICAL source of truth; consolidated by John 2026-07-08; family prefs 2026-07-21)

> This is the AUTHORITATIVE definition of the foundry skill tiers. It lives WITH the skills so that ANY agent
> invoking a foundry skill from ANY host — Anchor's `job_runner`, a Claude Code terminal, Cowork, Grok Build,
> the `agy` CLI, VS Code — obeys the SAME definition. Each foundry `SKILL.md` points here. Do NOT re-define
> tiers in an engine's global file (`~/.claude/CLAUDE.md` etc.); edit THIS block. Governs the advisory skills
> (Gandalf / Jumper / Superjump / Ramanujan / Legal-Beagle / Financial-Analyst / Literature-Review) and the trio build tier.

**Family resolution (host-agnostic, 2026-07-21; UNIVERSAL SEATING LAW 2026-07-22).** Seats are filled from
**Anchor prefs only** — not hardcoded Claude/Gemini/Grok IDs. Canonical operator text:
user-global `~/.claude/AGENTS.md` → **"UNIVERSAL SEATING LAW"**. Summary:

- **`coding_family`** — code / reason / orchestrate / synthesize seats
- **`review_family`** — adversarial review / judge / Shark / check seats

> **Reviewer seats (John, 2026-09-05):** Claude, **Grok** and **ChatGPT** all serve review / judge / Shark / refuter seats. A verification seat must prove its FAMILY; when the CLI cannot name the served MODEL (Codex today) the verdict is accepted and stamped `model_attested:false` — said on the log, never blind. Grok attests its model through `--output-format json`. Gemini stays off (subscription dropped 2026-08-31).
- **`default_cli`** — which interactive terminal Anchor opens (orthogonal to skill seats)

Resolve from the complete, valid primary Anchor data-dir `settings.json`; only an absent primary permits the well-known mirror `~/.anchor/model_prefs.json`. An existing invalid primary blocks launch. Mirror `primary_path` is metadata, never a redirect. Stale environment family/model pins are not authority. Same family is allowed with `cross_model:false`.

**Subscription transports (production path — no API keys for skill seats on this host):**
| Family | Driver / binary |
|--------|-----------------|
| claude | trio `claude` → `claude.exe` |
| gemini | trio `gemini-cli` / `agy-dispatch` → `agy.exe` |
| grok | trio **`grok-cli`** → **`grok.exe -p`** (Grok Build login) — **never** raw `XAI_API_KEY` HTTP for prefs seats |
| chatgpt | trio **`chatgpt-cli`** → **`codex.exe exec`** (ChatGPT subscription login) — **never** raw `OPENAI_API_KEY` HTTP for prefs seats |

Mechanism: `C:\dev\trio\drivers\index.mjs` (`familyToDriverName`, `runAgent`, …). Prefs beat stale
`TRIO_DRIVER_*` setx. Foundry skills MUST use those seams for live seats. Never hardcode product model IDs
in skill prose. (Default when prefs are absent — no Anchor settings and no mirror — is coding=claude/review=claude,
single-family, stamped `cross_model:false`; changed from review=gemini by John 2026-09-04. It never fires where a
dashboard exists: the dashboard's selection is the seat, universally.)

**Latest/highest model policy (John-approved 2026-09-08; formal Foundry improvement).**
All production seats, regular and Heavy, request `latest_supported` / `highest_supported` from the installed subscription CLI's current capability catalog or verified moving frontier alias. This supersedes one-notch-below defaults and per-project model pins. Exact IDs belong in discovery caches and run receipts, not durable preferences or tier tables. Highest effort is provider-specific; use Ultra when supported by the selected ChatGPT model, never pass that spelling blindly to another provider.

Heavy remains a depth/stakes signal and triggers the existing independent-check policy; it does not license an older model for ordinary calls. Task depth, tool permissions and review independence remain separate from model quality. A base session cannot change its own model: use the resolved subscription seat for required delegated work and stamp actual service honestly. Explicit subagent defaults must match the resolved model/effort unless the isolation contract disables delegation, which must be disclosed.

**Cross-model is a foundry-skill property — always AVAILABLE, fired by the STAKES GATE (amended 2026-07-11,
John-approved; family-prefs 2026-07-21).** Every foundry skill carries the true cross-model swarm
(**coding_family generates/codes, review_family independently checks**), and WHEN it fires is pre-decided —
never deliberated per run:
- **Fires:** stakes ≥ medium (the skill's own triage), ANY `-Heavy` run, or on John's request — **and**
  coding_family ≠ review_family.
- **Skipped / single-family:** light regular-tier asks, **or** coding_family == review_family — honestly stamped
  `cross_model:false` / degraded — the stamps exist precisely so a skipped or same-family check is VISIBLE,
  never hidden.
Rationale: the always-on rule taxed every quick ask with cross-family latency the skills' own internal gates
would have skipped (2026-07-11 portfolio review, finding F4). The tier only swaps WHICH notch of the coding
family fills the coding seat. A single-family result is never passed off as cross-model, and a first `-Heavy`
run per skill must FORCE the cross-model seams when families differ (don't accept a host's default
single-family pick that contradicts prefs).

**Trio BUILD tier (HEAVY vs STANDARD).** Preserve workflow depth and verification controls, but both use the shared latest/highest policy. `TRIO_TIER`, old `TRIO_MODEL_*` variables and per-project model names cannot override saved family choices or model policy. Capability discovery failure is explicit. Failover is bounded to configured families, journaled before launch, never silently replays ambiguous actions, and never turns verification into unmarked self-review.

Per-skill seat mapping (Heavy → frontier of CODING_FAMILY on coding seats, frontier/available REVIEW_FAMILY on
check seats — historical prose said "Claude"/"Gemini"; treat those as the default families, not fixed IDs):
- **Gandalf** — map-reduce advisor: shard reads (review_family) + coding-family fusion/synthesis + host grade.
- **Jumper** — ideation engine that COMPOSES Gandalf: coding_family ideates (SCAMPER/TRIZ/analogical); the
  composed Gandalf runs at the MATCHING tier (Jumper-Heavy → Gandalf-Heavy); the 3-gate kill-filter + grounding
  on review_family.
- **Superjump** — structured ideation (Read / Leap / Judge) that REUSES Jumper seating: coding_family reads and
  leaps; review_family judges independently; Heavy = frontier of the coding family on read/leap, review family
  at highest supported effort. Lean Jumper remains the fast path.
- **Ramanujan** — coding_family proposes/reasons; review_family runs the adversarial verify-router /
  cross-family (Phase F) check; the z3/SMT/Lean certifier arm + Honesty-Law abstain are deterministic solvers,
  identical in BOTH tiers.
- **Legal-Beagle** — coding_family analyzes/drafts over PROVIDED sources; review_family independently checks
  every citation is grounded + jurisdiction/date established. The anti-hallucination rules are tier-invariant
  hard discipline.
- **Financial-Analyst** — coding_family structures the deal/model + report narrative; review_family checks
  assumptions + grounding; the exact-Decimal Excel/Python penny-exact tie-out is a deterministic engine,
  identical in BOTH tiers.
- **Literature-Review** — an augmented researchPrime (COMPOSES a trio skill): Heavy = `TRIO_TIER=heavy`,
  regular = `TRIO_TIER=standard`. No new wiring — just the tier flag.
- **Tidy-Idy** — repository hygiene (HOLD LIFTED by John 2026-07-11 after the simplify-first completion:
  git-is-the-archive removals, driver-catalogue model default, single-pass debate, 42/42): review_family fills
  the analysis/attacker/judge seats via the trio driver; coding_family supervises and owns every human gate. The
  deterministic protections (git-required refusal, protected-file classes, exact-path matching, RETAIN
  fail-safe, >10-removal confirmation) are tier-invariant. First run should be INTERACTIVE and watched.

Lighter skills (Legal-Beagle, Financial-Analyst) may lack a
built-in cross-model verification loop, so their FIRST `-Heavy` run needs the review_family checking seat
wired/verified once.

### Research reports for John — findings before process (2026-09-08)

Applies to researchPrime, Literature-Review, Ramanujan and Jumper human-facing plans and results. Lead the results with an accessible executive summary: the main findings, what is already known, what might be a contribution, and what proof or experiment would establish it. Use explanatory figures and references beside the claims. Follow with detailed coverage of the relevant areas; put reference-search/snowballing methods near the bottom, and agents, review rounds, model provenance and process details last. Keep qualifications next to affected scientific claims, without replacing the findings with a process-status preamble. A plan explains the research questions, why they matter, the approach and the expected result in ordinary language. Explicitly register and link the results; a plan or machine receipt is not the result. Verify the rendered report and finish recoverable independent-review work before closing; an unresolved tooling defect is work to resolve, not a reason to declare the requested research finished. This is John's correction after his first serious review of the literature output, not optional styling.

**Apply corrections before dependent review (2026-09-08).** Read an independent review's actual findings and apply the required changes before freezing or launching its downstream correction check. A completed output file alone is not a signal that the artifact is ready for final review. If a report changes after a review snapshot, verify the changed claims explicitly; never imply that the earlier receipt covers them. In structured model calls, put the human summary inside the requested JSON field and require one complete JSON object without a prose preface.

### Invocation discipline — ZERO deliberation at start (added 2026-07-11; this is why John keeps having to remind)

When a foundry skill is invoked, the operating parameters below are **ALREADY DECIDED**. Do NOT open an internal
discussion about whether/how to do them, do NOT ask John, do NOT re-derive them each run — just DO them. Spending
the first moves of a run debating "how do I do the 5:1 / Heavy" is the exact failure mode this rule kills.

1. **Assess complexity/model use upfront.** Apply the existing depth/stakes rules, resolve current selected families and latest/highest capabilities, and record the actual seat. Do not recreate a second tier table or ask a ritual model-choice question.
2. **Independent review is stakes-gated and family-aware.** Use the configured independent family when the gate fires, and stamp same-family/absent checks honestly. Gemini uses agy-dispatch only when selected and its capability contract is verified; no bare Gemini or API-key fallback.
3. **The ~10-minute status update is automatic** — emitted on your own initiative during any long foundry/trio
   run, WITHOUT John asking. The format is NOT defined here: use the **LOCKED Status-table format** in the
   user-global `AGENTS.md` (`C:\Users\example\.claude\AGENTS.md` → "Long-run progress updates — the 10-minute
   rule", locked by John 2026-07-01: `[HH:MM]` header, bordered field block, Effort/Doing/Status/Tests/Blocker/
   Procs, ETA + To-do footer, chat window as primary channel, cadence armed AT LAUNCH). A 2026-07-11 session
   drafted a second format here unaware of the locked one; the global table WINS — one standard, defined once.
   A long-running skill that goes silent is a defect.

### Run capture for training — EVERY job leaves a machine-readable record (added 2026-07-11, John's directive)

Every foundry/trio skill run captures its work in TWO layers under the skill's `journal/`:

1. **The human entry (unchanged):** the curated `NNNN-<slug>.md` — 7 fields, ≤15 lines, one per real run.
   Id = **max(existing NNNN)+1 over the WHOLE directory** — never read the low numbers as the frontier
   (gandalf accumulated 32 colliding ids that way; journal 0299).
   This layer stays HUMAN-ONLY: no machine dumps in the `NNNN` namespace, ever (the Gandalf journal drowned
   under 460 auto-dumped files and its sleep-loop signal died — that is the failure mode this split prevents).
2. **The training record (NEW, required):** `journal/runs/<UTC-timestamp>-<runid>.json` — machine-readable,
   committed, written by the ENGINE where one exists (Foreman run-live, Crucible, researchPrime rounds, Gandalf
   host, Jumper CLI) and by the operating agent for prompt-only skills. Schema (keep flat, keep small):
   `{ skill, tier, started, ended, input, params, output, result, cross_model, models, duration_s, journal_ref }`
   where `input` = the task/prompt (or a path pointer when large), `params` = the decisive knobs (stakes, fanOut,
   roundCap, wave range…), `output` = pointer(s) to the deliverable(s), `result` = the honest outcome
   (verdict/grade/GO-HALT/converged + one-line note), `journal_ref` = the NNNN entry it pairs with.
   Large payloads go NEXT TO the record as files in the same `runs/` dir, pointed to — never inlined.
   A crash storm collapses to ONE aggregated record. These records are the Foundry's TRAINING FEED
   (sleep-loop distillation, few-shot exemplars, regression corpora) — they only have value if they are
   written EVERY run, so an engine that finishes a job without its run record is a defect.

### Skill-run read scope (added 2026-07-11)

**RUNNING a foundry skill** requires reading only: the skill's `SKILL.md` + THIS file's "Skill tiers" +
"Invocation discipline" + "Run capture" blocks. `PLAN.md` / `HANDOFF.md` are surfaces for working **ON** the
foundry (building/reviewing the skills themselves) — do NOT load them for an ordinary skill invocation; they
are ~700 lines of context tax that add nothing to a run.

### Construction freeze — usage before waves (added 2026-07-11, John-ratified via the 2026-07 portfolio review)

No new build waves / stages / engine construction on ANY foundry skill without a `journal/` entry showing the
CURRENT version was used on a real job and fell short in a named way. The portfolio's recorded failure mode is
engines outgrowing any demonstrated use (five skills reached 2026-07 with empty journals). Usage first, then
construction — the journal entry IS the ticket into a new wave.

## 📍 Active plan

**Current short-term plan + verified status of every core skill, the trio, the GUI/Sleep-Engine,
and Anchor lives in [`PLAN.md`](./PLAN.md). Read it after this file.** It is the shared work
surface for **all agents (Claude and Gemini)**; update its §3 status table and append to its §7
review log whenever you complete or re-verify work. Do not trust a skill's own `SKILL.md` STATUS
line — trust `PLAN.md` (grounded review, 2026-06-27) and re-verify before acting.

---

## The Elegance Law — canonical pointer

**Chekhov process-learning intake — 2026-09-10.** John requests lessons from the slow heading-based onboarding and the planning review that deferred manuscript coverage. [Evidence, causal limits and candidate acceptance checks](skills/chekhov/planning/foundry-20260910-readiness/PROCESS-REVIEW.md) and paired Chekhov journal0026 are the current formal improvement intake for Foundry commissioning, Crucible plan review and Foreman/root supervision. Preserve the full author outcome and show a readable, measured real-use example before expansion. Do not mistake an approved technical plan, local timing or a passing replay for proof of useful full-source coverage. This correction belongs in the existing review/commissioning path; shared engine changes require the separately scoped formal improvement/sleep cycle, not ad-hoc patches or automatic promotion into gated LESSONS.md.

**Full text: [`ELEGANCE.md`](./ELEGANCE.md) (this folder).** Locked by John 2026-08-15 and
injected verbatim into every canonical `SKILL.md` under `skills/*` plus the trio and
Ecgberht, so any agent on any host carries it — this is deliberately NOT a file the skills
merely point at, because pointed-at rule files do not ship.

Five rules: approvals ≤200 words · summaries ≤150 words · default to the lightest band
without asking (a heavy tier must name its trigger in the first status line) · every
unrequested element carries a "needed because ___; dropping it costs ___" line · one dry
round ends a review loop and every plan names something it cut.

**Amended 2026-08-15 (v2 — the verification law).** `ELEGANCE.md` now carries four more
rules, after the same failure recurred a fourth time with a written correction already on
file: verify the claim you actually made on the surface he actually uses; a symptom reported
twice retires the first explanation; prefer a mechanism to an instruction; and a correction
that lives only in a journal has not been made. The block injected into every canonical
`SKILL.md` is `<!-- ELEGANCE-LAW v2 -->`.


## Gandalf live provenance labels — September 30, 2026
A live CLI return can carry legacy Claude/Gemini commission labels even when the actual selected reviewers ran in Grok. Before claiming family independence, compare the actual subscription-seat/session receipts with the returned metadata. Preserve original output and source a separate correction from exact returned replies/model IDs; never invent a reviewer or treat the GROUNDED stamp as completed ResearchPrime verification. MBA Homework1 evidence: .ecgberht/homework1-20260930/gandalf-provenance-check.json. This records an observed runtime defect, not an installed engine repair.
