/* Anchor R&D interactive terminal — REAL xterm.js adapter (Wave 7+).
 *
 * SUBSTRATE: This is now a genuine xterm.js terminal. The upstream xterm.js
 * library (vendored offline at /vendor/xterm/xterm.js, exposing window.Terminal)
 * renders the live SSE output stream as a real terminal canvas. This file is the
 * ADAPTER + REPL chrome that drives that Terminal and layers the Anchor-specific
 * affordances xterm.js does NOT provide on its own:
 *   - feeds the SSE assistant output into term.write() (\n -> \r\n)
 *   - captures typed input (a DOM input line beneath the terminal) and POSTs
 *     turns to the live persistent stream-json REPL session
 *   - surfaces in-session gates / AskUserQuestion inline as clickable chrome
 *   - on process exit, runs the discover -> confirm-adopt flow
 *   - best-effort reaps the abandoned persistent process on tab close / dispose
 *
 * The PUBLIC surface is UNCHANGED: window.AnchorTerm.mount(opts) with the same
 * opts and the same dispose()/beforeunload reap behavior, so the project-window
 * openTerminal() caller and the asset/wiring tests need no integration rewrite.
 * The same backend calls are used, unchanged: SSE GET /api/rnd/term_stream,
 * POST /api/rnd/term_input, /api/rnd/term_discover, /api/rnd/term_adopt, and the
 * unload reap POST /api/rnd/cancel_job.
 *
 * Pure browser JS. xterm.js is vendored as a static asset (like KaTeX); no
 * native/compiled code, no network, no npm.
 */
(function () {
  "use strict";

  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  // A single terminal instance bound to one session_id.
  function AnchorTerm(opts) {
    this.host = opts.host;                 // container element
    this.sessionId = opts.session;         // job_id of the terminal session
    this.lane = opts.lane || "";
    this.title = opts.title || (this.lane || "terminal");
    this.postJson = opts.postJson;         // token-aware POST helper (from caller)
    this.onAdopted = opts.onAdopted || function () {};
    this.cursor = 0;
    this.status = "running";
    this.pending = null;                   // a pending gate prompt, if any
    this.closed = false;
    this._es = null;                       // EventSource (SSE)
    this._term = null;                      // the real xterm.js Terminal
    this._build();
  }

  AnchorTerm.prototype._build = function () {
    this.host.innerHTML = "";
    var root = el("div", "aterm");
    // Title bar.
    var bar = el("div", "aterm-bar");
    this._dot = el("span", "dot live");
    bar.appendChild(this._dot);
    var t = el("span", "title"); t.textContent = this.title; bar.appendChild(t);
    this._statusEl = el("span", "status"); this._statusEl.textContent = "running"; bar.appendChild(this._statusEl);
    root.appendChild(bar);

    // Screen: a REAL xterm.js terminal renders the SSE stream here. The gate /
    // adopt chrome are DOM siblings layered around this canvas (xterm renders the
    // stream only; interactive Anchor affordances stay as accessible HTML).
    this._screen = el("div", "aterm-screen");
    root.appendChild(this._screen);

    // Gate / adopt chrome live BELOW the terminal canvas so xterm owns its grid.
    this._chrome = el("div", "aterm-chrome");
    root.appendChild(this._chrome);

    // Input row (a DOM line, not the xterm grid): cleaner UX for sending whole
    // turns and keeps gate/adopt focus handling simple.
    var row = el("div", "aterm-inputrow");
    var pr = el("span", "prompt"); pr.textContent = "›"; row.appendChild(pr);
    this._input = el("input");
    this._input.setAttribute("placeholder", "type a turn and press Enter…");
    this._input.setAttribute("aria-label", "terminal input");
    var self = this;
    this._input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && self._input.value.trim()) {
        self.sendTurn(self._input.value);
        self._input.value = "";
      }
    });
    row.appendChild(this._input);
    root.appendChild(row);

    this.host.appendChild(root);

    // Instantiate the real xterm.js Terminal. window.Terminal is provided by the
    // vendored UMD bundle (loaded before this script). If it is somehow missing,
    // fall back to a plain pre-element so the console still works degraded.
    if (typeof window.Terminal === "function") {
      var term = new window.Terminal({
        convertEol: true,                  // treat \n as CRLF on write()
        cursorBlink: false,
        disableStdin: true,                // input is the DOM row, not the grid
        scrollback: 5000,
        fontFamily: 'ui-monospace, "Cascadia Code", Consolas, Menlo, monospace',
        fontSize: 12.5,
        theme: {
          background: "#0a0c11", foreground: "#cdd2dc",
          cursor: "#0a0c11", selectionBackground: "#2e3340"
        }
      });
      term.open(this._screen);
      this._term = term;
    } else {
      // Degraded fallback (no xterm.js): a scrollback pre we write() into.
      this._fallbackPre = el("pre", "aterm-fallback");
      this._screen.appendChild(this._fallbackPre);
    }
    this._input.focus();
  };

  // Write a chunk to the real terminal (or the degraded fallback). xterm's
  // convertEol handles \n, but we normalize explicitly so a CR-less stream also
  // advances lines, and we never inject raw HTML (xterm renders text, not HTML).
  AnchorTerm.prototype._termWrite = function (text) {
    if (text == null) return;
    var s = String(text);
    if (this._term) {
      // Normalize bare LF to CRLF so each line starts at column 0.
      this._term.write(s.replace(/\r?\n/g, "\r\n"));
    } else if (this._fallbackPre) {
      this._fallbackPre.textContent += s.replace(/\r/g, "");
      this._screen.scrollTop = this._screen.scrollHeight;
    }
  };

  AnchorTerm.prototype.writeLine = function (text, kind) {
    // Roles get a subtle inline ANSI color so user echoes/system/error lines are
    // distinguishable inside the real terminal (SGR codes, reset after).
    var color = "";
    if (kind === "user") color = "\x1b[38;2;108;156;252m";        // blue
    else if (kind === "system") color = "\x1b[38;2;139;143;154m"; // dim
    else if (kind === "error") color = "\x1b[38;2;248;113;113m";  // red
    var line = String(text == null ? "" : text);
    if (color && this._term) this._termWrite(color + line + "\x1b[0m\r\n");
    else this._termWrite(line + "\n");
  };

  // Render a server output chunk. The SSE "output" event carries raw stream-json
  // lines from the engine; we surface them verbatim into the real terminal.
  AnchorTerm.prototype._renderOutput = function (payload) {
    var lines = payload && payload.lines ? payload.lines : [];
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      this.writeLine(typeof ln === "string" ? ln : JSON.stringify(ln), "assistant");
    }
    if (payload && typeof payload.next === "number") this.cursor = payload.next;
  };

  AnchorTerm.prototype._setStatus = function (st) {
    if (!st) return;
    this.status = st;
    if (this._statusEl) this._statusEl.textContent = st;
    if (this._dot) {
      this._dot.className = "dot" +
        (st === "running" || st === "awaiting-input" ? " live" :
         (st === "done" ? " done" : (st === "failed" || st === "cancelled" || st === "interrupted" ? " fail" : "")));
    }
  };

  AnchorTerm.prototype._renderGate = function (prompt) {
    this.pending = prompt;
    var g = el("div", "aterm-gate");
    var q = el("div", "q"); q.textContent = prompt && prompt.question ? prompt.question : "Input requested";
    g.appendChild(q);
    var opts = el("div", "opts");
    var list = (prompt && prompt.options) || [];
    var self = this;
    list.forEach(function (o) {
      var label = (o && o.label != null) ? o.label : String(o);
      var b = el("button", "opt");        // value set via DOM, never string-concatenated into HTML
      b.textContent = label;
      b.addEventListener("click", function () { self.sendTurn(label); });
      opts.appendChild(b);
    });
    g.appendChild(opts);
    this._chrome.appendChild(g);
  };

  // POST one turn to the live session stdin (token-aware via the caller's helper).
  AnchorTerm.prototype.sendTurn = function (text) {
    text = (text || "").trim();
    if (!text || this.closed) return;
    this.writeLine("› " + text, "user");
    this.pending = null;
    // Clear any rendered gate prompts once a turn is sent (they were answered).
    if (this._chrome) {
      var gates = this._chrome.querySelectorAll(".aterm-gate");
      for (var i = 0; i < gates.length; i++) gates[i].parentNode.removeChild(gates[i]);
    }
    var self = this;
    var payload = { session: this.sessionId, text: text };
    Promise.resolve(this.postJson("/api/rnd/term_input", payload))
      .then(function (data) {
        if (!data || !data.ok) {
          self.writeLine("[input refused: " + ((data && (data.error || data.reason)) || "unknown") + "]", "error");
        }
      })
      .catch(function (e) { self.writeLine("[input error] " + e.message, "error"); });
  };

  // Start consuming the SSE stream. The endpoint heartbeats + terminates cleanly,
  // so on a benign close we re-open while the session is still live.
  AnchorTerm.prototype.start = function () {
    if (this.closed) return;
    var self = this;
    var url = "/api/rnd/term_stream?session=" + encodeURIComponent(this.sessionId) +
              "&since=" + encodeURIComponent(this.cursor);
    var es = new EventSource(url);
    this._es = es;
    es.addEventListener("output", function (ev) {
      try { self._renderOutput(JSON.parse(ev.data)); } catch (e) {}
    });
    es.addEventListener("status", function (ev) {
      try { self._setStatus(JSON.parse(ev.data).status); } catch (e) {}
    });
    es.addEventListener("gate", function (ev) {
      try { self._renderGate(JSON.parse(ev.data).prompt); } catch (e) {}
    });
    es.addEventListener("done", function (ev) {
      try { self._setStatus(JSON.parse(ev.data).status); } catch (e) {}
      es.close();
      self._es = null;
      self._onExit();
    });
    es.addEventListener("heartbeat", function () { /* keep-alive; stream may end after */ });
    es.onerror = function () {
      // The stream ended (bounded/heartbeat design). Re-open if the session is
      // still live; otherwise fall to the exit path.
      es.close();
      self._es = null;
      var terminal = ["done", "cancelled", "interrupted", "failed"];
      if (!self.closed && terminal.indexOf(self.status) < 0) {
        setTimeout(function () { self.start(); }, 400);
      } else {
        self._onExit();
      }
    };
  };

  // On exit: ask the server what the session produced and offer confirm-adopt.
  AnchorTerm.prototype._onExit = function () {
    if (this.closed) return;
    this.closed = true;
    if (this._input) { this._input.disabled = true; this._input.setAttribute("placeholder", "session ended"); }
    var self = this;
    Promise.resolve(this.postJson("/api/rnd/term_discover", { session: this.sessionId }))
      .then(function (data) {
        if (data && data.ok && data.proposal && data.proposal.adoptable) {
          self._renderAdopt(data.proposal);
        } else {
          self.writeLine("[session ended — no produced files to adopt]", "system");
        }
      })
      .catch(function (e) { self.writeLine("[discover error] " + e.message, "error"); });
  };

  AnchorTerm.prototype._renderAdopt = function (proposal) {
    var panel = el("div", "aterm-adopt");
    var h = el("h5"); h.textContent = "Session produced " + proposal.produced.length + " file(s) — adopt as a " +
      (proposal.lane || "") + " session?";
    panel.appendChild(h);
    var ul = el("ul");
    proposal.produced.forEach(function (p) {
      var li = el("li"); li.textContent = p.rel + (p.kind ? "  (" + p.kind + ")" : ""); ul.appendChild(li);
    });
    panel.appendChild(ul);
    var row = el("div", "row");
    var yes = el("button", "accent"); yes.textContent = "Adopt as session";
    var no = el("button"); no.textContent = "Dismiss";
    var self = this;
    yes.addEventListener("click", function () {
      Promise.resolve(self.postJson("/api/rnd/term_adopt", { session: self.sessionId }))
        .then(function (data) {
          if (data && data.ok) {
            panel.innerHTML = "<h5>Adopted as a session ✓</h5>";
            self._adopted = true;       // do not reap an adopted session on unload
            self.onAdopted(data);
          } else {
            self.writeLine("[adopt refused: " + ((data && data.error) || "unknown") + "]", "error");
          }
        })
        .catch(function (e) { self.writeLine("[adopt error] " + e.message, "error"); });
    });
    no.addEventListener("click", function () { panel.parentNode && panel.parentNode.removeChild(panel); });
    row.appendChild(yes); row.appendChild(no);
    panel.appendChild(row);
    this._chrome.appendChild(panel);
  };

  // Best-effort cancel of the live session's persistent process. Used on tab
  // close / dispose when the session is still live and was NOT yet adopted — a
  // persistent stream-json REPL otherwise waits for input forever (a leak). The
  // cancel POST carries the token in the JSON BODY (the server's auth middleware
  // accepts a "token" field) because sendBeacon / unload requests can't set the
  // X-Anchor-Token header. Prefers navigator.sendBeacon (survives unload), falls
  // back to a keepalive fetch, then a sync XHR — whichever lands.
  AnchorTerm.prototype._reapCancel = function () {
    if (this._reaped) return;
    this._reaped = true;
    var sid = this.sessionId;
    if (!sid) return;
    var token = "";
    try { token = localStorage.getItem("anchor_token") || ""; } catch (e) {}
    var payload = { job_id: sid };
    if (token) payload.token = token;
    var bodyStr = JSON.stringify(payload);
    var url = "/api/rnd/cancel_job";
    try {
      if (navigator && typeof navigator.sendBeacon === "function") {
        var blob = new Blob([bodyStr], { type: "application/json" });
        if (navigator.sendBeacon(url, blob)) return;
      }
    } catch (e) {}
    try {
      if (typeof fetch === "function") {
        fetch(url, { method: "POST", body: bodyStr, keepalive: true,
                     headers: { "Content-Type": "application/json" } });
        return;
      }
    } catch (e) {}
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", url, false);            // sync fallback so it lands on unload
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(bodyStr);
    } catch (e) {}
  };

  AnchorTerm.prototype.dispose = function () {
    // If the session is still live and was not adopted/finished, fire a
    // best-effort cancel so the abandoned persistent process is reaped.
    var live = !this.closed &&
      ["done", "cancelled", "interrupted", "failed"].indexOf(this.status) < 0;
    this.closed = true;
    if (this._beforeUnload) {
      try { window.removeEventListener("beforeunload", this._beforeUnload); } catch (e) {}
      this._beforeUnload = null;
    }
    if (live && !this._adopted) this._reapCancel();
    if (this._es) { try { this._es.close(); } catch (e) {} this._es = null; }
    if (this._term) { try { this._term.dispose(); } catch (e) {} this._term = null; }
  };

  // Public factory. The body now drives a REAL xterm.js Terminal, but the API
  // (window.AnchorTerm.mount) and the dispose()/unload-reap behavior are the SAME
  // so callers (anchor_gui project window) and tests need no integration change.
  window.AnchorTerm = {
    mount: function (opts) {
      var t = new AnchorTerm(opts);
      // Reap the abandoned persistent process if the user closes the tab while
      // the session is still live and unadopted (best-effort cancel on unload).
      t._beforeUnload = function () {
        var live = !t.closed &&
          ["done", "cancelled", "interrupted", "failed"].indexOf(t.status) < 0;
        if (live && !t._adopted) t._reapCancel();
      };
      try { window.addEventListener("beforeunload", t._beforeUnload); } catch (e) {}
      t.start();
      return t;
    }
  };
})();
