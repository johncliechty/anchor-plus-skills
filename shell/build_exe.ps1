# Package the Anchor program for his other Windows PCs (every-device PLAN v1.2 D1): a folder (PyInstaller onedir -
# fewer antivirus false alarms than one exe) zipped as Anchor.zip. Run on PUTER from the Anchor folder:
#   powershell -ExecutionPolicy Bypass -File shell\build_exe.ps1
# Output: %LOCALAPPDATA%\anchor-shell\dist\Anchor\Anchor.exe and %LOCALAPPDATA%\anchor-shell\dist\Anchor.zip
# (outside the repo: built binaries never go into git).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py = Join-Path $env:LOCALAPPDATA "anchor-shell\.venv\Scripts\python.exe"
$out = Join-Path $env:LOCALAPPDATA "anchor-shell\dist"
$work = Join-Path $env:LOCALAPPDATA "anchor-shell\build"
$icon = Join-Path $root "vendor\brand\anchor-icon.ico"
$versionFile = Join-Path $root "VERSION"

& $py -m pip install -q pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
& $py -m PyInstaller --noconfirm --clean --onedir --windowed --name Anchor `
    --icon $icon --add-data "$icon;." --add-data "$versionFile;." `
    --paths $root --paths (Join-Path $root "shell") `
    --collect-all webview --hidden-import clr --hidden-import connect --hidden-import onboard_bootstrap `
    --distpath $out --workpath $work --specpath $work `
    (Join-Path $root "shell\anchor_shell.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Get-ChildItem -Path (Join-Path $out "Anchor") -Recurse | Unblock-File -ErrorAction SilentlyContinue
$zip = Join-Path $out "Anchor.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $out "Anchor") -DestinationPath $zip
"built: $zip  ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
