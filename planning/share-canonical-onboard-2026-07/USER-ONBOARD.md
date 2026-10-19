# Install guide — Shareable skills + Anchor (Package A / B)

**All rights reserved.** Not open source. Use by author permission only.

This is the short path for collaborators. Plain ASCII for mail and terminals.

---

## Super-simple path (Windows)

### 1. Open a terminal where you want everything installed

Recommended: `C:\dev` (create it if needed).

- File Explorer → that folder → address bar → type `cmd` or `powershell` and Enter  
- Or VS Code / Cursor → Open Folder → that directory → Terminal  

### 2. Get the package (git)

**Package B — Anchor + skills (full product, desktop icon):**

```text
git clone <YOUR-ANCHOR-OR-PACKAGE-B-URL> anchor-plus-skills
cd anchor-plus-skills
```

**Package A — skills only (no Anchor desktop service):**

```text
git clone <YOUR-PACKAGE-A-OR-SKILLS-URL> skills-only
cd skills-only
```

(If you were given a zip instead of git: unzip, then `cd` into the package root.)

### 3. Run onboard (one command)

From the package root (folder that contains `onboard.cmd` and `share_onboard.py`):

```text
.\onboard.cmd
```

Or:

```text
powershell -File .\onboard.ps1
```

**What this does for you:**

1. Checks for **Python 3.8+**. If missing, tries **winget** to install it (Windows). If that fails, it points you at python.org and asks you to re-run.
2. Starts the **interactive** install dialogue — same as `python -m share_onboard`.
3. Asks/confirm **where** to put things (home; often under your chosen `C:\dev` tree).
4. Installs **skills** and registers them for your agent hosts (Claude pointer, Grok paths, etc.).
5. Probes **Claude / Gemini(agy) / Grok** subscription CLIs (at least one coding seat should be present to stamp ready).
6. Optional **feedback** — **default is No**.
7. **Package B only:** starts the Anchor **service** if needed, HTTP-probes the local dashboard, places an **Anchor** icon on the desktop (with **anchor.ico**). Dashboard **favicon** ships with the product for the browser tab.

You do **not** need to pre-install Python by hand when winget works.  
You do **not** use silent/`--non-interactive` for a real ready install (that path never stamps ready).

You can also run the dialogue directly after Python is available:

```text
python -m share_onboard
```

### 4. After Package B succeeds

- Double-click **Anchor Dashboard** on the desktop (or pin it to the taskbar).
- That icon runs a **launcher**: if Anchor is already running, it leaves it alone; if it died, it starts the **service**; then it opens the dashboard in your **default browser** (favicon / **anchor.ico** branding).
- Optional: right-click the taskbar icon → pin.

### 5. After skills are installed — `/onboard` in Claude (etc.)

Once skills are registered, your coding agent may expose **`/onboard`** as a **re-run / help** path.  
**Cold-start for a new machine is still `.\onboard.cmd`**, not slash-onboard (slash needs skills already present).

---

## Package A vs B (what ready means)

| | **A — skills only** | **B — Anchor + skills** |
|--|---------------------|-------------------------|
| Skills + host register | Yes | Yes |
| Seat probe (claude / agy / grok) | Yes | Yes |
| Anchor service + local dashboard | No | Yes (HTTP probe) |
| Desktop icon (service-aware) | No | Yes |

Zero coding seats → not-ready (non-zero exit). Skills still may be on disk.

---

## Feedback (optional)

Onboard asks whether to share **sanitized** skill-friction reports. **Default is No.**  
If Yes: coarse metadata only — not your files, prompts, or project content.

---

## Rights

**All rights reserved.** Not MIT/Apache/GPL. Redistribution only by permission.
