# 2026-07-28 — High Seat: token re-prompt (saved) → reload → lost input

- **id**: `2026-07-28-08-high-seat-token-re-prompt-saved-then-rel`
- **surface**: Main Anchor dashboard · **High Seat** (Ecgberht portfolio steward tile)
- **situation**: Gave High Seat input → asked for Anchor token (already saved) → page reload → input gone. High Seat not usable yet.
- **severity**: problem (blocks product use of High Seat)
- **status**: Journaled for sleep — **do not ad-hoc patch**; John will separately look at **project-level steward**
- **provenance**: genuine-user-report + code inspection

---

## What John said (verbatim intent)

> Also, a bug with regards to the High Seat. I just tried to give it input and it came back with asking me for the Anchor token, which I gave it (actually it was still saved--that may be a problem). Then it restarted anchor and lost/forgot what I had given it. So, we are not able to use the High Seat yet. I will take a look at the project level steward.

---

## Failure chain (observed + code)

```text
User types High Seat input (speak)
        │
        ▼
POST /api/ecgberht/high_seat_act  (or related GET) → 401 unauthorized
        │
        ▼
Global window.fetch wrapper (anchor_gui)
  if 401 && ANCHOR_AUTH_REQUIRED → setAnchorToken()
        │
        ▼
prompt("Paste your Anchor access token:", cur)
  cur = localStorage.anchor_token   ← "it was still saved"
        │
        ▼
location.reload()                   ← feels like "restarted anchor"
        │
        ▼
High Seat remounts empty
  dialogue is ephemeral by design → typed text gone forever
```

### Why the saved token is still a problem
- `setAnchorToken` **pre-fills** the prompt with `localStorage` — so “still saved” is expected, not proof the request was authenticated.
- 401 can still fire if: token empty on that request path, wrong/stale token, query-only vs header mismatch, or race before token is attached.
- High Seat `_ecgHsPost` / `_ecgHsGet` use **`?token=`** only; the rest of the dashboard often uses **`X-Anchor-Token`**. Sleep should verify AUTH accepts both and that High Seat always sends a valid token.

### Why input is lost (by design today)
`static/high-seat.js` header:

> Dialogue is ephemeral: talk compiles to closed verbs + receipts, and nothing here persists panel truth locally.

Combined with **full-page reload on any 401**, mid-compose re-auth is guaranteed data loss.

### “Restarted anchor”
Most likely **browser `location.reload()`**, not NSSM service restart. Sleep should confirm (no service bounce in the same second). If a real service restart also occurs, that is a second bug.

---

## Out of scope (explicit)

| Item | Owner |
|------|--------|
| **Project-level steward** | John will inspect separately |
| Ecgberht engine git/version (`2026-07-27-02-…`) | Separate open friction |

---

## Success criteria

1. Valid saved token → High Seat **speak never** token-prompts.
2. Real 401 → re-auth **without** wiping saybox / pending act (draft restore or act retry; no mandatory full reload for this surface).
3. One complete speak → receipt path without page reload.
4. Honest diagnosis when token is present but request still 401 (do not re-show “success” prefilled token as if fixed).
5. Clarify page reload vs service restart in the fix write-up.

---

## Code seams

| Seam | Role |
|------|------|
| `static/high-seat.js` | speak / `_ecgHsPost` / ephemeral UI |
| `anchor_gui.py` `setAnchorToken` + global fetch 401→`location.reload()` | The wipe mechanism |
| `route_table.py` `AUTH_TOKEN` on `/api/ecgberht/high_seat*` | Why 401 fires |
| `handle_ecgberht_high_seat_act` | speak bridge |

---

## Cross-links

| Item | Link |
|------|------|
| Friction store | `friction/2026-07-28-08-high-seat-token-re-prompt-saved-then-rel.json` |
| Sleep intake 2026-07-28 | Defect 7 |
| Related | Ecgberht version control `2026-07-27-02-…` |
