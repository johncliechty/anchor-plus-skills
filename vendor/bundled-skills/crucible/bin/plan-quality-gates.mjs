// plan-quality-gates.mjs — Mechanical Chekhov PROCESS-REVIEW.md Plan-Quality Guards
// & Portfolio Skill Composition for Crucible (Stage 1 / Stage 2 / Matrix Fast-Track).
//
// Pure, deterministic, 0-LLM-call lints enforcing:
//   1. Wave 1 = Usable End-to-End Pilot Slice (rejects >=3-wave plans whose Wave 1 + Wave 2
//      deliver only internal plumbing/schemas without an explicit `pilot_override_reason`).
//   2. O(N) Call / Latency Budget Estimator (flags unbounded per-item / per-chapter / per-file
//      serial LLM/agent spawns lacking batching or concurrency bounds).
//   3. Plain-English Scope-Cut & <=200-Word Approval Gate Block (ELEGANCE.md Rule 1 & Rule 5).
//   4. Portfolio Skill Composition Gates:
//      - Interactive Chrome Mockup (`ft.py chrome-open` + `ft.py look`) & `Figure-Designer`
//        whenever planned write targets touch `.html`, `.css`, `.tsx`, `.jsx`, `.svg`, or UI templates.
//      - Domain certifiers (`Ramanujan`, `Financial-Analyst`, `Legal-Beagle`, `Literature-Review`).
//   5. Disjoint-write-set `### Wave W.k` sub-wave partitioning when wave files partition cleanly.

import path from 'node:path';

export const APPROVAL_MAX_WORDS = 200;

const INTERNAL_PLUMBING_RE =
  /\b(?:schema(?:s)?|migration(?:s)?|ddl\b|typedef(?:s)?|types?[- ]only|interface(?:s)?[- ]only|scaffold(?:ing)?|boilerplate|plumbing|internal[- ](?:plumbing|types|state|helpers?|wiring)|stub(?:s)?[- ]only|wireframe[- ]free|config[- ]only|constants?[- ]only|data[- ]model[- ]only|directory[- ]layout)\b/i;

const USABLE_END_TO_END_SLICE_RE =
  /\b(?:end[- ]to[- ]end|e2e\b|pilot[- ]slice|usable[- ]slice|cli\b|command[- ]line|subcommand|interactive|render(?:s|ed|ing)?|mockup|chrome[- ]open|http\b|endpoint|route|serves?\b|prints?\b|outputs?\b|executes?\b|runnable|smoke[- ]test|user[- ](?:facing|visible|flow|journey)|bin\/[a-z0-9._-]+|--[a-z0-9-]+)\b/i;

const PLUMBING_ONLY_FILE_RE =
  /(?:^|\/)(?:schema|migrations?|types|interfaces|constants|config|plumbing|ddl|models)\b|\.(?:sql|prisma|graphql|d\.ts)$/i;

const USER_OR_CLI_SURFACE_FILE_RE =
  /(?:^|\/)(?:bin|cli|ui|views?|pages?|routes?|controllers?|app|public|frontend)\/|\.(?:html?|css|tsx|jsx|vue|svelte|svg)$/i;

function flattenWaveText(wave) {
  if (!wave || typeof wave !== 'object') return String(wave ?? '');
  const parts = [
    wave.title,
    wave.intent,
    Array.isArray(wave.deliverables) ? wave.deliverables.join(' ') : wave.deliverables,
    wave.doneWhen,
    wave.acceptance,
    Array.isArray(wave.gwt)
      ? wave.gwt.map((g) => `${g?.given ?? ''} ${g?.when ?? ''} ${g?.then ?? ''}`).join(' ')
      : '',
  ];
  return parts.filter(Boolean).join('\n');
}

function isWaveUsableSlice(wave) {
  if (!wave || typeof wave !== 'object') return false;
  if (wave.pilotSlice === true || wave.usableSlice === true) return true;
  if (wave.plumbingOnly === true) return false;

  const text = flattenWaveText(wave);
  const dels = Array.isArray(wave.deliverables) ? wave.deliverables.map(String) : [];
  const hasSurfaceFile = dels.some((d) => USER_OR_CLI_SURFACE_FILE_RE.test(d));
  const allPlumbingFiles = dels.length > 0 && dels.every((d) => PLUMBING_ONLY_FILE_RE.test(d));

  const hasUsableSignal = USABLE_END_TO_END_SLICE_RE.test(text) || hasSurfaceFile;
  const hasPlumbingSignal = INTERNAL_PLUMBING_RE.test(text) || allPlumbingFiles;

  if (allPlumbingFiles && !USABLE_END_TO_END_SLICE_RE.test(String(wave.doneWhen ?? ''))) {
    return false;
  }
  if (hasPlumbingSignal && !hasUsableSignal) {
    return false;
  }
  return hasUsableSignal || !hasPlumbingSignal;
}

/**
 * Chekhov Guard 1: Reject plans of `>= 3` waves where Wave 1 + Wave 2 deliver only
 * internal plumbing/schemas with zero end-to-end runnable/verifiable user or CLI slice,
 * unless `pilot_override_reason` is explicitly documented.
 */
export function checkWave1PilotSlice({ waves = [], plan = '', pilotOverrideReason = null } = {}) {
  const list = Array.isArray(waves) ? waves : [];
  const inlineOverride = String(plan ?? '').match(/pilot_override_reason\s*:\s*([^\r\n]+)/i);
  const override = (typeof pilotOverrideReason === 'string' && pilotOverrideReason.trim())
    ? pilotOverrideReason.trim()
    : (inlineOverride ? inlineOverride[1].trim() : null);

  if (list.length < 3) {
    return {
      pass: true,
      waveCount: list.length,
      overrideReason: override,
      detail: `plan has ${list.length} wave(s) (<3); pilot-slice rule satisfied`,
    };
  }
  if (override) {
    return {
      pass: true,
      waveCount: list.length,
      overrideReason: override,
      detail: `pilot_override_reason documented: ${override}`,
    };
  }

  const w1 = list[0];
  const w2 = list[1];
  const w1Usable = isWaveUsableSlice(w1);
  const w2Usable = isWaveUsableSlice(w2);

  if (!w1Usable && !w2Usable) {
    return {
      pass: false,
      waveCount: list.length,
      overrideReason: null,
      detail:
        `Chekhov Wave-1 Pilot-Slice Guard FAILED: plan has ${list.length} waves, and both Wave 1 ` +
        `("${w1?.title ?? 'Wave 1'}") and Wave 2 ("${w2?.title ?? 'Wave 2'}") deliver only internal ` +
        `plumbing/schemas with zero runnable end-to-end user or CLI slice. Reorder Wave 1 to deliver ` +
        `a thin runnable vertical pilot slice, or document an explicit \`pilot_override_reason:\`.`,
    };
  }

  return {
    pass: true,
    waveCount: list.length,
    overrideReason: null,
    pilotWave: w1Usable ? 1 : 2,
    detail: `usable end-to-end pilot slice present in Wave ${w1Usable ? 1 : 2}`,
  };
}

const UNBOUNDED_SERIAL_SPAWN_PATTERNS = [
  /\b(?:for\s+each|for\s+every|per[- ](?:item|chapter|file|row|record|page|document|doc|section|paragraph|scene|entity|paper|module|chunk)|loop(?:ing)?\s+over\s+(?:every|all|each)|serial(?:ly)?\s+(?:over|across|for\s+each))\b[^.\n]{0,140}\b(?:llm|model|agent|sub-?agent|spawn|prompt|invoke|claude|gemini|gpt|chatgpt|grok)\b/i,
  /\b(?:spawn|invoke|call|dispatch|run)\s+(?:an?\s+|one\s+)?(?:fresh\s+)?(?:llm|model|agent|sub-?agent|prompt)\b[^.\n]{0,140}\b(?:for\s+each|for\s+every|per[- ](?:item|chapter|file|row|record|page|document|doc|section|paragraph|scene|entity|paper|module))\b/i,
  /\bO\(\s*N\s*\)\s*(?:serial\s+)?(?:llm|model|agent|sub-?agent)\s*(?:calls?|spawns?)/i,
];

const BATCH_OR_CONCURRENCY_BOUND_RE =
  /\b(?:batch(?:ed|ing|es|[-_ ]?size)?|chunk(?:ed|ing)?|concurren(?:cy|t)|parallel(?:ism|ized)?|semaphore|worker[- ]pool|cap(?:ped)?\s*(?:at|to|=|:)?\s*\d+|max[-_ ]?(?:calls|spawns|concurrency|parallel|batches|workers)|bounded\s+(?:to|by)|<=\s*\d+\s*(?:calls?|spawns?|batches|concurrent)|\b\d+\s*(?:items?\s+per\s+batch|concurrent|in\s+parallel))\b/i;

/**
 * Chekhov Guard 2: Flag any wave/step proposing unbounded per-item / per-chapter / per-file
 * serial LLM spawns without batching or concurrency bounds.
 */
export function checkCallLatencyBudget({ waves = [], plan = '' } = {}) {
  const violations = [];
  const list = Array.isArray(waves) ? waves : [];

  list.forEach((w, idx) => {
    const body = flattenWaveText(w);
    const matched = UNBOUNDED_SERIAL_SPAWN_PATTERNS.find((re) => re.test(body));
    if (matched && !BATCH_OR_CONCURRENCY_BOUND_RE.test(body)) {
      violations.push({
        wave: Number.isInteger(w?.n) ? w.n : idx + 1,
        title: String(w?.title ?? `Wave ${idx + 1}`),
        reason: 'unbounded serial per-item/per-chapter/per-file LLM spawn without batching or concurrency cap',
      });
    }
  });

  if (violations.length === 0 && plan) {
    const paragraphs = String(plan).split(/\n\s*\n/);
    for (const para of paragraphs) {
      const matched = UNBOUNDED_SERIAL_SPAWN_PATTERNS.find((re) => re.test(para));
      if (matched && !BATCH_OR_CONCURRENCY_BOUND_RE.test(para)) {
        violations.push({
          wave: null,
          title: 'plan-body',
          reason: `unbounded serial O(N) LLM spawn in plan prose: "${para.trim().slice(0, 120)}"`,
        });
        break;
      }
    }
  }

  return {
    pass: violations.length === 0,
    violations,
    detail: violations.length === 0
      ? 'call/latency budget bounded (no unbounded per-item serial LLM spawns)'
      : `O(N) Call/Latency Budget Estimator flagged ${violations.length} unbounded serial LLM spawn(s): ` +
        violations.map((v) => `${v.wave ? `Wave ${v.wave} (${v.title})` : v.title}: ${v.reason}`).join('; '),
  };
}

/** Count whitespace-delimited words in a gate block. */
export function countWords(text) {
  const s = String(text ?? '').trim();
  if (!s) return 0;
  return s.split(/\s+/).filter(Boolean).length;
}

/**
 * Chekhov Guard 3a: Enforce `<= 200` words on human approval gate blocks (`ELEGANCE.md` Rule 1).
 */
export function checkApprovalBlockWordBudget(blockText, maxWords = APPROVAL_MAX_WORDS) {
  const words = countWords(blockText);
  return {
    pass: words <= maxWords,
    words,
    maxWords,
    detail: words <= maxWords
      ? `approval block is ${words}/${maxWords} words`
      : `approval block exceeds ELEGANCE.md Rule 1 budget (${words} > ${maxWords} words)`,
  };
}

/**
 * Extract deferred or cut scope in plain English (never silent scope omission).
 */
export function extractPlainEnglishScopeCuts({ deferredScope = [], grasscatcher = [], eleganceCuts = [] } = {}) {
  const items = [];
  for (const d of Array.isArray(deferredScope) ? deferredScope : [deferredScope]) {
    const s = typeof d === 'string' ? d.trim() : String(d?.title ?? d?.text ?? '').trim();
    if (s) items.push(s);
  }
  for (const g of Array.isArray(grasscatcher) ? grasscatcher : []) {
    const s = typeof g === 'string' ? g.trim() : String(g?.title ?? g?.summary ?? g?.idea ?? '').trim();
    if (s) items.push(s);
  }
  for (const c of Array.isArray(eleganceCuts) ? eleganceCuts : []) {
    const s = typeof c === 'string' ? c.trim() : String(c?.text ?? c?.id ?? '').trim();
    if (s) items.push(s);
  }
  const unique = [...new Set(items)];
  if (!unique.length) return 'Nothing cut from your requested scope.';
  return `Deferred/cut scope: ${unique.slice(0, 4).join('; ')}${unique.length > 4 ? ` (+${unique.length - 4} more on disk)` : ''}.`;
}

/**
 * Build a human approval gate block guaranteed `<= 200` words (`ELEGANCE.md` Rule 1 & Speaking Law),
 * explicitly naming deferred/cut scope in plain English and pointing to the artifact on disk.
 */
export function formatPlainEnglishApprovalGate({
  goal,
  recommendation = 'Approve and start the build.',
  tradeOff = 'Deferred items wait for a follow-up pass.',
  deferredScope = [],
  grasscatcher = [],
  eleganceCuts = [],
  artifactPath = 'IMPLEMENTATION-PLAN.md',
  portfolioGates = [],
  maxWords = APPROVAL_MAX_WORDS,
} = {}) {
  const cutsLine = extractPlainEnglishScopeCuts({ deferredScope, grasscatcher, eleganceCuts });
  const gateNames = Array.isArray(portfolioGates) && portfolioGates.length
    ? `Active verification gates: ${portfolioGates.map((g) => g.skill).join(', ')}.`
    : '';
  const rawParts = [
    `Goal: ${String(goal || 'deliver the locked North Star').trim().slice(0, 220)}`,
    cutsLine,
    gateNames,
    `Full plan on disk: ${artifactPath}.`,
    `Recommendation: ${String(recommendation).trim()} Trade-off: ${String(tradeOff).trim()}`,
    'Approve, edit, or tell me something else?',
  ].filter(Boolean);

  let text = rawParts.join(' ');
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length > maxWords) {
    const tail = ['Approve, edit, or tell me something else?'];
    const budget = Math.max(20, maxWords - countWords(tail[0]) - 2);
    text = `${words.slice(0, budget).join(' ')} … ${tail[0]}`;
  }
  return text;
}

const UI_TARGET_FILE_RE = /(?:^|[\s`'"(])([A-Za-z0-9_./\\-]+\.(?:html?|css|scss|tsx|jsx|vue|svelte))(?=$|[\s`'")\],;:])/gi;
const SVG_TARGET_FILE_RE = /(?:^|[\s`'"(])([A-Za-z0-9_./\\-]+\.svg)(?=$|[\s`'")\],;:])/gi;
const UI_TEMPLATE_RE = /\b(?:ui\s+template|jinja2?\s+template|handlebars|ejs|blade\.php|interactive\s+mockup|web\s+dashboard|browser\s+ui)\b/i;
const FIGURE_SIGNAL_RE = /\b(?:figure-designer|scientific\s+figure|architecture\s+diagram|multi-panel\s+figure|publication\s+figure)\b/i;

const CERTIFIER_RULES = Object.freeze([
  {
    id: 'ramanujan',
    skill: 'Ramanujan',
    pattern: /\b(?:ramanujan|theorem|lemma|formal\s+proof|mathematical\s+derivation|closed[- ]form|differential\s+equation|eigenvalue|jacobian|hessian|z3\b|lean\s*4?|symbolic\s+certif)/i,
    gateText: 'Ramanujan certifier gate: exact arithmetic / symbolic / z3 ground-equation check with earned honesty rung',
  },
  {
    id: 'financial-analyst',
    skill: 'Financial-Analyst',
    pattern: /\b(?:financial-analyst|cap[- ]?table|equity\s+waterfall|liquidation\s+preference|dcf\b|irr\b|npv\b|valuation\s+model|round[- ]comp|penny[- ]exact\s+tie[- ]out)/i,
    gateText: 'Financial-Analyst certifier gate: exact-Decimal Python/Excel dependency-graph tie-out (zero float drift)',
  },
  {
    id: 'legal-beagle',
    skill: 'Legal-Beagle',
    pattern: /\b(?:legal-beagle|contract\s+clause|indemnification|fiduciary\s+duty|regulatory\s+compliance|case[- ]law|statut(?:e|ory)|governing\s+law|nda\b|msa\b)/i,
    gateText: 'Legal-Beagle certifier gate: jurisdiction + date established and zero uncited case-law/statute claims',
  },
  {
    id: 'literature-review',
    skill: 'Literature-Review',
    pattern: /\b(?:literature-review|systematic\s+review|multi[- ]paper\s+synthesis|prisma\b|snowball\s+search|citation\s+matrix|meta[- ]analysis)/i,
    gateText: 'Literature-Review certifier gate: PRISMA flow + deterministic primary-source quote grounding',
  },
]);

function collectMatches(re, haystack) {
  const out = new Set();
  const clone = new RegExp(re.source, re.flags);
  let m;
  while ((m = clone.exec(haystack)) !== null) {
    if (m[1]) out.add(m[1]);
  }
  return [...out];
}

/**
 * Detect UI/Figure mockup gates and portfolio domain certifier gates from planned write targets and text.
 */
export function detectPortfolioSkillGates({ intent = '', northStar = '', plan = '', waves = [] } = {}) {
  const waveBlob = (Array.isArray(waves) ? waves : []).map(flattenWaveText).join('\n');
  const targetBlob = `${plan}\n${waveBlob}`;
  const fullBlob = `${intent}\n${northStar}\n${targetBlob}`;

  const uiFiles = collectMatches(UI_TARGET_FILE_RE, targetBlob);
  const svgFiles = collectMatches(SVG_TARGET_FILE_RE, targetBlob);
  const hasUiTemplate = UI_TEMPLATE_RE.test(targetBlob);
  const hasFigureSignal = FIGURE_SIGNAL_RE.test(fullBlob);

  const gates = [];

  if (uiFiles.length > 0 || hasUiTemplate) {
    gates.push({
      id: 'ui-chrome-mockup',
      skill: 'Chrome-UI-Mockup',
      waveTarget: 1,
      matchedTargets: uiFiles,
      gateText:
        'Wave-1 Interactive Chrome Mockup gate: launch preview via `python <path> chrome-open <url> --new-window` ' +
        'and visually inspect layout/states via `python <path> look` before downstream UI waves',
    });
  }

  if (svgFiles.length > 0 || hasFigureSignal) {
    gates.push({
      id: 'figure-designer',
      skill: 'Figure-Designer',
      waveTarget: 1,
      matchedTargets: svgFiles,
      gateText:
        'Wave-1 Figure-Designer gate: apply `Figure-Designer` visual hierarchy/encoding check and inspect rendered figure via ' +
        '`python <path> chrome-open <svg/html> --new-window` + `ft.py look`',
    });
  }

  for (const rule of CERTIFIER_RULES) {
    if (rule.pattern.test(fullBlob)) {
      gates.push({
        id: rule.id,
        skill: rule.skill,
        waveTarget: 'domain',
        matchedTargets: [],
        gateText: rule.gateText,
      });
    }
  }

  return gates;
}

/**
 * Attach detected UI/Figure Wave-1 mockup gates and domain certifier gates onto structured waves idempotently.
 */
export function attachPortfolioSkillGates(waves = [], gates = []) {
  const src = Array.isArray(waves) ? waves : [];
  if (!src.length || !Array.isArray(gates) || !gates.length) return src.map((w) => ({ ...w }));

  const out = src.map((w) => ({
    ...w,
    skillGates: Array.isArray(w?.skillGates) ? [...w.skillGates] : [],
  }));

  for (const gate of gates) {
    if (gate.waveTarget === 1) {
      const w1 = out[0];
      if (!w1.skillGates.includes(gate.skill)) w1.skillGates.push(gate.skill);
      if (!String(w1.doneWhen || '').includes('ft.py chrome-open')) {
        w1.doneWhen = `${String(w1.doneWhen || '').trim()}; ${gate.gateText}`;
      }
      continue;
    }
    // Domain certifiers attach to the wave matching the domain pattern, or the final wave as certifier sign-off.
    const rule = CERTIFIER_RULES.find((r) => r.id === gate.id);
    let idx = rule ? out.findIndex((w) => rule.pattern.test(flattenWaveText(w))) : -1;
    if (idx < 0) idx = out.length - 1;
    const target = out[idx];
    if (!target.skillGates.includes(gate.skill)) target.skillGates.push(gate.skill);
    if (!String(target.doneWhen || '').toLowerCase().includes(gate.skill.toLowerCase())) {
      target.doneWhen = `${String(target.doneWhen || '').trim()}; ${gate.gateText}`;
    }
  }

  return out;
}

const FILE_LIKE_RE = /^(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+$|^[A-Za-z0-9_.-]+\.(?:mjs|cjs|js|ts|tsx|jsx|py|json|md|html|css|svg|sql|toml|yaml|yml)$/i;

/**
 * Deterministically partition a wave's deliverables into `### Wave W.k` disjoint-write-set
 * sub-waves when `>= 2` file groups have strictly disjoint write paths.
 */
export function partitionDisjointSubWaves(wave, waveNumber = null) {
  const wNum = Number.isInteger(waveNumber) ? waveNumber : (Number.isInteger(wave?.n) ? wave.n : 1);
  if (Array.isArray(wave?.subWaves) && wave.subWaves.length >= 2) {
    return wave.subWaves;
  }
  const dels = Array.isArray(wave?.deliverables) ? wave.deliverables.map((d) => String(d ?? '').trim()).filter(Boolean) : [];
  const fileItems = dels
    .map((raw) => {
      const token = raw.split(/\s+[—–-]\s+|\s+:\s+/)[0].replace(/^[`'"(]+|[`'")\],;:]+$/g, '');
      return FILE_LIKE_RE.test(token) ? token.replace(/\\/g, '/') : null;
    })
    .filter(Boolean);

  const uniqueFiles = [...new Set(fileItems)];
  if (uniqueFiles.length < 2) return [];

  const byBucket = new Map();
  for (const f of uniqueFiles) {
    const dir = path.posix.dirname(f);
    const bucket = dir === '.' ? `root:${path.posix.basename(f, path.posix.extname(f))}` : dir.split('/').slice(0, 2).join('/');
    if (!byBucket.has(bucket)) byBucket.set(bucket, []);
    byBucket.get(bucket).push(f);
  }

  if (byBucket.size < 2) return [];

  // Verify strict pairwise file disjointness across buckets (guaranteed by uniqueFiles, double-checked).
  const seen = new Set();
  const subWaves = [];
  let k = 1;
  for (const [bucket, files] of byBucket.entries()) {
    if (files.some((f) => seen.has(f))) return [];
    files.forEach((f) => seen.add(f));
    const label = bucket.startsWith('root:') ? bucket.slice(5) : bucket;
    subWaves.push({
      id: `${wNum}.${k}`,
      title: `${label} slice`,
      writeSet: files,
      doneWhen: `${files.join(', ')} implemented and passing ${wave?.doneWhen ? `(${String(wave.doneWhen).slice(0, 120)})` : 'wave tests'}`,
    });
    k += 1;
  }
  return subWaves;
}

/**
 * Run all deterministic Chekhov plan-quality guards + portfolio skill detection in one pass.
 */
export function runChekhovPlanQualityLint({
  plan = '',
  waves = [],
  intent = '',
  northStar = '',
  deferredScope = [],
  grasscatcher = [],
  eleganceCuts = [],
  pilotOverrideReason = null,
  gateBlock = null,
} = {}) {
  const pilotSlice = checkWave1PilotSlice({ waves, plan, pilotOverrideReason });
  const callBudget = checkCallLatencyBudget({ waves, plan });
  const wordBudget = gateBlock != null ? checkApprovalBlockWordBudget(gateBlock) : { pass: true, words: 0, maxWords: APPROVAL_MAX_WORDS, detail: 'no gateBlock supplied' };
  const portfolioGates = detectPortfolioSkillGates({ intent, northStar, plan, waves });
  const deferredScopeText = extractPlainEnglishScopeCuts({ deferredScope, grasscatcher, eleganceCuts });

  const issues = [];
  if (!pilotSlice.pass) issues.push(pilotSlice.detail);
  if (!callBudget.pass) issues.push(callBudget.detail);
  if (!wordBudget.pass) issues.push(wordBudget.detail);

  return {
    pass: issues.length === 0,
    pilotSlice,
    callBudget,
    wordBudget,
    deferredScopeText,
    portfolioGates,
    issues,
  };
}
