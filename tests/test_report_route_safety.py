"""Wave 7 hardening (MINOR-3) — report route path-segment sanitation.

The ``/report/<pid>/<lane>/<job_id>`` route builds a filesystem path from
``lane`` / ``job_id``. Those segments must be rejected when they contain a path
separator or ``..`` BEFORE they reach the filesystem, consistent with the
hardened vendored-KaTeX static route. No network, no subprocess.
"""
import importlib

import pytest


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import report_viewer
    importlib.reload(report_viewer)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


def test_unsafe_path_seg_rejects_traversal_and_separators(gui):
    bad = ["..", "../etc", "a/b", "a\\b", "..\\x", "foo/..", "a/../b"]
    for seg in bad:
        assert gui._unsafe_path_seg(seg) is True, f"should reject {seg!r}"


def test_unsafe_path_seg_accepts_valid_ids(gui):
    good = ["abc123", "c1", "job-2026-06-08", "research", "fake-session-0001",
            None]
    for seg in good:
        assert gui._unsafe_path_seg(seg) is False, f"should accept {seg!r}"


def test_traversal_job_id_would_escape_efforts_dir(gui, tmp_path):
    """Demonstrates the hazard the guard prevents: a ``..`` job_id escapes the
    lane's efforts dir, while a valid id stays contained. The route's
    ``_unsafe_path_seg`` check is what stops the escaping value from being used.
    """
    import effort_history as eh

    folder = tmp_path / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    pid = "pid1"
    ed = eh.efforts_dir(folder, pid, "research").resolve()

    # A valid id stays inside the efforts dir.
    safe_target = (ed / "c1").resolve()
    assert str(safe_target).startswith(str(ed))

    # A traversal id WOULD escape — which is exactly why the route rejects it.
    escape_target = (ed / ".." / ".." / "secret").resolve()
    assert not str(escape_target).startswith(str(ed))
    # And the guard flags that id.
    assert gui_is_unsafe("../../secret")


def gui_is_unsafe(seg):
    import anchor_gui
    return anchor_gui._unsafe_path_seg(seg)
