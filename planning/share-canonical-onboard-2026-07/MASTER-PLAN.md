# Master Plan (draft)

**North Star:** # North Star — Canonical skills root + full A/B onboard

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
| Host adapters drift | skills_root.json registry + per-host list_* + portfolio equality oracle (W0) |
| Dual product trees (Claude copy + SKILLS_ROOT) | Recipient: product bytes **once** under SKILLS_ROOT; Claude adapter = junction/symlink/pointer only; seal/upgrade must not leave a second tree |
| Journal write path split-brain | Single resolve helper `resolve_skill_journal_dir` (registry → SKILLS_ROOT/<id>/journal); realpath acceptance on simulated runs |
| Second onboard stack | Extend share_onboard / onboard_cli only; any new module maps onto named GREEN modules |
| Service “registered” but not running | B ready ≡ HTTP probe OK ∧ icon targets same local URL; probe fail ⇒ non-zero / not-ready / no B-complete Done |
| LITE under-planning multi-host | Locked plan document is mandatory input; inclusion test vs criteria |
| False portfolio GREEN via Claude-compat | Equality oracle ignores host-natives; must not pass on Claude-compat superset alone |

## Foresight

After this, Foundry sleep can consume author journals + optional intake; collaborators get one `/onboard` story; later hub at `C:\dev\skills` is optional cleanup, not required for GREEN.

## Process depth

**LITE** — single-pass Master Plan + Implementation Plan from locked CANONICAL plan; ≤1 Shark round; then Foreman build.


---

# Locked architecture plan (must not drift)

# Canonical skills access + full onboard (A/B) — Plan

**Date:** 2026-07-24  
**Status:** LOCKED by John 2026-07-24 — proceed Crucible LITE → Foreman  
**Scope:** (1) agent-independent skills + journal topology; (2) full guided onboard Packages A/B

---

## 0. Why this exists

Today’s stranger onboard is a thin non-interactive `python onboard.py` that copies skills into **`~/.claude/skills` only**. That is Claude-centric, confuses multi-engine users, and does not match how *this* author machine actually works (junctions into Foundry/trio). Journals, Foundry sleep, and opt-in friction share-back already have solid *library* pieces but are not wired into one guided `/onboard`.

John’s bar:

1. **One sense-making place** for skills — not “Claude’s folder is the universe.”
2. **Any agent** (Claude / Grok / Gemini-agy / Anchor) sees the **same** skill set.
3. **Journals** land where Foundry sleep can improve skills; **share-back is opt-in only**, sanitized.
4. **Onboard** = clone → `/onboard` (or one CLI) → home pick → Python/PATH → multi-host skills + AGENTS → ≥1 subscription → Package B: Anchor install + **start service** + **desktop icon**.  
   - **A** = skills only  
   - **B** = skills + Anchor

---

## 1. How it works **on this host today** (ground truth)

### 1.1 Authoring roots (source of truth for product skills)

| Root | Contents |
|------|----------|
| `C:\dev\Skill Foundry\skills\<name>\` | Foundry skills (gandalf, jumper, ZH, tidy-idy, …) + `journal/` |
| `C:\dev\trio\{researchPrime,crucible,foreman}\` | Trio engines + their journals |

### 1.2 How Claude sees them (why `~/.claude/skills` looks “odd” but works)

`C:\Users\john\.claude\skills\` is **not** a second copy of the product for foundry/trio — almost every product skill is a **junction**:

```
~/.claude/skills/gandalf      →  C:\dev\Skill Foundry\skills\gandalf
~/.claude/skills/foreman      →  C:\dev\trio\foreman
… etc.
```

Claude Code’s loader only scans **`~/.claude/skills`**. The junction farm is the adapter: Claude-shaped path, Foundry/trio-shaped truth. Journals written “under Claude’s path” are actually **in the Foundry/trio tree**.

Thin locals (agent-builder, expert-coder) are real directories under `~/.claude\skills` only.

### 1.3 How Grok sees them

| Location | Role |
|----------|------|
| `~/.grok/skills` | User skills (thin: check-work, help, …) |
| `~/.grok/bundled/skills` | Grok product skills (docx, design, …) |
| **Claude compat** | Scans `~/.claude/skills` by default |

Grok does **not** natively scan Foundry. It sees foundry/trio skills **because** they appear under Claude’s skills home (via junctions). If that farm breaks or onboard only **copies** into Claude without updating Grok, Grok still “works” via compat — but a pure-Grok machine with no Claude home would miss them unless we set `[skills].paths`.

### 1.4 How Gemini / agy sees them

Dual legacy:

- `~/.gemini/skills` junction farm (older skills-master path)
- `~/.gemini/config/skills.json` extra paths → trio + `Skill Foundry\skills`

Not the same mechanism as Claude.

### 1.5 What stranger onboard does (broken relative to the above)

`onboard.py` **COPY** (default) into `~/.claude/skills` only:

- No Foundry as source of truth on recipient
- No Grok path / config registration
- No Gemini registration
- No AGENTS.md multi-host install
- No home picker
- Service often `foreground_fallback`; no desktop icon in that CLI
- Journals: empty product trees (vendor denylist strips `journal/`) — correct for ship; local runs create **local** journals under the installed skill dirs

### 1.6 Journals + Foundry sleep + share-back (already designed)

**Local (always, no permission needed for local disk):**

```
<skill_dir>/journal/NNNN-<slug>.md     # human sleep feed (7 fields)
<skill_dir>/journal/runs/<ts>-id.json  # machine training record
```

Law: Skill Foundry `AGENTS.md` (two-layer capture). Sleep reads these under the **canonical skill dir**.

**Ship packages:** `vendor_skills` **denies entire `journal/`** — author journals never leave in the zip/git archive.

**Opt-in friction share (permission required):**

```
consent default OFF  (feedback_consent.json)
  → only if opted in: sanitize journal friction enums
  → allowlist fields only + de-identified install_key (random UUID)
  → fail-closed on PII / paths / secrets
  → offline queue
  → intake by_skill/  (W7) — NEVER auto-merge into main skill sources
  → human Foundry sleep pulls intake as signals, not code merge
```

Full journals **never** retro-upload when someone opts in later.

---

## 2. Canonical topology (PROPOSED LOCK)

### 2.1 One concept: **Skills Root** (agent-independent)

```
SKILLS_ROOT/
  <skill-id>/
    SKILL.md
    … implementation …
    journal/                 # always here (local runs only)
      NNNN-*.md
      runs/*.json
```

**Not** named “claude skills.” Claude/Grok/Gemini are **adapters** that *point at* this root.

### 2.2 Two modes

| Mode | Who | SKILLS_ROOT | Host adapters |
|------|-----|-------------|---------------|
| **Author** | John | Foundry `skills/` + trio skill dirs (indexed) | Junctions/registrations into each host |
| **Recipient** | Collaborator / consumer | `<HOME>/skills` (default Windows home `C:\dev` → `C:\dev\skills`) | Product bytes land **once** under SKILLS_ROOT (copy+seal from vendor default); every host adapter is pointer/config only — **no second product tree** |

**install_mode semantics (LOCKABLE — criterion 1):**

| `install_mode` | What is copied / linked | What is **banned** |
|----------------|-------------------------|--------------------|
| **`copy` (recipient default)** | Vendor pin → **only** `SKILLS_ROOT/<id>/` (then seal) | Second full skill tree under `~/.claude/skills`, `~/.grok/skills`, or any host home |
| **`junction` (author / advanced)** | Host adapter paths junction/symlink → existing author skill dirs (or hub) | Treating host adapter path as the durable product store |

`share_home_config` already proposed:

- `home/skills`
- `home/skill-journals` — **retire as a separate journal dump**; journals stay **inside each skill** so Foundry sleep and seal stay coherent. Optional `skill-journals` can be a **mirror/export staging** dir only, never the write path for live runs.

### 2.3 Host adapters (how every agent sees the same set)

**Law (criterion 1 — falsify dual trees):** Product skill **bytes exist once** under `SKILLS_ROOT/<id>/`. Hosts are adapters that **point at** that tree. Dual independent copies (SKILLS_ROOT **and** a full second tree under `~/.claude/skills`) are **banned**. Seal, upgrade, and re-onboard must not leave a second product tree.

| Host | Adapter mechanism (canonical) |
|------|--------------------------------|
| **Claude** | `~/.claude/skills/<id>` → **junction / symlink / pointer only** to `SKILLS_ROOT/<id>` (author **and** recipient). Claude never holds a second full product copy. If a host cannot create junctions/symlinks, document a **non-copy load** path (e.g. settings/skills path pointing at SKILLS_ROOT) — still no dual tree. |
| **Grok** | `[skills].paths = ["<SKILLS_ROOT>"]` in `~/.grok/config.toml` **plus** keep Claude-compat as backup; do **not** rely on Claude-only forever. Portfolio equality (criterion 2) must pass on Grok’s own path list, **not** via Claude-compat superset alone. |
| **Gemini/agy** | **Promote or demote in W0/W1:** either **first-class** (single `skills.json` entry → `SKILLS_ROOT`, in portfolio equality + `hosts_registered`) **or** explicitly **demoted** to best-effort/legacy (omitted from criterion-2 equality and readiness-required hosts). No half-registered “maybe.” Default for this effort if register is implemented: **promote** with single-entry → SKILLS_ROOT; stop growing dual skills-master farm. |
| **Anchor** | `ANCHOR_SKILLS_ROOT` / runner = `SKILLS_ROOT` only; **retire split** “install to Claude home vs run from Foundry” as two truths — one env, one root. Package A may register Anchor env/root without starting the service; `hosts_registered` must not claim Anchor if register did not actually run. |

**install_mode meaning (clarified):**
- `copy` = product bytes materialize under `SKILLS_ROOT` from the vendor pin (recipient default + seal).
- `junction` = SKILLS_ROOT entries (or author index roots) are junctions into Foundry/trio (author/advanced).
- Claude adapter is **always** pointer-to-SKILLS_ROOT, **never** a second copy mode.

Registry file written at onboard (portable):

```
<HOME>/governance/skills_root.json
{
  "schema": "skills-root/v1",
  "skills_root": "<absolute or ~ path>",
  "install_mode": "junction" | "copy",
  "hosts_registered": ["claude", "grok", "gemini", "anchor"],
  "portfolio_manifest": "<vendor-pin skill-id list ref or inline ids>"
}
```

**hosts_registered honesty:** list only hosts whose adapter register actually succeeded this run. Package A without Anchor product tree must **not** stamp `"anchor"` unless Anchor env/root registration ran and verified.

### 2.4 Global rules (AGENTS / CLAUDE / Grok Agents)

| Artifact | Canonical write at onboard |
|----------|----------------------------|
| Exportable rules body | `<HOME>/governance/AGENTS.md` (from share_governance_pack) |
| Claude | `~/.claude/AGENTS.md` + thin `CLAUDE.md` → pointer to governance or inlined body |
| Grok | `~/.grok/Agents.md` → pointer to same body (same as current thin pointer pattern) |
| Model prefs | `~/.anchor/model_prefs.json` (or `<HOME>/anchor/…`) coding/review family |

One body, multi-host pointers. No host-specific fork of seating law.

### 2.5 Journals (canonical + Foundry sleep)

**Single resolve helper (criterion 3 — named, mandatory):**  
`resolve_skill_journal_dir(skill_id) → Path`  
= read `<HOME>/governance/skills_root.json` (or in-process registry) → `skills_root` → `Path(skills_root) / skill_id / "journal"`.  
No alternate live write roots. Optional `home/skill-journals` remains **mirror/export staging only**.

| Rule | Detail |
|------|--------|
| Resolve | **Only** via `resolve_skill_journal_dir` (registry → `SKILLS_ROOT/<id>/journal`) |
| Write path | Always that resolved dir: `NNNN-*.md` + `runs/*.json` |
| Bindings | `share_skill_journal` + host runners (Claude/Grok/Anchor skill execution paths) **must** call this helper — not host-local cwd, not `~/.claude/skills/<id>/journal` as a separate store |
| Author machine | Junctions ⇒ sleep reads Foundry/trio trees (today’s win); realpath still under author skill dirs |
| Recipient | Journals accumulate **locally** under their `SKILLS_ROOT` skill dirs (one tree) |
| Ship | Never include `journal/` in packages (keep denylist) |
| Sleep | Operates on **author** Foundry/trio journals; recipient friction is separate feed |

**Hermetic acceptance (install layout alone is insufficient):** After register, a **simulated skill run** entered via Claude adapter path, Grok adapter path, and Anchor runner path must each create a journal file whose **`os.path.realpath` is under `realpath(SKILLS_ROOT)`**. Fail if any adapter writes under a second tree or host-local only path.

### 2.6 Opt-in share-back (canonical — already coded, must be in UX)

| Step | Behavior |
|------|----------|
| Onboard question | Exact `FEEDBACK_CONSENT_COPY` — default **No** |
| If No | No install_key; no queue; full local journals still fine |
| If Yes | Mint install_key; explain what is / isn’t shared; residual risk |
| Export | Sanitizer allowlist only; sealed tree only; fail-closed |
| Intake | `by_skill/` for Foundry sleep **signals**; never product_main_write |
| Opt-out later | Wipe key optional; stop queue drain |

---

## 3. Full onboard experience (product bar)

### 3.1 Packages

| Package | Contents | Onboard does |
|---------|----------|--------------|
| **A — Skills only** | Vendored skills @ pin + governance pack + skills_root registry helpers | Home → Python → install skills to SKILLS_ROOT → host adapters → AGENTS → seats → feedback consent → readiness |
| **B — Anchor + Skills** | Everything in A + Anchor product | All of A + install/scaffold Anchor + **start service** + **desktop icon** (local URL) |

### 3.2 Happy-path dialogue (user-visible)

**Cold-start entrypoint ranking (criterion 7):**
1. **Sole bootstrap (pre-skills):** `python -m share_onboard` (or `python onboard_cli.py` as thin alias into the same module). This is the only path that works on a machine with **no** skills installed yet.
2. **Post-install only:** `/onboard` skill wrappers (Claude/Grok) — available after skills land under SKILLS_ROOT; **not** the cold-start bootstrap.
3. **Silent/non-interactive** (`onboard.py` progress-only or `--non-interactive` without full dialogue): **never** stamps ready; exit non-zero or readiness=`not-ready` with explicit “interactive onboard required” (criterion 7 + 10).

Dialogue order:

1. **Get code** — `git clone <repo>` or unzip pin package; open terminal in root.  
2. **Start** — `python -m share_onboard` (cold-start); `/onboard` only after install.  
3. **Home** — recommend `C:\dev`; confirm.  
4. **Python** — detect; if missing, actionable install + PATH refresh (or link); hard fail if still missing.  
5. **Package mode** — A vs B (auto-detect from tree if only one present).  
6. **Permissions** — list writes; continue.  
7. **Install skills** → `SKILLS_ROOT` (one product tree); register host **adapters** (Claude pointer-only, Grok paths, Gemini per promote/demote, Anchor env).  
8. **Governance** — write AGENTS pack + host pointers.  
9. **Subscriptions** — probe claude / agy / grok; **zero-seat matrix** bound to stamp+exit (see W2/W3).  
10. **Feedback** — opt-in default No.  
11. **If B** — scaffold Anchor data; mint token (path only); **start service**; **desktop icon** only if probe path is defined; B-complete only on dual gate (W4).  
12. **Done** — print readiness stamp; Package A never requires service; Package B Done only if B ready.

### 3.3 Implementation notes (build waves — for Crucible/Foreman)

Suggested wave split (LITE plan → Foreman):

| Wave | Outcome |
|------|---------|
| W0 | Lock skills-root registry + **portfolio ID manifest + per-host list_* + equality oracle** + adapter contracts (**before** install work) |
| W1 | Product bytes once under SKILLS_ROOT; multi-host **pointer** register; journal resolve helper + realpath simulated-run acceptance |
| W2 | Interactive CLI sole bootstrap `python -m share_onboard`; zero-seat matrix; silent path non-ready; feedback copy |
| W3 | Package A E2E + readiness stamp; hosts_registered honesty; portfolio equality passes |
| W4 | Package B **split gates**: (a) failure must not lie; (b) B ready ≡ HTTP OK ∧ icon same URL |
| W5 | Docs: user instructions email-ready; no-license rights line |
| W6 | Gate: sandbox run transcript = exact user-visible output |

Reuse: `share_onboard`, `share_home_config`, `share_governance`, `share_feedback`, `onboard.install_skills`, `vendor_skills`, `share_skill_journal`, desktop shortcut helpers — **extend, don’t second-stack**.

**Extension map (criterion 8 — any new surface must land here):**

| Need | GREEN module to extend (no second stack) |
|------|------------------------------------------|
| Registry / resolve / adapters | `share_home_config` / `share_topology` or thin `share_skills_root` **inside** Anchor share package |
| Install product skills to SKILLS_ROOT | `onboard.install_skills` + `vendor_skills` |
| Journal write/resolve | `share_skill_journal` (bind `resolve_skill_journal_dir`) |
| Governance / AGENTS pointers | `share_governance` |
| Feedback consent / export | `share_feedback` |
| Guided dialogue / readiness stamp | `share_onboard` / onboard_cli / `share_readiness` |
| Seal / upgrade single tree | existing seal helpers (`share_skill_seal` etc.) — must not dual-copy |
| Desktop icon | existing create_shortcut / setup_shortcut helpers |
| B service start + probe | existing Anchor service/supervisor helpers |

---

## 4. Migration for **this** (author) machine

1. Treat **Foundry + trio** as author SKILLS_ROOT(s) with one **index** (map.json / skills_root.json).  
2. Keep Claude junctions (already correct).  
3. **Add** Grok `[skills].paths` → Foundry skills dir + trio parents (or a single aggregated root if we add a junction hub at `C:\dev\skills` → children).  
4. **Normalize** Gemini to the same index; stop growing skills-master dual farm.  
5. Point Anchor `ANCHOR_SKILLS_ROOT` at the same index.  
6. Do **not** move monorepos on day one — hub + adapters is enough.

Optional later: `C:\dev\skills` as junction hub:

```
C:\dev\skills\gandalf → Skill Foundry\skills\gandalf
C:\dev\skills\foreman → trio\foreman
…
```

All hosts point only at `C:\dev\skills`.

---

## 5. Explicit non-goals (v1 of this plan)

- Auto-install Node/Claude/agy/Grok installers beyond detect + fix-links (Python is the hard dependency).  
- Open-source license (none for now — rights reserved).  
- Auto-merge of recipient friction into skill main.  
- Shipping author journals.  
- Making OpenClaw first-class (real copies only if ever needed).

---

## 6. Success criteria

1. A user who never heard of Claude’s folder can explain: “skills live in my skills root; each agent is told where that is.”  
2. Claude, Grok, and Anchor all list the same portfolio skill IDs after onboard.  
3. A skill run on any host writes journal under that skill’s dir on SKILLS_ROOT.  
4. Feedback export impossible without explicit opt-in.  
5. Package B ends with **running service + desktop icon**.  
6. Package A never requires Anchor service.  
7. Sandbox transcript of onboard is the email-ready “what you will see.”

---

## 7. Decision log

| ID | Decision | Recommendation |
|----|----------|----------------|
| D1 | Skills root naming | Agent-independent `SKILLS_ROOT` under chosen home; Claude path is adapter only |
| D2 | Author topology | Keep Foundry + trio monorepos; add hub/index; don’t force monorepo merge in v1 |
| D3 | Recipient install | Product bytes **once** under SKILLS_ROOT (copy+seal default); Claude adapter always junction/symlink/pointer — **never** dual copy; author junction mode for Foundry/trio index |
| D7 | Portfolio equality | Frozen vendor-pin ID manifest; per-host list_*; equality ignores host-natives; must not pass via Claude-compat alone |
| D8 | Journal resolve | Single `resolve_skill_journal_dir`; realpath under SKILLS_ROOT on simulated multi-host runs |
| D9 | Package B ready | Dual gate: HTTP probe OK ∧ icon targets same local dashboard URL; probe fail ⇒ not B-complete |
| D10 | Cold-start | `python -m share_onboard` sole bootstrap; `/onboard` post-install only; silent path never ready |
| D4 | Journal location | Always under skill dir; no separate live journal root |
| D5 | Share-back | Keep existing opt-in sanitizer + intake; wire into onboard UX |
| D6 | Build path | Crucible LITE → Foreman on this plan after go |

---

## 8. Next action

**John go** on this plan as LOCKED → Crucible LITE on intent “full A/B onboard per this doc” → Foreman implement.


## Success criteria
- SKILLS_ROOT agent-independent; Claude/Grok/Gemini/Anchor are adapters only
- After onboard same portfolio skill IDs on Claude, Grok, Anchor
- Journals only under SKILLS_ROOT/<skill>/journal/; never ship journal/
- Feedback export opt-in default off; sanitizer + install key; no auto-merge
- Package A skills-only full guided onboard
- Package B = A + Anchor + service running + desktop icon local
- Interactive CLI//onboard not progress-only silent installer
- Reuse share_* GREEN modules; no second distro stack
- No open-source license stamp

Phased plan for agent-independent SKILLS_ROOT plus full guided Package A/B onboard, extending existing Anchor GREEN share_* / onboard / vendor_skills surfaces only (no second distro stack). Front-load registry contract, multi-host adapters, journal-under-skill law, interactive dialogue, then A→B E2E with service+icon proof, docs (rights reserved), and sandbox transcript as the user-visible bar. Author Foundry+trio hub migration is explicit and non-blocking for recipient GREEN.

## Phase 1 — W0 — skills-root registry + adapter contracts + portfolio equality (BEFORE install)

Serves criteria **1–2** and **8**. **Must complete before W1 install work** so portfolio GREEN cannot be faked later.

**North Star restored:** criterion 2 (same portfolio skill IDs on Claude, Grok, Anchor); criterion 1 (adapters only).

**Near-term specifics:**
- Add schema skills-root/v1 (or extend share_schemas) with required fields: schema, skills_root (abs or ~ path), install_mode junction|copy, hosts_registered subset of claude|grok|gemini|anchor, portfolio_manifest ref; write target <HOME>/governance/skills_root.json via share_home_config / share_governance seam.
- **Freeze portfolio ≡ vendor-pin ID manifest** (ordered/set of skill IDs shipped by `vendor_skills` pin). This set is the only portfolio definition for equality. Host-native skills (e.g. Grok bundled docx/design, Claude thin locals not in pin) are **out of portfolio**.
- **Per-host list functions** (contract stubs, implemented fully in W1): `list_portfolio_ids_claude(home)`, `list_portfolio_ids_grok(home)`, `list_portfolio_ids_anchor(home)` — each returns skill IDs the host would load from **its adapter registration to SKILLS_ROOT**, not a host-native inventory dump.
- **Equality oracle (criterion 2 acceptance):**  
  `set(list_portfolio_ids_claude) == set(list_portfolio_ids_grok) == set(list_portfolio_ids_anchor) == set(vendor_pin_manifest)`.  
  **Falsify false GREEN:** oracle **must fail** if Grok (or others) only “see” portfolio via Claude-compat superset while `[skills].paths` does not include SKILLS_ROOT; must ignore host-natives so extras do not break equality; must fail if any required host misses a pin ID.
- **Gemini promote-or-demote decision recorded in W0:** if promoted, add `list_portfolio_ids_gemini` to equality; if demoted, document exclusion from criterion-2 bar and do not stamp gemini in hosts_registered as required for ready.
- Define adapter contract surface (pure functions under Anchor share package, e.g. extend share_topology / thin share_skills_root — **extension map, not second stack**): `resolve_skills_root(home)`, `write_registry(doc)`, `register_host(host, root, mode)`, `resolve_skill_journal_dir(skill_id)` stubs with deterministic side-effect descriptions for tests.
- Contract tests (pytest under Anchor/tests): round-trip registry JSON; reject unknown install_mode/hosts; assert each host’s registration target is documented (Claude: pointer/junction only under ~/.claude/skills/<id> → SKILLS_ROOT/<id>; Grok: ~/.grok/config.toml [skills].paths; Gemini: per promote/demote; Anchor: ANCHOR_SKILLS_ROOT / runner env only).
- Golden fixtures: sample skills_root.json for junction-author and copy-recipient modes; hosts_registered lists only hosts that “registered” in the fixture; portfolio_manifest matches vendor-pin golden.
- Wire schema validation into existing share_contracts / share_readiness hooks so later waves fail closed on missing registry — do not invent a parallel config store.

**Acceptance that falsifies false GREEN:** unit test where Grok paths omit SKILLS_ROOT but Claude farm is populated → equality oracle **FAILS**. Test where host-native IDs are present → oracle still **PASSES** if pin IDs match.

**Deferred (explicitly):**
- Live multi-host file writes and install_skills body (W1).
- Interactive CLI dialogue and FEEDBACK_CONSENT UX (W2).
- Package A/B E2E readiness stamps (W3–W4).
- Optional C:\dev\skills junction hub and author monorepo merge (author migration / later cleanup).

## Phase 2 — W1 — SKILLS_ROOT install + multi-host register + journal law

Serves criteria **1–3** and **8**: one product tree, adapters only, journals under skill dirs via named resolve; no dual Claude copy.

**North Star restored:** criterion 1 (SKILLS_ROOT one truth; adapters only); criterion 3 (journals only under SKILLS_ROOT/<skill>/journal/).

**Near-term specifics:**
- Extend `onboard.install_skills` / `vendor_skills` so product skills land **only** under `SKILLS_ROOT/<id>/` (recipient default: `<HOME>/skills` via share_home_config `home/skills`). SKILLS_ROOT is the truth store — not `~/.claude/skills`.
- install_mode: recipient default **copy into SKILLS_ROOT** + seal (`share_skill_seal`); author/advanced junction into Foundry/trio index; both stamp skills_root.json install_mode + skills_root absolute path + portfolio_manifest.
- **Claude adapter (LOCKABLE — ban dual copy):** `~/.claude/skills/<id>` is **junction/symlink/pointer only** → `SKILLS_ROOT/<id>` for **both** author and recipient. **Forbidden:** full second copy of product bytes under `~/.claude/skills`. Seal/upgrade/re-onboard paths must assert: for each portfolio id, Claude path is link/pointer or documented non-copy load; `realpath(claude_skill_dir) == realpath(SKILLS_ROOT/id)` (or equivalent pointer proof). **Falsify false GREEN:** after “success” register, two independent trees with divergent content → **FAIL**.
- **Grok adapter:** set `[skills].paths` to include SKILLS_ROOT in `~/.grok/config.toml`; Claude-compat may remain as backup but criterion-2 equality uses Grok path registration, not compat alone.
- **Gemini/agy:** execute W0 promote-or-demote; if promoted, single skills.json entry → SKILLS_ROOT; do not grow dual skills-master farm on new register.
- **Anchor adapter:** `ANCHOR_SKILLS_ROOT` / skill_runner root = SKILLS_ROOT only; one env, one root for new installs.
- **Journal law + named helper:** implement `resolve_skill_journal_dir(skill_id)` as the **only** live resolve path (registry → `SKILLS_ROOT/<id>/journal`). Bind `share_skill_journal` and host runners to it. Keep vendor_skills denylist of entire `journal/`. `skill-journals` home subdir = mirror/export staging only (docs/comments; no live write).
- **Hermetic journal acceptance (criterion 3 — beyond layout):** After register in temp home, simulated skill run via Claude adapter entry, Grok adapter entry, and Anchor runner each write a journal file; assert `realpath(written_file).startswith(realpath(SKILLS_ROOT))`. Layout-only tests without a simulated write are **insufficient**.
- **Portfolio equality (from W0):** after register, run equality oracle; ship package still strips journal/.

**Deferred (explicitly):**
- Full interactive home/Python/permissions dialogue wiring (W2).
- Package A readiness stamp and Package B service/icon (W3–W4).
- Author machine migration of live Foundry+trio index and optional hub (separate phase).
- Deprecating/removing legacy ~/.gemini/skills junction farm entirely on existing author machines (normalize over time).
- OpenClaw first-class registration.

## Phase 3 — W2 — Interactive onboard_cli / /onboard dialogue

Serves criteria **4, 7, 8** and UX spine for **5–6**: guided onboard, not silent installer; feedback opt-in fail-closed; cold-start ranking and seat matrix are lockable.

**North Star restored:** criterion 7 (interactive onboard); criterion 4 (feedback opt-in).

**Near-term specifics:**
- Extend `share_onboard` + onboard_cli (`python -m share_onboard` / `onboard_cli.py` alias) — **sole cold-start bootstrap**. Thin `/onboard` skill wrappers for Claude/Grok are **post-install only** (after SKILLS_ROOT has the onboard skill). No second installer stack (extension map).
- Dialogue steps in order: (1) home picker recommend C:\dev (`share_home_config.recommend_home_dir`), (2) Python detect + PATH fix links; hard fail if missing, (3) package mode A|B auto-detect from tree if only one present, (4) permissions list of writes then continue, (5) install skills → register hosts (W1), (6) governance pack + host AGENTS/CLAUDE/Grok pointers (`share_governance`), (7) probe claude/agy/grok seats, (8) feedback question exact `FEEDBACK_CONSENT_COPY` default No — mint install_key only on Yes (`share_feedback`); if No: no key, no queue; local journals still allowed, (9) if B: hand off to W4 steps, (10) print readiness stamp + try /gandalf / open dashboard (B only if dual gate).
- **Zero-seat readiness matrix (bound to stamp + exit):**

| Coding-capable seats | Stamp | Exit | Notes |
|---------------------|-------|------|-------|
| ≥1 (any of claude/agy/grok) | `ready` or `ready-degraded` (one family) | 0 | Degraded message lists missing families |
| 0 | `not-ready` | non-zero | Honest “install ≥1 subscription CLI”; skills/governance may still be on disk |

- **Silent path non-ready (criterion 7):** progress-only / non-interactive `onboard.py` without full dialogue **must not** stamp `ready`; exit non-zero or `not-ready` with reason. **Falsify false GREEN:** silent path prints success/ready without home/Python/permissions/feedback steps → **FAIL**.
- Default-off consent: export impossible without opt-in; no retro-upload of full journals when opting in later (document + assert in tests).

**Deferred (explicitly):**
- Package A full E2E readiness artifact and gate matrix (W3).
- Reliable Anchor service start + desktop .url + dashboard HTTP prove (W4).
- Auto-install of Claude/agy/Grok CLIs beyond detect + fix-links.
- Sandbox full transcript golden as ship gate (W6).

## Phase 4 — W3 — Package A end-to-end (skills-only)

Serves criteria **5, 1–4, 7–8**: skills + governance + multi-host register + readiness without requiring Anchor **service**.

**North Star restored:** criterion 5 (Package A); criterion 2 (portfolio equality); hosts_registered honesty.

**Near-term specifics:**
- Package A path: vendored skills @ pin + governance pack + skills_root registry + host adapters + feedback consent + readiness stamp (`share_readiness` / existing readiness report).
- **hosts_registered honesty (Package A):** if Anchor product is not installed / Anchor register not run, do **not** list `"anchor"` as registered. If A registers Anchor env root only (no service), list anchor only when that register step actually succeeded; never imply service-up. **Falsify false GREEN:** Package A stamps hosts_registered including hosts not touched → **FAIL**.
- **Acceptance:** after A onboard in hermetic temp home: skills_root.json present; product bytes only under SKILLS_ROOT; Claude paths are pointers not second trees; W0 equality oracle PASSES for claude/grok/(anchor list if registered); **no** Anchor service start attempted; readiness does not require dashboard; zero-seat → not-ready per W2 matrix; silent path not used for ready stamp.
- AGENTS body at <HOME>/governance/AGENTS.md; Claude ~/.claude/AGENTS.md + thin CLAUDE.md pointer; Grok ~/.grok/Agents.md pointer; model prefs path documented if written.
- Regression: vendor/ship still denies journal/; feedback export blocked when consent false; simulated journal realpath under SKILLS_ROOT (W1 acceptance re-run).
- Idempotent re-run / rollback using existing run_share_onboard / rollback_share_onboard patterns; re-run must not create dual Claude copy.

**Deferred (explicitly):**
- Package B Anchor install, service, token path, desktop icon (W4).
- Email-ready user docs and rights-reserved line as ship artifacts (W5).
- Author-only junction hub at C:\dev\skills.

## Phase 5 — W4 — Package B (Anchor + service + desktop icon)

Serves criterion **6**: B = all of A + Anchor scaffold + **service running** + **desktop icon** to local dashboard; token path-only.

**North Star restored:** criterion 6 (service running + desktop icon). Split gates so neither probe nor icon can lie alone.

**Near-term specifics:**
- B path reuses A then: install/scaffold Anchor data dir under chosen home; mint token (path-only, never print secret body in transcript if policy already forbids); start service via existing service/supervisor helpers; place desktop icon via existing shortcut helpers.

**Split gates (LOCKABLE):**

**(a) Failure path must not lie**  
- If service start fails, falls back to foreground-only, or HTTP probe fails: stamp **`not-ready` / B-incomplete**, exit **non-zero**, print **honest failure** (no “success” / “B complete” / ready that implies live dashboard).  
- **Forbidden:** silent `foreground_fallback` counted as success.  
- **Falsify false GREEN:** start fails or probe fails but Done says B ready → **FAIL**.

**(b) B ready ≡ conjunction (not either/or)**  
`B_ready ⇔ (HTTP(S) probe local dashboard == OK) ∧ (desktop icon exists ∧ icon target URL == that same local dashboard URL)`.  
- Icon **never** substitutes for live service.  
- Probe OK without icon → not B-complete (icon is happy-path required).  
- Icon present with probe fail → not B-complete.  
- **Falsify false GREEN:** icon-only or “registered service” without HTTP OK → **FAIL**.

- Desktop icon placement is part of happy-path B Done, not optional docs note.
- Tests: hermetic B with mocked service start **success** and **failure** branches; probe fail branch; icon path + URL match assertion; A still never requires service.

**Deferred (explicitly):**
- Windows service hardening beyond current start path (e.g. full NSSM/task-scheduler redesign).
- Auto taskbar pin beyond desktop .url if not already GREEN.
- Remote/tunnel dashboard; multi-user service accounts.

## Phase 6 — W5 — Docs + rights-reserved (no OSS license stamp)

Serves criterion 9 and success foresight: email-ready stranger instructions without open-source license stamp; rights reserved per John 2026-07-24.

**Near-term specifics:**
- User-facing onboard doc: clone/unzip → **cold-start** `python -m share_onboard` (sole bootstrap; `/onboard` only after skills install) → what A vs B does → home/Python/seats/feedback → B service+icon dual gate; plain English matching dialogue order; rights-reserved line.
- Explicit rights-reserved / no open-source license line in ship docs and package metadata; do not add MIT/Apache/etc. stamps.
- Cross-link readiness Done strings to doc so support email can paste sandbox transcript later (W6).

**Deferred (explicitly):**
- Public GitHub open-source release process.
- Marketing site / video walkthrough.
- Non-English localization.

## Phase 7 — W6 — Sandbox transcript gate (user-visible bar)

Serves criterion 10 (sandbox transcript = honest what the user sees) and premortem (3): extend onboard only; transcript is the canonical bar for Stage-2/Foreman acceptance.

**Near-term specifics:**
- Record hermetic interactive (scripted stdin) Package A and Package B onboard transcripts as golden fixtures under Anchor tests or planning ship gate.
- Assert transcript contains: home recommend, Python step, permissions, package mode, feedback default No wording from FEEDBACK_CONSENT_COPY, readiness lines (including zero-seat not-ready if scripted); B adds **probe result** + desktop icon path **or** honest fail / not-ready (never B-complete on probe fail).
- CI/share_ci_ship_gate style check: drift of user-visible strings fails the gate; silent installer path must not appear as ready/pass.
- Document that email-ready “what you will see” = this transcript.

**Deferred (explicitly):**
- Live video capture of GUI dashboard beyond CLI transcript.
- Cross-OS non-Windows transcript matrix (Windows is primary host bar for this effort).

## Phase 8 — Author migration — Foundry+trio index (non-blocking for recipient GREEN)

Serves criteria 1–2 foresight on the author machine without blocking stranger Package A/B GREEN; keep monorepos, add index/adapters only.

**Near-term specifics:**
- Author skills_root index (map.json / skills_root.json) over Skill Foundry skills/ + trio skill dirs; keep existing Claude junctions.
- Add Grok [skills].paths → Foundry skills + trio parents (or index roots); point Anchor ANCHOR_SKILLS_ROOT at same index; normalize Gemini to same index on register.
- Document that recipient path remains: product bytes **once** under SKILLS_ROOT (copy+seal) with Claude **pointer-only** adapters — independent of author Foundry/trio junctions; no dual tree on either mode.

**Deferred (explicitly):**
- Optional C:\dev\skills junction hub with children → Foundry/trio (all hosts point only there).
- Merging Foundry + trio monorepos.
- Moving Gandalf (already at Foundry skills/gandalf; Claude path is junction only).
- Recipient friction auto-merge into skill sources; shipping author journals; Foundry sleep intake productization beyond existing by_skill/ signals.

---

## AMENDMENT A1 — Icons & branding (LOCKED John 2026-07-24 with Master Plan approval)

**Status:** LOCKED with Master Plan approval 2026-07-24 — must appear in Stage-2 waves and Foreman acceptance.

### Feedback consent placement (confirmed, unchanged)
Interactive onboard step **8** (after seats, before Package B service/icon):
- Exact FEEDBACK_CONSENT_COPY; **default No**
- Yes → install_key + optional sanitized friction only
- No → full local journals OK; no export; not a readiness gate

### Icon / branding acceptance (NEW — required for Package B happy path; skill icons for A install assets)

1. **Desktop Anchor icon (universal mark)**  
   - Package B places a desktop shortcut that opens the **same local dashboard URL** used by the HTTP probe.  
   - Shortcut MUST use the universal **nchor.ico** (IconLocation / equivalent via create_shortcut.py or same contract).  
   - Bare .url without Anchor icon is **not** B-complete for branding.  
   - Acceptance: desktop shortcut exists + IconLocation (or OS-visible icon resource) is nchor.ico + target URL matches live dashboard.

2. **Browser tab favicon**  
   - Package B ship includes nchor.ico / nchor.png (and existing favicon routes in Anchor product).  
   - After service up: GET /favicon.ico and/or /anchor.ico returns the asset; HTML includes rel=icon.  
   - Acceptance: probe path includes favicon asset OK (or documented link tag present on dashboard HTML).

3. **Skill icons for Skill Foundry / dashboard**  
   - Portfolio skill brand icons (/vendor/brand/* and any skill-local icons used by Foundry GUI) install with the product / skills tree.  
   - Skill Foundry (and dashboard skill lists) show those icons without broken images for each portfolio skill ID (or a documented default fallback icon).  
   - Package A still lands skill assets under SKILLS_ROOT so B/Foundry can show them later.  
   - Acceptance: hermetic check that icon URLs/paths for portfolio skills resolve after onboard.

4. **W4 dual gate remains**  
   B_ready ⇔ HTTP dashboard OK ∧ desktop shortcut (with **anchor.ico**) targets same URL.  
   Icon branding failures (missing ico, broken skill icons) are **not-ready / B-incomplete** for branding criteria even if service is up — document as explicit acceptance in IMPLEMENTATION-PLAN.

**Waves touched:** W1/W3 (ship brand + skill icon assets with product/skills); W4 (desktop create_shortcut + favicon probe); W6 (transcript notes icon steps if user-visible).

