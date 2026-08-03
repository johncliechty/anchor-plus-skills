"""W2 — Durability Substrate: atomic finalize writes + fail-closed sidecar seam.

Cites the NORTH-STAR-AMENDMENT (tripwire severity + the W2 durability-substrate
plan): atomic temp→rename writes for the finalize set, a ``cost_final``
compare-and-set latch keyed by session_id, and a fail-closed engine-sidecar-root
resolver in ``paths.py``. Serves criteria (1),(6).

These are pure-Python, hermetic tests — no live :8777 service, no real
``~/.claude`` store, no model calls. They land BEFORE any finalize/capture code
(W4), which is the whole point of a durability substrate.
"""
import json
import threading
from pathlib import Path

import pytest

import paths
import session_registry as sreg
import effort_history as eh
import usage_ledger as ul
from tools import write_tripwire as wt


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    """A hermetic data dir (session registry + ledger live under it)."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(d))
    return d


# ══════════════════════════════════════════════════════════════════════════════
# 1) cost_final compare-and-set — the finalize-once latch
# ══════════════════════════════════════════════════════════════════════════════

class TestCostFinalCompareAndSet:
    def test_single_thread_wins_once_then_false(self, datadir):
        rec = sreg.register_session("pid", "build",
                                    status=sreg.STATUS_RUNNING)
        sid = rec["session_id"]
        # a fresh record has never been finalized
        assert sreg.get_session(sid)["cost_final"] is False
        assert sreg.get_session(sid)["cost_final_at"] is None
        # first finalize WINS; every later one is a no-op
        assert sreg.finalize_cost_once(sid) is True
        assert sreg.finalize_cost_once(sid) is False
        assert sreg.finalize_cost_once(sid) is False
        after = sreg.get_session(sid)
        assert after["cost_final"] is True
        assert isinstance(after["cost_final_at"], float)

    def test_unknown_session_never_wins(self, datadir):
        assert sreg.finalize_cost_once("no-such-session") is False
        assert sreg.finalize_cost_once("") is False

    def test_latch_survives_update_session(self, datadir):
        """A concurrent field update (status flip) must not clear the latch."""
        rec = sreg.register_session("pid", "build",
                                    status=sreg.STATUS_RUNNING)
        sid = rec["session_id"]
        assert sreg.finalize_cost_once(sid) is True
        sreg.update_session(sid, status=sreg.STATUS_DONE, label="parked")
        assert sreg.get_session(sid)["cost_final"] is True


def _simulate_finalize(folder, pid, sid, label, winners, engine_uuid):
    """One end path (kill / close / reconcile) racing to finalize the session.

    The CAS gates the single RUN cost record; the status flip + usage append fire
    on every path so the sessions.json + ledger atomic writers are stressed under
    contention.
    """
    won = sreg.finalize_cost_once(sid)
    sreg.update_session(sid, status=sreg.STATUS_DONE, label=f"end:{label}")
    ul.append_entries(engine_uuid, [
        {"key": ul.entry_key(engine_uuid, message_uuid="msg-1"),
         "input_tokens": 10, "output_tokens": 5},
    ])
    if won:
        winners.append(label)
        eh.record_effort(
            folder, pid, "build", f"run-cost-{sid}",
            extra={"source": "run", "kind": "run-cost", "session_id": sid,
                   "cost": {"input_tokens": 10, "output_tokens": 5,
                            "total_tokens": 15, "duration_ms": 150000,
                            "total_cost_usd": 0.0}})


class TestConcurrentFinalizeRace:
    def test_50x_concurrent_kill_close_reconcile_one_cost_record(
            self, datadir, tmp_path):
        """G/W/T: fire kill/close/reconcile concurrently 50x against one session
        → exactly one finalized cost record (cost_final CAS) and every touched
        index still parses."""
        folder = str(tmp_path / "proj")
        Path(folder).mkdir()
        pid = "proj-w2"
        rec = sreg.register_session(pid, "build",
                                    status=sreg.STATUS_RUNNING, label="w2")
        sid = rec["session_id"]
        engine_uuid = f"uuid-{sid}"

        winners = []
        labels = ("kill", "close", "reconcile")
        threads = [
            threading.Thread(
                target=_simulate_finalize,
                args=(folder, pid, sid, labels[i % 3], winners, engine_uuid))
            for i in range(50)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # exactly ONE thread won the compare-and-set
        assert len(winners) == 1, winners
        # → exactly one finalized RUN cost record
        efforts = eh.list_efforts(folder, pid, "build")
        cost_recs = [e for e in efforts if e.get("kind") == "run-cost"]
        assert len(cost_recs) == 1, cost_recs
        # the latch is set on the record
        assert sreg.get_session(sid)["cost_final"] is True

        # every touched index still PARSES cleanly (atomic writes never leave a
        # torn file — the raw JSON decodes and the shapes are intact)
        reg = sreg.load_sessions()
        assert isinstance(reg, dict) and len(reg) == 1
        assert eh._load_index(folder, pid, "build") == [f"run-cost-{sid}"]
        led = ul.load_ledger(engine_uuid)
        # 50 concurrent appends of the SAME key → one deduped ledger entry
        assert len(led["entries"]) == 1

        # the on-disk files decode without error (no partial write survived)
        json.loads(sreg.sessions_path().read_text(encoding="utf-8"))
        json.loads(eh._index_path(folder, pid, "build").read_text(
            encoding="utf-8"))
        json.loads(ul.ledger_path(engine_uuid).read_text(encoding="utf-8"))
        # no orphaned tmp twins left behind
        assert not sreg.sessions_path().with_name(
            sreg.sessions_path().name + ".tmp").exists()


# ══════════════════════════════════════════════════════════════════════════════
# 2) The grep-level atomicity assertion (done-when)
# ══════════════════════════════════════════════════════════════════════════════

def _is_finalize_store(store: str) -> bool:
    return (store.endswith("sessions.json")
            or store.endswith("index.json")
            or "/usage_ledger/" in store
            or "/efforts/" in store)


class TestFinalizePathWritesAreAtomic:
    def test_no_finalize_write_is_non_atomic(self, datadir, tmp_path):
        """The done-when grep-level assertion, proven mechanically via the
        write-site tripwire: every finalize-path store write goes tmp→rename, so
        each finalize store shows a 'replace' op. A store written with a bare
        ``open(target, 'w')`` would show 'write' with NO 'replace'."""
        folder = str(tmp_path / "proj")
        Path(folder).mkdir()
        pid = "proj-w2-atomic"

        with wt.active(mode=wt.MODE_INVENTORY):
            rec = sreg.register_session(pid, "build",
                                        status=sreg.STATUS_RUNNING)
            sid = rec["session_id"]
            assert sreg.finalize_cost_once(sid) is True
            eh.record_effort(
                folder, pid, "build", f"run-cost-{sid}",
                extra={"source": "run", "kind": "run-cost", "session_id": sid,
                       "cost": {"input_tokens": 1, "output_tokens": 1}})
            ul.append_entries(f"uuid-{sid}", [
                {"key": ul.entry_key(f"uuid-{sid}", message_uuid="m1"),
                 "input_tokens": 1}])
            inv = wt.inventory()

        ops_by_store: dict[str, set] = {}
        for r in inv:
            ops_by_store.setdefault(r["store"], set()).add(r["op"])

        finalize_stores = [s for s in ops_by_store if _is_finalize_store(s)]
        # the three named finalize stores are all covered
        assert any(s.endswith("sessions.json") for s in finalize_stores), \
            ops_by_store
        assert any(s.endswith("index.json") for s in finalize_stores), \
            ops_by_store
        assert any("/usage_ledger/" in s for s in finalize_stores), \
            ops_by_store

        # EVERY finalize store that was written was written ATOMICALLY (the write
        # to its .tmp twin is folded onto the target, and the tmp→target rename
        # shows as a 'replace'). A non-atomic write would be 'write' with no
        # 'replace' — that is the failure the grep-level assertion forbids.
        for store in finalize_stores:
            ops = ops_by_store[store]
            assert "replace" in ops, (
                f"finalize store {store!r} was written NON-ATOMICALLY "
                f"(a write with no tmp→rename replace): ops={ops}")


# ══════════════════════════════════════════════════════════════════════════════
# 3) Idempotent, atomic usage ledger (substrate)
# ══════════════════════════════════════════════════════════════════════════════

class TestUsageLedger:
    def test_append_is_idempotent_by_key(self, datadir):
        uuid = "sess-uuid-A"
        e1 = {"key": ul.entry_key(uuid, message_uuid="m1"), "output_tokens": 3}
        e2 = {"key": ul.entry_key(uuid, message_uuid="m2"), "output_tokens": 7}
        assert ul.append_entries(uuid, [e1, e2]) == 2
        # re-ingesting the same keys adds nothing (first-write-wins)
        assert ul.append_entries(uuid, [e1, e2]) == 0
        # a genuinely new key is added
        e3 = {"key": ul.entry_key(uuid, message_uuid="m3"), "output_tokens": 1}
        assert ul.append_entries(uuid, [e3]) == 1
        assert len(ul.ledger_entries(uuid)) == 3

    def test_same_message_id_across_lines_collapses(self, datadir):
        """The W1 load-bearing finding: multiple JSONL lines share a message.id
        and repeat the usage block; keying on message.id collapses them to one."""
        uuid = "sess-uuid-B"
        k = ul.entry_key(uuid, message_uuid="msg_01B")
        line_a = {"key": k, "output_tokens": 100}
        line_b = {"key": k, "output_tokens": 100}  # duplicate content block
        assert ul.append_entries(uuid, [line_a, line_b]) == 1
        assert len(ul.ledger_entries(uuid)) == 1

    def test_entries_without_key_are_skipped(self, datadir):
        uuid = "sess-uuid-C"
        assert ul.append_entries(uuid, [{"no": "key"}, {"key": ""}]) == 0
        assert ul.ledger_entries(uuid) == []

    def test_corrupt_ledger_reads_as_empty(self, datadir):
        uuid = "sess-uuid-D"
        p = ul.ledger_path(uuid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ this is not json", encoding="utf-8")
        assert ul.load_ledger(uuid)["entries"] == {}
        # a subsequent append still works (overwrites the torn file atomically)
        assert ul.append_entries(
            uuid, [{"key": "line:x", "output_tokens": 1}]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 4) Fail-closed engine-sidecar-root resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestFailClosedSidecarResolver:
    def test_raises_in_test_mode_when_unset(self, monkeypatch):
        """pytest sets PYTEST_CURRENT_TEST → hermetic; with ANCHOR_SIDECAR_DIR
        unset the resolver refuses rather than resolving ~/.claude."""
        monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
        with pytest.raises(paths.SidecarRootUnavailable):
            paths.sidecar_root()

    def test_raises_under_data_dir_redirect(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("ANCHOR_HEALTHCHECK", raising=False)
        monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
        with pytest.raises(paths.SidecarRootUnavailable):
            paths.sidecar_root()

    def test_raises_under_healthcheck_marker(self, monkeypatch):
        monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("ANCHOR_DATA_DIR", raising=False)
        monkeypatch.setenv("ANCHOR_HEALTHCHECK", "1")
        with pytest.raises(paths.SidecarRootUnavailable):
            paths.sidecar_root()

    def test_explicit_sidecar_dir_is_honored(self, monkeypatch, tmp_path):
        sc = tmp_path / "sidecars"
        sc.mkdir()
        monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sc))
        assert paths.sidecar_root() == sc.resolve()

    def test_healthcheck_walk_never_opens_real_home(self, monkeypatch):
        """STUB-GATE spy: in healthcheck mode with ANCHOR_SIDECAR_DIR unset the
        resolver raises BEFORE ever consulting Path.home — proving the walk is
        physically unable to open the live ~/.claude store."""
        monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
        monkeypatch.setenv("ANCHOR_HEALTHCHECK", "1")
        home_calls = []
        monkeypatch.setattr(
            paths.Path, "home",
            classmethod(lambda cls: (home_calls.append(1),
                                     Path("/should-never-be-used"))[1]))
        with pytest.raises(paths.SidecarRootUnavailable):
            paths.sidecar_root()
        assert home_calls == [], "resolver consulted ~/.claude in hermetic mode"

    def test_production_branch_resolves_home_claude_projects(
            self, monkeypatch, tmp_path):
        """Only genuine production (no redirect / not a test / not the
        healthcheck) resolves ~/.claude/projects — and even then it only RETURNS
        the path, never opens it."""
        monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
        monkeypatch.delenv("ANCHOR_DATA_DIR", raising=False)
        monkeypatch.delenv("ANCHOR_HEALTHCHECK", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(paths.Path, "home",
                            classmethod(lambda cls: fake_home))
        assert paths.sidecar_root() == fake_home / ".claude" / "projects"
