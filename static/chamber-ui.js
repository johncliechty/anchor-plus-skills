/* ═══════════════════════════════════════════════════════════════════════════
   Ecgberht Chamber UI (Wave 18) — steps, proposals, confirmations, artifacts,
   corrections. Renders engine view models from /api/ecgberht/chamber_* via
   scripts/chamber-ui-bridge.mjs. I52: scaffold never wears commissioned-
   artifact chrome; no artifact card without a bundle hash.

   POLLER DISCIPLINE — adopts static/high-seat.js:485-528 pattern BY NAME:
   - ECG_CHAMBER_MIN_MS = one healthy visible-tab poll interval
   - ECG_CHAMBER_MAX_MS = geometric backoff ceiling under consecutive failures
   - document.hidden → skip poll entirely; pagehide → clear timer
   Under failure backoff latency may reach MAX_MS; under a hidden tab polls
   skip entirely — both are the contract, not silent violations.
   ═══════════════════════════════════════════════════════════════════════════ */

/* Wave 18 poll contract (poller-audit tests import these names — do not rename):
   mirrors ECG_HS_MIN_MS / ECG_HS_MAX_MS from high-seat.js:485-528. */
var ECG_CHAMBER_MIN_MS = 90000;
var ECG_CHAMBER_MAX_MS = 15 * 60 * 1000;

(function () {
  'use strict';

  function _el(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }

  // (2026-08-04) The CANONICAL token accessor is `_anchorToken()` — localStorage
  // key `anchor_token` — the same one project-window.js and high-seat.js use.
  // This file originally read `window._anchorTokenQuery` (defined NOWHERE) and
  // `window.ANCHOR_TOKEN` (not set on the project window), so every chamber GET
  // went out unauthenticated, 401'd, and re-prompted for a token the window
  // already held — the exact defect reported against the seal.
  function _tokenValue() {
    try {
      if (typeof _anchorToken === 'function') return _anchorToken() || '';
    } catch (e) { /* fall through */ }
    return (window.ANCHOR_TOKEN || window.anchorToken || '');
  }

  function _tok() {
    var t = _tokenValue();
    return t ? ('&token=' + encodeURIComponent(t)) : '';
  }

  function _pid() {
    return (typeof PROJECT_ID !== 'undefined' && PROJECT_ID)
      ? PROJECT_ID
      : (window.PROJECT_ID || '');
  }

  function _getJson(url, cb) {
    var hdrs = {};
    var _t = _tokenValue();
    if (_t) hdrs['X-Anchor-Token'] = _t;
    if (window.BUILD_ID) hdrs['X-Anchor-Build'] = window.BUILD_ID;
    fetch(url, { headers: hdrs, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) {
        return { ok: r.ok, status: r.status, body: j };
      }); })
      .then(function (res) { cb(res.ok && res.body && res.body.ok !== false, res.body); })
      .catch(function () { cb(false, null); });
  }

  function _postJson(url, body, cb) {
    // Prefer project-window _postJson when available (token on header).
    if (typeof window._postJson === 'function') {
      window._postJson(url, body)
        .then(function (r) { return r.json(); })
        .then(function (j) { cb(j && j.ok !== false, j); })
        .catch(function () { cb(false, null); });
      return;
    }
    var hdrs = { 'Content-Type': 'application/json' };
    var _t = _tokenValue();
    if (_t) hdrs['X-Anchor-Token'] = _t;
    fetch(url, {
      method: 'POST',
      headers: hdrs,
      credentials: 'same-origin',
      body: JSON.stringify(body || {}),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) { cb(j && j.ok !== false, j); })
      .catch(function () { cb(false, null); });
  }

  /** Paint a named failure (distinct code + text — empty ≠ unreadable). */
  function _paintFailure(host, surface, payload) {
    host.innerHTML = '';
    var box = _el('div', 'ecg-chamber-fail');
    var code = (payload && (payload.status_code || payload.code)) || 'CHAMBER_STATE_UNKNOWN';
    var text = (payload && (payload.user_text || payload.text || payload.message))
      || (surface + ': state unknown — reported as unknown, distinct from empty.');
    box.appendChild(_el('div', 'code', code));
    box.appendChild(_el('div', 'text', text));
    if (payload && payload.last_good_age_ms != null) {
      box.appendChild(_el('div', 'age',
        'last good age: ' + payload.last_good_age_ms + 'ms'));
    }
    host.appendChild(box);
  }

  /** Steps view — confirmed roadmap with per-step status. */
  function ecgChamberRenderSteps(host, view) {
    host.innerHTML = '';
    if (!view || view.ok === false) {
      _paintFailure(host, 'Steps view', view);
      return;
    }
    if (view.empty) {
      _paintFailure(host, 'Steps view', {
        status_code: view.status_code || 'CHAMBER_EMPTY',
        user_text: view.user_text || 'Steps view: nothing here yet.',
      });
      return;
    }
    var list = _el('div', 'ecg-chamber-steps');
    list.appendChild(_el('h3', null, 'Campaign steps'));
    var steps = view.steps || [];
    for (var i = 0; i < steps.length; i++) {
      var s = steps[i];
      var row = _el('div', 'ecg-step ' + (s.status || 'next'));
      row.appendChild(_el('span', 'id', s.id || ''));
      row.appendChild(_el('span', 'name', s.name || ''));
      row.appendChild(_el('span', 'status', s.status || 'unknown'));
      list.appendChild(row);
    }
    host.appendChild(list);
  }

  /** Proposal + confirm — spend shown before confirm; hash-bound. */
  function ecgChamberRenderProposal(host, view, onConfirm) {
    host.innerHTML = '';
    if (!view || view.ok === false) {
      _paintFailure(host, 'Proposal/confirm', view);
      return;
    }
    if (view.empty) {
      _paintFailure(host, 'Proposal/confirm', {
        status_code: 'CHAMBER_EMPTY',
        user_text: view.user_text || 'Proposal/confirm: nothing here yet.',
      });
      return;
    }
    var card = _el('div', 'ecg-chamber-proposal');
    card.appendChild(_el('h3', null, 'Proposal · confirm'));
    card.appendChild(_el('div', 'kind', view.proposal_kind || ''));
    if (view.spend) {
      var spend = _el('div', 'spend');
      spend.appendChild(_el('div', 'lab', 'What will be spent (before confirm)'));
      spend.appendChild(_el('div', 'sum', view.spend.summary || ''));
      if (view.spend.cost_usd != null) {
        spend.appendChild(_el('div', 'usd', '≈ $' + view.spend.cost_usd));
      }
      card.appendChild(spend);
    }
    if (view.confirm && view.confirm.requires_confirm && !view.confirm.confirmed) {
      var btn = _el('button', 'ecg-btn gold', 'Confirm');
      btn.onclick = function () {
        if (typeof onConfirm === 'function') {
          onConfirm({
            proposal: view.proposal,
            proposal_hash: view.confirm.proposal_hash || view.confirm.expected_hash,
          });
        }
      };
      card.appendChild(btn);
    }
    host.appendChild(card);
  }

  /**
   * Artifact view — commissioned chrome only when bundle_hash present and
   * not a scaffold (I52).
   */
  function ecgChamberRenderArtifact(host, view) {
    host.innerHTML = '';
    if (!view || view.ok === false) {
      _paintFailure(host, 'Artifact view', view);
      return;
    }
    if (view.empty) {
      _paintFailure(host, 'Artifact view', {
        status_code: 'CHAMBER_EMPTY',
        user_text: view.user_text || 'Artifact view: nothing here yet.',
      });
      return;
    }
    if (view.refused) {
      _paintFailure(host, 'Artifact view', view);
      return;
    }
    var card = view.card || {};
    var el = _el('div', 'ecg-chamber-artifact commissioned-artifact-card');
    el.appendChild(_el('h3', null, card.title || 'Artifact'));
    el.appendChild(_el('div', 'hash', 'bundle ' + (view.bundle_hash || card.bundle_hash || '')));
    if (card.ref) el.appendChild(_el('div', 'ref', card.ref));
    host.appendChild(el);
  }

  /** Typed conversation artifact (receipt / next-stage) — never chat. */
  function ecgChamberRenderReceipt(host, view) {
    host.innerHTML = '';
    if (!view || view.ok === false) {
      _paintFailure(host, 'Receipt render', view);
      return;
    }
    if (view.empty) {
      _paintFailure(host, 'Receipt render', {
        status_code: 'CHAMBER_EMPTY',
        user_text: view.user_text || 'Receipt render: nothing here yet.',
      });
      return;
    }
    var box = _el('div', 'ecg-chamber-receipts');
    var items = view.receipts || (view.artifact ? [{ artifact: view.artifact }] : []);
    for (var i = 0; i < items.length; i++) {
      var a = items[i].artifact || items[i];
      if (!a) continue;
      var row = _el('div', 'typed-artifact');
      row.appendChild(_el('div', 'kind', a.kind || a.card || 'typed'));
      row.appendChild(_el('div', 'hash', a.content_hash || a.bundle_hash || ''));
      row.setAttribute('data-persisted-chat', 'false');
      box.appendChild(row);
    }
    host.appendChild(box);
  }

  /** Fetch steps view for the open project. */
  function ecgChamberLoadSteps(host, cb) {
    var pid = _pid();
    if (!pid) {
      _paintFailure(host, 'Steps view', {
        status_code: 'CHAMBER_DEP_MISSING',
        user_text: 'Steps view: its data source is not available — shown as unavailable, not blank.',
      });
      if (cb) cb(false);
      return;
    }
    var url = '/api/ecgberht/chamber_steps?project_id=' + encodeURIComponent(pid) + _tok();
    _getJson(url, function (ok, body) {
      if (!ok || !body) {
        _paintFailure(host, 'Steps view', body || {
          status_code: 'CHAMBER_DEP_DEAD',
          user_text: 'Steps view: the data source stopped responding — last good state shown with its age.',
        });
        if (cb) cb(false);
        return;
      }
      ecgChamberRenderSteps(host, body);
      if (cb) cb(true);
    });
  }

  /** Fetch artifact view (I52 + containment). */
  function ecgChamberLoadArtifact(host, opts, cb) {
    opts = opts || {};
    var pid = _pid();
    var url = '/api/ecgberht/chamber_artifact?project_id=' + encodeURIComponent(pid) +
      (opts.rel ? '&rel=' + encodeURIComponent(opts.rel) : '') +
      (opts.bundle_hash ? '&bundle_hash=' + encodeURIComponent(opts.bundle_hash) : '') +
      (opts.kind ? '&kind=' + encodeURIComponent(opts.kind) : '') +
      _tok();
    _getJson(url, function (ok, body) {
      if (!body) {
        _paintFailure(host, 'Artifact view', {
          status_code: 'CHAMBER_DEP_GARBAGE',
          user_text: 'Artifact view: the data source returned something unreadable — shown as an error, nothing invented.',
        });
        if (cb) cb(false);
        return;
      }
      // ok=false is still rendered (refusal / path escape carry their codes)
      ecgChamberRenderArtifact(host, body);
      if (cb) cb(!!ok && !body.refused);
    });
  }

  /** Hash-bound confirm POST. */
  function ecgChamberConfirm(payload, cb) {
    var body = {
      project_id: _pid(),
      proposal: payload.proposal,
      proposal_hash: payload.proposal_hash,
      client_event_id: payload.client_event_id,
      who: payload.who || 'john',
    };
    _postJson('/api/ecgberht/chamber_confirm', body, cb);
  }

  /** Correction propose / confirm. */
  function ecgChamberCorrect(payload, cb) {
    var body = Object.assign({ project_id: _pid(), who: 'john' }, payload || {});
    _postJson('/api/ecgberht/chamber_correct', body, cb);
  }

  // Export for project-window / tests
  window.ecgChamberRenderSteps = ecgChamberRenderSteps;
  window.ecgChamberRenderProposal = ecgChamberRenderProposal;
  window.ecgChamberRenderArtifact = ecgChamberRenderArtifact;
  window.ecgChamberRenderReceipt = ecgChamberRenderReceipt;
  window.ecgChamberLoadSteps = ecgChamberLoadSteps;
  window.ecgChamberLoadArtifact = ecgChamberLoadArtifact;
  window.ecgChamberConfirm = ecgChamberConfirm;
  window.ecgChamberCorrect = ecgChamberCorrect;
  window.ECG_CHAMBER_MIN_MS = ECG_CHAMBER_MIN_MS;
  window.ECG_CHAMBER_MAX_MS = ECG_CHAMBER_MAX_MS;

  /* Ambient chamber steps poll — high-seat.js:485-528 pattern BY NAME.
     Reaches an endpoint that SPAWNS A NODE SUBPROCESS, so: skip while
     hidden, geometric backoff on failure, pagehide cleanup. Never a bare
     setInterval. */
  (function chamberStepsPoller() {
    var MIN_MS = ECG_CHAMBER_MIN_MS, MAX_MS = ECG_CHAMBER_MAX_MS;
    var fails = 0, timer = null;

    var delay = function () {
      var d = MIN_MS * Math.pow(2, Math.min(fails, 4));
      return Math.min(d, MAX_MS);
    };

    var schedule = function () {
      if (timer) { clearTimeout(timer); timer = null; }
      timer = setTimeout(tick, delay());
    };

    var tick = function () {
      if (document.hidden) { schedule(); return; }   // nobody is looking
      var host = document.getElementById('ecgChamberStepsHost');
      if (!host) { schedule(); return; }
      ecgChamberLoadSteps(host, function (ok) {
        fails = ok ? 0 : fails + 1;
        schedule();
      });
    };

    var boot = function () {
      // Only arm when a chamber steps host is present (project dashboard).
      if (!document.getElementById('ecgChamberStepsHost')) return;
      tick();
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) { fails = 0; tick(); }  // refresh on return
      });
      window.addEventListener('pagehide', function () {
        if (timer) { clearTimeout(timer); timer = null; }
      });
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot);
    } else {
      boot();
    }
  })();
})();
