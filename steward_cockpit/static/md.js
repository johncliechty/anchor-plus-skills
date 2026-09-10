/* Safe, small markdown renderer for human-facing reports.
   DOM-building only (textContent) - never innerHTML with document text.
   Covers: #-#### headings, hr, > quotes, -/* lists, 1. lists, ``` fences,
   | tables, paragraphs; inline **bold**, `code`, [text](http-links). */
"use strict";
// Report links belong to the Anchor origin the reader is using. Historical
// steward replies hard-coded the author's loopback host, which is another
// machine when opened remotely. Keep external paper URLs untouched.
function mdReportHref(raw) {
  const current = new URL(window.location.href);
  let dest;
  try { dest = new URL(raw, current.origin); }
  catch (_) { return raw; } // An invalid document link must not erase the turn.
  const internal = /^\/artifact\/[^/]+$/.test(dest.pathname) ||
    dest.pathname === "/api/steward/deliverable-file";
  const legacy = dest.origin === "http://127.0.0.1:8777";
  if (internal && !dest.username && !dest.password &&
      (dest.origin === current.origin || legacy)) {
    dest.searchParams.delete("token");
    if (window.STEWARD_TOKEN) dest.searchParams.set("token", window.STEWARD_TOKEN);
    return dest.pathname + dest.search + dest.hash;
  }
  return raw;
}
function mdRender(container, text) {
  const el = (t, c, x) => { const n = document.createElement(t);
    if (c) n.className = c; if (x !== undefined) n.textContent = x; return n; };
  function inline(node, s) {
    const parts = String(s).split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((?:https?:\/\/[^\s)]+|\/artifact\/[^\s)]+|\/api\/steward\/deliverable-file\?[^\s)]+)\))/g);
    parts.forEach(p => {
      if (/^\*\*[^*]+\*\*$/.test(p)) node.appendChild(el("strong", "", p.slice(2, -2)));
      else if (/^`[^`]+`$/.test(p)) node.appendChild(el("code", "", p.slice(1, -1)));
      else if (/^\[[^\]]+\]\(/.test(p)) {
        const m = p.match(/^\[([^\]]+)\]\(([^\s)]+)\)$/);
        if (m) { const a = el("a", "", m[1]); a.href = mdReportHref(m[2]);
                 a.target = "_blank"; a.rel = "noopener noreferrer"; node.appendChild(a); }
        else node.appendChild(document.createTextNode(p));
      } else if (p) node.appendChild(document.createTextNode(p));
    });
  }
  container.textContent = "";
  const lines = String(text || "").split("\n");
  let i = 0, list = null, quote = null;
  const flush = () => { list = null; quote = null; };
  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {                          // code fence
      flush(); i++;
      const buf = [];
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++;
      const pre = el("pre"); pre.appendChild(el("code", "", buf.join("\n")));
      container.appendChild(pre); continue;
    }
    if (ln.trim().startsWith("|") && ln.includes("|", 2)) {   // table
      flush();
      const table = el("table"); let first = true;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
        i++;
        if (cells.every(c => /^[\s:-]+$/.test(c))) continue;
        const tr = el("tr");
        cells.forEach(c => { const td = el(first ? "th" : "td");
                             inline(td, c.trim()); tr.appendChild(td); });
        table.appendChild(tr); first = false;
      }
      const wrap = el("div", "tblwrap"); wrap.appendChild(table);
      container.appendChild(wrap); continue;
    }
    const h = ln.match(/^(#{1,4})\s+(.*)$/);
    if (h) { flush(); const hd = el("h" + (h[1].length + 1), "mdh");
             inline(hd, h[2].replace(/#+\s*$/, "")); container.appendChild(hd);
             i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { flush(); container.appendChild(el("hr")); i++; continue; }
    const q = ln.match(/^\s*>\s?(.*)$/);
    if (q) { if (!quote) { quote = el("blockquote"); container.appendChild(quote); list = null; }
             const pp = el("div"); inline(pp, q[1]); quote.appendChild(pp); i++; continue; }
    const li = ln.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
    if (li) { if (!list) { list = el(/\d/.test(li[1]) ? "ol" : "ul");
                           container.appendChild(list); quote = null; }
              const item = el("li"); inline(item, li[2]); list.appendChild(item);
              i++; continue; }
    if (!ln.trim()) { flush(); i++; continue; }
    flush();
    const p = el("p"); inline(p, ln); container.appendChild(p); i++;
  }
}
