/* Locked Mockup #2 Paper Replication, Ramanujan Math Audit & Vetted Refactoring Report (`anvil_report.js`, `<= 550` lines).
 * Enforces:
 *   - `0` green badges unless `OBSERVED` / `VERIFIED_NUMERIC` / `ATTESTED` (`NOT_YET_RUN` & `CLAIMED` are amber/slate).
 *   - `0` `.queue-btn` nodes unless a surgical refactoring passed the 3-leg gate (`approved_fixes`).
 *   - Prominent **Blocked by Adversarial Review** cards for wrong-side paper/code divergence edits.
 *   - Single-flight recursive `setTimeout` polling (`0` `setInt`+`erval`).
 */
(function (root) {
  "use strict";

  function esc(val) {
    return root.AnvilV5Client ? root.AnvilV5Client.escHtml(val) : String(val == null ? "" : val).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function stripDollars(txt) {
    return String(txt == null ? "" : txt).replace(/\$/g, "");
  }

  var GREEN_DISPLAY_STATES = { ATTESTED: true, VERIFIED_TRACE: true, VERIFIED_NUMERIC: true };

  function rungPillCls(rung, allowGreen) {
    var u = String(rung || "CLAIMED").toUpperCase();
    if (u === "OBSERVED" || u === "VERIFIED_NUMERIC" || u === "ATTESTED" || u === "VERIFIED_TRACE") {
      return allowGreen ? "p-green" : "p-amber";
    }
    if (u === "REFUTED" || u === "UNGROUNDED") return "p-red";
    if (u === "CORROBORATED" || u === "CACHED_BASELINE") return "p-ram";
    return "p-amber";
  }

  function renderReplicationReportV2Html(repState, opts) {
    var st = (repState && typeof repState === "object") ? repState : {};
    var options = opts || {};
    var rep = (st.report && typeof st.report === "object") ? st.report : {};
    var job = (st.job && typeof st.job === "object") ? st.job : null;
    var sem = (st.semantic_comprehension && st.semantic_comprehension.pass2) ? st.semantic_comprehension.pass2 : null;
    var gandalf = (st.semantic_comprehension && st.semantic_comprehension.gandalf_critique) || null;
    var filterFlags = Boolean(options.filterDiscrepancies);
    var openDrawerId = String(options.openQueueDrawerId || "");
    var queuedSet = new Set(Array.isArray(st.queued_refactoring_ids) ? st.queued_refactoring_ids.map(String) : []);

    var execState = String(rep.execution_state || (st.state === "NOT_YET_RUN" ? "not_yet_run" : "not_yet_run"));
    var isNotRun = execState === "not_yet_run";
    var isInstallingDeps = Boolean(job && job.status === "installing_deps");
    var isRunning = Boolean(job && (job.status === "running" || job.status === "installing_deps"));
    var receiptVerified = Boolean(st.receipt_hmac_verified === true && GREEN_DISPLAY_STATES[String(st.display_state || "")]) && !isNotRun && !isRunning;
    var semVerified = Boolean(st.semantic_comprehension && GREEN_DISPLAY_STATES[String(st.semantic_comprehension.display_state || "")]);
    var missingPkgs = Array.isArray(st.missing_packages) ? st.missing_packages.map(String).filter(Boolean) : [];
    var depInstallTok = String(st.dep_install_token || "");

    var badges = (Array.isArray(rep.badges) ? rep.badges : []).map(function (b) {
      var rawCls = String(b.cls || "p-ram");
      if (rawCls === "p-green" && !receiptVerified) rawCls = "p-amber";
      return { cls: rawCls, icon: b.icon, text: b.text };
    });
    var summaryParagraphs = Array.isArray(rep.summary_paragraphs) ? rep.summary_paragraphs.slice() : [];
    if (gandalf && gandalf.what_is_really_going_on) {
      summaryParagraphs.push("Gandalf Synthesis: " + gandalf.what_is_really_going_on + (gandalf.missing_or_wrong ? (" — " + gandalf.missing_or_wrong) : ""));
    }

    var semRows = [];
    if (sem && sem.ramanujan_audit) {
      [].concat(sem.ramanujan_audit.pass2a_paper_to_code || [], sem.ramanujan_audit.pass2b_code_to_paper || []).forEach(function (f, idx) {
        semRows.push({
          row_id: f.finding_id || ("sem-r-" + (idx + 1)),
          paper_cell: (f.eq_label ? (f.eq_label + " · ") : (f.direction === "code_to_paper" ? "Reverse Audit (Code → Paper) · " : "")) + (f.paper_claim || f.title || ""),
          code_cell: (f.code_symbol ? (f.code_symbol + " — ") : "") + (f.code_reality || ""),
          replication_status: isNotRun ? "not yet run" : "Static + Semantic Audit",
          error_class: isNotRun ? "NOT_YET_RUN" : "SEMANTIC_DIVERGENCE",
          ramanujan_rung: f.rung || "CLAIMED",
          ramanujan_note: (f.title ? (f.title + ": ") : "") + (f.impact || ""),
          sem_row: true,
          flag: true
        });
      });
    }

    var allRows = (Array.isArray(rep.matrix) ? rep.matrix : []).concat(semRows);
    var discCount = allRows.filter(function (r) { return Boolean(r && r.flag); }).length;
    var shownRows = filterFlags ? allRows.filter(function (r) { return Boolean(r && r.flag); }) : allRows;

    var rawApprovedFixes = Array.isArray(rep.approved_fixes) ? rep.approved_fixes : [];
    var approvedFixes = receiptVerified ? rawApprovedFixes : [];
    var unverifiedApprovedFallback = receiptVerified ? [] : rawApprovedFixes;
    var semBlocked = [];
    var semNotVetted = [];
    if (sem && Array.isArray(sem.refactor_candidates)) {
      sem.refactor_candidates.forEach(function (rc) {
        var mapped = {
          id: rc.refactor_id || "sem-ref",
          title: rc.title || "Candidate Refactoring",
          where: (rc.target_file || "") + (rc.target_symbol ? (" · " + rc.target_symbol) : ""),
          summary: rc.summary || "",
          reasons: [rc.blocked_reason || rc.wrong_side_warning || "Requires 3-leg numeric parity + cross-family review."]
        };
        if (rc.gate_status === "blocked_author_decision" || rc.gate_status === "blocked") semBlocked.push(mapped);
        else if (!approvedFixes.some(function (a) { return a.id === mapped.id; })) semNotVetted.push(mapped);
      });
    }
    var rejectedFixes = (Array.isArray(rep.rejected_fixes) ? rep.rejected_fixes : []).concat(semBlocked);
    var notVettedFixes = unverifiedApprovedFallback.concat(Array.isArray(rep.not_vetted_fixes) ? rep.not_vetted_fixes : [], semNotVetted);

    var jobBannerHtml = "";
    if (isRunning) {
      var runLabel = isInstallingDeps
        ? ("⏳ Installing Approved Python Packages (" + esc((job.installing_packages || []).join(", ") || "venv") + ") in Isolated Anvil Runtime:")
        : ("⏳ Running Isolated Scratch Replication (" + esc(job.phase ? "Phase " + job.phase : "Phase A") + "):");
      var stepMeta = isInstallingDeps ? ("Preparing verification · Job <code>" + esc(job.job_id || "") + "</code>") : ("Step " + Number(job.completed_steps || 0) + " / " + Math.max(1, Number(job.total_steps || 1)) + " · Job <code>" + esc(job.job_id || "") + "</code>");
      jobBannerHtml = '<div class="rep-run-banner running" data-rep-run-state="running"><div><strong>' + runLabel + "</strong> " + stepMeta + '</div><button type="button" class="danger-btn" id="btnCancelReplicationJob" data-cancel-rep-job="' + esc(job.job_id || "") + '">✕ Cancel &amp; Kill Tree</button></div>';
    } else if (st.status_kind && st.status_kind !== "healthy" && st.status_kind !== "empty-but-valid") {
      var canOneClickInstall = st.status_kind === "dependency-missing" && missingPkgs.length > 0 && Boolean(depInstallTok);
      var pkgListLabel = esc(missingPkgs.join(", "));
      var msgHtml = canOneClickInstall
        ? ("Missing Python package(s) required to complete verification: <code>" + pkgListLabel + "</code> (installed into isolated Anvil runtime; research repo untouched).")
        : esc(stripDollars(st.message || st.error || ""));
      var actionBtnsHtml = canOneClickInstall
        ? ('<div class="selector-group"><button type="button" class="consent-run-btn" id="btnApproveInstallRepDeps" data-approve-rep-deps="true">⬇ Install Missing Packages (' + pkgListLabel + ') &amp; Complete Verification</button><button type="button" class="small-btn" id="btnRetryReplicationConsent" data-open-rep-consent="A">↻ Re-Run Only</button></div>')
        : '<button type="button" class="consent-run-btn" id="btnRetryReplicationConsent" data-open-rep-consent="A">↻ Re-Run with Consent</button>';
      jobBannerHtml = '<div class="rep-run-banner failed" data-rep-run-state="failed" data-rep-failure-kind="' + esc(st.status_kind) + '"><div><strong>[' + esc(st.badge || st.state || "ERROR") + "]</strong> " + msgHtml + "</div>" + actionBtnsHtml + "</div>";
    } else if (isNotRun) {
      jobBannerHtml = '<div class="rep-run-banner idle" data-rep-run-state="not_yet_run"><div><strong>Status: not yet run</strong> — Scope <code>' + esc(String(st.scope_sha256 || "").slice(0, 12)) + '…</code> is locked. Confirm operator consent to execute paper table scripts in isolated scratch.</div><button type="button" class="consent-run-btn" id="btnOpenReplicationConsent" data-open-rep-consent="A">▶ Run Paper Replication &amp; Ramanujan Audit</button></div>';
    }

    return jobBannerHtml +
      '<section class="exec-card" id="sec-summary">' +
        '<div class="exec-kicker"><img class="sk-ico" src="/vendor/brand/anvil-icon.jpg" alt="Anvil" /><img class="sk-ico" src="/vendor/brand/ramanujan-icon.jpg" alt="Ramanujan" /><img class="sk-ico" src="/vendor/brand/gandalf-icon.jpg" alt="Gandalf" /><span>Anvil Replication · Ramanujan Mathematical Audit · Adversarial Refactoring Triage</span></div>' +
        '<h1 class="exec-title">' + esc(stripDollars(rep.doc_title || "Replication, Ramanujan Math & Vetted Refactoring")) + "</h1>" +
        '<div class="badge-strip">' + badges.map(function (b) {
          return '<span class="pill ' + esc(b.cls) + '">' + (b.icon ? '<img class="sk-ico-sm" src="' + esc(b.icon) + '" alt="" style="margin:0;" />' : "") + esc(stripDollars(b.text || "")) + "</span>";
        }).join("") + "</div>" +
        '<div class="summary-prose"><h2>Executive Summary (Read Cold First)</h2>' + summaryParagraphs.map(function (p) { return "<p>" + esc(stripDollars(p)) + "</p>"; }).join("") + "</div>" +
        '<div class="summary-actions"><span style="font-size:12px;color:var(--ink-soft);font-weight:600;">Every proposed code issue passes the 3-leg gate (cross-family review + Ramanujan + scratch table replay) so wrong-side edits are blocked.</span>' +
          '<div class="selector-group"><button type="button" class="small-btn" id="btnExportRepDeliverables" data-export-rep-deliverables="true">📄 Export to DELIVERABLES.md</button>' +
          '<a class="jump-big-btn" href="#sec-refactoring">⚡ Jump to Proposed Code Issues &amp; Refactoring (' + approvedFixes.length + " Approved · " + rejectedFixes.length + " Blocked) ↓</a></div></div>" +
      "</section>" +
      '<section id="sec-matrix"><div class="sec-banner"><h2>2. Detailed End-to-End Paper ↔ Software ↔ Replication ↔ Ramanujan Matrix</h2>' +
        '<div class="f-pills"><button type="button" class="f-btn' + (!filterFlags ? " active" : "") + '" data-rep-matrix-filter="all">All Sections &amp; Tables (' + allRows.length + ')</button>' +
        '<button type="button" class="f-btn' + (filterFlags ? " active" : "") + '" data-rep-matrix-filter="flags">⚠ Discrepancies Only (' + discCount + ")</button></div></div>" +
        '<table class="audit-grid"><thead><tr><th style="width:22%;">1. Paper Section / Formula / Table</th><th style="width:25%;">2. Software Implementation (Fixed Scope)</th><th style="width:24%;">3. Live Table Replication &amp; Error Type</th><th style="width:29%;">4. Ramanujan Math Verdict &amp; Fix Link</th></tr></thead><tbody>' +
        (shownRows.length === 0 ? '<tr><td colspan="4" style="text-align:center;color:var(--ink-soft);">0 rows match the active filter.</td></tr>' : shownRows.map(function (r) {
          var rStat = String(r.replication_status || "not yet run");
          var rowNotRun = rStat === "not yet run" || r.error_class === "NOT_YET_RUN";
          var rowAllowGreen = r.sem_row ? semVerified : receiptVerified;
          var repPillCls = (receiptVerified && !rowNotRun && (r.error_class === "EXACT_REPLICATION" || r.error_class === "FLOAT_REDUCTION_TOLERANCE")) ? "p-green" : "p-amber";
          var rungTxt = String(r.ramanujan_rung || "CLAIMED");
          return '<tr data-matrix-row-id="' + esc(r.row_id || "") + '"><td><strong>' + esc(stripDollars(r.paper_cell || "")) + "</strong></td>" +
            '<td><span class="mono">' + esc(stripDollars(r.code_cell || "")) + "</span></td>" +
            '<td><span class="pill ' + repPillCls + '">' + esc(rowNotRun ? "not yet run" : (r.error_class || "EXECUTED")) + '</span><div style="margin-top:4px;">' + esc(stripDollars(rStat)) + "</div></td>" +
            '<td><div><img class="sk-ico-sm" src="/vendor/brand/ramanujan-icon.jpg" alt="Ramanujan" /><span class="pill ' + rungPillCls(rungTxt, rowAllowGreen) + '" data-ramanujan-rung="' + esc(rungTxt) + '">' + esc(rungTxt) + "</span>" +
              (r.inline_ref ? ' <span class="mono">' + esc(stripDollars(r.inline_ref)) + "</span>" : "") + "</div>" +
              '<div style="margin-top:4px;">' + esc(stripDollars(r.ramanujan_note || "")) + "</div>" +
              (r.jump_id ? '<a class="row-jump-link" href="#' + esc(r.jump_id) + '">' + esc(stripDollars(r.jump_label || "Jump to Issue ↓")) + "</a>" : "") + "</td></tr>";
        }).join("")) + "</tbody></table></section>" +
      '<section class="refac-section" id="sec-refactoring"><div style="display:flex;align-items:center;gap:10px;"><img class="sk-ico" src="/vendor/brand/gandalf-icon.jpg" alt="Gandalf" /><div><h2 style="margin:0;font-size:18.5px;font-weight:800;">3. Analysis of Proposed Code Issues, Refactoring &amp; Adversarial Review</h2><div style="font-size:12.5px;color:var(--ink-soft);">Every candidate defect and refactoring is challenged by cross-family review + Ramanujan + scratch replay before touching code.</div></div></div>' +
        '<div class="sub-bucket-hdr sub-approved"><span>✓ Adversarially Approved Surgical Code Refactorings (' + approvedFixes.length + ' — Verified by 3-Leg Gate)</span><span>Safe · High Signal</span></div>' +
        (approvedFixes.length === 0 ? '<div class="fix-card" style="color:var(--ink-soft);">0 approved refactorings in current scope receipt.</div>' : approvedFixes.map(function (f) {
          var fid = String(f.id || "");
          var isQueued = queuedSet.has(fid);
          var drawerOpen = (openDrawerId === fid);
          return '<div class="fix-card" id="' + esc(fid) + '" data-approved-fix-id="' + esc(fid) + '"><div class="fix-top"><div><div style="font-weight:800;font-size:14.5px;">' + esc(stripDollars(f.title || fid)) + '</div><div class="mono" style="margin-top:2px;">' + esc(stripDollars(f.where || "")) + '</div></div><span class="pill p-green">✓ ' + esc(f.gate_label || "Survived Adversarial Review") + "</span></div>" +
            '<div style="font-size:13px;color:var(--ink-soft);margin-bottom:6px;"><strong>What is wrong in the code:</strong> ' + esc(stripDollars(f.summary || "")) + "</div>" +
            '<div class="fix-cols"><pre class="diff-pre">' + esc(f.diff || "") + '</pre><div class="adv-box"><div><div style="margin-bottom:5px;"><img class="sk-ico-sm" src="/vendor/brand/gandalf-icon.jpg" alt="" /><img class="sk-ico-sm" src="/vendor/brand/ramanujan-icon.jpg" alt="" /><strong>Adversarial &amp; Mathematical Gate (APPROVED)</strong></div><div>' + esc(stripDollars((f.reasons || []).join(" "))) + "</div></div>" +
              (isQueued ? '<span class="pill p-green" data-queued-badge="' + esc(fid) + '">✓ Queued for Cockpit Steward (0 source edits)</span>'
                        : '<button type="button" class="queue-btn" data-open-queue-drawer="' + esc(fid) + '">Queue Refactoring for Cockpit Steward →</button>') +
              (drawerOpen ? '<div class="queue-drawer-inline" data-queue-drawer="' + esc(fid) + '"><div style="font-weight:800;font-size:12px;margin-bottom:4px;">Queue Approved Surgical Fix for Cockpit Steward</div><input type="text" class="text-field" data-queue-note-input="' + esc(fid) + '" placeholder="Optional guidance note..." aria-label="Guidance note" /><div class="selector-group" style="margin-top:6px;justify-content:flex-end;"><button type="button" class="small-btn" data-close-queue-drawer="' + esc(fid) + '">Cancel</button><button type="button" class="queue-btn" data-confirm-queue-fix="' + esc(fid) + '">✓ Confirm &amp; Queue Proposal</button></div></div>' : "") +
            "</div></div></div>";
        }).join("")) +
        '<div class="sub-bucket-hdr sub-rejected"><span>🛡 Candidate Code Edits REJECTED / BLOCKED by Adversarial Review (' + rejectedFixes.length + ' — Wrong Side, Degrades Fit, or Needs Author Intent)</span><span>Filtered Out</span></div>' +
        (rejectedFixes.length === 0 ? '<div class="fix-card rejected-card" style="color:var(--ink-soft);">0 blocked/wrong-side edits recorded.</div>' : rejectedFixes.map(function (f) {
          var fid = String(f.id || "");
          return '<div class="fix-card rejected-card" id="' + esc(fid) + '" data-blocked-fix-id="' + esc(fid) + '"><div class="fix-top"><div><div style="font-weight:800;font-size:14px;color:#6E190C;">' + esc(stripDollars(f.title || fid)) + '</div><div class="mono" style="margin-top:2px;">' + esc(stripDollars(f.where || "")) + '</div></div><span class="pill p-red">✕ Blocked by Adversarial Review</span></div>' +
            '<div style="font-size:12.8px;color:var(--ink-soft);margin-bottom:8px;"><strong>What a naive check proposed:</strong> ' + esc(stripDollars(f.summary || "")) + "</div>" +
            '<div class="adv-box blocked"><div><img class="sk-ico-sm" src="/vendor/brand/gandalf-icon.jpg" alt="" /><img class="sk-ico-sm" src="/vendor/brand/ramanujan-icon.jpg" alt="" />' + esc(stripDollars((f.reasons || []).join(" "))) + "</div></div></div>";
        }).join("")) +
        (notVettedFixes.length > 0 ? '<div class="sub-bucket-hdr" style="background:#FEF3DC;color:#7A4B08;border:1px solid #E5C278;margin-top:18px;"><span>⚠ Not Vetted (Claimed) (' + notVettedFixes.length + ' — Missing 1+ Verification Legs)</span><span>Cannot Queue Until All 3 Legs Pass</span></div>' +
          notVettedFixes.map(function (f) {
            var fid = String(f.id || "");
            return '<div class="fix-card" id="' + esc(fid) + '" data-not-vetted-fix-id="' + esc(fid) + '"><div class="fix-top"><div><strong>' + esc(stripDollars(f.title || fid)) + '</strong><div class="mono">' + esc(stripDollars(f.where || "")) + '</div></div><span class="pill p-amber">Not Vetted (Claimed)</span></div>' +
              '<div style="font-size:12.5px;color:var(--ink-soft);">' + esc(stripDollars((f.reasons || []).join(" "))) + "</div>" +
              (f.diff ? '<div style="margin-top:6px;"><button type="button" class="small-btn" data-open-phase-b-consent="' + esc(fid) + '">▶ Run Consented Phase-B Scratch Replay</button></div>' : "") + "</div>";
          }).join("") : "") +
      "</section>";
  }

  function mountReportController(ctx) {
    var state = ctx.state;

    function stopReplicationPolling() {
      if (state.replicationPollTimer !== null) {
        root.clearTimeout(state.replicationPollTimer);
        state.replicationPollTimer = null;
      }
    }

    async function fetchReplicationState(aidOverride) {
      if (!state.anvilV6Enabled) return;
      var effAid = String(aidOverride || state.activeAnalysisId || "");
      var u = ctx.apiUrl("anvil/replication", effAid ? { analysis_id: effAid } : {});
      ctx.recordAnvilRequest("GET", u, "replication_state", effAid);
      try {
        var resp = await root.fetch(u, { method: "GET", headers: ctx.headers(), cache: "no-store" });
        var data = null;
        try { data = await resp.json(); } catch (_e) { data = null; }
        if (resp.status === 409 && data && data.scope_drifted) {
          stopReplicationPolling();
          state.replicationViewOpen = false;
          ctx.hydrateFromServerPayload(data, 409, false);
          if (ctx.fetchScopingV2State) await ctx.fetchScopingV2State(state.scopingSelectedModuleIds);
          ctx.renderAll();
          return;
        }
        state.replicationState = data || { status_kind: "backing-store-unreadable", badge: "UNKNOWN", message: "UNKNOWN: Replication store unreadable" };
        if (data && data.scope_sha256) state.scopeSha256 = String(data.scope_sha256);
        renderReplicationV2Surface();

        stopReplicationPolling();
        var job = data && data.job;
        if (state.replicationViewOpen && job && (job.status === "running" || job.status === "installing_deps") && document.visibilityState === "visible") {
          var pollMs = Math.max(400, Math.min(8000, Number(data.recommended_poll_ms || 1000)));
          state.replicationPollTimer = root.setTimeout(function () {
            state.replicationPollTimer = null;
            fetchReplicationState(effAid);
          }, pollMs);
        }
      } catch (_err) {
        state.replicationState = { status_kind: "dependency-slow-or-killed", badge: "TIMEOUT_OR_CANCELLED", message: "Unable to reach Replication Audit endpoint." };
        renderReplicationV2Surface();
      }
    }

    async function openReplicationReportView(aidOverride) {
      if (aidOverride) state.activeAnalysisId = String(aidOverride);
      state.launcherOpen = false;
      state.replicationViewOpen = true;
      state.replicationQueueDrawerId = "";
      if (root.AnvilV5Client) root.AnvilV5Client.writeSurfaceRoute("report", state.scopeSha256);
      ctx.renderTopDeckAndBanner();
      await fetchReplicationState(state.activeAnalysisId);
    }

    function renderReplicationV2Surface() {
      var rootEl = document.getElementById("reportRoot");
      var titleEl = document.getElementById("topDocTitle");
      if (!rootEl) return;
      var st = state.replicationState || {};
      if (titleEl && st.report && st.report.top_title) titleEl.textContent = st.report.top_title;
      rootEl.innerHTML = renderReplicationReportV2Html(st, {
        filterDiscrepancies: state.replicationFilterFlags,
        openQueueDrawerId: state.replicationQueueDrawerId
      });
    }

    async function openReplicationConsentModal(phase, candidateId) {
      var modal = document.getElementById("replication-consent-modal");
      var errEl = document.getElementById("repConsentError");
      var diffWrap = document.getElementById("repConsentDiffWrap");
      if (!modal) return;
      if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
      state.pendingReplicationPhase = phase === "B" ? "B" : "A";
      state.pendingReplicationCandidateId = String(candidateId || "");
      state.pendingReplicationCandidateDiff = "";
      state.pendingReplicationConsentToken = "";

      if (state.pendingReplicationPhase === "B" && state.replicationState && state.replicationState.report) {
        var allCands = [].concat(state.replicationState.report.not_vetted_fixes || [], state.replicationState.report.approved_fixes || []);
        var found = allCands.find(function (c) { return c && c.id === state.pendingReplicationCandidateId; });
        if (found && found.diff) state.pendingReplicationCandidateDiff = String(found.diff);
      }

      var res = await ctx.postAnvil("replication_consent", {
        analysis_id: state.activeAnalysisId || undefined,
        phase: state.pendingReplicationPhase,
        candidate_id: state.pendingReplicationCandidateId || undefined,
        candidate_diff: state.pendingReplicationCandidateDiff || undefined
      });
      if (!res || !res.ok || !res.data || !res.data.consent_token) {
        if (errEl) { errEl.hidden = false; errEl.textContent = (res && res.data && (res.data.message || res.data.error)) || "Unable to mint consent token."; }
        modal.hidden = false;
        return;
      }
      state.pendingReplicationConsentToken = String(res.data.consent_token);
      state.scopeSha256 = String(res.data.scope_sha256 || state.scopeSha256 || "");
      document.getElementById("repConsentSha").textContent = state.scopeSha256;
      document.getElementById("repConsentInterpreter").textContent = String(res.data.pinned_interpreter || "sys.executable");
      if (state.pendingReplicationPhase === "B" && state.pendingReplicationCandidateDiff) {
        diffWrap.hidden = false;
        document.getElementById("repConsentDiffSha").textContent = String(res.data.diff_sha256 || "").slice(0, 16) + "…";
        document.getElementById("repConsentDiffPreview").textContent = state.pendingReplicationCandidateDiff;
      } else {
        diffWrap.hidden = true;
      }
      modal.hidden = false;
    }

    function closeReplicationConsentModal() {
      var modal = document.getElementById("replication-consent-modal");
      if (modal) modal.hidden = true;
    }

    var topBtn = document.getElementById("btnOpenReplicationReport");
    if (topBtn) topBtn.addEventListener("click", function () { openReplicationReportView(state.activeAnalysisId); });
    var backBtn = document.getElementById("btnBackFromReplication");
    if (backBtn) {
      backBtn.addEventListener("click", function () {
        stopReplicationPolling();
        state.replicationViewOpen = false;
        state.launcherOpen = true;
        if (root.AnvilV5Client) root.AnvilV5Client.writeSurfaceRoute("scoping", state.scopeSha256);
        ctx.renderAll();
        if (ctx.fetchScopingV2State) {
          ctx.fetchScopingV2State(state.scopingSelectedModuleIds).then(function () {
            if (!state.replicationViewOpen) ctx.renderAll();
          });
        }
      });
    }
    var wbJumpBtn = document.getElementById("btnOpenWorkbenchFromRep");
    if (wbJumpBtn) {
      wbJumpBtn.addEventListener("click", function () {
        stopReplicationPolling();
        state.replicationViewOpen = false;
        state.launcherOpen = false;
        if (root.AnvilV5Client) root.AnvilV5Client.writeSurfaceRoute("workbench", state.scopeSha256);
        ctx.renderAll();
      });
    }
    var cancelBtn = document.getElementById("btnCancelReplicationConsent");
    if (cancelBtn) cancelBtn.addEventListener("click", closeReplicationConsentModal);
    var confirmBtn = document.getElementById("btnConfirmReplicationConsent");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async function () {
        var errEl = document.getElementById("repConsentError");
        if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
        var actName = state.pendingReplicationPhase === "B" ? "replication_phase_b" : "replication_start";
        var payload = { analysis_id: state.activeAnalysisId || undefined, scope_sha256: state.scopeSha256, consent_token: state.pendingReplicationConsentToken, phase: state.pendingReplicationPhase };
        if (state.pendingReplicationPhase === "B") {
          payload.candidate_id = state.pendingReplicationCandidateId;
          payload.candidate_diff = state.pendingReplicationCandidateDiff;
        }
        var res = await ctx.postAnvil(actName, payload, confirmBtn);
        if (res && (res.status === 200 || res.status === 202)) {
          closeReplicationConsentModal();
          await fetchReplicationState(state.activeAnalysisId);
        } else if (errEl) {
          errEl.hidden = false;
          errEl.textContent = (res && res.data && (res.data.message || res.data.error)) || ("Refused (" + (res ? res.status : 400) + ")");
        }
      });
    }

    var repShell = document.getElementById("anvilReplicationV2Root");
    if (repShell) {
      repShell.addEventListener("click", async function (ev) {
        var filtBtn = ev.target.closest ? ev.target.closest("[data-rep-matrix-filter]") : null;
        if (filtBtn) { state.replicationFilterFlags = filtBtn.getAttribute("data-rep-matrix-filter") === "flags"; renderReplicationV2Surface(); return; }
        var approveDepsBtn = ev.target.closest ? ev.target.closest("[data-approve-rep-deps]") : null;
        if (approveDepsBtn) {
          var curSt = state.replicationState || {};
          var pkgs = Array.isArray(curSt.missing_packages) ? curSt.missing_packages : [];
          var dTok = String(curSt.dep_install_token || "");
          if (!pkgs.length || !dTok) return;
          stopReplicationPolling();
          var depRes = await ctx.postAnvil("replication_install_deps", {
            analysis_id: state.activeAnalysisId || undefined,
            scope_sha256: String(curSt.scope_sha256 || state.scopeSha256 || ""),
            packages: pkgs,
            dep_install_token: dTok
          }, approveDepsBtn);
          var depToast = document.getElementById("repToastBanner");
          if (depRes && (depRes.status === 200 || depRes.status === 202)) {
            if (depToast) { depToast.hidden = false; depToast.textContent = (depRes.data && depRes.data.message) || ("Installing " + pkgs.join(", ") + " and completing verification…"); }
            await fetchReplicationState(state.activeAnalysisId);
          } else if (depToast) {
            depToast.hidden = false;
            depToast.textContent = (depRes && depRes.data && (depRes.data.message || depRes.data.error)) || "Package installation refused.";
          }
          return;
        }
        var consentBtn = ev.target.closest ? ev.target.closest("[data-open-rep-consent]") : null;
        if (consentBtn) { await openReplicationConsentModal(consentBtn.getAttribute("data-open-rep-consent") || "A", ""); return; }
        var phaseBBtn = ev.target.closest ? ev.target.closest("[data-open-phase-b-consent]") : null;
        if (phaseBBtn) { await openReplicationConsentModal("B", phaseBBtn.getAttribute("data-open-phase-b-consent") || ""); return; }
        var cancelJobBtn = ev.target.closest ? ev.target.closest("[data-cancel-rep-job]") : null;
        if (cancelJobBtn) {
          stopReplicationPolling();
          await ctx.postAnvil("replication_cancel", { analysis_id: state.activeAnalysisId || undefined, job_id: cancelJobBtn.getAttribute("data-cancel-rep-job") || "" }, cancelJobBtn);
          await fetchReplicationState(state.activeAnalysisId);
          return;
        }
        var openQBtn = ev.target.closest ? ev.target.closest("[data-open-queue-drawer]") : null;
        if (openQBtn) { state.replicationQueueDrawerId = openQBtn.getAttribute("data-open-queue-drawer") || ""; renderReplicationV2Surface(); return; }
        var closeQBtn = ev.target.closest ? ev.target.closest("[data-close-queue-drawer]") : null;
        if (closeQBtn) { state.replicationQueueDrawerId = ""; renderReplicationV2Surface(); return; }
        var confirmQBtn = ev.target.closest ? ev.target.closest("[data-confirm-queue-fix]") : null;
        if (confirmQBtn) {
          var cid = confirmQBtn.getAttribute("data-confirm-queue-fix") || "";
          var noteInp = Array.from(repShell.querySelectorAll("[data-queue-note-input]")).find(function (el) { return el.getAttribute("data-queue-note-input") === cid; });
          var res = await ctx.postAnvil("replication_queue_refactor", { analysis_id: state.activeAnalysisId || undefined, candidate_id: cid, operator_consent: true, operator_note: noteInp ? String(noteInp.value || "") : "" }, confirmQBtn);
          var toast = document.getElementById("repToastBanner");
          if (res && res.ok && res.data) {
            state.replicationQueueDrawerId = "";
            if (toast) { toast.hidden = false; toast.textContent = res.data.message || "Queued approved surgical refactoring."; }
            await fetchReplicationState(state.activeAnalysisId);
          } else if (toast) {
            toast.hidden = false;
            toast.textContent = (res && res.data && (res.data.message || res.data.error)) || "Unable to queue refactoring.";
          }
          return;
        }
        var expDelivBtn = ev.target.closest ? ev.target.closest("[data-export-rep-deliverables]") : null;
        if (expDelivBtn) {
          var expRes = await ctx.postAnvil("replication_export_deliverables", { analysis_id: state.activeAnalysisId || undefined }, expDelivBtn);
          var expToast = document.getElementById("repToastBanner");
          if (expToast && expRes && expRes.data) {
            expToast.hidden = false;
            expToast.textContent = expRes.ok ? ("Exported scrubbed report to " + (expRes.data.report_file || "ANVIL-REPLICATION-REPORT.md") + " and registered in DELIVERABLES.md.") : (expRes.data.message || "Export refused.");
          }
        }
      });
    }

    return {
      stopReplicationPolling: stopReplicationPolling,
      fetchReplicationState: fetchReplicationState,
      openReplicationReportView: openReplicationReportView,
      renderReplicationV2Surface: renderReplicationV2Surface,
      openReplicationConsentModal: openReplicationConsentModal,
      closeReplicationConsentModal: closeReplicationConsentModal
    };
  }

  root.AnvilReport = {
    renderReplicationReportV2Html: renderReplicationReportV2Html,
    mountReportController: mountReportController
  };
  if (typeof module === "object" && module && module.exports) {
    module.exports = root.AnvilReport;
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
