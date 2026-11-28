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
    fileHintRe: /(?:math|proof|solver|symbolic|certif|matrix|eigen|jacobian|hessian|z3|lean|theorem|formula)/i,
    gateText: 'Ramanujan certifier gate: exact arithmetic / symbolic / z3 ground-equation check with earned honesty rung',
  },
  {
    id: 'financial-analyst',
    skill: 'Financial-Analyst',
    pattern: /\b(?:financial-analyst|cap[- ]?table|equity\s+waterfall|liquidation\s+preference|dcf\b|irr\b|npv\b|valuation\s+model|round[- ]comp|penny[- ]exact\s+tie[- ]out)/i,
    fileHintRe: /(?:waterfall|valuation|captable|cap[-_]?table|dcf|irr|npv|finance|financial|ledger|decimal)/i,
    gateText: 'Financial-Analyst certifier gate: exact-Decimal Python/Excel dependency-graph tie-out (zero float drift)',
  },
  {
    id: 'legal-beagle',
    skill: 'Legal-Beagle',
    pattern: /\b(?:legal-beagle|contract\s+clause|indemnification|fiduciary\s+duty|regulatory\s+compliance|case[- ]law|statut(?:e|ory)|governing\s+law|nda\b|msa\b)/i,
    fileHintRe: /(?:legal|contract|clause|compliance|nda|msa|indemn|statut|policy|trust)/i,
    gateText: 'Legal-Beagle certifier gate: jurisdiction + date established and zero uncited case-law/statute claims',
  },
  {
    id: 'literature-review',
    skill: 'Literature-Review',
    pattern: /\b(?:literature-review|systematic\s+review|multi[- ]paper\s+synthesis|prisma\b|snowball\s+search|citation\s+matrix|meta[- ]analysis)/i,
    fileHintRe: /(?:prisma|snowball|citation|literature|bibliography|corpus|meta[-_]?analysis|papers?)/i,
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

function selectOwningCertifierWaveIndex(waves = [], rule) {
  if (!Array.isArray(waves) || waves.length === 0 || !rule) return -1;
  const FORWARD_REF_RE = /\b(?:before\s+wave\s+\d+|prepared?\s+for\s+wave\s+\d+|deferred\s+to\s+wave\s+\d+|later\s+in\s+wave\s+\d+)\b/i;
  let bestIdx = -1;
  let bestScore = 0;

  waves.forEach((w, idx) => {
    const dels = [
      ...(Array.isArray(w?.deliverables) ? w.deliverables : [w?.deliverables]),
      ...(Array.isArray(w?.files) ? w.files : []),
      ...(Array.isArray(w?.writes) ? w.writes : []),
    ].filter(Boolean).join(' ');
    const gwtText = Array.isArray(w?.gwt)
      ? w.gwt.map((g) => `${g?.given ?? ''} ${g?.when ?? ''} ${g?.then ?? ''}`).join(' ')
      : '';
    const ownedSurface = `${w?.title ?? ''}\n${dels}\n${w?.doneWhen ?? ''}\n${gwtText}`;
    const fullWave = flattenWaveText(w);

    let score = 0;
    if (rule.fileHintRe && dels && rule.fileHintRe.test(dels)) score += 6;
    if (dels && rule.pattern.test(dels)) score += 5;
    if (w?.title && rule.pattern.test(String(w.title))) score += 4;
    if (ownedSurface && rule.pattern.test(ownedSurface)) score += 3;
    if (fullWave && rule.pattern.test(fullWave)) {
      score += FORWARD_REF_RE.test(String(w?.intent ?? '')) && score === 0 ? 0.5 : 1;
    }

    if (score > bestScore) {
      bestScore = score;
      bestIdx = idx;
    }
  });

  return bestScore > 0 ? bestIdx : waves.length - 1;
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
    const why = uiFiles.length ? `UI targets (${uiFiles.slice(0, 3).join(', ')})` : 'interactive UI template surface';
    gates.push({
      id: 'ui-chrome-mockup',
      skill: 'Chrome-UI-Mockup',
      waveTarget: 1,
      matchedTargets: uiFiles,
      neededBecause: `Needed-because: ${why} requires rendered visual verification per ELEGANCE Rule 6`,
      gateText:
        'Wave-1 Interactive Chrome Mockup gate: launch preview via `python <path> chrome-open <url> --new-window` ' +
        'and visually inspect layout/states via `python <path> look` before downstream UI waves',
    });
  }

  if (svgFiles.length > 0 || hasFigureSignal) {
    const why = svgFiles.length ? `figure targets (${svgFiles.slice(0, 3).join(', ')})` : 'scientific/architectural figure surface';
    gates.push({
      id: 'figure-designer',
      skill: 'Figure-Designer',
      waveTarget: 1,
      matchedTargets: svgFiles,
      neededBecause: `Needed-because: ${why} requires Figure-Designer encoding & visual inspection`,
      gateText:
        'Wave-1 Figure-Designer gate: apply `Figure-Designer` visual hierarchy/encoding check and inspect rendered figure via ' +
        '`python <path> chrome-open <svg/html> --new-window` + `ft.py look`',
    });
  }

  for (const rule of CERTIFIER_RULES) {
    const m = rule.pattern.exec(fullBlob);
    if (m) {
      gates.push({
        id: rule.id,
        skill: rule.skill,
        waveTarget: 'domain',
        matchedTargets: [m[0]],
        neededBecause: `Needed-because: plan domain signal "${m[0]}" requires ${rule.skill} deterministic/honesty certification`,
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
    const whySuffix = gate.neededBecause ? ` (${gate.neededBecause})` : '';
    if (gate.waveTarget === 1) {
      const ruleAsUi = gate.id === 'figure-designer'
        ? { pattern: FIGURE_SIGNAL_RE, fileHintRe: /\.svg\b/i }
        : { pattern: UI_TEMPLATE_RE, fileHintRe: /\.(?:html?|css|scss|tsx|jsx|vue|svelte)\b/i };
      const uiOwnerIdx = selectOwningCertifierWaveIndex(out, ruleAsUi);
      const targetWave = out[uiOwnerIdx >= 0 && gate.matchedTargets?.length ? uiOwnerIdx : 0];
      if (!targetWave.skillGates.includes(gate.skill)) targetWave.skillGates.push(gate.skill);
      if (!String(targetWave.doneWhen || '').includes('ft.py chrome-open')) {
        targetWave.doneWhen = `${String(targetWave.doneWhen || '').trim()}; ${gate.gateText}${whySuffix}`;
      }
      continue;
    }
    // Journal 0126 fix: attach domain certifiers to the wave OWNING the domain deliverables/surface,
    // never blindly to Wave 1 when Wave 1 merely forward-references a downstream wave in prose.
    const rule = CERTIFIER_RULES.find((r) => r.id === gate.id);
    const idx = selectOwningCertifierWaveIndex(out, rule);
    const target = out[idx >= 0 ? idx : out.length - 1];
    if (!target.skillGates.includes(gate.skill)) target.skillGates.push(gate.skill);
    if (!String(target.doneWhen || '').toLowerCase().includes(gate.skill.toLowerCase())) {
      target.doneWhen = `${String(target.doneWhen || '').trim()}; ${gate.gateText}${whySuffix}`;
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

export const MONOLITH_FREEZE_LINES = 1500;
export const MONOLITH_MAX_ADAPTER_DELTA_LINES = 180;
export const WAVE_DONE_WHEN_MAX_WORDS = 360;

const STRIP_INJECTED_GATE_SUFFIX_RE = /;\s*(?:Wave-1\s+(?:Interactive Chrome Mockup|Figure-Designer)\s+gate:|Ramanujan\s+math\/domain\s+gate:|Financial-Analyst\s+gate:|Legal-Beagle\s+gate:|Literature-Review\s+gate:)[\s\S]*$/i;

function extractDeliverablePaths(deliverables = []) {
  const list = Array.isArray(deliverables) ? deliverables : [];
  const out = [];
  for (const raw of list) {
    const s = String(raw ?? '').trim();
    if (!s) continue;
    const colonIdx = s.lastIndexOf(': ');
    const cand = (colonIdx >= 0 ? s.slice(colonIdx + 2) : s.split(/\s+[—–-]\s+/)[0])
      .replace(/^[`'"(]+|[`'")\],;:]+$/g, '')
      .replace(/^Test\s+file\s+/i, '')
      .trim()
      .replace(/\\/g, '/');
    if (cand && (FILE_LIKE_RE.test(cand) || /[a-z0-9_.-]+\/[a-z0-9_.-]+\.[a-z0-9]+$/i.test(cand))) {
      out.push(cand.replace(/^\.\//, ''));
    }
  }
  return [...new Set(out)];
}

function extractDirectiveReason(text, key) {
  const escaped = String(key).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`^\\s*(?:[-*>]\\s*)?(?:\\*\\*)?${escaped}(?:\\*\\*)?\\s*:\\s*(?!\`)([^\`\\r\\n]{6,})$`, 'im');
  const m = String(text ?? '').match(re);
  if (!m) return null;
  const val = m[1].trim();
  if (!val || /^if\s+(?:coexistence|needed|required)\b/i.test(val)) return null;
  return val;
}

/**
 * Chekhov Guard 4 (Gandalf journal 0402 — Anti-Bloat & Monolith-Freeze Gate):
 * - Any wave touching an existing monolith (>1,500 lines) must ALSO declare a focused
 *   non-test companion module deliverable (keeping monolith edits <=180 net adapter lines)
 *   OR document an explicit `monolith_override_reason:`.
 * - Optionally bounds raw per-wave `doneWhen` prose (<=360 words before injected gates)
 *   so Shark revisions replace weak clauses rather than concatenating unbounded checklists.
 */
export function checkMonolithAndContractBudget({
  waves = [],
  plan = '',
  monoliths = [],
  monolithOverrideReason = null,
  enforceProseBudget = false,
  maxDoneWhenWords = WAVE_DONE_WHEN_MAX_WORDS,
} = {}) {
  const inlineOverride = extractDirectiveReason(plan, 'monolith_override_reason');
  const override = (typeof monolithOverrideReason === 'string' && monolithOverrideReason.trim())
    ? monolithOverrideReason.trim()
    : inlineOverride;

  const monolithMap = new Map();
  for (const m of monoliths || []) {
    if (!m) continue;
    const p = String(typeof m === 'string' ? m : (m.path || m.file || '')).replace(/\\/g, '/').replace(/^\.\//, '');
    const lines = typeof m === 'object' && Number.isFinite(m.lines) ? m.lines : MONOLITH_FREEZE_LINES + 1;
    if (p && lines > MONOLITH_FREEZE_LINES) monolithMap.set(p.toLowerCase(), { path: p, lines });
  }

  const violations = [];
  const list = Array.isArray(waves) ? waves : [];

  list.forEach((w, idx) => {
    const wNum = w?.n ?? idx + 1;
    const paths = extractDeliverablePaths(w?.deliverables);
    if (!override && monolithMap.size > 0 && paths.length > 0) {
      const touchedMonoliths = paths.filter((p) => monolithMap.has(p.toLowerCase()));
      if (touchedMonoliths.length > 0) {
        const companionModules = paths.filter((p) => {
          const low = p.toLowerCase();
          if (monolithMap.has(low)) return false;
          if (/(^|\/)tests?\//i.test(low) || /(^|\/)test_[^/]*\.py$/i.test(low) || /\.(?:test|spec)\.[a-z]+$/i.test(low)) return false;
          if (/\.(?:json|md|txt|ya?ml|toml)$/i.test(low)) return false;
          if (/^vendor\//i.test(low)) return false;
          return true;
        });
        if (companionModules.length === 0) {
          const desc = touchedMonoliths.map((p) => {
            const info = monolithMap.get(p.toLowerCase());
            return `${info.path} (${info.lines} lines)`;
          }).join(', ');
          violations.push(
            `Wave ${wNum} touches frozen monolith(s) >${MONOLITH_FREEZE_LINES} lines [${desc}] without declaring a focused companion module deliverable (<600 lines, keeping monolith adapter glue <=${MONOLITH_MAX_ADAPTER_DELTA_LINES} net lines) or an explicit \`monolith_override_reason:\`.`,
          );
        }
      }
    }

    if (enforceProseBudget && !extractDirectiveReason(plan, 'prose_budget_override')) {
      const rawDoneWhen = String(w?.doneWhen ?? '').replace(STRIP_INJECTED_GATE_SUFFIX_RE, '').trim();
      const words = rawDoneWhen ? rawDoneWhen.split(/\s+/).filter(Boolean).length : 0;
      if (words > maxDoneWhenWords) {
        violations.push(
          `Wave ${wNum} doneWhen prose is ${words} words (cap ${maxDoneWhenWords}); replace redundant clauses instead of appending Shark checklists.`,
        );
      }
    }
  });

  return {
    pass: violations.length === 0,
    overrideReason: override,
    violations,
    detail: violations.length === 0
      ? 'monolith-freeze & contract prose budgets satisfied'
      : `Chekhov Anti-Bloat Budget FAILED: ${violations.join(' | ')}`,
  };
}

/**
 * Chekhov Guard 5 (Gandalf Anti-Bloat — Reuse-Before-Write & Sunset-Old-Version Gate):
 * - Reuse-Before-Write: when the repository already exports canonical lock / atomic-write /
 *   path-containment helpers (`reusablePrimitives`), blocks waves that re-implement bespoke
 *   lock/atomic-write boilerplate without importing/reusing an existing helper module or
 *   declaring `reuse_override_reason:`.
 * - Sunset-Old-Version: when `intent`/`northStar` builds a newer `vN` (`N >= 2`) in a repo
 *   that already carries `v1..v(N-1)` files/symbols (`versionedLayers`), requires the plan
 *   to name superseded legacy shims to retire/consolidate or declare `sunset_override_reason:`.
 */
export function checkReuseAndSunsetDiscipline({
  waves = [],
  plan = '',
  intent = '',
  northStar = '',
  reusablePrimitives = [],
  versionedLayers = [],
  reuseOverrideReason = null,
  sunsetOverrideReason = null,
} = {}) {
  const planStr = String(plan ?? '');
  const inlineReuseOverride = extractDirectiveReason(planStr, 'reuse_override_reason');
  const effectiveReuseOverride = (typeof reuseOverrideReason === 'string' && reuseOverrideReason.trim())
    ? reuseOverrideReason.trim()
    : inlineReuseOverride;

  const inlineSunsetOverride = extractDirectiveReason(planStr, 'sunset_override_reason');
  const effectiveSunsetOverride = (typeof sunsetOverrideReason === 'string' && sunsetOverrideReason.trim())
    ? sunsetOverrideReason.trim()
    : inlineSunsetOverride;

  const violations = [];
  const list = Array.isArray(waves) ? waves : [];

  // 5a. Reuse-Before-Write check
  const prims = (Array.isArray(reusablePrimitives) ? reusablePrimitives : [])
    .map((p) => {
      if (!p) return null;
      if (typeof p === 'string') {
        const clean = p.replace(/\\/g, '/').replace(/^\.\//, '');
        const stem = path.posix.basename(clean, path.posix.extname(clean));
        return { path: clean, stem, exports: [] };
      }
      const clean = String(p.path || p.file || '').replace(/\\/g, '/').replace(/^\.\//, '');
      if (!clean) return null;
      const stem = path.posix.basename(clean, path.posix.extname(clean));
      return { path: clean, stem, exports: Array.isArray(p.exports) ? p.exports.map(String) : [] };
    })
    .filter(Boolean);

  if (!effectiveReuseOverride && prims.length > 0) {
    const BESPOKE_INFRA_RE = /\b(?:re-?implement|implement|write|build|create|define)\b[^.;\n]{0,90}\b(?:exclusive[_\s-]?file[_\s-]?lock|atomic[_\s-]?write(?:_json)?|msvcrt\.locking|fcntl\.flock|bespoke\s+lock|custom\s+file\s+lock)\b|\b(?:msvcrt\.locking|fcntl\.flock)\b/i;
    list.forEach((w, idx) => {
      const wNum = w?.n ?? idx + 1;
      const waveText = flattenWaveText(w);
      if (!BESPOKE_INFRA_RE.test(waveText)) return;
      const delPaths = extractDeliverablePaths(w?.deliverables).map((d) => d.toLowerCase());
      const touchesExistingPrim = prims.some((p) => delPaths.includes(p.path.toLowerCase()));
      if (touchesExistingPrim) return;
      const citesExistingPrim = prims.some((p) => {
        const pathMentioned = waveText.toLowerCase().includes(p.path.toLowerCase());
        const stemRe = p.stem.length >= 3
          ? new RegExp(`\\b(?:reuse|import|from|use|via|shared)\\b[^.;\\n]{0,60}\\b${p.stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b|\\b${p.stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\.(?:py|m?js|ts)\\b`, 'i')
          : null;
        return pathMentioned || Boolean(stemRe && stemRe.test(waveText));
      });
      if (!citesExistingPrim) {
        const sample = prims.slice(0, 4).map((p) => (p.exports.length ? `${p.path} (${p.exports.slice(0, 3).join(', ')})` : p.path)).join(', ');
        violations.push(
          `Wave ${wNum} proposes bespoke file-lock / atomic-write boilerplate instead of importing existing repo helper(s) [${sample}] (or declaring \`reuse_override_reason:\`).`,
        );
      }
    });
  }

  // 5b. Sunset-Old-Version check (vN replaces v1..v(N-1))
  const layers = (Array.isArray(versionedLayers) ? versionedLayers : []).map((x) => String(x || '').trim()).filter(Boolean);
  if (!effectiveSunsetOverride && layers.length > 0) {
    const goalText = `${intent || ''}\n${northStar || ''}`;
    const targetVerMatches = [...goalText.matchAll(/\bv(\d{1,2})\b/gi)].map((m) => Number(m[1])).filter((n) => n >= 2);
    const targetVer = targetVerMatches.length ? Math.max(...targetVerMatches) : 0;
    if (targetVer >= 2) {
      const legacyVers = new Set();
      for (const l of layers) {
        for (const m of l.matchAll(/(?:^|[/_.-])v(\d{1,2})(?:[/_.:-]|$)/gi)) {
          const v = Number(m[1]);
          if (v >= 1 && v < targetVer) legacyVers.add(v);
        }
      }
      if (legacyVers.size > 0) {
        const combinedPlanAndWaves = `${planStr}\n${list.map(flattenWaveText).join('\n')}`;
        const hasSunsetAction = /\b(?:sunset|retire|remove|delete|strip|deprecate|consolidate|supersede|sunset_plan|sunset_targets)\b/i.test(combinedPlanAndWaves);
        const namesLegacyTarget = [...legacyVers].some((v) => new RegExp(`\\bv${v}\\b`, 'i').test(combinedPlanAndWaves))
          || layers.some((l) => {
            const base = path.posix.basename(l.split(':')[0].replace(/\\/g, '/'));
            return base && combinedPlanAndWaves.toLowerCase().includes(base.toLowerCase());
          });
        if (!(hasSunsetAction && namesLegacyTarget)) {
          const legacyLabel = [...legacyVers].sort((a, b) => a - b).map((v) => `v${v}`).join('/');
          violations.push(
            `Plan targets v${targetVer} while repo carries legacy ${legacyLabel} layer(s) [${layers.slice(0, 4).join(', ')}] without naming superseded shims to retire/consolidate (or declaring \`sunset_override_reason:\` when coexistence is required).`,
          );
        }
      }
    }
  }

  return {
    pass: violations.length === 0,
    reuseOverrideReason: effectiveReuseOverride,
    sunsetOverrideReason: effectiveSunsetOverride,
    violations,
    detail: violations.length === 0
      ? 'reuse-before-write & version-sunset discipline satisfied'
      : `Chekhov Reuse/Sunset Guard FAILED: ${violations.join(' | ')}`,
  };
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
  monoliths = [],
  monolithOverrideReason = null,
  enforceProseBudget = false,
  reusablePrimitives = [],
  versionedLayers = [],
  reuseOverrideReason = null,
  sunsetOverrideReason = null,
  gateBlock = null,
} = {}) {
  const pilotSlice = checkWave1PilotSlice({ waves, plan, pilotOverrideReason });
  const callBudget = checkCallLatencyBudget({ waves, plan });
  const wordBudget = gateBlock != null ? checkApprovalBlockWordBudget(gateBlock) : { pass: true, words: 0, maxWords: APPROVAL_MAX_WORDS, detail: 'no gateBlock supplied' };
  const monolithBudget = checkMonolithAndContractBudget({
    waves,
    plan,
    monoliths,
    monolithOverrideReason,
    enforceProseBudget,
  });
  const reuseSunset = checkReuseAndSunsetDiscipline({
    waves,
    plan,
    intent,
    northStar,
    reusablePrimitives,
    versionedLayers,
    reuseOverrideReason,
    sunsetOverrideReason,
  });
  const portfolioGates = detectPortfolioSkillGates({ intent, northStar, plan, waves });
  const deferredScopeText = extractPlainEnglishScopeCuts({ deferredScope, grasscatcher, eleganceCuts });

  const issues = [];
  if (!pilotSlice.pass) issues.push(pilotSlice.detail);
  if (!callBudget.pass) issues.push(callBudget.detail);
  if (!wordBudget.pass) issues.push(wordBudget.detail);
  if (!monolithBudget.pass) issues.push(monolithBudget.detail);
  if (!reuseSunset.pass) issues.push(reuseSunset.detail);

  return {
    pass: issues.length === 0,
    pilotSlice,
    callBudget,
    wordBudget,
    monolithBudget,
    reuseSunset,
    deferredScopeText,
    portfolioGates,
    issues,
  };
}
