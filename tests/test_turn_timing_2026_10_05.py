"""W1 of the two-lane plan (2026-10-05): every steward turn leaves one timing line - the wait, the first word, the turn,
the tools - and a reader turns them into the responsiveness table."""
import json
import os
import sys
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from steward_cockpit import steward_engine as se  # noqa: E402


def test_a_turn_leaves_one_timing_line(tmp_path):
    eng = SimpleNamespace(dir=str(tmp_path), cli="chatgpt", model_selection={"effort": "high"}, _turn_origin="human")
    t = time.time()
    eng._timing = {"arrived": t - 30, "started": t, "first_word": t + 12.5, "tools": 3}
    se.Engine._record_timing(eng, 95.2, False)
    row = json.loads((tmp_path / ".ecgberht" / "turn-timing.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["queued_s"] == 30.0 and row["first_word_s"] == 12.5 and row["turn_s"] == 95.2 and row["tools"] == 3
    assert row["origin"] == "human" and row["effort"] == "high" and eng._timing is None
    se.Engine._record_timing(eng, 1, False)   # nothing measured: no line, no raise
    assert len((tmp_path / ".ecgberht" / "turn-timing.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_the_reader_reads_the_effort_lines(tmp_path):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import steward_timing as st
    d = tmp_path / "Eff" / ".ecgberht"; d.mkdir(parents=True)
    d.joinpath("turn-timing.jsonl").write_text(json.dumps({"at": "2026-10-05T12:00:00", "origin": "human", "first_word_s": 5}) + "\n", encoding="utf-8")
    rows = st.rows_for(str(tmp_path))
    assert rows and rows[0]["effort"] == "Eff" and st._pct([5, 50, 9], .5) == 9
