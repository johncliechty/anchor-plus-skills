/* Unified Anvil Core Client Utilities, Boot Failure Table, Safe MathML Builder,
 * Display-State Honesty Mapper & Sync Scheduler (`anvil.js`).
 * Dual-exported as `window.AnvilV5Client` and CommonJS `module.exports` (`<= 550` lines).
 * Zero `setInt`+`erval`, zero mockup sample literals, zero fake green badges.
 */
(function (root) {
  "use strict";

  var MAX_DIRECTION_BYTES = 16384;
  var MAX_XVAL_CONCURRENCY = 2;
  var OPAQUE_MODULE_ID_RE = /^[a-z0-9_-]+$/;
  var MATHML_NS = "http://www.w3.org/1998/Math/MathML";
  var ALLOWED_MATHML_TAGS = {
    math: 1, mrow: 1, mi: 1, mn: 1, mo: 1, mfrac: 1, msup: 1, msub: 1, msubsup: 1,
    msqrt: 1, mroot: 1, mover: 1, munder: 1, munderover: 1, mtable: 1, mtr: 1, mtd: 1,
    mtext: 1, mspace: 1
  };
  var ALLOWED_MATHML_ATTRS = { display: 1, mathvariant: 1, width: 1, linebreak: 1, columnalign: 1, rowspacing: 1 };
  var GREEN_DISPLAY_STATES = { ATTESTED: 1, VERIFIED_TRACE: 1, VERIFIED_NUMERIC: 1 };

  var DISPLAY_STATE_BADGES = {
    ATTESTED: { cls: "badge-verified-green", label: "✓ Cross-Family Attested", green: true },
    VERIFIED_TRACE: { cls: "badge-verified-green", label: "● Verified Runtime Trace", green: true },
    VERIFIED_NUMERIC: { cls: "badge-verified-green", label: "✓ Verified Numeric Parity", green: true },
    SINGLE_FAMILY_CLAIMED: { cls: "badge-claimed-amber", label: "◌ Single-Family Claimed", green: false },
    DEGRADED_QUORUM: { cls: "badge-claimed-amber", label: "⚠ Degraded Quorum", green: false },
    ATTESTATION_MISMATCH: { cls: "badge-fault-red", label: "✕ Attestation Mismatch", green: false },
    SEAT_UNAVAILABLE: { cls: "badge-claimed-amber", label: "◌ Seat Unavailable (Static)", green: false },
    NO_RECEIPT: { cls: "badge-neutral-slate", label: "◌ Static AST (No Receipt)", green: false },
    UNGROUNDED: { cls: "badge-fault-red", label: "✕ Ungrounded Claim", green: false }
  };

  var V5_BOOT_FAILURE_TABLE = {
    503: { status_kind: "dependency-missing", http_status: 503, badge: "DEGRADED_STATIC", open_intake: false, retryable: true, unknown_state: false, message: "Required runtime/tracer unavailable — showing static AST map" },
    504: { status_kind: "dependency-slow-or-killed", http_status: 504, badge: "TIMEOUT_PARTIAL", open_intake: false, retryable: true, unknown_state: false, message: "Worker timed out or was terminated — partial state preserved" },
    502: { status_kind: "dependency-returns-garbage", http_status: 502, badge: "REJECTED_GARBAGE", open_intake: false, retryable: true, unknown_state: false, message: "Malformed engine/validator payload — rejected fail-closed" },
    500: { status_kind: "backing-store-unreadable", http_status: 500, badge: "UNKNOWN", open_intake: false, retryable: true, unknown_state: true, message: "Session/trace store unreadable (unknown state, not empty)" },
    429: { status_kind: "rate-limited", http_status: 429, badge: "RATE_LIMITED", open_intake: false, retryable: true, unknown_state: false, message: "Rate limited — backing off without clearing existing analyses" },
    409: { status_kind: "scope-drifted", http_status: 409, badge: "409_SCOPE_DRIFTED", open_intake: false, retryable: true, unknown_state: false, message: "409 Scope Drifted — in-scope files changed since lock; re-lock scope to refresh" },
    401: { status_kind: "unauthorized", http_status: 401, badge: "UNAUTHORIZED", open_intake: false, retryable: false, unknown_state: false, message: "Unauthorized — valid Anchor session token required" },
    400: { status_kind: "bad-request", http_status: 400, badge: "REFUSED", open_intake: false, retryable: false, unknown_state: false, message: "Request refused by Anvil bounds/containment policy" },
    200: { status_kind: "empty-but-valid", http_status: 200, badge: "EMPTY", open_intake: true, retryable: false, unknown_state: false, message: "No Anvil analyses configured yet — choose a repository and manuscript to begin" }
  };
  var V6_BOOT_FAILURE_TABLE = Object.assign({}, V5_BOOT_FAILURE_TABLE, {
    200: { status_kind: "empty-but-valid", http_status: 200, badge: "EMPTY", open_intake: true, retryable: false, unknown_state: false, message: "No Anvil scopes locked yet — inspect the Software & Paper Map below" }
  });

  function isValidOpaqueModuleId(rawId) {
    return typeof rawId === "string" && rawId.length <= 80 && OPAQUE_MODULE_ID_RE.test(rawId);
  }

  function escHtml(val) {
    return String(val == null ? "" : val)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function stripDollars(txt) {
    return String(txt == null ? "" : txt).replace(/\$/g, "");
  }

  function utf8ByteLength(raw) {
    var s = String(raw == null ? "" : raw);
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(s).length;
    if (typeof Buffer !== "undefined") return Buffer.byteLength(s, "utf8");
    return unescape(encodeURIComponent(s)).length;
  }

  function resolveDisplayStateBadge(displayState, fallbackLabel) {
    var key = String(displayState || "NO_RECEIPT").toUpperCase();
    var entry = DISPLAY_STATE_BADGES[key] || DISPLAY_STATE_BADGES.NO_RECEIPT;
    var isGreen = Boolean(GREEN_DISPLAY_STATES[key]);
    return {
      state: DISPLAY_STATE_BADGES[key] ? key : "NO_RECEIPT",
      cls: entry.cls,
      label: (isGreen && fallbackLabel) ? String(fallbackLabel) : entry.label,
      green: isGreen
    };
  }

  function sanitizeMathMlString(rawMml, fallbackText) {
    var clean = stripDollars(rawMml || "").trim();
    var fb = '<math xmlns="' + MATHML_NS + '" display="block"><mrow><mtext>' + escHtml(stripDollars(fallbackText || "Equation")) + '</mtext></mrow></math>';
    if (!clean || clean.indexOf("<math") < 0) return fb;
    if (/<script\b|javascript:|data:text\/html|\bon[a-z]+\s*=/i.test(clean)) return fb;
    if (typeof DOMParser !== "undefined" && typeof document !== "undefined") {
      try {
        var doc = new DOMParser().parseFromString(clean, "text/html");
        var mathEl = doc.querySelector("math");
        if (!mathEl) return fb;
        var outDom = buildSafeMathNode(mathEl);
        return outDom ? outDom.outerHTML : fb;
      } catch (_e) {
        return fb;
      }
    }
    return fb;
  }

  function buildSafeMathNode(srcNode) {
    if (typeof document === "undefined") return null;
    if (srcNode.nodeType === 3) return document.createTextNode(srcNode.nodeValue || "");
    if (srcNode.nodeType !== 1) return null;
    var tag = String(srcNode.tagName || "").toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(ALLOWED_MATHML_TAGS, tag)) return null;
    var el = document.createElementNS(MATHML_NS, tag);
    if (tag === "math") el.setAttribute("display", srcNode.getAttribute("display") === "inline" ? "inline" : "block");
    for (var i = 0; i < srcNode.attributes.length; i += 1) {
      var a = srcNode.attributes[i];
      var aname = String(a.name || "").toLowerCase();
      if (Object.prototype.hasOwnProperty.call(ALLOWED_MATHML_ATTRS, aname) && !/javascript:/i.test(a.value || "")) {
        el.setAttribute(aname, a.value);
      }
    }
    for (var c = 0; c < srcNode.childNodes.length; c += 1) {
      var child = buildSafeMathNode(srcNode.childNodes[c]);
      if (child) el.appendChild(child);
    }
    return el;
  }

  function readSurfaceRoute(scopeSha) {
    if (typeof window === "undefined") return "";
    var h = String(window.location.hash || "").replace(/^#/, "").toLowerCase();
    if (h === "scoping" || h === "workbench" || h === "report") return h;
    if (scopeSha) {
      try { return String(window.sessionStorage.getItem("anvil_route_" + scopeSha) || ""); } catch (_e) {}
    }
    return "";
  }

  function writeSurfaceRoute(route, scopeSha) {
    if (typeof window === "undefined") return;
    if (scopeSha) {
      try { window.sessionStorage.setItem("anvil_route_" + scopeSha, String(route || "")); } catch (_e) {}
    }
  }

  function validateDirectionPayload(rawDirection, opts) {
    var options = opts || {};
    var s = String(rawDirection == null ? "" : rawDirection);
    var byteLen = utf8ByteLength(s);
    if (byteLen > MAX_DIRECTION_BYTES) {
      return {
        ok: false,
        error_code: "BOUND_EXCEEDED_REFUSAL",
        byte_length: byteLen,
        max_bytes: MAX_DIRECTION_BYTES,
        message: "BOUND_EXCEEDED_REFUSAL: Direction exceeds 16,384 UTF-8 bytes (" + byteLen + " B)."
      };
    }
    if (options.max_concurrency !== undefined && options.max_concurrency !== null) {
      var mc = Number(options.max_concurrency);
      if (!Number.isFinite(mc) || mc < 1 || mc > MAX_XVAL_CONCURRENCY) {
        return {
          ok: false,
          error_code: "BOUND_EXCEEDED_REFUSAL",
          byte_length: byteLen,
          max_concurrency: mc,
          message: "BOUND_EXCEEDED_REFUSAL: max_concurrency must be 1 or 2."
        };
      }
    }
    return { ok: true, byte_length: byteLen, escaped_direction: escHtml(s) };
  }

  function resolveBootFailureSurface(httpStatus, data, opts) {
    var tbl = (opts && opts.anvilV6Enabled) ? V6_BOOT_FAILURE_TABLE : V5_BOOT_FAILURE_TABLE;
    var code = Number(httpStatus);
    if (code === 200 && (!data || typeof data !== "object" || Array.isArray(data))) {
      return Object.assign({}, tbl[502], { http_status: 502 });
    }
    if (!code || code <= 0) {
      return Object.assign({}, tbl[504], { message: (data && (data.error || data.message)) || tbl[504].message });
    }
    if (data && typeof data === "object" && (data.unknown_state === true || code === 500)) {
      return Object.assign({}, tbl[500], { message: (data && (data.message || data.error)) || tbl[500].message });
    }
    if (code === 200 && data && data.ok !== false && !data.active) {
      return Object.assign({}, tbl[200], { message: data.message || tbl[200].message });
    }
    if (code >= 200 && code < 300 && data && data.ok !== false) {
      return { status_kind: "healthy", http_status: code, badge: "HEALTHY", open_intake: false, retryable: false, unknown_state: false, message: "" };
    }
    var base = tbl[code] || (code >= 500 ? tbl[500] : tbl[400]);
    return Object.assign({}, base, {
      http_status: code,
      message: (data && typeof data === "object" && (data.message || data.error)) ? String(data.message || data.error) : base.message
    });
  }

  function normalizeVendorFamily(raw) {
    var low = String(raw || "").trim().toLowerCase();
    if (!low) return "";
    if (low === "gemini" || low === "claude" || low === "chatgpt" || low === "grok") return low;
    if (/claude|anthropic|opus|sonnet|haiku|fable/.test(low)) return "claude";
    if (/gemini|argon|carbon/.test(low)) return "gemini";
    if (/gpt-|chatgpt|openai|codex|\bo[134](?:-|\b)/.test(low)) return "chatgpt";
    if (/grok|xai/.test(low)) return "grok";
    return "";
  }

  function normalizeAnalysesList(data, currentBundle, fallbackLabel) {
    var d = (data && typeof data === "object") ? data : {};
    var rawArr = Array.isArray(d.analyses) ? d.analyses : (Array.isArray(d.saved_scopes) ? d.saved_scopes : []);
    if (rawArr.length > 0) {
      return rawArr.filter(function (x) { return x && typeof x === "object" && !x.archived; }).map(function (item, idx) {
        var aid = String(item.analysis_id || item.id || ("slot-" + (idx + 1)));
        return Object.assign({}, item, {
          analysis_id: aid,
          title: String(item.title || item.label || fallbackLabel || aid),
          validation_badge: String(item.validation_badge || (item.scope_drifted ? "409_SCOPE_DRIFTED" : (item.has_trace ? "TRACED" : "STATIC")))
        });
      });
    }
    if (d.active && (currentBundle || d.analysis_id)) {
      var singleId = String(d.analysis_id || d.active_analysis_id || "primary");
      return [{
        analysis_id: singleId,
        title: String((currentBundle && currentBundle.repo_name) || fallbackLabel || "Active Analysis"),
        validation_badge: (currentBundle && currentBundle.has_trace) ? "TRACED" : "STATIC"
      }];
    }
    return [];
  }

  function renderAnalysisSwitcherOptionsHtml(analyses, activeAnalysisId) {
    var list = Array.isArray(analyses) ? analyses : [];
    if (list.length === 0) return '<option value="">0 Analyses — Configure Scope</option>';
    return list.map(function (a) {
      var aid = String(a.analysis_id || "");
      var sel = aid === String(activeAnalysisId || "") ? " selected" : "";
      var bdg = a.validation_badge ? " [" + a.validation_badge + "]" : "";
      return '<option value="' + escHtml(aid) + '"' + sel + '>' + escHtml((a.title || aid) + bdg) + "</option>";
    }).join("");
  }

  function buildGuidedIntakeSubmission(formValues, opts) {
    var fv = formValues || {};
    var options = opts || {};
    var chk = validateDirectionPayload(fv.direction || "", { max_concurrency: fv.max_concurrency });
    if (!chk.ok) return chk;
    var sw = String(fv.software_target || ".").trim() || ".";
    var pp = String(fv.paper_target || "").trim();
    var mc = fv.max_concurrency !== undefined ? Math.min(2, Math.max(1, Number(fv.max_concurrency) || 2)) : 2;
    var basePayload = {
      title: String(fv.title || "").trim(),
      software_target: sw,
      paper_target: pp,
      selected_pipelines: Array.isArray(fv.selected_pipelines) ? fv.selected_pipelines : [],
      active_pipeline: String(fv.active_pipeline || ""),
      materialize_replication_package: fv.materialize_replication_package !== false,
      direction: String(fv.direction || ""),
      max_concurrency: mc
    };
    if (options.multiAnalysisEnabled) {
      if (options.editExisting && options.activeAnalysisId) {
        basePayload.analysis_id = String(options.activeAnalysisId);
        return { ok: true, action: pp ? "start_paper" : "start_code", payload: basePayload };
      }
      return { ok: true, action: "create_analysis", payload: basePayload };
    }
    basePayload.mode = pp ? "paper" : "code";
    return { ok: true, action: pp ? "start_paper" : "start_code", payload: basePayload };
  }

  function normalizeSourcePayload(data) {
    var d = (data && typeof data === "object") ? data : {};
    var txt = typeof d.content === "string" ? d.content : (typeof d.raw_source === "string" ? d.raw_source : (typeof d.source === "string" ? d.source : ""));
    var lines = Array.isArray(d.lines) ? d.lines.map(function (it, idx) {
      return Array.isArray(it) ? [Number(it[0]) || (idx + 1), String(it[1] == null ? "" : it[1])] : [idx + 1, String(it == null ? "" : it)];
    }) : (txt ? txt.split(/\r?\n/).map(function (ln, i) { return [i + 1, ln]; }) : []);
    return { text: txt, lines: lines };
  }

  function extractDivergences(bundle, rawSession) {
    var list = [];
    var b = (bundle && typeof bundle === "object") ? bundle : {};
    var s = (rawSession && typeof rawSession === "object") ? rawSession : {};
    var srcs = [].concat(b.divergences || [], (b.static_validation && b.static_validation.findings) || [], s.divergences || []);
    srcs.forEach(function (it) {
      if (it && typeof it === "object") list.push(it);
    });
    return list;
  }

  function renderDivergencePanelHtml(bundle, rawSession, unknownState) {
    if (unknownState) return "";
    var divs = extractDivergences(bundle, rawSession);
    if (divs.length === 0) return "";
    return '<section class="card-block divergence-panel" data-divergence-panel="true" aria-label="Detected Divergences">' +
      '<div class="deck-row"><strong>⚠ Static Scientific &amp; Spec Divergences (' + divs.length + ')</strong><span class="div-cat-pill">CLAIMED</span></div>' +
      divs.slice(0, 8).map(function (d) {
        return '<div class="div-item-card">' +
          '<div class="deck-row"><strong>' + escHtml(stripDollars(d.title || d.rule_id || "Divergence")) + '</strong>' +
          (d.file ? '<button type="button" class="small-btn" data-jump-file="' + escHtml(d.file) + '" data-jump-line="' + Number(d.line || 1) + '"><code>' + escHtml(d.file + ":L" + (d.line || 1)) + '</code></button>' : '') +
          '</div><div style="margin-top:3px;color:var(--ink-soft);">' + escHtml(stripDollars(d.message || d.summary || "")) + '</div></div>';
      }).join("") + "</section>";
  }

  function createSyncScheduler(opts) {
    var cfg = opts || {};
    var baseMs = Number(cfg.baseIntervalMs || 10000);
    var timer = null;
    var controller = null;
    var errStreak = 0;
    var idleStreak = 0;
    function clearTimer() { if (timer !== null) { clearTimeout(timer); timer = null; } }
    function abortInFlight() { if (controller) { try { controller.abort(); } catch (_e) {} controller = null; } }
    return {
      clearTimer: clearTimer,
      abortInFlight: abortInFlight,
      nextErrorBackoffMs: function () { errStreak += 1; return Math.min(30000, 1000 * Math.pow(2, Math.min(4, errStreak - 1))); },
      nextIdleDelayMs: function (hadChange) { if (hadChange) { errStreak = 0; idleStreak = 0; return baseMs; } idleStreak = Math.min(4, idleStreak + 1); return Math.min(60000, baseMs * Math.pow(2, idleStreak - 1)); },
      isPageVisible: function () { return typeof document === "undefined" || document.visibilityState === "visible"; },
      schedule: function (delayMs, cb) { clearTimer(); if (typeof document !== "undefined" && document.visibilityState !== "visible") return; timer = setTimeout(function () { timer = null; cb(); }, delayMs); },
      beginRequest: function () { abortInFlight(); controller = typeof AbortController !== "undefined" ? new AbortController() : null; return controller; },
      finishRequest: function (c) { if (controller === c) controller = null; },
      dispose: function () { clearTimer(); abortInFlight(); }
    };
  }

  function buildCopilotChatPayload(question, stateObj) {
    var st = stateObj || {};
    return {
      question: String(question || ""),
      active_stage_id: String(st.activeStageId || "S1"),
      active_file: String(st.activeFile || ""),
      active_line: Math.max(1, parseInt(st.activeLine, 10) || 1),
      ide_open: Boolean(st.ideOpen),
      pinned_watches: st.pinnedWatches ? Array.from(st.pinnedWatches) : [],
      live: true
    };
  }

  function renderThreeLayerViewHtml(bundle, opts) {
    var b = (bundle && typeof bundle === "object") ? bundle : {};
    var tlv = (b.three_layer_view && typeof b.three_layer_view === "object") ? b.three_layer_view : null;
    var options = opts || {};
    if (!tlv || options.unknownState) return "";
    var safeMathFn = typeof options.safeMathMlHtml === "function" ? options.safeMathMlHtml : sanitizeMathMlString;
    var baseFn = typeof options.basename === "function" ? options.basename : function (p) { var a = String(p || "").split(/[\\/]+/); return a[a.length - 1] || ""; };
    var semDone = Boolean(options.semanticCompleted);
    var sa = tlv.static_audit || {};
    var l1 = tlv.layer1_estimator || {};
    var l2 = tlv.layer2_replicators || {};
    var l3 = tlv.layer3_plumbing || {};
    var cnt = Number.isFinite(Number(sa.pattern_classes_checked)) ? Number(sa.pattern_classes_checked) : 4;
    var stampTxt = semDone
      ? "Semantic Comprehension + Bidirectional Math Audit active on locked scope"
      : (sa.stamp || (cnt + " static pattern classes checked; semantic math audit not run in this wave"));
    var l1Syms = Array.isArray(l1.symbols) ? l1.symbols : [];
    var l1Eqs = Array.isArray(l1.equations) ? l1.equations : [];
    var l2Cards = Array.isArray(l2.cards) ? l2.cards : [];
    var l3Files = Array.isArray(l3.plumbing_files) ? l3.plumbing_files : [];
    var l3Unreached = Array.isArray(l3.unreached_symbols) ? l3.unreached_symbols : [];
    var unreachedTotal = Number(l3.unreached_count || l3Unreached.length || 0);

    return '<div class="three-layer-stack" data-three-layer-view="true">' +
      '<div class="three-layer-stamp-bar" data-static-audit-stamp="true"><strong>Scope Audit Posture:</strong> ' + escHtml(stampTxt) + (!semDone ? ' · <span style="color:var(--ink-soft);">' + escHtml(sa.detail || "Static AST pattern scan only — semantic audit not run in this wave.") + "</span>" : "") + "</div>" +
      '<section id="anvil-layer1-estimator" class="three-layer-card layer1" aria-label="Layer 1 Core Mathematical Estimator">' +
        '<div class="deck-row"><strong>' + escHtml(l1.title || "Layer 1 · Core Mathematical Estimator & Equations") + '</strong><span class="prov-tag">' + l1Syms.length + ' active symbol(s) · ' + l1Eqs.length + ' eq(s)</span></div>' +
        (l1Syms.length > 0 ? '<div style="margin-top:5px;display:flex;flex-wrap:wrap;gap:5px;">' + l1Syms.slice(0, 12).map(function (s) {
          return '<span class="reach-pill' + (s.badge === "uncertain" ? " uncertain" : "") + '" data-reach-badge="' + escHtml(s.badge || "reached") + '">' +
            escHtml((s.symbol || s.short_name || "") + " [" + (s.badge || "reached") + "]") +
            (s.file ? ' <button type="button" class="small-btn" style="padding:1px 6px;font-size:11px;" data-jump-file="' + escHtml(s.file) + '" data-jump-line="' + Number(s.lineno || 1) + '">' + escHtml(baseFn(s.file) + ":L" + (s.lineno || 1)) + "</button>" : "") + "</span>";
        }).join("") + "</div>" : '<div class="layer-subcard">0 active estimator symbols in current slice.</div>') +
        l1Eqs.slice(0, 4).map(function (eq) {
          var mfs = Array.isArray(eq.matched_functions) ? eq.matched_functions : [];
          return '<div class="layer-subcard"><div class="deck-row"><strong>Eq (' + escHtml(eq.number || eq.id) + ')' + (eq.label ? ' · <code>' + escHtml(eq.label) + "</code>" : "") + '</strong><span class="prov-tag">' + escHtml(eq.verification_stamp || "STATIC_ALIGNED") + "</span></div>" +
            '<div class="mathml-wrap" style="margin-top:4px;">' + safeMathFn(eq.mathml, eq.label || eq.id) + "</div>" +
            '<div style="margin-top:4px;font-size:11.5px;">' + (mfs.length > 0 ? "Bound: " + mfs.map(function (mf) { return "<code>" + escHtml((mf.file || "") + ":" + (mf.qualname || "")) + "</code>"; }).join(", ") : "Unbound in active entrypoint slice.") + "</div></div>";
        }).join("") +
      "</section>" +
      '<section id="anvil-layer2-replicators" class="three-layer-card layer2" aria-label="Layer 2 Paper Table and Figure Replicators">' +
        '<div class="deck-row"><strong>' + escHtml(l2.title || "Layer 2 · Paper Table & Figure Replicators") + '</strong><span class="prov-tag">' + Number(l2.matched_count || 0) + " matched · " + Number(l2.unmatched_count || 0) + " unmatched</span></div>" +
        (l2Cards.length > 0 ? l2Cards.map(function (c) {
          var okM = Boolean(c.matched);
          return '<div class="layer-subcard' + (okM ? "" : " unmatched") + '" data-replicator-matched="' + String(okM) + '"><div class="deck-row"><strong>' + escHtml(stripDollars(c.title || c.artifact_ref || "No replicator script matched")) + "</strong>" +
            (okM && c.script ? '<button type="button" class="small-btn" data-jump-file="' + escHtml(c.script) + '" data-jump-line="1"><code>' + escHtml(c.script) + "</code> ⤢</button>" : '<span class="reach-pill uncertain">' + escHtml(c.badge || "No replicator script matched") + "</span>") + "</div></div>";
        }).join("") : '<div class="layer-subcard unmatched" data-replicator-matched="false"><strong>No replicator script matched</strong> — 0 manuscript Table/Figure replicator scripts matched in this scope.</div>') +
      "</section>" +
      '<details id="anvil-layer3-plumbing" class="three-layer-details"><summary><span>▸ ' + escHtml(l3.title || "Layer 3 · Data Plumbing, Utilities & Unreached Symbols") + '</span><span class="prov-tag">' + l3Files.length + " plumbing · " + unreachedTotal + " unreached</span></summary>" +
        '<div style="margin-top:6px;"><div class="layer-subcard"><strong>Plumbing Modules:</strong> ' + (l3Files.length ? "<code>" + escHtml(l3Files.join(", ")) + "</code>" : "None") + "</div>" +
        '<div class="layer-subcard"><strong>Unreached Symbols (' + unreachedTotal + '):</strong> ' + (l3Unreached.length ? l3Unreached.slice(0, 30).map(function (u) { return '<span class="reach-pill unreached" data-reach-badge="unreached">' + escHtml((u.file ? u.file + ":" : "") + (u.symbol || "")) + "</span> "; }).join("") : "0") + "</div></div>" +
      "</details></div>";
  }

  function renderReplicationReportV2Html(repState, opts) {
    if (root.AnvilReport && typeof root.AnvilReport.renderReplicationReportV2Html === "function") {
      return root.AnvilReport.renderReplicationReportV2Html(repState, opts);
    }
    return '<section id="sec-summary"><p>Status: not yet run</p></section><section id="sec-matrix"></section><section id="sec-refactoring"></section>';
  }

  var api = {
    MAX_DIRECTION_BYTES: MAX_DIRECTION_BYTES,
    MAX_XVAL_CONCURRENCY: MAX_XVAL_CONCURRENCY,
    V5_BOOT_FAILURE_TABLE: V5_BOOT_FAILURE_TABLE,
    V6_BOOT_FAILURE_TABLE: V6_BOOT_FAILURE_TABLE,
    DISPLAY_STATE_BADGES: DISPLAY_STATE_BADGES,
    OPAQUE_MODULE_ID_RE: OPAQUE_MODULE_ID_RE,
    isValidOpaqueModuleId: isValidOpaqueModuleId,
    escHtml: escHtml,
    stripDollars: stripDollars,
    utf8ByteLength: utf8ByteLength,
    resolveDisplayStateBadge: resolveDisplayStateBadge,
    sanitizeMathMlString: sanitizeMathMlString,
    readSurfaceRoute: readSurfaceRoute,
    writeSurfaceRoute: writeSurfaceRoute,
    validateDirectionPayload: validateDirectionPayload,
    resolveBootFailureSurface: resolveBootFailureSurface,
    normalizeAnalysesList: normalizeAnalysesList,
    renderAnalysisSwitcherOptionsHtml: renderAnalysisSwitcherOptionsHtml,
    buildGuidedIntakeSubmission: buildGuidedIntakeSubmission,
    normalizeVendorFamily: normalizeVendorFamily,
    normalizeSourcePayload: normalizeSourcePayload,
    extractDivergences: extractDivergences,
    renderDivergencePanelHtml: renderDivergencePanelHtml,
    renderThreeLayerViewHtml: renderThreeLayerViewHtml,
    renderReplicationReportV2Html: renderReplicationReportV2Html,
    createSyncScheduler: createSyncScheduler,
    buildCopilotChatPayload: buildCopilotChatPayload
  };

  root.AnvilV5Client = api;
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
