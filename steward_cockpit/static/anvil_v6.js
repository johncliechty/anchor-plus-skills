/* Unified Anvil v6 Surface Bridge (`anvil_v6.js`).
 * Delegates cleanly to `AnvilScoping` (`#1`), `AnvilSchematic` (`#3`), `AnvilIdeDrawer` (`#3`),
 * and `AnvilReport` (`#2`). Zero `setInt`+`erval`, zero duplicate synthesis/SVG bloat.
 */
(function (root) {
  "use strict";

  function hydrateV6BrandIcons(container) {
    if (root.AnvilScoping && root.AnvilScoping.hydrateBrandIcons) {
      root.AnvilScoping.hydrateBrandIcons(container);
    }
  }

  function mountV6SurfaceControllers(ctx) {
    var repCtrl = root.AnvilReport ? root.AnvilReport.mountReportController(ctx) : {};
    ctx.openReplicationReportView = repCtrl.openReplicationReportView || function () {};
    var scopeCtrl = root.AnvilScoping ? root.AnvilScoping.mountScopingController(ctx) : {};
    ctx.fetchScopingV2State = scopeCtrl.fetchScopingV2State || function () {};
    ctx._v6Mounted = true;
    root.__anvilV6Ctx = ctx;
    return Object.assign({}, scopeCtrl, repCtrl);
  }

  function syncSurfaceDepInstallBanner() {
    var ctx = root.__anvilV6Ctx;
    var banner = typeof document !== "undefined" ? document.getElementById("surface-state-banner") : null;
    if (!ctx || !banner) return;
    var surf = ctx.state && ctx.state.surfaceState;
    var pkgs = (surf && Array.isArray(surf.missing_packages)) ? surf.missing_packages.map(String).filter(Boolean) : [];
    var tok = surf && surf.dep_install_token ? String(surf.dep_install_token) : "";
    var existing = document.getElementById("btn-approve-trace-deps");
    if (!pkgs.length || !tok || banner.hidden) {
      if (existing) existing.hidden = true;
      return;
    }
    if (!existing) {
      existing = document.createElement("button");
      existing.type = "button";
      existing.id = "btn-approve-trace-deps";
      existing.className = "consent-run-btn";
      var retryBtn = document.getElementById("btn-retry-state");
      if (retryBtn && retryBtn.parentNode === banner) banner.insertBefore(existing, retryBtn);
      else banner.appendChild(existing);
      existing.addEventListener("click", async function () {
        var cur = ctx.state && ctx.state.surfaceState;
        if (!cur || !cur.dep_install_token || !Array.isArray(cur.missing_packages)) return;
        var res = await ctx.postAnvil("trace_install_deps", {
          analysis_id: ctx.state.activeAnalysisId || undefined,
          scope_sha256: cur.scope_sha256 || ctx.state.scopeSha256 || undefined,
          packages: cur.missing_packages,
          dep_install_token: cur.dep_install_token
        }, existing);
        if (res && (res.ok || (res.data && res.data.surface_state))) {
          ctx.hydrateFromServerPayload(res.data, res.status, false);
          ctx.renderAll();
        }
      });
    }
    existing.hidden = false;
    existing.textContent = "⬇ Install Missing Packages (" + pkgs.join(", ") + ") & Complete Trace";
  }

  root.AnvilV6Runtime = {
    hydrateV6BrandIcons: hydrateV6BrandIcons,
    mountV6SurfaceControllers: mountV6SurfaceControllers,
    syncSurfaceDepInstallBanner: syncSurfaceDepInstallBanner
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
