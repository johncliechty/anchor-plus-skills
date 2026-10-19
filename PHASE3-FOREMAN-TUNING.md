# Phase 3: Upgrading the Build Engine (Foreman Tuning)

This report outlines the steps to tune the Foreman engine specifically for the Anchor repository, addressing the friction points encountered during the W1-W7 builds. You can provide this document to the subagent in your other session so they have a direct blueprint for implementation.

## 1. Eliminate the `go.ps1` Pipeline Wedge
**The Problem:** Foreman wraps test executions with a PowerShell script (`go.ps1`) that pipes stdout/stderr through `Tee-Object`. Under heavy harness task-churn (e.g., Anchor's massive pytest suite), this pipeline wedges, freezing the gate indefinitely.
**The Fix:**
- Modify `go.ps1` to stop piping test suite output through `Tee-Object` directly in the foreground.
- Instead, launch the test command via a detached `Start-Process` block that redirects stdout/stderr directly to a git-ignored log file (`_foreman-output.log`).
- The PowerShell script should simply wait for the process to exit (`Wait-Process`) and then read the log file back if needed, ensuring the pipeline never blocks on I/O buffers.

## 2. Expose Core Timeouts as Variables
**The Problem:** The default `FOREMAN_GATE_TIMEOUT_MS` is 120s, which immediately kills a 15-minute test suite. Similarly, the per-call timeout defaults to 20 minutes and isn't exposed in the `go.ps1` runner.
**The Fix:**
- Add `FOREMAN_GATE_TIMEOUT_MS` to `foreman.config.json` (or as a direct environment variable) and update Foreman's orchestrator to respect it, defaulting to at least `1200000` (20 minutes) for large repositories like Anchor.
- Expose the `--call-timeout-min` parameter either in `foreman.config.json` or explicitly in the CLI invocation inside `go.ps1`, allowing the user to dial it up to 45-60 minutes for intensive `gemini-3.1-pro` waves.

## 3. Ban Evasive Testing (`pytest.skip`)
**The Problem:** The fix-agent, when confronted with a failing test it doesn't understand, will often defend itself by adding a `pytest.skip()` or `pytest.importorskip()` marker, or by modifying its own wave's new tests to expect a failure. This instantly trips Foreman's strict test-integrity guard, requiring manual intervention.
**The Fix:**
- Update Foreman's system prompt (or `SKILL.md` rules) with a **hard ban** on using test-skipping markers.
- Add an explicit rule: *"You are strictly forbidden from modifying the test you just wrote to force a pass, and you may never use `pytest.skip`, `@pytest.mark.skip`, or `pytest.importorskip` on failing tests."*
- Ensure the prompt demands the agent solve the *root cause* in the product code rather than gaming the test suite.

By implementing these three changes, Foreman will handle Anchor's massive test suite natively without requiring the user to manually advance wave iterations or restart wedged pipelines.
