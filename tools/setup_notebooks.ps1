<# One-time, administrator-approved notebook setup. No daily manual startup.
   Windows/task credentials remain in process memory. Jupyter password is read
   securely and only its hash is written. Existing accounts/tasks/state are never
   adopted or overwritten. This entrypoint intentionally requires an interactive
   administrator session; it is not run when a notebook link is clicked. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$AnchorDataDirectory,
    [Parameter(Mandatory=$true)][string]$PublicBaseUrl,
    [string]$NotebookRoot,
    [string]$RExecutable,
    [string[]]$RLibraryDirectories = @(),
    [string]$InstallDirectory = (Join-Path $env:ProgramData 'AnchorNotebook'),
    [ValidatePattern('^[A-Za-z][A-Za-z0-9_-]{0,19}$')][string]$AccountName = 'AnchorNotebook',
    [ValidateRange(1024,65535)][int]$ListenPort = 8891,
    [string]$TailscaleExecutable,
    [ValidateRange(1024,65535)][int]$HttpsPort = 8448
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$notebookAdmin = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $notebookAdmin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this one-time notebook setup as administrator. No changes were made.'
}

function LocalPath([string]$Value, [bool]$Directory = $true) {
    if (-not [IO.Path]::IsPathRooted($Value) -or $Value.StartsWith('\\') -or $Value -match '[\x00-\x1f"<>|]') { throw 'An explicit local path is required.' }
    $resolved = [IO.Path]::GetFullPath($Value)
    if ($resolved.Substring(2).Contains(':')) { throw 'Alternate-stream paths are not accepted.' }
    $item = Get-Item -LiteralPath $resolved -Force
    if ([bool]$item.PSIsContainer -ne $Directory) { throw 'An installation path has the wrong type.' }
    $cursor = $item
    while ($null -ne $cursor) {
        if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installation paths must not contain junctions or symlinks.' }
        if ($cursor -is [IO.FileInfo]) { $cursor = $cursor.Directory } else { $cursor = $cursor.Parent }
    }
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($resolved))
    if ($drive.DriveType -ne [IO.DriveType]::Fixed) { throw 'A local fixed disk is required.' }
    return $resolved.TrimEnd('\')
}
function Within([string]$Child, [string]$Parent) {
    return $Child.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or $Child.StartsWith($Parent.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}
function Rule([string]$Sid, [Security.AccessControl.FileSystemRights]$Rights, [string]$Type='Allow', [bool]$Inherit=$true) {
    $inheritance = if ($Inherit) { 'ContainerInherit,ObjectInherit' } else { 'None' }
    return New-Object Security.AccessControl.FileSystemAccessRule(
        (New-Object Security.Principal.SecurityIdentifier($Sid)), $Rights, $inheritance, 'None', $Type)
}
function PrivateAcl([string]$Target, [string]$Sid, [bool]$Directory=$true, [bool]$Writable=$true) {
    $acl = if ($Directory) { New-Object Security.AccessControl.DirectorySecurity } else { New-Object Security.AccessControl.FileSecurity }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach ($principal in @('S-1-5-18','S-1-5-32-544')) { $acl.AddAccessRule((Rule $principal 'FullControl' 'Allow' $Directory)) }
    $rights = if ($Writable) { 'Modify' } else { 'ReadAndExecute' }
    $acl.AddAccessRule((Rule $Sid $rights 'Allow' $Directory))
    Set-Acl -LiteralPath $Target -AclObject $acl
}
function Native([string]$Exe, [string[]]$Arguments, [string]$InputText='', [int]$TimeoutMilliseconds=120000) {
    # Arguments here are generated fixed flags/quoted validated local paths.
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe; $psi.Arguments = $Arguments -join ' '
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process; $process.StartInfo = $psi
    try {
        if (-not $process.Start()) { throw 'A notebook setup dependency could not start.' }
        $out = $process.StandardOutput.ReadToEndAsync(); $err = $process.StandardError.ReadToEndAsync()
        if ($InputText) {
            # Windows PowerShell's .NET Framework lacks StandardInputEncoding.
            # Write exact UTF-8 bytes to the pipe; never put a secret in argv.
            $inputBytes = (New-Object Text.UTF8Encoding($false)).GetBytes($InputText)
            try { $process.StandardInput.BaseStream.Write($inputBytes,0,$inputBytes.Length) }
            finally { [Array]::Clear($inputBytes,0,$inputBytes.Length) }
        }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            $process.Kill(); $null = $process.WaitForExit(5000)
            throw 'Notebook setup dependency timed out; its owned process was stopped. Inspect setup state before retrying.'
        }
        $output = $out.GetAwaiter().GetResult(); $null = $err.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw 'A notebook dependency check failed; no secret-bearing output was printed.' }
        return $output
    } finally { $process.Dispose() }
}
function Read-JupyterPasswordHash([string]$PythonExecutable) {
    while ($true) {
        $jupyterSecret = $null; $confirmation = $null
        $secretPointer = [IntPtr]::Zero; $confirmPointer = [IntPtr]::Zero
        $clear = $null; $check = $null
        try {
            $jupyterSecret = Read-Host 'Jupyter password (at least 12 characters)' -AsSecureString
            $confirmation = Read-Host 'Confirm Jupyter password' -AsSecureString
            $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($jupyterSecret)
            $confirmPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($confirmation)
            $clear = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
            $check = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($confirmPointer)
            if ($clear.Length -lt 12) {
                Write-Host 'Password must contain at least 12 characters. Please try again.'
                continue
            }
            if (-not [string]::Equals($clear, $check, [StringComparison]::Ordinal)) {
                Write-Host 'Passwords do not match exactly (including case). Please try again.'
                continue
            }
            return (Native $PythonExecutable @('-I','-c','"import sys; from jupyter_server.auth.security import passwd; print(passwd(sys.stdin.buffer.read().decode(''utf-8'')))"') $clear).Trim()
        } finally {
            if ($secretPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer) }
            if ($confirmPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($confirmPointer) }
            $clear = $null; $check = $null
            if ($null -ne $jupyterSecret) { $jupyterSecret.Dispose() }
            if ($null -ne $confirmation) { $confirmation.Dispose() }
        }
    }
}

function WriteJsonNew([string]$Target, $Object) {
    $json = $Object | ConvertTo-Json -Depth 12
    $stream = [IO.File]::Open($Target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($json)
        $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true)
    } finally { $stream.Dispose() }
}

$basePython = LocalPath $PythonExecutable $false
$basePythonRoot = Split-Path $basePython -Parent
if ([IO.Path]::GetFileName($basePython) -notin @('python.exe','python3.exe') -or
    (Test-Path -LiteralPath (Join-Path $basePythonRoot 'pyvenv.cfg')) -or
    (Test-Path -LiteralPath (Join-Path (Split-Path $basePythonRoot -Parent) 'pyvenv.cfg'))) {
    throw 'Choose a standalone base Python interpreter, not an existing virtual environment.'
}
$anchorData = LocalPath $AnchorDataDirectory
$source = LocalPath (Split-Path $PSScriptRoot -Parent)
$startup = LocalPath (Join-Path $PSScriptRoot 'install_notebook_startup.ps1') $false
$install = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
if ($install -notmatch '^[A-Za-z]:\\' -or $install -match '[\x00-\x1f"<>|]' -or $install.Substring(2).Contains(':')) { throw 'An explicit local installation path is required.' }
$null = LocalPath (Split-Path $install -Parent)
if (Test-Path -LiteralPath $install) { throw 'Notebook installation directory already exists. Inspect its receipt; setup will not overwrite it.' }
if (Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue) { throw 'Notebook account name is already in use; no existing account will be changed.' }
if (Get-ScheduledTask -TaskName 'AnchorNotebookHost' -ErrorAction SilentlyContinue) { throw 'Notebook startup task already exists; no existing task will be changed.' }
$publicConfig = Join-Path $anchorData 'notebook-runtime.json'
if (Test-Path -LiteralPath $publicConfig) { throw 'Notebook runtime configuration already exists; review it before installing another host.' }
if (-not $NotebookRoot) {
    Add-Type -AssemblyName System.Windows.Forms
    $folder = New-Object Windows.Forms.FolderBrowserDialog
    $folder.Description = 'Choose the project folder whose files notebook code may read and modify. Do not choose a drive or user-profile root.'
    $folder.ShowNewFolderButton = $false
    try {
        if ($folder.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'Notebook setup cancelled; no account was created.' }
        $NotebookRoot = $folder.SelectedPath
    } finally { $folder.Dispose() }
}
$workspace = LocalPath $NotebookRoot
$profileRoot = [Environment]::GetFolderPath('UserProfile')
if ($workspace -eq [IO.Path]::GetPathRoot($workspace).TrimEnd('\') -or $workspace -eq $profileRoot -or
    (Within $install $workspace) -or (Within $workspace $install) -or (Within $source $workspace) -or
    (Within $workspace $source) -or (Within $basePython $workspace) -or (Within $anchorData $workspace)) {
    throw 'Select a project-only workspace, separate from service code, Python, private state and profile roots.'
}
$uri = [Uri]$PublicBaseUrl
if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw 'A credential-free private HTTPS notebook origin is required.' }
$basePythonVersion = (Native $basePython @('-I','-S','-c','"import json, sys; print(json.dumps(sys.version_info[:2]))"')) | ConvertFrom-Json
if ($basePythonVersion.Count -ne 2 -or [int]$basePythonVersion[0] -lt 3 -or ([int]$basePythonVersion[0] -eq 3 -and [int]$basePythonVersion[1] -lt 12)) {
  throw 'Optional notebook installation requires standalone Python 3.12 or newer. Choose a supported interpreter and rerun setup.'
}
$r = $null; $rLibraries = @()
if ($RExecutable) {
    $r = LocalPath $RExecutable $false
    foreach ($library in $RLibraryDirectories) { $rLibraries += LocalPath $library }
    if (-not $rLibraries.Count) { throw 'Explicit R/IRkernel library directories are required.' }
    $rBin = Split-Path $r -Parent
    if ((Split-Path $rBin -Leaf) -eq 'x64') { $rBin = Split-Path $rBin -Parent }
    if ([IO.Path]::GetFileName($r) -ine 'R.exe' -or (Split-Path $rBin -Leaf) -ine 'bin') { throw 'An explicit local R/bin/R.exe layout is required.' }
    $rRoot = LocalPath (Split-Path $rBin -Parent)
    $rPaths = @($rLibraries | ForEach-Object { ConvertTo-Json -InputObject $_ -Compress }) -join ','
    $null = Native $r @('--vanilla','--slave') ('.libPaths(c(' + $rPaths + ')); stopifnot(requireNamespace("IRkernel", quietly=TRUE))')
}
$runtimeTrees = @($basePythonRoot) + $rLibraries
if ($r) { $runtimeTrees += $rRoot }
foreach ($tree in $runtimeTrees) {
    if ($tree.TrimEnd('\') -eq [IO.Path]::GetPathRoot($tree).TrimEnd('\') -or
        (Within $profileRoot $tree) -or (Within $source $tree) -or (Within $anchorData $tree) -or
        (Within $workspace $tree) -or (Within $tree $workspace) -or (Within $install $tree) -or (Within $tree $install)) {
        throw 'Runtime, installation and notebook trees must be separate.'
    }
}
function CheckPrivatePort {
    $serveBefore = (Native $tailscale @('serve','status','--json')) | ConvertFrom-Json
    $tcpProperty = $serveBefore.PSObject.Properties['TCP']
    if ($null -ne $tcpProperty -and $null -ne $tcpProperty.Value -and $tcpProperty.Value.PSObject.Properties.Name -contains "$HttpsPort") {
        throw 'The selected HTTPS port is already configured; it will not be changed.'
    }
}
$tailscale = $null
if ($TailscaleExecutable) {
    $tailscale = LocalPath $TailscaleExecutable $false
    if ($uri.Port -ne $HttpsPort -or $uri.AbsolutePath -ne '/') { throw 'The private Tailscale origin must use the selected HTTPS port and no path prefix.' }
    $tailStatus = (Native $tailscale @('status','--json')) | ConvertFrom-Json
    if ($tailStatus.BackendState -ne 'Running' -or $tailStatus.Self.DNSName.TrimEnd('.') -ine $uri.DnsSafeHost) { throw 'Notebook HTTPS origin does not belong to this running private Tailscale host.' }
    CheckPrivatePort
}
if (Get-NetTCPConnection -State Listen -LocalPort $ListenPort -ErrorAction SilentlyContinue) { throw 'The selected notebook port is occupied; no process will be stopped.' }
# Prepare a clean environment before creating any account or task. -S prevents
# the base interpreter loading user-specific .pth hooks during venv creation.
$null = New-Item -ItemType Directory -Path $install
PrivateAcl $install 'S-1-5-32-544' $true $false
WriteJsonNew (Join-Path $install 'preparation.json') @{schema_version=1;status='runtime_preparation';base_python=$basePython;workspace=$workspace}
$venv = Join-Path $install 'python'
try {
    $null = Native $basePython @('-I','-S','-m','venv',('"' + $venv + '"'))
    $python = LocalPath (Join-Path $venv 'Scripts\python.exe') $false
$null = Native $python @('-I','-m','pip','--isolated','install','--disable-pip-version-check','jupyterlab>=4,<5','jupyter-server>=2,<3','ipykernel>=6,<8') '' 900000
    $null = Native $python @('-I','-c','"import sys,site,pathlib; import jupyterlab,jupyter_server,ipykernel; assert sys.prefix != sys.base_prefix; assert not site.ENABLE_USER_SITE; assert not any(pathlib.Path(p) == pathlib.Path(sys.base_prefix)/''Lib''/''site-packages'' for p in sys.path)"')
    $kernelSpecs = @{python3=@($python,'-m','ipykernel_launcher','-f','{connection_file}')}
    if ($r) { $kernelSpecs.ir = @($r,'--slave','-e','IRkernel::main()','--args','{connection_file}') }
$runtime = @{schema_version=1;enabled=$true;public_base_url=$PublicBaseUrl;root_dir=$workspace;execution_host=[Net.Dns]::GetHostName();local_kernel_specs=$kernelSpecs}
    $validator = LocalPath (Join-Path $source 'notebook_runtime.py') $false
    $null = Native $python @('-I','-c','"import runpy,sys,json; runpy.run_path(sys.argv[1])[''validate_config''](json.loads(sys.stdin.buffer.read().decode(''utf-8'')))"',('"' + $validator + '"')) ($runtime | ConvertTo-Json -Depth 10)
    # Reject executable/path hooks in the newly installed environment before
    # account provisioning, matching the startup installer's fail-closed policy.
    foreach ($pth in Get-ChildItem -LiteralPath (Join-Path $venv 'Lib\site-packages') -Filter '*.pth' -File) {
        if (@(Get-Content -LiteralPath $pth.FullName | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') }).Count) {
            throw 'The clean notebook environment contains an unsupported import-path hook; review it before provisioning.'
        }
    }
} catch {
    Write-Warning 'Clean runtime preparation failed. No account/task was created; the new installation directory is retained for inspection.'
    throw
}
Write-Host 'One-time setup: selected project files will be writable by notebook code. Other project folders are not enrolled.'
Write-Host 'Choose a Jupyter password here, not in chat. Your browser will remember its login subject to normal session expiry.'
$passwordHash = Read-JupyterPasswordHash $python
if (-not $passwordHash.StartsWith('argon2:')) { throw 'Jupyter did not produce its expected password hash.' }
$random = New-Object byte[] 48
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($random) } finally { $rng.Dispose() }
$accountPassword = ('Aa1!' + [Convert]::ToBase64String($random)) | ConvertTo-SecureString -AsPlainText -Force
[Array]::Clear($random,0,$random.Length)
$account = $env:COMPUTERNAME + '\' + $AccountName
$receipt = $null
try {
    $user = New-LocalUser -Name $AccountName -Password $accountPassword -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword -Description 'Anchor notebook runtime; no AI credentials'
    $sid = $user.SID.Value
    $usersGroup = Get-LocalGroup -SID 'S-1-5-32-545'
    Add-LocalGroupMember -Group $usersGroup -Member $user
    PrivateAcl $install $sid $true $false
    $private = Join-Path $install 'private'; $app = Join-Path $install 'app'
    $null = New-Item -ItemType Directory -Path $private,$app
    PrivateAcl $private $sid; PrivateAcl $app $sid $true $false
    $receipt = Join-Path $install 'installation.json'
    WriteJsonNew $receipt @{schema_version=1;status='provisioning';account_sid=$sid;account=$account;workspace=$workspace;task='AnchorNotebookHost'}
    foreach ($module in @('notebook_service.py','notebook_runtime.py')) { Copy-Item -LiteralPath (LocalPath (Join-Path $source $module) $false) -Destination (Join-Path $app $module) }
    # Grant only the selected workspace; preserve all unrelated ACL entries.
    $acl = Get-Acl -LiteralPath $workspace; $acl.AddAccessRule((Rule $sid 'Modify')); Set-Acl -LiteralPath $workspace -AclObject $acl
    # Exact runtime trees only. A direct deny protects against broader inherited
    # write grants; it never grants access to the rest of the owner's profile.
    foreach ($tree in ($runtimeTrees | Select-Object -Unique)) {
        $null = LocalPath $tree
        if ((Within $workspace $tree) -or (Within $tree $workspace)) { throw 'Runtime and notebook trees must be separate.' }
        $acl = Get-Acl -LiteralPath $tree
        $acl.AddAccessRule((Rule $sid 'Write,Delete,DeleteSubdirectoriesAndFiles,ChangePermissions,TakeOwnership' 'Deny'))
        $acl.AddAccessRule((Rule $sid 'ReadAndExecute'))
        Set-Acl -LiteralPath $tree -AclObject $acl
    }
    $passwordFile = Join-Path $private 'password.json'
    WriteJsonNew $passwordFile @{IdentityProvider=@{hashed_password=$passwordHash}}
    PrivateAcl $passwordFile $sid $false $false; $passwordHash=$null
    $serviceOptions = @{runtime_dir=$private;password_file=$passwordFile;service_account=$account;dedicated_account_confirmed=$true;listen_host='127.0.0.1';port=$ListenPort;runtime_paths=@();r_library_dirs=$rLibraries}
    $settings = Join-Path $private 'service-settings.json'
    WriteJsonNew $settings @{runtime=$runtime;service=$serviceOptions}; PrivateAcl $settings $sid $false $false
    $credential = New-Object Management.Automation.PSCredential($account,$accountPassword)
    $taskResult = & $startup -Action Install -PythonExecutable $python -ServiceScript (Join-Path $app 'notebook_service.py') -SettingsFile $settings -Account $account -Credential $credential
    $taskStatus = ($taskResult -join [Environment]::NewLine) | ConvertFrom-Json
    if (-not $taskStatus.ok -or -not $taskStatus.start_requested) {
        $startupError = 'startup_result_invalid'
        if ($taskStatus.PSObject.Properties['error'] -and [string]$taskStatus.error -cmatch '^[a-z][a-z0-9_]{0,127}$') { $startupError = [string]$taskStatus.error }
        WriteJsonNew (Join-Path $install 'startup-failure.json') @{schema_version=1;error=$startupError;status='startup_failed';task='AnchorNotebookHost'}
        throw ('Automatic startup installation failed (' + $startupError + '); notebook links remain disabled.')
    }
    if ($tailscale) {
        CheckPrivatePort
        $null = Native $tailscale @('serve','--bg',"--https=$HttpsPort","http://127.0.0.1:$ListenPort")
    }
    # Do not claim live readiness or expose an enabled link before login/kernel
    # acceptance. A separate verified activation changes this false to true.
    $runtime.enabled = $false
    WriteJsonNew $publicConfig $runtime
    WriteJsonNew (Join-Path $install 'startup-installed.json') @{schema_version=1;status='startup_installed_acceptance_pending';task='AnchorNotebookHost';configuration=$publicConfig;checked_at=[DateTime]::UtcNow.ToString('o')}
    Write-Host 'Automatic notebook startup is installed. Browser login, Python/R execution and recovery verification are still required before enabling Anchor links.'
} catch {
    Write-Warning 'Setup did not finish. Any created account/task/files were retained for explicit recovery; no existing service was stopped. Do not blindly rerun setup.'
    throw
} finally {
    $passwordHash=$null; $credential=$null; $accountPassword.Dispose()
}
