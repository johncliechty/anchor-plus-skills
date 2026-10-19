"""W0 of the steward revision (2026-09-28): presence — where he is, and the leave on an explicit switch."""
import importlib

import pytest


@pytest.fixture
def pres(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    from steward_cockpit import presence
    importlib.reload(presence)
    return presence


def test_first_open_and_same_project_are_not_a_switch(pres):
    assert pres.read_presence() == {}
    assert pres.note_open("mba", now=100.0, folder="C:/x/mba") == (None, None, "")
    assert pres.read_presence() == {"project_id": "mba", "at": 100.0, "folder": "C:/x/mba"}
    assert pres.note_open("mba", now=160.0, folder="C:/x/mba") == (None, None, "")
    assert pres.read_presence()["at"] == 160.0
    assert pres.note_open("", now=170.0) == (None, None, ""), "an empty id records nothing"
    assert pres.read_presence()["project_id"] == "mba"


def test_a_switch_returns_the_project_he_left_when_and_the_record_he_had_open(pres):
    pres.note_open("mba", now=100.0, folder="C:/x/mba/peter")
    assert pres.note_open("magi", now=250.0) == ("mba", 100.0, "C:/x/mba/peter")
    assert pres.read_presence() == {"project_id": "magi", "at": 250.0, "folder": ""}
    assert pres.note_open("mba", now=300.0) == ("magi", 250.0, "")


def test_the_sleep_fallback_leaves_once_only_when_he_is_still_on_that_record(pres):
    calls = []
    fn = lambda pid, at: calls.append((pid, at)) or {"ok": True}
    pres.note_open("mba", now=1_700_000_000.0, folder="C:\\x\\MBA\\peter")
    assert pres.leave_if_still_here("c:/x/mba/peter/", fn, now=1_700_000_060.0) is True
    assert calls == [("mba", "2023-11-14T22:14:20Z")]
    assert pres.read_presence()["folder"] == "", "the stored record is cleared on ok"
    assert pres.leave_if_still_here("c:/x/mba/peter/", fn, now=1_700_000_120.0) is False, "a second quiet spell repeats nothing"
    assert len(calls) == 1
    pres.note_open("magi", now=2.0, folder="C:/x/magi")
    assert pres.leave_if_still_here("C:/x/mba", fn, now=3.0) is False, "he is elsewhere: no receipt"
    # an engine failure leaves the record stored, so the next quiet spell tries once more
    pres.note_open("mba", now=4.0, folder="C:/x/mba")
    assert pres.leave_if_still_here("C:/x/mba", lambda pid, at: {"ok": False, "error": "x"}, now=5.0) is False
    assert pres.read_presence()["folder"] == "C:/x/mba"


def test_on_open_runs_the_leave_for_the_previous_project_only_on_a_switch(pres):
    calls = []
    fn = lambda pid, at, rec: calls.append((pid, at, rec))
    assert pres.on_open("mba", fn, now=100.0, background=False, folder="C:/x/mba/peter") is None
    assert calls == []
    assert pres.on_open("mba", fn, now=120.0, background=False, folder="C:/x/mba/peter") is None
    assert calls == []
    assert pres.on_open("magi", fn, now=1_700_000_000.0, background=False) == "mba"
    assert calls == [("mba", "2023-11-14T22:13:20Z", "C:/x/mba/peter")], "the record he HAD open, stored at his open"


def test_a_failing_leave_never_raises(pres):
    def boom(pid, at, rec):
        raise RuntimeError("engine down")
    pres.on_open("mba", boom, now=1.0, background=False)
    assert pres.on_open("magi", boom, now=2.0, background=False) == "mba"
