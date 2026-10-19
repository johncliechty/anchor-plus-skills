"""Original goal brainstorming stays one conversation, with an atomic association."""
import pytest
from steward_cockpit import conversation_history as history


def test_goal_association_preserves_originals_and_is_idempotent(tmp_path):
    original = {'role':'john','text':'Entire original dictation\n'+'word '*900,
                'at':'2026-10-04T14:00:00Z','turn_id':'source','extra':{'keep':True}}
    history.append_turns(tmp_path,[original,{'role':'john','text':'Copy to goal','turn_id':'permission'}])
    assert history.associate_turns_with_goal(tmp_path,['source'],'anchor-steward',source_turn_id='permission') == 1
    result=history.read_history_document(tmp_path)
    assert len(result['turns']) == 2
    changed=result['turns'][0]
    for key,value in original.items(): assert changed[key] == value
    assert changed['goal'] == 'anchor-steward'
    assert changed['goal_associations'][0]['source_turn_id'] == 'permission'
    before=(tmp_path/'.ecgberht/conversation-log.json').read_bytes()
    assert history.associate_turns_with_goal(tmp_path,['source'],'anchor-steward',source_turn_id='permission') == 0
    assert (tmp_path/'.ecgberht/conversation-log.json').read_bytes() == before


@pytest.mark.parametrize('ids,code', [(['source','missing'],'goal_association_turn_missing'),(['source','other'],'goal_association_conflict')])
def test_invalid_batch_changes_nothing(tmp_path,ids,code):
    history.append_turns(tmp_path,[{'role':'john','text':'Original','turn_id':'source'},
        {'role':'john','text':'Other','turn_id':'other','goal':'different'},
        {'role':'john','text':'Permission','turn_id':'permission'}])
    before=(tmp_path/'.ecgberht/conversation-log.json').read_bytes()
    with pytest.raises(history.ConversationHistoryError) as error:
        history.associate_turns_with_goal(tmp_path,ids,'anchor-steward',source_turn_id='permission')
    assert error.value.code == code
    assert (tmp_path/'.ecgberht/conversation-log.json').read_bytes() == before
