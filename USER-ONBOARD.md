# Install & Setup Guide — Anchor (`v1.5.6` · Windows, Apple Mac / MacBook Air, & Linux)

## Ghost World Labs License (`GHOST-WORLD-LAB-NON-RESALE-v1` · Version 1, Refinement 2)

**All rights reserved.** Not open source. Use and voluntary free sharing are governed by the **Ghost World Labs Non-Resale License**:
- **Free Use & Free Sharing Permitted:** Worldwide, royalty-free permission for personal, academic/research, and internal business use, private modification, and voluntary free sharing without a fee. Your own independent papers, data, analyses, and outputs created with Anchor belong 100% to you.
- **No Resale or Commercialization:** Selling copies of Anchor or its bundled skills, bundling them into a paid product, charging recurring version-use/subscription fees, or offering Paid Hosted Access requires **Separate Written Permission** from Ghost World Labs.
- **Setup Acknowledgement:** During first-run setup (`Anchor.exe`, `/onboard-wizard` Step 1, or `/setup`), check the Ghost World Labs License box to record a local signed receipt in `.anchor/license_acceptances.json`.

---

## Single-Download Setup (`Anchor.zip` -> `Anchor.exe` Automatically Pulls All 20 Skills & Agent CLIs)

You **only** need the single `Anchor.zip` download from the official Anchor repository (`https://github.com/johncliechty/ghostworldlabs-anchor/releases/latest/download/Anchor.zip`) — **no separate Skill Foundry download or second repository is needed!**

1. **Unzip `Anchor.zip`** to a clean folder on your PC (for example `C:\Anchor-App` or your Desktop) and double-click **`Anchor\Anchor.exe`** (uses `anchor.ico` for the desktop shortcut and Anchor favicon in embedded views).
2. **Automatic Tailscale Check (Optional):** `Anchor.exe` checks whether Tailscale is installed and signed in. If not, it asks whether you would like to set up Tailscale (1-click install & sign-in for private access from a second laptop or phone) or skip it and run the local background service without Tailscale.
3. **1-Click Registry & Automatic Future Updates (`release-signal.json`):**
   - Enter your **Email Address** to connect.
   - The **Anchor GitHub Repository (`https://github.com/johncliechty/ghostworldlabs-anchor` / `mothership_registry.json`)** is pre-filled and locked as the official registry.
   - Click **Register & Install** — Anchor installs/updates `<workspace>\Anchor`, automatically syncs all **20 Ghost World Labs skills** into `<workspace>\skills` and your agent CLI homes (`~/.claude/skills`, `~/.agents/skills`, `~/.gemini/antigravity/skills`), and watches Ghost World Labs' Ed25519-signed `https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/release-signal.json` online for future automatic updates (no Tailscale required).
4. **Auto-Install AI Agent CLIs, Free-Tier Preset & Browser Sign-In:**
   - Setup automatically installs **Claude Code CLI (`claude`)**, **Antigravity / Gemini CLI (`agy` / `gemini`)**, **OpenAI Codex CLI (`codex`)**, and **Grok (`grok`, when enabled)**.
   - Setup checks whether you already have provider accounts open in your browser (`claude.ai`, `gemini.google.com` / `aistudio.google.com`, `chatgpt.com`, `grok.com`) and gives you a **1-click "Open Browser & Log In"** button.
   - **Free-Tier AI Provider Accounts & Older Laptops:** Click **Apply Free-Account Preset** in Step 3 for single-seat paced Free-Tier accounts (such as a free Google account or free Google AI Studio key at `aistudio.google.com`), and keep **Low-Memory Mothership Mode** enabled on older laptops (`< 12 GB` RAM or `<= 4` CPU cores).
5. **Straightforward Email Linking:**
   - Click **1-Click Connect Running Windows Outlook** (zero password needed if Windows Outlook is open), OR simply type your email address — Anchor auto-detects Gmail, Outlook, Yahoo, iCloud, or institutional IMAP settings and opens your provider's App Password / sign-in page in your browser with 1 click.

---

## Clean Uninstall (Windows)

If an earlier setup did not finish or you ever want to remove Anchor cleanly while keeping all of your own documents and non-Anchor project folders untouched:
- Double-click **`Uninstall-Anchor.cmd`** inside `Anchor\` (from `Anchor.zip`), **OR**
- Run `Anchor.exe --uninstall`, **OR**
- Open Windows **Settings → Apps → Installed Apps → Anchor (Ghost World Labs) → Uninstall**.

---

## Apple Mac / MacBook Air (macOS) & Linux Install

Unzip `Anchor.zip` (or clone `https://github.com/johncliechty/ghostworldlabs-anchor.git`) and run `bash ./install-mac-linux.sh` to build the native standalone **`Anchor.app`** (macOS) or Linux desktop app, place a double-clickable **`Anchor.command`** launcher on your Desktop, start the local service (`--no-browser`), and sync all 20 bundled skills.

---

## CLI Onboarding & Package Reference (`Package B` vs `Package A`)

- **Package B — Anchor + skills**: Full local Anchor service, Cave of Wonders, AI Cockpits, desktop icon (`anchor.ico`) + browser favicon, and all 20 bundled skills (`Anchor.zip` / `.\onboard.cmd` / `python -m share_onboard`).
- **Package A — skills only**: Skills + governance pack without running the Anchor server (`python -m share_onboard`).
- **Diagnostics & Optional Feedback:** Run `python doctor.py` for a zero-AI local health check, or opt in to sanitized setup feedback (default is No; coarse metadata only, never your files or prompts).

---

## Rights

**All rights reserved.** Not licensed under MIT, Apache, or GPL (`not open source`). Free personal, academic, and internal use under `GHOST-WORLD-LAB-NON-RESALE-v1`; commercial resale or paid bundling requires Separate Written Permission from Ghost World Labs.
