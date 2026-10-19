# dashboard-v2 — prototype r3 (the home's design contract)

Built 2026-08-27/28 (with Grok). The 2026-08-29 best-in-class addendum named it
the design contract for the Anchor home and asked (P0) that it be versioned,
screenshotted, and that each element be marked live / projected / sample / future.
Versioned here 2026-09-03; the live home became this prototype the same day
(`anchor_gui.py` generate_html + `home_attention.py`, pinned by
`tests/test_home_r3_2026_09_03.py`).

**Scrubbed.** The prototype ships SAMPLE data. The author's originals carried real
names, accounts and tasks; the tracked copy replaces every one of them with generic
sample text (a person, a client, a school — never a real one). The originals stay
beside it as `*.personal.*`, git-ignored by this folder's `.gitignore`. Nothing under
`_mockups/` is ever in the collaborator bundle (`dist_manifest.txt` excludes it).

| File | What it is |
|---|---|
| `index.html` | the prototype (open it in a browser; every action is simulated) |
| `SCORECARD.md` | what it is scored against, the cuts it made, the v0 ranking / Doctor / Hunter rules |
| `CHANGE-2026-08-28.md` | the r3 delta over r2 (cockpit + home) |
| `CONNECT.md` | how a Google / Microsoft connector would be set up by the user (no connector exists) |
| `reference/` | rendered 2026-09-03 from the scrubbed copy: default 1440×1000, Tip of the Hat open, phone 390 wide (full page) |

## Element marking (as of 2026-09-03)

| Element | Mark | Where it lives now |
|---|---|---|
| Steward rail: the move · due today · coming up · projects 2×2 · workbench | **live** | home (`generate_html`) |
| Needs-attention rows, deterministic v0 rule shown per row | **live** | `home_attention.py`; the steward's raise queue joins client-side |
| "I would take X first" | **live** | the steward tile |
| Tiles in r3 order: Steward · Tasks · Projects · Workbench · Calendar · Email · Grass | **live** | home |
| Counts on the Tasks line; archives inside the tile; stats row / header buttons / click-to-expand cut | **live** | home |
| Calendar / Email tiles | **future** (connector) — the honest not-connected zero state is **live** | home; research in `plans/2026-08-29-anchor-email-calendar-research` |
| Calendar week/month view, add-event form, mail flow-by-source | **sample** | prototype only |
| Doctor: Resolve all with a live re-probe; issues in plain words | **live** | `POST /api/doctor/resolve_all`, `doctor_plain.py` |
| Doctor: reads the report, probes the live server and re-runs the check itself on open; receipt in plain words in the Doctor terminal | **live** | `GET /api/doctor/probe`, the /doctor page (after v1.2.10) |
| Hunter census of every runner class; arming | **future** | Zombie Hunter is live as a session/PTY census; not armed (2026-07-05 read) |
| Foundry skill cards | **projected** | the Skill Foundry page exists; the card view does not |
| "Not as important" 7-day demotion feedback | **future** | not built |
| New project by talking | **projected** | the steward converse exists; the new-project dialog is prototype only |
| Phone breakpoint | **sample** | prototype CSS only |
