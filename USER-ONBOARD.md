# Install guide — Anchor + skills (v1.5.2, Windows, Apple Mac / MacBook Air, & Linux)

## Quick Platform Compatibility FAQ (Windows vs. Apple Mac / Linux)

- **Does `Anchor.exe` run on an Apple Mac / MacBook Air or Linux?**
  **No.** `Anchor.exe` is a Windows-only binary (`PE32+ x86-64` built with PyInstaller + Microsoft Edge WebView2). It will **not** run directly on macOS or Linux.
- **Is there a standalone native GUI app for Apple Mac (MacBook Air / Pro) and Linux (not running in a browser)?**
  **Yes — 100% standalone native GUI window on all three operating systems (never in a web browser)!**
  - **Windows:** `Anchor.exe` (frameless native desktop window powered by `shell/anchor_shell.py` + WebView2).
  - **macOS (MacBook Air M1/M2/M3/M4 or Intel):** `Anchor.app` (frameless native macOS Cocoa/WebKit desktop app built by `shell/build_unix.sh` and launched via `shell/anchor_shell.py` — own Dock icon, custom title bar, single-instance lock, **no browser**).
  - **Linux:** Standalone `Anchor` desktop application (`anchor.desktop` + `shell/anchor_shell.py` powered by native WebKitGTK — own window and taskbar icon, **no browser**).
- **Two ways to use the standalone Anchor GUI on a MacBook Air or Linux machine:**
  1. **Mode A — Standalone Native GUI Connected to an Existing Mother Ship:** Run `./install-mac-linux.sh` (or `Anchor.app`), and on the first screen click **"Connect to my existing mother ship"** and enter your Mother Ship's Tailscale HTTPS address.
  2. **Mode B — Full Standalone Mother Ship + Native GUI on macOS or Linux:** Run `./install-mac-linux.sh` once. It installs the background service (`--no-browser`), builds the native **`Anchor.app`** (macOS) or **`Anchor`** desktop app (Linux), and opens the standalone Anchor GUI window directly.

---

## Option 1: Windows 10/11 Install (`Anchor.exe` or `onboard.cmd`)

1. **Extract `Anchor.zip`** into `C:\dev\Anchor` (or any clean folder) and double-click **`Anchor.exe`**.
2. In the **Anchor Setup** screen (`v1.5.2` shown in the top bar):
   - Choose your **Install Mode**:
     - **Upgrade In-Place (Recommended):** Updates Anchor and overwrites all 20 bundled Foundry skills while keeping your existing projects and settings.
     - **Clean Fresh Install:** Archives any previous `.ecgberht` state so you start completely fresh with the Onboarding Wizard.
     - **Migrate State:** Copies your settings and projects from an earlier installation into the new folder.
   - Note: Anchor automatically ignores backup folders (`Anchor-1.4.6-backup`, `Anchor 2`, `Anchor 3`) and never imports its own skill folders (`SKILL.md` / Foundry skills) as R&D projects.
3. Once installed, Anchor automatically routes new setups to the **Onboarding & Setup Wizard (`/onboard-wizard`)** so you can set your display name, connect AI providers (Claude Code, Gemini CLI, ChatGPT Codex, Grok), and pick your real project folders.

---

## Option 2: Apple Mac / MacBook Air (macOS) & Linux Install

### Prerequisites on macOS (MacBook Air / Pro)
Open **Terminal.app** (`Cmd + Space`, type `Terminal`) and ensure Command Line Tools, Python 3, and Node.js 18+ are installed:
```bash
xcode-select --install 2>/dev/null || true
# If using Homebrew (https://brew.sh):
brew install git python node
```

### Prerequisites on Linux (Ubuntu / Debian / Fedora)
```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip python3-gi gir1.2-webkit2-4.1 nodejs npm
```

### 1-Command Turnkey Install (macOS & Linux — Standalone Native GUI, Never a Browser)
If you received `Anchor.zip`, unzip it into `~/dev/Anchor` (or clone the repository) and run:
```bash
cd ~/dev/Anchor
bash ./install-mac-linux.sh
```
**What `install-mac-linux.sh` does automatically:**
- Verifies `git`, `python3`, and `node`.
- Installs and updates all **20 bundled Foundry skills** into `~/.claude/skills` and `~/.agents/skills`.
- Scaffolds your Anchor workspace and local security token (`~/.anchor/.anchor/onboard-token`).
- Sets up the isolated native GUI shell environment (`~/Library/Application Support/anchor-shell/.venv` on macOS, `~/.local/share/anchor-shell/.venv` on Linux) with `pywebview` and builds the standalone native desktop application (**`Anchor.app`** in `/Applications/Anchor.app` on macOS, or the standalone **`Anchor`** desktop application + `anchor.desktop` entry on Linux), plus places a double-clickable **`Anchor.command`** launcher on your Desktop.
- Starts the Anchor Mother Ship background service (`--no-browser`) and opens the **standalone native Anchor GUI window** directly (never in a browser).

---

## Mother Ship Registration & Push / Pull Updates (`v1.5.2+`)

- **Where to see your version:** Look at the `v1.5.2` badge in the **very top title bar** of Anchor (`#bar-version-pill` / masthead) or open **⚙ Host & Provider Setup (`/setup`)**.
- **How a collaborator pulls the latest update:**
  Click the `v1.5.2` version pill in the top bar (or open **⚙ Setup -> Section 1: Mother Ship**), click **🔍 Check for Updates**, and click **⬆ Pull & Update to Latest Version**. This pulls the latest Anchor code and refreshes all 20 bundled Foundry skills without touching your projects.
- **How to register a collaborator's Mother Ship in the Anchor repo (`mothership_registry.json`):**
  In **⚙ Setup -> Section 1: Mother Ship -> Register Mother Ship in Anchor Repository**, enter the collaborator's name, Steward pseudonym, Tailscale/Mother Ship URL, and platform (`windows`, `macos-arm64`, `macos-x64`, `linux`), and click **📌 Register Mother Ship in Repo**.
- **How to push the latest Anchor release to registered Mother Ships:**
  In **⚙ Setup -> Section 1: Mother Ship**, click **🚀 Push Latest Anchor to Registered Mother Ships** (or POST to `/api/mothership/push_update`).

---

**All rights reserved.** Not open source. Use by author permission only.

This is the short path for collaborators. Plain ASCII for mail and terminals.

---

## What you're getting — pick your package

- **Package B — Anchor + skills**: the full product. A local R&D dashboard
  (runs on your machine at `http://localhost:8777`) that drives projects,
  tasks, and AI research/plan/build sessions, plus 14 bundled skills.
  AI requests go to the subscription provider you select. **Pick this to try Anchor.**
- **Package A — skills only**: just the skills, registered for your coding
  agent. No server, no dashboard.

## What you need

- **Windows 10/11.** About 200 MB free for Anchor. Core onboarding does not
  require administrator rights. Optional notebook setup needs additional disk
  space and one-time administrator confirmation.
- **git** (to clone and to pull upgrades): `winget install --id Git.Git`
  or gitforwindows.org. No GitHub account needed — the repo is public.
- **Python 3.8+** — onboard installs it via winget if you don't have it.
- For the **AI features** (in-dashboard terminals, research/plan/build
  sessions, Gandalf): sign in to a supported **subscription CLI** (Claude Code,
  ChatGPT Codex, or Grok Build), plus install **git** and **Node.js 16+**.
  Choose the coding and review families in Anchor Settings. Without these tools
  the dashboard still runs — the AI features
  honestly report themselves unavailable instead of breaking.
- **Money honesty:** nothing spends your model subscription without an
  explicit action by you. Background auto-summaries are OFF on shared
  installs; the multi-agent skills (researchPrime / Crucible / Foreman /
  Gandalf) only run when you invoke them.

---

## Install (three steps)

### 1. Clone the repo somewhere stable

In PowerShell, this installs outside your development tree:

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\Programs" | Out-Null
Set-Location "$env:LOCALAPPDATA\Programs"
git clone https://github.com/johncliechty/anchor-plus-skills.git
Set-Location anchor-plus-skills
```

- Keep this folder — **your Anchor data lives inside it** (see "Known
  limits" below).
- **Upgrading later is `git pull`, then re-run `.\onboard.cmd`** — your data
  files are untracked and git-ignored, so the pull never touches your tasks
  or projects; the onboard re-run (idempotent) registers any NEW skills the
  release added and heals older installs.

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
3. Asks/confirms **where** to put things. Keep the program folder above;
   choose your existing project folders separately. Anchor's local data still
   needs a backup even when the program is installed outside your development tree.
4. Installs **skills** and registers them for your agent hosts. For Claude it
   tries a symlink, then a **directory junction** (works on stock Windows —
   no admin, no Developer Mode), then a **full copy** as last resort, and
   reports which one it used. Check: `%USERPROFILE%\.claude\skills\<name>`
   contains a real `SKILL.md`.
5. Probes subscription CLIs, including **Claude / ChatGPT Codex / Grok** (at least one
   coding seat should be present to stamp ready).
6. Optional **feedback** — **default is No**.
7. **Package B only:** installs the **pywinpty** terminal extra (real
   in-browser terminals; if the install fails, onboard prints the manual
   command and everything else still works), scaffolds a fresh empty Anchor,
   mints your local access **token** (stored outside the package at
   `%USERPROFILE%\.anchor\.anchor\onboard-token`), and places an **Anchor**
   desktop icon (anchor.ico).

### 3. Start Anchor (Package B)

**Skip optional Windows notebook-host setup in this release; startup is under repair.**
The Anchor dashboard and bundled skills can be installed independently.

Optional Python/R notebooks have a separate [one-time host setup](docs/notebook-host-setup.md).
Notebook software defaults to `C:\ProgramData\AnchorNotebook`; your existing
notebooks stay in the project folder you select. R and IRkernel are needed only
for R notebooks. The notebook service starts automatically after its setup;
the Anchor dashboard launcher below is separate.

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
- **Native Windows app (`Anchor\Anchor.exe`):** You can also launch `Anchor\Anchor.exe` directly. On startup it automatically removes Windows Mark-of-the-Web (`:Zone.Identifier`) from extracted WebView2 DLLs, registers a Start-menu shortcut, and — when **"This computer is my mother ship"** is selected — automatically starts the local Anchor service on port `8777` (or pulls & installs the Mother Ship repository and Foundry skills into your chosen workspace directory if not yet present) before opening `/setup`.
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

## Running the skills properly (read this before your first real run)

Two files in the package root decide whether the skills behave the way they
were designed to. They are short; read them before you invoke anything
expensive.

### `AGENTS.md` — the run contract

Every bundled skill points here. Most importantly it defines the **10-minute
status table**: any long run (a Foreman build, a Crucible plan, a researchPrime
investigation, any `-Heavy` variant) reports progress roughly every ten
minutes, unprompted, in one fixed format — what it is doing, elapsed, ETA, the
last gate result, and anything that broke.

If you start a long run and get twenty minutes of silence, something is wrong.
The usual cause is the run being launched as a blocking foreground call, which
freezes the session so it cannot report; `AGENTS.md` gives the launch pattern
that avoids it.

> **Package A note.** Seat assignment (which model does the work, which model
> checks it) resolves from Anchor's preferences. Package A has no Anchor, so
> either create `~/.anchor/model_prefs.json` or expect the skills to stamp
> `cross_model:false` and cap their confidence. **That stamp is correct
> behavior, not a bug** — it means one model family did the work and the check,
> so the check is a weaker signal. The skills will never quietly pass that off
> as independent verification.

### `AUTONOMOUS-MODE.md` — running unattended

By default your agent asks before each action. That is right while you are
learning what the skills do — and wrong the moment you want a Foreman build to
run for an hour while you are away, since a single wave touches dozens of files
and runs your test suite several times.

`AUTONOMOUS-MODE.md` gives the exact settings block, what each capability is
for, and what stays blocked. **The change lands in your own user-level config,
not a file we ship** — an agent deliberately restricts what a settings file
arriving inside a cloned repository may authorize, which is a good rule we are
not going to work around. After reading it, one command installs both the
agent-level best-practice rules and (optionally) the autonomy settings,
reversibly, into your own config:

```text
python share_agent_rules.py install --settings
```

(`install` alone = rules only; `remove` undoes the rules block; `status`
shows what is installed. Your pre-merge settings are kept at
`settings.json.anchor-orig`.)

Read the risk section there before you turn it on. It is a real grant of
authority on your machine, and it is the same one the author runs with.

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

## Known limits of v1.2.4 (honest)

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
