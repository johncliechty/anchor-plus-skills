/* Simplified 3-Zone Plan / Wave Map for AI Cockpit Left Rail (`/steward/v1`).
   Default state: Zone 1 (`Most Recently Done`) OPEN by default; Current Wave & Next Steps CLOSED by default:
   Zone 1 (`<details open>`): 🕘 Most Recently Done (last 2-3 completed moves)
   Zone 2 (`<details>`): 🌊 Current Wave (`WAVE K · ACTIVE`, `Round R`, recommendation, Iterate / Done->Next)
   Zone 3 (`<details>`): ⏭ Next Steps (`★ Next Up` on first queued wave + `+ Wave` quick add)
   Strictly suppressed when `embed=dialogue` (Oct 4 Cave expanded-tile law). */
"use strict";

window.CockpitWaveMap = (() => {
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  };

  const _zoneOpenState = { "recent-history": true, "current-wave": false, "coming-next": false };
  let _cachedWaveMap = null;
  let _quickAddOpen = false;

  function isEmbedDialogue(ctx) {
    if (ctx && ctx.embedDialogue) return true;
    try {
      const p = new URLSearchParams(location.search || "");
      const v = (p.get("view") || "").toLowerCase();
      if (p.get("embed") === "dialogue" || p.get("embed") === "1" || v === "dialogue" || v === "tile" || v === "talk") return true;
      if (window.STEWARD_EMBED === true) return true;
    } catch (_e) {}
    const app = document.querySelector(".app");
    return Boolean(app && (app.classList.contains("tileview") || app.classList.contains("talkview") || app.classList.contains("embed-tile")));
  }

  function stepIsDone(st) {
    if (!st) return false;
    if (st.refinement && st.refinement.phase === "done") return true;
    if (st.refinement && (st.refinement.phase === "awaiting_review" || st.refinement.phase === "blocked")) return false;
    return Boolean(st.done === true || st.status === "done");
  }

  function cleanTitle(st, waveNum) {
    const raw = String((st && st.navigation && st.navigation.label) || (st && (st.title || st.name)) || ("Wave " + waveNum)).replace(/\*\*/g, "").trim();
    const re = new RegExp("^(?:wave|step)\\s*" + waveNum + "\\s*[:\\u00b7\\u2014\\u2013\\-]\\s*", "i");
    return raw.replace(re, "").trim() || ("Wave " + waveNum);
  }

  function deriveFallbackFromMap(mapData) {
    const m = mapData || {};
    const pool = (Array.isArray(m.steps) ? m.steps : []).filter(s => s && !(s.parked === true || s.status === "parked"));
    const total = pool.length, doneCnt = pool.filter(stepIsDone).length;
    const hb = m.heartbeat || {};
    const focusId = String(m.now_step_id || hb.current_step_id || "").trim();
    let curIdx = focusId ? pool.findIndex(s => String(s.id || "") === focusId && !stepIsDone(s)) : -1;
    if (curIdx < 0) curIdx = pool.findIndex(s => !stepIsDone(s) && /^(active|in_progress|waiting|blocked)$/i.test(String(s.status || "")));
    if (curIdx < 0) curIdx = pool.findIndex(s => !stepIsDone(s));

    let currentWave = null;
    const comingNext = [];
    if (curIdx >= 0) {
      const cur = pool[curIdx], wNum = curIdx + 1;
      const rRaw = (cur.refinement && (cur.refinement.display_round || cur.refinement.round)) || 1;
      const round = Math.max(1, Math.min(99, parseInt(rRaw, 10) || 1)), nextR = Math.min(99, round + 1);
      currentWave = {
        step_id: String(cur.id || ("wave-" + wNum)), wave_num: wNum, total_waves: total, round,
        can_iterate: round < 99, badge: "WAVE " + wNum + " \u00b7 ACTIVE",
        iter_badge: "\u21bb Iterating \u00b7 Round " + round,
        progress_badge: "Wave " + wNum + "/" + total + " \u00b7 R" + round,
        title: cleanTitle(cur, wNum), goal: String(cur.goal || cur.done_when || hb.active_effort || "").trim(),
        recommended_action: null, recommendation_text: String(hb.next_recommended || "").trim(),
        iterate_label: "\u21bb Iterate Wave " + wNum + " (Round " + nextR + ")",
        done_label: "\u2713 Wave " + wNum + " Done \u2192 Next",
      };
      let qIdx = 0;
      pool.forEach((s, i) => {
        if (i === curIdx || stepIsDone(s)) return;
        const nNum = i + 1;
        comingNext.push({
          step_id: String(s.id || ("wave-" + nNum)), wave_num: nNum, title: cleanTitle(s, nNum),
          note: String(s.goal || s.done_when || "Queued wave").trim(),
          next_up: qIdx === 0, badge: qIdx === 0 ? "\u2605 Next Up" : "",
        });
        qIdx += 1;
      });
    }
    const recentHistory = [];
    for (let i = pool.length - 1; i >= 0 && recentHistory.length < 3; i--) {
      if (stepIsDone(pool[i])) recentHistory.push({ ago: "Done", text: "Completed Wave " + (i + 1) + " \u2014 " + cleanTitle(pool[i], i + 1) });
    }
    return { ok: true, counts: { done: doneCnt, total }, recent_history: recentHistory, current_wave: currentWave, coming_next: comingNext, all_done: total > 0 && !currentWave };
  }

  async function fetchWaveMap(ctx) {
    if (isEmbedDialogue(ctx)) return null;
    const apiFn = (ctx && ctx.api) ? ctx.api : (u => u);
    try {
      const r = await fetch(apiFn("/api/wave-state"));
      if (!r || !r.ok) return null;
      const j = await r.json();
      if (j && j.ok) _cachedWaveMap = j;
      return j;
    } catch (_e) { return null; }
  }

  function makeZoneDetails(zoneKey, titleText, badgeText, badgeCls, previewText) {
    const det = el("details", "wm-zone wm-fold"), sum = el("summary", "wm-zone-sum"), body = el("div", "wm-zone-body");
    det.dataset.waveZone = zoneKey;
    det.open = Boolean(_zoneOpenState[zoneKey]);
    det.addEventListener("toggle", () => { if (det.isConnected) _zoneOpenState[zoneKey] = det.open; });
    const top = el("div", "wm-sum-top");
    top.appendChild(el("span", "wm-sum-title", titleText));
    top.appendChild(el("span", "wm-sum-pill" + (badgeCls ? (" " + badgeCls) : ""), badgeText));
    sum.appendChild(top);
    if (previewText) sum.appendChild(el("div", "wm-sum-preview", previewText));
    det.appendChild(sum);
    det.appendChild(body);
    return { det, body };
  }

  function render(mapData, ctx) {
    if (isEmbedDialogue(ctx)) return false;
    const mount = document.querySelector("[data-wave-map]");
    if (!mount) return false;
    mount.hidden = false;
    document.querySelectorAll("[data-plan-focus],[data-plan-add]").forEach((n) => { n.hidden = true; n.style.display = "none"; });

    const postFn = (ctx && ctx.post) ? ctx.post : ((u, b) => fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }));
    const onMutated = (ctx && ctx.onMutated) ? ctx.onMutated : (() => {});
    const wm = (mapData && mapData.wave_map && mapData.wave_map.ok) ? mapData.wave_map : (_cachedWaveMap && _cachedWaveMap.ok ? _cachedWaveMap : deriveFallbackFromMap(mapData));

    const headEl = document.querySelector("[data-plan-head]"), countEl = document.querySelector("[data-plan-count]"), fillEl = document.querySelector("[data-progress-fill]");
    const counts = wm.counts || { done: 0, total: 0 };
    if (headEl) headEl.textContent = "PLAN";
    if (countEl) countEl.textContent = counts.done + "/" + counts.total + " Waves";
    if (fillEl) fillEl.style.width = (counts.total ? Math.round((100 * counts.done) / counts.total) : 0) + "%";

    const ae = typeof document !== "undefined" ? document.activeElement : null;
    if (_quickAddOpen && ae && mount.contains(ae) && (ae.dataset.waveAddTitle || ae.dataset.waveAddGoal)) {
      return true;
    }
    const domSig = JSON.stringify([
      counts,
      Boolean(wm.all_done),
      wm.goal_brief || "",
      wm.folder_path || "",
      Array.isArray(wm.recent_history) ? wm.recent_history.slice(0, 3) : [],
      wm.current_wave || null,
      Array.isArray(wm.coming_next) ? wm.coming_next : [],
      Boolean(_quickAddOpen),
    ]);
    if (mount.dataset.domSig === domSig && mount.childElementCount > 0) {
      return true;
    }
    mount.dataset.domSig = domSig;
    mount.textContent = "";

    // Zone 1 (OPEN by default): Most Recently Done (+ immediate Goal/Folder/Recent hydration before large /api/map finishes)
    const histItems = Array.isArray(wm.recent_history) ? wm.recent_history.slice(0, 3) : [];
    const gbEl = document.querySelector("[data-goalbrief]");
    if (gbEl && wm.goal_brief && (!gbEl.textContent || gbEl.textContent.trim() === "\u2026")) gbEl.textContent = wm.goal_brief;
    const fpPill = document.querySelector("[data-cockpit-folder-pill]"), fpCode = document.querySelector("[data-cockpit-folder-path]");
    if (fpPill && fpCode && wm.folder_path && fpPill.hidden) { fpPill.hidden = false; fpCode.textContent = wm.folder_path; }
    const recentLineEl = document.querySelector("[data-recent-done-line]");
    if (recentLineEl && histItems[0] && histItems[0].text && !recentLineEl.dataset.fromServer) {
      const txt0 = String(histItems[0].text).trim();
      const ago0 = (histItems[0].ago && !/^done$/i.test(String(histItems[0].ago).trim())) ? (" (" + histItems[0].ago + ")") : "";
      recentLineEl.textContent = (/[.!?]$/.test(txt0) ? txt0.slice(0, -1) : txt0) + ago0 + ".";
    }
    const z1 = makeZoneDetails("recent-history", "\ud83d\udd58 Most Recently Done", (counts.done || histItems.length) + " done", "is-done", histItems[0] ? histItems[0].text : "");
    const histBox = el("div", "wm-hist-box");
    histBox.dataset.recentHistory = "1";
    if (histItems.length) {
      histItems.forEach((h) => {
        const row = el("div", "wm-hist-row");
        row.appendChild(el("span", "wm-hist-time", h.ago || "Done"));
        row.appendChild(el("span", "wm-hist-txt", h.text || ""));
        histBox.appendChild(row);
      });
    } else {
      histBox.appendChild(el("div", "wm-empty-note", "Completed waves and deliverable landings appear here."));
    }
    z1.body.appendChild(histBox);
    mount.appendChild(z1.det);

    // Zone 2 (Closed by default): Current Wave
    const cw = wm.current_wave;
    const cwPill = cw ? ("Wave " + cw.wave_num + "/" + cw.total_waves + " \u00b7 R" + cw.round + " \u25b8") : (wm.all_done ? "All done \u25b8" : "Idle \u25b8");
    const z2 = makeZoneDetails("current-wave", "\ud83c\udf0a Current Wave", cwPill, cw ? "is-active" : "", cw ? cw.title : "");
    const card = el("div", "wm-active-card");
    card.dataset.currentWaveCard = "1";
    if (cw) {
      const top = el("div", "wm-wave-top");
      top.appendChild(el("span", "wm-wave-num", cw.badge || ("WAVE " + cw.wave_num + " \u00b7 ACTIVE")));
      const iterBadge = el("span", "wm-iter-badge", cw.iter_badge || ("\u21bb Iterating \u00b7 Round " + cw.round));
      iterBadge.dataset.waveRound = String(cw.round);
      top.appendChild(iterBadge);
      card.appendChild(top);
      card.appendChild(el("div", "wm-wave-title", cw.title || ""));
      if (cw.goal) card.appendChild(el("div", "wm-wave-goal", cw.goal));
      if (cw.recommendation_text) {
        const rec = el("div", "wm-rec-strip", cw.recommendation_text);
        if (cw.recommended_action) rec.dataset.recommendedAction = cw.recommended_action;
        card.appendChild(rec);
      }
      const runWaveOp = async (btn, opName) => {
        btn.disabled = true;
        try {
          const r = await postFn("/api/wave-state", { op: opName, step_id: cw.step_id });
          const j = r ? await r.json() : null;
          if (j && j.ok) { _cachedWaveMap = j; if (mapData) mapData.wave_map = j; render(mapData, ctx); onMutated(j); }
          else btn.disabled = false;
        } catch (_e) { btn.disabled = false; }
      };
      const btns = el("div", "wm-btns");
      const iterBtn = el("button", "wm-btn iter", cw.iterate_label || ("\u21bb Iterate Wave " + cw.wave_num + " (Round " + (cw.round + 1) + ")"));
      iterBtn.type = "button"; iterBtn.dataset.waveIterate = cw.step_id; iterBtn.disabled = cw.can_iterate === false;
      iterBtn.onclick = (ev) => { ev.preventDefault(); runWaveOp(iterBtn, "iterate"); };
      const doneBtn = el("button", "wm-btn done", cw.done_label || ("\u2713 Wave " + cw.wave_num + " Done \u2192 Next"));
      doneBtn.type = "button"; doneBtn.dataset.waveDone = cw.step_id;
      doneBtn.onclick = (ev) => { ev.preventDefault(); runWaveOp(doneBtn, "done_next"); };
      btns.appendChild(iterBtn); btns.appendChild(doneBtn);
      card.appendChild(btns);
    } else {
      card.appendChild(el("div", "wm-empty-note", wm.all_done ? "\u2713 All planned waves completed. Open Next Steps to add a wave or ask Steward." : "No active wave yet \u2014 open Next Steps to add a wave or ask Steward."));
    }
    z2.body.appendChild(card);
    mount.appendChild(z2.det);

    // Zone 3 (Closed by default): Next Steps
    const upcoming = Array.isArray(wm.coming_next) ? wm.coming_next : [];
    const z3 = makeZoneDetails("coming-next", "\u23ed Next Steps", upcoming.length + " next \u25b8", "is-next", upcoming[0] ? ("Next: " + upcoming[0].title) : "");
    const addRow = el("div", "wm-zone-hdr"), addToggle = el("button", "wm-add-btn", "+ Add Wave");
    addToggle.type = "button"; addToggle.dataset.quickAddWave = "1";
    addRow.appendChild(el("span", "wm-zone-sub", upcoming.length ? "Queued waves" : "Queue empty"));
    addRow.appendChild(addToggle);
    z3.body.appendChild(addRow);

    const addForm = el("form", "wm-add-form"), titleIn = el("input", "wm-add-input"), goalIn = el("input", "wm-add-input"), subBtn = el("button", "wm-btn done", "Save Wave");
    addForm.hidden = !_quickAddOpen; addForm.style.display = _quickAddOpen ? "flex" : "none";
    titleIn.type = "text"; titleIn.placeholder = "New wave title\u2026"; titleIn.dataset.waveAddTitle = "1";
    goalIn.type = "text"; goalIn.placeholder = "Wave goal (optional)"; goalIn.dataset.waveAddGoal = "1";
    subBtn.type = "submit";
    addForm.appendChild(titleIn); addForm.appendChild(goalIn); addForm.appendChild(subBtn);
    addToggle.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); _quickAddOpen = !_quickAddOpen; addForm.hidden = !_quickAddOpen; addForm.style.display = _quickAddOpen ? "flex" : "none"; if (_quickAddOpen) titleIn.focus(); };
    addForm.onsubmit = async (ev) => {
      ev.preventDefault();
      const tVal = String(titleIn.value || "").trim(), gVal = String(goalIn.value || "").trim();
      if (!tVal) { titleIn.focus(); return; }
      subBtn.disabled = true;
      try {
        const r = await postFn("/api/plan", { op: "add_step", title: tVal, goal: gVal });
        const j = r ? await r.json() : null;
        if (j && j.ok) { titleIn.value = ""; goalIn.value = ""; _quickAddOpen = false; _cachedWaveMap = null; await fetchWaveMap(ctx); onMutated(j); }
      } finally { subBtn.disabled = false; }
    };
    z3.body.appendChild(addForm);

    const nextList = el("div", "wm-next-list");
    nextList.dataset.comingNextList = "1";
    if (upcoming.length) {
      upcoming.forEach((w) => {
        const row = el("div", "wm-next-row" + (w.next_up ? " recommended" : "")), top = el("div", "wm-nwr-top");
        row.dataset.waveStepId = w.step_id || "";
        top.appendChild(el("span", "", "Wave " + w.wave_num + " \u00b7 " + w.title));
        if (w.next_up) top.appendChild(el("span", "wm-rec-tag", "\u2605 Next Up"));
        row.appendChild(top);
        if (w.note) row.appendChild(el("div", "wm-nwr-sub", w.note));
        nextList.appendChild(row);
      });
    } else {
      nextList.appendChild(el("div", "wm-empty-note", "No additional waves queued."));
    }
    z3.body.appendChild(nextList);
    mount.appendChild(z3.det);
    return true;
  }

  return { render, fetchWaveMap, isEmbedDialogue, deriveFallbackFromMap };
})();
