/* Locked Mockup #1 Entry Scoping Controller (`anvil_scoping.js`, `<= 500` lines).
 * Implements:
 *   - Saved Scopes Shelf (`What Has Been Done`) with `Open Anvil Map ->` & `Replication & Ramanujan Report ->`
 *   - Hub + Provenance Architectural Module Cards + Contained Sibling Containers
 *   - 2-Step Outbound Privacy Consent Modal for `researchPrime` Literature Validation (`DOI:`/`arXiv:`/`PMID:` only;
 *     `0` unpublished draft prose/equations transmitted externally)
 *   - Steward + Gandalf Scoping Dialogue & Live 64-Hex SHA-256 Scope Manifest Receipt
 */
(function (root) {
  "use strict";

  function esc(val) {
    return root.AnvilV5Client ? root.AnvilV5Client.escHtml(val) : String(val == null ? "" : val).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function stripDollars(txt) {
    return String(txt == null ? "" : txt).replace(/\$/g, "");
  }

  function hydrateBrandIcons(container) {
    if (!container || !container.querySelectorAll) return;
    container.querySelectorAll("img[data-v6-src]").forEach(function (img) {
      var s = img.getAttribute("data-v6-src");
      if (s && !img.getAttribute("src")) img.setAttribute("src", s);
    });
  }

  function mountScopingController(ctx) {
    var state = ctx.state;

    async function fetchScopingV2State(overrideModuleIds) {
      if (!state.anvilV6Enabled) return;
      var v5 = root.AnvilV5Client || null;
      try {
        var extra = {};
        if (state.activeAnalysisId && state.intakeMode === "edit") extra.analysis_id = state.activeAnalysisId;
        if (Array.isArray(overrideModuleIds) && overrideModuleIds.length > 0) extra.module_ids = overrideModuleIds.join(",");
        if (state.scopingSoftwareSpec && (state.scopingSoftwareSpec !== "." || state.scopingUserPickedSoftware)) extra.software_spec = state.scopingSoftwareSpec;
        if (state.scopingPaperSpec !== undefined && state.scopingPaperSpec !== null && (state.scopingPaperSpec !== "" || state.scopingUserPickedPaper)) extra.paper_spec = state.scopingPaperSpec;

        var u = ctx.apiUrl("anvil/scoping", extra);
        ctx.recordAnvilRequest("GET", u, "scoping_state", state.activeAnalysisId || "");
        var resp = await root.fetch(u, { method: "GET", headers: ctx.headers(), cache: "no-store" });
        var data = null;
        try { data = await resp.json(); } catch (_e) { data = null; }
        if (!resp.ok || !data || data.ok === false) {
          var failSurf = v5 ? v5.resolveBootFailureSurface(resp.status, data, { anvilV6Enabled: true }) : ctx.SURFACE_FAILURE_ROWS[resp.status] || ctx.SURFACE_FAILURE_ROWS[500];
          state.surfaceState = failSurf;
          state.unknownState = Boolean(failSurf && failSurf.unknown_state);
          if (!state.scopeDrifted) state.bootFailureOnly = true;
          ctx.renderTopDeckAndBanner();
          return;
        }
        state.scopingState = data;
        state.scopingGandalfEnabled = data.gandalf_enabled !== false;
        var rec = data.receipt || {};
        if (Array.isArray(rec.selected_module_ids)) state.scopingSelectedModuleIds = rec.selected_module_ids.slice();
        if (typeof rec.software_spec === "string" && rec.software_spec) state.scopingSoftwareSpec = rec.software_spec;
        if (typeof rec.paper_spec === "string") state.scopingPaperSpec = rec.paper_spec;
        if (data.scope_sha256) state.scopeSha256 = String(data.scope_sha256);
        if (v5 && Array.isArray(data.saved_scopes)) {
          state.analyses = v5.normalizeAnalysesList({ analyses: data.saved_scopes, active_analysis_id: data.active_analysis_id }, null, state.cockpitName);
        }
      } catch (netErr) {
        state.surfaceState = v5 ? v5.resolveBootFailureSurface(0, { error: netErr ? netErr.message : "Network error" }, { anvilV6Enabled: true }) : ctx.SURFACE_FAILURE_ROWS[504];
        if (!state.scopeDrifted) state.bootFailureOnly = true;
        ctx.renderTopDeckAndBanner();
      }
    }

    function renderScopingV2Surface() {
      var sc = state.scopingState || {};
      var shelfEl = document.getElementById("doneShelf");
      var mapEl = document.getElementById("softwareMapScroll");
      var convEl = document.getElementById("convScroll");
      var recEl = document.getElementById("receiptBodyScroll");
      var recPill = document.getElementById("receiptStatusPill");
      var mainStageEl = document.getElementById("mainStage");
      var gandalfBtn = document.getElementById("btnGandalfToggle");
      var expBtn = document.getElementById("btnExpandMap");
      var rpLblEl = document.getElementById("rpBtnLabel");
      if (!shelfEl || !mapEl || !convEl || !recEl) return;

      if (mainStageEl) mainStageEl.classList.toggle("map-expanded", Boolean(state.scopingMapExpanded));
      if (expBtn) expBtn.textContent = state.scopingMapExpanded ? "⤡ Compact Map" : "⤢ Expand Map";
      if (gandalfBtn) {
        gandalfBtn.setAttribute("aria-pressed", String(Boolean(state.scopingGandalfEnabled)));
        gandalfBtn.textContent = state.scopingGandalfEnabled ? "🧙 Gandalf: ON" : "🧙 Gandalf: OFF";
      }
      var litInfo = sc.literature_sketch || {};
      if (rpLblEl) {
        rpLblEl.textContent = state.literatureValidated
          ? "✓ researchPrime Literature Validated"
          : (litInfo.has_sketch ? "◌ Literature Sketch (CLAIMED)" : "+ Validate Literature (researchPrime)");
      }

      var savedList = Array.isArray(sc.saved_scopes) && sc.saved_scopes.length > 0 ? sc.saved_scopes : (Array.isArray(state.analyses) ? state.analyses : []);
      if (savedList.length === 0) {
        shelfEl.innerHTML = '<div class="first-time-banner"><div class="selector-group"><img class="brand-icon-sm" src="/vendor/brand/gandalf-icon.jpg" alt="Gandalf" />' +
          '<div><div style="font-size:12.5px;font-weight:800;">' + esc(sc.message || "No Anvil scopes locked yet — inspect the Software & Paper Map below") + '</div>' +
          '<div style="font-size:11.5px;color:var(--ink-soft);">Select architectural modules on the map, verify the 64-hex SHA-256 receipt, and click Lock Scope &amp; Open Anvil Analysis.</div></div></div>' +
          '<span class="prov-tag">0 Locked Scopes</span></div>';
      } else {
        shelfEl.innerHTML = '<div class="shelf-head"><div class="shelf-title"><span>What Has Been Done · Saved Scopes &amp; Analyses in This Cockpit</span>' +
          '<span class="shelf-count-pill">' + savedList.length + ' Saved</span></div>' +
          '<button type="button" id="btnSetupNewScope" class="small-btn">+ Set Up a New Scope</button></div>' +
          '<div class="shelf-cards">' + savedList.map(function (item) {
            var aid = String(item.analysis_id || "");
            var drifted = Boolean(item.scope_drifted);
            var fullSha = String(item.scope_sha256 || "");
            var repDisabled = (!fullSha || drifted) ? " disabled" : "";
            var repTxt = item.has_replication_report ? "Replication &amp; Ramanujan Report →" : "Replication &amp; Ramanujan Report (Not run yet) →";
            return '<article class="done-card' + (drifted ? " drifted" : "") + '" data-saved-scope-card="' + esc(aid) + '">' +
              '<div class="done-card-top"><div><div class="done-card-name">' + esc(item.title || aid) + '</div>' +
              '<div class="done-card-meta">SHA-256: <code>' + esc(fullSha ? (fullSha.slice(0, 12) + "…") : "legacy") + '</code> · ' + Number(item.in_scope_file_count || 0) + ' file(s)</div></div>' +
              '<span class="prov-tag">' + (drifted ? "409 Scope Drifted" : (fullSha ? "Locked" : "Legacy")) + '</span></div>' +
              '<div class="done-card-actions">' +
                (drifted ? '<button type="button" class="consent-run-btn" data-relock-scope-id="' + esc(aid) + '">Inspect &amp; Re-Lock →</button>'
                         : '<button type="button" class="consent-run-btn" data-open-scope-id="' + esc(aid) + '">Open Anvil Map →</button>') +
                '<button type="button" class="small-btn" data-open-replication-id="' + esc(aid) + '"' + repDisabled + '><img class="brand-icon-xs" src="/vendor/brand/ramanujan-icon.jpg" alt="" /> <span>' + repTxt + '</span></button>' +
              "</div></article>";
          }).join("") + "</div>";
      }

      var swMap = sc.software_map || {};
      var repos = Array.isArray(swMap.repos) ? swMap.repos : [];
      var msCit = swMap.manuscript_citations || {};
      var statusLabels = { in_scope: "In Proposed Scope", saved_scope: "Other Saved Scope", available: "Available", unscoped_plumbing: "Unscoped Plumbing" };
      var statusClasses = { in_scope: "in-scope", saved_scope: "saved-scope", available: "", unscoped_plumbing: "unscoped" };

      var scCands = sc.candidates || state.candidates || {};
      var swCands = Array.isArray(scCands.software) ? scCands.software.filter(function (c) { return c && c.path && !/^([A-Za-z]:|[\\/])/.test(String(c.path)); }) : [];
      var ppCands = Array.isArray(scCands.papers) ? scCands.papers.filter(function (c) { return c && c.path && !/^([A-Za-z]:|[\\/])/.test(String(c.path)); }) : [];
      var curRec = sc.receipt || {};
      var curSwSpec = String(curRec.software_spec || state.scopingSoftwareSpec || ".");
      var curPpSpec = String(curRec.paper_file || curRec.paper_spec || state.scopingPaperSpec || "");
      var targetPickerHtml = "";
      if (swCands.length > 1 || ppCands.length > 0) {
        var swSeen = {};
        var swOpts = swCands.map(function (c) { swSeen[c.path] = true; return '<option value="' + esc(c.path) + '"' + (c.path === curSwSpec ? " selected" : "") + '>' + esc(c.label || c.path) + "</option>"; });
        if (!swSeen[curSwSpec]) swOpts.unshift('<option value="' + esc(curSwSpec) + '" selected>' + esc(curSwSpec === "." ? "Cockpit Root (.)" : curSwSpec) + "</option>");
        var ppOpts = ['<option value=""' + (!curPpSpec ? " selected" : "") + '>Auto / Software-only</option>'].concat(ppCands.map(function (c) {
          var isM = (c.path === curPpSpec) || (curPpSpec && ("cockpit:" + c.path) === curPpSpec) || (curPpSpec && c.path.slice(-curPpSpec.length) === curPpSpec);
          return '<option value="' + esc(c.path) + '"' + (isM ? " selected" : "") + '>' + esc(c.label || c.path) + "</option>";
        }));
        targetPickerHtml = '<div class="card-block" style="padding:8px 10px;margin-bottom:8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">' +
          '<label style="font-size:11px;font-weight:700;display:flex;align-items:center;gap:5px;flex:1 1 180px;"><span>Codebase:</span><select id="scopingRepoSelect" class="small-btn" style="flex:1;max-width:100%;font-weight:600;">' + swOpts.join("") + "</select></label>" +
          (ppCands.length > 0 ? '<label style="font-size:11px;font-weight:700;display:flex;align-items:center;gap:5px;flex:1 1 180px;"><span>Paper:</span><select id="scopingPaperSelect" class="small-btn" style="flex:1;max-width:100%;font-weight:600;">' + ppOpts.join("") + "</select></label>" : "") + "</div>";
      }

      var bibStrip = Number(msCit.count || 0) > 0
        ? '<div class="card-block" style="padding:7px 10px;margin-bottom:8px;background:#F8F5EE;"><div class="deck-row"><span style="font-size:11.5px;font-weight:700;">📚 Local Manuscript Bibliography (`MANUSCRIPT_CITED`): <strong>' + Number(msCit.count) + '</strong> entries · <strong>' + ((msCit.catalog_seeds || []).length) + '</strong> DOI/arXiv seed(s)</span><span class="prov-tag">Tier 0 Offline</span></div></div>'
        : "";
      var litBanner = litInfo.has_sketch ? '<div class="mod-lit-box" data-lit-claimed-banner="true"><strong>CLAIMED / unverified:</strong> Scholarly orientation sketch active (`verified: false`).</div>' : "";

      mapEl.innerHTML = targetPickerHtml + bibStrip + litBanner + (repos.length === 0
        ? '<div class="card-block">Scanning repository architecture and companion manuscript…</div>'
        : repos.map(function (rObj) {
            var mods = Array.isArray(rObj.modules) ? rObj.modules : [];
            return '<div class="card-block"><div class="deck-row"><strong>' + esc(rObj.repo_name || "Repository") + (rObj.is_primary ? " (Primary)" : " (Contained Sibling — Out of Default Scope)") + '</strong><span class="prov-tag">' + Number(rObj.total_files || 0) + " files</span></div>" +
              '<div class="cluster-grid" style="margin-top:8px;">' + mods.map(function (m) {
                var mid = String(m.module_id || m.id || "");
                var stKey = String(m.scope_status || "available");
                var scCounts = m.symbol_counts || {};
                var pLinks = m.local_paper_links || {};
                var extLit = m.external_literature || {};
                return '<button type="button" class="mod-node ' + (statusClasses[stKey] || "") + '" data-module-id="' + esc(mid) + '" aria-pressed="' + String(stKey === "in_scope") + '">' +
                  '<div class="deck-row" style="width:100%;"><strong style="font-size:12px;">' + esc(m.title || mid) + '</strong><span class="mod-badge ' + (statusClasses[stKey] || "") + '">' + esc(statusLabels[stKey] || stKey) + "</span></div>" +
                  '<div style="font-family:var(--font-mono);font-size:11px;color:var(--ink-soft);">' + esc(m.files_short || "") + "</div>" +
                  '<div style="font-size:11px;color:var(--ink-soft);">Symbols: ' + Number(scCounts.reached || 0) + " reached · " + Number(scCounts.uncertain || 0) + " uncertain · " + Number(scCounts.unreached || 0) + " unreached</div>" +
                  '<div style="font-size:11px;color:#1C4A78;">📄 ' + esc(pLinks.summary || "No local paper link") + "</div>" +
                  (extLit.status === "claimed" && extLit.summary ? '<div class="mod-lit-box"><strong>CLAIMED / unverified:</strong> ' + esc(extLit.summary) + "</div>" : "") +
                "</button>";
              }).join("") + "</div></div>";
          }).join(""));

      var turns = Array.isArray(sc.dialogue_turns) ? sc.dialogue_turns : [];
      convEl.innerHTML = turns.map(function (t) {
        var isUser = t.role === "user";
        return '<div class="chat-msg ' + (isUser ? "user" : "assistant") + '"><div style="font-size:11px;font-weight:800;margin-bottom:2px;">' + esc(t.speaker || (isUser ? "Operator" : "Steward + Gandalf")) + "</div>" +
          "<div>" + esc(stripDollars(t.text || "")) + "</div>" +
          (t.gandalf_note ? '<div style="margin-top:4px;padding-top:4px;border-top:1px dashed var(--border);font-size:11.5px;color:#4A3510;">🧙 ' + esc(stripDollars(t.gandalf_note)) + "</div>" : "") + "</div>";
      }).join("");
      convEl.scrollTop = convEl.scrollHeight;

      var receipt = sc.receipt || {};
      var shaHex = String(receipt.scope_sha256 || sc.scope_sha256 || state.scopeSha256 || "");
      var selMids = Array.isArray(receipt.selected_module_ids) ? receipt.selected_module_ids : [];
      var inFiles = Array.isArray(receipt.in_scope_files) ? receipt.in_scope_files : [];
      var eps = Array.isArray(receipt.entrypoints) ? receipt.entrypoints : [];
      var isDrifted = Boolean(state.scopeDrifted || receipt.drifted);
      if (recPill) {
        recPill.textContent = isDrifted ? "409 SCOPE DRIFTED" : "64-HEX SPEC READY";
        recPill.className = "prov-tag";
      }
      recEl.innerHTML =
        (isDrifted ? '<div class="drift-alert-banner" data-scope-drifted-badge="409"><strong>409 Scope Drifted:</strong> In-scope files changed after locking. Review updated digest and click Re-Lock Scope.</div>' : "") +
        '<div class="card-block"><div style="font-size:11.5px;font-weight:800;margin-bottom:4px;">Manifest SHA-256 Digest (64-hex):</div><div id="receiptSha256" class="sha-box">' + esc(shaHex || "computing…") + "</div></div>" +
        '<div class="card-block"><div style="font-size:11.5px;font-weight:800;">Selected Architectural Modules (' + selMids.length + '):</div>' +
          '<div style="margin-top:5px;display:flex;flex-wrap:wrap;gap:5px;">' + (selMids.length ? selMids.map(function (m) { return '<span class="reach-pill">' + esc(m) + "</span>"; }).join("") : '<span style="color:var(--ink-soft);">None</span>') + "</div>" +
          '<div style="margin-top:6px;font-size:11.5px;color:var(--ink-soft);">In-scope files: <strong>' + inFiles.length + '</strong> · Entrypoints: <strong>' + eps.length + '</strong></div>' +
          '<div style="margin-top:3px;font-size:11.5px;color:var(--ink-soft);">Manuscript: <code>' + esc(receipt.paper_file || "Software-only") + "</code></div></div>" +
        '<div class="card-block"><div class="selector-group"><img class="brand-icon-sm" src="/vendor/brand/ramanujan-icon.jpg" alt="" /><div style="font-size:11.5px;color:var(--ink-soft);">Replication &amp; Semantic Audit: <strong>Not run yet</strong> (unlocks after scope lock).</div></div></div>' +
        '<button type="button" id="btnLockScope" class="primary-launch-btn" style="width:100%;justify-content:center;">' + (isDrifted ? "↻ Re-Lock Scope &amp; Refresh Analysis →" : "🔒 Lock Scope &amp; Open Anvil Analysis →") + "</button>";
    }

    async function submitScopingV2Turn(rawText, btn) {
      var errBox = document.getElementById("scopingTurnError");
      if (errBox) { errBox.hidden = true; errBox.textContent = ""; }
      var res = await ctx.postAnvil("scoping_turn", {
        message: String(rawText || ""), gandalf_enabled: state.scopingGandalfEnabled,
        software_spec: state.scopingSoftwareSpec || undefined, paper_spec: state.scopingPaperSpec || undefined,
        module_ids: state.scopingSelectedModuleIds || undefined
      }, btn);
      if (res && res.ok && res.data) {
        var box = document.getElementById("msgBox");
        if (box) box.value = "";
        state.scopingState = res.data;
        if (res.data.receipt && Array.isArray(res.data.receipt.selected_module_ids)) state.scopingSelectedModuleIds = res.data.receipt.selected_module_ids.slice();
        if (res.data.scope_sha256) state.scopeSha256 = String(res.data.scope_sha256);
        renderScopingV2Surface();
      } else if (errBox) {
        errBox.hidden = false;
        errBox.textContent = (res && res.data && (res.data.message || res.data.error)) || ("Refused (" + (res ? res.status : 400) + ")");
      }
    }

    async function openLiteraturePrivacyModal(triggerBtn) {
      var modal = document.getElementById("literature-consent-modal");
      if (!modal) {
        var fallbackRes = await ctx.postAnvil("quick_literature_sketch", { operator_consent: true, software_spec: state.scopingSoftwareSpec || undefined, paper_spec: state.scopingPaperSpec || undefined, module_ids: state.scopingSelectedModuleIds || undefined }, triggerBtn);
        if (fallbackRes && fallbackRes.ok && fallbackRes.data) { state.scopingState = fallbackRes.data; renderScopingV2Surface(); }
        return;
      }
      var res = await ctx.postAnvil("literature_consent", { analysis_id: state.activeAnalysisId || undefined }, triggerBtn);
      var bodyEl = document.getElementById("litConsentSeedsPreview");
      var confirmBtn = document.getElementById("btnConfirmLiteratureConsent");
      if (res && res.ok && res.data) {
        state.pendingLitConsentToken = String(res.data.consent_token || "");
        var seeds = res.data.catalog_seed_ids || [];
        if (res.data.status === "NO_CATALOG_SEEDS" || seeds.length === 0) {
          bodyEl.textContent = res.data.message || "No public DOI/arXiv/PMID catalog identifiers found in .bib; 0 outbound requests will be sent.";
          if (confirmBtn) confirmBtn.hidden = true;
        } else {
          bodyEl.textContent = "Catalog seeds (" + seeds.length + "): " + seeds.join(", ") + " → Hosts: " + (res.data.outbound_hosts || []).join(", ") + " (0 unpublished draft prose sent)";
          if (confirmBtn) confirmBtn.hidden = false;
        }
      } else {
        bodyEl.textContent = (res && res.data && res.data.message) || "Lock scope first to run Tier-1 researchPrime literature validation, or click Orientation Sketch below.";
        if (confirmBtn) confirmBtn.hidden = true;
      }
      modal.hidden = false;
    }

    var scopingRoot = document.getElementById("anvilScopingV2Root");
    if (scopingRoot) {
      var v5 = root.AnvilV5Client || null;
      scopingRoot.addEventListener("click", async function (ev) {
        var modBtn = ev.target.closest ? ev.target.closest("[data-module-id]") : null;
        if (modBtn) {
          var mid = modBtn.getAttribute("data-module-id") || "";
          if (!mid || (v5 && !v5.isValidOpaqueModuleId(mid))) return;
          var prevList = Array.isArray(state.scopingSelectedModuleIds) ? state.scopingSelectedModuleIds.slice() : (((state.scopingState && state.scopingState.receipt && state.scopingState.receipt.selected_module_ids) || []).slice());
          var curList = prevList.slice();
          var idx = curList.indexOf(mid);
          if (idx >= 0) { if (curList.length <= 1) return; curList.splice(idx, 1); } else curList.push(mid);
          state.scopingSelectedModuleIds = curList;
          var res = await ctx.postAnvil("scoping_preview", { module_ids: curList, software_spec: state.scopingSoftwareSpec || undefined, paper_spec: state.scopingPaperSpec || undefined, analysis_id: state.intakeMode === "edit" ? (state.activeAnalysisId || undefined) : undefined }, modBtn);
          if (res && res.ok && res.data) { state.scopingState = res.data; state.scopeSha256 = String(res.data.scope_sha256 || ""); }
          else state.scopingSelectedModuleIds = prevList;
          renderScopingV2Surface();
          return;
        }
        var relockBtn = ev.target.closest ? ev.target.closest("[data-relock-scope-id]") : null;
        if (relockBtn) {
          var aid = relockBtn.getAttribute("data-relock-scope-id") || "";
          state.activeAnalysisId = aid; state.intakeMode = "edit"; state.scopeDrifted = true; state.launcherOpen = true; state.replicationViewOpen = false;
          await fetchScopingV2State(state.scopingSelectedModuleIds);
          ctx.renderAll();
          return;
        }
        var openRepBtn = ev.target.closest ? ev.target.closest("[data-open-replication-id]") : null;
        if (openRepBtn && !openRepBtn.disabled) { await ctx.openReplicationReportView(openRepBtn.getAttribute("data-open-replication-id") || ""); return; }
        var openScopeBtn = ev.target.closest ? ev.target.closest("[data-open-scope-id]") : null;
        if (openScopeBtn) {
          state.launcherOpen = false; state.replicationViewOpen = false; state.scopeDrifted = false;
          await ctx.switchActiveAnalysis(openScopeBtn.getAttribute("data-open-scope-id") || "");
          return;
        }
        if (ev.target.closest && ev.target.closest("#btnSetupNewScope")) {
          state.intakeMode = "new"; state.scopeDrifted = false; state.scopingSelectedModuleIds = null;
          await fetchScopingV2State(null); renderScopingV2Surface(); return;
        }
        var chipBtn = ev.target.closest ? ev.target.closest("[data-scoping-chip]") : null;
        if (chipBtn) { await submitScopingV2Turn(chipBtn.getAttribute("data-scoping-chip") || "", chipBtn); return; }
        var lockBtn = ev.target.closest ? ev.target.closest("#btnLockScope") : null;
        if (lockBtn) {
          var scRec = (state.scopingState && state.scopingState.receipt) || {};
          var selList = Array.isArray(state.scopingSelectedModuleIds) ? state.scopingSelectedModuleIds.slice() : ((scRec.selected_module_ids || []).slice());
          var lRes = await ctx.postAnvil("lock_scope", {
            module_ids: selList, software_spec: scRec.software_spec || state.scopingSoftwareSpec || ".",
            paper_spec: scRec.paper_spec !== undefined ? scRec.paper_spec : (state.scopingPaperSpec || ""),
            create_new: state.intakeMode === "new",
            analysis_id: (state.scopeDrifted || state.intakeMode === "edit") ? (state.activeAnalysisId || undefined) : undefined
          }, lockBtn);
          if (lRes && lRes.ok && lRes.data) {
            state.launcherOpen = false; state.replicationViewOpen = false; state.scopeDrifted = false;
            state.intakeMode = "edit"; state.lens = "understand"; state.inspectorTab = "story";
            ctx.hydrateFromServerPayload(lRes.data, lRes.status, false);
            ctx.renderAll();
          }
        }
      });

      scopingRoot.addEventListener("change", async function (ev) {
        var t = ev.target;
        if (!t) return;
        if (t.id === "scopingRepoSelect") {
          state.scopingSoftwareSpec = String(t.value || "."); state.scopingUserPickedSoftware = true; state.scopingSelectedModuleIds = null;
          await fetchScopingV2State(null); renderScopingV2Surface();
        } else if (t.id === "scopingPaperSelect") {
          state.scopingPaperSpec = String(t.value || ""); state.scopingUserPickedPaper = true;
          await fetchScopingV2State(state.scopingSelectedModuleIds); renderScopingV2Surface();
        }
      });

      var expBtn = document.getElementById("btnExpandMap");
      if (expBtn) expBtn.addEventListener("click", function () { state.scopingMapExpanded = !state.scopingMapExpanded; renderScopingV2Surface(); });
      var rpBtn = document.getElementById("btnRpToggle");
      if (rpBtn) rpBtn.addEventListener("click", function () { openLiteraturePrivacyModal(rpBtn); });
      var gBtn = document.getElementById("btnGandalfToggle");
      if (gBtn) gBtn.addEventListener("click", async function () { state.scopingGandalfEnabled = !state.scopingGandalfEnabled; await submitScopingV2Turn("", gBtn); });
      var sendBtn = document.getElementById("btnSendScopingTurn");
      var msgBox = document.getElementById("msgBox");
      if (sendBtn && msgBox) {
        sendBtn.addEventListener("click", function () { if ((msgBox.value || "").trim()) submitScopingV2Turn(msgBox.value, sendBtn); });
        msgBox.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendBtn.click(); } });
      }
    }

    var cancelLit = document.getElementById("btnCancelLiteratureConsent");
    if (cancelLit) cancelLit.addEventListener("click", function () { document.getElementById("literature-consent-modal").hidden = true; });
    var sketchLit = document.getElementById("btnSketchLiteratureFallback");
    if (sketchLit) sketchLit.addEventListener("click", async function () {
      var res = await ctx.postAnvil("quick_literature_sketch", { operator_consent: true, software_spec: state.scopingSoftwareSpec || undefined, paper_spec: state.scopingPaperSpec || undefined, module_ids: state.scopingSelectedModuleIds || undefined }, sketchLit);
      document.getElementById("literature-consent-modal").hidden = true;
      if (res && res.ok && res.data) { state.scopingState = res.data; renderScopingV2Surface(); }
    });
    var confirmLit = document.getElementById("btnConfirmLiteratureConsent");
    if (confirmLit) confirmLit.addEventListener("click", async function () {
      var res = await ctx.postAnvil("literature_start", { analysis_id: state.activeAnalysisId || undefined, scope_sha256: state.scopeSha256, consent_token: state.pendingLitConsentToken }, confirmLit);
      document.getElementById("literature-consent-modal").hidden = true;
      if (res && res.ok) { state.literatureValidated = true; state.literatureData = res.data; ctx.renderAll(); }
    });

    return { fetchScopingV2State: fetchScopingV2State, renderScopingV2Surface: renderScopingV2Surface, submitScopingV2Turn: submitScopingV2Turn, openLiteraturePrivacyModal: openLiteraturePrivacyModal };
  }

  root.AnvilScoping = { hydrateBrandIcons: hydrateBrandIcons, mountScopingController: mountScopingController };
})(typeof globalThis !== "undefined" ? globalThis : window);
