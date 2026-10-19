"""Usage-visibility + live-spawn-guard regression tests (2026-07-26 hardening).

The three defects these pin, all found by the Anchor hardening review
(planning/anchor-hardening-2026-07-26/FINDINGS-F-usage-tracking.md):

1. ``ROLLUP_LANES`` excluded ``general`` — the DAILY driver lane — so every
   run-cost record written there was unreachable by every rollup forever.
2. ``list_efforts`` trusted ``index.json`` alone; the index is a
   read-modify-write guarded by an in-process lock only, so a second process
   silently drops entries (observed live: 17 pointer files, 13 indexed, both
   run-cost records missing).
3. The summarizer reads ``session["member_files"]``; the two callers in
   terminal_session built ``{"efforts": …}`` — so EVERY summary saw zero
   members ⇒ "no grounded claims" + "0 tokens · 0.0s · 0 run(s)".

Plus the fail-closed engine-spawn guard (the suite once leaked 8,816 billed
sessions). Hermetic: no PTY, no model, no network.
"""
import json
import os
from pathlib import Path

import pytest

import effort_history as eh
import terminal_session as ts


def _seed_run_cost(folder: Path, pid: str, lane: str, sid: str,
                   tokens: int, ms: int, index_it: bool):
    """Write a run-cost pointer record; optionally register it in index.json."""
    eff_dir = eh.efforts_dir(str(folder), pid, lane)
    eff_dir.mkdir(parents=True, exist_ok=True)
    job_id = f"run-cost-{sid}"
    rec = {
        "job_id": job_id, "kind": "run-cost", "session_id": sid,
        "lane": lane, "usage_state": "measured",
        "cost": {"total_tokens": tokens, "input_tokens": tokens,
                 "output_tokens": 0, "total_cost_usd": 0.0,
                 "duration_ms": ms},
        "created_at": 1785000000,
    }
    (eff_dir / f"{job_id}{eh.POINTER_SUFFIX}").write_text(
        json.dumps(rec), encoding="utf-8")
    if index_it:
        idx = eff_dir.parent / eh.INDEX_NAME
        cur = []
        if idx.exists():
            try:
                cur = json.loads(idx.read_text(encoding="utf-8")) or []
            except Exception:
                cur = []
        cur.append(job_id)
        idx.write_text(json.dumps(cur), encoding="utf-8")
    return job_id


def test_general_lane_is_in_the_cost_rollup(tmp_path):
    """The daily 'general' lane must reach the rollup (was excluded forever)."""
    assert "general" in eh.ROLLUP_LANES
    pid = "p_general_rollup"
    _seed_run_cost(tmp_path, pid, "general", "s1", 2_757_886, 444_813, True)
    roll = eh.project_effort_rollup(pid, folder_path=str(tmp_path))
    assert roll["tokens"] == 2_757_886, roll
    assert roll["wall_clock_ms"] == 444_813, roll


def test_list_efforts_recovers_records_missing_from_a_lossy_index(tmp_path):
    """A pointer record on disk but absent from index.json must still be read."""
    pid = "p_index_loss"
    indexed = _seed_run_cost(tmp_path, pid, "general", "s_in", 100, 10, True)
    orphan = _seed_run_cost(tmp_path, pid, "general", "s_out", 400_000, 85_700,
                            False)  # written, never indexed (the live bug)
    got = {e.get("job_id") for e in
           eh.list_efforts(str(tmp_path), pid, "general")}
    assert indexed in got
    assert orphan in got, "a record present on disk but missing from the index was dropped"
    roll = eh.project_effort_rollup(pid, folder_path=str(tmp_path))
    assert roll["tokens"] == 400_100, roll


def test_summarizer_session_dict_uses_the_member_files_key():
    """The writer's key must match what the summarizer actually reads."""
    src = Path(ts.__file__).read_text(encoding="utf-8", errors="replace")
    # Both background-summary call sites must carry member_files.
    assert src.count('"member_files": efforts') >= 2, (
        "terminal_session must hand the summarizer session['member_files'] — "
        "the key it reads (summarizer.py:291/:427/:456/:484/:1029)")


def test_engine_spawn_guard_refuses_real_engines_under_test():
    """Fail-closed: a real engine basename cannot be spawned under the guard."""
    prior = os.environ.get("ANCHOR_TESTS_ALLOW_LIVE")
    os.environ.pop("ANCHOR_TESTS_ALLOW_LIVE", None)
    try:
        for argv in (["claude", "-p"], ["C:/x/claude.exe"], ["agy"],
                     ["gemini", "--yolo"], ["grok"]):
            with pytest.raises(ts.TerminalSessionError) as ei:
                ts.assert_not_live_engine_under_test(argv)
            assert "live-engine-spawn-refused" in str(ei.value)
        # A stub command is fine.
        ts.assert_not_live_engine_under_test(["python", "-c", "pass"])
        # Explicit opt-in disarms it.
        os.environ["ANCHOR_TESTS_ALLOW_LIVE"] = "1"
        ts.assert_not_live_engine_under_test(["claude", "-p"])
    finally:
        os.environ.pop("ANCHOR_TESTS_ALLOW_LIVE", None)
        if prior is not None:
            os.environ["ANCHOR_TESTS_ALLOW_LIVE"] = prior


def test_engine_cmd_seam_overrides_the_raw_binary(monkeypatch):
    """ANCHOR_ENGINE_CMD is the PTY-path mirror of ANCHOR_RUNNER_CMD."""
    monkeypatch.setenv(ts.ENGINE_CMD_ENV, "python -c pass")
    assert ts._resolve_engine_cmd("claude") == "python -c pass"
    assert ts._resolve_engine_cmd("gemini") == "python -c pass"
    monkeypatch.delenv(ts.ENGINE_CMD_ENV, raising=False)
    assert ts._resolve_engine_cmd("claude") == "claude"
