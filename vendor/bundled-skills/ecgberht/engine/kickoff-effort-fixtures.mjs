/**
 * Gate 5 / Wave 6 - the FIVE representative efforts and the readable-distinction law.
 *
 * WHY THIS IS ENGINE SOURCE AND NOT TEST DATA. The North Star's proof (criterion 12)
 * runs on John's screen across five synthetic efforts - document, software, research,
 * simple, ambiguous - and three different waves need the SAME five: this wave's hermetic
 * fixture suite, the final wave's staging for John's 30-second look, and any later
 * regression on the synthesis contract. Data that three consumers must agree on lives
 * once, beside the law it exercises, or the copies drift and the proof rots.
 *
 * WHAT EACH FIXTURE IS. One representative effort: John's opening (his voice, rich or
 * sparse), the scripted seat replies (what a model AUTHORS - the compiler generates
 * nothing, so the fixture's bundle is the model side of the no-generation invariant),
 * and the expectation row a test asserts. The ambiguous effort deliberately reaches its
 * THIN proposal by turn 2 under the Wave 3 bound - a thin bundle, never a third
 * question, is the answer to ambiguity.
 *
 * THE READABLE-DISTINCTION LAW (North Star criterion 4, this wave's cut). The prose John
 * reviews carries the labelled sections in HUMAN words - outcome, parts, plan, first
 * slice, and how the parts join where any - and none of the schema vocabulary. The law
 * is one function over (record, prose) so every suite asserts the same sentence:
 *   - every section the record EARNS is present under its human label;
 *   - no section the record did not earn is fabricated into the prose;
 *   - no schema key (the snake_case vocabulary) appears anywhere in the prose.
 * The ban list is exactly the underscore-carrying identifiers: a natural English word
 * such as "plan" or "goal" can appear in an authored goal and must never trip the law.
 *
 * Pure data + pure functions. Stdlib only; no fs, no child_process. Source is ASCII on
 * purpose (the repo's mojibake sweep).
 */

/** The human labels THE renderer (kickoff-record.mjs) writes, named once for assertions. */
export const KICKOFF_PROSE_LABELS = Object.freeze({
  outcome: 'Outcome: ',
  finished_when: 'Finished when:',
  parts: 'Parts of ',
  plan: 'Plan:',
  first_slice: 'First slice: ',
  integration: 'How the parts join: ',
  integration_proof: 'Seen when: ',
});

/**
 * The schema vocabulary that must never reach John's eyes. Deliberately ONLY the
 * underscore-carrying identifiers: they cannot occur in natural prose, so the law has
 * zero false positives on model-authored goals ("plan the steps of..." is fine).
 */
export const KICKOFF_SCHEMA_WORDS = Object.freeze([
  'work_product',
  'plan_entries',
  'first_slice_id',
  'success_signals',
  'end_to_end_slice',
  'done_when',
  'component_ids',
  'proposal_hash',
  'rendered_prose_hash',
  'prior_confirmed_hash',
  'source_turn',
  'requires_confirm',
  'zero_model',
  'kickoff_proposal',
  'client_event_id',
  'seat_family',
]);

/**
 * THE LAW, as one report. Sections the record earns must be present under their human
 * label; sections it did not earn must be absent (a fabricated section is padding by
 * prose); schema words must not appear at all.
 *
 * @param {object|null} record a kickoff_proposal_v0 record (or its content)
 * @param {string} prose the rendered prose shown for that record
 * @returns {{ok: boolean, present: string[], missing: string[], fabricated: string[],
 *   schema_words_found: string[], expected: {integration: boolean, finished_when: boolean}}}
 */
export function readableDistinctionReport(record, prose) {
  const text = String(prose ?? '');
  const lines = text.split('\n');
  const has = (probe) => lines.some((line) => line.startsWith(probe));

  const expected = {
    integration: record != null && record.integration != null,
    finished_when: Array.isArray(record?.success_signals) && record.success_signals.length > 0,
  };

  const present = [];
  const missing = [];
  const fabricated = [];
  const need = (name, probe) => {
    if (has(probe)) present.push(name);
    else missing.push(name);
  };

  need('outcome', KICKOFF_PROSE_LABELS.outcome);
  need('parts', KICKOFF_PROSE_LABELS.parts);
  need('plan', KICKOFF_PROSE_LABELS.plan);
  need('first_slice', KICKOFF_PROSE_LABELS.first_slice);
  if (expected.integration) {
    need('integration', KICKOFF_PROSE_LABELS.integration);
    need('integration_proof', KICKOFF_PROSE_LABELS.integration_proof);
  } else if (has(KICKOFF_PROSE_LABELS.integration) || has(KICKOFF_PROSE_LABELS.integration_proof)) {
    fabricated.push('integration');
  }
  if (expected.finished_when) {
    need('finished_when', KICKOFF_PROSE_LABELS.finished_when);
  } else if (has(KICKOFF_PROSE_LABELS.finished_when)) {
    fabricated.push('finished_when');
  }

  const schemaWordsFound = KICKOFF_SCHEMA_WORDS.filter((word) => text.includes(word));
  const ok = missing.length === 0 && fabricated.length === 0 && schemaWordsFound.length === 0;
  return Object.freeze({
    ok,
    present: Object.freeze(present),
    missing: Object.freeze(missing),
    fabricated: Object.freeze(fabricated),
    schema_words_found: Object.freeze(schemaWordsFound),
    expected: Object.freeze(expected),
  });
}

// -- the five efforts --------------------------------------------------------------

function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

const talkReply = (say, asks = [], extra = {}) => ({ say, asks, wants_plan: false, ...extra });
const planReply = (say, proposal) => ({ say, asks: [], proposal });

/** DOCUMENT - the plan's one-page memo Given/When/Then: one component, no padding. */
const DOCUMENT_EFFORT = {
  key: 'document',
  label: 'one-page decision memo',
  opening:
    'I owe the dean a one-page memo on the spring pilot: what changed in the course, what '
    + 'it cost in hours, and my recommendation at the top. Done means she decides in one '
    + 'read without asking me anything. First move is drafting the page from the pilot '
    + 'notes I already have.',
  followup: null,
  talk: [
    talkReply('A one-page memo with the decision at the top - I can frame that now.', [], {
      wants_plan: true,
      plan_brief: 'Frame the spring pilot memo as one reviewed bundle.',
    }),
  ],
  plan: [
    planReply('One page, one part, two moves.', {
      kind: 'kickoff',
      goal: 'Give the dean a one-page memo on the spring pilot: what changed, what it cost, and the recommendation.',
      success_signals: ['The dean decides in one read and asks no follow-up question.'],
      work_product: {
        id: 'pilot-memo',
        name: 'Spring pilot memo',
        components: [{ id: 'page', name: 'The one-page memo' }],
      },
      integration: null,
      plan_entries: [
        {
          id: 'draft-page',
          name: 'Draft the page from the pilot notes',
          component_ids: ['page'],
          end_to_end_slice: true,
        },
        {
          id: 'read-aloud',
          name: 'Read it aloud once and tighten it',
          component_ids: ['page'],
          end_to_end_slice: false,
        },
      ],
      first_slice_id: 'draft-page',
    }),
  ],
  expect: {
    turns: 1,
    asks_turn_1: 0,
    components: 1,
    integration: false,
    plan_entries: 2,
    finished_when: true,
  },
};

/** SOFTWARE - multiple parts that must join, so integration is EARNED, not padded. */
const SOFTWARE_EFFORT = {
  key: 'software',
  label: 'folder-audit command-line tool',
  opening:
    'I want the folder-audit command-line tool we keep talking about: one command runs a '
    + 'set of audit rules over a folder and prints a findings report, so a stray file '
    + 'cannot hide. The rules and the report matter as much as the command itself. Done '
    + 'means a run over the planted samples flags every stray and nothing else. Start '
    + 'with one rule running end to end.',
  followup: null,
  talk: [
    talkReply('Three parts that have to act as one tool - framing it now.', [], {
      wants_plan: true,
      plan_brief: 'Frame the folder-audit tool: command, rules, report, and their join.',
    }),
  ],
  plan: [
    planReply('One tool, three parts, one walking skeleton first.', {
      kind: 'kickoff',
      goal: 'Ship the folder-audit command-line tool so one run flags every stray file in a folder.',
      success_signals: ['A run over the planted samples flags every stray and nothing else.'],
      work_product: {
        id: 'audit-tool',
        name: 'Folder audit tool',
        components: [
          { id: 'command', name: 'The command surface' },
          { id: 'rules', name: 'The audit rules', done_when: 'Every rule has a planted sample that trips it.' },
          { id: 'report', name: 'The findings report' },
        ],
      },
      integration: {
        summary: 'The command runs the rules and every rule hit lands as one row of the report.',
        relationships: [
          {
            kind: 'depends_on',
            component_ids: ['command', 'rules'],
            description: 'The command surface loads and runs the rule set.',
          },
          {
            kind: 'feeds',
            component_ids: ['rules', 'report'],
            description: 'Each rule hit becomes one findings row.',
          },
        ],
        proof: {
          observable: 'One command over the planted samples prints a report naming every stray.',
          method: 'Run the tool against the samples and read the report beside the plant list.',
        },
      },
      plan_entries: [
        {
          id: 'walking-skeleton',
          name: 'One command runs one rule end to end',
          component_ids: ['command', 'rules', 'report'],
          end_to_end_slice: true,
        },
        {
          id: 'fill-rules',
          name: 'Add the remaining audit rules with their samples',
          component_ids: ['rules'],
          end_to_end_slice: false,
        },
        {
          id: 'readable-report',
          name: 'Make the report readable in one glance',
          component_ids: ['report'],
          end_to_end_slice: false,
        },
      ],
      first_slice_id: 'walking-skeleton',
    }),
  ],
  expect: {
    turns: 1,
    asks_turn_1: 0,
    components: 3,
    integration: true,
    plan_entries: 3,
    finished_when: true,
  },
};

/** RESEARCH - a memo that may argue only what a linked evidence log can back. */
const RESEARCH_EFFORT = {
  key: 'research',
  label: 'retention evidence review',
  opening:
    'I need to find out whether spaced oral quizzes actually beat weekly problem sets for '
    + 'retention, from the course literature, before I commit the syllabus to them. I want '
    + 'a short findings memo I can defend, and an evidence log behind it so a colleague '
    + 'can check any claim. Start by logging the first sources and drafting the claim list.',
  followup: null,
  talk: [
    talkReply('A defensible memo needs its evidence log beside it - framing both.', [], {
      wants_plan: true,
      plan_brief: 'Frame the retention review: findings memo plus evidence log, joined.',
    }),
  ],
  plan: [
    planReply('Two parts: the memo, and the log that makes it checkable.', {
      kind: 'kickoff',
      goal: 'Learn whether spaced oral quizzes beat weekly problem sets for retention, from the course literature.',
      success_signals: ['A colleague can check any memo claim against the evidence log.'],
      work_product: {
        id: 'retention-review',
        name: 'Retention evidence review',
        components: [
          { id: 'memo', name: 'The findings memo' },
          {
            id: 'evidence-log',
            name: 'The evidence log',
            done_when: 'Every claim in the memo points at one logged source.',
          },
        ],
      },
      integration: {
        summary: 'The memo argues only what the evidence log can back.',
        relationships: [
          {
            kind: 'validates',
            component_ids: ['evidence-log', 'memo'],
            description: 'Each memo claim cites a logged source by id.',
          },
        ],
        proof: {
          observable: 'Reading the memo beside the log ties every claim to a source.',
          method: 'Spot-check five claims against their logged sources.',
        },
      },
      plan_entries: [
        {
          id: 'first-pass',
          name: 'Log the first ten sources and draft the claim list',
          component_ids: ['evidence-log', 'memo'],
          end_to_end_slice: true,
        },
        {
          id: 'write-memo',
          name: 'Write the memo from the logged evidence',
          component_ids: ['memo'],
          end_to_end_slice: false,
        },
      ],
      first_slice_id: 'first-pass',
    }),
  ],
  expect: {
    turns: 1,
    asks_turn_1: 0,
    components: 2,
    integration: true,
    plan_entries: 2,
    finished_when: true,
  },
};

/** SIMPLE - a one-sitting effort that collapses honestly: nothing optional at all. */
const SIMPLE_EFFORT = {
  key: 'simple',
  label: 'one-sitting team note',
  opening:
    'Just a two-paragraph note to the team about the new build cadence, nothing more - '
    + 'I will write the whole thing in one sitting today.',
  followup: null,
  talk: [
    talkReply('One sitting, one note - here is the whole of it.', [], {
      wants_plan: true,
      plan_brief: 'Frame the cadence note as the smallest honest bundle.',
    }),
  ],
  plan: [
    planReply('The whole of it.', {
      kind: 'kickoff',
      goal: 'Send the team the two-paragraph note about the new build cadence.',
      success_signals: [],
      work_product: {
        id: 'cadence-note',
        name: 'Cadence note',
        components: [{ id: 'note', name: 'The note' }],
      },
      integration: null,
      plan_entries: [
        {
          id: 'write-and-send',
          name: 'Write it, read it once, send it',
          component_ids: ['note'],
          end_to_end_slice: true,
        },
      ],
      first_slice_id: 'write-and-send',
    }),
  ],
  expect: {
    turns: 1,
    asks_turn_1: 0,
    components: 1,
    integration: false,
    plan_entries: 1,
    finished_when: false,
  },
};

/**
 * AMBIGUOUS - a sparse opening that never firms up. One natural question on turn 1;
 * on turn 2 the thin bound forces the planning tier and the seat authors the SMALLEST
 * honest bundle from John's own words. A thin bundle, never a third question.
 */
const AMBIGUOUS_EFFORT = {
  key: 'ambiguous',
  label: 'unshaped workshop material',
  opening:
    'I keep circling something about the workshop material but I cannot say yet what '
    + 'shape it actually wants to be.',
  followup:
    'Maybe a page people can share, maybe something more - honestly you pick the '
    + 'smallest useful shape for now.',
  talk: [
    talkReply('Let us find its shape together.', [
      'What must it produce, at minimum?',
      'Who is it for?',
    ]),
    talkReply('Still loose, but I can start from the smallest version.', ['Who is it for?']),
  ],
  plan: [
    planReply('The smallest honest version, from your own words.', {
      kind: 'kickoff',
      goal: 'Put the workshop material into one shareable page.',
      success_signals: [],
      work_product: {
        id: 'workshop-page',
        name: 'Workshop page',
        components: [{ id: 'page', name: 'The page' }],
      },
      integration: null,
      plan_entries: [
        {
          id: 'gather-and-draft',
          name: 'Gather the material and draft the page',
          component_ids: ['page'],
          end_to_end_slice: true,
        },
      ],
      first_slice_id: 'gather-and-draft',
    }),
  ],
  expect: {
    turns: 2,
    asks_turn_1: 1,
    components: 1,
    integration: false,
    plan_entries: 1,
    finished_when: false,
  },
};

/** The five representative efforts, in the plan's order. Deep-frozen shared truth. */
export const KICKOFF_EFFORT_FIXTURES = deepFreeze([
  DOCUMENT_EFFORT,
  SOFTWARE_EFFORT,
  RESEARCH_EFFORT,
  SIMPLE_EFFORT,
  AMBIGUOUS_EFFORT,
]);

/** @param {string} key @returns {object|null} */
export function kickoffEffortFixture(key) {
  return KICKOFF_EFFORT_FIXTURES.find((fixture) => fixture.key === key) ?? null;
}
