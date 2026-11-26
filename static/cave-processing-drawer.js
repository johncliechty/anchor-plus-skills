/* cave-processing-drawer.js — Inline [N Processing ▾] drawer on Cave #cosTopRowBar (<220 lines, safe textContent only) */
(function () {
  'use strict';

  var _isOpen = false;
  var _pollTimer = null;
  var _lastPayload = null;
  var _inFlight = false;

  function _authHeaders() {
    var h = { Accept: 'application/json' };
    try {
      var tok = window.localStorage && (window.localStorage.getItem('anchor_token') || window.localStorage.getItem('anchor.token'));
      if (tok) {
        h.Authorization = 'Bearer ' + tok;
        h['X-Anchor-Token'] = tok;
      }
      if (window.StewardDialogue && typeof window.StewardDialogue.authHeaders === 'function') {
        return window.StewardDialogue.authHeaders(h);
      }
    } catch (_e) {}
    return h;
  }

  function _el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function _syncButtonChrome(payload) {
    var btn = document.getElementById('cosRunningTile');
    var panel = document.getElementById('cosProcessingPanel');
    if (!btn) return;
    btn.setAttribute('aria-expanded', _isOpen ? 'true' : 'false');
    btn.classList.toggle('is-open', _isOpen);
    var caret = document.getElementById('cosRunningCaret');
    if (caret) caret.textContent = _isOpen ? '\u25B4' : '\u25BE';
    if (panel) panel.hidden = !_isOpen;
    if (!payload || typeof payload !== 'object') return;

    var cntEl = document.getElementById('cosRunningCount');
    var dotEl = document.getElementById('cosRunningDot');
    var isUnknown = payload.state === 'unknown';
    var count = typeof payload.count === 'number' ? payload.count : 0;
    btn.classList.toggle('is-unknown', isUnknown);
    btn.classList.toggle('is-running', !isUnknown && count > 0);
    if (cntEl) cntEl.textContent = isUnknown ? '!' : String(count);
    if (dotEl) dotEl.textContent = isUnknown ? '\u26A0' : (count > 0 ? '\uD83D\uDFE2' : '\u26AA');
  }

  function _appendGroup(panel, label, rows, skyTone) {
    if (!rows.length) return;
    panel.appendChild(_el('div', 'cos-proc-group' + (skyTone ? ' is-cockpit' : ''), label));
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      var rowEl = _el('div', 'cos-proc-row');
      rowEl.setAttribute('data-proc-id', String(r.id || ('row-' + i)));
      rowEl.setAttribute('data-timing-class', String(r.timing_class || ''));

      var titleWrap = _el('div', 'cos-proc-title');
      titleWrap.appendChild(_el('span', 'cos-proc-dot'));
      titleWrap.appendChild(_el('span', 'cos-proc-title-txt', r.title || 'Active Task'));
      rowEl.appendChild(titleWrap);
      rowEl.appendChild(_el('div', 'cos-proc-desc', r.description || ''));

      var etaWrap = _el('div', 'cos-proc-eta');
      etaWrap.appendChild(_el('span', 'cos-proc-elapsed', r.elapsed_text || 'Elapsed 0m 00s'));
      var pillCls = 'cos-proc-pill' + (r.timing_class === 'live_phase' ? ' is-live' : '');
      etaWrap.appendChild(_el('span', pillCls, r.eta_text || 'Running'));
      var href = String(r.cockpit_href || '');
      if (href.indexOf('/') === 0 && href.indexOf('//') !== 0) {
        var link = _el('a', 'cos-proc-link', '\u2197 Open Cockpit');
        link.setAttribute('href', href);
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener');
        etaWrap.appendChild(link);
      }
      rowEl.appendChild(etaWrap);
      panel.appendChild(rowEl);
    }
  }

  function renderPayload(payload) {
    _lastPayload = payload;
    _syncButtonChrome(payload);
    var panel = document.getElementById('cosProcessingPanel');
    if (!panel) return;
    while (panel.firstChild) panel.removeChild(panel.firstChild);

    var head = _el('div', 'cos-proc-head');
    head.appendChild(_el('strong', '', 'Active Work in Cave of Wonders & Delegated Cockpits'));
    head.appendChild(_el('span', '', 'Auto-updates every 5s \u00B7 Click Processing above to collapse'));
    panel.appendChild(head);

    if (!payload || payload.state === 'unknown' || payload.ok === false) {
      var unk = _el('div', 'cos-proc-unknown', (payload && (payload.message || payload.error)) || 'Processing backing store unreadable (unknown \u2014 not empty).');
      unk.setAttribute('data-proc-state', 'unknown');
      panel.appendChild(unk);
      return;
    }

    var rows = Array.isArray(payload.rows) ? payload.rows : [];
    if (payload.state === 'empty' || rows.length === 0) {
      var emp = _el('div', 'cos-proc-empty', payload.message || '0 Processing \u2014 no active Cave Steward turns, Scribe drafts, or delegated cockpit runs.');
      emp.setAttribute('data-proc-state', 'empty');
      panel.appendChild(emp);
      return;
    }

    var caveRows = rows.filter(function (x) { return x && x.group !== 'cockpit'; });
    var ckRows = rows.filter(function (x) { return x && x.group === 'cockpit'; });
    _appendGroup(panel, 'Cave of Wonders Steward (In-Flight Now)', caveRows, false);
    _appendGroup(panel, 'Delegated AI Cockpit Runs on Mothership (' + ckRows.length + ' Active)', ckRows, true);
  }

  function _readInitAttr() {
    var panel = document.getElementById('cosProcessingPanel');
    var raw = panel && panel.getAttribute('data-proc-init');
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (_e) { return null; }
  }

  function refresh() {
    if (_inFlight) return Promise.resolve(_lastPayload);
    _inFlight = true;
    return fetch('/api/high-seat/processing', {
      method: 'GET',
      headers: _authHeaders(),
      credentials: 'same-origin'
    })
      .then(function (resp) {
        return resp.json().catch(function () {
          return { ok: false, state: 'unknown', message: 'Malformed response from /api/high-seat/processing (HTTP ' + resp.status + ')' };
        }).then(function (data) {
          if (resp.status >= 500 || data.state === 'unknown') {
            data.state = 'unknown';
            data.ok = false;
          }
          renderPayload(data);
          return data;
        });
      })
      .catch(function () {
        var fallback = { ok: false, state: 'unknown', message: 'Unable to reach /api/high-seat/processing (unknown \u2014 not empty).' };
        renderPayload(fallback);
        return fallback;
      })
      .finally(function () {
        _inFlight = false;
      });
  }

  function _syncTimer() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_isOpen) {
      _pollTimer = setInterval(function () {
        if (document.visibilityState !== 'hidden' && _isOpen) refresh();
      }, 5000);
    }
  }

  function toggle(forceOpen) {
    _isOpen = typeof forceOpen === 'boolean' ? forceOpen : !_isOpen;
    if (!_lastPayload) {
      var initData = _readInitAttr();
      if (initData) _lastPayload = initData;
    }
    if (_lastPayload) renderPayload(_lastPayload);
    else _syncButtonChrome(null);
    _syncTimer();
    if (_isOpen) refresh();
  }

  function restoreAfterMorph(wasOpen) {
    _isOpen = !!wasOpen;
    var freshInit = _readInitAttr();
    if (freshInit) _lastPayload = freshInit;
    if (_lastPayload) renderPayload(_lastPayload);
    else _syncButtonChrome(null);
    _syncTimer();
  }

  var _bootInit = _readInitAttr();
  if (_bootInit) renderPayload(_bootInit);

  document.addEventListener('click', function (ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest('#cosRunningTile, [data-cos-toggle-processing]') : null;
    if (!btn) return;
    ev.preventDefault();
    toggle();
  });

  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && _isOpen) toggle(false);
  });

  window.CaveProcessingDrawer = {
    toggle: toggle,
    refresh: refresh,
    renderPayload: renderPayload,
    restoreAfterMorph: restoreAfterMorph,
    isOpen: function () { return _isOpen; }
  };
})();
