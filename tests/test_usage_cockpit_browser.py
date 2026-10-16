"""Usage visibility through the real authenticated disposable cockpit."""
import io
from types import SimpleNamespace

from playwright.sync_api import expect

from tests.test_steward_refinement_browser import campaign_server, cockpit
from steward_cockpit import steward_engine, steward_routes


def test_project_usage_includes_checkpoint_and_remains_visible_asleep(cockpit, monkeypatch):
    page, server = cockpit
    eng = steward_routes.get_engine(str(server.campaign), False, None)
    monkeypatch.setattr(eng, "_status_update", lambda **kw: None)
    eng.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    eng.session_id = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
    eng.turn_text = "Recorded prior response."
    eng._handle({"type": "result", "subtype": "success", "total_cost_usd": 1.25,
                 "usage": {"input_tokens": 10, "output_tokens": 0}}, eng.proc)
    eng.busy = True
    eng._handle({"type": "usage_checkpoint", "session_id": eng.session_id,
                 "invocation_id": "01a08260-068d-76a1-99f6-5a7bdf3aaab9",
                 "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 20},
                 "token_status": "reported", "usage_source": "codex-rollout"}, eng.proc)
    steward_engine._update_state(str(server.campaign) + "-unrelated", {
        "usage": {"tokens": 999999, "spend": 999, "cost_complete": True, "turns": 1}})
    import effort_history
    effort_history.record_effort(str(server.campaign), server.project_id, "research", "recorded-job-1", extra={
        "label": "Earlier research run", "source": "run",
        "cost": {"total_tokens": 456789, "total_cost_usd": 0}})
    page.reload()
    expect(page.locator('[data-total]')).to_contain_text("130")
    expect(page.locator('[data-total]')).to_contain_text("unpriced")
    expect(page.locator('[data-total]')).not_to_contain_text("456,789")
    other = page.locator('[data-other-usage]')
    other.locator('summary').click()
    expect(other).to_contain_text("Earlier research run")
    expect(other).to_contain_text("456,789 recorded tokens")
    expect(other).to_contain_text("coverage unverified")
    page.screenshot(path=str(server.campaign.parent / "project-usage-sources.png"), full_page=True)
    page.locator('[data-efforts] .efrow').filter(has_text='foundation campaign').first.click()
    surface = page.frame_locator('[data-fsframe]')
    footer = surface.locator('[data-spend]')
    expect(footer).to_contain_text("130")
    expect(footer).to_contain_text("Total $")                   # one total on the line (Wave I); the parts sit in the hover title
    expect(footer).not_to_contain_text("effort sessions")
    expect(footer).to_contain_text("1.25")
    expect(footer).to_contain_text("no dollar amount")
    assert "effort total" in footer.get_attribute("title").lower()   # the parts stay in the hover
    assert "999999" not in footer.inner_text()
    eng.proc = None
    eng.busy = False
    page.reload()
    page.locator('[data-efforts] .efrow').filter(has_text='foundation campaign').first.click()
    footer = page.frame_locator('[data-fsframe]').locator('[data-spend]')
    expect(footer).to_contain_text("130")
    expect(footer).to_contain_text("1.25")
    expect(footer).to_contain_text("Total $")
    assert "session" in footer.get_attribute("title").lower()
    page.screenshot(path=str(server.campaign.parent / "usage-cockpit.png"), full_page=True)
