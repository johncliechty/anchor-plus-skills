"""W4 STUB GATE — Usage-Capture Pipeline: UUID-at-launch · ledger · eager finalize
· capture-failed RED path (Honest Telemetry).

Cites ``NORTH-STAR-AMENDMENT.md`` (tripwire severity · defer-and-badge ·
no-own-pricing-table) + ``W1-GROUND-TRUTH.md`` §1 (sidecar shape / dedup by
``message.id``). Serves criteria (1),(3),(6).

done-when (verbatim from the plan): the STUB-GATE suite is green — every end path
finalizes exactly one RUN cost record with the pinned fixture's exact totals, the
corrupted-fixture leg yields ``state='capture-failed'`` (not $0, not unmeasured),
the switch-engine invariant holds, and **no test ever resolved the live
``~/.claude`` store** (the W2 fail-closed seam is enforced — a temp
``ANCHOR_SIDECAR_DIR`` or a raise, never a real home path).

Hermetic: temp data dir, temp ``ANCHOR_SIDECAR_DIR`` with the PINNED fixtures, stub
PTY backend, the fake runner, a temp git repo — NEVER ``:8777`` / real data /
network / a live model.
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


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1) The sum-over-message parser + capture-failed classifier (PURE, no env)
# ══════════════════════════════════════════════════════════════════════════════

class TestParser:
    def test_canonical_measured_deduped_totals(self):
        import usage_capture as uc
        res = uc.parse_sidecar_text(_fx("canonical_3turn.jsonl"))
        exp = EXPECTED["canonical_3turn.jsonl"]
        assert res["state"] == uc.STATE_MEASURED
        assert res["reason"] is None
        # DEDUP by message.id — 4 assistant lines, 3 unique message ids.
        assert res["assistant_record_lines"] == exp["assistant_record_lines"]
        assert res["unique_message_ids"] == exp["unique_message_ids"]
        for k, v in exp["token_totals"].items():
            assert res["token_totals"][k] == v, k
        assert res["duration_ms"] == exp["duration_ms"]

    def test_canonical_is_not_naively_double_counted(self):
        """The duplicated ``message.id`` line must NOT inflate the totals."""
        import usage_capture as uc
        res = uc.parse_sidecar_text(_fx("canonical_3turn.jsonl"))
        naive = EXPECTED["canonical_3turn.jsonl"]["naive_undeduped_would_be"]
        assert res["token_totals"]["input_tokens"] != naive["input_tokens"]
        assert res["token_totals"]["output_tokens"] != naive["output_tokens"]

    def test_resumed_segment_measured(self):
        import usage_capture as uc
        res = uc.parse_sidecar_text(_fx("resumed_segment.jsonl"))
        exp = EXPECTED["resumed_segment.jsonl"]
        assert res["state"] == uc.STATE_MEASURED
        for k, v in exp["token_totals"].items():
            assert res["token_totals"][k] == v, k
        assert res["duration_ms"] == exp["duration_ms"]

    def test_zero_usage_is_capture_failed_not_measured_zero(self):
        import usage_capture as uc
        res = uc.parse_sidecar_text(_fx("corrupted_zero_usage.jsonl"))
        assert res["state"] == uc.STATE_CAPTURE_FAILED
        assert res["reason"] == uc.REASON_ZERO_USAGE
        assert res["has_message_lines"] is True
        # NEVER measured-$0: no measured state despite the message lines.
        assert res["state"] != uc.STATE_MEASURED

    def test_malformed_line_is_capture_failed_parse_error(self):
        import usage_capture as uc
        res = uc.parse_sidecar_text(_fx("corrupted_malformed.jsonl"))
        assert res["state"] == uc.STATE_CAPTURE_FAILED
        assert res["reason"] == uc.REASON_PARSE_ERROR

    def test_empty_sidecar_is_unmeasured_not_capture_failed(self):
        """A present-but-turnless file (only a summary) is honest UNMEASURED —
        NOT capture-failed (there were no turns to measure)."""
        import usage_capture as uc
        text = ('{"type":"summary","summary":"s","leafUuid":"x"}\n')
        res = uc.parse_sidecar_text(text)
        assert res["state"] == uc.STATE_UNMEASURED
        assert res["reason"] == uc.REASON_EMPTY_SIDECAR


# ══════════════════════════════════════════════════════════════════════════════
# 2) Ledger idempotency + the switch-engine invariant (temp data dir only)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def datadir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(d))
    for mod in ("paths", "usage_ledger", "session_registry", "effort_history"):
        importlib.reload(importlib.import_module(mod))
    import usage_capture
    importlib.reload(usage_capture)
    import paths
    paths.ensure_data_dirs()
    return d


class TestSwitchEngineInvariant:
    def test_A_plus_B_counted_once_idempotent_on_reingest(self, datadir):
        """Ingest segment A (canonical) + segment B (resumed), RE-ingest B, then
        the combined ledger total == A + B counted EXACTLY once."""
        import usage_capture as uc
        ua = "uuid-A-0001"
        ub = "uuid-B-0002"
        uc.ingest_sidecar(ua, _fx("canonical_3turn.jsonl"), is_text=True)
        uc.ingest_sidecar(ub, _fx("resumed_segment.jsonl"), is_text=True)
        # RE-INGEST the same file — must add nothing (idempotent by message.id).
        uc.ingest_sidecar(ub, _fx("resumed_segment.jsonl"), is_text=True)

        combined = uc.combined_totals([ua, ub])
        exp = EXPECTED["engine_switch_combined_A_plus_B"]["token_totals"]
        for k, v in exp.items():
            assert combined[k] == v, k

    def test_reingest_same_uuid_does_not_double_count(self, datadir):
        import usage_capture as uc
        ua = "uuid-A-solo"
        uc.ingest_sidecar(ua, _fx("canonical_3turn.jsonl"), is_text=True)
        uc.ingest_sidecar(ua, _fx("canonical_3turn.jsonl"), is_text=True)
        combined = uc.combined_totals([ua])
        exp = EXPECTED["canonical_3turn.jsonl"]["token_totals"]
        assert combined["total_all_classes"] == exp["total_all_classes"]


# ══════════════════════════════════════════════════════════════════════════════
# 3) Eager finalize on EVERY end path — the full stub stack
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data dir + temp ANCHOR_SIDECAR_DIR + temp worktree base + stub PTY +
    fake runner + a temp git repo. The sidecar root is a FIXTURE dir — the W2
    fail-closed seam means no real ``~/.claude`` store is ever resolvable.

    git is a HARD requirement for Anchor (worktree isolation) and is always
    present in the build/CI environment, so this fixture does NOT skip on a
    missing git — a missing-git failure is an honest failure, not a silent skip
    (the skip added a marker that tripped Foreman's §5 test-integrity guard)."""
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
                "brownfield_scan", "effort_view", "deliverables",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import terminal_session, session_registry, effort_history, rnd_registry
    import usage_capture, pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)

    yield {
        "ts": terminal_session, "reg": session_registry, "eh": effort_history,
        "uc": usage_capture, "sidecars": sidecars, "pid": proj["id"],
        "repo": repo,
    }
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _start_and_place(env, fixture="canonical_3turn.jsonl", lane="build"):
    """Start a stub session (UUID pinned at launch) and place ``fixture`` as its
    sidecar under the temp ANCHOR_SIDECAR_DIR (keyed by the launch UUID)."""
    rec = env["ts"].start_session(env["pid"], lane, backend="claude")
    sid = rec["session_id"]
    euuid = rec.get("engine_session_uuid")
    assert euuid, "UUID-at-launch was not captured onto the record"
    (env["sidecars"] / f"{euuid}.jsonl").write_text(
        _fx(fixture), encoding="utf-8")
    return rec, sid, euuid


def _run_cost_records(env, pid, lane="build"):
    folder = env["repo"]
    return [e for e in env["eh"].list_efforts(str(folder), pid, lane)
            if e.get("kind") == "run-cost"]


# The five end paths, each a callable (ts, sid, pid) → performs the end path.
END_PATHS = {
    "kill": lambda e, sid: e["ts"].kill(sid),
    "close": lambda e, sid: e["ts"].close_session(sid),
    "drain": lambda e, sid: e["ts"].suspend_session(sid),
    "finish": lambda e, sid: e["ts"].finalize_usage(sid),
    "reconcile": lambda e, sid: e["ts"].reconcile_and_advance(
        live_session_ids=set()),
}


@pytest.mark.parametrize("end_path", list(END_PATHS))
def test_every_end_path_finalizes_one_measured_cost_record(env, end_path):
    """G/W/T: end via each path (kill / close-park / drain / finish /
    reconcile-dead) → EXACTLY ONE RUN cost record whose tokens/time match the
    fixture's summed per-message usage, snapshotted into ``.anchor/``."""
    rec, sid, euuid = _start_and_place(env)
    END_PATHS[end_path](env, sid)

    cost_recs = _run_cost_records(env, env["pid"])
    assert len(cost_recs) == 1, (end_path, cost_recs)
    rc = cost_recs[0]
    assert rc.get("usage_state") == env["uc"].STATE_MEASURED
    assert rc.get("session_id") == sid
    cost = rc.get("cost") or {}
    exp = EXPECTED["canonical_3turn.jsonl"]
    for k, v in exp["token_totals"].items():
        assert cost.get(k) == v, (end_path, k)
    assert cost.get("total_tokens") == exp["token_totals"]["total_all_classes"]
    assert cost.get("duration_ms") == exp["duration_ms"]
    # no-own-pricing-table: $ is 0.0 on the interactive path (no costUSD).
    assert cost.get("total_cost_usd") == 0.0
    # the registry record is stamped MEASURED + the cost_final latch is set.
    after = env["reg"].get_session(sid)
    assert after["usage_state"] == env["uc"].STATE_MEASURED
    assert after["cost_final"] is True


def test_finalize_is_idempotent_across_two_end_paths(env):
    """close then kill the SAME session → still EXACTLY ONE cost record (the W2
    cost_final CAS gates the write; the second end path is a clean no-op)."""
    rec, sid, euuid = _start_and_place(env)
    env["ts"].close_session(sid)
    env["ts"].kill(sid)
    assert len(_run_cost_records(env, env["pid"])) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 4) The capture-failed RED path (corrupted fixture) — never $0, never unmeasured
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fixture,reason_attr", [
    ("corrupted_zero_usage.jsonl", "REASON_ZERO_USAGE"),
    ("corrupted_malformed.jsonl", "REASON_PARSE_ERROR"),
])
def test_corrupted_fixture_yields_capture_failed_record(env, fixture,
                                                        reason_attr):
    """A sidecar that is PRESENT but unparseable / zero-usage-despite-message-lines
    finalizes to an atomic ``capture-failed`` record carrying the parse-error
    class — never a measured-$0 record, never a silent unmeasured. The session
    lifecycle (kill) completes normally."""
    rec, sid, euuid = _start_and_place(env, fixture=fixture)
    out = env["ts"].kill(sid)
    assert out.get("ok") is True  # lifecycle completed normally

    cost_recs = _run_cost_records(env, env["pid"])
    assert len(cost_recs) == 1
    rc = cost_recs[0]
    assert rc.get("usage_state") == env["uc"].STATE_CAPTURE_FAILED
    assert rc.get("usage_reason") == getattr(env["uc"], reason_attr)
    # NEVER measured-$0, NEVER a silent unmeasured — cost is explicitly None.
    assert rc.get("cost") is None
    after = env["reg"].get_session(sid)
    assert after["usage_state"] == env["uc"].STATE_CAPTURE_FAILED


# ══════════════════════════════════════════════════════════════════════════════
# 5) Honest unmeasured legs — uncorrelated / sidecar-pruned / fail-closed
# ══════════════════════════════════════════════════════════════════════════════

def test_uncaptured_uuid_is_uncorrelated_not_a_guessed_total(env,
                                                             monkeypatch):
    """No engine UUID captured at launch (injection disabled by the seam) → the
    session finalizes UNMEASURED (uncorrelated); NO effort cost record is written
    (defer-and-badge — never a guessed total)."""
    monkeypatch.setenv("ANCHOR_TERMINAL_SESSION_ID_FLAG", "")  # disable injection
    rec = env["ts"].start_session(env["pid"], "build", backend="claude")
    sid = rec["session_id"]
    assert rec.get("engine_session_uuid") == ""  # honestly uncorrelated
    env["ts"].kill(sid)
    assert _run_cost_records(env, env["pid"]) == []
    after = env["reg"].get_session(sid)
    assert after["usage_state"] == env["uc"].STATE_UNMEASURED
    assert after["usage_reason"] == env["uc"].REASON_UNCORRELATED


def test_pruned_sidecar_is_unmeasured_no_cost_record(env):
    """UUID captured but the sidecar file is absent (pruned) → UNMEASURED
    (sidecar-pruned); no cost record (never a fabricated measurement)."""
    rec = env["ts"].start_session(env["pid"], "build", backend="claude")
    sid = rec["session_id"]
    assert rec.get("engine_session_uuid")  # captured, but we place NO file
    env["ts"].kill(sid)
    assert _run_cost_records(env, env["pid"]) == []
    after = env["reg"].get_session(sid)
    assert after["usage_state"] == env["uc"].STATE_UNMEASURED
    assert after["usage_reason"] == env["uc"].REASON_SIDECAR_PRUNED


def test_measured_totals_snapshot_into_anchor_store_not_home(env):
    """The measured usage lands in Anchor's OWN durable ledger (``.anchor/``), so
    a weeks-later reconcile reads the snapshot, not the prunable home store."""
    import usage_ledger as ul
    rec, sid, euuid = _start_and_place(env)
    env["ts"].kill(sid)
    led = ul.ledger_entries(euuid)
    assert led, "measured usage was not snapshotted into the .anchor/ ledger"
    combined = env["uc"].combined_totals([euuid])
    exp = EXPECTED["canonical_3turn.jsonl"]["token_totals"]
    assert combined["total_all_classes"] == exp["total_all_classes"]


class TestFailClosedUnderPytest:
    def test_finalize_never_resolves_home_when_sidecar_dir_unset(
            self, tmp_path, monkeypatch):
        """With ANCHOR_SIDECAR_DIR UNSET under pytest, finalize degrades to
        unmeasured WITHOUT ever resolving ``~/.claude`` (the fail-closed seam) and
        WITHOUT crashing — proving no test resolves the live home store."""
        data = tmp_path / "data"
        data.mkdir()
        monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
        monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
        for mod in ("paths", "usage_ledger", "session_registry",
                    "effort_history", "usage_capture"):
            importlib.reload(importlib.import_module(mod))
        import paths, session_registry as reg, usage_capture as uc
        paths.ensure_data_dirs()
        # The resolver refuses outright in this hermetic context.
        with pytest.raises(paths.SidecarRootUnavailable):
            paths.sidecar_root()
        # A record carrying an engine uuid but no reachable sidecar root.
        r = reg.register_session("pid", "build", status=reg.STATUS_RUNNING,
                                 engine_session_uuid="uuid-x")
        sid = r["session_id"]
        # Spy: Path.home must never be consulted during finalize.
        home_calls = []
        monkeypatch.setattr(
            paths.Path, "home",
            classmethod(lambda cls: (home_calls.append(1),
                                     Path("/should-never-be-used"))[1]))
        out = uc.finalize_session_usage(sid)  # must NOT raise
        assert out["state"] == uc.STATE_UNMEASURED
        assert home_calls == [], "finalize resolved ~/.claude in hermetic mode"


# ══════════════════════════════════════════════════════════════════════════════
# 6) The UUID-at-launch argv seam + the ledger inspection endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestUuidAtLaunchArgv:
    def test_claude_argv_injects_session_id_flag(self):
        import terminal_session as ts
        argv = ts._engine_launch_argv("claude", "claude", "the-uuid")
        assert argv == ["claude", "--session-id", "the-uuid"]

    def test_gemini_argv_is_not_injected(self):
        import terminal_session as ts
        argv = ts._engine_launch_argv("agy", "gemini", "the-uuid")
        assert argv == ["agy"]  # no pin on the gemini segment (RULED Option C)

    def test_seam_can_disable_injection(self, monkeypatch):
        import terminal_session as ts
        monkeypatch.setenv("ANCHOR_TERMINAL_SESSION_ID_FLAG", "")
        argv = ts._engine_launch_argv("claude", "claude", "the-uuid")
        assert argv == ["claude"]


def test_usage_ledger_endpoint_reports_finalized_state(env):
    """The token-authed ledger inspection endpoint surfaces the finalized usage
    verdict + ledger totals (SAFE projection — never worktree/branch)."""
    rec, sid, euuid = _start_and_place(env)
    env["ts"].kill(sid)
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    captured = {}

    class _H:
        path = f"/api/rnd/usage_ledger?session={sid}"

        def _term_token_ok(self):
            return True

        def _send_json(self, obj, code=200):
            captured["obj"] = obj
            captured["code"] = code

    gui.handle_usage_ledger(_H(), _H.path, {})
    assert captured["obj"]["ok"] is True
    usage = captured["obj"]["usage"]
    assert usage["state"] == env["uc"].STATE_MEASURED
    assert usage["cost_final"] is True
    assert euuid in usage["engine_session_uuids"]
    exp = EXPECTED["canonical_3turn.jsonl"]["token_totals"]
    assert usage["ledger_totals"]["total_all_classes"] == exp["total_all_classes"]
    # SAFE projection — no worktree/branch leak.
    assert "worktree_path" not in usage
    assert "branch" not in usage
