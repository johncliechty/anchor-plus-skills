import { spawnSync } from 'child_process';
import fs from 'fs';

console.log("Running cross-skill spawn integration smoke...");

let hasError = false;

if (fs.existsSync('locate-plan.mjs')) {
    const res = spawnSync('node', ['locate-plan.mjs', '--help'], { stdio: 'inherit' });
    if (res.status !== 0) hasError = true;
}

if (fs.existsSync('resolver.js') || fs.existsSync('resolver.mjs')) {
    // Just a placeholder for the resolver CLI
    console.log("Found resolver script.");
}

if (hasError) {
    console.error("Integration smoke failed.");
    process.exit(1);
} else {
    console.log("Integration smoke passed.");
}
