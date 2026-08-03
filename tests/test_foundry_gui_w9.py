"""foundry-v2 Wave 9 — Foundry GUI read surface (stateless client).

Proves the Wave-9 done-when:
  (a) EVERY rendered value resolves to a REAL engine-written artifact —
      each view row carries a ``trace`` naming the artifact file it was
      read from (the autoload registry, map.json v2 + lockfile, job_runner
      records/logs, the Wave-2 journal skeletons) and the value re-derives
      from that artifact;
  (b) INTEGRATION: the monitor view reads job_runner STATE (not a mirror) —
      a real server-owned job is launched through job_runner, the view
      reflects its live record, and a direct engine-side record mutation is
      visible on the very next view call with no sync/refresh step (a
      GUI-side copy would keep answering stale);
  (c) the ANTI-THEATER check is clean on the shipped module and FAILS
      loudly when a parallel run/progress store (or a GUI-side write path,
      or a runtime module-level mirror/cache) is introduced;
  plus: the ``/foundry`` page renders from these views and is launched from
  an Anchor dashboard button (route + button wired in ``anchor_gui.py``).

Hermetic like tests/test_foundry_ops_w7.py: temp ANCHOR_DATA_DIR + temp
skills root + temp map/lock/registry artifacts; the launched job is a tiny
``sys.executable -c`` print (deterministic local code — NEVER real claude /
real node / the real Skill Foundry / the worktree map / :8777). Stdlib only.
"""
import json
import sys
from pathlib import Path

import pytest

import foundry_autoload as fa
import foundry_gui as fgui
import foundry_journal as fj
import foundry_map as fm

_ROOT = Path(__file__).resolve().parents[1]


# ── Fixture: a hermetic engine-artifact rig ──────────────────────────────────

@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Temp data dir + skills root (one runnable, one bare skill) + map v2 +
    lockfile + autoload registry + one seam-written journal entry — every
    artifact the read surface projects, all engine-written shapes."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    (skills_root / "gandalf").mkdir()          # bare: no manifest
    demo = skills_root / "runner-demo"
    demo.mkdir()
    (demo / "SKILL.md").write_text("# Runner Demo protocol\n",
                                   encoding="utf-8")
    manifest = {
        "skill": "runner-demo",
        "skill_dir": str(demo),
        "op_kind": "run",
        "host_cmd": [sys.executable, "{skill_dir}/host.py"],
        "output_contract": {"format": "json"},
        "panel": {"title": "Runner Demo"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": [],
        "activation": {"trigger": "first_run"},
    }
    (demo / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                        encoding="utf-8")
    doc = {
        "schema": fm.MAP_SCHEMA_ID,
        "map_version": fm.MAP_VERSION,
        "skills": [
            {"ref": "skill:gandalf", "name": "gandalf",
             "source": (skills_root / "gandalf").as_posix(),
             "status": "5 - Production/Stable", "tier": "standard",
             "version": "1.2.0", "edges": []},
            {"ref": "skill:runner-demo", "name": "runner-demo",
             "source": demo.as_posix(),
             "status": "4 - Beta", "tier": "standard",
             "version": "0.2.0",
             "edges": [{"type": "compose", "to": "skill:gandalf",
                        "range": "^1.0.0"}]},
        ],
    }
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock_path = tmp_path / "map.lock.json"
    fm.write_lockfile(doc, path=lock_path)
    autoload_home = tmp_path / "autoload"
    autoload_home.mkdir()
    # The ENGINE writes the registry (the Wave-8 op body) — never this test.
    res = fa.sync_registrations(doc, home=autoload_home, root=tmp_path)
    assert res["ok"] is True
    # The ENGINE writes the journal entry (the Wave-2 seam) — never this test.
    written = fj.journal_run_writeback(
        demo, run_id="w9-run-1", operation_kind="run",
        provenance="host-enforced:anchor.skill_runner:runner-demo",
        model_cost=None, inputs={"payload": {"ping": "pong"}},
        outputs={"output": {"verdict": "ok-w9"}},
        verdict="ok-w9",
        timing={"started_ts": 1.0, "finished_ts": 2.0, "duration_s": 1.0},
        outcome="done", linkage={"run_id": "w9-run-1"})
    assert written is not None
    return {"tmp": tmp_path, "data": data_dir, "skills_root": skills_root,
            "demo": demo, "map": map_path, "lock": lock_path,
            "seed_doc": doc, "autoload": autoload_home}


def _collect_traces(obj, acc):
    """Walk a view projection collecting every trace stamp on it."""
    if isinstance(obj, dict):
        if "artifact" in obj and "via" in obj:
            acc.append(obj)
        else:
            for v in obj.values():
                _collect_traces(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_traces(v, acc)


def _launch_print_job(tmp_path, lane, text):
    import job_runner as jr
    rec = jr.launch(lane, cwd=str(tmp_path),
                    command=[sys.executable, "-c", "print(%r)" % text])
    final = jr.wait(rec["job_id"], timeout=60.0)
    assert final and final["status"] == jr.STATUS_DONE
    return rec["job_id"]


# ── library: rows trace to the engine-written registry ───────────────────────

def test_library_view_traces_to_the_registry_artifact(rig):
    lib = fgui.library_view(home=rig["autoload"])
    assert lib["ok"] is True and lib["registered"] is True
    by = {r["name"]: r for r in lib["skills"]}
    assert set(by) == {"gandalf", "runner-demo"}
    assert by["runner-demo"]["runnable"] is True
    assert by["runner-demo"]["panel_title"] == "Runner Demo"
    assert by["runner-demo"]["version"] == "0.2.0"
    assert by["gandalf"]["runnable"] is False
    assert by["gandalf"]["reason"] == "manifest-missing"
    # Every row traces to the REAL registry artifact the engine wrote, and
    # the displayed values re-derive from that artifact.
    reg = fa.registry_path(rig["autoload"])
    reg_text = reg.read_text(encoding="utf-8")
    for r in lib["skills"]:
        assert r["trace"]["artifact"] == reg.as_posix()
        assert r["trace"]["exists"] is True
        assert r["name"] in reg_text and str(r["version"]) in reg_text

    # Honest before any registration — and READ-ONLY: peeking at a never-
    # synced home neither fabricates rows nor creates the home on disk.
    fresh = rig["tmp"] / "never-synced"
    empty = fgui.library_view(home=fresh)
    assert empty["ok"] is True and empty["registered"] is False
    assert empty["skills"] == []
    assert not fresh.exists()


# ── knowledge graph: typed edges + verified pins, honest on a bad map ────────

def test_graph_view_projects_typed_graph_with_verified_pins(rig):
    g = fgui.graph_view(map_path=rig["map"], lock_path=rig["lock"])
    assert g["ok"] is True
    assert [n["ref"] for n in g["nodes"]] == ["skill:gandalf",
                                              "skill:runner-demo"]
    map_posix = Path(rig["map"]).as_posix()
    for n in g["nodes"]:
        assert n["trace"]["artifact"] == map_posix
        assert n["trace"]["exists"] is True
    # The one typed edge, pinned from the VERIFIED lockfile.
    assert len(g["edges"]) == 1
    e = g["edges"][0]
    assert (e["from"], e["type"], e["to"]) == (
        "skill:runner-demo", "compose", "skill:gandalf")
    assert e["range"] == "^1.0.0"
    assert e["pinned"] == "1.2.0"
    assert g["lock"]["ok"] is True
    assert g["lock"]["pins"] == {"skill:gandalf": "1.2.0",
                                 "skill:runner-demo": "0.2.0"}
    # Node values re-derive from the map artifact itself.
    doc = json.loads(Path(g["trace"]["artifact"]).read_text(encoding="utf-8"))
    assert {s["ref"]: s["version"] for s in doc["skills"]} == \
        {n["ref"]: n["version"] for n in g["nodes"]}


def test_graph_view_is_honest_on_invalid_map_and_lock_drift(rig):
    # An UNTYPED edge → the graph REFUSES (no fabricated nodes/edges).
    bad = json.loads(rig["map"].read_text(encoding="utf-8"))
    bad["skills"][1]["edges"] = [{"to": "skill:gandalf", "range": "*"}]
    bad_path = rig["tmp"] / "bad-map.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    gv = fgui.graph_view(map_path=bad_path, lock_path=rig["lock"])
    assert gv["ok"] is False
    assert gv["reason"].startswith("map-invalid:")
    assert gv["nodes"] == [] and gv["edges"] == []

    # A drifted (stale) lock → the graph stands, the lock reports drift BY
    # NAME, and no pin is fabricated onto any edge.
    moved = json.loads(rig["map"].read_text(encoding="utf-8"))
    moved["skills"][0]["version"] = "1.3.0"
    moved["skills"][1]["edges"][0]["range"] = "^1.3.0"
    moved_path = rig["tmp"] / "moved-map.json"
    moved_path.write_text(json.dumps(moved), encoding="utf-8")
    gd = fgui.graph_view(map_path=moved_path, lock_path=rig["lock"])
    assert gd["ok"] is True
    assert gd["lock"]["ok"] is False
    assert gd["lock"]["problems"]
    assert gd["lock"]["pins"] == {}
    assert all(e["pinned"] is None for e in gd["edges"])

    # An unreadable map is honest too.
    gone = fgui.graph_view(map_path=rig["tmp"] / "no-such-map.json",
                           lock_path=rig["lock"])
    assert gone["ok"] is False and gone["reason"].startswith("map-unreadable:")


# ── changes: the seam-written journal skeletons, traced per entry ────────────

def test_changes_view_reads_the_seam_written_journal(rig):
    ch = fgui.changes_view(rig["demo"])
    assert ch["ok"] is True and ch["count"] == 1
    e = ch["entries"][0]
    assert e["id"] == "w9-run-1"
    assert e["operation_kind"] == "run"
    assert e["outcome"] == "done"
    assert e["verdict"] == "ok-w9"
    p = Path(e["trace"]["artifact"])
    assert p.is_file() and p.suffix == ".md"
    text = p.read_text(encoding="utf-8")
    assert "ok-w9" in text and "host-enforced:" in text
    # A skill with no journal yet is an honest empty list, never fabricated.
    bare = fgui.changes_view(rig["skills_root"] / "gandalf")
    assert bare["ok"] is True and bare["entries"] == [] and bare["count"] == 0


# ── (b) INTEGRATION: the monitor view reads job_runner state, not a mirror ───

def test_monitor_view_reads_job_runner_state_not_a_mirror(rig):
    import job_runner as jr
    job_id = _launch_print_job(rig["tmp"], "foundry-gui-w9",
                               "gui-w9-output-line")

    mv = fgui.monitor_view(job_id)
    assert mv["ok"] is True
    assert mv["lane"] == "foundry-gui-w9"
    assert mv["status"] == jr.STATUS_DONE
    assert any("gui-w9-output-line" in ln for ln in mv["lines"])

    # The displayed values resolve to the REAL engine artifacts: the durable
    # job record and the durable log job_runner itself wrote.
    rec_path = Path(mv["trace"]["artifact"])
    assert rec_path.is_file()
    on_disk = json.loads(rec_path.read_text(encoding="utf-8"))
    assert on_disk["job_id"] == job_id
    assert on_disk["status"] == mv["status"]
    assert on_disk["lane"] == mv["lane"]
    log_path = Path(mv["log_trace"]["artifact"])
    assert log_path.is_file()
    assert "gui-w9-output-line" in log_path.read_text(encoding="utf-8")

    # NOT A MIRROR: mutate the engine's record directly — the very next view
    # call reflects it with NO sync/refresh/invalidate step in between. A
    # GUI-side copy (a parallel store) would keep answering the stale status.
    jr._update_record(job_id, status=jr.STATUS_INTERRUPTED)
    assert fgui.monitor_view(job_id)["status"] == jr.STATUS_INTERRUPTED
    jr._update_record(job_id, status=jr.STATUS_DONE)
    assert fgui.monitor_view(job_id)["status"] == jr.STATUS_DONE

    # runs_view is the same live read (lane-filtered), no copy either.
    rv = fgui.runs_view(lane="foundry-gui-w9")
    assert [r["job_id"] for r in rv["runs"]] == [job_id]
    assert rv["runs"][0]["status"] == jr.STATUS_DONE
    # SAFE projection: no crypt token / pid / relaunch spec leaks to the GUI.
    for key in ("crypt_token", "pid", "relaunch_spec"):
        assert key not in rv["runs"][0]
        assert key not in mv

    # An unknown job is honest, never fabricated.
    missing = fgui.monitor_view("no-such-job")
    assert missing["ok"] is False
    assert missing["reason"].startswith("unknown-job:")


# ── (a) every rendered value resolves to a real engine artifact ──────────────

def test_every_rendered_value_traces_to_a_real_engine_artifact(rig):
    job_id = _launch_print_job(rig["tmp"], "foundry-gui-w9", "trace-line")
    views = [
        fgui.library_view(home=rig["autoload"]),
        fgui.graph_view(map_path=rig["map"], lock_path=rig["lock"]),
        fgui.changes_view(rig["demo"]),
        fgui.runs_view(lane="foundry-gui-w9"),
        fgui.monitor_view(job_id),
    ]
    traces = []
    for view in views:
        _collect_traces(view, traces)
    assert len(traces) >= 5  # every view is trace-stamped, not bare
    for t in traces:
        assert t["exists"] is True, t
        assert Path(t["artifact"]).exists(), t
        assert t["via"], t  # names the engine accessor it was read through


# ── (c) the anti-theater check — fails when a parallel store appears ─────────

def test_anti_theater_check_clean_then_fails_on_parallel_store(monkeypatch):
    src = Path(fgui.__file__).read_text(encoding="utf-8")
    # The shipped GUI data layer is clean: stateless, no mutation path.
    assert fgui.anti_theater_check() == []

    # A parallel run/progress store introduced at module level → FAIL.
    doctored_store = src + "\n_RUN_PROGRESS = {}\n"
    probs = fgui.anti_theater_check(source_text=doctored_store)
    assert any(p.startswith("parallel-store:") for p in probs)

    # A GUI-side write path introduced → FAIL. (The forbidden call is
    # assembled at runtime so this test file never carries it verbatim.)
    doctored_write = (src + "\ndef _persist(x):\n"
                      + "    Path('mirror.json').write_" + "text(x)\n")
    probs = fgui.anti_theater_check(source_text=doctored_write)
    assert any(p.startswith("gui-mutation-path:") for p in probs)

    # A runtime module-level mirror/cache (however it got there) → FAIL.
    monkeypatch.setattr(fgui, "_MIRROR_CACHE", {}, raising=False)
    probs = fgui.anti_theater_check()
    assert any(p.startswith("module-state:_MIRROR_CACHE") for p in probs)


# ── the page + the Anchor button (launched from Anchor) ──────────────────────

def test_foundry_page_renders_from_views_and_anchor_button_is_wired(rig):
    page = fgui.render_foundry_page(home=rig["autoload"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    assert "Skill Foundry" in page
    assert "runner-demo" in page and "gandalf" in page
    assert "compose" in page                       # the typed edge renders
    assert "ok-w9" in page                         # the journaled change
    assert "data-anti-theater='stateless'" in page
    # The provenance is ON the page: the registry artifact is named.
    assert fa.registry_path(rig["autoload"]).as_posix() in page

    # The monitor drill-in renders the live job_runner read.
    job_id = _launch_print_job(rig["tmp"], "foundry-gui-w9", "page-line")
    mon_page = fgui.render_foundry_page(home=rig["autoload"],
                                        map_path=rig["map"],
                                        lock_path=rig["lock"],
                                        lane="foundry-gui-w9", job_id=job_id)
    assert job_id in mon_page and "page-line" in mon_page

    # Launched from an Anchor button: anchor_gui imports the stateless
    # client, serves GET /foundry through it, and the dashboard carries the
    # launch button — the GUI has no other data path.
    src = (_ROOT / "anchor_gui.py").read_text(encoding="utf-8",
                                              errors="replace")
    assert "import foundry_gui as _fgui" in src
    assert '_path_only == "/foundry"' in src
    assert "_fgui.render_foundry_page(" in src
    assert "window.open('/foundry','_blank')" in src
