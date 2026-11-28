# Install & Setup Guide — Anchor (`v1.5.8` · Agentic-CLI Onboarding + `Anchor.exe`)

## Ghost World Labs License (`GHOST-WORLD-LAB-NON-RESALE-v1` · Version 1, Refinement 2)

**All rights reserved.** Not open source. Nothing is unpacked or activated until you acknowledge and agree to the **Ghost World Labs Non-Resale License**:
- **Free Use & Free Sharing Permitted:** Worldwide, royalty-free permission for personal, academic/research, and internal business use, private modification, and voluntary free sharing without a fee. Your own independent papers, data, analyses, and outputs created with Anchor belong 100% to you.
- **No Resale or Commercialization:** Selling copies of Anchor or its bundled skills, bundling them into a paid product, charging recurring version-use/subscription fees, or offering Paid Hosted Access requires **Separate Written Permission** from Ghost World Labs.

---

## Recommended Collaborator Setup — Run Inside Your Agentic CLI (`claude`, `codex`, `agy`, or `grok`)

If you already have at least one working, token-connected agentic CLI (**Claude Code `claude`**, **OpenAI Codex `codex`**, **Google Antigravity `agy`**, or **xAI `grok`**), simply open that CLI in a terminal and paste the onboarding prompt from `docs/COLLABORATOR-INVITE-EMAIL.md`.

Your agent drives **`anchor_onboard_agent.py`** deterministically through 7 guided stages:
1. **Preflight & License Gate (`start-license-gate` + `poll-gate`):** Opens a local `127.0.0.1` one-time browser page so you can review and accept `GHOST-WORLD-LAB-NON-RESALE-v1` without timing out your CLI session.
2. **Mother Ship & 20-Skill Install (`install-mothership`):** Installs Anchor + `Anchor.exe`, syncs all **20 Standing Foundry Skills** across `<workspace>/skills`, `~/.claude/skills`, `~/.codex/skills`, `~/.agents/skills`, and `~/.gemini/antigravity/skills`, and registers the visual `/foundry` skill gallery.
3. **Optional Tailscale Setup (`configure-tailscale`):** Sets up private WireGuard remote access if desired, or skips cleanly for local Mother Ship mode.
4. **Agent CLI Seats (`probe-agents` + `save-agent-seats`):** Auto-detects your active CLI plus any sibling CLIs (`claude`, `codex`, `agy`, `grok`), discovers only the live models your account actually owns, and configures cross-family verification seats.
5. **Updates, Recovery & Collaborations (`register-collaborator`):** Sets your Display Name, Pseudonym (`did:anchor:<slug>`), and Steward Persona (`Aladdin`, `Jarvis`, or `Ecgberht`), enables Ed25519-signed automatic updates (`core_sha256` + `exe_sha256`), writes your owner-only `.anchor/RECOVERY-KIT.md`, and generates a signed `[ANCHOR-COLLAB-REGISTER]` card for cross-Mothership collaborations.
6. **Optional Email & Calendar Local Vault (`start-comms-gate`):** Opens a `127.0.0.1` local OS Vault page so your Gmail/Outlook App Password and Google Calendar Secret ICS URL are saved directly to your OS Credential Vault and **never** enter AI chat transcripts (supports 300,000+ message Gmail archives via bounded tail sync).
7. **Workspace Survey & Starter AI Cockpits (`survey-projects` + `provision-cockpits`):** Surveys your chosen project folders, lets you confirm/rename/merge/split proposed projects right in chat, scaffolds your initial `Active` and `On Deck` AI Cockpits, and opens `Anchor.exe`.

---

## Ongoing Controls Inside `Anchor.exe` (Gear Icon `⚙` & Left-Side CLI/Agent Tiles)

At any time after setup, inside `Anchor.exe` and Cave of Wonders:
- Click the **Gear Icon (`⚙`)** in the top bar to open `/setup` (Mother Ship updates, Provider connections, Workspace folders, and Email/Calendar settings).
- Click any of the **4 CLI/Agent Tiles (`Claude`, `ChatGPT`, `Gemini`, `Grok`)** on the left side of the window to inspect live subscription usage, switch models/reasoning effort, or connect an additional CLI seat.

---

## Clean Uninstall & Account Recovery

- **Uninstall (Windows):** Double-click **`Uninstall-Anchor.cmd`** inside `Anchor\` or run `Anchor.exe --uninstall` (preserves all of your own documents and non-Anchor project folders).
- **Recover on a New Computer:** Run `python anchor_onboard_agent.py recover --display-name "<Name>" --pseudonym "<Pseudonym>" --email "<Email>" --json` from your `.anchor/RECOVERY-KIT.md`.

---

## Rights

**All rights reserved.** Not licensed under MIT, Apache, or GPL (`not open source`). Free personal, academic, and internal use under `GHOST-WORLD-LAB-NON-RESALE-v1`; commercial resale or paid bundling requires Separate Written Permission from Ghost World Labs.
