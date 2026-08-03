# Install guide — Anchor + skills (v1.1.3, Package A / B)

**All rights reserved.** Not open source. Use by author permission only.

This is the short path for collaborators. Plain ASCII for mail and terminals.

---

## What you're getting — pick your package

- **Package B — Anchor + skills**: the full product. A local R&D dashboard
  (runs on your machine at `http://localhost:8777`, nothing leaves your
  computer) that drives projects, tasks, and AI research/plan/build sessions,
  plus 13 bundled skills for Claude Code. **Pick this to try Anchor.**
- **Package A — skills only**: just the skills, registered for your coding
  agent. No server, no dashboard.

## What you need

- **Windows 10/11.** About 200 MB free. **No admin rights needed.**
- **git** (to clone and to pull upgrades): `winget install --id Git.Git`
  or gitforwindows.org. No GitHub account needed — the repo is public.
- **Python 3.8+** — onboard installs it via winget if you don't have it.
- For the **AI features** (in-dashboard terminals, research/plan/build
  sessions, Gandalf): the **Claude Code CLI** with your subscription
  (`npm install -g @anthropic-ai/claude-code`), plus **git** and
  **Node.js 16+**. Without them the dashboard still runs — the AI features
  honestly report themselves unavailable instead of breaking.
- **Money honesty:** nothing spends your Claude subscription without an
  explicit action by you. Background auto-summaries are OFF on shared
  installs; the multi-agent skills (researchPrime / Crucible / Foreman /
  Gandalf) only run when you invoke them.

---

## Install (three steps)

### 1. Clone the repo somewhere stable

```text
cd C:\dev        (create the folder if needed)
git clone https://github.com/johncliechty/anchor-plus-skills.git
cd anchor-plus-skills
```

- Keep this folder — **your Anchor data lives inside it** (see "Known
  limits" below).
- **Upgrading later is just `git pull`** — your data files are untracked and
  git-ignored, so a pull updates the product without touching your tasks or
  projects.

(No git and can't install it? Use the repo page's "Code → Download ZIP"
instead — then right-click the zip → Properties → check **Unblock** → OK
**before** extracting, and note zip installs must be upgraded by hand.)

### 2. Run onboard (one command)

Open a terminal in the package root (the folder containing `onboard.cmd`):

```text
.\onboard.cmd
```

(or `powershell -File .\onboard.ps1`, or — once Python exists —
`python -m share_onboard`.)

**What this does for you:**

1. Checks for **Python 3.8+**. If missing, tries **winget** to install it. If
   that fails, it points you at python.org and asks you to re-run.
2. Starts the **interactive** install dialogue (a silent/`--non-interactive`
   run never stamps ready — that is deliberate).
3. Asks/confirms **where** to put things (recommend your `C:\dev` tree).
4. Installs **skills** and registers them for your agent hosts. For Claude it
   tries a symlink, then a **directory junction** (works on stock Windows —
   no admin, no Developer Mode), then a **full copy** as last resort, and
   reports which one it used. Check: `%USERPROFILE%\.claude\skills\<name>`
   contains a real `SKILL.md`.
5. Probes **Claude / Gemini(agy) / Grok** subscription CLIs (at least one
   coding seat should be present to stamp ready).
6. Optional **feedback** — **default is No**.
7. **Package B only:** installs the **pywinpty** terminal extra (real
   in-browser terminals; if the install fails, onboard prints the manual
   command and everything else still works), scaffolds a fresh empty Anchor,
   mints your local access **token** (stored outside the package at
   `%USERPROFILE%\.anchor\.anchor\onboard-token`), and places an **Anchor**
   desktop icon (anchor.ico).

### 3. Start Anchor (Package B)

There is **no Windows service** — Anchor runs as a background process you
start with the launcher:

```text
python launch_anchor_dashboard.py
```

- The desktop **Anchor Dashboard** icon runs the same launcher.
- The launcher: if Anchor is already running it leaves it alone; if it is
  down it **starts the local server** (wiring in your access token — mutating
  APIs and terminals then require it automatically); then it opens the
  dashboard in your **default browser** (the Anchor **favicon** marks the
  tab). The token is handed to the page once and immediately stripped from
  the URL.
- **After a reboot, run the launcher (or click the icon) again** — nothing
  auto-starts on login in this release.

---

## First ten minutes (try this)

1. **Dashboard basics:** add a task, capture an idea to the inbox — it all
   saves to plain markdown files you can open yourself.
2. **Register a project:** New project → point it at any code folder on your
   machine → open its project window (the 5-lane R&D board).
3. **If you installed the Claude CLI:** "Open terminal" in a project window
   starts a live engine session — with git present it runs in an isolated
   worktree, without git it honestly runs in-place.

---

## If something is broken (cheap checks first)

1. `python doctor.py` — deterministic install health: missing modules,
   pywinpty, engine CLIs, token, server reachability. **No AI calls, free.**
2. Look at the tail of `logs\errors.log` **inside this package folder**
   (that folder is the default data dir).
3. Only then ask an AI agent — and point it at THIS package folder (which
   carries an agent-notes `CLAUDE.md`), **never** at a full author monorepo
   dump. Do not use researchPrime / Crucible / Foreman / Gandalf to debug an
   install: those are intentional multi-agent tools that fan out many paid
   model calls.

## Tell John what hurt (this is how fixes actually happen)

Anchor has a built-in friction journal. When anything is broken, confusing,
or annoying — even small stuff — take 30 seconds:

```text
python anchor.py journal "what hurt, in one line" --severity problem --body "details: what you did, what you expected, any error text"
python anchor.py friction-report
```

Copy the `friction-report` output back to John (mail/message). Severities:
`concern` (papercut) / `friction` (slowed you down) / `problem` (broken).
This exact loop is what produced the v1.1.3 fixes.

---

## Known limits of v1.1.3 (honest)

- **No auto-start:** run the launcher (or click the icon) again after a
  reboot.
- **Local-only:** the server binds loopback; nothing is exposed to the
  network.
- **Your data lives in the package folder** (`DASHBOARD.md`, project
  registry, `logs\` — beside `anchor_gui.py`). It is untracked and
  git-ignored, so **upgrading with `git pull` never touches it**. If you
  installed from a zip instead: never just delete the old folder — keep it
  (or copy your `.md` files over) so you keep your tasks and projects.
- **Terminals** need pywinpty (onboard installs it); **AI sessions** need the
  Claude CLI; **worktree isolation** needs git; **Gandalf/trio engines** need
  Node.js. Each degrades honestly when missing.

---

## Package A vs B (what ready means)

| | **A — skills only** | **B — Anchor + skills** |
|--|---------------------|-------------------------|
| Skills + host register (symlink/junction/copy, reported) | Yes | Yes |
| Seat probe (claude / agy / grok) | Yes | Yes |
| Anchor server + local dashboard (launcher-started; HTTP probe) | No | Yes |
| pywinpty terminal extra (Windows) | No | Yes |
| Access token minted + wired by the launcher | No | Yes |
| Desktop icon (launcher-targeting, anchor.ico) | No | Yes |

Zero coding seats → not-ready (non-zero exit). Skills still may be on disk.

## After skills are installed — `/onboard` in Claude (etc.)

Once skills are registered, your coding agent may expose **`/onboard`** as a
**re-run / help** path. **Cold-start for a new machine is still
`.\onboard.cmd`**, not slash-onboard (slash needs skills already present).

## Feedback consent (separate from the friction journal above)

Onboard asks whether to auto-share **sanitized** skill-friction reports.
**Default is No.** If Yes: coarse metadata only — never your files, prompts,
or project content.

---

## Rights

**All rights reserved.** Not MIT/Apache/GPL. Redistribution only by permission.
