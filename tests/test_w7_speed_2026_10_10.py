"""W7 of the night of 2026-10-10: the service answers fast under its own polling load. The live service took 35-170 s
for the home page and 300 s for a maintenance status because every poll redid work whose inputs had not changed:
the private homes resolved for every listed file, the deliverables rebuilt, every usage ledger and every job record
re-read. Each is now reused while its inputs are unchanged - and each test proves a change is still seen."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import provider_native  # noqa: E402
import usage_capacity  # noqa: E402
from steward_cockpit import steward_routes as sr  # noqa: E402


def test_the_private_guard_is_not_cached(monkeypatch, tmp_path):
    """review r1 BLOCKER: a cached home could miss a junction retargeted since - the guard resolves every call."""
    assert not hasattr(provider_native, "_HOMES_CACHE")
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert provider_native.private_account_path(str(tmp_path / ".claude" / "credentials.json"))
    assert not provider_native.private_account_path(str(tmp_path / "proj" / "notes.md"))


def test_a_new_home_redirect_is_seen_at_once(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "elsewhere"
    assert not provider_native.private_account_path(str(other / "auth.json"))
    monkeypatch.setenv("CODEX_HOME", str(other))
    assert provider_native.private_account_path(str(other / "auth.json"))


def _ledger(d, name, cli, tokens, when):
    p = d / name
    p.write_text(json.dumps({"entries": {"a": {"cli": cli, "tokens": tokens, "recorded_at": when}}}), encoding="utf-8")
    return p


def test_a_ledger_file_is_parsed_once_and_a_changed_one_again(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    iso = now.isoformat()
    p = _ledger(tmp_path, "one.json", "claude", 100, iso)
    sums, docs = usage_capacity._seen(str(tmp_path), now)
    assert docs == 1 and sums["claude"]["week_tokens"] == 100
    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    usage_capacity._seen(str(tmp_path), now)
    assert not opened, "an unchanged ledger is not re-read"
    p.write_text(json.dumps({"entries": {"a": {"cli": "claude", "tokens": 250, "recorded_at": iso}}}), encoding="utf-8")
    os.utime(p, ns=(time.time_ns(), time.time_ns() + 1_000_000))
    sums, _ = usage_capacity._seen(str(tmp_path), now)
    assert sums["claude"]["week_tokens"] == 250, "a changed ledger is read again"


def _job(d, jid, status):
    (d / (jid + ".json")).write_text(json.dumps({"job_id": jid, "status": status}), encoding="utf-8")


def test_running_job_ids_follow_the_records_and_reread_only_changes(monkeypatch, tmp_path):
    import job_runner
    monkeypatch.setattr(job_runner, "jobs_dir", lambda: tmp_path)
    sr._JOB_STATUS.clear()
    _job(tmp_path, "a", job_runner.STATUS_RUNNING)
    _job(tmp_path, "b", "done")
    (tmp_path / "a.gate.json").write_text("{}", encoding="utf-8")
    assert sr._running_record_ids(job_runner) == ["a"]
    reads = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (reads.append(self.name), real(self, *a, **k))[1])
    assert sr._running_record_ids(job_runner) == ["a"] and not reads
    time.sleep(0.01)
    _job(tmp_path, "a", "done")
    _job(tmp_path, "c", job_runner.STATUS_RUNNING)
    assert sr._running_record_ids(job_runner) == ["c"]
    (tmp_path / "c.json").unlink()
    assert sr._running_record_ids(job_runner) == [] and not any(k.endswith("c.json") for k in sr._JOB_STATUS)


def test_the_deliverables_answer_is_reused_until_the_register_changes(monkeypatch, tmp_path):
    cdir = tmp_path / "Effort"
    cdir.mkdir()
    (cdir / "ECGBERHT.md").write_text("# x\n", encoding="utf-8")
    reg = cdir / "DELIVERABLES.md"
    reg.write_text("| What | Where | Date | Step |\n|---|---|---|---|\n", encoding="utf-8")
    sr._DELIV_CACHE.clear()
    builds = []
    real = sr.campaign.read_deliverables
    monkeypatch.setattr(sr.campaign, "read_deliverables", lambda d: (builds.append(d), real(d))[1])
    qs = {"pid": "p", "dir": "Effort"}
    a, code = sr.handle_get(str(cdir), "deliverables", qs)
    b, _ = sr.handle_get(str(cdir), "deliverables", qs)
    assert code == 200 and a == b and len(builds) == 1
    b["items"] = ["mutated"]
    c, _ = sr.handle_get(str(cdir), "deliverables", qs)
    assert c == a, "a caller's change never reaches the cache"
    time.sleep(0.01)
    reg.write_text(reg.read_text(encoding="utf-8") + "| A | `a.md` | 2026-10-10 | 1 |\n", encoding="utf-8")
    sr.handle_get(str(cdir), "deliverables", qs)
    assert len(builds) == 2, "a changed register is rebuilt"
    monkeypatch.setattr(sr, "_DELIV_TTL", 0.0)
    sr.handle_get(str(cdir), "deliverables", qs)
    assert len(builds) == 3, "past the time limit it is rebuilt even unchanged"


def _effort_with_a_deliverable(tmp_path):
    cdir = tmp_path / "Effort"
    cdir.mkdir()
    (cdir / "ECGBERHT.md").write_text("# x\n", encoding="utf-8")
    (cdir / "report.md").write_text("# report\n", encoding="utf-8")
    (cdir / "DELIVERABLES.md").write_text("| What | Where | Date | Step |\n|---|---|---|---|\n"
                                          "| Report | `report.md` | 2026-10-10 | 1 |\n", encoding="utf-8")
    return cdir


def test_a_swapped_deliverable_is_rebuilt_and_rechecked_not_reoffered(monkeypatch, tmp_path):
    """review r1 MAJOR: an offered file replaced (same register, same map) must not be served from the cache."""
    cdir = _effort_with_a_deliverable(tmp_path)
    sr._DELIV_CACHE.clear()
    builds = []
    real = sr.campaign.read_deliverables
    monkeypatch.setattr(sr.campaign, "read_deliverables", lambda d: (builds.append(d), real(d))[1])
    qs = {"pid": "p", "dir": "Effort"}
    first, _ = sr.handle_get(str(cdir), "deliverables", qs)
    assert any(i.get("path") == "report.md" for i in first.get("items") or []), first
    sr.handle_get(str(cdir), "deliverables", qs)
    assert len(builds) == 1
    (cdir / "report.md").unlink()                                   # the file is replaced (here: removed and
    (cdir / "report.md").write_text("# a different file entirely\n", encoding="utf-8")   # written anew, new size)
    sr.handle_get(str(cdir), "deliverables", qs)
    assert len(builds) == 2, "a changed offered file forces a rebuild (its link is re-checked)"


def test_review_r2_a_private_home_that_now_resolves_elsewhere_forces_a_rebuild(monkeypatch, tmp_path):
    cdir = _effort_with_a_deliverable(tmp_path)
    sr._DELIV_CACHE.clear()
    builds = []
    real = sr.campaign.read_deliverables
    monkeypatch.setattr(sr.campaign, "read_deliverables", lambda d: (builds.append(d), real(d))[1])
    homes = [("a",)]
    monkeypatch.setattr(sr, "_private_stamp", lambda: homes[0])
    qs = {"pid": "p", "dir": "Effort"}
    sr.handle_get(str(cdir), "deliverables", qs)
    sr.handle_get(str(cdir), "deliverables", qs)
    assert len(builds) == 1
    homes[0] = ("b",)                                   # a junction retargeted: the homes resolve elsewhere now
    sr.handle_get(str(cdir), "deliverables", qs)
    assert len(builds) == 2


def test_review_r2_files_changed_while_links_were_checked_are_answered_but_never_kept(monkeypatch, tmp_path):
    cdir = _effort_with_a_deliverable(tmp_path)
    sr._DELIV_CACHE.clear()
    import deliverables_register as dr
    real = dr.reading_target
    swapped = {"done": False}

    def racing(it, **kw):
        out = real(it, **kw)
        if not swapped["done"]:
            swapped["done"] = True
            (cdir / "report.md").write_text("# replaced during the check, other size\n", encoding="utf-8")
        return out
    monkeypatch.setattr(dr, "reading_target", racing)
    sr.handle_get(str(cdir), "deliverables", {"pid": "p", "dir": "Effort"})
    assert not sr._DELIV_CACHE, "an answer whose files moved under its own check is never reused"


def test_the_cache_key_is_canonical_and_bounded(monkeypatch, tmp_path):
    """review r1 MAJOR: whitespace variants share one entry; the cache never grows past its bound."""
    cdir = _effort_with_a_deliverable(tmp_path)
    sr._DELIV_CACHE.clear()
    for d in ("Effort", " Effort", "Effort  "):
        sr.handle_get(str(cdir), "deliverables", {"pid": "p", "dir": d})
    assert len(sr._DELIV_CACHE) == 1
    monkeypatch.setattr(sr, "_DELIV_MAX", 3)
    for i in range(10):
        sr.handle_get(str(cdir), "deliverables", {"pid": "p%d" % i, "dir": "Effort"})
    assert len(sr._DELIV_CACHE) <= 3


def test_the_service_warms_the_job_status_at_start():
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert 'name="anchor-warm-job-status"' in src and "_sr_warm._running_job_ids" in src
