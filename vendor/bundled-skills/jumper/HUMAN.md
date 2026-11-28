# Jumper

**One sentence:** An ideation engine that forces structured creative leaps (SCAMPER, analogy, TRIZ), then kills weak ideas so you only see survivors with a concrete way to test them.

## Use this when
- You’re stuck and need genuine options, not the first three clichés
- You want architecture extensions, pivots, or out-of-domain analogies
- You need brainstorming that is vetted, not a hallucinated wish list

## Do not use this when
- You need diagnosis of an existing artifact (use Gandalf)
- You need a locked build plan (use Crucible)
- You only want a quick “pros and cons” of one idea you already have

## What you get
- Divergent candidates built through structured methods
- A ruthless kill-filter so shallow or impossible ideas die early
- Survivors in build order (the engine does not rank; judge them against your brief) plus a grounding plan (how you’d actually try the winner)
- A kill log so you can see what died and why
- A lean mode (`--mode lean`): one generation pass, then one independent cross-family review of every candidate — two calls, when you want vetted candidates fast

## What it is not
- Not pure free-association chat
- Not a substitute for research or engineering proof
- Not a guarantee the surviving idea will work — only that it survived structured filters

## Variable Strength (`Jumper` Standard Default vs. `Jumper Heavy` vs. `Superjump`) — What to Call When
- **Call `Jumper` (default = `Standard` · one generalist model below frontier @ `medium` effort on generation and cross-family kill-filter)** when you want fast vetted lateral options (`--mode lean` or standard tripartite pass) for everyday design pivots, feature ideas, or framing bottlenecks.
- **Call `Jumper Heavy` (`⚡ Heavy` · frontier model @ full effort on generation, composed Gandalf, and cross-family kill-filter)** when you want Jumper's fast tripartite/lean workflow backed by frontier model depth on a high-stakes pivot.
- **Escalate to `Superjump` (`⚡ Heavy` by default, with `Superjump Light` available)** when you have explicit `MUST` / `FIXED` / `FORBID` / `JUDGE` constraints and want unbounded progress-watched analogical leaps judged against a formal Fit Contract.

## How to start (human)
1. State the problem as clearly as you can (constraints and what “good” means).
2. Run Jumper (optionally more fan-out for more parallel candidates).
3. Review survivors and the kill log.
4. Use the grounding protocol to test the winner in the real world.

## Limits (honest)
- Creativity still has bounds; some problem spaces yield no survivors
- Independence of the last kill gate can fail closed if a second review family is down
- Composes Gandalf for rigor — it is not a light parlor game

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
