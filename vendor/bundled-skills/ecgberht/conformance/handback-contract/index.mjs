/**
 * Wave 21 — shared handback-contract conformance suite (public entry).
 *
 * One skill-owned contract, two executors, one CI suite (NS criterion 15).
 */

export {
  CLAUSE_NAMES,
  CLAUSE_DESCRIPTIONS,
  isClauseName,
  clauseFailureName,
} from './clauses.mjs';

export {
  ADAPTER_METHODS,
  EXECUTOR_SLOTS,
  validateAdapter,
  isExecutorSlot,
} from './adapter-interface.mjs';

export {
  REAL_WRITER_SOURCES,
  sourceShowsS6,
  loadWriterSource,
  evaluateWriteInterception,
  evaluateWriteDiscipline,
  probeRealWriterS6,
} from './write-intercept.mjs';

export {
  CONFORMANCE_VERDICT_REL,
  CONFORMANCE_WRITTEN_BY,
  conformanceVerdictPath,
  emptyConformanceVerdict,
  readConformanceVerdict,
  mergeExecutorResult,
  writeConformanceVerdictForExecutor,
  writeConformanceVerdict,
  proveRegenerateTwiceByteIdentical,
  forceWriteConformanceVerdict,
} from './verdict.mjs';

export {
  evaluateClause,
  runConformanceAgainstAdapter,
  evaluateInjectedScenario,
  makeCannedStubAdapter,
} from './suite.mjs';

export { createInsessionAdapter } from './adapters/insession.mjs';
export { createAnchorAdapter } from './adapters/anchor.mjs';

import { createInsessionAdapter } from './adapters/insession.mjs';
import { createAnchorAdapter } from './adapters/anchor.mjs';
import { runConformanceAgainstAdapter } from './suite.mjs';
import { CONTRACT_VERSION } from '../../engine/handback-contract.mjs';
import {
  writeConformanceVerdict,
  readConformanceVerdict,
  conformanceVerdictPath,
} from './verdict.mjs';

/**
 * Run both adapters (when available) and write the combined verdict.
 *
 * @param {{
 *   root: string,
 *   skillRoot?: string,
 *   anchorRoot?: string|null,
 *   skipAnchor?: boolean,
 * }} opts
 */
export async function runFullConformanceSuite(opts) {
  const skillRoot = opts.skillRoot;
  const root = opts.root;
  const results = { insession: null, anchor: null };

  const insession = createInsessionAdapter({ skillRoot });
  results.insession = await runConformanceAgainstAdapter(insession, {
    root,
    skillRoot,
    writeVerdict: true,
  });

  if (!opts.skipAnchor) {
    try {
      const anchor = createAnchorAdapter({
        skillRoot,
        anchorRoot: opts.anchorRoot,
      });
      results.anchor = await runConformanceAgainstAdapter(anchor, {
        root,
        skillRoot,
        anchorRoot: opts.anchorRoot,
        writeVerdict: true,
        peer_versions: {
          insession: results.insession?.contract_version,
        },
      });
    } catch (e) {
      results.anchor = {
        ok: false,
        executor: 'anchor',
        message: String(e?.message ?? e),
        clause_results: [],
        failed_clauses: [`executor:anchor clause:write-interception`],
      };
      // Still record FAIL for anchor
      const { writeConformanceVerdictForExecutor } = await import('./verdict.mjs');
      writeConformanceVerdictForExecutor({
        root,
        executor: 'anchor',
        contract_version: CONTRACT_VERSION,
        clause_results: [
          {
            clause: 'write-interception',
            ok: false,
            reason: String(e?.message ?? e),
          },
        ],
        peer_versions: {
          insession: results.insession?.contract_version,
        },
      });
    }
  }

  const verdict = readConformanceVerdict(root);
  return {
    ok:
      verdict?.executors?.insession === 'PASS' &&
      verdict?.executors?.anchor === 'PASS' &&
      Boolean(verdict?.contract_version),
    contract_version: verdict?.contract_version ?? CONTRACT_VERSION,
    results,
    verdict,
    path: conformanceVerdictPath(root),
  };
}

export { CONTRACT_VERSION };
