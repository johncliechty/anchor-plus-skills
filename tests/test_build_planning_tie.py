"""Build→Planning tie + EXECUTION-LOG→build classification (the "show every build
session in the Build lane, tied to its plan" change).

Proves, end-to-end and hermetically (temp ANCHOR_DATA_DIR, never :8777 / real data):

1. CLASSIFY — a Foreman EXECUTION-LOG.md that lives under ``planning/<ver>/`` is
   adopted into the BUILD lane (not planning), so the build session appears in the
   Build column even though the build ran outside Anchor.
2. ID — a discovered BUILD session's id is LANE-QUALIFIED (``build::…``) so it never
   collides with the planning session that shares its source directory.
3. TIE — _gather_project_sessions attaches ``linked_planning`` (the planning
   session's real id + version label) to a build session sharing a planning
   session's source dir; NO match → NO tie (honest, nothing fabricated).
4. RENDER — the build tile carries the clickable ``.tiechip`` + the
   ``data-linked-planning`` attribute resolving to the planning session id.
"""
import importlib
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "brownfield_scan", "job_runner", "rnd_registry",
                "lanes", "effort_history", "sessions", "summarizer",
                "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


def _plant_version(root, ver):
    """Plant a full trio doc set under ``planning/<ver>/`` (plan docs + the
    Foreman EXECUTION-LOG, exactly as the real repo lays the rnd-vN folders)."""
    d = root / "planning" / ver
    d.mkdir(parents=True, exist_ok=True)
    (d / "MASTER-PLAN.md").write_text(f"# {ver} Master Plan\n", encoding="utf-8")
    (d / "IMPLEMENTATION-PLAN.md").write_text(f"# {ver} Impl\n", encoding="utf-8")
    (d / "EXECUTION-LOG.md").write_text(f"# {ver} Build log\n", encoding="utf-8")


def _scan_adopt(folder, pid):
    import brownfield_scan as bscan
    import effort_history as eh
    eh.adopt_discovered(str(folder), pid, bscan.scan(str(folder)))


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        self.els.append((tag, dict(attrs)))


def _parse(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    c = _Collector()
    c.feed(b)
    return c.els


# ── 1 + 2: classification → build lane, lane-qualified id ───────────────────

def test_execution_log_lands_in_build_with_qualified_id(gui_env, tmp_path):
    import sessions as sx
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    _plant_version(folder, "rnd-v4")
    _scan_adopt(folder, pid)

    build = sx.list_sessions(str(folder), pid, "build")
    plan = sx.list_sessions(str(folder), pid, "planning")

    # The EXECUTION-LOG is a BUILD session member (not planning).
    build_members = [m["artifact_path"] for s in build for m in s["member_files"]]
    assert "planning/rnd-v4/EXECUTION-LOG.md" in build_members
    plan_members = [m["artifact_path"] for s in plan for m in s["member_files"]]
    assert "planning/rnd-v4/EXECUTION-LOG.md" not in plan_members
    # Plan docs stayed in planning.
    assert "planning/rnd-v4/MASTER-PLAN.md" in plan_members

    # The build session id is LANE-QUALIFIED so it can't collide with the planning
    # session for the same source directory.
    bsid = build[0]["session_id"]
    psid = plan[0]["session_id"]
    assert bsid.startswith("build::")
    assert bsid != psid


# ── 3: the tie is computed (and is honest when there's no match) ────────────

def test_gather_sessions_attaches_linked_planning(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    _plant_version(folder, "rnd-v4")
    _scan_adopt(folder, pid)

    out = gui._gather_project_sessions(str(folder), pid)
    build_sv = out["build"][0]
    plan_sv = out["plan"][0]   # planning column's trio-lane key is "plan"
    tie = build_sv.get("linked_planning")
    assert tie is not None
    assert tie["session_id"] == plan_sv["session_id"]
    assert tie["label"] == "rnd-v4"


def test_no_tie_when_build_has_no_matching_planning(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    # A build log in a directory with NO planning docs → no clear match.
    d = folder / "build" / "loose-run"
    d.mkdir(parents=True, exist_ok=True)
    (d / "EXECUTION-LOG.md").write_text("# orphan build\n", encoding="utf-8")
    _scan_adopt(folder, pid)

    out = gui._gather_project_sessions(str(folder), pid)
    assert out["build"], "the orphan build session should still appear"
    for sv in out["build"]:
        assert sv.get("linked_planning") in (None, {}), \
            "no planning in that dir → no fabricated tie"


# ── 4: the rendered build tile carries the chip + the link target ───────────

def test_build_tile_renders_tie_chip(gui_env, tmp_path):
    gui = gui_env
    folder = tmp_path / "Proj"
    pid = _mkproject(folder, "Proj")["id"]
    _plant_version(folder, "rnd-v4")
    _scan_adopt(folder, pid)

    # The matched planning session id (the chip's link target).
    import sessions as sx
    psid = sx.list_sessions(str(folder), pid, "planning")[0]["session_id"]

    els = _parse(gui.render_project_window_html(pid))
    # A build tile carrying the tie data + a .tiechip child somewhere in the body.
    tied = [d for tag, d in els
            if "tile" in (d.get("class") or "").split()
            and d.get("data-linked-planning") == psid]
    assert tied, "expected a build tile with data-linked-planning == planning sid"
    chips = [d for tag, d in els if "tiechip" in (d.get("class") or "").split()]
    assert chips, "expected a rendered .tiechip on the board"
