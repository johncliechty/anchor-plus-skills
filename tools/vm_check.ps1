# vm_check.ps1 — one-shot clean-box acceptance for the v1.1.3 share package.
#
# Run this ON THE VM (or a fresh Windows user account with NO Developer Mode
# and NO admin elevation), from inside the unzipped package root:
#
#   powershell -ExecutionPolicy Bypass -File .\tools\vm_check.ps1
#
# It performs the scripted (non-interactive-friendly) half of the collaborator
# journey and prints PASS/FAIL per check. The full interactive onboard
# (.\onboard.cmd) should ALSO be walked once by hand — this script proves the
# machinery; the dialogue proves the experience.

$ErrorActionPreference = "Continue"
$results = @()
function Check($name, $ok, $detail) {
  $tag = if ($ok) { "PASS" } else { "FAIL" }
  Write-Host ("[{0}] {1} - {2}" -f $tag, $name, $detail)
  $script:results += [pscustomobject]@{ name = $name; ok = [bool]$ok }
}

$pkg = (Get-Location).Path
Write-Host "Package root: $pkg`n"

# 1. Python present
$py = Get-Command python -ErrorAction SilentlyContinue
Check "python on PATH" ($null -ne $py) ($(if ($py) { $py.Source } else { "missing - run onboard.cmd first (it winget-installs Python)" }))
if (-not $py) { exit 1 }

# 2. Package completeness (the v1.1.x incident modules)
$mods = @("proc_probe.py","reaper.py","reaper_arming.py","freeze_state.py",
          "zombie_hunter.py","tidy_idy_runner.py","foundry_integrity.py",
          "foundry_safety.py","foundry_skills.py","foundry_acceptance.py",
          "verify_freeze_manifest.py","orientation.py","parity.py",
          "onboard.cmd","share_onboard.py","launch_anchor_dashboard.py",
          "USER-ONBOARD.md","VERSION","CLAUDE.md","anchor.ico")
$missing = $mods | Where-Object { -not (Test-Path (Join-Path $pkg $_)) }
Check "package completeness" ($missing.Count -eq 0) ($(if ($missing) { "missing: " + ($missing -join ", ") } else { "all present" }))

# 3. Doctor (deterministic; no AI calls)
& python doctor.py
Check "doctor exit code" ($LASTEXITCODE -eq 0) "exit=$LASTEXITCODE (non-zero = read the prescriptions above)"

# 4. Onboard, scripted (silent path never stamps ready - that is expected;
#    this only proves the machinery runs; walk .\onboard.cmd by hand after).
& python -m share_onboard --non-interactive --package B
Check "share_onboard machinery runs" ($LASTEXITCODE -ne 2) "exit=$LASTEXITCODE (2 = refused; non-2 expected here)"

# 5. Launcher genuinely starts the server
& python launch_anchor_dashboard.py --no-browser
Check "launcher starts server" ($LASTEXITCODE -eq 0) "exit=$LASTEXITCODE"
Start-Sleep -Seconds 2
try {
  $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8777/" -UseBasicParsing -TimeoutSec 5
  Check "dashboard HTTP 200" ($resp.StatusCode -eq 200) "status=$($resp.StatusCode)"
} catch {
  Check "dashboard HTTP 200" $false "$($_.Exception.Message)"
}

# 6. Error log clean of the incident class
$dataDir = if ($env:ANCHOR_DATA_DIR) { $env:ANCHOR_DATA_DIR } else { Join-Path $env:USERPROFILE ".anchor" }
$errLog = Join-Path $dataDir "logs\errors.log"
if (Test-Path $errLog) {
  $spam = Select-String -Path $errLog -Pattern "ModuleNotFoundError" -ErrorAction SilentlyContinue
  Check "errors.log clean of ModuleNotFoundError" ($null -eq $spam) ($(if ($spam) { $spam[0].Line } else { "clean" }))
} else {
  Check "errors.log clean of ModuleNotFoundError" $true "no errors.log yet"
}

# 7. Skills readable by Claude (junction/copy - a real SKILL.md, not a marker)
$farm = Join-Path $env:USERPROFILE ".claude\skills"
if (Test-Path $farm) {
  $unreadable = @()
  Get-ChildItem $farm -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    if (-not (Test-Path (Join-Path $_.FullName "SKILL.md"))) { $unreadable += $_.Name }
  }
  Check "Claude skills readable (SKILL.md present)" ($unreadable.Count -eq 0) ($(if ($unreadable) { "unreadable: " + ($unreadable -join ", ") } else { "all readable" }))
} else {
  Check "Claude skills readable (SKILL.md present)" $false "no ~/.claude/skills yet - run .\onboard.cmd first"
}

$failed = @($results | Where-Object { -not $_.ok })
Write-Host ""
Write-Host ("{0}/{1} checks passed." -f ($results.Count - $failed.Count), $results.Count)
if ($failed.Count -gt 0) { exit 1 } else { exit 0 }
