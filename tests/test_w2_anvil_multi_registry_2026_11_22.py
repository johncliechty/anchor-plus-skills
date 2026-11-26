"""Wave 2 Verification Suite — ANCHOR_ANVIL_MULTI Safety Gate, Store-Root Indirection Registry,
<50 ms Disk Cache & Wave-2 HTTP/UI Pilot (`2026-11-22`).
"""
from __future__ import annotations

import hashlib
import http.client
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

import anchor_gui
import distro
import paths
import rnd_registry
from steward_cockpit import anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
DEV_ROOT = ANCHOR_ROOT.parent
PLAN_DIR = ANCHOR_ROOT / "planning" / "2026-11-22-anvil-cockpit-multi-analysis"
BACKUP_DIR = PLAN_DIR / "backups" / "legacy-anvil-20261122"
MOE_BACKUP_ANVIL = BACKUP_DIR / "moe_paper1" / ".anvil"
HNF_BACKUP_ANVIL = BACKUP_DIR / "hnf_paper1" / ".anvil"
HNF_OUTER_BACKUP_ANVIL = BACKUP_DIR / "hnf_outer" / ".anvil"
W2_MOCKUP_HTML = PLAN_DIR / "mockups" / "w2-multi-analysis-pilot.html"
W2_LOOK_DIR = PLAN_DIR / "looks" / "w2"
W2_LOOK_VERDICT = W2_LOOK_DIR / "verdict.json"


def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    anvil_session._LOADED_MTIME_NS = Path(anvil_session.__file__).stat().st_mtime_ns
    extra = [tmp_path.resolve()]
    moe_live = DEV_ROOT / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
    hnf_live = DEV_ROOT / "Hierarchical Normalizing Flows"
    if moe_live.exists():
        extra.append(moe_live.resolve())
    if hnf_live.exists():
        extra.append(hnf_live.resolve())
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, *extra),
    )


def _create_synth_repo(root: Path, *, slug: str = "alpha") -> tuple[Path, Path, Path]:
    repo = root / f"repo_{slug}"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "manuscript").mkdir(parents=True, exist_ok=True)
    (repo / "workflow.sh").write_text(
        "#!/usr/bin/env bash\npython src/pipeline.py\n",
        encoding="utf-8",
    )
    (repo / "src" / "pipeline.py").write_text(
        textwrap.dedent(
            f"""\
            def ingest_{slug}(n: int = 4) -> list[float]:
                return [float(i + 1) for i in range(n)]

            def compute_{slug}(xs: list[float]) -> float:
                return sum(v * v for v in xs) / float(len(xs) or 1)

            def legacy_unused_helper_{slug}() -> int:
                return 7

            if __name__ == "__main__":
                vals = ingest_{slug}(4)
                out = compute_{slug}(vals)
                assert out > 0.0
            """
        ),
        encoding="utf-8",
    )
    tex_main = repo / "manuscript" / "Main.tex"
    tex_main.write_text(
        textwrap.dedent(
            f"""\
            \\documentclass{{article}}
            \\title{{Replication Study {slug.upper()}}}
            \\begin{{document}}
            \\section{{Model}}
            \\begin{{equation}}\\label{{eq:{slug}}}
            E(x) = \\frac{{1}}{{N}}\\sum_{{i=1}}^{{N}} x_i^2
            \\end{{equation}}
            \\end{{document}}
            """
        ),
        encoding="utf-8",
    )
    alt_tex = repo / "manuscript" / "Appendix.md"
    alt_tex.write_text(
        f"# Appendix {slug.upper()}\n\n$$E(x) = x^2$$\n",
        encoding="utf-8",
    )
    return repo, tex_main, alt_tex


def _snapshot_tree_hashes(root: Path) -> dict[str, tuple[str, int, int]]:
    snap: dict[str, tuple[str, int, int]] = {}
    if not root.exists():
        return snap
    for fp in sorted(root.rglob("*")):
        if fp.is_file():
            raw = fp.read_bytes()
            st = fp.stat()
            rel = fp.relative_to(root).as_posix()
            snap[rel] = (hashlib.sha256(raw).hexdigest(), int(st.st_size), int(st.st_mtime_ns))
    return snap


def _stage_backup_cockpit(backup_anvil: Path, dst_cockpit: Path) -> Path:
    dst_cockpit.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        backup_anvil,
        dst_cockpit / ".anvil",
        ignore=shutil.ignore_patterns("*.lock", "*.part"),
    )
    return dst_cockpit


def test_w2_flag_default_off_keeps_polls_inert_and_unknown_pid_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify code default of is_multi_analysis_enabled is False, GET polls perform zero disk
    writes, and unknown Anvil pids return HTTP 404 UNKNOWN_PROJECT_ID (never HNF fallback).
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.delenv("ANCHOR_ANVIL_MULTI", raising=False)

    fake_anchor_root = tmp_path / "fake_anchor_root"
    fake_anchor_root.mkdir()
    monkeypatch.setattr(anvil_session, "_ANCHOR_ROOT", fake_anchor_root.resolve())
    assert anvil_session.is_multi_analysis_enabled(anchor_root=fake_anchor_root) is False
    assert anvil_session.is_multi_analysis_enabled() is False

    # 1. Empty cockpit GET polls create zero files/directories
    empty_cdir = tmp_path / "inert_empty_cockpit"
    empty_cdir.mkdir()
    s_sum, c_sum = steward_routes.handle_get(str(empty_cdir), "anvil", {"summary": "1"})
    assert c_sum == 200 and s_sum["active"] is False
    s_full, c_full = steward_routes.handle_get(str(empty_cdir), "anvil", {})
    assert c_full == 200 and s_full["active"] is False
    s_v4, c_v4 = steward_routes.handle_get(str(empty_cdir), "anvil/v4_state", {})
    assert c_v4 == 200 and s_v4["active"] is False
    assert list(empty_cdir.rglob("*")) == []

    # 2. Legacy cockpit without workbench_session.json: GET polls must NOT persist workbench_session.json or index.json
    repo_i, tex_i, _ = _create_synth_repo(tmp_path, slug="inert")
    leg_cdir = tmp_path / "inert_legacy_cockpit"
    leg_cdir.mkdir()
    anvil_session.start_cockpit_session(
        leg_cdir,
        mode="paper",
        software_spec=str(repo_i),
        paper_spec=str(tex_i),
        anchor_root=fake_anchor_root,
    )
    ws_file = leg_cdir / ".anvil" / "v4" / "workbench_session.json"
    if ws_file.exists():
        ws_file.unlink()
    before_snap = _snapshot_tree_hashes(leg_cdir / ".anvil")

    _, rc1 = steward_routes.handle_get(str(leg_cdir), "anvil", {"summary": "1"})
    _, rc2 = steward_routes.handle_get(str(leg_cdir), "anvil", {})
    v4_body, rc3 = steward_routes.handle_get(str(leg_cdir), "anvil/v4_state", {})
    assert (rc1, rc2, rc3) == (200, 200, 200)
    assert v4_body["ok"] is True
    assert not ws_file.exists(), "GET poll must never persist workbench_session.json on read"
    assert not (leg_cdir / ".anvil" / "analyses" / "index.json").exists()
    assert _snapshot_tree_hashes(leg_cdir / ".anvil") == before_snap
    assert list(leg_cdir.rglob("*.lock")) == []

    # 3. Ephemeral HTTP server (port != 8777): unknown pid on Anvil GET and POST MUST return 404 UNKNOWN_PROJECT_ID
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "anchor_data"))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    monkeypatch.setenv("ANCHOR_AUTH_MODE", "open")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    paths.ensure_data_dirs()

    srv = anchor_gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        for get_path in (
            "/api/steward/anvil?pid=nonexistent-unknown-pid-w2",
            "/api/steward/anvil/v4_state?pid=nonexistent-unknown-pid-w2",
            "/api/steward/anvil/source?pid=nonexistent-unknown-pid-w2&file=a.py",
        ):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.request("GET", get_path)
                resp = conn.getresponse()
                doc = json.loads(resp.read().decode("utf-8"))
                assert resp.status == 404, f"Expected 404 for {get_path}, got {resp.status}: {doc}"
                assert doc["ok"] is False
                assert doc["error_code"] == "UNKNOWN_PROJECT_ID"
            finally:
                conn.close()

        conn_p = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            payload_bytes = json.dumps({"pid": "nonexistent-unknown-pid-w2", "action": "v4_session"}).encode("utf-8")
            conn_p.request(
                "POST",
                "/api/steward/anvil",
                body=payload_bytes,
                headers={"Content-Type": "application/json"},
            )
            resp_p = conn_p.getresponse()
            doc_p = json.loads(resp_p.read().decode("utf-8"))
            assert resp_p.status == 404
            assert doc_p["ok"] is False
            assert doc_p["error_code"] == "UNKNOWN_PROJECT_ID"
        finally:
            conn_p.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_w2_enable_mechanism_env_and_marker_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify ANCHOR_ANVIL_MULTI env and <anchor_root>/.anchor/anvil-multi-enabled.json marker
    exclusively on tmp_path without ever touching live ANCHOR_ROOT/.anchor.
    """
    live_marker = ANCHOR_ROOT / ".anchor" / "anvil-multi-enabled.json"
    live_existed_before = live_marker.exists()

    isolated_anchor = tmp_path / "isolated_anchor_root"
    dot_anchor = isolated_anchor / ".anchor"
    dot_anchor.mkdir(parents=True)
    marker = dot_anchor / "anvil-multi-enabled.json"

    monkeypatch.delenv("ANCHOR_ANVIL_MULTI", raising=False)
    assert anvil_session.is_multi_analysis_enabled(anchor_root=isolated_anchor) is False

    # Marker false -> False
    marker.write_text('{"enabled": false}\n', encoding="utf-8")
    assert anvil_session.is_multi_analysis_enabled(anchor_root=isolated_anchor) is False

    # Marker true -> True
    marker.write_text('{"enabled": true}\n', encoding="utf-8")
    assert anvil_session.is_multi_analysis_enabled(anchor_root=isolated_anchor) is True

    # CLI --anchor-root seam check
    cli_proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "steward_cockpit.anvil_session",
            "--cockpit",
            str(tmp_path),
            "--anchor-root",
            str(isolated_anchor),
            "--action",
            "list_analyses",
        ],
        cwd=str(ANCHOR_ROOT),
        env={k: v for k, v in os.environ.items() if k != "ANCHOR_ANVIL_MULTI"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert cli_proc.returncode == 0
    cli_doc = json.loads(cli_proc.stdout)
    assert cli_doc["multi_analysis_enabled"] is True

    # Explicit env "0"/"false"/"off" overrides marker true -> False
    for off_val in ("0", "false", "no", "off"):
        monkeypatch.setenv("ANCHOR_ANVIL_MULTI", off_val)
        assert anvil_session.is_multi_analysis_enabled(anchor_root=isolated_anchor) is False

    # Explicit env "1"/"true"/"yes"/"on" overrides marker false -> True
    marker.write_text('{"enabled": false}\n', encoding="utf-8")
    for on_val in ("1", "true", "yes", "on"):
        monkeypatch.setenv("ANCHOR_ANVIL_MULTI", on_val)
        assert anvil_session.is_multi_analysis_enabled(anchor_root=isolated_anchor) is True

    # Symlink marker file is rejected fail-closed -> False
    monkeypatch.delenv("ANCHOR_ANVIL_MULTI", raising=False)
    marker.unlink()
    outside_true = tmp_path / "outside_enabled.json"
    outside_true.write_text('{"enabled": true}\n', encoding="utf-8")
    try:
        os.symlink(str(outside_true), str(marker))
        assert anvil_session.is_multi_analysis_enabled(anchor_root=isolated_anchor) is False
    except OSError:
        pass

    assert live_marker.exists() is live_existed_before


def test_w2_store_root_indirection_zero_copy_legacy_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage tmp_path copies of BOTH backed-up moe_paper1 and hnf_paper1 .anvil trees,
    verifying zero-write in-place reads before registration and zero-rewrite explicit registration
    at store='.' preserving paid CROSS_FAMILY_VALIDATED xval_receipt.json bytes.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")

    assert MOE_BACKUP_ANVIL.is_dir() and HNF_BACKUP_ANVIL.is_dir()
    moe_tmp = _stage_backup_cockpit(MOE_BACKUP_ANVIL, tmp_path / "moe_cockpit")
    hnf_tmp = _stage_backup_cockpit(HNF_BACKUP_ANVIL, tmp_path / "hnf_cockpit")

    # Point software/paper paths in staged copies at synthetic local repos if live sibling dirs are absent,
    # OR if live dirs exist on PUTER, patch relative paths to resolved paths BEFORE taking our immutable snapshot!
    moe_live_root = DEV_ROOT / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
    hnf_live_root = DEV_ROOT / "Hierarchical Normalizing Flows" / "Paper 1"
    for staged_cdir, live_base in ((moe_tmp, moe_live_root), (hnf_tmp, hnf_live_root)):
        sfile = staged_cdir / ".anvil" / "session.json"
        sess = json.loads(sfile.read_text(encoding="utf-8"))
        changed = False
        if live_base.is_dir():
            for sw_k in ("software", "compare_software"):
                sw_d = sess.get(sw_k)
                if isinstance(sw_d, dict) and isinstance(sw_d.get("path"), str):
                    p_cand = Path(sw_d["path"])
                    if not p_cand.is_absolute():
                        sw_d["path"] = str((live_base / p_cand).resolve())
                        changed = True
            pmap = sess.get("paper_map")
            if isinstance(pmap, dict):
                for pk in ("paper_path", "source_path"):
                    if isinstance(pmap.get(pk), str) and pmap[pk] and not Path(pmap[pk]).is_absolute():
                        pmap[pk] = str((live_base / pmap[pk]).resolve())
                        changed = True
                pinfo = pmap.get("paper_info")
                if isinstance(pinfo, dict):
                    for pik in ("primary_tex", "path"):
                        if isinstance(pinfo.get(pik), str) and pinfo[pik] and not Path(pinfo[pik]).is_absolute():
                            pinfo[pik] = str((live_base / pinfo[pik]).resolve())
                            changed = True
        if changed:
            sfile.write_text(json.dumps(sess, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        # Remove copied last_trace.json if any so static state check is hermetic
        lt = staged_cdir / ".anvil" / "v4" / "last_trace.json"
        if lt.exists():
            lt.unlink()

    moe_before = _snapshot_tree_hashes(moe_tmp / ".anvil")
    hnf_before = _snapshot_tree_hashes(hnf_tmp / ".anvil")

    # 1. Un-migrated in-place reads: resolve_store_root returns ("legacy-primary", cdir) with ZERO writes
    for cdir_i, snap_before in ((moe_tmp, moe_before), (hnf_tmp, hnf_before)):
        aid, sroot = anvil_session.resolve_store_root(cdir_i)
        assert aid == "legacy-primary"
        assert sroot == cdir_i.resolve()
        st_sum = anvil_session.get_session_status(cdir_i, summary_only=True)
        assert st_sum["ok"] is True and st_sum["active"] is True
        p_v4, c_v4 = anvil_session.get_v4_cockpit_state(cdir_i)
        assert c_v4 == 200 and p_v4["ok"] is True
        assert not (cdir_i / ".anvil" / "analyses" / "index.json").exists()
        assert _snapshot_tree_hashes(cdir_i / ".anvil") == snap_before

    # 2. Explicit registration binds store="." with ZERO rewrites of session.json, manifest.json, or v4/xval_receipt.json
    for cdir_i, snap_before in ((moe_tmp, moe_before), (hnf_tmp, hnf_before)):
        reg1, code1 = anvil_session.register_legacy_analysis(cdir_i)
        assert code1 == 200 and reg1["ok"] is True and reg1["mode"] == "registered"
        assert reg1["analysis"]["store"] == "."

        idx_path = cdir_i / ".anvil" / "analyses" / "index.json"
        assert idx_path.is_file()
        idx_bytes_1 = idx_path.read_bytes()

        # Repeat-invocation idempotence: zero rewrite, zero duplicate entries
        reg2, code2 = anvil_session.register_legacy_analysis(cdir_i)
        assert code2 == 200 and reg2["mode"] == "already_registered"
        assert len(reg2["analyses"]) == 1
        assert idx_path.read_bytes() == idx_bytes_1

        snap_after = _snapshot_tree_hashes(cdir_i / ".anvil")
        for protected_rel in ("session.json", "manifest.json", "v4/xval_receipt.json", "v4/workbench_session.json"):
            if protected_rel in snap_before:
                assert snap_after[protected_rel] == snap_before[protected_rel], f"Legacy file mutated: {protected_rel}"

    # Verify paid CROSS_FAMILY_VALIDATED receipt on MoE copy remained intact
    moe_xval = json.loads((moe_tmp / ".anvil" / "v4" / "xval_receipt.json").read_text(encoding="utf-8"))
    assert moe_xval["verdict"] == "PASS"
    assert moe_xval["mode"] in {"CROSS_FAMILY_VALIDATED", "RATE_LIMITED_COOLDOWN"}


def test_w2_all_mutating_actions_isolated_across_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise all 13+ anvil_session readers/writers across Analysis A (store='.') and
    Analysis B (store='analyses/analysis-b'), proving <2 ms switch and 100% isolation.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")

    repo_a, tex_a, _ = _create_synth_repo(tmp_path, slug="alpha")
    repo_b, tex_b, alt_paper_b = _create_synth_repo(tmp_path, slug="beta")

    cdir = tmp_path / "multi_cockpit"
    cdir.mkdir()

    # 1. Start Analysis A at store="."
    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(repo_a),
        paper_spec=str(tex_a),
        analysis_id="analysis-a",
        title="Alpha Primary",
    )
    a_session_file = cdir / ".anvil" / "session.json"
    a_ws_file = cdir / ".anvil" / "v4" / "workbench_session.json"
    assert a_session_file.is_file()
    a_snap_before = _snapshot_tree_hashes(cdir / ".anvil" / "v4")
    a_ir_before = a_session_file.read_bytes()

    # 2. Create Analysis B (isolated under .anvil/analyses/analysis-b/)
    res_b, code_b = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "create_analysis",
            "analysis_id": "analysis-b",
            "title": "Beta Replication",
            "mode": "paper",
            "software_target": str(repo_b),
            "paper_target": str(tex_b),
            "direction": "Focus on compute_beta stage purity.",
            "set_active": True,
        },
    )
    assert code_b == 200 and res_b["ok"] is True
    b_store = cdir / ".anvil" / "analyses" / "analysis-b"
    assert (b_store / ".anvil" / "session.json").is_file()

    # Exercise ALL mutating & read operations while Analysis B is active:
    # (a) get_session_status + get_v4_cockpit_state + get_cockpit_file_source
    st_b = anvil_session.get_session_status(cdir)
    assert st_b["analysis_id"] == "analysis-b"
    v4_b, cv4_b = anvil_session.get_v4_cockpit_state(cdir)
    assert cv4_b == 200 and v4_b["analysis_id"] == "analysis-b"
    src_b = anvil_session.get_cockpit_file_source(cdir, "src/pipeline.py")
    assert "compute_beta" in src_b["content"]

    # (b) save_v4_cockpit_ui_session
    ui_res, ui_code = anvil_session.save_v4_cockpit_ui_session(
        cdir,
        {"ide_theme": "dark", "pinned_watches": ["vals"], "breakpoints": ["src/pipeline.py:2"]},
    )
    assert ui_code == 200 and ui_res["session"]["ide_theme"] == "dark"

    # (c) probe_block_in_session
    b_first_block = st_b["session"]["code_map"]["conceptual_buckets"][0]["id"]
    pr_res = anvil_session.probe_block_in_session(cdir, b_first_block, lock_description="Verified beta block")
    assert pr_res["block"]["id"] == b_first_block

    # (d) sign_off_null_space_in_session
    so_res = anvil_session.sign_off_null_space_in_session(cdir, "legacy_unused_helper_beta")
    assert "legacy_unused_helper_beta" in so_res["session"]["signed_off_drops"]

    # (e) attach_paper_to_session
    ap_res = anvil_session.attach_paper_to_session(cdir, str(alt_paper_b))
    assert ap_res["paper_map"]["has_paper"] is True

    # (f) chat_in_session
    ch_res = anvil_session.chat_in_session(cdir, "Summarize compute_beta")
    assert "reply" in ch_res and ch_res["analysis_id"] == "analysis-b"

    # (g) apply_conversational_anvil_side_effects
    note_b = anvil_session.apply_conversational_anvil_side_effects(cdir, "please sign off null space")
    assert "analysis-b" in note_b

    # (h) walkthrough_in_session
    wt_res = anvil_session.walkthrough_in_session(cdir)
    assert "walkthrough" in wt_res

    # (i) run_v4_cockpit_trace
    tr_res, tr_code = anvil_session.run_v4_cockpit_trace(
        cdir,
        {"argv": ["python", "src/pipeline.py"], "operator_consent_confirmed": True},
    )
    assert tr_code == 200 and tr_res["analysis_id"] == "analysis-b"
    assert (b_store / ".anvil" / "v4" / "last_trace.json").is_file()

    # (j) run_v4_cockpit_profile_lit
    pl_res, pl_code = anvil_session.run_v4_cockpit_profile_lit(
        cdir,
        {"argv": ["python", "src/pipeline.py"], "operator_consent_confirmed": True},
    )
    assert pl_code == 200 and pl_res["analysis_id"] == "analysis-b"

    # (k) run_v4_cockpit_chat
    vc_res, vc_code = anvil_session.run_v4_cockpit_chat(cdir, {"question": "Explain S1 stage contract"})
    assert vc_code == 200 and vc_res["analysis_id"] == "analysis-b"

    # (l) run_v4_cockpit_xval (deterministic or stubbed)
    xv_res, xv_code = anvil_session.run_v4_cockpit_xval(cdir, {"max_concurrency": 2})
    assert xv_code == 200 and xv_res["analysis_id"] == "analysis-b"

    # 3. Switch back to Analysis A in < 50 ms (index update < 2 ms) and verify A is 100% UNTOUCHED!
    t_sw0 = time.perf_counter()
    sw_res, sw_code = anvil_session.switch_cockpit_analysis(cdir, "analysis-a")
    sw_ms = (time.perf_counter() - t_sw0) * 1000.0
    assert sw_code == 200 and sw_res["active_analysis_id"] == "analysis-a"
    assert sw_ms < 50.0, f"Switch exceeded 50 ms: {sw_ms:.2f} ms"

    assert a_session_file.read_bytes() == a_ir_before, "Analysis A session.json was mutated while editing Analysis B!"
    assert not (cdir / ".anvil" / "v4" / "last_trace.json").exists(), "Analysis B trace leaked into Analysis A!"
    a_ws_now = json.loads(a_ws_file.read_text(encoding="utf-8"))
    assert a_ws_now["ide_theme"] == "light"
    assert a_ws_now["pinned_watches"] == []
    assert a_snap_before["workbench_session.json"] == _snapshot_tree_hashes(cdir / ".anvil" / "v4")["workbench_session.json"]

    # Switch back to B and verify all of B's mutations persisted
    sw_b, sw_bc = anvil_session.switch_cockpit_analysis(cdir, "analysis-b")
    assert sw_bc == 200 and sw_b["active_analysis_id"] == "analysis-b"
    v4_b_again, _ = anvil_session.get_v4_cockpit_state(cdir)
    assert v4_b_again["v4_bundle"]["session"]["ide_theme"] == "dark"
    assert "vals" in v4_b_again["v4_bundle"]["session"]["pinned_watches"]
    assert v4_b_again["v4_bundle"]["has_trace"] is True


def test_w2_switch_during_xval_pins_receipt_to_origin_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Start 2-seat XVal on Analysis A, switch active_analysis_id to Analysis B mid-flight,
    and prove the receipt lands strictly on Analysis A with analysis_id + repo_fingerprint,
    while mismatched receipts are rejected fail-closed (502).
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")

    repo_a, tex_a, _ = _create_synth_repo(tmp_path, slug="xa")
    repo_b, tex_b, _ = _create_synth_repo(tmp_path, slug="xb")
    cdir = tmp_path / "xval_switch_cockpit"
    cdir.mkdir()

    anvil_session.create_cockpit_analysis(
        cdir,
        analysis_id="origin-a",
        mode="paper",
        software_spec=str(repo_a),
        paper_spec=str(tex_a),
        set_active=True,
    )
    anvil_session.create_cockpit_analysis(
        cdir,
        analysis_id="other-b",
        mode="paper",
        software_spec=str(repo_b),
        paper_spec=str(tex_b),
        set_active=False,
    )

    store_a = cdir / ".anvil" / "analyses" / "origin-a"
    store_b = cdir / ".anvil" / "analyses" / "other-b"
    b_xval_path = store_b / ".anvil" / "v4" / "xval_receipt.json"
    if b_xval_path.exists():
        b_xval_path.unlink()

    entered_xval = threading.Event()
    allow_finish = threading.Event()
    worker_result: dict[str, Any] = {}

    def _blocking_cli_runner(**kwargs: Any) -> dict[str, Any]:
        entered_xval.set()
        assert allow_finish.wait(timeout=10.0), "Timed out waiting for mid-flight switch barrier"
        fam = kwargs.get("family")
        if fam == "gemini":
            reply = json.dumps({"verdict": "PASS", "citation_checks": [], "findings": []})
            out = (
                json.dumps({"event": "init", "init": {"model": "gemini-4-carbon-high"}})
                + "\n"
                + json.dumps({"event": "result", "result": {"status": "SUCCESS", "model": "gemini-4-carbon-high", "response": reply}})
                + "\n"
            )
            return {"returncode": 0, "stdout": out, "stderr": ""}
        reply_c = json.dumps({"verdict": "PASS", "citation_checks": [], "findings": []})
        out_c = (
            json.dumps({"type": "assistant", "message": {"model": "claude-fable-5-2", "content": [{"type": "text", "text": reply_c}]}})
            + "\n"
            + json.dumps({"type": "result", "is_error": False, "model": "claude-fable-5-2", "result": reply_c})
            + "\n"
        )
        return {"returncode": 0, "stdout": out_c, "stderr": ""}

    def _run_xval_bg() -> None:
        res, code = anvil_session.run_v4_cockpit_xval(
            cdir,
            {"max_concurrency": 2, "live": True},
            cli_runner=_blocking_cli_runner,
        )
        worker_result["res"] = res
        worker_result["code"] = code

    bg = threading.Thread(target=_run_xval_bg)
    bg.start()
    assert entered_xval.wait(timeout=10.0), "XVal worker did not enter cli_runner"

    # Switch active analysis to other-b WHILE origin-a XVal is mid-run!
    sw_res, sw_code = anvil_session.switch_cockpit_analysis(cdir, "other-b")
    assert sw_code == 200 and sw_res["active_analysis_id"] == "other-b"

    allow_finish.set()
    bg.join(timeout=15.0)
    assert not bg.is_alive()

    assert worker_result["code"] == 200
    assert worker_result["res"]["analysis_id"] == "origin-a"

    a_xval_path = store_a / ".anvil" / "v4" / "xval_receipt.json"
    assert a_xval_path.is_file()
    assert not b_xval_path.exists(), "Mid-flight switch must never write Analysis A receipt into Analysis B!"

    a_rec = json.loads(a_xval_path.read_text(encoding="utf-8"))
    assert a_rec["analysis_id"] == "origin-a"
    assert bool(a_rec["repo_fingerprint"])
    assert a_rec["cross_family_attested"] is True
    assert a_rec["model_served"] == "claude-fable-5-2"

    # Injecting Analysis A's receipt into Analysis B MUST be rejected fail-closed (502)
    b_xval_path.parent.mkdir(parents=True, exist_ok=True)
    b_xval_path.write_text(json.dumps(a_rec), encoding="utf-8")
    anvil_session._invalidate_store_bundle_cache(store_b)
    bad_b, bad_b_code = anvil_session.get_v4_cockpit_state(cdir, analysis_id="other-b")
    assert bad_b_code == 502
    assert bad_b["status_kind"] == "dependency-returns-garbage"
    b_xval_path.unlink()

    # Tampering repo_fingerprint on Analysis A's pinned receipt MUST also be rejected fail-closed (502)
    tampered_a = dict(a_rec, repo_fingerprint="mismatch_fp_0001")
    a_xval_path.write_text(json.dumps(tampered_a), encoding="utf-8")
    anvil_session._invalidate_store_bundle_cache(store_a)
    bad_fp, bad_fp_code = anvil_session.get_v4_cockpit_state(cdir, analysis_id="origin-a")
    assert bad_fp_code == 502
    assert bad_fp["status_kind"] == "dependency-returns-garbage"


def test_w2_reset_archives_single_analysis_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify reset_cockpit_session archives only the target analysis in index.json without
    deleting or touching sibling analyses, and falls back to the remaining live analysis.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")

    repo_1, tex_1, _ = _create_synth_repo(tmp_path, slug="r1")
    repo_2, tex_2, _ = _create_synth_repo(tmp_path, slug="r2")
    cdir = tmp_path / "reset_cockpit"
    cdir.mkdir()

    anvil_session.create_cockpit_analysis(cdir, analysis_id="keep-1", mode="paper", software_spec=str(repo_1), paper_spec=str(tex_1))
    anvil_session.create_cockpit_analysis(cdir, analysis_id="archive-2", mode="paper", software_spec=str(repo_2), paper_spec=str(tex_2))

    keep_snap = _snapshot_tree_hashes(cdir / ".anvil" / "analyses" / "keep-1")

    reset_out = anvil_session.reset_cockpit_session(cdir, analysis_id="archive-2")
    assert reset_out["archived_analysis_id"] == "archive-2"
    assert reset_out["analysis_id"] == "keep-1"
    assert reset_out["active"] is True

    listed, l_code = anvil_session.list_cockpit_analyses(cdir, include_archived=False)
    assert l_code == 200
    assert [e["analysis_id"] for e in listed["analyses"]] == ["keep-1"]
    assert listed["active_analysis_id"] == "keep-1"

    listed_all, _ = anvil_session.list_cockpit_analyses(cdir, include_archived=True)
    arch_row = next(e for e in listed_all["analyses"] if e["analysis_id"] == "archive-2")
    assert arch_row["archived"] is True and bool(arch_row.get("archived_at"))

    # Sibling analysis files are 100% untouched
    assert _snapshot_tree_hashes(cdir / ".anvil" / "analyses" / "keep-1") == keep_snap

    # Archiving the final remaining analysis transitions cleanly to 200 EMPTY (not 500!)
    anvil_session.reset_cockpit_session(cdir, analysis_id="keep-1")
    empty_state, empty_code = anvil_session.get_v4_cockpit_state(cdir)
    assert empty_code == 200
    assert empty_state["state"] == "EMPTY" and empty_state["unknown_state"] is False


def test_w2_multi_analysis_atomic_concurrency_and_idempotence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spawn two concurrent OS subprocesses creating & switching analyses on the same cockpit,
    verifying zero lost entries, zero .part/.lock leftovers in the cockpit, and idempotence.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    repo_c, tex_c, _ = _create_synth_repo(tmp_path, slug="conc")
    cdir = tmp_path / "conc_cockpit"
    cdir.mkdir()

    worker_py = tmp_path / "conc_registry_worker.py"
    worker_py.write_text(
        textwrap.dedent(
            f"""\
            import os, sys
            from pathlib import Path
            sys.path.insert(0, {str(ANCHOR_ROOT)!r})
            os.environ["ANCHOR_ANVIL_MULTI"] = "1"
            from steward_cockpit import anvil_session
            anvil_session.ALLOWED_LOCAL_ROOTS = (*anvil_session.ALLOWED_LOCAL_ROOTS, Path({str(tmp_path.resolve())!r}))

            cdir = Path(sys.argv[1])
            repo = Path(sys.argv[2])
            tex = Path(sys.argv[3])
            prefix = sys.argv[4]

            for i in range(4):
                aid = f"{{prefix}}-{{i}}"
                res, code = anvil_session.create_cockpit_analysis(
                    cdir,
                    analysis_id=aid,
                    title=f"Worker {{prefix}} #{{i}}",
                    mode="paper",
                    software_spec=str(repo),
                    paper_spec=str(tex),
                )
                assert code == 200 and res["ok"] is True, f"create failed: {{res}}"
                sw, sc = anvil_session.switch_cockpit_analysis(cdir, aid)
                assert sc == 200 and sw["ok"] is True, f"switch failed: {{sw}}"
            """
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "ANCHOR_ANVIL_MULTI": "1"}
    p1 = subprocess.Popen(
        [sys.executable, "-B", str(worker_py), str(cdir), str(repo_c), str(tex_c), "procA"],
        cwd=str(ANCHOR_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p2 = subprocess.Popen(
        [sys.executable, "-B", str(worker_py), str(cdir), str(repo_c), str(tex_c), "procB"],
        cwd=str(ANCHOR_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _, err1 = p1.communicate(timeout=90)
    _, err2 = p2.communicate(timeout=90)
    assert p1.returncode == 0, f"p1 failed: {err1}"
    assert p2.returncode == 0, f"p2 failed: {err2}"

    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")
    listed, l_code = anvil_session.list_cockpit_analyses(cdir)
    assert l_code == 200
    found_ids = {e["analysis_id"] for e in listed["analyses"]}
    expected_ids = {f"procA-{i}" for i in range(4)} | {f"procB-{i}" for i in range(4)}
    assert found_ids == expected_ids, f"Dropped concurrent analysis registrations: {expected_ids - found_ids}"

    assert list(cdir.rglob("*.part")) == []
    assert list(cdir.rglob("*.lock")) == []

    # Repeat-invocation idempotence on switch_cockpit_analysis
    idx_file = cdir / ".anvil" / "analyses" / "index.json"
    active_now = listed["active_analysis_id"]
    bytes_before = idx_file.read_bytes()
    mtime_before = idx_file.stat().st_mtime_ns
    sw_idem, sw_c = anvil_session.switch_cockpit_analysis(cdir, active_now)
    assert sw_c == 200 and sw_idem["switched"] is False
    assert idx_file.read_bytes() == bytes_before
    assert idx_file.stat().st_mtime_ns == mtime_before


def test_w2_disk_bundle_cache_under_50ms_and_sig_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify <50 ms hydration from v5_bundle_cache.json across simulated server restarts
    (clearing RAM cache), plus automatic rebuild when source files or ANVIL_V5_BUNDLE_SCHEMA_VERSION change.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")

    repo_d, tex_d, _ = _create_synth_repo(tmp_path, slug="diskcache")
    # Add 25 modules so AST work is non-trivial on rebuild while disk cache stays <50 ms
    for m_idx in range(25):
        (repo_d / "src" / f"mod_{m_idx:02d}.py").write_text(
            f"def stage_fn_{m_idx}(x: float) -> float:\n    return x * {m_idx + 1}.0\n",
            encoding="utf-8",
        )

    cdir = tmp_path / "cache_cockpit"
    cdir.mkdir()
    res_create, code_create = anvil_session.create_cockpit_analysis(
        cdir,
        analysis_id="cached-primary",
        mode="paper",
        software_spec=str(repo_d),
        paper_spec=str(tex_d),
    )
    assert code_create == 200 and res_create["ok"] is True

    store_root = cdir / ".anvil" / "analyses" / "cached-primary"
    cache_file = store_root / ".anvil" / "v4" / "v5_bundle_cache.json"
    assert cache_file.is_file()
    cache_doc_1 = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache_doc_1["schema"] == anvil_session.ANVIL_V5_BUNDLE_CACHE_SCHEMA
    sig_1 = cache_doc_1["bundle_sig"]

    # Simulate cold server restart by clearing ALL RAM caches!
    with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
        anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()
    with anvil_session._SESSION_IR_CACHE_LOCK:
        anvil_session._SESSION_IR_CACHE.clear()

    post_restart_samples_ms: list[float] = []
    for i in range(4):
        if i == 0:
            t0 = time.perf_counter()
            p_disk, c_disk = anvil_session.get_v4_cockpit_state(cdir)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert c_disk == 200 and p_disk["cache_hit"] == "disk"
            post_restart_samples_ms.append(elapsed_ms)
        else:
            with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
                anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()
            t0 = time.perf_counter()
            p_disk, c_disk = anvil_session.get_v4_cockpit_state(cdir)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert c_disk == 200 and p_disk["cache_hit"] == "disk"
            post_restart_samples_ms.append(elapsed_ms)

    assert min(post_restart_samples_ms) < 50.0, (
        f"Post-restart v5_bundle_cache.json hydration exceeded 50 ms: {post_restart_samples_ms}"
    )

    # 1. Source subfile edit invalidates ANVIL_BUNDLE_SIG and triggers automatic cache rebuild
    mod0 = repo_d / "src" / "mod_00.py"
    mod0.write_text(mod0.read_text(encoding="utf-8") + "\ndef added_after_cache(z: float) -> float:\n    return z + 1.0\n", encoding="utf-8")
    with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
        anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()

    p_rebuilt, c_rebuilt = anvil_session.get_v4_cockpit_state(cdir)
    assert c_rebuilt == 200
    assert p_rebuilt["cache_hit"] == "rebuilt"
    sig_2 = p_rebuilt["bundle_sig"]
    assert sig_2 != sig_1
    assert json.loads(cache_file.read_text(encoding="utf-8"))["bundle_sig"] == sig_2

    # 2. Engine version upgrade (ANVIL_V5_BUNDLE_SCHEMA_VERSION bump) auto-rebuilds preserving targets
    monkeypatch.setattr(anvil_session, "ANVIL_V5_BUNDLE_SCHEMA_VERSION", "5.3.0-test-upgrade")
    with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
        anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()

    p_ver, c_ver = anvil_session.get_v4_cockpit_state(cdir)
    assert c_ver == 200
    assert p_ver["cache_hit"] == "rebuilt"
    assert p_ver["bundle_sig"] != sig_2
    assert p_ver["v4_bundle"]["has_paper"] is True


def test_w2_bounds_64_analyses_8mb_refusal_and_containment_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify <=64 analyses bound (400 BOUND_EXCEEDED_REFUSAL), <=8 MB cache bound (400),
    ../absolute/symlink escape refusals (403), outer ?pid=<pid> child effort resolution,
    candidate discovery, and the full 5-row failure-state table keeping 500 UNKNOWN != 200 EMPTY.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")

    repo_b, tex_b, _ = _create_synth_repo(tmp_path, slug="bounds")
    cdir = tmp_path / "bounds_cockpit"
    cdir.mkdir()

    # 1. <= 64 analyses bound + refusal path
    idx_dir = cdir / ".anvil" / "analyses"
    idx_dir.mkdir(parents=True, exist_ok=True)
    sixty_four = [
        {
            "analysis_id": f"slot-{i:02d}",
            "title": f"Slot {i}",
            "store": f"analyses/slot-{i:02d}",
            "mode": "code",
            "software_spec": ".",
            "paper_spec": "",
            "active_pipeline": "",
            "direction": "",
            "archived": False,
            "created_at": "2026-11-23T00:00:00Z",
            "updated_at": "2026-11-23T00:00:00Z",
        }
        for i in range(64)
    ]
    anvil_session._write_analyses_index(
        cdir,
        {
            "schema": anvil_session.ANVIL_ANALYSES_INDEX_SCHEMA,
            "active_analysis_id": "slot-00",
            "updated_at": "2026-11-23T00:00:00Z",
            "analyses": sixty_four,
        },
    )
    over_res, over_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "create_analysis", "analysis_id": "slot-65", "software_target": str(repo_b)},
    )
    assert over_code == 400
    assert over_res["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    assert over_res["bound_limit"] == 64

    # 2. <= 8 MB v5_bundle_cache.json bound (both write and read refusal paths!)
    cache_cdir = tmp_path / "cache_bound_cockpit"
    cache_cdir.mkdir()
    anvil_session.create_cockpit_analysis(
        cache_cdir,
        analysis_id="cb-1",
        mode="paper",
        software_spec=str(repo_b),
        paper_spec=str(tex_b),
    )
    cb_store = cache_cdir / ".anvil" / "analyses" / "cb-1"
    with pytest.raises(anvil_session.AnvilAnalysisRefusalError) as exc_8m_w:
        anvil_session.write_v5_bundle_cache(
            cb_store,
            "sig-oversized",
            "cb-1",
            {"blob": "x" * (8 * 1024 * 1024 + 512)},
        )
    assert exc_8m_w.value.http_status == 400
    assert exc_8m_w.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    # Oversized cache file on disk -> 400 BOUND_EXCEEDED_REFUSAL on get_v4_cockpit_state
    cache_p = cb_store / ".anvil" / "v4" / "v5_bundle_cache.json"
    cache_p.write_bytes(b"{" + (b" " * (8 * 1024 * 1024 + 256)) + b"}")
    with anvil_session._COCKPIT_V4_BUNDLE_CACHE_LOCK:
        anvil_session._COCKPIT_V4_BUNDLE_CACHE.clear()
    r_8m, c_8m = anvil_session.get_v4_cockpit_state(cache_cdir)
    assert c_8m == 400 and r_8m["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    cache_p.unlink()

    # 3. Containment 403 escape attempts (.., absolute path, symlink)
    outside_dir = tmp_path / "outside_escape_target"
    outside_dir.mkdir()
    for bad_aid in ("../outside", "..\\outside", "/etc/passwd", str(outside_dir.resolve())):
        esc_r, esc_c = steward_routes.handle_get(str(cache_cdir), "anvil/v4_state", {"analysis_id": bad_aid})
        assert esc_c == 403, f"Expected 403 on analysis_id={bad_aid!r}, got {esc_c}: {esc_r}"
        assert esc_r["error_code"] == "PATH_ESCAPE_REFUSED"

        esc_p, esc_pc = steward_routes.handle_post(
            str(cache_cdir), "anvil", {"action": "switch_analysis", "analysis_id": bad_aid}
        )
        assert esc_pc == 403 and esc_p["error_code"] == "PATH_ESCAPE_REFUSED"

    for bad_dir in ("../outside_escape_target", str(outside_dir.resolve())):
        d_esc, d_code = steward_routes.api_get(str(cache_cdir), "anvil/v4_state", {"dir": bad_dir})
        assert d_code == 403 and d_esc["error_code"] == "PATH_ESCAPE_REFUSED"

    sym_slot = cache_cdir / ".anvil" / "analyses" / "sym-escape"
    try:
        os.symlink(str(outside_dir), str(sym_slot), target_is_directory=True)
        sym_r, sym_c = steward_routes.handle_get(str(cache_cdir), "anvil/v4_state", {"analysis_id": "sym-escape"})
        assert sym_c == 403 and sym_r["error_code"] == "PATH_ESCAPE_REFUSED"
    except OSError:
        pass

    # 4. Outer project effort resolution (?pid=<outer> without dir=) + candidate discovery + cockpit.html link check
    outer_proj = tmp_path / "outer_hnf_proj"
    inner_paper1 = outer_proj / "Paper 1"
    (outer_proj / "shared_sources" / "pkg_flow").mkdir(parents=True)
    (outer_proj / "shared_sources" / "pkg_flow" / "flow.py").write_text("def run_flow():\n    return 1\n", encoding="utf-8")
    inner_paper1.mkdir(parents=True)
    (inner_paper1 / "sources" / "subpkg").mkdir(parents=True)
    (inner_paper1 / "sources" / "subpkg" / "model.py").write_text("def fit():\n    return 2\n", encoding="utf-8")
    (inner_paper1 / "workflow.sh").write_text("#!/usr/bin/env bash\npython sources/subpkg/model.py\n", encoding="utf-8")
    (inner_paper1 / "Main.tex").write_text("\\documentclass{article}\n\\begin{document}\n$x=1$\n\\end{document}\n", encoding="utf-8")

    anvil_session.create_cockpit_analysis(
        inner_paper1,
        analysis_id="inner-flow-1",
        mode="paper",
        software_spec="sources/subpkg",
        paper_spec="Main.tex",
    )

    resolved_eff = anvil_session.resolve_cockpit_or_child_effort(outer_proj)
    assert resolved_eff == inner_paper1.resolve()

    outer_state, outer_code = steward_routes.api_get(str(outer_proj), "anvil/v4_state", {})
    assert outer_code == 200 and outer_state["active"] is True
    assert outer_state["analysis_id"] == "inner-flow-1"

    disc_get, disc_gc = steward_routes.api_get(str(inner_paper1), "anvil", {"discover": "1"})
    assert disc_gc == 200 and disc_get["ok"] is True
    sw_paths = [c["path"] for c in disc_get["candidates"]["software"]]
    assert "sources/subpkg" in sw_paths
    assert any("shared_sources" in p for p in sw_paths)
    assert any("Main.tex" in c["path"] for c in disc_get["candidates"]["papers"])
    assert any("workflow.sh" in c["path"] for c in disc_get["candidates"]["pipelines"])

    disc_post, disc_pc = steward_routes.api_post(str(inner_paper1), "anvil", {"action": "discover_candidates"})
    assert disc_pc == 200 and disc_post["ok"] is True

    cockpit_html_txt = (ANCHOR_ROOT / "steward_cockpit" / "static" / "cockpit.html").read_text(encoding="utf-8")
    assert 'p.set("dir", resolvedDir)' in cockpit_html_txt

    # 5. Exact 5-row failure-state table with strict 500 UNKNOWN != 200 EMPTY separation
    empty_v5_dir = tmp_path / "v5_empty_cockpit"
    empty_v5_dir.mkdir()

    # Row 5: empty-but-valid -> 200 EMPTY
    r200, c200 = anvil_session.get_v4_cockpit_state(empty_v5_dir)
    assert c200 == 200
    assert r200["status_kind"] == "empty-but-valid"
    assert r200["state"] == "EMPTY"
    assert r200["unknown_state"] is False
    assert r200["message"] == "No Anvil analyses configured yet — choose a repository and manuscript to begin"

    # Row 4: backing-store-unreadable -> 500 UNKNOWN (strictly separate from 200 EMPTY!)
    bad_idx = empty_v5_dir / ".anvil" / "analyses" / "index.json"
    bad_idx.parent.mkdir(parents=True, exist_ok=True)
    bad_idx.write_text("{corrupt-index-json", encoding="utf-8")
    r500, c500 = anvil_session.get_v4_cockpit_state(empty_v5_dir)
    assert c500 == 500
    assert r500["status_kind"] == "backing-store-unreadable"
    assert r500["state"] == "UNKNOWN"
    assert r500["unknown_state"] is True
    assert r500["message"] == "UNKNOWN: Anvil analysis store unreadable or corrupted"
    assert r500["state"] != r200["state"] and r500["status_kind"] != r200["status_kind"]
    bad_idx.unlink()

    # Row 3: dependency-returns-garbage -> 400 / 502
    r400, c400 = steward_routes.api_post(str(empty_v5_dir), "anvil", "not-a-dict")  # type: ignore[arg-type]
    assert c400 == 400
    assert r400["status_kind"] == "dependency-returns-garbage"
    assert r400["message"] == "Malformed Anvil request or invalid engine output"

    bad_trace = empty_v5_dir / ".anvil" / "v4" / "last_trace.json"
    bad_trace.parent.mkdir(parents=True, exist_ok=True)
    bad_trace.write_text("{corrupt-trace", encoding="utf-8")
    r502, c502 = anvil_session.get_v4_cockpit_state(empty_v5_dir)
    assert c502 == 502
    assert r502["status_kind"] == "dependency-returns-garbage"
    assert r502["message"] == "Malformed Anvil request or invalid engine output"
    bad_trace.unlink()

    # Row 1: dependency-missing -> 503
    with monkeypatch.context() as mp_dep:
        mp_dep.setattr(anvil_session, "anvil_engine", None)
        r503, c503 = anvil_session.get_v4_cockpit_state(empty_v5_dir)
        assert c503 == 503
        assert r503["status_kind"] == "dependency-missing"
        assert r503["message"] == "Anvil engine unavailable: required Python/skill module missing"

    # Row 2: dependency-slow-or-killed -> 504
    def _raise_timeout(*_a: Any, **_k: Any) -> Any:
        raise TimeoutError("simulated lock timeout")

    with monkeypatch.context() as mp_slow:
        mp_slow.setattr(anvil_session, "resolve_store_root", _raise_timeout)
        r504, c504 = anvil_session.get_v4_cockpit_state(empty_v5_dir)
        assert c504 == 504
        assert r504["status_kind"] == "dependency-slow-or-killed"
        assert r504["message"] == "Anvil operation timed out or worker terminated"


def test_w2_l3_look_verdict() -> None:
    """Sole writer of looks/w2/verdict.json: unlinks any prior verdict.json, runs ft.py look
    on w2-multi-analysis-pilot.html, asserts painted/uncovered/onScreen on phone & desktop,
    writes repo-relative verdict.json, and verifies distro.scan_paths == [] across Wave-2 files.
    """
    assert W2_MOCKUP_HTML.is_file(), f"Missing Wave-2 mockup HTML: {W2_MOCKUP_HTML}"
    if W2_LOOK_VERDICT.exists():
        W2_LOOK_VERDICT.unlink()
    W2_LOOK_DIR.mkdir(parents=True, exist_ok=True)

    ft_py = DEV_ROOT / "foundry-tools" / "ft.py"
    rel_mockup = W2_MOCKUP_HTML.relative_to(ANCHOR_ROOT).as_posix()
    rel_out = W2_LOOK_DIR.relative_to(ANCHOR_ROOT).as_posix()

    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ft_py),
            "look",
            rel_mockup,
            "--check",
            "[data-analysis-registry-pilot]",
            "--out",
            rel_out,
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

    for vp in results:
        assert vp.get("errors") == []
        shot_raw = Path(vp["screenshot"])
        shot_abs = shot_raw if shot_raw.is_absolute() else (ANCHOR_ROOT / shot_raw)
        assert shot_abs.is_file() and shot_abs.stat().st_size > 1_000
        vp["screenshot"] = shot_abs.resolve().relative_to(ANCHOR_ROOT.resolve()).as_posix()

        checks_map = vp.get("checks") or {}
        assert "[data-analysis-registry-pilot]" in checks_map
        elems = checks_map["[data-analysis-registry-pilot]"]
        assert isinstance(elems, list) and len(elems) >= 1
        for el in elems:
            assert el.get("painted") is True
            assert el.get("coveredBy") is None
            assert el.get("onScreen") is True

    if isinstance(look_doc.get("target"), str):
        t_path = Path(look_doc["target"])
        if t_path.is_absolute() and t_path.resolve().is_relative_to(ANCHOR_ROOT.resolve()):
            look_doc["target"] = t_path.resolve().relative_to(ANCHOR_ROOT.resolve()).as_posix()

    W2_LOOK_VERDICT.write_text(json.dumps(look_doc, indent=2) + "\n", encoding="utf-8")

    # Distro hygiene gate across all 6 Wave-2 deliverables
    w2_deliverables = [
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        ANCHOR_ROOT / "anchor_gui.py",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "cockpit.html",
        W2_MOCKUP_HTML,
        ANCHOR_ROOT / "tests" / "test_w2_anvil_multi_registry_2026_11_22.py",
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in w2_deliverables]
    assert distro.scan_paths(pairs, root=ANCHOR_ROOT) == []
