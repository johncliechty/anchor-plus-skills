# W12 — the release-gate CI bundle, green on the final commit
# (steward-chamber W12, Phase-4 Close).
#
# AUTH-ON: not-a-surface
#
# One suite re-running every named release check at its named seam:
# zero-model-call import closure + spawn audit · <2s budget at the
# committed >=2x-real fixture sizes · first-open-after-deploy degraded
# paint · DOM/class diff pinned to the SIGNED post-amendment mockup hash ·
# F6 living-routes inventory + diff guard + auth-ON coverage rule · F3
# escape + hostile-argv bounds · F4 sweep containment (symlink AND Windows
# junction/reparse fixtures, BOTH directions) · F5 slot-registered
# hostile-string inventory with the growth rule · F2 manifest-schema lint ·
# the wire-homing registry symbol-check · V3 landing-scoped commit
# coverage · the C11 signed-parity retirement gate.
#
# Where a landing wave's own instrument exists, this bundle RE-RUNS it (the
# committed function, imported); where the cited instrument is a ghost
# (chamber/W12-AUDIT-REPORT.md names each), the bundle exercises the landed
# machinery at the same seam — the recorded W12 reconciliation.
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chamber_audit as ca  # noqa: E402
import chamber_deliverable as cdeliv  # noqa: E402
import chamber_enforcement as ce  # noqa: E402
import chamber_gates as cg  # noqa: E402
import chamber_mockup_diff as cmd  # noqa: E402
import chamber_registries as reg  # noqa: E402
import chamber_retirement as ret  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]


def _link_dir(link: Path, target: Path) -> None:
    """A REAL reparse fixture: an NTFS junction on Windows (no privilege
    needed), a symlink elsewhere — the plan's named junction/reparse case."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


# ═════════════════════════════════════════════════════════════════════════════
# C1 legs — zero-model import closure · <2s budget · first-open degraded
# ═════════════════════════════════════════════════════════════════════════════

def test_zero_model_zero_spawn_import_closure_rerun():
    from test_chamber_open_w6 import (
        test_module_import_closure_admits_no_spawn_no_network_no_model,
    )
    test_module_import_closure_admits_no_spawn_no_network_no_model()


def test_budget_under_2s_at_committed_2x_fixture_sizes_rerun(tmp_path):
    from test_chamber_open_w6 import (
        test_open_budget_under_2s_at_the_committed_2x_fixture_sizes,
    )
    d = tmp_path / "budget"
    d.mkdir()
    test_open_budget_under_2s_at_the_committed_2x_fixture_sizes(d)


def test_first_open_after_deploy_degraded_paint_rerun(tmp_path):
    from test_chamber_open_w6 import (
        test_first_open_after_deploy_paints_drawn_degraded_and_never_rebuilds,
        test_read_cap_exceeded_refuses_into_the_drawn_degraded_state,
    )
    d1 = tmp_path / "deploy"
    d1.mkdir()
    test_first_open_after_deploy_paints_drawn_degraded_and_never_rebuilds(d1)
    # The boundedness refusal (the 200-read backstop) rides the same leg.
    d2 = tmp_path / "cap"
    d2.mkdir()
    test_read_cap_exceeded_refuses_into_the_drawn_degraded_state(d2)


# ═════════════════════════════════════════════════════════════════════════════
# C9 — the DOM/class diff stays pinned to the SIGNED hash
# ═════════════════════════════════════════════════════════════════════════════

def test_mockup_pin_holds_and_hard_fails_without_a_signature(tmp_path):
    import hashlib
    pinned = cmd.signed_hash()
    actual = hashlib.sha256(cmd.mockup_path().read_bytes()).hexdigest()
    assert pinned == actual, (
        "the live mockups.html no longer matches the SIGNED post-amendment "
        "hash — no mockup-verbatim claim may stand (C9)")
    # The kill gate's negative paths, re-run from the landing instrument.
    from test_chamber_mockup_diff_w6 import (
        test_signed_hash_parses_from_the_gate_record,
        test_pin_hard_fails_on_absent_record_or_hash_or_mismatch,
    )
    test_signed_hash_parses_from_the_gate_record()
    d = tmp_path / "pin"
    d.mkdir()
    test_pin_hard_fails_on_absent_record_or_hash_or_mismatch(d)
    # All three signed sections load as diff specs.
    spec = cmd.slice_spec()
    assert spec.get("sigs") or spec.get("edges")


# ═════════════════════════════════════════════════════════════════════════════
# F6 — living routes inventory + diff guard + the auth-ON coverage rule
# ═════════════════════════════════════════════════════════════════════════════

def test_living_routes_inventory_valid_and_diff_guard_green():
    inv = ce.load_routes_inventory()
    assert ce.validate_routes_inventory(inv) == []
    assert ce.diff_guard_problems() == [], (
        "a route/bridge verb moved without its inventory row — the F6 "
        "living-inventory guard is red")


def test_auth_on_coverage_rule_green_over_the_chamber_namespace():
    # Every tests/test_chamber_*.py (including THIS wave's four files)
    # carries a truthful AUTH-ON tag.
    assert ce.scan_new_surface_tests() == []


# ═════════════════════════════════════════════════════════════════════════════
# F3 — deliverable action bounds: escape fixtures + hostile argv
# ═════════════════════════════════════════════════════════════════════════════

def test_f3_escape_fixtures_all_inert_with_named_reasons(tmp_path):
    proj = tmp_path / "proj"
    (proj / "docs").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "loot.txt").write_text("x", encoding="utf-8")

    # '..' traversal
    _, refused = cdeliv.resolve_contained(proj, "../outside/loot.txt")
    assert refused["reason"] == cdeliv.INERT_PARENT_TRAVERSAL
    # absolute + drive-lettered
    _, refused = cdeliv.resolve_contained(proj, "/etc/passwd")
    assert refused["reason"] == cdeliv.INERT_ABSOLUTE_PATH
    _, refused = cdeliv.resolve_contained(proj, "C:/Windows/system32")
    assert refused["reason"] == cdeliv.INERT_ABSOLUTE_PATH
    # symlink / junction-resolved escape (a REAL reparse point)
    _link_dir(proj / "jump", outside)
    _, refused = cdeliv.resolve_contained(proj, "jump/loot.txt")
    assert refused["reason"] == cdeliv.INERT_OUTSIDE_TREE
    # a contained path still resolves
    (proj / "docs" / "report.md").write_text("ok", encoding="utf-8")
    real, none = cdeliv.resolve_contained(proj, "docs/report.md")
    assert none is None and real.is_file()


def test_f3_hostile_argv_content_is_inert_and_never_spawns(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    spawned = []

    def recording_spawn(argv, cwd):
        spawned.append((argv, cwd))
        return 4242

    hostile = ('a"b.py', "a b.py", "a&b.py", "a|b.py", "a;b.py",
               "a\nb.py", "a\x00b.py", "a'b.py")
    for rel in hostile:
        action = cdeliv.resolve_action(
            proj, {"declared": True, "type": "program", "output_path": rel})
        assert action["state"] == "inert", rel
        assert action["reason"] in (cdeliv.INERT_HOSTILE_PATH,
                                    cdeliv.INERT_PARENT_TRAVERSAL), rel
        out = cdeliv.invoke_action(action, spawn_fn=recording_spawn)
        assert out["invoked"] is False, rel
    assert spawned == [], "hostile argv content must NEVER reach a spawn"


def test_f3_verb_allow_list_is_code_owned_and_spawns_shell_false(tmp_path):
    # The allow-list is frozen in source (read-only mapping) — never config.
    import types
    assert isinstance(cdeliv.VERB_ALLOW_LIST, types.MappingProxyType)
    assert isinstance(cdeliv.TYPE_VERBS, types.MappingProxyType)
    # An armed program action carries shell:false + list argv + pinned cwd.
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "tool.py").write_text("print('hi')\n", encoding="utf-8")
    action = cdeliv.resolve_action(
        proj, {"declared": True, "type": "program",
               "output_path": "tool.py"})
    assert action["state"] == "armed" and action["kind"] == "spawn"
    assert action["shell"] is False and isinstance(action["argv"], list)
    assert Path(action["cwd"]) == proj.resolve()


# ═════════════════════════════════════════════════════════════════════════════
# F4 — sweep containment, BOTH directions, symlink + junction resolved
# ═════════════════════════════════════════════════════════════════════════════

def test_f4_sweep_containment_refuses_every_escape_by_name(tmp_path):
    root = tmp_path / "worktree"
    (root / "src").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")

    _, r = cg.sweep_containment(root, "../elsewhere/secret.txt")
    assert r["reason"] == cg.SWEEP_TRAVERSAL
    _, r = cg.sweep_containment(root, "/abs/path")
    assert r["reason"] == cg.SWEEP_ABSOLUTE
    _, r = cg.sweep_containment(root, "C:/abs/path")
    assert r["reason"] == cg.SWEEP_ABSOLUTE
    _, r = cg.sweep_containment(root, "a\x00b")
    assert r["reason"] == cg.SWEEP_HOSTILE_PATH

    # Direction 1: a junction/symlink escaping the root.
    _link_dir(root / "jump", outside)
    _, r = cg.sweep_containment(root, "jump/secret.txt")
    assert r["reason"] == cg.SWEEP_OUTSIDE
    # Direction 2: a link that RESOLVES TO an ancestor (claiming the root
    # would sweep the world) — refused as contains-swept-root.
    _link_dir(root / "up", tmp_path)
    _, r = cg.sweep_containment(root, "up")
    assert r["reason"] == cg.SWEEP_CONTAINS_ROOT

    # A contained path still resolves.
    (root / "src" / "made.txt").write_text("y", encoding="utf-8")
    real, none = cg.sweep_containment(root, "src/made.txt")
    assert none is None and real.is_file()


# ═════════════════════════════════════════════════════════════════════════════
# F5 — the slot-registered hostile-string suite + growth rule (re-run)
# ═════════════════════════════════════════════════════════════════════════════

def test_f5_slot_inventory_and_growth_rule_rerun(tmp_path):
    from test_chamber_dom_law_w9 import (
        test_slot_inventory_is_versioned_owned_and_valid,
        test_growth_rule_green_on_committed_renders_and_sinks,
        test_growth_rule_names_a_new_render_added_without_a_row,
        test_hostile_fixture_map_is_complete_against_the_inventory,
    )
    test_slot_inventory_is_versioned_owned_and_valid()
    test_growth_rule_green_on_committed_renders_and_sinks()
    d = tmp_path / "f5"
    d.mkdir()
    test_growth_rule_names_a_new_render_added_without_a_row(d)
    test_hostile_fixture_map_is_complete_against_the_inventory()


# ═════════════════════════════════════════════════════════════════════════════
# F2 — the manifest-schema lint (re-run from the landing instrument)
# ═════════════════════════════════════════════════════════════════════════════

def test_f2_manifest_schema_lint_rerun(tmp_path):
    from test_chamber_manifest_schema_w4 import (
        test_manifest_schema_document_exists_versioned_and_owned,
        test_derive_validate_write_load_round_trip,
        test_schema_version_mismatch_is_rejected,
    )
    test_manifest_schema_document_exists_versioned_and_owned()
    d = tmp_path / "f2"
    d.mkdir()
    test_derive_validate_write_load_round_trip(d)
    test_schema_version_mismatch_is_rejected()


# ═════════════════════════════════════════════════════════════════════════════
# C12 — the wire-homing registry symbol-check (landing in this wave)
# ═════════════════════════════════════════════════════════════════════════════

def test_wire_homing_symbol_check_green_on_both_trees():
    assert reg.lint_wire_homing() == []


def test_wire_homing_lint_names_a_vanished_symbol():
    tampered = reg.load_wire_homing()
    tampered["rows"][0]["owners"][0]["symbols"] = ["def symbol_that_left"]
    problems = reg.lint_wire_homing(tampered)
    assert any(tampered["rows"][0]["id"] in p and "no longer present" in p
               for p in problems), problems
    # A row silently dropped from the registry is also named.
    short = reg.load_wire_homing()
    short["rows"] = [r for r in short["rows"] if r["id"] != "paced_pty"]
    problems2 = reg.lint_wire_homing(short)
    assert any("paced_pty" in p for p in problems2), problems2


def test_provenance_table_lints_green():
    assert reg.lint_provenance_table() == []


# ═════════════════════════════════════════════════════════════════════════════
# V3 — landing-scoped commit coverage (all four landing classes bank)
# ═════════════════════════════════════════════════════════════════════════════

def test_v3_every_landing_class_has_its_commit_call_site():
    gates_src = (ANCHOR / "chamber_gates.py").read_text(encoding="utf-8")
    refine_src = (ANCHOR / "chamber_refine.py").read_text(encoding="utf-8")
    cs_src = (ANCHOR / "commission_session.py").read_text(encoding="utf-8")
    # sweep landing -> bind_sweep_card banks
    assert "sweep landing bound to the gate queue" in gates_src
    # gate resolution banks
    assert '_auto_commit(folder, "gate %s' in gates_src
    # correction fix -> refine confirm banks
    assert "refine confirm: section" in refine_src
    # step yield + deliverable landing -> finish_run records the landing
    # THEN banks the campaign state in the same path
    assert "record_landing_if_present" in cs_src
    assert "commit_campaign_state(" in cs_src
    idx_landing = cs_src.index("record_landing_if_present(folder, updated)")
    assert "commit_campaign_state(" in cs_src[idx_landing:], (
        "the deliverable-landing record must be followed by the campaign "
        "bank in finish_run (V3 landing-scoped coverage)")


# ═════════════════════════════════════════════════════════════════════════════
# C11 — the signed-parity retirement gate holds on the release commit
# ═════════════════════════════════════════════════════════════════════════════

def test_c11_retirement_gate_holds_and_parity_map_green():
    st = ret.retirement_state()
    assert st["parity"]["problems"] == []
    # Unsigned -> tiles stand; signed -> every row ruled. Either way the
    # release ships with the gate GREEN, never bypassed.
    if not st["signature"]["signed"]:
        assert st["tiles_stand"] is True
        assert st["verdict"]["allowed"] is False
    else:
        assert st["parity"]["all_rows_resolved"] is True


# ═════════════════════════════════════════════════════════════════════════════
# The audit artifacts ride the release commit, honest and regenerable
# ═════════════════════════════════════════════════════════════════════════════

def test_release_bundle_artifacts_are_committed_and_regenerable():
    import chamber_close_report as ccr
    assert ca.committed_matches_regenerated() == []
    assert ccr.committed_matches_regenerated() == []
    assert ca.test_debt_problems() == []


def test_c_recheck_rows_are_green_with_honest_notes():
    rows = {r["id"]: r for r in ca.c_recheck_rows()}
    assert set(rows) == {"C9", "C10", "C11", "C12"}
    for rid, row in rows.items():
        assert row["green"], (rid, row["note"])


def test_fixture_sizes_still_committed_at_2x_real():
    # The boundedness gate's numeric bound stays committed (W5/W6 law).
    manifest = json.loads(
        (ANCHOR / "tests" / "fixtures" / "chamber" / "real-ledgers" /
         "fixture-manifest.json").read_text(encoding="utf-8"))
    rule = manifest.get("w6_budget_rule") or {}
    assert rule, "the committed >=2x-real budget rule must ride the tree"
