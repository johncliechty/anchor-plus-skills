# Skill icons on three surfaces (John, 2026-09-05)

> "I want the icons for the different skills to show up in the plan when they are mentioned (Gandalf,
> Jumper …). Then I want the icons put at the top of each report that is created by a skill and I also
> want the icons to show up in the list of skills in the drop down menu in the workbench terminal."

**Band:** LITE, by hand, one change (converged ask, fixed scope, reversible). Needed because John asked;
dropping it costs nothing but the thing he asked for.

## What exists (inventory, 2026-09-05)

- **Assets:** `vendor/brand/*` served at `/vendor/brand/<file>` (`anchor_gui.py` ~836); the cockpit's
  `/brand/<file>` is rewritten to the same place (`steward_routes.serve_page_doc` ~194).
- **The one good map:** `static/project-window.js` `_SKILLS` (~3366–3378, `{g, name, label, icon}`) — the
  project-window session panel already renders `<img src='/vendor/brand/'+icon>` (~3400). Three other
  partial maps exist (`share_onboard.PORTFOLIO_BRAND_ICON_MAP`, foundry-gui `SKILL_ICONS`, `anchor_gui._skill_icon_img`).
- **No icons outside Anchor** (Skill Foundry has one `financial-analyst/icon.jpg`; trio has none).

## The change (one map, four spots)

1. **One server-side map** `SKILL_ICONS` (name → brand file, with a fallback of `gwl-m-icon.svg`) in
   `steward_cockpit/steward_routes.py` beside `SKILLS`; the `skills` verb returns `[{name, icon}]`
   (today a flat name list). The cockpit reads icons from there — no second client-side table.
2. **Plan outline** — `steward_cockpit/static/shared.js` `paintStepsList` (~328): when a step's
   `commissioned_as` (from `steward_campaign.read_map` ~211) names a skill, or the step text mentions
   one, prepend `<img class="skico" src="/brand/<icon>">` to the title.
3. **Report tops** — (a) `report_viewer.reader_html` gains an optional `skill=`; `render_effort` passes
   `terminal_session.LANE_SKILL[lane]` (research → researchPrime, plan → Crucible, build → Foreman) and the
   `/artifact?render=1` path derives Gandalf from `.anchor/gandalf/`; one `<img>` before the article.
   (b) the cockpit's `static/report.html` header (~74) keys the icon off the first path segment
   (`gandalf/…` → Gandalf, `report/…` etc. → the lane's skill when known, else none).
4. **Workbench skill rail** — `steward_cockpit/static/cockpit.html` (~867): each skill button becomes
   `img + span` using the icon from `/api/skills`.

**Tests (stub gate):** `tests/test_skill_icons_2026_09_05.py` — the skills verb carries an icon for every
name and the fallback for an unknown; `reader_html(skill=…)` emits exactly one brand `<img>` at the top and
none without a skill; source-level assertions that shared.js and cockpit.html carry the icon branch.
**Proof:** Playwright screenshot of the cockpit with a Gandalf step in the outline, the skill rail, and a
Gandalf report page.

**Not done:** icons for skills with no brand file (they get the GWL mark, said aloud); icons in the
classic project window (already there).

## John, later the same evening: "put them into the existing projects and plans"

The icons must appear on what already exists, with no migration and no re-run: the plan outline keys
off the step TEXT (a mention of Gandalf / Jumper / researchPrime / Crucible / Foreman / Ecgberht /
Ramanujan / literature-review / zombie-hunter / tidy-idy / financial-analyst / legal-beagle), not only
the `commissioned_as` field new steps carry; report tops key off the lane and the on-disk path, which
every existing report already has. Existing projects therefore light up on the next page load.

## Built the same evening (commits 5d0ff52, 4f88467)

One client map `steward_cockpit/static/skill-icons.js` (the cockpit's shim serves only its own static dir —
the first placement under `static/` 404ed on the page, found by the proof), one server map
`steward_routes.SKILL_ICONS` (the skills verb carries icons), `report_viewer.skill_icon_html` on top of a report.
Spots: plan outline steps, the workbench skill rail, the cockpit report page and the Anchor report page, the
home project line. Proven on the live pages with Playwright (screenshots in the session scratchpad). Also in the
same batch: links labelled by the document, rendered by type (md Reader / Office preview / PDF inline), file
search + sort name/type/date, files open in a new window (the app button stays).
