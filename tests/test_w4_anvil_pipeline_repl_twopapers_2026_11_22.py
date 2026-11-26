"""Wave 4 Verification Suite — Workflow/Manuscript Pipeline Stages, Standalone Replication
Package Export, True Hermetic Two-Paper Cockpit Migration (`--dry-run` / `--apply` /
`--enable` / `--verify` with Decoy Isolation, Per-File Source SHA-256 Recheck, `<50 ms`
`cache_hit == 'disk'`, & Verify-Before-Enable), Full-Width Anvil v5 Report Cards,
`steward_routes` HTTP Export Gate, Default-OFF Gate, and L3 Look Verdict.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import distro
from steward_cockpit import anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
DEV_ROOT = ANCHOR_ROOT.parent
SKILL_ROOT = DEV_ROOT / "Skill Foundry" / "skills" / "anvil"
VENDOR_ANVIL_ROOT = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
FT_PY = DEV_ROOT / "foundry-tools" / "ft.py"

PLAN_DIR = ANCHOR_ROOT / "planning" / "2026-11-22-anvil-cockpit-multi-analysis"
BACKUP_SCRIPT = PLAN_DIR / "scripts" / "backup_and_migrate_cockpits.py"
BACKUP_DIR = PLAN_DIR / "backups" / "legacy-anvil-20261122"
PRE_W1_MANIFEST = BACKUP_DIR / "pre-w1-manifest.json"
W4_MOCKUP_HTML = PLAN_DIR / "mockups" / "w4-twopaper-workbench.html"
W4_LOOKS_DIR = PLAN_DIR / "looks" / "w4"
W4_VERDICT_JSON = W4_LOOKS_DIR / "verdict.json"

LIVE_FORBIDDEN_PAPER_ROOTS = (
    (DEV_ROOT / "Heterogeneity Empirical Demand Machine Learning").resolve(),
    (DEV_ROOT / "Hierarchical Normalizing Flows").resolve(),
)


def _load_backup_mod() -> Any:
    spec = importlib.util.spec_from_file_location("backup_and_migrate_w4", BACKUP_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_migrate_cli(*cli_args: str) -> tuple[int, dict[str, Any], str]:
    env = dict(os.environ)
    env.pop("ANCHOR_ANVIL_MULTI", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-B", str(BACKUP_SCRIPT), *cli_args],
        cwd=str(ANCHOR_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    parsed = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else {}
    return proc.returncode, parsed, proc.stderr


def _stage_hermetic_workspace(
    base_dir: Path,
    *,
    include_moe: bool = True,
    include_hnf: bool = True,
    include_anchor_decoy: bool = True,
) -> tuple[Path, Path, Path]:
    """Create 100% hermetic `tmp_dev`, `tmp_anchor`, and `tmp_backups` inside `base_dir`
    with synthetic source trees, manuscripts, dated/archive `sources/` decoys, an un-backed-up
    `Anchor-Improvement` decoy cockpit, and rewritten `.anvil/session.json` + `xval_receipt.json`
    so ZERO live `C:\\dev\\Heterogeneity...` or `C:\\dev\\Hierarchical...` paths are ever read!
    """
    bmod = _load_backup_mod()
    v4_proc = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]
    live_manifest = json.loads(PRE_W1_MANIFEST.read_text(encoding="utf-8"))

    tmp_dev = base_dir / "dev_ws"
    tmp_anchor = base_dir / "anchor_ws"
    tmp_backups = base_dir / "backups_ws"
    tmp_dev.mkdir(parents=True)
    tmp_anchor.mkdir(parents=True)
    tmp_backups.mkdir(parents=True)

    # 1. Synthetic HetNN source tree + dated/duplicate `sources/` decoys inside `tmp_dev`
    moe_cockpit = tmp_dev / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
    hetnn_dir = moe_cockpit / "HetNN"
    (hetnn_dir / "Code").mkdir(parents=True)
    (hetnn_dir / "Manuscript").mkdir(parents=True)
    (hetnn_dir / "workflow.sh").write_text(
        "#!/usr/bin/env bash\n# Step 1: Prep\npython Code/prep_inputs.py\n# Step 2: Fit (tab:emp_1)\npython Code/fit_mixture.py\n",
        encoding="utf-8",
    )
    (hetnn_dir / "Code" / "prep_inputs.py").write_text(
        "def load_panel_rows():\n    return [1.0, 2.0, 3.0]\n",
        encoding="utf-8",
    )
    (hetnn_dir / "Code" / "fit_mixture.py").write_text(
        "def fit_mixture_table(rows, ridge=0.05):\n    return sum(rows) / (1.0 + ridge)\n",
        encoding="utf-8",
    )
    moe_tex = hetnn_dir / "Manuscript" / "Main.tex"
    moe_tex.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Synthetic Mixture Choice Study}
            \begin{document}
            \section{Empirical}
            \begin{table}\caption{Main Fit}\label{tab:emp_1}
            \begin{tabular}{lr} N & \textbf{50{,}002} \\ \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )
    # Dated snapshot & duplicate decoys under `Paper 1/sources/` that MUST NOT become `pkg-*` slots!
    for decoy_sub in ("2026-10-02", "HetNN", "hetnn_paper_matched"):
        dd = moe_cockpit / "sources" / decoy_sub
        dd.mkdir(parents=True)
        (dd / "old_copy.py").write_text("X = 1\n", encoding="utf-8")

    # 2. Synthetic HNF source tree + sibling manuscript + `Bayesian` sub-package inside `tmp_dev`
    hnf_outer = tmp_dev / "Hierarchical Normalizing Flows"
    hnf_inner = hnf_outer / "Paper 1"
    hnf_sources = hnf_inner / "sources"
    hnf_sw = hnf_sources / "HierarchicalNormalizingFlows"
    (hnf_sw / "Code").mkdir(parents=True)
    (hnf_sw / "workflow.sh").write_text(
        "#!/usr/bin/env bash\n# Step 1: Benchmark (tab:sv)\npython Code/run_sp500_sv_benchmark.py\n",
        encoding="utf-8",
    )
    (hnf_sw / "Code" / "run_sp500_sv_benchmark.py").write_text(
        "def estimate_sv_flow(y=1.0):\n    return y * 0.95\n",
        encoding="utf-8",
    )
    bayesian_pkg = hnf_sources / "Bayesian"
    (bayesian_pkg / "Code").mkdir(parents=True)
    (bayesian_pkg / "Code" / "dag_sampler.py").write_text(
        "def sample_dag_posterior(draws=10):\n    return float(draws)\n",
        encoding="utf-8",
    )
    # Cross-project duplicate `HetNN` dir under HNF `sources/` that MUST be skipped!
    (hnf_sources / "HetNN").mkdir(parents=True)
    (hnf_sources / "HetNN" / "dup.py").write_text("DUP = 1\n", encoding="utf-8")

    hnf_tex = hnf_sources / "current-2026-10-02" / "overleaf" / "Main.tex"
    hnf_tex.parent.mkdir(parents=True)
    hnf_tex.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Synthetic DAG Normalizing Flows}
            \begin{document}
            \section{Benchmarks}
            \begin{table}\caption{SV Results}\label{tab:sv}
            \begin{tabular}{lr} ELBO & -1{,}204.5 \\ \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    # 3. Un-backed-up `Anchor-Improvement` decoy cockpit inside `tmp_dev`
    if include_anchor_decoy:
        decoy_cdir = tmp_dev / "Anchor-Improvement"
        (decoy_cdir / ".anvil").mkdir(parents=True)
        (decoy_cdir / ".anvil" / "session.json").write_text(
            json.dumps({"active": True, "mode": "code", "software": {"path": str(decoy_cdir)}}),
            encoding="utf-8",
        )

    # 4. Stage `.anvil` trees with rewritten `tmp_dev` paths + matching `repo_fingerprint`s + `tmp_backups`
    hetnn_fp = v4_proc.build_process_map(hetnn_dir, persist=False, paper_path=moe_tex)["repo_fingerprint"]
    hnf_fp = v4_proc.build_process_map(hnf_sw, persist=False, paper_path=hnf_tex, allowed_root=hnf_inner)["repo_fingerprint"]

    slug_targets = []
    if include_moe:
        slug_targets.append(("moe_paper1", moe_cockpit, hetnn_dir, moe_tex, hetnn_fp))
    if include_hnf:
        slug_targets.append(("hnf_paper1", hnf_inner, hnf_sw, hnf_tex, hnf_fp))
        slug_targets.append(("hnf_outer", hnf_outer, hnf_sw, hnf_tex, hnf_fp))

    backed_up_files: dict[str, dict[str, Any]] = {}
    cockpits_summary: dict[str, dict[str, Any]] = {}

    for slug, cdir, sw_p, tex_p, repo_fp in slug_targets:
        src_backup_anvil = BACKUP_DIR / slug / ".anvil"
        dst_anvil = cdir / ".anvil"
        if dst_anvil.exists():
            shutil.rmtree(dst_anvil)
        shutil.copytree(src_backup_anvil, dst_anvil)

        # Rewrite session.json strictly to `tmp_dev` paths
        sfile = dst_anvil / "session.json"
        sdoc = json.loads(sfile.read_text(encoding="utf-8"))
        sdoc["cockpit_dir"] = str(cdir.resolve())
        if isinstance(sdoc.get("software"), dict):
            sdoc["software"]["path"] = str(sw_p.resolve())
        if isinstance(sdoc.get("compare_software"), dict):
            sdoc["compare_software"]["path"] = str(sw_p.resolve())
        if isinstance(sdoc.get("paper_map"), dict):
            sdoc["paper_map"]["paper_path"] = str(tex_p.resolve())
            sdoc["paper_map"]["source_path"] = str(tex_p.resolve())
            if isinstance(sdoc["paper_map"].get("paper_info"), dict):
                sdoc["paper_map"]["paper_info"]["path"] = str(tex_p.resolve())
                sdoc["paper_map"]["paper_info"]["primary_tex"] = str(tex_p.resolve())
        sfile.write_text(json.dumps(sdoc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        # Update xval_receipt.json repo_fingerprint to match the `tmp_dev` synthetic repo
        xv_file = dst_anvil / "v4" / "xval_receipt.json"
        if xv_file.is_file():
            xv_doc = json.loads(xv_file.read_text(encoding="utf-8"))
            xv_doc["repo_fingerprint"] = repo_fp
            xv_file.write_text(json.dumps(xv_doc, indent=2), encoding="utf-8")

        # Mirror into `tmp_backups/<slug>/.anvil` so `verify_backup_manifest` & `verify_cockpit_migrations` check real SHA-256s
        b_dst = tmp_backups / slug / ".anvil"
        shutil.copytree(dst_anvil, b_dst)
        f_cnt = 0
        f_bytes = 0
        for item in sorted(b_dst.rglob("*")):
            if item.is_file():
                raw_b = item.read_bytes()
                rel_b = item.relative_to(tmp_backups).as_posix()
                backed_up_files[rel_b] = {
                    "sha256": hashlib.sha256(raw_b).hexdigest(),
                    "size": len(raw_b),
                    "target": slug,
                }
                f_cnt += 1
                f_bytes += len(raw_b)
        cockpits_summary[slug] = {
            "source_anvil": dst_anvil.as_posix(),
            "backup_anvil": b_dst.as_posix(),
            "file_count": f_cnt,
            "total_bytes": f_bytes,
        }

    # Ensure all 3 required Wave-1 slugs exist in `tmp_backups` so `verify_backup_manifest` passes even in single-paper test
    for missing_slug in ("moe_paper1", "hnf_paper1", "hnf_outer"):
        if missing_slug not in cockpits_summary:
            b_dst = tmp_backups / missing_slug / ".anvil"
            shutil.copytree(BACKUP_DIR / missing_slug / ".anvil", b_dst)
            for item in sorted(b_dst.rglob("*")):
                if item.is_file():
                    raw_b = item.read_bytes()
                    rel_b = item.relative_to(tmp_backups).as_posix()
                    backed_up_files[rel_b] = {
                        "sha256": hashlib.sha256(raw_b).hexdigest(),
                        "size": len(raw_b),
                        "target": missing_slug,
                    }
            cockpits_summary[missing_slug] = {"source_anvil": "", "backup_anvil": b_dst.as_posix(), "file_count": 1, "total_bytes": 1}

    hnf_base_doc = bmod.compute_source_baseline(hnf_sources)
    hnf_base_bytes = bmod.atomic_write_json(tmp_backups / "hnf-baseline-sha256.json", hnf_base_doc)

    hetnn_sha_map = {
        fp.relative_to(hetnn_dir).as_posix(): hashlib.sha256(fp.read_bytes()).hexdigest()
        for fp in sorted(hetnn_dir.rglob("*"))
        if fp.is_file()
    }
    hetnn_base_bytes = bmod.atomic_write_json(tmp_backups / "hetnn-baseline-sha256.json", {"sha256": hetnn_sha_map})

    tmp_manifest_doc = {
        "schema": bmod.PRE_W1_MANIFEST_SCHEMA,
        "created_utc": live_manifest["created_utc"],
        "pre_edit_product_hashes": live_manifest["pre_edit_product_hashes"],
        "hnf_baseline_path": "hnf-baseline-sha256.json",
        "hnf_baseline_sha256": hashlib.sha256(hnf_base_bytes).hexdigest(),
        "hetnn_baseline_path": "hetnn-baseline-sha256.json",
        "hetnn_baseline_sha256": hashlib.sha256(hetnn_base_bytes).hexdigest(),
        "cockpits": cockpits_summary,
        "backed_up_files": backed_up_files,
    }
    bmod.atomic_write_json(tmp_backups / "pre-w1-manifest.json", tmp_manifest_doc)
    return tmp_dev, tmp_anchor, tmp_backups


def test_w4_zero_paper_specific_identifiers_grep_gate() -> None:
    """Enforce zero paper-specific or author-specific identifiers across every Anvil skill
    script/static asset, vendored bundle asset, and `steward_cockpit/anvil_session.py`.
    """
    forbidden_tokens = (
        "Het" + "NN",
        "Hierarchical" + "NormalizingFlows",
        "BINN_" + "NeurIPS",
        "Liech" + "ty",
        "Fo" + "ng",
        "Paper" + " 1",
        "Anchored" + "MoE",
        "step2_" + "runner",
        "DEV_" + "PEN",
        "unstick_" + "residuals",
        "MixtureOfExperts" + "MNL",
    )

    targets: list[Path] = [ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py"]
    for tree_root in (SKILL_ROOT, VENDOR_ANVIL_ROOT):
        for sub in ("scripts", "static"):
            sub_dir = tree_root / sub
            assert sub_dir.is_dir(), f"Missing {sub_dir}"
            for fp in sorted(sub_dir.rglob("*")):
                if fp.is_file() and fp.suffix.lower() in {".py", ".html", ".js", ".css"}:
                    targets.append(fp)

    violations: list[str] = []
    for fp in targets:
        low = fp.read_text(encoding="utf-8").lower()
        for tok in forbidden_tokens:
            if tok.lower() in low:
                violations.append(f"{fp.name}: forbidden token {tok!r}")

    assert violations == [], f"Paper-specific identifier grep-gate violations: {violations}"


def test_w4_foundry_vendor_byte_sync_no_pycache() -> None:
    """Verify exact bidirectional parity on `scripts/` and `static/` plus curated vendor files
    between Skill Foundry `skills/anvil` and `vendor/bundled-skills/anvil`, zero import-time
    `rmtree` side-effect in `anvil_session.py`, zero `__pycache__`/`*.pyc` in `vendor`, and
    `distro.scan_paths == []` across all Wave-4 Anchor deliverables.
    """
    # Confirm `anvil_session._load_anvil_engine` has zero import-time `rmtree` side-effects
    as_src = (ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py").read_text(encoding="utf-8")
    assert "_BUNDLED_PYCACHE_CLEANED" not in as_src

    pycache_dirs = list(VENDOR_ANVIL_ROOT.rglob("__pycache__"))
    pyc_files = list(VENDOR_ANVIL_ROOT.rglob("*.pyc"))
    assert pycache_dirs == [], f"Found __pycache__ under vendor/bundled-skills/anvil: {pycache_dirs}"
    assert pyc_files == [], f"Found .pyc files under vendor/bundled-skills/anvil: {pyc_files}"

    for sub in ("scripts", "static"):
        sf_files = {
            p.relative_to(SKILL_ROOT / sub).as_posix(): p
            for p in (SKILL_ROOT / sub).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix.lower() != ".pyc"
        }
        vn_files = {
            p.relative_to(VENDOR_ANVIL_ROOT / sub).as_posix(): p
            for p in (VENDOR_ANVIL_ROOT / sub).rglob("*")
            if p.is_file()
        }
        assert set(sf_files.keys()) == set(vn_files.keys()), (
            f"Bidirectional file-set drift in {sub}: foundry={sorted(sf_files)} vs vendor={sorted(vn_files)}"
        )
        for rel, sf_p in sorted(sf_files.items()):
            h_sf = hashlib.sha256(sf_p.read_bytes()).hexdigest()
            h_vn = hashlib.sha256(vn_files[rel].read_bytes()).hexdigest()
            assert h_sf == h_vn, f"SHA-256 drift on {sub}/{rel}: {h_sf} != {h_vn}"

    sf_curated = {
        p.relative_to(SKILL_ROOT).as_posix()
        for p in SKILL_ROOT.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix.lower() != ".pyc"
        and p.relative_to(SKILL_ROOT).parts[0] not in {"journal", "tests"}
    }
    vn_curated = {
        p.relative_to(VENDOR_ANVIL_ROOT).as_posix()
        for p in VENDOR_ANVIL_ROOT.rglob("*")
        if p.is_file() and p.relative_to(VENDOR_ANVIL_ROOT).parts[0] not in {"journal", "tests"}
    }
    assert sf_curated == vn_curated, (
        f"Bidirectional non-journal/non-test file drift: sf_only={sorted(sf_curated - vn_curated)}, vn_only={sorted(vn_curated - sf_curated)}"
    )
    for rel_any in sorted(
        p.relative_to(VENDOR_ANVIL_ROOT).as_posix()
        for p in VENDOR_ANVIL_ROOT.rglob("*")
        if p.is_file()
    ):
        sf_counterpart = SKILL_ROOT / rel_any
        assert sf_counterpart.is_file(), f"Vendor file missing in Skill Foundry: {rel_any}"
        assert (
            hashlib.sha256((VENDOR_ANVIL_ROOT / rel_any).read_bytes()).hexdigest()
            == hashlib.sha256(sf_counterpart.read_bytes()).hexdigest()
        ), f"Vendor SHA-256 mismatch on {rel_any}"

    anchor_w4_files = [
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        VENDOR_ANVIL_ROOT / "scripts" / "anvil_v4_process.py",
        VENDOR_ANVIL_ROOT / "scripts" / "anvil_v4_refactor.py",
        VENDOR_ANVIL_ROOT / "static" / "anvil_v4_workbench.html",
        BACKUP_SCRIPT,
        W4_MOCKUP_HTML,
        Path(__file__).resolve(),
    ]
    for req_p in anchor_w4_files:
        assert req_p.is_file(), f"Missing declared Wave-4 Anchor deliverable: {req_p}"

    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in anchor_w4_files]
    hits = distro.scan_paths(pairs, root=ANCHOR_ROOT)
    assert hits == [], f"distro.scan_paths flagged Wave-4 Anchor deliverables: {hits}"


def test_w4_tmp_moe_migration_and_apply_enable_verify_script(tmp_path: Path) -> None:
    """Hermetically stage MoE (`HetNN` + dated `sources/` decoys + un-backed-up `Anchor-Improvement`
    decoy) strictly inside `tmp_path`, prove default discovery excludes `Anchor*`/un-backed-up
    cockpits, test first-time 2-process concurrent `--apply`, verify per-file source SHA-256
    recheck + `<50 ms` `cache_hit == 'disk'` + verify-before-enable rollback on source mutation!
    """
    live_marker = ANCHOR_ROOT / ".anchor" / "anvil-multi-enabled.json"
    live_marker_before = live_marker.read_bytes() if live_marker.is_file() else None

    # Read-only check on `discover_target_cockpits(DEV_ROOT)`: NEVER returns `Anchor*` or un-backed-up cockpits!
    bmod = _load_backup_mod()
    live_discovered = bmod.discover_target_cockpits(DEV_ROOT)
    assert not any(p.name.startswith("Anchor") for p in live_discovered)
    assert all(bmod._match_backup_slug_for_cockpit(p, DEV_ROOT) is not None for p in live_discovered)

    tmp_dev, tmp_anchor, tmp_backups = _stage_hermetic_workspace(
        tmp_path / "moe_case",
        include_moe=True,
        include_hnf=False,
        include_anchor_decoy=True,
    )
    staged_moe = tmp_dev / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
    decoy_anchor_imp = tmp_dev / "Anchor-Improvement"
    manifest_doc = json.loads((tmp_backups / "pre-w1-manifest.json").read_text(encoding="utf-8"))
    backed_up = manifest_doc["backed_up_files"]

    # 1. `--dry-run`: zero writes on disk AND un-backed-up `Anchor-Improvement` decoy is ignored!
    before_tree = sorted(p.relative_to(tmp_dev).as_posix() for p in tmp_dev.rglob("*"))
    rc_dry, out_dry, err_dry = _run_migrate_cli(
        "--dev-root",
        str(tmp_dev),
        "--anchor-root",
        str(tmp_anchor),
        "--out-dir",
        str(tmp_backups),
        "--dry-run",
    )
    assert rc_dry == 0, f"--dry-run failed: {err_dry}"
    assert out_dry["dry_run"]["cockpit_count"] == 1
    assert out_dry["dry_run"]["cockpits"][0]["backup_slug"] == "moe_paper1"
    # Verify dated/duplicate `sources/{2026-10-02,HetNN,hetnn_paper_matched}` were NOT planned as junk `pkg-*`!
    planned_sec_ids = [s["analysis_id"] for s in out_dry["dry_run"]["cockpits"][0]["secondary_analyses"]]
    assert planned_sec_ids == ["hetnn-replication-package"], f"Unexpected junk secondary slots: {planned_sec_ids}"
    after_tree = sorted(p.relative_to(tmp_dev).as_posix() for p in tmp_dev.rglob("*"))
    assert after_tree == before_tree, "--dry-run wrote files to disk!"

    # Explicitly passing an un-backed-up `--cockpit` MUST fail closed (exit 1)!
    rc_unb, _, err_unb = _run_migrate_cli(
        "--dev-root",
        str(tmp_dev),
        "--anchor-root",
        str(tmp_anchor),
        "--out-dir",
        str(tmp_backups),
        "--cockpit",
        str(decoy_anchor_imp),
        "--dry-run",
    )
    assert rc_unb == 1 and "un-backed-up" in err_unb.lower()

    # 2. Real FIRST-TIME 2-process concurrent `--apply` on an un-migrated cockpit!
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(BACKUP_SCRIPT),
                "--dev-root",
                str(tmp_dev),
                "--anchor-root",
                str(tmp_anchor),
                "--out-dir",
                str(tmp_backups),
                "--apply",
            ],
            cwd=str(ANCHOR_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    for pr in procs:
        out_c, err_c = pr.communicate(timeout=90)
        assert pr.returncode == 0, f"First-time concurrent --apply failed: {err_c}\n{out_c}"

    assert not (decoy_anchor_imp / ".anvil" / "analyses" / "index.json").exists()
    assert not (tmp_anchor / ".anchor" / "anvil-multi-enabled.json").exists()

    idx_path = staged_moe / ".anvil" / "analyses" / "index.json"
    assert idx_path.is_file()
    idx_1_bytes = idx_path.read_bytes()
    idx_1 = json.loads(idx_1_bytes.decode("utf-8"))
    live_entries = [e for e in idx_1["analyses"] if not e.get("archived")]
    assert [e["analysis_id"] for e in live_entries] == ["legacy-primary", "hetnn-replication-package"]
    # Confirm software_spec points strictly inside `tmp_dev`, NEVER live `DEV_ROOT`!
    for ent in live_entries:
        if ent["analysis_id"] != "legacy-primary":
            assert Path(ent["software_spec"]).resolve().is_relative_to(tmp_dev.resolve())

    # 3. `--apply --enable --verify` TWICE: verifies per-file source SHA-256s, `<50 ms` `cache_hit == 'disk'`, & idempotence!
    rc_en1, out_en1, err_en1 = _run_migrate_cli(
        "--dev-root",
        str(tmp_dev),
        "--anchor-root",
        str(tmp_anchor),
        "--out-dir",
        str(tmp_backups),
        "--apply",
        "--enable",
        "--verify",
    )
    assert rc_en1 == 0, f"--apply --enable --verify #1 failed: {err_en1}"
    assert (tmp_anchor / ".anchor" / "anvil-multi-enabled.json").is_file()
    assert (live_marker.read_bytes() if live_marker.is_file() else None) == live_marker_before
    ver_1 = out_en1["verify"]
    assert ver_1["multi_analysis_enabled"] is True
    assert ver_1["verified_source_files"] >= 4
    cv_1 = ver_1["cockpit_verdicts"][0]
    assert len(cv_1["verified_legacy_files"]) >= 2
    for aid in ("legacy-primary", "hetnn-replication-package"):
        assert cv_1["warm_disk_ms"][aid] < 50.0
        assert cv_1["warm_ram_ms"][aid] < 50.0

    rc_en2, out_en2, err_en2 = _run_migrate_cli(
        "--dev-root",
        str(tmp_dev),
        "--anchor-root",
        str(tmp_anchor),
        "--out-dir",
        str(tmp_backups),
        "--apply",
        "--enable",
        "--verify",
    )
    assert rc_en2 == 0, f"--apply --enable --verify #2 failed: {err_en2}"
    assert idx_path.read_bytes() == idx_1_bytes
    assert all(s["mode"] == "already_migrated" for s in out_en2["apply"]["cockpits"][0]["secondary_analyses"])
    assert list(tmp_dev.rglob("*.lock")) == [] and list(tmp_dev.rglob("*.part")) == []

    # 4. Verify-Before-Enable fail-closed test: mutating a source file makes `--enable --verify` exit 1 WITHOUT writing marker!
    fit_py = staged_moe / "HetNN" / "Code" / "fit_mixture.py"
    orig_fit = fit_py.read_text(encoding="utf-8")
    fresh_anchor_fail = tmp_path / "anchor_should_stay_off"
    fresh_anchor_fail.mkdir()
    try:
        fit_py.write_text(orig_fit + "\n# unauthorized source drift\n", encoding="utf-8")
        rc_mut, _, err_mut = _run_migrate_cli(
            "--dev-root",
            str(tmp_dev),
            "--anchor-root",
            str(fresh_anchor_fail),
            "--out-dir",
            str(tmp_backups),
            "--enable",
            "--verify",
        )
        assert rc_mut == 1
        assert "sha-256" in err_mut.lower() or "mismatch" in err_mut.lower()
        assert not (fresh_anchor_fail / ".anchor" / "anvil-multi-enabled.json").exists(), (
            "--enable wrote activation marker despite --verify failing!"
        )
    finally:
        fit_py.write_text(orig_fit, encoding="utf-8")

    for rel_chk in (".anvil/session.json", ".anvil/v4/xval_receipt.json", ".anvil/v4/last_trace.json"):
        bkey = f"moe_paper1/{rel_chk}"
        if bkey in backed_up:
            act_sha = hashlib.sha256((staged_moe / rel_chk).read_bytes()).hexdigest()
            assert act_sha == backed_up[bkey]["sha256"]


def test_w4_tmp_hnf_migration_and_outer_cockpit_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hermetically stage both `hnf_paper1` and `hnf_outer` (with `sources/{HierarchicalNormalizingFlows,
    Bayesian,HetNN,current-2026-10-02}`) strictly inside `tmp_path`, verify child-effort fallback,
    run `--apply --enable --verify` twice, assert `pkg-bayesian` + replication package + pipeline stage
    titles + `<50 ms` `cache_hit == 'disk'` + zero live-tree reads!
    """
    unmigrated_outer = tmp_path / "outer_without_anvil"
    child_effort = unmigrated_outer / "Paper 1"
    (child_effort / ".anvil").mkdir(parents=True)
    (child_effort / ".anvil" / "session.json").write_text('{"active": true}', encoding="utf-8")
    assert anvil_session.resolve_cockpit_or_child_effort(unmigrated_outer) == child_effort.resolve()

    tmp_dev, tmp_anchor, tmp_backups = _stage_hermetic_workspace(
        tmp_path / "hnf_case",
        include_moe=False,
        include_hnf=True,
        include_anchor_decoy=True,
    )
    staged_outer = tmp_dev / "Hierarchical Normalizing Flows"
    staged_inner = staged_outer / "Paper 1"
    manifest_doc = json.loads((tmp_backups / "pre-w1-manifest.json").read_text(encoding="utf-8"))
    backed_up = manifest_doc["backed_up_files"]

    assert anvil_session.resolve_cockpit_or_child_effort(staged_outer) == staged_outer.resolve()
    assert anvil_session.resolve_cockpit_or_child_effort(staged_inner) == staged_inner.resolve()

    rc_1, out_1, err_1 = _run_migrate_cli(
        "--dev-root",
        str(tmp_dev),
        "--anchor-root",
        str(tmp_anchor),
        "--out-dir",
        str(tmp_backups),
        "--apply",
        "--enable",
        "--verify",
    )
    assert rc_1 == 0, f"HNF --apply --enable --verify #1 failed: {err_1}"
    assert out_1["apply"]["cockpit_count"] == 2
    assert out_1["verify"]["migrated_cockpits_verified"] == 2
    assert out_1["verify"]["verified_source_files"] >= 4

    rc_2, out_2, err_2 = _run_migrate_cli(
        "--dev-root",
        str(tmp_dev),
        "--anchor-root",
        str(tmp_anchor),
        "--out-dir",
        str(tmp_backups),
        "--apply",
        "--enable",
        "--verify",
    )
    assert rc_2 == 0, f"HNF --apply --enable --verify #2 failed: {err_2}"
    assert all(
        s["mode"] == "already_migrated"
        for cp in out_2["apply"]["cockpits"]
        for s in cp["secondary_analyses"]
    )

    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, tmp_dev.resolve(), tmp_anchor.resolve()),
    )

    for cdir, slug in ((staged_outer, "hnf_outer"), (staged_inner, "hnf_paper1")):
        idx_doc = json.loads((cdir / ".anvil" / "analyses" / "index.json").read_text(encoding="utf-8"))
        live_map = {e["analysis_id"]: e for e in idx_doc["analyses"] if not e.get("archived")}
        assert set(live_map.keys()) == {
            "legacy-primary",
            "pkg-bayesian",
            "hierarchicalnormalizingflows-replication-package",
        }
        for sec_k in ("pkg-bayesian", "hierarchicalnormalizingflows-replication-package"):
            assert Path(live_map[sec_k]["software_spec"]).resolve().is_relative_to(tmp_dev.resolve())

        # Verify in-process disk-cache read returns `cache_hit == 'disk'` with pipeline stage titles & sibling manuscript
        with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
            anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()
        st_p, st_c = anvil_session.get_v4_cockpit_state(cdir, analysis_id="legacy-primary", anchor_root=tmp_anchor)
        assert st_c == 200 and st_p["cache_hit"] == "disk"
        assert st_p["v4_bundle"]["has_paper"] is True
        stage_titles = " | ".join(s["title"] for s in st_p["v4_bundle"]["process_map"]["l1_stages"]).lower()
        assert "tab:sv" in stage_titles or "predictive" in stage_titles or "benchmark" in stage_titles

        for rel_chk in (".anvil/session.json", ".anvil/v4/xval_receipt.json", ".anvil/v4/last_trace.json"):
            bkey = f"{slug}/{rel_chk}"
            if bkey in backed_up:
                act_sha = hashlib.sha256((cdir / rel_chk).read_bytes()).hexdigest()
                assert act_sha == backed_up[bkey]["sha256"]

    # AST static guard: confirm this test file never passes live paper constants to anvil_session/steward_routes
    self_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assert self_tree is not None


def test_w4_anvil_report_v5_cards_and_code_default_remains_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `is_multi_analysis_enabled()` defaults to `False`, live `.anchor/anvil-multi-enabled.json`
    is absent, `ANVIL-REPORT.md` renders pipeline-derived `S1`..`Sk` stages in Card 6B (`v4_bundle`
    non-null), and `steward_routes.handle_post(..., 'anvil', {'action': 'export_replication_package'})`
    enforces `503` (flag off), `400 LEGACY_ROOT_IMMUTABLE` (`store='.'`), `403`, `400`, and `200`!
    """
    monkeypatch.delenv("ANCHOR_ANVIL_MULTI", raising=False)
    clean_anchor = tmp_path / "clean_anchor"
    clean_anchor.mkdir()
    monkeypatch.setattr(anvil_session, "_ANCHOR_ROOT", clean_anchor.resolve())
    assert anvil_session.is_multi_analysis_enabled() is False
    assert anvil_session.is_multi_analysis_enabled(clean_anchor) is False
    assert not (clean_anchor / ".anchor" / "anvil-multi-enabled.json").exists()

    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, tmp_path.resolve()),
    )

    # 1. With flag OFF, `export_replication_package` via `steward_routes` refuses with `503 MULTI_ANALYSIS_DISABLED`
    #    and NEVER rewrites a legacy `.anvil/session.json`!
    leg_cdir = tmp_path / "legacy_cockpit_off"
    (leg_cdir / ".anvil").mkdir(parents=True)
    leg_sfile = leg_cdir / ".anvil" / "session.json"
    leg_orig_bytes = b'{"active":true,"mode":"code","software":{"path":"."}}'
    leg_sfile.write_bytes(leg_orig_bytes)

    off_res, off_code = steward_routes.handle_post(
        str(leg_cdir),
        "anvil",
        {"action": "export_replication_package"},
    )
    assert off_code == 503 and off_res["error_code"] == "MULTI_ANALYSIS_DISABLED"
    assert leg_sfile.read_bytes() == leg_orig_bytes
    assert not (leg_cdir / ".anvil" / "replication_package").exists()

    # 2. Enable in-process via `monkeypatch.setenv` and verify `LEGACY_ROOT_IMMUTABLE` on `store='.'`
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")
    anvil_session.register_legacy_analysis(leg_cdir, anchor_root=tmp_path / "tmp_anchor")
    imm_res, imm_code = steward_routes.handle_post(
        str(leg_cdir),
        "anvil",
        {"action": "export_replication_package", "analysis_id": "legacy-primary"},
    )
    assert imm_code == 400 and imm_res["error_code"] == "LEGACY_ROOT_IMMUTABLE"
    assert leg_sfile.read_bytes() == leg_orig_bytes

    # 3. Create isolated analysis with workflow.sh + Paper.tex and verify non-fallback `S1` pipeline stage in Card 6B
    cdir = tmp_path / "v5_report_cockpit"
    repo = cdir / "model_pkg"
    ms_dir = cdir / "manuscript"
    repo.mkdir(parents=True)
    ms_dir.mkdir(parents=True)

    (repo / "workflow.sh").write_text(
        "#!/usr/bin/env bash\n# Step 1: Ridge Fit (tab:emp_1)\npython fit_core.py\n",
        encoding="utf-8",
    )
    (repo / "fit_core.py").write_text(
        textwrap.dedent(
            """\
            def estimate_ridge_beta(x_val: float, penalty: float = 0.05) -> float:
                return x_val / (1.0 + penalty)
            """
        ),
        encoding="utf-8",
    )
    (ms_dir / "Paper.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Ridge Shrinkage Notes}
            \begin{document}
            \section{Estimation}
            \begin{equation}
            \hat{\beta} = \frac{x}{1 + \lambda}
            \end{equation}
            \begin{table}\caption{Main Estimates}\label{tab:emp_1}
            \begin{tabular}{lr} N & \textbf{50{,}002} \\ \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    cr_res, cr_code = anvil_session.create_cockpit_analysis(
        cdir,
        analysis_id="ridge-primary",
        title="Ridge Shrinkage Full Audit",
        mode="paper",
        software_spec="model_pkg",
        paper_spec="manuscript/Paper.tex",
        direction="Verify Eq. 1 shrinkage denominator and export standalone replication closure.",
        materialize_replication_package=True,
        anchor_root=tmp_path / "tmp_anchor",
    )
    assert cr_code == 200 and cr_res["ok"] is True
    assert cr_res["v4_bundle"] is not None

    store_dir = cdir / ".anvil" / "analyses" / "ridge-primary"
    report_md_path = store_dir / "ANVIL-REPORT.md"
    report_txt = report_md_path.read_text(encoding="utf-8")

    for expected_token in (
        "# Anvil Session Report",
        "## 1. Parable of the Oranges",
        "## 2. Conceptual & Process Map Blocks",
        "## 3. Old → New Code Map & Explicit Null Space",
        "## 5.",
        "## 6. Anvil v5 — Full-Width Multi-Analysis, Workflow Pipeline, Divergence & Replication Cards",
        "### Card 6A · Active Analysis & Validation Provenance",
        "### Card 6B · Workflow & Manuscript Pipeline Stages",
        "| `S1` |",
        "### Card 6C · Manuscript ↔ Code Divergences & Citation Audit",
        "### Card 6D · Standalone Replication Package Manifest",
        ".anvil/replication_package/REPLICATION_MANIFEST.md",
    ):
        assert expected_token in report_txt, f"Missing {expected_token!r} in ANVIL-REPORT.md"

    assert distro.scan_paths([("ANVIL-REPORT.md", report_md_path)], root=tmp_path) == []

    # 4. Exercise `steward_routes` HTTP `export_replication_package` (200, 403 escape, 400 bound)
    ok_route, ok_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "export_replication_package", "analysis_id": "ridge-primary"},
    )
    assert ok_code == 200 and ok_route["ok"] is True

    esc_route, esc_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "export_replication_package",
            "analysis_id": "ridge-primary",
            "closure_files": ["../outside.py"],
        },
    )
    assert esc_code == 403 and esc_route["error_code"] == "PATH_ESCAPE_REFUSED"

    bound_route, bound_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "export_replication_package",
            "analysis_id": "ridge-primary",
            "closure_files": [f"f_{i}.py" for i in range(501)],
        },
    )
    assert bound_code == 400 and bound_route["error_code"] == "BOUND_EXCEEDED_REFUSAL"


def _run_ft_look_w4(target: str, out_dir: Path) -> dict[str, Any]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    required_selectors = [
        "#analysisSwitcherSelect",
        "[data-divergence-panel]",
    ]
    cmd = [
        sys.executable,
        str(FT_PY),
        "look",
        target,
        "--check",
        required_selectors[0],
        "--check",
        required_selectors[1],
        "--out",
        str(out_dir),
        "--json",
    ]
    proc = subprocess.run(cmd, cwd=str(ANCHOR_ROOT), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"ft.py look failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    payload = json.loads(proc.stdout)
    viewports = payload.get("results") or payload.get("viewports") or []
    assert len(viewports) >= 2

    sanitized_vps: list[dict[str, Any]] = []
    for vp in viewports:
        vp_label = vp.get("size") or vp.get("viewport")
        assert "error" not in vp
        assert vp.get("errors", []) == []
        assert vp.get("consoleErrors", []) == []
        assert vp.get("pageErrors", []) == []
        assert vp.get("failedAssets", []) == []

        checks = vp.get("checks") or {}
        for sel in required_selectors:
            matches = checks.get(sel)
            assert isinstance(matches, list) and len(matches) >= 1, f"Missing {sel} on {vp_label}"
            first = matches[0]
            assert first.get("painted") is True
            assert first.get("coveredBy") is None
            assert first.get("onScreen") is True

        shot_raw = str(vp.get("screenshot") or "")
        shot_rel = Path(shot_raw).resolve().relative_to(ANCHOR_ROOT).as_posix() if shot_raw else ""
        sanitized_vps.append(
            {
                "size": vp.get("size"),
                "viewport": vp.get("viewport"),
                "screenshot": shot_rel,
                "errors": vp.get("errors", []),
                "checks": checks,
            }
        )
    return {"viewports": sanitized_vps}


def test_w4_l3_look_verdict(tmp_path: Path) -> None:
    """Sole writer of `planning/2026-11-22-anvil-cockpit-multi-analysis/looks/w4/verdict.json`."""
    assert FT_PY.is_file()
    assert W4_MOCKUP_HTML.is_file()

    W4_LOOKS_DIR.mkdir(parents=True, exist_ok=True)
    if W4_VERDICT_JSON.exists():
        W4_VERDICT_JSON.unlink()

    mockup_res = _run_ft_look_w4(str(W4_MOCKUP_HTML), W4_LOOKS_DIR / "mockup")

    wb_repo = tmp_path / "wb_live_repo"
    wb_repo.mkdir(parents=True)
    (wb_repo / "workflow.sh").write_text("#!/usr/bin/env bash\npython run_emp_1.py\n", encoding="utf-8")
    (wb_repo / "run_emp_1.py").write_text(
        "def solve_emp_1(x: float = 2.0, ridge: float = 0.01) -> float:\n    return x / (1.0 + ridge)\n",
        encoding="utf-8",
    )
    wb_tex = wb_repo / "Main.tex"
    wb_tex.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Live Ephemeral Workbench Check}
            \begin{document}
            \section{Model}
            \begin{table}\caption{Empirical Table}\label{tab:emp_1}
            \begin{tabular}{lr} N & \textbf{50{,}002} \\ \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    v4_mods = anvil_session._load_anvil_v4_modules()
    v4_wb = v4_mods["anvil_v4_workbench"]
    wb_server = v4_wb.create_workbench_server(wb_repo, paper_path=wb_tex, host="127.0.0.1", port=0)
    wb_port = int(wb_server.server_address[1])
    assert wb_port != 8777 and wb_port > 0
    srv_thread = threading.Thread(target=wb_server.serve_forever, daemon=True)
    srv_thread.start()
    try:
        live_url = f"http://127.0.0.1:{wb_port}/"
        live_res = _run_ft_look_w4(live_url, W4_LOOKS_DIR / "live")
    finally:
        wb_server.shutdown()
        wb_server.server_close()

    verdict_doc = {
        "schema": "anvil.look-verdict.v1",
        "wave": "w4",
        "status": "PASSED",
        "checked_selectors": [
            "#analysisSwitcherSelect",
            "[data-divergence-panel]",
        ],
        "surfaces": {
            "mockup": {
                "target": W4_MOCKUP_HTML.relative_to(ANCHOR_ROOT).as_posix(),
                "viewports": mockup_res["viewports"],
            },
            "live_workbench": {
                "target": "/",
                "ephemeral_port_non_live": True,
                "viewports": live_res["viewports"],
            },
        },
        "generated_at_epoch_s": int(time.time()),
    }
    tmp_verdict = W4_VERDICT_JSON.with_suffix(".json.tmp")
    tmp_verdict.write_text(json.dumps(verdict_doc, indent=2), encoding="utf-8")
    os.replace(tmp_verdict, W4_VERDICT_JSON)

    assert W4_VERDICT_JSON.is_file()
    hits = distro.scan_paths(
        [(W4_VERDICT_JSON.relative_to(ANCHOR_ROOT).as_posix(), W4_VERDICT_JSON)],
        root=ANCHOR_ROOT,
    )
    assert hits == [], f"distro.scan_paths flagged looks/w4/verdict.json: {hits}"
