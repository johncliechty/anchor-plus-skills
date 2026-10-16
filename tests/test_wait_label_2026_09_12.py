import pytest
from steward_cockpit.steward_campaign import _real_wait

@pytest.mark.parametrize('text',['nothing — the plan is approved and research is running',
                                'None - independent work is continuing','none','Nothing.'])
def test_negative_wait_with_explanation_is_not_an_approval_request(text):
    assert _real_wait(text)==''

@pytest.mark.parametrize('text',['Approve the plan','None of these plans is approved',
                                'Nothing else is needed except your decision'])
def test_real_or_qualified_requests_are_preserved(text):
    assert _real_wait(text)==text
