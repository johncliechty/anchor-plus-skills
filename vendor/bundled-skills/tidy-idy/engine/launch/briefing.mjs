// engine/launch/briefing.mjs — Wave 7: the per-run investigator briefing.
//
// The panel turns a run into a VERDICT. The briefing turns it into a
// CONVERSATION: a plain-markdown file a seeded agent terminal reads on open, so
// the human can argue with the findings instead of only clicking them.
//
// THREE properties this file exists to hold:
//
//   1. ENGINE-AGNOSTIC MARKDOWN, DISTINCT FROM THE PANEL JSON. The panel model
//      (engine/panel/model.mjs) is a token-carrying transport object for a
//      browser. The briefing is prose for a human-plus-agent: project root, run
//      summary, the specific findings with ABSOLUTE paths and their verbatim
//      evidence, and suggested first questions. Claude reads it, Gemini reads it,
//      a third engine reads it — nothing in it is engine-specific.
//
//   2. THE CLEAN-MACHINE FAILURE (FM15) IS DESIGNED OUT. The dev box has the
//      tidy-idy skill on its skill path; a fresh machine does not. A briefing
//      that merely said "load the tidy-idy skill" would work in the demo and
//      break on every clean machine. So the briefing VERIFIES skill
//      resolvability and, when the skill is absent, INLINES its operating
//      instructions — the agent gets a readable briefing rather than an
//      unresolved-skill dead end. The inline source is this skill's own
//      SKILL.md, which ships with the tool and is therefore always available.
//
//   3. IT NEVER LEAKS A SECRET. A secret-blocked finding contributes only its
//      rule name and the finding's OWN masked trigger text — never the matched
//      bytes, exactly as the panel enforces.

import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { toPosixRel } from '../glob.mjs';

/** The per-run briefing artifact, alongside envelope.json/report.md in the run dir. */
export const BRIEFING_FILENAME = 'briefing.md';

/** The tool's shipping SKILL.md — the inline source when the skill is unresolvable. */
export const SKILL_MD_SOURCE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'SKILL.md');

/** The skill name an agent would look up on its skill path. */
export const TIDY_IDY_SKILL_NAME = 'tidy-idy';

/**
 * Where an agent launched in this project would look for the tidy-idy skill.
 * Injectable so a test can model a clean profile (no dev skill paths) without
 * touching the real machine.
 */
export function skillSearchPaths({ env = process.env } = {}) {
  const paths = [];
  if (env.TIDY_IDY_SKILL_PATH) paths.push(env.TIDY_IDY_SKILL_PATH);
  if (env.CLAUDE_SKILLS_DIR) paths.push(path.join(env.CLAUDE_SKILLS_DIR, TIDY_IDY_SKILL_NAME, 'SKILL.md'));
  const home = env.HOME || env.USERPROFILE || null;
  if (home) paths.push(path.join(home, '.claude', 'skills', TIDY_IDY_SKILL_NAME, 'SKILL.md'));
  return paths;
}

/**
 * Is the tidy-idy skill resolvable in this environment? A filesystem check over
 * the agent's real skill-search locations. `resolvable:false` is the clean
 * machine, and it is the case the briefing must survive.
 *
 * @returns {Promise<{resolvable: boolean, path: string|null, searched: string[]}>}
 */
export async function resolveTidyIdySkill({ env = process.env, fs = fsp, searchPaths = null } = {}) {
  const candidates = searchPaths || skillSearchPaths({ env });
  for (const p of candidates) {
    try {
      const st = await fs.stat(p);
      if (st.isFile()) return { resolvable: true, path: p, searched: candidates };
    } catch { /* not here — keep looking */ }
  }
  return { resolvable: false, path: null, searched: candidates };
}

/** Read the shipping skill instructions for inlining. Always available; null only on IO failure. */
export async function readSkillInstructions({ fs = fsp, source = SKILL_MD_SOURCE } = {}) {
  try {
    return String(await fs.readFile(source, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Render the briefing markdown for one run.
 *
 * @param {{envelope: object, identity: object, runNumber?: number|null,
 *   skill?: {resolvable: boolean, path?: string|null}, skillInstructions?: string|null}} opts
 */
export function renderBriefingMarkdown({ envelope, identity, runNumber = null, skill = { resolvable: true }, skillInstructions = null } = {}) {
  const root = identity.path;
  const findings = envelope.findings || [];
  const L = [];

  L.push(`# tidy-idy investigation briefing — ${identity.name} — run ${runNumber ?? '?'}`);
  L.push('');
  L.push('You are helping the human act on a completed tidy-idy hygiene run. Read this whole');
  L.push('briefing before doing anything. Nothing below has been applied — every removal, SAVE');
  L.push('and move is a PROPOSAL awaiting the human, and approvals happen in the Triage Panel,');
  L.push('one Apply per run. Do not delete, move, or commit anything yourself without being asked.');
  L.push('');

  L.push('## The project');
  L.push('');
  L.push(`- **Name**: ${identity.name}`);
  L.push(`- **Root (absolute)**: \`${root}\``);
  L.push(`- **Git**: ${identity.git && identity.git.present
    ? `${identity.git.branch || 'detached'} @ ${identity.git.shortSha || '(no commits)'}${Number.isInteger(identity.git.dirtyCount) ? ` — ${identity.git.dirtyCount} dirty path(s)` : ''}`
    : 'no repository — removals apply through the reversible Trash'}`);
  L.push(`- **Mode**: ${envelope.mode}`);
  L.push(`- **Run id**: \`${envelope.runId}\``);
  L.push(`- **Terminal status**: **${String(envelope.status).toUpperCase()}** (the worst stage status — there is no "mostly fine")`);
  L.push('');

  L.push('## What this run concluded');
  L.push('');
  if (envelope.isClean) {
    L.push('This run is a **clean** verdict: every stage completed with full coverage and zero findings.');
  } else {
    L.push('This run is **not** a clean verdict. Exactly why:');
    L.push('');
    for (const b of envelope.cleanBlockers || []) L.push(`- ${b}`);
  }
  L.push('');

  L.push('### Stage coverage');
  L.push('');
  L.push('| stage | status | scanned | skipped | errored |');
  L.push('| --- | --- | --- | --- | --- |');
  for (const s of envelope.stages || []) {
    const c = s.coverage || {};
    L.push(`| ${s.stage} | ${s.status} | ${c.scanned || 0} | ${c.skipped || 0} | ${c.errored || 0} |`);
  }
  L.push('');
  if ((envelope.errors || []).length) {
    L.push('### Stage errors (verbatim)');
    L.push('');
    for (const e of envelope.errors) L.push(`- **${e.stage}**: ${e.message}`);
    L.push('');
  }

  L.push('## Findings');
  L.push('');
  if (!findings.length) {
    L.push('_No findings in this run._');
    L.push('');
  } else {
    const byAction = new Map();
    for (const f of findings) {
      const key = f.kind || f.action || 'finding';
      if (!byAction.has(key)) byAction.set(key, []);
      byAction.get(key).push(f);
    }
    for (const [group, list] of byAction) {
      L.push(`### ${group} (${list.length})`);
      L.push('');
      for (const f of list) L.push(...findingLines(f, root));
      L.push('');
    }
  }

  L.push('## Suggested first questions');
  L.push('');
  for (const q of suggestedQuestions(envelope)) L.push(`- ${q}`);
  L.push('');

  L.push('## The tidy-idy skill');
  L.push('');
  if (skill && skill.resolvable) {
    L.push(`The tidy-idy skill is resolvable in this environment${skill.path ? ` (at \`${skill.path}\`)` : ''}.`);
    L.push('Load it for the full operating manual before you advise on any removal.');
  } else {
    L.push('The tidy-idy skill is **not resolvable** in this environment, so its operating');
    L.push('instructions are inlined below verbatim — work from these rather than trying to');
    L.push('load a skill that is not on this machine\'s skill path.');
    L.push('');
    L.push('<details><summary>tidy-idy operating instructions (inlined — skill not resolvable here)</summary>');
    L.push('');
    L.push(skillInstructions || '(the shipping SKILL.md could not be read — treat this as advisory only and confirm every action with the human)');
    L.push('');
    L.push('</details>');
  }
  L.push('');

  L.push('---');
  L.push('');
  L.push('This briefing is engine-agnostic: it is the same file whether you are Claude, Gemini, Grok,');
  L.push('or another agent. It reflects run state at scan time; if HEAD has since moved, say so');
  L.push('and suggest a cheap re-scan rather than acting on a tree that no longer exists.');
  L.push('');
  return L.join('\n');
}

/** One finding rendered as briefing lines: absolute path + verbatim evidence, no secret bytes. */
function findingLines(f, root) {
  const rel = f.path ? toPosixRel(f.path) : null;
  const abs = f.absolutePath || (rel ? path.join(root, rel) : null);
  const out = [];
  out.push(`- **${f.action || f.kind || 'finding'}** — \`${abs || rel || '(no path)'}\``);
  if (f.why) out.push(`  - why: ${oneLine(f.why)}`);
  const ev = f.evidence || {};
  if (ev.decision) out.push(`  - judge (verbatim): ${ev.decision}${ev.rationale ? ` — ${oneLine(ev.rationale)}` : ''}`);
  if (ev.attacker && (ev.attacker.case_for_removal || ev.attacker.claim)) {
    out.push(`  - attacker (verbatim): ${oneLine(ev.attacker.case_for_removal || ev.attacker.claim)}${ev.attacker.strength ? ` [strength: ${ev.attacker.strength}]` : ''}`);
  }
  if (Array.isArray(f.heuristics) && f.heuristics.length) out.push(`  - heuristics: ${f.heuristics.join(' + ')}`);
  if (f.porcelain) out.push(`  - git porcelain (verbatim): \`${oneLine(f.porcelain)}\``);
  if (f.quarantine) out.push(`  - quarantined: ${f.quarantine} — individually confirmable only, never bulk`);
  if (f.kind === 'secret-blocked' || f.action === 'blocked') {
    // NEVER the matched bytes: rule names and the finding's own masked text only.
    const rules = (f.triggers || []).map((t) => t.rule || t.name).filter(Boolean).join(', ');
    out.push(`  - **BLOCKED** — no approval control exists for this class${rules ? ` (rule(s): ${rules})` : ''}${f.maskedTriggerText ? `; masked trigger: ${f.maskedTriggerText}` : ''}`);
  }
  if (f.undo) out.push(`  - undo: ${oneLine(f.undo)}`);
  return out;
}

function oneLine(s) {
  return String(s == null ? '' : s).replace(/\s*\n\s*/g, ' ').trim();
}

/** Questions seeded from what the run actually contains — never generic filler. */
function suggestedQuestions(envelope) {
  const findings = envelope.findings || [];
  const has = (pred) => findings.some(pred);
  const qs = [];
  if (has((f) => f.kind === 'removal-candidate' || f.action === 'remove')) {
    qs.push('Which of the proposed removals would you push back on, and what evidence would change the verdict?');
  }
  if (has((f) => f.kind === 'save-candidate' || f.action === 'save')) {
    qs.push('Of the SAVE candidates (content git does not hold yet), which are worth committing and which are throwaway?');
  }
  if (has((f) => f.kind === 'secret-blocked' || f.action === 'blocked')) {
    qs.push('For each BLOCKED secret, which remediation fits — .gitignore, untrack, relocate, or a reviewed next-run override?');
  }
  if (has((f) => f.kind === 'heuristic-candidate')) {
    qs.push('The heuristic candidates are evidence, not verdicts — which ones actually earn a removal?');
  }
  if (envelope.status !== 'ok') {
    qs.push('A stage did not complete cleanly — what did the run fail to look at, and does that change any verdict here?');
  }
  qs.push('What did this run likely MISS — a file class, a directory, or a risk the stages do not cover?');
  return qs;
}

/**
 * Write the per-run briefing into the run directory, resolving the skill in the
 * CALLER's environment. Plain write, on purpose: the briefing is regenerable
 * tool output, and it is refreshed at launch so it always matches the
 * environment the terminal is actually opening in (the FM15 fix). It is NOT one
 * of the wx-guarded canonical artifacts.
 *
 * @returns {Promise<{path: string, skill: object, inlined: boolean}>}
 */
export async function writeBriefing({ runDir, envelope, identity, runNumber = null, skill = null, fs = fsp, env = process.env } = {}) {
  const resolved = skill || await resolveTidyIdySkill({ env, fs });
  const skillInstructions = resolved.resolvable ? null : await readSkillInstructions({ fs });
  const md = renderBriefingMarkdown({ envelope, identity, runNumber, skill: resolved, skillInstructions });
  const file = path.join(runDir, BRIEFING_FILENAME);
  await fs.writeFile(file, md, 'utf8');
  return { path: file, skill: resolved, inlined: !resolved.resolvable };
}

export default {
  writeBriefing, renderBriefingMarkdown, resolveTidyIdySkill, readSkillInstructions, skillSearchPaths,
  BRIEFING_FILENAME, SKILL_MD_SOURCE, TIDY_IDY_SKILL_NAME,
};
