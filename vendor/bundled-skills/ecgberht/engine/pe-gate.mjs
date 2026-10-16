/**
 * TW8 — Progressive-enhancement HARD GATE + E7 Roadmap stubs.
 *
 * Charm never ships before the spine. The three progressive-enhancement
 * features (voice · living animation · calendar/email proactivity) are
 * blocked behind a hard gate that opens ONLY when BOTH hold:
 *
 *   1. SPINE GREEN — the TW5 Seal chamber and the TW6 High Seat / Decision
 *      Packet surfaces pass their structural probes (real assemblies of the
 *      shipped chambers, checked against the locked falsify quotes — never
 *      a config bit someone can flip).
 *   2. EXPLICIT CONFIG — the feature is enabled with a literal `true` in
 *      the PE config. Truthy strings, 1, "yes" are NOT explicit; the
 *      default config enables nothing.
 *
 * Either missing → structured refuse (pe_gate_refused). There is no
 * override receipt for this gate — it opens by evidence, not permission.
 *
 * E7 (calendar/email) is RECORDED, NOT BUILT: the Roadmap gains parked
 * future steps from a template (templates/roadmap-e7-stubs.json) appended
 * through the TW1 single writer — and nothing else. No connector, no OAuth
 * code, anywhere in the engine; runE7NotBuiltCanary scans sources to keep
 * it that way (an implemented connector marker + import/network call is a
 * red build).
 */

import fs from 'node:fs';
import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import {
  skillRoot,
  loadStripFixture,
  loadRoadmapFixture,
  loadE7StubTemplate,
} from './load.mjs';
import { verbStatus } from './verb-bodies.mjs';
import { assembleBriefPacket } from './brief.mjs';
import {
  SEAL_CHAMBER_SCHEMA_ID,
  CHAMBER_FOOTER_STAMP,
  assembleSealChamber,
  chamberAgreesWithStatus,
} from './seal-chamber.mjs';
import {
  HIGH_SEAT_SCHEMA_ID,
  MAX_RAISED_BLOCKS,
  assembleHighSeat,
} from './high-seat.mjs';
import { assemblePacketView } from './packet-view.mjs';
import {
  appendRoadmapEvent,
  emptyRoadmap,
  ROADMAP_SINGLE_WRITER,
} from './roadmap.mjs';
import { appendRoadmapEventThroughSpine } from './ledger-spine.mjs';

export const PE_GATE_SCHEMA_ID = 'ecgberht-pe-gate-v0';

/** The gated progressive-enhancement features — closed list. */
export const PE_FEATURES = Object.freeze([
  'voice',
  'living_animation',
  'calendar_email',
]);

/** Plain subtitles (house style). */
export const PE_FEATURE_LABELS = Object.freeze({
  voice: 'voice I/O (chat first — the spine speaks in text)',
  living_animation: 'living animation (the seal breathes only over a green spine)',
  calendar_email: 'calendar/email proactivity (E7 — parked Roadmap steps until its own wave)',
});

/** Which waves the spine check covers. */
export const PE_SPINE_WAVES = Object.freeze(['TW5', 'TW6']);

/** The gate law, exported for docs and refusals. */
export const PE_GATE_LAW = Object.freeze({
  gate: 'hard',
  requires: Object.freeze({
    spine_green: 'TW5 Seal chamber + TW6 High Seat / Decision Packet structural probes pass',
    explicit_config: 'PE config enables the feature with a literal true (default: everything off)',
  }),
  override_receipt: null,
  message:
    'Progressive enhancement is blocked until the spine is green AND the feature is explicitly configured — charm never ships before the spine.',
});

// ---------------------------------------------------------------------------
// PE config — explicit true only, default everything off
// ---------------------------------------------------------------------------

/** Default PE config: every feature off. */
export function defaultPeConfig() {
  const enable = {};
  for (const f of PE_FEATURES) enable[f] = false;
  return { schema: PE_GATE_SCHEMA_ID, enable };
}

/**
 * Normalize a PE config. Only a literal `true` counts as explicit —
 * truthy strings / numbers / missing keys all normalize to off.
 * @param {object|null|undefined} config
 * @returns {{ schema: string, enable: Record<string, boolean>, explicit_only: true }}
 */
export function normalizePeConfig(config) {
  const raw =
    config && typeof config === 'object' && !Array.isArray(config)
      ? (config.enable && typeof config.enable === 'object' ? config.enable : config)
      : {};
  const enable = {};
  for (const f of PE_FEATURES) enable[f] = raw[f] === true;
  return { schema: PE_GATE_SCHEMA_ID, enable, explicit_only: true };
}

// ---------------------------------------------------------------------------
// Spine probes — real assemblies of the shipped TW5/TW6 surfaces
// ---------------------------------------------------------------------------

const PROBE_NORTH_STAR =
  'Take-charge steward: John only decides when the homework is done.';

/** Injected prefs — probes never read the real home dir. */
const PROBE_PREFS = Object.freeze({
  coding_family: 'claude',
  review_family: 'grok',
  default_cli: 'claude',
});

function spineInjection() {
  const strip = { ...loadStripFixture(), project_id: 'tw8-spine-probe' };
  return {
    project: 'tw8-spine-probe',
    surfaces: {
      strip,
      strip_source: 'strip_json',
      face: {
        narrative: {
          north_star: PROBE_NORTH_STAR,
          current_state: 'spine probe',
        },
      },
    },
    roadmap: loadRoadmapFixture(),
    journal: { present: false, entries: [] },
    anchor_knowledge: { present: false },
    prefs: { ...PROBE_PREFS },
  };
}

function probeItems() {
  return [
    {
      project_id: 'probe-a',
      project_path: 'projects/probe-a',
      active_effort: 'wave 1/2',
      goal_phrase: 'Spine probe A.',
      human_wait: 'none',
      capacity: 'known',
      anti_starvation_age_days: 0,
      packet_ready: false,
      waiting_steps: 0,
    },
    {
      project_id: 'probe-b',
      project_path: 'projects/probe-b',
      active_effort: null,
      goal_phrase: 'Spine probe B.',
      human_wait: 'one decision',
      capacity: 'known',
      anti_starvation_age_days: 1,
      packet_ready: true,
      waiting_steps: 1,
    },
  ];
}

/**
 * TW5 probe — assemble the shipped Seal chamber from fixtures and check the
 * Screen 1 falsify quotes structurally (goal first, engine rail, steward
 * first, no instrument-primary face, CLI parity).
 * @returns {{ wave: 'TW5', ok: boolean, checks: {check: string, pass: boolean}[], error?: string }}
 */
export function probeTw5SealChamber() {
  const checks = [];
  const push = (check, pass) => checks.push({ check, pass: pass === true });

  let chamber;
  let status;
  try {
    const inj = spineInjection();
    chamber = assembleSealChamber(inj);
    status = verbStatus({ ...inj, roots: [] });
  } catch (e) {
    return { wave: 'TW5', ok: false, checks, error: String(e?.message ?? e) };
  }

  push('schema', chamber.schema === SEAL_CHAMBER_SCHEMA_ID);
  push(
    'goal_on_the_table_first',
    chamber.goal_bar?.first === true && chamber.goal_bar?.unknown === false,
  );
  push(
    'roadmap_rail_from_engine',
    chamber.roadmap_rail?.from_engine === true &&
      chamber.roadmap_rail?.panel_invented === false,
  );
  push('steward_speaks_first', chamber.conversation?.steward_first === true);
  push(
    'no_instrument_primary_face',
    chamber.negative?.instrument_card_sheet === false &&
      chamber.negative?.instrument_primary === false,
  );
  push('footer_stamp', chamber.footer_stamp === CHAMBER_FOOTER_STAMP);
  const parity = chamberAgreesWithStatus(chamber, status);
  push('cli_parity', parity.agrees === true);

  return { wave: 'TW5', ok: checks.every((c) => c.pass), checks };
}

/**
 * TW6 probe — assemble the shipped High Seat + Decision Packet from fixtures
 * and check the Screens 0+2+3 falsify quotes structurally (≤1 raised block,
 * ⚑ = queue length only ambient, no master table / meters, goal card always
 * first, exactly one question, zero further gathering).
 * @returns {{ wave: 'TW6', ok: boolean, checks: {check: string, pass: boolean}[], error?: string }}
 */
export function probeTw6HighSeat() {
  const checks = [];
  const push = (check, pass) => checks.push({ check, pass: pass === true });

  let hs;
  let view;
  try {
    hs = assembleHighSeat({ items: probeItems(), prefs: { ...PROBE_PREFS } });
    const inj = spineInjection();
    const packet = assembleBriefPacket({ ...inj, roots: [], altitude: 'project' });
    view = assemblePacketView(packet, { project_id: inj.project });
  } catch (e) {
    return { wave: 'TW6', ok: false, checks, error: String(e?.message ?? e) };
  }

  push('schema', hs.schema === HIGH_SEAT_SCHEMA_ID);
  push('at_most_one_raised_block', hs.raised_block_count <= MAX_RAISED_BLOCKS);
  push(
    'badge_is_only_ambient_signal',
    hs.ambient?.only_signal === 'badge' &&
      hs.ambient?.badge_count_equals_queue_length === true,
  );
  push(
    'no_master_table_no_meters',
    hs.negative?.master_data_table === false &&
      hs.negative?.percent_meter === false,
  );
  push('tiles_present', (hs.tiles?.tiles?.length ?? 0) === probeItems().length);
  push('balancing_card_present', hs.balancing != null);
  push(
    'packet_goal_card_first',
    view.goal_card_present === true && view.goal_card_first === true,
  );
  push('packet_exactly_one_question', view.question_count === 1);
  push(
    'packet_zero_further_gathering',
    view.further_gathering === false && view.padded_filler === false,
  );

  return { wave: 'TW6', ok: checks.every((c) => c.pass), checks };
}

/**
 * Spine green = TW5 probe AND TW6 probe pass. Evidence, never a config bit.
 * @param {{ probes?: { tw5?: () => object, tw6?: () => object } }} [opts]
 *   test injection only — production callers pass nothing.
 */
export function checkSpineGreen(opts = {}) {
  const tw5 =
    typeof opts.probes?.tw5 === 'function' ? opts.probes.tw5() : probeTw5SealChamber();
  const tw6 =
    typeof opts.probes?.tw6 === 'function' ? opts.probes.tw6() : probeTw6HighSeat();
  const green = tw5?.ok === true && tw6?.ok === true;
  return {
    schema: PE_GATE_SCHEMA_ID,
    spelling: SPELLING,
    spine: [...PE_SPINE_WAVES],
    green,
    tw5,
    tw6,
    evidence: 'structural probes over the shipped chambers — never a config bit',
  };
}

// ---------------------------------------------------------------------------
// The hard gate
// ---------------------------------------------------------------------------

/**
 * Evaluate the PE hard gate for one feature.
 * Open ⇔ spine green (TW5–TW6 probes) AND config enables the feature with a
 * literal true. Anything else is a structured refuse — no override receipt.
 * @param {string} feature one of PE_FEATURES
 * @param {{ config?: object, spine?: object, probes?: object }} [opts]
 *   `spine`/`probes` are test injection; production callers pass config only.
 */
export function evaluatePeGate(feature, opts = {}) {
  if (!PE_FEATURES.includes(feature)) {
    return {
      ok: false,
      error: 'unknown_pe_feature',
      spelling: SPELLING,
      feature: feature ?? null,
      pe_features: [...PE_FEATURES],
      message: `${SPELLING} gates exactly three progressive enhancements — '${String(
        feature,
      )}' is not one of them.`,
    };
  }

  const config = normalizePeConfig(opts.config ?? defaultPeConfig());
  const spine = opts.spine ?? checkSpineGreen(opts);
  const spine_green = spine?.green === true;
  const config_enabled = config.enable[feature] === true;

  const blockers = [];
  if (!spine_green) {
    blockers.push({
      blocker: 'spine_not_green',
      detail:
        'TW5–TW6 structural probes are not green — the spine ships before any charm.',
      tw5_ok: spine?.tw5?.ok === true,
      tw6_ok: spine?.tw6?.ok === true,
    });
  }
  if (!config_enabled) {
    blockers.push({
      blocker: 'not_explicitly_configured',
      detail: `PE config does not enable '${feature}' with a literal true (default is off; truthy strings do not count).`,
    });
  }

  const label = PE_FEATURE_LABELS[feature];
  if (blockers.length) {
    return {
      ok: false,
      error: 'pe_gate_refused',
      gate: 'closed',
      spelling: SPELLING,
      feature,
      label,
      spine_green,
      config_enabled,
      blockers,
      law: PE_GATE_LAW,
      spine,
      message: `Not yet — ${label} stays off. ${PE_GATE_LAW.message}`,
    };
  }

  return {
    ok: true,
    gate: 'open',
    spelling: SPELLING,
    feature,
    label,
    spine_green: true,
    config_enabled: true,
    law: PE_GATE_LAW,
    spine,
    message: `Gate open for ${label}: spine green (TW5–TW6 probes) + explicit config.`,
  };
}

/**
 * The attempt path — what a caller trying to turn a PE feature on gets.
 * Before the gate: refuse, with exactly what is missing and how it opens.
 * @param {string} feature
 * @param {object} [opts] same as evaluatePeGate
 */
export function requestProgressiveEnhancement(feature, opts = {}) {
  const verdict = evaluatePeGate(feature, opts);
  if (!verdict.ok) {
    return {
      ...verdict,
      attempted: feature ?? null,
      refused: true,
      how_to_open: [
        'Bring the spine green: TW5 Seal chamber + TW6 High Seat / Decision Packet probes must pass (checkSpineGreen).',
        `Enable the feature explicitly: PE config { enable: { ${
          PE_FEATURES.includes(feature) ? feature : '<feature>'
        }: true } } — literal true only.`,
      ],
    };
  }
  return { ...verdict, attempted: feature, refused: false };
}

// ---------------------------------------------------------------------------
// E7 — recorded on the Roadmap, NOT built
// ---------------------------------------------------------------------------

export const E7_STUBS_SCHEMA_ID = 'ecgberht-e7-stubs-v0';

/** Every E7 stub step carries exactly this status. */
export const E7_STEP_STATUS = 'parked';

/** The E7 not-built contract, exported for docs and refusals. */
export const E7_NOT_BUILT = Object.freeze({
  built: false,
  connector_present: false,
  oauth_code: false,
  recorded_as: 'roadmap_parked_steps',
  why: 'Scope / OAuth trap (frozen plan, Oranges foresight) — E7 is recorded on the Roadmap, never built, in this run.',
});

/**
 * The E7 stub steps from the template, normalized: status is FORCED parked
 * regardless of what a hand-edited template says.
 * @returns {{ step_id: string, name: string, status: 'parked', done_when: string|null, waiting_on: string|null }[]}
 */
export function e7StubSteps() {
  const template = loadE7StubTemplate();
  const steps = Array.isArray(template?.steps) ? template.steps : [];
  return steps.map((s) => ({
    step_id: s.step_id,
    name: s.name,
    status: E7_STEP_STATUS,
    done_when: s.done_when ?? null,
    waiting_on: s.waiting_on ?? null,
  }));
}

/**
 * Record the E7 future steps on a Roadmap as PARKED step_create events —
 * through the TW1 single writer only (no dual write, projection derived).
 * Steps already present are skipped (idempotent re-record).
 * @param {object|string|null} roadmapInput existing roadmap (or null → empty)
 * @param {{ project_id?: string|null, as_of?: string }} [opts]
 */
export function appendE7StubSteps(roadmapInput, opts = {}) {
  let current = roadmapInput ?? emptyRoadmap(opts.project_id ?? null);
  const appended = [];
  const skipped_existing = [];

  // Wave 6 live-writer migration (pe-gate.mjs:443): when project_path is set,
  // each step_create lands through the locked spine; otherwise pure law only.
  for (const step of e7StubSteps()) {
    const event = {
      kind: 'step_create',
      step_id: step.step_id,
      name: step.name,
      status: E7_STEP_STATUS,
      done_when: step.done_when,
      waiting_on: step.waiting_on,
      at: opts.as_of ?? undefined,
    };
    const res = opts.project_path
      ? appendRoadmapEventThroughSpine(opts.project_path, event, {
          seed: current,
          at: opts.as_of,
          project_id: opts.project_id,
          home: opts.home,
          skip_index: !opts.project_id,
        })
      : appendRoadmapEvent(current, event);
    if (!res.ok) {
      if (res.error === 'duplicate_step_id') {
        skipped_existing.push(step.step_id);
        continue;
      }
      return { ...res, failed_step_id: step.step_id };
    }
    current = res.roadmap;
    appended.push(res.event);
  }

  return {
    ok: true,
    spelling: SPELLING,
    schema: E7_STUBS_SCHEMA_ID,
    roadmap: typeof current === 'string' ? JSON.parse(current) : current,
    appended,
    skipped_existing,
    parked_step_ids: e7StubSteps().map((s) => s.step_id),
    status: E7_STEP_STATUS,
    not_built: E7_NOT_BUILT,
    events_only: true,
    single_writer: ROADMAP_SINGLE_WRITER,
    spine: Boolean(opts.project_path),
    message:
      'E7 recorded as parked Roadmap steps via the single writer — future steps only, nothing built, no OAuth code.',
  };
}

/**
 * Any attempt to use E7 as an implemented connector refuses — there is no
 * connector in this build, only parked Roadmap steps.
 * @param {string|null} [action] what the caller tried (e.g. 'sync-calendar')
 */
export function refuseE7Connector(action = null) {
  return {
    ok: false,
    error: 'e7_not_built',
    spelling: SPELLING,
    action: action ?? null,
    connector: 'calendar_email',
    built: false,
    roadmap_status: E7_STEP_STATUS,
    not_built: E7_NOT_BUILT,
    message:
      'E7 calendar/email exists only as parked future steps on the Roadmap — no connector and no OAuth code ship in this build. A future John-approved wave (behind the calendar_email PE gate) builds it.',
  };
}

// ---------------------------------------------------------------------------
// E7 not-built canary — an implemented connector in engine sources is RED
// ---------------------------------------------------------------------------

/**
 * Markers of an IMPLEMENTED calendar/email connector. A marker alone is not
 * a hit — it must co-occur on a line with an import/require or a network
 * call (that is what separates recording E7 from building it).
 */
export const E7_CONNECTOR_MARKERS = Object.freeze([
  'googleapis',
  'google-auth-library',
  'oauth2',
  'client_secret',
  'refresh_token',
  'msal',
  '@azure/identity',
  'graph.microsoft.com',
  'www.googleapis.com',
  'calendar/v3',
  'gmail/v1',
  'nodemailer',
  'imapflow',
  'node-imap',
  'smtp://',
  'imap://',
]);

const IMPORT_OR_REQUIRE =
  /\b(?:import\s[^;]*from\s*['"]|require\s*\(\s*['"]|import\s*\(\s*['"])/;

const NETWORK_CALL =
  /\b(?:fetch|axios|got)\s*\(|\bhttps?\.(?:request|get)\s*\(/;

/**
 * TW8 canary: E7 must not be present as an implemented connector.
 * 1. No engine source line pairs a connector marker with an import/require
 *    or a network call.
 * 2. Every E7 stub step is parked (recorded, not active work).
 * Runs in CI via the test suite; a red here fails the build.
 * @param {{ engineDir?: string, texts?: {file: string, text: string}[], stubs?: object[] }} [opts]
 */
export function runE7NotBuiltCanary(opts = {}) {
  const hits = [];
  const scanned = [];

  let sources;
  if (Array.isArray(opts.texts)) {
    sources = opts.texts;
  } else {
    const dir = path.resolve(opts.engineDir || path.join(skillRoot(), 'engine'));
    sources = listJsFiles(dir).map((file) => {
      let text = '';
      try {
        text = fs.readFileSync(file, 'utf8');
      } catch {
        /* unreadable file scans as empty */
      }
      return { file: path.basename(file), text };
    });
  }

  for (const { file, text } of sources) {
    scanned.push(file);
    const lines = String(text ?? '').split(/\r?\n/);
    lines.forEach((line, idx) => {
      // Strip trailing // comments — but not the // inside a URL scheme
      // (https://…), or a fetch against a calendar host would scan clean.
      const code = line.trim().replace(/(^|[^:])\/\/.*$/, '$1').trim();
      if (!code || code.startsWith('*') || code.startsWith('/*')) return;
      // Skip this canary's own definitions/aggregations
      if (/E7_CONNECTOR_MARKERS|runE7NotBuiltCanary/.test(code)) return;
      const marker = E7_CONNECTOR_MARKERS.find((m) => code.includes(m));
      if (!marker) return;
      if (IMPORT_OR_REQUIRE.test(code) || NETWORK_CALL.test(code)) {
        hits.push({ file, line: idx + 1, marker, text: code.slice(0, 120) });
      }
    });
  }

  const stubs = Array.isArray(opts.stubs) ? opts.stubs : e7StubSteps();
  const not_parked = stubs
    .filter((s) => s?.status !== E7_STEP_STATUS)
    .map((s) => s?.step_id ?? null);
  const stubs_parked_ok = stubs.length > 0 && not_parked.length === 0;

  const ok = hits.length === 0 && stubs_parked_ok;
  return {
    ok,
    connector_hits: hits,
    stubs_parked_ok,
    not_parked,
    stub_count: stubs.length,
    scanned,
    not_built: E7_NOT_BUILT,
    message: ok
      ? 'E7 not built: no connector imports/network calls in engine sources; every stub step parked'
      : 'E7 not-built canary failed',
  };
}

function listJsFiles(dir) {
  const out = [];
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === 'node_modules' || ent.name === '.git') continue;
      out.push(...listJsFiles(p));
    } else if (
      ent.isFile() &&
      (ent.name.endsWith('.mjs') || ent.name.endsWith('.js'))
    ) {
      out.push(p);
    }
  }
  return out;
}
