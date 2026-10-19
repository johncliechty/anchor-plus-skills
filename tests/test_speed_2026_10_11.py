"""John 2026-10-11 (#5 speed): the service was busy answering the same state polls again and again - usage figures
are reused for a few seconds, one state answer serves every asker for two seconds (a new engine event makes it fresh),
the heartbeat folder is listed again only when it changes, and each boot step says its own time."""
import time
from pathlib import Path

from steward_cockpit import steward_campaign as campaign, steward_routes as sr


def test_usage_figures_are_reused_for_a_few_seconds_and_a_callers_own_state_is_always_fresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sr, "_usage_rollup_fresh", lambda cdir, estate=None: calls.append(estate) or {"n": len(calls)})
    monkeypatch.setattr(sr, "_ROLLUP_CACHE", {})
    monkeypatch.setenv("ANCHOR_USAGE_ROLLUP_TTL_S", "15")
    assert sr._usage_rollup(str(tmp_path)) == {"n": 1}
    assert sr._usage_rollup(str(tmp_path)) == {"n": 1}, "reused"
    assert sr._usage_rollup(str(tmp_path), estate={"x": 1}) == {"n": 2}, "a caller's own engine state: fresh"
    monkeypatch.setenv("ANCHOR_USAGE_ROLLUP_TTL_S", "0")
    assert sr._usage_rollup(str(tmp_path)) == {"n": 3}, "0 turns the reuse off"


def test_one_state_answer_serves_every_asker_until_the_engine_says_something(tmp_path, monkeypatch):
    built = []
    monkeypatch.setattr(sr, "_state_with_usage", lambda eng, cdir: built.append(1) or {"busy": eng.busy, "n": len(built)})
    monkeypatch.setattr(campaign, "map_stamp", lambda cdir: "s")
    monkeypatch.setattr(sr, "_STATE_CACHE", {})
    monkeypatch.setenv("ANCHOR_STATE_TTL_S", "2")
    eng = type("E", (), {"seq": 5, "busy": False})()
    first = sr._state_cached(eng, str(tmp_path))
    first["n"] = 99                                   # a caller changing its copy never changes the shared answer
    assert sr._state_cached(eng, str(tmp_path))["n"] == 1 and len(built) == 1
    eng.seq = 6
    assert sr._state_cached(eng, str(tmp_path))["n"] == 2, "a new event: fresh"
    eng.busy = True
    assert sr._state_cached(eng, str(tmp_path))["n"] == 3, "busy changed: fresh"
    monkeypatch.setattr(campaign, "map_stamp", lambda cdir: "s2")
    assert sr._state_cached(eng, str(tmp_path))["n"] == 4, "a question written to disk: fresh"


def test_the_heartbeat_folder_is_listed_again_when_a_file_arrives(tmp_path):
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    assert campaign._heartbeat_names(tmp_path) == []
    time.sleep(0.05)
    beat = tmp_path / "heartbeat-r1-seat.json"
    beat.write_text("{}", encoding="utf-8")
    assert [p.name for p in campaign._heartbeat_names(tmp_path)] == [beat.name]
    beat.unlink()
    assert campaign._heartbeat_names(tmp_path) == []


def test_each_boot_step_says_its_time():
    src = (Path(__file__).resolve().parent.parent / "anchor_gui.py").read_text(encoding="utf-8")
    for label in ("job records", "terminal sessions", "worktree sweep", "zombie hunter"):
        assert "_boot_step(%r)" % label in src
