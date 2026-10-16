// W10 / P7 — SKILL.md ↔ reason-catalog / server reason-code field map CI contract.
//
// Drift between the shipped skill contract and the closed server catalog is
// HALT-worthy: unit green must not silently ship a divergent map.

const fs = require('node:fs');
const path = require('node:path');

const {
  REASON_CATALOG_VERSION,
  DOCTOR_ISSUE_CATALOG_VERSION,
  CLASSIFIER_REASON_CODES,
  DOCTOR_ISSUE_IDS,
  getCatalogsPublicPayload,
} = require('./reason-catalog.js');

const SKILL_ROOT = path.join(__dirname, '..');
const DEFAULT_SKILL_MD = path.join(SKILL_ROOT, 'SKILL.md');

/** Marker for the machine-readable field map fenced in SKILL.md. */
const FIELD_MAP_START = '<!-- ZH_REASON_FIELD_MAP_BEGIN -->';
const FIELD_MAP_END = '<!-- ZH_REASON_FIELD_MAP_END -->';

/** Ownership badge fields required on radar / Why / dual-write (W3 seed + W10 UI). */
const OWNERSHIP_BADGE_FIELDS = Object.freeze([
  'owned',
  'keep',
  'failClosed',
  'label',
  'reasonCodes',
  'stub',
  'stubMaxWave',
]);

/** Server /api catalog payload fields that must stay in lockstep with SKILL.md. */
const SERVER_CATALOG_FIELDS = Object.freeze([
  'reasonCatalogVersion',
  'doctorIssueCatalogVersion',
  'reasonCodes',
  'doctorIssues',
]);

/**
 * Build the canonical field-map object (source of truth for SKILL.md embedding).
 */
function buildCanonicalFieldMap() {
  return {
    contractVersion: 'w10-skill-server-v1',
    reasonCatalogVersion: REASON_CATALOG_VERSION,
    doctorIssueCatalogVersion: DOCTOR_ISSUE_CATALOG_VERSION,
    ownershipBadgeFields: OWNERSHIP_BADGE_FIELDS.slice(),
    serverCatalogFields: SERVER_CATALOG_FIELDS.slice(),
    reasonCodes: CLASSIFIER_REASON_CODES.slice(),
    doctorIssueIds: DOCTOR_ISSUE_IDS.map((x) => x.id),
  };
}

/**
 * Extract the JSON field map from SKILL.md between HTML markers.
 * @param {string} markdown
 * @returns {{ ok: boolean, map: object|null, reason: string }}
 */
function extractFieldMapFromSkillMarkdown(markdown) {
  const text = String(markdown || '');
  const start = text.indexOf(FIELD_MAP_START);
  const end = text.indexOf(FIELD_MAP_END);
  if (start < 0 || end < 0 || end <= start) {
    return {
      ok: false,
      map: null,
      reason: 'missing_zh_reason_field_map_markers',
    };
  }
  const block = text.slice(start + FIELD_MAP_START.length, end);
  // Prefer fenced ```json ... ``` inside the markers; else raw JSON.
  const fence = block.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const raw = fence ? fence[1].trim() : block.trim();
  if (!raw) {
    return { ok: false, map: null, reason: 'empty_field_map_block' };
  }
  try {
    const map = JSON.parse(raw);
    if (!map || typeof map !== 'object' || Array.isArray(map)) {
      return { ok: false, map: null, reason: 'field_map_not_object' };
    }
    return { ok: true, map, reason: 'ok' };
  } catch (e) {
    return {
      ok: false,
      map: null,
      reason: `field_map_json_parse_error:${e && e.message ? e.message : e}`,
    };
  }
}

/**
 * Load and parse SKILL.md field map from disk.
 * @param {string} [skillMdPath]
 */
function loadSkillFieldMap(skillMdPath = DEFAULT_SKILL_MD) {
  if (!fs.existsSync(skillMdPath)) {
    return { ok: false, map: null, reason: 'skill_md_missing', path: skillMdPath };
  }
  const markdown = fs.readFileSync(skillMdPath, 'utf8');
  const extracted = extractFieldMapFromSkillMarkdown(markdown);
  return { ...extracted, path: skillMdPath };
}

/**
 * Compare two string arrays as sets (order-independent).
 * @returns {{ equal: boolean, onlyA: string[], onlyB: string[] }}
 */
function setDiff(a, b) {
  const sa = new Set((a || []).map(String));
  const sb = new Set((b || []).map(String));
  const onlyA = [];
  const onlyB = [];
  for (const x of sa) if (!sb.has(x)) onlyA.push(x);
  for (const x of sb) if (!sa.has(x)) onlyB.push(x);
  onlyA.sort();
  onlyB.sort();
  return { equal: onlyA.length === 0 && onlyB.length === 0, onlyA, onlyB };
}

/**
 * Assert SKILL.md field map matches server reason-catalog (HALT-worthy on drift).
 * @param {object} [opts]
 * @param {string} [opts.skillMdPath]
 * @param {object} [opts.skillMap] — inject map (tests)
 * @returns {{ ok: boolean, haltWorthy: boolean, failures: string[], skill: object|null, canonical: object }}
 */
function assertSkillServerReasonCodeContract(opts = {}) {
  const canonical = buildCanonicalFieldMap();
  const failures = [];
  let skillMap = opts.skillMap || null;

  if (!skillMap) {
    const loaded = loadSkillFieldMap(opts.skillMdPath || DEFAULT_SKILL_MD);
    if (!loaded.ok) {
      return {
        ok: false,
        haltWorthy: true,
        failures: [`skill_map_load:${loaded.reason}`],
        skill: null,
        canonical,
      };
    }
    skillMap = loaded.map;
  }

  if (String(skillMap.contractVersion || '') !== String(canonical.contractVersion)) {
    failures.push(
      `contractVersion drift skill=${skillMap.contractVersion} server=${canonical.contractVersion}`,
    );
  }
  if (String(skillMap.reasonCatalogVersion || '') !== String(canonical.reasonCatalogVersion)) {
    failures.push(
      `reasonCatalogVersion drift skill=${skillMap.reasonCatalogVersion} server=${canonical.reasonCatalogVersion}`,
    );
  }
  if (String(skillMap.doctorIssueCatalogVersion || '')
    !== String(canonical.doctorIssueCatalogVersion)) {
    failures.push(
      `doctorIssueCatalogVersion drift skill=${skillMap.doctorIssueCatalogVersion} server=${canonical.doctorIssueCatalogVersion}`,
    );
  }

  const codeDiff = setDiff(skillMap.reasonCodes, canonical.reasonCodes);
  if (!codeDiff.equal) {
    if (codeDiff.onlyA.length) {
      failures.push(`reasonCodes only_in_SKILL: ${codeDiff.onlyA.join(',')}`);
    }
    if (codeDiff.onlyB.length) {
      failures.push(`reasonCodes only_in_server: ${codeDiff.onlyB.join(',')}`);
    }
  }

  const badgeDiff = setDiff(skillMap.ownershipBadgeFields, canonical.ownershipBadgeFields);
  if (!badgeDiff.equal) {
    failures.push(
      `ownershipBadgeFields drift only_skill=${badgeDiff.onlyA.join(',')} only_server=${badgeDiff.onlyB.join(',')}`,
    );
  }

  const serverFieldsDiff = setDiff(skillMap.serverCatalogFields, canonical.serverCatalogFields);
  if (!serverFieldsDiff.equal) {
    failures.push(
      `serverCatalogFields drift only_skill=${serverFieldsDiff.onlyA.join(',')} only_server=${serverFieldsDiff.onlyB.join(',')}`,
    );
  }

  const issueDiff = setDiff(skillMap.doctorIssueIds, canonical.doctorIssueIds);
  if (!issueDiff.equal) {
    if (issueDiff.onlyA.length) {
      failures.push(`doctorIssueIds only_in_SKILL: ${issueDiff.onlyA.join(',')}`);
    }
    if (issueDiff.onlyB.length) {
      failures.push(`doctorIssueIds only_in_server: ${issueDiff.onlyB.join(',')}`);
    }
  }

  // Server public payload must expose the same closed catalog.
  const pub = getCatalogsPublicPayload();
  const pubDiff = setDiff(pub.reasonCodes, canonical.reasonCodes);
  if (!pubDiff.equal) {
    failures.push('server getCatalogsPublicPayload reasonCodes diverge from CLASSIFIER_REASON_CODES');
  }
  if (pub.reasonCatalogVersion !== REASON_CATALOG_VERSION) {
    failures.push('public reasonCatalogVersion mismatch');
  }

  const ok = failures.length === 0;
  return {
    ok,
    haltWorthy: !ok, // any drift is HALT-worthy per W10
    failures,
    skill: skillMap,
    canonical,
  };
}

/**
 * Named CI gate: test_skill_server_reason_code_contract
 * @param {object} [opts]
 */
function testSkillServerReasonCodeContract(opts = {}) {
  return assertSkillServerReasonCodeContract(opts);
}

module.exports = {
  FIELD_MAP_START,
  FIELD_MAP_END,
  OWNERSHIP_BADGE_FIELDS,
  SERVER_CATALOG_FIELDS,
  DEFAULT_SKILL_MD,
  buildCanonicalFieldMap,
  extractFieldMapFromSkillMarkdown,
  loadSkillFieldMap,
  setDiff,
  assertSkillServerReasonCodeContract,
  testSkillServerReasonCodeContract,
};
