"""Wave 4 Verification Suite — Anvil v5 Deduplicated IR (<2 MB), <100 ms Fingerprint Cache,
Topological Process Schematics, Source Containment & Ground-Truth Manuscript-vs-Code Divergences.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

import distro
import paths
from steward_cockpit import anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil"
VENDOR_ANVIL_ROOT = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
PAPER1_ROOT = ANCHOR_ROOT.parent / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
HETNN_ROOT = PAPER1_ROOT / "HetNN"
HETNN_MAIN_TEX = HETNN_ROOT / "Manuscript" / "Main.tex"
HETNN_BASELINE_JSON = ANCHOR_ROOT / ".foreman" / "hetnn-baseline-sha256.json"
W4_MOCKUP_HTML = (
    ANCHOR_ROOT
    / "planning"
    / "cross-system-upgrade-2026-11-20"
    / "mockups"
    / "w4-anvil-divergence-workbench.html"
)
W4_LOOKS_DIR = ANCHOR_ROOT / "planning" / "cross-system-upgrade-2026-11-20" / "looks" / "w4"

if str(SKILL_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import anvil_engine  # noqa: E402
import anvil_v4_process  # noqa: E402
import anvil_v4_refactor  # noqa: E402
import anvil_v4_workbench  # noqa: E402


def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    anvil_session._LOADED_MTIME_NS = Path(anvil_session.__file__).stat().st_mtime_ns
    extra_roots = [tmp_path.resolve()]
    if PAPER1_ROOT.exists():
        extra_roots.append(PAPER1_ROOT.resolve())
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, *extra_roots),
    )


def _create_synthetic_divergence_fixture(base_dir: Path) -> tuple[Path, Path]:
    """Build a multi-stage PyTorch + R + TeX repository with 6 differently named seeded
    divergences and 1 documented ridge penalty mechanism.
    """
    repo = base_dir / "synthetic_choice_repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "r_post").mkdir(parents=True, exist_ok=True)
    (repo / "manuscript" / "parts").mkdir(parents=True, exist_ok=True)

    (repo / "workflow.sh").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            python src/dgp_monte_carlo.py --draws 64
            python src/regime_trainer.py --folds 5
            Rscript r_post/render_welfare_summary.R
            """
        ),
        encoding="utf-8",
    )

    (repo / "src" / "dgp_monte_carlo.py").write_text(
        textwrap.dedent(
            """\
            import math

            def unpack_nested_cell(cell_spec):
                (n_obs, n_periods), sigma_scale = cell_spec
                return float(n_obs * n_periods) * sigma_scale

            def simulate_synthetic_market_panel(n_markets: int = 32, seed: int = 11):
                \"\"\"Monte Carlo synthetic data generation for latent demand panels.\"\"\"
                return [{"m": i, "fare": 1.0 + 0.2 * (i % 4), "shock": math.cos(seed + i)} for i in range(n_markets)]
            """
        ),
        encoding="utf-8",
    )

    (repo / "src" / "estimators.py").write_text(
        textwrap.dedent(
            """\
            import torch
            import torch.nn as nn
            import torch.nn.functional as F

            class AbstractUtilityModel(nn.Module):
                def __init__(self):
                    super().__init__()

                def loss(self, log_p, target_y):
                    return -torch.mean(torch.sum(target_y * log_p, dim=-1))

            class HomogeneousLogitAnchor(AbstractUtilityModel):
                def __init__(self, n_features: int):
                    super().__init__()
                    self.linear_head = nn.Linear(n_features, 1, bias=False)

                def forward(self, x_mat):
                    return F.log_softmax(self.linear_head(x_mat).squeeze(-1), dim=-1)

            class HeterogeneousGateMixture(AbstractUtilityModel):
                def __init__(self, n_features: int, k_classes: int = 3):
                    super().__init__()
                    self.gate_net = nn.Sequential(nn.Linear(n_features, 12), nn.Tanh(), nn.Linear(12, k_classes))
                    self.taste_matrix = nn.Parameter(torch.zeros(k_classes, n_features))

                def forward(self, full_x, sub_x):
                    weights = F.softmax(self.gate_net(full_x), dim=-1)
                    utilities = torch.einsum("btd,kd->btk", sub_x, self.taste_matrix)
                    choice_p = F.softmax(utilities, dim=1)
                    mix_p = torch.sum(weights.unsqueeze(1) * choice_p, dim=-1)
                    return torch.log(mix_p.clamp_min(1e-12))
            """
        ),
        encoding="utf-8",
    )

    (repo / "src" / "regime_trainer.py").write_text(
        textwrap.dedent(
            """\
            import torch
            import torch.nn as nn
            from src.estimators import HomogeneousLogitAnchor, HeterogeneousGateMixture

            # Documented in Estimation.tex: L2 ridge penalty alpha = 1e-3
            DOCUMENTED_RIDGE_ALPHA = 1e-3

            # Seeded Divergence 4: undocumented cross-class dispersion penalty
            CLASS_DISPERSION_GAMMA = 0.07

            class ResidualAnchoredMixture(nn.Module):
                def __init__(self, core_mix: HeterogeneousGateMixture):
                    super().__init__()
                    self.core_mix = core_mix
                    self.base_shift = nn.Parameter(torch.zeros(1))

                def forward(self, x_all):
                    # Seeded Divergence 5: slicing covariate tensor to single column [0]
                    fare_slice = x_all[:, :, [0]]
                    return self.core_mix(x_all, fare_slice) + self.base_shift

            def nudge_zero_slacks(net: ResidualAnchoredMixture, eps: float = 1e-6) -> None:
                \"\"\"Seeded Divergence 2: stochastic Gaussian perturbation on stalled tensors.\"\"\"
                with torch.no_grad():
                    zero_mask = net.core_mix.taste_matrix.abs() < eps
                    if zero_mask.any():
                        noise = 1e-3 * torch.randn_like(net.core_mix.taste_matrix)
                        net.core_mix.taste_matrix.add_(noise * zero_mask.float())

            def pick_parsimonious_k(cv_loss_means, cv_stderrs, k_grid):
                \"\"\"Seeded Divergence 6: 1-SE selection gate instead of argmin CV loss.\"\"\"
                best_i = min(range(len(cv_loss_means)), key=lambda idx: cv_loss_means[idx])
                one_se_bound = cv_loss_means[best_i] + cv_stderrs[best_i]
                passing = [k_grid[i] for i in range(len(k_grid)) if cv_loss_means[i] <= one_se_bound]
                return min(passing)

            def fit_anchored_regime_model(x_train, y_train, anchor_state_path: str):
                # Seeded Divergence 1: warm-start transfer from fitted HomogeneousLogitAnchor
                homog = HomogeneousLogitAnchor(n_features=x_train.shape[-1])
                homog.load_state_dict(torch.load(anchor_state_path))
                mix_core = HeterogeneousGateMixture(n_features=x_train.shape[-1], k_classes=3)
                with torch.no_grad():
                    mix_core.taste_matrix.copy_(homog.linear_head.weight.repeat(3, 1))
                model = ResidualAnchoredMixture(mix_core)

                # Seeded Divergence 3: multi-rate Adam parameter groups
                opt = torch.optim.Adam(
                    [
                        {"params": [model.base_shift], "lr": 2e-4},
                        {"params": list(model.core_mix.parameters()), "lr": 3e-3},
                    ]
                )
                for step in range(8):
                    opt.zero_grad()
                    lp = model(x_train)
                    nll = -torch.mean(torch.sum(y_train * lp, dim=-1))
                    doc_ridge = DOCUMENTED_RIDGE_ALPHA * torch.sum(model.core_mix.taste_matrix ** 2)
                    undoc_disp = CLASS_DISPERSION_GAMMA * torch.var(model.core_mix.taste_matrix, dim=0).sum()
                    loss_total = nll + doc_ridge + undoc_disp
                    loss_total.backward()
                    opt.step()
                    if step == 2:
                        nudge_zero_slacks(model)
                return model
            """
        ),
        encoding="utf-8",
    )

    (repo / "r_post" / "render_welfare_summary.R").write_text(
        textwrap.dedent(
            """\
            df_welfare <- data.frame(segment = c(1, 2, 3), surplus = c(1.2, 2.4, 1.9))
            agg_out <- aggregate(surplus ~ segment, data = df_welfare, FUN = mean)
            write.csv(agg_out, file = "welfare_summary.csv", row.names = FALSE)
            """
        ),
        encoding="utf-8",
    )

    main_tex = repo / "manuscript" / "Main.tex"
    main_tex.write_text(
        textwrap.dedent(
            """\
            \\documentclass{article}
            \\title{Heterogeneous Gate Choice Estimation}
            \\begin{document}
            \\maketitle
            \\input{parts/Specification}
            \\input{parts/Estimation}
            \\end{document}
            """
        ),
        encoding="utf-8",
    )

    (repo / "manuscript" / "parts" / "Specification.tex").write_text(
        textwrap.dedent(
            """\
            \\section{Choice Model Specification}
            Each household evaluates full observable product characteristics $x_{jt}$ in both the gating network
            and the segment utility $\\beta_k^\\top x_{jt}$:
            \\begin{equation}
            P_{ijt} = \\sum_{k=1}^{K} \\pi_k(x_{it}) \\frac{\\exp(\\beta_k^\\top x_{ijt})}{\\sum_{m} \\exp(\\beta_k^\\top x_{imt})}
            \\end{equation}
            """
        ),
        encoding="utf-8",
    )

    (repo / "manuscript" / "parts" / "Estimation.tex").write_text(
        textwrap.dedent(
            """\
            \\section{Estimation and Model Selection}
            All parameters are initialized randomly and estimated jointly in a single stage via Adam with a single learning rate $\\eta = 0.003$.
            We include a documented $L_2$ ridge penalty `DOCUMENTED_RIDGE_ALPHA` ($\\alpha = 10^{-3}$) on taste weights:
            \\begin{equation}
            \\mathcal{L}(\\theta) = -\\frac{1}{N} \\sum_{i=1}^{N} \\log P_{i, y_i} + \\alpha \\|\\beta\\|_2^2
            \\end{equation}
            The class count $K$ is selected to minimize out-of-sample cross-validation negative log-likelihood.
            """
        ),
        encoding="utf-8",
    )

    return repo, main_tex


def test_w4_no_paper1_identifiers_grep_gate() -> None:
    """Deterministic grep gate + Skill Foundry <-> vendor/bundled-skills/anvil byte-sync check."""
    forbidden_literals = (
        "AnchoredMoE",
        "step2_runner",
        "DEV_PEN",
        "unstick_residuals",
        "MixtureOfExpertsMNL",
    )
    pattern = re.compile("|".join(re.escape(tok) for tok in forbidden_literals), re.IGNORECASE)

    scan_roots = [
        SKILL_ROOT / "scripts",
        SKILL_ROOT / "static",
        VENDOR_ANVIL_ROOT / "scripts",
        VENDOR_ANVIL_ROOT / "static",
    ]
    hits: list[str] = []
    for root in scan_roots:
        assert root.is_dir(), f"Expected Anvil directory missing: {root}"
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            txt = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(txt.splitlines(), start=1):
                m = pattern.search(line)
                if m:
                    hits.append(f"{path}:{lineno}:{m.group(0)}")
    assert hits == [], f"Paper-1 identifier literals forbidden in Anvil code/static: {hits}"

    # Verify 100% byte-identity between Skill Foundry and Anchor's vendor/bundled-skills/anvil
    vendor_files = [p for p in sorted(VENDOR_ANVIL_ROOT.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    assert len(vendor_files) >= 10
    for vf in vendor_files:
        rel = vf.relative_to(VENDOR_ANVIL_ROOT)
        sf = SKILL_ROOT / rel
        assert sf.is_file(), f"Bundled Anvil file missing in Skill Foundry: {rel}"
        assert vf.read_bytes() == sf.read_bytes(), f"Byte drift between Skill Foundry and vendor on {rel}"


def test_w4_synthetic_repo_divergences_found_and_non_divergence_absent(tmp_path: Path) -> None:
    """Synthetic fixture finds all 6 seeded divergences, suppresses the documented ridge penalty,
    preserves topological Simulation + R stages + nn.Module.forward, and fixes walkthrough/Aegis/MathML/:L<line>.
    """
    repo, main_tex = _create_synthetic_divergence_fixture(tmp_path)

    div_report = anvil_v4_refactor.detect_manuscript_code_divergences(repo, main_tex)
    assert div_report["ok"] is True
    divs = div_report["divergences"]
    found_cats = {d["category"] for d in divs}
    expected_cats = {
        "undocumented_warm_start_stage",
        "post_fit_residual_perturbation",
        "multi_rate_optimizer_groups",
        "undocumented_penalty_or_shrinkage",
        "covariate_subset_adapter",
        "cv_selection_rule_divergence",
    }
    assert expected_cats == found_cats

    # Documented ridge penalty must NOT be flagged as an undocumented divergence
    titles_and_summaries = " ".join(f"{d.get('title', '')} {d.get('summary', '')}" for d in divs)
    assert "DOCUMENTED_RIDGE_ALPHA" not in titles_and_summaries
    assert "CLASS_DISPERSION_GAMMA" in titles_and_summaries
    assert int(div_report["documented_non_divergence_count"]) >= 1

    # Hardening check: (a) multiple penalties in same repo BOTH surface (no 1-per-category cap),
    # (b) renaming trainer & total variable still detects penalty AST-structurally, and
    # (c) negated warm-start prose & statistical significance 0.07 level never suppress divergences
    trainer_p = repo / "src" / "regime_trainer.py"
    est_tex_p = repo / "manuscript" / "parts" / "Estimation.tex"
    orig_trainer = trainer_p.read_text(encoding="utf-8")
    orig_est_tex = est_tex_p.read_text(encoding="utf-8")
    try:
        mod_trainer = (
            orig_trainer.replace("CLASS_DISPERSION_GAMMA = 0.07", "CLASS_DISPERSION_GAMMA = 0.07\nSECOND_GAMMA = 0.09")
            .replace("def fit_anchored_regime_model(", "def run_regime_training_loop(")
            .replace("loss_total = nll + doc_ridge + undoc_disp", "total = nll + doc_ridge + undoc_disp + SECOND_GAMMA * torch.var(model.core_mix.taste_matrix, dim=1).sum()")
            .replace("loss_total.backward()", "total.backward()")
        )
        trainer_p.write_text(mod_trainer, encoding="utf-8")
        est_tex_p.write_text(
            orig_est_tex
            + "\nUnlike prior work, we do not warm-start any parameters.\nResults are robust at the 0.07 level.\n",
            encoding="utf-8",
        )
        hard_rep = anvil_v4_refactor.detect_manuscript_code_divergences(repo, main_tex)
        hard_divs = hard_rep["divergences"]
        hard_cats = [d["category"] for d in hard_divs]
        assert "undocumented_warm_start_stage" in hard_cats
        assert hard_cats.count("undocumented_penalty_or_shrinkage") >= 2
        hard_blob = " ".join(f"{d.get('title', '')} {d.get('summary', '')}" for d in hard_divs)
        assert "CLASS_DISPERSION_GAMMA" in hard_blob and "SECOND_GAMMA" in hard_blob
    finally:
        trainer_p.write_text(orig_trainer, encoding="utf-8")
        est_tex_p.write_text(orig_est_tex, encoding="utf-8")

    # Subdirectory content edit immediately invalidates compute_repo_state_fingerprint (zero 2s root-mtime blind window)
    fp_before = anvil_v4_workbench.compute_repo_state_fingerprint(repo, main_tex)
    trainer_p.write_text(orig_trainer + "\n# in-place subfile edit\n", encoding="utf-8")
    try:
        fp_after = anvil_v4_workbench.compute_repo_state_fingerprint(repo, main_tex)
        assert fp_after != fp_before
    finally:
        trainer_p.write_text(orig_trainer, encoding="utf-8")

    # Topological L0/L1 Process Schematic: Simulation -> Estimation -> R script
    pmap = anvil_v4_process.build_process_map(repo, persist=False, paper_path=main_tex)
    stages = pmap["l1_stages"]
    assert any(st["kind"] == "simulation" for st in stages)
    sim_stage = next(i for i, st in enumerate(stages) if "src/dgp_monte_carlo.py" in st.get("member_files", []))
    est_stage = next(i for i, st in enumerate(stages) if "src/regime_trainer.py" in st.get("member_files", []))
    r_stage = next(i for i, st in enumerate(stages) if "r_post/render_welfare_summary.R" in st.get("member_files", []))
    assert sim_stage <= est_stage <= r_stage

    # PyTorch nn.Module.forward methods are never misclassified as NULL_PROVEN dead helpers
    rmap = anvil_v4_refactor.build_refactor_map(repo, persist=False, paper_path=main_tex, process_map=pmap)
    null_syms = {item["symbol"] for item in rmap["null_set"]["null_proven"]}
    assert "HeterogeneousGateMixture.forward" not in null_syms
    assert "ResidualAnchoredMixture.forward" not in null_syms

    # Equation alignment weights concrete pipeline leaf classes over AbstractUtilityModel.loss
    paper_map = anvil_engine.paper_to_code_map(repo, main_tex)
    eq0_matches = [m["qualname"] for m in paper_map["equations"][0]["matched_functions"][:2]]
    assert eq0_matches[0] != "AbstractUtilityModel.loss"
    assert any(
        leaf in qn
        for qn in eq0_matches
        for leaf in ("HeterogeneousGateMixture", "ResidualAnchoredMixture", "fit_anchored_regime_model")
    )

    # Tuple-unpacking walkthrough guard, MathML \top -> ⊤, Aegis uppercase severity, and :L<line> profile citations
    wt = anvil_engine.run_code_walkthrough(repo)
    assert wt.get("overall_verdict") != "DIVERGENCE" and len(wt.get("steps") or []) >= 1

    mml_top = anvil_engine.compile_latex_to_mathml(r"\beta_k^\top x_{ijt}")
    assert "⊤" in mml_top and ">top<" not in mml_top

    prof = anvil_v4_refactor.run_profile_and_literature(repo, persist=False)
    for key in ("imperative_shell_io_fixes", "functional_core_kernel_upgrades", "rejected_kernel_upgrades"):
        for item in prof.get(key, []):
            assert re.search(r":L\d+$", str(item.get("citation_loc") or "")), f"Missing :L<line> on {item}"


def test_w4_divergence_citations_and_manuscript_search_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify mandatory file:L<line> code citations + manuscript passage or absent_from_manuscript
    search records on both the synthetic fixture and read-only Paper 1 (HetNN + Main.tex).
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    cite_re = re.compile(r"^([^:\s]+):L(\d+)$")

    def _assert_valid_divergence_rows(rows: list[dict], code_root: Path) -> None:
        assert len(rows) >= 6
        for row in rows:
            m = cite_re.match(str(row.get("code_citation") or ""))
            assert m is not None, f"Invalid code_citation on {row}"
            rel_file, line_s = m.group(1), m.group(2)
            line_no = int(line_s)
            fpath = code_root / rel_file
            assert fpath.is_file(), f"Cited code file does not exist: {fpath}"
            total_lines = len(fpath.read_text(encoding="utf-8", errors="replace").splitlines())
            assert 1 <= line_no <= total_lines

            status = row.get("manuscript_status")
            assert status in {"contradicted_in_manuscript", "absent_from_manuscript"}
            if status == "contradicted_in_manuscript":
                assert ":L" in str(row.get("manuscript_citation") or "")
                assert len(str(row.get("manuscript_passage") or "").strip()) >= 10
            else:
                sr = row.get("search_record") or {}
                assert sr.get("status") == "absent_from_manuscript"
                assert isinstance(sr.get("searched_files"), list) and len(sr["searched_files"]) >= 1
                assert isinstance(sr.get("queries"), list) and len(sr["queries"]) >= 1
                assert bool(str(sr.get("closest_section") or "").strip())

    synth_repo, synth_tex = _create_synthetic_divergence_fixture(tmp_path / "synth")
    synth_rep = anvil_v4_refactor.detect_manuscript_code_divergences(synth_repo, synth_tex)
    _assert_valid_divergence_rows(synth_rep["divergences"], synth_repo)
    for srow in synth_rep["divergences"]:
        if srow.get("manuscript_status") == "absent_from_manuscript":
            sr_obj = srow.get("search_record") or {}
            assert bool(str(sr_obj.get("executed_regex") or "").strip())
            v_chk = anvil_v4_refactor.verify_divergence_search_record(synth_tex, sr_obj)
            assert v_chk["ok"] is True and v_chk["reproduced"] is True

    if HETNN_ROOT.is_dir() and HETNN_MAIN_TEX.is_file():
        p1_cockpit = tmp_path / "paper1_readonly_cockpit"
        p1_cockpit.mkdir()
        started = anvil_session.start_cockpit_session(
            p1_cockpit,
            mode="paper",
            software_spec=str(HETNN_ROOT),
            paper_spec=str(HETNN_MAIN_TEX),
        )
        assert started["ok"] is True
        v4_state, status_code = anvil_session.get_v4_cockpit_state(p1_cockpit)
        assert status_code == 200
        bundle = v4_state["v4_bundle"]
        p1_divs = bundle["divergences"]
        _assert_valid_divergence_rows(p1_divs, HETNN_ROOT)

        p1_cats = {d["category"] for d in p1_divs}
        assert {
            "undocumented_warm_start_stage",
            "post_fit_residual_perturbation",
            "multi_rate_optimizer_groups",
            "undocumented_penalty_or_shrinkage",
            "covariate_subset_adapter",
            "cv_selection_rule_divergence",
        }.issubset(p1_cats)

        # Verify Paper 1 MoE equations weight concrete leaf models ahead of ChoiceModel.loss
        p1_eqs = bundle["paper_map"]["equations"]
        assert len(p1_eqs) >= 10
        top1_symbols = [eq["maps_to_old"][0]["symbol"] for eq in p1_eqs if eq.get("maps_to_old")]
        assert top1_symbols.count("ChoiceModel.loss") == 0
        assert any("AnchoredMoE" in s or "MixtureOfExpertsMNL" in s for s in top1_symbols)

        # Verify HetNN source tree SHA-256 immutability against baseline
        if HETNN_BASELINE_JSON.is_file():
            baseline = json.loads(HETNN_BASELINE_JSON.read_text(encoding="utf-8"))
            sha_map = baseline.get("sha256", {})
            assert len(sha_map) >= 200
            for rel_p, exp_hash in sha_map.items():
                actual_hash = hashlib.sha256((HETNN_ROOT / rel_p).read_bytes()).hexdigest()
                assert actual_hash == exp_hash, f"HetNN file modified: {rel_p}"


def test_w4_session_ir_under_2mb_and_warm_v4_under_100ms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify <2 MB deduplicated .anvil/session.json IR, <100 ms warm v4_state cache,
    two-process atomic lock concurrency, and repeat-invocation determinism.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)

    target_repo, target_tex = (
        (HETNN_ROOT, HETNN_MAIN_TEX)
        if (HETNN_ROOT.is_dir() and HETNN_MAIN_TEX.is_file())
        else _create_synthetic_divergence_fixture(tmp_path / "perf_fixture")
    )

    cdir = tmp_path / "perf_cockpit"
    cdir.mkdir()
    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(target_repo),
        paper_spec=str(target_tex),
    )

    sfile = cdir / ".anvil" / "session.json"
    mfile = cdir / ".anvil" / "manifest.json"
    assert sfile.is_file() and mfile.is_file()
    session_bytes = sfile.stat().st_size
    assert session_bytes < 2 * 1024 * 1024, f"session.json exceeded 2 MB bound: {session_bytes}"
    assert mfile.stat().st_size < 256 * 1024

    # Verify on-disk IR omits self-duplicating remap.new_code_comprehension while _read_session_ir rehydrates
    raw_disk = json.loads(sfile.read_text(encoding="utf-8"))
    assert raw_disk.get("ir_schema") == anvil_session.ANVIL_SESSION_IR_SCHEMA
    assert "symbol_store" in (raw_disk.get("code_map") or {})
    assert "new_code_comprehension" not in (raw_disk.get("remap") or {})
    rehydrated = anvil_session._read_session_ir(sfile)
    assert isinstance((rehydrated.get("remap") or {}).get("new_code_comprehension"), dict)

    # Prime cold cache, then benchmark warm v4_state (< 100 ms)
    _, code_cold = anvil_session.get_v4_cockpit_state(cdir)
    assert code_cold == 200

    warm_samples_ms: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        payload_warm, code_warm = anvil_session.get_v4_cockpit_state(cdir)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert code_warm == 200 and payload_warm["ok"] is True
        warm_samples_ms.append(elapsed_ms)
    assert min(warm_samples_ms) < 100.0, f"Warm get_v4_cockpit_state exceeded 100 ms: {warm_samples_ms}"

    # Repeat-invocation idempotence check
    synth_repo, synth_tex = _create_synthetic_divergence_fixture(tmp_path / "idem")
    div_1 = anvil_v4_refactor.detect_manuscript_code_divergences(synth_repo, synth_tex)
    div_2 = anvil_v4_refactor.detect_manuscript_code_divergences(synth_repo, synth_tex)
    assert div_1 == div_2

    # Two-process concurrency test on atomic _write_session_ir under exclusive_file_lock
    worker_code = textwrap.dedent(
        f"""\
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(ANCHOR_ROOT)!r})
        from steward_cockpit import anvil_session
        sfile = Path(sys.argv[1])
        wid = sys.argv[2]
        for i in range(6):
            cur = anvil_session._read_session_ir(sfile)
            cur["selected_block_id"] = f"{{wid}}-{{i}}"
            anvil_session._write_session_ir(sfile, cur)
        """
    )
    worker_py = tmp_path / "concurrent_ir_writer.py"
    worker_py.write_text(worker_code, encoding="utf-8")
    p1 = subprocess.Popen([sys.executable, str(worker_py), str(sfile), "wA"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p2 = subprocess.Popen([sys.executable, str(worker_py), str(sfile), "wB"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _, err1 = p1.communicate(timeout=30)
    _, err2 = p2.communicate(timeout=30)
    assert p1.returncode == 0, err1
    assert p2.returncode == 0, err2
    after_concurrent = anvil_session._read_session_ir(sfile)
    assert after_concurrent["active"] is True
    assert str(after_concurrent.get("selected_block_id", "")).startswith(("wA-", "wB-"))
    assert sfile.stat().st_size < 2 * 1024 * 1024


def test_w4_source_containment_escape_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise content + raw_source lazy loading, >2 MB 413 bound refusal, and 403 escape refusals
    (.., absolute path, symlink) on both /api/steward/anvil/source and /api/anvil/v4/source.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    repo, main_tex = _create_synthetic_divergence_fixture(tmp_path / "src_guard")
    outside_secret = tmp_path / "outside_secret.py"
    outside_secret.write_text("SECRET_VAL = 42\n", encoding="utf-8")

    big_file = repo / "src" / "oversized_blob.py"
    big_file.write_text("# " + ("x" * (2 * 1024 * 1024 + 128)) + "\n", encoding="utf-8")

    symlink_created = False
    symlink_rel = "src/escape_link.py"
    try:
        os.symlink(str(outside_secret), str(repo / "src" / "escape_link.py"))
        symlink_created = True
    except OSError:
        symlink_created = False

    cdir = tmp_path / "src_cockpit"
    cdir.mkdir()
    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(repo),
        paper_spec=str(main_tex),
    )

    # 1. Anchor Cockpit route `/api/steward/anvil/source`
    ok_body, ok_code = steward_routes.handle_get(str(cdir), "anvil/source", {"file": ["src/estimators.py"]})
    assert ok_code == 200 and ok_body["ok"] is True
    expected_src = (repo / "src" / "estimators.py").read_text(encoding="utf-8")
    assert ok_body["content"] == expected_src
    assert ok_body["raw_source"] == expected_src
    assert ok_body["start_line"] == 1 and ok_body["end_line"] == len(expected_src.splitlines())

    b413, c413 = steward_routes.handle_get(str(cdir), "anvil/source", {"file": ["src/oversized_blob.py"]})
    assert c413 == 413 and b413["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    for bad_spec in ("../outside_secret.py", str(outside_secret.resolve())):
        b_esc, c_esc = steward_routes.handle_get(str(cdir), "anvil/source", {"file": [bad_spec]})
        assert c_esc == 403, f"Expected 403 for {bad_spec}, got {c_esc}: {b_esc}"

    if symlink_created:
        b_sym, c_sym = steward_routes.handle_get(str(cdir), "anvil/source", {"file": [symlink_rel]})
        assert c_sym == 403

    # Direct unit verification on get_l3_numbered_file + helper contracts
    l3_direct = anvil_v4_process.get_l3_numbered_file(repo, "src/estimators.py")
    assert l3_direct["content"] == expected_src and l3_direct["raw_source"] == expected_src
    with pytest.raises(anvil_v4_process.AnvilRefusalError) as exc_big:
        anvil_v4_process.get_l3_numbered_file(repo, "src/oversized_blob.py")
    assert exc_big.value.error_code == "BOUND_EXCEEDED_REFUSAL"
    assert anvil_v4_refactor._values_equivalent(1.0, 1.0 + 1e-12, 1e-7, 1e-9) is True
    assert anvil_session._build_stage_symbol_maps({"l1_stages": []}, {"target_stages": [], "mapped_to_new": []})[2] == "S1"
    prog_map = anvil_engine.build_progressive_abstraction_map(outside_secret)
    assert prog_map["schema"] == "anvil-map/v1"

    # 2. Standalone Workbench HTTP server `/api/anvil/v4/source`
    srv = anvil_v4_workbench.create_workbench_server(repo, host="127.0.0.1", port=0, paper_path=main_tex)
    port = srv.server_address[1]
    assert port != 8777
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        def _http_get(rel_q: str) -> tuple[int, dict]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.request("GET", f"/api/anvil/v4/source?file={urllib.parse.quote(rel_q)}")
                resp = conn.getresponse()
                body_bytes = resp.read()
                return int(resp.status), json.loads(body_bytes.decode("utf-8"))
            finally:
                conn.close()

        st_ok, doc_ok = _http_get("src/estimators.py")
        assert st_ok == 200 and doc_ok["content"] == expected_src and doc_ok["raw_source"] == expected_src

        st_big, doc_big = _http_get("src/oversized_blob.py")
        assert st_big == 413 and doc_big["error_code"] == "BOUND_EXCEEDED_REFUSAL"

        for bad_spec in ("../outside_secret.py", str(outside_secret.resolve())):
            st_bad, _ = _http_get(bad_spec)
            assert st_bad == 403

        if symlink_created:
            st_sym, _ = _http_get(symlink_rel)
            assert st_sym == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_w4_workbench_session_isolation_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent UI state mutations update only .anvil/v4/workbench_session.json without
    rewriting .anvil/session.json, and client assets satisfy visibility/backoff/distro gates.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    repo, main_tex = _create_synthetic_divergence_fixture(tmp_path / "ui_iso")
    cdir = tmp_path / "ui_cockpit"
    cdir.mkdir()
    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(repo),
        paper_spec=str(main_tex),
    )

    sfile = cdir / ".anvil" / "session.json"
    wsfile = cdir / ".anvil" / "v4" / "workbench_session.json"
    before_bytes = sfile.read_bytes()
    before_mtime = sfile.stat().st_mtime_ns
    time.sleep(0.02)

    errors: list[Exception] = []

    def _mutate_ui(idx: int) -> None:
        try:
            body, code = steward_routes.handle_post(
                str(cdir),
                "anvil",
                {
                    "action": "v4_session",
                    "active_stage_id": f"S{(idx % 3) + 1}",
                    "ide_open": bool(idx % 2 == 0),
                    "ide_theme": "dark" if idx % 2 else "light",
                    "pinned_watches": [f"watch_{idx}"],
                    "breakpoints": [f"src/regime_trainer.py:{10 + idx}"],
                },
            )
            assert code == 200 and body["ok"] is True
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=_mutate_ui, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == [], f"Concurrent v4_session errors: {errors}"
    assert wsfile.is_file()
    assert sfile.stat().st_mtime_ns == before_mtime
    assert sfile.read_bytes() == before_bytes

    # Static client & distribution checks
    dist_txt = (ANCHOR_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "steward_cockpit/static/anvil.js" in dist_txt

    anvil_js = (ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js").read_text(encoding="utf-8")
    anvil_html = (ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html").read_text(encoding="utf-8")
    wb_html = (SKILL_ROOT / "static" / "anvil_v4_workbench.html").read_text(encoding="utf-8")
    assert "AbortController" in anvil_js and "visibilityState" in anvil_js
    assert "data-divergence-panel" in anvil_js and "data-divergence-panel" in wb_html
    assert "setInterval" not in anvil_html and "setInterval" not in wb_html

    scan_targets = [
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html",
        ANCHOR_ROOT / "tests" / "test_wave4_anvil_ir_divergence_2026_11_20.py",
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in scan_targets]
    assert distro.scan_paths(pairs, root=ANCHOR_ROOT) == []


def test_w4_failure_state_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify all 5 surface failure-state rows (503, 504, 502, 500 UNKNOWN, 200 EMPTY)
    with strict UNKNOWN != EMPTY separation, plus Wave-4 L3 look painted/uncovered artifacts.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)

    # Row 5: 200 empty-but-valid (UNKNOWN != EMPTY)
    empty_cdir = tmp_path / "empty_cockpit"
    empty_cdir.mkdir()
    p200, c200 = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert c200 == 200
    assert p200["status_kind"] == "empty-but-valid"
    assert p200["badge"] == "EMPTY"
    assert p200["unknown_state"] is False

    # Row 4: 500 backing-store-unreadable (corrupt session.json -> UNKNOWN, unknown_state=True)
    anvil_dir = empty_cdir / ".anvil"
    anvil_dir.mkdir(parents=True, exist_ok=True)
    (anvil_dir / "session.json").write_text("{corrupt-session-ir", encoding="utf-8")
    p500, c500 = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert c500 == 500
    assert p500["status_kind"] == "backing-store-unreadable"
    assert p500["badge"] == "UNKNOWN"
    assert p500["unknown_state"] is True
    assert p500["status_kind"] != p200["status_kind"]

    # Corrupt .anvil/session.json MUST ALSO fail-close GET /api/steward/anvil/source with HTTP 500 UNKNOWN
    (empty_cdir / "local_probe.py").write_text("X = 1\n", encoding="utf-8")
    s500, sc500 = steward_routes.handle_get(str(empty_cdir), "anvil/source", {"file": ["local_probe.py"]})
    assert sc500 == 500
    assert s500["status_kind"] == "backing-store-unreadable"
    assert s500["badge"] == "UNKNOWN"
    assert s500["unknown_state"] is True
    (empty_cdir / "local_probe.py").unlink()
    (anvil_dir / "session.json").unlink()

    # Row 3: 502 dependency-returns-garbage (malformed last_trace.json -> REJECTED_GARBAGE)
    v4_dir = anvil_dir / "v4"
    v4_dir.mkdir(parents=True, exist_ok=True)
    (v4_dir / "last_trace.json").write_text("{malformed-trace", encoding="utf-8")
    p502, c502 = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert c502 == 502
    assert p502["status_kind"] == "dependency-returns-garbage"
    assert p502["badge"] == "REJECTED_GARBAGE"
    assert p502["unknown_state"] is False
    (v4_dir / "last_trace.json").unlink()

    # Row 2: 504 dependency-slow-or-killed (real subprocess timeout on POST v4_trace -> TIMEOUT_PARTIAL)
    slow_cdir = tmp_path / "slow_cockpit"
    slow_cdir.mkdir()
    (slow_cdir / "slow_job.py").write_text("import time\ntime.sleep(3.0)\n", encoding="utf-8")
    anvil_session.start_cockpit_session(slow_cdir, software_spec=".")
    p504, c504 = steward_routes.handle_post(
        str(slow_cdir),
        "anvil",
        {
            "action": "v4_trace",
            "argv": ["python", "slow_job.py"],
            "timeout_sec": 0.25,
            "operator_consent_confirmed": True,
        },
    )
    assert c504 == 504
    assert p504["status_kind"] == "dependency-slow-or-killed"
    assert p504["badge"] == "TIMEOUT_PARTIAL"
    assert p504["unknown_state"] is False

    # Row 1: 503 dependency-missing (unavailable runtime modules -> DEGRADED_STATIC)
    with monkeypatch.context() as mp:
        mp.setattr(anvil_session, "_load_anvil_v4_modules", lambda: None)
        p503, c503 = anvil_session.get_v4_cockpit_state(empty_cdir)
        assert c503 == 503
        assert p503["status_kind"] == "dependency-missing"
        assert p503["badge"] == "DEGRADED_STATIC"
        assert p503["unknown_state"] is False

    # Verify exported Wave-4 Workbench HTML & L3 ft.py look verdicts
    assert W4_MOCKUP_HTML.is_file(), f"Missing Wave-4 mockup HTML: {W4_MOCKUP_HTML}"
    mockup_txt = W4_MOCKUP_HTML.read_text(encoding="utf-8")
    assert 'data-divergence-panel="true"' in mockup_txt
    win_home_prefix = "c:" + "\\users\\"
    posix_home_prefix = "c:/" + "users/"
    assert win_home_prefix not in mockup_txt.lower() and posix_home_prefix not in mockup_txt.lower()

    verdict_file = W4_LOOKS_DIR / "verdict.json"
    live_verdict_file = W4_LOOKS_DIR / "live" / "verdict.json"
    assert verdict_file.is_file() and live_verdict_file.is_file()
    for vf in (verdict_file, live_verdict_file):
        vdoc = json.loads(vf.read_text(encoding="utf-8"))
        vraw = json.dumps(vdoc)
        assert '"painted": true' in vraw.lower()
        assert '"painted": false' not in vraw.lower()
        assert '"coveredby": null' in vraw.lower()
