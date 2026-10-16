"""Gate 5 / Wave 8 - Phase 4.2: cockpit GET exposure, inventory truth, and
manifest coverage.

Executed by Ecgberht's orchestrator gate (`node scripts/run-all-tests.mjs`)
through the auth-on lane pytest bridge - this path is declared in Ecgberht's
scripts/wave-manifests.mjs, which is what makes these tests reachable by the
gate.

What this suite proves, per the frozen plan's Wave 8 contract:

* the cockpit exposes kickoff VIEWING only - one read-model
  ``GET /api/ecgberht/kickoff_show?pid=&effort=`` route, resolved through the
  steward cockpit's existing ``_effort_dir`` guard (unknown effort refused),
  with distinct unknown / empty response-state rows and no mutation path;
* the chamber-routes inventory tells the truth about the three kickoff verbs:
  show has a real GET exposure; confirm and replay are declared
  conversational/bridge-CLI with ZERO ``not_exposed`` rows - and hermetic
  bridge-CLI tests here actually DRIVE both verbs against a real lineage
  (built through the real Ecgberht engine seams, never hand-written bytes);
* every new Anchor kickoff file carries a ``dist_manifest`` row.

No HTTP server is booted and no socket is opened: the endpoint is exercised at
the real handler seam (anchor_gui's route-table handler with the project
registry seam pointed at a temp folder). The only subprocesses are the Node
fixture builder and the seal-chamber bridge CLI - the two verbs under proof.

Every hardening-gate obligation of this wave maps to a NAMED test in this file
(OBLIGATIONS below); the printed checklist is not the gate.
"""

from __future__ import annotations

import ast
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

# The named bound on every Node spawn (boundedness: a hung build/bridge fails
# the test by name instead of hanging the gate).
NODE_TIMEOUT_SECONDS = 120

# obligation -> the named test that IS its gate
OBLIGATIONS = {
    "cockpit-exposes-kickoff-show-only":
        "test_w8_t01_route_table_exposes_kickoff_show_only",
    "unknown-effort-refused-through-effort-dir-guard":
        "test_w8_t02_unknown_effort_refused",
    "read-model-rows-confirmed-and-open":
        "test_w8_t03_confirmed_and_open_read_model",
    "failure-table-unknown-vs-empty-separate-rows":
        "test_w8_t04_unknown_empty_malformed_distinct",
    "no-mutation-path-invoked":
        "test_w8_t05_no_mutation_tree_and_ast",
    "handler-wired-through-real-registry-seam":
        "test_w8_t06_handler_wiring",
    "bridge-cli-drives-kickoff-confirm":
        "test_w8_t07_bridge_cli_confirm",
    "bridge-cli-drives-kickoff-replay":
        "test_w8_t08_bridge_cli_replay",
    "inventory-truth-zero-kickoff-not-exposed":
        "test_w8_t09_inventory_truth",
    "dist-manifest-rows-for-new-anchor-files":
        "test_w8_t10_dist_manifest_rows",
    "obligations-are-tests":
        "test_w8_t11_obligations_are_tests",
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


def _run_bridge(project_dir: Path, *argv: str) -> dict:
    """Drive the REAL seal-chamber bridge CLI (a fresh Node process, argv
    flags, JSON on stdout) - the exact caller class the inventory declares.
    Hermetic: the confirm verb's best-effort portfolio-ledger note is pointed
    INSIDE the temp project via its own env seam, never at the host home."""
    bridge = _ecgberht_root() / "scripts" / "seal-chamber-bridge.mjs"
    assert bridge.is_file(), f"bridge not found at {bridge} - set ECGBERHT_REPO"
    env = dict(os.environ)
    env["ECGBERHT_PORTFOLIO_LEDGER"] = str(
        Path(project_dir).parent / "portfolio-ledger.json")
    run = subprocess.run(
        [_node(), str(bridge), "--project", str(project_dir), *argv],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
        env=env,
    )
    assert run.stdout.strip(), f"bridge wrote no stdout:\n{run.stderr}"
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def lineage(tmp_path_factory):
    """A real kickoff lineage confirmed THROUGH the bridge CLI.

    Step 1: Ecgberht's golden fixture builds confirmed v1 + open v2 through the
    real engine seams. Step 2: the seal-chamber bridge CLI - the declared
    conversational/bridge-CLI exposure - confirms the open v2 draft by hash.
    A minimal Face file makes the project root a discoverable effort so the
    cockpit route can read the same folder.
    """
    ecgberht = _ecgberht_root()
    script = ecgberht / "scripts" / "kickoff-golden-fixture.mjs"
    assert script.is_file(), (
        f"golden fixture script not found at {script} - set ECGBERHT_REPO"
    )
    project = tmp_path_factory.mktemp("kickoff-cli") / "proj ect"
    build = subprocess.run(
        [_node(), str(script), str(project)],
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert build.returncode == 0, (
        f"fixture build failed:\n{build.stdout}\n{build.stderr}"
    )
    golden = json.loads(build.stdout.strip().splitlines()[-1])
    assert golden["ok"] is True, golden
    assert golden["open_draft"]["version"] == 2

    (project / "ECGBERHT.md").write_text(
        "# Ecgberht - Face (campaign memory)\n\n## North star\n\nW8 canary.\n",
        encoding="utf-8",
    )

    confirm = _run_bridge(
        project,
        "--kickoff-confirm",
        json.dumps({
            "proposal_hash": golden["open_draft"]["proposal_hash"],
            "who": "john",
            "client_event_id": "w8-cli-confirm",
            "at": "2026-09-01T09:20:00Z",
        }),
    )
    return {"project": project, "golden": golden, "confirm": confirm}


def _confirmed_doc(open_draft=None):
    """A minimal well-formed confirmed projection document (w7's shape)."""
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


def _project_with_effort(tmp_path, rel="eff one"):
    """A steward project folder with ONE discoverable effort (Face file)."""
    proot = tmp_path / "camp aign"
    edir = proot / rel
    edir.mkdir(parents=True)
    (edir / "ECGBERHT.md").write_text("# Face\n", encoding="utf-8")
    return proot, edir


def _tree_snapshot(root: Path):
    """Every path + size under root - the no-mutation witness."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        out[str(p.relative_to(root))] = p.stat().st_size if p.is_file() else -1
    return out


# ── The exposure: show only ──────────────────────────────────────────────────

def test_w8_t01_route_table_exposes_kickoff_show_only():
    """ONE kickoff route exists in the whole route table: the read-model GET.
    No kickoff POST (no network mutation path) - the cockpit shows, only."""
    import route_table
    kickoff_routes = [r for r in route_table.ROUTES if "kickoff" in r.pattern]
    assert len(kickoff_routes) == 1, kickoff_routes
    row = kickoff_routes[0]
    assert row.method == "GET"
    assert row.pattern == "/api/ecgberht/kickoff_show"
    assert row.auth == "token"
    assert row.migrated is True
    assert row.handler == "handle_ecgberht_kickoff_show"


def test_w8_t02_unknown_effort_refused(tmp_path):
    """The _effort_dir guard rides in front of every read: an effort the
    discovery does not know - including a Face-less project root - answers 404
    with the guard's OWN row, and nothing on disk changes."""
    proot, _ = _project_with_effort(tmp_path)
    before = _tree_snapshot(proot)

    out, status = ksr.kickoff_show(str(proot), "no such effort")
    assert status == 404
    assert out["ok"] is False
    assert out["error"] == "unknown effort"
    assert out["code"] == ksr.CODE_UNKNOWN_EFFORT
    assert out["surface"] == "kickoff_show"

    # The project ROOT carries no Face here, so rel "" is equally unknown -
    # the guard refuses it too (discovery-truth, not path-truth).
    root_out, root_status = ksr.kickoff_show(str(proot), "")
    assert root_status == 404
    assert root_out["code"] == ksr.CODE_UNKNOWN_EFFORT

    # Distinct from the reader's source-UNKNOWN row (known effort, no file).
    known_out, known_status = ksr.kickoff_show(str(proot), "eff one")
    assert known_status == 404
    assert known_out["code"] == kr.CODE_UNKNOWN
    assert known_out["code"] != ksr.CODE_UNKNOWN_EFFORT

    assert _tree_snapshot(proot) == before, "a refusal must write nothing"


def test_w8_t03_confirmed_and_open_read_model(tmp_path):
    """A confirmed or open kickoff answers 200 with ONLY read-model data - the
    Wave 7 reader's row passed through, effort echoed, nothing else."""
    proot, edir = _project_with_effort(tmp_path)
    kdir = edir / ".ecgberht" / "kickoff"
    kdir.mkdir(parents=True)
    projection = kdir / "projection.json"

    projection.write_text(json.dumps(_confirmed_doc()), encoding="utf-8")
    out, status = ksr.kickoff_show(str(proot), "eff one")
    assert status == 200
    assert out["ok"] is True and out["code"] == kr.CODE_CONFIRMED
    assert out["version"] == 1
    assert out["surface"] == "kickoff_show" and out["effort"] == "eff one"
    assert out["rendered"].startswith("# Kickoff - confirmed v1")
    assert out["read_only"] is True and out["pass_through"] is True
    assert out["projection"] == _confirmed_doc()

    projection.write_text(
        json.dumps({
            "schema": kr.KICKOFF_PROJECTION_SCHEMA,
            "state": "open",
            "open_draft": {"version": 1, "proposal_hash": "c" * 64,
                           "goal": "A draft goal", "applied": False},
        }),
        encoding="utf-8",
    )
    opened, open_status = ksr.kickoff_show(str(proot), "eff one")
    assert open_status == 200
    assert opened["ok"] is False and opened["code"] == kr.CODE_OPEN
    assert opened["open_draft"]["applied"] is False
    assert "draft, not" in opened["user_text"]


def test_w8_t04_unknown_empty_malformed_distinct(tmp_path):
    """unknown and empty are SEPARATE response states - distinct codes, texts
    AND HTTP statuses - and malformed input is refused, never guessed."""
    proot, edir = _project_with_effort(tmp_path)
    kdir = edir / ".ecgberht" / "kickoff"
    kdir.mkdir(parents=True)
    projection = kdir / "projection.json"

    unknown_out, unknown_status = ksr.kickoff_show(str(proot), "eff one")
    assert unknown_status == 404 and unknown_out["code"] == kr.CODE_UNKNOWN

    projection.write_bytes(b"")
    empty_out, empty_status = ksr.kickoff_show(str(proot), "eff one")
    assert empty_status == 200 and empty_out["code"] == kr.CODE_EMPTY
    assert empty_out["code"] != unknown_out["code"]
    assert empty_out["user_text"] != unknown_out["user_text"]
    assert empty_status != unknown_status

    projection.write_bytes(b"{ not json")
    bad_out, bad_status = ksr.kickoff_show(str(proot), "eff one")
    assert bad_status == 502 and bad_out["code"] == kr.CODE_MALFORMED

    # The surface's failure table: the guard row plus the reader's five, each
    # with its HTTP status; the three refusal-ish rows stay separate.
    table = ksr.kickoff_show_failure_table()
    assert [row["state"] for row in table] == [
        "unknown-effort", "confirmed", "open", "unknown", "empty-but-valid",
        "malformed",
    ]
    by_state = {row["state"]: row for row in table}
    assert len({row["status_code"] for row in table}) == 6
    assert by_state["unknown-effort"]["http_status"] == 404
    assert by_state["unknown"]["http_status"] == 404
    assert by_state["empty-but-valid"]["http_status"] == 200
    assert by_state["malformed"]["http_status"] == 502
    for row in table:
        assert row["surface"] == "kickoff_show"
        assert isinstance(row["user_text"], str) and row["user_text"]


def test_w8_t05_no_mutation_tree_and_ast(tmp_path):
    """No mutation path is invoked: every response state leaves the tree
    byte-for-byte alone, and the route module's AST contains no write, spawn,
    or exec seam at all (read-only by construction, like the w7 reader)."""
    proot, edir = _project_with_effort(tmp_path)
    kdir = edir / ".ecgberht" / "kickoff"
    kdir.mkdir(parents=True)
    (kdir / "projection.json").write_text(
        json.dumps(_confirmed_doc()), encoding="utf-8")
    before = _tree_snapshot(proot)
    for rel in ("eff one", "no such effort", ""):
        ksr.kickoff_show(str(proot), rel)
    assert _tree_snapshot(proot) == before

    source = Path(ksr.__file__).read_text(encoding="utf-8")
    forbidden = {
        "open", "exec", "eval", "compile", "__import__",
        "system", "popen", "spawn", "run", "Popen", "call", "check_call",
        "check_output",
        "remove", "unlink", "rmdir", "rename", "mkdir", "makedirs", "chmod",
        "touch", "write", "write_text", "write_bytes", "symlink_to",
        "hardlink_to", "rmtree", "link",
    }
    allowed_imports = {"__future__", "steward_cockpit"}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed_imports, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] in allowed_imports, \
                node.module
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = None
            assert name not in forbidden, f"forbidden call in route: {name}"

    assert ksr.ROUTE_GUARDS["read_only"] is True
    assert ksr.ROUTE_GUARDS["mutates"] is False
    assert ksr.ROUTE_GUARDS["executes"] is False
    assert ksr.ROUTE_GUARDS["spawns_bridge"] is False


def test_w8_t06_handler_wiring(tmp_path, monkeypatch):
    """The REAL anchor_gui handler serves the route: registered under the
    route-table name, resolving pid through the project registry seam and the
    effort through the guard - unknown pid 404, unknown effort 404, confirmed
    200 with the read-model row."""
    import anchor_gui

    assert anchor_gui._MIGRATED_HANDLERS["handle_ecgberht_kickoff_show"] \
        is anchor_gui.handle_ecgberht_kickoff_show

    proot, edir = _project_with_effort(tmp_path)
    kdir = edir / ".ecgberht" / "kickoff"
    kdir.mkdir(parents=True)
    (kdir / "projection.json").write_text(
        json.dumps(_confirmed_doc()), encoding="utf-8")

    def fake_get_project(pid):
        return {"folder_path": str(proot)} if pid == "p1" else None

    monkeypatch.setattr(anchor_gui._rnd, "get_project", fake_get_project)

    class StubHandler:
        def __init__(self, path):
            self.path = path
            self.sent = None

        def _send_json(self, obj, code=200):
            self.sent = (obj, code)

    def get(path):
        h = StubHandler(path)
        anchor_gui.handle_ecgberht_kickoff_show(h, path, None)
        return h.sent

    obj, code = get("/api/ecgberht/kickoff_show?pid=nope&effort=eff%20one")
    assert code == 404 and obj["error"] == "Unknown project"

    obj, code = get("/api/ecgberht/kickoff_show?pid=p1&effort=missing")
    assert code == 404 and obj["code"] == ksr.CODE_UNKNOWN_EFFORT

    before = _tree_snapshot(proot)
    obj, code = get("/api/ecgberht/kickoff_show?pid=p1&effort=eff%20one")
    assert code == 200
    assert obj["ok"] is True and obj["code"] == kr.CODE_CONFIRMED
    assert obj["surface"] == "kickoff_show" and obj["effort"] == "eff one"
    assert _tree_snapshot(proot) == before, "the GET must mutate nothing"


# ── The two non-HTTP verbs, driven through the bridge CLI ────────────────────

def test_w8_t07_bridge_cli_confirm(lineage):
    """kickoff-confirm IS reachable exactly as declared: the bridge CLI
    confirmed the open v2 draft by hash against the real store lineage, and
    the cockpit's read-model now shows confirmed v2 with no draft left."""
    res = lineage["confirm"]
    assert res["ok"] is True, res
    assert res["mode"] == "kickoff-confirm"
    assert res["hash_bound"] is True
    assert res["lane"] == "store"
    assert res["projection_written"] is True

    out, status = ksr.kickoff_show(str(lineage["project"]), "")
    assert status == 200
    assert out["ok"] is True and out["code"] == kr.CODE_CONFIRMED
    assert out["version"] == 2
    assert out["proposal_hash"] == lineage["golden"]["open_draft"]["proposal_hash"]
    assert out["open_draft"] is None


def test_w8_t08_bridge_cli_replay(lineage):
    """kickoff-replay IS reachable exactly as declared: the bridge CLI
    re-projects the CONFIRMED kickoff (the v2 bundle the CLI confirm landed)
    from lineage truth - writing projections, never the lineage."""
    events_before = Path(lineage["golden"]["events_path"]).read_bytes()
    res = _run_bridge(lineage["project"], "--kickoff-replay",
                      json.dumps({"who": "john"}))
    assert res["ok"] is True, res
    assert res["mode"] == "kickoff-replay"
    assert res["phase"] == "replayed"
    assert res["authoritative"] is True
    assert res["proposal"]["goal"] == lineage["golden"]["open_draft"]["goal"]
    assert Path(lineage["golden"]["events_path"]).read_bytes() == \
        events_before, "replay must never write the lineage"


# ── Inventory truth and manifest coverage ────────────────────────────────────

def test_w8_t09_inventory_truth():
    """The living inventory declares the kickoff verbs truthfully: show has a
    real GET exposure matching the route table; confirm and replay carry the
    conversational/bridge-CLI declaration naming THIS file; ZERO kickoff
    not_exposed rows remain; the artifact still validates."""
    import chamber_enforcement as ce
    import route_table

    inv = ce.load_routes_inventory()
    assert ce.validate_routes_inventory(inv) == []

    verbs = {v["verb"]: v for v in
             inv["ecgberht_bridges"]["seal-chamber-bridge"]["verbs"]}
    show = verbs["kickoff-show"]
    assert show["exposed_via"] == ["GET /api/ecgberht/kickoff_show"]
    assert show["state_changing"] is False

    route = next(r for r in route_table.ROUTES
                 if r.pattern == "/api/ecgberht/kickoff_show")
    assert "%s %s" % (route.method, route.pattern) in show["exposed_via"]

    for verb in ("kickoff-confirm", "kickoff-replay"):
        row = verbs[verb]
        assert row["exposed_via"] == [], (verb, "zero network exposure")
        conv = row["conversational_cli"]
        assert conv["declaration"] == "conversational/bridge-cli"
        assert conv["proven_by"] == "tests/" + Path(__file__).name
        assert "--" + verb in conv["cli"]

    for verb, row in verbs.items():
        if verb.startswith("kickoff"):
            assert "not_exposed" not in row, (
                "kickoff verb %r still carries a not_exposed exception" % verb)


def test_w8_t10_dist_manifest_rows():
    """Every new Anchor kickoff file is distributable: the Gate 5 reader (W7)
    and the W8 route module each carry a dist_manifest row, and every
    manifest kickoff row points at a file that exists."""
    manifest = (ANCHOR_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    rows = [line.strip() for line in manifest.splitlines()
            if line.strip() and not line.strip().startswith("#")]
    assert "steward_cockpit/kickoff_reader.py" in rows
    assert "steward_cockpit/kickoff_show_route.py" in rows
    for row in rows:
        if "kickoff" in row:
            assert (ANCHOR_ROOT / row).is_file(), row


def test_w8_t11_obligations_are_tests():
    names = set(globals())
    for obligation, test_name in OBLIGATIONS.items():
        assert test_name in names and callable(globals()[test_name]), (
            f"obligation '{obligation}' has no test named {test_name}"
        )
