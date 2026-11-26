/* Unified Anvil Workbench Controller (`anvil_workbench.js`, `<= 1,000` lines). */
(function () {
  "use strict";
  const params = new URLSearchParams(window.location.search);
  const pid = params.get("pid") || "", dir = params.get("dir") || "";
  let token = params.get("token") || "";
  if (!token) { try { token = window.localStorage.getItem("anchor_token") || ""; } catch (_e) {} }
  const BACKOFF_STEPS_MS = [1000, 2000, 4000, 8000], HEALTHY_POLL_MS = 10000;
  const FIVE_SCOPES = ["function_locals", "closure_nonlocals", "instance_attrs", "module_globals", "stage_io_contracts"];
  const SURFACE_FAILURE_ROWS = {
    503: { status_kind: "dependency-missing", http_status: 503, badge: "DEGRADED_STATIC", message: "Required runtime/tracer unavailable — showing static AST map" },
    504: { status_kind: "dependency-slow-or-killed", http_status: 504, badge: "TIMEOUT_PARTIAL", message: "Subprocess timed out or was terminated — partial state preserved" },
    502: { status_kind: "dependency-returns-garbage", http_status: 502, badge: "REJECTED_GARBAGE", message: "Malformed payload — rejected fail-closed" },
    500: { status_kind: "backing-store-unreadable", http_status: 500, badge: "UNKNOWN", message: "Session/trace store unreadable (unknown state, not empty)" },
    200: { status_kind: "empty-but-valid", http_status: 200, badge: "EMPTY", message: "Repository parsed cleanly with 0 matched items" }
  };
  const v5 = window.AnvilV5Client;
  const esc = v5 ? v5.escHtml : function (x) { return String(x == null ? "" : x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); };
  const stripDollarTokens = v5 ? v5.stripDollars : function (t) { return String(t == null ? "" : t).replace(/\$/g, ""); };
  function basename(p) { const s = String(p || ""); const i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\")); return i >= 0 ? s.slice(i + 1) : s; }
  function shortWords(r, mw, mc) { const c = stripDollarTokens(r).replace(/\s+/g, " ").trim(); if (!c) return ""; const j = c.split(" ").slice(0, mw || 6).join(" "); return j.length > (mc || 44) ? j.slice(0, (mc || 44) - 1) + "…" : j; }
  function apiUrl(verb, extraObj) {
    const qs = new URLSearchParams();
    if (pid) qs.set("pid", pid);
    if (dir) qs.set("dir", dir);
    if (token) qs.set("token", token);
    if (extraObj && typeof extraObj === "object") Object.keys(extraObj).forEach(function (k) { if (extraObj[k] !== undefined && extraObj[k] !== null && extraObj[k] !== "") qs.set(k, String(extraObj[k])); });
    const qStr = qs.toString();
    return "/api/steward/" + verb + (qStr ? "?" + qStr : "");
  }
  function headers() {
    const h = { "Content-Type": "application/json", "Accept": "application/json" };
    if (token) { h["X-Anchor-Token"] = token; h["Authorization"] = "Bearer " + token; }
    return h;
  }
  function buildCockpitTileDialogueUrl() {
    if (!pid) return "";
    const q = new URLSearchParams();
    q.set("pid", pid); if (dir) q.set("dir", dir); q.set("embed", "1"); q.set("view", "tile"); q.set("inst", "anvil"); if (token) q.set("token", token);
    return "/steward/v1?" + q.toString();
  }

  const state = {
    bootPending: true, bootNeedsInitialFetch: true, bootFailureOnly: false,
    multiAnalysisEnabled: false, anvilV6Enabled: false, scopeDrifted: false, scopeSha256: "",
    scopingState: null, scopingMapExpanded: false, scopingGandalfEnabled: true,
    scopingSelectedModuleIds: null, scopingSoftwareSpec: ".", scopingPaperSpec: "", scopingLegacyRemoved: false,
    replicationViewOpen: params.get("view") === "replication", replicationState: null,
    replicationFilterFlags: false, replicationQueueDrawerId: "", pendingReplicationPhase: "A",
    pendingReplicationCandidateId: "", pendingReplicationCandidateDiff: "", pendingReplicationConsentToken: "",
    replicationPollTimer: null, pendingLitConsentToken: "", pendingSemConsentToken: "", literatureValidated: false, literatureData: null,
    semanticComprehension: null, paperNodeView: "S", copilotMinimized: false,
    analyses: [], activeAnalysisId: params.get("analysis_id") || "", globalActiveAnalysisId: "",
    intakeMode: "initial", intakeFormInitialized: false, formSelectedPipelines: null, warmAnalysisCache: {},
    active: false, launcherOpen: false, cockpitName: params.get("name") || dir || "AI Cockpit",
    candidates: { software: [{ path: ".", label: "This Cockpit Folder" }], papers: [], pipelines: [] },
    seating: { coding_short: "", review_short: "" }, rawSession: null, bundle: null,
    surfaceState: null, unknownState: false, lastUpdatedAt: "",
    lens: "understand", progLevel: 1, inspectorTab: "story", activeScenarioIdx: 0,
    activeStageId: "S1", activeStepId: "1.1", activeFile: "", activeLine: 1,
    ideOpen: false, ideTheme: "light", activePipeline: "", showQuarantinedDrawer: false,
    funnelStage: "all", activeScopes: new Set(FIVE_SCOPES), funnelSearch: "",
    pinnedWatches: new Set(), breakpoints: new Set(), dialogueTurns: [], preLaunchTurns: [],
    useLiveCockpitTile: false, consentAction: "trace", recommendedArgv: ["pytest", "-q"], loadingFileSet: new Set()
  };

  window.__anvilBootTelemetry = { bootSettled: false, bootSkeletonShownInitially: true, setupScreenPaintedDuringBoot: false, setupScreenEverShown: false, lastHttpStatus: 0, bootFailureRow: null };
  window.__anvilRequestLog = [];
  window.__anvilLastSwitchMs = null;
  window.__anvilLastSwitchSource = null;
  window.__anvilBootHydrateMs = null;
  window.__anvilSyncStats = { inFlight: false, pollCount: 0, abortedCount: 0, failureStreak: 0, lastBackoffMs: 0, pausedForVisibility: false };

  let activePollController = null;
  let scheduledPollTimer = null;
  let warmPrefetchController = null;

  function abortWarmPrefetch() { if (warmPrefetchController) { try { warmPrefetchController.abort(); } catch (_e) {} warmPrefetchController = null; } }
  function putWarmAnalysisCache(aid, entry) {
    const k = String(aid || "").trim();
    if (!k || !entry) return;
    delete state.warmAnalysisCache[k];
    state.warmAnalysisCache[k] = entry;
    const keys = Object.keys(state.warmAnalysisCache);
    while (keys.length > 8) {
      const old = keys.find(function (x) { return x !== state.activeAnalysisId; }) || keys[0];
      delete state.warmAnalysisCache[old];
      keys.splice(keys.indexOf(old), 1);
    }
  }
  function recordAnvilRequest(method, url, action, analysisId) {
    window.__anvilRequestLog.push({ method: method, url: url, action: action || "", analysis_id: analysisId || "", ts: Date.now() });
    if (window.__anvilRequestLog.length > 48) window.__anvilRequestLog.splice(0, window.__anvilRequestLog.length - 48);
  }
  function safeMathMlHtml(rawMml, fallbackTitle) { return v5 ? v5.sanitizeMathMlString(rawMml, fallbackTitle) : esc(fallbackTitle || "Equation"); }

  async function postAnvil(action, extraPayload, btn) {
    const origText = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "Working…"; }
    try {
      const bodyObj = Object.assign({ action: action }, extraPayload || {});
      if (pid) bodyObj.pid = pid;
      if (dir) bodyObj.dir = dir;
      if (action !== "create_analysis" && action !== "discover_candidates" && !bodyObj.create_new && !bodyObj.analysis_id && state.activeAnalysisId) {
        bodyObj.analysis_id = state.activeAnalysisId;
      }
      const reqUrl = apiUrl("anvil");
      recordAnvilRequest("POST", reqUrl, action, bodyObj.analysis_id || "");
      let resp = await window.fetch(reqUrl, { method: "POST", headers: headers(), body: JSON.stringify(bodyObj) });
      let data = null;
      try { data = await resp.json(); } catch (_e) { data = null; }
      const isV4Op = (action === "v4_session" || action === "v4_trace" || action === "v4_profile_lit");
      if (isV4Op && resp.status === 400 && String((data && (data.error || data.message)) || "").toLowerCase().indexOf("unknown anvil action") >= 0) {
        const fb = { action: "probe_block", block_id: "__anvil_v4_op__", lock_description: JSON.stringify({ op: action, payload: extraPayload || {} }) };
        if (pid) fb.pid = pid;
        if (dir) fb.dir = dir;
        resp = await window.fetch(apiUrl("anvil"), { method: "POST", headers: headers(), body: JSON.stringify(fb) });
        try { data = await resp.json(); } catch (_e2) { data = null; }
      }
      return { status: resp.status, ok: resp.ok && (!data || data.ok !== false), data: data };
    } catch (err) {
      return { status: 0, ok: false, data: { ok: false, error: err ? err.message : "Network error" } };
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = origText; }
    }
  }

  function hydrateFromServerPayload(data, httpStatus, initialLoad) {
    const statusNum = Number(httpStatus !== undefined && httpStatus !== null ? httpStatus : 0);
    window.__anvilBootTelemetry.lastHttpStatus = statusNum;
    const hasValid = Boolean(data && typeof data === "object" && !Array.isArray(data));
    if (hasValid && typeof data.anvil_v6_enabled === "boolean") state.anvilV6Enabled = data.anvil_v6_enabled;
    const resolvedFailure = v5 ? v5.resolveBootFailureSurface(statusNum, hasValid ? data : null, { anvilV6Enabled: state.anvilV6Enabled }) : null;
    window.__anvilBootTelemetry.bootFailureRow = resolvedFailure;

    if (hasValid && (statusNum === 409 || Boolean(data.scope_drifted))) {
      state.scopeDrifted = true; state.bootFailureOnly = false; state.unknownState = false; state.launcherOpen = true;
      if (data.cockpit_name) state.cockpitName = String(data.cockpit_name);
      if (typeof data.multi_analysis_enabled === "boolean") state.multiAnalysisEnabled = data.multi_analysis_enabled;
      if (data.analysis_id) state.activeAnalysisId = String(data.analysis_id);
      if (Array.isArray(data.selected_module_ids)) state.scopingSelectedModuleIds = data.selected_module_ids.slice();
      state.analyses = v5 ? v5.normalizeAnalysesList(data, null, state.cockpitName) : [];
      state.surfaceState = resolvedFailure || { status_kind: "scope-drifted", http_status: 409, badge: "409_SCOPE_DRIFTED", message: data.message || "409 Scope Drifted" };
      return;
    }
    if (!hasValid) {
      const fbRow = resolvedFailure || SURFACE_FAILURE_ROWS[statusNum] || SURFACE_FAILURE_ROWS[502];
      state.surfaceState = fbRow;
      state.unknownState = Boolean(fbRow && fbRow.unknown_state);
      if (state.unknownState || statusNum === 502) { state.bundle = null; state.bootFailureOnly = statusNum === 502 ? !state.active : false; }
      else if (!state.bundle) { state.active = false; state.bootFailureOnly = true; }
      return;
    }

    if (data.cockpit_name) state.cockpitName = String(data.cockpit_name);
    if (typeof data.multi_analysis_enabled === "boolean") state.multiAnalysisEnabled = data.multi_analysis_enabled;
    state.scopeDrifted = Boolean(data.scope_drifted);
    if (typeof data.scope_sha256 === "string" && data.scope_sha256) state.scopeSha256 = data.scope_sha256;
    if (data.semantic_comprehension && typeof data.semantic_comprehension === "object") state.semanticComprehension = data.semantic_comprehension;
    if (data.candidates && typeof data.candidates === "object") state.candidates = Object.assign({ software: [{ path: ".", label: "This Cockpit Folder" }], papers: [], pipelines: [] }, state.candidates || {}, data.candidates);

    const seatSrc = data.seating || data.model_seating || (data.session && data.session.model_seating) || (data.v4_bundle && data.v4_bundle.seating) || null;
    if (seatSrc && typeof seatSrc === "object") state.seating = { coding_short: String(seatSrc.coding_short || seatSrc.coding_model_id || ""), review_short: String(seatSrc.review_short || seatSrc.review_model_id || "") };

    if (data.surface_state && typeof data.surface_state === "object") state.surfaceState = data.surface_state;
    else if (resolvedFailure && (statusNum < 200 || statusNum >= 300 || data.ok === false || !data.active)) state.surfaceState = resolvedFailure;
    else if (statusNum && SURFACE_FAILURE_ROWS[statusNum] && statusNum !== 200) state.surfaceState = Object.assign({}, SURFACE_FAILURE_ROWS[statusNum], { message: data.message || data.error || SURFACE_FAILURE_ROWS[statusNum].message });
    else state.surfaceState = null;

    state.unknownState = Boolean(statusNum === 500 || (resolvedFailure && resolvedFailure.unknown_state) || (state.surfaceState && (state.surfaceState.http_status === 500 || state.surfaceState.badge === "UNKNOWN")));
    if (state.unknownState) { state.bundle = null; state.bootFailureOnly = false; return; }
    if (statusNum < 200 || statusNum >= 300 || data.ok === false || (resolvedFailure && resolvedFailure.open_intake === false && !data.active)) {
      if (statusNum === 502) { state.bundle = null; state.bootFailureOnly = !state.active; }
      else if (!state.bundle) { state.active = false; state.bootFailureOnly = true; }
      return;
    }

    state.bootFailureOnly = false;
    const prevAid = state.activeAnalysisId;
    const returnedAid = String(data.analysis_id || (data.analysis && data.analysis.analysis_id) || data.active_analysis_id || state.activeAnalysisId || "").trim();
    const directBundle = data.v4_bundle || data.bundle || (data.session && data.session.v4_bundle) || (data.process_map ? data : null);
    state.active = ("active" in data) ? Boolean(data.active) : Boolean(directBundle || data.session);
    if (!state.active) {
      state.bundle = null; state.rawSession = null; state.activeAnalysisId = returnedAid;
      state.analyses = v5 ? v5.normalizeAnalysesList(data, null, state.cockpitName) : [];
      if (!state.surfaceState) state.surfaceState = resolvedFailure || Object.assign({}, SURFACE_FAILURE_ROWS[200]);
      return;
    }

    const switching = Boolean(returnedAid && prevAid && returnedAid !== prevAid);
    if (switching && !data.semantic_comprehension) state.semanticComprehension = null;
    state.rawSession = (data.session && typeof data.session === "object") ? data.session : (switching || initialLoad ? null : state.rawSession);
    if (state.rawSession && state.rawSession.updated_at) state.lastUpdatedAt = String(state.rawSession.updated_at);
    if (data.updated_at) state.lastUpdatedAt = String(data.updated_at);
    if (!directBundle) return;
    state.bundle = directBundle;
    if (returnedAid) state.activeAnalysisId = returnedAid;

    if (v5) {
      const normList = v5.normalizeAnalysesList(Object.assign({}, data, { active: true, analysis_id: state.activeAnalysisId }), directBundle, state.cockpitName);
      if (normList.length > 0) { state.analyses = normList; if (!state.activeAnalysisId) state.activeAnalysisId = normList[0].analysis_id; }
    }
    const stages = getStages();
    if (stages.length === 0 && !state.surfaceState) state.surfaceState = Object.assign({}, SURFACE_FAILURE_ROWS[200]);
    if (Array.isArray(directBundle.recommended_argv) && directBundle.recommended_argv.length > 0) state.recommendedArgv = directBundle.recommended_argv.slice();
    const v4Sess = directBundle.session || (state.rawSession && state.rawSession.v4_session) || {};
    if (Array.isArray(v4Sess.pinned_watches)) state.pinnedWatches = new Set(v4Sess.pinned_watches.map(String));
    if (Array.isArray(v4Sess.breakpoints)) {
      const nb = new Set();
      v4Sess.breakpoints.forEach(function (bp) { if (typeof bp === "string") nb.add(bp); else if (bp && bp.file && bp.line) nb.add(bp.file + ":" + bp.line); });
      state.breakpoints = nb;
    }
    if (switching || initialLoad) {
      state.dialogueTurns = Array.isArray(directBundle.dialogue_turns) ? directBundle.dialogue_turns.slice() : [];
      state.activeStageId = v4Sess.active_stage_id ? String(v4Sess.active_stage_id) : "S1";
      state.activeStepId = v4Sess.active_step_id ? String(v4Sess.active_step_id) : "1.1";
      state.activeFile = v4Sess.active_file ? String(v4Sess.active_file) : "";
      state.activeLine = Number(v4Sess.active_line) || 1;
      state.ideOpen = Boolean(v4Sess.ide_open);
      state.ideTheme = v4Sess.ide_theme === "dark" ? "dark" : "light";
      state.activePipeline = typeof v4Sess.active_pipeline === "string" ? v4Sess.active_pipeline : "";
    }
    if (state.activeAnalysisId) putWarmAnalysisCache(state.activeAnalysisId, { bundle: directBundle, rawSession: state.rawSession, seating: Object.assign({}, state.seating), lastUpdatedAt: state.lastUpdatedAt, semanticComprehension: state.semanticComprehension, dialogueTurns: state.dialogueTurns.slice() });
    ensureValidSelection();
  }

  function getSemanticPass2() {
    return (state.semanticComprehension && state.semanticComprehension.semantic_status === "completed" && state.semanticComprehension.pass2) ? state.semanticComprehension.pass2 : null;
  }

  function getStages() {
    const p2 = getSemanticPass2();
    if (p2 && Array.isArray(p2.l1_stages) && p2.l1_stages.length > 0) {
      return p2.l1_stages.map(function (s) {
        return {
          id: s.stage_id, stage_id: s.stage_id, title: s.title, subtitle: s.subtitle, kind: s.kind,
          files: s.files || [], purpose: s.subtitle || "", what_enters: s.inputs || ["inputs"],
          actions_run: (s.symbols || []).map(function (x) { return x.split(":").pop(); }),
          what_exits: s.outputs || ["outputs"], verdict: (state.bundle && state.bundle.has_trace) ? "TRACED" : "STATIC_AST",
          l2_steps: (s.l2_steps || []).map(function (st) { return { id: st.step_id, title: st.title, summary: st.summary, code_ref: { file: st.file, start_line: st.start_line, end_line: st.end_line } }; })
        };
      });
    }
    return (state.bundle && state.bundle.process_map && state.bundle.process_map.l1_stages) || [];
  }

  function getActiveStage() {
    const stages = getStages();
    return stages.find(function (s) { return s.id === state.activeStageId; }) || stages[0] || null;
  }

  function ensureValidSelection() {
    const stages = getStages();
    if (stages.length > 0 && !stages.some(function (s) { return s.id === state.activeStageId; })) state.activeStageId = stages[0].id;
    const filesMap = (state.bundle && state.bundle.files_source_map) || {};
    const keys = Object.keys(filesMap);
    if (keys.length > 0 && (!state.activeFile || !filesMap[state.activeFile])) {
      state.activeFile = keys.find(function (fk) { return !/(?:^|\/)__init__\.py$/.test(fk); }) || keys[0];
    }
  }

  async function ensureActiveFileSourceLoaded(relFile) {
    if (!relFile || !state.bundle || !state.bundle.files_source_map) return;
    const entry = state.bundle.files_source_map[relFile];
    if (!entry || (entry.lines && entry.lines.length > 0 && !entry.needs_lazy_fetch) || state.loadingFileSet.has(relFile)) return;
    state.loadingFileSet.add(relFile);
    try {
      const srcUrl = apiUrl("anvil/source", { file: relFile, analysis_id: state.activeAnalysisId || "" });
      recordAnvilRequest("GET", srcUrl, "source", state.activeAnalysisId || "");
      const resp = await window.fetch(srcUrl, { method: "GET", headers: headers(), cache: "no-store" });
      const data = await resp.json();
      const normSrc = v5 ? v5.normalizeSourcePayload(data) : { text: "", lines: [] };
      if (resp.ok && normSrc.lines.length > 0) {
        entry.lines = normSrc.lines; entry.needs_lazy_fetch = false;
        if (state.ideOpen || state.inspectorTab === "ide") { renderFullIdePane(); renderInspector(); }
      }
    } catch (_e) {} finally { state.loadingFileSet.delete(relFile); }
  }

  async function persistSessionState() {
    if (!state.active || state.unknownState) return;
    await postAnvil("v4_session", {
      pinned_watches: Array.from(state.pinnedWatches), breakpoints: Array.from(state.breakpoints),
      active_stage_id: state.activeStageId, active_step_id: state.activeStepId,
      active_file: state.activeFile, active_line: state.activeLine,
      ide_open: state.ideOpen, ide_theme: state.ideTheme, active_pipeline: state.activePipeline || ""
    });
  }

  function clearScheduledSync() { if (scheduledPollTimer !== null) { window.clearTimeout(scheduledPollTimer); scheduledPollTimer = null; } }
  function abortActivePoll() { if (activePollController) { try { activePollController.abort(); } catch (_e) {} activePollController = null; window.__anvilSyncStats.inFlight = false; window.__anvilSyncStats.abortedCount += 1; } }
  function scheduleNextStateSync(delayMs) {
    clearScheduledSync();
    if (document.visibilityState !== "visible") { window.__anvilSyncStats.pausedForVisibility = true; return; }
    window.__anvilSyncStats.pausedForVisibility = false;
    scheduledPollTimer = window.setTimeout(function () { scheduledPollTimer = null; pollSummaryGate(); }, delayMs);
  }

  async function ensureDiscoveredCandidates() {
    try {
      const u = apiUrl("anvil", { discover: "1" });
      recordAnvilRequest("GET", u, "discover", "");
      const r = await window.fetch(u, { method: "GET", headers: headers(), cache: "no-store" });
      if (r.ok) { const d = await r.json(); if (d && d.candidates) state.candidates = Object.assign(state.candidates, d.candidates); }
    } catch (_e) {}
  }

  async function prefetchWarmAnalyses() {
    if (!state.multiAnalysisEnabled || state.analyses.length <= 1) return;
    abortWarmPrefetch();
    const ctrl = new AbortController();
    warmPrefetchController = ctrl;
    try {
      const others = state.analyses.filter(function (a) { return a && a.analysis_id && a.analysis_id !== state.activeAnalysisId && !state.warmAnalysisCache[a.analysis_id]; }).slice(0, 4);
      await Promise.all(others.map(async function (a) {
        const u = apiUrl("anvil", { action: "v4_state", analysis_id: a.analysis_id });
        const r = await window.fetch(u, { method: "GET", headers: headers(), cache: "no-store", signal: ctrl.signal });
        if (!r.ok) return;
        const d = await r.json();
        const bnd = d && (d.v4_bundle || d.bundle || (d.session && d.session.v4_bundle));
        if (bnd) putWarmAnalysisCache(a.analysis_id, { bundle: bnd, rawSession: d.session || null, seating: d.seating || state.seating, lastUpdatedAt: d.updated_at || "", semanticComprehension: d.semantic_comprehension || null, dialogueTurns: Array.isArray(bnd.dialogue_turns) ? bnd.dialogue_turns.slice() : [] });
      }));
    } catch (_e) {} finally { if (warmPrefetchController === ctrl) warmPrefetchController = null; }
  }

  async function switchActiveAnalysis(targetId) {
    const tid = String(targetId || "").trim();
    if (!tid) return;
    const t0 = performance.now();
    state.launcherOpen = false; state.bootFailureOnly = false;
    const warm = state.warmAnalysisCache[tid];
    if (warm && warm.bundle) {
      hydrateFromServerPayload({ ok: true, active: true, active_analysis_id: tid, analysis_id: tid, analyses: state.analyses, multi_analysis_enabled: state.multiAnalysisEnabled, anvil_v6_enabled: state.anvilV6Enabled, v4_bundle: warm.bundle, session: warm.rawSession, seating: warm.seating, semantic_comprehension: warm.semanticComprehension }, 200, true);
      state.dialogueTurns = Array.isArray(warm.dialogueTurns) ? warm.dialogueTurns.slice() : [];
      renderAll();
      window.__anvilLastSwitchSource = "warm";
      window.__anvilLastSwitchMs = Math.max(0.01, performance.now() - t0);
      if (state.multiAnalysisEnabled) postAnvil("switch_analysis", { analysis_id: tid });
      return;
    }
    const swP = state.multiAnalysisEnabled ? postAnvil("switch_analysis", { analysis_id: tid }) : Promise.resolve(null);
    const stUrl = apiUrl("anvil", { action: "v4_state", analysis_id: tid });
    recordAnvilRequest("GET", stUrl, "v4_state", tid);
    const resArr = await Promise.all([swP, window.fetch(stUrl, { method: "GET", headers: headers(), cache: "no-store" })]);
    let stData = null;
    try { stData = await resArr[1].json(); } catch (_e) {}
    if (resArr[1].ok && stData && stData.ok !== false) { hydrateFromServerPayload(stData, resArr[1].status, true); renderAll(); }
    window.__anvilLastSwitchSource = "network";
    window.__anvilLastSwitchMs = Math.max(0.01, performance.now() - t0);
  }

  async function fetchFullState(initialLoad) {
    abortActivePoll();
    const isBoot = Boolean(initialLoad || state.bootPending || state.bootNeedsInitialFetch);
    const t0 = performance.now();
    const controller = new AbortController();
    activePollController = controller;
    window.__anvilSyncStats.inFlight = true; window.__anvilSyncStats.pollCount += 1;
    const pill = document.getElementById("sync-status-pill");
    if (pill) pill.textContent = "Sync: Reading…";
    try {
      const reqAid = (!isBoot && state.activeAnalysisId) ? state.activeAnalysisId : (params.get("analysis_id") || state.activeAnalysisId || "");
      const stUrl = apiUrl("anvil", { action: "v4_state", analysis_id: reqAid });
      recordAnvilRequest("GET", stUrl, "v4_state", reqAid);
      const resp = await window.fetch(stUrl, { method: "GET", headers: headers(), cache: "no-store", signal: controller.signal });
      let data = null;
      try { data = await resp.json(); } catch (_e) {}
      if (activePollController === controller) { activePollController = null; window.__anvilSyncStats.inFlight = false; }

      if (resp.ok && data && data.ok !== false) {
        window.__anvilSyncStats.failureStreak = 0; window.__anvilSyncStats.lastBackoffMs = 0;
        hydrateFromServerPayload(data, resp.status, isBoot);
        if (isBoot && params.get("view") === "scoping") state.launcherOpen = true;
        if (state.anvilV6Enabled && state.replicationViewOpen && state.active && !state.scopeDrifted) {
          await fetchReplicationState(state.activeAnalysisId);
        } else if (state.anvilV6Enabled && (!state.active || state.launcherOpen || state.scopeDrifted)) {
          await fetchScopingV2State(state.scopingSelectedModuleIds);
        } else if (!state.anvilV6Enabled && !state.active && !state.unknownState) {
          await ensureDiscoveredCandidates();
        }
        if (isBoot && state.multiAnalysisEnabled && state.analyses.length > 1) {
          await prefetchWarmAnalyses();
        }
        state.bootPending = false; state.bootNeedsInitialFetch = false;
        window.__anvilBootTelemetry.bootSettled = true;
        if (pill) pill.textContent = "Sync: Live (" + resp.status + ")";
        renderAll();
        if (isBoot) window.__anvilBootHydrateMs = Math.max(0.01, performance.now() - t0);
        scheduleNextStateSync(HEALTHY_POLL_MS);
      } else {
        const backoff = BACKOFF_STEPS_MS[Math.min(window.__anvilSyncStats.failureStreak, BACKOFF_STEPS_MS.length - 1)];
        window.__anvilSyncStats.failureStreak += 1; window.__anvilSyncStats.lastBackoffMs = backoff;
        hydrateFromServerPayload(data, resp.status || 500, false);
        if (resp.status === 409 && state.anvilV6Enabled) await fetchScopingV2State(state.scopingSelectedModuleIds);
        state.bootPending = false; state.bootNeedsInitialFetch = false; window.__anvilBootTelemetry.bootSettled = true;
        renderAll();
        scheduleNextStateSync(backoff);
      }
    } catch (err) {
      if (activePollController === controller) { activePollController = null; window.__anvilSyncStats.inFlight = false; }
      if (err && err.name === "AbortError") { if (state.bootPending) state.bootNeedsInitialFetch = true; return; }
      const backoff = BACKOFF_STEPS_MS[Math.min(window.__anvilSyncStats.failureStreak, BACKOFF_STEPS_MS.length - 1)];
      window.__anvilSyncStats.failureStreak += 1; window.__anvilSyncStats.lastBackoffMs = backoff;
      hydrateFromServerPayload({ ok: false, error: err ? err.message : "Network timeout" }, 0, false);
      state.bootPending = false; state.bootNeedsInitialFetch = false; window.__anvilBootTelemetry.bootSettled = true;
      renderAll();
      scheduleNextStateSync(backoff);
    }
  }

  async function pollSummaryGate() {
    if (document.visibilityState !== "visible") { window.__anvilSyncStats.pausedForVisibility = true; return; }
    if (state.bootPending || state.bootNeedsInitialFetch) { await fetchFullState(true); return; }
    abortActivePoll();
    const controller = new AbortController();
    activePollController = controller;
    window.__anvilSyncStats.inFlight = true; window.__anvilSyncStats.pollCount += 1;
    try {
      const sumUrl = apiUrl("anvil", { summary: "1", analysis_id: state.activeAnalysisId || "" });
      recordAnvilRequest("GET", sumUrl, "summary", state.activeAnalysisId || "");
      const resp = await window.fetch(sumUrl, { method: "GET", headers: headers(), cache: "no-store", signal: controller.signal });
      let sumData = null;
      try { sumData = await resp.json(); } catch (_e) {}
      if (activePollController === controller) { activePollController = null; window.__anvilSyncStats.inFlight = false; }
      if (!resp.ok || !sumData || sumData.ok === false) {
        const backoff = BACKOFF_STEPS_MS[Math.min(window.__anvilSyncStats.failureStreak, BACKOFF_STEPS_MS.length - 1)];
        window.__anvilSyncStats.failureStreak += 1; window.__anvilSyncStats.lastBackoffMs = backoff;
        hydrateFromServerPayload(sumData, resp.status || 500, false);
        renderAll();
        scheduleNextStateSync(backoff);
        return;
      }
      window.__anvilSyncStats.failureStreak = 0; window.__anvilSyncStats.lastBackoffMs = 0;
      const nextUp = String((sumData.session && sumData.session.updated_at) || sumData.updated_at || "");
      if (Boolean(sumData.active) !== state.active || (nextUp && nextUp !== state.lastUpdatedAt)) {
        window.__anvilSyncStats.idleStreak = 0;
        await fetchFullState(false);
        return;
      }
      window.__anvilSyncStats.idleStreak = Math.min(4, (window.__anvilSyncStats.idleStreak || 0) + 1);
      scheduleNextStateSync(Math.min(60000, HEALTHY_POLL_MS * Math.pow(2, window.__anvilSyncStats.idleStreak - 1)));
    } catch (err) {
      if (activePollController === controller) { activePollController = null; window.__anvilSyncStats.inFlight = false; }
      if (err && err.name === "AbortError") return;
      const backoff = BACKOFF_STEPS_MS[Math.min(window.__anvilSyncStats.failureStreak, BACKOFF_STEPS_MS.length - 1)];
      window.__anvilSyncStats.failureStreak += 1; window.__anvilSyncStats.lastBackoffMs = backoff;
      scheduleNextStateSync(backoff);
    }
  }

  function renderTopDeckAndBanner() {
    const b = state.bundle;
    const cname = state.cockpitName || "AI Cockpit";
    const brandSpan = document.getElementById("brandTitleText");
    if (brandSpan) {
      brandSpan.textContent = state.anvilV6Enabled ? "Anvil · Process Workbench & Scientific IDE" : "Anvil v5 · B3 Workbench + Scientific IDE";
      if (state.anvilV6Enabled) document.title = "Anvil · Anchor Cockpit Process Workbench & Scientific IDE";
    }

    const switcherEl = document.getElementById("analysisSwitcherSelect");
    if (switcherEl) {
      switcherEl.innerHTML = state.bootPending ? '<option value="">Hydrating analyses…</option>' : (v5 ? v5.renderAnalysisSwitcherOptionsHtml(state.analyses, state.activeAnalysisId) : "");
      switcherEl.disabled = state.bootPending || (!state.multiAnalysisEnabled && state.analyses.length <= 1);
    }
    const newBtnEl = document.getElementById("btnNewAnvilAnalysis");
    if (newBtnEl) newBtnEl.disabled = state.bootPending || !state.multiAnalysisEnabled;

    const bootSkel = document.getElementById("anvilBootSkeleton");
    const bootErrCard = document.getElementById("anvilBootErrorCard");
    const launchEl = document.getElementById("cockpit-launch-screen");
    const scopingV2El = document.getElementById("anvilScopingV2Root");
    const repV2El = document.getElementById("anvilReplicationV2Root");
    const mainSplitEl = document.getElementById("main-workbench-split");
    const lensRowEl = document.getElementById("workbench-lens-row");

    if (state.anvilV6Enabled && !state.scopingLegacyRemoved && launchEl) {
      launchEl.innerHTML = ""; launchEl.hidden = true; state.scopingLegacyRemoved = true;
    }
    if (state.bootPending) {
      if (bootSkel) bootSkel.hidden = false;
      if (bootErrCard) bootErrCard.hidden = true;
      if (launchEl) launchEl.hidden = true;
      if (scopingV2El) scopingV2El.hidden = true;
      mainSplitEl.hidden = true; lensRowEl.hidden = true;
      return;
    }
    if (bootSkel) bootSkel.hidden = true;

    const showRep = Boolean(state.anvilV6Enabled && state.replicationViewOpen && !state.scopeDrifted);
    const showWb = (state.active || state.unknownState) && !state.launcherOpen && !state.scopeDrifted && !showRep;
    const showErr = Boolean(state.bootFailureOnly && !state.launcherOpen && !showWb && !showRep && !state.scopeDrifted);
    const showIntake = !showWb && !showRep && !showErr;

    if (showIntake) {
      window.__anvilBootTelemetry.setupScreenEverShown = true;
      if (!window.__anvilBootTelemetry.bootSettled) window.__anvilBootTelemetry.setupScreenPaintedDuringBoot = true;
    }
    if (bootErrCard) {
      bootErrCard.hidden = !showErr;
      if (showErr) {
        const se = state.surfaceState || {};
        document.getElementById("bootErrorHeading").textContent = (se.badge ? "[" + se.badge + "] " : "") + "Anvil Cockpit State Error (Not Empty)";
        document.getElementById("bootErrorDetail").textContent = se.message || "Unable to read Anvil state.";
      }
    }

    const openRepBtn = document.getElementById("btnOpenReplicationReport");
    if (openRepBtn) {
      openRepBtn.hidden = !(state.anvilV6Enabled && state.active && !state.scopeDrifted);
      if (!openRepBtn.hidden && window.AnvilV6Runtime) window.AnvilV6Runtime.hydrateV6BrandIcons(openRepBtn);
    }
    const runSemBtn = document.getElementById("btnRunSemanticPass");
    if (runSemBtn) {
      runSemBtn.hidden = !(state.anvilV6Enabled && state.active && !state.scopeDrifted);
      const semDone = Boolean(getSemanticPass2());
      runSemBtn.textContent = semDone ? "↻ Re-Run Gandalf + Ramanujan Pass" : "🧠 Run Gandalf + Ramanujan Pass";
    }

    if (state.anvilV6Enabled) {
      if (launchEl) launchEl.hidden = true;
      if (scopingV2El) scopingV2El.hidden = !showIntake;
      if (repV2El) repV2El.hidden = !showRep;
      document.body.classList.toggle("v6-scoping-active", showIntake);
      document.body.classList.toggle("v6-workbench-active", showWb);
      document.body.classList.toggle("v6-replication-active", showRep);
      if (showIntake) { if (window.AnvilV6Runtime) window.AnvilV6Runtime.hydrateV6BrandIcons(scopingV2El); renderScopingV2Surface(); }
      else if (showRep) { if (window.AnvilV6Runtime) window.AnvilV6Runtime.hydrateV6BrandIcons(repV2El); renderReplicationV2Surface(); }
    } else {
      if (scopingV2El) scopingV2El.hidden = true;
      if (repV2El) repV2El.hidden = true;
      if (launchEl) launchEl.hidden = !showIntake;
      if (showIntake) renderLegacyV5Intake();
    }

    mainSplitEl.hidden = !showWb;
    lensRowEl.hidden = !showWb;
    document.getElementById("active-session-controls").hidden = !(state.active || state.unknownState);

    const seatEl = document.getElementById("seating-badge");
    seatEl.textContent = (state.seating && (state.seating.coding_short || state.seating.review_short))
      ? ("Code: " + (state.seating.coding_short || "CLI") + " · Review: " + (state.seating.review_short || "CLI"))
      : "Seats: Configured CLI";

    const repoBadge = document.getElementById("repo-badge");
    const provStamp = document.getElementById("provenance-stamp");
    const hasTrace = Boolean(b && b.has_trace);
    if (state.unknownState) {
      repoBadge.textContent = "Store: UNKNOWN"; provStamp.textContent = "UNKNOWN"; provStamp.className = "prov-tag";
    } else if (b) {
      repoBadge.textContent = (b.repo_name || cname) + (b.repo_fingerprint ? " · " + String(b.repo_fingerprint).slice(0, 8) : "");
      provStamp.textContent = hasTrace ? "● TRACED · VERIFIED_TRACE" : "◌ Static · NO_RECEIPT";
      provStamp.className = "prov-tag" + (hasTrace ? " traced" : "");
    } else {
      repoBadge.textContent = cname; provStamp.textContent = "SETUP_READY"; provStamp.className = "prov-tag";
    }

    renderAuditChipsBar(b, hasTrace);
    const pm = b && b.paper_map, p2 = getSemanticPass2();
    const hasPaper = Boolean((pm && pm.has_paper !== false && !state.unknownState && ((pm.equations && pm.equations.length > 0) || pm.paper_title)) || (p2 && (p2.paper_aligned_rows || []).length > 0));
    document.getElementById("lens-tab-paper").style.display = hasPaper ? "" : "none";
    if (!hasPaper && state.lens === "paper") state.lens = "understand";
    document.querySelectorAll(".lens-tab").forEach(function (btn) { btn.classList.toggle("active", btn.getAttribute("data-lens") === state.lens); });
    document.querySelectorAll("[data-prog-level]").forEach(function (btn) { btn.classList.toggle("active", Number(btn.getAttribute("data-prog-level")) === state.progLevel); });
    const ideBtn = document.getElementById("btn-open-ide-debugger");
    ideBtn.classList.toggle("active", state.ideOpen); ideBtn.setAttribute("aria-pressed", String(state.ideOpen));
    ideBtn.textContent = state.ideOpen ? "← Back to 48/52 Workbench (Esc)" : "💻 Open IDE Debugger ⤢";
    mainSplitEl.classList.toggle("ide-debugger-open", state.ideOpen);
    document.getElementById("full-ide-pane").hidden = !state.ideOpen; document.getElementById("left-legend-row").hidden = state.ideOpen;
    document.getElementById("btn-rail-back").hidden = !state.ideOpen; document.getElementById("inspector-tabbar").hidden = state.ideOpen;
    document.getElementById("left-width-pill").textContent = state.ideOpen ? "25% Live Rail" : "48% Serpentine";
    const shardBanner = document.getElementById("semanticShardBanner");
    if (shardBanner) {
      const sc = state.semanticComprehension;
      if (sc && sc.semantic_status === "running" && Number(sc.completed_shards || 0) < Number(sc.total_shards || 5)) { shardBanner.hidden = false; shardBanner.textContent = "⏳ Semantic Comprehension Streaming: PARTIAL " + Number(sc.completed_shards || 0) + "/" + Number(sc.total_shards || 5) + " shards committed"; }
      else shardBanner.hidden = true;
    }
    const banner = document.getElementById("surface-state-banner"), surf = state.surfaceState;
    if (surf && surf.status_kind && surf.status_kind !== "healthy") {
      banner.hidden = false;
      const isErr = Number(surf.http_status || 0) >= 500 && Number(surf.http_status) !== 503;
      banner.className = "surface-banner" + (isErr ? " sev-error" : (surf.status_kind === "empty-but-valid" ? " sev-empty" : ""));
      document.getElementById("surface-state-badge").textContent = surf.badge || "ALERT";
      document.getElementById("surface-state-message").textContent = surf.message || "";
    } else banner.hidden = true;
    if (window.AnvilV6Runtime && window.AnvilV6Runtime.syncSurfaceDepInstallBanner) window.AnvilV6Runtime.syncSurfaceDepInstallBanner();
  }

  function renderAuditChipsBar(b, hasTrace) {
    const host = document.getElementById("audit-chips-bar");
    if (!host) return;
    const p2 = getSemanticPass2(), semDisp = state.semanticComprehension && state.semanticComprehension.display_state;
    const divCnt = p2 ? ((p2.ramanujan_audit.pass2a_paper_to_code || []).length + (p2.ramanujan_audit.pass2b_code_to_paper || []).length) : (v5 ? v5.extractDivergences(b, state.rawSession).length : 0);
    const unexCnt = (b && b.three_layer_view && b.three_layer_view.layer3_plumbing && b.three_layer_view.layer3_plumbing.unreached_count) || 0;
    const chips = [];
    if (hasTrace) chips.push('<span class="audit-chip st-verified-trace">● VERIFIED_TRACE</span>');
    if (semDisp === "ATTESTED") chips.push('<span class="audit-chip st-verified-numeric">✓ ATTESTED (2-Family)</span>');
    if (divCnt > 0) chips.push('<span class="audit-chip st-map-drift">⚠ ' + divCnt + " Divergence(s)</span>");
    if (unexCnt > 0) chips.push('<span class="audit-chip st-unexercised">∅ ' + unexCnt + " Unreached</span>");
    if (!hasTrace && semDisp !== "ATTESTED") chips.push('<span class="audit-chip st-unexercised">◌ Untraced Static Mode</span>');
    host.innerHTML = chips.join("");
  }

  function renderLeftPane() {
    if (window.AnvilSchematic && window.AnvilSchematic.renderLeftPaneDom) {
      window.AnvilSchematic.renderLeftPaneDom({ state: state, p2: getSemanticPass2(), stages: getStages(), actStage: getActiveStage(), selectStage: selectStage, persistSessionState: persistSessionState, renderAll: renderAll });
    }
  }

  function selectStage(sid) {
    if (!sid) return;
    state.activeStageId = sid;
    const st = getActiveStage();
    if (st && (st.l2_steps || []).length > 0) {
      state.activeStepId = st.l2_steps[0].id;
      const cr = st.l2_steps[0].code_ref || {};
      if (cr.file) { state.activeFile = cr.file; state.activeLine = Number(cr.start_line) || 1; }
    }
    persistSessionState(); renderAll();
  }

  function renderFullIdePane() {
    if (window.AnvilIdeDrawer) window.AnvilIdeDrawer.renderFullIdePane({ state: state, ensureActiveFileSourceLoaded: ensureActiveFileSourceLoaded, persistSessionState: persistSessionState, renderAll: renderAll, renderInspector: renderInspector });
  }

  function bindPinAndJumpButtons(container) {
    container.querySelectorAll("[data-pin-var]").forEach(function (btn) {
      btn.addEventListener("click", function () { const v = btn.getAttribute("data-pin-var") || ""; if (state.pinnedWatches.has(v)) state.pinnedWatches.delete(v); else state.pinnedWatches.add(v); persistSessionState(); renderFullIdePane(); renderInspector(); });
    });
    container.querySelectorAll("[data-jump-file]").forEach(function (btn) {
      btn.addEventListener("click", function () { state.activeFile = btn.getAttribute("data-jump-file") || state.activeFile; state.activeLine = Number(btn.getAttribute("data-jump-line")) || 1; state.ideOpen = true; persistSessionState(); renderAll(); });
    });
  }

  function renderInspector() {
    if (!(state.active || state.unknownState) || state.launcherOpen) return;
    document.querySelectorAll(".insp-tab").forEach(function (t) { t.classList.toggle("active", t.getAttribute("data-inspector") === state.inspectorTab); });
    const body = document.getElementById("inspector-body");
    document.getElementById("walkthroughPanel").hidden = true; document.getElementById("betaReaderPanelStrip").hidden = true;
    if (state.ideOpen || state.inspectorTab === "funnel" || state.unknownState) {
      if (window.AnvilIdeDrawer) window.AnvilIdeDrawer.renderSmartFunnelView(body, { state: state, FIVE_SCOPES: FIVE_SCOPES, renderInspector: renderInspector, bindPinAndJumpButtons: bindPinAndJumpButtons });
      return;
    }

    if (state.inspectorTab === "xval") {
      if (window.AnvilIdeDrawer && window.AnvilIdeDrawer.renderValidatorTab) {
        window.AnvilIdeDrawer.renderValidatorTab(body, {
          state: state,
          onRunXval: async function (runBtn) {
            if (state.anvilV6Enabled) await triggerSemanticComprehensionRun(runBtn);
            else { const r = await postAnvil("v4_xval", { max_concurrency: 2 }, runBtn); if (r && r.ok && r.data) { hydrateFromServerPayload(r.data, r.status, false); renderAll(); } }
          }
        });
      }
      return;
    }

    if (state.inspectorTab === "ide") {
      const filesMap = (state.bundle && state.bundle.files_source_map) || {};
      const fObj = filesMap[state.activeFile] || Object.values(filesMap)[0];
      if (fObj && fObj.needs_lazy_fetch) ensureActiveFileSourceLoaded(fObj.file);
      body.innerHTML = '<div class="card-block active-card"><div class="deck-row"><strong>Code Split (58%/42%) · ' + esc(fObj ? fObj.file : "No File") + '</strong><button type="button" id="btn-expand-ide-split" class="ide-posture-btn">💻 Expand 3-Col IDE Debugger ⤢</button></div>' +
        '<div style="margin-top:6px;font-family:var(--font-mono);font-size:11.5px;white-space:pre-wrap;max-height:240px;overflow:auto;background:var(--bg-canvas);padding:8px;border-radius:6px;">' + esc(fObj ? (fObj.lines || []).slice(0, 32).map(function (p) { return p[0] + " | " + p[1]; }).join("\n") : "Empty repository") + "</div></div>";
      const exp = document.getElementById("btn-expand-ide-split");
      if (exp) exp.addEventListener("click", function () { state.ideOpen = true; persistSessionState(); renderAll(); });
      return;
    }

    if (state.inspectorTab === "walkthrough" || state.lens === "debug") {
      const steps = ((state.rawSession && state.rawSession.walkthrough && state.rawSession.walkthrough.steps) || []);
      body.innerHTML = '<div class="card-block"><strong>▶ Code Walkthrough &amp; Runtime Tripwires</strong><div style="margin-top:4px;color:var(--ink-soft);">' + (steps.length > 0 ? esc(steps[0].title || "Step 1 ready") : "Click ▶ Run Consented Trace to inspect runtime variable transitions in the 3-column IDE Debugger.") + "</div></div>";
      return;
    }

    const p2 = getSemanticPass2();
    if (state.lens === "refactor") {
      const diffs = (p2 && p2.story_diff_rows) || getStages().map(function (st, i) {
        return { from_stage_id: st.id, to_node_id: "N" + (i + 1), today_title: st.id + " · " + st.title, today_detail: st.purpose || "Current imperative stage", pure_core_title: "N" + (i + 1) + " · Pure Functional Stage", pure_core_detail: "Explicit tensor inputs/outputs with I/O isolated at shell.", disposition: "extract_pure_core" };
      });
      const refs = (p2 && p2.refactor_candidates) || [];
      body.innerHTML = diffs.map(function (d) {
        return '<article class="story-diff-row"><div class="diff-col"><div class="kv-lbl">Today (' + esc(d.from_stage_id) + ')</div><strong>' + esc(stripDollarTokens(d.today_title)) + '</strong><div style="color:var(--ink-soft);margin-top:2px;">' + esc(stripDollarTokens(d.today_detail)) + '</div></div>' +
          '<div class="diff-col pure"><div class="kv-lbl">Proposed (' + esc(d.to_node_id) + ')</div><strong>' + esc(stripDollarTokens(d.pure_core_title)) + '</strong><div style="color:var(--ink-soft);margin-top:2px;">' + esc(stripDollarTokens(d.pure_core_detail)) + "</div></div></article>";
      }).join("") + refs.map(function (rc) {
        const bdg = v5 ? v5.resolveDisplayStateBadge(rc.display_state) : { cls: "badge-claimed-amber", label: "CLAIMED" };
        const isBlk = rc.gate_status === "blocked_author_decision" || rc.gate_status === "blocked";
        return '<div class="card-block' + (isBlk ? " fault-card" : "") + '"><div class="deck-row"><strong>' + esc(rc.title) + '</strong><span class="' + esc(isBlk ? "badge-fault-red" : bdg.cls) + '">' + esc(isBlk ? "✕ BLOCKED (Wrong-Side Guard)" : bdg.label) + "</span></div>" +
          '<div style="margin-top:4px;color:var(--ink-soft);">' + esc(rc.summary) + "</div>" +
          (rc.blocked_reason ? '<div style="margin-top:4px;font-weight:700;color:#7A1E0A;">' + esc(rc.blocked_reason) + "</div>" : "") + "</div>";
      }).join("");
      return;
    }

    if (state.lens === "paper") {
      if (window.AnvilSchematic && window.AnvilSchematic.renderPaperCrosswalkInspector) {
        window.AnvilSchematic.renderPaperCrosswalkInspector(body, { state: state, p2: p2, stages: getStages(), safeMathMlHtml: safeMathMlHtml, renderInspector: renderInspector, bindPinAndJumpButtons: bindPinAndJumpButtons });
      }
      return;
    }

    if (state.lens === "profile") {
      if (window.AnvilSchematic && window.AnvilSchematic.renderProfileAndLiteratureInspector) {
        window.AnvilSchematic.renderProfileAndLiteratureInspector(body, { state: state, stages: getStages(), openLiteraturePrivacyModal: v6Ctrl && v6Ctrl.openLiteraturePrivacyModal });
      }
      return;
    }

    // Lens 1: Understand Process — Compact 3-Layer Scope Summary + Causal Triptych Chapter Cards!
    const semDone = Boolean(p2);
    const threeLayerHtml = (state.anvilV6Enabled && v5 && v5.renderThreeLayerViewHtml)
      ? v5.renderThreeLayerViewHtml(state.bundle, { unknownState: state.unknownState, safeMathMlHtml: safeMathMlHtml, basename: basename, semanticCompleted: semDone })
      : "";
    const stages = getStages();
    const triptychMap = {};
    if (p2 && Array.isArray(p2.causal_triptych)) p2.causal_triptych.forEach(function (t) { triptychMap[t.stage_id] = t; });
    const gandalfHtml = (semDone && state.semanticComprehension && state.semanticComprehension.gandalf_critique)
      ? '<div class="card-block active-card"><div class="deck-row"><strong>🧙 Gandalf Deep-Think Architectural Read</strong><span class="badge-claimed-amber">GROUNDED</span></div><div style="margin-top:4px;">' + esc(state.semanticComprehension.gandalf_critique.what_is_really_going_on || "") + '</div><div style="margin-top:4px;color:#7A1E0A;"><strong>Watch:</strong> ' + esc(state.semanticComprehension.gandalf_critique.missing_or_wrong || "") + "</div></div>"
      : "";

    const ramanujanItems = p2 && p2.ramanujan_audit ? [].concat(p2.ramanujan_audit.pass2a_paper_to_code || [], p2.ramanujan_audit.pass2b_code_to_paper || []) : [];
    const ramanujanHtml = ramanujanItems.length > 0
      ? '<div class="card-block fault-card"><div class="deck-row"><strong>📐 Ramanujan Bidirectional Audit (' + ramanujanItems.length + ')</strong><span class="badge-claimed-amber">Pass 2a + 2b</span></div>' +
        ramanujanItems.slice(0, 4).map(function (f) {
          const fb = v5 ? v5.resolveDisplayStateBadge(f.display_state) : { cls: "badge-claimed-amber", label: "CLAIMED" };
          return '<div style="margin-top:6px;padding-top:6px;border-top:1px dashed #E5C7B8;"><div class="deck-row"><strong>' + esc(f.title) + '</strong><span class="' + esc(fb.cls) + '">' + esc(fb.label) + '</span></div><div style="color:var(--ink-soft);margin-top:2px;">' + esc(f.code_reality || "") + "</div></div>";
        }).join("") + "</div>"
      : "";

    function renderStageCard(st) {
      const isAct = st.id === state.activeStageId;
      const tr = triptychMap[st.id] || {
        chapter_title: st.id + " · " + stripDollarTokens(st.title || st.id),
        why_needed: stripDollarTokens(st.purpose || "Establishes stage preconditions for downstream computation."),
        transform_mechanism: "Executes " + (st.actions_run || ["AST symbols"]).slice(0, 3).join(", "),
        downstream_handoff: "Emits " + (st.what_exits || ["stage outputs"]).join(", ")
      };
      const lead = (st.l2_steps && st.l2_steps[0] && st.l2_steps[0].code_ref) || null;
      return '<article class="card-block chapter-card' + (isAct ? " active-card" : "") + '" data-chapter-stage="' + esc(st.id) + '">' +
        '<div class="deck-row"><strong>' + esc(tr.chapter_title) + '</strong><div class="selector-group">' +
        (lead && lead.file ? '<button type="button" class="small-btn" data-jump-file="' + esc(lead.file) + '" data-jump-line="' + Number(lead.start_line || 1) + '">💻 ' + esc(basename(lead.file) + ":L" + (lead.start_line || 1)) + " ⤢</button>" : "") +
        "</div></div>" +
        '<div class="causal-triptych">' +
          '<div class="triptych-col"><div class="kv-lbl">1. Why Needed</div><div>' + esc(tr.why_needed) + "</div></div>" +
          '<div class="triptych-col"><div class="kv-lbl">2. Transform Mechanism</div><div>' + esc(tr.transform_mechanism) + "</div></div>" +
          '<div class="triptych-col"><div class="kv-lbl">3. Downstream Handoff</div><div>' + esc(tr.downstream_handoff) + "</div></div>" +
        "</div></article>";
    }
    const actSt = getActiveStage();
    const otherStages = stages.filter(function (s) { return !actSt || s.id !== actSt.id; });
    const stagesHtml = semDone
      ? ((actSt ? renderStageCard(actSt) : "") + (otherStages.length > 0 ? '<details class="card-block"><summary style="cursor:pointer;font-weight:700;">All Stage Causal Triptychs (' + stages.length + ')</summary><div style="display:flex;flex-direction:column;gap:8px;margin-top:8px;">' + otherStages.map(renderStageCard).join("") + "</div></details>" : ""))
      : stages.map(renderStageCard).join("");
    body.innerHTML = semDone ? (gandalfHtml + ramanujanHtml + stagesHtml + threeLayerHtml) : (threeLayerHtml + stagesHtml);
    bindPinAndJumpButtons(body);
  }

  function renderLegacyV5Intake() {
    const cands = state.candidates || {}, bdg = document.getElementById("intakeModeBadge"), closeB = document.getElementById("btnCloseLauncherDrawer");
    if (bdg) bdg.textContent = state.intakeMode === "new" ? "New Analysis" : (state.intakeMode === "edit" ? "Edit Scope" : "Initial Setup");
    if (closeB) closeB.hidden = !state.active;
    const repoSel = document.getElementById("intakeRepoSelect"), msSel = document.getElementById("intakeManuscriptSelect");
    const swInp = document.getElementById("inputSoftwareTarget"), ppInp = document.getElementById("inputPaperTarget"), pipeBox = document.getElementById("intakePipelinesList");
    const swList = (Array.isArray(cands.software) && cands.software.length > 0) ? cands.software : [{ path: ".", label: "This Cockpit Folder" }];
    const ppList = Array.isArray(cands.papers) ? cands.papers : [];
    const pipeList = (Array.isArray(cands.pipelines) && cands.pipelines.length > 0) ? cands.pipelines : [{ id: "all_paper_matched", title: "All Paper-Matched Pipelines" }];
    if (repoSel) repoSel.innerHTML = swList.slice(0, 10).map(function (it) { const p = typeof it === "string" ? it : (it.path || "."); return '<option value="' + esc(p) + '">' + esc(typeof it === "string" ? it : (it.label || p)) + "</option>"; }).join("");
    if (msSel) msSel.innerHTML = ppList.slice(0, 10).map(function (it) { const p = typeof it === "string" ? it : (it.path || ""); return '<option value="' + esc(p) + '">' + esc(typeof it === "string" ? it : (it.label || p)) + "</option>"; }).join("") + '<option value="">None (Software Only)</option>';
    if (!state.intakeFormInitialized) {
      state.intakeFormInitialized = true;
      const rs = (state.intakeMode === "edit" && state.rawSession) ? state.rawSession : null;
      const curMeta = (state.intakeMode === "edit" && state.analyses) ? (state.analyses.find(function (a) { return a.analysis_id === state.activeAnalysisId; }) || {}) : {};
      const tDom = document.getElementById("inputAnalysisTitle"), dDom = document.getElementById("intakeDirectionInput"), rDom = document.getElementById("intakeReplicationPkgToggle"), mDom = document.getElementById("intakeMaxConcurrency");
      if (tDom) tDom.value = rs ? String(rs.title || curMeta.title || "") : "";
      if (swInp) swInp.value = rs ? String(rs.software_spec || rs.software_target || curMeta.software_spec || ".") : String((typeof swList[0] === "string" ? swList[0] : swList[0].path) || ".");
      if (ppInp) ppInp.value = rs ? String(rs.paper_spec || rs.paper_target || curMeta.paper_spec || "") : (ppList.length > 0 ? String((typeof ppList[0] === "string" ? ppList[0] : ppList[0].path) || "") : "");
      if (dDom) dDom.value = rs ? String(rs.direction || "") : "";
      if (rDom) rDom.checked = rs ? (rs.materialize_replication_package !== false) : true;
      if (mDom) mDom.value = String(rs && rs.max_concurrency ? rs.max_concurrency : 2);
      state.formSelectedPipelines = rs && Array.isArray(rs.selected_pipelines) ? rs.selected_pipelines.slice() : pipeList.map(function (p) { return String(p.id || p.pipeline_id || p); });
    }
    if (repoSel && swInp) { repoSel.value = swInp.value; repoSel.onchange = function () { swInp.value = repoSel.value || "."; }; }
    if (msSel && ppInp) { msSel.value = ppInp.value; msSel.onchange = function () { ppInp.value = msSel.value || ""; }; }
    if (pipeBox) {
      const selSet = new Set(state.formSelectedPipelines || []);
      pipeBox.innerHTML = pipeList.slice(0, 8).map(function (p) {
        const pidV = String(p.id || p.pipeline_id || p), chk = (selSet.size === 0 || selSet.has(pidV)) ? " checked" : "";
        return '<label class="intake-pipe-pill"><input type="checkbox" value="' + esc(pidV) + '"' + chk + " /> " + esc(p.title || pidV) + "</label>";
      }).join("");
      pipeBox.querySelectorAll("input[type='checkbox']").forEach(function (cb) { cb.addEventListener("change", function () { state.formSelectedPipelines = Array.from(pipeBox.querySelectorAll("input[type='checkbox']:checked")).map(function (el) { return el.value; }); }); });
    }
  }

  function renderChatMessages() {
    if (window.AnvilIdeDrawer && window.AnvilIdeDrawer.renderCopilotPane) window.AnvilIdeDrawer.renderCopilotPane({ state: state, pid: pid, activeStageId: (getActiveStage() || { id: "scope" }).id, buildCockpitTileDialogueUrl: buildCockpitTileDialogueUrl });
  }

  async function submitChatQuestion(rawQ) {
    const q = String(rawQ || "").trim();
    if (!q) return;
    const basePayload = v5 ? v5.buildCopilotChatPayload(q, state) : { question: q, active_stage_id: state.activeStageId, live: true };
    basePayload.mode = ({ understand: "map", refactor: "remap", paper: "paper", debug: "walkthrough", profile: "map" })[state.lens] || "map";
    basePayload.target = state.activeFile || state.activeStageId;
    const res = await postAnvil("chat", basePayload, document.getElementById("btn-chat-send"));
    if (res && res.ok && res.data) { hydrateFromServerPayload(res.data, res.status, false); if (res.data.reply && state.dialogueTurns.length === 0) state.dialogueTurns.push({ role: "user", text: q }, { role: "assistant", text: res.data.reply }); renderAll(); }
  }

  async function triggerSemanticComprehensionRun(btn) {
    const cRes = await postAnvil("semantic_consent", { analysis_id: state.activeAnalysisId || undefined, scope_sha256: state.scopeSha256 || undefined }, btn);
    if (!cRes || !cRes.ok || !cRes.data || !cRes.data.consent_token) return;
    state.pendingSemConsentToken = cRes.data.consent_token;
    const modal = document.getElementById("semantic-consent-modal"), prev = document.getElementById("semConsentPreview");
    if (prev) prev.textContent = "Scope: " + String(cRes.data.scope_sha256 || "").slice(0, 16) + "… · Payload SHA-256: " + String(cRes.data.payload_sha256 || "").slice(0, 16) + "… (" + Number(cRes.data.payload_bytes || 0) + " B) · Seats: " + (cRes.data.vendors_disclosed || []).join(" + ");
    if (modal) modal.hidden = false;
  }
  async function confirmSemanticConsentRun(btn) {
    const modal = document.getElementById("semantic-consent-modal");
    const res = await postAnvil("semantic_run", { analysis_id: state.activeAnalysisId || undefined, scope_sha256: state.scopeSha256 || undefined, use_live_seats: true, consent_token: state.pendingSemConsentToken || "" }, btn);
    if (modal) modal.hidden = true;
    if (res && res.ok && res.data) { state.semanticComprehension = res.data; if (state.activeAnalysisId && state.warmAnalysisCache[state.activeAnalysisId]) state.warmAnalysisCache[state.activeAnalysisId].semanticComprehension = res.data; renderAll(); }
  }

  function openConsentModal(actionKind) {
    state.consentAction = actionKind || "trace";
    const modal = document.getElementById("trace-consent-modal");
    const argvJson = JSON.stringify(state.recommendedArgv);
    document.getElementById("consent-argv-preview").textContent = argvJson;
    document.getElementById("consent-argv-input").value = argvJson;
    document.getElementById("consent-modal-error").hidden = true;
    modal.hidden = false;
  }
  function closeConsentModal() { document.getElementById("trace-consent-modal").hidden = true; }
  async function confirmConsentExecution() {
    const errEl = document.getElementById("consent-modal-error");
    let parsedArgv = null;
    try {
      parsedArgv = JSON.parse(document.getElementById("consent-argv-input").value);
      if (!Array.isArray(parsedArgv) || parsedArgv.length === 0) throw new Error("argv must be a non-empty JSON array");
    } catch (e) { errEl.hidden = false; errEl.textContent = "Invalid argv JSON array: " + e.message; return; }
    const opName = state.consentAction === "profile" ? "v4_profile_lit" : "v4_trace";
    const res = await postAnvil(opName, { argv: parsedArgv, operator_consent_confirmed: true }, document.getElementById("btn-confirm-trace-consent"));
    if (res && (res.ok || (res.data && res.data.surface_state))) {
      closeConsentModal(); hydrateFromServerPayload(res.data, res.status, false); renderAll();
    } else {
      errEl.hidden = false; errEl.textContent = (res && res.data && (res.data.error || res.data.message)) || "Execution refused.";
    }
  }

  function renderAll() { renderTopDeckAndBanner(); renderLeftPane(); renderFullIdePane(); renderInspector(); renderChatMessages(); }

  function returnFromAnvilWorkbench() {
    if (window.parent && window.parent !== window) {
      try { window.parent.postMessage({ type: "anvil-return-cockpit" }, window.location.origin); window.parent.postMessage({ type: "anchor-overlay-close", closeTile: true, source: "anvil" }, window.location.origin); } catch (_e) {}
    } else { const qs = params.toString(); window.location.href = qs ? ("/steward?" + qs) : "/high-seat"; }
  }
  document.getElementById("btnReturnCockpit").addEventListener("click", returnFromAnvilWorkbench);
  const btnCloseX = document.getElementById("btnCloseWorkbenchX");
  if (btnCloseX) btnCloseX.addEventListener("click", returnFromAnvilWorkbench);
  document.getElementById("btnOpenAegisWorkbench").addEventListener("click", function () {
    if (window.parent && window.parent !== window) window.parent.postMessage({ type: "anvil-open-aegis" }, window.location.origin);
    else window.location.href = "/steward-static/aegis.html?" + params.toString();
  });
  const switcherDom = document.getElementById("analysisSwitcherSelect");
  if (switcherDom) switcherDom.addEventListener("change", function () { if (switcherDom.value) switchActiveAnalysis(switcherDom.value); });
  document.getElementById("btnNewAnvilAnalysis").addEventListener("click", async function () {
    if (!state.multiAnalysisEnabled && !state.anvilV6Enabled) return;
    state.intakeMode = "new"; state.intakeFormInitialized = false; state.scopeDrifted = false; state.scopingSelectedModuleIds = null; state.launcherOpen = true;
    renderAll(); if (state.anvilV6Enabled) { await fetchScopingV2State(null); renderAll(); }
  });
  document.getElementById("btnOpenLauncherDrawer").addEventListener("click", async function () {
    if (state.launcherOpen && state.intakeMode !== "new") state.launcherOpen = false;
    else { state.intakeMode = state.active ? "edit" : "initial"; state.intakeFormInitialized = false; state.launcherOpen = true; if (state.anvilV6Enabled) await fetchScopingV2State(state.scopingSelectedModuleIds); }
    renderAll();
  });
  const closeDrw = document.getElementById("btnCloseLauncherDrawer"), btnBootRetry = document.getElementById("btnBootErrorRetry"), btnMinChat = document.getElementById("btnMinimizeCopilot");
  if (closeDrw) closeDrw.addEventListener("click", function () { state.launcherOpen = false; renderAll(); });
  if (btnBootRetry) btnBootRetry.addEventListener("click", function () { fetchFullState(false); });
  if (btnMinChat) btnMinChat.addEventListener("click", function () { state.copilotMinimized = !state.copilotMinimized; renderChatMessages(); });
  const btnSem = document.getElementById("btnRunSemanticPass"), btnCancelSem = document.getElementById("btnCancelSemanticConsent"), btnConfirmSem = document.getElementById("btnConfirmSemanticConsent");
  if (btnSem) btnSem.addEventListener("click", function () { triggerSemanticComprehensionRun(btnSem); });
  if (btnCancelSem) btnCancelSem.addEventListener("click", function () { document.getElementById("semantic-consent-modal").hidden = true; });
  if (btnConfirmSem) btnConfirmSem.addEventListener("click", function () { confirmSemanticConsentRun(btnConfirmSem); });
  const intakeDirDom = document.getElementById("intakeDirectionInput");
  if (intakeDirDom) intakeDirDom.addEventListener("input", function () {
    const rawTxt = intakeDirDom.value || "", cnt = document.getElementById("intakeDirectionByteCounter"), errBox = document.getElementById("intakeDirectionError");
    if (cnt && v5) cnt.textContent = v5.utf8ByteLength(rawTxt) + " / 16,384 B";
    if (errBox && v5) { const chk = v5.validateDirectionPayload(rawTxt, { max_concurrency: Number((document.getElementById("intakeMaxConcurrency") && document.getElementById("intakeMaxConcurrency").value) || 2) }); errBox.hidden = chk.ok; errBox.textContent = chk.ok ? "" : chk.message; }
  });
  async function submitLegacyIntake(btn) {
    const sw = (document.getElementById("inputSoftwareTarget") && document.getElementById("inputSoftwareTarget").value || ".").trim(), pp = (document.getElementById("inputPaperTarget") && document.getElementById("inputPaperTarget").value || "").trim();
    const titleV = (document.getElementById("inputAnalysisTitle") && document.getElementById("inputAnalysisTitle").value || "").trim(), dirV = (document.getElementById("intakeDirectionInput") && document.getElementById("intakeDirectionInput").value) || "";
    const rDom = document.getElementById("intakeReplicationPkgToggle"), matRep = rDom ? Boolean(rDom.checked) : true, mc = Number((document.getElementById("intakeMaxConcurrency") && document.getElementById("intakeMaxConcurrency").value) || 2), errBox = document.getElementById("intakeDirectionError");
    const sub = v5.buildGuidedIntakeSubmission({ title: titleV, software_target: sw, paper_target: pp, direction: dirV, materialize_replication_package: matRep, selected_pipelines: state.formSelectedPipelines || [], max_concurrency: mc }, { createNew: state.intakeMode === "new", multiAnalysisEnabled: state.multiAnalysisEnabled, editExisting: state.intakeMode === "edit" && state.active, activeAnalysisId: state.activeAnalysisId });
    if (!sub.ok) { if (errBox) { errBox.hidden = false; errBox.textContent = sub.message; } return; }
    const res = await postAnvil(sub.action, sub.payload, btn);
    if (res && res.ok && res.data) { state.launcherOpen = false; state.intakeMode = "edit"; state.intakeFormInitialized = false; hydrateFromServerPayload(res.data, res.status, true); renderAll(); }
  }
  ["btnSubmitGuidedIntake", "btnStartCode", "btnStartPaper", "btnStartWalkthrough"].forEach(function (id) { const el = document.getElementById(id); if (el) el.addEventListener("click", function () { submitLegacyIntake(el); }); });
  document.querySelectorAll(".lens-tab").forEach(function (btn) { btn.addEventListener("click", function () { state.lens = btn.getAttribute("data-lens") || "understand"; state.inspectorTab = state.lens === "debug" ? "funnel" : "story"; renderAll(); }); });
  document.querySelectorAll("[data-prog-level]").forEach(function (btn) { btn.addEventListener("click", function () { state.progLevel = Number(btn.getAttribute("data-prog-level") || 1); state.ideOpen = (state.progLevel === 3); persistSessionState(); renderAll(); }); });
  document.querySelectorAll(".insp-tab").forEach(function (btn) { btn.addEventListener("click", function () { state.inspectorTab = btn.getAttribute("data-inspector") || "story"; renderInspector(); }); });

  document.getElementById("btn-open-ide-debugger").addEventListener("click", function () { state.ideOpen = !state.ideOpen; state.progLevel = state.ideOpen ? 3 : 1; persistSessionState(); renderAll(); });
  document.getElementById("btn-rail-back").addEventListener("click", function () { state.ideOpen = false; state.progLevel = 1; persistSessionState(); renderAll(); });
  document.getElementById("btn-close-full-ide").addEventListener("click", function () { state.ideOpen = false; state.progLevel = 1; persistSessionState(); renderAll(); });
  document.getElementById("btn-ide-theme").addEventListener("click", function () { state.ideTheme = state.ideTheme === "dark" ? "light" : "dark"; persistSessionState(); renderFullIdePane(); });
  document.getElementById("btn-top-xval").addEventListener("click", function () { state.ideOpen = false; state.inspectorTab = "xval"; renderAll(); });
  document.getElementById("btn-run-trace").addEventListener("click", function () { openConsentModal("trace"); });
  document.getElementById("btn-cancel-trace-consent").addEventListener("click", closeConsentModal);
  document.getElementById("btn-confirm-trace-consent").addEventListener("click", confirmConsentExecution);
  document.getElementById("btn-retry-state").addEventListener("click", function () { fetchFullState(false); });
  document.getElementById("btnToggleDialogueSurface").addEventListener("click", function () { state.useLiveCockpitTile = !state.useLiveCockpitTile; renderChatMessages(); });

  document.getElementById("btn-chat-send").addEventListener("click", function () {
    const inp = document.getElementById("chat-input");
    if ((inp.value || "").trim()) { const t = inp.value; inp.value = ""; submitChatQuestion(t); }
  });
  document.getElementById("chat-input").addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); document.getElementById("btn-chat-send").click(); } });

  document.querySelectorAll("[data-chat-intent]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      const intent = chip.getAttribute("data-chat-intent");
      if (intent === "debug_inf") { state.ideOpen = true; state.funnelStage = "anomalies"; renderAll(); }
      else if (intent === "refactor_rec") { state.ideOpen = false; state.lens = "refactor"; state.inspectorTab = "story"; renderAll(); }
      else if (intent === "show_xval") { state.ideOpen = false; state.inspectorTab = "xval"; renderAll(); }
      else submitChatQuestion("Explain causal triptych and I/O contract of " + state.activeStageId + ".");
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.isComposing || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target && e.target.tagName) ? e.target.tagName.toUpperCase() : "";
    const inEditable = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || Boolean(e.target && e.target.isContentEditable);
    if (e.key === "Escape") {
      const semModal = document.getElementById("semantic-consent-modal");
      if (semModal && !semModal.hidden) { semModal.hidden = true; return; }
      const litModal = document.getElementById("literature-consent-modal");
      if (litModal && !litModal.hidden) { litModal.hidden = true; return; }
      const repModal = document.getElementById("replication-consent-modal");
      if (repModal && !repModal.hidden) { if (v6Ctrl && v6Ctrl.closeReplicationConsentModal) v6Ctrl.closeReplicationConsentModal(); else repModal.hidden = true; return; }
      const trModal = document.getElementById("trace-consent-modal");
      if (trModal && !trModal.hidden) { closeConsentModal(); return; }
      if (state.launcherOpen && state.active) { state.launcherOpen = false; renderAll(); return; }
      if (state.ideOpen) { state.ideOpen = false; state.progLevel = 1; persistSessionState(); renderAll(); return; }
      return;
    }
    if (inEditable || !state.active || state.launcherOpen || state.replicationViewOpen) return;
    if (e.key === "j" || e.key === "k") {
      const stages = getStages();
      if (stages.length > 1) {
        const curIdx = Math.max(0, stages.findIndex(function (s) { return s.id === state.activeStageId; }));
        const nextIdx = e.key === "j" ? ((curIdx + 1) % stages.length) : ((curIdx - 1 + stages.length) % stages.length);
        selectStage(stages[nextIdx].id);
      }
    } else if (e.key === "Enter" && tag === "BODY") {
      state.ideOpen = !state.ideOpen; state.progLevel = state.ideOpen ? 3 : 1; persistSessionState(); renderAll();
    }
  });

  window.addEventListener("pagehide", function () { clearScheduledSync(); abortActivePoll(); abortWarmPrefetch(); stopReplicationPolling(); });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "visible") { clearScheduledSync(); abortActivePoll(); abortWarmPrefetch(); window.__anvilSyncStats.pausedForVisibility = true; }
    else { window.__anvilSyncStats.pausedForVisibility = false; if (state.bootPending || state.bootNeedsInitialFetch) fetchFullState(true); else pollSummaryGate(); }
  });

  const v6Ctrl = window.AnvilV6Runtime ? window.AnvilV6Runtime.mountV6SurfaceControllers({
    state: state, SURFACE_FAILURE_ROWS: SURFACE_FAILURE_ROWS, apiUrl: apiUrl, headers: headers,
    recordAnvilRequest: recordAnvilRequest, postAnvil: postAnvil, hydrateFromServerPayload: hydrateFromServerPayload,
    renderTopDeckAndBanner: renderTopDeckAndBanner, renderAll: renderAll, switchActiveAnalysis: switchActiveAnalysis
  }) : null;

  async function fetchScopingV2State(m) { if (v6Ctrl && v6Ctrl.fetchScopingV2State) await v6Ctrl.fetchScopingV2State(m); }
  function renderScopingV2Surface() { if (v6Ctrl && v6Ctrl.renderScopingV2Surface) v6Ctrl.renderScopingV2Surface(); }
  function stopReplicationPolling() { if (v6Ctrl && v6Ctrl.stopReplicationPolling) v6Ctrl.stopReplicationPolling(); }
  async function fetchReplicationState(a) { if (v6Ctrl && v6Ctrl.fetchReplicationState) await v6Ctrl.fetchReplicationState(a); }
  function renderReplicationV2Surface() { if (v6Ctrl && v6Ctrl.renderReplicationV2Surface) v6Ctrl.renderReplicationV2Surface(); }

  renderAll();
  fetchFullState(true);
})();
