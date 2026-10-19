#!/usr/bin/env node

import { exec } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';
import { reportDirFor } from '../engine/report-dir.mjs';

const execAsync = promisify(exec);

/**
 * Checks the git repository status for a given project path.
 * 
 * @param {string} projectPath 
 * @param {object} options 
 * @returns {Promise<object>}
 */
export async function checkProjectHygiene(projectPath, options = {}) {
  const execFn = options.exec || execAsync;
  const resolvedPath = path.resolve(projectPath);

  const status = {
    isGit: false,
    isDirty: false,
    hasUnpushedBranch: false,
    hasUnpushedCommits: false,
    currentBranch: '',
    error: null
  };

  try {
    const stats = await fs.stat(resolvedPath);
    if (!stats.isDirectory()) {
      throw new Error(`Path ${resolvedPath} is not a directory`);
    }

    // Check if inside a git repository
    try {
      const { stdout } = await execFn('git rev-parse --is-inside-work-tree', { cwd: resolvedPath });
      if (stdout.trim() === 'true') {
        status.isGit = true;
      }
    } catch {
      status.isGit = false;
    }

    if (status.isGit) {
      // 1. Check for uncommitted changes
      const { stdout: statusOut } = await execFn('git status --porcelain', { cwd: resolvedPath });
      if (statusOut.trim().length > 0) {
        status.isDirty = true;
      }

      // 2. Check current branch
      try {
        const { stdout: branchOut } = await execFn('git rev-parse --abbrev-ref HEAD', { cwd: resolvedPath });
        status.currentBranch = branchOut.trim();
      } catch {
        status.currentBranch = 'HEAD';
      }

      // 3. Check upstream branch (if HEAD is not detached)
      let upstream = '';
      if (status.currentBranch && status.currentBranch !== 'HEAD') {
        try {
          const { stdout: upstreamOut } = await execFn('git rev-parse --abbrev-ref @{u}', { cwd: resolvedPath });
          upstream = upstreamOut.trim();
        } catch {
          // If no upstream is configured, it means it's an unpushed branch
          status.hasUnpushedBranch = true;
        }
      }

      // 4. Check for unpushed commits if upstream exists
      if (upstream && !status.hasUnpushedBranch) {
        const { stdout: cherryOut } = await execFn('git cherry', { cwd: resolvedPath });
        if (cherryOut.trim().length > 0) {
          status.hasUnpushedCommits = true;
        }
      }
    }
  } catch (err) {
    status.error = err.message;
  }

  return status;
}

/**
 * Helper to prompt the user using the strictly required 5-point Human Decision-Making format.
 */
export async function promptUser(questionObj, options = {}) {
  const outputStream = options.stdout || process.stdout;
  const inputStream = options.stdin || process.stdin;

  outputStream.write(`\n=== HUMAN DECISION REQUIRED ===\n`);
  outputStream.write(`[Question]\n${questionObj.question}\n\n`);
  outputStream.write(`[Context]\n${questionObj.context}\n\n`);
  outputStream.write(`[Explanation]\n${questionObj.explanation}\n\n`);
  outputStream.write(`[Options]\n`);
  questionObj.options.forEach((opt, idx) => {
    outputStream.write(`  ${idx + 1}. ${opt}\n`);
  });
  outputStream.write(`\n[Recommendation]\n${questionObj.recommendation}\n`);
  outputStream.write(`================================\n`);

  const rl = readline.createInterface({ input: inputStream, output: outputStream });
  try {
    const answer = await rl.question('Select an option (number): ');
    return answer.trim();
  } finally {
    rl.close();
  }
}

/**
 * Runs the hygiene check for a project path. If dirty/unclean, it presents a compliant nag prompt
 * and halts execution unless bypassed by the user in interactive mode.
 */
export async function runHygieneCheck(projectPath, options = {}) {
  const outputStream = options.stdout || process.stdout;
  const status = await checkProjectHygiene(projectPath, options);

  let warnings = [];
  if (!status.isGit) {
    warnings.push('The target directory is not a Git repository.');
  } else {
    if (status.isDirty) {
      warnings.push('There are uncommitted changes in the repository.');
    }
    if (status.hasUnpushedBranch) {
      warnings.push(`The current branch '${status.currentBranch}' has no upstream tracking branch configured (unpushed branch).`);
    }
    if (status.hasUnpushedCommits) {
      warnings.push(`There are commits on branch '${status.currentBranch}' that have not been pushed to the remote repository.`);
    }
  }

  if (warnings.length === 0) {
    outputStream.write(`Git hygiene check passed for project: ${projectPath}\n`);
    return true;
  }

  // C9 (2026-07-11): a NON-GIT directory is a HARD refusal — no "force proceed"
  // exists for it, interactive or not. tidy-idy's entire safety story is now
  // "git is the archive" (removals are committed; recovery = git revert), so
  // without git there is NO backstop and the old interactive bypass let one
  // mistaken keypress expose unversioned files to permanent deletion.
  if (!status.isGit) {
    outputStream.write(`REFUSED: '${projectPath}' is not a Git repository — tidy-idy only operates where git can undo it.\n`);
    throw new Error(`hygiene refusal: ${projectPath} is not a git repository (no force-proceed for non-git)`);
  }

  // Define the compliant 5-point prompt
  const questionObj = {
    question: 'How would you like to handle the repository hygiene warnings before proceeding with tidy-idy?',
    context: `The project at '${projectPath}' has the following Git hygiene issues:\n` + warnings.map(w => `- ${w}`).join('\n'),
    explanation: 'Running tidy-idy can archive or permanently delete files. Having uncommitted changes or unpushed commits increases the risk of loss of work or makes it difficult to revert changes if needed.',
    options: [
      'Abort the execution to clean up Git status manually (commit, stash, or push) [Highly Recommended].',
      'Ignore warnings and force proceed with tidy-idy execution.',
      'Stash current changes automatically and proceed (Note: does not push commits).'
    ],
    recommendation: 'Choose option 1: Abort the execution, commit or stash your changes, push your branch, and then run tidy-idy again.'
  };

  const isInteractive = options.interactive !== undefined ? options.interactive : process.stdin.isTTY;

  if (!isInteractive) {
    // Non-interactive mode: print prompt and halt execution
    outputStream.write(`\n=== GIT HYGIENE PRE-FLIGHT ALERT (NON-INTERACTIVE) ===\n`);
    outputStream.write(`[Question]\n${questionObj.question}\n\n`);
    outputStream.write(`[Context]\n${questionObj.context}\n\n`);
    outputStream.write(`[Explanation]\n${questionObj.explanation}\n\n`);
    outputStream.write(`[Options]\n`);
    questionObj.options.forEach((opt, idx) => {
      outputStream.write(`  ${idx + 1}. ${opt}\n`);
    });
    outputStream.write(`\n[Recommendation]\n${questionObj.recommendation}\n`);
    outputStream.write(`========================================================\n`);

    if (options.throwOnError) {
      throw new Error(`Git hygiene check failed: ${warnings.join('; ')}`);
    } else {
      process.exit(1);
    }
  }

  // Interactive mode
  const answer = await promptUser(questionObj, options);

  if (answer === '2') {
    outputStream.write(`Proceeding with tidy-idy execution despite Git hygiene warnings.\n`);
    return true;
  } else if (answer === '3') {
    if (status.isGit) {
      outputStream.write(`Attempting to automatically stash changes...\n`);
      const execFn = options.exec || execAsync;
      try {
        await execFn('git stash push -m "tidy-idy auto-stash"', { cwd: path.resolve(projectPath) });
        outputStream.write(`Changes stashed successfully. Proceeding with tidy-idy execution.\n`);
        return true;
      } catch (err) {
        outputStream.write(`Failed to auto-stash changes: ${err.message}\n`);
        if (options.throwOnError) {
          throw new Error(`Git stash failed: ${err.message}`);
        } else {
          process.exit(1);
        }
      }
    } else {
      outputStream.write(`Cannot auto-stash: Target directory is not a Git repository.\n`);
      if (options.throwOnError) {
        throw new Error('Not a Git repository, cannot auto-stash');
      } else {
        process.exit(1);
      }
    }
  } else {
    outputStream.write(`Aborted by user request.\n`);
    if (options.throwOnError) {
      throw new Error('Aborted by user request.');
    } else {
      process.exit(1);
    }
  }
}

async function main() {
  try {
    let target = process.argv[2];
    let projectPaths = [];

    if (target) {
      projectPaths.push(path.resolve(target));
    } else {
      // Wave-1 refactor-in-place (Wave-0 seam: shared-mutable-state). With no
      // target argument the TARGET IS the current directory — explicitly, by
      // derivation — so the state we read is this target's, never whatever run's
      // state happened to be sitting in the launch directory.
      const targetRoot = path.resolve('.');
      const projectsJsonPath = path.join(reportDirFor(targetRoot), 'projects.json');
      let exists = false;
      try {
        await fs.access(projectsJsonPath);
        exists = true;
      } catch {}

      if (exists) {
        const content = await fs.readFile(projectsJsonPath, 'utf8');
        const projects = JSON.parse(content);
        if (Array.isArray(projects)) {
          projectPaths = projects.map(p => p.path);
        }
      }

      if (projectPaths.length === 0) {
        projectPaths.push(path.resolve('.'));
      }
    }

    for (const projectPath of projectPaths) {
      await runHygieneCheck(projectPath);
    }
  } catch (error) {
    console.error('Hygiene pre-flight execution failed:', error.message);
    process.exit(1);
  }
}

const isDirectRun = process.argv[1] && (
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))
);

if (isDirectRun || process.argv[1]?.endsWith('hygiene.mjs')) {
  main();
}
