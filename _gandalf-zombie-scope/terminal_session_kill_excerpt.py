# =============================================================================
# EXCERPT — from C:\dev\Anchor\terminal_session.py  (NOT the whole file)
#
# The managed-session lifecycle teardown paths. These are the "reap" surfaces a
# reviewer must weigh against the zombie-hunter: how a live PTY-backed session is
# stopped, parked, or deleted, and how a boot-time reconcile advances stale ones.
#
# Pulled sections (verify line numbers — they drift):
#   def kill(...)                    (~ lines 2219-2307)   reap PTY + persist docs + remove worktree + DONE
#   def capture_session_docs(...)    (~ lines 2344-2378)   persist-before-reap
#   def close_session(...)           (~ lines 2383-2460)   graceful park (STATUS_IDLE, keep worktree)
#   def delete_session(...)          (~ lines 2476-2551)   hard-delete record (kills first if live)
#   def reconcile_and_advance(...)   (~ lines 2886-2920)   boot reconcile → auto-advance stale planning
#
# Module aliases used below: _pty (pty_manager), _reg (session_registry),
# _wt (worktrees), _eh (effort_history), _rnd (rnd_registry), _journal, _boneyard,
# _handoff. _PLANNING_LANES is the set {plan, planning}.
# =============================================================================


# ── def kill(...)  (terminal_session.py ~2219-2307) ──────────────────────────
def kill(session_id, project_id=None, _record_boneyard=True, actor=None):
    """Kill a session: reap the PTY, mark terminal, PERSIST DOCS, remove worktree.

    Tolerant: an unknown/already-dead PTY still proceeds to re-status the registry
    record (``STATUS_DONE``) and remove the worktree. ``project_id`` is resolved
    from the registry record when not supplied so the worktree's owning repo can
    be located for a clean ``git worktree remove``. Other sessions are untouched.

    v8 Wave 2 (THE KEYSTONE): BEFORE the worktree is reaped, the session's
    produced documents are persisted into the MAIN project (copied + committed
    via :func:`capture_session_docs` → ``effort_history.persist_session_docs``)
    so they survive the kill, are discoverable from the main folder, and ride
    into later worktrees (which are checked out off main HEAD). This is
    best-effort — a persistence failure never blocks the kill.

    ``_record_boneyard`` (PRIVATE, default ``True``): when ``False`` the v10 W6
    ``killed`` Boneyard capture is SUPPRESSED. :func:`delete_session` passes
    ``False`` when it kills a still-live session as part of a delete — the
    ``deleted`` entry is the canonical record for a delete, so a kill-driven
    ``killed`` entry would be a spurious DUPLICATE. Doc PERSISTENCE
    (``capture_session_docs``) still runs regardless — only the Boneyard record is
    suppressed, so the subsequent ``deleted`` entry's ``doc_rels`` are populated.

    Returns ``{"ok": True, "session_id", "pty_killed", "docs": {...},
    "worktree": {...}}``.
    """
    record = _reg.get_session(session_id)
    if project_id is None and record:
        project_id = record.get("project_id") or None

    pty_killed = False
    try:
        _pty.kill(session_id)
        pty_killed = True
    except _pty.UnknownSession:
        pty_killed = False  # already dead / never had a live PTY — tolerate

    # Mark the registry record terminal (DONE) — tolerate an unknown id.
    # W12 (C3, D1): journal-first — emit ``session-killed`` BEFORE the legacy
    # DONE write (best-effort, off-switch-gated: with the journal flag off ONLY
    # update_session runs, byte-identical to before).
    try:
        _journal.dual_write(
            project_id, _journal.EV_SESSION_KILLED,
            lambda: _reg.update_session(session_id, status=_reg.STATUS_DONE),
            correlation_id=((record or {}).get("chain_id") or session_id),
            actor=actor,
            causation_id=((record or {}).get("parent_session_id") or None),
            payload={"session_id": session_id,
                     "lane": (record or {}).get("lane", "")},
        )
    except KeyError:
        pass

    # v8 KEYSTONE: capture + persist the session's produced docs into the MAIN
    # project BEFORE the worktree is reaped (after which they'd be gone forever).
    #
    # v12 Wave 5: this now routes through the SHARED persist+summarize keystone
    # (:func:`_persist_current_stage`) that :func:`finish_stage` also calls — so a
    # stage boundary and a kill persist identically. For a v12 effort with a
    # recorded active stage it persists ONLY that stage's docs (Wave-3) and
    # schedules the stage-keyed summary (Wave-4); for every legacy/non-effort
    # session (i.e. every existing kill test) it falls back to the EXACT pre-v12
    # whole-tree :func:`capture_session_docs`, so kill's observable behavior here
    # — the persisted doc set fed to the worktree-removal + the Boneyard below —
    # is byte-identical to before the refactor. Best-effort (never blocks kill).
    docs_out = _persist_current_stage(session_id, project_id=project_id,
                                      record=record)

    # Remove the per-session worktree (safety-checked, tolerant of already-gone).
    wt_out = _wt.remove_worktree(session_id, project_id=project_id)

    # v10 Wave 6 — Boneyard capture (D3 source "killed"). A hard-kill is the
    # deliberate "I'm done / discarding" action; if this session PRODUCED material
    # (persisted docs), index it in the project's Boneyard. This is purely ADDITIVE
    # — the session's normal finished tile/record is unaffected — and BEST-EFFORT:
    # a Boneyard failure must NEVER break the kill path. SUPPRESSED when this kill
    # is part of a delete_session (the canonical "deleted" entry is recorded there;
    # a "killed" entry too would be a spurious duplicate for ONE delete).
    if _record_boneyard:
        _capture_killed_to_boneyard(session_id, project_id, record, docs_out)

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "docs": docs_out,
        "worktree": wt_out,
    }


# ── def capture_session_docs(...)  (terminal_session.py ~2344-2378) ──────────
def capture_session_docs(session_id, project_id=None, record=None):
    """Persist a session's produced docs into the MAIN project (before any reap).

    Generalizes the v6 ``capture_plan_set`` capture-before-reap discipline to ALL
    trio docs: resolves the session's registry record (its lane + worktree_path),
    then delegates to :func:`effort_history.persist_session_docs`, which copies
    the produced documents into the main folder, records per-doc efforts so they
    are discoverable, and commits them scoped to the project repo.

    Best-effort and never raises — returns the ``persist_session_docs`` result, or
    a ``{"ok": False, "reason": ...}`` dict when the session/worktree/project
    cannot be resolved (so a missing record can't break the kill path).
    """
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if rec is None:
            return {"ok": False, "reason": "unknown-session", "persisted": []}
        if project_id is None:
            project_id = rec.get("project_id") or None
        if not project_id:
            return {"ok": False, "reason": "no-project", "persisted": []}
        worktree_path = rec.get("worktree_path", "")
        if not worktree_path:
            return {"ok": False, "reason": "no-worktree", "persisted": []}
        proj = _rnd.get_project(project_id)
        if proj is None:
            return {"ok": False, "reason": "unknown-project", "persisted": []}
        folder = proj.get("folder_path", "")
        if not folder:
            return {"ok": False, "reason": "no-folder", "persisted": []}
        lane = rec.get("lane", "") or ""
        return _eh.persist_session_docs(
            folder, project_id, lane, session_id, worktree_path)
    except Exception:
        return {"ok": False, "reason": "error", "persisted": []}


# ── def close_session(...)  (terminal_session.py ~2383-2460) ─────────────────
def close_session(session_id, project_id=None, actor=None):
    """GRACEFUL CLOSE (the panel "×") — park a session so it resumes WARM (W6).

    DISTINCT from both :func:`kill` and :func:`delete_session`. The panel "×" is a
    NON-destructive close: it STOPS the live PTY but PRESERVES the worktree and
    KEEPS the registry record — re-statused ``STATUS_IDLE`` (parked / grey /
    reopenable) when it was RUNNING — so the session can be resumed later (W3/W4).
    No worktree removal, no record deletion, no auto-advance (a park is NOT a
    finish).

    W6 amendment — a bare "preserve the worktree" close would reopen COLD: the
    boot orphan-reaper deletes a no-live-PTY worktree on restart, and
    :func:`anchor_gui._build_continue_seed` reads cache / main-persisted docs ONLY
    (never the worktree). So before returning, close MUST PERSIST the session's
    produced docs into the MAIN project (:func:`capture_session_docs`, exactly like
    :func:`kill`) so they survive the boot reaper and feed the resume seed. The
    ``/api/rnd/term_close`` endpoint ALSO schedules the same best-effort background
    session-summary hook ``finish``/``kill`` use, so the resume opens WARM; and
    :func:`worktrees.reap_orphans` is taught to KEEP a ``STATUS_IDLE`` worktree.

    Tolerant + best-effort: an already-dead / never-live PTY, a missing record, or
    a persist failure never blocks the park. Returns ``{"ok": True, "session_id",
    "pty_killed", "status", "docs"}`` — or ``{"ok": False, "reason":
    "unknown-session"}`` when the id has no registry record (the panel close then
    just tears down its DOM).
    """
    record = _reg.get_session(session_id)
    if record is None:
        return {"ok": False, "session_id": session_id,
                "reason": "unknown-session"}
    if project_id is None:
        project_id = record.get("project_id") or None

    # Stop the live PTY (tolerant of an already-dead / never-live session).
    pty_killed = False
    try:
        _pty.kill(session_id)
        pty_killed = True
    except _pty.UnknownSession:
        pty_killed = False

    # W6 amendment: persist the produced docs into the MAIN project (like kill)
    # BEFORE anything could reap the worktree (the boot reaper / a later restart),
    # so they survive and the W3 resume seed (cache / main-only) can read them.
    # Best-effort — never blocks the park.
    docs_out = capture_session_docs(session_id, project_id=project_id,
                                    record=record)

    # KEEP the worktree (NO remove_worktree) and KEEP the registry record. Park a
    # still-RUNNING session at STATUS_IDLE (grey, reopenable); leave an already
    # terminal/idle record as-is — a historical panel close must never "un-finish"
    # a DONE/FAILED session.
    status = record.get("status")
    if status == _reg.STATUS_RUNNING:
        # W12 (C3, D1): journal-first — emit ``session-closed`` BEFORE the legacy
        # park (RUNNING→IDLE) write (best-effort, off-switch-gated).
        try:
            _journal.dual_write(
                project_id, _journal.EV_SESSION_CLOSED,
                lambda: _reg.update_session(
                    session_id, status=_reg.STATUS_IDLE),
                correlation_id=(record.get("chain_id") or session_id),
                actor=actor,
                causation_id=(record.get("parent_session_id") or None),
                payload={"session_id": session_id,
                         "lane": record.get("lane", "")},
            )
            status = _reg.STATUS_IDLE
        except KeyError:
            pass

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "status": status,
        "docs": docs_out,
    }


# ── def delete_session(...)  (terminal_session.py ~2476-2551) ────────────────
def delete_session(session_id, project_id=None):
    """Permanently delete a managed session from Anchor (v9 Wave 1).

    Distinct from :func:`kill`: this REMOVES the registry record (so the tile is
    gone and STAYS gone across a reload — ``term_sessions``/the board read the
    registry, which no longer holds it) AND removes the session's lane effort
    pointer-records / index entries / cached summary
    (``effort_history.delete_session_efforts``). The produced DOCUMENTS are KEPT
    on disk (Option A) — only the Anchor pointer-records + cache are dropped.

    If the session is still LIVE it is :func:`kill`-ed first (reap PTY + persist
    docs + remove worktree), so a running session can be deleted safely.

    Best-effort, IDEMPOTENT (a second delete is a clean no-op), and never raises.
    Returns ``{"ok": True, "deleted": bool, "session_id", "killed": bool,
    "efforts": {...}}`` where ``deleted`` is whether a registry record was
    removed (False if the id was already unknown).
    """
    rec = _reg.get_session(session_id)
    if project_id is None and rec:
        project_id = rec.get("project_id") or None
    lane = (rec.get("lane") if rec else "") or ""

    killed = False
    # If the session is still live (a running PTY / RUNNING status), kill it first
    # so the PTY + worktree are reaped and its docs are persisted before we drop
    # the record. Tolerate any failure — delete must still proceed. We SUPPRESS the
    # kill's "killed" Boneyard capture (``_record_boneyard=False``): a delete of a
    # live session must yield exactly ONE Boneyard entry — the canonical "deleted"
    # entry recorded below — not a "killed" + "deleted" pair. Doc PERSISTENCE still
    # runs in kill, so the "deleted" entry's doc_rels are populated.
    try:
        if rec is not None and (
                session_id in set(_pty.live_sessions())
                or rec.get("status") == _reg.STATUS_RUNNING):
            kill(session_id, project_id=project_id, _record_boneyard=False)
            killed = True
    except Exception:
        killed = False

    # Hard-delete the registry record (the durability of "stays gone": the board
    # + term_sessions read the registry, so a removed record never re-surfaces).
    try:
        deleted = bool(_reg.remove_session(session_id))
    except Exception:
        deleted = False

    # Remove the lane effort pointer-records / index entries / cached summary —
    # but KEEP the produced documents on disk (Option A). Resolve the folder.
    efforts_out = {"ok": False, "reason": "unresolved"}
    try:
        if project_id and lane:
            proj = _rnd.get_project(project_id)
            folder = (proj or {}).get("folder_path", "") if proj else ""
            if folder:
                # v10 Wave 6 (D10) — CAPTURE the Boneyard entry BEFORE
                # delete_session_efforts drops the pointer-records: the entry is
                # built from efforts_for_session_id (the docs the session
                # produced) + the cached summary, which only exist WHILE the
                # pointer-records are still present. After this call the efforts
                # are gone — the Boneyard is the deleted session's ONLY remaining
                # home (the docs stay on disk, Option A). BEST-EFFORT.
                _capture_deleted_to_boneyard(folder, project_id, lane,
                                             session_id, rec)
                efforts_out = _eh.delete_session_efforts(
                    folder, project_id, lane, session_id)
    except Exception:
        efforts_out = {"ok": False, "reason": "error"}

    return {
        "ok": True,
        "deleted": deleted,
        "session_id": session_id,
        "killed": killed,
        "efforts": efforts_out,
    }


# ── def reconcile_and_advance(...)  (terminal_session.py ~2886-2920) ─────────
def reconcile_and_advance(live_session_ids=None, worktree_exists=None,
                          mark_stale_status=_reg.STATUS_DONE):
    """Reconcile the registry, then auto-advance any newly-DONE planning session.

    The cockpit's reconcile-dead path (a managed session whose process is gone):
    re-status the stale sessions, then for each one that was a **planning** session
    just marked terminal/DONE, attempt :func:`auto_advance_planning_to_build`
    (idempotent on ``parent_session_id``, so re-running reconcile never
    duplicates; ``no plan ⇒ no advance``). Best-effort — an advance failure for
    one session never breaks the reconcile or the others.

    Reconcile here defaults ``mark_stale_status`` to ``STATUS_DONE`` (not the
    registry default ``STATUS_IDLE``) because a reconcile-dead transition for the
    cockpit IS the "this session finished" signal that gates the advance. Returns
    ``{"reconcile": <report>, "auto_builds": [<build_record>, ...]}``.
    """
    report = _reg.reconcile(
        live_session_ids=live_session_ids, worktree_exists=worktree_exists,
        mark_stale_status=mark_stale_status, apply=True)
    auto_builds = []
    if mark_stale_status == _reg.STATUS_DONE:
        for sid in report.get("marked", []):
            rec = _reg.get_session(sid)
            if rec is None or rec.get("lane") not in _PLANNING_LANES:
                continue
            pid = rec.get("project_id") or None
            if not pid:
                continue
            try:
                build = auto_advance_planning_to_build(pid, sid)
            except Exception:
                build = None
            if build is not None:
                auto_builds.append(build)
    return {"reconcile": report, "auto_builds": auto_builds}
