# Zombie Hunter reliability + Doctor/health UX — Description

**North Star:** # North Star — Zombie Hunter reliability + Doctor/health UX

**Locked intent (2026-07-21 investigation → Crucible FULL, Grok seats via Anchor prefs):**  
Stop flagging legitimate AI sessions (especially VS Code) as zombies; make Freeze/Kill actually work; make Zombie Hunter and Anchor Doctor terminals fast and multi-engine (Claude / Gemini / Grok); make health banners actionable.

## Statement

Make Anchor’s Zombie Hunter a **trustworthy, fail-safe token-spend sentinel** that only marks a process as a reap candidate when spend and lack of supervision are **both positively established**, never when uncertain — and make Freeze/Kill, investigation terminals, and health-warning → Doctor diagnosis paths **instant, complete, and operator-usable**.

## Success criteria

1. **No false zombies for live interactive work.** Starting one or two Claude (or other engine) sessions in VS Code / Cursor / Windows Terminal / Anchor must **not** produce a “token-spending zombie” banner or red reap tile for those processes. Uncertain supervision or a broken sweep → **abstain** (never red).
2. **Tightened definition (code + skill contract).** Zombie ⇔ known AI engine image **and** confirmed paid-provider spend (not generic Google 443) **and** unsupervised by a robust interactive-host walk (incl. `code`, `code - insiders`, `cursor`, `openconsole`, `grok`, shells, Explorer) **and** not Anchor-owned. Idle / keyword-only matches stay hidden.
3. **Freeze and Kill work.** Freeze uses real process suspend (NtSuspendProcess or equivalent), reports true success/fail; Kill tree-kills and removes the row only on success. Broken SoftFreeze (`Thread.Suspend`) is gone.
4. **Radar loads immediately.** Page shell + last-known counts/tiles from cache paint in &lt;1s; full sweep runs in background; “Why?” / per-row detail is ready without waiting for a 10–20s blocking first paint. Sweep JSON is control-char safe (no silent sweepError).
5. **Investigate terminal: Claude + Gemini + Grok.** Engine toggle includes all three; session start is fast (slim seed); optional deep briefing for a selected candidate so the operator knows how to treat it.
6. **Doctor terminal: same engines, not forever to open.** Page is responsive without blocking on auto-session; engine choice available; optional one-click “diagnose” path with a short seed.
7. **Health banners are clickable.** Dashboard health (and reaper-health) banners open Doctor with the issue context and start a diagnostic terminal that investigates that message — not a static path to a markdown file.

## Non-goals

- Auto-arming the Python reaper kill ladder (`TIER_KILL`) or silent mass kills.
- Replacing the ownership-based Anchor reaper for registered sessions (keep it; align Node classifier with its fail-SAFE spirit).
- Building a new forensics product beyond what’s needed to treat a flagged process.
- Cross-model verification theater while both coding and review families are Grok (`cross_model: false` is honest).

## Risk taxonomy

| Risk | Mitigation |
|------|------------|
| False kill of user’s live session | Abstain on uncertainty; freeze before kill; confirm dialogs; supervised = KEEP |
| Freeze no-ops leave spend running | Replace SoftFreeze; assert suspend via probe |
| Sweep parse failures hide real zombies | JSON-safe enum; surface sweepError; never invent zombies on error |
| Slow terminals block diagnosis | Cache-first UI; slim seeds; start-on-demand |
| Scope creep into full system sentinel rewrite | Stay on definition + freeze/kill + UX paths from investigation |

## Code surfaces (brownfield)

- Skill: `<path> Foundry\skills\zombie-hunter` (Node sentinel: `classify.js`, `spend.js`, `soft-freeze.js`, `server.js`, tests)
- Anchor: `<path> (`anchor_gui.py` zombie/doctor/health banner handlers, `proc_probe.py`, `zombie_hunter.py` / `reaper.py` only if needed for ownership parity)
- Optional skill SKILL.md contract sync for the tightened definition

## Depth / seating

- Crucible depth: **FULL** (user-confirmed)
- Tier: **regular** (not Heavy)
- Seats: **coding_family=grok**, **review_family=grok** → honest `cross_model: false`; transport `grok-cli` / `grok.exe -p`


Tighten zombie definition; fix freeze/kill; instant radar; multi-engine terminals; clickable health→Doctor. Cap-halt Master Plan with operator locks OL1–OL5.

## Success criteria
- Live VS Code / Cursor / WT / Anchor AI sessions are never red-flagged as token-spending zombies; uncertainty abstains.
- Zombie definition is tightened in code+tests: engine image + confirmed provider spend + unsupervised interactive-host walk + not Anchor-owned; generic Google 443 is not spend.
- Freeze uses real NtSuspendProcess (or equivalent) with honest success/fail; Kill tree-kills only on success; SoftFreeze Thread.Suspend is gone.
- Radar paints shell + cached verdicts immediately; full sweep background; control-char-safe process JSON; per-candidate Why/treat detail without blocking first paint.
- Zombie investigate terminal offers Claude, Gemini (agy), and Grok; start is fast with slim seed; selected-candidate deep brief available.
- Doctor page is responsive; engine picker Claude/Gemini/Grok; session start on demand or one-click diagnose, not multi-minute blank wait.
- Dashboard health (and reaper-health) banners are clickable and open Doctor with that issue seeded into a diagnostic terminal session.

## Provenance

Generated by Crucible Stage 2 from an approved Master Plan, vetted by the Shark-Tank loop and the well-formedness gate before handoff.
