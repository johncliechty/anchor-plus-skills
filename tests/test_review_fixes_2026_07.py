"""2026-07-02 review fixes — STUB GATE.

Two diagnosed regressions:

1. Gandalf store/read split (`run_gandalf(store_folder=...)`): a run whose
   ANALYSIS scope is re-pointed away from the project's registry folder must
   still RECORD (index + `gandalf/run-*/` artifacts) into the registry folder —
   the read path (`/api/rnd/gandalf`, the panel render, archive/delete) resolves
   off the registry folder, so a run stored anywhere else is invisible (the
   `__dashboard__` five-stranded-runs regression).

2. Orphan-tolerant discovered-session fold (`effort_view`): a persisted doc
   tagged with a `session_id` whose registry record is GONE (wiped/rolled-back
   `sessions.json`) folds in as a first-class historical effort instead of
   vanishing from every view.

Hermetic + fully stubbed like `test_gandalf_mapreduce_w9.py`: temp
`ANCHOR_DATA_DIR`, stub draft/host runners, never real claude / node / :8777.
"""
import importlib
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()


@pytest.fixture
def gandalf(tmp_path, monkeypatch):
    """A fresh gandalf module wired to the two stubs + a temp data dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", f"{sys.executable} {HOST_STUB}")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    # The fusion tests exercise the LEGACY map-reduce path (retained fallback);
    # the DEFAULT is now the agentic canonical-skill run.
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    import gandalf
    yield importlib.reload(gandalf)


@pytest.fixture
def scoped_folders(tmp_path):
    """An analysis folder (tiny tree) + a DISTINCT store/registry folder."""
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "README.md").write_text("# scope\n", encoding="utf-8")
    store = tmp_path / "registry-folder"
    store.mkdir()
    return analysis, store


# ── 1. gandalf store/read split ──────────────────────────────────────────────

def test_run_gandalf_records_into_store_folder_not_analysis_folder(
        gandalf, scoped_folders):
    analysis, store = scoped_folders
    pid = "pid-split"
    res = gandalf.run_gandalf(str(analysis), pid, store_folder=str(store))
    # The index lives under the STORE folder — where the read path looks…
    assert gandalf._index_path(str(store), pid).exists()
    assert gandalf.list_runs(str(store), pid), "run visible from the store index"
    # …and NOT under the re-scoped analysis folder (the regression shape).
    assert not gandalf._index_path(str(analysis), pid).exists()
    assert gandalf.list_runs(str(analysis), pid) == []
    # A successful run's artifacts also land under the STORE folder.
    if res.get("ok"):
        assert (Path(str(store)) / gandalf.GANDALF_DIRNAME).is_dir()
        assert not (Path(str(analysis)) / gandalf.GANDALF_DIRNAME).exists()


def test_run_gandalf_default_store_is_the_analysis_folder(gandalf, scoped_folders):
    analysis, _store = scoped_folders
    pid = "pid-default"
    gandalf.run_gandalf(str(analysis), pid)
    assert gandalf._index_path(str(analysis), pid).exists()
    assert gandalf.list_runs(str(analysis), pid)


def test_run_gandalf_if_absent_checks_the_store_index(gandalf, scoped_folders):
    analysis, store = scoped_folders
    pid = "pid-absent"
    first = gandalf.run_gandalf_if_absent(str(analysis), pid,
                                          store_folder=str(store))
    assert not first.get("skipped")
    second = gandalf.run_gandalf_if_absent(str(analysis), pid,
                                           store_folder=str(store))
    assert second.get("skipped"), "the absence check must read the STORE index"


# ── 2. orphan-tolerant discovered-session fold ───────────────────────────────

def _fake_discovered(monkeypatch, tmp_path):
    import sessions, effort_history
    fake = [{
        "session_id": "disc-orphan", "timestamp": 123.0,
        "member_files": [{
            "artifact_path": "planning/DOC.md", "title": "Doc", "kind": "doc",
            "status": "imported", "session_id": "gone-sid",
        }],
    }]
    monkeypatch.setattr(sessions, "list_sessions",
                        lambda f, p, lane: fake if lane == "plan" else [])
    monkeypatch.setattr(effort_history, "is_discovered", lambda m: True)


def test_orphaned_persisted_session_folds_in(monkeypatch, tmp_path):
    import effort_view, session_registry
    _fake_discovered(monkeypatch, tmp_path)
    # Registry record GONE (the wipe) → the session must fold in, not vanish.
    monkeypatch.setattr(session_registry, "get_session", lambda sid: None)
    out = effort_view._efforts_from_discovered(str(tmp_path), "pid")
    assert len(out) == 1, "an orphaned persisted session is a first-class effort"


def test_registered_persisted_session_still_skipped(monkeypatch, tmp_path):
    import effort_view, session_registry
    _fake_discovered(monkeypatch, tmp_path)
    # Registry record PRESENT → the skip stands (no duplicate tile).
    monkeypatch.setattr(session_registry, "get_session",
                        lambda sid: {"session_id": sid})
    out = effort_view._efforts_from_discovered(str(tmp_path), "pid")
    assert out == [], "a registered session stays represented by its registry effort"


# ── 2b. reduce honors the PRE-REGISTERED output caps (live 2026-07-02 failure:
#        a 12-shard merge aggregated 35 nitpicks; the Stage-B host hard-fails
#        >7 nitpicks / >5 elevations, so the whole run died at grading) ────────

def test_reduce_trims_to_contract_caps_round_robin(gandalf):
    shard_results = []
    for s in range(6):  # 6 shards × 3 nitpicks + 2 elevations each
        shard_results.append((f"s{s}", {
            "findings": [{"id": f"f{s}", "verdict": "x"}],
            "nitpicks": [{"id": f"n{s}-{i}", "verdict": "nit"} for i in range(3)],
            "elevations": [{"id": f"e{s}-{i}", "verdict": "el"} for i in range(2)],
            "verdict": f"v{s}", "reasoning": f"r{s}",
        }, None))
    merged, reason = gandalf._reduce_drafts(shard_results)
    assert reason is None
    assert len(merged["nitpicks"]) == 7, "nitpicks trimmed to the pre-registered cap"
    assert len(merged["elevations"]) == 5, "elevations trimmed to the pre-registered cap"
    # Round-robin fairness: the first item of EVERY shard survives before any
    # shard's second item (6 shards → all six n*-0 kept, one n*-1).
    kept_first = [n["id"] for n in merged["nitpicks"] if n["id"].endswith("-0")]
    assert len(kept_first) == 6
    assert "Trimmed to the pre-registered output caps" in merged["reasoning"]


def test_reduce_under_cap_untouched(gandalf):
    shard_results = [("a", {"findings": [], "nitpicks": [{"id": "n1"}],
                            "elevations": [], "verdict": "v"}, None)]
    merged, _ = gandalf._reduce_drafts(shard_results)
    assert len(merged["nitpicks"]) == 1
    assert "Trimmed" not in merged["reasoning"]


# ── 3. map-reduce FUSION pass (2026-07: the cross-shard synthesis step) ──────

@pytest.fixture
def multi_project(tmp_path):
    folder = tmp_path / "proj"
    (folder / "src").mkdir(parents=True)
    (folder / "docs").mkdir()
    (folder / "lib").mkdir()
    (folder / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (folder / "docs" / "x.md").write_text("# doc\n", encoding="utf-8")
    (folder / "lib" / "y.py").write_text("def y():\n    return 1\n", encoding="utf-8")
    return folder, "pid-fusion"


def test_fusion_augments_multi_shard_draft(gandalf, multi_project, monkeypatch):
    folder, pid = multi_project
    shards = gandalf._shard_tree(str(folder))
    assert len(shards) >= 2
    launches = []
    orig_launch = gandalf._jr.launch
    monkeypatch.setattr(gandalf._jr, "launch",
                        lambda *a, **k: (launches.append(k), orig_launch(*a, **k))[1])
    captured = {}
    orig_stage_b = gandalf._run_stage_b
    monkeypatch.setattr(gandalf, "_run_stage_b",
                        lambda draft, run_id=None: (captured.setdefault("draft", draft),
                                                    orig_stage_b(draft, run_id=run_id))[1])
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    draft = captured["draft"]
    # One launch per shard + ONE fusion launch, all read-only.
    assert len(launches) == len(shards) + 1
    assert all(k.get("permission_mode") == "plan" for k in launches)
    # Fusion stamped; the grouped per-shard coverage contract SURVIVES fusion.
    assert draft["fusion"] == "fused"
    assert draft["shard_count"] == len(shards)
    for lbl in draft["groups"]:
        assert [f for f in draft["findings"] if f.get("group") == lbl]
    # The fusion job's brain inherits the run's TIER reasoner model (2026-07-07):
    # a default/standard run fuses on Opus (heavy fuses on Fable-5, below).
    fusion_env = launches[-1].get("env") or {}
    assert fusion_env.get("ANTHROPIC_MODEL") == "claude-opus-4-8"
    assert fusion_env.get("TRIO_TIER") == "standard"


def test_fusion_uses_fable5_when_heavy(gandalf, multi_project, monkeypatch):
    """A Gandalf-Heavy run fuses on the top-tier Claude seat (Fable-5)."""
    folder, pid = multi_project
    launches = []
    orig_launch = gandalf._jr.launch
    monkeypatch.setattr(gandalf._jr, "launch",
                        lambda *a, **k: (launches.append(k), orig_launch(*a, **k))[1])
    out = gandalf.run_gandalf(str(folder), pid, tier="heavy")
    assert out["ok"] is True and out["tier"] == "heavy"
    fusion_env = launches[-1].get("env") or {}
    assert fusion_env.get("ANTHROPIC_MODEL") == "claude-fable-5"
    assert fusion_env.get("TRIO_TIER") == "heavy"


def test_fusion_skipped_single_shard_and_when_disabled(gandalf, scoped_folders,
                                                       multi_project, monkeypatch):
    analysis, _store = scoped_folders
    captured = {}
    orig_stage_b = gandalf._run_stage_b
    monkeypatch.setattr(gandalf, "_run_stage_b",
                        lambda draft, run_id=None: (captured.setdefault("draft", draft),
                                                    orig_stage_b(draft, run_id=run_id))[1])
    gandalf.run_gandalf(str(analysis), "pid-single")
    assert captured["draft"]["fusion"] == "single-shard"

    captured.clear()
    monkeypatch.setenv("ANCHOR_GANDALF_FUSION", "0")
    folder, pid = multi_project
    gandalf.run_gandalf(str(folder), pid)
    assert captured["draft"]["fusion"] == "disabled"


def test_registry_read_error_errs_toward_skip(monkeypatch, tmp_path):
    import effort_view, session_registry
    _fake_discovered(monkeypatch, tmp_path)
    def _boom(sid):
        raise OSError("registry unreadable")
    monkeypatch.setattr(session_registry, "get_session", _boom)
    out = effort_view._efforts_from_discovered(str(tmp_path), "pid")
    assert out == [], "a transient registry error may hide for one render, never double"
