"""The final review of the night of 2026-10-10 (reviews/final1010-anchor.md): the fixes it asked for, proven."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, link_check, skill_jobs  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402
from steward_cockpit import steward_routes as sr  # noqa: E402


def test_a_failed_integration_check_stops_the_stage_line_there():
    j = {"files": ["a.py"], "check": "pytest", "check_ok": True, "review": {"verdict": "PASS"},
         "integration_check_ok": False, "landed": False}
    assert code_jobs.stage_line(j) == "made → checked → reviewed → integration check failed"
    src = (ROOT / "steward_cockpit" / "code_jobs.py").read_text(encoding="utf-8")
    assert 'fields["integration_check_ok"] = ok is True' in src


def test_a_stopped_code_jobs_flag_is_left_alone(tmp_path):
    (tmp_path / ".ecgberht").mkdir()
    (tmp_path / ".ecgberht" / "code-jobs.json").write_text(json.dumps({"c1": {"id": "c1", "status": "stopped"}}))
    (tmp_path / ".ecgberht" / "attention.json").write_text(json.dumps({"state": "working", "reason": "x", "job": "c1"}))
    assert sc.clear_stale_job_flag(tmp_path) is None


def test_the_restart_check_counts_a_running_skill_job_and_none_starts_mid_drain(monkeypatch, tmp_path):
    class Alive:
        def poll(self):
            return None
    monkeypatch.setitem(skill_jobs._PROCS, "k-test", Alive())
    import job_runner
    monkeypatch.setattr(job_runner, "jobs_dir", lambda: tmp_path)
    try:
        assert "skill:k-test" in sr._running_job_ids()
    finally:
        skill_jobs._PROCS.pop("k-test", None)
    from steward_cockpit import maintenance
    monkeypatch.setattr(maintenance, "is_active", lambda: True)
    monkeypatch.setattr(skill_jobs, "validate", lambda argv: (True, ""))
    out = skill_jobs.start(str(tmp_path), ["node", "x.mjs"])
    assert out["ok"] is False and "draining" in out["error"]


def test_a_malformed_anchor_link_still_records_no_credential():
    out, _ = link_check.check_reply("[bad](http://localhost:99999/x?path=a&token=SECRET2)", ".", hosts={"localhost"})
    assert "SECRET2" not in out


def test_the_serving_size_limit_is_respected(tmp_path, monkeypatch):
    proj = tmp_path / "P"
    eff = proj / "E"
    eff.mkdir(parents=True)
    (eff / "ECGBERHT.md").write_text("# x", encoding="utf-8")
    big = eff / "big.pdf"
    big.write_bytes(b"%PDF")
    monkeypatch.setattr(link_check, "_project_folder", lambda pid: str(proj))
    real_stat = Path.stat

    def fake_stat(self, *a, **k):
        st = real_stat(self, *a, **k)
        if self.name == "big.pdf":
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                                   60 * 1024 * 1024, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
        return st
    monkeypatch.setattr(Path, "stat", fake_stat)
    assert link_check.check_route("/api/steward/deliverable-file?pid=p&dir=E&path=big.pdf") == "unavailable now"


def test_r2_a_start_is_counted_before_the_drain_question_and_a_refused_one_leaves_no_trace(monkeypatch, tmp_path):
    from steward_cockpit import maintenance
    seen = {}

    def active():
        seen["registered"] = any(isinstance(p, skill_jobs._Reserved) for p in skill_jobs._PROCS.values())
        return True
    monkeypatch.setattr(maintenance, "is_active", active)
    monkeypatch.setattr(skill_jobs, "validate", lambda argv: (True, ""))
    out = skill_jobs.start(str(tmp_path), ["node", "x.mjs"])
    assert out["ok"] is False and seen["registered"] is True
    assert not any(isinstance(p, skill_jobs._Reserved) for p in skill_jobs._PROCS.values())


def test_r2_a_stopped_skill_stays_registered_until_its_process_ends(monkeypatch, tmp_path):
    # 2026-10-10 lifetime parity: Stop ends the contained tree and SEES it gone (code_jobs._Run.end) before the record
    # says stopped - no taskkill, no stop recorded on hope; the run stays counted until its wait drops it
    ended = []

    class Proc:
        pid, returncode = 4242, None

        def poll(self):
            return self.returncode

        def kill(self):
            ended.append(self.pid)
            self.returncode = -1

        def wait(self, timeout=None):
            return self.returncode
    (tmp_path / ".ecgberht").mkdir()
    (tmp_path / ".ecgberht" / "skill-jobs.json").write_text(json.dumps({"k9": {
        "id": "k9", "status": "running", "started": "2026-10-10 10:00:00", "label": "k9", "argv": ["node", "x.mjs"],
        "log": ".ecgberht/skill-jobs/k9.log", "process": {"pid": 4242, "contained": False}}}), encoding="utf-8")
    monkeypatch.setitem(skill_jobs._PROCS, "k9", code_jobs._Run(Proc(), None))
    try:
        out = skill_jobs.stop(str(tmp_path), "k9", actor="John")
        assert out["ok"] and ended == [4242], out
        rec = skill_jobs.read_jobs(str(tmp_path))["k9"]
        assert rec["status"] == "stopped" and rec["stopped_by"] == "John" and rec["stop_requested"]
        assert rec["process"]["state"] == "ended" and rec["handoff"]["state"] == "needs_report"
        assert "k9" in skill_jobs._PROCS, "still counted by the restart check until its wait sees it end"
    finally:
        skill_jobs._PROCS.pop("k9", None)
    assert not hasattr(skill_jobs, "_kill_tree") and not hasattr(skill_jobs, "TIMEOUT_S")


def test_r2_an_encoded_credential_name_is_removed_from_a_malformed_link():
    out, _ = link_check.check_reply("[bad](http://localhost:99999/x?a=1&%74oken=SECRET3#f)", ".", hosts={"localhost"})
    assert "SECRET3" not in out and "a=1" in out


def test_r2_an_interrupted_turn_releases_its_reply_blocks():
    js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert '/turn interrupted|session ended|asleep|steward stopped/i.test(ev.text || "")) turnReplyBlocks = [];' in js


def test_r3_a_start_that_fails_after_its_reservation_gives_the_reservation_back(monkeypatch, tmp_path):
    from steward_cockpit import maintenance
    monkeypatch.setattr(maintenance, "is_active", lambda: False)
    monkeypatch.setattr(skill_jobs, "validate", lambda argv: (True, ""))
    import builtins
    real_open = builtins.open

    def failing_open(p, *a, **k):
        if str(p).endswith(".log"):
            raise PermissionError("denied")
        return real_open(p, *a, **k)
    monkeypatch.setattr(builtins, "open", failing_open)
    before = set(skill_jobs._PROCS)
    out = skill_jobs.start(str(tmp_path), ["node", "x.mjs"])
    assert out["ok"] is False and set(skill_jobs._PROCS) == before


def test_r4_a_record_that_cannot_be_written_launches_nothing(monkeypatch, tmp_path):
    # 2026-10-10 lifetime parity: the record is written BEFORE the launch (the code-job order), so a registry that
    # cannot be written means no process at all - never a child nobody owns that a kill then has to catch
    import sys as _sys
    from steward_cockpit import maintenance
    monkeypatch.setattr(maintenance, "is_active", lambda: False)
    monkeypatch.setattr(skill_jobs, "validate", lambda argv: (True, ""))
    monkeypatch.setattr(skill_jobs, "_write_job", lambda cdir, job: (_ for _ in ()).throw(OSError("disk full")))
    launched = []

    def never(*a, **k):
        launched.append(a)
        raise AssertionError("launched without a record")
    monkeypatch.setattr(code_jobs, "_popen_contained", never)
    before = set(skill_jobs._PROCS)
    out = skill_jobs.start(str(tmp_path), [_sys.executable, "-c", "import time; time.sleep(1.5)"])
    assert out["ok"] is False and "nothing started" in out["error"] and "disk full" in out["error"]
    assert launched == [] and set(skill_jobs._PROCS) == before
