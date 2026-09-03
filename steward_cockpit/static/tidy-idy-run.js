/* Tidy-Idy thin caller for the AI cockpit workbench.
   Same endpoints as the classic project window: POST /api/rnd/tidy_idy_run,
   poll /api/rnd/tidy_idy_status, open the triage panel (loopback locally,
   Anchor proxy remotely). */
(function (global) {
  "use strict";

  function _pid() {
    return String(
      global.STEWARD_PID ||
      (typeof global.PROJECT_ID !== "undefined" && global.PROJECT_ID) ||
      (global.ANCHOR_BOOT && global.ANCHOR_BOOT.project_id) ||
      ""
    );
  }
  function _anchorToken() {
    try {
      return global.STEWARD_TOKEN || localStorage.getItem("anchor_token") || "";
    } catch (e) {
      return global.STEWARD_TOKEN || "";
    }
  }
  function setAnchorToken() {
    var cur = _anchorToken();
    var t = global.prompt("Paste your Anchor access token:", cur);
    if (t === null) return false;
    try {
      if (t) localStorage.setItem("anchor_token", t.trim());
      else localStorage.removeItem("anchor_token");
      global.STEWARD_TOKEN = (t || "").trim();
    } catch (e) {}
    return true;
  }
  function _postJson(url, payload) {
    var headers = { "Content-Type": "application/json" };
    var tok = _anchorToken();
    if (tok) headers["X-Anchor-Token"] = tok;
    if (tok) headers["Authorization"] = "Bearer " + tok;
    return fetch(url, { method: "POST", headers: headers, body: JSON.stringify(payload) });
  }
  function _isUnauthorized(r, data) {
    return r.status === 401 || (data && data.error === "unauthorized");
  }

  async function tidyIdyRun(_backend) {
    var tidyProjectId = _pid();
    if (!tidyProjectId) {
      alert("[tidy-idy] This cockpit has no project id — reload and try again.");
      return;
    }
    var winName = "tidy-idy-" + String(tidyProjectId || "run");
    var win = null;
    var localPage = (function () {
      var h = (location.hostname || "").toLowerCase();
      return h === "127.0.0.1" || h === "localhost" || h === "[::1]";
    })();

    function _isLoopbackUrl(u) {
      if (!u) return false;
      try {
        var x = new URL(u, location.href);
        var h = (x.hostname || "").toLowerCase();
        return h === "127.0.0.1" || h === "localhost" || h === "[::1]";
      } catch (_e) { return false; }
    }
    function _withToken(url) {
      if (!url) return url;
      var tok = _anchorToken();
      if (!tok) return url;
      return url + (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(tok);
    }
    function _absoluteUrl(url) {
      if (!url) return null;
      try {
        if (/^https?:\/\//i.test(url) || /^data:/i.test(url)) return url;
        if (url.charAt(0) === "/") return String(location.origin || "") + url;
        return new URL(url, location.href).href;
      } catch (_e) { return url; }
    }
    function _browserUrl(targetUrl, proxyPath) {
      var out = null;
      if (proxyPath) out = _withToken(proxyPath);
      else if (!targetUrl) out = null;
      else if (!_isLoopbackUrl(targetUrl)) out = targetUrl;
      else if (localPage) out = targetUrl;
      else {
        try {
          var x = new URL(targetUrl);
          var sub = x.pathname + (x.search || "");
          if (!sub) sub = "/";
          if (sub === "/" || sub === "") out = null;
          else out = _withToken("/api/rnd/tidy_idy_proxy/" + encodeURIComponent(tidyProjectId) + sub);
        } catch (_e) { out = null; }
      }
      return _absoluteUrl(out);
    }
    function _isPanelUrl(u) {
      if (!u) return false;
      return String(u).indexOf("/bootstrap/") >= 0 || String(u).indexOf("tidy_idy_proxy") >= 0;
    }

    var _TIDY_FAVICON_SVG = "data:image/svg+xml," + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">' +
      '<rect width="32" height="32" rx="7" fill="#1a2332"/>' +
      '<path d="M8 22c2-6 5-10 9-12 1.2 2.5 2 5.2 2.2 8.2 2.8-.4 5 .6 6.8 2.4-3.2 1.2-6.5 1.6-9.5.6C13.2 23 10.5 23 8 22z" fill="#8ab4f8"/>' +
      '<path d="M11 9l2.2 1.1L14.5 8l.8 2.3L17.5 11l-2.3.7L14.5 14l-1.1-2.2L11 11.2l2.2-.6z" fill="#fdd663"/>' +
      "</svg>"
    );
    var _TIDY_FAVICON_ABS = _absoluteUrl("/vendor/brand/tidy-idy-icon.jpg");

    function _writeStatusShell(message) {
      if (!win || win.closed) return;
      try {
        win.document.open();
        win.document.write(
          '<!doctype html><html><head><meta charset="utf-8"/><title>Tidy-Idy…</title>' +
          '<link rel="icon" href="' + _TIDY_FAVICON_SVG + '" type="image/svg+xml"/>' +
          (_TIDY_FAVICON_ABS ? '<link rel="icon" href="' + _TIDY_FAVICON_ABS + '" type="image/jpeg"/>' : "") +
          "<style>" +
          "body{font-family:system-ui,sans-serif;background:#0f1115;color:#e8eaed;padding:2rem;line-height:1.5;margin:0}" +
          ".card{max-width:36rem;border:1px solid #2a2f3a;border-radius:12px;padding:1.25rem 1.4rem;background:#161a22}" +
          ".phase{display:inline-block;font-size:.75rem;letter-spacing:.04em;text-transform:uppercase;" +
          "color:#8ab4f8;border:1px solid rgba(138,180,248,.33);border-radius:999px;padding:.15rem .6rem;margin-bottom:.75rem}" +
          "h2{margin:0 0 .5rem;font-size:1.35rem;font-weight:600}" +
          "#msg{margin:0 0 .75rem;font-size:1.05rem}" +
          ".bar-meta{display:flex;justify-content:space-between;font-size:.85rem;color:#9aa0a6;margin-bottom:.35rem}" +
          "#pct{color:#8ab4f8;font-weight:600;font-variant-numeric:tabular-nums}" +
          ".bar{height:.55rem;background:#2a2f3a;border-radius:999px;overflow:hidden;margin-bottom:.5rem}" +
          ".bar>i{display:block;height:100%;width:2%;background:linear-gradient(90deg,#8ab4f8,#8ab4f8cc);" +
          "border-radius:999px;transition:width .4s ease}" +
          "#detail{color:#9aa0a6;font-size:.9rem;margin:.5rem 0 0;white-space:pre-wrap}" +
          "#alive{color:#9aa0a6;font-size:.8rem;margin:.65rem 0 0}" +
          "#openBtn{display:none;margin-top:1rem;padding:.55rem 1rem;border:0;border-radius:8px;" +
          "background:#8ab4f8;color:#0f1115;font:600 14px system-ui;cursor:pointer}" +
          "</style></head><body><div class='card'>" +
          '<div class="phase" id="phase">starting</div>' +
          "<h2>Tidy-Idy</h2>" +
          "<p id='msg'>" + (message || "Starting hygiene pass…") + "</p>" +
          '<div class="bar-meta"><span id="stepLabel">Starting</span><span id="pct">0%</span></div>' +
          '<div class="bar"><i id="barFill"></i></div>' +
          '<p id="detail"></p><p id="alive">Waiting for first status…</p>' +
          '<button type="button" id="openBtn">Open Triage Panel</button>' +
          "</div></body></html>"
        );
        win.document.close();
      } catch (_w) {}
    }
    function _showOpenButton(absUrl) {
      if (!win || win.closed || !absUrl) return;
      try {
        var btn = win.document.getElementById("openBtn");
        if (!btn) return;
        btn.style.display = "inline-block";
        btn.onclick = function () {
          try { win.location.href = absUrl; } catch (_e) {
            try { window.open(absUrl, winName); } catch (_e2) {}
          }
        };
      } catch (_e) {}
    }
    function _setProgress(pct, stepLabel) {
      if (!win || win.closed) return;
      try {
        var p = Math.max(0, Math.min(100, Number(pct) || 0));
        var fill = win.document.getElementById("barFill");
        if (fill) fill.style.width = p + "%";
        var pctEl = win.document.getElementById("pct");
        if (pctEl) pctEl.textContent = Math.round(p) + "%";
        var sl = win.document.getElementById("stepLabel");
        if (sl && stepLabel) sl.textContent = stepLabel;
        try { win.document.title = Math.round(p) + "% · Tidy-Idy"; } catch (_t) {}
      } catch (_e) {}
    }
    function _setWinMsg(msg, phase, detail, progress, stepLabel, alive) {
      if (!win || win.closed) return;
      try {
        var el = win.document.getElementById("msg");
        if (el) el.textContent = msg || "";
        else _writeStatusShell(msg);
        var ph = win.document.getElementById("phase");
        if (ph && phase) ph.textContent = phase;
        var det = win.document.getElementById("detail");
        if (det && detail != null) det.textContent = detail;
        if (progress != null || stepLabel) _setProgress(progress != null ? progress : 0, stepLabel);
        var al = win.document.getElementById("alive");
        if (al && alive != null) al.textContent = alive;
      } catch (_e) {}
    }
    function _fmtElapsed(ms) {
      if (!isFinite(ms) || ms < 0) return "0s";
      var s = Math.floor(ms / 1000);
      if (s < 60) return s + "s";
      var m = Math.floor(s / 60); s = s % 60;
      if (m < 60) return m + "m " + s + "s";
      var h = Math.floor(m / 60); m = m % 60;
      return h + "h " + m + "m";
    }
    function _aliveLine(st) {
      var parts = [];
      if (st && st.startedAt) {
        var t0 = Date.parse(st.startedAt);
        if (isFinite(t0)) parts.push("elapsed " + _fmtElapsed(Date.now() - t0));
      }
      if (st && st.updatedAt) {
        var t1 = Date.parse(st.updatedAt);
        if (isFinite(t1)) {
          var age = Date.now() - t1;
          parts.push(age < 2500 ? "status fresh" : ("last update " + _fmtElapsed(age) + " ago"));
        }
      }
      return parts.length ? parts.join(" · ") : "Working…";
    }
    function _navWin(url) {
      if (!url) return false;
      url = _absoluteUrl(url);
      if (!url) return false;
      if (win && !win.closed) {
        try { win.location.href = url; return true; } catch (_nav) {
          try { win.location = url; return true; } catch (_n2) {}
        }
      }
      try { win = window.open(url, winName); return Boolean(win); } catch (_o) { return false; }
    }
    function _navBest(targetUrl, proxyPath, phase) {
      if (!localPage && targetUrl && _isLoopbackUrl(targetUrl) && !_isPanelUrl(targetUrl)
          && phase !== "panel-ready") {
        return null;
      }
      var dest = null;
      if (proxyPath && String(proxyPath).indexOf("/bootstrap/") >= 0) {
        dest = _browserUrl(null, proxyPath);
      } else if (targetUrl && _isPanelUrl(targetUrl)) {
        dest = _browserUrl(targetUrl, proxyPath);
      } else if (phase === "panel-ready" && proxyPath) {
        dest = _browserUrl(targetUrl, proxyPath);
      } else {
        dest = _browserUrl(targetUrl, proxyPath);
      }
      if (!dest) return null;
      if (/\/api\/rnd\/tidy_idy_proxy\/[^/]+\/?(\?|$)/.test(dest) && dest.indexOf("/bootstrap/") < 0) {
        return null;
      }
      _navWin(dest);
      return dest;
    }

    try {
      win = window.open("about:blank", winName);
      _writeStatusShell(
        "Starting hygiene pass… this can take a minute on large folders. " +
        (localPage
          ? "Live status updates here; the Triage Panel opens in this tab when ready."
          : "You are on a remote Anchor session — status stays in this tab (via Anchor); the panel opens through Anchor when ready.")
      );
      try { if (win) win.focus(); } catch (_f) {}
    } catch (_o) { win = null; }

    var payload = { project_id: tidyProjectId, async: true };
    var r, data;
    try {
      r = await _postJson("/api/rnd/tidy_idy_run", payload);
      data = await r.json();
      if (_isUnauthorized(r, data) && setAnchorToken()) {
        r = await _postJson("/api/rnd/tidy_idy_run", payload);
        data = await r.json();
      }
    } catch (e) {
      _setWinMsg("Error: " + String(e.message || e), "failed", null, 100, "Failed");
      alert("[tidy-idy error] " + e.message);
      return;
    }

    if (!data || !data.ok) {
      var reopen = (data && (data.proxy_open_path || data.open_url || data.status_url)) || null;
      if (reopen || (data && data.proxy_open_path)) {
        if (!_navBest(data.open_url || data.status_url, data.proxy_open_path || data.proxy_status_path,
            data.phase || "panel-ready")) {
          if (data.phase === "panel-ready" || data.open_url) {
            alert("[tidy-idy] A run is live but the browser blocked the popup.");
          }
        } else {
          return;
        }
      } else {
        var err = (data && (data.error || data.code)) || "unknown";
        _setWinMsg("Refused: " + err, "refused", null, 100, "Refused");
        alert("[tidy-idy refused] " + err);
        return;
      }
    }

    var phase = data.phase || (data.already_running ? "scanning" : "starting");
    var message = data.message || (data.already_running
      ? "A tidy-idy run is already in progress for this project."
      : "Hygiene pass started…");
    var prog = (data.progress != null) ? data.progress : (
      phase === "panel-ready" ? 100 :
      phase === "archiving" ? 96 :
      phase === "analyzing" ? 20 :
      phase === "scanning" ? 8 : 2
    );
    var stepLab = data.stepLabel || data.step || phase || "Starting";
    _setWinMsg(message, phase, data.job_id ? ("job " + data.job_id) : "", prog, stepLab);
    _setProgress(prog, stepLab);
    var readyUrl = data.open_url || data.panel_base ||
      (data.panel && (data.panel.bootstrapUrl || data.panel.baseUrl || data.panel.url));
    var statusUrl = data.status_url || null;
    var proxyOpen = data.proxy_open_path || null;
    var proxyStatus = data.proxy_status_path || null;

    if (phase === "panel-ready" || (data.already_running && phase === "panel-ready")) {
      _setProgress(100, "Panel ready");
      var destReady = _navBest(readyUrl, proxyOpen, "panel-ready");
      if (destReady) {
        _showOpenButton(destReady);
        _setWinMsg(
          "Triage Panel is ready — opening… If it does not appear, click the button below.",
          "panel-ready", destReady, 100, "Panel ready"
        );
        return;
      }
      _setWinMsg(
        "Triage Panel is ready but no open URL was returned. Re-click Tidy-Idy, or check Anchor jobs.",
        "panel-ready", null, 100, "Panel ready"
      );
    }
    if (statusUrl && localPage) {
      if (_navBest(statusUrl, proxyStatus, phase)) return;
    }

    var jobId = data.job_id || null;
    if (!jobId && !statusUrl && !readyUrl && !data.already_running) {
      _setWinMsg("Run reported ok but returned no status or panel URL.", "failed", null, 100, "Failed");
      alert("[tidy-idy] run reported ok but returned no status or panel URL.");
      return;
    }

    var polls = 0;
    var maxPolls = 600;
    async function _pollOnce() {
      polls++;
      var st = null;
      try {
        var sr = await _postJson("/api/rnd/tidy_idy_status", {
          project_id: tidyProjectId,
          job_id: jobId || null
        });
        st = await sr.json();
        if (_isUnauthorized(sr, st) && setAnchorToken()) {
          sr = await _postJson("/api/rnd/tidy_idy_status", {
            project_id: tidyProjectId,
            job_id: jobId || null
          });
          st = await sr.json();
        }
      } catch (_pe) { st = null; }
      if (!st || !st.ok) {
        var failMsg = (st && (st.error || st.message)) || "Status poll failed (network or auth). Retrying…";
        if (failMsg && String(failMsg).indexOf("project_id") >= 0) {
          failMsg = "Status poll missing project id — hard-refresh this cockpit, then click Tidy-Idy again.";
        }
        _setWinMsg(failMsg, (st && st.phase) || "running", "poll " + polls, null, null, "poll error · will retry");
        if (polls < maxPolls) setTimeout(_pollOnce, 1000);
        return;
      }
      if (st.upstreamLive === false && (st.phase === "done" || st.stale || st.phase === "failed")) {
        _setProgress(100, st.phase === "failed" ? "Failed" : "Session ended");
        _setWinMsg(
          st.message || "Previous tidy-idy session ended. Re-click Tidy-Idy to start a fresh pass.",
          st.phase || "done", st.staleReason || "", 100, "Session ended", _aliveLine(st)
        );
        return;
      }
      var detailBits = [];
      if (st.stepIndex != null && st.stepTotal != null) {
        detailBits.push("step " + st.stepIndex + " / " + st.stepTotal + (st.step ? " (" + st.step + ")" : ""));
      } else if (st.step) {
        detailBits.push("step: " + st.step);
      }
      if (st.findings != null) detailBits.push(st.findings + " finding(s)");
      _setWinMsg(
        st.message || "Working…",
        st.phase || "running",
        detailBits.join(" · "),
        st.progress != null ? st.progress : 0,
        st.stepLabel || st.step || st.phase || "Working",
        _aliveLine(st)
      );

      if (st.phase === "panel-ready") {
        var openTarget = st.openUrl;
        if (openTarget && String(openTarget).indexOf("/bootstrap/") < 0 && st.proxyOpenPath) {
          openTarget = null;
        }
        var proxyForOpen = st.proxyOpenPath || null;
        if (!localPage && proxyForOpen && String(proxyForOpen).indexOf("/bootstrap/") < 0) {
          if (polls < maxPolls) setTimeout(_pollOnce, 1000);
          _setWinMsg("Panel is ready on the host — waiting for the open link…",
            "panel-ready", "", 100, "Panel ready", _aliveLine(st));
          return;
        }
        _setProgress(100, "Panel ready");
        var dest = _navBest(
          localPage ? (openTarget || st.openUrl) : null,
          proxyForOpen || (localPage ? null : st.proxyOpenPath),
          "panel-ready"
        );
        if (dest) {
          _showOpenButton(dest);
          _setWinMsg(
            "Triage Panel is ready — opening… If it does not appear, click Open Triage Panel.",
            "panel-ready", dest, 100, "Panel ready", _aliveLine(st)
          );
          return;
        }
        _setWinMsg(
          "Panel is ready on the host, but this browser could not open it. Re-click Tidy-Idy.",
          "panel-ready", "", 100, "Panel ready", _aliveLine(st)
        );
        return;
      }
      if (localPage && st.statusUrl && !statusUrl) {
        statusUrl = st.statusUrl;
        if (_navBest(st.statusUrl, st.proxyStatusPath, st.phase)) return;
      }
      if (st.phase === "failed" || st.phase === "refused" || st.phase === "done") {
        _setProgress(100, st.phase);
        return;
      }
      if (polls < maxPolls) setTimeout(_pollOnce, 1000);
      else {
        _setWinMsg(
          "Still running, but status polling timed out in this tab. Re-click Tidy-Idy to re-open.",
          st.phase || "running", null, st.progress != null ? st.progress : 0,
          st.stepLabel || st.phase, _aliveLine(st)
        );
      }
    }
    setTimeout(_pollOnce, 250);
  }

  global.tidyIdyRun = tidyIdyRun;
})(window);
