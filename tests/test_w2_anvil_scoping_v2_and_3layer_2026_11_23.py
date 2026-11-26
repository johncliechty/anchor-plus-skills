#!/usr/bin/env python3
"""Anvil v6 Wave 2 Test Suite — Call-Time `ANCHOR_ANVIL_V6` Gate, Locked Scoping v2 UI,
Explicit 3-Layer Workbench View, Contained Opaque-ID Routes, CWE-918 Scholarly Allowlist,
Atomic Lock Concurrency/Idempotence, XSS Hostile Escaping & Headless `ft.py look --check`.
"""
from __future__ import annotations

import ast
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
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
from steward_cockpit import anvil_session, steward_routes  # noqa: E402


def _load_module(py_path: Path, mod_name: str) -> Any:
    scripts_dir = str(py_path.parent)
    added = False
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        added = True
    prev_bc = sys.dont_write_bytecode
    prev_mod = sys.modules.get(mod_name)
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(py_path))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = prev_bc
        if prev_mod is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = prev_mod
        if added and scripts_dir in sys.path:
            sys.path.remove(scripts_dir)


def _build_hostile_scoping_cockpit(base_dir: Path, *, include_xss: bool = True) -> Path:
    """Create a self-contained synthetic research cockpit inside `base_dir` with:
      - Core estimator (`reached` + dynamic registry `uncertain` + statically `unreached` dead function)
      - Matched Table 1 replicator (`run_table1_eval.py`) + unmatched Table 2 (`tab:unmatched_two`)
      - Raw ETL / load-time imported plumbing (`prep_clean_data.py`)
      - Optional hostile XSS payloads in manuscript title/section/caption/equation and Python docstrings
    """
    cdir = base_dir / "synth_cockpit"
    cdir.mkdir(parents=True, exist_ok=True)
    xss_tag = '<img src=x onerror="window.__xss_fired=1">' if include_xss else "Alpha"

    (cdir / "prep_clean_data.py").write_text(
        textwrap.dedent(
            """\
            def build_default_grid():
                return [0.25, 0.5, 0.75]

            DEFAULT_GRID = build_default_grid()

            def clean_raw_records(rows):
                return [float(r) for r in rows]
            """
        ),
        encoding="utf-8",
    )

    (cdir / "core_estimator.py").write_text(
        textwrap.dedent(
            f'''\
            """Core estimator module {xss_tag}."""
            import prep_clean_data

            class PenalizedLikelihoodEstimator:
                def __init__(self, penalty_weight: float = 0.5):
                    self.penalty_weight = penalty_weight

                def log_likelihood(self, theta: float, x: list) -> float:
                    scale = prep_clean_data.DEFAULT_GRID[0]
                    return -0.5 * sum((v - theta) ** 2 for v in x) - self.penalty_weight * (theta ** 2) * scale

            def dynamic_bfgs_step(theta: float) -> float:
                return theta * 0.9

            def dynamic_newton_step(theta: float) -> float:
                return theta * 0.85

            STEP_SOLVERS = {{
                "bfgs": dynamic_bfgs_step,
                "newton": dynamic_newton_step,
            }}

            def abandoned_legacy_approx(theta: float) -> float:
                """Statically unreached sibling function — must never bind equations."""
                return theta + 999.0
            '''
        ),
        encoding="utf-8",
    )

    (cdir / "run_table1_eval.py").write_text(
        textwrap.dedent(
            """\
            from core_estimator import PenalizedLikelihoodEstimator, STEP_SOLVERS

            def replicate_table_one(solver_name: str = "bfgs") -> float:
                est = PenalizedLikelihoodEstimator(penalty_weight=0.5)
                step_fn = STEP_SOLVERS[solver_name]
                theta1 = step_fn(1.2)
                val = est.log_likelihood(theta1, [1.0, 1.5, 2.0])
                # Writes tab_main_est summary
                return val

            if __name__ == "__main__":
                replicate_table_one("bfgs")
            """
        ),
        encoding="utf-8",
    )

    (cdir / "sim_monte_carlo.py").write_text(
        textwrap.dedent(
            """\
            def run_synthetic_dgp_simulation(n: int = 20) -> float:
                return float(n) * 0.1
            """
        ),
        encoding="utf-8",
    )

    (cdir / "workflow.sh").write_text(
        "# Step 1: Primary Estimator Table (tab:main_est)\n"
        "python run_table1_eval.py --out results/tab_main_est.tex\n",
        encoding="utf-8",
    )

    (cdir / "main.tex").write_text(
        textwrap.dedent(
            f"""\
            \\documentclass{{article}}
            \\title{{Penalized Likelihood Estimation {xss_tag}}}
            \\begin{{document}}
            \\section{{Model Specification {xss_tag}}}
            The penalized objective maximizes `log_likelihood` with `penalty_weight`:
            \\begin{{equation}}\\label{{eq:pen_ll}}
            \\mathcal{{L}}(\\theta) = -\\frac{{1}}{{2}}\\sum_i (x_i - \\theta)^2 - \\lambda \\theta^2
            \\end{{equation}}

            \\section{{Empirical Results}}
            \\begin{{table}}
            \\caption{{Primary Estimator Fit {xss_tag}}}
            \\label{{tab:main_est}}
            \\begin{{tabular}}{{lc}}
            Metric & Value \\\\
            LogLik & -1.25 \\\\
            \\end{{tabular}}
            \\end{{table}}

            \\begin{{table}}
            \\caption{{External Holdout Comparison Without Script}}
            \\label{{tab:unmatched_two}}
            \\begin{{tabular}}{{lc}}
            Metric & Value \\\\
            Holdout & 0.88 \\\\
            \\end{{tabular}}
            \\end{{table}}
            \\end{{document}}
            """
        ),
        encoding="utf-8",
    )
    return cdir


def _start_ephemeral_cockpit_http_server(cockpit_dir: Path) -> Tuple[ThreadingHTTPServer, int, threading.Thread]:
    """Bind an ephemeral loopback HTTP server (`port != 8777`) serving `/steward-static/*`,
    `/vendor/brand/*`, and `/api/steward/*` pinned to `cockpit_dir`.
    """
    static_dir = (ANCHOR_ROOT / "steward_cockpit" / "static").resolve()
    brand_dir = (ANCHOR_ROOT / "vendor" / "brand").resolve()
    cdir_str = str(cockpit_dir.resolve())

    class _CockpitTestHandler(BaseHTTPRequestHandler):
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
            path = parsed.path
            if not path.startswith("/api/steward/"):
                self.send_error(404)
                return
            verb = path[len("/api/steward/"):]
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body_obj = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self._send_json(
                    400,
                    {
                        "ok": False,
                        "error_code": "MALFORMED_DATA_REFUSED",
                        "status_kind": "dependency-returns-garbage",
                        "failure_state": "dependency-returns-garbage",
                        "message": "Malformed Anvil request or invalid engine output",
                        "error": "Malformed Anvil request or invalid engine output",
                    },
                )
                return
            if not isinstance(body_obj, dict):
                self._send_json(
                    400,
                    {
                        "ok": False,
                        "error_code": "MALFORMED_DATA_REFUSED",
                        "status_kind": "dependency-returns-garbage",
                        "failure_state": "dependency-returns-garbage",
                        "message": "Malformed Anvil request or invalid engine output",
                        "error": "Malformed Anvil request or invalid engine output",
                    },
                )
                return

            out, code = steward_routes.handle_post(cdir_str, verb, body_obj)
            self._send_json(code, out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _CockpitTestHandler)
    port = int(srv.server_address[1])
    if port == 8777:
        srv2 = ThreadingHTTPServer(("127.0.0.1", 0), _CockpitTestHandler)
        srv.server_close()
        srv = srv2
        port = int(srv.server_address[1])
    assert port != 8777
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    th.start()
    return srv, port, th


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: Optional[Any] = None,
) -> Tuple[int, Dict[str, Any]]:
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
        with urlopen(req, timeout=20.0) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except HTTPError as herr:
        payload = json.loads(herr.read().decode("utf-8"))
        return int(herr.code), payload


def test_w2_v6_feature_gate_marker_isolation_and_5row_failure_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify:
      1) `is_anvil_v6_enabled()` code default is strictly `False` when `ANCHOR_ANVIL_V6` is unset,
         and live `C:\\dev\\Anchor\\.anchor\\anvil-v6-enabled.json` is untouched.
      2) `ANCHOR_ANVIL_V6=1/0` and `--anchor-root <tmp_path>` marker file (`{"enabled": true}`)
         toggle v6 cleanly while refusing symlinks.
      3) Full 5-row failure-state table with `ANCHOR_ANVIL_V6=1` returns exact HTTP status codes and
         exact user-visible messages, keeping `500 UNKNOWN` and `200 EMPTY` strictly separate.
    """
    live_v6_marker = ANCHOR_ROOT / ".anchor" / "anvil-v6-enabled.json"
    pre_marker_exists = live_v6_marker.exists()

    monkeypatch.delenv("ANCHOR_ANVIL_V6", raising=False)
    empty_anchor_root = tmp_path / "isolated_anchor_root"
    empty_anchor_root.mkdir()
    assert anvil_session.is_anvil_v6_enabled(anchor_root=empty_anchor_root) is False

    # Marker file inside tmp_path (--anchor-root <tmp_path>) enables v6 without touching live .anchor/
    dot_anchor = empty_anchor_root / ".anchor"
    dot_anchor.mkdir()
    marker_file = dot_anchor / "anvil-v6-enabled.json"
    marker_file.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert anvil_session.is_anvil_v6_enabled(anchor_root=empty_anchor_root) is True

    # Env override ANCHOR_ANVIL_V6=0 takes precedence over marker and refuses mutating v6 actions with 403 ANVIL_V6_DISABLED
    monkeypatch.setenv("ANCHOR_ANVIL_V6", "0")
    assert anvil_session.is_anvil_v6_enabled(anchor_root=empty_anchor_root) is False
    off_lock_p, off_lock_c = anvil_session.lock_scope_v2(tmp_path, {}, anchor_root=empty_anchor_root)
    assert off_lock_c == 403 and off_lock_p["error_code"] == "ANVIL_V6_DISABLED"
    off_turn_p, off_turn_c = anvil_session.run_scoping_v2_turn(tmp_path, {"message": "hi"}, anchor_root=empty_anchor_root)
    assert off_turn_c == 403 and off_turn_p["error_code"] == "ANVIL_V6_DISABLED"

    # Symlinked .anchor or marker file is strictly refused (returns False)
    monkeypatch.delenv("ANCHOR_ANVIL_V6", raising=False)
    symlink_anchor_root = tmp_path / "symlink_anchor_root"
    symlink_anchor_root.mkdir()
    real_outside_anchor = tmp_path / "outside_dot_anchor"
    real_outside_anchor.mkdir()
    (real_outside_anchor / "anvil-v6-enabled.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    linked_dot_anchor = symlink_anchor_root / ".anchor"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(linked_dot_anchor), str(real_outside_anchor)], check=True, capture_output=True)
    else:
        linked_dot_anchor.symlink_to(real_outside_anchor, target_is_directory=True)
    try:
        assert anvil_session.is_anvil_v6_enabled(anchor_root=symlink_anchor_root) is False
    finally:
        if os.name == "nt":
            os.rmdir(linked_dot_anchor)
        else:
            linked_dot_anchor.unlink()

    # CLI subprocess check with --anchor-root <tmp_path> and ANCHOR_ANVIL_V6 unset
    cdir = _build_hostile_scoping_cockpit(tmp_path, include_xss=False)
    cli_env = {k: v for k, v in os.environ.items() if k != "ANCHOR_ANVIL_V6"}
    cli_proc = subprocess.run(
        [
            sys.executable,
            str(ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py"),
            "--cockpit",
            str(cdir),
            "--anchor-root",
            str(empty_anchor_root),
            "--action",
            "scoping_state",
        ],
        env=cli_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert cli_proc.returncode == 0, cli_proc.stderr
    cli_doc = json.loads(cli_proc.stdout)
    assert cli_doc["anvil_v6_enabled"] is True
    assert cli_doc["message"] == "No Anvil scopes locked yet — inspect the Software & Paper Map below"
    assert live_v6_marker.exists() == pre_marker_exists

    # Verify all 5 failure-state rows with ANCHOR_ANVIL_V6=1
    monkeypatch.setenv("ANCHOR_ANVIL_V6", "1")
    expected_rows = [
        ("dependency-missing", 503, False, "Anvil engine unavailable: required Python/skill module missing"),
        ("dependency-slow-or-killed", 504, False, "Anvil operation timed out or worker terminated"),
        ("dependency-returns-garbage", 502, False, "Malformed Anvil request or invalid engine output"),
        ("backing-store-unreadable", 500, True, "UNKNOWN: Anvil analysis store unreadable or corrupted"),
        ("empty-but-valid", 200, False, "No Anvil scopes locked yet — inspect the Software & Paper Map below"),
    ]
    for row_key, exp_code, exp_unknown, exp_msg in expected_rows:
        payload, code = anvil_session.build_v5_failure_response(row_key, anchor_root=empty_anchor_root)
        assert code == exp_code
        assert payload["http_status"] == exp_code
        assert payload["unknown_state"] is exp_unknown
        assert payload["message"] == exp_msg

        # Verify JS client boot failure resolver matches exact status + message
    # Also verify real corrupt backing store triggers 500 UNKNOWN (never 200 EMPTY!)
    corrupt_cdir = tmp_path / "corrupt_cockpit"
    (corrupt_cdir / ".anvil" / "analyses").mkdir(parents=True)
    (corrupt_cdir / ".anvil" / "analyses" / "index.json").write_text("{truncated-corrupt-json", encoding="utf-8")
    p500, c500 = anvil_session.get_scoping_v2_state(corrupt_cdir, anchor_root=empty_anchor_root)
    assert c500 == 500
    assert p500["badge"] == "UNKNOWN"
    assert p500["unknown_state"] is True
    assert p500["message"] == "UNKNOWN: Anvil analysis store unreadable or corrupted"


def test_w2_atomic_lock_concurrency_repeat_idempotence_and_numeric_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove:
      1) Two concurrent child OS processes calling `lock_scope_v2` serialize under `exclusive_file_lock`
         and commit atomic `index.json` + `scope_manifest.json` with zero partial writes or leftover `.part` files.
      2) Repeat `lock_scope_v2` invocation with identical scope is idempotent (`idempotent_reuse=True`).
      3) Warm `get_v4_cockpit_state` read hits disk/RAM cache in `<50 ms`.
      4) Numeric bounds (`MAX_DIRECTION_BYTES=16384 -> 413`, `<=64` analyses -> `400`, `<=8 MB` bundle -> `400`)
         refuse cleanly when exceeded.
    """
    monkeypatch.setenv("ANCHOR_ANVIL_V6", "1")
    cdir = _build_hostile_scoping_cockpit(tmp_path, include_xss=False)

    # Verify preview SHA-256 == locked SHA-256 and entrypoints are populated in preview receipt
    prev_state, prev_code = anvil_session.get_scoping_v2_state(cdir)
    assert prev_code == 200
    preview_sha = prev_state["receipt"]["scope_sha256"]
    assert len(prev_state["receipt"]["entrypoints"]) >= 1
    default_mids = sorted(prev_state["receipt"]["selected_module_ids"])
    assert len(default_mids) >= 2
    subset_mids = [default_mids[0]]

    worker_tmpl = textwrap.dedent(
        """\
        import json, os, sys
        sys.path.insert(0, {anchor_root})
        os.environ["ANCHOR_ANVIL_V6"] = "1"
        from steward_cockpit import anvil_session
        payload, code = anvil_session.lock_scope_v2({cdir}, {{"module_ids": {mids}, "create_new": True}})
        print(json.dumps({{"code": code, "aid": payload.get("analysis_id"), "sha": payload.get("scope_sha256"), "reuse": payload.get("idempotent_reuse")}}))
        """
    )
    w1_code = worker_tmpl.format(anchor_root=json.dumps(str(ANCHOR_ROOT)), cdir=json.dumps(str(cdir)), mids=json.dumps(default_mids))
    w2_code = worker_tmpl.format(anchor_root=json.dumps(str(ANCHOR_ROOT)), cdir=json.dumps(str(cdir)), mids=json.dumps(subset_mids))
    p1 = subprocess.Popen([sys.executable, "-c", w1_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p2 = subprocess.Popen([sys.executable, "-c", w2_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out1, err1 = p1.communicate(timeout=45)
    out2, err2 = p2.communicate(timeout=45)
    assert p1.returncode == 0, err1
    assert p2.returncode == 0, err2
    r1 = json.loads(out1.strip().splitlines()[-1])
    r2 = json.loads(out2.strip().splitlines()[-1])
    assert r1["code"] == 200 and r2["code"] == 200
    assert re.fullmatch(r"[0-9a-f]{64}", r1["sha"])
    assert re.fullmatch(r"[0-9a-f]{64}", r2["sha"])
    # Preview SHA-256 MUST equal Locked SHA-256 for identical module selection!
    assert r1["sha"] == preview_sha
    assert r1["sha"] != r2["sha"]
    assert r1["aid"] != r2["aid"]

    # Zero leftover temp/part files, and BOTH distinct concurrent slots survived in index.json!
    leftover_parts = list((cdir / ".anvil").rglob("*.part"))
    assert leftover_parts == []
    listed, l_code = anvil_session.list_cockpit_analyses(cdir)
    assert l_code == 200
    surviving_ids = {a["analysis_id"] for a in listed["analyses"]}
    assert {r1["aid"], r2["aid"]}.issubset(surviving_ids)
    assert len(listed["analyses"]) == 2

    # Repeat invocation in-process (`create_new=False`) is idempotent and reuses r1["aid"]
    rep_payload, rep_code = anvil_session.lock_scope_v2(cdir, {"module_ids": default_mids})
    assert rep_code == 200
    assert rep_payload["idempotent_reuse"] is True
    assert rep_payload["analysis_id"] == r1["aid"]
    listed2, _ = anvil_session.list_cockpit_analyses(cdir)
    assert len(listed2["analyses"]) == 2

    # Reserved/JSON analysis_id refusal ("index.json", "custom.json")
    bad_idx_res, bad_idx_code = anvil_session.lock_scope_v2(cdir, {"analysis_id": "index.json"})
    assert bad_idx_code == 400

    # Warm `get_v4_cockpit_state` read completes in <50 ms and warm `check_locked_scope_drift` in <5 ms
    with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
        anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()
    t0 = time.perf_counter()
    warm_p, warm_c = anvil_session.get_v4_cockpit_state(cdir, analysis_id=r1["aid"])
    warm_ms = (time.perf_counter() - t0) * 1000.0
    assert warm_c == 200
    assert warm_p["cache_hit"] in {"disk", "memory"}
    assert warm_ms < 50.0, f"Warm state read took {warm_ms:.2f} ms (expected < 50 ms)"

    v4_proc_live = anvil_session._load_anvil_v4_modules()["anvil_v4_process"]
    _, r1_store = anvil_session.resolve_store_root(cdir, r1["aid"])
    _ = anvil_session.check_locked_scope_drift(cdir, r1_store, v4_proc_live)
    td0 = time.perf_counter()
    drift_warm = anvil_session.check_locked_scope_drift(cdir, r1_store, v4_proc_live)
    drift_ms = (time.perf_counter() - td0) * 1000.0
    assert drift_warm is not None and drift_warm["drifted"] is False
    assert drift_ms < 5.0, f"Stat-memoized drift check took {drift_ms:.3f} ms (expected < 5 ms)"

    # Bound 1: MAX_DIRECTION_BYTES = 16384 -> 413 when exceeded
    ok_turn, ok_tc = anvil_session.run_scoping_v2_turn(cdir, {"message": "a" * 16384})
    assert ok_tc == 200
    big_turn, big_tc = anvil_session.run_scoping_v2_turn(cdir, {"message": "a" * 16385})
    assert big_tc == 413
    assert big_turn["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    big_lock, big_lc = anvil_session.lock_scope_v2(cdir, {"direction": "b" * 16385})
    assert big_lc == 413
    assert big_lock["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    # Bound 2: <= 8 MB in-scope bundle -> 400 when exceeded
    huge_cdir = tmp_path / "huge_bundle_cockpit"
    huge_cdir.mkdir()
    huge_body = "# " + ("x" * 1020) + "\n"
    (huge_cdir / "giant_estimator.py").write_text(
        "def fit_model(x):\n    return x\n" + (huge_body * 8300),
        encoding="utf-8",
    )
    huge_res, huge_code = anvil_session.lock_scope_v2(huge_cdir, {})
    assert huge_code == 400
    assert huge_res["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    # Bound 3: <= 64 non-archived analyses -> 400 on 65th slot
    cap_cdir = _build_hostile_scoping_cockpit(tmp_path / "cap64", include_xss=False)
    idx_dir = cap_cdir / ".anvil" / "analyses"
    idx_dir.mkdir(parents=True)
    synth_entries = []
    for i in range(1, 65):
        aid_i = f"scope-slot-{i}"
        (idx_dir / aid_i).mkdir(parents=True, exist_ok=True)
        synth_entries.append({
            "analysis_id": aid_i,
            "title": f"Scope {i}",
            "store": f"analyses/{aid_i}",
            "mode": "code",
            "software_spec": ".",
            "paper_spec": "",
            "archived": False,
        })
    (idx_dir / "index.json").write_text(
        json.dumps({
            "schema": anvil_session.ANVIL_ANALYSES_INDEX_SCHEMA,
            "active_analysis_id": "scope-slot-1",
            "analyses": synth_entries,
        }),
        encoding="utf-8",
    )
    cap_res, cap_code = anvil_session.lock_scope_v2(cap_cdir, {"create_new": True})
    assert cap_code == 400
    assert cap_res["error_code"] == "BOUND_EXCEEDED_REFUSAL"


def test_w2_cwe22_escape_attempts_cwe918_scholarly_allowlist_and_chat_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify over a live ephemeral server (`port != 8777`):
      - Path-key `module_ids` (`a/b.py`) & unknown forged `module_ids` return `400`.
      - Traversal (`..`), absolute paths, UNC paths, and OS junctions/symlinks return `403`.
      - `quick_literature_sketch` refuses unconsented calls (`403`), `http://`, `file://`, `127.0.0.1`,
        and non-allowlisted domains (`403`), while stubbed allowlisted `https://api.openalex.org/...`
        returns `200` stamped `CLAIMED / unverified` (`verified: False`, `model_calls: 1`).
      - Chat messages mentioning `researchPrime` / `literature` NEVER trigger `quick_literature_sketch`.
    """
    monkeypatch.setenv("ANCHOR_ANVIL_V6", "1")
    cdir = _build_hostile_scoping_cockpit(tmp_path, include_xss=False)
    outside_dir = tmp_path / "outside_secret"
    outside_dir.mkdir()
    (outside_dir / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")

    srv, port, _th = _start_ephemeral_cockpit_http_server(cdir)
    base_url = f"http://127.0.0.1:{port}"
    try:
        # 1. Path-like key & forged unknown ID -> 400
        c_pathkey, p_pathkey = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "lock_scope", "module_ids": ["core_estimator.py"]},
        )
        assert c_pathkey == 400
        assert p_pathkey["message"] == "Malformed Anvil request or invalid engine output"

        c_slashkey, _ = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "lock_scope", "module_ids": ["pkg/core_estimator.py"]},
        )
        assert c_slashkey == 400

        c_forged, _ = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "lock_scope", "module_ids": ["forged_nonexistent_module"]},
        )
        assert c_forged == 400

        # 2. Traversal, UNC, absolute path, and OS junction -> 403
        link_dir = cdir / "linked_escape"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link_dir), str(outside_dir)], check=True, capture_output=True)
        else:
            link_dir.symlink_to(outside_dir, target_is_directory=True)
        try:
            escape_payloads = [
                {"action": "lock_scope", "module_ids": ["../outside_secret"]},
                {"action": "lock_scope", "module_ids": ["\\\\evil\\share"]},
                {"action": "scoping_state", "software_spec": "../outside_secret"},
                {"action": "scoping_state", "software_spec": str(outside_dir.resolve())},
                {"action": "scoping_state", "software_spec": "\\\\127.0.0.1\\c$"},
                {"action": "scoping_state", "software_spec": "linked_escape"},
                {"action": "scoping_state", "paper_spec": "../outside_secret/secret.py"},
            ]
            for bad_body in escape_payloads:
                code_esc, pay_esc = _http_json(
                    f"{base_url}/api/steward/anvil/scoping",
                    method="POST",
                    body=bad_body,
                )
                assert code_esc == 403, f"Expected 403 for {bad_body}, got {code_esc}: {pay_esc}"
        finally:
            if os.name == "nt":
                os.rmdir(link_dir)
            else:
                link_dir.unlink()

        # 3. Chat regex NEVER triggers quick_literature_sketch
        lit_calls: List[str] = []

        def _spy_urlopen(url: str, timeout: float = 8.0) -> Tuple[bytes, str]:
            lit_calls.append(url)
            return json.dumps({"results": [{"title": "Stubbed Penalized Likelihood Paper (2024)"}]}).encode("utf-8"), "application/json"

        c_chat, _ = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "scoping_turn", "message": "Please run researchPrime literature sketch on arxiv papers now!"},
        )
        assert c_chat == 200
        assert not (cdir / ".anvil" / "scoping_literature_cache.json").exists()
        assert lit_calls == []

        # 3b. Word-boundary check: "dropout" in scoping_turn must NOT trigger "drop" exclusion,
        # and deterministic local quick_literature_sketch records model_calls=0, queried_url=None.
        c_dropout, p_dropout = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "scoping_turn", "message": "Inspect dropout regularization in m_core_estimator"},
        )
        assert c_dropout == 200
        assert "m_core_estimator" in p_dropout["receipt"]["selected_module_ids"]

        det_lit_c, det_lit_p = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "quick_literature_sketch", "operator_consent": True},
        )
        assert det_lit_c == 200
        assert det_lit_p["literature_sketch_receipt"]["model_calls"] == 0
        assert det_lit_p["literature_sketch_receipt"]["queried_url"] is None

        # 4. CWE-918 SSRF & Consent refusals on quick_literature_sketch
        c_noconsent, _ = _http_json(
            f"{base_url}/api/steward/anvil/scoping",
            method="POST",
            body={"action": "quick_literature_sketch", "operator_consent": False},
        )
        assert c_noconsent == 403

        for bad_url in (
            "http://api.openalex.org/works",
            "http://127.0.0.1:8777/api/status",
            "file:///C:/Windows/win.ini",
            "https://evil.example.com/works",
            "https://api.openalex.org:8443/works",
        ):
            c_ssrf, p_ssrf = _http_json(
                f"{base_url}/api/steward/anvil/scoping",
                method="POST",
                body={"action": "quick_literature_sketch", "operator_consent": True, "scholarly_url": bad_url},
            )
            assert c_ssrf == 403, f"Expected 403 for {bad_url}, got {c_ssrf}: {p_ssrf}"
            assert p_ssrf["error_code"] == "SSRF_DOMAIN_REFUSED"

        # 5. Stubbed allowlisted HTTPS call succeeds with CLAIMED / unverified stamp
        lit_res, lit_code = anvil_session.run_quick_literature_sketch(
            cdir,
            {
                "operator_consent": True,
                "scholarly_url": "https://api.openalex.org/works?search=penalized+likelihood&per-page=2",
            },
            scholarly_urlopen=_spy_urlopen,
        )
        assert lit_code == 200
        assert len(lit_calls) == 1
        rec_lit = lit_res["literature_sketch_receipt"]
        assert rec_lit["status"] == "claimed"
        assert rec_lit["posture"] == "CLAIMED"
        assert rec_lit["label"] == "CLAIMED / unverified"
        assert rec_lit["verified"] is False
        assert rec_lit["model_calls"] == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_w2_playwright_e2e_scoping_v2_xss_3layer_409_drift_ft_look_and_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live Playwright + `ft.py look --check` verification across Scoping v2 and 3-Layer Workbench:
      - Hostile XSS strings across manuscript/code/chat render as escaped text (`window.__xss_fired` falsy).
      - All Scoping v2 ship selectors present; demo switches & legacy `.`/`max_concurrency`/`16,384 B` absent.
      - All 5 `/vendor/brand/` icons load with `naturalWidth > 0`.
      - Clicking `[data-module-id]` updates the server-computed 64-hex `scope_sha256`.
      - Locking scope opens the 3-Layer Workbench (`#anvil-layer1-estimator`, `#anvil-layer2-replicators`
        with `'No replicator script matched'`, collapsed `details#anvil-layer3-plumbing`, static stamp
        `'3 static pattern classes checked; semantic math audit not run in this wave'` with zero `'Ramanujan'`).
      - `ft.py look --check` passes at BOTH desktop (`1560x960`) and phone (`390x844`).
      - Editing an in-scope `.py` file flips state to `409` scope-drifted requiring re-lock.
      - Foundry == vendor SHA-256 parity and `distro.scan_paths()` pass cleanly.
    """
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("ANCHOR_ANVIL_V6", "1")
    cdir = _build_hostile_scoping_cockpit(tmp_path, include_xss=True)
    srv, port, _th = _start_ephemeral_cockpit_http_server(cdir)
    anvil_url = f"http://127.0.0.1:{port}/steward-static/anvil.html?pid=synth_w2&name=SynthCockpit"
    look_out = tmp_path / "ft_look_w2"
    look_out.mkdir()

    try:
        # 1. Headless `ft.py look --check` on live Scoping v2 at desktop (1560x960) & phone (390x844)
        scoping_check_csv = "#doneShelf,#mainStage,#softwareMapScroll,#convScroll,#receiptCol,#btnRpToggle,#btnExpandMap,#msgBox"
        for viewport_sz in ("1560x960", "390x844"):
            proc_look = subprocess.run(
                [
                    sys.executable,
                    str(FT_PY),
                    "look",
                    anvil_url,
                    "--size",
                    viewport_sz,
                    "--wait",
                    "1200",
                    "--out",
                    str(look_out / f"scoping_{viewport_sz}"),
                    "--check",
                    scoping_check_csv,
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
            assert proc_look.returncode == 0, f"ft.py look failed at {viewport_sz}: {proc_look.stderr}\n{proc_look.stdout}"
            verdict = json.loads(proc_look.stdout)["results"][0]
            assert verdict["errors"] == [], f"Page errors at {viewport_sz}: {verdict['errors']}"
            for chk in verdict["checks"][scoping_check_csv]:
                assert chk["painted"] is True, f"Unpainted selector at {viewport_sz}: {chk}"
                assert chk["coveredBy"] is None and chk["hiddenBy"] is None, f"Obscured selector at {viewport_sz}: {chk}"

        # 2. Full Playwright interactive journey
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1560, "height": 960})
            page_errors: List[str] = []
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            page.goto(anvil_url, wait_until="networkidle")
            page.locator("#anvilScopingV2Root").wait_for(state="visible", timeout=10000)

            # Zero demo switches & zero legacy inputs
            for forbidden_sel in (
                ".proto-bar",
                "#btnStateExisting",
                "#btnStateFirst",
                "#btnPaperMoe",
                "#btnPaperHnf",
                "#inputSoftwareTarget",
                "#intakeMaxConcurrency",
                "#intakeDirectionByteCounter",
            ):
                assert page.locator(forbidden_sel).count() == 0, f"Forbidden selector rendered in v6: {forbidden_sel}"

            # Empty-but-valid message in #doneShelf
            assert "No Anvil scopes locked yet — inspect the Software & Paper Map below" in page.locator("#doneShelf").inner_text()

            # All 5 real brand icons loaded with naturalWidth > 0
            icon_widths = page.evaluate(
                """() => {
                    const imgs = Array.from(document.querySelectorAll('#anvilScopingV2Root img'));
                    const bySrc = {};
                    for (const im of imgs) {
                        const u = new URL(im.src).pathname;
                        bySrc[u] = Math.max(bySrc[u] || 0, im.naturalWidth || 0);
                    }
                    return bySrc;
                }"""
            )
            for req_icon in (
                "/vendor/brand/anvil-icon.jpg",
                "/vendor/brand/gandalf-icon.jpg",
                "/vendor/brand/research-prime-icon.jpg",
                "/vendor/brand/ramanujan-icon.jpg",
                "/vendor/brand/aladdin-seal-lamp.jpg",
            ):
                assert icon_widths.get(req_icon, 0) > 0, f"Brand icon failed to load: {req_icon} -> {icon_widths}"

            # Toggle module selection (verify opaque IDs ^[a-z0-9_-]+$) and verify server 64-hex SHA-256 updates
            sha_initial = page.locator("#receiptSha256").inner_text().strip()
            assert re.fullmatch(r"[0-9a-f]{64}", sha_initial)
            all_mod_ids = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-module-id]')).map((el) => el.getAttribute('data-module-id'))"
            )
            assert len(all_mod_ids) >= 3
            for mid_val in all_mod_ids:
                assert re.fullmatch(r"[a-z0-9_-]+", mid_val), f"Non-opaque module id in DOM: {mid_val}"
            toggle_target = page.locator('[data-module-id][aria-pressed="false"]').first
            assert toggle_target.count() == 1
            toggled_mid = toggle_target.get_attribute("data-module-id")
            assert toggled_mid
            specific_mod_btn = page.locator(f'[data-module-id="{toggled_mid}"]')
            specific_mod_btn.click()
            page.wait_for_function(
                "(prev) => { const el = document.getElementById('receiptSha256'); return el && el.textContent.trim() !== prev && /^[0-9a-f]{64}$/.test(el.textContent.trim()); }",
                arg=sha_initial,
                timeout=10000,
            )
            sha_toggled = page.locator("#receiptSha256").inner_text().strip()
            assert sha_toggled != sha_initial
            # Toggle the exact same module back off so simulations/plumbing stay excluded when locking core+replicators
            specific_mod_btn.click()
            page.wait_for_function(
                "(orig) => { const el = document.getElementById('receiptSha256'); return el && el.textContent.trim() === orig; }",
                arg=sha_initial,
                timeout=10000,
            )

            # Send hostile XSS chat message in #msgBox -> escaped text, zero execution
            xss_chat = '<img src=x onerror="window.__xss_fired=99"><script>window.__xss_fired=100</script>'
            page.locator("#msgBox").fill(xss_chat)
            page.locator("#btnSendScopingTurn").click()
            page.wait_for_function(
                "() => document.getElementById('convScroll').textContent.includes('onerror')",
                timeout=10000,
            )
            assert page.evaluate("() => window.__xss_fired") is None

            # Lock scope -> transitions to 3-Layer Workbench
            page.locator("#btnLockScope").click()
            page.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=15000)
            page.locator("#anvil-layer2-replicators").wait_for(state="visible", timeout=10000)

            l1_txt = page.locator("#anvil-layer1-estimator").inner_text()
            assert "log_likelihood" in l1_txt
            assert "dynamic_bfgs_step" in l1_txt
            assert "[uncertain]" in l1_txt
            # Statically unreached function MUST NOT appear in Layer 1 estimator bindings
            assert "abandoned_legacy_approx" not in l1_txt

            l2_txt = page.locator("#anvil-layer2-replicators").inner_text()
            assert "run_table1_eval.py" in l2_txt
            assert "No replicator script matched" in l2_txt

            # Layer 3 `<details id="anvil-layer3-plumbing">` is collapsed by default
            l3_open = page.locator("details#anvil-layer3-plumbing").evaluate("(el) => el.open")
            assert l3_open is False
            page.locator("details#anvil-layer3-plumbing > summary").click()
            assert "abandoned_legacy_approx" in page.locator("#anvil-layer3-plumbing").inner_text()

            # Dynamic static audit stamp present (4 SCI rules checked), and zero "Ramanujan" in static workbench text
            insp_txt = page.locator("#inspector-body").inner_text()
            assert "4 static pattern classes checked; semantic math audit not run in this wave" in insp_txt
            assert "semantic audit not run in this wave" in insp_txt
            assert "ramanujan" not in insp_txt.lower()
            assert page.evaluate("() => window.__xss_fired") is None
            assert page_errors == []

            # Verify "What Has Been Done" Saved-Scopes Shelf has Replication & Ramanujan Report (Not run yet) button
            page.locator("#btnOpenLauncherDrawer").click()
            page.locator("#doneShelf [data-saved-scope-card]").wait_for(state="visible", timeout=10000)
            assert "What Has Been Done" in page.locator("#doneShelf").inner_text()
            rep_btn = page.locator("#doneShelf [data-open-replication-id]")
            assert rep_btn.count() == 1
            assert "Not run yet" in rep_btn.inner_text()
            page.locator("#doneShelf [data-open-scope-id]").first.click()
            page.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=10000)

            browser.close()

        # 3. Headless `ft.py look --check` on active 3-Layer Workbench at desktop (1560x960) & phone (390x844)
        wb_check_csv = "#anvil-layer1-estimator,#anvil-layer2-replicators,#anvil-layer3-plumbing"
        for viewport_sz in ("1560x960", "390x844"):
            proc_wb_look = subprocess.run(
                [
                    sys.executable,
                    str(FT_PY),
                    "look",
                    anvil_url,
                    "--size",
                    viewport_sz,
                    "--wait",
                    "1200",
                    "--out",
                    str(look_out / f"workbench_{viewport_sz}"),
                    "--check",
                    wb_check_csv,
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
            assert proc_wb_look.returncode == 0, f"ft.py look failed on 3-layer wb at {viewport_sz}: {proc_wb_look.stderr}\n{proc_wb_look.stdout}"
            v_wb = json.loads(proc_wb_look.stdout)["results"][0]
            assert v_wb["errors"] == []
            for chk in v_wb["checks"][wb_check_csv]:
                assert chk["painted"] is True, f"Unpainted 3-layer selector at {viewport_sz}: {chk}"
                assert chk["coveredBy"] is None and chk["hiddenBy"] is None

        # 4. Also verify standalone Foundry/vendor `anvil_v4_workbench.py` + `anvil_v4_workbench.html` 3-layer export
        _prev_bc = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            v4_wb_mod = _load_module(VENDOR_ANVIL_DIR / "scripts" / "anvil_v4_workbench.py", "vendor_anvil_v4_wb_w2")
            standalone_html = tmp_path / "standalone_3layer.html"
            exp_res = v4_wb_mod.export_workbench_html(cdir, standalone_html, paper_path=cdir / "main.tex", persist=False)
        finally:
            sys.dont_write_bytecode = _prev_bc
        assert exp_res["ok"] is True
        with sync_playwright() as pw2:
            b2 = pw2.chromium.launch(headless=True)
            p2 = b2.new_page(viewport={"width": 1560, "height": 960})
            p2.goto(standalone_html.as_uri(), wait_until="load")
            p2.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=10000)
            assert "No replicator script matched" in p2.locator("#anvil-layer2-replicators").inner_text()
            assert p2.locator("details#anvil-layer3-plumbing").evaluate("(el) => el.open") is False
            assert "4 static pattern classes checked; semantic math audit not run in this wave" in p2.locator("#inspector-body").inner_text()
            assert p2.evaluate("() => window.__xss_fired") is None
            b2.close()

        # 5. Edit an in-scope file (`core_estimator.py`) -> flips state to 409 scope-drifted requiring re-lock!
        est_py = cdir / "core_estimator.py"
        est_py.write_text(est_py.read_text(encoding="utf-8") + "\n# Post-lock edit triggering 409 scope drift\n", encoding="utf-8")

        drift_code, drift_payload = _http_json(f"http://127.0.0.1:{port}/api/steward/anvil/v4_state")
        assert drift_code == 409
        assert drift_payload["scope_drifted"] is True
        assert drift_payload["error_code"] == "SCOPE_DRIFTED_409"

        with sync_playwright() as pw3:
            b3 = pw3.chromium.launch(headless=True)
            p3 = b3.new_page(viewport={"width": 1560, "height": 960})
            p3.goto(anvil_url, wait_until="networkidle")
            p3.locator('[data-scope-drifted-badge="409"]').wait_for(state="visible", timeout=10000)
            assert "409 Scope Drifted" in p3.locator("#receiptCol").inner_text()
            # Re-locking clears 409 drift and re-opens 3-Layer Workbench
            p3.locator("#btnLockScope").click()
            p3.locator("#anvil-layer1-estimator").wait_for(state="visible", timeout=15000)
            b3.close()
    finally:
        srv.shutdown()
        srv.server_close()

    # 6. Foundry == vendor SHA-256 parity + distro.scan_paths() + zero chrome-open in test code
    sync_chk = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert sync_chk.returncode == 0, f"Foundry==vendor parity check failed: {sync_chk.stdout}\n{sync_chk.stderr}"
    for rel_pair in (
        "scripts/anvil_v4_workbench.py",
        "static/anvil_v4_workbench.html",
        "scripts/anvil_v4_process.py",
        "scripts/anvil_v4_refactor.py",
    ):
        f_sha = hashlib.sha256((FOUNDRY_ANVIL_DIR / rel_pair).read_bytes()).hexdigest()
        v_sha = hashlib.sha256((VENDOR_ANVIL_DIR / rel_pair).read_bytes()).hexdigest()
        assert f_sha == v_sha, f"SHA-256 mismatch on {rel_pair}"

    w2_files = [
        VENDOR_ANVIL_DIR / "scripts" / "anvil_v4_workbench.py",
        VENDOR_ANVIL_DIR / "static" / "anvil_v4_workbench.html",
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js",
        Path(__file__).resolve(),
    ]
    scan_hits = distro.scan_paths(
        [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in w2_files],
        root=ANCHOR_ROOT,
    )
    assert scan_hits == [], f"distro.scan_paths flagged Wave 2 files: {scan_hits}"

    own_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bad_chrome = [
        node.value
        for node in ast.walk(own_tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == ("chrome-" + "open")
    ]
    assert bad_chrome == []
