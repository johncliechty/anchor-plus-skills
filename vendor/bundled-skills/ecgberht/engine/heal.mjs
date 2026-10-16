/**
 * Heal law — enforceable helpers (Face wins narrative; Strip wins append-only clocks).
 *
 * Law summary:
 * - Face wins human narrative / north-star / why-stakes
 * - Strip wins append-only instrument clocks
 * - crisis = explicit re-sync only (no silent dual-write)
 * - silence = negative-heartbeat (not invented "all clear")
 * - chat cannot invent truth
 * - fence/schema drift repair must not silently rewrite Strip history
 */

import { parseFaceDocument, parseStrip, extractStripFence } from './face-strip.mjs';
import { rewriteFaceNarrative, appendStripInstrument } from './write-authority.mjs';

export const HEAL_LAW = Object.freeze({
  face_wins: 'narrative',
  strip_wins: 'append_only_clocks',
  crisis: 'explicit_re_sync',
  silence: 'negative_heartbeat',
  chat_invents_truth: false,
  silent_strip_rewrite: false,
});

/**
 * Documented heal-law notes for skill/schema consumers.
 */
export const HEAL_LAW_NOTES = Object.freeze([
  'Face wins narrative (north star, active effort prose, why-stakes, human-wait story).',
  'Strip wins append-only clocks and instruments/receipts.',
  'Crisis requires explicit re-sync (healResync with explicit:true); never silent dual-write.',
  'Silence is not green: record negative_heartbeat (dark-night) instead of inventing progress.',
  'Chat cannot invent truth: claims need Face or Strip surface grounding.',
  'Fence/schema drift may be repaired by rewriting the Face fence text from Strip projection without mutating Strip history.',
]);

/**
 * Assess Face vs Strip drift (read-only).
 * @param {object|null} faceNarrative
 * @param {object|null} strip
 */
export function assessDrift(faceNarrative, strip) {
  const issues = [];
  const parsedStrip = strip ? parseStrip(strip) : { ok: false };

  if (!faceNarrative && !parsedStrip.ok) {
    return {
      ok: true,
      drifted: false,
      severity: 'none',
      issues: [{ code: 'empty_surfaces', message: 'No Face or Strip to compare' }],
    };
  }

  if (faceNarrative && parsedStrip.ok) {
    const s = parsedStrip.strip;
    // Soft alignment checks (labels, not authority fights)
    if (
      faceNarrative.active_effort &&
      s.active_effort &&
      typeof faceNarrative.active_effort === 'string' &&
      !faceNarrative.active_effort.includes(String(s.active_effort)) &&
      !String(s.active_effort).includes(faceNarrative.active_effort.slice(0, 40))
    ) {
      issues.push({
        code: 'active_effort_mismatch',
        surface_authority: 'face_for_prose_strip_for_clock',
        message: 'Face active-effort prose and Strip active_effort clock may disagree — crisis heal if true conflict',
      });
    }
  }

  if (parsedStrip.ok) {
    const s = parsedStrip.strip;
    if (s.schema && s.schema !== 'ecgberht-strip-v0') {
      issues.push({ code: 'schema_drift', message: `Strip schema id is ${s.schema}` });
    }
  }

  const drifted = issues.some((i) => i.code !== 'empty_surfaces');
  return {
    ok: true,
    drifted,
    severity: drifted ? 'attention' : 'none',
    issues,
    heal_law: HEAL_LAW,
  };
}

/**
 * Explicit crisis re-sync. Requires explicit:true — refuses ambient/silent heal.
 * Face narrative wins narrative fields; Strip clocks win instrument fields.
 * Strip history is never rewritten: a heal instrument is appended.
 *
 * @param {{ face?: object, strip?: object, explicit?: boolean, reason?: string, strip_clock_patch?: object, face_patch?: object }} args
 */
export function healResync(args = {}) {
  if (args.explicit !== true) {
    return {
      ok: false,
      error: 'heal_requires_explicit',
      message:
        'Crisis heal requires explicit:true. Ambient chat cannot re-sync Face+Strip.',
      heal_law: HEAL_LAW,
    };
  }

  const reason = typeof args.reason === 'string' && args.reason.trim()
    ? args.reason.trim()
    : 'explicit_re_sync';

  let faceResult = null;
  let narrative = args.face && args.face.narrative
    ? { ...args.face.narrative }
    : args.face && typeof args.face === 'object'
      ? { ...args.face }
      : {};

  if (args.face_patch && typeof args.face_patch === 'object') {
    faceResult = rewriteFaceNarrative(narrative, args.face_patch);
    narrative = faceResult.narrative;
  }

  let strip = args.strip ? parseStrip(args.strip) : { ok: false, error: 'no_strip' };
  if (!strip.ok) {
    return {
      ok: false,
      error: strip.error ?? 'no_strip',
      message: 'Heal re-sync needs a Strip surface for clocks',
      heal_law: HEAL_LAW,
    };
  }

  const instrument = {
    kind: 'heal_resync',
    reason,
    at: new Date().toISOString(),
    ...(args.strip_clock_patch && typeof args.strip_clock_patch === 'object'
      ? args.strip_clock_patch
      : {}),
  };

  const appended = appendStripInstrument(strip.strip, instrument, {
    apply_to_projection: true,
  });
  if (!appended.ok) return appended;

  return {
    ok: true,
    mode: 'explicit_re_sync',
    heal_law: HEAL_LAW,
    face_narrative: narrative,
    face_rewritten: faceResult ? faceResult.rewritten : [],
    strip: appended.strip,
    reason,
    message: 'Face narrative authority applied; Strip clocks updated only via append heal instrument',
  };
}

/**
 * Silence → negative-heartbeat helper (does not invent green).
 * Appends instrument; does not silent-rewrite history.
 * @param {object} strip
 * @param {{ why?: string|null, until?: string|null }} [opts]
 */
export function applyNegativeHeartbeat(strip, opts = {}) {
  const nh = {
    no_attention_needed: true,
    why: opts.why ?? 'silence_recorded_as_negative_heartbeat',
    until: opts.until ?? null,
  };
  return appendStripInstrument(
    strip,
    {
      kind: 'negative_heartbeat',
      negative_heartbeat: nh,
    },
    { apply_to_projection: true },
  );
}

/**
 * Chat cannot invent truth: a claim must be grounded in Face narrative or Strip fields.
 * @param {string} claim
 * @param {{ face?: object, strip?: object }} surfaces
 */
export function chatCannotInventTruth(claim, surfaces = {}) {
  const text = typeof claim === 'string' ? claim.trim() : '';
  if (!text) {
    return {
      ok: false,
      error: 'empty_claim',
      invent: false,
      message: 'Empty claim rejected',
    };
  }

  const grounded = [];
  const face = surfaces.face;
  const narrative =
    face?.narrative && typeof face.narrative === 'object'
      ? face.narrative
      : face && typeof face === 'object'
        ? face
        : null;

  if (narrative) {
    for (const [k, v] of Object.entries(narrative)) {
      if (typeof v === 'string' && v && textIncludesLoose(v, text)) {
        grounded.push({ surface: 'face', field: k });
      }
    }
  }

  if (surfaces.strip) {
    const parsed = parseStrip(surfaces.strip);
    if (parsed.ok) {
      const s = parsed.strip;
      for (const key of ['active_effort', 'next_recommended', 'why_next', 'phase', 'human_wait']) {
        const v = s[key];
        if (typeof v === 'string' && v && textIncludesLoose(v, text)) {
          grounded.push({ surface: 'strip', field: key });
        }
      }
    }
  }

  if (grounded.length === 0) {
    return {
      ok: false,
      error: 'chat_cannot_invent_truth',
      invent: false,
      grounded: [],
      message: 'Claim is not grounded in Face or Strip; chat cannot invent truth',
      heal_law: HEAL_LAW,
    };
  }

  return {
    ok: true,
    invent: false,
    grounded,
    message: 'Claim grounded in durable surfaces',
  };
}

function textIncludesLoose(surface, claim) {
  const a = surface.toLowerCase();
  const b = claim.toLowerCase();
  return a.includes(b) || b.includes(a.slice(0, Math.min(a.length, 48)));
}

/**
 * Repair Face fence text from Strip projection without mutating Strip history.
 * Returns new markdown; strip object is unchanged (caller must not rewrite Strip silently).
 * @param {string} faceMarkdown
 * @param {object} strip authoritative Strip projection
 */
export function repairFenceFromStrip(faceMarkdown, strip) {
  const parsed = parseStrip(strip);
  if (!parsed.ok) {
    return { ok: false, ...parsed };
  }

  // Projection only — omit append-only logs from fence body to keep fence lean
  const {
    instruments: _i,
    receipts: _r,
    ...projection
  } = parsed.strip;

  const fenceBody = JSON.stringify(projection, null, 2);
  const newFence = `\`\`\`json\n${fenceBody}\n\`\`\``;

  let markdown = typeof faceMarkdown === 'string' ? faceMarkdown : '';
  const fence = extractStripFence(markdown);

  if (fence.found && fence.jsonText != null) {
    // Replace only the JSON interior of the first matching strip fence
    markdown = markdown.replace(
      /```(?:json)?\s*\r?\n[\s\S]*?```/i,
      newFence,
    );
  } else {
    // Append Strip section
    if (markdown && !markdown.endsWith('\n')) markdown += '\n';
    markdown += `\n## Strip (instrument)\n\n${newFence}\n`;
  }

  return {
    ok: true,
    markdown,
    strip_mutated: false,
    strip_history_rewritten: false,
    message: 'Fence repaired from Strip projection; Strip append-only history untouched',
    heal_law: HEAL_LAW,
  };
}

/**
 * Parse face markdown helper re-export for heal callers.
 */
export function loadFaceNarrativeFromMarkdown(markdown) {
  return parseFaceDocument(markdown);
}
