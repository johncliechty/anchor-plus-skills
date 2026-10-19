# Cockpit shows "interrupted" while the steward is working in the background

John, MBA Teaching AI, 21 September 2026, during the AI Supplement 3 Draft 3 build:

> Why have I got an interupted error/status? That seems like a mistake if you are working. Somthing to journal about.

What was actually happening: the steward (Claude seat) had launched seven real Claude Code rehearsal runs as a detached background script, armed a Monitor on their log, set `.ecgberht/attention.json` to `{"state":"working","reason":"Building AI Supplement 3 Draft 3 ..."}`, and ended its turn with a one-line note that nothing else could proceed until the runs landed. The runs were still executing (log entries every few minutes; the Denver plan-first execution was in flight). John then sent "What is going on?" and saw an *interrupted* error/status.

Mechanism, as far as this seat can see it: the cockpit derives "interrupted" from the turn boundary — a steward turn that ends without a handback while a human message arrives (the same label the engine resume calls "INTERRUPTED TURN: human message arrived during a self-started turn"). It does not consult the attention flag (`working`) or the background job the steward is waiting on, so honest waiting on background work reads as a failure.

Why it matters: it violates the standing rule that the indicator must be green while work is running and amber only for a real question (John, 2026-09-09), and it costs John a message each time ("Are you stalled?", "What is going on?", this one) — three overhead messages across two days for the same cause.

Recommendation: while `attention.json` is `working` (and within its lease), or while a Monitor/background task owned by the current steward session is alive, render the header as *working: <reason>* and never as interrupted; reserve *interrupted* for a turn that ended without a handback **and** with no live background work. Acceptance: start a detached job, end the steward turn, send a human message, and confirm the header reads working with the reason, then flips to quiet when the job lands.

Not fixed here: this seat can only journal it; the cockpit change belongs to the separate Anchor/Steward effort. The MBA campaign continued; no slice was closed.
