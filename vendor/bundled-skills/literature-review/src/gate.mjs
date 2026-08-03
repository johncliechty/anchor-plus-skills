import readline from 'node:readline';

/**
 * Constructs the prompt for the On-Demand Copilot.
 */
export function constructCopilotPrompt(chunks, query) {
  const contextText = Array.isArray(chunks) ? chunks.join('\n\n') : String(chunks || '');
  return [
    `You are the On-Demand Copilot for literature review analysis.`,
    `Your task is to answer the user's query using strictly and only the ingested text context provided below.`,
    `Do not include external information or speculate beyond what is written.`,
    `If the text does not contain the answer, state that the answer is not present in the ingested text.`,
    ``,
    `=== INGESTED TEXT CONTEXT ===`,
    contextText,
    ``,
    `=== USER QUERY ===`,
    query,
    ``,
    `Answer:`
  ].join('\n');
}

/**
 * Prompts a question to the console and resolves with the response.
 */
function askQuestion(query) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });
  return new Promise((resolve) => {
    rl.question(query, (answer) => {
      rl.close();
      resolve(answer);
    });
  });
}

/**
 * Mixed-Initiative Gate & On-Demand Copilot.
 * 
 * - Pauses execution to prompt the user with the vetted candidate list.
 * - Provides an On-Demand Copilot for granular interrogation (micro-queries).
 * - Resumes on 'approve' or aborts on 'reject'.
 * - Supports mock inputs via `options.mockUser` for automated testing.
 */
export async function runMixedInitiativeGate(candidates, chunks, options = {}) {
  const log = options.log || console.log;
  const agent = options.agent || (async (prompt) => `[Default Copilot Response]`);
  const mockUser = options.mockUser || null;

  // C8 (2026-07-11): TTY detection — the raw readline loop used to hang FOREVER when
  // an agent drove the CLI without a terminal (and without knowing about --mock-user).
  // Non-interactive + no mock sequence ⇒ AUTO-APPROVE with a loud stamp; the human
  // gate is only a gate when a human is actually attached.
  const interactive = options.interactive ?? !!process.stdin.isTTY;
  if (!mockUser && !interactive) {
    log('[Gate] NON-INTERACTIVE stdin and no --mock-user: AUTO-APPROVING the candidate list.');
    log('[Gate] (Stamp: the mixed-initiative human gate did NOT run — no human was attached.)');
    return { approved: true, queries: [], autoApproved: true };
  }

  log('\n==================================================');
  log('MIXED-INITIATIVE GATE: VETTED CANDIDATE LIST');
  log('==================================================');
  if (!candidates || candidates.length === 0) {
    log('No candidates available.');
  } else {
    candidates.forEach((cand, idx) => {
      const title = cand.title || 'Untitled';
      const venue = cand.venue || 'Unknown Venue';
      const year = cand.year || 'Unknown Year';
      const citations = cand.citationCount !== undefined ? cand.citationCount : 0;
      log(`${idx + 1}. [${venue} ${year}] ${title} (Citations: ${citations}) - ID: ${cand.paperId || 'N/A'}`);
    });
  }
  log('==================================================\n');

  log('Entering On-Demand Copilot Chat Loop.');
  log('Ask questions about the ingested text context, or enter "approve" / "reject".\n');

  const queries = [];

  if (mockUser) {
    log(`[Gate] Running with mock user sequence: "${mockUser}"`);
    const actions = mockUser.split('|').map(s => s.trim()).filter(Boolean);

    for (const action of actions) {
      if (action.toLowerCase() === 'approve') {
        log('[Mock User] approve');
        log('Resuming execution as approved by user.');
        return { approved: true, queries };
      }
      if (action.toLowerCase() === 'reject') {
        log('[Mock User] reject');
        throw new Error('Execution rejected by user');
      }

      // Treat anything else as a query
      const queryText = action.replace(/^(query|q):\s*/i, '');
      log(`[Mock User] Query: ${queryText}`);

      const prompt = constructCopilotPrompt(chunks, queryText);
      const response = await agent(prompt, { label: 'copilot:query', query: queryText });
      log(`[Copilot Response]:\n${response}\n`);
      queries.push({ query: queryText, response });
    }

    // Default fallback if mock sequence runs out without approve/reject
    log('Warning: Mock sequence finished without explicit approve or reject. Resuming by default.');
    return { approved: true, queries };
  }

  // Interactive Loop
  while (true) {
    const input = await askQuestion('Copilot> ');
    const trimmed = input.trim();
    if (!trimmed) continue;

    if (trimmed.toLowerCase() === 'approve') {
      log('Resuming execution as approved by user.');
      return { approved: true, queries };
    }
    if (trimmed.toLowerCase() === 'reject') {
      throw new Error('Execution rejected by user');
    }

    // Treat as query
    const fullPrompt = constructCopilotPrompt(chunks, trimmed);
    try {
      const response = await agent(fullPrompt, { label: 'copilot:query', query: trimmed });
      log(`\n[Copilot Response]:\n${response}\n`);
      queries.push({ query: trimmed, response });
    } catch (err) {
      log(`Error executing copilot query: ${err.message}`);
    }
  }
}
