"""Friction-journal tests (2026-07-26) — the user-initiated journaling loop.

Pins the honesty rules that make this feature trustworthy:
  * capture NEVER calls a model (it must work when engines are down)
  * the user's words are stored VERBATIM
  * nothing self-resolves — a record leaves `open` only by explicit action
  * a clobbered index never hides a record (directory is authoritative)
  * the safe projection never leaks host paths / raw log lines
"""
import json
import time

import pytest


@pytest.fixture()
def fj(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import importlib
    import friction_journal as _fj
    importlib.reload(_fj)
    return _fj


def test_capture_stores_the_users_words_verbatim(fj):
    said = "  the terminal DOUBLE-prints after my laptop sleeps!!  "
    rec = fj.capture(said, body="two screens, one session", severity="problem")
    # Verbatim except the outer whitespace strip — no rewriting, no title-casing.
    assert rec["title"] == said.strip()
    assert rec["body"] == "two screens, one session"
    assert rec["severity"] == "problem"
    assert rec["status"] == "open"
    assert rec["source"] == "user"
    on_disk = json.loads((fj.friction_dir() / f"{rec['id']}.json").read_text("utf-8"))
    assert on_disk["title"] == said.strip()


def test_capture_needs_a_title_but_tolerates_everything_else(fj):
    with pytest.raises(fj.FrictionJournalError):
        fj.capture("   ")
    # An unknown severity degrades to the default rather than refusing the capture:
    # never lose a user's report over a taxonomy quibble.
    rec = fj.capture("something felt off", severity="catastrophic")
    assert rec["severity"] == fj.DEFAULT_SEVERITY


def test_capture_path_makes_no_model_call(fj, monkeypatch):
    """The moment of friction is when engines are down — capture must not need one."""
    import subprocess
    def _boom(*a, **k):  # any spawn attempt fails the test
        raise AssertionError("capture path attempted a subprocess/model call")
    monkeypatch.setattr(subprocess, "run", _boom, raising=False)
    monkeypatch.setattr(subprocess, "Popen", _boom, raising=False)
    rec = fj.capture("engines are wedged and I cannot work")
    assert rec["status"] == "open"


def test_context_is_facts_only_and_auto_attached(fj):
    rec = fj.capture("dictation blew up", project_id="p1", session_id="s1",
                     lane="general", route="/project/p1", engine="claude")
    ctx = rec["context"]
    assert ctx["project_id"] == "p1" and ctx["session_id"] == "s1"
    assert ctx["lane"] == "general" and ctx["engine"] == "claude"
    assert "anchor_version" in ctx and "recent_errors" in ctx
    # No interpretation/judgement fields are minted at capture time.
    assert not any(k in ctx for k in ("diagnosis", "root_cause", "summary"))


def test_nothing_self_resolves_and_status_moves_only_explicitly(fj):
    rec = fj.capture("summaries are useless")
    assert fj.list_records(status="open")
    got = fj.set_status(rec["id"], "resolved", note="fixed the key",
                        commit="121b479")
    assert got["status"] == "resolved"
    assert got["resolution"]["commit"] == "121b479"
    assert fj.list_records(status="open") == []
    with pytest.raises(fj.FrictionJournalError):
        fj.set_status(rec["id"], "not-a-status")


def test_a_clobbered_index_never_hides_a_record(fj):
    """Same index-loss lesson as effort_history: the directory is the truth."""
    a = fj.capture("first thing")
    b = fj.capture("second thing")
    (fj.friction_dir() / fj.INDEX_NAME).write_text("[]", encoding="utf-8")
    ids = {r["id"] for r in fj.list_records()}
    assert {a["id"], b["id"]} <= ids


def test_safe_projection_drops_raw_log_lines(fj):
    rec = fj.capture("something broke")
    proj = fj.safe_projection(rec)
    assert "recent_errors" not in proj["context"]
    assert proj["title"] == "something broke"


def test_report_is_the_sleep_cycle_intake_brief(fj):
    fj.capture("terminal double prints", severity="problem")
    fj.capture("iPad dictation repeats everything", severity="problem")
    fj.capture("token usage shows zero", severity="friction")
    brief = fj.friction_report()
    assert "sleep-cycle intake" in brief
    assert "3 record(s)" in brief
    # Deterministic keyword clustering — never a model judgement.
    assert "terminal" in brief and "dictation/input" in brief and "usage/cost" in brief
    assert "friction-resolve" in brief, "the brief must say how to close a record"
    # Empty-filter case is honest, not blank.
    assert "nothing to clean up" in fj.friction_report(status="resolved")


def test_report_renders_without_unicode_replacement_chars(fj):
    """errors.log is cp1252/utf-8 MIXED; the brief must stay printable."""
    fj.capture("something broke")
    assert "�" not in fj.friction_report()


def test_since_filter_selects_recent_records(fj):
    old = fj.capture("ancient gripe")
    # Backdate the record on disk.
    p = fj.friction_dir() / f"{old['id']}.json"
    rec = json.loads(p.read_text("utf-8"))
    rec["ts"] = time.time() - 86400 * 30
    p.write_text(json.dumps(rec), encoding="utf-8")
    fresh = fj.capture("today's gripe")
    recent = fj.list_records(since_ts=time.time() - 3600)
    ids = {r["id"] for r in recent}
    assert fresh["id"] in ids and old["id"] not in ids


# ── HTTP surface (2026-07-26): the feature must be reachable from the dashboard,
# not only the CLI. Contract-level so no server boot is needed.

def test_endpoints_are_registered_in_the_route_table():
    from pathlib import Path
    rt = Path(__file__).resolve().parent.parent / "route_table.py"
    src = rt.read_text(encoding="utf-8", errors="replace")
    assert '"/api/rnd/journal_friction"' in src, "capture endpoint not routed"
    assert '"/api/rnd/friction"' in src, "read endpoint not routed"
    assert "handle_journal_friction" in src and "handle_friction_list" in src
    # Both must be token-authed like every other rnd surface. Check the route
    # DECLARATION lines (_r(...)), not the handler= continuation lines.
    for line in src.splitlines():
        stripped = line.strip()
        if not stripped.startswith("_r("):
            continue
        if "/api/rnd/journal_friction" in stripped or '"/api/rnd/friction"' in stripped:
            assert "AUTH_TOKEN" in stripped, f"unauthed friction route: {stripped}"


def test_handlers_exist_and_never_call_a_model():
    from pathlib import Path
    gui = Path(__file__).resolve().parent.parent / "anchor_gui.py"
    src = gui.read_text(encoding="utf-8", errors="replace")
    assert "def handle_journal_friction(" in src
    assert "def handle_friction_list(" in src
    cap = src.split("def handle_journal_friction", 1)[1].split("\ndef ", 1)[0]
    for forbidden in ("job_runner", "summarize", "launch(", "_sm."):
        assert forbidden not in cap, (
            f"the capture path must not touch {forbidden} — it has to work "
            "when the engines are down")
    # The read path must hand out the SAFE projection (no raw log lines).
    read = src.split("def handle_friction_list", 1)[1].split("\ndef ", 1)[0]
    assert "safe_projection" in read
