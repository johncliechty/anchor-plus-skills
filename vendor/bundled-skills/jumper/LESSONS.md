# LESSONS — jumper (sleep-cycle promotion 2026-08-15; 24 entries, first promotion)

1. **Wait for out.json or HALT.json — heartbeat silence is NOT death, and a
   wrong survivor file is NOT DONE.** The cadence agent falsely declared a
   live run complete (0014) and operators killed healthy runs (0008); the
   inverse — treating a stuck seat as working — burned a talk deadline.
   Liveness = the artifact contract, never log rhythm. (0005/0008/0011/0014)
2. **`2>&1 | tail` buffers heartbeats to EOF** — stdout reads 0 bytes for a
   45-minute run and the operator flies blind (0022, repeated verbatim in
   0024 AFTER reading 0022: knowing a lesson is not applying it). Tail the
   status FILE, never the pipe.
3. **A liveness check must watch the processes the run actually spawns** —
   0024 nearly killed a healthy run on a node.exe-only metric while the live
   seats were claude.exe/grok.exe children.
4. **Budget-HALT is draft variance, not escalation** — firing-elevation count
   varies by draft, so jump straight to generous headroom (`--budget 8`)
   instead of paying a HALT per notch (0021/0023/0024). And a Gate-1 PARSE
   failure must be distinguishable from a real kill in the survivor count
   (0024, open).
5. **Pre-flight everything that can refuse at t=0** — output-dir existence
   (0019: ENOENT after a 45-min tournament destroyed the killLog; run-capture
   wrote only on success), seat auth (0006: single-family surfaced after
   ~8 min of paid seats — now a t=0 refusal). Artifacts are written
   crash-first: mkdir at launch, capture on failure too.
6. **Jumper produces analytical FRAMES, not terminal artifacts** — two Heavy
   zero-survivor runs (0021/0022) asked for objects and got disciplines;
   state the pass predicate explicitly for aesthetic/naming tasks and
   instantiate frames before Gate-3. (hypothesis, 2 corroborating runs)
