"""Isolated browser proof through Anchor's real routes and Ecgberht CLI.

These tests run a disposable local server and campaign.  They do not establish
deployment to a user's running app, or acceptance of a deliverable by a user.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from steward_cockpit import refinement_client


@dataclass
class CampaignServer:
    origin: str
    campaign: Path
    project_id: str
    token: str

    @property
    def cockpit_url(self):
        return f"{self.origin}/project/{quote(self.project_id, safe='')}?dir="


@pytest.fixture
def campaign_server(tmp_path, monkeypatch):
    """Start the application's actual HTTP handler, with no production seats."""
    anchor_root = Path(__file__).resolve().parents[1]
    ecgberht_root = anchor_root.parent / "ecgberht"
    cli = ecgberht_root / "bin" / "ecgberht.mjs"
    demo = ecgberht_root / "test" / "refinement-demo.mjs"
    assert cli.is_file(), f"Missing paired Ecgberht checkout: {cli}"
    assert demo.is_file(), f"Missing lifecycle fixture generator: {demo}"
    node = shutil.which("node")
    assert node, "The real CLI integration requires Node on PATH"

    campaign = tmp_path / "foundation campaign"
    campaign.mkdir()
    data_dir = tmp_path / "anchor-data"
    data_dir.mkdir()
    test_token = "refinement-browser-disposable-token"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_TOKEN", test_token)
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ECGBERHT_REFINEMENT_CLI", str(cli))
    subprocess.run(
        [node, str(demo), str(campaign)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        timeout=30,
    )

    # Imports happen after isolated paths/auth/backend are selected.
    import anchor_gui
    from steward_cockpit import steward_routes

    monkeypatch.setitem(steward_routes.CONFIG, "fake", True)
    registration = anchor_gui.select_existing_project("Refinement browser foundation", str(tmp_path))
    project_id = registration["entry"]["id"]
    server = anchor_gui.make_server("127.0.0.1", 0)
    worker = threading.Thread(target=server.serve_forever, name="refinement-browser-http", daemon=True)
    worker.start()
    try:
        yield CampaignServer(f"http://127.0.0.1:{server.server_address[1]}", campaign, project_id, test_token)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive(), "Disposable Anchor server did not stop"


@pytest.fixture
def cockpit(campaign_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1365, "height": 1050})
        page = context.new_page()
        try:
            # Use the normal launcher flow: dashboard JS exchanges the token
            # for an HttpOnly cookie.  Subsequent requests receive no injected
            # auth headers and the URL no longer contains the test token.
            with page.expect_response(
                lambda response: response.url == f"{campaign_server.origin}/api/auth/login"
                and response.request.method == "POST"
            ) as login:
                # `/` serves the High Seat now; the classic dashboard still carries the launcher token hand-off
                page.goto(f"{campaign_server.origin}/?classic=1&token={quote(campaign_server.token, safe='')}")
            assert login.value.ok, "Normal launcher login failed"
            page.wait_for_function("!new URL(location.href).searchParams.has('token')")
            cookies = context.cookies(campaign_server.origin)
            assert any(cookie.get("httpOnly") for cookie in cookies), "Normal login did not mint its HttpOnly cookie"
            page.goto(campaign_server.cockpit_url)
            yield page, campaign_server
        finally:
            context.close()
            browser.close()


def _state(server):
    result = refinement_client.read_state(server.campaign)
    assert result["ok"] is True, result
    assert result["projection_status"]["consistent"] is True, result
    return result["state"]


def _foundation(state):
    return state["slices"]["foundation"]


def _view_count(server):
    return len(_foundation(_state(server)).get("views", []))


def _expand_foundation(page):
    page.locator('[data-efforts] .efrow').filter(has_text='foundation campaign').first.click()
    surface = page.frame_locator('[data-fsframe]')
    title = surface.locator("[data-steps] li .stitle").filter(has_text=re.compile("foundation", re.I)).first
    expect(title).to_be_visible()
    title.click()
    step = surface.locator("[data-steps] li").filter(has=surface.locator(".stitle").filter(has_text=re.compile("foundation", re.I))).first
    product = step.locator(".sdone").filter(has_text="guide").first
    expect(product).to_be_visible()
    product.click()
    return step


def _open_history(step):
    history = step.locator("summary").filter(has_text=re.compile("Earlier versions", re.I)).first
    expect(history).to_be_visible()
    history.click()
    initial = step.get_by_role("link", name="Initial draft", exact=False).first
    expect(initial).to_be_visible()
    return initial


def _click_version(page, link, heading):
    with page.expect_popup() as opened:
        link.click()
    popup = opened.value
    try:
        expect(popup.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        assert popup.url.startswith(urlsplit(page.url).scheme + "://" + urlsplit(page.url).netloc)
    finally:
        popup.close()


def test_real_cockpit_keeps_current_and_collapsed_old_versions_with_click_receipts(cockpit):
    page, server = cockpit
    assert _view_count(server) == 0
    step = _expand_foundation(page)
    expect(step).to_contain_text(re.compile(r"Refinement\s*1", re.I))
    expect(step).to_contain_text(re.compile(r"1\s+refinements?", re.I))
    current = step.get_by_role("link", name=re.compile(r"^Open")).first
    expect(current).to_be_visible()
    current_url = urljoin(server.origin, current.get_attribute("href"))

    # Fetch and prefetch can serve bytes, but cannot impersonate an intentional
    # cockpit click.  Real auth cookies are shared by Playwright's request API.
    raw = page.request.get(current_url)
    assert raw.status == 200
    assert "Model foundations refined" in raw.text()
    prefetch = page.request.get(current_url, headers={"Purpose": "prefetch", "Sec-Purpose": "prefetch"})
    assert prefetch.status == 200
    assert _view_count(server) == 0

    initial = _open_history(step)
    initial_url = urljoin(server.origin, initial.get_attribute("href"))
    assert initial_url != current_url
    _click_version(page, initial, "Model foundations initial")
    _click_version(page, current, "Model foundations refined")
    assert _view_count(server) == 2
    # Exercise the application's existing deliverable-refresh notification;
    # repaint must preserve history while the user compares versions.
    step.locator('details').first.evaluate("node => node.dataset.beforeRefresh = '1'")
    with page.expect_response(lambda r: "/deliverables?" in r.url and r.request.method == "GET"):
        page.frame_locator('[data-fsframe]').locator('body').evaluate(
            "() => window.dispatchEvent(new Event('anchor-notebooks-changed'))"
        )
    expect(step.locator('[data-before-refresh]')).to_have_count(0)
    expect(initial).to_be_visible()
    page.screenshot(path=str(server.campaign.parent / "refinement-cockpit.png"), full_page=True)

    # A full repaint must retain both version links and the user's open review.
    page.reload()
    step = _expand_foundation(page)
    current_again = step.get_by_role("link", name=re.compile(r"^Open")).first
    initial_again = _open_history(step)
    assert urljoin(server.origin, current_again.get_attribute("href")) == current_url
    assert urljoin(server.origin, initial_again.get_attribute("href")) == initial_url
    assert _view_count(server) == 2
    _click_version(page, initial_again, "Model foundations initial")
    foundation = _foundation(_state(server))
    assert foundation["phase"] == "awaiting_review"
    assert foundation["round"] == 1
    assert foundation["accepted_presentation"] is None
    assert foundation["closed_presentation"] is None


def _replace_query(url, **values):
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    for key, value in values.items():
        query[key] = [value]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def test_real_close_then_refine_reopens_same_slice_and_preserves_requirements(cockpit, monkeypatch):
    page, server = cockpit
    from steward_cockpit import steward_engine

    delivered = []
    # Only the production model seat is replaced. Browser, authentication,
    # POST routing, lifecycle CLI and persistent campaign remain real.
    def capture_say(self, text, human=True):
        delivered.append(text)
        return {"ok": True, "queued": False}

    monkeypatch.setattr(steward_engine.Engine, "say", capture_say)
    step = _expand_foundation(page)
    before = _foundation(_state(server))
    with page.expect_response(lambda r: "/refinement-close" in r.url and r.request.method == "POST") as response:
        step.get_by_role("button", name="Done with this slice", exact=True).click()
    assert response.value.ok
    closed = _foundation(_state(server))
    assert closed["phase"] == "done"
    assert closed["closed_presentation"] == "p1"

    page.reload()
    step = _expand_foundation(page)
    step.get_by_role("button", name="Refine this slice", exact=True).click()
    surface = page.frame_locator('[data-fsframe]')
    feedback = "Keep the refined explanation and add one concrete example."
    surface.locator('[data-say]').fill(feedback)
    with page.expect_response(lambda r: "/say" in r.url and r.request.method == "POST") as response:
        surface.locator('[data-send]').click()
    assert response.value.ok
    assert delivered == [feedback]
    reopened = _foundation(_state(server))
    assert reopened["round"] == 2
    assert reopened["phase"] != "done"
    assert reopened["closed_presentation"] is None
    assert reopened["candidate"] == before["candidate"]
    for key, requirement in before["requirements"].items():
        assert reopened["requirements"][key] == requirement
    assert reopened["feedback"][-1]["source_message"] == feedback


def test_real_deliverable_route_rejects_hash_tampering_and_parent_escape(cockpit):
    page, server = cockpit
    step = _expand_foundation(page)
    current = step.get_by_role("link", name=re.compile(r"^Open")).first
    valid_url = urljoin(server.origin, current.get_attribute("href"))
    query = parse_qs(urlsplit(valid_url).query)
    assert query.get("hash"), "Presented version links must bind the expected file hash"
    before = _view_count(server)
    tampered = page.request.get(_replace_query(valid_url, hash="0" * 64))
    assert tampered.status in (400, 403, 409, 412)
    assert "Model foundations refined" not in tampered.text()

    outside = server.campaign.parent / "private-outside.html"
    outside.write_text("<h1>outside campaign sentinel</h1>", encoding="utf-8")
    escaped = page.request.get(_replace_query(valid_url, path="../private-outside.html"))
    assert escaped.status in (400, 403, 404)
    assert "outside campaign sentinel" not in escaped.text()
    assert _view_count(server) == before


def test_managed_wait_is_shared_by_status_header_and_drive(campaign_server, monkeypatch):
    from steward_cockpit import steward_engine, steward_campaign

    server = campaign_server
    engine = steward_engine.Engine(str(server.campaign), fake=True)
    class IdleProc:
        def poll(self):
            return None
    engine.proc = IdleProc()
    sent = []
    monkeypatch.setattr(engine, '_send_locked', lambda text: (sent.append(text), True)[1])
    monkeypatch.setattr(engine, '_status_update', lambda **kwargs: None)
    engine.open_question = 'A rhetorical question?'
    engine.drive = True
    purpose = _state(server)['pending_request']['purpose']
    state = engine.state()
    assert state['open_question'] == purpose
    assert state['light'] == 'orange'
    assert steward_campaign.compose_status(str(server.campaign), state)['plan']['waiting_on_you'] == purpose

    assert engine.say('An unrelated observation about tomorrow.')['ok']
    assert _state(server)['pending_request']['purpose'] == purpose
    sent.clear()
    engine._maybe_drive_locked(completed_text='A rhetorical question?')
    assert sent == [], 'Unanswered review must still block drive'

    current = refinement_client.read_state(server.campaign)
    result = refinement_client.update(server.campaign, {
        'action': 'close', 'operation_id': 'wait-test-close', 'expected_seq': current['sequence'],
        'step_id': 'foundation', 'presentation_id': 'p1',
        'human': {'explicit': True, 'source_message': 'Done with the current foundation presentation.'}})
    assert result['ok'], result
    # Stale authored stamps cannot restore a human wait after explicit close.
    (server.campaign / '.ecgberht').mkdir(exist_ok=True)
    (server.campaign / '.ecgberht' / 'attention.json').write_text(
        json.dumps({'state': 'needs_you', 'reason': 'obsolete stamp', 'at': '2099-01-01'}), encoding='utf-8')
    engine.open_question = 'Old restored question?'
    state = engine.state()
    assert state['open_question'] == ''
    assert state['light'] == 'quiet'
    assert state['attention_state'] != 'needs_you'
    assert steward_campaign.compose_status(str(server.campaign), state)['plan']['waiting_on_you'] == ''
    engine.turn_text = 'This is a rhetorical question?'
    engine._handle({'type': 'result', 'total_cost_usd': 0.0, 'duration_ms': 1, 'usage': {}}, engine.proc)
    assert engine.open_question == ''
    assert len(sent) == 1 and '(drive - not John)' in sent[0]


def test_cockpit_done_repairs_prior_committed_projection_lag_once(cockpit):
    page, server = cockpit
    step = _expand_foundation(page)
    before = refinement_client.read_state(server.campaign)
    ecg = Path(__file__).resolve().parents[2] / 'ecgberht'
    # Restore an authentic earlier projection, as left by an interrupted
    # publisher. Do not delete markers or erase externally authored content.
    source = (
        "import fs from 'node:fs'; import path from 'node:path';"
        f"import {{foldRefinements}} from {json.dumps((ecg/'engine/refinement-state.mjs').as_uri())};"
        f"import {{renderRefinementDocument}} from {json.dumps((ecg/'engine/refinement.mjs').as_uri())};"
        "const root=JSON.parse(fs.readFileSync(0,'utf8'));"
        "const events=JSON.parse(fs.readFileSync(path.join(root,'roadmap.json'),'utf8')).roadmap_events;"
        "const first=events.findIndex(e=>e.kind==='refinement_update');"
        "const state=foldRefinements(events.slice(0,first+1));"
        "fs.writeFileSync(path.join(root,'PLAN.md'),state.adoption.documents['PLAN.md'].baseline+'\\n'+renderRefinementDocument(state,'PLAN.md')+'\\n');"
    )
    subprocess.run([shutil.which('node'), '--input-type=module', '-e', source],
                   input=json.dumps(str(server.campaign)), text=True, encoding='utf-8',
                   check=True, capture_output=True, timeout=10,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert not refinement_client.read_state(server.campaign)['projection_status']['consistent']
    with page.expect_response(lambda r: '/refinement-close' in r.url and r.request.method == 'POST') as response:
        step.get_by_role('button', name='Done with this slice', exact=True).click()
    assert response.value.ok
    result = refinement_client.read_state(server.campaign)
    assert result['projection_status']['consistent']
    assert result['sequence'] == before['sequence'] + 1
    assert _foundation(result['state'])['phase'] == 'done'
