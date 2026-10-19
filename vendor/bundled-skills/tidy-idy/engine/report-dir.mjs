// engine/report-dir.mjs — where a run's state and reports live.
//
// Wave-0 coupling inventory, five records (scanner/hygiene/analyze/debate/
// compress, kind=shared-mutable-state): every CLI main() transported
// cross-stage state through `path.resolve('.tidy-idy')` — a CWD-RELATIVE
// location. Measured consequence: `node bin/scanner.mjs <target>` run from any
// other directory wrote `.tidy-idy/projects.json` into the CWD and nothing under
// the target, i.e. a write OUTSIDE the target root; and the downstream mains
// then read whatever run's state happened to be sitting in the CWD.
//
// The fix is one line of policy, applied everywhere: the state/report location
// is DERIVED FROM THE TARGET ROOT and from nothing else. When no target is
// given, the target is the current directory — explicitly, by derivation, not
// by accident of where the process was launched.

import path from 'node:path';

export const REPORT_DIR_NAME = '.tidy-idy';

/**
 * The run state/report directory for a target root. Never CWD-relative in the
 * sense that matters: it is always DERIVED from the target root. When no target
 * is given, the target IS the current directory — explicitly, by derivation
 * (path.resolve('.')), not by an accident of where the process was launched.
 */
export function reportDirFor(rootPath = '.') {
  return path.join(path.resolve(rootPath ?? '.'), REPORT_DIR_NAME);
}
