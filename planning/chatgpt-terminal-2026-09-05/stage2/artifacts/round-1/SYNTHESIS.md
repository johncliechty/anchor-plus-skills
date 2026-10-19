# Shark-Tank Round 1 — BLOCKED

- Verdict: **BLOCKED** (3 new BLOCKER)
- Angles: Skeptic=operator, Contrarian=skeptical-researcher
- Findings: 17 · Blockers: 3 · Demoted (inclusion test): 0

## Blocking (≥2 Sharks agree, traces to a criterion)
- **BLOCKER** `topic:exists-gate-screenshot-ship` — agree 2 (Skeptic, Contrarian) — The only non-stub proof is skippable (`pytest.importorskip('playwright')` plus `ANCHOR_TESTS_ALLOW_LIVE=1` plus a real `codex` binary). A skip is a green pytest. The wait is for unnamed "Codex greet text." The tag rule is "the screenshot file exists" plus the stub suite. A blank xterm, a login wall, an on-request approval modal, a throwaway-port harness that is not `:8777`, or a planted PNG all satisfy "file exists." Criterion 4 is a claim about John's dashboard page. The warm-restart sentence in done-when is a ritual with no named string and is not in the tag condition. As written, v1.2.12 can ship with the greet still inferred.
- **MAJOR** `topic:argv-before-launch-ready` — agree 2 (Skeptic, Contrarian) — W1's definition of done is the picker and capability note saying ready, while the launch is still bare `codex` (alt-screen, no `--cd`, no sandbox) until W2. That is the operator-visible surface going green before the terminal can open as specified. Every wave "ships real source" onto a live service. A mid-effort restart, or a saved `default_cli=chatgpt` after W1, presents a first-class seat that hits the exact alt-screen failure the risk table named. "Ready" is a surface claim, not a permission to open a gate.
- **MAJOR** `topic:engine-first-output-seed-skips-switch` — agree 2 (Skeptic, Contrarian) — First-output-gated seed is specified for `start_session` at the stdin site. Engine switch is the operator's other way onto ChatGPT (criterion 1 names it). W2 applies launch argv at both relaunch sites; W3 does not apply `SEED_AFTER_FIRST_OUTPUT_BACKENDS` there. Toggling Claude → ChatGPT can dump the skill into a composer that is not up — the seed-before-ready risk, on the hotter operator path. W7 asserts `len(pty_manager.live_sessions())` unchanged after toggle, not that the ChatGPT side was seeded after first output or that a greet is visible after the switch.

## Demoted (failed the inclusion test — cannot hold the loop open)
_none_
