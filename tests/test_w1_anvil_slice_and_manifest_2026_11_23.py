"""Wave 1 Hermetic Gate Suite — Canonical Foundry Slicer, 64-Hex Scope Manifest,
Atomic Vendor Sync, Constructor-Attribute Overwrite Pruning, Unbound-Equation Flagging,
Software Architecture & Paper Map, Locked v2 Mockup `ft.py look --check` Contract, and
`anvil-v6-gate.mjs` Fail-Closed Self-Tests (`2026-11-23`).
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import time
from typing import Any, Dict

import pytest

import distro
from steward_cockpit import anvil_session

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
DEV_ROOT = ANCHOR_ROOT.parent
FOUNDRY_ANVIL_ROOT = DEV_ROOT / "Skill Foundry" / "skills" / "anvil"
FOUNDRY_SCRIPTS_DIR = FOUNDRY_ANVIL_ROOT / "scripts"
VENDOR_ANVIL_ROOT = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
VENDOR_SCRIPTS_DIR = VENDOR_ANVIL_ROOT / "scripts"
FT_PY = DEV_ROOT / "foundry-tools" / "ft.py"

PLAN_DIR = ANCHOR_ROOT / "planning" / "2026-11-23-anvil-scoping-and-comprehension"
PLAN_SCRIPTS_DIR = PLAN_DIR / "scripts"
SYNC_SCRIPT = PLAN_SCRIPTS_DIR / "sync_anvil_vendor.py"
GATE_MJS = PLAN_SCRIPTS_DIR / "anvil-v6-gate.mjs"
LOCKED_MOCKUPS_JSON = PLAN_DIR / "mockups" / "LOCKED-MOCKUPS.json"


def _load_sync_module() -> Any:
    spec = importlib.util.spec_from_file_location("sync_anvil_vendor_w1", SYNC_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _create_dir_link_or_junction(link_path: Path, target_dir: Path) -> None:
    """Create a real OS directory junction on Windows (`mklink /J`) or symlink on POSIX."""
    if os.name == "nt":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"mklink /J failed: {proc.stderr}\n{proc.stdout}"
    else:
        os.symlink(str(target_dir), str(link_path), target_is_directory=True)


def test_w1_sync_anvil_vendor_idempotence_concurrency_and_canonical_loader(tmp_path: Path) -> None:
    """Verify `sync_anvil_vendor.py` atomic write + cross-process lock serialization:
    1) Live `sha256(Foundry) == sha256(vendor)` parity across `scripts/`, `static/`,
       `FLOW.json`, `LIBRARY.json`, `SKILL.md`, and zero `__pycache__`/`.pyc`.
    2) Repeat-invocation idempotence on hermetic `tmp_path` trees.
    3) Multi-process simultaneous sync (`4` worker processes) with zero torn/temp files.
    4) `anvil_session._load_anvil_v4_modules()` resolving canonical Foundry when present
       and falling back cleanly to `vendor/bundled-skills/anvil/scripts`.
    """
    sync_mod = _load_sync_module()

    live_parity = sync_mod.verify_foundry_vendor_parity(FOUNDRY_ANVIL_ROOT, VENDOR_ANVIL_ROOT)
    assert live_parity["ok"] is True, f"Live Foundry/vendor parity failed: {live_parity}"
    assert live_parity["pycache_hits"] == []
    for req_rel in (
        "FLOW.json",
        "LIBRARY.json",
        "SKILL.md",
        "scripts/anvil_v4_process.py",
        "scripts/anvil_v4_refactor.py",
        "static/anvil_v4_workbench.html",
    ):
        assert req_rel in live_parity["digests"], f"Missing required synced file {req_rel}"
        h_f = hashlib.sha256((FOUNDRY_ANVIL_ROOT / req_rel).read_bytes()).hexdigest()
        h_v = hashlib.sha256((VENDOR_ANVIL_ROOT / req_rel).read_bytes()).hexdigest()
        assert h_f == h_v

    # Hermetic repeat-invocation idempotence + orphan/pycache cleanup test
    tmp_foundry = tmp_path / "hermetic_foundry"
    tmp_vendor = tmp_path / "hermetic_vendor"
    tmp_lock = tmp_path / "locks" / "sync.lock"
    for sub in ("scripts", "static", "journal"):
        (tmp_foundry / sub).mkdir(parents=True)
    for rf in ("FLOW.json", "LIBRARY.json", "SKILL.md"):
        (tmp_foundry / rf).write_text(f'{{"file": "{rf}"}}\n', encoding="utf-8")
    (tmp_foundry / "scripts" / "anvil_v4_process.py").write_text("X = 1\n" * 200, encoding="utf-8")
    (tmp_foundry / "scripts" / "anvil_v4_refactor.py").write_text("Y = 2\n" * 200, encoding="utf-8")
    (tmp_foundry / "static" / "anvil_v4_workbench.html").write_text("<html>ok</html>\n", encoding="utf-8")
    (tmp_foundry / "journal" / "0001-local.md").write_text("not synced to vendor\n", encoding="utf-8")

    # Plant stale orphan & __pycache__ in vendor before first sync
    (tmp_vendor / "scripts" / "__pycache__").mkdir(parents=True)
    (tmp_vendor / "scripts" / "__pycache__" / "stale.cpython-312.pyc").write_bytes(b"\x00\x01")
    (tmp_vendor / "scripts" / "obsolete_orphan.py").write_text("DEAD = True\n", encoding="utf-8")

    r1 = sync_mod.sync_foundry_to_vendor(tmp_foundry, tmp_vendor, lock_path=tmp_lock)
    assert r1["ok"] is True
    assert len(r1["updated_files"]) == 6
    assert "scripts/obsolete_orphan.py" in r1["removed_orphans"]
    assert not (tmp_vendor / "journal").exists()
    assert list(tmp_vendor.rglob("__pycache__")) == []

    # Repeat invocation: 0 files rewritten, 6 unchanged, digests identical
    r2 = sync_mod.sync_foundry_to_vendor(tmp_foundry, tmp_vendor, lock_path=tmp_lock)
    assert r2["ok"] is True
    assert r2["updated_files"] == []
    assert len(r2["unchanged_files"]) == 6
    assert r2["digests"] == r1["digests"]

    # 4-process real OS concurrency test with `--force` atomic temp+fsync+replace contention
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(SYNC_SCRIPT),
                "--foundry-root",
                str(tmp_foundry),
                "--vendor-root",
                str(tmp_vendor),
                "--lock-path",
                str(tmp_lock),
                "--force",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    for p in procs:
        out_s, err_s = p.communicate(timeout=30)
        assert p.returncode == 0, f"Concurrent sync worker failed: {err_s}\n{out_s}"
        parsed_w = json.loads(out_s)
        assert parsed_w["ok"] is True

    post_conc = sync_mod.verify_foundry_vendor_parity(tmp_foundry, tmp_vendor, lock_path=tmp_lock)
    assert post_conc["ok"] is True
    assert [x for x in tmp_vendor.rglob("*") if x.name.startswith(".sync_tmp.")] == []

    # Verify `_load_anvil_v4_modules()` resolves canonical Skill Foundry and supports vendor fallback
    loaded_live = anvil_session._load_anvil_v4_modules()
    assert "anvil_v4_process" in loaded_live and "anvil_v4_refactor" in loaded_live
    proc_mod_file = Path(loaded_live["anvil_v4_process"].__file__).resolve()
    assert proc_mod_file == (FOUNDRY_SCRIPTS_DIR / "anvil_v4_process.py").resolve()

    for exported_fn in (
        "compute_scope_manifest",
        "slice_call_graph",
        "build_software_architecture_paper_map",
        "bind_manuscript_equations_to_symbols",
    ):
        assert hasattr(loaded_live["anvil_v4_process"], exported_fn)
        assert hasattr(loaded_live["anvil_v4_refactor"], exported_fn)

    loaded_fallback = anvil_session._load_anvil_v4_modules(
        candidates=(tmp_path / "absent_foundry_scripts", VENDOR_SCRIPTS_DIR)
    )
    assert Path(loaded_fallback["anvil_v4_process"].__file__).resolve() == (
        VENDOR_SCRIPTS_DIR / "anvil_v4_process.py"
    ).resolve()
    # Restore canonical module cache after custom-candidate probe
    anvil_session._load_anvil_v4_modules()


def test_w1_compute_scope_manifest_determinism_sensitivity_bounds_and_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `compute_scope_manifest` mtime/re-copy invariance, 1-byte sensitivity across
    files/papers/data/modules/entrypoints/engine, 2 GB data-root & 8 MB bundle refusal bounds,
    and CWE-22 escape-attempt refusals (`..`, absolute path, symlink/junction).
    """
    mods = anvil_session._load_anvil_v4_modules()
    v4_proc = mods["anvil_v4_process"]

    assert v4_proc.MAX_ALLOWLISTED_DATA_BYTES == 2 * 1024 * 1024 * 1024
    assert v4_proc.MAX_SCOPE_BUNDLE_BYTES == 8 * 1024 * 1024
    assert v4_proc.SCOPE_MANIFEST_SCHEMA_VERSION == "anvil-scope-manifest/v6.1"

    cockpit_a = tmp_path / "cockpit_alpha"
    repo_a = cockpit_a / "sources" / "synth_repo"
    (repo_a / "core").mkdir(parents=True)
    (repo_a / "drivers").mkdir(parents=True)
    (repo_a / "data").mkdir(parents=True)
    (repo_a / "unallowlisted_notes").mkdir(parents=True)
    (cockpit_a / "Datasets").mkdir(parents=True)
    (cockpit_a / "manuscript" / "tables").mkdir(parents=True)

    f_core = repo_a / "core" / "kernel.py"
    f_drv = repo_a / "drivers" / "run_tab1.py"
    f_data = repo_a / "data" / "panel.csv"
    f_ck_data = cockpit_a / "Datasets" / "holdout.csv"
    f_tex = cockpit_a / "manuscript" / "Main.tex"
    f_tab_tex = cockpit_a / "manuscript" / "tables" / "tab1.tex"

    f_core.write_text("def compute_ll(x, beta):\n    return sum(v * beta for v in x)\n", encoding="utf-8")
    f_drv.write_text("from core.kernel import compute_ll\n\ndef main():\n    return compute_ll([1.0, 2.0], 0.5)\n", encoding="utf-8")
    f_data.write_text("id,x\n1,0.25\n2,0.75\n", encoding="utf-8")
    f_ck_data.write_text("id,x\n3,1.25\n", encoding="utf-8")
    (repo_a / "unallowlisted_notes" / "scratch.bin").write_bytes(b"ignored_non_data_dir")
    f_tab_tex.write_text("\\begin{tabular}{lr} LL & 0.75 \\\\ \\end{tabular}\n", encoding="utf-8")
    f_tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{tables/tab1.tex}\n\\end{document}\n",
        encoding="utf-8",
    )

    synth_eng = tmp_path / "synth_engine_scripts"
    synth_eng.mkdir()
    eng_py = synth_eng / "anvil_v4_process.py"
    eng_py.write_text("ENGINE_VER = 1\n", encoding="utf-8")

    cjson_1, sha_1 = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["drivers/run_tab1.py", "core/kernel.py"],
        selected_module_ids=["m_replicators", "m_core"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert re.fullmatch(r"[0-9a-f]{64}", sha_1)
    assert str(tmp_path) not in cjson_1 and str(tmp_path).replace("\\", "/") not in cjson_1
    doc_1 = json.loads(cjson_1)
    assert doc_1["schema_version"] == "anvil-scope-manifest/v6.1"
    assert doc_1["selected_module_ids"] == ["m_core", "m_replicators"]
    assert [x["path"] for x in doc_1["files"]] == ["core/kernel.py", "drivers/run_tab1.py"]
    assert len(doc_1["papers"]) == 2
    assert len(doc_1["allowlisted_data_files"]) == 2

    # 1. Repeat invocation + mtime touch invariance
    future_ts = time.time() + 7200.0
    for touched in (f_core, f_drv, f_data, f_ck_data, f_tex, f_tab_tex):
        os.utime(touched, (future_ts, future_ts))
    cjson_touch, sha_touch = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core", "m_replicators"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert cjson_touch == cjson_1
    assert sha_touch == sha_1

    # 2. Re-copy / re-checkout into a distinct directory preserves exact 64-hex SHA-256
    cockpit_copy = tmp_path / "recheckout_clone_beta"
    shutil.copytree(cockpit_a, cockpit_copy)
    _, sha_copy = v4_proc.compute_scope_manifest(
        cockpit_copy / "sources" / "synth_repo",
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core", "m_replicators"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[cockpit_copy / "manuscript" / "Main.tex"],
        cockpit_root=cockpit_copy,
        engine_scripts_dir=synth_eng,
    )
    assert sha_copy == sha_1

    # 3. 1-byte sensitivity across source, paper child, allowlisted data, modules, entrypoints, and engine
    f_core.write_text("def compute_ll(x, beta):\n    return sum(v * beta for v in x) + 0.0\n", encoding="utf-8")
    _, sha_src_edit = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core", "m_replicators"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert sha_src_edit != sha_1

    f_tab_tex.write_text("\\begin{tabular}{lr} LL & 0.76 \\\\ \\end{tabular}\n", encoding="utf-8")
    _, sha_paper_edit = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core", "m_replicators"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert sha_paper_edit not in {sha_1, sha_src_edit}

    f_data.write_text("id,x\n1,0.26\n2,0.75\n", encoding="utf-8")
    _, sha_data_edit = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core", "m_replicators"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert sha_data_edit not in {sha_1, sha_src_edit, sha_paper_edit}

    _, sha_mod_edit = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert sha_mod_edit != sha_data_edit

    eng_py.write_text("ENGINE_VER = 2\n", encoding="utf-8")
    _, sha_eng_edit = v4_proc.compute_scope_manifest(
        repo_a,
        scope_files=["core/kernel.py", "drivers/run_tab1.py"],
        selected_module_ids=["m_core"],
        entrypoints=["drivers/run_tab1.py:main"],
        paper_paths=[f_tex],
        cockpit_root=cockpit_a,
        engine_scripts_dir=synth_eng,
    )
    assert sha_eng_edit != sha_mod_edit

    # 4. Numeric bound refusals (>2 GB data cap via monkeypatch & >8 MB bundle cap via real >8 MB file)
    monkeypatch.setattr(v4_proc, "MAX_ALLOWLISTED_DATA_BYTES", 10)
    with pytest.raises(v4_proc.AnvilRefusalError) as data_bound_err:
        v4_proc.compute_scope_manifest(repo_a, cockpit_root=cockpit_a, engine_scripts_dir=synth_eng)
    assert data_bound_err.value.error_code == "BOUND_EXCEEDED_REFUSAL"
    monkeypatch.undo()

    big_bundle_repo = tmp_path / "oversized_bundle_repo"
    big_bundle_repo.mkdir()
    (big_bundle_repo / "huge_generated.py").write_bytes(b"#" + (b"x" * (8 * 1024 * 1024 + 64)))
    with pytest.raises(v4_proc.AnvilRefusalError) as bundle_bound_err:
        v4_proc.compute_scope_manifest(big_bundle_repo, engine_scripts_dir=synth_eng)
    assert bundle_bound_err.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    # 5. Escape-attempt refusals (.., absolute path, unauthorized data dir, real OS junction)
    outside_dir = tmp_path / "outside_escape_zone"
    outside_dir.mkdir()
    outside_py = outside_dir / "secret.py"
    outside_py.write_text("SECRET = 1\n", encoding="utf-8")
    outside_tex = outside_dir / "leak.tex"
    outside_tex.write_text("leak\n", encoding="utf-8")

    for bad_kwargs in (
        {"scope_files": ["../../../outside_escape_zone/secret.py"]},
        {"scope_files": [str(outside_py)]},
        {"entrypoints": [str(f_drv)]},
        {"data_roots": ["../outside_escape_zone"]},
        {"data_roots": [str(outside_dir)]},
        {"data_roots": ["unallowlisted_notes"]},
        {"paper_paths": ["../../../../outside_escape_zone/leak.tex"]},
        {"paper_paths": [outside_tex]},
        {"selected_module_ids": ["../forged_mod"]},
    ):
        with pytest.raises(v4_proc.AnvilRefusalError) as esc_err:
            v4_proc.compute_scope_manifest(repo_a, cockpit_root=cockpit_a, engine_scripts_dir=synth_eng, **bad_kwargs)
        assert esc_err.value.cwe == "CWE-22"
        assert esc_err.value.error_code == "PATH_ESCAPE_REFUSED"

    junc_data = repo_a / "data" / "junction_out"
    _create_dir_link_or_junction(junc_data, outside_dir)
    try:
        with pytest.raises(v4_proc.AnvilRefusalError) as junc_err:
            v4_proc.compute_scope_manifest(repo_a, cockpit_root=cockpit_a, engine_scripts_dir=synth_eng)
        assert junc_err.value.error_code == "PATH_ESCAPE_REFUSED"
        assert junc_err.value.cwe == "CWE-22"
    finally:
        if os.name == "nt":
            os.rmdir(junc_data)
        else:
            junc_data.unlink()


def test_w1_repo_a_symbol_slicer_equation_binding_and_replication_package(tmp_path: Path) -> None:
    """Synthetic Repo A: `active_moe.py` + `dead_sibling_logit.py` (only 1 helper imported) +
    load-time-imported `utils.py` + manuscript with 1 bound equation and 1 unbound equation.
    Proves:
      - Zero target execution during static AST slicing,
      - `dead_sibling_logit` estimator functions classified `unreached` & excluded from equation binding,
      - Unmatched / dead-only paper equation flagged `status == 'unbound'` in `unbound_equations`,
      - `build_software_architecture_paper_map` emits opaque `^[a-z0-9_-]+$` module IDs + paper links,
      - `materialize_replication_package` retains load-time-imported `utils.py` & `dead_sibling_logit.py`
        so running `run_table1.py` inside `replication_package/` succeeds with zero `ImportError`.
    """
    mods = anvil_session._load_anvil_v4_modules()
    v4_proc = mods["anvil_v4_process"]
    v4_ref = mods["anvil_v4_refactor"]

    repo_a = tmp_path / "synth_repo_a"
    store_a = tmp_path / "synth_store_a"
    (repo_a / "manuscript").mkdir(parents=True)
    (repo_a / "tests").mkdir(parents=True)
    store_a.mkdir(parents=True)

    canary_file = tmp_path / "MUST_NEVER_BE_WRITTEN_DURING_STATIC_SLICE.txt"
    (repo_a / "unreferenced_bomb.py").write_text(
        f"import pathlib\npathlib.Path({canary_file.as_posix()!r}).write_text('BOOM')\n"
        "def trigger_bomb():\n    return 0\n",
        encoding="utf-8",
    )

    (repo_a / "utils.py").write_text(
        textwrap.dedent(
            """\
            import math

            MODULE_LOAD_STAMP = "loaded_cleanly"

            def logsumexp_stable(logits):
                m = max(logits)
                return m + math.log(sum(math.exp(v - m) for v in logits))

            def unused_formatting_helper(items):
                return ",".join(str(x) for x in items)
            """
        ),
        encoding="utf-8",
    )

    (repo_a / "dead_sibling_logit.py").write_text(
        textwrap.dedent(
            """\
            def resolve_step_schedule(total_steps: int) -> list:
                return [max(1, total_steps // 2), total_steps]

            class AbandonedMixedLogit:
                def __init__(self, halton_draws: int = 100):
                    self.halton_draws = halton_draws

                def fit_halton_cholesky_integral(self, cholesky_cov, halton_eta):
                    return sum(c * e for c, e in zip(cholesky_cov, halton_eta))
            """
        ),
        encoding="utf-8",
    )

    (repo_a / "active_moe.py").write_text(
        textwrap.dedent(
            """\
            import utils
            from dead_sibling_logit import resolve_step_schedule

            class ActiveChoiceMixture:
                def __init__(self, num_experts: int = 3):
                    self.num_experts = num_experts

                def compute_expert_gating_loglik(self, gating_pi, beta_price, price_vec):
                    sched = resolve_step_schedule(len(price_vec))
                    expert_terms = [g - beta_price * p for g, p in zip(gating_pi, price_vec)]
                    return utils.logsumexp_stable(expert_terms) + 0.0 * len(sched)
            """
        ),
        encoding="utf-8",
    )

    (repo_a / "run_table1.py").write_text(
        textwrap.dedent(
            """\
            from active_moe import ActiveChoiceMixture

            def replicate_table_1() -> float:
                model = ActiveChoiceMixture(num_experts=3)
                return model.compute_expert_gating_loglik([0.2, 0.5, 0.3], 1.25, [1.0, 2.0, 3.0])

            if __name__ == "__main__":
                val = replicate_table_1()
                assert isinstance(val, float)
            """
        ),
        encoding="utf-8",
    )

    (repo_a / "prep_raw_survey.py").write_text(
        "def convert_raw_survey_csv(rows):\n    return list(rows)\n",
        encoding="utf-8",
    )
    (repo_a / "tests" / "test_unit_moe.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    (repo_a / "workflow.sh").write_text(
        "#!/usr/bin/env bash\n# Step 1: Main Demand Fit (tab:demand_fit)\npython run_table1.py\n",
        encoding="utf-8",
    )

    tex_a = repo_a / "manuscript" / "Main.tex"
    tex_a.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \begin{document}
            \section{Mixture Choice Model}
            Expert gating log-likelihood with price slope:
            \begin{equation}
            \label{eq:moe_gating}
            \ell(\pi, \beta_{price}) = \log \sum_{k=1}^{K} \pi_k \exp(-\beta_{price} \cdot price_k)
            \end{equation}

            \section{Unimplemented Halton Cholesky Integral}
            Simulated Halton Cholesky covariance integral:
            \begin{equation}
            \label{eq:halton_cholesky_unbound}
            \mathcal{I}_{halton} = \int \Phi(\text{cholesky\_cov} \cdot \text{halton\_eta}) \, d\eta
            \end{equation}

            \section{Empirical Results}
            \begin{table}
            \caption{Out-of-Sample Demand Fit}
            \label{tab:demand_fit}
            \begin{tabular}{lr} NLL & 0.6142 \\ \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    slice_res = v4_proc.slice_call_graph(repo_a, entrypoints=["run_table1.py"])
    assert not canary_file.exists(), "Static symbol slicer executed repository code!"
    assert "run_table1.py:replicate_table_1" in slice_res["reached"]
    assert "active_moe.py:ActiveChoiceMixture" in slice_res["reached"]
    assert "active_moe.py:ActiveChoiceMixture.compute_expert_gating_loglik" in slice_res["reached"]
    assert "dead_sibling_logit.py:resolve_step_schedule" in slice_res["reached"]
    assert "utils.py:logsumexp_stable" in slice_res["reached"]

    assert "dead_sibling_logit.py:AbandonedMixedLogit" in slice_res["unreached"]
    assert "dead_sibling_logit.py:AbandonedMixedLogit.fit_halton_cholesky_integral" in slice_res["unreached"]
    assert "utils.py:unused_formatting_helper" in slice_res["unreached"]
    unreached_disclosed_ids = {s["id"] for s in slice_res["unreached_symbols"]}
    assert "dead_sibling_logit.py:AbandonedMixedLogit.fit_halton_cholesky_integral" in unreached_disclosed_ids

    # Equation binding excludes unreached `AbandonedMixedLogit.fit_halton_cholesky_integral`!
    eq_bind = v4_proc.bind_manuscript_equations_to_symbols(
        repo_a, tex_a, entrypoints=["run_table1.py"], scoped=True
    )
    by_lbl = {e["label"]: e for e in eq_bind["equations"]}
    assert by_lbl["eq:moe_gating"]["status"] == "bound"
    assert by_lbl["eq:moe_gating"]["bound_file"] == "active_moe.py"

    assert by_lbl["eq:halton_cholesky_unbound"]["status"] == "unbound"
    assert by_lbl["eq:halton_cholesky_unbound"]["bound_symbol"] is None
    assert any(
        u["label"] == "eq:halton_cholesky_unbound" for u in eq_bind["unbound_equations"]
    )
    assert any(
        "dead_sibling_logit.py" in c["file"]
        for c in by_lbl["eq:halton_cholesky_unbound"]["excluded_unreached_candidates"]
    )

    # Software Architecture & Paper-Linkage Map check
    arch_map = v4_proc.build_software_architecture_paper_map(repo_a, paper_path=tex_a)
    assert arch_map["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", arch_map["scope_sha256"])
    valid_statuses = {"in_scope", "saved_scope", "available", "unscoped_plumbing"}
    for mod_item in arch_map["modules"]:
        assert re.fullmatch(r"^[a-z0-9_-]+$", mod_item["module_id"])
        assert mod_item["scope_status"] in valid_statuses
        assert mod_item["external_literature"]["status"] == "not_requested"
    assert any("tab:demand_fit" in m["local_paper_links"]["tables"] for m in arch_map["modules"])

    # Replication package retains load-time-imported `utils.py` and `dead_sibling_logit.py`
    # even when caller passes only the core files `["run_table1.py", "active_moe.py"]`!
    pkg_res = v4_ref.materialize_replication_package(
        repo_a,
        store_a,
        closure_files=["run_table1.py", "active_moe.py"],
        entrypoints=["run_table1.py"],
        paper_path=tex_a,
    )
    assert pkg_res["ok"] is True
    pkg_dir = Path(pkg_res["package_dir"])
    pkg_files = {p.relative_to(pkg_dir).as_posix() for p in pkg_dir.rglob("*") if p.is_file()}
    assert {"run_table1.py", "active_moe.py", "utils.py", "dead_sibling_logit.py", "REPLICATION_MANIFEST.md"} <= pkg_files
    assert pkg_res["symbol_slice"] is not None
    assert "dead_sibling_logit.py:AbandonedMixedLogit.fit_halton_cholesky_integral" in pkg_res["symbol_slice"]["unreached"]

    # Execute exported package script to prove zero runtime ImportError!
    run_pkg = subprocess.run(
        [sys.executable, "-B", str(pkg_dir / "run_table1.py")],
        cwd=str(pkg_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_pkg.returncode == 0, f"Exported replication_package crashed with ImportError: {run_pkg.stderr}"


def test_w1_repo_b_constructor_attribute_overwrite_pruning(tmp_path: Path) -> None:
    """Synthetic Repo B: verify generic AST constructor-attribute overwrite pruning:
      - Unconditional `self.prior_flow = DeadFlow()` overwritten before read by
        `self.prior_flow = ActiveFlow()` prunes `DeadFlow` & records `shadowed_allocations`.
      - Subclass `super().__init__()` followed by unconditional `self.base_flow = ActiveFlow()`
        prunes `InheritedDeadFlow` when base class is never directly instantiated.
      - Conditional overwrite inside `if flag:` is NEVER pruned.
      - Attribute read between two assignments (`dim = self.read_flow.dim`) is NEVER pruned.
    """
    v4_proc = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]

    repo_b = tmp_path / "synth_repo_b"
    repo_b.mkdir()

    (repo_b / "dead_flows.py").write_text(
        textwrap.dedent(
            """\
            class DeadFlow:
                def __init__(self, dim: int = 4):
                    self.dim = dim

                def log_prob(self, z):
                    return -sum(v * v for v in z)

            class InheritedDeadFlow:
                def __init__(self, dim: int = 4):
                    self.dim = dim

                def log_prob(self, z):
                    return 0.0
            """
        ),
        encoding="utf-8",
    )

    (repo_b / "active_flows.py").write_text(
        textwrap.dedent(
            """\
            class ActiveFlow:
                def __init__(self, dim: int = 4):
                    self.dim = dim

                def log_prob(self, z):
                    return sum(z)

            class FallbackBranchFlow:
                def __init__(self, dim: int = 4):
                    self.dim = dim

                def log_prob(self, z):
                    return sum(z) * 0.5

            class ConditionalOverrideFlow:
                def __init__(self, dim: int = 4):
                    self.dim = dim

                def log_prob(self, z):
                    return sum(z) * 2.0

            class ReadBeforeOverwriteFlow:
                def __init__(self, dim: int = 4):
                    self.dim = dim
            """
        ),
        encoding="utf-8",
    )

    (repo_b / "estimators.py").write_text(
        textwrap.dedent(
            """\
            from dead_flows import DeadFlow, InheritedDeadFlow
            from active_flows import (
                ActiveFlow,
                ConditionalOverrideFlow,
                FallbackBranchFlow,
                ReadBeforeOverwriteFlow,
            )

            class _AbstractBaseFlowModel:
                def __init__(self, dim: int = 4):
                    self.base_flow = InheritedDeadFlow(dim=dim)

            class ShadowingEstimator(_AbstractBaseFlowModel):
                def __init__(self, dim: int = 4, use_override: bool = False):
                    super().__init__(dim=dim)
                    self.base_flow = ActiveFlow(dim=dim)

                    self.prior_flow = DeadFlow(dim=dim)
                    self.scale = 1.0
                    self.prior_flow = ActiveFlow(dim=dim)

                    self.branch_flow = FallbackBranchFlow(dim=dim)
                    if use_override:
                        self.branch_flow = ConditionalOverrideFlow(dim=dim)

                    self.staged = ReadBeforeOverwriteFlow(dim=dim)
                    observed_dim = self.staged.dim
                    self.staged = ActiveFlow(dim=observed_dim)

                def evaluate(self, z):
                    return self.prior_flow.log_prob(z) + self.branch_flow.log_prob(z) + self.base_flow.log_prob(z)
            """
        ),
        encoding="utf-8",
    )

    (repo_b / "run_bench.py").write_text(
        textwrap.dedent(
            """\
            from estimators import ShadowingEstimator

            def main():
                est = ShadowingEstimator(dim=4, use_override=True)
                return est.evaluate([1.0, 2.0])

            if __name__ == "__main__":
                main()
            """
        ),
        encoding="utf-8",
    )

    res_b = v4_proc.slice_call_graph(repo_b, entrypoints=["run_bench.py"])
    reached_b = set(res_b["reached"])
    unreached_b = set(res_b["unreached"])

    # Shadowed `DeadFlow` and `InheritedDeadFlow` (and their `.log_prob` methods!) MUST be unreached
    assert "dead_flows.py:DeadFlow" in unreached_b
    assert "dead_flows.py:DeadFlow.__init__" in unreached_b
    assert "dead_flows.py:DeadFlow.log_prob" in unreached_b
    assert "dead_flows.py:InheritedDeadFlow" in unreached_b
    assert "dead_flows.py:InheritedDeadFlow.log_prob" in unreached_b

    shadowed_syms = {
        sym_id
        for item in res_b["shadowed_allocations"]
        for sym_id in item["shadowed_symbols"]
    }
    assert "dead_flows.py:DeadFlow" in shadowed_syms
    assert "dead_flows.py:InheritedDeadFlow" in shadowed_syms

    # Active overwrite, conditional `if use_override:` branch, and read-before-overwrite MUST stay reached!
    assert "active_flows.py:ActiveFlow" in reached_b
    assert "active_flows.py:ActiveFlow.log_prob" in reached_b
    assert "active_flows.py:FallbackBranchFlow" in reached_b
    assert "active_flows.py:ConditionalOverrideFlow" in reached_b
    assert "active_flows.py:ReadBeforeOverwriteFlow" in reached_b


def test_w1_repo_c_heldout_subpackages_dynamic_dispatch_and_zero_paper_identifiers(tmp_path: Path) -> None:
    """Held-out Synthetic Repo C (multi-subpackage layout with `REGISTRY[name]`,
    `getattr(plugin_mod, fn_name)`, `@register_hook` decorator, and `globals()[...]`)
    plus the zero-paper-identifier grep gate across Foundry & vendor Anvil scripts.
    """
    v4_proc = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]

    repo_c = tmp_path / "synth_repo_c"
    for sub in (
        "pkg_gamma",
        "pkg_gamma/kernel",
        "pkg_gamma/solvers",
        "pkg_gamma/plugins",
        "pkg_gamma/drivers",
        "pkg_gamma/superseded_v0",
    ):
        d = repo_c / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text("", encoding="utf-8")

    (repo_c / "pkg_gamma" / "kernel" / "objective.py").write_text(
        "def quadratic_penalty(x):\n    return sum(v * v for v in x)\n",
        encoding="utf-8",
    )

    (repo_c / "pkg_gamma" / "solvers" / "registry.py").write_text(
        textwrap.dedent(
            """\
            from pkg_gamma.kernel.objective import quadratic_penalty

            class QuasiNewtonSolver:
                def solve(self, x):
                    return quadratic_penalty(x)

            def coordinate_descent_solver(x):
                return quadratic_penalty(x) * 0.5

            SOLVER_REGISTRY = {
                "qn": QuasiNewtonSolver,
                "cd": coordinate_descent_solver,
            }
            """
        ),
        encoding="utf-8",
    )

    (repo_c / "pkg_gamma" / "plugins" / "hooks.py").write_text(
        textwrap.dedent(
            """\
            def register_hook(fn):
                return fn

            def postprocess_alpha(val):
                return val + 1.0

            def postprocess_beta(val):
                return val + 2.0

            @register_hook
            def decorated_audit_callback(val):
                return val
            """
        ),
        encoding="utf-8",
    )

    (repo_c / "pkg_gamma" / "superseded_v0" / "abandoned_solver.py").write_text(
        "def obsolete_grid_search(x):\n    return 0.0\n",
        encoding="utf-8",
    )

    (repo_c / "pkg_gamma" / "drivers" / "cli_runner.py").write_text(
        textwrap.dedent(
            """\
            from pkg_gamma.solvers.registry import SOLVER_REGISTRY
            from pkg_gamma.plugins import hooks

            def run_experiment(solver_key: str, hook_name: str, x: list) -> float:
                solver_entry = SOLVER_REGISTRY[solver_key]
                raw_val = solver_entry().solve(x) if isinstance(solver_entry, type) else solver_entry(x)
                hook_fn = getattr(hooks, hook_name)
                return hook_fn(raw_val)

            if __name__ == "__main__":
                run_experiment("qn", "postprocess_alpha", [1.0, 2.0])
            """
        ),
        encoding="utf-8",
    )

    res_c = v4_proc.slice_call_graph(repo_c, entrypoints=["pkg_gamma/drivers/cli_runner.py"])
    reached_c = set(res_c["reached"])
    uncertain_c = set(res_c["uncertain"])
    unreached_c = set(res_c["unreached"])

    assert "pkg_gamma/drivers/cli_runner.py:run_experiment" in reached_c
    # Dynamic registry & getattr & decorated targets MUST remain visible in `uncertain` (never dropped!)
    assert "pkg_gamma/solvers/registry.py:QuasiNewtonSolver" in uncertain_c
    assert "pkg_gamma/solvers/registry.py:QuasiNewtonSolver.solve" in uncertain_c
    assert "pkg_gamma/solvers/registry.py:coordinate_descent_solver" in uncertain_c
    assert "pkg_gamma/plugins/hooks.py:postprocess_alpha" in uncertain_c
    assert "pkg_gamma/plugins/hooks.py:postprocess_beta" in uncertain_c
    assert "pkg_gamma/plugins/hooks.py:decorated_audit_callback" in uncertain_c
    # Transitive callee of uncertain solvers is also preserved (never dropped!)
    assert "pkg_gamma/kernel/objective.py:quadratic_penalty" in (reached_c | uncertain_c)
    # Genuinely unreferenced superseded subpackage is classified `unreached`
    assert "pkg_gamma/superseded_v0/abandoned_solver.py:obsolete_grid_search" in unreached_c

    # Zero-paper-identifier grep gate across Foundry & vendor Anvil `.py` scripts
    forbidden_substrings = [
        "het" + "nn",
        "rc_" + "logit",
        "hyper_" + "flow",
        "hierarchical" + "normalizingflows",
        "binn_" + "neurips",
        "mixtureofexperts" + "mnl",
        "step2_" + "runner",
        "run_panel_" + "ss",
        "tab:" + "panelss",
        "tab:" + "mixedlm",
        "tab:" + "hlr",
        "good" + "year",
        "sam" + "sung",
        "pro" + "lific",
    ]
    baseline_json = PLAN_DIR / ".crucible" / "research-repos-baseline-sha256.json"
    generic_stem_allow = {
        "__init__",
        "conftest",
        "setup",
        "main",
        "utils",
        "data_utils",
        "metrics_utils",
        "prepare_data",
        "make_minimal_data",
        "replicate",
        "replication_bundle",
        "manuscript_scope",
        "eval_all_tasks",
        "run_all",
    }
    if baseline_json.is_file():
        baseline_doc = json.loads(baseline_json.read_text(encoding="utf-8"))
        for repo_entry in baseline_doc.values():
            if not isinstance(repo_entry, dict):
                continue
            for rel_key in (repo_entry.get("files") or {}).keys():
                p_rel = Path(str(rel_key))
                if p_rel.suffix.lower() != ".py":
                    continue
                stem_low = p_rel.stem.lower()
                if (
                    len(stem_low) >= 12
                    and "_" in stem_low
                    and not stem_low.startswith("test_")
                    and stem_low not in generic_stem_allow
                ):
                    forbidden_substrings.append(stem_low)

    hnf_word_re = re.compile(r"(?<![a-z])" + "hn" + r"f2?(?![a-z])", re.IGNORECASE)

    violations: list[str] = []
    for scripts_dir in (FOUNDRY_SCRIPTS_DIR, VENDOR_SCRIPTS_DIR):
        py_list = sorted(scripts_dir.glob("*.py"))
        assert len(py_list) >= 6
        for py_fp in py_list:
            txt_low = py_fp.read_text(encoding="utf-8").lower()
            for bad_tok in forbidden_substrings:
                if bad_tok in txt_low:
                    violations.append(f"{py_fp.name}: forbidden token {bad_tok!r}")
            if hnf_word_re.search(txt_low):
                violations.append(f"{py_fp.name}: forbidden paper identifier matched hnf_word_re")
    assert violations == [], f"Paper-specific identifier violations: {violations}"

    # Also verify `distro.scan_paths` passes cleanly on our new Wave 1 files
    w1_check_files = [
        VENDOR_SCRIPTS_DIR / "anvil_v4_process.py",
        VENDOR_SCRIPTS_DIR / "anvil_v4_refactor.py",
        SYNC_SCRIPT,
        Path(__file__).resolve(),
    ]
    scan_hits = distro.scan_paths(
        [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in w1_check_files],
        root=ANCHOR_ROOT,
    )
    assert scan_hits == [], f"distro.scan_paths flagged Wave 1 files: {scan_hits}"


def test_w1_locked_mockups_sha256_and_headless_ft_look_contract(tmp_path: Path) -> None:
    """Verify `LOCKED-MOCKUPS.json` SHA-256 digests and execute headless `ft.py look --check`
    on BOTH locked v2 mockups (`scoping-v2-option2-software-map.html` and
    `replication-v2-dossier-matrix-refactoring.html`), asserting exit 0, `errors == []`,
    all key selectors `painted` and `onScreen`, and zero `chrome-open` calls in test code.
    """
    assert LOCKED_MOCKUPS_JSON.is_file()
    locked_doc = json.loads(LOCKED_MOCKUPS_JSON.read_text(encoding="utf-8"))
    mockups_meta: Dict[str, Dict[str, Any]] = locked_doc["mockups"]
    assert set(mockups_meta.keys()) == {
        "scoping-v2-option2-software-map.html",
        "replication-v2-dossier-matrix-refactoring.html",
    }

    selector_contracts = {
        "scoping-v2-option2-software-map.html": {
            "above_fold": "#doneShelf,#mainStage,#softwareMapScroll,#convScroll,#receiptCol,#btnRpToggle,#btnExpandMap,#msgBox",
            "all_painted": "#doneShelf,#mainStage,#softwareMapScroll,#convScroll,#receiptCol,#btnRpToggle,#btnExpandMap,#msgBox",
        },
        "replication-v2-dossier-matrix-refactoring.html": {
            "above_fold": "#reportRoot,#sec-summary,.jump-nav",
            "all_painted": "#reportRoot,#sec-summary,#sec-matrix,#sec-refactoring,.audit-grid,.fix-card",
        },
    }

    out_shots = tmp_path / "look_shots"
    out_shots.mkdir()

    for m_name, meta in mockups_meta.items():
        m_path = PLAN_DIR / "mockups" / m_name
        assert m_path.is_file(), f"Locked mockup missing: {m_name}"
        raw_bytes = m_path.read_bytes()
        assert len(raw_bytes) == int(meta["bytes"]), f"Byte count drift on {m_name}"
        assert hashlib.sha256(raw_bytes).hexdigest() == meta["sha256"], f"SHA-256 drift on {m_name}"

        above_csv = selector_contracts[m_name]["above_fold"]
        all_csv = selector_contracts[m_name]["all_painted"]
        proc = subprocess.run(
            [
                sys.executable,
                str(FT_PY),
                "look",
                str(m_path),
                "--size",
                "1560x960",
                "--out",
                str(out_shots),
                "--check",
                above_csv,
                "--check",
                all_csv,
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        assert proc.returncode == 0, f"ft.py look failed on {m_name}: {proc.stderr}\n{proc.stdout}"
        verdict = json.loads(proc.stdout)
        results = verdict.get("results") or []
        assert len(results) == 1
        res0 = results[0]
        assert res0["errors"] == [], f"Console/page errors on {m_name}: {res0['errors']}"

        above_checks = res0["checks"][above_csv]
        assert len(above_checks) >= len(above_csv.split(","))
        for chk in above_checks:
            assert chk["painted"] is True, f"Unpainted above-fold selector in {m_name}: {chk}"
            assert chk["onScreen"] is True, f"Off-screen above-fold selector in {m_name}: {chk}"

        all_checks = res0["checks"][all_csv]
        assert len(all_checks) >= len(all_csv.split(","))
        for chk in all_checks:
            assert chk["painted"] is True, f"Unpainted section selector in {m_name}: {chk}"
            assert chk["coveredBy"] is None and chk["hiddenBy"] is None, f"Obscured selector in {m_name}: {chk}"

    # Verify unattended test suites never invoke interactive `chrome-open`
    own_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bad_chrome_calls = [
        node.value
        for node in ast.walk(own_tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == ("chrome-" + "open")
    ]
    assert bad_chrome_calls == []


def test_w1_anvil_v6_gate_selftests(tmp_path: Path) -> None:
    """Self-test `anvil-v6-gate.mjs`:
      1) `PLANNED_WAVE_SUITES[0..3]` all match `ANCHOR_ANVIL_V6_SUITES_RE`.
      2) `inferMinimumWaveFromForemanState(tmpPlanDir, tmpRepoRoot)` ignores out-of-plan
         checkpoints (e.g. `2026-11-22`), honors in-plan `current_wave`, and honors anchored
         `Wave N/M GREEN ... appended by orchestrator on GO` lines while ignoring prose mentions.
      3) Non-zero exit on missing owed suite file and on skipped required tests (`enforceNoSkippedRequired`).
    """
    node_probe_js = textwrap.dedent(
        f"""\
        import assert from 'node:assert/strict';
        import fs from 'node:fs';
        import path from 'node:path';
        import {{ pathToFileURL }} from 'node:url';

        const gateMod = await import(pathToFileURL({json.dumps(str(GATE_MJS))}).href);
        const tmpRoot = {json.dumps(str(tmp_path))};

        // 1. All 4 planned wave suites match ANCHOR_ANVIL_V6_SUITES_RE
        assert.equal(gateMod.PLANNED_WAVE_SUITES.length, 4);
        for (const rel of gateMod.PLANNED_WAVE_SUITES) {{
          const base = path.basename(rel);
          assert.equal(gateMod.ANCHOR_ANVIL_V6_SUITES_RE.test(base), true, `Regex failed on ${{base}}`);
        }}

        // 2. enforceNoSkippedRequired catches skipped/xfailed output
        assert.equal(gateMod.enforceNoSkippedRequired('4 passed in 0.12s').ok, true);
        assert.equal(gateMod.enforceNoSkippedRequired('3 passed, 1 skipped in 0.12s').ok, false);
        assert.equal(gateMod.enforceNoSkippedRequired('test_foo.py::test_a SKIPPED').ok, false);
        assert.equal(gateMod.enforceNoSkippedRequired('3 passed, 1 xfailed in 0.12s').ok, false);

        // 3. inferMinimumWaveFromForemanState scoping tests
        const repoDir = path.join(tmpRoot, 'fake_repo');
        const planDir = path.join(repoDir, 'planning', '2026-11-23-anvil-scoping-and-comprehension');
        const otherPlanDir = path.join(repoDir, 'planning', '2026-11-22-anvil-cockpit-multi-analysis');
        fs.mkdirSync(planDir, {{ recursive: true }});
        fs.mkdirSync(otherPlanDir, {{ recursive: true }});

        // 3a. Out-of-plan foreman-checkpoint.json (pointing to 2026-11-22) MUST be ignored -> 0
        fs.writeFileSync(
          path.join(repoDir, 'foreman-checkpoint.json'),
          JSON.stringify({{ plan_path: path.join(otherPlanDir, 'IMPLEMENTATION-PLAN.md'), current_wave: 4 }}),
        );
        assert.equal(gateMod.inferMinimumWaveFromForemanState(planDir, repoDir), 0);

        // 3b. Unanchored prose mention of 'Wave 4 GREEN' in EXECUTION-LOG.md MUST be ignored -> 0
        fs.writeFileSync(
          path.join(planDir, 'EXECUTION-LOG.md'),
          'Notes: Wave 4 GREEN will run after Wave 3 finishes.\\n',
        );
        assert.equal(gateMod.inferMinimumWaveFromForemanState(planDir, repoDir), 0);

        // 3c. Anchored orchestrator GO line is honored -> 2
        fs.writeFileSync(
          path.join(planDir, 'EXECUTION-LOG.md'),
          '### Wave 2/4 GREEN — 2026-11-23T20:00:00Z (appended by orchestrator on GO)\\n',
        );
        assert.equal(gateMod.inferMinimumWaveFromForemanState(planDir, repoDir), 2);

        // 3d. In-plan foreman-checkpoint.json current_wave: 3 raises floor -> 3
        fs.writeFileSync(
          path.join(repoDir, 'foreman-checkpoint.json'),
          JSON.stringify({{ plan_path: path.join(planDir, 'IMPLEMENTATION-PLAN.md'), current_wave: 3 }}),
        );
        assert.equal(gateMod.inferMinimumWaveFromForemanState(planDir, repoDir), 3);
        console.log('GATE_UNIT_PROBES_OK');
        """
    )
    probe_proc = subprocess.run(
        ["node", "--input-type=module", "-e", node_probe_js],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert probe_proc.returncode == 0, f"Gate unit probes failed: {probe_proc.stderr}\n{probe_proc.stdout}"
    assert "GATE_UNIT_PROBES_OK" in probe_proc.stdout

    # 4. CLI fail-closed check: empty owedSuites + zero v6 suites with --require-v6 -> non-zero exit
    empty_anchor = tmp_path / "empty_anchor_repo"
    empty_scripts = empty_anchor / "planning" / "2026-11-23-anvil-scoping-and-comprehension" / "scripts"
    empty_scripts.mkdir(parents=True)
    (empty_anchor / "tests").mkdir(parents=True)
    copied_gate = empty_scripts / "anvil-v6-gate.mjs"
    shutil.copy2(GATE_MJS, copied_gate)
    (empty_scripts / "required-suites.json").write_text(
        json.dumps({"schema": "anvil-v6-required-suites/v1", "owedSuites": []}),
        encoding="utf-8",
    )
    empty_proc = subprocess.run(
        ["node", str(copied_gate), "--require-v6"],
        cwd=str(empty_anchor),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert empty_proc.returncode != 0
    assert (
        "REQUIRED_V6_SUITE_EMPTY_REFUSED" in (empty_proc.stderr + empty_proc.stdout)
        or "OWED_SUITE_MISSING_REFUSED" in (empty_proc.stderr + empty_proc.stdout)
    )

    # 5. CLI fail-closed check: missing owed suite in manifest -> non-zero exit
    missing_manifest = tmp_path / "missing-owed.json"
    missing_manifest.write_text(
        json.dumps({
            "schema": "anvil-v6-required-suites/v1",
            "owedSuites": ["tests/test_nonexistent_missing_suite_2026_11_23.py"],
        }),
        encoding="utf-8",
    )
    miss_proc = subprocess.run(
        ["node", str(GATE_MJS), f"--owed-suites-file={missing_manifest}", "--require-v6"],
        cwd=str(ANCHOR_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert miss_proc.returncode != 0
    assert "OWED_SUITE_MISSING_REFUSED" in (miss_proc.stderr + miss_proc.stdout)

    # 5. CLI fail-closed check: skipped test in required suite -> non-zero exit
    skip_py = tmp_path / "test_w1_anvil_synth_skip_2026_11_23.py"
    skip_py.write_text(
        "import pytest\n\ndef test_passes():\n    assert True\n\n"
        "@pytest.mark.skip(reason='must trigger fail-closed skip gate')\ndef test_skipped():\n    assert True\n",
        encoding="utf-8",
    )
    skip_proc = subprocess.run(
        ["node", str(GATE_MJS), f"--suite-override={skip_py}"],
        cwd=str(ANCHOR_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert skip_proc.returncode != 0
    assert "REQUIRED_TEST_SKIP_REFUSED" in (skip_proc.stderr + skip_proc.stdout)


def test_w1_wave1_review_repros_soundness_and_sync_guards(tmp_path: Path) -> None:
    """Regression suite covering all Wave 1 dual-Fable-5.2 findings:
      - Registry `.items()`/`.values()`, module-qualified `reg.SOLVERS[k]`, callable lists, cross-file `getattr(instance, m)`.
      - Bound methods (`minimize(self.neg_loglik)`), module-qualified callbacks (`pool.map(workers.run_rep)`), class values.
      - Subclass method overrides (`Sub._penalty`) via RTA + flow-safe `local_var_classes` union across reassignments.
      - Decorators (`@standardize`), `@property`, dunder protocols, import-time calls across import closure, lazy imports.
      - Sound `__init__` overwrite pruning (`return`, `self.setup()`, `super().__init__()`, subclass `self.flow` override).
      - Explicit unresolved entrypoints -> `ok=False`, `unresolved_entrypoints=[...]`.
      - `compute_scope_manifest` clamps `max_data_bytes` & `max_bundle_bytes` and hashes contained `../shared/*.tex` inputs.
      - `resolve_manuscript_path` & `bind_manuscript_equations_to_symbols` fail closed on `../` without `allowed_root`.
      - `sync_anvil_vendor.py` refuses non-Anvil `--vendor-root` and never deletes `foundry_root/tests` or `journal`.
    """
    v4_proc = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]

    # 1. Registry `.items()`, module-qualified subscript, callable list, cross-file instance `getattr`
    r1 = tmp_path / "repro_dispatch"
    r1.mkdir()
    (r1 / "reg.py").write_text(
        "def s_a(x):\n    return x\ndef s_b(x):\n    return x + 1\n"
        "SOLVERS = {'a': s_a, 'b': s_b}\nMODELS = [s_a, s_b]\n",
        encoding="utf-8",
    )
    (r1 / "plugins.py").write_text(
        "class HookRunner:\n    def hook_one(self, v):\n        return v * 2\n",
        encoding="utf-8",
    )
    (r1 / "run.py").write_text(
        "import reg\nfrom plugins import HookRunner\n"
        "def main(k, m):\n"
        "    out = 0\n"
        "    for _, fn in reg.SOLVERS.items():\n        out += fn(1)\n"
        "    fn2 = reg.SOLVERS[k]\n"
        "    cls_or_fn = reg.MODELS[0]\n"
        "    hr = HookRunner()\n"
        "    cb = getattr(hr, m)\n"
        "    return fn2(out) + cls_or_fn(1) + cb(2)\n"
        "if __name__ == '__main__':\n    main('a', 'hook_one')\n",
        encoding="utf-8",
    )
    sl1 = v4_proc.slice_call_graph(r1, entrypoints=["run.py"])
    assert sl1["ok"] is True
    vis1 = set(sl1["reached"]) | set(sl1["uncertain"])
    assert "reg.py:s_a" in vis1
    assert "reg.py:s_b" in vis1
    assert "plugins.py:HookRunner.hook_one" in vis1

    # 2. Callbacks, class values, RTA subclass overrides, flow-safe `local_var_classes` union, implicit protocols
    r2 = tmp_path / "repro_rta_flow"
    r2.mkdir()
    (r2 / "workers.py").write_text(
        "def wrap_dec(fn):\n    return fn\n"
        "def init_grid():\n    return [1, 2]\n"
        "GRID = init_grid()\n"
        "def run_rep(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    (r2 / "models.py").write_text(
        "from workers import wrap_dec\n"
        "class BaseEst:\n"
        "    def fit(self, x):\n        return self._penalty(x)\n"
        "    def _penalty(self, x):\n        return 0.0\n"
        "class SubEst(BaseEst):\n"
        "    def _penalty(self, x):\n        return 1.5 * x\n"
        "class AltEst:\n"
        "    @property\n    def score_prop(self):\n        return 42.0\n"
        "    def __call__(self, z):\n        return z + self.score_prop\n"
        "    @wrap_dec\n    def fit(self, x):\n        return self(x)\n",
        encoding="utf-8",
    )
    (r2 / "driver.py").write_text(
        "import workers\n"
        "def minimize(fn, x0):\n    return fn(x0)\n"
        "class Problem:\n"
        "    def neg_loglik(self, x):\n        return x * x\n"
        "    def solve(self):\n        return minimize(self.neg_loglik, 2.0)\n"
        "def run_all():\n"
        "    from models import SubEst, AltEst\n"
        "    m = SubEst()\n    m.fit(1.0)\n"
        "    m = AltEst()\n    m.fit(2.0)\n"
        "    for cls in (SubEst, AltEst):\n        cls().fit(3.0)\n"
        "    list(map(workers.run_rep, workers.GRID))\n"
        "    return Problem().solve()\n"
        "if __name__ == '__main__':\n    run_all()\n",
        encoding="utf-8",
    )
    sl2 = v4_proc.slice_call_graph(r2, entrypoints=["driver.py"])
    vis2 = set(sl2["reached"]) | set(sl2["uncertain"])
    assert "workers.py:init_grid" in vis2
    assert "workers.py:wrap_dec" in vis2
    assert "workers.py:run_rep" in vis2
    assert "models.py:SubEst._penalty" in vis2
    assert "models.py:BaseEst.fit" in vis2
    assert "models.py:AltEst.fit" in vis2
    assert "models.py:AltEst.score_prop" in vis2
    assert "models.py:AltEst.__call__" in vis2
    assert "driver.py:Problem.neg_loglik" in vis2

    # 3. Sound `__init__` overwrite pruning (`return`, `self.setup()`, subclass `self.flow = ActiveFlow()`)
    r3 = tmp_path / "repro_init_soundness"
    r3.mkdir()
    (r3 / "flows.py").write_text(
        "class EarlyFlow:\n    def log_prob(self):\n        return 1.0\n"
        "class LateFlow:\n    def log_prob(self):\n        return 2.0\n"
        "class SubFlow:\n    def log_prob(self):\n        return 3.0\n"
        "class GuardedModel:\n"
        "    def __init__(self, fast=True):\n"
        "        self.flow = EarlyFlow()\n"
        "        if fast:\n            return\n"
        "        self.flow = LateFlow()\n"
        "    def eval_ll(self):\n        return self.flow.log_prob()\n"
        "class SubGuarded(GuardedModel):\n"
        "    def __init__(self):\n"
        "        super().__init__(fast=False)\n"
        "        self.flow = SubFlow()\n"
        "if __name__ == '__main__':\n"
        "    GuardedModel(True).eval_ll()\n"
        "    SubGuarded().eval_ll()\n",
        encoding="utf-8",
    )
    sl3 = v4_proc.slice_call_graph(r3, entrypoints=["flows.py"])
    vis3 = set(sl3["reached"]) | set(sl3["uncertain"])
    assert "flows.py:EarlyFlow.log_prob" in vis3
    assert "flows.py:LateFlow.log_prob" in vis3
    assert "flows.py:SubFlow.log_prob" in vis3

    # 4. Explicit unresolved entrypoint returns `ok=False`
    sl_bad = v4_proc.slice_call_graph(r3, entrypoints=["nonexistent_entry.py"])
    assert sl_bad["ok"] is False
    assert "nonexistent_entry.py" in sl_bad.get("unresolved_entrypoints", [])

    # 5. `compute_scope_manifest` clamps `max_data_bytes`/`max_bundle_bytes` & hashes contained `../shared/macros.tex`
    ws_root = tmp_path / "cockpit_ws"
    code_dir = ws_root / "code"
    paper_sub = ws_root / "papers" / "main_doc"
    shared_tex = ws_root / "papers" / "shared"
    code_dir.mkdir(parents=True)
    paper_sub.mkdir(parents=True)
    shared_tex.mkdir(parents=True)
    (code_dir / "est.py").write_text("def fit(x):\n    return x\n", encoding="utf-8")
    macro_file = shared_tex / "macros.tex"
    macro_file.write_text("\\newcommand{\\EstLoss}{\\mathcal{L}}\n", encoding="utf-8")
    main_tex = paper_sub / "main.tex"
    main_tex.write_text(
        "\\documentclass{article}\n\\input{../shared/macros}\n\\begin{document}\n$\\EstLoss$\n\\end{document}\n",
        encoding="utf-8",
    )
    _, sha_v1 = v4_proc.compute_scope_manifest(
        code_dir,
        selected_module_ids=["mod_est"],
        scope_files=["est.py"],
        paper_paths=[main_tex],
        cockpit_root=ws_root,
        max_data_bytes=10**15,
        max_bundle_bytes=10**15,
    )
    macro_file.write_text("\\newcommand{\\EstLoss}{\\widetilde{\\mathcal{L}}}\n", encoding="utf-8")
    _, sha_v2 = v4_proc.compute_scope_manifest(
        code_dir,
        selected_module_ids=["mod_est"],
        scope_files=["est.py"],
        paper_paths=[main_tex],
        cockpit_root=ws_root,
    )
    assert sha_v1 != sha_v2

    # Default boundary pinning on `resolve_manuscript_path` & `bind_manuscript_equations_to_symbols`
    (ws_root / "SECRET.tex").write_text("secret\n", encoding="utf-8")
    with pytest.raises(v4_proc.AnvilRefusalError) as exc_rel:
        v4_proc.bind_manuscript_equations_to_symbols(code_dir, "../SECRET.tex")
    assert exc_rel.value.error_code == "PATH_ESCAPE_REFUSED"

    # 6. `sync_anvil_vendor.py` refuses wrong `--vendor-root` and leaves `foundry_root/tests` untouched
    fake_foundry = tmp_path / "fake_foundry"
    (fake_foundry / "scripts").mkdir(parents=True)
    (fake_foundry / "static").mkdir(parents=True)
    (fake_foundry / "tests").mkdir(parents=True)
    (fake_foundry / "journal").mkdir(parents=True)
    (fake_foundry / "SKILL.md").write_text("# Anvil\n", encoding="utf-8")
    (fake_foundry / "FLOW.json").write_text("{}\n", encoding="utf-8")
    (fake_foundry / "scripts" / "anvil_v4_process.py").write_text("X = 1\n", encoding="utf-8")
    (fake_foundry / "static" / "anvil_v4_workbench.html").write_text("<html></html>\n", encoding="utf-8")
    sentinel_test = fake_foundry / "tests" / "keep_me.py"
    sentinel_test.write_text("assert True\n", encoding="utf-8")
    wrong_vendor = tmp_path / "not_anvil_vendor"
    wrong_vendor.mkdir()
    (wrong_vendor / "unrelated.txt").write_text("do not delete\n", encoding="utf-8")
    bad_sync = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--foundry-root", str(fake_foundry), "--vendor-root", str(wrong_vendor)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert bad_sync.returncode != 0
    assert (wrong_vendor / "unrelated.txt").is_file()
    assert sentinel_test.is_file()

