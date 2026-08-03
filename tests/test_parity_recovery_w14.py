"""W14 (rearch 2026-07, C3) — parity gate + recovery & replay tools.

Covers the frozen Wave-16 deliverables + acceptance:

  * the QUIESCENT classifying parity gate (``parity.classify_parity``): derives a
    session view + an effort view from a WRITE_LOCK-bracketed snapshot of the
    journal AND the legacy stores, and classifies every divergence
    (journal-ahead=OK/crash-residue · legacy-ahead=BUG · conflict=BUG), tolerating
    a bounded tail window;
  * ``tools.rebuild_index``: re-derives a deleted grass ``index.json`` from the
    journal and re-materializes ``sessions.json`` rows from the journal, proven by
    deleting the store mid-test and rebuilding to parity — idempotently;
  * ``tools.replay_journal``: the dry-run-first reconcile report + idempotent
    convergence of the legacy stores to the journal for the journal-ahead class,
    never mutating a legacy-ahead/conflict row unasked.

Journaling is OFF by default; a test turns the ``journal`` flag on. The session
tests need a temp ``ANCHOR_DATA_DIR`` (the global ``sessions.json`` lives there);
the effort tests are folder-explicit. Nothing binds ``:8777`` or touches real
data.
"""
import json
from pathlib import Path

import pytest

import journal
import parity
from tools import rebuild_index, replay_journal

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    for v in ("ANCHOR_JOURNAL", "ANCHOR_JOURNAL_FSYNC", "ANCHOR_WRITE_TRIPWIRE"):
        monkeypatch.delenv(v, raising=False)
    # Hermetic data dir so the session-store read in classify_parity never
    # touches the repo's real .anchor/sessions.json (the ``datadir`` fixture
    # overrides this with its own temp when a test needs a shared root).
    hc = tmp_path / "_hcdata"
    hc.mkdir(exist_ok=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(hc))
    journal.reset_seq_cache()
    yield
    journal.reset_seq_cache()


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """Temp ANCHOR_DATA_DIR so the global sessions.json is hermetic."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    import paths
    paths.ensure_data_dirs()
    yield tmp_path


def _start_session(pid, folder, sid, lane="research"):
    """Drive a journaled session start exactly as terminal_session does."""
    import session_registry as reg
    return journal.dual_write(
        pid, journal.EV_SESSION_STARTED,
        lambda: reg.register_session(project_id=pid, lane=lane, session_id=sid,
                                     status=reg.STATUS_RUNNING),
        correlation_id=sid, folder_path=str(folder),
        payload={"session_id": sid, "lane": lane, "backend": reg.BACKEND_CLAUDE})


def _kill_session(pid, folder, sid, lane="research"):
    import session_registry as reg
    return journal.dual_write(
        pid, journal.EV_SESSION_KILLED,
        lambda: reg.update_session(sid, status=reg.STATUS_DONE),
        correlation_id=sid, folder_path=str(folder),
        payload={"session_id": sid, "lane": lane})


# ══════════════════════════════════════════════════════════════════════════════
# 1) The gate reports ZERO divergence for a clean, quiescent project
# ══════════════════════════════════════════════════════════════════════════════

class TestQuiescentParity:
    def test_effort_view_clean(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidClean"
        eh.add_idea(str(f), pid, "idea 1")
        eh.add_idea(str(f), pid, "idea 2")

        rep = parity.classify_parity(pid, folder_path=str(f))
        assert rep.is_clean(), rep.summary()
        assert rep.divergences == []

    def test_session_view_clean(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        f, pid = datadir, "pidSess"
        _start_session(pid, f, "sess-1")
        _kill_session(pid, f, "sess-1")

        rep = parity.classify_parity(pid, folder_path=str(f))
        assert rep.is_clean(), rep.summary()
        # the journal-derived session view matches the store view exactly.
        events = journal.read_events(pid, folder_path=str(f))
        jview = parity.derive_session_view_from_journal(events)
        assert jview["sess-1"]["status"] == "done"

    def test_mixed_clean(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = datadir, "pidMixed"
        eh.add_idea(str(f), pid, "grass a")
        _start_session(pid, f, "s-1")
        eh.add_idea(str(f), pid, "grass b")
        rep = parity.classify_parity(pid, folder_path=str(f))
        assert rep.is_clean(), rep.summary()


# ══════════════════════════════════════════════════════════════════════════════
# 2) AC1 — delete index.json mid-suite, rebuild from the journal → parity
# ══════════════════════════════════════════════════════════════════════════════

class TestRebuildFromJournal:
    def test_deleted_grass_index_rebuilds_to_parity(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidRebuild"
        for i in range(3):
            eh.add_idea(str(f), pid, f"idea {i}")
        before = eh._load_index(str(f), pid, "grass")
        assert len(before) == 3

        # delete the index (a torn/lost derived layer).
        idx = eh._index_path(str(f), pid, "grass")
        idx.unlink()
        assert eh._load_index(str(f), pid, "grass") == []

        # the gate now CLASSIFIES the loss (journal-ahead, strict tail).
        rep_lost = parity.classify_parity(pid, folder_path=str(f))
        assert not rep_lost.is_clean()
        assert all(d["classification"] == parity.CLASS_JOURNAL_AHEAD
                   for d in rep_lost.effective_divergences())

        # rebuild from the journal restores the index (order preserved).
        out = rebuild_index.rebuild_grass_index_from_journal(
            str(f), pid, dry_run=False)
        assert out["wrote"] and out["rebuilt"] == before

        rep_ok = parity.classify_parity(pid, folder_path=str(f))
        assert rep_ok.is_clean(), rep_ok.summary()
        assert rep_ok.divergences == []

    def test_rebuild_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidDry"
        eh.add_idea(str(f), pid, "only idea")
        idx = eh._index_path(str(f), pid, "grass")
        idx.unlink()
        out = rebuild_index.rebuild_grass_index_from_journal(
            str(f), pid, dry_run=True)
        assert out["changed"] and not out["wrote"]
        assert not idx.exists()  # dry-run mutated nothing

    def test_rebuild_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidIdem"
        eh.add_idea(str(f), pid, "a")
        eh.add_idea(str(f), pid, "b")
        # already-consistent store → rebuild is a no-op.
        out = rebuild_index.rebuild_grass_index_from_journal(
            str(f), pid, dry_run=False)
        assert not out["changed"] and not out["wrote"]

    def test_session_rows_rebuild_from_journal(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import session_registry as reg
        f, pid = datadir, "pidSessRebuild"
        _start_session(pid, f, "sr-1")
        _kill_session(pid, f, "sr-1")

        # wipe the session row (a lost registry row).
        store = reg.load_sessions()
        del store["sr-1"]
        reg._save_sessions(store)
        assert reg.get_session("sr-1") is None
        rep_lost = parity.classify_parity(pid, folder_path=str(f))
        assert not rep_lost.is_clean()

        out = rebuild_index.rebuild_session_rows_from_journal(
            pid, folder_path=str(f), dry_run=False)
        assert "sr-1" in out["added"] and out["wrote"]
        row = reg.get_session("sr-1")
        assert row and row["status"] == "done" and row["lane"] == "research"
        rep_ok = parity.classify_parity(pid, folder_path=str(f))
        assert rep_ok.is_clean(), rep_ok.summary()


# ══════════════════════════════════════════════════════════════════════════════
# 3) AC2 — a seeded legacy-ahead / conflict classifies BUG; tools stay dry-run
# ══════════════════════════════════════════════════════════════════════════════

class TestLegacyAheadAndConflict:
    def test_legacy_ahead_effort_is_bug(self, tmp_path, monkeypatch):
        # a grass index entry written with the journal OFF → legacy-ahead.
        f, pid = tmp_path, "pidLA"
        monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
        import effort_history as eh
        eh.add_idea(str(f), pid, "unjournaled idea")  # NO journal event
        assert journal.read_events(pid, folder_path=str(f)) == []

        rep = parity.classify_parity(pid, folder_path=str(f))
        assert not rep.is_clean()
        bugs = rep.bugs
        assert bugs and all(b["severity"] == parity.SEVERITY_BUG for b in bugs)
        assert any(b["classification"] == parity.CLASS_LEGACY_AHEAD
                   and b["entity"] == parity.ENTITY_EFFORT for b in bugs)

    def test_legacy_ahead_session_is_bug(self, datadir, monkeypatch):
        # a session registered without journaling → legacy-ahead session.
        import session_registry as reg
        f, pid = datadir, "pidLAsess"
        reg.register_session(project_id=pid, lane="research",
                             session_id="ghost", status=reg.STATUS_RUNNING)
        rep = parity.classify_parity(pid, folder_path=str(f))
        assert any(b["classification"] == parity.CLASS_LEGACY_AHEAD
                   and b["entity"] == parity.ENTITY_SESSION for b in rep.bugs)

    def test_conflict_is_bug(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import session_registry as reg
        f, pid = datadir, "pidConf"
        _start_session(pid, f, "c-1")  # journal + store: running
        # mutate the store to DONE WITHOUT a journal killed event → conflict.
        reg.update_session("c-1", status=reg.STATUS_DONE)
        rep = parity.classify_parity(pid, folder_path=str(f))
        conflicts = [d for d in rep.divergences
                     if d["classification"] == parity.CLASS_CONFLICT]
        assert conflicts and conflicts[0]["severity"] == parity.SEVERITY_BUG

    def test_reconcile_report_dry_run_mutates_nothing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
        import effort_history as eh
        f, pid = tmp_path, "pidRecon"
        eh.add_idea(str(f), pid, "unjournaled")  # legacy-ahead
        idx = eh._index_path(str(f), pid, "grass")
        before = idx.read_bytes()

        out = replay_journal.reconcile_report(str(f), pid)
        assert not out["clean"] and out["bugs"] >= 1
        assert out["investigate"] and out["investigate"][0]["action"] == \
            replay_journal.ACTION_INVESTIGATE
        # the read-only report mutated nothing.
        assert idx.read_bytes() == before


# ══════════════════════════════════════════════════════════════════════════════
# 4) The bounded tail window
# ══════════════════════════════════════════════════════════════════════════════

class TestTailWindow:
    def test_tail_window_tolerates_tip_but_not_beyond(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidTail"
        eh.add_idea(str(f), pid, "a")  # seq 1
        eh.add_idea(str(f), pid, "b")  # seq 2
        # both become journal-ahead when the index is dropped.
        eh._index_path(str(f), pid, "grass").unlink()

        # strict: nothing tolerated → 2 effective divergences.
        strict = parity.classify_parity(pid, folder_path=str(f), tail_window=0)
        assert len(strict.effective_divergences()) == 2 and not strict.is_clean()

        # window covering the whole log → all journal-ahead tolerated → clean.
        wide = parity.classify_parity(pid, folder_path=str(f), tail_window=5)
        assert wide.is_clean() and wide.effective_divergences() == []

        # window of 1 → only the tip seq tolerated → exactly 1 remains.
        one = parity.classify_parity(pid, folder_path=str(f), tail_window=1)
        assert len(one.effective_divergences()) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 5) Replay — idempotent convergence, reconcile-report split
# ══════════════════════════════════════════════════════════════════════════════

class TestReplay:
    def test_replay_converges_journal_ahead_idempotently(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = tmp_path, "pidReplay"
        eh.add_idea(str(f), pid, "x")
        eh.add_idea(str(f), pid, "y")
        expected = eh._load_index(str(f), pid, "grass")
        eh._index_path(str(f), pid, "grass").unlink()

        # dry-run replay reports the replayable divergence but writes nothing.
        dry = replay_journal.replay(str(f), pid, dry_run=True)
        assert dry["report"]["replayable"] and not dry["applied"]
        assert eh._load_index(str(f), pid, "grass") == []

        # apply converges the store to the journal.
        applied = replay_journal.replay(str(f), pid, dry_run=False)
        assert applied["applied"]
        assert eh._load_index(str(f), pid, "grass") == expected
        assert parity.classify_parity(pid, folder_path=str(f)).is_clean()

        # a second apply is a no-op (idempotent — gate already clean).
        again = replay_journal.replay(str(f), pid, dry_run=False)
        assert not again["applied"] and again["report"]["clean"]

    def test_run_rebuild_dry_run_report_shape(self, datadir, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        import effort_history as eh
        f, pid = datadir, "pidRunRebuild"
        eh.add_idea(str(f), pid, "z")
        rep = rebuild_index.run_rebuild(str(f), pid, dry_run=True)
        assert rep["dry_run"] is True
        assert rep["grass"]["lane"] == "grass"
        assert set(rep["pointer_lanes"]) == {"research", "planning",
                                             "build", "deliverables"}
        assert "added" in rep["sessions"] and "converged" in rep["sessions"]
