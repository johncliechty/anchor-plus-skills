# Consumer-Enumeration Inventory — open-route consumers + verified token paths (W2)

Re-architecture 2026-07, **W2 — Regression Rails** (frozen plan:
`IMPLEMENTATION-PLAN.md` at the repo root). This is the reviewed inventory of
EVERY consumer of the currently-open routes (the data plane W8/W9 will gate:
`/artifact`, `/report`, `/summary`, `/project`, `/api/rnd/projects`,
`/api/rnd/tail`, `/api/rnd/jobs` — plus the open `GET /`, `/api/status`,
`/api/version`), each with its **verified token path**. The W8 warn-mode soak
reviews its would-401 log against THIS list; the W9 enforce flip does not ship
until every row here holds.

**Server acceptance (implemented in W2):** every token gate accepts, in order —
`?token=` (WS/SSE transports only need this), the standard `Authorization`
header (`Bearer <token>` or a bare token — `paths.token_from_authorization`),
`X-Anchor-Token` (browser JS), `Sec-WebSocket-Protocol` (WS smuggle), and the
JSON-body `token` field (POST). `?token=` is **retained only for WS/SSE**
(browsers cannot set headers on EventSource/WebSocket handshakes); every other
consumer has a header path.

| # | consumer | class | open routes it calls | token path (verified) |
|---|---|---|---|---|
| 1 | Home-dashboard browser JS (`generate_html`) | repo code / browser | `GET /`, `/api/status`, `/api/version`, `/api/rnd/projects*` reads, all `/api/*` POSTs | localStorage token → `X-Anchor-Token` on POSTs (`apiCall`), `?token=` on token-gated reads; 401 auto-reprompt (`setAnchorToken`); cookie navigation lands in W9 |
| 2 | Project-window browser JS (`_PROJECT_WINDOW_JS`) | repo code / browser | `/project/<id>`, `/summary`, `/report`, `/artifact`, `/api/rnd/*` reads + POSTs, WS/SSE terminals | localStorage token → `X-Anchor-Token` (`_postJson`), `?token=` (`_tokenQ`) on reads and — permanently — on `term_ws`/`term_stream2` (WS/SSE) |
| 3 | Zombie-hunter terminal page (Swarm & Owner View) | repo code / browser | `/api/rnd/zombie_*` POSTs, `term_ws`/`term_input2`/`term_resize` | `X-Anchor-Token` + body `token` on POSTs; `?token=` on the WS transport |
| 4 | `anchor_healthcheck.py` endpoint walk (+ 5 AM scheduled task "Anchor Health Check") | repo code / scheduled task | `GET /`, `GET /api/status`, POST validation pings, v2–v5 surface walks (module-level, not HTTP) | **`Authorization: Bearer` — switched in W2** (`_post`); the deliberately-tokenless 401 probe stays tokenless by design |
| 5 | `fix_anchor_stale.ps1` (John's elevated fix script) | personal script | `GET /api/rnd/tail` (gated batch!), `GET /` | **`Authorization: Bearer $env:ANCHOR_TOKEN` — added in W2**; headerless when the env var is unset (local back-compat) |
| 6 | `setup_service_as_john.ps1` | personal script | `GET /api/status` | `/api/status` is NOT in the gated data-plane batch (stays open per D3's reviewed allowlist, pending W7 OPEN_ROUTES); no token needed |
| 7 | `enable_remote.ps1` | personal script | none (port-listener checks only; prints URLs) | n/a — no HTTP request |
| 8 | Launchers: `AnchorDashboard.vbs`/`.bat`, `Anchor Dashboard.bat`, `launch_anchor.pyw`, `pin_anchor_to_taskbar.vbs`, `create_shortcut.py` | launchers | none — they only OPEN THE BROWSER on `http://localhost:8777` (post-2026-06-08 discipline: launchers never spawn servers, never fetch) | n/a — the opened browser client is row 1/2 |
| 9 | Scheduled task "Anchor Server" | scheduled task | none — **Disabled** (verified 2026-06-08; the rogue NSSM `Anchor-Server` service was removed) | n/a |
| 10 | `anchor.py` CLI (incl. every `rnd` mirror) | repo code | none — reads/writes via direct module imports, never HTTP | n/a |
| 11 | `preview_server.py` / `deliverables.py` launch probes | repo code | none on :8777 — they health-check their OWN spawned child preview on an OS-assigned port (hard-guarded ≠ 8777) with an isolated temp data dir (child auth off) | n/a for :8777 |
| 12 | iPhone/iPad PWA over Tailscale HTTPS | browser (remote) | same as rows 1–2 | same localStorage token paths; the W2 contract shim protects the PWA-cached stale client (structured 409 → reload banner); cookie navigation + WS verdict land in W3/W9 |

## Notes

- **Rows 4 and 5 are the two consumers that would have silently broken at the
  W9 enforce flip** (they hit gated routes with no header path before W2).
  Both now present `Authorization: Bearer` — the healthcheck proves its path
  on every nightly run; the fix script honors `$env:ANCHOR_TOKEN`.
- **`?token=` survives only on WS/SSE** (`term_ws`, `term_stream2`,
  `term_stream`, and the browser's read-GET `_tokenQ()` senders until the W9
  cookie cutover). No NEW `?token=` consumer may be added; W9 removes URL
  tokens everywhere the spike verdict allows.
- Gate coverage: `tests/test_rearch_2026_07.py::TestW2AuthorizationHeader`
  (server accepts the header on representative POST/GET/SSE routes) and
  `::TestW2ConsumerInventory` (this artifact enumerates every class above and
  the claimed W2 changes are really in the consumers' source).
