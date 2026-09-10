# Same-host notebook setup for Anchor

This guide configures the Jupyter adapter in `notebook_service.py`. The server and
its Python/R kernels run on the computer running Anchor; a tablet or another
computer supplies only the browser. See [Notebook work products](notebook-work-products.md)
for producing, registering, and preserving notebook deliverables.

Windows has a one-time interactive setup entrypoint,
`tools/setup_notebooks.ps1`, and a separate startup installer,
`tools/install_notebook_startup.ps1`. Setup requires administrator confirmation;
daily use does not. The setup wizard creates a dedicated account and clean Python
environment, protects service files, and registers automatic background startup.
An optional Tailscale Serve route uses a new private HTTPS port, without changing
existing routes or enabling Funnel. Other private HTTPS proxies remain an
explicit deployment choice.

Setup is not a readiness certificate: Anchor links stay disabled until the
browser and kernel acceptance checks below pass. This source addition does not
mean a particular computer has been installed or reboot-tested. The underlying
`notebook_service.py` remains a foreground entrypoint, with a read-only Python
`build_launch_plan(runtime_config, service_options)` API.

This is a trusted, single-user notebook workspace, not a multi-tenant service.
People sharing its login share its filesystem and execution authority. `root_dir`
controls notebook navigation; it is **not an OS sandbox**. Notebook code can use
the permissions of the Windows service account outside that directory. Separate
untrusted users require a different deployment architecture.

## 1. Make the installation choices

### One-time Windows wizard

The optional Windows notebook wizard requires standalone Python 3.12 or newer.
Core Anchor's Python requirements are unchanged. Active `.pth` import hooks
remain unsupported and are rejected during setup.

From an administrator PowerShell session, run the shipped setup script with your
own installation values. This example is not a command to copy unchanged:

```powershell
.\tools\setup_notebooks.ps1 -PythonExecutable 'C:\Apps\Python313\python.exe' -AnchorDataDirectory 'C:\AnchorData' -PublicBaseUrl 'https://YOUR-PRIVATE-HOST:8448/' -TailscaleExecutable 'C:\Program Files\Tailscale\tailscale.exe'
```

Choose the project-only notebook folder in the local folder dialog and enter a
Jupyter password only in the secure local prompt. Optional `-RExecutable` and
`-RLibraryDirectories` enroll an existing R/IRkernel installation. Setup creates
a clean venv from the supplied standalone base Python; it does not reuse its
site-packages, editable project imports, AI credentials, or user profiles. It
downloads notebook dependencies once. No package installation occurs when
opening a notebook. Existing accounts, tasks, runtime configurations and install
directories are never silently overwritten. Failed preparation is retained for
inspection; do not blindly rerun or delete a user's existing installation.

The initial pip dependency installation allows up to 15 minutes for a cold
download. Wait for completion or a reported failure before attempting recovery.

After a preparation failure, inspect `preparation.json` in the selected software
installation folder. Confirm that this attempt created that folder and that no
dedicated account, startup task, or public runtime configuration exists. Only
under those conditions, rename that exact software installation folder to a
sibling named `<install-folder>-failed-<timestamp>`, then rerun the corrected
setup with the same intended configuration and original installation path.
Never rename or delete the notebook/data folder. Existing state is not
automatically adopted.

The startup task uses the dedicated standard account, runs at boot without an
interactive login, suppresses duplicate instances and has no session-duration
cutoff. Its credential is passed in memory to Windows Task Scheduler, not stored
in script arguments or public configuration. Installation requests startup;
actual readiness and reboot recovery must still be verified.

For an already provisioned deployment, the separate startup installer supports
`-Action Plan` and `-Action Status`. Plan generates credential-free task XML
without registration or startup; account/ACL checks are explicitly deferred to
Install. Status reports task state, not kernel health. Both use the same required
path/account parameters as Install. The manual sections below remain useful for
reviewing or provisioning those choices individually.

Choose these values for each installation; do not copy another person's working
settings, account profile, credentials, or project files.

| Choice | Requirement |
| --- | --- |
| Windows account | A dedicated standard account, identified as `COMPUTER\account` or `DOMAIN\account`; not an administrator or a shared built-in service identity. |
| Anchor code and Python environment | Local fixed-disk locations readable/executable by the notebook account, but not writable by that account or notebook users. |
| R installation and libraries | Optional local R executable and approved libraries, also protected from notebook modification. |
| Notebook tree | A deliberately selected local directory containing only the material this workspace may access. Grant the account only the necessary read/modify permissions. |
| Private service state | An existing private local directory outside the notebook tree, including its password file; no junctions, symlinks, mapped drives, or shared-storage paths. |
| Listen address and port | A literal loopback address such as `127.0.0.1` and one fixed available port. No automatic port changes. |
| Browser origin | A separate token-free HTTPS origin on the same host, reachable only by the intended clients through the chosen private access mechanism. |

An OS administrator should provision the account and permissions explicitly.
Keep its membership out of Administrators: running an administrator account with
UAC unelevated is still rejected. Leave the existing Anchor/Jupyter services alone
while preparing this separate deployment.

In Windows folder **Properties → Security → Advanced**, give the private service
directory a restricted owner/DACL allowing the dedicated account, SYSTEM, and
Administrators only. Remove inherited broad grants rather than adding an Allow
rule on top of them. Apply suitable inheritance to its new files/subdirectories.
The adapter verifies permissions; it does not silently repair an existing public
directory. The account must be able to create its runtime files there.

The notebook tree's permissions are a separate decision. Give the notebook
account Modify only where saving notebooks, outputs, and working files requires
it. Do not grant it Modify over Anchor's code, the Python environment, R program
files, the HTTPS proxy configuration, or unrelated user profiles. Do not copy AI
CLI credentials into the dedicated account or its service state.

## 2. Prepare Python and optional R

Use an administrator-controlled Python environment containing JupyterLab, a
compatible Jupyter Server 2.x, and ipykernel. Install dependencies as an explicit
setup operation; clicking a deliverable never installs packages. Confirm that
the dedicated account can run that exact Python executable and import the
packages before creating the startup task.

For R, install IRkernel and its dependencies into an approved R library readable
by the dedicated account. Test this using that account and the exact R executable
and library directories you will configure. See the [IRkernel installation guide](https://irkernel.github.io/installation/).
This adapter writes its own isolated `ir` kernelspec from the explicit argv below;
another person's `IRkernel::installspec()` registration is not used as proof that
the service account can run R.

The adapter allows only the configured `python3` and `ir` kernels. It excludes
inherited Jupyter configuration/gateway settings, external kernels, and remote
provisioners. Its generated specs explicitly select the local provisioner.
Inherited AI credentials, arbitrary PATH entries, Python user-site configuration,
and R startup profiles are not forwarded. Any required executable directories or
R libraries must therefore be configured explicitly.

## 3. Create the Jupyter password privately

Use Jupyter's own password prompt under the dedicated account. Do not send the
password to an AI chat, place it in a command argument, paste it into a notebook,
or add it to Anchor's configuration. Jupyter writes a password hash to its JSON
file; protect that file as private authentication material too.

The following is a **manual example**, using replacement installation paths. First
create `C:\ProgramData\AnchorNotebook\password-setup` with the private permissions
described above. In a one-purpose PowerShell session running as the dedicated
account:

```powershell
$env:JUPYTER_CONFIG_DIR = 'C:\ProgramData\AnchorNotebook\password-setup'
& 'C:\Apps\AnchorPython\Scripts\python.exe' -m jupyter server password
```

Type and confirm the password only in Jupyter's prompt. Close that one-purpose
shell afterward so the temporary configuration-directory setting is not reused
accidentally. The expected output file is
`C:\ProgramData\AnchorNotebook\password-setup\jupyter_server_config.json`.
Do not print or publish its contents.

The adapter accepts the Argon2 hash produced by modern Jupyter under
`IdentityProvider.hashed_password` or `PasswordIdentityProvider.hashed_password`.
It rejects plaintext, conflicting hashes, and obsolete weak-hash examples. Its
running server uses password authentication with token login disabled, not an
authentication-free server. [Jupyter password setup](https://jupyter-server.readthedocs.io/en/latest/operators/public-server.html#automatic-password-setup)
and [Jupyter's password writer](https://github.com/jupyter-server/jupyter_server/blob/main/jupyter_server/auth/security.py)
describe the upstream mechanism.

## 4. Write the local configuration

All paths and names below are examples to replace. Paths must already exist;
executables must be the actual local installations. Replace `LOCAL_HOSTNAME` with
the output of `socket.gethostname()` from Python on the Anchor host, not the
browser's hostname or the notebook HTTPS DNS name. The service account value
must match the dedicated account actually running the process.

### Private service settings

Save a private `service-settings.json` in the service state directory. The top
level has exactly `runtime` and `service`; service-only settings do not belong in
the runtime object.

```json
{
  "runtime": {
    "schema_version": 1,
    "enabled": true,
    "public_base_url": "https://notebooks.example.test/",
    "root_dir": "C:\\NotebookWork",
    "execution_host": "LOCAL_HOSTNAME",
    "local_kernel_specs": {
      "python3": [
        "C:\\Apps\\AnchorPython\\Scripts\\python.exe",
        "-m", "ipykernel_launcher", "-f", "{connection_file}"
      ],
      "ir": [
        "C:\\Apps\\R\\bin\\R.exe",
        "--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"
      ]
    }
  },
  "service": {
    "runtime_dir": "C:\\ProgramData\\AnchorNotebook",
    "password_file": "C:\\ProgramData\\AnchorNotebook\\password-setup\\jupyter_server_config.json",
    "service_account": "LOCAL_HOSTNAME\\NotebookRunner",
    "dedicated_account_confirmed": true,
    "listen_host": "127.0.0.1",
    "port": 8891,
    "runtime_paths": [],
    "r_library_dirs": ["C:\\Apps\\AnchorRLibrary"]
  }
}
```

For Python-only setup, remove the `ir` entry and omit `r_library_dirs`. Add to
`runtime_paths` only specific existing local executable directories required by
your runtime; do not paste the interactive account's entire PATH. The service
creates isolated configuration, data, kernel, temporary, profile, and JupyterLab
state directories below `runtime_dir`. Changed managed kernelspec files cause a
conflict instead of being overwritten silently.

### Anchor's non-secret runtime configuration

Anchor separately reads `notebook-runtime.json` in its active data directory (the directory returned by `paths.data_dir()`). If
the installation uses a configured Anchor data directory, use that active data
directory rather than creating a second copy elsewhere. This file is only the
runtime object—not the surrounding `runtime`/`service` document:

```json
{
  "schema_version": 1,
  "enabled": true,
  "public_base_url": "https://notebooks.example.test/",
  "root_dir": "C:\\NotebookWork",
  "execution_host": "LOCAL_HOSTNAME",
  "local_kernel_specs": {
    "python3": [
      "C:\\Apps\\AnchorPython\\Scripts\\python.exe",
      "-m", "ipykernel_launcher", "-f", "{connection_file}"
    ],
    "ir": [
      "C:\\Apps\\R\\bin\\R.exe",
      "--slave", "-e", "IRkernel::main()", "--args", "{connection_file}"
    ]
  }
}
```

Keep these runtime values consistent with the service settings. The Anchor file
must contain no password/hash, authentication token, service-account credential,
or token-bearing URL. “Non-secret” does not mean that actual installation paths
and hostnames should be included in a distributable template.

Keep Anchor's `enabled` false during provisioning. After the service and private
HTTPS route pass their initial checks, enable it deliberately for the controlled
Anchor/browser acceptance test below; disable it again if a gate fails. Normal
availability follows the complete acceptance test. The private service's runtime
must be enabled to start it for testing. For normal remote/tablet use, use HTTPS; the
`allow_loopback_dev` exception is only for deliberate local development and is
not an iPad deployment shortcut.

## 5. Start once in the foreground

Run the exact entrypoint under the dedicated account, with isolated Python:

```powershell
& 'C:\Apps\AnchorPython\Scripts\python.exe' -I 'C:\Apps\Anchor\notebook_service.py' --settings 'C:\ProgramData\AnchorNotebook\service-settings.json'
```

This starts the service; it is not a dry run. Use the protected Anchor code
directory as the working directory, not a notebook/project directory. The module
must be present beside its Anchor helper modules. Missing dependencies, wrong
account, unsafe permissions, nonlocal kernel settings, or an occupied fixed port
are deployment failures to fix explicitly.

The adapter owns a runtime lock and does not adopt another server because a PID
or port happens to match. It does not kill a process occupying the selected port
and does not move to another port. If an existing Jupyter service is in use,
preserve it and choose a distinct validated runtime/port for this deployment.

## 6. Provide the private HTTPS route

Configure an administrator-controlled HTTPS proxy on the Anchor host to forward
the chosen notebook origin to `http://127.0.0.1:8891` (or your selected loopback
endpoint). Restrict the origin to the intended authenticated/private-access
clients. Do not bind raw Jupyter HTTP to a LAN/public interface, open its loopback
port in the firewall, or publish a token-bearing launch URL.

The proxy must support WebSocket upgrades and preserve the browser's notebook
host and base path. The service does not trust client-supplied forwarded headers;
secure cookies follow the explicit HTTPS public URL. Keep the configured public
base URL and any proxy path prefix aligned. Restrict access to the proxy through
the chosen private interface/access policy; this guide does not install that
policy or assume an existing tunnel is secure. Verify a trusted certificate on
the actual tablet/browser—do not normalize certificate warnings as success.

Anchor authorizes the notebook launch request and redirects to the exact
token-free JupyterLab tab. It does not convert Anchor login into a Jupyter login,
share Anchor/model credentials with Jupyter, or reverse-proxy notebook code
execution. The browser must satisfy Jupyter's own password/cookie authentication.
Do not disable Jupyter authentication, origin checks, or XSRF protection to make
the route work. [Jupyter Server configuration](https://jupyter-server.readthedocs.io/en/latest/other/full-config.html)
documents the upstream security and connection options.

## 7. Install startup using Windows' administrative workflow

After the foreground smoke test passes, stop that **new, owned foreground
instance** before enabling automatic startup. In Task Scheduler, an administrator
can create a specifically named task for this deployment:

1. On **General**, select the dedicated standard account. Leave **Run with highest
   privileges** unchecked. Choose the appropriate logged-out/background option
   for the installation.
2. Let Windows request any required credentials through its own secure UI. Do not
   put a password in scripts, task arguments, JSON, AI chat, or a plaintext
   `schtasks` command. Account creation and task credential entry are explicit
   administrator/user actions, not performed by this guide or adapter.
3. Add an **At startup** trigger. Ensure the notebook account has the applicable
   batch-logon right and that local storage is available at startup.
4. Add one action with **Program/script**
   `C:\Apps\AnchorPython\Scripts\python.exe`, replacing it with the selected
   protected Python executable.
5. Set **Arguments** to
   `-I "C:\Apps\Anchor\notebook_service.py" --settings "C:\ProgramData\AnchorNotebook\service-settings.json"`.
   Set **Start in** to `C:\Apps\Anchor`. Do not add a shell wrapper, visible
   terminal, browser launcher, or notebook execution command.
6. Configure **If the task is already running: Do not start a new instance**.
   Remove an automatic duration limit that would stop an intentionally persistent
   server. Do not add an aggressive retry loop that hides a configuration failure.
7. Start the task once and inspect its result/history. Recheck the process account,
   runtime ownership, fixed loopback listener, HTTPS route, and kernel tests.

This is a manual installation procedure, not a claim that a task is already
installed. Windows' [task security context](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks)
controls which credentials and privileges the scheduled process receives.

## 8. Acceptance checks before enabling normal use

Use a synthetic instructional example, not a private project, for the first
acceptance run. Record evidence privately; do not ship outputs containing actual
hostnames, account identities, installation paths, cookies, or runtime IDs.

1. Open the producing plan step, Deliverables entry, and Files entry in an
   authenticated Anchor session. Each notebook action must reach the intended
   `.ipynb` tab through Anchor's authorized route—not a directory listing, static
   rendering, source download, or unrelated previous tab. The URL must not contain
   a token. Opening a product must not run its cells automatically.
2. In a fresh browser session, complete Jupyter's own login. Verify that the exact
   tab survives refresh/reconnection and that its kernel WebSocket connection
   works over WSS. Repeat after signing out/session renewal, not only with an
   already authenticated development browser.
3. Deliberately run this diagnostic cell in a Python notebook:

   ```python
   import os
   import socket
   import sys
   {"execution_host": socket.gethostname(), "pid": os.getpid(), "python": sys.executable}
   ```

4. If R is enabled, deliberately run this cell in an R notebook:

   ```r
   list(execution_host = Sys.info()[["nodename"]], pid = Sys.getpid(), r_home = R.home())
   ```

5. On the Anchor host, verify that each returned PID is a current local process
   using the expected runtime and dedicated account. Compare the reported host
   with the actual Anchor computer. A local Jupyter URL alone is not proof of a
   local kernel; both the explicit local kernelspec and observed execution count.
6. Repeat from the iPad or other intended remote browser. No Python/R installation
   on that client should be needed. Confirm that the displayed computation still
   comes from the Anchor host, not another kernel gateway or a client-side runtime.
7. Save a harmless notebook edit and verify that reopening preserves it. For
   worktree-produced products, confirm that the source, notebook, companion, and
   single MAIN register row are all durable before completing/reaping the worktree.
8. Reboot the Anchor host during a safe maintenance window. Verify startup without
   the setup user logged in, Jupyter reauthentication as needed, the exact tab,
   WSS, and both local kernel checks again. A successful manual launch is not a
   reboot-persistence test.

Leave the Anchor-side runtime enabled for normal use only after these checks
pass. Notebook availability and AI model selection are separate concerns: the notebook configuration contains
no model names, and AI provider/model policy remains in Anchor's model settings.

## Rollback and collaborator packaging

Disable Anchor's notebook runtime if the launch path is not ready. Disable the
new task/proxy route by their exact configured identities, and stop only the
instance owned by that deployment. Do not identify a process for termination
solely from a port or an old PID. Preserve any pre-existing Jupyter service and
launch pages until the replacement has been verified.

Keep sources, notebooks, companions, DELIVERABLES.md, and pending recovery records.
Do not delete a worktree while notebook completion verification fails. Inspect
and resolve the recorded conflict; do not overwrite an edited MAIN notebook to
force the gate through. A password change uses Jupyter's own prompt again and a
controlled restart of the owned service.

Distribute only generic Anchor/skill code, this guide, and sanitized examples.
Exclude active data settings, private service state/password files, task exports
containing local deployment details, credentials, journals, recovery receipts,
and project-specific materials. A collaborator must make their own account,
directory, runtime, HTTPS, password, and startup choices and pass the same
clean-profile acceptance checks.
