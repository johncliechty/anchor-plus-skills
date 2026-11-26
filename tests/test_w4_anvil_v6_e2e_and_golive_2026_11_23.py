"""Wave 4 Hermetic End-to-End Verification, Upgrade CLI, Reload/Latency & Distro Canary Suite (`2026-11-23`).

Covers every Wave 4 obligation hermetically (`tmp_path` + `--anchor-root <tmp_path>`, zero hardcoded user
or private repository paths):
  1. `upgrade_cockpits_anvil_v6.py` durability, repeat-invocation idempotence, 2-process concurrency under
     `exclusive_file_lock`, numeric bounds (`MAX_UPGRADE_MANIFEST_BYTES`, `MAX_BACKUP_FILES`), containment
     escape refusal (`..`, external absolute path, symlink/junction), `n-1` `xval`/`trace` receipt preservation,
     0-byte research-repo SHA-256 diff, and byte-exact `--restore` rollback.
  2. Full Playwright E2E walkthrough at desktop (`1560x960`) and phone (`390x844`) + headless `ft.py look --check`
     across Scoping v2 -> 3-Layer Workbench -> Report v2 (`not yet run` before execution, `0` mockup sample
     literals, `0` unapproved refactorings) -> consented Phase A scratch replication transitioning to `OBSERVED`.
  3. Reload coherence (`steward_routes` + `anvil_session` + `anvil_replication_job` mtime reload without splitting
     `AnvilAnalysisRefusalError`), `anvil.html` de-bloating (`< 4,650` lines) + `?v=` SHA-256 asset stamps on
     `anvil_v6.css` / `anvil_v6.js`, and `< 15 ms` median warm `get_v4_cockpit_state` + `check_locked_scope_drift`.
  4. Unmodified `distro.py`, clean `distro.scan_paths()` + `distro.scan_import_closure()` on shipped manifest paths,
     planted secret / Windows user-path / third-party-import scanner canaries, stubbed `anchor_healthcheck`
     `check_rnd_v2..v5_surface` checks, and `sync_anvil_vendor.py --check` SHA-256 parity with zero `__pycache__`.
"""
from __future__ import annotations

import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

import anchor_healthcheck
import distro
from steward_cockpit import anvil_replication_job, anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
FOUNDRY_ANVIL_DIR = ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil"
VENDOR_ANVIL_DIR = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
PLAN_DIR = ANCHOR_ROOT / "planning" / "2026-11-23-anvil-scoping-and-comprehension"
SCRIPTS_DIR = PLAN_DIR / "scripts"
UPGRADE_SCRIPT = SCRIPTS_DIR / "upgrade_cockpits_anvil_v6.py"
SYNC_SCRIPT = SCRIPTS_DIR / "sync_anvil_vendor.py"
FT_SCRIPT = ANCHOR_ROOT.parent / "foundry-tools" / "ft.py"


def _load_upgrade_mod() -> Any:
    spec = importlib.util.spec_from_file_location("upgrade_cockpits_anvil_v6", UPGRADE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_upgrade_cli(*args: str, env_extra: Dict[str, str] | None = None) -> Tuple[int, Dict[str, Any], str]:
    env = dict(os.environ)
    env.pop("ANCHOR_ANVIL_V6", None)
    env.pop("ANCHOR_ANVIL_MULTI", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-B", str(UPGRADE_SCRIPT), *args],
        cwd=str(ANCHOR_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    parsed = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    return proc.returncode, parsed, proc.stderr


def _build_hermetic_v6_workspace(base_dir: Path) -> Dict[str, Path]:
    """Create a 100% synthetic two-project workspace (`moe_paper1`, `hnf_paper1`, `hnf_outer`) under `base_dir`."""
    ws = base_dir / "workspace"
    anchor_root = ws / "Anchor"
    anchor_root.mkdir(parents=True)

    # 1. Synthetic discrete-choice estimator cockpit (`Paper 1` -> `synth_choice_pkg`)
    moe_proj = ws / "Synthetic_Choice_Project"
    moe_paper1 = moe_proj / "Paper 1"
    moe_repo = moe_paper1 / "synth_choice_pkg"
    (moe_repo / "Code").mkdir(parents=True)
    (moe_repo / "Data").mkdir(parents=True)
    (moe_repo / "Manuscript").mkdir(parents=True)
    (moe_paper1 / "ECGBERHT.md").write_text("# Synthetic Choice Paper 1\n", encoding="utf-8")

    (moe_repo / "Data" / "panel_obs.csv").write_text("id,y,x\n1,1,0.5\n2,0,-0.4\n3,1,1.1\n4,0,-0.8\n", encoding="utf-8")
    (moe_repo / "workflow.sh").write_text(
        "#!/usr/bin/env bash\n# Step 1: Table 1 (tab:emp_fit)\npython Code/run_table1.py\n",
        encoding="utf-8",
    )
    (moe_repo / "Code" / "estimator_core.py").write_text(
        textwrap.dedent(
            """\
            import math

            def compute_mixture_loglik(xs, ys, beta=1.25):
                total = 0.0
                for x, y in zip(xs, ys):
                    p = 1.0 / (1.0 + math.exp(-beta * x))
                    total += y * math.log(max(p, 1e-9)) + (1.0 - y) * math.log(max(1.0 - p, 1e-9))
                return round(total, 4)

            def unused_legacy_helper(z):
                return z * 99.0
            """
        ),
        encoding="utf-8",
    )
    (moe_repo / "Code" / "run_table1.py").write_text(
        textwrap.dedent(
            """\
            import csv
            import json
            from pathlib import Path
            from estimator_core import compute_mixture_loglik

            def replicate_table_1():
                data_p = Path(__file__).resolve().parent.parent / "Data" / "panel_obs.csv"
                xs, ys = [], []
                with data_p.open("r", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        xs.append(float(row["x"]))
                        ys.append(float(row["y"]))
                ll = compute_mixture_loglik(xs, ys, beta=1.25)
                out = {"observations": float(len(xs)), "loglik": ll}
                print("ANVIL_METRICS_JSON:" + json.dumps({"metrics": out}))
                return out

            if __name__ == "__main__":
                replicate_table_1()
            """
        ),
        encoding="utf-8",
    )
    # Compute exact loglik (-1.4415) so Phase A table replication matches 2/2 published cells cleanly
    moe_tex = moe_repo / "Manuscript" / "Main.tex"
    moe_tex.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Synthetic Mixture Choice Benchmark}
            \begin{document}
            \section{Model}
            \begin{equation}\label{eq:loglik}
            \ell(\beta) = \sum_{i=1}^{N} y_i \log \sigma(\beta x_i) + (1 - y_i)\log(1 - \sigma(\beta x_i))
            \end{equation}
            \section{Empirical Results}
            \begin{table}[h]
            \caption{Primary Mixture Fit}
            \label{tab:emp_fit}
            \begin{tabular}{lr}
            Metric & Estimate \\
            Observations & 4 \\
            LogLik & -1.4415 \\
            \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    # Seed legacy `.anvil/session.json` + validated `xval_receipt.json` & `last_trace.json` (`n-1` receipts)
    (moe_paper1 / ".anvil" / "v4").mkdir(parents=True)
    (moe_paper1 / ".anvil" / "session.json").write_text(
        json.dumps(
            {
                "schema": "anvil-cockpit-session/v2",
                "active": True,
                "mode": "paper",
                "cockpit_name": "Synthetic Choice Paper 1",
                "software_spec": "synth_choice_pkg",
                "paper_spec": "synth_choice_pkg/Manuscript/Main.tex",
                "software": {"spec": "synth_choice_pkg", "label": "synth_choice_pkg"},
                "paper": {"spec": "synth_choice_pkg/Manuscript/Main.tex"},
                "code_map": {"conceptual_buckets": []},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    moe_xval_doc = {
        "schema": "anvil-v4-xval-receipt/v1",
        "mode": "CROSS_FAMILY_2_SEAT",
        "verdict": "PASS",
        "verdict_qualified": "PASS_ATTESTED",
        "cross_family_attested": True,
        "orchestrator_family": "claude",
        "validator_family": "gemini",
        "digest_bytes": 512,
        "digest_sha256": "a1b2c3d4" * 8,
        "findings": [],
    }
    moe_trace_doc = {
        "schema": "anvil-v4-trace/v1",
        "ok": True,
        "exit_code": 0,
        "isolation_boundary": "consented_local_subprocess",
        "argv": ["python", "Code/run_table1.py"],
        "executed_lines": [{"file": "Code/run_table1.py", "line": 14, "hits": 4}],
        "stage_hits": {"S1": 4},
        "tripwires": [],
    }
    (moe_paper1 / ".anvil" / "v4" / "xval_receipt.json").write_text(
        json.dumps(moe_xval_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (moe_paper1 / ".anvil" / "v4" / "last_trace.json").write_text(
        json.dumps(moe_trace_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # 2. Synthetic normalizing-flow multi-repo project (`Paper 1` inner + `hnf_outer` outer)
    hnf_outer = ws / "Synthetic_Flow_Project"
    hnf_paper1 = hnf_outer / "Paper 1"
    hnf_sw = hnf_paper1 / "sources" / "synth_flow_repo"
    hnf_bayes = hnf_paper1 / "sources" / "Bayesian"
    hnf_overleaf = hnf_paper1 / "sources" / "current-overleaf"
    (hnf_sw / "Code").mkdir(parents=True)
    (hnf_bayes / "Code").mkdir(parents=True)
    hnf_overleaf.mkdir(parents=True)
    (hnf_paper1 / "ECGBERHT.md").write_text("# Synthetic Flow Paper 1\n", encoding="utf-8")

    (hnf_sw / "workflow.sh").write_text(
        "#!/usr/bin/env bash\n# Step 1: Flow Table (tab:flow_bench)\npython Code/run_flow_bench.py\n",
        encoding="utf-8",
    )
    (hnf_sw / "Code" / "dag_conditioner.py").write_text(
        "def sparse_jacobian_det(diag_vals):\n    prod = 1.0\n    for v in diag_vals:\n        prod *= v\n    return round(prod, 4)\n",
        encoding="utf-8",
    )
    (hnf_sw / "Code" / "run_flow_bench.py").write_text(
        "import json\nfrom dag_conditioner import sparse_jacobian_det\nif __name__ == '__main__':\n    print(json.dumps({'tab:flow_bench': {'JacobianDet': sparse_jacobian_det([1.2, 1.5])}}))\n",
        encoding="utf-8",
    )
    (hnf_bayes / "Code" / "prior_mcmc.py").write_text(
        "def log_slab_prior(w):\n    return -0.5 * (w ** 2)\n",
        encoding="utf-8",
    )
    hnf_tex = hnf_overleaf / "Main.tex"
    hnf_tex.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Synthetic DAG Flow Study}
            \begin{document}
            \section{Architecture}
            \begin{equation}\label{eq:jac}
            J(z) = \prod_{k=1}^{K} d_k
            \end{equation}
            \begin{table}[h]
            \caption{Flow Benchmark}
            \label{tab:flow_bench}
            \begin{tabular}{lr}
            Metric & Value \\
            JacobianDet & 1.8 \\
            \end{tabular}
            \end{table}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    # Seed inner `hnf_paper1` multi-slot `.anvil` + receipts
    (hnf_paper1 / ".anvil" / "v4").mkdir(parents=True)
    (hnf_paper1 / ".anvil" / "analyses" / "pkg-bayesian" / ".anvil" / "v4").mkdir(parents=True)
    (hnf_paper1 / ".anvil" / "session.json").write_text(
        json.dumps(
            {
                "schema": "anvil-cockpit-session/v2",
                "active": True,
                "mode": "paper",
                "cockpit_name": "Synthetic Flow Paper 1",
                "software_spec": "sources/synth_flow_repo",
                "paper_spec": "sources/current-overleaf/Main.tex",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (hnf_paper1 / ".anvil" / "analyses" / "pkg-bayesian" / ".anvil" / "session.json").write_text(
        json.dumps(
            {
                "schema": "anvil-cockpit-session/v2",
                "active": True,
                "mode": "paper",
                "cockpit_name": "Bayesian Sub-Package",
                "software_spec": "sources/Bayesian",
                "paper_spec": "sources/current-overleaf/Main.tex",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (hnf_paper1 / ".anvil" / "analyses" / "index.json").write_text(
        json.dumps(
            {
                "schema": "anvil-analyses-index/v1",
                "active_analysis_id": "legacy-primary",
                "analyses": [
                    {
                        "analysis_id": "legacy-primary",
                        "title": "Primary DAG Flow Scope",
                        "store": ".",
                        "mode": "paper",
                        "software_spec": "sources/synth_flow_repo",
                        "paper_spec": "sources/current-overleaf/Main.tex",
                        "archived": False,
                    },
                    {
                        "analysis_id": "pkg-bayesian",
                        "title": "Bayesian Prior Sub-Package",
                        "store": "analyses/pkg-bayesian",
                        "mode": "paper",
                        "software_spec": "sources/Bayesian",
                        "paper_spec": "sources/current-overleaf/Main.tex",
                        "archived": False,
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (hnf_paper1 / ".anvil" / "v4" / "xval_receipt.json").write_text(
        json.dumps(moe_xval_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (hnf_paper1 / ".anvil" / "analyses" / "pkg-bayesian" / ".anvil" / "v4" / "xval_receipt.json").write_text(
        json.dumps(moe_xval_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Seed outer `hnf_outer` static scope + receipts
    (hnf_outer / ".anvil" / "v4").mkdir(parents=True)
    (hnf_outer / ".anvil" / "session.json").write_text(
        json.dumps(
            {
                "schema": "anvil-cockpit-session/v2",
                "active": True,
                "mode": "paper",
                "cockpit_name": "Synthetic Flow Outer",
                "software_spec": "Paper 1/sources/synth_flow_repo",
                "paper_spec": "Paper 1/sources/current-overleaf/Main.tex",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (hnf_outer / ".anvil" / "v4" / "xval_receipt.json").write_text(
        json.dumps(moe_xval_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Register both projects in `<anchor_root>/rnd_projects.json`
    (anchor_root / "rnd_projects.json").write_text(
        json.dumps(
            {
                "projects": [
                    {"id": "proj_synth_choice", "name": "Synthetic Choice Project", "folder_path": str(moe_proj), "status": "active"},
                    {"id": "proj_synth_flow", "name": "Synthetic Flow Project", "folder_path": str(hnf_outer), "status": "active"},
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "ws": ws,
        "anchor_root": anchor_root,
        "moe_paper1": moe_paper1,
        "hnf_paper1": hnf_paper1,
        "hnf_outer": hnf_outer,
    }


def _start_ephemeral_w4_server(cockpit_dir: Path) -> Tuple[ThreadingHTTPServer, int]:
    cdir_str = str(cockpit_dir.resolve())
    brand_dir = (ANCHOR_ROOT / "vendor" / "brand").resolve()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(code))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/steward-static/"):
                rel = path[len("/steward-static/"):]
                data, ctype = steward_routes.serve_static(rel)
                if data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith("/vendor/brand/"):
                clean_rel = path[len("/vendor/brand/"):].lstrip("/")
                cand = (brand_dir / clean_rel).resolve()
                if not cand.is_relative_to(brand_dir) or not cand.is_file():
                    self.send_error(404)
                    return
                raw_b = cand.read_bytes()
                ctype_b, _ = mimetypes.guess_type(cand.name)
                self.send_response(200)
                self.send_header("Content-Type", ctype_b or "image/jpeg")
                self.send_header("Content-Length", str(len(raw_b)))
                self.end_headers()
                self.wfile.write(raw_b)
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
            path = parsed.path
            if not path.startswith("/api/steward/"):
                self.send_error(404)
                return
            verb = path[len("/api/steward/"):]
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            body_obj = json.loads(raw_body.decode("utf-8"))
            out = steward_routes.handle_post(cdir_str, verb, body_obj)
            resp_obj, status_code = out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            self._send_json(status_code, resp_obj)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, free_port = sock.getsockname()
    sock.close()
    assert free_port != 8777
    srv = ThreadingHTTPServer(("127.0.0.1", free_port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, free_port


def test_w4_upgrade_cli_durability_idempotence_concurrency_bounds_containment_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `--backup --apply --enable --verify` twice, 2-process concurrency, numeric bounds,
    containment escape refusal (`..`, external path, symlink/junction), `n-1` receipt preservation,
    0-byte research-repo diff, and `--restore` byte-exact rollback.
    """
    monkeypatch.delenv("ANCHOR_ANVIL_V6", raising=False)
    monkeypatch.delenv("ANCHOR_ANVIL_MULTI", raising=False)
    mod = _load_upgrade_mod()
    layout = _build_hermetic_v6_workspace(tmp_path)
    anchor_root = layout["anchor_root"]
    moe_p1 = layout["moe_paper1"]
    hnf_p1 = layout["hnf_paper1"]
    hnf_out = layout["hnf_outer"]

    assert anvil_session.is_anvil_v6_enabled(anchor_root=anchor_root) is False

    # Capture pre-upgrade SHA-256 baselines for `.anvil` files & research trees
    pre_xval_bytes = (moe_p1 / ".anvil" / "v4" / "xval_receipt.json").read_bytes()
    pre_trace_bytes = (moe_p1 / ".anvil" / "v4" / "last_trace.json").read_bytes()
    pre_moe_sess_sha = hashlib.sha256((moe_p1 / ".anvil" / "session.json").read_bytes()).hexdigest()
    pre_src_snaps = {
        k: mod.snapshot_research_tree_sha256(layout[k])
        for k in ("moe_paper1", "hnf_paper1", "hnf_outer")
    }

    # 1. First `--backup --apply --enable --verify` run
    rc1, out1, err1 = _run_upgrade_cli("--anchor-root", str(anchor_root), "--backup", "--apply", "--enable", "--verify")
    assert rc1 == 0, f"Run 1 failed: {out1}\n{err1}"
    assert out1["ok"] is True
    assert out1["steps"]["backup"]["mode"] == "created"
    assert out1["steps"]["apply"]["cockpit_count"] == 3
    assert out1["steps"]["verify"]["anvil_v6_enabled"] is True
    assert anvil_session.is_anvil_v6_enabled(anchor_root=anchor_root) is True

    # Preserved `n-1` receipts are byte-identical
    assert (moe_p1 / ".anvil" / "v4" / "xval_receipt.json").read_bytes() == pre_xval_bytes
    assert (moe_p1 / ".anvil" / "v4" / "last_trace.json").read_bytes() == pre_trace_bytes

    # 2. Second `--backup --apply --enable --verify` run (repeat-invocation idempotence)
    rc2, out2, err2 = _run_upgrade_cli("--anchor-root", str(anchor_root), "--backup", "--apply", "--enable", "--verify")
    assert rc2 == 0, f"Run 2 failed: {out2}\n{err2}"
    assert out2["steps"]["backup"]["mode"] == "verified_existing"
    slots_r1 = {c["cockpit_dir"]: [(s["analysis_id"], s["scope_sha256"]) for s in c["slots"]] for c in out1["steps"]["apply"]["cockpits"]}
    slots_r2 = {c["cockpit_dir"]: [(s["analysis_id"], s["scope_sha256"]) for s in c["slots"]] for c in out2["steps"]["apply"]["cockpits"]}
    assert slots_r1 == slots_r2
    for c_row in out2["steps"]["apply"]["cockpits"]:
        assert all(s["mode"] == "idempotent_reuse" for s in c_row["slots"])

    # 3. Concurrency test: two real `subprocess.Popen` processes running `--apply --enable` concurrently
    env_conc = dict(os.environ)
    env_conc.pop("ANCHOR_ANVIL_V6", None)
    env_conc["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd_conc = [sys.executable, "-B", str(UPGRADE_SCRIPT), "--anchor-root", str(anchor_root), "--apply", "--enable"]
    p_a = subprocess.Popen(cmd_conc, cwd=str(ANCHOR_ROOT), env=env_conc, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p_b = subprocess.Popen(cmd_conc, cwd=str(ANCHOR_ROOT), env=env_conc, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out_a_s, err_a_s = p_a.communicate(timeout=120)
    out_b_s, err_b_s = p_b.communicate(timeout=120)
    assert p_a.returncode == 0, f"Concurrent proc A failed: {out_a_s}\n{err_a_s}"
    assert p_b.returncode == 0, f"Concurrent proc B failed: {out_b_s}\n{err_b_s}"
    assert json.loads(out_a_s)["ok"] is True and json.loads(out_b_s)["ok"] is True
    for cp in (moe_p1, hnf_p1, hnf_out):
        for jf in (cp / ".anvil").rglob("*.json"):
            parsed_jf = json.loads(jf.read_text(encoding="utf-8"))
            assert isinstance(parsed_jf, dict)
    assert (moe_p1 / ".anvil" / "v4" / "xval_receipt.json").read_bytes() == pre_xval_bytes

    # 4. Numeric bound refusal tests (`MAX_UPGRADE_MANIFEST_BYTES` and `MAX_BACKUP_FILES`)
    bound_layout = _build_hermetic_v6_workspace(tmp_path / "bounds_case")
    bound_anchor = bound_layout["anchor_root"]
    rc_fcap, out_fcap, _ = _run_upgrade_cli(
        "--anchor-root", str(bound_anchor), "--backup", "--backup-id", "fcap", "--max-backup-files", "2"
    )
    assert rc_fcap == 2 and out_fcap["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    assert out_fcap["bound_name"] == "MAX_BACKUP_FILES"

    # Trigger real 16 MiB `MAX_UPGRADE_MANIFEST_BYTES` cap without any CLI cap override
    (bound_layout["moe_paper1"] / ".anvil" / "oversized_state.bin").write_bytes(b"Z" * (mod.MAX_UPGRADE_MANIFEST_BYTES + 4096))
    rc_bcap, out_bcap, _ = _run_upgrade_cli("--anchor-root", str(bound_anchor), "--backup", "--backup-id", "bcap")
    assert rc_bcap == 2 and out_bcap["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    assert out_bcap["bound_name"] == "MAX_UPGRADE_MANIFEST_BYTES"

    # 5. Containment escape-attempt tests (`..`, external absolute path, and symlink/junction)
    rc_dot, out_dot, _ = _run_upgrade_cli(
        "--anchor-root", str(anchor_root), "--cockpit", str(anchor_root) + os.sep + ".." + os.sep + "..", "--backup"
    )
    assert rc_dot == 2 and out_dot["error_code"] == "PATH_ESCAPE_REFUSED"

    outside_dir = tmp_path / "external_escape_cockpit"
    (outside_dir / ".anvil").mkdir(parents=True)
    (outside_dir / ".anvil" / "session.json").write_text('{"active": true}', encoding="utf-8")
    rc_ext, out_ext, _ = _run_upgrade_cli("--anchor-root", str(anchor_root), "--cockpit", str(outside_dir), "--apply")
    assert rc_ext == 2 and out_ext["error_code"] == "PATH_ESCAPE_REFUSED"

    junc_dir = layout["ws"] / "Junction_Escape_Cockpit"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junc_dir), str(outside_dir)], check=True, capture_output=True)
    else:
        os.symlink(str(outside_dir), str(junc_dir), target_is_directory=True)
    rc_lnk, out_lnk, _ = _run_upgrade_cli("--anchor-root", str(anchor_root), "--cockpit", str(junc_dir), "--apply")
    assert rc_lnk == 2 and out_lnk["error_code"] == "PATH_ESCAPE_REFUSED"
    if os.name == "nt":
        os.rmdir(str(junc_dir))
    else:
        junc_dir.unlink()

    # 6. `--restore` rolls back cleanly to pre-upgrade state (`is_anvil_v6_enabled == False`, exact `.anvil` bytes)
    rc_rst, out_rst, err_rst = _run_upgrade_cli("--anchor-root", str(anchor_root), "--restore")
    assert rc_rst == 0, f"Restore failed: {out_rst}\n{err_rst}"
    assert out_rst["steps"]["restore"]["anvil_v6_enabled"] is False
    assert anvil_session.is_anvil_v6_enabled(anchor_root=anchor_root) is False
    assert not (anchor_root / ".anchor" / "anvil-v6-enabled.json").exists()
    assert not (moe_p1 / ".anvil" / "scope_manifest.json").exists()
    assert not (moe_p1 / ".anvil" / "scoping_v2_state.json").exists()
    assert hashlib.sha256((moe_p1 / ".anvil" / "session.json").read_bytes()).hexdigest() == pre_moe_sess_sha
    assert (moe_p1 / ".anvil" / "v4" / "xval_receipt.json").read_bytes() == pre_xval_bytes
    assert (moe_p1 / ".anvil" / "v4" / "last_trace.json").read_bytes() == pre_trace_bytes

    for k in ("moe_paper1", "hnf_paper1", "hnf_outer"):
        assert mod.diff_sha256_maps(pre_src_snaps[k], mod.snapshot_research_tree_sha256(layout[k])) == []


def test_w4_playwright_e2e_desktop_mobile_and_look_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walk upgraded `tmp_path` cockpit end-to-end in Playwright (`1560x960` desktop + `390x844` mobile)
    with headless `ft.py look --check`, verifying Scoping v2 -> 3-Layer Workbench -> Report v2 (`not yet run`,
    0 mockup literals, 0 unapproved refactorings) -> consented Phase A scratch replication -> `OBSERVED`.
    """
    pw = pytest.importorskip("playwright.sync_api")
    mod = _load_upgrade_mod()
    layout = _build_hermetic_v6_workspace(tmp_path)
    anchor_root = layout["anchor_root"]
    moe_p1 = layout["moe_paper1"]

    rc, out, err = _run_upgrade_cli("--anchor-root", str(anchor_root), "--backup", "--apply", "--enable", "--verify")
    assert rc == 0, f"Upgrade failed before E2E: {out}\n{err}"

    monkeypatch.delenv("ANCHOR_ANVIL_V6", raising=False)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(anchor_root))
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        tuple(dict.fromkeys([*anvil_session.ALLOWED_LOCAL_ROOTS, layout["ws"].resolve(), anchor_root.resolve()])),
    )

    pre_src = mod.snapshot_research_tree_sha256(moe_p1)
    srv, port = _start_ephemeral_w4_server(moe_p1)
    base_url = f"http://127.0.0.1:{port}/steward-static/anvil.html?pid=synth_choice_w4&name=SynthChoicePaper1"
    rep_url = base_url + "&view=replication"

    try:
        with pw.sync_playwright() as p:
            for width, height in ((1560, 960), (390, 844)):
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": height})
                page_errors: list[str] = []
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))

                # Boot lands directly on 3-Layer Workbench for upgraded active scope
                page.goto(base_url, wait_until="networkidle")
                page.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=15000)
                assert page.locator("#anvil-layer2-replicators").is_visible()
                assert page.locator("details#anvil-layer3-plumbing").evaluate("el => el.open === false")

                # Open Scoping v2 (`⚙ Edit Scope`) and verify Saved-Scopes Shelf + Map + Dialogue + 64-hex Receipt + Icons
                page.locator("#btnOpenLauncherDrawer").click()
                page.locator("#anvilScopingV2Root").wait_for(state="visible", timeout=10000)
                for sel in ("#doneShelf", "#mainStage", "#softwareMapScroll", "#convScroll", "#receiptCol"):
                    assert page.locator(sel).is_visible(), f"Missing {sel} at {width}x{height}"
                assert "Open Anvil Map →" in page.locator("#doneShelf").inner_text()
                assert "Replication & Ramanujan Report" in page.locator("#doneShelf").inner_text()
                sha_txt = page.locator("#receiptSha256").inner_text().strip()
                assert re.fullmatch(r"[0-9a-f]{64}", sha_txt)
                icons_ok = page.evaluate(
                    "() => Array.from(document.querySelectorAll('#anvilScopingV2Root img')).every(i => i.complete && i.naturalWidth > 0)"
                )
                assert icons_ok is True

                # Click `Open Anvil Map →` from Saved-Scopes Shelf to return to 3-Layer Workbench
                page.locator("[data-open-scope-id]").first.click()
                page.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=10000)

                # Open Report v2 (`Replication & Ramanujan Report →`) and verify honest `not yet run` before execution
                page.locator("#btnOpenReplicationReport").click()
                page.locator("#sec-summary").wait_for(state="visible", timeout=10000)
                assert page.locator("#sec-matrix").is_visible()
                assert page.locator("#sec-refactoring").is_visible()
                rep_text_low = page.locator("#anvilReplicationV2Root").inner_text().lower()
                assert "not yet run" in rep_text_low
                for bad_lit in mod.MOCKUP_SAMPLE_LITERALS:
                    assert bad_lit not in rep_text_low
                assert page.locator("#sec-refactoring .queue-btn").count() == 0

                if width == 390:
                    # Consented Phase A scratch replication transitions `not yet run` -> receipt-backed `OBSERVED`
                    page.locator('[data-open-rep-consent="A"]').first.click()
                    page.locator("#replication-consent-modal").wait_for(state="visible", timeout=10000)
                    assert page.locator("#repConsentSha").inner_text().strip() == sha_txt
                    page.locator("#btnConfirmReplicationConsent").click()
                    page.wait_for_function(
                        "() => document.querySelector('#sec-matrix') && document.querySelector('#sec-matrix').innerText.includes('OBSERVED')",
                        timeout=25000,
                    )
                    post_run_matrix = page.locator("#sec-matrix").inner_text()
                    assert "OBSERVED" in post_run_matrix
                    assert "run_table1.py" in post_run_matrix

                assert page_errors == [], f"Uncaught JS errors at {width}x{height}: {page_errors}"
                browser.close()

        # Headless `ft.py look --check` verdicts at desktop (`1560x960`) and phone (`390x844`)
        wb_checks = "#anvil-layer1-estimator,#anvil-layer2-replicators,#anvil-layer3-plumbing"
        rep_checks = "#sec-summary,#sec-matrix,#sec-refactoring"
        for idx, (url_t, chk_csv, vp) in enumerate(
            (
                (base_url, wb_checks, "1560x960"),
                (base_url, wb_checks, "390x844"),
                (rep_url, rep_checks, "1560x960"),
                (rep_url, rep_checks, "390x844"),
            )
        ):
            look_out = tmp_path / f"look_w4_{idx}"
            proc_look = subprocess.run(
                [
                    sys.executable,
                    str(FT_SCRIPT),
                    "look",
                    url_t,
                    "--size",
                    vp,
                    "--wait",
                    "1400",
                    "--out",
                    str(look_out),
                    "--check",
                    chk_csv,
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
            assert proc_look.returncode == 0, f"ft.py look failed ({vp}): {proc_look.stderr}\n{proc_look.stdout}"
            verdict = json.loads(proc_look.stdout)["results"][0]
            assert verdict["errors"] == []
            for c_row in verdict["checks"][chk_csv]:
                assert c_row["painted"] is True and c_row["coveredBy"] is None and c_row["hiddenBy"] is None
    finally:
        srv.shutdown()
        srv.server_close()

    assert mod.diff_sha256_maps(pre_src, mod.snapshot_research_tree_sha256(moe_p1)) == []


def test_w4_debloat_asset_stamps_hot_reload_and_sub15ms_warm_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `anvil.html` < 4,650 lines, `?v=` SHA-256 stamps on `anvil_v6.css`/`anvil_v6.js`,
    `importlib.reload` coherence across `steward_routes` + `anvil_session` + `anvil_replication_job`,
    and warm `get_v4_cockpit_state` + `check_locked_scope_drift` median latency < 15 ms.
    """
    anvil_html_p = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html"
    anvil_v6_css_p = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil_v6.css"
    anvil_v6_js_p = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil_v6.js"
    anvil_wb_css_p = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil_workbench.css"
    anvil_wb_js_p = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil_workbench.js"

    html_lines = anvil_html_p.read_text(encoding="utf-8").splitlines()
    assert len(html_lines) < 600, f"Expected pure-shell anvil.html < 600 lines, got {len(html_lines)}"
    assert anvil_v6_css_p.is_file() and anvil_v6_js_p.is_file()
    assert anvil_wb_css_p.is_file() and anvil_wb_js_p.is_file()
    for asset_p in (anvil_html_p, anvil_v6_css_p, anvil_v6_js_p, anvil_wb_css_p, anvil_wb_js_p):
        txt = asset_p.read_text(encoding="utf-8")
        assert ("set" + "Interval") not in txt

    # Verify `?v=<12-hex>` SHA-256 stamps via `steward_routes.serve_static("anvil.html")`
    served_bytes, ctype = steward_routes.serve_static("anvil.html")
    assert served_bytes is not None and ctype == "text/html; charset=utf-8"
    served_html = served_bytes.decode("utf-8")
    for asset_name in ("anvil.js", "anvil_v6.css", "anvil_v6.js", "anvil_workbench.css", "anvil_workbench.js"):
        m = re.search(rf'/steward-static/{re.escape(asset_name)}\?v=([0-9a-f]{{12}})"', served_html)
        assert m is not None, f"Missing ?v= 12-hex stamp on {asset_name}"
        exp_sha12 = hashlib.sha256((ANCHOR_ROOT / "steward_cockpit" / "static" / asset_name).read_bytes()).hexdigest()[:12]
        assert m.group(1) == exp_sha12

    # Verify hot-reload registration & `importlib.reload` exception-identity coherence
    sr_src = (ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
    assert '"steward_cockpit.anvil_replication_job"' in sr_src
    assert '"steward_cockpit.anvil_scoping_v6"' in sr_src
    assert "anvil_replication_audit" in anvil_session._V4_MODULE_NAMES

    layout = _build_hermetic_v6_workspace(tmp_path)
    anchor_root = layout["anchor_root"]
    moe_p1 = layout["moe_paper1"]
    rc, _, err = _run_upgrade_cli("--anchor-root", str(anchor_root), "--backup", "--apply", "--enable")
    assert rc == 0, err

    monkeypatch.delenv("ANCHOR_ANVIL_V6", raising=False)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(anchor_root))
    monkeypatch.setattr(anvil_session, "_LOADED_MTIME_NS", -1)
    monkeypatch.setattr(anvil_replication_job, "_LOADED_MTIME_NS", -1)

    # Trigger coordinated reload via `steward_routes.handle_get` and verify `AnvilAnalysisRefusalError` catch coherence
    importlib.reload(anvil_session)
    anvil_session.ALLOWED_LOCAL_ROOTS = tuple(
        dict.fromkeys([*anvil_session.ALLOWED_LOCAL_ROOTS, layout["ws"].resolve(), anchor_root.resolve()])
    )
    escape_resp, escape_code = steward_routes.handle_get(
        str(moe_p1), "anvil/replication", {"analysis_id": "../bad_escape"}
    )
    assert escape_code in (400, 403)
    assert escape_resp["ok"] is False
    assert getattr(anvil_replication_job, "_LOADED_MTIME_NS", None) is not None

    # Benchmark warm `get_v4_cockpit_state` + `check_locked_scope_drift` < 15 ms median
    v4_proc = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]
    _ = anvil_session.get_v4_cockpit_state(moe_p1, anchor_root=anchor_root)
    _ = anvil_session.check_locked_scope_drift(moe_p1, moe_p1, v4_proc)

    samples_ms: list[float] = []
    for _ in range(15):
        t0 = time.perf_counter()
        st_payload, st_code = anvil_session.get_v4_cockpit_state(moe_p1, anchor_root=anchor_root)
        drift_res = anvil_session.check_locked_scope_drift(moe_p1, moe_p1, v4_proc)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert st_code == 200 and st_payload["ok"] is True
        assert drift_res is not None and drift_res["drifted"] is False
        samples_ms.append(elapsed_ms)

    median_ms = statistics.median(samples_ms)
    assert median_ms < 15.0, f"Warm get_v4_cockpit_state + check_locked_scope_drift median {median_ms:.2f} ms >= 15 ms"


def test_w4_distro_manifest_scanner_canary_healthcheck_and_vendor_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `distro.py` is untouched, shipped manifest passes `scan_paths` + `scan_import_closure` with `[]`,
    planted secret / user-path / third-party-import canaries are caught, `anchor_healthcheck` R&D v2..v5
    surfaces pass hermetically, and `sync_anvil_vendor.py --check` holds with zero `__pycache__`.
    """
    # 1. `distro.py` untouched vs HEAD
    git_diff_distro = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "distro.py"],
        cwd=str(ANCHOR_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert git_diff_distro.stdout.strip() == "", f"distro.py must remain unmodified: {git_diff_distro.stdout}"

    # 2. Manifest inclusion/exclusion & clean scan over shipped files
    shipped = set(distro.select_shippable(root=ANCHOR_ROOT))
    for req_ship in (
        "steward_cockpit/anvil_replication_job.py",
        "steward_cockpit/anvil_scoping_v6.py",
        "steward_cockpit/static/anvil_v6.css",
        "steward_cockpit/static/anvil_v6.js",
        "steward_cockpit/static/anvil_workbench.css",
        "steward_cockpit/static/anvil_workbench.js",
        "vendor/bundled-skills/anvil/scripts/anvil_replication_audit.py",
        "tests/test_w4_anvil_v6_e2e_and_golive_2026_11_23.py",
    ):
        assert req_ship in shipped, f"Expected {req_ship} in dist_manifest.txt selection"

    for denied_rel in (
        "planning/2026-11-23-anvil-scoping-and-comprehension/scripts/upgrade_cockpits_anvil_v6.py",
        "planning/2026-11-23-anvil-scoping-and-comprehension/scripts/anvil-v6-gate.mjs",
        "steward_cockpit/static/cave-processing-and-provider-detail-mockup.html",
        "steward_cockpit/static/cockpit-wave-map-and-deliverables-mockup.html",
    ):
        assert denied_rel not in shipped, f"Local-only/untracked file {denied_rel} leaked into dist_manifest.txt"

    shipped_pairs = [(rel, ANCHOR_ROOT / rel) for rel in sorted(shipped)]
    assert distro.scan_paths(shipped_pairs, root=ANCHOR_ROOT) == []
    assert distro.scan_import_closure(shipped_pairs, root=ANCHOR_ROOT) == []

    # 3. Planted scanner canary verification in `tmp_path` (constructed dynamically so this test file stays 0-hit!)
    canary_root = tmp_path / "canary_pkg"
    canary_root.mkdir()
    secret_file = canary_root / "leak_secret.py"
    secret_val = "sk-" + "ant-api03-" + ("A" * 36)
    key_lhs = "API_" + "KEY"
    secret_file.write_text(f'{key_lhs} = "{secret_val}"\n', encoding="utf-8")

    path_file = canary_root / "leak_userpath.py"
    win_user_path = "C:" + "\\Users\\" + "canary_acct\\private_notes.txt"
    path_file.write_text(f'LEAKED_PATH = r"{win_user_path}"\n', encoding="utf-8")

    import_file = canary_root / "leak_import.py"
    import_file.write_text(("import " + "requests\n") + ("import " + "playwright\n"), encoding="utf-8")

    hits_secret = distro.scan_paths([("leak_secret.py", secret_file)], root=canary_root)
    hits_userpath = distro.scan_paths([("leak_userpath.py", path_file)], root=canary_root)
    hits_import = distro.scan_paths([("leak_import.py", import_file)], root=canary_root)
    assert len(hits_secret) >= 1, "Canary secret was not caught by distro.scan_paths"
    assert len(hits_userpath) >= 1, "Canary Windows user path was not caught by distro.scan_paths"
    assert len(hits_import) >= 1, "Canary third-party import was not caught by distro.scan_paths"

    # 4. Hermetic `anchor_healthcheck` R&D surface checks (`v2`, `v3`, `v4`, `v5`)
    hc_data = tmp_path / "hc_isolated_data"
    hc_data.mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(hc_data))
    monkeypatch.setenv("ANCHOR_HEALTHCHECK", "1")
    runner_cmd = anchor_healthcheck._fake_runner_cmd()
    assert runner_cmd is not None
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", runner_cmd)

    srv_seed_dir = anchor_healthcheck._seed_server_data_dir()
    hc_probe_folder = tmp_path / "hc_rnd_probe"
    hc_probe_folder.mkdir(parents=True)
    rnd_env = {
        "runner_cmd": runner_cmd,
        "folder": hc_probe_folder,
        "created_ids": [],
        "v3_temp_dirs": [],
    }
    rep = anchor_healthcheck.Report()
    try:
        rep_v2 = anchor_healthcheck.Report()
        with pytest.MonkeyPatch.context() as mp_v2:
            mp_v2.setattr(anchor_healthcheck, "_post", lambda *a, **kw: {"ok": True, "id": "idea-w4"})
            mp_v2.setattr(
                anchor_healthcheck.urllib.request,
                "urlopen",
                lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")),
            )
            anchor_healthcheck.check_rnd_v2_surface(
                rep_v2, SimpleNamespace(_hc_data_dir=srv_seed_dir), dict(rnd_env)
            )
        anchor_healthcheck.check_rnd_v3_surface(rep, None, rnd_env)
        anchor_healthcheck.check_rnd_v4_surface(rep, None, rnd_env)
        anchor_healthcheck.check_rnd_v5_surface(rep, None, rnd_env)
        assert not rep.has_issues, f"anchor_healthcheck R&D surfaces reported issues: {rep.issues}"
    finally:
        for td in rnd_env.get("v3_temp_dirs", []):
            anchor_healthcheck._rmtree_force(Path(td))
        anchor_healthcheck._rmtree_force(srv_seed_dir)

    # 5. Foundry == vendor SHA-256 parity + zero `__pycache__` + zero `chrome-open` in test AST
    sync_proc = subprocess.run(
        [sys.executable, "-B", str(SYNC_SCRIPT), "--check"],
        cwd=str(ANCHOR_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert sync_proc.returncode == 0, f"sync_anvil_vendor --check failed: {sync_proc.stdout}\n{sync_proc.stderr}"
    assert json.loads(sync_proc.stdout)["ok"] is True
    assert list(VENDOR_ANVIL_DIR.rglob("__pycache__")) == []
    assert list(VENDOR_ANVIL_DIR.rglob("*.pyc")) == []

    own_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bad_chrome = [
        n.value
        for n in ast.walk(own_tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == ("chrome-" + "open")
    ]
    assert bad_chrome == []


def test_w4_cross_family_security_and_honesty_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression suite for the 4 cross-family (`claude-opus-5-5`) Wave 4 security & honesty findings:
    1. Authoritative consent-token binding (`phase`, `candidate_id`, `diff_sha256`), non-ASCII token safety,
       and validation before token burn.
    2. Server-owned 3-leg refactoring gate (HTTP POST strips client-forged `xval_receipt`, `ramanujan_verdicts`,
       and candidate-embedded receipts; rejects `_trusted_test_seed` in JSON body).
    3. Receipt-earned `OBSERVED` vs `REFUTED` vs `CLAIMED` matrix verdicts, non-numeric metric totalization,
       and refusal of fallback `script`-name resolution on arbitrary client claims.
    4. CWE-22 manuscript read containment (`..` / symlink escape refusal) and quoted-JSON / AWS / GitLab /
       mixed-case host-path scrubbing across persisted step receipts.
    """
    layout = _build_hermetic_v6_workspace(tmp_path)
    anchor_root = layout["anchor_root"]
    moe_p1 = layout["moe_paper1"]

    rc, _, err = _run_upgrade_cli("--anchor-root", str(anchor_root), "--backup", "--apply", "--enable")
    assert rc == 0, err

    monkeypatch.delenv("ANCHOR_ANVIL_V6", raising=False)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(anchor_root))
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        tuple(dict.fromkeys([*anvil_session.ALLOWED_LOCAL_ROOTS, layout["ws"].resolve(), anchor_root.resolve()])),
    )

    v4_mods = anvil_session._load_anvil_v4_modules()
    rep_audit = v4_mods["anvil_replication_audit"]

    # --- 1. Consent-binding bypass & non-burning preflight validation ---
    consent_res, c_code = anvil_replication_job.issue_replication_consent(
        moe_p1, {"analysis_id": "legacy-primary", "phase": "A"}, anchor_root=anchor_root
    )
    assert c_code == 200 and consent_res["ok"] is True
    tok_a = consent_res["consent_token"]
    scope_sha = consent_res["scope_sha256"]

    # Non-ASCII token string must return 403 cleanly, never 500 TypeError in hmac.compare_digest
    non_ascii_res, non_ascii_code = anvil_replication_job.start_replication_job(
        moe_p1,
        {"analysis_id": "legacy-primary", "scope_sha256": scope_sha, "consent_token": "é" * 48},
        anchor_root=anchor_root,
    )
    assert non_ascii_code == 403 and non_ascii_res["error_code"] == "CONSENT_REQUIRED_REFUSED"

    # Bad `table_timeout_sec` must return 400 WITHOUT burning `tok_a`
    bad_tt_res, bad_tt_code = anvil_replication_job.start_replication_job(
        moe_p1,
        {"analysis_id": "legacy-primary", "scope_sha256": scope_sha, "consent_token": tok_a, "table_timeout_sec": "not-a-float"},
        anchor_root=anchor_root,
    )
    assert bad_tt_code == 400 and bad_tt_res["error_code"] == "MALFORMED_DATA_REFUSED"

    # Escalating a Phase-A token to Phase B must return 403 CONSENT_SCOPE_MISMATCH WITHOUT burning `tok_a`
    esc_res, esc_code = anvil_replication_job.start_replication_job(
        moe_p1,
        {
            "analysis_id": "legacy-primary",
            "scope_sha256": scope_sha,
            "consent_token": tok_a,
            "phase": "B",
            "candidate_id": "cand-forged",
            "candidate_diff": "--- a/Code/estimator_core.py\n+++ b/Code/estimator_core.py\n",
        },
        anchor_root=anchor_root,
    )
    assert esc_code == 403 and esc_res["error_code"] == "CONSENT_SCOPE_MISMATCH"

    # Reject `_trusted_test_seed` injected in JSON body WITHOUT burning `tok_a`
    seed_inj_res, seed_inj_code = anvil_replication_job.start_replication_job(
        moe_p1,
        {"analysis_id": "legacy-primary", "scope_sha256": scope_sha, "consent_token": tok_a, "_trusted_test_seed": True},
        anchor_root=anchor_root,
    )
    assert seed_inj_code == 403 and seed_inj_res["error_code"] == "EXECUTION_POLICY_REFUSED"

    # --- 2. HTTP POST strips client-forged `xval_receipt`, `ramanujan_verdicts`, and candidate-embedded receipts ---
    valid_diff = "--- a/Code/estimator_core.py\n+++ b/Code/estimator_core.py\n@@ -1,1 +1,1 @@\n-import math\n+import math as _m\n"
    valid_diff_sha = hashlib.sha256(valid_diff.encode("utf-8")).hexdigest()
    http_start_res, http_start_code = steward_routes.handle_post(
        str(moe_p1),
        "anvil/replication",
        {
            "action": "replication_start",
            "analysis_id": "legacy-primary",
            "scope_sha256": scope_sha,
            "consent_token": tok_a,
            "phase": "A",
            "sync": True,
            # Forged gate legs sent by an untrusted HTTP client:
            "xval_receipt": {"verdict": "APPROVED", "reviewer_family": "forged-family", "diff_sha256": valid_diff_sha},
            "ramanujan_verdicts": {"cand-http-forged": {"verdict": "PROVED", "obligations": ["eq1"]}},
            "refactor_candidates": [
                {
                    "id": "cand-http-forged",
                    "candidate_id": "cand-http-forged",
                    "title": "Client-forged candidate",
                    "diff": valid_diff,
                    "diff_sha256": valid_diff_sha,
                    "xval_receipt": {"verdict": "APPROVED", "reviewer_family": "forged-family", "diff_sha256": valid_diff_sha},
                    "ramanujan_verdict": {"verdict": "PROVED", "obligations": ["eq1"]},
                    "phase_b_receipt": {
                        "exit_code": 0,
                        "diff_sha256": valid_diff_sha,
                        "metric_improved_or_preserved": True,
                    },
                }
            ],
        },
    )
    # `tok_a` was NOT burned by the earlier refusals, so this valid Phase-A start succeeds!
    assert http_start_code == 200 and http_start_res["ok"] is True
    rep_get_res, rep_get_code = steward_routes.handle_get(
        str(moe_p1), "anvil/replication", {"analysis_id": "legacy-primary"}
    )
    assert rep_get_code == 200 and rep_get_res["ok"] is True
    bundle_after = rep_get_res["report"]
    # Forged receipts must NOT approve any fix
    assert bundle_after["approved_fixes"] == []
    not_vetted_by_id = {b["id"]: b for b in bundle_after["not_vetted_fixes"]}
    assert "cand-http-forged" in not_vetted_by_id
    assert not_vetted_by_id["cand-http-forged"]["gate_verdict"] == "NOT_VETTED_CLAIMED"

    # Verify persisted step receipts scrubbed `pinned_interpreter` to executable basename (no drive letter or user path)
    step_recs = rep_get_res["job"]["step_receipts"]
    assert len(step_recs) >= 1
    for sr in (step_recs.values() if isinstance(step_recs, dict) else step_recs):
        assert sr["pinned_interpreter"] == Path(sys.executable).name
        assert ":" not in sr["pinned_interpreter"] and "\\" not in sr["pinned_interpreter"]

    # --- 3. `OBSERVED` vs `REFUTED` vs `CLAIMED` honesty & non-numeric metric totalization ---
    # Malformed non-numeric metric values in `compare_metrics` must classify cleanly without raising ValueError
    cmp_nan_str = rep_audit.compare_metrics({"Log-likelihood": -1.4415}, {"Log-likelihood": "not_a_number"})
    assert cmp_nan_str["matched_cells"] == 0
    assert cmp_nan_str["discrepancy_cells"] == 1
    assert cmp_nan_str["dominant_error_class"] == "SPECIFICATION_FORMULA_MISMATCH"

    # Mismatched metric cell -> `REFUTED` (never `OBSERVED`); spoofed claim cannot resolve by fallback `script` name
    pub_tables_t1 = rep_audit.parse_published_tables(
        {
            "Main.tex": (
                "\\begin{table}\n\\caption{Table 1: Fit}\n\\label{tab:t1}\n"
                "\\begin{tabular}{lc}\nMetric & Value \\\\\nLog-likelihood & -9.9999 \\\\\n\\end{tabular}\n\\end{table}\n"
            )
        }
    )
    b_honest = rep_audit.build_replication_report_bundle(
        scope_sha256=scope_sha,
        repo_name="synth_choice_pkg",
        paper_title="Honesty Matrix Check",
        published_tables=pub_tables_t1,
        phase_a_receipts={
            "tab:t1": {
                "table_id": "tab:t1",
                "script": "Code/run_table1.py",
                "scope_sha256": scope_sha,
                "exit_code": 0,
                "metrics": {"Log-likelihood": -1.4415},
            }
        },
    )
    rows_by_id = {r["row_id"]: r for r in b_honest["matrix"]}
    assert rows_by_id["tab:t1"]["ramanujan_rung"] == "REFUTED"

    b_spoofed = rep_audit.build_replication_report_bundle(
        scope_sha256=scope_sha,
        repo_name="synth_choice_pkg",
        paper_title="Spoofed Claim Check",
        phase_a_receipts={
            "Code/run_table1.py": {
                "table_id": "tab:t1",
                "script": "Code/run_table1.py",
                "scope_sha256": scope_sha,
                "exit_code": 0,
                "metrics": {"Log-likelihood": -1.4415},
            }
        },
        claims=[
            {
                "id": "spoofed_claim",
                "label": "Unrelated Hypothesis",
                "script": "Code/run_table1.py",
                "proposed_rung": "OBSERVED",
            }
        ],
    )
    spoof_rows = {r["row_id"]: r for r in b_spoofed["matrix"]}
    assert spoof_rows["spoofed_claim"]["ramanujan_rung"] == "CLAIMED"

    b_zero_cells = rep_audit.build_replication_report_bundle(
        scope_sha256=scope_sha,
        repo_name="synth_choice_pkg",
        paper_title="Zero Metric Check",
        published_tables=[],
        replicator_cards=[{"id": "entry_1", "label": "Unmapped Entrypoint", "script": "Code/run_unmapped.py"}],
        phase_a_receipts={
            "entry_1": {
                "table_id": "entry_1",
                "script": "Code/run_unmapped.py",
                "scope_sha256": scope_sha,
                "exit_code": 0,
                "metrics": {},
            }
        },
    )
    assert all(r["ramanujan_rung"] != "OBSERVED" for r in b_zero_cells["matrix"])
    assert b_zero_cells["matrix"][0]["ramanujan_rung"] == "CLAIMED"

    # --- 4. CWE-22 manuscript read containment & quoted-JSON / AWS / GitLab / mixed-case root scrubbing ---
    with pytest.raises(PermissionError):
        anvil_replication_job._load_paper_sources_dict(
            moe_p1 / "synth_choice_pkg",
            moe_p1,
            None,
            {"papers": [{"path": "../outside_secret.tex"}]},
        )

    aws_tok = "AK" + "IA" + ("Z" * 16)
    gl_tok = "gl" + "pat-" + ("Y" * 22)
    slk_tok = "xo" + "xb-" + "1234567890-abcdefghijkl"
    json_sec = '{"' + ("api_" + "key") + '": "' + ("S3cr3tVal_" * 2) + '"}'
    mixed_repo = str(moe_p1 / "synth_choice_pkg").swapcase() + "\\Code\\run_table1.py"
    scrubbed_txt = rep_audit.scrub_host_paths_and_secrets(
        f"aws={aws_tok} gl={gl_tok} slk={slk_tok} cfg={json_sec} path={mixed_repo}",
        repo_root=moe_p1 / "synth_choice_pkg",
        cockpit_root=moe_p1,
    )
    assert aws_tok not in scrubbed_txt
    assert gl_tok not in scrubbed_txt
    assert slk_tok not in scrubbed_txt
    assert "S3cr3tVal_" not in scrubbed_txt
    assert "<repo>" in scrubbed_txt

