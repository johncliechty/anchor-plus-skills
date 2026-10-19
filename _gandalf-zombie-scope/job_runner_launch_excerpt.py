# =============================================================================
# EXCERPT — from C:\dev\Anchor\job_runner.py  (NOT the whole file)
#
# The durable job runner's spawn path — where a swarm/lane sub-agent process is
# created, wrapped in a Windows Job Object (KILL_ON_JOB_CLOSE), and mints its
# sweepable session_registry record carrying the zombie-hunter identity
# (pid / proc_create_time / crypt_token).
#
# Pulled sections (verify line numbers — they drift):
#   SWARM_LANE constant                    (~ line 141)
#   def launch(...)                        (~ lines 508-679)
#   def _holder_is_active(job_id)          (~ lines 1461-1479)   [the job_active probe]
#   def launch_guarded(...)                (~ lines 1519-1580)   [concurrency + spawn cap]
#
# The Job Object wrapper itself (attach_to_job_object / CreateJobObjectW /
# AssignProcessToJobObject / JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) lives in
# proc_probe.py (copied verbatim into this scope). launch() calls it below.
# =============================================================================


SWARM_LANE = "swarm"   # (~ line 141) session_registry lane for a launched job


# ── def launch(...)  (job_runner.py ~508-679) ────────────────────────────────
def launch(lane: str, cwd=None, extra_args=None, env=None,
           job_id: str = None, backend=DEFAULT_BACKEND,
           prompt=None, output_dir=None, gated=False,
           permission_mode=None, project_id=None, folder_path=None) -> dict:
    """Launch a server-owned job. Returns the job record.

    The record holds at least ``{job_id, lane, pid, status, log_path, backend}``.
    stdout is streamed by a daemon reader thread into a durable log file *and* an
    in-memory ring buffer. ``cwd`` is the project working directory; ``env`` is
    merged onto the current environment. ``backend`` ∈ {"claude","gemini"}
    selects the engine command (resolved by :func:`resolve_runner_cmd`); it is
    recorded on the job so the UI/history can show which engine ran the effort.
    ``ANCHOR_RUNNER_CMD``, when set, still overrides the command for any backend.

    ``prompt`` (the natural-language lane seed), ``output_dir`` (project-scoped),
    and ``gated`` (falsy for research; ``"plan"``/``"build"`` for the gated lanes)
    are threaded into :func:`resolve_runner_cmd` so a real launch builds a VALID
    per-backend argv.

    ``project_id`` / ``folder_path`` (durability 2026-07 Wave 1, amended) are
    NOT used by the spawn itself — they are persisted into the record's
    ``relaunch_spec`` so :func:`relaunch` can re-drive :func:`launch_guarded`
    with the same concurrency-policy context. :func:`launch_guarded` passes
    them; a direct call may leave them ``None``.

    Stdin handling (D / SETUP §5):
    - NON-GATED (research) **or** no prompt: ``stdin=DEVNULL`` (unchanged Wave-4
      contract — the prompt, if any, is on argv).
    - GATED (plan/build, claude only): ``stdin=PIPE`` kept OPEN for the job's
      lifetime, and the INITIAL prompt is written as a stream-json user message
      (claude's ``--input-format stream-json`` consumes the prompt from stdin,
      not argv). The live process stdin is registered with the gate adapter so an
      answer can be written into the SAME pipe. NOTE: in the test path
      (``ANCHOR_RUNNER_CMD`` set → the mock), the mock reads no stdin, so we still
      open the pipe but the mock simply ignores it; gate tests register their own
      fake sink. This plain-text-after-auto-dismiss gate path is inherently
      FRAGILE (SETUP §4 residual risk): AskUserQuestion can't be answered via a
      tool_result, so the model re-asks in plain text and we answer with a
      stream-json user TEXT turn — best-effort continuation, not guaranteed.
    """
    backend = backend or DEFAULT_BACKEND
    job_id = job_id or uuid.uuid4().hex
    # Pin this job's storage dir for its lifetime (resolved now, once).
    pinned = jobs_dir()
    pinned.mkdir(parents=True, exist_ok=True)
    with _JOB_DIRS_LOCK:
        _JOB_DIRS[job_id] = pinned
    lp = log_path_for(job_id)
    # Truncate/create the durable log up front so tail() always has a target.
    lp.write_text("", encoding="utf-8")

    argv = resolve_runner_cmd(extra_args, backend=backend, prompt=prompt,
                              output_dir=output_dir, gated=gated,
                              permission_mode=permission_mode)

    full_env = dict(os.environ)
    if backend == BACKEND_GEMINI:
        full_env["TRIO_DRIVER"] = "gemini-cli-native"
    if env:
        full_env.update(env)

    crypt_token = uuid.uuid4().hex
    full_env["ANCHOR_SESSION_ID_CRYPT_TOKEN"] = crypt_token

    # On Windows, create a new process group so the whole tree is reapable and
    # signals/kills target the group. taskkill /T handles tree reap regardless,
    # but the flag keeps the child detached from our console.
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW: a console-subsystem child (claude/gemini/python) must
        # never flash a visible window (John's standing no-visible-shells rule).
        creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                         | _paths.NO_WINDOW)

    # Gated lanes need a kept-open stdin PIPE so the initial prompt + the gate
    # answer can be written into the live session. Non-gated lanes keep the
    # original DEVNULL contract.
    use_stdin_pipe = bool(gated)
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=(subprocess.PIPE if use_stdin_pipe else subprocess.DEVNULL),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        bufsize=1,
        text=True,
        # The runner emits UTF-8 (claude -p stream-json, em-dashes / smart quotes /
        # ☢ etc.). Without an explicit encoding, text mode uses the Windows locale
        # (cp1252) and mojibakes every non-ASCII char at capture time. Decode UTF-8
        # (replace any stray byte rather than crash the reader thread).
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    live = _LiveJob(job_id, proc, lp, gated=gated)
    with _LIVE_LOCK:
        _LIVE[job_id] = live

    # Wrap the subprocess in a Job Object with KILL_ON_JOB_CLOSE (Windows only)
    if os.name == "nt":
        try:
            import proc_probe
            live._h_job = proc_probe.attach_to_job_object(proc.pid)
        except Exception:
            live._h_job = None

    # For a gated lane, deliver the initial prompt as a stream-json user turn on
    # stdin and register the (kept-open) pipe with the gate adapter so a later
    # answer writes into the SAME session. Deferred import avoids a cycle.
    if use_stdin_pipe and proc.stdin is not None:
        try:
            if prompt:
                proc.stdin.write(_stream_json_user_turn(prompt))
                proc.stdin.flush()
            import gate_adapter as _ga
            _ga.register_stdin_sink(job_id, proc.stdin)
        except (OSError, ValueError, ImportError):
            # A dead/closed pipe (e.g. the mock exited instantly) is non-fatal —
            # the reader thread + finalize still record the terminal status.
            pass

    try:
        import proc_probe
        proc_create_time = proc_probe.creation_time(proc.pid)
    except Exception:
        proc_create_time = None

    # zombie-hunter v2: mint a sweepable session_registry record for this swarm
    # child, stamping the SAME identity (pid / proc_create_time / crypt_token) the
    # hunter's classify needs. Done here, at the single spawn site, so EVERY job
    # (direct launch() or launch_guarded()) participates. Cleared on exit by
    # _finalize/cancel via _mirror_session_status (the finally-reset).
    _register_swarm_session(job_id, proc.pid, proc_create_time, crypt_token,
                            cwd=cwd)

    rec = {
        "job_id": job_id,
        "lane": lane,
        "pid": proc.pid,
        "status": STATUS_RUNNING,
        "log_path": str(lp),
        "cwd": str(cwd) if cwd else None,
        "started_at": time.time(),
        "exit_code": None,
        "session_id": None,
        "backend": backend,
        "crypt_token": crypt_token,
        "proc_create_time": proc_create_time,
        # Durability 2026-07 Wave 1: everything a guarded launch needs to start
        # an equivalent job, so an interrupted record is re-launchable in ONE
        # call. project_id/folder_path (approved amendment 2026-07-02) are set
        # when the launch came through launch_guarded().
        "relaunch_spec": _build_relaunch_spec(
            lane, cwd, prompt, output_dir, gated, permission_mode, backend, env,
            project_id=project_id, folder_path=folder_path),
    }
    # W13 (C3): journal the launch. Use the project_id/folder_path PARAMETERS
    # (a guarded launch passes them) — the rec dict carries them only inside
    # relaunch_spec, so reading rec.get("project_id") here would always no-op.
    _journal.emit_safe(project_id or "", _journal.EV_JOB_LAUNCHED,
                       correlation_id=job_id or "x", folder_path=folder_path,
                       payload={"job_id": job_id, "lane": lane})
    _write_record(rec)

    live.reader = threading.Thread(
        target=_reader_loop, args=(live,), name=f"job-reader-{job_id}",
        daemon=True,
    )
    live.reader.start()
    return rec


# ── def _holder_is_active(job_id)  (job_runner.py ~1461-1479) ─────────────────
# This is the DEFAULT ``job_active`` probe zombie_hunter.live_owner_ids uses to
# decide a session has a LIVE OWNING JOB (session_id == job_id for a swarm job).
def _holder_is_active(job_id: str) -> bool:
    """True if ``job_id`` is still a live (non-terminal) job.

    Used to garbage-collect stale slots: a holder whose record is terminal (or
    gone) no longer occupies its lane/folder slot, so a fresh launch may proceed.
    Consults the durable record (the cross-restart source of truth); reconciles
    a dead 'running' record to interrupted via :func:`liveness_check`.
    """
    if not job_id:
        return False
    rec = load_record(job_id)
    if rec is None:
        return False
    if rec.get("status") in TERMINAL_STATUSES:
        return False
    # Record still says running — verify the process is genuinely alive,
    # reconciling a dead-but-"running" record to interrupted as a side effect.
    rec = liveness_check(job_id) or rec
    return rec.get("status") not in TERMINAL_STATUSES


# ── def launch_guarded(...)  (job_runner.py ~1519-1580) ──────────────────────
def launch_guarded(lane: str, project_id: str, folder_path, cwd=None,
                   extra_args=None, env=None, job_id: str = None,
                   backend=DEFAULT_BACKEND, prompt=None, output_dir=None,
                   gated=False, permission_mode=None) -> dict:
    """Launch a job under the Wave-6 concurrency policy.

    Policy (frozen design — MASTER-PLAN "Lanes & concurrency"):
    - WITHIN a project: same-lane jobs are **serialized** (a second same-lane
      launch while one is live is refused); cross-lane jobs run **concurrently**
      (the key includes the lane, so different lanes never contend).
    - ACROSS projects sharing a folder: **build** jobs are serialized at the
      FOLDER level (at most one build per ``folder_path``); a second build in
      that folder — even for a different project — is refused with the
      ``folder-build-lock`` indicator. research/plan are NOT folder-locked.

    The reservation (check-and-set of both the lane slot and, for builds, the
    folder lock) plus the actual :func:`launch` all happen INSIDE
    ``paths.WRITE_LOCK``, so the policy is correct under concurrency — two
    builds for one folder can never both win the lock.

    ``prompt`` / ``output_dir`` / ``gated`` / ``permission_mode`` are threaded
    straight through to :func:`launch` so the real per-backend argv (and the
    gated stdin pipe) are built there. They are inert under the concurrency
    policy itself.

    Raises :class:`LaneBusyError` (with ``reason`` + ``holder``) when refused.
    On success returns the job record (as :func:`launch`).
    """
    folder_path = str(folder_path)
    with _paths.WRITE_LOCK:
        # 0) Global spawn cap.
        import pty_manager
        cap = int(os.environ.get("ANCHOR_SPAWN_CAP", 16))
        # Count only GENUINELY-LIVE entries. Finished jobs linger in _LIVE (only
        # cleared on a test reset) and dead PTY children linger in pty_manager
        # _LIVE, so a raw len() count permanently locks out new spawns after a
        # few cumulative runs until a restart. _holder_is_active is already used
        # under this same WRITE_LOCK by _gc_lane_slot, so it is safe here.
        live_jobs = sum(1 for jid in list(_LIVE.keys()) if _holder_is_active(jid))
        live_ptys = sum(1 for c in pty_manager._LIVE.values() if c.is_alive())
        total_live = live_jobs + live_ptys
        if total_live >= cap:
            raise LaneBusyError("spawn-cap-reached", message=f"Global sub-agent spawn cap reached ({total_live}/{cap}).")

        # 1) Same-lane within-project serialization.
        _gc_lane_slot(project_id, lane)
        same = _ACTIVE_LANE.get((project_id, lane))
        if same is not None:
            raise LaneBusyError(REFUSED_SAME_LANE, holder=same)

        # 2) Folder-level build lock (build lane only).
        if lane == BUILD_LANE:
            _gc_folder_build(folder_path)
            held = _FOLDER_BUILD.get(folder_path)
            if held is not None:
                raise LaneBusyError(REFUSED_FOLDER_BUILD, holder=held)

        # Both gates clear → launch under the lock, then record the reservation
        # against the real job_id so subsequent contenders see it. project_id /
        # folder_path ride into launch() so the durable relaunch_spec carries
        # the policy context (approved amendment, 2026-07-02).
        rec = launch(lane, cwd=cwd, extra_args=extra_args, env=env,
                     # ... (reservation bookkeeping continues below this excerpt) ...
                     )
