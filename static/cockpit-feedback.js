/* Shared read-only activity and attention for Cave initiatives and Anchor's cockpit tiles. */
(function () {
  'use strict';
  function identity(t) { return [t.pid, t.dir || '', t.general || '', t.term || ''].join('|'); }
  function review(map, delivery) {
    return ((delivery && delivery.items) || []).some(function (it) {
      if (!it.is_current || it.accepted || it.accepted_current) return false;
      if (it.managed) return it.phase === 'awaiting_review';
      var owner = ((map && map.steps) || []).find(function (s) { return s.id === it.owner_step_id; });
      if (!owner || owner.status === 'done' || owner.status === 'parked' || (owner.refinement || {}).phase === 'done') return false;
      // Managed products have their own current revisions above. Old register labels
      // on that owner cannot turn an ordinary work copy into a new review request.
      if ((owner.refinement || {}).phase) return false;
      var nav = owner.navigation || {}, label = String(nav.label || '');
      if (nav.current === false || nav.role === 'support') return false;
      return /^(?:START\s+HERE\s*[:\u2014\u2013-]\s*)?FOR\s+REVIEW\s*(?:[:\u2014\u2013-]|$)/i.test(String(it.what || ''))
        || (!/\b(?:not|no longer)\b/i.test(label) && /\b(?:for (?:author |your )?review|awaiting (?:author |your )?review|ready for (?:author |your )?review)\s*$/i.test(label));
    });
  }
  // John (2026-10-15): working status is always a green light across AI Cockpit, Cave of Wonders, and App Header Strip
  function color(light, ready) { return light === 'red' ? 'red' : light === 'green' ? 'green' : ready ? 'orange' : 'gray'; }
  function get(url, headers) {
    var controller = new AbortController(), timer = setTimeout(function () { controller.abort(); }, 12000);
    return fetch(url, { cache: 'no-store', signal: controller.signal, headers: headers || {} })
      .then(function (r) { if (!r.ok) throw new Error('feedback unavailable'); return r.json(); })
      .finally(function () { clearTimeout(timer); });
  }
  function read(target, old, headers, early) {
    var key = identity(target), q = '?pid=' + encodeURIComponent(target.pid) + '&dir=' + encodeURIComponent(target.dir || '');
    if (target.general) q += '&general=1&term=' + encodeURIComponent(target.term || '1');
    return get('/api/steward/state' + q, headers).then(function (st) {
      if (!st || !/^(green|orange|red|quiet|gray)$/.test(st.light) || typeof st.busy !== 'boolean') throw new Error('incomplete feedback');
      var question = !!st.open_question || !!((st.pending_questions || []).length) || st.light === 'orange';   // W4 (2026-10-05): one rule - the light is orange exactly when something waits on him
      if (early) early(st, question);
      var stamp = String(st.stamp || ''), cached = old && old.identity === key && old.stamp === stamp && Date.now() < old.until;
      var record = cached ? Promise.resolve(old) : target.general ? Promise.resolve({identity:key,stamp:stamp,until:Date.now()+15000,review:false})
        : Promise.all([get('/api/steward/map' + q, headers), get('/api/steward/deliverables' + q, headers)]).then(function (data) {
          if (!Array.isArray(data[0].steps) || !Array.isArray(data[1].items)) throw new Error('incomplete review record');
          return {identity:key,stamp:stamp,until:String(data[0].stamp || '')===stamp?Date.now()+15000:0,review:review(data[0],data[1])};
        });
      return record.then(function (rec) {
        return {state:st,record:rec,ready:question || rec.review,reason:question?'needs your answer':rec.review?'review waiting':''};
      }).catch(function () { return {state:st,record:null,ready:question?true:null,reason:question?'needs your answer':''}; });
    });
  }
  window.AnchorCockpitFeedback = {identity:identity, review:review, color:color, read:read};
})();
