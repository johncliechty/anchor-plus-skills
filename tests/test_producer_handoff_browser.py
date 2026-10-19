from playwright.sync_api import expect
from tests.test_steward_refinement_browser import campaign_server, cockpit, _expand_foundation


def test_mapped_failure_and_unmapped_work_are_visible_in_authenticated_workflow(cockpit):
    from steward_cockpit.producer_handoff import record_handoff, capture_context
    page, server = cockpit
    assert record_handoff(server.campaign,'terminal','unmapped','Unmapped source fixture')['ok']
    assert record_handoff(server.campaign,'job','failed','Failed producer fixture',context=capture_context(server.campaign,'foundation'),terminal='failed')['ok']
    page.reload()
    step = _expand_foundation(page)
    surface = page.frame_locator('[data-fsframe]')
    unmapped = surface.locator('[data-steps] summary').filter(has_text='not yet placed in the plan')
    expect(unmapped).to_be_visible()
    unmapped.click()
    expect(surface.locator('[data-steps]').get_by_text('Unmapped source fixture',exact=False)).to_be_visible()
    failed = step.locator('summary').filter(has_text='work item(s) awaiting Steward review')
    expect(failed).to_be_visible()
    failed.click()
    expect(step.get_by_text('Failed producer fixture',exact=False)).to_be_visible()
    expect(step.get_by_text('Producer failed; Steward recovery required',exact=False)).to_be_visible()
