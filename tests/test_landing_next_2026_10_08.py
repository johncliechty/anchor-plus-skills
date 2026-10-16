"""W1a of the night of 2026-10-08, as it stands after 2026-10-12: "landed" and "live" are two places for an INSTALLED
SKILL REPOSITORY (its anchor-next waits for a human activation), and the lander can never write the running Anchor -
whose code is changed only from outside Anchor (John, 2026-10-10; the Anchor activation path removed 2026-10-12).

Every proof runs on throwaway repositories: one standing in for a skill repository, one for the running checkout
(ANCHOR_SERVED_ROOT) - never C:\\dev\\Anchor, never C:\\dev\\trio, never :8777."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import anchor_next  # noqa: E402
import git_safety  # noqa: E402
from steward_cockpit import code_jobs  # noqa: E402

PASS = [sys.executable, "-c", "pass"]


def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _init(repo):
    repo.mkdir()
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _g(repo, *args)
    (repo / "static").mkdir()
    (repo / "static" / "page.js").write_text("var build = 'one';\n", encoding="utf-8")
    (repo / "helper.py").write_text("WHO = 'one'\n", encoding="utf-8")
    (repo / "records.json").write_text("{}\n", encoding="utf-8")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "start")
    return repo


@pytest.fixture()
def served(tmp_path, monkeypatch):
    """A throwaway repository playing the running Anchor."""
    repo = _init(tmp_path / "Anchor")
    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(repo))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    return repo


@pytest.fixture()
def repo(tmp_path, served):
    """A throwaway repository playing an installed skill repository (activation is the human's step there)."""
    return _init(tmp_path / "trio")


def _land_next(repo, writes, message="a landing"):
    """What a code job's landing leaves: a commit on the repository's anchor-next, in the lander's checkout."""
    ip, why = anchor_next.ensure_integration(repo)
    assert ip is not None, why
    for name, text in writes.items():
        Path(ip, name).parent.mkdir(parents=True, exist_ok=True)
        Path(ip, name).write_text(text, encoding="utf-8")
    _g(ip, "add", "-A")
    _g(ip, "commit", "-qm", message)
    return Path(ip), _g(ip, "rev-parse", "HEAD")


class _Coder:
    def __init__(self, wt, writes):
        self.wt, self.writes = wt, writes
        self.written_ok, self.on_turn_done, self.code_job, self.policy_override = [], None, None, None
        self.cli = "claude"

    def wake(self, fresh=False, seed=None):
        for name, text in self.writes.items():
            Path(self.wt, name).parent.mkdir(parents=True, exist_ok=True)
            Path(self.wt, name).write_text(text, encoding="utf-8")
            self.written_ok.append(str(Path(self.wt, name)))
        self.on_turn_done({"text": "done", "error": ""})
        return True, "awake"

    def stop(self):
        pass


def _run_job(tmp_path, monkeypatch, repo, writes, check=PASS, name="steward"):
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    cdir = tmp_path / name
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change the page.", check, engine_factory=lambda wt: _Coder(wt, writes))
    assert out["ok"], out
    for _ in range(400):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return j
        time.sleep(0.1)
    raise AssertionError(code_jobs.read_jobs(str(cdir)))


def test_the_running_checkout_is_never_a_landing_target(served):
    _g(served, "checkout", "-q", "-b", "job")
    (served / "helper.py").write_text("WHO = 'two'\n", encoding="utf-8")
    _g(served, "commit", "-qam", "job")
    cand = _g(served, "rev-parse", "HEAD")
    _g(served, "checkout", "-q", "master")
    ok, note = git_safety.land(str(served), cand, ["helper.py"], "a direct landing")
    assert ok is False and "is the running Anchor" in note and "outside Anchor" in note
    assert (served / "helper.py").read_text(encoding="utf-8") == "WHO = 'one'\n"


def test_code_jobs_on_the_running_anchor_are_refused_whatever_the_switches_say(tmp_path, monkeypatch, served):
    """2026-10-12: the ANCHOR_SERVED_CODE_JOBS escape is gone - no switch starts a code job on Anchor's own code."""
    monkeypatch.setenv("ANCHOR_SERVED_CODE_JOBS", "1")
    monkeypatch.setenv("ANCHOR_UNCONFINED_CODERS", "1")
    for coder in ("claude", "chatgpt"):
        monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="", c=coder: (c, None))
        cdir = tmp_path / coder
        cdir.mkdir()
        made = []
        out = code_jobs.start(str(cdir), str(served), "x", PASS, engine_factory=lambda wt: made.append(wt))
        assert out["ok"] is False and "never changed from a cockpit" in out["error"], out
        assert made == [] and code_jobs.read_jobs(str(cdir)) == {}
    assert "never changed from a cockpit" in code_jobs.integration_required_error({"repo": str(served), "land_to": "x"})


def test_the_running_anchor_never_gets_an_anchor_next_or_an_activation(served):
    """2026-10-12: nothing lands on the running Anchor's anchor-next, and nothing activates it - even by hand."""
    ip, why = anchor_next.ensure_integration(served)
    assert ip is None and "running Anchor" in why
    _g(served, "branch", anchor_next.BRANCH)                     # an old branch left from before (the live repo has one)
    head = _g(served, "rev-parse", "HEAD")
    r = anchor_next.activate(served)
    assert r["ok"] is False and "running Anchor" in r["why"] and _g(served, "rev-parse", "HEAD") == head


def test_the_activation_brings_in_the_checked_out_branchs_own_commits(repo):
    _land_next(repo, {"static/page.js": "var build = 'two';\n"})
    (repo / "records.json").write_text('{"checkpoint": 1}\n', encoding="utf-8")       # the repository's own commit
    _g(repo, "commit", "-qam", "its own commit")
    pre = anchor_next.check(repo)
    assert pre["ok"] and not pre["blockers"], pre
    r = anchor_next.activate(repo)
    assert r["ok"], r
    assert (repo / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'two';\n"
    assert (repo / "records.json").read_text(encoding="utf-8") == '{"checkpoint": 1}\n'
    assert _g(repo, "rev-parse", "HEAD") == _g(repo, "rev-parse", "anchor-next")
    assert anchor_next.waiting(repo) == []


def test_an_uncommitted_file_the_activation_would_overwrite_stops_it_before_any_change(repo):
    _land_next(repo, {"static/page.js": "var build = 'two';\n"})
    (repo / "static" / "page.js").write_text("var build = 'a local edit';\n", encoding="utf-8")
    head = _g(repo, "rev-parse", "HEAD")
    pre = anchor_next.check(repo)
    assert pre["ok"] is False and pre["blockers"] == ["static/page.js"] and "would be overwritten" in pre["why"]
    r = anchor_next.activate(repo)
    assert r["ok"] is False and r["blockers"] == ["static/page.js"]
    assert _g(repo, "rev-parse", "HEAD") == head
    assert (repo / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'a local edit';\n"


def test_a_conflict_between_the_branches_stops_the_activation_before_any_change(repo):
    _land_next(repo, {"helper.py": "WHO = 'two'\n"})
    (repo / "helper.py").write_text("WHO = 'committed by hand'\n", encoding="utf-8")
    _g(repo, "commit", "-qam", "a hand commit")
    head = _g(repo, "rev-parse", "HEAD")
    r = anchor_next.activate(repo)
    assert r["ok"] is False and "helper.py" in " ".join(r["conflicts"]) and "conflict" in r["why"]
    assert _g(repo, "rev-parse", "HEAD") == head and (repo / "helper.py").read_text(encoding="utf-8") == "WHO = 'committed by hand'\n"


def test_every_landing_needs_an_explicit_passing_check(tmp_path, monkeypatch, repo):
    # a missing check is refused at the START (the production gate): no job, no worktree, no coder, no record
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    made = []
    cdir = tmp_path / "nocheck"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change the page.", "", engine_factory=lambda wt: made.append(wt))
    assert out["ok"] is False and "needs --check" in out["error"] and "no job started" in out["error"]
    assert made == [] and code_jobs.read_jobs(str(cdir)) == {} and not (tmp_path / "jobs").exists()
    # a failing check never lands
    head = _g(repo, "rev-parse", "HEAD")
    job = _run_job(tmp_path, monkeypatch, repo, {"static/page.js": "var build = 'three';\n"},
                   check=[sys.executable, "-c", "raise SystemExit(4)"], name="badcheck")
    assert job["landed"] is False and "check failed" in job["land_note"]
    assert _g(repo, "rev-parse", "HEAD") == head


def test_one_lock_for_every_checkout_of_a_repository(repo):
    ip, why = anchor_next.ensure_integration(repo)
    assert ip is not None, why
    assert git_safety._lock_path(str(repo)) == git_safety._lock_path(str(ip))
    with git_safety.repo_lock(str(repo), wait_s=0) as held:
        assert held
        with git_safety.repo_lock(str(ip), wait_s=0) as again:
            assert again is False                      # the lander's checkout waits on the checkout's lock


def test_the_landers_checkout_written_by_someone_else_is_refused_never_cleaned(repo):
    ip, _ = anchor_next.ensure_integration(repo)
    (Path(ip) / "helper.py").write_text("WHO = 'stray'\n", encoding="utf-8")
    again, why = anchor_next.ensure_integration(repo)
    assert again is None and "nobody committed" in why
    assert (Path(ip) / "helper.py").read_text(encoding="utf-8") == "WHO = 'stray'\n"


def test_a_steward_inside_the_running_anchor_cannot_write_code_there():
    from steward_cockpit import steward_engine as se
    assert "Edit(./**/*.py)" in se.SERVED_CODE_DENY and "Edit(./**/*.js)" in se.SERVED_CODE_DENY
    assert "Edit(./**/*.css)" in se.SERVED_CODE_DENY
    assert se._in_served(str(se._SERVED / "Setup and Mother Ship")) and not se._in_served(str(ROOT.parent / "elsewhere"))
    src = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert '"plan" if read_only else ("fenced" if fenced else self.permission_mode)' in src
    assert '*(SERVED_CODE_DENY if (fenced and in_served) else ())' in src


def test_the_restart_drains_before_it_stops_and_changes_no_code():
    """2026-10-12: the restart no longer activates anything - drain, stop, start; the code is installed from outside."""
    ps = (ROOT / "restart_anchor.ps1").read_text(encoding="utf-8")
    order = [ps.index('tools\\pre_restart_drain.py'), ps.index("& $Nssm stop anchor"), ps.index("& $Nssm start anchor")]
    assert order == sorted(order)
    assert "anchor_next" not in ps and "reset --hard" not in ps and "RESTART STOPPED BEFORE ANY CHANGE" in ps


# ---------- ChatGPT review round 1 ----------

def test_the_running_checkout_is_the_main_worktree_wherever_this_is_imported_from(monkeypatch):
    monkeypatch.delenv("ANCHOR_SERVED_ROOT", raising=False)
    main = subprocess.run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True, text=True).stdout.splitlines()[0][len("worktree "):]
    assert anchor_next._norm(anchor_next.served_root()) == anchor_next._norm(main)
    assert not anchor_next.is_served_checkout(str(ROOT)) or anchor_next._norm(ROOT) == anchor_next._norm(main)


def test_an_ignored_local_file_or_a_folder_in_the_way_blocks_the_activation(repo):
    (repo / ".gitignore").write_text("local.cfg\n", encoding="utf-8")
    _g(repo, "add", ".gitignore")
    _g(repo, "commit", "-qm", "ignore")
    ip, _ = anchor_next.ensure_integration(repo)
    (Path(ip) / "local.cfg").write_text("shipped\n", encoding="utf-8")
    (Path(ip) / "assets").write_text("a file\n", encoding="utf-8")
    _g(ip, "add", "-f", "local.cfg", "assets")
    _g(ip, "commit", "-qm", "adds a tracked local.cfg and a file named assets")
    (repo / "local.cfg").write_text("John's own settings\n", encoding="utf-8")       # ignored, local
    (repo / "assets").mkdir()
    (repo / "assets" / "mine.txt").write_text("untracked\n", encoding="utf-8")      # a folder where a file comes
    pre = anchor_next.check(repo)
    assert pre["ok"] is False and set(pre["blockers"]) == {"local.cfg", "assets"}, pre
    r = anchor_next.activate(repo)
    assert r["ok"] is False and (repo / "local.cfg").read_text(encoding="utf-8") == "John's own settings\n"


def test_a_refused_fast_forward_is_restored_and_verified(repo):
    _land_next(repo, {"static/page.js": "var build = 'two';\n"})
    head = _g(repo, "rev-parse", "HEAD")
    gitdir = Path(_g(repo, "rev-parse", "--absolute-git-dir"))
    lock = gitdir / "refs" / "heads" / "master.lock"
    lock.write_text("held\n", encoding="utf-8")                  # git checks out, then cannot move the branch
    try:
        r = anchor_next.activate(repo)
    finally:
        lock.unlink()
    assert r["ok"] is False and r["unverified"] == [] and "restored and verified" in r["why"], r
    assert _g(repo, "rev-parse", "HEAD") == head
    assert (repo / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'one';\n"
    assert _g(repo, "status", "--porcelain") == ""


def test_a_kept_jobs_rows_are_never_announced_one_by_one(tmp_path, monkeypatch):
    """ChatGPT W1a r2: the generic publisher never announces a kept code job's rows - its one line does (atomic: no
    window between a registration and a suppression)."""
    from steward_cockpit import steward_engine as se
    import deliverables_register as dr
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# cockpit\n", encoding="utf-8")
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", ""))
    se.receipt_baseline(str(eff))
    (eff / "code-job-outputs").mkdir()
    for n in ("a.pdf", "b.pdf"):
        (eff / "code-job-outputs" / n).write_bytes(b"%PDF-1.4")
        assert dr.register(eff, "Code job J1 kept (not landed): " + n, "`code-job-outputs/%s`" % n, notify=False)["written"]
    lines = []
    se.publish_delivery_receipts(str(eff), record=lambda line, rid: lines.append(line), emit=None)
    assert lines == []


# ---------- ChatGPT review round 2 ----------

def test_recovery_restores_only_what_the_activation_wrote(monkeypatch, repo):
    """A save made by someone else to an incoming file between the check and the fast-forward is KEPT, and the
    refusal is unverified (the checkout is looked at before it is used)."""
    _land_next(repo, {"static/page.js": "var build = 'two';\n"})
    head = _g(repo, "rev-parse", "HEAD")
    real_check = anchor_next.check

    def check_then_save(root):
        out = real_check(root)
        (repo / "static" / "page.js").write_text("var build = 'his save';\n", encoding="utf-8")   # after the check
        return out
    monkeypatch.setattr(anchor_next, "check", check_then_save)
    r = anchor_next.activate(repo)
    assert r["ok"] is False and r["unverified"], r
    assert (repo / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'his save';\n"
    assert _g(repo, "rev-parse", "HEAD") == head


def test_recovery_reads_file_names_literally(repo):
    (repo / "a1.txt").write_text("tracked\n", encoding="utf-8")
    (repo / "a[1].txt").write_text("tracked too\n", encoding="utf-8")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-qm", "two names a pattern could confuse")
    ip, _ = anchor_next.ensure_integration(repo)
    (Path(ip) / "a[1].txt").write_text("next\n", encoding="utf-8")
    _g(ip, "commit", "-qam", "changes a[1].txt only")
    (repo / "a1.txt").write_text("his local edit\n", encoding="utf-8")       # dirty, but not incoming
    lock = Path(_g(repo, "rev-parse", "--absolute-git-dir")) / "refs" / "heads" / "master.lock"
    lock.write_text("held\n", encoding="utf-8")
    try:
        r = anchor_next.activate(repo)
    finally:
        lock.unlink()
    assert r["ok"] is False and r["unverified"] == [], r
    assert (repo / "a1.txt").read_text(encoding="utf-8") == "his local edit\n"
    assert (repo / "a[1].txt").read_text(encoding="utf-8") == "tracked too\n"


@pytest.mark.parametrize("who,cmd,refused", [
    ("steward", "git diff --stat", False), ("steward", "git diff --output=C:/dev/Anchor/static/x.js", True),
    ("steward", 'git diff "--output=x"', True), ("steward", "git diff $'--output=x'", True),
    ("steward", "git status > C:/dev/Anchor/a.py", True), ("steward", "git log -c core.pager=x", True),
    ("steward", 'python C:/dev/Anchor/tools/steward_code_job.py start --repo C:/dev/Anchor --brief "fix a; b > c"', False),
    ("steward", 'python C:/dev/Anchor/tools/steward_code_job.py start --brief "$(rm -rf x)"', True),
    ("steward", "rm -rf C:/dev/Anchor", True), ("steward", "git diff a\\b", True),
    ("coder", "pytest -q tests/test_a.py", False), ("coder", "cp x C:/dev/Anchor/static/a.js", True),
    ("coder", "cd /c/dev/Anchor && ls", True), ("coder", "cd ../../../../dev && ls", True),
])
def test_the_fence_guard_grammar(who, cmd, refused, tmp_path):
    env = dict(os.environ, **({"ANCHOR_FENCE_SHELL": "1"} if who == "steward" else
                              {"ANCHOR_FENCE_ROOT": str(tmp_path), "ANCHOR_FENCE_SERVED": "C:/dev/Anchor"}))
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "fence_guard.py")],
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True, env=env)
    assert (r.returncode == 2) is refused, (cmd, r.returncode, r.stderr)


def test_declared_outputs_are_normalized_and_one_the_check_made_lands(tmp_path, monkeypatch):
    assert code_jobs.declared_outputs(["./out//report.pdf", "out/report.pdf"]) == (["out/report.pdf"], None)
    assert code_jobs.declared_outputs(["out/../../x"])[0] is None


# ---------- ChatGPT review round 3 ----------

def test_a_declared_output_is_validated_after_normalizing():
    for bad in ("roadmap.json/.", "./strip.json", "x/../roadmap.json", ".ecgberht/./state.json"):
        assert code_jobs.declared_outputs([bad])[0] is None, bad


def test_every_coder_launch_on_the_running_anchors_repository_is_claudes(monkeypatch, served):
    from steward_cockpit import steward_engine as se
    monkeypatch.delenv("ANCHOR_UNCONFINED_CODERS", raising=False)
    assert se._unconfined_ok({"repo": str(served)}) is False
    assert se._unconfined_ok({"repo": ""}) is False, "unknown counts as the running Anchor's"
    monkeypatch.setenv("ANCHOR_UNCONFINED_CODERS", "1")
    assert se._unconfined_ok({"repo": str(served)}) is True
    src = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert 'if self.code_job is not None and self.cli != "claude" and not _unconfined_ok(self.code_job):' in src


def test_temporary_builds_live_under_c_dev_beside_the_checkout(monkeypatch):
    r"""John, 2026-10-08: temporary builds go in a C:\dev folder (backed up), never inside C:\dev\Anchor."""
    import paths
    monkeypatch.delenv("ANCHOR_CODE_JOBS_DIR", raising=False)
    d = paths.code_jobs_dir()
    assert d.name == "Anchor-code-jobs" and d.parent == paths.CODE_DIR.parent
    assert not str(d).lower().startswith(str(paths.CODE_DIR).lower() + os.sep.lower())
