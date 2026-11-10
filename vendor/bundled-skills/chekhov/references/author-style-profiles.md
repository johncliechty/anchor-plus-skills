# Author Writing Style & Voice Profiles Within Chekhov

Chekhov preserves and enforces a distinct **Author Writing Style Profile** for each of the author's creative domains (`artificial-magi`, `bright-heart`, `sing-for-the-dead`, and `essays`), grounded in the salvaged project-local voice guides indexed in `lib/salvage-index.mjs` and `lib/prose.mjs`.

- **W1 Privacy & Project-Root Resolution Boundary (`packs/README.md`, `lib/privacy.mjs`):** Raw author calibration passages and private manuscript excerpts remain strictly inside each writing project's root (`<project_root>/.claude/skills/<voice>/SKILL.md` and `editorial/EDITORIAL-LEARNING.md`) and are never copied into shareable `packs/`. This reference document serves as Chekhov's **Per-Project Style Dispatch Contract & Cross-Contamination Guard Table** so operator sessions and Beta-Reader sub-agents load the right mechanical rules for the active project key.

> **THE BIDIRECTIONAL CROSS-CONTAMINATION GUARD (HARD LAW):**
> Each book series or collection has deliberate, craft-specific mechanical laws. In particular, ***Sing for the Dead* (`sing-for-the-dead`) uses a poetic-prose prosody whose punctuation and word-formation rules are the exact opposite of the novel rules (`artificial-magi` and `bright-heart`).**
> - **Direction 1 (Novels / Essays $\not\to$ *Sing for the Dead*):** Chekhov, its Beta-Reader sub-agents (`Seat 3` and `Seat 5`), and its prose refinement pass must **NEVER** apply novel punctuation caps, compound-word bans, `bright-heart`'s filter-verb / gaze-word bans, or `essays`' 40-word sentence ceiling to *Sing for the Dead*.
> - **Direction 2 (*Sing for the Dead* $\not\to$ Novels / Essays):** Conversely, never leak *Sing for the Dead*'s multi-word poetic compound chains, cascading em-dashes, slash notation, unattributed italicized interiority, list-compressing semicolons, parenthetical emotional detonations, or communal `"we/our"` narration into *Artificial Magi*, *Bright-Heart*, or *Essays Beyond*.

---

## 1. Cross-Project Mechanical Contrast Matrix

Before running any drafting, linting, beta-reader, or prose-polish pass, Chekhov resolves the active project key from `roots.json` and locks the corresponding column in this matrix:

| Craft Dimension | `artificial-magi` (*Artificial Magi*) | `bright-heart` (*Bright-Heart*) | `sing-for-the-dead` (*Sing for the Dead*) | `essays` (*Essays Beyond*) |
| :--- | :--- | :--- | :--- | :--- |
| **Genre & Target Reader** | YA / Crossover SFF (Ages 10–14+ to Adult; 60% 10yo floor) | Upper-YA / Adult Epic SFF & Trauma Allegory (Ages 14+ / Adult) | Adult Literary Sacred Realism in Poetic Prose | Adult Analytical & Philosophical Nonfiction |
| **Default Form Pack** | `four-part` (with Two-Stage Causal-Key Welds) | `four-part` / `kishotenketsu` (thread-specific) | `eddy` (5-Part Temporal Spiral) | `prosecution` (`Claim -> Ground -> Illustrate -> Test`) |
| **POV & Narrative Distance** | Close-third single POV (`ct` / Charlie) | Multi-POV close-third (`ct`) with sharp register shifts per POV | Communal-witness `"we/our"`, intimate `"I"`, or close-third with oral storytelling cadence | Direct first/editorial voice (`"I"` / forensic declarative) |
| **Hyphenated Compounds** | **BANNED (`-like` & poetic chains):** Zero `-like` compounds or multi-word poetic compound chains (standard grammatical hyphens like `ten-year-old` allowed) | **BANNED (`-like` & poetic chains):** Zero `-like` compounds or multi-word poetic chains (standard grammatical hyphens allowed) | **SIGNATURE PROSODY: 3–4 multi-word hyphenated compounds per full narrative paragraph** (`deep-water-wave`, `soul-spent-lament`, `God-Within-Cries`; descriptive range, never reduced in editing) | Standard grammatical hyphenation only |
| **Em-Dash Budget (`—`)** | **Capped at $\le 3$ per page** (250 words) | **Capped at $\le 3$ per page** (250 words) | **LIBERAL CASCADING (`2–4+` per long cascading sentence):** Primary syntactic engine; **NEVER reduce in editing** | Sparingly (prefer colons `:` for pivots) |
| **Semicolons (`;`)** | **BANNED (`0` per chapter)** | **Rare ($\le 1\text{–}2$ per chapter)** | **ACTIVE TOOL:** Used as rapid-fire list-compression accelerators inside long sentences | Allowed for balanced forensic clauses |
| **Slash Notation (`a/b`)** | **BANNED** | **BANNED** | **SIGNATURE (`1–3` per story):** Simultaneous mental states (`watching/wondering`) | **BANNED** (except citations/ratios) |
| **Italics Discipline** | **Strict Four-Rule Italics:** (1) book/ship titles, (2) foreign/runic terms on first use, (3) direct silent telepathy/comms, (4) single-word vocal stress (rare). No unattributed floating thoughts. | Attributed deep interiority + *lyn* incantation markers; no unanchored floating italics | **UNATTRIBUTED ITALICIZED INTERIORITY:** Raw inner voice breaking through mid-paragraph without `"he thought"` tags | Emphasis and titles only |
| **Dialogue Ratio & Action Beats** | **40–50% of chapter lines** must be dialogue; crisp banter + tactile workshop beats | Scene-dependent; **period after action beat before quote** (`He set the knife down. "No."` — never a comma) | **Minimal, high-weight dialogue:** Characters speak rarely; when they speak, a single line carries the weight of years | Quoted primary sources and steelmanned objections |
| **Treatment of the Sacred / Wonder** | Magic as discoverable engineering + dangerous institutional mystery | **"The Wound Before the Wonder"** (physical/emotional cost precedes mythic awe) | **The Sacred as Material Fact:** Zero narrator hedging (`"as if"`, `"it seemed"`, `"almost like"`, `"almost felt"`, `"he imagined"` are **BANNED** on narrator sacred beats) | Empirical & philosophical rigor |

---

## 2. Profile 1: `artificial-magi` (*Artificial Magi* — Canonical Writing Style, Locked Gold Standard `v9`/`v10`)

- **Salvaged & Forged Source Lineage:** `<path> Magi/.claude/skills/magi-voice/SKILL.md`, `expert-editor/SKILL.md`, `<path> Magi/Book 1/editorial/EDITORIAL-LEARNING.md` (Laws 1–15), and `<path> Magi/Book 1/editorial/CANONICAL-WRITING-STYLE-ARTIFICIAL-MAGI-v1.md`.
- **Core Voice Identity (The *Artificial Magi* Gold Standard):**
  Warm, fast-moving, sharp-witted, tactile YA/crossover sci-fi/fantasy (`Ages 10–14+ to Adult`) where a diverse six-kid crew (`Hackers for Peace—and Pizza`: `ct`, `el`, `Durgan`, `Remi`, `Anya`, and eleven-year-old `Jess`) approaches ancient-looking game mysteries and underground fiber vaults with hands-on builder ingenuity, crackling banter, and fierce loyalty—tested against the chilling institutional power of `Halcyon` and `Julian Thorne`'s Grey Hat Hackers (`GHH`).
- **The Tonal Contrast Engine (Light, Witty Kid Comedy vs. Ice-Cold High Stakes):**
  - *In the workshop, kitchen, and hallways:* Keep the tone light, clever, grounded, and genuinely funny through concrete physical business and kid-level stakes—`Jess` appointing herself Chief of Labels and Crusts and tagging power strips with a fat black Sharpie (*DO NOT UNPLUG UNLESS YOU WANT DURGAN TO CRY*, *TOUCH THIS AND DIE — REMI*), `Durgan` tripping the three-phase breaker into pitch darkness while `Jess` freezes with a cold slice of pepperoni halfway to her mouth as `Marcus Vance`'s boots clomp past, or `Jess` declaring that messing with pizza day is a war crime against sixth grade.
  - *When the threshold or antagonist strikes:* Drop the humor instantly into dead-cold, tactile precision—a tiny needle-sharp blue-white spark jumping across the gap between `Julian`'s tinted glasses and his temple while his palms rest flat on the desk and `Noah`'s untended terminal hijacks a girl's Queens apartment router and webcam; the unplugged Xeon rig printing `*I HEARD THE HINGES.*` in an empty dark vault; or the word `*MAGI*` stamped into the keystone above *The Wizard's Dial*.
- **The 60 / 40 Crossover Law (Zero Technical Info-Dumps):**
  - **60% Effortless 10-Year-Old Accessibility:** Plain, concrete Anglo-Saxon nouns and physical metaphors (`the stone above the door` instead of `lintel`; `low stone wall` instead of `parapet`; `house brain` instead of `air-gapped LLM cluster`; `bounce-ping` instead of `bidirectional RTT probe`; `the little plastic table that keeps the cheese from sticking to the lid`).
  - **40% Adult/Teen Crossover Depth:** Real distributed-systems, hardware-clock (`Time Thief` NYSE sub-microsecond matching engine), air-gapped security (`Zone One` vs. `Zone Two`), and institutional-incentive mechanics woven into action and character conflict without ever stopping the story for a textbook lecture.
- **Character Voice Differentiation (The Tag-Free Test Across the Locked Cast):**
  - **`ct` (Charlie — `"ct"` at school and online; `"Charlie"` only to `el` in private/casual moments; `"Mr. ct"` to teachers):** Observant, loyal, self-deprecating, intuitive systems thinker; hates bullies; notices small physical tells (the spark at Julian's temple, the look Remi gives her brother's empty stool); feels a real human tug of pride over winning the Salt Hall before choosing equal council weight.
  - **`el` (Elena):** Composed Upper West Side poise with razor-sharp dry wit; can pivot from effortless social charm (*"Oh, Daddy"*) to steel-spined strategist (*"Two couriers. One door."*); never says *I told you so* when `ct` corrects his own mistake.
  - **`Remi` (`Durgan`'s twin sister):** Quiet, surgical, deadpan security realist; measures trust in verifiable hashes, air-gapped lines, and live `*MOLE*` break-in tests (*"For one session. If Anya's monitor shows a single read coming back the wrong way, I pull the plug."*).
  - **`Durgan` (`Remi`'s twin brother):** Brash, kinetic hardware pride (solder, salvaged Xeon blades, his prized sub-microsecond matching board); hungry for elite recognition and visibly stung when `Dr. Lin` or `Halcyon` dismisses his hardware as off-the-shelf surplus.
  - **`Anya`:** Methodical, calm, fiercely organized (`ISOLATED HOST`, velcro cable ties at right angles, frame-by-frame timestamp strips); translates chaotic schemes into clean two-zone architecture (`Zone One` shared play vs. `Zone Two` air-gapped house brain) while reminding the room, *"Remember, some of us are eleven."*
  - **`Jess` (`ct`'s 11-year-old sixth-grade sister):** Deadpan comedic precision, courtroom-lawyer negotiator for half-points and extra chocolate milk, and the crew's natural namer of sacred things (*The Pizza Box*, *The Round Table*, *The Wizard's Dial*, *"Assist my expedition sounds like Mom when she means clean the bathroom while I hold the mop"*).
  - **`Abigail` (`ct` & `Jess`'s Jamaican mother, single parent & hospital nurse):** Warm, sharp, trimmer/energetic, no-nonsense boundary setter (the `B-plus` rule, the three check-in texts) with spunk and humor of her own.
  - **`Julian Thorne` (`GHH` president, senior):** Effortless prep-school command that hardens after his upstate `Halcyon` residency into cold, detached institutional superiority—both hands flat on the desk in plain view while his tinted glasses spark and terminals move by themselves (*"Don't bring a toy key to people who own the lock"*).
- **The 15 Locked *Artificial Magi* Mechanical, Editorial & Structural Laws (`v1`–`v10`):**
  1. **Law 1 (Direct Scene Openings):** Open scenes with direct time/place grounding (`At 3:20 on Tuesday afternoon...`); never stack em-dashes in scene-opening transitions.
  2. **Law 2 (Concrete Plain-English Nouns):** Replace academic/archaic architectural or technical jargon (`lintel`, `parapet`, `cryptographic nonce`) with immediate visual words (`the stone above the door`, `low stone wall`, `one-time key`).
  3. **Law 3 (Tactile Prop Continuity):** Anchor every recurring device in consistent physical details (Durgan's padded black case with two latches; Anya's black velcro straps and label maker; Remi's pocket-sized approval box and ruled notebook).
  4. **Law 4 (Cold-Reader Acronym & Entity Anchoring):** Re-anchor acronyms (`GHH`, `SB2`) and recurring adults (`Marcus Vance`, `Dr. Lin`, `Agent Riley`) with a crisp physical or role reminder when they re-enter after a gap.
  5. **Law 5 (POV-Filtered Descriptions):** Filter every visual and wardrobe detail through `ct`'s live perception, reaction, or dialogue—never as a neutral narrator catalog.
  6. **Law 6 (Single-Speaker Paragraphs & `<= 160–175` Word Ceiling):** Keep 40–50% of lines in dialogue; strictly one speaker per paragraph; split any multi-speaker or montage block over `160–175` words so every comedic and dramatic turn breathes.
  7. **Law 7 (Earned Dialogue Closers):** End scenes and beats on the punchline or physical action; cut explanatory summary tags that repeat what the dialogue just did.
  8. **Law 8 (Immediate Emotional & Thematic Grounding After Set-Pieces):** After a major set-piece (like the Pit tryouts), take one quiet beat at the table for `ct`, `Remi`, and `el` to name the human cost (*"They're not just show-offs. They're bullies."*).
  9. **Law 9 (Strict Punctuation Caps):**
     - Semicolons (`;`): **Zero (`0`) in new/revised prose**. Split into two crisp sentences or use a conjunction.
     - Em-dashes (`—`): **$\le 3$ per 250-word page**.
     - Ellipses (`...`): **$\le 2$ per 250-word page** (hesitation/trailing speech only).
     - `-like` compounds and multi-word poetic compound chains: **Zero (`0`)** (standard grammatical hyphens like `ten-year-old`, `blue-white`, `three-phase` are allowed).
     - Four-Rule Italics Only: (1) formal titles (*AtlasCraft*), (2) named in-world systems/rooms on coinages (*The Pizza Box*, *The Round Table*), (3) exact terminal/screen/plaque readouts (`*I HEARD THE HINGES.*`), (4) rare single-word spoken stress.
  10. **Law 10 (The Two-Stage Causal-Key Weld):** Every major threshold requires both a technical/structural key (Anya's 14-tick hinge balance window + Jess catching the ambiguous `"she"` pronoun rule) and a moral/character key (`ct` deleting the `"Chair"` priority header so Oda, Vesper, and Sable stand as equals).
  11. **Law 11 (Zero Technical Info-Dumps):** Never pause a scene for a multi-sentence lecture on network protocols; dramatize how a hack works through a concrete 1–2 sentence visual image and immediate human consequence.
  12. **Law 12 (Pre-Revision Author-Return Scan & Baseline Preservation):** Before any revision pass, extract 100% of John's `<w:ins>`, `<w:del>`, and `<w:comment>` markup from his returned `.docx`, preserve his exact wording, resolve and strip his temporary editorial comments, and compile native Word Track Changes (`ft.py docx-redline --redline`) on top of the accepted baseline.
  13. **Law 13 (Cold-Reader Zero-Assumed-Context, Named-Extra Economy & Anti-Compression Law):** Never invent disposable named extras (like `"Evan Liu"`) when established recurring minor characters (the two smiley GHH pizza-hack boys from Chapter 3, or the boy whose avatar Julian aged into a 76-year-old grandpa) can carry the thread with rich continuity; never compress a multi-beat set-piece into a 1-paragraph summary.
  14. **Law 14 (Authentic Protocol & Voice Vitality Law):** Stage every set-piece using its authentic in-world rules (e.g., GHH Pit auditions require applicants `Leo`, `Tessa`, and `Eliot` to bring their own original hacks while Julian's glasses spark with both hands flat on the desk and Noah's untended terminal counter-hacks them), pairing warm, witty kid banter with chilling institutional stakes.
  15. **Law 15 (Multi-Thread Interlacing, Multi-Session Threshold Effort, Prop Economy & Organic Caper-Clue Law):**
      - *Interlace Antagonist & School Threads Across Time:* Never clump all Pizza Box scenes into one block and dump GHH at the end of the chapter; weave GHH hallway sightings, locker rumors, and classroom beats naturally across the weeks after the Pit closes.
      - *Multi-Session Effort for Major Thresholds:* When `el` records the translucent white dragon settling into the wall relief and opening the shiny white alabaster door to *The Round Table*, dropping a marker outside/at the threshold cannot bypass the door in a single sentence on Thursday afternoon. Because the alabaster door closes when the dragon leaves, re-opening the dragon door and threading Zone Two's air-gapped decryption relay onto *The Wizard's Dial* must take **two Pizza Box sessions** of real coordination.
      - *Prop & Signifier Economy (No Accidental Chekhov's Guns):* Establish the two pizza-hack boys' black GHH lanyards once or twice as a badge of honor, then stop repeating the lanyard mention in every scene so readers do not mistake the lanyards for a plot device.
      - *Contextual Dialogue Coherence & Organic Caper Clues:* Every line of dialogue at a lunch table or workbench must fit the immediate conversation (never insert an out-of-context speech about GHH's annual prank while staring at a dragon video, and never cut to a 1-paragraph home snippet followed by an abrupt time jump). Deliver the Monday caper clue organically by having the two GHH pizza-hack boys taunt `ct`, `el`, and `Durgan` at lunch for dropping out of the Pit tryouts (*"Wait till you see what we do—enjoy your lunch today, it's not going to be fun in the future"*), which naturally prompts the crew to watch the cafeteria vendor gateway.
- **Canonical Chekhov Workflow & Command Pipeline for *Artificial Magi*:**
  1. **Author-Return Inspection:** Extract `<w:ins>`, `<w:del>`, and `<w:comment>` from John's returned `.docx` (`chapters/returns/CHAPTERS-XX-TO-YY-MANUSCRIPT-vN - jcl edits.docx`) and record every edit/comment in `editorial/EDITORIAL-LEARNING.md`.
  2. **Voice & Structural Pass:** Draft/revise in `.ecgberht/vN_target_manuscript.md` against the 15 Laws above.
  3. **Deterministic Gate (`check_vN.py`):** Verify zero semicolons in revised ranges, paragraph word-count ceiling (`<= 165–175` words), exact preservation of John's line edits, prop economy (e.g., lanyard mention cap), and zero invented named extras.
  4. **Native Word Track Changes Compilation (`ft.py`):**
     ```bash
     python "<path> Foundry/skills/chekhov/scripts/ft.py" docx-redline \
       "chapters/returns/CHAPTERS-01-TO-05-MANUSCRIPT-v4-jcl-accepted.docx" \
       ".ecgberht/v10_target_manuscript.md" \
       "chapters/CHAPTERS-01-TO-05-MANUSCRIPT-v10.docx" \
       --author "Aladdin" --redline
     ```
  5. **6-Seat Beta-Reader + Gandalf Diagnostic & Cross-Family Review:** Run the 6-seat panel (now upgraded with Law 15's Multi-Thread Interlacing & Prop-Economy audit) and land via `steward_code_job.py start --skill chekhov`.

---

## 3. Profile 2: `bright-heart` (*Bright-Heart / Chronicles of the Dragon-Kept* — Upper-YA / Adult Epic SFF)

- **Salvaged Source Lineage:** `<path> and `expert-editor/SKILL.md`.
- **Core Governing Doctrine — *"The Wound Before the Wonder"*:**
  In *Bright-Heart*, mythic grandeur, dragon-keeping awe, and incandescent *lyn* magic never arrive as free spectacle. Every moment of wonder is preceded and purchased by a concrete physical or psychological wound—grief, burned skin, clinical exhaustion, exile, or terror.
- **Multi-POV & Multi-Setting Register Shifts:**
  Unlike single-POV YA, *Bright-Heart* shifts prose rhythm, vocabulary, and sensory filtering to match each POV or focal character:
  1. **Heinrich:**
     - *3D Cerebral-Spark Inventor Wit:* Rapid associative leaps, geometric and mechanical precision, dry self-protective humor (the washcloth comedy beats), and signature exclamations (`"Voot!"`).
     - *Dissociative Trauma Wash-Outs:* When triggered, syntax fractures into stark, clinical, white-noise sensory fragments—sound dropping out, peripheral vision narrowing, hands going numb.
     - *Tender Grief:* Quiet, unguarded simplicity when holding what remains of family and memory.
  2. **Peter:**
     - *Market Haggling & Diplomatic Restraint:* Weighs every word like coin on a scale; observant of posture, boots, and leverage; protective older-brother steadiness masking deep fatigue.
  3. **Elliott:**
     - *Bread-Baking Simplicity $\to$ Incantatory Lyn:* Grounded in tactile domestic craft (flour dust, kneaded dough, oven heat, blistered knuckles) until he channels *lyn*, when the prose rises into rhythmic, elemental, incantatory cadence.
  4. **Pep:**
     - *Hushed Liturgical Whisper:* Speaks and remembers mythology not as academic lore, but as a hushed, intimate family liturgy passed hand-to-hand in the dark.
  5. **Sasha:**
     - *Kinetic Heat:* Short, muscular clauses, immediate physical threat assessment, zero patience for euphemism.
  6. **Snyg:**
     - *Silk Menace:* Unhurried, velvet-gloved courtesy where threat lives entirely in the politeness of the phrasing.
- **Jason Kirk Prose Mechanics (Enforced by `lib/prose.mjs` & Seat 3):**
  1. **Period After Action Beat Before Quote:** Always punctuate a physical action beat with a period, never a comma (`He wiped the blade on his sleeve. "Tell me again."` — **never** `He wiped the blade on his sleeve, "Tell me again."`).
  2. **Punctuation Caps:** Em-dashes $\le 3$/page; ellipses $\le 2$/page; semicolons $\le 1\text{–}2$/chapter; zero `-like` compounds.
  3. **Forbidden Weak Constructions:** Eliminate expletive openings (`"There was a..."`, `"There were..."`), filter verbs (`"He saw"`, `"She heard"`, `"He felt"`), and overused gaze crutches (`"eyes"`, `"look"`, `"gaze"`, `"stared"`). Replace with concrete physical verbs and visceral bodily tells.

---

## 4. Profile 3: `sing-for-the-dead` (*Sing for the Dead* — Adult Literary Sacred Realism in Poetic Prose)

- **Salvaged Source Lineage:** `<path> Projects/Short Stories/.claude/skills/sing-voice/SKILL.md` and `collection-editor/SKILL.md`.
- **Literary Ancestors:** Gerard Manley Hopkins (sprung rhythm, compound forging, *inscape*), James Agee (*Let Us Now Praise Famous Men* sacramental attention to working-class detail), Marilynne Robinson (*Gilead* quiet domestic grace), Cormac McCarthy (elemental parataxis), and Dylan Thomas (cascading oral music).
- **Core Voice Identity:** **Sacred Realism in Poetic Prose.** These stories inhabit the kitchens, hospital corridors, back porches, and weathered churches of ordinary, bruised people—where grief and divine grace occupy the exact same square foot of linoleum.

### The 10 Sacred-Realism Prosody & Voice Laws (NEVER Normalize to Novel Rules)

1. **Multi-Word Hyphenated Compounds (`3–4` per full narrative paragraph — Descriptive Range, Never Reduced):**
   - Forge original 2-, 3-, and 4-plus-word hyphenated compounds that fuse sensation, memory, and theology into a single chord:
     - *2-word:* `soul-spent`, `grief-heavy`, `bone-tired`, `rain-dark`
     - *3-word:* `deep-water-wave`, `soul-spent-lament`, `God-Within-Cries`, `tobacco-stained-knuckle`
     - *4+ word clause-compounds:* `nothing-good-happens-after-two-AM`, `too-late-for-sorry-now`
   - *Editorial Rule:* `3–4` compounds applies as a descriptive range to full narrative paragraphs (never to 1–5 word fragments or short dialogue). **Never reduce existing compounds in editing, and never mechanically insert artificial compounds to meet a quota**—if a narrative section feels flat, note it only as an optional observation for the author.
2. **Liberal Cascading Em-Dashes (`2–4+` per long cascading sentence — NEVER Reduce):**
   - Em-dashes in *Sing for the Dead* are **not** an overused tic to be pruned; in long cascading sentences they are the primary syntactic engine representing breath, self-interruption, memory breaking into the present, and appositive qualification (`—and not the clean kind either, the kind that stays under your fingernails for a week—`). Short 1–5 word fragments (Law 7) stand clean without em-dashes.
3. **Slash Notation (`1–3` per story):**
   - Use unspaced forward slashes (`watching/wondering`, `praying/cursing`, `holding/held`) to capture two simultaneous, indivisible states of mind or spirit.
4. **Unattributed Italicized Interiority:**
   - Let raw interior prayer, shame, or childlike plea surface directly inside the paragraph in italics with zero `"he thought"` attribution.
5. **Parenthetical Emotional Detonations:**
   - Place the most devastating, quietest human truths inside parentheses mid-sentence—as if the narrator can only bear to speak them under their breath.
6. **Semicolons as List-Compression Accelerators:**
   - Use semicolons inside long sentences to stack decades of sensory inventory into a single accelerating breath before snapping shut.
7. **Syncopated Short-Short-LONG Jazz Rhythm:**
   - Alternate 40–60+ word cascading, em-dash-laden sentences with sudden 1–5 word fragments (`Gone now.` `Just like that.` `Not a sound.`).
8. **Communal-Witness `"We / Our"` & Intimate Oral Cadence + Minimal High-Weight Dialogue:**
   - The narrator speaks with the authority of a neighbor who stood at the sink and watched it happen (`"We knew before the sheriff's car turned off the gravel..."`).
   - Dialogue is sparse. Characters do not banter; when someone finally speaks aloud, the sentence lands like a stone dropped down a well.
9. **Unflinching Bluntness as Compassion:**
   - Never sanitize poverty, illness, bodily decay, addiction, or cognitive damage with polite euphemisms. State the physical reality plainly; that unflinching honesty is what makes the subsequent tenderness completely unsentimental and earned.
10. **The Sacred as Material Fact (Zero Narrator Hedging):**
    - When grace intrudes, when the dead are sung for, or when God answers in a kitchen, the narrator states it with the exact same grammatical certainty as the weather or the furniture.
    - **CANONICAL BANNED NARRATOR HEDGE LIST:** Never use **`"as if"`**, **`"it seemed"`**, **`"almost like"`**, **`"almost felt"`**, or **`"he imagined"`** in narrator assertions of a sacred turning point (`BLOCKER`). *(Characters voicing doubt in spoken dialogue or raw italicized interiority remain allowed.)*

---

## 5. Profile 4: `essays` (*Essays Beyond* — Adult Analytical & Philosophical Nonfiction)

- **Salvaged Source Lineage:** `<path> Projects/Essays/.claude/skills/voice/SKILL.md`.
- **Literary Ancestors:** George Orwell, Christopher Hitchens, and appellate legal briefs.
- **Core Architecture (`prosecution` pack):** Every essay and section moves through **`Claim -> Ground -> Illustrate -> Test`**:
  1. **Claim:** State the thesis or section proposition in one declarative sentence with zero throat-clearing.
  2. **Ground:** Establish the mechanism, historical record, or primary-source evidence.
  3. **Illustrate:** Anchor the abstraction in a concrete, memorable real-world case.
  4. **Test:** Steelman the strongest possible counter-argument at full strength and dismantle it on the evidence.
- **Mechanical & Punctuation Laws:**
  - **Sentence Length:** Default **12–25 words**; hard ceiling **40 words**. Follow any 30+ word analytical sentence with a short declarative punch ($\le 10$ words).
  - **Signature Punctuation — The Colon (`:`):** Use the colon as the primary fulcrum between setup and verdict (`The institution did not fail by accident: it functioned exactly as its incentives demanded.`).
  - **Banned Habits:** Zero throat-clearing (`"In this essay I will argue..."`, `"Throughout history..."`), zero double-hedges (`"might perhaps"`, `"could arguably"`), and zero passive-voice evasion of agency.
