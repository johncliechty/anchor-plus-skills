# Why the dollar summaries are missing — 2026-10-05

**His report:** "I'm not getting dollar summaries … ChatGPT doesn't seem to show up properly … I should be able to
get it for Grok, ChatGPT, Gemini and Claude."

**What the stewards record today** (`steward-cockpit-state.json`, per cockpit):
- Claude stewards: dollars present (Fractal $261, Math Review $135, Collapse $124, 3D $102) — the Claude CLI
  reports `total_cost_usd` on every turn, so `reported_spend` fills.
- ChatGPT stewards: every recent turn unpriced, estimate $0.00 — Cave 22/22, Distribution 15/15, Setup 12/12,
  Foundry 8/8, MBA 109/109. Artificial Magi did get ~$340 estimated earlier, so the path worked once.
- Grok: no Grok steward right now, but any Grok turn would be unpriced (below).
- Gemini: none; no Gemini steward can run (below).

**Root causes (each verified in code):**
1. **ChatGPT — the model left the price table.** Codex reports tokens but no dollars, so `steward_engine.py` (~2504)
   estimates at OpenAI list price via `estimate_list_price_usd(model, counts)`, looked up in
   `steward_cockpit/api_list_prices.json`. That table (as of 2026-09-25) lists only `gpt-6-astra` and `gpt-5.6-sol`;
   the stewards now run **`gpt-6.1-sol`** (model policy `latest_supported`/`highest_supported`, effort `ultra`).
   No row → `None` → the turn stays unpriced. Silent: the policy upgrade never updated the table.
2. **Grok — the bridge throws the dollars away.** The Grok CLI's result event carries `total_cost_usd` (a real
   review this session: $0.38, 14 calls, `grok-4.7-build`), but `steward_cockpit/grok_turn_bridge.py` (~523) copies
   only the token `usage` and `modelUsage` into its result; `total_cost_usd` never reaches the engine, so every Grok
   turn counts as unpriced and shows as "Grok subscription (N turns)".
3. **Gemini — not runnable as a steward, and no usage parser.** `switch_cli` only allows a family that is one of the
   settings' default/coding/review families (`chatgpt`/`chatgpt`/`grok` now); Gemini runs through `agy`, which has
   no usage/cost path in the engine. (His 2026-08-31 rule dropped Gemini from review seats.)
4. **The dashboard and summary lines never show estimates.** The cockpit status line (`shared.js` ~1813) does show
   "about $X estimated", but `fmt_usage_cost_text` — used by the project rows, the High Seat/Cave summaries
   (`_fmt_steward_usage_clause`) — ignores `estimated_spend` and prints "ChatGPT subscription (N turns)".

**Not a bug, but worth saying:** Claude's dollars are the CLI's API-equivalent figure, labelled "reported"; on a
subscription they are not a charge either.

**Proposed fix (for his word):** (a) add `gpt-6.1-sol` at OpenAI's published price, and make a model missing from
the table loud (one status line) instead of silent; (b) keep Grok's `total_cost_usd` in the bridge result; (c) show
estimates in the summary lines (`fmt_usage_cost_text`); (d) backfill estimates for past ChatGPT turns from their
recorded tokens; (e) Gemini only if he wants a Gemini steward back.
