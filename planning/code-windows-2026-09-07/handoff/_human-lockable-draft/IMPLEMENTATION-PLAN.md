# Anchor: code opens where it runs — notebooks in the project's JupyterLab, short code as a notebook, long code in the editor, live links from the register — Implementation Plan (Foreman-ready)

test-command: python -m pytest tests/test_code_windows_2026_09_07.py tests/test_steward_deliverables.py tests/test_reports_links_2026_09_05.py -p no:cacheprovider

**North Star:** # North Star — code opens where it runs (John, 2026-09-07)

> "the jupyter notebooks need to come up every time python or R code is called (at least if the code is
> descriptive/shorter) longer bits of code can have a GUI that runs in a window ... a bit like running in
> something like VS Code"

**Statement.** When Anchor produces or lists Python or R code, one click opens it where it runs: short code
as a Jupyter notebook in the project's own JupyterLab (Python and R kernels), longer code in an editor
window, and notebooks always in JupyterLab — and every such thing is a clickable row in the plan, the
deliverables and the files, like every other report.

## Success criteria (the SURFACE)

1. **A project's own JupyterLab, managed like a preview:** started on demand for a project (cwd = the
   project folder), on an OS-assigned free port that is never 8777, with its own token, registered,
   listed, stoppable, and reaped when dead — the same discipline `preview_server` already has.
2. **A notebook row opens in JupyterLab:** a `.ipynb` in the register, under its step in the plan, or in
   the files tile opens in a new window at the lab's `/lab/tree/<rel>` for that file (starting the lab
   if needed); a stale or dead lab is restarted, never a blank page.
3. **Code rows open where they run:** a `.py` or `.R` row that is short (≤ 120 lines) or marked as a
   notebook (`# %%` cells, or `# notebook` in its first lines) is converted once to a sibling one-cell
   `.ipynb` (nbformat; kernel `python3` or `ir`) and opened in JupyterLab; longer code opens in the
   editor (VS Code on this machine, `code -r <file>`), and the row says which ("notebook" / "editor").
4. **Live links from the register:** a Where cell that is a `http://localhost:<port>/…`,
   `http://127.0.0.1:<port>/…` or `http://<this machine's tailnet name>/…` URL renders as a link
   (new window); every other host stays text (the 2026-09-07 journal 0110 gap — a JupyterLab or Shiny
   address reachable from the register and the plan without a launch page).
5. **Seen on the page before it ships:** on a real project, a `.ipynb` row opens the lab with the file
   selected, a short `.py` opens as a notebook, a long `.py` opens in the editor, and a live-link row
   opens (Playwright screenshots), then the release pipeline.

## Non-goals (parked, named)

- Browser-hosted VS Code (code-server) or remote (iPad) editing — the editor is the local VS Code.
- Running Python or R inside the dashboard's origin; the lab is its own origin on its own port.
- Roar / cluster execution; Shiny app management (a Shiny URL is a live-link row, nothing more).
- Notebook *execution* on open (the user runs cells); nbconvert renders as a fallback are not built.

## Risk taxonomy

- A lab bound on 8777 → hard-guarded `pick_free_port` (existing).
- A lab left running forever → reap-on-dead + a stop control (existing preview discipline).
- A `.py` converted twice or converted over a hand-edited notebook → convert once; never overwrite an
  existing `.ipynb` (open the existing one).
- A live-link row pointing at a hostile host → only localhost / 127.0.0.1 / this machine's tailnet name.

## Foresight brief

The `run:` shell terminal (v1.2.13) and this are the two halves of "a deliverable runs in an Anchor
window": commands in a shell, code in a notebook or editor. The register row is the one place both hang
off; the plan and the files inherit it.


## Success criteria
- A project's own JupyterLab is managed like a preview: started on demand (cwd = the project folder) on an OS-assigned free port that is never 8777, with its own token, registered, listed, stoppable, reaped when dead (the preview_server discipline)
- A .ipynb row (register, plan outline, files tile) opens in a new window at the lab's /lab/tree/<rel> for that file, starting or restarting the lab if needed — never a blank page
- A .py or .R row that is short (<= 120 lines) or marked as a notebook (# %% cells or "# notebook" in its first lines) is converted ONCE to a sibling one-cell .ipynb (nbformat 4 JSON written with stdlib; kernel python3 or ir) and opened in JupyterLab; longer code opens in the local editor (code -r <file>); the row says which (notebook / editor); an existing .ipynb is never overwritten
- A Where cell that is a http://localhost:<port>/…, http://127.0.0.1:<port>/… or http://<this machine's tailnet name>/… URL renders as a link opening in a new window; every other host stays text
- Seen on the page before it ships: on a real project a .ipynb row opens the lab with the file selected, a short .py opens as a notebook, a long .py opens in the editor, a live-link row opens (Playwright screenshots); nets green; then the release pipeline

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W1 — code_open.py: open_kind classifier + one-cell nbformat writer (pure stdlib, no spawn/route/render)

**Intent:** Serves criterion 3. Land the ONE decision every later surface renders and the route executes — what kind of thing a path is — as pure functions proven by fast tests before any process exists. Resolves the Stage-1 HOLDs against the locked North Star: P1.1's marker rule ('# %%' cells or '# notebook' in the first lines opens as a notebook) is criterion 3 verbatim and is KEPT; P1.3's marker_split flag is OMITTED entirely (criterion 3 says a sibling one-cell .ipynb — no split branch, no flag through the route, no second test path). Traversal + convert-once + never-clobber live in the writer's contract here (premortem 3 closed in code).

**Deliverables:** code_open.py (new; stdlib os/io/json/re/tempfile/uuid only): open_kind(path) -> {kind:'lab'|'notebook'|'editor'|'text', reason, lines, marker, kernel}. .ipynb -> 'lab'; .py/.R (case-insensitive) -> stream-count lines stopping at 121 (never read a huge file whole), scan the first 5 non-blank lines for '# notebook' and any line within the 121-line cap for '# %%'; short (<= 120 lines) OR marked -> 'notebook', else 'editor'; kernel 'python3' for .py, 'ir' for .R; any other extension -> 'text'; missing/unreadable -> {kind:'text', reason:'unreadable'}; never raises.; code_open.to_notebook(src_path, kernel, project_folder) -> {ok, ipynb_path, created, reason}: sibling <stem>.ipynb in the same dir; if it already exists return it with created=False and touch no byte; else write nbformat 4 / nbformat_minor 5 JSON (metadata.kernelspec {name:'python3'|'ir', display_name:'Python 3'|'R', language:'python'|'R'}, metadata.language_info {name}, cells = ONE code cell {cell_type:'code', id:uuid4().hex[:8], metadata:{}, source:[lines with trailing \n except last], outputs:[], execution_count:null}) via tempfile in the same dir + os.replace under paths.WRITE_LOCK. Refuses (ok:false, reason:'outside project') when realpath(src) is not inside realpath(project_folder); refuses an unwritable parent rather than writing elsewhere; never follows a symlinked sibling out of the project. NO marker_split parameter. nbformat is never imported.; anchor.py CLI mirror `rnd open-kind <pid> <path>` — prints the open_kind dict; inspection only (never converts, never spawns).; tests/test_code_opens_w0.py (new STUB GATE) + the Foreman gate file tests/test_code_windows_2026_09_07.py extended with the wave's key assertions: open_kind table (119/120/121-line fixtures; '# %%' on line 3 of a 400-line file -> notebook; '# notebook' first line -> notebook; .R -> kernel ir; .txt -> text; missing file -> text/unreadable; never raises); to_notebook writes valid nbformat-4 JSON (json.loads + structural asserts, exactly one code cell); second call returns created=False with identical sha256; a pre-existing hand-written .ipynb is returned untouched (sha256 before/after); outside-project src refused; distro.py import scan stays green.

**Depends on:** —

**done-when:** open_kind and to_notebook pass the boundary table (120 vs 121, marker rules, ir kernel, text, unreadable) and convert-once / never-clobber / outside-project are asserted by sha256 and realpath in green tests, with no nbformat import anywhere in product code.

- **Given** a 121-line .py with no marker and a 120-line .py with no marker, and a 400-line .py whose line 3 is '# %%', **when** open_kind is called on each, **then** the 121-line file is kind 'editor', the 120-line file is kind 'notebook' with kernel python3, and the 400-line marked file is kind 'notebook' with marker '# %%' — no file was read past line 121
- **Given** a short .py inside the project with no sibling .ipynb, **when** to_notebook is called twice with the project folder as the boundary, **then** the first call creates a sibling <stem>.ipynb that json.loads as nbformat 4 with exactly one code cell whose source equals the file's lines, and the second call returns created=False with the file's sha256 unchanged
- **Given** a hand-written <stem>.ipynb already sits beside <stem>.py, and a second .py that lives outside the project folder, **when** to_notebook is called on each, **then** the first returns the existing notebook path with created=False and its bytes are identical before and after; the second returns ok:false reason 'outside project' and no file is written anywhere

## Wave 2 — W2 — live_links.py: the live-link host allowlist (localhost / 127.0.0.1 / this machine's tailnet name)

**Intent:** Serves criterion 4 (the journal-0110 gap). One pure decision — is this Where-cell URL a trusted live link — with strict hostname EQUALITY so a hostile or look-alike host stays text (premortem 2). No render yet; W6 consumes it. No code dependency on W1; ordered after it so the single gate file grows in sequence.

**Deliverables:** live_links.py (new; stdlib socket/subprocess/urllib.parse/json/time/os): allowed_hosts() -> frozenset of lowercased names = {'localhost','127.0.0.1', socket.gethostname().lower()} ∪ names from ANCHOR_TAILNET_NAMES (comma-separated override, e.g. 'gwl-server,gwl-server.tailb49f65.ts.net') ∪ best-effort Self.HostName + Self.DNSName (trailing dot stripped) read through the ANCHOR_TAILSCALE_CMD seam (default `tailscale status --self --json`, 2 s timeout, result cached 10 min, any failure -> empty contribution, never raises). (HOLD — Ship allowed_hosts without ANCHOR_TAILSCALE_CMD. Rebuild the auto-probe only if a live-link row with a real tailnet URL fails to render when ANCHOR_TAILNET_NAMES is unset, or John asks that the host list not be configured.); live_links.is_live_url(text) -> url|None: first http(s):// token in the cell; urllib.parse.urlsplit; scheme in {http,https}; the parsed hostname (post-userinfo, so 'http://localhost@evil.example/' resolves to evil.example) must EQUAL an allowed host exactly (case-insensitive); any port, any path; else None.; tests/fake_tailscale.py — a stub script printing a canned `tailscale status --self --json` document; tests point ANCHOR_TAILSCALE_CMD at it and never at the real binary. (HOLD — W2.1 probe KEEP. Until then do not add tests/fake_tailscale.py.); tests/test_live_links_w0.py (new STUB GATE) + gate-file extension: positive cases (http://localhost:8888/lab, http://127.0.0.1:3838/app, http://gwl-server/x via ANCHOR_TAILNET_NAMES, https, uppercase host, the fake_tailscale DNSName); negative cases (http://evil.example/x, http://localhost.evil.com/, the userinfo trick, ftp://, //protocol-relative, a Where cell with no URL); cache + timeout behaviour with a hanging stub; the seed test 'external URL stays text' remains green.

**Depends on:** W1 — code_open.py: open_kind classifier + one-cell nbformat writer (pure stdlib, no spawn/route/render)

**done-when:** is_live_url returns the URL for every localhost / 127.0.0.1 / configured-tailnet / tailscale-seam host case and None for every hostile, look-alike, userinfo, non-http and URL-less case, with the tailscale seam exercised only through the stub.

- **Given** ANCHOR_TAILNET_NAMES=gwl-server and ANCHOR_TAILSCALE_CMD pointing at tests/fake_tailscale.py, **when** is_live_url is called on 'http://gwl-server/shiny/app', 'http://LOCALHOST:8888/lab' and the DNSName the stub prints, **then** each returns the URL string unchanged (host compared case-insensitively) and the stub was invoked at most once across the calls (cached)
- **Given** the same environment, **when** is_live_url is called on 'http://localhost@evil.example/', 'http://localhost.evil.com/', 'http://evil.example/x' and 'ftp://localhost/x', **then** every call returns None

## Wave 3 — W3 — lab_server.py + tests/fake_lab.py: a project's own JupyterLab, managed like a preview

**Intent:** Serves criterion 1 verbatim (started on demand, cwd = project folder, OS port never 8777, own token, registered, listed, stoppable, reaped when dead). The locked criterion IS option (B) of the Stage-1 HOLD on P2.1/P2.2/P2.4/P2.7 — the North Star answers that one-liner, so the manager is built; the loopback-only bind and the tailnet-reachable bind stay deferred exactly as the plan says. Cloned from preview_server rather than generalised, so the preview path is untouched. fake_lab is what keeps every later gate and the 5 AM healthcheck free of a real jupyter.

**Deliverables:** lab_server.py (new, cloned from preview_server.py): registry .anchor/labs.json — list of {lab_id, project_id, folder, port, token, pid, url, status: running|stopped|dead, started_at, last_probe_ok} written tempfile + os.replace under paths.WRITE_LOCK; imports preview_server.pick_free_port (never copies it); token = secrets.token_hex(24); argv = ANCHOR_LAB_CMD (command-line template, default `jupyter lab`) + `--no-browser --ip=127.0.0.1 --port=<port> --ServerApp.token=<token> --ServerApp.password= --ServerApp.root_dir=<project folder> --ServerApp.allow_remote_access=False --ServerApp.open_browser=False`; cwd = project folder; stdin DEVNULL, output captured; CREATE_NEW_PROCESS_GROUP | paths.NO_WINDOW; env strips ANCHOR_TOKEN; refuses to proceed when port == 8777. (HOLD — John's one-line: (A) wire GET /notebook to the existing jupyter-serve token/URL the friction note named, or (B) build a new per-project lab. Until (B) is ratified, W3.1 and its dependents spend zero.); Public API: start_lab(folder, project_id, health_timeout=20) -> {ok, lab_id, url, port, pid} | {ok:false, reason}; probe_lab(record, timeout=1.5) -> bool via GET http://127.0.0.1:<port>/api/status with `Authorization: token <token>` == 200 (hung socket or 403 under a dead token counts as NOT ok); ensure_lab(folder, project_id) -> record, serialized per project under a module lock: a running record that probes ok is returned; a record whose pid is alive but fails 2 probes is tree-killed (job_runner._tree_kill) and replaced; stop_lab(lab_id) tree-kills + status stopped; list_labs(project_id) reconciles dead pids -> dead; reap_orphans() at boot RE-ADOPTS a record whose pid is alive AND probes ok (port + token reused) and marks the rest dead. (HOLD — Same one-line as W3.1. If (B) is chosen, re-score ensure/probe against never-a-blank-page; the lock still needs a named double-spawn hazard or it stays cut.); Missing jupyter is an honest state: start_lab returns {ok:false, reason:'jupyter not found: <argv0>'} when shutil.which on the seam's executable fails; nothing is installed by Anchor.; tests/fake_lab.py (new; stdlib http.server): parses --port / --ServerApp.token= / --ServerApp.root_dir=; GET /api/status -> 200 {} only when the token header or ?token= matches, else 403; GET /lab/tree/<rel> -> 200 with <title><basename></title>; GET /lab -> 200; FAKE_LAB_HANG=1 accepts the socket and never answers; FAKE_LAB_EXIT=1 exits immediately. (HOLD — W3.1 resolves to KEEP (John picks a new per-project lab). Until then do not add tests/fake_lab.py.); tests/test_lab_server_w1.py (new STUB GATE; ANCHOR_LAB_CMD -> fake_lab.py, temp project folder, temp ANCHOR_DATA_DIR) + gate-file extension: start -> port != 8777 and a registry record; probe ok; ensure_lab twice -> the same lab_id and one process; FAKE_LAB_HANG -> ensure_lab restarts and the old pid is gone; FAKE_LAB_EXIT -> ok:false with a reason and no registry row; stop -> status stopped and pid dead; reap_orphans with an injected dead-pid record -> dead, with an injected alive-and-probing record -> retained running with its port and token; missing executable -> the honest reason; a 8777 port injected into the spawn path is refused. (HOLD — W3.1 KEEP. Until then tests/test_lab_server_w1.py is not earned.)

**Depends on:** W2 — live_links.py: the live-link host allowlist (localhost / 127.0.0.1 / this machine's tailnet name)

**done-when:** Through fake_lab only, start/probe/ensure(idempotent)/hung-restart/never-came-up/stop/reap(re-adopt vs dead)/missing-executable all behave as specified, the port is never 8777, and no real jupyter is spawned by any test.

- **Given** ANCHOR_LAB_CMD points at tests/fake_lab.py and a temp project folder is registered, **when** ensure_lab is called twice for the project within a second, **then** both calls return the same lab_id and port (never 8777), exactly one fake_lab process exists, its cwd is the project folder, and probe_lab answers True with the record's token
- **Given** a running record whose fake_lab was started with FAKE_LAB_HANG=1, **when** ensure_lab is called, **then** the hung pid is tree-killed after two failed probes, a fresh lab starts on a new port, and the registry holds one running record for the project
- **Given** a labs.json containing one record whose pid is dead and one whose fake_lab is alive and probing ok, **when** reap_orphans runs, **then** the dead record's status is 'dead' and the alive record stays 'running' with its original port and token reused

## Wave 4 — W4 — Lab wiring: /api/rnd/labs + lab_stop endpoints, boot reap hook, .ipynb_checkpoints hygiene, healthcheck walk, `rnd labs` CLI

**Intent:** Serves criterion 1's 'listed, stoppable, reaped when dead' at the service boundary and joins the institutional guards (token-auth 401-before-substance, SAFE projections that never leak the lab token or an absolute folder, boot reap in its own fail-open try/except, the 5 AM fully-stubbed walk). Hygiene closes the certain side-effect of a kept lab: JupyterLab mints .ipynb_checkpoints, which must never surface as discovered docs, files rows or register rows, nor dirty git status.

**Deliverables:** anchor_gui.py endpoints (token-authed, 401 before substance): GET /api/rnd/labs?project_id= -> SAFE projection [{lab_id, port, url_public:false, status, started_at}] — never 'token', never the folder path; POST /api/rnd/lab_stop {project_id, lab_id} -> lab_server.stop_lab; 404 on an unknown lab_id without echoing it. (HOLD — Same as W3.1.); Boot hook: lab_server.reap_orphans() beside preview_server.reap_orphans() (anchor_gui.py ~line 22307) in its own try/except, logged, fail-open. (HOLD — Same as W3.1.); project_bootstrap.ensure_git_exclude(folder, name): append-if-absent to <repo>/.git/info/exclude (never a tracked file; the shape of terminal_session._gitignore_in_worktree), idempotent; start_lab calls it for '.ipynb_checkpoints/' best-effort. '.ipynb_checkpoints' added to steward_campaign._LOOK_SKIP_DIRS, the files-tile producer's skip set and brownfield_scan's ignore set.; anchor_healthcheck.check_code_opens_surface(report, ...): walks start_lab -> probe -> ensure_lab idempotence -> stop -> reap through fake_lab only (ANCHOR_LAB_CMD + a temp ANCHOR_DATA_DIR forced then restored; nothing bound on 8777), reporting correctness via report.check and any timing via report.warn; wired into the daily run after check_rnd_v5_surface. (HOLD — W3.1 KEEP, then this walk is earned as the stubbed 5 AM surface.); anchor.py CLI mirror `rnd labs <pid>` -> lab_server.list_labs (reconciles dead -> dead; never spawns). (HOLD — Same as W3.1.); tests/test_lab_wiring_w1b.py (new STUB GATE) + gate-file extension: both endpoints 401 without a token; /api/rnd/labs JSON keys contain no 'token' and no absolute path (assert on keys and on the absence of the temp folder string); lab_stop stops the fake lab; the boot hook runs reap_orphans and a raising reap does not abort boot; ensure_git_exclude is idempotent across two calls; a seeded .ipynb_checkpoints/x-checkpoint.ipynb is absent from discover_efforts/read_deliverables candidates, the files listing and brownfield_scan; check_code_opens_surface called directly with a Report records ok through fake_lab. (HOLD — the catcher did not judge this element — judge it before it is built)

**Depends on:** W3 — lab_server.py + tests/fake_lab.py: a project's own JupyterLab, managed like a preview

**done-when:** The two lab endpoints answer 401-first and a SAFE projection with no token or absolute path, boot reap is wired fail-open, .ipynb_checkpoints never surfaces on any discovery/files/register surface, and the healthcheck walk passes through fake_lab with env restored.

- **Given** a running fake lab registered for a temp project, **when** GET /api/rnd/labs?project_id=<pid>&token=<t> is called, **then** the response lists the lab with lab_id, port, status and started_at, and the serialized body contains neither the lab token nor the project folder path; the same call without the token is 401
- **Given** the project folder contains notebooks/.ipynb_checkpoints/a-checkpoint.ipynb next to notebooks/a.ipynb, **when** discover_efforts, the files-tile producer and brownfield_scan run over the project, **then** a.ipynb appears where it should and the checkpoint copy appears nowhere, and .git/info/exclude contains one '.ipynb_checkpoints/' line after two ensure_git_exclude calls

## Wave 5 — W5 — The one open route: GET /notebook/<pid>?path=&dir= (lab 302 · convert-once · editor page · never-blank interstitial)

**Intent:** Serves criteria 2 and 3 as one server-side decision: classify with W1, guarantee a live lab with W3, then send the browser somewhere never blank. Resolves the Stage-1 HOLDs against the locked criteria: P3.2's dispatch and 127.0.0.1 Location follow from criterion 1 (B) (tailnet/iPad open of the managed lab is parked on the record; live-link rows are the remote path); P3.3/P3.7 — criterion 2 forbids a blank page, and a spinnerless 20 s wait on the dashboard origin IS a blank page, so the interstitial + lab_ready poll ship as the never-blank mechanism (the Skeptic's open finding); P3.5 — `code -r` per the North Star is the primary server-side launcher, the vscode://file href on the tiny page is the browser-side fallback. The lab URL never carries the Anchor token (premortem 2); conversion happens only inside the already-contained realpath (premortem 3).

**Deliverables:** Route GET /notebook/<pid>?path=<rel>[&dir=<effort-rel>]&token=<t> registered beside /artifact in anchor_gui's GET dispatch (token-gated GET transport like the others): 401 before any path resolution, the same 401 for a real and an unknown pid; pid must resolve to a registered project; dir + path joined, realpath'd and contained inside the project's realpath under the classify_route/_unsafe_path_seg rules (no '..', no absolute, no drive, no backslash); a miss is 404 with no echo of the rejected string.; Dispatch on code_open.open_kind: 'lab' -> lab_server.ensure_lab -> 302 Location http://127.0.0.1:<port>/lab/tree/<urllib.parse.quote(rel, safe='/')>?token=<labtoken> with rel relative to the lab root_dir (the project folder); 'notebook' -> code_open.to_notebook(src, kernel, project_folder) -> the same 302 for the sibling .ipynb (created or pre-existing); 'editor' -> the editor page; 'text' -> 302 to the existing /artifact route with the Anchor token (never a dead end). (HOLD — Same one-line as W3.1. If (A), Location is the existing tailnet jupyter-serve URL. If (B), say on the record that iPad/tailnet open is parked and live-link rows are the only remote path.); Never blank: a lab that is up on the first probe 302s directly; otherwise the route answers immediately with a tiny interstitial page (no external script, textContent only: 'Starting <project> lab…') that polls GET /api/rnd/lab_ready?project_id=&path=&dir=&token= every 1 s and sets window.location on {ready:true, location}; on expiry (20 s) or 'jupyter not found' the same page shows the honest reason and a Retry link. lab_ready is token-authed, read-only and SAFE (location is the lab URL only when ready; never the folder; ensure_lab progress is driven by the route's background start, the poll never spawns a second lab). (HOLD — A recorded click that is blank or hung under a blocking 302-after-probe, or W3.1(B) plus a measured cold-lab click that times out in the browser. Until then do not add the poll page or lab_ready.); Editor page: body 'Opening <basename> in the editor' with the absolute path shown; server-side, BEFORE responding, the route fires the ANCHOR_EDITOR_CMD seam best-effort and non-blocking (default `code -r <abs>`; shutil.which('code') gate; Popen with paths.NO_WINDOW, stdin DEVNULL, never waited on); the page then fires vscode://file/<abs path with forward slashes, drive kept> via location.assign after load and offers a plain 'Open in editor again' button. (HOLD — A recorded click where server-side `code -r` did not land and vscode:// would have, or John asks for the URI handler.); Token separation: the Location header is the lab origin + the lab token only; the Anchor token never appears in it; the lab token is never passed through routeHref or written into the page.; tests/fake_editor.py (stub appending its argv to a file) and tests/test_notebook_route_w2.py (new STUB GATE; ANCHOR_LAB_CMD -> fake_lab, ANCHOR_EDITOR_CMD -> fake_editor, temp project registered in a temp data dir) + gate-file extension: 401 enumeration (real vs fake pid identical); '..' / absolute / drive / backslash path -> 404 without echo; .ipynb -> 302 whose parsed Location has host 127.0.0.1, port == the lab port, path == /lab/tree/<quoted rel>, query token == the lab token and != the Anchor token; short .py -> sibling .ipynb exists exactly once after two GETs (sha256 equal) and Location points at the sibling; a pre-existing hand-written sibling is untouched; long .py -> 200 editor page containing 'vscode://file/' and the stub editor invoked exactly once with the absolute path; FAKE_LAB_HANG -> interstitial 200 then lab_ready reports a restarted lab and a location; missing jupyter -> interstitial with the honest reason and no 302; .R -> kernel 'ir' in the written notebook; a .md row -> 302 to /artifact carrying the Anchor token.

**Depends on:** W4 — Lab wiring: /api/rnd/labs + lab_stop endpoints, boot reap hook, .ipynb_checkpoints hygiene, healthcheck walk, `rnd labs` CLI

**done-when:** Every /notebook click resolves to a lab 302 carrying only the lab token, a written-once sibling notebook, an editor page whose `code -r` seam fired, an /artifact fallthrough, or an honest interstitial — never a 5xx, a blank body or a leaked Anchor token — with auth-first and traversal-safe behaviour asserted through fake_lab and fake_editor.

- **Given** a registered temp project holding notebooks/a.ipynb and fake_lab up for it, **when** GET /notebook/<pid>?path=notebooks/a.ipynb&token=<anchor token> is requested, **then** the response is a 302 whose Location parses to host 127.0.0.1, the lab's port, path /lab/tree/notebooks/a.ipynb and a token query equal to the lab token, and the Anchor token appears nowhere in the Location
- **Given** the same project holding short.py (20 lines) and long.py (200 lines), ANCHOR_EDITOR_CMD pointing at fake_editor, **when** /notebook is requested twice for short.py and once for long.py, **then** short.ipynb exists exactly once with identical sha256 after both requests and each response 302s to it; long.py returns a 200 editor page containing 'vscode://file/' and fake_editor's argv log holds exactly one line with long.py's absolute path
- **Given** fake_lab started with FAKE_LAB_HANG=1 for the project, or ANCHOR_LAB_CMD pointing at a non-existent executable, **when** /notebook is requested for a.ipynb, **then** the response is a 200 interstitial (not a 302, not a 5xx); in the hung case a subsequent lab_ready poll reports ready with a location on a fresh lab, and in the missing case lab_ready reports ready:false with reason 'jupyter not found: …'

## Wave 6 — W6 — Every surface inherits: read_deliverables url + open_kind, delivRow live-link branch + /notebook rewrite + mode chip, plan-step rows, files tile, where_for(url=)

**Intent:** Serves criteria 2, 3 and 4 on the SURFACE: a code thing is a clickable row wherever it appears (register, under its plan step, files tile) and a live address in the register is a link. The parser and the ONE row renderer are the two places the plan already inherits from; the files tile is routed through the same decision. where_for accepting an allowed absolute URL retires the RUN-<thing>.html launch-page workaround from journal 0110.

**Deliverables:** steward_campaign.read_deliverables: each item gains url (live_links.is_live_url on the Where cell, parsed BEFORE the backtick/route branch; set only for an allowed host — every other http(s) cell keeps route:null/openable:false; a cell carrying both a path and a URL keeps the path as the open target) and open_kind (code_open.open_kind on the resolved contained path, or on the rel of a classified /artifact route, ONLY for .ipynb/.py/.R — the key is absent otherwise so non-code rows' JSON shape is unchanged).; steward_cockpit/static/shared.js delivRow: new first branch if (it.url) -> an <a href=it.url target=_blank rel='noopener noreferrer'> whose textContent is '• ' + what, built from the parsed url only (never innerHTML) and NEVER passed through routeHref; then, for it.route/it.path whose rel ends in .ipynb/.py/.R (case-insensitive) with it.open_kind present, the href becomes /notebook/<pid>?path=<rel>&dir=<dir> with the page token appended routeHref-style, target=_blank; a mode chip <span class='okind'> reading 'notebook' / 'editor' / 'lab' (textContent from it.open_kind.kind) after the link. stepDelivLine unchanged (it calls delivRow) — a test proves the plan-step detail row carries the same href and chip.; Files tile: shared.js openProducedFile/renderFiles and cockpit.html renderFiles open a produced .ipynb/.py/.R via window.open of the /notebook route (dir='' — project-relative path) instead of the report viewer, and show the same chip when the files payload carries open_kind; the files endpoint adds open_kind for those three extensions only (a <=121-line read per row; no model, no spawn).; deliverables_register.where_for gains url=: returns the URL verbatim when live_links.is_live_url accepts it; a disallowed host returns '' and register() no-ops journaling {register: 'host not allowed'} (a hook never mints a hostile row). The header-contract docstring and steward_engine's row grammar text (~line 158) name the URL form.; tests/test_code_surfaces_w3.py (new STUB GATE) + gate-file extension: read_deliverables fixtures — 'http://localhost:8888/lab/tree/a.ipynb' -> url set; 'http://gwl-server/shiny/app' with ANCHOR_TAILNET_NAMES=gwl-server -> url set; 'http://evil.example/x' and 'http://localhost.evil.com/' -> url None, openable False (the seed test stays green); an in-effort .py row -> open_kind present with kind; a .md row -> no open_kind key; JS asserted textually the way test_reports_links_2026_09_05 does (the delivRow slice contains the url branch, rel='noopener noreferrer', never routeHref(it.url), the /notebook rewrite and the okind chip; openProducedFile and cockpit.html renderFiles contain the /notebook window.open); the stepDelivLine path yields the same href + chip; where_for(url=allowed) verbatim, where_for(url=hostile) ''; register() with a hostile URL journals the no-op; tests/test_reports_links_2026_09_05.py, test_steward_deliverables.py and test_files_tile_2026_09_05.py remain green.

**Depends on:** W5 — The one open route: GET /notebook/<pid>?path=&dir= (lab 302 · convert-once · editor page · never-blank interstitial)

**done-when:** A register/plan-step/files row for a .ipynb/.py/.R links to /notebook with its mode chip, an allowed-host Where cell renders as a noopener new-window link without any Anchor token, a hostile-host cell stays text on every surface and cannot be registered by a hook, and all pre-existing register/files tests stay green.

- **Given** a DELIVERABLES.md with rows for notebooks/a.ipynb, code/short.py, code/long.py, http://localhost:8888/lab and http://evil.example/lab, **when** read_deliverables parses it and delivRow/stepDelivLine render the items, **then** the three code rows carry a /notebook href with the page token and chips 'lab', 'notebook', 'editor'; the localhost row is an <a target=_blank rel='noopener noreferrer'> whose href is exactly the cell URL with no token; the evil.example row is plain text with openable False
- **Given** a campaign hook calling deliverables_register.register with where_for(url='http://gwl-server/shiny/app') under ANCHOR_TAILNET_NAMES=gwl-server, then again with url='http://evil.example/app', **when** both register calls run, **then** the first writes a row whose Where cell is the URL verbatim; the second writes nothing and the journal carries the reason 'host not allowed'

## Wave 7 — W7 — Lab chip + stop control in the project window, CLAUDE.md surface documentation

**Intent:** Serves criterion 1's 'listed, stoppable' as the operator-visible surface (the only place a running lab is seen and stopped from the UI — the left-running-forever hazard the preview discipline names) and the repo's documented step 5 (CLAUDE.md currency) so the next session inherits the routes, files and the jupyter host prerequisite. Resolves the P4.5 HOLD by criterion 1 (B). Read-only render — never a spawn on page load.

**Deliverables:** Project window lifecycle header: a 'Lab' chip rendered off lab_server.list_labs(pid) — running: green with the port and a 'stop' control POSTing /api/rnd/lab_stop (via _postJson, token-aware); none: grey 'no lab'; jupyter absent (one shutil.which on the seam's executable per render, cached briefly): an honest 'jupyter not installed' chip. CSS .labchip / .labchip-running / .labchip-none / .labchip-missing; the JS lives in the raw _PROJECT_WINDOW_JS string (single braces). (HOLD — W3.1(B), or unpark friction item 3 and put health on the existing jupyter-serve in attention.json rather than a new chip.); CLAUDE.md: API rows for GET /notebook/<pid>, GET /api/rnd/labs, POST /api/rnd/lab_stop, GET /api/rnd/lab_ready; file-structure lines for lab_server.py, code_open.py, live_links.py, tests/fake_lab.py; the jupyter host-prerequisite note beside the pywinpty exception (Anchor never installs it; a missing jupyter is an honest reason on the click); CLI mirror lines for `rnd open-kind` and `rnd labs`.; tests/test_lab_chip_w3b.py (new STUB GATE) + gate-file extension: the chip renders each of the three states from injected registry records / a forced missing executable without spawning (no fake_lab process created during render); the stop control's POST target is /api/rnd/lab_stop; a textual assertion that CLAUDE.md names the four routes and the three modules. (HOLD — W7.1 KEEP. Until then tests/test_lab_chip_w3b.py is not earned.)

**Depends on:** W6 — Every surface inherits: read_deliverables url + open_kind, delivRow live-link branch + /notebook rewrite + mode chip, plan-step rows, files tile, where_for(url=)

**done-when:** The project window shows the Lab chip in the running / no-lab / jupyter-missing states from registry data alone, its stop control stops the lab through /api/rnd/lab_stop, and CLAUDE.md documents the routes, modules, CLI mirrors and the jupyter prerequisite.

- **Given** labs.json holds a running fake lab for the project, **when** GET /project/<pid> renders and the chip's stop control is clicked, **then** the header shows a green Lab chip with the lab's port, no new process was spawned by the render, and after the click list_labs reports the lab stopped and the chip re-renders grey 'no lab'

## Wave 8 — W8 — Seen on the page: real-project Playwright sign-off, full gate, deploy + live verify, release v1.2.16, docs closed

**Intent:** Serves criterion 5 (the v4 lesson made law): a UI wave is not done until Playwright opens it on a real project and screenshots are kept. This is the ONLY wave that spawns a real JupyterLab and a real editor; everything before it is gated through fake_lab / stub seams. The Skeptic's open finding on the live-link fixture is honoured: the fixture row names an address that is actually up during the sign-off and the test NAVIGATES it, so the row is proven reachable, not merely painted. Then the release pipeline stamps and bundles, and the two records that motivated the effort are closed.

**Deliverables:** Sign-off fixture on THIS repo's effort dir planning/code-windows-2026-09-07/: a DELIVERABLES.md with rows for a committed tiny hand-written signoff/hello.ipynb, a short signoff/short.py (~20 lines, no marker), a long signoff/long.py (~200 lines, no marker), a signoff/hello.R row (kernels python3 and ir are both installed on PUTER per the baseline inventory), and a live-link row whose URL is up during the pass (the existing tailnet JupyterLab https://gwl-server.tailb49f65.ts.net:8446/lab via ANCHOR_TAILNET_NAMES, or the running managed lab's URL written by the sign-off itself — never a guessed port).; tests/test_code_opens_signoff_w4.py (Playwright, dev-only via pytest.importorskip, against the live :8777 with the page token): (a) click the .ipynb row -> the popup URL contains /lab/tree/signoff/hello.ipynb and after load the JupyterLab document title contains the file name -> signoff/01-ipynb-in-lab.png; (b) click the short .py row -> signoff/short.ipynb exists exactly once, a second click leaves its sha256 unchanged, the popup lands in the lab with the file selected -> 02-short-py-notebook.png; (c) the long .py row reads 'editor', its page fires an href starting vscode://file/ (captured from the navigation request) and the `code -r` seam ran (VS Code has the file open — eyes-on, recorded as such) -> 03-long-py-editor.png; (d) the live-link row is an <a> whose href has no token= and rel contains noopener, AND the popup navigates to it and reaches a 200 page -> 04-live-link.png; (e) the Lab chip shows running with the port and its stop control stops the lab (list_labs -> stopped) -> 05-lab-chip-stop.png; (f) the .R row opens a notebook whose kernelspec is ir -> 06-r-notebook.png. Screenshots kept under planning/code-windows-2026-09-07/signoff/ and named in EXECUTION-LOG.; Gate before the pass: the full pytest suite green (W1–W7 STUB GATE files plus the existing suite), distro.py import scan green (no nbformat/jupyter import in product code), anchor_healthcheck.py run on demand green with check_code_opens_surface reporting through fake_lab; both results pasted verbatim into EXECUTION-LOG (a red is reported red, never forced green).; Deploy + verify: merge to master, restart_anchor.ps1 (warm), live-verify GET /notebook/<pid>?path=x returns 401 without a token (route present, auth-first) and the Lab chip renders on a project window; rescan the project.; Release: python tools/release.py -> v1.2.16 with a changelog entry naming the four behaviours (lab manager, /notebook route, code rows open where they run, live-link Where cells) and the jupyter host prerequisite; the clone-verify step (the v1.2.14 lesson) confirms lab_server.py, code_open.py, live_links.py and tests/fake_lab.py are in the bundle manifest.; Docs closed: CLAUDE.md's 'Live code opens live' note updated from proposed to built with the route names; docs/friction/2026-09-07-live-notebooks-from-the-register.md gains a one-line resolution pointer to this effort and v1.2.16.

**Depends on:** W7 — Lab chip + stop control in the project window, CLAUDE.md surface documentation

**done-when:** On the live service the six sign-off clicks are seen and screenshotted (ipynb in the lab with the file selected, short .py written once and opened as a notebook, long .py in the editor, live link reached, Lab chip stops the lab, .R as an ir notebook), the full suite + distro scan + healthcheck are green and pasted verbatim, master is deployed and 401-verified, v1.2.16 is released with the four files in the bundle, and both records are updated.

- **Given** the live :8777 service running the merged code, the effort's DELIVERABLES.md fixture, and no lab running for the Anchor project, **when** the Playwright sign-off clicks the hello.ipynb row, **then** a popup opens whose URL contains /lab/tree/signoff/hello.ipynb on a 127.0.0.1 port that is not 8777, its document title contains 'hello.ipynb', the Lab chip turns green with that port, and 01-ipynb-in-lab.png is written
- **Given** the same session, **when** the short.py row is clicked twice and then the long.py row once, **then** signoff/short.ipynb exists exactly once with an unchanged sha256 between clicks and opened in the lab; the long.py row's chip reads 'editor', its page fired a vscode://file/ href, the `code -r` seam ran, and 02 and 03 screenshots are written
- **Given** the release step, **when** python tools/release.py runs and the clone-verify checks the bundle, **then** the version is v1.2.16, the changelog names the four behaviours and the jupyter prerequisite, and lab_server.py, code_open.py, live_links.py and tests/fake_lab.py are present in the bundle manifest

## Property gates (hardening law — crucible journal 0080)

### idempotence — asserted by this plan
_idempotence is only real if something re-invokes and asserts no change_

- [ ] a repeat-invocation test

### boundedness — asserted by this plan
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- [ ] the numeric bound named in the plan
- [ ] a refusal path when the bound is exceeded

### containment — asserted by this plan
_containment is asserted far more often than it is exercised_

- [ ] an escape-attempt test (.., absolute path, symlink)

A property named in the plan and absent from this list is a BLOCKER:
the plan is claiming a guarantee nothing enforces.

## Hardening-gate obligations (mechanical — journal 0080)

This section is the **emitted** property-gate checklist. A claim in the plan without a matching obligation below is a BLOCKER.

### Property `idempotence`
_idempotence is only real if something re-invokes and asserts no change_

- **Gate:** a repeat-invocation test

### Property `boundedness`
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- **Gate:** the numeric bound named in the plan
- **Gate:** a refusal path when the bound is exceeded

### Property `containment`
_containment is asserted far more often than it is exercised_

- **Gate:** an escape-attempt test (.., absolute path, symlink)

### Storage mechanism vocabulary (required when durability is claimed)

- **atomic write** via **temp** + **fsync** + **rename** for snapshot (and durable JSON) paths
- cross-process **lock** or documented **serialization** around multi-writer index paths
- a **concurrency test** (two real processes; assert no event/receipt dropped)
- where "exactly once" / identity is claimed: a **repeat-invocation test**
- where containment is claimed: an **escape-attempt** test (`..`, absolute path, symlink/junction)
- where bounds are claimed: the **numeric bound** named (e.g. 10000 rows / 50000 events) and a **refusal** path when exceeded

### Failure-state table vocabulary (required when addsSurface)

Every surface-bearing wave answers these **five** states with named status code AND user-visible text.
**unknown** and **empty** are SEPARATE rows (never collapsed).

- **dependency-missing** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **dependency-slow-or-killed** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **dependency-returns-garbage** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **backing-store-unreadable** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **empty-but-valid** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)

See also wave-local failure tables (hardening-gate 0080 format) and generated red stubs.

