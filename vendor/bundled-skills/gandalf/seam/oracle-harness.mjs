// Gandalf advisor — the ADVISORY elevation-oracle HARNESS + fixture-construction TOOLING (Wave 8).
//
// This is the INSTRUMENT that the NS5 "elevates, not merely critique" claim is EVENTUALLY proven
// with (the RULING — feasibility, calibration ICC, the A/B SHIP/UNPROVEN verdict — is H1/H2, never
// here). By assignment it is ADVISORY (PRINCIPLE-D): it is recorded as an artifact a human reads
// and is NEVER part of the deterministic Foreman gate (`node --test test/*.test.mjs`). The proof
// of that isolation is structural — `test/harness.mjs`'s static import closure does NOT reach this
// module (its companion test asserts exactly that, the same way Wave 7 proved it for seam/oracle.mjs).
//
// What this module owns (all deterministic, all unit-tested), composing the cross-family judge
// ADAPTER (seam/oracle.mjs) into the paired bias-robust A/B harness the dive specified:
//   • `elevations.jsonl` fixture-construction TOOLING — mint / validate / (de)serialize the
//     must-anticipate / must-situate fixtures with their real-history answer keys, with the
//     "weak panel / retrodiction arms are NEVER pooled" guard made machine-checkable.
//   • PER-PILLAR BINDING BASELINES — SITUATE's binding baseline = the abstraction-equipped
//     direct-researchPrime arm; ANTICIPATE's = diagnose-core + a generic-premortem prompt (so each
//     pillar's added value is measured, never pooled).
//   • POSITION-SWAP-WITH-AGREEMENT — present each pair in both orders; a decision counts only when
//     both orders agree (otherwise it is position bias → no decision).
//   • LENGTH-CONTROL — flag a length confound so a verbosity-driven verdict can be discarded.
//   • ANSWER-KEY SCORER — elevate_recall (a LOWER bound) + the paired FALSE-ELEVATION precision
//     guard, scored deterministically against the fixture's answer key.
//   • CAT SECONDARY — the Consensual-Assessment-Technique novelty × usefulness secondary score.
//   • `evaluateFixture(..)` — composes all of the above into ONE advisory, NON-GATING A/B artifact.
//
// EXPLICIT SCOPE BOUNDARY (Wave 8 done-when): this file builds the harness CODE and proves its
// LOGIC is correct on synthetic fixtures with known answer keys. It emits NO feasibility verdict,
// NO calibration ICC ruling, and NO SHIP/UNPROVEN advisory — those require real-history fixtures
// and a human-dual-scored calibration and are owned by the HALT-gated increments H1/H2. Every
// artifact this module returns is stamped `advisory:true, gating:false`.
//
// Public surface:
//   ORACLE_HARNESS_KIND                          — the advisory harness artifact marker
//   ELEVATION_PILLARS                            — the two measured pillars (situate, anticipate)
//   BINDING_BASELINES / bindingBaselineFor(p)    — the per-pillar binding baseline arm
//   NON_POOLABLE_ARMS / isPoolableArm(arm)       — the weak-panel/retrodiction non-pooling guard
//   buildElevationFixture(spec)                  — mint a validated elevations.jsonl fixture record
//   toJsonl(fixtures) / parseJsonl(text)         — (de)serialize the fixture set, round-trip safe
//   POSITION_VERDICTS / positionSwapWithAgreement(..) — bias-robust paired decision
//   lengthControl(textA, textB, opts)            — the length-confound control
//   scoreAnswerKey(response, answerKey)          — elevate_recall + false-elevation precision guard
//   catSecondary(scores)                         — CAT novelty × usefulness secondary
//   evaluateFixture(args)                         — compose one advisory, NON-GATING A/B artifact

// --- self-contained helpers (the seam imports only the advisory cross-family judge adapter) -----
function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}
function isObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}
function uniqueStrings(arr) {
  return [...new Set((Array.isArray(arr) ? arr : []).filter(isNonEmptyString).map((s) => s.trim()))];
}

/** The advisory elevation-oracle harness artifact marker (stamped on every artifact this returns). */
export const ORACLE_HARNESS_KIND = 'advisory-elevation-oracle-harness';

// === the two measured pillars + their PER-PILLAR BINDING BASELINES =============================
/** The two pillars whose added value the oracle measures SEPARATELY (never pooled): clause-2
 *  SITUATE and clause-3 ANTICIPATE. */
export const ELEVATION_PILLARS = ['situate', 'anticipate'];

/** The BINDING baseline arm each pillar must beat (the dive's self-disproof, owned): SITUATE must
 *  beat the abstraction-equipped direct-researchPrime arm; ANTICIPATE must beat diagnose-core +
 *  a generic premortem. (A cheap baseline, not a strawman — otherwise the pillar's value is
 *  unmeasured.) */
export const BINDING_BASELINES = Object.freeze({
  situate: 'abstraction-equipped-direct-researchprime',
  anticipate: 'diagnose-core-plus-generic-premortem',
});

/** The binding baseline arm for a pillar. Throws on an unknown pillar (a fixture's pillar must be
 *  one of ELEVATION_PILLARS — there is no default baseline). */
export function bindingBaselineFor(pillar) {
  if (!ELEVATION_PILLARS.includes(pillar)) {
    throw new Error(`oracle-harness: unknown pillar ${JSON.stringify(pillar)} — expected one of [${ELEVATION_PILLARS.join(', ')}]`);
  }
  return BINDING_BASELINES[pillar];
}

// === the NON-POOLING guard (weak panel / retrodiction arms are NEVER pooled) ====================
/** Arms that are too weak to be pooled into the headline A/B (the dive: "weak panel / retrodiction
 *  arms NEVER pooled"). A fixture or comparison drawn from these arms may be recorded, but the
 *  harness refuses to fold it into a pooled effect estimate. */
export const NON_POOLABLE_ARMS = ['weak-panel', 'retrodiction', 'weak_panel'];

/** Predicate: may `arm` be pooled into the headline effect estimate? FALSE for the weak-panel /
 *  retrodiction arms. Pure; never throws. */
export function isPoolableArm(arm) {
  if (!isNonEmptyString(arm)) return false;
  return !NON_POOLABLE_ARMS.includes(arm.trim().toLowerCase());
}

// === `elevations.jsonl` fixture-construction TOOLING ==========================================
/** Mint a VALIDATED `elevations.jsonl` fixture record — one must-situate or must-anticipate item
 *  carrying its real-history ANSWER KEY (the set of non-obvious forward-value items a competent
 *  review must surface). Enforces the construction invariants so a malformed fixture cannot enter
 *  the corpus:
 *    • `id` and `prompt` are non-empty;
 *    • `pillar` is one of ELEVATION_PILLARS;
 *    • `answer_key` is a NON-EMPTY array of unique non-empty item ids (the must-surface ground truth);
 *    • `arm` (the provenance arm of the fixture) is recorded, and `poolable` is computed from it
 *      via the non-pooling guard — a weak-panel/retrodiction fixture is stamped `poolable:false`.
 *  The fixture also pins its `binding_baseline` (the per-pillar arm it will be scored against).
 *  Returns a FRESH plain object suitable for JSONL serialization. Throws on any violation. */
export function buildElevationFixture(spec = {}) {
  const { id, pillar, prompt, answer_key, arm = 'real-history', source = null, notes = null } = spec;
  if (!isNonEmptyString(id)) throw new Error('oracle-harness: buildElevationFixture requires a non-empty id');
  if (!ELEVATION_PILLARS.includes(pillar)) {
    throw new Error(`oracle-harness: buildElevationFixture requires pillar ∈ [${ELEVATION_PILLARS.join(', ')}], got ${JSON.stringify(pillar)}`);
  }
  if (!isNonEmptyString(prompt)) throw new Error(`oracle-harness: fixture '${id}' requires a non-empty prompt`);
  const key = uniqueStrings(answer_key);
  if (key.length === 0) {
    throw new Error(`oracle-harness: fixture '${id}' requires a non-empty answer_key (the must-surface ground-truth items)`);
  }
  if (Array.isArray(answer_key) && key.length !== answer_key.length) {
    throw new Error(`oracle-harness: fixture '${id}' answer_key has empty or duplicate item ids`);
  }
  if (!isNonEmptyString(arm)) throw new Error(`oracle-harness: fixture '${id}' requires a non-empty provenance arm`);
  return {
    kind: 'elevation-fixture',
    id: id.trim(),
    pillar,
    binding_baseline: bindingBaselineFor(pillar),
    prompt: prompt.trim(),
    answer_key: key,
    arm: arm.trim(),
    poolable: isPoolableArm(arm),
    source: isNonEmptyString(source) ? source.trim() : null,
    notes: isNonEmptyString(notes) ? notes.trim() : null,
  };
}

/** Serialize a set of fixtures to JSONL (one JSON object per line, trailing newline). Pure. */
export function toJsonl(fixtures) {
  const list = Array.isArray(fixtures) ? fixtures : [];
  return list.map((f) => JSON.stringify(f)).join('\n') + (list.length ? '\n' : '');
}

/** Parse JSONL back into an array of fixture records. Blank lines are skipped; a malformed line
 *  throws with its 1-based line number. Round-trips with `toJsonl`. */
export function parseJsonl(text) {
  if (typeof text !== 'string') throw new Error('oracle-harness: parseJsonl requires a string');
  const out = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line === '') continue;
    try {
      out.push(JSON.parse(line));
    } catch (err) {
      throw new Error(`oracle-harness: parseJsonl malformed JSON on line ${i + 1}: ${err?.message ?? err}`);
    }
  }
  return out;
}

// === POSITION-SWAP-WITH-AGREEMENT (the position-bias control) ==================================
/** The raw per-comparison verdict vocabulary: which POSITION the judge preferred. */
export const POSITION_VERDICTS = ['first', 'second', 'tie'];

function resolveArm(positionVerdict, firstArm, secondArm, where) {
  if (!POSITION_VERDICTS.includes(positionVerdict)) {
    throw new Error(`oracle-harness: ${where} verdict ${JSON.stringify(positionVerdict)} not in [${POSITION_VERDICTS.join(', ')}]`);
  }
  if (positionVerdict === 'tie') return 'tie';
  return positionVerdict === 'first' ? firstArm : secondArm;
}

/** Position-swap-with-agreement: a paired decision is trustworthy only if it SURVIVES swapping the
 *  presentation order. The judge is run twice — `forward` presents [armA, armB] and `swapped`
 *  presents [armB, armA] — each returning a POSITION verdict ('first'|'second'|'tie'). The decision
 *  stands only when both orders resolve to the SAME underlying winner; otherwise the disagreement
 *  IS position bias and there is NO decision. Returns an advisory record:
 *    { agreed, decided, winner, position_bias, forward_pick, swapped_pick }
 *  `armA`/`armB` default to 'A'/'B'. Pure; throws only on an out-of-vocabulary verdict. */
export function positionSwapWithAgreement({ forward, swapped, armA = 'A', armB = 'B' } = {}) {
  const forwardPick = resolveArm(forward, armA, armB, 'forward');
  const swappedPick = resolveArm(swapped, armB, armA, 'swapped'); // swapped order: first=armB, second=armA
  const agreed = forwardPick === swappedPick;
  const decided = agreed && forwardPick !== 'tie';
  return {
    agreed,
    decided,
    winner: decided ? forwardPick : null,
    position_bias: !agreed,
    forward_pick: forwardPick,
    swapped_pick: swappedPick,
  };
}

// === LENGTH-CONTROL (the verbosity-confound control) ==========================================
function wordCount(text) {
  if (!isNonEmptyString(text)) return 0;
  return text.trim().split(/\s+/).length;
}

/** Length-control for an A/B pair: a judge can be swayed by sheer verbosity, so a comparison whose
 *  two responses differ in length beyond `tolerance` (default 0.25 = 25% of the longer) is flagged
 *  as a LENGTH CONFOUND so its verdict can be length-adjusted or discarded. Returns:
 *    { len_a, len_b, abs_diff, ratio, longer, within_tolerance, length_confound }
 *  Lengths are word counts. Pure; never throws. */
export function lengthControl(textA, textB, { tolerance = 0.25 } = {}) {
  const lenA = wordCount(textA);
  const lenB = wordCount(textB);
  const longerLen = Math.max(lenA, lenB);
  const absDiff = Math.abs(lenA - lenB);
  const ratio = longerLen === 0 ? 1 : Math.min(lenA, lenB) / longerLen; // 1 == identical length
  const within = longerLen === 0 ? true : absDiff / longerLen <= tolerance;
  return {
    len_a: lenA,
    len_b: lenB,
    abs_diff: absDiff,
    ratio,
    longer: lenA === lenB ? 'equal' : lenA > lenB ? 'A' : 'B',
    within_tolerance: within,
    length_confound: !within,
  };
}

// === ANSWER-KEY SCORER (elevate_recall LOWER bound + false-elevation precision guard) ===========
/** Score one arm's response against a fixture's answer key. The answer key is the set of
 *  must-surface ground-truth item ids; the response is the set of item ids the arm actually
 *  ELEVATED. Computes, deterministically:
 *    • true_positives  = elevated ∩ key   (must-surface items the arm caught)
 *    • false_negatives = key \ elevated   (must-surface items the arm missed)
 *    • false_positives = elevated \ key   (FALSE elevations — the precision guard's concern)
 *    • elevate_recall  = tp / |key|       (a LOWER bound on true recall — the key is a floor)
 *    • precision       = tp / (tp + fp)   (the paired FALSE-ELEVATION guard; 1 when nothing elevated)
 *  `response` is `{ elevated: [ids] }` (or an array of ids); `answerKey` is an array of ids (or a
 *  fixture carrying `answer_key`). Pure; throws only on a missing/empty answer key. */
export function scoreAnswerKey(response, answerKey) {
  const key = uniqueStrings(Array.isArray(answerKey) ? answerKey : answerKey?.answer_key);
  if (key.length === 0) {
    throw new Error('oracle-harness: scoreAnswerKey requires a non-empty answer key');
  }
  const elevatedRaw = Array.isArray(response) ? response : response?.elevated;
  const elevated = uniqueStrings(elevatedRaw);
  const keySet = new Set(key);
  const elevSet = new Set(elevated);
  const truePositives = elevated.filter((e) => keySet.has(e));
  const falsePositives = elevated.filter((e) => !keySet.has(e));
  const falseNegatives = key.filter((k) => !elevSet.has(k));
  const tp = truePositives.length;
  const fp = falsePositives.length;
  const elevateRecall = tp / key.length;
  const precision = tp + fp === 0 ? 1 : tp / (tp + fp);
  return {
    elevate_recall: elevateRecall, // LOWER bound — the answer key is a floor on true recall
    precision, // the FALSE-elevation guard
    true_positives: truePositives,
    false_positives: falsePositives, // the false elevations
    false_negatives: falseNegatives,
    key_size: key.length,
  };
}

// === CAT SECONDARY (Consensual Assessment Technique: novelty × usefulness) ======================
/** The CAT secondary score: a suggestion's worth is novelty × usefulness (the Consensual
 *  Assessment Technique), kept as a SECONDARY to the answer-key recall primary. Both axes are in
 *  [0, 1]; the score is their product. Returns `{ novelty, usefulness, cat_score }`. Throws on an
 *  out-of-range axis. (Judging the magnitudes is the advisory layer's job — this only composes them.) */
export function catSecondary({ novelty, usefulness } = {}) {
  for (const [name, v] of [['novelty', novelty], ['usefulness', usefulness]]) {
    if (typeof v !== 'number' || Number.isNaN(v) || v < 0 || v > 1) {
      throw new Error(`oracle-harness: catSecondary requires ${name} ∈ [0, 1], got ${JSON.stringify(v)}`);
    }
  }
  return { novelty, usefulness, cat_score: novelty * usefulness };
}

// === compose ONE advisory, NON-GATING A/B artifact for a fixture ===============================
/** Run the full paired bias-robust A/B for ONE fixture, composing every control above into a
 *  single ADVISORY artifact (stamped `gating:false` — PRINCIPLE-D). Inputs:
 *    • `fixture`            — a built elevation fixture (carries pillar, answer_key, binding_baseline);
 *    • `gandalf`            — { elevated:[ids], text } the Gandalf arm's response;
 *    • `baseline`           — { elevated:[ids], text } the binding-baseline arm's response;
 *    • `positionSwap`       — { forward, swapped } the two position verdicts (optional);
 *    • `cat`                — { novelty, usefulness } the CAT secondary (optional);
 *    • `lengthTolerance`    — the length-control tolerance (optional).
 *  Scores BOTH arms against the answer key (per-pillar, never pooled across pillars), runs the
 *  length-control and (when given) the position-swap-with-agreement decision and the CAT secondary,
 *  and returns the bundle. NEVER gates and NEVER throws on a reachable/unreachable judge — it is the
 *  surface a human reads. Throws only on a malformed fixture (no answer key). */
export function evaluateFixture({ fixture, gandalf = {}, baseline = {}, positionSwap = null, cat = null, lengthTolerance = 0.25 } = {}) {
  if (!isObject(fixture)) throw new Error('oracle-harness: evaluateFixture requires a fixture object');
  const answerKey = fixture.answer_key;
  const pillar = fixture.pillar;
  const gandalfScore = scoreAnswerKey(gandalf, answerKey);
  const baselineScore = scoreAnswerKey(baseline, answerKey);
  const length = lengthControl(gandalf?.text, baseline?.text, { tolerance: lengthTolerance });
  const swap = isObject(positionSwap)
    ? positionSwapWithAgreement({ ...positionSwap, armA: 'gandalf', armB: 'baseline' })
    : null;
  const catScore = isObject(cat) ? catSecondary(cat) : null;
  return {
    kind: ORACLE_HARNESS_KIND,
    advisory: true,
    gating: false, // PRINCIPLE-D: the elevation oracle is ADVISORY — recorded, NEVER part of node --test
    fixture_id: fixture.id ?? null,
    pillar,
    binding_baseline: fixture.binding_baseline ?? (ELEVATION_PILLARS.includes(pillar) ? bindingBaselineFor(pillar) : null),
    poolable: fixture.poolable !== false, // weak-panel/retrodiction fixtures are not pooled
    gandalf: gandalfScore,
    baseline: baselineScore,
    // elevate_recall is reported per arm; the headline EFFECT (recall lift) is left to the pooled
    // power-calc, which only pools poolable fixtures — see seam/power-calc.mjs.
    recall_lift: gandalfScore.elevate_recall - baselineScore.elevate_recall,
    length_control: length,
    position_swap: swap,
    cat_secondary: catScore,
    note: 'ADVISORY elevation-oracle A/B artifact — recorded for a human to read, NEVER a Foreman gate; the SHIP/UNPROVEN ruling + calibration ICC are H1/H2',
  };
}
