/**
 * Salvage index (decision 1: SALVAGE THE TEXT, REWRITE THE ORCHESTRATION).
 *
 * The four project-local .claude/skills sets, listed by file path (relative to
 * each project root) and section heading, as READ-ONLY CITED TEXT. Their
 * orchestration is REPLACED by the engine — never a fifth SKILL.md.
 *
 * NO runtime command reads these files: this module is pure data, imports no
 * fs, and is imported by no runtime module (a source-grep test enforces both).
 * Packs and profiles in Phase 3 cite them by section.
 */

export const SALVAGE_INDEX = Object.freeze({
  schema: 'chekhov-salvage-index-v1',
  frozen: true,
  note: 'read-only cited TEXT; the engine replaces the orchestration; Phase-3 packs and profiles cite sections from here',
  sets: Object.freeze([
    Object.freeze({
      root: 'artificial-magi',
      count: 5,
      skills: Object.freeze([
        Object.freeze({
          file: '.claude/skills/cascade-writer/SKILL.md',
          title: 'Cascade Writer — Production System for Artificial Magi',
          headings: Object.freeze(['Trigger', 'Session Start Protocol', 'The Production Pipeline', 'Phase 0: Bible Review & Iteration (CRITICAL — Unique to Artificial Magi)', 'Phase 2: Book Outlines', 'Phase 3: Beat Sheets', 'Phase 4: Draft Prose']),
        }),
        Object.freeze({
          file: '.claude/skills/expert-editor/SKILL.md',
          title: 'Expert Editor: Artificial Magi Series',
          headings: Object.freeze(['The Role', 'Core Editorial Principles (YA Edition)', 'The Editorial Checklist', 'The AI-as-Magic Allegory', 'YA-Specific Standards', 'Working with J.C. Liechty', 'Quick Reference: The Series']),
        }),
        Object.freeze({
          file: '.claude/skills/magi-voice/SKILL.md',
          title: 'Artificial Magi Voice Guide',
          headings: Object.freeze(['1. The Signature Voice', '2. Character Voice Registers', '3. Voice Registers by Setting', '4. Punctuation and Mechanics', '5. Dialogue Rules', '6. Mandatory Preservations (Series Signatures)', '7. Watch For (Common Pitfalls)']),
        }),
        Object.freeze({
          file: '.claude/skills/story-engine/SKILL.md',
          title: 'Artificial Magi: Story Engine (Dual-Engine Structural Framework)',
          headings: Object.freeze(['Core Principle', 'The Two Engines', 'Multi-Scale Application', 'Thematic Architecture: AI-as-Magic Allegory', 'Dual-Engine Analysis Template', 'Dominance Rules', 'Humor as Structural Element']),
        }),
        Object.freeze({
          file: '.claude/skills/storytelling-craft/SKILL.md',
          title: 'Storytelling Craft — Universal Writing Framework',
          headings: Object.freeze(['Trigger', 'I. Four-Part Pacing (J. Scott Savage)', 'II. The Dynamic Quartet', 'III. Scene/Sequel Micro-Pacing (Dwight V. Swain)', 'IV. Jungian Shadow Integration for Storytelling', 'V. Hemispheric Storytelling (Right Brain / Left Brain)', 'VI. Magic Systems']),
        }),
      ]),
    }),
    Object.freeze({
      root: 'bright-heart',
      count: 5,
      excluded: Object.freeze([
        Object.freeze({
          file: '.claude/skills/anchor/SKILL.md',
          reason: 'the Anchor life-dashboard agent, not a writing skill-set — outside decision 1',
        }),
      ]),
      skills: Object.freeze([
        Object.freeze({
          file: '.claude/skills/brightheart-voice/SKILL.md',
          title: 'Bright-Heart Voice: The Writing Style of J.C. Liechty',
          headings: Object.freeze(['Trigger', "The Author's Signature", 'Voice Characteristics (Universal)', 'Voice Registers by Character POV', 'Voice Registers by Setting and Mode']),
        }),
        Object.freeze({
          file: '.claude/skills/cascade-writer/SKILL.md',
          title: 'Cascade Writer — Production System for Chronicles of the Dragon-Kept',
          headings: Object.freeze(['Trigger', 'Session Start Protocol', 'Storage Paths (All Within BrightHeart Directory)', 'The Production Pipeline', 'Phase 2: Book Outlines']),
        }),
        Object.freeze({
          file: '.claude/skills/expert-editor/SKILL.md',
          title: 'Expert Writer and Editor Role',
          headings: Object.freeze(['Trigger', 'The Role', 'Core Principles', 'Editorial Framework', 'The Trauma Allegory']),
        }),
        Object.freeze({
          file: '.claude/skills/storytelling-craft/SKILL.md',
          title: 'Storytelling Craft — Universal Writing Framework',
          headings: Object.freeze(['Trigger', 'I. Four-Part Pacing (J. Scott Savage)', 'II. The Dynamic Quartet', 'III. Scene/Sequel Micro-Pacing (Dwight V. Swain)', 'IV. Jungian Shadow Integration for Storytelling']),
        }),
        Object.freeze({
          file: '.claude/skills/three-rivers/SKILL.md',
          title: 'Three-River Synthesis — Structural Framework for Chronicles of the Dragon-Kept',
          headings: Object.freeze(['Trigger', 'The Core Synthesis: Three Rivers Running Simultaneously', 'The Dual-Engine Model', 'Multi-Scale Application', 'The Trauma Allegory Architecture']),
        }),
      ]),
    }),
    Object.freeze({
      root: 'sing-for-the-dead',
      count: 4,
      skills: Object.freeze([
        Object.freeze({
          file: '.claude/skills/collection-editor/SKILL.md',
          title: 'Collection Editor — Sing for the Dead',
          headings: Object.freeze(['The Role', 'Core Editorial Principles', 'The Editorial Workflow for Each Story', 'Competition and Submission Strategy', 'The "Stretch" Exercise — Analyzing Other Authors']),
        }),
        Object.freeze({
          file: '.claude/skills/collection-writer/SKILL.md',
          title: 'Collection Writer — Production System for Sing for the Dead',
          headings: Object.freeze(['Session Start Protocol', 'The Production Pipeline', 'The Stretch Exercise', 'The Editorial Workflow', 'Collection-Level Thinking']),
        }),
        Object.freeze({
          file: '.claude/skills/eddy-engine/SKILL.md',
          title: 'The Eddy — Structural Framework for Sing for the Dead',
          headings: Object.freeze(['What This Is (and What It Is Not)', 'The Four Movements', 'Section Breaks as Musical Movements', 'Structural Patterns Across the Collection', 'Diagnosing Structural Problems']),
        }),
        Object.freeze({
          file: '.claude/skills/sing-voice/SKILL.md',
          title: 'Sing Voice — Prose Style Guide',
          headings: Object.freeze(['The Signature Voice', 'The Mechanical Toolkit', 'Rhythm and Music', 'The Narrator', 'The Sacred as Material Fact']),
        }),
      ]),
    }),
    Object.freeze({
      root: 'essays',
      count: 5,
      skills: Object.freeze([
        Object.freeze({
          file: '.claude/skills/design-style/SKILL.md',
          title: 'Design & Submission Formatting',
          headings: Object.freeze(['Publication Targets & Requirements', 'Standard Formatting Specifications', 'Citation Style: Chicago Notes-Bibliography', 'Submission Checklist']),
        }),
        Object.freeze({
          file: '.claude/skills/expert-editor/SKILL.md',
          title: 'Expert Editor: Argumentative Nonfiction',
          headings: Object.freeze(['Editorial Philosophy', 'Editing Phases', 'Fact-Check Template', 'Feedback Framework']),
        }),
        Object.freeze({
          file: '.claude/skills/production/SKILL.md',
          title: "Essay's Beyond — Production Orchestrator",
          headings: Object.freeze(['Pipeline Overview', 'Phase 0: Research & Bible', 'Phase 1: Outline', 'Role in The Prosecution']),
        }),
        Object.freeze({
          file: '.claude/skills/structure/SKILL.md',
          title: 'The Prosecution — Structural Architecture',
          headings: Object.freeze(['The Core Metaphor', 'Collection-Level Structure', 'Individual Essay Structure', 'Cross-Essay Architecture', 'Structural Decisions Checklist']),
        }),
        Object.freeze({
          file: '.claude/skills/voice/SKILL.md',
          title: 'Essays Beyond — Voice Skill',
          headings: Object.freeze(['Voice Identity', 'Sentence Architecture', 'Argumentative Technique', 'Tone and Register', 'Mechanical Rules']),
        }),
      ]),
    }),
  ]),
});
