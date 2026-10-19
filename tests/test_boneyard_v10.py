"""v10 Wave 6 — Boneyard store + capture wiring (backend only; no UI).

The Boneyard (Pillar 3, frozen design in ``planning/rnd-v10/MASTER-PLAN.md``) is a
per-project (D4), searchable INDEX over DISCARDED material (D9 — references the
already-persisted docs, never a second copy), fed by THREE locked sources (D3):

  1. ``killed``        — a hard-KILLED session that had produced material; the
                         session's normal finished tile is UNAFFECTED (additive).
  2. ``deleted``       — a v9-DELETED session — captured BEFORE
                         ``delete_session_efforts`` drops the pointer-records (D10);
                         the Boneyard is the deleted session's ONLY remaining home.
  3. ``grass-deleted`` — a DELETED grass idea — captured BEFORE the idea is purged.

Plus: stdlib search over title/summary/idea/doc terms; content-addressed
idempotency (re-record == one entry); SAFE projections (no absolute paths /
worktree / branch); and ``boneyard.py`` ships first-party stdlib-only.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, a temp git repo for the worktree, a tmp
data dir + tmp worktree base, the STUB summarizer runner. NEVER binds ``:8777``;
NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real push/gh/network.
"""
import importlib
import subprocess
from pathlib import Path

import pytest

STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# ── env / fixtures (stub PTY + temp git repo + project + STUB summarizer) ─────

@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "The locked north star is durable resumable work")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import effort_history
    import terminal_session
    import session_registry
    import summarizer
    import rnd_registry
    import boneyard

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "ts": terminal_session, "reg": session_registry, "eh": effort_history,
        "summ": summarizer, "rnd": rnd_registry, "bone": boneyard,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_build_docs(worktree_path, plan_dir="build/rnd-x"):
    wt = Path(worktree_path)
    north = f"{plan_dir}/NORTH-STAR.md"
    deliv = f"{plan_dir}/DELIVERABLE.md"
    log = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [
            (north, "# North Star\nThe locked north star is durable resumable work.\n"),
            (deliv, "# Deliverable\nThe widget cache service ships.\n"),
            (log, "# Execution Log\nWave 1 GREEN.\n")]:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return {"north": north, "deliv": deliv, "log": log}


def _make_killed_session(env, lane="build", plan_dir="build/rnd-x"):
    ts, summ, repo, pid = env["ts"], env["summ"], env["repo"], env["pid"]
    sess = ts.start_session(pid, lane, backend="claude")
    sid = sess["session_id"]
    docs = _write_build_docs(sess["worktree_path"], plan_dir=plan_dir)
    out = ts.kill(sid)
    assert out["docs"]["ok"] is True
    return sid, docs


# ════════════════════════════════════════════════════════════════════════════
# (1) KILL — a killed session with material leaves a "killed" entry; tile intact
# ════════════════════════════════════════════════════════════════════════════

def test_kill_with_material_records_killed_entry(env):
    ts, bone, reg, repo, pid = (env["ts"], env["bone"], env["reg"],
                                env["repo"], env["pid"])
    sid, docs = _make_killed_session(env, lane="build", plan_dir="build/kill1")

    entries = bone.list_entries(str(repo), pid)
    assert len(entries) == 1, entries
    e = entries[0]
    assert e["source"] == "killed"
    assert e["session_id"] == sid
    assert e["lane"] in ("build",)
    # References the doc's REL path (the v8 keystone already persisted it).
    assert any(r.endswith("DELIVERABLE.md") for r in e["doc_rels"]), e["doc_rels"]
    assert docs["deliv"] in e["doc_rels"]
    # A summary excerpt field is present (best-effort: filled from the cached
    # summary when one exists, honest "" while the proactive summary is still
    # generating — it is never fabricated and never blocks the kill).
    assert isinstance(e["summary_excerpt"], str)

    # The session's normal finished record/tile is UNAFFECTED (additive).
    rec = reg.get_session(sid)
    assert rec is not None
    assert rec["status"] == reg.STATUS_DONE
    # Docs are on disk (index, not a second copy — they live in the main folder).
    assert (repo / docs["deliv"]).is_file()


def test_summary_excerpt_surfaced_when_cached(env):
    """When a session summary IS cached, build_session_entry surfaces its text as
    the entry's summary_excerpt (best-effort; honest "" when uncached)."""
    import json as _json
    summ, bone, reg, repo, pid = (env["summ"], env["bone"], env["reg"],
                                  env["repo"], env["pid"])
    sid, _docs = _make_killed_session(env, lane="build", plan_dir="build/exc")
    # Write a valid cached summary directly (keyed to the managed session id).
    sdir = summ.summary_dir(str(repo), pid, "build", sid)
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / summ.SUMMARY_JSON).write_text(_json.dumps({
        "schema_version": summ.SUMMARY_SCHEMA_VERSION,
        "session_id": sid, "lane": "build", "title": "Cache build",
        "summary_text": "Built a durable widget cache service.",
        "claims": ["The cache service is durable."],
    }), encoding="utf-8")

    entry = bone.build_session_entry(str(repo), pid, "build", sid,
                                     source="killed", record=reg.get_session(sid))
    assert "durable widget cache service" in entry["summary_excerpt"]


def test_kill_no_material_records_no_entry(env):
    """A hard-kill of a session that produced NOTHING leaves no Boneyard entry."""
    ts, bone, repo, pid = env["ts"], env["bone"], env["repo"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude")
    sid = sess["session_id"]
    # No docs written → kill persists nothing → no material → no entry.
    ts.kill(sid)
    assert bone.list_entries(str(repo), pid) == []


# ════════════════════════════════════════════════════════════════════════════
# (2) v9-DELETE ORDERING (D10) — capture BEFORE delete_session_efforts drops them
# ════════════════════════════════════════════════════════════════════════════

def test_delete_captures_entry_before_efforts_dropped(env):
    ts, eh, bone, reg, repo, pid = (env["ts"], env["eh"], env["bone"],
                                    env["reg"], env["repo"], env["pid"])
    sid, docs = _make_killed_session(env, lane="build", plan_dir="build/del1")

    # Pre: the session-tagged efforts (the docs) exist BEFORE delete.
    tagged = eh.efforts_for_session_id(str(repo), pid, "build", sid)
    assert tagged, "expected session-tagged efforts before delete"

    out = ts.delete_session(sid)
    assert out["ok"] is True and out["deleted"] is True

    # The v9-delete dropped the pointer-records (the join is now EMPTY) ...
    assert eh.efforts_for_session_id(str(repo), pid, "build", sid) == []
    # ... AND the registry record is gone (its ONLY home is now the Boneyard).
    assert reg.get_session(sid) is None

    # ... YET a "deleted" Boneyard entry was captured with NON-EMPTY doc_rels —
    # proving the capture happened BEFORE the drop (D10).
    deleted = [e for e in bone.list_entries(str(repo), pid)
               if e["source"] == "deleted" and e["session_id"] == sid]
    assert len(deleted) == 1, bone.list_entries(str(repo), pid)
    assert deleted[0]["doc_rels"], "deleted entry lost its doc_rels (D10 violation)"
    assert docs["deliv"] in deleted[0]["doc_rels"]

    # OPTION A: the produced DOCUMENTS still exist on disk after the delete.
    assert (repo / docs["deliv"]).is_file()
    assert (repo / docs["north"]).is_file()


# ════════════════════════════════════════════════════════════════════════════
# (2b) LIVE DELETE (DEFECT 1) — deleting a STILL-RUNNING session that produced a
#      doc yields EXACTLY ONE Boneyard entry (source "deleted") WITH its docs.
#      Pre-fix the kill-as-part-of-delete fired a "killed" capture too → 2 entries.
# ════════════════════════════════════════════════════════════════════════════

def test_delete_live_session_records_single_deleted_entry(env):
    ts, eh, bone, reg, repo, pid = (env["ts"], env["eh"], env["bone"],
                                    env["reg"], env["repo"], env["pid"])
    # Start a session and write a doc, but DO NOT kill it — it stays LIVE/RUNNING.
    sess = ts.start_session(pid, "build", backend="claude")
    sid = sess["session_id"]
    docs = _write_build_docs(sess["worktree_path"], plan_dir="build/live-del")
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    # Delete the LIVE session: delete_session kills it first (persisting docs),
    # then records the canonical "deleted" entry. The kill's "killed" capture is
    # SUPPRESSED, so there must be EXACTLY ONE Boneyard entry total.
    out = ts.delete_session(sid)
    assert out["ok"] is True and out["deleted"] is True and out["killed"] is True

    all_entries = bone.list_entries(str(repo), pid)
    assert len(all_entries) == 1, all_entries  # FAILS pre-fix (killed + deleted = 2)
    e = all_entries[0]
    assert e["source"] == "deleted", e
    assert e["session_id"] == sid
    # The "deleted" entry carries the docs (kill still persisted them before reap).
    assert docs["deliv"] in e["doc_rels"], e["doc_rels"]
    # No spurious "killed" entry for the same delete.
    assert not [x for x in all_entries if x["source"] == "killed"], all_entries
    # OPTION A: the produced documents survive on disk.
    assert (repo / docs["deliv"]).is_file()


# ════════════════════════════════════════════════════════════════════════════
# (3) GRASS-DELETE — a deleted idea leaves a "grass-deleted" entry w/ idea text
# ════════════════════════════════════════════════════════════════════════════

def test_grass_delete_records_idea_text(env):
    eh, bone, repo, pid = env["eh"], env["bone"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Whisper voice control for the cache layer")
    iid = idea["job_id"]
    # A versioned refinement referencing a produced artifact rel.
    eh.save_grass_refinement(repo, pid, iid, text="v1 notes",
                             label="r1", artifacts=["grass/dev/whisper.md"])

    out = eh.delete_grass_idea(repo, pid, iid)
    assert out["ok"] is True and out["deleted"] is True
    assert eh.get_grass_idea(repo, pid, iid) is None  # idea purged

    grass = [e for e in bone.list_entries(str(repo), pid)
             if e["source"] == "grass-deleted"]
    assert len(grass) == 1, bone.list_entries(str(repo), pid)
    e = grass[0]
    assert "Whisper voice control" in e["idea_text"]
    assert e["lane"] == "grass"
    # The refinement artifact rel was captured.
    assert "grass/dev/whisper.md" in e["doc_rels"]


# ════════════════════════════════════════════════════════════════════════════
# (3b) ARCHIVE → DELETE (DEFECT 2) — an idea ARCHIVED then deleted carries its W4
#      archive bundle docs into the "grass-deleted" Boneyard entry's doc_rels.
#      Pre-fix build_grass_entry folded only refinement artifacts, NOT archives.
# ════════════════════════════════════════════════════════════════════════════

def test_grass_delete_carries_archive_docs(env):
    eh, bone, repo, pid = env["eh"], env["bone"], env["repo"], env["pid"]
    idea = eh.add_idea(repo, pid, "Adaptive prefetch for the cache layer")
    iid = idea["job_id"]

    # Develop the idea in a contained 'research' dev session, produce a doc in its
    # worktree, then ARCHIVE it (W4) → a per-idea archive bundle of persisted docs.
    dev = eh.develop_grass_idea(pid, iid, "research", folder_path=str(repo))
    wt = Path(dev["worktree_path"])
    arch_rel = "research/grass-dev/PREFETCH-NOTES.md"
    p = wt / arch_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Prefetch notes\nAdaptive prefetch for the cache layer.\n",
                 encoding="utf-8")
    res = eh.archive_grass_session(pid, iid, "research", folder_path=str(repo))
    assert res["ok"] is True, res
    # Sanity: the archive bundle is on the idea record now.
    archives = eh.list_grass_archives(str(repo), pid, iid)
    assert archives and any(arch_rel in (b.get("docs") or []) for b in archives), \
        archives

    # Delete the idea — the "grass-deleted" Boneyard entry must carry the archived
    # doc rel (FAILS pre-fix: only refinement artifacts were folded in).
    out = eh.delete_grass_idea(repo, pid, iid)
    assert out["ok"] is True and out["deleted"] is True

    grass = [e for e in bone.list_entries(str(repo), pid)
             if e["source"] == "grass-deleted" and e["idea_text"]]
    assert len(grass) == 1, bone.list_entries(str(repo), pid)
    assert arch_rel in grass[0]["doc_rels"], grass[0]["doc_rels"]
    # OPTION A: the archived doc survives on disk in the main folder.
    assert (repo / arch_rel).is_file()


# ════════════════════════════════════════════════════════════════════════════
# (4) SEARCH — token/substring match over title/summary/idea/doc; case-insensitive
# ════════════════════════════════════════════════════════════════════════════

def test_search_filters_matching_entries(env):
    ts, eh, bone, repo, pid = (env["ts"], env["eh"], env["bone"],
                               env["repo"], env["pid"])
    # Entry A (killed): a build with a DELIVERABLE.md doc + "cache" in the summary.
    sid_a, _ = _make_killed_session(env, lane="build", plan_dir="build/cache-svc")
    # Entry B (grass-deleted): an idea about "telemetry".
    idea = eh.add_idea(repo, pid, "Telemetry dashboard for the runner")
    eh.delete_grass_idea(repo, pid, idea["job_id"])

    all_entries = bone.list_entries(str(repo), pid)
    assert len(all_entries) == 2

    # Search by a doc-path/filename term (the build's plan_dir / filename).
    cache_hits = bone.search(str(repo), pid, "cache")
    assert all(e["source"] == "killed" for e in cache_hits)
    assert any(e["session_id"] == sid_a for e in cache_hits)
    assert all(e["source"] != "grass-deleted" for e in cache_hits)

    # Search by an idea-text term, case-insensitive.
    tele = bone.search(str(repo), pid, "TELEMETRY")
    assert len(tele) == 1 and tele[0]["source"] == "grass-deleted"

    # A non-matching term returns nothing; an empty query returns all.
    assert bone.search(str(repo), pid, "zzz-no-such-term") == []
    assert len(bone.search(str(repo), pid, "")) == 2

    # NON-DESTRUCTIVE: searching removed no entries / no docs.
    assert len(bone.list_entries(str(repo), pid)) == 2


# ════════════════════════════════════════════════════════════════════════════
# (5) IDEMPOTENCY — re-recording the same discard yields ONE entry (upsert)
# ════════════════════════════════════════════════════════════════════════════

def test_record_entry_idempotent_upsert(env):
    bone, repo, pid = env["bone"], env["repo"], env["pid"]
    entry = {
        "source": "killed", "session_id": "sid-1", "lane": "build",
        "title": "build session", "summary_excerpt": "did a thing",
        "doc_rels": ["build/x/DELIVERABLE.md", "build/x/NORTH-STAR.md"],
    }
    r1 = bone.record_entry(str(repo), pid, entry)
    r2 = bone.record_entry(str(repo), pid, dict(entry))  # same content
    # Same content-addressed id; ONE entry in the index.
    assert r1["entry_id"] == r2["entry_id"]
    entries = bone.list_entries(str(repo), pid)
    assert len(entries) == 1
    assert entries[0]["entry_id"] == r1["entry_id"]
    # The first-write timestamp is preserved across the re-record.
    assert r2["when"] == r1["when"]


def test_kill_then_idempotent_rekill_one_entry(env):
    """Killing a session whose docs were already persisted, then re-killing
    (re-recording the same material), yields exactly ONE Boneyard entry."""
    ts, bone, repo, pid = env["ts"], env["bone"], env["repo"], env["pid"]
    sid, _docs = _make_killed_session(env, lane="build", plan_dir="build/redo")
    # A second kill of the same (now done) session re-persists nothing new and
    # re-records the SAME content-addressed entry → still one entry.
    ts.kill(sid)
    killed = [e for e in bone.list_entries(str(repo), pid)
              if e["source"] == "killed" and e["session_id"] == sid]
    assert len(killed) == 1, bone.list_entries(str(repo), pid)


# ════════════════════════════════════════════════════════════════════════════
# (6) SAFE — list_entries / get_entry never leak absolute paths / worktree / branch
# ════════════════════════════════════════════════════════════════════════════

def test_entries_are_safe_projections(env):
    bone, repo, pid = env["bone"], env["repo"], env["pid"]
    sid, _docs = _make_killed_session(env, lane="build", plan_dir="build/safe")

    safe_keys = set(bone._SAFE_KEYS)
    for e in bone.list_entries(str(repo), pid):
        assert set(e.keys()) == safe_keys, e.keys()
        assert "worktree_path" not in e and "branch" not in e
        # No absolute path / no worktree-base leak in doc_rels.
        for r in e["doc_rels"]:
            assert not Path(r).is_absolute(), r
            assert str(env["wbase"]) not in r
            assert str(repo) not in r

    # get_entry returns the same SAFE shape (or None for unknown).
    eid = bone.list_entries(str(repo), pid)[0]["entry_id"]
    one = bone.get_entry(str(repo), pid, eid)
    assert one is not None and set(one.keys()) == safe_keys
    assert bone.get_entry(str(repo), pid, "bone-nope") is None


# ════════════════════════════════════════════════════════════════════════════
# (6b) CROSS-PROJECT ISOLATION (coverage) — a kill/delete in project A writes ONLY
#      into A's Boneyard; list_entries(B) / search(B) never see A's entry.
# ════════════════════════════════════════════════════════════════════════════

def test_boneyard_is_per_project_isolated(env, tmp_path):
    ts, bone, rnd, repo, pid_a = (env["ts"], env["bone"], env["rnd"],
                                  env["repo"], env["pid"])
    # A SECOND, independent project B in its own git repo.
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    _git(repo_b, "init", "-b", "main")
    _git(repo_b, "config", "user.email", "t@example.com")
    _git(repo_b, "config", "user.name", "Test")
    (repo_b / "README.md").write_text("hello b\n", encoding="utf-8")
    _git(repo_b, "add", "-A")
    _git(repo_b, "commit", "-m", "initial")
    proj_b = rnd.add_project("TempB", str(repo_b), scaffold=False)
    pid_b = proj_b["id"]

    # A kill in project A writes ONE entry into A's Boneyard.
    sid_a, docs = _make_killed_session(env, lane="build", plan_dir="build/iso")
    a_entries = bone.list_entries(str(repo), pid_a)
    assert len(a_entries) == 1 and a_entries[0]["session_id"] == sid_a

    # Project B's Boneyard is EMPTY — it never sees A's entry (list OR search).
    assert bone.list_entries(str(repo_b), pid_b) == []
    assert bone.search(str(repo_b), pid_b, "") == []
    # Search B for a term unique to A's entry → still nothing leaks across.
    assert bone.search(str(repo_b), pid_b, "DELIVERABLE") == []
    assert all(e["session_id"] != sid_a
               for e in bone.list_entries(str(repo_b), pid_b))


# ════════════════════════════════════════════════════════════════════════════
# (7) BEST-EFFORT — a Boneyard failure never breaks kill / delete / grass-delete
# ════════════════════════════════════════════════════════════════════════════

def test_boneyard_failure_does_not_break_kill(env, monkeypatch):
    ts, bone, reg, repo, pid = (env["ts"], env["bone"], env["reg"],
                                env["repo"], env["pid"])
    monkeypatch.setattr(bone, "record_entry",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    sid, docs = _make_killed_session(env, lane="build", plan_dir="build/boom")
    # Kill still succeeded: docs persisted + record DONE despite Boneyard raising.
    assert (repo / docs["deliv"]).is_file()
    assert reg.get_session(sid)["status"] == reg.STATUS_DONE


def test_boneyard_failure_does_not_break_delete(env, monkeypatch):
    ts, bone, eh, reg, repo, pid = (env["ts"], env["bone"], env["eh"],
                                    env["reg"], env["repo"], env["pid"])
    sid, _docs = _make_killed_session(env, lane="build", plan_dir="build/boom2")
    monkeypatch.setattr(bone, "record_entry",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = ts.delete_session(sid)
    assert out["ok"] is True and out["deleted"] is True
    assert reg.get_session(sid) is None
    assert eh.efforts_for_session_id(str(repo), pid, "build", sid) == []


# ════════════════════════════════════════════════════════════════════════════
# (8) DISTRO — boneyard.py ships first-party stdlib-only; scan clean
# ════════════════════════════════════════════════════════════════════════════

def test_boneyard_ships_and_scans_clean():
    import distro
    selected = set(distro.select_shippable())
    assert "boneyard.py" in selected, "boneyard.py should ship"
    pairs = [("boneyard.py", distro.REPO_ROOT / "boneyard.py")]
    hits = distro.scan_third_party_imports(pairs, root=distro.REPO_ROOT)
    assert hits == [], f"boneyard.py leaks a third-party import: {hits}"
