import { spawnSync, spawn, execFile } from 'node:child_process';
import fs from 'node:fs';

const ENV_ALLOWLIST = [
    'PATH', 'NODE_ENV', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOME', 'XDG_CONFIG_HOME',
    'CRUCIBLE_ALLOW_SPEND', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY',
    'CRUCIBLE_AGENT_LIVE', 'TRIO_DRIVER', 'GEMINI_MODEL',
    'ANCHOR_DATA_DIR', 'TRIO_ROOT', 'SKILL_FOUNDRY_ROOT',
    'FOUNDRY_MAP', 'FOUNDRY_ROOT', 'FOUNDRY_NORTH_STAR', 'FOUNDRY_KERNEL_DIR',
    'FOUNDRY_SKILLS_ROOT', 'FOUNDRY_SKILLS_REPO', 'FOUNDRY_SLEEP_RUNS',
    'FOUNDRY_KERNEL_TIMEOUT_MS', 'PORT', 'ANCHOR_AGY_DISPATCH',
    'SPAWN_JOURNAL_PATH', 'ANCHOR_TOKEN', 'ANCHOR_AUTH_MODE'
];

function buildEnv() {
    const env = {};
    for (const key of ENV_ALLOWLIST) {
        if (process.env[key] !== undefined) {
            env[key] = process.env[key];
        }
    }
    return env;
}

function journalSpawn(cmd, args, env) {
    if (process.env.NODE_ENV === 'test') {
        const journalPath = process.env.SPAWN_JOURNAL_PATH || 'spawn-journal.jsonl';
        const entry = JSON.stringify({ cmd, args, env }) + '\n';
        fs.appendFileSync(journalPath, entry);
    }
}

export function anchorSpawnSync(cmd, args, options = {}) {
    const env = buildEnv();
    if (options.env) {
        Object.assign(env, options.env);
    }
    journalSpawn(cmd, args, env);
    return spawnSync(cmd, args, { ...options, env, shell: false });
}

export function anchorSpawn(cmd, args, options = {}) {
    const env = buildEnv();
    if (options.env) {
        Object.assign(env, options.env);
    }
    journalSpawn(cmd, args, env);
    return spawn(cmd, args, { ...options, env, shell: false });
}

export function anchorExecFile(cmd, args, options, callback) {
    if (typeof options === 'function') {
        callback = options;
        options = {};
    }
    const env = buildEnv();
    if (options && options.env) {
        Object.assign(env, options.env);
    }
    journalSpawn(cmd, args, env);
    return execFile(cmd, args, { ...options, env, shell: false }, callback);
}
