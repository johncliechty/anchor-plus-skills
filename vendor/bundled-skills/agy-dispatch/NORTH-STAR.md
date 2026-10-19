# North Star — agy-dispatch (written 2026-07-25)

> The 2026-07-25 review found this transport to be the portfolio's least-governed
> load-bearing artifact: every skill's cross-family adversarial review rides it, yet it
> had no North Star, no journal, no registration, and shipped a phantom default model
> its own canonical driver documented as a silent-degrade hazard. This lock closes that.

## The objective

Be the BORING, HONEST transport: deliver a prompt to Gemini via the `agy` CLI and bring
back the reply — with every failure mode SURFACED to the caller as a typed reason, and
zero classes of silent degradation.

## Criteria (each is a refusal, not a hope)

1. **No phantom models.** Only catalogued agy LABEL ids leave this dispatcher; an
   uncatalogued id is refused pre-spawn (`MODEL_LABEL_UNKNOWN` + remedy) unless
   `--force-model`. A substituted serve is `status: model_substituted` + `servedModel`
   — NEVER `success`. (The old `gemini-3.1-pro` default silently degraded every
   default call to Flash while reporting success — the crucible-0005 fake-dry class.)
2. **Auth failures name themselves.** A logged-out agy is `NOT_LOGGED_IN_ANTIGRAVITY`
   with the remedy (re-login to the Antigravity APP; there is no `agy login` CLI) —
   never laundered into "reply was not valid JSON" four layers downstream.
3. **Reply identity is bound.** The reply comes from THIS call's conversation id (B6)
   — a cross-wired sibling answer is worse than no answer; never guess.
4. **No shell popups.** The no-shell STEER + belt flags stay; Gemini works file-tools-only.
5. **The DRIVER is canonical.** `trio/drivers/gemini-cli.mjs` owns the contract
   (labels, attestation); when agy changes, the driver updates FIRST, then this mirror
   — a drifted mirror is a bug even when it "works".
6. **Health is one command.** `--selftest` answers "is agy healthy?" (auth + model
   catalog + a tiny round-trip) before any long run pays for the answer.

## Non-goals

- Not a seam/retry/abstain layer (that is the driver's job); not a queue; not a second
  model catalog (mirror only, rule 5).
- Not a sizer: sizing/tiers are the CALLER's job — deliberately (John-ratified, 2026-08-25).
