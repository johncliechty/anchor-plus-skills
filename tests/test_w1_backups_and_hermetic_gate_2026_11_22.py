"""Wave 1 Verification Suite — Pre-Edit Live Cockpit SHA-256 Backups,
Hermetic test_wave5 Retarget & Non-Skippable Gate Runner CLI Pilot.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

import distro
from steward_cockpit import anvil_session

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
DEV_ROOT = ANCHOR_ROOT.parent
PLAN_DIR = ANCHOR_ROOT / "planning" / "2026-11-22-anvil-cockpit-multi-analysis"
SCRIPTS_DIR = PLAN_DIR / "scripts"
BACKUP_SCRIPT = SCRIPTS_DIR / "backup_and_migrate_cockpits.py"
GATE_RUNNER_MJS = SCRIPTS_DIR / "run-all-tests.mjs"
BACKUP_DIR = PLAN_DIR / "backups" / "legacy-anvil-20261122"
PRE_W1_MANIFEST = BACKUP_DIR / "pre-w1-manifest.json"
IMMUTABLE_PRE_W1_MANIFEST_SHA256 = "".join(
    (
        "2971b136dd904db3",
        "cdc9a36c2d588b23",
        "03799ed109ef7804",
        "7fd0efe444a08985",
    )
)
HNF_BASELINE_JSON = BACKUP_DIR / "hnf-baseline-sha256.json"
HETNN_BASELINE_JSON = ANCHOR_ROOT / ".foreman" / "hetnn-baseline-sha256.json"
W1_MOCKUP_HTML = PLAN_DIR / "mockups" / "w1-anvil-v5-preview.html"
W1_LOOK_DIR = PLAN_DIR / "looks" / "w1"
W1_LOOK_VERDICT = W1_LOOK_DIR / "verdict.json"

PAPER1_ROOT = DEV_ROOT / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
HETNN_ROOT = PAPER1_ROOT / "HetNN"
HNF_OUTER_ROOT = DEV_ROOT / "Hierarchical Normalizing Flows"
HNF_PAPER1_ROOT = HNF_OUTER_ROOT / "Paper 1"
HNF_SOURCES_ROOT = HNF_PAPER1_ROOT / "sources"


def _load_backup_module() -> Any:
    spec = importlib.util.spec_from_file_location("backup_and_migrate_cockpits", BACKUP_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_w1_pre_edit_backups_and_product_hash_ordering() -> None:
    """Verify pre-w1-manifest.json exists, records a valid ISO UTC timestamp and 64-hex
    pre_edit_product_hashes for all 3 product files (without asserting live product files
    stay unedited in Waves 2-4), and every backed-up .anvil file matches its SHA-256.
    """
    mod = _load_backup_module()
    assert PRE_W1_MANIFEST.is_file(), f"Missing pre-w1-manifest.json: {PRE_W1_MANIFEST}"
    manifest_raw = PRE_W1_MANIFEST.read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == IMMUTABLE_PRE_W1_MANIFEST_SHA256

    doc = json.loads(manifest_raw.decode("utf-8"))
    assert doc["schema"] == mod.PRE_W1_MANIFEST_SCHEMA

    created_utc = doc["created_utc"]
    assert isinstance(created_utc, str) and created_utc.endswith("Z")
    parsed_ts = dt.datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
    assert parsed_ts.tzinfo is not None
    assert parsed_ts <= dt.datetime.now(dt.timezone.utc)

    prod_hashes = doc["pre_edit_product_hashes"]
    expected_products = {
        "steward_cockpit/anvil_session.py",
        "steward_cockpit/steward_routes.py",
        "anchor_gui.py",
    }
    assert set(prod_hashes.keys()) == expected_products
    manifest_epoch_ns = int(parsed_ts.timestamp() * 1_000_000_000)
    for rel_path, info in prod_hashes.items():
        sha = info["sha256"]
        assert isinstance(sha, str) and len(sha) == 64, f"Bad SHA-256 on {rel_path}: {sha!r}"
        assert all(ch in "0123456789abcdef" for ch in sha)
        assert isinstance(info["size"], int) and info["size"] > 1_000
        assert isinstance(info["mtime_ns"], int) and 0 < info["mtime_ns"] <= manifest_epoch_ns
        live_pf = ANCHOR_ROOT / rel_path
        live_sha = hashlib.sha256(live_pf.read_bytes()).hexdigest()
        if live_sha != sha:
            # Post-Wave-1 product edit occurred strictly AFTER pre-w1-manifest.json was created
            assert live_pf.stat().st_mtime_ns >= info["mtime_ns"]

    backed_up_files: dict[str, dict[str, Any]] = doc["backed_up_files"]
    assert len(backed_up_files) >= 18
    required_backed_up = (
        "moe_paper1/.anvil/session.json",
        "moe_paper1/.anvil/v4/workbench_session.json",
        "moe_paper1/.anvil/v4/xval_receipt.json",
        "hnf_paper1/.anvil/session.json",
        "hnf_paper1/.anvil/v4/xval_receipt.json",
        "hnf_outer/.anvil/session.json",
        "hnf_outer/.anvil/v4/xval_receipt.json",
    )
    for req_rel in required_backed_up:
        assert req_rel in backed_up_files, f"Missing required backed-up file: {req_rel}"

    for rel_str, meta in backed_up_files.items():
        fp = BACKUP_DIR / rel_str
        assert fp.is_file(), f"Backed-up file missing on disk: {fp}"
        raw = fp.read_bytes()
        assert len(raw) == meta["size"], f"Byte size mismatch on {rel_str}"
        assert hashlib.sha256(raw).hexdigest() == meta["sha256"], f"SHA-256 mismatch on {rel_str}"

    res = mod.verify_backup_manifest(
        out_dir=BACKUP_DIR,
        manifest_path=PRE_W1_MANIFEST,
        anchor_root=ANCHOR_ROOT,
    )
    assert res["ok"] is True and res["verified_files"] == len(backed_up_files)


def test_w1_hnf_and_hetnn_source_sha256_baselines() -> None:
    """Verify both hnf-baseline-sha256.json and .foreman/hetnn-baseline-sha256.json exist,
    cover >0 source files, match pre-w1-manifest.json digests, and match live source SHA-256s.
    """
    assert HNF_BASELINE_JSON.is_file(), f"Missing HNF baseline: {HNF_BASELINE_JSON}"
    assert HETNN_BASELINE_JSON.is_file(), f"Missing HetNN baseline: {HETNN_BASELINE_JSON}"

    manifest = json.loads(PRE_W1_MANIFEST.read_text(encoding="utf-8"))
    assert hashlib.sha256(HNF_BASELINE_JSON.read_bytes()).hexdigest() == manifest["hnf_baseline_sha256"]
    assert hashlib.sha256(HETNN_BASELINE_JSON.read_bytes()).hexdigest() == manifest["hetnn_baseline_sha256"]

    # 1. HNF sources baseline verification
    hnf_doc = json.loads(HNF_BASELINE_JSON.read_text(encoding="utf-8"))
    hnf_files: dict[str, dict[str, Any]] = hnf_doc["files"]
    assert len(hnf_files) >= 300
    assert hnf_doc["file_count"] == len(hnf_files)

    actual_hnf: dict[str, tuple[str, int]] = {}
    for fp in sorted(HNF_SOURCES_ROOT.rglob("*")):
        if not fp.is_file():
            continue
        if ".git" in fp.parts or "__pycache__" in fp.parts or fp.suffix.lower() in {".pyc", ".pyo"}:
            continue
        st = fp.stat()
        if st.st_size > 50 * 1024 * 1024:
            continue
        rel = fp.relative_to(HNF_SOURCES_ROOT).as_posix()
        raw = fp.read_bytes()
        actual_hnf[rel] = (hashlib.sha256(raw).hexdigest(), len(raw))

    assert set(actual_hnf.keys()) == set(hnf_files.keys())
    hnf_mismatches = [
        rel
        for rel, (sha, sz) in actual_hnf.items()
        if hnf_files[rel]["sha256"] != sha or hnf_files[rel]["size"] != sz
    ]
    assert hnf_mismatches == [], f"HNF source baseline mismatches: {hnf_mismatches}"

    # 2. HetNN sources baseline verification
    hetnn_doc = json.loads(HETNN_BASELINE_JSON.read_text(encoding="utf-8"))
    hetnn_sha_map: dict[str, str] = hetnn_doc["sha256"]
    assert len(hetnn_sha_map) == 267

    actual_hetnn: dict[str, str] = {}
    for fp in sorted(HETNN_ROOT.rglob("*")):
        if not fp.is_file():
            continue
        if ".git" in fp.parts or "__pycache__" in fp.parts or fp.suffix.lower() == ".pyc":
            continue
        rel = fp.relative_to(HETNN_ROOT).as_posix()
        actual_hetnn[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()

    assert set(actual_hetnn.keys()) == set(hetnn_sha_map.keys())
    hetnn_mismatches = [rel for rel, exp in hetnn_sha_map.items() if actual_hetnn.get(rel) != exp]
    assert hetnn_mismatches == [], f"HetNN source baseline mismatches: {hetnn_mismatches}"


def test_w1_wave5_uses_tmp_path_never_live_cockpit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove test_wave5_anvil_xval_paper1_2026_11_20.py never passes live PAPER1_ROOT or
    HNF cockpit paths to anvil_session (both via AST inspection and runtime call wrapping).
    """
    w5_path = ANCHOR_ROOT / "tests" / "test_wave5_anvil_xval_paper1_2026_11_20.py"
    tree = ast.parse(w5_path.read_text(encoding="utf-8"), filename=str(w5_path))

    forbidden_arg_names = {"PAPER1_ROOT", "HETNN_ROOT", "HNF_PAPER1_ROOT", "HNF_OUTER_ROOT", "MOE_BACKUP_ANVIL"}
    ast_violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            is_anvil_call = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"anvil_session", "steward_routes"}
            )
            if is_anvil_call:
                call_exprs = [*node.args, *(kw.value for kw in node.keywords if kw.value is not None)]
                for expr in call_exprs:
                    for sub in ast.walk(expr):
                        if isinstance(sub, ast.Name) and sub.id in forbidden_arg_names:
                            ast_violations.append(f"L{node.lineno}: {sub.id}")
    assert ast_violations == [], f"Forbidden live cockpit argument in test_wave5: {ast_violations}"

    spec = importlib.util.spec_from_file_location("w5_retargeted_check", w5_path)
    assert spec is not None and spec.loader is not None
    w5_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w5_mod)

    live_forbidden_roots = (
        PAPER1_ROOT.resolve(),
        HNF_PAPER1_ROOT.resolve(),
        HNF_OUTER_ROOT.resolve(),
        BACKUP_DIR.resolve(),
    )
    observed_cockpit_dirs: list[Path] = []
    orig_get_v4 = anvil_session.get_v4_cockpit_state

    def _guarded_get_v4(cockpit_dir: str | Path, *args: Any, **kwargs: Any):
        resolved = Path(cockpit_dir).resolve()
        for bad_root in live_forbidden_roots:
            if resolved == bad_root or resolved.is_relative_to(bad_root):
                raise AssertionError(f"Forbidden live/backup cockpit passed to get_v4_cockpit_state: {resolved}")
        observed_cockpit_dirs.append(resolved)
        return orig_get_v4(cockpit_dir, *args, **kwargs)

    monkeypatch.setattr(anvil_session, "get_v4_cockpit_state", _guarded_get_v4)

    live_sfile = PAPER1_ROOT / ".anvil" / "session.json"
    live_session_mtime_before = live_sfile.stat().st_mtime_ns if live_sfile.is_file() else None
    isolated_tmp = tmp_path / "w5_hermetic_run"
    isolated_tmp.mkdir(parents=True, exist_ok=True)
    w5_mod._allow_tmp_workspace(monkeypatch, isolated_tmp)
    staged_cockpit = w5_mod._stage_moe_backup_cockpit(isolated_tmp)
    payload_h, status_h = anvil_session.get_v4_cockpit_state(staged_cockpit)
    assert status_h == 200 and payload_h["ok"] is True

    assert len(observed_cockpit_dirs) >= 1
    assert all(p.is_relative_to(isolated_tmp.resolve()) for p in observed_cockpit_dirs)
    assert (live_sfile.stat().st_mtime_ns if live_sfile.is_file() else None) == live_session_mtime_before


def test_w1_runner_rejects_skipped_or_xfailed_required_tests(tmp_path: Path) -> None:
    """Execute run-all-tests.mjs against synthetic skipped, xfailed, and missing required
    test files via ANVIL_GATE_SUITE_OVERRIDE and verify non-zero exit + explicit refusal codes.
    """
    runner_src = GATE_RUNNER_MJS.read_text(encoding="utf-8")
    assert "import.meta.dirname" in runner_src
    win_u = "c:" + "\\users\\"
    pos_u = "c:/" + "users/"
    assert win_u not in runner_src.lower() and pos_u not in runner_src.lower()

    skip_suite = tmp_path / "test_synth_skip_2026_11_22.py"
    skip_suite.write_text(
        textwrap.dedent(
            """\
            import pytest

            def test_ok():
                assert True

            @pytest.mark.skip(reason="synthetic skip must fail gate")
            def test_skipped_case():
                assert True
            """
        ),
        encoding="utf-8",
    )

    xfail_suite = tmp_path / "test_synth_xfail_2026_11_22.py"
    xfail_suite.write_text(
        textwrap.dedent(
            """\
            import pytest

            def test_ok():
                assert True

            @pytest.mark.xfail(reason="synthetic xfail must fail gate")
            def test_xfailed_case():
                assert False
            """
        ),
        encoding="utf-8",
    )

    pass_suite = tmp_path / "test_synth_pass_2026_11_22.py"
    pass_suite.write_text(
        textwrap.dedent(
            """\
            def test_alpha():
                assert 2 + 2 == 4
            """
        ),
        encoding="utf-8",
    )

    base_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    # 1. Skipped test MUST exit non-zero with REQUIRED_TEST_SKIP_REFUSED (CLI-only --suite-override)
    r_skip = subprocess.run(
        ["node", str(GATE_RUNNER_MJS), "--suite-override", str(skip_suite)],
        cwd=str(ANCHOR_ROOT),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r_skip.returncode != 0
    assert "REQUIRED_TEST_SKIP_REFUSED" in (r_skip.stdout + "\n" + r_skip.stderr)

    # 2. Xfailed test MUST exit non-zero with REQUIRED_TEST_SKIP_REFUSED
    r_xfail = subprocess.run(
        ["node", str(GATE_RUNNER_MJS), "--suite-override", str(xfail_suite)],
        cwd=str(ANCHOR_ROOT),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r_xfail.returncode != 0
    assert "REQUIRED_TEST_SKIP_REFUSED" in (r_xfail.stdout + "\n" + r_xfail.stderr)

    # 2b. Verify ambient ANVIL_GATE_SUITE_OVERRIDE env var is NEVER honored as a gate bypass
    assert "process.env.ANVIL_GATE_SUITE_OVERRIDE" not in runner_src
    assert "envObj.ANVIL_GATE_SUITE_OVERRIDE" not in runner_src

    # 3. Missing named required test MUST exit non-zero with REQUIRED_TEST_MISSING_REFUSED
    r_missing = subprocess.run(
        ["node", str(GATE_RUNNER_MJS), "--suite-override", str(pass_suite), "--required-tests", "test_alpha,test_missing_one"],
        cwd=str(ANCHOR_ROOT),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r_missing.returncode != 0
    assert "REQUIRED_TEST_MISSING_REFUSED" in (r_missing.stdout + "\n" + r_missing.stderr)

    # 4. Passing suite with all required tests PASSED exits 0
    r_ok = subprocess.run(
        ["node", str(GATE_RUNNER_MJS), "--suite-override", str(pass_suite), "--required-tests", "test_alpha"],
        cwd=str(ANCHOR_ROOT),
        env=base_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r_ok.returncode == 0, f"Expected clean pass, got: {r_ok.stdout}\n{r_ok.stderr}"


def test_w1_backup_cli_idempotence(tmp_path: Path) -> None:
    """Run backup_and_migrate_cockpits.py --backup twice and prove pre-w1-manifest.json
    bytes, mtime_ns, and created_utc remain 100% unchanged (first-write-wins idempotence),
    while tampered backup files fail closed without overwriting the manifest.
    """
    before_bytes = PRE_W1_MANIFEST.read_bytes()
    before_mtime_ns = PRE_W1_MANIFEST.stat().st_mtime_ns
    before_doc = json.loads(before_bytes.decode("utf-8"))

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-B", str(BACKUP_SCRIPT), "--backup"],
            cwd=str(ANCHOR_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"--backup failed: {proc.stderr}"
        out_json = json.loads(proc.stdout)
        assert out_json["ok"] is True
        assert out_json["backup"]["mode"] == "verified_existing"

    after_bytes = PRE_W1_MANIFEST.read_bytes()
    after_mtime_ns = PRE_W1_MANIFEST.stat().st_mtime_ns
    after_doc = json.loads(after_bytes.decode("utf-8"))

    assert after_bytes == before_bytes
    assert after_mtime_ns == before_mtime_ns
    assert after_doc["created_utc"] == before_doc["created_utc"]

    # Also verify tamper fail-closed behavior on an isolated tmp_path copy
    tamper_dir = tmp_path / "tamper_check"
    shutil.copytree(BACKUP_DIR, tamper_dir)
    tamper_manifest = tamper_dir / "pre-w1-manifest.json"
    tamper_manifest_bytes = tamper_manifest.read_bytes()
    (tamper_dir / "moe_paper1" / ".anvil" / "manifest.json").write_text('{"corrupted": true}\n', encoding="utf-8")

    bad_proc = subprocess.run(
        [sys.executable, "-B", str(BACKUP_SCRIPT), "--backup", "--out-dir", str(tamper_dir)],
        cwd=str(ANCHOR_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert bad_proc.returncode != 0
    assert tamper_manifest.read_bytes() == tamper_manifest_bytes


def test_w1_backup_cli_two_process_concurrency(tmp_path: Path) -> None:
    """Spawn two concurrent backup_and_migrate_cockpits.py --backup processes targeting
    the same --out-dir and verify both exit 0 with an uncorrupted manifest under lock + atomic write.
    """
    conc_out = tmp_path / "concurrent_backup"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-B", str(BACKUP_SCRIPT), "--backup", "--out-dir", str(conc_out)]

    p1 = subprocess.Popen(cmd, cwd=str(ANCHOR_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p2 = subprocess.Popen(cmd, cwd=str(ANCHOR_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out1, err1 = p1.communicate(timeout=90)
    out2, err2 = p2.communicate(timeout=90)

    assert p1.returncode == 0, f"Process 1 failed: {err1}"
    assert p2.returncode == 0, f"Process 2 failed: {err2}"

    j1 = json.loads(out1)
    j2 = json.loads(out2)
    assert j1["ok"] is True and j2["ok"] is True
    modes = {j1["backup"]["mode"], j2["backup"]["mode"]}
    assert modes == {"created", "verified_existing"}

    manifest_file = conc_out / "pre-w1-manifest.json"
    assert manifest_file.is_file()
    leftover_parts = list(conc_out.rglob("*.part"))
    assert leftover_parts == [], f"Leftover atomic temp files found: {leftover_parts}"

    mod = _load_backup_module()
    ver = mod.verify_backup_manifest(out_dir=conc_out, manifest_path=manifest_file, anchor_root=ANCHOR_ROOT)
    assert ver["ok"] is True and ver["verified_files"] >= 18

    # Distro hygiene scan across Wave-1 deliverables
    scan_targets = [
        BACKUP_SCRIPT,
        ANCHOR_ROOT / "tests" / "test_wave5_anvil_xval_paper1_2026_11_20.py",
        ANCHOR_ROOT / "tests" / "test_w1_backups_and_hermetic_gate_2026_11_22.py",
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in scan_targets]
    assert distro.scan_paths(pairs, root=ANCHOR_ROOT) == []


def test_w1_mockup_look_verdict_painted_uncovered() -> None:
    """Verify Wave-1 preview mockup look verdict is freshly generated and painted/uncovered on phone + desktop."""
    assert W1_MOCKUP_HTML.is_file(), f"Missing Wave-1 mockup HTML: {W1_MOCKUP_HTML}"
    if W1_LOOK_VERDICT.exists():
        W1_LOOK_VERDICT.unlink()
    W1_LOOK_DIR.mkdir(parents=True, exist_ok=True)

    ft_py = DEV_ROOT / "foundry-tools" / "ft.py"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ft_py),
            "look",
            str(W1_MOCKUP_HTML),
            "--check",
            "[data-w1-backup-pilot]",
            "--check",
            "#analysisSwitcherSelect",
            "--check",
            "#btnNewAnvilAnalysis",
            "--out",
            str(W1_LOOK_DIR),
            "--json",
        ],
        cwd=str(ANCHOR_ROOT),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, f"ft.py look failed: {proc.stderr}\n{proc.stdout}"
    look_doc = json.loads(proc.stdout)
    assert "error" not in look_doc
    results = look_doc.get("results") or []
    sizes = {vp.get("size") for vp in results}
    assert {"phone", "desktop"}.issubset(sizes)
    expected_selectors = {"[data-w1-backup-pilot]", "#analysisSwitcherSelect", "#btnNewAnvilAnalysis"}
    for vp in results:
        assert vp.get("errors") == []
        shot = Path(vp["screenshot"])
        assert shot.is_file() and shot.stat().st_size > 1_000
        checks_map = vp.get("checks") or {}
        assert set(checks_map.keys()) == expected_selectors, f"Unexpected or empty look checks on {vp.get('size')}: {list(checks_map.keys())}"
        for sel, elems in checks_map.items():
            assert len(elems) >= 1, f"Missing element {sel} on {vp.get('size')}"
            for el in elems:
                assert el.get("painted") is True
                assert el.get("coveredBy") is None
                assert el.get("onScreen") is True

    W1_LOOK_VERDICT.write_text(json.dumps(look_doc, indent=2) + "\n", encoding="utf-8")
