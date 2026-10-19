# Release Checklist

This checklist gates each release.

**Read this first.** Until v1.2.3 every box below was unchecked and had been
through two shipped releases that way — v1.1.3 went out on a different evidence
set entirely (the three acceptance suites), and nothing recorded that the stated
gate and the practised gate had diverged. An all-unchecked checklist sitting in
a public repository is a false signal to anyone who reads it. So the list is now
split: what actually gates a release today, and what is aspirational and named
as such.

---

## Part A — the gate (must be GREEN to ship)

Run from a **clean worktree of committed HEAD**, never the working tree
(a dirty tree once leaked uncommitted WIP into a build; the import-closure gate
correctly refused, but only by luck of what was dirty):

```text
git worktree add --detach <tmp> HEAD
ANCHOR_SHIP_OUT="C:\dev\Anchor-ship" python <tmp>/planning/share-anchor-skills-2026-07/_build_clean_ship.py
```

- [ ] **Build fail-closed from committed HEAD** — `_build_clean_ship.py` exits 0.
      Covers the no-personal-data scan, the import-closure gate, the
      startup-import gate, and the scrub-residue gate. Record the file counts.
- [ ] **Stranger sandbox 10/10** — `python tools/share_sandbox.py`
- [ ] **Pull dry run 7/7** — `python tools/pull_dry_run.py`
      (simulated collaborator install against the built package)
- [ ] **Targeted test net green** — the distro / doctor / share suites.
      The full suite is not run wholesale (known flaky under load; regen traps).
- [ ] **Version stamps agree** — `VERSION` == `pyproject.toml`. Bump both
      together; G3 asserts agreement, not a literal.
- [ ] **Vendored skill pins are intentional** — check
      `vendor/bundled-skills/SOURCES.md` against the source repos. Vendoring is
      `git archive` over a **commit**, so anything uncommitted in `trio` /
      `Skill Foundry` does NOT ship. Confirm that is what you want.
- [ ] **Human spot-check of the staged bundle** — a deliberate release act, not
      per-commit. Open it and look at it.
- [ ] **CHANGELOG entry states what is still open, by name.**

## Part B — publish

- [ ] **Tag from the reviewed commit.** Never assume the newest tag is the best
      commit: at v1.2.2 the tagged artifact was the defective one and the
      untagged tip carried the repair.
- [ ] **Publish** — `python tools/publish_share_repo.py` (mirror → force-add →
      count invariant; refuses to push if any built file failed to track).
- [ ] **Verify from a real clone**, not the local build — file count, skill
      count, and the pull dry run against the clone.
- [ ] **Confirm there is exactly one URL to hand out.** The older public
      `Anchor` repo is still reachable and serves months-old code; archive or
      redirect it.

## Part C — aspirational (NOT currently gating; do not pretend otherwise)

These are standards worth reaching. None has gated a shipped release yet.
Leaving them here is deliberate — deleting them would quietly retire them —
but they are marked so nobody reads an unchecked box as a missed step.

- [ ] **External red-team pass** per release cycle against the staged bundle,
      covering claim flow, pairing flow, WS upgrade, control channel, and
      exposure refusals. *Never performed.*
- [ ] **All red-team findings triaged to closure.** *Blocked on the above.*
- [ ] **SSH-signed release tags** (`gpg.format=ssh`), author-side. *Tags to
      date are unsigned.*
- [ ] **`release-map.json`** recording source SHA → release SHA at tag time.
      *Not maintained; the public history is a curated export with no
      merge-base to the dev history, which is exactly why such a map would
      earn its keep.*
- [ ] **True-VM check** — `python C:\dev\Anchor-ship\vm-sandbox\host_run.py`.
      *Staged since 2026-08-02, still pending; the clean-profile run is the
      current approximation.*
