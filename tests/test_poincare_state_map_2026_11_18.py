"""Regression & Chromium UI tests for Dual-Poincaré Deep-Memory State Maps (2026-11-18).

Covers:
1. Exact log-polar hyperbolic distance stability past r = 600 (immune to IEEE-754
   float64 r = 39 Cartesian Poincaré horizon collapse).
2. Sarkar combinatorial layout + Popularity-Similarity Radial Importance Promotion
   + bi-temporal Boneyard centrifugal recession for superseded/dismissed deliverables.
3. Isometric Möbius gyrovector re-centering T_{-a}(z) = (z - a) / (1 - conj(a)*z)
   mapping any focus node to (0, 0) while preserving geodesic neighborhood structure.
4. MERA-Poincaré 2-Resolution Ancestor-Closed Marginal-Density Knapsack parser +
   12-token Horizon Breadcrumbs + Transversal Poincaré Section fingerprint cache.
5. Path-containment guard (`resolve_contained_effort_dir`) + Gandalf Poincaré map
   builder + interactive 2D Möbius-zoomable SVG Poincaré Disk in headless Chromium.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import poincare_state_map as psm


def test_logpolar_hyperbolic_distance_stable_past_r600():
    # Naive Cartesian Poincaré ball ||x|| = tanh(r/2) rounds to 1.0 in float64 above r = 39.
    assert math.tanh(50.0 / 2.0) == 1.0
    # Log-polar hyperbolic distance stays finite, positive, and exact at r = 600 (>10^260 leaves).
    d_same = psm.hyperbolic_distance_logpolar(600.0, 0.4, 600.0, 0.4)
    d_radial = psm.hyperbolic_distance_logpolar(580.0, 0.4, 600.0, 0.4)
    d_ang = psm.hyperbolic_distance_logpolar(600.0, 0.2, 600.0, 1.9)
    assert d_same == pytest.approx(0.0, abs=1e-9)
    assert d_radial == pytest.approx(20.0, rel=1e-6)
    assert math.isfinite(d_ang) and d_ang > 1100.0


def test_radial_importance_promotion_and_boneyard_recession():
    raw_nodes = [
        {"id": "root", "parent_id": "", "kind": "north_star", "title": "North Star", "importance": 1.0, "age_hours": 1.0},
        {"id": "w1", "parent_id": "root", "kind": "wave", "title": "Wave 1", "importance": 0.85, "age_hours": 24.0},
        {"id": "locked-inv", "parent_id": "w1", "kind": "decision", "title": "Locked Theorem Invariant", "importance": 0.98, "age_hours": 120.0},
        {"id": "chatter", "parent_id": "w1", "kind": "turn", "title": "Routine status chatter", "importance": 0.35, "age_hours": 120.0},
        {"id": "old-draft", "parent_id": "w1", "kind": "deliverable", "title": "Superseded Draft v0", "importance": 0.90, "age_hours": 48.0, "valid_until": "superseded", "lifecycle_state": "superseded"},
    ]
    laid = {nd["id"]: nd for nd in psm.sarkar_combinatorial_layout(raw_nodes)}
    assert laid["root"]["r_eff"] == 0.0
    # High-importance invariant is radially promoted much closer to origin than routine chatter at identical tree depth
    assert laid["locked-inv"]["r_eff"] < laid["chatter"]["r_eff"]
    assert laid["locked-inv"]["survival"] > laid["chatter"]["survival"] * 3.0
    # Superseded deliverable recedes outward into the Boneyard horocycle
    assert laid["old-draft"]["superseded"] is True
    assert laid["old-draft"]["r_eff"] >= 3.6


def test_mobius_recenter_translates_focus_to_origin_and_preserves_unit_disk():
    raw_nodes = [
        {"id": "root", "parent_id": "", "kind": "north_star", "title": "Root", "importance": 1.0},
        {"id": "a", "parent_id": "root", "kind": "wave", "title": "Branch A", "importance": 0.85},
        {"id": "a1", "parent_id": "a", "kind": "deliverable", "title": "Paper PDF", "importance": 0.94},
        {"id": "b", "parent_id": "root", "kind": "wave", "title": "Branch B", "importance": 0.80},
    ]
    mdoc = {"title": "Test Map", "nodes": psm.sarkar_combinatorial_layout(raw_nodes), "corpus_raw_tokens": 500}
    recentered = psm.mobius_recenter_map(mdoc, "a1")
    by_id = {nd["id"]: nd for nd in recentered["nodes"]}
    assert by_id["a1"]["disk_x"] == pytest.approx(0.0, abs=1e-6)
    assert by_id["a1"]["disk_y"] == pytest.approx(0.0, abs=1e-6)
    for nd in recentered["nodes"]:
        mag = math.hypot(nd["disk_x"], nd["disk_y"])
        assert mag < 1.0


def test_cockpit_builder_section_cache_knapsack_and_containment(tmp_path: Path):
    cdir = tmp_path / "Sample Effort"
    ecg = cdir / ".ecgberht"
    ecg.mkdir(parents=True)
    (cdir / "ECGBERHT.md").write_text("# Sample Effort\n\nProve hyperbolic rate-distortion bounds.\n", encoding="utf-8")
    (cdir / "roadmap.json").write_text(
        json.dumps({
            "goal": "Prove hyperbolic rate-distortion bounds",
            "steps": [
                {"id": "s1", "name": "Wave 1 Literature", "status": "done", "done_when": "Ledger complete"},
                {"id": "s2", "name": "Wave 2 Engine", "status": "active", "done_when": "Engine verified"},
            ],
        }),
        encoding="utf-8",
    )
    (cdir / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n"
        "| Main Theorem Report | reports/theorem.pdf | 2026-11-18 | 2 |\n"
        "| Old Draft v0 | reports/old.pdf | 2026-11-10 | 1 |\n",
        encoding="utf-8",
    )
    (ecg / "dismissed-deliverables.json").write_text(
        json.dumps({"items": {"reports/old.pdf": {"disposition": "superseded"}}}),
        encoding="utf-8",
    )
    turns = [
        {"role": "john", "text": f"Turn {i}: Focus on theorem {i} and preserve North Star invariants." * 6, "at": "2026-11-18T12:00:00Z"}
        for i in range(1, 25)
    ]
    (ecg / "conversation-log.json").write_text(json.dumps({"turns": turns}), encoding="utf-8")

    mdoc1 = psm.build_cockpit_poincare_map(cdir, persist=True, force=True)
    assert (ecg / "poincare-state.json").is_file()
    assert mdoc1["boneyard_node_count"] >= 1
    assert mdoc1["active_node_count"] >= 20

    # Transversal section fingerprint cache hit returns identical fingerprint
    mdoc2 = psm.build_cockpit_poincare_map(cdir, persist=False, force=False)
    assert mdoc2["section_fingerprint"] == mdoc1["section_fingerprint"]

    # Knapsack strictly respects token budget, excludes superseded boneyard nodes, and guarantees ancestor closure
    pack = psm.parse_deep_memory_window(mdoc1, focus_id="s2", query="theorem invariants", budget_tokens=450)
    assert pack["used_tokens"] <= 450
    sel_ids = {nd["id"] for nd in pack["selected_nodes"]}
    by_id = {nd["id"]: nd for nd in mdoc1["nodes"]}
    for sid in sel_ids:
        assert not by_id[sid]["superseded"]
        pid = by_id[sid].get("parent_id")
        if pid:
            assert pid in sel_ids
    assert len(pack["horizon_breadcrumbs"]) >= 1
    assert "[POINCARÉ DEEP-MEMORY STATE CAPSULE" in pack["formatted_capsule"]

    # Containment guard blocks path traversal
    assert psm.resolve_contained_effort_dir(tmp_path, "Sample Effort") == cdir.resolve()
    assert psm.resolve_contained_effort_dir(tmp_path, "../outside") is None

    # Per-turn RAM-cached Möbius recall hits RAM cache and promotes matched focus node to verbatim
    cap1 = psm.fast_turn_recall_capsule(cdir, query="Main Theorem Report", budget_tokens=600)
    cap2 = psm.fast_turn_recall_capsule(cdir, query="Main Theorem Report", budget_tokens=600)
    assert "[POINCARÉ DEEP-MEMORY STATE CAPSULE" in cap1
    assert cap1.splitlines()[1:] == cap2.splitlines()[1:]
    assert "[FULL · deliverable" in cap2


def test_interactive_poincare_viewer_mobius_zoom_in_chromium(tmp_path: Path):
    pw_mod = pytest.importorskip("playwright.sync_api")
    gandalf_sample = {
        "verdict": "Use Parent-Relative Log-Polar Sarkar layout with Radial Importance Promotion.",
        "reasoning": "Avoids float64 horizon collapse past r=39.",
        "findings": [
            {"kind": "diagnose", "severity": "critical", "rung": "OBSERVED", "verdict": "Horizon underflow at r=39", "reasoning": "1 - tanh(r/2) rounds to zero."},
            {"kind": "situate", "severity": "major", "rung": "CLAIMED", "verdict": "Popularity-Similarity geometry", "reasoning": "Krioukov radial-angular mapping."},
        ],
        "elevations": [
            {"tier": "GROUNDED", "value_if_true": "high", "verdict": "Ship interactive 2D Möbius viewer", "reasoning": "Sub-millisecond focus translation.", "what_would_refute_it": "If SVG lag exceeded 50ms."},
        ],
        "kill_log": {
            "elevations": [{"verdict": "Naive Cartesian float64 storage"}],
        },
    }
    mdoc = psm.build_gandalf_poincare_map(gandalf_sample)
    html_file = tmp_path / "viewer.html"
    html_file.write_text(psm.render_poincare_viewer_html(mdoc, initial_budget=8192), encoding="utf-8")

    with pw_mod.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(html_file.as_uri(), wait_until="domcontentloaded")
            target_g = page.locator('[data-node-id="elevation-1"]')
            assert target_g.count() == 1
            # Before click, elevation-1 is away from origin
            before_cx = float(target_g.locator("circle").last.get_attribute("cx") or "1")
            before_cy = float(target_g.locator("circle").last.get_attribute("cy") or "1")
            assert math.hypot(before_cx, before_cy) > 0.15

            # Click peripheral node -> animated Möbius translation brings it to (0, 0)
            target_g.click(force=True)
            page.wait_for_timeout(420)
            after_g = page.locator('[data-node-id="elevation-1"]')
            after_cx = float(after_g.locator("circle").last.get_attribute("cx") or "1")
            after_cy = float(after_g.locator("circle").last.get_attribute("cy") or "1")
            assert math.hypot(after_cx, after_cy) < 0.015
            assert "Ship interactive 2D Möbius viewer" in page.locator("#pmSelTitle").inner_text()
        finally:
            browser.close()
