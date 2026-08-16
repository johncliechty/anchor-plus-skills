/**
 * READ WHAT THE SKILL SAID, AND TELL JOHN IN A FEW LINES.
 *
 * WHY. A commissioned session hands back a raw PTY transcript: ANSI escapes, spinner
 * frames, "⏵⏵ auto mode on", a status bar, and the skill's actual answer wrapped
 * somewhere inside it. Handing that to John is exactly the "way too much stuff in that
 * feedback window" he asked me to stop doing.
 *
 * So the steward READS the run and reports it: what the skill did, what it produced,
 * what it needs from him, and the one thing he should do next. Detail on request.
 *
 * Two stages, and the split matters:
 *   1. `cleanTranscript` is DETERMINISTIC — it strips the terminal furniture. No model,
 *      no judgement, testable.
 *   2. `buildRunReportPrompt` asks the seat to summarise what remains. A model is used
 *      to read prose, never to decide what happened: the OUTCOME (asked/produced/quiet/
 *      died) is classified deterministically by the runner before this is ever called.
 *
 * ENGINE LAW: no child_process here. The seat call is injected, as everywhere else.
 */

import { SPELLING } from './verbs.mjs';

/** Terminal furniture that is never part of what the skill said. */
const NOISE_PATTERNS = Object.freeze([
  /\x1b\[[0-9;?]*[a-zA-Z]/g,          // CSI escapes
  /\x1b\][^\x07]*\x07/g,              // OSC title sequences
  /\x1b[()][AB012]/g,                 // charset selection
  /\r/g,
  /^.*⏵⏵.*$/gm,                       // "auto mode on (shift+tab to cycle)"
  /^.*Transcript saving is off.*$/gm,
  /^.*\bctrl\+[a-z]\b.*$/gim,         // key hints
  /^.*\(shift\+tab.*$/gm,
  /^\s*[─━═]{10,}\s*$/gm,             // rule lines
  /^\s*❯\s*$/gm,                      // empty prompt lines
  /^.*\b(?:Billowing|Inferring|Sautéed|Worked for|Tip:)\b.*$/gm, // spinner/status frames
]);

/**
 * Strip the terminal's own output from a session transcript.
 *
 * Deterministic and testable — this is the part that must not be a model's guess,
 * because everything downstream reads what it leaves behind.
 *
 * @param {string} raw
 * @returns {string}
 */
export function cleanTranscript(raw) {
  let text = String(raw ?? '');
  for (const re of NOISE_PATTERNS) text = text.replace(re, '');
  return text
    .split(/\n/)
    .map((l) => l.replace(/[ \t]+$/, ''))
    .filter((l, i, arr) => !(l.trim() === '' && arr[i - 1]?.trim() === ''))
    .join('\n')
    .trim();
}

/**
 * The steward's standing instruction for reading a commissioned run.
 *
 * Concision is the point. John: "when it interacts with me it should be really concise,
 * really to the point — I can ask it for more details. I don't want to be reading lots
 * and lots of stuff."
 */
export const RUN_REPORT_INSTRUCTION = [
  `You are ${SPELLING}. A skill you commissioned has just run. Read its output and`,
  'tell John where things stand. You are reporting, not re-doing the work.',
  '',
  // (2026-08-06, John on his first real reports) 90 words flattened a
  // 27-minute heavy read into a teaser — "really short, compared to the amount
  // of work that was done". The cap now scales with the content: still no
  // padding, but every real finding gets a sentence.
  'LENGTH MATCHES SUBSTANCE. A run that produced real findings gets up to 250',
  'words in `say` — every substantive finding, verdict, number, and caught',
  'error named. A thin run gets a thin report. Never pad; never truncate a',
  'real result to hit a word count. No headers, no bullet walls.',
  'Lead with the outcome — what came back — then what to do next.',
  'If the skill asked a question, that question IS the next thing: put it in `needs`.',
  'List every artifact the skill actually wrote in `produced`, WITH its file',
  'path when the output names one.',
  'Never invent a file, a finding, or a decision the skill did not produce.',
  '',
  'REPLY WITH ONLY a JSON object, no prose outside it, no code fence:',
  '{',
  '  "say": "<the report: up to 250 words when the content earns it>",',
  '  "produced": ["<artifact with path, or finding, actually produced>"],',
  '  "needs": "<the decision the skill needs from John, or null>",',
  '  "recommend": "<your recommendation for the next move, one line>"',
  '}',
].join('\n');

/**
 * Build the prompt that turns a run into a report.
 *
 * @param {{ skill: string, step?: string|null, outcome: string, transcript: string }} run
 * @returns {string}
 */
export function buildRunReportPrompt(run = {}) {
  const cleaned = cleanTranscript(run.transcript);
  return [
    RUN_REPORT_INSTRUCTION,
    '',
    '--- THE RUN ---',
    `Skill: ${run.skill ?? 'unknown'}`,
    run.step ? `Step: ${run.step}` : null,
    // The outcome is DETERMINISTIC (classified by the runner from the raw stream).
    // It is given to the model as fact, never asked of it.
    `Outcome (already determined, do not re-judge): ${run.outcome}`,
    '',
    '--- WHAT THE SKILL SAID ---',
    cleaned || '(the skill produced no readable output)',
  ].filter(Boolean).join('\n');
}

/**
 * Honest report for a run that produced nothing readable.
 *
 * A commissioned run that greeted and stopped is NOT a run, and must not be summarised
 * as though it were — that is precisely the "45-second plan" that planned nothing.
 *
 * @param {{ outcome: string, ran?: boolean, elapsed_s?: number, skill?: string }} run
 */
export function emptyRunReport(run = {}) {
  const skill = run.skill ?? 'The skill';
  const map = {
    quiet: `${skill} loaded but produced nothing in ${Math.round(run.elapsed_s ?? 0)}s. `
      + 'It is waiting, not working — nothing was produced.',
    died: `${skill}'s session ended before it produced anything.`,
    timeout: `${skill} was still working when I stopped watching. Nothing final yet.`,
    // 0082: the engine-launch death gets its own sentence AND its own
    // recommendation — "open the session" is exactly wrong for a session
    // that never opened.
    launch_failure: `${skill} never started — the engine failed at launch `
      + `(${Math.round(run.elapsed_s ?? 0)}s of life, nothing written). `
      + 'Usage limit or a broken engine CLI.',
  };
  return {
    ok: true,
    outcome: run.outcome,
    ran: run.ran === true,
    say: map[run.outcome] ?? `${skill} returned nothing I can report.`,
    produced: [],
    needs: null,
    recommend: run.outcome === 'launch_failure'
      ? 'Check the engine CLI/auth (a tiny probe call) BEFORE relaunching — a blind relaunch pays for the same death again.'
      : 'Open the session and see what it is waiting on.',
    reported_without_model: true,
  };
}

/**
 * Parse the seat's report reply. Strict: a shape we cannot read is reported as such,
 * never salvaged into a plausible-sounding summary.
 *
 * @param {string|object} raw
 */
export function parseRunReport(raw) {
  let obj = raw;
  if (typeof raw === 'string') {
    const m = raw.match(/\{[\s\S]*\}/);
    try {
      obj = JSON.parse(m ? m[0] : raw);
    } catch {
      return { ok: false, error: 'report_unparseable' };
    }
  }
  if (!obj || typeof obj !== 'object') return { ok: false, error: 'report_not_object' };
  const say = String(obj.say ?? '').trim();
  if (!say) return { ok: false, error: 'report_empty' };
  return {
    ok: true,
    say,
    produced: (Array.isArray(obj.produced) ? obj.produced : [])
      .map((p) => String(p).trim()).filter(Boolean),
    needs: String(obj.needs ?? '').trim() || null,
    recommend: String(obj.recommend ?? '').trim() || null,
  };
}

/**
 * Read a commissioned run and produce John's report.
 *
 * @param {{ skill: string, step?: string, outcome: string, transcript: string, ran?: boolean, elapsed_s?: number }} run
 * @param {{ seatCall?: Function }} opts
 */
export async function reportOnRun(run = {}, opts = {}) {
  // Nothing readable → say so plainly. No model call, no dressing it up.
  if (run.ran !== true || !cleanTranscript(run.transcript)) {
    return emptyRunReport(run);
  }
  if (typeof opts.seatCall !== 'function') {
    return { ...emptyRunReport(run), say: 'The run finished but I could not reach a seat to read it.' };
  }
  const prompt = buildRunReportPrompt(run);
  let reply;
  try {
    reply = await opts.seatCall(prompt, { role: 'conversational' });
  } catch (e) {
    return { ...emptyRunReport(run), say: `The run finished but reading it failed: ${e?.message ?? e}` };
  }
  if (!reply?.ok || !String(reply.text ?? '').trim()) {
    return { ...emptyRunReport(run), say: 'The run finished but I could not read it back.' };
  }
  const parsed = parseRunReport(reply.text);
  if (!parsed.ok) {
    return { ...emptyRunReport(run), say: 'The run finished but its summary came back unreadable.' };
  }
  return { ok: true, outcome: run.outcome, ran: true, ...parsed, usage: reply.meta ?? null };
}
