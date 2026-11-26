"""Wave 3 regression & integration oracle for Anchor AI Cockpit & Cave of Wonders Elegance Overhaul:
- #caveStewardWatchlistDrawer collapsed by default
- Duplicate visual horizon bar inside #caveWorkingListSpine hidden while retaining #wlHzToday/Week/Month/StarChart DOM IDs and #shTriage 3-driver contract
- .cave-outlook-mail-split widened to minmax(340px, 420px) minmax(0, 1fr) and 100%-width #caveDlgStewardDirectionsBar + #caveDlgStewardDirectionsInput (rows="1", min-height: 58px)
- Unique caveSrAttachmentPreviewHost ID, #caveSrStewardPromptInput hidden when Speed Racer queue is non-empty, Enter + spinner + d.message error display when empty, and line 972 stray data-steward-draft-intent removed
- Reversible Spam/Unspam UI controls wired in Cave Email and Speed Racer
- Cross-wave property gates (durability, idempotence, boundedness, containment) & distro cleanliness
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import urllib.request

import pytest

import anchor_gui
import comms_connector as comms
import distro
import high_seat_page
import paths


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(comms, "_CAVE_STEWARD_DISPATCH_HOOK", None)
    monkeypatch.setattr(comms, "_SEND_TRANSPORT_HOOK", None)
    return tmp_path


def _minimal_cave_ctx(**overrides) -> dict:
    ctx = {
        "build": "w3-elegance-test",
        "today": date(2026, 11, 17),
        "today_str": "Tue, Nov 17, 2026",
        "week": "Week of Nov 16",
        "week_short": "Nov 16-22",
        "auth_required": False,
        "logged_in": True,
        "steward": {
            "label": "Ecgberht",
            "high_seat_name": "Cave of Wonders",
            "high_seat": "cave-of-wonders.jpg",
            "campaign_icon": "campaign-aladdin-star-chart.jpg",
            "mode_name": "Star Chart",
        },
        "campaign": {"pid": "proj-camp"},
        "entries": [],
        "facts": {},
        "groups": {},
        "initiatives": [],
        "parked": [],
        "rows": [],
        "bullets": [],
        "counts": {},
        "tasks_open": 0,
        "seeds": 0,
        "seed_rows": [],
        "terms_open": 0,
        "capacity": [],
    }
    ctx.update(overrides)
    return ctx


def test_w3_watchlist_collapsed_and_horizon_dedup_preserving_shtriage_and_dom_ids(isolated_data, monkeypatch):
    monkeypatch.setattr(
        comms,
        "build_live_cockpits_and_goals_catalogs",
        lambda: {
            "cockpits_dropdown_catalog": [],
            "goals_dropdown_catalog": [],
            "project_folders_catalog": ["Business", "Research", "Teaching"],
        },
    )
    today_d = date.today()
    comms.mutate_working_list_spine("add_tile", {
        "title": "Finalize Quantum Paper Figures",
        "category": "Research",
        "priority": 1,
        "due": today_d.isoformat(),
        "goalName": "Tier 1 Goal: Quantum Paper",
        "steps": [{"id": "st-1", "text": "Verify Figure 2 curves", "done": False}],
    })
    comms.mutate_working_list_spine("add_tile", {
        "title": "Prepare Lecture Deck",
        "category": "Teaching",
        "priority": 2,
        "due": (today_d + timedelta(days=3)).isoformat(),
        "steps": [{"id": "st-2", "text": "Update lecture slides", "done": False}],
    })
    comms.add_watchlist_item({
        "title": "Monthly Family Trust Review",
        "due": (today_d + timedelta(days=15)).isoformat(),
        "counterparty": "Counsel",
    })

    ctx = _minimal_cave_ctx(
        today=today_d,
        comms={
            "watchlist": {
                "items": [
                    {
                        "id": "wl-item-1",
                        "title": "Monthly Family Trust Review",
                        "due_date": (today_d + timedelta(days=15)).isoformat(),
                        "counterparty": "Counsel",
                        "status": "open",
                    }
                ]
            }
        },
    )
    html = high_seat_page.render_high_seat_html(ctx)
    css_src = (REPO_ROOT / "static" / "high-seat-page.css").read_text(encoding="utf-8")

    # (1) #caveStewardWatchlistDrawer starts collapsed by default (no `open` attribute)
    m_wl = re.search(r'<details\b[^>]*id="caveStewardWatchlistDrawer"[^>]*>', html)
    assert m_wl is not None, "#caveStewardWatchlistDrawer must render when watchlist items exist"
    wl_open_tag = m_wl.group(0)
    assert " open" not in wl_open_tag, f"#caveStewardWatchlistDrawer must start collapsed, got: {wl_open_tag}"

    # (2) #shTriage renders the minimalist Chief-of-Staff bar ([Chief of Staff] + [Running] + [Poincare Map]) + Top-3 panel
    assert 'id="shTriage"' in html
    assert 'id="btnCosToggleExpand"' in html
    assert 'id="cosRunningTile"' in html
    assert "/steward-static/poincare.html" in html
    assert 'id="cosSuggestionsPanel"' in html
    assert 'id="cosTopThreeStack"' in html
    assert 'id="cosCompactSummaryRow"' in html
    assert "cosOrangesModal" not in html
    assert "data-cos-dispatch-skill=" not in html

    # (3) Duplicate visual horizon bar inside #caveWorkingListSpine is hidden while #wlHzToday/Week/Month/StarChart remain in DOM
    m_hz_bar = re.search(r'<span\b[^>]*id="wlHorizonCountsBar"[^>]*>', html)
    assert m_hz_bar is not None
    assert "hidden" in m_hz_bar.group(0)
    assert "display:none" in m_hz_bar.group(0).replace(" ", "")
    assert re.search(r"#wlHorizonCountsBar\s*\{[^}]*display:\s*none\s*!important", css_src)
    assert 'id="wlHzToday">1<' in html
    assert 'id="wlHzWeek">1<' in html
    assert 'id="wlHzMonth">1<' in html
    assert 'id="wlHzStarChart">1<' in html


def test_w3_wide_email_split_and_full_width_directions_bar_css_and_dom(isolated_data):
    html = high_seat_page.render_high_seat_html(_minimal_cave_ctx())
    css_src = (REPO_ROOT / "static" / "high-seat-page.css").read_text(encoding="utf-8")
    js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")

    # (1) .cave-outlook-mail-split widened to minmax(340px, 420px) minmax(0, 1fr)
    m_split = re.search(r"\.cave-outlook-mail-split\s*\{([^}]*)\}", css_src)
    assert m_split is not None
    assert "grid-template-columns: minmax(340px, 420px) minmax(0, 1fr)" in m_split.group(1)

    # Float mode media queries also preserve minmax(340px, 420px) minmax(0, 1fr)
    assert "grid-template-columns: minmax(340px, 420px) minmax(0, 1fr) !important" in css_src

    # (2) #caveDlgStewardDirectionsBar and #caveDlgStewardDirectionsInput span 100% width with rows="1" in HTML and min-height: 58px in CSS
    assert '<div id="caveDlgStewardDirectionsBar" class="cave-scribe-bar">' in html
    assert '<textarea id="caveDlgStewardDirectionsInput" rows="1" class="cave-autogrow-ta"' in html

    m_bar_css = re.search(r"#caveDlgStewardDirectionsBar\s*\{([^}]*)\}", css_src)
    assert m_bar_css is not None
    bar_rules = m_bar_css.group(1)
    assert "width: 100%" in bar_rules
    assert "flex-direction: column" in bar_rules

    m_in_css = re.search(r"#caveDlgStewardDirectionsInput\s*\{([^}]*)\}", css_src)
    assert m_in_css is not None
    in_rules = m_in_css.group(1)
    assert "width: 100%" in in_rules
    assert "min-height: 58px" in in_rules
    assert "box-sizing: border-box" in in_rules

    # .cave-autogrow-ta global rule keeps min-height: 30px so #caveSrFeedbackInput is unaffected
    m_ag_css = re.search(r"\.cave-autogrow-ta\s*\{([^}]*)\}", css_src)
    assert m_ag_css is not None
    assert "min-height: 30px" in m_ag_css.group(1)


def test_w3_speed_racer_unique_preview_host_prompt_bar_hiding_enter_spinner_and_error(isolated_data):
    # Render with empty Speed Racer queue
    html_empty = high_seat_page.render_high_seat_html(
        _minimal_cave_ctx(comms={"speed_racer": {"queue": [], "archive": []}})
    )
    assert html_empty.count('id="caveSrAttachmentPreviewHost"') == 1
    m_bar_empty = re.search(r'<div\b[^>]*id="caveSrStewardPromptBar"[^>]*>', html_empty)
    m_in_empty = re.search(r'<input\b[^>]*id="caveSrStewardPromptInput"[^>]*>', html_empty)
    assert m_bar_empty is not None and " hidden" not in m_bar_empty.group(0)
    assert m_in_empty is not None and " hidden" not in m_in_empty.group(0)

    # Render with non-empty Speed Racer queue
    html_nonempty = high_seat_page.render_high_seat_html(
        _minimal_cave_ctx(
            comms={
                "speed_racer": {
                    "queue": [
                        {
                            "id": "sr-test-1",
                            "uid": "u-test-1",
                            "to": "colleague@example.org",
                            "subject": "Re: Project update",
                            "draft_body": "Hi,\n\nSounds good.\n\nBest,",
                        }
                    ],
                    "archive": [],
                }
            }
        )
    )
    # Duplicate caveSrAttachmentPreviewHost ID is fixed (unique even when sr-card is rendered)
    assert html_nonempty.count('id="caveSrAttachmentPreviewHost"') == 1
    assert html_nonempty.count('id="caveSrCardAttachmentPreviewHost"') == 1

    # Stray data-steward-draft-intent at line 972 is removed from data-sr-tone="async_email"
    m_async_btn = re.search(r'<button\b[^>]*data-sr-tone="async_email"[^>]*>', html_nonempty)
    assert m_async_btn is not None
    assert "data-steward-draft-intent" not in m_async_btn.group(0)

    # #caveSrStewardPromptBar and #caveSrStewardPromptInput remain visible even when queue is non-empty (Journal 0057)
    m_bar_nonempty = re.search(r'<div\b[^>]*id="caveSrStewardPromptBar"[^>]*>', html_nonempty)
    m_in_nonempty = re.search(r'<input\b[^>]*id="caveSrStewardPromptInput"[^>]*>', html_nonempty)
    assert m_bar_nonempty is not None and " hidden" not in m_bar_nonempty.group(0)
    assert m_in_nonempty is not None and " hidden" not in m_in_nonempty.group(0)
    assert 'id="btnCaveSrSendFeedbackSteward"' in html_nonempty

    # Verify JS runtime behavior for Speed Racer prompt bar hiding, Enter keydown, spinner, and d.message error display
    js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    node_probe = """
const fs = require('fs');
const vm = require('vm');
const jsSrc = fs.readFileSync(%s, 'utf8');

const elements = {};
function makeEl(id, tag) {
  return {
    id: id,
    tagName: tag || 'DIV',
    hidden: false,
    disabled: false,
    value: '',
    innerHTML: '',
    textContent: '',
    style: {},
    attributes: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, force) {
        if (force === undefined) {
          if (this._set.has(c)) { this._set.delete(c); return false; }
          this._set.add(c); return true;
        }
        if (force) this._set.add(c); else this._set.delete(c);
        return !!force;
      },
      contains(c) { return this._set.has(c); }
    },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return this.attributes[k] || null; },
    removeAttribute(k) { delete this.attributes[k]; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest(sel) {
      if (sel.includes('#' + this.id)) return this;
      return null;
    },
    click() {
      for (const fn of clickListeners) {
        fn({
          target: this,
          preventDefault() {},
          stopPropagation() {}
        });
      }
    }
  };
}

[
  ['caveSpeedRacerDeckHost', 'DIV'],
  ['caveSrStewardPromptBar', 'DIV'],
  ['caveSrStewardPromptInput', 'INPUT'],
  ['btnCaveSrStewardDraft', 'BUTTON'],
  ['caveSrStewardPromptError', 'SPAN'],
  ['caveSpeedRacerTile', 'DIV'],
  ['caveSpeedRacerBody', 'DIV'],
  ['caveSrToggleHint', 'SPAN'],
  ['caveSpeedRacerArchiveDrawer', 'DIV'],
  ['caveMailSpamUndoBar', 'DIV'],
  ['caveMailSpamUndoText', 'SPAN'],
  ['btnCaveUndoSpam', 'BUTTON'],
  ['btnCaveDlgSpam', 'BUTTON'],
  ['btnCaveDlgUnspam', 'BUTTON'],
  ['caveSrSpamUndoBar', 'DIV'],
  ['caveSrSpamUndoText', 'SPAN'],
  ['btnCaveSrUnspam', 'BUTTON']
].forEach(([id, tag]) => { elements[id] = makeEl(id, tag); });
elements.btnCaveSrStewardDraft.innerHTML = 'Draft';
elements.caveSrStewardPromptError.hidden = true;
elements.caveMailSpamUndoBar.hidden = true;
elements.btnCaveDlgUnspam.hidden = true;
elements.caveSrSpamUndoBar.hidden = true;

const clickListeners = [];
const keydownListeners = [];
let fetchCalls = [];
let pendingResolve = null;

const storageMock = { getItem() { return null; }, setItem() {}, removeItem() {} };
const sandbox = {
  window: {
    ANCHOR_SPEED_RACER_INIT: { queue: [{ id: 'sr-1', uid: 'u-1', account_id: 'acc-1', to: 'user@example.com', subject: 'Hello', draft_body: 'Body', attachments: [{ filename: 'Agenda.pdf' }] }], archive: [] },
    ANCHOR_WORKING_LIST_INIT: { tiles: [], proposals: [], auto_checked: [], horizon_counts: {} },
    localStorage: storageMock,
    sessionStorage: storageMock,
    addEventListener() {},
    removeEventListener() {},
    location: { search: '', pathname: '/', hash: '', origin: 'http://localhost:8777', reload() {} },
    history: { replaceState() {} },
    innerHeight: 900,
    innerWidth: 1440,
    getSelection() { return ''; },
    scrollBy() {},
    open() { return null; }
  },
  document: {
    title: '',
    readyState: 'complete',
    hidden: false,
    activeElement: null,
    head: { appendChild() {} },
    body: { appendChild() {} },
    getElementById(id) { return elements[id] || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement(tag) { return makeEl('', String(tag || 'DIV').toUpperCase()); },
    addEventListener(type, fn) {
      if (type === 'click') clickListeners.push(fn);
      if (type === 'keydown') keydownListeners.push(fn);
    }
  },
  localStorage: storageMock,
  sessionStorage: storageMock,
  location: { search: '', pathname: '/', hash: '', origin: 'http://localhost:8777', reload() {} },
  history: { replaceState() {} },
  innerHeight: 900,
  innerWidth: 1440,
  getComputedStyle() { return { position: 'static', display: 'block' }; },
  URLSearchParams,
  Event: function(t) { this.type = t; },
  CustomEvent: function(t) { this.type = t; },
  navigator: { clipboard: { writeText() {} } },
  console,
  fetch(url, opts) {
    const bodyStr = (opts && opts.body) || '{}';
    fetchCalls.push({ url, opts: JSON.parse(bodyStr) });
    return new Promise((resolve) => { pendingResolve = resolve; });
  },
  setTimeout() { return 1; },
  clearTimeout() {},
  setInterval() { return 1; },
  clearInterval() {},
  Promise,
  JSON,
  Date,
  Math,
  Object,
  Array,
  String,
  Number,
  Boolean,
  RegExp,
  Map,
  Set,
  Error,
  encodeURIComponent,
  decodeURIComponent,
  parseInt,
  parseFloat,
  isNaN
};
sandbox.window.document = sandbox.document;
vm.runInNewContext(jsSrc, sandbox);

// 1) Initial queue has 1 item -> openCaveSpeedRacer renders tile and keeps prompt bar & input visible
sandbox.window.openCaveSpeedRacer();
const visibleWhenNonEmpty = elements.caveSrStewardPromptBar.hidden === false && elements.caveSrStewardPromptInput.hidden === false;
const deckHasSinglePreviewHost = !elements.caveSpeedRacerDeckHost.innerHTML.includes('id="caveSrAttachmentPreviewHost"') &&
  elements.caveSpeedRacerDeckHost.innerHTML.includes('id="caveSrCardAttachmentPreviewHost"') &&
  elements.caveSpeedRacerDeckHost.innerHTML.includes('btnCaveSrSendFeedbackSteward');

// 2) Resolve openCaveSpeedRacer list fetch with empty queue -> prompt bar becomes visible
pendingResolve({
  status: 200,
  json: () => Promise.resolve({ ok: true, speed_racer: { queue: [], archive: [] } })
});

setImmediate(() => {
  const visibleWhenEmpty = elements.caveSrStewardPromptBar.hidden === false && elements.caveSrStewardPromptInput.hidden === false;

  // 3) Type prompt and press Enter on #caveSrStewardPromptInput
  fetchCalls = [];
  elements.caveSrStewardPromptInput.value = 'Draft note to board on Q4 timeline';
  for (const kfn of keydownListeners) {
    kfn({
      key: 'Enter',
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      isComposing: false,
      target: elements.caveSrStewardPromptInput,
      preventDefault() {}
    });
  }

  const spinnerShown = elements.btnCaveSrStewardDraft.disabled === true && elements.btnCaveSrStewardDraft.innerHTML.includes('Drafting');
  const sentPayload = fetchCalls.length === 1 ? fetchCalls[0].opts : null;

  // 4) Resolve draft request with HTTP 503 + d.message error
  pendingResolve({
    status: 503,
    json: () => Promise.resolve({ ok: false, message: 'Scribe model temporarily unavailable — retry' })
  });

  setImmediate(() => {
    setImmediate(() => {
      console.log(JSON.stringify({
        visibleWhenNonEmpty,
        deckHasSinglePreviewHost,
        visibleWhenEmpty,
        spinnerShown,
        sentPayload,
        btnReenabled: elements.btnCaveSrStewardDraft.disabled === false,
        errorHidden: elements.caveSrStewardPromptError.hidden,
        errorText: elements.caveSrStewardPromptError.textContent
      }));
    });
  });
});
""" % json.dumps(str(REPO_ROOT / "static" / "high-seat-page.js"))

    proc = subprocess.run(
        ["node", "-e", node_probe],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    res = json.loads(proc.stdout.strip().splitlines()[-1])
    assert res["visibleWhenNonEmpty"] is True
    assert res["deckHasSinglePreviewHost"] is True
    assert res["visibleWhenEmpty"] is True
    assert res["spinnerShown"] is True
    assert res["sentPayload"]["action"] == "speed_racer_queue"
    assert res["sentPayload"]["steward_directions"] == "Draft note to board on Q4 timeline"
    assert res["sentPayload"]["uid"] == ""
    assert res["sentPayload"]["to"] == ""
    assert res["btnReenabled"] is True
    assert res["errorHidden"] is False
    assert "Scribe model temporarily unavailable — retry" in res["errorText"]


def test_w3_reversible_spam_unspam_ui_controls_in_cave_email_and_speed_racer(isolated_data, monkeypatch):
    monkeypatch.setattr(comms, "mark_email_read_remote", lambda **_kw: {"ok": True})
    comms.save_comms_sync({
        "synced_at": "2026-11-17 09:00",
        "calendar_events": [],
        "sent_email_headers": [],
        "email_headers": [
            {
                "uid": "u-w3-spam-1",
                "account_id": "acc-1",
                "account_badge": "Gmail",
                "from": "Noisy Vendor <Promo.Bot@Example.COM>",
                "sender_email": "Promo.Bot@Example.COM",
                "subject": "Special Webinar Invite",
                "snippet": "Join our webinar today.",
                "date": "2026-11-17 08:30",
                "is_read": False,
            },
            {
                "uid": "u-w3-keep-2",
                "account_id": "acc-1",
                "account_badge": "Gmail",
                "from": "Colleague <colleague@example.com>",
                "sender_email": "colleague@example.com",
                "subject": "Lab meeting agenda",
                "snippet": "See agenda.",
                "date": "2026-11-17 08:45",
                "is_read": False,
            },
        ],
    })
    comms.queue_speed_racer_draft({
        "uid": "u-w3-spam-1",
        "to": "Noisy Vendor <Promo.Bot@Example.COM>",
        "subject": "Re: Special Webinar Invite",
        "draft_body": "Hi,\n\nUnsubscribe.\n\nBest,",
        "preserve_manual_draft": True,
    })

    imp_init, oth_init = comms.classify_inbox_emails(comms.load_comms_sync()["email_headers"], comms.load_triage_prefs())
    sr_init = comms.load_speed_racer_queue()
    html = high_seat_page.render_high_seat_html(
        _minimal_cave_ctx(
            comms={
                "important_emails": imp_init,
                "other_emails": oth_init,
                "speed_racer": sr_init,
            }
        )
    )

    # Verify Spam and Unspam UI controls exist across Cave Email cards, Email reading pane, and Speed Racer with account_id scoping
    assert 'data-cave-mail-triage="spam"' in html
    assert 'data-mail-account-id="acc-1"' in html
    assert 'id="btnCaveDlgSpam"' in html
    assert 'id="btnCaveDlgUnspam"' in html
    assert 'id="caveMailSpamUndoBar"' in html
    assert 'id="btnCaveUndoSpam"' in html
    assert 'id="btnCaveSrSpam"' in html
    assert 'id="caveSrSpamUndoBar"' in html
    assert 'id="btnCaveSrUnspam"' in html

    # Execute high-seat-page.js click handlers in Node vm to verify:
    # (a) account_id is sent on Card Spam, Dialog Spam, Speed Racer Spam, and Undo Unspam
    # (b) failed Speed Racer Spam rolls back the removed draft and undo bar
    # (c) failed Unspam keeps the undo bar visible instead of stranding the user
    spam_ui_probe = r"""
const fs = require('fs');
const vm = require('vm');
const jsSrc = fs.readFileSync(process.argv[2], 'utf8');

const elements = {};
const clickListeners = [];
let fetchCalls = [];
let pendingResolve = null;

function makeEl(id, tag) {
  return {
    id: id,
    tagName: tag || 'DIV',
    hidden: false,
    disabled: false,
    value: '',
    innerHTML: '',
    textContent: '',
    style: {},
    attributes: {},
    parentCard: null,
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, f) {
        if (f === undefined) {
          if (this._set.has(c)) { this._set.delete(c); return false; }
          this._set.add(c); return true;
        }
        if (f) this._set.add(c); else this._set.delete(c);
        return !!f;
      },
      contains(c) { return this._set.has(c); }
    },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; },
    removeAttribute(k) { delete this.attributes[k]; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest(sel) {
      if (this.id && sel.includes('#' + this.id)) return this;
      if (this.attributes['data-cave-mail-triage'] && sel.includes('[data-cave-mail-triage]')) return this;
      if (this.attributes['data-sr-spam'] && sel.includes('[data-sr-spam]')) return this;
      if (sel.includes('.cave-mail-card') && this.parentCard) return this.parentCard;
      return null;
    }
  };
}

[
  ['caveSpeedRacerDeckHost', 'DIV'],
  ['caveSrStewardPromptBar', 'DIV'],
  ['caveSrStewardPromptInput', 'INPUT'],
  ['btnCaveSrStewardDraft', 'BUTTON'],
  ['caveSrStewardPromptError', 'SPAN'],
  ['caveSpeedRacerTile', 'DIV'],
  ['caveSpeedRacerBody', 'DIV'],
  ['caveSrToggleHint', 'SPAN'],
  ['caveSpeedRacerArchiveDrawer', 'DIV'],
  ['caveMailSpamUndoBar', 'DIV'],
  ['caveMailSpamUndoText', 'SPAN'],
  ['btnCaveUndoSpam', 'BUTTON'],
  ['btnCaveDlgSpam', 'BUTTON'],
  ['btnCaveDlgUnspam', 'BUTTON'],
  ['caveSrSpamUndoBar', 'DIV'],
  ['caveSrSpamUndoText', 'SPAN'],
  ['btnCaveSrUnspam', 'BUTTON'],
  ['btnCaveSrSpam', 'BUTTON'],
  ['caveDlgMailSubject', 'DIV'],
  ['caveDialogueThreadList', 'DIV']
].forEach(([id, tag]) => { elements[id] = makeEl(id, tag); });
elements.caveMailSpamUndoBar.hidden = true;
elements.btnCaveDlgUnspam.hidden = true;
elements.caveSrSpamUndoBar.hidden = true;
elements.btnCaveSrSpam.setAttribute('data-sr-spam', '1');

const selectedCard = makeEl('', 'DIV');
selectedCard.setAttribute('data-mail-uid', 'u-w3-spam-1');
selectedCard.setAttribute('data-mail-account-id', 'acc-1');
selectedCard.setAttribute('data-mail-sender', 'Promo.Bot@Example.COM');
selectedCard.setAttribute('data-mail-source', 'Gmail');
selectedCard.setAttribute('data-mail-opened', '1');

const cardSpamPill = makeEl('', 'BUTTON');
cardSpamPill.setAttribute('data-cave-mail-triage', 'spam');
cardSpamPill.setAttribute('data-mail-uid', 'u-w3-spam-1');
cardSpamPill.setAttribute('data-mail-account-id', 'acc-1');
cardSpamPill.setAttribute('data-mail-sender', 'Promo.Bot@Example.COM');
cardSpamPill.setAttribute('data-mail-subject', 'Special Webinar Invite');
cardSpamPill.parentCard = selectedCard;

const storageMock = { getItem() { return null; }, setItem() {}, removeItem() {} };
const sandbox = {
  window: {
    ANCHOR_SPEED_RACER_INIT: {
      queue: [{ id: 'sr-spam-1', uid: 'u-w3-spam-1', account_id: 'acc-1', to: 'Promo.Bot@Example.COM', subject: 'Re: Special Webinar Invite', draft_body: 'Draft' }],
      archive: []
    },
    ANCHOR_WORKING_LIST_INIT: { tiles: [], proposals: [], auto_checked: [], horizon_counts: {} },
    localStorage: storageMock,
    sessionStorage: storageMock,
    addEventListener() {},
    removeEventListener() {},
    location: { search: '', pathname: '/', hash: '', origin: 'http://localhost:8777', reload() {} },
    history: { replaceState() {} },
    innerHeight: 900,
    innerWidth: 1440,
    getSelection() { return ''; },
    scrollBy() {},
    open() { return null; }
  },
  document: {
    title: '',
    readyState: 'complete',
    hidden: false,
    activeElement: null,
    head: { appendChild() {} },
    body: { appendChild() {} },
    getElementById(id) { return elements[id] || null; },
    querySelector(sel) {
      if (sel.includes('.cave-mail-card')) return selectedCard;
      return null;
    },
    querySelectorAll() { return []; },
    createElement(tag) { return makeEl('', String(tag || 'DIV').toUpperCase()); },
    addEventListener(type, fn) {
      if (type === 'click') clickListeners.push(fn);
    }
  },
  localStorage: storageMock,
  sessionStorage: storageMock,
  location: { search: '', pathname: '/', hash: '', origin: 'http://localhost:8777', reload() {} },
  history: { replaceState() {} },
  innerHeight: 900,
  innerWidth: 1440,
  getComputedStyle() { return { position: 'static', display: 'block' }; },
  URLSearchParams,
  Event: function(t) { this.type = t; },
  CustomEvent: function(t) { this.type = t; },
  navigator: { clipboard: { writeText() {} } },
  console,
  fetch(url, opts) {
    const bodyStr = (opts && opts.body) || '{}';
    fetchCalls.push({ url, opts: JSON.parse(bodyStr) });
    return new Promise((resolve) => { pendingResolve = resolve; });
  },
  setTimeout() { return 1; },
  clearTimeout() {},
  setInterval() { return 1; },
  clearInterval() {},
  Promise, JSON, Date, Math, Object, Array, String, Number, Boolean, RegExp, Map, Set, Error,
  encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN
};
sandbox.window.document = sandbox.document;
vm.runInNewContext(jsSrc, sandbox);

function fireClick(target) {
  for (const fn of clickListeners) {
    fn({ target, preventDefault() {}, stopPropagation() {} });
  }
}

(async () => {
  const flush = () => new Promise((r) => setImmediate(() => setImmediate(r)));

  // 1) Speed Racer Spam failure (HTTP 400 / ok:false) rolls back queue & hides undo bar
  fetchCalls = [];
  fireClick(elements.btnCaveSrSpam);
  const srSpamPayload = fetchCalls[0].opts;
  pendingResolve({ status: 400, json: () => Promise.resolve({ ok: false, error: 'MAX_SPAM_SENDERS reached' }) });
  await flush();
  const srRollbackRestoredDraft = elements.caveSpeedRacerDeckHost.innerHTML.includes('Re: Special Webinar Invite');
  const srUndoHiddenAfterFail = elements.caveSrSpamUndoBar.hidden === true;

  // 2) Card Spam Pill sends account_id and succeeds -> shows undo bar
  fetchCalls = [];
  fireClick(cardSpamPill);
  const cardSpamPayload = fetchCalls[0].opts;
  pendingResolve({ status: 200, json: () => Promise.resolve({ ok: true, important_emails: [], other_emails: [], acted_upon_emails: [] }) });
  await flush();
  const undoVisibleAfterSpam = elements.caveMailSpamUndoBar.hidden === false;

  // 3) Unspam failure (HTTP 500 / ok:false) keeps undo bar visible and sends account_id
  fetchCalls = [];
  fireClick(elements.btnCaveUndoSpam);
  const unspamPayload = fetchCalls[0].opts;
  pendingResolve({ status: 500, json: () => Promise.resolve({ ok: false, error: 'Temporary error' }) });
  await flush();
  const undoPreservedAfterFailedUnspam = elements.caveMailSpamUndoBar.hidden === false;

  // 4) Unspam success clears undo bar
  fetchCalls = [];
  fireClick(elements.btnCaveUndoSpam);
  pendingResolve({ status: 200, json: () => Promise.resolve({ ok: true, important_emails: [], other_emails: [], acted_upon_emails: [] }) });
  await flush();
  const undoHiddenAfterSucceededUnspam = elements.caveMailSpamUndoBar.hidden === true;

  // 5) Dialog Spam button sends account_id from right-pane context
  fetchCalls = [];
  fireClick(elements.btnCaveDlgSpam);
  const dlgSpamPayload = fetchCalls[0].opts;
  pendingResolve({ status: 200, json: () => Promise.resolve({ ok: true }) });
  await flush();

  process.stdout.write(JSON.stringify({
    srSpamAcct: srSpamPayload.account_id,
    srRollbackRestoredDraft,
    srUndoHiddenAfterFail,
    cardSpamAcct: cardSpamPayload.account_id,
    undoVisibleAfterSpam,
    unspamAcct: unspamPayload.account_id,
    undoPreservedAfterFailedUnspam,
    undoHiddenAfterSucceededUnspam,
    dlgSpamAcct: dlgSpamPayload.account_id
  }) + '\n');
})();
"""
    with tempfile.TemporaryDirectory() as tmp_d:
        probe_path = Path(tmp_d) / "spam_ui_probe.cjs"
        probe_path.write_text(spam_ui_probe, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(probe_path), str(REPO_ROOT / "static" / "high-seat-page.js")],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=True,
        )
    ui_res = json.loads(proc.stdout.strip().splitlines()[-1])
    assert ui_res["srSpamAcct"] == "acc-1"
    assert ui_res["srRollbackRestoredDraft"] is True
    assert ui_res["srUndoHiddenAfterFail"] is True
    assert ui_res["cardSpamAcct"] == "acc-1"
    assert ui_res["undoVisibleAfterSpam"] is True
    assert ui_res["unspamAcct"] == "acc-1"
    assert ui_res["undoPreservedAfterFailedUnspam"] is True
    assert ui_res["undoHiddenAfterSucceededUnspam"] is True
    assert ui_res["dlgSpamAcct"] == "acc-1"


def test_w3_scope_preservation_distro_hygiene_and_live_http_surfaces(isolated_data, tmp_path):
    # 1) Scope preservation: anvil_session.py, steward_cockpit/static/anvil.html, and code_jobs.py untouched vs HEAD
    git_chk = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "anvil_session.py", "steward_cockpit/static/anvil.html", "steward_cockpit/code_jobs.py"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert git_chk.stdout.strip() == ""

    # 2) Live HTTP surface verification over AnchorHandler (Cave GET / + AI Cockpit GET /steward/v1 + CSS/JS static assets)
    eff_dir = tmp_path / "live_surface_effort"
    eff_dir.mkdir(parents=True, exist_ok=True)
    (eff_dir / "ECGBERHT.md").write_text(
        "# Live Effort\n\n## The Plan\n- [x] **Phase 1: Setup** (id: `p1`) — Done\n- [ ] **Phase 2: Verify** (id: `p2`) — Active\n",
        encoding="utf-8",
    )
    (eff_dir / "DELIVERABLES.md").write_text("# Deliverables\n", encoding="utf-8")

    srv = anchor_gui._ExclusiveThreadingHTTPServer(("127.0.0.1", 0), anchor_gui.AnchorHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        tok = paths.expected_token()
        hdrs = {"Cookie": f"{paths.AUTH_COOKIE_NAME}={tok}"} if tok else {}

        def _http_get(rel_url: str) -> str:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{rel_url}", headers=hdrs)
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 200
                return resp.read().decode("utf-8", errors="replace")

        cave_live = _http_get("/")
        assert 'id="shTriage"' in cave_live
        assert 'id="caveWorkingListSpine"' in cave_live
        assert 'id="caveDlgStewardDirectionsInput"' in cave_live
        assert 'id="btnCaveDlgSpam"' in cave_live
        assert cave_live.count('id="caveSrAttachmentPreviewHost"') == 1

        css_live = _http_get("/static/high-seat-page.css")
        assert "minmax(340px, 420px) minmax(0, 1fr)" in css_live

        cockpit_live = _http_get(f"/steward/v1?dir={urllib.request.quote(str(eff_dir))}")
        m_shared = re.search(r'src="([^"]*shared\.js[^"]*)"', cockpit_live)
        assert m_shared is not None
        shared_js_live = _http_get(m_shared.group(1))
        assert "Accept New Plan" not in shared_js_live
        assert "buildClientDeliverableHierarchyFallback" not in shared_js_live
    finally:
        srv.shutdown()
        srv.server_close()

    # 3) Distro hygiene scan across Wave 3 deliverables
    w3_files = (
        "high_seat_page.py",
        "static/high-seat-page.css",
        "static/high-seat-page.js",
        "tests/test_steward_cockpit_cave_elegance_2026_11_17_w3.py",
    )
    hits = []
    for rel in w3_files:
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        hits.extend(distro._scan_text(rel, txt))
        hits.extend(distro._scan_registry_artifact(rel, txt))
    assert hits == [], f"Unexpected distro PII/secret/host-path hits: {hits}"
