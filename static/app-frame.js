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
  try { app.zoomKeys(document); } catch (e) { /* zoom is a convenience */ }
  // a click anywhere in a pane makes that pane the active one (where the next tile he clicks will show)
  document.addEventListener("pointerdown", function () { try { app.touch(window); } catch (e) { /* no app */ } }, true);

  if (window.parent === window.top) {
    window.close = function () { try { app.closeWindow(window); } catch (e) { /* nothing to close */ } };
  }
})();
