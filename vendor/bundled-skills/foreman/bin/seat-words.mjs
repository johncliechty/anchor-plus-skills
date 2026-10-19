// seat-words.mjs — the pure helpers run-live.mjs re-exports. They live here so a test can import them without
// running run-live.mjs, whose top level IS the live run (2026-10-10, S1: importing it from a test started a
// "run" against the test's cwd and wrote a run record into foreman/journal/runs).

/** A dead seat's last words: the result text of an error envelope, one line, clipped. */
export function seatLastWords(text, max = 240) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  if (!t) return '';
  return t.length <= max ? t : t.slice(0, max - 1).replace(/\s+\S*$/, '') + '…';
}

/** True when a CLI/model message says a session / usage / rate limit was hit. */
export const USAGE_LIMIT_RE = /usage limit|rate.?limit|limit reached|hit your limit|reached your limit|out of (?:extra )?usage|quota|resets? (?:at|in) |too many requests|\b429\b|resource exhausted|overloaded/i;
export function isUsageLimitText(text) {
  return USAGE_LIMIT_RE.test(String(text || ''));
}
