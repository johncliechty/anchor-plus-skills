"""codex-discipline Wave 2 S3 (2026-09-17) — ids into children, skill seats under the effort.

STUB GATE for the third slice of John's rule ("the skills they call spawn
agents ... every one carries an ID that flows back up to the particular
project"). Behaviours only:

- the ids a child inherits by environment name (project, effort dir, job or
  engine session, where to drop receipts) are on a delegated job's environment,
  a steward's, and a terminal session's.
- a receipt file a trio seat dropped becomes one row through the seam: keyed by
  the seat's native session, attributed by the inherited ids (else by the folder
  it ran in), priced when the seat reported a charge, unpriced when only tokens,
  unknown when nothing; a seat under a worktree joins at the project folder; a
  steward's seats name it as parent (its own sweep, or the cockpit state for the
  effort at any sweep); the job or the recorded child wins on the same native
  session, at ingest and at read; a re-prompt is its own row; a consumed file is
  removed; a replay adds nothing.
- the rollup shows seats as a bucket beside jobs and children.
"""
import importlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
SEAT_A = "3f2c1b0a-9d8e-4c7b-8a6f-5e4d3c2b1a09"
SEAT_B = "01a0af74-186b-7262-b53e-ece8c5b956a7"
JOB_UUID = "6f5f2f1e-0d8e-4c7c-9a1b-2d3e4f5a6b7c"


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
                "effort_history", "summarizer", "effort_view", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    project = tmp_path / "proj"
    effort = project / "planning" / "eff-1"
    effort.mkdir(parents=True)
    pid = rnd_registry.add_project("Attribution", str(project), scaffold=False)["id"]
    return {"pid": pid, "project": str(project), "effort": str(effort), "data": data}


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _receipt(root, *, native=SEAT_A, family="claude", model="claude-fable-5-1", usage=None,
             cost=None, env_ids=None, cwd=None, name=None):
    root.mkdir(parents=True, exist_ok=True)
    body = {"at": "2026-09-17T20:00:00Z", "family": family, "model_served": model, "model_attested": True,
            "native_id": native, "usage": usage, "cost_usd": cost, "duration_ms": 1200,
            "cwd": cwd, "env": env_ids or {}}
    p = root / ((name or native or "r") + ".json")
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


# ── ids into children ─────────────────────────────────────────────────────────

def test_attribution_env_names_the_ids_a_child_inherits(env):
    import usage_capture as uc
    e = uc.attribution_env(project_id=env["pid"], effort_dir=env["effort"], job_id="job-9")
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and e["ANCHOR_EFFORT_DIR"] == env["effort"]
    assert e["ANCHOR_JOB_ID"] == "job-9" and "ANCHOR_SESSION_ID" not in e
    assert _same(e["ANCHOR_RECEIPTS_DIR"], str(env["data"] / ".anchor" / "receipts"))
    e = uc.attribution_env(session_id=SESSION)
    assert e["ANCHOR_SESSION_ID"] == SESSION and "ANCHOR_PROJECT_ID" not in e and "ANCHOR_EFFORT_DIR" not in e


def test_a_delegated_job_launches_with_the_ids_in_its_environment(env, monkeypatch):
    import job_runner as jr
    seen = {}

    class FakeProc:
        pid = 4321
        stdout = io.StringIO("")
        stdin = None

        def poll(self):
            return 0

    def fake_popen(argv, **kw):
        seen["env"] = kw.get("env") or {}
        return FakeProc()
    monkeypatch.setattr(jr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(jr, "_register_swarm_session", lambda *a, **k: None)
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "python -c pass")
    try:
        jr.launch("research", cwd=env["effort"], prompt="hi", job_id="job-env-1", backend="claude",
                  project_id=env["pid"], folder_path=env["project"])
    except Exception:
        pass                                                   # the fake process ends the launch early
    e = seen.get("env") or {}
    assert e.get("ANCHOR_PROJECT_ID") == env["pid"] and e.get("ANCHOR_EFFORT_DIR") == env["effort"]
    assert e.get("ANCHOR_JOB_ID") == "job-env-1" and e.get("ANCHOR_RECEIPTS_DIR")
    # a Codex job: the minimal env plus the ids (Grok S3 F3)
    monkeypatch.setattr(jr._codex, "subscription_only_env", lambda env=None: {"PATH": "x", "CODEX_HOME": "y"})
    import model_policy
    monkeypatch.setattr(model_policy, "resolve", lambda backend, settings=None: {
        "cli": "chatgpt", "model": "gpt-6-astra", "effort": "high", "reasoning_effort": "high", "source": "test"})
    seen.clear()
    out = Path(env["effort"]) / "out"
    out.mkdir()
    err = None
    try:
        jr.launch("research", cwd=env["effort"], output_dir=str(out), prompt="hi", job_id="job-env-2",
                  backend="chatgpt", permission_mode="plan", project_id=env["pid"], folder_path=env["project"])
    except Exception as exc:
        err = exc
    e = seen.get("env") or {}
    assert e.get("ANCHOR_JOB_ID") == "job-env-2" and e.get("ANCHOR_RECEIPTS_DIR") and e.get("PATH") == "x", err


def test_a_terminal_session_env_carries_the_ids(env):
    import terminal_session as ts
    e = ts._model_launch_env({"model": "x"}, project_id=env["pid"], session_id=SESSION)
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and _same(e["ANCHOR_EFFORT_DIR"], env["project"])
    assert e["ANCHOR_SESSION_ID"] == SESSION and e["ANCHOR_RECEIPTS_DIR"]
    e = ts._model_launch_env(None, project_id=env["pid"], session_id=SESSION)
    assert e["ANCHOR_PROJECT_ID"] == env["pid"]


def test_the_steward_process_env_carries_the_ids(env, monkeypatch, tmp_path):
    import anchor_settings
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "claude", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    e = engine._spawn_env()
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and e["ANCHOR_EFFORT_DIR"] == env["effort"]
    assert e["ANCHOR_RECEIPTS_DIR"] and "ANCHOR_SESSION_ID" not in e
    engine.session_id = SESSION                                  # a resumed steward names its session
    assert engine._spawn_env()["ANCHOR_SESSION_ID"] == SESSION


# ── seat receipts through the seam ────────────────────────────────────────────

def test_receipts_become_seat_rows_priced_unpriced_and_unknown(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"], "session_id": SESSION}
    _receipt(root, native=SEAT_A, family="claude", cost=0.37,
             usage={"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0}, env_ids=ids)
    _receipt(root, native="01a0b0c6-2222-7b50-a38b-b91aad842222", family="chatgpt", model="gpt-6-astra",
             usage={"input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 3, "reasoning_output_tokens": 1}, env_ids=ids)
    _receipt(root, native=SEAT_B, family="grok", model="grok-4.6-build", usage=None, env_ids=ids)
    assert uc.ingest_receipts() == 2                            # two seats reached a ledger doc; unknown stays index-only
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert set(rows) == {SEAT_A, "01a0b0c6-2222-7b50-a38b-b91aad842222", SEAT_B}
    a = rows[SEAT_A]
    assert a["source"] == "seat" and a["usage_state"] == "measured" and a["cost_usd"] == 0.37
    assert a["tokens"] == 1150 and a["cli"] == "claude" and a["parent_id"] == SESSION
    assert a["effort_dir"] == env["effort"]
    b = rows["01a0b0c6-2222-7b50-a38b-b91aad842222"]
    assert b["usage_state"] == "unpriced" and b["tokens"] == 13 and b["cli"] == "chatgpt"   # cached/reasoning are subsets
    assert rows[SEAT_B]["usage_state"] == "unknown" and rows[SEAT_B]["engine_session_uuid"] is None
    entry = ul.ledger_entries(SEAT_A)[0]                         # the seat's own engine session is its doc
    assert entry["model"] == "claude-fable-5-1" and entry["model_attested"] is True
    assert a["model"] == "claude-fable-5-1" and a["model_attested"] is True   # the cockpit's row too
    assert list(root.glob("*.json")) == []                       # consumed
    assert uc.ingest_receipts() == 0 and len(ui.load_rows(env["pid"])) == 3


def test_a_receipt_without_ids_attributes_by_the_folder_it_ran_in(env):
    import usage_capture as uc
    import usage_index as ui
    root = env["data"] / ".anchor" / "receipts"
    _receipt(root, native=SEAT_A, cwd=env["effort"], usage={"input_tokens": 5, "output_tokens": 5}, cost=0.01)
    _receipt(root, native=SEAT_B, cwd=str(Path(env["project"]).parent / "elsewhere"), usage={"input_tokens": 1, "output_tokens": 1}, name="outside")
    uc.ingest_receipts()
    rows = ui.load_rows(env["pid"])
    assert [r["native_id"] for r in rows] == [SEAT_A] and rows[0]["effort_dir"] == env["effort"] and rows[0]["parent_id"] is None
    assert list(root.glob("*.json")) == []                       # the unattributed one still reached the ledger and was consumed


def test_a_seat_under_a_worktree_joins_at_the_project_folder(env, tmp_path):
    """A job runs in a managed worktree outside the project; its seats carry that
    cwd as the effort dir. They join at the project folder, like the job
    (Grok S3 F6)."""
    import usage_capture as uc
    import usage_index as ui
    root = env["data"] / ".anchor" / "receipts"
    wt = str(tmp_path / "worktrees" / "job-1")
    _receipt(root, native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1}, cwd=wt,
             env_ids={"project_id": env["pid"], "effort_dir": wt, "job_id": "job-1"})
    uc.ingest_receipts()
    rows = ui.load_rows(env["pid"])
    assert rows[0]["effort_dir"] == env["project"] and rows[0]["parent_id"] == "job-1"


def test_any_sweep_names_a_stewards_seat_parent_from_the_cockpit_state(env, monkeypatch):
    """A job's or a terminal's sweep may consume a steward's seat receipt first;
    the parent comes from the cockpit state for that effort (Grok S3 F4)."""
    import usage_capture as uc
    import usage_index as ui
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "_read_state_entry",
                        lambda key: {"session_id": SESSION} if key == env["effort"] else {})
    root = env["data"] / ".anchor" / "receipts"
    _receipt(root, native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1},
             env_ids={"project_id": env["pid"], "effort_dir": env["effort"]})
    uc.ingest_receipts()                                          # no parent given
    assert ui.load_rows(env["pid"])[0]["parent_id"] == SESSION


def test_the_child_wins_on_the_same_native_session(env):
    """A Codex seat a Codex steward spawned is also one of its child threads
    (S2): one row, the child's (Grok S3 F5) — at ingest and at read."""
    import usage_capture as uc
    import usage_index as ui
    from steward_cockpit import steward_routes
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"], "session_id": SESSION}
    uc.ingest_usage(SESSION, "child-key", index_key="child:%s:%s" % (SESSION, SEAT_A), source="subagent",
                    native_id=SEAT_A, tokens=900, cost_usd=None, project_id=env["pid"],
                    folder_path=env["project"], effort_dir=env["effort"], cli="chatgpt", parent_id=SESSION)
    _receipt(root, native=SEAT_A, usage={"input_tokens": 800, "output_tokens": 100}, env_ids=ids)
    assert uc.ingest_receipts() == 0 and len(ui.load_rows(env["pid"])) == 1
    # the seat lands first (a job's sweep ran before the steward's turn ended): the read skips it
    _receipt(root, native=SEAT_B, usage={"input_tokens": 80, "output_tokens": 10}, env_ids=ids)
    uc.ingest_receipts()
    uc.ingest_usage(SESSION, "child-key-2", index_key="child:%s:%s" % (SESSION, SEAT_B), source="subagent",
                    native_id=SEAT_B, tokens=90, cost_usd=None, project_id=env["pid"],
                    folder_path=env["project"], effort_dir=env["effort"], cli="chatgpt", parent_id=SESSION)
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["children"]["count"] == 2 and r["children"]["tokens"] == 990
    assert r["seats"]["count"] == 0


def test_a_reprompted_seat_is_its_own_row(env):
    """The dispatcher can call a seat twice on one session (initial + schema
    re-prompt): two charges, two rows (Grok S3 F7)."""
    import usage_capture as uc
    import usage_index as ui
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"], "session_id": SESSION}
    _receipt(root, native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1}, env_ids=ids, name="first")
    p = _receipt(root, native=SEAT_A, cost=0.1, usage={"input_tokens": 4, "output_tokens": 1}, env_ids=ids, name="second")
    body = json.loads(p.read_text(encoding="utf-8"))
    body["kind"] = "schema_reprompt"
    p.write_text(json.dumps(body), encoding="utf-8")
    assert uc.ingest_receipts() == 2
    rows = ui.load_rows(env["pid"])
    assert sorted(r["key"] for r in rows) == ["seat:%s" % SEAT_A, "seat:%s:reprompt" % SEAT_A]
    assert abs(sum(r["cost_usd"] for r in rows) - 0.3) < 1e-9


def test_a_stewards_own_seats_name_it_as_parent(env):
    """A steward's process has no session id at spawn; its seats carry the effort
    dir, and the steward's sweep supplies the parent (Rabbit S3)."""
    import usage_capture as uc
    import usage_index as ui
    root = env["data"] / ".anchor" / "receipts"
    _receipt(root, native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1},
             env_ids={"project_id": env["pid"], "effort_dir": env["effort"]})
    _receipt(root, native=SEAT_B, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1},
             env_ids={"project_id": env["pid"], "effort_dir": str(Path(env["project"]) / "planning" / "eff-2")})
    uc.ingest_receipts(parent_session=SESSION, parent_effort=env["effort"])
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert rows[SEAT_A]["parent_id"] == SESSION and rows[SEAT_B]["parent_id"] is None


def test_the_job_wins_on_the_same_engine_session_at_ingest_and_at_read(env):
    import usage_capture as uc
    import usage_index as ui
    from steward_cockpit import steward_routes
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"]}
    # the job row exists first: the receipt is skipped at ingest
    uc.ingest_usage(JOB_UUID, "job-key", source="job", native_id="job-1", tokens=500, cost_usd=0.5,
                    project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"], cli="claude")
    _receipt(root, native=JOB_UUID, cost=0.5, usage={"input_tokens": 400, "output_tokens": 100}, env_ids=ids)
    assert uc.ingest_receipts() == 0 and len(ui.load_rows(env["pid"])) == 1
    # the receipt lands first (a steward's sweep ran before the job finalized): the read skips it
    _receipt(root, native=SEAT_B, cost=0.3, usage={"input_tokens": 40, "output_tokens": 10}, env_ids=ids)
    uc.ingest_receipts()
    uc.ingest_usage(SEAT_B, "job-key-2", source="job", native_id="job-2", tokens=50, cost_usd=0.3,
                    project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"], cli="claude")
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["jobs"]["count"] == 2 and r["jobs"]["reported_spend"] == 0.8
    assert r["seats"]["count"] == 0
    assert list(root.glob("*.json")) == []


def test_junk_receipt_files_are_removed(env):
    import usage_capture as uc
    root = env["data"] / ".anchor" / "receipts"
    root.mkdir(parents=True)
    (root / "junk.json").write_text('{"native_id": "x"', encoding="utf-8")
    uc.ingest_receipts()
    assert list(root.glob("*.json")) == []


# ── sweeps ────────────────────────────────────────────────────────────────────

def test_turn_end_sweeps_receipts(env, monkeypatch, tmp_path):
    import anchor_settings
    import usage_index as ui
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "chatgpt", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    engine.cli = "chatgpt"
    engine.session_id = SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    _receipt(env["data"] / ".anchor" / "receipts", native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1},
             env_ids={"project_id": env["pid"], "effort_dir": env["effort"]})
    engine.turn_text = "Reviewed."
    engine._handle({"type": "result", "subtype": "success", "session_id": SESSION,
                    "usage": {"input_tokens": 150, "output_tokens": 30, "cached_input_tokens": 90},
                    "total_cost_usd": None, "duration_ms": 2000}, engine.proc)
    rows = {r["source"]: r for r in ui.load_rows(env["pid"])}
    assert set(rows) == {"seat"} and rows["seat"]["native_id"] == SEAT_A
    assert rows["seat"]["parent_id"] == SESSION                  # the steward's own seat names it


def test_a_terminal_sessions_end_path_sweeps_receipts(env, monkeypatch):
    import session_registry as reg
    import usage_capture as uc
    import usage_index as ui
    _receipt(env["data"] / ".anchor" / "receipts", native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1},
             env_ids={"project_id": env["pid"], "effort_dir": env["effort"], "session_id": SESSION})
    monkeypatch.setattr(reg, "get_session", lambda sid: {"session_id": sid, "project_id": env["pid"], "backend": "claude"})
    monkeypatch.setattr(reg, "finalize_cost_once", lambda sid: True)
    monkeypatch.setattr(uc, "_stamp", lambda *a, **k: None)
    uc.finalize_session_usage("sess-1", project_id=env["pid"], lane="general", folder_path=env["project"])
    assert [r["native_id"] for r in ui.load_rows(env["pid"])] == [SEAT_A]


# ── the reader ────────────────────────────────────────────────────────────────

def test_rollup_shows_seats_beside_jobs_and_children(env):
    import usage_capture as uc
    from steward_cockpit import steward_routes
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"]}
    _receipt(root, native=SEAT_A, cost=0.37, usage={"input_tokens": 100, "output_tokens": 50}, env_ids=ids)
    _receipt(root, native=SEAT_B, family="grok", usage=None, env_ids=ids)
    uc.ingest_receipts()
    uc.ingest_usage("a1", "k1", source="job", native_id="j1", tokens=1000, cost_usd=0.5,
                    project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"], cli="claude")
    r = steward_routes._usage_rollup(env["effort"], estate={})
    seats = r["seats"]
    assert seats["count"] == 2 and seats["unknown"] == 1 and seats["tokens"] == 150
    assert seats["reported_spend"] == 0.37 and seats["cost_status"] == "partial"
    assert r["jobs"]["count"] == 1 and r["jobs"]["reported_spend"] == 0.5    # seats never leak into jobs
    assert r["children"]["count"] == 0 and r["total"]["tokens"] == 0
