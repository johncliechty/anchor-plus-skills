// REMOVED (W6 / SC3 / G7): SoftFreeze / Thread.Suspend process-freeze path.
// The sole Freeze/Kill service boundary is src/freeze.js (NtSuspendProcess).
// This file remains only as a hard-fail shim so stale imports cannot silently
// reintroduce Thread.Suspend.

function SoftFreeze() {
  throw new Error(
    'SoftFreeze removed in W6 — use freeze.js sole Freeze/Kill service boundary (NtSuspendProcess)',
  );
}

module.exports = {
  SoftFreeze,
  REMOVED: true,
  replacement: './freeze.js',
  reason: 'Thread.Suspend SoftFreeze deleted; sole boundary is freeze.js',
};
