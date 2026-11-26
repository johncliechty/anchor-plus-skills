/* Locked Mockup #3 Horizontal Serpentine Process Schematic & Generic Edge Router (`anvil_schematic.js`).
 * Implements:
 *   - `computeSchematicLayout(stages)`: horizontal serpentine grid (`cols = min(k,4), rows = ceil(k/4)`)
 *     guaranteeing ZERO node-node bounding-box collisions across `k = 1..8`.
 *   - Generic 4-mode edge router (adjacent horizontal, cross-row outer-gutter Bezier, same-row top arc,
 *     and under-row dashed amber optimization/feedback loop-back).
 *   - Click-to-expand `L2 Sub-Diagram` (`b`) + Stage Wall-Time Share bar.
 *   - 2-band horizontal `S* -> N*` Pure-Core Refactor Crosswalk + Paper Equation -> Stage Crosswalk.
 *   - Compact 25% Posture-2 Live Rail & Static-vs-Traced `#scrubber-bar`.
 */
(function (root) {
  "use strict";

  function esc(val) {
    return root.AnvilV5Client ? root.AnvilV5Client.escHtml(val) : String(val == null ? "" : val).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function stripDollars(txt) {
    return String(txt == null ? "" : txt).replace(/\$/g, "");
  }

  function shortWords(raw, maxWords, maxChars) {
    var clean = stripDollars(raw).replace(/\s+/g, " ").trim();
    if (!clean) return "";
    var joined = clean.split(" ").slice(0, maxWords || 5).join(" ");
    var cap = maxChars || 30;
    return joined.length > cap ? joined.slice(0, cap - 1).trimEnd() + "…" : joined;
  }

  function basename(p) {
    var s = String(p || "");
    var i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
    return i >= 0 ? s.slice(i + 1) : s;
  }

  function stagePalette(kind, isFault) {
    if (isFault) return { stroke: "#C44F2A", fill: "#FBE0D0", tag: "FAULT" };
    var k = String(kind || "compute").toLowerCase();
    if (k.indexOf("ingest") >= 0 || k.indexOf("prep") >= 0) return { stroke: "#4FA869", fill: "#DAEEDC", tag: k.indexOf("prep") >= 0 ? "PREP" : "INGEST" };
    if (k.indexOf("optim") >= 0 || k.indexOf("emit") >= 0 || k.indexOf("loop") >= 0) return { stroke: "#D4A858", fill: "#F8E8C8", tag: k.indexOf("optim") >= 0 ? "OPTIMIZE" : "EMIT" };
    if (k.indexOf("out") >= 0 || k.indexOf("eval") >= 0 || k.indexOf("infra") >= 0) return { stroke: "#5A6573", fill: "#E0E4E9", tag: "OUTPUT" };
    return { stroke: "#4A7DB0", fill: "#DCE8F5", tag: "KERNEL" };
  }

  function computeSchematicLayout(stages) {
    var list = Array.isArray(stages) ? stages.slice(0, 8) : [];
    var k = list.length;
    if (k === 0) return { width: 760, height: 150, cols: 0, rows: 0, nodes: [], byId: {} };
    var cols = Math.min(k, 4);
    var rows = Math.ceil(k / 4);
    var padX = 34;
    var topY = 44;
    var boxW = cols <= 3 ? 210 : 162;
    var boxH = 88;
    var gapX = cols <= 3 ? 34 : 26;
    var gapY = 64;
    var svgW = Math.max(720, padX * 2 + cols * boxW + Math.max(0, cols - 1) * gapX + 24);
    var svgH = topY + rows * boxH + Math.max(0, rows - 1) * gapY + 52;
    var nodes = [];
    var byId = {};

    list.forEach(function (st, idx) {
      var r = Math.floor(idx / 4);
      var posInRow = idx % 4;
      var c = (r % 2 === 1) ? (cols - 1 - posInRow) : posInRow;
      var x = padX + c * (boxW + gapX);
      var y = topY + r * (boxH + gapY);
      var sid = String(st.id || st.stage_id || ("S" + (idx + 1)));
      var box = {
        id: sid,
        index: idx,
        row: r,
        col: c,
        x: x,
        y: y,
        w: boxW,
        h: boxH,
        cx: x + boxW / 2,
        cy: y + boxH / 2,
        stage: st
      };
      nodes.push(box);
      byId[sid] = box;
    });
    return { width: svgW, height: svgH, cols: cols, rows: rows, boxW: boxW, boxH: boxH, gapX: gapX, gapY: gapY, nodes: nodes, byId: byId };
  }

  function routeEdgePath(a, b, layout, kind) {
    var isLoop = kind === "feedback_loop" || b.index < a.index;
    if (isLoop && a.row === b.row) {
      var underY = a.y + a.h + 26;
      return {
        d: "M " + a.cx + " " + (a.y + a.h) + " C " + a.cx + " " + underY + ", " + b.cx + " " + underY + ", " + b.cx + " " + (b.y + b.h),
        lx: (a.cx + b.cx) / 2,
        ly: underY + 4,
        loop: true
      };
    }
    if (a.row === b.row && Math.abs(a.col - b.col) === 1) {
      var leftToRight = b.x > a.x;
      var x1 = leftToRight ? (a.x + a.w) : a.x;
      var x2 = leftToRight ? b.x : (b.x + b.w);
      return { d: "M " + x1 + " " + a.cy + " L " + x2 + " " + b.cy, lx: (x1 + x2) / 2, ly: a.cy - 8, loop: false };
    }
    if (a.row === b.row && Math.abs(a.col - b.col) > 1) {
      var arcY = a.y - 22;
      return { d: "M " + a.cx + " " + a.y + " C " + a.cx + " " + arcY + ", " + b.cx + " " + arcY + ", " + b.cx + " " + b.y, lx: (a.cx + b.cx) / 2, ly: arcY - 2, loop: isLoop };
    }
    if (b.row === a.row + 1 && a.col === b.col) {
      return { d: "M " + a.cx + " " + (a.y + a.h) + " L " + b.cx + " " + b.y, lx: a.cx + 14, ly: (a.y + a.h + b.y) / 2, loop: isLoop };
    }
    var midGutterY = a.y + a.h + layout.gapY / 2;
    return {
      d: "M " + a.cx + " " + (a.y + a.h) + " C " + a.cx + " " + midGutterY + ", " + b.cx + " " + midGutterY + ", " + b.cx + " " + b.y,
      lx: (a.cx + b.cx) / 2,
      ly: midGutterY - 4,
      loop: isLoop
    };
  }

  function buildProcessSchematicSvg(stages, hasTrace, state, semEdges) {
    if (state && state.unknownState) {
      return '<svg viewBox="0 0 720 150" role="img" aria-label="Unknown Backing Store State"><rect x="16" y="20" width="688" height="110" rx="10" fill="#FBE0D0" stroke="#C44F2A" stroke-width="2"/><text x="36" y="64" font-size="14" font-weight="800" fill="#7A1E0A">Backing store state UNKNOWN</text><text x="36" y="94" font-size="12" fill="#5A2214">Stage count UNKNOWN</text></svg>';
    }
    var lay = computeSchematicLayout(stages);
    if (lay.nodes.length === 0) {
      return '<svg viewBox="0 0 720 140" role="img" aria-label="Empty Repository Schematic"><rect x="16" y="18" width="688" height="104" rx="10" fill="#FAF8F5" stroke="#5A6573" stroke-dasharray="6 4" stroke-width="1.6"/><text x="34" y="60" font-size="13" font-weight="800" fill="#1F2225">EMPTY · Zero matched stages</text><text x="34" y="88" font-size="12" fill="#4A4F55">Repository parsed cleanly without stages</text></svg>';
    }

    var edgeList = Array.isArray(semEdges) && semEdges.length > 0 ? semEdges : lay.nodes.slice(0, -1).map(function (n, idx) {
      return { from: n.id, to: lay.nodes[idx + 1].id, kind: "forward", witnessed: false };
    });

    var out = '<svg viewBox="0 0 ' + lay.width + ' ' + lay.height + '" role="img" aria-label="Horizontal Serpentine Process Schematic">' +
      '<defs>' +
      '<marker id="arr-fwd" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 1.5 L 9 5 L 0 8.5 z" fill="#4A7DB0"/></marker>' +
      '<marker id="arr-loop" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 1.5 L 9 5 L 0 8.5 z" fill="#B88328"/></marker>' +
      '</defs>' +
      '<text x="34" y="25" font-size="12" font-weight="800" fill="#1F2225">Horizontal Process Flow S1 → S' + lay.nodes.length + (lay.rows > 1 ? ' (Serpentine)' : '') + '</text>' +
      '<text x="' + (lay.width - 28) + '" y="25" font-size="11" font-weight="700" fill="#4A4F55" text-anchor="end">' + (hasTrace ? "● Solid: Traced Runtime" : "◌ Dashed: Static AST (Untraced)") + '</text>';

    edgeList.forEach(function (e) {
      var a = lay.byId[e.from || e.from_stage];
      var b = lay.byId[e.to || e.to_stage];
      if (!a || !b || a.id === b.id) return;
      var rt = routeEdgePath(a, b, lay, e.kind);
      var witnessed = Boolean(hasTrace && (e.witnessed === true || e.evidence === "traced"));
      var stroke = rt.loop ? "#B88328" : "#4A7DB0";
      var dash = (rt.loop || !witnessed) ? ' stroke-dasharray="5 3"' : "";
      var marker = rt.loop ? "url(#arr-loop)" : "url(#arr-fwd)";
      out += '<path d="' + rt.d + '" fill="none" stroke="' + stroke + '" stroke-width="2"' + dash + ' marker-end="' + marker + '"/>';
      if (rt.loop && e.label) {
        out += '<text x="' + Math.round(rt.lx) + '" y="' + Math.round(rt.ly) + '" font-size="11" font-weight="700" fill="#7A540E" text-anchor="middle" class="svg-halo">' + esc(shortWords(e.label, 3, 22)) + "</text>";
      }
    });

    lay.nodes.forEach(function (n) {
      var st = n.stage;
      var isFault = (st.tripwires && st.tripwires.length > 0) || st.verdict === "CODE_VIOLATES_SPEC";
      var pal = stagePalette(st.kind, isFault);
      var isSel = Boolean(state && n.id === state.activeStageId);
      var cleanTitle = shortWords(String(st.title || n.id).replace(/^S\d+\s*[·:-]?\s*/i, ""), 4, 24);
      var subCount = (st.l2_steps || []).length;
      var leadFile = ((st.files && st.files[0]) || (st.l2_steps && st.l2_steps[0] && st.l2_steps[0].code_ref && st.l2_steps[0].code_ref.file) || "");
      var footTxt = leadFile ? basename(leadFile) : (subCount + " sub-step(s)");
      var borderDash = (!hasTrace && !isSel) ? ' stroke-dasharray="5 2"' : "";

      out += '<g class="stage-node-group" data-stage-node="' + esc(n.id) + '">' +
        '<rect x="' + n.x + '" y="' + n.y + '" width="' + n.w + '" height="' + n.h + '" rx="9" fill="#FFFFFF" stroke="' + (isSel ? "#1F2225" : pal.stroke) + '" stroke-width="' + (isSel ? "2.8" : "1.8") + '"' + borderDash + '/>' +
        '<rect x="' + (n.x + 1) + '" y="' + (n.y + 1) + '" width="' + (n.w - 2) + '" height="24" rx="8" fill="' + pal.fill + '"/>' +
        '<text x="' + (n.x + 10) + '" y="' + (n.y + 17) + '" font-size="11" font-weight="800" fill="#1F2225" class="svg-halo">' + esc(n.id + " · " + pal.tag) + '</text>' +
        '<text x="' + (n.x + n.w - 9) + '" y="' + (n.y + 17) + '" font-size="11" font-weight="700" fill="#4A4F55" text-anchor="end">' + esc(subCount + " L2") + '</text>' +
        '<text x="' + (n.x + 10) + '" y="' + (n.y + 46) + '" font-size="11.5" font-weight="800" fill="#1F2225">' + esc(cleanTitle) + '</text>' +
        '<text x="' + (n.x + 10) + '" y="' + (n.y + 71) + '" font-size="11" fill="#5A5F66">' + esc(shortWords(footTxt, 2, 22)) + '</text>' +
        "</g>";
    });

    out += "</svg>";
    return out;
  }

  function buildRefactorCrosswalkSvg(refMap) {
    var oldSt = ((refMap && refMap.old_stages) || []).slice(0, 8);
    var newSt = ((refMap && refMap.target_stages) || []).slice(0, 8);
    var edges = (refMap && refMap.crosswalk_edges) || [];
    var nOld = Math.max(oldSt.length, 1);
    var nNew = Math.max(newSt.length, 1);
    var svgW = 760;
    var svgH = 250;
    var oldGap = 14;
    var oldW = Math.max(76, Math.floor((svgW - 56 - (nOld - 1) * oldGap) / nOld));
    var newGap = 18;
    var newW = Math.max(110, Math.floor((svgW - 56 - (nNew - 1) * newGap) / nNew));
    var oldCenters = {};
    var newCenters = {};

    var out = '<svg viewBox="0 0 ' + svgW + ' ' + svgH + '" role="img" aria-label="Horizontal 2-Band S* to N* Pure-Core Crosswalk">' +
      '<text x="28" y="22" font-size="11.5" font-weight="800" fill="#1F2225">Band A · Today Imperative Stages (S1–S' + oldSt.length + ')</text>' +
      '<text x="28" y="158" font-size="11.5" font-weight="800" fill="#163E6C">Band B · Proposed Pure-Core &amp; I/O Boundary Targets (N1–N' + newSt.length + ')</text>';

    oldSt.forEach(function (s, i) {
      var sid = String(s.id || s.stage_id || ("S" + (i + 1)));
      var x = 28 + i * (oldW + oldGap);
      var pal = stagePalette(s.kind, false);
      oldCenters[sid] = { x: x + oldW / 2, y: 34 + 62 };
      out += '<g class="stage-node-group" data-stage-node="' + esc(sid) + '">' +
        '<rect x="' + x + '" y="34" width="' + oldW + '" height="62" rx="7" fill="#FFFFFF" stroke="' + pal.stroke + '" stroke-width="1.7"/>' +
        '<text x="' + (x + 8) + '" y="53" font-size="11" font-weight="800" fill="#1F2225">' + esc(sid) + '</text>' +
        '<text x="' + (x + 8) + '" y="76" font-size="11" fill="#4A4F55">' + esc(shortWords(String(s.title || sid).replace(/^S\d+\s*[·:-]?\s*/i, ""), 2, 15)) + '</text></g>';
    });

    newSt.forEach(function (ns, j) {
      var nid = String(ns.id || ("N" + (j + 1)));
      var x = 28 + j * (newW + newGap);
      var isCore = Boolean(ns.is_pure_core);
      newCenters[nid] = { x: x + newW / 2, y: 170 };
      out += '<g><rect x="' + x + '" y="170" width="' + newW + '" height="62" rx="7" fill="' + (isCore ? "#DCE8F5" : "#DAEEDC") + '" stroke="' + (isCore ? "#4A7DB0" : "#4FA869") + '" stroke-width="1.8"/>' +
        '<text x="' + (x + 9) + '" y="191" font-size="11" font-weight="800" fill="#1F2225">' + esc(nid + " · " + (isCore ? "Pure Core" : "I/O Shell")) + '</text>' +
        '<text x="' + (x + 9) + '" y="214" font-size="11" fill="#1F2225">' + esc(shortWords(ns.title || nid, 3, 20)) + '</text></g>';
    });

    edges.forEach(function (e) {
      var c1 = oldCenters[e.from_stage];
      var c2 = newCenters[e.to_stage];
      if (c1 && c2) {
        out += '<path d="M ' + c1.x + ' ' + c1.y + ' C ' + c1.x + ' 132, ' + c2.x + ' 134, ' + c2.x + ' ' + c2.y + '" fill="none" stroke="#4A7DB0" stroke-width="1.8"/>';
      }
    });
    out += "</svg>";
    return out;
  }

  function buildPaperCrosswalkSvg(paperMap, stages, state) {
    var eqs = ((paperMap && paperMap.equations) || []).slice(0, 6);
    var stList = (stages || []).slice(0, 6);
    if (eqs.length === 0) return buildProcessSchematicSvg(stages, false, state);
    var svgW = 760;
    var svgH = 242;
    var eqW = Math.max(92, Math.floor((svgW - 56 - Math.max(0, eqs.length - 1) * 12) / eqs.length));
    var stW = Math.max(92, Math.floor((svgW - 56 - Math.max(0, stList.length - 1) * 12) / Math.max(1, stList.length)));
    var stC = {};

    var out = '<svg viewBox="0 0 ' + svgW + ' ' + svgH + '" role="img" aria-label="Paper Equations to Horizontal Software Stages">' +
      '<text x="28" y="22" font-size="11.5" font-weight="800" fill="#1F2225">Manuscript Equations &amp; Section Claims</text>' +
      '<text x="28" y="156" font-size="11.5" font-weight="800" fill="#163E6C">Bound Execution Stages (S1–S' + stList.length + ')</text>';

    stList.forEach(function (st, j) {
      var sid = String(st.id || ("S" + (j + 1)));
      var x = 28 + j * (stW + 12);
      var pal = stagePalette(st.kind, false);
      stC[sid] = { x: x + stW / 2, y: 168 };
      out += '<g class="stage-node-group" data-stage-node="' + esc(sid) + '">' +
        '<rect x="' + x + '" y="168" width="' + stW + '" height="58" rx="7" fill="#FFFFFF" stroke="' + pal.stroke + '" stroke-width="1.7"/>' +
        '<text x="' + (x + 8) + '" y="188" font-size="11" font-weight="800" fill="#1F2225">' + esc(sid) + '</text>' +
        '<text x="' + (x + 8) + '" y="210" font-size="11" fill="#4A4F55">' + esc(shortWords(String(st.title || sid).replace(/^S\d+\s*[·:-]?\s*/i, ""), 2, 16)) + '</text></g>';
    });

    eqs.forEach(function (eq, i) {
      var x = 28 + i * (eqW + 12);
      var isDrift = eq.verification_stamp === "MAP_DRIFT" || eq.verdict === "DIVERGENCE_SUSPECTED";
      var targetSid = (eq.maps_to_old && eq.maps_to_old[0] && eq.maps_to_old[0].stage_id) || eq.stage_id || (stList[0] && stList[0].id);
      out += '<g><rect x="' + x + '" y="34" width="' + eqW + '" height="58" rx="7" fill="' + (isDrift ? "#FBE0D0" : "#DCE8F5") + '" stroke="' + (isDrift ? "#C44F2A" : "#4A7DB0") + '" stroke-width="1.7"/>' +
        '<text x="' + (x + 8) + '" y="54" font-size="11" font-weight="800" fill="#1F2225">' + esc(shortWords("Eq " + (eq.number || eq.eq_number || eq.id || (i + 1)), 2, 14)) + '</text>' +
        '<text x="' + (x + 8) + '" y="76" font-size="11" fill="#4A4F55">' + esc(shortWords(eq.label || eq.eq_label || "Aligned", 2, 15)) + '</text></g>';
      if (targetSid && stC[targetSid]) {
        var cx1 = x + eqW / 2;
        out += '<path d="M ' + cx1 + ' 92 C ' + cx1 + ' 130, ' + stC[targetSid].x + ' 130, ' + stC[targetSid].x + ' ' + stC[targetSid].y + '" fill="none" stroke="' + (isDrift ? "#C44F2A" : "#4A7DB0") + '" stroke-width="1.8"' + (isDrift ? ' stroke-dasharray="5 3"' : '') + '/>';
      }
    });
    out += "</svg>";
    return out;
  }

  function buildCompactRailSvg(stages, hasTrace, state) {
    var list = Array.isArray(stages) ? stages : [];
    if (list.length === 0) return buildProcessSchematicSvg(list, hasTrace, state);
    var rowGap = 76;
    var svgH = 40 + list.length * rowGap;
    var out = '<svg viewBox="0 0 340 ' + svgH + '" role="img" aria-label="Compact 25% Live Process Rail">' +
      '<text x="12" y="20" font-size="11.5" font-weight="800" fill="#1F2225">25% Live Stage Rail</text>' +
      '<text x="328" y="20" font-size="11" fill="#4A4F55" text-anchor="end">' + (hasTrace ? "● Traced" : "◌ Static") + '</text>';
    list.forEach(function (st, idx) {
      var sid = String(st.id || ("S" + (idx + 1)));
      var y = 32 + idx * rowGap;
      var pal = stagePalette(st.kind, false);
      var isSel = Boolean(state && sid === state.activeStageId);
      out += '<g class="stage-node-group" data-stage-node="' + esc(sid) + '">' +
        '<rect x="12" y="' + y + '" width="316" height="56" rx="7" fill="#FFFFFF" stroke="' + (isSel ? "#1F2225" : pal.stroke) + '" stroke-width="' + (isSel ? "2.5" : "1.6") + '"/>' +
        '<rect x="13" y="' + (y + 1) + '" width="314" height="20" rx="6" fill="' + pal.fill + '"/>' +
        '<text x="22" y="' + (y + 15) + '" font-size="11" font-weight="800" fill="#1F2225">' + esc(sid + " · " + pal.tag) + '</text>' +
        '<text x="22" y="' + (y + 42) + '" font-size="11.2" font-weight="700" fill="#1F2225">' + esc(shortWords(String(st.title || sid).replace(/^S\d+\s*[·:-]?\s*/i, ""), 4, 28)) + '</text></g>';
      if (idx < list.length - 1) {
        out += '<line x1="170" y1="' + (y + 56) + '" x2="170" y2="' + (y + rowGap - 2) + '" stroke="#4A7DB0" stroke-width="1.6"' + (hasTrace ? "" : ' stroke-dasharray="4 3"') + '/>';
      }
    });
    out += "</svg>";
    return out;
  }

  function renderExpandedL2StripHtml(stage, hasTrace) {
    if (!stage) return "";
    var steps = stage.l2_steps || [];
    var wallTxt = hasTrace && typeof stage.wall_pct === "number" ? (stage.wall_pct.toFixed(1) + "% measured runtime share") : "Wall-time share: unmeasured (static AST)";
    return '<div class="l2-subdiagram-strip" data-l2-strip="' + esc(stage.id || "") + '">' +
      '<div class="deck-row"><span style="font-size:11.5px;font-weight:800;">↳ Expanded L2 Sub-Diagram · ' + esc(stage.id || "") + ' (' + steps.length + ' step(s))</span><span class="prov-tag">' + esc(wallTxt) + "</span></div>" +
      (steps.length > 0
        ? '<div class="l2-horiz-cards">' + steps.map(function (sb, idx) {
            var cr = sb.code_ref || { file: sb.file || "", start_line: sb.start_line || 1 };
            var sid = sb.id || sb.step_id || ((stage.id || "S1") + "." + (idx + 1));
            return '<button type="button" class="l2-horiz-card" data-left-l2-file="' + esc(cr.file || "") + '" data-left-l2-line="' + Number(cr.start_line || 1) + '">' +
              '<div style="font-size:11px;font-weight:800;color:#163E6C;">' + esc(sid) + "</div>" +
              '<div style="font-size:11.5px;font-weight:700;margin-top:2px;">' + esc(shortWords(sb.title || sid, 5, 34)) + "</div>" +
              (cr.file ? '<div style="font-family:var(--font-mono);font-size:11px;color:var(--ink-soft);margin-top:3px;">' + esc(basename(cr.file) + ":L" + (cr.start_line || 1)) + "</div>" : "") +
            "</button>";
          }).join('<span class="l2-arrow-sep">→</span>') + "</div>"
        : '<div style="font-size:11.5px;color:var(--ink-soft);margin-top:4px;">0 granular L2 sub-steps extracted for this stage.</div>') +
      "</div>";
  }

  function renderPaperCrosswalkInspector(body, ctx) {
    var state = ctx.state;
    var p2 = ctx.p2;
    var safeMathMlHtml = ctx.safeMathMlHtml;
    var pm = (state.bundle && state.bundle.paper_map) || {};
    var rows = (p2 && p2.paper_aligned_rows && p2.paper_aligned_rows.length > 0) ? p2.paper_aligned_rows : ((pm.equations || []).map(function (eq, idx) {
      var m0 = (eq.matched_functions && eq.matched_functions[0]) || {};
      return { row_id: eq.id || ("eq-" + (idx + 1)), stage_id: "S" + ((idx % Math.max(1, ctx.stages.length)) + 1), eq_label: eq.label || eq.id || ("Eq " + (idx + 1)), eq_number: eq.number || "", section: eq.section || "Main", mathml: eq.mathml || "", paper_tex: eq.raw_latex || eq.label || "", code_symbol: (m0.file ? m0.file + ":" : "") + (m0.qualname || "<unbound>"), code_file: m0.file || "", start_line: m0.lineno || 1, verdict: eq.verification_stamp || "STATIC_MATCH", rationale: eq.drift_reason || "Static identifier/operator alignment.", display_state: "NO_RECEIPT" };
    }));
    var r2a = (p2 && p2.ramanujan_audit && p2.ramanujan_audit.pass2a_paper_to_code) || [];
    var r2b = (p2 && p2.ramanujan_audit && p2.ramanujan_audit.pass2b_code_to_paper) || [];

    var toggleHtml = '<div class="deck-row"><strong style="font-size:12px;">Side-by-Side Manuscript MathML ⇄ Code Crosswalk</strong>' +
      '<div class="selector-group"><button type="button" class="small-btn' + (state.paperNodeView === "S" ? " active" : "") + '" data-paper-node-mode="S">Current Stages (S*)</button>' +
      '<button type="button" class="small-btn' + (state.paperNodeView === "N" ? " active" : "") + '" data-paper-node-mode="N">Pure Core (N*)</button></div></div>';

    var findingsHtml = [].concat(r2a, r2b).map(function (f) {
      var isUnreached = f.grounding_status === "GROUNDED_UNREACHED";
      return '<div class="card-block fault-card"><div class="deck-row"><strong>' + esc(f.direction === "code_to_paper" ? "⇄ Pass 2b (Code → Paper): " : "⇄ Pass 2a (Paper → Code): ") + esc(f.title) + "</strong>" +
        '<span class="badge-claimed-amber">' + esc(isUnreached ? "GROUNDED_UNREACHED / OVERRIDDEN" : (f.verdict || "DIVERGENCE")) + "</span></div>" +
        '<div style="margin-top:4px;"><strong>Paper:</strong> ' + esc(f.paper_claim) + "</div>" +
        '<div style="margin-top:3px;"><strong>Executed Code:</strong> ' + esc(f.code_reality) + "</div>" +
        (f.slice_truncated ? '<div style="margin-top:3px;font-size:11px;color:#7A540E;">[SLICE_TRUNCATED: bounded 12 KB AST priority slice]</div>' : "") + "</div>";
    }).join("");

    body.innerHTML = toggleHtml + findingsHtml + rows.map(function (r) {
      var nodeBadge = state.paperNodeView === "N" ? String(r.stage_id || "S1").replace("S", "N") : (r.stage_id || "S1");
      var isDiv = r.verdict === "DIVERGENCE_SUSPECTED" || r.verdict === "MAP_DRIFT";
      var gWarn = (r.grounding_warnings && r.grounding_warnings.length > 0) ? '<div style="margin-top:4px;font-size:11px;font-weight:700;color:#7A540E;">⚠ GROUNDED_UNREACHED / OVERRIDDEN: ' + esc(r.grounding_warnings[0]) + "</div>" : "";
      return '<article class="paper-aligned-row' + (isDiv ? " fault-card" : "") + '">' +
        '<div class="paper-col"><div class="deck-row"><strong>' + esc((r.eq_number ? "Eq (" + r.eq_number + ") · " : "") + r.eq_label) + '</strong><span class="prov-tag">' + esc(r.section || "Main") + "</span></div>" +
          '<div class="mathml-wrap" style="margin-top:5px;">' + safeMathMlHtml(r.mathml, r.paper_tex || r.eq_label) + "</div></div>" +
        '<div class="code-col"><div class="deck-row"><span class="prov-tag">' + esc(nodeBadge) + '</span><span class="' + (isDiv ? "badge-fault-red" : "badge-neutral-slate") + '">' + esc(r.verdict || "STATIC_MATCH") + "</span></div>" +
          '<div style="margin-top:5px;font-family:var(--font-mono);font-size:11.5px;">' + esc(r.code_symbol || "") + "</div>" +
          '<div style="margin-top:4px;color:var(--ink-soft);">' + esc(r.rationale || "") + "</div>" + gWarn +
          (r.code_file ? '<div style="margin-top:5px;"><button type="button" class="small-btn" data-jump-file="' + esc(r.code_file) + '" data-jump-line="' + Number(r.start_line || 1) + '">Jump to ' + esc(basename(r.code_file) + ":L" + (r.start_line || 1)) + " ⤢</button></div>" : "") +
        "</div></article>";
    }).join("");

    body.querySelectorAll("[data-paper-node-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () { state.paperNodeView = btn.getAttribute("data-paper-node-mode") || "S"; ctx.renderInspector(); });
    });
    ctx.bindPinAndJumpButtons(body);
  }

  function renderProfileAndLiteratureInspector(body, ctx) {
    var state = ctx.state;
    var hasTrace = Boolean(state.bundle && state.bundle.has_trace);
    var stages = ctx.stages;
    var lit = state.literatureData || {};
    var swMap = (state.scopingState && state.scopingState.software_map) || {};
    var tier0 = (swMap.manuscript_citations && swMap.manuscript_citations.entries) || [];
    var tier1Claims = Array.isArray(lit.claims) ? lit.claims : [];

    body.innerHTML =
      '<div class="card-block"><div class="deck-row"><strong>Stage Complexity &amp; Runtime Flame Ribbon</strong><span class="prov-tag">' + (hasTrace ? "● Measured Trace" : "◌ Static Unmeasured") + "</span></div>" +
        '<div class="flame-ribbon">' + stages.map(function (s) {
          var lbl = hasTrace && typeof s.wall_pct === "number" ? (s.id + " (" + s.wall_pct.toFixed(0) + "%)") : (s.id + " (unmeasured)");
          return '<div class="flame-seg">' + esc(lbl) + "</div>";
        }).join("") + "</div></div>" +
      '<div class="card-block"><div class="deck-row"><strong>📚 Tier-0 Local Manuscript Citations (`MANUSCRIPT_CITED`: ' + tier0.length + ')</strong>' +
        '<button type="button" id="btnWorkbenchLitConsent" class="consent-run-btn">🌐 Validate via researchPrime (2-Click Consent)</button></div>' +
        (tier0.length > 0 ? '<div style="margin-top:6px;display:flex;flex-direction:column;gap:4px;">' + tier0.slice(0, 10).map(function (e) {
          return '<div style="font-size:11.5px;">• <code>' + esc(e.cite_key) + "</code> — " + esc(e.title || "") + (e.year ? " (" + esc(e.year) + ")" : "") + (e.doi ? ' · <span class="prov-tag">DOI:' + esc(e.doi) + "</span>" : "") + "</div>";
        }).join("") + "</div>" : '<div style="margin-top:4px;color:var(--ink-soft);">Open Scope Map or load `.bib` to list local manuscript citations.</div>') + "</div>" +
      (tier1Claims.length > 0 ? '<div class="card-block active-card"><strong>✓ Tier-1 Quote-Grounded Literature Ledger (' + tier1Claims.length + ')</strong>' + tier1Claims.map(function (c) {
        return '<div class="layer-subcard"><div class="deck-row"><strong>' + esc((c.source && c.source.title) || c.claim_id) + '</strong><span class="badge-claimed-amber">' + esc(c.posture || "QUOTE_VERIFIED") + "</span></div><div>" + esc(c.statement || "") + '</div><div style="margin-top:3px;font-style:italic;color:var(--ink-soft);">"' + esc(c.quote || "") + '"</div></div>';
      }).join("") + "</div>" : "");

    var litBtn = document.getElementById("btnWorkbenchLitConsent");
    if (litBtn && ctx.openLiteraturePrivacyModal) litBtn.addEventListener("click", function () { ctx.openLiteraturePrivacyModal(litBtn); });
  }

  function renderLeftPaneDom(ctx) {
    var state = ctx.state;
    if (!(state.active || state.unknownState) || state.launcherOpen) return;
    var b = state.bundle;
    var p2 = ctx.p2;
    var stages = ctx.stages;
    var hasTrace = Boolean(b && b.has_trace);
    var svgBox = document.getElementById("svg-container");
    var l0Bar = document.getElementById("l0-scenario-bar");
    var scrub = document.getElementById("scrubber-bar");
    var railL2 = document.getElementById("rail-l2-container");
    var nullShelf = document.getElementById("null-shelf-container");
    var detailCard = document.getElementById("left-stage-detail-card");
    var heading = document.getElementById("left-map-heading");

    var l0List = (p2 && p2.l0_scenarios) || (b && b.process_map && b.process_map.l0_scenarios) || [];
    if (!state.ideOpen && l0List.length > 0 && !state.unknownState) {
      l0Bar.hidden = false;
      l0Bar.innerHTML = l0List.map(function (sc, idx) {
        return '<button type="button" class="l0-pill' + (idx === state.activeScenarioIdx ? " active" : "") + '" data-l0-idx="' + idx + '">' + esc(stripDollars(sc.title || sc.scenario_id || ("Scenario " + (idx + 1)))) + "</button>";
      }).join("");
      l0Bar.querySelectorAll("[data-l0-idx]").forEach(function (btn) {
        btn.addEventListener("click", function () { state.activeScenarioIdx = Number(btn.getAttribute("data-l0-idx")) || 0; ctx.renderAll(); });
      });
    } else l0Bar.hidden = true;

    if (state.ideOpen) {
      heading.textContent = "Live Process Rail";
      svgBox.innerHTML = buildCompactRailSvg(stages, hasTrace, state);
      nullShelf.hidden = true; scrub.hidden = true; detailCard.hidden = true;
      var actSt = ctx.actStage;
      if (actSt && (actSt.l2_steps || []).length > 0 && !state.unknownState) {
        railL2.hidden = false;
        railL2.innerHTML = '<div style="font-size:11.5px;font-weight:800;">Active L2 Sub-Steps · ' + esc(actSt.id) + "</div>" +
          actSt.l2_steps.map(function (sub) {
            var cr = sub.code_ref || {};
            return '<button type="button" class="rail-l2-btn' + (sub.id === state.activeStepId ? " active" : "") + '" data-rail-step="' + esc(sub.id) + '" data-rail-file="' + esc(cr.file || "") + '" data-rail-line="' + Number(cr.start_line || 1) + '"><span><strong>' + esc(sub.id) + "</strong> " + esc(shortWords(sub.title || sub.id, 4, 24)) + '</span><span style="font-family:var(--font-mono);font-size:11px;">' + esc(basename(cr.file || "") + ":L" + (cr.start_line || 1)) + "</span></button>";
          }).join("");
        railL2.querySelectorAll("[data-rail-step]").forEach(function (btn) {
          btn.addEventListener("click", function () {
            state.activeStepId = btn.getAttribute("data-rail-step") || "1.1";
            if (btn.getAttribute("data-rail-file")) state.activeFile = btn.getAttribute("data-rail-file");
            state.activeLine = Number(btn.getAttribute("data-rail-line")) || 1;
            ctx.persistSessionState(); ctx.renderAll();
          });
        });
      } else railL2.hidden = true;
    } else {
      railL2.hidden = true;
      if (state.lens === "refactor" && b && b.refactor_map && !state.unknownState) {
        heading.textContent = "Horizontal 2-Band Refactor Crosswalk (S1–Sk → N1–Nk)";
        svgBox.innerHTML = buildRefactorCrosswalkSvg(b.refactor_map);
        var ns = (p2 && p2.null_set) || b.refactor_map.null_set || {};
        var c1 = (ns.tier1_dead || ns.null_proven || []).length;
        var c2 = (ns.tier2_plumbing || ns.null_unexercised || []).length;
        var c3 = (ns.tier3_io_harness || ns.null_redundant || []).length;
        nullShelf.hidden = false;
        nullShelf.innerHTML = '<div class="deck-row"><span style="font-weight:800;font-size:12px;">3-Tier ∅ Null Set Disposition Shelf</span><span class="prov-tag">Symbol Conservation Verified</span></div>' +
          '<div class="kv-grid"><div class="kv-box"><div class="kv-lbl">Tier 1 · Unreached / Dead</div><div><strong>' + c1 + '</strong> symbols</div></div>' +
          '<div class="kv-box"><div class="kv-lbl">Tier 2 · CLI &amp; Config Plumbing</div><div><strong>' + c2 + '</strong> modules</div></div>' +
          '<div class="kv-box"><div class="kv-lbl">Tier 3 · I/O &amp; Table Shell</div><div><strong>' + c3 + '</strong> scripts</div></div></div>';
      } else if (state.lens === "paper" && b && b.paper_map && !state.unknownState) {
        heading.textContent = "Paper Equations ⇄ Horizontal Software Stages";
        nullShelf.hidden = true;
        svgBox.innerHTML = buildPaperCrosswalkSvg(b.paper_map, stages, state);
      } else {
        heading.textContent = "Horizontal Serpentine Process Schematic (L1 + L2)";
        nullShelf.hidden = true;
        svgBox.innerHTML = buildProcessSchematicSvg(stages, hasTrace, state, p2 ? p2.edges : (b && b.process_map && b.process_map.edges ? b.process_map.edges : null));
      }

      scrub.hidden = Boolean(state.unknownState || stages.length === 0);
      if (!scrub.hidden) {
        scrub.innerHTML = hasTrace
          ? '<div class="deck-row"><strong style="font-size:11.5px;">● Runtime Step Scrubber</strong><div class="selector-group">' + stages.map(function (s) { return '<button type="button" class="small-btn" data-scrub-stage="' + esc(s.id) + '">' + esc(s.id) + "</button>"; }).join("") + "</div></div>"
          : '<div style="font-size:11.5px;color:var(--ink-soft);"><strong>◌ Static AST + LaTeX Mode:</strong> Runtime timeline inactive until operator runs a consented local trace.</div>';
        scrub.querySelectorAll("[data-scrub-stage]").forEach(function (btn) { btn.addEventListener("click", function () { ctx.selectStage(btn.getAttribute("data-scrub-stage")); }); });
      }

      var actStage = ctx.actStage;
      if (state.unknownState) {
        detailCard.hidden = false;
        detailCard.innerHTML = '<div style="font-weight:800;color:#7A1E0A;">Stage Details: UNKNOWN (Backing store unreadable)</div>';
      } else if (actStage) {
        detailCard.hidden = false;
        detailCard.innerHTML = renderExpandedL2StripHtml(actStage, hasTrace) +
          '<div class="kv-grid" style="margin-top:8px;">' +
            '<div class="kv-box"><div class="kv-lbl">What Enters</div><div>' + esc((actStage.what_enters || ["inputs"]).join(", ")) + "</div></div>" +
            '<div class="kv-box"><div class="kv-lbl">Actions Run</div><div>' + esc(shortWords((actStage.actions_run || ["AST unit"]).join("; "), 8, 60)) + "</div></div>" +
            '<div class="kv-box"><div class="kv-lbl">What Exits</div><div>' + esc((actStage.what_exits || ["outputs"]).join(", ")) + "</div></div></div>";
        detailCard.querySelectorAll("[data-left-l2-file]").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var rf = btn.getAttribute("data-left-l2-file") || "";
            if (rf) state.activeFile = rf;
            state.activeLine = Number(btn.getAttribute("data-left-l2-line")) || 1;
            state.ideOpen = true; ctx.persistSessionState(); ctx.renderAll();
          });
        });
      } else {
        detailCard.hidden = false;
        detailCard.innerHTML = "<div>EMPTY · 0 stages matched in repository.</div>";
      }
    }

    svgBox.querySelectorAll("[data-stage-node]").forEach(function (g) {
      g.addEventListener("click", function () { ctx.selectStage(g.getAttribute("data-stage-node")); });
    });
  }

  var api = {
    computeSchematicLayout: computeSchematicLayout,
    buildProcessSchematicSvg: buildProcessSchematicSvg,
    buildRefactorCrosswalkSvg: buildRefactorCrosswalkSvg,
    buildPaperCrosswalkSvg: buildPaperCrosswalkSvg,
    buildCompactRailSvg: buildCompactRailSvg,
    renderExpandedL2StripHtml: renderExpandedL2StripHtml,
    renderLeftPaneDom: renderLeftPaneDom,
    renderPaperCrosswalkInspector: renderPaperCrosswalkInspector,
    renderProfileAndLiteratureInspector: renderProfileAndLiteratureInspector
  };

  root.AnvilSchematic = api;
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
