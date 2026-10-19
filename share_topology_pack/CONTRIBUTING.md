# Contributing — Shareable Anchor + Skills

This project is **dual-audience**: public consumers download and use; invited collaborators work on private `*-dev` via branch/PR. Sanitized friction feedback is a **separate** channel — it is **not** a code push to main.

## Three paths (use / sanitized-feedback / collaborate)

```
  [use]  Download & use ──► local install; edits stay local
  [sanitized-feedback] ──► opt-in friction intake (NOT code push to main)
  [collaborate] ──► invited branch/PR on private *-dev only
```

1. **Download & use** — Download & use — pin to release artifacts (not floating main); local edits stay local; no write access to upstream.
2. **Sanitized feedback** — Optional sanitized friction feedback — opt-in only; separate John-controlled intake channel; NOT a code push to main or a PR into product sources. See docs/share-feedback-intake.md.
3. **Collaborate** — Invited collaborate — private *-dev invite, feature branches + PR only; no force-push; no direct push to main; CODEOWNERS review.

## Public consumers (read-only)

- Pin to **release artifacts**, not floating `main`.
- Local edits stay local; they do not flow back to upstream.
- You may open issues. You may **not** open unsolicited PRs into private upstream without an invitation.

## Sanitized feedback (optional, not code contribution)

- Opt-in only (default off). Fail-closed sanitizer.
- Lands in a John-controlled **feedback intake** for pull/review only.
- **Not** a code push to main; **not** a product write path.
- Ops detail: [`docs/share-feedback-intake.md`](../docs/share-feedback-intake.md).

## Invited collaborators

- Invite is required to the private `*-dev` source of truth.
- Push **feature branches** only; open a **pull request** for review.
- **No force-push** and **no direct push to main** (branch protection).
- CODEOWNERS review is required on protected paths.

## Uninvited pull requests

This repository's private *-dev source of truth does not accept unsolicited pull requests from the public. Public consumers may (1) download & use release artifacts, (2) file issues, or (3) optionally opt into sanitized friction feedback — which is NOT a code contribution and is not a PR into product main. To contribute code, request a collaborator invite first; then push only feature branches and open a PR for review.

## Backlog SLA (honest)

Invited collaborator PRs are reviewed when the maintainer is free — there is no guaranteed turnaround SLA. Uninvited public PRs into private upstream are not accepted.

## Release topology

- Private `*-dev` is the source of truth.
- Public mirrors are **one-way** publish from private (bot-only write; human hand-edit of public mirrors is forbidden).
- Mirror lag is checked: a private release tag without a matching public publish raises an alert; consumers stay on the last public release artifact.

## Privacy / friction

See package README privacy section and [`docs/share-feedback-intake.md`](../docs/share-feedback-intake.md).
