"""Doctor must prove actual human replies, independent of automatic turns."""
import json
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def cockpit_check(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    import anchor_healthcheck as hc
    from steward_cockpit import steward_engine as engine
    monkeypatch.setattr(engine, "STATE_FILE", tmp_path / "live-state.json")
    original = engine.STATE_FILE
    yield hc, engine, original
    assert engine.STATE_FILE == original


@pytest.mark.parametrize("shape_retry", [True, False])
def test_real_fake_stream_answers_both_messages(cockpit_check, monkeypatch, shape_retry):
    hc, engine, _ = cockpit_check
    if not shape_retry:
        # The old check passed only when an unrelated correction added an end.
        monkeypatch.setattr(engine, "_has_recommendation", lambda text: True)
    report = hc.Report()
    hc.check_steward_cockpit_surface(report)
    assert not report.issues, report.issues


@pytest.mark.parametrize("fault", [
    "only_greeting", "missing_end", "missing_second_reply", "missing_status",
    "error_after_reply", "split_across_ends", "busy", "queued",
])
def test_incomplete_or_unrelated_turns_fail(cockpit_check, monkeypatch, fault):
    hc, engine, _ = cockpit_check

    class ProbeEngine:
        def __init__(self, campaign_dir, **kwargs):
            self.root = campaign_dir
            self.events, self.queue = [], []
            self.busy = self.broken = False

        def emit(self, kind, **fields):
            self.events.append({"t": kind, "seq": len(self.events) + 1, **fields})

        def say(self, message):
            self.emit("john", text=message)
            if fault == "only_greeting":
                self.emit("delta", text="Good to see you. The campaign is ready.")
            elif fault == "missing_second_reply" and message.startswith("grasscatch"):
                self.emit("delta", text="Heard. (Fake steward - unrelated reply.)")
            elif fault == "split_across_ends":
                self.emit("delta", text="Heard. (Fake ")
                self.emit("turn_end")
                self.emit("delta", text="steward - unrelated turn.)")
            else:
                self.emit("delta", text=("Caught it - parked on the Strip" if message.startswith("grasscatch")
                                         else "Heard. (Fake steward - reply.)"))
            if fault != "missing_end":
                self.emit("turn_end")
            if fault == "error_after_reply":
                self.emit("sys", text="the steward's turn ended in an error: injected failure")
            if fault != "missing_status":
                self.emit("status")
            self.busy = fault == "busy"
            self.queue = ["undelivered"] if fault == "queued" else []
            from pathlib import Path
            (Path(self.root) / ".ecgberht" / "status-summary.json").write_text(
                json.dumps({"now": ["test"], "plan": {}}), encoding="utf-8")
            return {"ok": True}

        def state(self):
            return {"alive": True, "busy": self.busy, "queued": len(self.queue),
                    "light": "green", "epoch": 1, "open_question": ""}

        def stop(self):
            pass

    monkeypatch.setattr(engine, "Engine", ProbeEngine)
    # Advance only the healthcheck's polling clock; no engine or global clock
    # changes, and no real 30-second delay for a deliberately broken fixture.
    ticks = iter(range(0, 1000, 10))
    monkeypatch.setattr(hc, "time", SimpleNamespace(
        time=time.time, monotonic=lambda: next(ticks), sleep=lambda seconds: None))
    report = hc.Report()
    hc.check_steward_cockpit_surface(report)
    assert any("engine did not complete reply" in issue for issue in report.issues), report.checks
