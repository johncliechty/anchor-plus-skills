// Isolated one-shot classification sweep.
//
// classifyAll() enumerates the process tree, signature-checks AI-flagged
// processes, samples network spend, and reads the token ledger — ~10-20s. That
// can NEVER run on the server's event loop (it would block every HTTP response
// and blow the Anchor proxy's 5s timeout). The server forks THIS worker, which
// runs one sweep, prints JSON, and exits. The server serves the last result.
//
// W7 / SC4: JSON-safe enum — control chars in cmdline/image are sanitized so
// parse never invents zombies on failure.
const { classifyAll } = require('./classify.js');
const { jsonSafeStringify, sanitizeProcessFields } = require('./json-safe.js');

try {
  const result = sanitizeProcessFields(classifyAll());
  process.stdout.write(jsonSafeStringify(result));
} catch (e) {
  process.stdout.write(jsonSafeStringify({
    ok: false,
    error: String(e && e.message || e),
    engines: [],
    hiddenNonEngine: 0,
    hiddenSample: [],
    ledger: {
      sessions: [],
      totals: { activeSessions: 0, usdRecent: 0, usdPerMin: 0, tokensRecent: 0 },
      windowMin: 10,
    },
  }));
}
