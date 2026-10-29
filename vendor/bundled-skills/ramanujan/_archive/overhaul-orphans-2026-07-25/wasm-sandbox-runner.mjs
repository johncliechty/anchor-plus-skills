// Wave 3 — the NATIVE WASM SANDBOX RUNNER child entry (the out-of-process arm of the secure WASM
// sandbox runtime; mirrors the Wave-9 §Build-host & subprocess contract of test/sandbox-runner.mjs).
//
// This is the child runInNativeSandbox spawns via child_process.execFileSync on the same `node`
// binary (NO shell). It receives ONE argument — the path to the hermetic input file holding the
// job spec (module bytes base64, entry, args, limits) — executes the module under the FULL
// in-process sandbox (default-deny imports, engine-capped memory, fuel + cooperative deadline;
// the single engine in src/wasm-sandbox.mjs, shared with the parent), and writes the structured
// JSON execution record to stdout. The PARENT holds the non-cooperative boundary: its native
// execFileSync timeout kills this process if a runaway module never yields.
//
// It is NOT a test file. The frozen gate `node --test test/` loads test/index.js (which imports
// only `*.test.mjs`), so this module is never executed by the test runner — only as the spawned
// child. Invoked with no input path it is a deliberate no-op (registers nothing, exits 0).

import { runWasmSandboxChild } from '../src/wasm-sandbox.mjs';

await runWasmSandboxChild(process.argv.slice(2));
