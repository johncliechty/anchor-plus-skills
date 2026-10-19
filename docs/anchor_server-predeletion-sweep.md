# Pre-deletion sweep — `anchor_server.py` (W10 / C5, 2026-07)

Before deleting the dead legacy Flask app `anchor_server.py` (port 5000), this
sweep confirms nothing live references it. The plan calls for three checks:
a scheduled-task scan, a `*.lnk` shortcut-target search for `:5000` /
`anchor_server`, and an `_archive/` grep — plus the in-repo reference sweep.

## In-repo evidence (OBSERVED — gathered with file-search tools)

| Check | Result |
|-------|--------|
| Runtime references to `anchor_server` (`*.py`/`*.md`/`*.json`/`*.ps1`/`*.bat`/`*.vbs`/`*.mjs`) | **None.** Only hits are research reports under `.anchor/projects/**/research/` and the plan/description docs, all of which describe it as dead legacy. No import, launcher, or service points at it. |
| `flask` / `from flask` imports across the tree | **`anchor_server.py` only.** After deletion, Flask has zero importers in product code (matching the stdlib-only contract; `requirements.txt` still lists `flask` as a stale entry — noted as follow-up hygiene, out of W10 scope). |
| Port `:5000` references | **`anchor_server.py` only** (its `app.run(..., port=5000)`, browser-open, and banner). No launcher, shortcut, or doc wires `:5000`. The live service is `:8777` (NSSM `anchor`). |
| `.lnk` shortcut files inside the repo | **None present** in the working tree. |
| `_archive/` grep for `anchor_server` / `:5000` | **No hits.** The frozen Axmra snapshot does not reference the dead server. |

Conclusion: within the repository, `anchor_server.py` is referenced by nothing
executable — consistent with the research finding *"DEAD LEGACY … not shipped,
not referenced by runtime"* `[OBSERVED | E9,E13]`.

## Host-level scans (run at the host — EXECUTE agent cannot spawn a shell)

The following two checks query OS state outside the repository. Per the build
rules the EXECUTE agent does not run terminal commands; the orchestrator/human
runs these at the host and appends the (expected-empty) results:

```powershell
# 1. Scheduled tasks referencing anchor_server / :5000
Get-ScheduledTask | Where-Object {
    ($_.Actions | Out-String) -match 'anchor_server|:5000|port 5000'
} | Select-Object TaskName, State
#   Expected: empty. (Per project CLAUDE.md, the disabled "Anchor Server"
#   task was already investigated and is NOT tied to the live :8777 service.)

# 2. Start-Menu / Desktop *.lnk shortcut targets pointing at :5000 / anchor_server
Get-ChildItem -Path "$env:APPDATA\Microsoft\Windows\Start Menu",
    "$env:USERPROFILE\Desktop", "$env:PUBLIC\Desktop" -Recurse -Filter *.lnk -EA 0 |
  ForEach-Object {
    $t = (New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName)
    if (($t.TargetPath + ' ' + $t.Arguments) -match 'anchor_server|5000') { $_.FullName }
  }
#   Expected: empty. Every Anchor launcher (AnchorDashboard.vbs/.bat,
#   launch_anchor.pyw, pin_anchor_to_taskbar.vbs) opens the browser only and
#   targets :8777 — never anchor_server / :5000.
```

Removal is safe: no runtime import, launcher, shortcut, scheduled task, or
archive references the file.
