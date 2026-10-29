# Sleep feed — wall-clock + hang productivity (share-anchor + host-wide)

**Purpose:** End-of-effort Foundry sleep for share-anchor must pull **this effort’s journals** and **other concurrent sessions’ skill journals** on this host. All paths below are readable from this machine (verified 2026-07-23).

## Principle

Wall clock is fine when **dangerously productive**. Fake RED, silent death, and true hangs that wait forever are **skill bugs**.

## Canonical journals — this share-anchor effort

| ID | Path |
|----|------|
| **0078** (primary) | `<path> — also under `<path> |
| **0070** | `…\crucible\journal\0070-share-effort-wallclock-productivity-cluster.md` |
| **0069** | Stage-2 approved re-tank no emit |
| **0068** | Stage-1 wall-clock investigation |

## Hang / stall (must not confuse with fake RED)

| Class | Sleep home |
|-------|------------|
| Timeout incomplete (fake RED) | **0078** recipes A–C, tickets T1–T3, T7 |
| Silent mid-wave death | **0072** cluster, **0075** process-lifetime fix (landed code: `trio/drivers/process-lifetime.mjs`) |
| True hang (alive, no progress) | **0078** T8–T11 watchdog ladder; Jumper **0005** sparse logging |

## Concurrent runs on this host — journals ARE accessible

Verified recent writes (same day) under:

| Skill | Journal roots (either is fine; often mirrored) |
|-------|--------------------------------------------------|
| **Foreman** | `<path> · `<path> |
| **Crucible** | `<path> · `<path> |
| **Jumper** | `<path> · `<path> Foundry\skills\jumper\journal\` |
| **Gandalf** | `<path> (+ `runs/`, `side/`) · Foundry twin |
| **Portfolio program** | `<path> · `FRICTION-JOURNAL.md` |

### Recent concurrent-run learning (examples already on disk)

- Jumper **0005** — sparse stage logging looks like stall (Ecgberht)  
- Jumper **0003–0007** — refuter budget, self-review single-family, etc.  
- Gandalf **0280** + run side dumps same day  
- Foreman **0079–0080** — execute vacuous / skill-improve guardrails (other session)  
- Crucible **0070-e1** Family Finances LITE revise JSON  
- Portfolio **SLEEP-FEED.md** — indexes F-H process lifetime, execute thrash, etc.

**Sleep procedure for share-anchor final improvement wave:**

1. Open this file + **0078**.  
2. Open portfolio `SLEEP-FEED.md` and skim `FRICTION-JOURNAL` for F-numbers still open.  
3. Glob skill journals modified since share-anchor start (or last 7 days):  
   `foreman|crucible|jumper|gandalf|researchPrime` under `~\.claude\skills\*\journal\` and `Skill Foundry\skills\*\journal\` and `trio\*\journal\`.  
4. Only **genuine-execution** entries corroborate sleep decisions.  
5. Do **not** treat this chat alone as the sleep corpus — journals are the feed.

## Ticket shortlist for final sleep (combined)

**P0 fake RED / gate:** T1–T3, T7  
**P0 hang honest:** T8–T10 (+ prove **0075** process-lifetime on multi-wave)  
**P1 thrash:** T5 Stage-2 emit, revise patch, NS-by-reference  
**P1 cross-skill:** T11 shared progress events (Jumper 0005)  

## What we do NOT promise until sleep ships

- “Never hung.”  
- “10-minute chat alone detects stalls.”  

We promise after P0: budgets, loud death, progress stamps, and no fake 0/0/0 RED.
