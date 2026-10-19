# Anchor Migration Plan — New Windows 11 Desktop

*Drafted 2026-05-11. Mirrors the pattern of `Agentic-Home`'s `OneDrive-Migration-Plan.md` from 2026-05-01/02.*

> **Status:** All four decision points are locked. Tailscale admin console verified (MagicDNS on, HTTPS Certificates on). Ready to execute end-to-end. Substitute your real Tailscale machine name for `<anchor-host>` wherever it appears below.

## End state

- Anchor lives at `C:\dev\Anchor` on the new Windows 11 desktop.
- `anchor_gui.py` runs as a background server on that desktop, bound to localhost:8777.
- Tailscale Serve exposes it to your tailnet over HTTPS at `https://<anchor-host>.tailb49f65.ts.net` — clean URL, no port, real Let's-Encrypt cert, only reachable from devices on your tailnet.
- A custom "Anchor" app icon (chosen from three designs) is pinned to the taskbar on each device (laptop, iPad via Home Screen, office desktop). One tap opens the live dashboard.
- The daily health check (`anchor_healthcheck.py`) runs on the new desktop at 5:00 AM.
- The laptop's `C:\dev\Anchor` becomes a frozen historical backup with a dead-banner CLAUDE.md (same pattern as the old PSU OneDrive folder).

## Locked decisions

| Decision | Choice |
|---|---|
| Server exposure | Tailscale Serve (HTTPS) at `https://<anchor-host>.tailb49f65.ts.net` |
| Auto-start | Task Scheduler "At log on" trigger |
| Transfer method | SSD bare-repo handoff |
| History | Start fresh on `logs/` and `health_reports/`. The actual data (DASHBOARD.md, INBOX.md, PROJECTS.md, CANCELLED.md, SAVED_FOR_LATER.md, WEEKLY_REVIEW.md, all of `domains/`) is git-tracked and comes over via the clone. |
| Icon | Option C — Heritage crest. White anchor (outlined ring, shank, stock with end-balls, filled smile with triangular flukes) on deep navy `#021a3d`. Generated 2026-05-11 and committed to the repo as `anchor.ico` (7 sizes: 16/24/32/48/64/128/256), `anchor.png` (256×256), `anchor-touch.png` (180×180 for iPad), and `anchor.svg` (source). |

## Tailscale prerequisites — confirmed

- Tailnet DNS name: `tailb49f65.ts.net` (visible at login.tailscale.com/admin/dns)
- MagicDNS: enabled
- HTTPS Certificates: enabled

No further admin-console changes needed. Tailscale Serve will provision the cert automatically the first time you wire it up.

---

## Step 0 — Pre-flight

On the **laptop** (source):

```powershell
cd C:\dev\Anchor
git status                          # must be clean — commit any pending edits first
```

If `git status` shows uncommitted work, commit it now. The bare-repo clone in Step 1 only carries committed history — anything in the working directory that hasn't been committed gets left behind. In particular, this migration session has added four icon files and updated `.gitignore` — those need to be committed before you clone:

```powershell
git add .gitignore anchor.ico anchor.png anchor-touch.png anchor.svg MIGRATION-PLAN-New-Desktop-2026-05-11.md
git commit -m "Add Option C anchor icon assets; update .gitignore exceptions; add migration plan"
git log -1 --oneline                # note the commit hash (record it somewhere safe)
python anchor_healthcheck.py        # one last clean health check before moving
```

On the **new desktop**:

```powershell
python --version                    # need >= 3.8
git --version                       # need git
tailscale status                    # desktop authenticated + online
tailscale ip -4                     # note the IPv4 (will be 100.x.x.x)
```

Install whatever's missing. Python from python.org (check "Add to PATH" during install). Git from git-scm.com.

While you're here, learn your new desktop's Tailscale machine name from `tailscale status` (the first column of the line where you see your own IP). That's the `<anchor-host>` you'll use in every URL below. If it's something unwieldy, rename it now in the Tailscale admin console (Machines → click the machine → Edit machine name) — easier to do before you bake the URL into shortcuts.

---

## Step 1 — Transfer the repo via SSD

On the **laptop**, with the SSD plugged in (assume it mounts as `E:`):

```powershell
git clone --bare C:\dev\Anchor E:\anchor.git
```

Safely eject. Walk the SSD to the new desktop. Plug it in.

On the **new desktop**:

```powershell
mkdir C:\dev -Force
cd C:\dev
git clone E:\anchor.git Anchor
cd Anchor
git log -1 --oneline                # confirm same commit hash you noted on the laptop
```

The clone brings over `DASHBOARD.md`, `INBOX.md`, `PROJECTS.md`, `CANCELLED.md`, `SAVED_FOR_LATER.md`, `WEEKLY_REVIEW.md`, everything in `domains/`, both Python scripts (`anchor_gui.py`, `anchor.py`, `anchor_healthcheck.py`), `register_healthcheck.ps1`, `requirements.txt`, the `_archive/` snapshot, and all CLAUDE.md documentation. Your current tasks and projects appear on the new desktop exactly as they show on the laptop right now.

What does **not** come over (gitignored): `logs/*.md` (daily activity logs), `health_reports/*.md` (daily health reports), `.bat` launcher scripts, `.ico` icon files, `dashboard_live.html`, and the `Summary for PSU/` folder of decks. The launcher and icon will be recreated in Step 6; logs and health reports will start fresh as designed. The decks aren't operational data.

Eject the SSD when the clone is done. Keep it as a one-shot backup of the migration point — you can reformat or repurpose it after you've verified the new setup is healthy.

---

## Step 2 — Local smoke test on the new desktop

Before involving Tailscale, prove the server runs locally on the new box:

```powershell
cd C:\dev\Anchor
python anchor_gui.py
```

A browser opens to `http://localhost:8777`. Click around:

- Check off a task → confirm the corresponding markdown file under `C:\dev\Anchor` reflects the `[x]`
- Add a new inbox item → confirm it appears in `INBOX.md`
- Browse Completed view, reopen the task → confirm markdown updated again
- Browse Cancelled, Saved, and each domain view → spot-check they load

Stop with Ctrl+C. If anything failed, fix it before involving Tailscale — Tailscale only adds variables.

---

## Step 3 — Expose via Tailscale Serve

With the server *not* currently running, on the **new desktop**:

```powershell
tailscale version                   # confirm a current build
tailscale serve status              # should be empty/no config

# Wire up: HTTPS at the root of this machine's tailnet hostname → localhost:8777
tailscale serve --bg https / http://localhost:8777

tailscale serve status              # should now show the mapping
```

Now start the Python server (no browser this time — we're testing the remote URL):

```powershell
python anchor_gui.py --no-browser
```

From your **laptop** in any browser, hit `https://<anchor-host>.tailb49f65.ts.net`. You should see:

- The dashboard, identical to what shows locally
- A valid Let's-Encrypt padlock (no cert warnings)

Tick a task from the laptop. SSH/RDP to the new desktop and confirm `Get-Content C:\dev\Anchor\DASHBOARD.md` reflects the change. Repeat from your iPad to verify Safari accepts the cert and the iPad-touch UX is acceptable.

If Serve fails to start: `tailscale serve status` and `tailscale serve --help` are the diagnostic starting points. The most common failure modes are (a) MagicDNS disabled in the admin console — we already confirmed it's on, or (b) the cert hasn't provisioned yet, which can take 30–60s on first request. If the URL gives a cert error on first hit, wait a minute and reload.

Stop the manual `python anchor_gui.py` once the remote test passes — Step 4 takes over launching it.

`tailscale serve --bg` writes its config to disk and re-applies automatically on reboot, so this is a one-time setup.

---

## Step 4 — Auto-start with Task Scheduler ("At log on")

Open Task Scheduler. Right-pane → **Create Task** (not Basic Task).

- **General** tab:
  - Name: `Anchor Server`
  - "Run only when user is logged on"
  - "Run with highest privileges"
- **Triggers** tab → New:
  - "At log on"
  - Specific user: your account
- **Actions** tab → New:
  - Action: "Start a program"
  - Program/script: `C:\Windows\pyw.exe` *(verify with `where pythonw` — adjust to the actual path)*
  - Add arguments: `"C:\dev\Anchor\anchor_gui.py" --no-browser`
  - Start in: `C:\dev\Anchor`
- **Settings** tab:
  - Uncheck "Stop the task if it runs longer than"
  - Check "If the task fails, restart every 1 minute" (up to 3 times)
  - "Allow task to be run on demand"

Save. To test: log off, log back on, open a browser, hit `https://<anchor-host>.tailb49f65.ts.net`. Should load without you having launched anything.

You can lock the desktop session after logging in; the server keeps running on the locked session. When you RDP in later, you're reconnecting to that same session — the server is already there.

If Windows ever reboots overnight unattended, the server will start the next time you log in via RDP or in person. If that becomes a problem, we can upgrade to an "At startup" trigger (which requires storing your account password in Credential Manager).

---

## Step 5 — Move the daily health check

On the **laptop** (decommission the old scheduled task):

```powershell
Unregister-ScheduledTask -TaskName "Anchor Health Check" -Confirm:$false
```

On the **new desktop** (register fresh):

```powershell
cd C:\dev\Anchor
powershell -ExecutionPolicy Bypass -File .\register_healthcheck.ps1
```

Run it once manually to seed today's report and confirm everything wires up:

```powershell
python anchor_healthcheck.py
```

A fresh report should appear at `C:\dev\Anchor\health_reports\2026-05-11.md` (or whatever today's date is when you execute). The scheduler will fire at 5:00 AM tomorrow.

---

## Step 6 — Taskbar icons on each device

You'll first need the custom anchor icon. Once you pick one of the three designs from chat (A/B/C), I'll generate a multi-resolution `anchor.ico` (16/24/32/48/64/128/256) and drop it at `C:\dev\Anchor\anchor.ico`. For everything below, that file is the icon source.

### Windows (new desktop, laptop, office desktop)

The Option C icon ships in the repo as `C:\dev\Anchor\anchor.ico` (multi-resolution; 16/24/32/48/64/128/256 all rendered independently from the SVG so each is crisp). On the laptop and office desktop, also copy `anchor.ico` to a stable local path — for example `C:\Users\<user>\Anchor\anchor.ico` — so the shortcut's icon path doesn't depend on the Anchor folder being present there.

Easiest path uses Edge's "install as an app":

1. Open Edge, navigate to `https://<anchor-host>.tailb49f65.ts.net` (or `http://localhost:8777` on the new desktop itself).
2. ⋯ menu → Apps → "Install this site as an app". Name it "Anchor".
3. Edge gives it a chrome-less window. Right-click the entry in Start → Pin to Taskbar.
4. Tap the taskbar icon any time → live dashboard.

Edge will derive an icon automatically from the favicon shipped by the server. To force the custom `anchor.ico` instead, use a plain Windows shortcut:

```powershell
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$env:USERPROFILE\Desktop\Anchor.lnk")
$sc.TargetPath = "C:\Windows\System32\cmd.exe"
$sc.Arguments  = "/c start https://<anchor-host>.tailb49f65.ts.net"
$sc.IconLocation = "C:\dev\Anchor\anchor.ico,0"   # or local path on laptop/office
$sc.WindowStyle = 7   # minimized — hides the cmd flash
$sc.Save()
```

Right-click the resulting Desktop shortcut → Pin to taskbar.

### iPad

1. Open Safari, go to `https://<anchor-host>.tailb49f65.ts.net`.
2. Share button → "Add to Home Screen" → name it "Anchor".
3. Tap the home-screen icon to launch the dashboard full-screen (no Safari chrome). Drag it to your dock alongside Safari/Mail.

iPad uses the favicon shipped by the server. The repo now ships `anchor-touch.png` (180×180, Option C) — to wire it up cleanly, update `generate_html()` in `anchor_gui.py` to include `<link rel="apple-touch-icon" href="/anchor-touch.png">` plus `<link rel="icon" href="/anchor.png">` in the `<head>`, and add a small handler in `AnchorHandler` to serve those two static files. Once that lands, "Add to Home Screen" picks up the Option C icon automatically. Polish task — does not block the migration.

### On the new desktop itself

The repo includes `pin_anchor_to_taskbar.vbs` — it creates a Desktop shortcut for `http://localhost:8777`. Run it once. We'll update its `IconLocation` to point at the new `anchor.ico` as part of the icon swap.

---

## Step 7 — Update docs, decommission the laptop copy

On the **new desktop**, add a host-machine line near the top of `C:\dev\Anchor\CLAUDE.md`:

> **Host machine (since 2026-05-11):** Anchor server runs on the dedicated Windows 11 desktop, exposed to the tailnet via Tailscale Serve at `https://<anchor-host>.tailb49f65.ts.net`. The previous laptop copy at `C:\dev\Anchor` is now a frozen backup.

On the **laptop**, prepend a dead-backup banner to `C:\dev\Anchor\CLAUDE.md`:

```markdown
> **⚠ DEAD BACKUP (as of 2026-05-11):** This folder is a frozen historical snapshot. **Do not read or write to it** for any operational purpose. The active Anchor system now runs on the dedicated Windows 11 desktop, served over Tailscale at `https://<anchor-host>.tailb49f65.ts.net`. This laptop copy is preserved only as a safety net while we verify the new setup.
```

Also disable any laptop-side auto-start so you don't accidentally launch a stale server pointing at the dead copy. Check Task Scheduler for an existing "Anchor" task (or whatever name you used) and disable it.

After two clean weeks of operation on the new host, you can delete or rename the laptop's `C:\dev\Anchor` to `_archive_anchor_laptop_pre_2026-05-11`.

---

## Verification checklist

Run all of these once you think you're done. Tick them off:

- [ ] `https://<anchor-host>.tailb49f65.ts.net` loads the dashboard from each device on your tailnet.
- [ ] Browser shows a valid Let's-Encrypt cert with no warnings (especially on iPad Safari).
- [ ] Check a task on the laptop → reload on the iPad → task shows checked.
- [ ] Capture an inbox item from the iPad → `Get-Content C:\dev\Anchor\INBOX.md` on the new desktop confirms it.
- [ ] Reboot the new desktop. Log back in (or RDP in). The URL works without any manual launch.
- [ ] `python anchor_healthcheck.py` on the new desktop produces today's report at `C:\dev\Anchor\health_reports\`.
- [ ] Office desktop: pin icon and repeat the smoke test next time you're there.
- [ ] Laptop's `C:\dev\Anchor` CLAUDE.md shows the dead-backup banner; laptop's auto-start (if any) is disabled.
- [ ] `tailscale serve status` on the new desktop still shows the HTTPS mapping after a reboot.

---

## Rollback

The migration is essentially zero-risk during the cutover window:

1. The laptop's `C:\dev\Anchor` is untouched by Steps 1–6 — re-enable its taskbar shortcut and the prior setup is back in 30 seconds.
2. On the new desktop, `tailscale serve reset` clears the Serve config without harming anything else.
3. The markdown files on both sides are identical right after the clone, so no data is at risk *as long as you don't make edits on both machines in parallel*. Pick one as authoritative (the new desktop, as soon as Step 2 passes) and stop editing on the laptop.

---

## Post-migration polish (optional, doesn't block cutover)

Already shipped in `C:\dev\Anchor\` as part of the icon work:

- `anchor.ico` — multi-resolution Windows icon (Option C, 7 sizes)
- `anchor.png` — 256×256 raster
- `anchor-touch.png` — 180×180 for iPad home-screen
- `anchor.svg` — source, so the icon can be regenerated or recolored later

Still to do after the migration is healthy:

1. Update `generate_html()` in `anchor_gui.py` to inject `<link rel="icon" href="/anchor.png">` and `<link rel="apple-touch-icon" href="/anchor-touch.png">` in the `<head>`, and add an `AnchorHandler.do_GET()` branch that serves those static files. Once that lands, every device that opens the URL gets the Option C icon automatically — Edge's "install as app", iPad's "Add to Home Screen", browser tabs, all of it.
2. Update `pin_anchor_to_taskbar.vbs` to point `IconLocation` at `C:\dev\Anchor\anchor.ico`.
3. Add a sibling `pin_anchor_remote.ps1` that creates a URL shortcut to the Tailscale URL for laptop / office desktop (same idea as the inline `WScript.Shell` snippet in Step 6, just packaged).

`.gitignore` already has explicit `!anchor.ico`, `!anchor.png`, `!anchor-touch.png` exceptions (committed alongside the icon assets in Step 0), so the icons travel with every future clone.

None of this blocks the migration. Do the migration first; come back to these once you're stable on the new host.
