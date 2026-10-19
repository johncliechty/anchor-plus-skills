# Complete only this positively identified, retained notebook installation.
$ErrorActionPreference = 'Stop'
$resultPath = Join-Path $PSScriptRoot 'notebook-startup-resume-result-2026-09-10.json'
if (Test-Path -LiteralPath $resultPath) {
    Write-Host ('This attempt already has a result. It was preserved: ' + $resultPath) -ForegroundColor Yellow
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run this in the Administrator PowerShell window.' -ForegroundColor Yellow
    return
}
$record = @{at=[DateTimeOffset]::UtcNow.ToString('o');pid=$PID;status='validating_retained_installation';phase='identity_checks'}
$accountPassword = $null
$credential = $null
function Save-ResumeResult {
    $record.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($resultPath,($record | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
}
function Startup-Result([string]$Action, $StartupCredential=$null) {
    $arguments = @{Action=$Action;PythonExecutable=$python;ServiceScript=$serviceFile;SettingsFile=$settingsFile;Account=$account}
    if ($null -ne $StartupCredential) { $arguments.Credential = $StartupCredential }
    $output = @(& $startup @arguments)
    return (($output -join [Environment]::NewLine) | ConvertFrom-Json)
}
try {
    Save-ResumeResult
    $verified = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'startup-resume-verified-source-2026-09-10.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $startup = 'C:\dev\Anchor\tools\install_notebook_startup.ps1'
    $setup = 'C:\dev\Anchor\tools\setup_notebooks.ps1'
    if ($verified.status -ne 'passed' -or (Get-FileHash -LiteralPath $startup -Algorithm SHA256).Hash -ine $verified.startup_sha256 -or (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash -ine $verified.setup_sha256) { throw 'Verified installer sources changed; no installation action taken.' }
    # Reuse only these verified function definitions; never run the fresh installer body.
    $tokens = $null; $parseErrors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($setup,[ref]$tokens,[ref]$parseErrors)
    if ($parseErrors.Count) { throw 'Verified setup source did not parse.' }
    foreach ($functionName in @('LocalPath','Native','WriteJsonNew')) {
        $definitions = @($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName},$true))
        if ($definitions.Count -ne 1) { throw 'Verified helper definition is not unique.' }
        . ([scriptblock]::Create($definitions[0].Extent.Text))
    }
    $install = LocalPath 'C:\ProgramData\AnchorNotebook'
    $manifest = Get-Content -LiteralPath (LocalPath (Join-Path $install 'installation.json') $false) -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedSid = 'S-1-5-21-2519451599-2226736531-398949285-1008'
    $account = $env:COMPUTERNAME + '\AnchorNotebook'
    $user = Get-LocalUser -Name 'AnchorNotebook'
    if ($manifest.schema_version -ne 1 -or $manifest.status -ne 'provisioning' -or $manifest.account_sid -ne $expectedSid -or $manifest.account -ine $account -or $manifest.workspace -ine 'C:\dev\Teaching' -or $manifest.task -ne 'AnchorNotebookHost' -or $user.SID.Value -ne $expectedSid -or -not $user.Enabled) { throw 'Owned account and retained installation identity do not match.' }
    $diagnostic = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'notebook-startup-diagnostic-2026-09-10.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($diagnostic.status -ne 'diagnosed' -or $diagnostic.account_sid -ne $expectedSid -or $diagnostic.validation.error -ne 'approval_required_code_tree_size' -or @($diagnostic.tasks).Count -ne 0) { throw 'Expected inspected pre-task scan-limit failure required.' }
    $record.account_sid = $expectedSid
    if (@(Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AnchorNotebookHost' }).Count) { throw 'A notebook task exists; it was preserved for inspection.' }
    $publicConfig = 'C:\dev\Anchor\notebook-runtime.json'
    if (Test-Path -LiteralPath $publicConfig) { throw 'Public runtime configuration exists; it was preserved.' }
    if (Test-Path -LiteralPath (Join-Path $install 'startup-installed.json')) { throw 'Startup completion receipt exists; it was preserved.' }
    $python = LocalPath (Join-Path $install 'python\Scripts\python.exe') $false
    $serviceFile = LocalPath (Join-Path $install 'app\notebook_service.py') $false
    $settingsFile = LocalPath (Join-Path $install 'private\service-settings.json') $false
    foreach ($module in @('notebook_service.py','notebook_runtime.py')) {
        $modulePath = LocalPath (Join-Path $install ('app\' + $module)) $false
        if ((Get-FileHash -LiteralPath $modulePath -Algorithm SHA256).Hash -ine $verified.modules.$module) { throw 'Retained service code does not match its approved source.' }
    }
    $settings = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($settings.runtime.root_dir -ine 'C:\dev\Teaching' -or $settings.runtime.public_base_url -ne 'https://gwl-server.tailb49f65.ts.net:8448/' -or $settings.service.service_account -ine $account -or $settings.service.listen_host -ne '127.0.0.1' -or $settings.service.port -ne 8891 -or $settings.service.password_file -ine (Join-Path $install 'private\password.json')) { throw 'Retained settings differ from the authorized installation.' }
    $null = LocalPath $settings.service.password_file $false
    $tailscale = LocalPath 'C:\Program Files\Tailscale\tailscale.exe' $false
    $tailStatus = (Native $tailscale @('status','--json')) | ConvertFrom-Json
    if ($tailStatus.BackendState -ne 'Running' -or $tailStatus.Self.DNSName.TrimEnd('.') -ine 'gwl-server.tailb49f65.ts.net') { throw 'Expected private Tailscale host is unavailable.' }
    function Assert-NotebookPortAvailable {
        $serve = (Native $tailscale @('serve','status','--json')) | ConvertFrom-Json
        $tcp = $serve.PSObject.Properties['TCP']
        if ($null -ne $tcp -and $null -ne $tcp.Value -and $tcp.Value.PSObject.Properties.Name -contains '8448') { throw 'Notebook HTTPS port is already configured; it was preserved.' }
    }
    Assert-NotebookPortAvailable
    if (Get-NetTCPConnection -State Listen -LocalPort 8891 -ErrorAction SilentlyContinue) { throw 'Notebook listener port is already occupied; it was preserved.' }
    $record.phase = 'validating_all_runtime_permissions'
    Save-ResumeResult
    Write-Host 'Checking the retained notebook software and permissions. Your Jupyter password stays unchanged.'
    $validation = Startup-Result 'Validate'
    $record.validation = $validation
    Save-ResumeResult
    if (-not $validation.ok) { throw ('Startup validation failed: ' + $validation.error) }
    # The discarded generated Windows-account credential is replaced only after
    # the exact owned account, absence of a task, and all runtime checks pass.
    if ((Get-LocalUser -Name 'AnchorNotebook').SID.Value -ne $expectedSid -or @(Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AnchorNotebookHost' }).Count) { throw 'Account or task state changed during validation.' }
    $record.phase = 'registering_automatic_startup'
    Save-ResumeResult
    $random = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($random)
        $accountPassword = ('Aa1!' + [Convert]::ToBase64String($random)) | ConvertTo-SecureString -AsPlainText -Force
    } finally { [Array]::Clear($random,0,$random.Length); $rng.Dispose() }
    Set-LocalUser -InputObject $user -Password $accountPassword
    $credential = [Management.Automation.PSCredential]::new($account,$accountPassword)
    $taskResult = Startup-Result 'Install' $credential
    $record.startup = $taskResult
    Save-ResumeResult
    if (-not $taskResult.ok -or -not $taskResult.start_requested) { throw ('Automatic startup failed: ' + $taskResult.error) }
    $credential = $null
    $accountPassword.Dispose(); $accountPassword = $null
    $record.phase = 'configuring_private_notebook_address'
    Save-ResumeResult
    Assert-NotebookPortAvailable
    $null = Native $tailscale @('serve','--bg','--https=8448','http://127.0.0.1:8891')
    # Enabled remains false until actual login, Python/R, persistence and recovery proof.
    $runtime = $settings.runtime
    $runtime.enabled = $false
    WriteJsonNew $publicConfig $runtime
    WriteJsonNew (Join-Path $install 'startup-installed.json') @{schema_version=1;status='startup_installed_acceptance_pending';task='AnchorNotebookHost';configuration=$publicConfig;checked_at=[DateTime]::UtcNow.ToString('o')}
    $record.status = 'installed_acceptance_pending'
    $record.phase = 'awaiting_live_notebook_verification'
    Save-ResumeResult
    Write-Host 'Automatic startup is installed. Leave this window open; Codex will verify opening and running notebooks.' -ForegroundColor Green
} catch {
    $record.status = 'failed'
    $record.error_type = $_.Exception.GetType().FullName
    $record.error_id = $_.FullyQualifiedErrorId
    $record.error_line = $_.InvocationInfo.ScriptLineNumber
    Save-ResumeResult
    Write-Host ('Recovery stopped during ' + $record.phase + '. Leave this window open; the result was preserved.') -ForegroundColor Yellow
    Write-Host ('Result: ' + $resultPath)
} finally {
    $credential = $null
    if ($null -ne $accountPassword) { $accountPassword.Dispose() }
}
