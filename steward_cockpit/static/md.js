/* Safe, small markdown renderer for human-facing reports.
   DOM-building only (textContent) - never innerHTML with document text.
   Covers: #-#### headings, hr, > quotes, -/* lists, 1. lists, ``` fences,
   | tables, paragraphs; inline **bold**, `code`, [text](links - spaces and ( ) survive). */
"use strict";
// Report links belong to the Anchor origin the reader is using. Historical
// steward replies hard-coded the author's loopback host, which is another
// machine when opened remotely. Keep external paper URLs untouched.
function mdFileHref(rawPath) {
  if (!window.STEWARD_PID) return null;
  let p = String(rawPath || "").trim().replace(/\\/g, "/");
  if (/^file:\/\/\//i.test(p)) {
    try { p = decodeURIComponent(new URL(p).pathname).replace(/^\/([A-Za-z]:\/)/, "$1"); }
    catch (_) { p = p.replace(/^file:\/\/\/+/i, ""); }
  }
  p = p.replace(/#L?\d+(?:-L?\d+)?$/i, "");
  const dirRel = String(window.STEWARD_DIR || "");
  if (/^[A-Za-z]:\//.test(p)) {
    // Extract relative path inside the project/effort if possible
    const marker = p.match(/(?:\/|^)((?:BA 815|\.ecgberht|deliverables|planning|lectures|homework|quiz|syllabus|ta-feedback|code-job-outputs|chapters|story-arc|editorial|Finished Deliverables|skills|foundry-tools|steward_cockpit|tools|docs|tests)\/.+)$/i);
    if (marker) p = marker[1];
    else {
      const devMatch = p.match(/^[A-Za-z]:\/dev\/[^/]+\/(.+)$/i);
      if (devMatch) p = devMatch[1];
      else return null;
    }
  }
  if (typeof window.__resolveDeliverablePath === "function") {
    const resolved = window.__resolveDeliverablePath(p);
    if (resolved) p = resolved;
  }
  if (!p || p.startsWith("/") || /(?:^|\/)\.\.(?:\/|$)/.test(p)) return null;
  const isMd = /\.(md|markdown|txt|r|py|sql|sh|ps1|yaml|yml|toml|js|mjs|ts|css)$/i.test(p);
  const isOffice = /\.(docx|pptx|xlsx)$/i.test(p);
  return "/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID) +
    "&dir=" + encodeURIComponent(dirRel) +
    "&path=" + encodeURIComponent(p) +
    (isOffice ? "&view=1" : "") +
    (isMd ? "&render=1" : "") +
    (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
}
function mdYouTubeId(raw) {
  const m = String(raw || "").trim().match(/^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/)|youtu\.be\/)([A-Za-z0-9_-]{6,15})/i);
  return m ? m[1] : "";
}
function mdReportHref(raw, label) {
  const ytId = mdYouTubeId(raw);
  if (ytId) {
    return "/steward-static/video.html?v=" + encodeURIComponent(ytId) +
      "&url=" + encodeURIComponent(String(raw || "").trim()) +
      (label ? "&title=" + encodeURIComponent(String(label).trim()) : "");
  }
  if (/^file:\/\/\//i.test(String(raw || "").trim())) {
    const mapped = mdFileHref(raw);
    if (mapped) return mapped;
  }
  const current = new URL(window.location.href);
  let dest;
  try { dest = new URL(raw, current.origin); }
  catch (_) { return raw; } // An invalid document link must not erase the turn.
  // W3 (2026-10-10): both /artifact forms (?path= and /artifact/<pid>/<rel>) and /report are Anchor's own, and an
  // ABSOLUTE Anchor URL - loopback, this page's own host on another port or scheme, or the tailnet name - is opened
  // on the origin the reader is using (a reply written at the desk opens on the iPad)
  const internal = /^\/artifact\/[^/]+(\/.+)?$/.test(dest.pathname) || /^\/report\//.test(dest.pathname) ||
    dest.pathname === "/api/steward/deliverable-file" || dest.pathname === "/steward/v1" ||
    /^\/project\/[^/]+/.test(dest.pathname) || dest.pathname === "/high-seat" || dest.pathname === "/desk" || dest.pathname === "/doctor";
  const loop = /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(dest.hostname) && (dest.port === "8777" || dest.port === "");
  // review r1: only loopback or THIS page's own host name - never any *.ts.net machine or a look-alike
  // final review 10-10: the same host on ANOTHER service's port is that service's, never Anchor's
  const legacy = dest.origin === "http://127.0.0.1:8777" || loop || dest.origin === current.origin ||
    (dest.hostname === current.hostname && dest.port === "8777");
  if (internal && !dest.username && !dest.password &&
      (dest.origin === current.origin || legacy)) {
    dest.searchParams.delete("token");
    if (window.STEWARD_TOKEN) dest.searchParams.set("token", window.STEWARD_TOKEN);
    // 2026-10-07: a markdown product opens formatted (the canonical reading URL carries render=1)
    if (dest.pathname === "/api/steward/deliverable-file" && /\.(md|markdown|txt|r|py|sql|sh|ps1|yaml|yml|toml|js|mjs|ts|css)$/i.test(dest.searchParams.get("path") || "")
        && !dest.searchParams.has("download")) dest.searchParams.set("render", "1");
    return dest.pathname + dest.search + dest.hash;
  }
  return raw;
}
function mdRender(container, text) {
  const el = (t, c, x) => { const n = document.createElement(t);
    if (c) n.className = c; if (x !== undefined) n.textContent = x; return n; };
  // [label](target): the target may hold spaces, balanced ( ) or the <...> form (2026-10-07: "Calendar
  // (accepted).ics" or "MBA Teaching AI/..." broke the link at the first space or ")"). Only report links, file:///
  // links and http(s) become links; anything else stays text. Bare paths are never auto-linked.
  const LINKABLE = /^(?:https?:\/\/|file:\/\/\/|\/artifact\/|\/report\/|\/foundry\?|\/api\/steward\/deliverable-file\?|\/steward\/v1\?|\/project\/|\/high-seat|\/desk|\/doctor)/i;
  function splitLinks(s) {
    const out = []; let i = 0;
    while (i < s.length) {
      const j = s.indexOf("[", i);
      if (j < 0) break;
      const k = s.indexOf("](", j);
      if (k < 0) break;
      if (s.slice(j + 1, k).includes("[") || s.slice(j + 1, k).includes("]")) { out.push(s.slice(i, j + 1)); i = j + 1; continue; }
      let depth = 1, m = k + 2;
      const rest = s.slice(k + 2), lead = rest.length - rest.trimStart().length;
      if (rest.trimStart().startsWith("<")) {                 // the <...> form, taken whole
        const gt = s.indexOf(">", k + 2 + lead);
        if (gt >= 0 && s[gt + 1] === ")") { depth = 0; m = gt + 2; }
      }
      while (m < s.length && depth) { if (s[m] === "(") depth++; else if (s[m] === ")") depth--; m++; }
      let target = s.slice(k + 2, m - 1).trim();
      if (target.startsWith("<") && target.endsWith(">")) target = target.slice(1, -1).trim();
      if (depth || !LINKABLE.test(target)) { out.push(s.slice(i, k + 2)); i = k + 2; continue; }
      if (j > i) out.push(s.slice(i, j));
      out.push({label: s.slice(j + 1, k).replace(/^`+|`+$/g, ""), target});
      i = m;
    }
    if (i < s.length) out.push(s.slice(i));
    return out;
  }
function mdDownloadHref(href) {
  const h = String(href || "");
  if (!h || (!h.startsWith("/api/steward/deliverable-file?") && !h.startsWith("/artifact/"))) return null;
  const cleaned = h.replace(/([?&])(render|view)=1(&|$)/g, (m, p1, _k, p3) => p3 ? p1 : "");
  return cleaned + (cleaned.includes("?") ? "&" : "?") + "download=1";
}
function mdFileTypeBadge(target, href, label) {
  let probe = "";
  try {
    const u = new URL(String(href || target || ""), window.location.origin);
    probe = u.searchParams.get("path") || u.pathname || "";
  } catch (_) {
    probe = String(target || href || "");
  }
  const combined = (probe + " " + String(target || "") + " " + String(label || "")).trim();
  if (/\.pdf(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "PDF", ext: ".pdf", cls: "fmt-pdf" };
  if (/\.pptx?(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "PPTX", ext: ".pptx", cls: "fmt-pptx" };
  if (/\.docx?(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "DOCX", ext: ".docx", cls: "fmt-docx" };
  if (/\.xlsx?(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "XLSX", ext: ".xlsx", cls: "fmt-xlsx" };
  if (/\.r(?:$|\?|&|\b|\s|\))/i.test(probe)) return { tag: "R", ext: ".R", cls: "fmt-r" };
  if (/\.csv(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "CSV", ext: ".csv", cls: "fmt-csv" };
  if (/\.py(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "PY", ext: ".py", cls: "fmt-py" };
  if (/\.html?(?:$|\?|&|\b|\s|\))/i.test(probe)) return { tag: "HTML", ext: ".html", cls: "fmt-html" };
  if (/\.zip(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "ZIP", ext: ".zip", cls: "fmt-zip" };
  if (/\.json(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "JSON", ext: ".json", cls: "fmt-json" };
  if (/\.(?:md|markdown)(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "MD", ext: ".md", cls: "fmt-md" };
  if (/\.txt(?:$|\?|&|\b|\s|\))/i.test(combined)) return { tag: "TXT", ext: ".txt", cls: "fmt-txt" };
  return null;
}
function wireMdSplitLink(a, label, href) {
  if (!href || /^(?:https?:\/\/|mailto:|ms-\w+:)/i.test(href)) return;
  a.onclick = (ev) => {
    if (typeof window.enterSecondWindowMode === "function") {
      ev.preventDefault();
      ev.stopPropagation();
      window.enterSecondWindowMode(String(label || "Deliverable"), href);
    }
  };
}
  function inline(node, s) {
    splitLinks(String(s)).forEach(seg => {
      if (typeof seg !== "string") {
        const href = mdReportHref(seg.target, seg.label);
        const fmt = mdFileTypeBadge(seg.target, href, seg.label);
        if (fmt) {
          const badge = el("span", "file-fmt-badge md-fmt-pill " + fmt.cls, fmt.tag);
          badge.title = "File type: " + fmt.tag + " (" + fmt.ext + ")";
          node.appendChild(badge);
        }
        const a = el("a", "md-file-link", seg.label); a.href = href;
        if (fmt) a.title = seg.label + " (" + fmt.tag + " · " + fmt.ext + ")";
        a.target = "_blank"; a.rel = "noopener noreferrer";
        wireMdSplitLink(a, fmt ? (seg.label + " (" + fmt.ext + ")") : seg.label, href);
        node.appendChild(a);
        const dlHref = mdDownloadHref(href);
        if (dlHref) {
          const dl = el("span", "md-dl", fmt ? ("⬇ " + fmt.ext) : "⬇"); // el("a", "md-dl", "⬇")
          dl.setAttribute("role", "button");
          dl.title = "Download " + (fmt ? (fmt.tag + " (" + fmt.ext + ")") : "file");
          dl.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); window.open(dlHref, "_blank", "noopener,noreferrer"); };
          node.appendChild(dl);
        }
        return;
      }
      seg.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).forEach(p => {
        if (/^\*\*[^*]+\*\*$/.test(p)) node.appendChild(el("strong", "", p.slice(2, -2)));
        else if (/^`[^`]+`$/.test(p)) {
          const inner = p.slice(1, -1).trim();
          const isDocPath = !/^\s*-/.test(inner) && !/\s{2,}/.test(inner) &&
            /\.(?:md|markdown|pdf|html?|docx|pptx|xlsx|csv|txt|json|py|r|sql|sh|ps1|yaml|yml|toml|m?js|css|zip)(?:#L?\d+(?:-L?\d+)?)?$/i.test(inner);
          const href = isDocPath ? mdFileHref(inner) : null;
          if (href) {
            const fmt = mdFileTypeBadge(inner, href, inner);
            if (fmt) {
              const badge = el("span", "file-fmt-badge md-fmt-pill " + fmt.cls, fmt.tag);
              badge.title = "File type: " + fmt.tag + " (" + fmt.ext + ")";
              node.appendChild(badge);
            }
            const a = el("a", "md-file-link"); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
            a.title = "Open " + inner + (fmt ? (" (" + fmt.tag + " · " + fmt.ext + ")") : "");
            a.appendChild(el("code", "", inner));
            wireMdSplitLink(a, inner, href);
            node.appendChild(a);
            const dlHref = mdDownloadHref(href);
            if (dlHref) {
              const dl = el("span", "md-dl", fmt ? ("⬇ " + fmt.ext) : "⬇");
              dl.setAttribute("role", "button");
              dl.title = "Download " + inner;
              dl.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); window.open(dlHref, "_blank", "noopener,noreferrer"); };
              node.appendChild(dl);
            }
          } else {
            node.appendChild(el("code", "", p.slice(1, -1)));
          }
        }
        else if (p) node.appendChild(document.createTextNode(p));
      });
    });
  }
  container.textContent = "";
  const cleanedText = String(text || "").replace(/<!--\s*(?:producer-handoff-|steward-receipt-|ecgberht-)[\s\S]*?-->/gi, "").trimEnd();
  const lines = cleanedText.split("\n");
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
