# Read-only inspection of the retained task. Never registers, enables, or starts it.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$destination = Join-Path $PSScriptRoot 'registered-notebook-task-diagnostic-2026-09-10.json'
if (Test-Path -LiteralPath $destination) {
    Write-Host ('Diagnostic already saved: ' + $destination)
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run this in the existing Administrator PowerShell window.' -ForegroundColor Yellow
    return
}
$record = @{at=[DateTimeOffset]::UtcNow.ToString('o');pid=$PID;status='diagnosing';read_only=$true;errors=@()}
$operation = 'verify_owned_installation'
try {
    $install = 'C:\ProgramData\AnchorNotebook'
    $expectedSid = 'S-1-5-21-2519451599-2226736531-398949285-1008'
    $account = $env:COMPUTERNAME + '\AnchorNotebook'
    $receipt = Get-Content -LiteralPath (Join-Path $install 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $user = Get-LocalUser -Name 'AnchorNotebook'
    if ($receipt.schema_version -ne 1 -or $receipt.status -ne 'provisioning' -or $receipt.account_sid -ne $expectedSid -or $user.SID.Value -ne $expectedSid -or $receipt.account -ine $account -or $receipt.workspace -ine 'C:\dev\Teaching' -or $receipt.task -ne 'AnchorNotebookHost') { throw 'Owned installation receipt and notebook account must match.' }
    $record.account_sid = $expectedSid
    $record.account_enabled = $user.Enabled
    $operation = 'read_exact_registered_task'
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $task = $scheduler.GetFolder('\').GetTask('AnchorNotebookHost')
    # XML contains command configuration, never the Task Scheduler stored password.
    $record.actual_xml = [string]$task.Xml
    foreach ($property in @('Path','Enabled','State','LastTaskResult')) {
        try { $record[$property] = $task.$property }
        catch { $record.errors += @{operation=('task_' + $property);hresult=$_.Exception.HResult;message=$_.Exception.Message} }
    }
    try { $record.dacl = $task.GetSecurityDescriptor(4) }
    catch { $record.errors += @{operation='task_dacl';hresult=$_.Exception.HResult;message=$_.Exception.Message} }
    $operation = 'verify_startup_source'
    $startup = 'C:\dev\Anchor\tools\install_notebook_startup.ps1'
    $verified = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'registered-task-diagnostic-source-2026-09-10.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($verified.status -ne 'passed' -or (Get-FileHash -LiteralPath $startup -Algorithm SHA256).Hash -ine $verified.sha256) { throw 'Read-only plan entrypoint must match its verified source.' }
    $record.startup_sha256 = $verified.sha256
    $operation = 'read_intended_disabled_task_plan'
    $output = @(& $startup -Action Plan -PythonExecutable (Join-Path $install 'python\Scripts\python.exe') -ServiceScript (Join-Path $install 'app\notebook_service.py') -SettingsFile (Join-Path $install 'private\service-settings.json') -Account $account)
    $plan = ($output -join [Environment]::NewLine) | ConvertFrom-Json
    if (-not $plan.ok -or $plan.action -ne 'plan') { $record.plan_failure = $plan; throw 'Read-only task plan failed.' }
    $record.planned_xml = [string]$plan.task_xml
    $operation = 'compare_registered_xml_with_disabled_plan'
    [xml]$expected = $record.planned_xml
    [xml]$actual = $record.actual_xml
    $expectedNs = [Xml.XmlNamespaceManager]::new($expected.NameTable)
    $actualNs = [Xml.XmlNamespaceManager]::new($actual.NameTable)
    $namespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
    $expectedNs.AddNamespace('t',$namespace)
    $actualNs.AddNamespace('t',$namespace)
    $fields = @(
        't:Principals/t:Principal/t:UserId','t:Principals/t:Principal/t:LogonType','t:Principals/t:Principal/t:RunLevel',
        't:Triggers/t:BootTrigger/t:Delay','t:Triggers/t:BootTrigger/t:Enabled',
        't:Settings/t:MultipleInstancesPolicy','t:Settings/t:ExecutionTimeLimit','t:Settings/t:Enabled',
        't:Settings/t:StartWhenAvailable','t:Settings/t:AllowStartOnDemand',
        't:Settings/t:RestartOnFailure/t:Interval','t:Settings/t:RestartOnFailure/t:Count',
        't:Actions/t:Exec/t:Command','t:Actions/t:Exec/t:Arguments','t:Actions/t:Exec/t:WorkingDirectory'
    )
    $record.comparisons = @()
    foreach ($field in $fields) {
        $left = $expected.SelectSingleNode('/t:Task/' + $field,$expectedNs)
        $right = $actual.SelectSingleNode('/t:Task/' + $field,$actualNs)
        $leftText = if ($null -eq $left) { $null } else { $left.InnerText }
        $rightText = if ($null -eq $right) { $null } else { $right.InnerText }
        $record.comparisons += @{field=$field;expected=$leftText;actual=$rightText;missing=($null -eq $right);exact_match=($null -ne $right -and $leftText -ceq $rightText)}
    }
    $record.counts = @{
        actions=$actual.SelectNodes('/t:Task/t:Actions/*',$actualNs).Count
        triggers=$actual.SelectNodes('/t:Task/t:Triggers/*',$actualNs).Count
        principals=$actual.SelectNodes('/t:Task/t:Principals/*',$actualNs).Count
    }
    $record.status = 'diagnosed'
} catch {
    $record.status = 'diagnostic_incomplete'
    $record.errors += @{operation=$operation;hresult=$_.Exception.HResult;type=$_.Exception.GetType().FullName;message=$_.Exception.Message;line=$_.InvocationInfo.ScriptLineNumber}
} finally {
    $json = $record | ConvertTo-Json -Depth 12
    $stream = [IO.File]::Open($destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
        $stream.Write($bytes,0,$bytes.Length)
    } finally { $stream.Dispose() }
}
Write-Host 'Task diagnostic saved. No installation, account, password, permissions, or startup task was changed.'
Write-Host ('Result: ' + $destination)
