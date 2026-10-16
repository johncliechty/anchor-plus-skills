# LESSONS — literature-review

1. **A test constant is not a production default.** The 50ms backoff base (~0.7s total
   budget) shipped because tests tuned it for speed — the skill's only real run died on
   a 429 it could never survive. Production defaults live apart from test knobs; tests
   inject their own. (journal 0001 → fixed 0002)
2. **The first calls of a run need retries most.** The two seed-resolution calls had
   zero retry while the walk had three — a 429 at t=0 killed everything downstream.
   (journal 0002)
3. **Silent truncation is an honesty bug, not a robustness feature.** "Proceed with
   whatever we have" without a stamp made a rate-limited run indistinguishable from a
   complete one. Every loss gets a PRISMA row. (journal 0002)
4. **Single provider = single point of total outage.** The 429 wasn't a retry problem
   at heart; it was an architecture problem. (residual: OpenAlex fallback)
