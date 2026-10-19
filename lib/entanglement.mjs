import fs from 'node:fs/promises';
import path from 'node:path';

export class ModuleCrawler {
    async assertBoundaryImmutability(dir) {
        const entries = await fs.readdir(dir, { withFileTypes: true });
        const skills = [];
        for (const entry of entries) {
            if (entry.isDirectory()) {
                skills.push(entry.name);
            }
        }

        for (const skill of skills) {
            const skillDir = path.join(dir, skill);
            await this._checkCrossSkillImports(dir, skillDir, skill, skills);
        }
    }

    async _checkCrossSkillImports(baseDir, currentDir, currentSkill, allSkills) {
        const entries = await fs.readdir(currentDir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = path.join(currentDir, entry.name);
            if (entry.isDirectory()) {
                await this._checkCrossSkillImports(baseDir, fullPath, currentSkill, allSkills);
            } else if (entry.isFile() && entry.name.endsWith('.mjs')) {
                const content = await fs.readFile(fullPath, 'utf8');
                const importRegex = /import\s+.*?from\s+['"](.*?)['"]/g;
                let match;
                while ((match = importRegex.exec(content)) !== null) {
                    const importPath = match[1];
                    if (!importPath.startsWith('.')) continue;
                    
                    const resolvedPath = path.resolve(currentDir, importPath);
                    if (resolvedPath.startsWith(baseDir)) {
                        const relativeToBase = path.relative(baseDir, resolvedPath);
                        const importedSkill = relativeToBase.split(path.sep)[0];
                        if (allSkills.includes(importedSkill) && importedSkill !== currentSkill) {
                            throw new Error(`Cross-skill import detected: ${currentSkill} imports ${importedSkill}`);
                        }
                    }
                }
            }
        }
    }

    async assertPortability(dir) {
        await this._checkPortability(dir, dir);
    }

    async _checkPortability(baseDir, currentDir) {
        const entries = await fs.readdir(currentDir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = path.join(currentDir, entry.name);
            if (entry.isDirectory()) {
                await this._checkPortability(baseDir, fullPath);
            } else if (entry.isFile() && entry.name.endsWith('.mjs')) {
                const content = await fs.readFile(fullPath, 'utf8');
                
                // Check for literal cross-sibling paths
                const literalPathRegex = /(?:[Cc]:[\\\/]+dev[\\\/]+|\/dev\/trio[\\\/]?)/;
                if (literalPathRegex.test(content)) {
                    throw new Error('Literal cross-sibling path detected');
                }

                // Check for hardcoded Windows path separators
                if (content.includes('C:\\\\') || content.includes('C:\\')) {
                    throw new Error('Hardcoded path separator detected');
                }

                // Check for unsanctioned child_process spawn
                const normalizedPath = fullPath.replace(/\\/g, '/');
                if (!normalizedPath.endsWith('lib/spawn.mjs') && (content.includes('node:child_process') || content.includes("'child_process'") || content.includes('"child_process"'))) {
                    throw new Error(`Unsanctioned spawn detected in ${fullPath}: all spawn calls must use lib/spawn.mjs`);
                }

                // Check for case-mismatched imports
                const importRegex = /import\s+.*?from\s+['"](.*?)['"]/g;
                let match;
                while ((match = importRegex.exec(content)) !== null) {
                    const importPath = match[1];
                    if (!importPath.startsWith('.')) continue;

                    const targetDir = path.resolve(currentDir, path.dirname(importPath));
                    const targetBase = path.basename(importPath);

                    try {
                        const targetEntries = await fs.readdir(targetDir);
                        const lowerEntries = targetEntries.map(e => e.toLowerCase());
                        const targetBaseLower = targetBase.toLowerCase();
                        
                        if (lowerEntries.includes(targetBaseLower) && !targetEntries.includes(targetBase)) {
                            throw new Error('Case-mismatched import detected');
                        }
                    } catch (e) {
                        if (e.message.includes('Case-mismatched import detected')) {
                            throw e;
                        }
                    }
                }
            }
        }
    }
}
