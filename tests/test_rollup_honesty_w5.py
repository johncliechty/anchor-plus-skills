"""W5 STUB GATE — Rollup Honesty: measured / unmeasured(reason) / capture-failed,
dedup, per-segment badges (Honest Telemetry).

Cites ``NORTH-STAR-AMENDMENT.md`` (defer-and-badge · tripwire severity ·
Gemini-segment RULED letter C · no-own-pricing-table) + ``W1-CLOSED-WORLD-AUDIT.md``
(the sibling-structure path: ``rollup_honesty`` does NOT mutate
``project_effort_rollup``'s dict, so the two exact-shape legacy assertions stay
green unmodified). Serves criteria (2),(3).

done-when (verbatim from the plan): the dedup test, the three-state render tests,
the per-segment 'partial' test, and the untouched v4/v8 suites are all green, and
the dashboard rollup visibly stamps the capture-rate with capture-failed counted
separately.

No ``pytest.importorskip`` / ``skip`` / ``xfail`` / ``skipif`` anywhere (the W1
lesson — a skip rise trips Foreman's §5 test-integrity guard). git is a hard
requirement in CI, so the integration legs fail honestly (never skip) if absent.
"""
import importlib
import json
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sidecar"
EXPECTED = json.loads((FIXTURES / "EXPECTED.json").read_text(encoding="utf-8"))
FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _fx(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1) The classifier — the single source of truth (PURE, no env)
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifier:
    def test_measured_is_measured(self):
        import usage_capture as uc, rollup_honesty as rh
        rec = {"usage_state": uc.STATE_MEASURED, "backend": "claude"}
        c = rh.classify_session_usage(rec)
        assert c["state"] == rh.STATE_MEASURED
        assert c["reason"] == ""

    def test_unmeasured_carries_reason_enum(self):
        import usage_capture as uc, rollup_honesty as rh
        for reason in (uc.REASON_SIDECAR_PRUNED, uc.REASON_UNCORRELATED,
                       uc.REASON_PRE_FEATURE):
            rec = {"usage_state": uc.STATE_UNMEASURED, "usage_reason": reason}
            c = rh.classify_session_usage(rec)
            assert c["state"] == rh.STATE_UNMEASURED
            # The reason is an ENUM value, never free text.
            assert c["reason"] == reason
            assert rh.reason_label(reason) and rh.reason_label(reason) != ""

    def test_capture_failed_is_its_own_state_never_unmeasured(self):
        import usage_capture as uc, rollup_honesty as rh
        rec = {"usage_state": uc.STATE_CAPTURE_FAILED,
               "usage_reason": uc.REASON_PARSE_ERROR}
        c = rh.classify_session_usage(rec)
        assert c["state"] == rh.STATE_CAPTURE_FAILED
        assert c["state"] != rh.STATE_UNMEASURED
        assert c["reason"] == uc.REASON_PARSE_ERROR

    def test_not_finalized_is_excluded(self):
        import rollup_honesty as rh
        c = rh.classify_session_usage({"usage_state": "", "backend": "claude"})
        assert c["state"] == ""  # not in the denominator

    def test_mixed_session_is_partial_gemini(self):
        """RULED Option C: measured Claude + a gemini segment → PARTIAL, never a
        complete-looking Claude-only 'measured'."""
        import usage_capture as uc, rollup_honesty as rh
        # (a) ended on the gemini backend
        rec_a = {"usage_state": uc.STATE_MEASURED, "backend": "gemini"}
        # (b) round-tripped back to claude but flagged by the durable marker
        rec_b = {"usage_state": uc.STATE_MEASURED, "backend": "claude",
                 "usage_gemini_segment": True}
        for rec in (rec_a, rec_b):
            c = rh.classify_session_usage(rec)
            assert c["state"] == rh.STATE_PARTIAL, rec
            assert c["reason"] == uc.REASON_GEMINI_SEGMENT
            assert c["gemini_segment"] is True

    def test_gemini_only_unmeasured_reason_is_gemini_segment(self):
        import usage_capture as uc, rollup_honesty as rh
        rec = {"usage_state": uc.STATE_UNMEASURED, "backend": "gemini",
               "usage_reason": ""}
        c = rh.classify_session_usage(rec)
        assert c["state"] == rh.STATE_UNMEASURED
        assert c["reason"] == uc.REASON_GEMINI_SEGMENT


# ══════════════════════════════════════════════════════════════════════════════
# 2) The three-state VISUAL model — distinct badges, enum hover, never $0
# ══════════════════════════════════════════════════════════════════════════════

class TestBadges:
    def test_three_states_are_visually_distinct(self):
        import usage_capture as uc, rollup_honesty as rh
        measured = rh.badge_html({"usage_state": uc.STATE_MEASURED,
                                  "backend": "claude"})
        unmeasured = rh.badge_html({"usage_state": uc.STATE_UNMEASURED,
                                    "usage_reason": uc.REASON_SIDECAR_PRUNED})
        capfail = rh.badge_html({"usage_state": uc.STATE_CAPTURE_FAILED,
                                 "usage_reason": uc.REASON_ZERO_USAGE})
        # All three render a badge, each a different CSS class.
        assert "ub-meas" in measured
        assert "ub-unmeas" in unmeasured
        assert "ub-capfail" in capfail
        # capture-failed is RED-tinted; unmeasured is GREY — distinct by style.
        assert "248,81,73" in capfail        # red channel
        assert "140,140,150" in unmeasured   # grey channel
        assert "248,81,73" not in unmeasured  # never blends into red
        # A capture-failed badge is NEVER a measured-$0 look.
        assert "$0.00" not in capfail

    def test_badge_title_is_reason_label_not_free_text(self):
        import usage_capture as uc, rollup_honesty as rh
        b = rh.session_usage_badge({"usage_state": uc.STATE_UNMEASURED,
                                    "usage_reason": uc.REASON_PRE_FEATURE})
        assert b["reason"] == uc.REASON_PRE_FEATURE
        assert b["title"] == rh.reason_label(uc.REASON_PRE_FEATURE)

    def test_partial_badge_reads_gemini_segment_unmeasured(self):
        import usage_capture as uc, rollup_honesty as rh
        b = rh.session_usage_badge({"usage_state": uc.STATE_MEASURED,
                                    "backend": "gemini"})
        assert b["state"] == rh.STATE_PARTIAL
        assert b["label"] == "partial"
        assert "gemini segment unmeasured" in b["title"]

    def test_pending_session_renders_no_badge(self):
        import rollup_honesty as rh
        assert rh.badge_html({"usage_state": ""}) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 3) capture_rate_line — capture-failed counted SEPARATELY, never folded
# ══════════════════════════════════════════════════════════════════════════════

class TestCaptureRateLine:
    def test_line_matches_locked_shape(self):
        import rollup_honesty as rh
        rate = {"window": "30d", "total": 17, "measured": 14, "partial": 0,
                "unmeasured": 2, "capture_failed": 1}
        line = rh.capture_rate_line(rate)
        assert line == "measured 14/17 sessions (30d) · 1 capture-failed"

    def test_capture_failed_never_folded_into_unmeasured(self):
        import rollup_honesty as rh
        rate = {"window": "lifetime", "total": 3, "measured": 1, "partial": 0,
                "unmeasured": 1, "capture_failed": 1}
        line = rh.capture_rate_line(rate)
        assert "1 capture-failed" in line       # its own count
        assert "capture-failed" != "unmeasured"  # (sanity) distinct words
        # The measured numerator excludes both unmeasured AND capture-failed.
        assert line.startswith("measured 1/3")

    def test_partial_surfaced_when_nonzero(self):
        import rollup_honesty as rh
        rate = {"window": "lifetime", "total": 4, "measured": 2, "partial": 1,
                "unmeasured": 1, "capture_failed": 0}
        line = rh.capture_rate_line(rate)
        assert "1 partial" in line
        assert "capture-failed" not in line  # zero → omitted

    def test_zero_project_is_honest(self):
        import rollup_honesty as rh
        line = rh.capture_rate_line({"window": "30d", "total": 0})
        assert "no measured sessions yet" in line

    def test_html_stamp_tints_red_on_capture_failed(self):
        import rollup_honesty as rh
        clean = rh.capture_rate_html({"window": "30d", "total": 2,
                                      "measured": 2, "capture_failed": 0})
        red = rh.capture_rate_html({"window": "30d", "total": 2, "measured": 1,
                                    "capture_failed": 1})
        assert "caprate" in clean and "caprate" in red
        assert "#dc2626" in red          # red-tinted when capture-failed present
        assert "#dc2626" not in clean


# ══════════════════════════════════════════════════════════════════════════════
# 4) project_capture_rate over the registry (temp data dir)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def datadir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(d))
    for mod in ("paths", "usage_ledger", "usage_capture", "session_registry",
                "rollup_honesty"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    return d


class TestProjectCaptureRate:
    def _mk(self, reg, pid, state, reason="", **extra):
        r = reg.register_session(pid, "research", status=reg.STATUS_DONE)
        reg.update_session(r["session_id"], usage_state=state,
                           usage_reason=reason, **extra)
        return r["session_id"]

    def test_counts_each_state_separately(self, datadir):
        import session_registry as reg, usage_capture as uc, rollup_honesty as rh
        pid = "proj-cr"
        self._mk(reg, pid, uc.STATE_MEASURED)
        self._mk(reg, pid, uc.STATE_MEASURED)
        self._mk(reg, pid, uc.STATE_UNMEASURED, uc.REASON_SIDECAR_PRUNED)
        self._mk(reg, pid, uc.STATE_CAPTURE_FAILED, uc.REASON_ZERO_USAGE)
        self._mk(reg, pid, uc.STATE_MEASURED, usage_gemini_segment=True)  # partial
        rate = rh.project_capture_rate(pid, window="lifetime")
        assert rate["total"] == 5
        assert rate["measured"] == 2
        assert rate["partial"] == 1
        assert rate["unmeasured"] == 1
        assert rate["capture_failed"] == 1
        # capture-failed counted SEPARATELY, never in unmeasured.
        assert rate["capture_failed"] + rate["unmeasured"] == 2
        assert uc.REASON_ZERO_USAGE in rate["reasons"]

    def test_running_session_excluded_from_denominator(self, datadir):
        import session_registry as reg, rollup_honesty as rh
        pid = "proj-run"
        reg.register_session(pid, "research", status=reg.STATUS_RUNNING)
        self._mk(reg, pid, "measured")
        rate = rh.project_capture_rate(pid, window="lifetime")
        assert rate["total"] == 1  # the still-running (unstamped) one is excluded

    def test_30d_window_applies_cutoff(self, datadir):
        """The 30d cutoff is exercised deterministically: sessions stamped at the
        real clock fall OUTSIDE a window whose ``now`` is 100 days in the future
        (cutoff = now-30d is later than every session's launch time)."""
        import time as _time
        import session_registry as reg, usage_capture as uc, rollup_honesty as rh
        pid = "proj-win"
        self._mk(reg, pid, uc.STATE_MEASURED)
        self._mk(reg, pid, uc.STATE_MEASURED)
        # lifetime counts both (no cutoff).
        assert rh.project_capture_rate(pid, window="lifetime")["total"] == 2
        # 30d relative to a far-future now → cutoff excludes the real-now sessions.
        future = _time.time() + 100 * 86400.0
        assert rh.project_capture_rate(pid, window="30d",
                                       now=future)["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 5) Rollup DEDUP — persisted docs + a RUN cost record for the SAME session
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def rollupenv(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    for mod in ("paths", "rnd_registry", "effort_history", "sessions",
                "usage_capture", "rollup_honesty"):
        importlib.reload(importlib.import_module(mod))
    import rnd_registry, effort_history, sessions
    return rnd_registry, effort_history, sessions, tmp_path


class TestRollupDedup:
    def test_docs_plus_run_cost_same_session_cost_counted_once(self, rollupenv):
        """A session whose docs were persisted (source=discovered) AND which also
        has a finalized RUN cost record → cost counted EXACTLY once, the
        discovered doc-effort contributes 0, the total is not inflated."""
        rnd, eh, sess, tmp_path = rollupenv
        proj_folder = tmp_path / "proj"
        proj_folder.mkdir(parents=True, exist_ok=True)
        pid = rnd.add_project("P", str(proj_folder))["id"]
        sid = "build::sess-XYZ"

        # 1) The finalized RUN cost record for the session (measured, 100 tok).
        eh.record_effort(
            str(proj_folder), pid, "build", "run-cost-%s" % sid,
            extra={"source": "run", "kind": "run-cost", "provenance": "run",
                   "session_id": sid, "usage_state": "measured",
                   "cost": {"total_tokens": 100, "input_tokens": 40,
                            "output_tokens": 60, "duration_ms": 1234,
                            "total_cost_usd": 0.0}})

        # 2) Persisted docs for the SAME session (source=discovered → 0).
        for rel in ("planning/v/NORTH-STAR.md", "planning/v/EXECUTION-LOG.md"):
            jid = eh.discovered_job_id("build", rel)
            eh.record_effort(str(proj_folder), pid, "build", jid, extra={
                "source": eh.SOURCE_DISCOVERED, "artifact_path": rel,
                "title": rel, "status": "imported", "session_id": sid})

        out = eh.project_effort_rollup(pid, "lifetime",
                                       folder_path=str(proj_folder))
        assert out["tokens"] == 100        # counted EXACTLY once, not inflated
        assert out["wall_clock_ms"] == 1234
        # The discovered doc-effort session contributes 0 (imported provenance).
        assert out["sessions"] == 1

    def test_capture_failed_run_cost_contributes_no_tokens(self, rollupenv):
        """A capture-failed RUN record (cost=None) never inflates measured tokens
        (never a measured-$0), while still being a real session on disk."""
        rnd, eh, sess, tmp_path = rollupenv
        proj_folder = tmp_path / "proj2"
        proj_folder.mkdir(parents=True, exist_ok=True)
        pid = rnd.add_project("P2", str(proj_folder))["id"]
        eh.record_effort(
            str(proj_folder), pid, "build", "run-cost-sess-CF",
            extra={"source": "run", "kind": "run-cost", "provenance": "run",
                   "session_id": "sess-CF", "usage_state": "capture-failed",
                   "usage_reason": "parse-error", "cost": None})
        out = eh.project_effort_rollup(pid, "lifetime",
                                       folder_path=str(proj_folder))
        assert out["tokens"] == 0        # never a fabricated measured total


# ══════════════════════════════════════════════════════════════════════════════
# 6) Dollars-optional rendering (no-own-pricing-table) + capture-rate stamp wired
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboardWiring:
    def test_fmt_rollup_line_subscription_when_no_dollars(self):
        import anchor_gui
        line0 = anchor_gui._fmt_rollup_line(
            {"tokens": 5000, "cost_usd": None, "wall_clock_ms": 60000,
             "sessions": 1, "billing_modes": ["subscription"],
             "cost_states": ["subscription_covered"],
             "priced_cost_count": 0, "unpriced_subscription_count": 1})
        # Explicit subscription state → named subscription, never measured $0.
        assert "(subscription)" in line0
        assert "$0.00" not in line0
        line1 = anchor_gui._fmt_rollup_line(
            {"tokens": 5000, "cost_usd": 1.25, "wall_clock_ms": 60000,
             "sessions": 1})
        assert "$1.25" in line1
        assert "(subscription)" not in line1

        unknown = anchor_gui._fmt_rollup_line(
            {"tokens": 5000, "cost_usd": 0.0, "wall_clock_ms": 60000,
             "sessions": 1})
        assert "cost unknown" in unknown
        assert "(subscription)" not in unknown

        measured_zero = anchor_gui._fmt_rollup_line(
            {"tokens": 5, "cost_usd": 0.0, "wall_clock_ms": 100,
             "sessions": 1, "billing_modes": ["metered"],
             "cost_states": ["engine_reported"], "priced_cost_count": 1})
        assert "$0.00" in measured_zero

        mixed = anchor_gui._fmt_rollup_line(
            {"tokens": 50, "cost_usd": 1.25, "wall_clock_ms": 100,
             "sessions": 2, "billing_modes": ["metered", "subscription"],
             "cost_states": ["engine_reported", "subscription_covered"],
             "priced_cost_count": 1, "unpriced_subscription_count": 1})
        assert "$1.25 measured + subscription" in mixed

        no_seat = anchor_gui._fmt_rollup_line(
            {"tokens": 0, "cost_usd": None, "wall_clock_ms": 1,
             "sessions": 1, "cost_states": ["no_seat_started"],
             "priced_cost_count": 0, "unpriced_subscription_count": 0})
        assert "no seat started" in no_seat
        assert "(subscription)" not in no_seat

    def test_fmt_rollup_line_empty_and_unmeasured_are_named(self):
        """Optimize-not-lying: never invent subscription/zero as fact."""
        import anchor_gui
        empty = anchor_gui._fmt_rollup_line(
            {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0, "sessions": 0})
        assert empty == "Σ no run sessions yet"
        assert "(subscription)" not in empty
        assert "0 tok" not in empty  # no bare zero-token claim on empty projects

        unmeasured = anchor_gui._fmt_rollup_line(
            {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0, "sessions": 2})
        assert "0 tok measured" in unmeasured
        assert "cost unknown" in unmeasured
        assert "(subscription)" not in unmeasured

        wall_only = anchor_gui._fmt_rollup_line(
            {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 90000, "sessions": 1})
        assert "0 tok measured" in wall_only
        assert "cost unknown" in wall_only
        assert "(subscription)" not in wall_only


    def test_fmt_project_usage_line_joins_capture_rate(self):
        """Empty effort rollup + capture-rate sessions must not say no sessions."""
        import anchor_gui
        empty_roll = {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0, "sessions": 0}
        # Pure empty
        assert anchor_gui._fmt_project_usage_line(empty_roll) == "Σ no run sessions yet"
        # Capture-rate proves sessions existed
        line = anchor_gui._fmt_project_usage_line(
            empty_roll,
            rate={"total": 1, "measured": 0, "unmeasured": 1,
                  "capture_failed": 0, "reasons": {"uncorrelated": 1}},
            live_count=0)
        assert "no run sessions yet" not in line
        assert "0 tok measured" in line
        assert "unmeasured" in line
        assert "uncorrelated" in line
        # Live session mid-flight
        live = anchor_gui._fmt_project_usage_line(
            empty_roll, rate={}, live_count=1)
        assert "live" in live
        assert "pending finalize" in live
        assert "no run sessions yet" not in live


    def test_header_rollup_stamps_capture_rate(self, tmp_path, monkeypatch):
        """The project-window header visibly stamps the capture-rate with
        capture-failed counted separately (done-when)."""
        monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
        for mod in ("paths", "rnd_registry", "session_registry",
                    "effort_history", "sessions", "usage_capture",
                    "rollup_honesty", "anchor_gui"):
            importlib.reload(importlib.import_module(mod))
        import paths, rnd_registry, session_registry as reg, usage_capture as uc
        import anchor_gui
        paths.ensure_data_dirs()
        folder = tmp_path / "proj"
        folder.mkdir()
        pid = rnd_registry.add_project("P", str(folder))["id"]
        for st, rsn in ((uc.STATE_MEASURED, ""),
                        (uc.STATE_MEASURED, ""),
                        (uc.STATE_CAPTURE_FAILED, uc.REASON_ZERO_USAGE)):
            r = reg.register_session(pid, "research", status=reg.STATUS_DONE)
            reg.update_session(r["session_id"], usage_state=st, usage_reason=rsn)
        html = anchor_gui.render_header_rollup_html(pid)
        assert "caprate" in html
        assert "measured 2/3 sessions" in html
        assert "1 capture-failed" in html


# ══════════════════════════════════════════════════════════════════════════════
# 7) Integration — finalize → partial (switch-engine) + Boneyard cost block
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data dir + temp ANCHOR_SIDECAR_DIR (fixtures) + stub PTY + fake runner
    + a temp git repo. git is a hard requirement in CI, so this does NOT skip on a
    missing git (the W1 lesson — a skip trips the §5 guard)."""
    data = tmp_path / "data"
    data.mkdir()
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sidecars))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SESSION_ID_FLAG", raising=False)
    for mod in ("paths", "usage_ledger", "job_runner", "pty_manager",
                "rnd_registry", "session_registry", "worktrees", "lanes",
                "effort_history", "sessions", "summarizer", "usage_capture",
                "rollup_honesty", "brownfield_scan", "effort_view",
                "deliverables", "boneyard", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import terminal_session, session_registry, effort_history, rnd_registry
    import usage_capture, rollup_honesty, boneyard, pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)

    yield {"ts": terminal_session, "reg": session_registry, "eh": effort_history,
           "uc": usage_capture, "rh": rollup_honesty, "bone": boneyard,
           "sidecars": sidecars, "pid": proj["id"], "repo": repo}
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def test_switch_to_gemini_makes_session_partial(env):
    """A research session started on claude (measured) then switched to gemini
    finalizes MEASURED for the Claude segment but classifies PARTIAL (gemini
    segment unmeasured) — never a complete-looking Claude-only number."""
    rec = env["ts"].start_session(env["pid"], "research", backend="claude")
    sid = rec["session_id"]
    euuid = rec.get("engine_session_uuid")
    assert euuid
    (env["sidecars"] / f"{euuid}.jsonl").write_text(
        _fx("canonical_3turn.jsonl"), encoding="utf-8")

    env["ts"].switch_engine(sid, "gemini")
    after = env["reg"].get_session(sid)
    assert after["backend"] == "gemini"
    assert after["usage_gemini_segment"] is True  # durable marker stamped

    env["ts"].kill(sid)
    final = env["reg"].get_session(sid)
    # The Claude segment was measured (real tokens), but the session is PARTIAL.
    assert final["usage_state"] == env["uc"].STATE_MEASURED
    c = env["rh"].classify_session_usage(final)
    assert c["state"] == env["rh"].STATE_PARTIAL
    assert c["reason"] == env["uc"].REASON_GEMINI_SEGMENT
    rate = env["rh"].project_capture_rate(env["pid"], window="lifetime")
    assert rate["partial"] == 1 and rate["measured"] == 0


def test_boneyard_entry_carries_finalized_cost_block(env):
    """A hard-KILLED measured session's Boneyard entry carries its FINALIZED cost
    block (tokens/time/$ + usage_state) — the honest cost of the discarded work."""
    rec = env["ts"].start_session(env["pid"], "build", backend="claude")
    sid = rec["session_id"]
    euuid = rec.get("engine_session_uuid")
    (env["sidecars"] / f"{euuid}.jsonl").write_text(
        _fx("canonical_3turn.jsonl"), encoding="utf-8")
    # Produce a doc so the kill records a Boneyard entry (has material).
    (env["repo"] / "OUT.md").write_text("result\n", encoding="utf-8")

    # Kill finalizes the usage (writes the run-cost record), THEN build the entry
    # from the post-kill record so it resolves the finalized cost block.
    env["ts"].kill(sid)
    entry = env["bone"].build_session_entry(
        str(env["repo"]), env["pid"], "build", sid,
        env["bone"].SOURCE_KILLED, record=env["reg"].get_session(sid),
        doc_rels=["OUT.md"])
    stored = env["bone"].record_entry(str(env["repo"]), env["pid"], entry)
    view = env["bone"].get_entry(str(env["repo"]), env["pid"],
                                 stored["entry_id"])
    assert view is not None
    assert view["usage_state"] == env["uc"].STATE_MEASURED
    cost = view["cost"] or {}
    exp = EXPECTED["canonical_3turn.jsonl"]["token_totals"]
    assert cost.get("total_tokens") == exp["total_all_classes"]
    # SAFE projection — no worktree/branch leak via the cost block.
    assert "worktree_path" not in view and "branch" not in view
