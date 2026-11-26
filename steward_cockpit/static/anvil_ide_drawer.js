/* Locked Mockup #3 3-Column Scientific IDE Debugger (`25%/45%/30%`), Code Split
 * & 4-Stage Smart Variable Funnel (`anvil_ide_drawer.js`, `<= 500` lines).
 * Enforces strict receipt-gating on `.full-ghost-note`: runtime values render ONLY
 * when a signed `has_trace === true` receipt is present.
 */
(function (root) {
  "use strict";

  function esc(val) {
    return root.AnvilV5Client ? root.AnvilV5Client.escHtml(val) : String(val == null ? "" : val).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function stripDollars(txt) {
    return String(txt == null ? "" : txt).replace(/\$/g, "");
  }

  function basename(p) {
    var s = String(p || "");
    var i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
    return i >= 0 ? s.slice(i + 1) : s;
  }

  function bpKey(file, line) {
    return String(file || "") + ":" + String(line || 1);
  }

  function tokenizeCodeLine(lineText, watchables, pinnedSet) {
    if (!lineText) return "";
    var trimmed = String(lineText).trim();
    if (/^(?:#|\/\/|"""|'''|\*\s)/.test(trimmed)) return esc(lineText);
    var wSet = new Set(watchables || []);
    return String(lineText).split(/(\b[A-Za-z_][A-Za-z0-9_]*\b)/g).map(function (tok) {
      if (wSet.has(tok)) {
        var pinned = Boolean(pinnedSet && pinnedSet.has(tok));
        return '<span role="button" tabindex="0" class="code-ident-tok' + (pinned ? " pinned" : "") + '" data-var="' + esc(tok) + '">' + (pinned ? "★ " : "") + esc(tok) + "</span>";
      }
      return esc(tok);
    }).join("");
  }

  function renderFullIdePane(ctx) {
    var state = ctx.state;
    var pane = document.getElementById("full-ide-pane");
    if (!pane) return;
    if (!state.ideOpen || !(state.active || state.unknownState) || state.launcherOpen) {
      pane.hidden = true;
      return;
    }
    pane.hidden = false;
    pane.classList.toggle("theme-light", state.ideTheme !== "dark");
    pane.classList.toggle("theme-dark", state.ideTheme === "dark");
    var themeBtn = document.getElementById("btn-ide-theme");
    if (themeBtn) themeBtn.textContent = state.ideTheme === "dark" ? "☾ Studio Dark" : "☀ Paper Light";

    var filesMap = (state.bundle && state.bundle.files_source_map) || {};
    var fileKeys = Object.keys(filesMap);
    var tabsEl = document.getElementById("full-ide-tabs");
    var scrollEl = document.getElementById("full-ide-code-scroll");
    var execBadge = document.getElementById("full-ide-exec-badge");
    var bpBadge = document.getElementById("full-ide-bp-badge");

    if (state.unknownState) {
      tabsEl.innerHTML = "";
      execBadge.textContent = "UNKNOWN";
      bpBadge.textContent = "Breakpoints: UNKNOWN · Watches: UNKNOWN";
      scrollEl.innerHTML = '<div style="padding:14px;font-weight:700;">Backing store unreadable (UNKNOWN state)</div>';
      return;
    }
    if (fileKeys.length === 0) {
      tabsEl.innerHTML = "";
      execBadge.textContent = "EMPTY";
      bpBadge.textContent = "● 0 breakpoints · ★ " + state.pinnedWatches.size + " pinned";
      scrollEl.innerHTML = '<div style="padding:14px;">No source files present in locked scope.</div>';
      return;
    }

    if (!filesMap[state.activeFile]) state.activeFile = fileKeys[0];
    var fObj = filesMap[state.activeFile];
    if (fObj && fObj.needs_lazy_fetch) ctx.ensureActiveFileSourceLoaded(fObj.file);
    var activeLn = state.activeLine || fObj.exec_line || 1;
    var hasTrace = Boolean(state.bundle && state.bundle.has_trace);

    execBadge.textContent = fObj.file + " · ▶ L" + activeLn + (hasTrace ? " (TRACED)" : " (STATIC)");
    bpBadge.textContent = "● " + state.breakpoints.size + " breakpoints · ★ " + state.pinnedWatches.size + " pinned";

    var sortedKeys = fileKeys.slice().sort(function (a, b) {
      var aInit = /(?:^|\/)__init__\.py$/.test(a) ? 1 : 0;
      var bInit = /(?:^|\/)__init__\.py$/.test(b) ? 1 : 0;
      return aInit !== bInit ? (aInit - bInit) : a.localeCompare(b);
    });
    var baseCounts = {};
    sortedKeys.forEach(function (fk) { var bn = basename(fk); baseCounts[bn] = (baseCounts[bn] || 0) + 1; });

    tabsEl.innerHTML = sortedKeys.map(function (fk) {
      var bn = basename(fk);
      var lbl = bn;
      if (baseCounts[bn] > 1) {
        var segs = String(fk).replace(/\\/g, "/").split("/").filter(Boolean);
        lbl = segs.length >= 2 ? (segs[segs.length - 2] + "/" + bn) : fk;
      }
      return '<button type="button" class="full-ide-tab' + (fk === fObj.file ? " active" : "") + '" data-ide-tab="' + esc(fk) + '">' + esc(lbl) + "</button>";
    }).join("");

    tabsEl.querySelectorAll("[data-ide-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var fk = btn.getAttribute("data-ide-tab") || "";
        state.activeFile = fk;
        var target = filesMap[fk];
        if (target) {
          state.activeStageId = target.stage_id || state.activeStageId;
          state.activeLine = target.exec_line || 1;
        }
        ctx.persistSessionState();
        ctx.renderAll();
      });
    });

    var ghosts = hasTrace ? (fObj.ghost_values || {}) : {};
    var linesArr = fObj.lines || [];
    if (linesArr.length === 0) {
      scrollEl.innerHTML = '<div style="padding:14px;">Loading source lines for ' + esc(fObj.file) + "…</div>";
      return;
    }

    scrollEl.innerHTML = linesArr.map(function (pair) {
      var ln = pair[0];
      var txt = pair[1];
      var key = bpKey(fObj.file, ln);
      var bpOn = state.breakpoints.has(key);
      var isExec = ln === activeLn;
      var gEntry = ghosts[String(ln)];
      var isFaultLn = Boolean(gEntry && gEntry.fault);
      var cls = "full-code-line" + (isExec ? (isFaultLn ? " exec-fault" : " exec-clean") : (isFaultLn ? " exec-fault" : ""));
      return '<div class="' + cls + '" data-code-ln="' + ln + '">' +
        '<button type="button" class="full-bp-btn' + (bpOn ? " bp-on" : "") + '" data-bp-key="' + esc(key) + '" title="Toggle breakpoint ' + esc(key) + '">●</button>' +
        '<span class="full-exec-arrow">' + (isExec ? "▶" : "") + "</span>" +
        '<span class="full-ln-num">' + ln + "</span>" +
        '<div class="full-code-txt">' + tokenizeCodeLine(txt, fObj.watchable_tokens, state.pinnedWatches) +
          (gEntry ? '<span class="full-ghost-note' + (gEntry.fault ? " fault" : "") + '">' + esc(stripDollars(gEntry.text)) + "</span>" : "") +
        "</div></div>";
    }).join("");

    scrollEl.querySelectorAll("[data-bp-key]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var k = btn.getAttribute("data-bp-key") || "";
        if (state.breakpoints.has(k)) state.breakpoints.delete(k);
        else state.breakpoints.add(k);
        ctx.persistSessionState();
        renderFullIdePane(ctx);
      });
    });
    scrollEl.querySelectorAll(".code-ident-tok").forEach(function (tokEl) {
      tokEl.addEventListener("click", function () {
        var v = tokEl.getAttribute("data-var") || "";
        if (!v) return;
        if (state.pinnedWatches.has(v)) state.pinnedWatches.delete(v);
        else state.pinnedWatches.add(v);
        ctx.persistSessionState();
        renderFullIdePane(ctx);
        ctx.renderInspector();
      });
    });
  }

  function renderSmartFunnelView(body, ctx) {
    var state = ctx.state;
    var FIVE_SCOPES = ctx.FIVE_SCOPES;
    if (state.unknownState) {
      body.innerHTML = '<div class="funnel-grid">' +
        '<div class="funnel-stage-btn"><div class="funnel-lbl">1. All State</div><div id="funnel-count-all" class="funnel-num">UNKNOWN</div></div>' +
        '<div class="funnel-stage-btn"><div class="funnel-lbl">2. Stage Scope</div><div id="funnel-count-stage" class="funnel-num">UNKNOWN</div></div>' +
        '<div class="funnel-stage-btn"><div class="funnel-lbl">3. Delta Mutated</div><div id="funnel-count-delta" class="funnel-num">UNKNOWN</div></div>' +
        '<div class="funnel-stage-btn"><div class="funnel-lbl">4. Anomalies &amp; Pins</div><div id="funnel-count-anomalies" class="funnel-num">UNKNOWN</div></div></div>' +
        '<div class="card-block fault-card">Session/trace store unreadable (unknown state, not empty).</div>';
      return;
    }

    var vc = (state.bundle && state.bundle.variable_catalog) || { scopes: {} };
    var scopesObj = vc.scopes || {};
    var hasTrace = Boolean(state.bundle && state.bundle.has_trace);
    var allItems = [];
    var seenNames = new Set();
    FIVE_SCOPES.forEach(function (sc) {
      if (!state.activeScopes.has(sc)) return;
      (scopesObj[sc] || []).forEach(function (it) {
        seenNames.add(it.name);
        allItems.push(Object.assign({}, it, { pinned: state.pinnedWatches.has(it.name) || Boolean(it.pinned) }));
      });
    });
    state.pinnedWatches.forEach(function (pw) {
      if (!seenNames.has(pw) && state.activeScopes.has("function_locals")) {
        allItems.push({
          key: "pin:" + pw, scope: "function_locals", stage_id: state.activeStageId,
          file: state.activeFile, line: state.activeLine || 1,
          file_line: (state.activeFile || "active") + ":" + (state.activeLine || 1),
          name: pw, type_shape: "pinned_watch",
          value: hasTrace ? "Pinned runtime watch" : "unmeasured (run consented trace for live value)",
          changed: hasTrace, anomaly: false, pinned: true
        });
      }
    });

    var stageItems = allItems.filter(function (it) { return it.stage_id === state.activeStageId || it.pinned || it.anomaly; });
    var deltaItems = stageItems.filter(function (it) { return Boolean(it.changed) || it.pinned || it.anomaly; });
    var anomItems = deltaItems.filter(function (it) { return Boolean(it.anomaly) || it.pinned; });
    var visible = state.funnelStage === "stage" ? stageItems : (state.funnelStage === "delta" ? deltaItems : (state.funnelStage === "anomalies" ? anomItems : allItems));
    var q = state.funnelSearch.trim().toLowerCase();
    if (q) {
      visible = visible.filter(function (it) { return (it.name + " " + it.scope + " " + it.type_shape + " " + it.value + " " + it.file_line).toLowerCase().indexOf(q) >= 0; });
    }

    body.innerHTML =
      '<div class="funnel-grid" role="group" aria-label="4-Stage Smart Variable Funnel">' +
        '<button type="button" class="funnel-stage-btn' + (state.funnelStage === "all" ? " active" : "") + '" data-funnel-stage="all"><div class="funnel-lbl">1. All State</div><div id="funnel-count-all" class="funnel-num">' + allItems.length + "</div></button>" +
        '<button type="button" class="funnel-stage-btn' + (state.funnelStage === "stage" ? " active" : "") + '" data-funnel-stage="stage"><div class="funnel-lbl">2. Stage Scope</div><div id="funnel-count-stage" class="funnel-num">' + stageItems.length + "</div></button>" +
        '<button type="button" class="funnel-stage-btn' + (state.funnelStage === "delta" ? " active" : "") + '" data-funnel-stage="delta"><div class="funnel-lbl">3. Delta Mutated</div><div id="funnel-count-delta" class="funnel-num">' + deltaItems.length + "</div></button>" +
        '<button type="button" class="funnel-stage-btn' + (state.funnelStage === "anomalies" ? " active" : "") + '" data-funnel-stage="anomalies"><div class="funnel-lbl">4. Anomalies &amp; Pins</div><div id="funnel-count-anomalies" class="funnel-num">' + anomItems.length + "</div></button>" +
      "</div>" +
      '<div class="scope-pills" role="group" aria-label="5-Scope Variable Filter">' + FIVE_SCOPES.map(function (sc) {
        return '<button type="button" class="scope-pill' + (state.activeScopes.has(sc) ? " active" : "") + '" data-scope="' + esc(sc) + '">' + esc(sc) + "</button>";
      }).join("") + "</div>" +
      '<div><input id="funnel-search-input" type="search" class="chat-input" style="width:100%;" value="' + esc(state.funnelSearch) + '" placeholder="Filter variables, types, shapes, or files..." aria-label="Search Smart Variable Funnel"/></div>' +
      (visible.length > 0 ? visible.slice(0, 50).map(function (it) {
        return '<div class="var-row' + (it.anomaly ? " anom" : "") + '">' +
          '<div><strong style="font-family:var(--font-mono);">' + (it.anomaly ? "🚨 " : "") + esc(it.name) + '</strong> <span class="prov-tag">' + esc(it.scope) + "</span> " +
          '<span style="color:var(--ink-soft);">' + esc(stripDollars(it.value || "unmeasured")) + "</span></div>" +
          '<div class="selector-group">' +
            (it.file ? '<button type="button" class="small-btn" data-jump-file="' + esc(it.file) + '" data-jump-line="' + Number(it.line || 1) + '">' + esc(basename(it.file) + ":L" + (it.line || 1)) + "</button>" : "") +
            '<button type="button" class="small-btn" data-pin-var="' + esc(it.name) + '">' + (it.pinned ? "★ Unpin" : "☆ Pin") + "</button>" +
          "</div></div>";
      }).join("") : '<div class="card-block" style="color:var(--ink-soft);">0 variables match active funnel filter.</div>');

    body.querySelectorAll("[data-funnel-stage]").forEach(function (b) {
      b.addEventListener("click", function () { state.funnelStage = b.getAttribute("data-funnel-stage") || "all"; ctx.renderInspector(); });
    });
    body.querySelectorAll("[data-scope]").forEach(function (b) {
      b.addEventListener("click", function () {
        var sc = b.getAttribute("data-scope");
        if (state.activeScopes.has(sc) && state.activeScopes.size > 1) state.activeScopes.delete(sc);
        else state.activeScopes.add(sc);
        ctx.renderInspector();
      });
    });
    var sInp = document.getElementById("funnel-search-input");
    if (sInp) sInp.addEventListener("input", function () { state.funnelSearch = sInp.value; renderSmartFunnelView(body, ctx); });
    ctx.bindPinAndJumpButtons(body);
  }

  function renderValidatorTab(body, ctx) {
    var state = ctx.state;
    var v5 = root.AnvilV5Client;
    var xf = (state.semanticComprehension && state.semanticComprehension.cross_family_receipt) || null;
    var xv = (state.bundle && state.bundle.xval_receipt) || {};
    var dispState = (xf && xf.display_state) || (xv.cross_family_attested ? "ATTESTED" : "NO_RECEIPT");
    var bdg = v5 ? v5.resolveDisplayStateBadge(dispState) : { cls: "badge-neutral-slate", label: dispState };
    body.innerHTML = '<div class="card-block active-card"><div class="deck-row"><strong>⇄ 2-Seat Cross-Family Validator Receipt</strong>' +
      '<div class="selector-group"><span class="' + esc(bdg.cls) + '" data-display-state="' + esc(dispState) + '">' + esc(bdg.label) + '</span>' +
      '<button type="button" id="btnRunXvalAudit" class="consent-run-btn">✓ Run Cross-Family Audit</button></div></div>' +
      (xf && xf.primary_model_served
        ? '<div style="margin-top:6px;font-size:12px;">Primary Seat: <code>' + esc(xf.primary_vendor + ":" + xf.primary_model_served) + '</code> · Adversarial Seat: <code>' + esc((xf.review_vendor || "pending") + ":" + (xf.review_model_served || "not_run")) + "</code></div>" +
          (xf.notes ? '<div style="margin-top:4px;color:var(--ink-soft);">' + esc(xf.notes) + "</div>" : "")
        : '<div style="margin-top:6px;color:var(--ink-soft);">No cross-family receipt recorded yet (`display_state: ' + esc(dispState) + '`). Click Run Cross-Family Audit or Run Gandalf + Ramanujan Pass.</div>') +
      "</div>";
    var runBtn = document.getElementById("btnRunXvalAudit");
    if (runBtn) runBtn.addEventListener("click", function () { ctx.onRunXval(runBtn); });
  }

  function renderCopilotPane(ctx) {
    var state = ctx.state;
    if (!(state.active || state.unknownState) || state.launcherOpen) return;
    var shell = document.getElementById("copilot-shell");
    if (shell) shell.classList.toggle("chat-minimized", Boolean(state.copilotMinimized));
    var toggleBtn = document.getElementById("btnToggleDialogueSurface");
    var liveWrap = document.getElementById("cockpitLiveDialogueWrap");
    var liveFrame = document.getElementById("cockpitLiveDialogueFrame");
    var box = document.getElementById("chat-messages");
    var comp = document.getElementById("copilot-composer");
    var chips = document.getElementById("copilot-starter-chips");
    if (toggleBtn) { toggleBtn.hidden = !ctx.pid; toggleBtn.textContent = state.useLiveCockpitTile ? "📋 Anvil Co-Pilot" : "💬 Live Cockpit Tile"; }
    if (ctx.pid && state.useLiveCockpitTile && liveWrap && liveFrame) {
      var url = ctx.buildCockpitTileDialogueUrl();
      if (url && liveFrame.getAttribute("src") !== url) liveFrame.setAttribute("src", url);
      liveWrap.hidden = false; box.hidden = true; comp.hidden = true; chips.hidden = true;
      return;
    }
    if (liveWrap) liveWrap.hidden = true;
    box.hidden = state.copilotMinimized; comp.hidden = state.copilotMinimized; chips.hidden = state.copilotMinimized;
    if (state.copilotMinimized) return;
    if (state.dialogueTurns.length === 0) {
      box.innerHTML = '<div class="chat-msg assistant">[Steward Co-Pilot] Grounded on <strong>' + esc(ctx.activeStageId || "scope") + "</strong>. Ask about causal triptychs, pure-core refactor targets (N1..Nk), or manuscript MathML equations.</div>";
      return;
    }
    box.innerHTML = state.dialogueTurns.map(function (t) { return '<div class="chat-msg ' + (t.role === "user" ? "user" : "assistant") + '">' + esc(stripDollars(t.text || "")) + "</div>"; }).join("");
    box.scrollTop = box.scrollHeight;
  }

  root.AnvilIdeDrawer = {
    bpKey: bpKey,
    tokenizeCodeLine: tokenizeCodeLine,
    renderFullIdePane: renderFullIdePane,
    renderSmartFunnelView: renderSmartFunnelView,
    renderValidatorTab: renderValidatorTab,
    renderCopilotPane: renderCopilotPane
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
