"""foundry-v2 Wave 2 — the HOST-ENFORCED journaling write-back seam.

Proves the Wave-2 done-when:
  (a) every gandalf run through Anchor (done / failed / crashed) auto-journals
      a schema-valid 7-field skeleton entry to ``<skill_dir>/journal/`` with
      ZERO author action (no env toggle, no opt-in);
  (b) the droppable side channel (``journal/side/<run_id>/``) holds the heavy
      payloads, keeps the skeleton small (≤ the DR-04 2 KB cap), and can be
      deleted without breaking the skeleton;
  (c) the grep/drift gate fails if a capture path bypasses the seam — the
      low-level journal writer lives ONLY in ``foundry_journal.py`` and
      gandalf's finalize path is wired through it;
  (d) PLAN.md §7 (the append-only review log — the v1 honor-system system
      journal) backfills into schema-valid skeleton entries.

Hermetic like tests/test_gandalf_engine.py: temp ANCHOR_DATA_DIR, temp
project folder, temp ANCHOR_GANDALF_SKILL_DIR, both model seams stubbed
(``stub_gandalf_draft.py`` / ``stub_gandalf_host.py``). NEVER real claude /
real node / the real Skill Foundry / :8777. Stdlib only.
"""
import importlib
import re
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()

#: The real Skill Foundry PLAN.md (the system-level journal source). The
#: backfill test against it SKIPS gracefully when absent (portability).
REAL_PLAN_MD = Path(r"C:\dev\Skill Foundry\PLAN.md")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh gandalf + foundry_journal wired to stubs and a temp skill dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# stub skill protocol\n",
                                        encoding="utf-8")
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD",
                       f"{sys.executable} {HOST_STUB}")
    # Pin the legacy two-stage (map-reduce) path these draft+host stubs target.
    # master flipped run_gandalf's DEFAULT to the AGENTIC single-job path
    # (DEFAULT_MODE=agentic), which the two-stage stubs don't drive; the
    # journaling seam under test fires identically on either path, so we
    # exercise it via the stubbed legacy path.
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(skill_dir))
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    import foundry_journal
    fj = importlib.reload(foundry_journal)
    import gandalf
    g = importlib.reload(gandalf)
    return {"gandalf": g, "fj": fj, "skill_dir": skill_dir}


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text("# A project\n", encoding="utf-8")
    return folder, "pid-w2"


def _journal_entries(skill_dir: Path) -> list:
    # P2 2026-07-25: machine skeletons live under journal/machine/ (the curated
    # journal root is the HUMAN NNNN-*.md namespace — the flood fix).
    return sorted((skill_dir / "journal" / "machine").glob("*.md"))


def _parse_only_entry(fj, skill_dir: Path) -> dict:
    entries = _journal_entries(skill_dir)
    assert len(entries) == 1, "expected exactly one skeleton entry"
    return fj.parse_entry(entries[0].read_text(encoding="utf-8"))


# ── (a) every run auto-journals a schema-valid 7-field entry ─────────────────

def test_ok_run_auto_journals_seven_field_entry(env, project):
    g, fj, skill = env["gandalf"], env["fj"], env["skill_dir"]
    folder, pid = project
    out = g.run_gandalf(str(folder), pid)
    assert out["ok"] is True

    parsed = _parse_only_entry(fj, skill)
    # All 7 DR-04 fields present + non-empty (schema-valid).
    import foundry_decisions
    for field in foundry_decisions.JOURNAL_ENTRY_FIELDS:
        assert parsed.get(field), f"skeleton missing field: {field}"
    assert fj.validate_entry(parsed) == []
    assert parsed["operation_kind"] in foundry_decisions.OP_KINDS
    # Provenance names the host seam — capture was a by-product, not an author.
    assert "host-enforced" in parsed["provenance"]
    # Verdict + timing + linkage carry the run's real facts.
    assert "broadly sound" in parsed["verdict_timing"]["verdict"]
    assert parsed["verdict_timing"]["duration_s"] >= 0
    assert parsed["outcome_linkage"]["outcome"] == "done"
    assert parsed["outcome_linkage"]["run_id"] == out["run_id"]
    assert parsed["outcome_linkage"]["project_id"] == pid
    # model_cost carries model + billed cost + cache tokens (honest zeros
    # under stubs — the stub envelope reports no spend).
    mc = parsed["model_cost"]
    for key in ("model", "billed_cost_usd", "cache_tokens"):
        assert key in mc


def test_failed_run_still_journals(env, project, monkeypatch):
    g, fj, skill = env["gandalf"], env["fj"], env["skill_dir"]
    folder, pid = project
    monkeypatch.setenv("STUB_GANDALF_HOST_FAIL", "1")
    out = g.run_gandalf(str(folder), pid)
    assert out["ok"] is False

    parsed = _parse_only_entry(fj, skill)
    assert fj.validate_entry(parsed) == []
    assert parsed["outcome_linkage"]["outcome"] == "failed"
    assert parsed["outcome_linkage"]["reason"]  # the honest failure reason


def test_each_run_journals_its_own_entry(env, project):
    g, skill = env["gandalf"], env["skill_dir"]
    folder, pid = project
    first = g.run_gandalf(str(folder), pid)
    second = g.run_gandalf(str(folder), pid)
    names = {p.stem for p in _journal_entries(skill)}
    assert names == {first["run_id"], second["run_id"]}


# ── (b) droppable side channel: small skeleton, heavy bytes shunted ──────────

def test_skeleton_small_and_heavy_payload_in_side_channel(env, project):
    g, fj, skill = env["gandalf"], env["fj"], env["skill_dir"]
    folder, pid = project
    out = g.run_gandalf(str(folder), pid)
    assert out["ok"] is True
    run_id = out["run_id"]

    entry_file = _journal_entries(skill)[0]
    import foundry_decisions
    cap = foundry_decisions.SIDE_CHANNEL_DESIGN["skeleton_max_bytes"]
    assert entry_file.stat().st_size <= cap

    skeleton = entry_file.read_text(encoding="utf-8")
    # The heavy graded payload (the stub host's reasoning prose) is NOT
    # inlined in the skeleton...
    heavy_marker = "The deterministic seam pass stamped the raw draft"
    assert heavy_marker not in skeleton

    # ...it lives in the side channel, which the skeleton only REFERENCES.
    parsed = fj.parse_entry(skeleton)
    side = skill / "journal" / "machine" / "side" / run_id
    assert side.is_dir()
    outputs = (side / "outputs.json").read_text(encoding="utf-8")
    assert heavy_marker in outputs
    assert parsed["inputs_ref"] == f"journal/machine/side/{run_id}/inputs.json"
    assert parsed["outputs_ref"] == f"journal/machine/side/{run_id}/outputs.json"


def test_side_channel_is_droppable(env, project):
    g, fj, skill = env["gandalf"], env["fj"], env["skill_dir"]
    folder, pid = project
    out = g.run_gandalf(str(folder), pid)
    assert out["ok"] is True

    # Drop the WHOLE side channel (disk pressure / retention policy)...
    shutil.rmtree(skill / "journal" / "machine" / "side")
    # ...the skeleton still parses and validates — the corpus survives.
    parsed = _parse_only_entry(fj, skill)
    assert fj.validate_entry(parsed) == []
    assert parsed["outcome_linkage"]["run_id"] == out["run_id"]


# ── (c) the grep/drift gate — no honor-system capture path remains ───────────

#: A file write marker on the SAME LINE as a skill-journal dir indicator is a
#: capture path bypassing the seam. (journal.py — the per-project EVENT log,
#: journal.jsonl — is a different subsystem and carries no journal/ DIR path.)
_WRITE_MARKERS = ("open(", "write_text", "write_bytes", "mkdir", "makedirs",
                  "os.replace", ".write(")
_JOURNAL_DIR_MARKERS = ("journal/", "journal\\\\", "JOURNAL_DIRNAME",
                        "journal_dir", "side_dir")


def _product_sources():
    for py in sorted(_ROOT.glob("*.py")):
        yield py, py.read_text(encoding="utf-8", errors="replace")


def test_drift_gate_seam_is_the_only_journal_writer():
    offenders = []
    for py, src in _product_sources():
        if py.name == "foundry_journal.py":
            continue  # THE seam — the one sanctioned writer
        for n, line in enumerate(src.splitlines(), start=1):
            if any(w in line for w in _WRITE_MARKERS) and \
               any(j in line for j in _JOURNAL_DIR_MARKERS):
                offenders.append(f"{py.name}:{n}: {line.strip()}")
    assert not offenders, (
        "honor-system capture path(s) bypass the journaling seam:\n"
        + "\n".join(offenders))


def test_drift_gate_low_level_writer_defined_only_in_seam():
    for py, src in _product_sources():
        if py.name == "foundry_journal.py":
            assert "def append_entry" in src
            assert "def write_side_artifact" in src
            continue
        assert "def append_entry" not in src, py.name
        assert "def write_side_artifact" not in src, py.name


def test_drift_gate_gandalf_finalize_wired_through_seam():
    src = (_ROOT / "gandalf.py").read_text(encoding="utf-8",
                                           errors="replace")
    # The adapter imports the seam and its finalize path calls the write-back.
    assert "import foundry_journal" in src
    assert "journal_run_writeback(" in src
    body = src[src.index("def run_gandalf("):]
    body = body[:body.index("\ndef ")]  # the run_gandalf body only
    calls = re.findall(r"_journal_writeback\(", body)
    # Wired on BOTH terminal paths: the normal finalize + the crash path.
    assert len(calls) >= 2, "run_gandalf must journal on finalize AND crash"
    # Host-ENFORCED means unconditional: no env toggle guards the seam call.
    for line in body.splitlines():
        if "_journal_writeback(" in line:
            assert "environ" not in line and "getenv" not in line


# ── skeleton schema unit coverage ────────────────────────────────────────────

def test_validate_entry_rejects_missing_fields_and_bad_kind(env):
    fj = env["fj"]
    problems = fj.validate_entry({})
    import foundry_decisions
    for field in foundry_decisions.JOURNAL_ENTRY_FIELDS:
        assert any(field in p for p in problems)
    bad = {f: "x" for f in foundry_decisions.JOURNAL_ENTRY_FIELDS}
    bad["operation_kind"] = "freestyle"  # not on the DR-01 enum
    assert any("OP_KINDS" in p for p in fj.validate_entry(bad))


def test_append_entry_rejects_inline_bulk(env, tmp_path):
    fj = env["fj"]
    import foundry_decisions
    entry = {f: "x" for f in foundry_decisions.JOURNAL_ENTRY_FIELDS}
    entry["operation_kind"] = "run"
    entry["inputs_ref"] = "B" * 5000  # inline bulk, not a reference
    with pytest.raises(ValueError):
        fj.append_entry(tmp_path / "skill2", "e-1", entry)
    assert not (tmp_path / "skill2" / "journal" / "machine" / "e-1.md").exists()


def test_render_parse_roundtrip(env):
    fj = env["fj"]
    entry = {
        "id": "e-rt", "entry_schema": 1, "ts": 1234.5,
        "provenance": "host-enforced:anchor.gandalf",
        "operation_kind": "run",
        "model_cost": {"model": "claude", "billed_cost_usd": 0.12,
                       "cache_tokens": 42},
        "inputs_ref": "journal/side/e-rt/inputs.json",
        "outputs_ref": "journal/side/e-rt/outputs.json",
        "verdict_timing": {"verdict": "fine", "duration_s": 1.5},
        "outcome_linkage": {"outcome": "done", "run_id": "e-rt"},
    }
    parsed = fj.parse_entry(fj.render_entry(entry))
    assert parsed["model_cost"] == entry["model_cost"]
    assert parsed["verdict_timing"] == entry["verdict_timing"]
    assert parsed["outcome_linkage"] == entry["outcome_linkage"]
    assert fj.validate_entry(parsed) == []


# ── (d) PLAN.md §7 backfilled as a system-level journal ──────────────────────

_PLAN7_FIXTURE = """# Some Plan

## 6. Protocol

- not a review-log bullet (different section)

## 7. Review log (append-only — newest last)

- `2026-06-27` — **Claude** — Initial grounded status review (10 agents).
- `2026-06-27` — **Gemini** — **Cross-review complete (AGREE).** Re-ran gates.
- `2026-06-28` — **Gemini → Claude (Opus 4.8)** — **Phase 3 done.**
    - sub-detail line folds into the open bullet
    - another sub-detail

---

## 8. Evidence appendix

- also not a review-log bullet
"""


def test_backfill_plan_section7_fixture(env, tmp_path):
    fj = env["fj"]
    plan = tmp_path / "PLAN.md"
    plan.write_text(_PLAN7_FIXTURE, encoding="utf-8")
    out_dir = tmp_path / "system-journal"
    written = fj.backfill_plan_section7(plan, out_dir)
    assert len(written) == 3  # only the §7 top-level bullets
    for i, p in enumerate(written, start=1):
        parsed = fj.parse_entry(p.read_text(encoding="utf-8"))
        assert fj.validate_entry(parsed) == []
        assert parsed["provenance"].startswith("backfill:PLAN.md#7:")
        assert parsed["outcome_linkage"]["source"] == "PLAN.md#7"
        assert parsed["outcome_linkage"]["entry"] == i
    # Actors + dates extracted, sub-details folded in.
    first = fj.parse_entry(written[0].read_text(encoding="utf-8"))
    assert "Claude" in first["provenance"]
    assert first["verdict_timing"]["date"] == "2026-06-27"
    third = fj.parse_entry(written[2].read_text(encoding="utf-8"))
    assert "folds into the open bullet" in third["verdict_timing"]["verdict"]
    # Idempotent: same input → same files, no duplicates.
    again = fj.backfill_plan_section7(plan, out_dir)
    assert [p.name for p in again] == [p.name for p in written]
    assert len(list(out_dir.glob("*.md"))) == 3


def test_backfill_real_plan_md_when_present(env, tmp_path):
    fj = env["fj"]
    if not REAL_PLAN_MD.is_file():
        pytest.skip("real Skill Foundry PLAN.md not on this host")
    out_dir = tmp_path / "system-journal"
    written = fj.backfill_plan_section7(REAL_PLAN_MD, out_dir)
    # The real §7 review log yields a non-empty, fully schema-valid corpus.
    assert len(written) >= 1
    for p in written:
        parsed = fj.parse_entry(p.read_text(encoding="utf-8"))
        assert fj.validate_entry(parsed) == []
