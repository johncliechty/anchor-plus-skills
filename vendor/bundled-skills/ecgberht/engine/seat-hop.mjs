/**
 * TW4 — Seat hop (Master Plan R2 §4.4).
 *
 * Titlebar seat switcher wired to Anchor prefs (chatgpt/claude/gemini/grok).
 * A seat hop is a NON-EVENT with a receipt: `seat_hop` who/when/from→to.
 * The ledger is the transition document — the next turn continues from
 * Face / Strip / Roadmap / packet with NO re-brief and no chat-history
 * dependency (dialogue is ephemeral, see engine/dialogue.mjs).
 *
 * No host-absolute path literals: prefs paths resolve via env/home only
 * (engine/seating.mjs resolvePrefsCandidatePaths).
 */

import fs from 'node:fs';

import { SPELLING } from './verbs.mjs';
import {
  SEAT_FAMILIES,
  normalizeFamily,
  familyToSubscriptionDriver,
  loadAnchorPrefs,
  resolvePrefsCandidatePaths,
} from './seating.mjs';
import {
  RECEIPT_SCHEMA_ID,
  SEAT_HOP_RECEIPT_FIELDS,
  validateReceipt,
} from './receipt-validate.mjs';

function nonEmpty(v) {
  return v != null && v !== '';
}

/** Durable surfaces the next turn continues from after a hop — no re-brief. */
export const SEAT_HOP_CONTINUES_FROM = Object.freeze([
  'face',
  'strip',
  'roadmap',
  'packet',
]);

/**
 * Map a subscription driver name back to its seat family.
 * @param {*} driver
 * @returns {string|null}
 */
export function driverToFamily(driver) {
  const d = String(driver || '')
    .trim()
    .toLowerCase();
  if (d === 'chatgpt-cli' || d === 'chatgpt' || d === 'codex') return 'chatgpt';
  if (d === 'claude') return 'claude';
  if (d === 'gemini-cli' || d === 'agy' || d === 'gemini') return 'gemini';
  if (d === 'grok-cli' || d === 'grok') return 'grok';
  return null;
}

/**
 * Current seat family from Anchor prefs (injectable for tests).
 * Order: coding_family → default_cli driver. This mirrors the family actually
 * passed to Steward's model call; a stale terminal default may never mislabel it.
 * @param {{ prefs?: object|null, env?: object, prefsPath?: string|null }} [opts]
 * @returns {string}
 */
export function currentSeatFamily(opts = {}) {
  const prefs = loadAnchorPrefs(opts);
  const viaDefaultCli = driverToFamily(prefs.default_cli);
  return prefs.coding_family ?? viaDefaultCli ?? 'claude';
}

/**
 * Build a `seat_hop` receipt — who/when/from→to all required.
 * @param {{ who: string, when?: string, from: string, to: string, as_of?: string }} fields
 */
export function buildSeatHopReceipt(fields = {}) {
  const when = nonEmpty(fields.when)
    ? String(fields.when)
    : new Date().toISOString();
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'seat_hop',
    as_of: fields.as_of ?? when.slice(0, 10),
    who: fields.who ?? null,
    when,
    from: fields.from ?? null,
    to: fields.to ?? null,
    non_event: true,
    re_brief: false,
  };
}

/**
 * Perform a seat hop. Non-event: the session context (Face/Strip/Roadmap/
 * packet references) carries over unchanged; only the seat changes; the
 * receipt is the transition document.
 * @param {{
 *   to: string,
 *   who: string,
 *   when?: string,
 *   session?: object,
 *   prefs?: object|null,
 *   env?: object,
 *   prefsPath?: string|null,
 * }} opts
 */
export function seatHop(opts = {}) {
  const to = normalizeFamily(opts.to);
  if (!to) {
    return {
      ok: false,
      error: 'unknown_seat_family',
      spelling: SPELLING,
      to: opts.to ?? null,
      families: [...SEAT_FAMILIES],
      message: `Seat family must be one of ${SEAT_FAMILIES.join('/')} (Anchor prefs families, never product model IDs).`,
    };
  }
  if (!nonEmpty(opts.who)) {
    return {
      ok: false,
      error: 'seat_hop_requires_who',
      spelling: SPELLING,
      required: [...SEAT_HOP_RECEIPT_FIELDS],
      message: 'seat_hop receipt requires who (who switched the seat).',
    };
  }

  const session =
    opts.session && typeof opts.session === 'object' ? opts.session : {};
  const from = normalizeFamily(session.seat) ?? currentSeatFamily(opts);
  const receipt = buildSeatHopReceipt({
    who: opts.who,
    when: opts.when,
    from,
    to,
  });
  const validated = validateReceipt(receipt);
  if (!validated.ok) {
    return {
      ok: false,
      error: 'seat_hop_receipt_invalid',
      issues: validated.issues ?? [],
      message: validated.message,
    };
  }

  return {
    ok: true,
    non_event: true,
    receipt,
    from,
    to,
    driver: familyToSubscriptionDriver(to),
    no_rebrief: true,
    re_brief_required: false,
    continues_from: [...SEAT_HOP_CONTINUES_FROM],
    // Session carries over untouched except the seat — no context loss.
    session: { ...session, seat: to },
    message: `seat hop ${from}→${to} is a non-event: next turn continues from Face/Strip/Roadmap/packet (receipt only; no re-brief).`,
  };
}

/**
 * Next-turn context after (or without) a hop: built ONLY from durable
 * surfaces — Face, Strip, Roadmap projection, cached Decision Packet.
 * Chat history is never required (ephemeral dialogue policy).
 * @param {{ session?: object, face?: *, strip?: *, roadmap?: *, packet?: * }} [opts]
 */
export function nextTurnContext(opts = {}) {
  const session =
    opts.session && typeof opts.session === 'object' ? opts.session : {};
  const face = opts.face ?? session.face ?? null;
  const strip = opts.strip ?? session.strip ?? null;
  const roadmap = opts.roadmap ?? session.roadmap ?? null;
  const packet = opts.packet ?? session.packet ?? null;

  const sources = [];
  if (face != null) sources.push('face');
  if (strip != null) sources.push('strip');
  if (roadmap != null) sources.push('roadmap');
  if (packet != null) sources.push('packet');

  return {
    ok: true,
    seat: normalizeFamily(session.seat) ?? null,
    re_brief_required: false,
    chat_history_required: false,
    sources,
    context: { face, strip, roadmap, packet },
    message: sources.length
      ? `next turn continues from ${sources.join('/')} — no re-brief`
      : 'no durable surfaces present — honest empty context (chat ledger is never a fallback)',
  };
}

/**
 * Titlebar seat switcher options, read from Anchor prefs.
 * @param {{ prefs?: object|null, env?: object, prefsPath?: string|null }} [opts]
 */
export function titlebarSeatOptions(opts = {}) {
  const prefs = loadAnchorPrefs(opts);
  const current = currentSeatFamily(opts);
  return {
    ok: true,
    surface: 'titlebar_seat_switcher',
    source: 'anchor_prefs',
    prefs_source: prefs.source,
    current,
    options: SEAT_FAMILIES.map((family) => ({
      family,
      driver: familyToSubscriptionDriver(family),
      selected: family === current,
    })),
  };
}

/**
 * Persist the selected Steward seat back to Anchor prefs. `coding_family` is
 * the actual runtime route; `default_cli` and `seat_family` retain UI/legacy parity.
 * Path resolves via injectable prefsPath or env/home candidates — no
 * host-absolute literals. All IO is injectable for tests.
 * @param {{
 *   family: string,
 *   driver: string,
 *   prefsPath?: string|null,
 *   env?: object,
 *   readFile?: Function,
 *   writeFile?: Function,
 *   exists?: Function,
 * }} opts
 */
export function persistSeatToAnchorPrefs(opts = {}) {
  const env = opts.env ?? process.env;
  const target = opts.prefsPath || resolvePrefsCandidatePaths(env)[0] || null;
  if (!target) {
    return { ok: false, error: 'no_prefs_path', persisted: false };
  }
  const read = opts.readFile ?? ((p) => fs.readFileSync(p, 'utf8'));
  const write = opts.writeFile ?? ((p, text) => fs.writeFileSync(p, text));
  const has = opts.exists ?? ((p) => fs.existsSync(p));

  let current = {};
  if (has(target)) {
    try {
      const parsed = JSON.parse(read(target));
      if (parsed && typeof parsed === 'object') current = parsed;
    } catch {
      // unreadable prefs are replaced, never block the hop
    }
  }
  const next = {
    ...current,
    coding_family: opts.family,
    default_cli: opts.driver,
    seat_family: opts.family,
  };
  try {
    write(target, `${JSON.stringify(next, null, 2)}\n`);
  } catch (err) {
    return {
      ok: false,
      error: 'prefs_write_failed',
      message: String(err?.message ?? err),
      persisted: false,
      prefs_path: target,
    };
  }
  return { ok: true, persisted: true, prefs_path: target, prefs: next };
}

/**
 * Titlebar switch action: hop the seat + persist the choice to Anchor prefs.
 * `persist: false` performs the hop (with receipt) without touching disk.
 * @param {{ to: string, who: string, when?: string, session?: object, prefs?: object|null, env?: object, prefsPath?: string|null, persist?: boolean, readFile?: Function, writeFile?: Function, exists?: Function }} opts
 */
export function applyTitlebarSeatSwitch(opts = {}) {
  const hop = seatHop(opts);
  if (!hop.ok) return hop;
  if (opts.persist === false) {
    return { ...hop, persisted: false, prefs_path: null };
  }
  const persisted = persistSeatToAnchorPrefs({
    family: hop.to,
    driver: hop.driver,
    prefsPath: opts.prefsPath,
    env: opts.env,
    readFile: opts.readFile,
    writeFile: opts.writeFile,
    exists: opts.exists,
  });
  if (!persisted.ok) {
    return {
      ...hop,
      persisted: false,
      prefs_path: persisted.prefs_path ?? null,
      persist_error: persisted.error,
    };
  }
  return { ...hop, persisted: true, prefs_path: persisted.prefs_path };
}

/**
 * Closed verb body: `seat-hop --seat <chatgpt|claude|gemini|grok> --who <name>`.
 * The titlebar switcher calls the same path (CLI parity).
 * @param {object} opts parsed verb options + injectors
 */
export function verbSeatHop(opts = {}) {
  const target = opts.seat ?? opts.to ?? null;
  if (!nonEmpty(target)) {
    return {
      ok: false,
      verb: 'seat-hop',
      error: 'seat_target_required',
      spelling: SPELLING,
      families: [...SEAT_FAMILIES],
      usage: 'seat-hop --seat <chatgpt|claude|gemini|grok> [--who <name>] [--when <iso>]',
      message:
        'seat-hop requires --seat <family> (the titlebar switcher passes the selected family).',
    };
  }
  const result = applyTitlebarSeatSwitch({ ...opts, to: target });
  return { verb: 'seat-hop', ...result };
}
