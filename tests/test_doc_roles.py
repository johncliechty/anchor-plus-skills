"""v4 Wave 3 — per-lane document roles (``summarizer.session_doc_roles``).

Maps a session's member docs (by filename) to the lane's LOCKED role set:
  - research → exec · report · agent · provenance
  - planning → master · impl · northstar
  - build    → northstar · deliverable · execlog · plan

Each role's href uses the EXISTING routes (``/report/<pid>/<lane>/<job>`` for run
docs, ``/artifact/<pid>?path=<rel>`` for discovered/on-disk files). Roles whose
doc is ABSENT are OMITTED — never fabricated.

Temp ANCHOR_DATA_DIR; no live claude, no real data, never :8777.
"""
import importlib

import pytest


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import deliverables
    importlib.reload(deliverables)
    import handoff
    importlib.reload(handoff)
    import summarizer
    importlib.reload(summarizer)
    return rnd_registry, effort_history, sessions, deliverables, handoff, summarizer


def _project(rnd, folder, name="P"):
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder))


def _discovered(eh, folder, pid, lane, rel, title="", kind=""):
    """Write a DISCOVERED member pointer-record carrying an artifact_path."""
    jid = eh.discovered_job_id(lane, rel)
    extra = {
        "source": eh.SOURCE_DISCOVERED,
        "kind": kind,
        "title": title,
        "artifact_path": rel,
        "status": "imported",
    }
    return eh.record_effort(folder, pid, lane, jid, extra=extra)


def _session_id_for_dir(sessions_mod, eh, folder, pid, lane, parent_dir):
    for s in sessions_mod.list_sessions(folder, pid, lane):
        # discovered members under the same parent dir group into one session
        if any((m.get("artifact_path") or "").replace("\\", "/").startswith(
                parent_dir + "/") for m in s["member_files"]):
            return s["session_id"]
    return None


# ── planning lane: master / impl / northstar ─────────────────────────────────

def test_planning_roles_resolve_master_impl_northstar(mods, tmp_path):
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    d = "planning/rnd-x"
    _discovered(eh, folder, pid, "planning", f"{d}/MASTER-PLAN.md", "Master Plan")
    _discovered(eh, folder, pid, "planning", f"{d}/IMPLEMENTATION-PLAN.md", "Impl")
    _discovered(eh, folder, pid, "planning", f"{d}/North-Star.md", "North Star")

    sid = _session_id_for_dir(sess, eh, folder, pid, "planning", d)
    assert sid is not None
    roles = summ.session_doc_roles(pid, "planning", sid, folder_path=folder)

    assert set(roles) == {"master", "impl", "northstar"}
    # Paths are URL-quoted (safe='') exactly like the existing _member_links.
    assert roles["master"]["href"] == (
        f"/artifact/{pid}?path=planning%2Frnd-x%2FMASTER-PLAN.md")
    assert roles["impl"]["href"].endswith("IMPLEMENTATION-PLAN.md")
    assert roles["northstar"]["href"].endswith("North-Star.md")
    # every href is an existing route
    for r in roles.values():
        assert r["href"].startswith(("/artifact/", "/report/"))


def test_planning_absent_roles_omitted(mods, tmp_path):
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    d = "planning/rnd-y"
    # Only a MASTER-PLAN present — impl + northstar must be OMITTED, not faked.
    _discovered(eh, folder, pid, "planning", f"{d}/MASTER-PLAN.md", "Master")
    sid = _session_id_for_dir(sess, eh, folder, pid, "planning", d)
    roles = summ.session_doc_roles(pid, "planning", sid, folder_path=folder)
    assert set(roles) == {"master"}
    assert "impl" not in roles
    assert "northstar" not in roles


# ── research lane: exec / report / agent / provenance ────────────────────────

def test_research_roles_resolve_all(mods, tmp_path):
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    d = "research/topic-a"
    _discovered(eh, folder, pid, "research", f"{d}/executive-summary.md", "Exec")
    _discovered(eh, folder, pid, "research", f"{d}/report.pdf", "Report")
    _discovered(eh, folder, pid, "research", f"{d}/agent.json", "Agent")
    _discovered(eh, folder, pid, "research", f"{d}/refs.bib", "Refs")
    _discovered(eh, folder, pid, "research", f"{d}/run.log", "Log")

    sid = _session_id_for_dir(sess, eh, folder, pid, "research", d)
    roles = summ.session_doc_roles(pid, "research", sid, folder_path=folder)
    assert "exec" in roles and roles["exec"]["href"].endswith(
        "executive-summary.md")
    assert "report" in roles and roles["report"]["href"].endswith("report.pdf")
    assert "agent" in roles and roles["agent"]["href"].endswith("agent.json")
    assert "provenance" in roles  # refs.bib or run.log


def test_research_run_session_report_uses_report_route(mods, tmp_path):
    """A RUN research session (no per-file artifact_path) maps the report role to
    the ``/report/<pid>/<lane>/<job_id>`` route."""
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    # A run effort: has a job_id, no artifact_path → groups as one run session.
    eh.record_effort(folder, pid, "research", "runjob1", skill="researchPrime")
    runs = [s for s in sess.list_sessions(folder, pid, "research")
            if s["provenance"] == sess.PROV_RUN]
    assert runs, "expected a run-provenance research session"
    sid = runs[0]["session_id"]
    roles = summ.session_doc_roles(pid, "research", sid, folder_path=folder)
    assert "report" in roles
    assert roles["report"]["href"] == f"/report/{pid}/research/runjob1"


# ── build lane: northstar / execlog / deliverable / plan ─────────────────────

def test_build_roles_resolve_northstar_execlog_deliverable_plan(mods, tmp_path):
    rnd, eh, sess, deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]

    # A pinned deliverable (artifact_path) → the build "deliverable" role.
    (folder / "anchor_gui.py").write_text("print('hi')\n", encoding="utf-8")
    deliv.pin_deliverable(folder, pid, "anchor_gui.py", name="Anchor GUI")

    # A planning session with a MASTER-PLAN → the build "plan" role (handoff).
    pd = "planning/rnd-z"
    _discovered(eh, folder, pid, "planning", f"{pd}/MASTER-PLAN.md", "Master")
    _discovered(eh, folder, pid, "planning", f"{pd}/IMPLEMENTATION-PLAN.md", "I")

    # The build session's own members: North-Star + EXECUTION-LOG.
    bd = "build/wave-run"
    _discovered(eh, folder, pid, "build", f"{bd}/North-Star.md", "NS")
    _discovered(eh, folder, pid, "build", f"{bd}/EXECUTION-LOG.md", "Log")

    sid = _session_id_for_dir(sess, eh, folder, pid, "build", bd)
    assert sid is not None
    roles = summ.session_doc_roles(pid, "build", sid, folder_path=folder)

    assert "northstar" in roles and roles["northstar"]["href"].endswith(
        "North-Star.md")
    assert "execlog" in roles and roles["execlog"]["href"].endswith(
        "EXECUTION-LOG.md")
    assert "deliverable" in roles
    assert roles["deliverable"]["href"] == f"/artifact/{pid}?path=anchor_gui.py"
    assert "plan" in roles
    assert roles["plan"]["href"].endswith("MASTER-PLAN.md")


def test_build_omits_deliverable_and_plan_when_absent(mods, tmp_path):
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    bd = "build/lonely"
    _discovered(eh, folder, pid, "build", f"{bd}/North-Star.md", "NS")
    sid = _session_id_for_dir(sess, eh, folder, pid, "build", bd)
    roles = summ.session_doc_roles(pid, "build", sid, folder_path=folder)
    assert set(roles) == {"northstar"}
    assert "deliverable" not in roles
    assert "plan" not in roles
    assert "execlog" not in roles


# ── resolution / safety ──────────────────────────────────────────────────────

def test_unknown_session_returns_empty(mods, tmp_path):
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    assert summ.session_doc_roles(pid, "planning", "no::such", folder_path=folder) == {}


def test_folder_path_resolved_from_registry(mods, tmp_path):
    rnd, eh, sess, _deliv, _ho, summ = mods
    folder = tmp_path / "proj"
    proj = _project(rnd, folder)
    pid = proj["id"]
    d = "planning/auto"
    _discovered(eh, folder, pid, "planning", f"{d}/MASTER-PLAN.md", "M")
    sid = _session_id_for_dir(sess, eh, folder, pid, "planning", d)
    # Omit folder_path → resolved from the live registry by pid.
    roles = summ.session_doc_roles(pid, "planning", sid)
    assert "master" in roles
