# Ship Anchor v1 (full foundry suite + cross-platform onboard + Tailscale) — MASTER PLAN (FROZEN)

> Crucible, 2026-07-01. Branch `ship-anchor-v1` off Anchor master. This is the **delta** on top of the
> already-GREEN `planning/share-distro-v1/` effort (12 waves, 2026-06-23): distro.py + dist_manifest.txt +
> vendor_skills.py + onboard.py + the repo-local `/onboard` skill + enable_remote.ps1 all exist and pass.
> This plan REUSES those modules — never forks them — and closes the gap to a shippable v1.
> Prior work read via three deep surveys + a canonical-gandalf hunt (Gandalf-style read), diffed against
> the share-distro-v1 doc-trio.

## North Star (LOCKED — John, 2026-07-01)
A collaborator receives the Anchor repo as a **zip/tarball**, runs **one onboard** to get Anchor plus the
**full foundry skill suite** running locally on their machine (Windows / macOS / Linux), and optionally runs
a **second onboard (onboard2)** to reach that service from another computer over **Tailscale** (as John reaches
gwl-server). The shipped distro carries the **10-minute-summary discipline + locked "Status table" format** and
lets the collaborator opt into **auto-run (with-permission)** and **low-verbosity** at onboard time. It ships
**zero** of the author's personal data, secrets, or host paths — enforced by distro.py's existing scans.

## Skill roster (LOCKED — John, 2026-07-01)
**Ship (12 vendored skills + the repo-local `/onboard`):**
- Trio front-end + planning + build: **researchPrime, crucible, foreman**
- Deep-think + ideation: **gandalf** (canonical source found — see D2), **jumper** (needs gandalf as a sibling)
- Ready, self-contained: **expert-coder, agent-builder, figure-designer, zombie-hunter, legal-beagle,
  literature-review, ramanujan**

**Defer to a fast-follow ("improve first" — John):** **financial-analyst** (25 MB w/ node_modules; slim/rework
needed) and **helping-hand** (hard-wired to John's PRIVATE Aurora `aurora-kb` MCP; useless to collaborators
without it).

**Exclude:** **tidy-idy** (John).

## Locked decisions
1. **Reuse the GREEN share-distro-v1 machinery** — distro.py (deny-by-default + 4 scans: personal-email,
   build-host-path, auth-token, stdlib-only-import), dist_manifest.txt, vendor_skills.py, onboard.py, the
   repo-local `/onboard` skill, enable_remote.ps1. This plan EXTENDS them; it does not rewrite them.
2. **Canonical gandalf = `C:\dev\Skill Foundry\skills\gandalf\`** — a self-contained Node engine (SKILL.md +
   `runtime/` incl. `runtime/seam-pass.mjs` + `seam/*.mjs`), NO external npm deps, actively developed
   (judgment-first tiering). It IS bundleable.
3. **Jumper needs NO code surgery.** Its only gandalf dependency is a *sibling* relative import
   (`../gandalf/runtime/seam-pass.mjs`, using `applySeamPass` / `SCHEMA_VERSION='gandalf-advisor-1'` /
   `SeamPassInputError`). Once onboard installs jumper and gandalf side-by-side in the skills home, it resolves.
   "Unblock jumper" = bundle both as siblings + a resolution test.
4. **Data-driven roster via a source map.** vendor_skills.py grows a roster manifest (skill → source dir →
   `git archive` vs. clean-copy). Sources: Skill Foundry repo (`C:\dev\Skill Foundry\skills\<name>`: gandalf,
   jumper, figure-designer, legal-beagle, literature-review, ramanujan, zombie-hunter); the trio repo
   (`ANCHOR_TRIO_DIR`: researchPrime, crucible, foreman); and agent-builder + expert-coder (source resolved at
   build via the map — env `ANCHOR_FOUNDRY_DIR`/per-skill override). Every source path is an injectable seam so
   tests use temp git repos and NEVER read the author's real dirs.
5. **node_modules are NOT shipped.** `git archive` already drops them (gitignored). Vendored Node skills ship
   source-only; **onboard runs `npm install --omit=dev`** for any bundled skill that has a `package.json` with
   a non-empty `dependencies`, gated on `node` present, best-effort with an honest skip when node is absent.
   gandalf is dependency-free, so the trio front-end works even with no npm.
6. **Preferences are opt-in via onboard prompts, never silent.** onboard ASKS the collaborator two questions —
   (a) enable **auto-run (with-permission)** and (b) enable **low-verbosity** — and writes the matching Claude
   Code config (settings.json permissions/mode for auto-run; an output-style/instruction for low-verbosity)
   ONLY on opt-in. Decline = no-op. Idempotent and reversible.
7. **The operating discipline ships as AGENTS.md.** A distro-root `AGENTS.md` (the canonical instructions per
   the workspace convention) carries the **10-minute-summary rule**, the **exact locked "Status table" format**,
   and the low-verbosity rule, so a collaborator's agent inherits the cadence. CLAUDE.md/GEMINI.md stay thin
   pointers to it.
8. **onboard2 = cross-platform Tailscale remote access.** Formalize enable_remote.ps1 into a documented
   onboard2 flow: keep the Windows PowerShell path (edit service env `ANCHOR_TOKEN`/`ANCHOR_BIND` + Tailscale
   dependency + restart) and ADD a POSIX path (macOS/Linux via `tailscale serve`). **Hard guard: refuse to
   expose the service without an `ANCHOR_TOKEN` set** — closes the known gap where the bind guard misses the
   same-box proxy path.
9. **Delivery = zip/tarball, no GitHub push.** The final wave builds the scrubbed distro to a folder, packages
   it to a zip/tarball, and clean-room-verifies an onboard from the unpacked archive. `publish_distro` (the
   GitHub path) stays available but is NOT exercised for v1.
10. **Every gate stays hermetic and Windows-safe.** The gate host is Windows; cross-platform done-whens run via
    faked-platform / dependency-injected seams (never `pytest.skip` as sole coverage — the rnd-v12 vacuous-GREEN
    lesson). Temp HOME/skills-home/data-dir/source-repos; stubbed `ANCHOR_SERVICE_CMD`/`ANCHOR_FOREGROUND_CMD`/
    `ANCHOR_TRIO_DIR`/`ANCHOR_FOUNDRY_DIR`; NEVER bind `:8777`, spawn a real server, register a real service,
    run real `npm`/`tailscale`, or hit the network.

## Architecture (reuse + extend)
- **`vendor_skills.py`** — generalize from the fixed 4-skill set to the data-driven roster (D4); `git archive`
  per-source with the existing denylist + host-path/PII scrub + `SOURCES.md`; handle a subdir-of-repo source
  (pathspec) and a non-git source (clean copy + scrub).
- **`dist_manifest.txt` / `distro.py`** — allow-list the expanded `vendor/bundled-skills/**` (already treated as
  vendored, so import/entropy scans skip it), the new `AGENTS.md`, and onboard2 assets; the 4 scans must pass
  over the REAL expanded vendor output.
- **`onboard.py`** — install the expanded roster as siblings (copy-default, refuse-don't-clobber, resumable);
  add node prereq reporting + `npm install --omit=dev` for dep-bearing skills (D5); add pywinpty handling on
  Windows; add the two preference prompts (D6). All new behavior behind the existing hermetic seams.
- **`AGENTS.md` (NEW, distro-root)** — the 10-min cadence + Status-table format + low-verbosity rule (D7).
- **onboard2 (NEW)** — cross-platform Tailscale enablement (D8): the existing PowerShell path + a POSIX path +
  the token-mandatory guard + docs.
- **Packaging** — a build→scrub→zip step + a clean-room onboard verification (D9); wire an on-demand
  `check_onboard_surface`-style regression for the expanded roster.

## Risks (with mitigations)
- **R1 PII/host-path leak in the newly-vendored skills** → `git archive` + the build-host-path detector +
  residual scrub + the clean-scan gate; done-when asserts `build_distro` CLEAN over the REAL expanded vendor
  tree (not a fixture).
- **R2 jumper can't find gandalf at runtime** → install both as siblings; W2 test proves the vendored jumper
  resolves `applySeamPass` from the vendored gandalf in the install layout.
- **R3 Node skills dead on arrival (missing deps)** → onboard `npm install --omit=dev` best-effort + honest
  skip; gandalf/trio front-end is dependency-light so core value survives a no-node host.
- **R4 agent-builder / expert-coder source not a git repo** → the roster map supports a non-git clean-copy
  source path (D4); done-when covers a non-git source in a temp fixture.
- **R5 onboard clobbers the collaborator's existing skills/data** → copy-default + refuse-don't-clobber +
  resumable + rollback; scaffold only-if-absent.
- **R6 Tailscale exposure without auth** → onboard2 refuses to expose without `ANCHOR_TOKEN` (hard guard, tested
  on all three OSes via the platform seam).
- **R7 preferences silently changing a collaborator's harness** → opt-in prompts only; decline = no-op;
  idempotent; documented reversal.
- **R8 vendoring drift** → `SOURCES.md` archived-commit stamp per skill; re-vendor is a clean `git archive`.

## Out of scope (v1)
financial-analyst + helping-hand (deferred fast-follow); tidy-idy (excluded); GitHub-repo delivery
(`publish_distro` stays unused); auto-syncing vendored skills with upstream; a GUI installer; multi-user/hosted
Anchor; migrating an existing user's Anchor data (the share distro is for FRESH installs); alternate-engine
API keys (documented-optional).
