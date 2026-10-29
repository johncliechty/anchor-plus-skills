# Skill Foundry page: current, coherent, and a flow map per skill. PLAN v1.1-candidate (Poincaré correction 2026-10-03; 2026-10-02 evening: journal report, Poincaré knowledge map in the T2R format as default view, Steward at two levels, Campaign counsel with researchPrime evidence)

**What it is for:** John can open the Skill Foundry from the Cave of Wonders and, for any skill, see what it is
for, what it can do, how it has evolved, and exactly what happens when it is called, with every step linked to the
real code and the real instructions.

**His words (2026-10-02, dictated):** all foundry skills listed, A–Z on the left; bigger icons so the detail shows;
style in step with the rest of Anchor; for each skill a proper North Star, a link to open the actual skill file and
programs, core capabilities filled out, an evolution history that includes the journal entries and the sleep /
improvement sessions, the journal entries available. Second: a flow map (rectangles, arrows, descriptions, links in
each box to the code and the instructions) showing what is program and what is a model call, which agents are
called, whether there is a swarm, how the orchestrator works, when overview / Parable-of-the-Oranges steps happen,
how results come back and are adjudicated, how many review rounds, the stop criteria, the final deliverable.
researchPrime first, then Gandalf. Superjump for the design; the plan adversarially reviewed and vetted.

**Inputs:** `SURVEY.md`; `superjump-result.md` (all three candidates killed on one point: the map must be bound to
the code); `TRACES.md` + the `FLOWS` data in `mockup/foundry-mockup.src.html` (read from the code); mockup v1
https://claude.ai/artifact/NxHfV3NzNeRGmp1k3f1FHd; Grok R1 `review/GROK-PLAN-R1.verdict.json` (revise: 1 blocker,
3 major, 1 minor) and R2 `review/GROK-PLAN-R2.verdict.json` (revise: 1 blocker, 3 major, 1 minor) R3 and R4 (`review/GROK-PLAN-R3/R4.verdict.json`, each
revise: 1 blocker, 3 major, 1 minor), all folded below. R4's findings were facts about specific anchors; they are
kept in the W6 anchor notes at the end, and the plan states the rule.

## Order of work (his rule: mockups are the decision before any plan word or build)
**M0. The mockup look.** He goes through the mockup, says what to change, looks again. No build before his word
that it matches. This plan is revised to whatever the mockup settles.

## Part 1: make the page current

**W1. Read the skills from disk.** `foundry_api.build_skills` discovers every `SKILL.md` under the configured roots
(`Skill Foundry/skills/*` except `skills/templates`, `trio/{crucible,foreman,researchPrime}`, the canonical
Ecgberht folder), de-duplicates by resolved path, sorts A–Z ignoring case. The page list IS that scan, minus
skills whose SKILL.md front-matter says `foundry: false`: agy-dispatch and Figure-Designer get that line (his word,
2026-10-02: not foundry skills). 15 foundry skills remain.
`foundry_map_v2.json` (the edge and autoload graph, with its schema, lock file and clickable rule) is NOT written by
this effort: the page shows skills on disk but not in the map as "not in the Foundry map" and lists them in the
effort report, so nothing becomes clickable in Anchor without a runner manifest. The stale `SEED_SKILLS`
fallback goes. Fixes the missing skills. Ecgberht's one folder yields two labelled rows (W1b); the Campaign counsel placeholder is
not a scanned SKILL.md but one fixed placeholder row (W8).
Acceptance: the page lists the disk scan minus the template and the `foundry: false` skills (15), with Ecgberht as
two rows and the counsel placeholder (17 rows); adding a folder with a SKILL.md adds a row.

**W2. Icons from the skill, shown large.** Icon = the SKILL.md `icon:` front-matter when that file exists, else the
skill's own `assets/icon.*` or `assets/icons/icon.*` (Einstein's portrait, Financial-Analyst, Ecgberht), else the
art the page already pins today (`SKILL_ICONS` paths, e.g. `research-prime-icon.jpg`, `gandalf-icon-v5.jpg`,
`zombie-hunter-radar.jpg`), else one listed alias per skill (Ecgberht → `ecgberht-project-seal.jpg`, Chekhov →
`chekhov-icon.svg`), else the monogram. The table moves into one resolver; no existing art is lost. **White edges become black** (his word): six
icons have white backgrounds at the edge (Skill Foundry, Ramanujan, Einstein, Literature-Review, Legal-Beagle,
Ecgberht's portfolio seal). Black-edged copies are ready in `icons-black-edge/` (before/after sheet there); the
build swaps them in, keeping the originals beside them. 56 px in the list, 120 px on the
skill head (88 px on a phone). Figure-Designer and agy-dispatch have no art: a monogram marked "art needed" until he picks art. Acceptance: judged on HIS screen at those sizes.
(Cut from v0.1: rewiring the icon maps in report_viewer.py, share_onboard.py, steward_routes.py; no need-line.)

**W3. One look with Anchor: restyle, not rebuild.** Keep the existing React page and its routes; move it onto
Anchor's `high-seat-page.css` colors, the system font, 7 px tiles and the standard masthead (his anchor, the Ghost
World Labs lockup), matching the mockup. Kept: the sleep console's propose / apply / rollback (it moves off the
primary view into a "Sleep console" panel, since it is the only screen on those write routes) and the
`foundry_gui.py` fallback (restyled tokens only). The d3 knowledge graph moves behind a "Related skills" link.
Needed because the page must read as part of Anchor (his ask);
rebuilding Anchor-native was v0.1 and is cut: it would drop working write routes for no gain he asked for.

**W3b. The Foundry home and its actions (mockup v2).** "Foundry home" heads the list: the Foundry North Star
(`C:/dev/plans/2026-07-foundry-v2/NORTH-STAR.md`), counts (skills, journal entries, sleep records, maps traced),
"Needs attention" (not in the Foundry map; not registered for Claude Code in `~/.claude/skills`, today agy-dispatch,
Chekhov, Einstein; no North Star; art needed; traced disagreements), recent activity and recent sleep cycles across
all skills, and three actions:
- **Build a new skill**: a five-step wizard (name and purpose; two or three scoping questions from the steward, one at
  a time with a recommendation; a North Star draft he edits and locks; create from `skills/templates/skill-repo`
  through the existing `foundry_gui_write.create_skill` → `foundry.scaffold_skill`, which registers the map row,
  regenerates the lock and commits on a branch; then a steward cockpit for its Crucible plan and Foreman build).
  The existing "Create New Skill" button opens a form that was never wired (ControlPlaneModal); W3b wires it.
  Needed because he asked to BUILD a skill and for the 2–3 clarifying questions; `create_skill` alone yields an empty
  template. Dropping the questions and the cockpit costs a hollow skill folder with no plan behind it.
- **Sleep console**: propose / apply / roll back (working routes) and "run a sleep session" shown honestly as not
  connected yet (`foundry_gui_write.sleep_session_status` reports pending).
- **Skill map**: the d3 graph of the Foundry map's edges.
Per skill (his word, mockup v3): the header (icon, North Star, file buttons), then **tiles you click to open**: How it
works, Process map, Poincaré knowledge map, Core capabilities (with when to use it and facts), Evolution
history, Journal report, Files. Each closed tile shows a one-line preview.
- **How it works**: a plain-language summary of a call, start to finish, kept in each skill's HUMAN.md (`## How it
  works`) so it changes with the skill; written for researchPrime and Gandalf from the traces, for the others from
  SKILL.md / HUMAN.md until their process map is traced.
- **Poincaré knowledge map**: defined once, in W5b below (the same knowledge as an outline is a toggle; the
  Piaget development view sits inside it).
- **Landing view:** where a skill's sphere is drawn, the sphere tile opens first; where it is not drawn yet, How it
  works opens and the sphere tile says "not drawn yet" (this wave: researchPrime and Gandalf drawn; the other
  skills and both Steward rows land on How it works).
Header buttons for SKILL.md, the program, HUMAN.md and Edit North Star (the existing propose /
apply route). ("Run it" from mockup v2 is cut: the program button already opens the run command.)

**W4. Fill each section from the skill's own files.**
- **North Star** resolves: `NORTH-STAR.md` → a `## North Star` section in SKILL.md → `VISION.md` → "No North Star
  yet". A draft is offered only where that chain is empty (today: Einstein), and never outranks a locked section.
  (v0.1 wrongly listed Chekhov, Crucible, Foreman and Figure-Designer as missing; each has a locked section.)
- **Open the files**: SKILL.md, HUMAN.md and the program the skill's own SKILL.md says to run (its "How to run"
  command, e.g. Gandalf `runtime/gandalf-run.mjs`, agy-dispatch `Skill Foundry/tools/agy-dispatch.mjs`), plus the
  files its FLOW.json anchors, open in a read-only source viewer `/foundry/source?skill=&path=&anchor=`. The viewer
  opens that skill's own SKILL.md, HUMAN.md, NORTH-STAR.md, VISION.md, CHANGELOG.md, LESSONS.md and files under its
  `journal/`, plus any path its SKILL.md, FLOW file(s) or knowledge-node anchors name (so a tool outside the folder still opens); every other
  path is refused. The anchor line is highlighted; "open in editor" on the desktop. Needed because he asked to click and see the skill's files, and the
  flow-map links need a place to land.
- **Core capabilities**: the `##` sections of HUMAN.md / SKILL.md, open by default, each linked to its passage.
- **Evolution**: newest first, merging only records that exist in the skill folder: `journal/NNNN-*.md` (date from
  the entry's Date line, else file time), `CHANGELOG.md` and `LESSONS.md` where present (jumper, literature-review;
  LESSONS in seven skills), each typed. An entry is marked "sleep / improvement" only from a marker already in the
  skill folder (a filename or heading naming sleep / elegance / improvement, a LESSONS "Promoted" heading, the
  ELEGANCE-LAW block's version tag). Ecgberht's cross-skill sleep cycles (journal 0076, 0078) are linked from every
  skill, never copied. Missing sources say "Not recorded". The mockup's hand-written rows are not shipped.
- **Journal**: searchable list of every entry, opening in full; colliding ids shown as they are.
- **Sleep sessions are already recorded per skill:** the sleep runbook's step 5
  (`planning/portfolio-program/SLEEP-SESSION-RUNBOOK.md`) commits a `sleep:` message and appends a journal entry.
  W4 marks those entries as sleep sessions (and reads the skill's `sleep:` commits from git as a second source).
  The only runbook change: the promotion journal entry's filename or heading must contain "sleep", so the mark is
  reliable. "Not recorded" only when no such entry exists. (v0.3's CHANGELOG step is cut.)
Acceptance: researchPrime and Gandalf render against their folders with no hand-written rows.

## Part 2: the flow map

**W5. A flow file per skill, checked against the code.** Each skill folder gets `FLOW.json`: stages; steps (kind:
program / AI call / you decide / operator / orchestrator; title; one plain sentence; seat and count); a required
`swarm` field on the map and on each group (yes, with seat, count, concurrency cap and the knob that sets it; or
no); the review loop; exits with stop rules; the final deliverable. A step carries a **Code** anchor and an
**Instructions** anchor (an AI call: its caller and its prompt or heading); a side that does not exist is declared
`no-code` / `no-instruction`. Anchor types, never a bare line number:
- **callable**: file + function + the entry point that must reach it + the **consumer**: the caller that uses the
  result. Reachability follows static imports, `await import(specifier)` and string-keyed surfaces (researchPrime's
  `TRIO_SURFACE` / `TRIO_MODULES` in contract.mjs, the drivers import in live-round-agent.mjs) from the declared
  entry; the checker fails when that chain no longer reaches the function. It hashes the callee AND the consumer,
  so a change in how the result is used (e.g. the loop breaking on `obs.converged`, run-rounds.mjs, not on the
  Judge verdict) shows "code changed since this map was checked". Where the result is stored but unused, the step
  says so (`differs`).
- **heading**: instruction file + heading; fails if the heading is gone.
- **data**: the value the box displays, anchored to **what the running code actually uses, through the function
  that resolves it, including its HALT branches**; fails if the value differs. Every number a box or exit shows is a
  data anchor; no typed numbers. A value that can only HALT on a path (e.g. a formal run without a locked scope) is
  shown as the HALT, never as a number. The exact chains for researchPrime and Gandalf are in the W6 anchor notes.
- **prompt**: file + the function that builds the model's prompt text (e.g. `reviewerPrompt`, `defaultRefutePrompt`);
  an AI call's Instructions link uses this when no SKILL.md heading governs it.
- **conditional swarm**: a swarm shown only inside the condition that starts it, with that condition as a data
  anchor; the other branches are drawn too (researchPrime's panel: swarm only when spawning is on, the reviews
  are vacant, the artifact path is absolute and no sidecar is loaded; beside it the sidecar, HALT and
  supplied-reviews branches, per the W6 anchor notes).
- **env**: the knob's name and default, checked against where the code reads it.
- **no-code**: declared explicitly ("instructions only"), shown as such; not a failure.
`tools/flow-check.mjs` runs when the page loads a map and in the Foundry test gate. Known code-vs-SKILL.md
disagreements are data on the step (`differs`, with evidence), shown red.
Why hand-traced and machine-checked rather than generated: the control flow is spread across modules, knobs and
prose; a generated graph would be unreadable or wrong, which is what Superjump's judge rejected.
Reachability is a static check: a call that exists but is skipped at runtime by a condition is caught only when its
condition is anchored as data. Said, not hidden.

**W6. researchPrime, then Gandalf.** FLOW.json for both, re-anchored to the W5 types (the mockup's line-number
anchors are not copied). Each map is drawn to its OWN skill:
- researchPrime: a marked Parable-of-the-Oranges foresight step (oranges.mjs); the orchestrator as SKILL.md defines
  it (governor + round loop: heartbeat, one respawn, silence fatal); the review loop with its data-anchored exits;
  the deliverable naming the three summary levels and who writes them (the session, not the program).
- Gandalf: foresight is the ANTICIPATE part of the session's raw read (marked); the orchestrator is the CLI host
  (gandalf-run.mjs): ONE live refuter round or a zero-call grade, no loop; the analyze path as its own branch. Swarms,
  counts and deliverables per path exactly as in the W6 anchor notes.
Grok checks every anchor and every displayed number against the code before he sees it. Other skills
show "not traced yet" until he asks.

**W7. The disagreements become one ticket, not patches.** The 30 disagreements (18 researchPrime, 12 Gandalf) go
to `DISAGREEMENTS.md` in this effort folder with evidence; each skill's journal gets ONE entry pointing to it (the
ticket into a formal Foundry improvement cycle, AGENTS.md rule 1). Fixing them is not in this plan.

## Part 3: his 2026-10-02 evening asks

**W4c. The journal report** (mockup v4; built). Per skill, read from every journal entry (`journal-report/<id>.json`,
15 skills, about 880 entries): a two-sentence summary; 3–6 strengths and 3–6 weaknesses (each marked open or fixed,
each citing entry ids); 3–7 themes; and the entries organised **by batch of work** (what was being worked on, for
which project, dates, outcome) or **by date**. A Foundry job regenerates a skill's report whenever its journal gains an entry (and on each sleep cycle); the page
only reads the JSON. The job fails, keeping the last good report and saying so on the tile, when a cited entry id
does not exist, an entry sits in no batch or in two, or a weakness's open/fixed mark disagrees with the later
entries, LESSONS or CHANGELOG in either direction. Needed because he asked for it; dropping the regeneration costs a report that goes
stale after the next run.

**Correction (John, 2026-10-03):** the hierarchy he wants is **Poincaré** (hyperbolic) geometry, after Nickel &
Kiela 2017 (2–5 hyperbolic dimensions matched or beat 200 Euclidean ones on hierarchical data), with the **Lorentz**
model for computation; "Piaget" was a memory slip. Piaget keeps a later role: the sleep loop's assimilate /
accommodate cycle. The map is **derived and calibrated from real usage** (run records, journals, outcomes), not
hand-drawn; its purpose is **context management**: a mixture-of-experts router loads only the relevant branches into
the skill's context window. Concept: `poincare-maps/CONCEPT.md`. For THIS page, v1 draws a map **seeded** from the
traced process map and the skill's files and labels it "seeded, not yet calibrated"; building the usage-derived,
Lorentz-embedded maps into the skills themselves is **W9**, planned after the knowledge-map research.

**W5b. The Poincaré knowledge map, in his T2R cognitive-cell format** (the single definition; replaces v0.10's chain; mockup v6;
sources in `piaget-sphere/SOURCES.md`; Gandalf read `piaget-sphere/gandalf-read.json`, cross-family, 2 claims
grounded, 1 refuted). Each Foundry skill is treated as one T2R cognitive cell, and its sphere is that cell's
per-cell knowledge store drawn as his BASE-BRAIN-SPEC defines it: hierarchy by radius, general at the apex/center,
specific toward the rim.
- **Center:** the skill's focus questions (its question shapes; the North Star distilled). His "most important
  questions" and the spec's "most general" coincide here; importance below the center is shown by size, not radius.
- **Rings:** expert domains (the cell's experts: what its gate routes among) → methods and the skills it
  commissions → tools and code → places to look and learned shards (references, constants, LESSONS, journal themes).
- **Format on disk** (his PVB+P Kit concept-file shape, so the Foundry and the GWL brain share one format, minus the
  learned parts): `knowledge/` in the skill folder with one file per concept (front-matter `id, name, tags,
  parent_ids` (exactly one parent: a declared tree), `sibling_ids`, `ring` (must equal the node's depth in the
  tree), `facets`, `anchor` to a file or symbol);
  `graph.json` is that declared tree (`root_clusters → children`, without the kit's `centroid`), not the kit's
  GEO-derived analogy graph; and
  `worldview.md` (the top-level partition). The kit's `position` (ball coordinates the GEO worker owns and
  overwrites) is omitted until the later learned-geometry stage; v1 radius and sector come only from the declared
  tree. `tools/sphere-check.mjs` runs on page load and in the Foundry test gate and fails a node with no anchor, an
  anchored source that is missing or changed since the node was checked (the node shows "source changed"), a
  `parent_ids` / `graph.json` mismatch, a `ring` that disagrees with the node's tree depth, or a radius or sector read
  from anything but the tree (`position`, `ring`, a centroid).
- **Several dimensions:** facet lenses over the one hierarchy (where it comes from: instructions / code / learned /
  data; health: open weakness or code-vs-instructions disagreement; used by the process map; later certainty,
  recency, cost). His "a sphere, not a circle" is carried by the radial hierarchy plus these facet lenses. A 3-D globe
  is cut: in the research a 3-D viewer did worst and a globe hides half its nodes.
- **Joined to the process map:** each FLOW.json step stores the ids of the sphere nodes it uses; clicking either lights the other. Run records
  gain a "steps run" field copied from flags the engines already write (Gandalf e-2, grounded), which later gives
  real usage weights (his routing ledger).
- **Piaget learning cycle (later role) on the map** (his explicit ask, 2026-10-02: "this is useful and I want to incorporate
  this", mockup v3; no source document defines the stage rules, so they are his-to-review proposals): the development
  view sits inside the sphere tile: the developmental stage (1 sensorimotor: instructions only or under 3 uses; 2
  preoperational: used, nothing accommodated; 3 concrete operational: learns from experience; 4 formal operational:
  also has a traced process map that agrees with its code) and three tallies from his records (tallies, not a measure of learning; John's requested view, R10 G2 / R12 G1
  declined): experiences =
  the skill's journal entries; disequilibria = the journal report's weaknesses with their cited entries;
  accommodations = sleep cycles, LESSONS promotions and CHANGELOG entries. The disequilibria awaiting accommodation =
  the open weaknesses in the current report; Foundry home shows each skill's stage and that number. This wave
  does NOT attach journal prose to sphere nodes (Gandalf e-3: that mapping would be invented); the sphere tile lists
  the open weaknesses with their entries, and a node shows a hotspot only when a weakness carries node ids that
  sphere-check proves. The source card's journal list comes only from such proven ids.
  accommodation = sleep-cycle proposals to add, split, merge or move nodes, which
  he approves. The sleep loop does not emit node edits today (Gandalf e-3 refuted: LESSONS are prose), so W5b adds
  one structured field to the promotion record (`sphere_edits`). The disequilibrium signal stays the open weaknesses
  until runs record a prediction; only then does it become his §P5 predict → act → compare loop
  ("Cognition-Inspired Architectures" §P5).
- **The sphere is the default view** (his word, 2026-10-02, after the evidence that people find a named item faster
  in an outline): explore it like a library. Zoom with the wheel or buttons and drag to pan; click an expert domain to
  enlarge that sector to the full circle, with a breadcrumb back; click a node for its **source card**: a call
  number (skill › domain › ring › node), its shelf (folder), its instruction or code source with Open, the process
  steps that use it, and journal entries only where a weakness names this node and sphere-check proves it (otherwise
  no journal list). A search box above highlights matching nodes and lists
  them; an Outline toggle gives the same hierarchy as a list for finding a named item. For the agents, the same
  structure is the retrieval index; its geometry pays off once a skill's knowledge reaches hundreds of nodes.
- **v1 is the declared hierarchy, not learned geometry** (Aurora critique; T2R D3 defers Lorentz until depth > 3).
- First spheres: researchPrime and Gandalf (drawn in mockup v5), then the others on his word.

**W1b. The Steward at two levels.** Ecgberht is listed twice in the Foundry: "Steward: project (the Lamp / Salver /
Seal)" and "Steward: portfolio (the Cave of Wonders / High Seat)", each with its own process map and sphere, sharing
one skill folder: the named exception to one-FLOW-per-folder: `FLOW.project.json` / `FLOW.portfolio.json` and
`knowledge/project/` / `knowledge/portfolio/`, each tree with its own `graph.json`; sphere-check and the step-to-node
join walk both. This wave adds the two rows and reserves those files as not traced and not drawn. The persona labels follow his Anchor setting.

**W8. Campaign counsel (placeholder skill; Superjump `campaign-skill/superjump-result.md`; researchPrime
`research-campaign/REPORT.md`, https://claude.ai/artifact/SFJW7fVj5UoSUF1vRGx5bz, five Grok review passes).** A
variation of the Steward with its own name and remit for the Campaign page. It shares the Steward's memory and
delivery path, hands approved work to the High Seat, and changes nothing without his approval. What it does, by the
strength of the evidence:
- **Adopt (corroborated):** each goal has a specific done-when; each Tier-1 goal has one if-then next step; progress is
  recorded per goal.
- **Try (sensible, untested as such; each measured on John's own record before it is kept):** pace as near-term
  milestones; a guided "main obstacle?" exchange; a weekly look-ahead; a starvation check for important undated
  goals (deliberate pauses marked in the goal's guide do not count); a "park, boneyard or re-commit?" question; a
  premortem at goal creation or a slipped deadline; backward planning when a deadline is set, checked against his
  own past paces; nudges in two lanes (close dated items at a natural break with a ready-to-resume note; everything
  else batched into the look-ahead), each stating why and dismissible in one tap.
- **Try, goal words:** John writes them; the counsel asks questions and offers options (the evidence compared
  self-written with fully AI-written goals only), measured on his record like the other Try items.
- **Skip:** OKRs, the 12-week year, horizon scanning, formal scenario planning (no one-person evidence found).
- **Division of labour** (design by analogy): counsel = goals and foresight; High Seat = seating and a soft cap on
  active initiatives; project stewards = next actions; only one level nudges about any given item.
Names (one per persona; his pick between Superjump's two surviving sets): set 1, Basira (insight; the Astrolabe) /
Prospect (the Spyglass) / Ræd (counsel; the Counsel Book); set 2, Hikma (wisdom; the Astrolabe) / Foresight (the
Spyglass) / Ræd (the Beacon). This plan lists it in the Foundry as one
placeholder row (not a scanned SKILL.md), with no separate engine, goal store or work queue (Superjump's cut);
building it is its own effort (Crucible plan, Foreman build) on his word.

**W9. Poincaré knowledge maps inside the Foundry skills (to be planned after research).** Build each skill's map from
its run records, embed it in the Lorentz model, route context by it, and let the sleep cycle recalibrate it; test it
against a flat (linear) store at matched cost (his Tournament 1 design). Its own researchPrime run and plan first
(`poincare-maps/`); not in this page build.

## How it gets built and checked
- **This effort is run by the Steward** (his word): an Ecgberht cockpit for the Skill Foundry project holds the plan,
  the deliverables and his decisions; this session commissions the skills. Build on an Anchor branch; Foreman standard band for
  W1–W5 (each wave: execute, adversarial review on the review family, fix).
- Crucible not used: inputs converged (his words, a judged design, code traces), scope fixed and reversible;
  lightest band. He can ask for a Crucible LITE pass.
- **Declined review findings (R10 G2, R12 G1):** Grok asked to delete the Piaget developmental stages and tallies as
  unsourced; kept because John asked for them, labelled as tallies, and flagged for his review in Open item 5.
- **Plan review closed at R12** (R1–R8 to v0.8; R9–R12 on his evening asks): every finding applied except the one
  that is his decision.
- **His-screen acceptance:** on his machine at desktop and phone width: the masthead and colors beside a High Seat
  page; the A–Z list and icon sizes; one North Star; one Evolution row whose sleep mark comes from a real journal or
  LESSONS file; the skill file and the run command opened from the header; on each map the swarm boxes, every exit (researchPrime: dry,
  clean, cap or HALT) and the deliverable visible; and for one box of each map both the Code and the Instructions link opened and
  landing on the right passage; the journal report (summary, strengths, weaknesses, themes, by batch and by date) with
  one cited entry opened from a weakness; the sphere as the default view (zoom, pan, a domain enlarged, a source card
  opened through to its file, search, the outline toggle); the two Steward rows; the counsel placeholder with its
  names. Captured, not asserted. One Anchor restart at the end, on his word, after the idle check.

## Cut (Elegance rule 5)
- Fixing the 30 disagreements (own improvement cycle).
- Flow maps and spheres for every skill other than researchPrime and Gandalf, including both Steward levels (on his
  word, one at a time).
- The knowledge-map chain and title-keyword disequilibrium count (v0.10, replaced by W5b); the 3-D globe.
- Generated flow maps; the Anchor-native rebuild (v0.1); icon rewiring outside the Foundry page;
  writing new rows into foundry_map_v2.json (v0.2).

## Open for John (one at a time, after the mockup)
1. The mockup v6 (journal report, the sphere as default with zoom and source cards, the two Steward rows, the counsel
   placeholder and its names): does it match?
2. Should every skill ask 2–3 scoping questions before a substantial run (today only Ecgberht does)? The new-skill
   wizard asks them either way.
3. Einstein's North Star draft.
4. Register agy-dispatch, Chekhov and Einstein for Claude Code (add them to `~/.claude/skills`)?
5. The Piaget development view (four stage rules, sensorimotor → formal operational, and three tallies from your
   records): keep as drafted, or adjust? Grok twice advised removing them as unsourced; they stay because you asked
   for them, and they are tallies, not a measure of learning.

## Estimate (rough)
W1–W4 about a day of build and review; W5–W6 about a day; W7 an hour. His review time is separate.

## W6 anchor notes (facts from Grok R2–R4, to be verified again when FLOW.json is written)
- researchPrime round cap (`intake.mjs resolveBandRoundBudget`, called by run-rounds with failClosed): locked triage
  extension required, else HALT; then `--max-rounds`; then `RESEARCHPRIME_MAX_ROUNDS`; then the extension's
  `knobs.maxRounds`; else HALT. The contract's fallback 8 is never shown on this path. `includeAdjudication` is the
  extension knob, with the same HALT. mapping.mjs is only the table that seeds the extension at scope approval.
- researchPrime exits (`round.mjs makeConvergenceTracker`): dry when dryStreak ≥ N; clean when emptyStreak ≥ cleanN
  (default N+1). N, K and M all come from the same contract: the locked governor output's thresholds when usable
  (it has thresholds and a tier), else `deriveGovernorContract` (stage1Inputs when set; else preregistration for N,
  4 and 2 for K and M). Preregistration's K=2, M=0 marked `differs`.
- researchPrime panel: `runPanelRound` runs the three SHARK_ROLES seats together (serial when
  `RESEARCHPRIME_CONCURRENT_PANEL=0`) only when spawning is on (`spawnPanel`, `RESEARCHPRIME_LIVE_ROUND=1` or
  `RESEARCHPRIME_SPAWN_PANEL=1`), `isVacantReviews` is true (no reviews, or all with empty findings), the artifact
  path is absolute and no sidecar is loaded. Sidecar present: reviews loaded, no new swarm. Spawn on, vacant, no
  absolute artifact: HALT. Otherwise the supplied reviews are adjudicated.
- Gandalf grade path: with `--live`, swarm yes: refuters ≤ R=3, 2 at a time (`GANDALF_REFUTER_CONCURRENCY`, ceiling
  3); without it, the zero-call grade, swarm no. Both deliver read.json.
- Gandalf analyze path: deliverable is the graded JSON envelope (`gradeScaledReport`) at `--output` or stdout,
  degraded, refuters not run; SKILL.md's `out.md` example marked `differs`. No swarm on: the direct pass
  (`decideTier`), scout-then-fits, and a whole repo without `GANDALF_ALLOW_REPO_SCALE=1` (one degraded direct pass);
  otherwise shard readers in parallel, count from `resolveConsumeKnobs`: when locked (depth, tier, or a lock env: `GANDALF_DEPTH`,
  `FOUNDRY_TRIAGE_DEPTH`, `GANDALF_TIER`, `FOUNDRY_TRIAGE_TIER`) the band knobs, which the caller cannot override;
  unlocked, the caller's cap, or null when none was passed; `GANDALF_MAX_SHARDS` tightens a set cap and is the cap
  when it is null; concurrency from the map-reduce resolver
  (default 3).
