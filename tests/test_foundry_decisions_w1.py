"""foundry-v2 Wave 1 GATE — Phase-0 decisions as CODE (``foundry_decisions``).

Frozen plan (``FOUNDRY-V2-IMPLEMENTATION-PLAN.md`` §Wave 1): the four Phase-0
de-risking decisions are encoded as an IMPORTABLE Python module (not just
prose) so later waves consume them and the §5 vacuous-GREEN guard is
satisfied. done-when (verbatim): this test **imports ``foundry_decisions``**
and asserts (a) the isolation runtime + cost constant is set, (b) the
accepted provenance classes are enumerated, (c) the mutative-verb inventory
for Wave 9-10 is present, and (d) every decision carries a
``traces_to_north_star`` tag.

Pure data assertions — no PTY, no subprocess, no server, no model call.
"""
import pathlib

import foundry_decisions as fd

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# (a) the isolation runtime + cost constant is set
# ---------------------------------------------------------------------------

def test_isolation_runtime_is_set():
    assert isinstance(fd.ISOLATION_RUNTIME, str) and fd.ISOLATION_RUNTIME.strip()
    # v2's resolved decision is the Master-Plan-sanctioned honest downgrade.
    assert fd.ISOLATION_RUNTIME == fd.PERMISSIONS_ADVISORY_V2


def test_isolation_cost_envelope_is_set():
    envelope = fd.ISOLATION_COST_ENVELOPE
    chosen = envelope["chosen"]
    assert chosen["runtime"] == fd.ISOLATION_RUNTIME
    assert isinstance(chosen["startup_latency_ms"], (int, float))
    assert isinstance(chosen["per_run_overhead_ms"], (int, float))
    # The C2 reconciliation: the chosen posture must not conflict with
    # lazy/budgeted activation.
    assert chosen["lazy_activation_conflict"] is False
    # Every evaluated candidate carries a cost figure and an explicit verdict.
    assert envelope["candidates"], "no candidates were evaluated"
    for name, cand in envelope["candidates"].items():
        assert isinstance(cand["startup_latency_ms"], (int, float)), name
        assert cand["eligible"] is False, name
        assert cand["why_not"].strip(), name


def test_isolation_downgrade_carries_compensating_controls():
    controls = fd.ISOLATION_COMPENSATING_CONTROLS
    assert len(controls) >= 5
    joined = " ".join(controls).lower()
    # The load-bearing controls the later waves must implement.
    assert "confirm token" in joined
    assert "write-scope" in joined
    assert "journal" in joined


# ---------------------------------------------------------------------------
# (b) the accepted provenance classes are enumerated
# ---------------------------------------------------------------------------

def test_provenance_taxonomy_enumerates_the_four_accepted_classes():
    expected = {
        "human_authored",
        "agent_cross_model_verified",
        "agent_human_ratified",
        "frozen_benchmark_delta",
    }
    assert expected <= set(fd.TEST_PROVENANCE_CLASSES)
    assert set(fd.PROMOTION_ACCEPTED_CLASSES) == expected


def test_every_provenance_class_has_a_trust_ceiling_on_the_ladder():
    for cls, spec in fd.TEST_PROVENANCE_CLASSES.items():
        assert spec["trust_ceiling"] in fd.TRUST_LADDER, cls


def test_unverified_agent_tests_are_rejected_not_omitted():
    # The anti-circular-validation rule is a positive, machine-readable fact.
    spec = fd.TEST_PROVENANCE_CLASSES["agent_unverified"]
    assert spec["trust_ceiling"] == fd.TRUST_REJECTED
    assert "agent_unverified" not in fd.PROMOTION_ACCEPTED_CLASSES


def test_prose_lessons_gate_only_via_frozen_benchmark():
    # Prose has no unit test, so cross-model code verification does not apply
    # to it; frozen-benchmark-delta is the prose gate.
    assert "prose" not in (
        fd.TEST_PROVENANCE_CLASSES["agent_cross_model_verified"]["applies_to"])
    frozen = fd.TEST_PROVENANCE_CLASSES["frozen_benchmark_delta"]
    assert frozen["applies_to"] == ("prose",)


# ---------------------------------------------------------------------------
# (c) the mutative-verb inventory for Wave 9-10 is present
# ---------------------------------------------------------------------------

def test_mutative_verb_inventory_for_waves_9_and_10():
    verbs = fd.ANCHOR_API_CONTRACT["mutative_verbs"]
    assert verbs is fd.MUTATIVE_VERBS
    wave9 = {v for v, spec in verbs.items() if spec["wave"] == 9}
    wave10 = {v for v, spec in verbs.items() if spec["wave"] == 10}
    assert wave9 == {"foundry.scaffold_skill", "foundry.gen_manifest"}
    assert wave10 == {"foundry.edit_north_star", "foundry.register_autoload"}
    # The Wave-6 sleep apply is also a control-plane mutate op.
    assert verbs["foundry.apply_sleep_improvement"]["wave"] == 6


def test_every_mutative_verb_is_confirm_gated_and_write_scoped():
    for verb, spec in fd.MUTATIVE_VERBS.items():
        assert spec["confirm_gated"] is True, verb
        assert spec["write_scope"].strip(), verb
        assert spec["summary"].strip(), verb


def test_contract_splits_native_surface_from_mutative_verbs():
    native = fd.ANCHOR_API_CONTRACT["native_read_execute"]
    for capability in ("run_skill_job", "monitor_job", "live_session",
                       "read_artifacts", "auth"):
        assert native[capability], capability
    # The Phase-2 hook the control-plane ops plug into.
    assert fd.OP_KINDS == ("run", "mutate")


# ---------------------------------------------------------------------------
# (d) every decision carries a traces_to_north_star tag
# ---------------------------------------------------------------------------

def test_every_decision_traces_to_the_north_star():
    assert {r["id"] for r in fd.DECISIONS} == {"DR-01", "DR-02", "DR-03",
                                               "DR-04"}
    for record in fd.DECISIONS:
        tags = record["traces_to_north_star"]
        assert tags, record["id"]
        for tag in tags:
            assert tag.startswith("NS#"), (record["id"], tag)


def test_decision_registry_validates_clean():
    assert fd.validate_decisions() == []


def test_each_decision_has_its_rationale_doc_on_disk():
    for record in fd.DECISIONS:
        doc = REPO_ROOT / record["rationale_doc"]
        assert doc.is_file(), record["rationale_doc"]
        text = doc.read_text(encoding="utf-8")
        assert record["id"] in text, record["id"]


# ---------------------------------------------------------------------------
# Telemetry decision shape (consumed by the Wave-2 journaling seam)
# ---------------------------------------------------------------------------

def test_telemetry_depth_and_seven_field_journal_entry():
    assert fd.PROCESS_TELEMETRY_DEPTH == "OUTCOME_PLUS_RECOVERY"
    assert len(fd.JOURNAL_ENTRY_FIELDS) == 7
    assert len(set(fd.JOURNAL_ENTRY_FIELDS)) == 7


def test_side_channel_is_droppable_by_design():
    side = fd.SIDE_CHANNEL_DESIGN
    assert side["droppable"] is True
    assert side["skeleton_survives_drop"] is True
    assert set(side["referenced_by"]) <= set(fd.JOURNAL_ENTRY_FIELDS)
    assert side["skeleton_max_bytes"] <= 4096
