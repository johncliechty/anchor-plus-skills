"""W12 (rearch 2026-07, C3) — journal.py core: emit() choke point + Butler envelope.

Covers the frozen Wave-14 deliverables + acceptance:

  * the ONE emit() choke point — schema validation, monotonic per-project seq,
    atomic O(1) append, configurable fsync policy;
  * the Butler envelope answering the THREE W3 Butler user stories from journal
    events ALONE (no legacy-store read) —
    ``planning/rearch-2026-07/BUTLER-USER-STORIES.md``;
  * the schema-evolution rule — a v1→current round-trip + an unknown-field /
    higher-schema_ver reader-tolerance proof;
  * the distro.py-style scan forbidding a direct journal write outside emit();
  * the blessed ``dual_write`` wrapper — journal-first-then-legacy order, the
    ``journal`` off-switch (off ⇒ ONLY the legacy write, byte-identical), and the
    best-effort guarantee (a journal failure never blocks the legacy write);
  * the FIRST instrumented class: a session started → advanced → killed through
    the normal ``terminal_session`` paths journals each transition (monotonic
    seq, correct actor kind, correlation/causation ids linking the advance to
    its parent) while the registry store stays behaviorally equivalent to
    pre-journal behavior.

Pure unit tests need no git/PTY (emit against an explicit ``folder_path``). The
lifecycle tests are hermetic: ``ANCHOR_PTY_BACKEND=stub``, a temp git repo +
temp data dir + temp worktree base; they NEVER bind ``:8777`` or touch real data.
"""
import importlib
import json
import subprocess
from pathlib import Path

import pytest

import journal


# ── shared helpers ───────────────────────────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture(autouse=True)
def _clean_journal_env(monkeypatch):
    """Default every test to journal OFF + a clean seq cache."""
    monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
    monkeypatch.delenv("ANCHOR_JOURNAL_FSYNC", raising=False)
    journal.reset_seq_cache()
    yield
    journal.reset_seq_cache()


# ══════════════════════════════════════════════════════════════════════════════
# 1) emit() — the choke point: envelope, seq, validation
# ══════════════════════════════════════════════════════════════════════════════

class TestEmitChokePoint:
    def test_envelope_fields_present_and_typed(self, tmp_path):
        ev = journal.emit(
            "pidA", journal.EV_SESSION_STARTED,
            folder_path=str(tmp_path), correlation_id="chain1",
            actor=journal.actor(journal.ACTOR_KIND_USER_CLICK, "john"),
            causation_id=None, payload={"session_id": "s1", "lane": "research"})
        for k in journal.ENVELOPE_KEYS:
            assert k in ev, k
        assert ev["schema_ver"] == journal.CURRENT_SCHEMA_VER
        assert ev["seq"] == 1
        assert isinstance(ev["ts"], float)
        assert ev["type"] == journal.EV_SESSION_STARTED
        assert ev["actor"] == {"kind": "user-click", "id": "john"}
        assert ev["correlation_id"] == "chain1"
        assert ev["causation_id"] is None
        assert ev["project_id"] == "pidA"
        assert ev["payload"]["session_id"] == "s1"
        # actually appended, one JSON line
        p = journal.journal_path_for(str(tmp_path), "pidA")
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1
        assert json.loads(lines[0])["seq"] == 1

    def test_monotonic_seq_per_project(self, tmp_path):
        for i in range(1, 6):
            ev = journal.emit(
                "pidA", journal.EV_SESSION_STARTED, folder_path=str(tmp_path),
                correlation_id="c", actor=journal.actor("cli"),
                payload={"n": i})
            assert ev["seq"] == i
        # a DIFFERENT project has its OWN independent counter
        ev_b = journal.emit(
            "pidB", journal.EV_SESSION_STARTED, folder_path=str(tmp_path),
            correlation_id="c", actor=journal.actor("cli"), payload={})
        assert ev_b["seq"] == 1

    def test_seq_survives_cache_reset_via_disk(self, tmp_path):
        journal.emit("pidA", journal.EV_SESSION_STARTED,
                     folder_path=str(tmp_path), correlation_id="c",
                     actor=journal.actor("cli"), payload={})
        journal.reset_seq_cache()  # simulate a fresh process
        ev = journal.emit("pidA", journal.EV_SESSION_STARTED,
                          folder_path=str(tmp_path), correlation_id="c",
                          actor=journal.actor("cli"), payload={})
        assert ev["seq"] == 2  # re-derived from disk, not restarted at 1

    def test_schema_validation_rejects_bad_events(self, tmp_path):
        base = dict(folder_path=str(tmp_path), correlation_id="c",
                    actor=journal.actor("cli"), payload={})
        with pytest.raises(journal.JournalSchemaError):
            journal.emit("pidA", "", **base)                      # empty type
        with pytest.raises(journal.JournalSchemaError):
            journal.emit("", journal.EV_SESSION_STARTED, **base)  # empty pid
        bad = dict(base)
        bad["correlation_id"] = None
        with pytest.raises(journal.JournalSchemaError):
            journal.emit("pidA", journal.EV_SESSION_STARTED, **bad)
        with pytest.raises(journal.JournalSchemaError):
            journal.emit("pidA", journal.EV_SESSION_STARTED,
                         folder_path=str(tmp_path), correlation_id="c",
                         actor={"kind": "bogus", "id": ""}, payload={})
        # a rejected emit burns NO seq (gap-free) and writes NOTHING
        assert journal.read_events("pidA", folder_path=str(tmp_path)) == []

    def test_actor_validation(self):
        assert journal.actor("cli") == {"kind": "cli", "id": ""}
        assert journal.actor("user-click", "john")["id"] == "john"
        with pytest.raises(journal.JournalSchemaError):
            journal.actor("not-a-kind")

    def test_fsync_policy_configurable(self, tmp_path, monkeypatch):
        assert journal.fsync_enabled({}) is False
        assert journal.fsync_enabled({"ANCHOR_JOURNAL_FSYNC": "on"}) is True
        monkeypatch.setenv("ANCHOR_JOURNAL_FSYNC", "1")
        # fsync path executes without error and still appends the event
        ev = journal.emit("pidA", journal.EV_SESSION_STARTED,
                          folder_path=str(tmp_path), correlation_id="c",
                          actor=journal.actor("cli"), payload={})
        assert ev["seq"] == 1
        assert journal.read_events("pidA", folder_path=str(tmp_path))


# ══════════════════════════════════════════════════════════════════════════════
# 2) The three Butler user stories — answered from journal events ALONE
# ══════════════════════════════════════════════════════════════════════════════

class TestButlerUserStories:
    """A synthetic per-project journal feeding all three W3 stories, answered
    WITHOUT reading any legacy store (only the journal envelopes)."""

    def _seed_chain(self, folder, pid):
        """One effort chain R→P→B (causation = parent session id) + a synthetic
        healthcheck event, all in the SAME project journal."""
        f = str(folder)
        # research start — the ROOT user action
        journal.emit(pid, journal.EV_SESSION_STARTED, folder_path=f,
                     correlation_id="effortX",
                     actor=journal.actor("user-click", "john"),
                     causation_id=None, ts=1000.0,
                     payload={"session_id": "R", "lane": "research"})
        # planning start — auto-advanced from research
        journal.emit(pid, journal.EV_SESSION_STARTED, folder_path=f,
                     correlation_id="effortX",
                     actor=journal.actor("auto-advance"),
                     causation_id="R", ts=1001.0,
                     payload={"session_id": "P", "lane": "planning"})
        # build start — auto-advanced from planning
        journal.emit(pid, journal.EV_SESSION_STARTED, folder_path=f,
                     correlation_id="effortX",
                     actor=journal.actor("auto-advance"),
                     causation_id="P", ts=1002.0,
                     payload={"session_id": "B", "lane": "build"})
        # a synthetic healthcheck event (its OWN correlation)
        journal.emit(pid, journal.EV_SESSION_STARTED, folder_path=f,
                     correlation_id="hc-walk",
                     actor=journal.actor("healthcheck-synthetic"),
                     causation_id=None, ts=1003.0,
                     payload={"session_id": "HC", "lane": "research"})

    def test_story1_what_happened_while_away(self, tmp_path):
        """Filter to events with seq > last-seen, order by seq, label each by
        type + actor.kind/id — no legacy read."""
        self._seed_chain(tmp_path, "pidA")
        last_seen = 1  # John last looked after the research start
        evs = journal.read_events("pidA", folder_path=str(tmp_path),
                                  since_seq=last_seen)
        assert [e["seq"] for e in evs] == [2, 3, 4]  # ordered, monotonic
        labelled = [(e["type"], e["actor"]["kind"]) for e in evs]
        assert labelled == [
            ("session-started", "auto-advance"),
            ("session-started", "auto-advance"),
            ("session-started", "healthcheck-synthetic"),
        ]

    def test_story2_why_did_this_build_start(self, tmp_path):
        """From the build's event, follow causation_id to the root user-click;
        correlation_id groups the whole lineage; the auto-advance hop is visible."""
        self._seed_chain(tmp_path, "pidA")
        evs = journal.read_events("pidA", folder_path=str(tmp_path))
        by_session = {e["payload"]["session_id"]: e for e in evs}

        # correlation_id groups the effort — research+plan+build, NOT the hc walk
        effort = [e for e in evs if e["correlation_id"] == "effortX"]
        assert {e["payload"]["session_id"] for e in effort} == {"R", "P", "B"}

        # walk causation_id up from the build to the root
        chain = []
        cur = by_session["B"]
        while cur is not None:
            chain.append(cur["payload"]["session_id"])
            cause = cur["causation_id"]
            cur = by_session.get(cause) if cause else None
        assert chain == ["B", "P", "R"]

        root = by_session["R"]
        assert root["causation_id"] is None
        assert root["actor"]["kind"] == "user-click"  # "John did this"
        # the machine hops are honestly distinguishable from the user action
        assert by_session["P"]["actor"]["kind"] == "auto-advance"
        assert by_session["B"]["actor"]["kind"] == "auto-advance"

    def test_story3_real_activity_excludes_synthetic(self, tmp_path):
        """Partition by actor.kind, drop healthcheck-synthetic, bucket by ts-day
        + project, count by type — no legacy read."""
        self._seed_chain(tmp_path, "pidA")
        evs = journal.read_events("pidA", folder_path=str(tmp_path))
        real = [e for e in evs
                if e["actor"]["kind"] != "healthcheck-synthetic"]
        assert len(real) == 3 and all(
            e["actor"]["kind"] != "healthcheck-synthetic" for e in real)
        # count by type, bucketed by ts day (all on the same synthetic day here)
        import time as _t
        day = _t.strftime("%Y-%m-%d", _t.gmtime(1000.0))
        buckets = {}
        for e in real:
            key = (day, e["project_id"], e["type"])
            buckets[key] = buckets.get(key, 0) + 1
        assert buckets == {(day, "pidA", "session-started"): 3}
        # schema_ver spans old+new readers uniformly
        assert all(e["schema_ver"] == journal.CURRENT_SCHEMA_VER for e in evs)


# ══════════════════════════════════════════════════════════════════════════════
# 3) Schema-evolution rule — round-trip + unknown-field tolerance
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemaEvolution:
    def test_v1_to_current_roundtrip(self, tmp_path):
        ev = journal.emit(
            "pidA", journal.EV_SESSION_STARTED, folder_path=str(tmp_path),
            correlation_id="c", actor=journal.actor("cli"),
            payload={"session_id": "s1"})
        assert ev["schema_ver"] == 1 == journal.CURRENT_SCHEMA_VER
        read_back = journal.read_events("pidA", folder_path=str(tmp_path))
        assert len(read_back) == 1
        # write→read is lossless (JSON round-trip), and forward-migration of a
        # current-major event is the identity
        assert read_back[0] == ev
        assert journal.migrate_event(read_back[0]) == ev

    def test_reader_tolerates_unknown_fields_and_higher_ver(self, tmp_path):
        p = journal.journal_path_for(str(tmp_path), "pidA")
        p.parent.mkdir(parents=True, exist_ok=True)
        # a FUTURE event: higher schema_ver + a field this reader never heard of
        future = {
            "schema_ver": 999, "seq": 1, "ts": 1.0, "type": "session-started",
            "actor": {"kind": "cli", "id": ""}, "correlation_id": "c",
            "causation_id": None, "project_id": "pidA", "event_id": "pidA#1",
            "payload": {}, "a_field_from_the_future": {"nested": True},
        }
        p.write_text(json.dumps(future) + "\n", encoding="utf-8")
        evs = journal.read_events("pidA", folder_path=str(tmp_path))
        assert len(evs) == 1
        # unknown field preserved, higher schema_ver did NOT raise
        assert evs[0]["a_field_from_the_future"] == {"nested": True}
        assert evs[0]["schema_ver"] == 999

    def test_reader_skips_torn_tail_line(self, tmp_path):
        p = journal.journal_path_for(str(tmp_path), "pidA")
        p.parent.mkdir(parents=True, exist_ok=True)
        journal.emit("pidA", journal.EV_SESSION_STARTED,
                     folder_path=str(tmp_path), correlation_id="c",
                     actor=journal.actor("cli"), payload={})
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"seq": 2, "type": "sess')  # a torn crash-tail line
        evs = journal.read_events("pidA", folder_path=str(tmp_path))
        assert len(evs) == 1 and evs[0]["seq"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 4) dual_write — off-switch, journal-first order, best-effort
# ══════════════════════════════════════════════════════════════════════════════

class TestDualWrite:
    def test_offswitch_off_runs_only_legacy(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)  # default off
        ran = []
        out = journal.dual_write(
            "pidA", journal.EV_SESSION_STARTED,
            lambda: (ran.append(1) or "legacy-result"),
            correlation_id="c", folder_path=str(tmp_path),
            actor=journal.actor("cli"), payload={})
        assert out == "legacy-result" and ran == [1]
        # NO journal written when the pillar flag is off
        assert journal.read_events("pidA", folder_path=str(tmp_path)) == []

    def test_offswitch_on_writes_journal_and_legacy(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        ran = []
        journal.dual_write(
            "pidA", journal.EV_SESSION_STARTED,
            lambda: ran.append(1),
            correlation_id="c", folder_path=str(tmp_path),
            actor=journal.actor("user-click", "john"),
            payload={"session_id": "s1"})
        assert ran == [1]
        evs = journal.read_events("pidA", folder_path=str(tmp_path))
        assert len(evs) == 1 and evs[0]["type"] == "session-started"

    def test_journal_first_then_legacy_order(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        seen = {}

        def legacy():
            # by the time the LEGACY write runs, the journal event already exists
            seen["events_when_legacy_ran"] = len(
                journal.read_events("pidA", folder_path=str(tmp_path)))
            return "ok"

        journal.dual_write("pidA", journal.EV_SESSION_STARTED, legacy,
                           correlation_id="c", folder_path=str(tmp_path),
                           actor=journal.actor("cli"), payload={})
        assert seen["events_when_legacy_ran"] == 1  # journal FIRST

    def test_best_effort_journal_failure_never_blocks_legacy(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        ran = []
        # correlation_id=None makes emit() raise — dual_write must swallow it and
        # STILL perform the legacy write ("alongside, never instead of").
        out = journal.dual_write(
            "pidA", journal.EV_SESSION_STARTED,
            lambda: (ran.append(1) or "legacy-ok"),
            correlation_id=None, folder_path=str(tmp_path),
            actor=journal.actor("cli"), payload={})
        assert out == "legacy-ok" and ran == [1]
        assert journal.read_events("pidA", folder_path=str(tmp_path)) == []

    def test_legacy_bytes_byte_equivalent_off_vs_on(self, tmp_path, monkeypatch):
        """The legacy-store write is BYTE-IDENTICAL whether the journal is on or
        off — journaling only ADDS journal.jsonl, never perturbs the legacy bytes."""
        content = b'{"status": "done", "n": 42}\n'
        off_file = tmp_path / "off" / "store.json"
        on_file = tmp_path / "on" / "store.json"
        off_file.parent.mkdir(parents=True)
        on_file.parent.mkdir(parents=True)

        monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
        journal.dual_write(
            "pidA", journal.EV_SESSION_KILLED,
            lambda: off_file.write_bytes(content),
            correlation_id="c", folder_path=str(tmp_path / "off"),
            actor=journal.actor("cli"), payload={})

        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        journal.dual_write(
            "pidA", journal.EV_SESSION_KILLED,
            lambda: on_file.write_bytes(content),
            correlation_id="c", folder_path=str(tmp_path / "on"),
            actor=journal.actor("cli"), payload={})

        assert off_file.read_bytes() == on_file.read_bytes()
        # journal only appeared on the ON side
        assert not journal.journal_path_for(
            str(tmp_path / "off"), "pidA").exists()
        assert journal.journal_path_for(str(tmp_path / "on"), "pidA").exists()


# ══════════════════════════════════════════════════════════════════════════════
# 5) distro.py-style scan — emit() is the ONLY journal write path
# ══════════════════════════════════════════════════════════════════════════════

class TestForbiddenJournalWriteScan:
    def test_repo_is_clean(self):
        hits = journal.scan_direct_journal_writes()
        assert hits == [], (
            "a module other than journal.py writes a journal path directly: "
            + repr(hits))

    def test_predicate_catches_a_violation(self):
        bad = [
            'with open(journal_path, "w") as f:',
            'p.write_text(data)  # journal.jsonl',
            'json.dump(event, open("x/journal.jsonl", "a"))',
        ]
        for line in bad:
            assert journal._line_is_forbidden_journal_write(line), line
        # a plain read / a non-journal write is NOT flagged
        assert not journal._line_is_forbidden_journal_write(
            'evs = read_events(pid)  # journal.jsonl (a read)')
        assert not journal._line_is_forbidden_journal_write(
            'open("sessions.json", "w")')

    def test_scan_flags_a_planted_bad_file(self, tmp_path):
        (tmp_path / "rogue.py").write_text(
            'def bad():\n'
            '    with open("x/journal.jsonl", "w") as f:\n'
            '        f.write("{}")\n',
            encoding="utf-8")
        hits = journal.scan_direct_journal_writes(repo_root=tmp_path)
        assert any(h[0] == "rogue.py" and h[1] == "direct-journal-write"
                   for h in hits)


# ══════════════════════════════════════════════════════════════════════════════
# 6) FIRST instrumented class — session lifecycle through terminal_session
# ══════════════════════════════════════════════════════════════════════════════

STUB = (Path(__file__).resolve().parent / "stub_summarizer.py")
_STUB_ARG = STUB.as_posix() if STUB.exists() else ""

pytestmark_git = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def tsenv(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    if _STUB_ARG:
        monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {_STUB_ARG}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

    for mod in ("paths", "pillar_flags", "job_runner", "pty_manager",
                "rnd_registry", "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "journal",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import terminal_session
    import session_registry
    import rnd_registry
    import pty_manager
    import journal as _journal
    _journal.reset_seq_cache()

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "ts": terminal_session, "reg": session_registry, "rnd": rnd_registry,
        "pty": pty_manager, "journal": _journal, "repo": repo,
        "pid": proj["id"], "data": data,
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytestmark_git
class TestSessionLifecycleInstrumented:
    def test_start_advance_kill_journaled_and_linked(self, tsenv, monkeypatch):
        """Given a research session started, a linked planning session advanced
        from it, and that planning session killed — the per-project journal holds
        a schema-versioned event for each transition with monotonic seq, correct
        actor kind, and correlation/causation ids linking the advance to its
        parent."""
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        ts, reg, journal_mod, pid = (
            tsenv["ts"], tsenv["reg"], tsenv["journal"], tsenv["pid"])

        research = ts.start_session(
            pid, "research", backend="claude",
            actor=journal_mod.actor("user-click", "john"))
        r_sid = research["session_id"]
        r_chain = research["chain_id"]

        planning = ts.start_session(
            pid, "planning", backend="claude", parent_session_id=r_sid,
            actor=journal_mod.auto_advance_actor())
        p_sid = planning["session_id"]

        ts.kill(p_sid, project_id=pid,
                actor=journal_mod.auto_advance_actor())

        evs = journal_mod.read_events(pid)
        types = [e["type"] for e in evs]
        assert types == ["session-started", "session-started", "session-killed"]

        # monotonic seq
        assert [e["seq"] for e in evs] == [1, 2, 3]

        by_sid = {}
        for e in evs:
            by_sid.setdefault(e["payload"].get("session_id"), []).append(e)

        r_start = by_sid[r_sid][0]
        p_start = by_sid[p_sid][0]
        p_kill = [e for e in by_sid[p_sid] if e["type"] == "session-killed"][0]

        # the research start is the ROOT user action
        assert r_start["actor"]["kind"] == "user-click"
        assert r_start["causation_id"] is None
        assert r_start["correlation_id"] == r_chain

        # the planning session shares the effort chain and its start CAUSATION
        # links to its parent (the research session) — the advance→parent link
        assert p_start["correlation_id"] == r_chain
        assert p_start["causation_id"] == r_sid
        assert p_start["actor"]["kind"] == "auto-advance"

        # the kill is journaled too, in the same chain
        assert p_kill["correlation_id"] == r_chain
        assert p_kill["actor"]["kind"] == "auto-advance"

        # registry stayed correct through it all (behaviorally equivalent):
        # research still RUNNING, planning terminal DONE
        assert reg.get_session(r_sid)["status"] == reg.STATUS_RUNNING
        assert reg.get_session(p_sid)["status"] == reg.STATUS_DONE

    def test_advance_stage_emits_session_advanced(self, tsenv, monkeypatch):
        """A single-session v12 effort advanced in-session journals a
        ``session-advanced`` event (from→to stage in the payload)."""
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")
        ts, journal_mod, pid = tsenv["ts"], tsenv["journal"], tsenv["pid"]

        sess = ts.start_session(pid, "research", backend="claude",
                                effort_managed=True,
                                actor=journal_mod.actor("user-click", "john"))
        sid = sess["session_id"]
        # write a doc into the worktree so the stage persist is real
        wt = Path(sess["worktree_path"])
        (wt / "research").mkdir(parents=True, exist_ok=True)
        (wt / "research" / "findings.md").write_text(
            "# Findings\ndurable resumable work\n", encoding="utf-8")

        out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid,
                               actor=journal_mod.actor("user-click", "john"))
        assert out.get("ok") and out.get("advanced")

        evs = journal_mod.read_events(pid)
        adv = [e for e in evs if e["type"] == "session-advanced"]
        assert len(adv) == 1
        assert adv[0]["payload"]["from_stage"] == "research"
        assert adv[0]["payload"]["to_stage"] == "plan"
        assert adv[0]["correlation_id"] == sess["chain_id"]

    def test_offswitch_off_writes_no_journal_through_terminal_session(
            self, tsenv, monkeypatch):
        """With the journal flag OFF (default), driving the same lifecycle writes
        NO journal — the legacy registry behavior is untouched."""
        monkeypatch.delenv("ANCHOR_JOURNAL", raising=False)
        ts, reg, journal_mod, pid = (
            tsenv["ts"], tsenv["reg"], tsenv["journal"], tsenv["pid"])

        research = ts.start_session(pid, "research", backend="claude")
        ts.kill(research["session_id"], project_id=pid)

        assert journal_mod.read_events(pid) == []
        assert reg.get_session(research["session_id"])["status"] == \
            reg.STATUS_DONE
