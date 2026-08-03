"""Wave 2: write-locks serialize concurrent mutations (no lost update) and the
bind-retry loop recovers from a transient bind failure.

The race test seeds a tmp ANCHOR_DATA_DIR, points the GUI module's data
constants at it, then fires many threads that each mark a distinct task done.
Under a correct write-lock every update survives (the classic lost-update bug
is read-modify-write where one thread overwrites another's change).
"""
import importlib
import threading

import paths


def _load_gui_with_data_dir(monkeypatch, tmp_path):
    """Reload anchor_gui so its module-level path constants resolve under
    tmp_path. Returns the (re)loaded module."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    return gui


def test_concurrent_mark_done_no_lost_update(monkeypatch, tmp_path):
    gui = _load_gui_with_data_dir(monkeypatch, tmp_path)
    paths.ensure_data_dirs()

    n = 40
    lines = ["# Dashboard", ""]
    for i in range(n):
        lines.append(f"- [ ] task-{i:03d} — Priority: 2 — [academic]")
    gui.DASHBOARD_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    barrier = threading.Barrier(n)
    errors = []

    def worker(i):
        try:
            barrier.wait()  # maximize contention
            gui.mark_done(f"task-{i:03d}")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    final = gui.DASHBOARD_MD.read_text(encoding="utf-8")
    done = final.count("[x]")
    # Every single update must have survived — this is the lost-update assertion.
    assert done == n, f"expected {n} completed, got {done}"
    assert "[ ]" not in final


def test_lock_serializes_critical_section():
    """Direct proof the shared lock serializes a read-modify-write counter."""
    paths_mod = importlib.reload(paths)
    lock = paths_mod.WRITE_LOCK
    state = {"v": 0}

    def bump():
        for _ in range(1000):
            with lock:
                cur = state["v"]
                cur += 1
                state["v"] = cur

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["v"] == 8 * 1000


def test_bind_with_retry_recovers_after_one_failure():
    """A bind that fails once then succeeds is recovered by bind_with_retry."""
    paths_mod = importlib.reload(paths)
    calls = {"n": 0}

    def make():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("address not available yet (slow Tailscale)")
        return "SERVER"

    result = paths_mod.bind_with_retry(make, attempts=5, delay=0.01)
    assert result == "SERVER"
    assert calls["n"] == 2


def test_bind_with_retry_raises_after_exhausting_attempts():
    paths_mod = importlib.reload(paths)

    def always_fail():
        raise OSError("nope")

    try:
        paths_mod.bind_with_retry(always_fail, attempts=3, delay=0.005)
    except OSError as e:
        assert "nope" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected OSError after exhausting attempts")
