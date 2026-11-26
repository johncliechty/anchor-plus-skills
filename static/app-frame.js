/* app-frame.js - the one script that makes a page behave inside the Anchor app (static/app.html).
 *
 * Inert unless the page sits somewhere inside app.html (window.top.ANCHOR_APP). Loaded two ways:
 *   - FIRST in a cockpit page (/project/<pid>, /steward/v1|v3|report), by the client shim in
 *     steward_cockpit/steward_routes.py, so the shim's own window.open wrapper wraps OURS and its
 *     /report -> /steward/report rewrite still happens;
 *   - by app.html itself on every other frame's load (the Cave, the Campaign page, the Desk), whose
 *     opens all happen on a click, long after load.
 * What it does (PLAN v2.2 section 3.2):
 *   - window.open for an Anchor page or deliverable asks the app for a tile and returns that tile
 *     frame's REAL window, so callers' .location =, .location.replace, .closed and named targets work;
 *     downloads, other sites and non-http links (ms-word:, mailto:) go to the native call, which the
 *     desktop host hands to Windows;
 *   - a link with a new-window target (_blank or a name) does the same, unless the page handled the click;
 *   - inside a tile the app opened for a caller, window.opener is that caller and window.close() closes
 *     the tile (the New-project popup's opener.postMessage handshake).
 */
(function () {
  "use strict";
  if (window.__anchorFrame) return;
  var app = null;
  try { app = window.top && window.top.ANCHOR_APP; } catch (e) { app = null; }
  if (!app || window === window.top) return;
  window.__anchorFrame = true;

  function toSplitVideoUrl(rawUrl, title) {
    var m = String(rawUrl || "").trim().match(/^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/)|youtu\.be\/)([A-Za-z0-9_-]{6,15})/i);
    if (!m) return "";
    return "/steward-static/video.html?v=" + encodeURIComponent(m[1]) +
      "&url=" + encodeURIComponent(String(rawUrl || "").trim()) +
      (title ? "&title=" + encodeURIComponent(String(title).trim()) : "");
  }
  var nativeOpen = window.open;
  window.open = function (url, target, features) {
    var vUrl = toSplitVideoUrl(url, "");
    if (vUrl && location.pathname !== "/steward-static/video.html") url = vUrl;
    var rawUrl = String(url == null ? "" : url).trim();
    if (rawUrl && (/\/static\/calendar-alarm\.html\b/i.test(rawUrl) || /[?&]alarm_window=1\b/i.test(rawUrl))) {
      return nativeOpen.call(window, url, target, features);
    }
    try { if (app.download(url, window)) return null; } catch (e) {}
    var w = null;
    try { w = app.open(url, target, window, features); } catch (e) { w = null; }
    if (w) return w;
    if (!rawUrl || /^about:/i.test(rawUrl)) return null;
    try {
      var u = new URL(rawUrl, window.location.href);
      if (u.origin === window.top.location.origin && !/^(ms-\w+|mailto|tel|file):/i.test(rawUrl)) {
        return null;
      }
    } catch (e) {}
    return nativeOpen.call(window, url, target, features);
  };

  function onDocClick(ev, isCapture) {
    if (ev.defaultPrevented || ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
    if (!a) return;
    var href = a.getAttribute("href") || "";
    if (!href || href === "#" || /^javascript:/i.test(href)) return;
    if (a.hasAttribute("download")) {
      var topWv = null;
      try { topWv = window.top && window.top.pywebview && window.top.pywebview.api; } catch (e) { topWv = null; }
      if (topWv && typeof topWv.save_download === "function" && !/^(blob|data):/i.test(href)) {
        if (isCapture && typeof a.onclick === "function") return;
        try { if (app.download(a.href, window, a.getAttribute("download") || true)) { ev.preventDefault(); return; } } catch (e) {}
      }
      return;
    }
    if (isCapture && typeof a.onclick === "function") return;
    try { if (app.download(a.href, window)) { ev.preventDefault(); return; } } catch (e) { /* the link goes as it was */ }
    if (/^(ms-\w+|mailto|tel|file):/i.test(href)) {          // an app link: Windows opens it, never the frame
      ev.preventDefault(); nativeOpen.call(window, href, "_blank"); return;
    }
    var vidHref = (location.pathname !== "/steward-static/video.html") ? toSplitVideoUrl(a.href || href, a.textContent || "") : "";
    if (vidHref) {
      var vw = null;
      try { vw = app.open(vidHref, "_blank", window); } catch (e) { vw = null; }
      if (vw) { ev.preventDefault(); return; }
    }
    var t = (a.getAttribute("target") || "").toLowerCase();
    if (!t || t === "_self" || t === "_parent" || t === "_top") return;
    var w = null;
    try { w = app.open(a.href, a.getAttribute("target"), window); } catch (e) { w = null; }
    if (w) ev.preventDefault();
  }
  document.addEventListener("click", function (ev) { onDocClick(ev, true); }, true);
  document.addEventListener("click", function (ev) { onDocClick(ev, false); }, false);

  try {
    var opener = app.openerOf(window);
    if (opener) Object.defineProperty(window, "opener", { configurable: true, get: function () { return opener; } });
  } catch (e) { /* the page keeps its own opener */ }

  // Live-sync an already-open Anchor.exe shell (even if app.html has not reloaded since an earlier session):
  // 1) Reset accidental >100% shell ZoomFactor once; 2) upgrade ANCHOR_APP.open & split ratio for docs.
  try {
    var topWin = window.top;
    if (topWin && topWin !== window) {
      var topHost = topWin.pywebview && topWin.pywebview.api;
      if (topHost && typeof topHost.zoom === "function" &&
          topWin.location && topWin.location.hostname !== "anchor.test" &&
          localStorage.getItem("anchor_shell_zoom_reset_20261122_v2") !== "1") {
        localStorage.setItem("anchor_shell_zoom_reset_20261122_v2", "1");
        topHost.zoom(0);
      }
      if (!topWin.__anchorDocFit20261122 && topWin.ANCHOR_APP) {
        topWin.__anchorDocFit20261122 = true;
        var origOpen = topWin.ANCHOR_APP.open;
        if (typeof origOpen === "function") {
          topWin.ANCHOR_APP.open = function (u, target, fromWin, features) {
            try {
              var full = new URL(String(u == null ? "" : u), (fromWin && fromWin.location ? fromWin.location.href : topWin.location.href));
              if (full.origin === topWin.location.origin &&
                  full.pathname === "/api/steward/deliverable-file" &&
                  full.searchParams.get("download") !== "1" &&
                  full.searchParams.get("raw") !== "1" &&
                  full.searchParams.get("scrollview") !== "0" &&
                  !full.searchParams.has("scrollview") &&
                  !full.searchParams.has("pdf_page")) {
                var qp = (full.searchParams.get("path") || "").toLowerCase();
                if (qp.endsWith(".pdf") || qp.endsWith(".html") || qp.endsWith(".htm") || (qp.endsWith(".pptx") && full.searchParams.get("view") === "1")) {
                  full.searchParams.set("scrollview", "1");
                  u = full.pathname + full.search + full.hash;
                }
              }
            } catch (_eu) {}
            var stg = topWin.document && topWin.document.getElementById("stage");
            if (stg && !stg.style.getPropertyValue("--left")) {
              stg.style.setProperty("--left", "0.44");
            }
            return origOpen.call(topWin.ANCHOR_APP, u, target, fromWin, features);
          };
        }
        if (typeof topWin.ANCHOR_APP.openSecondWindow !== "function") {
          topWin.ANCHOR_APP.openSecondWindow = function (u, _title, fromWin) {
            return topWin.ANCHOR_APP.open(u, "_blank", fromWin);
          };
        }
      }
    }
  } catch (_eTop) {}

  // Provide scoped document zoom (Ctrl +/-/0, Ctrl+wheel) on Office/Markdown/text deliverable frames
  // that carry no inline scripts of their own (e.g. office_preview.py), without touching cockpit/Cave pages.
  try {
    if (typeof window.__anchorPdfZoom !== "function" &&
        (location.pathname === "/api/steward/deliverable-file" ||
         location.pathname === "/steward/report" ||
         location.pathname.indexOf("/report/") === 0 ||
         location.pathname.indexOf("/summary/") === 0 ||
         location.pathname.indexOf("/artifact/") === 0)) {
      var _docPct = 100;
      window.__anchorPdfZoom = function (step) {
        if (Number(step) === 0) _docPct = 100;
        else _docPct = Math.max(60, Math.min(240, _docPct + (Number(step) > 0 ? 15 : -15)));
        var tgt = document.getElementById("opMain") || document.querySelector("main, .anchor-reader") || document.body;
        if (tgt) {
          tgt.style.zoom = (_docPct === 100) ? "" : (_docPct + "%");
          if (tgt.tagName === "MAIN") tgt.style.maxWidth = (_docPct > 100) ? "none" : "980px";
        }
        document.documentElement.style.overflowX = (_docPct > 100) ? "auto" : "hidden";
        return _docPct;
      };
    }
  } catch (_eDocZ) {}

  // Intercept Ctrl +/-/0 and Ctrl+wheel inside zoomable document frames BEFORE app.zoomKeys(document),
  // so even an un-reloaded older app.js in window.top never zooms the entire Anchor.exe shell.
  document.addEventListener("keydown", function (ev) {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
    if (typeof window.__anchorPdfZoom !== "function") return;
    var k = ev.key || "";
    var step = (k === "+" || k === "=" || ev.code === "NumpadAdd") ? 1
             : (k === "-" || k === "_" || ev.code === "NumpadSubtract") ? -1
             : (k === "0" || ev.code === "Numpad0") ? 0 : null;
    if (step !== null) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      try { window.__anchorPdfZoom(step); } catch (_ez) {}
    }
  }, true);
  document.addEventListener("wheel", function (ev) {
    if (!(ev.ctrlKey || ev.metaKey) || !ev.deltaY) return;
    if (typeof window.__anchorPdfZoom !== "function") return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    try { window.__anchorPdfZoom(ev.deltaY < 0 ? 1 : -1, ev.clientX, ev.clientY); } catch (_ew) {}
  }, { capture: true, passive: false });

  try { app.zoomKeys(document); } catch (e) { /* zoom is a convenience */ }
  // a click anywhere in a pane makes that pane the active one; moving the pointer tracks which pane is hovered
  document.addEventListener("pointerdown", function () { try { app.touch(window); } catch (e) { /* no app */ } }, true);
  document.addEventListener("pointerenter", function () { try { if (app.hover) app.hover(window); } catch (e) {} }, true);
  document.addEventListener("pointermove", function () { try { if (app.hover) app.hover(window); } catch (e) {} }, { capture: true, passive: true });

  if (window.parent === window.top) {
    window.close = function () { try { app.closeWindow(window); } catch (e) { /* nothing to close */ } };
  }
})();
