#!/usr/bin/env python3
"""Anvil v6 Wave 3 Test Suite — Trace-Policy Extended Scratch Replication Runner,
Pure-Core Receipt-Earned Ramanujan Audit, 3-Leg Refactoring Gate, Durable Job Runner,
and Locked Report v2 UI (`#sec-summary`, `#sec-matrix`, `#sec-refactoring`).
"""
from __future__ import annotations

import ast
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import pytest

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
FOUNDRY_ANVIL_DIR = ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil"
VENDOR_ANVIL_DIR = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
PLAN_DIR = ANCHOR_ROOT / "planning" / "2026-11-23-anvil-scoping-and-comprehension"
SYNC_SCRIPT = PLAN_DIR / "scripts" / "sync_anvil_vendor.py"
FT_PY = Path(os.environ.get("FOUNDRY_TOOLS_PY") or (ANCHOR_ROOT.parent / "foundry-tools" / "ft.py"))

if str(ANCHOR_ROOT) not in sys.path:
    sys.path.insert(0, str(ANCHOR_ROOT))

import distro  # noqa: E402
from steward_cockpit import anvil_replication_job, anvil_session, steward_routes  # noqa: E402


def _build_synthetic_w3_cockpit(base_dir: Path, *, init_git: bool = True) -> Path:
    """Create a 100% synthetic fixture repository with:
      - `synth_choice_model.py` (core estimator with FP32 tolerance + documented warm-start),
      - `synth_uplift_driver.py` (unseeded tie-break seed-drift defect on `tab:uplift`),
      - `synth_dag_flow.py` (active triangular flow where manuscript prose writes reversed eq),
      - allowlisted gitignored `data/panel_obs.csv` + cockpit `Datasets/holdout_obs.csv`,
      - `main.tex` with published Tables 1–3, and `workflow.sh`.
    """
    cdir = base_dir / "synth_w3_cockpit"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "data").mkdir()
    (cdir / "Datasets").mkdir()

    (cdir / "data" / "panel_obs.csv").write_text(
        "id,x,choice\n1,0.50,1\n2,1.20,0\n3,0.80,1\n4,1.50,1\n",
        encoding="utf-8",
    )
    (cdir / "Datasets" / "holdout_obs.csv").write_text(
        "id,uplift\n1,0.20\n2,0.20\n3,0.10\n4,0.30\n",
        encoding="utf-8",
    )

    (cdir / "synth_choice_model.py").write_text(
        textwrap.dedent(
            """\
            import csv
            from pathlib import Path

            def fit_choice_nll(csv_path: str = "data/panel_obs.csv", slope_penalty: float = 0.0) -> float:
                rows = list(csv.DictReader(Path(csv_path).read_text(encoding="utf-8").splitlines()))
                xs = [float(r["x"]) for r in rows]
                # Unpenalized slope matches published 0.6142 within FP32 1e-4 tolerance
                base = 0.6142 + (0.0001 if len(xs) == 4 else 0.0) + (0.045 * slope_penalty)
                return round(base, 6)

            if __name__ == "__main__":
                import json
                val = fit_choice_nll()
                print("ANVIL_METRICS_JSON:" + json.dumps({"metrics": {"holdout_nll": val}}))
            """
        ),
        encoding="utf-8",
    )

    (cdir / "synth_uplift_driver.py").write_text(
        textwrap.dedent(
            """\
            import csv
            import json
            import random
            from pathlib import Path

            def compute_policy_uplift(seed=None) -> float:
                rows = list(csv.DictReader(Path("Datasets/holdout_obs.csv").read_text(encoding="utf-8").splitlines()))
                vals = [float(r["uplift"]) for r in rows]
                # Genuine code defect when seed is None: unseeded tie-break shifts uplift from 14.9 to 14.2
                if seed is None:
                    _ = random.random()
                    return 14.2
                rng = random.Random(int(seed))
                _ = rng.random()
                return 14.9

            if __name__ == "__main__":
                u = compute_policy_uplift(seed=None)
                print("ANVIL_METRICS_JSON:" + json.dumps({
                    "metrics": {"policy_uplift": u},
                    "has_unseeded_rng": (u != 14.9),
                }))
            """
        ),
        encoding="utf-8",
    )

    (cdir / "synth_dag_flow.py").write_text(
        textwrap.dedent(
            """\
            import json

            def run_fast_inverse_pass(dim: int = 8) -> float:
                # Active O(1) inverse pass (code is right; manuscript Eq. 2 wrote sequential form)
                return -0.4812

            if __name__ == "__main__":
                score = run_fast_inverse_pass()
                print("ANVIL_METRICS_JSON:" + json.dumps({"metrics": {"flow_elbo": score}}))
            """
        ),
        encoding="utf-8",
    )

    (cdir / "workflow.sh").write_text(
        "# Table 1 (tab:choice_fit)\n"
        "python synth_choice_model.py\n"
        "# Table 2 (tab:uplift)\n"
        "python synth_uplift_driver.py\n"
        "# Table 3 (tab:dag_elbo)\n"
        "python synth_dag_flow.py\n",
        encoding="utf-8",
    )

    (cdir / "main.tex").write_text(
        textwrap.dedent(
            """\
            \\documentclass{article}
            \\title{Synthetic Choice and Flow Estimation Benchmark}
            \\begin{document}
            \\section{Choice Kernel}
            \\begin{table}
            \\caption{Holdout Negative Log-Likelihood}
            \\label{tab:choice_fit}
            \\begin{tabular}{lc}
            Metric & Value \\\\
            Holdout NLL & 0.6142 \\\\
            \\end{tabular}
            \\end{table}

            \\section{Policy Targeting}
            \\begin{table}
            \\caption{Targeted Policy Uplift}
            \\label{tab:uplift}
            \\begin{tabular}{lc}
            Metric & Value \\\\
            Policy Uplift & 14.9 \\\\
            \\end{tabular}
            \\end{table}

            \\section{Variational Flow}
            \\begin{table}
            \\caption{Variational ELBO Score}
            \\label{tab:dag_elbo}
            \\begin{tabular}{lc}
            Metric & Value \\\\
            Flow ELBO & -0.4812 \\\\
            \\end{tabular}
            \\end{table}
            \\end{document}
            """
        ),
        encoding="utf-8",
    )

    if init_git:
        (cdir / ".gitignore").write_text("data/\nDatasets/\n.anvil/\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=str(cdir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(cdir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=str(cdir), check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=str(cdir), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init synthetic fixture"], cwd=str(cdir), check=True, capture_output=True)

    return cdir


def _start_ephemeral_w3_server(cockpit_dir: Path) -> Tuple[ThreadingHTTPServer, int, threading.Thread]:
    static_dir = (ANCHOR_ROOT / "steward_cockpit" / "static").resolve()
    brand_dir = (ANCHOR_ROOT / "vendor" / "brand").resolve()
    cdir_str = str(cockpit_dir.resolve())

    class _W3Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(code))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _serve_file(self, base: Path, rel_part: str) -> None:
            clean_rel = rel_part.lstrip("/").split("?", 1)[0]
            cand = (base / clean_rel).resolve()
            if not cand.is_relative_to(base) or not cand.is_file():
                self.send_error(404)
                return
            data = cand.read_bytes()
            ctype, _ = mimetypes.guess_type(cand.name)
            self.send_response(200)
            self.send_header("Content-Type", ctype or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/steward-static/"):
                self._serve_file(static_dir, path[len("/steward-static/"):])
                return
            if path.startswith("/vendor/brand/"):
                self._serve_file(brand_dir, path[len("/vendor/brand/"):])
                return
            if path.startswith("/api/steward/"):
                verb = path[len("/api/steward/"):]
                qs_raw = parse_qs(parsed.query, keep_blank_values=True)
                qs_flat = {k: (v[0] if len(v) == 1 else v) for k, v in qs_raw.items()}
                resp_obj, status_code = steward_routes.handle_get(cdir_str, verb, qs_flat)
                self._send_json(status_code, resp_obj)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/steward/"):
                self.send_error(404)
                return
            verb = parsed.path[len("/api/steward/"):]
            length = int(self.headers.get("Content-Length") or "0")
            raw_b = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body_obj = json.loads(raw_b.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "message": "Invalid JSON"})
                return
            out, code = steward_routes.handle_post(cdir_str, verb, body_obj)
            self._send_json(code, out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _W3Handler)
    if int(srv.server_address[1]) == 8777:
        srv2 = ThreadingHTTPServer(("127.0.0.1", 0), _W3Handler)
        srv.server_close()
        srv = srv2
    port = int(srv.server_address[1])
    assert port != 8777
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    th.start()
    return srv, port, th


def _http_json(url: str, *, method: str = "GET", body: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Refused URL scheme")
    raw_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        url,
        data=raw_bytes,
        method=method,
        headers={"Content-Type": "application/json"} if raw_bytes is not None else {},
    )
    try:
        with urlopen(req, timeout=30.0) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as herr:
        return int(herr.code), json.loads(herr.read().decode("utf-8"))


def test_w3_trace_scratch_copy_data_bounds_escapes_timeouts_and_sys_executable(tmp_path: Path) -> None:
    """Verify `anvil_v4_trace` Wave 3 extensions:
      - `MAX_TIMEOUT_SEC == 300` preserved for interactive traces, plus `1800s` table / `5400s` total caps;
      - Gitignored allowlisted `data/` & `Datasets/` copied (never hardlinked; source mtime/mode/SHA-256 untouched);
      - `<= 2 GB` (`max_data_bytes`) bound refusal when exceeded;
      - Escape-attempt refusals (`..`, absolute path, non-allowlisted dir, symlink/junction);
      - Pinned `sys.executable` (rejecting custom interpreter paths) and `PIPELINE_DEPENDENCY_MISSING` classification;
      - Phase B AST sink check refusing dangerous calls/imports in scratch patches.
    """
    mods = anvil_session._load_anvil_v4_modules()
    v4_trace = mods["anvil_v4_trace"]
    v4_proc = mods["anvil_v4_process"]

    assert v4_trace.MAX_TIMEOUT_SEC == 300.0
    assert v4_trace.MAX_REPLICATION_TABLE_TIMEOUT_SEC == 1800.0
    assert v4_trace.MAX_REPLICATION_TOTAL_TIMEOUT_SEC == 5400.0
    assert v4_trace.MAX_ALLOWLISTED_DATA_BYTES == 2 * 1024 * 1024 * 1024

    cdir = _build_synthetic_w3_cockpit(tmp_path, init_git=True)
    src_csv = cdir / "data" / "panel_obs.csv"
    pre_stat = os.stat(src_csv)
    pre_sha = hashlib.sha256(src_csv.read_bytes()).hexdigest()

    # Script mutates data/panel_obs.csv inside scratch — verify source file & attributes stay 100% untouched!
    (cdir / "mutate_scratch_check.py").write_text(
        "import pathlib, sys\n"
        "p = pathlib.Path('data/panel_obs.csv')\n"
        "assert p.is_file()\n"
        "p.write_text('mutated_in_scratch\\n', encoding='utf-8')\n"
        "print('{\"interp\": ' + repr(sys.executable) + ', \"metrics\": {\"ok_flag\": 1.0}}')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "mutate_scratch_check.py"], cwd=str(cdir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add scratch check"], cwd=str(cdir), check=True, capture_output=True)

    scratch_probe = tmp_path / "manual_scratch"
    staged_wt = v4_trace._stage_isolated_worktree_copy(
        cdir,
        scratch_probe,
        allowlisted_data_roots=["repo:data", "cockpit:Datasets"],
        cockpit_root=cdir,
    )
    staged_csv = staged_wt / "data" / "panel_obs.csv"
    assert staged_csv.is_file()
    assert (staged_wt / "Datasets" / "holdout_obs.csv").is_file()
    # Prove pure copy (never hardlinked: nlink == 1 or distinct file index)
    assert os.stat(src_csv).st_nlink == 1

    rep_rec = v4_trace.run_replication_table_in_scratch(
        cdir,
        ["python", "mutate_scratch_check.py"],
        approve_run=True,
        timeout_sec=30.0,
        allowlisted_data_roots=["repo:data", "cockpit:Datasets"],
        cockpit_root=cdir,
    )
    assert rep_rec["ok"] is True
    assert rep_rec["exit_code"] == 0
    assert Path(rep_rec["pinned_interpreter"]).resolve() == Path(sys.executable).resolve()
    assert hashlib.sha256(src_csv.read_bytes()).hexdigest() == pre_sha
    assert os.stat(src_csv).st_mtime_ns == pre_stat.st_mtime_ns

    # <= 2 GB numeric bound refusal path when data exceeds cap
    with pytest.raises(v4_proc.AnvilRefusalError) as bound_exc:
        v4_trace._stage_isolated_worktree_copy(
            cdir,
            tmp_path / "scratch_bound",
            allowlisted_data_roots=["repo:data"],
            max_data_bytes=10,
        )
    assert bound_exc.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    # Timeout cap refusals (interactive >300s refused; replication >1800s or >5400s refused)
    with pytest.raises(v4_proc.AnvilRefusalError) as tr_to_exc:
        v4_trace.run_consented_trace(cdir, ["python", "synth_choice_model.py"], approve_run=True, timeout_sec=301.0)
    assert tr_to_exc.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    with pytest.raises(v4_proc.AnvilRefusalError) as rep_to_exc:
        v4_trace.run_replication_table_in_scratch(cdir, ["python", "synth_choice_model.py"], approve_run=True, timeout_sec=1801.0)
    assert rep_to_exc.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    with pytest.raises(v4_proc.AnvilRefusalError) as tot_to_exc:
        v4_trace.run_replication_table_in_scratch(
            cdir, ["python", "synth_choice_model.py"], approve_run=True, timeout_sec=30.0, remaining_total_sec=5401.0
        )
    assert tot_to_exc.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    # Escape-attempt refusals (.., absolute path, non-allowlisted folder, symlink/junction)
    outside_d = tmp_path / "outside_data"
    outside_d.mkdir()
    (outside_d / "leak.csv").write_text("secret\n", encoding="utf-8")
    (cdir / "notes").mkdir()

    for bad_root in ("../outside_data", str(outside_d.resolve()), "repo:notes"):
        with pytest.raises(v4_proc.AnvilRefusalError) as esc_exc:
            v4_trace._stage_isolated_worktree_copy(
                cdir, tmp_path / f"esc_{ abs(hash(bad_root)) }", allowlisted_data_roots=[bad_root], cockpit_root=cdir
            )
        assert esc_exc.value.error_code == "PATH_ESCAPE_REFUSED"

    junc_in_data = cdir / "data" / "linked_out"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junc_in_data), str(outside_d)], check=True, capture_output=True)
    else:
        junc_in_data.symlink_to(outside_d, target_is_directory=True)
    try:
        with pytest.raises(v4_proc.AnvilRefusalError) as sym_exc:
            v4_trace._stage_isolated_worktree_copy(
                cdir, tmp_path / "esc_sym", allowlisted_data_roots=["repo:data"], cockpit_root=cdir
            )
        assert sym_exc.value.error_code == "PATH_ESCAPE_REFUSED"
    finally:
        if os.name == "nt":
            os.rmdir(junc_in_data)
        else:
            junc_in_data.unlink()

    # Client/repo custom interpreter path is strictly refused
    fake_interp = tmp_path / "fake_python.exe"
    fake_interp.write_bytes(b"MZ")
    with pytest.raises(v4_proc.AnvilRefusalError) as bin_exc:
        v4_trace.run_replication_table_in_scratch(cdir, [str(fake_interp), "synth_choice_model.py"], approve_run=True)
    assert bin_exc.value.error_code == "EXECUTION_POLICY_REFUSED"

    # Missing third-party package classified explicitly as PIPELINE_DEPENDENCY_MISSING
    (cdir / "missing_dep_script.py").write_text("import nonexistent_scipkg_w3_999\n", encoding="utf-8")
    subprocess.run(["git", "add", "missing_dep_script.py"], cwd=str(cdir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add missing dep script"], cwd=str(cdir), check=True, capture_output=True)
    dep_rec = v4_trace.run_replication_table_in_scratch(cdir, ["python", "missing_dep_script.py"], approve_run=True)
    assert dep_rec["exit_code"] != 0
    assert dep_rec["error_class"] == "PIPELINE_DEPENDENCY_MISSING"
    assert dep_rec["missing_module"] == "nonexistent_scipkg_w3_999"

    # Phase B AST sink check refuses unsafe patch calls in scratch
    evil_diff = (
        "--- a/synth_dag_flow.py\n"
        "+++ b/synth_dag_flow.py\n"
        "@@ -1,4 +1,5 @@\n"
        " import json\n"
        "+import subprocess\n"
        " \n"
        " def run_fast_inverse_pass(dim: int = 8) -> float:\n"
    )
    with pytest.raises(v4_proc.AnvilRefusalError) as sink_exc:
        v4_trace.run_replication_table_in_scratch(
            cdir,
            ["python", "synth_dag_flow.py"],
            approve_run=True,
            candidate_diff=evil_diff,
            candidate_diff_sha256=hashlib.sha256(evil_diff.encode("utf-8")).hexdigest(),
        )
    assert sink_exc.value.error_code == "EXECUTION_POLICY_REFUSED"


def test_w3_pure_core_6_error_classes_synthetic_fixtures_rungs_and_3leg_gate(tmp_path: Path) -> None:
    """Exercise pure-core `anvil_replication_audit`:
      - `parse_published_tables` over LaTeX & Markdown,
      - All 6 deterministic error classes via `classify_error` & `compare_metrics`,
      - `assign_rung` downgrading forged/stale/failed `OBSERVED` citations to `CLAIMED` and cached to `CACHED_BASELINE`,
      - `decide_refactor_gate` enforcing 3-leg `APPROVED` vs wrong-side `BLOCKED` vs `Not Vetted (Claimed)`.
    """
    audit = anvil_session._load_anvil_v4_modules()["anvil_replication_audit"]
    cdir = _build_synthetic_w3_cockpit(tmp_path, init_git=False)

    parsed_tabs = audit.parse_published_tables({
        "main.tex": (cdir / "main.tex").read_text(encoding="utf-8"),
        "notes.md": "# Holdout Summary\n| Metric | Score |\n| --- | --- |\n| Aux Metric | 0.42 |\n",
    })
    assert len(parsed_tabs) == 4
    by_id = {t["table_id"]: t for t in parsed_tabs}
    assert by_id["tab:choice_fit"]["metrics"]["holdout_nll"] == pytest.approx(0.6142)
    assert by_id["tab:uplift"]["metrics"]["policy_uplift"] == pytest.approx(14.9)
    assert by_id["tab:dag_elbo"]["metrics"]["flow_elbo"] == pytest.approx(-0.4812)

    # All 6 error classes
    assert audit.classify_error(0.6142, 0.6142) == "EXACT_REPLICATION"
    assert audit.classify_error(0.6142, 0.6144, abs_tol=1e-6, float_tol=1e-3) == "FLOAT_REDUCTION_TOLERANCE"
    assert audit.classify_error(14.9, 14.2, has_unseeded_rng=True, seed_span=(14.1, 15.0)) == "STOCHASTIC_SEED_MC_VARIANCE"
    assert audit.classify_error(-0.4812, -0.4812, used_cached_baseline=True) == "CACHED_PRECOMPUTED_BASELINE"
    assert audit.classify_error(0.5, None, missing_dependency="torch_scatter", exit_code=1) == "PIPELINE_DEPENDENCY_MISSING"
    assert audit.classify_error(-0.4812, -1.9500, formula_mismatch=True) == "SPECIFICATION_FORMULA_MISMATCH"

    cmp_res = audit.compare_metrics(
        {"exact_m": 1.0, "fp32_m": 0.6142, "seed_m": 14.9, "spec_m": -0.4812},
        {
            "exact_m": 1.0,
            "fp32_m": 0.6143,
            "seed_m": {"value": 14.2, "has_unseeded_rng": True},
            "spec_m": {"value": -1.25, "formula_mismatch": True},
        },
    )
    seen_classes = {c["error_class"] for c in cmp_res["cells"]}
    assert seen_classes == {
        "EXACT_REPLICATION",
        "FLOAT_REDUCTION_TOLERANCE",
        "STOCHASTIC_SEED_MC_VARIANCE",
        "SPECIFICATION_FORMULA_MISMATCH",
    }

    # Ramanujan Honesty-Law rungs
    valid_sha = "a" * 64
    stale_sha = "b" * 64
    receipts = {
        "tab:choice_fit": {
            "scope_sha256": valid_sha,
            "script": "synth_choice_model.py",
            "exit_code": 0,
            "output_summary": "holdout_nll=0.6143",
        },
        "tab:cached": {
            "scope_sha256": valid_sha,
            "script": "load_cached.py",
            "exit_code": 0,
            "used_cached_baseline": True,
            "output_summary": "cached=1",
        },
        "tab:stale": {
            "scope_sha256": stale_sha,
            "script": "synth_choice_model.py",
            "exit_code": 0,
        },
        "tab:failed": {
            "scope_sha256": valid_sha,
            "script": "synth_uplift_driver.py",
            "exit_code": 2,
        },
        "tab:refuted": {
            "scope_sha256": valid_sha,
            "script": "synth_dag_flow.py",
            "exit_code": 0,
            "contradicts_claim": True,
            "output_summary": "O(D) != O(1)",
        },
    }

    r_obs = audit.assign_rung({"proposed_rung": "OBSERVED", "receipt_id": "tab:choice_fit"}, receipts, valid_sha)
    assert r_obs["rung"] == "OBSERVED" and "synth_choice_model.py" in r_obs["inline_ref"]

    r_cached = audit.assign_rung({"proposed_rung": "OBSERVED", "receipt_id": "tab:cached"}, receipts, valid_sha)
    assert r_cached["rung"] == "CACHED_BASELINE" and r_cached["downgraded"] is True

    for bad_id in ("forged_nonexistent_receipt", "tab:stale", "tab:failed"):
        r_down = audit.assign_rung({"proposed_rung": "OBSERVED", "receipt_id": bad_id}, receipts, valid_sha)
        assert r_down["rung"] == "CLAIMED"
        assert r_down["downgraded"] is True
        assert r_down["inline_ref"] == ""

    r_ref = audit.assign_rung({"proposed_rung": "REFUTED", "receipt_id": "tab:refuted"}, receipts, valid_sha)
    assert r_ref["rung"] == "REFUTED"

    # 3-Leg Refactoring Gate: APPROVED vs BLOCKED (wrong-side) vs Not Vetted (Claimed)
    diff_txt = "--- a/synth_uplift_driver.py\n+++ b/synth_uplift_driver.py\n@@ -1 +1 @@\n-x\n+y\n"
    diff_sha = hashlib.sha256(diff_txt.encode("utf-8")).hexdigest()
    cand_ok = {"id": "fix-seed", "diff": diff_txt, "diff_sha256": diff_sha}
    leg1_2fam = {"scope_sha256": valid_sha, "cross_family_attested": True, "families": ["claude", "gemini"], "verdict": "PASS"}
    leg2_ram = {"scope_sha256": valid_sha, "code_defect_confirmed": True, "wrong_side": False, "verdict": "APPROVED"}
    leg3_pb = {"scope_sha256": valid_sha, "diff_sha256": diff_sha, "exit_code": 0, "metric_improved_or_preserved": True, "regressions": 0}

    g_app = audit.decide_refactor_gate(cand_ok, leg1_2fam, leg2_ram, leg3_pb, valid_sha)
    assert g_app["verdict"] == "APPROVED"

    # Wrong-side edit -> BLOCKED
    g_blk = audit.decide_refactor_gate(
        {"id": "fix-wrong-side"},
        leg1_2fam,
        {"scope_sha256": valid_sha, "wrong_side": True, "target_side": "paper", "verdict": "BLOCKED", "reason": "Update manuscript equation, not working code."},
        None,
        valid_sha,
    )
    assert g_blk["verdict"] == "BLOCKED"

    # Single-family xval or missing Phase B -> Not Vetted (Claimed)
    g_single = audit.decide_refactor_gate(
        cand_ok,
        {"scope_sha256": valid_sha, "cross_family_attested": False, "families": ["claude"], "verdict": "PASS"},
        leg2_ram,
        leg3_pb,
        valid_sha,
    )
    assert g_single["verdict"] == "NOT_VETTED_CLAIMED"
    assert g_single["label"] == "Not Vetted (Claimed)"

    g_no_pb = audit.decide_refactor_gate(cand_ok, leg1_2fam, leg2_ram, None, valid_sha)
    assert g_no_pb["verdict"] == "NOT_VETTED_CLAIMED"


def test_no_mockup_sample_literals_without_receipt(tmp_path: Path) -> None:
    """Verify:
      1) Zero mockup sample literals from `replication-v2-dossier-matrix-refactoring.html` leak into
         `anvil_replication_audit.py`, `anvil_replication_job.py`, `anvil.js`, `anvil.html`, or rendered bundles;
      2) Grep + AST gates on `anvil_replication_audit.py`: zero `subprocess`, `_safe_subprocess_run`,
         `pickle`, `torch.load`, `allow_pickle`, `readRDS`, `eval`, `exec`, and zero I/O;
      3) `probe_block.test_cmd` raw command strings are policy-refused (`403 EXECUTION_POLICY_REFUSED`).
    """
    audit_paths = [
        FOUNDRY_ANVIL_DIR / "scripts" / "anvil_replication_audit.py",
        VENDOR_ANVIL_DIR / "scripts" / "anvil_replication_audit.py",
    ]
    forbidden_audit_re = re.compile(
        r"\b(?:subprocess|_safe_subprocess_run|pickle|allow_pickle|readRDS|eval|exec|open)\b|torch\.load"
    )
    for ap in audit_paths:
        src = ap.read_text(encoding="utf-8")
        hits = forbidden_audit_re.findall(src)
        assert hits == [], f"Forbidden token(s) in {ap.name}: {hits}"
        tree = ast.parse(src, filename=ap.name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod_names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for mn in mod_names:
                    assert mn.split(".")[0] not in {"os", "sys", "pathlib", "shutil", "tempfile", "subprocess", "urllib", "http", "socket", "pickle"}

    mockup_literals = [
        "good" + "year",
        "sam" + "sung",
        "vac" + "cine",
        "german " + "credit",
        "conditional" + "iaf",
        "conditional" + "maf",
        "torchmixtureofexperts" + "mnl",
        "run_uplift_" + "targeting",
        "#a41c" + "92",
        "#3d08" + "b1",
    ]
    checked_shipped = [
        FOUNDRY_ANVIL_DIR / "scripts" / "anvil_replication_audit.py",
        VENDOR_ANVIL_DIR / "scripts" / "anvil_replication_audit.py",
        ANCHOR_ROOT / "steward_cockpit" / "anvil_replication_job.py",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html",
    ]
    for fp in checked_shipped:
        low_txt = fp.read_text(encoding="utf-8").lower()
        for lit in mockup_literals:
            assert lit not in low_txt, f"Mockup sample literal {lit!r} leaked into {fp.name}"

    audit_mod = anvil_session._load_anvil_v4_modules()["anvil_replication_audit"]
    bundle = audit_mod.build_replication_report_bundle(
        scope_sha256="c" * 64,
        repo_name="clean_synth_repo",
        paper_title="Clean Synthetic Paper",
    )
    serialized = json.dumps(bundle).lower()
    for lit in mockup_literals:
        assert lit not in serialized

    # Verify probe_block.test_cmd raw string refusal over steward_routes.handle_post and validate_probe_test_argv
    cdir = _build_synthetic_w3_cockpit(tmp_path, init_git=False)
    anvil_session.start_cockpit_session(cdir, mode="code", software_spec=".")
    resp_pb, code_pb = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "probe_block", "block_id": "synth_choice_model.py", "test_cmd": "echo pwned"},
    )
    assert code_pb == 403
    assert resp_pb["error_code"] == "EXECUTION_POLICY_REFUSED"

    v4_xval = anvil_session._load_anvil_v4_modules()["anvil_v4_xval"]
    v4_proc = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]
    with pytest.raises(v4_proc.AnvilRefusalError) as xval_pb_exc:
        v4_xval.validate_probe_test_argv(cdir, "python synth_choice_model.py")
    assert xval_pb_exc.value.error_code == "EXECUTION_POLICY_REFUSED"
    valid_pol = v4_xval.validate_probe_test_argv(cdir, ["python", "synth_choice_model.py"])
    assert valid_pol["target_rel_script"] == "synth_choice_model.py"


def test_w3_job_concurrency_singleflight_409_repeat_idempotence_and_5row_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `anvil_replication_job`:
      - Full 5-row failure-state table keeping `500 UNKNOWN` and `200 not yet run` separate,
      - Two concurrent child processes racing `start_replication_job` on the same `scope_sha256` ->
        atomic lock serialization + single-flight `409 REPLICATION_JOB_ALREADY_RUNNING`,
      - Phase A + Phase B consented scratch patch replay over synthetic fixture -> empty post-run
        source-repo SHA-256 diff, forged `OBSERVED` -> `CLAIMED`, 3-leg `APPROVED` vs `BLOCKED`,
        and scrubbed `DELIVERABLES.md` export!
    """
    monkeypatch.setenv("ANCHOR_ANVIL_V6", "1")

    # 1. All 5 failure-state rows keep 500 UNKNOWN and 200 not-yet-run separate
    rows_expected = [
        ("dependency-missing", 503, False, "PIPELINE_DEPENDENCY_MISSING"),
        ("dependency-slow-or-killed", 504, False, "timed out or was cancelled"),
        ("dependency-returns-garbage", 502, False, "Invalid replication receipt"),
        ("backing-store-unreadable", 500, True, "UNKNOWN:"),
        ("empty-but-valid", 200, False, "not yet run"),
    ]
    for rkey, exp_http, exp_unk, exp_sub in rows_expected:
        p_row, c_row = anvil_replication_job.build_replication_failure_response(rkey)
        assert c_row == exp_http
        assert p_row["unknown_state"] is exp_unk
        assert exp_sub in p_row["message"]

    cdir = _build_synthetic_w3_cockpit(tmp_path, init_git=True)
    # Add a slow script to test single-flight 409 concurrency & process-tree cancel cleanly
    (cdir / "slow_step.py").write_text("import time\ntime.sleep(1.5)\nprint('{\"metrics\": {\"slow\": 1.0}}')\n", encoding="utf-8")
    subprocess.run(["git", "add", "slow_step.py"], cwd=str(cdir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add slow step"], cwd=str(cdir), check=True, capture_output=True)

    lock_res, lock_code = anvil_session.lock_scope_v2(cdir, {})
    assert lock_code == 200
    aid = lock_res["analysis_id"]
    scope_sha = lock_res["scope_sha256"]

    # Before execution -> 200 empty-but-valid ("not yet run")
    idle_state, idle_code = anvil_replication_job.get_replication_state(cdir, analysis_id=aid)
    assert idle_code == 200
    assert idle_state["status_kind"] == "empty-but-valid"
    assert "not yet run" in idle_state["message"]
    assert all(r["replication_status"] == "not yet run" for r in idle_state["report"]["matrix"])

    # Corrupt job backing store -> 500 UNKNOWN (never collapsed into 200 not yet run!)
    _, store_root = anvil_session.resolve_store_root(cdir, aid)
    rec_file = store_root / ".anvil" / "v4" / "replication_audit_receipt.json"
    rec_file.parent.mkdir(parents=True, exist_ok=True)
    rec_file.write_text("{corrupt-json", encoding="utf-8")
    unk_state, unk_code = anvil_replication_job.get_replication_state(cdir, analysis_id=aid)
    assert unk_code == 500 and unk_state["unknown_state"] is True and unk_state["badge"] == "UNKNOWN"
    rec_file.unlink()

    # 2. Multi-process concurrency & single-flight 409 test
    c1, _ = anvil_replication_job.issue_replication_consent(cdir, {"analysis_id": aid, "phase": "A"})
    c2, _ = anvil_replication_job.issue_replication_consent(cdir, {"analysis_id": aid, "phase": "A"})
    # Inject slow_step into entrypoints temporarily on a separate test cockpit for fast race determinism
    race_cdir = _build_synthetic_w3_cockpit(tmp_path / "race_env", init_git=False)
    (race_cdir / "synth_choice_model.py").write_text("import time\ntime.sleep(1.2)\nprint('{\"metrics\": {\"holdout_nll\": 0.6142}}')\n", encoding="utf-8")
    race_lock, _ = anvil_session.lock_scope_v2(race_cdir, {})
    race_aid = race_lock["analysis_id"]
    race_sha = race_lock["scope_sha256"]
    rc1, _ = anvil_replication_job.issue_replication_consent(race_cdir, {"analysis_id": race_aid, "phase": "A"})
    rc2, _ = anvil_replication_job.issue_replication_consent(race_cdir, {"analysis_id": race_aid, "phase": "A"})

    race_worker = textwrap.dedent(
        """\
        import json, os, sys
        sys.path.insert(0, {anchor})
        os.environ["ANCHOR_ANVIL_V6"] = "1"
        from steward_cockpit import anvil_replication_job
        res, code = anvil_replication_job.start_replication_job({cdir}, {{
            "analysis_id": {aid},
            "scope_sha256": {sha},
            "consent_token": {tok},
            "sync": True,
        }})
        print(json.dumps({{"code": code, "err": res.get("error_code", "")}}))
        """
    )
    p_a = subprocess.Popen(
        [sys.executable, "-c", race_worker.format(anchor=json.dumps(str(ANCHOR_ROOT)), cdir=json.dumps(str(race_cdir)), aid=json.dumps(race_aid), sha=json.dumps(race_sha), tok=json.dumps(rc1["consent_token"]))],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    time.sleep(0.18)
    p_b = subprocess.Popen(
        [sys.executable, "-c", race_worker.format(anchor=json.dumps(str(ANCHOR_ROOT)), cdir=json.dumps(str(race_cdir)), aid=json.dumps(race_aid), sha=json.dumps(race_sha), tok=json.dumps(rc2["consent_token"]))],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out_a, err_a = p_a.communicate(timeout=45)
    out_b, err_b = p_b.communicate(timeout=45)
    assert p_a.returncode == 0, err_a
    assert p_b.returncode == 0, err_b
    ra = json.loads(out_a.strip().splitlines()[-1])
    rb = json.loads(out_b.strip().splitlines()[-1])
    assert sorted([ra["code"], rb["code"]]) == [200, 409]
    assert "REPLICATION_JOB_ALREADY_RUNNING" in {ra["err"], rb["err"]}

    # 2b. Live cancel_replication_job -> _kill_process_tree -> 504 TIMEOUT_OR_CANCELLED
    rc_can, _ = anvil_replication_job.issue_replication_consent(race_cdir, {"analysis_id": race_aid, "phase": "A"})
    bg_start, bg_code = anvil_replication_job.start_replication_job(
        race_cdir,
        {"analysis_id": race_aid, "scope_sha256": race_sha, "consent_token": rc_can["consent_token"], "sync": False},
    )
    assert bg_code == 202
    time.sleep(0.15)
    can_res, can_code = anvil_replication_job.cancel_replication_job(
        race_cdir, {"analysis_id": race_aid, "job_id": bg_start["job_id"]}
    )
    assert can_code == 504
    assert can_res["cancelled"] is True
    assert can_res["status_kind"] == "dependency-slow-or-killed"

    # 3. Given/When/Then Full Phase A + Phase B Scratch Replay on `cdir`
    pre_repo_snap = anvil_replication_job._snapshot_source_repo_sha256(cdir)
    seed_fix_diff = (
        "--- a/synth_uplift_driver.py\n"
        "+++ b/synth_uplift_driver.py\n"
        "@@ -17,3 +17,3 @@\n"
        " if __name__ == \"__main__\":\n"
        "-    u = compute_policy_uplift(seed=None)\n"
        "+    u = compute_policy_uplift(seed=42)\n"
        "     print(\"ANVIL_METRICS_JSON:\" + json.dumps({\n"
    )
    seed_diff_sha = hashlib.sha256(seed_fix_diff.encode("utf-8")).hexdigest()
    planted_host_path = "C:" + "\\Users\\" + "alice\\private\\notes.tex"
    planted_secret_tok = "sk-" + "1234567890abcdef"

    claims_in = [
        {
            "table_id": "tab:choice_fit",
            "paper_summary": "Table 1 Holdout NLL (0.6142)",
            "code_ref": "synth_choice_model.py",
            "metrics": {"holdout_nll": 0.6142},
            "proposed_rung": "OBSERVED",
        },
        {
            "table_id": "tab:uplift",
            "paper_summary": "Table 2 Policy Uplift (14.9%)",
            "code_ref": "synth_uplift_driver.py",
            "metrics": {"policy_uplift": 14.9},
            "proposed_rung": "OBSERVED",
            "jump_fix_id": "fix-seed-tie",
        },
        {
            "table_id": "forged_unexecuted_claim",
            "paper_summary": f"Forged Theorem 9 Claim ( host {planted_host_path} api_key={planted_secret_tok} )",
            "code_ref": "nonexistent_verifier.py",
            "proposed_rung": "OBSERVED",
        },
    ]
    cands_in = [
        {
            "id": "fix-seed-tie",
            "table_id": "tab:uplift",
            "title": "Seeded Tie-Handling in synth_uplift_driver.py",
            "where": "synth_uplift_driver.py:L17",
            "summary": "Unseeded tie-break shifts policy_uplift by -0.7.",
            "diff": seed_fix_diff,
            "diff_sha256": seed_diff_sha,
        },
        {
            "id": "fix-wrong-prose",
            "table_id": "tab:dag_elbo",
            "title": "Rewrite Fast Inverse Pass to Sequential Pass",
            "where": "synth_dag_flow.py:L3",
            "summary": "Naive literal match to prose Eq. 2.",
            "diff": "",
        },
    ]
    xval_2fam = {
        "scope_sha256": scope_sha,
        "cross_family_attested": True,
        "families": ["claude", "gemini"],
        "verdict": "PASS",
    }
    ram_verdicts = {
        "fix-seed-tie": {
            "scope_sha256": scope_sha,
            "code_defect_confirmed": True,
            "wrong_side": False,
            "verdict": "APPROVED",
        },
        "fix-wrong-prose": {
            "scope_sha256": scope_sha,
            "code_defect_confirmed": False,
            "wrong_side": True,
            "target_side": "paper",
            "verdict": "BLOCKED",
            "reason": "Code implements O(1) inverse pass accurately; update manuscript prose Eq. 2 instead.",
        },
    }

    # Phase A run (before Phase B, fix-seed-tie is NOT_VETTED_CLAIMED; fix-wrong-prose is BLOCKED)
    res_a, code_a = anvil_replication_job.start_replication_job(
        cdir,
        {
            "analysis_id": aid,
            "scope_sha256": scope_sha,
            "consent_token": c1["consent_token"],
            "phase": "A",
            "sync": True,
            "claims": claims_in,
            "refactor_candidates": cands_in,
            "xval_receipt": xval_2fam,
            "ramanujan_verdicts": ram_verdicts,
        },
        _trusted_test_seed=True,
    )
    assert code_a == 200
    rep_a = res_a["report"]
    # Forged OBSERVED downgraded to CLAIMED!
    rows_by_id = {r["row_id"]: r for r in rep_a["matrix"]}
    assert rows_by_id["forged_unexecuted_claim"]["ramanujan_rung"] == "CLAIMED"
    assert rows_by_id["forged_unexecuted_claim"]["downgraded"] is True
    assert rows_by_id["tab:choice_fit"]["ramanujan_rung"] == "OBSERVED"
    assert len(rep_a["approved_fixes"]) == 0
    assert [x["id"] for x in rep_a["rejected_fixes"]] == ["fix-wrong-prose"]
    assert [x["id"] for x in rep_a["not_vetted_fixes"]] == ["fix-seed-tie"]

    # Refuses queueing unvetted or blocked fix before Phase B passes
    q_refuse, q_ref_code = anvil_replication_job.queue_vetted_refactoring(
        cdir, {"analysis_id": aid, "candidate_id": "fix-seed-tie", "operator_consent": True}
    )
    assert q_ref_code == 403

    # Phase B consented scratch patch replay -> upgrades `fix-seed-tie` to 3-leg APPROVED while source repo stays untouched!
    cb_consent, cb_code = anvil_replication_job.issue_replication_consent(
        cdir, {"analysis_id": aid, "phase": "B", "candidate_id": "fix-seed-tie", "candidate_diff": seed_fix_diff}
    )
    assert cb_code == 200
    res_b, code_b = anvil_replication_job.start_replication_job(
        cdir,
        {
            "analysis_id": aid,
            "scope_sha256": scope_sha,
            "consent_token": cb_consent["consent_token"],
            "phase": "B",
            "candidate_id": "fix-seed-tie",
            "candidate_diff": seed_fix_diff,
            "sync": True,
        },
    )
    assert code_b == 200
    assert res_b["source_repo_diff"] == []
    post_repo_snap = anvil_replication_job._snapshot_source_repo_sha256(cdir)
    assert anvil_replication_job._diff_source_snapshots(pre_repo_snap, post_repo_snap) == []

    rep_b = res_b["report"]
    assert [x["id"] for x in rep_b["approved_fixes"]] == ["fix-seed-tie"]
    assert [x["id"] for x in rep_b["rejected_fixes"]] == ["fix-wrong-prose"]

    # Export to DELIVERABLES.md scrubs planted user path + secret key, and repeat export is idempotent
    exp1, exp1_code = anvil_replication_job.export_replication_deliverables(cdir, {"analysis_id": aid})
    exp2, exp2_code = anvil_replication_job.export_replication_deliverables(cdir, {"analysis_id": aid})
    assert exp1_code == 200 and exp2_code == 200
    assert exp1["markdown"] == exp2["markdown"]
    assert planted_host_path[:9] not in exp1["markdown"]
    assert planted_secret_tok not in exp1["markdown"]
    assert "[REDACTED]" in exp1["markdown"]
    assert (cdir / "DELIVERABLES.md").read_text(encoding="utf-8").count("ANVIL-REPLICATION-REPORT.md") == 1


def test_w3_playwright_report_v2_ui_states_drawer_export_and_ft_look(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live Playwright + `ft.py look --check` at desktop (`1560x960`) & phone (`390x844`):
      - Opens Report v2 from `#doneShelf`, verifies honest `'not yet run'` state before consent,
      - Runs consented Phase A + Phase B, renders `#sec-summary`, `#sec-matrix` (filters + rungs),
        and `#sec-refactoring` (inline Queue Refactoring drawer with ZERO `window.alert()`),
      - Exports scrubbed `DELIVERABLES.md`, passes desktop & phone `ft.py look --check`,
      - Verifies Foundry==vendor SHA-256 parity and `distro.scan_paths() == []`.
    """
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("ANCHOR_ANVIL_V6", "1")
    cdir = _build_synthetic_w3_cockpit(tmp_path, init_git=True)
    srv, port, _th = _start_ephemeral_w3_server(cdir)
    anvil_url = f"http://127.0.0.1:{port}/steward-static/anvil.html?pid=synth_w3&name=SynthW3Cockpit"
    look_out = tmp_path / "ft_look_w3"
    look_out.mkdir()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1560, "height": 960})
            alerts_seen: List[str] = []
            page_errors: List[str] = []
            page.on("dialog", lambda dlg: (alerts_seen.append(dlg.message), dlg.dismiss()))
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            # Lock scope -> open Scoping shelf -> click Replication & Ramanujan Report (Not run yet) ->
            page.goto(anvil_url, wait_until="networkidle")
            page.locator("#btnLockScope").wait_for(state="visible", timeout=10000)
            page.locator("#btnLockScope").click()
            page.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=15000)

            page.locator("#btnOpenLauncherDrawer").click()
            page.locator("#doneShelf [data-open-replication-id]").wait_for(state="visible", timeout=10000)
            aid = page.locator("#doneShelf [data-open-replication-id]").first.get_attribute("data-open-replication-id")
            assert aid
            page.locator("#doneShelf [data-open-replication-id]").first.click()

            page.locator("#sec-summary").wait_for(state="visible", timeout=10000)
            assert page.locator('[data-rep-run-state="not_yet_run"]').count() == 1
            assert "not yet run" in page.locator("#sec-matrix").inner_text().lower()

            # Open two-phase consent modal & run Phase A from UI
            page.locator("#btnOpenReplicationConsent").click()
            page.locator("#replication-consent-modal").wait_for(state="visible", timeout=10000)
            assert re.fullmatch(r"[0-9a-f]{64}", page.locator("#repConsentSha").inner_text().strip())
            page.locator("#btnConfirmReplicationConsent").click()
            page.wait_for_function(
                "() => document.querySelector('#sec-matrix') && document.querySelector('#sec-matrix').textContent.includes('OBSERVED')",
                timeout=20000,
            )

            # Seed a 3-leg approved candidate + blocked candidate via API and reload Report v2 to test drawer + filters
            seed_fix_diff = (
                "--- a/synth_uplift_driver.py\n"
                "+++ b/synth_uplift_driver.py\n"
                "@@ -17,3 +17,3 @@\n"
                " if __name__ == \"__main__\":\n"
                "-    u = compute_policy_uplift(seed=None)\n"
                "+    u = compute_policy_uplift(seed=42)\n"
                "     print(\"ANVIL_METRICS_JSON:\" + json.dumps({\n"
            )
            scope_ca2_code, c_a2 = _http_json(
                f"http://127.0.0.1:{port}/api/steward/anvil/replication",
                method="POST",
                body={"action": "replication_consent", "analysis_id": aid, "phase": "A"},
            )
            assert scope_ca2_code == 200
            scope_sha = c_a2["scope_sha256"]
            assert re.fullmatch(r"[0-9a-f]{64}", scope_sha)
            # Seed server-owned xval_receipt.json + ramanujan_verdicts.json on disk, then run Phase A + B via HTTP
            _, ui_store_root = anvil_session.resolve_store_root(cdir, aid)
            (ui_store_root / ".anvil" / "v4").mkdir(parents=True, exist_ok=True)
            (ui_store_root / ".anvil" / "v4" / "xval_receipt.json").write_text(
                json.dumps(
                    anvil_replication_job.sign_gate_artifact(
                        cdir,
                        "xval-gate",
                        {
                            "schema": "anvil-v4-xval-receipt/v1",
                            "analysis_id": aid,
                            "scope_sha256": scope_sha,
                            "cross_family_attested": True,
                            "families": ["claude", "gemini"],
                            "verdict": "PASS",
                        },
                    )
                ),
                encoding="utf-8",
            )
            (ui_store_root / ".anvil" / "v4" / "ramanujan_verdicts.json").write_text(
                json.dumps(
                    anvil_replication_job.sign_gate_artifact(
                        cdir,
                        "ram-gate",
                        {
                            "scope_sha256": scope_sha,
                            "verdicts": {
                                "fix-ui-app-1": {"scope_sha256": scope_sha, "code_defect_confirmed": True, "verdict": "APPROVED"},
                                "fix-ui-blk-1": {"scope_sha256": scope_sha, "wrong_side": True, "target_side": "paper", "verdict": "BLOCKED", "reason": "Wrong side."},
                            },
                        },
                    )
                ),
                encoding="utf-8",
            )
            ra2_code, _ = _http_json(
                f"http://127.0.0.1:{port}/api/steward/anvil/replication",
                method="POST",
                body={
                    "action": "replication_start",
                    "analysis_id": aid,
                    "scope_sha256": scope_sha,
                    "consent_token": c_a2["consent_token"],
                    "sync": True,
                    "refactor_candidates": [
                        {
                            "id": "fix-ui-app-1",
                            "table_id": "tab:uplift",
                            "title": "Deterministic Seeded Tie-Break",
                            "where": "synth_uplift_driver.py:L17",
                            "summary": "Unseeded tie-break causes variance.",
                            "diff": seed_fix_diff,
                        },
                        {
                            "id": "fix-ui-blk-1",
                            "table_id": "tab:dag_elbo",
                            "title": "Blocked Wrong-Side Flow Rewrite",
                            "where": "synth_dag_flow.py:L3",
                            "summary": "Would break O(1) pass.",
                            "diff": "",
                        },
                    ],
                },
            )
            assert ra2_code == 200
            cb2_code, c_b2 = _http_json(
                f"http://127.0.0.1:{port}/api/steward/anvil/replication",
                method="POST",
                body={"action": "replication_consent", "analysis_id": aid, "phase": "B", "candidate_id": "fix-ui-app-1", "candidate_diff": seed_fix_diff},
            )
            assert cb2_code == 200
            rb2_code, r_b2 = _http_json(
                f"http://127.0.0.1:{port}/api/steward/anvil/replication",
                method="POST",
                body={
                    "action": "replication_phase_b",
                    "analysis_id": aid,
                    "scope_sha256": scope_sha,
                    "consent_token": c_b2["consent_token"],
                    "candidate_id": "fix-ui-app-1",
                    "candidate_diff": seed_fix_diff,
                    "sync": True,
                },
            )
            assert rb2_code == 200
            assert [fx["id"] for fx in r_b2["report"]["approved_fixes"]] == ["fix-ui-app-1"]

            # Refresh Report v2 view
            page.locator("#btnBackFromReplication").click()
            page.locator("#doneShelf [data-open-replication-id]").first.wait_for(state="visible", timeout=10000)
            page.locator("#doneShelf [data-open-replication-id]").first.click()
            page.locator("#fix-ui-app-1").wait_for(state="visible", timeout=10000)
            page.locator("#fix-ui-blk-1").wait_for(state="visible", timeout=10000)

            # Test Discrepancies filter toggle
            page.locator('[data-rep-matrix-filter="flags"]').click()
            assert page.locator('[data-rep-matrix-filter="flags"].active').count() == 1
            page.locator('[data-rep-matrix-filter="all"]').click()

            # Test inline Queue Refactoring drawer (NO window.alert()!)
            page.locator('[data-open-queue-drawer="fix-ui-app-1"]').click()
            page.locator('[data-queue-drawer="fix-ui-app-1"]').wait_for(state="visible", timeout=5000)
            page.locator('[data-queue-note-input="fix-ui-app-1"]').fill("Apply cleanly on branch")
            page.locator('[data-confirm-queue-fix="fix-ui-app-1"]').click()
            page.locator('[data-queued-badge="fix-ui-app-1"]').wait_for(state="visible", timeout=10000)
            assert alerts_seen == []

            # Test DELIVERABLES.md export button
            page.locator("#btnExportRepDeliverables").click()
            page.wait_for_function(
                "() => { const b = document.getElementById('repToastBanner'); return b && !b.hidden && b.textContent.includes('DELIVERABLES.md'); }",
                timeout=10000,
            )
            assert (cdir / "DELIVERABLES.md").is_file()
            assert (cdir / "ANVIL-REPLICATION-REPORT.md").is_file()
            assert page_errors == []
            browser.close()

        # Headless `ft.py look --check` on live `?view=replication` URL at desktop (1560x960) & phone (390x844)
        rep_live_url = f"{anvil_url}&view=replication"
        rep_check_csv = "#sec-summary,#sec-matrix,#sec-refactoring"
        for viewport_sz in ("1560x960", "390x844"):
            proc_look = subprocess.run(
                [
                    sys.executable,
                    str(FT_PY),
                    "look",
                    rep_live_url,
                    "--size",
                    viewport_sz,
                    "--wait",
                    "1400",
                    "--out",
                    str(look_out / f"report_v2_{viewport_sz}"),
                    "--check",
                    rep_check_csv,
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
            assert proc_look.returncode == 0, f"ft.py look failed at {viewport_sz}: {proc_look.stderr}\n{proc_look.stdout}"
            verdict = json.loads(proc_look.stdout)["results"][0]
            assert verdict["errors"] == [], f"Errors at {viewport_sz}: {verdict['errors']}"
            for chk in verdict["checks"][rep_check_csv]:
                assert chk["painted"] is True, f"Unpainted Report v2 selector at {viewport_sz}: {chk}"
                assert chk["coveredBy"] is None and chk["hiddenBy"] is None
    finally:
        srv.shutdown()
        srv.server_close()

    # Foundry == vendor SHA-256 parity + distro.scan_paths() + zero chrome-open in test code
    sync_chk = subprocess.run([sys.executable, str(SYNC_SCRIPT), "--check"], capture_output=True, text=True, check=False, timeout=30)
    assert sync_chk.returncode == 0, sync_chk.stdout + sync_chk.stderr

    w3_files = [
        VENDOR_ANVIL_DIR / "scripts" / "anvil_replication_audit.py",
        VENDOR_ANVIL_DIR / "scripts" / "anvil_v4_trace.py",
        VENDOR_ANVIL_DIR / "scripts" / "anvil_v4_xval.py",
        ANCHOR_ROOT / "steward_cockpit" / "anvil_replication_job.py",
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js",
        Path(__file__).resolve(),
    ]
    scan_hits = distro.scan_paths([(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in w3_files], root=ANCHOR_ROOT)
    assert scan_hits == [], f"distro.scan_paths flagged Wave 3 files: {scan_hits}"
