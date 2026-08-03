import vm from 'node:vm';

/**
 * Pillar 7 Interface: Solve/Execute Empirical.
 * Builds and executes empirical algorithms in a rigorously separated sandbox,
 * achieving the `EMPIRICALLY-TESTED` rung.
 *
 * @param {{ id?: string, code: string, tests?: Array<string | { name?: string, code?: string, input?: any, expected?: any }> }} algorithm
 * @param {{ ledger?: any }} [options]
 * @returns {{ success: boolean, tests: Array<{ name: string, passed: boolean, error?: string }>, logs: string[], error?: string }}
 */
export function executeEmpirical(algorithm, { ledger } = {}) {
  if (!algorithm || typeof algorithm !== 'object') {
    throw new Error('executeEmpirical: algorithm payload is required');
  }

  const { id, code, tests = [] } = algorithm;

  if (typeof code !== 'string') {
    throw new Error('executeEmpirical: algorithm.code must be a string');
  }

  const logs = [];
  const sandbox = {
    console: {
      log: (...args) => logs.push(args.join(' ')),
      error: (...args) => logs.push(args.join(' ')),
      warn: (...args) => logs.push(args.join(' ')),
      info: (...args) => logs.push(args.join(' ')),
    },
    assert: (condition, message) => {
      if (!condition) {
        throw new Error(message || 'Assertion failed');
      }
    },
    assertEquals: (actual, expected) => {
      if (actual !== expected) {
        throw new Error(`Assertion failed: expected ${expected}, got ${actual}`);
      }
    },
  };

  const context = vm.createContext(sandbox);

  let script;
  try {
    script = new vm.Script(code);
  } catch (err) {
    return {
      success: false,
      error: `Compilation error: ${err.message}`,
      tests: [],
      logs,
    };
  }

  try {
    script.runInContext(context, { timeout: 1000 });
  } catch (err) {
    return {
      success: false,
      error: `Execution error in algorithm code: ${err.message}`,
      tests: [],
      logs,
    };
  }

  const testResults = [];
  let allPassed = true;

  for (let i = 0; i < tests.length; i++) {
    const test = tests[i];
    let testCode = '';
    let name = `Test #${i + 1}`;

    if (typeof test === 'string') {
      testCode = test;
      name = test;
    } else if (test && typeof test === 'object') {
      name = test.name || `Test #${i + 1}`;
      if (test.code) {
        testCode = test.code;
      } else if (test.input !== undefined && test.expected !== undefined) {
        // Assume test.input is a snippet/expression calling a function in the code
        testCode = `assertEquals(${test.input}, ${JSON.stringify(test.expected)})`;
      }
    }

    try {
      vm.runInContext(testCode, context, { timeout: 1000 });
      testResults.push({ name, passed: true });
    } catch (err) {
      allPassed = false;
      testResults.push({ name, passed: false, error: err.message });
    }
  }

  const success = allPassed && testResults.length > 0 || (tests.length === 0 && allPassed);

  if (success && id && ledger) {
    if (ledger.has(id)) {
      ledger.promote(id, 'EMPIRICALLY-TESTED', {
        family: 'empirical-sandbox',
        reason: 'all sandbox tests passed',
      });
    }
  }

  return {
    success,
    tests: testResults,
    logs,
  };
}
