"""codex-discipline Wave 2 S4 (2026-09-18) — the remaining holes.

STUB GATE for the last attribution slice. Behaviours only:

- a bare launch (no project passed) names the registered project at or above
  its cwd from the start: on its record, in its children's environment; the
  lane hooks (cost bridge, deliverable register) still key on what
  launch_guarded commissioned, so a bare launch never triggers them.
- "unknown" counts every spawn seen: a child the steward's own transcript names
  when it started it (Codex ``SubAgentActivity``; Claude's Agent result line)
  but whose file was not found is an ``unknown`` row until it appears.
- a Grok steward turn is an honest row: unpriced with its tokens, else unknown.
- the Codex adapter's minimal env carries the five attribution names through
  to the CLI child and still refuses any other extra key.
"""
import importlib
import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

STEWARD = "01a0ac59-ca5d-7832-9474-08a6afada25b"
CHILD_A = "01a0b5b6-10bc-7252-9e6f-db00746cf976"
CHILD_B = "01a0b5b7-2222-7252-9e6f-db00746cf977"
SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
GROK_SESSION = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    (tmp_path / "sidecars").mkdir()
    for mod in ("paths", "journal", "usage_ledger", "usage_index", "usage_capture",
                "job_runner", "rnd_registry", "session_registry", "sessions",
                "effort_history", "summarizer", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    project = tmp_path / "proj"
    effort = project / "planning" / "eff-1"
    effort.mkdir(parents=True)
    pid = rnd_registry.add_project("Attribution", str(project), scaffold=False)["id"]
    return {"pid": pid, "project": str(project), "effort": str(effort), "data": data,
            "codex": tmp_path / "codex-home" / "sessions", "sidecars": tmp_path / "sidecars"}


def _day_dir(root, days_ago=0):
    t = time.gmtime(time.time() - days_ago * 86400)
    d = Path(root) / time.strftime("%Y", t) / time.strftime("%m", t) / time.strftime("%d", t)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rollout(path, thread_id, parent=None, root_session=None, started="2026-09-18T12:00:00.000Z",
             spawned=(), totals=None, model="gpt-6-astra"):
    """A Codex rollout: the header (a child names its parent and root session),
    the SubAgentActivity items a steward writes when it starts children, and
    a cumulative token_count when usage is known."""
    src = {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1}}} if parent else None
    meta = {"timestamp": started, "type": "session_meta",
            "payload": {"id": thread_id, "parent_thread_id": parent, "session_id": root_session, "source": src}}
    lines = [json.dumps(meta)]
    for tid in spawned:
        for kind in ("started", "interacted"):
            lines.append(json.dumps({"timestamp": started, "type": "event_msg", "payload": {
                "type": "item_completed", "thread_id": thread_id,
                "item": {"type": "SubAgentActivity", "id": "call_x", "kind": kind, "agent_thread_id": tid}}}))
    if totals is not None:
        lines.append(json.dumps({"type": "turn_context", "payload": {"model": model}}))
        lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": totals, "output_tokens": 0, "total_tokens": totals}}}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── bare launches ─────────────────────────────────────────────────────────────

def test_a_bare_launch_names_its_project_from_the_start(env, monkeypatch):
    import job_runner as jr
    seen = {}

    class FakeProc:
        pid = 4321
        stdout = io.StringIO("")
        stdin = None
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kw):
        seen["env"] = kw.get("env") or {}
        return FakeProc()
    monkeypatch.setattr(jr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(jr, "_register_swarm_session", lambda *a, **k: None)
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "python -c pass")
    rec = None
    try:
        rec = jr.launch("research", cwd=env["effort"], prompt="hi", job_id="job-bare-1", backend="claude")
    except Exception:
        pass
    rec = rec or jr.load_record("job-bare-1") or {}
    assert rec.get("project_id") == env["pid"] and rec.get("folder_path") == env["project"]
    assert (rec.get("relaunch_spec") or {}).get("project_id") is None        # nothing commissioned it
    assert jr._commissioned(rec) is None
    e = seen.get("env") or {}
    assert e.get("ANCHOR_PROJECT_ID") == env["pid"] and e.get("ANCHOR_EFFORT_DIR") == env["effort"]


def test_a_bare_launch_never_triggers_the_lane_hooks_at_finalize(env, monkeypatch):
    """A finished bare job carries its resolved project, but the W3 cost bridge
    and Hook B's deliverable register fire only for a commissioned lane launch
    (the spec's project); an early record with no spec keeps its own field."""
    import effort_history as eh
    import job_runner as jr
    import deliverables_register as dreg
    registered = []
    monkeypatch.setattr(dreg, "register", lambda *a, **k: registered.append(a) or {"register": "written"})
    envelope = {"type": "result", "total_cost_usd": 0.42, "duration_ms": 5000,
                "usage": {"input_tokens": 100, "output_tokens": 200}}
    base = {"lane": "research", "status": "running", "started_at": 1.0, "exit_code": None, "session_id": None,
            "backend": "claude", "cost": None, "project_id": env["pid"], "folder_path": env["project"]}
    # resolved at launch, commissioned by nobody: no bridge, no register
    jr._write_record(dict(base, job_id="job-bare-2", relaunch_spec={"project_id": None, "folder_path": None}))
    jr._finalize("job-bare-2", 0, result_envelope=envelope)
    assert eh.load_effort(env["project"], env["pid"], "research", "job-bare-2") is None and registered == []
    # commissioned through launch_guarded (the spec names the project): both hooks
    jr._write_record(dict(base, job_id="job-lane-2", relaunch_spec={"project_id": env["pid"], "folder_path": env["project"]}))
    jr._finalize("job-lane-2", 0, result_envelope=envelope)
    assert eh.load_effort(env["project"], env["pid"], "research", "job-lane-2") is not None and len(registered) == 1
    # an early record without a spec, or whose spec omits the key, keeps its own field (the W3 behaviour)
    jr._write_record(dict(base, job_id="job-early-2"))
    jr._finalize("job-early-2", 0, result_envelope=envelope)
    assert eh.load_effort(env["project"], env["pid"], "research", "job-early-2") is not None
    jr._write_record(dict(base, job_id="job-early-3", relaunch_spec={"lane": "research"}))
    jr._finalize("job-early-3", 0, result_envelope=envelope)
    assert eh.load_effort(env["project"], env["pid"], "research", "job-early-3") is not None


def test_a_relaunched_bare_job_stays_named_and_uncommissioned(env, monkeypatch):
    """A REAL relaunch of an interrupted bare job: the new record names the
    project launch() resolved (launch_guarded no longer wipes it), nothing
    commissions it (no lane slot), and a commissioned spec still passes its
    project (Grok S4 F1, both reads)."""
    import job_runner as jr
    seen = []

    class FakeProc:
        pid = 4321
        stdout = io.StringIO("")
        stdin = None
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(jr.subprocess, "Popen", lambda argv, **kw: seen.append(kw.get("env") or {}) or FakeProc())
    monkeypatch.setattr(jr, "_register_swarm_session", lambda *a, **k: None)
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "python -c pass")
    jr._ACTIVE_LANE.clear()
    spec = {"lane": "research", "cwd": env["effort"], "prompt": "p", "backend": "claude", "gated": False,
            "permission_mode": "plan", "expected_artifacts": [], "env_keys": {}, "project_id": None, "folder_path": None}
    jr._write_record({"job_id": "job-int-1", "lane": "research", "status": jr.STATUS_INTERRUPTED, "backend": "claude",
                      "project_id": env["pid"], "folder_path": env["project"], "relaunch_spec": spec})
    out = jr.relaunch("job-int-1")
    assert out.get("ok") is True, out
    new = jr.load_record(out["job_id"])
    assert new["project_id"] == env["pid"] and new["folder_path"] == env["project"]      # named from the start
    assert jr._commissioned(new) is None and jr.lane_holder(env["pid"], "research") is None
    assert seen[-1].get("ANCHOR_PROJECT_ID") == env["pid"]
    jr._write_record({"job_id": "job-int-2", "lane": "research", "status": jr.STATUS_INTERRUPTED, "backend": "claude",
                      "project_id": env["pid"], "folder_path": env["project"],
                      "relaunch_spec": dict(spec, project_id=env["pid"], folder_path=env["project"])})
    out = jr.relaunch("job-int-2")
    assert out.get("ok") is True, out
    assert jr._commissioned(jr.load_record(out["job_id"])) == env["pid"]      # (the fake process exits at once, so no slot to hold)
    jr._ACTIVE_LANE.clear()


def test_a_worktree_outside_the_project_resolves_to_the_session_that_owns_it(env, monkeypatch, tmp_path):
    """A bare job whose cwd is a managed worktree (outside the project folder)
    names the project of the session that owns the worktree (Grok S4 F2)."""
    import session_registry as sr
    import usage_capture as uc
    wt = tmp_path / "worktrees" / "sess-1"
    (wt / "sub").mkdir(parents=True)
    assert uc.resolve_project(str(wt)) == (None, None)
    monkeypatch.setattr(sr, "list_sessions", lambda *a, **k: [{"session_id": "sess-1", "project_id": env["pid"],
                                                                "worktree_path": str(wt)}])
    assert uc.resolve_project(str(wt / "sub")) == (env["pid"], env["project"])
    assert uc.resolve_project(str(tmp_path / "elsewhere")) == (None, None)


def test_the_restart_rebuild_keys_lane_slots_on_the_commissioning_launch(env, monkeypatch):
    """After a dashboard restart the supervisor re-adopts running jobs into the
    lane slots. A live bare job (resolved project on its record, nothing
    commissioned) must not hold the project's lane or the folder-build lock
    (Grok S4 F2); a commissioned job still does."""
    import job_runner as jr
    import supervisor as sup
    monkeypatch.setattr(jr, "_pid_alive", lambda pid: True)
    jr._ACTIVE_LANE.clear()
    jr._FOLDER_BUILD.clear()
    base = {"status": jr.STATUS_RUNNING, "pid": 4242, "backend": "claude", "started_at": 1.0,
            "project_id": env["pid"], "folder_path": env["project"]}
    jr._write_record(dict(base, job_id="job-live-bare", lane="research", cwd=env["project"],
                          relaunch_spec={"project_id": None, "folder_path": None, "cwd": env["project"]}))
    jr._write_record(dict(base, job_id="job-live-build", lane=jr.BUILD_LANE, cwd=env["project"],
                          relaunch_spec={"project_id": None, "folder_path": None, "cwd": env["project"]}))
    jr._write_record(dict(base, job_id="job-live-lane", lane="plan", cwd=env["project"],
                          relaunch_spec={"project_id": env["pid"], "folder_path": env["project"], "cwd": env["project"]}))
    out = sup.InlineSupervisor().rebuild()
    assert jr.lane_holder(env["pid"], "research") is None and jr.lane_holder(env["pid"], jr.BUILD_LANE) is None
    assert env["project"] not in jr._FOLDER_BUILD
    assert jr.lane_holder(env["pid"], "plan") == "job-live-lane"
    assert out.get("lane_slots") == 1 if "lane_slots" in out else True
    jr._ACTIVE_LANE.clear()
    jr._FOLDER_BUILD.clear()


# ── the spawn list ────────────────────────────────────────────────────────────

def test_codex_spawned_names_the_children_the_steward_started(env):
    import usage_capture as uc
    d = _day_dir(env["codex"], days_ago=40)                                  # an old steward, found by name
    p = _rollout(d / ("rollout-2026-08-09T10-00-00-%s.jsonl" % STEWARD), STEWARD, spawned=(CHILD_A, CHILD_B, CHILD_A))
    assert uc.codex_spawned(STEWARD) == [CHILD_A, CHILD_B]
    assert uc.codex_spawned("01a0ffff-0000-7000-8000-000000000000") == []
    # the rollout grows: only the new bytes are scanned; a line still being written waits (Grok S4 F4)
    third = "01a0b5b8-3333-7252-9e6f-db00746cf978"
    with io.open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "SubAgentActivity", "kind": "started", "agent_thread_id": third}}}) + "\n")
        fh.write('{"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "SubAgentActivity", "kind": "started", "agent_thread_id": "01a0b5b9-4444')
    assert uc.codex_spawned(STEWARD) == [CHILD_A, CHILD_B, third]
    with io.open(p, "a", encoding="utf-8") as fh:
        fh.write('-7252-9e6f-db00746cf979"}}}\n')
    assert uc.codex_spawned(STEWARD) == [CHILD_A, CHILD_B, third, "01a0b5b9-4444-7252-9e6f-db00746cf979"]


def test_claude_spawned_names_the_agents_the_session_launched(env):
    import usage_capture as uc
    main = env["sidecars"] / (SESSION + ".jsonl")
    lines = [
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text",
                    "text": "Async agent launched successfully. (internal metadata)\nagentId: ad7a4792df5592e7a\noutput file: x"}]}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "no ids here"}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text",
                    "text": "Async agent launched successfully.\nagentId: ad7a4792df5592e7a (again)"}]}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "text",
                    "text": "John pasted a log with agentId: deadbeefdeadbeef1 in it"}]}}),   # user text never mints a row
    ]
    main.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert uc.claude_spawned(SESSION) == ["ad7a4792df5592e7a"]


def test_an_older_child_the_walk_missed_is_read_by_name_not_guessed(env):
    """The 3-day walk misses a child whose rollout sits in an old day folder; the
    steward's spawn list names it, so its rollout is found by name and read —
    a real figure, not an unknown placeholder."""
    import usage_capture as uc
    import usage_index as ui
    d = _day_dir(env["codex"])
    _rollout(d / ("rollout-2026-09-18T10-00-00-%s.jsonl" % STEWARD), STEWARD, spawned=(CHILD_A,))
    old = _day_dir(env["codex"], days_ago=20)
    _rollout(old / ("rollout-2026-08-29T10-05-00-%s.jsonl" % CHILD_A), CHILD_A, parent=STEWARD, root_session=STEWARD,
             started="2026-08-29T10:05:00.000Z", totals=777)
    assert uc.ingest_children(STEWARD, "chatgpt", project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"]) == 1
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1 and rows[0]["native_id"] == CHILD_A and rows[0]["usage_state"] == "unpriced" and rows[0]["tokens"] == 777
    assert uc.ingest_children(STEWARD, "chatgpt", project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"]) == 0


def test_a_spawn_seen_without_a_file_is_unknown_until_it_appears(env):
    import usage_capture as uc
    import usage_index as ui
    from steward_cockpit import steward_routes
    d = _day_dir(env["codex"])
    _rollout(d / ("rollout-2026-09-18T10-00-00-%s.jsonl" % STEWARD), STEWARD, spawned=(CHILD_A, CHILD_B))
    _rollout(d / ("rollout-2026-09-18T10-05-00-%s.jsonl" % CHILD_A), CHILD_A, parent=STEWARD, root_session=STEWARD,
             started="2026-09-18T10:05:00.000Z", totals=1000)
    uc.ingest_children(STEWARD, "chatgpt", project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"])
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert rows[CHILD_A]["usage_state"] == "unpriced" and rows[CHILD_A]["tokens"] == 1000
    assert rows[CHILD_B]["usage_state"] == "unknown" and rows[CHILD_B]["parent_id"] == STEWARD
    assert rows[CHILD_B]["engine_session_uuid"] is None                       # index-only until it appears
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["children"]["count"] == 2 and r["children"]["unknown"] == 1
    # the child's rollout appears: the placeholder is upgraded, never doubled
    _rollout(d / ("rollout-2026-09-18T10-06-00-%s.jsonl" % CHILD_B), CHILD_B, parent=STEWARD, root_session=STEWARD,
             started="2026-09-18T10:06:00.000Z", totals=250)
    uc.ingest_children(STEWARD, "chatgpt", project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"])
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 2 and {r["native_id"]: r["usage_state"] for r in rows}[CHILD_B] == "unpriced"
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["children"]["count"] == 2 and r["children"]["unknown"] == 0 and r["children"]["tokens"] == 1250


def test_a_placeholder_upgrades_when_its_file_turns_up_by_name(env):
    """The placeholder was written first; the child's rollout later appears in
    an OLD day folder (outside the walk) — the spawned loop reads it by name
    and the unknown row becomes a real one (Grok S4 F3)."""
    import usage_capture as uc
    import usage_index as ui
    d = _day_dir(env["codex"])
    _rollout(d / ("rollout-2026-09-18T10-00-00-%s.jsonl" % STEWARD), STEWARD, spawned=(CHILD_B,))
    uc.ingest_children(STEWARD, "chatgpt", project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"])
    assert ui.load_rows(env["pid"])[0]["usage_state"] == "unknown"
    old = _day_dir(env["codex"], days_ago=10)
    _rollout(old / ("rollout-2026-09-08T10-05-00-%s.jsonl" % CHILD_B), CHILD_B, parent=STEWARD, root_session=STEWARD,
             started="2026-09-08T10:05:00.000Z", totals=333)
    assert uc.ingest_children(STEWARD, "chatgpt", project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"]) == 1
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1 and rows[0]["usage_state"] == "unpriced" and rows[0]["tokens"] == 333


# ── Grok honesty ──────────────────────────────────────────────────────────────

def test_a_grok_steward_turn_is_an_honest_row(env, monkeypatch, tmp_path):
    import anchor_settings
    import usage_ledger as ul
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "grok", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    engine.cli = "grok"
    engine.session_id = GROK_SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    engine.turn_text = "Reviewed."
    engine._handle({"type": "result", "subtype": "success", "session_id": GROK_SESSION,
                    "usage": {"input_tokens": 400, "output_tokens": 100}, "total_cost_usd": None,
                    "duration_ms": 900}, engine.proc)
    entries = ul.ledger_entries(GROK_SESSION)
    assert len(entries) == 1
    e = entries[0]
    assert e["source"] == "steward-turn" and e["cli"] == "grok" and e["project_id"] == env["pid"]
    assert e["tokens"] == 500 and e["cost_usd"] is None and e["usage_state"] == "unpriced"
    # a turn that reported nothing is an unknown row, never a made-up figure
    engine.turn_text = "Again."
    engine._handle({"type": "result", "subtype": "success", "session_id": GROK_SESSION,
                    "total_cost_usd": None, "duration_ms": 400}, engine.proc)
    states = sorted(x["usage_state"] for x in ul.ledger_entries(GROK_SESSION))
    assert states == ["unknown", "unpriced"]


# ── the Codex adapter's minimal env ───────────────────────────────────────────

def test_the_codex_minimal_env_carries_the_attribution_ids_and_nothing_else_extra():
    import codex_adapter as ca
    clean = ca.subscription_only_env({
        "ANCHOR_PROJECT_ID": "p1", "ANCHOR_EFFORT_DIR": "C:/proj/eff", "ANCHOR_RECEIPTS_DIR": "C:/data/.anchor/receipts",
        "ANCHOR_JOB_ID": "job-7", "OPENAI_API_KEY": "secret", "ANCHOR_RUNNER_CMD": "C:/malicious/runner",
    })
    assert clean["ANCHOR_PROJECT_ID"] == "p1" and clean["ANCHOR_JOB_ID"] == "job-7"
    assert clean["ANCHOR_RECEIPTS_DIR"] == "C:/data/.anchor/receipts" and "ANCHOR_SESSION_ID" not in clean
    assert "OPENAI_API_KEY" not in clean and "ANCHOR_RUNNER_CMD" not in clean
    assert ca._minimal_env_verified(clean) is True
    assert ca._minimal_env_verified(dict(clean, UNDOCUMENTED_RUNTIME="1")) is False
    bare = ca.subscription_only_env({})
    assert not (set(bare) & ca.ATTRIBUTION_ENV_KEYS) and ca._minimal_env_verified(bare) is True
