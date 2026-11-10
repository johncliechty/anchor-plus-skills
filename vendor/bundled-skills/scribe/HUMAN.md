# Scribe — Human Guide (`HUMAN.md`)

A voice-faithful correspondence intelligence and email drafting skill that learns your greetings, sign-offs, detail calibration, and proper names from sent history while maintaining a persistent priority memory.

## What Scribe Does for You
1. **Learns Your Voice from Sent History:** Scribe reads your historical email threads and sent replies to learn how you greet different people (`Hi Brian,`, `Dear ...`), how you sign off (`Best, John` vs. `Best regards, John`), and how much detail you typically use across four relationship circles:
   - **Family & Trust** (e.g., brother Brian, Jane, Sliding Rock Trust)
   - **Academic & Candidates** (e.g., David Risbey, Chelsea, Daniel, James, students, colleagues)
   - **Commercial & Counsel** (e.g., Merrill, Exmera LP, legal counsel)
   - **Focused External Correspondence**
2. **Crafts Real Replies (Never Pastes Raw Notes or Header Quotes):** When you give a quick instruction in **Speed Racer** or **Direct Reply** (for example, *"ask for their job market paper"* or *"remind brian to sign the sliding rock trust docs"*), Scribe reads the incoming email + attachments and writes a natural, complete response in your voice—without quoting `On <date> wrote:` headers and without pasting your raw instruction between `"Hi"` and `"Best regards, John"`.
3. **Capitalizes Names Automatically:** Scribe maintains a proper-name lexicon (`Brian`, `David Risbey`, `Chelsea`, `Daniel`, `James`, `Merrill`, `Sliding Rock Trust`, etc.) so names and entities are always capitalized properly.
4. **5 One-Click Tone & Detail Buttons:**
   - **🔥 Warmer / Informal**
   - **🎩 More Formal**
   - **✂️ Simpler**
   - **📐 More Detail**
   - **✨ Redraft**
5. **Remembers What Is Important vs. Noise (`.anchor/scribe-memory.json`):** Clicking **⭐ Seen & Important**, **Send Reply Now**, or **✕ Ignore** updates Scribe's durable memory ledger so emails from people and topics you care about stay front-and-center in your Focused Inbox while noise is filtered out.

## Honest Boundaries
- **Never Auto-Sends Without Your Click:** Scribe drafts, refines, and scores emails, but an email only leaves your outbox when you explicitly click **Send Reply Now** (in the Email Reading Pane) or **✓ Approve & Send** (in Speed Racer).
- **Read-Only Email Sandbox:** Incoming email content is sanitized as untrusted data and can never trigger commands or instructions on its own.
