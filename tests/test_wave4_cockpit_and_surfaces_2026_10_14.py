"""Wave 4 (2026-10-14): AI Cockpit, Cave of Wonders, and Star Chart workflow upgrades.

1. AI Cockpit (v1.html, shared.js, md.js, shared.css):
   - Proactive Steward Next Steps mounted at the TOP of the Steward dialogue (.main > [data-steward-next-top]).
   - Cockpit File Drop Zone ([data-cockpit-drop] + full-cockpit drag-and-drop on .main) saving dropped files directly into the cockpit's associated directory via /api/upload.
   - Universal clickable Open (.md rendered, .pdf inline) and Download (⬇ &download=1) links on all referenced files across Steward dialogue (md.js, including root-level filenames), Deliverables (delivRow), and Files produced (renderFiles).
   - Persistent Left-Panel Plan Progress Bar ([data-progress-bar]) and Proactive Foundry Tool Scout ([data-tool-scout]).
2. Cave of Wonders & Star Chart (home_rows.py, high_seat_page.py, campaign_page.py):
   - Embedded plan progress bars (.t-prog) on seated Cave of Wonders cards.
   - Segmented multi-step/wave rollup pips (.gpips) on Star Chart goal tiles.
"""
from datetime import date
from pathlib import Path

import campaign_page as cpg
import high_seat_page as hsp
import home_rows as hr

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "steward_cockpit" / "static"


def test_proactive_steward_next_steps_sits_at_the_top_of_the_steward_dialogue():
    v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    main_block = v1[v1.index('<div class="main">'):v1.index('<div class="statustab"')]
    assert main_block.index("data-steward-next-top") < main_block.index('class="scroll"')
    assert 'src="/vendor/brand/anchor-tab-48.png"' in v1
    assert "let _sntOpen = false;" in js
    assert "function renderTopNextSteps()" in js
    assert 'const topHost = $("[data-steward-next-top]");' in js
    assert "Next Step Recommendation" in js and "Run Next Step" in js
    assert "All deliverables" in js
    assert ".steward-next-top" in css and ".snt-bar" in css


def test_cockpit_file_drop_zone_lands_files_in_cockpit_directory():
    v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
    cp = (STATIC / "cockpit.html").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    upper_deliv = v1[v1.index("data-delivmount"):v1.index("data-pstatus")]
    bottom_files = v1[v1.index("data-filesect"):]
    assert "data-cockpit-drop" not in upper_deliv
    assert v1.count('type="file"') == 1
    assert cp.count('type="file"') == 1
    assert "data-cockpit-drop" in bottom_files and "data-cockpit-dropfile" in bottom_files and "data-drop-dir" in bottom_files
    assert "function wireCockpitDrop()" in js
    assert 'post("/api/upload", { name: file.name, data_b64: b64, mode: "keepboth", sub: "" })' in js
    assert ".cockpit-dropbar" in css


def test_all_referenced_files_have_clickable_open_and_download_links():
    md_js = (STATIC / "md.js").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    # md.js links root-level and nested files (.md, .pdf, .json, .py, etc.) with both Open and Download (⬇)
    assert "function mdDownloadHref(href)" in md_js
    assert 'el("a", "md-dl", "⬇")' in md_js
    assert '(inner.includes("/") || inner.includes("\\\\"))' not in md_js
    # shared.js adds ⬇ download links in delivRow and renderFiles
    assert "function producedFileDownloadHref(f)" in js
    assert 'el("a", "ddl-inline", "\\u2b07")' in js
    assert ".md-dl, .ddl-inline" in css


def test_left_panel_plan_progress_bar_and_proactive_tool_scout():
    v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    rail = v1[v1.index('<div class="rail">'):v1.index('<div class="railtab"')]
    assert "data-progress-bar" in rail and "data-progress-fill" in rail and "data-tool-scout" in rail
    assert "Proactive Foundry Tool Scout" in js


def test_cave_cards_and_star_chart_tiles_render_multi_step_progress_and_pips(tmp_path):
    # 1. home_rows.project_facts populates steps_done and steps_total from roadmap.json
    proj = tmp_path / "Proj"
    proj.mkdir()
    (proj / "ECGBERHT.md").write_text("# Proj\n", encoding="utf-8")
    (proj / "roadmap.json").write_text(
        '{"roadmap_projection": [{"id": "s1", "name": "Step 1", "status": "done"}, '
        '{"id": "s2", "name": "Step 2", "status": "active"}, '
        '{"id": "s3", "name": "Step 3", "status": "planned"}]}',
        encoding="utf-8",
    )
    facts = hr.project_facts({"id": "p1", "name": "Proj", "folder_path": str(proj)}, today=date(2026, 10, 14))
    assert facts["steps_done"] == 1 and facts["steps_total"] == 3
    # 2. high_seat_page._card embeds .t-prog with percentage and step count
    card_html = hsp._card({"id": "p1", "name": "Proj", "blurb": "Test"}, facts, "")
    assert 'class="t-prog"' in card_html and "1/3 steps" in card_html and 'width:33%' in card_html
    # 3. campaign_page._gtile embeds .gpips segmented pips
    init = {
        "id": "g1", "name": "Goal 1", "tier": 1, "area": "tools", "status": "active",
        "done_when": "All done", "pace": "2026-10-20", "next_deadline": "2026-10-18",
        "needs": [], "done_count": 1,
        "parts": [
            {"id": "p1", "kind": "step", "text": "Part 1", "done": True, "needs_you": False, "broken": False, "status": "done"},
            {"id": "p2", "kind": "step", "text": "Part 2", "done": False, "needs_you": True, "broken": False, "status": "waiting"},
        ],
    }
    tile_html = cpg._gtile(init, {"today": date(2026, 10, 14), "working": set(), "premortems": {}}, "1")
    assert 'class="gpips"' in tile_html and '<i class="gp d"></i><i class="gp n"></i>' in tile_html


def test_cockpit_html_multi_effort_shell_has_top_next_steps_dropzone_and_downloads():
    cp_html = (STATIC / "cockpit.html").read_text(encoding="utf-8")
    assert 'data-steward-next-top' in cp_html
    assert 'data-cockpit-drop' in cp_html and 'data-cockpit-dropfile' in cp_html
    assert 'Open & Run Next Step' in cp_html
    assert 'el("a", "ddl-inline", "\\u2b07")' in cp_html


def test_doctor_resolve_all_and_resolve_this_one_click_fixes_stale_service_code():
    import anchor_gui as ag
    import doctor_plain as dp
    from unittest import mock

    issue = {"component": "the running service runs the checked code", "detail": "running sources 3e084c2, checked 60f9a68"}
    ex = dp.explain(issue)
    assert ex["kind"] == dp.KIND_SERVICE_STALE_CODE
    assert dp.decide([ex], [{"path": "/api/version", "ok": True}, {"path": "/api/status", "ok": True}]) == "rerun"

    sent = []

    class FakeH:
        def _send_json(self, data, code=200):
            sent.append((code, data))

    with mock.patch.object(ag, "_doctor_stats", return_value={"issues": [issue], "autofixes": []}), \
         mock.patch.object(ag, "_doctor_live_probe", side_effect=lambda p, timeout=4.0: {"path": p, "ok": True, "code": 200, "ms": 2}), \
         mock.patch.object(ag, "_doctor_sync_live_code", return_value="8233ddd+new") as sync_mock, \
         mock.patch.object(ag, "_doctor_start_healthcheck_run", return_value={"ok": True, "pid": 42}) as hc_mock:
        ag.handle_doctor_resolve_all(FakeH(), "/api/doctor/resolve_all", {})
    assert sent[0][0] == 200 and sent[0][1]["decision"] == "rerun"
    sync_mock.assert_called_once()
    hc_mock.assert_called_once()


def test_wave4_refinements_spend_popover_milestone_eta_and_status_state_button():
    v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    w4 = (STATIC / "wave4-surfaces-mockup.html").read_text(encoding="utf-8")

    # 1. Spend total chip + click-to-open breakdown popover matching wave4-surfaces-mockup.html
    assert "spend-popover" in js and "Spend, Tokens & Time Breakdown" in js
    assert "sp-table" in js and "Campaign Total" in js
    assert ".spend-popover" in css and ".spend-popover table.sp-table" in css
    assert "spendPopover" in w4 and "Total $14.80" in w4

    # 2. Milestone-tied 3-part ETA formatting + compact status table
    assert "const formatMilestoneEta =" in js
    assert "eta-compact" in js and "LIVE STATUS" in js
    assert "Current step" in js and "Next milestone" in js and "Whole effort" in js
    assert "1. Wave 4 &amp; 5 Sign-Off:" in w4 and "2. Wave 6 Cave Tidy:" in w4 and "3. Wave 7 Star Chart + Test Gate:" in w4

    # 3. Status State button + left/right side restore tiles + Previous Status Updates log + Second-window auto-collapse
    assert 'class="status-state-pill"' in v1 and 'class="statustab-state"' in v1
    assert 'data-prev-status-log' in v1 and 'data-prev-status-list' in v1
    assert 'function enterSecondWindowMode()' in v1 and 'function exitSecondWindowMode()' in v1
    assert 'anchor-app-split' in v1
    assert 'function personaName()' in js
    assert 'id="leftSideTile"' in w4 and 'id="rightSideTile"' in w4 and 'id="statusStateBtn"' in w4
    assert 'id="prevStatusLog"' in w4 and 'id="artifactWindow"' in w4
    assert 'openArtifactInSecondWindow' in w4 and 'closeArtifactSecondWindow' in w4

    # 4. Goal Tagline Bar + Boneyard Icon + No Persona Switcher in AI Cockpits + Mutual Anvil Toggle Tile (No Crossed Hammers)
    assert 'id="goalTaglineBar"' in w4 and 'id="boneyardBtn"' in w4
    assert 'class="persona-switch"' not in w4
    assert 'id="launchAnvilTile"' in w4 and 'id="anvilTakeoverView"' in w4 and 'id="returnToCockpitTile"' in w4
    assert 'data-anvil-toggle' in v1 and 'data-anvil-takeover' in v1 and 'data-anvil-return' in v1
    assert "⚒" not in w4 and "⚒" not in v1


def test_wave5_anvil_mockup_typeset_math_and_persistent_dialogue_dock():
    w5 = (STATIC / "wave5-anvil-mockup.html").read_text(encoding="utf-8")
    # 1. Zero raw LaTeX dollar strings in the HTML body
    assert "\\mathcal" not in w5 and "\\sum" not in w5
    assert "<math" in w5 and "<mfrac>" in w5 and "<munderover>" in w5
    # 2. Persistent right-side Anvil Agent Dialogue Dock across all 4 tabs
    assert 'class="anvil-dialogue-dock"' in w5
    assert 'id="dockContextLabel"' in w5 and 'id="globalAnvilChat"' in w5 and 'id="globalAnvilInput"' in w5
    assert "all 4 pages of Anvil" in w5
    # 3. Locked Option 1 Recommended (Crystalline Sword Transformation) Anvil icon + AI Cockpit Return Top Tile + Zero Crossed Hammers + Zero Unselected Icon Options
    assert 'src="/vendor/brand/anvil-option-2-sword-crystal-v1.jpg"' in w5
    assert 'src="/vendor/brand/anvil-option-2-sword-crystal-v2.jpg"' not in w5
    assert 'src="/vendor/brand/anvil-option-2-blueprint-forge.jpg"' not in w5
    assert 'id="returnToCockpitBtn"' in w5
    assert "⚒" not in w5


def test_top_deliverables_strip_and_right_status_bar_deliverables_tab():
    v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    cp_html = (STATIC / "cockpit.html").read_text(encoding="utf-8")

    # 1. Top New Deliverables Strip in v1.html bar
    assert 'data-top-deliverables' in v1
    assert 'const topStrip = $("[data-top-deliverables]");' in js
    assert ".top-deliv-strip" in css and ".file-chip.tds-chip" in css
    assert 'ev.target.closest("[data-top-deliverables], a, button, details, summary")' in js

    # 2. Right-hand DELIVERABLES tab matches wave4-surfaces-mockup.html
    assert "deliv-group-lbl" in js and "Open 2nd Win" in js
    assert "const hasCurrent = items.some(i => i.is_current === true);" in js

    # 3. Outer project cockpit.html loadDeliv renders openable paths as real <a> links
    assert "const isClickable = !!(it.route || (it.openable && it.path));" in cp_html
    assert 'const fn = el(isClickable ? "a" : "span", "fn", "• " + it.what);' in cp_html


def test_anvil_icon_and_skill_foundry_registration():
    import foundry_page as fp
    from steward_cockpit import steward_routes as sr

    # 1. Custom icon files exist in Anchor vendor/brand and Skill Foundry skills/anvil/assets
    assert (ROOT / "vendor" / "brand" / "anvil-icon.jpg").is_file()
    assert (ROOT / "vendor" / "brand" / "anvil-option-1-forge-blade.jpg").is_file()
    assert (ROOT / "vendor" / "brand" / "anvil-option-2-blueprint-forge.jpg").is_file()
    assert (ROOT / "vendor" / "brand" / "anvil-option-3-crucible-crest.jpg").is_file()
    anvil_dir = Path(r"C:\dev\Skill Foundry\skills\anvil")
    assert (anvil_dir / "assets" / "icon.jpg").is_file()

    # 2. Registered in foundry_page.py, steward_routes.py, and skill-icons.js
    assert ("anvil", "anvil-icon.jpg") in fp.ICON_NAMES
    assert fp.DISPLAY_NAMES.get("anvil") == "Anvil"
    assert "Anvil" in sr.SKILLS
    assert sr.SKILL_ICONS.get("Anvil") == "anvil-icon.jpg"
    assert sr.SKILL_ICONS.get("anvil") == "anvil-icon.jpg"
    icons_js = (STATIC / "skill-icons.js").read_text(encoding="utf-8")
    assert 'name: "Anvil"' in icons_js and '"anvil-icon.jpg"' in icons_js

    # 3. Skill Foundry detail for anvil loads cleanly with zero issues
    detail = fp.skill_detail("anvil")
    assert detail is not None
    assert detail["skill"]["name"] == "Anvil"
    assert detail["skill"]["icon"] in ("/brand/anvil-icon.jpg", "/foundry/icon?skill=anvil")
    assert detail["libraryIssues"] == []
    assert detail["processMap"]["issues"] == []
    assert detail["knowledgeMap"]["issues"] == []


def test_cave_of_wonders_provider_summary_single_line_dictation_and_iframe_reload():
    from steward_cockpit import steward_routes as sr

    # 1. Cave of Wonders left rail includes open Connections & capacity · Providers summary
    hsp_src = (ROOT / "high_seat_page.py").read_text(encoding="utf-8")
    assert '<details class="cap provider-history" open>' in hsp_src
    assert 'Connections &amp; capacity &middot; Providers' in hsp_src
    assert '/static/provider-controls.js?v=' in hsp_src

    # 2. Ask Aladdin single-line-safe fitComposer + no horizontal scrollbar
    sd_js = (ROOT / "static" / "steward-dialogue.js").read_text(encoding="utf-8")
    sd_css = (ROOT / "static" / "steward-dialogue.css").read_text(encoding="utf-8")
    assert "box.style.height = 'auto';" in sd_js
    assert "overflow-x:hidden" in sd_css and "overflow-x: hidden" in (STATIC / "shared.css").read_text(encoding="utf-8")

    # 3. Scoped per-iframe reload key in steward_routes._CLIENT_SHIM so all Anchor.exe cockpit tiles reload
    assert "'steward_reloaded_for:' + location.pathname + location.search" in sr._CLIENT_SHIM


def test_wave5_5_and_5_6_proactive_deliverables_flat_plan_clear_wait_and_parable_of_oranges(tmp_path):
    import json
    from steward_cockpit import steward_routes as sr

    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    ps_html = (ROOT / "static" / "provider-setup.html").read_text(encoding="utf-8")
    ps_css = (ROOT / "static" / "provider-setup.css").read_text(encoding="utf-8")
    cj_py = (ROOT / "steward_cockpit" / "code_jobs.py").read_text(encoding="utf-8")

    # 1. Single-line top deliverables strip with best deliverables + folded-by-default right panel Deliverables + clean step cards
    assert "let _delivOpen = false;" in js
    assert "All in Deliverables (" in js and ".file-chip.tds-chip" in css
    assert "step-card" in js and "THE PLAN \\u00b7 " in js
    assert "Final & Approved deliverables" in js and "Most recent & for review" in js

    # 2. Tight spend pill (.spend-pill-main) + consolidated Next Step recommendation & clear-wait
    assert "spend-pill-main" in js and ".spend-pill-main" in css
    assert "Recommendation:" in js and 'post("/api/clear-wait"' in js
    assert "step-status-pill" in js and ".step-status-pill" in css

    # 3. Auto-registration of landed reading documents into DELIVERABLES.md in code_jobs.py
    assert "deliverables_register" in cj_py and "is_document(rel_p)" in cj_py

    # 4. POST /api/steward/clear-wait clears stale human_wait and roadmap waiting status
    proj = tmp_path / "ClearWaitProj"
    proj.mkdir()
    (proj / "strip.json").write_text(json.dumps({"human_wait": "Approve Wave 4"}), encoding="utf-8")
    (proj / "roadmap.json").write_text(json.dumps({
        "roadmap_projection": [{"id": "wave-4", "name": "Wave 4", "status": "waiting", "waiting_on": "John"}]
    }), encoding="utf-8")
    res, code = sr.handle_post(str(proj), "clear-wait", {})
    assert code == 200 and res.get("ok") is True
    assert json.loads((proj / "strip.json").read_text(encoding="utf-8")).get("human_wait") == ""
    assert json.loads((proj / "roadmap.json").read_text(encoding="utf-8"))["roadmap_projection"][0]["status"] == "active"

    # 5. Setup modal shows 3-Stage Onboarding rail + Companion Persona selector
    assert 'id="wave2-summary-strip"' in ps_html and 'id="wave2-persona-strip"' in ps_html
    assert ".provider-setup.is-embedded .cave-rail{display:none}" not in ps_css

    # 6. Parable of the Oranges accurately documented in Skill Foundry Anvil
    anvil_skill = Path(r"C:\dev\Skill Foundry\skills\anvil\SKILL.md").read_text(encoding="utf-8")
    assert "The Parable of the Oranges" in anvil_skill
    assert "boss's wife" in anvil_skill and "one trip" in anvil_skill


def test_per_cockpit_anvil_sessions_and_usage_allowance_monitor(tmp_path):
    import pytest
    from steward_cockpit import anvil_session as _as
    from steward_cockpit import steward_routes as sr
    import usage_allowance_monitor as uam

    # 1. v1.html & anvil.html hardening checks (B1, B2, H1, H2)
    v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
    anvil_html = (STATIC / "anvil.html").read_text(encoding="utf-8")
    assert "/steward-static/anvil.html" in v1
    assert 'src="/vendor/brand/anvil-option-2-sword-crystal-v1.jpg"' in anvil_html
    assert "⚒" not in anvil_html
    assert "[hidden] { display: none !important; }" in anvil_html
    assert "function sanitizeMathML(raw)" in anvil_html
    assert "if (dir) bodyObj.dir = dir;" in anvil_html

    # 2. MathML XSS & LaTeX command ordering checks (B1, M10)
    xss_mml = _as.latex_to_mathml("<math><mi>x</mi></math><img src=x onerror=alert(1)>")
    assert "<img" not in xss_mml and "onerror" not in xss_mml
    int_mml = _as.latex_to_mathml(r"\int_0^1 f(x) \leq \infty + \epsilon + \phi")
    assert "∫" in int_mml and "∞" in int_mml and "≤" in int_mml and "ϵ" in int_mml and "ϕ" in int_mml
    assert "fty" not in int_mml and "≤q" not in int_mml

    # 3. Path traversal, UNC, and SSRF hardening checks (H3, H4)
    proot = tmp_path / "ProjectRoot"
    proot.mkdir()
    cockpit = proot / "SampleCockpit"
    cockpit.mkdir()
    with pytest.raises(ValueError):
        _as._validate_and_resolve_local_path(cockpit, r"\\attacker\share\file.py")
    with pytest.raises(ValueError):
        _as._validate_and_resolve_local_path(cockpit, "../outside.py")
    with pytest.raises(ValueError):
        _as._validate_and_resolve_local_path(cockpit, ".claude/.credentials.json")
    with pytest.raises(ValueError):
        _as._validate_public_url("http://127.0.0.1:9222/json/list")
    with pytest.raises(ValueError):
        _as._validate_public_url("http://100.100.1.1/secret")

    # 4. Full api_get / api_post routing with sub-effort dir (B2)
    (cockpit / "ECGBERHT.md").write_text("# Sample Cockpit\n", encoding="utf-8")
    (cockpit / "solver.py").write_text(
        "def compute_energy(mass, velocity):\n"
        "    '''Compute kinetic energy E = 0.5 * m * v^2.'''\n"
        "    return 0.5 * mass * (velocity ** 2)\n\n"
        "def format_report(val):\n"
        "    return f'Energy: {val:.2f}'\n",
        encoding="utf-8",
    )
    (cockpit / "paper.md").write_text(
        "# Kinetic Energy Paper\n\n"
        "## Core Equation\n"
        "$$E = \\frac{1}{2} m v^2$$\n"
        "- Compute energy from mass and velocity.\n",
        encoding="utf-8",
    )

    st0, code0 = sr.api_get(str(proot), "anvil", {"dir": "SampleCockpit"})
    assert code0 == 200
    assert st0["ok"] is True and st0["active"] is False and st0["session"] is None
    assert any(c["path"] == "solver.py" for c in st0["candidates"]["software"])
    assert any(c["path"] == "paper.md" for c in st0["candidates"]["papers"])

    # 5. Launching via api_post populates the sub-effort's .anvil/session.json, ANVIL-REPORT.md, and DELIVERABLES.md
    st1, code1 = sr.api_post(str(proot), "anvil", {
        "dir": "SampleCockpit",
        "action": "start_paper",
        "software_target": ".",
        "paper_target": "paper.md",
    })
    assert code1 == 200 and st1["ok"] is True and st1["active"] is True
    assert (cockpit / ".anvil" / "session.json").is_file()
    assert (cockpit / "ANVIL-REPORT.md").is_file()
    assert (cockpit / "DELIVERABLES.md").is_file()
    assert "ANVIL-REPORT.md" in (cockpit / "DELIVERABLES.md").read_text(encoding="utf-8")
    sess = st1["session"]
    assert sess["paper_map"]["claims_mapped"] >= 1
    assert "<math" in sess["paper_map"]["alignments"][0]["mathml"]
    # Before empirical block probe, matched claims are honestly labeled HEURISTIC_MATCH (H5)
    matched_al = next(a for a in sess["paper_map"]["alignments"] if a["mapped_function"] == "compute_energy")
    assert matched_al["empirical_status"] == "HEURISTIC_MATCH"

    # 6. Probing the block upgrades the block to validated=True and upgrades the paper alignment to VERIFIED
    bid = sess["code_map"]["conceptual_buckets"][0]["id"]
    st2, code2 = sr.api_post(str(proot), "anvil", {
        "dir": "SampleCockpit",
        "action": "probe_block",
        "block_id": bid,
        "lock_description": "",
    })
    assert code2 == 200 and st2["ok"] is True
    assert st2["block"]["validated"] is True
    matched_al_after = next(a for a in st2["session"]["paper_map"]["alignments"] if a["mapped_function"] == "compute_energy")
    assert matched_al_after["empirical_status"] == "VERIFIED"

    st3, code3 = sr.api_post(str(proot), "anvil", {
        "dir": "SampleCockpit",
        "action": "chat",
        "question": "How does compute_energy align with the paper?",
        "mode": "paper",
        "target": matched_al_after["claim_id"],
    })
    assert code3 == 200 and st3["ok"] is True
    assert "compute_energy" in st3["reply"]

    # 7. Resetting returns the cockpit's Anvil session to empty state
    st4, code4 = sr.api_post(str(proot), "anvil", {"dir": "SampleCockpit", "action": "reset"})
    assert code4 == 200 and st4["active"] is False

    # 8. Usage Allowance Monitor reports all 4 providers (Claude, Gemini, Grok, ChatGPT)
    snap = uam.compute_allowance_monitor()
    assert set(snap["families"].keys()) == {"claude", "gemini", "grok", "chatgpt"}
    for p in ("claude", "gemini", "grok", "chatgpt"):
        pct = snap["families"][p]["remaining_percent"]
        if pct is not None:
            assert 0 <= pct <= 100


def test_verified_cli_frontier_models_and_organized_deliverables_and_plan():
    import usage_allowance_monitor as uam

    uam_src = (ROOT / "usage_allowance_monitor.py").read_text(encoding="utf-8")
    ps_js = (ROOT / "static" / "provider-setup.js").read_text(encoding="utf-8")
    pc_js = (ROOT / "static" / "provider-controls.js").read_text(encoding="utf-8")
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")

    # 1. Verified CLI frontier models everywhere — zero guessed stale model names
    for m in ("claude-fable-5-1", "gpt-6.1-sol", "gemini-4-argon", "grok-4.7"):
        assert m in uam_src
        assert m in ps_js
        assert m in js
    for stale in ("Claude Opus 4.7", "Claude Sonnet 4.6", "GPT-5.4", "Gemini 3.1 Pro"):
        assert stale not in uam_src
        assert stale not in ps_js
        assert stale not in js

    snap = uam.compute_allowance_monitor()
    assert snap["families"]["claude"]["frontier_model"] == "claude-fable-5-1 · max"
    assert snap["families"]["chatgpt"]["frontier_model"] == "gpt-6.1-sol · ultra"
    assert snap["families"]["gemini"]["frontier_model"] == "gemini-4-argon · high"
    assert snap["families"]["grok"]["frontier_model"] == "grok-4.7 · xhigh"

    # 2. Compact Cave of Wonders left rail cards with frontier model + reset dates
    assert "cave-account-summary" in pc_js and "ec-frontier" in pc_js
    assert "Subscriptions &amp; Frontier" in pc_js and "reset_7d_text" in pc_js

    # 3. 3-Tier Deliverables organization & 2-line readable cards with format badges
    assert "1. Current & Ready for Review (" in js
    assert "2. Final & Approved deliverables (" in js
    assert "3. Earlier & Supporting Deliverables by Section (" in js
    assert "file-fmt-badge" in js and "file-row-sub" in js
    assert ".file-fmt-badge" in css and ".app3 .pdeliv .file-row-sub" in css

    # 4. Left-rail Plan collapsible section groups & step-specific subtitles
    assert "Focus & Needs Your Input" in js
    assert "Active & In Open Review" in js
    assert "Next Up in Plan" in js
    assert "Later & Parked Steps" in js
    assert ".app3 .steps .plan-sec-group" in css


def test_nightly_allowance_scheduler_plan_modes_deliverables_count_tiles_and_anvil_empty_chat(tmp_path):
    from steward_cockpit import steward_routes as sr
    from steward_cockpit import foundry_tools as ft
    import usage_allowance_monitor as uam

    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    anvil_html = (STATIC / "anvil.html").read_text(encoding="utf-8")
    ag_py = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")

    # 1. Nightly & automatic subscription allowance refresh scheduler
    snap = uam.run_nightly_allowance_refresh(force=False)
    assert snap.get("auto_refresh", {}).get("enabled") is True
    assert "02:00" in snap["auto_refresh"]["schedule"]
    assert "ensure_nightly_allowance_scheduler()" in ag_py

    # 2. Deliverables tab: open "ready now" + closed-by-default click-to-open count tiles for Finalized & Earlier
    assert "ready now" in js
    assert "finalized \\u00b7 click to open" in js
    assert "sections \\u00b7 click to open" in js
    assert "more items in open review (click to open)" in js
    assert ".deliv-tile-pill" in css and ".deliv-more-fold" in css

    # 3. Left-rail THE PLAN: Waves vs Hierarchy mode toggle + human-readable wrapping step cards
    assert "function getPlanViewMode()" in js and 'navChoice("plan:view_mode"' in js
    assert "function classifyStepHierarchyBlock(entry, map)" in js
    assert "\\ud83c\\udf0a Waves" in js and "\\ud83d\\uddc2 Hierarchy" in js
    assert ".plan-mode-bar" in css and ".plan-mode-btn" in css
    assert "step-meta-row" in js and ".app3 .steps li.step-card .step-meta-row" in css

    # 4. Anvil Empty / Setup screen: persistent Steward & Anvil Dialogue Dock + natural-language setup from chat
    assert 'id="anvilDialogueDock"' in anvil_html
    assert "Steward &amp; Anvil Dialogue" in anvil_html
    assert "data-quick-setup-prompt" in anvil_html and "renderAgentDock(null, cands, cname);" in anvil_html
    proot = tmp_path / "AnvilChatSetupRoot"
    proot.mkdir()
    sub = proot / "SubProject"
    sub.mkdir()
    (sub / "ECGBERHT.md").write_text("# SubProject\n", encoding="utf-8")
    (sub / "attention_paper.md").write_text(
        "# Attention Paper\n\n$$A(Q,K,V) = \\frac{QK^T}{\\sqrt{d_k}} V$$\n- Compute scaled dot-product attention.\n",
        encoding="utf-8",
    )
    (sub / "attention_net.py").write_text(
        "def compute_attention(q, k, v):\n"
        "    '''Compute scaled dot-product attention from q, k, v.'''\n"
        "    return (q @ k.T) @ v\n",
        encoding="utf-8",
    )
    # Chatting before any session is initialized locates the local paper + code and starts the session
    res_chat, code_chat = sr.api_post(str(proot), "anvil", {
        "dir": "SubProject",
        "action": "chat",
        "question": "Please look for attention_paper.md loaded locally and map it to attention_net.py",
        "mode": "setup",
        "target": "global",
    })
    assert code_chat == 200 and res_chat["ok"] is True
    assert res_chat["active"] is True and res_chat["session"] is not None
    assert "attention_paper.md" in res_chat["reply"]
    assert (sub / ".anvil" / "session.json").is_file()

    # 5. Steward Task Challenge Triage & Context Sizing
    assert "SMALL BOUNDED JOB (`--size small`)" in ft.FOUNDRY_SKILLS_SUMMARY
    assert "HARD / ARCHITECTURAL / DOMAIN-SKILL WORK (`--size standard` at Frontier Max/Ultra/XHigh)" in ft.FOUNDRY_SKILLS_SUMMARY
    assert "never dump raw conversation transcripts" in ft.FOUNDRY_SKILLS_SUMMARY
    assert "<=8,000 chars" in ft.FOUNDRY_SKILLS_SUMMARY


def test_steward_manages_current_summary_review_banners_and_doctor_gemini_non_plan_fix(tmp_path):
    from steward_cockpit import steward_campaign as sc
    from steward_cockpit import steward_engine as se
    import deliverables_register as dreg
    import doctor_plain as dp

    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    ag_py = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    ts_py = (ROOT / "terminal_session.py").read_text(encoding="utf-8")
    rd_mjs = (ROOT / "tools" / "review_diff.mjs").read_text(encoding="utf-8")
    sr_mjs = (ROOT / "tools" / "steward_review.mjs").read_text(encoding="utf-8")

    # 1. Steward current & needs-review banners across Deliverables, Top Dialogue, and Left Plan Rail
    assert "steward-current-banner" in js and ".steward-current-banner" in css
    assert "Needs Review: " in js
    assert "Work Ready for Review: " in js
    assert "STEWARD CURRENT FOCUS" in js and "plan-current-card" in js

    # 2. Steward immediate responsiveness: 6s fast receipt & preserves opening sentence across tool calls
    assert se.FAST_RECEIPT_AFTER_S == 6.0
    assert "IMMEDIATE RESPONSIVENESS & COCKPIT SYNC" in se.CONTRACT

    # 3. deliverables_register inserts new items at top and reads strip.current_step_id first
    camp = tmp_path / "CampSync"
    camp.mkdir()
    (camp / "ECGBERHT.md").write_text("# CampSync\n", encoding="utf-8")
    (camp / "strip.json").write_text(
        '{"current_step_id": "s2", "active_effort": "Step 2 v2 ready for review", '
        '"human_wait": "John\'s review of Draft v2", "next_recommended": "Read Draft v2"}',
        encoding="utf-8",
    )
    (camp / "roadmap.json").write_text(
        '{"roadmap_projection": ['
        '{"id": "s1", "name": "Step 1", "status": "active"}, '
        '{"id": "s2", "name": "Step 2 v1", "status": "active", "waiting_on": "", '
        '"navigation": {"path": ["g1"], "label": "Step 2 v1", "current": true, "pin": false, "featured_paths": ["old-v1.pdf"]}}'
        ']}',
        encoding="utf-8",
    )
    assert dreg.active_step(camp) == "2"
    (camp / "old-v1.pdf").write_text("v1", encoding="utf-8")
    (camp / "new-v2.pdf").write_text("v2", encoding="utf-8")
    dreg.register(camp, "Supporting — Old v1 (PDF)", "`old-v1.pdf`", date="2026-10-14", step="s2", notify=False)
    dreg.register(camp, "START HERE — New v2 (PDF)", "`new-v2.pdf`", date="2026-10-15", step="s2", notify=False)
    sync_res = sc.sync_steward_projections(str(camp))
    assert sync_res["ok"] is True and sync_res["changed"] is True
    deliv = sc.read_deliverables(str(camp))
    assert deliv["current_summary"]["active_effort"] == "Step 2 v2 ready for review"
    assert deliv["current_summary"]["review_count"] == 1
    current_paths = [it["path"] for it in deliv["items"] if it.get("is_current")]
    assert "new-v2.pdf" in current_paths and "old-v1.pdf" not in current_paths

    # 4. Doctor classifies [GET /api/rnd/projects_html] unreachable as KIND_SELF_TEST_UNREACHABLE and reruns when green
    issue = {
        "component": "[GET /api/rnd/projects_html] unreachable (<urlopen error timed out>)",
        "detail": "[GET /api/rnd/projects_html] unreachable (<urlopen error timed out>)",
    }
    ex = dp.explain(issue)
    assert ex["kind"] == dp.KIND_SELF_TEST_UNREACHABLE
    assert "/api/rnd/projects_html" in ex["paths"]
    assert dp.decide([ex], [{"path": "/api/rnd/projects_html", "ok": True}]) == "rerun"

    # 5. Doctor defaults to Gemini (not in plan mode) and provides tools/doctor_fix.py
    assert 'if backend == _reg.BACKEND_GEMINI and os.environ.get("ANCHOR_PTY_BACKEND") != "stub":' in ts_py
    assert 'value="gemini" selected>Gemini (AGY CLI)</option>' in ag_py
    assert "tools/doctor_fix.py --auto" in ag_py
    assert (ROOT / "tools" / "doctor_fix.py").is_file()

    # 6. Post-integration delta review filters to candidate files only
    assert "deltaBase: deltaFrom ? base : ''" in sr_mjs
    assert "delta-noop" in sr_mjs
    assert "if (options.deltaBase && options.deltaBase !== from)" in rd_mjs


def test_workday_15m_allowance_horizontal_hierarchy_default_closed_groups_and_clean_cave_rail():
    import usage_allowance_monitor as uam

    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    ps_css = (ROOT / "static" / "provider-setup.css").read_text(encoding="utf-8")
    pc_js = (ROOT / "static" / "provider-controls.js").read_text(encoding="utf-8")

    # 1. Workday 15m allowance refresh separated from Nightly 02:00 model frontier check
    meta = uam._read_auto_refresh_meta()
    assert meta["enabled"] is True
    assert meta["allowance_interval_minutes"] == 15
    assert "15m" in meta["schedule"] and "02:00" in meta["schedule"]
    assert "15m / Nightly" in pc_js

    # 2. Horizontal Hierarchy mode layout (1 full horizontal line per item name, details below) & single-current-group-open
    assert "hier-group" in js and "hier-list" in js
    assert ".app3 .steps .plan-sec-list.hier-list" in css
    assert "flex-direction: column;" in css and "flex: 1 1 100%;" in css
    assert 'openWaveKey === "focus"' in js and 'openWaveKey === "active"' in js and 'openWaveKey === "next"' in js
    assert "const isCurrentBlock = bIdx === currentBlockIdx;" in js

    # 3. Deliverables groupings closed by default except current wave/review group
    assert 'navChoice("deliv:v2:tier:review", reviewNow.length > 0)' in js
    assert 'navChoice("deliv:v2:tier:final", false)' in js
    assert 'navChoice("deliv:v2:tier:other", false)' in js
    assert 'navChoice(secKey, false)' in js
    assert 'navChoice("deliv:v2:tier:receipts", false)' in js

    # 4. Cave of Wonders left rail keeps #cave-account-summaries snug under Destinations (margin-top:6px)
    assert "#cave-account-summaries" in ps_css and "margin-top:6px" in ps_css


def test_compact_deliverable_tiles_and_steward_performance_engine_upgrades(tmp_path, monkeypatch):
    import json, sys, time
    from steward_cockpit import code_jobs as cj, code_job_handoff as ch, steward_campaign as sc
    from tools import reading_copy as rc, steward_code_job as cli

    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")

    # 1. Compact 1-2 line deliverable tiles with inline Open/Download & click-to-expand
    assert "compact-tile" in js and ".file-row-more" in css
    assert "file-open-btn" in js and "file-dl" in js and "file-exp-btn" in js
    assert "snt-review-strip" in js and "snt-rev-chip" in js and "snt-rev-openbtn" in js

    # 2. reading_copy.py --no-pdf --docx converts Markdown to .docx in <1s
    md_file = tmp_path / "chapter_01.md"
    docx_file = tmp_path / "chapter_01.docx"
    md_file.write_text("# Chapter 1: The Awakening\n\nA **bold** opening paragraph.\n\n- First item\n- Second item\n", encoding="utf-8")
    assert rc.main([str(md_file), "--no-pdf", "--docx", str(docx_file)]) == 0
    assert docx_file.is_file() and docx_file.stat().st_size > 1000

    # 3. _companion_outputs admits new same-directory, same-stem document companions and rejects existing tracked files or unrelated files
    wt = tmp_path / "wt"
    wt.mkdir()
    job = {"work_dir": "", "outputs": ["chapters/ch01.docx"]}
    allowed = {"chapters/ch01.docx"}
    candidates = ["chapters/ch01_source.md", "chapters/ch01.md", "chapters/ch01_redline.docx", "chapters/other.docx"]
    admitted = cj._companion_outputs(job, wt, allowed, candidates)
    assert sorted(admitted) == ["chapters/ch01.md", "chapters/ch01_redline.docx", "chapters/ch01_source.md"]
    assert "chapters/other.docx" not in admitted
    assert job["admitted_companions"] == ["chapters/ch01.md", "chapters/ch01_redline.docx", "chapters/ch01_source.md"]
    # When a candidate already existed at base (tracked file), _companion_outputs refuses undeclared edits to it
    monkeypatch.setattr(cj, "_blob", lambda tree, rev, rel: "deadbeef" if rel == "chapters/ch01.md" else None)
    admitted_with_base = cj._companion_outputs(job, wt, allowed, candidates, base="HEAD")
    assert "chapters/ch01.md" not in admitted_with_base
    assert sorted(admitted_with_base) == ["chapters/ch01_redline.docx", "chapters/ch01_source.md"]

    # 4. worktree_activity surfaces live file counts and latest file sizes in observe() and who_is_working()
    now = time.time()
    (wt / "chapters").mkdir()
    ch_path = wt / "chapters" / "ch01_v5.md"
    ch_path.write_text("# Draft\n" + ("word " * 400), encoding="utf-8")
    job_live = {
        "id": "job123",
        "status": "running",
        "phase": "producing",
        "phase_at": now - 60,
        "worker_birth": now - 60,
        "worktree": str(wt),
        "steward_dir": str(tmp_path),
        "title": "Draft Chapter 1",
        "coder_family": "claude",
    }
    ch._WT_ACTIVITY_CACHE.clear()
    act = ch.worktree_activity(job_live)
    assert act is not None and act["modified_count"] == 1
    assert "chapters/ch01_v5.md" in act["worktree_summary"]
    job_live["native"] = {"phase": "producing", "phase_at": now - 60, "estimates": [], "stopped": False}
    job_live["supervision"] = ch.supervise(job_live, native=job_live["native"], now=now)
    who, phase, _, _, _ = sc.who_is_working(tmp_path, {}, [job_live], None, now=now)
    assert "chapters/ch01_v5.md" in who and "modified in worktree" in who

    # 5. steward_code_job.py auto-compacts oversize --brief-file (>7800 chars) and enforces the 3-stem cap
    big_brief = tmp_path / "big_brief.md"
    big_brief.write_text("HEADER_CONTEXT\n" + ("x" * 9500) + "\nFINAL_ACCEPTANCE_CRITERIA", encoding="utf-8")
    sent = []
    monkeypatch.setattr(cli, "project_for", lambda cwd: ("fixture", "A"))
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok":true}'
    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda req, **kw: sent.append(json.loads(req.data)) or _Resp())
    monkeypatch.setattr(sys, "argv", ["steward_code_job.py", "start", "--repo", str(tmp_path),
                                      "--brief-file", str(big_brief), "--check", "pytest -q",
                                      "--output", "ch01.docx", "--output", "ch01_redline.docx"])
    cli.main()
    assert len(sent[-1]["brief"]) <= cj.BRIEF_MAX
    assert sent[-1]["brief"].startswith("FULL BRIEF FILE")
    assert "HEADER_CONTEXT" in sent[-1]["brief"] and "FINAL_ACCEPTANCE_CRITERIA" in sent[-1]["brief"]
    # Declaring >3 distinct document stems raises SystemExit at start
    import pytest
    monkeypatch.setattr(sys, "argv", ["steward_code_job.py", "start", "--repo", str(tmp_path),
                                      "--brief-file", str(big_brief), "--check", "pytest -q",
                                      "--output", "ch01.docx", "--output", "ch02.docx",
                                      "--output", "ch03.docx", "--output", "ch04.docx"])
    with pytest.raises(SystemExit, match="distinct document stems"):
        cli.main()

