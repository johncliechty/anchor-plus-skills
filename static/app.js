/* The Anchor app (static/app.html) - Skill Foundry/planning/anchor-app-shell-2026-09-29 (PLAN v2.2 + his
 * 2026-10-03 layout).
 *
 * His rules: the Cave of Wonders is always the first tile and never closes; everything he opens is a tile in
 * the title bar; ONE pane or TWO side by side (the toggle at the upper right); he clicks in a pane to make it
 * the active one and clicks a tile to show it there; each pane has an x that shuts that pane. A deliverable
 * opened from a cockpit goes to the OTHER pane - the right one by default, the left when the cockpit is on the
 * right - opening the second pane if there was one, and the cockpit keeps the focus so he can dictate.
 *
 * Frames: the Cave's frame lives for the whole session. A tile shown in a pane has a live frame; a tile that
 * leaves the panes KEEPS its frame, hidden, so switching back shows it exactly as he left it - conversation,
 * draft, scroll (his rule, 2026-10-08: "once opened ... keep the content in them"). Only past KEEP_LIVE hidden
 * tiles does the least recently shown one drop its frame (once the panes' new frames have loaded, never inside
 * the caller's own window.open call); it comes back from its last address on a click. The tile list lives in memory.
 */
(function () {
  "use strict";
  var CAVE_URL = "/";
  var CAVE_EFFORT = "Cave of Wonders";       // the Cave's own conversation folder (high_seat_page.CAVE_EFFORT)
  var COCKPIT = " \u2014 AI Cockpit";
  var FRAME_SCRIPT = "/static/app-frame.js";
  var DROP_AFTER_MS = 15000;
  var KEEP_LIVE = 6, KEEP_LIVE_NARROW = 3;    // hidden tiles that keep their page (a phone keeps fewer)
  if (typeof window.ANCHOR_KEEP_LIVE === "number" && window.ANCHOR_KEEP_LIVE >= 0)   // tests of the drop path
    KEEP_LIVE = KEEP_LIVE_NARROW = window.ANCHOR_KEEP_LIVE;

  var strip = document.getElementById("strip");
  var rowButton = document.getElementById("rows"), rowsExpanded = false, rowTick = null;
  var stage = document.getElementById("stage");
  var heads = [document.getElementById("head0"), document.getElementById("head1")];
  var tiles = [];                  // {id, kind: "cave"|"page"|"doc", url, title, name, opener, frame}
  var panes = ["cave", null];      // the tile shown in the left and the right pane
  var two = false, active = 0, seq = 0;
  var hist = [[], []];             // per pane: the tiles it showed before, newest last (a close goes back)
  var pendingDrop = [], dropTimer = null;
  var narrowMq = window.matchMedia("(max-width: 760px)");
  var narrow = { get matches() { return narrowMq.matches && !document.body.classList.contains("hosted"); } };
  try { narrowMq.addEventListener("change", function () { settle(); }); } catch (e) { /* older engines: next settle */ }

  // ---------- frames ----------
  function newFrame(src) {
    var f = document.createElement("iframe");
    f.className = "pane";
    f.setAttribute("allow", "clipboard-read; clipboard-write; fullscreen");
    stage.appendChild(f);
    f.addEventListener("load", function () { onLoad(f); });
    if (src) f.src = src;
    return f;
  }

  function arm(win) {              // pages not served with the script get it on every load
    try {
      if (!win || win.__anchorFrame || !win.document || !win.document.head) return;
      var s = win.document.createElement("script");
      s.src = FRAME_SCRIPT;
      win.document.head.appendChild(s);
    } catch (e) { /* not ours to arm */ }
  }

  function addressOf(win) {
    try { var h = win.location.href; return h === "about:blank" ? "" : h; } catch (e) { return ""; }
  }

  function titleOf(win, fallback) {
    try {
      var t = (win.document.title || "").trim();
      if (win.location.pathname === "/steward/v1" && (t === "Steward \u2014 V1" || t === "Aladdin \u2014 AI Cockpit")) return fallback;
      if (t) return t;
      var p = win.location.pathname;
      return p && p !== "blank" ? decodeURIComponent(p.split("/").filter(Boolean).pop() || fallback) : fallback;
    } catch (e) { return fallback; }
  }

  function onLoad(f) {
    var t = tileOfFrame(f);
    if (!t) return;
    arm(f.contentWindow);
    if (shownIn(t.id) < 0) { t.hiddenSaid = true; tellVisibility(f, true); }
    var isSplit = !!(two && shownIn(t.id) >= 0);
    t.splitSaid = isSplit;
    tellSplit(f, isSplit);
    var url = addressOf(f.contentWindow);
    if (url) t.url = url;
    var route = resolve(url);
    // A blank window can navigate to a real page, or receive a generated document at its caller's address.
    // Only the former acquires a page identity; the generated report must keep its own tile.
    if (t.kind !== "cave" && !t.asked && route && !route.blank && url !== t.blankFrom) {
      t.asked = url;
      t.kind = isPage(route.path) ? "page" : "doc";
    }
    // one tile per page (his rule, 2026-10-03): a tile that navigated onto a page already open in another tile
    // gives way to it. A page written into a blank window (document.open) carries its CALLER's address and is
    // not that page, so only a tile opened at a real address is merged.
    if (t.kind === "page" && t.asked && route && !route.blank) {
      var key = pageKey(route), existing = key === "cave" ? byId("cave") : tiles.find(function (other) {
        return other !== t && other.kind === "page" && pageKey(resolve(other.url)) === key;
      });
      if (existing) {
        var pane = shownIn(t.id);
        if (pane >= 0) show(existing.id, pane, true);
        if ((route.q.has("step") || route.q.has("open")) && existing.frame) existing.frame.src = route.url;
        closeTile(t.id);
        return;
      }
    }
    if (t.kind !== "cave" && !t.named) t.title = titleOf(f.contentWindow, t.title || "Page");
    if (shownIn(t.id) >= 0) settle();
    layout(); render();
  }

  function tileOfFrame(f) { for (var i = 0; i < tiles.length; i++) if (tiles[i].frame === f) return tiles[i]; return null; }

  // the tile a window belongs to (the window itself, or a frame nested inside a tile's page)
  function tileOfWindow(win) {
    for (var w = win, guard = 0; w && guard < 8; guard++) {
      for (var i = 0; i < tiles.length; i++) if (tiles[i].frame && tiles[i].frame.contentWindow === w) return tiles[i];
      if (w === window || w.parent === w) break;
      w = w.parent;
    }
    return null;
  }

  function byId(id) { for (var i = 0; i < tiles.length; i++) if (tiles[i].id === id) return tiles[i]; return null; }
  function shownIn(id) { return id && panes[0] === id ? 0 : (two && id && panes[1] === id ? 1 : -1); }
  // His rule (2026-10-03): a tile is named for WHAT it shows, read from its address - the Cave (its persona's name
  // and picture), the Campaign board (the mode's: Star Chart / Chart Room / Beacon), and the two conversations'
  // cockpits ("<name> - AI Cockpit"). Everything else keeps its page's own title.
  function names() {
    var b = {}, w = null;
    try { w = byId("cave").frame.contentWindow; b = w.ANCHOR_TILES || {}; b.campaign_pid = (w.ANCHOR_BOOT || {}).campaign_pid; } catch (e) {}
    var doc = null; try { doc = w && w.document; } catch (e) {}
    var q = function (sel) { try { return doc ? doc.querySelector(sel) : null; } catch (e) { return null; } };
    var rail = q('#railNav [data-rail="campaign"] .n'), seatImg = q(".mh-stew img");
    return {
      pid: b.campaign_pid || "",
      seat: b.seat_name || "Cave of Wonders",
      seatIcon: b.seat_icon || (seatImg ? seatImg.getAttribute("src") : "") || "/vendor/brand/aladdin-high-seat-cave.png",
      mode: b.mode_name || (rail ? rail.textContent.trim() : "") || "Star Chart",
      modeIcon: b.mode_icon || "/vendor/brand/campaign-aladdin-star-chart.jpg"
    };
  }
  function identity(t) {                                       // {title, icon} for the tiles his rule names, else null
    if (t.kind === "cave") { var c = names(); return { title: c.seat, icon: c.seatIcon }; }
    if (t.kind !== "page") return null;
    var r = resolve(t.url || t.asked), n = names();
    if (!r || r.blank || !n.pid) return null;
    var key = pageKey(r);
    if (key === "board:/project/" + n.pid + ":") return { title: n.mode, icon: n.modeIcon, mode: true };
    if (key === "conversation:" + n.pid + ":") return { title: n.mode + COCKPIT, icon: n.modeIcon, mode: true };
    if (key === "conversation:" + n.pid + ":" + CAVE_EFFORT) return { title: n.seat + COCKPIT, icon: n.seatIcon };
    return null;
  }
  function displayTitle(t) { var id = identity(t); return id ? id.title : (t.title || "Page"); }

  // ---------- what an address is ----------
  function resolve(u, fromWin) {
    if (u === undefined || u === null || u === "" || String(u) === "about:blank") return { blank: true };
    var s = String(u);
    var yt = s.match(/^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/)|youtu\.be\/)([A-Za-z0-9_-]{6,15})/i);
    if (yt && (!fromWin || !fromWin.location || fromWin.location.pathname !== "/steward-static/video.html")) {
      s = "/steward-static/video.html?v=" + encodeURIComponent(yt[1]) + "&url=" + encodeURIComponent(s);
    }
    var x;
    try { x = new URL(s, fromWin && fromWin.location ? fromWin.location.href : location.href); }
    catch (e) { return null; }
    if (x.origin !== location.origin || !/^https?:$/.test(x.protocol)) return null;
    return { url: x.href, path: x.pathname, q: x.searchParams };
  }

  // The board and its conversation are different items. Conversation identity comes from pid + dir,
  // never its display title, instance bridge, query order or embedded/full-size presentation.
  function pageKey(r) {
    if (!r || r.blank) return "";
    if ((r.path === "/" || r.path === "/high-seat") && !r.q.has("view")) return "cave";
    if (r.path === "/steward/v1") return "conversation:" + r.q.get("pid") + ":" + (r.q.get("dir") || "") +
      (r.q.get("general") === "1" ? ":terminal:" + (r.q.get("term") || "") : "");
    if (/^\/project\/[^/]+\/?$/.test(r.path) && !r.q.has("doc") && !r.q.has("classic") && !r.q.has("chamber"))
      return "board:" + r.path.replace(/\/$/, "") + ":" + (r.q.get("view") || "");
    return r.url;
  }

  function campaignPid() {
    var home = byId("cave"), pid = "";
    try { pid = home.frame.contentWindow.ANCHOR_BOOT.campaign_pid || ""; } catch (e) {}
    return pid;
  }

  function conversationAlias(r) {
    var pid = campaignPid();
    if (pid && r.path === "/project/" + pid && r.q.get("doc") === "1") {
      var u = new URL("/steward/v1", location.href);
      u.searchParams.set("pid", pid); u.searchParams.set("dir", r.q.get("dir") || "");
      if (r.q.get("step")) u.searchParams.set("step", r.q.get("step"));
      return resolve(u.href);
    }
    return r;
  }

  function isDownload(r) {
    if (r.q.get("download") === "1") return true;
    return r.path === "/api/steward/deliverable-file" && r.q.get("view") !== "1" &&
           /\.(docx|pptx|xlsx|zip|7z|exe|msi)$/i.test(r.q.get("path") || "");
  }

  // Anchor's own pages open where they were asked from; everything else (a report, an artifact, a deliverable
  // file, a notebook) is a deliverable and opens in the other pane.
  function isPage(path) {
    return path === "/" || path === "/dashboard" || path === "/high-seat" || path === "/doctor" ||
           path === "/setup" || path === "/setup/install" || path === "/onboard-wizard" ||
           /^\/foundry\/?$/.test(path) || /^\/project\//.test(path) || /^\/steward\/v[13]\b/.test(path);
  }

  function labelFor(r) {
    var p = r.q.get("path");
    if (p) return p.split(/[\\/]/).pop();
    if (r.path === "/steward/v1" && r.q.get("general") !== "1") {
      var dir = r.q.get("dir") || "";
      var name = dir ? dir.split(/[\\/]/).pop() : (r.q.get("pid") === campaignPid() ? "Star Chart" : "Conversation");
      return name + " \u2014 AI Cockpit";
    }
    return decodeURIComponent(r.path.split("/").filter(Boolean).pop() || "Page");
  }

  // ---------- the API the frames call (static/app-frame.js) ----------
  var api = {
    open: function (u, target, fromWin) {
      var r = resolve(u, fromWin);
      if (!r || (!r.blank && isDownload(r))) return null;      // the native call
      if (!r.blank && r.path === "/static/app.html") return null;
      if (!r.blank) r = conversationAlias(r);
      var caller = tileOfWindow(fromWin);
      var from = caller ? shownIn(caller.id) : -1;
      if (from < 0) from = two ? active : 0;
      if (!r.blank && pageKey(r) === "cave") {
        show("cave", from, true);                              // the Cave is one tile, never a second one
        active = from; layout(); render();
        return byId("cave").frame.contentWindow;
      }
      var asDoc = r.blank ? !!(caller && caller.kind !== "cave") : !isPage(r.path);
      var name = target && !/^_(blank|self|parent|top)$/i.test(String(target)) ? String(target) : "";

      var key = pageKey(r), t = null, i;
      for (i = 0; i < tiles.length && !t; i++) {               // a named window, or the same page, is reused
        if ((name && tiles[i].name === name) ||
            (!r.blank && tiles[i].kind !== "cave" && (pageKey(resolve(tiles[i].url)) === key || pageKey(resolve(tiles[i].asked)) === key))) t = tiles[i];
      }
      if (t) {
        if (!t.frame) t.frame = newFrame("");
        var current = resolve(addressOf(t.frame.contentWindow));
        if (!r.blank && (pageKey(current) !== key || r.q.has("step") || r.q.has("open"))) t.frame.src = r.url;
      } else {
        t = { id: "t" + (++seq), kind: asDoc ? "doc" : "page", url: r.blank ? "" : r.url, asked: r.blank ? "" : r.url,
              blankFrom: r.blank ? addressOf(fromWin) : "",
              title: r.blank ? "Opening…" : labelFor(r), name: name, opener: fromWin || null, frame: null,
              named: !r.blank && !!r.q.get("path") };           // a deliverable file keeps its file name
        tiles.push(t);
        t.frame = newFrame(r.blank ? "" : r.url);
        if (r.blank) guardBlank(t.frame, function () { closeTile(t.id); });
      }
      if (asDoc && caller && caller.kind === "doc" && shownIn(caller.id) >= 0) {
        show(t.id, from, true);                                // a deliverable's own link: in its pane, the cockpit stays
        active = from;
      } else if (asDoc) {                                      // the other pane; the caller keeps the focus
        var to;
        if (!two) { two = true; from = 0; to = 1; }
        else to = from === 0 ? 1 : 0;
        show(t.id, to, true);
        active = from;
      } else {
        show(t.id, from, true);
        active = from;
      }
      layout(); render();
      if (cockpitTarget(t)) refreshFeedback();
      return t.frame.contentWindow;
    },
    download: function (u, fromWin) {
      var r = resolve(u, fromWin);
      if (!r || r.blank || !isDownload(r)) return false;
      var a = document.createElement("a");
      a.href = r.url; a.download = ""; a.hidden = true;
      document.body.appendChild(a); a.click(); a.remove();
      return true;
    },
    touch: function (win) {                                    // a click inside a pane makes it the active pane
      var t = tileOfWindow(win), k = t ? shownIn(t.id) : -1;
      if (k >= 0 && k !== active) { active = k; layout(); render(); }
    },
    openerOf: function (win) {
      var t = tileOfWindow(win);
      return t && t.frame && t.frame.contentWindow === win && t.opener && t.opener !== win ? t.opener : null;
    },
    closeWindow: function (win) { var t = tileOfWindow(win); if (t) closeTile(t.id); },
    closeDeliverable: function (u, fromWin) {
      var r = resolve(u, fromWin);
      if (!r) return false;
      var key = pageKey(r), wantPath = r.q.get("path");
      var removed = false;
      tiles.slice().forEach(function (t) {
        if (t.kind !== "doc") return;
        var ru = resolve(t.url), ra = resolve(t.asked);
        if ((ru && pageKey(ru) === key) || (ra && pageKey(ra) === key) ||
            (wantPath && ((ru && ru.q.get("path") === wantPath) || (ra && ra.q.get("path") === wantPath)))) {
          closeTile(t.id);
          removed = true;
        }
      });
      return removed;
    }
  };

  // a caller's w.close() on a window that is still blank (a failed create) closes its tile
  function guardBlank(f, close) { try { f.contentWindow.close = close; } catch (e) { /* not reachable */ } }

  // ---------- panes ----------
  // fromCall: inside a page's window.open - old frames go once the new ones load (or the timer), never now
  function show(id, k, fromCall) {
    var t = byId(id);
    if (!t) return;
    var other = shownIn(id);
    var prev = panes[k];
    if (other >= 0 && other !== k) panes[other] = prev;       // already on the other side: the two swap
    panes[k] = id;
    t.seen = ++seq;                                            // least recently shown drops first, past KEEP_LIVE
    if (prev && prev !== id) { hist[k] = hist[k].filter(function (x) { return x !== prev; }); hist[k].push(prev); }
    if (prev && prev !== id && shownIn(prev) < 0) leave(prev);
    if (!t.frame) t.frame = newFrame(t.url || CAVE_URL);
    if (!fromCall) active = k;
    layout(); render();
    if (!fromCall && frameReady(t.frame)) settle();
    clearTimeout(dropTimer);
    dropTimer = setTimeout(settle, DROP_AFTER_MS);
  }

  function leave(id) {                                         // a tile left the panes: its frame goes later
    var t = byId(id);
    if (!t || t.kind === "cave") return;
    if (t.frame && !t.named) t.title = titleOf(t.frame.contentWindow, t.title);
    try { var ae = t.frame && t.frame.contentDocument && t.frame.contentDocument.activeElement; if (ae && ae.blur) ae.blur(); }
    catch (e) { /* the draft keeps itself */ }
    if (pendingDrop.indexOf(id) < 0) pendingDrop.push(id);
  }

  function frameReady(f) {
    try { return f.contentDocument && f.contentDocument.readyState === "complete" && addressOf(f.contentWindow) !== ""; }
    catch (e) { return false; }
  }

  function settle() {
    pendingDrop = pendingDrop.filter(function (id) {        // a tile that left keeps its page: remember where it is
      var t = byId(id);
      if (t && t.frame && shownIn(id) < 0) { t.url = addressOf(t.frame.contentWindow) || t.url; if (!t.named) t.title = titleOf(t.frame.contentWindow, t.title); }
      return false;
    });
    var cap = narrowMq.matches ? KEEP_LIVE_NARROW : KEEP_LIVE;
    var hiddenLive = tiles.filter(function (t) { return t.kind !== "cave" && t.frame && shownIn(t.id) < 0; })
                          .sort(function (a, b) { return (a.seen || 0) - (b.seen || 0); });
    hiddenLive.slice(0, Math.max(0, hiddenLive.length - cap)).forEach(function (t) {
      t.url = addressOf(t.frame.contentWindow) || t.url;
      if (!t.named) t.title = titleOf(t.frame.contentWindow, t.title);
      t.frame.remove(); t.frame = null;
    });
  }

  function hidePane(k) {                                       // the 1-pane toggle or a non-deliverable pane's x: the pane goes, its tile stays
    if (!two) return;
    var gone = panes[k];
    panes[0] = panes[k === 0 ? 1 : 0];
    panes[1] = gone;                                           // remembered for the toggle; not shown
    two = false; active = 0;
    if (gone) leave(gone);
    layout(); render(); settle();
  }

  function setTwo(on) {
    if (on === two) return;
    if (!on) { hidePane(two ? (active === 0 ? 1 : 0) : 1); return; }
    var next = null;
    if (panes[1] && panes[1] !== panes[0] && byId(panes[1])) next = panes[1];
    if (!next) {
      var rest = tiles.filter(function (t) { return t.id !== panes[0]; });
      next = rest.length ? rest[rest.length - 1].id : null;
    }
    if (!next) return;                                         // only the Cave is open: nothing for a second pane
    two = true;
    panes[1] = null;
    show(next, 1);
  }

  function closePane(k) {                                      // a pane's x: a deliverable (doc) under review is removed from the top row of tiles
    if (!two) return;
    var t = byId(panes[k]);
    if (t && t.kind === "doc") { closeTile(t.id); return; }
    hidePane(k);
  }

  function closeTile(id) {
    var t = byId(id);
    if (!t || t.kind === "cave") return;                       // the Cave never closes
    var hadFocus = t.el && t.el.contains(document.activeElement);
    var i = tiles.indexOf(t), k = shownIn(id);
    if (t.frame) {
      try { t.frame.src = "about:blank"; } catch (e) {}
      t.frame.remove();
    }
    if (t.el) t.el.remove();
    tiles.splice(i, 1);
    var d = pendingDrop.indexOf(id);
    if (d >= 0) pendingDrop.splice(d, 1);
    if (panes[1] === id) panes[1] = null;
    hist[0] = hist[0].filter(function (x) { return x !== id; });
    hist[1] = hist[1].filter(function (x) { return x !== id; });
    if (k >= 0) {
      if (two) { panes[0] = panes[k === 0 ? 1 : 0]; panes[1] = null; two = false; active = 0; }
      else {                                                   // back to what this pane showed before (else the opener's)
        var back = hist[0].length ? hist[0].pop() : null;
        var op = t.opener ? tileOfWindow(t.opener) : null;
        panes[0] = back || (op ? op.id : null) || (tiles[i - 1] || tiles[0]).id;
      }
      var s = byId(panes[0]);
      if (s) s.seen = ++seq;                                   // restored: the most recently shown (the keep-alive order)
      if (s && !s.frame) s.frame = newFrame(s.url || CAVE_URL);
    }
    layout(); render();
    if (hadFocus) {
      var neighbor = tiles[Math.min(i, tiles.length - 1)].el;
      if (neighbor.inert) rowButton.focus(); else neighbor.focus();
    }
  }

  // A hidden tile keeps its page (keep-alive) but must not keep working the network or reload under a draft:
  // every window in the tile (the page and the frames inside it, e.g. a cockpit's chamber) gets
  // window.__anchorHidden and an "anchor-app-visibility" event. A cockpit parks its event poll on it (the same
  // park the Cave's preloaded cards use) and its build self-reload waits until it is shown again.
  function tellVisibility(f, hidden) {
    (function walk(w, depth) {
      try {
        w.__anchorHidden = hidden;
        w.dispatchEvent(new w.CustomEvent("anchor-app-visibility", { detail: { hidden: hidden } }));
        for (var i = 0; depth < 4 && i < w.frames.length; i++) walk(w.frames[i], depth + 1);
      } catch (e) { /* not ours */ }
    })(f.contentWindow, 0);
  }

  function tellSplit(f, split) {
    (function walk(w, depth) {
      try {
        w.__anchorSplit = split;
        w.dispatchEvent(new w.CustomEvent("anchor-app-split", { detail: { split: split } }));
        for (var i = 0; depth < 4 && i < w.frames.length; i++) walk(w.frames[i], depth + 1);
      } catch (e) { /* not ours */ }
    })(f.contentWindow, 0);
  }

  function layout() {
    document.body.classList.toggle("two", two);
    tiles.forEach(function (t) {
      if (!t.frame) return;
      var k = shownIn(t.id);
      t.frame.hidden = k < 0;
      if (t.hiddenSaid !== (k < 0)) { t.hiddenSaid = k < 0; tellVisibility(t.frame, k < 0); }
      var isSplit = !!(two && k >= 0);
      if (t.splitSaid !== isSplit) { t.splitSaid = isSplit; tellSplit(t.frame, isSplit); }
      t.frame.dataset.pane = k < 0 ? "" : String(k);
      t.frame.classList.toggle("active", two && k === active);
    });
    heads.forEach(function (h, k) {
      h.hidden = !two;
      h.classList.toggle("active", two && k === active);
      var t = byId(panes[k]);
      h.querySelector(".name").textContent = t ? displayTitle(t) : "";
    });
    document.getElementById("one").setAttribute("aria-pressed", String(!two));
    document.getElementById("two").setAttribute("aria-pressed", String(two));
  }

  // ---------- the strip of tiles ----------
  // Measure the real wrapped boxes. Hidden rows keep their layout but are inert, so
  // neither keyboard navigation nor scrollIntoView can expose a clipped row.
  function measureRows() {
    rowTick = null;
    var items = Array.from(strip.children);
    if (!items.length) return;
    var arrowFocused = document.activeElement === rowButton;
    var first = items[0].getBoundingClientRect(), bottom = first.bottom;
    var overflow = items.some(function (el) { return el.getBoundingClientRect().top > first.top + 1; });
    if (!overflow) rowsExpanded = false;
    rowButton.hidden = !overflow;
    rowButton.setAttribute("aria-expanded", String(rowsExpanded));
    rowButton.title = rowsExpanded ? "Show first row of open tiles" : "Show all open tiles";
    rowButton.setAttribute("aria-label", rowButton.title);
    strip.classList.toggle("expanded", rowsExpanded);
    items.forEach(function (el) {
      var r = el.getBoundingClientRect(), hide = !rowsExpanded && r.top > first.top + 1;
      bottom = Math.max(bottom, r.bottom);
      if (hide && el.contains(document.activeElement)) rowButton.focus();
      el.classList.toggle("overflow-row", hide);
      el.inert = hide;
      el.tabIndex = hide ? -1 : 0;
      el.setAttribute("aria-hidden", String(hide));
    });
    strip.style.setProperty("--strip-height", (rowsExpanded ? bottom - first.top : first.height) + "px");
    if (!rowsExpanded) strip.scrollTop = 0;
    if (!overflow && arrowFocused) {
      var selected = byId(panes[two ? active : 0]);
      (selected ? selected.el : items[0]).focus();
    }
  }
  function queueRows() { if (rowTick === null) rowTick = requestAnimationFrame(measureRows); }
  rowButton.addEventListener("click", function () { rowsExpanded = !rowsExpanded; measureRows(); });
  strip.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && rowsExpanded) { ev.preventDefault(); rowsExpanded = false; measureRows(); rowButton.focus(); }
  });
  window.addEventListener("resize", queueRows);
  new ResizeObserver(queueRows).observe(strip);

  function render() {
    var focusId = panes[two ? active : 0];
    var focused = document.activeElement;
    tiles.forEach(function (t, index) {
      // Status, selection and row changes retain the tile's nodes and animation.
      if (!t.el) {
        var el = document.createElement("div");
        el.className = "tile" + (t.kind === "cave" ? " cave" : "");
        el.tabIndex = 0;
        el.setAttribute("role", "button");
        el.dataset.id = t.id;
        var name = document.createElement("span"); name.className = "name"; el.appendChild(name);
        var pos = document.createElement("span"); pos.className = "pos"; el.appendChild(pos);
        if (t.kind !== "cave") {
          var x = document.createElement("button"); x.className = "x"; x.type = "button"; x.title = "Close"; x.textContent = "×";
          x.addEventListener("click", function (ev) { ev.stopPropagation(); closeTile(t.id); });
          el.appendChild(x);
          el.addEventListener("pointerdown", startDrag);
        }
        el.addEventListener("click", function () { if (!dragMoved && !swiped) show(t.id, two ? active : 0); });
        el.addEventListener("keydown", function (ev) {
          if (ev.target === el && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); show(t.id, two ? active : 0); }
        });
        t.el = el;
      }
      var tile = t.el, pane = shownIn(t.id), side = tile.querySelector(".side"), whoNow = identity(t);
      tile.classList.toggle("shown", pane >= 0);
      tile.classList.toggle("focus", t.id === focusId);
      tile.classList.toggle("doc", t.kind === "doc");
      tile.querySelector(".name").textContent = displayTitle(t);
      tile.title = displayTitle(t);
      var oldIcon = tile.querySelector(".tile-icon, :scope > img");
      if (whoNow && whoNow.icon && (!oldIcon || (oldIcon.querySelector("img") || oldIcon).getAttribute("src") !== whoNow.icon)) {
        if (oldIcon) oldIcon.remove();
        var newIcon = document.createElement("img"); newIcon.src = whoNow.icon; newIcon.alt = "";
        if (whoNow.mode) { var wrap = document.createElement("span"); wrap.className = "tile-icon star-chart"; wrap.appendChild(newIcon); newIcon = wrap; }
        tile.insertBefore(newIcon, tile.firstChild);
      } else if (!whoNow && oldIcon) oldIcon.remove();
      if (cockpitTarget(t) && !tile.querySelector(".activity-dot")) {
        var newDot = document.createElement("span"); newDot.className = "activity-dot gray"; newDot.setAttribute("role", "img");
        tile.insertBefore(newDot, tile.querySelector(".pos"));
      } else if (!cockpitTarget(t) && tile.querySelector(".activity-dot")) {
        tile.querySelector(".activity-dot").remove(); tile.classList.remove("ready");
      }
      if (two && pane >= 0) {
        if (!side) { side = document.createElement("span"); tile.insertBefore(side, tile.querySelector(".pos")); }
        side.className = "side" + (pane ? " r" : ""); side.textContent = pane ? "R" : "L";
      } else if (side) side.remove();
      tile.querySelector(".pos").textContent = tiles.length > 1 ? "‹ " + (index + 1) + " of " + tiles.length + " ›" : "";
      if (strip.children[index] !== tile) strip.insertBefore(tile, strip.children[index] || null);
      paintFeedback(t);
    });
    if (focused && focused.isConnected && focused.closest("#strip") && document.activeElement !== focused) focused.focus();
    measureRows();
  }

  // the phone (760 px fold): a swipe on the title bar steps the active pane through the tiles, in order
  var swiped = false;
  (function () {
    var x0 = null, y0 = 0;
    strip.addEventListener("pointerdown", function (ev) { if (narrow.matches) { x0 = ev.clientX; y0 = ev.clientY; } });
    document.addEventListener("pointerup", function (ev) {
      if (x0 === null) return;
      var dx = ev.clientX - x0, dy = ev.clientY - y0;
      x0 = null;
      if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
      var k = two ? active : 0, i = tiles.indexOf(byId(panes[k])), j = i + (dx < 0 ? 1 : -1);
      if (j < 0 || j >= tiles.length) return;
      swiped = true;
      show(tiles[j].id, k);
      setTimeout(function () { swiped = false; }, 0);
    });
    document.addEventListener("pointercancel", function () { x0 = null; });
  })();

  // drag a tile to reorder (pointer events, a finger works too); the Cave stays first; not on the phone
  var dragMoved = false;
  function startDrag(ev) {
    if (narrow.matches) return;
    if (ev.button !== 0 || (ev.target && ev.target.classList && ev.target.classList.contains("x"))) return;
    var el = ev.currentTarget, id = el.dataset.id, x0 = ev.clientX, y0 = ev.clientY;
    dragMoved = false;
    function move(e) {
      if (!dragMoved && Math.max(Math.abs(e.clientX - x0), Math.abs(e.clientY - y0)) < 6) return;
      dragMoved = true;
      el.classList.add("dragging");
      var over = document.elementFromPoint(e.clientX, e.clientY);
      var tEl = over && over.closest ? over.closest(".tile") : null;
      if (!tEl || tEl === el || tEl.classList.contains("cave")) return;
      var a = tiles.indexOf(byId(id)), b = tiles.indexOf(byId(tEl.dataset.id));
      if (a < 1 || b < 1) return;
      tiles.splice(b, 0, tiles.splice(a, 1)[0]);
      render();
      el = strip.querySelector('[data-id="' + id + '"]');
      if (el) el.classList.add("dragging");
    }
    function up() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      if (el) el.classList.remove("dragging");
      setTimeout(function () { dragMoved = false; }, 0);
    }
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  // ---------- the pane headers, the gutter, the toggle ----------
  heads.forEach(function (h, k) {
    h.addEventListener("pointerdown", function (ev) { if (!ev.target.closest(".x, .pane-scroll") && active !== k) { active = k; layout(); render(); } });
    h.querySelector(".x").addEventListener("click", function () { closePane(k); });
    h.querySelectorAll(".pane-scroll").forEach(function (btn) {
      btn.addEventListener("pointerdown", function (ev) { ev.preventDefault(); ev.stopPropagation(); });
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var dir = Number(btn.getAttribute("data-scroll") || "1") || 1;
        api.scrollPane(k, dir * Math.max(380, Math.round(window.innerHeight * 0.72)));
      });
    });
  });
  document.getElementById("one").addEventListener("click", function () { setTwo(false); });
  document.getElementById("two").addEventListener("click", function () { setTwo(true); });

  // ---------- the Setup gear ----------
  // His rule: the gear sits at the very upper left of ANCHOR - this bar, left of the mark - not only inside
  // a framed page's own header. It opens the saved Setup page; one tile per page makes a repeat click reuse it.
  document.getElementById("setup-gear").addEventListener("click", function () {
    api.open("/setup", "", window);
  });
  // The Setup page's "Return to Cave" posts anchor-setup-close to its parent; shown as a tile, that parent is
  // this shell - bring the Cave back to that pane. The Setup tile stays a tile; nothing is launched or closed.
  window.addEventListener("message", function (ev) {
    if (ev.origin !== location.origin || !ev.data) return;
    if (ev.data.proto === "anchor-cockpit-state") {
      var ct = tileOfWindow(ev.source);
      if (ct && cockpitTarget(ct) && window.AnchorCockpitFeedback) {
        ct.feedbackKey = window.AnchorCockpitFeedback.identity(cockpitTarget(ct));
        ct.feedback = { light: ev.data.light || "gray", ready: !!ev.data.ready, reason: ev.data.reason || "" };
        paintFeedback(ct);
      }
      return;
    }
    if (ev.data.type !== "anchor-setup-close") return;
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].frame && tiles[i].frame.contentWindow === ev.source) {
        var k = shownIn(tiles[i].id);
        if (k >= 0) show("cave", k);
        return;
      }
    }
  });

  (function () {                                               // drag the line between the panes
    var g = document.getElementById("gutter");
    g.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      document.body.classList.add("resizing");
      function move(e) {
        var r = stage.getBoundingClientRect();
        var f = Math.min(0.8, Math.max(0.2, (e.clientX - r.left) / r.width));
        stage.style.setProperty("--left", f.toFixed(3));
      }
      function up() {
        document.body.classList.remove("resizing");
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
      }
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  })();

  // the tile and pane names follow their pages' titles
  setInterval(function () {
    var changed = false;
    [panes[0], two ? panes[1] : null].forEach(function (id) {
      var t = byId(id);
      if (!t || t.kind === "cave" || t.named || !t.frame) return;
      var now = titleOf(t.frame.contentWindow, t.title);
      if (now && now !== t.title) { t.title = now; changed = true; }
    });
    if (changed) { layout(); render(); }
  }, 2000);

  // ---------- zoom (Ctrl + / - / 0, Ctrl + wheel) and the window's own controls: the desktop program only ----------
  function host() { return window.pywebview && window.pywebview.api; }
  api.zoom = function (step) {
    var h = host();
    if (!h || !h.zoom) return false;
    h.zoom(step);
    return true;
  };
  api.zoomKeys = function (doc) {
    doc.addEventListener("keydown", function (ev) {
      if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
      var step = (ev.key === "+" || ev.key === "=") ? 1 : (ev.key === "-" || ev.key === "_") ? -1 : ev.key === "0" ? 0 : null;
      if (step !== null && api.zoom(step)) ev.preventDefault();
    }, true);
    doc.addEventListener("wheel", function (ev) {
      if (ev.ctrlKey && ev.deltaY && api.zoom(ev.deltaY < 0 ? 1 : -1)) ev.preventDefault();
    }, { capture: true, passive: false });
  };
  api.closeRightDeliverable = function () {
    if (two && panes[1]) closePane(1);
  };
  api.scrollPane = function (k, deltaY) {
    var t = byId(panes[k]);
    if (!t || !t.frame || !t.frame.contentWindow) return false;
    var d = Number(deltaY) || 420;
    try { t.frame.contentWindow.scrollBy({ top: d, behavior: "smooth" }); } catch (e) {}
    try { t.frame.contentWindow.postMessage({ type: "anchor-scroll-deliverable", deltaY: d }, "*"); } catch (e) {}
    return true;
  };
  api.scrollDeliverable = function (deltaY) {
    if (!two) return false;
    var docPane = 1;
    var t1 = byId(panes[1]), t0 = byId(panes[0]);
    if (t1 && t1.kind === "doc") docPane = 1;
    else if (t0 && t0.kind === "doc") docPane = 0;
    else docPane = active === 0 ? 1 : 0;
    return api.scrollPane(docPane, deltaY);
  };
  api.zoomKeys(document);

  function wireWindow() {
    var h = host();
    if (!h || !h.window_control) return;
    document.body.classList.add("hosted");
    queueRows();
    document.querySelectorAll("#winctl [data-act]").forEach(function (b) {
      b.addEventListener("click", function () { h.window_control(b.dataset.act); });
    });
  }
  if (host()) wireWindow(); else window.addEventListener("pywebviewready", wireWindow);

  window.ANCHOR_APP = api;

  // A cockpit's work continues after its pane/frame is left. Poll only its scoped read-only
  // state and existing review records; neither opening a tile nor selecting it is acceptance.
  function cockpitTarget(t) {
    if (!t || t.kind !== "page") return null;
    var r = resolve(t.url || t.asked);
    if (!r || !/^\/steward\/v\d+$/.test(r.path) || !r.q.get("pid")) return null;
    return {pid:r.q.get("pid"),dir:r.q.get("dir") || "",general:r.q.get("general")==="1",term:r.q.get("term") || ""};
  }
  function paintFeedback(t) {
    var el = t.el;
    if (!el) return;
    var dot = el.querySelector(".activity-dot"); if (!dot) return;
    var target = cockpitTarget(t), key = target && window.AnchorCockpitFeedback.identity(target);
    if (t.feedbackKey !== key) { t.feedbackKey = key; t.feedback = null; t.feedbackRecord = null; }
    var f = t.feedback, light = f ? window.AnchorCockpitFeedback.color(f.light, f.ready) : "gray";
    var word = !f ? "reading activity" : light === "green" ? "working" : light === "orange" ? "needs your attention" : light === "red" ? "a problem" : "idle";
    if (f && f.ready && light !== "orange") word += "; needs your attention";
    dot.className = "activity-dot " + light; dot.title = word; dot.setAttribute("aria-label", word);
    el.classList.toggle("ready", !!(f && f.ready));
    el.title = displayTitle(t) + "; " + word + (f && f.reason ? "; " + f.reason : "");
  }
  var feedbackBusy = false, feedbackAgain = false;
  function refreshFeedback() {
    if (document.hidden || !window.AnchorCockpitFeedback) return;
    if (feedbackBusy) { feedbackAgain = true; return; }
    feedbackBusy = true;
    var list = tiles.filter(cockpitTarget), next = 0;
    function worker() {
      var t = list[next++]; if (!t) return Promise.resolve();
      var target = cockpitTarget(t), key = window.AnchorCockpitFeedback.identity(target);
      function current() { var now = cockpitTarget(byId(t.id)); return !!now && key === window.AnchorCockpitFeedback.identity(now); }
      return window.AnchorCockpitFeedback.read(target,t.feedbackRecord,{},function (st, question) {
        if (!current()) return;
        t.feedback = {light:st.light,ready:question || !!(t.feedback && t.feedback.ready),reason:question?"needs your answer":(t.feedback && t.feedback.reason) || ""};
        paintFeedback(t);
      }).then(function (value) {
        if (!current()) return;
        var before = t.feedback || {};
        t.feedback = {light:value.state.light,ready:value.ready===null?!!before.ready:value.ready,reason:value.ready===null?before.reason:value.reason};
        if (value.record) t.feedbackRecord = value.record;
        paintFeedback(t);
      }).catch(function () {}).then(worker);
    }
    Promise.all([worker(),worker(),worker(),worker()]).finally(function () {
      feedbackBusy = false;
      if (feedbackAgain) { feedbackAgain = false; refreshFeedback(); }
    });
  }
  setInterval(refreshFeedback,5000);
  document.addEventListener("visibilitychange",function () { if (!document.hidden) refreshFeedback(); });
  window.addEventListener("focus",refreshFeedback);

  // ---------- start: the Cave alone ----------
  var cave = { id: "cave", kind: "cave", url: CAVE_URL, title: "Cave of Wonders", name: "", opener: null, frame: null };
  tiles.push(cave);
  cave.frame = newFrame(CAVE_URL);
  layout();
  render();
  try {
    var initOpen = new URLSearchParams(location.search).get("open");
    if (initOpen && /^\/(onboard-wizard|setup)\b/.test(initOpen)) api.open(initOpen, "", window);
  } catch (_e) {}
})();
