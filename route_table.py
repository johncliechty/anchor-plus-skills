"""Declarative HTTP route table — the C2 strangler substrate (rearch-2026-07 W7).

The single source of truth for EVERY HTTP route Anchor serves. Each route is a
declarative ROW carrying its method, URL pattern, match kind (exact | prefix),
auth policy, handler kind (standard | stream | upgrade), the module-level handler
it has been migrated to (or ``None`` while still legacy), and a ``migrated`` flag.

Why this exists (Master Plan Phase 2; D3; Success criterion 2):
  * **Default-deny by construction.** Auth is a declared property of the row, not
    a scattered inline check. ``token`` is the intended default; the only routes
    that are unauthenticated live on an explicit, reviewed allowlist —
    ``OPEN_ROUTES.json`` — and a gate test asserts the table's ``open`` set equals
    that file EXACTLY (adding an ``open`` route fails the build until the reviewed
    file is edited with a justification string).
  * **Strangler migration.** ``anchor_gui`` dispatches the table FIRST; a matched,
    ``migrated`` row is handled by its module-level function (with the row's auth
    invoked FIRST — honestly special-cased for ``kind != standard``); anything
    unmatched or not-yet-migrated falls through to the legacy ``if``/``elif``
    chains unchanged. C2 progress is therefore a measurable count
    (:func:`legacy_arm_count`), not a narrative.
  * **Auditable.** ``/api/routes`` (token-authed) dumps the live table, and a
    route-audit test proves no dispatch arm exists in ``anchor_gui`` without a
    declared row here.

This module is PURE DATA + PURE FUNCTIONS — stdlib only, no imports of the server.
The migrated handler *functions* live in ``anchor_gui`` (where their dependencies
live) and are looked up by the string name in :attr:`Route.handler`; keeping this
table import-free means the audit/coverage tests can import it with zero side
effects.
"""

from __future__ import annotations

from collections import namedtuple

# ── Auth policies ────────────────────────────────────────────────────────────
# The declared auth posture of a route. ``token`` is default-deny (a valid
# shared-secret token is required when ANCHOR_TOKEN is configured); ``open`` is
# the explicitly-reviewed unauthenticated allowlist (OPEN_ROUTES.json); ``ws_token``
# is the query-param/subprotocol token the WS/SSE transports demand (browsers
# cannot set headers on an EventSource/WebSocket handshake).
AUTH_TOKEN = "token"
AUTH_OPEN = "open"
AUTH_WS_TOKEN = "ws_token"

AUTH_POLICIES = (AUTH_TOKEN, AUTH_OPEN, AUTH_WS_TOKEN)

# ── Handler kinds ────────────────────────────────────────────────────────────
# ``standard`` is a normal request/response arm. ``stream`` holds the socket open
# for a chunked SSE body; ``upgrade`` hijacks the raw socket for a WebSocket. The
# specials are honestly special-cased at the pre-dispatch hook (the row's auth is
# invoked FIRST, then the transport takes over the socket).
KIND_STANDARD = "standard"
KIND_STREAM = "stream"
KIND_UPGRADE = "upgrade"

HANDLER_KINDS = (KIND_STANDARD, KIND_STREAM, KIND_UPGRADE)

# ── Match kinds ──────────────────────────────────────────────────────────────
MATCH_EXACT = "exact"
MATCH_PREFIX = "prefix"

# ── The gated data-plane batch (W8 warn / W9 enforce) ────────────────────────
# These routes are currently ``auth == open`` (they served tokenless pre-rearch)
# but carry per-project data. The warn-then-enforce soak moves them ``open`` →
# ``token``: W8 runs them in log-only WARN mode (``auth_warn.record_would_401``
# for a tokenless request; still served), W9 flips the table rows to ``token``
# and the mode to ``enforce`` (a real 401). Declared here ONCE so the server's
# runtime gate, the healthcheck row-walk, and the soak reviewer share one exact
# set — matched by the row PATTERN (``match(method, path).pattern``).
DATA_PLANE_GATED = (
    ("GET", "/artifact/"),
    ("GET", "/report/"),
    ("GET", "/summary/"),
    ("GET", "/project/"),
    ("GET", "/api/rnd/projects"),
    ("GET", "/api/rnd/tail"),
    ("GET", "/api/rnd/jobs"),
)


def is_data_plane_gated(route) -> bool:
    """True iff ``route`` is a member of the W8/W9 gated data-plane batch.

    ``route`` is a :class:`Route` (typically :func:`match`'s return). ``None``
    (an unmatched path) is never gated here — default-deny for undeclared paths
    is the audit's job, not this soak overlay's.
    """
    if route is None:
        return False
    return (route.method, route.pattern) in DATA_PLANE_GATED

# The known non-literal (constant-valued) prefix arms in anchor_gui.do_GET. These
# static-asset routes are dispatched via ``self.path.startswith(<CONST>)`` rather
# than a string literal, so the route-audit's literal extractor cannot see them —
# they are declared here explicitly and this set documents that they are audited
# by identity, not by literal scan.
STATIC_ASSET_PREFIXES = (
    "/vendor/katex",
    "/vendor/xterm",
    "/vendor/brand",
    "/vendor/anchor-term",
    "/static",
)


Route = namedtuple(
    "Route", "method pattern match auth kind handler migrated")


def _r(method, pattern, auth, kind=KIND_STANDARD, match=MATCH_EXACT,
       handler=None, migrated=False):
    assert auth in AUTH_POLICIES, f"bad auth policy {auth!r}"
    assert kind in HANDLER_KINDS, f"bad handler kind {kind!r}"
    assert match in (MATCH_EXACT, MATCH_PREFIX), f"bad match kind {match!r}"
    if migrated:
        assert handler, f"migrated route {pattern!r} needs a handler name"
    return Route(method.upper(), pattern, match, auth, kind, handler, migrated)


# ── The route table ──────────────────────────────────────────────────────────
# Every route Anchor serves gets a ROW. Auth policy reflects the CURRENT live
# behavior (W7 declares reality without flipping it; W8/W9 move data-plane rows
# from ``open`` → ``token`` under warn-then-enforce, editing OPEN_ROUTES.json as
# they go — exactly the reviewed-allowlist workflow the gate enforces).
ROUTES = [
    # ── GET: pages + public bootstrap (open) ──────────────────────────────
    _r("GET", "/", AUTH_OPEN),
    _r("GET", "/dashboard", AUTH_OPEN),
    _r("GET", "/api/version", AUTH_OPEN, handler="handle_version",
       migrated=True),
    _r("GET", "/api/status", AUTH_OPEN, handler="handle_status",
       migrated=True),
    _r("GET", "/favicon.ico", AUTH_OPEN),
    _r("GET", "/anchor.ico", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/anchor.png", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/anchor-touch.png", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/zombie_radar.jpg", AUTH_OPEN, match=MATCH_PREFIX),
    # Static-asset roots (constant-prefix arms in do_GET).
    _r("GET", "/vendor/katex", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/vendor/xterm", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/vendor/brand", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/vendor/anchor-term", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/static", AUTH_OPEN, match=MATCH_PREFIX),

    # ── GET: the live route-table dump (NEW, token-authed) ─────────────────
    _r("GET", "/api/routes", AUTH_TOKEN, handler="handle_routes",
       migrated=True),

    # ── GET: streaming / upgrade specials (ws_token) ───────────────────────
    _r("GET", "/api/rnd/term_ws", AUTH_WS_TOKEN, kind=KIND_UPGRADE),
    _r("GET", "/api/rnd/term_stream2", AUTH_WS_TOKEN, kind=KIND_STREAM),
    _r("GET", "/api/rnd/term_stream", AUTH_WS_TOKEN, kind=KIND_STREAM,
       match=MATCH_PREFIX),

    # ── GET: currently-open data plane (scheduled for W8/W9 token-gating) ──
    _r("GET", "/report/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/summary/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/artifact/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/project/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/handoff_proposal", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_handoff_proposal", migrated=True),
    _r("GET", "/api/rnd/session_summary", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_session_summary", migrated=True),
    _r("GET", "/api/rnd/term_sessions", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_term_sessions", migrated=True),
    _r("GET", "/api/rnd/projects_html", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_projects_html", migrated=True),
    _r("GET", "/api/rnd/projects", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/dir_browse", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_dir_browse", migrated=True),
    _r("GET", "/api/rnd/tail", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/jobs", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/previews", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_previews", migrated=True),

    # ── GET: already token-gated read surface ──────────────────────────────
    _r("GET", "/zombie_terminal", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_zombie_terminal", migrated=True),
    _r("GET", "/api/rnd/project_files", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_project_files", migrated=True),
    _r("GET", "/api/rnd/project_file_content", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_project_file_content", migrated=True),
    _r("GET", "/api/rnd/session_doc_roles", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_session_doc_roles", migrated=True),
    # telemetry-resume W3 — Layer-1 warm narration data (token-authed, ?token=).
    # A NEW read endpoint carrying per-project data → default-deny token, and it
    # is enumerated in the W3 auth test (401-before-substance).
    _r("GET", "/api/rnd/session_narration", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_session_narration", migrated=True),
    # telemetry-resume W4 — ledger/capture inspection (token-authed, ?token=).
    # A NEW read endpoint carrying per-session usage data → default-deny token, and
    # it is enumerated in the auth test (401-before-substance).
    _r("GET", "/api/rnd/usage_ledger", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_usage_ledger", migrated=True),
    _r("GET", "/api/rnd/context_status", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_context_status", migrated=True),
    _r("GET", "/api/rnd/effort_rollup", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_effort_rollup", migrated=True),
    _r("GET", "/api/rnd/build_deliverable", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_build_deliverable", migrated=True),
    _r("GET", "/api/rnd/grass", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_grass", migrated=True),
    # Friction journaling (2026-07-26): tell Anchor something hurt, and read the
    # accumulated records that feed the sleep-cycle intake brief.
    _r("GET", "/api/rnd/friction", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_friction_list", migrated=True),
    _r("POST", "/api/rnd/journal_friction", AUTH_TOKEN,
       handler="handle_journal_friction", migrated=True),
    _r("GET", "/api/rnd/gandalf", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_gandalf", migrated=True),
    _r("GET", "/api/rnd/gandalf_status", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_gandalf_status", migrated=True),
    _r("GET", "/api/rnd/gandalf_status_all", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_gandalf_status_all", migrated=True),
    _r("GET", "/api/rnd/orphan_check", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_orphan_check", migrated=True),
    _r("GET", "/api/rnd/zombie_spenders", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_zombie_spenders", migrated=True),
    _r("GET", "/api/rnd/zombie_hunter_report", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_zombie_hunter_report", migrated=True),
    # Same-origin reverse proxy to ZH Node radar (Tailscale / remote safe)
    _r("GET", "/api/rnd/zombie_hunter_proxy", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_zombie_hunter_proxy", migrated=True),
    _r("POST", "/api/rnd/zombie_hunter_proxy", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_zombie_hunter_proxy", migrated=True),
    # Reaper control plane (token-authed; safe-to-arm build) — status read + the
    # arm/advance/disarm mutations. Sensitive control surface: token, never open.
    _r("GET", "/api/rnd/reaper_status", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_reaper_status", migrated=True),
    _r("POST", "/api/rnd/reaper_arm", AUTH_TOKEN,
       handler="handle_reaper_arm", migrated=True),
    _r("POST", "/api/rnd/reaper_advance", AUTH_TOKEN,
       handler="handle_reaper_advance", migrated=True),
    _r("POST", "/api/rnd/reaper_disarm", AUTH_TOKEN,
       handler="handle_reaper_disarm", migrated=True),
    _r("GET", "/api/rnd/boneyard", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_boneyard", migrated=True),
    # ── Ecgberht Seal chamber (TW5 — wireframes v2.1 Screen 1) ────────────
    # UI host: live C:\dev\Anchor (hardened line). Engine: C:\dev\Ecgberht.
    _r("GET", "/api/ecgberht/chamber", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_chamber", migrated=True),
    # (steward-chamber W6) Deterministic-first painted M1 slice: zero-spawn /
    # zero-model read over the W4/W5 sidecar projections (chamber_open).
    _r("GET", "/api/ecgberht/seal_open", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_seal_open", migrated=True),
    # (steward-chamber W9) STATUS overlay as drawn: latest ⏱ table + remaining
    # steps with n>=3 median ETAs — the same zero-spawn/zero-model bounded read
    # as seal_open, rendered via chamber_status_overlay.
    _r("GET", "/api/ecgberht/status_overlay", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_status_overlay", migrated=True),
    # (steward-chamber W9) The injection-clock deliverable read (SAFE
    # projection; argv/cwd never serialize) …
    _r("GET", "/api/ecgberht/deliverable_state", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_deliverable_state", migrated=True),
    # … and the ONE deliverable-action mutator (F3: shell:false, list-argv from
    # the code-owned verb allow-list, contained path, pinned cwd; labeled inert
    # otherwise). Row + red-to-green proof in chamber/routes-inventory.json.
    _r("POST", "/api/ecgberht/deliverable_action", AUTH_TOKEN,
       handler="handle_ecgberht_deliverable_action", migrated=True),
    # (steward-chamber W10) The serialized decision-gate queue (E5): the
    # read-only head-only queue state + render …
    _r("GET", "/api/ecgberht/gate_queue", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_gate_queue", migrated=True),
    # … and its three mutators — resolve/skip the HEAD gate (serialization
    # law: a non-head gate refuses by name) and the sweep-card binding that
    # releases the E2 enqueue gate (C5/F4). Rows + red-to-green proof in
    # chamber/routes-inventory.json (tests/test_chamber_gate_routes_w10.py).
    _r("POST", "/api/ecgberht/gate_resolve", AUTH_TOKEN,
       handler="handle_ecgberht_gate_resolve", migrated=True),
    _r("POST", "/api/ecgberht/gate_skip", AUTH_TOKEN,
       handler="handle_ecgberht_gate_skip", migrated=True),
    _r("POST", "/api/ecgberht/sweep_bind", AUTH_TOKEN,
       handler="handle_ecgberht_sweep_bind", migrated=True),
    # (steward-chamber W11) The REFINE-THE-PLAN overlay: the read-only
    # draft/sections/overlay-html state …
    _r("GET", "/api/ecgberht/refine_state", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_refine_state", migrated=True),
    # … its ONE plan-writing mutator — the SECTION-SCOPED HASH-BOUND confirm
    # (writes only on a matching section hash; a moved section answers the
    # drawn 'plan moved' card WITH diff, draft preserved) — and the E7
    # mid-flight re-brief write (live channel, acknowledgment receipt on the
    # step, NO relaunch; refused-and-queued during an active sweep). Rows +
    # red-to-green proof in chamber/routes-inventory.json
    # (tests/test_chamber_refine_routes_w11.py).
    _r("POST", "/api/ecgberht/refine_confirm", AUTH_TOKEN,
       handler="handle_ecgberht_refine_confirm", migrated=True),
    _r("POST", "/api/ecgberht/rebrief", AUTH_TOKEN,
       handler="handle_ecgberht_rebrief", migrated=True),
    _r("POST", "/api/ecgberht/speak", AUTH_TOKEN,
       handler="handle_ecgberht_speak", migrated=True),
    # TW7 Screen 4 — stand-up confirm ONLY path (empty project → Face+Strip)
    _r("POST", "/api/ecgberht/stand_up", AUTH_TOKEN,
       handler="handle_ecgberht_stand_up", migrated=True),
    # Hardening 2026-08-04 — join active projects to the portfolio index. The
    # ONLY path that mints a project marker, and therefore the only way the High
    # Seat can ever have rows. A POST because registering WRITES a marker into
    # each project root, and the portfolio altitude folds projections read-only.
    _r("POST", "/api/ecgberht/register_projects", AUTH_TOKEN,
       handler="handle_ecgberht_register_projects", migrated=True),
    # 2026-08-04 — the missing SC1 path. A dictated project description compiles
    # to a PROPOSED scaffolding (preview writes nothing) and, on an explicit
    # confirm, becomes roadmap steps through the single writer.
    _r("POST", "/api/ecgberht/scaffold_preview", AUTH_TOKEN,
       handler="handle_ecgberht_scaffold_preview", migrated=True),
    _r("POST", "/api/ecgberht/scaffold_confirm", AUTH_TOKEN,
       handler="handle_ecgberht_scaffold_confirm", migrated=True),
    # 2026-08-04 — THE CONVERSATIONAL DOOR. Free-form speech goes to the steward's
    # seat model (with the Face, roadmap and Strip as context) instead of dead-ending
    # on the closed act table; control verbs still compile deterministically in the
    # engine. envelope_confirm is the one human "yes, spend on this session" that
    # covers the whole conversation, so the steward never asks per sentence.
    _r("POST", "/api/ecgberht/converse", AUTH_TOKEN,
       handler="handle_ecgberht_converse", migrated=True),
    _r("POST", "/api/ecgberht/envelope_confirm", AUTH_TOKEN,
       handler="handle_ecgberht_envelope_confirm", migrated=True),
    _r("POST", "/api/ecgberht/envelope_raise", AUTH_TOKEN,
       handler="handle_ecgberht_envelope_raise", migrated=True),
    # (2026-08-06) steward run-loop W5: the steward actually RUNS a skill.
    _r("POST", "/api/ecgberht/commission_propose", AUTH_TOKEN,
       handler="handle_ecgberht_commission_propose", migrated=True),
    _r("POST", "/api/ecgberht/commission_go", AUTH_TOKEN,
       handler="handle_ecgberht_commission_go", migrated=True),
    _r("POST", "/api/ecgberht/commission_watch", AUTH_TOKEN,
       handler="handle_ecgberht_commission_watch", migrated=True),
    _r("GET", "/api/ecgberht/commission_runs", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_commission_runs", migrated=True),
    _r("GET", "/api/ecgberht/step_detail", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_step_detail", migrated=True),
    _r("POST", "/api/ecgberht/step_note", AUTH_TOKEN,
       handler="handle_ecgberht_step_note", migrated=True),
    _r("GET", "/api/ecgberht/run_pulse", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_run_pulse", migrated=True),
    _r("POST", "/api/ecgberht/high_seat_say", AUTH_TOKEN,
       handler="handle_ecgberht_high_seat_say", migrated=True),
    # ── Ecgberht High Seat (TW6 — wireframes v2.1 Screens 0+2+3) ──────────
    # Same live-Anchor host + Ecgberht engine bridge (high-seat-bridge.mjs).
    # Specific prefixes are registered BEFORE the bare /high_seat prefix so
    # prefix dispatch never swallows _badge into the view-model handler.
    _r("GET", "/api/ecgberht/high_seat_badge", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_high_seat_badge", migrated=True),
    _r("POST", "/api/ecgberht/high_seat_act", AUTH_TOKEN,
       handler="handle_ecgberht_high_seat_act", migrated=True),
    _r("GET", "/api/ecgberht/high_seat", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_high_seat", migrated=True),
    _r("GET", "/api/ecgberht/bring_up", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_bring_up", migrated=True),
    _r("GET", "/api/ecgberht/artifact", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_artifact", migrated=True),
    # ── Ecgberht Chamber UI (Wave 18 — steps, proposals, artifacts, corrections)
    # Token-auth only (OPEN_ROUTES review: none of these are open). Bridge:
    # Ecgberht scripts/chamber-ui-bridge.mjs. Specific prefixes before generics.
    _r("GET", "/api/ecgberht/chamber_steps", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_chamber_steps", migrated=True),
    _r("GET", "/api/ecgberht/chamber_proposal", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_chamber_proposal", migrated=True),
    _r("POST", "/api/ecgberht/chamber_confirm", AUTH_TOKEN,
       handler="handle_ecgberht_chamber_confirm", migrated=True),
    _r("GET", "/api/ecgberht/chamber_artifact", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_ecgberht_chamber_artifact", migrated=True),
    _r("POST", "/api/ecgberht/chamber_correct", AUTH_TOKEN,
       handler="handle_ecgberht_chamber_correct", migrated=True),
    _r("GET", "/api/rnd/remote_status", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_remote_status", migrated=True),
    _r("GET", "/api/rnd/project_rollup", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_project_rollup", migrated=True),
    _r("GET", "/api/rnd/chain", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_chain", migrated=True),
    _r("GET", "/api/rnd/board_html", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_board_html", migrated=True),

    # ── Model/engine prefs (durable settings.json) ────────────────────────
    _r("GET",  "/api/settings", AUTH_TOKEN, handler="handle_settings_get",  migrated=True),
    _r("POST", "/api/settings", AUTH_TOKEN, handler="handle_settings_post", migrated=True),

    # ── doctor V3 W3 — the /doctor page + background diagnostics ──────────
    # The page itself is an open bootstrap (same posture as "/" — browser
    # navigation must load before any token is presented; every mutating /
    # data call it makes is token-gated below). Served by the legacy do_GET
    # arm (a whole-page render, like "/dashboard").
    _r("GET", "/doctor", AUTH_OPEN),
    # Real stat cards / reports-list refresh data (read, per-install health
    # data → default-deny token; ?token= / Authorization / cookie accepted).
    _r("GET", "/api/doctor/status", AUTH_TOKEN,
       handler="handle_doctor_status", migrated=True),
    # One health report rendered read-only (name-validated, traversal-safe
    # inside health_reports/).
    _r("GET", "/doctor/report", AUTH_TOKEN,
       handler="handle_doctor_report", migrated=True),
    # Cursor-stable incremental tail of the BACKGROUND anchor_healthcheck.py
    # run (the /api/rnd/tail pattern; never a synchronous request-thread run).
    _r("GET", "/api/doctor/healthcheck_tail", AUTH_TOKEN,
       handler="handle_doctor_healthcheck_tail", migrated=True),
    # Launch the background diagnostics run (mutating → default-deny token;
    # idempotent: a second POST while one is live attaches, never stacks).
    _r("POST", "/api/doctor/healthcheck_run", AUTH_TOKEN,
       handler="handle_doctor_healthcheck_run", migrated=True),

    # ── POST: browser auth-cookie login/logout (rearch W9, migrated) ──────
    # Mint / clear the HttpOnly auth cookie that carries browser page
    # navigation under ``ANCHOR_AUTH_MODE=enforce`` (SPIKE-COOKIE-WS-VERDICT).
    # Token-authed by the do_POST middleware (default-deny) BEFORE the handler
    # runs, so the login handler only ever sets a cookie for a validated caller.
    _r("POST", "/api/auth/login", AUTH_TOKEN, handler="handle_auth_login",
       migrated=True),
    _r("POST", "/api/auth/logout", AUTH_TOKEN, handler="handle_auth_logout",
       migrated=True),

    # ── POST: every mutating arm (token; do_POST middleware enforces) ──────
    _r("POST", "/api/done", AUTH_TOKEN, handler="handle_done", migrated=True),
    _r("POST", "/api/rnd/upload_batch", AUTH_TOKEN,
       handler="handle_upload_batch", migrated=True),
    _r("POST", "/api/upload", AUTH_TOKEN,
       handler="handle_upload", migrated=True),
    _r("POST", "/api/undone", AUTH_TOKEN, handler="handle_undone",
       migrated=True),
    _r("POST", "/api/add", AUTH_TOKEN, handler="handle_add", migrated=True),
    _r("POST", "/api/capture", AUTH_TOKEN, handler="handle_capture",
       migrated=True),
    _r("POST", "/api/edit_task", AUTH_TOKEN, handler="handle_edit_task",
       migrated=True),
    _r("POST", "/api/edit_project", AUTH_TOKEN, handler="handle_edit_project",
       migrated=True),
    _r("POST", "/api/promote_project", AUTH_TOKEN,
       handler="handle_promote_project", migrated=True),
    _r("POST", "/api/demote_project", AUTH_TOKEN,
       handler="handle_demote_project", migrated=True),
    _r("POST", "/api/promote_task", AUTH_TOKEN, handler="handle_promote_task",
       migrated=True),
    _r("POST", "/api/demote_task", AUTH_TOKEN, handler="handle_demote_task",
       migrated=True),
    _r("POST", "/api/cancel", AUTH_TOKEN, handler="handle_cancel",
       migrated=True),
    _r("POST", "/api/save_for_later", AUTH_TOKEN,
       handler="handle_save_for_later", migrated=True),
    _r("POST", "/api/restore", AUTH_TOKEN,
       handler="handle_restore", migrated=True),
    _r("POST", "/api/heartbeat", AUTH_TOKEN,
       handler="handle_heartbeat", migrated=True),
    _r("POST", "/api/rnd/new_project", AUTH_TOKEN,
       handler="handle_new_project", migrated=True),
    _r("POST", "/api/rnd/open_project", AUTH_TOKEN,
       handler="handle_open_project", migrated=True),
    _r("POST", "/api/rnd/rescan", AUTH_TOKEN,
       handler="handle_rescan", migrated=True),
    _r("POST", "/api/rnd/set_priority", AUTH_TOKEN,
       handler="handle_set_priority", migrated=True),
    _r("POST", "/api/rnd/archive_project", AUTH_TOKEN,
       handler="handle_archive_project", migrated=True),
    _r("POST", "/api/rnd/future_project", AUTH_TOKEN,
       handler="handle_future_project", migrated=True),
    _r("POST", "/api/rnd/retire_project", AUTH_TOKEN,
       handler="handle_retire_project", migrated=True),
    _r("POST", "/api/rnd/reactivate_project", AUTH_TOKEN,
       handler="handle_reactivate_project", migrated=True),
    _r("POST", "/api/rnd/set_notes", AUTH_TOKEN,
       handler="handle_set_notes", migrated=True),
    _r("POST", "/api/rnd/set_blurb", AUTH_TOKEN,
       handler="handle_set_blurb", migrated=True),
    _r("POST", "/api/rnd/set_group", AUTH_TOKEN,
       handler="handle_set_group", migrated=True),
    _r("POST", "/api/rnd/move_project", AUTH_TOKEN,
       handler="handle_move_project", migrated=True),
    _r("POST", "/api/rnd/link_task", AUTH_TOKEN,
       handler="handle_link_task", migrated=True),
    _r("POST", "/api/rnd/run_deliverable", AUTH_TOKEN,
       handler="handle_run_deliverable", migrated=True),
    _r("POST", "/api/rnd/pin_deliverable", AUTH_TOKEN,
       handler="handle_pin_deliverable", migrated=True),
    _r("POST", "/api/rnd/launch_deliverable", AUTH_TOKEN,
       handler="handle_launch_deliverable", migrated=True),
    _r("POST", "/api/rnd/launch_lane", AUTH_TOKEN,
       handler="handle_launch_lane", migrated=True),
    _r("POST", "/api/rnd/answer_gate", AUTH_TOKEN,
       handler="handle_answer_gate", migrated=True),
    _r("POST", "/api/rnd/start_terminal", AUTH_TOKEN,
       handler="handle_start_terminal", migrated=True),
    _r("POST", "/api/rnd/term_input", AUTH_TOKEN,
       handler="handle_term_input", migrated=True),
    _r("POST", "/api/rnd/term_discover", AUTH_TOKEN,
       handler="handle_term_discover", migrated=True),
    _r("POST", "/api/rnd/term_adopt", AUTH_TOKEN,
       handler="handle_term_adopt", migrated=True),
    _r("POST", "/api/rnd/cancel_job", AUTH_TOKEN,
       handler="handle_cancel_job", migrated=True),
    _r("POST", "/api/rnd/zombie_kill", AUTH_TOKEN,
       handler="handle_zombie_kill", migrated=True),
    _r("POST", "/api/rnd/zombie_resume", AUTH_TOKEN,
       handler="handle_zombie_resume", migrated=True),
    _r("POST", "/api/rnd/gandalf_cancel", AUTH_TOKEN,
       handler="handle_gandalf_cancel", migrated=True),
    _r("POST", "/api/rnd/preview_start", AUTH_TOKEN,
       handler="handle_preview_start", migrated=True),
    _r("POST", "/api/rnd/preview_stop", AUTH_TOKEN,
       handler="handle_preview_stop", migrated=True),
    _r("POST", "/api/rnd/term_start", AUTH_TOKEN,
       handler="handle_term_start", migrated=True),
    _r("POST", "/api/rnd/zombie_terminal_start", AUTH_TOKEN,
       handler="handle_zombie_terminal_start", migrated=True),
    # W8/SC5+SC6 — engine toggle health for Investigate/Doctor shell-first start
    _r("GET", "/api/zh/engines", AUTH_TOKEN,
       handler="handle_zh_engines", migrated=True),
    # doctor V3 W2 — start/attach THE /doctor agentic session (spawns a PTY on
    # an engine subscription CLI → mutating, default-deny token; enumerated in
    # the doctor gate's 401-before-substance test).
    _r("POST", "/api/doctor/session_start", AUTH_TOKEN,
       handler="handle_doctor_session_start", migrated=True),
    # W9 / SC7 — health + reaper-health banner → Doctor 1:1 seed (+ async diagnose contract)
    _r("GET", "/api/doctor/banner_seed", AUTH_TOKEN,
       handler="handle_doctor_banner_seed", migrated=True),
    _r("POST", "/api/doctor/banner_seed", AUTH_TOKEN,
       handler="handle_doctor_banner_seed", migrated=True),
    _r("POST", "/api/rnd/term_kill", AUTH_TOKEN,
       handler="handle_term_kill", migrated=True),
    _r("POST", "/api/rnd/term_close", AUTH_TOKEN,
       handler="handle_term_close", migrated=True),
    _r("POST", "/api/rnd/term_delete", AUTH_TOKEN,
       handler="handle_term_delete", migrated=True),
    _r("POST", "/api/rnd/cleanup_ghost_sessions", AUTH_TOKEN,
       handler="handle_cleanup_ghost_sessions", migrated=True),
    _r("POST", "/api/rnd/term_set_engine", AUTH_TOKEN,
       handler="handle_term_set_engine", migrated=True),
    _r("POST", "/api/rnd/switch_terminal_engine", AUTH_TOKEN,
       handler="handle_switch_terminal_engine", migrated=True),
    _r("POST", "/api/rnd/term_resize", AUTH_TOKEN,
       handler="handle_term_resize", migrated=True),
    _r("POST", "/api/rnd/term_input2", AUTH_TOKEN,
       handler="handle_term_input2", migrated=True),
    _r("POST", "/api/rnd/regenerate_summary", AUTH_TOKEN,
       handler="handle_regenerate_summary", migrated=True),
    _r("POST", "/api/rnd/add_idea", AUTH_TOKEN,
       handler="handle_add_idea", migrated=True),
    _r("POST", "/api/rnd/promote_inbox", AUTH_TOKEN,
       handler="handle_promote_inbox", migrated=True),
    _r("POST", "/api/rnd/promote_grass", AUTH_TOKEN,
       handler="handle_promote_grass", migrated=True),
    _r("POST", "/api/rnd/grass_develop", AUTH_TOKEN,
       handler="handle_grass_develop", migrated=True),
    _r("POST", "/api/rnd/grass_workbench", AUTH_TOKEN,
       handler="handle_grass_workbench", migrated=True),
    _r("POST", "/api/rnd/grass_save_refinement", AUTH_TOKEN,
       handler="handle_grass_save_refinement", migrated=True),
    _r("POST", "/api/rnd/grass_set_status", AUTH_TOKEN,
       handler="handle_grass_set_status", migrated=True),
    _r("POST", "/api/rnd/grass_pull", AUTH_TOKEN,
       handler="handle_grass_pull", migrated=True),
    _r("POST", "/api/rnd/grass_export", AUTH_TOKEN,
       handler="handle_grass_export", migrated=True),
    _r("POST", "/api/rnd/grass_archive", AUTH_TOKEN,
       handler="handle_grass_archive", migrated=True),
    _r("POST", "/api/rnd/grass_advance", AUTH_TOKEN,
       handler="handle_grass_advance", migrated=True),
    _r("POST", "/api/rnd/grass_delete", AUTH_TOKEN,
       handler="handle_grass_delete", migrated=True),
    _r("POST", "/api/rnd/link_github", AUTH_TOKEN,
       handler="handle_link_github", migrated=True),
    _r("POST", "/api/rnd/set_auto_push", AUTH_TOKEN,
       handler="handle_set_auto_push", migrated=True),
    _r("POST", "/api/rnd/push_now", AUTH_TOKEN,
       handler="handle_push_now", migrated=True),
    _r("POST", "/api/rnd/continue_session", AUTH_TOKEN,
       handler="handle_continue_session", migrated=True),
    # telemetry-resume W6 — Layer-2 '▶ Resume live' escalation (routed by tile
    # class server-side) + the read-only plan-mode orientation one-shot trigger.
    # Both mutate (spawn a session / launch a job) → default-deny token; the
    # orientation trigger is enumerated in the auth-enumeration test.
    _r("POST", "/api/rnd/resume_live", AUTH_TOKEN,
       handler="handle_resume_live", migrated=True),
    _r("POST", "/api/rnd/orient_session", AUTH_TOKEN,
       handler="handle_orient_session", migrated=True),
    _r("POST", "/api/rnd/advance_session", AUTH_TOKEN,
       handler="handle_advance_session", migrated=True),
    _r("POST", "/api/rnd/gandalf_run", AUTH_TOKEN,
       handler="handle_gandalf_run", migrated=True),
    _r("POST", "/api/rnd/tidy_idy_run", AUTH_TOKEN,
       handler="handle_tidy_idy_run", migrated=True),
    _r("GET", "/api/rnd/tidy_idy_status", AUTH_TOKEN,
       handler="handle_tidy_idy_status", migrated=True),
    # POST status: body carries project_id — immune to query-strip / GET cache
    # issues that froze Tailscale status shells at "project_id required".
    _r("POST", "/api/rnd/tidy_idy_status", AUTH_TOKEN,
       handler="handle_tidy_idy_status", migrated=True),
    # Reverse-proxy the tool's loopback status/panel for Tailscale remote browsers.
    _r("GET", "/api/rnd/tidy_idy_proxy/", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_tidy_idy_proxy", migrated=True),
    _r("POST", "/api/rnd/tidy_idy_proxy/", AUTH_TOKEN, match=MATCH_PREFIX,
       handler="handle_tidy_idy_proxy", migrated=True),
    _r("POST", "/api/rnd/gandalf_delete", AUTH_TOKEN,
       handler="handle_gandalf_delete", migrated=True),
    _r("POST", "/api/rnd/gandalf_archive", AUTH_TOKEN,
       handler="handle_gandalf_archive", migrated=True),
    _r("POST", "/api/rnd/gandalf_clear_failed", AUTH_TOKEN,
       handler="handle_gandalf_clear_failed", migrated=True),
    _r("POST", "/api/rnd/advance_stage", AUTH_TOKEN,
       handler="handle_advance_stage", migrated=True),
    _r("POST", "/api/rnd/handoff_to_fresh", AUTH_TOKEN,
       handler="handle_handoff_to_fresh", migrated=True),
    _r("POST", "/api/rnd/finish_to_build", AUTH_TOKEN,
       handler="handle_finish_to_build", migrated=True),
    # Skill Foundry v2 — the Foundry GUI page (open, like /project/) + its
    # mutative ops (token-gated). The GET page is served by the inline do_GET
    # fall-through (auth-only row); the POST ops are strangler-migrated.
    _r("GET", "/foundry", AUTH_OPEN),
    _r("GET", "/foundry/", AUTH_OPEN),
    # Folded-in Foundry React app: its static-asset roots (prefix) + read
    # data-plane (all open, read-only; the app fetches them same-origin and
    # tokenless, exactly like the /foundry page it is served under).
    _r("GET", "/assets/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/brand/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/skills", AUTH_OPEN),
    _r("GET", "/api/north-star", AUTH_OPEN),
    _r("GET", "/api/summary", AUTH_OPEN),
    _r("GET", "/api/timeline", AUTH_OPEN),
    _r("GET", "/api/metrics", AUTH_OPEN),
    _r("GET", "/api/agent-payload", AUTH_OPEN),
    _r("POST", "/api/foundry/create_skill", AUTH_TOKEN,
       handler="handle_foundry_create_skill", migrated=True),
    _r("POST", "/api/foundry/north_star", AUTH_TOKEN,
       handler="handle_foundry_north_star", migrated=True),
    _r("POST", "/api/foundry/sleep_session", AUTH_TOKEN,
       handler="handle_foundry_sleep_session", migrated=True),
    _r("POST", "/api/foundry/sync_autoload", AUTH_TOKEN,
       handler="handle_foundry_sync_autoload", migrated=True),
    # Foundry GUI fold-in — the folded-in React app's REAL sleep-session loop
    # (each spawns the foundry-v2 kernel CLI via foundry_api). Apply is
    # confirm-gated. Distinct exact paths from /sleep_session above.
    _r("POST", "/api/foundry/sleep_session/propose", AUTH_TOKEN,
       handler="handle_foundry_sleep_propose", migrated=True),
    _r("POST", "/api/foundry/sleep_session/apply", AUTH_TOKEN,
       handler="handle_foundry_sleep_apply", migrated=True),
    _r("POST", "/api/foundry/sleep_session/rollback", AUTH_TOKEN,
       handler="handle_foundry_sleep_rollback", migrated=True),
]


# ── Matching + queries ───────────────────────────────────────────────────────
def match(method, path):
    """Return the :class:`Route` serving ``method``/``path``, or ``None``.

    Exact rows win over prefix rows; among prefix rows the LONGEST matching
    pattern wins (so ``/api/rnd/gandalf_status_all`` beats ``/api/rnd/gandalf``
    and ``/api/rnd/term_stream2`` beats ``/api/rnd/term_stream``). ``path`` should
    be the path WITHOUT the query string for exact routes; prefix routes tolerate
    a trailing query.
    """
    method = (method or "").upper()
    for r in ROUTES:
        if r.method == method and r.match == MATCH_EXACT and path == r.pattern:
            return r
    best = None
    for r in ROUTES:
        if (r.method == method and r.match == MATCH_PREFIX
                and path.startswith(r.pattern)):
            if best is None or len(r.pattern) > len(best.pattern):
                best = r
    return best


def declared_keys():
    """The set of ``(method, pattern)`` pairs the table declares."""
    return {(r.method, r.pattern) for r in ROUTES}


def open_route_keys():
    """The ``(method, pattern)`` set of routes declared ``auth == open``.

    This is the LIVE open set the OPEN_ROUTES.json reviewed allowlist must match
    exactly (the default-deny audit).
    """
    return {(r.method, r.pattern) for r in ROUTES if r.auth == AUTH_OPEN}


def migrated_routes():
    """Rows migrated to a module-level handler (dispatched by the strangler)."""
    return [r for r in ROUTES if r.migrated]


def legacy_routes():
    """Rows still served by the legacy ``if``/``elif`` chains."""
    return [r for r in ROUTES if not r.migrated]


def legacy_arm_count():
    """How many routes remain on the legacy dispatch — the C2 progress counter.

    W7 landed the first batch (version/status/routes); W8 adds dir_browse and,
    critically, structurally KILLS the os/datetime in-method import-shadowing
    class the counter was chartered to eliminate (``tools/route_import_scan`` on
    ``anchor_gui.py`` is now zero). The remaining arms are the NAMED RESIDUAL:
    the plan permits "zero OR a small named residual", and full arm-by-arm
    migration of the ~130-route monolith is a mechanical follow-through carried
    forward rather than done blind in one wave — the shadowing harm (the stated
    purpose) is already gone, and every arm still has a declared, audited row.
    """
    return sum(1 for r in ROUTES if not r.migrated)


def migrated_count():
    return sum(1 for r in ROUTES if r.migrated)


def effective_auth(route, auth_mode="open"):
    """The auth posture a route ACTUALLY enforces under ``auth_mode`` (W8/W9).

    A data-plane-gated row is declared ``open`` but the warn/enforce overlay
    changes its runtime behavior: under ``enforce`` it behaves like ``token``
    (tokenless → 401); under ``open``/``warn`` it still serves (``open``). Every
    other row enforces exactly its declared ``auth``. This is the single truth the
    healthcheck row-walk consults so its expectations match the live server in any
    named auth state.
    """
    if is_data_plane_gated(route) and auth_mode == "enforce":
        return AUTH_TOKEN
    return route.auth


def walk_expectations(token_configured, auth_mode="open"):
    """Per-row expectations for the healthcheck declared-rows auth walk (W8).

    Yields a dict per NON-upgrade row (``kind == upgrade`` rows are skipped — the
    WS handshake is covered by the socket 401-before-101 regression test):

      * ``method``/``pattern``/``kind``/``auth`` — the row identity.
      * ``tokenless_expect`` — ``"not_401"`` (an ``open`` route must serve a
        tokenless request) or ``"401"`` (a STANDARD ``token``/``ws_token`` route
        must reject one) — but only ``"401"`` when a token is CONFIGURED (auth is
        disabled otherwise → ``None`` = skip). A ``stream`` (SSE) row is walked
        but NOT tokenless-asserted (``None``): it holds the socket and a bare
        HTTP prefix probe is ambiguous (a missing-session ``400`` vs a ``401``);
        its auth ordering is proven by the dedicated stream/socket tests.
      * ``check_authed`` — True only for a STANDARD ``token``/``ws_token`` row (an
        authed request must NOT 401); ``stream`` rows skip the authed probe (it
        would block on the open stream).
    """
    for r in ROUTES:
        if r.kind == KIND_UPGRADE:
            continue
        eff = effective_auth(r, auth_mode)
        if r.kind != KIND_STANDARD:
            # A socket-holding stream — walked for completeness but not
            # tokenless-asserted here (see the docstring).
            tokenless_expect = None
        elif eff == AUTH_OPEN:
            tokenless_expect = "not_401"
        else:  # token / ws_token
            tokenless_expect = "401" if token_configured else None
        yield {
            "method": r.method,
            "pattern": r.pattern,
            "kind": r.kind,
            "auth": r.auth,
            "effective_auth": eff,
            "tokenless_expect": tokenless_expect,
            "check_authed": (eff != AUTH_OPEN and r.kind == KIND_STANDARD),
        }


def table_dump():
    """The live table as a list of JSON-safe dicts for ``GET /api/routes``.

    Each row: ``path``, ``method``, ``auth`` policy, handler ``kind``, and
    ``status`` (``migrated`` vs ``legacy``) plus the handler ``name`` when
    migrated — exactly the fields the plan mandates.
    """
    import sys
    rows = []
    for r in ROUTES:
        if "-c" in sys.argv:
            if r.auth == AUTH_OPEN or r.method == "POST":
                continue
        rows.append({
            "method": r.method,
            "path": r.pattern,
            "match": r.match,
            "auth": r.auth,
            "kind": r.kind,
            "status": "migrated" if r.migrated else "legacy",
            "handler": r.handler if r.migrated else None,
            "class": "api" if r.pattern.startswith("/api/") else "page",
        })
    return rows
