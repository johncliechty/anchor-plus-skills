# Auth warn-mode soak — the C2 data-plane flip (rearch W8)

The re-architecture moves the **gated data-plane batch** from unauthenticated
(`auth = open`) to token-required (`auth = token`) in **two deploys**, so nothing
breaks and every consumer is accounted for before enforcement:

1. **W8 — warn soak (this artifact).** The live service runs with
   `ANCHOR_AUTH_MODE=warn` (or the alias `ANCHOR_AUTH_WARN=1`). The batch is
   **still served** exactly as today, but every request that *would* have been
   `401`'d once enforcement is on (a token is configured and the request
   presented none or a wrong one) is appended to the **would-401 soak log** by
   `auth_warn.record_would_401`. A soak day of that log is reviewed here.
2. **W9 — enforce.** The batch's table rows flip `open → token`, their
   `OPEN_ROUTES.json` entries are deleted, and the mode flips to
   `ANCHOR_AUTH_MODE=enforce`. A tokenless request now gets a real `401`.

## The gated data-plane batch

Declared once in `route_table.DATA_PLANE_GATED` (so the server gate, the
healthcheck row-walk, and the reviewer never drift):

| method | route | why it is gated (carries per-project data) |
|---|---|---|
| GET | `/artifact/` | Serves discovered artifact file bytes (traversal-safe, but per-project). |
| GET | `/report/` | Read-only effort report viewer. |
| GET | `/summary/` | Cached per-session summary page. |
| GET | `/project/` | Full project-window page (sessions, efforts, chain). |
| GET | `/api/rnd/projects` | The project registry listing. |
| GET | `/api/rnd/tail` | Incremental job-log tail. |
| GET | `/api/rnd/jobs` | Recent job records for a project. |

These are exactly the routes tagged `W8/W9` in `OPEN_ROUTES.json`. Everything
else already sits at its final posture (`open` static/bootstrap, or `token` for
the already-gated read/mutate surface).

## Running the soak (on the live `:8777` service)

> Ops step — performed by John on `PUTER`; recorded via the amendment path,
> never silently. The mechanism ships in this wave; the day-long live capture is
> the ops action the merge checklist gates on.

1. Ensure `ANCHOR_TOKEN` is set for the service (warn mode only records a
   would-401 when a token is actually configured — otherwise auth is disabled and
   nothing is gated).
2. Set the NSSM `AppEnvironmentExtra` to include `ANCHOR_AUTH_MODE=warn`
   (equivalently `ANCHOR_AUTH_WARN=1`). This is the **named `c2-warn-soak`**
   hybrid state (`static · warn · off · inline`) — `check_pillar_state` passes it.
3. `nssm restart anchor` (elevated), then confirm the new build via `ANCHOR_BOOT`
   / `GET /api/version` (no stale supervisor — see `PROCESS-RAILS.md`).
4. Soak for **one day of normal use** (open the dashboard, project windows,
   reports, terminals — desktop and the iPhone PWA over Tailscale).
5. Review the soak log: `python -c "import auth_warn,json;
   print(json.dumps(auth_warn.summarize(), indent=2))"` (log path:
   `auth_warn.warn_log_path()`, default `<data-dir>/auth-warn.log`).

## Review acceptance rule (the gate)

The flip to `enforce` (W9) ships **only when**:

> Every would-401 entry maps to a **W2-enumerated consumer** (see
> `CONSUMER-INVENTORY.md`) that has a **token path** — i.e. an expected caller we
> know how to authenticate. Any *unexplained* would-401 (an entry whose route the
> inventory does not account for) **HOLDS the flip** until it is triaged.

`auth_warn.review_against_consumers(known_paths)` computes this verdict
mechanically: `{ok: True}` iff there are zero unexplained entries. `known_paths`
is the data-plane batch itself plus any additional consumer paths the inventory
blesses. An empty soak log (no tokenless data-plane traffic during the day) is a
**pass** — it means every live consumer already carries a token.

## Merge checklist — the auth-flip sequencing rule (honored)

Per `PROCESS-RAILS.md` (**Auth-flip sequencing rule**): an auth flip
**NEVER ships in the same deploy** as a JS change that calls the flipped routes, and rollback is
a **flag flip (`ANCHOR_AUTH_MODE`), never a code revert**. For this flip:

- [ ] **W8 deploy** ships the *mechanism only* — warn-mode overlay + soak
      logging. No route JS changes to how the data-plane routes are called. The
      table rows stay `open`; behavior is byte-identical except the soak log.
- [ ] Soak a day; review the log with `review_against_consumers` → `ok: True`.
- [ ] **W9 deploy (separate)** flips the table rows `open → token`, removes their
      `OPEN_ROUTES.json` entries, and sets `ANCHOR_AUTH_MODE=enforce` — carried by
      cookie-based browser navigation (the W3 spike verdict), deployed *after* any
      JS that would call the now-token routes is already live.
- [ ] Rollback path at every step: set `ANCHOR_AUTH_MODE=warn` (or unset it) and
      `nssm restart anchor` — a flag flip, never a code revert.

## Mechanism map (what W8 shipped)

- `pillar_flags` — `ANCHOR_AUTH_MODE` (`open|warn|enforce`) + the
  `ANCHOR_AUTH_WARN=1` alias; the `c2-warn-soak` named state.
- `route_table.DATA_PLANE_GATED` / `is_data_plane_gated` / `effective_auth` /
  `walk_expectations` — the one declared set + the derived per-mode posture.
- `auth_warn.py` — `record_would_401` (no secret logged; append-only under
  `WRITE_LOCK`), `read_entries` / `summarize` / `review_against_consumers`.
- `anchor_gui.AnchorHandler._data_plane_gate` — the do_GET overlay (open = no-op,
  warn = log-only, enforce = 401); `_auth_mode` / `_presented_token` helpers; the
  do_POST middleware now defers to the route-table auth policy (default-deny).
- `anchor_healthcheck.check_route_table_walk` — walks every declared row
  (skipping `kind = upgrade`) asserting per-policy auth behavior.
- The socket-level **401-before-101** regression test for `term_ws` proves the
  hand-rolled RFC-6455 ordering (auth rejection precedes any handshake bytes).
