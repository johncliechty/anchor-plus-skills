"""An INSTALLED skill repository is never installed by a model pass (2026-10-10). A code job on C:\\dev\\trio or
C:\\dev\\Skill Foundry - the checkouts the installed skills run from - lands on that repository's own anchor-next in the
lander's checkout, exactly as a job on Anchor's own code does; the live checkout (HEAD, index, files) is untouched
until a HUMAN activates it. Every proof runs on throwaway repositories standing in for the installed skill repository
(ANCHOR_SKILL_ROOTS inside it) and for the running Anchor (ANCHOR_SERVED_ROOT) - never C:\\dev\\trio, never C:\\dev\\Anchor,
never :8777. The coder is a stand-in that writes files; the reviewer is tests/fake_review.py."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anchor_next  # noqa: E402
from steward_cockpit import code_jobs, code_job_handoff as handoff, steward_routes  # noqa: E402

PASS = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "raise SystemExit(4)"]


def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(root, files):
    root.mkdir(parents=True)
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _g(root, *args)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _g(root, "add", "-A")
    _g(root, "commit", "-q", "-m", "start")
    return root


def _state(repo):
    """What the live checkout holds: HEAD, the index, the working tree's status, every tracked file's bytes."""
    return (_g(repo, "rev-parse", "HEAD"), _g(repo, "ls-files", "-s"),
            _g(repo, "status", "--porcelain", "--untracked-files=all"),
            {p: (repo / p).read_text(encoding="utf-8") for p in _g(repo, "ls-files").split()})


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    """A throwaway repository playing an installed skill repository (its skills/ folder is a skill root), beside a
    throwaway running Anchor and an ordinary project repository. No real source of installed roots is read."""
    served = _repo(tmp_path / "Anchor", {"helper.py": "WHO = 'one'\n"})
    trio = _repo(tmp_path / "trio", {"skills/gandalf/run.py": "print('gandalf')\n", "lib/a.py": "A = 1\n"})
    plain = _repo(tmp_path / "project", {"lib/a.py": "A = 1\n"})
    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(served))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(trio / "skills"))              # the skill root INSIDE the repository
    monkeypatch.setenv("ANCHOR_SKILLS_ROOT", str(tmp_path / "skills-root"))     # the share registry's root: nothing there
    monkeypatch.setenv("ANCHOR_SKILLS_DIR", str(tmp_path / "farm"))             # Claude's adapter farm: empty
    (tmp_path / "farm").mkdir()
    monkeypatch.setattr(code_jobs, "FOREMAN_RUN_LIVE", tmp_path / "nowhere" / "run-live.mjs")
    # Each proof owns its complete installation inventory, including the
    # manifest; it must not discover repositories from the developer's host.
    import foundry_api
    manifest = tmp_path / "foundry-manifest.json"
    manifest.write_text(json.dumps({"skills": []}), encoding="utf-8")
    monkeypatch.setattr(foundry_api, "MANIFEST_PATH", manifest)
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    monkeypatch.delenv("FAKE_REVIEW_VERDICT", raising=False)
    monkeypatch.delenv("ANCHOR_SERVED_CODE_JOBS", raising=False)
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    monkeypatch.setattr(steward_routes, "get_engine", lambda *a, **k: None)   # no engine is ever made or woken here
    return served, trio, plain


class _Coder:
    """A coder stand-in: writes what it is told and ends its turn."""

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


def _run_job(tmp_path, repo, writes, check=PASS, name="steward"):
    cdir = tmp_path / name
    cdir.mkdir(exist_ok=True)
    out = code_jobs.start(str(cdir), str(repo), "Change lib.", check, engine_factory=lambda wt: _Coder(wt, writes))
    assert out["ok"], out
    for _ in range(600):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed", "stopped") and not j.get("finalizer_active"):
            return cdir, j
        time.sleep(0.1)
    raise AssertionError(code_jobs.read_jobs(str(cdir)))


# ---- the predicate ----

def test_the_predicate_keys_on_the_owning_common_dir_for_worktrees_and_aliases(installed, tmp_path):
    served, trio, plain = installed
    assert anchor_next.is_installed_repo(trio) and anchor_next.is_installed_repo(trio / "lib")
    assert not anchor_next.is_installed_repo(plain) and not anchor_next.is_installed_repo(served)
    assert not anchor_next.is_installed_repo(tmp_path / "nowhere")
    assert anchor_next.common_dir(trio) in anchor_next.installed_common_dirs()
    wt = tmp_path / "trio-wt"
    _g(trio, "worktree", "add", "-q", "-b", "side", str(wt))
    assert anchor_next.is_installed_repo(wt), "a linked worktree is the same repository"
    if os.name == "nt":
        import _winapi
        alias = tmp_path / "alias"
        try:
            _winapi.CreateJunction(str(trio), str(alias))
        except OSError:
            pytest.skip("junctions cannot be made here")
        assert anchor_next.is_installed_repo(alias), "a junction alias is the same repository"


def test_the_running_anchor_is_served_never_installed_even_when_named_as_a_skill_root(installed, monkeypatch):
    served, trio, plain = installed
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", os.pathsep.join([str(trio / "skills"), str(served)]))
    assert anchor_next.is_served_repo(served) and not anchor_next.is_installed_repo(served)
    assert anchor_next.is_installed_repo(trio)


# ---- the landing ----

def test_a_job_on_an_installed_repository_lands_on_its_anchor_next_and_the_live_checkout_is_untouched(installed, tmp_path):
    served, trio, plain = installed
    before = _state(trio)
    cdir, job = _run_job(tmp_path, trio, {"lib/a.py": "A = 2\n"})
    assert job["landed"] is True and job["verified"] is True, job.get("land_note")
    assert job["installed_repo"] is True and job["land_to"]
    ip = Path(job["land_to"])
    assert ip.resolve() != trio.resolve() and str(ip).startswith(str(tmp_path / "jobs"))
    assert ip.resolve() == anchor_next.integration_dir(trio).resolve()
    # the installed checkout: same HEAD, same index, same bytes - the next skill run executes the OLD code
    assert _state(trio) == before
    assert (trio / "lib" / "a.py").read_text(encoding="utf-8") == "A = 1\n"
    # anchor-next carries it, and it waits for a human
    assert _g(trio, "show", "anchor-next:lib/a.py") == "A = 2"
    assert [s for s, _ in anchor_next.waiting(trio)] == [job["landed_commit"]]
    note = job["land_note"]
    assert "NOT installed" in note and "anchor_next.py activate" in note and str(trio) in note
    stage = code_jobs.stage_line(job)
    assert stage.startswith("made → checked → reviewed → landed → not installed") and "live" not in stage
    # the durable result says it too, and never claims an installation
    receipt = code_jobs._materialize_report(str(cdir), code_jobs.read_jobs(str(cdir))[job["id"]])
    text = receipt["text"]
    assert "NOT INSTALLED" in text and "awaits his activation" in text and "never call it installed" in text
    assert "Stage: " + stage in text


def test_an_ordinary_repository_still_lands_directly(installed, tmp_path):
    served, trio, plain = installed
    cdir, job = _run_job(tmp_path, plain, {"lib/a.py": "A = 2\n"}, name="plain")
    assert job["landed"] is True and job["land_to"] == "" and "installed_repo" not in job, job.get("land_note")
    assert (plain / "lib" / "a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert _g(plain, "rev-parse", "HEAD") == job["landed_commit"]
    assert "NOT installed" not in job["land_note"] and "not installed" not in code_jobs.stage_line(job)
    assert code_jobs.installed_note(job) == ""


def test_integration_swapped_during_review_is_refused_before_placement(installed, tmp_path, monkeypatch):
    _, trio, _ = installed
    original = code_jobs.run_review
    swapped = []
    def review(job, *args, **kwargs):
        result = original(job, *args, **kwargs)
        if not swapped:
            integration = Path(job["land_to"])
            preserved = integration.with_name(integration.name + "-preserved")
            _g(trio, "worktree", "move", str(integration), str(preserved))
            _g(trio, "clone", "--no-hardlinks", str(trio), str(integration))
            _g(integration, "checkout", "-B", "anchor-next", job["base"])
            swapped.append((integration, _state(integration)))
        return result
    monkeypatch.setattr(code_jobs, "run_review", review)
    _, job = _run_job(tmp_path, trio, {"lib/a.py": "A = 2\n"})
    assert not job.get("landed"), job
    assert swapped and _state(swapped[0][0]) == swapped[0][1]
    assert (trio / "lib/a.py").read_text(encoding="utf-8") == "A = 1\n"
    assert Path(job["worktree"], "lib/a.py").read_text(encoding="utf-8") == "A = 2\n"


def test_two_jobs_combine_on_anchor_next_and_one_human_activation_installs_both(installed, tmp_path):
    served, trio, plain = installed
    before = _state(trio)
    _, first = _run_job(tmp_path, trio, {"lib/a.py": "A = 2\n"}, name="s1")
    _, second = _run_job(tmp_path, trio, {"lib/b.py": "B = 2\n"}, name="s2")
    assert first["landed"] and second["landed"], (first.get("land_note"), second.get("land_note"))
    assert second["base"] == first["landed_commit"], "the second job starts from what the first landed"
    assert [s for s, _ in anchor_next.waiting(trio)] == [second["landed_commit"], first["landed_commit"]]
    assert _state(trio) == before, "two landings, still nothing installed"
    pre = anchor_next.check(trio)
    assert pre["ok"] and sorted(pre["incoming"]) == ["lib/a.py", "lib/b.py"], pre
    r = anchor_next.activate(trio)                                       # the human's explicit step
    assert r["ok"], r
    assert (trio / "lib" / "a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert (trio / "lib" / "b.py").read_text(encoding="utf-8") == "B = 2\n"
    assert _g(trio, "rev-parse", "HEAD") == _g(trio, "rev-parse", "anchor-next") and anchor_next.waiting(trio) == []


def test_a_dirty_or_stale_installed_checkout_is_never_overwritten_and_both_works_are_kept(installed, tmp_path):
    served, trio, plain = installed
    _, job = _run_job(tmp_path, trio, {"lib/a.py": "A = 2\n"})
    assert job["landed"], job.get("land_note")
    # dirty: a hand edit in the installed checkout that the activation would overwrite
    (trio / "lib" / "a.py").write_text("A = 'hand edit, unsaved'\n", encoding="utf-8")
    head = _g(trio, "rev-parse", "HEAD")
    pre = anchor_next.check(trio)
    assert pre["ok"] is False and pre["blockers"] == ["lib/a.py"] and "would be overwritten" in pre["why"]
    r = anchor_next.activate(trio)
    assert r["ok"] is False and r["blockers"] == ["lib/a.py"] and not r["unverified"]
    assert _g(trio, "rev-parse", "HEAD") == head
    assert (trio / "lib" / "a.py").read_text(encoding="utf-8") == "A = 'hand edit, unsaved'\n"
    assert [s for s, _ in anchor_next.waiting(trio)] == [job["landed_commit"]], "the landing is still there"
    # stale: the installed checkout moved on by hand, in conflict with the landing
    _g(trio, "commit", "-qam", "a hand commit to the same file")
    head = _g(trio, "rev-parse", "HEAD")
    r = anchor_next.activate(trio)
    assert r["ok"] is False and "lib/a.py" in " ".join(r["conflicts"]) and "conflict" in r["why"]
    assert _g(trio, "rev-parse", "HEAD") == head
    assert (trio / "lib" / "a.py").read_text(encoding="utf-8") == "A = 'hand edit, unsaved'\n"
    assert _g(trio, "show", "anchor-next:lib/a.py") == "A = 2"


# ---- recovery and the landing refuse an older record that names no integration checkout ----

def test_recovery_of_an_older_record_without_an_integration_checkout_is_refused(installed, tmp_path):
    served, trio, plain = installed
    before = _state(trio)
    cdir, job = _run_job(tmp_path, trio, {"lib/a.py": "A = 2\n"}, check=FAIL)
    assert job["landed"] is False and job["check_ok"] is False and job["kept_worktree"], job.get("land_note")
    assert job["land_to"] and job["installed_repo"] is True
    assert handoff.inspect(str(cdir), job["id"])["recovery"]["available"] is True, "a corrected check could recover it"
    # an older record of the same shape never named an integration checkout (land_to)
    old = dict(job)
    old.pop("land_to")
    old.pop("installed_repo")
    code_jobs._write_job(str(cdir), old)
    look = handoff.inspect(str(cdir), job["id"])
    assert look["recovery"]["available"] is False and "installed skill repository" in look["recovery"]["reason"]
    out = handoff.recover(str(cdir), job["id"], check=PASS)
    assert out["ok"] is False and "installed skill repository" in out["error"]
    rec = code_jobs.read_jobs(str(cdir))[job["id"]]
    assert rec["attempt"] == 1 and rec["status"] == "done" and not rec.get("finalizer_active"), "nothing was claimed"
    # and the landing itself refuses such a record, whatever path reached it
    landed, note, _ = code_jobs.land(old, ["lib/a.py"])
    assert landed is False and "installed skill repository" in note and "land_to" in note
    assert code_jobs.integration_required_error(job) == ""                 # the record WITH land_to may land there
    assert _state(trio) == before


def test_manifest_only_external_skill_lands_in_its_own_integration_checkout(installed, tmp_path):
    import foundry_api

    _served, _trio, _plain = installed
    external = _repo(tmp_path / "external-registered", {"SKILL.md": "# Registered skill\n", "helper.py": "VALUE = 1\n"})
    Path(foundry_api.MANIFEST_PATH).write_text(
        json.dumps({"skills": [{"name": "external", "source": str(external)}]}), encoding="utf-8"
    )
    before = _g(external, "rev-parse", "HEAD")
    assert anchor_next.is_installed_repo(external)
    _cdir, job = _run_job(tmp_path, external, {"helper.py": "VALUE = 2\n"}, name="external-job")
    assert job["landed"] and job["installed_repo"], job
    assert anchor_next.common_dir(job["land_to"]) == anchor_next.common_dir(external)
    assert _g(external, "rev-parse", "HEAD") == before
    assert (external / "helper.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _g(external, "show", "anchor-next:helper.py") == "VALUE = 2"


@pytest.mark.parametrize("contents", ["{", "[]", '{"skills":"invalid"}'])
def test_invalid_configured_manifest_refuses_direct_landing(installed, contents):
    import foundry_api

    _served, _trio, plain = installed
    Path(foundry_api.MANIFEST_PATH).write_text(contents, encoding="utf-8")
    with pytest.raises(anchor_next.InstalledUnknown, match="manifest"):
        anchor_next.is_installed_repo(plain)
    error = code_jobs.integration_required_error({"repo": str(plain)})
    assert "direct landing is refused" in error and "work is kept" in error


def test_unreadable_configured_manifest_refuses_start_before_spawning(installed, tmp_path, monkeypatch):
    import foundry_api

    _served, _trio, plain = installed
    manifest = Path(foundry_api.MANIFEST_PATH)
    read_text = Path.read_text

    def denied(path, *args, **kwargs):
        if path == manifest:
            raise PermissionError("manifest access denied")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    made = []
    cdir = tmp_path / "unreadable-manifest-job"
    cdir.mkdir()
    before = (_g(plain, "rev-parse", "HEAD"), _g(plain, "status", "--porcelain"))
    result = code_jobs.start(str(cdir), str(plain), "Change the source file.", PASS,
                             engine_factory=lambda wt: made.append(wt))
    assert result["ok"] is False and "manifest" in result["error"].lower(), result
    assert made == []
    assert (_g(plain, "rev-parse", "HEAD"), _g(plain, "status", "--porcelain")) == before


@pytest.mark.parametrize("failure", ["resolve", "git-entry"])
def test_unreadable_source_identity_never_becomes_an_absent_repository(installed, monkeypatch, failure):
    _served, trio, plain = installed
    resolve, lstat = Path.resolve, Path.lstat

    def denied_resolve(path, *args, **kwargs):
        if path == trio or trio in path.parents:
            raise PermissionError("source resolution denied")
        return resolve(path, *args, **kwargs)

    def denied_lstat(path, *args, **kwargs):
        if path == trio / ".git":
            raise PermissionError("git identity access denied")
        return lstat(path, *args, **kwargs)

    if failure == "resolve":
        monkeypatch.setattr(Path, "resolve", denied_resolve)
    else:
        monkeypatch.setattr(Path, "lstat", denied_lstat)
    with pytest.raises(anchor_next.InstalledUnknown):
        anchor_next._git_anchor(trio)
    assert "direct landing is refused" in code_jobs.integration_required_error({"repo": str(plain)})


def test_failed_candidate_git_identity_is_not_reported_as_uninstalled(installed, monkeypatch):
    _served, trio, _plain = installed
    common_dir = anchor_next.common_dir
    monkeypatch.setattr(anchor_next, "common_dir", lambda path: "" if Path(path) == trio else common_dir(path))
    with pytest.raises(anchor_next.InstalledUnknown, match="common directory"):
        anchor_next.is_installed_repo(trio)
    assert "direct landing is refused" in code_jobs.integration_required_error({"repo": str(trio)})


def test_failed_served_git_identity_cannot_remove_its_exclusion(installed, monkeypatch):
    served, _trio, plain = installed
    common_dir = anchor_next.common_dir
    monkeypatch.setattr(anchor_next, "common_dir", lambda path: "" if Path(path) == served else common_dir(path))
    with pytest.raises(anchor_next.InstalledUnknown, match="served Anchor"):
        anchor_next.is_installed_repo(plain)


def test_an_absent_optional_skill_farm_does_not_block_ordinary_repositories(installed, tmp_path, monkeypatch):
    _served, trio, plain = installed
    monkeypatch.setenv("ANCHOR_SKILLS_DIR", str(tmp_path / "optional-farm-not-installed"))
    assert anchor_next.is_installed_repo(trio)
    assert not anchor_next.is_installed_repo(plain)


def test_recorded_installed_identity_survives_lost_discovery_coverage(installed, monkeypatch):
    _served, trio, _plain = installed

    def discovery_must_not_clear_recorded_identity(_path):
        raise AssertionError("the recorded installed identity already requires integration")

    monkeypatch.setattr(anchor_next, "is_installed_repo", discovery_must_not_clear_recorded_identity)
    error = code_jobs.integration_required_error({"repo": str(trio), "installed_repo": True})
    assert "was classified an installed skill repository" in error and "land_to" in error


def test_expected_integration_path_cannot_be_replaced_by_another_repository(installed, tmp_path):
    _served, trio, _plain = installed
    integration, why = anchor_next.ensure_integration(trio)
    assert integration is not None, why
    integration = Path(integration)
    assert integration.resolve().is_relative_to(tmp_path.resolve())
    _g(trio, "worktree", "move", str(integration), str(tmp_path / "preserved-integration"))
    foreign = _repo(integration, {"foreign.py": "UNCHANGED = True\n"})
    _g(foreign, "checkout", "-q", "-b", anchor_next.BRANCH)
    before = (_g(foreign, "rev-parse", "HEAD"), (foreign / "foreign.py").read_bytes())
    assert anchor_next.common_dir(foreign) != anchor_next.common_dir(trio)
    actual, why = anchor_next.ensure_integration(trio)
    assert actual is None and ("repository" in why or "common" in why), why
    assert (_g(foreign, "rev-parse", "HEAD"), (foreign / "foreign.py").read_bytes()) == before
    assert not _g(foreign, "status", "--porcelain")


def test_served_anchor_worktree_identity_keeps_the_existing_served_guard(installed, tmp_path):
    served, _trio, _plain = installed
    alias = tmp_path / "served-worktree"
    _g(served, "worktree", "add", "--detach", str(alias), "HEAD")
    assert anchor_next.is_served_repo(alias)
    assert not anchor_next.is_installed_repo(alias)


def test_the_cli_takes_the_installed_repository_by_name(installed, tmp_path, capsys):
    served, trio, plain = installed
    _, job = _run_job(tmp_path, trio, {"lib/a.py": "A = 2\n"})
    assert anchor_next._main(["anchor_next.py", "status", str(trio)]) == 0
    out = capsys.readouterr().out
    assert "1 change(s) landed on anchor-next wait for activation in %s" % trio in out and job["landed_commit"][:10] in out
    assert anchor_next._main(["anchor_next.py", "check", str(trio)]) == 0
    assert (trio / "lib" / "a.py").read_text(encoding="utf-8") == "A = 1\n", "check changes nothing"
    assert anchor_next._main(["anchor_next.py", "activate", str(trio)]) == 0
    assert (trio / "lib" / "a.py").read_text(encoding="utf-8") == "A = 2\n"
