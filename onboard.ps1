# onboard.ps1 — Windows cold-start bootstrap for shareable Anchor / skills.
# Paste-friendly: open a terminal in the package root, then:
#   powershell -File .\onboard.ps1
#   or:  .\onboard.ps1
#
# 1) Ensure Python 3.8+ (winget install if missing when winget exists)
# 2) Run: python -m share_onboard  (interactive dialogue — never silent ready)
#
# North Star: collaborators do not pre-install Python by hand; this script owns it.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-PythonOk {
  param([string]$Exe)
  try {
    $v = & $Exe -c "import sys; print('%d.%d'%sys.version_info[:2]); raise SystemExit(0 if sys.version_info>=(3,8) else 2)" 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Find-Python {
  foreach ($c in @("python", "py", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $exe = $cmd.Source
    if ($c -eq "py") {
      try {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,8) else 2)" 2>$null
        if ($LASTEXITCODE -eq 0) { return "py -3" }
      } catch { }
      continue
    }
    if (Test-PythonOk $exe) { return $exe }
  }
  return $null
}

Write-Host "Anchor / skills onboard bootstrap"
Write-Host "Working directory: $PSScriptRoot"
Write-Host ""

$py = Find-Python
if (-not $py) {
  Write-Host "Python 3.8+ not found. Attempting install via winget (Python.Python.3.12)..."
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-Host "winget not available. Install Python 3.8+ from https://www.python.org/downloads/"
    Write-Host "Then re-run: powershell -File .\onboard.ps1"
    exit 3
  }
  & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    Write-Host "winget install did not succeed (exit $LASTEXITCODE). Install Python from https://www.python.org/downloads/ and re-run."
    exit 3
  }
  # Refresh PATH for this session from Machine+User
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [System.Environment]::GetEnvironmentVariable("Path", "User")
  $py = Find-Python
  if (-not $py) {
    Write-Host "Python installed but not on PATH yet. Close this terminal, open a new one in this folder, run .\onboard.ps1 again."
    exit 3
  }
}

Write-Host "Using Python: $py"
Write-Host "Starting interactive onboard (this will not stamp ready in silent mode)..."
Write-Host ""

if ($py -eq "py -3") {
  & py -3 -m share_onboard @args
} else {
  & $py -m share_onboard @args
}
exit $LASTEXITCODE
