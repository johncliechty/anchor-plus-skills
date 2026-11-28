/**
 * Shared subscription-CLI policy for Trio and Foundry seats.
 *
 * Persist intent (latest supported / highest supported), never a release name.
 * Capability discovery and the resulting selection are separate from a served-
 * model attestation: only a provider's actual turn receipt can supply the latter.
 * No Anchor imports, private project paths, API clients, or permission overrides.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync as nodeSpawnSync } from 'node:child_process';
import { reconcileCodexCatalog } from './codex-catalog.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';

const EXTRA_CLAUDE_VERIFICATION_ROLES = new Set(['verifier', 'adversarial']);
const DATED_CLAUDE_FABLE_RE = /^claude-fable-5-2(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$/;
const DATED_CLAUDE_OPUS_55_RE = /^claude-opus-5-5(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$/;
const DATED_CLAUDE_SONNET_RE = /^claude-sonnet-\d+(?:-\d+)*(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$/;
const CLAUDE_MOVING_ALIAS_SET = new Set(['best', 'opus', 'sonnet', 'haiku']);
const CLAUDE_DUPLICATE_ALIAS_SET = new Set(['best', 'opus']);
const SMALL_OR_WRAPPER_TOKENS = ['flash', 'lite', 'nano', 'mini', 'haiku', 'spark', 'orchestrator'];

export const STRENGTH_TIERS = Object.freeze(['standard', 'heavy', 'light']);
export const TOP_EFFORT_CHOICES = Object.freeze(['highest', 'ultra', 'max', 'xhigh', 'high']);
export const DEFAULT_HEAVY_SPEC = Object.freeze({ model_steps_below: 0, effort_steps_below: 0 });
export const DEFAULT_LIGHT_SPEC = Object.freeze({ model_steps_below: 1, effort_steps_below: 2 });
export const HEAVY_DEFAULT_SKILLS = Object.freeze(new Set(['anvil', 'chekhov', 'aegis', 'superjump']));
export const VARIABLE_STRENGTH_POLICY = Object.freeze({
  mode: 'variable_strength',
  default_strength: 'standard',
});

const SKILL_ALIASES = Object.freeze({
  anvil: 'anvil',
  chekhov: 'chekhov',
  checkov: 'chekhov',
  aegis: 'aegis',
  agies: 'aegis',
  sentinel: 'aegis',
  superjump: 'superjump',
  'super-jump': 'superjump',
  gandalf: 'gandalf',
  researchprime: 'researchprime',
  'research-prime': 'researchprime',
  crucible: 'crucible',
  foreman: 'foreman',
  jumper: 'jumper',
  ramanujan: 'ramanujan',
  scribe: 'scribe',
  einstein: 'einstein',
  'legal-beagle': 'legal-beagle',
  legalbeagle: 'legal-beagle',
  'financial-analyst': 'financial-analyst',
  financialanalyst: 'financial-analyst',
  'doctor-seuss': 'doctor-seuss',
  'literature-review': 'literature-review',
  'figure-designer': 'figure-designer',
  figuredesigner: 'figure-designer',
  'tidy-idy': 'tidy-idy',
  tidyidy: 'tidy-idy',
  'zombie-hunter': 'zombie-hunter',
  zombiehunter: 'zombie-hunter',
  'agy-dispatch': 'agy-dispatch',
  agydispatch: 'agy-dispatch',
});

const LEADING_SKILL_QUALIFIER_RE = /^\s*(?:(?:please\s+)?(?:run|use|launch|start|invoke)\s+|\/)?(?<skill>super\s+jump|super-jump|superjump|research\s*prime|research-prime|legal[-\s]+beagle|financial[-\s]+analyst|doctor[-\s]+seuss|literature[-\s]+review|figure[-\s]+designer|tidy[-\s]+idy|zombie[-\s]+hunter|agy[-\s]+dispatch|anvil|chekhov|checkov|aegis|agies|sentinel|gandalf|crucible|foreman|jumper|ramanujan|scribe|einstein)(?:\s+(?<strength>heavy|light|standard|regular))?(?=$|[\s:.,;\-—/!?])/i;

export function normalizeStrength(value, fallback = 'standard') {
  if (typeof value !== 'string') return fallback;
  const tok = value.trim().toLowerCase();
  if (tok === 'regular') return 'standard';
  if (STRENGTH_TIERS.includes(tok)) return tok;
  return fallback;
}

export function canonicalSkillName(skill) {
  if (typeof skill !== 'string' || !skill.trim()) return null;
  const cleaned = skill.trim().toLowerCase().replace(/[\s_]+/g, '-').replace(/^\/+|\/+$/g, '');
  return SKILL_ALIASES[cleaned] ?? SKILL_ALIASES[cleaned.replace(/-/g, '')] ?? null;
}

export function parseLeadingSkillQualifier(text) {
  if (typeof text !== 'string' || !text.trim()) return { skill: null, strength: null };
  const m = LEADING_SKILL_QUALIFIER_RE.exec(text);
  if (!m?.groups) return { skill: null, strength: null };
  return {
    skill: canonicalSkillName(m.groups.skill),
    strength: normalizeStrength(m.groups.strength, null),
  };
}

function normalizeStepSpec(raw, fallback) {
  if (!object(raw)) fail(null, 'Strength tier spec must be an object.', 'settings_invalid');
  const allowed = new Set(['model_steps_below', 'effort_steps_below']);
  if (Object.keys(raw).some(k => !Object.hasOwn(raw, k) || !allowed.has(k))) {
    fail(null, 'Strength tier spec contains unsupported keys.', 'settings_invalid');
  }
  const mSteps = raw.model_steps_below === undefined ? fallback.model_steps_below : raw.model_steps_below;
  const eSteps = raw.effort_steps_below === undefined ? fallback.effort_steps_below : raw.effort_steps_below;
  if (!Number.isSafeInteger(mSteps) || mSteps < 0 || mSteps > 3) {
    fail(null, 'model_steps_below must be an integer between 0 and 3.', 'settings_invalid');
  }
  if (!Number.isSafeInteger(eSteps) || eSteps < 0 || eSteps > 3) {
    fail(null, 'effort_steps_below must be an integer between 0 and 3.', 'settings_invalid');
  }
  return { model_steps_below: mSteps, effort_steps_below: eSteps };
}

function normalizeHeavySkills(raw) {
  if (!Array.isArray(raw)) fail(null, 'heavy_skills must be an array of skill names.', 'settings_invalid');
  const out = [];
  for (const item of raw) {
    if (typeof item !== 'string') fail(null, 'heavy_skills entries must be strings.', 'settings_invalid');
    const canon = canonicalSkillName(item);
    if (!canon) fail(null, `Unknown skill in heavy_skills: ${item}`, 'settings_invalid');
    if (!out.includes(canon)) out.push(canon);
  }
  return out;
}

export function effectiveVariableStrengthConfig(policyOrSettings = null) {
  const polRaw = object(policyOrSettings)
    ? (Object.hasOwn(policyOrSettings, 'model_policy') ? policyOrSettings.model_policy : policyOrSettings)
    : null;
  const pol = object(polRaw) && polRaw.mode === 'variable_strength' ? polRaw : {};
  const defStr = normalizeStrength(pol.default_strength, 'standard');
  const topRaw = typeof pol.top_effort === 'string' ? pol.top_effort.trim().toLowerCase() : 'highest';
  const topEff = TOP_EFFORT_CHOICES.includes(topRaw) ? topRaw : 'highest';
  let heavySpec = { ...DEFAULT_HEAVY_SPEC };
  if (object(pol.heavy)) {
    try { heavySpec = normalizeStepSpec(pol.heavy, DEFAULT_HEAVY_SPEC); } catch { heavySpec = { ...DEFAULT_HEAVY_SPEC }; }
  }
  let lightSpec = { ...DEFAULT_LIGHT_SPEC };
  if (object(pol.light)) {
    try { lightSpec = normalizeStepSpec(pol.light, DEFAULT_LIGHT_SPEC); } catch { lightSpec = { ...DEFAULT_LIGHT_SPEC }; }
  }
  let heavySkills = [...HEAVY_DEFAULT_SKILLS];
  if (Array.isArray(pol.heavy_skills)) {
    try { heavySkills = normalizeHeavySkills(pol.heavy_skills); } catch { heavySkills = [...HEAVY_DEFAULT_SKILLS]; }
  }
  return {
    mode: 'variable_strength',
    default_strength: defStr,
    top_effort: topEff,
    heavy: heavySpec,
    light: lightSpec,
    heavy_skills: heavySkills,
  };
}

function configuredHeavySkillsSet({ settings = null, heavySkills = null, env = null } = {}) {
  if (Array.isArray(heavySkills)) {
    try { return new Set(normalizeHeavySkills(heavySkills)); } catch { return HEAVY_DEFAULT_SKILLS; }
  }
  if (object(settings) && Array.isArray(settings.model_policy?.heavy_skills)) {
    try { return new Set(normalizeHeavySkills(settings.model_policy.heavy_skills)); } catch { /* fall through */ }
  }
  if (env && (env.ANCHOR_SETTINGS_DIR || env.ANCHOR_DATA_DIR)) {
    try {
      const prefs = loadPolicyPrefs(env);
      if (Array.isArray(prefs?.model_policy?.heavy_skills)) {
        return new Set(normalizeHeavySkills(prefs.model_policy.heavy_skills));
      }
    } catch { /* fall through */ }
  }
  return HEAVY_DEFAULT_SKILLS;
}

export function resolveSkillStrength({
  skill = null,
  explicitStrength = null,
  inheritedStrength = null,
  cockpitStrength = null,
  defaultStrength = 'standard',
  settings = null,
  heavySkills = null,
  env = null,
} = {}) {
  const exp = normalizeStrength(explicitStrength, null);
  if (exp !== null) return exp;
  const inh = normalizeStrength(inheritedStrength, null);
  if (inh !== null) return inh;
  const ckp = normalizeStrength(cockpitStrength, null);
  if (ckp === 'heavy' || ckp === 'light') return ckp;
  const canon = canonicalSkillName(skill);
  const heavySet = configuredHeavySkillsSet({ settings, heavySkills, env });
  if (canon && heavySet.has(canon)) return 'heavy';
  return normalizeStrength(defaultStrength, 'standard');
}

export function isVariableStrengthActive({ settings = null, env = process.env, tier = null, skill = null } = {}) {
  const mode = settings?.model_policy?.mode;
  if (mode === 'variable_strength') return true;
  if (normalizeStrength(tier, null) === 'light') return true;
  if (normalizeStrength(env?.ANCHOR_STRENGTH, null) !== null) return true;
  if (normalizeStrength(env?.TRIO_TIER, null) === 'light') return true;
  if (env?.ANCHOR_VARIABLE_STRENGTH === '1') return true;
  if (canonicalSkillName(skill || env?.ANCHOR_SKILL) && mode !== 'latest_supported') return true;
  return false;
}

export function isClaudeVerificationSeat({ role, label } = {}) {
  if (isVerificationRole({ role, label })) return true;
  const r = normalizeRole({ role, label });
  return Boolean(r && EXTRA_CLAUDE_VERIFICATION_ROLES.has(r));
}

export function normalizeClaudeFableModel(modelIdValue) {
  if (typeof modelIdValue !== 'string') return modelIdValue;
  const trimmed = modelIdValue.trim();
  if (DATED_CLAUDE_FABLE_RE.test(trimmed)) return 'claude-fable-5-2';
  if (DATED_CLAUDE_OPUS_55_RE.test(trimmed)) return 'claude-opus-5-5';
  return trimmed;
}

export const DEFAULT_POLICY = Object.freeze({
  mode: 'latest_supported',
  effort: 'highest_supported',
});
export const POLICY_VERSION = 1;
export const CLAUDE_CATALOG_MODELS = Object.freeze([
  'claude-fable-5-2',
  'claude-opus-5-5',
  'best',
  'opus',
  'sonnet',
  'haiku',
]);
const FAMILIES = new Set(['claude', 'chatgpt', 'grok', 'gemini']);
const EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/;
const TTL_MS = 300_000;
const MAX_BYTES = 8 * 1024 * 1024;
const GROK_ORIGIN = 'https://cli-chat-proxy.grok.com/v1/models';
const cache = new Map();
let discovererIds = new WeakMap();
let nextDiscovererId = 1;

export class PolicyUnavailable extends Error {
  constructor(family, reason, code = 'model_policy_unavailable') {
    super(`${family || 'settings'}: ${reason}`);
    this.name = 'PolicyUnavailable';
    this.family = family || null;
    this.code = code;
    // Discovery/settings failed before a provider action was submitted. This is
    // an internal prelaunch receipt for the configured-family failover ladder,
    // not a claim that any requested model served a turn.
    this.seat_unavailable = true;
    this.seat_status = code;
    this.raw_receipt = {
      ok: false, status: code, error: this.message, replay_safe: true,
      model_served: null, model_attested: false, family_attested: false,
    };
  }
}

function fail(family, reason, code) {
  throw new PolicyUnavailable(family, reason, code);
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function familyName(family) {
  if (!FAMILIES.has(family)) fail(family, 'Unsupported provider family.');
  return family;
}

export function validatePolicy(policy = DEFAULT_POLICY) {
  if (!object(policy)) {
    fail(null, 'The model policy must request latest_supported and highest_supported or variable_strength.', 'settings_invalid');
  }
  if (policy.mode === 'variable_strength') {
    const allowed = new Set(['mode', 'default_strength', 'top_effort', 'heavy', 'light', 'heavy_skills']);
    if (Object.keys(policy).some(key => !Object.hasOwn(policy, key) || !allowed.has(key))) {
      fail(null, 'The variable_strength model policy contains unsupported keys.', 'settings_invalid');
    }
    const rawDef = policy.default_strength === undefined ? 'standard' : policy.default_strength;
    const normDef = normalizeStrength(rawDef, null);
    if (typeof rawDef !== 'string' || normDef === null) {
      fail(null, 'The variable_strength default_strength must be standard, heavy, or light.', 'settings_invalid');
    }
    const out = { mode: 'variable_strength', default_strength: normDef };
    if (policy.top_effort !== undefined) {
      const te = typeof policy.top_effort === 'string' ? policy.top_effort.trim().toLowerCase() : '';
      if (!TOP_EFFORT_CHOICES.includes(te)) {
        fail(null, 'The variable_strength top_effort must be highest, ultra, max, xhigh, or high.', 'settings_invalid');
      }
      out.top_effort = te;
    }
    if (policy.heavy !== undefined) out.heavy = normalizeStepSpec(policy.heavy, DEFAULT_HEAVY_SPEC);
    if (policy.light !== undefined) out.light = normalizeStepSpec(policy.light, DEFAULT_LIGHT_SPEC);
    if (policy.heavy_skills !== undefined) out.heavy_skills = normalizeHeavySkills(policy.heavy_skills);
    return out;
  }
  if (Object.keys(policy).some(key => !Object.hasOwn(DEFAULT_POLICY, key))
      || policy.mode !== DEFAULT_POLICY.mode || policy.effort !== DEFAULT_POLICY.effort) {
    fail(null, 'The model policy must request latest_supported and highest_supported.', 'settings_invalid');
  }
  return { ...DEFAULT_POLICY };
}

function extractQualityPreferences(raw) {
  if (!object(raw)) return null;
  const quality = object(raw.provider_preferences) && object(raw.provider_preferences.quality)
    ? raw.provider_preferences.quality
    : {};
  const out = {};
  for (const family of FAMILIES) {
    const item = quality[family];
    if (typeof item === 'string' && MODEL_ID.test(item.trim())) {
      out[family] = { model: item.trim(), effort: 'highest_supported' };
    } else if (object(item) && typeof item.model === 'string' && MODEL_ID.test(item.model.trim())) {
      const eff = typeof item.effort === 'string' ? item.effort.trim().toLowerCase() : 'highest_supported';
      out[family] = {
        model: item.model.trim(),
        effort: (eff === 'highest_supported' || EFFORTS.includes(eff)) ? eff : 'highest_supported',
      };
    } else if (typeof raw[`${family}_model`] === 'string' && MODEL_ID.test(raw[`${family}_model`].trim())) {
      out[family] = { model: raw[`${family}_model`].trim(), effort: 'highest_supported' };
    }
  }
  return Object.keys(out).length > 0 ? { quality: out } : null;
}

function validatePrefs(raw, source) {
  if (!object(raw) || raw.settings_error) fail(null, 'Model preferences are invalid.', 'settings_invalid');
  if (raw.orchestrator_family && !raw.coding_family) raw = { ...raw, coding_family: raw.orchestrator_family };
  if (raw.orchestrator_family && !raw.default_cli) raw = { ...raw, default_cli: raw.orchestrator_family };
  if (raw.reviewer_family && !raw.review_family) raw = { ...raw, review_family: raw.reviewer_family };
  for (const key of ['coding_family', 'review_family', 'default_cli']) {
    if (!FAMILIES.has(raw[key])) fail(null, `Missing or invalid ${key}.`, 'settings_invalid');
  }
  const revision = raw.settings_revision === undefined ? 0 : raw.settings_revision;
  if (!Number.isSafeInteger(revision) || revision < 0) {
    fail(null, 'settings_revision must be a nonnegative safe integer.', 'settings_invalid');
  }
  const providerPreferences = extractQualityPreferences(raw);
  return {
    coding_family: raw.coding_family,
    review_family: raw.review_family,
    default_cli: raw.default_cli,
    model_policy: validatePolicy(raw.model_policy === undefined ? DEFAULT_POLICY : raw.model_policy),
    settings_revision: revision,
    source: source || raw.source || 'provided-settings',
    ...(providerPreferences ? { provider_preferences: providerPreferences } : {}),
  };
}

function profileDirectory(env) {
  if (env && env !== process.env && !env.USERPROFILE && !env.HOME) return '';
  return env?.USERPROFILE || env?.HOME || os.homedir();
}

function readJson(filename, family, errorCode = 'model_policy_unavailable') {
  try {
    const stat = fs.statSync(filename);
    if (!stat.isFile() || stat.size > MAX_BYTES) fail(family, 'The metadata file is not a bounded regular file.', errorCode);
    return JSON.parse(fs.readFileSync(filename, 'utf8'));
  } catch (error) {
    if (error instanceof PolicyUnavailable) throw error;
    // Do not expose file contents, provider stderr, credentials, or JSON excerpts.
    fail(family, 'Cannot read valid provider metadata or preferences.', errorCode);
  }
}

function present(filename) {
  try {
    fs.statSync(filename);
    return true;
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    fail(null, 'Cannot inspect the authoritative preference file.', 'settings_invalid');
  }
}

/**
 * An existing primary is authority, even if corrupt. Only an absent primary
 * allows the mirror to serve as authority. primary_path metadata is ignored.
 * A standalone Trio install with neither file retains historical Claude seats;
 * Anchor itself has a stricter first-run setup gate before launching a seat.
 */
export function loadPolicyPrefs(env = process.env) {
  const profile = profileDirectory(env);
  const mirror = profile ? path.join(profile, '.anchor', 'model_prefs.json') : null;
  const settingsRoot = env.ANCHOR_SETTINGS_DIR || env.ANCHOR_DATA_DIR;
  const primary = settingsRoot ? path.join(settingsRoot, 'settings.json') : null;
  if (primary && present(primary)) return validatePrefs(readJson(primary, null, 'settings_invalid'), 'primary');
  if (mirror && present(mirror)) return validatePrefs(readJson(mirror, null, 'settings_invalid'), 'mirror');
  return validatePrefs({
    coding_family: 'claude', review_family: 'claude', default_cli: 'claude',
    model_policy: DEFAULT_POLICY, settings_revision: 0,
  }, 'historical-default');
}

function modelId(value, family) {
  if (typeof value !== 'string' || MODEL_ID.exec(value)?.[0] !== value) fail(family, 'The catalog contains an invalid model identifier.');
  return value;
}

function effortValues(values, family) {
  if (!Array.isArray(values) || !values.length) fail(family, 'The provider did not advertise supported reasoning efforts.');
  return [...new Set(values.map(value => {
    const effort = typeof value === 'string' ? value
      : value?.effort ?? value?.reasoningEffort ?? value?.value ?? value?.id;
    if (typeof effort !== 'string' || !EFFORTS.includes(effort)) {
      fail(family, 'The provider advertised an unknown reasoning effort; capability support must be updated.');
    }
    return effort;
  }))];
}

const AGY_EFFORT_SUFFIX = /^(gemini-[A-Za-z0-9.-]+?)-(minimal|low|medium|high|xhigh|max)$/;

/** `agy models` text -> [{ model: base, efforts }] in the CLI's order (the effort is the id suffix). */
export function parseAgyModels(text) {
  const order = [];
  const efforts = new Map();
  for (const line of String(text ?? '').split(/\r?\n/)) {
    const id = line.split('\t')[0].trim();
    if (!id.startsWith('gemini-')) continue;
    const m = AGY_EFFORT_SUFFIX.exec(id);
    const base = m ? m[1] : id;
    if (!efforts.has(base)) { order.push(base); efforts.set(base, []); }
    if (m && !efforts.get(base).includes(m[2])) efforts.get(base).push(m[2]);
  }
  return order.map(model => ({ model, efforts: efforts.get(model).length ? efforts.get(model) : ['medium'] }));
}

/** The id agy accepts for a Gemini base model at an effort. */
export function agyModelId(model, effort) {
  return effort && !AGY_EFFORT_SUFFIX.test(model) ? `${model}-${effort}` : model;
}

export function highestEffort(values, family = null) {
  const supported = effortValues(values, family);
  return EFFORTS.filter(value => supported.includes(value)).at(-1);
}

function upgradeId(value, family) {
  if (value === undefined || value === null || value === '') return undefined;
  return modelId(typeof value === 'string' ? value : value?.model ?? value?.id, family);
}

function hidden(entry) {
  return entry.hidden === true || entry.isHidden === true || entry.selectable === false
    || entry.visibility === 'hide' || entry.visibility === 'hidden' || entry.visibility === 'none';
}

function claudeEfforts(raw) {
  if (Array.isArray(raw?.efforts)) return effortValues(raw.efforts, 'claude');
  if (Array.isArray(raw?.supportedEfforts)) return effortValues(raw.supportedEfforts, 'claude');
  const help = typeof raw === 'string' ? raw : raw?.help;
  if (typeof help !== 'string') fail('claude', 'Claude effort capability help is unavailable.');
  const lines = help.split(/\r?\n/);
  const at = lines.findIndex(line => /--effort\b/.test(line));
  if (at < 0) fail('claude', 'The installed Claude CLI does not advertise effort selection.');
  let declaration = lines[at];
  for (let index = at + 1; index < Math.min(at + 4, lines.length); index++) {
    if (/^\s+-/.test(lines[index])) break;
    declaration += ` ${lines[index]}`;
  }
  const choices = declaration.match(/\((?:choices:\s*)?([a-zA-Z"'\s,|/-]+)\)/);
  if (!choices) fail('claude', 'Claude did not expose a parseable effort capability list.');
  return effortValues(choices[1].split(/[\s,|/]+/).map(value => value.replace(/["']/g, '')).filter(Boolean), 'claude');
}

function normalizedRows(family, entries) {
  if (!Array.isArray(entries) || !entries.length) fail(family, 'The provider catalog contains no selectable models.');
  const seen = new Set();
  return entries.map((entry, index) => {
    if (!object(entry)) fail(family, 'The model catalog contains an invalid entry.');
    const model = modelId(entry.model, family);
    if (seen.has(model)) fail(family, 'The model catalog contains duplicate identifiers.');
    seen.add(model);
    const rank = entry.rank ?? index;
    if (!Number.isFinite(rank)) fail(family, 'The provider model rank is invalid.');
    const result = { model, efforts: effortValues(entry.efforts, family), rank };
    const upgrade = upgradeId(entry.upgrade, family);
    if (upgrade) result.upgrade = upgrade;
    return result;
  });
}

/** Retains capability fields only, never prompts, API keys, headers or config. */
export function normalizeCatalog(family, raw) {
  familyName(family);
  if (family === 'gemini' && raw?.schema_version !== 1) {
    // agy 1.3.x (2026-10-07): `agy models` lists "<id> TAB <name>" rows newest first; only gemini-* rows are the
    // Gemini family, and the effort is the id's suffix (gemini-3.8-flash-high).
    if (typeof raw !== 'string') fail(family, 'The agy model catalog is unavailable.', 'capability_probe_failed');
    return { schema_version: 1, family, models: normalizedRows(family, parseAgyModels(raw)),
      selection_evidence: 'provider_catalog_order' };
  }
  let entries;
  let evidence;
  let warning;
  if (raw?.schema_version === 1) {
    if (raw.family !== family) fail(family, 'Capability catalog family mismatch.');
    entries = normalizedRows(family, raw.models);
    evidence = family === 'claude' ? 'provider_moving_alias'
      : family === 'grok' ? 'provider_catalog_order'
        : raw.selection_evidence === 'installed_cli_priority+native_capabilities' ? raw.selection_evidence
          : raw.selection_evidence === 'provider_catalog_order' ? 'provider_catalog_order' : 'provider_priority';
  } else if (family === 'chatgpt') {
    const models = Array.isArray(raw?.models) ? raw.models : raw?.data;
    if (!Array.isArray(models)) fail(family, 'Codex did not return a model catalog.');
    const visible = models.filter(entry => object(entry) && !hidden(entry));
    evidence = raw._codex_catalog_evidence ? 'installed_cli_priority+native_capabilities'
      : visible.every(entry => Number.isFinite(entry.priority)) ? 'provider_priority' : 'provider_catalog_order';
    entries = normalizedRows(family, visible.map((entry, index) => ({
      model: entry.slug ?? entry.model ?? entry.id,
      efforts: entry.supported_reasoning_levels ?? entry.supportedReasoningEfforts,
      rank: evidence !== 'provider_catalog_order' ? entry.priority : index,
      upgrade: entry.upgrade,
    })));
  } else if (family === 'grok') {
    const models = raw?.models ?? raw?.data;
    if (!object(models) && !Array.isArray(models)) fail(family, 'Grok did not return a model catalog.');
    const items = Object.entries(models).map(([key, value]) => ({ key, info: value?.info ?? value }));
    entries = normalizedRows(family, items.filter(item => object(item.info) && !hidden(item.info)).map((item, index) => ({
      model: item.info.model ?? item.info.id ?? item.key,
      efforts: item.info.reasoning_efforts ?? item.info.supportedReasoningEfforts,
      rank: index,
    })));
    evidence = 'provider_catalog_order';
  } else {
    const efforts = claudeEfforts(raw);
    const explicitModels = Array.isArray(raw?.models) && raw.models.length > 0
      ? raw.models.map((item, index) => (typeof item === 'string'
        ? { model: item, efforts, rank: index }
        : {
          model: item.model ?? item.slug ?? item.id,
          efforts: item.efforts ?? efforts,
          rank: item.rank ?? index,
          upgrade: item.upgrade,
        }))
      : ((raw?.include_frontier === true || raw?.canonical === true)
        ? CLAUDE_CATALOG_MODELS
        : ['best', 'opus', 'sonnet', 'haiku']).map((alias, index) => ({
        model: alias,
        efforts,
        rank: index,
      }));
    entries = normalizedRows(family, explicitModels);
    evidence = 'provider_moving_alias';
  }
  if (family === 'grok') {
    warning = 'Provider catalog order is used; the provider does not attest an explicit latest/frontier rank.';
  } else if (family === 'chatgpt' && evidence === 'provider_catalog_order') {
    warning = 'Provider priority is unavailable; selection follows advertised catalog order.';
  }
  return {
    schema_version: 1, family, models: entries, selection_evidence: evidence,
    ...(warning ? { warning } : {}),
  };
}

export function selectModel(family, catalog) {
  const normalized = normalizeCatalog(family, catalog);
  const ranked = [...normalized.models].sort((left, right) => left.rank - right.rank);
  if (family === 'chatgpt' && ranked.length > 1 && ranked[0].rank === ranked[1].rank) {
    fail(family, 'Latest model ranking is ambiguous; refresh subscription capabilities.');
  }
  const byId = new Map(ranked.map(entry => [entry.model, entry]));
  const visited = new Set();
  let selected = ranked[0];
  let upgraded = false;
  while (selected.upgrade) {
    if (visited.has(selected.model)) fail(family, 'The model upgrade links contain a cycle.');
    visited.add(selected.model);
    const successor = byId.get(selected.upgrade);
    if (!successor) fail(family, 'The advertised model upgrade target is absent or unavailable.');
    selected = successor;
    upgraded = true;
  }
  return {
    family, model: selected.model, effort: highestEffort(selected.efforts, family),
    selection_evidence: upgraded ? `${normalized.selection_evidence}+provider_upgrade` : normalized.selection_evidence,
    model_attested: false,
    ...(normalized.warning ? { warning: normalized.warning } : {}),
  };
}

const SMALL_OR_WRAPPER_TOKEN_SET = new Set(SMALL_OR_WRAPPER_TOKENS);

function isSmallOrWrapperModel(modelId) {
  const segs = String(modelId || '').toLowerCase().split(/[-_./:\s]+/);
  return segs.some(seg => SMALL_OR_WRAPPER_TOKEN_SET.has(seg));
}

function geminiGeneralistSortKey(entry, origIndex) {
  const name = String(entry.model || '').toLowerCase();
  const segs = name.split(/[-_./:\s]+/);
  const isSmall = segs.some(s => s === 'flash' || s === 'lite' || s === 'nano') ? 1 : 0;
  const isInternal = segs.includes('orchestrator') ? 1 : 0;
  const m = /^gemini-(\d+(?:\.\d+)*)/.exec(name);
  const ver = m ? m[1].split('.').map(x => -Number(x)) : [1];
  return { isSmall, isInternal, ver, origIndex };
}

function compareGeminiKeys(a, b) {
  if (a.isSmall !== b.isSmall) return a.isSmall - b.isSmall;
  if (a.isInternal !== b.isInternal) return a.isInternal - b.isInternal;
  const maxLen = Math.max(a.ver.length, b.ver.length);
  for (let i = 0; i < maxLen; i++) {
    const av = a.ver[i] ?? 0;
    const bv = b.ver[i] ?? 0;
    if (av !== bv) return av - bv;
  }
  return a.origIndex - b.origIndex;
}

function resolveEffortForSteps(values, family, effortStepsBelow = 0, topEffort = 'highest') {
  const supported = effortValues(values, family);
  const ordered = EFFORTS.filter(value => supported.includes(value));
  const capName = ['ultra', 'max', 'xhigh', 'high'].includes(topEffort) ? topEffort : 'ultra';
  const capIdx = EFFORTS.indexOf(capName);
  const capped = ordered.filter(e => EFFORTS.indexOf(e) <= capIdx);
  const pool = capped.length ? capped : [ordered[0]];
  const topRung = topEffort === 'high' ? 2 : 3;
  const targetRung = Math.max(0, topRung - Math.max(0, Number(effortStepsBelow) || 0));
  if (targetRung >= 3) return pool.at(-1);
  if (targetRung === 2) {
    if (pool.includes('high')) return 'high';
    const le = pool.filter(e => EFFORTS.indexOf(e) <= EFFORTS.indexOf('high'));
    return le.length ? le.at(-1) : pool[0];
  }
  if (targetRung === 1) {
    if (pool.includes('medium')) return 'medium';
    const le = pool.filter(e => EFFORTS.indexOf(e) <= EFFORTS.indexOf('medium'));
    return le.length ? le.at(-1) : pool[0];
  }
  if (pool.includes('low')) return 'low';
  const le = pool.filter(e => EFFORTS.indexOf(e) <= EFFORTS.indexOf('low'));
  return le.length ? le.at(-1) : pool[0];
}

function standardEffortForLevels(values, family) {
  return resolveEffortForSteps(values, family, 2, 'highest');
}

function generalistLadder(family, ranked) {
  let generalist;
  if (family === 'claude') {
    const hasVersioned = ranked.some(r => !CLAUDE_MOVING_ALIAS_SET.has(r.model));
    generalist = hasVersioned
      ? ranked.filter(r => !CLAUDE_DUPLICATE_ALIAS_SET.has(r.model) && !isSmallOrWrapperModel(r.model))
      : ranked.filter(r => !r.model.toLowerCase().includes('haiku'));
  } else {
    generalist = ranked.filter(r => !isSmallOrWrapperModel(r.model));
  }
  return generalist.length ? generalist : ranked;
}

export function selectStrength(family, catalog, strength = 'standard', policy = null) {
  const effStrength = normalizeStrength(strength, 'standard');
  const cfg = effectiveVariableStrengthConfig(policy);
  const spec = effStrength === 'heavy' ? cfg.heavy : cfg.light;
  const mSteps = Number(spec.model_steps_below) || 0;
  const eSteps = Number(spec.effort_steps_below) || 0;
  const topEff = cfg.top_effort || 'highest';
  const alreadyNormalizedRows = Array.isArray(catalog)
    && catalog.length > 0
    && catalog.every(r => r && typeof r === 'object' && typeof r.model === 'string' && Array.isArray(r.efforts));
  const normalized = alreadyNormalizedRows
    ? {
      schema_version: 1,
      family,
      models: normalizedRows(family, catalog),
      selection_evidence: 'normalized_catalog',
    }
    : normalizeCatalog(family, catalog);
  let ranked = [...normalized.models].sort((left, right) => left.rank - right.rank);
  if (family === 'gemini') {
    ranked = ranked
      .map((entry, idx) => ({ entry, key: geminiGeneralistSortKey(entry, idx) }))
      .sort((a, b) => compareGeminiKeys(a.key, b.key))
      .map(item => item.entry);
  }
  if (family === 'chatgpt' && ranked.length > 1 && ranked[0].rank === ranked[1].rank) {
    fail(family, 'Latest model ranking is ambiguous; refresh subscription capabilities.');
  }
  if (effStrength === 'heavy' && mSteps === 0 && eSteps === 0 && topEff === 'highest') {
    const byId = new Map(ranked.map(entry => [entry.model, entry]));
    const visited = new Set();
    let selected = ranked[0];
    let upgraded = false;
    while (selected.upgrade) {
      if (visited.has(selected.model)) fail(family, 'The model upgrade links contain a cycle.');
      visited.add(selected.model);
      const successor = byId.get(selected.upgrade);
      if (!successor) fail(family, 'The advertised model upgrade target is absent or unavailable.');
      selected = successor;
      upgraded = true;
    }
    return {
      family,
      model: selected.model,
      effort: highestEffort(selected.efforts, family),
      requested_strength: 'heavy',
      selection_evidence: upgraded ? `${normalized.selection_evidence}+provider_upgrade` : normalized.selection_evidence,
      model_attested: false,
      ...(normalized.warning ? { warning: normalized.warning } : {}),
    };
  }
  const generalist = generalistLadder(family, ranked);
  const idx = Math.min(Math.max(0, mSteps), generalist.length - 1);
  const chosen = generalist[idx];
  const stepSuffix = mSteps === 0
    ? (eSteps > 0 || topEff !== 'highest' ? '+frontier_step0' : '')
    : (generalist.length === 1
      ? '+single_model_catalog_effort_stepdown'
      : (idx === 1 ? '+one_below_frontier' : `+${idx}_below_frontier`));
  return {
    family,
    model: chosen.model,
    effort: resolveEffortForSteps(chosen.efforts, family, eSteps, topEff),
    requested_strength: effStrength,
    selection_evidence: `${normalized.selection_evidence}${stepSuffix}`,
    model_attested: false,
    ...(normalized.warning ? { warning: normalized.warning } : {}),
  };
}

/** Strip routing pins and API billing inputs, retaining subscription identity and permissions. */
export function policyEnvironment(env = process.env) {
  const clean = { ...env };
  const modelPins = new Set([
    'ANTHROPIC_MODEL', 'CLAUDE_MODEL', 'CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_SUBAGENT_MODEL',
    'GROK_DEFAULT_MODEL', 'GROK_MODEL', 'GROK_REASONING_EFFORT', 'CODEX_MODEL', 'CHATGPT_MODEL',
    'CODEX_REASONING_EFFORT', 'OPENAI_MODEL', 'GEMINI_MODEL', 'GOOGLE_MODEL',
    'TRIO_REASONING_EFFORT', 'TRIO_EFFORT',
    'OPENAI_BASE_URL', 'OPENAI_API_BASE', 'ANTHROPIC_BASE_URL', 'XAI_BASE_URL', 'GROK_BASE_URL',
    'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
  ]);
  const providerKeys = /^(?:OPENAI|ANTHROPIC|XAI|GROK|CODEX|GEMINI|GOOGLE|GOOGLE_AI|AZURE_OPENAI|OPENROUTER)_API_KEY$/;
  for (const key of Object.keys(clean)) {
    const upper = key.toUpperCase();
    if (modelPins.has(upper) || /^ANTHROPIC_DEFAULT_.*_MODEL$/.test(upper)
        || /^TRIO_MODEL/.test(upper) || /^TRIO_DRIVER_/.test(upper) || providerKeys.test(upper)
        || upper === 'ANTHROPIC_AUTH_TOKEN' || upper === 'OPENAI_API_TOKEN' || upper === 'GROK_API_TOKEN') {
      delete clean[key];
    }
  }
  return clean;
}

function pathValue(env) {
  return env.PATH ?? env.Path ?? env.path ?? '';
}

function executableFor(family, env) {
  const base = { chatgpt: 'codex', grok: 'grok', claude: 'claude', gemini: 'agy' }[family];
  if (!base) return null;
  const name = process.platform === 'win32' ? `${base}.exe` : base;
  const extra = family === 'gemini' && env.LOCALAPPDATA ? [path.join(env.LOCALAPPDATA, 'agy', 'bin')] : [];
  for (const directory of [...pathValue(env).split(path.delimiter).filter(Boolean), ...extra]) {
    const candidate = path.join(directory.replace(/^"|"$/g, ''), name);
    try {
      if (fs.statSync(candidate).isFile()) return fs.realpathSync(candidate);
    } catch { /* Another PATH entry may contain the native subscription CLI. */ }
  }
  return null;
}

function probe(family, executable, args, env) {
  try {
    return execFileSync(executable, args, {
      encoding: 'utf8', timeout: 25_000, maxBuffer: MAX_BYTES,
      windowsHide: true, shell: false, env: policyEnvironment(env),
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch {
    fail(family, 'The bounded subscription CLI capability probe failed.', 'capability_probe_failed');
  }
}

function semver(value) {
  return typeof value === 'string' ? value.match(/\b\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?\b/)?.[0] : undefined;
}

/**
 * Deterministic subscription CLI authentication preflight across all 4 families
 * (`claude auth status --json`, `codex login status`, `agy models`, `grok models`).
 */
export function preflightSubscriptionCli(family, {
  env = process.env,
  executable = executableFor(family, env),
  spawnSyncImpl = nodeSpawnSync,
} = {}) {
  familyName(family);
  if (!executable) {
    return {
      ok: false, family, status: 'cli_unavailable', login_required: false,
      subscription_auth: null, replay_safe: true,
      error: `${family} native subscription CLI is not available on PATH`,
    };
  }
  const args = family === 'claude' ? ['auth', 'status', '--json']
    : family === 'chatgpt' ? ['login', 'status']
      : ['models'];
  const run = spawnSyncImpl(executable, args, {
    env: Object.assign({}, policyEnvironment(env), { NO_COLOR: '1', CI: '1' }),
    shell: false, windowsHide: true, encoding: 'utf8', timeout: 15_000,
  });
  const detail = `${run?.error?.message || ''}\n${run?.stdout || ''}\n${run?.stderr || ''}`.trim();
  if (run?.error?.code === 'ETIMEDOUT') {
    return {
      ok: false, family, status: 'preflight_timeout', login_required: false,
      subscription_auth: null, replay_safe: true,
      error: `${family} auth preflight timed out`.slice(0, 300),
    };
  }
  if (run?.error || run?.status == null) {
    return {
      ok: false, family, status: 'spawn_error', login_required: false,
      subscription_auth: null, replay_safe: true,
      error: `${family} auth preflight could not start: ${detail}`.slice(0, 300),
    };
  }
  if (family === 'claude') {
    let parsed = null;
    try { parsed = JSON.parse(String(run.stdout || '').trim()); } catch { parsed = null; }
    if (parsed && typeof parsed === 'object') {
      if (parsed.loggedIn === true) {
        const subType = typeof parsed.subscriptionType === 'string' ? parsed.subscriptionType.trim().toLowerCase() : '';
        const planTier = typeof parsed.planTier === 'string' ? parsed.planTier.trim().toLowerCase() : '';
        return {
          ok: true, family, status: 'ready', login_required: false, subscription_auth: true,
          subscriptionType: subType || null, planTier: planTier || null,
        };
      }
      return {
        ok: false, family, status: 'auth_expired', login_required: true,
        subscription_auth: false, replay_safe: true,
        error: String(parsed.error || detail || 'Claude CLI loggedIn:false').slice(0, 300),
      };
    }
    if (run.status === 0 && /\blogged\s*in\b/i.test(detail) && !/\bnot\s+logged\s+in\b/i.test(detail)) {
      return { ok: true, family, status: 'ready', login_required: false, subscription_auth: true };
    }
    return {
      ok: false, family, status: 'auth_expired', login_required: true,
      subscription_auth: false, replay_safe: true,
      error: detail.slice(0, 300) || 'Claude CLI authentication required',
    };
  }
  if (family === 'chatgpt') {
    if (run.status === 0 && /logged in using chatgpt/i.test(detail)) {
      return { ok: true, family, status: 'ready', login_required: false, subscription_auth: true };
    }
    return {
      ok: false, family, status: 'auth_expired', login_required: true,
      subscription_auth: false, replay_safe: true,
      error: detail.slice(0, 300) || 'Codex CLI is not logged in using ChatGPT',
    };
  }
  const authFailed = /not logged in|login required|authentication|please (?:log|sign) in|oauth.*expired|session.*expired|unauthenticated|unauthorized/i.test(detail);
  if (run.status !== 0 || authFailed || (family === 'gemini' && !/\bgemini-/i.test(String(run.stdout || '')))) {
    return {
      ok: false, family, status: 'auth_expired', login_required: true,
      subscription_auth: false, replay_safe: true,
      error: detail.slice(0, 300) || `${family} CLI authentication required`,
    };
  }
  return { ok: true, family, status: 'ready', login_required: false, subscription_auth: true };
}

export function preflightAllSubscriptionClis(
  families = ['claude', 'chatgpt', 'gemini', 'grok'],
  opts = {},
) {
  const unique = [...new Set(families)];
  const results = {};
  const failed = [];
  for (const fam of unique) {
    const customExec = opts.executables?.[fam]
      ?? (typeof opts.executableForImpl === 'function' ? opts.executableForImpl(fam, opts.env) : undefined);
    const res = preflightSubscriptionCli(fam, {
      ...opts,
      ...(customExec !== undefined ? { executable: customExec } : {}),
    });
    results[fam] = res;
    if (!res.ok) failed.push(res);
  }
  return { ok: failed.length === 0, results, byFamily: results, failed };
}

export function discoverModelCapabilities(family, { env = process.env, executable = executableFor(family, env) } = {}) {
  familyName(family);
  if (!executable) fail(family, 'A native subscription CLI is not available on PATH.', 'cli_unavailable');
  if (family === 'gemini') return normalizeCatalog(family, probe(family, executable, ['models'], env));
  if (family === 'chatgpt') {
    let raw;
    try { raw = JSON.parse(probe(family, executable, ['debug', 'models'], env)); }
    catch (error) {
      if (error instanceof PolicyUnavailable) throw error;
      fail(family, 'Codex returned malformed capability JSON.');
    }
    let bundled;
    try { bundled = JSON.parse(probe(family, executable, ['debug', 'models', '--bundled'], env)); }
    catch { bundled = null; } // A unique current ranking needs no tie-break.
    raw = reconcileCodexCatalog(raw, bundled);
    return normalizeCatalog(family, raw);
  }
  if (family === 'claude') {
    let restrictFrontier = false;
    if (env.TRIO_SKIP_AUTH_PREFLIGHT !== '1') {
      const auth = preflightSubscriptionCli('claude', { env, executable });
      if (!auth.ok && (auth.status === 'auth_expired' || auth.login_required)) {
        fail('claude', 'Claude subscription CLI is not authenticated (run `claude auth login`).', 'auth_expired');
      }
      restrictFrontier = auth.ok && (auth.subscriptionType === 'pro' || auth.subscriptionType === 'free');
    }
    return normalizeCatalog(family, {
      help: probe(family, executable, ['--help'], env),
      models: restrictFrontier
        ? ['claude-opus-5-5', 'opus', 'sonnet', 'haiku']
        : CLAUDE_CATALOG_MODELS,
    });
  }
  const version = semver(probe(family, executable, ['--version'], env));
  if (!version) fail(family, 'The installed Grok version could not be verified.');
  probe(family, executable, ['models'], env);
  const raw = readJson(path.join(profileDirectory(env), '.grok', 'models_cache.json'), family);
  const fetched = typeof raw?.fetched_at === 'string' ? Date.parse(raw.fetched_at) : NaN;
  const freshnessTimestamp = raw?.renewed_at ?? raw?.fetched_at;
  const freshness = typeof freshnessTimestamp === 'string' ? Date.parse(freshnessTimestamp) : NaN;
  const now = Date.now();
  const age = now - freshness;
  if (!Number.isFinite(fetched) || fetched > now || !Number.isFinite(freshness)
      || freshness < fetched || age < 0 || age > TTL_MS) {
    fail(family, 'Grok capability cache is stale or has an invalid timestamp.');
  }
  if (raw.auth_method !== 'session' || raw.origin !== GROK_ORIGIN || raw.grok_version !== version) {
    fail(family, 'Grok capability cache does not match the subscription identity, origin, or installed CLI version.');
  }
  return normalizeCatalog(family, raw);
}

function statStamp(filename) {
  try {
    const stat = fs.statSync(filename);
    return [filename, stat.dev, stat.ino, stat.size, stat.mtimeMs, stat.ctimeMs];
  } catch (error) {
    return [filename, error.code === 'ENOENT' ? 'absent' : 'unreadable'];
  }
}

function provenance(family, env, executable) {
  const profile = profileDirectory(env);
  const codex = env.CODEX_HOME || path.join(profile, '.codex');
  const claude = env.CLAUDE_CONFIG_DIR || path.join(profile, '.claude');
  const files = family === 'chatgpt'
    ? [path.join(codex, 'auth.json'), path.join(codex, 'config.toml'), path.join(codex, 'models_cache.json')]
    : family === 'grok'
      ? ['config.toml', 'config.json', 'auth.json', 'session.json', 'models_cache.json'].map(name => path.join(profile, '.grok', name))
      : [path.join(profile, '.claude.json'), path.join(claude, 'settings.json'), path.join(claude, '.credentials.json')];
  if (executable) files.push(executable);
  return [family, profile, pathValue(env), env.CODEX_HOME || '', env.CLAUDE_CONFIG_DIR || '', files.map(statStamp)];
}

export function clearModelPolicyCache() {
  cache.clear();
  discovererIds = new WeakMap();
  nextDiscovererId = 1;
}

/** Resolve once per seat/turn boundary; callers persist this frozen receipt. */
export function resolveModelPolicy(family, {
  env = process.env, settings, force = false, discoverer = discoverModelCapabilities,
  role = null, label = null, tier = null, skill = null, model = null,
} = {}) {
  familyName(family);
  const prefs = settings === undefined ? loadPolicyPrefs(env) : validatePrefs(settings);
  const executable = executableFor(family, env);
  if (typeof discoverer !== 'function') fail(family, 'The capability discovery adapter is unavailable.');
  if (!discovererIds.has(discoverer)) discovererIds.set(discoverer, nextDiscovererId++);
  const keyFor = () => JSON.stringify([discovererIds.get(discoverer), provenance(family, env, executable)]);
  let key = keyFor();
  let entry = force ? null : cache.get(key);
  if (!entry || Date.now() - entry.at > TTL_MS || Date.now() < entry.at) {
    let rawDiscovered = discoverer(family, { env: policyEnvironment(env), executable });
    if (family === 'claude' && rawDiscovered?.schema_version !== 1 && !Array.isArray(rawDiscovered?.models)) {
      rawDiscovered = object(rawDiscovered)
        ? { ...rawDiscovered, models: CLAUDE_CATALOG_MODELS }
        : { help: rawDiscovered, models: CLAUDE_CATALOG_MODELS };
    }
    const catalog = normalizeCatalog(family, rawDiscovered);
    const at = Date.now();
    entry = { catalog, at, discovered_at: new Date(at).toISOString() };
    // Discovery may refresh a provider cache or authentication/config metadata.
    key = keyFor();
    cache.set(key, entry);
    if (cache.size > 64) cache.delete(cache.keys().next().value);
  }
  const vsActive = isVariableStrengthActive({ settings: prefs, env, tier, skill });
  if (vsActive) {
    const vsCfg = effectiveVariableStrengthConfig(prefs.model_policy?.mode === 'variable_strength' ? prefs.model_policy : prefs);
    const effStrength = resolveSkillStrength({
      skill: skill || env?.ANCHOR_SKILL,
      explicitStrength: tier ?? env?.ANCHOR_STRENGTH ?? env?.TRIO_TIER,
      inheritedStrength: env?.ANCHOR_INHERITED_STRENGTH,
      cockpitStrength: env?.ANCHOR_COCKPIT_STRENGTH,
      defaultStrength: vsCfg.default_strength || 'standard',
      settings: prefs,
      env,
    });
    let resolvedVs = selectStrength(family, entry.catalog, effStrength, vsCfg);
    if (family === 'claude') {
      const explicitTrimmed = typeof model === 'string' && model.trim() ? model.trim() : null;
      const reviewEnvOverride = typeof env?.TRIO_CLAUDE_REVIEW_MODEL === 'string' && env.TRIO_CLAUDE_REVIEW_MODEL.trim()
        ? env.TRIO_CLAUDE_REVIEW_MODEL.trim()
        : null;
      const verificationSeat = isClaudeVerificationSeat({ role, label });
      if (reviewEnvOverride) {
        const matchedEnv = entry.catalog.models.find(row => row.model === reviewEnvOverride);
        if (matchedEnv) {
          const requestedEff = typeof env?.CLAUDE_EFFORT === 'string' ? env.CLAUDE_EFFORT.trim().toLowerCase() : '';
          resolvedVs = {
            ...resolvedVs,
            model: matchedEnv.model,
            effort: (requestedEff && matchedEnv.efforts.includes(requestedEff))
              ? requestedEff
              : resolvedVs.effort,
            selection_evidence: 'explicit_review_env_override',
          };
        }
      } else if (!verificationSeat && explicitTrimmed && explicitTrimmed !== 'best' && explicitTrimmed !== 'latest_supported') {
        const matchedExplicit = entry.catalog.models.find(row => row.model === explicitTrimmed);
        if (matchedExplicit) {
          const spec = effStrength === 'heavy' ? vsCfg.heavy : vsCfg.light;
          resolvedVs = {
            ...resolvedVs,
            model: matchedExplicit.model,
            effort: resolveEffortForSteps(matchedExplicit.efforts, family, spec.effort_steps_below, vsCfg.top_effort),
            selection_evidence: 'explicit_call_model',
          };
        }
      } else if (
        effStrength === 'heavy'
        && vsCfg.heavy.model_steps_below === 0
        && (
          entry.catalog.models.some(row => row.model === 'claude-fable-5-2')
          || entry.catalog.models.every(row => CLAUDE_MOVING_ALIAS_SET.has(row.model))
        )
      ) {
        const fableRow = entry.catalog.models.find(row => row.model === 'claude-fable-5-2');
        resolvedVs = {
          ...resolvedVs,
          model: 'claude-fable-5-2',
          effort: fableRow
            ? resolveEffortForSteps(fableRow.efforts, family, vsCfg.heavy.effort_steps_below, vsCfg.top_effort)
            : resolvedVs.effort,
          selection_evidence: 'heavy_review_fable_pin',
        };
      }
    }
    return {
      ...resolvedVs,
      policy_version: POLICY_VERSION,
      requested_policy: prefs.model_policy?.mode === 'variable_strength'
        ? { ...prefs.model_policy }
        : { ...VARIABLE_STRENGTH_POLICY },
      settings_revision: prefs.settings_revision,
      discovered_at: entry.discovered_at,
    };
  }
  const baseSelection = selectModel(family, entry.catalog);
  const qualityChoice = prefs.provider_preferences?.quality?.[family];
  let resolvedSelection = baseSelection;
  if (qualityChoice && typeof qualityChoice.model === 'string') {
    const targetModel = qualityChoice.model === 'latest_supported'
      ? baseSelection.model
      : qualityChoice.model;
    const matchedRow = entry.catalog.models.find(row => row.model === targetModel);
    if (matchedRow) {
      const targetEffort = qualityChoice.effort && qualityChoice.effort !== 'highest_supported'
        && matchedRow.efforts.includes(qualityChoice.effort)
        ? qualityChoice.effort
        : highestEffort(matchedRow.efforts, family);
      if (targetModel !== baseSelection.model || targetEffort !== baseSelection.effort) {
        resolvedSelection = {
          ...baseSelection,
          model: matchedRow.model,
          effort: targetEffort,
          selection_evidence: 'explicit_setup_choice',
        };
      }
    }
  }
  if (family === 'claude') {
    const explicitTrimmed = typeof model === 'string' && model.trim() ? model.trim() : null;
    const reviewEnvOverride = typeof env?.TRIO_CLAUDE_REVIEW_MODEL === 'string' && env.TRIO_CLAUDE_REVIEW_MODEL.trim()
      ? env.TRIO_CLAUDE_REVIEW_MODEL.trim()
      : null;
    const verificationSeat = isClaudeVerificationSeat({ role, label });
    const heavyTier = String(tier ?? env?.TRIO_TIER ?? '').trim().toLowerCase() === 'heavy';
    const heavyOrReview = verificationSeat || heavyTier;
    if (reviewEnvOverride) {
      const matchedEnv = entry.catalog.models.find(row => row.model === reviewEnvOverride);
      if (matchedEnv) {
        const requestedEff = typeof env?.CLAUDE_EFFORT === 'string' ? env.CLAUDE_EFFORT.trim().toLowerCase() : '';
        resolvedSelection = {
          ...resolvedSelection,
          model: matchedEnv.model,
          effort: (requestedEff && matchedEnv.efforts.includes(requestedEff))
            ? requestedEff
            : highestEffort(matchedEnv.efforts, family),
          selection_evidence: 'explicit_review_env_override',
        };
      }
    } else if (!verificationSeat && explicitTrimmed && explicitTrimmed !== 'best' && explicitTrimmed !== 'latest_supported') {
      const matchedExplicit = entry.catalog.models.find(row => row.model === explicitTrimmed);
      if (matchedExplicit) {
        resolvedSelection = {
          ...resolvedSelection,
          model: matchedExplicit.model,
          effort: highestEffort(matchedExplicit.efforts, family),
          selection_evidence: 'explicit_call_model',
        };
      }
    } else if (heavyOrReview) {
      const fableRow = entry.catalog.models.find(row => row.model === 'claude-fable-5-2');
      resolvedSelection = {
        ...resolvedSelection,
        model: 'claude-fable-5-2',
        effort: fableRow ? highestEffort(fableRow.efforts, family) : resolvedSelection.effort,
        selection_evidence: 'heavy_review_fable_pin',
      };
    }
  }
  return {
    ...resolvedSelection,
    policy_version: POLICY_VERSION,
    requested_policy: { ...prefs.model_policy },
    settings_revision: prefs.settings_revision,
    discovered_at: entry.discovered_at,
  };
}

/** Caller retains its existing permission flags; these affect selection only. */
export function modelLaunchArgs(selection) {
  const family = familyName(selection?.family);
  const model = modelId(selection.model, family);
  const effort = highestEffort([selection.effort], family);
  if (family === 'chatgpt') return [
    '--model', model,
    '-c', `model_reasoning_effort=${JSON.stringify(effort)}`,
    '-c', `agents.default_subagent_model=${JSON.stringify(model)}`,
    '-c', `agents.default_subagent_reasoning_effort=${JSON.stringify(effort)}`,
    '-c', 'forced_login_method="chatgpt"',
  ];
  if (family === 'grok') return ['--model', model, '--reasoning-effort', effort];
  if (family === 'claude') return ['--model', model, '--effort', effort];
  if (family === 'gemini') return ['--model', agyModelId(model, effort)];
  fail(family, 'No verified latest/highest launch contract for this family.', 'capability_unsupported');
}
