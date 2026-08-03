// engine/stages/compress.stage.mjs — Wave 1: compression DEMOTED to a proposal.
//
// bin/compress.mjs writes agent.md and agent_hist.md directly. Inside a
// read-only analysis pass that is a zero-write-invariant violation by
// construction — and it is also the wrong shape: a lossy LLM rewrite of a
// project's context file is exactly the kind of change a human should approve
// before it lands, not something a background scan does on its way past.
//
// So this stage computes the compression IN MEMORY and emits a PROPOSAL finding
// carrying the rendered diff. Nothing is written. Wave 3's Apply executor
// realises approved proposals by hashing the in-memory content into the temp
// index (Amendment C.iv: tool-generated blobs are never re-read from the
// working tree), so the bytes the human approved are exactly the bytes
// committed.

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';
import { renderUnifiedDiff, diffStats } from '../diff.mjs';
import { toPosixRel } from '../glob.mjs';

const AGENT_FILE = 'agent.md';
const HISTORY_FILE = 'agent_hist.md';
const AGENT_LINE_CAP = 50;

export const compressStage = {
  name: 'compress',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // Unbounded cap: git presence does not gate this stage's findings (see
    // analyze.stage.mjs for the declaration semantics).
    findings: Number.POSITIVE_INFINITY,
    note: 'no repo — compression is an in-memory proposal over file content and does not consult git',
  },

  async run(ctx) {
    const agentPath = path.join(ctx.rootPath, AGENT_FILE);

    // Wave 2: this stage puts a whole file into a prompt, so it is subject to
    // the universal pre-LLM gate like every other LLM stage. A flagged agent.md
    // is not compressed at all — there is no "compress it but mask the secret"
    // path, because a partially masked secret in a prompt is still a leak.
    const blocked = ctx.state.llmBlocked || new Set();
    if (blocked.has(toPosixRel(AGENT_FILE))) {
      return makeStageResult({
        stage: compressStage.name,
        status: STATUS.PARTIAL,
        coverage: { scanned: 0, skipped: 1, errored: 0, note: `${AGENT_FILE} was flagged by the pre-LLM secret gate — it is NOT sent to a model, so no compression proposal exists for this run` },
        findings: [],
        notes: [`${AGENT_FILE} is withheld from every LLM stage by the secret gate; resolve the flagged content (see its BLOCKED tile) and re-run to get a compression proposal`],
      });
    }

    const before = await readOrNull(ctx, agentPath);

    if (before === null) {
      return makeStageResult({
        stage: compressStage.name,
        status: STATUS.OK,
        coverage: { scanned: 0, skipped: 0, errored: 0, note: `no ${AGENT_FILE} at the run root — nothing to compress` },
        findings: [],
      });
    }

    const prompt = `You are a repository context compression engine.
Parse the 'agent.md' file below and produce:
1. 'executiveSummary' — the new condensed content for 'agent.md', strictly under ${AGENT_LINE_CAP} lines. Focus on current active goals, project status, and immediate next steps.
2. 'historyToAppend' — the historical log entries to move into 'agent_hist.md'. Empty string if there is none.

Below is the content of '${AGENT_FILE}':
"""
${before}
"""`;

    const schema = {
      type: 'object',
      properties: {
        executiveSummary: { type: 'string' },
        historyToAppend: { type: 'string' },
      },
      required: ['executiveSummary', 'historyToAppend'],
    };

    let reply = null;
    const errors = [];
    try {
      reply = await ctx.agent(prompt, { schema, label: 'compress-agent-proposal' });
    } catch (err) {
      errors.push({ name: err.name || 'Error', message: `compression proposal could not be computed: ${err.message}` });
    }

    const valid = reply && typeof reply.executiveSummary === 'string' && typeof reply.historyToAppend === 'string';
    if (!valid) {
      // No proposal is a PARTIAL stage, never a silent success — but it is also
      // not a run-killer: the rest of the analysis is unaffected, and nothing
      // was written either way.
      return makeStageResult({
        stage: compressStage.name,
        status: STATUS.PARTIAL,
        coverage: { scanned: 1, skipped: 1, errored: errors.length, note: 'the compression proposal did not come back usable — agent.md is untouched (it always is: this stage never writes)' },
        errors: errors.length ? errors : [{ message: 'compression agent returned a reply that did not match the schema' }],
        findings: [],
      });
    }

    let after = reply.executiveSummary;
    const lines = after.split('\n');
    let truncated = false;
    if (lines.length >= AGENT_LINE_CAP) {
      after = lines.slice(0, AGENT_LINE_CAP - 1).join('\n');
      truncated = true;
    }

    const findings = [];
    if (after !== before) {
      findings.push({
        stage: compressStage.name,
        kind: 'compression-proposal',
        action: 'propose-content',
        path: toPosixRel(AGENT_FILE),
        absolutePath: agentPath,
        proposal: {
          // The bytes a human approves; Apply hashes THESE, never a re-read.
          content: after,
          diff: renderUnifiedDiff(before, after, { fromLabel: `a/${AGENT_FILE}`, toLabel: `b/${AGENT_FILE}` }),
          stats: diffStats(before, after),
          truncatedToLineCap: truncated,
        },
      });
    }

    const historyToAppend = reply.historyToAppend;
    if (historyToAppend && historyToAppend.trim()) {
      const historyPath = path.join(ctx.rootPath, HISTORY_FILE);
      const historyBefore = (await readOrNull(ctx, historyPath)) ?? '';
      const historyAfter = (historyBefore && !historyBefore.endsWith('\n') ? historyBefore + '\n' : historyBefore) + historyToAppend;
      findings.push({
        stage: compressStage.name,
        kind: 'compression-proposal',
        action: 'propose-content',
        path: toPosixRel(HISTORY_FILE),
        absolutePath: historyPath,
        proposal: {
          content: historyAfter,
          diff: renderUnifiedDiff(historyBefore, historyAfter, { fromLabel: `a/${HISTORY_FILE}`, toLabel: `b/${HISTORY_FILE}` }),
          stats: diffStats(historyBefore, historyAfter),
          createsFile: historyBefore === '',
        },
      });
    }

    return makeStageResult({
      stage: compressStage.name,
      status: STATUS.OK,
      coverage: { scanned: findings.length ? findings.length : 1, skipped: 0, errored: 0 },
      findings,
      notes: [
        `${findings.length} content proposal(s) computed IN MEMORY — this stage writes nothing; approval happens in the panel and realisation in Wave-3 Apply`,
        ...(truncated ? [`the proposed ${AGENT_FILE} exceeded the ${AGENT_LINE_CAP}-line cap and was truncated to satisfy the invariant`] : []),
      ],
    });
  },
};

async function readOrNull(ctx, p) {
  try {
    return await ctx.fs.readFile(p, 'utf8');
  } catch {
    return null;
  }
}

export default compressStage;
