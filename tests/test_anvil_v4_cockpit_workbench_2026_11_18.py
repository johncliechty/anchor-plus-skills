"""Gate-6 Regression & Playwright E2E Suite for Anchor Anvil v4 Workbench (2026-11-18).

Verifies:
1. Per-cockpit `.anvil/v4` artifact isolation (external software repo stays 100% clean),
   compact `<15 KB` `?summary=1` status payload, native MathML (`0` `$`), S1..Sk -> N1..Nk
   refactor crosswalk + symbol conservation, fail-closed `v4_trace` consent/argv gates,
   +Infinity tripwire + monotonic Smart Variable Funnel, and zero-restart hot-reload bridge.
2. All 5 surface failure states & strict `UNKNOWN` (500) vs `EMPTY` (200) vs `REJECTED_GARBAGE` (502).
3. Headless Chromium (`1600x1000`) Gate-6 roundtrip: Launch Screen -> Posture 1 (`48%/52%`),
   `0` console/page errors, `0` SVG `<text>` overlaps, `minFont >= 11px`, Consent Modal ->
   `TRACED`, Posture 2 (`25%/45%/30%`) IDE Debugger, theme toggle, breakpoint + watch pin,
   Steward Co-Pilot chat, `page.reload()` persistence, `Escape` return, and `UNKNOWN` badge/funnel.
4. Zero `setInterval` in `anvil.html` and `0` `distro.scan_paths` findings across all v4 surfaces.
"""
from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import anchor_gui
import distro
import paths
import rnd_registry
from steward_cockpit import anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent

PIPELINE_PY_SRC = """\
from __future__ import annotations


def ingest_samples(count: int = 4) -> list[float]:
    \"\"\"Ingest deterministic latent samples for energy evaluation.\"\"\"
    return [float(i + 1) for i in range(count)]


def compute_energy_loop(samples: list[float]) -> tuple[float, float]:
    \"\"\"Compute mean quadratic energy E(z) and trigger a +Infinity tripwire.\"\"\"
    accum = 0.0
    z = 0.0
    for item in samples:
        z = float(item)
        accum += z * z
    energy = accum / float(len(samples) or 1)
    unstable_norm = float("inf")
    return energy, unstable_norm


def emit_summary(energy: float, unstable_norm: float) -> dict[str, float]:
    \"\"\"Emit structured summary dictionary.\"\"\"
    return {"energy": energy, "norm": unstable_norm}


if __name__ == "__main__":
    batch = ingest_samples(4)
    eng, norm_val = compute_energy_loop(batch)
    emit_summary(eng, norm_val)
"""

PAPER_TEX_SRC = r"""\documentclass{article}
\title{Quadratic Energy Flow Verification}
\begin{document}
\section{Objective}
We formalize quadratic latent energy across sequential flow stages.
\begin{algorithm}
\caption{Quadratic Energy Pass}
\begin{algorithmic}
\State Ingest latent vector $z$ via $\text{ingest\_samples}$
\State Evaluate $E(z)$ via $\text{compute\_energy\_loop}$
\end{algorithmic}
\end{algorithm}
\begin{equation}\label{eq:energy}
E(z) = \frac{1}{N}\sum_{i=1}^{N} z_i^2
\end{equation}
\end{document}
"""


def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    anvil_session._LOADED_MTIME_NS = Path(anvil_session.__file__).stat().st_mtime_ns
    monkeypatch.setattr(anvil_session, "_ANCHOR_ROOT", (tmp_path / "_v4_isolated_anchor").resolve())
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, tmp_path.resolve()),
    )


def test_cockpit_v4_bundle_isolation_consent_gates_and_zero_restart_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_tmp_workspace(monkeypatch, tmp_path)
    cdir = tmp_path / "sci_cockpit"
    sw_dir = tmp_path / "external_repo"
    cdir.mkdir()
    sw_dir.mkdir()
    (sw_dir / "pipeline.py").write_text(PIPELINE_PY_SRC, encoding="utf-8")
    (sw_dir / "paper.tex").write_text(PAPER_TEX_SRC, encoding="utf-8")

    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(sw_dir),
        paper_spec=str(sw_dir / "paper.tex"),
    )

    # 1. Per-cockpit v4 storage isolation: external software directory stays 100% untouched
    v4_dir = cdir / ".anvil" / "v4"
    assert v4_dir.is_dir()
    assert (v4_dir / "workbench_session.json").is_file()
    assert not (sw_dir / ".anvil").exists()

    # 2. Compact `?summary=1` status must stay < 15 KB without embedding `v4_bundle`
    sum_status = anvil_session.get_session_status(cdir, summary_only=True)
    assert sum_status["active"] is True
    assert sum_status["summary_only"] is True
    assert "v4_bundle" not in sum_status
    assert len(json.dumps(sum_status).encode("utf-8")) < 15_000

    # 3. Full `get_v4_cockpit_state` contract: native MathML, S1..Sk, N1..Nk, symbol conservation
    state_payload, state_code = anvil_session.get_v4_cockpit_state(cdir)
    assert state_code == 200
    assert state_payload["ok"] is True
    bundle = state_payload["v4_bundle"]
    assert bundle["has_paper"] is True
    eqs = bundle["paper_map"]["equations"]
    assert len(eqs) >= 1
    for eq in eqs:
        mml = eq["mathml"]
        assert "<math" in mml
        assert "$" not in mml
        ET.fromstring(mml)

    s_ids = [st["id"] for st in bundle["process_map"]["l1_stages"]]
    n_ids = [nt["id"] for nt in bundle["refactor_map"]["target_stages"]]
    assert len(s_ids) >= 1 and all(sid.startswith("S") for sid in s_ids)
    assert len(n_ids) >= 1 and all(nid.startswith("N") for nid in n_ids)
    sym_cons = bundle["refactor_map"]["symbol_conservation"]
    assert sym_cons.get("conserved", True) is True
    assert sym_cons.get("unaccounted_count", 0) == 0

    # 4. Fail-closed consent & argv execution policy gates on `POST /api/steward/anvil`
    refused_no_consent, c_nc = steward_routes.handle_post(
        str(cdir), "anvil", {"action": "v4_trace", "argv": ["python", "pipeline.py"]}
    )
    assert c_nc == 403 and refused_no_consent["ok"] is False

    refused_cmd_str, c_cmd = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "v4_trace", "cmd": "python pipeline.py", "operator_consent_confirmed": True},
    )
    assert c_cmd == 403 and refused_cmd_str["ok"] is False

    refused_shell_bin, c_ps = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "v4_trace",
            "argv": ["powershell", "-Command", "dir"],
            "operator_consent_confirmed": True,
        },
    )
    assert c_ps == 403 and refused_shell_bin["ok"] is False

    # Consented execution succeeds (200), stamps `has_trace=True`, catches `+Infinity`, keeps sw_dir clean
    traced_res, c_ok = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {
            "action": "v4_trace",
            "argv": ["python", "pipeline.py"],
            "operator_consent_confirmed": True,
        },
    )
    assert c_ok == 200 and traced_res["ok"] is True
    tr_bundle = traced_res["v4_bundle"]
    assert tr_bundle["has_trace"] is True
    assert not (sw_dir / ".anvil").exists()
    tripwires = tr_bundle["trace_summary"]["tripwires"]
    assert any(tw.get("kind") == "+Infinity" for tw in tripwires)
    funnel = tr_bundle["variable_catalog"]["funnel"]
    assert (
        funnel["all_state"]
        >= funnel["stage_scope"]
        >= funnel["delta_mutated"]
        >= funnel["anomalies_and_pinned_watches"]
        >= 1
    )

    # 5. Zero-restart hot-reload bridge (`probe_block_in_session` -> `__anvil_v4_op__`)
    bridge_out = anvil_session.probe_block_in_session(
        cdir,
        "__anvil_v4_op__",
        lock_description=json.dumps({"op": "v4_session", "payload": {"pinned_watches": ["z"]}}),
    )
    assert bridge_out["ok"] is True and bridge_out["http_status"] == 200
    saved_ws = json.loads((v4_dir / "workbench_session.json").read_text(encoding="utf-8"))
    assert "z" in saved_ws["pinned_watches"]


def test_cockpit_v4_five_surface_failure_states_and_unknown_vs_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_tmp_workspace(monkeypatch, tmp_path)
    empty_cdir = tmp_path / "empty_cockpit"
    empty_cdir.mkdir()

    # Empty repository (both pre-launch and started session) -> 200 `empty-but-valid`
    pre_payload, pre_code = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert pre_code == 200
    assert pre_payload["status_kind"] == "empty-but-valid"
    assert pre_payload["badge"] == "EMPTY"
    assert pre_payload["message"] == "Repository parsed cleanly with 0 matched items"
    assert pre_payload["unknown_state"] is False

    anvil_session.start_cockpit_session(empty_cdir, software_spec=".")
    act_payload, act_code = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert act_code == 200
    assert act_payload["status_kind"] == "empty-but-valid"
    assert act_payload["badge"] == "EMPTY"
    assert act_payload["message"] == "Repository parsed cleanly with 0 matched items"
    assert act_payload["unknown_state"] is False

    # Corrupt `workbench_session.json` -> 500 `UNKNOWN` (never `0` or `EMPTY`)
    v4_dir = empty_cdir / ".anvil" / "v4"
    v4_dir.mkdir(parents=True, exist_ok=True)
    ws_file = v4_dir / "workbench_session.json"
    ws_file.write_text("{corrupt-workbench-session", encoding="utf-8")
    p500, c500 = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert c500 == 500
    assert p500["badge"] == "UNKNOWN"
    assert p500["unknown_state"] is True
    assert "Session/trace store unreadable (unknown state, not empty)" in p500["message"]
    ws_file.unlink()

    # Corrupt `last_trace.json` -> 502 `REJECTED_GARBAGE` fail-closed
    trace_file = v4_dir / "last_trace.json"
    trace_file.write_text("{corrupt-trace-payload", encoding="utf-8")
    p502, c502 = anvil_session.get_v4_cockpit_state(empty_cdir)
    assert c502 == 502
    assert p502["badge"] == "REJECTED_GARBAGE"
    assert "Malformed trace/validator payload — rejected fail-closed" in p502["message"]


def _check_svg_no_overlap_and_min_font(page) -> dict:
    return page.evaluate(
        """() => {
        const overlaps = [];
        const svg = document.querySelector('#svg-container svg');
        if (svg) {
          const texts = Array.from(svg.querySelectorAll('text')).filter(t => {
            const r = t.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          });
          for (let i = 0; i < texts.length; i++) {
            const a = texts[i].getBoundingClientRect();
            for (let j = i + 1; j < texts.length; j++) {
              const b = texts[j].getBoundingClientRect();
              const ix = Math.min(a.right, b.right) - Math.max(a.left, b.left);
              const iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
              if (ix > 2.0 && iy > 2.0) {
                overlaps.push([texts[i].textContent, texts[j].textContent]);
              }
            }
          }
        }
        let minFont = 999;
        const candidates = document.querySelectorAll(
          '.top-deck button, .top-deck span, #main-workbench-split button, #main-workbench-split span, #svg-container text'
        );
        candidates.forEach(el => {
          if (el.closest('[hidden]')) return;
          const r = el.getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) return;
          const fs = parseFloat(window.getComputedStyle(el).fontSize || '12');
          if (!Number.isNaN(fs) && fs < minFont) minFont = fs;
        });
        return { overlaps, minFont: minFont === 999 ? 12 : minFont };
        }"""
    )


def _grid_column_ratios(page) -> list[float]:
    cols = page.evaluate(
        """() => {
        const raw = window.getComputedStyle(document.getElementById('main-workbench-split')).gridTemplateColumns;
        return raw.split(/\\s+/).map(v => parseFloat(v)).filter(v => !Number.isNaN(v) && v > 0);
        }"""
    )
    total = sum(cols) or 1.0
    return [c / total for c in cols]


def test_cockpit_anvil_v4_playwright_gate6_and_cockpit_takeover_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pw = pytest.importorskip("playwright.sync_api")
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "anchor_data"))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    monkeypatch.setenv("ANCHOR_AUTH_MODE", "open")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    paths.ensure_data_dirs()

    proj_dir = tmp_path / "flow_cockpit"
    proj_dir.mkdir()
    (proj_dir / "pipeline.py").write_text(PIPELINE_PY_SRC, encoding="utf-8")
    (proj_dir / "paper.tex").write_text(PAPER_TEX_SRC, encoding="utf-8")
    entry = rnd_registry.add_project("Flow Cockpit", proj_dir)
    pid = entry["id"]

    server = anchor_gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            page = context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            page.goto(f"http://127.0.0.1:{port}/steward-static/anvil.html?pid={pid}", wait_until="networkidle")
            page.locator("#cockpit-launch-screen").wait_for(state="visible", timeout=10000)

            # Launch Anvil v4 Paper-to-Software mode from Launch Screen
            page.fill("#inputPaperTarget", "paper.tex")
            page.click("#btnStartPaper")
            page.locator("#main-workbench-split").wait_for(state="visible", timeout=15000)

            # Verify Posture 1 (48% / 52% grid columns)
            r1 = _grid_column_ratios(page)
            assert len(r1) == 2
            assert abs(r1[0] - 0.48) < 0.02 and abs(r1[1] - 0.52) < 0.02

            # Check SVG 0-overlap and minFont >= 11px across all visible lens tabs and inspector tabs
            for sel in (
                "#lens-tab-understand",
                "#lens-tab-refactor",
                "#lens-tab-paper",
                "#lens-tab-debug",
                "#lens-tab-profile",
            ):
                loc = page.locator(sel)
                if loc.is_visible():
                    loc.click()
                    chk = _check_svg_no_overlap_and_min_font(page)
                    assert chk["overlaps"] == [], f"SVG overlaps on {sel}: {chk['overlaps']}"
                    assert chk["minFont"] >= 11.0, f"minFont < 11px on {sel}: {chk['minFont']}"

            page.click("#lens-tab-understand")
            for insp_name in ("story", "ide", "funnel", "xval", "walkthrough"):
                tab_loc = page.locator(f'.insp-tab[data-inspector="{insp_name}"]')
                if tab_loc.is_visible():
                    tab_loc.click()
                    chk = _check_svg_no_overlap_and_min_font(page)
                    assert chk["overlaps"] == []
                    assert chk["minFont"] >= 11.0

            # Consent Modal -> Consented Subprocess Trace -> `TRACED` provenance stamp
            page.click("#btn-run-trace")
            modal = page.locator("#trace-consent-modal")
            modal.wait_for(state="visible", timeout=5000)
            modal_txt = modal.inner_text()
            assert "consented_local_subprocess" in modal_txt
            assert "NOT an OS/VM sandbox" in modal_txt
            page.fill("#consent-argv-input", '["python", "pipeline.py"]')
            page.click("#btn-confirm-trace-consent")
            modal.wait_for(state="hidden", timeout=15000)
            assert "TRACED" in page.locator("#provenance-stamp").inner_text()

            # Expand Scientific IDE Debugger -> Posture 2 (25% / 45% / 30%)
            page.click("#btn-open-ide-debugger")
            page.locator("#full-ide-pane").wait_for(state="visible", timeout=5000)
            r2 = _grid_column_ratios(page)
            assert len(r2) == 3
            assert abs(r2[0] - 0.25) < 0.02 and abs(r2[1] - 0.45) < 0.02 and abs(r2[2] - 0.30) < 0.02

            # Toggle Paper Light / Studio Dark
            page.click("#btn-ide-theme")
            assert "Studio Dark" in page.locator("#btn-ide-theme").inner_text()

            # Toggle breakpoint and pin variable watch token
            bp_btn = page.locator(".full-bp-btn").first
            bp_btn.wait_for(state="visible", timeout=5000)
            bp_btn.click()
            assert "bp-on" in (bp_btn.get_attribute("class") or "")

            tok_span = page.locator("span.code-ident-tok[data-var]").first
            tok_span.wait_for(state="visible", timeout=5000)
            pinned_var = tok_span.get_attribute("data-var") or ""
            tok_span.click()
            assert "1 breakpoints" in page.locator("#full-ide-bp-badge").inner_text()
            assert "1 pinned" in page.locator("#full-ide-bp-badge").inner_text()

            # Steward Co-Pilot chat turn
            page.fill("#chat-input", "Explain S1 stage contract and tripwires")
            page.click("#btn-chat-send")
            page.wait_for_function(
                "() => document.querySelectorAll('#chat-messages .chat-msg.user').length >= 1",
                timeout=10000,
            )

            # Verify page.reload() persistence of Posture 2, Studio Dark, breakpoint, watch, and chat
            page.wait_for_timeout(250)
            page.reload(wait_until="networkidle")
            page.locator("#full-ide-pane").wait_for(state="visible", timeout=10000)
            assert "Studio Dark" in page.locator("#btn-ide-theme").inner_text()
            assert page.locator(".full-bp-btn.bp-on").count() >= 1
            if pinned_var:
                assert page.locator(f'span.code-ident-tok.pinned[data-var="{pinned_var}"]').count() >= 1

            # Escape returns cleanly to Posture 1 (48% / 52%)
            with page.expect_response(lambda r: "/api/steward/anvil" in r.url and r.request.method == "POST", timeout=5000):
                page.keyboard.press("Escape")
            page.locator("#full-ide-pane").wait_for(state="hidden", timeout=5000)
            r_back = _grid_column_ratios(page)
            assert len(r_back) == 2
            assert abs(r_back[0] - 0.48) < 0.02 and abs(r_back[1] - 0.52) < 0.02

            # Zero console or page errors across the entire healthy roundtrip
            assert console_errors == [], f"Unexpected console errors: {console_errors}"
            assert page_errors == [], f"Unexpected page errors: {page_errors}"

            # Inject corrupt `workbench_session.json` on disk -> reload -> `UNKNOWN` (never `0`)
            (proj_dir / ".anvil" / "v4" / "workbench_session.json").write_text(
                "{corrupt-json-store", encoding="utf-8"
            )
            page.reload(wait_until="networkidle")
            page.locator("#surface-state-banner").wait_for(state="visible", timeout=10000)
            assert page.locator("#surface-state-badge").inner_text().strip() == "UNKNOWN"
            funnel_all = page.locator("#funnel-count-all").inner_text().strip()
            assert funnel_all == "UNKNOWN" and funnel_all != "0"
            assert page_errors == [], f"Unexpected page errors after corrupt store: {page_errors}"

            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_anvil_v4_cockpit_distro_and_aegis_cleanliness() -> None:
    anvil_html_path = ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html"
    assert "setInterval" not in anvil_html_path.read_text(encoding="utf-8")

    bundled_files = [
        p
        for p in sorted((ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil").rglob("*"))
        if p.is_file() and not any(part in (".ruff_cache", "__pycache__", ".pytest_cache") for part in p.parts)
    ]
    abs_targets = [
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html",
        ANCHOR_ROOT / "tests" / "test_anvil_v4_cockpit_workbench_2026_11_18.py",
        *bundled_files,
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in abs_targets]
    hits = distro.scan_paths(pairs, root=ANCHOR_ROOT)
    assert hits == [], f"Unexpected distro PII/secret hits: {hits}"
