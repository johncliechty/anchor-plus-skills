"""W1 of the night of 2026-10-09 (PLAN-OVERNIGHT-2026-10-09 v0.6): work a helper finishes lands - narrowly.
Exact declared outputs up to 80, the whole declaration validated (never cut short); git_safety.is_runtime_path called
(never edited) at inspection, after the check, at staging and before placement, so a steward's runtime records never
refuse a job and never enter its commit; a refusal names each file with the declaration line that would admit it, or
says it cannot be declared. Prospective acceptance on throwaway repositories, declarations recorded before each job."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from steward_cockpit import code_jobs  # noqa: E402
import test_execution_minimum_2026_10_07 as em  # noqa: E402

PASS = [sys.executable, "-c", "pass"]


class _StagingCoder(em._Coder):
    """A coder whose run also leaves a steward runtime record STAGED in the job's worktree."""
    def __init__(self, wt, staged=None, **kw):
        super().__init__(wt, **kw)
        self.staged = staged or {}

    def wake(self, fresh=False, seed=None):
        for name, text in self.staged.items():
            p = Path(self.wt, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            subprocess.run(["git", "-C", str(self.wt), "add", "-f", "--", name], check=True)
        return super().wake(fresh, seed)


def _run(tmp_path, monkeypatch, factory, outputs=None, check=PASS, gitignore=""):
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", em._json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    repo, cdir = em._git_repo(tmp_path / "repo"), tmp_path / "steward"
    if gitignore:
        (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True)
    cdir.mkdir()
    declared = list(outputs or [])                       # recorded before the job runs
    out = code_jobs.start(str(cdir), str(repo), "Render the report.", check, engine_factory=factory, outputs=outputs)
    assert out.get("ok"), out
    assert (code_jobs.read_jobs(str(cdir))[out["job"]].get("outputs") or []) == declared
    for _ in range(600):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return repo, j
        em._time.sleep(0.1)
    raise AssertionError("the job never finished")


def _head_files(repo):
    return subprocess.run(["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.split()


# ---- acceptance (prospective) ----

def test_a_script_made_pdf_lands_with_staged_runtime_records_and_an_ignored_strip_present(tmp_path, monkeypatch):
    factory = lambda wt: _StagingCoder(wt, staged={".ecgberht/delivery.json": "{}\n", "conversation-log.json": "[]\n"},
                                       tool_writes={"a.txt": "two\n"},
                                       stray={"out/report.pdf": "%PDF-1.4", "strip.json": "{\"as_of\": \"x\"}"})
    repo, job = _run(tmp_path, monkeypatch, factory, outputs=["out/report.pdf"], gitignore="strip.json\n.ecgberht/\n")
    assert job["landed"] is True, job["land_note"]
    assert job["review"]["verdict"] == "PASS"
    assert sorted(job["files"]) == ["a.txt", "out/report.pdf"]
    landed = _head_files(repo)
    assert "out/report.pdf" in landed and "a.txt" in landed
    assert not [f for f in landed if f.startswith(".ecgberht/") or f in ("conversation-log.json", "strip.json")]
    assert not (repo / ".ecgberht").exists() and not (repo / "strip.json").exists()
    kept = Path(job["kept_worktree"])                     # the runtime records are kept, never thrown away
    assert (kept / ".ecgberht" / "delivery.json").read_text(encoding="utf-8") == "{}\n"


def test_a_sixty_output_declaration_survives_commissioning_and_review_and_lands(tmp_path, monkeypatch):
    names = ["out/fig%02d.txt" % i for i in range(60)]
    factory = lambda wt: em._Coder(wt, tool_writes={"a.txt": "two\n"}, stray={n: n for n in names})
    repo, job = _run(tmp_path, monkeypatch, factory, outputs=names)
    assert job["landed"] is True, job["land_note"]
    assert sorted(job["files"]) == sorted(["a.txt"] + names)
    assert all((repo / n).read_text(encoding="utf-8") == n for n in names)


def test_an_undeclared_extra_file_is_refused_before_the_check_and_says_how_to_declare_it(tmp_path, monkeypatch):
    marker = tmp_path / "check-ran"
    check = [sys.executable, "-c", "open(r'%s','w').write('x')" % marker]
    factory = lambda wt: em._Coder(wt, tool_writes={"a.txt": "two\n"}, stray={"out/extra.pdf": "%PDF"})
    repo, job = _run(tmp_path, monkeypatch, factory, outputs=["out/report.pdf"], check=check)
    assert job["landed"] is False and job["unexpected"] == ["out/extra.pdf"]
    assert "declare it: --output out/extra.pdf" in job["land_note"]
    assert not marker.exists(), "refused before the check"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n" and not (repo / "out").exists()
    assert (Path(job["kept_worktree"]) / "out" / "extra.pdf").exists(), "the work is kept"


# ---- the declaration ----

def test_eighty_declared_outputs_are_accepted_and_eighty_one_are_refused_with_the_count():
    ok, why = code_jobs.declared_outputs(["o/%d.txt" % i for i in range(80)])
    assert why is None and len(ok) == 80
    ok, why = code_jobs.declared_outputs(["o/%d.txt" % i for i in range(81)])
    assert ok is None and "80" in why and "81" in why


def test_the_whole_declaration_is_validated_never_cut_short():
    paths = ["o/%d.txt" % i for i in range(50)] + ["../escape.txt"]
    ok, why = code_jobs.declared_outputs(paths)
    assert ok is None and "escape" in why


def test_a_hint_is_given_only_for_a_path_that_can_be_declared():
    assert code_jobs.declare_hint("out/a.pdf") == "declare it: --output out/a.pdf"
    for p in ("DELIVERABLES.md", "foreman.config.json", "journal/0001.md", "roadmap.json"):
        assert code_jobs.declare_hint(p).startswith("cannot be declared:"), p


def test_the_runtime_rule_is_the_existing_predicate_called_not_edited():
    import git_safety
    for p in (".ecgberht/x.json", ".anchor/y", "strip.json", "conversation-log.json", "settings.json",
              "rnd_registry.json", "steward-cockpit-state.json"):
        assert git_safety.is_runtime_path(p) and code_jobs._runtime(p) and code_jobs._runtime(p + " (ignored by git)")
    for p in ("DELIVERABLES.md", "journal/0001.md", "out/report.pdf"):
        assert not code_jobs._runtime(p)
