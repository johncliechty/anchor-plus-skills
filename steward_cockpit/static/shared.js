/* steward-proto shared client. Safe rendering: model text goes through
   textContent-based builders only - no innerHTML anywhere.
   All API calls carry the effort's dir (?dir=<rel>) so one server hosts
   several steward efforts at once. */
"use strict";

const Proto = (() => {
  const PARAMS = new URLSearchParams(location.search);
  const DIR = PARAMS.get("dir") || "";
  const GENERAL = PARAMS.get("general") === "1";
  const TERM = PARAMS.get("term") || "";
  const EMBED = PARAMS.get("embed") === "1";
  let seq = 0, stamp = "", busySince = null, currentBlock = null,
      opts = {}, map = null, lastState = null, latestStatusId = "";

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

  /* ---------- kickoff (Gate 5 canary, 2026-09-01) ----------
     The confirmed kickoff is the goal's AUTHORITATIVE form (confirmed intent has
     display precedence; the tag-derived map is fallback only), so it paints FIRST
     inside the Goal bar. The prose comes from the engine's projection (rendered
     from the hashed record — never composed here); an open draft paints as one
     plain "not applied" line; anything else paints nothing. XHR on purpose: the
     client shim rewrites fetch('/api/…') to /api/steward/, and this route is
     Anchor's own GET /api/ecgberht/kickoff_show. Read-only; never throws. */
  // the one-line status of record shown in the top bar (2026-09-03); once a
  // status has painted it, map repaints and the kickoff paint leave it alone
  let _statusLine = "";
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
          if (m && m[1] && !_statusLine) briefEl.textContent = m[1].trim();
        }
      } else if (j.state === "open" && j.open_draft && j.open_draft.applied === false) {
        box.classList.add("draft");
        if (briefEl && j.open_draft.goal && !_statusLine) briefEl.textContent = "draft, not applied — " + j.open_draft.goal;
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
    return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  }
  function pin(s, force) {
    if (s && (force || atBottom(s))) s.scrollTop = s.scrollHeight;
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
  function closeCurrent() {
    if (currentBlock) {
      const body = currentBlock.querySelector(".body");
      renderRich(body, currentBlock._raw || body.textContent);
      currentBlock = null;
    }
  }

  /* ---------- the deterministic 10-minute status (engine-composed) ----------
     Two parts: NOW (what is running — the steward's turn AND commissioned/
     background runs) over PLAN (step n/m · waiting-on-you · next). Rendered
     into the RIGHT STATUS PANE only — never the conversation. The same shape
     is persisted server-side to .ecgberht/status-summary.json for the
     main-dashboard tile. */
  function renderStatus(stat) {
    const s = paneEl();
    if (!s || !stat) return;
    const statusId = String(stat.status_id || "");
    // The fresh status painted on open must not be replaced by an older
    // status event replayed from the engine buffer.
    if (statusId && latestStatusId && statusId <= latestStatusId) return;
    if (statusId) latestStatusId = statusId;
    const stick = atBottom(s);
    // only the newest status stays expanded (same fold rule as tick turns)
    s.querySelectorAll(".blk.steward:not(.folded)").forEach(old => {
      old.classList.add("folded");
      old.onclick = () => old.classList.toggle("folded");
    });
    const b = el("div", "blk steward status");
    const hhmm = (stat.at || "").slice(-5);
    const who = el("div", "who", "⏱ " + hhmm + " · STATUS");
    if (stat.stale) who.appendChild(el("span", "stale",
      " · last update on record — nothing has run since"));
    b.appendChild(who);
    const body = el("div", "body");
    const p = stat.plan || {};
    // John's locked 10-minute format (AGENTS.md status block, 2026-09-03):
    // every row is present every time; a fact the engine does not have is an
    // honest dash, never a guess.
    const goal = (_lastMap && (_lastMap.goal_brief || _lastMap.goal)) || "";
    const nowLine = (stat.now || []).join(" · ");
    const seats = (stat.swarm || []).map(x => (x.label || "seat") + " · " + (x.state || "?"));
    // (2026-09-04, John) the status is about the CURRENT SLICE, looked through
    // the steward to the skill it runs; what's next is <=3 short bullets; the
    // whole map lives in the goal bar, not here.
    const sl = stat.slice || null;
    const run = stat.running || null;
    const proj = stat.project || {};
    const sliceLine = sl ? ("Slice " + sl.n + "/" + sl.total + " · " + sl.name +
      (sl.summary ? " — " + sl.summary : "")) : "";
    const doingLine = (run && run.label) || nowLine;
    const bullets = (stat.next_bullets && stat.next_bullets.length) ? stat.next_bullets
      : (p.next ? [p.next] : []);
    const todo = bullets.length ? el("ul", "stodo") : null;
    if (todo) bullets.slice(0, 3).forEach(t => todo.appendChild(el("li", "", t)));
    const rows = [
      ["Summary", sliceLine || goal || "—", !sliceLine && !goal],
      ["Effort", (stat.effort || "—") + (proj.brief ? " — " + proj.brief : ""), !stat.effort],
      ["Doing", doingLine || "—", !doingLine],
      ["Status", hhmm + " · " + (p.step || "(no active step)") + " · " +
        (p.steps_done || 0) + "/" + (p.steps_total || 0) + " done · attention: " +
        (p.attention || "unknown"), false],
      ["Tests", stat.tests || "—", !stat.tests],
      ["Blocker", p.waiting_on_you ? "waiting on you: " + p.waiting_on_you : "none",
        false, !!p.waiting_on_you],
      ["Procs", seats.length ? seats.join(" · ")
        : ((run && run.kind === "skill") ? run.skill + " (commissioned)" : "none"), false],
      ["Journal", stat.journal || "—", !stat.journal],
      ["ETA", stat.eta || "—", !stat.eta],
      ["To do", todo || "—", !todo],
    ];
    const tab = el("table", "stab");
    rows.forEach(([k, v, dim, flag]) => {
      const tr = el("tr", flag ? "flag" : "");
      tr.appendChild(el("th", "", k));
      const isNode = !!(v && v.nodeType);
      const td = el("td", dim ? "dim" : "", isNode ? "" : v);
      if (isNode) td.appendChild(v);
      tr.appendChild(td);
      tab.appendChild(tr);
    });
    body.appendChild(tab);
    if (p.goal_reread === false)
      body.appendChild(el("div", "splan sflag", "goal not re-read since last close"));
    b.appendChild(body);
    s.appendChild(b);
    pin(s, stick);
    // the window's header carries the time of the last update (idle projects
    // show their LAST update, stamped, not a fresh blank)
    const stamp = $("[data-statusstamp]");
    if (stamp) stamp.textContent = "last update " + hhmm + (stat.stale ? " · idle" : "");
    // the top bar is the ONE-LINE status of record for this steward run
    // (John, 2026-09-03); the goal moves inside the bar, one click away
    try {
      const brief = $("[data-goalbrief]"), lab = $("[data-goallabel]");
      if (brief) {
        // what is running (looked through) · the slice · its ETA
        let line = (run && run.label) || (stat.now || [])[0] || "quiet";
        if (sl) line += " · slice " + sl.n + "/" + sl.total + " " + sl.name;
        else line += " · " + (p.steps_done || 0) + "/" + (p.steps_total || 0) + " done";
        if (p.waiting_on_you) line += " · waiting on you: " + p.waiting_on_you;
        else if (stat.eta) line += " · ETA " + stat.eta;
        if (line.length > 120) line = line.slice(0, 117).replace(/\s+\S*$/, "") + "…";
        _statusLine = line + (stat.stale ? "  (" + hhmm + ")" : "");
        brief.textContent = _statusLine;
        if (lab) lab.textContent = "Status";
      }
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
  let _delivItems = [], _lastMap = null;
  let _delivOpen = (() => {
    try { return localStorage.getItem("steward_deliv_open") === "1"; }
    catch (e) { return false; }
  })();
  function stepDeliverables(stepName, idx1) {
    return _delivItems.filter((it) => {
      const s = (it.step || "").trim();
      if (!s) return false;
      if (/^\d+$/.test(s)) return parseInt(s, 10) === idx1;
      return (stepName || "").toLowerCase().indexOf(s.toLowerCase()) >= 0;
    });
  }
  // One blue SENTENCE under its step. Click once → the detail; click the
  // detail's link → the report itself (John's two-stage disclosure).
  function stepDelivLine(it) {
    const row = el("div", "sdrow");
    const one = (it.what || "").split(" — ")[0].trim() || it.what || "(untitled)";
    const line = el("div", "sdone", "▸ " + one);
    const detail = el("div", "sddetail");
    const full = el("div", "", it.what || "");
    detail.appendChild(full);
    if (it.date) detail.appendChild(el("div", "sdmeta", it.date));
    detail.appendChild(delivRow(it));           // the actual open link
    // the detail already carries the full description above; the link itself
    // just says what it does (2026-09-03)
    const lnk = detail.querySelector(".drow a");
    if (lnk) lnk.textContent = "Open ↗" + (it.path ? "  " + it.path : "");
    const key = (it.dir || "") + "|" + (it.path || it.what || "");
    if (_openDelivs.has(key)) row.classList.add("open");
    line.onclick = (ev) => {
      ev.stopPropagation();
      row.classList.toggle("open");
      if (row.classList.contains("open")) _openDelivs.add(key);
      else _openDelivs.delete(key);
    };
    row.appendChild(line);
    row.appendChild(detail);
    return row;
  }
  // What the USER opened, kept across repaints. paintStepsList rebuilds every
  // <li> and it runs on every map-stamp change (the steward rewrites the map
  // constantly) and on every register load — without this, a click collapsed
  // again within seconds.
  const _openSteps = new Set(), _openDelivs = new Set();
  function paintStepsList(map) {
    const list = $("[data-steps]");
    if (!list) return;
    list.textContent = "";
    map.steps.forEach((st, i) => {
      const li = el("li", st.status);
      const mark = { done: "✓", active: "▶", waiting: "⚑" }[st.status] || "○";
      li.appendChild(el("span", "mark", mark));
      const wrap = el("div");
      // a flex item defaults to min-width:auto, which nowrap text resolves to
      // the full string width — the rail then grows a horizontal scrollbar
      // instead of ellipsizing the blue line
      wrap.style.minWidth = "0";
      const title = el("div", "");
      if (st.part) title.appendChild(el("span", "wpkind", st.part));
      title.appendChild(document.createTextNode(st.name));
      wrap.appendChild(title);
      const parts = [];
      // live feedback rides the map: the active step says what is
      // happening now; waiting steps say what they wait on
      if (st.status === "active") {
        const live = map.attention.state === "working"
          ? (map.attention.reason || "running now")
          : (map.heartbeat.next_recommended || "");
        if (live) parts.push("now: " + live.replace(/\*\*/g, ""));
      }
      if (st.status === "waiting" && st.waiting_on)
        parts.push("waiting on: " + st.waiting_on);
      if (st.done_when) parts.push("done when: " + st.done_when);
      if (st.commissioned_as) parts.push("ran as: " + st.commissioned_as);
      // no filler: a step with nothing recorded shows nothing
      if (parts.length) wrap.appendChild(el("div", "why", parts.join("\n")));
      // The plan must stay SCANNABLE (John, 2026-08-26: "it should not open
      // up and give me all the details ... has to be really tight and tidy").
      // Three levels, each a deliberate click:
      //   1. step name (+ a one-SENTENCE blue line per deliverable)
      //   2. click the step  -> its why/done-when detail
      //   3. click a deliverable -> its detail, click again -> the report
      const dl = stepDeliverables(st.name, i + 1);
      if (dl.length) {
        const box = el("div", "sdeliv");
        dl.forEach((it) => box.appendChild(stepDelivLine(it)));
        wrap.appendChild(box);
      }
      li.appendChild(wrap);
      const stepKey = st.name || String(i);
      if (_openSteps.has(stepKey)) li.classList.add("open");
      li.onclick = (ev) => {
        if (ev.target.closest(".sdeliv")) return;   // deliverables own their clicks
        li.classList.toggle("open");
        if (li.classList.contains("open")) _openSteps.add(stepKey);
        else _openSteps.delete(stepKey);
      };
      list.appendChild(li);
    });
  }
  async function renderDeliverablesTile() {
    if (_delivBusy) return;
    _delivBusy = true;
    let d = null;
    try { d = await (await fetch(api("/api/deliverables"))).json(); }
    catch (e) { _delivBusy = false; return; }
    _delivBusy = false;
    const items = (d && d.items) || [];
    _delivItems = items;
    // repaint the plan so step-tagged deliverables land under their steps
    if (_lastMap) { try { paintStepsList(_lastMap); } catch (e) {} }
    // — the tile: its OWN slot above the scrollport when the page provides
    //   one (never overlaps the status blocks), else the pane as before —
    const s = $("[data-delivmount]") || paneEl();
    if (s) {
      let tile = s.querySelector(".blk.deliv");
      // starts CLOSED so the status keeps the room; his choice then sticks
      const wasOpen = tile ? !tile.classList.contains("folded")
                           : (_delivOpen === true);
      if (!tile) {
        tile = el("div", "blk steward deliv folded");
        s.insertBefore(tile, s.firstChild);
      } else tile.textContent = "";
      if (wasOpen) tile.classList.remove("folded");
      // one-line summary in the header, so a folded tile still tells him what
      // is in there (John, 2026-08-27: "deliverables on top with a little
      // summary above that")
      // "newest" must BE the newest: the register is parsed in file order and
      // its own convention (newest-first) is a convention, not a guarantee —
      // labelling items[0] as newest silently lied whenever a steward
      // appended. Pick by date, fall back to file order.
      const byDate = items.slice().sort((a, b) =>
        String(b.date || "").localeCompare(String(a.date || "")));
      const newest = byDate.length
        ? (byDate[0].what || "").split(" — ")[0].trim() : "";
      const who = el("div", "who",
        "📦 DELIVERABLES (" + items.length + ")" +
        (newest ? " — newest: " + newest : " — nothing registered yet"));
      who.style.cursor = "pointer";
      who.onclick = () => {
        tile.classList.toggle("folded");
        _delivOpen = !tile.classList.contains("folded");
        try { localStorage.setItem("steward_deliv_open",
                                   _delivOpen ? "1" : "0"); } catch (e) {}
      };
      tile.appendChild(who);
      const body = el("div", "body");
      if (!d || !d.exists) {
        body.appendChild(el("div", "snow", "No DELIVERABLES.md yet — the steward starts the register when the first human-facing artifact lands."));
      } else if (!items.length) {
        body.appendChild(el("div", "snow", "(register is empty)"));
      }
      // ONE line each (John, 2026-09-03): click → the long description →
      // click its link → the deliverable opens in a new window
      items.forEach((it) => body.appendChild(stepDelivLine(it)));
      tile.appendChild(body);
      if (s.firstChild !== tile) s.insertBefore(tile, s.firstChild);
    }
    // — the goal/map links —
    const slot = $("[data-deliverables]");
    if (slot) {
      slot.textContent = "";
      if (items.length) {
        slot.appendChild(el("div", "glabel", "Deliverables"));
        items.forEach((it) => slot.appendChild(stepDelivLine(it)));
      }
    }
  }
  function delivRow(it) {
    const row = el("div", "snow drow");
    if (it.openable && it.path) {
      const a = document.createElement("a");
      a.textContent = "• " + it.what;
      // 2026-08-26 (John: "I click on them and the page had nothing"): a raw
      // <a href> NAVIGATES — it never passes through the fetch shim, so the
      // old api() URL arrived with no /api/steward/ prefix, no pid and no
      // token → a blank page. Build the FULL authed URL ourselves, and send
      // text docs (.md/.txt/.csv/.json/.log) through the report VIEWER so
      // they render human-readable instead of as raw bytes.
      const dirRel = it.dir !== undefined ? it.dir : DIR;
      const isText = /\.(md|txt|csv|json|log)$/i.test(it.path);
      if (isText) {
        a.href = "#";
        a.onclick = (ev) => { ev.preventDefault();
          window.open("/report?dir=" + encodeURIComponent(dirRel) +
                      "&path=" + encodeURIComponent(it.path)); };
      } else {
        a.href = "/api/steward/deliverable-file?pid=" +
          encodeURIComponent(window.STEWARD_PID || "") +
          "&dir=" + encodeURIComponent(dirRel) +
          "&path=" + encodeURIComponent(it.path) +
          (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
        a.target = "_blank";
        a.rel = "noopener";
      }
      row.appendChild(a);
    } else {
      row.appendChild(document.createTextNode("• " + it.what + (it.path ? " — " + it.path : "")));
    }
    if (it.date) row.appendChild(document.createTextNode(" · " + it.date));
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
      actEl.querySelector(".acthead").textContent =
        "✓ " + n + (n === 1 ? " step" : " steps") + " — click to see what it did";
    }
    actEl = null; actSteps = []; actStart = 0; actHome = null;
  }
  function activity(ev) {
    const step = (ev.name || "?") + (ev.detail ? " " + ev.detail : "");
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
      const body = el("div", "actbody");       // actEl and the old closure then
      head.onclick = () => box.classList.toggle("open");  // threw / hit the
      box.appendChild(head);                   // wrong line
      box.appendChild(body);
      s.appendChild(box);
      actEl = box;
      pin(s, stick);
      actTimer = setInterval(() => {
        if (!actEl || !actEl.isConnected) { resetActivity(); return; }
        actEl.querySelector(".acthead").textContent = actLabel();
      }, 1000);
    }
    actEl.querySelector(".acthead").textContent = actLabel();
    actEl.querySelector(".actbody").appendChild(el("div", "actstep", "· " + step));
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
    box.querySelector(".acthead").textContent =
      "✓ " + n + (n === 1 ? " step" : " steps") +
      (ev && ev.duration_s ? " · " + (ev.duration_s < 90 ? ev.duration_s + "s"
        : Math.round(ev.duration_s / 60) + "m") : "") + " — click to see what it did";
  }

  /* ---------- events ---------- */
  function handle(ev) {
    if (ev.t === "delta") {
      if (!currentBlock || currentBlock._tick !== !!ev.tick) {
        closeCurrent();
        currentBlock = addBlock("steward", opts.stewardLabel || "ECGBERHT",
                                "", "", ev);
        currentBlock._raw = "";
        currentBlock._tick = !!ev.tick;
      }
      currentBlock._raw += ev.text;
      currentBlock.querySelector(".body").textContent = currentBlock._raw;
      pin(targetFor(ev), false);
    } else if (ev.t === "john") {
      closeCurrent();
      addBlock("john", opts.johnLabel || "JOHN", ev.text);
      busySince = Date.now();
    } else if (ev.t === "tool") {
      // ONE live activity line, not a line per call (John, 2026-08-26: the
      // tool chatter buried what the steward was actually saying, and he
      // still couldn't tell whether it was running). The line updates in
      // place, counts the steps, names the current one, and expands to the
      // full list on click. It IS the running indicator.
      closeCurrent();
      activity(ev);
    } else if (ev.t === "turn_end") {
      closeCurrent();
      busySince = null;
      endActivity(ev);
      addLine("turnend", "· turn done in " + ev.duration_s + "s · $" +
              (ev.cost_usd || 0).toFixed(3), ev);
    } else if (ev.t === "status") {
      // the engine-composed two-part status of record (disk map + engine
      // state, zero-model) — pane only, never the conversation
      closeCurrent();
      renderStatus(ev.status);
    } else if (ev.t === "sys") {
      closeCurrent();
      // a session that ended/slept emits sys, never turn_end — finalize the
      // live line here or its timer runs for the life of the tab and the next
      // turn appends into a dead turn's counter
      if (/session ended|asleep|could not start|CLI not found/i.test(ev.text || ""))
        endActivity(null);
      // tick-tagged housekeeping (drive continues, cadence commits) rides
      // the status pane; plain sys lines stay in the conversation
      addLine("sys", ev.text, ev.tick ? ev : undefined);
    }
    if (opts.onEvent) opts.onEvent(ev);
  }

  let epoch = null;
  async function poll() {
    for (;;) {
      try {
        const r = await fetch(api("/api/events?since=" + seq));
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
        if (j.stamp && j.stamp !== stamp) { stamp = j.stamp; await loadMap(); }
      } catch (e) {
        await new Promise(res => setTimeout(res, 3000));
      }
    }
  }

  // a cheap idle repaint so the map also refreshes when the steward is quiet
  // or files change from outside this engine (not only on streamed events)
  async function stampPoll() {
    for (;;) {
      await new Promise(res => setTimeout(res, 3500));
      try {
        const r = await fetch(api("/api/state"));
        const j = await r.json();
        updateState(j);
        if (j.stamp && j.stamp !== stamp) { stamp = j.stamp; await loadMap(); }
      } catch (e) { /* the event poll handles backoff */ }
    }
  }

  function updateState(st) {
    if (st) lastState = st;
    st = lastState;
    if (!st) return;
    const busy = $("[data-busy]");
    if (busy) {
      busy.textContent = st.busy
        ? (busySince ? "thinking " + Math.round((Date.now() - busySince) / 1000) + "s"
                     : "working...")
        : "";
    }
    const spend = $("[data-spend]");
    if (spend) spend.textContent = st.alive
      ? ("session $" + (st.spend_usd || 0).toFixed(2) + " · " + st.turns + " turns")
      : (GENERAL ? "" : "steward asleep" +
         (st.queued ? " · " + st.queued + " held" : ""));
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
    const light = $("[data-light]"), light2 = $("[data-light2]");
    if (light) light.className = "light " + (st.light || "orange");
    if (light2) light2.className = "light " + (st.light || "orange");
    const stx = $("[data-statetext]");
    if (stx) {
      let txt;
      if (st.light === "red") txt = "stuck or broken — needs a look";
      else if (!st.alive && st.queued) txt = st.queued +
        " held message(s) — waking the steward for delivery";
      else if (!st.alive) txt = "nothing running — asleep; your message wakes it";
      else if (st.busy) txt = "actively running" +
        (busySince ? " — " + Math.round((Date.now() - busySince) / 1000) + "s" : "");
      else if (st.working_bg) txt = "working in the background — commissioned run in flight, nothing needed from you";
      else txt = "awake — waiting on you";
      stx.textContent = txt;
    }
    // the pinned open question (rubric #6): visible until answered
    const oq = $("[data-openq]");
    if (oq) {
      const q = st.open_question || "";
      oq.textContent = q;
      oq.classList.toggle("show", !!q);
      oq.onclick = () => { const ta = $("[data-say]"); if (ta) ta.focus(); };
    }
    const pm = $("[data-msgs]");
    if (pm) pm.textContent = "you: " + (st.john_msgs || 0) +
      " messages this session · ask “what's my overhead?” for the ease metric";
    document.body.dataset.alive = st.alive ? "1" : "";
  }

  /* ---------- files the steward touched ---------- */
  function renderFiles(files) {
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
    list.textContent = "";
    files.slice().reverse().forEach(f => {
      const row = el("div", "frow");
      row.appendChild(el("span", "fname", f.split(/[\\/]/).pop()));
      const btn = el("button", "", "Open");
      btn.onclick = () => post("/api/open", { path: f });
      row.appendChild(btn);
      list.appendChild(row);
    });
    if (!files.length) list.appendChild(el("div", "frow", "(none yet)"));
  }

  /* ---------- work-product overlay (tile on the plan rail) ---------- */
  function closeWorkMap() {
    const ov = $("[data-wpmap]");
    if (ov) ov.hidden = true;
  }
  function openWorkMap() {
    const ov = $("[data-wpmap]");
    if (ov) ov.hidden = false;
  }
  let _plates = [];
  let _plateId = "";
  function paintWorkMap(map) {
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
    map = await r.json();
    stamp = map.stamp;
    if (map.steward && !opts._labelSet) {
      opts.stewardLabel = map.steward.toUpperCase();
      opts._labelSet = true;
    }
    document.title = (map.attention.state === "needs_you" ? "⚑ " :
                      map.attention.state === "working" ? "▶ " : "") +
                     map.name + " — steward";
    if (opts.renderMap) { opts.renderMap(map); return; }
    // goal tile (one sentence; expands to the full bold-led description)
    const gb = $("[data-goalbrief]");
    if (gb) gb.textContent = _statusLine || map.goal_brief || "(no goal recorded)";
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
    _lastMap = map;
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
    if (att) { att.className = "dot " + (map.attention.state || "unknown");
               att.title = map.attention.state +
                 (map.attention.reason ? " - " + map.attention.reason : ""); }
    const name = $("[data-name]");
    if (name) name.textContent = map.name;
    if (opts.afterMap) opts.afterMap(map);
  }

  /* ---------- history ---------- */
  async function loadHistory() {
    const r = await fetch(api("/api/history"));
    const j = await r.json();
    (j.turns || []).forEach(t => addBlock(
      t.role === "john" ? "john" : "steward",
      t.role === "john" ? (opts.johnLabel || "JOHN") : (opts.stewardLabel || "ECGBERHT"),
      t.text, "hist"));
    if (j.turns && j.turns.length)
      addLine("divider", "—— live from here ——");
    pin(scrollEl(), true);
  }

  /* ---------- composer + dictation ---------- */
  function wireComposer() {
    const ta = $("[data-say]");
    const send = $("[data-send]");
    if (!ta) return;
    const grow = () => { ta.style.height = "auto";
                         ta.style.height = Math.min(ta.scrollHeight + 2, innerHeight * 0.4) + "px"; };
    ta.addEventListener("input", grow);
    const submit = async () => {
      let text = ta.value.trim();
      if (!text) return;
      // dictation-friendly grasscatch: "later: ..." parks it without ceremony
      const later = text.match(/^(later|grasscatcher?)[:,]\s*(.+)/is);
      if (later) text = "Grasscatch this (park it on the Strip with a reason, " +
                        "then carry on with the step in hand): " + later[2];
      const keep = ta.value;
      ta.value = ""; grow();
      try {
        const r = await post("/api/say", { text });
        const j = await r.json();
        if (!j.ok) { ta.value = keep; grow();
          addLine("sys", "not delivered: " + (j.error || "?") + " - your text is back in the box"); }
      } catch (e) {
        ta.value = keep; grow();
        addLine("sys", "not delivered (network) - your text is back in the box");
      }
    };
    if (send) send.onclick = submit;
    ta.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.isComposing) return;
      // (2026-09-04, John) Enter sends, the same as the Send button; Shift+Enter
      // keeps a newline. Dictation (Win+H) never presses Enter, so the button
      // stays the way to send dictated text.
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
    if (goalbar) goalbar.onclick = () => goalbar.classList.toggle("open");
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
    if (opts.stewardLabel) opts._labelSet = true;
    applyTheme();
    try { await loadMap(); } catch (e) {
      const p = $("[data-progress]");
      if (p) p.textContent = "map failed: " + ((e && e.message) || "could not load");
    }
    if (!opts.skipHistory) {
      try { await loadHistory(); } catch (e) { /* no-op */ }
    }
    if (opts.statusPane) {
      // paint the pane's status of record immediately (composed fresh,
      // zero-model) so it never opens empty waiting for the next cadence
      try { renderStatus(await (await fetch(api("/api/status"))).json()); }
      catch (e) {}
    }
    // deliverables surface on open (tile + goal/map links) — John's ask 2026-08-25
    try { renderDeliverablesTile(); } catch (e) {}
    wireComposer();
    wireChrome();
    try { wireWorkMap(); } catch (e) {}
    poll();
    stampPoll();
    setInterval(() => updateState(null), 1000); // busy clock repaint
  }

  return { init, addLine, applyTheme, toggleTheme,
           get map() { return map; }, get dir() { return DIR; } };
})();
