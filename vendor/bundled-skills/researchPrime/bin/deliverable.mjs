// bin/deliverable.mjs — Wave 10: Deliverable assembly and rendering (Wave 10 changes recovered)+ HONEST DEGRADED MODE (Phase E).
//
// MASTER-PLAN Phase E / IMPLEMENTATION-PLAN Wave 10 done-when: assemble the run's final deliverable so
// it CARRIES — as first-class, separable sections —
//   • the ROUND HISTORY (the Wave-7 multi-round adversarial loop, per-round),
//   • the JUDGE VERDICT (G4, the separate context-free decider),
//   • the CONVERGENCE PROOF (the Wave-7 honest convergence tracker's final state + per-round trail),
//   • ρ̂ + the LEARNED-QUORUM STATE (the Wave-9 calibration verdict — carried in BOTH modes because
//     default-mode calibration is a pure function of inputs), and
//   • the separate SYNTHESIZER BRIEF (the active Deep-Think steer — kept STRICTLY SEPARATE from the
//     Judge verdict: the Synthesizer steers, it never decides — premortem #6 / crit-6).
//
// And it makes the DEGRADED (non-engine / prose) mode HONEST:
//   • a non-engine run emits the literal HONESTY STAMP ("schema conforms; adversarial verification did
//     NOT run") and force-sets `cross_model:false` (I3 — degraded mode is never an independence claim);
//   • the user-facing prose surfaces (the three researchPrime summary levels) of a prose-mode
//     deliverable NEVER claim "parity" with an engine-verified result — the output-conformance gate
//     (test/output-conformance.test.mjs) forbids the literal word in every prose-mode surface.
//
// REUSE, NOT FORK: this module ASSEMBLES already-produced outputs (round.mjs's `orchestrateRound`
// results, its `makeConvergenceTracker` state, and rho-ledger.mjs's `calibrationVerdict`) into the
// deliverable shape + renders the user surfaces. It computes no verification of its own and re-homes no
// gate logic; it is the presentation seam on top of Waves 6–9. `MODES` is the SAME two-mode taxonomy the
// evidenced core (verify-core.mjs) already locks, imported not re-declared.
//
// PURITY: every function here is a deterministic, side-effect-free function of its inputs — no clock, no
// randomness, no I/O. The deliverable is a value; rendering it is a pure projection of that value.

import { MODES } from './verify-core.mjs';
// HALT-for-human signalling — the single upstream class, via the canonical trio-core specifier (no fork).
import { HaltError } from '#trio-core/contract-core.mjs';

/**
 * The literal honesty stamp a NON-ENGINE (prose/degraded) run wears (done-when). Asserted verbatim by
 * the output-conformance gate — a host that cannot run the adversarial loop says so in exactly these
 * words, never silently presenting prose as if it were verified.
 */
export const HONESTY_STAMP = 'schema conforms; adversarial verification did NOT run';

/** researchPrime's three deliverable summary levels — the user-facing surfaces (the prose check's scope). */
export const SUMMARY_LEVELS = Object.freeze(['full', 'executive', 'agent-implementation']);

/**
 * The word FORBIDDEN in any prose-mode (non-engine) user surface (done-when). A degraded run must not
 * imply it is on par / "parity" with an engine-verified result — the honesty stamp already says
 * verification did not run, and no surface may walk that back.
 */
export const FORBIDDEN_PROSE_WORD = 'parity';

// ── cross_model (I3): a heterogeneity proxy, true ONLY in the engine across attested distinct lineages ──
/**
 * `cross_model` is TRUE only in ENGINE mode AND when the run actually spanned ≥2 distinct substrate
 * families (a heterogeneity PROXY, never an independence guarantee — I3). DEGRADED mode forces it FALSE
 * unconditionally: a host that did not run the adversarial loop cannot claim cross-model anything.
 */
export function crossModelFor(mode, substrateFamilies = []) {
  if (mode !== 'engine') return false; // I3: degraded ⇒ cross_model:false, always
  const fams = new Set(
    (Array.isArray(substrateFamilies) ? substrateFamilies : [])
      .filter((f) => typeof f === 'string' && f.trim().length > 0)
      .map((f) => f.trim()),
  );
  return fams.size >= 2;
}

// ── ROUND HISTORY — the per-round trail of the Wave-7 loop ───────────────────────────────────────────
/**
 * Project the raw `orchestrateRound` results into a compact, auditable round-history trail: one record
 * per round naming what that round did (dry/empty, finding count, the GATE-1 origin quorum, conflicts,
 * whether G9 debate fired). This is the deliverable's "round history" section.
 */
export function deriveRoundHistory(rounds = []) {
  if (!Array.isArray(rounds)) throw new HaltError('deriveRoundHistory requires a rounds[] array');
  return rounds.map((r, i) => ({
    round: Number.isInteger(r?.round) ? r.round : i + 1,
    dry: !!r?.dry,
    empty: !!r?.empty,
    findings: Array.isArray(r?.tally?.findings) ? r.tally.findings.length : 0,
    quorum: r?.quorum
      ? { origins: r.quorum.origins ?? 0, required: r.quorum.required ?? null, met: !!r.quorum.met }
      : null,
    conflicts: Array.isArray(r?.conflicts) ? r.conflicts.length : 0,
    debate_fired: !!r?.debate?.fired,
  }));
}

// ── SYNTHESIZER BRIEF — the steer, kept STRICTLY SEPARATE from the Judge verdict ─────────────────────
/**
 * Build the Synthesizer Brief from the per-round `direction` outputs. It is a SEPARATE section
 * (premortem #6 / crit-6: the Synthesizer steers, it never decides) and is stamped `decides:false` so
 * the conformance gate can assert it is never conflated with the Judge's verdict (G4 decides).
 */
export function buildSynthesizerBrief(rounds = []) {
  if (!Array.isArray(rounds)) throw new HaltError('buildSynthesizerBrief requires a rounds[] array');
  const perRound = rounds
    .map((r, i) => ({ round: Number.isInteger(r?.round) ? r.round : i + 1, direction: r?.direction ?? null }))
    .filter((x) => x.direction != null);
  return {
    role: 'synthesizer',
    decides: false, // crit-6: STEERS, never decides — the separate Judge (G4) decides.
    note: 'STEERING ONLY — the Synthesizer steers; the separate context-free Judge (G4) decides.',
    rounds: perRound,
  };
}

// ── The DELIVERABLE assembler ────────────────────────────────────────────────────────────────────────
/**
 * Assemble the run's final deliverable VALUE.
 *
 * ENGINE mode: the full adversarially-verified deliverable — round history, the final round's Judge
 * verdict, the convergence proof, the calibration (ρ̂ + learned-quorum) state, and the separate
 * Synthesizer Brief. `cross_model` reflects the actual substrate.
 *
 * DEGRADED / non-engine mode: the adversarial loop did NOT run on this host, so the verification-only
 * sections are NULL and the deliverable carries the literal HONESTY STAMP with `cross_model:false`
 * (I3). The calibration state is still carried (default-mode ρ̂/learned-quorum is a pure function of
 * inputs), so the deliverable never has to fabricate or omit it.
 *
 * @param {object} o
 * @param {'engine'|'degraded'} o.mode
 * @param {Array<object>} [o.rounds]              raw orchestrateRound results (round history source)
 * @param {?object}       [o.convergence]         the convergence tracker's final state (the proof)
 * @param {?object}       [o.calibration]         the Wave-9 calibrationVerdict (ρ̂ + learned-quorum state)
 * @param {string[]}      [o.substrateFamilies]   the model families actually reachable this run
 * @param {?string}       [o.northStar]
 * @returns {object} the deliverable value
 */
export function assembleDeliverable({
  mode,
  rounds = [],
  convergence = null,
  calibration = null,
  substrateFamilies = [],
  northStar = null,
} = {}) {
  if (!MODES.includes(mode)) {
    throw new HaltError(`assembleDeliverable: mode must be one of ${MODES.join(' | ')}, got ${JSON.stringify(mode)}`);
  }
  const cross_model = crossModelFor(mode, substrateFamilies);
  const base = {
    mode,
    north_star: northStar ?? null,
    cross_model,
    // ρ̂ + learned-quorum state — carried in BOTH modes (default-mode calibration is pure-of-inputs).
    calibration: calibration ?? null,
    rho_hat: calibration?.rho_hat ?? null,
  };

  if (mode !== 'engine') {
    // Non-engine / prose / degraded: the adversarial loop did NOT run on this host. Say so, honestly.
    return {
      ...base,
      verified: false,
      honesty_stamp: HONESTY_STAMP,
      round_history: [],
      judge_verdict: null,
      convergence_proof: null,
      synthesizer_brief: null,
    };
  }

  // Engine mode: the full, adversarially-verified deliverable.
  const finalRound = rounds.length ? rounds[rounds.length - 1] : null;
  return {
    ...base,
    verified: true,
    honesty_stamp: null,
    round_history: deriveRoundHistory(rounds),
    judge_verdict: engineJudgeVerdict(finalRound),
    convergence_proof: convergence ?? null,
    synthesizer_brief: buildSynthesizerBrief(rounds),
  };
}

/**
 * The engine deliverable's judge section. P0 2026-07-25: a GOVERNED run may legitimately
 * have no Judge verdict — the stakes governor excludes the Judge below the adjudication
 * floor (crit-2), and the inclusion test skips zero-AXIS rounds entirely (crit-4). Those
 * are HONEST absences and must be CARRIED as explicit exclusion stamps, not null — so the
 * output-conformance gate still catches a verdict that is missing for any OTHER reason
 * (a judge that should have run and didn't stays a contract violation).
 */
function engineJudgeVerdict(finalRound) {
  const jv = finalRound?.judgeVerdict;
  if (jv != null) return jv;
  if (finalRound?.skipped === true) {
    return {
      excluded: true,
      by: 'inclusion-test',
      reason: finalRound.reason ?? 'zero-AXIS-finding round skipped (crit-4) — no adjudication ran',
    };
  }
  if (finalRound?.policy && finalRound.policy.judge === false) {
    return {
      excluded: true,
      by: 'stakes-governor',
      tier: finalRound.tier ?? null,
      reason: finalRound.policy.reason ?? 'governor tier below the adjudication floor — Judge excluded (crit-2)',
    };
  }
  return null; // genuinely missing — the conformance gate rejects this, by design
}

// ── USER SURFACES — researchPrime's three summary levels (pure projections of the deliverable) ────────
function fmtConvergence(c) {
  if (!c || typeof c !== 'object') return 'convergence: (none recorded)';
  return `convergence: ${c.converged ? 'CONVERGED' : 'not converged'} ` +
    `(dryStreak=${c.dryStreak ?? '?'}, counted=${c.countedRounds ?? '?'}, rounds=${c.rounds ?? '?'})`;
}

function fmtCalibration(d) {
  const c = d.calibration;
  if (!c) return 'ρ̂: (calibration not carried)';
  const rho = c.rho_hat == null ? 'unestimated' : String(c.rho_hat);
  return `ρ̂: ${rho} · learned-quorum required=${c.required ?? '?'} ` +
    `(static would require ${c.static_would_require ?? '?'}) · ${c.stamp ?? c.mode ?? ''}`.trim();
}

/**
 * Render ONE user-facing summary surface (a string) for a deliverable. The three levels mirror
 * researchPrime's full / executive / agent-implementation tiers. A NON-ENGINE deliverable's surfaces
 * lead with the honesty stamp and NEVER use the forbidden "parity" claim (the conformance gate enforces
 * this); an engine deliverable's surfaces report the verified result.
 *
 * @param {object} deliverable  the value from assembleDeliverable
 * @param {'full'|'executive'|'agent-implementation'} level
 * @returns {string}
 */
export function renderSurface(deliverable, level) {
  if (!SUMMARY_LEVELS.includes(level)) {
    throw new HaltError(`renderSurface: level must be one of ${SUMMARY_LEVELS.join(' | ')}, got ${JSON.stringify(level)}`);
  }
  if (!deliverable || typeof deliverable !== 'object' || !MODES.includes(deliverable.mode)) {
    throw new HaltError('renderSurface requires a deliverable from assembleDeliverable');
  }
  const ns = deliverable.north_star ? `North Star: ${deliverable.north_star}` : 'North Star: (unset)';

  if (deliverable.mode !== 'engine') {
    // Prose / degraded mode. HONEST: leads with the stamp; makes NO equivalence/"parity" claim.
    const stamp = `Honesty: ${deliverable.honesty_stamp}`;
    const xm = `cross_model: ${deliverable.cross_model}`;
    if (level === 'executive') {
      return [`researchPrime (DEGRADED prose mode) — UNVERIFIED.`, stamp, xm].join('\n');
    }
    if (level === 'agent-implementation') {
      return [
        `# researchPrime deliverable [mode=degraded verified=false]`,
        stamp,
        xm,
        fmtCalibration(deliverable),
        `findings are SCHEMA-CONFORMANT prose only — re-run on an engine host for adversarial verification.`,
      ].join('\n');
    }
    // full
    return [
      `# researchPrime Deliverable — DEGRADED (prose) mode`,
      stamp,
      xm,
      ns,
      ``,
      `This host could not run the adversarial verification loop (G1–G9). The output below conforms to`,
      `the deliverable SCHEMA only: there is NO Judge verdict, NO convergence proof, and NO round`,
      `history. Treat every finding as UNVERIFIED prose — it has not been independently checked. To`,
      `obtain a verified result, re-run on an engine host.`,
      fmtCalibration(deliverable),
    ].join('\n');
  }

  // Engine mode: the verified surfaces.
  const j = deliverable.judge_verdict;
  const jline = `Judge verdict: ${j ? (j.verdict ?? j.decision ?? JSON.stringify(j)) : '(none)'}`;
  const rounds = `rounds: ${deliverable.round_history.length}`;
  if (level === 'executive') {
    return [`researchPrime (engine, VERIFIED).`, jline, fmtConvergence(deliverable.convergence_proof)].join('\n');
  }
  if (level === 'agent-implementation') {
    return [
      `# researchPrime deliverable [mode=engine verified=true]`,
      `cross_model: ${deliverable.cross_model}`,
      jline,
      rounds,
      fmtConvergence(deliverable.convergence_proof),
      fmtCalibration(deliverable),
      `synthesizer_brief: present (decides=${deliverable.synthesizer_brief?.decides}) — steering only.`,
    ].join('\n');
  }
  // full
  return [
    `# researchPrime Deliverable — ENGINE (adversarially verified)`,
    ns,
    `cross_model: ${deliverable.cross_model}`,
    jline,
    rounds,
    fmtConvergence(deliverable.convergence_proof),
    fmtCalibration(deliverable),
    ``,
    `Round history and the separate Synthesizer Brief (steering only — the Judge decides) accompany`,
    `this report as structured sections.`,
  ].join('\n');
}

/** Render all three summary-level surfaces of a deliverable as `{ level: text }`. */
export function renderAllSurfaces(deliverable) {
  return Object.fromEntries(SUMMARY_LEVELS.map((l) => [l, renderSurface(deliverable, l)]));
}

// ── The OUTPUT-CONFORMANCE gate (the predicate test/output-conformance.test.mjs asserts on) ──────────
/** Does `text` use the forbidden prose word as a whole word (case-insensitive)? */
export function containsForbiddenProse(text) {
  return new RegExp(`\\b${FORBIDDEN_PROSE_WORD}\\b`, 'i').test(String(text ?? ''));
}

/**
 * Check a deliverable against the Wave-10 output contract, returning `{ ok, violations }`.
 *
 * NON-ENGINE (prose) mode: must carry the literal honesty stamp, force `cross_model:false` (I3), and
 * NO user surface may contain the forbidden "parity" claim.
 * ENGINE mode: must carry every required section — round history, Judge verdict, convergence proof, the
 * calibration (ρ̂ + learned-quorum) state, and the Synthesizer Brief — and the Brief must be SEPARATE
 * from the Judge verdict (it must NOT decide).
 *
 * @returns {{ ok:boolean, violations:string[] }}
 */
export function checkOutputConformance(deliverable) {
  const violations = [];
  if (!deliverable || typeof deliverable !== 'object' || !MODES.includes(deliverable.mode)) {
    return { ok: false, violations: ['not a deliverable (missing/invalid mode)'] };
  }
  const surfaces = renderAllSurfaces(deliverable);

  if (deliverable.mode !== 'engine') {
    if (deliverable.honesty_stamp !== HONESTY_STAMP) {
      violations.push('non-engine deliverable must carry the exact honesty stamp');
    }
    if (deliverable.cross_model !== false) {
      violations.push('non-engine deliverable must force cross_model:false (I3)');
    }
    for (const [level, text] of Object.entries(surfaces)) {
      if (containsForbiddenProse(text)) {
        violations.push(`prose-mode surface '${level}' claims "${FORBIDDEN_PROSE_WORD}" (forbidden)`);
      }
    }
    return { ok: violations.length === 0, violations };
  }

  // Engine mode: every section must be carried.
  for (const k of ['round_history', 'judge_verdict', 'convergence_proof', 'calibration', 'synthesizer_brief']) {
    if (deliverable[k] == null) violations.push(`engine deliverable missing required section: ${k}`);
  }
  if (deliverable.synthesizer_brief && deliverable.synthesizer_brief.decides !== false) {
    violations.push('Synthesizer Brief must be SEPARATE from the Judge verdict (decides must be false)');
  }
  return { ok: violations.length === 0, violations };
}

// Re-export the two-mode taxonomy so a consumer/test reads the SAME modes the evidenced core locks.
export { MODES };
