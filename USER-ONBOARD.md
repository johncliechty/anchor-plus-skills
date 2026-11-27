# Install & Setup Guide — Anchor (`v1.5.7` · Windows, Apple Mac / MacBook Air, & Linux)

## Ghost World Labs License (`GHOST-WORLD-LAB-NON-RESALE-v1` · Version 1, Refinement 2)

**All rights reserved.** Not open source. Nothing is downloaded until you acknowledge and agree to the **Ghost World Labs Non-Resale License** in Step 1:
- **Free Use & Free Sharing Permitted:** Worldwide, royalty-free permission for personal, academic/research, and internal business use, private modification, and voluntary free sharing without a fee. Your own independent papers, data, analyses, and outputs created with Anchor belong 100% to you.
- **No Resale or Commercialization:** Selling copies of Anchor or its bundled skills, bundling them into a paid product, charging recurring version-use/subscription fees, or offering Paid Hosted Access requires **Separate Written Permission** from Ghost World Labs.
- **License-First Setup Gate:** `Anchor.zip` contains only the launcher shell; acknowledging the Ghost World Labs License in **Step 1 (`Mother Ship & Remote`)** unlocks downloading Anchor + all 20 standing Foundry skills and records a signed receipt in `.anchor/license_acceptances.json`.

---

## Single-Download Setup (`Anchor.zip` -> Step 1 License & Mother Ship -> All 4 CLIs + 20 Skills)

You **only** need the single `Anchor.zip` download from the official Anchor repository (`https://github.com/johncliechty/ghostworldlabs-anchor/releases/latest/download/Anchor.zip`):

1. **Unzip `Anchor.zip`** to any folder (e.g. `C:\Anchor-App` or Desktop) and double-click **`Anchor\Anchor.exe`**.
2. **Step 1 — Mother Ship & Remote + Ghost World Labs License:**
   - Check the **Ghost World Labs License** box first (required before anything is downloaded).
   - Optional: 1-click **Tailscale** setup if you want private remote access from a phone or second laptop (or click **No Thanks — Use Locally**).
   - Enter your **Email Address** and click **Register** against the locked official Anchor GitHub repository (`https://github.com/johncliechty/ghostworldlabs-anchor` · `mothership_registry.json`) so signed `release-signal.json` updates pull automatically.
   - All **20 Standing Foundry Skills** load automatically into `<workspace>\skills` and your CLI homes (`~/.claude/skills`, `~/.agents/skills`, `~/.gemini/antigravity/skills`) — no questions needed.
3. **Step 2 — All 4 AI Agent CLIs + Simple 1-Button Connect (`🟢 Connected`):**
   - Anchor automatically installs all 4 CLIs: **Claude Code (`claude`)**, **Gemini / Antigravity (`gemini` & `agy`)**, **OpenAI Codex (`codex`)**, and **Grok (`grok`)**.
   - Click **Connect** on any provider card to jump straight to the exact login/key screen needed for that CLI (`claude auth login`, Google OAuth / free AI Studio key, `codex login`, or `console.x.ai`). As soon as connected, the card turns **`🟢 Connected`**!
4. **Step 3 — Hard-Drive Folder Tree + Gandalf Project Proposal (Drag to Merge · Split Apart):**
   - Expand any hard drive (`C:\`, `D:\`) or smart **Proposed Work Area** (`C:\dev`, `Documents`, `Desktop`) and check (`☑`) the folders or subfolders you want included.
   - Click **Analyze with Gandalf & Propose Projects** — Gandalf inspects your checked folders and proposes clean **Project Cards**.
   - **Drag one project card onto another to merge them**, drag individual folder chips (`📁`) between projects, or click **Split Apart** to separate subfolders into individual projects, then click **Create Selected Projects**.
5. **Step 4 — Simple Email & Calendar Connect (`🟢 Connected`):**
   - Click **1-Click Connect Windows Outlook** (zero password if Windows Outlook is open), OR enter your email address → click **Open Provider Password Page** → paste password & click **Connect** to verify live IMAP SSL and show **`🟢 Connected`**.

---

## Clean Uninstall (Windows)

To remove Anchor cleanly while keeping all of your own documents and non-Anchor project folders untouched:
- Double-click **`Uninstall-Anchor.cmd`** inside `Anchor\`, **OR** run `Anchor.exe --uninstall`, **OR** open Windows **Settings → Apps → Installed Apps → Anchor (Ghost World Labs) → Uninstall**.

---

## Apple Mac / MacBook Air (macOS) & Linux Install

Run `bash ./install-mac-linux.sh`, acknowledge the Ghost World Labs License prompt, and Anchor builds the native standalone **`Anchor.app`** (macOS) or Linux desktop app, places **`Anchor.command`** on your Desktop, and loads all 20 standing Foundry skills.

---

## Rights

**All rights reserved.** Not licensed under MIT, Apache, or GPL (`not open source`). Free personal, academic, and internal use under `GHOST-WORLD-LAB-NON-RESALE-v1`; commercial resale or paid bundling requires Separate Written Permission from Ghost World Labs.
