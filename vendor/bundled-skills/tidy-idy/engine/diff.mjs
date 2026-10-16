// engine/diff.mjs — a small line-diff renderer.
//
// The compression stage is DEMOTED in Wave 1: it no longer writes agent.md, it
// emits a PROPOSAL finding carrying a rendered diff, which the human approves
// (or does not) in the panel. That requires a diff renderer that does not
// depend on anything outside the standard library.

/** Longest-common-subsequence line diff → unified-ish hunks. */
export function renderUnifiedDiff(beforeText, afterText, { fromLabel = 'before', toLabel = 'after', context = 3 } = {}) {
  const a = String(beforeText ?? '').split('\n');
  const b = String(afterText ?? '').split('\n');
  const ops = diffLines(a, b);

  const lines = [`--- ${fromLabel}`, `+++ ${toLabel}`];
  let i = 0;
  while (i < ops.length) {
    if (ops[i].op === ' ') { i++; continue; }
    // Grow a hunk around this change, with `context` equal lines on each side.
    let start = i;
    let ctx = 0;
    while (start > 0 && ctx < context) { start--; if (ops[start].op === ' ') ctx++; }
    let end = i;
    let trailing = 0;
    while (end < ops.length && trailing < context) {
      if (ops[end].op === ' ') trailing++;
      else trailing = 0;
      end++;
    }
    const slice = ops.slice(start, end);
    const aCount = slice.filter((o) => o.op !== '+').length;
    const bCount = slice.filter((o) => o.op !== '-').length;
    const aStart = ops.slice(0, start).filter((o) => o.op !== '+').length + 1;
    const bStart = ops.slice(0, start).filter((o) => o.op !== '-').length + 1;
    lines.push(`@@ -${aStart},${aCount} +${bStart},${bCount} @@`);
    for (const o of slice) lines.push(`${o.op}${o.line}`);
    i = end;
  }
  return lines.join('\n');
}

/** Classic LCS diff over line arrays. Returns [{op: ' '|'-'|'+', line}]. */
export function diffLines(a, b) {
  const n = a.length;
  const m = b.length;
  // Guard: the LCS table is O(n*m); very large inputs fall back to a coarse
  // whole-file replacement rather than eating the run's memory.
  if (n * m > 4_000_000) {
    return [
      ...a.map((line) => ({ op: '-', line })),
      ...b.map((line) => ({ op: '+', line })),
    ];
  }
  const lcs = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ op: ' ', line: a[i] }); i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { out.push({ op: '-', line: a[i] }); i++; }
    else { out.push({ op: '+', line: b[j] }); j++; }
  }
  while (i < n) { out.push({ op: '-', line: a[i] }); i++; }
  while (j < m) { out.push({ op: '+', line: b[j] }); j++; }
  return out;
}

/** Summary counts for a proposal tile. */
export function diffStats(beforeText, afterText) {
  const ops = diffLines(String(beforeText ?? '').split('\n'), String(afterText ?? '').split('\n'));
  return {
    added: ops.filter((o) => o.op === '+').length,
    removed: ops.filter((o) => o.op === '-').length,
    unchanged: ops.filter((o) => o.op === ' ').length,
  };
}
