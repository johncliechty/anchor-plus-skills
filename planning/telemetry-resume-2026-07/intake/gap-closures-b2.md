# diag-B2 closure — tile/resume inconsistencies ROOT-CAUSED (code-verified 2026-07-11)

Investigation delegated per the Stage-0 ingest gate; all three symptoms traced to
exact code paths. Confidence: mechanical chains VERIFIED-FROM-CODE; the real-world
triggering events are high-confidence, code-consistent hypotheses pending the
criterion-4 Playwright repro (repro-first discipline stands — fixtures before fixes).

## S1 — Blank window on large (headline) tiles
`laneTileClick` routes every `data-effort-id` tile to `openEffortDock`, which decides
liveness from the CLIENT cache alone (`MANAGED[sid].status === 'running'`,
project-window.js:4057). `repopulate()` runs only on DOMContentLoaded + after
user-initiated actions — NO periodic/visibility re-poll — so a session that dies
server-side (restart/reap/crash) while a tab sits open stays cached 'running'.
Click → `_mountTerminal` → WS (`_serve_term_ws`, anchor_gui.py:13350-13354) and the
SSE fallback both terminate SILENTLY on `{"ok":false,"reason":"unknown-session"}`
(no output frame ever sent) → xterm never receives a byte → blank pane; summary area
shows the uncached placeholder. Headlines are hit disproportionately because the
most-recent session is the one most likely cached-live at death.
**Fix direction:** paint an explicit "no longer live" state / fall back to
`_mountReadOnlyBody` on contentless close; add periodic or visibility-triggered
repopulate; optionally verify liveness server-side before choosing `live`.

## S2 — Context-free blue restart button
Non-live tiles mount `_mountReadOnlyBody` → the blue `.ro-continue` button POSTs
`continue_session` immediately with NO preview. Context is absent because: dock
title falls back to bare "<lane> · <skill>" (`label` defaults `""` in
`start_session`, terminal_session.py:370-372, and callers don't pass one); the
summary region shows "No cached summary" for never-summarized sessions; and the
actual resume context (`_build_continue_seed`'s doc list/phase) is only revealed
AFTER the click mints a session.
**Fix direction:** surface a pre-click preview of what the seed would contain
(title/what-was-asked/skill/age/doc list); better title fallback than lane·skill.

## S3 — Manual orientation after restart
TWO structurally different resume mechanisms coexist, undistinguished for the user:
(1) `continue_session` AUTO-SUBMITS the seed (folded into the launch seed,
terminal_session.py:579-590); (2) every stage-handoff path uses v11.1 pending-paste
(never auto-submits). Same-looking "restart" behaves differently depending on which
internal flow produced it — the reported inconsistency. COMPOUNDING: the
pending-paste flush is gated on observing the literal greet marker
("what would you like to do?", terminal_session.py:180, counted vs the seed's own
occurrences at 706-712) — a model that paraphrases/omits the greet (or a backend
switch, or an env-overridden seed without the marker) leaves the paste pending
FOREVER; and the flush is only evaluated on attach/read_since, so an unmounted
follow-on session never even checks.
**Fix direction:** one consistent user-facing resume policy (read-only orientation
may auto-run; ACTION prompts stay paste-not-submit — the Stage-0 fork), plus a
bounded fallback for the greet gate (time/poll-based flush or an explicit
"orientation undelivered — click to insert" affordance).

Full report: agent transcript 2026-07-11; key locations —
project-window.js:2261-2280 (laneTileClick), 4033-4136 (openEffortDock),
3814-3936 (_mountTerminal), 2959-2981 (_mountReadOnlyBody), 3260-3372 (summary);
anchor_gui.py:13190-13194/13350-13354 (silent transports), 1691-1794
(_build_continue_seed); terminal_session.py:180/191-205/631-753 (greet gate),
370-372 (label default), 579-590 (auto-submit), 1978-2096/3098+ (pending-paste).
