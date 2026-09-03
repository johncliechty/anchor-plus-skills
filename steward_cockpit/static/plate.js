/* Exploded-assembly plate for one key deliverable. Not the plan list. */
"use strict";
(function (global) {
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function byId(parts, id) {
    return (parts || []).find((p) => p.id === id) || null;
  }

  function pointerLine(p) {
    if (!p || !p.pointer) return "";
    const f = p.pointer.file || "";
    const h = p.pointer.heading || "";
    return h ? (f + " · " + h) : f;
  }

  function paintNode(p) {
    const kind = p.kind || "part";
    const node = el("div", "plat-node " + kind);
    node.dataset.id = p.id || "";
    node.appendChild(el("div", "plat-lab", p.label || p.id || ""));
    if (kind === "socket") node.appendChild(el("div", "plat-hole", p.note || "reserved"));
    const det = el("div", "plat-det");
    const ptr = pointerLine(p);
    if (ptr) det.appendChild(el("div", "plat-ptr", ptr));
    (p.children || []).forEach((ch) => {
      det.appendChild(el("div", "plat-child " + (ch.kind || ""), ch.label || ch.id));
    });
    node.appendChild(det);
    node.onclick = (ev) => {
      ev.stopPropagation();
      node.classList.toggle("on");
    };
    return node;
  }

  function paintPlate(host, plate) {
    host.textContent = "";
    if (!plate) {
      host.appendChild(el("p", "wphint", "No plate authored for this deliverable yet."));
      return;
    }
    const wrap = el("div", "wpplat");
    const spine = el("div", "wpspine");
    spine.appendChild(el("div", "plat-cap", "reading spine"));
    const parts = plate.parts || [];
    const ids = plate.spine || parts.filter((p) => p.slot === "spine").map((p) => p.id);
    ids.forEach((id, i) => {
      const p = byId(parts, id);
      if (!p) return;
      if (i) spine.appendChild(el("div", "plat-join", "↓"));
      spine.appendChild(paintNode(p));
    });
    wrap.appendChild(spine);

    const hang = el("div", "wphang");
    hang.appendChild(el("div", "plat-cap", "hangs off a claim"));
    const hangers = parts.filter((p) => p.slot === "hanger");
    if (!hangers.length) hang.appendChild(el("div", "plat-empty", "(nothing hanging)"));
    hangers.forEach((p) => {
      const box = el("div", "plat-hangwrap");
      const from = byId(parts, p.hangsFrom);
      box.appendChild(el("div", "plat-lead",
        (p.jointLabel || "depends-on") + " ← " + ((from && from.label) || p.hangsFrom || "")));
      box.appendChild(paintNode(p));
      hang.appendChild(box);
    });
    wrap.appendChild(hang);

    const sub = el("div", "wpsub");
    sub.appendChild(el("div", "plat-cap", "substrate — what the paper sits on"));
    const row = el("div", "wpsubrow");
    const subs = parts.filter((p) => p.slot === "substrate");
    if (!subs.length) row.appendChild(el("div", "plat-empty", "(no substrate)"));
    subs.forEach((p, i) => {
      if (i) row.appendChild(el("div", "plat-iface", "interfaces-with"));
      row.appendChild(paintNode(p));
    });
    sub.appendChild(row);
    wrap.appendChild(sub);
    host.appendChild(wrap);
  }

  function paintAtlas(bar, plates, currentId, onPick) {
    if (!bar) return;
    bar.textContent = "";
    (plates || []).forEach((pl) => {
      const b = el("button", "plat-chip" + (pl.deliverableId === currentId ? " on" : ""),
                   pl.title || pl.deliverableId);
      b.onclick = (ev) => { ev.preventDefault(); onPick(pl.deliverableId); };
      bar.appendChild(b);
    });
  }

  global.DeliverablePlate = { paintPlate, paintAtlas };
})(window);
