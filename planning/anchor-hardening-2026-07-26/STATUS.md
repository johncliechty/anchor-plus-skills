# Anchor hardening — status log (10-min cadence, John's locked format)
# HONESTY NOTE (2026-07-26 19:29): the first entry was originally stamped [17:10],
# copied from earlier CLI output instead of the clock — corrected to [19:00] (the
# real commit time). And NO timer was ever armed: the cadence was written into
# PLAN.md but no mechanism scheduled it. Same "documented but not wired" class this
# review exists to kill. A cadence claim with no scheduler is a false green.
#
# GOAL (lead every update with this): make Anchor world-class — fix what John
# reported (zombie detection, tile summaries/restart, terminal double-print,
# iPad dictation, usage tracking) + add friction journaling — then ship v1.1.1
# to collaborators. Evidence: FINDINGS-A/BCD/E/F. Program: REVIEW.md. Plan: PLAN.md.

[19:00] wave 1+journaling COMMITTED
Effort   | Anchor hardening -> v1.1.1 (pre-collaborator-share gate)
Doing    | journaling landed (638b0cb); next = journaling endpoints/UI, then P0
           terminal cursor-resume + one-mount teardown, dictation, token redaction
Status   | 3 of ~9 fix items done; 6 evidence reports complete; nothing pushed yet
Tests    | +15 new green (10 friction-journal, 5 usage/guard); smoke subset 40 pass
           / 1 pre-existing fail (test_token_hygiene, confirmed at HEAD)
Blocker  | none
Procs    | no background agents running; all 6 review agents finished
Journal  | usage record 2026-07-26-02 RESOLVED with commit 121b479; record
           2026-07-26-01 (terminal double-print) still OPEN — closes when P0.1/P0.2 land
ETA      | remaining P0 + endpoints ~1 working session, then propagate/re-vendor/
           smoke/tag v1.1.1/memo
To do    | journaling endpoints+UI · terminal cursor resume · one-mount teardown ·
           dictation compose box · token redaction · zh-node backoff · summarizer
           quality · release sequence · collaborator memo

[19:29] IDLE — awaiting user; no work since 19:00
Effort   | Anchor hardening -> v1.1.1 (pre-collaborator-share gate)
Doing    | nothing — session idle between turns, awaiting John's go
Status   | unchanged from 19:00: 3 of ~9 fix items done, nothing pushed
Tests    | unchanged (+15 green this effort)
Blocker  | NONE technical. Process gap: the 10-min cadence was documented but no
           scheduler was armed (corrected in this file; needs /loop to actually run)
Procs    | none
Journal  | unchanged — 2026-07-26-01 (terminal double-print) OPEN
ETA      | unchanged
To do    | arm a real cadence (see PLAN) · journaling endpoints+UI · terminal
           cursor resume · one-mount teardown · dictation · token redaction ·
           zh-node backoff · summarizer quality · release · memo

[04:52] RUN START — v1.1 hardening resumed (steward/v1.2 EXCLUDED per John)
Effort   | Anchor v1.1.1 hardening: finish P0 fixes + journaling endpoints, ship
Doing    | isolating 735 lines of UNCOMMITTED Ecgberht/steward (v1.2) work found in
           anchor_gui.py, route_table.py, static/project-window.{js,css,html} —
           the exact files my terminal/dictation fixes touch. Committing it
           SEPARATELY, untouched, so my v1.1 commits stay clean and honest.
Status   | wave 1 + journaling already landed (121b479, 638b0cb); 6 items to go
Tests    | +15 green so far this effort
Blocker  | none (steward isolation is the mitigation, not a blocker)
Procs    | none
Journal  | 2 open: terminal double-print (problem), status-cadence gap (concern)
ETA      | P0 fixes this run; release sequence + memo after
To do    | steward isolate · journaling endpoints+UI · terminal cursor resume ·
           one-mount teardown · dictation · token redaction · zh-node backoff ·
           summarizer quality · release · memo

[05:12] P0.1 + P0.2 LANDED — terminal double-print fixed
Effort   | Anchor v1.1.1 hardening (steward/v1.2 isolated at b9252a9, untouched)
Doing    | committed terminal cursor-resume + one-mount teardown + sleep-resume
Status   | 5 of ~9 items done (usage, test guard, journaling CLI, P0.1, P0.2)
Tests    | +12 new terminal regression tests; 23 green incl. the two UI suites
Blocker  | none
Procs    | none
Journal  | terminal double-print record CLOSES with this commit; cadence-gap
           record still open
ETA      | dictation + token redaction + zh-node next; then release sequence
To do    | dictation compose box · token redaction · zh-node backoff · journaling
           endpoints+UI · summarizer quality · release · memo

[05:34] P0.3 LANDED — iPad dictation blow-up fixed
Effort   | Anchor v1.1.1 hardening (steward/v1.2 isolated at b9252a9, untouched)
Doing    | composition guard + textarea clear + delta-only send + server cap + iOS CSS
Status   | 6 of ~9 items done
Tests    | +8 dictation tests; 20 green with the terminal set
Blocker  | none
Procs    | none
Journal  | 1 open (status-cadence gap); terminal + usage records closed
ETA      | token redaction + zh-node backoff next, then journaling endpoints
To do    | token redaction · zh-node backoff · journaling endpoints+UI ·
           summarizer quality · release sequence · collaborator memo

[05:48] P0.4 LANDED — capability token no longer written to the access log
Effort   | Anchor v1.1.1 hardening (steward/v1.2 isolated at b9252a9, untouched)
Doing    | redaction at the single request-line writer + 8 tests
Status   | 7 of ~9 items done
Tests    | +8 redaction tests (48 new tests total this effort, all green)
Blocker  | none
Procs    | none
Journal  | 1 open (status-cadence gap)
ETA      | zh-node backoff, then journaling endpoints, then release sequence
To do    | zh-node backoff · journaling endpoints+UI · summarizer quality ·
           release sequence · collaborator memo
NOTE     | pre-existing logs still contain historic tokens; rotating/scrubbing
           them is an operator action - flag to John before the memo ships.

[06:12] P0.6 + journaling endpoints LANDED
Effort   | Anchor v1.1.1 hardening (steward/v1.2 isolated at b9252a9, untouched)
Doing    | zh-node circuit breaker + friction HTTP endpoints, both tested
Status   | 8 of ~9 items done; summarizer quality is the last fix
Tests    | +5 breaker, +2 endpoint contract; 61 new tests this effort, all green
Blocker  | none
Procs    | none
Journal  | 1 open (status-cadence gap)
ETA      | summarizer quality, then propagate/re-vendor/smoke/tag v1.1.1/memo
To do    | summarizer quality · release sequence · collaborator memo

[05:43] SUMMARIZER QUALITY LANDED (9d13b2e) — last fix of the wave
Effort   | Anchor v1.1.1 hardening (steward/v1.2 isolated at b9252a9, untouched)
Doing    | P1.3 empty-corpus short-circuit + P1.4 near-duplicate collapse
Status   | ALL 9 fix items done; release sequence is what remains
Evidence | measured across the 167 cached summaries on disk:
           - 76 (45%) render blank "no grounded claims" -> those model calls
             are now skipped entirely (one such blank cost 194,422 tok / 66.6s)
           - 56 carry restated claims -> 278 redundant claims collapsed;
             one 33-claim planning summary comes back as 20
Tests    | +12 summarizer quality; 73 new tests this effort, all green.
           test_summary_on_finish_v7 was FIXED not accommodated: its sessions
           owned no docs, so at HEAD it asserted a BLANK summary got cached —
           it encoded the bug. Each now gets a real member doc. 9/9 pass.
Known    | test_project_summary_v5::test_seed_includes_all_sources fails at
           HEAD too (verified by git stash) — pre-existing, not from this work.
Blocker  | none
Procs    | none
Journal  | 1 open (status-cadence gap)
ETA      | propagate to Anchor-release-v1.0 -> re-vendor skills -> in-bundle
           smoke -> tag v1.1.1 -> collaborator memo x3
To do    | release sequence · collaborator memo
NOTE     | still outstanding for John (operator action, not code): existing log
           files under logs/ contain historic capability tokens. Redaction is
           live for NEW requests; the old files need rotating before sharing.

[05:54] RELEASE SEQUENCE — found and fixed a v1.1.0 SHIP-BLOCKER
Effort   | Anchor v1.1.1 hardening (v1.2 steward kept out of the release)
Doing    | propagating the 9 hardening fixes into Anchor-release-v1.0
FINDING  | *** the public v1.1.0 tag could not start at all. ***
           anchor_gui -> foundry_gui -> foundry_autoload -> foundry_map, and
           foundry_map resolves its schema at MODULE SCOPE. But
           foundry_map_v2.schema.json was never listed in dist_manifest.txt,
           which is deny-by-default — so it silently never shipped. Anyone who
           cloned v1.1.0 got FileNotFoundError on `import anchor_gui`.
           Verified against the TAG itself (git ls-tree v1.1.0 -> 0 matches).
           Every build check was green because every check reads file CONTENT,
           and a content scan cannot see a file that is ABSENT.
Fix      | shipped the 3 foundry_map data files + friction_journal.py (my new
           module, which had the identical hole waiting), and wired a STARTUP
           GATE into distro.py: the build now imports the staged bundle in a
           child process and fails if it cannot start (8637dd5, +7 tests).
v1.2     | isolated cleanly. Built the release tree by reverting b9252a9 in a
           throwaway worktree; one CSS conflict resolved by keeping my
           dictation block and dropping the Ecgberht chamber styles. Verified
           0 ecgberht/high-seat references in the release bundle.
Verified | 70/70 hardening tests green in the v1.2-free tree · release bundle
           imports OK · ramanujan HOLDS/REFUTED as documented · legal-beagle
           11/11 · financial-analyst 8/8 · journaling CLI works in-bundle and
           reports 1.1.1 · distro PII/secret scan unchanged (67 pre-existing
           findings before AND after, so I introduced none)
Journal  | 2 open (status-cadence gap; the v1.1.0 ship-blocker, journaled)
Blocker  | none
ETA      | collaborator memo x3, then push
To do    | memo · commit+tag v1.1.1 · sync Anchor-dev · push
NOTE     | pre-existing and NOT fixed here: `python distro.py` itself still
           fails its scan on 67 fake secrets inside vendored skill TEST files
           (e.g. apiKey: 'short-key'). Identical before my changes. The release
           repo is maintained by file copy, not by distro.py, so this does not
           block v1.1.1 — but the builder is unusable until those fixtures are
           allowlisted. Flagging, not silently fixing.

[05:58] SHIPPED — v1.1.1 tagged and pushed
Effort   | Anchor v1.1.1 hardening — COMPLETE
Shipped  | github.com/johncliechty/Anchor @ 784ed0f, tag v1.1.1 (verified on
           the remote: refs/tags/v1.1.1^{} -> 784ed0f)
           source repo C:\dev\Anchor -> E:\anchor.git master @ 8637dd5
Memo     | COLLABORATOR-EMAIL.md rewritten for 1.1.1 in the release repo and
           copied to C:\dev\Anchor-COLLABORATOR-EMAIL.md. It LEADS with the
           1.1.0-could-not-start notice and carries an explicit token-rotation
           warning for anyone who ran an older build.
Totals   | 10 fixes · 77 new tests · 9 commits (v1.2 isolated in its own
           commit b9252a9 and kept OUT of the release bundle)
Journal  | v1.1.0 ship-blocker record RESOLVED against 784ed0f.
           1 still open: the status-cadence gap (a real process defect —
           leaving it open deliberately).
NOT DONE — deliberate, needs John:
  1. Anchor-dev was NOT synced. It carries ~18k lines of UNCOMMITTED v1.2
     steward work in exactly the files a sync would overwrite (anchor_gui.py,
     route_table.py, project-window.js/css). Overwriting work I did not author
     and John has not committed is not mine to do. Sync it after the steward
     work is committed.
  2. Existing logs/ still contain historic capability tokens. Redaction covers
     NEW requests only; it cannot clean what is already written. Rotate the
     token and scrub/delete those files.
  3. `python distro.py` still fails its own secret scan on 67 placeholder keys
     in vendored skill TEST files (identical count before this work). The
     release repo is maintained by file copy so this did not block v1.1.1, but
     the builder is unusable until those fixtures are allowlisted.
Deferred to v1.2 (recorded, not dropped): zombie detection made real (P1.5),
RESTART.md brief rewrite (P1.1/P1.2), keyed board diff (P1.6), P2 hygiene,
journaling UI control.
