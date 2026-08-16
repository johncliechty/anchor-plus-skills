/**
 * Wave 22 — T-HOST-0 host-independence acceptance gate.
 *
 * EXCLUDED from the standing suite (wave-local real-run gate). Orchestrator /
 * human only:
 *   node gate/t-host-0.mjs
 *
 * Scrubbed no-Anchor environment: no ANCHOR_TOKEN / ANCHOR_DATA_DIR /
 * ANCHOR_PREFS_PATH, isolated HOME with no ~/.anchor/, no .anchor/ in targets,
 * real in-session cheap-profile commission, golden-matched deterministic
 * emitters, separate no-executor-host case, network/token traps.
 *
 * Writes: artifacts/t-host-0-verdict.json (S8) — consumed by Wave 19.
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { runTHost0Gate } from '../engine/t-host-0.mjs';
import { makeRealInSessionHooks } from './insession-process-hooks.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

async function main() {
  const result = await runTHost0Gate({
    root: ROOT,
    write_verdict: true,
    hooks: makeRealInSessionHooks(),
  });

  const out = {
    ok: result.ok,
    verdict: result.verdict?.verdict,
    steps: (result.steps ?? []).map((s) => ({
      name: s.name,
      ok: s.ok,
      ...(s.error ? { error: s.error } : {}),
    })),
    verdict_path: result.verdict_path ?? 'artifacts/t-host-0-verdict.json',
    zero_network_calls: result.verdict?.zero_network_calls,
    zero_anchor_reads: result.verdict?.zero_anchor_reads,
    zero_token_reads: result.verdict?.zero_token_reads,
  };
  console.log(JSON.stringify(out, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
