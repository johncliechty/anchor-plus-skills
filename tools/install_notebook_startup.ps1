# Startup only: provision the dedicated account, runtimes, settings, and private HTTPS separately.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PythonExecutable,
    [Parameter(Mandatory)][string]$ServiceScript,
    [Parameter(Mandatory)][string]$SettingsFile,
    [Parameter(Mandatory)][string]$Account,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')][string]$TaskName = 'AnchorNotebookHost',
    [ValidateSet('Install','Plan','Status','Validate')][string]$Action = 'Install',
    [ValidateRange(30000,500000)][int]$MaxCodeEntries = 200000,
    [System.Management.Automation.PSCredential]$Credential
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:failure = 'startup_validation_failed'
$script:codeEntriesChecked = 0
$script:validationPath = $null
$registered = $null; $credentialBstr = [IntPtr]::Zero; $plainPassword = $null
function Fail([string]$Code) { $script:failure = $Code; throw $Code }

function Get-AnchorNotebookLocalGroupSids([string]$UserName) {
    if (-not ('AnchorNotebookLocalGroups' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class AnchorNotebookLocalGroups {
    [DllImport("Netapi32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern uint NetUserGetLocalGroups(
        string serverName, string userName, uint level, uint flags,
        out IntPtr buffer, int preferredMaximumLength,
        out uint entriesRead, out uint totalEntries);

    [DllImport("Netapi32.dll", ExactSpelling = true)]
    public static extern uint NetApiBufferFree(IntPtr buffer);
}
'@ -ErrorAction Stop
    }

    $buffer = [IntPtr]::Zero
    [uint32]$entriesRead = 0
    [uint32]$totalEntries = 0
    try {
        # Level 0 contains group-name pointers; flag 1 includes indirect memberships.
        $status = [AnchorNotebookLocalGroups]::NetUserGetLocalGroups(
            $null, $UserName, 0, 1, [ref]$buffer, -1,
            [ref]$entriesRead, [ref]$totalEntries)
        if ($status -ne 0 -or $entriesRead -ne $totalEntries -or
            ($entriesRead -gt 0 -and $buffer -eq [IntPtr]::Zero)) {
            throw 'account_group_membership_lookup_failed'
        }
        for ($index = 0; $index -lt $entriesRead; $index++) {
            $namePointer = [Runtime.InteropServices.Marshal]::ReadIntPtr(
                $buffer, ($index * [IntPtr]::Size))
            $groupName = [Runtime.InteropServices.Marshal]::PtrToStringUni($namePointer)
            if ([string]::IsNullOrWhiteSpace($groupName)) {
                throw 'account_group_sid_resolution_failed'
            }
            $groups = @(Get-LocalGroup -Name $groupName -ErrorAction Stop)
            if ($groups.Count -ne 1 -or $groups[0].Name -ine $groupName -or
                $null -eq $groups[0].SID -or [string]::IsNullOrWhiteSpace($groups[0].SID.Value)) {
                throw 'account_group_sid_resolution_failed'
            }
            $groups[0].SID.Value
        }
    } finally {
        if ($buffer -ne [IntPtr]::Zero) {
            if ([AnchorNotebookLocalGroups]::NetApiBufferFree($buffer) -ne 0) {
                throw 'account_group_buffer_free_failed'
            }
        }
    }
}
function Exact-Path([string]$Value, [bool]$Directory = $false) {
    if ($Value -notmatch '^[A-Za-z]:[\\/]' -or $Value -match '[\x00-\x1f"]' -or $Value.Substring(2).Contains(':')) { Fail 'absolute_local_path_required' }
    $full = [IO.Path]::GetFullPath($Value)
    if (([IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))).DriveType -ne 'Fixed') { Fail 'fixed_disk_required' }
    $item = Get-Item -LiteralPath $full -Force
    if ([bool]$item.PSIsContainer -ne $Directory) { Fail 'path_type_mismatch' }
    $node = $item
    while ($null -ne $node) {
        if ($node.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail 'reparse_path_refused' }
        $node = if ($node -is [IO.DirectoryInfo]) { $node.Parent } else { $node.Directory }
    }
    return $item.FullName
}
function Within([string]$Path, [string]$Root) {
    return $Path.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or $Path.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}
function Escape-Xml([string]$Value) { return [Security.SecurityElement]::Escape($Value) }
function Check-Acl([string]$Path, [string[]]$Owners, [string[]]$Writers, [bool]$Private = $false, [bool]$Writable = $false, [bool]$Ancestor = $false) {
    $script:validationPath = $Path
    $acl = Get-Acl -LiteralPath $Path
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $Owners) { Fail 'approval_required_untrusted_path_owner' }
    if ($Private -and -not $acl.AreAccessRulesProtected) { Fail 'private_acl_must_be_protected' }
    $mask = [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    if (-not $Ancestor) { $mask = $mask -bor [Security.AccessControl.FileSystemRights]::Write }
    $accountRights = 0
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($Private -and $rule.AccessControlType -ne 'Allow') { Fail 'private_acl_requires_clean_allow_policy' }
        $ruleSid = $rule.IdentityReference.Value
        if ($Private -and $ruleSid -notin $Writers) { Fail 'private_acl_has_other_principal' }
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -ne 'Allow') { continue }
        if (($rule.FileSystemRights -band $mask) -and $ruleSid -notin $Writers) { Fail 'approval_required_writable_executable_chain' }
        if ($ruleSid -eq $script:accountSid) { $accountRights = $accountRights -bor $rule.FileSystemRights }
    }
    if ($Private) {
        $required = [Security.AccessControl.FileSystemRights]::Read
        if ($Writable) { $required = [Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Write }
        if (($accountRights -band $required) -ne $required) { Fail 'private_acl_missing_account_access' }
    }
}
function Check-Ancestors([string]$Path, [string[]]$Trusted) {
    $item = Get-Item -LiteralPath $Path -Force
    $node = if ($item.PSIsContainer) { $item.Parent } else { $item.Directory }
    while ($null -ne $node) {
        Check-Acl $node.FullName $Trusted $Trusted $false $false $true
        $node = $node.Parent
    }
}
try {
    if ($Action -eq 'Status') {
        $scheduler = New-Object -ComObject 'Schedule.Service'; $scheduler.Connect()
        $folder = $scheduler.GetFolder('\')
        $task = @($folder.GetTasks(1) | Where-Object { $_.Name -eq $TaskName })
        if ($task.Count -eq 0) { @{ok=$true; installed=$false; task_name=$TaskName} | ConvertTo-Json -Compress; return }
        @{ok=$true; installed=$true; task_name=$TaskName; enabled=$task[0].Enabled; state=$task[0].State; last_result=$task[0].LastTaskResult; last_run=$task[0].LastRunTime; next_run=$task[0].NextRunTime; readiness='not_proven'} | ConvertTo-Json -Compress
        return
    }
    $parts = $Account.Split('\')
    if ($parts.Count -ne 2 -or $parts[0] -ine [Environment]::MachineName -or $parts[1] -match '[@\\/*?\[\]:\x00-\x1f]' -or -not $parts[1]) { Fail 'exact_local_account_required' }
    $python = Exact-Path $PythonExecutable; $serviceFile = Exact-Path $ServiceScript; $settingsPath = Exact-Path $SettingsFile
    if ([IO.Path]::GetFileName($python) -notin @('python.exe','python3.exe')) { Fail 'python_executable_required' }
    if ([IO.Path]::GetFileName($serviceFile) -ine 'notebook_service.py') { Fail 'notebook_service_script_required' }
    $document = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    if ((@($document.PSObject.Properties.Name | Sort-Object) -join ',') -ne 'runtime,service') { Fail 'settings_document_shape_invalid' }
    $runtime = $document.runtime; $service = $document.service
    if (($runtime.schema_version -isnot [int] -and $runtime.schema_version -isnot [long]) -or $runtime.schema_version -ne 1 -or $runtime.enabled -isnot [bool] -or -not $runtime.enabled) { Fail 'runtime_not_enabled' }
    if ($service.service_account -ine $Account -or $service.dedicated_account_confirmed -isnot [bool] -or -not $service.dedicated_account_confirmed -or $runtime.execution_host -ine [Net.Dns]::GetHostName()) { Fail 'settings_identity_mismatch' }
    $public = [Uri]$runtime.public_base_url
    if (-not $public.IsAbsoluteUri -or $public.Scheme -ne 'https' -or $public.UserInfo -or $public.Query -or $public.Fragment) { Fail 'private_https_endpoint_required' }
    if ($service.listen_host -ne '127.0.0.1' -or ($service.port -isnot [long] -and $service.port -isnot [int]) -or $service.port -lt 1024 -or $service.port -gt 65535) { Fail 'loopback_listener_required' }
    $workspace = Exact-Path $runtime.root_dir $true; $runtimeDir = Exact-Path $service.runtime_dir $true
    $passwordFile = Exact-Path $service.password_file
    foreach ($path in @($python,$serviceFile,$settingsPath,$runtimeDir,$passwordFile)) { if (Within $path $workspace) { Fail 'service_paths_must_be_outside_workspace' } }
    if (-not (Within $passwordFile $runtimeDir)) { Fail 'password_file_must_be_private' }
    $kernels = @($runtime.local_kernel_specs.PSObject.Properties.Name)
    if ('python3' -notin $kernels -or @($kernels | Where-Object { $_ -notin @('python3','ir') }).Count) { Fail 'local_kernel_specs_invalid' }
    $pyArgs = @($runtime.local_kernel_specs.python3)
    if ($pyArgs.Count -ne 5 -or (Exact-Path $pyArgs[0]) -ine $python -or ($pyArgs[1..4] -join '|') -cne '-m|ipykernel_launcher|-f|{connection_file}') { Fail 'python_kernel_identity_mismatch' }
    $pythonRoot = Split-Path -Parent $python; $serviceRoot = Split-Path -Parent $serviceFile
    $venvConfig = $null; $basePythonRoot = $null; $excludedBasePackages = $null
    $codeRoots = @($pythonRoot, $serviceRoot)
    $candidateConfig = Join-Path (Split-Path -Parent $pythonRoot) 'pyvenv.cfg'
    if ((Split-Path -Leaf $pythonRoot) -eq 'Scripts' -and (Test-Path -LiteralPath $candidateConfig)) {
        $venvConfig = Exact-Path $candidateConfig; $venvRoot = Split-Path -Parent $venvConfig
        if ((Get-Item -LiteralPath $venvConfig).Length -gt 16384) { Fail 'venv_configuration_too_large' }
        $venvFields = @{}
        foreach ($line in Get-Content -LiteralPath $venvConfig -Encoding UTF8) {
            if (-not $line.Trim() -or $line.Trim().StartsWith('#')) { continue }
            if ($line -notmatch '^\s*([A-Za-z0-9_-]+)\s*=\s*(.*?)\s*$') { Fail 'venv_configuration_invalid' }
            $key = $Matches[1].ToLowerInvariant(); $value = $Matches[2]
            if ($venvFields.ContainsKey($key) -or $key -notin @('home','include-system-site-packages','version','executable','command')) { Fail 'venv_configuration_unsupported' }
            $venvFields[$key] = $value
        }
        if (-not $venvFields.ContainsKey('home') -or $venvFields['include-system-site-packages'] -cne 'false') { Fail 'isolated_venv_required' }
        $basePythonRoot = Exact-Path $venvFields['home'] $true
        $baseExecutable = Exact-Path (Join-Path $basePythonRoot 'python.exe')
        if ($venvFields.ContainsKey('executable') -and (Exact-Path $venvFields['executable']) -ine $baseExecutable) { Fail 'venv_base_identity_mismatch' }
        if ((Within $venvRoot $basePythonRoot) -or (Within $basePythonRoot $venvRoot)) { Fail 'venv_and_base_must_be_separate' }
        $baseLib = Exact-Path (Join-Path $basePythonRoot 'Lib') $true
        $baseDlls = Exact-Path (Join-Path $basePythonRoot 'DLLs') $true
        $excludedBasePackages = Join-Path $baseLib 'site-packages'
        $codeRoots = @($venvRoot, $baseLib, $baseDlls, $serviceRoot)
    }
    if ('ir' -in $kernels) {
        $rArgs = @($runtime.local_kernel_specs.ir)
        if ($rArgs.Count -ne 6 -or ($rArgs[1..5] -join '|') -cne '--slave|-e|IRkernel::main()|--args|{connection_file}') { Fail 'r_kernel_identity_mismatch' }
        $rExe = Exact-Path $rArgs[0]; $rBin = Split-Path -Parent $rExe
        if ((Split-Path -Leaf $rBin) -eq 'x64') { $rBin = Split-Path -Parent $rBin }
        if ((Split-Path -Leaf $rBin) -ne 'bin' -or [IO.Path]::GetFileName($rExe) -ine 'R.exe') { Fail 'approval_required_r_layout' }
        $codeRoots += Exact-Path (Split-Path -Parent $rBin) $true
    }
    foreach ($path in @($service.runtime_paths) + @($service.r_library_dirs)) { $codeRoots += Exact-Path $path $true }
    foreach ($path in $codeRoots) { if ((Within $path $workspace) -or (Within $workspace $path) -or (Within $runtimeDir $path)) { Fail 'protected_code_roots_must_be_separate' } }
    if ($basePythonRoot -and ((Within $basePythonRoot $workspace) -or (Within $workspace $basePythonRoot) -or (Within $runtimeDir $basePythonRoot))) { Fail 'protected_base_must_be_separate' }
    $arguments = '-I "' + $serviceFile + '" --settings "' + $settingsPath + '"'
    $xml = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Anchor dedicated-account notebook host; activation is not readiness proof.</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled><Delay>PT20S</Delay></BootTrigger></Triggers>
  <Principals><Principal id="NotebookAccount"><UserId>$(Escape-Xml $Account)</UserId><LogonType>Password</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>false</Enabled><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure></Settings>
  <Actions Context="NotebookAccount"><Exec><Command>$(Escape-Xml $python)</Command><Arguments>$(Escape-Xml $arguments)</Arguments><WorkingDirectory>$(Escape-Xml $serviceRoot)</WorkingDirectory></Exec></Actions>
</Task>
"@
    if ($Action -eq 'Plan') {
        @{ok=$true; action='plan'; task_name=$TaskName; account=$Account; workspace=$workspace; task_xml=$xml; registration_disabled_until_verified=$true; account_acl_checks='deferred_to_install'; endpoint_access='not_verified'; readiness='not_proven'} | ConvertTo-Json -Depth 5
        return
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail 'administrator_approval_required' }
    $script:failure = 'local_account_validation_failed'
    $user = @(Get-LocalUser -Name $parts[1])
    if ($user.Count -ne 1 -or $user[0].Name -ine $parts[1] -or -not $user[0].Enabled -or $user[0].SID.Value -notmatch '^S-1-5-21-.+-\d+$') { Fail 'enabled_standard_local_account_required' }
    $script:accountSid = $user[0].SID.Value
    if ([long]($script:accountSid.Split('-')[-1]) -lt 1000) { Fail 'built_in_account_refused' }
    try {
        $accountGroupSids = @(Get-AnchorNotebookLocalGroupSids -UserName $parts[1])
    } catch {
        Fail 'account_group_membership_lookup_failed'
    }
    foreach ($groupSid in $accountGroupSids) {
        if ($groupSid -ne 'S-1-5-32-545') { Fail 'account_has_nonstandard_group_membership' }
    }
    $trusted = @('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464',$identity.User.Value)
    $privateTrust = @('S-1-5-18','S-1-5-32-544',$script:accountSid)
    Check-Acl $runtimeDir $privateTrust $privateTrust $true $true
    Check-Acl $settingsPath $privateTrust $privateTrust $true
    Check-Acl $passwordFile $privateTrust $privateTrust $true
    Check-Ancestors $runtimeDir ($trusted + $script:accountSid)
    Check-Ancestors $settingsPath ($trusted + $script:accountSid)
    Check-Ancestors $passwordFile ($trusted + $script:accountSid)
    if (-not $venvConfig -and ((Test-Path -LiteralPath (Join-Path $pythonRoot 'pyvenv.cfg')) -or (Test-Path -LiteralPath $candidateConfig))) { Fail 'approval_required_venv_layout' }
    $pending = [Collections.Generic.Queue[object]]::new(); $seen = @{}
    foreach ($path in ($codeRoots | Select-Object -Unique)) { Check-Ancestors $path $trusted; $pending.Enqueue((Get-Item -LiteralPath $path -Force)) }
    if ($basePythonRoot) {
        Check-Ancestors $basePythonRoot $trusted; Check-Acl $basePythonRoot $trusted $trusted
        foreach ($baseFile in Get-ChildItem -LiteralPath $basePythonRoot -Force -File) { $pending.Enqueue($baseFile) }
    }
    while ($pending.Count) {
        $item = $pending.Dequeue()
        if ($excludedBasePackages -and $item.FullName -ieq $excludedBasePackages) { continue }
        if ($seen.ContainsKey($item.FullName)) { continue }; $seen[$item.FullName] = $true
        $script:codeEntriesChecked = $seen.Count
        if ($seen.Count -gt $MaxCodeEntries) { Fail 'code_tree_scan_limit_exceeded' }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail 'reparse_code_tree_refused' }
        Check-Acl $item.FullName $trusted $trusted
        if ($item.PSIsContainer) { foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) { $pending.Enqueue($child) } }
        elseif ($item.Name -like '*._pth' -or ($item.Name -eq 'pyvenv.cfg' -and $item.FullName -ine $venvConfig)) { Fail 'approval_required_python_path_indirection' }
        elseif ($item.Extension -eq '.pth' -and @(Get-Content -LiteralPath $item.FullName | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') }).Count) { Fail 'approval_required_python_pth_review' }
    }
    $scheduler = New-Object -ComObject 'Schedule.Service'; $scheduler.Connect(); $folder = $scheduler.GetFolder('\')
    if (@($folder.GetTasks(1) | Where-Object { $_.Name -eq $TaskName }).Count) { Fail 'task_already_exists_no_overwrite' }
    if ($Action -eq 'Validate') {
        @{ok=$true;action='validate';task_name=$TaskName;account=$Account;readiness='not_proven';endpoint_access='not_verified';code_entries_checked=$script:codeEntriesChecked;max_code_entries=$MaxCodeEntries} | ConvertTo-Json -Compress
        return
    }
    if ($null -eq $Credential) { $Credential = Get-Credential -UserName $Account -Message 'Register the existing dedicated notebook account for unattended startup.' }
    if ($null -eq $Credential -or $Credential.UserName -ine $Account -or $Credential.Password.Length -eq 0) { Fail 'exact_account_credential_required' }
    $script:failure = 'task_registration_failed'
    try {
        $credentialBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($credentialBstr)
        $registered = $folder.RegisterTask($TaskName, $xml, 2, $Account, $plainPassword, 1, 'D:P(A;;FA;;;SY)(A;;FA;;;BA)')
    } finally {
        $plainPassword = $null; $Credential = $null
        if ($credentialBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($credentialBstr); $credentialBstr = [IntPtr]::Zero }
    }
    $script:failure = 'registered_task_verification_failed'
    [xml]$actual = $registered.Xml
    $ns = [Xml.XmlNamespaceManager]::new($actual.NameTable); $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    $checks = @{
        't:Principals/t:Principal/t:LogonType'='Password'; 't:Principals/t:Principal/t:RunLevel'='LeastPrivilege'
        't:Triggers/t:BootTrigger/t:Delay'='PT20S'; 't:Triggers/t:BootTrigger/t:Enabled'='true'
        't:Settings/t:MultipleInstancesPolicy'='IgnoreNew'; 't:Settings/t:ExecutionTimeLimit'='PT0S'; 't:Settings/t:Enabled'='false'
        't:Settings/t:StartWhenAvailable'='true'; 't:Settings/t:AllowStartOnDemand'='true'
        't:Settings/t:RestartOnFailure/t:Interval'='PT1M'; 't:Settings/t:RestartOnFailure/t:Count'='3'
        't:Actions/t:Exec/t:Command'=$python; 't:Actions/t:Exec/t:Arguments'=$arguments; 't:Actions/t:Exec/t:WorkingDirectory'=$serviceRoot
    }
    foreach ($key in $checks.Keys) { $node = $actual.SelectSingleNode('/t:Task/' + $key,$ns); if ($null -eq $node -or $node.InnerText -cne $checks[$key]) { Fail 'registered_task_verification_failed' } }
    $principal = $actual.SelectSingleNode('/t:Task/t:Principals/t:Principal/t:UserId',$ns).InnerText
    if ($principal -ine $Account -and $principal -ne $script:accountSid) { Fail 'registered_task_identity_mismatch' }
    if ($actual.SelectNodes('/t:Task/t:Actions/*',$ns).Count -ne 1 -or $actual.SelectNodes('/t:Task/t:Triggers/*',$ns).Count -ne 1 -or $actual.SelectNodes('/t:Task/t:Principals/*',$ns).Count -ne 1) { Fail 'registered_task_extra_action_or_trigger' }
    $script:failure = 'task_enable_or_start_failed'
    $registered.Enabled = $true
    if (-not $folder.GetTask($TaskName).Enabled) { Fail 'registered_task_enable_failed' }
    $null = $registered.Run($null)
    @{ok=$true; installed=$true; start_requested=$true; task_name=$TaskName; account=$Account; readiness='not_proven'; reboot_proven=$false; endpoint_access='not_verified'; code_entries_checked=$script:codeEntriesChecked; max_code_entries=$MaxCodeEntries} | ConvertTo-Json -Compress
} catch {
    $plainPassword = $null; $Credential = $null
    if ($credentialBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($credentialBstr) }
    @{ok=$false; error=$script:failure; error_line=$_.InvocationInfo.ScriptLineNumber; validation_path=$script:validationPath; task_may_exist=($null -ne $registered); readiness='not_proven'; code_entries_checked=$script:codeEntriesChecked; max_code_entries=$MaxCodeEntries} | ConvertTo-Json -Compress
    exit 1
}
