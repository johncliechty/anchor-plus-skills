import fs from 'node:fs/promises';
import path from 'node:path';

const ENTANGLEMENT_PATTERNS = [
    { type: 'absolute_path', regex: /C:\\[\w\\]+/i },
    { type: 'username_email', regex: /john\.liechty|@gmail\.com|john@/i },
    { type: 'machine_name', regex: /\bPUTER\b|\bgwl-server\b/i },
    { type: 'hardcoded_model', regex: /gemini-[0-9]|claude-[0-9]/i }
];

async function scanDirectory(dir, results) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
        if (['node_modules', '.git', '_archive', 'census'].includes(entry.name)) continue;
        const fullPath = path.join(dir, entry.name);
        
        if (entry.isDirectory()) {
            await scanDirectory(fullPath, results);
        } else if (entry.isFile()) {
            if (/\.(js|mjs|py|md|json|txt|yml|yaml|ps1|bat)$/.test(entry.name)) {
                try {
                    const content = await fs.readFile(fullPath, 'utf8');
                    const lines = content.split('\n');
                    for (let i = 0; i < lines.length; i++) {
                        const line = lines[i];
                        for (const pattern of ENTANGLEMENT_PATTERNS) {
                            if (pattern.regex.test(line)) {
                                results.push({
                                    file: fullPath,
                                    line: i + 1,
                                    type: pattern.type,
                                    match: line.trim().substring(0, 100)
                                });
                                break;
                            }
                        }
                    }
                } catch (e) {
                    // Skip
                }
            }
        }
    }
}

async function run() {
    const results = [];
    const cwd = process.cwd();
    await scanDirectory(cwd, results);
    console.log(JSON.stringify(results, null, 2));
}

run().catch(console.error);
