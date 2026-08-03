"""Wave 9 — Gandalf map-reduce (Pillar B, #2) STUB GATE.

Replaces the single whole-tree Stage-A pass with a real MAP-REDUCE: shard the
target tree (≥2 shards for a multi-dir project), fan out one read per shard via
the W8 engine substrate (``lanes.select_engine_plan``), REDUCE the per-shard
drafts into ONE merged raw draft whose findings are GROUPED by shard (≥1 per
shard that produced a draft), then grade once via the Stage-B host. While the
run fans out, the index exposes an in-progress ``status='running'`` record.

Hermetic + fully stubbed exactly like ``test_gandalf_engine.py``: temp
``ANCHOR_DATA_DIR`` (job records), a temp project folder (artifacts at PROJECT
ROOT), ``ANCHOR_RUNNER_CMD`` → ``stub_gandalf_draft.py`` (canned RAW draft per
shard) and ``ANCHOR_GANDALF_HOST_CMD`` → ``stub_gandalf_host.py`` (canned GRADED
output). NEVER real claude / real node / :8777. Stdlib only.
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
    # These W9 gates assert the PURE map-reduce contract (exactly one launch per
    # shard, mechanical merge). The 2026-07 FUSION pass is its own feature with
    # its own gates (tests/test_review_fixes_2026_07.py) — off here.
    monkeypatch.setenv("ANCHOR_GANDALF_FUSION", "0")
    # This suite asserts the LEGACY map-reduce contract (the retained fallback);
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
def multi_project(tmp_path):
    """A project with several top-level dirs → the tree shards into ≥2 shards."""
    folder = tmp_path / "proj"
    (folder / "src").mkdir(parents=True)
    (folder / "docs").mkdir()
    (folder / "lib").mkdir()
    (folder / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (folder / "src" / "b.py").write_text("print('b')\n", encoding="utf-8")
    (folder / "docs" / "x.md").write_text("# doc\n", encoding="utf-8")
    (folder / "lib" / "y.py").write_text("def y():\n    return 1\n", encoding="utf-8")
    return folder, "pid-mr"


@pytest.fixture
def tiny_project(tmp_path):
    """A single-file project → the tree yields exactly ONE shard (single-pass)."""
    folder = tmp_path / "tiny"
    folder.mkdir()
    (folder / "README.md").write_text("# only\n", encoding="utf-8")
    return folder, "pid-tiny"


# ── sharding ─────────────────────────────────────────────────────────────────

def test_shard_tree_splits_multi_dir_into_ge2_shards(gandalf, multi_project):
    folder, _pid = multi_project
    shards = gandalf._shard_tree(str(folder))
    assert len(shards) >= 2, "a multi-dir tree must shard into ≥2 read-units"
    # Every shard carries a label + a (possibly empty) file list.
    for s in shards:
        assert s.get("label")
        assert isinstance(s.get("files"), list)
    # The covered files are exactly the non-ignored files (no loss, no dupes).
    covered = sorted(f for s in shards for f in s["files"])
    assert covered == sorted(gandalf._collect_files(str(folder)))


def test_single_file_tree_yields_one_shard(gandalf, tiny_project):
    folder, _pid = tiny_project
    shards = gandalf._shard_tree(str(folder))
    assert len(shards) == 1, "a trivial tree preserves the single-pass behavior"


# ── map: one dispatched read per shard ───────────────────────────────────────

def test_run_dispatches_a_read_per_shard(gandalf, multi_project, monkeypatch):
    folder, pid = multi_project
    shards = gandalf._shard_tree(str(folder))
    assert len(shards) >= 2

    launches = []
    orig_launch = gandalf._jr.launch

    def spy_launch(*a, **k):
        launches.append((a, k))
        return orig_launch(*a, **k)

    monkeypatch.setattr(gandalf._jr, "launch", spy_launch)
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    # Exactly one dispatched read per shard.
    assert len(launches) == len(shards) >= 2
    # Every dispatched read is read-only (plan), never acceptEdits.
    for (_a, k) in launches:
        assert k.get("permission_mode") == "plan"


# ── reduce: grouped findings, ≥1 per shard ───────────────────────────────────

def test_reduce_emits_grouped_findings_ge1_per_shard(gandalf):
    shard_results = [
        ("src", {"findings": [{"id": "d1", "verdict": "x"}], "nitpicks": [],
                 "elevations": [], "verdict": "v-src", "reasoning": "r-src"}, None),
        # An empty-findings shard still gets an honest coverage marker (proves it
        # was read) so grouping is ≥1 per shard.
        ("docs", {"findings": [], "nitpicks": [], "elevations": [],
                  "verdict": "v-docs"}, None),
        # A failed shard contributes nothing (not counted as a group).
        ("lib", None, "stage-a-unparseable-draft"),
    ]
    merged, reason = gandalf._reduce_drafts(shard_results)
    assert reason is None
    assert merged["shard_count"] == 2
    assert set(merged["groups"]) == {"src", "docs"}
    for lbl in ("src", "docs"):
        got = [f for f in merged["findings"] if f.get("group") == lbl]
        assert len(got) >= 1, f"shard {lbl} must contribute ≥1 grouped finding"
    # No finding is left untagged.
    assert all(f.get("group") for f in merged["findings"])


def test_reduce_all_unparseable_is_honest_error(gandalf):
    res = [("a", None, "stage-a-unparseable-draft"), ("b", None, "launch-failed")]
    merged, reason = gandalf._reduce_drafts(res)
    assert merged is None
    assert "unparseable" in reason  # preserves the honest Stage-A degrade reason


# ── index exposes an in-progress state before completion ─────────────────────

def test_index_exposes_in_progress_and_grouped_draft(gandalf, multi_project,
                                                      monkeypatch):
    folder, pid = multi_project
    shards = gandalf._shard_tree(str(folder))
    captured = {}

    orig_stage_b = gandalf._run_stage_b

    def spy_stage_b(raw_draft, run_id=None):
        # Snapshot the index the moment the reduce hands off to grading — the run
        # is NOT yet finalized, so the in-progress record must be visible.
        captured["draft"] = raw_draft
        captured["mid_runs"] = gandalf.list_runs(str(folder), pid)
        return orig_stage_b(raw_draft, run_id=run_id)

    monkeypatch.setattr(gandalf, "_run_stage_b", spy_stage_b)
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True

    # (a) in-progress state exposed before completion.
    mid = captured["mid_runs"]
    running = [r for r in mid
               if r.get("in_progress") and r.get("status") == "running"]
    assert running, "the index must expose an in-progress record before completion"
    assert running[0]["ok"] is False

    # (b) the reduced draft handed to grading carries grouped findings, ≥1/shard.
    draft = captured["draft"]
    assert draft["shard_count"] == len(shards)
    assert len(draft["groups"]) == len(shards) >= 2
    for lbl in draft["groups"]:
        got = [f for f in draft["findings"] if f.get("group") == lbl]
        assert len(got) >= 1, f"shard {lbl} must contribute ≥1 grouped finding"


def test_completed_run_upserts_a_single_terminal_record(gandalf, multi_project):
    folder, pid = multi_project
    out = gandalf.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    runs = gandalf.list_runs(str(folder), pid)
    # The in-progress row is UPSERTED into ONE terminal record (no ghost row).
    assert len(runs) == 1
    assert runs[0]["status"] == "done"
    assert runs[0]["in_progress"] is False
    assert runs[0]["ok"] is True
    assert runs[0]["verdict"]


def test_shard_backend_never_cross_calls_on_claude_only(gandalf, monkeypatch):
    """The W8 substrate drives the shard reads: a Claude-only host never picks a
    Gemini shard backend (honest single-subscription fallback, #10)."""
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "0")
    assert gandalf._resolve_shard_backend() == gandalf._jr.BACKEND_CLAUDE
