"""W2 of the night of 2026-10-08 (Grok's strict rule, kept): only the files the coder's tools recorded writing land -
plus a file the job named UP FRONT as its declared output (a render a script made), still reviewed; every exclusion
holds; every job is reviewed by another family, documents included; one line per kept job."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from steward_cockpit import code_jobs  # noqa: E402
import test_execution_minimum_2026_10_07 as em  # noqa: E402

PASS = [sys.executable, "-c", "pass"]


def _job(tmp_path, monkeypatch, coder_kw, outputs=None, name="repo"):
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", em._json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    repo, cdir = em._git_repo(tmp_path / name), tmp_path / ("steward-" + name)
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Render the report.", PASS, engine_factory=lambda wt: em._Coder(wt, **coder_kw),
                          outputs=outputs)
    if not out.get("ok"):
        return repo, out
    for _ in range(300):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return repo, j
        em._time.sleep(0.1)
    raise AssertionError("the job never finished")


def test_a_declared_output_a_script_wrote_lands_with_the_tool_written_files(tmp_path, monkeypatch):
    repo, job = _job(tmp_path, monkeypatch, {"tool_writes": {"a.txt": "two\n"}, "stray": {"out/report.pdf": "%PDF-1.4"}},
                     outputs=["out/report.pdf"])
    assert job["landed"] is True, job["land_note"]
    assert sorted(job["files"]) == ["a.txt", "out/report.pdf"] and job["review"]["verdict"] == "PASS"
    assert (repo / "out" / "report.pdf").read_text(encoding="utf-8") == "%PDF-1.4"


def test_an_undeclared_file_a_script_wrote_still_blocks_the_landing(tmp_path, monkeypatch):
    repo, job = _job(tmp_path, monkeypatch, {"tool_writes": {"a.txt": "two\n"}, "stray": {"out/other.pdf": "%PDF"}},
                     outputs=["out/report.pdf"])
    assert job["landed"] is False and job["unexpected"] == ["out/other.pdf"]
    assert not (repo / "out").exists() and (repo / "a.txt").read_text(encoding="utf-8") == "one\n"


@pytest.mark.parametrize("bad", ["../escape.txt", "C:/dev/x.txt", "/etc/x", ".ecgberht/state.json", "foreman.config.json",
                                 "strip.json", "out/*.pdf"])
def test_a_declared_output_is_a_plain_path_never_a_record_or_the_foreman_config(tmp_path, monkeypatch, bad):
    _, out = _job(tmp_path, monkeypatch, {"tool_writes": {"a.txt": "two\n"}}, outputs=[bad])
    assert out.get("ok") is False and "declared output" in out["error"]


def test_a_documents_only_job_is_reviewed_and_a_failed_review_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVIEW_VERDICT", "FAIL")
    repo, job = _job(tmp_path, monkeypatch, {"tool_writes": {"notes.md": "# notes\n"}})
    assert job["landed"] is False and "did not pass it" in job["land_note"] and job["review"]["verdict"] == "FAIL"
    assert not (repo / "notes.md").exists()


def test_a_kept_job_is_one_line_never_one_per_file():
    src = (ROOT / "steward_cockpit" / "code_jobs.py").read_text(encoding="utf-8")
    assert 'line = "**Anchor** · kept from code job %s (not landed): %s" % (job["id"], ", ".join(unlisted))' in src
    assert '"receipt:kept:%s:%s"' not in src
    assert "docs_only" not in src, "documents are reviewed like code"


def test_the_launcher_carries_declared_outputs():
    src = (ROOT / "tools" / "steward_code_job.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--output", action="append", default=[]' in src and "outputs=a.output" in src
    routes = (ROOT / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
    assert 'outputs=body.get("outputs") or []' in routes


def test_a_declared_output_made_by_the_check_lands(tmp_path, monkeypatch):
    """ChatGPT W1a r2: the coder edits the generator; the passing check renders the declared output."""
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", em._json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    repo, cdir = em._git_repo(tmp_path / "repo"), tmp_path / "steward-r"
    cdir.mkdir()
    render = [sys.executable, "-c", "import os; os.makedirs('out', exist_ok=True); open('out/report.html','w').write(open('a.txt').read())"]
    out = code_jobs.start(str(cdir), str(repo), "Render.", render, engine_factory=lambda wt: em._Coder(wt, tool_writes={"a.txt": "two\n"}),
                          outputs=["./out/report.html"])
    assert out["ok"], out
    for _ in range(300):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed"):
            break
        em._time.sleep(0.1)
    assert j["landed"] is True, j.get("land_note")
    assert (repo / "out" / "report.html").read_text(encoding="utf-8") == "two\n"
