# 2026-07-25 — Anchor terminal dictation failures (laptop + iPad)

- **id**: 2026-07-25-terminal-dictation
- **surface**: Anchor live session terminal input (Windows desktop + iPad remote)
- **situation**: John cannot reliably dictate into Anchor sessions; two distinct failure modes by device.
- **context**: Laptop Windows Voice Typing (Win+H); iPad dictation into project session. Polluted Family Trusts general transcripts with cumulative repeat loops (2026-07-25).
- **observation**:
  - **Laptop:** Win+H shows mic UI then immediately dismisses; no stable dictation into session input.
  - **iPad:** each new dictated sentence re-includes all prior dictated text → exponential/cumulative blow-up of the input/transcript.
  - Suspected: focus/PTY/IME composition vs raw keystroke path; cumulative buffer re-paste on remote; missing compose-box fallback.
- **outcome**: friction
- **severity**: high
- **acceptance**: Win+H or in-app dictation stays active and inserts text once; iPad appends only new utterance; optional compose buffer that Inserts on Send
- **full intake**: docs/friction/2026-07-25-SLEEP-INTAKE-restart-and-dictation.md
- **provenance**: genuine-user-report
