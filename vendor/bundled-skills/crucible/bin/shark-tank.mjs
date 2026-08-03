// shark-tank.mjs — Crucible's adversarial review round (Wave 2).
//
// A Shark Tank is one round of adversarial review: three INDEPENDENT, fresh-
// context Sharks (Skeptic / Contrarian / Analyst) are each handed the North Star
// VERBATIM plus a rotated PM critique angle, and prompted to REFUTE the draft.
// Their findings are then tallied into a single verdict.
//
// REUSE, NOT REINVENT (per the project's standing rule + MASTER-PLAN §6):
//   - The agent INJECTION contract mirrors Foreman's `makeAgentDriver({ agent })`
//     (`wave-workflow.js`): the driver is built from the SAME Wave-1 `agent` seam
//     (`makeAgentSeam(...).agent`) you would hand Foreman. We define a Crucible
//     `makeSharkDriver({ agent })` rather than calling Foreman's `makeAgentDriver`
//     verbatim because its `review()` emits a Foreman-GATE-artifact prompt; the
//     more-specific Wave-2 requirement — "each prompt embedding the North Star + a
//     rotated PM critique angle" — needs a plan-level Shark prompt instead.
//   - The agreement TALLY reuses Foreman's `collectFindings` (`wave-engine.mjs`)
//     unchanged; Crucible only adds the cross-Shark id NORMALIZATION in front of
//     it (so ≥2-agree fires on the *same* issue even when Sharks word it
//     differently) and the inclusion-test DEMOTION behind it.
//   - The finding schema extends Foreman's `REVIEW_SCHEMA` with the Crucible
//     fields the round mechanic needs (`topic`, `traces_to_north_star`, `tag`).

import fs from 'node:fs';
import path from 'node:path';

import { HaltError, REVIEW_SCHEMA } from './crucible-lib.mjs';
import { collectFindings } from '../../foreman/bin/wave-engine.mjs';

// ---------------------------------------------------------------------------
// The Sharks and PM's 8 critique angles (MASTER-PLAN §6).
// ---------------------------------------------------------------------------

/** The three fixed Shark roles (persona = the machinery each channels). */
export const SHARK_ROLES = [
  { role: 'Skeptic', persona: 'Critic' },
  { role: 'Contrarian', persona: "Devil's-Advocate" },
  { role: 'Analyst', persona: 'researchPrime' },
];

/** PM's 8 critique angles, rotated across Sharks/rounds for diverse pushback. */
export const PM_CRITIQUE_ANGLES = [
  'security',
  'frustrated-UX',
  'operator',
  'skeptical-researcher',
  'competitor',
  'bored-investor',
  'future-maintainer',
  'steel-man-the-premise',
];

/**
 * The critique angle a given Shark wears this round. Rotates across BOTH the
 * Shark index and the round number so the same Shark sees fresh angles over a
 * multi-round loop and no angle is starved.
 */
export function angleForShark(round, sharkIndex, roleCount = SHARK_ROLES.length) {
  const n = PM_CRITIQUE_ANGLES.length;
  const rc = Math.max(1, Number(roleCount) || SHARK_ROLES.length);
  const i = ((round * rc + sharkIndex) % n + n) % n;
  return PM_CRITIQUE_ANGLES[i];
}

// ---------------------------------------------------------------------------
// Finding schema — Foreman's REVIEW_SCHEMA + Crucible round fields.
// ---------------------------------------------------------------------------

/**
 * Each Shark finding: a severity, a STABLE `topic` naming the issue (the cross-
 * Shark convergence key — same issue ⇒ same topic), an inclusion-test verdict
 * (`traces_to_north_star` + which criterion), and a scope tag. Extends Foreman's
 * REVIEW_SCHEMA item shape rather than redefining it.
 */
export const SHARK_SCHEMA = {
  type: 'object',
  required: ['answerable', 'findings'],
  properties: {
    answerable: { enum: ['yes', 'no'] },
    note: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'topic', 'traces_to_north_star'],
        properties: {
          severity: { enum: ['BLOCKER', 'MAJOR', 'MINOR', 'NIT'] },
          topic: { type: 'string' },
          claim_id: { type: ['string', 'null'] },
          section: { type: 'string' },
          tag: { enum: ['refinement', 'out-of-scope'] },
          traces_to_north_star: { enum: ['yes', 'no'] },
          criterion: { type: ['string', 'null'] },
          message: { type: 'string' },
        },
      },
    },
  },
};

// ---------------------------------------------------------------------------
// Cross-Shark finding identity (normalization).
//
// Foreman's findingId is `file:line+rule` — right for code, wrong for plan-level
// critique where two Sharks describe the SAME issue in different words. Crucible
// keys identity on a NORMALIZED topic: lowercase, alphanumeric tokens, stopwords
// dropped, then sorted — so "North Star is ambiguous about scope" and "ambiguous
// scope in the North Star" collapse to one id and their ≥2 agreement actually
// registers. Falls back to a Foreman-style location id only if a Shark omits a
// topic.
// ---------------------------------------------------------------------------

const STOPWORDS = new Set([
  'the', 'a', 'an', 'is', 'are', 'was', 'be', 'being', 'been', 'of', 'to', 'about',
  'on', 'in', 'for', 'and', 'or', 'that', 'this', 'it', 'its', 'too', 'very', 'as',
  'by', 'at', 'not', 'no', 'but', 'with', 'should', 'must', 'need', 'needs', 'has',
  'have', 'plan', 'draft', 'there', 'here', 'we', 'you',
]);

/** Canonicalize free text into an order- and wording-insensitive identity key. */
export function normalizeTopic(s) {
  const tokens = String(s ?? '').toLowerCase().match(/[a-z0-9]+/g) || [];
  const kept = tokens.filter((t) => t.length > 1 && !STOPWORDS.has(t));
  return (kept.length ? kept : tokens).sort().join('-');
}

/**
 * Canonicalize an EXPLICIT claim id (e.g. "C3", "claim-heartbeat-cadence"). Unlike
 * `normalizeTopic` this preserves token ORDER — an id is an identifier, not prose.
 */
function normalizeClaimId(v) {
  if (v == null) return '';
  return String(v).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

/** The stable, cross-Shark normalized id for a finding. */
export function normalizeFindingId(f) {
  // An EXPLICIT claim id BEATS the free-text topic slug. When the artifact under
  // review carries stable claim ids (researchPrime's ledger), reviewers disputing
  // the same claim must converge on ONE identity even when their topic wording
  // differs — three reviewers slugging the same claim three ways each counted
  // agreement:1 and produced a real false-DRY (researchPrime journal 0001,
  // 2026-07-06). Identity precedence: claim_id > topic > location.
  const claimKey = normalizeClaimId(f.claim_id ?? f.claimId);
  if (claimKey) return `claim:${claimKey}`;
  const topicKey = normalizeTopic(f.topic);
  if (topicKey) return `topic:${topicKey}`;
  const scope = normalizeTopic(f.section || f.file) || 'plan';
  const rule = normalizeTopic(f.rule || f.message) || 'unspecified';
  return `loc:${scope}::${rule}`;
}

const SEV_RANK = { BLOCKER: 4, MAJOR: 3, MINOR: 2, NIT: 1 };
const sevRank = (s) => SEV_RANK[String(s || '').toUpperCase()] || 0;

// ---------------------------------------------------------------------------
// Tally: normalize → reuse Foreman agreement count → inclusion-test demote →
// ≥2-agree BLOCKER → dry-round.
// ---------------------------------------------------------------------------

/**
 * Merge per-Shark reviews into a single verdict.
 *
 * Steps:
 *  1. Assign each finding its cross-Shark normalized id and gather per-id facts
 *     (does ANY Shark trace it to the North Star, the max severity raised, which
 *     Sharks raised it, tags/criteria/messages).
 *  2. Reuse Foreman's `collectFindings` for the dedup + agreement count.
 *  3. DEMOTE any finding that traces to no criterion (the inclusion test as a
 *     round mechanic) — demoted findings can never be BLOCKERs and cannot hold
 *     the loop open.
 *  4. A BLOCKER is a non-demoted BLOCKER/MAJOR with ≥2 Sharks agreeing.
 *  5. The round is DRY when there is no NEW BLOCKER (ids in `priorBlockerIds`
 *     are not new — anti-oscillation via the stable id).
 *
 * @param {Array<{reviewer:string, findings:object[]}>} reviews
 * @param {{priorBlockerIds?:string[]}} [o]
 */
export function tallyFindings(reviews, { priorBlockerIds = [] } = {}) {
  const prior = new Set(priorBlockerIds);
  const extras = new Map();

  // (1) normalize ids + accumulate per-id facts.
  const normReviews = reviews.map((rv) => ({
    ...rv,
    findings: (rv.findings || []).map((f) => {
      const id = normalizeFindingId(f);
      const e = extras.get(id) || {
        id, anyTraces: false, severity: 'NIT',
        roles: new Set(), tags: new Set(), criteria: new Set(),
        messages: [], section: f.section || f.file || null,
      };
      if (String(f.traces_to_north_star).toLowerCase() === 'yes') e.anyTraces = true;
      if (sevRank(f.severity) > sevRank(e.severity)) e.severity = String(f.severity).toUpperCase();
      if (rv.reviewer != null) e.roles.add(rv.reviewer);
      if (f.tag) e.tags.add(f.tag);
      if (f.criterion) e.criteria.add(f.criterion);
      if (f.message) e.messages.push(f.message);
      if (!e.section && (f.section || f.file)) e.section = f.section || f.file;
      extras.set(id, e);
      return { ...f, id };
    }),
  }));

  // (2) reuse Foreman's agreement tally (dedup by id, count distinct reviewers).
  const merged = collectFindings(normReviews);

  // (3,4,5) assemble Crucible findings with demotion + blocker + new flags.
  const findings = merged.map((m) => {
    const e = extras.get(m.id);
    const demoted = !e.anyTraces; // fails the inclusion test ⇒ cannot hold the loop open
    const severity = e.severity;
    const isBlocker = !demoted && (severity === 'BLOCKER' || severity === 'MAJOR') && m.agreement >= 2;
    return {
      id: m.id,
      severity,
      agreement: m.agreement,
      demoted,
      isBlocker,
      isNew: !prior.has(m.id),
      traces_to_north_star: e.anyTraces ? 'yes' : 'no',
      tag: e.tags.has('refinement') ? 'refinement' : ([...e.tags][0] || (demoted ? 'out-of-scope' : null)),
      criterion: [...e.criteria][0] || null,
      raisedBy: [...e.roles],
      section: e.section,
      message: e.messages[0] || null,
    };
  });

  const blockers = findings.filter((f) => f.isBlocker);
  const newBlockers = blockers.filter((f) => f.isNew);
  const demoted = findings.filter((f) => f.demoted);
  const dry = newBlockers.length === 0;
  // Quorum floor (2026-07-17): a BLOCKER needs >=2 Sharks to agree, so a round where fewer
  // than 2 reviewers returned a PARSEABLE review is INCONCLUSIVE — its "dry" would be a FALSE
  // convergence (no blocker could ever surface). Only an explicit abstain (answerable:'no' —
  // a rejected call or unparseable-after-retry reply) fails to count; a review present counts.
  const answered = reviews.filter((r) => r && r.answerable !== 'no').length;
  const inconclusive = answered < 2;
  return { findings, blockers, newBlockers, demoted, dry, inconclusive, answered, verdict: dry ? 'DRY' : 'BLOCKED' };
}

// ---------------------------------------------------------------------------
// The Shark driver — built from the injected Wave-1 `agent` seam.
// ---------------------------------------------------------------------------

function sharkPrompt(role, angle, northStar, draft, research = null,
                     { priorBlockerIds = [], changelog = null, markdownFirst = false } = {}) {
  // Fresh researchPrime findings flow to the ANALYST Shark only (persona = researchPrime,
  // MASTER-PLAN §6) — the other Sharks stay deliberately context-fresh.
  const isAnalyst = role.persona === 'researchPrime' || role.role === 'Analyst';
  const researchBlock = isAnalyst && research
    ? [
        ``,
        `=== FRESH RESEARCH INPUT (researchPrime — you are the Analyst; weigh this evidence by quality) ===`,
        typeof research === 'string' ? research : JSON.stringify(research),
        `=== END RESEARCH ===`,
      ]
    : [];
  // 2026-07 efficiency: tell each Shark what is ALREADY on the blocker register
  // and what the last revision changed, so its budget goes to NEW ground instead
  // of re-deriving known findings the tally will discard as not-new. Rigor is
  // unchanged: the Shark still reads the FULL draft and MAY re-raise anything it
  // believes is still unresolved (the register is orientation, not a muzzle).
  const registerBlock = priorBlockerIds.length
    ? [
        ``,
        `=== ALREADY ON THE BLOCKER REGISTER (known topics from prior rounds) ===`,
        ...priorBlockerIds.map((id) => `  - ${id}`),
        `These are KNOWN. A finding matching one of these ids counts as not-new in the`,
        `tally. Spend your effort on NEW failure modes — but if a register item is`,
        `STILL unresolved in this draft, say so explicitly.`,
        `=== END REGISTER ===`,
      ]
    : [];
  const changelogBlock = changelog
    ? [
        ``,
        `=== WHAT THE LAST REVISION CHANGED (the reviser's own changelog) ===`,
        String(changelog),
        `=== END CHANGELOG ===`,
      ]
    : [];
  return [
    `You are the ${role.role} Shark (${role.persona}) in a Crucible Shark Tank — an`,
    `ADVERSARIAL review whose job is to REFUTE this draft, not to praise it. You have`,
    `fresh context: rely only on what is written below.`,
    ``,
    `=== THE NORTH STAR (verbatim — judge every finding against it) ===`,
    String(northStar),
    `=== END NORTH STAR ===`,
    ``,
    `Press hardest through this PM critique angle: ${angle}.`,
    ...researchBlock,
    ...registerBlock,
    ...changelogBlock,
    ``,
    `For EVERY finding emit:`,
    `  - severity: BLOCKER | MAJOR | MINOR | NIT`,
    `  - topic: a SHORT, stable phrase naming the ISSUE itself (not your wording) so`,
    `    other Sharks naming the same issue converge on it`,
    `  - section: the part of the draft it targets`,
    `  - tag: refinement | out-of-scope`,
    `  - traces_to_north_star: yes | no, and (when yes) which criterion`,
    `  - message: the refutation`,
    ...(markdownFirst ? [
      ``,
      `Because this draft is extremely large, DO NOT output a JSON object.`,
      `Emit your review in strict Markdown format exactly like this:`,
      `answerable: yes`,
      `note: [optional context]`,
      ``,
      `## Finding 1`,
      `severity: BLOCKER`,
      `topic: [short phrase]`,
      `section: [section name]`,
      `tag: refinement`,
      `traces_to_north_star: yes`,
      `criterion: [criterion text]`,
      `message: [your refutation]`,
    ] : []),
    ``,
    `INCLUSION TEST: a finding that does not trace to a North-Star criterion`,
    `(traces_to_north_star: no) is out-of-scope and will be DEMOTED — do not inflate`,
    `its severity to keep the loop open.`,
    ``,
    `=== DRAFT UNDER REVIEW ===`,
    String(draft),
    `=== END DRAFT ===`,
  ].join('\n');
}

/**
 * Best-effort recovery of Shark findings from a RAW-TEXT reply for large drafts
 * where JSON serialization breaks.
 */
export function parseFindingsFromMarkdown(rawText) {
  const findings = [];
  let currentFinding = null;
  let answerable = 'yes';
  let note = '';

  // Handle literal \n and missing newlines before keywords
  let normalizedText = String(rawText).replace(/\\n/g, '\n');
  normalizedText = normalizedText.replace(/\s+(?:\*\*)?(severity|topic|section|tag|traces_to_north_star|criterion|message|answerable|note)(?:\*\*)?[:\-]/gi, '\n$1:');

  const lines = normalizedText.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
  for (const line of lines) {
    let m;
    if ((m = line.match(/^(?:##\s*)?(?:\*\*)?Finding[\s\d\:]*(.*)/i))) {
      currentFinding = {
        severity: 'NIT',
        topic: m[1].trim() || 'unnamed finding',
        section: '',
        tag: 'refinement',
        traces_to_north_star: 'yes',
        criterion: null,
        message: ''
      };
      findings.push(currentFinding);
    } else if (currentFinding) {
      if ((m = line.match(/^(?:\*\*)?(severity|topic|section|tag|traces_to_north_star|criterion|message)(?:\*\*)?[:\-\s]+(.*)/i))) {
        const key = m[1].toLowerCase();
        const val = m[2].trim();
        if (key === 'severity') currentFinding.severity = val.toUpperCase();
        else if (key === 'topic') currentFinding.topic = val;
        else if (key === 'section') currentFinding.section = val;
        else if (key === 'tag') currentFinding.tag = val;
        else if (key === 'traces_to_north_star') {
           currentFinding.traces_to_north_star = val.toLowerCase().startsWith('no') ? 'no' : 'yes';
        }
        else if (key === 'criterion') currentFinding.criterion = val;
        else if (key === 'message') currentFinding.message = val;
      }
    } else {
       if ((m = line.match(/^(?:\*\*)?answerable(?:\*\*)?[:\-\s]+(.*)/i))) {
         answerable = m[1].trim().toLowerCase() === 'no' ? 'no' : 'yes';
       } else if ((m = line.match(/^(?:\*\*)?note(?:\*\*)?[:\-\s]+(.*)/i))) {
         note = m[1].trim();
       }
    }
  }
  return { answerable, note, findings };
}

/**
 * Build a Shark driver from an injected `agent()` (Wave-1's seam) — same
 * injection contract as Foreman's `makeAgentDriver({ agent })`.
 * @param {{agent:(prompt:string,opts?:object)=>Promise<any>}} deps
 */
export function makeSharkDriver({ agent } = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError(
      'makeSharkDriver requires an agent() function',
      'pass the Wave-1 seam: makeSharkDriver({ agent: makeAgentSeam(...).agent })',
    );
  }
  return {
    /** Run one Shark over the draft; returns a normalized per-Shark review. */
    async review(role, { round = 0, northStar, draft, angle, research = null,
                         priorBlockerIds = [], changelog = null }) {
      const lens = angle ?? angleForShark(round, SHARK_ROLES.findIndex((r) => r.role === role.role));
      
      const markdownFirst = draft.length > 20000;
      
      const out = await agent(
        sharkPrompt(role, lens, northStar, draft, research, { priorBlockerIds, changelog, markdownFirst }), {
          label: `shark:${role.role}:r${round}`,
          role: 'shark',
          schema: markdownFirst ? undefined : SHARK_SCHEMA,
        });

      let answerable, note, findings;
      if (markdownFirst) {
        const parsed = parseFindingsFromMarkdown(typeof out === 'string' ? out : '');
        answerable = parsed.answerable;
        note = parsed.note;
        findings = parsed.findings;
      } else {
        answerable = out?.answerable ?? 'yes';
        note = out?.note;
        findings = Array.isArray(out?.findings) ? out.findings : [];
      }
      
      return {
        reviewer: role.role,
        angle: lens,
        answerable,
        note,
        findings,
      };
    },
  };
}

// ---------------------------------------------------------------------------
// One full Shark-Tank round.
// ---------------------------------------------------------------------------

/**
 * Run all three Sharks over `draft`, tally a verdict, and (optionally) write the
 * file-based round artifacts.
 *
 * @param {object} o
 * @param {Function} o.agent                    Wave-1 agent seam
 * @param {string}   o.northStar                embedded verbatim in every Shark prompt
 * @param {string}   o.draft                    the artifact under review
 * @param {number}  [o.round=0]
 * @param {string[]}[o.priorBlockerIds=[]]      ids already blocking (anti-oscillation)
 * @param {?(string|object)} [o.research=null]  researchPrime findings — embedded into the Analyst Shark only
 * @param {?string} [o.artifactsDir=null]       when set, writes round artifacts there
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<object>} the round verdict
 */
export async function runSharkTank({
  agent,
  northStar,
  draft,
  round = 0,
  priorBlockerIds = [],
  research = null,
  changelog = null,
  artifactsDir = null,
  /** 2 = LITE concurrent pair; 3 = FULL (default). Floor 2 so ≥2-agree can still fire. */
  sharkRoles = 3,
  log = () => {},
}) {
  const driver = makeSharkDriver({ agent });
  const n = Math.max(2, Math.min(SHARK_ROLES.length, Number(sharkRoles) || 3));
  const roles = SHARK_ROLES.slice(0, n);
  const angles = {};
  const jobs = roles.map((role, i) => {
    const angle = angleForShark(round, i, n);
    angles[role.role] = angle;
    return { role, angle };
  });
  // 2026-07 efficiency: the three fresh-context Sharks run CONCURRENTLY (the
  // port of Foreman's FOREMAN_CONCURRENT_REVIEW pattern — tallyFindings keys on
  // normalized topic ids and is order-independent, and concurrency only
  // strengthens independence). A REJECTED Shark maps to an abstain
  // (answerable:'no', zero findings) — never silently dropped — so the caller's
  // ambiguity handling sees it, exactly like Foreman's mapping. Set
  // CRUCIBLE_CONCURRENT_SHARKS=0 to restore the historical serial path.
  let reviews;
  if (process.env.CRUCIBLE_CONCURRENT_SHARKS !== '0') {
    const settled = await Promise.allSettled(jobs.map(({ role, angle }) =>
      driver.review(role, { round, northStar, draft, angle, research,
                            priorBlockerIds, changelog })));
    reviews = settled.map((s, i) => s.status === 'fulfilled' ? s.value : {
      reviewer: jobs[i].role.role,
      angle: jobs[i].angle,
      answerable: 'no',
      note: `shark ${jobs[i].role.role} call rejected (${s.reason?.message || s.reason}) — abstain`,
      findings: [],
    });
  } else {
    reviews = [];
    for (const { role, angle } of jobs) {
      reviews.push(await driver.review(role, { round, northStar, draft, angle,
                                               research, priorBlockerIds, changelog }));
    }
  }

  const tally = tallyFindings(reviews, { priorBlockerIds });
  const verdict = { round, ...tally, angles, reviews };
  log(
    `shark-tank round ${round}: ${verdict.verdict} — ${verdict.blockers.length} blocker(s), ` +
    `${verdict.demoted.length} demoted, ${verdict.findings.length} finding(s)`,
  );

  if (artifactsDir) verdict.artifactPath = writeRoundArtifacts(artifactsDir, verdict);
  return verdict;
}

// ---------------------------------------------------------------------------
// File-based verdict artifacts.
// ---------------------------------------------------------------------------

function renderSynthesis(verdict) {
  const lines = [
    `# Shark-Tank Round ${verdict.round} — ${verdict.verdict}`,
    '',
    `- Verdict: **${verdict.verdict}** (${verdict.dry ? 'dry round — no new BLOCKER' : `${verdict.newBlockers.length} new BLOCKER`})`,
    `- Angles: ${Object.entries(verdict.angles).map(([r, a]) => `${r}=${a}`).join(', ')}`,
    `- Findings: ${verdict.findings.length} · Blockers: ${verdict.blockers.length} · Demoted (inclusion test): ${verdict.demoted.length}`,
    '',
    '## Blocking (≥2 Sharks agree, traces to a criterion)',
  ];
  if (verdict.blockers.length === 0) lines.push('_none_');
  for (const f of verdict.blockers) {
    lines.push(`- **${f.severity}** \`${f.id}\` — agree ${f.agreement} (${f.raisedBy.join(', ')}) — ${f.message ?? ''}`);
  }
  lines.push('', '## Demoted (failed the inclusion test — cannot hold the loop open)');
  if (verdict.demoted.length === 0) lines.push('_none_');
  for (const f of verdict.demoted) {
    lines.push(`- ~~\`${f.id}\`~~ traces_to_north_star: no — ${f.message ?? ''}`);
  }
  return lines.join('\n') + '\n';
}

/**
 * Write the round's verdict artifacts: a machine `verdict.json`, one file per
 * Shark, and a human-readable `SYNTHESIS.md` (matching the existing
 * `plans/debates/round-N/SYNTHESIS.md` convention). Returns the round dir.
 */
export function writeRoundArtifacts(baseDir, verdict) {
  const roundDir = path.join(baseDir, `round-${verdict.round}`);
  fs.mkdirSync(roundDir, { recursive: true });
  fs.writeFileSync(path.join(roundDir, 'verdict.json'), JSON.stringify(verdict, null, 2));
  for (const rv of verdict.reviews) {
    fs.writeFileSync(path.join(roundDir, `shark-${rv.reviewer}.json`), JSON.stringify(rv, null, 2));
  }
  fs.writeFileSync(path.join(roundDir, 'SYNTHESIS.md'), renderSynthesis(verdict));
  return roundDir;
}
