# Scribe — Voice, Tone & Priority Memory Reference (`SCRIBE-VOICE-TONE-MEMORY-REFERENCE.md`)

## 1. Relationship Archetypes & Default Register Matrix

| Archetype ID | Label | Typical Senders / Context | Default Salutation | Default Sign-Off | Warmth | Formality | Detail Calibration |
|---|---|---|---|---|---|---|---|
| `family_trust` | **Family & Trust** | Brother Brian, Jane, Sliding Rock Trust, family travel/estate | `Hi <First>,` | `Best,\nJohn` | `0.85` | `0.35` | `direct_warm` |
| `candidate_academic` | **Academic & Candidate** | David Risbey, Chelsea, Daniel, James, PhD/faculty applicants, MBA students | `Hi <First>,` | `Best regards,\nJohn` | `0.72` | `0.55` | `collegial_concise` |
| `commercial_counsel` | **Commercial & Counsel** | Merrill, Exmera LP, Nexia, Stanford counsel, legal/financial partners | `Hi <First>,` | `Best regards,\nJohn` | `0.55` | `0.75` | `executive_precise` |
| `general_external` | **Focused Correspondence** | General incoming inquiries, scheduling confirmations, vendors | `Hi <First>,` | `Best regards,\nJohn` | `0.65` | `0.55` | `concise` |

## 2. Interest & Priority Memory Weights (`.anchor/scribe-memory.json`)

| User Action | Sender Weight Delta | Domain Weight Delta | Topic Keyword Delta | Focused Inbox Effect |
|---|---|---|---|---|
| **⭐ Seen & Important** (`seen_important`) | `+25` (`important: true`) | `+12` | `+8` | Always surfaces future unread emails from this sender in Focused Inbox |
| **✉️ Direct Reply / ✓ Approve & Send** (`direct_reply` / `approve_send`) | `+20` (`important: true`) | `+10` | `+6` | Marks sender high-priority and ingests reply greeting/sign-off into voice profile |
| **🏎️ Speed Racer** (`speed_racer`) | `+15` | `+6` | `+5` | Boosts sender actionability score |
| **✕ Ignore** (`ignore`) | `-25` | `-10` (`-3` on public webmail) | `-6` | Suppresses low-value sender/topic out of Focused Inbox into All Emails |
