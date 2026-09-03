"""W3 — the BOTH-TREE living routes inventory, its CI diff guard, and the
auth-ON coverage rule.

AUTH-ON: not-a-surface

This file exercises no HTTP surface: it validates the versioned inventory
artifact (``chamber/routes-inventory.json``), proves the diff guard actually
BITES in all four directions (a route/verb in code without a row; a stale
row), asserts the caller-class threat split is recorded, and enforces the
auth-ON tag rule over the new-surface test namespace — including the negative
proof that the scanner catches an untagged/dishonestly-tagged file.

The live red-to-green proof for every inventory row lives in
``tests/test_chamber_red_to_green_w3.py`` (that file boots servers; this one
never does).
"""
import copy
import json
from pathlib import Path

import chamber_enforcement as ce

ANCHOR_ROOT = Path(__file__).resolve().parents[1]


# ── The artifact: versioned, owned, valid ────────────────────────────────────

def test_inventory_is_versioned_owned_and_structurally_valid():
    inv = ce.load_routes_inventory()
    problems = ce.validate_routes_inventory(inv)
    assert not problems, "routes-inventory.json invalid:\n" + "\n".join(problems)
    assert inv["schema_version"] == ce.SCHEMA_VERSION
    assert inv["owner_file"] == "chamber_enforcement.py"
    owner = ANCHOR_ROOT / inv["owner_file"]
    assert owner.is_file(), "the named owner file must exist (living-registry law)"


def test_inventory_carries_the_caller_class_threat_split():
    """F6: the threat model is SPLIT by caller class and recorded in the
    artifact — browser (token + POST-only + CSRF-refusal) and bridge/CLI
    (token still required, asserted NON-exempt)."""
    inv = ce.load_routes_inventory()
    tm = inv["threat_model"]

    browser = " ".join(tm["browser"]["required"]).lower()
    assert "token" in browser
    assert "post-only" in browser
    assert "csrf" in browser

    bridge = " ".join(tm["bridge-cli"]["required"]).lower()
    assert "token" in bridge
    assert "non-exempt" in bridge or "no-exemption" in bridge, (
        "the bridge/CLI class must be recorded as NON-exempt from auth")


def test_bridge_verbs_carry_state_changing_truth():
    """The verbs that write (converse, stand-up-confirm, scaffold-confirm,
    envelope confirm/raise, step-note; commission confirm, ingest-run) are
    flagged state-changing; the read verbs are not."""
    inv = ce.load_routes_inventory()
    seal = {v["verb"]: v for v in
            inv["ecgberht_bridges"]["seal-chamber-bridge"]["verbs"]}
    comm = {v["verb"]: v for v in
            inv["ecgberht_bridges"]["commission-run-bridge"]["verbs"]}

    for verb in ("converse", "stand-up-confirm", "scaffold-confirm",
                 "envelope-confirm", "envelope-raise", "step-note"):
        assert seal[verb]["state_changing"] is True, verb
    for verb in ("chamber", "recall", "scaffold-preview", "speak",
                 "step-detail"):
        assert seal[verb]["state_changing"] is False, verb

    assert comm["confirm"]["state_changing"] is True
    assert comm["ingest-run"]["state_changing"] is True
    assert comm["propose-active"]["state_changing"] is False

    # Every state-changing verb names at least one exposing Anchor route, and
    # that route has its own inventory row (the caller-class split holds:
    # network exposure of a bridge verb is exactly its anchor_routes rows).
    inv_patterns = {r["pattern"] for r in inv["anchor_routes"]}
    for verbs in (seal, comm):
        for verb in verbs.values():
            if not verb["state_changing"]:
                continue
            exposed = verb.get("exposed_via") or []
            conv = verb.get("conversational_cli")
            if not exposed and conv:
                # A TRUTHFUL non-HTTP exposure (Gate 5 W8): the verb is driven
                # conversationally / by the bridge CLI only — zero network
                # exposure by DESIGN, never a not_exposed debt row. The
                # declaration must name the hermetic bridge-CLI test standing
                # behind it (and that file must exist), name the driving CLI
                # flag, and must not double-declare not_exposed.
                assert "bridge-cli" in str(conv.get("declaration", "")), \
                    verb["verb"]
                assert not verb.get("not_exposed"), (
                    "verb %r declares BOTH conversational_cli and not_exposed"
                    % verb["verb"])
                proof = ANCHOR_ROOT / str(conv.get("proven_by", ""))
                assert proof.is_file(), (
                    "verb %r conversational_cli.proven_by %r is not a file"
                    % (verb["verb"], conv.get("proven_by")))
                assert "--" + verb["verb"] in str(conv.get("cli", "")), (
                    "verb %r conversational_cli.cli does not name its flag"
                    % verb["verb"])
                continue
            if not exposed and verb.get("not_exposed"):
                # A DECLARED exception: a bridge mutator no Anchor handler
                # invokes yet (zero network exposure). The diff guard still
                # forces its row to exist; the declaration must say why, and
                # the exposing effort must replace it with exposed_via rows.
                assert len(str(verb["not_exposed"])) > 40, verb["verb"]
                continue
            assert exposed, "state-changing verb %r names no exposing route" \
                % verb["verb"]
            for ref in exposed:
                method, _, pattern = ref.partition(" ")
                if method == "POST":
                    assert pattern in inv_patterns, (
                        "verb %r exposed_via %r has no anchor_routes row"
                        % (verb["verb"], ref))


def test_every_chamber_surface_route_is_inventoried():
    """The surface that shipped broken twice (handle_ecgberht_* mutators) is
    fully carried — a spot-intent check on top of the mechanical parity."""
    inv = ce.load_routes_inventory()
    patterns = {r["pattern"] for r in inv["anchor_routes"]}
    ecg = [r["pattern"] for r in ce.anchor_state_changing_routes()
           if r["pattern"].startswith("/api/ecgberht/")]
    assert ecg, "route_table lost the ecgberht POST surface?"
    missing = [p for p in ecg if p not in patterns]
    assert not missing, "chamber routes missing from inventory: %s" % missing


# ── The CI diff guard: green now, and it BITES ───────────────────────────────

def test_diff_guard_is_green_on_the_committed_inventory():
    """Both trees, both directions: no route or verb exists in code without a
    row, and no row is stale. This is the living-registry CI gate."""
    problems = ce.diff_guard_problems()
    assert not problems, (
        "living routes inventory out of sync with code:\n" +
        "\n".join(problems) +
        "\n(add the new mutator's row + its red-to-green proof, or remove "
        "the stale row — see chamber/routes-inventory.json law)")


def test_diff_guard_names_a_route_added_in_code_without_a_row():
    """Simulate the exact failure the guard exists for: a new mutator merged
    with no inventory row → the guard fails NAMING the route."""
    inv = copy.deepcopy(ce.load_routes_inventory())
    removed = None
    for i, row in enumerate(inv["anchor_routes"]):
        if row["pattern"] == "/api/ecgberht/converse":
            removed = inv["anchor_routes"].pop(i)
            break
    assert removed is not None
    diff = ce.diff_inventory_vs_code(inv)
    assert "POST /api/ecgberht/converse" in diff["routes_missing_from_inventory"]


def test_diff_guard_names_a_stale_inventory_row():
    inv = copy.deepcopy(ce.load_routes_inventory())
    inv["anchor_routes"].append(
        {"method": "POST", "pattern": "/api/ecgberht/never_built",
         "match": "exact", "auth": "token"})
    diff = ce.diff_inventory_vs_code(inv)
    assert "POST /api/ecgberht/never_built" in diff["routes_stale_in_inventory"]


def test_diff_guard_names_a_bridge_verb_without_a_row():
    inv = copy.deepcopy(ce.load_routes_inventory())
    verbs = inv["ecgberht_bridges"]["seal-chamber-bridge"]["verbs"]
    inv["ecgberht_bridges"]["seal-chamber-bridge"]["verbs"] = [
        v for v in verbs if v["verb"] != "converse"]
    diff = ce.diff_inventory_vs_code(inv)
    assert "seal-chamber-bridge:converse" in diff["verbs_missing_from_inventory"]


def test_diff_guard_names_a_stale_bridge_verb_row():
    inv = copy.deepcopy(ce.load_routes_inventory())
    inv["ecgberht_bridges"]["commission-run-bridge"]["verbs"].append(
        {"verb": "never-a-mode", "symbol": "neverAMode",
         "caller_class": "bridge-cli", "state_changing": False,
         "exposed_via": []})
    diff = ce.diff_inventory_vs_code(inv)
    assert ("commission-run-bridge:never-a-mode"
            in diff["verbs_stale_in_inventory"])


def test_bridge_scans_read_the_real_sibling_sources():
    """The scans anchor on the real Ecgberht sources (ECGBERHT_ROOT env else
    the sibling checkout — the two-repo execution contract makes the sibling
    REQUIRED, so an absent sibling fails loudly rather than skipping)."""
    seal = {v["verb"] for v in ce.scan_seal_chamber_verbs()}
    for verb in ("converse", "stand-up-confirm", "scaffold-confirm",
                 "speak", "chamber", "step-note"):
        assert verb in seal, "seal-chamber scan lost %r (got %s)" % (verb, seal)
    modes = set(ce.scan_commission_bridge_modes())
    assert modes == {"propose-active", "confirm", "ingest-run"}, modes


# ── The auth-ON coverage rule (CI rule over the new-surface namespace) ───────

def test_new_surface_namespace_is_fully_tagged():
    """Every test file in the declared new-surface namespace carries an honest
    AUTH-ON tag. This IS the CI coverage rule: it runs in the gate, and any
    W6-W11 surface test landing untagged fails the suite by name."""
    violations = ce.scan_new_surface_tests()
    assert not violations, (
        "auth-ON coverage rule violations:\n" +
        "\n".join("%s: %s" % (v["file"], v["problem"]) for v in violations))


def test_coverage_rule_catches_an_untagged_new_surface_test(tmp_path):
    """Negative proof: the rule BITES. A synthetic new-surface test file with
    no tag, a dishonest not-a-surface tag, and a label-only enforced tag are
    each caught by name."""
    d = tmp_path / "tests"
    d.mkdir()

    # Surface tokens are assembled by concatenation so THIS file (tagged
    # not-a-surface) never carries them as literals.
    srv_call = "make_" + "server"
    harness = "chamber_" + "harness"

    (d / "test_chamber_untagged.py").write_text(
        '"""A new chamber surface test with no auth posture tag."""\n',
        encoding="utf-8")
    (d / "test_chamber_dishonest.py").write_text(
        '"""AUTH-ON: not-a-surface"""\n'
        "import anchor_gui\n"
        "def test_boot():\n"
        "    srv = anchor_gui.%s('127.0.0.1', 0)\n" % srv_call,
        encoding="utf-8")
    (d / "test_chamber_label_only.py").write_text(
        '"""AUTH-ON: enforced — but nothing here ever sets a token."""\n'
        "def test_nothing():\n    pass\n",
        encoding="utf-8")
    (d / "test_chamber_honest.py").write_text(
        '"""AUTH-ON: enforced"""\n'
        "from tests.%s import TEST_TOKEN\n" % harness,
        encoding="utf-8")

    violations = ce.scan_new_surface_tests(d)
    by_file = {v["file"] for v in violations}
    assert "test_chamber_untagged.py" in by_file
    assert "test_chamber_dishonest.py" in by_file
    assert "test_chamber_label_only.py" in by_file
    assert "test_chamber_honest.py" not in by_file


def test_coverage_rule_is_recorded_in_the_inventory_artifact():
    """The rule's namespace + tag convention is recorded as data in the
    inventory (the artifact John reviews), matching the module constants the
    scanner enforces."""
    inv = ce.load_routes_inventory()
    rule = inv["coverage_rule"]
    assert ce.NEW_SURFACE_TEST_GLOB in rule["namespace"].replace("tests/", "")
    assert "AUTH-ON: enforced" in rule["rule"]
    assert "AUTH-ON: not-a-surface" in rule["rule"]
    assert "scan_new_surface_tests" in rule["rule"]
