# W11 — E6: the deterministic standing-preferences preload + the DIFFABLE
# projection (steward-chamber W11, C7).
#
# AUTH-ON: not-a-surface
#
# The wave's own words drive these tests:
#   * "Given a fixture feedback ledger and global standing rules, when the
#     talk instruction composes at session start, then the preload projection
#     lists exactly the loaded entries and each is present in the
#     instruction — a missing entry is a diffable failure, not a vibe (E6)."
#   * The fold is WIRED into the session-start brief composition
#     (commission_session.confirm_and_launch) — asserted structurally so a
#     vacuously-unwired preload cannot pass.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_preload as cpl  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]

FEEDBACK_ENTRIES = [
    {"id": "fb-oranges", "text": "Always offer the parable-of-the-oranges "
                                 "framing before locking a sequencing call."},
    {"id": "fb-decks", "text": "Deck counts come from the filesystem, "
                               "never from memory."},
]


def _project(tmp_path):
    folder = tmp_path / "proj"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    cpl.feedback_ledger_path(folder).write_text(
        json.dumps({"entries": FEEDBACK_ENTRIES}), encoding="utf-8")
    return folder


def _rules(tmp_path, rules):
    p = tmp_path / "standing-rules.json"
    p.write_text(json.dumps({"schema_version": 1, "rules": rules}),
                 encoding="utf-8")
    return p


# ── E6: exactness — projection == instruction, both directions ──────────────

def test_projection_lists_exactly_the_loaded_entries_each_in_instruction(tmp_path):
    folder = _project(tmp_path)
    rules = _rules(tmp_path, [{"id": "gr-one", "rule": "Question last."}])
    out = cpl.compose_talk_instruction(folder, "BASE BRIEF.",
                                       rules_path=rules)
    proj = out["projection"]
    ids = [e["id"] for e in proj["loaded"]]
    assert ids == ["fb-oranges", "fb-decks", "gr-one"]
    assert proj["count"] == 3
    for e in proj["loaded"]:
        assert ("- [%s] %s" % (e["id"], e["text"])) in out["instruction"]
    verdict = cpl.verify_preload(out["instruction"], proj)
    assert verdict["exact"], verdict


def test_a_missing_entry_is_a_diffable_failure_not_a_vibe(tmp_path):
    folder = _project(tmp_path)
    rules = _rules(tmp_path, [{"id": "gr-one", "rule": "Question last."}])
    out = cpl.compose_talk_instruction(folder, "BASE", rules_path=rules)
    # Drop ONE loaded entry's line from the instruction — the diff NAMES it.
    line = "- [fb-decks] %s" % FEEDBACK_ENTRIES[1]["text"]
    broken = out["instruction"].replace(line, "")
    verdict = cpl.verify_preload(broken, out["projection"])
    assert not verdict["exact"]
    assert verdict["missing_from_instruction"] == ["fb-decks"]


def test_a_smuggled_unprojected_line_also_diffs(tmp_path):
    folder = _project(tmp_path)
    rules = _rules(tmp_path, [])
    out = cpl.compose_talk_instruction(folder, "BASE", rules_path=rules)
    smuggled = out["instruction"] + "- [never-loaded] invented preference\n"
    verdict = cpl.verify_preload(smuggled, out["projection"])
    assert not verdict["exact"]
    assert verdict["unprojected_in_instruction"] == [
        "- [never-loaded] invented preference"]


# ── deterministic load: dedupe, empty-but-valid, named unreadable ───────────

def test_project_feedback_outranks_a_same_id_global_rule(tmp_path):
    folder = _project(tmp_path)
    rules = _rules(tmp_path, [{"id": "fb-oranges", "rule": "a different, "
                                                          "later text"}])
    loaded = cpl.load_standing_preferences(folder, rules_path=rules)
    texts = {e["id"]: e for e in loaded["entries"]}
    assert texts["fb-oranges"]["source"] == cpl.SOURCE_FEEDBACK
    assert len(loaded["entries"]) == 2  # deduped, never both


def test_missing_ledger_is_empty_but_valid_and_still_exact(tmp_path):
    folder = tmp_path / "bare"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    rules = _rules(tmp_path, [{"id": "gr-one", "rule": "Question last."}])
    out = cpl.compose_talk_instruction(folder, "BASE", rules_path=rules)
    assert [e["id"] for e in out["projection"]["loaded"]] == ["gr-one"]
    assert out["projection"]["errors"] == []
    assert cpl.verify_preload(out["instruction"], out["projection"])["exact"]


def test_garbage_ledger_is_a_named_error_in_the_projection_never_silent(tmp_path):
    folder = tmp_path / "garbled"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    cpl.feedback_ledger_path(folder).write_text("{not json", encoding="utf-8")
    rules = _rules(tmp_path, [{"id": "gr-one", "rule": "Question last."}])
    out = cpl.compose_talk_instruction(folder, "BASE", rules_path=rules)
    errs = [e["error"] for e in out["projection"]["errors"]]
    assert cpl.ERROR_LEDGER_UNREADABLE in errs


# ── the committed global artifact + the sidecar projection persistence ──────

def test_committed_standing_rules_artifact_is_versioned_owned_and_loads():
    doc = json.loads((ANCHOR / "chamber" / "standing-rules.json")
                     .read_text(encoding="utf-8"))
    assert doc["schema_version"] == cpl.STANDING_RULES_SCHEMA_VERSION
    assert doc["owner_file"] == "chamber_preload.py"
    entries, errors = cpl.load_global_rules()
    assert errors == []
    assert {e["id"] for e in entries} >= {"compose-first", "answer-last"}
    for e in entries:
        assert e["source"] == cpl.SOURCE_GLOBAL


def test_preload_into_instruction_persists_the_projection_sidecar(tmp_path):
    folder = _project(tmp_path)
    rules = _rules(tmp_path, [])
    out = cpl.preload_into_instruction(folder, "BASE", rules_path=rules)
    persisted = cpl.load_projection(folder)
    assert persisted is not None
    assert persisted["loaded"] == out["projection"]["loaded"]


# ── the session-start WIRING (anti-vacuous: the fold is in the brief path) ──

def test_confirm_and_launch_composes_the_preload_into_the_brief():
    src = (ANCHOR / "commission_session.py").read_text(encoding="utf-8")
    assert "chamber_preload" in src, (
        "the E6 preload is not wired into commission_session at all")
    assert "preload_into_instruction" in src
    # The fold happens where the session-start brief composes: after
    # build_brief, before the launch.
    brief_at = src.index("directive_block + build_brief")
    launch_at = src.index("execute_confirmed_commission")
    wired_at = src.index("preload_into_instruction")
    assert brief_at < wired_at < launch_at, (
        "preload_into_instruction must fold into the brief BETWEEN "
        "composition and launch (the talk instruction at session start)")
