#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { reportDirFor } from '../engine/report-dir.mjs';
import { resolveAgent } from '../engine/agent-seam.mjs';

/**
 * Runs the context context compression engine for a single project.
 * 
 * @param {string} projectPath Absolute path to the target project.
 * @param {object} options Override configurations and mocks.
 * @returns {Promise<{
 *   path: string,
 *   agentCompressed: boolean,
 *   historyAppended: boolean,
 *   historySummarized: boolean,
 *   originalAgentLines: number,
 *   newAgentLines: number,
 *   originalHistoryLines: number,
 *   newHistoryLines: number
 * }>}
 */
export async function runCompression(projectPath, options = {}) {
  const log = options.log || (() => {});
  
  const agentPath = path.join(projectPath, 'agent.md');
  const historyPath = path.join(projectPath, 'agent_hist.md');

  const result = {
    path: projectPath,
    agentCompressed: false,
    historyAppended: false,
    historySummarized: false,
    originalAgentLines: 0,
    newAgentLines: 0,
    originalHistoryLines: 0,
    newHistoryLines: 0
  };

  let agentExists = false;
  let historyExists = false;

  try {
    await fs.access(agentPath);
    agentExists = true;
  } catch {}

  try {
    await fs.access(historyPath);
    historyExists = true;
  } catch {}

  // If neither file exists, we have nothing to compress
  if (!agentExists && !historyExists) {
    log(`No agent.md or agent_hist.md found in project: ${projectPath}`);
    return result;
  }

  // C9 (2026-07-11): default from the driver catalogue — the hardcoded
  // 'gemini-1.5-pro' was unrecognized by agy (silent no-op). Compression edits
  // are COMMITTED by the legacy orchestrator, so any truncation is git-recoverable.
  //
  // Wave-1 refactor-in-place (Wave-0 seam: hardcoded-path): the driver module is
  // resolved from the injected agent / config / env, never from an absolute
  // machine-local path. (Wave 1 also DEMOTES compression inside the staged
  // pipeline to an in-memory proposal — see engine/stages/compress.stage.mjs;
  // this legacy writer remains only on the legacy CLI path.)
  const agentFn = resolveAgent({
    agent: options.agent,
    driverPath: options.driverPath,
    model: options.model,
    log,
  });

  let historyContent = '';
  if (historyExists) {
    try {
      historyContent = await fs.readFile(historyPath, 'utf8');
      result.originalHistoryLines = historyContent.split('\n').length;
    } catch (err) {
      log(`Error reading ${historyPath}: ${err.message}`);
    }
  }

  let historyToAppend = '';

  // 1. Process agent.md if it exists
  if (agentExists) {
    let agentContent = '';
    try {
      agentContent = await fs.readFile(agentPath, 'utf8');
      result.originalAgentLines = agentContent.split('\n').length;
    } catch (err) {
      log(`Error reading ${agentPath}: ${err.message}`);
    }

    if (agentContent) {
      const compressPrompt = `You are a repository context compression engine.
Your objective is to parse the 'agent.md' file of a project and:
1. Extract an executive summary of the file. This summary MUST be strictly under 50 lines of text (typically around 10-30 lines). Focus on current active goals, project status, and immediate next steps.
2. Extract the historical logs, older milestones, or log entries that describe past activities or completed tasks. This history will be appended to 'agent_hist.md' to keep 'agent.md' thin.

Below is the content of 'agent.md':
"""
${agentContent}
"""

Provide:
- 'executiveSummary': The new condensed content for 'agent.md' (strictly under 50 lines).
- 'historyToAppend': The history/log entries to append to 'agent_hist.md'. If there is no history to append, return an empty string.`;

      const compressSchema = {
        type: 'object',
        properties: {
          executiveSummary: { type: 'string' },
          historyToAppend: { type: 'string' }
        },
        required: ['executiveSummary', 'historyToAppend']
      };

      let agentResponse = null;
      try {
        agentResponse = await agentFn(compressPrompt, { schema: compressSchema, label: 'compress-agent' });
      } catch (err) {
        log(`Agent call for agent.md compression failed: ${err.message}`);
      }

      // Safe default validation
      let isValid = agentResponse && typeof agentResponse.executiveSummary === 'string' && typeof agentResponse.historyToAppend === 'string';
      
      let newAgentContent;
      if (isValid) {
        newAgentContent = agentResponse.executiveSummary;
        historyToAppend = agentResponse.historyToAppend;
      } else {
        log('Agent response invalid or failed. Defaulting safely to keeping agent.md intact.');
        newAgentContent = agentContent;
        historyToAppend = '';
      }

      // Hard safety constraint: Ensure under 50 lines
      const agentLines = newAgentContent.split('\n');
      if (agentLines.length >= 50) {
        log(`Warning: agent.md summary exceeded 50 lines (${agentLines.length}). Truncating to satisfy invariant.`);
        newAgentContent = agentLines.slice(0, 49).join('\n');
      }

      // Write updated agent.md if it changed or to enforce under 50 lines
      try {
        await fs.writeFile(agentPath, newAgentContent, 'utf8');
        result.agentCompressed = true;
        result.newAgentLines = newAgentContent.split('\n').length;
      } catch (err) {
        log(`Error writing ${agentPath}: ${err.message}`);
      }
    }
  }

  // 2. Append history to agent_hist.md if there is any history to append
  let updatedHistoryContent = historyContent;
  if (historyToAppend && historyToAppend.trim()) {
    if (updatedHistoryContent && !updatedHistoryContent.endsWith('\n')) {
      updatedHistoryContent += '\n';
    }
    updatedHistoryContent += historyToAppend;
    result.historyAppended = true;

    // Write updated history (even if we summarize later, this ensures intermediate states are preserved)
    try {
      await fs.writeFile(historyPath, updatedHistoryContent, 'utf8');
      result.newHistoryLines = updatedHistoryContent.split('\n').length;
    } catch (err) {
      log(`Error writing updated history to ${historyPath}: ${err.message}`);
    }
  } else {
    result.newHistoryLines = result.originalHistoryLines;
  }

  // 3. Summarize agent_hist.md if it exceeds 500 lines
  const currentHistoryLines = updatedHistoryContent.split('\n').length;
  if (currentHistoryLines > 500) {
    const summarizePrompt = `You are a repository context compression engine.
The history log file 'agent_hist.md' has exceeded 500 lines (currently ${currentHistoryLines} lines).
Your task is to apply lossy summarization to condense it to strictly under 500 lines, while ensuring you DO NOT lose critical milestone data.
Critical milestone data includes:
- Dates of key changes or releases
- Specific version numbers
- Major completed features/milestones
- Important architectural decisions or pivots

Condense or merge older log entries, minor updates, repetitive status reports, or debug details.

Below is the full history content:
"""
${updatedHistoryContent}
"""

Provide:
- 'summarizedHistory': The condensed history content (strictly under 500 lines).`;

    const summarizeSchema = {
      type: 'object',
      properties: {
        summarizedHistory: { type: 'string' }
      },
      required: ['summarizedHistory']
    };

    let summaryResponse = null;
    try {
      summaryResponse = await agentFn(summarizePrompt, { schema: summarizeSchema, label: 'summarize-history' });
    } catch (err) {
      log(`Agent call for history summarization failed: ${err.message}`);
    }

    let finalHistoryContent = updatedHistoryContent;
    if (summaryResponse && typeof summaryResponse.summarizedHistory === 'string') {
      finalHistoryContent = summaryResponse.summarizedHistory;
      result.historySummarized = true;
    } else {
      log('History summary response invalid or failed. Retaining original history content.');
    }

    // Hard safety constraint: Ensure under 500 lines
    const finalHistoryLines = finalHistoryContent.split('\n');
    if (finalHistoryLines.length >= 500) {
      log(`Warning: agent_hist.md summary exceeded 500 lines (${finalHistoryLines.length}). Truncating to satisfy invariant.`);
      finalHistoryContent = finalHistoryLines.slice(0, 499).join('\n');
    }

    try {
      await fs.writeFile(historyPath, finalHistoryContent, 'utf8');
      result.newHistoryLines = finalHistoryContent.split('\n').length;
    } catch (err) {
      log(`Error writing summarized history to ${historyPath}: ${err.message}`);
    }
  }

  return result;
}

async function main() {
  try {
    let target = process.argv[2];
    let projects = [];

    // Locate target projects similar to other waves
    if (target) {
      const resolvedTarget = path.resolve(target);
      try {
        const stat = await fs.stat(resolvedTarget);
        if (stat.isDirectory()) {
          projects.push({ path: resolvedTarget });
        } else {
          console.error(`Target path is not a directory: ${resolvedTarget}`);
          process.exit(1);
        }
      } catch (err) {
        console.error(`Target path does not exist: ${resolvedTarget}`);
        process.exit(1);
      }
    } else {
      // Wave-1 refactor-in-place (Wave-0 seam: shared-mutable-state) — the state
      // location is derived from the target root (the CWD when no target is
      // given), never from a CWD-relative path shared across unrelated runs.
      const projectsJsonPath = path.join(reportDirFor(process.cwd()), 'projects.json');
      let exists = false;
      try {
        await fs.access(projectsJsonPath);
        exists = true;
      } catch {}

      if (exists) {
        const content = await fs.readFile(projectsJsonPath, 'utf8');
        const projData = JSON.parse(content);
        projects = projData.map(p => ({ path: path.resolve(p.path) }));
      } else {
        const resolvedCwd = process.cwd();
        projects.push({ path: resolvedCwd });
      }
    }

    if (projects.length === 0) {
      console.log(JSON.stringify([], null, 2));
      return;
    }

    const allResults = [];
    for (const project of projects) {
      const result = await runCompression(project.path);
      allResults.push(result);
    }

    // Write output state for downstream integration — under the TARGET root
    const stateDir = reportDirFor(target ? path.resolve(target) : process.cwd());
    await fs.mkdir(stateDir, { recursive: true });
    const outputPath = path.join(stateDir, 'compression.json');
    await fs.writeFile(outputPath, JSON.stringify(allResults, null, 2), 'utf8');

    console.log(JSON.stringify(allResults, null, 2));
  } catch (error) {
    console.error('Context Compression Engine execution failed:', error.message);
    process.exit(1);
  }
}

const isDirectRun = process.argv[1] && (
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))
);

if (isDirectRun || process.argv[1]?.endsWith('compress.mjs')) {
  main();
}
