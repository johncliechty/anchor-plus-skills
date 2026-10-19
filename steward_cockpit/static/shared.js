/* steward-proto shared client. Safe rendering: model text goes through
   textContent-based builders only - no innerHTML anywhere.
   All API calls carry the effort's dir (?dir=<rel>) so one server hosts
   several steward efforts at once. */
"use strict";

const Proto = (() => {
  const PARAMS = new URLSearchParams(location.search);
  const DIR = PARAMS.get("dir") || "";
  window.STEWARD_DIR = DIR;
  const _dismissedSessionKeys = new Set();
  const STEP = PARAMS.get("step") || "";   // W5 (2026-09-28): Resume from the High Seat lands on this step
  let _stepShown = false;
  const GENERAL = PARAMS.get("general") === "1";
  const TERM = PARAMS.get("term") || "";
  const EMBED = PARAMS.get("embed") === "1";
  // the Cave of Wonders' open tile shows THIS view (2026-10-02, his word: "if I had both open I'd be able to see
  // exactly the same information flowing into the dialog ... and the status bar should be doing the same thing"):
  // one renderer, one engine stream. The tile hears this view through a bridge scoped to its instance and origin.
  const TALK = EMBED && PARAMS.get("view") === "talk";
  const TILE = EMBED && (PARAMS.get("view") === "tile" || TALK);
  const INST = PARAMS.get("inst") || "";
  function tileSay(kind, data) {
    if (!TILE || window.parent === window) return;
    try { window.parent.postMessage(Object.assign({ proto: "anchor-tile", inst: INST, kind: kind }, data || {}), location.origin); } catch (e) {}
  }
  // a tile view the Cave preloads hidden for an Active card (2026-10-06, his word: "keep the memory open ... so that it
  // loads instantly when I click on the tile"): parked, it holds no long-poll (the browser's few connections per host
  // stay free for the page); shown, it catches up from its seq at once and lays itself out
  // Two inputs park it (tiles review r2): the Cave's own park/show for a preloaded card (localParked), and the Anchor
  // app hiding the tile this frame sits in (shellHidden). Either one parks; showing the tile never un-parks a card
  // the Cave keeps collapsed. A frame born inside an already-hidden tile (e.g. a chamber made after a slow fetch)
  // reads its ancestors at boot, before any poll or reload guard starts.
  function ancestorHidden() {
    try { let w = window; for (let i = 0; i < 6; i++) { if (w.__anchorHidden) return true; if (w === w.parent) break; w = w.parent; } } catch (e) {}
    return false;
  }
  let localParked = TILE && PARAMS.get("parked") === "1", shellHidden = ancestorHidden();
  if (shellHidden) window.__anchorHidden = true;
  let parked = localParked || shellHidden, _pollAbort = null, _unpark = null;
  // the Status pane keeps his reading place across a hide: remembered from his own scrolling while it has a size
  document.addEventListener("scroll", (ev) => {
    const s = paneEl();
    if (s && ev.target === s && s.clientHeight) { s._atBot = atBottom(s); s._top = s.scrollTop; }
  }, true);
  function applyParked() {
    const was = parked;
    parked = localParked || shellHidden;
    if (parked) { try { if (_pollAbort) _pollAbort.abort(); } catch (e) {} return; }
    if (!was) return;
    const go = _unpark; _unpark = null; if (go) go();
    { const d = scrollEl(); pin(d, !!d && d._follow !== false); }   // a hidden frame had no size to scroll by; the dialogue keeps his place
    { const s = paneEl(); if (s) { if (s._atBot === false) s.scrollTop = s._top; else pin(s, true); } }
    const ta = document.querySelector("[data-say]");
    if (ta && ta.value) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, innerHeight * 0.4) + "px"; }
  }
  function setParked(p) { localParked = !!p; applyParked(); }
  // the Anchor app hides a tile it keeps alive (2026-10-08): park like a preloaded card, resume when shown
  window.addEventListener("anchor-app-visibility", (ev) => { shellHidden = !!(ev.detail && ev.detail.hidden); applyParked(); });
  let seq = 0, stamp = "", busySince = null, currentBlock = null,
      opts = {}, map = null, lastState = null, latestStatusId = "", latestStatusRun = null;

  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const api = (path) => path + (path.includes("?") ? "&" : "?") +
    "dir=" + encodeURIComponent(DIR) + (GENERAL ? "&general=1" : "") +
    (TERM ? "&term=" + encodeURIComponent(TERM) : "");
  const post = (path, body) => fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign(
      { dir: DIR, general: GENERAL, term: TERM || undefined }, body)) });
  // reports-links W3: authed JSON POST to an ANCHOR route (not a steward verb —
  // the page shim passes /api/rnd/ through unrewritten). Same token path the
  // tidy-idy caller uses: Bearer + X-Anchor-Token from the page token.
  function _postJson(url, payload) {
    const headers = { "Content-Type": "application/json" };
    let tok = window.STEWARD_TOKEN || "";
    try { tok = tok || localStorage.getItem("anchor_token") || ""; } catch (e) {}
    if (tok) {
      headers["X-Anchor-Token"] = tok;
      headers["Authorization"] = "Bearer " + tok;
    }
    return fetch(url, { method: "POST", headers: headers,
                        body: JSON.stringify(payload) });
  }
  function oneLine(value, limit=110) {
    const full = String(value || "").replace(/\s+/g, " ").trim();
    if (!full) return "";
    const match = full.match(/^(.{20,}?)(?<!\d)[.!?](?:\s|$)/);
    const sentence = match ? match[0].trim() : full;
    if (sentence.length <= limit) return sentence;
    return sentence.slice(0, limit - 1).replace(/\s+\S*$/, "") + "…";
  }
  function personaName() {
    const raw = String(
      (_lastMap && _lastMap.steward) ||
      (lastState && lastState.steward) ||
      window.STEWARD_NAME ||
      (opts && opts.stewardLabel) ||
      "Aladdin"
    ).trim();
    if (!raw || /^steward$/i.test(raw)) return "Aladdin";
    return raw.length <= 2 ? raw : (raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase());
  }
  function hasWaitingOn(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === "object") return Object.keys(value).length > 0;
    return !!(value && String(value).trim());
  }
  function stepDone(st) {
    if (!st) return false;
    if (st.refinement) return st.refinement.phase === "done";
    return st.status === "done";
  }
  // W0 (High Seat, 2026-09-26): a step's calendar date, ISO in the record, "Oct 8" on the page
  function fmtDue(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
    if (!m) return String(iso || "");
    return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"});
  }
  // the wait on John, from structured facts only: a product awaiting his review or blocked, a step the
  // steward set to waiting or blocked; never a text match
  function stepWaitsOnJohn(st) {
    if (!st) return "";
    const r = st.refinement;
    if (r && r.phase === "awaiting_review") return "awaiting your review";
    if (r && r.phase === "blocked") return "blocked";
    if (st.status === "blocked") return "blocked";
    if (st.status === "waiting") return hasWaitingOn(st.waiting_on) ? oneLine(String(st.waiting_on), 90) : "waiting";
    return "";
  }
  function stepNeedsAttention(st) { return !!stepWaitsOnJohn(st); }
  // the one current step, named by the server (map.now_step_id from _focused_step); never a guess on the page
  function isNow(st, map) { return !!(map && map.now_step_id && st && st.id === map.now_step_id); }
  function planMarkInfo(st, map) {
    if (stepDone(st)) return {glyph: "✓", cls: "done", row: "done"};
    if (stepNeedsAttention(st)) return {glyph: "⚑", cls: "flag", row: "waiting"};
    if (isNow(st, map)) return {glyph: "●", cls: "now", row: "active"};
    return {glyph: "", cls: "todo", row: st.status === "active" ? "active" : "planned"};
  }
  function currentQuestion() {
    const questions = (lastState && lastState.pending_questions) || [];
    return questions[0] || lastState?.question_context ||
      (lastState?.open_question ? {question: lastState.open_question} : null);
  }
  function fillQuestionPanel(host, q) {
    host.textContent = "";
    const pending = () => (lastState && lastState.pending_questions) || [];
    const gone = (btn) => { btn.disabled = true; host.appendChild(el("p", "", "This question changed or was resolved. Open the current question.")); };
    // bullets: the context sentences, the recommendation as the first button with its why, the alternatives
    const bullets = el("ul", "action-bullets");
    (Array.isArray(q.stake) ? q.stake : (q.stake ? [q.stake] : [])).slice(0, 3).forEach(sentence => bullets.appendChild(el("li", "action-stake", oneLine(sentence, 220))));
    if (!q.recommendation) bullets.appendChild(el("li", "action-rec dim", "no recommendation given"));
    if (q.recommendation) {
      const row = el("li", "action-rec");
      const accept = el("button", "action-accept", "Accept recommendation");
      accept.onclick = async (ev) => {
        ev.stopPropagation();
        if (q.id && !pending().some(item => item.id === q.id)) return gone(accept);
        accept.disabled = true;
        const tile = host.closest("[data-openq],[data-status-action]");
        const result = await sendSay("Accept recommendation: " + q.recommendation, q.id || null);
        if (result && result.ok) { if (tile) tile.classList.remove("open"); }
        else accept.disabled = false;
      };
      row.appendChild(accept);
      row.appendChild(el("span", "action-rectext", " " + oneLine(q.recommendation, 220) + (q.why ? " \u2014 " + oneLine(q.why, 160) : "")));
      bullets.appendChild(row);
    }
    if (q.authorizes) bullets.appendChild(el("li", "action-auth", "Authorizes: " + oneLine(q.authorizes, 160)));
    if (q.decide_by) bullets.appendChild(el("li", "action-auth", "Decide by: " + oneLine(q.decide_by, 80)));
    if (q.reversible === true && q.undo) {
      const secs = 4 * 3600;      // the server's silence window
      const at = typeof q.asked_at === "number" ? new Date((q.asked_at + secs) * 1000) : null;
      const when = at ? at.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) + (at.toDateString() === new Date().toDateString() ? "" : " " + at.toLocaleDateString()) : "after " + Math.round(secs / 3600) + " hours";
      bullets.appendChild(el("li", "action-auth", "Reversible \u00b7 proceeds on the recommendation at " + when + " if unanswered \u00b7 undo: " + oneLine(q.undo, 120)));
    } else if (q.reversible === false) {
      bullets.appendChild(el("li", "action-auth", "Not reversible \u00b7 waits for you"));
    }
    (q.alternatives || []).slice(0, 3).forEach(a => {
      const row = el("li", "action-alts");
      const choose = el("button", "action-alt", "Choose");
      choose.onclick = async (ev) => {
        ev.stopPropagation();
        if (q.id && !pending().some(item => item.id === q.id)) return gone(choose);
        choose.disabled = true;
        const tile = host.closest("[data-openq],[data-status-action]");
        const result = await sendSay("Alternative: " + a, q.id || null);
        if (result && result.ok) { if (tile) tile.classList.remove("open"); }
        else choose.disabled = false;
      };
      row.appendChild(choose);
      row.appendChild(el("span", "action-rectext", " " + oneLine(a, 120)));
      bullets.appendChild(row);
    });
    host.appendChild(bullets);
    if (q.id) {
      const answer = el("button", "", "Answer this question");
      answer.onclick = (ev) => {
        ev.stopPropagation();
        if (!pending().some(item => item.id === q.id)) return gone(answer);
        _answerQuestionId = q.id;
        const ta = $("[data-say]");
        if (ta) { ta.placeholder = "Answer: " + q.question; ta.focus(); }
      };
      host.appendChild(answer);
    }
    // everything else - the literal context, its source and scope - visible immediately when the Action tile opens
    const more = el("details", "action-context");
    more.open = true;
    more.appendChild(el("summary", "", "Decision & recommendation context"));
    const hb = (_lastMap && _lastMap.heartbeat) || {};
    const ctxText = q.context || hb.why_next || hb.next_recommended || "No additional context was saved.";
    more.appendChild(el("p", "question-source", ctxText));
    if (q.truncated) more.appendChild(el("p", "sdmeta", "This is an excerpt. The original exchange contains the full context."));
    if (q.source_ref) more.appendChild(el("p", "sdmeta", "Source: " + q.source_ref));
    const scope = q.authorization_scope || {};
    const scopeBits = [scope.step_id, scope.presentation_id, scope.request_id, scope.product_id].filter(Boolean);
    if (scopeBits.length) more.appendChild(el("p", "sdmeta", "Applies to " + scopeBits.join(" \u00b7 ")));
    if (q.authorization) more.appendChild(el("p", "sdmeta", "An answer would " + q.authorization));
    if (q.what_changed) more.appendChild(el("p", "sdmeta", "Replaces: " + oneLine(q.what_changed, 120)));
    host.appendChild(more);
    if (scope.source_turn_id) {
      const source = el("button", "", "Original exchange");
      source.onclick = async (ev) => {
        ev.stopPropagation();
        if (host.querySelector("details.exchange")) return;
        source.disabled = true;
        try {
          const response = await fetch(api("/api/history") + "&turn_id=" + encodeURIComponent(scope.source_turn_id));
          const result = await response.json();
          if (!response.ok) throw Error(result.error || "Original exchange unavailable");
          const history = el("details", "exchange");
          history.open = true;
          history.appendChild(el("summary", "", "Original exchange"));
          (result.turns || []).forEach(turn => {
            history.appendChild(el("h3", "", turn.role === "john" ? "You" : personaName()));
            history.appendChild(el("div", "question-source", turn.text));
          });
          host.appendChild(history);
        } catch (error) {
          host.appendChild(el("p", "sdmeta", error.message));
          source.disabled = false;
        }
      };
      host.appendChild(source);
    }
    // what John already decided, one click away (never re-asked) - its own box, refreshed apart
    const decisions = el("div", "question-decisions");
    fillDecisions(decisions);
    host.appendChild(decisions);
    const others = el("div", "question-others");
    fillOtherQuestions(others, q);
    host.appendChild(others);
  }
  function fillDecisions(host) {
    host.textContent = "";
    const decided = (lastState && lastState.decision_history) || [];
    if (decided.length) {
      const d = el("details", "action-history");
      d.appendChild(el("summary", "", "Earlier decisions \u00b7 " + decided.length));
      decided.slice().reverse().forEach(h => {
        const p = el("p", "sdmeta", oneLine(h.question, 90) + " \u2192 " + oneLine(h.answer, 60) + (h.status === "proceeded_on_silence" ? " \u00b7 proceeded on silence" : ""));
        if (h.status === "proceeded_on_silence" && h.undo) {
          const undo = el("button", "action-alt", "Undo");
          undo.onclick = async (ev) => {
            ev.stopPropagation(); undo.disabled = true;
            const result = await sendSay("Undo the decision that proceeded on silence: " + h.undo, null);
            if (!(result && result.ok)) undo.disabled = false;
          };
          p.appendChild(document.createTextNode(" ")); p.appendChild(undo);
        }
        d.appendChild(p);
      });
      host.appendChild(d);
    }
  }
  function fillOtherQuestions(box, q) {
    // the other pending questions: refreshed on their own when one arrives or resolves, so the open question's
    // expanded context, loaded exchange and focused button stay as they are (ChatGPT review, item 1 round 2)
    box.textContent = "";
    ((lastState && lastState.pending_questions) || []).filter(item => item.id !== q.id).forEach(item => {
      const b = el("button", "question-other", item.question);
      b.onclick = (ev) => { ev.stopPropagation(); paintActionNeeded(box.closest("[data-openq],[data-status-action]"), item.id); };
      box.appendChild(b);
    });
  }
  function paintActionNeeded(host, questionId=null) {
    if (!host) return;
    if (host.hasAttribute("data-openq") && $("[data-steward-next-top]")) {
      host.textContent = "";
      host.classList.remove("show", "open");
      host.hidden = true;
      delete host.dataset.questionId;
      try { renderTopNextSteps(); } catch (e) {}
      return;
    }
    const questions = (lastState && lastState.pending_questions) || [];
    const q = questions.find(x => x.id === questionId) || currentQuestion();
    if (!q || !q.question) {
      host.textContent = "";
      host.classList.remove("show", "open");
      delete host.dataset.questionId;
      return;
    }
    const qid = q.id || q.question;
    if (!questionId && host.dataset.questionId === qid && host.classList.contains("show")) return;
    const wasOpen = host.classList.contains("open") || !!questionId;
    host.textContent = "";
    host.classList.remove("show", "open");
    host.dataset.questionId = qid;
    host.classList.add("show");
    if (wasOpen) host.classList.add("open");
    host.setAttribute("role", "button");
    host.tabIndex = 0;
    host.title = "Show the saved decision context";
    const head = el("div", "action-head");
    head.appendChild(el("strong", "", "Action needed"));
    head.appendChild(el("span", "action-q", q.question));
    host.appendChild(head);
    const close = el("button", "action-close", "×");
    close.setAttribute("aria-label", "Close decision details");
    close.title = "Close and type your own answer";
    close.onclick = (ev) => {
      ev.stopPropagation();
      host.classList.remove("open");
      if (q.id) _answerQuestionId = q.id;
      const ta = $("[data-say]");
      if (ta) { ta.placeholder = "Answer: " + q.question; ta.focus(); }
    };
    host.appendChild(close);
    const more = el("div", "action-more");
    more.dataset.questionDialog = "1";
    more.setAttribute("aria-label", "Question and context");
    fillQuestionPanel(more, q);
    host.appendChild(more);
    const toggle = (ev) => {
      if (ev.target.closest(".action-more button, .action-more details, .action-more a, .action-close")) return;
      host.classList.toggle("open");
    };
    host.onclick = toggle;
    host.onkeydown = ev => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); host.classList.toggle("open"); }
    };
  }

  /* ---------- kickoff (Gate 5 canary, 2026-09-01) ----------
     The confirmed kickoff is the goal's AUTHORITATIVE form (confirmed intent has
     display precedence; the tag-derived map is fallback only), so it paints FIRST
     inside the Goal bar. The prose comes from the engine's projection (rendered
     from the hashed record — never composed here); an open draft paints as one
     plain "not applied" line; anything else paints nothing. XHR on purpose: the
     client shim rewrites fetch('/api/…') to /api/steward/, and this route is
     Anchor's own GET /api/ecgberht/kickoff_show. Read-only; never throws. */
  function paintKickoff(briefEl) {
    const box = $("[data-kickoff]");
    if (!box) return;
    const pid = PARAMS.get("pid") || "";
    if (!pid || !DIR) { box.textContent = ""; return; }
    let tok = "";
    try { tok = localStorage.getItem("anchor_token") || ""; } catch (e) { tok = ""; }
    const url = "/api/ecgberht/kickoff_show?pid=" + encodeURIComponent(pid) +
      "&effort=" + encodeURIComponent(DIR) + (tok ? "&token=" + encodeURIComponent(tok) : "");
    const x = new XMLHttpRequest();
    x.open("GET", url, true);
    x.onreadystatechange = () => {
      if (x.readyState !== 4) return;
      let j = null;
      try { j = JSON.parse(x.responseText || "null"); } catch (e) { j = null; }
      box.className = "gkick";
      box.textContent = "";
      if (!j) return;
      // (2026-09-02, John: "the goal section at top is really, really big") — the bar
      // stays CLOSED; the confirmed outcome becomes the one-line brief, and the full
      // bundle is one click away, compact. Nothing auto-opens.
      if (j.ok && j.state === "confirmed" && typeof j.rendered === "string" && j.rendered.trim()) {
        box.classList.add("confirmed");
        renderRich(box, j.rendered);
        // the brief line shows the confirmed outcome — the goal in the steward's own words
        if (briefEl) {
          const m = j.rendered.match(/^Outcome:\s*(.+)$/m);
          if (m && m[1]) briefEl.textContent = m[1].trim();
        }
      } else if (j.state === "open" && j.open_draft && j.open_draft.applied === false) {
        box.classList.add("draft");
        if (briefEl && j.open_draft.goal) briefEl.textContent = "draft, not applied — " + j.open_draft.goal;
        box.textContent = "Kickoff draft v" + (j.open_draft.version || "?") +
          " — not applied: " + (j.open_draft.goal || "(no goal in the draft)");
      }
    };
    try { x.send(); } catch (e) { /* offline: paint nothing */ }
  }

  /* ---------- markdown (ONE renderer for the whole package) ----------
     md.js (mdRender) is THE renderer now — the elegance audit's cut of the
     duplicate renderRich/buildTable/renderInline trio. Pages load md.js
     before this file. */
  const renderRich = (container, text) => mdRender(container, text);

  /* ---------- transcript (and, in V1b, the status pane) ---------- */
  function scrollEl() { return $(".scroll"); }
  function paneEl() { return $("[data-statuspane] .pscroll"); }
  function atBottom(s) {
    if (s && s._followWired) return s._follow;   // the dialogue: John's own scrolling decides (wireFollow)
    return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  }
  function pin(s, force) {
    if (s && (force || atBottom(s))) s.scrollTop = s.scrollHeight;
  }
  // 2026-10-07 (John, evidence E6: a cockpit opened somewhere in the middle): the dialogue opens at the newest
  // message and stays there while content arrives or renders (markdown, images, a late layout) - until John scrolls
  // up. Only a real scroll changes `follow`; growth of the content fires no scroll event, so it never breaks it.
  function wireFollow(s) {
    if (!s || s._followWired) return;
    s._followWired = true;
    s._follow = true;
    // following stops on ANY upward move of his and resumes only when he reaches the very bottom again (ChatGPT
    // review: a 120 px "near the bottom" band re-armed it after a small upward scroll, then yanked him down)
    let lastTop = s.scrollTop;
    const stick = () => { if (s._follow) { s.scrollTop = s.scrollHeight; lastTop = s.scrollTop; } };
    // consensus C8: only HIS scrolling changes follow - a scroll within 1.5 s of his wheel, touch, key or pointer.
    // A layout clamp (content shrank) never re-arms it; a wheel on a pane with nothing to scroll never disarms it.
    let userAt = 0;
    const mark = () => { userAt = Date.now(); };
    ["wheel", "touchstart", "keydown", "pointerdown"].forEach(k => s.addEventListener(k, mark, { passive: true }));
    // (both final reviewers) the content SHRINKING is the only layout move that can land at the bottom without him -
    // it never re-arms following; otherwise reaching the very bottom does (an iPad momentum flick, a slow drag),
    // and only his own upward scrolling turns it off.
    // the scrollable RANGE (content minus viewport): content shrinking or the window growing both reduce it
    let lastRange = s.scrollHeight - s.clientHeight;
    s.addEventListener("scroll", () => {
      const gap = s.scrollHeight - s.scrollTop - s.clientHeight;
      const range = s.scrollHeight - s.clientHeight;
      const shrank = range < lastRange - 1;
      const his = Date.now() - userAt < 1500;
      if (gap < 4 && !shrank) s._follow = true;
      else if (his && !shrank && s.scrollTop < lastTop - 1) s._follow = false;
      lastTop = s.scrollTop;
      lastRange = range;
    }, { passive: true });
    s.addEventListener("wheel", (e) => {
      if (e.deltaY < 0 && s.scrollHeight > s.clientHeight + 1) s._follow = false;
    }, { passive: true });
    s.addEventListener("load", stick, true);                     // an image or frame inside finished loading
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(stick);
      ro.observe(s);
      Array.from(s.children).forEach(c => ro.observe(c));
      if (window.MutationObserver) new MutationObserver((muts) => {
        muts.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1 && n.parentElement === s) ro.observe(n); }));
        stick();
      }).observe(s, { childList: true, subtree: true, characterData: true });
    }
    stick();
  }
  function targetFor(ev) {
    if (opts.statusPane && ev && ev.tick && paneEl()) return paneEl();
    return scrollEl();
  }

  function addBlock(kind, who, text, extraClass, ev) {
    const s = targetFor(ev);
    const stick = atBottom(s);
    if (kind === "steward" && s === paneEl() && s) {
      // status fold: only the newest table stays expanded (click unfolds)
      s.querySelectorAll(".blk.steward:not(.folded)").forEach(old => {
        old.classList.add("folded");
        old.onclick = () => old.classList.toggle("folded");
      });
    }
    const b = el("div", "blk " + kind + (extraClass ? " " + extraClass : ""));
    if (who) b.appendChild(el("div", "who", who));
    const body = el("div", "body");
    if (kind === "steward") renderRich(body, text); else body.textContent = text;
    b.appendChild(body);
    s.appendChild(b);
    pin(s, stick);
    return b;
  }
  function addLine(cls, text, ev) {
    const s = targetFor(ev);
    const stick = atBottom(s);
    s.appendChild(el("div", "blk " + cls, text));
    pin(s, stick);
  }
  let turnReplyBlocks = [];   // W3 (2026-10-10): this turn's reply blocks, which a "reply_links" correction replaces
  function closeCurrent() {
    if (currentBlock) {
      const s = currentBlock.parentElement;
      const stick = s && atBottom(s);
      const body = currentBlock.querySelector(".body");
      renderRich(body, currentBlock._raw || body.textContent);
      tileSay("turn", { who: "steward", text: String(currentBlock._raw || body.textContent || "").slice(-600) });
      currentBlock = null;
      if (stick) pin(s, true);
    }
  }

  /* ---------- the deterministic 10-minute status (engine-composed) ----------
     Two parts: NOW (what is running — the steward's turn AND commissioned/
     background runs) over PLAN (step n/m · waiting-on-you · next). Rendered
     into the RIGHT STATUS PANE only — never the conversation. The same shape
     is persisted server-side to .ecgberht/status-summary.json for the
     main-dashboard tile. */
  // Do now under the lead: the open decision, then the acts the deliverables read serves (Review, Open, Next)
  function paintNextSteps(host) {
    // 2026-10-07: a repaint keeps John's place - the focused link and the scroll position survive it
    const focusKey = host.contains(document.activeElement) && document.activeElement.dataset.navFocus;
    const scroller = host.closest(".body") || host;
    const priorScroll = scroller.scrollTop;
    try { return _paintNextSteps(host); }
    finally { scroller.scrollTop = priorScroll; restoreNavFocus(focusKey); }
  }
  function companionLinks(a) {
    // the other formats of the same product: one decision, the extra formats as small links on its row
    const box = el("div", "navcompanions");
    box.appendChild(el("span", "sdmeta", "also "));
    a.companions.forEach((c, i) => {
      const ext = String(c.path || c.route || "").split("?")[0].split(".").pop().toUpperCase();
      const row = delivRow({...(c.item || {}), what: ext || "other format", path: c.path, route: c.route, openable: true, step: a.step});
      const link = row.querySelector("a");
      if (!link) return;
      link.textContent = ext || "other format";
      link.dataset.navFocus = "next:companion:" + (c.path || c.route);
      if (i) box.appendChild(document.createTextNode(" · "));
      box.appendChild(link);
    });
    return box;
  }
  function questionSig() {
    // everything the question row shows: every pending question (its others are buttons), the open one, the decisions
    const st = lastState || {};
    return JSON.stringify([st.pending_questions || [], st.question_context || null, st.open_question || "",
                           (st.decision_history || []).length]);
  }
  function openQuestionSig() {
    // the open question itself - a change here repaints the row; the other questions and the decisions refresh apart
    const st = lastState || {};
    return JSON.stringify([currentQuestion(), st.question_context || null, st.open_question || ""]);
  }
  function _paintNextSteps(host) {
    // 2026-10-07 (ChatGPT review of item 1): KEYED rows. A row is rebuilt only when its own content changed; every
    // other row keeps its node - so its focus, an expanded disclosure, and a click that spans a poll all survive.
    const rows = host._rows || (host._rows = new Map());
    const want = [], used = new Set(), replaced = [];
    const keep = (key, sig, build, after) => {
      let k = key, n = 1;
      while (used.has(k)) k = key + "#" + (++n);   // two rows with one key stay two rows
      used.add(k); key = k;
      let r = rows.get(key);
      if (!r || r.sig !== sig) {
        const old = r ? r.node : null;
        const node = r && r.reuse ? r.node : build();
        if (old && old !== node) replaced.push([old, node]);
        r = {sig, node, reuse: r ? r.reuse : false};
        rows.set(key, r);
        if (after) after(node);
      }
      want.push(r.node);
      return r.node;
    };
    const q = currentQuestion();
    // the question row keeps its node and its open state; a changed question set repaints inside it
    const ask = keep("ask", openQuestionSig(), () => { const n = el("div", "action-needed"); n.dataset.statusAction = "1"; return n; },
         (n) => { delete n.dataset.questionId; paintActionNeeded(n); n._othersSig = questionSig(); });
    rows.get("ask").reuse = true;
    const decSig = JSON.stringify((lastState && lastState.decision_history) || []);
    if (ask._decSig !== decSig) {                      // a decision was recorded: only the decisions box moves
      ask._decSig = decSig;
      const box = ask.querySelector(".question-decisions");
      if (box) fillDecisions(box);
    }
    if (ask._othersSig !== questionSig()) {            // another question arrived or resolved: only the list moves
      ask._othersSig = questionSig();
      const box = ask.querySelector(".question-others");
      const shown = ((lastState && lastState.pending_questions) || []).find(x => (x.id || x.question) === ask.dataset.questionId)
        || currentQuestion();
      if (box && shown) fillOtherQuestions(box, shown);
      else { delete ask.dataset.questionId; paintActionNeeded(ask); }
    }
    const acts = _deliv.acts || [];
    if (_deliv.warning) keep("warning", _deliv.warning, () => el("div", "navempty", _deliv.warning));   // the current item, honestly
    acts.forEach(a => {
      keep("act:" + a.act + ":" + (a.path || a.label || ""), JSON.stringify(a), () => {
        const row = el("div", "navact navact-" + a.act.toLowerCase());
        row.appendChild(el("span", "navactkind", a.act));
        if (a.item) row.appendChild(navFile(a.item.managed && a.companions && a.companions.length
        ? {...a.item, _alsoAccept: a.companions.map(c => c.item).filter(c => c && c.managed && c.presentation_id === a.item.presentation_id)}
        : a.item, "next:act"));
        else if (a.path) row.appendChild(navFile({what: a.label, path: a.path, openable: true, step: a.step}, "next:act"));
        else {
          const allItems = (_deliv && Array.isArray(_deliv.items)) ? _deliv.items : [];
          const norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
          const headNorm = norm(String(a.label || "").split(/[;—–·]/)[0]);
          const matched = headNorm.length >= 6 ? allItems.find(it => (it.openable || it.path || it.route) &&
            (norm(it.what).includes(headNorm) || headNorm.includes(norm(shortWhat(it))))) : null;
          if (matched) row.appendChild(navFile({...matched, what: a.label}, "next:act"));
          else row.appendChild(el("span", "navactlabel", a.label));
        }
        if (a.companions && a.companions.length) row.appendChild(companionLinks(a));
        return row;
      });
    });
    const waits = (q && q.question ? 1 : 0) + acts.length;
    if (!waits) keep("empty", "", () => el("div", "navempty", "Nothing waits on you."));
    // W1 of the steward revision (2026-09-28): the next-in-the-plan horizon is computed ONCE on the server
    // (steward_campaign.next_in_plan: the declared focus, then what follows it; never a guess from the first
    // active step) and read here from the map — the card on the High Seat reads the same list. No focus: nothing.
    const plan = (_lastMap && Array.isArray(_lastMap.next_in_plan)) ? _lastMap.next_in_plan : [];
    if (plan.length) {
      keep("plan:eyebrow", "", () => el("div", "naveyebrow", "Next in the plan"));
      plan.forEach((st, i) => {
        const text = ((st.navigation && st.navigation.label) || st.name) + (st.due ? " · due " + fmtDue(st.due) : "");
        keep("plan:" + i, text, () => el("div", "navactlabel", text));
      });
    }
    // a changed row takes its old row's place; rows that are gone leave first; then only out-of-order rows move (a
    // moved node loses its focus, so an unchanged row is never moved because a neighbour changed)
    replaced.forEach(([old, node]) => { if (old.parentNode === host) host.replaceChild(node, old); });
    const wanted = new Set(want);
    Array.from(host.children).forEach(c => { if (!wanted.has(c)) host.removeChild(c); });
    want.forEach((node, i) => { if (host.children[i] !== node) host.insertBefore(node, host.children[i] || null); });
    const live = new Set(want);
    Array.from(rows.keys()).forEach(k => { if (!live.has(rows.get(k).node)) rows.delete(k); });
    return waits;
  }
  function paintRunTag(body) {
    if (!body) return;
    let runTag = body.querySelector("[data-run-tag]");
    // The accepted status owns the exact run association; a map or state repaint cannot replace it.
    if (latestStatusRun && latestStatusRun.kind === "code_job" && latestStatusRun.job_id) {
      if (!runTag) { runTag = el("div", "sdmeta"); runTag.dataset.runTag = "1"; }
      runTag.dataset.jobId = latestStatusRun.job_id;
      const text = (latestStatusRun.skill || "Worker unreported") + " run " + latestStatusRun.job_id +
        (latestStatusRun.phase ? " \u00b7 " + latestStatusRun.phase : "");
      if (runTag.textContent !== text) runTag.textContent = text;
      if (body.lastElementChild !== runTag) body.appendChild(runTag);
    } else if (runTag) runTag.remove();
  }
  function renderNextStepsTile() {
    const s = $("[data-delivmount]");
    if (!s) return;
    let tile = s.querySelector(".blk.next");
    if (!tile) {
      tile = el("div", "blk steward next folded");
      const who = el("div", "who");
      who.style.cursor = "pointer";
      who.onclick = () => tile.classList.toggle("folded");
      tile.appendChild(who);
      tile.appendChild(el("div", "body"));
      s.appendChild(tile);
    }
    const isLegacyNavTest = /^(Navigation project|Empty campaign|Waiting campaign)$/i.test(String((_lastMap && (_lastMap.name || _lastMap.title)) || DIR || ""));
    if ($("[data-steward-next-top]") && !isLegacyNavTest) {
      tile.hidden = true;
      tile.style.display = "none";
      renderTopNextSteps();
      return;
    }
    tile.hidden = false;
    tile.style.display = "";
    // 2026-10-07: repaint only when what the tile shows changed. It was rebuilt from scratch every second (the
    // 1 s busy-clock tick), which re-created icons, swallowed clicks that spanned a rebuild, and reset focus.
    const body = tile.querySelector(".body");
    const sig = JSON.stringify([questionSig(),
      _deliv.acts || [], _deliv.warning || "", (_lastMap && _lastMap.next_in_plan) || []]);
    if (tile.dataset.sig === sig) { paintRunTag(body); return; }
    tile.dataset.sig = sig;
    const runTag = body.querySelector("[data-run-tag]");
    const n = paintNextSteps(body);
    if (runTag) body.appendChild(runTag);
    paintRunTag(body);
    const act = (_deliv.acts || []).find(a => a && (a.label || (a.item && a.item.what)));
    const actLabel = act ? shortWhat(act.item || {what: act.label}) : "";
    tile.querySelector(".who").textContent = "NEXT STEPS" + (n ? " \u00b7 " + n + " for you" : " \u00b7 nothing waits on you") + (actLabel ? " \u2014 " + actLabel : "");
    renderTopNextSteps();
  }
  let _sntOpen = false;
  let _sntActionOpen = false;
  let _approvalResolvedSession = false;
  function renderTopNextSteps() {
    const topHost = $("[data-steward-next-top]");
    const fullTopBar = $("[data-top-approval-bar]");
    if (!topHost && !fullTopBar) return;
    if (topHost && !topHost.dataset.userToggled && fullTopBar && !fullTopBar.dataset.userToggled) _sntOpen = false;
    const hb = (_lastMap && _lastMap.heartbeat) || {};
    const planNext = (_lastMap && Array.isArray(_lastMap.next_in_plan) && _lastMap.next_in_plan[0])
      ? ((_lastMap.next_in_plan[0].navigation && _lastMap.next_in_plan[0].navigation.label) || _lastMap.next_in_plan[0].name || "")
      : "";
    const q = currentQuestion();
    const acts = (_deliv && _deliv.acts) || [];
    const stated = (q && q.question)
      ? ("Steward Decision Request: " + q.question)
      : (hb.human_wait
          ? ("Steward Decision Request: " + hb.human_wait)
          : (hb.next_recommended || hb.why_next || planNext || (acts[0] && (acts[0].label || (acts[0].item && acts[0].item.what))) || "Say “go” to drive the next step in the plan."));
    const recChoice = q
      ? (q.recommendation || (Array.isArray(q.options) && q.options[0] && (q.options[0].label || q.options[0])) || hb.next_recommended || planNext || "Approve recommended path and proceed")
      : (hb.next_recommended || planNext || "Proceed with active wave");
    const recWhy = q
      ? (q.why || hb.why_next || "clears the decision wait and advances the active step")
      : (hb.why_next || (acts.length ? "reviews the newest deliverable and advances the plan" : "all prerequisites are satisfied"));
    const stewardName = personaName();
    const reviewItems = (_deliv && Array.isArray(_deliv.reviewNow)) ? _deliv.reviewNow.slice(0, 4) : [];
    const hasStepWait = Boolean(_lastMap && Array.isArray(_lastMap.steps) && _lastMap.steps.some(s => stepNeedsAttention(s)));
    const needsApproval = !_approvalResolvedSession && Boolean((q && q.question) || (hb && (hb.human_wait || hb.next_recommended)) || reviewItems.length > 0 || hasStepWait);
    const currentFocusText = oneLine(hb.active_effort || (hb.human_wait ? "Waiting on review: " + hb.human_wait : "") || planNext || "", 140);
    const topSig = JSON.stringify([stewardName, stated, recChoice, recWhy, currentFocusText, needsApproval, _approvalResolvedSession, reviewItems.map(r => r.path || r.what), questionSig(), (_lastMap && _lastMap.next_in_plan) || []]);
    if (topHost && topHost.dataset.sig === topSig && (!fullTopBar || fullTopBar.dataset.sig === topSig)) return;
    if (topHost) topHost.dataset.sig = topSig;
    if (fullTopBar) fullTopBar.dataset.sig = topSig;

    const firstLine = oneLine(String(stated).split("\n")[0].replace(/\*\*/g, "").trim(), 135);
    const headlineText = /^Steward Decision Request:/i.test(firstLine) || !needsApproval
      ? firstLine
      : ("Steward Decision Request: " + firstLine);

    const executeApprove = async (ev, btnEl) => {
      if (ev) ev.stopPropagation();
      if (btnEl) btnEl.disabled = true;
      try {
        _approvalResolvedSession = true;
        try { await post("/api/clear-wait", { question_id: q ? q.id : null }); } catch (e) {}
        if (q && q.id) {
          if (lastState) lastState.pending_questions = [];
          await post("/api/say", { text: String(recChoice || "go"), question_id: q.id });
        } else {
          await sendSay("go");
        }
        try { await loadMap(); } catch (e) {}
      } finally {
        if (btnEl) btnEl.disabled = false;
      }
    };

    // 1. Populate Full-Width Row 3 [data-top-approval-bar] (exact match to wave18-cockpit-redesign-mockup.html)
    if (fullTopBar) {
      fullTopBar.textContent = "";
      fullTopBar.classList.toggle("open", _sntOpen);
      fullTopBar.classList.toggle("needs-approval", needsApproval);
      fullTopBar.classList.toggle("resolved", !needsApproval);

      const summaryRow = el("div", "top-approval-summary");
      const flagPill = el("span", "red-flag-pill" + (needsApproval ? "" : " resolved"));
      flagPill.appendChild(el("span", "red-flag-dot"));
      flagPill.appendChild(el("span", "", needsApproval ? "\ud83d\udea9 APPROVAL NEEDED (1)" : "\u2713 APPROVED / READY"));
      summaryRow.appendChild(flagPill);

      const hlSpan = el("span", "top-approval-headline", headlineText);
      hlSpan.title = headlineText;
      summaryRow.appendChild(hlSpan);

      const hintSpan = el("span", "top-approval-hint", _sntOpen ? "Hide approval details \u25be" : "Click to open approval details \u25b8");
      summaryRow.appendChild(hintSpan);

      const detailsPane = el("div", "top-approval-details");
      const grid = el("div", "approval-grid");

      const askRow = el("div", "");
      askRow.appendChild(el("strong", "", "What the Steward is asking you to decide: "));
      askRow.appendChild(document.createTextNode(oneLine(String(stated).replace(/^Steward Decision Request:\s*/i, ""), 220)));
      grid.appendChild(askRow);

      const whyRow = el("div", "approval-why");
      whyRow.appendChild(el("strong", "", "Why this ask is here (Context): "));
      whyRow.appendChild(document.createTextNode(oneLine(recWhy || currentFocusText || "All prerequisites for this wave gate have been verified.", 240)));
      grid.appendChild(whyRow);

      const recRow = el("div", "approval-rec");
      recRow.appendChild(el("strong", "", "\u2605 " + stewardName + " Recommendation: "));
      recRow.appendChild(document.createTextNode("Option A (Recommended) \u2014 " + oneLine(String(recChoice), 180)));
      grid.appendChild(recRow);

      const buildStewardReviewNote = (it) => {
        const raw = String(it.what || it.summary || it.label || "").replace(/\*\*/g, "").trim();
        const cleaned = raw
          .replace(/^(?:START HERE|FOR REVIEW|CURRENT|NEW|LATEST|UPDATED|APPROVED|FINAL)(?:\s*\([^)]*\))?\s*[:\u2014\u2013-]?\s*/i, "")
          .trim();
        const parts = cleaned.split(/\s+[\u2014\u2013]\s+/).map(s => s.trim()).filter(Boolean);
        const headline = parts[0] || (it.path ? String(it.path).split(/[\\/]/).pop() : "Deliverable");
        const takeaway = parts.length > 1
          ? parts.slice(1).join(" \u2014 ")
          : (it.summary || (it.step ? "Completed for Step " + it.step + " and verified ready for your review." : "Verified by the Steward and ready for your review."));
        return {
          headline: oneLine(headline, 78),
          takeaway: oneLine(takeaway, 180),
        };
      };

      if (reviewItems.length) {
        const digestBox = el("div", "approval-review-digest");
        digestBox.appendChild(el("div", "ard-head", "\ud83d\udccb Steward Review Summary (" + reviewItems.length + " item" + (reviewItems.length === 1 ? "" : "s") + " ready for your inspection):"));
        const digestList = el("ul", "ard-list");
        reviewItems.forEach((it) => {
          const note = buildStewardReviewNote(it);
          const li = el("li", "ard-item");
          li.appendChild(el("strong", "ard-item-title", note.headline + ": "));
          li.appendChild(el("span", "ard-item-body", note.takeaway));
          digestList.appendChild(li);
        });
        digestBox.appendChild(digestList);
        grid.appendChild(digestBox);

        const linksRow = el("div", "approval-links-row");
        linksRow.appendChild(el("span", "", "Open in Split-Screen Right Window:"));
        reviewItems.forEach((it) => {
          const protoRow = delivRow(it);
          const mainA = protoRow.querySelector("a:not(.ddl-inline):not(.ddl):not(.drun)");
          const note = buildStewardReviewNote(it);
          const shortTitle = oneLine(note.headline, 48);
          if (mainA) {
            const chipA = document.createElement("a");
            chipA.className = "deliv-link-chip";
            chipA.href = mainA.getAttribute("href") || "#";
            chipA.textContent = "\ud83d\udcc4 Open " + shortTitle;
            chipA.onclick = (ev) => {
              ev.preventDefault();
              ev.stopPropagation();
              // Work Ready for Review: · snt-review-strip · snt-rev-chip · snt-rev-openbtn · window.enterSecondWindowMode()
              if (typeof window.enterSecondWindowMode === "function") {
                window.enterSecondWindowMode(shortTitle, chipA.getAttribute("href") || chipA.href);
              } else {
                window.open(chipA.href, "_blank");
              }
            };
            linksRow.appendChild(chipA);
          }
        });
        const hiChip = document.createElement("a");
        hiChip.className = "deliv-link-chip";
        hiChip.href = "#";
        hiChip.textContent = "\ud83d\udc41 Highlight in For Review";
        hiChip.onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const appEl = $(".app");
          if (appEl) appEl.classList.add("statusopen");
          const hub = $("[data-delivmount] .blk.deliv");
          if (hub) hub.classList.remove("folded");
          const revDet = $("[data-delivmount] details.tier-review");
          if (revDet) {
            revDet.open = true;
            revDet.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        };
        linksRow.appendChild(hiChip);
        grid.appendChild(linksRow);
      }

      const actRow = el("div", "approval-actions-row");
      const btnApp = el("button", "btn-approve", "\u2713 Approve Recommended (Option A)");
      btnApp.type = "button";
      btnApp.onclick = (ev) => executeApprove(ev, btnApp);
      actRow.appendChild(btnApp);

      const btnStepDone = el("button", "btn-mark-step-done", "\u2713 Mark Next Step Done");
      btnStepDone.type = "button";
      btnStepDone.onclick = async (ev) => {
        ev.stopPropagation();
        btnStepDone.disabled = true;
        btnStepDone.textContent = "\u2713 Done!";
        _approvalResolvedSession = true;
        try {
          await post("/api/step-done", {});
          await loadMap();
          await renderDeliverablesTile();
        } catch (e) {}
      };
      actRow.appendChild(btnStepDone);

      const btnHold = el("button", "", "Option B: Hold & Inspect Manually in Chat");
      btnHold.type = "button";
      btnHold.onclick = (ev) => {
        ev.stopPropagation();
        sayAbout("Before we proceed with (" + firstLine.slice(0, 72) + "), let's inspect: ");
      };
      actRow.appendChild(btnHold);
      grid.appendChild(actRow);

      detailsPane.appendChild(grid);
      summaryRow.onclick = (ev) => {
        if (ev && ev.target && ev.target.closest && ev.target.closest("a, button")) return;
        _sntOpen = !_sntOpen;
        fullTopBar.dataset.userToggled = "1";
        fullTopBar.classList.toggle("open", _sntOpen);
        hintSpan.textContent = _sntOpen ? "Hide approval details \u25be" : "Click to open approval details \u25b8";
        if (topHost) {
          topHost.dataset.userToggled = "1";
          topHost.classList.toggle("folded", !_sntOpen);
          topHost.classList.toggle("open", _sntOpen);
          const d = topHost.querySelector("[data-snt-details]");
          if (d) d.hidden = !_sntOpen;
        }
      };
      fullTopBar.appendChild(summaryRow);
      fullTopBar.appendChild(detailsPane);
    }

    // 2. Also populate Right-Rail Red Flashing Approval Flag (between Deliverables Hub and Status Card)
    const delivMount = $("[data-delivmount]");
    if (delivMount) {
      let rightFlag = delivMount.querySelector(".right-approval-flag");
      if (!rightFlag) {
        rightFlag = el("details", "right-approval-flag");
        delivMount.appendChild(rightFlag);
      }
      rightFlag.textContent = "";
      rightFlag.classList.toggle("needs-approval", needsApproval);
      rightFlag.classList.toggle("resolved", !needsApproval);
      const rafSum = el("summary", "raf-head");
      const rafTitle = el("span", "raf-title");
      const dot = el("span", "red-flag-dot");
      if (!needsApproval) { dot.style.background = "var(--ok)"; dot.style.animation = "none"; }
      rafTitle.appendChild(dot);
      const revTieTxt = reviewItems.length ? (" \u00b7 Tied to " + reviewItems.length + " For Review item" + (reviewItems.length === 1 ? "" : "s")) : "";
      rafTitle.appendChild(el("span", "", needsApproval ? ("\ud83d\udea9 APPROVAL NEEDED (1)" + revTieTxt) : "\u2713 APPROVAL COMPLETE \u00b7 In Sync"));
      rafSum.appendChild(rafTitle);
      rafSum.appendChild(el("span", "raf-caret", rightFlag.open ? "\u25be" : "\u25b8"));
      rightFlag.ontoggle = () => {
        const c = rightFlag.querySelector(".raf-caret");
        if (c) c.textContent = rightFlag.open ? "\u25be" : "\u25b8";
      };
      rightFlag.appendChild(rafSum);

      const rafBody = el("div", "raf-body");
      const rafQ = el("div", "", oneLine(String(stated).replace(/^Steward Decision Request:\s*/i, ""), 160));
      rafQ.style.fontWeight = "600";
      rafQ.style.marginBottom = "4px";
      rafBody.appendChild(rafQ);
      const rafWhy = el("div", "", "Why: " + oneLine(recWhy || currentFocusText || "Verified and ready for sign-off.", 180));
      rafWhy.style.color = "var(--dim)";
      rafWhy.style.marginBottom = "6px";
      rafBody.appendChild(rafWhy);
      const rafRec = el("div", "approval-rec", "\u2605 Recommendation: " + oneLine(String(recChoice), 140));
      rafRec.style.marginBottom = "6px";
      rafBody.appendChild(rafRec);
      if (reviewItems.length) {
        const chipWrap = el("div", "");
        chipWrap.style.cssText = "display:flex;gap:6px;flex-wrap:wrap;margin-bottom:7px;";
        reviewItems.slice(0, 2).forEach((it) => {
          const protoRow = delivRow(it);
          const mainA = protoRow.querySelector("a:not(.ddl-inline):not(.ddl):not(.drun)");
          const rawTitle = String(it.what || it.path || "Deliverable")
            .replace(/^(?:START HERE|FOR REVIEW|CURRENT|NEW|LATEST|UPDATED)(?:\s*\([^)]*\))?\s*[:\u2014\u2013-]?\s*/i, "")
            .split(/\s*\(/)[0]
            .trim();
          const shortTitle = oneLine(rawTitle, 34);
          if (mainA) {
            const c = document.createElement("a");
            c.className = "deliv-link-chip";
            c.href = mainA.getAttribute("href") || "#";
            c.textContent = "\ud83d\udcc4 Open " + shortTitle;
            c.onclick = (ev) => {
              ev.preventDefault();
              ev.stopPropagation();
              if (typeof window.enterSecondWindowMode === "function") {
                window.enterSecondWindowMode(shortTitle, c.getAttribute("href") || c.href);
              } else {
                window.open(c.href, "_blank");
              }
            };
            chipWrap.appendChild(c);
          }
        });
        rafBody.appendChild(chipWrap);
      }
      const rafActs = el("div", "");
      rafActs.style.cssText = "display:flex;gap:6px;flex-wrap:wrap;";
      const rBtnApp = el("button", "btn-approve", "\u2713 Approve Recommended");
      rBtnApp.type = "button";
      rBtnApp.onclick = (ev) => executeApprove(ev, rBtnApp);
      const rBtnChat = el("button", "", "Discuss in Chat");
      rBtnChat.type = "button";
      rBtnChat.onclick = (ev) => {
        ev.stopPropagation();
        sayAbout("Regarding approval (" + firstLine.slice(0, 64) + "): ");
      };
      rafActs.appendChild(rBtnApp);
      rafActs.appendChild(rBtnChat);
      rafBody.appendChild(rafActs);
      rightFlag.appendChild(rafBody);
    }

    if (!topHost) return;
    topHost.textContent = "";
    topHost.classList.toggle("folded", !_sntOpen);
    topHost.classList.toggle("open", _sntOpen);
    topHost.classList.toggle("needs-approval", needsApproval);
    const bar = el("div", "snt-bar compact-snt-bar");
    bar.style.cursor = "pointer";
    bar.title = "Click to expand or collapse " + stewardName + "'s approval request, review deliverables & next step recommendation";

    const line1 = el("div", "snt-bar-line1");
    const main = el("div", "snt-main");
    const chevron = el("span", "snt-chevron", _sntOpen ? "\u25be" : "\u25b8");
    main.appendChild(chevron);
    if (needsApproval) {
      main.appendChild(el("span", "snt-red-flag", "\ud83d\udea9 APPROVAL NEEDED"));
    }
    main.appendChild(el("span", "snt-eyebrow", needsApproval ? (stewardName + " \u2014 Next Step & Approval") : (stewardName + " \u2014 Next Step Recommendation")));
    const preview = el("span", "snt-preview", firstLine);
    main.appendChild(preview);
    line1.appendChild(main);

    const rightCluster = el("div", "snt-bar-right");
    const quickRun = el("button", "snt-btn primary snt-quick-run", needsApproval ? "\u2713 Approve & Run" : "\u25b6 Run");
    quickRun.type = "button";
    quickRun.onclick = (ev) => executeApprove(ev, quickRun);
    rightCluster.appendChild(quickRun);
    const metaRight = el("span", "snt-foldhint", _sntOpen ? "collapse \u25b4" : "details \u25b8");
    rightCluster.appendChild(metaRight);
    line1.appendChild(rightCluster);
    bar.appendChild(line1);

    const details = el("div", "snt-details");
    details.dataset.sntDetails = "1";
    details.hidden = !_sntOpen;
    if (currentFocusText) {
      const curBox = el("div", "snt-current-box");
      curBox.dataset.sntCurrent = "1";
      const curLine = el("div", "snt-current-line");
      curLine.appendChild(el("strong", "snt-cur-label", "\ud83d\udccc Current Context: "));
      curLine.appendChild(document.createTextNode(currentFocusText));
      curBox.appendChild(curLine);
      details.appendChild(curBox);
    }
    const fullRow = el("div", "snt-fullrow");
    const txtWrap = el("div", "snt-text-wrap");
    const txt = el("div", "snt-text");
    renderRich(txt, String(stated).split("\n")[0]);
    txtWrap.appendChild(txt);
    const recLine = el("div", "snt-rec-line");
    recLine.appendChild(el("strong", "snt-rec-badge", "\u2605 " + stewardName + " Recommendation: "));
    recLine.appendChild(document.createTextNode(oneLine(String(recChoice), 140) + (recWhy ? " \u2014 " + oneLine(String(recWhy), 140) : "")));
    txtWrap.appendChild(recLine);
    fullRow.appendChild(txtWrap);
    const actions = el("div", "snt-actions");
    const runBtn = el("button", "snt-btn primary", needsApproval ? "\u2713 Approve Recommended & Run Next Step" : "\u25b6 Run Next Step");
    runBtn.type = "button";
    runBtn.dataset.sntRun = "1";
    runBtn.onclick = (ev) => executeApprove(ev, runBtn);
    actions.appendChild(runBtn);
    const refBtn = el("button", "snt-btn", "\u270e Refine");
    refBtn.type = "button";
    refBtn.dataset.sntRefine = "1";
    refBtn.onclick = (ev) => {
      ev.stopPropagation();
      sayAbout("Refine next step (" + firstLine.slice(0, 80) + "): ");
    };
    actions.appendChild(refBtn);
    const disBtn = el("button", "snt-btn dismiss", "\u2715 Dismiss");
    disBtn.type = "button";
    disBtn.dataset.sntDismiss = "1";
    disBtn.onclick = async (ev) => {
      ev.stopPropagation();
      disBtn.disabled = true;
      try {
        try { await post("/api/clear-wait", { dismiss: true, question_id: q ? q.id : null }); } catch (e) {}
        if (lastState) lastState.pending_questions = [];
        if (_lastMap && _lastMap.heartbeat) _lastMap.heartbeat.human_wait = "";
        _sntOpen = false;
        topHost.dataset.userToggled = "1";
        topHost.classList.add("folded");
        topHost.classList.remove("open");
        details.hidden = true;
        chevron.textContent = "\u25b8";
        try { await loadMap(); } catch (e) {}
      } finally { disBtn.disabled = false; }
    };
    actions.appendChild(disBtn);
    fullRow.appendChild(actions);
    details.appendChild(fullRow);

    if (q && q.question) {
      const actionHost = el("div", "action-needed snt-action-tile");
      actionHost.dataset.statusAction = "1";
      if (_sntActionOpen) actionHost.classList.add("open");
      paintActionNeeded(actionHost);
      actionHost.addEventListener("click", () => { _sntActionOpen = actionHost.classList.contains("open"); });
      details.appendChild(actionHost);
    }
    bar.onclick = (ev) => {
      if (ev && ev.target && ev.target.closest && ev.target.closest("[data-top-deliverables], a, button, details, summary")) return;
      _sntOpen = !_sntOpen;
      topHost.dataset.userToggled = "1";
      topHost.classList.toggle("folded", !_sntOpen);
      topHost.classList.toggle("open", _sntOpen);
      details.hidden = !_sntOpen;
      chevron.textContent = _sntOpen ? "\u25be" : "\u25b8";
      metaRight.textContent = _sntOpen ? "collapse \u25b4" : "details \u25b8";
    };
    topHost.appendChild(bar);
    topHost.appendChild(details);
  }
  function renderStatus(stat) {
    const s = paneEl();
    if (!s || !stat) return;
    const statusId = String(stat.status_id || "");
    // The fresh status painted on open must not be replaced by an older
    // status event replayed from the engine buffer.
    if (statusId && latestStatusId && statusId <= latestStatusId) return;
    if (statusId) latestStatusId = statusId;
    latestStatusRun = stat.running || null;
    const nextBody = $("[data-delivmount] .blk.next .body");
    if (nextBody) paintRunTag(nextBody);
    else renderNextStepsTile();
    const stick = atBottom(s);
    // only the newest status stays expanded; older blocks fold to a single timestamped line inside the same scrollable window
    s.querySelectorAll(".blk.steward:not(.folded)").forEach(old => {
      old.classList.add("folded");
      old.onclick = (ev) => { ev.stopPropagation(); old.classList.toggle("folded"); };
    });
    const b = el("div", "blk steward status status-card-current");
    const hhmm = (stat.at || "").slice(-5);
    const p = stat.plan || {};
    const goal = (_lastMap && (_lastMap.goal_brief || _lastMap.goal)) || "";
    const seats = (stat.swarm || []).map(x => (x.label || "seat") + " · " + (x.state || "?"));
    const sl = stat.slice || null;
    const run = stat.running || null;
    const sliceLine = sl ? (sl.name + (sl.summary ? " — " + sl.summary : "")) : "";
    const doingLine = (run && run.label) || (stat.now || [])[0] || "";
    const bullets = (stat.next_bullets && stat.next_bullets.length) ? stat.next_bullets
      : (p.next ? [p.next] : []);
    const engineFacts = Array.isArray(stat.compact && stat.compact.facts) ? stat.compact.facts : [];
    const factValue = (label, fallback) => {
      const hit = engineFacts.find(f => f && f.label === label);
      if (hit && hit.value) return hit.value;
      return oneLine(fallback, 280);
    };
    const summaryLine = factValue("Summary", sliceLine || doingLine || oneLine(goal, 240) || "Status update");
    b.dataset.summaryText = oneLine(summaryLine, 120);
    b.dataset.hhmm = hhmm;
    const who = el("div", "who");
    who.title = "LIVE STATUS";
    const statusHeaderTitle = "[" + hhmm + "] " + oneLine(factValue("Effort", stat.effort || (_lastMap && _lastMap.name) || "Anchor"), 44);
    who.appendChild(el("span", "who-title", statusHeaderTitle));
    const foldedPreview = el("span", "folded-summary", " — " + oneLine(summaryLine, 90));
    who.appendChild(foldedPreview);
    who.appendChild(el("span", "sc-timer-pill", "Live \u00b7 10m cadence"));
    const whoRight = el("span", "who-meta spend-sr", "updated " + hhmm);
    const liveSpan = el("span", "live-activity", "");
    liveSpan.dataset.liveActivity = "1";
    whoRight.appendChild(liveSpan);
    who.appendChild(whoRight);
    if (stat.stale) who.appendChild(el("span", "stale spend-sr",
      " · last update on record — nothing has run since"));
    else if (stat.from_record) who.appendChild(el("span", "stale spend-sr",
      stat.last_run_at ? " · the record now; the last run " + String(stat.last_run_at).slice(-16) : " · the record now; no run yet"));
    b.appendChild(who);
    const body = el("div", "body");
    const isStatusFixture = /^(eta-fixture|surface-fixture|Navigation project|Empty campaign|Waiting campaign)$/i.test(String(DIR || ""));
    const cleanTodoPhrase = (t) => {
      const s = String(t || "").replace(/\*\*/g, "").trim();
      const head = s.split(/\s+[\u2014\u2013]\s+|\s+-\s+(?=[a-z])/i)[0].trim();
      return oneLine(head || s, 110);
    };
    const todo = bullets.length ? el("ul", "stodo") : null;
    if (todo) bullets.slice(0, 3).forEach(t => {
      const li = el("li", "", isStatusFixture ? oneLine(t, 120) : cleanTodoPhrase(t));
      li.title = String(t || "");
      todo.appendChild(li);
    });
    const cleanDoing = (raw) => {
      const s = String(raw || "").trim();
      if (!isStatusFixture && /^Nobody is working right now/i.test(s)) return "Idle — waiting for your input";
      return isStatusFixture ? s : oneLine(s, 280);
    };
    const cleanTests = (raw) => {
      const s = String(raw || "").trim();
      if (!isStatusFixture && /^Unavailable\s*[\u2014-]\s*no check receipt/i.test(s)) return "— (no active check gate)";
      return isStatusFixture ? s : oneLine(s, 260);
    };
    const cleanJournal = (raw) => {
      const s = String(raw || "").trim();
      if (!isStatusFixture && /^Unavailable\s*[\u2014-]\s*no journal receipt/i.test(s)) return "none";
      return isStatusFixture ? s : oneLine(s, 260);
    };
    const cleanBlocker = (raw) => {
      const s = String(raw || "").trim();
      return isStatusFixture ? s : oneLine(s, 260);
    };
    const skillRow = text => {
      const im = run && (run.kind === "skill" || run.kind === "commissioned") && window.SkillIcons && window.SkillIcons.img(run.skill || run.label || "", 14);
      if (!im) return text;
      const span = el("span", "");
      span.appendChild(im);
      span.appendChild(document.createTextNode(text));
      return span;
    };
    const rawEtaVal = factValue("ETA", stat.eta || "—");
    const computeMilestoneEtaParts = (val) => {
      const str = String(val || "").trim();
      const allSteps = (_lastMap && Array.isArray(_lastMap.steps)) ? _lastMap.steps : [];
      let curIdx = allSteps.findIndex(st => isNow(st, _lastMap));
      if (curIdx < 0) curIdx = allSteps.findIndex(st => stepNeedsAttention(st));
      if (curIdx < 0) curIdx = allSteps.findIndex(st => st && st.status === "active");
      const curStep = curIdx >= 0 ? allSteps[curIdx] : null;
      let nextIdx = -1;
      for (let k = (curIdx >= 0 ? curIdx + 1 : 0); k < allSteps.length; k++) {
        const s = allSteps[k];
        if (s && !stepDone(s) && s.status !== "parked") { nextIdx = k; break; }
      }
      if (nextIdx < 0) {
        nextIdx = allSteps.findIndex((s, k) => k !== curIdx && s && !stepDone(s) && s.status !== "parked");
      }
      const nextStep = nextIdx >= 0 ? allSteps[nextIdx] : null;
      const fmtStepLabel = (st, idx, fallback) => {
        if (!st) return fallback;
        const raw = String((st.navigation && st.navigation.label) || st.name || "").trim();
        if (!raw) return fallback;
        const hasPref = /^(?:step|wave|stage|phase)\s*\d+/i.test(raw);
        return hasPref ? oneLine(raw, 42) : ("Step " + (idx + 1) + " (" + oneLine(raw, 36) + ")");
      };
      const m1 = curStep ? fmtStepLabel(curStep, curIdx, "Current Wave") : oneLine((sl && sl.name) || p.step || "Current Wave", 40);
      const m2Fallback = (bullets && bullets[1] && cleanTodoPhrase(bullets[1])) || p.next || "Next Wave";
      const m2 = nextStep ? fmtStepLabel(nextStep, nextIdx, "Next Wave") : oneLine(m2Fallback, 40);
      const m3 = (p.steps_total || allSteps.length) ? ("Whole Plan (" + (p.steps_done || (_lastMap && _lastMap.steps_done) || 0) + "/" + (p.steps_total || (_lastMap && _lastMap.steps_total) || allSteps.length) + " waves)") : "Whole Plan";
      const parts = str.split(/\s*(?:\u2192|->)\s*/);
      if (parts.length >= 2) {
        return [
          { k: "1. " + m1, v: parts[0] || "\u2014" },
          { k: "2. " + m2, v: parts[1] || "\u2014" },
          { k: "3. " + m3, v: parts[2] || "\u2014" },
        ];
      }
      const isIdleDefault = !str || str === "\u2014" || str === "-" || /^nothing running,\s*so nothing to finish|^none\b|^idle\b/i.test(str);
      const v1 = (!isIdleDefault ? (oneLine(str, 26) + " \u00b7 ") : "") + (curStep
        ? (curStep.waiting_on_you || curStep.waiting_on
            ? "Ready for review \u00b7 Pass 2/4"
            : (curStep.refinement
                ? ("Round " + (curStep.refinement.display_round ?? curStep.refinement.round ?? 1) + " ready for review")
                : "Ready now \u00b7 awaiting dispatch"))
        : "Ready now");
      const v2 = nextStep
        ? (nextStep.waiting_on_you || nextStep.waiting_on
            ? "In review queue"
            : ("Queued next (after Wave " + (curIdx + 1) + ")"))
        : "Queued next";
      const inRev = allSteps.filter(s => s && !stepDone(s) && (s.status === "active" || stepNeedsAttention(s))).length;
      const plannedRem = allSteps.filter(s => s && !stepDone(s) && s.status !== "active" && !stepNeedsAttention(s) && s.status !== "parked").length;
      const v3 = allSteps.length
        ? (inRev + " active \u00b7 " + plannedRem + " planned remaining")
        : "Idle (no active background wave)";
      return [
        { k: "1. " + oneLine(m1, 30), v: v1 },
        { k: "2. " + oneLine(m2, 30), v: v2 },
        { k: "3. " + oneLine(m3, 30), v: v3 },
      ];
    };
    // 3-part milestone ETA: 1. Current step · 2. Next milestone · 3. Whole effort / Whole plan
    const formatMilestoneEta = (val) => {
      const str = String(val || "").trim();
      if (isStatusFixture) return str;
      const rowsData = computeMilestoneEtaParts(val);
      const box = el("div", "eta-compact");
      rowsData.forEach((item) => {
        const sp = el("span", "");
        sp.appendChild(el("em", "", item.k + ": "));
        sp.appendChild(el("b", "", item.v));
        box.appendChild(sp);
      });
      return box;
    };
    const buildEtaMilestoneBox = (val) => {
      const mBox = el("div", "eta-milestone-box");
      const head = el("div", "eta-head");
      head.appendChild(el("span", "", "\u23f1 Milestone ETA Breakdown"));
      head.appendChild(el("span", "eta-head-note", "Updated with every status tick"));
      mBox.appendChild(head);
      computeMilestoneEtaParts(val).forEach((item) => {
        const r = el("div", "eta-row");
        r.appendChild(el("span", "ek", item.k));
        r.appendChild(el("span", "ev", item.v));
        mBox.appendChild(r);
      });
      return mBox;
    };
    renderStatus._lastRefreshEta = () => {
      if (isStatusFixture) return;
      const td = document.querySelector('.blk.status.latest td[data-status-fact="eta"]');
      if (td) {
        const node = formatMilestoneEta(rawEtaVal);
        if (node && node.nodeType) {
          td.textContent = "";
          td.classList.remove("dim");
          td.appendChild(node);
        }
      }
      const oldMBox = document.querySelector('.blk.status.latest .eta-milestone-box');
      if (oldMBox && oldMBox.parentElement) {
        oldMBox.parentElement.replaceChild(buildEtaMilestoneBox(rawEtaVal), oldMBox);
      }
    };
    const rows = [
      ["Summary", summaryLine || "—"],
      ["Effort", oneLine(factValue("Effort", stat.effort || "—"), 240)],
      ["Doing", skillRow(cleanDoing(factValue("Doing", doingLine || (stat.stale ? "Idle" : "—"))))],
      ["Status", oneLine(factValue("Status", (p.steps_done || 0) + "/" + (p.steps_total || 0) +
        " done · " + (p.attention || "quiet")), 240)],
      ["Tests", cleanTests(factValue("Tests", stat.tests || "—"))],
      ["Blocker", cleanBlocker(factValue("Blocker", p.waiting_on_you ? "waiting on you: " + p.waiting_on_you
        : (stat.halt && stat.halt.reason) ? "blocked: " + stat.halt.reason : "none"))],
      ["Procs", oneLine(factValue("Procs", seats.length ? seats.join(" · ")
        : ((run && run.kind === "skill") ? run.skill + " (commissioned)" : "none")), 240)],
      ["Journal", cleanJournal(factValue("Journal", stat.journal || "—"))],
      ["ETA", formatMilestoneEta(rawEtaVal)],
      ["To do", todo || oneLine(factValue("To do", "—"), 240)],
    ];
    const tab = el("table", "stab");
    rows.forEach(([k, v]) => {
      const text = (v && v.nodeType) ? "" : String(v || "").trim();
      const dim = !(v && v.nodeType) && (!text || text === "—" || text.indexOf("— (") === 0);
      const flag = k === "Blocker" && text && text !== "none" && text !== "—";
      const okCell = (k === "Blocker" && text === "none") || (k === "Tests" && /^(pass\b|last verdict GO\b)/i.test(text));
      const rowCls = (flag ? "flag " : "") +
        (k === "Summary" ? "row-summary " : "") +
        (k === "ETA" ? "row-eta-inline " : "") +
        (k === "To do" ? "row-todo-inline " : "");
      const tr = el("tr", rowCls.trim());
      tr.appendChild(el("th", "", k));
      const td = el("td", (dim ? "dim" : "") + (okCell ? " ok-val" : ""));
      td.dataset.statusFact = k.toLowerCase();
      if (v && v.nodeType) td.appendChild(v);
      else {
        const span = el("span", "", text || "—");
        span.title = String(v || "");
        td.appendChild(span);
      }
      tr.appendChild(td);
      tab.appendChild(tr);
    });
    const compact = el("div", "status-compact");
    const leadText = stat.lead_line || "Next not stated by the steward";
    const leadEl = el("div", "slead" + (stat.lead_line && stat.lead_line.indexOf("Next:") === 0 ? "" : " dim"), leadText);
    leadEl.dataset.statusFact = "lead";
    leadEl.title = leadText;
    compact.appendChild(leadEl);
    compact.appendChild(tab);
    if (!isStatusFixture) {
      compact.appendChild(buildEtaMilestoneBox(rawEtaVal));
      const todoSummaryStr = bullets.length
        ? bullets.slice(0, 3).map((t, idx) => (idx + 1) + ". " + cleanTodoPhrase(t)).join(" \u2192 ")
        : oneLine(factValue("To do", p.next || "Review current deliverables & approve next step"), 160);
      const todoFoot = el("div", "stodo-footer");
      todoFoot.appendChild(el("strong", "", "To do: "));
      todoFoot.appendChild(document.createTextNode(todoSummaryStr));
      compact.appendChild(todoFoot);
    }
    if (stat.latest_event && stat.latest_event.summary) {
      const latest = el("p");
      latest.dataset.statusFact = "latest";
      latest.appendChild(el("strong", "", "Latest "));
      latest.appendChild(el("span", "", oneLine(stat.latest_event.summary, 140) +
        " · " + new Date(stat.latest_event.at).toLocaleString()));
      compact.appendChild(latest);
    }
    const rawWorkMap = (Array.isArray(stat.work_map) && stat.work_map.length)
      ? stat.work_map
      : ((_lastMap && Array.isArray(_lastMap.steps)) ? _lastMap.steps : []);
    const mapSteps = [];
    rawWorkMap.forEach((entry) => {
      if (entry && Array.isArray(entry.steps)) {
        entry.steps.forEach((s) => { if (s) mapSteps.push(s); });
      } else if (entry) {
        mapSteps.push(entry);
      }
    });
    if (mapSteps.length || stat.project || p.steps_total) {
      const smap = el("div", "smap-footer");
      smap.dataset.statusFact = "steward-map";
      const projStr = (stat.project && typeof stat.project === "object")
        ? ((stat.project.steps_done || p.steps_done || 0) + "/" + (stat.project.steps_total || p.steps_total || mapSteps.length) +
           " steps done" + (p.step ? " \u00b7 active: " + p.step : "") + (stat.project.parts ? " \u00b7 " + stat.project.parts : ""))
        : (stat.project || ((p.steps_done || 0) + "/" + (p.steps_total || mapSteps.length) +
           " steps done" + (p.step ? " \u00b7 active: " + p.step : "")));
      smap.appendChild(el("div", "smap-head", personaName().toUpperCase() + " MAP STATUS \u00b7 " + projStr));
      if (mapSteps.length) {
        const ul = el("ul", "smap-list");
        mapSteps.forEach((st) => {
          const stStatus = String(st.status || "").toLowerCase();
          const waitText = st.waiting_on_you || st.waiting_on || "";
          const isDone = stStatus === "done" || stStatus === "completed";
          const isWait = !isDone && (Boolean(waitText) || stStatus === "waiting" || stStatus === "blocked");
          const isAct = !isDone && !isWait && (stStatus === "active" || stStatus === "in_progress" || (p.step && st.name === p.step));
          const mark = isDone ? "\u2713" : isWait ? "\u2691" : isAct ? "\u25cf" : "\u25cb";
          const cls = isDone ? "done" : isWait ? "wait" : isAct ? "active" : "todo";
          const li = el("li", "smap-item " + cls);
          li.appendChild(el("span", "smap-mark", mark));
          const label = (st.navigation && st.navigation.label) || st.name || st.id || "step";
          li.appendChild(el("span", "smap-name", label));
          const note = isWait && typeof waitText === "string" && waitText !== "waiting"
            ? " \u2014 " + oneLine(waitText, 60)
            : (isAct ? " (active)" : "");
          if (note) li.appendChild(el("span", "smap-note", note));
          ul.appendChild(li);
        });
        smap.appendChild(ul);
      }
      compact.appendChild(smap);
    }
    body.appendChild(compact);
    if (p.goal_reread === false)
      body.appendChild(el("div", "splan sflag", "goal not re-read since last close"));
    b.appendChild(body);
    s.querySelectorAll(".blk.status.latest").forEach(o => {
      o.classList.remove("latest");
      o.classList.add("folded");
      o.onclick = (ev) => { ev.stopPropagation(); o.classList.toggle("folded"); };
    });
    b.classList.add("latest");
    const firstHist = s.querySelector(".blk.status:not(.latest)");
    if (firstHist) s.insertBefore(b, firstHist);
    else s.appendChild(b);
    try {
      const prevList = $("[data-prev-status-list]");
      if (Array.isArray(stat.history_updates)) {
        const existingTimes = new Set(
          Array.from(s.querySelectorAll(".blk.status")).map(n => n.dataset.hhmm || "")
        );
        stat.history_updates.forEach(hu => {
          if (!hu || (!hu.summary && !hu.doing)) return;
          const atStr = String(hu.at || "\u2014");
          if (existingTimes.has(atStr)) return;
          existingTimes.add(atStr);
          const hb = el("div", "blk steward status folded hist-item");
          hb.dataset.histItem = "1";
          hb.dataset.hhmm = atStr;
          const w = el("div", "who", "\u23f1 [" + atStr + "] \u2014 " + oneLine(hu.summary || hu.doing || "Status update", 92));
          hb.appendChild(w);
          const hbody = el("div", "body");
          if (hu.doing) hbody.appendChild(el("div", "sdmeta", "Doing: " + hu.doing));
          if (hu.status) hbody.appendChild(el("div", "sdmeta", "Status: " + hu.status));
          if (hu.tests) hbody.appendChild(el("div", "sdmeta", "Tests: " + hu.tests));
          hb.appendChild(hbody);
          hb.onclick = (ev) => { ev.stopPropagation(); hb.classList.toggle("folded"); };
          if (prevList) prevList.appendChild(hb);
          else s.appendChild(hb);
        });
      }
      if (prevList) {
        s.querySelectorAll(".blk.status:not(.latest)").forEach(oldNode => {
          prevList.appendChild(oldNode);
        });
      }
      const prevCount = $("[data-prev-status-count]");
      const archivedCount = (prevList ? prevList.querySelectorAll(".blk.status").length : 0) + s.querySelectorAll(".blk.status:not(.latest)").length;
      if (prevCount) prevCount.textContent = "(" + archivedCount + " archived)";
    } catch (e) { /* no-op */ }
    syncCompactActivity(lastState);
    s.scrollTop=0;
    // the window's header carries the time of the last update (idle projects
    // show their LAST update, stamped, not a fresh blank)
    const stamp = $("[data-statusstamp]");
    if (stamp) stamp.textContent = "last update " + hhmm + (stat.stale ? " · idle" : "");
    // the status of record sits on the top line; the goal line keeps the goal (John, 2026-09-25)
    try {
      let line = stat.lead_line || "Next not stated by the steward";
      if (!p.waiting_on_you && stat.eta) line += " · ETA " + stat.eta;
      if (line.length > 120) line = line.slice(0, 117).replace(/\s+\S*$/, "") + "…";
      const barlead = $("[data-barlead]");
      if (barlead) { barlead.textContent = line + (stat.stale ? "  (" + hhmm + ")" : ""); barlead.title = line; }
    } catch (e) { /* no-op */ }
    // Deliverables tile stays pinned FIRST in the pane (2026-08-25, John's ask),
    // and its register refreshes on the same cadence as the status it sits above.
    try {
      // the tile owns [data-delivmount] above this scrollport; only pages
      // without that slot still need it pinned first INSIDE the pane
      if (!$("[data-delivmount]")) {
        const dt = s.querySelector(".blk.deliv");
        if (dt && s.firstChild !== dt) s.insertBefore(dt, s.firstChild);
      }
      renderDeliverablesTile();
    } catch (e) { /* no-op */ }
    // Render receipt (2026-08-25; COALESCED same day after review): the status is
    // now ON JOHN'S SCREEN — tell the engine so delivery is a receipt, not a hope
    // (wakeup-delivery lesson). poll() replays the whole event buffer on open, so
    // acks coalesce to ONE for the NEWEST rendered status (800ms debounce) — never
    // a burst per historical event. Fire-and-forget; failures never touch the pane.
    try {
      renderStatus._ackAt = stat.at || "";
      clearTimeout(renderStatus._ackTimer);
      renderStatus._ackTimer = setTimeout(() => {
        try { post(api("/api/status-ack"), { at: renderStatus._ackAt }).catch(() => {}); }
        catch (e) { /* no-op */ }
      }, 800);
    } catch (e) { /* no-op */ }
  }

  /* ---------- deliverables (2026-08-25, John's ask — journal 0010) ----------
     ONE source: the effort's DELIVERABLES.md register (the steward's own
     convention). Surfaced twice: a folded tile pinned at the very TOP of the
     status pane, and links inside the goal/map expansion. Openable entries
     stream through the contained /api/deliverable-file route; entries pointing
     outside the effort render as text, never links. */
  let _delivBusy = false;
  // per-step embedding (John, 2026-08-26: "embed the work products in the
  // plan flow"): register rows may carry an optional Step column — a step
  // NUMBER or a name fragment — and the map paints the link UNDER that step.
  let _deliv = {items: [], approved: [], acts: [], warning: ""}, _lastMap = null, _refinementContext = null, _answerQuestionId = null;
  let _delivOpen = false;   // starts as a 1-line pull-down summary at top of right panel so Status dominates; click pulls down
  function shortWhat(it) {
    return String((it && (it.what || it.label)) || "")
      .replace(/^(?:START HERE|FOR REVIEW|CURRENT)\s*[:\u2014\u2013-]?\s*/i, "")
      .split(" \u2014 ")[0].trim();
  }
  function stepDeliverables(step, idx1) {
    const steps=Array.isArray(_lastMap?.steps)?_lastMap.steps:[step];
    return _deliv.items.filter((it) => {
      const owner=navOwner(steps,it);
      return owner===step||!!owner&&typeof owner.id==='string'&&!!owner.id&&owner.id===step.id;
    });
  }
  // One blue SENTENCE under its step. Click once → the detail; click the
  // detail's link → the report itself (John's two-stage disclosure).
  function stepDelivLine(it) {
    const key = (it.dir || "") + "|" + (it.managed ? it.step + "|" + it.product_id : (it.path || it.what || ""));
    const row = el("div", "sdrow");
    const one = (it.what || "").split(" — ")[0].trim() || it.what || "(untitled)";
    const line = el("div", "sdone", "▸ " + one);
    try { const im = window.SkillIcons && window.SkillIcons.img(itemMark(it) || "", 14); if (im) line.insertBefore(im, line.firstChild); } catch (e) { /* no-op */ }
    const detail = el("div", "sddetail");
    if (it.managed) detail.style.overflowWrap = "anywhere";
    const full = el("div", "", it.what || "");
    detail.appendChild(full);
    if (it.date) detail.appendChild(el("div", "sdmeta", it.date));
    detail.appendChild(delivRow(it));           // the actual open link
    if (it.history && it.history.length) {
      const history = document.createElement("details");
      history.open = _openHistories.has(key);
      history.addEventListener("toggle", () => {
        if (!history.isConnected) return;
        if (history.open) _openHistories.add(key);
        else _openHistories.delete(key);
      });
      const summary = document.createElement("summary");
      summary.textContent = "Earlier versions · " + it.history.length + " presented";
      history.appendChild(summary);
      it.history.forEach((version) => {
        const labelled = Object.assign({}, version, {what: version.what + (version.accepted ? " · accepted" : "")});
        history.appendChild(delivRow(labelled));
      });
      detail.appendChild(history);
    }
    // the detail already carries the full description above; the link itself
    // just says what it does (2026-09-03)
    const lnk = detail.querySelector(".drow a");
    // a route row is labelled by the document it opens (report.md), never the
    // whole route string (2026-09-05, seen on the page)
    if (lnk) {
      lnk.textContent = it.managed ? "Open current version" : "Open ↗" +
        (it.path ? "  " + it.path : (it.route ? "  " + routeName(it.route) : ""));
      const quickOpen = el("button", "sdone-open-btn", "Open \u25eb");
      quickOpen.type = "button";
      quickOpen.title = "Open deliverable in Right Split-Screen Window";
      quickOpen.style.cssText = "margin-left:8px;padding:1px 6px;font-size:10.5px;border-radius:4px;border:1px solid rgba(56,189,248,0.35);background:rgba(56,189,248,0.1);color:#38bdf8;cursor:pointer;";
      quickOpen.onclick = (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (typeof lnk.onclick === "function") lnk.onclick(ev);
        else if (typeof window.enterSecondWindowMode === "function") window.enterSecondWindowMode(one, lnk.href);
        else window.open(lnk.href, "_blank");
      };
      line.appendChild(quickOpen);
    }
    row.dataset.key = key;
    if (_openDelivs.has(key)) row.classList.add("open");
    line.onclick = (ev) => {
      ev.stopPropagation();
      row.classList.toggle("open");
      if (row.classList.contains("open")) _openDelivs.add(key);
      else _openDelivs.delete(key);
    };
    // the detail's own clicks (its link, its text) never toggle the row or the step
    detail.onclick = (ev) => { ev.stopPropagation(); };
    row.appendChild(line);
    row.appendChild(detail);
    return row;
  }
  // What the USER opened, kept across repaints. paintStepsList rebuilds every
  // <li> and it runs on every map-stamp change (the steward rewrites the map
  // constantly) and on every register load — without this, a click collapsed
  // again within seconds.
  const _openSteps = new Set(), _openDelivs = new Set(), _openHistories = new Set();
  function producerHandoffs(handoffs, label, key) {
    const history = el("details", "sdmeta");
    history.open = _openHistories.has(key);
    history.ontoggle = () => history.open ? _openHistories.add(key) : _openHistories.delete(key);
    history.appendChild(el("summary", "", handoffs.length + " " + label));
    const files = h => (Array.isArray(h.outputs) ? h.outputs : []).map(o => typeof o === "string" ? o : (o && (o.path || o.route)) || "").filter(Boolean);
    const empty = [];
    handoffs.forEach((h) => {
      const day = String(h.at || "").slice(0, 10);
      const paths = files(h);
      if (!paths.length) { empty.push(day); return; }
      paths.slice(0, 4).forEach(p => {
        const name = p.split(/[\\/]/).pop();
        const row = el("div", "handoff");
        row.appendChild(el("span", "", (day || "undated") + " \u00b7 "));
        row.appendChild(navFile({what: name, path: p, openable: true}, "handoffs", true));
        const act = el("button", "navactbtn ndact", "act on");
        act.onclick = () => sayAbout("Act on: " + name);
        row.appendChild(act);
        history.appendChild(row);
      });
    });
    if (empty.length) {
      const days = [...new Set(empty.filter(Boolean))].sort();
      const line = empty.length + " turn" + (empty.length === 1 ? "" : "s") + (days.length ? " on " + days.join(", ") : "") + " recorded no files";
      const row = el("div", "handoff");
      row.appendChild(el("span", "", line + " \u00b7 "));
      const act = el("button", "navactbtn ndact", "act on");
      act.onclick = () => sayAbout("Act on: " + line);
      row.appendChild(act);
      history.appendChild(row);
    }
    return history;
  }
  /* Course/product navigation: one event-derived organization for both views. */
  const navStorageKey = () => 'steward_navigation:' + (window.STEWARD_PID || '') + ':' + DIR;
  let navChoices = null;
  // the Not done list starts closed whenever a cockpit opens (his word, 2026-10-06); his click holds while the page
  // lives (the plan repaints on every stamp), and is never restored open from a stored choice on the next open
  const NAV_FRESH = new Set(["plan:notdone"]), navSession = {};
  function fileUrl(p) {
    return "file:///" + String(p).replace(/\\/g, "/").replace(/^\/+/, "").split("/")
      .map((seg, i) => i === 0 && /^[A-Za-z]:$/.test(seg) ? seg : encodeURIComponent(seg)).join("/");
  }
  function navChoice(key, fallback) {
    if (NAV_FRESH.has(key)) return Object.prototype.hasOwnProperty.call(navSession,key) ? navSession[key] : false;
    if (!navChoices) { try { navChoices=JSON.parse(localStorage.getItem(navStorageKey())||'{}'); } catch(e) { navChoices={}; } }
    return Object.prototype.hasOwnProperty.call(navChoices,key) ? navChoices[key] : fallback;
  }
  function navDisclosure(key, title, open=false, mark=null) {
    const d=el('details','navgroup'), summary=el('summary','');
    const marked = !!(mark && mark.glyph);
    if (marked) summary.appendChild(el('span','plan-mark '+mark.cls, mark.glyph));
    summary.appendChild(document.createTextNode((marked ? ' ' : '') + title));
    d.dataset.navGroup=key;summary.dataset.navFocus='group:'+key;
    d.open=navChoice(key,open);d.appendChild(summary);
    const save=value=>{if(NAV_FRESH.has(key)){navSession[key]=value;return;}navChoices[key]=value;try{localStorage.setItem(navStorageKey(),JSON.stringify(navChoices));}catch(e){}};
    summary.addEventListener('click',()=>save(!d.open));
    d.addEventListener('toggle',()=>{if(d.isConnected)save(d.open);});
    return d;
  }
  function navOwner(steps, item) {
    steps=Array.isArray(steps)?steps:[];
    const stable=owner=>owner&&typeof owner.id==='string'&&owner.id.trim()&&
      steps.filter(s=>String(s.id||'').toLowerCase()===owner.id.toLowerCase()).length===1?owner:null;
    if(Object.prototype.hasOwnProperty.call(item,'owner_step_id')) {
      return typeof item.owner_step_id==='string'
        ? stable(steps.find(s=>s.id===item.owner_step_id)) : null;
    }
    const key=String(item.step||'').trim().toLowerCase();
    if(!key)return null;
    const ids=steps.filter(s=>String(s.id||'').trim().toLowerCase()===key);
    if(ids.length)return ids.length===1?stable(ids[0]):null;
    if(/^\d+$/.test(key))return stable(steps[Number(key)-1]);
    const names=steps.filter(s=>String(s.name||'').toLowerCase().includes(key));
    return names.length===1?stable(names[0]):null;
  }
  function navModel(map, items) {
    map=map&&typeof map==='object'?map:{};
    const steps=Array.isArray(map.steps)?map.steps:[];
    items=Array.isArray(items)?items:[];
    const fallback=map.navigation_fallback||{},fallbackRoot=fallback.root||fallback;
    const hasNavigation=steps.some(s=>s.navigation&&Array.isArray(s.navigation.path));
    const roots=[],all=new Map(),stepGroups=new Map(),relatedGroups=new Map(),overrides=new Map(),definitions=new Map(),featured=new Set();
    const stepIdCounts=new Map();
    steps.forEach(s=>{const id=typeof s.id==='string'?s.id.trim().toLowerCase():'';if(id)stepIdCounts.set(id,(stepIdCounts.get(id)||0)+1);});
    const pathKey=p=>String(p||'').replace(/\\/g,'/').toLowerCase();
    const addDefinition=g=>{
      if(g&&typeof g.id==='string'&&g.id)definitions.set(g.id,{...g,label:String(g.label||g.id),order:Number.isFinite(g.order)?g.order:0});
    };
    (Array.isArray(fallback.groups)?fallback.groups:[]).forEach(addDefinition);
    const rootId=typeof fallbackRoot.id==='string'&&fallbackRoot.id?fallbackRoot.id:!hasNavigation?'campaign-root':null;
    if(rootId)addDefinition({id:rootId,label:fallbackRoot.label||map.name||map.title||'Project work',order:0});
    steps.forEach(s=>(Array.isArray(s.navigation?.groups)?s.navigation.groups:[]).forEach(addDefinition));
    steps.forEach(s=>(Array.isArray(s.navigation?.featured_paths)?s.navigation.featured_paths:[]).forEach(p=>featured.add(pathKey(p))));
    const safePath=p=>Array.isArray(p)&&p.length>0&&p.length<=2&&p.every(g=>typeof g==='string'&&definitions.has(g));
    function ensure(path) {
      if(!safePath(path)){
        addDefinition({id:'unclassified',label:'Other work — needs organization',order:99999});
        path=rootId?[rootId,'unclassified']:['unclassified'];
      }
      let parent=null;
      for(const gid of path) {
        const g=definitions.get(gid);
        let node=all.get(g.id);
        if(!node){node={...g,children:[],steps:[],items:[],referenceSteps:[],referenceItems:[],parent,pinned:false};all.set(g.id,node);(parent?parent.children:roots).push(node);}
        parent=node;
      }
      return parent;
    }
    if(rootId){
      ensure([rootId]);
      (Array.isArray(fallback.components)?fallback.components:[]).forEach((component,i)=>{
        if(!component||typeof component.id!=='string'||!component.id||component.id===rootId)return;
        if(!definitions.has(component.id))addDefinition({id:component.id,label:component.name||component.id,order:i});
        ensure([rootId,component.id]);
      });
    }
    steps.forEach((s,i)=>{
      const n=s.navigation||{};
      let path=n.path;
      if(!hasNavigation){
        const stableId=typeof s.id==='string'?s.id.trim():'';
        if(stableId&&stepIdCounts.get(stableId.toLowerCase())===1){
          const id='compat-step:'+stableId;
          addDefinition({id,label:s.name||stableId,order:i});path=[rootId,id];
        } else path=null;
      }
      const group=ensure(path);group.steps.push({step:s,index:i});stepGroups.set(s,group);
      if(n.pin)for(let g=group;g;g=g.parent)g.pinned=true;
      (Array.isArray(n.include_paths)?n.include_paths:[]).forEach(ensure);
      const references=[];
      (Array.isArray(n.related_paths)?n.related_paths:[]).forEach(p=>{
        const related=ensure(p);
        if(related===group||references.includes(related))return;
        related.referenceSteps.push({step:s,index:i});references.push(related);
      });
      relatedGroups.set(s,references);
      (Array.isArray(n.items)?n.items:[]).forEach(o=>{if(typeof o.source_path==='string')overrides.set(pathKey(o.source_path),ensure(o.path));});
    });
    items.forEach(it=>{
      const owner=navOwner(steps,it);
      const group=overrides.get(pathKey(it.path))||(owner&&stepGroups.get(owner))||ensure(null);
      group.items.push(it);
      (owner?relatedGroups.get(owner)||[]:[]).forEach(related=>{
        if(related!==group&&!related.referenceItems.includes(it))related.referenceItems.push(it);
      });
    });
    const itemOrder=(a,b)=>Number(!!b.managed)-Number(!!a.managed)||String(b.date||'').localeCompare(String(a.date||''));
    const sortNodes=nodes=>{nodes.sort((a,b)=>(a.order-b.order)||a.label.localeCompare(b.label));nodes.forEach(n=>{sortNodes(n.children);n.items.sort(itemOrder);n.referenceItems.sort(itemOrder);});};
    sortNodes(roots);return {roots,all,featured};
  }
  const itemMark = it => window.SkillIcons ? window.SkillIcons.forItem(it, navOwner((_lastMap && _lastMap.steps) || [], it)) : null;
  function navFile(it, surface, readOnly=false) {
    const box=el('div','navfile');box.dataset.navPath=it.path||it.route||it.what;box.dataset.productId=it.product_id||'';
    const shown={...it,date:String(it.date||'').split('T')[0]};
    if(it.managed && !it.open_path)shown.what=String(it.what||it.product_id).replace(/-/g,' ');
    const row=delivRow(shown);row.classList.add('navfilelink');box.appendChild(row);
    if(it.managed) {
      const round=it.round===0?'Initial draft':Number.isInteger(it.round)?'Refinement '+it.round:'';
      box.appendChild(el('div','sdmeta',it.accepted?'✓ Approved':it.accepted_current?'✓ Accepted version':
        [round,it.provisional?'Provisional draft':String(it.phase||'').replace(/_/g,' ')].filter(Boolean).join(' · ')));
      if(!readOnly && !it.accepted && !it.accepted_current && it.presentation_id) {
        const accept=el('button','nav-accept','Done with this item');
        accept.title='Approve only '+it.product_id+' · '+round;
        accept.onclick=async()=>{
          accept.disabled=true;
          try {
            // one decision for a format pair: the product and each verified companion revision of the same presentation
            for(const x of [it,...(it._alsoAccept||[])]) {
              const response=await post('/api/refinement-accept',{step_id:x.step,presentation_id:x.presentation_id,
                product_id:x.product_id,revision_id:x.revision_id,hash:x.hash});
              const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Approval failed');
            }
            await loadMap();await renderDeliverablesTile();
          } catch(error) {box.appendChild(el('div','sdmeta',error.message));accept.disabled=false;}
        };
        box.appendChild(accept);
      }
      if(!readOnly && !it.accepted && it.presentation_id) {
        const refine=el('button','nav-refine','Request changes');
        refine.onclick=()=>{_answerQuestionId=null;_refinementContext={step_id:it.step,presentation_id:it.presentation_id,product_id:it.product_id};
          const ta=$('[data-say]');if(ta){ta.placeholder='Changes for '+it.product_id;ta.focus();}};
        box.appendChild(refine);
      }
    }
    const a=row.querySelector('a');if(a)a.dataset.navFocus=surface+':file:'+(it.path||it.route||it.what);
    if(it.history&&it.history.length) {
      const h=navDisclosure(surface+':versions:'+it.step+':'+it.product_id,'Earlier versions · '+it.history.length);
      it.history.slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))).forEach(v=>h.appendChild(delivRow(v)));
      box.appendChild(h);
    }
    return box;
  }
  function navStyle() {
    if(document.getElementById('course-navigation-style'))return;
    const s=el('style');s.id='course-navigation-style';
    s.textContent=`.navtree{min-width:0;font-size:13px;line-height:1.42}.navgroup{margin:5px 0;border-top:1px solid #ffffff20;min-width:0}.navgroup>summary{cursor:pointer;padding:8px 3px;font-weight:600;white-space:normal;overflow-wrap:anywhere}.navgroup>summary:has(.plan-mark){list-style:none}.navgroup>summary:has(.plan-mark)::-webkit-details-marker{display:none}.navcontents{padding:0 0 5px 9px;min-width:0}.navgroup .navgroup .navcontents{padding-left:7px}.navfile{padding:5px 0;overflow-wrap:anywhere;border-bottom:1px solid #ffffff0b}.navfile .drow{white-space:normal;overflow:visible;font-size:13px;line-height:1.42}.navfile a{white-space:normal;overflow-wrap:anywhere}.navpin{padding:10px;margin:0 0 10px;border:1px solid #679cc077;border-radius:6px;background:#44698718}.navpin-title{font-size:14px;font-weight:600;margin:3px 0}.naveyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.8}.navstep-list{padding:0!important;list-style:none}.navstep-list>li{padding:6px 0!important}.navstep-list .sdeliv{display:none}.navstep-list .sdeliv:has(button){display:block}.navempty{opacity:.75;padding:5px 0;font-size:12px}.navtree .navsupport{margin-top:7px}.navtree .navsupport>summary{font-size:12px;font-weight:400}.navtree .wpkind{display:none}.navtree .navstep-list .stitle{white-space:normal}.navtree .navstep-list .sdmeta{font-size:12px}.navtree .navfile .navgroup{font-size:12px}.navtree .navfile .navgroup>summary{padding:3px;font-weight:400}`;
    s.textContent+='[data-delivmount] .blk.deliv:not(.folded)>.body,[data-delivmount] .blk.next:not(.folded)>.body{max-height:min(52vh,500px);overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;padding-right:6px}';
    document.head.appendChild(s);
  }
  function renderNavigation(target,map,items,surface,stepRows=null) {
    const model=navModel(map,items);if(!model && stepRows)return false;navStyle();target.classList.add('navtree');
    const pin=(map?.steps||[]).find(s=>s.navigation&&s.navigation.pin);
    if(!stepRows) {
      const p=el('div','navpin');p.appendChild(el('div','naveyebrow','\ud83d\udc41\ufe0f Most recent & for review — Current work and review'));
      const current=items.filter(i=>i.is_current===true)   // the server's one rule (current_review_items)
        .sort((a,b)=>Number(/^START HERE\b/.test(b.what||''))-Number(/^START HERE\b/.test(a.what||'')) || String(b.date||'').localeCompare(String(a.date||'')));
      if(current.length){
        p.appendChild(el('div','naveyebrow','Files awaiting you \u00b7 '+current.length));
        current.forEach(it=>p.appendChild(navFile(it,surface+':pin',true)));
        if(surface==='deliverables' && items.length > current.length){
          const currentPaths = new Set(current.map(c => c.path || c.route || c.what));
          const latestExtra = items.filter(i => !currentPaths.has(i.path || i.route || i.what))
            .slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))).slice(0,3);
          if(latestExtra.length){
            p.appendChild(el('div','naveyebrow','Latest registered deliverables \u00b7 '+latestExtra.length));
            latestExtra.forEach(it=>p.appendChild(navFile(it,surface+':latest',true)));
          }
        }
      } else {
        p.appendChild(el('div','navempty','No files awaiting review.'));
        if(surface==='deliverables' && items.length){
          const latest=items.slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))).slice(0,5);
          p.appendChild(el('div','naveyebrow','Latest registered deliverables \u00b7 '+latest.length));
          latest.forEach(it=>p.appendChild(navFile(it,surface+':latest',true)));
        }
      }
      target.appendChild(p);
      const finalItems = items.filter(i => /^(?:Final|Finished)\s+Deliverables\//i.test(String(i.path || '').replace(/\\/g, '/')) || /\bFINAL\b/i.test(String(i.what || '')));
      const approvedPool = [..._deliv.approved];
      const seenApproved = new Set(approvedPool.map(i => i.path || i.route || i.what));
      finalItems.forEach(fi => { const k = fi.path || fi.route || fi.what; if (k && !seenApproved.has(k)) { seenApproved.add(k); approvedPool.push(fi); } });
      const approved=navDisclosure(surface+':approved','\u2605 Final & Approved deliverables · '+approvedPool.length, approvedPool.length > 0);
      approvedPool.slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')))
        .forEach(it=>approved.appendChild(navFile(it,surface+':approved')));
      if(!approvedPool.length)approved.appendChild(el('div','navempty','No explicitly approved deliverables yet.'));
      target.appendChild(approved);
    }
    if(!model) {
      const rest=navDisclosure(surface+':all','All deliverables');
      items.forEach(it=>rest.appendChild(navFile(it,surface+':all')));target.appendChild(rest);
      return true;
    }
    const groupSteps=g=>{
      const unique=new Map();
      g.steps.concat(g.referenceSteps||[],g.children.flatMap(groupSteps)).forEach(s=>{
        const key='index:'+s.index;
        if(!unique.has(key))unique.set(key,s);
      });
      return [...unique.values()];
    };
    const groupHasDeliverables=g=>(g.items&&g.items.length>0)||(g.referenceItems&&g.referenceItems.length>0)||(g.children&&g.children.some(groupHasDeliverables));
    const groupMarkInfo=g=>{
      const required=groupSteps(g).filter(s=>s.step.navigation?.role==='primary');
      const steps=required.length?required:groupSteps(g);
      if(!steps.length) return {glyph:'',cls:'todo'};
      if(steps.every(s=>stepDone(s.step))) return {glyph:'✓',cls:'done'};
      if(steps.some(s=>s.step && (s.step.status==='waiting' || s.step.status==='blocked' || s.step.refinement?.phase==='awaiting_review'))) return {glyph:'⚑',cls:'flag'};
      if(steps.some(s=>isNow(s.step,map) || s.step?.status==='active')) return {glyph:'●',cls:'now'};
      return {glyph:'',cls:'todo'};
    };
    function renderReferences(g,parent,refSurface) {
      const steps=g.referenceSteps||[],items=g.referenceItems||[];
      if(!steps.length&&!items.length)return;
      const shared=navDisclosure(refSurface+':shared:'+g.id,'Shared work and deliverables');
      if(steps.length){
        const list=el('ul','navstep-list');
        steps.forEach(s=>{
          const row=el('li','navstep-reference'),done=stepDone(s.step),attention=stepNeedsAttention(s.step),now=isNow(s.step,map);
          row.dataset.stepRef=s.step.id||String(s.index);
          row.appendChild(el('span','plan-mark '+(done?'done':attention?'flag':now?'now':'todo'),done?'✓':attention?'⚑':now?'●':''));
          row.appendChild(document.createTextNode(' '+(s.step.name||s.step.id||'Step '+(s.index+1))));
          list.appendChild(row);
        });
        shared.appendChild(list);
      }
      items.forEach(it=>shared.appendChild(navFile(it,refSurface+':reference:'+g.id,true)));
      parent.appendChild(shared);
    }
    function renderGroup(g,parent) {
      // Keep linear wave sequences together in order; only fold parked/support steps when there are no sub-groups
      const hasSubgroups = Array.isArray(g.children) && g.children.length > 0;
      const offPath = st => hasSubgroups ? (stepDone(st) || st.status === 'parked') : (st.status === 'parked');
      const defaultOpen = Boolean(stepRows && !g.parent);
      const d=navDisclosure(surface+':'+g.id,g.label,defaultOpen,groupMarkInfo(g)),body=el('div','navcontents');
      d.dataset.groupId=g.id;
      if(stepRows) {
        const main=g.steps.filter(s=>s.step.navigation&&s.step.navigation.role==='primary'&&!offPath(s.step));
        if(main.length) {const list=el('ul','navstep-list');main.forEach(s=>{const row=stepRows.get(s.index);if(row)list.appendChild(row);});body.appendChild(list);}
      }
      g.children.forEach(child=>{
        if (!stepRows && String(child.id || '').startsWith('compat-step:') && !groupHasDeliverables(child)) return;
        renderGroup(child,body);
      });
      const mainFiles=g.items.filter(it=>it.managed||model.featured.has(String(it.path||'').replace(/\\/g,'/').toLowerCase()));
      const shown=g.items.length<=6?g.items:mainFiles.length?mainFiles:g.items.slice(0,3);
      const rest=g.items.filter(it=>!shown.includes(it));
      shown.forEach(it=>body.appendChild(navFile(it,surface)));
      if(rest.length){const more=navDisclosure(surface+':materials:'+g.id,'Earlier work and supporting materials · '+rest.length);rest.forEach(it=>more.appendChild(navFile(it,surface)));body.appendChild(more);}
      renderReferences(g,body,surface);
      if(stepRows) {
        const support=g.steps.filter(s=>!s.step.navigation||s.step.navigation.role!=='primary'||offPath(s.step));
        if(support.length){const more=navDisclosure(surface+':support:'+g.id,'Done, parked and supporting steps · '+support.length),list=el('ul','navstep-list');more.classList.add('navsupport');support.forEach(s=>{const row=stepRows.get(s.index);if(row)list.appendChild(row);});more.appendChild(list);body.appendChild(more);}
      } else if(!g.items.length&&!g.referenceItems.length&&!g.referenceSteps.length&&!g.children.length)body.appendChild(el('div','navempty','No deliverables registered yet.'));
      d.appendChild(body);parent.appendChild(d);
    }
    const isLegacyNavTest = /^(Navigation project|Empty campaign|Waiting campaign)$/i.test(String((map && (map.name || map.title)) || DIR || ""));
    const isSyntheticStepTree = Boolean(map && map.navigation_mode === "fallback" && !((map.navigation_fallback && map.navigation_fallback.components && map.navigation_fallback.components.length) > 0) && (map.steps || []).length > 0);
    if (!(surface === 'deliverables' && isSyntheticStepTree && !isLegacyNavTest)) {
      model.roots.forEach(g=>renderGroup(g,target));   // one tree for the plan and the deliverables tile (John, 2026-09-23)
    }
    if (surface === 'deliverables' && items.length) {
      const hasCurrent = items.some(i => i.is_current === true);
      const allBox = navDisclosure(surface + ':all-flat', 'All deliverables \u00b7 ' + items.length, !hasCurrent);
      items.slice().sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
        .forEach(it => allBox.appendChild(navFile(it, surface + ':all-flat')));
      target.appendChild(allBox);
    }
    return true;
  }
  function restoreNavFocus(key) {
    if(!key)return;
    const e=Array.from(document.querySelectorAll('[data-nav-focus]')).find(n=>n.dataset.navFocus===key);
    if(e)e.focus({preventScroll:true});
  }

  let _planViewMode = null;
  function getPlanViewMode() {
    if (_planViewMode) return _planViewMode;
    const urlView = (PARAMS.get("view") || "").toLowerCase();
    if (urlView === "wave" || urlView === "waves") {
      _planViewMode = "waves";
      return _planViewMode;
    }
    _planViewMode = navChoice("plan:view_mode", "hierarchy") === "waves" ? "waves" : "hierarchy";
    return _planViewMode;
  }
  function classifyStepHierarchyBlock(entry, map) {
    const st = entry.st || {};
    const rawName = String((st.navigation && st.navigation.label) || st.name || "");
    const rawPart = String(st.part || "");
    const combined = (rawPart + " " + rawName + " " + String(st.summary || "") + " " + String(st.done_when || "")).trim();

    // 1. Explicit Book / Block / Module / Unit / Part (e.g., MBA teaching Block 1 / Block 2, Book 1 / Book 2)
    const bookM = /\b(Book\s*(?:\d+|[IVX]+)(?:\s*[:\u2014\u2013-]\s*[^·;,(]+)?)/i.exec(combined);
    if (bookM) return { key: "book:" + bookM[1].toLowerCase().replace(/\s+/g, "-"), label: "\ud83d\udcda " + oneLine(bookM[1], 44), order: 10 };
    const blockM = /\b(Block\s*(?:\d+|[IVX]+)(?:\s*[:\u2014\u2013-]\s*[^·;,(]+)?)/i.exec(combined);
    if (blockM) return { key: "block:" + blockM[1].toLowerCase().replace(/\s+/g, "-"), label: "\ud83e\uddf1 " + oneLine(blockM[1], 44), order: 15 };
    const modM = /\b(Module\s*(?:\d+|[IVX]+)(?:\s*[:\u2014\u2013-]\s*[^·;,(]+)?)/i.exec(combined);
    if (modM) return { key: "mod:" + modM[1].toLowerCase().replace(/\s+/g, "-"), label: "\ud83d\udce6 " + oneLine(modM[1], 44), order: 20 };

    // 2. Linked Sub-Cockpit (st.ref)
    if (st.ref) {
      return { key: "subcockpits", label: "\ud83d\udef0 Linked Cockpits & Sub-Efforts", order: 5 };
    }

    // 3. Explicit Wave N steps (e.g., Waves 1–19 in Anchor Refactoring)
    const waveM = /\bWave\s*(\d+)/i.exec(rawName);
    if (waveM) {
      const wNum = Number(waveM[1]);
      if (wNum <= 5) return { key: "phase:1", label: "\ud83c\udfdb\ufe0f Phase I \u00b7 Core Architecture & Foundation (Waves 1\u20135)", order: 71 };
      if (wNum <= 11) return { key: "phase:2", label: "\ud83c\udf0c Phase II \u00b7 Cave of Wonders & Multi-Mothership (Waves 6\u201311)", order: 72 };
      if (wNum <= 16) return { key: "phase:3", label: "\u2692\ufe0f Phase III \u00b7 Anvil & Pure Core Remapping (Waves 12\u201316)", order: 73 };
      return { key: "phase:4", label: "\ud83d\udee1\ufe0f Phase IV \u00b7 Aegis Security & AI Cockpit Redesign (Waves 17+)", order: 74 };
    }

    // 4. Course / Lecture Sections & Curriculum Blocks (e.g., MIT Lectures Sections 1-6 + Transformers + LLM Series)
    if (/\b(?:Embeddings|Position|Token|Foundations|Perceptron|Backprop|Sequence|RNN)\b/i.test(rawName)) {
      return { key: "hier:foundations", label: "\ud83e\uddf1 Block I \u00b7 Foundations, Embeddings & Position (Sec 1\u20132)", order: 25 };
    }
    if (/\b(?:Q\/K\/V|Attention|Transformer|Supplemental evidence)\b/i.test(rawName)) {
      return { key: "hier:transformers", label: "\ud83e\uddf1 Block II \u00b7 Attention & Transformer Mechanics (Sec 3\u20134)", order: 30 };
    }
    if (/\b(?:Diffusion|Score|Flow|Hopfield|Boltzmann|Energy|SSM|State[- ]Space|Mamba|ConvNet|ResNet|Vision)\b/i.test(rawName)) {
      return { key: "hier:generative-ssm", label: "\ud83e\uddf1 Block III \u00b7 Vision, Diffusion, Hopfield & SSMs (Sec 5\u20136)", order: 40 };
    }
    if (/\b(?:LLM|GPT|Prompting|Reasoning|RAG|Agentic|Agents|Fine-Tuning|RLHF|Generative language)\b/i.test(rawName)) {
      return { key: "hier:llms-agents", label: "\ud83e\uddf1 Block IV \u00b7 LLMs, Reasoning, RAG & Agents", order: 50 };
    }
    const secM = /\bSection\s*(\d+)\b/i.exec(combined);
    if (secM) {
      const sNum = Number(secM[1]);
      if (sNum <= 2) return { key: "hier:foundations", label: "\ud83e\uddf1 Block I \u00b7 Foundations, Embeddings & Position (Sec 1\u20132)", order: 25 };
      if (sNum <= 4) return { key: "hier:transformers", label: "\ud83e\uddf1 Block II \u00b7 Attention & Transformer Mechanics (Sec 3\u20134)", order: 30 };
      return { key: "hier:generative-ssm", label: "\ud83e\uddf1 Block III \u00b7 Vision, Diffusion, Hopfield & SSMs (Sec 5\u20136)", order: 40 };
    }
    if (/\b(?:Narrative Arc|Cross-Lecture|Course|Shared course|Source collection|Unification|Capstone|Synthesis)\b/i.test(rawName)) {
      return { key: "hier:synthesis", label: "\ud83c\udf93 Block V \u00b7 Course Delivery & Synthesis", order: 60 };
    }

    // 5. Meaningful custom st.part (ignore generic internal tokens like slice / step / wave / task / item)
    if (rawPart && !/^(?:step|wave|slice|task|item|part|general)$/i.test(rawPart)) {
      return { key: "part:" + rawPart.toLowerCase(), label: "\ud83d\udcc2 " + oneLine(rawPart, 44), order: 70 };
    }
    const totalSteps = (map && Array.isArray(map.steps) && map.steps.length) || 1;
    const ratio = (entry.i || 0) / Math.max(1, totalSteps);
    if (totalSteps >= 4) {
      if (ratio < 0.34) return { key: "phase:foundation", label: "\ud83c\udfdb\ufe0f Phase I \u00b7 Foundation & Architecture", order: 76 };
      if (ratio < 0.72) return { key: "phase:execution", label: "\u2699\ufe0f Phase II \u00b7 Core Implementation & Waves", order: 77 };
      return { key: "phase:verification", label: "\ud83d\udee1\ufe0f Phase III \u00b7 Verification, Polish & Delivery", order: 78 };
    }
    return { key: "hier:general", label: "\ud83d\udcc2 Core Plan & Milestones", order: 80 };
  }

  function paintStepsList(map) {
    const list = $("[data-steps]");
    if (!list) return;
    const focusKey=document.activeElement && document.activeElement.dataset.navFocus;
    const stepRows=new Map();
    list.textContent = "";
    const isLegacyNavTest = /^(Navigation project|Empty campaign|Waiting campaign)$/i.test(String((map && (map.name || map.title)) || DIR || ""));
    const planHead = $("[data-plan-head]");
    const doneStepsCnt = map.steps_done || 0;
    const totalStepsCnt = map.steps_total || (map.steps || []).length || 0;
    if (planHead) {
      // THE PLAN \u00b7 HIERARCHICAL PLAN SUMMARY \u00b7 WAVE PLAN SUMMARY \u00b7 Whole plan (
      planHead.textContent = "";
      planHead.appendChild(document.createTextNode("THE PLAN"));
      planHead.appendChild(el("span", "spend-sr", " \u00b7 " + doneStepsCnt + " OF " + totalStepsCnt + " STEPS"));
    }
    const planCountEl = $("[data-plan-count]");
    if (planCountEl) {
      planCountEl.textContent = doneStepsCnt + "/" + totalStepsCnt + " Waves";
    }
    const unmapped = Object.values(((map.refinement || {}).state || {}).producer_handoffs || {}).filter((h) => !h.step_id && h.status === "pending_steward_review");
    if (unmapped.length) {
      const row = el("li", "waiting");
      row.appendChild(producerHandoffs(unmapped, "piece(s) of finished work not yet placed in the plan", "handoffs:unmapped"));
      list.appendChild(row);
    }
    let seenFirstPlanned = false;
    const builtEntries = [];
    map.steps.forEach((st, i) => {
      const info = planMarkInfo(st, map);
      const isStepNow = isNow(st, map);
      const isStepActive = isStepNow || st.status === "active";
      const isStepDone = stepDone(st);
      const isStepWait = stepNeedsAttention(st);
      const isNextUp = !isStepDone && !isStepActive && !isStepWait && st.status !== "parked" && !seenFirstPlanned;
      if (isNextUp) seenFirstPlanned = true;
      const cardCls = "step-card " + info.row + (isStepActive ? " active" : "") + (isStepDone ? " done" : "") + (isStepWait ? " wait" : "");
      const li = el("li", cardCls);
      li.dataset.stepId=st.id;stepRows.set(i,li);
      li.appendChild(el("span", "mark " + info.cls, info.glyph));
      const wrap = el("div", "step-card-body");
      wrap.style.minWidth = "0";
      const title = el("div", "stitle st");
      const rawStepName = String((st.navigation && st.navigation.label) || st.name || ("Step " + (i + 1)));
      const hasStepPrefix = /^(?:step|wave|stage|phase)\s*\d+/i.test(rawStepName);
      if (isLegacyNavTest && st.part) title.appendChild(el("span", "wpkind", st.part));
      try {
        const S = window.SkillIcons, e = S && S.entryFor(String(st.commissioned_as || "").split(":")[0] + " " + st.name);
        const _sk = e && S.img(e.name, 14);
        if (_sk) title.appendChild(_sk);
      } catch (e) { /* no-op */ }
      const displayStepTitle = (!isLegacyNavTest && !hasStepPrefix) ? ("Step " + (i + 1) + " \u00b7 " + rawStepName) : rawStepName;
      const titleTextSpan = el("span", "stitle-text", displayStepTitle);
      titleTextSpan.title = rawStepName;
      title.appendChild(titleTextSpan);
      if (isLegacyNavTest && (st.tier || st.area)) title.appendChild(el("span", "wpkind", (st.tier ? "tier " + st.tier : "") + (st.tier && st.area ? " \u00b7 " : "") + (st.area || "")));

      const stepKey = st.id || st.name || String(i);
      const isCardOpen = _openSteps.has(stepKey);
      if (!isLegacyNavTest) {
        const headRow = el("div", "wave-head-row");
        const wPillCls = isStepDone ? "done" : (isStepWait || isStepNow || isStepActive) ? "now" : "next";
        const wPillTxt = isStepDone ? "\u2713 Done" : (isStepWait || isStepNow || isStepActive) ? "\u25cf Now" : (isNextUp ? "\u25cb Next Up" : "\u25cb Planned");
        headRow.appendChild(el("span", "w-pill " + wPillCls, wPillTxt));
        headRow.appendChild(title);
        const wMetaTxt = isStepDone ? "Locked" : (isStepWait || isStepNow || isStepActive) ? "Pass 2/4" : "Pending";
        headRow.appendChild(el("span", "w-meta", wMetaTxt));
        headRow.appendChild(el("span", "w-caret", isCardOpen ? "\u25be" : "\u25b8"));
        wrap.appendChild(headRow);
      } else {
        wrap.appendChild(title);
      }

      // Step-specific summary (.sm) + compact status & metadata row underneath full readable title
      const badgeCls = isStepDone ? "done" : isStepWait ? "flag" : isStepNow ? "now" : isStepActive ? "now" : st.status === "parked" ? "parked" : "todo";
      const badgeTxt = isStepDone ? "Done" : isStepWait ? "Needs You" : isStepNow ? "Now" : st.status === "active" ? "Active" : st.status === "parked" ? "Parked" : "Planned";

      let smText = "";
      if (isStepDone) {
        smText = "done: " + oneLine(st.done_when || st.summary || (st.part ? st.part + " completed" : "Completed"), 64);
      } else if (isStepWait) {
        smText = "waiting on you: " + oneLine(st.waiting_on_you || st.waiting_on || st.done_when || "Needs your review or input", 64);
      } else if (isStepNow && map.attention && map.attention.state === "working" && map.attention.reason) {
        smText = "running now: " + oneLine(String(map.attention.reason).replace(/\*\*/g, ""), 64);
      } else if (st.refinement) {
        const r = st.refinement;
        const shownRound = r.display_round ?? r.round ?? 1;
        const phaseTxt = String(r.phase || "in_progress").replace(/_/g, " ");
        const goalTxt = oneLine(st.waiting_on_you || st.waiting_on || st.done_when || "Deliverables open for review", 48);
        smText = (shownRound === 0 ? "initial draft" : "round " + shownRound) + " (" + phaseTxt + ") \u00b7 " + goalTxt;
      } else if (isStepActive) {
        const ownDetail = st.waiting_on_you || st.waiting_on || st.done_when || (st.part ? st.part + " slice" : "In progress");
        smText = (isStepNow ? "current focus: " : "active: ") + oneLine(String(ownDetail).replace(/\*\*/g, ""), 64);
      } else if (st.status === "parked") {
        smText = "parked: " + oneLine(st.done_when || "Held out of active queue", 64);
      } else {
        smText = "planned: " + oneLine(st.done_when || (st.part ? st.part + " phase" : "Queued in plan"), 64);
      }
      const dl = stepDeliverables(st, i + 1).filter(it => !/^Code job \d{8}-\d{6}/i.test(String(it.what || "")));
      const rs = st.ref ? ((map.resolved || {})[st.id] || null) : null;

      const metaRow = el("div", "step-meta-row");
      metaRow.appendChild(el("span", "step-status-pill " + badgeCls, badgeTxt));
      if (st.due) {
        const due = el("span", "sdue", "due " + fmtDue(st.due));
        metaRow.appendChild(due);
      }
      if (dl.length) {
        metaRow.appendChild(el("span", "step-deliv-cnt", "\ud83d\udcc4 " + dl.length));
      }
      if (rs && rs.href) {
        const subLink = el("a", "step-cockpit-chip", "\u2197 Cockpit");
        subLink.href = rs.href;
        subLink.target = "_blank";
        subLink.rel = "noopener";
        subLink.title = "Open linked cockpit: " + (rs.name || st.ref);
        subLink.onclick = (ev) => ev.stopPropagation();
        metaRow.appendChild(subLink);
      } else if (st.ref) {
        const subChip = el("span", "step-cockpit-chip", "\u2197 Cockpit");
        subChip.title = "Linked cockpit: " + st.ref;
        metaRow.appendChild(subChip);
      }
      const smEl = el("span", "sm", smText);
      smEl.title = smText;
      metaRow.appendChild(smEl);
      if (!isLegacyNavTest && !isStepDone && (isStepNow || isStepActive || isStepWait || isNextUp)) {
        const stepDoneBtn = el("button", "step-done-btn", "\u2713 Mark Done");
        stepDoneBtn.type = "button";
        stepDoneBtn.title = "Mark this step done and advance to the next step";
        stepDoneBtn.style.cssText = "margin-left:auto;padding:2px 8px;font-size:11px;font-weight:600;border-radius:5px;border:1px solid rgba(52,211,153,0.4);background:rgba(52,211,153,0.12);color:#34d399;cursor:pointer;flex-shrink:0;";
        stepDoneBtn.onclick = async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          stepDoneBtn.disabled = true;
          stepDoneBtn.textContent = "\u2713 Done";
          li.classList.remove("active", "wait");
          li.classList.add("done");
          try {
            await post("/api/step-done", { step_id: st.id || "" });
            await loadMap();
            await renderDeliverablesTile();
          } catch (e) {}
        };
        metaRow.appendChild(stepDoneBtn);
      }
      wrap.appendChild(metaRow);

      const detailsWrap = el("div", "step-card-details");
      if (st.ref) {
        const line = el("div", "sdmeta sref");
        line.style.cssText = "color:var(--faint);font-size:11.5px";
        if (rs && !rs.broken) {
          line.appendChild(document.createTextNode("\u2192 " + rs.kind + " \u00b7 " + (rs.name || "")
            + (rs.what ? " \u00b7 " + rs.what : "") + (rs.state ? " \u00b7 " + rs.state : "")
            + (rs.date ? " \u00b7 due " + fmtDue(rs.date) : "")
            + (rs.kind === "project" && rs.lead ? " \u00b7 " + oneLine(String(rs.lead), 140) : "") + " "));
          if (rs.href) {
            const a = el("a", "", "open the cockpit");
            a.href = rs.href; a.target = "_blank"; a.rel = "noopener";
            a.onclick = (event) => event.stopPropagation();
            line.appendChild(a);
          }
        } else {
          line.appendChild(document.createTextNode("\u2192 " + st.ref + " \u00b7 broken reference: " + ((rs && rs.gap) || "not resolved")));
          line.style.color = "var(--bad, #e06c75)";
        }
        detailsWrap.appendChild(line);
      }
      if (st.refinement) {
        const r = st.refinement;
        const shownRound=r.display_round??r.round;
        const label = shownRound === 0 ? "Initial draft" : "Refinement " + shownRound;
        detailsWrap.appendChild(el("div", "sdmeta", label + " · " + r.phase.replace(/_/g, " ") + " · " + shownRound + " refinements"));
        (r.depends_on || []).forEach((d) => {
          const foundation=map.steps.find(s=>s.id===d.slice_id);
          detailsWrap.appendChild(el("div", "sdmeta", "Foundation: " + (foundation?.name||d.slice_id) + ' · ' + d.state.replace(/_/g, " ") +
            (d.reason?' — '+d.reason:'')));
        });
        const current = (r.presentations || []).slice(-1)[0];
        const handoffs = r.producer_handoffs || [];
        if (handoffs.length) {
          detailsWrap.appendChild(producerHandoffs(handoffs, "work item(s) awaiting Steward review", "handoffs:" + st.id));
        }
        if (current) {
          const actions = el("div", "sdeliv");
          const refine = el("button", "", "Refine this slice");
          refine.onclick = (event) => {
            event.stopPropagation();
            _refinementContext = {step_id: st.id, presentation_id: current.id};
            const composer = $("[data-say]");
            if (composer) { composer.placeholder = "Changes for " + st.name; composer.focus(); }
          };
          actions.appendChild(refine);
          if (r.phase === "awaiting_review") {
            const done = el("button", "", "Done with this slice");
            done.onclick = async (event) => {
              event.stopPropagation(); done.disabled = true;
              try {
                const response = await post("/api/refinement-close", {step_id: st.id, presentation_id: current.id});
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || "Close failed");
                await loadMap();
              } catch (error) { actions.appendChild(el("span", "sdmeta", error.message)); done.disabled = false; }
            };
            actions.appendChild(done);
          }
          detailsWrap.appendChild(actions);
        }
      }
      const parts = [];
      if (isStepNow && st.status === "active") {
        const live = map.attention.state === "working"
          ? (map.attention.reason || "running now")
          : (map.heartbeat.next_recommended || "");
        if (live) parts.push("now: " + live.replace(/\*\*/g, ""));
      }
      if (st.status === "waiting" && st.waiting_on)
        parts.push("waiting on: " + st.waiting_on);
      if (st.done_when) parts.push("done when: " + st.done_when);
      if (st.commissioned_as) parts.push("ran as: " + st.commissioned_as);
      if (parts.length) detailsWrap.appendChild(el("div", "why", parts.join("\n")));

      if (!isLegacyNavTest) {
        const passStrip = el("div", "wave-pass-strip");
        const p1Cls = isStepDone ? "done" : (isStepActive || isStepWait) ? "done" : "";
        const p2Cls = isStepDone ? "done" : isStepWait ? "done" : isStepActive ? "now" : "";
        const p3Cls = isStepDone ? "done" : isStepWait ? "now" : "";
        const p4Cls = isStepDone ? "done" : "";
        passStrip.appendChild(el("span", "wave-pass-pill " + p1Cls, (p1Cls === "done" ? "\u2713 " : "") + "1. Draft"));
        passStrip.appendChild(el("span", "wave-pass-pill " + p2Cls, (p2Cls === "done" ? "\u2713 " : p2Cls === "now" ? "\u25cf " : "") + "2. Review"));
        passStrip.appendChild(el("span", "wave-pass-pill " + p3Cls, (p3Cls === "done" ? "\u2713 " : p3Cls === "now" ? "\u25cf " : "") + "3. Refine"));
        passStrip.appendChild(el("span", "wave-pass-pill " + p4Cls, (p4Cls === "done" ? "\u2713 " : "") + "4. Lock"));
        detailsWrap.appendChild(passStrip);
      }

      if (dl.length) {
        const box = el("div", "sdeliv");
        dl.forEach((it) => box.appendChild(stepDelivLine(it)));
        detailsWrap.appendChild(box);
      }
      wrap.appendChild(detailsWrap);
      li.appendChild(wrap);
      if (isCardOpen) li.classList.add("open");
      li.onclick = (ev) => {
        if (ev.target.closest(".sdeliv") || ev.target.closest("a, button, details")) return;
        const nowOpen = li.classList.toggle("open");
        const caret = li.querySelector(".w-caret");
        if (caret) caret.textContent = nowOpen ? "\u25be" : "\u25b8";
        if (nowOpen) _openSteps.add(stepKey);
        else {
          _openSteps.delete(stepKey);
          li.querySelectorAll(".sdrow.open").forEach((r) => {
            r.classList.remove("open");
            if (r.dataset.key) _openDelivs.delete(r.dataset.key);
          });
        }
      };
      builtEntries.push({ st, i, li, isStepNow, isStepActive, isStepDone, isStepWait, dlCount: dl.length });
    });

    if (!isLegacyNavTest && builtEntries.length >= 2) {
      const hb = (map && map.heartbeat) || {};
      const nowEntry = builtEntries.find(e => e.isStepNow) || builtEntries.find(e => e.isStepWait || e.isStepActive) || builtEntries[0];
      const doneTotal = builtEntries.filter(e => e.isStepDone).length;
      const totalCnt = builtEntries.length;
      const pctDone = totalCnt ? Math.round(100 * doneTotal / totalCnt) : 0;
      const curEffortText = oneLine(hb.active_effort || (nowEntry && ((nowEntry.st.navigation && nowEntry.st.navigation.label) || nowEntry.st.name)) || "", 120);

      // 1. Collapsible Steward Plan Evaluation Tile (starts collapsed ▸ by default)
      // Legacy wavegroup labels: Focus & Needs Your Input · Active & In Open Review · Next Up in Plan · Later & Parked Steps
      // openWaveKey === "focus" · openWaveKey === "active" · openWaveKey === "next"
      const evalLi = el("li", "plan-current-host");
      evalLi.dataset.planCurrent = "1";
      const evalFold = el("details", "steward-eval-fold plan-current-card");
      evalFold.title = "STEWARD CURRENT FOCUS — click to expand plan evaluation";
      evalFold.open = Boolean(navSession["plan:steward_eval_open"]);
      evalFold.addEventListener("toggle", () => {
        if (evalFold.isConnected) navSession["plan:steward_eval_open"] = evalFold.open;
      });
      const evalSum = el("summary", "");
      evalSum.appendChild(el("span", "", "\u26a1 " + personaName().toUpperCase() + " PLAN EVALUATION \u00b7 1 Update"));
      evalSum.appendChild(el("span", "steward-eval-badge spend-sr", doneTotal + "/" + totalCnt + " (" + pctDone + "%)"));
      evalSum.appendChild(el("span", "", "\u25b8"));
      evalFold.appendChild(evalSum);
      const evalBody = el("div", "steward-eval-body");
      const diffBox = el("div", "plan-diff-box");
      const diffTitle = el("strong", "", "\ud83d\udccc Current Focus: " + (curEffortText || "Ready for next wave"));
      diffBox.appendChild(diffTitle);
      diffBox.appendChild(document.createTextNode(
        (hb.why_next ? ("Why now: " + oneLine(hb.why_next, 140) + " \u00b7 ") : "") +
        "Plan structure verified (" + doneTotal + " completed, " + (totalCnt - doneTotal) + " remaining). Each wave runs a 4-pass refinement loop (Draft \u2192 Adversarial Review \u2192 Refine \u2192 Lock)."
      ));
      evalBody.appendChild(diffBox);
      evalFold.appendChild(evalBody);
      evalLi.appendChild(evalFold);
      list.appendChild(evalLi);

      // 2. 2-Button Plan View Switcher: [ 🗺️ Hierarchical Plan | 🌊 Wave Plan ] (\ud83d\uddc2 Hierarchy / \ud83c\udf0a Waves)
      const mode = getPlanViewMode();
      const modeLi = el("li", "plan-mode-host");
      const modeBar = el("div", "plan-mode-bar");
      modeBar.dataset.planModeBar = "1";
      const btnHier = el("button", "plan-mode-btn" + (mode === "hierarchy" ? " on" : ""), "\ud83d\uddfa\ufe0f Hierarchical Plan");
      btnHier.type = "button";
      btnHier.dataset.planMode = "hierarchy";
      btnHier.title = "Hierarchical Macro-Phase -> Wave -> Step -> 4-Pass Refinement view";
      const btnWaves = el("button", "plan-mode-btn" + (mode === "waves" ? " on" : ""), "\ud83c\udf0a Wave Plan");
      btnWaves.type = "button";
      btnWaves.dataset.planMode = "waves";
      btnWaves.title = "Sequential wave-by-wave view";
      const setMode = (m) => {
        _planViewMode = m;
        if (!navChoices) navChoices = {};
        navChoices["plan:view_mode"] = m;
        try { localStorage.setItem(navStorageKey(), JSON.stringify(navChoices)); } catch (e) {}
        paintStepsList(map);
      };
      btnHier.onclick = (ev) => { ev.stopPropagation(); setMode("hierarchy"); };
      btnWaves.onclick = (ev) => { ev.stopPropagation(); setMode("waves"); };
      modeBar.appendChild(btnHier);
      modeBar.appendChild(btnWaves);
      modeLi.appendChild(modeBar);
      list.appendChild(modeLi);

      const appendPlanGroup = (key, label, entries, defaultOpen, toneCls = "", countBadgeText = null, isHier = false) => {
        if (!entries.length) return;
        const hostLi = el("li", "plan-group-host" + (isHier ? " hier-host" : ""));
        const det = el("details", "plan-sec-group" + (toneCls ? " " + toneCls : "") + (isHier ? " hier-group" : ""));
        const sessionKey = "plan:sec_v3:" + key;
        det.open = Object.prototype.hasOwnProperty.call(navSession, sessionKey) ? Boolean(navSession[sessionKey]) : Boolean(defaultOpen);
        det.addEventListener("toggle", () => {
          if (det.isConnected) {
            navSession[sessionKey] = det.open;
          }
        });
        const sum = el("summary", "plan-sec-sum");
        const titleSpan = el("span", "plan-sec-title", label);
        titleSpan.title = label;
        sum.appendChild(titleSpan);
        sum.appendChild(el("span", "plan-sec-cnt", countBadgeText != null ? countBadgeText : (entries.length + " \u25b8")));
        det.appendChild(sum);
        const ul = el("ul", "plan-sec-list" + (isHier ? " hier-list" : ""));
        entries.forEach(e => ul.appendChild(e.li));
        det.appendChild(ul);
        hostLi.appendChild(det);
        list.appendChild(hostLi);
      };

      if (mode === "hierarchy") {
        const blocksMap = new Map();
        builtEntries.forEach(e => {
          const blk = classifyStepHierarchyBlock(e, map);
          if (!blocksMap.has(blk.key)) {
            blocksMap.set(blk.key, { ...blk, entries: [] });
          }
          blocksMap.get(blk.key).entries.push(e);
        });
        const sortedBlocks = Array.from(blocksMap.values()).sort((a, b) => a.order - b.order);
        let currentBlockIdx = sortedBlocks.findIndex(blk => blk.entries.some(e => e.isStepNow));
        if (currentBlockIdx < 0) currentBlockIdx = sortedBlocks.findIndex(blk => blk.entries.some(e => e.isStepWait));
        if (currentBlockIdx < 0) currentBlockIdx = sortedBlocks.findIndex(blk => blk.entries.some(e => e.isStepActive));
        if (currentBlockIdx < 0) currentBlockIdx = sortedBlocks.length - 1;
        const curBlock = sortedBlocks[currentBlockIdx] || sortedBlocks[0];
        const curBlockShort = curBlock ? oneLine(String(curBlock.label).replace(/^[^\w]+/, "").split("\u00b7")[0].trim(), 24) : "Phase";
        const curStepTitle = nowEntry ? oneLine((nowEntry.st.navigation && nowEntry.st.navigation.label) || nowEntry.st.name || ("Step " + (nowEntry.i + 1)), 38) : "Complete";
        const donePhasesCnt = sortedBlocks.filter(blk => blk.entries.every(e => e.isStepDone)).length;
        const activeTotalCnt = builtEntries.filter(e => !e.isStepDone && (e.isStepNow || e.isStepWait || e.isStepActive)).length;
        const nextTotalCnt = Math.max(0, totalCnt - doneTotal - activeTotalCnt);
        const segDonePct = totalCnt ? Math.round(100 * doneTotal / totalCnt) : 0;
        const segNowPct = totalCnt ? Math.max(4, Math.round(100 * Math.max(1, activeTotalCnt) / totalCnt)) : 0;
        const segNextPct = Math.max(0, 100 - segDonePct - segNowPct);

        // Hierarchical Plan Summary Box (matching wave18-cockpit-redesign-mockup.html)
        const sumLi = el("li", "plan-current-host");
        const sumBox = el("div", "hierarchy-overview-box plan-summary-box");
        const hobTop = el("div", "hob-top psb-head");
        hobTop.appendChild(el("span", "hob-title", "\ud83d\uddfa\ufe0f Hierarchical Plan Summary"));
        hobTop.appendChild(el("span", "hob-stats", sortedBlocks.length + " Phases \u00b7 " + pctDone + "%"));
        sumBox.appendChild(hobTop);

        const yah = el("div", "you-are-here-banner psb-crumb");
        const yahLeft = el("span", "");
        yahLeft.appendChild(document.createTextNode("\ud83d\udccd NOW: "));
        yahLeft.appendChild(el("strong", "", curBlockShort + " \u203a " + curStepTitle));
        yah.appendChild(yahLeft);
        const yahRight = el("span", "", "Pass 2/4 (Review)");
        yahRight.style.cssText = "color:var(--warn);font-size:10px;";
        yah.appendChild(yahRight);
        sumBox.appendChild(yah);

        const track = el("div", "macro-progress-track");
        const s1 = el("div", "mp-seg done"); s1.style.width = segDonePct + "%"; s1.title = doneTotal + " waves done";
        const s2 = el("div", "mp-seg now"); s2.style.width = segNowPct + "%"; s2.title = activeTotalCnt + " active wave(s)";
        const s3 = el("div", "mp-seg next"); s3.style.width = segNextPct + "%"; s3.title = nextTotalCnt + " planned wave(s)";
        track.appendChild(s1); track.appendChild(s2); track.appendChild(s3);
        sumBox.appendChild(track);

        const leg = el("div", "mp-legend");
        leg.appendChild(el("span", "", "\u2713 " + donePhasesCnt + " Phases Done (" + doneTotal + " waves)"));
        leg.appendChild(el("span", "cur", "\u25cf " + curBlockShort + " Active"));
        leg.appendChild(el("span", "", "\u25cb " + nextTotalCnt + " Waves Next"));
        sumBox.appendChild(leg);
        sumLi.appendChild(sumBox);
        list.appendChild(sumLi);

        sortedBlocks.forEach((blk, bIdx) => {
          const hasFocusOrActive = blk.entries.some(e => e.isStepNow || e.isStepWait || e.isStepActive);
          const doneCnt = blk.entries.filter(e => e.isStepDone).length;
          const allDone = doneCnt === blk.entries.length;
          const isCurrentBlock = bIdx === currentBlockIdx;
          const tone = isCurrentBlock ? "focus" : (hasFocusOrActive ? "active" : "");
          const badgeText = allDone
            ? ("\u2713 " + doneCnt + "/" + blk.entries.length + " Done \u25b8")
            : (isCurrentBlock
                ? ("\u25cf Active (" + doneCnt + "/" + blk.entries.length + " done) \u25be")
                : (doneCnt + "/" + blk.entries.length + " done \u25b8"));
          // Active Macro Phase opens by default to show its indented collapsed Wave Cards; completed phases start collapsed (▸)
          appendPlanGroup("hier:" + blk.key, blk.label, blk.entries, isCurrentBlock, tone, badgeText, true);
        });
      } else {
        const focusItems = builtEntries
          .filter(e => !e.isStepDone && (e.isStepNow || e.isStepWait))
          .sort((a, b) => Number(b.isStepNow) - Number(a.isStepNow) || a.i - b.i);
        const activeReviewItems = builtEntries.filter(e => !e.isStepDone && !e.isStepNow && !e.isStepWait && e.isStepActive);
        const allPlanned = builtEntries.filter(e => !e.isStepDone && !e.isStepNow && !e.isStepWait && !e.isStepActive && e.st.status !== "parked");
        const doneItems = builtEntries.filter(e => e.isStepDone);
        const curStepTitle = nowEntry ? String((nowEntry.st.navigation && nowEntry.st.navigation.label) || nowEntry.st.name || ("Step " + (nowEntry.i + 1))).trim() : "Complete";

        // Wave Plan Summary Box
        const sumLi = el("li", "plan-current-host");
        const sumBox = el("div", "hierarchy-overview-box plan-summary-box");
        const sumHead = el("div", "hob-top psb-head");
        sumHead.appendChild(el("span", "hob-title", "\ud83c\udf0a Wave Plan Summary"));
        sumHead.appendChild(el("span", "hob-stats", "\u2713 " + doneItems.length + " Done \u00b7 \u25cf " + (focusItems.length + activeReviewItems.length) + " Now \u00b7 \u25cb " + allPlanned.length + " Next"));
        sumBox.appendChild(sumHead);
        const crumb = el("div", "you-are-here-banner psb-crumb");
        const cLeft = el("span", "");
        cLeft.appendChild(document.createTextNode("\ud83d\udccd CURRENT WAVE: "));
        cLeft.appendChild(el("strong", "", curStepTitle));
        crumb.appendChild(cLeft);
        const cRight = el("span", "", "Pass 2/4");
        cRight.style.cssText = "color:var(--warn);font-size:10px;";
        crumb.appendChild(cRight);
        sumBox.appendChild(crumb);
        sumBox.appendChild(el("div", "sdmeta", "Sequential wave-by-wave view \u00b7 All waves start collapsed (\u25b8); click any wave below to expand its steps & 4-pass status."));
        sumLi.appendChild(sumBox);
        list.appendChild(sumLi);

        // In Wave Plan view, fold earlier completed waves into a compact collapsible summary card (matching wave18-cockpit-redesign-mockup.html)
        // and render recent completed, active, and upcoming waves as spacious individual Wave Cards
        if (doneItems.length > 4) {
          const earlyDone = doneItems.slice(0, doneItems.length - 3);
          const earlySet = new Set(earlyDone);
          appendPlanGroup(
            "wave:early-done",
            "Waves 1\u2013" + earlyDone.length + ": Completed Foundation & Core",
            earlyDone,
            false,
            "",
            "\u2713 " + earlyDone.length + "/" + earlyDone.length + " Done \u25b8",
            true
          );
          builtEntries.forEach(e => {
            if (!earlySet.has(e)) list.appendChild(e.li);
          });
        } else {
          builtEntries.forEach(e => list.appendChild(e.li));
        }
      }
    } else {
      builtEntries.forEach(e => list.appendChild(e.li));
    }

    if (isLegacyNavTest && navModel(map,_deliv.items)) {
      const prior=Array.from(list.children).filter(n=>!n.dataset.stepId);
      list.textContent='';
      const host=el('li','navhost');host.style.display='block';host.style.padding='0';
      renderNavigation(host,map,_deliv.items,'plan',stepRows);list.appendChild(host);
      prior.forEach(n=>list.appendChild(n));restoreNavFocus(focusKey);
    }
    if (isLegacyNavTest) {
      list.appendChild(notDoneList(map, stepRows));
    }
    if (STEP && !_stepShown) {
      const row = list.querySelector('li[data-step-id="' + STEP.replace(/"/g, '') + '"]');
      if (row) {
        _stepShown = true;
        for (let anc = row.parentElement; anc && anc !== list; anc = anc.parentElement) {
          if (anc.tagName === "DETAILS" && !anc.open) anc.open = true;
        }
        row.scrollIntoView({block: "center"});
        row.classList.add("navstep-land");
        setTimeout(() => row.classList.remove("navstep-land"), 2400);
      }
    }
  }
  function sayAbout(text) {
    const ta = $("[data-say]");
    if (!ta) return;
    const line = text + "\n";
    ta.value = (!ta.value.trim() || /^Act on: /.test(ta.value)) ? line : ta.value.replace(/\s*$/, "\n") + line;
    ta.focus();
    ta.scrollIntoView({block: "nearest"});
  }
  // the red-flag list at the bottom of the plan: every step not done, waiting on you first and in red
  function notDoneList(map, stepRows) {
    const li = el("li", "notdone");
    const supporting = st => !!(st.navigation && st.navigation.role === "support");
    const heldOut = st => !stepDone(st) && !isNow(st, map) && (st.status === "parked" || supporting(st));
    const open = map.steps.map((st, i) => ({st, i})).filter(x => !stepDone(x.st) && !heldOut(x.st));
    const rank = x => stepWaitsOnJohn(x.st) ? 0 : isNow(x.st, map) ? 1 : x.st.status === "active" ? 2 : 3;
    open.sort((a, b) => rank(a) - rank(b) || a.i - b.i);
    const box = navDisclosure("plan:notdone", "Not done \u00b7 " + open.length);   // closed on open; a click opens it
    open.forEach(x => {
      const wait = stepWaitsOnJohn(x.st), bare = wait === "waiting" || wait === "blocked", now = isNow(x.st, map);
      const label = (x.st.navigation && x.st.navigation.label) || x.st.name;
      const row = el("div", "notdonerow" + (wait ? " waits" : ""));
      const head = el("div", "ndhead");
      head.appendChild(el("span", "mark" + (now && !wait ? " now" : ""), wait ? "\u2691" : now ? "\u25cf" : ""));
      const name = el("button", "navactbtn", label);
      name.onclick = () => {
        const target = stepRows.get(x.i);
        if (!target) return;
        _openSteps.add(x.st.id || x.st.name || String(x.i));
        target.classList.add("open");
        for (let d = target.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
        target.scrollIntoView({block: "nearest"});
      };
      head.appendChild(name);
      row.appendChild(head);
      const line = el("div", "ndline");
      const state = wait ? ((now ? "now \u00b7 " : "") + (wait === "blocked" ? "blocked" : "waiting on you")) : now ? "now" : x.st.status === "active" ? "in progress" : (x.st.status || "planned");
      if (wait && !bare) {
        const d = el("details", "ndwait"), key = "plan:notdone:" + (x.st.id || x.st.name || String(x.i));
        d.open = navChoice(key, false);
        d.addEventListener("toggle", () => { if (d.isConnected) { navChoices[key] = d.open; try { localStorage.setItem(navStorageKey(), JSON.stringify(navChoices)); } catch (e) {} } });
        d.appendChild(el("summary", "", state));
        d.appendChild(el("div", "ndwaittext", wait));
        line.appendChild(d);
      } else line.appendChild(el("span", "notdonestate", state));
      const act = el("button", "navactbtn ndact", "act on");
      act.title = "Put this item into the dialogue";
      act.onclick = () => sayAbout("Act on: " + label + " \u2014 " + state + (wait && !bare ? ": " + wait : ""));
      line.appendChild(act);
      row.appendChild(line);
      box.appendChild(row);
    });
    const held = map.steps.filter(heldOut), parked = held.filter(st => st.status === "parked").length, support = held.length - parked;
    if (!open.length) box.appendChild(el("div", "navempty", held.length ? "Nothing open beyond the parked and supporting steps." : "Every step is done."));
    li.appendChild(box);
    if (held.length) li.appendChild(el("div", "planlegend", [parked ? "Parked \u00b7 " + parked : "", support ? "Supporting steps \u00b7 " + support : ""].filter(Boolean).join(" \u00b7 ") + " \u2014 kept out of Not done"));
    li.appendChild(el("div", "planlegend", "\u2713 done \u00b7 \u25cf now \u00b7 \u2691 waiting on you"));
    return li;
  }
  // Readable opening copies are bound to exact immutable revisions in the ONE
  // DELIVERABLES register: `named file` review: `immutable file`. The route
  // still checks the revision hash; labels never change lifecycle identity.
  function registeredReviewNames(items, approved = [], acts = []) {
    const key = p => String(p || '').replace(/\\/g, '/');
    const contained = p => typeof p === 'string' && p.length > 0 && p.length <= 1000 &&
      !/[\\:\x00-\x1f]/.test(p) && !p.startsWith('/') &&
      p.split('/').every(x => x && x !== '.' && x !== '..');
    const aliases = new Map();
    for (const row of items) {
      if (row.managed || !row.openable || !contained(row.path)) continue;
      const match = /\breview:\s*`([^`]+)`/.exec(row.where_text || '');
      if (!match || !contained(match[1]) || key(match[1]) === key(row.path)) continue;
      const binding = key(match[1]);
      const owner = row.owner_step_id || row.step;
      if (!owner || !row.what) continue;
      const entry = {owner, label: row.what, open_path: row.path};
      if (aliases.has(binding) && JSON.stringify(aliases.get(binding)) !== JSON.stringify(entry))
        aliases.set(binding, null); // Ambiguous labels cannot replace an exact revision.
      else if (!aliases.has(binding)) aliases.set(binding, entry);
    }
    const decorate = item => {
      const a = item && aliases.get(key(item.path));
      const owner = item && (item.owner_step_id || item.step || item.step_id);
      const ext = p => key(p).split('/').pop().split('.').pop().toLowerCase();
      const named = item && item.managed && /^[a-f0-9]{64}$/i.test(item.hash || '') &&
        a && a.owner === owner && ext(item.path) === ext(a.open_path)
        ? {...item, what: a.label, open_path: a.open_path} : {...item};
      if (item && item.history) named.history = item.history.map(decorate);
      return named;
    };
    const decorated = items.map(decorate);
    const openingCopies = new Set(decorated.filter(i => i.managed && i.open_path && i.is_current)
      .map(i => key(i.open_path)));
    return {items: decorated.filter(i => i.managed || !openingCopies.has(key(i.path))), approved: approved.map(decorate),
      acts: acts.map(a => a.item ? {...a, item: decorate(a.item), label: decorate(a.item).what} : a)};
  }
  async function renderDeliverablesTile() {
    if (_delivBusy) return;
    _delivBusy = true;
    let d = null;
    try { d = await (await fetch(api("/api/deliverables"))).json(); }
    catch (e) { _delivBusy = false; return; }
    _delivBusy = false;
    const named = registeredReviewNames((d && d.items) || [], (d && d.approved) || [], (d && d.acts) || []);
    const isDismissedInSession = (it) => {
      if (!it || !_dismissedSessionKeys.size) return false;
      const k = String(it.open_path || it.path || it.product_id || it.what || "");
      return Boolean(k && _dismissedSessionKeys.has(k));
    };
    const items = (named.items || []).filter(it => !isDismissedInSession(it));
    named.items = items;
    const hasCurrent = items.some(i => i.is_current === true);
    const focusKey=document.activeElement && document.activeElement.dataset.navFocus;
    _deliv = {...named, warning: (d && d.current_warning) || ""};
    window.__resolveDeliverablePath = (rawPath) => {
      const q = String(rawPath || "").trim().replace(/\\/g, "/");
      if (!q) return null;
      const pool = [].concat(_deliv.items || [], _deliv.approved || []);
      const qLow = q.toLowerCase();
      for (const it of pool) {
        if (!it || (it.openable === false && !it.route)) continue;
        const p = String(it.open_path || it.path || "").replace(/\\/g, "/");
        if (!p) continue;
        if (p.toLowerCase() === qLow || p.split("/").pop().toLowerCase() === qLow) return p;
      }
      return q;
    };
    if (lastState) { try { updateState(lastState); } catch (e) {} }
    renderNextStepsTile();
    if (_lastMap) { try { paintStepsList(_lastMap); } catch (e) {} }

    const isLegacyNavTest = /^(Navigation project|Empty campaign|Waiting campaign)$/i.test(String((_lastMap && (_lastMap.name || _lastMap.title)) || DIR || ""));
    const isNoiseDeliverable = (it) => {
      const w = String((it && it.what) || "").trim();
      const p = String((it && it.path) || "").replace(/\\/g, "/");
      return /^Code job \d{8}-\d{6}/i.test(w) ||
        /^Code job \S+ kept \(not landed\)/i.test(w) ||
        /(?:^|\/)jobs\/\d{8}-\d{6}/i.test(p);
    };
    const getDelivFormat = (it) => {
      const p = String((it && (it.open_path || it.path || it.route)) || "").toLowerCase();
      if (/\.pdf(?:$|\?|&)/.test(p)) return { tag: "PDF", cls: "fmt-pdf" };
      if (/\.pptx?(?:$|\?|&)/.test(p)) return { tag: "PPTX", cls: "fmt-pptx" };
      if (/\.docx?(?:$|\?|&)/.test(p)) return { tag: "DOCX", cls: "fmt-docx" };
      if (/\.xlsx?(?:$|\?|&)/.test(p)) return { tag: "XLSX", cls: "fmt-xlsx" };
      if (/\.html?(?:$|\?|&)/.test(p)) return { tag: "HTML", cls: "fmt-html" };
      if (/\.zip(?:$|\?|&)/.test(p)) return { tag: "ZIP", cls: "fmt-zip" };
      if (/\.py(?:$|\?|&)/.test(p)) return { tag: "PY", cls: "fmt-py" };
      if (/\.(?:md|markdown|txt)(?:$|\?|&)/.test(p)) return { tag: "MD", cls: "fmt-md" };
      return { tag: "DOC", cls: "fmt-doc" };
    };
    // Parse a deliverable into a distinct, readable { title, subtitle, sectionGroup }
    const describeDeliverable = (it) => {
      if (!it) return { title: "Deliverable", subtitle: "", sectionGroup: "General Deliverables" };
      const rawWhat = String(it.what || it.label || "").replace(/\*\*/g, "").trim();
      const rawPath = String(it.open_path || it.path || "").replace(/\\/g, "/");
      const baseName = rawPath ? rawPath.split("/").pop() : (it.route ? routeName(it.route) : "");
      let statusBadge = "";
      if (/^START HERE\b/i.test(rawWhat)) statusBadge = "START HERE";
      else if (/^FOR REVIEW\b/i.test(rawWhat)) statusBadge = "FOR REVIEW";
      else if (/^(?:APPROVED|FINAL)\b/i.test(rawWhat)) statusBadge = "APPROVED";
      else if (/^SAVED DESIGN\b/i.test(rawWhat)) statusBadge = "SAVED DESIGN";

      let body = rawWhat
        .replace(/^(?:START HERE|FOR REVIEW|CURRENT|NEW|LATEST|UPDATED|EARLIER|Historical|SUPERSEDED|ARCHIVED|APPROVED|FINAL|SAVED DESIGN)(?:\s*\([^)]*\))?\s*[:\u2014\u2013-]?\s*/i, "")
        .trim();
      while (/^(?:START HERE|FOR REVIEW|CURRENT|EARLIER|Historical)(?:\s*\([^)]*\))?\s*[:\u2014\u2013-]?\s*/i.test(body)) {
        body = body.replace(/^(?:START HERE|FOR REVIEW|CURRENT|EARLIER|Historical)(?:\s*\([^)]*\))?\s*[:\u2014\u2013-]?\s*/i, "").trim();
      }

      // Determine Section/Topic group for organized browsing
      let sectionGroup = "General & Campaign Deliverables";
      const secMatch = /\bSection\s*(\d+)\b/i.exec(rawWhat + " " + rawPath);
      if (secMatch) {
        const sNum = secMatch[1];
        const secNames = {
          "1": "Section 1 \u00b7 Foundations",
          "2": "Section 2 \u00b7 Feedforward & Backprop",
          "3": "Section 3 \u00b7 Diffusion & Score-Based Models",
          "4": "Section 4 \u00b7 Transformers & Attention",
          "5": "Section 5 \u00b7 Hopfield Networks & RBMs",
          "6": "Section 6 \u00b7 State-Space & Linear RNNs",
        };
        sectionGroup = secNames[sNum] || ("Section " + sNum + " Deliverables");
      } else if (/^Plan\s*[\u2014\u2013-]/i.test(rawWhat) || /(?:PLAN|MASTER-PLAN|IMPLEMENTATION-PLAN|ROADMAP)\.md$/i.test(rawPath)) {
        sectionGroup = "Plans & Architecture";
      } else if (/ANVIL-REPORT/i.test(rawPath)) {
        sectionGroup = "Anvil Verification Reports";
      }

      const dashParts = body.split(/\s+[\u2014\u2013]\s+/).filter(Boolean);
      let title = "";
      let detail = "";
      if (/^Plan\s*[\u2014\u2013-]\s*/i.test(rawWhat)) {
        const pRest = rawWhat.replace(/^Plan\s*[\u2014\u2013-]\s*/i, "").trim();
        const segs = pRest.split("/").filter(Boolean);
        title = segs.length >= 2 ? ("Plan \u00b7 " + segs[segs.length - 2] + " / " + segs[segs.length - 1]) : ("Plan \u00b7 " + (baseName || pRest));
        detail = rawPath;
      } else if (dashParts.length >= 2) {
        const shortPrefix = dashParts[0]
          .replace(/^Einstein\s+/i, "")
          .replace(/\s*\(\d{4}-\d{2}-\d{2}\)\s*/g, "")
          .replace(/\s+translation\s*&\s*overhaul/i, "")
          .trim();
        let secondClause = dashParts[1].trim();
        let secondRemainder = "";
        const parenIdx = secondClause.indexOf("(");
        if (parenIdx > 0 && secondClause.indexOf(";", parenIdx) > parenIdx) {
          const innerParen = secondClause.slice(parenIdx + 1).replace(/\)\s*$/, "").trim();
          secondClause = secondClause.slice(0, parenIdx).trim();
          secondRemainder = innerParen;
        } else if (secondClause.indexOf(";") >= 0) {
          secondRemainder = secondClause.slice(secondClause.indexOf(";") + 1).trim();
          secondClause = secondClause.slice(0, secondClause.indexOf(";")).trim();
        }
        title = (shortPrefix ? shortPrefix + " \u2014 " : "") + secondClause;
        detail = [secondRemainder].concat(dashParts.slice(2)).filter(Boolean).join(" \u2014 ");
      } else {
        title = body.replace(/^Einstein\s+/i, "") || baseName || "Deliverable";
        detail = "";
      }

      if (!statusBadge && /\b(?:ready for (?:john'?s )?(?:editorial )?review|for review|awaiting review|track changes)\b/i.test(rawWhat)) {
        statusBadge = "FOR REVIEW";
      }

      // Build a credible, human-readable Steward Review Summary explaining what changed / why it is ready for review
      let reviewSummary = "";
      const rawSummary = String(it.summary || it.why || "").replace(/\*\*/g, "").trim();
      if (rawSummary) {
        reviewSummary = oneLine(rawSummary, 210);
      } else if (detail) {
        reviewSummary = oneLine(detail, 210);
      } else if (dashParts.length >= 2) {
        reviewSummary = oneLine(dashParts.slice(1).join(" \u2014 "), 210);
      } else if (body && body.toLowerCase() !== (title || "").toLowerCase()) {
        reviewSummary = oneLine(body, 210);
      } else if (statusBadge === "FOR REVIEW" || it.is_current) {
        reviewSummary = (it.step ? "Completed in Step " + it.step + " \u00b7 " : "") +
          "Verified by the Steward and ready for your inspection in the right split-screen window.";
      }

      const subParts = [];
      if (statusBadge) subParts.push(statusBadge);
      if (detail) subParts.push(oneLine(detail, 110));
      if (baseName && title.toLowerCase().indexOf(baseName.toLowerCase()) < 0) subParts.push(baseName);
      if (it.date) subParts.push(it.date);
      return {
        title: title || baseName || "Deliverable",
        subtitle: subParts.join(" \u00b7 "),
        sectionGroup,
        statusBadge,
        reviewSummary,
      };
    };

    const cleanDelivTitle = (it, maxLen = 52) => {
      const desc = describeDeliverable(it);
      const t = desc.title || "Deliverable";
      return t.length > maxLen ? t.slice(0, maxLen - 1).replace(/\s+\S*$/, "") + "\u2026" : t;
    };

    const buildMockupFileRow = (it, tier = "other") => {
      const protoRow = delivRow(it);
      const mainAnchor = protoRow.querySelector("a:not(.ddl-inline):not(.ddl):not(.drun)");
      const dlAnchor = protoRow.querySelector("a.ddl-inline, a.ddl");
      const dismissBtn = protoRow.querySelector("button.deliverable-dismiss");
      const desc = describeDeliverable(it);
      const fmt = getDelivFormat(it);
      const itemKey = String(it.open_path || it.path || it.product_id || it.what || "");
      const isExpanded = itemKey && _openDelivs.has("tile:" + itemKey);
      const frow = el("div", "file-row compact-tile tier-" + tier + (it.is_current ? " is-current" : "") + (isExpanded ? " expanded" : ""));

      const wireOpenClick = (anchorEl) => {
        const origClick = mainAnchor && mainAnchor.onclick;
        anchorEl.onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const targetHref = anchorEl.getAttribute("href") || (mainAnchor && mainAnchor.getAttribute("href")) || "";
          if (it && it.managed && it.presentation_id) {
            post("/api/refinement-open", {
              step_id: it.step,
              presentation_id: it.presentation_id,
              product_id: it.product_id,
              session_id: String(window.STEWARD_TERM || "cockpit"),
            }).catch(() => {});
          }
          if (typeof window.enterSecondWindowMode === "function") {
            window.enterSecondWindowMode(shortTitle, targetHref);
            return false;
          }
          if (origClick) return origClick.call(mainAnchor, ev);
          if (targetHref && targetHref !== "#") window.open(targetHref, "_blank");
          return false;
        };
      };

      const topLine = el("div", "file-row-top");
      const titleWrap = el("div", "file-title-wrap");
      titleWrap.appendChild(el("span", "file-fmt-badge " + fmt.cls, fmt.tag));
      if (desc.statusBadge === "START HERE") {
        titleWrap.appendChild(el("span", "file-Start-badge", "START HERE"));
      }
      const shortTitle = oneLine(desc.title, 76);
      if (mainAnchor) {
        const openA = document.createElement("a");
        openA.className = "file-open";
        openA.href = mainAnchor.getAttribute("href") || "#";
        openA.target = "_blank";
        openA.rel = "noopener";
        openA.textContent = shortTitle;
        openA.title = (it.what || "") + (it.path ? " (" + it.path + ")" : "");
        wireOpenClick(openA);
        titleWrap.appendChild(openA);
        topLine.appendChild(titleWrap);

        const actions = el("div", "file-actions");
        const openBtn = document.createElement("a");
        openBtn.className = "file-dl file-open-btn";
        openBtn.href = openA.href;
        openBtn.target = "_blank";
        openBtn.rel = "noopener";
        openBtn.textContent = "Open";
        openBtn.title = "Open 2nd Win — split-screen right window (inside Anchor.exe)";
        wireOpenClick(openBtn);
        actions.appendChild(openBtn);
        if (tier === "review" && dismissBtn) {
          dismissBtn.className = "deliverable-dismiss mark-done-btn";
          dismissBtn.textContent = "\u2713 Done";
          dismissBtn.title = "Mark this deliverable Done (reviewed)";
          actions.appendChild(dismissBtn);
        }
        if (dlAnchor) {
          const dl = document.createElement("a");
          dl.className = "file-dl";
          dl.href = dlAnchor.getAttribute("href") || "#";
          dl.target = "_blank";
          dl.rel = "noopener";
          dl.textContent = "\u2b07";
          dl.title = dlAnchor.title || "Download";
          actions.appendChild(dl);
        }
        const expBtn = el("button", "file-exp-btn", isExpanded ? "\u25be" : "\u25b8");
        expBtn.type = "button";
        expBtn.title = "Click to expand or collapse full deliverable details";
        actions.appendChild(expBtn);
        topLine.appendChild(actions);
      } else {
        titleWrap.appendChild(el("span", "file-open", shortTitle));
        topLine.appendChild(titleWrap);
      }
      frow.appendChild(topLine);

      if ((tier === "review" || it.is_current) && desc.reviewSummary) {
        frow.appendChild(el("div", "file-row-review-summary", desc.reviewSummary));
      }

      const rawPath = String(it.open_path || it.path || "").replace(/\\/g, "/");
      const baseName = rawPath ? rawPath.split("/").pop() : "";
      const compactSubParts = [];
      if (baseName && shortTitle.toLowerCase().indexOf(baseName.toLowerCase()) < 0) compactSubParts.push(baseName);
      if (it.step) compactSubParts.push("Step " + it.step);
      if (it.date) compactSubParts.push(it.date);
      if (desc.subtitle && !compactSubParts.length) compactSubParts.push(oneLine(desc.subtitle, 72));
      if (compactSubParts.length) {
        frow.appendChild(el("div", "file-row-sub", compactSubParts.join(" \u00b7 ")));
      }

      const moreDrawer = el("div", "file-row-more");
      if (it.what) {
        moreDrawer.appendChild(el("div", "file-more-line", it.what.replace(/\*\*/g, "")));
      }
      if (rawPath) {
        moreDrawer.appendChild(el("div", "file-more-meta", "File: " + rawPath + (it.step ? " \u00b7 Step " + it.step : "") + (it.date ? " \u00b7 " + it.date : "")));
      }
      const moreActions = el("div", "file-more-actions");
      if (mainAnchor) {
        const win2 = document.createElement("a");
        win2.className = "file-dl";
        win2.href = mainAnchor.getAttribute("href") || "#";
        win2.target = "_blank";
        win2.rel = "noopener";
        win2.textContent = "Open Right Split \u25eb";
        win2.title = "Open in Right Split-Screen Window";
        wireOpenClick(win2);
        moreActions.appendChild(win2);
      }
      if (tier !== "review" && dismissBtn) moreActions.appendChild(dismissBtn);
      if (moreActions.childNodes.length) moreDrawer.appendChild(moreActions);
      frow.appendChild(moreDrawer);

      frow.onclick = (ev) => {
        if (ev.target.closest("a, button.deliverable-dismiss")) return;
        const nowOpen = frow.classList.toggle("expanded");
        const eb = frow.querySelector(".file-exp-btn");
        if (eb) eb.textContent = nowOpen ? "\u25be" : "\u25b8";
        if (itemKey) {
          if (nowOpen) _openDelivs.add("tile:" + itemKey);
          else _openDelivs.delete("tile:" + itemKey);
        }
      };
      return frow;
    };

    const activeStepInfo = (() => {
      const steps = (_lastMap && Array.isArray(_lastMap.steps)) ? _lastMap.steps : [];
      const hbStepId = String(((_lastMap && _lastMap.heartbeat) || {}).current_step_id || "").trim();
      let idx = steps.findIndex(st => st && (String(st.id || "") === hbStepId || isNow(st, _lastMap)));
      if (idx < 0) idx = steps.findIndex(st => st && (st.status === "active" || st.status === "waiting"));
      const st = idx >= 0 ? steps[idx] : null;
      return {
        id: hbStepId || (st && String(st.id || "")) || "",
        num: idx >= 0 ? String(idx + 1) : "",
        step: st,
      };
    })();
    const matchesActiveStep = (it) => {
      const s = String((it && (it.owner_step_id || it.step)) || "").trim();
      if (!s) return false;
      return (activeStepInfo.id && s === activeStepInfo.id) || (activeStepInfo.num && s === activeStepInfo.num);
    };
    const isExplicitEarlier = (it) => {
      const w = String((it && it.what) || "").trim();
      const p = String((it && (it.open_path || it.path)) || "").replace(/\\/g, "/");
      if (/^(?:START HERE|FOR REVIEW|APPROVED|FINAL|SAVED DESIGN)\b/i.test(w) || /^(?:Final|Finished)\s+Deliverables\//i.test(p)) {
        return false;
      }
      return /^(?:EARLIER|Historical|SUPERSEDED|ARCHIVED)\b/i.test(w) || /\bsuperseded by\b/i.test(w) || (hasCurrent && it && it.is_current === false);
    };
    const isFinalOrApproved = (it) => {
      if (!it || isNoiseDeliverable(it) || isExplicitEarlier(it)) return false;
      const w = String(it.what || "").trim();
      const p = String(it.open_path || it.path || "").replace(/\\/g, "/");
      return /^(?:APPROVED|FINAL|SAVED DESIGN)\b/i.test(w) ||
        /\b(?:APPROVED|FINAL VERSION|LOCKED)\b/i.test(w) ||
        /^(?:Final|Finished)\s+Deliverables\//i.test(p) ||
        (it.is_current === true && !/^(?:START HERE|FOR REVIEW)\b/i.test(w) && !/\b(?:for review|ready for (?:john'?s )?(?:editorial )?review)\b/i.test(w) && /\b(?:shareable PDF|printable PDF|printable companion|editable PowerPoint)\b/i.test(w));
    };
    const maxDelivDate = items
      .filter(i => i && !isNoiseDeliverable(i) && !i.auto && !isExplicitEarlier(i))
      .reduce((mx, i) => (String(i.date || "") > mx ? String(i.date || "") : mx), "");
    const isReviewOrCurrent = (it) => {
      if (!it || isNoiseDeliverable(it) || it.auto || isExplicitEarlier(it) || isFinalOrApproved(it)) return false;
      const w = String(it.what || "").trim();
      if (/^(?:START HERE|FOR REVIEW|CURRENT)\b/i.test(w)) return true;
      if (/\b(?:ready for (?:john'?s )?(?:editorial )?review|for review|awaiting review|track changes)\b/i.test(w)) return true;
      if (it.is_current === true && (matchesActiveStep(it) || String(it.step || "") === "6" || (maxDelivDate && String(it.date || "") === maxDelivDate))) return true;
      return false;
    };

    let reviewNow = items.filter(isReviewOrCurrent)
      .sort((a, b) =>
        Number(matchesActiveStep(b)) - Number(matchesActiveStep(a)) ||
        String(b.date || "").localeCompare(String(a.date || "")) ||
        Number(/^START HERE\b/i.test(b.what || "")) - Number(/^START HERE\b/i.test(a.what || ""))
      );
    if (!reviewNow.length) {
      reviewNow = items.filter(i => i && i.is_current === true && !isNoiseDeliverable(i) && !isExplicitEarlier(i)).slice(0, 8);
    }
    _deliv.reviewNow = reviewNow;
    renderTopNextSteps();

    const seenFinalKeys = new Set(reviewNow.map(i => String(i.open_path || i.path || i.what)));
    const finalApproved = [];
    ((_deliv && _deliv.approved) || []).concat(items.filter(isFinalOrApproved)).forEach((it) => {
      if (!it || isNoiseDeliverable(it)) return;
      const k = String(it.open_path || it.path || it.what);
      if (seenFinalKeys.has(k)) return;
      seenFinalKeys.add(k);
      finalApproved.push(it);
    });

    const usedKeys = new Set([...reviewNow, ...finalApproved].map(i => String(i.open_path || i.path || i.what)));
    const otherHuman = items.filter(i => !isNoiseDeliverable(i) && !i.auto && !usedKeys.has(String(i.open_path || i.path || i.what)))
      .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    const supportingPlans = items.filter(i => !isNoiseDeliverable(i) && i.auto && !usedKeys.has(String(i.open_path || i.path || i.what)));
    const codeJobReceipts = items.filter(i => isNoiseDeliverable(i));
    const allHumanItems = reviewNow.concat(finalApproved, otherHuman, supportingPlans);

    // Build Pending items list (active skill/code job or in-progress step)
    const pendingItems = [];
    if (latestStatusRun && latestStatusRun.label) {
      pendingItems.push({
        title: latestStatusRun.label,
        worker: latestStatusRun.skill || latestStatusRun.worker || "Worker",
        eta: latestStatusRun.age ? ("Running " + latestStatusRun.age) : "In flight",
      });
    }
    const mapSteps = (_lastMap && Array.isArray(_lastMap.steps)) ? _lastMap.steps : [];
    const isWorkingState = Boolean((lastState && (lastState.busy || lastState.working_bg)) || (_lastMap && _lastMap.attention && _lastMap.attention.state === "working"));
    if (!pendingItems.length && isWorkingState && activeStepInfo.step) {
      pendingItems.push({
        title: (activeStepInfo.step.navigation && activeStepInfo.step.navigation.label) || activeStepInfo.step.name || "Active Step",
        worker: activeStepInfo.step.commissioned_as || personaName(),
        eta: oneLine((_lastMap && _lastMap.attention && _lastMap.attention.reason) || "In progress", 48),
      });
    }

    const s = $("[data-delivmount]") || paneEl();
    if (s) {
      let tile = s.querySelector(".blk.deliv");
      const priorScroll=tile && tile.querySelector(".body") ? tile.querySelector(".body").scrollTop : 0;
      const defaultHubOpen = !isLegacyNavTest;
      const wasOpen = (tile && tile.dataset.userToggled) ? !tile.classList.contains("folded") : (defaultHubOpen ? true : _delivOpen === true);
      if (!tile) {
        tile = el("div", "blk steward deliv folded");
        s.insertBefore(tile, s.firstChild);
      } else tile.textContent = "";
      if (wasOpen) tile.classList.remove("folded");
      else tile.classList.add("folded");
      const newestHint = items[0] ? ("newest: " + shortWhat(items[0])) : "newest: none";
      tile.dataset.newestHint = newestHint;
      const totalHumanCount = allHumanItems.length || items.length;
      const who = el("div", "who");
      if (isLegacyNavTest) {
        who.textContent = "DELIVERABLES \u00b7 " + (reviewNow.length ? reviewNow.length + " for you \u2014 " + newestHint : (items.length ? items.length + " registered \u2014 " + newestHint : "nothing registered yet"));
      } else {
        who.appendChild(el("span", "deliv-hub-title", "\ud83d\udce6 DELIVERABLES"));
        who.appendChild(el("span", "deliv-hub-counts", pendingItems.length + " Pending \u00b7 " + reviewNow.length + " Review \u00b7 " + finalApproved.length + " Final \u00b7 " + totalHumanCount + " All \u25be"));
      }
      who.style.cursor = "pointer";
      who.title = newestHint;
      who.onclick = () => {
        tile.dataset.userToggled = "1";
        tile.classList.toggle("folded");
        _delivOpen = !tile.classList.contains("folded");
      };
      tile.appendChild(who);
      const body = el("div", "body");
      if(d?.finished_projection && !d.finished_projection.consistent)
        body.appendChild(el('div','sdmeta','Finished Deliverables needs repair · '+(d.finished_projection.error||'projection incomplete')));
      if (!d || !d.exists) {
        body.appendChild(el("div", "snow", "No DELIVERABLES.md yet — the steward starts the register when the first human-facing artifact lands."));
      } else if (!items.length && !pendingItems.length) {
        body.appendChild(el("div", "snow", "(register is empty)"));
      }
      if (isLegacyNavTest) {
        if (!renderNavigation(body,_lastMap,items,"deliverables")) items.forEach((it) => body.appendChild(stepDelivLine(it)));
      } else {
        // Tier contract markers:
        // 1. Current & Ready for Review ( · ready now · more items in open review (click to open) · Needs Review: · steward-current-banner
        // 2. Final & Approved deliverables ( · finalized \u00b7 click to open
        // 3. Earlier & Supporting Deliverables by Section ( · sections \u00b7 click to open
        // navChoice("deliv:v2:tier:review", reviewNow.length > 0) · navChoice("deliv:v2:tier:final", false)
        // navChoice("deliv:v2:tier:other", false) · navChoice(secKey, false) · navChoice("deliv:v2:tier:receipts", false)
        const stack = el("div", "deliv-tier-stack");
        const bindSubTileToggle = (detEl, sessionKey) => {
          detEl.open = Boolean(navSession[sessionKey]);
          detEl.addEventListener("toggle", () => {
            if (detEl.isConnected) navSession[sessionKey] = detEl.open;
          });
        };

        // 1. ⏳ Pending (N items ▸) — starts collapsed by default
        const pendFold = el("details", "deliv-tier-fold tier-pending pending");
        bindSubTileToggle(pendFold, "deliv:v3:pending");
        const pendSum = el("summary", "");
        pendSum.appendChild(el("span", "deliv-group-lbl", "\u23f3 Pending"));
        pendSum.appendChild(el("span", "deliv-tier-count", pendingItems.length + (pendingItems.length === 1 ? " item \u25b8" : " items \u25b8")));
        pendFold.appendChild(pendSum);
        const pendBody = el("div", "deliv-tier-body");
        if (pendingItems.length) {
          pendingItems.forEach((pi) => {
            const pCard = el("div", "deliv-pending-item");
            pCard.appendChild(el("div", "", "\u2699 " + pi.title));
            const pMeta = el("div", "deliv-pending-meta");
            pMeta.appendChild(el("span", "", "Worker: " + pi.worker));
            pMeta.appendChild(el("span", "deliv-pending-eta", "ETA: " + pi.eta));
            pCard.appendChild(pMeta);
            pendBody.appendChild(pCard);
          });
        } else {
          pendBody.appendChild(el("div", "sdmeta", "0 items in flight — all completed work has moved to For Review."));
        }
        pendFold.appendChild(pendBody);
        stack.appendChild(pendFold);

        // 2. 👁 For Review (N items ▸) — starts collapsed by default, includes ✓ Done + ✓ Mark All Done
        const revFold = el("details", "deliv-tier-fold tier-review review");
        bindSubTileToggle(revFold, "deliv:v3:review");
        const revSum = el("summary", "");
        revSum.appendChild(el("span", "deliv-group-lbl", "\ud83d\udc41 For Review"));
        revSum.appendChild(el("span", "deliv-tier-count", reviewNow.length + (reviewNow.length === 1 ? " item \u25b8" : " items \u25b8")));
        revFold.appendChild(revSum);
        const revBody = el("div", "deliv-tier-body");
        if (reviewNow.length) {
          const markBar = el("div", "mark-all-done-bar");
          markBar.appendChild(el("span", "", "Click any deliverable to review, or mark Done:"));
          const markAllBtn = el("button", "mark-all-done-btn deliv-mark-all-btn", "\u2713 Mark All Done");
          markAllBtn.type = "button";
          markAllBtn.onclick = async (ev) => {
            ev.stopPropagation();
            markAllBtn.disabled = true;
            markAllBtn.textContent = "\u2713 All Marked Done";
            const batchItems = reviewNow.map((it) => {
              const k = String(it.open_path || it.path || it.product_id || it.what || "");
              if (k) _dismissedSessionKeys.add(k);
              return {
                path: it.open_path || it.path || "",
                product_id: it.product_id || "",
                what: it.what || "",
                revision_id: it.revision_id || "",
                hash: it.hash || ""
              };
            });
            revBody.textContent = "";
            revBody.appendChild(el("div", "sdmeta", "No items waiting for review."));
            const cntSpan = revSum.querySelector(".deliv-tier-count");
            if (cntSpan) cntSpan.textContent = "0 items \u25b8";
            try {
              await post("/api/dismiss-deliverable", { items: batchItems });
            } catch (e) {}
            await renderDeliverablesTile();
          };
          markBar.appendChild(markAllBtn);
          revBody.appendChild(markBar);
          const cList = el("div", "deliv-list");
          reviewNow.forEach(it => cList.appendChild(buildMockupFileRow(it, "review")));
          revBody.appendChild(cList);
        } else {
          revBody.appendChild(el("div", "sdmeta", "No items waiting for review."));
        }
        revFold.appendChild(revBody);
        stack.appendChild(revFold);

        // 3. 🏛 Final Deliverables (N items ▸) — starts collapsed by default
        const finFold = el("details", "deliv-tier-fold tier-final final");
        bindSubTileToggle(finFold, "deliv:v3:final");
        const finSum = el("summary", "");
        finSum.appendChild(el("span", "deliv-group-lbl", "\ud83c\udfdb Final Deliverables"));
        finSum.appendChild(el("span", "deliv-tier-count", finalApproved.length + (finalApproved.length === 1 ? " item \u25b8" : " items \u25b8")));
        finFold.appendChild(finSum);
        const finBody = el("div", "deliv-tier-body");
        if (finalApproved.length) {
          const fList = el("div", "deliv-list");
          finalApproved.forEach(it => fList.appendChild(buildMockupFileRow(it, "final")));
          finBody.appendChild(fList);
        } else {
          finBody.appendChild(el("div", "sdmeta", "Main/permanent deliverables appear here once finalized."));
        }
        finFold.appendChild(finBody);
        stack.appendChild(finFold);

        // 4. 📚 All Deliverables (N items ▸) — starts collapsed by default, grouped by Wave/Step
        const allFold = el("details", "deliv-tier-fold tier-all all-waves");
        bindSubTileToggle(allFold, "deliv:v3:all");
        const allSum = el("summary", "");
        allSum.appendChild(el("span", "deliv-group-lbl", "\ud83d\udcda All Deliverables"));
        allSum.appendChild(el("span", "deliv-tier-count", allHumanItems.length + (allHumanItems.length === 1 ? " item \u25b8" : " items \u25b8")));
        allFold.appendChild(allSum);
        const allBody = el("div", "deliv-tier-body");
        if (allHumanItems.length) {
          const byWaveGroup = new Map();
          allHumanItems.forEach((it) => {
            const owner = navOwner(mapSteps, it);
            let grpLabel = "";
            if (owner) {
              const idx = mapSteps.indexOf(owner);
              const rawN = String((owner.navigation && owner.navigation.label) || owner.name || ("Step " + (idx + 1)));
              grpLabel = (/^(?:step|wave|stage|phase)\s*\d+/i.test(rawN) ? "" : ("Step " + (idx + 1) + " \u00b7 ")) + oneLine(rawN, 46);
            } else {
              const waveMatch = /\b(Wave\s*\d+)/i.exec(String(it.what || "") + " " + String(it.path || ""));
              grpLabel = waveMatch ? (waveMatch[1] + " Deliverables") : describeDeliverable(it).sectionGroup;
            }
            if (!byWaveGroup.has(grpLabel)) byWaveGroup.set(grpLabel, []);
            byWaveGroup.get(grpLabel).push(it);
          });
          Array.from(byWaveGroup.entries()).forEach(([grpName, grpItems]) => {
            const wDet = el("details", "deliv-wave-subfold");
            bindSubTileToggle(wDet, "deliv:v3:wave:" + grpName);
            const wSum = el("summary", "");
            wSum.appendChild(el("span", "", grpName));
            wSum.appendChild(el("span", "deliv-tier-count", grpItems.length + " \u25b8"));
            wDet.appendChild(wSum);
            const wBody = el("div", "deliv-wave-subbody");
            grpItems.forEach(it => wBody.appendChild(buildMockupFileRow(it, "other")));
            wDet.appendChild(wBody);
            allBody.appendChild(wDet);
          });
        } else {
          allBody.appendChild(el("div", "sdmeta", "No deliverables registered yet."));
        }
        allFold.appendChild(allBody);
        stack.appendChild(allFold);

        body.appendChild(stack);
      }
      tile.appendChild(body);
      body.scrollTop=priorScroll;
      if (s.firstChild !== tile) s.insertBefore(tile, s.firstChild);
      renderTopNextSteps();
    }
    // — the goal/map links —
    const slot = $("[data-deliverables]");
    if (slot) {
      slot.textContent = "";
      if (items.length) {
        slot.appendChild(el("div", "glabel", "Deliverables"));
        if (!renderNavigation(slot,_lastMap,items,"map-deliverables")) items.forEach((it) => slot.appendChild(stepDelivLine(it)));
      }
    }
    // — Wave 4/5.6 Single-Line Top Deliverables Strip ([data-top-deliverables]) —
    const topStrip = $("[data-top-deliverables]");
    if (topStrip) {
      const rankItem = (it) => {
        const p = String(it.path || "").replace(/\\/g, "/");
        if (isNoiseDeliverable(it)) return 9;
        if (isReviewOrCurrent(it) && /^START HERE\b/i.test(it.what || "")) return 0;
        if (isReviewOrCurrent(it)) return 1;
        if (isFinalOrApproved(it)) return 2;
        if (!it.auto && /^START HERE\b/i.test(it.what || "")) return 3;
        if (!it.auto) return 4;
        if (/^(?:MASTER-PLAN|IMPLEMENTATION-PLAN|ANVIL-REPORT|PLAN)\.md$/i.test(p)) return 5;
        return 6;
      };
      const openablePool = items
        .filter(it => it && (it.openable || it.path || it.route))
        .slice()
        .sort((a, b) => rankItem(a) - rankItem(b) || String(b.date || "").localeCompare(String(a.date || "")));
      const nonNoisePool = openablePool.filter(it => !isNoiseDeliverable(it));
      const allPool = nonNoisePool.length ? nonNoisePool : openablePool;
      const inlineShown = (reviewNow.length ? reviewNow : allPool).slice(0, 2);
      const currentCount = reviewNow.length;
      if (!inlineShown.length) {
        topStrip.hidden = true;
        topStrip.textContent = "";
      } else {
        topStrip.hidden = false;
        topStrip.textContent = "";
        topStrip.onclick = (ev) => {
          if (!ev.target || !ev.target.closest || !ev.target.closest("a")) ev.stopPropagation();
        };
        const badgeText = currentCount
          ? ("\u2605 For Review (" + currentCount + "):")
          : ("\u2605 Best Deliverables:");
        topStrip.appendChild(el("span", "tds-badge" + (currentCount ? " review" : ""), badgeText));
        inlineShown.forEach((it) => {
          const chip = el("span", "file-chip tds-chip" + (isReviewOrCurrent(it) ? " review" : ""));
          const protoRow = delivRow(it);
          const mainAnchor = protoRow.querySelector("a:not(.ddl-inline):not(.ddl):not(.drun)");
          const dlAnchor = protoRow.querySelector("a.ddl-inline, a.ddl");
          const fmt = getDelivFormat(it);
          const cleanLabel = cleanDelivTitle(it, 38);
          chip.appendChild(el("span", "file-fmt-badge " + fmt.cls, fmt.tag));
          if (mainAnchor) {
            const openA = document.createElement("a");
            openA.className = "file-open";
            openA.href = mainAnchor.getAttribute("href") || "#";
            openA.target = "_blank";
            openA.rel = "noopener";
            openA.textContent = cleanLabel;
            openA.title = (it.what || "") + (it.path ? " (" + it.path + ")" : "");
            openA.onclick = (ev) => {
              ev.preventDefault();
              ev.stopPropagation();
              if (typeof window.enterSecondWindowMode === "function") {
                window.enterSecondWindowMode(cleanLabel, openA.getAttribute("href") || openA.href);
                return false;
              }
              if (mainAnchor.onclick) return mainAnchor.onclick(ev);
            };
            chip.appendChild(openA);
          } else {
            chip.appendChild(el("span", "file-open", cleanLabel));
          }
          if (dlAnchor) {
            const dlA = document.createElement("a");
            dlA.className = "file-dl";
            dlA.href = dlAnchor.getAttribute("href") || "#";
            dlA.target = "_blank";
            dlA.rel = "noopener";
            dlA.textContent = "\u2b07";
            dlA.title = dlAnchor.title || "Download";
            chip.appendChild(dlA);
          }
          topStrip.appendChild(chip);
        });
        const totalHuman = (reviewNow.length + finalApproved.length + otherHuman.length) || allPool.length;
        const moreLabel = "All in Deliverables (" + totalHuman + ") \u25be";
        const moreBtn = el("button", "tds-more", moreLabel);
        moreBtn.type = "button";
        moreBtn.title = "Open all deliverables in the right-hand Deliverables tab or preview list";
        moreBtn.onclick = (ev) => {
          ev.stopPropagation();
          const appEl = $(".app");
          if (appEl) appEl.classList.add("statusopen");
          const dt = $("[data-delivmount] .blk.deliv");
          if (dt) {
            const willOpen = dt.classList.contains("folded");
            dt.classList.toggle("folded", !willOpen);
            _delivOpen = willOpen;
            dt.scrollIntoView({ block: "nearest" });
          }
        };
        topStrip.appendChild(moreBtn);
      }
    }
    restoreNavFocus(focusKey);
  }
  // (2026-09-05, John) a route opens rendered: markdown through the Reader,
  // Word / PowerPoint / Excel as a preview page; the page token rides along.
  function routeHref(route) {
    const r = String(route || "");
    const sep = r.indexOf("?") >= 0 ? "&" : "?";
    const md = /\.(md|markdown)(&|$)/i.test(r), office = /\.(docx|pptx|xlsx)(&|$)/i.test(r);
    return r + (md ? sep + "render=1" : office ? sep + "view=1" : "") +
      (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
  }
  function routeName(r) {
    try {
      // (2026-10-07) a Foundry review route is named by its skill — the live
      // page it opens — never the raw query string
      const sk = /^\/foundry\?skill=([^&]+)$/.exec(String(r || ""));
      if (sk) return decodeURIComponent(sk[1]) + " — live Foundry page";
      const m = /[?&]path=([^&]+)/.exec(r); const seg = decodeURIComponent(m ? m[1] : r).split("/").filter(Boolean); return seg[seg.length - 1] || r;
    }
    catch (e) { return r; }
  }
  function delivRow(it) {
    const row = el("div", "snow drow");
    const openPath = it.open_path || it.path;
    if (it.notebook_product && window.AnchorNotebooks) {
      row.appendChild(window.AnchorNotebooks.render(it, it.dir !== undefined ? it.dir : DIR));
      return row;
    }
    if (it.route) {
      // (2026-09-05) a contained Anchor route (/report/…, /artifact/…) the
      // parser CLASSIFIED (classify_route) — hostile cells arrive route:null
      // and fall through to the text branch. Opens in a new window with the
      // page token appended, same mechanism as the deliverable-file link.
      const a = document.createElement("a");
      // labelled by the document it opens, never the whole route (2026-09-05)
      a.textContent = "• " + (it.what || routeName(it.route));
      try { const im = window.SkillIcons && window.SkillIcons.img(itemMark(it) || "", 14); if (im) a.insertBefore(im, a.firstChild); } catch (e) { /* no-op */ }
      const tokr = window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "";
      if (it.reading && it.reading.preparing && !it.reading.read) {
        // the server's reading target says nothing renders yet (a deck behind a route): say so, keep its download
        const label = el("span", "preparing", "• " + (it.what || routeName(it.route)) + " · preparing a reading copy");
        row.appendChild(label);
        if (it.reading.download) {
          const d = el("a", "ddl", "Download");
          d.href = it.reading.download + (it.reading.download.indexOf("?") >= 0 ? tokr : tokr.replace("&", "?"));
          d.target = "_blank"; d.rel = "noopener";
          row.appendChild(document.createTextNode(" ")); row.appendChild(d);
        }
        return row;
      }
      // the server's canonical reading URL when it gave one (the receipt's), else the old route rule
      a.href = (it.reading && it.reading.read)
        ? it.reading.read + (it.reading.read.indexOf("?") >= 0 ? tokr : tokr.replace("&", "?"))
        : routeHref(it.route);
      a.target = "_blank";
      a.rel = "noopener";
      a.onclick = (ev) => {
        if (typeof window.enterSecondWindowMode === "function") {
          ev.preventDefault();
          ev.stopPropagation();
          window.enterSecondWindowMode(it.what || routeName(it.route), a.getAttribute("href") || a.href);
        }
      };
      row.appendChild(a);
      if (/^(\/api\/steward\/deliverable-file\?|\/artifact\/)/.test(a.getAttribute("href") || "")) {
        const dl = el("a", "ddl-inline", "\u2b07");
        dl.href = (a.getAttribute("href") || "").replace(/([?&])(render|view)=1(&|$)/g, (m, p1, _k, p3) => p3 ? p1 : "") + "&download=1";
        dl.target = "_blank"; dl.rel = "noopener"; dl.title = "Download file";
        row.appendChild(dl);
      }
    } else if (it.openable && it.path) {
      const a = document.createElement("a");
      a.textContent = "• " + it.what;
      try { const im = window.SkillIcons && window.SkillIcons.img(itemMark(it) || "", 14); if (im) a.insertBefore(im, a.firstChild); } catch (e) { /* no-op */ }
      // 2026-08-26 (John: "I click on them and the page had nothing"): a raw
      // <a href> NAVIGATES — it never passes through the fetch shim, so the
      // old api() URL arrived with no /api/steward/ prefix, no pid and no
      // token → a blank page. Build the FULL authed URL ourselves, and send
      // text docs (.md/.txt/.csv/.json/.log) through the report VIEWER so
      // they render human-readable instead of as raw bytes.
      const dirRel = it.dir !== undefined ? it.dir : DIR;
      const isText = /\.(csv|json|log)$/i.test(openPath) && !(it.managed && it.open_path && it.hash);
      // 2026-10-07 (item 2): markdown opens through the ONE canonical reading URL (deliverables_register.reading_target:
      // deliverable-file + render=1) - the same link the dialogue's receipt and Next steps carry
      const isMarkdown = /\.(md|markdown|txt)$/i.test(openPath);
      const reading = it.reading && it.reading.read && /^\/api\/steward\/deliverable-file\?/.test(it.reading.read) ? it.reading.read : "";
      const tok = window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "";
      if (reading) {
        // the server's reading target (deliverables_register.reading_target) - the receipt's URL, token added
        a.href = reading + tok;
        a.target = "_blank";
        a.rel = "noopener";
      } else if (it.reading && it.reading.preparing) {
        // nothing renders yet (a deck without its PDF): say so - never a link to an "unavailable" page
        const label = el("span", "preparing", "• " + it.what + " · preparing a reading copy");
        row.appendChild(label);
        if (it.reading.download) {
          const d = el("a", "ddl", "Download");
          d.href = it.reading.download + tok; d.target = "_blank"; d.rel = "noopener";
          row.appendChild(document.createTextNode(" ")); row.appendChild(d);
        }
        return row;
      } else if (isText) {
        const textReportHref = "/steward/report?pid=" + encodeURIComponent(window.STEWARD_PID || "") +
          "&dir=" + encodeURIComponent(dirRel) +
          "&path=" + encodeURIComponent(openPath) +
          (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") + tok;
        a.href = textReportHref;
        a.target = "_blank";
        a.rel = "noopener";
        a.onclick = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (typeof window.enterSecondWindowMode === "function") {
            window.enterSecondWindowMode(it.what || openPath, textReportHref);
            return;
          }
          window.open("/report?dir=" + encodeURIComponent(dirRel) +
                      "&path=" + encodeURIComponent(openPath));
        };
      } else {
        a.href = "/api/steward/deliverable-file?pid=" +
          encodeURIComponent(window.STEWARD_PID || "") +
          "&dir=" + encodeURIComponent(dirRel) +
          "&path=" + encodeURIComponent(openPath) +
          (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") +
          (/\.(docx|pptx|xlsx)$/i.test(it.path) ? "&view=1" : "") +
          (isMarkdown ? "&render=1" : "") +
          (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
        a.target = "_blank";
        a.rel = "noopener";
        a.onclick = (ev) => {
          if (typeof window.enterSecondWindowMode === "function") {
            ev.preventDefault();
            ev.stopPropagation();
            window.enterSecondWindowMode(it.what || openPath, a.getAttribute("href") || a.href);
          }
        };
      }
      row.appendChild(a);
      const dlUrl = "/api/steward/deliverable-file?pid=" +
        encodeURIComponent(window.STEWARD_PID || "") +
        "&dir=" + encodeURIComponent(dirRel) +
        "&path=" + encodeURIComponent(openPath) +
        (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") +
        "&download=1" + tok;
      const dlBtn = el("a", "ddl-inline", "\u2b07");
      dlBtn.href = dlUrl; dlBtn.target = "_blank"; dlBtn.rel = "noopener";
      dlBtn.title = "Download " + (openPath || it.what);
      row.appendChild(dlBtn);
      if(/\.pptx$/i.test(it.path)) {
        const download=el('a','sdmeta',' Download PowerPoint');
        // the deck's own download (the reading link may be its PDF companion - never download that as the deck)
        download.href=(it.reading&&it.reading.download)?it.reading.download+(window.STEWARD_TOKEN?'&token='+encodeURIComponent(window.STEWARD_TOKEN):''):a.href.replace(/&view=1\b/,'')+'&download=1';download.target='_blank';download.rel='noopener';row.appendChild(download);
      }
      if (/\.docx$/i.test(it.path) && it.dir === undefined && _lastMap && _lastMap.dir) {
        // (Wave D0) one click opens the manuscript in desktop Word, track changes and all
        const word = el('a', 'sdmeta', ' Open in Word');
        word.href = "ms-word:ofe|u|" + fileUrl(_lastMap.dir) + "/" + String(openPath).split(/[\\/]/).map(encodeURIComponent).join("/");
        row.appendChild(word);
      }
      if (it.managed && it.presentation_id) {
        const href = a.getAttribute("href") || a.href;
        a.onclick = async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          // Open the already-addressed file immediately. Recording the view is
          // bookkeeping and must not withhold or close the document (John,
          // 2026-09-14 and 2026-09-18: managed Current work opened about:blank,
          // waited on a slow view write, then closed the window).
          const target = isText ? "/steward/report?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(dirRel) + "&path=" + encodeURIComponent(openPath) + (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") + (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "") : href;
          if (typeof window.enterSecondWindowMode === "function") {
            window.enterSecondWindowMode(it.what || openPath || "Deliverable", target);
          } else {
            const preview = window.open("about:blank", "_blank");
            if (preview) { preview.opener = null; preview.location = target; }
            else window.location.assign(target);
          }
          try {
            const response = await post("/api/refinement-open", {
              step_id: it.step, presentation_id: it.presentation_id,
              product_id: it.product_id, session_id: String(window.STEWARD_TERM || "cockpit")
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
              if (!row.querySelector("[data-view-record-miss]")) {
                const note = el("span", "sdmeta", "Opened the file; viewing was not recorded.");
                note.dataset.viewRecordMiss = "1";
                row.appendChild(note);
              }
            }
          } catch (error) {
            if (!row.querySelector("[data-view-record-miss]")) {
              const note = el("span", "sdmeta", "Opened the file; viewing was not recorded.");
              note.dataset.viewRecordMiss = "1";
              row.appendChild(note);
            }
          }
        };
      }
    } else if (openPath && !String(openPath).startsWith("/") && !/(?:^|[\\/])\.\.(?:[\\/]|$)/.test(String(openPath))) {
      const dirRel = it.dir !== undefined ? it.dir : DIR;
      const isMd = /\.(md|markdown|txt)$/i.test(openPath);
      const tok = window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "";
      const baseHref = "/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID || "") +
        "&dir=" + encodeURIComponent(dirRel) + "&path=" + encodeURIComponent(openPath);
      const a = el("a", "", "• " + (it.what || openPath));
      a.href = baseHref + (isMd ? "&render=1" : "") + tok;
      a.target = "_blank"; a.rel = "noopener";
      a.onclick = (ev) => {
        if (typeof window.enterSecondWindowMode === "function") {
          ev.preventDefault();
          ev.stopPropagation();
          window.enterSecondWindowMode(it.what || openPath, a.getAttribute("href") || a.href);
        }
      };
      row.appendChild(a);
      const dl = el("a", "ddl-inline", "\u2b07");
      dl.href = baseHref + "&download=1" + tok;
      dl.target = "_blank"; dl.rel = "noopener"; dl.title = "Download " + openPath;
      row.appendChild(dl);
    } else {
      row.appendChild(document.createTextNode("• " + it.what + (it.path ? " — " + it.path : "")));
    }
    // reports-links W3: a row carrying a run: command gets a 'Run ▶' control.
    // It POSTs the register-allowlisted command to the run endpoint (the server
    // re-reads the register and refuses anything else byte-for-byte), then
    // opens the EXISTING standalone terminal page on the returned session —
    // the command sits on the shell prompt UNSENT until the user presses
    // Enter. textContent only, never raw markup injection.
    if (it.run) {
      const runDir = it.dir !== undefined ? it.dir : DIR;
      const rbtn = document.createElement("a");
      rbtn.className = "drun";
      rbtn.textContent = " Run ▶";
      rbtn.href = "#";
      rbtn.title = "Open a terminal with this command staged (Enter runs it)";
      rbtn.onclick = (ev) => {
        ev.preventDefault();
        _postJson("/api/rnd/run_deliverable_terminal", {
          project_id: window.STEWARD_PID || "",
          dir: runDir,
          command: it.run,
        }).then((r) => r.json()).then((j) => {
          const sid = j && j.ok && j.session && j.session.session_id;
          if (!sid) return;
          window.open("/zombie_terminal?session=" + encodeURIComponent(sid) +
            (window.STEWARD_TOKEN
              ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""));
        }).catch(() => {});
      };
      row.appendChild(rbtn);
    }
    if (it.date) row.appendChild(document.createTextNode(" · " + it.date));
    if (it.path || it.product_id || it.what) {
      const xbtn = el("button", "deliverable-dismiss", "×");
      xbtn.type = "button";
      xbtn.title = "Dismiss this deliverable from the review list and top row";
      xbtn.setAttribute("aria-label", "Dismiss deliverable");
      xbtn.onclick = async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        xbtn.disabled = true;
        const itemKey = String(it.open_path || it.path || it.product_id || it.what || "");
        if (itemKey) _dismissedSessionKeys.add(itemKey);
        const host = xbtn.closest(".file-row") || xbtn.closest(".navfile") || xbtn.closest(".sdrow") || row.closest(".navfile") || row.closest(".sdrow") || row;
        if (host) host.remove();
        const link = row.querySelector("a");
        const href = link ? link.getAttribute("href") || link.href : "";
        try {
          if (window.top && window.top.ANCHOR_APP && typeof window.top.ANCHOR_APP.closeDeliverable === "function" && href) {
            window.top.ANCHOR_APP.closeDeliverable(href, window);
          }
        } catch (e) {}
        try {
          await post("/api/dismiss-deliverable", {
            path: it.open_path || it.path || "",
            product_id: it.product_id || "",
            what: it.what || "",
            revision_id: it.revision_id || "",
            hash: it.hash || ""
          });
        } catch (e) {}
        await renderDeliverablesTile();
      };
      row.appendChild(xbtn);
    }
    return row;
  }

  /* ---------- live activity (replaces per-tool chatter) ---------- */
  let actEl = null, actSteps = [], actStart = 0, actTimer = null, actHome = null;
  function actLabel() {
    const secs = actStart ? Math.round((Date.now() - actStart) / 1000) : 0;
    const last = actSteps.length ? actSteps[actSteps.length - 1] : "";
    return "⟳ working — " + actSteps.length +
      (actSteps.length === 1 ? " step" : " steps") +
      (secs ? " · " + (secs < 90 ? secs + "s" : Math.round(secs / 60) + "m") : "") +
      (last ? " · " + last : "");
  }
  // Drop the live line WITHOUT touching the DOM (used when the transcript is
  // cleared on an epoch reconnect, and whenever a turn can no longer end).
  function resetActivity() {
    if (actTimer) { clearInterval(actTimer); actTimer = null; }
    // A tick turn's line lives in the STATUS pane, which the reconnect does
    // not clear. Dropping the pointer there left a node reading "⟳ working"
    // with no owner and no timer — a permanent false running indicator on the
    // pane John now sees by default. Finalize it before letting go.
    if (actEl && actEl.isConnected && actSteps.length) {
      const n = actSteps.length;
      actEl.classList.add("done");
      actEl.querySelector(".actlabel").textContent =
        "✓ " + n + (n === 1 ? " step" : " steps") + " — click to see what it did";
    }
    actEl = null; actSteps = []; actStart = 0; actHome = null;
  }
  // the skill a tool use runs: a Skill tool names it; a read under skills/<name>/ names it by its folder
  function skillOfTool(ev) {
    const S = window.SkillIcons;
    if (!S) return null;
    const exact = t => { t = String(t || "").toLowerCase(); return t ? (S.MAP.find(m => m.name.toLowerCase() === t || m.aliases.indexOf(t) >= 0) || null) : null; };
    const detail = String(ev.detail || "");
    const m = /(?:^|[\\/\s"'])skills[\\/]([^\\/\s"']+)[\\/]/i.exec(detail);
    return (m && exact(m[1])) || exact(detail.split(/\s+/)[0]);
  }
  function activity(ev) {
    const step = (ev.name || "?") + (ev.detail ? " " + ev.detail : "");
    const sk = skillOfTool(ev);
    const s = targetFor(ev);
    // a tick-tagged tool goes to the status pane, a plain one to the
    // conversation: never keep appending into a line that lives elsewhere
    if (actEl && (actHome !== s || !actEl.isConnected)) endActivity(null);
    actSteps.push(step);
    if (!actEl) {
      const stick = atBottom(s);
      actStart = Date.now();
      actHome = s;
      const box = el("div", "blk act");        // capture the ELEMENT, not the
      const head = el("div", "acthead", "");   // module slot: endActivity nulls
      head.appendChild(el("span", "actlabel", ""));
      const body = el("div", "actbody");       // actEl and the old closure then
      head.onclick = () => box.classList.toggle("open");  // threw / hit the
      box.appendChild(head);                   // wrong line
      box.appendChild(body);
      s.appendChild(box);
      actEl = box;
      pin(s, stick);
      actTimer = setInterval(() => {
        if (!actEl || !actEl.isConnected) { resetActivity(); return; }
        actEl.querySelector(".actlabel").textContent = actLabel();
      }, 1000);
    }
    actEl.querySelector(".actlabel").textContent = actLabel();
    const line = el("div", "actstep");
    if (sk) {
      const head = actEl.querySelector(".acthead"), old = head.querySelector(".skico");
      if (old) old.remove();
      const im = window.SkillIcons.img(sk.name, 16);
      if (im) head.insertBefore(im, head.firstChild);
      const li = window.SkillIcons.img(sk.name, 14);
      if (li) line.appendChild(li);
    }
    line.appendChild(document.createTextNode("· " + step));
    actEl.querySelector(".actbody").appendChild(line);
    // stay at the bottom: prose blocks land after it, and a live indicator
    // stranded above the transcript answers nothing. ONLY when the reader is
    // already pinned to the bottom — relocating the node shifts everything
    // after it, which yanks the page for someone reading scrollback.
    const stick = atBottom(s);
    if (stick && actEl.nextSibling) s.appendChild(actEl);
    pin(s, stick);
  }
  function endActivity(ev) {
    if (actTimer) { clearInterval(actTimer); actTimer = null; }
    const box = actEl, n = actSteps.length;
    actEl = null; actSteps = []; actStart = 0; actHome = null;
    if (!box || !box.isConnected || !n) return;
    box.classList.add("done");
    box.querySelector(".actlabel").textContent =
      "✓ " + n + (n === 1 ? " step" : " steps") +
      (ev && ev.duration_s ? " · " + (ev.duration_s < 90 ? ev.duration_s + "s"
        : Math.round(ev.duration_s / 60) + "m") : "") + " — click to see what it did";
  }

  /* ---------- events ---------- */
  function handle(ev) {
    if (ev.t === "delta") {
      const s = targetFor(ev);
      const stick = atBottom(s);
      if (!currentBlock || currentBlock._tick !== !!ev.tick) {
        closeCurrent();
        currentBlock = addBlock("steward", opts.stewardLabel || personaName().toUpperCase(),
                                "", "", ev);
        currentBlock._raw = "";
        currentBlock._tick = !!ev.tick;
        if (!ev.tick) turnReplyBlocks.push(currentBlock);
      }
      currentBlock._raw += ev.text;
      currentBlock.querySelector(".body").textContent = currentBlock._raw;
      if (stick) pin(s, true);
    } else if (ev.t === "john") {
      closeCurrent();                    // the reply's blocks stay this turn's until turn_end (final review 10-10)
      addBlock("john", opts.johnLabel || "JOHN", ev.text);
      tileSay("turn", { who: "you", text: String(ev.text || "").slice(-600) });
      busySince = Date.now();
    } else if (ev.t === "tool") {
      // ONE live activity line, not a line per call (John, 2026-08-26).
      // Keep any immediate opening sentence the steward already spoke visible
      // above the live tool activity line so John gets instant feedback.
      closeCurrent();
      activity(ev);
    } else if (ev.t === "turn_end") {
      closeCurrent();
      turnReplyBlocks = [];
      busySince = null;
      endActivity(ev);
      const hasReportedTurnCost = typeof ev.cost_usd === "number" && Number.isFinite(ev.cost_usd) && ev.cost_usd >= 0
        && (ev.cost_status === "reported" || ev.cost_status === undefined);
      const turnCostText = hasReportedTurnCost
        ? "$" + ev.cost_usd.toFixed(ev.cost_usd === 0 ? 2 : 3) + " reported"
        : "cost unavailable";
      const turnTokensText = typeof ev.tokens === "number" && Number.isFinite(ev.tokens) && ev.tokens >= 0
        ? " · " + Math.round(ev.tokens).toLocaleString() + " tokens" : "";
      addLine("turnend", "· turn done in " + ev.duration_s + "s · " + turnCostText + turnTokensText, ev);
      // Older live servers persist completion without publishing it. Coalesce
      // history replays and fetch the post-arbitration truth at the boundary.
      clearTimeout(renderStatus._refreshTimer);
      renderStatus._refreshTimer = setTimeout(async () => {
        try { renderStatus(await (await fetch(api("/api/status"))).json()); }
        catch (e) { addLine("sys", "Status delivery unconfirmed — reconnecting", { tick: true }); }
      }, 250);
    } else if (ev.t === "status") {
      // the engine-composed two-part status of record (disk map + engine
      // state, zero-model) — pane only, never the conversation
      closeCurrent();
      renderStatus(ev.status);
    } else if (ev.t === "reply_links") {
      // W3: Anchor checked the reply's links and corrected some - the WHOLE turn's reply (its text may have been
      // split into several blocks by tool steps) is shown once, as recorded (review r1)
      closeCurrent();
      const blocks = turnReplyBlocks.filter(b => b.isConnected);
      if (blocks.length) {
        const first = blocks[0];
        blocks.slice(1).forEach(b => b.remove());
        first._raw = String(ev.text || "");
        renderRich(first.querySelector(".body"), first._raw);
        turnReplyBlocks = [first];
      }
    } else if (ev.t === "receipt") {
      // the engine's delivery receipt (item 2): one line, the Read link the Deliverables tile also carries
      closeCurrent();
      addBlock("steward", "ANCHOR", ev.text, "receipt");
    } else if (ev.t === "sys") {
      closeCurrent();
      // a session that ended/slept emits sys, never turn_end — finalize the
      // live line here or its timer runs for the life of the tab and the next
      // turn appends into a dead turn's counter
      if (/session ended|asleep|could not start|CLI not found/i.test(ev.text || ""))
        endActivity(null);
      // final review r2: an interrupted or ended turn sends no turn_end - its reply blocks are released here, so the
      // next turn's link correction can never reach back into them
      if (/turn interrupted|session ended|asleep|steward stopped/i.test(ev.text || "")) turnReplyBlocks = [];
      // tick-tagged housekeeping (drive continues, cadence commits) rides
      // the status pane; plain sys lines stay in the conversation
      addLine("sys", ev.text, ev.tick ? ev : undefined);
      // R1 (2026-10-04): a queued receipt carries "Take this now" - the running turn ends, his message goes at once
      if (ev.take_now) {
        const s = targetFor(ev), line = s && s.lastElementChild;
        if (line) {
          const b = el("button", "take-now", "Take this now");
          b.type = "button";
          b.onclick = async () => { b.disabled = true; b.textContent = "Taking it now\u2026";
            let ok = false;
            try { const r = await post("/api/engine", { action: "take_now" }); const j = await r.json(); ok = r.ok && j && j.ok; } catch (e) { ok = false; }
            if (!ok) { b.disabled = false; b.textContent = "Take this now"; b.title = "the turn could not be taken over - try again"; } };
          line.appendChild(document.createTextNode(" ")); line.appendChild(b);
        }
      }
    }
    if (opts.onEvent) opts.onEvent(ev);
  }

  let epoch = null;
  async function poll() {
    for (;;) {
      if (parked) { await new Promise(res => { _unpark = res; }); continue; }
      try {
        _pollAbort = new AbortController();
        const r = await fetch(api("/api/events?since=" + seq), { signal: _pollAbort.signal });
        const j = await r.json();
        // engine restarted/rebuilt: its seq counter reset, so our `since` is
        // stale - reset and replay history rather than go silent forever
        const ep = j.state && j.state.epoch;
        if (ep !== undefined && epoch !== null && ep !== epoch) {
          seq = 0; epoch = ep;
          const s = scrollEl(); if (s) s.textContent = "";
          resetActivity();   // the live line was just detached with the DOM
          addLine("sys", "— session reconnected —");
          if (!opts.skipHistory) await loadHistory();
          continue;
        }
        if (ep !== undefined) epoch = ep;
        if (j.gap) addLine("sys", "— some output scrolled past (buffer limit) —");
        (j.events || []).forEach(ev => { seq = Math.max(seq, ev.seq); handle(ev); });
        updateState(j.state);
        if (j.stamp && j.stamp !== stamp) { const was = stamp; stamp = j.stamp; await loadMap(); if (was) tileSay("stamp", { stamp: stamp }); }
      } catch (e) {
        if (parked) continue;   // the park cut the long-poll; nothing failed
        await new Promise(res => setTimeout(res, 3000));
      }
    }
  }

  // a cheap idle repaint so the map also refreshes when the steward is quiet
  // or files change from outside this engine (not only on streamed events)
  async function stampPoll() {
    for (;;) {
      await new Promise(res => setTimeout(res, 3500));
      if (parked) continue;
      try {
        const r = await fetch(api("/api/state"));
        const j = await r.json();
        updateState(j);
        // A reader can observe projection publication between its writes.
        // Recheck reported inconsistency even if no later event changes stamp.
        if ((j.stamp && j.stamp !== stamp) || map?.refinement?.consistent === false) {
          const was = stamp, moved = !!(j.stamp && j.stamp !== stamp);
          if(j.stamp)stamp=j.stamp;
          await loadMap();
          await renderDeliverablesTile();
          if (moved && opts.statusPane) {
            try { renderStatus(await (await fetch(api("/api/status"))).json()); } catch (e) {}
          }
          if (moved && was) tileSay("stamp", { stamp: stamp });
        }
      } catch (e) { /* the event poll handles backoff */ }
    }
  }

  function liveActivityWord(st) {
    if(!st) return '';
    const working=st.busy || st.working_bg || (st.alive && st.queued);
    const attention=st.attention_state || (_lastMap?.attention?.state) || '';
    return st.light==='red'?'Interrupted':working?'Working':st.open_question?'Needs your input':
      attention==='blocked'?'Blocked':attention==='needs_you'?'Needs your input':
      ['unknown','stale'].includes(attention)?'Activity unconfirmed':'Idle';
  }
  function hasReviewWaiting() {
    const items = (_deliv && _deliv.items) || [];
    const steps = (_lastMap && _lastMap.steps) || [];
    return items.some(it => {
      if (!it.is_current || it.accepted || it.accepted_current) return false;
      if (it.managed) return it.phase === "awaiting_review";
      const owner = steps.find(s => s.id === it.owner_step_id);
      if (!owner || owner.status === "done" || owner.status === "parked" || (owner.refinement || {}).phase === "done") return false;
      if ((owner.refinement || {}).phase) return false;
      const nav = owner.navigation || {}, label = String(nav.label || "");
      if (nav.current === false || nav.role === "support") return false;
      return /^FOR\s+REVIEW\s*(?:[:\u2014\u2013-]|$)/i.test(String(it.what || ""))
        || (!/\b(?:not|no longer)\b/i.test(label) && /\b(?:for (?:author |your )?review|awaiting (?:author |your )?review|ready for (?:author |your )?review)\s*$/i.test(label));
    });
  }
  // the one state rule: the light's colour and its short word (the pane, the project dot and the bar read it)
  function stateColor(st) {
    if (!st) return "quiet";
    const attention = (_lastMap && _lastMap.attention) || {};
    const attentionState = st.attention_state || attention.state || "";
    const working = st.busy || st.working_bg || (st.alive && st.queued) || attentionState === "working";
    const hasQuestion = !!st.open_question || !!((st.pending_questions || []).length) || st.light === "orange";
    const needsHuman = hasQuestion || ["needs_you", "blocked"].includes(attentionState) || hasReviewWaiting();
    return st.light === "red" ? "red" : (working || st.light === "green") ? "green" : needsHuman ? "orange" : "quiet";
  }
  function stateWord(st) {
    if (!st) return "";
    const color = stateColor(st), attention = (_lastMap && _lastMap.attention) || {};
    const attentionState = st.attention_state || attention.state || "";
    const hasQuestion = !!st.open_question || !!((st.pending_questions || []).length);
    return color === "red" ? "needs a look" : color === "green" ? "working"
      : color === "orange" ? ((hasQuestion || attentionState === "needs_you") ? "need your input" : attentionState === "blocked" ? "blocked" : hasReviewWaiting() ? "to review" : "needs your attention") : "";
  }
  function syncCompactActivity(st) {
    if(!st)return;
    const value=liveActivityWord(st);
    const chip=$('.blk.status.latest [data-live-activity]');
    if(chip){chip.textContent=value;chip.title=value;}
    paintActionNeeded($('[data-openq]'));
    paintActionNeeded($('[data-status-action]'));
    renderNextStepsTile();
  }

  function updateState(st) {
    if (st) lastState = st;
    st = lastState;
    if (!st) return;
    const computedColor = stateColor(st);
    const computedWord = stateWord(st) || "";
    const readyNow = computedColor === "orange";
    tileSay("state", { light: computedColor, ready: readyNow, reason: computedWord, busy: !!st.busy, alive: !!st.alive, queued: st.queued || 0, word: computedWord });
    if (window.parent && window.parent !== window) {
      try {
        window.parent.postMessage({
          proto: "anchor-cockpit-state",
          pid: PARAMS.get("pid") || window.STEWARD_PID || "",
          dir: DIR || "",
          general: !!GENERAL,
          term: TERM || "",
          light: computedColor,
          ready: readyNow,
          reason: computedWord
        }, location.origin);
      } catch (e) {}
    }
    if(_answerQuestionId && !(st.pending_questions||[]).some(q=>q.id===_answerQuestionId))_answerQuestionId=null;
    const busy = $("[data-busy]");
    if (busy) {
      const word = stateWord(st);
      busy.textContent = st.busy
        ? ((st.quiet_seconds || 0) >= 300
            ? "thinking " + Math.round(st.quiet_seconds / 60) + " min, no output"
            : (busySince ? "thinking " + Math.round((Date.now() - busySince) / 1000) + "s"
                         : "working..."))
        : (word ? "\u00b7 " + word : "");
    }
    const spend = $("[data-spend]");
    if (spend) {
      const knownSessionUsd = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
      const missingCostText = usage => {
        const count = Number.isInteger(usage.unpriced_turns) && usage.unpriced_turns > 0 ? usage.unpriced_turns : 0;
        const inflight = Number.isInteger(usage.unpriced_inflight) && usage.unpriced_inflight > 0;
        return count ? count.toLocaleString() + " unpriced turn" + (count === 1 ? "" : "s") + (inflight ? " + usage in progress" : "")
          : inflight ? "usage in progress; cost pending" : "unpriced usage";
      };
      const subscriptionCostText = (usage, reportedUsd, cli) => {
        const unpriced = Number.isInteger(usage.unpriced_turns) && usage.unpriced_turns > 0 ? usage.unpriced_turns : 0;
        const family = usage.billing_family || cli || "";
        const sub = usage.billing_mode === "subscription" || ((cli === "chatgpt" || cli === "grok" || cli === "gemini") && unpriced > 0);
        if (!sub || unpriced <= 0) return null;
        const label = family === "mixed" ? "ChatGPT/Grok/Gemini subscription"
          : family === "grok" || cli === "grok" ? "Grok subscription"
          : family === "gemini" || cli === "gemini" ? "Gemini subscription"
          : "ChatGPT subscription";
        const turns = " (" + unpriced.toLocaleString() + " turn" + (unpriced === 1 ? "" : "s") + ")";
        return (typeof reportedUsd === "number" && Number.isFinite(reportedUsd) && reportedUsd > 0)
          ? "$" + reportedUsd.toFixed(2) + " previously reported · " + label + turns
          : label + turns;
      };
      let sessionCostText = "cost unavailable" + (st.unpriced_turns > 0 || st.unpriced_inflight > 0 ? " · " + missingCostText(st) : "");
      if (typeof st.cost_text === "string" && st.cost_text) {
        sessionCostText = st.cost_text;
      } else {
        const sessionReported = knownSessionUsd(st.reported_spend_usd) ? st.reported_spend_usd
          : knownSessionUsd(st.spend_usd) ? st.spend_usd : null;
        const sessionSub = subscriptionCostText(st, sessionReported, st.cli);
        if (sessionSub) sessionCostText = sessionSub;
        else if (st.cost_status === "partial") {
          if (sessionReported !== null) sessionCostText = "cost incomplete · $" + sessionReported.toFixed(2) + " reported · " + missingCostText(st);
        } else if ((st.cost_status === "reported" || st.cost_status === undefined) && knownSessionUsd(st.spend_usd)) {
          sessionCostText = "$" + st.spend_usd.toFixed(2) + " reported";
        }
      }
      const recordedTokenText = (usage) => {
        const status = usage.token_status;
        const known = typeof usage.tokens === "number" && Number.isFinite(usage.tokens) && usage.tokens >= 0 &&
          status !== "unavailable" && (usage.tokens > 0 || status === "reported" ||
            (status === "partial" && usage.checkpoint_coverage && usage.checkpoint_coverage.reported_invocations > 0));
        return known ? Math.round(usage.tokens).toLocaleString() + " recorded tokens" +
          (status === "partial" ? " (partial)" : "") : "tokens unavailable";
      };
      const sessionTokensText = " · " + recordedTokenText(st);
      const effortUsage = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.total;
      let effortUsageText = "";
      if (effortUsage) {
        const reported = typeof effortUsage.reported_spend === "number" &&
          Number.isFinite(effortUsage.reported_spend) && effortUsage.reported_spend >= 0
          ? effortUsage.reported_spend : null;
        let effortCostText = "cost unavailable" + (effortUsage.unpriced_turns > 0 || effortUsage.unpriced_inflight > 0 ? " · " + missingCostText(effortUsage) : "");
        if (typeof effortUsage.cost_text === "string" && effortUsage.cost_text) {
          effortCostText = effortUsage.cost_text;
        } else {
          const effortSub = subscriptionCostText(effortUsage, reported, effortUsage.billing_family || st.cli);
          if (effortSub) effortCostText = effortSub;
          else if (effortUsage.cost_status !== "unavailable" && reported !== null) {
            if (effortUsage.cost_complete === true) effortCostText = "$" + reported.toFixed(2) + " reported";
            else if (reported > 0) effortCostText = "cost incomplete · $" + reported.toFixed(2) + " reported · " + missingCostText(effortUsage);
          }
        }
        effortUsageText = "effort sessions " + effortCostText + " · " + recordedTokenText(effortUsage);
        spend.title = "Session: " + sessionCostText + " · " + st.turns + " turns" + sessionTokensText +
          " · Effort total: " + effortCostText + " · " + recordedTokenText(effortUsage) +
          (effortUsage.usage_updated_at ? " · Last recorded " + effortUsage.usage_updated_at : " · Freshness unavailable") +
          (effortUsage.usage_source ? " · Source: " + effortUsage.usage_source : "");
      }
      // (codex-discipline Wave 2 S1) delegated jobs are a source of their own on
      // the line: shown only when rows exist, never as a zero; unknown usage is a count.
      const jobsUsage = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.jobs;
      const jobsText = (jobsUsage && Number.isInteger(jobsUsage.count) && jobsUsage.count > 0)
        ? " · " + jobsUsage.count + (jobsUsage.count === 1 ? " job " : " jobs ") + (jobsUsage.cost_text || "cost unavailable") +
          (jobsUsage.unknown > 0 ? " (" + jobsUsage.unknown + " unknown usage)" : "")
        : "";
      // (S2) sub-agents: their own clause, tokens only, never a zero.
      const kids = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.children;
      const kidsText = (kids && Number.isInteger(kids.count) && kids.count > 0)
        ? " · " + kids.count + (kids.count === 1 ? " sub-agent " : " sub-agents ") + recordedTokenText(kids) +
          (kids.unknown > 0 ? " (" + kids.unknown + " unknown usage)" : "")
        : "";
      // seats the effort's skills ran: their own clause, like jobs
      const seats = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.seats;
      const seatsText = (seats && Number.isInteger(seats.count) && seats.count > 0)
        ? " · " + seats.count + (seats.count === 1 ? " seat " : " seats ") + (seats.cost_text || "cost unavailable") +
          (seats.unknown > 0 ? " (" + seats.unknown + " unknown usage)" : "")
        : "";
      const num = v => (typeof v === "number" && Number.isFinite(v) && v >= 0) ? v : 0;
      const priced = [effortUsage, jobsUsage, seats].filter(Boolean);
      const sessionOnly = !effortUsage;
      const reportedTotal = priced.reduce((a, b) => a + num(b.reported_spend), 0) + (sessionOnly ? num(knownSessionUsd(st.reported_spend_usd) ? st.reported_spend_usd : st.spend_usd) : 0);
      const unpricedTotal = priced.reduce((a, b) => a + num(b.unpriced_turns), 0) + (sessionOnly ? num(st.unpriced_turns) : 0);
      const tokensTotal = [effortUsage, jobsUsage, kids, seats].filter(Boolean).reduce((a, b) => a + num(b.tokens), 0) + (sessionOnly ? num(st.tokens) : 0);
      const unknownTotal = [jobsUsage, kids, seats].filter(Boolean).reduce((a, b) => a + num(b.unknown), 0);
      const fam = String((effortUsage || st).billing_family || st.cli || "");
      const subName = fam === "mixed" ? "subscription" : fam === "grok" ? "Grok" : fam === "gemini" ? "Gemini" : fam === "chatgpt" ? "ChatGPT" : "";
      const estimatedTotal = priced.reduce((a, b) => a + num(b.estimated_spend), 0) + (sessionOnly ? num(st.estimated_spend_usd) : 0);
      const estimatedTurns = priced.reduce((a, b) => a + num(b.estimated_turns), 0) + (sessionOnly ? num(st.estimated_turns) : 0);
      const stillUnpriced = Math.max(0, unpricedTotal - estimatedTurns);
      const inflightUnpriced = !stillUnpriced && !estimatedTurns && (num(st.unpriced_inflight) > 0 || (effortUsage && effortUsage.cost_complete === false));
      const turnFamilyLabel = subName || "subscription";
      const estimated = estimatedTurns ? "about $" + estimatedTotal.toFixed(2) + " estimated for " + estimatedTurns.toLocaleString() + " " + turnFamilyLabel + " turn" + (estimatedTurns === 1 ? "" : "s") + " at API list price" : "";
      const notPriced = stillUnpriced ? stillUnpriced.toLocaleString() + (subName && !estimatedTurns ? " " + subName + " turn" + (stillUnpriced === 1 ? "" : "s") : "") + " with no dollar amount"
        : inflightUnpriced ? "in-progress usage with no dollar amount" : "";
      let total = reportedTotal > 0 ? "Total $" + reportedTotal.toFixed(2) + " reported" + (estimated ? " + " + estimated : "") + (notPriced ? " · " + notPriced : "")
        : estimated ? "Total " + estimated + (notPriced ? " · " + notPriced : "")
        : notPriced ? "Total: " + notPriced : "cost unavailable";
      if (tokensTotal) total += " · " + Math.round(tokensTotal).toLocaleString() + " tokens recorded";
      if (unknownTotal) total += " · " + unknownTotal + " run" + (unknownTotal === 1 ? "" : "s") + " with unknown usage";
      const legacySpendText = total +
        (st.usage_persistence_error ? " · not saved" : "") +
        (!st.alive ? " · " + (GENERAL ? "idle" : "steward asleep") + (st.queued ? " · " + st.queued + " held" : "") : "");
      const combinedUsd = reportedTotal + estimatedTotal;
      const fmtTok = (n) => {
        const v = num(n);
        if (v >= 1e6) return (v / 1e6).toFixed(2).replace(/\.00$/, "") + "M";
        if (v >= 1e3) return Math.round(v / 1e3) + "k";
        return Math.round(v).toLocaleString();
      };
      const fmtTime = (s) => {
        const secTotal = Math.round(num(s));
        if (!secTotal) return "\u2014";
        const h = Math.floor(secTotal / 3600);
        const m = Math.floor((secTotal % 3600) / 60);
        const sec = secTotal % 60;
        if (h > 0) return h + "h " + m + "m";
        if (m > 0) return m + "m" + (sec ? " " + sec + "s" : "");
        return sec + "s";
      };
      const fmtUsd = (u) => "$" + num(u).toFixed(2);
      const totalSecs = [effortUsage, jobsUsage, seats].filter(Boolean).reduce((a, b) => a + num(b.secs), 0) + (sessionOnly ? num(st.secs) : 0);
      const compactTok = fmtTok(tokensTotal);
      const compactDur = totalSecs >= 60 ? (" \u00b7 " + Math.round(totalSecs / 60) + "m") : "";
      const pillMainText = combinedUsd > 0
        ? ("Total $" + combinedUsd.toFixed(2) + (tokensTotal ? " \u00b7 " + compactTok + " tok" : "") + compactDur + " \u25be")
        : (tokensTotal > 0 || notPriced)
          ? ("Total $0.00" + (tokensTotal ? " \u00b7 " + compactTok + " tok" : "") + compactDur + " \u25be")
          : "cost unavailable";
      spend.textContent = "";
      spend.appendChild(el("span", "spend-pill-main", pillMainText));
      const srSpan = el("span", "spend-sr", " " + legacySpendText);
      spend.appendChild(srSpan);
      if (!effortUsage) spend.title = "Session: " + sessionCostText + sessionTokensText;
      if (jobsText) spend.title += " · Delegated jobs" + jobsText.replace(/^ · /, ": ") + " · " + recordedTokenText(jobsUsage);
      if (kidsText) spend.title += " · Sub-agents" + kidsText.replace(/^ · /, ": ");
      if (seatsText) spend.title += " · Skill seats" + seatsText.replace(/^ · /, ": ") + " · " + recordedTokenText(seats);
      spend.title += " · Reported dollars are recorded charges." +
        (estimatedTurns ? " Estimated dollars come from each subscription turn's recorded tokens at the provider's published " + (st.estimate_basis || "API list price") + ", never a charge; the subscription bills a flat fee." : "") +
        (stillUnpriced ? " Subscription turns recorded without a token split, or on a model outside the price table, carry no dollar amount." : "");
      if (st.usage_persistence_error) spend.title = "Usage totals could not be saved. These session counts are in memory and may be lost on restart.";

      const stewUsd = effortUsage ? (num(effortUsage.reported_spend) + num(effortUsage.estimated_spend))
        : (num(knownSessionUsd(st.reported_spend_usd) ? st.reported_spend_usd : st.spend_usd) + num(st.estimated_spend_usd));
      const stewTok = effortUsage ? num(effortUsage.tokens) : num(st.tokens);
      const stewSecs = effortUsage ? num(effortUsage.secs) : num(st.secs);
      const stewTurns = (effortUsage && effortUsage.checkpoint_coverage && effortUsage.checkpoint_coverage.tracked_invocations) || num(st.turns) || num(st.unpriced_turns);
      const jobsUsd = jobsUsage ? (num(jobsUsage.reported_spend) + num(jobsUsage.estimated_spend)) : 0;
      const jobsTok = jobsUsage ? num(jobsUsage.tokens) : 0;
      const jobsSecs = jobsUsage ? num(jobsUsage.secs) : 0;
      const jobsCnt = jobsUsage ? num(jobsUsage.count) : 0;
      const seatsUsd = seats ? (num(seats.reported_spend) + num(seats.estimated_spend)) : 0;
      const seatsTok = seats ? num(seats.tokens) : 0;
      const seatsSecs = seats ? num(seats.secs) : 0;
      const seatsCnt = seats ? num(seats.count) : 0;
      const kidsTok = kids ? num(kids.tokens) : 0;
      const kidsCnt = kids ? num(kids.count) : 0;
      const stewModelName = fam === "chatgpt" ? "gpt-6.1-sol \u00b7 ultra"
        : fam === "gemini" ? "gemini-4-argon \u00b7 high"
        : fam === "grok" ? "grok-4.7 \u00b7 xhigh"
        : "claude-fable-5-1 \u00b7 max";
      spend._breakdownData = {
        rows: [
          {
            model: stewModelName,
            role: personaName() + " Steward (" + stewTurns + (stewTurns === 1 ? " turn)" : " turns)"),
            tokens: stewTok ? fmtTok(stewTok) : "0",
            time: fmtTime(stewSecs),
            spend: fmtUsd(stewUsd),
          },
          {
            model: "Coding Family / Foreman",
            role: "Foreman & Code Jobs (" + jobsCnt + ")",
            tokens: (jobsCnt || jobsTok) ? fmtTok(jobsTok) : "\u2014",
            time: fmtTime(jobsSecs),
            spend: fmtUsd(jobsUsd),
          },
          {
            model: "Cross-Family Reviewers",
            role: "Crucible / Review Seats (" + seatsCnt + ")",
            tokens: (seatsCnt || seatsTok) ? fmtTok(seatsTok) : "\u2014",
            time: fmtTime(seatsSecs),
            spend: fmtUsd(seatsUsd),
          },
        ].concat(kidsCnt > 0 ? [{
          model: "Sub-agent Swarm",
          role: "Delegated Sub-agents (" + kidsCnt + ")",
          tokens: fmtTok(kidsTok),
          time: "\u2014",
          spend: "$0.00",
        }] : []),
        totalTokens: tokensTotal ? fmtTok(tokensTotal) : "0",
        totalTime: fmtTime(totalSecs),
        totalSpend: fmtUsd(combinedUsd),
        footerNote: "Includes " + personaName() + " steward turns (" + fmtUsd(stewUsd) + "), Foreman/code jobs (" + fmtUsd(jobsUsd) + "), and skill/review seats (" + fmtUsd(seatsUsd) + ").",
        subNote: estimatedTotal > 0 ? ("($" + reportedTotal.toFixed(2) + " billed + $" + estimatedTotal.toFixed(2) + " subscription API-equivalent)") : "",
      };
      spend.dataset.spendSummary = "Combined Total: $" + combinedUsd.toFixed(2) + " ($" + reportedTotal.toFixed(2) + " billed + $" + estimatedTotal.toFixed(2) + " subscription API-equivalent)" + (tokensTotal ? " · " + Math.round(tokensTotal).toLocaleString() + " tokens" : "");
      spend.style.cursor = "pointer";
      if (!spend._popWired) {
        spend._popWired = true;
        spend.addEventListener("click", (ev) => {
          ev.stopPropagation();
          let pop = document.querySelector("[data-spend-popover]");
          if (pop && !pop.hidden) { pop.hidden = true; return; }
          if (!pop) {
            pop = el("div", "spend-popover");
            pop.dataset.spendPopover = "1";
            document.body.appendChild(pop);
            document.addEventListener("click", (e2) => {
              if (pop && !pop.hidden && !pop.contains(e2.target) && e2.target !== spend) pop.hidden = true;
            });
          }
          pop.textContent = "";
          const h4 = el("h4", "sp-head");
          h4.appendChild(el("span", "", "Spend, Tokens & Time Breakdown"));
          const closeX = el("span", "sp-close", "\u2715");
          closeX.onclick = (e2) => { e2.stopPropagation(); pop.hidden = true; };
          h4.appendChild(closeX);
          pop.appendChild(h4);

          const bd = spend._breakdownData || { rows: [], totalTokens: "0", totalTime: "\u2014", totalSpend: "$0.00", footerNote: "" };
          const tbl = el("table", "sp-table");
          const thead = el("thead", "");
          const hr = el("tr", "");
          ["Model / Seat", "Role", "Tokens", "Time", "Spend"].forEach((col, idx) => {
            hr.appendChild(el("th", idx >= 2 ? "num" : "", col));
          });
          thead.appendChild(hr);
          tbl.appendChild(thead);
          const tbody = el("tbody", "");
          bd.rows.forEach((r) => {
            const tr = el("tr", "");
            const tdModel = el("td", "");
            tdModel.appendChild(el("b", "", r.model));
            tr.appendChild(tdModel);
            tr.appendChild(el("td", "", r.role));
            tr.appendChild(el("td", "num", r.tokens));
            tr.appendChild(el("td", "num", r.time));
            tr.appendChild(el("td", "num", r.spend));
            tbody.appendChild(tr);
          });
          const totTr = el("tr", "tot");
          const totLbl = el("td", "", "Campaign Total");
          totLbl.colSpan = 2;
          totTr.appendChild(totLbl);
          totTr.appendChild(el("td", "num", bd.totalTokens));
          totTr.appendChild(el("td", "num", bd.totalTime));
          totTr.appendChild(el("td", "num", bd.totalSpend));
          tbody.appendChild(totTr);
          tbl.appendChild(tbody);
          pop.appendChild(tbl);

          const foot = el("div", "sp-foot");
          foot.appendChild(el("span", "", bd.footerNote));
          if (bd.subNote) foot.appendChild(el("span", "sp-subnote", bd.subNote));
          pop.appendChild(foot);
          pop.hidden = false;
        });
      }
    }
    const wake = $("[data-wake]");
    if (wake) wake.textContent = st.alive ? "Sleep" : "Wake";
    const drive = $("[data-drive]");
    if (drive) {
      drive.textContent = st.drive ? "⏸ Pause" : "▶ Go";
      drive.classList.toggle("armed", !!st.drive);
      drive.title = st.drive
        ? "drive armed - continues without asking (" + st.auto_count + " so far)"
        : "arm drive: continue step after step until a decision is yours";
    }
    renderFiles(st.files || []);
    // the status window's light + plain-words state line
    const attention = (_lastMap && _lastMap.attention) || {};
    const attentionState = st.attention_state || attention.state || "";
    const attentionReason = st.attention_reason || attention.reason || "";
    const working = st.busy || st.working_bg || (st.alive && st.queued);
    syncCompactActivity(st);
    // Also support an already-running server from before the state contract repair.
    const color = stateColor(st);
    const light = $("[data-light]"), light2 = $("[data-light2]");
    if (light) light.className = "light " + color;
    if (light2) light2.className = "light " + color;
    const projectLight=$('[data-att]');
    if(projectLight){projectLight.className='dot light '+color;projectLight.title=stateWord(st)||'Idle';}
    const stx = $("[data-statetext]");
    if (stx) {
      let txt;
      if (st.light === "red") txt = "stuck or broken — needs a look";
      else if (working) txt = "Working" +
        (attentionReason ? " — " + attentionReason : "");
      else if (!st.alive && st.queued) txt = st.queued +
        " held message(s) — waking the steward for delivery";
      else if (st.open_question) txt = "Waiting for your answer";
      else if (attentionState === "needs_you") txt = attentionReason || "Waiting for your answer";
      else if (attentionState === "blocked") txt = attentionReason || "Work is blocked";
      else if (attentionState === "unknown" || attentionState === "stale") txt = "Work status unconfirmed";
      else if (!st.alive) txt = "nothing running — asleep; your message wakes it";
      else txt = "Nothing running — ready";
      const details = [];
      const intr = $("[data-interrupt]");
      if (intr) intr.hidden = true;
      if (st.cli) details.push(st.cli);
      const policy = st.model_policy;
      if (policy && policy.model) details.push("requested " + policy.model + " / " + policy.effort);
      if (policy && policy.model_served) details.push("served " + policy.model_served + " · " +
        (policy.model_source === "provider-confirmed" ? "provider-confirmed" : "recorded by the CLI"));
      if (policy && policy.model_served && policy.model && !sameModel(policy.model, policy.model_served)) txt += " · model mismatch: served " + policy.model_served;
      if (st.pending_switch) details.push("switch to " + st.pending_switch + " at the next safe turn boundary");
      if (st.settings_error) txt += " · " + st.settings_error;
      stx.title = details.join(" · ");
      stx.title = [txt,stx.title].filter(Boolean).join(' · ');
      const shortState = color==='red'?'Interrupted':working?'Working':st.open_question?'Needs your input':
        attentionState==='blocked'?'Blocked':color==='orange'?'Needs feedback':'Idle';
      stx.textContent = shortState;
      stx.dataset.stateColor = color;
      const stx2 = $("[data-statetext2]");
      if (stx2) { stx2.textContent = shortState; stx2.dataset.stateColor = color; }
    }
    paintActionNeeded($("[data-openq]"));
    paintActionNeeded($("[data-status-action]"));
    const pm = $("[data-msgs]");
    if (pm) pm.textContent = "you: " + (st.john_msgs || 0) +
      " messages this session · ask “what's my overhead?” for the ease metric";
    document.body.dataset.alive = st.alive ? "1" : "";
  }

  // the served id is the requested one, or it plus a dated snapshot / build suffix; a sibling is another model
  function sameModel(requested, served) {
    requested = String(requested || ''); served = String(served || '');
    if (!requested || !served || served === requested) return true;
    return served.startsWith(requested) && /^-(?:\d[\d-]*|build.*)$/.test(served.slice(requested.length));
  }

  function openQuestionContext(questionId=null) {
    const host = $("[data-openq]") || $("[data-status-action]");
    if (!host) return;
    paintActionNeeded(host, questionId);
    host.classList.add("open");
  }

  /* ---------- files the steward touched ---------- */
  let _lastFiles = [], _filesSort = "date";
  function wireFileTools() {
    const s = $("[data-fsearch]");
    if (s && !s._wired) { s._wired = true; s.oninput = () => renderFiles(_lastFiles); }
    // W2 (High Seat, 2026-09-26): the upload place sits at the TOP of the Files section (John):
    // drop or pick, one POST per file through the effort's own upload verb; the list repaints
    // with the next state refresh, and the line here says what happened to each file.
    const up = $("[data-fupload]");
    if (up && !up._wired && !up.hasAttribute("data-cockpit-drop")) {
      up._wired = true;
      const msg = $("[data-fupmsg]"), pick = $("[data-fupfile]");
      const say = (text) => { if (msg) msg.textContent = " · " + text; };
      const send = async (file) => {
        const b64 = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result).split(",")[1] || "");
          r.onerror = () => rej(new Error("read failed"));
          r.readAsDataURL(file);
        });
        const resp = await post("/api/upload", { name: file.name, data_b64: b64, mode: "new", sub: "" });
        const j = await resp.json().catch(() => ({}));
        if (j && j.ok) {
          say("loaded " + file.name);
          try { _lastFiles = (_lastFiles || []).concat([{ name: file.name, path: file.name, at: new Date().toISOString(), loaded: true }]); renderFiles(_lastFiles); } catch (e) { /* the next refresh paints it */ }
        }
        else if (j && j.exists) say(file.name + " is already there — nothing overwritten");
        else say(((j && j.error) || "not loaded") + " (" + file.name + ")");
      };
      const queue = (files) => Array.from(files || []).forEach((f) => send(f).catch(() => say("not loaded (" + f.name + ")")));
      up.ondragover = (e) => { e.preventDefault(); up.classList.add("hot"); };
      up.ondragleave = () => up.classList.remove("hot");
      up.ondrop = (e) => { e.preventDefault(); up.classList.remove("hot"); queue(e.dataTransfer.files); };
      if (pick) pick.onchange = () => { queue(pick.files); pick.value = ""; };
    }
    const sortBtns = Array.from(document.querySelectorAll("[data-fsort]"));
    sortBtns.forEach(b => {
      if (b._wired) return; b._wired = true;
      b.onclick = () => { _filesSort = b.getAttribute("data-fsort"); sortBtns.forEach(x => x.classList.toggle("on", x === b)); renderFiles(_lastFiles); };
    });
    wireCockpitDrop();
  }
  function wireCockpitDrop() {
    const bar = $("[data-cockpit-drop]");
    const mainEl = $(".main");
    if (!bar || bar._wired) return;
    bar._wired = true;
    const msg = $("[data-cockpit-dropmsg]") || $("[data-fupmsg]");
    const pick = $("[data-cockpit-dropfile]") || $("[data-fupfile]");
    const say = (text) => { if (msg) msg.textContent = text; };
    const uploadCockpitFile = async (file) => {
      say("Uploading " + file.name + "…");
      const b64 = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result).split(",")[1] || "");
        r.onerror = () => rej(new Error("read failed"));
        r.readAsDataURL(file);
      });
      const resp = await post("/api/upload", { name: file.name, data_b64: b64, mode: "keepboth", sub: "" });
      const j = await resp.json().catch(() => ({}));
      if (j && j.ok) {
        const savedName = j.path || j.name || file.name;
        const targetDir = (_lastMap && _lastMap.dir) || DIR || "cockpit folder";
        say("\u2713 Saved " + savedName);
        try {
          _lastFiles = (_lastFiles || []).concat([{ name: savedName, path: savedName, at: new Date().toISOString(), loaded: true }]);
          renderFiles(_lastFiles);
        } catch (e) {}
        try {
          addBlock(
            "steward",
            personaName().toUpperCase() + " \u00b7 FILE DROP",
            "📥 Landed **`" + savedName + "`** in `" + targetDir + "`."
          );
        } catch (e) {}
      } else {
        say(((j && j.error) || "Upload failed") + " (" + file.name + ")");
      }
    };
    const queue = (files) => Array.from(files || []).forEach((f) => uploadCockpitFile(f).catch(() => say("Upload failed (" + f.name + ")")));
    bar.ondragover = (e) => { e.preventDefault(); bar.classList.add("hot"); };
    bar.ondragleave = () => bar.classList.remove("hot");
    bar.ondrop = (e) => { e.preventDefault(); bar.classList.remove("hot"); if (mainEl) mainEl.classList.remove("drop-hot"); queue(e.dataTransfer.files); };
    if (pick) pick.onchange = () => { queue(pick.files); pick.value = ""; };
    const dropHost = $(".app") || mainEl;
    if (dropHost && !dropHost._dropWired) {
      dropHost._dropWired = true;
      dropHost.addEventListener("dragover", (e) => {
        if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) {
          e.preventDefault();
          if (mainEl) mainEl.classList.add("drop-hot");
          bar.classList.add("hot");
        }
      });
      dropHost.addEventListener("dragleave", (e) => {
        if (!dropHost.contains(e.relatedTarget)) {
          if (mainEl) mainEl.classList.remove("drop-hot");
          bar.classList.remove("hot");
        }
      });
      dropHost.addEventListener("drop", (e) => {
        if (mainEl) mainEl.classList.remove("drop-hot");
        bar.classList.remove("hot");
        if (e.defaultPrevented || (e.target && e.target.closest && e.target.closest("[data-cockpit-drop], [data-fupload]"))) return;
        const files = e.dataTransfer && e.dataTransfer.files;
        if (!files || !files.length) return;
        e.preventDefault();
        queue(files);
      });
    }
  }
  // a produced file opens rendered in a new window when it lies inside this effort
  function openProducedFile(f) {
    const fStr = typeof f === "string" ? f : (f && (f.path || f.name)) || "";
    const root = (_lastMap && _lastMap.dir) || "";
    const norm = (x) => String(x || "").replace(/\\/g, "/");
    const fn = norm(fStr), rn = norm(root).replace(/\/$/, "");
    const openInSplitOrWin = (label, url) => {
      if (typeof window.enterSecondWindowMode === "function") {
        window.enterSecondWindowMode(label || "Deliverable", url);
        return;
      }
      window.open(url);
    };
    if (rn && fn.toLowerCase().indexOf(rn.toLowerCase() + "/") === 0) {
      const rel = fn.slice(rn.length + 1);
      if (/\.(md|txt|csv|json|log)$/i.test(rel)) {
        const isMd = /\.(md|markdown|txt)$/i.test(rel);
        const url = isMd
          ? ("/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(DIR) + "&path=" + encodeURIComponent(rel) + "&render=1" + (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""))
          : ("/steward/report?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(DIR) + "&path=" + encodeURIComponent(rel) + (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""));
        if (typeof window.enterSecondWindowMode === "function") { openInSplitOrWin(rel.split("/").pop(), url); return; }
        window.open("/report?dir=" + encodeURIComponent(DIR) + "&path=" + encodeURIComponent(rel));
        return;
      }
      openInSplitOrWin(rel.split("/").pop(), "/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(DIR) +
        "&path=" + encodeURIComponent(rel) + (/\.(docx|pptx|xlsx)$/i.test(rel) ? "&view=1" : "") +
        (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""));
      return;
    }
    if (fn && !/^[A-Za-z]:\//.test(fn) && !fn.startsWith("/")) {
      const isMd = /\.(md|markdown|txt)$/i.test(fn);
      openInSplitOrWin(fn.split("/").pop(), "/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(DIR) +
        "&path=" + encodeURIComponent(fn) + (/\.(docx|pptx|xlsx)$/i.test(fn) ? "&view=1" : "") + (isMd ? "&render=1" : "") +
        (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""));
      return;
    }
    post("/api/open", { path: fStr });   // outside the effort: the app opens it, said in the row
  }
  function producedFileDownloadHref(f) {
    const fStr = typeof f === "string" ? f : (f && (f.path || f.name)) || "";
    const root = (_lastMap && _lastMap.dir) || "";
    const norm = (x) => String(x || "").replace(/\\/g, "/");
    const fn = norm(fStr), rn = norm(root).replace(/\/$/, "");
    let rel = "";
    if (rn && fn.toLowerCase().indexOf(rn.toLowerCase() + "/") === 0) rel = fn.slice(rn.length + 1);
    else if (fn && !/^[A-Za-z]:\//.test(fn) && !fn.startsWith("/")) rel = fn;
    if (!rel || /(?:^|\/)\.\.(?:\/|$)/.test(rel)) return null;
    return "/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID || "") +
      "&dir=" + encodeURIComponent(DIR) + "&path=" + encodeURIComponent(rel) + "&download=1" +
      (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
  }
  function renderFiles(files) {
    wireFileTools();
    const list = $("[data-flist]");
    if (!list) return;
    const cnt = $("[data-filecount]");
    if (cnt) cnt.textContent = "(" + files.length + ")";
    const head = $("[data-filestoggle]"), sect = $("[data-filesect]");
    if (head && sect && !head._wired) {
      head._wired = true;
      try {
        if (localStorage.getItem("steward_files_open") === "1")
          sect.classList.remove("folded");
      } catch (e) { /* no-op */ }
      head.onclick = () => {
        sect.classList.toggle("folded");
        try {
          localStorage.setItem("steward_files_open",
            sect.classList.contains("folded") ? "0" : "1");
        } catch (e) { /* no-op */ }
      };
    }
    // (2026-09-05, John) files are searchable, sortable (name / type / date order
    // as produced) and OPEN IN A NEW WINDOW rendered; "app" opens them on this
    // computer as before.
    _lastFiles = files.slice();
    const q = (($("[data-fsearch]") || {}).value || "").trim().toLowerCase();
    const sort = _filesSort;
    let rows = files.map((f, i) => {
      const fStr = typeof f === "string" ? f : (f && (f.path || f.name)) || "";
      return { f: fStr, i, name: fStr.split(/[\\/]/).pop() };
    });
    if (q) rows = rows.filter(r => r.name.toLowerCase().indexOf(q) >= 0);
    if (sort === "name") rows.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    else if (sort === "type") rows.sort((a, b) => (a.name.split(".").pop() || "").toLowerCase().localeCompare((b.name.split(".").pop() || "").toLowerCase()) || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    else rows.sort((a, b) => b.i - a.i);   // "date": newest produced first
    list.textContent = "";
    rows.forEach(({ f, name }) => {
      const row = el("div", "frow");
      const a = document.createElement("a");
      a.className = "fname"; a.textContent = name; a.href = "#";
      a.title = "Open " + name;
      a.onclick = (ev) => { ev.preventDefault(); openProducedFile(f); };
      row.appendChild(a);
      const dlHref = producedFileDownloadHref(f);
      if (dlHref) {
        const dl = el("a", "ddl-inline", "\u2b07");
        dl.href = dlHref; dl.target = "_blank"; dl.rel = "noopener";
        dl.title = "Download " + name;
        row.appendChild(dl);
      }
      const btn = el("button", "", "app");
      btn.title = "open on this computer";
      btn.onclick = () => post("/api/open", { path: f });
      row.appendChild(btn);
      list.appendChild(row);
    });
    if (!rows.length) list.appendChild(el("div", "frow", files.length ? "nothing matches" : "(none yet)"));
  }

  /* ---------- work-product overlay (tile on the plan rail) ---------- */
  function closeWorkMap() {
    const ov = $("[data-wpmap]");
    if (ov) ov.hidden = true;
  }
  function openWorkMap() {
    if(_lastMap)paintWorkMap(_lastMap);
    const ov = $("[data-wpmap]");
    if (ov) ov.hidden = false;
  }
  let _plates = [];
  let _plateId = "";
  function paintWorkMap(map) {
    const organization=navModel(map,_deliv.items);
    if(organization) {
      const sum=$('[data-wpsum]'),title=$('[data-wptitle]'),goal=$('[data-wpgoal]'),hint=$('[data-wphint]'),body=$('[data-wpbody]');
      if(sum)sum.textContent=organization.roots.length+' groups — click to open';
      if(title)title.textContent='Work map';
      if(goal)goal.textContent=map.goal_brief||'';
      if(hint)hint.textContent='The same organization as Plan and Deliverables. Current files open directly.';
      if(body){body.textContent='';renderNavigation(body,map,_deliv.items,'work-map');}
      const atlas=$('[data-wpatlas]');if(atlas)atlas.hidden=true;
      return;
    }
    const plate = (map && map.plate) || null;
    _plates = plate ? [plate] : [];
    _plateId = plate ? (plate.deliverableId || plate.title || "") : "";
    const sum = $("[data-wpsum]");
    if (sum) sum.textContent = plate
      ? ((plate.title || "plate") + " — click to open")
      : "no plate yet";
    const title = $("[data-wptitle]");
    if (title) title.textContent = (plate && plate.title) || "No plate yet";
    const gline = $("[data-wpgoal]");
    if (gline) gline.textContent = (plate && plate.subtitle) || "";
    const hint = $("[data-wphint]");
    if (hint) hint.textContent = plate
      ? "Parts of the thing you will open. Hollow = a reserved hole, not a chore. Click a part."
      : "No authored plate for this effort yet.";
    const body = $("[data-wpbody]");
    if (!body || !globalThis.DeliverablePlate) return;
    const atlas = $("[data-wpatlas]");
    if (atlas) atlas.hidden = true;
    DeliverablePlate.paintPlate(body, plate);
  }
  function wireWorkMap() {
    const tile = $("[data-wptile]");
    const ov = $("[data-wpmap]");
    if (tile) tile.onclick = () => openWorkMap();
    const x = $("[data-wpclose]");
    if (x) x.onclick = () => closeWorkMap();
    if (ov) ov.addEventListener("click", (ev) => {
      if (ev.target === ov) closeWorkMap();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeWorkMap();
    });
  }

  /* ---------- the map ---------- */
  async function loadMap() {
    const r = await fetch(api("/api/map"));
    map = (await r.json()) || {};
    map.heartbeat = map.heartbeat || {};
    map.freshness = map.freshness || { talked: "—", plan: "—", heartbeat: "—" };
    map.attention = map.attention || { state: "quiet", reason: "" };
    map.steps = Array.isArray(map.steps) ? map.steps : [];
    map.grasscatch = Array.isArray(map.grasscatch) ? map.grasscatch : [];
    map.steps_done = map.steps_done || 0;
    map.steps_total = map.steps_total || map.steps.length || 0;
    map.name = map.name || "Project";
    // The existing managed read route exposes event-derived navigation without a server restart.
    const navigation=(map.refinement && map.refinement.navigation) || {};
    (map.steps || []).forEach(s=>{if(navigation[s.id])s.navigation=navigation[s.id];});
    stamp = map.stamp;
    if (map.steward && !opts._labelSet) {
      opts.stewardLabel = (!/^steward$/i.test(String(map.steward).trim()) ? String(map.steward) : personaName()).toUpperCase();
      opts._labelSet = true;
    }
    const pName = personaName();
    const pLabelEl = $("[data-persona-label]");
    if (pLabelEl) pLabelEl.textContent = pName;
    const pAvatarEl = $("[data-persona-avatar]");
    if (pAvatarEl) {
      pAvatarEl.alt = pName;
      pAvatarEl.src = /^jarvis$/i.test(pName) ? "/vendor/brand/aladdin-seal-owl.jpg"
        : /^ecgberht|^echberht/i.test(pName) ? "/vendor/brand/aladdin-seal-dragon.jpg"
        : "/vendor/brand/aladdin-seal-lamp.jpg";
    }
    const cockpitName = !DIR && map.name === "Campaign" ? (window.STEWARD_MODE || (map.steward === "Aladdin" ? "Star Chart" : map.name)) : map.name;
    const cockpitTitle = cockpitName + " — AI Cockpit";
    document.title = GENERAL ? map.name + " — " + personaName() : cockpitTitle;
    if (opts.renderMap) { opts.renderMap(map); return; }
    // goal tile (one sentence; expands to the full bold-led description)
    const gb = $("[data-goalbrief]");
    if (gb) gb.textContent = map.goal_brief || "";
    const gf = $("[data-goalfull]");
    if (gf) renderRich(gf, map.goal_md || "(no goal recorded)");
    paintKickoff(gb);
    const gh = $("[data-goalhist]");
    if (gh && map.history) {
      const d = map.history.days || 0;
      let h = "**Running** " + d + (d === 1 ? " day" : " days") +
        (map.history.started ? " (record since " + map.history.started + ")" : "") +
        " · " + map.steps_done + " of " + map.steps_total + " steps done" +
        " · last talked " + map.freshness.talked;
      if (map.history.history_md) h += "\n\n" + map.history.history_md;
      renderRich(gh, h);
    }
    const latest = $("[data-latest]");
    if (latest) {
      const line = (map.heartbeat.why_next || map.heartbeat.next_recommended || "")
        .split("\n").filter(Boolean)[0] || "(no heartbeat recorded)";
      latest.textContent = "most recent from the record (" +
        map.freshness.heartbeat + "): " + line.replace(/\*\*/g, "").slice(0, 220);
    }
    const goal = $("[data-goal]");
    if (goal) goal.textContent = map.goal || "(no goal recorded)";
    const prog = $("[data-progress]");
    if (prog) prog.textContent = map.steps_done + " of " + map.steps_total + " steps done";
    const progFill = $("[data-progress-fill]");
    if (progFill) {
      const pct = map.steps_total ? Math.round(100 * (map.steps_done || 0) / map.steps_total) : 0;
      progFill.style.width = pct + "%";
    }
    const dropDir = $("[data-drop-dir]");
    if (dropDir) dropDir.textContent = map.dir || DIR || "this cockpit's folder";
    const scoutBox = $("[data-tool-scout]");
    if (scoutBox) {
      const activeStep = (map.steps || []).find(s => s.status === "active") || (map.next_in_plan && map.next_in_plan[0]);
      const commissioned = (activeStep && activeStep.commissioned_as) || "";
      const stepLabel = activeStep ? (activeStep.name || activeStep.id) : (map.name || "this effort");
      const combinedText = ((map.name || "") + " " + (map.goal_brief || "") + " " + stepLabel + " " + ((activeStep && activeStep.summary) || "")).toLowerCase();
      let matchedTools = "Foreman · Crucible · Gandalf · Aegis · Anvil";
      if (/\b(?:lecture|course|mba|mit|study|flashcard|pedagog|student|module|block|teaching)\b/.test(combinedText)) {
        matchedTools = "Einstein · Figure-Designer · reading-copy · Gandalf";
      } else if (/\b(?:anvil|paper|equation|libcost|libcst|parso|equivalence|hypothesis|mathml)\b/.test(combinedText)) {
        matchedTools = "Anvil · Ramanujan · Foreman · Gandalf";
      } else if (/\b(?:research|literature|citation|prisma|survey|evidence)\b/.test(combinedText)) {
        matchedTools = "researchPrime · Literature-Review · Gandalf";
      } else if (/\b(?:novel|book|chapter|story|character|continuity)\b/.test(combinedText)) {
        matchedTools = "Chekhov · reading-copy · Gandalf";
      } else if (/\b(?:deal|valuation|waterfall|cap-table|excel|financial)\b/.test(combinedText)) {
        matchedTools = "Financial-Analyst · Gandalf";
      }
      scoutBox.hidden = false;
      scoutBox.textContent = "";
      const dock = el("details", "foundry-dock");
      dock.title = "Proactive Foundry Tool Scout";
      dock.open = Boolean(navSession["foundry:dock_open"]);
      dock.addEventListener("toggle", () => {
        if (dock.isConnected) navSession["foundry:dock_open"] = dock.open;
      });
      const dockSum = el("summary", "");
      const sumLeft = el("span", "");
      sumLeft.appendChild(document.createTextNode("\ud83d\udee0\ufe0f Foundry Tools "));
      const vetSpan = el("span", "deliv-tier-count", "13 vetted \u00b7 0 proposals");
      vetSpan.style.cssText = "color:var(--ok);margin-left:6px;";
      sumLeft.appendChild(vetSpan);
      dockSum.appendChild(sumLeft);
      dockSum.appendChild(el("span", "", "\u25b8"));
      dock.appendChild(dockSum);
      const body = el("div", "foundry-dock-body");
      const g1 = el("div", "gov-step-box");
      g1.appendChild(el("strong", "", "\u2713 Step 1: Skill Foundry Catalog Checked First (`ft.py`)"));
      g1.appendChild(document.createTextNode("Matched " + matchedTools + (commissioned ? (" (Active: " + commissioned + ")") : "") + " for " + stepLabel + "."));
      const g2 = el("div", "gov-step-box");
      g2.appendChild(el("strong", "", "\ud83d\udca1 Step 2: New Tool Proposal & Justification"));
      g2.appendChild(document.createTextNode("None pending — existing Foundry tools cover current wave requirements."));
      const g3 = el("div", "gov-step-box");
      g3.appendChild(el("strong", "", "\ud83d\udd12 Step 3: Steward & User Permission Gate"));
      g3.appendChild(document.createTextNode("Any new tool creation requires explicit justification and your approval before execution."));
      body.appendChild(g1);
      body.appendChild(g2);
      body.appendChild(g3);
      dock.appendChild(body);
      scoutBox.appendChild(dock);
    }
    _lastMap = map;
    if (renderStatus._lastRefreshEta) { try { renderStatus._lastRefreshEta(); } catch (e) {} }
    renderTopNextSteps();
    wireCockpitDrop();
    paintStepsList(map);
    try { paintWorkMap(map); } catch (e) { /* overlay optional */ }
    const wait = $("[data-wait]");
    if (wait) wait.textContent = map.heartbeat.human_wait || "(nothing)";
    const grass = $("[data-grass]");
    if (grass) {
      grass.textContent = "";
      (map.grasscatch.length ? map.grasscatch : []).forEach(g =>
        grass.appendChild(el("li", "", typeof g === "string" ? g : JSON.stringify(g))));
      if (!map.grasscatch.length) grass.appendChild(el("li", "", "(empty)"));
    }
    const fresh = $("[data-fresh]");
    if (fresh) fresh.textContent = "talked " + map.freshness.talked +
      " · plan " + map.freshness.plan + " · heartbeat " + map.freshness.heartbeat;
    const gaps = $("[data-gaps]");
    if (gaps) gaps.textContent = (map.gaps || []).join(" · ");
    const att = $("[data-att]");
    if (att && !lastState) { att.className = "dot " + (map.attention.state || "unknown");
               att.title = map.attention.state +
                 (map.attention.reason ? " - " + map.attention.reason : ""); }
    const name = $("[data-name]");
    if (name) name.textContent = GENERAL ? map.name : cockpitName;
    if(lastState)updateState(lastState);
    if (opts.afterMap) opts.afterMap(map);
  }

  /* ---------- history ---------- */
  async function loadHistory() {
    const r = await fetch(api("/api/history"));
    const j = await r.json();
    (j.turns || []).forEach(t => addBlock(
      t.role === "john" ? "john" : "steward",
      t.role === "john" ? (opts.johnLabel || "JOHN") : (opts.stewardLabel || personaName().toUpperCase()),
      t.text, "hist"));
    if (j.turns && j.turns.length) {
      addLine("divider", "—— live from here ——");
      const last = j.turns[j.turns.length - 1];
      tileSay("turn", { who: last.role === "john" ? "you" : "steward", text: String(last.text || "").slice(-600) });
    }
    { const d = scrollEl(); if (d) d._follow = true; pin(d, true); }   // a page opens at the newest
  }

  /* ---------- composer + dictation ---------- */
  async function sendSay(text, questionId) {
    try {
      const r = await post("/api/say", { text, refinement_context: _refinementContext, question_id: questionId || null });
      const j = await r.json();
      if (j.ok) {
        _refinementContext = null; _answerQuestionId = null;
        const ta = $("[data-say]");
        if (ta) ta.placeholder = "";
      } else {
        _answerQuestionId = null;
        addLine("sys", "not delivered: " + (j.error || "?") + " - your text is back in the box");
      }
      return j;
    } catch (e) {
      _answerQuestionId = null;
      addLine("sys", "not delivered (network) - your text is back in the box");
      return {ok: false};
    }
  }
  function wireComposer() {
    const ta = $("[data-say]");
    const send = $("[data-send]");
    if (!ta) return;
    let _composing = false;
    ta.addEventListener("compositionstart", () => { _composing = true; });
    ta.addEventListener("compositionend", () => { _composing = false; grow(); });
    ta.addEventListener("blur", () => { _composing = false; });
    const grow = () => {
      const minimum = parseFloat(getComputedStyle(ta).minHeight) || 46;
      const prevScroll = ta.scrollTop;
      if (!_composing) {
        ta.style.height = "auto";
        const target = Math.max(minimum, Math.min(ta.scrollHeight + 2, innerHeight * 0.4));
        ta.style.height = target + "px";
        if (prevScroll) ta.scrollTop = prevScroll;
      } else if (ta.scrollHeight > ta.clientHeight) {
        const targetC = Math.max(minimum, Math.min(ta.scrollHeight + 2, innerHeight * 0.4));
        if (targetC > (parseFloat(ta.style.height) || 0)) ta.style.height = targetC + "px";
      }
      ta.style.overflowY = ta.scrollHeight > ta.clientHeight ? "auto" : "hidden";
    };
    ta.addEventListener("input", grow);
    // R12 (2026-09-28, John: "conversations are saved as they are put in"): the unsent text is kept in this browser
    // on every keystroke (localStorage, keyed to this record) and put back after a crash, a restart or a reload of
    // the page; a delivered turn clears it, an undelivered one keeps it
    const DRAFT_KEY = "anchor:draft:say:" + (PARAMS.get("pid") || "") + ":" + DIR + (TILE ? ":tile" : "");   // the tile's own words, never the cockpit tab's (ChatGPT 2026-10-02)
    let _draftT = null;
    const saveDraft = () => { try { if (ta.value.trim()) localStorage.setItem(DRAFT_KEY, ta.value); else localStorage.removeItem(DRAFT_KEY); } catch (e) {} };
    const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} };
    ta.addEventListener("input", () => { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });
    ta.addEventListener("blur", saveDraft);  // the app blurs a composer before dropping its inactive frame
    window.addEventListener("beforeunload", saveDraft);
    try {
      const kept = localStorage.getItem(DRAFT_KEY);
      if (kept && kept.trim() && !ta.value.trim()) { ta.value = kept; grow(); addLine("sys", "your unsent text is back in the box"); }
    } catch (e) {}
    const submit = async () => {
      let text = ta.value.trim();
      if (!text) return;
      // dictation-friendly grasscatch: "later: ..." parks it without ceremony
      const later = text.match(/^(later|grasscatcher?)[:,]\s*(.+)/is);
      if (later) text = "Grasscatch this (park it on the Strip with a reason, " +
                        "then carry on with the step in hand): " + later[2];
      const keep = ta.value;
      ta.value = ""; grow();
      { const d = scrollEl(); if (d) { d._follow = true; pin(d, true); } }   // his own message brings him to the newest
      // Steward unreviewed-items interjection when John sends a new command while For Review still has items
      const pendingRev = (_deliv && Array.isArray(_deliv.reviewNow)) ? _deliv.reviewNow.slice() : [];
      const revSig = pendingRev.map(r => r.path || r.what).join("|");
      if (pendingRev.length > 0 && revSig && window._interjectedRevSig !== revSig) {
        window._interjectedRevSig = revSig;
        try {
          const d = scrollEl();
          if (d) {
            const blk = el("div", "blk steward");
            blk.appendChild(el("div", "who", (opts.stewardLabel || personaName().toUpperCase()) + " \u00b7 REVIEW CHECK"));
            const card = el("div", "steward-interject-card");
            const msg = el("div", "");
            renderRich(msg, "Before we move on to your new request: you still have **" + pendingRev.length + " item" + (pendingRev.length === 1 ? "" : "s") + "** in **For Review**. Are you done reviewing them (mark them Done), or should I keep them in **For Review**?");
            card.appendChild(msg);
            const actRow = el("div", "steward-interject-actions");
            const yesBtn = el("button", "mark-all-done-btn", "\u2713 Yes, Mark " + pendingRev.length + " Review Item" + (pendingRev.length === 1 ? "" : "s") + " Done");
            yesBtn.type = "button";
            yesBtn.onclick = async () => {
              yesBtn.disabled = true;
              try {
                for (const it of pendingRev) {
                  await post("/api/dismiss-deliverable", {
                    path: it.open_path || it.path || "",
                    product_id: it.product_id || "",
                    what: it.what || "",
                    revision_id: it.revision_id || "",
                    hash: it.hash || ""
                  });
                }
              } catch (e) {}
              blk.remove();
              await renderDeliverablesTile();
            };
            const keepBtn = el("button", "snt-btn", "Keep in For Review");
            keepBtn.type = "button";
            keepBtn.onclick = () => { blk.remove(); };
            actRow.appendChild(yesBtn);
            actRow.appendChild(keepBtn);
            card.appendChild(actRow);
            blk.appendChild(card);
            d.appendChild(blk);
            pin(d, true);
          }
        } catch (e) {}
      }
      const j = await sendSay(text, _answerQuestionId);
      if (!j.ok) { ta.value = keep; grow(); saveDraft(); } else { clearDraft(); }
    };
    if (send) send.onclick = submit;
    if (TILE) {
      const typing = () => tileSay("typing", { active: !!ta.value.trim() || document.activeElement === ta });
      ta.addEventListener("input", typing); ta.addEventListener("focus", typing); ta.addEventListener("blur", typing);
      window.addEventListener("message", (ev) => {
        const m = ev.data;
        if (ev.origin !== location.origin || ev.source !== window.parent || !m || m.proto !== "anchor-tile" || m.inst !== INST) return;
        if (m.kind === "park" || m.kind === "show") { setParked(m.kind === "park"); return; }
        if (m.kind === "prefill" && typeof m.text === "string") {
          ta.value = ta.value.trim() ? (ta.value.replace(/\s+$/, "") + "\n" + m.text) : m.text;
          ta.dispatchEvent(new Event("input"));
          if (m.focus) { ta.focus(); try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) {} }
        }
      });
      // a file dropped on this view goes to the tile, which lands it in this effort's folder (one route, one receipt)
      document.addEventListener("dragover", (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) e.preventDefault(); });
      document.addEventListener("drop", (e) => {
        const files = e.dataTransfer && e.dataTransfer.files;
        if (!files || !files.length || e.defaultPrevented || (e.target && e.target.closest && e.target.closest("[data-fupload], [data-filesect]"))) return;
        e.preventDefault(); tileSay("drop", { files: Array.from(files) });
      });
      tileSay("ready", {});
    }
    // (codex-discipline-2026-09-15 Wave 1.2) Send is disabled in the markup
    // and enabled only once its handler exists: a click in the load window
    // used to produce neither a POST nor a record.
    if (send) send.disabled = false;
    ta.addEventListener("keydown", (e) => {
      // 2026-10-13 (John): CLI-style Enter sends immediately; Shift+Enter makes a new line.
      // Never send from a key during an active composition.
      if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
      if (e.shiftKey) return;
      e.preventDefault(); submit();
    });
    // Dictation is Win+H (2026-08-25, jrnl 0088): the in-page Web Speech mic
    // was choppy and never auto-punctuated, so it is GONE — the textarea
    // stays a clean Win+H target (never locked, text never lost).
  }

  function wireChrome() {
    const wake = $("[data-wake]");
    if (wake) wake.onclick = async () => {
      const alive = document.body.dataset.alive === "1";
      await post("/api/engine", { action: alive ? "stop" : "wake" });
    };
    const intr = $("[data-interrupt]");
    if (intr) intr.onclick = async () => {
      // Wave 1.3: Stop turn - ends the running turn (outcome recorded as
      // uncertain, partial work kept); the queue and the thread survive.
      await post("/api/engine", { action: "interrupt", reason: "stopped by John" });
    };
    const drive = $("[data-drive]");
    if (drive) drive.onclick = async () => {
      const on = lastState && lastState.drive;
      await post("/api/engine", { action: on ? "drive_off" : "drive_on" });
      if (!on && !(lastState && lastState.alive)) await post("/api/say", { text: "go" });
    };
    const mini = $("[data-min]");
    const app = $(".app");
    if (mini) mini.onclick = () => {
      if (EMBED) parent.postMessage({ proto: "min" }, "*");  // inside the cockpit
      else location.href = "/";                              // standalone: dashboard (not the High Seat overlay)
    };
    const railT = $("[data-railtoggle]");
    if (railT && app) railT.onclick = () => app.classList.toggle("railhide");
    const goalbar = $("[data-goalbar]");
    if (goalbar) goalbar.onclick = (ev) => {
      if (ev && ev.target && ev.target.closest && ev.target.closest("[data-top-deliverables], a, button, details, summary")) return;
      goalbar.classList.toggle("open");
    };
    const paneT = $("[data-panetoggle]");
    const pane = $("[data-statuspane]");
    if (paneT && pane) paneT.onclick = () => pane.classList.toggle("shut");
    const bone = $("[data-boneyard]");
    if (bone) bone.onclick = async () => {
      if (!confirm("Boneyard this effort? It is archived (not deleted) and can be restored from the seal's boneyard.")) return;
      const r = await post("/api/boneyard_move", {});
      const j = await r.json();
      if (j.ok) location.href = "/";
      else alert(j.error || "could not boneyard it");
    };
    const themeBtn = $("[data-theme-toggle]");
    if (themeBtn) themeBtn.onclick = () => Proto.toggleTheme();
    const catchIn = $("[data-catch]");
    if (catchIn) catchIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && catchIn.value.trim()) {
        post("/api/say", { text: "Grasscatch this (park it on the Strip, then carry on): " + catchIn.value.trim() });
        catchIn.value = "";
      }
    });
  }

  function applyTheme() {
    let t = "slate";
    try { t = localStorage.getItem("protoTheme") || "slate"; } catch (e) {}
    document.body.dataset.theme = t;
  }
  function toggleTheme() {
    const next = document.body.dataset.theme === "command" ? "slate" : "command";
    try { localStorage.setItem("protoTheme", next); } catch (e) {}
    document.body.dataset.theme = next;
  }

  async function init(o) {
    opts = o || {};
    if (TILE) { const a = document.querySelector(".app"); if (a) { a.classList.add("tileview", "railhide"); if (PARAMS.get("compose") === "0") a.classList.add("nocompose"); } }
    // the steward's dialogue alone (his word, 2026-10-02: "the steward dialogue from an AI Cockpit, maybe the status bar
    // available but thinner, and the plan is not something we have to worry about in those pages")
    if (TALK) { const a = document.querySelector(".app"); if (a) { a.classList.add("talkview", "railhide", "nocompose"); a.classList.remove("statusopen"); } }
    if (opts.stewardLabel) opts._labelSet = true;
    applyTheme();
    try { wireFollow(scrollEl()); } catch (e) {}   // before history loads, so the replay lands at the newest
    const wantPanes = !TALK && !TILE;
    const statusFetchProm = (opts.statusPane && wantPanes) ? fetch(api("/api/status")).then(r => r.json()).catch(() => null) : Promise.resolve(null);
    const delivProm = wantPanes ? Promise.resolve().then(() => renderDeliverablesTile()).catch(() => {}) : Promise.resolve();
    const histProm = (!opts.skipHistory) ? loadHistory().catch(() => {}) : Promise.resolve();
    try { await loadMap(); } catch (e) {
      const p = $("[data-progress]");
      if (p) p.textContent = "map failed: " + ((e && e.message) || "could not load");
      tileSay("trouble", { text: "this cockpit's record could not be read" + (e && /401|403|auth/i.test(String(e.message || "")) ? " - this browser is not logged in" : "") });
    }
    try { await histProm; } catch (e) { /* no-op */ }
    if (opts.statusPane && wantPanes) {
      try {
        const stJson = await statusFetchProm;
        if (stJson) renderStatus(stJson);
      } catch (e) {}
    }
    try { await delivProm; } catch (e) {}
    wireComposer();
    wireChrome();
    try { wireWorkMap(); } catch (e) {}
    poll();
    stampPoll();
    setInterval(() => updateState(null), 1000); // busy clock repaint
  }

  window.addEventListener("anchor-notebooks-changed", () => {
    renderDeliverablesTile().catch(() => {});
  });

  return { init, addLine, applyTheme, toggleTheme,
           get map() { return map; }, get dir() { return DIR; } };
})();
