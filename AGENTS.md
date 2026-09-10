# AGENTS.md — how the bundled skills expect to be run

> This file is the **canonical run contract for the skills in this bundle**.
> Every `SKILL.md` under `vendor/bundled-skills/` points here. If you move or
> delete it, those pointers dangle and the skills lose their contract.
>
> **Scope note.** This is a distributed copy and it is deliberately narrow. It
> carries only the rules that are *self-contained* — true on any machine, with or
> without the Anchor dashboard installed. Rules that resolve against the author's
> Anchor registry are described here as a dependency, not restated as if they
> worked without it.

---

## 1. Long-run progress updates — the 10-minute rule

Any skill here that runs a multi-minute background job — the trio
(**researchPrime**, **Crucible**, **Foreman**) and every advisory skill
(**Gandalf**, **Jumper**, **Ramanujan**, **Legal-Beagle**, **Financial-Analyst**,
**Literature-Review**, including every `-Heavy` variant) — must report progress
**about every 10 minutes, unprompted, until it finishes.**

### The launch pattern that makes it actually fire

This is mechanism, not preference. The cadence fails whenever the session is not
in a position to relay, and the most common cause is launching the engine as a
**blocking foreground call** — the session is then frozen inside the run and
cannot post anything until it halts. For every long run:

1. **Launch the engine in the BACKGROUND** — never a foreground call.
2. **Arm the ~600s wake-up AT LAUNCH** — not after ten minutes have elapsed.
3. Each tick, **read the run's status-log tail** and **post the table to chat**.
   Chat is the PRIMARY channel; the log is the data source.
   - Foreman writes `<project>/_foreman-status.log`
   - Crucible writes `<outputDir>/_crucible-status.log`
   - Both write the locked table there at t=0, ~10 min, and at halt.
4. **Stop the cadence at halt/done.**

If a run was launched in the foreground and is blocking, the session **cannot**
relay — it should say so rather than go quiet.

> **Host requirement.** Steps 1–2 need an agent that can launch background work
> and schedule its own wake-up. Claude Code supports both. On a host that cannot,
> the cadence is unavailable and the skill should say so rather than appear hung.

### The locked format — the "Status table"

Every update uses **this exact shape**: header line, bordered field/value block,
then the `ETA` + `To do` footer. Fixed field order:

```
[HH:MM] <run type, e.g. Foreman build> · <project>
─────────────────────────────────
Summary  <plain-English: what this effort is FOR — the goal, not the mechanics>
Effort   <effort/plan name + what it actually does> (<N> waves)
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

**Rules.**
- Lead with the wall-clock timestamp. Timestamp, elapsed, and ETA are mandatory
  on **every** update.
- `Summary` MUST be a high-level, plain-English "what this is FOR" line — the
  goal, not the mechanics — on every tick, so the point of the run never has to
  be reconstructed from wave mechanics.
- `Effort` must include a short plain-language description, never a bare
  filename. Not `Implementation-plan.md`; instead
  `Anchor durability — resumable job engine (Implementation-plan.md)`.
- `Blocker` must call out anything that died, plus any restart or investigation.
- `Journal` recaps **everything** journaled since the last tick — failures,
  timeouts, workarounds, triage decisions. Write `none` when empty; **never omit
  the row.** A journaled-but-unreported failure is still silent suppression.
- One line per field. Flag an elevated process count with `⚠`.
- An ad-hoc prose summary does **not** satisfy the rule. The table IS the
  deliverable of a tick.

**This block is the ONE canonical definition of the format.** Individual
`SKILL.md` files point here and must not redefine it.

### Census must be shell-free

Ticks must not spawn a shell each time — a console window flashing every minute
is the failure this rule exists to prevent. At launch, start ONE hidden
persistent census loop that appends counts to a log; every tick then only
**reads files**. Never a loop that shells out per iteration.

---

## 2. Skill tiers — Heavy vs regular

Invoking a skill by its **bare name** (`/gandalf`) runs the **regular tier**.
Appending `-Heavy` (`Gandalf-Heavy`) runs the **Heavy tier**. This shipped mirror
follows the canonical family-selection law; it adds no separate model-tier
definition. **Both regular and Heavy use `latest_supported` models with
`highest_supported` effort** for their selected coding and review families.
Resolve support from the installed subscription CLI's current catalog or a
verified moving alias. Exact model IDs belong only in receipts and caches, not
in preference pins. Heavy controls depth, stakes, and verification requirements;
regular does not select an older model.

**Where the seats come from — read this if you did not install Anchor.** The
primary source is Anchor's data-dir `settings.json`. It must contain complete,
valid `default_cli`, `coding_family`, and `review_family` selections. An existing
invalid primary file blocks resolution; it must not fall through to a mirror or
defaults. Only when the primary file is absent may the well-known mirror
`~/.anchor/model_prefs.json` supply the same complete, valid preferences. An
existing invalid mirror also blocks resolution. Its `primary_path` field is
metadata only and never redirects resolution. Stale environment variables do
not override or supply these preferences. If both files are absent, all three
selections default to `claude`, with `cross_model: false`.

`coding_family` fills code, reasoning, orchestration, and synthesis seats;
`review_family` fills adversarial review, judge, and checking seats. Production
seats use logged-in subscription CLIs. Choose available families from `claude`,
`chatgpt`, and `grok`; treat `gemini` as unavailable unless its installed,
authenticated subscription CLI and supported model have been verified.

- **Package B (Anchor installed):** use the Dashboard to set these preferences.
- **Package A (skills only):** when the primary settings file is absent, create
  `~/.anchor/model_prefs.json` with this minimal complete example, adjusting the
  families to the subscription CLIs available to you:

  ```json
  {
    "default_cli": "claude",
    "coding_family": "claude",
    "review_family": "claude",
    "model_policy": {
      "mode": "latest_supported",
      "effort": "highest_supported"
    },
    "settings_revision": 0
  }
  ```

**When both families resolve to the same value, stamp `cross_model: false`** and
honestly cap confidence tiers. Permissions and actual-served-model reporting
remain separate requirements: model preferences do not grant permissions, and
receipts must identify the model actually served, including any substitution.
If the provider cannot attest its model, record `model_attested: false` and
state that limit; never present the requested model as an observed one.

---

## 3. No shell spawns from sub-agents

Sub-agent prompts must forbid shell churn — Read/Grep/Glob only, no test suites,
no background processes that spawn visible windows. Spawned terminals steal
window focus and interrupt whatever you are typing. This holds on every host.

Long-running engine processes are launched from the **main session**, never owned
by a disposable sub-agent: a reaped sub-agent kills its children.

---

## 4. Honest degradation

No silent degradation, anywhere. If a leg of a skill could not run — no second
model family available, a verification engine absent, a tool missing — the skill
must **say so in its output and stamp it**, not quietly return a lower-quality
result that looks complete. A run that reports "adversarial verification did NOT
run" is behaving correctly; one that omits the caveat is defective.
