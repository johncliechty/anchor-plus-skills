# North Star (LOCKED) — Shareable Anchor + Skills

**Effort:** Shareable Anchor + Skills (dual package, dual audience)  
**Crucible:** Stage 0 — FULL depth (John confirmed 2026-07-23)  
**Status:** LOCKED — John 2026-07-23  
**Workspace:** `C:\dev\plans\2026-07-share-anchor-skills\`  
**Revision:** + opt-in sanitized skill-friction feedback; per-skill + de-identified user key (John 2026-07-23)

---

## Statement

Make **Anchor and the Skills (Trio + Foundry suite)** something John can **share cleanly** with two kinds of people, via **two product packages**, without leaking his machine, data, or secrets — and without waiting for every skill-improvement run to finish before the **plan** is done.

A recipient can:

1. **Get the right package** — either **Skills-only** or **Anchor + Skills** (Anchor **never** ships without Skills; Skills **never** ship without the environmental and governance setup they need to run well).
2. **Onboard in plain English from a terminal** — choose a home folder (recommend `C:\dev` on Windows), install code and rules, connect the **subscription** CLIs they actually use (Claude, Gemini via `agy`, Grok today; OpenAI later), start a **local** Anchor service when the package includes Anchor, and get a **desktop icon** that opens the Anchor dashboard in their default browser.
3. **Be either a consumer or a collaborator** — open users **download and use** (local changes stay local; they cannot push into John’s source of truth); invited collaborators can **push only to their own branches / PRs** for John to review and integrate — **never straight to `main`**.
4. **Inherit how the system is meant to run** — the same operating rules that govern skills on John’s machine (including the **10-minute Status table** discipline, seating from Anchor model prefs / subscription families, skill immutability vs Foundry edit path, and **journaling hooks** so future Foundry sleep sessions can improve skills from real use).
5. **Optionally help improve the skills for everyone** — at skills onboarding, **explicitly opt in** (or decline) to share a **sanitized subset** of local skill journals that describe **friction, bugs, and inefficiency only** — never personal, proprietary, or session-content data — so John can feed a **global skill improvement** loop (Foundry sleep / release updates). Sharing is **off unless they agree**; the ask is plain-English and unambiguous.

**Reuse, don’t rewrite:** extend the already-GREEN share-distro / shareable machinery (`distro.py`, `vendor_skills.py`, `onboard.py`, registrars, scrub gates, security defaults where present). Expand roster, packaging topology, onboarding UX, governance payload, and the opt-in feedback path. **Do not ship or vendor live skill trees until the concurrent skill-update run finishes and is merged**; packaging freezes from a **declared tag/snapshot**.

---

## Success criteria (checkable)

1. **Dual packages, correct coupling**
   - Package **A — Skills:** installable suite (Trio + Foundry skills + Foundry journal/sleep hooks + governance templates + subscription seat setup). No Anchor app required.
   - Package **B — Anchor + Skills:** Anchor service/app **plus** the full Skills suite (including Zombie Hunter, Tidy-Idy, and in-app Anchor Doctor). Build/publish of “Anchor-only” is **hard-blocked**.
   - Skills package refuse to claim “ready” unless governance + seat/env setup steps complete (or user explicitly declines with an honest “degraded” stamp).

2. **Dual audience, git-honest**
   - **Public / open consumers:** can clone or download releases; **no write access** to John’s upstream; local edits never flow back unless they become invited collaborators later.
   - **Collaborators:** invited to private `*-dev` (or equivalent) with ability to push **feature branches** and open PRs; branch protection blocks force-push and direct push to `main`; John integrates via review.
   - Public mirrors (if used) are **one-way publish** from private source of truth — not hand-edited.
   - **Exception path for opt-in feedback only:** consented, sanitized friction reports may flow back through a **dedicated, controlled channel** (e.g. automated contribution to a feedback inbox/repo path) that is **not** “user can push arbitrary code to main.” Stage 1 designs the exact transport; outcomes below are fixed.

3. **No-leak distribution**
   - Shipped trees pass deny-by-default scrub (no author’s personal data, host paths, secrets, project state, journals with PII, git history of private work).
   - Vendoring is `git archive` / snapshot-based with denylist + residual scrub; provenance stamped (`SOURCES.md` or equivalent).
   - Release freeze is against a **tag/commit**, not a dirty working tree mid-skill-run.

4. **Plain-English terminal onboard (few choices)**
   - Explains, in plain language, the home directory (default recommend `C:\dev` on Windows; user may choose another): that folder holds Anchor (if installed), skills, and future projects.
   - Asks permission before writing agent rules (`AGENTS.md` / thin pointers), model prefs, skill links/copies, and service registration.
   - Detects subscription CLIs present (Claude, Gemini/`agy`, Grok); guides login/session visibility so skills can use them; does **not** require API keys for the production seat path.
   - Future-proof seat slot for OpenAI without redesigning onboard.
   - Anchor package: starts **local** service only; opens dashboard; creates **desktop shortcut/icon** → default browser → local dashboard URL.
   - **Feedback consent step (skills onboard):** a clear yes/no — “Share sanitized skill-friction reports to help improve these skills for everyone?” — with plain-English text that states what is and is not shared (see criterion 9). Default is **no share** unless they opt in. Choice is stored locally and reversible later.
   - Idempotent, refuse-don’t-clobber, resumable; never destroys an existing foreign skill install.

5. **Governance travels with the code**
   - Distro ships (or onboard installs) the operating rules collaborators need: Status-table 10-minute format, seating law (prefs → family → subscription CLI transport), no ad-hoc skill patching, journal/run-capture expectations.
   - Rules live in a **canonical `AGENTS.md` payload** (host-global and/or package root) with thin `CLAUDE.md` / `GEMINI.md` pointers where appropriate — same convention John uses today.
   - Skill Foundry journal layout + “append after real runs” contract is installed so **when** Foundry sleep matures, journals are already in the right place. Incomplete Foundry does **not** block package v1, but hooks and docs are present and honest.

6. **Works-on-arrival (local-first v1)**
   - Recipient path: obtain package → onboard → (if Anchor) local browser dashboard, without Tailscale or multi-machine exposure in v1.
   - Missing prereqs surface as **one upfront actionable list**, not deep mid-run failures.
   - Windows is first-class (desktop icon, service); macOS/Linux paths exist where share-distro already invested (service units, PTY) or are honestly scoped.

7. **No regression of safety/durability already earned**
   - Does not undo default-deny auth, token handling, scrub gates, or durability invariants already landed in Anchor shareable work.
   - Test suite remains money-safe (no paid spend without explicit opt-in).

8. **Plan now, ship after the concurrent skill run**
   - Crucible completes with a Foreman-ready plan while skills may still be mid-update.
   - Foreman execute / release waves are **gated** on “skill sources frozen at agreed tags” and John’s go-ahead after concurrent run merges.

9. **Opt-in sanitized skill-friction feedback (global improvement feed)**
   - **Local journals always stay local** in full (including anything sensitive the user or agent wrote). That full local journal is for the user’s own machine and future local Foundry sleep.
   - **Only if opted in**, a **sanitizer** produces a **subset export** of journal entries that are about **skill friction / bugs / inefficiency / workarounds** — not about the user’s work product.
   - **Keyed and broken down by skill:** every export record is tagged with the **skill name + version** (and only that skill’s friction). Intake and any rollups John uses for global updates are **partitioned per skill** so Crucible friction does not mix with Foreman, Tidy-Idy, etc.
   - **De-identified installation key (not a person identity):** each opting-in install mints (or stores) a **stable random opaque ID** — e.g. a high-entropy UUID or hash with **no** name, email, machine name, path, or account. John can see that *the same de-identified install* hit related frictions over time (pattern / cluster signal) **without knowing who the person is**. The key is **not** reversible to identity by design; rotating/regenerating the key is allowed on user request (breaks continuity, which is fine).
   - **Allowed in the export (examples):** skill name + version; de-identified install key; outcome class (friction / failed / workaround); run size or duration band; complexity band; structural “why it failed” (timeout, tool missing, seat failover, parse error); what the agent tried as a workaround; host OS class; model-family seats used (not account ids).
   - **Forbidden in the export (hard fail if present):** real-world personal identifiers; emails; usernames; absolute host paths unique to the user; secrets/tokens; project names that are proprietary when avoidable; **session content**; **session purpose / business topic**; prompts; file contents; anything that describes *what the user was working on* rather than *how the skill broke*; anything that would re-identify the install key to a person.
   - Export **fails closed**: if sanitizer cannot prove the payload is clean, **nothing is sent**.
   - Transport delivers reports to a **John-controlled feedback intake** (preferred: a dedicated path in a repo John owns, or equivalent Stage-1 design) so John can **pull / ingest** them on his schedule into **Foundry sleep cycles** (and related global skill improvement work) — **not** unrestricted write access to product `main`, and **not** a requirement that sleep be fully built in v1 (the *feed* is built; sleep consumes it when ready).
   - Intake layout preserves **per-skill** partitioning and the de-identified install key for cross-report pattern spotting (“same install, same skill, repeated friction class”).
   - Opt-out anytime; previously local full journals are never retro-uploaded without consent; opt-out may stop new sends and optionally wipe the local install key.
   - Onboard copy is explicit: this is a **sanitized summary for improving the skills**, not telemetry of their work, not full journal upload, and the install key **does not identify them by name**.

---

## Non-goals (explicitly OUT of this effort)

- **Waiting for Skill Foundry to be “complete”** before planning or designing journal hooks / feedback hooks.
- **Shipping or vendoring during the concurrent skill-update run** (sequencing gate, not a product feature).
- **Tailscale / remote multi-machine access** in v1 (may fast-follow; ship-anchor’s onboard2 is deferred).
- **API-key-first production seats** (subscription CLIs remain the primary path; raw API keys are not the onboard default).
- **Multi-user / multi-tenant one Anchor instance** — each person runs their own single-user instance.
- **Cloud-hosted Anchor** or turning John into a SaaS operator.
- **Rebuilding skill internals** (Crucible/Foreman/researchPrime/Gandalf/etc.) — package, govern, and install them; improve via Foundry sleep + consented friction feed later.
- **Accepting open-source PRs into private upstream without invitation** (public consumers file issues/feedback only unless invited). *Sanitized friction reports under opt-in are a separate controlled channel, not arbitrary code push.*
- **Migrating John’s live personal projects into the public package.**
- **Rewriting the entire Anchor GUI** or changing the portfolio product identity.
- **Silent or default-on telemetry**; **full journal sync**; **session-content analytics**; **advertising / third-party data sale**.
- **Requiring feedback opt-in to use the skills** — decline must leave skills fully usable.

---

## Risk taxonomy

| ID | Risk | Why it matters | Mitigation direction |
|----|------|----------------|----------------------|
| R1 | **Leak** of personal/host/secret data in public or zip | Highest irreversible harm | Deny-by-default distro + host-path detector + clean-scan gate before any publish |
| R2 | **Anchor-without-skills** or skills-without-env ship by mistake | Broken first experience | Package matrix hard constraints + CI assert “B includes A”; onboard readiness gate |
| R3 | **Skill drift** during concurrent runs → inconsistent release | Collaborators get half-updated skills | Freeze-at-tag; plan/execute split; SOURCES.md stamps |
| R4 | **Public mirror vs private PR confusion** | Contributors push wrong place; wasted effort | Topology docs + CONTRIBUTING + branch protection; public README states write policy |
| R5 | **Onboard too clever / too silent** | Users lose trust or break existing setups | Plain-English prompts, permission for writes, refuse-don’t-clobber, degraded stamps |
| R6 | **Subscription detection false confidence** | “Grok installed” but skills can’t see session | Probe that matches real seat transport (`claude` / `agy` / `grok.exe -p`), not presence of a random binary name only |
| R7 | **Governance payload diverges** from John’s live AGENTS.md | Collaborators run “wrong culture” | Single exportable rules pack generated from canonical sources + version stamp |
| R8 | **Desktop icon / service fails** on non-Windows | Scope surprise | Windows first-class; other OS honest fallback documented |
| R9 | **Foundry incomplete** over-promised | Users expect sleep loop now | Ship hooks + docs; label Foundry sleep as future-ready, not v1 feature-complete |
| R10 | **Scope merge of three old plans** causes double-build | Wasted waves | Explicit reuse map; one master plan supersedes share-distro delta / ship-anchor / July topology for *this* product cut |
| R11 | **Feedback channel leaks session content or PII** | Destroys trust; legal/reputational harm | Fail-closed sanitizer; allowlist schema; red-team tests with planted PII; default opt-out; no send on ambiguity |
| R12 | **“Git push feedback” confuses consumer write policy** | Users think they can push code; or security holes | Separate feedback intake from product write access; docs draw hard line |
| R13 | **De-identified key still re-identifies** (tiny cohort, path leaks, etc.) | “Anonymous” becomes identifiable | Opaque random key only; never hash email/username; strip quasi-identifiers; banded size/complexity not free text; document residual risk honestly |
| R14 | **Cross-skill blob loses signal** | John can’t see which skill is broken | Hard per-skill record partition + intake folders/tags |

---

## Foresight brief (Parable of the Oranges)

- **Real goal:** not “put code on GitHub,” but **other people become productive with the same operating system of agents**, under the same rules, without John babysitting install or leaking his life — and **skills get better from real friction** without John reading anyone’s private work.
- **Two steps ahead:** the first public user will change a skill locally and wonder why it doesn’t “save to the cloud.” Onboard and README must make **consumer vs collaborator** crystal clear on day one — and separately make **feedback opt-in** crystal clear as *not* the same as code contribution.
- **Three steps ahead:** when Foundry sleep works, journals that were never written are worthless. Install journal paths and the “append after real runs” rule **now**, even if sleep is later. Opt-in friction exports become a **global** sleep/improvement feed for John; local full journals remain the user’s.
- **Coming problem:** dual packages will drift (skills release without matching Anchor pin, or vice versa). Anchor+Skills must **pin a Skills release tag**; Skills-only can move faster, but pins are documented.
- **Coming problem:** same-family seating (e.g. all-Grok) is valid on John’s machine today — onboard must stamp `cross_model` honestly from prefs, not hardcode the old 5:1 Claude/Gemini split.
- **Coming problem:** if feedback transport is “open a PR,” sanitizer bugs become public forever — prefer a design Stage 1 can harden (inbox + review before any merge into skill sources).
- **Coming problem:** without **per-skill + de-identified continuity**, the feed is either a noisy pile or a privacy bomb. Partition by skill for Foundry sleep; keep a stable opaque install key so “same install keeps hitting seat failover on Foreman” is visible without knowing who.
- **Iteration:** North Star is locked once; refinements after lock are **explicit amendments**. Stage 1 Sharks pressure-test the *plan* against this NS; they do not silently redefine product intent.

---

## Locked product decisions (proposed — part of NS lock)

These are the decisions Stage 0 asks John to treat as locked with the North Star (editable until lock):

| # | Decision | Choice |
|---|----------|--------|
| D1 | Pipeline depth | **FULL** |
| D2 | Packages | **Skills-only** and **Anchor+Skills**; never Anchor-only |
| D3 | Audiences | **Public consumer (read/download)** + **invited collaborator (branch/PR)** |
| D4 | Remote access v1 | **Local-only** (browser on same machine); no Tailscale in this cut |
| D5 | Auth for seats | **Subscription CLIs** (Claude, Gemini/agy, Grok); OpenAI slot reserved; not API-key-first |
| D6 | Home directory | Onboard **recommends** `C:\dev` (Windows); user-overridable; becomes base for projects/skills/Anchor |
| D7 | Desktop affordance | **Desktop icon/shortcut** → default browser → local Anchor dashboard (Anchor package) |
| D8 | Skill roster (Anchor+Skills) | Full suite: trio (researchPrime, Crucible, Foreman) + Foundry skills including **Gandalf, Jumper, Tidy-Idy, Zombie Hunter**, Legal-Beagle, Literature-Review, Ramanujan, Figure-Designer, Expert-Coder/Agent-Builder as available; **Anchor Doctor** ships as Anchor feature; Foundry tooling hooks included |
| D9 | Governance | Ship/install **AGENTS.md operating pack** (Status table, seating law, journal expectations) |
| D10 | Sequencing | **Plan freely now**; **execute/ship only after** concurrent skill-update run is merged; vendor from **tags** |
| D11 | Topology (working default) | Align with July plan: private `*-dev` source of truth + public mirrors/releases for consumers; collaborators on private — **Stage 1 may refine mechanism, not the audience outcomes** |
| D12 | Reuse base | Extend share-distro / shareable GREEN code; do not greenfield a second distro stack |
| D13 | Skill improvement feedback | **Opt-in only** (default off). Sanitized **friction/bug/inefficiency** journal subset only — no PII, no proprietary content, no session content/purpose. **Broken down per skill** (skill name + version on every record; intake partitioned by skill). **De-identified install key** (stable opaque random ID, not name/email/machine) so John can spot patterns from the *same install* without knowing who they are. Fail-closed sanitizer. Controlled intake (repo path John can **pull**) for **Foundry sleep cycles / global skill updates**. Full local journals always remain local. Reversible (incl. key rotate/wipe). Skills fully usable if declined. |

---

## Brownfield stance (salvage vs rewrite)

**Salvage and extend** the existing distro/onboard/vendor/publish stack.  
**Supersede** conflicting *product* decisions in older plans (e.g. tidy-idy exclusion, Tailscale-in-v1, 4-skill-only roster) with the table above.  
**Do not** re-implement security waves already claimed GREEN without a gap proof.

---

## How iteration works from here

1. **Now:** you review this candidate. Edit anything that feels wrong (roster, topology, naming, what’s in v1).
2. **You lock** the North Star (possibly after 1–2 refinement passes). After lock, product intent is frozen; changes are dated **amendments**.
3. **Stage 1 (Master Plan):** brainstorm + Shark Tank under FULL — pressures the *how* (including feedback transport + sanitizer schema), not a silent rewrite of the *what*.
4. **Stage 2:** wave plan + Foreman handoff; execute waves stay **gated** on skill freeze + your go-ahead.

---

*North Star LOCKED by John 2026-07-23. Stage-1 Master Plan in progress. Amendments only after lock.*
