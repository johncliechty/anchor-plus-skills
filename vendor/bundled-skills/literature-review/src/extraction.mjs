import { validateSchema } from './validateSchema.mjs';
import {
  LIT_REVIEW_SAFETY_FLOOR,
} from 'fil<path>';

// Generator Schema combining both AssumptionsLedger and ParameterizedMatrix structures
export const GENERATOR_SCHEMA = {
  type: 'object',
  required: ['ledger', 'matrix'],
  properties: {
    ledger: {
      type: 'object',
      required: ['assumptions'],
      properties: {
        assumptions: {
          type: 'array',
          items: {
            type: 'object',
            required: ['id', 'statement', 'type', 'source'],
            properties: {
              id: { type: 'string' },
              statement: { type: 'string' },
              type: { type: 'string', enum: ['OBSERVED', 'CORROBORATED', 'CLAIMED'] },
              source: {
                type: 'object',
                required: ['title', 'authors', 'venue', 'year'],
                properties: {
                  title: { type: 'string' },
                  authors: { type: 'array', items: { type: 'string' } },
                  venue: { type: 'string' },
                  year: { type: 'integer' },
                  citationCount: { type: 'integer' },
                  entityId: { type: 'string' }
                }
              },
              confidence: { type: 'number', minimum: 0, maximum: 1 },
              context: { type: 'string' },
              corroborationSources: { type: 'array', items: { type: 'string' } },
              conflicts: {
                type: 'array',
                items: {
                  type: 'object',
                  required: ['statement', 'sourceId'],
                  properties: {
                    statement: { type: 'string' },
                    sourceId: { type: 'string' }
                  }
                }
              }
            }
          }
        }
      }
    },
    matrix: {
      type: 'object',
      required: ['columns', 'rows'],
      properties: {
        columns: {
          type: 'array',
          items: { type: 'string' }
        },
        rows: {
          type: 'array',
          items: {
            type: 'object',
            required: ['paperId', 'title', 'values'],
            properties: {
              paperId: { type: 'string' },
              title: { type: 'string' },
              values: {
                type: 'object',
                additionalProperties: {
                  type: ['string', 'number', 'boolean', 'null']
                }
              }
            }
          }
        }
      }
    }
  }
};

// Shark Schema for critique findings
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
        required: ['severity', 'topic', 'message'],
        properties: {
          severity: { enum: ['BLOCKER', 'MAJOR', 'MINOR', 'NIT'] },
          topic: { type: 'string' },
          message: { type: 'string' }
        }
      }
    }
  }
};

// Synthesizer Schema for steering instruction
export const SYNTHESIZER_SCHEMA = {
  type: 'object',
  required: ['status', 'probingBrief'],
  properties: {
    status: { enum: ['correct', 'needs-refinement'] },
    probingBrief: { type: 'string' }
  }
};

const STOPWORDS = new Set([
  'the', 'a', 'an', 'is', 'are', 'was', 'be', 'being', 'been', 'of', 'to', 'about',
  'on', 'in', 'for', 'and', 'or', 'that', 'this', 'it', 'its', 'too', 'very', 'as',
  'by', 'at', 'not', 'no', 'but', 'with', 'should', 'must', 'need', 'needs', 'has',
  'have', 'plan', 'draft', 'there', 'here', 'we', 'you',
]);

export function normalizeTopic(s) {
  const tokens = String(s ?? '').toLowerCase().match(/[a-z0-9]+/g) || [];
  const kept = tokens.filter((t) => t.length > 1 && !STOPWORDS.has(t));
  return (kept.length ? kept : tokens).sort().join('-');
}

export function normalizeFindingId(f) {
  const topicKey = normalizeTopic(f.topic);
  if (topicKey) return `topic:${topicKey}`;
  const messageKey = normalizeTopic(f.message) || 'unspecified';
  return `msg:${messageKey}`;
}

export function tallyFindings(reviews, priorBlockerIds = []) {
  const prior = new Set(priorBlockerIds);
  const byId = new Map();

  for (const rv of reviews) {
    for (const f of rv.findings || []) {
      const id = normalizeFindingId(f);
      if (!byId.has(id)) {
        byId.set(id, {
          id,
          severity: f.severity,
          topic: f.topic,
          message: f.message,
          agreement: 0,
          raisedBy: [],
        });
      }
      const entry = byId.get(id);
      entry.agreement += 1;
      entry.raisedBy.push(rv.reviewer);
      const ranks = { BLOCKER: 4, MAJOR: 3, MINOR: 2, NIT: 1 };
      if (ranks[f.severity] > ranks[entry.severity]) {
        entry.severity = f.severity;
      }
    }
  }

  const findings = [...byId.values()];
  const blockers = findings.filter(
    (f) => (f.severity === 'BLOCKER' || f.severity === 'MAJOR') && f.agreement >= 2
  );
  const newBlockers = blockers.filter((f) => !prior.has(f.id));
  const dry = newBlockers.length === 0;

  return {
    findings,
    blockers,
    newBlockers,
    dry,
  };
}

function generatorPrompt(chunk, columns, options = {}) {
  const source = options.sourceInfo ?? { title: 'Unknown Title', authors: ['Unknown Author'], venue: 'Unknown Venue', year: 2026 };
  const conflictText = options.knownMockConflict
    ? `\nKNOWN MOCK CONFLICT to incorporate if relevant: ${JSON.stringify(options.knownMockConflict)}`
    : '';
  return [
    `You are the Literature Review Ingestion Generator.`,
    `Your task is to parse the following text chunk and extract an Assumptions Ledger and a Parameterized Matrix row.`,
    ``,
    `=== SOURCE INFORMATION ===`,
    JSON.stringify(source, null, 2),
    ``,
    `=== USER-DEFINED COLUMNS ===`,
    JSON.stringify(columns),
    conflictText,
    ``,
    `=== TEXT CHUNK ===`,
    chunk,
    ``,
    `Extract observations as OBSERVED (factual findings/data) and assertions/hypotheses as CLAIMED.`,
    `Populate the matrix columns. Ensure all outputs strictly validate against the AssumptionsLedger and ParameterizedMatrix schemas.`
  ].join('\n');
}

function refinementPrompt(chunk, columns, currentDraft, direction, options = {}) {
  return [
    `You are the Literature Review Ingestion Generator.`,
    `Refine the current draft Assumptions Ledger and Parameterized Matrix based on the Synthesizer direction.`,
    ``,
    `=== CURRENT DRAFT ===`,
    JSON.stringify(currentDraft, null, 2),
    ``,
    `=== SYNTHESIZER DIRECTION ===`,
    direction,
    ``,
    `=== TEXT CHUNK ===`,
    chunk,
    ``,
    `Correct any issues. Make sure the output strictly validates against the AssumptionsLedger and ParameterizedMatrix schemas.`
  ].join('\n');
}

function sharkPrompt(role, chunk, columns, draft, options = {}) {
  const conflictText = options.knownMockConflict
    ? `\nKNOWN MOCK CONFLICT: ${JSON.stringify(options.knownMockConflict)}`
    : '';
  return [
    `You are the ${role} Shark in a literature review extraction critique loop.`,
    `Your job is to identify errors, hallucinated claims, incorrect types (OBSERVED vs CLAIMED), or missing conflicts in the current draft.`,
    ``,
    `=== TEXT CHUNK ===`,
    chunk,
    ``,
    `=== USER-DEFINED COLUMNS ===`,
    JSON.stringify(columns),
    conflictText,
    ``,
    `=== CURRENT DRAFT ===`,
    JSON.stringify(draft, null, 2),
    ``,
    `Identify findings. Be adversarial and critical. If something is wrong or missing, raise a BLOCKER or MAJOR finding.`
  ].join('\n');
}

function synthesizerPrompt(chunk, columns, draft, reviews, options = {}) {
  return [
    `You are the Literature Review Ingestion Synthesizer.`,
    `Analyze the current draft and the critiques from the 3 Sharks.`,
    ``,
    `=== CURRENT DRAFT ===`,
    JSON.stringify(draft, null, 2),
    ``,
    `=== SHARK REVIEWS ===`,
    JSON.stringify(reviews, null, 2),
    ``,
    `Steer the generator on what to correct in the next iteration. Output a status (correct or needs-refinement) and a probingBrief.`
  ].join('\n');
}

export async function runExtractionLoop(chunk, columns, agent, options = {}) {
  const maxRounds = options.maxRounds ?? 3;
  let draft = null;
  let priorBlockerIds = [];
  const roundData = [];

  for (let round = 1; round <= maxRounds; round++) {
    if (round === 1) {
      draft = await agent(generatorPrompt(chunk, columns, options), {
        label: `generator:draft:r${round}`,
        schema: GENERATOR_SCHEMA,
      });
    } else {
      const lastRound = roundData[roundData.length - 1];
      draft = await agent(refinementPrompt(chunk, columns, draft, lastRound.direction.probingBrief, options), {
        label: `generator:refine:r${round}`,
        schema: GENERATOR_SCHEMA,
      });
    }

    validateSchema(draft.ledger, 'AssumptionsLedger');
    validateSchema(draft.matrix, 'ParameterizedMatrix');

    const reviews = [];
    const roles = ['Skeptic', 'Contrarian', 'Analyst'];
    for (const role of roles) {
      const review = await agent(sharkPrompt(role, chunk, columns, draft, options), {
        label: `shark:${role}:r${round}`,
        schema: SHARK_SCHEMA,
      });
      reviews.push({
        reviewer: role,
        findings: review.findings ?? [],
      });
    }

    const tally = tallyFindings(reviews, priorBlockerIds);

    for (const b of tally.blockers) {
      priorBlockerIds.push(b.id);
    }
    priorBlockerIds = [...new Set(priorBlockerIds)];

    if (tally.dry) {
      return {
        ledger: draft.ledger,
        matrix: draft.matrix,
        rounds: round,
        converged: true,
        history: roundData,
      };
    }

    const synthResult = await agent(synthesizerPrompt(chunk, columns, draft, reviews, options), {
      label: `synthesizer:direct:r${round}`,
      schema: SYNTHESIZER_SCHEMA,
    });

    roundData.push({
      round,
      draft,
      reviews,
      tally,
      direction: synthResult,
    });
  }

  return {
    ledger: draft.ledger,
    matrix: draft.matrix,
    rounds: maxRounds,
    converged: false,
    history: roundData,
  };
}

// ---------------------------------------------------------------------------
// C8 (2026-07-11) — the LEAN extraction path: ONE model call per paper plus a
// DETERMINISTIC quote-grounding check (zero extra calls).
//
// The Wave-3 per-chunk loop above (generator + 3 Sharks + Synthesizer per chunk,
// up to 3 rounds) costs ~5 calls/round × rounds × chunks × papers — thousands of
// calls for a modest review, which is why it never gained a production caller.
// Claim extraction from one paper does not need an adversarial court: it needs
// one careful pass whose every assumption carries a VERBATIM supporting quote,
// and a deterministic check that the quote actually appears in the paper's text.
// Fabricated support dies on a string match, not on a model's opinion. The
// adversarial machinery belongs at the END, over the synthesized cross-paper
// ledger (see bin/cli.mjs), where conflicts actually live.
// ---------------------------------------------------------------------------

export const LEAN_LEDGER_SCHEMA = {
  type: 'object',
  required: ['assumptions'],
  properties: {
    assumptions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim_id', 'statement', 'quote', 'column'],
        properties: {
          claim_id: { type: 'string' },
          statement: { type: 'string' },
          quote: { type: 'string' },
          column: { type: 'string' },
          context: { type: 'string' },
        },
      },
    },
  },
};

const normForGrounding = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/**
 * Extract an assumptions ledger from ONE paper's text with ONE model call, then
 * ground every assumption deterministically: its `quote` must appear verbatim
 * (whitespace/punctuation-normalized) in the provided text. Grounded assumptions
 * enter the ledger as CLAIMED (honest — one model, one pass); an assumption whose
 * quote is NOT in the text is marked UNVERIFIED-FABRICATED-QUOTE and EXCLUDED from
 * the ledger (reported separately — never silently kept).
 *
 * @param {object}   paper    { paperId, title, authors, venue, year, citationCount }
 * @param {string}   text     the paper's available text (abstract and/or chunks joined)
 * @param {string[]} columns  the review's comparison columns
 * @param {Function} agent    (prompt, opts) => reply (schema-forced)
 * @returns {Promise<{ledger:{assumptions:object[]}, rejected:object[], calls:number}>}
 */
export async function extractLedgerLean(paper, text, columns, agent) {
  if (typeof agent !== 'function') throw new Error('extractLedgerLean requires an agent() function');

  // Track B7 W2 — safety floor is depth-invariant authority for claim extraction.
  // Read LIT_REVIEW_SAFETY_FLOOR at claim-extraction start (Contract 4). Depth/band
  // branches must never assign floor fields false/0; floor is not a function of band.
  const floor = LIT_REVIEW_SAFETY_FLOOR;
  if (floor.requireQuoteGrounding !== true) {
    throw new Error('LIT_REVIEW_SAFETY_FLOOR.requireQuoteGrounding must remain true');
  }
  if (floor.oneCallPerPaperExtraction !== true) {
    throw new Error('LIT_REVIEW_SAFETY_FLOOR.oneCallPerPaperExtraction must remain true');
  }
  const minGrounded = Number(floor.minGroundedClaimsPerPaper);
  if (!(Number.isInteger(minGrounded) && minGrounded >= 1)) {
    throw new Error('LIT_REVIEW_SAFETY_FLOOR.minGroundedClaimsPerPaper must be integer ≥ 1');
  }

  const body = String(text || '').trim();
  if (!body) return { ledger: { assumptions: [] }, rejected: [], calls: 0, floor };

  const prompt = [
    `[literature-review LEAN extraction — one pass, quotes mandatory]`,
    `Extract the paper's load-bearing claims relevant to these comparison columns: ${columns.join(', ')}.`,
    `For EVERY assumption: claim_id = a short stable id (e.g. "${(paper.paperId || 'P').slice(0, 8)}-throughput");`,
    `statement = the claim in your words; quote = the VERBATIM supporting sentence copied from the text`,
    `(it will be string-matched — a paraphrase or invented quote is automatically rejected);`,
    `column = which comparison column it informs.`,
    ``,
    `=== PAPER: ${paper.title || paper.paperId} (${paper.venue || '?'} ${paper.year || '?'}) ===`,
    body,
    `=== END PAPER ===`,
  ].join('\n');

  // oneCallPerPaperExtraction: exactly one agent call per paper (floor-enforced).
  // Single await is the gate — never loop or multi-call by depth/band.
  // floor.oneCallPerPaperExtraction was already verified true at extract entry above.
  const out = await agent(prompt, { label: `extract:${paper.paperId || 'paper'}`, role: 'extraction', schema: LEAN_LEDGER_SCHEMA });
  const calls = 1;
  const raw = Array.isArray(out?.assumptions) ? out.assumptions : [];
  const hay = normForGrounding(body);
  const assumptions = [];
  const rejected = [];
  raw.forEach((a, i) => {
    const quote = String(a?.quote || '');
    // requireQuoteGrounding: fabricated support dies on a string match.
    // Floor is sole authority — never read grounding truth from depth profiles.
    const grounded =
      floor.requireQuoteGrounding === true
        ? quote.length >= 10 && hay.includes(normForGrounding(quote))
        : Boolean(quote);
    const entry = {
      id: `A-${(paper.paperId || 'P').slice(0, 8)}-${i}`,
      claim_id: String(a?.claim_id || `c-${i}`),
      statement: String(a?.statement || ''),
      type: 'CLAIMED', // one model, one pass — never self-assigned higher
      quote,
      column: String(a?.column || ''),
      source: {
        title: paper.title || 'Untitled',
        authors: (paper.authors || []).map((x) => x?.name || String(x)),
        venue: paper.venue || 'Unknown Venue',
        year: paper.year || 0,
        citationCount: paper.citationCount || 0,
        entityId: paper.paperId || '',
      },
    };
    if (grounded) assumptions.push(entry);
    else rejected.push({ ...entry, rejection: 'UNVERIFIED-FABRICATED-QUOTE: quote not found in the paper text' });
  });

  // minGroundedClaimsPerPaper: after quote-grounding filter, fail closed if below floor.
  // Empty paper body returns early above (no claims possible); this path is post-agent.
  if (assumptions.length < minGrounded) {
    const err = new Error(
      `extractLedgerLean: grounded claims ${assumptions.length} < ` +
        `LIT_REVIEW_SAFETY_FLOOR.minGroundedClaimsPerPaper ${minGrounded}`,
    );
    err.code = 'LIT_REVIEW_MIN_GROUNDED_CLAIMS';
    /** @type {any} */ (err).grounded = assumptions.length;
    /** @type {any} */ (err).minGrounded = minGrounded;
    /** @type {any} */ (err).rejected = rejected;
    /** @type {any} */ (err).floor = floor;
    throw err;
  }

  return {
    ledger: { assumptions },
    rejected,
    calls,
    floor,
    minGroundedClaimsPerPaper: minGrounded,
  };
}

/** Re-export floor for extract consumers / hermetic floor-consumption fixtures. */
export { LIT_REVIEW_SAFETY_FLOOR };
