/**
 * T0 lint transition — W1 seam, W2 coverage section, W4 T0 core.
 * Only lib/engine.mjs may call this module (machine-only-caller test); the
 * lint bound is ≤ 2 s on the real corpus (start-budget gate).
 *
 * W4: the deterministic checker (lib/t0.mjs) runs over every sidecar under
 * the root and the transition REGENERATES <root>/chekhov/LEDGER-REPORT.md —
 * line 1 contradictions=N (T0 only), then the four sections in order:
 * contradictions, superseded, receipt-drift, threads due — with W2's coverage
 * list beneath. On John's real TTY the report is opened on his screen (a
 * human step, never a test).
 *
 * A root with no chekhov/config.json (no pack yet) keeps the W1 seam
 * behaviour: coverage only, T0 skipped with the five-row failure text, ok
 * stays true — the missing pack is named, never guessed.
 */
import { spawn } from 'node:child_process';
import { coverageForRoot } from '../coverage.mjs';
import { failureRow } from '../failure-states.mjs';
import { loadProjectPack } from '../pack.mjs';
import { renderLedgerReport, reportPath, t0ForRoot } from '../t0.mjs';
import { atomicWriteFile, stateDirFor, withLock } from '../store.mjs';

function onRealTty() {
  return process.stdin.isTTY === true && process.stdout.isTTY === true;
}

/** Open the regenerated report on John's screen — TTY only, Windows only. */
function openOnScreen(file) {
  if (process.platform !== 'win32') return false;
  spawn('explorer.exe', [file], { detached: true, stdio: 'ignore', windowsHide: true, shell: false }).unref();
  return true;
}

export function runLint(root, opts = {}) {
  const started = Date.now();
  const coverage = coverageForRoot(root);

  let pack = opts.pack || null;
  if (!pack) {
    try {
      pack = loadProjectPack(root, { packsDir: opts.packsDir });
    } catch {
      // dependency-missing: the project pack (chekhov/config.json) is absent.
      return {
        transition: 'lint',
        ok: true,
        findings: [],
        coverage,
        t0: null,
        t0_skipped: failureRow('lint', 'dependency-missing').text,
        duration_ms: Date.now() - started,
      };
    }
  }

  let t0;
  try {
    t0 = t0ForRoot(root, { pack });
  } catch (e) {
    // dependency-returns-garbage: a sidecar that does not parse is refused,
    // never guessed — the lint reports it and writes no report over it.
    return {
      transition: 'lint',
      ok: false,
      findings: [],
      coverage,
      t0: null,
      t0_error: `${failureRow('lint', 'dependency-returns-garbage').text} (${e.message})`,
      duration_ms: Date.now() - started,
    };
  }

  const stateDir = stateDirFor(root, opts.stateDir);
  const target = reportPath(stateDir);
  const report = renderLedgerReport(t0, coverage);
  withLock(stateDir, opts.lockOpts, () => atomicWriteFile(target, report));
  const opened = opts.open !== false && onRealTty() ? openOnScreen(target) : false;

  return {
    transition: 'lint',
    ok: true,
    findings: t0.threads_due,
    contradictions: t0.contradictions.length,
    criterion1: t0.criterion1,
    outline_gate: t0.gate,
    coverage,
    t0,
    report_path: target,
    opened,
    duration_ms: Date.now() - started,
  };
}
