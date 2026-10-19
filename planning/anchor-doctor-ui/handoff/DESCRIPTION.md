# Anchor Doctor UI V3 — Honest Agentic Diagnostics

Replaces the V2 doctor build (commit 65e93e1), whose plan mandated a `google.generativeai` API-key wrapper (stdlib-only violation, unusable on a subscription-CLI host) and whose UI shipped fabricated data (fake disk %, fake chart, dead nav) plus a literal-`{fname}` f-string rendering bug.

V3: the `/doctor` page matches the existing Anchor dashboard style, shows only real data, and its terminal is a genuine read-only agentic session on Anchor's existing PTY/session substrate, engine-honest per the W8 model-flex policy (subscription CLIs only — never an API key).
