import React from 'react';

/**
 * Lightweight Markdown → React for human-facing skill cards (HUMAN.md).
 * No extra deps: headings, bold/italic, lists, code, paragraphs, links.
 * Escapes HTML so skill prose cannot inject scripts.
 */

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Inline: **bold**, *italic*, `code`, [text](url) */
function renderInline(text) {
  let s = escapeHtml(text);
  // links
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>',
  );
  // bold then italic
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong class="md-strong">$1</strong>');
  s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em class="md-em">$1</em>');
  s = s.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');
  return s;
}

/**
 * Block-level parse. Returns array of { type, level?, html?, items? }.
 */
export function parseMarkdownBlocks(src) {
  const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    // fenced code
    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim();
      i += 1;
      const buf = [];
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        buf.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      blocks.push({
        type: 'code',
        lang,
        html: escapeHtml(buf.join('\n')),
      });
      continue;
    }
    // headings
    const hm = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (hm) {
      blocks.push({ type: 'heading', level: hm[1].length, html: renderInline(hm[2]) });
      i += 1;
      continue;
    }
    // unordered list
    if (/^[-*+]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(renderInline(lines[i].trim().replace(/^[-*+]\s+/, '')));
        i += 1;
      }
      blocks.push({ type: 'ul', items });
      continue;
    }
    // ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(renderInline(lines[i].trim().replace(/^\d+\.\s+/, '')));
        i += 1;
      }
      blocks.push({ type: 'ol', items });
      continue;
    }
    // paragraph (merge consecutive non-empty non-special lines)
    const para = [trimmed];
    i += 1;
    while (
      i < lines.length
      && lines[i].trim()
      && !lines[i].trim().startsWith('#')
      && !/^[-*+]\s+/.test(lines[i].trim())
      && !/^\d+\.\s+/.test(lines[i].trim())
      && !lines[i].trim().startsWith('```')
    ) {
      para.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ type: 'p', html: renderInline(para.join(' ')) });
  }
  return blocks;
}

export default function Markdown({ source, className = '' }) {
  const blocks = parseMarkdownBlocks(source);
  if (!blocks.length) {
    return (
      <p className={`text-sm text-slate-500 ${className}`}>
        No description available.
      </p>
    );
  }
  return (
    <div className={`md-body space-y-3 ${className}`}>
      {blocks.map((b, idx) => {
        if (b.type === 'heading') {
          const Tag = b.level === 1 ? 'h2' : b.level === 2 ? 'h3' : 'h4';
          const cls =
            b.level === 1
              ? 'text-base font-semibold text-white font-display tracking-tight'
              : b.level === 2
                ? 'text-sm font-semibold text-[#00F0FF] font-display tracking-wide uppercase mt-2'
                : 'text-xs font-semibold text-slate-300 mt-1';
          return (
            <Tag
              key={idx}
              className={cls}
              dangerouslySetInnerHTML={{ __html: b.html }}
            />
          );
        }
        if (b.type === 'ul') {
          return (
            <ul key={idx} className="list-none space-y-1.5 pl-0">
              {b.items.map((it, j) => (
                <li key={j} className="flex gap-2 text-sm text-slate-300 font-light leading-relaxed">
                  <span className="text-[#00F0FF] shrink-0 mt-0.5">▪</span>
                  <span dangerouslySetInnerHTML={{ __html: it }} />
                </li>
              ))}
            </ul>
          );
        }
        if (b.type === 'ol') {
          return (
            <ol key={idx} className="list-decimal list-inside space-y-1.5 text-sm text-slate-300 font-light leading-relaxed">
              {b.items.map((it, j) => (
                <li key={j} dangerouslySetInnerHTML={{ __html: it }} />
              ))}
            </ol>
          );
        }
        if (b.type === 'code') {
          return (
            <pre
              key={idx}
              className="rounded-lg bg-[#050507] border border-[#16161A] p-3 text-[11px] font-mono text-emerald-400/90 overflow-x-auto"
            >
              <code dangerouslySetInnerHTML={{ __html: b.html }} />
            </pre>
          );
        }
        return (
          <p
            key={idx}
            className="text-sm leading-relaxed text-slate-300 font-light"
            dangerouslySetInnerHTML={{ __html: b.html }}
          />
        );
      })}
      <style>{`
        .md-body .md-strong { color: #f4f4f5; font-weight: 600; }
        .md-body .md-em { color: #a1a1aa; font-style: italic; }
        .md-body .md-code {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 0.85em;
          background: #16161A;
          border: 1px solid #27272a;
          border-radius: 4px;
          padding: 0.1em 0.35em;
          color: #67e8f9;
        }
        .md-body .md-link { color: #00F0FF; text-decoration: underline; text-underline-offset: 2px; }
        .md-body .md-link:hover { color: #67e8f9; }
      `}</style>
    </div>
  );
}
