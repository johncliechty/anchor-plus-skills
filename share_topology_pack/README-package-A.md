# Skills-only (Package A) — Shareable release

> **Dual audience.** Download & use · Invited to collaborate · Optional sanitized friction sharing. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Which path are you on?

| Path | Who | What you do |
|------|-----|-------------|
| **Download & use** | Public consumer | Install release artifacts; local edits stay local |
| **Invited to collaborate** | Collaborator | Branch + PR on private `*-dev` only |
| **Optional friction sharing** | Opt-in user | Sanitized feedback intake — **not** code push to main |

## Three paths (use / sanitized-feedback / collaborate)

```
  [use]  Download & use ──► local install; edits stay local
  [sanitized-feedback] ──► opt-in friction intake (NOT code push to main)
  [collaborate] ──► invited branch/PR on private *-dev only
```

1. **Download & use** — Download & use — pin to release artifacts (not floating main); local edits stay local; no write access to upstream.
2. **Sanitized feedback** — Optional sanitized friction feedback — opt-in only; separate John-controlled intake channel; NOT a code push to main or a PR into product sources. See docs/share-feedback-intake.md.
3. **Collaborate** — Invited collaborate — private *-dev invite, feature branches + PR only; no force-push; no direct push to main; CODEOWNERS review.

## Pin to release artifacts (not floating main)

Consumers must pin to **published release artifacts** (tagged, scrubbed packages). Do **not** track floating `main` as your install source — private development history is not the consumer product.

## Privacy / friction

- Feedback is **opt-in**, fail-closed, and de-identified.
- Full local journals never leave your machine via this channel.
- Details: [`docs/share-feedback-intake.md`](../docs/share-feedback-intake.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Package identity

- **Package id:** `A`
- **Never ships:** Anchor-only (hard-blocked by package matrix).

## Mirror lag badge

Public README may embed the output of `mirror_lag_badge(...)` so consumers know when private tags have not yet been published.

## Links

- [CONTRIBUTING.md](CONTRIBUTING.md) — write policy + three paths
- [`docs/share-feedback-intake.md`](../docs/share-feedback-intake.md) — feedback intake (not product write access)
- [`docs/share-topology.md`](../docs/share-topology.md) — topology ops
- [`docs/share-release-captain-checklist.md`](../docs/share-release-captain-checklist.md) — captain gate
