#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { reportDirFor } from '../engine/report-dir.mjs';

/**
 * Recursively scans the target directory to locate active Foundry projects.
 * A directory is considered an active project if it contains a North Star file.
 * The priority for the North Star file is: NORTH-STAR.md > INTENT.md > SKILL.md.
 * 
 * @param {string} targetDir Directory path to scan.
 * @returns {Promise<Array<{path: string, north_star_file: string}>>}
 */
async function scan(targetDir) {
  const results = [];

  async function walk(dir) {
    const name = path.basename(dir);
    // Ignore hidden files/folders and standard node/tooling directories
    if (name.startsWith('.') || name === 'node_modules') {
      return;
    }

    let stats;
    try {
      stats = await fs.stat(dir);
    } catch {
      return;
    }

    if (!stats.isDirectory()) {
      return;
    }

    let files;
    try {
      files = await fs.readdir(dir);
    } catch {
      return;
    }

    // Determine the project's North Star file based on predefined priority
    let northStarFile = null;
    if (files.includes('NORTH-STAR.md')) {
      northStarFile = 'NORTH-STAR.md';
    } else if (files.includes('INTENT.md')) {
      northStarFile = 'INTENT.md';
    } else if (files.includes('SKILL.md')) {
      northStarFile = 'SKILL.md';
    }

    if (northStarFile) {
      results.push({
        path: path.resolve(dir),
        north_star_file: path.resolve(dir, northStarFile)
      });
      // Do not recurse into subdirectories once a project root is identified
      return;
    }

    // Recurse into subdirectories
    for (const file of files) {
      await walk(path.join(dir, file));
    }
  }

  await walk(targetDir);
  return results;
}

async function main() {
  try {
    // Determine scanning target directory.
    // If a CLI argument is provided, scan that folder.
    // Otherwise, check if the parent directory has sibling skill folders, or fall back to the current directory.
    let targetDir = process.argv[2];
    if (!targetDir) {
      const parentDir = path.resolve('..');
      try {
        const parentFiles = await fs.readdir(parentDir);
        let hasSkillsInParent = false;
        for (const file of parentFiles) {
          if (file === 'tidy-idy') continue;
          const fullPath = path.join(parentDir, file);
          const stat = await fs.stat(fullPath);
          if (stat.isDirectory()) {
            const subFiles = await fs.readdir(fullPath);
            if (subFiles.includes('SKILL.md') || subFiles.includes('NORTH-STAR.md') || subFiles.includes('INTENT.md')) {
              hasSkillsInParent = true;
              break;
            }
          }
        }
        targetDir = hasSkillsInParent ? parentDir : '.';
      } catch {
        targetDir = '.';
      }
    }

    const resolvedTarget = path.resolve(targetDir);
    const projects = await scan(resolvedTarget);

    // Wave-1 refactor-in-place (Wave-0 seam: shared-mutable-state). State lives
    // under the TARGET ROOT, never the CWD — the old CWD-relative state dir
    // wrote outside the target whenever the CLI was launched from elsewhere.
    const stateDir = reportDirFor(resolvedTarget);
    await fs.mkdir(stateDir, { recursive: true });
    const outputPath = path.join(stateDir, 'projects.json');
    await fs.writeFile(outputPath, JSON.stringify(projects, null, 2), 'utf8');

    // Output the valid JSON array to stdout as requested by the Given/When/Then spec
    console.log(JSON.stringify(projects, null, 2));

  } catch (error) {
    console.error('Scanner execution failed:', error);
    process.exit(1);
  }
}

// Execute main if run directly as a CLI script
const isDirectRun = import.meta.url === `file://${process.argv[1]}` || 
                    (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname));

if (isDirectRun || process.argv[1]?.endsWith('scanner.mjs')) {
  main();
}

export { scan };
