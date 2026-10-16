// The Desk page (2026-10-06): add / tick / promote a small item, start a cockpit, seat a cockpit in the Cave (the
// Campaign's own seat_new act) or send it back to the Desk (withdraw). Every act reloads the page with its receipt,
// the way the Cave does; a refusal is said where he clicked.
(function () {
  'use strict';
  var BOOT = window.ANCHOR_BOOT || {};
  function token() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
  function headers() {
    var h = { 'Content-Type': 'application/json' };
    var t = token(); if (t) { h['X-Anchor-Token'] = t; h['Authorization'] = 'Bearer ' + t; }
    if (BOOT.build_id) h['X-Anchor-Build'] = BOOT.build_id;
    return h;
  }
  var busy = false;
  function say(where, text) {
    var n = document.createElement('div');
    n.className = 'dempty'; n.setAttribute('role', 'status'); n.textContent = text;
    (where || document.querySelector('.desk-h')).insertAdjacentElement('afterend', n);
    setTimeout(function () { n.remove(); }, 6000);
  }
  function post(url, body, where) {
    if (busy) return; busy = true;
    fetch(url, { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 401 || r.status === 403) return { ok: false, error: 'not logged in - log in on the Cave first' }; return r.json(); })
      .then(function (j) {
        busy = false;
        if (!j || !j.ok) { say(where, (j && (j.error || j.receipt)) || 'Nothing was done.'); return; }
        location.reload();
      })
      .catch(function () { busy = false; say(where, 'That did not go through - nothing was done.'); });
  }
  var add = document.getElementById('deskAdd');
  if (add) add.addEventListener('submit', function (e) {
    e.preventDefault();
    var v = document.getElementById('deskAddText').value.trim();
    if (v) post('/api/desk', { act: 'add', text: v }, add);
  });
  var nw = document.getElementById('deskNew');
  if (nw) nw.addEventListener('submit', function (e) {
    e.preventDefault();
    var v = document.getElementById('deskNewName').value.trim();
    if (v) post('/api/desk', { act: 'new_cockpit', name: v }, nw);
  });
  document.addEventListener('change', function (e) {
    var cb = e.target.closest('.ddone');
    if (!cb) return;
    var li = cb.closest('[data-item]');
    post('/api/desk', { act: cb.checked ? 'done' : 'undone', item: li.getAttribute('data-item') }, li);
  });
  document.addEventListener('click', function (e) {
    var p = e.target.closest('.dpromote');
    if (p) { var li = p.closest('[data-item]'); post('/api/desk', { act: 'promote', item: li.getAttribute('data-item') }, li); return; }
    var s = e.target.closest('.dseatbtn');
    if (s) {
      var card = s.closest('[data-ref]');
      if (!BOOT.campaign_pid) { say(card, 'The Campaign is not stood up yet, so there is no Cave seat to take.'); return; }
      post('/api/high-seat/campaign', { pid: BOOT.campaign_pid, act: 'seat_new', ref: card.getAttribute('data-ref'),
        name: card.getAttribute('data-dir'), seat: s.getAttribute('data-seat') }, card);
      return;
    }
    var b = e.target.closest('.dback');
    if (b) {
      var c2 = b.closest('[data-ref]');
      post('/api/high-seat/campaign', { pid: BOOT.campaign_pid, act: 'withdraw', step: b.getAttribute('data-step') }, c2);
    }
  });
})();
