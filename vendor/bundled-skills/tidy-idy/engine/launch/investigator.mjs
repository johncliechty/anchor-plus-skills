// engine/launch/investigator.mjs — Wave 7: the seeded, project-tied agent terminal.
//
// ONE LAUNCH SPEC, MANY ENGINES — the same discipline opener.mjs uses for the
// browser. What is identical across engines has exactly one implementation; only
// the ACT of opening a terminal, and the argv template of the agent CLI, adapt.
//
//   identical  = the briefing (engine-agnostic markdown), the cwd (project root),
//                the run it is tied to, and the skill-resolvability handling.
//   adaptive   = the ENGINE (Claude / Gemini / Grok) — a command TEMPLATE,
//                not a second code path; another engine is a new row in
//                ENGINE_TEMPLATES plus a config value, and nothing else.
//   adaptive   = the OPENER — a standalone run spawns a terminal in the project
//                cwd; an Anchor-hosted run hands the spec back for Anchor's own
//                terminal surface, importing nothing from Anchor.
//
// The clean-machine failure (FM15: "demoed once, breaks on clean machines") is
// designed out in briefing.mjs: the launch spec RE-RESOLVES the skill in the
// environment the terminal is actually opening in and regenerates the briefing
// so its instructions are inlined when the skill is not on this machine's path.

import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawn as nodeSpawn } from 'node:child_process';

import { ENVIRONMENT } from './opener.mjs';
import { writeBriefing, resolveTidyIdySkill, BRIEFING_FILENAME } from './briefing.mjs';

export const INVESTIGATOR_ENGINE = Object.freeze({
  CLAUDE: 'claude',
  GEMINI: 'gemini',
  GROK: 'grok',
});
export const DEFAULT_ENGINE = INVESTIGATOR_ENGINE.CLAUDE;

/**
 * The engine command templates. Each is DATA: a label and the base argv of the
 * agent CLI; the opening prompt (which names the briefing path) is appended as
 * the final argument by buildCommand. Adding an engine is adding a row here and
 * a config value — never a branch elsewhere.
 *
 * Grok matches Anchor's interactive seat: `grok` / `grok.exe` on PATH
 * (or `~/.grok/bin/grok.exe`). Gemini may resolve to `agy` at the OS shell
 * when `gemini` is absent (same host convention as Anchor terminal_session).
 */
export const ENGINE_TEMPLATES = Object.freeze({
  claude: { id: 'claude', label: 'Claude', default: true, argv: ['claude'] },
  gemini: { id: 'gemini', label: 'Gemini', default: false, argv: ['gemini'] },
  grok: { id: 'grok', label: 'Grok', default: false, argv: ['grok'] },
});

/** The pure display choices the panel offers, drift-checked against the templates by test. */
export function engineChoices({ defaultEngine = DEFAULT_ENGINE } = {}) {
  return Object.values(ENGINE_TEMPLATES).map((t) => ({ id: t.id, label: t.label, default: t.id === defaultEngine }));
}

/**
 * Resolve the engine id from an explicit request or config, defaulting to Claude.
 * An unknown request falls back to the default but is reported (requested vs
 * resolved) on the spec, so the fallback is never a silent lie.
 */
export function resolveEngine({ engine = null, config = null } = {}) {
  const requested = engine || (config && config.investigator && config.investigator.engine) || DEFAULT_ENGINE;
  const id = String(requested).toLowerCase();
  const resolved = ENGINE_TEMPLATES[id] ? id : DEFAULT_ENGINE;
  return { requested: String(requested), resolved, recognised: Boolean(ENGINE_TEMPLATES[id]) };
}

/** The opening prompt: names the briefing PATH and the project, engine-agnostic. */
export function openingPrompt({ briefingPath, project }) {
  return [
    `You are investigating the repository "${project.name}" at ${project.path}.`,
    `Read the tidy-idy run briefing at ${briefingPath} first, then help me act on its findings.`,
    'Nothing has been applied yet; do not delete, move, or commit anything without my explicit confirmation.',
  ].join(' ');
}

/** [engine argv..., opening prompt] — the verbatim command a caller launches. */
export function buildCommand(template, prompt) {
  return [...template.argv, prompt];
}

/**
 * Build the investigator launch spec for THIS run, regenerating the briefing so
 * it matches the launch environment (skill inlined when unresolvable here).
 *
 * @param {{rootPath: string, runDir: string, envelope: object, identity: object,
 *   runNumber?: number|null, engine?: string|null, config?: object|null,
 *   skill?: object|null, skillResolver?: Function, environment?: string,
 *   fs?: object, env?: object}} opts
 */
export async function buildInvestigatorLaunchSpec({
  rootPath,
  runDir,
  envelope,
  identity,
  runNumber = null,
  engine = null,
  config = null,
  skill = null,
  skillResolver = resolveTidyIdySkill,
  environment = ENVIRONMENT.STANDALONE,
  fs = fsp,
  env = process.env,
} = {}) {
  const root = path.resolve(rootPath);
  const engineChoice = resolveEngine({ engine, config });
  const template = ENGINE_TEMPLATES[engineChoice.resolved];

  // Resolve the skill HERE (not where the run was archived) and (re)write the
  // briefing to match — this is the FM15 fix made concrete.
  const resolved = skill || await skillResolver({ env, fs });
  const written = await writeBriefing({ runDir, envelope, identity, runNumber, skill: resolved, fs, env });
  const briefingPath = written.path;

  const project = { name: identity.name, path: root };
  const prompt = openingPrompt({ briefingPath, project });

  return {
    kind: 'open-terminal',
    engine: engineChoice.resolved,
    engineRequested: engineChoice.requested,
    engineRecognised: engineChoice.recognised,
    engineLabel: template.label,
    // The terminal lands in the PROJECT ROOT — the same project as the panel.
    cwd: root,
    command: buildCommand(template, prompt),
    briefingPath,
    briefingFilename: BRIEFING_FILENAME,
    openingPrompt: prompt,
    skill: {
      resolvable: resolved.resolvable,
      path: resolved.path || null,
      inlined: written.inlined,
      searched: resolved.searched || [],
    },
    project,
    runId: envelope.runId,
    runNumber,
    environment,
    note: 'one launch spec; the engine is a command-template field (Claude / Gemini / Grok) — adding an engine is a template row, never a second code path',
  };
}

/**
 * Execute a launch spec in the given environment. Standalone spawns a terminal
 * in the project cwd; Anchor hands the spec back for its own surface; none is a
 * headless/CI no-op that returns the spec unexecuted. Best-effort by design: a
 * failure to open a desktop terminal never throws into the panel's POST handler.
 */
export async function openInvestigator({
  spec,
  environment = ENVIRONMENT.STANDALONE,
  spawn = nodeSpawn,
  platform = process.platform,
  log = () => {},
} = {}) {
  if (environment === ENVIRONMENT.ANCHOR) {
    return { opened: false, by: 'anchor', handoff: true, spec, note: "Anchor opens the terminal in its own surface; the tool hands back the spec and never spawns a desktop terminal on the server" };
  }
  if (environment === ENVIRONMENT.NONE) {
    return { opened: false, by: 'none', spec, note: 'headless/CI — the launch spec is returned unexecuted' };
  }
  try {
    const term = terminalCommand(spec, platform);
    const child = spawn(term.command, term.args, { cwd: spec.cwd, detached: true, stdio: 'ignore', ...term.opts });
    if (child && typeof child.unref === 'function') child.unref();
    log(`investigator terminal opened (${spec.engine}) in ${spec.cwd}`);
    return { opened: true, by: 'terminal', spec };
  } catch (err) {
    return { opened: false, by: 'terminal', spec, error: err && err.message };
  }
}

/**
 * Wrap the engine command in an OS terminal so it opens a visible window rooted
 * at the project cwd. Best-effort and per-platform; split out so a test can
 * assert it without launching one.
 */
export function terminalCommand(spec, platform = process.platform) {
  const inner = spec.command;
  if (platform === 'win32') {
    // `start` opens a new console; the title arg guards a quoted first token.
    return { command: 'cmd', args: ['/c', 'start', 'tidy-idy investigator', ...inner], opts: { windowsHide: false } };
  }
  // On macOS/Linux the agent CLI's own TUI is the terminal session; run it
  // directly in cwd rather than guessing at the user's terminal emulator.
  return { command: inner[0], args: inner.slice(1), opts: {} };
}

/**
 * The panel-model slot descriptor. Pure data (engines, default engine, briefing
 * path) — no spawn, no server — so the launcher can compute it and hand it to
 * the token-free panel model without the panel importing this module.
 */
export function investigatorSlotDescriptor({ config = null, archive = null } = {}) {
  const { resolved } = resolveEngine({ config });
  const briefingPath = archive && archive.dir ? path.join(archive.dir, BRIEFING_FILENAME) : null;
  return {
    defaultEngine: resolved,
    engines: engineChoices({ defaultEngine: resolved }),
    briefingPath,
    briefingFilename: BRIEFING_FILENAME,
  };
}

/**
 * The panel's `onInvestigate` hook: builds the spec for the requested engine and
 * opens it, environment-appropriately. `spawn` is injectable so a test asserts
 * the command without launching one.
 */
export function makeInvestigateHook({
  rootPath,
  runDir,
  envelope,
  identity,
  runNumber = null,
  config = null,
  environment = ENVIRONMENT.STANDALONE,
  spawn = null,
  fs = fsp,
  env = process.env,
  log = () => {},
} = {}) {
  return async ({ engine = null } = {}) => {
    const spec = await buildInvestigatorLaunchSpec({
      rootPath, runDir, envelope, identity, runNumber, engine, config, environment, fs, env,
    });
    const opened = await openInvestigator({ spec, environment, ...(spawn ? { spawn } : {}), log });
    return {
      spec,
      opened,
      message: opened.opened
        ? `investigator terminal opened (${spec.engine}) in ${spec.cwd}`
        : (opened.note || opened.error || 'the terminal was not opened here — run the command in the spec yourself'),
    };
  };
}

export default {
  buildInvestigatorLaunchSpec, openInvestigator, terminalCommand, resolveEngine, engineChoices,
  openingPrompt, buildCommand, investigatorSlotDescriptor, makeInvestigateHook,
  INVESTIGATOR_ENGINE, DEFAULT_ENGINE, ENGINE_TEMPLATES,
};
