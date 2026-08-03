"""Guard: the canonical warm-restart wrapper wires the pre-restart drain in.

rearch W3 built ``tools/pre_restart_drain.py`` (park live sessions warm: persist
docs + cache summaries to disk) but left it UNWIRED - its docstring said "wired
into the deploy script by W17". Phase-2 durable saving finally wires it via
``restart_anchor.ps1`` (the canonical warm restart). This test locks that
wiring and, critically, the ORDERING: the drain must run WHILE THE SERVICE IS
STILL UP (before the nssm stop), or it snapshots nothing and the restart is cold.

Stdlib only; no service, no PTY, no model - a pure static-content invariant.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "restart_anchor.ps1"


def test_restart_wrapper_exists():
    assert SCRIPT.is_file(), "restart_anchor.ps1 (the canonical warm restart) must exist"


def test_wrapper_invokes_the_drain():
    text = SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "pre_restart_drain.py" in text, \
        "the warm restart must invoke tools/pre_restart_drain.py"


def test_drain_runs_before_the_stop():
    """The drain must precede the nssm stop - otherwise the PTYs are already
    dead and there is nothing to park warm."""
    text = SCRIPT.read_text(encoding="utf-8", errors="replace")
    drain_at = text.find("pre_restart_drain.py")
    stop_at = text.lower().find("stop anchor")
    assert drain_at != -1 and stop_at != -1, "both the drain and the stop must be present"
    assert drain_at < stop_at, \
        "the warm drain must run BEFORE 'nssm stop anchor' (service still up = state to snapshot)"


def test_wrapper_is_fail_open():
    """A failed drain must never block the restart - a warm restart is a bonus,
    not a gate (the drain itself is best-effort / never raises)."""
    text = SCRIPT.read_text(encoding="utf-8", errors="replace").lower()
    assert "fail-open" in text, \
        "the wrapper must document/behave fail-open: drain failure still restarts"


def test_drain_module_importable_and_bounded():
    """The wired module must import and expose the timeout-bounded warm-seed
    (a wedged model call can never block a restart)."""
    import sys
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools import pre_restart_drain as drain_mod
    assert hasattr(drain_mod, "drain")
    assert hasattr(drain_mod, "ensure_warm_seed")
    assert isinstance(drain_mod.DRAIN_SUMMARY_TIMEOUT, (int, float))
    # dry-run never mutates and never raises
    report = drain_mod.drain(dry_run=True)
    assert report["ok"] is True and report["dry_run"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
