# 2026-07-30 — Steward: goal refused (token re-prompt → "Unknown endpoint")

- **id**: `2026-07-30-01-steward-goal-refused-unknown-endpoint-an`
- **surface**: Project window · **steward chamber** (stand-up / set the goal) — and the same faults under the main dashboard **High Seat**
- **situation**: Entering a goal re-prompted for an already-stored token; after that was fixed, it refused with `Couldn't do that: Unknown endpoint — nothing was created.`
- **severity**: problem (the steward could not be used at all with auth on)
- **status**: **FIXED + gated** (`e102ddd`, `cb6ab30`, and this pass)
- **provenance**: genuine-user-report + code inspection + end-to-end browser reproduction
- **continues**: [`2026-07-28-high-seat-token-reload-loses-input.md`](2026-07-28-high-seat-token-reload-loses-input.md) — that record fixed the reload *symptom*; this one fixes the 401 *cause* it sat on, and finally ports the retry to the project window.

---

## What John said (verbatim)

> I thought that we got the steward up and working, but when I tried to enter a goal into a project level steward it did not let me. Instead it asked for a token again (which it had stored in the window). I suspect that the same thing happens when I try and use the steward in the main Anchor Dashboard.

Then, after the token transport was fixed:

> When I tried to set a goal, I did not get a problem with the token, but I did get the following error: Couldn't do that: Unknown endpoint — nothing was created.

His suspicion was right on both counts: the same fault sat under the High Seat, and the first fix uncovered a second one behind it.

---

## Failure chain (three independent faults, all auth-ON only)

```text
User types a goal → [Set the goal]
        │
        ▼
POST /api/ecgberht/stand_up?token=…
        │
        ├─(a) do_POST reads X-Anchor-Token / Authorization / body.token
        │     — NEVER the query string            → 401
        │              │
        │              ▼
        │     global 401 wrapper → prompt for a token the window already has
        │     (and, in the project window, location.reload() → typed goal lost)
        │
        ├─(c) dispatch used the RAW request line; route_table.match compares an
        │     EXACT row with path == pattern, so ?token=… missed the row
        │
        └─(b) …and even on a bare path, handle_ecgberht_stand_up was declared
              migrated=True but never registered in _MIGRATED_HANDLERS, so the
              strangler fell through to the legacy chain
                             │
                             ▼
              404 {"error": "Unknown endpoint"}
                             │
                             ▼
        "Couldn't do that: Unknown endpoint — nothing was created."
```

Same class, found by the new gate while fixing (b): `handle_friction_list`
(`GET /api/rnd/friction`) and `handle_journal_friction`
(`POST /api/rnd/journal_friction`) had the identical omission and **no legacy
fallback** — both were dead 404s. The friction journal's own read endpoint was
among the casualties.

---

## Why a green suite sat on top of a broken dashboard

**With `ANCHOR_TOKEN` unset, `_tokenQ()` is empty and every one of these faults
disappears.** The URLs become bare paths, no 401 is ever raised, and the
dispatch bug cannot fire. Virtually the entire suite — including every
Playwright flow — runs **auth-off**. So the product was broken in exactly the
configuration John runs and healthy in the configuration the tests run.

That is the real lesson here, bigger than any one of the three bugs.

---

## What was fixed

| # | Fault | Fix |
|---|-------|-----|
| a | token sent as `?token=` on POSTs | `_postJson` / `_ecgHsHeaders()` — the token rides `X-Anchor-Token` (+ `X-Anchor-Build`) |
| b | `migrated=True` rows with unregistered handlers | registered `handle_ecgberht_stand_up`, `handle_friction_list`, `handle_journal_friction` |
| c | `do_POST` dispatched on the raw request line | dispatches on `urlparse(path).path` (handlers still receive the full URI) |
| d | project window reloaded on 401, losing typed input | ported the home page's **retry, don't reload** wrapper (2026-07-28) |

---

## Gates added (each verified to FAIL on the pre-fix code)

- `tests/test_steward_goal_authon_2026_07_30.py` — **auth ON**. Sets a goal in a
  real browser and asserts the outcome: no token re-prompt, no "Unknown
  endpoint", and `ECGBERHT.md` + `strip.json` on disk with the North Star
  verbatim. Plus reachability of every mutating steward endpoint.
- `test_every_migrated_route_has_a_registered_handler` — a route row is a
  promise; this makes the promise checkable. It is what caught the two friction
  routes.
- `test_post_dispatch_tolerates_a_query_string`, `test_steward_post_urls_carry_no_query`,
  `test_steward_post_call_sites_send_token_header` — the transport + dispatch contracts.

Two long-standing failures were also repaired rather than left red:
`test_fetch_wrapper_present_*` asserted a `location.reload()` the product had
deliberately dropped (and its correction exposed fault **d**), and
`test_token_hygiene_lifecycle` died on a `log_change()` signature and a
`journal.Journal` class that have never existed — so **none** of its
secret-absence assertions had ever run. It now scans real logs and a real
journal for a real secret, mutation-checked.

---

## Follow-up (not done here, deliberately)

- **The auth-off blind spot is still mostly open.** This pass adds an auth-ON
  suite for the steward only. The other mutating surfaces remain covered
  exclusively auth-off. Recommend a standing auth-ON smoke pass over every
  mutating endpoint.
- **A GET/POST token-transport asymmetry** is pinned by test, not changed: a GET
  gates on `?token=` and rejects the `X-Anchor-Token` header; a POST does the
  reverse. The browser sends the right one on each, but it is a live trap for
  any new call site. Widening either side is an auth-surface decision.
