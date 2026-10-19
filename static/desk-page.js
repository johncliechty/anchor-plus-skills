// The Desk page (2026-10-06 + Wave 21 2026-10-19 polish): add / tick / promote a small item, start a cockpit,
// seat a cockpit in the Cave, filter items, manage Cross-Mothership collaborators, and run sub-20ms Desk Steward commands.
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
  function post(url, body, where, onDone) {
    if (busy) return; busy = true;
    fetch(url, { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 401 || r.status === 403) return { ok: false, error: 'not logged in - log in on the Cave first' }; return r.json(); })
      .then(function (j) {
        busy = false;
        if (!j || !j.ok) { say(where, (j && (j.error || j.receipt)) || 'Nothing was done.'); return; }
        if (onDone) { onDone(j); return; }
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

  // Wave 21: Filter buttons & Mark All Done
  var doneAllBtn = document.getElementById('btnDeskDoneAll');
  if (doneAllBtn) doneAllBtn.addEventListener('click', function () {
    post('/api/desk', { act: 'done_all' }, doneAllBtn);
  });
  document.querySelectorAll('[data-desk-filter]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var mode = btn.getAttribute('data-desk-filter');
      document.querySelectorAll('[data-desk-filter]').forEach(function (b) { b.classList.toggle('active', b === btn); });
      document.querySelectorAll('.ditem[data-waits], .dcard[data-waits]').forEach(function (el) {
        if (mode === 'waits') {
          el.style.display = el.getAttribute('data-waits') === '1' ? '' : 'none';
        } else {
          el.style.display = '';
        }
      });
    });
  });

  // Wave 21: Mothership Collaborator Drawer
  var msTog = document.getElementById('btnToggleMothershipDrawer');
  var msClose = document.getElementById('btnCloseMothershipDrawer');
  var msDrawer = document.getElementById('deskMothershipDrawer');
  if (msTog && msDrawer) {
    msTog.addEventListener('click', function () { msDrawer.hidden = !msDrawer.hidden; });
  }
  if (msClose && msDrawer) {
    msClose.addEventListener('click', function () { msDrawer.hidden = true; });
  }
  var peerForm = document.getElementById('deskPeerForm');
  if (peerForm) {
    peerForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var lbl = (document.getElementById('deskPeerLabel').value || '').trim();
      var ep = (document.getElementById('deskPeerEndpoint').value || '').trim();
      if (!lbl) return;
      post('/api/mothership/peers', { label: lbl, endpoint: ep || 'https://github.com/johncliechty/ghostworldlabs-anchor.git', transport: 'git_remote' }, peerForm);
    });
  }

  // Wave 21: Desk Steward Panel & Foundry Quick-Action Buttons
  var stForm = document.getElementById('deskStewardForm');
  var stInput = document.getElementById('deskStewardInput');
  var stFeed = document.getElementById('deskStewardFeed');
  function appendFeedMsg(who, text, isYou) {
    if (!stFeed) return;
    var d = document.createElement('div');
    d.className = 'ds-msg ' + (isYou ? 'you' : 'steward');
    var w = document.createElement('div');
    w.className = 'ds-who';
    w.textContent = who;
    var b = document.createElement('div');
    b.className = 'ds-body';
    b.textContent = text;
    d.appendChild(w);
    d.appendChild(b);
    stFeed.appendChild(d);
    stFeed.scrollTop = stFeed.scrollHeight;
  }
  function submitStewardText(txt) {
    var v = (txt || '').trim();
    if (!v) return;
    appendFeedMsg('You', v, true);
    if (stInput) stInput.value = '';
    post('/api/desk', { act: 'steward_say', text: v }, stForm, function (j) {
      appendFeedMsg('Aladdin · Desk Steward', j.say || j.receipt || 'Done.', false);
      if (j.mutated) {
        setTimeout(function () { location.reload(); }, 650);
      }
    });
  }
  if (stForm && stInput) {
    stForm.addEventListener('submit', function (e) {
      e.preventDefault();
      submitStewardText(stInput.value);
    });
    stInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitStewardText(stInput.value);
      }
    });
  }
  document.querySelectorAll('[data-desk-quick]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var q = btn.getAttribute('data-desk-quick') || '';
      if (q.endsWith(': ') || q.endsWith('for ')) {
        if (stInput) { stInput.value = q; stInput.focus(); }
      } else {
        submitStewardText(q);
      }
    });
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
