"""usage_capacity — the rail's capacity rows count what Anchor has seen spend per engine in the five-hour window and
the week, from the usage ledgers, and say what they cannot see (W4, High Seat)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usage_capacity as uc  # noqa: E402

NOW = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)


def _doc(path, entries):
    path.write_text(json.dumps({"engine_session_uuid": path.stem, "entries": {"e%d" % k: e for k, e in enumerate(entries)}}), encoding="utf-8")


def _e(cli, ago, tokens, ms=0):
    return {"cli": cli, "tokens": tokens, "duration_ms": ms, "recorded_at": (NOW - ago).strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_the_rows_count_the_window_and_the_week_per_engine_and_say_what_they_cannot_see(tmp_path):
    _doc(tmp_path / "a.json", [_e("claude", timedelta(hours=1), 1000), _e("claude", timedelta(hours=6), 5000), _e("claude", timedelta(days=8), 999)])
    _doc(tmp_path / "b.json", [_e("chatgpt", timedelta(hours=2), 300, ms=60000), _e("grok", timedelta(days=2), 2_500_000, ms=180000)])
    (tmp_path / "junk.json").write_text("not json", encoding="utf-8")
    out = uc.anchor_seen(now=NOW, directory=str(tmp_path), jobs="", ttl=0)
    rows = {r["cli"]: r for r in out["rows"]}
    assert out["docs"] == 2 and out["signal"] is None and [r["name"] for r in out["rows"]] == ["Claude", "ChatGPT", "Grok", "Gemini"]
    assert rows["claude"]["window_tokens"] == 1000 and rows["claude"]["week_tokens"] == 6000 and rows["claude"]["week_turns"] == 2
    assert rows["claude"]["state"] == "Anchor-seen · 1.0k tokens in the five-hour window · 6.0k this week"
    assert "claude.ai’s own bars are the truth" in rows["claude"]["note"] and "no percentage" in rows["claude"]["note"]
    assert rows["chatgpt"]["window_tokens"] == 300 and "1 ledger entry this week" in rows["chatgpt"]["note"]
    assert rows["grok"]["window_tokens"] == 0 and rows["grok"]["state"].endswith("0 tokens in the five-hour window · 2.5M this week")
    assert "3 min" in rows["grok"]["note"]
    assert rows["gemini"]["state"] == "not connected"


def test_an_engine_with_nothing_and_a_missing_ledger_dir_answer_honestly(tmp_path):
    out = uc.anchor_seen(now=NOW, directory=str(tmp_path / "nowhere"), jobs="", ttl=0)
    assert out["docs"] == 0 and all(r["state"] in ("Anchor-seen · nothing this week", "not connected") for r in out["rows"])
    rows = uc.capacity_rows(now=NOW, directory=str(tmp_path / "nowhere"), jobs="")
    assert [r["name"] for r in rows] == ["Claude", "ChatGPT", "Grok", "Gemini"] and set(rows[0]) == {"name", "state", "note", "bars", "amber"}
    assert "no Claude run this week has reported" in rows[0]["note"]


def test_the_answer_is_cached_for_five_minutes_per_directory(tmp_path):
    _doc(tmp_path / "a.json", [_e("claude", timedelta(hours=1), 10)])
    first = uc.anchor_seen(now=NOW, directory=str(tmp_path), jobs="", ttl=300)
    _doc(tmp_path / "b.json", [_e("claude", timedelta(hours=1), 990)])
    assert uc.anchor_seen(now=NOW, directory=str(tmp_path), jobs="", ttl=300) is first             # cached
    fresh = uc.anchor_seen(now=NOW, directory=str(tmp_path), jobs="", ttl=0)
    assert {r["cli"]: r for r in fresh["rows"]}["claude"]["week_tokens"] == 1000


def test_token_formatting():
    assert [uc.fmt_tokens(n) for n in (0, 820, 9303, 2_100_000)] == ["0", "820", "9.3k", "2.1M"]


# ── the limit signal: the CLI's own windows, read from the newest job log ──────────────────────

def _event(five, seven, status="allowed", threshold=None, resets=None):
    info = {"status": status, "resetsAt": resets or int(NOW.timestamp()) + 3600, "rateLimitType": "five_hour",
            "unifiedWindows": {"five_hour": {"utilization": five, "resetsAt": resets or int(NOW.timestamp()) + 3600},
                               "seven_day": {"utilization": seven, "resetsAt": int(NOW.timestamp()) + 3 * 86400}}}
    if threshold is not None:
        info["surpassedThreshold"] = threshold
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": info, "uuid": "u", "session_id": "s"})


def test_the_newest_run_reports_the_account_windows_and_amber_over_eighty(tmp_path):
    jobs = tmp_path / "rnd_jobs"; jobs.mkdir()
    older = jobs / "old.log"; older.write_text("x\n" * 3000 + _event(0.84, 0.40, "allowed_warning", 0.75) + "\n" + '{"type":"result"}\n', encoding="utf-8")
    newer = jobs / "new.log"; newer.write_text('{"type":"system"}\n' + _event(0.30, 0.05) + "\n" + '{"type":"assistant"}\n', encoding="utf-8")
    os.utime(older, (NOW.timestamp() - 7200, NOW.timestamp() - 7200)); os.utime(newer, (NOW.timestamp() - 600, NOW.timestamp() - 600))
    sig = uc.latest_limit_signal(now=NOW, directory=str(jobs))
    assert sig["log"] == "new.log" and sig["five_hour"]["utilization"] == 0.30 and sig["seven_day"]["utilization"] == 0.05 and sig["status"] == "allowed"
    led = tmp_path / "ledger"; led.mkdir()
    _doc(led / "a.json", [_e("claude", timedelta(hours=1), 1000)])
    row = {r["cli"]: r for r in uc.anchor_seen(now=NOW, directory=str(led), jobs=str(jobs), ttl=0)["rows"]}["claude"]
    assert row["state"].startswith("five-hour window 30% \u00b7 resets ") and "week 5% \u00b7 resets" in row["state"]
    assert [b["pct"] for b in row["bars"]] == [30, 5] and not any(b["warn"] for b in row["bars"]) and row["amber"] == ""
    assert "10 min ago, job new.log" in row["note"] and "Anchor-seen 1.0k tokens" in row["note"] and "it is that account as of that run, so a later chat is outside it" in row["note"]
    # the older run alone: amber, with the CLI's own warning threshold
    newer.unlink()
    row2 = {r["cli"]: r for r in uc.anchor_seen(now=NOW, directory=str(led), jobs=str(jobs), ttl=0)["rows"]}["claude"]
    assert row2["bars"][0] == {"label": "5h", "pct": 84, "warn": True} and row2["amber"].startswith("amber \u2014 over 80% of a known limit: Claude\u2019s five-hour window at 84%")
    assert "the CLI warned at 75%" in row2["note"]
    # a window whose reset has passed says so; the old percentage is not shown as the meter
    older.write_text(_event(0.84, 0.40, resets=int(NOW.timestamp()) - 600) + "\n", encoding="utf-8")
    os.utime(older, (NOW.timestamp() - 7200, NOW.timestamp() - 7200))
    row3 = {r["cli"]: r for r in uc.anchor_seen(now=NOW, directory=str(led), jobs=str(jobs), ttl=0)["rows"]}["claude"]
    assert row3["state"].startswith("five-hour window reset at ") and "was 84% before it; no newer run has reported" in row3["state"]
    assert row3["bars"][0]["pct"] is None and row3["amber"] == "" and "2 h ago" in row3["note"]
    # a log with no event, or a malformed line, yields no signal
    for p in jobs.glob("*.log"):
        p.unlink()
    (jobs / "z.log").write_text('{"type":"rate_limit_event","rate_limit_info":"nope"}\n', encoding="utf-8")
    assert uc.latest_limit_signal(now=NOW, directory=str(jobs)) is None


def test_the_row_renders_with_two_bars_and_the_amber_word():
    import high_seat_page as hsp
    h = hsp.capacity_row_html({"name": "Claude", "state": "five-hour window 84% \u00b7 resets 16:40 \u00b7 week 40% \u00b7 resets Sat 18:00",
                               "note": "the account\u2019s own windows", "bars": [{"label": "5h", "pct": 84, "warn": True}, {"label": "wk", "pct": 40, "warn": False}],
                               "amber": "amber \u2014 over 80% of a known limit: Claude\u2019s five-hour window at 84%, resets 16:40; hold a long run until then"})
    assert h.count('class="wbar"') == 2 and 'class="bar warn"' in h and '<b style="width:84%"></b>' in h and '<span class="p warn">84%</span>' in h
    unknown = hsp.capacity_row_html({"name": "Claude", "state": "five-hour window reset at 18:10", "note": "n", "bars": [{"label": "5h", "pct": None, "warn": False}], "amber": ""})
    assert '<span class="p">?</span>' in unknown and "est" not in unknown
    assert '<span class="amberword">amber' in h and "hold a long run until then" in h
    plain = hsp.capacity_row_html({"name": "Gemini", "state": "not connected", "note": "a future subscription", "bars": [], "amber": ""})
    assert "wbar" not in plain and "amberword" not in plain and "not connected" in plain
