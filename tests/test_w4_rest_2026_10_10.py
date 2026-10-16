"""W4 of the night of 2026-10-10 (the rest of PLAN-OVERNIGHT-2026-10-09 W4): the stage line for code jobs, forecasts
kept with their milestone and actual, and a stale flag cleared only when it names its job and that job stopped."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, forecasts  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402


def test_the_stage_line_says_how_far_a_job_got_in_order():
    assert code_jobs.stage_line({}) == "nothing made"
    j = {"files": ["a.py"], "check": "pytest", "check_ok": False}
    assert code_jobs.stage_line(j) == "made \u2192 check failed"
    j.update(check_ok=True, review={"verdict": "BLOCK"})
    assert code_jobs.stage_line(j) == "made \u2192 checked \u2192 review blocked (block)"
    j.update(review={"verdict": "PASS"}, landed=False)
    assert code_jobs.stage_line(j) == "made \u2192 checked \u2192 reviewed \u2192 not landed"
    j.update(landed=True, repo="C:/elsewhere")
    assert code_jobs.stage_line(j) == "made \u2192 checked \u2192 reviewed \u2192 landed"


def test_review_r1_the_final_candidates_integration_review_counts():
    j = {"files": ["a.py"], "check": "pytest", "check_ok": True, "review": {"verdict": "PASS"},
         "delta_review": {"verdict": "BLOCK"}, "landed": False}
    assert code_jobs.stage_line(j) == "made \u2192 checked \u2192 integration review blocked (block)"


def test_review_r1_a_skill_run_gets_no_coding_stages():
    assert code_jobs.stage_line({"skill": "Chekhov", "status": "done", "files": ["ch1.md"]}) == "Chekhov finished"
    assert code_jobs.stage_line({"skill": "Chekhov", "status": "failed"}) == "Chekhov failed"


def test_a_landed_anchor_job_says_waits_for_restart_until_the_build_carries_it(monkeypatch):
    j = {"files": ["a.py"], "check": "pytest", "check_ok": True, "review": {"verdict": "PASS"}, "landed": True}
    monkeypatch.setattr(code_jobs, "live_state", lambda job: "waits for a restart")
    assert code_jobs.stage_line(j).endswith("landed \u2192 waits for restart")
    monkeypatch.setattr(code_jobs, "live_state", lambda job: "live")
    assert code_jobs.stage_line(j).endswith("landed \u2192 live")


def _now():
    return time.mktime((2026, 10, 10, 14, 0, 0, 0, 0, -1))


def test_a_forecast_is_kept_once_per_change_and_its_actual_beside_it(tmp_path):
    now = _now()
    assert forecasts.note(tmp_path, "code:j1", "code_job", "about 14:30 (estimate: a typical code job here takes 30 min)", now=now)
    assert not forecasts.note(tmp_path, "code:j1", "code_job", "about 14:30 (estimate: a typical code job here takes 30 min)", now=now + 5)
    assert forecasts.note(tmp_path, "code:j1", "code_job", "about 14:45 (estimate - running longer than usual)", now=now + 600)
    (tmp_path / ".ecgberht" / "code-jobs.json").write_text(json.dumps({"j1": {"id": "j1", "finished": "2026-10-10T14:50:00"}}))
    assert forecasts.observe_finished(tmp_path, sc._job_epoch) == 1
    assert forecasts.observe_finished(tmp_path, sc._job_epoch) == 0, "an actual is recorded once"
    acc = forecasts.accuracy(tmp_path)
    assert len(acc) == 1 and acc[0]["text"].startswith("about 14:45") and acc[0]["error_min"] == 5.0
    assert acc[0]["basis"] == "typical"


def test_review_r1_a_stated_window_is_scored_as_a_window(tmp_path):
    forecasts.note(tmp_path, "skill:k1", "skill_job", "14:10-14:30 (its own estimate, given 13:55)", now=_now())
    (tmp_path / ".ecgberht" / "skill-jobs.json").write_text(json.dumps({"k1": {"id": "k1", "finished": "2026-10-10T14:20:00"}}))
    forecasts.observe_finished(tmp_path, sc._job_epoch)
    acc = forecasts.accuracy(tmp_path)
    assert acc[0]["error_min"] == 0.0 and acc[0]["basis"] == "own"


def test_a_no_basis_forecast_is_kept_but_never_scored(tmp_path):
    forecasts.note(tmp_path, "skill:k1", "skill_job", "no basis for an estimate yet (no finished run of this kind here to go by)")
    (tmp_path / ".ecgberht" / "skill-jobs.json").write_text(json.dumps({"k1": {"id": "k1", "finished": "2026-10-10T15:00:00"}}))
    forecasts.observe_finished(tmp_path, sc._job_epoch)
    assert forecasts.accuracy(tmp_path) == []


def test_review_r1_the_file_stays_bounded_and_keeps_every_unresolved_subject(tmp_path, monkeypatch):
    monkeypatch.setattr(forecasts, "MAX_BYTES", 4000)
    monkeypatch.setattr(forecasts, "KEEP_ROWS", 10)
    forecasts.note(tmp_path, "code:open", "code_job", "about 14:30", now=_now())
    for i in range(80):
        forecasts.note(tmp_path, "code:old%d" % i, "code_job", "about 14:%02d" % (i % 60), now=_now())
        forecasts._append(tmp_path, {"type": "actual", "subject": "code:old%d" % i, "actual_epoch": _now()})
    assert forecasts._path(tmp_path).stat().st_size <= 4000 + 4000
    assert "code:open" in forecasts.pending(tmp_path)
    assert (tmp_path / ".ecgberht" / "forecasts-archive.jsonl").exists()


def _flag(cdir, **kw):
    (cdir / ".ecgberht").mkdir(exist_ok=True)
    (cdir / ".ecgberht" / "attention.json").write_text(json.dumps(kw), encoding="utf-8")


def _jobs(cdir, name, **recs):
    (cdir / ".ecgberht").mkdir(exist_ok=True)
    (cdir / ".ecgberht" / name).write_text(json.dumps(recs), encoding="utf-8")


def test_a_flag_is_cleared_only_when_its_named_job_finished_or_was_stopped(tmp_path):
    _jobs(tmp_path, "code-jobs.json", live1={"id": "live1", "status": "running"}, done1={"id": "done1", "status": "done"},
          bad1={"id": "bad1", "status": "failed"})
    _flag(tmp_path, state="working", reason="a job")                      # names no job: never cleared here
    assert sc.clear_stale_job_flag(tmp_path) is None
    _flag(tmp_path, state="working", reason="a job", job="live1")         # its job still runs
    assert sc.clear_stale_job_flag(tmp_path) is None
    _flag(tmp_path, state="working", reason="a job", job="bad1")          # failed: left for the halt escalation
    assert sc.clear_stale_job_flag(tmp_path) is None
    _flag(tmp_path, state="working", reason="a job", job="ghost")         # no record: unknown is never "stopped"
    assert sc.clear_stale_job_flag(tmp_path) is None
    _flag(tmp_path, state="paused", reason="a job", job="done1")          # finished: cleared
    assert sc.clear_stale_job_flag(tmp_path)["state"] == "quiet"
    _flag(tmp_path, state="needs_you", reason="answer me", job="done1")   # not working/paused: never touched
    assert sc.clear_stale_job_flag(tmp_path) is None


def test_a_stopped_skill_flag_stays_while_its_process_lives(tmp_path):
    _jobs(tmp_path, "skill-jobs.json", k1={"id": "k1", "status": "stopped", "pid": os.getpid()})
    _flag(tmp_path, state="working", reason="skill", job="k1")
    assert sc.clear_stale_job_flag(tmp_path) is None, "stopped is recorded before the kill lands"
    _jobs(tmp_path, "skill-jobs.json", k1={"id": "k1", "status": "stopped", "pid": 999999})
    assert sc.clear_stale_job_flag(tmp_path)["state"] == "quiet"


def test_an_unreadable_job_record_never_clears(tmp_path):
    _flag(tmp_path, state="working", reason="x", job="done1")
    (tmp_path / ".ecgberht" / "code-jobs.json").write_text("{not json", encoding="utf-8")
    assert sc.clear_stale_job_flag(tmp_path) is None
