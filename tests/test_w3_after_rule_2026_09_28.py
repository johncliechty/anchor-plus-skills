"""W3 of the steward revision (2026-09-28): the after rule — the cockpit asks the engine to re-derive the line on the
events, and the server tick sweeps the records whose roadmap moved past the line's stamp (his Q1)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward_cockpit import horizon  # noqa: E402
from steward_cockpit import producer_handoff  # noqa: E402


def _record(d, seq_last, stamped=None, with_strip=True):
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> x\n", encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"roadmap_events": [{"seq": i, "kind": "step_create", "step_id": "s%d" % i} for i in range(1, seq_last + 1)],
                                                "roadmap_projection": [{"id": "s1", "name": "S1", "status": "active"}]}), encoding="utf-8")
    if with_strip:
        strip = {"human_wait": "none", "next_recommended": "x", "why_next": "y"}
        if stamped is not None:
            strip["horizon_source_seq"] = stamped
        (d / "strip.json").write_text(json.dumps(strip), encoding="utf-8")


def test_refresh_asks_the_engine_for_the_horizon_with_the_reason(tmp_path, monkeypatch):
    d = tmp_path / "p"
    _record(d, 3)
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        class R:
            stdout = json.dumps({"ok": True, "unchanged": False})
            stderr = ""
        return R()
    monkeypatch.setattr(horizon.subprocess, "run", fake_run)
    from steward_cockpit import engine_cli
    monkeypatch.setattr(engine_cli, "resolve", lambda: ("node", "cli.mjs"))
    out = horizon.refresh(str(d), "accepted", background=False)
    assert out == {"ok": True, "unchanged": False}
    assert seen["args"][2:] == ["update", "--project", str(d), "--horizon", "--horizon-reason", "accepted"]
    assert horizon.refresh(str(tmp_path / "nowhere"), "accepted", background=False) == {"ok": False, "error": "no_record"}


def test_stale_reads_the_stamp_against_the_roadmaps_last_seq(tmp_path):
    fresh, moved, never, nostrip = (tmp_path / n for n in ("fresh", "moved", "never", "nostrip"))
    _record(fresh, 5, stamped=5)
    _record(moved, 6, stamped=5)
    _record(never, 2)
    _record(nostrip, 4, with_strip=False)
    assert horizon.stale(str(fresh)) is False
    assert horizon.stale(str(moved)) is True
    assert horizon.stale(str(never)) is True, "a line never derived is stale"
    assert horizon.stale(str(nostrip)) is False, "no strip: nothing to write"


def test_the_tick_sweeps_only_the_stale_records_a_few_at_a_time(tmp_path):
    dirs = []
    for i in range(4):
        d = tmp_path / ("p%d" % i)
        _record(d, 3, stamped=(3 if i == 1 else 1))
        dirs.append(str(d))
    ran = []
    import threading
    done = threading.Event()

    def runner(d):
        ran.append(d)
        if len(ran) == 2:
            done.set()
    todo = horizon.sweep(dirs, runner=runner, limit=2)
    assert todo == [dirs[0], dirs[2]], "the fresh record is skipped; at most two per tick, in order"
    assert done.wait(5)
    assert ran == todo
    assert horizon.sweep([dirs[1]], runner=runner) == []


def test_a_refused_record_is_not_retried_until_its_plan_moves(tmp_path):
    d = tmp_path / "p"
    _record(d, 3)
    import threading
    done = threading.Event()
    ran = []

    def refusing(x):
        ran.append(x)
        done.set()
        return {"ok": False, "error": "no_horizon", "reason": "2 steps are active"}
    assert horizon.sweep([str(d)], runner=refusing) == [str(d)]
    assert done.wait(5)
    assert horizon.stale(str(d)) is False, "refused at seq 3: no retry on the next tick"
    assert horizon.sweep([str(d)], runner=refusing) == []
    _record(d, 4)
    assert horizon.stale(str(d)) is True, "the plan moved: try once more"
    horizon._note_refusal(str(d), {"ok": True})
    assert horizon.stale(str(d)) is True and horizon._REFUSED.get(horizon.os.path.normcase(horizon.os.path.normpath(str(d)))) is None
    # a failed SPAWN is not a refusal: the record stays stale and is retried (Grok W3)
    horizon._note_refusal(str(d), {"ok": False, "error": "horizon_failed", "message": "node missing"})
    assert horizon.stale(str(d)) is True


def test_one_sweep_at_a_time(tmp_path):
    d = tmp_path / "p"
    _record(d, 3)
    import threading
    gate = threading.Event()
    started = threading.Event()

    def slow(x):
        started.set()
        gate.wait(5)
        return {"ok": True}
    assert horizon.sweep([str(d)], runner=slow) == [str(d)]
    assert started.wait(5)
    assert horizon.sweep([str(d)], runner=slow) == [], "a sweep still inside its spawn: the tick starts none"
    gate.set()
    import time as _time
    for _ in range(50):
        if not horizon._SWEEP_RUNNING["on"]:
            break
        _time.sleep(0.05)
    assert horizon._SWEEP_RUNNING["on"] is False


def test_the_new_verbs_spawn_the_live_engine_never_the_vendored_bundle(tmp_path, monkeypatch):
    from steward_cockpit import engine_cli
    live = tmp_path / "Ecgberht" / "bin"
    live.mkdir(parents=True)
    (live / "ecgberht.mjs").write_text("// live", encoding="utf-8")
    monkeypatch.setenv("ECGBERHT_ROOT", str(tmp_path / "Ecgberht"))
    assert engine_cli.live_cli() == str(live / "ecgberht.mjs")
    deps = engine_cli.resolve()
    assert isinstance(deps, tuple) and deps[1] == str(live / "ecgberht.mjs")
    assert "vendor" not in deps[1]
    monkeypatch.setenv("ECGBERHT_ROOT", str(tmp_path / "nowhere"))
    # no live engine at the env root: the sibling checkout beside Anchor, else the refinement client's resolution
    got = engine_cli.live_cli()
    assert got is None or got.endswith("ecgberht.mjs")


def test_record_dirs_lists_the_root_and_its_efforts(tmp_path):
    root = tmp_path / "proj"
    _record(root, 1)
    _record(root / "peter", 1)
    (root / "notes").mkdir()
    assert horizon.record_dirs([str(root)]) == [str(root), str(root / "peter")]


def test_a_runs_end_refreshes_the_line_as_produced_or_stalled(tmp_path, monkeypatch):
    d = tmp_path / "p"
    _record(d, 2)
    calls = []
    monkeypatch.setattr(horizon, "refresh", lambda rd, reason="", background=True: calls.append((str(rd), reason)))
    monkeypatch.setattr(producer_handoff, "record_handoff", lambda *a, **k: {"ok": True, "skipped": True})
    producer_handoff.record_terminal({"job_id": "j1", "status": "done", "folder_path": str(d), "refinement_context": {"step_id": "s1"}})
    producer_handoff.record_terminal({"job_id": "j2", "status": "failed", "folder_path": str(d), "refinement_context": {"step_id": "s1"}})
    producer_handoff.record_terminal({"job_id": "j3", "status": "running", "folder_path": str(d)})
    assert calls == [(str(d), "produced"), (str(d), "stalled")]
