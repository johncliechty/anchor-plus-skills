"""Gate 5 / Wave 7 - Phase 4.1: Anchor pass-through reader and the
cross-language golden contract.

Executed by Ecgberht's orchestrator gate (`node scripts/run-all-tests.mjs`)
through the auth-on lane pytest bridge - this path is declared in Ecgberht's
scripts/wave-manifests.mjs, which is what makes the golden test reachable by
the gate.

The golden harness is Node-writes / Python-reads: this suite spawns Ecgberht's
scripts/kickoff-golden-fixture.mjs, which builds a confirmed v1 + open v2
lineage through the REAL engine seams and writes projection.json plus the
expected pass-through rendering. The append-only store is touched ONLY by that
harness (and by this test's no-derivation scramble); the reader under test
never opens it - an AST guard keeps the module read-only by construction.

Every hardening-gate obligation of this wave maps to a NAMED test in this file
(OBLIGATIONS below); the printed checklist is not the gate.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ANCHOR_ROOT = Path(__file__).resolve().parents[1]
if str(ANCHOR_ROOT) not in sys.path:
    sys.path.insert(0, str(ANCHOR_ROOT))

from steward_cockpit import kickoff_reader as kr

# The named bound on the fixture-builder spawn (boundedness: a hung Node build
# fails the test by name instead of hanging the gate).
NODE_TIMEOUT_SECONDS = 120

# obligation -> the named test that IS its gate
OBLIGATIONS = {
    "failure-table-unknown-vs-empty-separate-rows":
        "test_w7_t01_constants_and_failure_table",
    "failure-rows-unknown-empty-open-malformed-behavior":
        "test_w7_t02_unknown_empty_open_malformed_rows",
    "pass-through-rendering-template":
        "test_w7_t03_render_passthrough_template",
    "node-writes-python-reads-byte-equal-golden":
        "test_w7_t04_golden_node_writes_python_reads_byte_equal",
    "restart-paints-confirmed-plus-draft-not-applied":
        "test_w7_t05_restart_paints_confirmed_plus_draft_not_applied",
    "no-derivation-from-the-store":
        "test_w7_t06_no_derivation_from_store",
    "read-only-guards":
        "test_w7_t07_read_only_guards_ast",
    "obligations-are-tests":
        "test_w7_t08_obligations_are_tests",
}


def _ecgberht_root() -> Path:
    """Mirror of Ecgberht's resolveAnchorRoot, pointed the other way: the
    repo-conventional ``ECGBERHT_ROOT`` env override first, else the sibling
    checkout. No absolute host paths."""
    for var in ("ECGBERHT_ROOT", "ECGBERHT_REPO"):
        value = os.environ.get(var, "").strip()
        if value:
            return Path(value).resolve()
    return (ANCHOR_ROOT.parent / "Ecgberht").resolve()


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    """Run the Node-writes side once: a confirmed v1 + open v2 fixture built
    through the real Ecgberht engine, in a temp project dir (with a space)."""
    ecgberht = _ecgberht_root()
    script = ecgberht / "scripts" / "kickoff-golden-fixture.mjs"
    assert script.is_file(), (
        f"Ecgberht golden fixture script not found at {script} - set ECGBERHT_REPO"
    )
    node = os.environ.get("ECGBERHT_NODE") or shutil.which("node")
    assert node, "node not found on PATH (the orchestrator gate itself runs under Node)"
    target = tmp_path_factory.mktemp("kickoff-golden") / "proj ect"
    run = subprocess.run(
        [node, str(script), str(target)],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert run.returncode == 0, f"fixture build failed:\n{run.stdout}\n{run.stderr}"
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["ok"] is True, result
    return result


def _confirmed_doc(open_draft=None):
    """A minimal well-formed confirmed projection document, handcrafted for
    row-behavior tests (the golden test uses the real Node-written one)."""
    return {
        "schema": kr.KICKOFF_PROJECTION_SCHEMA,
        "state": "confirmed",
        "confirmed": {
            "version": 1,
            "proposal_hash": "a" * 64,
            "receipt_hash": "b" * 64,
            "rendered_prose": "Goal: ship the memo.\n",
            "who": "john",
            "confirmed_at": "2026-09-01T09:05:00Z",
        },
        "intent": {"kind": "intent_work_product"},
        "execution": {"kind": "execution"},
        "open_draft": open_draft,
    }


def test_w7_t01_constants_and_failure_table():
    assert kr.KICKOFF_PROJECTION_SCHEMA == "ecgberht-kickoff-projection-v0"
    assert kr.KICKOFF_PROJECTION_REL == ".ecgberht/kickoff/projection.json"
    assert kr.KICKOFF_PROJECTION_MAX_BYTES == 16 * 1024 * 1024
    assert kr.READER_GUARDS == {
        "read_only": True,
        "pass_through": True,
        "derives_from_store": False,
        "mutates": False,
        "executes": False,
    }
    # CONFIRMED / OPEN mirror Ecgberht's lifecycle codes - one vocabulary.
    assert kr.CODE_CONFIRMED == "KICKOFF_CONFIRMED"
    assert kr.CODE_OPEN == "KICKOFF_OPEN_UNCONFIRMED"

    table = kr.kickoff_reader_failure_table()
    assert [row["state"] for row in table] == [
        "confirmed", "open", "unknown", "empty-but-valid", "malformed",
    ]
    # unknown and empty are SEPARATE rows with distinct codes and text.
    codes = [row["status_code"] for row in table]
    assert len(set(codes)) == 5
    by_state = {row["state"]: row for row in table}
    assert by_state["unknown"]["status_code"] != by_state["empty-but-valid"]["status_code"]
    assert by_state["unknown"]["user_text"] != by_state["empty-but-valid"]["user_text"]
    for row in table:
        assert row["surface"] == "anchor_kickoff_reader"
        assert isinstance(row["user_text"], str) and row["user_text"]


def test_w7_t02_unknown_empty_open_malformed_rows(tmp_path):
    project = tmp_path / "proj ect"
    project.mkdir()

    # UNKNOWN: no source file at all - the reader refuses to guess and, being
    # pass-through, creates NOTHING by reading (not even a directory).
    row = kr.read_kickoff_projection(project)
    assert row["ok"] is False
    assert row["code"] == kr.CODE_UNKNOWN
    assert row["error"] == "projection_file_absent"
    assert row["status_code"] == row["code"]
    assert list(project.iterdir()) == [], "a read must create nothing"

    kickoff_dir = project / ".ecgberht" / "kickoff"
    kickoff_dir.mkdir(parents=True)
    projection = kickoff_dir / "projection.json"

    # EMPTY: zero bytes and whitespace-only are the SAME empty row - and a
    # DIFFERENT row from unknown.
    projection.write_bytes(b"")
    empty = kr.read_kickoff_projection(project)
    assert empty["ok"] is False and empty["code"] == kr.CODE_EMPTY
    projection.write_bytes(b" \n\t")
    assert kr.read_kickoff_projection(project)["code"] == kr.CODE_EMPTY
    assert empty["code"] != row["code"]

    # MALFORMED: unparseable bytes, an alien schema, an alien state, a
    # shape-invalid confirmed block - each by name.
    projection.write_bytes(b"{ not json")
    bad = kr.read_kickoff_projection(project)
    assert bad["ok"] is False and bad["code"] == kr.CODE_MALFORMED
    assert bad["error"] == "projection_json_unparseable"

    projection.write_text(json.dumps({"schema": "something-else"}), encoding="utf-8")
    assert kr.read_kickoff_projection(project)["error"] == "projection_schema_unknown"

    projection.write_text(
        json.dumps({"schema": kr.KICKOFF_PROJECTION_SCHEMA, "state": "weird"}),
        encoding="utf-8",
    )
    assert kr.read_kickoff_projection(project)["error"] == "projection_state_unknown"

    doc = _confirmed_doc()
    del doc["confirmed"]["receipt_hash"]
    projection.write_text(json.dumps(doc), encoding="utf-8")
    assert kr.read_kickoff_projection(project)["error"] == "projection_shape_invalid"

    # OPEN: schema matches, state is open - draft, not applied, its own row.
    projection.write_text(
        json.dumps({
            "schema": kr.KICKOFF_PROJECTION_SCHEMA,
            "state": "open",
            "open_draft": {"version": 1, "proposal_hash": "c" * 64,
                           "goal": "A draft goal", "applied": False},
        }),
        encoding="utf-8",
    )
    opened = kr.read_kickoff_projection(project)
    assert opened["ok"] is False and opened["code"] == kr.CODE_OPEN
    assert opened["open_draft"]["applied"] is False
    assert "draft, not" in opened["user_text"]

    # CONFIRMED: the ok row, pass-through.
    projection.write_text(json.dumps(_confirmed_doc()), encoding="utf-8")
    confirmed = kr.read_kickoff_projection(project)
    assert confirmed["ok"] is True and confirmed["code"] == kr.CODE_CONFIRMED
    assert confirmed["version"] == 1 and confirmed["open_draft"] is None

    # Boundedness: the named bound refuses by name (state honestly UNKNOWN -
    # the file was never read, so nothing is guessed about it).
    bounded = kr.read_kickoff_projection(project, max_bytes=16)
    assert bounded["ok"] is False and bounded["code"] == kr.CODE_UNKNOWN
    assert bounded["error"] == "projection_file_exceeds_bound"
    assert bounded["max_bytes"] == 16


def test_w7_t03_render_passthrough_template():
    # Without a draft: no draft lines at all.
    plain = kr.render_kickoff_passthrough(_confirmed_doc())
    assert plain.startswith("# Kickoff - confirmed v1\n")
    assert "Goal: ship the memo." in plain
    assert "Record sha256 " + "a" * 64 + "." in plain
    assert "Receipt sha256 " + "b" * 64 + "." in plain
    assert "Draft v" not in plain
    assert plain.endswith("\n")

    # With a draft: the non-authoritative draft-not-applied indication.
    doc = _confirmed_doc(open_draft={
        "version": 2, "proposal_hash": "c" * 64,
        "goal": "A different goal", "applied": False,
    })
    drafted = kr.render_kickoff_passthrough(doc)
    assert "Draft v2 (" + "c" * 64 + ") - draft, not applied: A different goal" in drafted
    assert "This draft is not authoritative" in drafted


def test_w7_t04_golden_node_writes_python_reads_byte_equal(golden):
    projection_path = Path(golden["projection_path"])
    raw = projection_path.read_bytes()

    row = kr.read_kickoff_projection_file(projection_path)
    assert row["ok"] is True, row
    assert row["version"] == 1 == golden["confirmed_version"]
    assert row["proposal_hash"] == golden["confirmed_proposal_hash"]
    assert row["receipt_hash"] == golden["receipt_hash"]
    assert row["open_draft"]["version"] == 2
    assert row["open_draft"]["applied"] is False

    # Cross-language canonical contract: parse in Python, re-serialize through
    # the mirrored canonical emitter, and the bytes equal what Node wrote
    # (the writer appends one trailing newline). Byte-equal, not "equivalent".
    assert kr.canonical_kickoff_bytes(row["projection"]) + b"\n" == raw

    # Golden rendering: Node derived the expected pass-through rendering from
    # the SAME file bytes; the Python rendering must be byte-equal to it.
    expected = Path(golden["expected_render_path"]).read_bytes()
    assert row["rendered"].encode("utf-8") == expected
    assert "draft, not applied" in row["rendered"]


def test_w7_t05_restart_paints_confirmed_plus_draft_not_applied(golden):
    projection_path = Path(golden["projection_path"])
    first = kr.read_kickoff_projection_file(projection_path)
    assert first["ok"] is True

    # A restart is a fresh module in a fresh process: reload, read again, and
    # the painted state is byte-identical - no session memory, disk only.
    reloaded = importlib.reload(kr)
    second = reloaded.read_kickoff_projection_file(projection_path)
    assert second["rendered"].encode("utf-8") == first["rendered"].encode("utf-8")
    assert second["projection"] == first["projection"]

    # The confirmed kickoff shows, plus the non-authoritative draft indication.
    assert "# Kickoff - confirmed v1" in second["rendered"]
    assert "draft, not applied" in second["rendered"]
    assert "This draft is not authoritative" in second["rendered"]


def test_w7_t06_no_derivation_from_store(golden):
    """Scramble, then delete, the append-only store: the reader's answer must
    not change by a byte, because it derives NOTHING from the store. (Only this
    golden suite ever touches that file - never the reader.)"""
    projection_path = Path(golden["projection_path"])
    store_path = Path(golden["events_path"])
    assert store_path.is_file(), "the harness built a real lineage"

    before = kr.read_kickoff_projection_file(projection_path)
    store_path.write_bytes(b"scrambled by the golden test - the reader must not care")
    scrambled = kr.read_kickoff_projection_file(projection_path)
    store_path.unlink()
    gone = kr.read_kickoff_projection_file(projection_path)

    assert before == scrambled == gone
    assert before["rendered"].encode("utf-8") == gone["rendered"].encode("utf-8")


# Calls that would let the reader edit, mutate, execute, or derive - forbidden
# in the module's AST. (str.replace/dict.update on locals are not world-writes
# and stay allowed; Path.replace/rename/write_* and every exec seam are not.)
_FORBIDDEN_CALLS = {
    "open", "exec", "eval", "compile", "__import__",
    "system", "popen", "spawn", "run", "Popen", "call", "check_call",
    "check_output",
    "remove", "unlink", "rmdir", "rename", "mkdir", "makedirs", "chmod",
    "touch", "write", "write_text", "write_bytes", "symlink_to",
    "hardlink_to", "rmtree", "link",
}
_ALLOWED_IMPORTS = {"__future__", "json", "pathlib"}


def test_w7_t07_read_only_guards_ast():
    source = Path(kr.__file__).read_text(encoding="utf-8")

    # Independent derivation is impossible by construction: the module never
    # names the store file (no 'events', no line-delimited extension) and
    # imports nothing that could reach it beyond the one projection path.
    assert "events" not in source
    assert "jsonl" not in source

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in _ALLOWED_IMPORTS, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in _ALLOWED_IMPORTS, node.module
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = None
            assert name not in _FORBIDDEN_CALLS, f"forbidden call in reader: {name}"

    assert kr.READER_GUARDS["read_only"] is True
    assert kr.READER_GUARDS["derives_from_store"] is False
    assert kr.READER_GUARDS["executes"] is False


def test_w7_t08_obligations_are_tests():
    names = set(globals())
    for obligation, test_name in OBLIGATIONS.items():
        assert test_name in names and callable(globals()[test_name]), (
            f"obligation '{obligation}' has no test named {test_name}"
        )
