# Anchor R&D Surface v8 — "Durable Artifacts" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-17

**What was asked:** Anchor R&D Surface v8 — "Durable Artifacts" — Master Plan (frozen design)

**North Star:** Make every trio session's **work durable, discoverable, and resumable**, and make the project a real git-backed home for it: 1. **No project starts broken.** Opening Research/Planning on a project with no git repo must not error. On register / open / **rescan**, if there's no local git repo → `git init`; if there's no `CLAUDE.md` → create a starter one; and offer a permission-gated **"Link GitHub"** (create a new private repo via `gh`, or paste an existing URL). Once linked + opted in, **auto-push after each session finishes** (Option A) plus a manual "Push now"; rescan sets up git/remote if m

## Actions & files produced

- Anchor R&D Surface v8 — "Durable Artifacts" — Master Plan (frozen design)
- Anchor R&D Surface v8 — "Durable Artifacts" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Anchor R&D Surface v8 â€” "Durable Artifacts" â€” Planning Trio Summary
- **Goal / North Star (locked â€” John's Stage-0 answers)**
- Make every trio session's work **durable, discoverable, and resumable**, and make the project a real **git-backed home** for it.
- **No project starts broken:** opening Research/Planning on a project with no git repo must not error. On register / open / **rescan**, if there's no local git repo â†’ `git init`; if there's no `CLAUDE.md` â†’ create a starter one.
- Offer a permission-gated **"Link GitHub"** â€” create a new private repo via `gh`, or paste an existing URL.
- **Locked decisions (Stage-0 user gates)**
- **#1 GitHub = Option A (approved):** permission-gated link prompt â€” create-new private repo via `gh` (John authed as `johncliechty`) **or** paste-existing.
- After a project is **linked + opted in**, **auto-push after each session finishes**, plus a manual **"Push now"**.
- **Local commits are automatic + unconditional** (required for the keystone); **offsite push is opt-in per project**.
- **Rescan sets up git/remote if missing.**
- **#2 keystone = commit-to-project:** trio docs are committed to the project's **own git repo on session finish** (and captured **before reap**). The **build worktree, created off main HEAD, then contains them.**
- **Member documents**
- Master Plan (frozen design) and Implementation Plan (Foreman-ready) for v8 "Durable Artifacts."
- **North Star (locked):** v8 makes every trio session's work **durable, discoverable, and resumable** and turns the project into a real git-backed home for it.
- **No project starts broken:** opening Research/Planning on a repo-less project must not error â€” on register/open/**rescan**, missing git â†’ `git init`, missing `CLAUDE.md` â†’ write a starter, and offer a permission-gated **"Link GitHub."**
- **Link GitHub (#1, Option A â€” approved):** create a new **private** repo via `gh` (John authed as `johncliechty`) or paste an existing URL; once linked + opted in, **auto-push after each session finishes** plus a manual **"Push now."**
- **Push policy:** local commits are **automatic + unconditional** (required by the keystone); offsite push is **opt-in per project**; rescan sets up git/remote if missing.
- **Keystone (#2 â€” commit-to-project):** trio docs are **committed to the project's own git repo on session finish** and **captured before the worktree is reaped**.
- **Build worktree consequence:** created off **main HEAD**, the build worktree then **contains** the committed plan/research docs â€” enabling discovery and resumption downstream.
- **Member documents:** the frozen **Master Plan** (design) and the Foreman-ready **Implementation Plan**.

## Files

- [Anchor R&D Surface v8 — "Durable Artifacts" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v8%2FMASTER-PLAN.md)
- [Anchor R&D Surface v8 — "Durable Artifacts" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v8%2FIMPLEMENTATION-PLAN.md)
