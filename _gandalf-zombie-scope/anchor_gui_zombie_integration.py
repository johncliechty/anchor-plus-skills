# =============================================================================
# EXCERPT — from C:\dev\Anchor\anchor_gui.py  (NOT the whole file)
#
# Zombie-hunter integration points inside the Anchor HTTP server. These are the
# call sites that consume zombie_hunter.classify / live_owner_ids / pause_orphan
# and drive the boot-time reconcile + reaper + armed kill-daemon.
#
# Pulled sections (verify line numbers against the live file — they drift):
#   (A) ~ lines 9997-10042  — GET /api/rnd/orphan_check  (the alert-banner poll)
#   (B) ~ lines 10180-10289 — do_GET "Swarm & Owner View" render + pause_orphan
#                              (the view that FREEZES flagged orphans)
#   (C) ~ lines 11912-11999 — POST /api/rnd/zombie_terminal_start (live briefing)
#   (D) ~ lines 13475-13548 — boot-time session_registry reconcile (by process
#                              liveness) + preview/worktree reap_orphans + the
#                              armed kill-daemon live_ids provider (start_hunter)
#
# Only the enclosing handler bodies are reproduced; surrounding do_GET/do_POST
# dispatch and unrelated branches are elided.
# =============================================================================


# ── (A) GET /api/rnd/orphan_check  (anchor_gui.py ~9997-10042) ───────────────
            elif self.path.startswith("/api/rnd/orphan_check"):
                # Lightweight read-only poll for the dashboard's orphan-swarm
                # alert banner: returns the session_ids of RUNNING sessions
                # currently classified ORPHANED (verdict "kill"). Token-gated
                # like the other read-API GETs; a no-op when ANCHOR_TOKEN unset.
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                import zombie_hunter
                import pty_manager
                try:
                    attached = set(pty_manager.live_sessions())
                except Exception:
                    attached = set()
                orphans = []
                try:
                    running_recs = _sessreg.list_sessions(status="running")
                    # (#1, safety-critical) An orphan is a RUNNING session with NO
                    # LIVE OWNER — not merely one absent from the PTY-attached set.
                    # Broaden "attached" to the full live-owner set (attached ∪
                    # job-owned ∪ parent-owned) so a legit, work-doing session with
                    # no open browser stream is never falsely flagged as a runaway.
                    try:
                        live_ids = zombie_hunter.live_owner_ids(attached, records=running_recs)
                    except Exception:
                        live_ids = attached
                    for rec in running_recs:
                        sid = rec.get("session_id", "")
                        try:
                            verdict = zombie_hunter.classify(rec, live_ids)
                        except Exception:
                            verdict = "kill" if (sid and sid not in live_ids) else "alive"
                        # Only alert on orphans born DURING THIS server's life.
                        # After a restart, prior-instance 'running' records whose
                        # backend survived classify as 'kill' against an empty
                        # live set — those are not a fresh runaway swarm, so the
                        # startup banner must not fire for them (the zombie report
                        # still lists any true survivor). _SERVER_BOOT_TS defaults
                        # to 0.0, so a record with no timestamp never spuriously
                        # alerts.
                        if (verdict == "kill" and sid
                                and float(rec.get("created_at") or 0) >= _SERVER_BOOT_TS):
                            orphans.append(sid)
                except Exception:
                    pass
                self._send_json({"ok": True, "orphans": orphans})


# ── (B) do_GET "Swarm & Owner View" render + pause_orphan  (anchor_gui.py ~10180-10289) ──
                # NOTE: _sessreg / _rnd are the MODULE-LEVEL aliases (imported at top).
                # Do NOT re-import them locally here — a local `import ... as _rnd`
                # makes _rnd function-local for ALL of do_GET, breaking earlier routes
                # in this method with UnboundLocalError.
                try:
                    attached = set(pty_manager.live_sessions())
                except Exception:
                    attached = set()

                running_records = []
                try:
                    running_records = _sessreg.list_sessions(status="running")
                except Exception:
                    pass

                # (#1, safety-critical) This view marks orphans AND FREEZES them
                # (pause_orphan). Use the full live-owner discriminator so a legit
                # work-doing session with no open stream is never frozen/killed:
                # an orphan has NO live owner (not job-owned, not parent-owned),
                # not merely "no attached PTY stream".
                try:
                    live_ids = zombie_hunter.live_owner_ids(attached, records=running_records)
                except Exception:
                    live_ids = attached

                # Group by OWNER (project title, or project_id, or "(unowned)")
                groups = {}
                for rec in running_records:
                    proj_id = rec.get("project_id", "")
                    if proj_id:
                        proj = _rnd.get_project(proj_id)
                        owner = proj.get("name") if (proj and proj.get("name")) else proj_id
                    else:
                        owner = "(unowned)"

                    if owner not in groups:
                        groups[owner] = []
                    groups[owner].append(rec)

                # Add new section Swarm & Owner View
                html += "<h2>Swarm & Owner View</h2>"
                html += "<style>"
                html += ".btn-kill { background: #7f1d1d; color: #fca5a5; border: 1px solid #b91c1c; border-radius: 4px; padding: 4px 8px; font-size: 11px; cursor: pointer; font-weight: 600; transition: background 0.2s; margin-left: 8px; }"
                html += ".btn-kill:hover { background: #991b1b; }"
                html += ".btn-kill:disabled { background: #27272a; color: #71717a; border-color: #3f3f46; cursor: not-allowed; }"
                html += ".btn-resume { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; border-radius: 4px; padding: 4px 8px; font-size: 11px; cursor: pointer; font-weight: 600; transition: background 0.2s; margin-left: 6px; }"
                html += ".btn-resume:hover { background: #065f46; }"
                html += ".btn-resume:disabled { background: #27272a; color: #71717a; border-color: #3f3f46; cursor: not-allowed; }"
                html += ".btn-start { background: #1e3a8a; color: #93c5fd; border: 1px solid #2563eb; border-radius: 4px; padding: 6px 12px; font-size: 12px; cursor: pointer; font-weight: 600; transition: background 0.2s; }"
                html += ".btn-start:hover { background: #1e40af; }"
                html += ".btn-start:disabled { background: #27272a; color: #71717a; border-color: #3f3f46; cursor: not-allowed; }"
                html += ".owner-heading { color: #f4f4f5; font-size: 16px; margin-top: 20px; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #27272a; font-weight: bold; }"
                html += "</style>"

                if not running_records:
                    html += "<p style='color: #a1a1aa; font-style: italic;'>No active swarms or sessions.</p>"
                else:
                    sorted_owners = sorted(groups.keys(), key=lambda o: (o == "(unowned)", o.lower()))
                    for owner in sorted_owners:
                        html += f"<div class='owner-heading'>Owner: {html_lib.escape(owner)}</div>"
                        html += "<table>"
                        html += "<thead><tr><th>Swarm/Lane</th><th>Session</th><th>PID</th><th>Backend</th><th>Status</th><th>State</th></tr></thead>"
                        html += "<tbody>"
                        for rec in groups[owner]:
                            sid = rec.get("session_id", "")
                            short_sid = sid[:8]
                            lane = rec.get("lane", "")
                            pid = rec.get("pid")
                            pid_str = str(pid) if pid is not None else ""
                            backend = rec.get("backend", "")
                            status = rec.get("status", "")

                            try:
                                is_orphaned = (zombie_hunter.classify(rec, live_ids) == "kill")
                            except Exception:
                                is_orphaned = (sid not in live_ids)

                            if is_orphaned:
                                # FREEZE the orphan while it waits to be killed so
                                # it stops burning CPU (pytest-guarded inside).
                                paused = False
                                try:
                                    paused = zombie_hunter.pause_orphan(pid)
                                except Exception:
                                    paused = False
                                pause_badge = ("<span class='badge badge-warning' title='Process frozen while it waits to be killed'>Paused</span> "
                                               if paused else "")
                                resume_btn = (f" <button class='btn-resume' onclick=\"resumeSession('{sid}', this)\">Resume</button>"
                                              if paused else "")
                                state_html = (
                                    f"<span class='badge badge-danger'>Orphaned</span> {pause_badge}"
                                    f"<button class='btn-kill' onclick=\"killSession('{sid}', this)\">Kill</button>{resume_btn}")
                            else:
                                state_html = (
                                    "<span class='badge badge-success'>Attached</span> "
                                    f"<button class='btn-kill' onclick=\"killSession('{sid}', this)\">Kill</button>")

                            html += f"<tr id='row-{sid}'>"
                            html += f"<td>{html_lib.escape(lane)}</td>"
                            html += f"<td title='{html_lib.escape(sid)}'><code>{html_lib.escape(short_sid)}</code></td>"
                            html += f"<td>{html_lib.escape(pid_str)}</td>"
                            html += f"<td><code>{html_lib.escape(backend)}</code></td>"
                            html += f"<td><span class='badge badge-success'>{html_lib.escape(status)}</span></td>"
                            html += f"<td>{state_html}</td>"
                            html += "</tr>"
                        html += "</tbody>"
                        html += "</table>"


# ── (C) POST /api/rnd/zombie_terminal_start  (anchor_gui.py ~11912-11999) ────
        elif self.path == "/api/rnd/zombie_terminal_start":
            import shutil
            import zombie_hunter
            import pty_manager

            backend = "claude"
            if not shutil.which("claude"):
                backend = "gemini"

            try:
                attached = set(pty_manager.live_sessions())
            except Exception:
                attached = set()

            report_path = zombie_hunter._last_report_path()
            report_data = None
            if report_path.exists():
                try:
                    report_data = json.loads(report_path.read_text("utf-8"))
                except Exception:
                    pass

            if not report_data:
                try:
                    report_data = zombie_hunter.sweep(live_session_ids=list(attached), apply=False)
                except Exception:
                    report_data = {}

            running_records = []
            try:
                running_records = _sessreg.list_sessions(status="running")
            except Exception:
                pass

            # (#1, safety-critical) Classify against the full live-owner set so a
            # legit work-doing session with no open stream is not briefed as an
            # orphan: attached ∪ job-owned ∪ parent-owned.
            try:
                live_ids = zombie_hunter.live_owner_ids(attached, records=running_records)
            except Exception:
                live_ids = attached

            session_briefs = []
            orphaned_ids = []
            for rec in running_records:
                sid = rec.get("session_id", "")
                lane_name = rec.get("lane", "")
                pid = rec.get("pid")
                rec_backend = rec.get("backend", "")
                proj_id = rec.get("project_id", "")

                owner = "(unowned)"
                if proj_id:
                    proj = _rnd.get_project(proj_id)
                    if proj and proj.get("name"):
                        owner = proj["name"]
                    else:
                        owner = proj_id

                try:
                    classification = zombie_hunter.classify(rec, live_ids)
                except Exception:
                    classification = "kill" if sid not in live_ids else "alive"

                if classification == "kill":
                    orphaned_ids.append(sid)
                    cls_str = "ORPHANED (Pending Kill)"
                elif classification == "alive":
                    cls_str = "ALIVE (Attached)"
                else:
                    cls_str = classification.upper()

                session_briefs.append(
                    f"- Session ID: {sid}\n  Lane: {lane_name}\n  PID: {pid}\n  Backend: {rec_backend}\n  Owner Project: {owner}\n  Classification: {cls_str}"
                )
            # ... (briefing text assembly continues below this excerpt) ...


# ── (D) boot: reconcile-by-liveness + reap_orphans + armed kill-daemon  (anchor_gui.py ~13475-13548) ──
            _pid = _rec.get("pid")
            if not _sid or not _pid:
                continue
            try:
                if _pp_boot.creation_time(_pid) is not None:
                    _alive_pids.add(_sid)
            except Exception:
                pass
        _sr_boot.reconcile(live_session_ids=_alive_pids)
    except Exception as e:
        _logger.error(f"session_registry boot reconcile failed: {e}")

    try:
        import preview_server
        preview_server.reap_orphans()
    except Exception as e:
        _logger.error(f"preview_server.reap_orphans failed: {e}")

    try:
        import worktrees
        import pty_manager
        _reap = worktrees.reap_orphans(set(pty_manager._LIVE.keys()))
        # W11 (C6): the first post-move boot sweeps report-only so a path-rewrite
        # miss can never delete a legit worktree. Live reaping re-arms only after
        # a clean dry report (worktrees.reap_orphans clears the marker itself).
        if _reap.get("dryrun"):
            _logger.info(
                "worktrees.reap_orphans DRY-RUN (post-move): would_reap=%s "
                "kept=%s — live reaping %s",
                _reap.get("would_reap"), _reap.get("kept"),
                "re-armed (clean report)" if not _reap.get("would_reap")
                and not _reap.get("errors") else "held (report not clean)")
    except Exception as e:
        _logger.error(f"worktrees.reap_orphans failed: {e}")

    # ... (leaked __healthcheck__ probe-project purge elided) ...

    try:
        if "PYTEST_CURRENT_TEST" not in os.environ and not _zombie_hunter_started:
            _zombie_hunter_started = True
            import zombie_hunter
            import pty_manager
            def _live_provider():
                # (#1, safety-critical) The daemon KILLS verdict==kill sessions
                # when armed (ANCHOR_ZOMBIE_HUNTER=1). Hand it the full live-owner
                # set, not just the PTY-attached one, so a legit job-owned /
                # parent-owned session is never reaped for lacking a browser stream.
                attached = set(pty_manager._LIVE.keys())
                try:
                    return zombie_hunter.live_owner_ids(attached)
                except Exception:
                    return attached
            zombie_hunter.start_hunter(_live_provider)
    except Exception as e:
        _logger.error(f"zombie_hunter.start_hunter failed: {e}")
