---
name: figure-designer
description: Best-in-class scientific figure design for technical/scientific documents. Trigger BEFORE generating any SVG, PNG, or PDF figure for whitepapers, papers, or technical reports — especially neuroscience, computational neuroscience, ML architecture diagrams, signal/circuit/system schematics, training-loss visuals, or any multi-panel figure where the reader needs to grasp the meaning at a glance. Trigger AGAIN when reviewing a figure before publication. Use when the user asks for "scientific illustration", "neuroscience figure", "architecture diagram", or pushes back on figures being "decorative but not informative".
---

## North Star (LOCKED — John, 2026-08-25)

Every figure that ships is understood at a glance: turns technical intent into best-in-class
visual communication and blocks decorative-but-uninformative figures before they render.

## Sizing (right-size the ceremony — 3 lines)

A quick 2-box diagram gets COMPRESSED ceremony: narrative in one line, build, gate 6
(render-and-look) — no scratch file, no full checklist. A publication or deck figure runs
the full workflow. Narrative-first and gate 6 are never skipped at any size.

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).

**THE SPEAKING LAW (John, 2026-08-16 — ELEGANCE.md Part III):** every ask,
HALT, or summary this skill puts to the user describes the DECISION, never
the machinery (a gate ask took FOUR attempts because it kept narrating waves
and gates); a few plain sentences carrying the two-three details that matter
+ where the full detail lives; genuinely complicated content goes in NUMBERED
BATCHES, one at a time, each ending "OK so far?"; no seat/stamp/gate
vocabulary in the sentence the user must read; every ask ends with a question
answerable in one word AND carries a recommendation (what you would choose +
one line of why + alternatives when the choice has them + "or tell me
something else" — options are a convenience, never a cage).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# figure-designer skill

A protocol for producing publication-quality scientific figures. Distilled from Rougier et al.'s *Ten Simple Rules for Better Figures* (PLOS Comp Bio 2014), Bang Wong's *Points of View* columns in *Nature Methods* (2010-2013), Naomi Altman & Martin Krzywinski's *Points of Significance* columns, the AAAS *Science* figure standards, and recurring conventions in *Nature Neuroscience* / *Neuron* / *Cell* (2020-2025).

**The single hardest-won lesson: never start drawing without a written narrative.** If you skip the narrative, you produce decoration; with the narrative, you produce communication. Every other rule below is downstream of this one.

---

## 1. The non-negotiable workflow

Follow these steps in order. Do not collapse them.

### 1.1 Narrative first (mandatory)

For every figure you intend to produce, write a **short narrative (one paragraph, led by its ONE-SENTENCE takeaway)** answering:

> *What should the reader grasp from this figure in five seconds?*

The narrative goes into a scratch file (e.g. `outputs/figure-narratives.md`) before any SVG/PNG/Python code is touched. The narrative names: the single main message (one sentence, lead with the takeaway), the supporting facts the figure must convey, and why it matters in the surrounding document.

**Get the narratives reviewed and locked — BATCHED per document.** For a multi-figure document,
write ALL the narratives to the scratch file first (the review reads each narrative's LEAD SENTENCE — the takeaway) and present them as ONE set for a
single review/lock ("yes, that's what I want each reader takeaway to be") — never N sequential
per-figure approval round-trips. Only after the set is locked do any sketching/building begin.

### 1.2 Sketch second
Before writing SVG: a 30-second pencil-or-text sketch. Where do the major elements sit? L→R or T→B flow? Which color encodes what? This catches layout problems that are expensive to fix in code.

### 1.3 Build third
Hand-write SVG (preferred) or use Python procedural SVG when many similar elements need rendering. See §5 for tooling guidance.

### 1.4 Verify fourth
Run §6's verification gates before declaring the figure done. Most failures hide in steps that look complete.

### 1.5 Iterate
Show the figure to a reader (or simulate one). If they can't recover the narrative from the figure alone in 5 seconds, the figure has failed. Fix and re-verify.

---

## 2. The ten conventions

### 2.1 One main message per figure
*Why:* Reader attention is finite; multiple competing messages produce zero retained messages.
*How:* If a figure has more than one takeaway, split into multiple panels (a/b/c) — never overlay.

### 2.2 Information hierarchy by visual weight
*Why:* The biggest, brightest element is read first whether you want it to or not.
*How:* Render the main message at largest size and highest contrast; subordinate everything else.

### 2.3 Color encodes meaning, not decoration
*Why:* Every additional color costs a memory slot. Spend the budget on semantics.
*How:* Pick a fixed palette where each color means one thing throughout the figure set. Reuse the same colors across figures so the reader builds a vocabulary. Keep the palette to 5-7 hues (Wong 2011, Nature Methods).

### 2.4 Typography: sans-serif, ≥ 9 pt at print, italics for variables
*Why:* Fonts smaller than 9 pt are illegible at column width; serif fonts at small sizes break up.
*How:* `font-family: Inter, Helvetica, Arial, sans-serif`, `font-size: 11-14 px` for body, italics only for mathematical variables.

### 2.5 Labels in figure, captions in text
*Why:* The figure must be self-contained at a scan; the caption explains in detail.
*How:* Every concept the figure references gets a short in-figure label. The caption explains what the labels mean. Never put narrative-length text inside the figure.

### 2.6 Self-contained terminology — every acronym defined inline
*Why:* The figure may be viewed out of context (slide, social-media share, isolated panel).
*How:* The first use of any acronym (LoRA, MoE, LLM, ...) gets an inline gloss in the figure. Even one word ("LoRA: low-rank adapter") is enough.

### 2.7 White space is structural
*Why:* Crowding hides the hierarchy and exhausts the reader.
*How:* 15-20% padding around the canvas. 8-12 px gap between adjacent elements. If a figure looks "full," delete something.

### 2.8 Process flow has a direction — pick one and keep it
*Why:* Mixed flow direction in the same figure doubles the cognitive load.
*How:* Choose left-to-right (preferred for English-language readers) or top-to-bottom. Hold it for the whole figure.

### 2.9 Text on colored backgrounds uses paint-order stroke
*Why:* Black text on a dark fill or white text on a light fill is unreadable; gradient backgrounds make this worse.
*How:* In SVG, `style="paint-order: stroke; stroke: #fff; stroke-width: 3; stroke-linejoin: round"` puts a white halo behind black text (or vice-versa). Use this for any text inside a colored region.

### 2.10 Panel labels: bold sans-serif, top-left, consistent
*Why:* Multi-panel figures need consistent navigation; readers expect "a, b, c" upper-left in that order.
*How:* `**a**` `**b**` `**c**` in 14-16 pt bold, top-left of each panel, no period after the letter (Wong 2010).

---

## 3. Color contract — the recommended palette

Use this palette across an entire figure set. Each role gets ONE color; the color does not mean anything else anywhere.

| Role | Hex | Notes |
|---|---|---|
| Primary semantic A (e.g. fast / Taste / System-1) | `#C44F2A` | warm coral; pair with `#FBE0D0` for fills |
| Primary semantic B (e.g. slow / Reasoning / System-2) | `#4A7DB0` | cool blue; pair with `#DCE8F5` for fills |
| External / outside-the-system | `#4FA869` | green; pair with `#DAEEDC` for fills |
| Decision / arbitration / shared | `#D4A858` | gold; pair with `#F8E8C8` for fills |
| Infrastructure / orchestration | `#5A6573` | slate; pair with `#E0E4E9` for fills |
| Neutral ink | `#1F2225` | for body text |
| Neutral ink-light | `#5A5F66` | for subtitles / annotations |

**Colorblind safety.** Inspired by Wong's colorblind-safe palette principles and sanity-checked against ColorBrewer-style guidance (these hexes are this skill's own set — NOT Wong's 8 values; check any new color yourself with a CVD simulator). For deuteranopia and protanopia (the two most common forms), warm/cool/green/gold remain distinguishable. Avoid red+green as the only encoding for a categorical distinction. Do not use rainbow / jet / hsv colormaps for sequential data; use viridis, magma, cividis, or single-hue sequential palettes.

---

## 4. Patterns for neuroscience and architecture figures

**4.1-4.2 Neuroscience-only patterns (schematic neuron; brain region map)** — moved to
`references/READING-AND-DOMAIN-PATTERNS.md` (2026-08-25); load when doing neuro figures.


**4.3 Signal / process flow with parallel tracks.** L→R flow. Each track is one horizontal lane. Use connecting lines (`<path>` with `marker-end`) of consistent stroke width across tracks. Conditional routing (e.g. "if confidence > θ, skip the next track") gets a labeled diamond or hexagon at the branch point.

**4.4 Training / loss diagram.** Show the loss as: source(s) → comparator → target. Annotate the comparator with the actual loss function (`cross-entropy`, `MSE`, `KL`). For per-cell or per-module loss, render modules as a stack with one loss per module, each loss labeled with its target.

**4.5 Multi-panel figures.** Panel labels (a/b/c) bold top-left. Panels share the same color contract. Panels share the same axis ranges where comparable. Captions name each panel.

---

## 5. Tooling guidance

| Tool | Use for | Avoid for |
|---|---|---|
| Hand-written SVG | Final figures, anything with bespoke layout | Data-driven plots |
| Python procedural SVG | Many similar elements (texture, grids, clusters) | One-off layout |
| matplotlib | Real data plots only | Architecture diagrams |
| Mermaid | Org charts, state machines where layout doesn't need control | Anything where exact positioning matters |
| ImageMagick `convert` | SVG → PNG rasterization at 150 dpi for PDF embed | Anything requiring vector output |
| pandoc + xelatex | Markdown → PDF (via PNG references) | Markdown with raw SVG → PDF (xelatex needs rsvg-convert which is often missing) |
| LibreOffice `soffice --headless` | Markdown → DOCX → PDF when xelatex misses chars | Reproducible builds (flaky on large docs) |

**PDF pipeline fallback (general recipe):** pandoc generates DOCX from markdown directly with SVG references (works). For PDF: convert SVG → PNG via `convert -density 150`, sed-substitute markdown references to PNG paths, run pandoc with `--pdf-engine=xelatex`. This avoids the rsvg-convert / soffice failure modes. (Project-specific build recipes belong in that project's docs, not here.)

---

## 6. Verification gates — before declaring done

Run every gate. A failed gate means the figure is not done.

1. **Narrative still accurate?** Open the locked narrative. Does the figure deliver it in 5 seconds without reading the caption? If no, the figure is wrong, not the narrative.
2. **Self-contained?** Every acronym defined inline. Every label readable. No reference to "see Fig X" required to understand this figure.
3. **Contrast?** Every text element passes WCAG AA contrast on its background. Use paint-order stroke for text on colored fills.
4. **Color encoding consistent?** Each color means one thing in this figure AND across the figure set. No accidental reuse.
5. **Panels titled and labeled?** Multi-panel: a/b/c top-left, panel titles short.
6. **RENDER IT AND LOOK AT IT — the gate that closes the 4×-recurred clipped-figure class
   (John's Verification Law rule 6; wired 2026-08-25).** Render the figure AT DELIVERY SIZE
   (the size it will appear in the deck/paper, not a zoomed preview), open the rendered
   image, and LOOK: nothing clipped, nothing overflowing, no collisions, axes complete,
   every label legible at that size. An assertion or parse cannot see a clipped axis —
   only eyes on the rendered image can. This gate is mandatory; a figure nobody looked at
   is not done.
7. **SVG parses as XML? (a LINT, not the done-gate — relabeled 2026-08-25)**
   `python3 -c "import xml.etree.ElementTree as ET; ET.parse('FILE.svg')"`. Structure
   checks are lints; gate 6 is the gate. File size for hand-crafted figures is a SMELL:
   well under ~8 KB often means under-detailed, well over ~35 KB often means
   over-decorated — but judge the content, not the byte count.
8. **Caption written and ≤ 150 words?** Caption explains what's in the figure; doesn't repeat what the figure shows visually.

---

## 7. Anti-patterns — these are bugs, fix them

- **Rainbow / jet colormaps for sequential data.** Use viridis or single-hue sequential.
- **3D pie charts, 3D bars, drop shadows, gradient backgrounds.** All decorative; none informative.
- **Procedural-noise texture on anatomical regions** (e.g. random wavy strokes "for gyri"). Adds clutter, conveys nothing.
- **Encoding the same dimension with shape AND color.** Pick one channel.
- **Decorative neurons.** A schematic rectangle with five labeled stages communicates more than a hand-drawn neuron with twenty unlabeled organelles.
- **Mystery acronyms.** First-use definition inside the figure.
- **Tiny text.** ≥ 9 pt at print = ≥ 11 px in screen SVG.
- **Crowding.** If you can't add 15% padding without overflowing, you have too many elements; remove some.
- **"Looks scientific" without saying anything.** Every visual element must answer "what is this telling the reader?"

---

## 8. Recommended reference set

Moved to `references/READING-AND-DOMAIN-PATTERNS.md` (2026-08-25 — ~14 lines of URLs
were loading on every run; zero capability change).

## 9. The narrative template (copy-paste this)

```
# Figure narratives — [project name]

## Figure 1 — [short slug]
**5-second reader takeaway:** [one sentence — lead with the takeaway, not the topic]
**Supporting facts:** [3-5 bullets]
**Why this matters:** [one sentence about its role in the document]
**Visual encoding contract:**
- L→R or T→B flow: [pick one]
- Color encoding: [list each color and what it means]
- Acronyms to define inline: [list]
```

Lock this with the user before drawing anything.

---

## 10. Provenance

Authored 2026-05-05 in response to John Liechty's directive: *"go and look at a few years of paper from Nature and Science on neural science and see what their figures look like (they do a good job). Learn and come back with an image developer skill file."* Distilled from the canonical references in §8.

If a future user objects that figures produced under this skill still feel decorative, the most likely failure is step 1.1 — the narrative was skipped or vague. Re-do that step before re-rendering.

> **⏱ STATUS UPDATES TO CHAT:** When running long phases in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s) and provide scheduled updates to the user in the LOCKED Status-table format — canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

## Usage journal + run capture

After every REAL run: append one `NNNN-<slug>.md` entry to `journal/`, and write the
machine-readable training record to `journal/runs/<ts>.json` per the canonical standard in
Skill Foundry `AGENTS.md` → "Run capture".

**The 7 canonical fields** (defined HERE — 2026-08-25 fix: this section and journal/README.md
each pointed at the other and neither defined them, so the mandate could not be followed):

- `id`: `NNNN-<slug>` (max existing NNNN + 1 — never reuse a number)
- `skill`: `figure-designer@<date>`
- `situation`: what was asked, one line
- `context`: where it ran (deck/paper, host, delivery size)
- `observation`: what happened — incl. what gate 6 (render-and-look) caught or confirmed
- `outcome`: worked / failed / partial, with the honest reason
- `provenance`: `genuine-execution` (a real run) — never write entries for imagined runs
