/**
 * WHAT THE SKILLS ACTUALLY ARE (2026-08-07, from John's design correction).
 *
 * "It seems like you just ran researchPrime because it's the next thing in the
 * list — there's no thought, no glue." The steward was commissioning engines
 * it did not understand. This primer is the steward's working knowledge of its
 * own workforce: what each engine is FOR, the shape of a run, and what the
 * steward owes John around it. It rides the reflection prompt and (compactly)
 * the talk instruction, so both tiers reason about the skills as they are —
 * never as interchangeable list items.
 *
 * Kept HONEST and compact: these describe the real engines in this portfolio.
 */

export const SKILL_PRIMERS = Object.freeze({
  Gandalf: [
    'Gandalf — the deep-think reader. Give it a corpus or a project and it',
    'returns a graded, refuter-checked VERDICT: what is really there, the hard',
    'numbers, what is missing, what bites later. It does not build or plan.',
    'A Gandalf verdict is INPUT for everything downstream — after one lands,',
    'the steward\'s job is to fold its findings into the campaign and aim the',
    'next engine with them.',
  ].join('\n'),
  researchPrime: [
    'researchPrime — the investigator. It needs a DIRECTIVE: what to find out,',
    'why, and what the answers will be used for. Aim it with everything already',
    'known — a directive that ignores the latest verdict wastes the run.',
    'Shape: it first frames a RESEARCH PLAN and presents it before executing —',
    'that plan arrives as a question for John; bring it to him, never approve',
    'it in his place. Then it executes with adversarial verification and',
    'returns evidence-graded findings.',
  ].join('\n'),
  Crucible: [
    'Crucible — the planner. It forges an implementation plan through staged',
    'gates: Stage 0 locks the North Star (John\'s decision, always), then master',
    'plan, then implementation detail. Commission it when decisions are made',
    'and detail exists to plan FROM; a Crucible run on a thin brief stalls at',
    'its first gate asking for what the steward should already have gathered.',
  ].join('\n'),
  Foreman: [
    'Foreman — the builder. It executes a FROZEN plan wave by wave with review',
    'loops. It needs Crucible-grade planning docs in the project; never send it',
    'in with prose intentions. Its questions are rare and technical.',
  ].join('\n'),
  Jumper: [
    'Jumper — the ideation engine. Structured creative divergence (SCAMPER,',
    'analogies, TRIZ) with a kill-filter. Commission it when the campaign needs',
    'OPTIONS rather than answers.',
  ].join('\n'),
  'legal-beagle': [
    'legal-beagle — contract & compliance analysis, case-law synthesis over',
    'PROVIDED sources, boilerplate drafting, plain-English companions. Hard',
    'anti-hallucination rules (never cites from memory). Not a licensed attorney.',
  ].join('\n'),
  'literature-review': [
    'literature-review — systematic academic review: snowball search + PRISMA',
    'discipline, per-paper claim extraction with quote grounding, weighted',
    'consensus synthesis. For scholarly evidence, not general web research.',
  ].join('\n'),
  ramanujan: [
    'ramanujan — the mathematical-reasoning partner under THE HONESTY LAW:',
    'every claim carries an earned evidence rung; a certifier engine (exact',
    'arithmetic, z3/Lean) is available on request. For real math, never adjacent.',
  ].join('\n'),
  'financial-analyst': [
    'financial-analyst — financial analysis and modelling with a vetted engine',
    'and prose-lock discipline. For numbers that must survive scrutiny.',
  ].join('\n'),
  'figure-designer': [
    'figure-designer — best-in-class scientific/technical figures; run BEFORE',
    'generating any publication-grade diagram, and again to review one.',
  ].join('\n'),
  'tidy-idy': [
    'tidy-idy — folder hygiene with a human triage panel and reversible Trash.',
    'For cleaning a project tree (e.g. stray PII, junk) with John approving.',
  ].join('\n'),
  'expert-coder': [
    'expert-coder — senior-level code work: non-trivial features, refactors,',
    'root-cause debugging, production hardening, thorough tests.',
  ].join('\n'),
});

/** The full primer block for the reflection prompt. */
export function skillPrimerBlock() {
  return [
    '--- YOUR WORKFORCE (how each engine actually works) ---',
    ...Object.values(SKILL_PRIMERS).flatMap((p) => [p, '']),
    'COMMISSIONABLE today (the run machinery): researchPrime, Crucible,',
    'Foreman, Gandalf, Jumper. The foundry skills above are known and can be',
    'RECOMMENDED — John runs them in a general terminal until their commission',
    'lane is admitted. Never pretend to launch one.',
  ].join('\n');
}

/** One-line-per-skill version for the talk instruction (token-lean). */
export const SKILL_PRIMERS_COMPACT = [
  'Your workforce, in one line each — commission by FIT, never list order:',
  '- Gandalf reads and grades (verdicts in, nothing built).',
  '- researchPrime investigates a DIRECTIVE you compose from what is known;',
  '  it frames a research plan FIRST and that plan comes back to John.',
  '- Crucible plans through staged gates (Stage 0 = John locks the North Star).',
  '- Foreman builds from a frozen Crucible-grade plan.',
  '- Jumper generates vetted options when the campaign needs ideas.',
].join('\n');
