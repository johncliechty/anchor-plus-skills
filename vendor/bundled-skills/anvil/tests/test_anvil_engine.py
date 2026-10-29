"""Tests for the Anvil Skill Engine & Programmatic Orchestrator (ANV-01 through ANV-11 + Orange-Split + LibCST + Hypothesis)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import anvil_engine as anvil  # noqa: E402


def _make_sample_repo(base: Path) -> tuple[Path, Path]:
    old_dir = base / "old_code"
    new_dir = base / "new_code"
    old_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)

    (old_dir / "pipeline.py").write_text(
        '"""Legacy data pipeline and LLM prompt dispatch."""\n'
        "def load_raw_records(path):\n"
        '    """Read raw CSV records from disk."""\n'
        "    return [path]\n\n"
        "def compute_risk_score(records):\n"
        '    """Analyze records and dispatch prompt to claude reviewer."""\n'
        "    data = load_raw_records(records)\n"
        "    return len(data)\n\n"
        "def legacy_xml_dump(score):\n"
        '    """Deprecated XML v1 writer."""\n'
        "    return f'<score>{score}</score>'\n\n"
        "def emit_json_report(score):\n"
        '    """Write final JSON report output."""\n'
        "    return {'score': compute_risk_score(score)}\n",
        encoding="utf-8",
    )

    (new_dir / "pipeline_v2.py").write_text(
        '"""Best-in-class pipeline with INGEST, COMPUTE, and EMIT stages."""\n'
        "def load_raw_records(path):\n"
        '    """Ingest raw records with strict schema validation."""\n'
        "    return [path]\n\n"
        "def compute_risk_score(records):\n"
        '    """Compute normalized risk score with adversarial claude/gemini check."""\n'
        "    items = load_raw_records(records)\n"
        "    return len(items) * 2\n\n"
        "def emit_json_report(score):\n"
        '    """Emit verified JSON report artifact."""\n'
        "    return {'score': compute_risk_score(score)}\n",
        encoding="utf-8",
    )
    return old_dir, new_dir


def test_mode1_conceptual_buckets_and_process_map_with_ai_badges(tmp_path: Path):
    old_dir, _ = _make_sample_repo(tmp_path)
    res = anvil.build_map(old_dir)
    assert res["schema"] == "anvil-map/v1"
    buckets = res["conceptual_buckets"]
    assert len(buckets) == 1
    b = buckets[0]
    assert len(b["functions"]) == 4
    assert any(fn["ai_interaction"] is not None for fn in b["functions"])
    assert res["process_map"]["nodes"][0]["ai_agent_badge"] is not None


def test_mode2_single_block_drilldown_and_empirical_claim_runner(tmp_path: Path):
    _, new_dir = _make_sample_repo(tmp_path)
    res = anvil.inspect_block(
        new_dir,
        "pipeline_v2.py",
        test_cmd=f'"{sys.executable}" -c "import pipeline_v2; assert pipeline_v2.compute_risk_score(\'x\') == 2"',
        lock_description="Validated: ingests records and doubles count.",
    )
    assert res["schema"] == "anvil-inspect/v1"
    assert res["empirical_validation"]["status"] == "PASS"
    assert res["validated"] is True
    assert (new_dir / "ANVIL-REPORT.md").is_file()
    assert "Validated: ingests records and doubles count." in (new_dir / "ANVIL-REPORT.md").read_text(encoding="utf-8")


def test_mode3_remap_null_space_and_three_stage_pipeline_validation(tmp_path: Path):
    old_dir, new_dir = _make_sample_repo(tmp_path)
    blocked = anvil.remap_code(old_dir, new_dir)
    assert blocked["schema"] == "anvil-remap/v1"
    assert blocked["null_space"]["count"] == 1
    assert blocked["null_space"]["unexplained_blockers"] == 1
    assert blocked["null_space"]["items"][0]["old_function"] == "legacy_xml_dump"
    assert blocked["verdict"] == "BLOCKED"

    approved = anvil.remap_code(old_dir, new_dir, signed_off_drops=["legacy_xml_dump"])
    assert approved["null_space"]["unexplained_blockers"] == 0
    assert approved["pipeline_validation"]["ingest_get_data"]["status"] == "PASS"
    assert approved["pipeline_validation"]["compute_do_analysis"]["status"] == "PASS"
    assert approved["pipeline_validation"]["emit_create_output"]["status"] == "PASS"
    assert approved["verdict"] == "PASS"


def test_mode4_paper_to_code_enforces_native_mathml_and_rejects_raw_latex(tmp_path: Path):
    _, new_dir = _make_sample_repo(tmp_path)
    res = anvil.paper_to_code_map(new_dir)
    assert res["schema"] == "anvil-paper-map/v1"
    assert res["native_mathml_enforced"] is True
    assert "<math" in res["alignments"][0]["mathml"]

    bad_paper = tmp_path / "bad_paper.json"
    bad_paper.write_text(
        json.dumps({"claims": [{"id": "eq-bad", "title": "Raw LaTeX", "mathml": "$$\\frac{a}{b}$$"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ANV-11 violation"):
        anvil.paper_to_code_map(new_dir, bad_paper)


def test_persistent_anvil_dialogue_across_all_four_modes(tmp_path: Path):
    _, new_dir = _make_sample_repo(tmp_path)
    for mode in ("map", "inspect", "remap", "paper-map"):
        chat = anvil.anvil_chat(new_dir, mode=mode, target="pipeline_v2.py", question="How does risk scoring work?")
        assert chat["schema"] == "anvil-dialogue/v1"
        assert chat["mode"] == mode
        assert chat["can_lock_validated_description"] is True
        assert "Pipeline V2" in chat["reply"]


def test_parable_of_the_oranges_decomposition_and_libcst_rewrite(tmp_path: Path):
    old_dir, _ = _make_sample_repo(tmp_path)
    orange = anvil.extract_orange_split(old_dir)
    assert orange["schema"] == "anvil-orange-split/v1"
    assert orange["counts"]["total_symbols"] == 4
    assert orange["counts"]["juice_count"] >= 1
    assert orange["counts"]["peel_count"] >= 1
    assert orange["counts"]["pith_and_seeds_count"] == 1
    assert orange["pith_and_seeds"][0]["name"] == "legacy_xml_dump"

    # Lossless CST rewrite excises legacy_xml_dump and renames compute_risk_score while preserving docstrings
    out_py = tmp_path / "rewritten.py"
    rw = anvil.cst_rewrite_module(
        old_dir / "pipeline.py",
        rename_map={"compute_risk_score": "evaluate_risk_score"},
        drop_functions=["legacy_xml_dump"],
        output_path=out_py,
    )
    assert rw["schema"] == "anvil-cst-rewrite/v1"
    assert "legacy_xml_dump" in rw["dropped_pith_functions"]
    assert "compute_risk_score->evaluate_risk_score" in rw["renamed_symbols"]
    assert rw["ruff_syntax_and_undefined_gate_ok"] is True
    rewritten_text = out_py.read_text(encoding="utf-8")
    assert "def evaluate_risk_score" in rewritten_text
    assert "legacy_xml_dump" not in rewritten_text
    assert '"""Read raw CSV records from disk."""' in rewritten_text


def test_programmatic_orchestrator_state_machine_and_differential_equivalence(tmp_path: Path):
    old_dir, new_dir = _make_sample_repo(tmp_path)
    # In _make_sample_repo, new_dir doubles compute_risk_score (len * 2 vs len), so equivalence gate detects drift!
    halted = anvil.orchestrate_anvil(old_dir, new_dir, sign_off_null_space=["legacy_xml_dump"])
    assert halted["schema"] == "anvil-orchestrator-state/v1"
    assert halted["orchestrator_governed"] is True
    assert halted["status"] == "HALTED_ON_GATE"
    assert halted["differential_equivalence"]["equivalent"] is False

    # When new_dir preserves exact Juice behavior for compute_risk_score, all 5 stages PASS and status is CONVERGED
    (new_dir / "pipeline_v2.py").write_text(
        (new_dir / "pipeline_v2.py").read_text(encoding="utf-8").replace("len(items) * 2", "len(items)"),
        encoding="utf-8",
    )
    converged = anvil.orchestrate_anvil(old_dir, new_dir, sign_off_null_space=["legacy_xml_dump"])
    assert converged["status"] == "CONVERGED"
    assert all(s["status"] == "PASS" for s in converged["stages"])
    assert Path(converged["state_file"]).is_file()
    assert Path(converged["manifest_file"]).is_file()


def test_anvil_v2_progressive_abstraction_beta_readers_and_walkthrough(tmp_path: Path):
    old_dir, new_dir = _make_sample_repo(tmp_path)
    res = anvil.build_map(old_dir)
    assert res["anvil_version"] == "v2"
    assert "blocks" in res and len(res["blocks"]) >= 1
    b = res["blocks"][0]

    # 3-Level Progressive Abstraction checks
    assert "level1_summary" in b
    assert "purpose" in b["level1_summary"]
    assert "inputs" in b["level1_summary"]
    assert "outputs" in b["level1_summary"]
    assert "level2_mechanics" in b
    assert "sub_blocks" in b["level2_mechanics"]
    assert "formulas_mathml" in b["level2_mechanics"]
    assert "<math" in b["level2_mechanics"]["formulas_mathml"][0]["mathml"]
    assert "assumptions" in b["level2_mechanics"]
    assert "old_to_new_diff" in b["level2_mechanics"]
    assert "level3_code" in b
    assert "old_source" in b["level3_code"]
    assert "best_in_class_source" in b["level3_code"]

    # 5-Seat Software Beta-Reader Panel checks
    beta = res["beta_reader_panel"]
    assert beta["schema"] == "anvil-beta-reader-panel/v2"
    assert len(beta["seats"]) == 5
    seat_ids = [s["seat_id"] for s in beta["seats"]]
    assert "cal_newport_cognitive_load" in seat_ids
    assert "functional_core_architect" in seat_ids
    assert "numerical_verification_auditor" in seat_ids
    assert "systems_performance_specialist" in seat_ids
    assert "security_boundary_auditor" in seat_ids

    # Live Code Walkthrough & Claim-vs-Reality Validator checks
    wt = anvil.run_code_walkthrough(old_dir, new_dir)
    assert wt["schema"] == "anvil-walkthrough/v2"
    assert wt["total_steps"] >= 1
    step0 = wt["steps"][0]
    assert "claimed_behavior" in step0
    assert "input_snapshot" in step0
    assert "actual_behavior" in step0
    assert "output_snapshot" in step0
    assert step0["verdict"] in ("ACCURATE", "DRIFT", "MISMATCH")

    # Standalone Markdown Report with Inline SVGs
    report_path = tmp_path / "ANVIL-V2-REPORT.md"
    md = anvil.render_markdown_report(old_dir, new_dir, report_path)
    assert report_path.is_file()
    assert "<svg" in md
    assert "5-Seat Software Beta-Reader Panel" in md
    assert "Block-by-Block Live Code Walkthrough" in md

