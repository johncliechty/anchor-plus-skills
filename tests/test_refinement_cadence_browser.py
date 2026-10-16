"""Opt-in wall-clock cadence proof; a disposable server, never production acceptance."""
import json
import os
from pathlib import Path
import threading
import time

import pytest
from tests.test_steward_refinement_browser import campaign_server, cockpit, _expand_foundation


@pytest.mark.skipif(not os.environ.get("STEWARD_CADENCE_PROOF"), reason="opt-in two real ten-minute intervals")
def test_two_real_cadence_intervals_reach_authenticated_pane(cockpit, monkeypatch):
    from steward_cockpit import steward_routes, steward_engine
    page, server = cockpit
    _expand_foundation(page)
    engine = steward_routes.get_engine(str(server.campaign))
    assert steward_engine.TICK_SECONDS == 600
    class OwnedBackground:
        stopped = False
        def poll(self):
            return 0 if self.stopped else None
    proc = OwnedBackground()
    engine.proc = proc
    engine.fake = True
    # Only the producer's background liveness is simulated. The real ticker,
    # status composition, HTTP polling, renderer and acknowledgement are used.
    monkeypatch.setattr(engine, "_working_bg", lambda: True)
    engine.busy = False
    engine.last_status = time.time()
    engine.last_output = time.time()
    engine._status_update()
    receipt = server.campaign / ".ecgberht" / "delivery.json"
    page.wait_for_timeout(2000)
    previous = json.loads(receipt.read_text(encoding="utf-8"))["last_acked_status_at"]
    worker = threading.Thread(target=engine._ticker, args=(proc,), daemon=True)
    started = time.time()
    worker.start()
    observations = []
    try:
        for interval in range(2):
            deadline = time.time() + 660
            while time.time() < deadline:
                page.wait_for_timeout(1000)
                data = json.loads(receipt.read_text(encoding="utf-8"))
                if data.get("last_acked_status_at") != previous:
                    observations.append({"elapsed": time.time()-started, "receipt": data})
                    previous = data["last_acked_status_at"]
                    break
            else:
                pytest.fail("Scheduled status was not acknowledged by the real pane")
        assert observations[0]["elapsed"] >= 590
        assert observations[1]["elapsed"] - observations[0]["elapsed"] >= 590
        out = Path(os.environ["STEWARD_CADENCE_PROOF"])
        out.write_text(json.dumps({"scope":"disposable authenticated Anchor, actual 600s ticker, simulated background producer", "observations":observations},indent=2),encoding="utf-8")
        page.screenshot(path=str(out.with_suffix('.png')), full_page=True)
    finally:
        proc.stopped = True
        worker.join(timeout=35)
        engine.proc = None
        assert not worker.is_alive()
