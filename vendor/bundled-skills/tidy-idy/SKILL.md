---
name: tidy-idy
description: >-
  Folder hygiene with a Triage Panel — run on any folder (git repo or plain
  directory), open the decision panel for removals/SAVE/reorg/secrets, and Apply
  once per run via reversible Trash (+ optional git commit). Anchor's button is a
  thin caller of the same CLI. Capability token stays in browser memory only.
---

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# tidy-idy

Repository hygiene for any folder: run a hygiene pass, open the **Triage Panel**,
approve findings (removals, SAVE, reorganization proposals, secrets), and
**Apply once per run**. Removals go through the **reversible Trash** (restore
supported). When a git repository is present, Apply can also commit; plain folders
are supported without a hard refusal — optional Bootstrap (`git init`) is an
upgrade, never a launch gate.

> **Tier definition (stakes-gated cross-model · invocation discipline · run capture):** canonical in
> `AGENTS.md` (Foundry root on the author host; your install root in a distributed bundle). Do not re-define or deliberate any of it at start.

## How to run (operator manual — truth-aligned to shipped code)

### Canonical entry point

```
node bin/tidy-idy.mjs <folder> [options]
```

Same entry is used from a terminal **and** from Anchor's Tidy-Idy button (thin
caller). Works on **any** folder: an Anchor project, or a plain directory outside
Anchor. Default path opens the Triage Panel in a browser (when serving).

**Options** (must match `node bin/tidy-idy.mjs --help` / `USAGE` in `bin/tidy-idy.mjs`):

| Option | Meaning |
|--------|---------|
| `--no-open` | Run and serve the panel, but do not open a browser |
| `--no-serve` | Run and archive only; no panel server; lock released |
| `--json` | Machine output (used by Anchor's thin caller) |
| `--environment=<env>` | `standalone` (default) \| `anchor` \| `none` |
| `--nonce-file=<path>` | Write the single-use bootstrap URL to this 0600 file |
| `--port=<n>` | Bind the panel to this loopback port (default: free) |
| `--mode=<mode>` | `north-star` \| `heuristic` \| `advisory` (default: detected) |
| `--idle-timeout=<seconds>` | Close the panel and release the lock after this long |
| `--no-cost-gate` | Skip the pre-scan cost gate (full scope) |
| `--no-verdict-cache` | Do not read or write the content-hash verdict cache |
| `--help` | Print usage |

Stdout discipline under `--json` (safety, not cosmetics): print the panel **base**
URL and the path of the 0600 bootstrap file — **never** the single-use bootstrap
URL on the durable log stream, and **never** the capability token on any path.
The opener reads the nonce from the file; the server unlinks it on redemption.

### Anchor thin caller

Anchor does **not** re-implement launch/panel/archive. The button:

1. Dispatches **this same** entry via `job_runner` with argv shaped like  
   `node bin/tidy-idy.mjs <folder> --environment=anchor --json [--nonce-file=…]`
2. Opens the single-use bootstrap URL the run produces (nonce file → open)

Contract and source facts: `docs/anchor-job-runner-integration-contract.md` and
`engine/launch/anchor-caller.mjs`. There is **no second capability channel**.

### Operator story (what you use)

1. **Launch** — `tidy-idy <folder>` takes the project lock, runs the pipeline stages
   (scan / preflight / hygiene / analysis paths as applicable), and serves the panel.
2. **Triage Panel** — decision-first cards for findings; approve/reject per item.
   Includes **reorganization proposals** (before→after trees) when the reorg stage
   emits them; Trash view for prior move-sets; SAVE / secrets classes as shipped.
3. **Apply (one per run)** — human-driven only; **no auto-apply**. One Apply per
   run settles approved findings into a single control-plane transition. Removals
   use the **Trash move-set** (restorable); with git present, Apply also uses the
   git commit path where the executor contracts require it. Undo/restore follows
   Trash restore and/or git revert as applicable — not “delete-only forever.”
4. **Close** — panel idle timeout or explicit close releases the lock. Re-scan for
   leftover work after an Apply (one Apply does not silently re-arm for a second
   Apply on the same run).

### State & reports (not only “`.tidy-idy/` is the whole product”)

Primary report/state root is **`<folder>/.tidy-idy/`** (derived from the target
root, never from accidental CWD). A run also uses that tree for apply-state,
panel-server artifacts, archives, status shells, and related launch files as
implemented under `engine/launch/` and `engine/report-dir.mjs`. Operators treat
`.tidy-idy/` as the project-local state home; it is not a claim that no other
process surfaces (status URL, panel server, archive dir) exist.

### Legacy batch entry (not the GUI product)

```
node bin/tidy.mjs [targetDir]
```

Still present as a **legacy Foundry batch** orchestrator (git-required hygiene
pre-flight → batched North-Star analysis → debate → delete+commit remove →
compress). Prefer **`bin/tidy-idy.mjs`** for the panel product and for Anchor.
Do not treat `tidy.mjs` as the operator-facing default.

### Safety invariants (parent North Star — unchanged by GUI polish)

Polish does **not** redesign the apply control plane:

- **No auto-apply** — Apply is an explicit human action in the panel.
- **One Apply per run** — a second Apply on the same run is refused; re-scan for leftovers.
- **Capability token** travels in browser memory / request header only — **never**
  on disk, never in a URL query, never in `localStorage`.
- Bootstrap handoff uses a **single-use nonce** (0600 file / redeem-once URL), not
  the long-lived capability token on the wire log.
- Thin caller and bare CLI share the same entry and the same safety story.

### Design truth (mockups — SC1 stage lock)

Canonical CURRENT mockups (only these; not a second CURRENT home):

`<path>

| File | Lock |
|------|------|
| `tidy-idy-mockup-A-triage.html` | CURRENT — triage panel |
| `tidy-idy-mockup-A2-reorg.html` | CURRENT — A2 **Option 1 only** (per-proposal before→after trees) |

A2 Option 2 (sorting buckets) and Mockups B/C are **REJECTED** (see
`design/archive/` and `docs/w1-mockup-hygiene.md`). Skill-root pointer:
`docs/w5-operator-truth.md`.

> **⏱ STATUS UPDATES TO CHAT:** When running long phases in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s) and provide scheduled updates to the user in the LOCKED Status-table format — canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

## Usage journal (lessons — append after every REAL run)

Append one `NNNN-<slug>.md` to `journal/` (7 canonical fields — id/skill/situation/context/
observation/outcome/provenance; ≤15 lines; append-only). The machine record is auto-captured;
the NNNN entry is for what the run TAUGHT you.
