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
| **POV & Narrative Distance** | Close-third single POV (`ct`) anchored in Arthur | Multi-POV close-third (`ct`) with sharp register shifts per POV | Communal-witness `"we/our"`, intimate `"I"`, or close-third with oral storytelling cadence | Direct first/editorial voice (`"I"` / forensic declarative) |
| **Hyphenated Compounds** | **BANNED (`-like` & poetic chains):** Zero `-like` compounds or multi-word poetic compound chains (standard grammatical hyphens like `ten-year-old` allowed) | **BANNED (`-like` & poetic chains):** Zero `-like` compounds or multi-word poetic chains (standard grammatical hyphens allowed) | **SIGNATURE PROSODY: 3–4 multi-word hyphenated compounds per full narrative paragraph** (`deep-water-wave`, `soul-spent-lament`, `God-Within-Cries`; descriptive range, never reduced in editing) | Standard grammatical hyphenation only |
| **Em-Dash Budget (`—`)** | **Capped at $\le 3$ per page** (250 words) | **Capped at $\le 3$ per page** (250 words) | **LIBERAL CASCADING (`2–4+` per long cascading sentence):** Primary syntactic engine; **NEVER reduce in editing** | Sparingly (prefer colons `:` for pivots) |
| **Semicolons (`;`)** | **BANNED (`0` per chapter)** | **Rare ($\le 1\text{–}2$ per chapter)** | **ACTIVE TOOL:** Used as rapid-fire list-compression accelerators inside long sentences | Allowed for balanced forensic clauses |
| **Slash Notation (`a/b`)** | **BANNED** | **BANNED** | **SIGNATURE (`1–3` per story):** Simultaneous mental states (`watching/wondering`) | **BANNED** (except citations/ratios) |
| **Italics Discipline** | **Strict Four-Rule Italics:** (1) book/ship titles, (2) foreign/runic terms on first use, (3) direct silent telepathy/comms, (4) single-word vocal stress (rare). No unattributed floating thoughts. | Attributed deep interiority + *lyn* incantation markers; no unanchored floating italics | **UNATTRIBUTED ITALICIZED INTERIORITY:** Raw inner voice breaking through mid-paragraph without `"he thought"` tags | Emphasis and titles only |
| **Dialogue Ratio & Action Beats** | **40–50% of chapter lines** must be dialogue; crisp banter + tactile workshop beats | Scene-dependent; **period after action beat before quote** (`He set the knife down. "No."` — never a comma) | **Minimal, high-weight dialogue:** Characters speak rarely; when they speak, a single line carries the weight of years | Quoted primary sources and steelmanned objections |
| **Treatment of the Sacred / Wonder** | Magic as discoverable engineering + dangerous institutional mystery | **"The Wound Before the Wonder"** (physical/emotional cost precedes mythic awe) | **The Sacred as Material Fact:** Zero narrator hedging (`"as if"`, `"it seemed"`, `"almost like"`, `"almost felt"`, `"he imagined"` are **BANNED** on narrator sacred beats) | Empirical & philosophical rigor |

---

## 2. Profile 1: `artificial-magi` (*Artificial Magi* — YA 10–14+ Crossover SFF)

- **Salvaged Source Lineage:** `<path> Magi/.claude/skills/magi-voice/SKILL.md` and `expert-editor/SKILL.md`.
- **Core Voice Identity:** Warm, sharp-witted, tactile YA/crossover fantasy-sci-fi where magic is approached with a blue-collar builder's curiosity and friendship is tested against institutional power.
- **The 60 / 40 Crossover Law:**
  - **60% Effortless 10-Year-Old Accessibility:** Concrete Anglo-Saxon nouns, physical comedy, workshop sparks, food, embarrassment, and immediate personal loyalty (`Scale 1`).
  - **40% Adult/Teen Crossover Depth:** Layered systems engineering, institutional economics, and subtle epistemic clues that reward older readers without ever stopping the story for an abstract lecture.
- **Mechanical & Punctuation Laws:**
  1. **Close-Third POV (`ct`):** Everything in the scene is filtered through Arthur's physical senses, working-class builder background, and immediate emotional stake.
  2. **40–50% Dialogue Ratio:** Keep scenes moving through brisk three-way dialogue among Arthur, Sterling, and Miranda. Break up any workshop or lore paragraph longer than 5 lines with dialogue or physical action.
  3. **Punctuation Caps:**
     - Em-dashes (`—`): **$\le 3$ per 250-word page**.
     - Ellipses (`...`): **$\le 2$ per 250-word page** (only for trailing speech).
     - Semicolons (`;`): **Zero (`0`)**. Split into two crisp sentences or use a conjunction.
     - `-like` compounds (`metallic-like`, `web-like`) and multi-word poetic compound chains: **Zero (`0`)**. Use a concrete metaphor or direct adjective (standard grammatical hyphenation like `ten-year-old`, `two-day`, or `blue-white` is allowed).
  4. **Four-Rule Italics Only:** Use italics solely for (1) formal titles, (2) first-use foreign/runic terms, (3) direct runic/device text, or (4) rare single-word spoken stress. Never use floating unattributed italicized thoughts.
  5. **Craft-Matched Props:** Every character's tools and metaphors must match their actual trade (e.g., herbalists handle shears, drying racks, and tincture vials; artificers handle calipers, flux, and copper wire).
- **Character Voice Differentiation (Tag-Free Test):**
  - **Arthur:** Practical, observant, self-deprecating humor; thinks in load-bearing joints, heat, solder, and household budgets.
  - **Sterling:** Dry, composed, precision-cut syntax; understated aristocratic irony that cracks only when his loyalty to his friends is threatened.
  - **Miranda:** Kinetic, rapid-fire, intuitive; cuts straight through procedural excuses to the emotional or physical weak point.

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
