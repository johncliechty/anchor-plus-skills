/**
 * Strip-first portfolio rank.
 * Ranks Strip projections only — never N-full-reads Faces.
 * Full Face only for top-k drill-in or heal (callers pass drill separately).
 *
 * Unknown capacity floor: capacity=unknown → rank penalty + LITE bias flag;
 * never silent green.
 * Anti-starvation: negative_heartbeat + anti_starvation_age_days.
 */

import { toStripProjection } from './face-strip.mjs';

/** Rank score penalty when capacity is unknown (stricter than zero). */
export const CAPACITY_UNKNOWN_PENALTY = 50;

/** Base weight per starvation day. */
export const STARVATION_DAY_WEIGHT = 3;

/** Boost when human_wait is not none. */
export const HUMAN_WAIT_BOOST = 40;

/** Penalty when negative_heartbeat says no attention needed. */
export const NEGATIVE_HEARTBEAT_PENALTY = 80;

/**
 * Build a rank projection from a strip object or discovery hit.
 * Never requires Face.
 * @param {object} stripOrHit
 * @returns {object|null}
 */
export function stripProjectionForRank(stripOrHit) {
  if (!stripOrHit || typeof stripOrHit !== 'object') return null;

  // Discovery hit already has projection
  if (stripOrHit.projection && stripOrHit.strip) {
    return {
      ...stripOrHit.projection,
      project_path: stripOrHit.project_path ?? stripOrHit.projection.project_path,
      strip_source: stripOrHit.strip_source ?? stripOrHit.projection.strip_source,
      face_loaded: false,
    };
  }

  if (stripOrHit.projection && !stripOrHit.strip) {
    return { ...stripOrHit.projection, face_loaded: false };
  }

  const strip = stripOrHit.strip ?? stripOrHit;
  const proj = toStripProjection(strip, {
    project_path: stripOrHit.project_path,
    strip_source: stripOrHit.strip_source,
  });
  if (!proj) return null;
  return { ...proj, face_loaded: false };
}

/**
 * Score a single Strip projection (no Face fields consulted).
 * @param {object} projection
 * @returns {{ score: number, flags: object, reasons: string[] }}
 */
export function scoreStripProjection(projection) {
  const reasons = [];
  const flags = {
    lite_bias: false,
    capacity_unknown: false,
    silent_green: false,
    negative_heartbeat: false,
    anti_starvation: false,
    human_wait: false,
  };

  let score = 100;

  const capacity = projection?.capacity === 'known' ? 'known' : 'unknown';
  if (capacity === 'unknown') {
    score -= CAPACITY_UNKNOWN_PENALTY;
    flags.capacity_unknown = true;
    flags.lite_bias = true;
    flags.silent_green = false; // never silent green
    reasons.push('capacity_unknown_penalty');
    reasons.push('lite_bias');
  }

  const age =
    typeof projection?.anti_starvation_age_days === 'number'
      ? projection.anti_starvation_age_days
      : 0;
  if (age > 0) {
    score += age * STARVATION_DAY_WEIGHT;
    flags.anti_starvation = true;
    reasons.push(`anti_starvation_age_days=${age}`);
  }

  const wait = projection?.human_wait;
  if (wait && wait !== 'none') {
    score += HUMAN_WAIT_BOOST;
    flags.human_wait = true;
    reasons.push('human_wait_boost');
  }

  const nh = projection?.negative_heartbeat;
  if (nh && nh.no_attention_needed === true) {
    score -= NEGATIVE_HEARTBEAT_PENALTY;
    flags.negative_heartbeat = true;
    flags.silent_green = false;
    reasons.push('negative_heartbeat_downrank');
  }

  // Explicit: unknown capacity must never present as green/all-clear
  let attention_color =
    capacity === 'unknown'
      ? 'amber'
      : nh?.no_attention_needed
        ? 'dim'
        : score >= 100
          ? 'attention'
          : 'normal';

  // Hard floor: capacity=unknown can never surface as silent green
  if (capacity === 'unknown') {
    flags.silent_green = false;
    flags.lite_bias = true;
    if (attention_color === 'green' || attention_color === 'normal') {
      attention_color = 'amber';
    }
  }

  return {
    score,
    flags,
    reasons,
    attention_color,
    capacity,
    /** Rank used Strip projection only — Face fields never consulted. */
    face_consulted: false,
  };
}

/**
 * Rank portfolio from Strip projections only.
 * @param {object[]} stripsOrHits discovery hits, strips, or projections
 * @param {{ top_k?: number }} [opts]
 * @returns {{ ok: true, ranked: object[], face_loads_for_rank: 0, top_k: number, drill_in_eligible: object[] }}
 */
export function rankPortfolioStripFirst(stripsOrHits = [], opts = {}) {
  const top_k = typeof opts.top_k === 'number' && opts.top_k > 0 ? opts.top_k : 3;
  const items = Array.isArray(stripsOrHits) ? stripsOrHits : [];

  const ranked = [];
  for (const item of items) {
    const projection = stripProjectionForRank(item);
    if (!projection) continue;
    const scored = scoreStripProjection(projection);
    ranked.push({
      project_id: projection.project_id,
      project_path: projection.project_path,
      score: scored.score,
      flags: scored.flags,
      reasons: scored.reasons,
      attention_color: scored.attention_color,
      capacity: scored.capacity,
      negative_heartbeat: projection.negative_heartbeat,
      anti_starvation_age_days: projection.anti_starvation_age_days,
      human_wait: projection.human_wait,
      next_recommended: projection.next_recommended,
      why_next: projection.why_next,
      active_effort: projection.active_effort,
      phase: projection.phase,
      // Prove strip-first: rank path never marks Face as loaded
      face_loaded: false,
      face_required_for_rank: false,
      projection,
    });
  }

  ranked.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const ap = a.project_id ?? a.project_path ?? '';
    const bp = b.project_id ?? b.project_path ?? '';
    return String(ap).localeCompare(String(bp));
  });

  const drill_in_eligible = ranked.slice(0, top_k);

  return {
    ok: true,
    ranked,
    face_loads_for_rank: 0,
    face_required_for_rank: false,
    top_k,
    drill_in_eligible,
    message:
      'Portfolio rank used Strip projections only; full Face reserved for top-k drill-in or heal',
  };
}

/**
 * Whether a rank result ever required full Face load (should always be false).
 * @param {object} rankResult
 */
export function rankRequiredFullFace(rankResult) {
  if (!rankResult || !Array.isArray(rankResult.ranked)) return false;
  if (rankResult.face_loads_for_rank > 0) return true;
  if (rankResult.face_required_for_rank) return true;
  return rankResult.ranked.some((r) => r.face_loaded === true || r.face_required_for_rank === true);
}
