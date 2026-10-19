// The text a code-job reviewer is given (steward_review.mjs); its own module so it is testable without a review.
import { execFileSync } from 'node:child_process';

// The reviewer reads text only: a binary file appears in a diff as one "Binary files differ" line, so a reviewer could
// pass content it never saw. The text files go to it as their exact diff (a NUL byte or invalid UTF-8 there is refused
// rather than sent lossy - rescued from WIP 283fc40, 2026-10-11). A binary file - a PDF reading copy, an image - is
// LISTED by name, size and hash, said plainly to be unread, and kept out of the text diff: refusing it outright left
// every job with a PDF unable to land (Book 1 conflict spine v2, 2026-10-12).
const RUNTIME_RECORDS = /(?:^|\/)\.ecgberht\/|(?:^|\/)\.anchor\/|(?:^|\/)(?:ECGBERHT|DELIVERABLES|STATUS[^/]*)\.md$|(?:^|\/)(?:strip|roadmap)\.json$|(?:^|\/)journal\/|(?:^|\/)code-job-outputs\//i;

export function reviewDiff(repo, from, head, options = {}) {
  const bytes = (...a) => execFileSync('git', ['-C', repo, ...a], { maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  const plain = ['--no-ext-diff', '--no-textconv', '--find-renames', from, head];
  const rawRows = numstatRows(bytes('diff', '--numstat', '-z', ...plain).toString('utf8'));
  let candPaths = null;
  if (options.deltaBase && options.deltaBase !== from) {
    try {
      const cRows = numstatRows(bytes('diff', '--numstat', '-z', '--no-ext-diff', '--no-textconv', '--find-renames', options.deltaBase, from).toString('utf8'));
      if (cRows.length) candPaths = new Set(cRows.flatMap(r => [r.from, r.to]).filter(Boolean));
    } catch { candPaths = null; }
  }
  const isIgnoredDelta = r => {
    const p = r.to || r.from || '';
    if (options.excludeRuntime && RUNTIME_RECORDS.test(p)) return true;
    if (candPaths && !candPaths.has(r.to) && !candPaths.has(r.from)) return true;
    return false;
  };
  const runtimeRows = (options.excludeRuntime || candPaths) ? rawRows.filter(isIgnoredDelta) : [];
  const all = (options.excludeRuntime || candPaths) ? rawRows.filter(r => !isIgnoredDelta(r)) : rawRows;
  if ((options.excludeRuntime || candPaths) && !all.length) return '';
  const binaries = all.filter(r => r.binary);
  const exclude = [...binaries, ...runtimeRows].flatMap(b => [b.from, b.to]).filter(Boolean).map(p => `:(exclude,literal)${p}`);
  const only = ['--', '.', ...exclude];
  // an excluded path also excludes what lies under it (a binary file "foo" replaced by a folder "foo/"): the text
  // rows left must be exactly the text rows of the whole change, or a text change would vanish unreviewed
  const kept = numstatRows(bytes('diff', '--numstat', '-z', ...plain, ...only).toString('utf8'));
  const pairs = rows => rows.map(r => JSON.stringify([r.from, r.to])).sort().join('\n');
  if (kept.some(r => r.binary) || pairs(kept) !== pairs(all.filter(r => !r.binary))) {
    throw new Error('a binary file and a text file share a path in this change - the reviewer could not be shown it exactly');
  }
  const raw = bytes('diff', '--no-color', ...plain, ...only);
  if (raw.includes(0)) throw new Error('the diff holds a NUL byte - the reviewer reads text only');
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(raw).trim();
  } catch {
    throw new Error('the diff is not valid UTF-8 - the reviewer would not see its exact bytes');
  }
  if (!binaries.length) return text;
  const size = (rev, p) => {                    // a blob's size; a folder now at that path counts as no file
    try {
      if (bytes('cat-file', '-t', `${rev}:${p}`).toString().trim() !== 'blob') return null;
      return Number(bytes('cat-file', '-s', `${rev}:${p}`).toString().trim());
    } catch { return null; }
  };
  const hash = (rev, p) => { try { return bytes('rev-parse', `${rev}:${p}`).toString().trim().slice(0, 12); } catch { return null; } };
  const rows = binaries.map(b => {
    const was = b.from ? size(from, b.from) : null, now = b.to ? size(head, b.to) : null;
    const name = b.from && b.from !== b.to ? `${b.from} -> ${b.to}` : b.to || b.from;
    const what = now === null ? `deleted (was ${was} bytes, blob ${hash(from, b.from)})` : was === null ? `added, ${now} bytes, blob ${hash(head, b.to)}`
      : `changed, ${was} -> ${now} bytes, blob ${hash(head, b.to)}`;
    return `- ${name}: ${what}`;
  });
  return [text, '', 'BINARY FILES (not shown above, and NOT read by you - judge only whether the brief asks for each one,',
          'for example a PDF reading copy of a document in this change):', ...rows].join('\n').trim();
}

// `git diff --numstat -z`: "A\tD\tpath\0", or for a rename "A\tD\t\0from\0to\0"; a binary file counts as "-\t-".
function numstatRows(numstat) {
  const parts = numstat.split('\0'), out = [];
  for (let i = 0; i < parts.length; i++) {
    const m = /^(-|\d+)\t(-|\d+)\t(.*)$/s.exec(parts[i]);
    if (!m) continue;
    let from = m[3], to = m[3];
    if (m[3] === '') { from = parts[++i]; to = parts[++i]; }
    out.push({ from, to, binary: m[1] === '-' && m[2] === '-' });
  }
  return out;
}

// 2026-10-13 (MBA job, a 485,869-character diff): an oversized change is refused with its five largest files named,
// so the steward knows how to split it. Never raises: the refusal stands without the names.
export function largest(repo, from, head) {
  try {
    const rows = execFileSync('git', ['-C', repo, 'diff', '--numstat', '--no-renames', from, head], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).split('\n').map(l => l.split('\t'))
      .filter(r => r.length >= 3 && r[0] !== '-').map(r => [r.slice(2).join('\t'), Number(r[0]) + Number(r[1])])
      .sort((a, b) => b[1] - a[1]).slice(0, 5);
    return rows.length ? '; largest: ' + rows.map(([p, n]) => `${p} (${n} lines)`).join(', ') : '';
  } catch { return ''; }
}
