"""Round 4 (John 2026-10-12: "smooth, seamless and efficient ... why do we use commands that take minutes?"):
finished work always lands, and every engine knows the Foundry tools.

- A re-filing after a clean audit (coder proven ended) is not refused for the steward's own later edits - Book 1 v3
  was refused for its steward editing Book 1/AGENTS.md after the job ended. A write the re-filing's own check makes
  into the repository still refuses, and a job whose last audit was NOT clean keeps refusing.
- Git-ignored scratch nobody declared stays in the kept worktree and never refuses the deliverable (MBA job 66e90d:
  a hand-built browser profile, 2,292 ignored files); a declared output git ignores lands.
- The reviewer seat failing once is retried; failing twice names its real cause in plain words.
- The Foundry tools index rides every engine's rules; a broken index falls back to the reading copy.
- Every finished job carries a plain time line."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from steward_cockpit import code_jobs as cj, code_job_handoff as ch, foundry_tools
from tests.test_delegation_workflow_2026_10_10 import PASS, FAIL, await_job, git, project  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _first_attempt_unlanded(root, workers, factory, check=FAIL, **kw):
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", check, engine_factory=factory, **kw)
    assert out["ok"], out
    workers[0].produce({"B/result.py": "answer = 42\n"})
    done = await_job(cdir, out["job"])
    assert not done["landed"]
    return cdir, out["job"], done


def _steward_edits_its_instructions(root):
    (root / "B" / "AGENTS.md").write_text("A rule the steward added after the job ended.\n", encoding="utf-8")
    git(root, "add", "B/AGENTS.md")
    git(root, "commit", "-qm", "steward checkpoint")


def test_a_refiling_after_a_clean_audit_lands_despite_the_stewards_later_instruction_edit(project, monkeypatch):
    root, workers, factory = project
    cdir, jid, first = _first_attempt_unlanded(root, workers, factory)
    assert cj.audit_clean(first) and "changed during the job" not in first["land_note"]
    _steward_edits_its_instructions(root)             # Book 1 v3: c10cf46 edited Book 1/AGENTS.md after the job
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.recover(cdir, jid, check=PASS)["ok"]
    done = await_job(cdir, jid, attempt=2)
    assert done["landed"], done["land_note"]
    assert (root / "B" / "result.py").read_text(encoding="utf-8") == "answer = 42\n"
    assert done["audit_from"]["head"] and not done.get("served_tree_changed")


def test_a_refilings_own_check_writing_into_the_repository_still_refuses(project, monkeypatch):
    root, workers, factory = project
    cdir, jid, _ = _first_attempt_unlanded(root, workers, factory)
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    target = (root / "B" / "AGENTS.md").as_posix()
    sneaky = [sys.executable, "-c", "open(%r, 'w').write('written by the check')" % target]
    assert ch.recover(cdir, jid, check=sneaky)["ok"]
    done = await_job(cdir, jid, attempt=2)
    assert not done["landed"] and "changed during the job" in done["land_note"], done["land_note"]


def test_a_job_whose_last_audit_was_not_clean_keeps_refusing(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", PASS, engine_factory=factory)
    (root / "B" / "AGENTS.md").write_text("written into the repository while the coder ran\n", encoding="utf-8")
    workers[0].produce({"B/result.py": "answer = 42\n"})
    first = await_job(cdir, out["job"])
    assert not first["landed"] and first.get("served_tree_changed") and not cj.audit_clean(first)
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    assert ch.recover(cdir, out["job"], check=PASS)["ok"]
    done = await_job(cdir, out["job"], attempt=2)
    assert not done["landed"] and "changed during the job" in done["land_note"]


def _ignore(root, *patterns):
    (root / ".gitignore").write_text("\n".join(patterns) + "\n", encoding="utf-8")
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "ignore rules")


def test_ignored_scratch_nobody_declared_stays_behind_and_the_deliverable_lands(project):
    root, workers, factory = project
    _ignore(root, "scratch/")
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", PASS, engine_factory=factory)
    w = workers[0]
    for i in range(30):                                # a hand-built browser profile, written by a command
        p = w.wt / "B" / "scratch" / "profile" / ("f%d.dat" % i)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    w.produce({"B/result.py": "answer = 42\n"})
    done = await_job(cdir, out["job"])
    assert done["landed"], done["land_note"]
    assert (root / "B" / "result.py").is_file() and not (root / "B" / "scratch").exists()
    assert len(done["scratch_kept"]) == 30 and done["kept_worktree"]
    assert (Path(done["kept_worktree"]) / "B" / "scratch" / "profile" / "f0.dat").is_file()   # kept, never lost


def test_a_declared_output_that_git_ignores_lands(project):
    root, workers, factory = project
    _ignore(root, "*.pdf")
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", PASS, engine_factory=factory, outputs=["B/report.pdf"])
    assert out["ok"], out
    workers[0].produce({"B/report.pdf": "%PDF-1.4 stand-in"})
    done = await_job(cdir, out["job"])
    assert done["landed"], done["land_note"]
    assert (root / "B" / "report.pdf").read_text(encoding="utf-8") == "%PDF-1.4 stand-in"
    assert git(root, "ls-files", "B/report.pdf") == "B/report.pdf"


def test_every_finished_job_carries_a_plain_time_line(project):
    root, workers, factory = project
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", PASS, engine_factory=factory)
    workers[0].produce({"B/result.py": "answer = 42\n"})
    done = await_job(cdir, out["job"])
    assert done["speed"] and "min" in done["speed"]
    assert "Time: " in done["handoff"]["text"]
    lines = (cj.jobs_base() / "speed.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["job"] == out["job"]


def test_the_foundry_tools_ride_every_engines_rules(tmp_path, monkeypatch):
    idx = tmp_path / "INDEX.json"
    idx.write_text(json.dumps({"tools": [
        {"name": "look", "purpose": "screenshots in seconds", "command": "python C:/dev/foundry-tools/ft.py look x"},
        {"name": "brand-new", "purpose": "added today", "command": "python C:/dev/foundry-tools/ft.py brand-new"}]}))
    monkeypatch.setenv("ANCHOR_FOUNDRY_TOOLS_INDEX", str(idx))
    steward, coder = foundry_tools.block(), foundry_tools.block(steward=False)
    assert "brand-new: added today" in steward and "ft.py propose" in steward
    assert "look: screenshots in seconds" in coder and "propose" not in coder
    from steward_cockpit import steward_engine as se
    eng = se.Engine.__new__(se.Engine)
    eng.code_job = {"id": "j"}
    assert "brand-new" in eng._contract()
    idx.write_text("{ not json")
    assert foundry_tools.block() == foundry_tools.FALLBACK and "reading_copy.py" in foundry_tools.FALLBACK


def test_the_foundry_block_is_bounded(tmp_path, monkeypatch):
    idx = tmp_path / "INDEX.json"
    idx.write_text(json.dumps({"tools": [{"name": "t%d" % i, "purpose": "p" * 900, "command": "c" * 900}
                                         for i in range(40)]}))
    monkeypatch.setenv("ANCHOR_FOUNDRY_TOOLS_INDEX", str(idx))
    text = foundry_tools.block()
    assert text.count("\n  - ") == foundry_tools.MAX_TOOLS and len(text) < 6200


FAKE_TRIO = textwrap.dedent("""
    import fs from 'node:fs';
    const state = process.env.FAKE_TRIO_STATE;
    export function loadModelFamilies() { return { review: 'gemini', coding: 'claude', terminal: 'claude' }; }
    export function familyToDriverName(f) { return f === 'gemini' ? 'gemini-cli' : f; }
    export async function runAgent(opts) {
      const n = Number(fs.existsSync(state) ? fs.readFileSync(state, 'utf8') : '0') + 1;
      fs.writeFileSync(state, String(n));
      if (n <= Number(process.env.FAKE_TRIO_FAILS || '0')) {
        const e = new Error('trio seat verification_fail_closed: review:code-job');
        e.receipt = { status: 'verification_fail_closed', attempts: [{ error: { code: 'schema_nonconforming' } }] };
        throw e;
      }
      opts.onReceipt({ served: { family: 'gemini', model: 'g', model_attested: true } });
      return { verdict: 'PASS', findings: [], elegance: '' };
    }
""")


def _review(tmp_path, fails):
    trio = tmp_path / "trio"
    (trio / "drivers").mkdir(parents=True)
    (trio / "drivers" / "index.mjs").write_text(FAKE_TRIO)
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "T")
    git(repo, "config", "user.email", "t@invalid")
    (repo / "a.txt").write_text("one\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "a")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("two\n")
    git(repo, "commit", "-qam", "b")
    head = git(repo, "rev-parse", "HEAD")
    env = dict(os.environ, ANCHOR_TRIO_ROOT=str(trio), FAKE_TRIO_STATE=str(tmp_path / "n"),
               FAKE_TRIO_FAILS=str(fails), ANCHOR_REVIEW_RETRY_MS="10")
    r = subprocess.run(["node", str(ROOT / "tools" / "steward_review.mjs"), "--repo", str(repo), "--base", base,
                        "--head", head, "--author-family", "claude"], capture_output=True, text=True, env=env, timeout=60)
    calls = int((tmp_path / "n").read_text())
    return json.loads(r.stdout.strip().splitlines()[-1]), calls


def test_a_reviewer_that_fails_once_is_retried_and_its_review_counts(tmp_path):
    rec, calls = _review(tmp_path, fails=1)
    assert rec["ok"] and rec["verdict"] == "PASS" and calls == 2


def test_a_reviewer_that_fails_twice_is_reported_in_plain_words(tmp_path):
    rec, calls = _review(tmp_path, fails=2)
    assert not rec["ok"] and calls == 2
    assert "not in the required review form" in rec["error"] and "schema_nonconforming" in rec["error"]
    assert "Reviewer seat" in rec["error"]


def test_a_snapshot_alone_is_not_a_clean_audit():
    base = {"status": "done", "attempt": 2, "recovery_snapshot": {"files": {}}}
    assert not cj.audit_clean(base)                                   # no mark: the audit may never have run
    assert not cj.audit_clean(dict(base, audit_ok_attempt=1))          # an earlier attempt's mark
    assert cj.audit_clean(dict(base, audit_ok_attempt=2))
    assert not cj.audit_clean(dict(base, audit_ok_attempt=2, status="stopped"))


def _refused_for_the_stewards_edit(root, workers, factory, monkeypatch):
    """Book 1 v3 as it stands: re-filed once on the old build, refused for the steward's own AGENTS.md edit."""
    cdir, jid, first = _first_attempt_unlanded(root, workers, factory)
    _steward_edits_its_instructions(root)
    jobs = cj.read_jobs(cdir)
    jobs[jid].pop("audit_ok_attempt", None)                           # a record from before this build
    jobs[jid]["served_tree_changed"] = ["B/AGENTS.md (committed abc)"]
    cj._write_job(cdir, jobs[jid])
    monkeypatch.setattr(ch, "process_state", lambda *a, **kw: "dead")
    return cdir, jid


def test_a_named_and_pinned_outside_file_lets_the_refiling_land(project, monkeypatch):
    root, workers, factory = project
    cdir, jid = _refused_for_the_stewards_edit(root, workers, factory, monkeypatch)
    assert ch.recover(cdir, jid, check=PASS)["ok"]
    assert not await_job(cdir, jid, attempt=2)["landed"]              # unnamed: still refused
    assert ch.recover(cdir, jid, check=PASS, outside_ok=["B/AGENTS.md"])["ok"]
    done = await_job(cdir, jid, attempt=3)
    assert done["landed"], done["land_note"]


def test_a_pinned_outside_file_that_changes_again_still_refuses(project, monkeypatch):
    root, workers, factory = project
    cdir, jid = _refused_for_the_stewards_edit(root, workers, factory, monkeypatch)
    target = (root / "B" / "AGENTS.md").as_posix()
    again = [sys.executable, "-c", "open(%r, 'a').write('changed after it was named')" % target]
    assert ch.recover(cdir, jid, check=again, outside_ok=["B/AGENTS.md"])["ok"]
    done = await_job(cdir, jid, attempt=2)
    assert not done["landed"] and "changed during the job" in done["land_note"]


def test_outside_ok_never_names_the_jobs_own_file_or_a_path_outside_the_repo(project, monkeypatch):
    root, workers, factory = project
    cdir, jid = _refused_for_the_stewards_edit(root, workers, factory, monkeypatch)
    (root / "B" / "result.py").write_text("a coder wrote this straight into the repository\n", encoding="utf-8")
    assert "job's own file" in ch.recover(cdir, jid, check=PASS, outside_ok=["B/result.py"])["error"]
    jobs = cj.read_jobs(cdir)                          # review r2 #1: a stopped job's manifest is its own file too
    jobs[jid]["files"], jobs[jid]["outputs"] = [], []
    cj._write_job(cdir, jobs[jid])
    assert "job's own file" in ch.recover(cdir, jid, check=PASS, outside_ok=["B/result.py"])["error"]
    assert "repository-relative" in ch.recover(cdir, jid, check=PASS, outside_ok=["../x"])["error"]


def test_an_unreadable_ignored_listing_is_never_taken_for_scratch(project, monkeypatch):
    root, workers, factory = project
    cdir = root / "A"
    out = cj.start(cdir, root / "B", "Produce result", PASS, engine_factory=factory)
    monkeypatch.setattr(cj, "ignored_outputs", lambda tree: ["(git could not list ignored files)"])
    workers[0].produce({"B/result.py": "answer = 42\n"})
    done = await_job(cdir, out["job"])
    assert not done["landed"] and "could not list ignored files" in done["land_note"], done["land_note"]
