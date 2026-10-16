# Zombie Hunter

**One sentence:** A safety-first reaper for Anchor that freezes or kills only proven-orphan agent swarms — and abstains by default whenever ownership or liveness is uncertain.

## Use this when
- Orphaned agent processes are burning resources after their real work is gone
- You need an evidence-gated cleanup path, not a guessy process killer
- You’re operating Anchor and want lifecycle hygiene with kill-switch controls

## Do not use this when
- A run is merely quiet, waiting on a question, or still owned by live work
- You want aggressive “kill anything idle-looking” behavior
- You’re cleaning files on disk (use Tidy-Idy)

## What you get
- Ownership-based liveness (keeps legitimate runs, including blocked-but-owned work)
- Positive proof-of-death before destructive action; uncertainty → keep
- Arming ladder: log/observe → reversible freeze → kill, earned by evidence
- Operator radar with multi-engine Burn Ledger (Claude measured $; Grok estimated from xAI list rates; Gemini/OpenAI when present)
- Auto-refresh while the radar is open (~90s) so you can watch a hunt without re-scanning by hand
- Operator visibility (why a process was kept, frozen, or targeted)

## What it is not
- Not armed by default — destructive capability is earned and can be disarmed
- Not an identity-token party trick that kills on a name match
- Not a license to free up CPU by slaughtering supervised sessions

## How to start (human)
1. Treat it as part of Anchor operations; start from observe/log mode.
2. Read the operator runbook for arming requirements and the kill-switch file.
3. Advance arm tiers only when evidence bars and receipts say it’s safe.
4. Prefer freeze first; kill only when proof-of-death and policy allow.

## Limits (honest)
- Fail-safe means some true orphans may live until evidence is clear
- Freeze/kill capabilities depend on host and arm tier
- Misconfiguration or missing receipts refuses to arm rather than “wing it”

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
