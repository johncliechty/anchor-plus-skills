/**
 * The HARDENING GATE — a plan that ASSERTS a property must EMIT a gate for it.
 *
 * WHY (journal 0080, 2026-07-27). Crucible planned and Foreman built the
 * Ecgberht steward. The build went GREEN and the wiring was genuinely correct:
 * every route reached a handler, every handler was routed, every endpoint the
 * UI called existed, every route was authed. It still shipped six real defects
 * and zero tests, and every one of them was the same shape — **an asserted
 * property implemented as prose**:
 *
 *   - "Strip is append-only; receipts are never lost" was enforced by a module
 *     that REJECTS in-place rewrite... sitting on a bare `fs.writeFileSync`
 *     read-modify-write with no atomic rename and no lock. Two concurrent acts
 *     silently dropped receipts. A module that VALIDATES append-only does not
 *     PROVIDE it.
 *   - "The steward never invents; unknown is spoken as unknown" was contradicted
 *     by `except Exception: pass; return []`, which rendered a BROKEN registry
 *     as the cheerful "no projects to steward" and painted an ambient queue
 *     badge of 0 — i.e. "nothing needs you" — when the truth was "unknown".
 *
 * Stage-2 acceptance criteria described behaviour under SUCCESS. Nothing forced
 * a reviewer to ask "what does this render when the backing store is
 * unreadable?" or "what happens if two of these run at once?".
 *
 * This gate is the sibling of the mockup-contract law (journal 0079): the plan
 * does not get to *describe* the guarantee, it must emit the artifact that
 * MAKES the guarantee checkable.
 *
 * Pure predicates over the emitted plan — no I/O, no model. Stdlib only.
 */

/**
 * Property claims that oblige a mechanical gate, with what the gate must show.
 * Matching is on plan text, so the vocabulary is deliberately broad.
 */
export const PROPERTY_CLAIMS = Object.freeze([
  {
    id: 'durability',
    /** Storage guarantees. Claiming one obliges naming the layer that PROVIDES it. */
    patterns: [
      /append[- ]only/i,
      /never lost/i,
      /no data loss/i,
      /durable/i,
      /crash[- ]safe/i,
      /single writer/i,
      /atomic/i,
    ],
    requires: ['atomic write (temp + fsync + rename)', 'lock or documented serialization', 'a concurrency test'],
    why: 'a durability claim is a STORAGE claim; validating a rule is not providing it',
  },
  {
    id: 'honesty',
    patterns: [
      /never invent/i,
      /honest(ly)?[- ]unknown/i,
      /unknown is spoken/i,
      /no fabricat/i,
      /never fabricat/i,
      /degrade[sd]? honestly/i,
    ],
    requires: ['a failure-state table', 'unknown and empty as SEPARATE rows'],
    why: 'the recurring defect is a confident wrong answer, not a crash',
  },
  {
    id: 'idempotence',
    patterns: [/idempotent/i, /exactly once/i, /run[- ]once/i, /at most once/i],
    requires: ['a repeat-invocation test'],
    why: 'idempotence is only real if something re-invokes and asserts no change',
  },
  {
    id: 'boundedness',
    patterns: [/bounded/i, /rate[- ]limit/i, /back ?off/i, /capped?\b/i, /timeout/i],
    requires: ['the numeric bound named in the plan', 'a refusal path when the bound is exceeded'],
    why: 'an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard',
  },
  {
    id: 'containment',
    patterns: [/traversal/i, /contain(ment|ed)/i, /sandbox/i, /must not escape/i],
    requires: ['an escape-attempt test (.., absolute path, symlink)'],
    why: 'containment is asserted far more often than it is exercised',
  },
]);

/** Failure states every surface-bearing wave must answer for. */
export const REQUIRED_FAILURE_STATES = Object.freeze([
  'dependency-missing',
  'dependency-slow-or-killed',
  'dependency-returns-garbage',
  'backing-store-unreadable',
  'empty-but-valid',
]);

function text(v) {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return v.map(text).join('\n');
  if (typeof v === 'object') return Object.values(v).map(text).join('\n');
  return String(v);
}

/**
 * Which property claims does this plan make?
 * @param {string|object} plan  plan text (or any object; values are flattened)
 * @returns {{id:string, why:string, requires:string[], matched:string}[]}
 */
export function detectPropertyClaims(plan) {
  const body = text(plan);
  const found = [];
  for (const claim of PROPERTY_CLAIMS) {
    const hit = claim.patterns.find((re) => re.test(body));
    if (hit) {
      found.push({
        id: claim.id,
        why: claim.why,
        requires: [...claim.requires],
        matched: String(hit),
      });
    }
  }
  return found;
}

/**
 * THE GATE. For every property the plan asserts, the plan must also carry a
 * mechanical gate for it — named in a wave's acceptance criteria, or in an
 * explicit `propertyGates` map.
 *
 * @param {object} o
 * @param {string|object} o.plan            the emitted plan (text or doc object)
 * @param {object[]} [o.waves=[]]           waves; acceptance text is searched
 * @param {Object<string,string[]>} [o.propertyGates={}]  explicit id -> gate descriptions
 * @param {boolean} [o.addsSurface=false]   does this plan add an HTTP/CLI/persistence surface?
 * @returns {{pass:boolean, claims:object[], missing:object[], detail:string}}
 */
export function checkPropertyGates({ plan, waves = [], propertyGates = {}, addsSurface = false } = {}) {
  const claims = detectPropertyClaims(plan);
  const acceptance = text(waves.map((w) => (w && (w.acceptance ?? w.doneWhen ?? w)) ?? ''));
  const declared = text(propertyGates);
  const haystack = `${acceptance}\n${declared}`.toLowerCase();

  const missing = [];
  for (const claim of claims) {
    const explicit = Array.isArray(propertyGates[claim.id]) && propertyGates[claim.id].length > 0;
    // A requirement counts as gated when its distinctive words appear in the
    // acceptance criteria — the plan must SAY the mechanism, not just the goal.
    const unmet = claim.requires.filter((req) => {
      if (explicit) return false;
      const keys = req.toLowerCase().match(/[a-z]{4,}/g) ?? [];
      const strong = keys.filter((k) => !['with', 'that', 'when', 'from', 'test'].includes(k));
      return !strong.some((k) => haystack.includes(k));
    });
    if (unmet.length) missing.push({ id: claim.id, why: claim.why, unmet });
  }

  if (addsSurface) {
    const absent = REQUIRED_FAILURE_STATES.filter(
      (s) => !haystack.includes(s.split('-')[0]) || !haystack.includes(s.split('-').slice(-1)[0]),
    );
    if (absent.length) {
      missing.push({
        id: 'failure-state-table',
        why: 'a wave that adds a surface must answer for each failure state, naming the status code AND the user-visible text',
        unmet: absent,
      });
    }
  }

  const pass = missing.length === 0;
  const detail = pass
    ? claims.length
      ? `${claims.length} asserted propert(ies) all carry a mechanical gate`
      : 'no property claims detected; nothing to gate'
    : missing
        .map((m) => `${m.id}: missing ${m.unmet.join(', ')} — ${m.why}`)
        .join('; ');
  return { pass, claims, missing, detail };
}

/**
 * Render the obligations as a plan-ready checklist, so Stage 2 can EMIT the
 * gate text rather than a planner inventing wording each run.
 * @param {ReturnType<typeof detectPropertyClaims>} claims
 */
export function renderPropertyGateChecklist(claims = []) {
  if (!claims.length) return '';
  const lines = ['## Property gates (hardening law — crucible journal 0080)', ''];
  for (const c of claims) {
    lines.push(`### ${c.id} — asserted by this plan`);
    lines.push(`_${c.why}_`);
    lines.push('');
    for (const r of c.requires) lines.push(`- [ ] ${r}`);
    lines.push('');
  }
  lines.push('A property named in the plan and absent from this list is a BLOCKER:');
  lines.push('the plan is claiming a guarantee nothing enforces.');
  return lines.join('\n');
}
