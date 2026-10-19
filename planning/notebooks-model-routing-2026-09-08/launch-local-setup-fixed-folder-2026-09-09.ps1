# Private installation pickup. No credential transcript or shipped host paths.
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $PSScriptRoot 'fixed-folder-setup-result-2026-09-09.json'
function Write-SetupReceipt([string]$Status, [int]$Line = 0, [string]$Message = '') {
    $record = @{at=[DateTimeOffset]::UtcNow.ToString('o');status=$Status;pid=$PID;error_line=$Line;message=$Message}
    [IO.File]::WriteAllText($receiptPath, ($record | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
}
$Host.UI.RawUI.WindowTitle = 'Anchor notebook installation - Teaching folder selected'
try {
    $admin = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator confirmation is required for installation.' }
    Write-SetupReceipt 'checking_prior_dialog'
    if (Test-Path -LiteralPath 'C:\ProgramData\AnchorNotebook') { throw 'Installation state now exists; inspect it before continuing.' }
    if (Get-LocalUser -Name 'AnchorNotebook' -ErrorAction SilentlyContinue) { throw 'Notebook account now exists; inspect it before continuing.' }
    if (Get-ScheduledTask -TaskName 'AnchorNotebookHost' -ErrorAction SilentlyContinue) { throw 'Notebook task now exists; inspect it before continuing.' }
    $old = Get-CimInstance Win32_Process -Filter 'ProcessId=52184'
    if ($null -ne $old) {
        if ($old.Name -ine 'powershell.exe' -or $old.CommandLine -notlike '*launch-local-setup-2026-09-09.ps1*') { throw 'Previous setup process identity does not match; no process was changed.' }
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class ApprovedNotebookDialog {
 public delegate bool Callback(IntPtr hWnd, IntPtr lParam);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Callback cb, IntPtr param);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
'@
        $script:dialog = [IntPtr]::Zero
        $null = [ApprovedNotebookDialog]::EnumWindows({param($handle,$unused)
            $windowPid=[uint32]0
            $null=[ApprovedNotebookDialog]::GetWindowThreadProcessId($handle,[ref]$windowPid)
            if ($windowPid -eq 52184) {
                $caption=[Text.StringBuilder]::new(256)
                $null=[ApprovedNotebookDialog]::GetWindowText($handle,$caption,256)
                if ($caption.ToString() -eq 'Browse For Folder') { $script:dialog=$handle }
            }
            return $true
        },[IntPtr]::Zero)
        if ($script:dialog -eq [IntPtr]::Zero) { throw 'Previous setup has left its folder chooser; inspect its result before continuing.' }
        if (-not [ApprovedNotebookDialog]::PostMessage($script:dialog,0x0111,[IntPtr]2,[IntPtr]::Zero)) { throw 'Could not cancel the previous folder chooser; no second installation was started.' }
        $oldReceipt = Join-Path $PSScriptRoot 'local-setup-result-2026-09-09.json'
        $cancelled = $false
        for ($attempt=0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 250
            $prior = Get-Content -Raw -Encoding UTF8 -LiteralPath $oldReceipt | ConvertFrom-Json
            if ($prior.status -eq 'failed' -and $prior.message -like '*setup cancelled; no account was created*') { $cancelled=$true; break }
        }
        if (-not $cancelled) { throw 'Previous setup did not confirm cancellation; no second installation was started.' }
        Stop-Process -Id 52184
    }
    Write-SetupReceipt 'installing'
    Write-Host 'Software: C:\ProgramData\AnchorNotebook'
    Write-Host 'Existing class notebooks: C:\dev\Teaching (Math 541 and Econ 588).'
    Write-Host 'The software will prepare first. When asked, enter a new Jupyter password here, not in chat.'
    & 'C:\dev\Anchor\tools\setup_notebooks.ps1' -PythonExecutable 'C:\Users\john\AppData\Local\Programs\Python\Python313\python.exe' -AnchorDataDirectory 'C:\dev\Anchor' -PublicBaseUrl 'https://gwl-server.tailb49f65.ts.net:8448/' -NotebookRoot 'C:\dev\Teaching' -RExecutable 'C:\Users\john\AppData\Local\Programs\R\bin\R.exe' -RLibraryDirectories @('C:\Users\john\AppData\Local\R\win-library\4.6','C:\Users\john\AppData\Local\Programs\R\library') -TailscaleExecutable 'C:\Program Files\Tailscale\tailscale.exe'
    Write-SetupReceipt 'installed_acceptance_pending'
    Write-Host 'Installation finished. Codex will verify notebook execution and Anchor links.'
} catch {
    Write-SetupReceipt 'failed' $_.InvocationInfo.ScriptLineNumber $_.Exception.Message
    Write-Host 'Setup stopped. Leave this window open; Codex will inspect the non-secret receipt before recovery.' -ForegroundColor Yellow
}
