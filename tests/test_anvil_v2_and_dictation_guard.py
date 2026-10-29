from __future__ import annotations

import json
from pathlib import Path

from steward_cockpit import anvil_session, campaign_say, steward_routes


_WS_ROOT = Path(__file__).resolve().parent.parent.parent
_ANCHOR_ROOT = Path(__file__).resolve().parent.parent


def test_campaign_dictation_scope_guard_prevents_book1_hijack():
    cdir = _WS_ROOT / "Campaign"
    prompt = (
        "Let us prepare Round 2 of U-OSTS and GWL-Free token compression and context compression "
        "with LLMLingua-2, KVzip, and HeadKV."
    )
    block = campaign_say._campaign_scope_prompt_block(cdir, prompt)
    assert "CAMPAIGN / EFFORT SCOPE GUARD" in block
    assert "NEVER hijack" in block
    assert not campaign_say._ANVIL_REPORT_RE.search(prompt)


def test_named_cockpit_resolution_book1_and_paper1():
    book1 = steward_routes._resolve_named_cockpit_dir("Book 1")
    paper1 = steward_routes._resolve_named_cockpit_dir("Paper 1")
    assert book1 is not None and Path(book1).name == "Book 1"
    assert paper1 is not None and Path(paper1).name == "Paper 1"


def test_anvil_walkthrough_endpoint_and_non_destructive_report():
    paper1 = _WS_ROOT / "Hierarchical Normalizing Flows" / "Paper 1"
    payload, status = steward_routes.handle_get(str(paper1), "anvil/walkthrough", {})
    assert status == 200
    assert payload.get("ok") is True
    wt = payload.get("walkthrough") or {}
    assert wt.get("schema") == "anvil-walkthrough/v2"
    assert len(wt.get("steps") or []) >= 1

    report_text = (paper1 / "ANVIL-REPORT.md").read_text(encoding="utf-8")
    assert report_text.lstrip().startswith("# Illustrated Anvil Architecture")
    assert "## 7. Anvil v2 — 3-Level Progressive Abstraction" in report_text
    assert (paper1 / ".anvil" / "manifest.json").is_file()


def test_anvil_v2_walkthrough_inside_anvil_and_mothership_file_browser():
    anvil_html = (_ANCHOR_ROOT / "steward_cockpit" / "static" / "anvil.html").read_text(encoding="utf-8")
    v1_html = (_ANCHOR_ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    shared_js = (_ANCHOR_ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")

    # Walkthrough Code is an option INSIDE Anvil (Launcher Card 3 + Workbench Mode Tab 2 + Quick Bar + Header)
    assert 'data-launch-card="walkthrough"' in anvil_html
    assert 'id="btnStartWalkthrough"' in anvil_html
    assert 'data-tab="walkthrough"' in anvil_html
    assert 'data-tab-panel="walkthrough"' in anvil_html
    assert "btnWalkthroughCode" in anvil_html
    assert "btnMapWalkthroughCode" in anvil_html
    assert "btnQuickWalkthrough" in anvil_html
    assert "walkthroughPanel" in anvil_html
    assert "betaReaderPanelStrip" in anvil_html
    assert 'data-prog-level="1"' in anvil_html
    assert 'data-prog-level="2"' in anvil_html
    assert 'data-prog-level="3"' in anvil_html
    assert '<button type="button" class="anvil-tile-btn" data-anvil-walkthrough-toggle' not in v1_html

    # Mothership File Browser on the Drop File tab (both v1.html and cockpit.html)
    cockpit_html = (_ANCHOR_ROOT / "steward_cockpit" / "static" / "cockpit.html").read_text(encoding="utf-8")
    assert "data-mothership-browse-btn" in v1_html
    assert "data-mothership-browser" in v1_html
    assert "data-mothership-browse-btn" in cockpit_html
    assert "data-mothership-browser" in cockpit_html
    assert "loadMothershipDir" in shared_js
    assert "/api/mothership-files" in shared_js

    paper1 = _WS_ROOT / "Hierarchical Normalizing Flows" / "Paper 1"
    mb_res, mb_status = steward_routes.handle_get(str(paper1), "mothership-files", {})
    assert mb_status == 200
    assert mb_res.get("ok") is True
    assert mb_res.get("cockpit_dir") == str(paper1.resolve())
    assert len(mb_res.get("roots") or []) >= 2
    assert any(e.get("name") == "ANVIL-REPORT.md" for e in (mb_res.get("entries") or []))
