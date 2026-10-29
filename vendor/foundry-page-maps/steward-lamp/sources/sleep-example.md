- `id`: 0076-sleep-cycle-promoted-a-gandalf-lesson-into-a-live-bug
- `skill`: ecgberht@v1.2.0
- `situation`: a sleep cycle promotes a lesson from one skill's journal and it lands on a live defect in another
- `context`: first real sleep cycle over the Foundry+trio corpus, 2026-08-04, run after
  514 journal files had accumulated with no cycle ever executed.
- `observation`:

  **A lesson from gandalf's journal found a bug shipped in Ecgberht hours earlier.**
  Gandalf 0274+0275 clustered (2 distinct contexts) on whole-project brownfield reads,
  and 0275's named fix was: a `main()` guard comparing `resolve(argv[1])` to the module's
  own path is a SILENT NO-OP through a junction — two spellings of one file, never equal,
  so `main()` never runs and the process exits 0 with empty stdout.

  Ecgberht is REGISTERED as a junction (`~/.claude/skills/ecgberht -> C:\dev\Ecgberht`),
  so the canonical host path is exactly the spelling that triggers it. Verified live:
  `node ~/.claude/skills/ecgberht/bin/ecgberht.mjs status --project …` printed NOTHING
  and exited 0. Same for `bin/steward.mjs` — which I had written that same day, copying
  the defective guard from `bin/ecgberht.mjs` without examining it. That is the second
  time in two days a defect propagated because I copied a working-looking construct
  (the first was the Foreman launcher's inverted model seats, journal foreman/0098).

  Fixed by realpathing both sides (`engine/direct-invocation.mjs`), exported, used by
  both CLIs, and pinned by `test/wh2-junction-invocation.test.mjs`, which reaches the
  CLIs through a real junction and fails if either guard regresses.

  **Two process notes worth more than the bug.** (1) My first version of that test used
  `t.skip()` when a symlink could not be created — and the repo's w48 guard correctly
  failed the build: a silently-skipped test is indistinguishable from a passing one. The
  skip was unnecessary (directory junctions need no privilege), so the test now fails
  loudly instead. (2) My first two journal PARSERS were wrong (a JS regex with `\Z`,
  which matches a literal Z, so the last field never terminated) and reported 0-32
  entries out of 514. A parser bug and a genuinely quiet corpus produce IDENTICAL output
  — "no candidates" — which is precisely how a broken improvement loop stays invisible.
- `outcome`: worked — 2 lessons promoted to gandalf LESSONS.md, 1 live defect fixed in
  two CLIs, gate 1205/0
- `provenance`: genuine-execution

## Lesson (one line)

**Run the sleep cycle across skills, not within one — the corroborated lesson from one
skill's journal is often a live, unnoticed defect in another — and never trust a
"0 candidates" cycle until you have printed parsed-vs-total, because a broken reader and
a quiet corpus look exactly alike.**
