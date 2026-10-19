// Shared normalize / exact-match for host allowlist H and engine allowlist E1.
// Substring / fuzzy match is forbidden (W2 / C1+C3).

/**
 * Basename after last path separator; strip trailing .exe (case-insensitive);
 * Unicode case-fold lower. Exact-match input for allowlist tables.
 * @param {string|null|undefined} imagePathOrName
 * @returns {string}
 */
function normalizeImageBasename(imagePathOrName) {
  let s = String(imagePathOrName == null ? '' : imagePathOrName).trim();
  if (!s) return '';
  const slash = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'));
  if (slash >= 0) s = s.slice(slash + 1);
  s = s.replace(/\.exe$/i, '');
  // Unicode case-fold via locale lower (covers Insiders multi-word basenames).
  try {
    s = s.toLocaleLowerCase('en-US');
  } catch (_) {
    s = s.toLowerCase();
  }
  // Collapse internal runs of whitespace to a single space (Windows image strings).
  s = s.replace(/\s+/g, ' ').trim();
  return s;
}

/**
 * Exact equality against a closed set of already-normalized allowlist entries,
 * or against a versioned alias map (normalized alias → canonical key).
 * Never substring/fuzzy.
 *
 * @param {string} imagePathOrName
 * @param {Iterable<string>|Set<string>} normalizedAllowlist
 * @param {Record<string, string>|Map<string, string>|null} [aliasTable]
 * @returns {{ matched: boolean, key: string|null, normalized: string }}
 */
function matchNormalizedExact(imagePathOrName, normalizedAllowlist, aliasTable = null) {
  const normalized = normalizeImageBasename(imagePathOrName);
  if (!normalized) return { matched: false, key: null, normalized: '' };

  const set = normalizedAllowlist instanceof Set
    ? normalizedAllowlist
    : new Set([...normalizedAllowlist].map((x) => normalizeImageBasename(x)));

  if (set.has(normalized)) {
    return { matched: true, key: normalized, normalized };
  }

  if (aliasTable) {
    const aliasKey = aliasTable instanceof Map
      ? aliasTable.get(normalized)
      : aliasTable[normalized];
    // Alias hits only when the canonical form is in THIS allowlist set.
    // Never match on identity alone (that false-positived "code - insiders"
    // against the plain "code" row when the alias table held an identity map).
    if (aliasKey != null) {
      const canon = normalizeImageBasename(aliasKey);
      if (set.has(canon)) {
        return { matched: true, key: canon, normalized };
      }
    }
  }

  return { matched: false, key: null, normalized };
}

module.exports = {
  normalizeImageBasename,
  matchNormalizedExact,
};
