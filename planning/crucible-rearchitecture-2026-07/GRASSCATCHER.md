
## Stage-1 triage — parked (out-of-scope; revisit if the North Star is amended)

- Butler v0 prototype: a read-only daily digest agent that consumes the journal and posts 'what happened this week' summaries. — Explicit non-goal ('NOT building the Butler itself'); park it — the B-23 schema stories keep the door open.
- Promote the journal to source of truth with a read-path cutover and legacy-store retirement. — Explicit non-goal; D1 defers this to a later effort. Parked with the note that B-21/B-22's semantics were designed to make the cutover safe later.
- Decompose terminal_session.py (3,547 lines) while the supervisor work is touching its seams anyway. — Explicitly excluded (Plan-1 Wave D item 13, A5); tempting adjacency is exactly how scope creep happens — park it.
- Enable the iPhone/Tailscale exposure (Tailscale Serve HTTPS + PWA manifest) once the auth pillar lands, since C2 removes the blocker the anchor-as-app research identified. — C2 is the enabler but exposure itself is a separate effort; B-14's PWA spike keeps this future compatible without absorbing it.
- Cross-project GLOBAL journal aggregator (one merged event stream across all projects with cross-project ordering). — C3 is per-project by design; a Butler-era need at most. B-23's per-project seq + wall ts makes later merging possible without building it now.
- Supervisor also absorbs the preview_server and zombie-hunter lifecycles so ALL child processes have one owner. — Attractive symmetry but C4 scopes 'spawned lane jobs' + PTYs-behind-spike only; absorbing more surface area multiplies FM-7/FM-8 risk in the same wave. Park as a natural follow-on.
