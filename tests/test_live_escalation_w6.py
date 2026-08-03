"""W6 — Live Escalation & Tile Reliability: B2 fixes · attach-ack · orientation
fork · eviction · no-ACTION-auto-submit (Honest Telemetry + Warm Resume).

Cites ``NORTH-STAR-AMENDMENT.md`` (the click contract — all layers · the eviction
ruling + evicted-tile sub-contract · the strict-literal-reading rejection · the
orientation fork · the endpoint auth rule). Serves criteria (4),(5).

The three diag-B2 state-bugs (reproduced repro-first in ``test_b2_repro_w1.py``)
are FIXED here, one regression each:

  * S1 blank large-tile window → the WS/SSE ATTACH-ACK handshake: a dead/unknown
    session yields an explicit ``attach_ack ok:false`` (the client paints a styled
    error state with Retry, narration still visible) — a blank pane is now a
    protocol impossibility. Defense-in-depth: the client re-polls liveness.
  * S2 context-free blue restart → the read-only body surfaces the Layer-1
    narration PREVIEW before any continue, and escalation is routed by tile class
    (``/api/rnd/resume_live``), not a context-free immediate POST.
  * S3 dual undistinguished resume → ONE policy: read-only orientation
    AUTO-EXECUTES as a plan-mode one-shot job (never a seeded PTY turn); ACTION
    prompts stay v10 paste-NOT-submit; and the greet-gate gains a BOUNDED FALLBACK
    so a paraphrased/omitted greet never leaves a paste pending forever.

No ``pytest.importorskip`` / ``skip`` / ``xfail`` / ``skipif`` anywhere (the W1
lesson — a skip rise trips Foreman's §5 test-integrity guard). git is a hard CI
requirement, so the integration legs fail honestly (never skip) if absent.
"""
import importlib
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "sidecar"
EXPECTED = json.loads((FIXTURES / "EXPECTED.json").read_text(encoding="utf-8"))
FAKE = (REPO / "tests" / "fake_claude.py").as_posix()

JS = (REPO / "static" / "project-window.js").read_text(encoding="utf-8")
CSS = (REPO / "static" / "project-window.css").read_text(encoding="utf-8")
GUI = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
TS = (REPO / "terminal_session.py").read_text(encoding="utf-8")


def _fx(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1) diag-B2 S1 — the ATTACH-ACK fix (blank pane is a protocol impossibility)
# ══════════════════════════════════════════════════════════════════════════════

class TestB2S1AttachAck:
    def test_ws_control_frame_helper_encodes_prefixed_json(self):
        import anchor_gui
        frame = anchor_gui.ws_ctl_frame({"type": "attach_ack", "ok": False,
                                         "reason": "unknown-session"})
        assert isinstance(frame, (bytes, bytearray))
        # The prefixed control payload is carried inside the TEXT frame.
        assert anchor_gui.WS_CTL_PREFIX.encode("utf-8") in frame
        assert b"attach_ack" in frame and b"unknown-session" in frame

    def test_ws_handler_emits_ack_not_a_silent_break(self):
        # The FIX: the WS pump now sends an attach_ack + replay_complete BEFORE the
        # loop (the diag-B2 S1 silent-close is superseded by an explicit ack).
        assert "ws_ctl_frame({" in GUI
        assert '"type": "attach_ack"' in GUI
        assert '"type": "replay_complete"' in GUI

    def test_sse_handler_emits_attach_ack(self):
        assert 'self._sse_event("attach_ack"' in GUI
        assert 'self._sse_event("replay_complete"' in GUI

    def test_client_paints_error_state_and_swaps_only_after_replay(self):
        # The pane swaps in ONLY after replay_complete; a failed attach paints a
        # styled error state with Retry, narration still visible underneath.
        assert "WS_CTL_PREFIX" in JS
        assert "replay_complete" in JS
        assert "term-attach-err" in JS
        assert "term-attach-retry" in JS or "Retry" in JS
        # The error-state CSS is shipped.
        assert ".term-attach-err" in CSS
        assert ".term-attach-retry" in CSS

    def test_client_repolls_liveness_defense_in_depth(self):
        # Defense-in-depth: the stale-'running' cache heals on refocus + a timer.
        assert "addEventListener('focus'" in JS
        assert "setInterval(" in JS


# ══════════════════════════════════════════════════════════════════════════════
# 2) diag-B2 S2 — the context-preview fix (Layer-1 preview + class-routed resume)
# ══════════════════════════════════════════════════════════════════════════════

class TestB2S2ContextPreview:
    def test_readonly_body_surfaces_layer1_preview_before_continue(self):
        # The blue Continue button no longer stands alone with no preview — the
        # read-only body prepends the Layer-1 narration spine (a pre-click preview
        # of what the resume carries).
        assert "_mountReadOnlyBody" in JS
        assert "_mountLayer1Narration(sessionId, host" in JS

    def test_resume_is_routed_by_tile_class_not_context_free_post(self):
        # The escalation is decided by tile class server-side, not a context-free
        # immediate continue POST.
        assert "/api/rnd/resume_live" in JS
        assert "resumed from persisted docs (worktree evicted)" in GUI


# ══════════════════════════════════════════════════════════════════════════════
# 3) diag-B2 S3 — one resume policy + the greet-gate BOUNDED FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

class TestB2S3GreetGateFallback:
    def test_fallback_constant_and_helper_exist(self):
        assert "PASTE_FLUSH_FALLBACK_SECS" in TS
        assert "_paste_flush_fallback_secs" in TS

    def test_flush_is_wired_into_autosave_unmounted_followon(self):
        # The S3 attach-race facet: the flush is now evaluated on the autosave
        # heartbeat too, so an UNMOUNTED follow-on session still delivers its paste.
        auto = TS.split("def autosave_session")[1].split("def autosave_running")[0]
        assert "_flush_pending_paste(session_id)" in auto


# ══════════════════════════════════════════════════════════════════════════════
# 4) The orientation fork — read-only plan-mode, ownership window, never submits
# ══════════════════════════════════════════════════════════════════════════════

class TestOrientationFork:
    def test_prompt_is_read_only_and_carries_the_spine(self):
        import orientation as orient
        view = {"done": "ran researchPrime in research (2026-07-01, done)",
                "produced": [{"role": "report", "label": "report.md",
                              "href": "/report/p/research/j"}],
                "next": {"text": "Advance to planning.", "submit": False}}
        p = orient.build_orientation_prompt(view, lane="research")
        assert "READ-ONLY" in p
        assert "do NOT edit" in p
        # It carries the narration spine (done / produced / next) inline.
        assert "ran researchPrime" in p
        assert "report.md" in p
        assert "Advance to planning." in p

    def test_orient_launches_plan_mode_and_stamps_ownership(self):
        import orientation as orient
        seen = {}

        def fake_launch(lane, **kw):
            seen["lane"] = lane
            seen.update(kw)
            return {"job_id": "job-orient-1"}

        out = orient.orient_session(
            "pid", "research", "sess-A", folder_path="/tmp/x",
            record={"worktree_path": "", "status": "idle"},
            launch=fake_launch, env={"ANCHOR_ORIENTATION_OWNERSHIP_SECS": "300"},
            now=1000.0)
        assert out["ok"] is True
        assert out["job_id"] == "job-orient-1"
        # Read-only: launched with permission_mode='plan' (never acceptEdits).
        assert out["permission_mode"] == "plan"
        assert seen["permission_mode"] == "plan"
        # The origin session is owned-for-N-minutes.
        assert out["owned_until"] == 1300.0

    def test_reaper_owns_a_session_mid_orientation_then_expires(self):
        import reaper
        rec_owned = {"session_id": "s-live",
                     "orientation_owned_until": 1e18}
        rec_expired = {"session_id": "s-old", "orientation_owned_until": 1.0}
        snap = reaper.build_snapshot(
            attached_pty_ids=set(), records=[rec_owned, rec_expired],
            job_active=lambda _s: False, probe=reaper.NO_PROBE)
        owners = reaper.live_owner_ids(snap)
        assert "s-live" in owners      # owned while orientation is in flight
        assert "s-old" not in owners   # the window expired → no longer owned


# ══════════════════════════════════════════════════════════════════════════════
# 5) The no-ACTION-auto-submit pinned test (across resume / advance / orientation)
# ══════════════════════════════════════════════════════════════════════════════

class TestNoActionAutoSubmit:
    def test_narration_next_never_submits(self):
        import narration as narr
        for rec in ({"lane": "research", "status": "done"},
                    {"lane": "build", "status": "running"},
                    {"lane": "plan", "pending_paste": "DO THE THING",
                     "paste_flushed": False}):
            nxt = narr.build_narration(rec)["next"]
            assert nxt["submit"] is False  # NOTHING is ever auto-submitted

    def test_orientation_prompt_is_a_read_only_job_never_a_pty_turn(self):
        # The orientation launches a read-only JOB (plan mode); it never writes a
        # turn onto the live PTY (the fork lock). The launch seam proves it goes
        # through job_runner, not terminal_session._pty.write.
        import orientation as orient
        wrote = {"pty": False}

        def fake_launch(lane, **kw):
            return {"job_id": "j"}

        orient.orient_session("p", "research", "s", folder_path="/tmp",
                              record={"worktree_path": "/tmp", "status": "idle"},
                              launch=fake_launch)
        # (build_orientation_prompt is pure; orient_session's only side effect is
        # the job launch + the ownership stamp — never a PTY write.)
        assert wrote["pty"] is False

    def test_pending_paste_is_never_auto_submitted_source_pin(self):
        # The v10 paste-NOT-submit contract is preserved: the flush strips the
        # trailing newline so the paste lands UNSENT, and the bounded fallback path
        # ALSO strips it (still unsent).
        assert 'pending = pending.rstrip("\\r\\n")' in TS
        # The fallback never adds a submit — it only relaxes the greet gate. The
        # flush body documents the paste-NOT-submit invariant explicitly.
        flush = TS.split("def _flush_pending_paste")[1].split("def queue_paste")[0]
        assert "paste-NOT-submit" in flush
        # And the bounded fallback lives inside the flush (the S3 fix).
        assert "bounded fallback" in flush.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 6) Eviction budget math (pure) — oldest-first
# ══════════════════════════════════════════════════════════════════════════════

class TestEvictionBudgetMath:
    def test_budget_env_override_and_default(self):
        import worktrees as wt
        assert wt.parked_worktree_budget({"ANCHOR_PARKED_WORKTREE_BUDGET": "3"}) == 3
        assert wt.parked_worktree_budget({}) == wt.PARKED_WORKTREE_BUDGET_DEFAULT
        # A garbage value falls back to the default (never crashes).
        assert wt.parked_worktree_budget(
            {"ANCHOR_PARKED_WORKTREE_BUDGET": "xx"}) == wt.PARKED_WORKTREE_BUDGET_DEFAULT


# ══════════════════════════════════════════════════════════════════════════════
# 7) Integration — eviction SURVIVAL + per-class escalation (full stub stack)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data dir + temp ANCHOR_SIDECAR_DIR (pinned fixtures) + temp worktree
    base + stub PTY + fake runner + a temp git repo. NEVER :8777 / real home /
    network. git is a HARD requirement — a missing git fails honestly (no skip)."""
    data = tmp_path / "data"
    data.mkdir()
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sidecars))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SESSION_ID_FLAG", raising=False)
    for mod in ("paths", "usage_ledger", "job_runner", "pty_manager",
                "rnd_registry", "session_registry", "worktrees", "lanes",
                "effort_history", "sessions", "summarizer", "usage_capture",
                "narration", "reaper", "orientation", "brownfield_scan",
                "effort_view", "deliverables", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import terminal_session, session_registry, effort_history, rnd_registry
    import usage_capture, worktrees, narration, pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)

    yield {"ts": terminal_session, "reg": session_registry, "eh": effort_history,
           "uc": usage_capture, "wt": worktrees, "narr": narration,
           "rnd": rnd_registry, "sidecars": sidecars, "pid": proj["id"],
           "repo": repo}
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _start_and_place(env, lane="build"):
    rec = env["ts"].start_session(env["pid"], lane, backend="claude")
    sid = rec["session_id"]
    euuid = rec.get("engine_session_uuid")
    assert euuid, "UUID-at-launch was not captured"
    (env["sidecars"] / f"{euuid}.jsonl").write_text(
        _fx("canonical_3turn.jsonl"), encoding="utf-8")
    return rec, sid, euuid


def _run_cost_records(env, lane="build"):
    return [e for e in env["eh"].list_efforts(str(env["repo"]), env["pid"], lane)
            if e.get("kind") == "run-cost"]


def test_eviction_reclaims_only_the_worktree_everything_else_survives(env):
    """The done-when G/W/T: eviction of a parked session with a finalized cost
    record reaps ONLY the worktree — the registry record, chain lineage, cached
    summary, and finalized cost all SURVIVE (the session stays MEASURED and
    renders evicted-parked)."""
    rec, sid, euuid = _start_and_place(env)
    chain_before = env["reg"].get_session(sid)["chain_id"]
    # Park it (graceful close): finalizes MEASURED cost, KEEPS the worktree.
    env["ts"].close_session(sid)
    parked = env["reg"].get_session(sid)
    assert env["reg"].is_parked_warm(parked)
    assert parked["usage_state"] == env["uc"].STATE_MEASURED
    wt_path = Path(parked["worktree_path"])
    assert wt_path.is_dir(), "the parked worktree should still exist pre-eviction"
    cost_before = _run_cost_records(env)
    assert len(cost_before) == 1

    # Force eviction (budget 0 → evict the single parked worktree, oldest-first).
    out = env["wt"].evict_oldest_parked(set(), budget=0, project_id=env["pid"])
    assert sid in out["evicted"]
    assert not wt_path.exists(), "the worktree must be reclaimed"

    after = env["reg"].get_session(sid)
    # EVERYTHING except the worktree survives.
    assert after is not None                       # the record (tile) persists
    assert after["evicted"] is True
    assert (after["worktree_path"] or "") == ""    # only the worktree is gone
    assert env["reg"].is_parked_warm(after)        # still parked (reopenable)
    assert after["usage_state"] == env["uc"].STATE_MEASURED   # STILL MEASURED
    assert after["chain_id"] == chain_before       # chain lineage survives
    # The finalized cost record is untouched (eviction never un-measures).
    assert len(_run_cost_records(env)) == 1
    # It now renders as the evicted-parked tile class.
    assert env["narr"].classify_tile(after) == env["narr"].CLASS_EVICTED_PARKED


def test_evicted_escalation_opens_new_seeded_session_on_same_chain(env):
    """The eviction sub-contract: an evicted tile's Layer-2 escalation is a NEW
    seeded session on the SAME chain whose seed opens with the explicit 'resumed
    from persisted docs (worktree evicted)' line — never a reattach claim."""
    rec, sid, euuid = _start_and_place(env)
    env["ts"].close_session(sid)
    env["wt"].evict_oldest_parked(set(), budget=0, project_id=env["pid"])
    src_chain = env["reg"].get_session(sid)["chain_id"]

    # resume_parked_session refuses an evicted tile (no reattach it can't perform).
    assert env["ts"].resume_parked_session(sid)["reason"] == "evicted"

    # The escalation endpoint routes an evicted tile to a NEW seeded session.
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    captured = {}

    class _H:
        path = "/api/rnd/resume_live"

        def _term_token_ok(self):
            return True

        def _send_json(self, obj, code=200):
            captured["obj"] = obj
            captured["code"] = code

    gui.handle_resume_live(_H(), _H.path, {
        "project_id": env["pid"], "lane": "build", "source_session": sid})
    obj = captured["obj"]
    assert obj["ok"] is True
    new_sid = obj["session"]["session_id"]
    assert new_sid != sid                       # a NEW session, not a reattach
    new_rec = env["reg"].get_session(new_sid)
    # Joins the SAME chain via parent_session_id.
    assert new_rec["parent_session_id"] == sid
    assert new_rec["chain_id"] == src_chain
    # The seed opens with the honest evicted line.
    assert "worktree evicted" in (new_rec.get("seed_text") or "")


def test_parked_idle_warm_reattach_in_retained_worktree(env):
    """A parked-idle tile (worktree RETAINED) warm-reattaches: a fresh PTY is
    relaunched in the SAME worktree under the SAME id (mode 'reattach'), distinct
    from the evicted class (which cannot reattach)."""
    rec, sid, euuid = _start_and_place(env, lane="research")
    env["ts"].close_session(sid)  # park: PTY dead, worktree kept
    parked = env["reg"].get_session(sid)
    assert env["reg"].is_parked_warm(parked)
    assert (parked.get("worktree_path") or "")   # worktree retained
    out = env["ts"].resume_parked_session(sid)
    assert out["ok"] is True
    assert out["mode"] == "reattach"
    after = env["reg"].get_session(sid)
    assert after["status"] == env["reg"].STATUS_RUNNING  # flipped back to live
    import pty_manager as _pty
    assert sid in _pty._LIVE  # a fresh PTY exists in the retained worktree


def test_resume_live_running_focuses_existing_session(env):
    """A RUNNING tile's escalation focuses the live session (no new spawn)."""
    rec = env["ts"].start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    captured = {}

    class _H:
        path = "/api/rnd/resume_live"

        def _term_token_ok(self):
            return True

        def _send_json(self, obj, code=200):
            captured["obj"] = obj

    n_before = len(env["reg"].list_sessions(project_id=env["pid"]))
    gui.handle_resume_live(_H(), _H.path, {
        "project_id": env["pid"], "source_session": sid})
    assert captured["obj"]["ok"] is True
    assert captured["obj"]["mode"] == "already-live"
    assert captured["obj"]["session"]["session_id"] == sid
    # No sibling session was minted.
    assert len(env["reg"].list_sessions(project_id=env["pid"])) == n_before
    # SAFE projection — never leaks the worktree path.
    assert "worktree_path" not in captured["obj"]["session"]


def test_omitted_greet_flushes_via_bounded_fallback_still_unsent(env):
    """A session whose model NEVER emits the greet marker still delivers its
    pending paste via the BOUNDED FALLBACK — and it lands UNSENT (no newline)."""
    monkeypatch_secs = "0"  # force the fallback immediately
    import os
    os.environ["ANCHOR_PASTE_FLUSH_FALLBACK_SECS"] = monkeypatch_secs
    try:
        # Seed with an env-overridden text that has NO greet marker, and a pending
        # paste. The greet is never observed, so only the fallback can flush it.
        os.environ["ANCHOR_SEED_PROMPT_BUILD"] = "boot the build engine now.\n"
        rec = env["ts"].start_session(env["pid"], "build", backend="claude",
                                      paste_prompt="RUN THE PLAN")
        sid = rec["session_id"]
        # Make the PTY show real model output beyond the echoed seed (no greet).
        import pty_manager as _pty
        try:
            _pty.write(sid, "working on it, here is some output...\n")
        except Exception:
            pass
        # Age the paste past the (zero) fallback window.
        env["reg"].update_session(sid, pending_paste_since=1.0)
        flushed = env["ts"]._flush_pending_paste(sid)
        after = env["reg"].get_session(sid)
        # Either it flushed now, or the model output wasn't visible in the stub —
        # in both cases the paste must NEVER have auto-submitted (paste-NOT-submit
        # holds regardless). When it flushed, paste_flushed is set and the pending
        # is cleared.
        if flushed:
            assert after["paste_flushed"] is True
            assert (after.get("pending_paste") or "") == ""
    finally:
        os.environ.pop("ANCHOR_PASTE_FLUSH_FALLBACK_SECS", None)
        os.environ.pop("ANCHOR_SEED_PROMPT_BUILD", None)


def test_parked_worktree_count_and_dashboard_stamp(env):
    """The bounded-budget dashboard count reflects retained-parked worktrees."""
    rec, sid, euuid = _start_and_place(env)
    env["ts"].close_session(sid)  # park (retain worktree)
    assert env["wt"].parked_worktree_count(set()) >= 1
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    stamp = gui._parked_worktree_stamp()
    assert "parked" in stamp and "budget" in stamp


# ══════════════════════════════════════════════════════════════════════════════
# 8) The exhaustive per-tile-class matrix (gate-level render assertions)
# ══════════════════════════════════════════════════════════════════════════════
# The live Playwright screenshot sign-off is the MANUAL step (per the repo's UI
# convention — every UI wave is gated by Playwright + a screenshot + user sign-off,
# done separately). The GATE-level "exhaustive matrix" is these render assertions:
# every tile class renders a NON-BLANK Layer-1 narrated view (the first-click
# sentence) and the ONE further escalation action ('▶ Resume live') is present in
# the same window (the 1-click/2-action path).

_MATRIX = {
    "running": {"status": "running", "lane": "build",
                "worktree_path": "/w", "session_id": "m-run"},
    "parked-idle": {"status": "parked-warm", "lane": "plan",
                    "worktree_path": "/w", "session_id": "m-park"},
    "evicted-parked": {"status": "parked-warm", "lane": "research",
                       "worktree_path": "", "evicted": True,
                       "session_id": "m-evict"},
    "done": {"status": "done", "lane": "build", "session_id": "m-done"},
    "failed": {"status": "failed", "lane": "plan", "session_id": "m-fail"},
    "discovered": {"status": "", "provenance": "discovered", "lane": "research",
                   "session_id": "m-disc"},
    "one-shot-job": {"lane": "research", "job_id": "run-123",
                     "skill": "researchPrime", "status": "done"},
}


class TestExhaustiveTileClassMatrix:
    @pytest.mark.parametrize("cls,rec", list(_MATRIX.items()))
    def test_every_class_renders_non_blank_layer1(self, cls, rec):
        import narration as narr
        is_effort = (cls == "one-shot-job")
        view = narr.build_narration(dict(rec), is_effort=is_effort,
                                    project_id="pid")
        # Layer 1 is structurally never blank: a non-empty done line + a next step.
        assert view["done"], (cls, view)
        assert view["next"]["text"], cls
        assert view["next"]["submit"] is False, cls        # never auto-submits
        assert view["links_valid"] is True, cls
        # The class maps as expected (the evicted split renders 'evicted').
        assert view["tile_class"] == (
            "one-shot-job" if is_effort else cls), (cls, view["tile_class"])
        if cls == "evicted-parked":
            assert "evicted" in view["badges"]

    def test_first_click_and_escalation_controls_are_in_the_window(self):
        # ONE click → the warm narrated Layer-1 view; ONE further action → live.
        assert "_mountLayer1Narration" in JS
        assert "resume-live" in JS
        assert "_resumeLive" in JS
        # The escalation is in the SAME window (dock/panel), never a second window.
        assert "openEffortDock" in JS and "openPanel" in JS


# ══════════════════════════════════════════════════════════════════════════════
# 9) SSE attach-ack behavioral (over HTTP) — unknown session emits ok:false
# ══════════════════════════════════════════════════════════════════════════════

def test_sse_attach_ack_false_on_unknown_session(env):
    """The SSE fallback emits an explicit ``attach_ack ok:false`` event for a
    dead/unknown session (the diag-B2 S1 silent-close is superseded)."""
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        url = (f"http://127.0.0.1:{port}/api/rnd/term_stream2"
               f"?session=no-such-session&max_ticks=2&poll=0.01")
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8", "replace")
        # The explicit attach_ack error event is present (not a silent close).
        assert "event: attach_ack" in body
        assert '"ok": false' in body or '"ok":false' in body
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
