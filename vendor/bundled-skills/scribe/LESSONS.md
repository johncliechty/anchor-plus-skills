# Scribe — Operational Lessons (`LESSONS.md`)

## Lesson 1 (2026-11-07): Never Echo Steering Instructions or Quoted Headers
- **Symptom:** Early Speed Racer drafts took the user's steering instruction (e.g., `"ask for his job market paper"` or `"make it warmer"`) and pasted it verbatim between `"Hi Name,"` and `"Best regards, John"`, or appended raw `On <date> <sender> wrote:` header dumps.
- **Mechanism:** `scribe_engine.synthesize_reply` and `scribe_engine.transform_draft` strip all quoted headers (`strip_quoted_headers_and_history`), translate third-person steering clauses (`tell him...`, `ask her for...`, `remind brian to sign...`) into natural first-person sentences (`_translate_instruction_Clause`), and apply 5 dedicated tone/detail transforms (`warmer`, `more_formal`, `simpler`, `more_detail`, `redraft`).

## Lesson 2 (2026-11-07): Deterministic Proper-Name Lexicon Protects Names Without Mangling URLs/Emails
- **Symptom:** Rapid dictation or lowercase instructions (`"hi brian, please sign the sliding rock trust docs with david risbey and chelsea"`) left people's names and trust names uncapitalized in drafts.
- **Mechanism:** `scribe_engine.apply_proper_name_lexicon` masks URLs and email addresses first, applies longest-match-first proper-name replacement (`Sliding Rock Trust`, `David Risbey`, `Brian`, `Chelsea`, `Daniel`, `James`, `Merrill`, `Jane`), capitalizes salutation names and sentence starts, and restores URLs/email addresses untouched.
