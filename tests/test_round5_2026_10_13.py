"""Round 5 (John 2026-10-13: "landing jobs ... seem to be a big issue"; "I'm okay having smaller jobs run on a model
below frontier (one tier down) and at a lower effort. How can we track/calibrate that ... Steward [is] in charge"):

- A job sized small runs its family's small tier from John's tiers.json, checked against what the family offers, on
  that job's engine only; a tier that cannot be resolved runs standard and says why.
- A small job that misses for a reason in the work says how to redo it at standard; an infrastructure miss does not.
- A failed check that tests a file the job was never asked to make says so plainly.
- A reading copy inherited unchanged from the base, beside Markdown the job changed, is remade - never delivered stale.
- A re-filing's time line counts from its claim, not from the first start (Book 1 v3: "1043 min in all").
- The ledger is handed to the Campaign steward after 10 finished jobs or 7 days; never when asleep; deduplicated.
- An oversized review refusal names the largest files."""
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from steward_cockpit import code_jobs as cj, code_job_handoff as ch, job_ledger, steward_engine as se
from tests.test_delegation_workflow_2026_10_10 import PASS, FAIL, await_job, git, project  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _tiers(tmp_path, monkeypatch, small):
    import model_policy
    monkeypatch.setattr(model_policy, "discover", lambda fam, **kw: CLAUDE if fam == "claude" else CATALOG)
    p = tmp_path / "tiers.json"
    p.write_text(json.dumps({"small": small}), encoding="utf-8")
    monkeypatch.setenv("ANCHOR_TIERS_FILE", str(p))
    return p


CLAUDE = ([{"model": "best", "efforts": ["low", "medium", "high", "xhigh", "max"]}], None)
CATALOG = ([{"model": "gpt-6.1-sol", "efforts": [{"effort": "high"}, {"effort": "max"}]},
            {"model": "gpt-6-luna", "efforts": [{"effort": "low"}, {"effort": "high"}]}], None)


def test_the_small_tier_resolves_for_claude_and_chatgpt_and_refuses_what_the_family_does_not_offer(tmp_path, monkeypatch):
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"},
                                   "chatgpt": {"model": "gpt-6-luna", "effort": "high"}})
    assert cj.small_tier("claude", discover=lambda fam: CLAUDE) == ({"family": "claude", "model": "sonnet", "effort": "high"}, None)
    sel, why = cj.small_tier("chatgpt", discover=lambda fam: CATALOG)
    assert sel == {"family": "chatgpt", "model": "gpt-6-luna", "effort": "high"} and why is None
    assert cj.small_tier("gemini")[0] is None
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "claude-sonnet-x", "effort": "high"},
                                   "chatgpt": {"model": "gpt-6-luna", "effort": "max"}})
    assert "not one of" in cj.small_tier("claude", discover=lambda fam: CLAUDE)[1]
    assert "has no 'max' effort" in cj.small_tier("chatgpt", discover=lambda fam: CATALOG)[1]
    _tiers(tmp_path, monkeypatch, {"chatgpt": {"model": "gpt-9", "effort": "high"}})
    assert "offers no model" in cj.small_tier("chatgpt", discover=lambda fam: CATALOG)[1]
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "ultra"}})
    assert "has no 'ultra' effort" in cj.small_tier("claude", discover=lambda fam: CLAUDE)[1]
    monkeypatch.setenv("ANCHOR_TIERS_FILE", str(tmp_path / "missing.json"))
    assert "could not be read" in cj.small_tier("claude", discover=lambda fam: CLAUDE)[1]


def test_the_engine_applies_the_tier_to_its_own_family_only():
    eng = SimpleNamespace(tier_override={"family": "claude", "model": "sonnet", "effort": "high"})
    base = {"family": "claude", "model": "best", "effort": "max", "command": "claude"}
    out = se.Engine._apply_tier(eng, "claude", base)
    assert out["model"] == "sonnet" and out["effort"] == "high" and out["selection_evidence"] == "small_tier"
    assert base["model"] == "best"                                  # never mutated in place
    assert se.Engine._apply_tier(eng, "chatgpt", dict(base, family="chatgpt"))["model"] == "best"   # failover
    assert se.Engine._apply_tier(SimpleNamespace(), "claude", base) is base


def test_a_small_job_records_its_tier_and_hands_it_to_its_engine(project, tmp_path, monkeypatch):
    root, workers, factory = project
    settings = ROOT / "nothing-is-written-here.json"
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    out = cj.start(root / "A", root / "B", "Produce result", PASS, engine_factory=factory, size="small")
    assert out["ok"], out
    assert workers[0].tier_override == {"family": "claude", "model": "sonnet", "effort": "high"}
    job = cj.read_jobs(root / "A")[out["job"]]
    assert job["size"] == "small" and job["tier"] == "small: sonnet high"
    workers[0].produce({"B/result.py": "answer = 42\n"})
    assert await_job(root / "A", out["job"])["landed"]
    assert not settings.exists()


def test_an_unresolvable_small_tier_runs_standard_and_says_why(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "nonsense", "effort": "high"}})
    out = cj.start(root / "A", root / "B", "Produce result", PASS, engine_factory=factory, size="small")
    assert out["ok"] and workers[0].tier_override is None
    assert cj.read_jobs(root / "A")[out["job"]]["tier"].startswith("standard (small unavailable: Claude model")


def test_size_and_escalates_are_validated_and_one_redo_per_missed_small_job(project, tmp_path, monkeypatch):
    root, workers, factory = project
    assert "small or standard" in cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, size="huge")["error"]
    assert "names a job id" in cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory,
                                        escalates="../x")["error"]
    assert "not a small-tier job" in cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory,
                                              escalates="20261013-070623-b2a758")["error"]
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    small = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, size="small")
    assert "still running" in cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory,
                                       escalates=small["job"])["error"]
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    await_job(root / "A", small["job"])
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, escalates=small["job"])
    job = cj.read_jobs(root / "A")[out["job"]]
    assert job["escalates"] == small["job"] and job["size"] == "standard" and job["tier"] == "standard"
    assert "already redone by %s" % out["job"] in cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory,
                                                           escalates=small["job"])["error"]


def test_a_small_job_that_fails_its_check_says_how_to_redo_it_at_standard(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    out = cj.start(root / "A", root / "B", "Produce result", FAIL, engine_factory=factory, size="small")
    workers[0].produce({"B/result.py": "answer = 42\n"})
    done = await_job(root / "A", out["job"])
    assert "small tier missed - start it again at standard with --escalates %s" % out["job"] in done["land_note"]


def test_only_a_miss_in_the_work_counts_against_the_small_tier():
    small = {"tier": "small: sonnet high", "id": "j"}
    assert cj.small_missed(small, {"check_ok": False}, "", "x")
    assert cj.small_missed(small, {"review": {"ok": True, "verdict": "FAIL"}}, "", "x")
    assert cj.small_missed(small, {}, "the coder crashed", "x")
    assert cj.small_missed(small, {}, "", "nothing changed")
    assert not cj.small_missed(small, {"review": {"ok": False, "error": "seat failed"}}, "", "x")
    assert not cj.small_missed(small, {}, "You've hit your session limit", "x")
    assert not cj.small_missed(small, {"landed": True, "check_ok": False}, "", "x")
    assert not cj.small_missed({"tier": "standard (small unavailable: x)"}, {"check_ok": False}, "", "x")
    assert not cj.small_missed(dict(small, status="stopped"), {"check_ok": False}, "", "x")


def test_a_failed_check_testing_a_receipt_nobody_asked_for_is_named(project, tmp_path):
    root, workers, factory = project
    check = [sys.executable, "-m", "zipfile", "-t", "B/build/evidence.zip"]
    out = cj.start(root / "A", root / "B", "Produce result", check, engine_factory=factory)
    workers[0].produce({"B/result.py": "answer = 42\n"})
    done = await_job(root / "A", out["job"])
    assert "the check names B/build/evidence.zip, which is not in the job's tree" in done["land_note"]
    job = {"check": 'python tools/check.py "B/out put.pdf" --strict', "outputs": ["B/out put.pdf"]}
    assert cj.check_names_absent(job, root) == ["tools/check.py", "B/out put.pdf"]   # declared or not: the fact only
    (root / "tools").mkdir()
    (root / "tools" / "check.py").write_text("", encoding="utf-8")
    assert cj.check_names_absent(job, root) == ["B/out put.pdf"]
    assert cj.check_names_absent({"check": "pytest -q"}, root) == []


def test_an_inherited_reading_copy_beside_changed_markdown_is_remade(project, monkeypatch):
    root, workers, factory = project
    (root / "B" / "report.md").write_text("# Old\n", encoding="utf-8")
    (root / "B" / "report.html").write_text("<p>Old</p>\n", encoding="utf-8")
    git(root, "add", "B/report.md", "B/report.html")
    git(root, "commit", "-qm", "old report")
    made = []
    real_run = subprocess.run
    def fake_run(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)               # git still runs
        out = Path(args[args.index("--html") + 1])
        out.write_text("<p>New</p>\n", encoding="utf-8")
        made.append(out.name)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    out = cj.start(root / "A", root / "B", "revise B/report.md", PASS, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    (wt / "B" / "report.md").write_text("# New\n", encoding="utf-8")
    monkeypatch.setattr(cj.subprocess, "run", fake_run)
    assert cj._make_reading_copies(job, wt) == ["B/report.html"] and made == ["report.html"]
    assert (wt / "B" / "report.html").read_text(encoding="utf-8") == "<p>New</p>\n"
    (wt / "B" / "report.html").write_text("<p>The worker's own</p>\n", encoding="utf-8")
    (wt / "B" / "report.md").write_text("# Newer\n", encoding="utf-8")
    assert cj._make_reading_copies(job, wt) == []                 # a copy the worker changed is its own
    assert (wt / "B" / "report.html").read_text(encoding="utf-8") == "<p>The worker's own</p>\n"


def test_an_inherited_copy_is_remade_when_a_figure_beside_its_markdown_changed(project):
    root, workers, factory = project
    (root / "B" / "report.md").write_text("# Same" + chr(10) + "![f](fig.png)" + chr(10), encoding="utf-8")
    (root / "B" / "report.pdf").write_bytes(b"%PDF-1.4 old")
    (root / "B" / "fig.png").write_bytes(b"old figure")
    git(root, "add", "B/report.md", "B/report.pdf", "B/fig.png")
    git(root, "commit", "-qm", "report")
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, outputs=["B/report.pdf"])
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    args = (job, wt, "B/report.pdf", wt / "B" / "report.pdf", wt / "B" / "report.md")
    assert not cj.inherited_stale(*args)
    (wt / "B" / "fig.png").write_bytes(b"new figure")
    assert cj.inherited_stale(*args)
    (wt / "B" / "fig.png").write_bytes(b"old figure")
    (wt / "B" / "fig2.png").write_bytes(b"a figure the document does not use")
    assert not cj.inherited_stale(*args)                                  # five r3 #3: only the images it names
    (wt / "assets").mkdir()
    (wt / "assets" / "chart.png").write_bytes(b"chart")
    (wt / "B" / "report.md").write_text("# Same" + chr(10) + "![f](fig.png)" + chr(10), encoding="utf-8")
    assert cj.copy_inputs(wt, "B/report.md") == ["B/report.md", "B/fig.png"]


def test_a_copy_anchor_made_is_made_again_when_the_check_redraws_a_figure(tmp_path):
    md = tmp_path / "doc" / "report.md"
    md.parent.mkdir()
    md.write_text("# R" + chr(10) + "![f](img/fig.png)" + chr(10), encoding="utf-8")
    pdf = tmp_path / "doc" / "report.pdf"
    pdf.write_bytes(b"%PDF made")
    fig = tmp_path / "doc" / "img" / "fig.png"
    fig.parent.mkdir()
    fig.write_bytes(b"figure")
    import os
    os.utime(md, (100, 100))
    os.utime(fig, (100, 100))
    os.utime(pdf, (200, 200))
    assert cj._newest_input(md, pdf, tmp_path) == 100
    os.utime(fig, (300, 300))                                             # the check redrew the figure
    assert cj._newest_input(md, pdf, tmp_path) == 300 > pdf.stat().st_mtime
    other = tmp_path / "doc" / "unrelated.png"
    other.write_bytes(b"x")
    os.utime(other, (900, 900))                                           # a file the document does not use
    assert cj._newest_input(md, pdf, tmp_path) == 300


def test_two_racing_redos_of_one_small_job_start_only_one(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    small = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, size="small")
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    await_job(root / "A", small["job"])
    real = cj.read_jobs
    calls = []
    def racing(cdir):
        out = dict(real(cdir))
        calls.append(1)
        if len(calls) > 1:                         # another redo was written between the check and the lock
            out["20990101-000000-abcdef"] = {"escalates": small["job"], "status": "running"}
        return out
    monkeypatch.setattr(cj, "read_jobs", racing)
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, escalates=small["job"])
    assert not out["ok"] and "already redone by 20990101-000000-abcdef" in out["error"]
    assert not any(p.name not in (small["job"],) for p in (tmp_path / "jobs").iterdir()
                   if p.is_dir() and p.name[:2] == "20" and p.name != small["job"])


def test_an_inherited_copy_beside_unchanged_markdown_is_left_alone(project):
    root, workers, factory = project
    (root / "B" / "report.md").write_text("# Same\n", encoding="utf-8")
    (root / "B" / "report.pdf").write_bytes(b"%PDF-1.4 old")
    git(root, "add", "B/report.md", "B/report.pdf")
    git(root, "commit", "-qm", "report")
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, outputs=["B/report.pdf"])
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    assert not cj.inherited_stale(job, wt, "B/report.pdf", wt / "B" / "report.pdf", wt / "B" / "report.md")


def test_a_refilings_time_line_counts_from_its_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    now = time.time()
    job = {"id": "j1", "attempt": 3, "attempts": [{"attempt": 1}, {"attempt": 2}], "steward_dir": "C:/x",
           "worker_birth": now - 18 * 3600, "worker_completed_at": now - 17.8 * 3600,
           "claim": {"at": now - 120}}
    line = cj.speed_line(job, tmp_path)
    assert line.startswith("re-filed: check, review and landing 2 min") and "in all" not in line
    row = json.loads((tmp_path / "jobs" / "speed.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["refiled"] and row["steward_dir"] == "C:/x" and row["minutes"] == 2.0   # its own minutes only
    first = cj.speed_line({"id": "j2", "worker_birth": now - 600, "worker_completed_at": now - 60}, tmp_path)
    assert first.startswith("10 min in all; worker 9 min")


class _Steward:
    def __init__(self, alive=True, ok=True):
        self._alive, self.ok, self.sent = alive, ok, []

    def alive(self):
        return self._alive

    def enqueue_job_result(self, ident, text):
        self.sent.append((ident, text))
        return {"ok": self.ok}


def _rows(tmp_path, n, status="done"):
    """n more jobs in the start index, each with its own record (as Anchor writes them)."""
    steward = tmp_path / "steward"
    path = steward / cj.JOBS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    with open(tmp_path / "jobs" / "jobs-index.jsonl", "a", encoding="utf-8") as f:
        for _ in range(n):
            jid = "j%d" % len(recs)
            recs[jid] = {"id": jid, "status": status}
            f.write(json.dumps({"job": jid, "steward_dir": str(steward), "at": time.time()}) + chr(10))
    path.write_text(json.dumps(recs), encoding="utf-8")


def test_the_ledger_goes_to_the_campaign_steward_after_ten_jobs_and_never_while_it_sleeps(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(job_ledger, "ledger_text", lambda: "LEDGER")
    monkeypatch.setattr(job_ledger, "_is_campaign", lambda eng: True)
    (tmp_path / "jobs").mkdir()
    eng = _Steward()
    assert not job_ledger.nudge(now=1000.0, engine=eng)                    # first sight starts the count at zero
    _rows(tmp_path, 9)
    _rows(tmp_path, 5, status="running")                                     # still at work: not counted yet
    assert not job_ledger.nudge(now=1001.0, engine=eng) and not eng.sent
    _rows(tmp_path, 1)
    asleep = _Steward(alive=False)
    assert not job_ledger.nudge(now=1002.0, engine=asleep) and not asleep.sent
    refused = _Steward(ok=False)
    assert not job_ledger.nudge(now=1003.0, engine=refused)                 # not accepted: the count stands
    assert job_ledger.nudge(now=1004.0, engine=eng)
    ident, text = eng.sent[0]
    assert ident == "attention:ledger:10"
    assert "LEDGER" in text and "at most ONE recommendation" in text and "Never change tiers.json" in text
    assert not job_ledger.nudge(now=1005.0, engine=eng) and len(eng.sent) == 1
    monkeypatch.setattr(job_ledger, "_is_campaign", lambda e: False)
    _rows(tmp_path, 10)
    other = _Steward()
    assert not job_ledger.nudge(now=1006.0, engine=other) and not other.sent       # only the Campaign steward


def test_the_campaign_stewards_own_tick_tries_the_ledger_hourly(monkeypatch):
    calls = []
    monkeypatch.setattr(job_ledger, "nudge_later", lambda engine=None: calls.append(engine))
    eng = SimpleNamespace(one_conversation=True, busy=True, queue=[], last_say=0, last_output=0, woke_at=0)
    se.Engine._idle_tick(eng, 10_000.0)
    se.Engine._idle_tick(eng, 10_100.0)
    se.Engine._idle_tick(eng, 13_700.0)
    assert calls == [eng, eng]
    plain = SimpleNamespace(one_conversation=False, busy=True, queue=[], last_say=0, last_output=0, woke_at=0)
    se.Engine._idle_tick(plain, 10_000.0)
    assert calls == [eng, eng]


def test_the_ledger_goes_after_seven_days_with_at_least_one_new_job(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    assert not job_ledger.due(5, {"rows": 5, "at": 0}, 8 * 86400)
    assert job_ledger.due(6, {"rows": 5, "at": 0}, 8 * 86400)
    assert not job_ledger.due(6, {"rows": 5, "at": 0}, 6 * 86400)
    assert not job_ledger.due(99, None, 0)


def test_an_oversized_review_names_its_largest_files(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "T")
    git(repo, "config", "user.email", "t@invalid")
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "base")
    (repo / "big.txt").write_text("line\n" * 50, encoding="utf-8")
    (repo / "small.txt").write_text("line\n" * 2, encoding="utf-8")
    git(repo, "add", "big.txt", "small.txt")
    git(repo, "commit", "-qm", "change")
    mod = (ROOT / "tools" / "review_diff.mjs").as_uri()
    r = subprocess.run(["node", "-e", "import(%r).then(m => console.log(m.largest(%r, 'HEAD~1', 'HEAD')))"
                        % (mod, str(repo))], capture_output=True, text=True)
    assert r.stdout.strip() == "; largest: big.txt (50 lines), small.txt (2 lines)", r.stderr
    src = (ROOT / "tools" / "steward_review.mjs").read_text(encoding="utf-8")
    assert "largest(repo, from, head)" in src and "one review reads ${MAX_DIFF} at most" in src


def test_the_stewards_rules_carry_the_round5_brief_rules_and_sizes():
    rules = se.WRITE_FOR_JOHN + se.DELEGATION_DUTY
    for words in ("The check tests the work", "never a receipt", "is Anchor's to make from the Markdown",
                  "Split a change of more than about 300 KB", "--size small", "--escalates",
                  "never edit tiers.json", "ft.py ledger"):
        assert words in rules, words


def test_the_cli_sends_size_and_escalates(monkeypatch, tmp_path):
    from tools import steward_code_job as cli
    sent = []
    monkeypatch.setattr(cli, "project_for", lambda cwd: ("fixture", "A"))
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b'{"ok":true}'
    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda request, **kw: sent.append(json.loads(request.data)) or Response())
    monkeypatch.setattr(sys, "argv", ["x", "start", "--repo", str(tmp_path), "--brief", "do it", "--check", "pytest",
                                      "--size", "small", "--escalates", "20261013-070623-b2a758"])
    cli.main()
    assert sent[-1]["size"] == "small" and sent[-1]["escalates"] == "20261013-070623-b2a758"


def test_the_first_finished_job_is_reported_after_seven_days_not_swallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(job_ledger, "ledger_text", lambda: "LEDGER")
    monkeypatch.setattr(job_ledger, "_is_campaign", lambda eng: True)
    (tmp_path / "jobs").mkdir()
    _rows(tmp_path, 1)                                                     # finished before the ledger ever looked
    eng = _Steward()
    assert not job_ledger.nudge(now=1000.0, engine=eng)
    assert job_ledger.nudge(now=1000.0 + 8 * 86400, engine=eng) and eng.sent[0][0] == "attention:ledger:1"


def test_a_redo_runs_standard_and_waits_while_the_small_job_is_refiled(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    small = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, size="small")
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    await_job(root / "A", small["job"])
    assert "runs at standard size" in cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, size="small",
                                               escalates=small["job"])["error"]
    jobs = cj.read_jobs(root / "A")
    assert "being re-filed" in cj._redo_refusal({**jobs, small["job"]: dict(jobs[small["job"]], finalizer_active=True)},
                                                small["job"])


def test_a_refiling_keeps_the_served_model_the_worker_reported(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    out = cj.start(root / "A", root / "B", "Produce result", FAIL, engine_factory=factory, size="small")
    workers[0].model_selection = {"model": "sonnet", "model_served": "claude-sonnet-5-5"}
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    first = await_job(root / "A", out["job"])
    assert first["model_served"] == "claude-sonnet-5-5"
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.recover(root / "A", out["job"], check=PASS)["ok"]
    done = await_job(root / "A", out["job"], attempt=2)
    assert done["landed"] and done["model_served"] == "claude-sonnet-5-5"


def test_a_reading_copy_is_made_again_when_integration_brings_a_newer_figure(project, monkeypatch):
    root, workers, factory = project
    (root / "B" / "fig.png").write_bytes(b"old figure")
    git(root, "add", "B/fig.png")
    git(root, "commit", "-qm", "figure")
    real_run = subprocess.run
    def fake_run(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)
        src = Path(args[2])
        out = Path(args[args.index("--html") + 1])
        fig = (src.parent / "fig.png").read_bytes().decode()
        out.write_text("<p>%s | %s</p>" % (src.read_text(encoding="utf-8").strip(), fig) + chr(10), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", fake_run)
    out = cj.start(root / "A", root / "B", "write B/report.md", PASS, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    (root / "B" / "fig.png").write_bytes(b"new figure")               # newer work lands while the job runs
    git(root, "add", "B/fig.png")
    git(root, "commit", "-qm", "newer figure")
    workers[0].produce({"B/report.md": "# Report ![f](fig.png)" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert done["landed"], done["land_note"]
    assert (root / "B" / "report.html").read_text(encoding="utf-8") == "<p># Report ![f](fig.png) | new figure</p>" + chr(10)
    assert done["anchor_copies"] == ["B/report.html"]


def _figure_project(root):
    (root / "B" / "fig.png").write_bytes(b"old figure")
    git(root, "add", "B/fig.png")
    git(root, "commit", "-qm", "figure")


def _newer_figure(root):
    (root / "B" / "fig.png").write_bytes(b"new figure")
    git(root, "add", "B/fig.png")
    git(root, "commit", "-qm", "newer figure")


def test_integration_never_overwrites_the_workers_own_copy_and_keeps_the_work(project):
    root, workers, factory = project
    _figure_project(root)
    out = cj.start(root / "A", root / "B", "write B/report.md and B/report.html", PASS, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    _newer_figure(root)
    workers[0].produce({"B/report.md": "# R ![f](fig.png)" + chr(10), "B/report.html": "<p>the worker's own</p>" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert not done["landed"] and "may be out of date" in done["land_note"] and "B/fig.png" in done["land_note"]
    assert not (root / "B" / "report.html").exists()


def test_a_remade_copy_identical_to_the_old_one_does_not_block_landing(project, monkeypatch):
    root, workers, factory = project
    _figure_project(root)
    real_run = subprocess.run
    def same_render(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)
        Path(args[args.index("--html") + 1]).write_text("<p>same</p>" + chr(10), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", same_render)
    out = cj.start(root / "A", root / "B", "write B/report.md", PASS, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    _newer_figure(root)
    workers[0].produce({"B/report.md": "# R ![f](fig.png)" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert done["landed"], done["land_note"]


def test_a_small_job_being_redone_is_not_refiled(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    small = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, size="small")
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    await_job(root / "A", small["job"])
    redo = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, escalates=small["job"])
    assert redo["ok"]
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    out = ch.recover(root / "A", small["job"], check=PASS)
    assert not out["ok"] and "being redone at standard by %s" % redo["job"] in out["error"]
    workers[1].produce({"B/result.py": "answer = 43" + chr(10)})          # the redo lands
    assert await_job(root / "A", redo["job"])["landed"]
    assert "or that redo landed" in ch.recover(root / "A", small["job"], check=PASS)["error"]


def test_a_redo_that_ended_unlanded_leaves_the_original_recoverable(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    small = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, size="small")
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    await_job(root / "A", small["job"])
    redo = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, escalates=small["job"])
    workers[1].produce({"B/result.py": "answer = 43" + chr(10)})
    await_job(root / "A", redo["job"])
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.recover(root / "A", small["job"], check=PASS)["ok"]
    assert await_job(root / "A", small["job"], attempt=2)["landed"]
    assert "running or landed" in ch.recover(root / "A", redo["job"], check=PASS)["error"]


def test_a_miss_at_the_integration_gates_counts_against_the_small_tier():
    small = {"tier": "small: sonnet high", "id": "j"}
    assert cj.small_missed(small, {"integration_check_ok": False}, "", "x")
    assert cj.small_missed(small, {"delta_review": {"ok": True, "verdict": "FAIL"}}, "", "x")
    assert not cj.small_missed(small, {"delta_review": {"ok": False, "error": "seat"}}, "", "x")


def test_the_result_the_steward_reads_names_the_tier_and_the_served_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    job = {"id": "j", "status": "done", "repo": "C:/r", "land_note": "not landed", "size": "small",
           "tier": "standard (small unavailable: no small tier for gemini)", "model_served": "gemini-x"}
    monkeypatch.setattr(cj, "stage_line", lambda j: "made")
    said = []
    monkeypatch.setattr(ch, "save_result", lambda cdir, j, text: said.append(text) or None)
    cj._materialize_report(tmp_path, job)
    text = said[0]
    assert "Tier: standard (small unavailable: no small tier for gemini); model served gemini-x." in text


def test_copy_inputs_read_figure_names_as_the_renderer_does(tmp_path):
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "plot one.png").write_bytes(b"x")
    (tmp_path / "doc" / "r.md").write_text("![p](plot%20one.png) ![q](<plot one.png>)", encoding="utf-8")
    assert "doc/plot one.png" in cj.copy_inputs(tmp_path, "doc/r.md")


def test_a_refiling_remakes_the_copy_an_earlier_attempt_made_when_its_check_rewrites_the_markdown(project, monkeypatch):
    root, workers, factory = project
    real_run = subprocess.run
    def render(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)
        src = Path(args[2])
        Path(args[args.index("--html") + 1]).write_text("<p>%s</p>" % src.read_text(encoding="utf-8").strip() + chr(10),
                                                         encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", render)
    out = cj.start(root / "A", root / "B", "write B/report.md", FAIL, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    workers[0].produce({"B/report.md": "first" + chr(10)})
    first = await_job(root / "A", out["job"])
    assert first["anchor_copies"] == ["B/report.html"] and not first["landed"]
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    fix = [sys.executable, "-c", "import time,pathlib; time.sleep(1.1); pathlib.Path('B/report.md').write_text('fixed\\n')"]
    assert ch.recover(root / "A", out["job"], check=fix)["ok"]
    done = await_job(root / "A", out["job"], attempt=2)
    assert done["landed"], done["land_note"]
    assert (root / "B" / "report.html").read_text(encoding="utf-8") == "<p>fixed</p>" + chr(10)


def test_copy_inputs_keep_an_encoded_hash_in_a_figure_name(tmp_path):
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "chart#1.png").write_bytes(b"x")
    (tmp_path / "doc" / "r.md").write_text("![c](chart%231.png)", encoding="utf-8")
    assert "doc/chart#1.png" in cj.copy_inputs(tmp_path, "doc/r.md")


def test_a_note_whose_save_was_lost_is_sent_again_word_for_word(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    texts = iter(["LEDGER ONE", "LEDGER TWO"])
    monkeypatch.setattr(job_ledger, "ledger_text", lambda: next(texts))
    monkeypatch.setattr(job_ledger, "_is_campaign", lambda eng: True)
    (tmp_path / "jobs").mkdir()
    _rows(tmp_path, 10)
    eng = _Steward()
    real = job_ledger._write_state
    calls = []
    def lose_the_final_save(rows, at, pending=None):
        calls.append(rows)
        if rows == 10 and pending is None:
            raise OSError("disk full")
        real(rows, at, pending)
    monkeypatch.setattr(job_ledger, "_write_state", lose_the_final_save)
    assert not job_ledger.nudge(now=1000.0, engine=eng)                  # sent, but its save was lost
    monkeypatch.setattr(job_ledger, "_write_state", real)
    assert job_ledger.nudge(now=2000.0, engine=eng)
    assert eng.sent[0] == eng.sent[1] and "LEDGER ONE" in eng.sent[1][1]  # same identity, same words: deduplicated
    assert not job_ledger.nudge(now=3000.0, engine=eng) and len(eng.sent) == 2


def test_placed_work_is_never_redone():
    jobs = {"s": {"tier": "small: sonnet high", "status": "failed", "placed": True}}
    assert "already landed" in cj._redo_refusal(jobs, "s")


def test_a_figure_swapped_with_its_old_timestamp_still_refreshes_anchors_copy(tmp_path, monkeypatch):
    import os
    import shutil
    doc = tmp_path / "B"
    doc.mkdir()
    (doc / "report.md").write_text("# R ![f](fig.png)", encoding="utf-8")
    (doc / "fig.png").write_bytes(b"old figure")
    renders = []
    def render(args, **kw):
        Path(args[args.index("--html") + 1]).write_text("<p>%d</p>" % len(renders), encoding="utf-8")
        renders.append(1)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", render)
    monkeypatch.setattr(cj, "inherited_stale", lambda *a: False)
    job = {"outputs": ["B/report.md", "B/report.html"]}
    made = []
    cj._make_reading_copies(job, tmp_path, made)
    assert made == ["B/report.html"] and len(renders) == 1
    new = tmp_path / "new.png"
    new.write_bytes(b"new figure")
    os.utime(new, (1, 1))                                       # older than everything: copy2 keeps it
    shutil.copy2(new, doc / "fig.png")
    cj._make_reading_copies(job, tmp_path, made)
    assert len(renders) == 2 and (doc / "report.html").read_text(encoding="utf-8") == "<p>1</p>"
    cj._make_reading_copies(job, tmp_path, made)
    assert len(renders) == 2                                    # unchanged inputs: not made again


def test_an_ignored_figure_made_by_the_job_refreshes_the_inherited_copy(project):
    root, workers, factory = project
    (root / ".gitignore").write_text("*.png" + chr(10), encoding="utf-8")
    (root / "B" / "report.md").write_text("# R ![f](fig.png)" + chr(10), encoding="utf-8")
    (root / "B" / "report.pdf").write_bytes(b"%PDF old")
    git(root, "add", ".gitignore", "B/report.md", "B/report.pdf")
    git(root, "commit", "-qm", "report")
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, outputs=["B/report.pdf", "B/fig.png"])
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    args = (job, wt, "B/report.pdf", wt / "B" / "report.pdf", wt / "B" / "report.md")
    assert not cj.inherited_stale(*args)
    (wt / "B" / "fig.png").write_bytes(b"a figure git ignores")
    assert cj.inherited_stale(*args)


def test_every_figure_of_a_large_document_is_an_input(tmp_path):
    (tmp_path / "r.md").write_text(" ".join("![f](f%d.png)" % i for i in range(300)), encoding="utf-8")
    inputs = cj.copy_inputs(tmp_path, "r.md")
    assert len(inputs) >= 301 and "f299.png" in inputs


def test_a_figure_redrawn_by_the_integration_check_refreshes_anchors_copy_before_the_last_review(project, monkeypatch):
    root, workers, factory = project
    (root / ".gitignore").write_text("*.png" + chr(10), encoding="utf-8")
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "ignore figures")
    real_run = subprocess.run
    def render(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)
        src = Path(args[2])
        fig = src.parent / "fig.png"
        Path(args[args.index("--html") + 1]).write_text(
            "<p>%s</p>" % (fig.read_bytes().decode() if fig.is_file() else "none") + chr(10), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", render)
    draw = [sys.executable, "-c", "import pathlib,subprocess; n = subprocess.run(['git','rev-list','--count','HEAD'],"
            "capture_output=True,text=True).stdout.strip(); pathlib.Path('B/fig.png').write_text('drawn at ' + n)"]
    out = cj.start(root / "A", root / "B", "write B/report.md", draw, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    (root / "B" / "notes.txt").write_text("newer" + chr(10), encoding="utf-8")   # newer work: the job integrates
    git(root, "add", "B/notes.txt")
    git(root, "commit", "-qm", "newer work")
    workers[0].produce({"B/report.md": "# R ![f](fig.png)" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert done["landed"], done["land_note"]
    html = (root / "B" / "report.html").read_text(encoding="utf-8")
    assert html.startswith("<p>drawn at ") and html != "<p>drawn at 2</p>" + chr(10)   # not the first check's figure


def test_a_check_that_redraws_the_figure_of_the_workers_own_copy_keeps_the_work(project):
    root, workers, factory = project
    (root / ".gitignore").write_text("*.png" + chr(10), encoding="utf-8")
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "ignore figures")
    draw = [sys.executable, "-c", "import pathlib; pathlib.Path('B/fig.png').write_text('redrawn')"]
    out = cj.start(root / "A", root / "B", "write B/report.md and its copy", draw, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    workers[0].produce({"B/report.md": "# R ![f](fig.png)" + chr(10), "B/fig.png": "drawn by the worker",
                        "B/report.html": "<p>the worker's copy</p>" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert not done["landed"] and "the check changed what B/report.html is made from" in done["land_note"]


def test_a_redo_waits_until_the_original_worker_is_confirmed_ended(project, tmp_path, monkeypatch):
    root, workers, factory = project
    _tiers(tmp_path, monkeypatch, {"claude": {"model": "sonnet", "effort": "high"}})
    small = cj.start(root / "A", root / "B", "x", FAIL, engine_factory=factory, size="small")
    workers[0].produce({"B/result.py": "answer = 42" + chr(10)})
    await_job(root / "A", small["job"])
    monkeypatch.setattr(ch, "observe", lambda job: {"state": "unknown"})
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, escalates=small["job"])
    assert not out["ok"] and "not confirmed ended (unknown)" in out["error"]


def test_an_inherited_copy_remade_after_its_check_redrew_the_figure_lands(project, monkeypatch):
    root, workers, factory = project
    (root / "B" / "report.md").write_text("# R ![f](fig.png)" + chr(10), encoding="utf-8")
    (root / "B" / "fig.png").write_bytes(b"old")
    (root / "B" / "report.html").write_text("<p>old</p>" + chr(10), encoding="utf-8")
    git(root, "add", "B/report.md", "B/fig.png", "B/report.html")
    git(root, "commit", "-qm", "report")
    real_run = subprocess.run
    def render(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)
        fig = Path(args[2]).parent / "fig.png"
        Path(args[args.index("--html") + 1]).write_text("<p>%s</p>" % fig.read_text() + chr(10), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", render)
    draw = [sys.executable, "-c", "import pathlib; pathlib.Path('B/fig.png').write_text('redrawn')"]
    out = cj.start(root / "A", root / "B", "tidy", draw, engine_factory=factory,
                   outputs=["B/report.html", "B/fig.png", "B/note.txt"])
    workers[0].produce({"B/note.txt": "a note" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert done["landed"], done["land_note"]
    assert (root / "B" / "report.html").read_text(encoding="utf-8") == "<p>redrawn</p>" + chr(10)


def test_a_copy_anchor_could_not_remake_never_lands(project, monkeypatch):
    root, workers, factory = project
    real_run = subprocess.run
    def render(args, **kw):
        if str(cj.READING_COPY_TOOL) not in [str(a) for a in args]:
            return real_run(args, **kw)
        Path(args[args.index("--html") + 1]).write_text("<p>first</p>" + chr(10), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cj.subprocess, "run", render)
    real_unlink = Path.unlink
    def locked(self, *a, **kw):
        if self.name == "report.html":
            raise PermissionError("open in another program")
        return real_unlink(self, *a, **kw)
    monkeypatch.setattr(Path, "unlink", locked)
    redraw = [sys.executable, "-c", "import pathlib; pathlib.Path('B/report.md').write_text('# changed by the check')"]
    out = cj.start(root / "A", root / "B", "write B/report.md", redraw, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    workers[0].produce({"B/report.md": "# R" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert not done["landed"] and "B/report.html could not be made again" in done["land_note"]


def test_a_locked_inherited_copy_beside_changed_markdown_never_lands(project, monkeypatch):
    root, workers, factory = project
    (root / "B" / "report.md").write_text("# Old" + chr(10), encoding="utf-8")
    (root / "B" / "report.html").write_text("<p>Old</p>" + chr(10), encoding="utf-8")
    git(root, "add", "B/report.md", "B/report.html")
    git(root, "commit", "-qm", "report")
    real_unlink = Path.unlink
    def locked(self, *a, **kw):
        if self.name == "report.html":
            raise PermissionError("open in another program")
        return real_unlink(self, *a, **kw)
    monkeypatch.setattr(Path, "unlink", locked)
    out = cj.start(root / "A", root / "B", "revise B/report.md", PASS, engine_factory=factory,
                   outputs=["B/report.md", "B/report.html"])
    workers[0].produce({"B/report.md": "# New" + chr(10)})
    done = await_job(root / "A", out["job"])
    assert not done["landed"] and "B/report.html could not be made again" in done["land_note"]
    assert (root / "B" / "report.md").read_text(encoding="utf-8") == "# Old" + chr(10)


def test_an_identical_remake_by_anchor_is_fresh_not_stale(project):
    root, workers, factory = project
    (root / "B" / "report.md").write_text("# Same" + chr(10), encoding="utf-8")
    (root / "B" / "report.html").write_text("<p>Same</p>" + chr(10), encoding="utf-8")
    git(root, "add", "B/report.md", "B/report.html")
    git(root, "commit", "-qm", "report")
    out = cj.start(root / "A", root / "B", "x", PASS, engine_factory=factory, outputs=["B/report.md", "B/report.html"])
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    (wt / "B" / "report.md").write_text("# Same" + chr(10) + chr(10), encoding="utf-8")   # a blank line: same page
    job["copy_prints"] = {"B/report.html": cj.inputs_print(wt, "B/report.md")}
    assert cj.stale_owned(job, wt, ["B/report.html"], ["B/report.md", "B/report.html"]) == []
    assert cj.stale_owned(job, wt, [], ["B/report.md"]) == ["B/report.html"]          # not Anchor's: stale


def test_an_owned_copy_unchanged_from_the_base_is_still_checked_against_its_inputs(tmp_path):
    (tmp_path / "B").mkdir()
    (tmp_path / "B" / "report.md").write_text("# R", encoding="utf-8")
    job = {"outputs": ["B/report.md", "B/report.html"], "copy_prints": {"B/report.html": "an older fingerprint"}}
    assert cj.stale_owned(job, tmp_path, ["B/report.html"], ["B/report.md"]) == ["B/report.html"]


def test_integration_resets_dirty_worktree_ecgberht_before_merge(project):
    """0042: a steward checkpoint committing .ecgberht/turn-timing.jsonl while the worktree engine also dirties it does not block git merge."""
    root, workers, factory = project
    (root / ".ecgberht").mkdir(exist_ok=True)
    (root / ".ecgberht" / "turn-timing.jsonl").write_text('{"turn": 1}\n', encoding="utf-8")
    git(root, "add", ".ecgberht/turn-timing.jsonl")
    git(root, "commit", "-qm", "track turn-timing")
    out = cj.start(root / "A", root / "B", "write B/result.py", PASS, engine_factory=factory)
    assert out["ok"]
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    # Main repo commits a newer .ecgberht/turn-timing.jsonl while worktree also dirties it
    (root / ".ecgberht" / "turn-timing.jsonl").write_text('{"turn": 1}\n{"turn": 2}\n', encoding="utf-8")
    git(root, "add", "-f", ".ecgberht/turn-timing.jsonl")
    git(root, "commit", "-qm", "steward cadence checkpoint")
    (wt / ".ecgberht").mkdir(exist_ok=True)
    (wt / ".ecgberht" / "turn-timing.jsonl").write_text('{"turn": 1}\n{"coder_turn": 99}\n', encoding="utf-8")
    workers[0].produce({"B/result.py": "answer = 42\n"})
    done = await_job(root / "A", out["job"])
    assert done["landed"], done["land_note"]


def test_reviewer_family_override_in_start_and_recover(project, monkeypatch):
    """0041: --reviewer overrides the Reviewer seat in start and recover while refusing self-review."""
    root, workers, factory = project
    # Self-review refused at start
    bad = cj.start(root / "A", root / "B", "write B/result.py", PASS, engine_factory=factory, coder="claude", reviewer="claude")
    assert not bad["ok"] and "must differ from coder family" in bad["error"]
    # Valid reviewer override saved on job
    out = cj.start(root / "A", root / "B", "write B/result.py", FAIL, engine_factory=factory, coder="claude", reviewer="gemini")
    assert out["ok"]
    job = cj.read_jobs(root / "A")[out["job"]]
    assert job["reviewer_family"] == "gemini"
    workers[0].produce({"B/result.py": "answer = 42\n"})
    await_job(root / "A", out["job"])
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    # Self-review refused at recover
    bad_rec = ch.recover(root / "A", out["job"], check=PASS, reviewer="claude")
    assert not bad_rec["ok"] and "is an author's family" in bad_rec["error"]
    # Valid reviewer override at recover
    ok_rec = ch.recover(root / "A", out["job"], check=PASS, reviewer="chatgpt")
    assert ok_rec["ok"]
    done = await_job(root / "A", out["job"], attempt=2)
    assert done["landed"] and done["reviewer_family"] == "chatgpt"


def test_snapshot_matches_candidate_commit_after_commit_manifest_interruption(project):
    """When _commit_manifest commits the candidate before a review crash, snapshot_matches accepts it without git reset."""
    root, workers, factory = project
    out = cj.start(root / "A", root / "B", "write B/result.py", PASS, engine_factory=factory)
    job = cj.read_jobs(root / "A")[out["job"]]
    wt = Path(job["worktree"])
    (wt / "B" / "result.py").write_text("answer = 42\n", encoding="utf-8")
    job["manifest"] = ["B/result.py"]
    pre_commit_snap = ch.snapshot(job)
    assert cj._commit_manifest(wt, job, ["B/result.py"]) == ""
    post_commit_snap = ch.snapshot(job)
    assert post_commit_snap["head"] != pre_commit_snap["head"]
    assert ch.snapshot_matches(job, post_commit_snap, pre_commit_snap) is True
    # Tampering with file content after commit is rejected
    (wt / "B" / "result.py").write_text("answer = 999\n", encoding="utf-8")
    assert ch.snapshot_matches(job, ch.snapshot(job), pre_commit_snap) is False


def test_orphaned_finalizer_does_not_hold_busy_repos_and_steward_may_write_cockpit_records(project, monkeypatch):
    """An orphaned finalizer drops from busy_repos(), and steward Write/Edit to DELIVERABLES.md/roadmap.json/strip.json is allowed during active jobs."""
    from steward_cockpit import steward_engine as se
    root, workers, factory = project
    out = cj.start(root / "A", root / "B", "write B/result.py", PASS, engine_factory=factory)
    assert cj._norm(root) in cj.busy_repos()
    # Simulate an active steward in root / "A"
    eng = se.Engine(str(root / "A"), fake=True)
    eng.fake = False
    eng.busy = True
    interrupted = []
    monkeypatch.setattr(eng, "_interrupt_turn_locked", lambda r: interrupted.append(r) or {"ok": True})
    monkeypatch.setattr(eng, "_wake_locked", lambda *a, **kw: (True, ""))
    # Writing DELIVERABLES.md, roadmap.json, strip.json is allowed even while a code job owns root
    for rec_file in ("DELIVERABLES.md", "roadmap.json", "strip.json", ".ecgberht/note.md"):
        assert eng._guard_turn({"name": "Write", "input": {"file_path": str(root / "A" / rec_file)}}) is False
    assert interrupted == []
    # Writing a source file in the busy repo IS still blocked
    assert eng._guard_turn({"name": "Write", "input": {"file_path": str(root / "B" / "app.py")}}) is True
    assert interrupted == ["one writer: a code job is working on that repository"]
    # When the job transitions to finishing and its finalizer dies (orphaned_finalizer=True), busy_repos() releases it
    cj._transition(root / "A", out["job"], ("running",), status="finishing", finalizer_active=True,
                   claim={"pid": 999999, "birth": 1.0})
    monkeypatch.setattr(ch, "orphaned_finalizer", lambda j: True)
    assert cj._norm(root) not in cj.busy_repos()


