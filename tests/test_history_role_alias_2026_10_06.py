"""A hand-written steward line that names the steward (role "ecgberht") reads as the steward, not a broken history
(AI Club 2026-10-02..05). Other malformed turns still fail closed."""
import json

import pytest

from steward_cockpit import conversation_history as ch


def _write(tmp_path, turns):
    d = tmp_path / ".ecgberht"
    d.mkdir()
    (d / "conversation-log.json").write_text(json.dumps({"turns": turns}), encoding="utf-8")
    return tmp_path


def test_steward_names_read_as_the_steward(tmp_path):
    camp = _write(tmp_path, [
        {"role": "john", "text": "hi", "at": "2026-10-02T20:00:00+00:00"},
        {"role": "ecgberht", "text": "Delivered.", "at": "2026-10-02T20:40:36+00:00", "turn_id": "ecgberht-x"},
        {"role": "Aladdin", "text": "ok", "at": "2026-10-02T20:41:00+00:00"},
    ])
    doc = ch.read_history_document(str(camp))
    assert [t["role"] for t in doc["turns"]] == ["john", "steward", "steward"]


def test_an_unknown_role_still_fails_closed(tmp_path):
    camp = _write(tmp_path, [{"role": "intruder", "text": "x", "at": "2026-10-02T20:00:00+00:00"}])
    with pytest.raises(ch.ConversationHistoryError):
        ch.read_history_document(str(camp))
