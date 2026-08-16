/**
 * Deterministic dispatch table (W4).
 * phase × uncertainty × human_wait × cost → LITE|FULL|SPIKE|commission|refuse
 *
 * Defaults bias LITE. SPIKE for unknown data shape. FULL only when a cell says so.
 * refuse when human_wait blocks or out-of-scope. capacity=unknown → LITE bias flag
 * (never silent FULL green). depth-suggest reads Strip signals + this table only.
 */

import { loadDispatchTableSeed } from './load.mjs';

export const DISPATCH_OUTCOMES = Object.freeze([
  'LITE',
  'FULL',
  'SPIKE',
  'commission',
  'refuse',
]);

export const DISPATCH_DIMENSIONS = Object.freeze([
  'phase',
  'uncertainty',
  'human_wait',
  'cost',
]);

export const DEFAULT_BIAS = 'LITE';

/** Built-in cells when fixture is missing/empty — LITE-biased, never silent FULL. */
export const BUILTIN_CELLS = Object.freeze([
  {
    phase: 'any',
    uncertainty: 'any',
    human_wait: 'blocked',
    cost: 'any',
    outcome: 'refuse',
    why: 'human_wait blocks depth ceremony',
  },
  {
    phase: 'any',
    uncertainty: 'any',
    human_wait: 'any',
    cost: 'out_of_scope',
    outcome: 'refuse',
    why: 'out-of-scope refuses dispatch',
  },
  {
    phase: 'any',
    uncertainty: 'high',
    human_wait: 'none',
    cost: 'unknown_shape',
    outcome: 'SPIKE',
    why: 'unknown data shape → SPIKE first',
  },
  {
    phase: 'any',
    uncertainty: 'any',
    human_wait: 'none',
    cost: 'unknown_shape',
    outcome: 'SPIKE',
    why: 'unknown data shape → SPIKE',
  },
  {
    phase: 'any',
    uncertainty: 'high',
    human_wait: 'none',
    cost: 'high',
    outcome: 'FULL',
    why: 'high uncertainty + high cost cell',
  },
  {
    phase: 'build',
    uncertainty: 'low',
    human_wait: 'none',
    cost: 'high',
    outcome: 'commission',
    why: 'build with known shape may commission specialist',
  },
  {
    phase: 'planning',
    uncertainty: 'low',
    human_wait: 'none',
    cost: 'low',
    outcome: 'LITE',
    why: 'planning LITE-biased default cell',
  },
  {
    phase: 'build',
    uncertainty: 'low',
    human_wait: 'none',
    cost: 'low',
    outcome: 'LITE',
    why: 'build LITE-biased default cell',
  },
  {
    phase: 'any',
    uncertainty: 'low',
    human_wait: 'none',
    cost: 'low',
    outcome: 'LITE',
    why: 'default LITE bias cell',
  },
  {
    phase: 'any',
    uncertainty: 'medium',
    human_wait: 'none',
    cost: 'low',
    outcome: 'LITE',
    why: 'medium uncertainty still LITE-biased',
  },
]);

/**
 * Load dispatch table (fixture seed + builtins). Fixture cells win on equal specificity
 * when listed first; builtins fill gaps.
 * @param {{ table?: object, cells?: object[] }} [opts]
 */
export function loadDispatchTable(opts = {}) {
  if (opts.table && typeof opts.table === 'object') {
    return normalizeTable(opts.table);
  }
  if (Array.isArray(opts.cells)) {
    return normalizeTable({
      schema: 'ecgberht-dispatch-table-seed-v0',
      bias: DEFAULT_BIAS,
      outcomes: [...DISPATCH_OUTCOMES],
      dimensions: [...DISPATCH_DIMENSIONS],
      cells: opts.cells,
    });
  }
  let seed = null;
  try {
    seed = loadDispatchTableSeed();
  } catch {
    seed = null;
  }
  return normalizeTable(seed);
}

/**
 * @param {object|null} raw
 */
export function normalizeTable(raw) {
  const cells = [];
  const seen = new Set();
  const push = (list) => {
    for (const c of list || []) {
      if (!c || typeof c !== 'object') continue;
      const outcome = normalizeOutcome(c.outcome);
      if (!outcome) continue;
      const key = cellKey(c);
      if (seen.has(key)) continue;
      seen.add(key);
      cells.push({
        phase: normDim(c.phase, 'any'),
        uncertainty: normDim(c.uncertainty, 'any'),
        human_wait: normDim(c.human_wait, 'any'),
        cost: normDim(c.cost, 'any'),
        outcome,
        why: typeof c.why === 'string' ? c.why : null,
      });
    }
  };
  // Fixture / caller cells first (higher priority on equal specificity via stable sort)
  push(raw?.cells);
  push(BUILTIN_CELLS);

  return {
    schema: raw?.schema ?? 'ecgberht-dispatch-table-seed-v0',
    spelling: 'Ecgberht',
    bias: raw?.bias === 'FULL' ? 'LITE' : DEFAULT_BIAS, // hard LITE bias — never flip default to FULL
    outcomes: [...DISPATCH_OUTCOMES],
    dimensions: [...DISPATCH_DIMENSIONS],
    capacity_rule: raw?.capacity_rule ?? {
      when: 'unknown',
      effect: ['rank_penalty', 'LITE_bias_flag'],
      forbid: 'silent_green',
    },
    cells,
    table_ready: true,
  };
}

function normDim(v, fallback = 'any') {
  if (v == null || v === '') return fallback;
  return String(v).toLowerCase();
}

function normalizeOutcome(v) {
  if (v == null) return null;
  const s = String(v).trim();
  const upper = s.toUpperCase();
  if (upper === 'LITE' || upper === 'FULL' || upper === 'SPIKE') return upper;
  const lower = s.toLowerCase();
  if (lower === 'commission' || lower === 'refuse') return lower;
  return null;
}

function cellKey(c) {
  return [c.phase, c.uncertainty, c.human_wait, c.cost, c.outcome]
    .map((x) => String(x ?? 'any').toLowerCase())
    .join('|');
}

/**
 * Extract dispatch dimensions + flags from Strip (or plain signal object).
 * Reads Strip signals only — no free-form depth inflation.
 * @param {object|null} stripOrSignals
 * @returns {object}
 */
export function extractDispatchSignals(stripOrSignals = null) {
  const s = stripOrSignals && typeof stripOrSignals === 'object' ? stripOrSignals : {};
  const flags = Array.isArray(s.uncertainty_flags) ? [...s.uncertainty_flags] : [];
  const capacity = s.capacity === 'known' ? 'known' : s.capacity === 'unknown' ? 'unknown' : s.capacity ?? null;

  const phase = s.phase != null && s.phase !== '' ? String(s.phase).toLowerCase() : 'any';

  let human_wait = 'none';
  const hw = s.human_wait;
  if (hw != null && String(hw).trim() !== '' && String(hw).toLowerCase() !== 'none') {
    // any non-none wait blocks ceremony (approval, blocked, waiting, …)
    human_wait = 'blocked';
  }

  // capacity_* flags are capacity signals, not ceremony-uncertainty levels
  const ceremonyFlags = flags.filter((f) => !/capacity/i.test(String(f)));

  let uncertainty =
    s.uncertainty != null && s.uncertainty !== ''
      ? String(s.uncertainty).toLowerCase()
      : null;
  if (!uncertainty) {
    if (
      ceremonyFlags.some((f) =>
        /^(high|uncertainty_high|high_uncertainty)$/i.test(String(f)) ||
        /unknown_shape|data_shape|high.?risk|trust_surface|false.?liquidity/i.test(
          String(f),
        ),
      )
    ) {
      uncertainty = 'high';
    } else if (ceremonyFlags.some((f) => /medium|moderate/i.test(String(f)))) {
      uncertainty = 'medium';
    } else if (ceremonyFlags.length === 0) {
      uncertainty = 'low';
    } else {
      uncertainty = 'medium';
    }
  }

  let cost =
    s.cost != null && s.cost !== ''
      ? String(s.cost).toLowerCase()
      : null;
  if (!cost) {
    if (
      flags.some((f) =>
        /unknown_shape|data_shape|unknown_data|unknown.?shape/i.test(String(f)),
      ) ||
      s.data_shape === 'unknown' ||
      s.unknown_data_shape === true
    ) {
      cost = 'unknown_shape';
    } else if (
      flags.some((f) =>
        /out_of_scope|out-of-scope|oos/i.test(String(f)),
      ) ||
      s.out_of_scope === true
    ) {
      cost = 'out_of_scope';
    } else if (
      flags.some((f) =>
        /high_cost|expensive|trust_surface|multi.?phase|platform/i.test(String(f)),
      )
    ) {
      cost = 'high';
    } else {
      cost = 'low';
    }
  }

  const capacity_unknown = capacity === 'unknown';
  // Table defaults LITE; capacity=unknown strengthens LITE bias flag (never silent green)
  const flags_out = {
    lite_bias: true,
    capacity_unknown,
    silent_full_green: false,
    unknown_data_shape: cost === 'unknown_shape',
    human_wait_blocked: human_wait === 'blocked',
  };

  return {
    phase,
    uncertainty,
    human_wait,
    cost,
    capacity: capacity ?? 'unknown',
    uncertainty_flags: flags,
    active_effort: s.active_effort ?? null,
    tool_depth_cell: s.tool_depth_cell ?? null,
    flags: flags_out,
  };
}

/**
 * Specificity score: more concrete dims beat wildcards.
 * @param {object} cell
 */
export function cellSpecificity(cell) {
  let n = 0;
  for (const d of DISPATCH_DIMENSIONS) {
    const v = cell[d];
    if (v != null && String(v).toLowerCase() !== 'any') n += 1;
  }
  return n;
}

/**
 * Whether a table cell matches normalized dimensions.
 * @param {object} cell
 * @param {object} dims
 */
export function cellMatches(cell, dims) {
  for (const d of DISPATCH_DIMENSIONS) {
    const cv = cell[d];
    if (cv == null || String(cv).toLowerCase() === 'any') continue;
    if (String(cv).toLowerCase() !== String(dims[d]).toLowerCase()) return false;
  }
  return true;
}

/**
 * Lookup outcome for dimensions against a table.
 * @param {object} dims extractDispatchSignals result or plain dims
 * @param {{ table?: object }} [opts]
 * @returns {object}
 */
export function lookupDispatch(dims, opts = {}) {
  const table = opts.table ?? loadDispatchTable(opts);
  const d = {
    phase: normDim(dims.phase, 'any'),
    uncertainty: normDim(dims.uncertainty, 'low'),
    human_wait: normDim(dims.human_wait, 'none'),
    cost: normDim(dims.cost, 'low'),
  };

  const matches = (table.cells || []).filter((c) => cellMatches(c, d));
  matches.sort((a, b) => cellSpecificity(b) - cellSpecificity(a));

  let cell = matches[0] ?? null;
  let outcome = cell ? cell.outcome : DEFAULT_BIAS;
  let why = cell?.why ?? (cell ? `table cell → ${outcome}` : 'default LITE bias (no matching cell)');
  let matched = Boolean(cell);
  const flags = {
    lite_bias: true,
    capacity_unknown: dims.capacity === 'unknown' || dims.flags?.capacity_unknown === true,
    silent_full_green: false,
    unknown_data_shape: d.cost === 'unknown_shape' || dims.flags?.unknown_data_shape === true,
    human_wait_blocked: d.human_wait === 'blocked',
    demoted_from_full: false,
    table_default: !matched,
  };

  // capacity=unknown: never silent FULL green — demote FULL → LITE with flag
  if (flags.capacity_unknown && outcome === 'FULL') {
    flags.demoted_from_full = true;
    why = `${why}; capacity=unknown demotes FULL → LITE (never silent FULL green)`;
    outcome = 'LITE';
  }

  // LITE bias flag on LITE outcomes, capacity-unknown, or unmatched default
  flags.lite_bias =
    outcome === 'LITE' || flags.capacity_unknown || flags.table_default;

  // Explicit: never report silent FULL green
  flags.silent_full_green = false;

  const tool_depth_why = buildToolDepthWhy({ outcome, why, dims: d, flags, cell });

  return {
    ok: true,
    table_ready: true,
    outcome,
    cell: cell
      ? {
          phase: cell.phase,
          uncertainty: cell.uncertainty,
          human_wait: cell.human_wait,
          cost: cell.cost,
          outcome: cell.outcome,
          why: cell.why,
        }
      : {
          phase: d.phase,
          uncertainty: d.uncertainty,
          human_wait: d.human_wait,
          cost: d.cost,
          outcome: DEFAULT_BIAS,
          why: 'default LITE bias',
          synthetic: true,
        },
    dimensions: d,
    flags,
    why,
    tool_depth_why,
    bias: DEFAULT_BIAS,
    matched,
  };
}

/**
 * Full suggest path: Strip signals → table → structured cell (no free-form).
 * @param {object|null} stripOrSignals
 * @param {{ table?: object }} [opts]
 */
export function suggestDepthFromStrip(stripOrSignals, opts = {}) {
  const signals = extractDispatchSignals(stripOrSignals);
  const result = lookupDispatch(signals, opts);
  const uncertainty_flags = [...signals.uncertainty_flags];
  if (
    result.flags.capacity_unknown &&
    !uncertainty_flags.includes('capacity_unknown')
  ) {
    uncertainty_flags.push('capacity_unknown');
  }
  if (result.flags.lite_bias && !uncertainty_flags.includes('LITE_bias')) {
    uncertainty_flags.push('LITE_bias');
  }

  return {
    ...result,
    signals,
    uncertainty_flags,
    capacity: signals.capacity,
  };
}

function buildToolDepthWhy({ outcome, why, dims, flags, cell }) {
  const parts = [
    `outcome=${outcome}`,
    `phase=${dims.phase}`,
    `uncertainty=${dims.uncertainty}`,
    `human_wait=${dims.human_wait}`,
    `cost=${dims.cost}`,
  ];
  if (flags.capacity_unknown) parts.push('capacity=unknown→LITE_bias');
  if (flags.unknown_data_shape) parts.push('unknown_data_shape→SPIKE_path');
  if (flags.demoted_from_full) parts.push('demoted_FULL');
  if (cell?.why) parts.push(cell.why);
  else if (why) parts.push(why);
  return parts.join('; ');
}

/**
 * Apply a human override of table outcome. Requires structured reason fields.
 * Does not mutate table — returns override envelope for receipt-validate.
 * @param {string} fromOutcome
 * @param {string} toOutcome
 * @param {{ who: string, when: string, why: string }} reason
 */
export function applyDepthOverride(fromOutcome, toOutcome, reason = {}) {
  const from = normalizeOutcome(fromOutcome);
  const to = normalizeOutcome(toOutcome);
  const issues = [];
  if (!from) issues.push('override.from required (valid outcome)');
  if (!to) issues.push('override.to required (valid outcome)');
  for (const key of ['who', 'when', 'why']) {
    if (reason[key] == null || reason[key] === '') {
      issues.push(`override.${key} required`);
    }
  }
  if (issues.length) {
    return {
      ok: false,
      error: 'override_receipt_required',
      message: `Human override requires structured receipt reason (who/when/why/from→to): ${issues.join('; ')}`,
      issues,
    };
  }
  return {
    ok: true,
    outcome: to,
    override: {
      who: reason.who,
      when: reason.when,
      why: reason.why,
      from,
      to,
    },
    tool_depth_why: `human override ${from}→${to}: ${reason.why}`,
  };
}
