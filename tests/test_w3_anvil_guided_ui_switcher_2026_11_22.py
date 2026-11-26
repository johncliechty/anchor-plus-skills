"""Wave 3 Verification Suite — Anvil v5 Guided Mapping & Direction Dialogue,
Zero-Flash Boot Skeleton, Multi-Analysis Header Switcher (<50 ms), Same-Wave
Foundry/Vendor Byte-Sync, Ephemeral Playwright E2E & L3 `ft.py look` Verdict.
"""
from __future__ import annotations

import hashlib
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
SKILL_ROOT = ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil"
VENDOR_ANVIL_ROOT = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
PLAN_ROOT = ANCHOR_ROOT / "planning" / "2026-11-22-anvil-cockpit-multi-analysis"
W3_MOCKUP_HTML = PLAN_ROOT / "mockups" / "w3-anvil-v5-guided-and-switcher.html"
W3_LOOKS_DIR = PLAN_ROOT / "looks" / "w3"
W3_VERDICT_JSON = W3_LOOKS_DIR / "verdict.json"
FT_PY = ANCHOR_ROOT.parent / "foundry-tools" / "ft.py"
FORBIDDEN_LIVE_PORT = 8700 + 77


ALPHA_PY_SRC = textwrap.dedent(
    """\
    from __future__ import annotations


    def ingest_alpha_panel(rows: int = 8) -> list[float]:
        \"\"\"Ingest synthetic demand observations for Alpha estimator.\"\"\"
        return [float(i + 1) * 0.5 for i in range(rows)]


    def fit_alpha_kernel(panel: list[float]) -> dict[str, float]:
        \"\"\"Compute pure-core quadratic objective for Alpha.\"\"\"
        total = sum(x * x for x in panel)
        mean_val = total / float(len(panel) or 1)
        return {"alpha_objective": mean_val, "n_obs": float(len(panel))}
    """
)

ALPHA_TEX_SRC = textwrap.dedent(
    r"""\documentclass{article}
    \title{Alpha Demand Kernel Manuscript}
    \begin{document}
    \section{Model Specification}
    We estimate the Alpha quadratic kernel across panel draws:
    \begin{equation}\label{eq:alpha}
    Q_{\alpha}(x) = \frac{1}{N}\sum_{i=1}^{N} x_i^2
    \end{equation}
    \end{document}
    """
)

BETA_PY_SRC = textwrap.dedent(
    """\
    from __future__ import annotations


    def simulate_beta_draws(draws: int = 6) -> list[float]:
        \"\"\"Generate synthetic Monte Carlo draws for Beta replication.\"\"\"
        return [float(k + 2) * 1.25 for k in range(draws)]


    def evaluate_beta_table(draws: list[float]) -> dict[str, float]:
        \"\"\"Emit summary moments for Beta Monte Carlo table.\"\"\"
        s = sum(draws)
        return {"beta_sum": s, "beta_count": float(len(draws))}
    """
)

BETA_TEX_SRC = textwrap.dedent(
    r"""\documentclass{article}
    \title{Beta Monte Carlo Appendix}
    \begin{document}
    \section{Simulation Design}
    Monte Carlo moments satisfy the linear aggregation identity:
    \begin{equation}\label{eq:beta}
    M_{\beta}(z) = \sum_{k=1}^{K} z_k
    \end{equation}
    \end{document}
    """
)


def _setup_isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    anvil_session._LOADED_MTIME_NS = Path(anvil_session.__file__).stat().st_mtime_ns
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, tmp_path.resolve()),
    )
    monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "1")
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "anchor_data"))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    monkeypatch.setenv("ANCHOR_AUTH_MODE", "open")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    paths.ensure_data_dirs()


def _create_synthetic_cockpit_workspace(tmp_path: Path, slug: str = "synth_cockpit") -> tuple[Path, str]:
    ws_root = tmp_path / f"{slug}_ws"
    cdir = ws_root / slug
    sibling_repo = ws_root / "beta_sim_pkg"
    (cdir / "alpha_pkg").mkdir(parents=True, exist_ok=True)
    (cdir / "manuscript").mkdir(parents=True, exist_ok=True)
    (cdir / "pipelines").mkdir(parents=True, exist_ok=True)
    sibling_repo.mkdir(parents=True, exist_ok=True)

    (cdir / "alpha_pkg" / "estimator.py").write_text(ALPHA_PY_SRC, encoding="utf-8")
    (cdir / "pipelines" / "run_alpha_table1.py").write_text(
        "from alpha_pkg.estimator import ingest_alpha_panel, fit_alpha_kernel\n"
        "if __name__ == '__main__':\n"
        "    fit_alpha_kernel(ingest_alpha_panel(4))\n",
        encoding="utf-8",
    )
    (cdir / "manuscript" / "AlphaMain.tex").write_text(ALPHA_TEX_SRC, encoding="utf-8")
    (cdir / "manuscript" / "BetaAppendix.tex").write_text(BETA_TEX_SRC, encoding="utf-8")
    (sibling_repo / "mc_runner.py").write_text(BETA_PY_SRC, encoding="utf-8")

    proj = rnd_registry.add_project(f"Cockpit {slug}", cdir)
    return cdir, str(proj["id"])


def _start_ephemeral_anchor_server() -> tuple[Any, int, threading.Thread]:
    server = anchor_gui.make_server("127.0.0.1", 0)
    port = int(server.server_address[1])
    assert port != FORBIDDEN_LIVE_PORT and port > 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def _unwrap_anvil_tuple(res: Any) -> dict[str, Any]:
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], dict):
        assert int(res[1]) == 200, f"Unexpected HTTP status {res[1]}: {res[0]}"
        return res[0]
    assert isinstance(res, dict)
    return res


def test_w3_boot_skeleton_prevents_setup_flash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `#anvilBootSkeleton` hides `#cockpit-launch-screen` until initial `v4_state` settles:
    1. Configured 2-analysis cockpits render warm state in `<50 ms` and paint `#main-workbench-split`
       directly (`setupScreenEverShown == False`).
    2. Boot abort (`visibilitychange` hidden -> visible) recovers cleanly and clears `#anvilBootSkeleton`.
    3. All failure rows (`503`, `504`, `400/401/404/409/429/502`, `500 UNKNOWN`, `200 null/malformed`,
       `200 EMPTY`) resolve cleanly, never collapsing errors into 'no analysis yet' or tearing down
       an already-loaded workbench on mid-session poll errors.
    """
    pw = pytest.importorskip("playwright.sync_api")
    _setup_isolated_env(monkeypatch, tmp_path)
    cdir, pid = _create_synthetic_cockpit_workspace(tmp_path, "boot_skel")

    anvil_html = (ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html").read_text(encoding="utf-8")
    assert 'id="anvilBootSkeleton"' in anvil_html
    assert 'data-anvil-boot-skeleton="true"' in anvil_html

    # Pre-configure 2 analyses and verify warm 2-analysis cockpit state reads in < 50 ms
    c1 = _unwrap_anvil_tuple(
        anvil_session.create_cockpit_analysis(
            cdir,
            title="Alpha Estimation v1",
            mode="paper",
            software_spec="alpha_pkg",
            paper_spec="manuscript/AlphaMain.tex",
            direction="Focus on quadratic kernel equation alignment.",
            set_active=True,
        )
    )
    c2 = _unwrap_anvil_tuple(
        anvil_session.create_cockpit_analysis(
            cdir,
            title="Beta Simulation v1",
            mode="paper",
            software_spec=str((cdir.parent / "beta_sim_pkg").resolve()),
            paper_spec="manuscript/BetaAppendix.tex",
            direction="Focus on Beta Monte Carlo moments.",
            set_active=True,
        )
    )
    assert c1["ok"] is True and c2["ok"] is True

    # Warm prime then measure 2-analysis `get_v4_cockpit_state` < 50 ms
    _ = anvil_session.get_v4_cockpit_state(cdir)
    t_s0 = time.perf_counter()
    warm_state, warm_code = anvil_session.get_v4_cockpit_state(cdir)
    warm_state_ms = (time.perf_counter() - t_s0) * 1000.0
    assert warm_code == 200 and warm_state["ok"] is True
    assert len(warm_state.get("analyses") or []) == 2
    assert warm_state_ms < 50.0, f"Expected 2-analysis warm state < 50 ms, got {warm_state_ms:.2f} ms"

    # Verify failure-surface resolution across all error classes (including 401, 409, 429, and 200 null)
    anvil_js_posix = (ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js").as_posix()
    node_check = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const c = require('{anvil_js_posix}');"
                "const r503 = c.resolveBootFailureSurface(503, {error:'feature disabled'});"
                "const r504 = c.resolveBootFailureSurface(504, {error:'worker timed out'});"
                "const r502 = c.resolveBootFailureSurface(502, {error:'corrupt payload'});"
                "const r400 = c.resolveBootFailureSurface(400, {error:'bound refused'});"
                "const r401 = c.resolveBootFailureSurface(401, {ok:false, error:'unauthorized'});"
                "const r409 = c.resolveBootFailureSurface(409, {ok:false, error:'conflict'});"
                "const r429 = c.resolveBootFailureSurface(429, {ok:false, error:'rate limited'});"
                "const r200Null = c.resolveBootFailureSurface(200, null);"
                "const r500 = c.resolveBootFailureSurface(500, {unknown_state:true});"
                "const r200 = c.resolveBootFailureSurface(200, {ok:true, active:false, analyses:[]});"
                "console.log(JSON.stringify({r503, r504, r502, r400, r401, r409, r429, r200Null, r500, r200}));"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = json.loads(node_check.stdout.strip())
    assert rows["r503"]["open_intake"] is False and rows["r503"]["badge"] == "DEGRADED_STATIC"
    assert rows["r504"]["open_intake"] is False and rows["r504"]["retryable"] is True
    assert rows["r502"]["open_intake"] is False and rows["r502"]["badge"] == "REJECTED_GARBAGE"
    assert rows["r400"]["open_intake"] is False
    assert rows["r401"]["open_intake"] is False and rows["r401"]["badge"] == "UNAUTHORIZED"
    assert rows["r409"]["open_intake"] is False
    assert rows["r429"]["open_intake"] is False and rows["r429"]["badge"] == "RATE_LIMITED"
    assert rows["r200Null"]["open_intake"] is False and rows["r200Null"]["badge"] == "REJECTED_GARBAGE"
    assert rows["r500"]["open_intake"] is False and rows["r500"]["unknown_state"] is True
    assert rows["r200"]["open_intake"] is True and rows["r200"]["badge"] == "EMPTY"

    server, port, _ = _start_ephemeral_anchor_server()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=10000)

            telem = page.evaluate("() => window.__anvilBootTelemetry")
            assert telem["bootSettled"] is True
            assert telem["bootSkeletonShownInitially"] is True
            assert telem["setupScreenPaintedDuringBoot"] is False
            assert telem["setupScreenEverShown"] is False
            assert page.locator("#anvilBootSkeleton").is_hidden()
            assert page.locator("#cockpit-launch-screen").is_hidden()

            # Verify mid-session 401 poll failure preserves loaded workbench (never tears down into EMPTY)
            def _fail_summary_401(route, _req=None):
                if "summary=1" in route.request.url:
                    route.fulfill(
                        status=401,
                        content_type="application/json",
                        body=json.dumps({"ok": False, "error": "unauthorized"}),
                    )
                else:
                    route.continue_()

            page.route("**/api/steward/anvil*", _fail_summary_401)
            page.click("#btn-retry-state", force=True) if page.locator("#btn-retry-state").is_visible() else None
            page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_timeout(150)
            assert page.locator("#main-workbench-split").is_visible()
            assert page.locator("#cockpit-launch-screen").is_hidden()
            assert page.locator("#analysisSwitcherSelect option").count() == 2
            page.unroute("**/api/steward/anvil*", _fail_summary_401)

            # Verify boot-abort recovery: abort first in-flight boot request via visibilitychange hidden -> visible
            abort_page = browser.new_page(viewport={"width": 1280, "height": 800})
            v4_calls = {"count": 0}

            def _delay_first_boot(route, _req=None):
                if "action=v4_state" in route.request.url:
                    v4_calls["count"] += 1
                    if v4_calls["count"] == 1:
                        time.sleep(0.35)
                route.continue_()

            abort_page.route("**/api/steward/anvil*", _delay_first_boot)
            abort_page.goto(
                f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}",
                wait_until="domcontentloaded",
            )
            # Simulate tab hidden mid-boot (aborts initial fetchFullState(true)), then visible again
            abort_page.evaluate(
                """() => {
                Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
                document.dispatchEvent(new Event('visibilitychange'));
                Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
                document.dispatchEvent(new Event('visibilitychange'));
                }"""
            )
            abort_page.locator("#main-workbench-split").wait_for(state="visible", timeout=10000)
            assert abort_page.locator("#anvilBootSkeleton").is_hidden()
            assert abort_page.locator("#cockpit-launch-screen").is_hidden()
            abort_page.close()

            # Verify 503, 504, and 401 boot responses show error surface + Retry and NEVER open Guided Intake
            for sim_status, expected_badge in (
                (503, "DEGRADED_STATIC"),
                (504, "TIMEOUT_PARTIAL"),
                (401, "UNAUTHORIZED"),
            ):
                err_page = browser.new_page(viewport={"width": 1280, "height": 800})

                def _make_interceptor(code_val: int):
                    def _intercept_err(route, _req=None):
                        if "action=v4_state" in route.request.url:
                            route.fulfill(
                                status=code_val,
                                content_type="application/json",
                                body=json.dumps({"ok": False, "error": f"Simulated {code_val} failure"}),
                            )
                        else:
                            route.continue_()

                    return _intercept_err

                err_page.route("**/api/steward/anvil*", _make_interceptor(sim_status))
                err_page.goto(
                    f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}",
                    wait_until="domcontentloaded",
                )
                err_page.locator("#surface-state-banner").wait_for(state="visible", timeout=10000)
                assert err_page.locator("#surface-state-badge").inner_text().strip() == expected_badge
                assert err_page.locator("#cockpit-launch-screen").is_hidden()
                assert err_page.locator("[data-anvil-intake-dialogue]").is_hidden()
                assert err_page.locator("#anvilBootErrorCard").is_visible()
                err_page.close()

            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_w3_first_click_empty_cockpit_opens_guided_dialogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify an empty cockpit (`analyses.length === 0`, HTTP 200) automatically opens
    `[data-anvil-intake-dialogue]` pre-populated AND pre-selecting the first discovered
    code repository and companion manuscript (matching the approved mockup).
    """
    pw = pytest.importorskip("playwright.sync_api")
    _setup_isolated_env(monkeypatch, tmp_path)
    _, pid = _create_synthetic_cockpit_workspace(tmp_path, "empty_intake")

    server, port, _ = _start_ephemeral_anchor_server()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")

            intake = page.locator("[data-anvil-intake-dialogue]")
            intake.wait_for(state="visible", timeout=10000)
            assert page.locator("#anvilBootSkeleton").is_hidden()

            switcher_txt = page.locator("#analysisSwitcherSelect").inner_text()
            assert "0 Analyses" in switcher_txt

            repo_opts = page.locator("#intakeRepoSelect option").all_inner_texts()
            ms_opts = page.locator("#intakeManuscriptSelect option").all_inner_texts()
            pipe_cnt = page.locator("#intakePipelinesList input[type='checkbox']").count()

            assert any("alpha_pkg" in opt or "Cockpit" in opt for opt in repo_opts)
            assert any("beta_sim_pkg" in opt for opt in repo_opts)
            assert any("AlphaMain.tex" in opt for opt in ms_opts)
            assert pipe_cnt >= 1

            # Verify first discovered repo and manuscript are pre-selected (not '__custom__' / empty)
            assert page.locator("#intakeRepoSelect").input_value() not in ("", "__custom__")
            assert page.locator("#intakeManuscriptSelect").input_value() not in ("", "__custom__")
            assert page.locator("#inputPaperTarget").input_value().endswith(".tex")
            assert page.locator("#intakeReplicationPkgToggle").is_checked()
            assert page.locator("#intakeDirectionInput").is_visible()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_w3_header_dropdown_switches_analyses_under_50ms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `#analysisSwitcherSelect` switches warm analyses in `< 50 ms` (`warm` source),
    isolates per-analysis session state (chat/walkthrough never bleed across switch), and honors
    explicit `?analysis_id=id1` even when cockpit-global `active_analysis_id` is `id2`.
    """
    pw = pytest.importorskip("playwright.sync_api")
    _setup_isolated_env(monkeypatch, tmp_path)
    cdir, pid = _create_synthetic_cockpit_workspace(tmp_path, "fast_switch")

    a1 = _unwrap_anvil_tuple(
        anvil_session.create_cockpit_analysis(
            cdir,
            title="Alpha Estimation Core",
            mode="paper",
            software_spec="alpha_pkg",
            paper_spec="manuscript/AlphaMain.tex",
            set_active=True,
        )
    )
    a2 = _unwrap_anvil_tuple(
        anvil_session.create_cockpit_analysis(
            cdir,
            title="Beta Monte Carlo Sim",
            mode="paper",
            software_spec=str((cdir.parent / "beta_sim_pkg").resolve()),
            paper_spec="manuscript/BetaAppendix.tex",
            set_active=True,
        )
    )
    id1 = a1["analysis_id"]
    id2 = a2["analysis_id"]
    assert id1 != id2

    server, port, _ = _start_ephemeral_anchor_server()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=10000)

            page.wait_for_function(
                "() => document.querySelectorAll('#analysisSwitcherSelect option').length === 2",
                timeout=10000,
            )
            page.wait_for_timeout(200)

            opt_texts = page.locator("#analysisSwitcherSelect option").all_inner_texts()
            assert len(opt_texts) == 2
            assert any("Alpha Estimation Core" in t and "[" in t for t in opt_texts)
            assert any("Beta Monte Carlo Sim" in t and "[" in t for t in opt_texts)

            # Record a distinct chat turn on Analysis 2 (`id2`) to test state-bleed isolation
            page.fill("#chat-input", "BETA_EXCLUSIVE_QUESTION_TOKEN")
            page.click("#btn-chat-send")
            page.wait_for_function(
                "() => document.getElementById('chat-messages').innerText.includes('BETA_EXCLUSIVE_QUESTION_TOKEN')",
                timeout=10000,
            )

            # Switch to Analysis 1 (`id1`): wait for non-null switch measurement, assert warm source & < 50 ms,
            # and assert Analysis 2's chat/session state did NOT bleed into Analysis 1!
            page.select_option("#analysisSwitcherSelect", id1)
            page.wait_for_function("() => window.__anvilLastSwitchMs !== null", timeout=5000)
            switch_src_1 = page.evaluate("() => window.__anvilLastSwitchSource")
            switch_ms_1 = float(page.evaluate("() => window.__anvilLastSwitchMs"))
            assert switch_src_1 == "warm", f"Expected warm cache switch, got {switch_src_1}"
            assert 0.0 < switch_ms_1 < 50.0, f"Expected warm switch < 50 ms, observed {switch_ms_1:.2f} ms"
            assert "BETA_EXCLUSIVE_QUESTION_TOKEN" not in page.locator("#chat-messages").inner_text()
            assert "alpha" in page.locator("#left-schematic-pane").inner_text().lower()

            # Switch back to Analysis 2 (`id2`) -> warm < 50 ms
            page.select_option("#analysisSwitcherSelect", id2)
            page.wait_for_function("() => window.__anvilLastSwitchMs !== null", timeout=5000)
            assert page.evaluate("() => window.__anvilLastSwitchSource") == "warm"
            switch_ms_2 = float(page.evaluate("() => window.__anvilLastSwitchMs"))
            assert 0.0 < switch_ms_2 < 50.0, f"Expected warm switch < 50 ms, observed {switch_ms_2:.2f} ms"
            # Wait for background switch_analysis POST to ensure global active_analysis_id == id2
            page.wait_for_timeout(120)

            # Open deep-link `?analysis_id=id1` while global `active_analysis_id == id2`!
            # Client MUST honor `analysis_id == id1` (never overwritten by `active_analysis_id == id2`).
            deep_page = browser.new_page(viewport={"width": 1440, "height": 900})
            deep_page.goto(
                f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}&analysis_id={id1}",
                wait_until="networkidle",
            )
            deep_page.locator("#main-workbench-split").wait_for(state="visible", timeout=10000)
            assert deep_page.locator("#analysisSwitcherSelect").input_value() == id1
            deep_page.fill("#chat-input", "Deep link explicit analysis_id check")
            deep_page.click("#btn-chat-send")
            deep_page.wait_for_function(
                "() => (window.__anvilRequestLog || []).some(r => r.action === 'chat')",
                timeout=10000,
            )
            deep_reqs = [r for r in deep_page.evaluate("() => window.__anvilRequestLog") if r.get("action") == "chat"]
            assert deep_reqs and deep_reqs[-1]["analysis_id"] == id1
            deep_page.close()

            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_w3_new_analysis_button_opens_guided_dialogue_preserving_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
    1. `+ New Analysis` creates a second analysis preserving Analysis 1 byte-for-byte on disk,
       and persists `selected_pipelines`, `materialize_replication_package`, and `max_concurrency`.
    2. Clicking `Edit Scope` (`#btnOpenLauncherDrawer`) after switching back to Analysis 1 populates
       the form with Analysis 1's own title, software, paper, and direction (never stale Analysis 2 values).
    3. Flag-OFF (`ANCHOR_ANVIL_MULTI=0`) disables multi-slot creation (`503 MULTI_ANALYSIS_DISABLED` on server,
       `start_code` fallback in `buildGuidedIntakeSubmission`, and disabled `#btnNewAnvilAnalysis` in UI).
    """
    pw = pytest.importorskip("playwright.sync_api")
    _setup_isolated_env(monkeypatch, tmp_path)
    cdir, pid = _create_synthetic_cockpit_workspace(tmp_path, "preserve_existing")

    first, f_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "create_analysis",
            "title": "Original Alpha Analysis",
            "mode": "paper",
            "software_target": "alpha_pkg",
            "paper_spec": "manuscript/AlphaMain.tex",
            "selected_pipelines": ["pipelines/run_alpha_table1.py"],
            "materialize_replication_package": False,
            "max_concurrency": 1,
            "direction": "Preserve original alpha session.",
            "set_active": True,
        },
    )
    assert f_code == 200 and first["ok"] is True
    id1 = first["analysis_id"]
    assert first["session"]["selected_pipelines"] == ["pipelines/run_alpha_table1.py"]
    assert first["session"]["materialize_replication_package"] is False
    assert first["session"]["max_concurrency"] == 1
    _, store_root_1 = anvil_session.resolve_store_root(cdir, id1)
    sess1_path = Path(store_root_1) / ".anvil" / "session.json"
    assert sess1_path.is_file()
    orig_sess1_bytes = sess1_path.read_bytes()

    server, port, _ = _start_ephemeral_anchor_server()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=10000)

            page.click("#btnNewAnvilAnalysis")
            page.locator("[data-anvil-intake-dialogue]").wait_for(state="visible", timeout=5000)
            assert "New Analysis" in page.locator("#intakeModeBadge").inner_text()
            assert page.locator("#analysisSwitcherSelect option").count() == 1

            # Submit second analysis via Guided Intake
            beta_sw_str = str((cdir.parent / "beta_sim_pkg").resolve())
            page.fill("#inputAnalysisTitle", "Added Beta Analysis")
            page.fill("#inputSoftwareTarget", beta_sw_str)
            page.fill("#inputPaperTarget", "manuscript/BetaAppendix.tex")
            page.fill("#intakeDirectionInput", "Map Beta Monte Carlo simulation moments.")
            page.click("#btnSubmitGuidedIntake")

            page.locator("#main-workbench-split").wait_for(state="visible", timeout=15000)
            assert page.locator("#analysisSwitcherSelect option").count() == 2

            # Verify Analysis 1 session file on disk was 100% preserved (byte-for-byte untouched)
            assert sess1_path.read_bytes() == orig_sess1_bytes
            listed = _unwrap_anvil_tuple(anvil_session.list_cockpit_analyses(cdir))
            assert len(listed["analyses"]) == 2

            # Switch back to Analysis 1 and click `Edit Scope` (`#btnOpenLauncherDrawer`) ->
            # form MUST display Analysis 1's scope, NOT Analysis 2's!
            page.select_option("#analysisSwitcherSelect", id1)
            page.wait_for_function("() => window.__anvilLastSwitchMs !== null", timeout=5000)
            page.click("#btnOpenLauncherDrawer")
            page.locator("[data-anvil-intake-dialogue]").wait_for(state="visible", timeout=5000)
            assert page.locator("#inputAnalysisTitle").input_value() == "Original Alpha Analysis"
            assert page.locator("#inputSoftwareTarget").input_value() == "alpha_pkg"
            assert page.locator("#inputPaperTarget").input_value() == "manuscript/AlphaMain.tex"
            assert page.locator("#intakeDirectionInput").input_value() == "Preserve original alpha session."
            assert page.locator("#intakeReplicationPkgToggle").is_checked() is False
            assert page.locator("#intakeMaxConcurrency").input_value() == "1"

            # Verify Flag-OFF (`ANCHOR_ANVIL_MULTI=0`) safety in server + JS + UI
            monkeypatch.setenv("ANCHOR_ANVIL_MULTI", "0")
            flag_off_cdir, flag_off_pid = _create_synthetic_cockpit_workspace(tmp_path, "flag_off_cockpit")
            off_res, off_code = anvil_session.create_cockpit_analysis(
                flag_off_cdir, title="Should Refuse", software_spec="alpha_pkg"
            )
            assert off_code == 503 and off_res["error_code"] == "MULTI_ANALYSIS_DISABLED"
            assert not (flag_off_cdir / ".anvil" / "analyses" / "index.json").exists()

            sw_off_res, sw_off_code = anvil_session.switch_cockpit_analysis(flag_off_cdir, "legacy-primary")
            assert sw_off_code == 503 and sw_off_res["error_code"] == "MULTI_ANALYSIS_DISABLED"

            off_page = browser.new_page(viewport={"width": 1280, "height": 800})
            off_page.goto(
                f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={flag_off_pid}",
                wait_until="networkidle",
            )
            off_page.locator("[data-anvil-intake-dialogue]").wait_for(state="visible", timeout=10000)
            assert off_page.locator("#btnNewAnvilAnalysis").is_disabled()
            off_page.close()

            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_w3_direction_payload_16kb_bound_and_escape_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify `<= 16384` UTF-8 byte guard on `direction` in JS + server (`create_analysis` AND
    `start_code`/`start_paper` -> `400 BOUND_EXCEEDED_REFUSAL`), strict HTML escaping against XSS,
    and `max_concurrency <= 2` enforcement.
    """
    pw = pytest.importorskip("playwright.sync_api")
    _setup_isolated_env(monkeypatch, tmp_path)
    cdir, pid = _create_synthetic_cockpit_workspace(tmp_path, "bounds_xss")

    # 1. Node unit verification of UTF-8 byte boundary, flag-OFF submission fallback, XSS escaping & max_concurrency <= 2
    anvil_js_posix = (ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js").as_posix()
    node_out = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const c = require('{anvil_js_posix}');"
                "const exact16k = 'λ'.repeat(8192);"
                "const over16k = exact16k + 'a';"
                "const okExact = c.validateDirectionPayload(exact16k, {max_concurrency: 2});"
                "const badOver = c.validateDirectionPayload(over16k, {max_concurrency: 2});"
                "const badConc = c.validateDirectionPayload('ok', {max_concurrency: 3});"
                "const flagOff = c.buildGuidedIntakeSubmission({direction:''}, {createNew:true, multiAnalysisEnabled:false});"
                "const xss = c.validateDirectionPayload('<img src=x onerror=alert(1)><script>evil()</script>');"
                "console.log(JSON.stringify({okExact: okExact.ok, exactBytes: okExact.byte_length, badOver, badConc, flagOffAct: flagOff.action, esc: xss.escaped_direction}));"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    res = json.loads(node_out.stdout.strip())
    assert res["okExact"] is True and res["exactBytes"] == 16384
    assert res["badOver"]["ok"] is False and res["badOver"]["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    assert res["badConc"]["ok"] is False and res["badConc"]["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    assert res["flagOffAct"] == "start_code"
    assert "<script>" not in res["esc"] and "&lt;script&gt;" in res["esc"]

    # 2. Server-side `400 BOUND_EXCEEDED_REFUSAL` on >16KB direction for BOTH `create_analysis` AND `start_code`
    for act_name in ("create_analysis", "start_code"):
        over_resp, over_code = steward_routes.handle_post(
            str(cdir),
            "anvil",
            {
                "action": act_name,
                "title": "Oversized Direction",
                "software_target": "alpha_pkg",
                "direction": "x" * 16385,
            },
        )
        assert over_code == 400 and over_resp["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    conc_resp, conc_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "start_code",
            "software_target": "alpha_pkg",
            "direction": "valid",
            "max_concurrency": 3,
        },
    )
    assert conc_code == 400 and conc_resp["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    # 3. Browser UI refusal on >16KB direction + safe XSS rendering on valid submission
    server, port, _ = _start_ephemeral_anchor_server()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 840})
            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")
            page.locator("[data-anvil-intake-dialogue]").wait_for(state="visible", timeout=10000)

            page.fill("#intakeDirectionInput", "d" * 16385)
            page.click("#btnSubmitGuidedIntake")
            err_loc = page.locator("#intakeDirectionError")
            assert err_loc.is_visible()
            assert "BOUND_EXCEEDED_REFUSAL" in err_loc.inner_text()
            assert _unwrap_anvil_tuple(anvil_session.list_cockpit_analyses(cdir))["analyses"] == []

            xss_payload = '<img src=x onerror="window.__xssTriggered=1"><svg onload="window.__xssTriggered=2">'
            page.fill("#inputAnalysisTitle", xss_payload)
            page.fill("#intakeDirectionInput", xss_payload)
            page.click("#btnSubmitGuidedIntake")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=15000)
            assert page.evaluate("() => window.__xssTriggered") is None
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_w3_anvil_v5_branding_and_same_wave_vendor_byte_sync() -> None:
    """Verify 'Anvil v5' branding, switcher & guided intake markers across all surfaces,
    100% SHA-256 byte-identity between Skill Foundry and `vendor/bundled-skills/anvil`,
    zero `__pycache__`/`.pyc`, and `distro.scan_paths == []` on all touched Anchor files.
    """
    sf_wb = SKILL_ROOT / "static" / "anvil_v4_workbench.html"
    vn_wb = VENDOR_ANVIL_ROOT / "static" / "anvil_v4_workbench.html"
    cockpit_html = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html"
    cockpit_js = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.js"

    for path_item in (sf_wb, vn_wb, cockpit_html, cockpit_js, W3_MOCKUP_HTML):
        assert path_item.is_file(), f"Missing required Wave 3 deliverable: {path_item}"

    sf_sha = hashlib.sha256(sf_wb.read_bytes()).hexdigest()
    vn_sha = hashlib.sha256(vn_wb.read_bytes()).hexdigest()
    assert sf_sha == vn_sha, "Skill Foundry and vendor anvil_v4_workbench.html SHA-256 drifted!"

    assert list(VENDOR_ANVIL_ROOT.rglob("__pycache__")) == []
    assert list(VENDOR_ANVIL_ROOT.rglob("*.pyc")) == []

    for html_surface in (cockpit_html, sf_wb, vn_wb, W3_MOCKUP_HTML):
        txt = html_surface.read_text(encoding="utf-8")
        assert "Anvil v5" in txt, f"Missing 'Anvil v5' branding in {html_surface}"
        assert 'id="analysisSwitcherSelect"' in txt, f"Missing #analysisSwitcherSelect in {html_surface}"
        assert "data-analysis-switcher" in txt, f"Missing data-analysis-switcher in {html_surface}"
        assert 'id="btnNewAnvilAnalysis"' in txt, f"Missing #btnNewAnvilAnalysis in {html_surface}"
        assert "data-anvil-intake-dialogue" in txt, f"Missing [data-anvil-intake-dialogue] in {html_surface}"
        assert "setInterval" not in txt, f"Forbidden setInterval found in {html_surface}"

    scan_targets = [
        cockpit_html,
        cockpit_js,
        vn_wb,
        W3_MOCKUP_HTML,
        Path(__file__).resolve(),
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in scan_targets]
    hits = distro.scan_paths(pairs, root=ANCHOR_ROOT)
    assert hits == [], f"distro.scan_paths flagged Wave 3 files: {hits}"


def test_w3_playwright_ephemeral_server_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full Playwright E2E journey on ephemeral loopback server (`port != 8777`):
    0-analysis guided intake -> create Analysis 1 -> `+ New Analysis` -> create Analysis 2
    -> `<select id="analysisSwitcherSelect">` switch between both + standalone HTML honest
    pre-built switching & offline read-only notice (never fabricating fake analyses).
    """
    pw = pytest.importorskip("playwright.sync_api")
    _setup_isolated_env(monkeypatch, tmp_path)
    cdir, pid = _create_synthetic_cockpit_workspace(tmp_path, "e2e_journey")

    server, port, _ = _start_ephemeral_anchor_server()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            console_errors: list[str] = []
            page_errors: list[str] = []
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)))

            # Step 1: Open empty cockpit -> Guided Intake opens automatically
            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")
            page.locator("[data-anvil-intake-dialogue]").wait_for(state="visible", timeout=10000)

            # Step 2: Create Analysis 1 (Alpha Estimation)
            page.fill("#inputAnalysisTitle", "Alpha Kernel Analysis")
            page.fill("#inputSoftwareTarget", "alpha_pkg")
            page.fill("#inputPaperTarget", "manuscript/AlphaMain.tex")
            page.fill("#intakeDirectionInput", "Map Alpha quadratic objective Eq. 1 to fit_alpha_kernel.")
            page.click("#btnSubmitGuidedIntake")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=15000)
            assert page.locator("#analysisSwitcherSelect option").count() == 1
            aid_1 = page.locator("#analysisSwitcherSelect").input_value()
            assert aid_1

            # Step 3: Click `+ New Analysis` -> Create Analysis 2 (Beta Simulation)
            page.click("#btnNewAnvilAnalysis")
            page.locator("[data-anvil-intake-dialogue]").wait_for(state="visible", timeout=5000)
            page.fill("#inputAnalysisTitle", "Beta Simulation Analysis")
            page.fill("#inputSoftwareTarget", str((cdir.parent / "beta_sim_pkg").resolve()))
            page.fill("#inputPaperTarget", "manuscript/BetaAppendix.tex")
            page.fill("#intakeDirectionInput", "Verify Beta Monte Carlo moments.")
            page.click("#btnSubmitGuidedIntake")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=15000)
            assert page.locator("#analysisSwitcherSelect option").count() == 2
            aid_2 = page.locator("#analysisSwitcherSelect").input_value()
            assert aid_2 and aid_2 != aid_1

            # Step 4: Switch back to Analysis 1 via `<select id="analysisSwitcherSelect">`
            page.select_option("#analysisSwitcherSelect", aid_1)
            page.wait_for_function("() => window.__anvilLastSwitchMs !== null", timeout=5000)
            assert page.locator("#analysisSwitcherSelect").input_value() == aid_1
            assert page.evaluate("() => window.__anvilLastSwitchSource") == "warm"
            assert float(page.evaluate("() => window.__anvilLastSwitchMs")) < 50.0
            assert "alpha" in page.locator("#left-schematic-pane").inner_text().lower()

            # Switch forward to Analysis 2
            page.select_option("#analysisSwitcherSelect", aid_2)
            page.wait_for_function("() => window.__anvilLastSwitchMs !== null", timeout=5000)
            assert page.locator("#analysisSwitcherSelect").input_value() == aid_2
            assert "beta" in page.locator("#left-schematic-pane").inner_text().lower()

            assert console_errors == [], f"Unexpected console errors: {console_errors}"
            assert page_errors == [], f"Unexpected page errors: {page_errors}"

            # Step 5: Verify standalone `anvil_v4_workbench.html`:
            # (i) Switches honestly between genuinely pre-built bundles in `bootstrap.analyses`.
            # (ii) Clicking `+ New Analysis` in offline standalone mode shows `[data-standalone-offline-notice]`
            #      with `#btnSubmitGuidedIntake` disabled and NEVER fabricates a fake option.
            alpha_bundle = {
                "repo_name": "alpha_pkg",
                "has_trace": False,
                "process_map": {
                    "l0_scenarios": [],
                    "l1_stages": [{"id": "S1", "title": "Fit Alpha Kernel", "kind": "compute", "l2_steps": []}],
                },
                "refactor_map": {"old_stages": [], "target_stages": [], "crosswalk_edges": []},
                "paper_map": {"has_paper": False, "equations": []},
                "files_source_map": {},
                "variable_catalog": {"scopes": {}},
            }
            beta_bundle = {
                "repo_name": "beta_sim_pkg",
                "has_trace": True,
                "process_map": {
                    "l0_scenarios": [],
                    "l1_stages": [{"id": "S1", "title": "Simulate Beta Draws", "kind": "simulate", "l2_steps": []}],
                },
                "refactor_map": {"old_stages": [], "target_stages": [], "crosswalk_edges": []},
                "paper_map": {"has_paper": False, "equations": []},
                "files_source_map": {},
                "variable_catalog": {"scopes": {}},
            }
            boot_doc = {
                "mode": "standalone",
                "capability_token": "",
                "active_analysis_id": "sa-1",
                "analyses": [
                    {
                        "analysis_id": "sa-1",
                        "title": "Standalone Alpha",
                        "validation_status": "STATIC_AST",
                        "bundle": alpha_bundle,
                    },
                    {
                        "analysis_id": "sa-2",
                        "title": "Standalone Beta",
                        "validation_status": "TRACED",
                        "bundle": beta_bundle,
                    },
                ],
                "bundle": alpha_bundle,
            }
            wb_template = (SKILL_ROOT / "static" / "anvil_v4_workbench.html").read_text(encoding="utf-8")
            standalone_html = wb_template.replace(
                "__ANVIL_BOOTSTRAP_JSON__",
                json.dumps(boot_doc).replace("</", "<\\/"),
            ).replace("__ANVIL_CSP_NONCE__", "w3testnonce")
            sa_path = tmp_path / "standalone_v5_check.html"
            sa_path.write_text(standalone_html, encoding="utf-8")
            sa_page = browser.new_page(viewport={"width": 1280, "height": 800})
            sa_page.goto(sa_path.as_uri(), wait_until="load")
            assert sa_page.locator("#analysisSwitcherSelect option").count() == 2
            assert "alpha_pkg" in sa_page.locator("#repo-badge").inner_text()
            sa_page.select_option("#analysisSwitcherSelect", "sa-2")
            assert "beta_sim_pkg" in sa_page.locator("#repo-badge").inner_text()
            assert "beta" in sa_page.locator("#left-schematic-pane").inner_text().lower()

            # Clicking `+ New Analysis` in standalone offline mode displays read-only notice & disables submit
            assert sa_page.locator("[data-anvil-intake-dialogue]").is_hidden()
            sa_page.click("#btnNewAnvilAnalysis")
            assert sa_page.locator("[data-anvil-intake-dialogue]").is_visible()
            assert sa_page.locator("[data-standalone-offline-notice]").is_visible()
            assert sa_page.locator("#btnSubmitGuidedIntake").is_disabled()
            assert sa_page.locator("#analysisSwitcherSelect option").count() == 2
            sa_page.close()

            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def _run_ft_look_and_assert(target: str, out_dir: Path) -> dict[str, Any]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    required_selectors = [
        "#analysisSwitcherSelect",
        "#btnNewAnvilAnalysis",
        "[data-anvil-intake-dialogue]",
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
        "--check",
        required_selectors[2],
        "--out",
        str(out_dir),
        "--json",
    ]
    proc = subprocess.run(cmd, cwd=str(ANCHOR_ROOT), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"ft.py look failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    payload = json.loads(proc.stdout)
    viewports = payload.get("results") or payload.get("viewports") or []
    assert len(viewports) >= 2, f"Expected phone & desktop viewports, got: {payload}"

    sanitized_vps: list[dict[str, Any]] = []
    for vp in viewports:
        vp_label = vp.get("size") or vp.get("viewport")
        assert "error" not in vp, f"Viewport error in ft.py look: {vp}"
        assert vp.get("errors", []) == [], f"Errors on {vp_label}: {vp.get('errors')}"
        assert vp.get("consoleErrors", []) == [], f"Console errors on {vp_label}: {vp.get('consoleErrors')}"
        assert vp.get("pageErrors", []) == [], f"Page errors on {vp_label}: {vp.get('pageErrors')}"
        assert vp.get("failedAssets", []) == [], f"Failed assets on {vp_label}: {vp.get('failedAssets')}"

        checks = vp.get("checks") or {}
        for sel in required_selectors:
            matches = checks.get(sel)
            assert isinstance(matches, list) and len(matches) >= 1, (
                f"Selector {sel} had 0 matches on {vp_label}: {checks}"
            )
            first = matches[0]
            assert first.get("painted") is True, f"Selector {sel} not painted on {vp_label}: {first}"
            assert first.get("coveredBy") is None, f"Selector {sel} covered on {vp_label}: {first}"
            assert first.get("onScreen") is True, f"Selector {sel} off-screen on {vp_label}: {first}"

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


def test_w3_l3_look_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sole writer of `planning/2026-11-22-anvil-cockpit-multi-analysis/looks/w3/verdict.json`.
    Unlinks any prior verdict, runs `ft.py look` on both the Wave-3 HTML mockup AND a live
    ephemeral loopback server (`port != 8777`), asserts `painted == True`, `coveredBy is None`,
    and `onScreen == True` on both `390x844` phone and `1440x900` desktop, and writes `PASSED`.
    """
    assert FT_PY.is_file(), f"Missing foundry-tools CLI: {FT_PY}"
    assert W3_MOCKUP_HTML.is_file(), f"Missing Wave 3 mockup: {W3_MOCKUP_HTML}"

    W3_LOOKS_DIR.mkdir(parents=True, exist_ok=True)
    if W3_VERDICT_JSON.exists():
        W3_VERDICT_JSON.unlink()

    _setup_isolated_env(monkeypatch, tmp_path)
    _, pid = _create_synthetic_cockpit_workspace(tmp_path, "look_live")

    mockup_res = _run_ft_look_and_assert(str(W3_MOCKUP_HTML), W3_LOOKS_DIR / "mockup")

    live_rel_path = f"/steward-static/anvil.html?pid={pid}"
    server, port, _ = _start_ephemeral_anchor_server()
    try:
        live_url = f"http://127.0.0.1:{port}{live_rel_path}"
        live_res = _run_ft_look_and_assert(live_url, W3_LOOKS_DIR / "live")
    finally:
        server.shutdown()
        server.server_close()

    verdict_doc = {
        "schema": "anvil.look-verdict.v1",
        "wave": "w3",
        "status": "PASSED",
        "checked_selectors": [
            "#analysisSwitcherSelect",
            "#btnNewAnvilAnalysis",
            "[data-anvil-intake-dialogue]",
        ],
        "surfaces": {
            "mockup": {
                "target": W3_MOCKUP_HTML.relative_to(ANCHOR_ROOT).as_posix(),
                "viewports": mockup_res["viewports"],
            },
            "live_cockpit": {
                "target": live_rel_path,
                "ephemeral_port_non_live": True,
                "viewports": live_res["viewports"],
            },
        },
        "generated_at_epoch_s": int(time.time()),
    }
    tmp_verdict = W3_VERDICT_JSON.with_suffix(".json.tmp")
    tmp_verdict.write_text(json.dumps(verdict_doc, indent=2), encoding="utf-8")
    os.replace(tmp_verdict, W3_VERDICT_JSON)

    assert W3_VERDICT_JSON.is_file()
    hits = distro.scan_paths(
        [(W3_VERDICT_JSON.relative_to(ANCHOR_ROOT).as_posix(), W3_VERDICT_JSON)],
        root=ANCHOR_ROOT,
    )
    assert hits == [], f"distro.scan_paths flagged verdict.json: {hits}"
