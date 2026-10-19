"""Wave 5 — Anchor.md marker writer (structure-only, no-churn, lock-safe).

Proves IMPLEMENTATION-PLAN.md "## Wave 5":
  - commit-safety: Anchor.md is STRUCTURE ONLY — counts / relative paths /
    titles — and NEVER leaks file contents or secrets.
  - no-churn: opening an unchanged folder twice does NOT rewrite Anchor.md.
  - concurrency (house style of test_threading_locks.py): N threads writing the
    marker for one folder concurrently yield exactly one consistent file.
  - sectioned for N-projects-per-folder.
  - machine sidecar .anchor/projects/<id>/discovery.json holds the ScanResult.
"""
import importlib
import json
import threading
from pathlib import Path

import pytest

import brownfield_scan as bscan


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import anchor_marker
    importlib.reload(anchor_marker)
    return anchor_marker, rnd_registry, effort_history


# Built at runtime so this SHIPPED test file (manifest tests/test_*.py) carries
# no contiguous secret-shaped literal and stays distro-scan-clean.
PLANTED = "hunter2-" + "TOPSECRET-" + "PASS" + "WORD-VALUE"


def _seed(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "foreman-checkpoint.json").write_text(
        '{"api_key": "%s"}' % PLANTED, encoding="utf-8")
    p = folder / "planning"
    p.mkdir()
    (p / "MASTER-PLAN.md").write_text(
        "# Master Plan\n\nThis body contains a %s embedded.\n" % PLANTED,
        encoding="utf-8")
    return folder


def test_anchor_md_is_structure_only_no_secret_leak(mods, tmp_path):
    marker, rnd, eh = mods
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("BrownProj", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    res = marker.write_anchor_md(folder)
    assert res["written"] is True
    md = (folder / "Anchor.md").read_text(encoding="utf-8")

    # Structure present: project name, relative paths, counts.
    assert "BrownProj" in md
    assert "planning/MASTER-PLAN.md" in md
    assert "foreman-checkpoint.json" in md
    assert "imported" in md
    # The TITLE (a markdown heading) is allowed (it is structure, from the scanner).
    assert "Master Plan" in md
    # NO file content / secret leaks into Anchor.md.
    assert PLANTED not in md
    assert "api_key" not in md
    assert "embedded" not in md  # body prose never copied


def test_no_churn_second_open_does_not_rewrite(mods, tmp_path):
    marker, rnd, eh = mods
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("BrownProj", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    r1 = marker.write_anchor_md(folder)
    assert r1["written"] is True
    mtime1 = (folder / "Anchor.md").stat().st_mtime_ns
    body1 = (folder / "Anchor.md").read_text(encoding="utf-8")

    # Second write with no structural change → not rewritten.
    r2 = marker.write_anchor_md(folder)
    assert r2["written"] is False
    assert r2["reason"] == "unchanged"
    mtime2 = (folder / "Anchor.md").stat().st_mtime_ns
    assert mtime1 == mtime2
    assert (folder / "Anchor.md").read_text(encoding="utf-8") == body1


def test_structural_change_triggers_rewrite(mods, tmp_path):
    marker, rnd, eh = mods
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("BrownProj", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    marker.write_anchor_md(folder)

    # Add a new artifact -> structure changed -> rewrite.
    (folder / "planning" / "IMPLEMENTATION-PLAN.md").write_text(
        "# Impl\n", encoding="utf-8")
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    r = marker.write_anchor_md(folder)
    assert r["written"] is True
    md = (folder / "Anchor.md").read_text(encoding="utf-8")
    assert "planning/IMPLEMENTATION-PLAN.md" in md


def test_sidecar_written(mods, tmp_path):
    marker, rnd, eh = mods
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("BrownProj", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    marker.write_anchor_md(folder)
    sc = marker.sidecar_path(folder, pid)
    assert sc.exists()
    data = json.loads(sc.read_text(encoding="utf-8"))
    assert "by_lane" in data and "counts" in data
    assert data["counts"]["planning"] >= 1


def test_sectioned_for_multiple_projects(mods, tmp_path):
    marker, rnd, eh = mods
    folder = _seed(tmp_path / "proj")
    a = rnd.add_project("Alpha", str(folder))
    b = rnd.add_project("Beta", str(folder))
    eh.adopt_discovered(folder, a["id"], bscan.scan(str(folder)))
    eh.adopt_discovered(folder, b["id"], bscan.scan(str(folder)))
    marker.write_anchor_md(folder)
    md = (folder / "Anchor.md").read_text(encoding="utf-8")
    assert "## Alpha" in md
    assert "## Beta" in md


def test_concurrent_writes_yield_one_consistent_file(mods, tmp_path):
    marker, rnd, eh = mods
    folder = _seed(tmp_path / "proj")
    proj = rnd.add_project("BrownProj", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    n = 24
    barrier = threading.Barrier(n)
    errors = []

    def worker():
        try:
            barrier.wait()
            marker.write_anchor_md(folder)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    md = (folder / "Anchor.md").read_text(encoding="utf-8")
    # Exactly one well-formed document (single H1, no interleaving corruption).
    assert md.count("# Anchor.md") == 1
    assert "BrownProj" in md
    assert PLANTED not in md


def test_missing_folder_is_noop(mods, tmp_path):
    marker, rnd, eh = mods
    res = marker.write_anchor_md(str(tmp_path / "does-not-exist"))
    assert res["written"] is False
    assert res["reason"] == "folder-missing"
