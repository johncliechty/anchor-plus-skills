# Anchor R&D Control Surface — Human Setup Gate (do BEFORE invoking Foreman)

These steps require elevation / host state / credentials and **cannot** be done or verified
by an autonomous code builder. Complete them once; then invoke Foreman on the
`IMPLEMENTATION-PLAN.md` waves. Each `[AGENT]` wave assumes this gate is satisfied and
verifies its *code* against mocks (never the live host).

## 1. Run the Anchor service as `john` (D3)
- Reconfigure the NSSM `anchor` service logon from `LocalSystem` to `john` (elevated; needs john's password).
  `nssm set anchor ObjectName .\john <password>` (or via `services.msc`).
- Add the per-user CLI dir to the service PATH so `claude.exe` resolves:
  `nssm set anchor AppEnvironmentExtra PATH=%PATH%;C:\Users\john\.local\bin`
- Verify: a `claude -p "say OK" --output-format json` spawned from the service context returns a subscription result (token refresh works non-interactively).

## 2. Single supervisor + reap orphans
- Confirm exactly one listener on 8777: `Get-NetTCPConnection -State Listen -LocalPort 8777`.
- Kill stray PIDs (the duplicate-supervisor was live during planning — disabling the task did NOT reap them): `taskkill /PID <pid> /F` for each extra.
- Disable/unregister the Task Scheduler "Anchor Server" task so NSSM is the sole supervisor.

## 3. Tailscale (D4)
- Ensure Tailscale is up; note the host's Tailscale IP (was `100.69.215.4`).
- Add `nssm set anchor DependOnService Tailscale` so the service starts after Tailscale.
- (The token-auth code + bind-retry are built in Wave 2; you only ensure Tailscale is running.)

## 4. Real-Crucible go/no-go (produces the Wave-5 test fixture)
- Run the real `crucible` skill headless to its first gate via the uniform primitive; confirm it surfaces the `AskUserQuestion`, accepts a **text-turn answer**, and **continues past the gate**.
- Capture the stream-json transcript to `planning/rnd-v1/fixtures/crucible_gate.jsonl` → this becomes the Wave-5 gate-adapter fixture.
- **If it does NOT continue cleanly:** STOP and re-plan the gate adapter before building (this is the one residual risk).

## 5. Optional — LaTeX → PDF for research docs (Tier 2)
- Install a TeX toolchain (MiKTeX or TeX Live) so `latexmk`/`pdflatex` are on PATH. Skip this and research simply uses the Reader (markdown + KaTeX) fallback; no PDFs.

## 6. (Later) Healthcheck task
- After the build, re-register/adjust the 5 AM "Anchor Health Check" task under the new env so its mock-runner round-trip and unauth-rejection assertions run daily.
