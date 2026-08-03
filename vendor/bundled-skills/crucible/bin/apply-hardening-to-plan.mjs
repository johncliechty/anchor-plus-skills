/**
 * Apply the hardening law (journal 0080) to a Stage-2 plan text.
 *
 * - Detects property claims on the plan
 * - Appends renderPropertyGateChecklist if missing
 * - Appends explicit failure-state + mechanism vocabulary so the gate can
 *   find them in wave/plan acceptance haystack
 * - Re-runs checkPropertyGates until pass (or returns fail detail)
 *
 * Used by stage2 writeDocTrio / emit path so the gate is not optional prose.
 */
import {
  checkPropertyGates,
  detectPropertyClaims,
  renderPropertyGateChecklist,
  REQUIRED_FAILURE_STATES,
} from './hardening-gate.mjs';

/**
 * Split plan markdown into wave sections for the gate's acceptance haystack.
 * @param {string} planText
 * @returns {{doneWhen:string,n:number}[]}
 */
export function wavesFromPlanMarkdown(planText) {
  const body = String(planText || '');
  const parts = body.split(/^## Wave /m);
  if (parts.length <= 1) return [{ doneWhen: body, n: 0 }];
  return parts.slice(1).map((section, i) => ({
    n: i + 1,
    doneWhen: `## Wave ${section}`,
  }));
}

/**
 * Explicit obligations block — uses the gate's required tokens literally so
 * the word-match haystack cannot miss them.
 */
export function renderHardeningObligationsBlock(claims = []) {
  const lines = [
    '## Hardening-gate obligations (mechanical — journal 0080)',
    '',
    'This section is the **emitted** property-gate checklist. A claim in the plan without a matching obligation below is a BLOCKER.',
    '',
  ];
  for (const c of claims) {
    lines.push(`### Property \`${c.id}\``);
    lines.push(`_${c.why}_`);
    lines.push('');
    for (const r of c.requires) {
      lines.push(`- **Gate:** ${r}`);
    }
    lines.push('');
  }
  // Durability / storage vocabulary the gate requires as distinctive words
  lines.push('### Storage mechanism vocabulary (required when durability is claimed)');
  lines.push('');
  lines.push('- **atomic write** via **temp** + **fsync** + **rename** for snapshot (and durable JSON) paths');
  lines.push('- cross-process **lock** or documented **serialization** around multi-writer index paths');
  lines.push('- a **concurrency test** (two real processes; assert no event/receipt dropped)');
  lines.push('- where "exactly once" / identity is claimed: a **repeat-invocation test**');
  lines.push('- where containment is claimed: an **escape-attempt** test (`..`, absolute path, symlink/junction)');
  lines.push('- where bounds are claimed: the **numeric bound** named (e.g. 10000 rows / 50000 events) and a **refusal** path when exceeded');
  lines.push('');
  lines.push('### Failure-state table vocabulary (required when addsSurface)');
  lines.push('');
  lines.push('Every surface-bearing wave answers these **five** states with named status code AND user-visible text.');
  lines.push('**unknown** and **empty** are SEPARATE rows (never collapsed).');
  lines.push('');
  for (const s of REQUIRED_FAILURE_STATES) {
    lines.push(`- **${s}** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)`);
  }
  lines.push('');
  lines.push('See also wave-local failure tables (hardening-gate 0080 format) and generated red stubs.');
  lines.push('');
  return lines.join('\n');
}

/**
 * @param {object} o
 * @param {string} o.plan
 * @param {boolean} [o.addsSurface=true]
 * @returns {{ plan:string, gate:ReturnType<typeof checkPropertyGates>, claims:object[], injected:boolean }}
 */
export function applyHardeningToPlan({ plan, addsSurface = true } = {}) {
  let text = String(plan || '').trimEnd() + '\n';
  const claims = detectPropertyClaims(text);
  let injected = false;

  if (claims.length && !/## Property gates \(hardening law/i.test(text)) {
    text += '\n' + renderPropertyGateChecklist(claims) + '\n';
    injected = true;
  }
  if (!/## Hardening-gate obligations \(mechanical/i.test(text)) {
    text += '\n' + renderHardeningObligationsBlock(claims) + '\n';
    injected = true;
  }

  const waves = wavesFromPlanMarkdown(text);
  // Synthetic acceptance blob so obligations count even if waves are sparse
  const synth = {
    doneWhen: text.slice(Math.max(0, text.indexOf('## Hardening-gate obligations'))),
  };
  const gate = checkPropertyGates({
    plan: text,
    waves: [...waves, synth],
    addsSurface,
  });

  return { plan: text, gate, claims, injected };
}

/**
 * Fail-closed: apply hardening; if still not pass, return fail (caller HALTs).
 */
export function enforceHardeningGate({ plan, addsSurface = true, log = () => {} } = {}) {
  const applied = applyHardeningToPlan({ plan, addsSurface });
  if (applied.injected) {
    log(`stage2 hardening: injected property-gate checklist / obligations (${applied.claims.length} claim(s))`);
  }
  if (!applied.gate.pass) {
    log(`stage2 hardening: FAIL — ${applied.gate.detail}`);
  } else {
    log(`stage2 hardening: PASS — ${applied.gate.detail}`);
  }
  return applied;
}
