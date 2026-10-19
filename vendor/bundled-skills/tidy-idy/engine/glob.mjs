// engine/glob.mjs — the tiny path-pattern matcher the protection and exclusion
// sets are written in. Deliberately small and dependency-free (the skill has no
// package.json and must stay installable as a bare folder).
//
// Supported syntax (a strict subset of gitignore-style globs):
//   *      — any run of characters except '/'
//   ?      — exactly one character except '/'
//   **     — any number of path segments (including zero)
//   [abc]  — a character class
//   trailing '/' on a pattern means "this directory and everything under it"
//
// Paths are matched as POSIX-style relative paths ('a/b/c.txt'); matching is
// case-insensitive because tidy-idy must behave identically on NTFS and ext4 —
// a protected pattern that stops protecting when someone types 'Readme.md'
// would be a silent hole in a deny-by-default set.

/** Normalise any path shape to the 'a/b/c' form the matcher expects. */
export function toPosixRel(p) {
  return String(p).replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
}

function escapeRe(ch) {
  return ch.replace(/[.+^${}()|[\]\\]/g, '\\$&');
}

const cache = new Map();

/** Compile one glob pattern to an anchored RegExp. */
export function compileGlob(pattern) {
  const key = String(pattern);
  const hit = cache.get(key);
  if (hit) return hit;

  let p = toPosixRel(key);
  // A bare name with no slash matches at any depth ('SKILL.md' protects
  // 'skills/x/SKILL.md' too) — the protected CLASSES are about the file, not
  // about where someone filed it.
  const anyDepth = !p.includes('/');
  const dirPrefix = String(key).endsWith('/') || String(key).endsWith('/**');
  if (String(key).endsWith('/**')) p = p.slice(0, -3);

  let re = '';
  for (let i = 0; i < p.length; i++) {
    const c = p[i];
    if (c === '*') {
      if (p[i + 1] === '*') {
        // '**' — cross segment boundaries. '**/' consumes zero-or-more segments.
        i++;
        if (p[i + 1] === '/') { i++; re += '(?:[^/]+/)*'; }
        else re += '.*';
      } else {
        re += '[^/]*';
      }
    } else if (c === '?') {
      re += '[^/]';
    } else if (c === '[') {
      const close = p.indexOf(']', i + 1);
      if (close === -1) { re += '\\['; }
      else { re += p.slice(i, close + 1); i = close; }
    } else {
      re += escapeRe(c);
    }
  }

  const head = anyDepth ? '(?:.*/)?' : '';
  const tail = dirPrefix ? '(?:/.*)?' : '';
  const compiled = new RegExp(`^${head}${re}${tail}$`, 'i');
  cache.set(key, compiled);
  return compiled;
}

/** True when `relPath` matches `pattern`. */
export function globMatch(pattern, relPath) {
  return compileGlob(pattern).test(toPosixRel(relPath));
}

/** First matching pattern from `patterns`, or null. */
export function firstMatch(patterns, relPath) {
  const rel = toPosixRel(relPath);
  for (const pattern of patterns) {
    if (compileGlob(pattern).test(rel)) return pattern;
  }
  return null;
}
