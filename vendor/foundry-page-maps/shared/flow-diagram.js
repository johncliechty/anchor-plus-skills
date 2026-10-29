/* Shared Foundry flow-diagram component (Refinement 2).
   Pure string renderer: process data + declared layout in, SVG out. No DOM, no
   fetch, no model calls — usable from any skill bundle page and from node tests. */
(function (root) {
  'use strict';
  const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const TYPES = {
    'program': 'Program / code',
    'model-call': 'Model call',
    'instruction': 'Instruction (SKILL.md prose)',
    'human-gate': 'Human gate',
    'adversarial-review': 'Adversarial review',
  };

  function wrapTitle(title, max) {
    const words = String(title).split(' ');
    const lines = [''];
    for (const word of words) {
      const current = lines[lines.length - 1];
      if (current && (current + ' ' + word).length > max) lines.push(word);
      else lines[lines.length - 1] = current ? current + ' ' + word : word;
    }
    return lines.slice(0, 2).map((line, i) => (i === 1 && lines.length > 2) ? line + '…' : line);
  }

  function nodeShape(type, kind, x, y, w, h) {
    // Shape = role in the flow; fill class = who performs the step.
    if (type === 'human-gate') {
      const cx = x + w / 2, cy = y + h / 2, ex = 14;
      return `<polygon class="fd-shape" points="${x - ex},${cy} ${cx},${y - 5} ${x + w + ex},${cy} ${cx},${y + h + 5}"/>`;
    }
    if (type === 'adversarial-review') {
      const cut = 13, cy = y + h / 2;
      return `<polygon class="fd-shape" points="${x + cut},${y} ${x + w - cut},${y} ${x + w},${cy} ${x + w - cut},${y + h} ${x + cut},${y + h} ${x},${cy}"/>`;
    }
    const r = kind === 'terminal' ? h / 2 : 7;
    return `<rect class="fd-shape" x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}"/>`;
  }

  function renderFlowDiagram(process, opts = {}) {
    const d = process.diagram;
    const steps = new Map(process.steps.map(s => [s.id, s]));
    const selected = opts.selected && steps.has(opts.selected) ? opts.selected : null;
    const flagged = new Set();
    for (const item of process.disagreements || []) for (const sid of item.step_ids || []) flagged.add(sid);
    const colW = d.col_width, rowH = d.row_height, w = d.node_width, h = d.node_height;
    const cells = Object.values(d.nodes);
    const cols = 1 + Math.max(...cells.map(p => p.col));
    const rows = 1 + Math.max(...cells.map(p => p.row));
    const padX = 56, padY = 36;
    const width = padX * 2 + (cols - 1) * colW + w;
    const height = padY * 2 + (rows - 1) * rowH + h;
    const pos = id => {
      const p = d.nodes[id];
      return {x: padX + p.col * colW, y: padY + p.row * rowH, cx: padX + p.col * colW + w / 2, cy: padY + p.row * rowH + h / 2};
    };

    // Native pixel size: nodes stay readable at every viewport and the host
    // pans inside an overflow box instead of shrinking the drawing to fit.
    let svg = `<svg class="flow-diagram" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="Process flow diagram: every box is a source-anchored step">`;
    svg += '<defs>'
      + '<marker id="fd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7.5" markerHeight="7.5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker>'
      + '<marker id="fd-arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker>'
      + '</defs>';

    for (const band of d.bands || []) {
      const top = padY + band.from_row * rowH - 14;
      const bottom = padY + band.to_row * rowH + h + 14;
      svg += `<rect class="fd-band" x="8" y="${top}" width="${width - 16}" height="${bottom - top}" rx="12"/>`
        + `<text class="fd-band-title" x="${width - 18}" y="${top + 17}" text-anchor="end">${esc(band.title)}</text>`;
    }

    // Edges. Deterministic orthogonal routing: adjacent same-column edges run
    // straight; everything else travels the gutters so lines never cross a box.
    let edges = '';
    process.edges.forEach((e, i) => {
      const s = pos(e.source), t = pos(e.target);
      const active = selected && (e.source === selected || e.target === selected);
      const chan = (i % 5 - 2) * 5;
      let path;
      if (t.y === s.y) {
        const off = (i % 3 - 1) * 9;
        path = s.cx < t.cx
          ? `M ${s.x + w} ${s.cy + off} H ${t.x - 2}`
          : `M ${s.x} ${s.cy + off} H ${t.x + w + 2}`;
      } else if (t.y > s.y) {
        if (t.cx === s.cx && t.y - s.y === rowH) {
          path = `M ${s.cx} ${s.y + h} V ${t.y - 2}`;
        } else {
          const laneX = s.cx >= t.cx ? t.x + w + 16 + (i % 4) * 6 : t.x - 16 - (i % 4) * 6;
          path = `M ${s.cx + chan} ${s.y + h} V ${s.y + h + 13 + chan} H ${laneX} V ${t.y - 11 - Math.abs(chan)} H ${t.cx + chan} V ${t.y - 2}`;
        }
      } else {
        const enterRight = s.cx >= t.cx;
        const railX = enterRight ? t.x + w + 18 + (i % 5) * 6 : t.x - 18 - (i % 5) * 6;
        const exitX = railX > s.cx ? s.x + w : s.x;
        const endX = enterRight ? t.x + w + 2 : t.x - 2;
        path = `M ${exitX} ${s.cy + chan} H ${railX} V ${t.cy + chan} H ${endX}`;
      }
      const label = `${steps.get(e.source).title} → ${steps.get(e.target).title}: ${e.label}`;
      edges += `<path class="fd-edge${active ? ' active' : ''}" d="${path}" marker-end="url(#fd-arrow${active ? '-active' : ''})"><title>${esc(label)}</title></path>`;
    });
    svg += edges;

    for (const step of process.steps) {
      const p = pos(step.id);
      const lines = wrapTitle(step.title, 24);
      const href = opts.href ? opts.href(step.id) : '#process/' + step.id;
      const textY = p.y + (lines.length === 1 ? 29 : 22);
      svg += `<a href="${esc(href)}" data-step="${esc(step.id)}" class="fd-node ${esc(step.display_type)}${step.kind === 'terminal' ? ' terminal' : ''}${step.id === selected ? ' selected' : ''}"`
        + `${step.id === selected ? ' aria-current="step"' : ''} aria-label="${esc(step.title)} (${esc(TYPES[step.display_type] || step.display_type)})">`
        + `<title>${esc(step.title)} · ${esc(TYPES[step.display_type] || step.display_type)} — ${esc(step.summary)}</title>`
        + nodeShape(step.display_type, step.kind, p.x, p.y, w, h)
        + `<text class="fd-type" x="${p.cx}" y="${p.y + 11}" text-anchor="middle">${esc((TYPES[step.display_type] || '').toUpperCase())}</text>`
        + lines.map((line, i) => `<text class="fd-title" x="${p.cx}" y="${textY + i * 13}" text-anchor="middle">${esc(line)}</text>`).join('')
        + (flagged.has(step.id) ? `<g class="fd-flag"><circle cx="${p.x + w - 3}" cy="${p.y + 2}" r="8"/><text x="${p.x + w - 3}" y="${p.y + 5.5}" text-anchor="middle">≠</text></g>` : '')
        + '</a>';
    }
    return svg + '</svg>';
  }

  function legend() {
    const swatches = Object.entries(TYPES).map(([type, label]) =>
      `<span class="fd-key ${type}"><i></i>${esc(label)}</span>`).join('');
    return `<div class="fd-legend">${swatches}<span class="fd-key terminal"><i></i>Stop / handback</span>`
      + `<span class="fd-key flag"><i>≠</i>Instructions and code disagree here (see the reconciliation record)</span>`
      + `<p class="fd-gate-note">A <strong>gate</strong> (diamond) is a point where the flow stops until a decision — APPROVE, EDIT or ABORT — chooses the outgoing branch; nothing downstream runs before that choice. Click a box to select that step and pan to it. Expand the record below for its summary and links. Click a source button to open the actual code or instruction text.</p></div>`;
  }

  const style = `<style data-foundry-flow>
.flow-diagram{display:block;background:#10141d;border-radius:10px}
.flow-diagram .fd-band{fill:#161b26;stroke:#262d3c}
.flow-diagram .fd-band-title{fill:#8c95a6;font:600 11px 'Segoe UI',system-ui,sans-serif;letter-spacing:.09em;text-transform:uppercase}
.flow-diagram .fd-edge{fill:none;stroke:#4d5a71;stroke-width:1.4;opacity:.75}
.flow-diagram .fd-edge.active{stroke:#9ec0ff;stroke-width:2.4;opacity:1}
.flow-diagram marker path{fill:#4d5a71}
.flow-diagram #fd-arrow-active path{fill:#9ec0ff}
.flow-diagram .fd-shape{fill:#1c212d;stroke-width:1.6}
.flow-diagram .program .fd-shape{stroke:#8e99ad}
.flow-diagram .model-call .fd-shape{stroke:#7fa4f6;fill:#1a2233}
.flow-diagram .instruction .fd-shape{stroke:#b391ea;stroke-dasharray:5 3;fill:#201d2d}
.flow-diagram .human-gate .fd-shape{stroke:#efbc6a;fill:#2a2315}
.flow-diagram .adversarial-review .fd-shape{stroke:#6fd3bb;fill:#15261f}
.flow-diagram .terminal .fd-shape{stroke:#e79b9b}
.flow-diagram .fd-type{fill:#99a3b4;font:600 7.5px 'Segoe UI',system-ui,sans-serif;letter-spacing:.07em}
.flow-diagram .fd-title{fill:#e6e9ef;font:600 11px 'Segoe UI',system-ui,sans-serif}
.flow-diagram a.fd-node:hover .fd-shape,.flow-diagram a.fd-node:focus .fd-shape{stroke-width:3;filter:brightness(1.25)}
.flow-diagram a.fd-node.selected .fd-shape{stroke:#fff;stroke-width:2.6}
.flow-diagram .fd-flag circle{fill:#452d35;stroke:#e79bb4;stroke-width:1.2}
.flow-diagram .fd-flag text{fill:#f1b8cc;font:700 11px 'Segoe UI',system-ui,sans-serif}
.fd-legend{display:flex;gap:12px 16px;flex-wrap:wrap;align-items:center;font-size:12px;color:#a4acba;margin:12px 0}
.fd-key{display:inline-flex;align-items:center;gap:6px}
.fd-key i{display:inline-block;width:13px;height:13px;border-radius:3px;border:2px solid #8e99ad;background:#1c212d;font-style:normal;line-height:9px;text-align:center;font-size:9px}
.fd-key.model-call i{border-color:#7fa4f6;background:#1a2233}
.fd-key.instruction i{border-style:dashed;border-color:#b391ea;background:#201d2d}
.fd-key.human-gate i{border-color:#efbc6a;background:#2a2315;transform:rotate(45deg);border-radius:2px}
.fd-key.adversarial-review i{border-color:#6fd3bb;background:#15261f;border-radius:7px}
.fd-key.terminal i{border-color:#e79b9b;border-radius:7px}
.fd-key.flag i{border-color:#e79bb4;background:#452d35;color:#f1b8cc;border-radius:7px}
.fd-gate-note{flex-basis:100%;margin:2px 0 0;font-size:12px;color:#a4acba;max-width:90ch}
</style>`;

  root.FoundryFlowDiagram = {renderFlowDiagram, legend, style, TYPES};
})(globalThis);
