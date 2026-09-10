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
import { execFileSync } from 'node:child_process';

export const DEFAULT_POLICY = Object.freeze({
  mode: 'latest_supported',
  effort: 'highest_supported',
});
export const POLICY_VERSION = 1;
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
  if (!object(policy) || Object.keys(policy).some(key => !Object.hasOwn(DEFAULT_POLICY, key))
      || policy.mode !== DEFAULT_POLICY.mode || policy.effort !== DEFAULT_POLICY.effort) {
    fail(null, 'The model policy must request latest_supported and highest_supported.', 'settings_invalid');
  }
  return { ...DEFAULT_POLICY };
}

function validatePrefs(raw, source) {
  if (!object(raw) || raw.settings_error) fail(null, 'Model preferences are invalid.', 'settings_invalid');
  for (const key of ['coding_family', 'review_family', 'default_cli']) {
    if (!FAMILIES.has(raw[key])) fail(null, `Missing or invalid ${key}.`, 'settings_invalid');
  }
  const revision = raw.settings_revision === undefined ? 0 : raw.settings_revision;
  if (!Number.isSafeInteger(revision) || revision < 0) {
    fail(null, 'settings_revision must be a nonnegative safe integer.', 'settings_invalid');
  }
  return {
    coding_family: raw.coding_family,
    review_family: raw.review_family,
    default_cli: raw.default_cli,
    model_policy: validatePolicy(raw.model_policy === undefined ? DEFAULT_POLICY : raw.model_policy),
    settings_revision: revision,
    source: source || raw.source || 'provided-settings',
  };
}

function profileDirectory(env) {
  return env.USERPROFILE || env.HOME || os.homedir();
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
  const mirror = path.join(profileDirectory(env), '.anchor', 'model_prefs.json');
  const primary = env.ANCHOR_DATA_DIR ? path.join(env.ANCHOR_DATA_DIR, 'settings.json') : null;
  if (primary && present(primary)) return validatePrefs(readJson(primary, null, 'settings_invalid'), 'primary');
  if (present(mirror)) return validatePrefs(readJson(mirror, null, 'settings_invalid'), 'mirror');
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
  if (family === 'gemini') {
    fail(family, 'The agy subscription adapter has no verified latest/highest capability contract.', 'capability_unsupported');
  }
  let entries;
  let evidence;
  let warning;
  if (raw?.schema_version === 1) {
    if (raw.family !== family) fail(family, 'Capability catalog family mismatch.');
    entries = normalizedRows(family, raw.models);
    evidence = family === 'claude' ? 'provider_moving_alias'
      : family === 'grok' ? 'provider_catalog_order'
        : raw.selection_evidence === 'provider_catalog_order' ? 'provider_catalog_order' : 'provider_priority';
  } else if (family === 'chatgpt') {
    const models = Array.isArray(raw?.models) ? raw.models : raw?.data;
    if (!Array.isArray(models)) fail(family, 'Codex did not return a model catalog.');
    const visible = models.filter(entry => object(entry) && !hidden(entry));
    evidence = visible.every(entry => Number.isFinite(entry.priority)) ? 'provider_priority' : 'provider_catalog_order';
    entries = normalizedRows(family, visible.map((entry, index) => ({
      model: entry.slug ?? entry.model ?? entry.id,
      efforts: entry.supported_reasoning_levels ?? entry.supportedReasoningEfforts,
      rank: evidence === 'provider_priority' ? entry.priority : index,
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
    entries = normalizedRows(family, [{ model: 'best', efforts: claudeEfforts(raw), rank: 0 }]);
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
  const base = { chatgpt: 'codex', grok: 'grok', claude: 'claude' }[family];
  if (!base) return null;
  const name = process.platform === 'win32' ? `${base}.exe` : base;
  for (const directory of pathValue(env).split(path.delimiter).filter(Boolean)) {
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

export function discoverModelCapabilities(family, { env = process.env, executable = executableFor(family, env) } = {}) {
  familyName(family);
  if (family === 'gemini') return normalizeCatalog(family, null);
  if (!executable) fail(family, 'A native subscription CLI is not available on PATH.', 'cli_unavailable');
  if (family === 'chatgpt') {
    let raw;
    try { raw = JSON.parse(probe(family, executable, ['debug', 'models'], env)); }
    catch (error) {
      if (error instanceof PolicyUnavailable) throw error;
      fail(family, 'Codex returned malformed capability JSON.');
    }
    return normalizeCatalog(family, raw);
  }
  if (family === 'claude') return normalizeCatalog(family, probe(family, executable, ['--help'], env));
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
    ? [path.join(codex, 'auth.json'), path.join(codex, 'config.toml')]
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
    const catalog = normalizeCatalog(family, discoverer(family, { env: policyEnvironment(env), executable }));
    const at = Date.now();
    entry = { catalog, at, discovered_at: new Date(at).toISOString() };
    // Discovery may refresh a provider cache or authentication/config metadata.
    key = keyFor();
    cache.set(key, entry);
    if (cache.size > 64) cache.delete(cache.keys().next().value);
  }
  return {
    ...selectModel(family, entry.catalog),
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
  fail(family, 'The agy subscription adapter has no verified latest/highest launch contract.', 'capability_unsupported');
}
