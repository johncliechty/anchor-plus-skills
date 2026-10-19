"""Wave 3 STUB GATE — Resume backend keystone (Pillar A, crucible-improve #6 + #3).

Frozen plan (``planning/crucible-improve-2026-06-30/IMPLEMENTATION-PLAN.md`` §Wave 3):

  - **#6 backend** — when ``anchor_gui._build_continue_seed`` finds no registry
    record / cached summary (a discovered/brownfield effort), it SYNTHESIZES a
    seed from the on-disk docs: the detected phase, the enumerated document list,
    and the chosen trio skill — so a resumed turn opens WARM, not cold.
  - **#3 data** — ``effort_view.build_effort_view`` folds discovered efforts in as
    first-class efforts: the docs of a discovered session are grouped as MEMBERS
    of ONE effort, NOT loose per-file singletons.

STUB GATE (verbatim from the plan): given a temp project with discovered docs and
NO registry/summary, ``_build_continue_seed`` returns a NON-empty seed containing
the doc list + chosen skill + detected phase; ``build_effort_view`` groups the
discovered effort as a member (not a ``loose::`` singleton).

Hermetic: temp data dir, stub PTY backend, the fake runner — NEVER ``:8777`` /
real data / network / a live model. No git required (pure read paths).
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Reload the stack against a temp data dir + a brownfield project whose
    docs are adopted as DISCOVERED efforts with NO registry record / summary."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "brownfield_scan", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import rnd_registry, effort_history, sessions, brownfield_scan, effort_view

    folder = tmp_path / "proj"
    # A brownfield planning effort: TWO planning docs sharing one parent dir →
    # ONE discovered session of two member docs (the grouping under test).
    (folder / "planning" / "rnd-x").mkdir(parents=True, exist_ok=True)
    (folder / "planning" / "rnd-x" / "MASTER-PLAN.md").write_text(
        "# Master Plan\n## North Star\nDurable resumable work.\n",
        encoding="utf-8")
    (folder / "planning" / "rnd-x" / "IMPLEMENTATION-PLAN.md").write_text(
        "# Implementation Plan\n## Goal\nResume sessions warm.\n",
        encoding="utf-8")
    # A brownfield research effort: a report under a research store.
    (folder / "research").mkdir(parents=True, exist_ok=True)
    (folder / "research" / "report.md").write_text(
        "# Research report\nThe cooling system is adequate.\n", encoding="utf-8")

    proj = rnd_registry.add_project("Brownfield", str(folder), scaffold=False)
    pid = proj["id"]
    # Adopt the on-disk artifacts as DISCOVERED efforts. NO managed session is
    # registered and NO summary is cached — the exact "carry-on" gap #6/#3 fix.
    effort_history.adopt_discovered(str(folder), pid,
                                    brownfield_scan.scan(str(folder)))
    return {
        "gui": gui, "eh": effort_history, "sessions": sessions,
        "ev": effort_view, "folder": folder, "pid": pid,
    }


def _planning_session(env):
    """The discovered planning session (grouped under planning/rnd-x)."""
    for s in env["sessions"].list_sessions(env["folder"], env["pid"], "planning"):
        if any("rnd-x" in (m.get("artifact_path") or "")
               for m in s.get("member_files", [])):
            return s
    raise AssertionError("expected a discovered planning session")


# ── #6 backend — _build_continue_seed synthesizes from on-disk docs ──────────

def test_continue_seed_synthesized_for_discovered_effort(env):
    gui, folder, pid = env["gui"], env["folder"], env["pid"]
    session = _planning_session(env)
    sid = session["session_id"]
    # Sanity: it really is a discovered session with no cached summary / registry.
    assert all(env["eh"].is_discovered(m) for m in session["member_files"])

    seed = gui._build_continue_seed(str(folder), pid, "plan", sid)

    # NON-empty.
    assert seed, "discovered effort must synthesize a non-empty resume seed"
    # Contains the DOC LIST (both planning docs, by their on-disk rel path).
    assert "MASTER-PLAN.md" in seed
    assert "IMPLEMENTATION-PLAN.md" in seed
    # Contains the CHOSEN SKILL (planning → Crucible).
    assert "Crucible" in seed
    # Contains the DETECTED PHASE (IMPLEMENTATION-PLAN present → Stage 2).
    assert "Phase:" in seed
    assert "implementation plan (Stage 2)" in seed


def test_continue_seed_skill_and_phase_track_the_lane(env):
    """The research discovered effort selects researchPrime + a research phase."""
    gui, folder, pid = env["gui"], env["folder"], env["pid"]
    rs = None
    for s in env["sessions"].list_sessions(folder, pid, "research"):
        if any(env["eh"].is_discovered(m) for m in s.get("member_files", [])):
            rs = s
            break
    assert rs is not None, "expected a discovered research session"
    seed = gui._build_continue_seed(str(folder), pid, "research",
                                    rs["session_id"])
    assert seed
    assert "researchPrime" in seed
    assert "research investigation" in seed
    assert "report.md" in seed


# ── #3 data — build_effort_view folds discovered efforts as grouped members ──

def test_build_effort_view_groups_discovered_not_loose(env):
    ev, folder, pid = env["ev"], env["folder"], env["pid"]
    session = _planning_session(env)
    sid = session["session_id"]

    efforts = ev.build_effort_view(str(folder), pid)
    assert efforts, "build_effort_view must surface the discovered efforts"

    # The discovered planning session is ONE first-class effort keyed by its
    # session id — NOT a loose:: singleton, and NOT one effort per file.
    by_cid = {e.get("chain_id"): e for e in efforts}
    assert sid in by_cid, "discovered planning session not folded into the view"
    eff = by_cid[sid]
    assert eff["effort_id"] == sid
    assert not eff["effort_id"].startswith("loose::")
    assert eff["current_stage"] == "plan"
    assert eff.get("discovered") is True
    # The TWO planning docs are grouped as MEMBERS of the one effort (grouped,
    # not split into two singleton efforts).
    assert len(eff["members"]) == 2
    rels = {d["rel"] for m in eff["members"] for d in m.get("docs", [])}
    assert any(r.endswith("MASTER-PLAN.md") for r in rels)
    assert any(r.endswith("IMPLEMENTATION-PLAN.md") for r in rels)
    # No effort in the whole view is a loose:: singleton.
    assert not any(str(e.get("effort_id", "")).startswith("loose::")
                   for e in efforts)
    # SAFE projection — a member NEVER leaks worktree_path / branch.
    for m in eff["members"]:
        assert "worktree_path" not in m
        assert "branch" not in m


def test_build_effort_view_idempotent_with_discovered(env):
    """Folding discovered efforts in is deterministic — build twice → equal."""
    ev, folder, pid = env["ev"], env["folder"], env["pid"]
    a = ev.build_effort_view(str(folder), pid)
    b = ev.build_effort_view(str(folder), pid)
    assert a == b
