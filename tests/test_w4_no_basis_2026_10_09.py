"""W4 of the night of 2026-10-09: with no estimate of its own and no finished work of the same kind to go by, the
status says "no basis" and shows no clock time (it used to publish start + max(2 x elapsed, 10 min))."""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import steward_campaign as sc  # noqa: E402


def test_no_history_says_no_basis_and_gives_no_clock_time(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "typical_duration_s", lambda *a, **k: None)
    now = time.time()
    for kind in ("code_job", "skill_job", "turn"):
        text = sc.finish_time(now - 900, now, kind, str(tmp_path))
        assert text.startswith("no basis for an estimate yet") and not re.search(r"\d{1,2}:\d{2}", text), text


def test_its_own_estimate_and_same_kind_history_still_give_a_time(tmp_path, monkeypatch):
    now = time.time()
    assert sc.finish_time(now - 60, now, "skill_job", str(tmp_path), own_eta="14:30").startswith("14:30 (its own estimate")
    monkeypatch.setattr(sc, "typical_duration_s", lambda *a, **k: 1200)
    assert re.match(r"about \d{2}:\d{2} \(estimate: a typical code job here takes 20 min\)",
                    sc.finish_time(now - 60, now, "code_job", str(tmp_path)))
