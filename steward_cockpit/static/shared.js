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
      opts = {}, map = null, lastState = null;

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
    const stick = atBottom(s);
    // only the newest status stays expanded (same fold rule as tick turns)
    s.querySelectorAll(".blk.steward:not(.folded)").forEach(old => {
      old.classList.add("folded");
      old.onclick = () => old.classList.toggle("folded");
    });
    const b = el("div", "blk steward status");
    b.appendChild(el("div", "who", "⏱ " + (stat.at || "").slice(-5) + " · STATUS"));
    const body = el("div", "body");
    (stat.now || []).forEach(l => body.appendChild(el("div", "snow", "now: " + l)));
    const p = stat.plan || {};
    body.appendChild(el("div", "splan",
      (p.step || "(no active step)") + " · " + (p.steps_done || 0) + "/" +
      (p.steps_total || 0) + " done · attention: " + (p.attention || "unknown")));
    if (p.waiting_on_you)
      body.appendChild(el("div", "splan sflag", "waiting on you: " + p.waiting_on_you));
    if (p.next) body.appendChild(el("div", "splan", "next: " + p.next));
    b.appendChild(body);
    s.appendChild(b);
    pin(s, stick);
    // Deliverables tile stays pinned FIRST in the pane (2026-08-25, John's ask),
    // and its register refreshes on the same cadence as the status it sits above.
    try {
      const dt = s.querySelector(".blk.deliv");
      if (dt && s.firstChild !== dt) s.insertBefore(dt, s.firstChild);
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
  async function renderDeliverablesTile() {
    if (_delivBusy) return;
    _delivBusy = true;
    let d = null;
    try { d = await (await fetch(api("/api/deliverables"))).json(); }
    catch (e) { _delivBusy = false; return; }
    _delivBusy = false;
    const items = (d && d.items) || [];
    // — the pane tile —
    const s = paneEl();
    if (s) {
      let tile = s.querySelector(".blk.deliv");
      const wasOpen = tile ? !tile.classList.contains("folded") : false;
      if (!tile) {
        tile = el("div", "blk steward deliv folded");
        s.insertBefore(tile, s.firstChild);
      } else tile.textContent = "";
      if (wasOpen) tile.classList.remove("folded");
      const who = el("div", "who", "📦 DELIVERABLES (" + items.length + ") — the things worth opening");
      who.style.cursor = "pointer";
      who.onclick = () => tile.classList.toggle("folded");
      tile.appendChild(who);
      const body = el("div", "body");
      if (!d || !d.exists) {
        body.appendChild(el("div", "snow", "No DELIVERABLES.md yet — the steward starts the register when the first human-facing artifact lands."));
      } else if (!items.length) {
        body.appendChild(el("div", "snow", "(register is empty)"));
      }
      items.forEach((it) => body.appendChild(delivRow(it)));
      tile.appendChild(body);
      if (s.firstChild !== tile) s.insertBefore(tile, s.firstChild);
    }
    // — the goal/map links —
    const slot = $("[data-deliverables]");
    if (slot) {
      slot.textContent = "";
      if (items.length) {
        slot.appendChild(el("div", "glabel", "Deliverables"));
        items.forEach((it) => slot.appendChild(delivRow(it)));
      }
    }
  }
  function delivRow(it) {
    const row = el("div", "snow drow");
    if (it.openable && it.path) {
      const a = document.createElement("a");
      a.textContent = it.what;
      a.href = api("/api/deliverable-file") + "&path=" + encodeURIComponent(it.path);
      a.target = "_blank";
      a.rel = "noopener";
      row.appendChild(a);
    } else {
      row.appendChild(document.createTextNode(it.what + (it.path ? " — " + it.path : "")));
    }
    if (it.date) row.appendChild(document.createTextNode(" · " + it.date));
    return row;
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
      closeCurrent();
      addLine("tool", "· " + ev.name + (ev.detail ? "  " + ev.detail : ""), ev);
    } else if (ev.t === "turn_end") {
      closeCurrent();
      busySince = null;
      addLine("turnend", "· turn done in " + ev.duration_s + "s · $" +
              (ev.cost_usd || 0).toFixed(3), ev);
    } else if (ev.t === "status") {
      // the engine-composed two-part status of record (disk map + engine
      // state, zero-model) — pane only, never the conversation
      closeCurrent();
      renderStatus(ev.status);
    } else if (ev.t === "sys") {
      closeCurrent();
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
      : (GENERAL ? "" : "steward asleep");
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
      else if (!st.alive) txt = "nothing running — asleep; your message wakes it";
      else if (st.busy) txt = "actively running" +
        (busySince ? " — " + Math.round((Date.now() - busySince) / 1000) + "s" : "");
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
    if (gb) gb.textContent = map.goal_brief || "(no goal recorded)";
    const gf = $("[data-goalfull]");
    if (gf) renderRich(gf, map.goal_md || "(no goal recorded)");
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
    const list = $("[data-steps]");
    if (list) {
      list.textContent = "";
      map.steps.forEach(st => {
        const li = el("li", st.status);
        const mark = { done: "✓", active: "▶", waiting: "⚑" }[st.status] || "○";
        li.appendChild(el("span", "mark", mark));
        const wrap = el("div");
        wrap.appendChild(el("div", "", st.name));
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
        wrap.appendChild(el("div", "why",
          parts.length ? parts.join("\n") : "details to be added"));
        li.appendChild(wrap);
        if (st.status === "active") li.classList.add("open");
        li.onclick = () => li.classList.toggle("open");
        list.appendChild(li);
      });
    }
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
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); }
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
      else location.href = "/";                              // standalone: High Seat
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
    await loadMap();
    if (!opts.skipHistory) await loadHistory();
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
    poll();
    stampPoll();
    setInterval(() => updateState(null), 1000); // busy clock repaint
  }

  return { init, addLine, applyTheme, toggleTheme,
           get map() { return map; }, get dir() { return DIR; } };
})();
