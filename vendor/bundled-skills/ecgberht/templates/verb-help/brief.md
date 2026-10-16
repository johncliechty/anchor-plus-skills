# Verb: brief

**Closed list:** yes · **Primary:** brief

The Oranges Brief / Decision Packet: the fixed question set (Q1–Q9 project; Q10–Q12 portfolio) answered by deterministic retrieval from local stores only — per-answer provenance, honest `unknown — no local evidence` where a store is silent.

- **Phase A** assembles the whole packet with **zero model / commission calls** (works fully offline).
- **Phase B** (`--phase-b`) optionally asks a model to recommend; model unavailable → Phase A complete + `recommendation: unknown`. Never required for green.
- **Goal card is mandatory** in every packet ("remember the goal") — honest unknown when no Face north star exists.
- **`seen` receipt** `{kind, who, when, altitude}` (`--mark-seen --who <who>`) is the append-only delta anchor: the next brief's Q2 shows only post-`seen` instruments/receipts/journal.
- **Roadmap-aware position**: Q1 reads the typed Campaign Roadmap projection (engine truth; prose never invents steps).
- **Anchor knowledge (Q7)** reads `.anchor/projects/<p>/{planning,research}/summaries` + `deliverables` **read-only**; missing/ungrounded store → `unknown`.
- **Precompute cache** (`--precompute`, or `update --precompute-brief`) writes `brief-cache.json` — a declared projection (zero write authority, regenerable, never read back as truth). `--cached` serves it instantly with a staleness stamp; `--refresh` recomputes.
- Footer coverage stamp: `answerable k/N from local evidence`.

Usage:

- `node bin/ecgberht.mjs brief [--project <path>]` — project packet (Phase A)
- `node bin/ecgberht.mjs brief --roots <a,b>` — portfolio packet (Q10–Q12)
- `node bin/ecgberht.mjs brief --mark-seen --who john` — view + stamp seen
- `node bin/ecgberht.mjs brief --cached` / `--refresh` — cached serve / recompute
- `--altitude project|portfolio` · `--anchor-root <path>` · env `ECGBERHT_ANCHOR_ROOT`

TW2. Modules: `engine/brief.mjs` · `engine/anchor-knowledge.mjs` (read-only). Spec: `research/e9-e10/W7-BRIEF-SPEC.md`.
