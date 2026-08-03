"""W11 (C6) gate — Data-Dir Migration + Git Hygiene (frozen plan: Wave 13).

Proves the four W11 deliverables, hermetically (temp data dirs + temp git repos;
never :8777, never the real data, never the network):

1. **Path-audit tool** (``tools/path_audit.py``) — finds every repo-rooted
   absolute path across the durable stores (registry folder_path, sessions
   worktree_path, job log_path/cwd, discovery paths), emits a rewrite map, and
   applies it atomically + idempotently; the relocated-data subset is rewritten
   while a project's own-repo ``folder_path`` is left untouched.
2. **Scripted migration unit** (``tools/migrate_data_dir.py``) — copy →
   path-rewrite → verify → arm-reaper, with preflight refusals and rollback (the
   partial new root is removed on failure; the old root is never mutated).
3. **ANCHOR_REAPER_DRYRUN** (``worktrees.reap_orphans``) — the first post-move
   boot sweeps report-only (env OR the armed marker); a clean dry report re-arms
   live reaping, an unclean one holds; nothing is deleted while dry.
4. **Git hygiene** (``tools/git_hygiene.py`` + ``.gitignore``) — the tracked
   runtime artifacts are classified + un-tracked so a full write cycle leaves
   ``git status --porcelain`` empty, with runtime writes landing OUTSIDE the repo.
"""

import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import paths
import worktrees
from tools import path_audit
from tools import git_hygiene
from tools import migrate_data_dir


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────

def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_needs_git = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


def _run_git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _seed_data_dir(root: Path, old_root: Path):
    """Seed a data dir whose stores carry OLD-root absolute paths."""
    old = str(old_root)
    (root / ".anchor" / "worktrees").mkdir(parents=True, exist_ok=True)
    (root / "rnd_jobs").mkdir(parents=True, exist_ok=True)
    (root / ".anchor" / "projects" / "p1").mkdir(parents=True, exist_ok=True)
    (root / "domains").mkdir(parents=True, exist_ok=True)

    # registry: a SELF project (folder_path == repo root, must NOT move) + an
    # external project (elsewhere, untouched).
    (root / "rnd_registry.json").write_text(json.dumps([
        {"id": "p1", "name": "self", "folder_path": old},
        {"id": "p2", "name": "ext", "folder_path": r"Q:\proj\OtherRepo"},
    ]), encoding="utf-8")

    # sessions: a worktree UNDER the data dir (relocates) + a blank one.
    (root / ".anchor" / "sessions.json").write_text(json.dumps([
        {"session_id": "s1",
         "worktree_path": os.path.join(old, ".anchor", "worktrees", "s1")},
        {"session_id": "s2", "worktree_path": ""},
    ]), encoding="utf-8")

    # job record: log_path + cwd both UNDER the data dir (relocate).
    (root / "rnd_jobs" / "j1.json").write_text(json.dumps({
        "job_id": "j1",
        "log_path": os.path.join(old, "rnd_jobs", "j1.log"),
        "cwd": os.path.join(old, ".anchor", "worktrees", "s1"),
        "note": "not-a-path",
    }), encoding="utf-8")

    # discovery: references a planning doc under the PROJECT tree (stays put).
    (root / ".anchor" / "projects" / "p1" / "discovery.json").write_text(
        json.dumps({"doc": os.path.join(old, "planning", "x.md")}),
        encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 1) path-audit — string-rewrite mechanics
# ══════════════════════════════════════════════════════════════════════════

class TestPathAuditMechanics:
    def test_under_root_is_rewritten(self):
        old = r"Q:\proj\Anchor"
        new = r"D:\AnchorData"
        got = path_audit.rewrite_string(
            r"Q:\proj\Anchor\.anchor\worktrees\s1", old, new)
        assert got == r"D:\AnchorData\.anchor\worktrees\s1"

    def test_exact_root_rewrites_to_new_root(self):
        old = r"Q:\proj\Anchor"
        assert path_audit.rewrite_string(old, old, r"D:\X") == r"D:\X"

    def test_not_under_root_is_left_alone(self):
        assert path_audit.rewrite_string(
            r"Q:\proj\Other\file", r"Q:\proj\Anchor", r"D:\X") is None
        # a sibling with a shared prefix but not a path boundary is NOT under.
        assert path_audit.rewrite_string(
            r"Q:\proj\Anchor2\file", r"Q:\proj\Anchor", r"D:\X") is None

    def test_case_and_separator_insensitive_match(self):
        # forward slashes + mixed case still match on Windows (case-insensitive).
        got = path_audit.rewrite_string(
            "Q:/PROJ/anchor/rnd_jobs/j.log", r"Q:\proj\Anchor", r"D:\New")
        if os.name == "nt":
            assert got == os.path.join(r"D:\New", "rnd_jobs", "j.log")
        else:
            # POSIX is case-sensitive; the mixed-case value simply won't match.
            assert got is None or got.startswith("D:")

    def test_non_string_and_empty_return_none(self):
        for v in (None, 123, "", [], {}):
            assert path_audit.rewrite_string(v, r"C:\a", r"C:\b") is None

    def test_segment_filter_keeps_repo_paths(self):
        old = r"Q:\proj\Anchor"
        # folder_path == repo root (empty tail) is NOT relocated data.
        assert path_audit.rewrite_string(
            old, old, r"D:\X", path_audit.RELOCATED_SEGMENTS) is None
        # a planning-doc path (project tree) is NOT relocated data.
        assert path_audit.rewrite_string(
            old + r"\planning\x.md", old, r"D:\X",
            path_audit.RELOCATED_SEGMENTS) is None
        # a worktree path IS relocated data.
        assert path_audit.rewrite_string(
            old + r"\.anchor\worktrees\s1", old, r"D:\X",
            path_audit.RELOCATED_SEGMENTS) == r"D:\X\.anchor\worktrees\s1"


# ══════════════════════════════════════════════════════════════════════════
# 2) path-audit — the durable stores
# ══════════════════════════════════════════════════════════════════════════

class TestPathAuditStores:
    def test_full_audit_reports_every_repo_rooted_path(self, tmp_path):
        data = tmp_path / "data"
        _seed_data_dir(data, data)
        new = tmp_path / "new"
        rmap = path_audit.audit_data_dir(data, str(data), str(new))
        # every store with a repo-rooted path is present.
        assert "rnd_registry.json" in rmap
        assert ".anchor/sessions.json" in rmap
        assert "rnd_jobs/j1.json" in rmap
        assert ".anchor/projects/p1/discovery.json" in rmap
        # the external project's folder_path (elsewhere) is never reported.
        reg = rmap["rnd_registry.json"]
        assert all("OtherRepo" not in c["old"] for c in reg)

    def test_safe_apply_rewrites_only_relocated_data(self, tmp_path):
        data = tmp_path / "data"
        _seed_data_dir(data, data)
        new = tmp_path / "AnchorData"
        rep = path_audit.apply_rewrites(data, str(data), str(new))
        assert rep["total"] >= 3          # worktree + job log + job cwd

        sessions = json.loads((data / ".anchor" / "sessions.json").read_text())
        assert sessions[0]["worktree_path"].startswith(str(new))
        assert sessions[1]["worktree_path"] == ""          # blank untouched

        job = json.loads((data / "rnd_jobs" / "j1.json").read_text())
        assert job["log_path"].startswith(str(new))
        assert job["cwd"].startswith(str(new))
        assert job["note"] == "not-a-path"

        reg = json.loads((data / "rnd_registry.json").read_text())
        self_p = next(p for p in reg if p["id"] == "p1")
        # the self project's folder_path (its own repo) is KEPT at the old root.
        assert self_p["folder_path"] == str(data)

        disc = json.loads(
            (data / ".anchor" / "projects" / "p1" / "discovery.json").read_text())
        # the planning-doc path (project tree) is KEPT, not relocated.
        assert disc["doc"] == os.path.join(str(data), "planning", "x.md")

    def test_apply_is_idempotent_and_verify_clean(self, tmp_path):
        data = tmp_path / "data"
        _seed_data_dir(data, data)
        new = tmp_path / "AnchorData"
        path_audit.apply_rewrites(data, str(data), str(new))
        second = path_audit.apply_rewrites(data, str(data), str(new))
        assert second["total"] == 0
        # verify: no RELOCATED store still points under the old root.
        assert path_audit.remaining_repo_rooted(data, str(data)) == {}


# ══════════════════════════════════════════════════════════════════════════
# 3) scripted migration unit
# ══════════════════════════════════════════════════════════════════════════

class TestMigrationUnit:
    def test_preflight_refusals(self, tmp_path):
        old = tmp_path / "old"
        old.mkdir()
        assert migrate_data_dir.preflight(old, old)[1] == "same-root"
        assert migrate_data_dir.preflight(old, old / "sub")[1] == \
            "new-root-inside-old"
        new = tmp_path / "new"
        new.mkdir()
        (new / "keep.txt").write_text("x", encoding="utf-8")
        assert migrate_data_dir.preflight(old, new)[1] == "new-root-not-empty"
        assert migrate_data_dir.preflight(tmp_path / "missing", new)[1] == \
            "old-root-missing"

    def test_migration_copies_rewrites_verifies_arms(self, tmp_path):
        old = tmp_path / "old"
        _seed_data_dir(old, old)
        (old / "DASHBOARD.md").write_text("# D\n- [ ] task-A\n", encoding="utf-8")
        new = tmp_path / "AnchorData"

        rep = migrate_data_dir.run_migration(old, new)
        assert rep["ok"] is True, rep
        assert rep["verified"] is True
        assert rep["reaper_armed"] is True
        assert rep["rewrites"]["total"] >= 3

        # data copied with zero loss.
        assert (new / "DASHBOARD.md").read_text(encoding="utf-8").startswith("# D")
        assert (new / "rnd_registry.json").exists()
        # relocated paths point at the NEW root.
        sessions = json.loads((new / ".anchor" / "sessions.json").read_text())
        assert sessions[0]["worktree_path"].startswith(str(new))
        # the self-project folder_path is kept (its repo did not move).
        reg = json.loads((new / "rnd_registry.json").read_text())
        assert next(p for p in reg if p["id"] == "p1")["folder_path"] == str(old)
        # reaper dry-run armed under the NEW managed base.
        marker = new / ".anchor" / "worktrees" / worktrees.REAPER_DRYRUN_MARKER
        assert marker.exists()
        # OLD dir untouched (rollback source).
        assert (old / "DASHBOARD.md").exists()

    def test_migration_rolls_back_on_verify_failure(self, tmp_path, monkeypatch):
        old = tmp_path / "old"
        _seed_data_dir(old, old)
        new = tmp_path / "AnchorData"

        # Force the verify step to report a lingering repo-rooted path.
        monkeypatch.setattr(
            migrate_data_dir.path_audit, "remaining_repo_rooted",
            lambda *a, **k: {"rnd_jobs/j1.json": [{"pointer": "/log_path",
                                                    "old": "x"}]})
        rep = migrate_data_dir.run_migration(old, new)
        assert rep["ok"] is False
        assert rep["rolled_back"] is True
        # the partial new root was removed; the old root is intact.
        assert not new.exists()
        assert (old / "rnd_registry.json").exists()


# ══════════════════════════════════════════════════════════════════════════
# 4) reaper dry-run
# ══════════════════════════════════════════════════════════════════════════

class TestReaperDryrun:
    @pytest.fixture
    def base(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("ANCHOR_REAPER_DRYRUN", raising=False)
        b = tmp_path / "wtbase"
        (b / "sidA").mkdir(parents=True)
        (b / "sidB").mkdir(parents=True)
        return b

    def test_explicit_dryrun_reports_and_deletes_nothing(self, base):
        r = worktrees.reap_orphans(set(), base=base, dryrun=True)
        assert r["dryrun"] is True
        assert set(r["would_reap"]) == {"sidA", "sidB"}
        assert r["reaped"] == []
        assert (base / "sidA").exists() and (base / "sidB").exists()

    def test_real_reap_deletes(self, base):
        r = worktrees.reap_orphans(set(), base=base, dryrun=False)
        assert set(r["reaped"]) == {"sidA", "sidB"}
        assert not (base / "sidA").exists()

    def test_active_and_parked_are_kept_even_when_dry(self, base):
        r = worktrees.reap_orphans({"sidA"}, base=base, dryrun=True)
        assert "sidA" in r["kept"]
        assert r["would_reap"] == ["sidB"]

    def test_marker_arms_and_clean_report_rearms(self, base):
        worktrees.arm_reaper_dryrun(base=base)
        assert worktrees.reaper_dryrun_marker(base=base).exists()
        assert worktrees.reaper_dryrun_active(base=base) is True

        # unclean dry sweep (orphans present) → marker HELD.
        r = worktrees.reap_orphans(set(), base=base)     # dryrun from marker
        assert r["dryrun"] is True and r["would_reap"]
        assert worktrees.reaper_dryrun_marker(base=base).exists()

        # clean dry sweep (all active) → marker CLEARED (live reaping re-armed).
        r = worktrees.reap_orphans({"sidA", "sidB"}, base=base)
        assert r["dryrun"] is True and r["would_reap"] == []
        assert not worktrees.reaper_dryrun_marker(base=base).exists()
        assert worktrees.reaper_dryrun_active(base=base) is False

    def test_env_override_forces_dryrun(self, base, monkeypatch):
        monkeypatch.setenv("ANCHOR_REAPER_DRYRUN", "1")
        r = worktrees.reap_orphans(set(), base=base)
        assert r["dryrun"] is True
        assert (base / "sidA").exists()


# ══════════════════════════════════════════════════════════════════════════
# 5) git hygiene
# ══════════════════════════════════════════════════════════════════════════

class TestRuntimeClassifier:
    def test_runtime_paths_classify_true(self):
        for rel in ("rnd_registry.json", "dashboard.html",
                    "logs/2026-07.md", "rnd_jobs/j.json",
                    "health_reports/2026-07-04.md", "_foreman-x.log",
                    "_census.log", "pytest_stdout.txt",
                    ".anchor/sessions.json",
                    ".anchor/projects/abcd/discovery.json",
                    ".anchor/projects/abcd/jobs/k.json"):
            assert git_hygiene.classify_runtime(rel) is True, rel

    def test_product_and_gate_paths_classify_false(self):
        for rel in ("anchor_gui.py", "anchor.py", "tools/path_audit.py",
                    "tests/test_data_dir_migration_w11.py",
                    "docs/anchor_server-predeletion-sweep.md",
                    "OPEN_ROUTES.json", "dist_manifest.txt",
                    ".anchor/projects/abcd/index.json",
                    ".anchor/projects/abcd/planning/summaries/x/summary.json"):
            assert git_hygiene.classify_runtime(rel) is False, rel


class TestGitignoreMirror:
    def test_gitignore_carries_the_runtime_rules(self):
        gi = (paths.CODE_DIR / ".gitignore").read_text(encoding="utf-8")
        for rule in ("rnd_registry.json", "dashboard.html", "_*.log",
                     ".anchor/projects/*/discovery.json"):
            assert rule in gi, f".gitignore missing runtime rule: {rule}"


class TestGitHygieneGate:
    @_needs_git
    def test_untrack_leaves_porcelain_empty_through_write_cycle(
            self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init")
        _run_git(repo, "config", "user.email", "t@t")
        _run_git(repo, "config", "user.name", "t")

        # copy the REAL ignore policy so classify_runtime ↔ .gitignore agree.
        (repo / ".gitignore").write_text(
            (paths.CODE_DIR / ".gitignore").read_text(encoding="utf-8"),
            encoding="utf-8")
        (repo / ".anchor").mkdir()
        src_anchor_gi = paths.CODE_DIR / ".anchor" / ".gitignore"
        if src_anchor_gi.exists():
            (repo / ".anchor" / ".gitignore").write_text(
                src_anchor_gi.read_text(encoding="utf-8"), encoding="utf-8")

        # product / gate / pointer files (must stay tracked).
        (repo / "anchor_gui.py").write_text("x", encoding="utf-8")
        (repo / "OPEN_ROUTES.json").write_text("{}", encoding="utf-8")
        (repo / ".anchor" / "projects" / "p").mkdir(parents=True)
        (repo / ".anchor" / "projects" / "p" / "index.json").write_text(
            "{}", encoding="utf-8")

        # runtime artifacts (the ~62-class the hygiene commit un-tracks).
        (repo / "rnd_registry.json").write_text("[]", encoding="utf-8")
        (repo / "dashboard.html").write_text("<html>", encoding="utf-8")
        (repo / "logs").mkdir()
        (repo / "logs" / "2026.md").write_text("x", encoding="utf-8")
        (repo / "rnd_jobs").mkdir()
        (repo / "rnd_jobs" / "j.json").write_text("{}", encoding="utf-8")
        (repo / "health_reports").mkdir()
        (repo / "health_reports" / "r.md").write_text("x", encoding="utf-8")
        (repo / "_foreman-x.log").write_text("x", encoding="utf-8")
        (repo / ".anchor" / "sessions.json").write_text("[]", encoding="utf-8")
        (repo / ".anchor" / "projects" / "p" / "discovery.json").write_text(
            "{}", encoding="utf-8")

        # historical state: everything is tracked (force past the .gitignore).
        _run_git(repo, "add", "-A", "-f")
        _run_git(repo, "commit", "-m", "seed")

        arts = git_hygiene.tracked_runtime_artifacts(repo)
        for expect in ("rnd_registry.json", "dashboard.html", "logs/2026.md",
                       "rnd_jobs/j.json", "health_reports/r.md",
                       "_foreman-x.log", ".anchor/sessions.json",
                       ".anchor/projects/p/discovery.json"):
            assert expect in arts, (expect, arts)
        for keep in ("anchor_gui.py", "OPEN_ROUTES.json",
                     ".anchor/projects/p/index.json", ".gitignore"):
            assert keep not in arts, keep

        # hygiene: un-track + commit the removals.
        rep = git_hygiene.run_hygiene(repo)
        assert rep["count"] == len(arts)
        _run_git(repo, "commit", "-m", "git hygiene: untrack runtime artifacts")

        # the repo is clean and the un-tracked files still exist on disk.
        assert git_hygiene.porcelain(repo) == []
        assert (repo / "rnd_registry.json").exists()
        assert (repo / "anchor_gui.py").exists()

        # a full write cycle IN the repo (runtime rewrites) — still clean.
        (repo / "rnd_registry.json").write_text("[1]", encoding="utf-8")
        (repo / "health_reports" / "r2.md").write_text("y", encoding="utf-8")
        (repo / "logs" / "2026-08.md").write_text("z", encoding="utf-8")
        assert git_hygiene.porcelain(repo) == []

    @_needs_git
    def test_runtime_writes_land_outside_the_repo(self, tmp_path, monkeypatch):
        """The done-when: with ANCHOR_DATA_DIR outside the repo, a health-report
        write lands outside and the repo's porcelain stays empty."""
        repo = tmp_path / "repo2"
        repo.mkdir()
        _run_git(repo, "init")
        _run_git(repo, "config", "user.email", "t@t")
        _run_git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(
            (paths.CODE_DIR / ".gitignore").read_text(encoding="utf-8"),
            encoding="utf-8")
        (repo / "anchor_gui.py").write_text("x", encoding="utf-8")
        _run_git(repo, "add", "-A")
        _run_git(repo, "commit", "-m", "seed")
        assert git_hygiene.porcelain(repo) == []

        data = tmp_path / "AnchorData"
        monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
        importlib.reload(paths)
        paths.ensure_data_dirs()
        (paths.health_reports_dir() / "2026-07-04.md").write_text(
            "# ok\n", encoding="utf-8")
        (paths.logs_dir() / "2026-07-04.md").write_text("log\n", encoding="utf-8")

        # the writes landed OUTSIDE the repo; the repo stays clean.
        assert (data / "health_reports" / "2026-07-04.md").exists()
        assert git_hygiene.porcelain(repo) == []
        importlib.reload(paths)          # restore default for later tests
