"""Gate 5 / Wave 9 - Phase 4.3: the integrated Ecgberht-to-Anchor hermetic
canary - open and confirmed restart rendering, and the final gate composition.

Executed by Ecgberht's orchestrator gate (`node scripts/run-all-tests.mjs`)
through the auth-on lane pytest bridge - this path is declared in Ecgberht's
scripts/wave-manifests.mjs, which is what makes this canary reachable by the
one gate.

The Node-writes side is Ecgberht's LOOK STAGING (scripts/kickoff-look-staging.mjs):
the same CLI John's look uses stages the five synthetic efforts through the real
engine seams - document, software, research, simple confirmed (research CORRECTED
once, to v2), ambiguous left OPEN and persisted through the Wave 9 open-state
read-model seam. This suite then plays Anchor's restart: a fresh module import
paints each persisted state FROM DISK - the confirmed kickoffs, and the open
draft as "draft, not applied" - with no session-memory dependency, both at the
Wave 7 reader seam and through the Wave 8 cockpit route.

The final machine-gate composition rides here too: the wave-manifest declares
waves 7, 8, and 9 so code + manifest + inventory + reader-golden all reach the
orchestrator gate; the dist_manifest kickoff rows still point at real files;
the route table still exposes kickoff VIEWING only; and the canonical
cross-language contract holds byte-for-byte on every staged projection.

Every hardening-gate obligation of this wave maps to a NAMED test in this file
(OBLIGATIONS below); the printed checklist is not the gate. What no test here
counts - deliberately - is John's restart, his 30-second look, and his burden
word: those are recorded human steps, and the wave ends in a HALT for them.
"""

from __future__ import annotations

import hashlib
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
from steward_cockpit import kickoff_show_route as ksr

# The named bound on the Node staging spawn (boundedness: a hung build fails
# the test by name instead of hanging the gate).
NODE_TIMEOUT_SECONDS = 180

# The five efforts as the frozen plan stages them (mirrors Ecgberht's
# KICKOFF_LOOK_EFFORT_PLAN; the staged summary is asserted against this).
EFFORT_PLAN = (
    {"key": "document", "dir": "document effort", "state": "confirmed", "corrected": False},
    {"key": "software", "dir": "software effort", "state": "confirmed", "corrected": False},
    {"key": "research", "dir": "research effort", "state": "confirmed", "corrected": True},
    {"key": "simple", "dir": "simple effort", "state": "confirmed", "corrected": False},
    {"key": "ambiguous", "dir": "ambiguous effort", "state": "open", "corrected": False},
)

# obligation -> the named test that IS its gate
OBLIGATIONS = {
    "five-efforts-staged-one-corrected-one-open-sentinel-clean":
        "test_w9_t01_staged_five_efforts",
    "restart-paints-open-from-disk":
        "test_w9_t02_restart_paints_open",
    "restart-paints-confirmed-from-disk":
        "test_w9_t03_restart_paints_confirmed",
    "cockpit-get-paints-both-states-read-only":
        "test_w9_t04_cockpit_get_both_states",
    "cross-language-canonical-byte-equality":
        "test_w9_t05_canonical_byte_equality",
    "gate-composition-manifest-inventory-golden-declared":
        "test_w9_t06_gate_composition",
    "repeat-invocation-and-no-execution":
        "test_w9_t07_repeat_invocation_no_execution",
    "obligations-are-tests":
        "test_w9_t08_obligations_are_tests",
}


def _ecgberht_root() -> Path:
    """The sibling Ecgberht engine root: env override first, else the sibling
    checkout beside this Anchor tree. No absolute host paths."""
    for var in ("ECGBERHT_ROOT", "ECGBERHT_REPO"):
        value = os.environ.get(var, "").strip()
        if value:
            return Path(value).resolve()
    return (ANCHOR_ROOT.parent / "Ecgberht").resolve()


def _node() -> str:
    node = os.environ.get("ECGBERHT_NODE") or shutil.which("node")
    assert node, "node not found on PATH (the orchestrator gate runs under Node)"
    return node


def _run_staging(target: Path) -> dict:
    """Spawn the REAL staging CLI - the exact command John's look uses."""
    script = _ecgberht_root() / "scripts" / "kickoff-look-staging.mjs"
    assert script.is_file(), (
        f"staging script not found at {script} - set ECGBERHT_REPO"
    )
    run = subprocess.run(
        [_node(), str(script), str(target)],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert run.returncode == 0, f"staging failed:\n{run.stdout}\n{run.stderr}"
    return json.loads(run.stdout.strip().splitlines()[-1])


def _tree_hashes(root: Path) -> dict:
    """Every file under root as rel-path -> sha256: the byte-level witness."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    """Stage the five efforts ONCE into a temp root (with a space) through the
    real CLI; every test reads the same persisted states, as a restart would."""
    target = tmp_path_factory.mktemp("kickoff-canary") / "look root"
    result = _run_staging(target)
    assert result["ok"] is True, result
    assert result["already"] is False
    return {"root": target, "result": result, "summary": result["summary"]}


def _row(staged, key):
    return next(r for r in staged["summary"]["staged"] if r["key"] == key)


def test_w9_t01_staged_five_efforts(staged):
    """The five fixtures stand staged as the plan names them: one corrected
    once (research, confirmed v2 over a real v1), one OPEN (ambiguous), the
    rest confirmed v1 - with the leak sentinel's recorded word that nothing
    executed and the handoff state at ready-for-first-slice."""
    summary = staged["summary"]
    assert [r["key"] for r in summary["staged"]] == [p["key"] for p in EFFORT_PLAN]
    assert summary["handoff_state"] == "ready-for-first-slice"
    assert summary["execution_started"] is False

    for plan in EFFORT_PLAN:
        row = _row(staged, plan["key"])
        assert row["state"] == plan["state"], plan["key"]
        assert row["corrected"] is plan["corrected"], plan["key"]
        assert (staged["root"] / plan["dir"] / "ECGBERHT.md").is_file(), plan["key"]

    research = _row(staged, "research")
    assert research["version"] == 2
    assert research["prior_confirmed_hash"], "the correction supersedes a real v1"
    ambiguous = _row(staged, "ambiguous")
    assert ambiguous["version"] == 1
    assert ambiguous["receipt_hash"] is None
    assert ambiguous["ready_for_first_slice"] is False
    for key in ("document", "software", "simple"):
        row = _row(staged, key)
        assert row["version"] == 1 and row["ready_for_first_slice"] is True
        assert row["first_slice_id"], key

    # The RECORDED handoff state carries the sentinel's own row: zero calls on
    # every execution seam, zero files outside the staged paths.
    sentinel = summary["leak_sentinel"]
    assert sentinel["code"] == "EXECUTION_LEAK_NONE"
    assert sentinel["execution_calls"] == 0
    assert sentinel["outside_allowed"] == 0
    assert set(sentinel["calls_by_seam"]) == {
        "commission", "draft", "model_run", "specialist"}
    assert all(count == 0 for count in sentinel["calls_by_seam"].values())

    # The two visual claims for John ride with the staging, by name.
    assert [c["id"] for c in summary["visual_claims"]] == [
        "thirty-second-test", "restart-paints-open-and-confirmed"]
    assert [s["id"] for s in summary["human_steps"]] == [
        "single-elevated-restart", "thirty-second-test", "burden-word"]


def test_w9_t02_restart_paints_open(staged):
    """Given an OPEN proposal, a restarted Anchor paints it from disk: the
    persisted open-state projection answers the OPEN row - draft, not applied -
    identically before and after a module reload (no session memory)."""
    ambiguous = _row(staged, "ambiguous")
    effort_dir = staged["root"] / ambiguous["dir"]

    first = kr.read_kickoff_projection(effort_dir)
    assert first["ok"] is False and first["code"] == kr.CODE_OPEN
    assert first["open_draft"]["version"] == 1
    assert first["open_draft"]["proposal_hash"] == ambiguous["proposal_hash"]
    assert first["open_draft"]["goal"] == ambiguous["goal"]
    assert first["open_draft"]["applied"] is False
    assert "draft, not" in first["user_text"]

    # THE RESTART: a fresh module is a fresh process's worth of state.
    reloaded = importlib.reload(kr)
    second = reloaded.read_kickoff_projection(effort_dir)
    assert second == first, "the paint comes from disk, not from session memory"


def test_w9_t03_restart_paints_confirmed(staged):
    """Given a separately confirmed kickoff, a restarted Anchor paints the same
    confirmed state from disk - including the corrected v2 with its prior
    lineage - byte-identically across a module reload."""
    for key, version in (("document", 1), ("research", 2)):
        row = _row(staged, key)
        effort_dir = staged["root"] / row["dir"]
        first = kr.read_kickoff_projection(effort_dir)
        assert first["ok"] is True, (key, first)
        assert first["code"] == kr.CODE_CONFIRMED
        assert first["version"] == version
        assert first["proposal_hash"] == row["proposal_hash"]
        assert first["rendered"].startswith(f"# Kickoff - confirmed v{version}")
        assert first["open_draft"] is None, "nothing rides beside the look's confirmed states"

        prior = first["projection"]["confirmed"]["prior_confirmed_hash"]
        if key == "research":
            assert prior == row["prior_confirmed_hash"] and prior, \
                "the one correction carries its v1 lineage"
        else:
            assert prior is None

        reloaded = importlib.reload(kr)
        second = reloaded.read_kickoff_projection(effort_dir)
        assert second["rendered"].encode("utf-8") == first["rendered"].encode("utf-8")
        assert second["projection"] == first["projection"]


def test_w9_t04_cockpit_get_both_states(staged):
    """The cockpit route paints BOTH persisted states read-only: confirmed 200,
    open 200 (draft, not applied), unknown effort refused 404 through the
    _effort_dir guard - and no read changes a byte on disk."""
    root = str(staged["root"])
    before = _tree_hashes(staged["root"])

    confirmed, status = ksr.kickoff_show(root, "document effort")
    assert status == 200
    assert confirmed["ok"] is True and confirmed["code"] == kr.CODE_CONFIRMED
    assert confirmed["surface"] == "kickoff_show"
    assert confirmed["effort"] == "document effort"

    opened, status = ksr.kickoff_show(root, "ambiguous effort")
    assert status == 200
    assert opened["ok"] is False and opened["code"] == kr.CODE_OPEN
    assert opened["open_draft"]["applied"] is False

    unknown, status = ksr.kickoff_show(root, "no such effort")
    assert status == 404
    assert unknown["code"] == ksr.CODE_UNKNOWN_EFFORT

    assert _tree_hashes(staged["root"]) == before, "a canary read writes nothing"


def test_w9_t05_canonical_byte_equality(staged):
    """The cross-language canonical contract holds on every staged projection:
    parse what Node wrote, re-serialize through the mirrored Python emitter,
    and the bytes equal the file exactly (plus the writer's trailing newline)."""
    for plan in EFFORT_PLAN:
        projection_path = (
            staged["root"] / plan["dir"] / kr.KICKOFF_PROJECTION_REL)
        raw = projection_path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
        assert kr.canonical_kickoff_bytes(doc) + b"\n" == raw, plan["key"]


def test_w9_t06_gate_composition(staged):
    """The final gate reaches everything: waves 7, 8, and 9 declared in
    Ecgberht's wave-manifests (code + reader-golden + inventory + manifest all
    ride the one orchestrator gate); the dist_manifest kickoff rows point at
    real files; the route table still exposes kickoff VIEWING only."""
    ecgberht = _ecgberht_root()
    manifests = (ecgberht / "scripts" / "wave-manifests.mjs").read_text(
        encoding="utf-8")
    for declared in (
        "tests/test_kickoff_reader_w7.py",
        "tests/test_kickoff_cockpit_w8.py",
        "tests/test_kickoff_canary_w9.py",
    ):
        assert declared in manifests, f"{declared} not declared to the gate"
        assert (ANCHOR_ROOT / declared).is_file(), declared

    # The reader-golden and staging runners the declarations lean on exist.
    assert (ecgberht / "scripts" / "kickoff-golden-fixture.mjs").is_file()
    assert (ecgberht / "scripts" / "kickoff-look-staging.mjs").is_file()

    # Manifest truth: the two Anchor kickoff files stay distributable; this
    # wave ships no new Anchor source (a test is not a distributable).
    manifest = (ANCHOR_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    rows = [line.strip() for line in manifest.splitlines()
            if line.strip() and not line.strip().startswith("#")]
    assert "steward_cockpit/kickoff_reader.py" in rows
    assert "steward_cockpit/kickoff_show_route.py" in rows
    for row in rows:
        if "kickoff" in row:
            assert (ANCHOR_ROOT / row).is_file(), row

    # Inventory truth still stands: ONE kickoff route, GET, show only.
    import route_table
    kickoff_routes = [r for r in route_table.ROUTES if "kickoff" in r.pattern]
    assert len(kickoff_routes) == 1
    assert kickoff_routes[0].method == "GET"
    assert kickoff_routes[0].pattern == "/api/ecgberht/kickoff_show"


def test_w9_t07_repeat_invocation_no_execution(staged):
    """Re-running the staging CLI on the staged root answers `already` and
    moves NOTHING - the idempotence John's look depends on (he can re-run the
    command without fear), witnessed byte-for-byte."""
    before = _tree_hashes(staged["root"])
    again = _run_staging(staged["root"])
    assert again["ok"] is True
    assert again["already"] is True
    assert again["staged_count"] == 5
    assert _tree_hashes(staged["root"]) == before, "already moves nothing"


def test_w9_t08_obligations_are_tests():
    names = set(globals())
    for obligation, test_name in OBLIGATIONS.items():
        assert test_name in names and callable(globals()[test_name]), (
            f"obligation '{obligation}' has no test named {test_name}"
        )
