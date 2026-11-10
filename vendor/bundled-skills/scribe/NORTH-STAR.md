# Scribe — Locked North Star (`NORTH-STAR.md`)

> **North Star:** Build **Scribe** (`skills/scribe`), a voice-faithful correspondence intelligence and drafting skill that mines John's historical email threads and sent replies to learn his authentic tone, greeting/sign-off habits, detail calibration by recipient relationship, and proper-name capitalization, while maintaining a persistent interest-and-priority memory ledger (`.anchor/scribe-memory.json`) that powers focused inbox filtering, 1-click tone/detail refinement (`Warmer / Informal`, `More Formal`, `Simpler`, `More Detail`, `Redraft`), and fast direct replies inside Anchor's Cave of Wonders.

## Success Criteria
1. **Skill Foundry Package & Feather Quill Identity (`C1`):** `SKILL.md`, `HUMAN.md`, `NORTH-STAR.md`, `LESSONS.md`, `LIBRARY.json`, `FLOW.json`, `knowledge/graph.json`, `assets/icon.jpg`, and `scripts/scribe_engine.py` exist and validate cleanly, with `/vendor/brand/scribe-icon.jpg` registered in `foundry_page.py` and `steward_cockpit/static/skill-icons.js`.
2. **Historical Correspondence Miner (`C2`):** `mine_correspondence_history` idempotently extracts sender relationship archetypes, greetings, sign-offs, and proper names from `.anchor/comms-sync.json`.
3. **Persistent Interest & Priority Memory Ledger (`C3`):** `.anchor/scribe-memory.json` persists `Seen & Important`, `Ignore`, `Direct Reply`, and `Speed Racer` signals atomically via `temp + os.fsync + os.replace` under `paths.WRITE_LOCK`, separating `empty` vs `unknown` states.
4. **Proper-Name Lexicon & Anti-Header-Quote Synthesis (`C4`):** Capitalizes proper names (`Brian`, `David Risbey`, `Chelsea`, `Daniel`, `James`, `Merrill`, `Sliding Rock Trust`) automatically, strips `On <date> wrote:` header quotes, and translates steering directions into natural prose.
5. **5-Mode Tone & Detail Transformation Engine (`C5`):** Powers `warmer`, `more_formal`, `simpler`, `more_detail`, and `redraft` transformations in `<20ms`.
