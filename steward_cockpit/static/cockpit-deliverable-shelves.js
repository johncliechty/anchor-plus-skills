/* Collapsible & Hierarchical Deliverables Hub for AI Cockpit Right Rail (`[data-delivmount]`).
   - Outer `<details class="dtile dtile-master">` allows collapsing ALL deliverables down to a single tile.
   - All 3 main sections inside start CLOSED by default (`recent: false, final: false, earlier: false`):
     1. ⚡ Most Recent (by Instruction): `Last Instruction` and `Instruction Before Last`.
     2. 🏛 Final Deliverables: Steward Hierarchical Summary + Category -> Unit Folder -> Multi-format Product Tree.
     3. 📚 Earlier & Supporting Deliverables: collapsed archive with instant search/filter.
   Preserves Oct 4 readable managed review links (`open_path` + immutable SHA-256 `hash`). */
"use strict";

window.CockpitDeliverableShelves = (() => {
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  };

  const _shelfOpenState = { master: true, recent: false, final: false, earlier: false };
  const _hierOpenState = {};
  let _earlierFilter = "";

  function cleanTitle(item) {
    if (!item) return "Deliverable";
    const raw = String(item.human_title || item.title || item.what || item.filename || item.open_path || item.path || "Deliverable")
      .replace(/\*\*/g, "")
      .replace(/^(?:[\u2605\u2b50]\s*)?(?:START\s+HERE|FOR\s+REVIEW|FINAL(?:IZED)?|APPROVED|ACCEPTED|EARLIER|SUPERSEDED|Supporting)\s*[:\u2014\u2013\-]\s*/i, "")
      .trim();
    return raw || "Deliverable";
  }

  function withTok(url) {
    if (!url) return "";
    let u = String(url);
    if (window.STEWARD_TOKEN && u.startsWith("/") && !/[?&]token=/.test(u)) {
      u += (u.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(window.STEWARD_TOKEN);
    }
    return u;
  }

  function buildOpenHref(item, ctx) {
    if (!item) return "";
    if (item.reading && item.reading.read) return withTok(item.reading.read);
    if (item.route) return (ctx && typeof ctx.routeHref === "function") ? ctx.routeHref(item.route) : String(item.route);
    const rel = String(item.open_path || item.path || "").replace(/\\/g, "/").trim();
    if (!rel || rel.startsWith("/") || /(?:^|\/)\.\.(?:\/|$)/.test(rel)) return "";
    const params = new URLSearchParams(location.search || "");
    const pid = window.STEWARD_PID || params.get("pid") || "";
    const dir = item.dir !== undefined ? item.dir : (window.STEWARD_DIR || params.get("dir") || "");
    const isOffice = /\.(docx|pptx|xlsx)$/i.test(rel);
    const isMd = /\.(md|markdown|txt|r|py|sql|sh|ps1|yaml|yml|toml|js|mjs|ts|css)$/i.test(rel);
    return withTok("/api/steward/deliverable-file?pid=" + encodeURIComponent(pid) +
      "&dir=" + encodeURIComponent(dir) + "&path=" + encodeURIComponent(rel) +
      (item.hash ? ("&hash=" + encodeURIComponent(item.hash)) : "") +
      (isOffice ? "&view=1" : "") + (isMd ? "&render=1" : ""));
  }

  function buildDownloadHref(item, ctx) {
    if (item && item.download_url) return withTok(item.download_url);
    const openUrl = buildOpenHref(item, ctx);
    if (!openUrl) return "";
    const base = openUrl.replace(/([?&])(?:view|render|scrollview)=1(&|$)/g, (_m, p1, p2) => (p2 ? p1 : ""));
    const fn = String(item.suggested_filename || "").trim();
    return base + (base.includes("?") ? "&" : "?") + "download=1" + (fn ? ("&filename=" + encodeURIComponent(fn)) : "");
  }

  function openDeliverable(title, href, item, ctx) {
    if (!href) return;
    if (item && item.managed && item.presentation_id && ctx && typeof ctx.post === "function") {
      ctx.post("/api/refinement-open", { step_id: item.step, presentation_id: item.presentation_id, product_id: item.product_id, session_id: String(window.STEWARD_TERM || "cockpit") }).catch(() => {});
    }
    if (ctx && typeof ctx.markOpened === "function") ctx.markOpened(String(item.open_path || item.path || item.product_id || title));
    if (typeof window.enterSecondWindowMode === "function") { window.enterSecondWindowMode(title, href); return; }
    window.open(href, "_blank", "noopener");
  }

  function buildRow(item, shelfKind, ctx) {
    const title = cleanTitle(item), primaryHref = buildOpenHref(item, ctx), dlHref = buildDownloadHref(item, ctx);
    const row = el("div", "dfile-row deliv-tree-node shelf-" + shelfKind);
    row.setAttribute("role", "button");
    row.tabIndex = 0;
    const effPath = String(item.open_path || item.path || "");
    row.dataset.filePath = effPath;
    if (item.path) row.dataset.immutablePath = String(item.path);
    if (item.hash) row.dataset.fileHash = String(item.hash);
    if (item.product_id) row.dataset.productId = String(item.product_id);
    if (item.suggested_filename) row.dataset.suggestedFilename = String(item.suggested_filename);
    if (item.route) row.dataset.route = String(item.route);

    const left = el("div", "dfile-left");
    left.appendChild(el("div", "dfile-title", (shelfKind === "final" ? "\u2605 " : "\ud83d\udcc4 ") + title));
    const subText = item.curation_note ||
      (shelfKind === "earlier" && item.superseded_by ? ("Superseded by " + item.superseded_by) : "") ||
      (shelfKind === "final" && item.date ? ("Verified Final \u00b7 " + String(item.date).slice(0, 10)) : "");
    if (subText) left.appendChild(el("div", "dfile-sub" + (shelfKind === "earlier" ? " is-muted" : ""), subText));
    row.appendChild(left);

    const right = el("div", "fmt-pills");
    const rawFormats = (Array.isArray(item.format_pills) && item.format_pills.length)
      ? item.format_pills
      : ((Array.isArray(item.formats) && item.formats.length) ? item.formats : null);
    const pills = rawFormats || [{
      label: item.ext || (effPath.includes(".") ? effPath.split(".").pop().toUpperCase() : "OPEN"),
      path: effPath, route: item.route || "", hash: item.hash || "", product_id: item.product_id || "",
      suggested_filename: item.suggested_filename || "", reading: item.reading, download_url: item.download_url || "",
    }];
    pills.forEach((p) => {
      const pLbl = p.label || p.ext || "FILE";
      const pHref = buildOpenHref(p, ctx) || primaryHref;
      const pillA = el("a", "fpill deliv-format-pill" + (p.is_redline ? " is-redline" : ""), pLbl);
      if (pHref) pillA.href = pHref;
      pillA.target = "_blank"; pillA.rel = "noopener";
      pillA.dataset.pillType = p.is_redline ? "redline" : "format";
      if (p.hash) pillA.dataset.fileHash = String(p.hash);
      pillA.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); openDeliverable(title + " (" + pLbl + ")", pHref, p, ctx); };
      right.appendChild(pillA);
    });
    if (dlHref) {
      const dlA = el("a", "fpill deliv-dl-arrow", "\u2b07");
      dlA.href = dlHref;
      dlA.title = "Download " + (item.suggested_filename || title);
      if (item.suggested_filename) dlA.download = String(item.suggested_filename);
      dlA.onclick = (ev) => ev.stopPropagation();
      right.appendChild(dlA);
    }
    row.appendChild(right);
    row.onclick = (ev) => { if (ev.target && ev.target.closest && ev.target.closest("a, button")) return; ev.preventDefault(); openDeliverable(title, primaryHref, item, ctx); };
    row.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openDeliverable(title, primaryHref, item, ctx); } };
    return row;
  }

  function makeShelf(cls, key, titleText, countText, countCls) {
    const det = el("details", cls), sum = el("summary", ""), body = el("div", "dtile-body");
    det.dataset.shelf = key;
    det.open = Boolean(_shelfOpenState[key]);
    det.addEventListener("toggle", () => { if (det.isConnected) _shelfOpenState[key] = det.open; });
    sum.appendChild(el("span", "", titleText));
    sum.appendChild(el("span", "dtile-cnt" + (countCls ? (" " + countCls) : ""), countText));
    det.appendChild(sum);
    det.appendChild(body);
    return { det, body };
  }

  function buildHierarchyFinalBody(bodyEl, hier, finalList, ctx) {
    const cats = (hier && Array.isArray(hier.categories)) ? hier.categories : [];
    const exec = (hier && hier.executive_summary) || {};
    if (exec.headline || exec.narrative) {
      const sumBox = el("div", "deliv-hier-summary-box");
      if (exec.headline) sumBox.appendChild(el("div", "deliv-hier-summary-hl", "\ud83e\udded Steward Summary: " + exec.headline));
      if (exec.narrative) sumBox.appendChild(el("div", "deliv-hier-summary-sub", exec.narrative));
      bodyEl.appendChild(sumBox);
    }
    const renderedPaths = new Set();
    if (cats.length) {
      const catWrap = el("div", "deliv-hier-cat-list");
      cats.forEach((cat) => {
        const cKey = "cat:" + (cat.id || cat.title || "default");
        const cDet = el("details", "deliv-hier-category"), cSum = el("summary", ""), uWrap = el("div", "deliv-hier-units-wrap");
        cDet.dataset.hierCategory = cat.id || "cat";
        cDet.open = Object.prototype.hasOwnProperty.call(_hierOpenState, cKey) ? Boolean(_hierOpenState[cKey]) : (cats.length === 1);
        cDet.addEventListener("toggle", () => { if (cDet.isConnected) _hierOpenState[cKey] = cDet.open; });
        cSum.appendChild(el("span", "", "\ud83d\udcc2 " + (cat.title || "Deliverable Workstreams")));
        cSum.appendChild(el("span", "deliv-hier-cat-meta", ((cat.unit_count || (cat.units || []).length) + " folders \u25b8")));
        cDet.appendChild(cSum);

        (cat.units || []).forEach((u) => {
          const uKey = "unit:" + (u.unit_key || u.title || u.label || "u");
          const uDet = el("details", "deliv-unit-folder"), uSum = el("summary", ""), uFiles = el("div", "deliv-tree-children");
          uDet.dataset.unitKey = u.unit_key || "";
          uDet.open = Object.prototype.hasOwnProperty.call(_hierOpenState, uKey) ? Boolean(_hierOpenState[uKey]) : false;
          uDet.addEventListener("toggle", () => { if (uDet.isConnected) _hierOpenState[uKey] = uDet.open; });
          const uLeft = el("span", "deliv-unit-left");
          uLeft.appendChild(el("span", "deliv-unit-caret", "\u25b8"));
          uLeft.appendChild(el("span", "deliv-unit-icon", "\ud83d\udcc1"));
          uLeft.appendChild(el("span", "deliv-unit-title-txt", u.title || u.label || "Deliverable Unit"));
          const uRight = el("span", "deliv-unit-right");
          if (u.ext_summary) uRight.appendChild(el("span", "deliv-unit-exts", u.ext_summary));
          uRight.appendChild(el("span", "deliv-unit-badge " + (/review/i.test(String(u.status || "")) ? "badge-review" : "badge-final"), /review/i.test(String(u.status || "")) ? "\ud83d\udc41 Review" : "\u2713 Final"));
          uSum.appendChild(uLeft); uSum.appendChild(uRight);
          uDet.appendChild(uSum);
          (u.files || []).forEach((f) => {
            const pNorm = String(f.open_path || f.path || "").replace(/\\/g, "/").toLowerCase();
            if (pNorm) renderedPaths.add(pNorm);
            if (f.path) renderedPaths.add(String(f.path).replace(/\\/g, "/").toLowerCase());
            uFiles.appendChild(buildRow(f, "final", ctx));
          });
          uDet.appendChild(uFiles);
          uWrap.appendChild(uDet);
        });
        cDet.appendChild(uWrap);
        catWrap.appendChild(cDet);
      });
      bodyEl.appendChild(catWrap);
    } else if (finalList.length) {
      finalList.forEach((it) => bodyEl.appendChild(buildRow(it, "final", ctx)));
    } else {
      bodyEl.appendChild(el("div", "wm-empty-note", "Flagship Final deliverables curated by Steward appear here."));
    }
  }

  function render(mount, delivResponse, _decoratedItems, ctx) {
    const shelves = (delivResponse && delivResponse.shelves && typeof delivResponse.shelves === "object") ? delivResponse.shelves : null;
    if (!mount || !shelves) return false;
    mount.textContent = "";

    const recentBatches = Array.isArray(shelves.most_recent_batches) ? shelves.most_recent_batches.slice(0, 2) : [];
    const recentFilesCnt = recentBatches.reduce((acc, b) => acc + (Number(b.file_count) || (b.items || []).length), 0);
    const finalList = Array.isArray(shelves.final) ? shelves.final : [];
    const earlierList = Array.isArray(shelves.earlier) ? shelves.earlier : [];
    const hier = (delivResponse && delivResponse.deliverable_hierarchy && typeof delivResponse.deliverable_hierarchy === "object") ? delivResponse.deliverable_hierarchy : null;
    const hierUnitsCnt = (hier && Array.isArray(hier.categories) && hier.categories.length)
      ? hier.categories.reduce((acc, c) => acc + (Number(c.unit_count) || (c.units || []).length), 0)
      : 0;

    // Master wrapper: allows collapsing ALL deliverables down into a single tile
    const master = el("details", "dtile-master"), mSum = el("summary", "dtile-master-sum"), wrap = el("div", "deliv-shelves-wrap");
    master.dataset.delivMaster = "1";
    master.open = Boolean(_shelfOpenState.master);
    master.addEventListener("toggle", () => { if (master.isConnected) _shelfOpenState.master = master.open; });
    mSum.appendChild(el("span", "dtile-master-lbl", "\ud83d\udce6 Deliverables"));
    mSum.appendChild(el("span", "dtile-cnt", recentFilesCnt + " Recent \u00b7 " + (hierUnitsCnt || finalList.length) + (hierUnitsCnt ? " Units" : " Final") + (master.open ? " \u25be" : " \u25b8")));
    master.appendChild(mSum);
    wrap.dataset.deliverableShelves = "1";

    // 1. Most Recent Deliverables by Instruction (CLOSED by default)
    const bWord = recentBatches.length === 1 ? "Instruction" : "Instructions";
    const s1 = makeShelf("dtile recent", "recent", "\u26a1 Most Recent (by Instruction)", recentBatches.length ? (recentBatches.length + " " + bWord + " \u00b7 " + recentFilesCnt + (recentFilesCnt === 1 ? " file \u25b8" : " files \u25b8")) : "0 recent \u25b8");
    if (recentBatches.length) {
      recentBatches.forEach((batch, idx) => {
        const grp = el("div", "dtile-batch"), lbl = el("div", "turn-group-lbl"), list = el("div", "dtile-list");
        grp.dataset.batchId = String(batch.batch_id || idx);
        const rank = batch.rank_label || (idx === 0 ? "Last Instruction" : "Instruction Before Last");
        lbl.appendChild(el("span", "", "Most Recent \u00b7 " + rank + (batch.turn_num ? (" (#" + batch.turn_num + ")") : "")));
        if (batch.ago) lbl.appendChild(el("span", "wm-zone-sub", batch.ago));
        grp.appendChild(lbl);
        if (batch.instruction_excerpt) grp.appendChild(el("div", "dtile-prompt", "\u201c" + batch.instruction_excerpt + "\u201d"));
        (batch.items || []).forEach((it) => list.appendChild(buildRow(it, "recent", ctx)));
        grp.appendChild(list);
        s1.body.appendChild(grp);
      });
    } else {
      s1.body.appendChild(el("div", "wm-empty-note", "Deliverables from your last instruction and the instruction before last appear here."));
    }
    wrap.appendChild(s1.det);

    // 2. Final Deliverables with Steward Hierarchical Summary & Category/Unit Tree (CLOSED by default)
    const finBadge = hierUnitsCnt ? (hierUnitsCnt + " Units \u00b7 Hierarchy \u25b8") : (finalList.length + " Final \u25b8");
    const s2 = makeShelf("dtile final tier-final", "final", "\ud83c\udfdb Final Deliverables", finBadge);
    buildHierarchyFinalBody(s2.body, hier, finalList, ctx);
    wrap.appendChild(s2.det);

    // 3. Earlier & Supporting Deliverables (CLOSED by default)
    const s3 = makeShelf("dtile archive deliv-supporting-drawer", "earlier", "\ud83d\udcda Earlier Deliverables", earlierList.length + " earlier \u25b8", "is-archive");
    const searchIn = el("input", "wm-add-input"), listWrap = el("div", "dtile-list");
    searchIn.type = "search"; searchIn.placeholder = "Filter superseded drafts & earlier deliverables\u2026"; searchIn.value = _earlierFilter; searchIn.dataset.earlierSearch = "1";
    const paintEarlier = () => {
      listWrap.textContent = "";
      const q = String(_earlierFilter || "").trim().toLowerCase();
      const filtered = earlierList.filter((it) => !q || (cleanTitle(it) + " " + (it.open_path || "") + " " + (it.path || "") + " " + (it.step || "")).toLowerCase().includes(q));
      if (!filtered.length) { listWrap.appendChild(el("div", "wm-empty-note", earlierList.length ? "No earlier deliverables match filter." : "Superseded drafts and outputs from 3+ instructions ago live here.")); return; }
      filtered.forEach((it) => listWrap.appendChild(buildRow(it, "earlier", ctx)));
    };
    searchIn.oninput = (ev) => { ev.stopPropagation(); _earlierFilter = searchIn.value || ""; paintEarlier(); };
    searchIn.onclick = (ev) => ev.stopPropagation();
    s3.body.appendChild(searchIn); s3.body.appendChild(listWrap); paintEarlier();
    wrap.appendChild(s3.det);

    master.appendChild(wrap);
    mount.appendChild(master);
    return true;
  }

  return { render, buildOpenHref, buildDownloadHref };
})();
